"""Open/Browse dialog: pick files to view by folder, tag, or both,
optionally filtered by media type. Split out from the copy/move dialog
since browsing has fundamentally different semantics (no destination, no
selected-files context - just choosing WHAT to view).

Layout: three sections side by side.
  1. Folder picker - same Relative/History/Favourites modes and manual
     F2/click path editing as the copy/move dialog, but folder selection
     is OPTIONAL here (nothing is auto-selected).
  2. Tag list - every known tag, alphabetically, single-select, also
     optional.
  3. Media type filter - Images and videos / Images only / Videos only.

At least one of folder or tag must be chosen. If only a folder is chosen,
all its files (optionally filtered by type) are shown. If only a tag is
chosen, every file carrying that tag (optionally filtered by type) is
shown. If both are chosen, only files that are BOTH in that folder AND
carry that tag are shown.
"""
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QLineEdit, QPushButton, QLabel, QGroupBox, QRadioButton, QButtonGroup,
    QMessageBox, QCheckBox
)
from PySide6.QtCore import Qt, QEvent, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent

from .key_utils import matches_any
from .file_scanner import list_subfolders, scan_media, scan_media_recursive, kind_for_path
from .style import STYLE

PARENT_MARK = "..."


class ClickableLabel(QLabel):
    """A QLabel that emits `clicked` on a left mouse click."""
    clicked = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class BrowseDialog(QDialog):
    def __init__(self, current_folder, settings, tags_db, parent=None):
        super().__init__(parent)
        self.current_folder = str(Path(current_folder).resolve())
        self.settings = settings
        self.tags_db = tags_db

        self.confirmed = False
        self.result_items = []     # list of (path, kind) once confirmed
        self.result_folder = None  # folder to adopt as MainWindow.folder, or None

        self.folder_mode = self.settings.get_last_dialog_mode() or "relative"
        self._relative_dir = self.current_folder

        self.setWindowTitle("Otworz / Przegladaj")
        self.resize(1020, 580)
        self.setStyleSheet(STYLE)

        self._build_ui()
        self._reload_folder_list()
        self._reload_tag_list()
        self._update_match_count()

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
        self.match_label.setStyleSheet("font-weight: bold;")
        outer.addWidget(self.match_label)

        btn_row = QHBoxLayout()
        self.open_btn = QPushButton("Otworz (Enter)", self)
        self.open_btn.setDefault(True)
        self.open_btn.clicked.connect(self._confirm)
        self.cancel_btn = QPushButton("Anuluj (Esc)", self)
        self.cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.open_btn)
        btn_row.addWidget(self.cancel_btn)
        outer.addLayout(btn_row)

        hint = QLabel(
            "R/H/F: tryb folderu (wzgledny/historia/ulubione)  |  "
            "F2 / klik na sciezce: recznie edytuj folder  |  "
            "Enter: otworz (lub wejdz w podfolder w trybie wzglednym)  |  "
            "Esc: anuluj  |  Trzeba wybrac folder LUB tag (mozna oba)",
            self,
        )
        hint.setStyleSheet("color: gray; font-size: 11px;")
        hint.setWordWrap(True)
        outer.addWidget(hint)

    def _build_folder_column(self, columns):
        col = QVBoxLayout()
        columns.addLayout(col, 2)

        col.addWidget(QLabel("Folder:", self))

        self.folder_mode_label = QLabel(self)
        col.addWidget(self.folder_mode_label)

        self.location_label = ClickableLabel(self)
        self.location_label.setStyleSheet(
            # "padding: 4px 6px; border: 1px solid #555; background-color: #222; "
            # "color: white; border-radius: 3px;"
            STYLE
        )
        self.location_label.setToolTip("Kliknij lub nacisnij F2 aby recznie wpisac sciezke")
        self.location_label.clicked.connect(self._begin_edit_location)
        col.addWidget(self.location_label)

        self.location_edit = QLineEdit(self)
        self.location_edit.installEventFilter(self)
        self.location_edit.hide()
        col.addWidget(self.location_edit)

        self.include_subfolders_cb = QCheckBox("Uwzglednij podfoldery", self)
        depth = self.settings.get("browse_subfolder_depth", default=1)
        self.include_subfolders_cb.setToolTip(
            f"Przeszukuje takze podfoldery (do {depth} "
            + ("poziomu" if depth == 1 else "poziomow")
            + " w glab - zmien w settings.json: browse_subfolder_depth)"
        )
        self.include_subfolders_cb.toggled.connect(lambda _checked: self._update_match_count())
        col.addWidget(self.include_subfolders_cb)

        self.folder_list = QListWidget(self)
        self.folder_list.currentItemChanged.connect(self._on_folder_selected)
        self.folder_list.itemActivated.connect(lambda _: self._navigate_or_select())
        self.folder_list.installEventFilter(self)
        col.addWidget(self.folder_list)

        self.clear_folder_btn = QPushButton("Wyczysc folder", self)
        self.clear_folder_btn.clicked.connect(self._clear_folder)
        col.addWidget(self.clear_folder_btn)

    def _build_tag_column(self, columns):
        col = QVBoxLayout()
        columns.addLayout(col, 2)

        col.addWidget(QLabel("Tag:", self))

        self.tag_list = QListWidget(self)
        self.tag_list.currentItemChanged.connect(lambda *_: self._update_match_count())
        self.tag_list.installEventFilter(self)
        col.addWidget(self.tag_list)

        self.clear_tag_btn = QPushButton("Wyczysc tag", self)
        self.clear_tag_btn.clicked.connect(self._clear_tag)
        col.addWidget(self.clear_tag_btn)

    def _build_type_column(self, columns):
        col = QVBoxLayout()
        columns.addLayout(col, 1)

        type_box = QGroupBox("Typ plikow", self)
        type_layout = QVBoxLayout(type_box)
        self.radio_both = QRadioButton("Zdjecia i wideo", type_box)
        self.radio_images = QRadioButton("Tylko zdjecia", type_box)
        self.radio_videos = QRadioButton("Tylko wideo", type_box)
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
        self.folder_list.setFocus()

    # ------------------------------------------------------------------
    # Folder list (Relative / History / Favourites) - same semantics as
    # the copy/move dialog, but nothing is auto-selected here.
    # ------------------------------------------------------------------
    def _current_folder_list(self):
        if self.folder_mode == "relative":
            root = Path(self._relative_dir).resolve()
            items = []
            if root.parent != root:
                items.append((PARENT_MARK, str(root.parent)))
            for p in list_subfolders(root):
                items.append((Path(p).name, p))
            return items
        elif self.folder_mode == "history":
            return [(p, p) for p in self.settings.get_history()]
        elif self.folder_mode == "favourites":
            return [(p, p) for p in self.settings.get_favourites()]
        return []

    def _reload_folder_list(self, select_path=None):
        self.folder_mode_label.setText(f"Tryb: {self._mode_display_name()}")
        self.folder_list.blockSignals(True)
        self.folder_list.clear()
        for text, path in self._current_folder_list():
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, path)
            if text != PARENT_MARK and self.settings.is_favourite(path):
                item.setText(f"\u2605 {text}")
            self.folder_list.addItem(item)
        self.folder_list.blockSignals(False)

        if select_path:
            for row in range(self.folder_list.count()):
                if self.folder_list.item(row).data(Qt.UserRole) == select_path:
                    self.folder_list.setCurrentRow(row)
                    break

    def _mode_display_name(self):
        return {"relative": "Wzgledny", "history": "Historia", "favourites": "Ulubione"}.get(
            self.folder_mode, self.folder_mode
        )

    def _on_folder_selected(self, current, _previous):
        if current is not None:
            self.location_label.setText(current.data(Qt.UserRole))
            self._update_match_count()

    def _navigate_or_select(self):
        item = self.folder_list.currentItem()
        if not item or self.folder_mode != "relative":
            return
        self._relative_dir = item.data(Qt.UserRole)
        self._reload_folder_list()

    def _set_folder_mode(self, mode):
        if mode == self.folder_mode:
            return
        self.folder_mode = mode
        self.settings.set_last_dialog_mode(mode)
        self._reload_folder_list()

    def _clear_folder(self):
        self.folder_list.blockSignals(True)
        self.folder_list.setCurrentRow(-1)
        self.folder_list.blockSignals(False)
        self.location_label.clear()
        self._update_match_count()

    def _clear_tag(self):
        self.tag_list.blockSignals(True)
        self.tag_list.setCurrentRow(-1)
        self.tag_list.blockSignals(False)
        self._update_match_count()

    # -- custom location editing (F2 / click on the label) ---------------
    def _begin_edit_location(self):
        self.location_edit.setText(self.location_label.text())
        self.location_label.hide()
        self.location_edit.show()
        self.location_edit.setFocus()
        self.location_edit.selectAll()

    def _confirm_edit_location(self):
        self.location_label.setText(self.location_edit.text().strip())
        self._end_edit_location()
        self._update_match_count()

    def _cancel_edit_location(self):
        self._end_edit_location()

    def _end_edit_location(self):
        self.location_edit.hide()
        self.location_label.show()
        self.folder_list.setFocus()

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
        return self.location_label.text().strip() or None

    def _selected_tag(self):
        item = self.tag_list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _media_type_filter(self):
        if self.radio_images.isChecked():
            return "images"
        if self.radio_videos.isChecked():
            return "videos"
        return "both"

    def _ext_lists(self):
        image_exts = self.settings.get("image_extensions", default=[])
        video_exts = self.settings.get("video_extensions", default=[])
        type_filter = self._media_type_filter()
        if type_filter == "images":
            return image_exts, []
        if type_filter == "videos":
            return [], video_exts
        return image_exts, video_exts

    def _compute_matching_items(self):
        """Returns list of (path, kind), or None if neither folder nor tag
        is selected (invalid - the dialog can't be confirmed)."""
        folder = self._selected_folder()
        tag = self._selected_tag()
        if not folder and not tag:
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

        if tag:
            tag_files = set(self.tags_db.files_for_tag(tag))
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
        items = self._compute_matching_items()
        if items is None:
            self.match_label.setText("Wybierz folder lub tag (mozna oba).")
        elif not items:
            self.match_label.setText("Znaleziono: 0 plikow")
        else:
            self.match_label.setText(f"Znaleziono: {len(items)} " + ("plik" if len(items) == 1 else "plikow"))

    # ------------------------------------------------------------------
    def _confirm(self):
        items = self._compute_matching_items()
        if items is None:
            QMessageBox.warning(self, "Blad", "Wybierz folder lub tag (mozna oba, ale przynajmniej jedno).")
            return
        self.result_items = items
        self.result_folder = self._selected_folder()
        self.confirmed = True
        self.accept()

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

        if not self.location_edit.isHidden() and focused_obj is self.location_edit:
            if isinstance(event, QKeyEvent) and event.key() in (Qt.Key_Return, Qt.Key_Enter):
                self._confirm_edit_location()
                return True
            if matches_any(event, file_dialog_keys.get("cancel", ["Escape"])):
                self._cancel_edit_location()
                return True
            return False

        if matches_any(event, file_dialog_keys.get("edit_location", ["F2"])):
            self._begin_edit_location()
            return True
        if matches_any(event, file_dialog_keys.get("cancel", ["Escape"])):
            self.reject()
            return True

        # R/H/F only switch the folder mode when the tag list doesn't have
        # focus (so typing doesn't clash with Qt's list type-ahead search).
        if focused_obj is not self.tag_list:
            if matches_any(event, file_dialog_keys.get("mode_relative", ["R"])):
                self._set_folder_mode("relative")
                return True
            if matches_any(event, file_dialog_keys.get("mode_history", ["H"])):
                self._set_folder_mode("history")
                return True
            if matches_any(event, file_dialog_keys.get("mode_favourites", ["F"])):
                self._set_folder_mode("favourites")
                return True

        if isinstance(event, QKeyEvent) and event.key() in (Qt.Key_Return, Qt.Key_Enter):
            item = self.folder_list.currentItem()
            if (
                self.folder_mode == "relative"
                and focused_obj is self.folder_list
                and item is not None
            ):
                self._navigate_or_select()
            else:
                self._confirm()
            return True

        return False
