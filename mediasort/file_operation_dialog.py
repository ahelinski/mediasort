"""File operation (copy/move) dialog.

Left side: shows a list of candidate destination folders in one of three
modes - Relative (folders at the same level as the current file's folder,
with the current folder pre-selected), History (recently used
destinations) or Favourites (user-pinned folders). The user can navigate
the list with arrow keys, edit the destination path directly, and confirm
with Copy / Move (or the Enter key, which triggers whichever action the
dialog was opened for).

Right side: a multi-file selection panel. The user picks whether the
operation should apply to the "Zaznaczone" (selected) files or just the
"Biezacy plik" (current file), can invert the selection or select all
files in the folder, and sees a small thumbnail summary of both the
selected and the remaining files.
"""
import os
import shutil
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget,
    QLineEdit, QPushButton, QLabel, QMessageBox, QGroupBox, QRadioButton,
    QButtonGroup, QInputDialog
)
from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QKeyEvent, QMouseEvent

from .key_utils import matches_any, shortcut_label
from .file_scanner import scan_media
from .folder_list import FolderListController
from .i18n import tr
from . import styles
from .selection_preview import SelectionPreviewWidget


def _same_file(path_a, path_b):
    """True when both paths refer to the same existing file - used to
    detect copying/moving a file onto itself, which is a no-op rather
    than a name conflict (the destination defaults to the current folder,
    so this is the common "keep it here" case)."""
    try:
        return os.path.samefile(path_a, path_b)
    except OSError:
        return False


