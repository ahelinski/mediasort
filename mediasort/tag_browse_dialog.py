"""Dialog for picking a tag to browse all its files/timestamp instances
(default key: Alt+T). Works like the "Open folder" dialog, but the list
shows recently VIEWED tags instead of folders.
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QLineEdit, QPushButton, QLabel, QGroupBox
)
from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QKeyEvent

from .file_scanner import kind_for_path
from .i18n import tr
from .selection_preview import SelectionPreviewWidget
from .style import STYLE
from .tags_db import MAX_TAG_LENGTH


class TagBrowseDialog(QDialog):
    def __init__(self, settings, tags_db, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.tags_db = tags_db
        self.confirmed = False
        self.selected_tag = None

        self.setWindowTitle(tr("tag_browse.title"))
        self.resize(560, 480)
        self.setStyleSheet(STYLE)

        self._build_ui()
        self._reload_tag_list()
        self._refresh_tag_preview()

    # ------------------------------------------------------------------
    def _build_ui(self):
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(tr("tag_browse.tag_label"), self))
        self.tag_edit = QLineEdit(self)
        self.tag_edit.setMaxLength(MAX_TAG_LENGTH)
        self.tag_edit.installEventFilter(self)
        self.tag_edit.textChanged.connect(lambda _t: self._refresh_tag_preview())
        layout.addWidget(self.tag_edit)

        layout.addWidget(QLabel(tr("tag_browse.recent_tags_label"), self))
        self.tag_list = QListWidget(self)
        self.tag_list.currentItemChanged.connect(self._on_tag_selected)
        self.tag_list.installEventFilter(self)
        layout.addWidget(self.tag_list)

        preview_box = QGroupBox(tr("tag_browse.preview_group"), self)
        preview_layout = QVBoxLayout(preview_box)
        self.tag_preview = SelectionPreviewWidget(tr("tag_browse.preview_tag"), preview_box)
        preview_layout.addWidget(self.tag_preview)
        layout.addWidget(preview_box)

        btn_row = QHBoxLayout()
        self.open_btn = QPushButton(tr("tag_browse.open_btn"), self)
        self.open_btn.setDefault(True)
        self.open_btn.clicked.connect(self._confirm)
        self.cancel_btn = QPushButton(tr("tag_browse.cancel_btn"), self)
        self.cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.open_btn)
        btn_row.addWidget(self.cancel_btn)
        layout.addLayout(btn_row)

        hint = QLabel(tr("tag_browse.hint"), self)
        hint.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(hint)

    def showEvent(self, event):
        super().showEvent(event)
        self.tag_edit.setFocus()

    # ------------------------------------------------------------------
    def _reload_tag_list(self):
        self.tag_list.blockSignals(True)
        self.tag_list.clear()
        for name in self.tags_db.recent_viewed_tags():
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, name)
            self.tag_list.addItem(item)
        self.tag_list.blockSignals(False)

    def _on_tag_selected(self, current, _previous):
        if current is not None:
            self.tag_edit.setText(current.data(Qt.UserRole))

    def _refresh_tag_preview(self):
        name = self.tags_db.normalize_tag(self.tag_edit.text())
        items = []
        if name:
            image_exts = self.settings.get("image_extensions", default=[])
            video_exts = self.settings.get("video_extensions", default=[])
            for path, _ts in self.tags_db.instances_for_tag(name):
                kind = kind_for_path(path, image_exts, video_exts) or "image"
                items.append((path, kind))
        self.tag_preview.set_items(items)

    # ------------------------------------------------------------------
    def _confirm(self):
        name = self.tags_db.normalize_tag(self.tag_edit.text())
        if not name:
            return
        if self.tags_db.instance_count_for_tag(name) == 0:
            return  # nothing to browse - silently ignore
        self.selected_tag = name
        self.confirmed = True
        self.accept()

    # ------------------------------------------------------------------
    # Keyboard handling
    # ------------------------------------------------------------------
    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress and isinstance(event, QKeyEvent):
            if self._handle_key(event):
                return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event: QKeyEvent):
        if self._handle_key(event):
            return
        super().keyPressEvent(event)

    def _handle_key(self, event: QKeyEvent) -> bool:
        if event.key() == Qt.Key_Escape:
            self.reject()
            return True
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._confirm()
            return True
        return False
