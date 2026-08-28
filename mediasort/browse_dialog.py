"""Open/Browse dialog: pick files to view by folder, tag, or both,
optionally filtered by media type.

Layout: three sections side by side.
  1. Folder picker - "Browse folder" checkbox switches the whole panel
     on/off.  When on, a folder value is REQUIRED; the
     Relative/History/Favourites list feeds the always-editable path
     field using the same selection logic as the copy/move dialog (list
     selection writes into the field, manual edits never propagate back,
     re-selecting overwrites, and confirmation always uses the field).
     When off, the rest of the panel is disabled.
  2. Tag picker - "Browse tag" checkbox switches the whole panel on/off.
     When on, at least one tag is REQUIRED; one or more tags can be
     selected from the list (Ctrl/Shift+click).  The "Suma (OR) /
     Część wspólna (AND)" toggle decides how multiple tags combine:
     OR shows every file carrying ANY of them, AND only files carrying
     ALL of them (a single selected tag behaves the same either way).
     When off, the rest of the panel is disabled.
  3. Media type filter - Images and videos / Images only / Videos only.

At least one of the two checkboxes must be checked.  With only the folder
checkbox, all files in that folder (optionally including subfolders) are
shown; with only the tag checkbox, every file matching the tag selection
(union or intersection, per the toggle); with both, only files that are
BOTH in the folder AND match the tag selection.

The dialog remembers its state (checkboxes, folder mode/path, tag, type
filter) between opens within one application run.  When the app restarts,
the state resets to: only "Browse folder" checked, folder mode relative,
folder set to the current folder.
"""
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QLineEdit, QPushButton, QLabel, QGroupBox, QRadioButton, QButtonGroup,
    QMessageBox, QCheckBox, QAbstractItemView
)
from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QKeyEvent, QMouseEvent

from .key_utils import matches_any, shortcut_label
from .file_scanner import scan_media, scan_media_recursive, kind_for_path
from .folder_list import FolderListController
from .i18n import tr, tr_plural
from . import styles

# Session-scoped state of the browse dialog: preserved between opens
# within one app run, discarded when the app exits (never written to
# settings.json, so restarting the app resets to the initial state).
_SESSION_STATE = None


def _default_session_state(current_folder):
    """Initial state for a fresh application run."""
    return {
        "browse_folder": True,
        "browse_tag": False,
        "folder_mode": "relative",
        "folder_path": "",
        "include_subfolders": False,
        "tags": [],            # selected tag names (one or more allowed)
        "tag_combine": "or",   # how multiple tags combine: "or" | "and"
        "type_filter": "both",
    }