class FileOperationDialog(QDialog):
    def __init__(
        self, current_file, settings, default_action="copy",
        media_items=None, selected_paths=None, tags_db=None, parent=None,
    ):
        super().__init__(parent)
        self.current_file = str(current_file)
        self.settings = settings
        self.tags_db = tags_db  # optional - if given, tags follow moved files
        self.default_action = default_action  # "copy" or "move"
        self.performed_action = None   # set to "copy"/"move" once an operation succeeds
        self.affected_paths = []       # paths actually copied/moved

        # media_items: list of (path, kind) tuples for the whole current folder.
        # selected_paths: a *mutable set* shared with MainWindow - mutations
        # here (invert/select-all) are immediately visible to the caller.
        self.media_items = list(media_items) if media_items else [(self.current_file, "image")]
        self.selected_paths = selected_paths if selected_paths is not None else set()

        titles = {
            "copy": tr("file_dialog.title_copy"),
            "move": tr("file_dialog.title_move"),
        }
        self.setWindowTitle(titles.get(default_action, tr("file_dialog.title_default")))
        self.resize(880, 560)
        # Setting a stylesheet on any single label (even just font-weight)
        # can make Qt stop inheriting the system palette for that widget
        # and fall back to black text, which becomes invisible on a dark
        # OS theme. Give the whole dialog an explicit, theme-independent
        # dark style so every label stays readable regardless of the
        # system palette.
        self.setStyleSheet(styles.DIALOG)

        # Shortcut labels for the UI texts, filled from the configured
        # "file_dialog" key bindings (first trigger of each action).
        self._shortcuts = self._shortcut_labels()

        self._build_ui()

        # Shared folder-list browsing (Relative / History / Favourites).
        self.folder_list_ctrl = FolderListController(
            self.list_widget, self.mode_label, self.settings,
            mode_label_key="file_dialog.mode_label",
        )
        self.folder_list_ctrl.on_select = self._on_folder_selected
        # Relative mode lists the folders at the same level as the current
        # file's folder and auto-selects the current folder itself.
        self.folder_list_ctrl.set_context(Path(self.current_file).resolve().parent)
        self.folder_list_ctrl.reload()

        self._refresh_selection_ui()
        if self.list_widget.currentItem() is None:
            # A non-empty list already fills the location edit (and with it
            # the folder preview) via the selection callback; this covers
            # the edge case where the list has no items at all.
            self._refresh_folder_preview()

    def create(self, /, arg__1: int | None = ..., initializeWindow: bool = ..., destroyOldWindow: bool = ...) -> None:
        super().create(arg__1, initializeWindow, destroyOldWindow)

    def _shortcut_labels(self):
        """Shortcut placeholder values for the UI texts, taken from the
        configured "file_dialog" key bindings (first trigger per action)."""
        fd = self.settings.get("file_dialog", default={})
        return {
            "copy_key": shortcut_label(fd.get("copy", ["Alt+C"])),
            "move_key": shortcut_label(fd.get("move", ["Alt+M"])),
            "invert_key": shortcut_label(fd.get("invert_selection", ["I"])),
            "select_all_key": shortcut_label(fd.get("select_all", ["A"])),
            "relative_key": shortcut_label(fd.get("mode_relative", ["R"])),
            "history_key": shortcut_label(fd.get("mode_history", ["H"])),
            "favourites_key": shortcut_label(fd.get("mode_favourites", ["F"])),
            "edit_key": shortcut_label(fd.get("edit_location", ["F2"])),
            "confirm_key": shortcut_label(fd.get("confirm_action", ["Ctrl+Return"])),
            "fav_key": shortcut_label(fd.get("toggle_favourite", ["Ctrl+D"])),
            "cancel_key": shortcut_label(fd.get("cancel", ["Escape"])),
        }

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        outer = QHBoxLayout(self)

        left = QVBoxLayout()
        outer.addLayout(left, 2)
        self._build_left_panel(left)

        right = QVBoxLayout()
        outer.addLayout(right, 1)
        self._build_selection_panel(right)

    def _build_left_panel(self, layout):
        info = QLabel(tr("file_dialog.current_file", filename=Path(self.current_file).name), self)
        info.setStyleSheet(styles.DIALOG)
        layout.addWidget(info)

        self.mode_label = QLabel(self)
        layout.addWidget(self.mode_label)

        # Destination path: a permanently visible, editable field.  It
        # mirrors the selected list item, but the user can type any path
        # into it; typed edits never propagate back to the list.
        self.location_edit = QLineEdit(self)
        self.location_edit.setPlaceholderText(tr("file_dialog.location_placeholder"))
        self.location_edit.setToolTip(tr("file_dialog.location_tooltip"))
        self.location_edit.installEventFilter(self)
        # Let QLineEdit handle Return itself and react to its dedicated
        # signal.  This is more reliable than relying on the dialog-level
        # event filter: Return can otherwise be consumed by the focused
        # line edit before it reaches the dialog.
        self.location_edit.returnPressed.connect(self._perform_edited_location)
        # Keep the "Folder" preview in sync with whatever the field holds
        # right now - list selections write into it, manual edits too.
        self.location_edit.textChanged.connect(lambda _: self._refresh_folder_preview())
        layout.addWidget(self.location_edit)

        self.list_widget = QListWidget(self)
        # Selection change / activation wiring lives in FolderListController.
        self.list_widget.installEventFilter(self)
        layout.addWidget(self.list_widget)

        btn_row = QHBoxLayout()
        self.copy_btn = QPushButton(tr("file_dialog.copy_btn", **self._shortcuts), self)
        self.move_btn = QPushButton(tr("file_dialog.move_btn", **self._shortcuts), self)
        self.fav_btn = QPushButton(tr("file_dialog.fav_btn"), self)
        self.copy_btn.clicked.connect(lambda: self._perform("copy"))
        self.move_btn.clicked.connect(lambda: self._perform("move"))
        self.fav_btn.clicked.connect(self._toggle_favourite_current)
        default_buttons = {"copy": self.copy_btn, "move": self.move_btn}
        default_buttons.get(self.default_action, self.copy_btn).setDefault(True)
        btn_row.addWidget(self.copy_btn)
        btn_row.addWidget(self.move_btn)
        btn_row.addWidget(self.fav_btn)
        layout.addLayout(btn_row)

        hint = QLabel(
            tr("file_dialog.hint", **self._shortcuts),
            self,
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(styles.HINT)
        layout.addWidget(hint)

    def _build_selection_panel(self, layout):
        context_box = QGroupBox(tr("file_dialog.context_group"), self)
        context_layout = QVBoxLayout(context_box)
        self.context_selected_radio = QRadioButton(tr("file_dialog.context_selected"), context_box)
        self.context_current_radio = QRadioButton(tr("file_dialog.context_current"), context_box)
        self.context_selected_radio.setChecked(True)  # default per spec
        group = QButtonGroup(self)
        group.addButton(self.context_selected_radio)
        group.addButton(self.context_current_radio)
        context_layout.addWidget(self.context_selected_radio)
        context_layout.addWidget(self.context_current_radio)
        layout.addWidget(context_box)

        action_row = QHBoxLayout()
        self.invert_btn = QPushButton(tr("file_dialog.invert_btn", **self._shortcuts), self)
        self.select_all_btn = QPushButton(tr("file_dialog.select_all_btn", **self._shortcuts), self)
        self.invert_btn.clicked.connect(self._invert_selection)
        self.select_all_btn.clicked.connect(self._select_all)
        action_row.addWidget(self.invert_btn)
        action_row.addWidget(self.select_all_btn)
        layout.addLayout(action_row)

        summary_box = QGroupBox(tr("file_dialog.summary_group"), self)
        summary_layout = QVBoxLayout(summary_box)
        self.selected_preview = SelectionPreviewWidget(tr("file_dialog.preview_selected"), summary_box)
        self.remaining_preview = SelectionPreviewWidget(tr("file_dialog.preview_remaining"), summary_box)
        self.folder_preview = SelectionPreviewWidget(tr("file_dialog.preview_folder"), summary_box)
        summary_layout.addWidget(self.selected_preview)
        summary_layout.addWidget(self.remaining_preview)
        summary_layout.addWidget(self.folder_preview)
        layout.addWidget(summary_box)

        layout.addStretch(1)

    def showEvent(self, event):
        super().showEvent(event)
        self.list_widget.setFocus()

    # ------------------------------------------------------------------
    # Destination folder list (Relative / History / Favourites) - owned
    # by the shared FolderListController.
    # ------------------------------------------------------------------
    def _on_folder_selected(self, path):
        # Picking a list row overwrites whatever the location edit holds
        # (the list is authoritative while a row is being selected).  The
        # reverse never happens: manual edits leave the list untouched.
        self.location_edit.setText(path)

    def _selected_path(self):
        """Current destination path.  The location edit is the single
        source of truth: list selections write into it, manual edits stay
        in it, and the copy/move always reads it."""
        return self.location_edit.text().strip()

    def _destination_path(self):
        """Return the path the operation must use right now.

        Always the value currently held by the location edit, whether it
        came from the list selection or was typed by the user.
        """
        return self._selected_path()

    # -- custom location editing ----------------------------------------
    # The location edit is always visible, so "editing" is simply focusing
    # the field and typing over whatever it currently holds.
    def _begin_edit_location(self):
        self.location_edit.setFocus()
        self.location_edit.selectAll()

    def _perform_edited_location(self):
        """Use the typed path as the destination and run the default action."""
        self._perform_default_action()

    # -- "Folder" preview: contents of the currently selected/edited
    # destination location --------------------------------------------
    def _refresh_folder_preview(self):
        path_str = self._selected_path()
        items = []
        if path_str:
            folder = Path(path_str)
            if folder.exists() and folder.is_dir():
                image_exts = self.settings.get("image_extensions", default=[])
                video_exts = self.settings.get("video_extensions", default=[])
                items = scan_media(str(folder), image_exts, video_exts)
        self.folder_preview.set_items(items)

    def _toggle_favourite_current(self):
        path = self._selected_path()
        if not path:
            return
        if self.settings.is_favourite(path):
            self.settings.remove_favourite(path)
        else:
            self.settings.add_favourite(path)
        self.folder_list_ctrl.reload(select_path=path)

    # ------------------------------------------------------------------
    # Multi-file selection panel
    # ------------------------------------------------------------------
    def _selected_items(self):
        return [item for item in self.media_items if item[0] in self.selected_paths]

    def _remaining_items(self):
        return [item for item in self.media_items if item[0] not in self.selected_paths]

    def _refresh_selection_ui(self):
        selected_items = self._selected_items()
        remaining_items = self._remaining_items()
        self.selected_preview.set_items(selected_items)
        self.remaining_preview.set_items(remaining_items)
        self.context_selected_radio.setText(tr("file_dialog.context_selected_count", count=len(selected_items)))
        self.context_current_radio.setText(tr("file_dialog.context_current"))

    def _invert_selection(self):
        all_paths = {p for p, _k in self.media_items}
        self.selected_paths.symmetric_difference_update(all_paths)
        self._refresh_selection_ui()

    def _select_all(self):
        for p, _k in self.media_items:
            self.selected_paths.add(p)
        self._refresh_selection_ui()

    def _operation_context(self):
        return "selected" if self.context_selected_radio.isChecked() else "current"

    # ------------------------------------------------------------------
    # Copy / Move
    # ------------------------------------------------------------------
    # -- existing-target conflict handling ------------------------------
    def _ask_conflict(self, filename):
        """Show the "file already exists in the destination" question.
        Returns "cancel", "overwrite" or "rename"."""
        box = QMessageBox(self)
        box.setWindowTitle(tr("file_dialog.conflict_title"))
        box.setText(tr("file_dialog.conflict_ask", file=filename))
        cancel_btn = box.addButton(tr("file_dialog.conflict_cancel"), QMessageBox.ButtonRole.RejectRole)
        overwrite_btn = box.addButton(tr("file_dialog.conflict_overwrite"), QMessageBox.ButtonRole.AcceptRole)
        rename_btn = box.addButton(tr("file_dialog.conflict_rename"), QMessageBox.ButtonRole.ActionRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is overwrite_btn:
            return "overwrite"
        if clicked is rename_btn:
            return "rename"
        return "cancel"

    def _ask_new_name(self, filename):
        """Ask for a replacement file name.  Returns the new name (without
        path separators), or None when the user cancels."""
        while True:
            name, ok = QInputDialog.getText(
                self, tr("file_dialog.conflict_rename_title"),
                tr("file_dialog.conflict_rename_ask"),
                text=filename,
            )
            if not ok:
                return None
            name = name.strip()
            if name and "/" not in name and "\\" not in name:
                return name
            QMessageBox.warning(
                self, tr("file_dialog.conflict_rename_title"),
                tr("file_dialog.conflict_name_invalid"),
            )

    def _resolve_conflict(self, filename, dest_path):
        """Ask the user what to do about an existing target file.  Returns
        ("overwrite", target_path) or ("rename", target_path), or None
        when the whole operation should be cancelled.  A renamed target
        that also exists re-asks the question for the new name."""
        while True:
            choice = self._ask_conflict(filename)
            if choice == "cancel":
                return None
            if choice == "overwrite":
                return "overwrite", dest_path / filename
            new_name = self._ask_new_name(filename)
            if new_name is None:
                return None  # name dialog cancelled -> abort the operation
            target = dest_path / new_name
            if not target.exists():
                return "rename", target
            filename = new_name  # the new name exists too - ask again

    def _perform(self, action):
        context = self._operation_context()
        if context == "selected":
            paths_to_process = [p for p, _k in self._selected_items()]
            if not paths_to_process:
                # Nothing is selected - fall back to the current file
                # instead of blocking the user with an error.
                paths_to_process = [self.current_file]
        else:
            paths_to_process = [self.current_file]

        destination_folder = self._destination_path()
        if not destination_folder:
            QMessageBox.warning(self, tr("common.error_title"), tr("file_dialog.error_no_destination"))
            return

        try:
            dest_path = Path(destination_folder)
        except (OSError, ValueError) as e:
            QMessageBox.critical(self, tr("file_dialog.invalid_path_title"), tr("file_dialog.error_invalid_path", error=e))
            return

        if dest_path.exists() and not dest_path.is_dir():
            QMessageBox.critical(
                self, tr("file_dialog.invalid_path_title"),
                tr("file_dialog.error_not_folder"),
            )
            return

        if not dest_path.exists():
            self.blockSignals(True)
            answer = QMessageBox.question(
                self, tr("file_dialog.create_folder_title"),
                tr("file_dialog.create_folder_ask", folder=destination_folder),
                defaultButton=QMessageBox.StandardButton.Yes
            )

            if answer != QMessageBox.Yes:
                return
            try:
                dest_path.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                QMessageBox.critical(self, tr("file_dialog.invalid_path_title"), tr("file_dialog.error_create_folder", error=e))
                return
            self.blockSignals(False)

        succeeded = []
        succeeded_targets = {}  # src_str -> target_str, only for action == "move"
        errors = []
        aborted = False
        for src_str in paths_to_process:
            src = Path(src_str)
            try:
                target = dest_path / src.name
                if _same_file(src, target):
                    # Copying/moving a file onto itself is a no-op, not a
                    # conflict - accept it silently.
                    succeeded.append(src_str)
                    if action == "move":
                        succeeded_targets[src_str] = str(target)
                    continue
                if target.exists():
                    resolved = self._resolve_conflict(src.name, dest_path)
                    if resolved is None:
                        aborted = True
                        break  # user cancelled the whole operation
                    _mode, target = resolved
                    if target.exists():  # "overwrite" - replace the file
                        target.unlink()
                if action == "copy":
                    shutil.copy2(str(src), str(target))
                else:
                    shutil.move(str(src), str(target))
                    succeeded_targets[src_str] = str(target)
                succeeded.append(src_str)
            except OSError as e:
                errors.append((src_str, str(e)))

        if errors:
            details = "\n".join(f"{Path(p).name}: {err}" for p, err in errors)
            QMessageBox.warning(self, tr("file_dialog.some_failed_title"), details)

        if aborted or not succeeded:
            return  # cancelled, or nothing worked - keep the dialog open

        self.settings.add_history(destination_folder)
        self.settings.set_last_used_location(destination_folder)
        self.performed_action = action
        self.affected_paths = succeeded

        if action == "move" and self.tags_db is not None:
            # Tags follow the file to its new location instead of being
            # orphaned (left pointing at a path that no longer exists).
            for src_str, target_str in succeeded_targets.items():
                self.tags_db.retarget_file(src_str, target_str)

        if action == "move":
            # Moved files no longer exist in this folder - drop them from
            # the (shared) selection set as well.
            for p in succeeded:
                self.selected_paths.discard(p)

        self.accept()

    def _perform_default_action(self):
        """Run whichever action (copy/move) this dialog was opened for."""
        self._perform(self.default_action)

    # ------------------------------------------------------------------
    # Configurable keyboard / mouse handling
    # ------------------------------------------------------------------
    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress and isinstance(event, QKeyEvent):
            if self._handle_dialog_key(event, obj):
                return True
        elif event.type() == QEvent.MouseButtonPress and isinstance(event, QMouseEvent):
            if self._handle_dialog_key(event, obj):
                return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event: QKeyEvent):
        if self._handle_dialog_key(event, self.focusWidget()):
            return
        super().keyPressEvent(event)

    def _handle_dialog_key(self, event, focused_obj) -> bool:
        file_dialog_keys = self.settings.get("file_dialog", default={})

        # While the location edit has focus, let QLineEdit process text
        # input normally.  Enter performs the default action using the
        # field's current value; Escape cancels the whole dialog.
        if focused_obj is self.location_edit:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                self._perform_default_action()
                return True
            if matches_any(event, file_dialog_keys.get("cancel", ["Escape"])):
                self.reject()
                return True
            return False

        # Ctrl+Enter always performs the dialog's configured action
        # (copy/move/open), regardless of mode - this is the escape hatch
        # for relative mode, where plain Enter now navigates instead.
        if matches_any(event, file_dialog_keys.get("confirm_action", ["Ctrl+Return"])):
            self._perform_default_action()
            return True

        if matches_any(event, file_dialog_keys.get("edit_location", ["F2"])):
            self._begin_edit_location()
            return True
        if matches_any(event, file_dialog_keys.get("copy", ["Alt+C"])):
            self._perform("copy")
            return True
        if matches_any(event, file_dialog_keys.get("move", ["Alt+M"])):
            self._perform("move")
            return True
        if matches_any(event, file_dialog_keys.get("toggle_favourite", ["Ctrl+D"])):
            self._toggle_favourite_current()
            return True
        if matches_any(event, file_dialog_keys.get("cancel", ["Escape"])):
            self.reject()
            return True
        if matches_any(event, file_dialog_keys.get("mode_relative", ["R"])):
            self.folder_list_ctrl.set_mode("relative")
            return True
        if matches_any(event, file_dialog_keys.get("mode_history", ["H"])):
            self.folder_list_ctrl.set_mode("history")
            return True
        if matches_any(event, file_dialog_keys.get("mode_favourites", ["F"])):
            self.folder_list_ctrl.set_mode("favourites")
            return True
        if matches_any(event, file_dialog_keys.get("invert_selection", ["I"])):
            self._invert_selection()
            return True
        if matches_any(event, file_dialog_keys.get("select_all", ["A"])):
            self._select_all()
            return True

        if isinstance(event, QKeyEvent) and event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if self.folder_list_ctrl.mode == "relative" and self.folder_list_ctrl.navigate():
                # Descend into (or ascend out of, via '...') the selected
                # folder instead of performing the copy/move/open action -
                # this is what lets the user go back down after using
                # '...' to go up.
                return True
            self._perform_default_action()
            return True

        return False
