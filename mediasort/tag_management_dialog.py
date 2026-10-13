"""Manage File Tags window (default key: T).

Shows and edits the tags of the CURRENT file: a text field for typing a
tag, the list of recently used tags (arrow-key navigable - selecting one
fills the text field) and the file's own tags as rows. Each row offers the
same small actions as the "Manage All Tags" window:

  * a magnifier - jump to the tag's timestamp (timestamp tags only);
  * a pencil - edit that entry: change the tag name and, for a timestamp
    tag, the time (minutes:seconds);
  * a trash - remove that entry from the file.

A timestamp row is highlighted while it is the interval currently shown at
the playback position (the same one the video overlay emphasizes). The
Play/Pause button at the bottom controls the video; MainWindow pauses the
video before opening this window and, unless that button was used, resumes
it after closing.
"""
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QLineEdit, QPushButton, QLabel, QWidget, QMessageBox
)
from PySide6.QtCore import Qt, QEvent, QSize
from PySide6.QtGui import QKeyEvent

from .tags_db import MAX_TAG_LENGTH
from .i18n import tr
from . import icons, styles
from .tag_suggestions import TagSuggestionBox
from .cut_dialog import parse_time_to_ms


def _format_ts(seconds):
    seconds = max(int(seconds or 0), 0)
    m, s = divmod(seconds, 60)
    return f"{m:02d}:{s:02d}"


class _TagEditDialog(QDialog):
    """Small form editing one tag entry of the current file.

    The tag name can always be changed; for a timestamp tag the time is
    editable too (minutes:seconds). ``result_name``/``result_timestamp``
    hold the accepted values after exec() returned truthy."""

    def __init__(self, name, timestamp_sec, tags_db, parent=None):
        super().__init__(parent)
        self.tags_db = tags_db
        self.result_name = None
        self.result_timestamp = timestamp_sec

        self.setWindowTitle(tr("tag_manage.edit_title"))
        self.setStyleSheet(styles.DIALOG)
        self.setMinimumWidth(360)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr("tag_manage.edit_name_label"), self))
        self.name_edit = QLineEdit(name, self)
        self.name_edit.setMaxLength(MAX_TAG_LENGTH)
        layout.addWidget(self.name_edit)
        # Same autocomplete popup as the other tag fields.
        self._suggestions = TagSuggestionBox(self, self.name_edit, tags_db.all_tags)

        self.time_edit = None
        if timestamp_sec is not None:
            layout.addWidget(QLabel(tr("tag_manage.edit_time_label"), self))
            self.time_edit = QLineEdit(_format_ts(timestamp_sec), self)
            layout.addWidget(self.time_edit)

        btn_row = QHBoxLayout()
        save_btn = QPushButton(tr("tag_manage.edit_save_btn"), self)
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)
        cancel_btn = QPushButton(tr("tag_manage.edit_cancel_btn", cancel_key="Esc"), self)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        self.name_edit.setFocus()
        self.name_edit.selectAll()

    def _save(self):
        name = self.tags_db.normalize_tag(self.name_edit.text())
        if not name:
            return
        if self.time_edit is not None:
            total_ms = parse_time_to_ms(self.time_edit.text())
            if total_ms is None:
                QMessageBox.warning(
                    self, tr("tag_manage.edit_title"),
                    tr("tag_manage.edit_time_invalid"),
                )
                return
            self.result_timestamp = max(0, int(round(total_ms / 1000)))
        else:
            self.result_timestamp = None
        self.result_name = name
        self.accept()

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)