class BrowseDialog(QDialog):
    def __init__(self, current_folder, settings, tags_db, parent=None):
        super().__init__(parent)
        self.current_folder = str(Path(current_folder).resolve())
        self.settings = settings
        self.tags_db = tags_db

        self.confirmed = False
        self.result_items = []     # list of (path, kind) once confirmed
        self.result_folder = None  # folder to adopt as MainWindow.folder, or None

        # Restore the previous state from this app run, if any.
        self._session = _default_session_state(self.current_folder)
        if _SESSION_STATE is not None:
            self._session = dict(_SESSION_STATE)

        self.setWindowTitle(tr("browse_dialog.title"))
        self.resize(1020, 580)
        self.setStyleSheet(styles.DIALOG)

        # Shortcut labels for the UI texts, filled from the configured
        # "file_dialog" key bindings (first trigger of each action).
        self._shortcuts = self._shortcut_labels()

        self._build_ui()

        # Shared folder-list browsing (Relative / History / Favourites).
        self.folder_list_ctrl = FolderListController(
            self.folder_list, self.folder_mode_label, self.settings,
            mode_label_key="browse_dialog.mode_label",
        )
        self.folder_list_ctrl.on_select = self._on_folder_selected
        self.folder_list_ctrl.mode = self._session["folder_mode"]
        # Relative mode lists the folders at the same level as the current
        # folder and auto-selects it; restoring a previous folder path
        # re-points the relative view at that folder.
        self.folder_list_ctrl.set_context(
            self._session["folder_path"] or self.current_folder
        )

        # Restore checkbox / option states.  The toggled handlers enable
        # or disable the rest of each panel, so they must run after the
        # UI exists.  setChecked() only emits toggled when the state
        # actually changes, so also apply the enabled states explicitly.
        self.browse_folder_cb.setChecked(self._session["browse_folder"])
        self.browse_tag_cb.setChecked(self._session["browse_tag"])
        self.include_subfolders_cb.setChecked(self._session["include_subfolders"])
        self._set_type_filter(self._session["type_filter"])
        self._apply_folder_enabled()
        self._apply_tag_enabled()

        # Restore the previous folder selection.  In relative mode the
        # context-based auto-select already picks the restored folder; in
        # History/Favourites the current folder is never auto-selected, so
        # re-select the restored path explicitly (when it is in the list).
        restored_folder = self._session["folder_path"] or self.current_folder
        self.folder_list_ctrl.reload(
            select_path=restored_folder if self.folder_list_ctrl.mode != "relative" else None,
            auto_select=self.browse_folder_cb.isChecked(),
        )
        self._reload_tag_list()
        for name in self._session.get("tags") or []:
            for row in range(self.tag_list.count()):
                if self.tag_list.item(row).data(Qt.UserRole) == name:
                    self.tag_list.item(row).setSelected(True)
                    break
        self._set_tag_combine(self._session.get("tag_combine", "or"))
        self.location_edit.setText(restored_folder)
        self._update_match_count()

    def _shortcut_labels(self):
        """Shortcut placeholder values for the UI texts, taken from the
        configured "file_dialog" key bindings (first trigger per action).
        The open action is the plain Return key and is not configurable."""
        fd = self.settings.get("file_dialog", default={})
        return {
            "enter_key": "Enter",
            "cancel_key": shortcut_label(fd.get("cancel", ["Escape"])),
            "edit_key": shortcut_label(fd.get("edit_location", ["F2"])),
            "relative_key": shortcut_label(fd.get("mode_relative", ["R"])),
            "history_key": shortcut_label(fd.get("mode_history", ["H"])),
            "favourites_key": shortcut_label(fd.get("mode_favourites", ["F"])),
        }

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        outer = QVBoxLayout(self)

        columns = QHBoxLayout()
        outer.addLayout(columns, 1)
        self._build_folder_column(columns)
        self._build_tag_column(columns)
        self._build_type_column(columns)

        self.match_label = QLabel(self)
        self.match_label.setStyleSheet(styles.BOLD_LABEL)
        outer.addWidget(self.match_label)

        btn_row = QHBoxLayout()
        self.open_btn = QPushButton(tr("browse_dialog.open_btn", **self._shortcuts), self)
        self.open_btn.setDefault(True)
        self.open_btn.clicked.connect(self._confirm)
        self.cancel_btn = QPushButton(tr("browse_dialog.cancel_btn", **self._shortcuts), self)
        self.cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.open_btn)
        btn_row.addWidget(self.cancel_btn)
        outer.addLayout(btn_row)

        hint = QLabel(
            tr("browse_dialog.hint", **self._shortcuts),
            self,
        )
        hint.setStyleSheet(styles.HINT)
        hint.setWordWrap(True)
        outer.addWidget(hint)

    def _build_folder_column(self, columns):
        col = QVBoxLayout()
        columns.addLayout(col, 2)

        self.browse_folder_cb = QCheckBox(tr("browse_dialog.browse_folder_cb"), self)
        self.browse_folder_cb.setToolTip(tr("browse_dialog.browse_folder_tooltip"))
        self.browse_folder_cb.toggled.connect(self._on_folder_browse_toggled)
        col.addWidget(self.browse_folder_cb)

        col.addWidget(QLabel(tr("browse_dialog.folder_label"), self))

        self.folder_mode_label = QLabel(self)
        col.addWidget(self.folder_mode_label)

        # Destination path: a permanently visible, editable field.  It
        # mirrors the selected list item, but the user can type any path
        # into it; typed edits never propagate back to the list.
        self.location_edit = QLineEdit(self)
        self.location_edit.setPlaceholderText(tr("browse_dialog.folder_placeholder"))
        self.location_edit.setToolTip(tr("browse_dialog.folder_tooltip"))
        self.location_edit.installEventFilter(self)
        # Let QLineEdit handle Return itself and react to its dedicated
        # signal.  This is more reliable than relying on the dialog-level
        # event filter: Return can otherwise be consumed by the focused
        # line edit before it reaches the dialog.
        self.location_edit.returnPressed.connect(self._confirm)
        # Keep the match count in sync with whatever the field holds right
        # now - list selections write into it, manual edits too.
        self.location_edit.textChanged.connect(lambda _: self._update_match_count())
        col.addWidget(self.location_edit)

        self.include_subfolders_cb = QCheckBox(tr("browse_dialog.include_subfolders"), self)
        depth = self.settings.get("browse_subfolder_depth", default=1)
        self.include_subfolders_cb.setToolTip(
            tr_plural("browse_dialog.include_subfolders_tooltip", depth, depth=depth)
        )
        self.include_subfolders_cb.toggled.connect(lambda _checked: self._update_match_count())
        col.addWidget(self.include_subfolders_cb)

        self.folder_list = QListWidget(self)
        # Selection change / activation wiring lives in FolderListController.
        self.folder_list.installEventFilter(self)
        col.addWidget(self.folder_list)

        self.clear_folder_btn = QPushButton(tr("browse_dialog.clear_folder_btn"), self)
        self.clear_folder_btn.clicked.connect(self._clear_folder)
        col.addWidget(self.clear_folder_btn)

    def _build_tag_column(self, columns):
        col = QVBoxLayout()
        columns.addLayout(col, 2)

        self.browse_tag_cb = QCheckBox(tr("browse_dialog.browse_tag_cb"), self)
        self.browse_tag_cb.setToolTip(tr("browse_dialog.browse_tag_tooltip"))
        self.browse_tag_cb.toggled.connect(self._on_tag_browse_toggled)
        col.addWidget(self.browse_tag_cb)

        col.addWidget(QLabel(tr("browse_dialog.tag_label"), self))

        self.tag_list = QListWidget(self)
        # One or more tags can be selected (Ctrl/Shift+click, drag).
        self.tag_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tag_list.itemSelectionChanged.connect(self._update_match_count)
        self.tag_list.installEventFilter(self)
        col.addWidget(self.tag_list)

        # How multiple selected tags combine: union (OR) or intersection (AND).
        combine_row = QHBoxLayout()
        self.combine_label = QLabel(tr("browse_dialog.tag_combine_label"), self)
        combine_row.addWidget(self.combine_label)
        self.combine_or_rb = QRadioButton(tr("browse_dialog.tag_combine_or"), self)
        self.combine_or_rb.setToolTip(tr("browse_dialog.tag_combine_or_tooltip"))
        self.combine_or_rb.setChecked(True)
        self.combine_and_rb = QRadioButton(tr("browse_dialog.tag_combine_and"), self)
        self.combine_and_rb.setToolTip(tr("browse_dialog.tag_combine_and_tooltip"))
        combine_group = QButtonGroup(self)
        combine_group.addButton(self.combine_or_rb)
        combine_group.addButton(self.combine_and_rb)
        for rb in (self.combine_or_rb, self.combine_and_rb):
            rb.toggled.connect(lambda checked: self._update_match_count() if checked else None)
            combine_row.addWidget(rb)
        combine_row.addStretch(1)
        col.addLayout(combine_row)

        self.clear_tag_btn = QPushButton(tr("browse_dialog.clear_tag_btn"), self)
        self.clear_tag_btn.clicked.connect(self._clear_tag)
        col.addWidget(self.clear_tag_btn)

    def _build_type_column(self, columns):
        col = QVBoxLayout()
        columns.addLayout(col, 1)

        type_box = QGroupBox(tr("browse_dialog.type_group"), self)
        type_layout = QVBoxLayout(type_box)
        self.radio_both = QRadioButton(tr("browse_dialog.type_both"), type_box)
        self.radio_images = QRadioButton(tr("browse_dialog.type_images"), type_box)
        self.radio_videos = QRadioButton(tr("browse_dialog.type_videos"), type_box)
        self.radio_both.setChecked(True)
        group = QButtonGroup(self)
        for rb in (self.radio_both, self.radio_images, self.radio_videos):
            group.addButton(rb)
            rb.toggled.connect(lambda checked: self._update_match_count() if checked else None)
        type_layout.addWidget(self.radio_both)
        type_layout.addWidget(self.radio_images)
        type_layout.addWidget(self.radio_videos)
        col.addWidget(type_box)
        col.addStretch(1)

    def showEvent(self, event):
        super().showEvent(event)
        if self.browse_folder_cb.isChecked():
            self.folder_list.setFocus()
        elif self.browse_tag_cb.isChecked():
            self.tag_list.setFocus()
        else:
            self.radio_both.setFocus()

    # ------------------------------------------------------------------
    # Folder list (Relative / History / Favourites) - owned by the shared
    # FolderListController; it feeds the always-editable location edit,
    # which is the single source of truth.
    # ------------------------------------------------------------------
    def _on_folder_selected(self, path):
        # Picking a list row overwrites whatever the location edit holds
        # (the list is authoritative while a row is being selected).  The
        # reverse never happens: manual edits leave the list untouched.
        self.location_edit.setText(path)

    def _clear_folder(self):
        # "Clear" turns folder browsing off - the panel (including this
        # button) becomes disabled; re-checking restores the previous
        # folder value.
        self.browse_folder_cb.setChecked(False)

    def _clear_tag(self):
        # "Clear" turns tag browsing off - the panel (including this
        # button) becomes disabled.
        self.browse_tag_cb.setChecked(False)

    # -- "Browse folder" / "Browse tag" checkbox handling ---------------
    def _on_folder_browse_toggled(self, checked):
        self._apply_folder_enabled()
        self._update_match_count()

    def _apply_folder_enabled(self):
        enabled = self.browse_folder_cb.isChecked()
        for w in (self.folder_mode_label, self.location_edit,
                  self.include_subfolders_cb, self.folder_list,
                  self.clear_folder_btn):
            w.setEnabled(enabled)

    def _on_tag_browse_toggled(self, checked):
        self._apply_tag_enabled()
        self._update_match_count()

    def _apply_tag_enabled(self):
        enabled = self.browse_tag_cb.isChecked()
        for w in (self.tag_list, self.combine_label,
                  self.combine_or_rb, self.combine_and_rb,
                  self.clear_tag_btn):
            w.setEnabled(enabled)

    # -- custom location editing ----------------------------------------
    # The location edit is always visible, so "editing" is simply focusing
    # the field and typing over whatever it currently holds.
    def _begin_edit_location(self):
        self.location_edit.setFocus()
        self.location_edit.selectAll()

    # ------------------------------------------------------------------
    # Tag list - every known tag, alphabetically
    # ------------------------------------------------------------------
    def _reload_tag_list(self):
        self.tag_list.blockSignals(True)
        self.tag_list.clear()
        for name in self.tags_db.all_tags():
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, name)
            self.tag_list.addItem(item)
        self.tag_list.blockSignals(False)

    # ------------------------------------------------------------------
    # Combined folder + tag + type filtering
    # ------------------------------------------------------------------
    def _selected_folder(self):
        return self.location_edit.text().strip() or None

    def _selected_tags(self):
        """Return the names of every currently selected tag (may be
        empty; several tags can be selected at once)."""
        return [
            self.tag_list.item(i).data(Qt.UserRole)
            for i in range(self.tag_list.count())
            if self.tag_list.item(i).isSelected()
        ]

    def _tag_combine(self):
        """How multiple selected tags are combined: "or" (union) or
        "and" (intersection). With a single tag both give the same result."""
        return "and" if self.combine_and_rb.isChecked() else "or"

    def _set_tag_combine(self, which):
        self.combine_or_rb.setChecked(which != "and")
        self.combine_and_rb.setChecked(which == "and")

    def _media_type_filter(self):
        if self.radio_images.isChecked():
            return "images"
        if self.radio_videos.isChecked():
            return "videos"
        return "both"

    def _set_type_filter(self, which):
        for rb, name in ((self.radio_both, "both"),
                         (self.radio_images, "images"),
                         (self.radio_videos, "videos")):
            rb.setChecked(name == which)

    def _ext_lists(self):
        image_exts = self.settings.get("image_extensions", default=[])
        video_exts = self.settings.get("video_extensions", default=[])
        type_filter = self._media_type_filter()
        if type_filter == "images":
            return image_exts, []
        if type_filter == "videos":
            return [], video_exts
        return image_exts, video_exts

    def _missing_selection_message(self):
        """Return a user-facing message when the current state cannot be
        confirmed, or None when a valid search can be run."""
        if not self.browse_folder_cb.isChecked() and not self.browse_tag_cb.isChecked():
            return tr("browse_dialog.missing_selection")
        if self.browse_folder_cb.isChecked() and not self._selected_folder():
            return tr("browse_dialog.missing_folder")
        if self.browse_tag_cb.isChecked() and not self._selected_tags():
            return tr("browse_dialog.missing_tag")
        return None

    def _compute_matching_items(self):
        """Returns list of (path, kind), or None when the current state is
        not a valid search (nothing selected, or a required value missing).

        Folder and tag filters only apply when their checkbox is checked;
        when both are checked, only files that match BOTH are returned.
        """
        use_folder = self.browse_folder_cb.isChecked()
        use_tag = self.browse_tag_cb.isChecked()
        if not use_folder and not use_tag:
            return None

        folder = self._selected_folder() if use_folder else None
        tags = self._selected_tags() if use_tag else None
        if use_folder and not folder:
            return None
        if use_tag and not tags:
            return None

        image_exts, video_exts = self._ext_lists()

        folder_items = None
        if folder:
            folder_path = Path(folder)
            if folder_path.exists() and folder_path.is_dir():
                if self.include_subfolders_cb.isChecked():
                    depth = self.settings.get("browse_subfolder_depth", default=1)
                    folder_items = scan_media_recursive(str(folder_path), image_exts, video_exts, max_depth=depth)
                else:
                    folder_items = scan_media(str(folder_path), image_exts, video_exts)
            else:
                folder_items = []

        if tags:
            # Combine the selected tags according to the OR/AND toggle:
            # union ("or") - a file carrying ANY of them matches; or
            # intersection ("and") - a file must carry ALL of them.
            tag_sets = [set(self.tags_db.files_for_tag(name)) for name in tags]
            if self._tag_combine() == "and":
                tag_files = set.intersection(*tag_sets)
            else:
                tag_files = set.union(*tag_sets)
        else:
            tag_files = None

        if folder_items is not None and tag_files is not None:
            return [(p, k) for p, k in folder_items if p in tag_files]
        if folder_items is not None:
            return folder_items
        # tag only
        items = []
        for p in sorted(tag_files):
            kind = kind_for_path(p, image_exts, video_exts)
            if kind is not None:
                items.append((p, kind))
        return items

    def _update_match_count(self):
        message = self._missing_selection_message()
        if message is not None:
            self.match_label.setText(message)
            return
        items = self._compute_matching_items()
        if not items:
            self.match_label.setText(tr_plural("browse_dialog.found_files", 0))
        else:
            self.match_label.setText(tr_plural("browse_dialog.found_files", len(items)))

    # ------------------------------------------------------------------
    def _confirm(self):
        message = self._missing_selection_message()
        if message is not None:
            QMessageBox.warning(self, tr("common.error_title"), message)
            return
        items = self._compute_matching_items()
        if items is None:
            return  # defensive - _missing_selection_message covered it
        self.result_items = items
        self.result_folder = self._selected_folder() if self.browse_folder_cb.isChecked() else None
        self.confirmed = True
        self.accept()

    # ------------------------------------------------------------------
    # Session state: remembered between opens, reset when app restarts.
    # ------------------------------------------------------------------
    def done(self, result):
        self._save_session_state()
        super().done(result)

    def _save_session_state(self):
        global _SESSION_STATE
        _SESSION_STATE = {
            "browse_folder": self.browse_folder_cb.isChecked(),
            "browse_tag": self.browse_tag_cb.isChecked(),
            "folder_mode": self.folder_list_ctrl.mode,
            "folder_path": self.location_edit.text().strip(),
            "include_subfolders": self.include_subfolders_cb.isChecked(),
            "tags": self._selected_tags(),
            "tag_combine": self._tag_combine(),
            "type_filter": self._media_type_filter(),
        }

    # ------------------------------------------------------------------
    # Configurable keyboard / mouse handling
    # ------------------------------------------------------------------
    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress and isinstance(event, QKeyEvent):
            if self._handle_key(event, obj):
                return True
        elif event.type() == QEvent.MouseButtonPress and isinstance(event, QMouseEvent):
            if self._handle_key(event, obj):
                return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event: QKeyEvent):
        if self._handle_key(event, self.focusWidget()):
            return
        super().keyPressEvent(event)

    def _handle_key(self, event, focused_obj) -> bool:
        file_dialog_keys = self.settings.get("file_dialog", default={})

        # While the location edit has focus, let QLineEdit process text
        # input normally.  Enter confirms using the field's current value;
        # Escape cancels the whole dialog.
        if focused_obj is self.location_edit:
            if isinstance(event, QKeyEvent) and event.key() in (Qt.Key_Return, Qt.Key_Enter):
                self._confirm()
                return True
            if matches_any(event, file_dialog_keys.get("cancel", ["Escape"])):
                self.reject()
                return True
            return False

        if matches_any(event, file_dialog_keys.get("edit_location", ["F2"])):
            self._begin_edit_location()
            return True
        if matches_any(event, file_dialog_keys.get("cancel", ["Escape"])):
            self.reject()
            return True

        # R/H/F only switch the folder mode when the tag list doesn't have
        # focus (so typing doesn't clash with Qt's list type-ahead search)
        # and folder browsing is enabled.
        if focused_obj is not self.tag_list and self.browse_folder_cb.isChecked():
            if matches_any(event, file_dialog_keys.get("mode_relative", ["R"])):
                self.folder_list_ctrl.set_mode("relative")
                return True
            if matches_any(event, file_dialog_keys.get("mode_history", ["H"])):
                self.folder_list_ctrl.set_mode("history")
                return True
            if matches_any(event, file_dialog_keys.get("mode_favourites", ["F"])):
                self.folder_list_ctrl.set_mode("favourites")
                return True

        if isinstance(event, QKeyEvent) and event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if (
                self.folder_list_ctrl.mode == "relative"
                and focused_obj is self.folder_list
                and self.folder_list_ctrl.navigate()
            ):
                return True
            self._confirm()
            return True

        return False
