"""File Tags Management window (default key: T).

Shows and edits tags for the CURRENT file: a text field for typing a tag,
a list of recently used tags on the left (arrow-key navigable - selecting
one fills the text field), and the current file's own tags on the right
(file-level tags shown plain, timestamp tags shown as "TAG@MM:SS").
"Tag file" (Enter) assigns the typed tag to the whole file; "Tag
timestamp" (Shift+Enter) - only shown for videos - assigns it to the
current playback second. MainWindow is responsible for pausing the video
before opening this dialog and resuming it after closing.
"""
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QLineEdit, QPushButton, QLabel, QWidget
)
from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QKeyEvent

from .tags_db import MAX_TAG_LENGTH
from .i18n import tr
from . import styles
from .tag_suggestions import TagSuggestionBox


def _format_ts(seconds):
    seconds = max(int(seconds or 0), 0)
    m, s = divmod(seconds, 60)
    return f"{m:02d}:{s:02d}"


class TagManagementDialog(QDialog):
    def __init__(self, current_file, is_video, current_timestamp_sec, settings, tags_db, parent=None):
        super().__init__(parent)
        self.current_file = str(current_file)
        self.is_video = is_video
        self.current_timestamp_sec = int(current_timestamp_sec or 0)
        self.settings = settings
        self.tags_db = tags_db
        self.changed = False  # True if at least one tag was added this session

        self.setWindowTitle(tr("tag_manage.title"))
        self.resize(600, 480)
        self.setStyleSheet(styles.DIALOG)

        # Shortcut labels for the UI texts - all actions here (Enter /
        # Shift+Enter / Esc) are handled directly and are not configurable.
        self._shortcuts = {
            "enter_key": "Enter",
            "shift_enter_key": "Shift+Enter",
            "cancel_key": "Esc",
        }

        self._build_ui()
        # Tag autocomplete: existing tags starting with the typed text are
        # suggested after the 2nd character (see tag_suggestions.py).
        self._suggestions = TagSuggestionBox(
            self, self.tag_edit, lambda: self.tags_db.all_tags()
        )
        self._reload_recent_tags()
        self._reload_file_tags()

    # ------------------------------------------------------------------
    def _build_ui(self):
        layout = QVBoxLayout(self)

        info = QLabel(tr("tag_manage.current_file", filename=Path(self.current_file).name), self)
        info.setStyleSheet(styles.DIALOG)
        layout.addWidget(info)

        layout.addWidget(QLabel(tr("tag_manage.tag_label"), self))
        self.tag_edit = QLineEdit(self)
        self.tag_edit.setMaxLength(MAX_TAG_LENGTH)
        self.tag_edit.installEventFilter(self)
        layout.addWidget(self.tag_edit)

        lists_row = QHBoxLayout()

        left_col = QVBoxLayout()
        left_col.addWidget(QLabel(tr("tag_manage.recent_tags_label"), self))
        self.recent_list = QListWidget(self)
        self.recent_list.currentItemChanged.connect(self._on_recent_selected)
        self.recent_list.installEventFilter(self)
        left_col.addWidget(self.recent_list)
        lists_row.addLayout(left_col)

        right_col = QVBoxLayout()
        right_col.addWidget(QLabel(tr("tag_manage.file_tags_label"), self))
        self.file_tags_list = QListWidget(self)
        right_col.addWidget(self.file_tags_list)
        lists_row.addLayout(right_col)

        layout.addLayout(lists_row)

        btn_row = QHBoxLayout()
        self.tag_file_btn = QPushButton(tr("tag_manage.tag_file_btn", **self._shortcuts), self)
        self.tag_file_btn.setDefault(True)
        self.tag_file_btn.clicked.connect(self._tag_file)
        btn_row.addWidget(self.tag_file_btn)

        self.tag_timestamp_btn = QPushButton(tr("tag_manage.tag_timestamp_btn", **self._shortcuts), self)
        self.tag_timestamp_btn.clicked.connect(self._tag_timestamp)
        self.tag_timestamp_btn.setVisible(self.is_video)
        btn_row.addWidget(self.tag_timestamp_btn)

        self.close_btn = QPushButton(tr("tag_manage.close_btn", **self._shortcuts), self)
        self.close_btn.clicked.connect(self.accept)
        btn_row.addWidget(self.close_btn)
        layout.addLayout(btn_row)

        hint_text = tr("tag_manage.hint", **self._shortcuts)
        if self.is_video:
            hint_text += tr(
                "tag_manage.hint_timestamp",
                time=_format_ts(self.current_timestamp_sec),
                **self._shortcuts,
            )
        hint = QLabel(hint_text, self)
        hint.setStyleSheet(styles.HINT)
        hint.setWordWrap(True)
        layout.addWidget(hint)

    def showEvent(self, event):
        super().showEvent(event)
        self.tag_edit.setFocus()

    # ------------------------------------------------------------------
    def _reload_recent_tags(self):
        self.recent_list.blockSignals(True)
        self.recent_list.clear()
        for name in self.tags_db.recent_assigned_tags():
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, name)
            self.recent_list.addItem(item)
        self.recent_list.blockSignals(False)

    def _on_recent_selected(self, current, _previous):
        if current is not None:
            self.tag_edit.setText(current.data(Qt.UserRole))

    def _go_to_timestamp(self, ts):
        self.video_viewer.player.setPosition(int(ts) * 1000)

    def _reload_file_tags(self):
        self.file_tags_list.clear()
        tags = self.tags_db.file_tags(self.current_file)
        # Whole-file tags (no timestamp) first, alphabetically; then
        # timestamp tags from the smallest to the largest timestamp, and
        # alphabetically within the same timestamp.
        tags.sort(key=lambda t: (
            0 if t[1] is None else 1,          # regular tags before timestamp tags
            t[1] if t[1] is not None else 0,   # timestamp ascending
            t[0].lower(),                      # alphabetical (case-insensitive)
        ))
        for name, ts in tags:
            text = name if ts is None else f"{name}@{_format_ts(ts)}"

            row_widget = QWidget(self.file_tags_list)
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(6, 2, 6, 2)

            label = QLabel(text, row_widget)
            label.setStyleSheet(styles.DIALOG)
            row_layout.addWidget(label)
            row_layout.addStretch(1)

            if ts is not None:
                go_to_ts_link = QPushButton(tr("tag_manage.show_btn"), row_widget)
                go_to_ts_link.setFlat(True)
                go_to_ts_link.setCursor(Qt.PointingHandCursor)
                go_to_ts_link.setStyleSheet(styles.LINK)
                go_to_ts_link.clicked.connect(lambda _checked=False, n=name, t=ts: self.parent().video_viewer.go_to_timestamp(t))
                row_layout.addWidget(go_to_ts_link)

            delete_link = QPushButton(tr("tag_manage.remove_btn"), row_widget)
            delete_link.setFlat(True)
            delete_link.setCursor(Qt.PointingHandCursor)
            delete_link.setStyleSheet(styles.DEL_LINK)
            delete_link.clicked.connect(lambda _checked=False, n=name, t=ts: self._remove_tag(n, t))
            row_layout.addWidget(delete_link)

            item = QListWidgetItem()
            item.setSizeHint(row_widget.sizeHint())
            self.file_tags_list.addItem(item)
            self.file_tags_list.setItemWidget(item, row_widget)

    def _remove_tag(self, name, timestamp_sec):
        self.tags_db.remove_tag(name, self.current_file, timestamp_sec=timestamp_sec)
        self.changed = True
        self._reload_file_tags()

    # ------------------------------------------------------------------
    # Actions - a tag can only be assigned once per file (or once per
    # video-second); duplicates are silently ignored by TagsDatabase, no
    # error message is shown.
    # ------------------------------------------------------------------
    def _tag_file(self):
        name = self.tags_db.normalize_tag(self.tag_edit.text())
        if not name:
            return
        self.tags_db.assign_tag(name, self.current_file)
        self.changed = True
        self._reload_recent_tags()
        self._reload_file_tags()
        # Clear the field and keep focus in it, so the next tag can be
        # typed right away (the dialog stays open for repeated tagging).
        self.tag_edit.clear()
        self.tag_edit.setFocus()

    def _tag_timestamp(self):
        if not self.is_video:
            return
        name = self.tags_db.normalize_tag(self.tag_edit.text())
        if not name:
            return
        self.tags_db.assign_tag(name, self.current_file, timestamp_sec=self.current_timestamp_sec)
        self.changed = True
        self._reload_recent_tags()
        self._reload_file_tags()
        self.tag_edit.clear()
        self.tag_edit.setFocus()

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
            self.accept()
            return True
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if event.modifiers() & Qt.ShiftModifier:
                self._tag_timestamp()
            else:
                self._tag_file()
            return True
        return False