class TagManagementDialog(QDialog):
    def __init__(self, current_file, is_video, current_timestamp_sec, settings, tags_db, parent=None):
        super().__init__(parent)
        self.current_file = str(current_file)
        self.is_video = is_video
        self.current_timestamp_sec = int(current_timestamp_sec or 0)
        self.settings = settings
        self.tags_db = tags_db
        self.changed = False  # True if at least one tag was added this session
        # True once the Play/Pause button was used - the caller then leaves
        # the playback state as the user set it.
        self.playback_touched = False

        # (name, timestamp, label widget) of every row, used to highlight
        # the interval shown at the current playback position.
        self._file_tag_rows = []
        self._last_second = None

        self.setWindowTitle(tr("tag_manage.title"))
        self.resize(640, 520)
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

        player = self._player()
        if player is not None:
            player.playbackStateChanged.connect(self._refresh_play_btn)
            player.positionChanged.connect(self._on_position_changed)
        self._update_play_btn()

    # ------------------------------------------------------------------
    # Helpers around the main window (this dialog's parent)
    # ------------------------------------------------------------------
    def _player(self):
        parent = self.parent()
        viewer = getattr(parent, "video_viewer", None)
        return getattr(viewer, "player", None) if viewer is not None else None

    def _viewer(self):
        return getattr(self.parent(), "video_viewer", None)

    def _current_second(self):
        """Playback second to use for new timestamp tags / highlighting."""
        if not self.is_video:
            return self.current_timestamp_sec
        player = self._player()
        if player is None:
            return self.current_timestamp_sec
        return max(int(player.position()) // 1000, 0)

    # ------------------------------------------------------------------
    def _build_ui(self):
        layout = QVBoxLayout(self)

        info = QLabel(tr("tag_manage.current_file", filename=Path(self.current_file).name), self)
        info.setStyleSheet(styles.FILE_TAG_ROW)
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

        self.play_btn = QPushButton(tr("manage_tags.play_btn"), self)
        self.play_btn.setStyleSheet(styles.SECONDARY_BUTTON)
        self.play_btn.setToolTip(tr("manage_tags.play_tooltip"))
        self.play_btn.clicked.connect(self._toggle_playback)
        self.play_btn.setVisible(self.is_video)
        btn_row.addWidget(self.play_btn)

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
        self.hint_label = QLabel(hint_text, self)
        self.hint_label.setStyleSheet(styles.HINT)
        self.hint_label.setWordWrap(True)
        layout.addWidget(self.hint_label)

    def showEvent(self, event):
        super().showEvent(event)
        self.tag_edit.setFocus()
        self._update_play_btn()

    # ------------------------------------------------------------------
    # Lists
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

    def _row_button(self, icon, tooltip, parent):
        button = QPushButton(parent)
        button.setIcon(icon)
        button.setIconSize(QSize(16, 16))
        button.setFlat(True)
        button.setCursor(Qt.PointingHandCursor)
        button.setFixedSize(24, 24)
        button.setToolTip(tooltip)
        button.setStyleSheet(styles.ICON_BUTTON)
        return button

    def _reload_file_tags(self):
        self.file_tags_list.clear()
        self._file_tag_rows = []
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
            label.setStyleSheet(styles.FILE_TAG_ROW)
            row_layout.addWidget(label)
            row_layout.addStretch(1)

            if ts is not None:
                # Magnifier: jump to the tagged moment (like "Show" before).
                go_to_btn = self._row_button(
                    icons.magnifier_icon(), tr("tag_manage.show_tooltip"), row_widget
                )
                go_to_btn.clicked.connect(
                    lambda _checked=False, t=ts: self._go_to_timestamp(t)
                )
                row_layout.addWidget(go_to_btn)

            # Pencil: edit the tag name and (for timestamps) the time.
            edit_btn = self._row_button(
                icons.pencil_icon(), tr("tag_manage.edit_tooltip"), row_widget
            )
            edit_btn.clicked.connect(
                lambda _checked=False, n=name, t=ts: self._edit_tag(n, t)
            )
            row_layout.addWidget(edit_btn)

            # Trash: remove this entry from the file.
            delete_btn = self._row_button(
                icons.trash_icon(), tr("tag_manage.remove_tooltip"), row_widget
            )
            delete_btn.clicked.connect(
                lambda _checked=False, n=name, t=ts: self._remove_tag(n, t)
            )
            row_layout.addWidget(delete_btn)

            item = QListWidgetItem()
            item.setSizeHint(row_widget.sizeHint())
            self.file_tags_list.addItem(item)
            self.file_tags_list.setItemWidget(item, row_widget)
            self._file_tag_rows.append((name, ts, label))

        self._update_active_highlight()

    def _update_active_highlight(self):
        """Emphasize the timestamp row(s) of the interval currently shown at
        the playback position - the same rule the video overlay uses (the
        last tagged second at or before the position)."""
        active_timestamp = None
        if self.is_video:
            current_second = self._current_second()
            candidates = [
                ts for _name, ts, _label in self._file_tag_rows if ts is not None
            ]
            if candidates:
                active_timestamp = max(
                    (ts for ts in candidates if ts <= current_second), default=None
                )
        for _name, ts, label in self._file_tag_rows:
            active = ts is not None and ts == active_timestamp
            wanted = styles.FILE_TAG_ACTIVE if active else styles.FILE_TAG_ROW
            if label.property("file_tag_active") != active:
                label.setProperty("file_tag_active", active)
                label.setStyleSheet(wanted)

    def _on_position_changed(self, position_ms):
        """Follow the playback: update the highlight and the hint time once
        per second. Does nothing while the window is hidden, so a closed
        window never keeps working in the background."""
        if not self.isVisible():
            return
        second = max(int(position_ms), 0) // 1000
        if second == self._last_second:
            return
        self._last_second = second
        self.current_timestamp_sec = second if self.is_video else self.current_timestamp_sec
        self._update_active_highlight()
        if self.is_video:
            hint_text = tr("tag_manage.hint", **self._shortcuts)
            hint_text += tr(
                "tag_manage.hint_timestamp",
                time=_format_ts(self.current_timestamp_sec),
                **self._shortcuts,
            )
            self.hint_label.setText(hint_text)

    def _go_to_timestamp(self, ts):
        viewer = self._viewer()
        if viewer is not None:
            viewer.go_to_timestamp(ts)

    def _remove_tag(self, name, timestamp_sec):
        self.tags_db.remove_tag(name, self.current_file, timestamp_sec=timestamp_sec)
        self.changed = True
        self._reload_file_tags()

    def _edit_tag(self, name, timestamp_sec):
        """Edit one entry: change its tag name and, for a timestamp entry,
        its time. The entry is moved to the new name/time (a collision with
        an existing entry just merges into it, as everywhere else)."""
        dialog = _TagEditDialog(name, timestamp_sec, self.tags_db, self)
        accepted = dialog.exec()
        new_name = dialog.result_name
        new_timestamp = dialog.result_timestamp
        # The form is short-lived - destroy it so it (and its autocomplete
        # popup) cannot pile up while the window stays open.
        dialog.deleteLater()
        if not accepted:
            return
        if new_name is None or (new_name, new_timestamp) == (name, timestamp_sec):
            return
        self.tags_db.remove_tag(name, self.current_file, timestamp_sec=timestamp_sec)
        self.tags_db.assign_tag(new_name, self.current_file, timestamp_sec=new_timestamp)
        self.changed = True
        self._reload_recent_tags()
        self._reload_file_tags()

    # ------------------------------------------------------------------
    # Playback
    # ------------------------------------------------------------------
    def _toggle_playback(self):
        viewer = self._viewer()
        if viewer is None:
            return
        self.playback_touched = True
        viewer.toggle_pause()
        self._update_play_btn()

    def _refresh_play_btn(self, *_args):
        """Slot for the player's signal - a hidden window stays idle."""
        if not self.isVisible():
            return
        self._update_play_btn()

    def _update_play_btn(self):
        """Enable Play/Pause only for videos and keep the label in sync."""
        viewer = self._viewer()
        self.play_btn.setEnabled(self.is_video and viewer is not None)
        if not self.is_video or viewer is None:
            return
        self.play_btn.setText(
            tr("manage_tags.play_btn") if viewer.is_paused() else tr("manage_tags.pause_btn")
        )

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
        self.tags_db.assign_tag(
            name, self.current_file, timestamp_sec=self._current_second()
        )
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
