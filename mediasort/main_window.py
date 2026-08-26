"""Main application window for MediaSort."""
import os
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QStackedWidget, QApplication, QLabel, QPushButton,
    QVBoxLayout, QWidget,
)
from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QKeyEvent, QMouseEvent, QWheelEvent

from .config import Settings
from .i18n import tr
from . import styles
from .key_utils import matches_any, matching_trigger
from .file_scanner import scan_media, kind_for_path
from .image_viewer import ImageViewer
from .video_viewer import VideoViewer
from .file_operation_dialog import FileOperationDialog
from .browse_dialog import BrowseDialog
from .tags_db import TagsDatabase
from .tag_assign_dialog import TagAssignDialog
from .tag_management_dialog import TagManagementDialog
from .tag_browse_dialog import TagBrowseDialog


def _format_ms(ms):
    """Format a millisecond duration as mm:ss (minutes can exceed 2 digits)."""
    if ms is None or ms < 0:
        ms = 0
    total_seconds = int(ms) // 1000
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes:02d}:{seconds:02d}"

def _pause_video_while_open(f):

    def wrapper(*args, **kwargs):
        self = args[0]
        is_video = self.current_kind() == "video"

        # if paused manually (we don't want to resume after closed)
        was_playing = False
        if is_video:
            was_playing = not self.video_viewer.is_paused()
            if was_playing:
                self.video_viewer.toggle_pause()
        #     current_ts = self.video_viewer.player.position() // 1000
        # else:
        #     current_ts = 0

        f(*args, **kwargs)

        if is_video and was_playing:
            self.video_viewer.toggle_pause()
        if is_video:
            self._update_timestamp_tags()

    return wrapper

class MainWindow(QMainWindow):
    def __init__(self, folder, settings: Settings, initial_file=None):
        super().__init__()
        self.settings = settings
        self.folder = str(Path(folder).resolve())
        self.setWindowTitle(tr("main_window.title"))
        self.setStyleSheet(styles.BG)

        self.stack = QStackedWidget(self)
        self.setCentralWidget(self.stack)

        self.image_viewer = ImageViewer(self)
        self.video_viewer = VideoViewer(self.settings, self)
        self.stack.addWidget(self.image_viewer)
        self.stack.addWidget(self.video_viewer)

        # "[x]" indicator shown in the top-right corner when the current
        # file is selected. Added as an unmanaged sibling of the stacked
        # pages so it stays on top regardless of which page is active.
        self.selection_indicator = QLabel("[x]", self.stack)
        self.selection_indicator.setStyleSheet(
            styles.SELECTION
        )
        self.selection_indicator.adjustSize()
        self.selection_indicator.hide()

        # Small "filename (x/total)" label, top-left corner. Always shown
        # while a file is loaded.
        self.file_info_label = QLabel(self.stack)
        self.file_info_label.setStyleSheet(styles.INFO_LABEL
        )
        self.file_info_label.hide()

        # Small "mm:ss / mm:ss" timestamp label, top-right corner (below
        # the selection indicator). Only shown while viewing a video.
        self.time_label = QLabel(self.stack)
        self.time_label.setStyleSheet(styles.INFO_LABEL
        )
        self.time_label.hide()
        self.video_viewer.player.positionChanged.connect(self._update_time_label)
        self.video_viewer.player.durationChanged.connect(self._update_time_label)

        # Timestamp-tag links are placed under the video's duration.  They
        # live in their own transparent container so their number can vary
        # freely from one video to another.
        self.timestamp_tags_widget = QWidget(self.stack)
        self.timestamp_tags_widget.setStyleSheet(styles.TRANSPARENT)
        self.timestamp_tags_layout = QVBoxLayout(self.timestamp_tags_widget)
        self.timestamp_tags_layout.setContentsMargins(0, 0, 0, 0)
        self.timestamp_tags_layout.setSpacing(3)
        self.timestamp_tags_layout.setAlignment(Qt.AlignRight | Qt.AlignTop)
        self._timestamp_tag_buttons = []
        self.timestamp_tags_widget.hide()

        # Set of currently selected file paths. Persists until the app is
        # closed OR the browsed folder changes (e.g. via the dialog's
        # "Open" action) - see open_folder().
        self.selected_paths = set()

        # When True, next/prev navigation (and the file-info label) only
        # consider selected files - toggled via the "filter" shortcut.
        self.filter_active = False

        # Local tags database (SQLite) for the Tags Library feature.
        self.tags_db = TagsDatabase()

        # "Tag browse" mode: when active, next/prev walk through every
        # instance (file, or file+timestamp) of a chosen tag instead of
        # the current folder's media_items - these instances can point at
        # files outside the currently open folder.
        self.tag_mode_active = False
        self.tag_mode_name = None
        self.tag_mode_instances = []
        self.tag_mode_index = 0

        self._rescan_media()
        self.current_index = 0
        if initial_file:
            self.current_index = self._find_index(initial_file)
        self._dialog_open = False
        self._active_dialog = None

        app = QApplication.instance()
        app.installEventFilter(self)

        self.showFullScreen()

        if self.media_items:
            self._show_current()
        else:
            self._show_message(tr("main_window.no_media_in_folder"))

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------
    def current_path(self):
        if self.tag_mode_active:
            if not self.tag_mode_instances:
                return None
            return self.tag_mode_instances[self.tag_mode_index][0]
        if not self.media_items:
            return None
        return self.media_items[self.current_index][0]

    def current_kind(self):
        if self.tag_mode_active:
            if not self.tag_mode_instances:
                return None
            path = self.tag_mode_instances[self.tag_mode_index][0]
            return kind_for_path(
                path,
                self.settings.get("image_extensions", default=[]),
                self.settings.get("video_extensions", default=[]),
            ) or "image"
        if not self.media_items:
            return None
        return self.media_items[self.current_index][1]

    def _rescan_media(self):
        self.media_items = scan_media(
            self.folder,
            self.settings.get("image_extensions", default=[]),
            self.settings.get("video_extensions", default=[]),
        )

    def open_folder(self, folder_path):
        """Switch browsing to a different folder in the app itself (used
        by the file operation dialog's "Open" action): loads the first
        media file found there, and next/prev navigation from then on
        stays within this new folder. The selection is reset, since
        selections from the previous folder shouldn't carry over."""
        self.folder = str(Path(folder_path).resolve())
        self._rescan_media()
        self.current_index = 0
        self.selected_paths = set()
        self.filter_active = False
        self.tag_mode_active = False
        self.video_viewer.stop()
        if self.media_items:
            self._show_current()
        else:
            self._show_message(tr("main_window.no_media_in_folder"))

    def browse_custom(self, media_items, folder_for_context=None):
        """Show a custom, precomputed list of (path, kind) files - used by
        the Browse dialog's folder/tag/type combination, which may span
        multiple folders (or none at all, if filtering by tag only).
        Reuses the normal media_items/current_index machinery, so next/
        prev, selection, filter, etc. all keep working unchanged."""
        if folder_for_context:
            self.folder = str(Path(folder_for_context).resolve())
        self.media_items = list(media_items)
        self.current_index = 0
        self.selected_paths = set()
        self.filter_active = False
        self.tag_mode_active = False
        self.video_viewer.stop()
        if self.media_items:
            self._show_current()
        else:
            self._show_message(tr("main_window.no_matching_media"))

    def enter_tag_browse_mode(self, tag_name):
        """Switch to "tag browse" mode (Alt+T): next/prev now walk through
        every instance of `tag_name` - a whole-file tag shows the file, a
        timestamp tag shows the file seeked to that second - regardless of
        which folder those files actually live in."""
        instances = self.tags_db.instances_for_tag(tag_name)
        if not instances:
            return
        self.tags_db.mark_tag_viewed(tag_name)
        self.tag_mode_active = True
        self.tag_mode_name = tag_name
        self.tag_mode_instances = instances
        self.tag_mode_index = 0
        self._show_current()

    def _find_index(self, file_path):
        """Return the index of `file_path` in media_items, or 0 if not found."""
        target = str(Path(file_path).resolve())
        for i, (path, _kind) in enumerate(self.media_items):
            if str(Path(path).resolve()) == target:
                return i
        return 0

    def _show_message(self, text):
        self.image_viewer.clear()
        self.image_viewer.label.setText(text)
        self.image_viewer.label.setStyleSheet(styles.MESSAGE_TEXT)
        self.stack.setCurrentWidget(self.image_viewer)
        self.file_info_label.hide()
        self.time_label.hide()
        self._clear_timestamp_tags()
        self._update_selection_indicator()

    def _show_current(self):
        if self.tag_mode_active:
            self._show_tag_instance()
            return
        if not self.media_items:
            self._show_message(tr("main_window.no_more_media"))
            return
        path, kind = self.media_items[self.current_index]
        self.video_viewer.stop()
        if kind == "image":
            self.image_viewer.load(path)
            self.stack.setCurrentWidget(self.image_viewer)
            self.time_label.hide()
            self._clear_timestamp_tags()
        else:
            self.video_viewer.load(path)
            self.stack.setCurrentWidget(self.video_viewer)
            self.time_label.show()
            self._update_timestamp_tags()
            self._update_time_label()
        self.setWindowTitle(tr("main_window.title_with_file", filename=os.path.basename(path)))
        self._update_file_info_label()
        self._update_selection_indicator()

    def _show_tag_instance(self):
        if not self.tag_mode_instances:
            self._show_message(tr("main_window.no_files_with_tag"))
            return
        path, timestamp_sec = self.tag_mode_instances[self.tag_mode_index]

        if not Path(path).exists():
            # Stale database entry (the file was deleted, or moved outside
            # the app so retargeting never happened) - silently drop every
            # tag on it and move on to another instance, no warning.
            self.tags_db.remove_file(path)
            self.tag_mode_instances = [inst for inst in self.tag_mode_instances if inst[0] != path]
            if not self.tag_mode_instances:
                self._show_message(tr("main_window.no_files_with_tag"))
                return
            if self.tag_mode_index >= len(self.tag_mode_instances):
                self.tag_mode_index = 0
            self._show_tag_instance()
            return

        kind = self.current_kind()
        target_ms = int(timestamp_sec or 0) * 1000

        if kind == "video":
            # If this is the same file that's already loaded, just seek -
            # reloading would restart playback and cause a visible flicker
            # even though we're only jumping between timestamps.
            already_loaded = (
                self.stack.currentWidget() is self.video_viewer
                and self.video_viewer.player.source().toLocalFile() == path
            )
            if already_loaded:
                self.video_viewer.player.setPosition(target_ms)
            else:
                self.video_viewer.stop()
                self.video_viewer.load(path, seek_ms=target_ms)
                self.stack.setCurrentWidget(self.video_viewer)
            self.time_label.show()
            self._update_timestamp_tags()
            self._update_time_label()
        else:
            self.video_viewer.stop()
            self.image_viewer.load(path)
            self.stack.setCurrentWidget(self.image_viewer)
            self.time_label.hide()
            self._clear_timestamp_tags()

        self.setWindowTitle(tr(
            "main_window.title_with_tag",
            filename=os.path.basename(path),
            tag=self.tag_mode_name,
        ))
        self._update_file_info_label()
        self._update_selection_indicator()

    def _update_file_info_label(self):
        """Set the top-left 'filename (x/total)' label. In filter mode,
        shows '(x/y -selected)'; in tag-browse mode, shows
        '(x/y -tag:NAME)' - x/y are the position among the relevant
        subset (selected files, or this tag's instances) instead of the
        full folder listing."""
        path = self.current_path()
        if not path:
            return
        filename = os.path.basename(path)

        if self.tag_mode_active:
            x = self.tag_mode_index + 1
            y = len(self.tag_mode_instances)
            text = tr(
                "main_window.file_info_tag",
                filename=filename, x=x, y=y, tag=self.tag_mode_name,
            )
        elif self.filter_active:
            selected_list = [p for p, _k in self.media_items if p in self.selected_paths]
            if path in selected_list:
                x = selected_list.index(path) + 1
                y = len(selected_list)
                text = tr("main_window.file_info_selected", filename=filename, x=x, y=y)
            else:
                # Edge case: filter is on but the current file somehow
                # isn't selected (e.g. it was just deselected). Fall back
                # to the normal counter until the next filtered navigation.
                text = tr(
                    "main_window.file_info",
                    filename=filename,
                    x=self.current_index + 1,
                    y=len(self.media_items),
                )
        else:
            text = tr(
                "main_window.file_info",
                filename=filename,
                x=self.current_index + 1,
                y=len(self.media_items),
            )

        self.file_info_label.setText(text)
        self.file_info_label.adjustSize()
        self.file_info_label.show()

    def _update_time_label(self, *_args):
        if self.current_kind() != "video":
            return
        player = self.video_viewer.player
        self.time_label.setText(f"{_format_ms(player.position())} / {_format_ms(player.duration())}")
        self.time_label.adjustSize()
        self._update_active_timestamp_tag(player.position())
        self._position_overlays()

    def _clear_timestamp_tags(self):
        """Remove timestamp-tag links from the video overlay."""
        self._timestamp_tag_buttons = []
        while self.timestamp_tags_layout.count():
            item = self.timestamp_tags_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.timestamp_tags_widget.hide()

    def _update_timestamp_tags(self):
        """Show each timestamp tag of the current video as a seek link."""
        self._clear_timestamp_tags()
        path = self.current_path()
        if self.current_kind() != "video" or not path:
            return

        timestamp_tags = sorted(
            ((name, ts) for name, ts in self.tags_db.file_tags(path) if ts is not None),
            key=lambda tag: tag[1],
        )
        for name, ts in timestamp_tags:
            button = QPushButton(
                tr(
                    "main_window.timestamp_tag_button",
                    name=name,
                    time=_format_ms(int(ts) * 1000),
                ),
                self.timestamp_tags_widget,
            )
            button.setCursor(Qt.PointingHandCursor)
            self._set_timestamp_tag_button_active(button, False)
            # Seek on press rather than release: this makes the action
            # immediate and avoids any later global mouse binding affecting
            # a completed click.
            button.pressed.connect(lambda timestamp=ts: self.video_viewer.go_to_timestamp(timestamp))
            self.timestamp_tags_layout.addWidget(button, 0, Qt.AlignRight)
            self._timestamp_tag_buttons.append((int(ts), button))

        if timestamp_tags:
            self.timestamp_tags_widget.adjustSize()
            self.timestamp_tags_widget.show()
        self._position_overlays()

    @staticmethod
    def _set_timestamp_tag_button_active(button, active):
        """Apply the standard timestamp style, optionally emphasizing it."""
        button.setProperty("timestamp_tag_active", active)
        if active:
            button.setStyleSheet(styles.ACTIVE_TS_LINK)
        else:
            button.setStyleSheet(styles.TS_LINK)
    def _update_active_timestamp_tag(self, position_ms):
        """Bold the timestamp interval containing the playback position."""
        if not self._timestamp_tag_buttons:
            return
        current_second = max(int(position_ms), 0) / 1000
        active_timestamp = max(
            (timestamp for timestamp, _button in self._timestamp_tag_buttons if timestamp <= current_second),
            default=None,
        )
        for timestamp, button in self._timestamp_tag_buttons:
            active = timestamp == active_timestamp
            if button.property("timestamp_tag_active") != active:
                self._set_timestamp_tag_button_active(button, active)

    def next_item(self):
        if self.tag_mode_active:
            self._tag_mode_step(1)
            return
        if not self.media_items:
            return
        if self.filter_active:
            self._jump_predicate(lambda item: item[0] in self.selected_paths, direction=1)
        else:
            self.current_index = (self.current_index + 1) % len(self.media_items)
            self._show_current()

    def prev_item(self):
        if self.tag_mode_active:
            self._tag_mode_step(-1)
            return
        if not self.media_items:
            return
        if self.filter_active:
            self._jump_predicate(lambda item: item[0] in self.selected_paths, direction=-1)
        else:
            self.current_index = (self.current_index - 1) % len(self.media_items)
            self._show_current()

    def _jump_to_timestamp_tag(self, direction):
        """Jump to the next/previous timestamp-tagged second in the
        CURRENT video, relative to the current playback frame. Considers
        every timestamp tag on the file regardless of tag name, and works
        the same way whether browsing a folder or browsing by tag."""
        if self.current_kind() != "video":
            return
        path = self.current_path()
        if not path:
            return
        timestamps = self.tags_db.file_timestamps(path)
        if not timestamps:
            return
        current_frame = self.video_viewer.player.position() // 1000

        if direction > 0:
            for ts in timestamps:
                if ts > current_frame:
                    self.video_viewer.player.setPosition(int(ts) * 1000)
                    return
            self.video_viewer.player.setPosition(int(timestamps[0]) * 1000)  # wrap
        else:
            for ts in reversed(timestamps):
                if ts < current_frame:
                    self.video_viewer.player.setPosition(int(ts) * 1000)
                    return
            self.video_viewer.player.setPosition(int(timestamps[-1]) * 1000)  # wrap

    def _tag_mode_step(self, direction):
        """Move to the next/previous tag instance, based on the ACTUAL
        current file and playback position rather than a stored index -
        so if the video has kept playing (or been seeked manually) past
        a tagged timestamp, Next/Prev still figures out the correct
        instance to jump to instead of relying on a stale counter.

        Instances are compared as (file_path, effective_position) tuples,
        where effective_position is 0 for a whole-file tag and the
        timestamp (seconds) for a timestamp tag. This matches how
        instances_for_tag() already orders them (file path, then time),
        so the "next" instance is simply the first one that's strictly
        greater than the current position, and "previous" is the last
        one that's strictly less - wrapping around at either end.
        """
        if not self.tag_mode_instances:
            return

        current_file = self.current_path()
        if self.current_kind() == "video":
            current_frame = self.video_viewer.player.position() // 1000
        else:
            current_frame = 0
        current_key = (current_file, current_frame)

        def effective_pos(ts):
            return 0 if ts is None else ts

        if direction > 0:
            for i, (path, ts) in enumerate(self.tag_mode_instances):
                if (path, effective_pos(ts)) > current_key:
                    self.tag_mode_index = i
                    self._show_current()
                    return
            self.tag_mode_index = 0  # wrap around to the first instance
        else:
            for i in range(len(self.tag_mode_instances) - 1, -1, -1):
                path, ts = self.tag_mode_instances[i]
                if (path, effective_pos(ts)) < current_key:
                    self.tag_mode_index = i
                    self._show_current()
                    return
            self.tag_mode_index = len(self.tag_mode_instances) - 1  # wrap to the last

        self._show_current()

    def _jump_predicate(self, predicate, direction):
        """Move current_index forward/backward (direction=+1/-1), wrapping
        around the list, until an item matching `predicate` is found."""
        if not self.media_items:
            return
        n = len(self.media_items)
        idx = self.current_index
        for _ in range(n):
            idx = (idx + direction) % n
            if predicate(self.media_items[idx]):
                self.current_index = idx
                self._show_current()
                return

    def _remove_paths_and_advance(self, moved_paths):
        """After a successful MOVE operation (of one or many files): drop
        the moved items from media_items/selected_paths, and show the
        appropriate next item (advancing only if the current file itself
        was among the moved ones)."""
        if not self.media_items or not moved_paths:
            return

        moved_resolved = {str(Path(p).resolve()) for p in moved_paths}
        self.selected_paths -= {p for p in self.selected_paths if str(Path(p).resolve()) in moved_resolved}
        self._disable_filter_if_nothing_selected()

        current_path_before = self.current_path()
        current_was_moved = (
            current_path_before is not None
            and str(Path(current_path_before).resolve()) in moved_resolved
        )

        self.media_items = [
            item for item in self.media_items
            if str(Path(item[0]).resolve()) not in moved_resolved
        ]

        if not self.media_items:
            self._show_message(tr("main_window.no_more_media"))
            return

        if current_was_moved:
            if self.current_index >= len(self.media_items):
                self.current_index = 0
            self._show_current()
        else:
            # The current file is still there; just refresh its index
            # (positions may have shifted) and update the overlays -
            # the total count in "(x/total)" has changed either way.
            target = str(Path(current_path_before).resolve()) if current_path_before else None
            for i, (p, _k) in enumerate(self.media_items):
                if str(Path(p).resolve()) == target:
                    self.current_index = i
                    break
            else:
                if self.current_index >= len(self.media_items):
                    self.current_index = 0
            self._update_file_info_label()
            self._update_selection_indicator()

    # ------------------------------------------------------------------
    # Multi-file selection
    # ------------------------------------------------------------------
    def _toggle_selection(self):
        path = self.current_path()
        if not path:
            return
        if path in self.selected_paths:
            self.selected_paths.discard(path)
        else:
            self.selected_paths.add(path)
        self._disable_filter_if_nothing_selected()
        self._update_selection_indicator()
        if self.filter_active:
            self._update_file_info_label()

    def _toggle_filter(self):
        """Toggle "show only selected files" mode (default key: F)."""
        if not self.filter_active:
            if not self.selected_paths:
                return  # nothing to filter to - ignore
            self.filter_active = True
            if self.current_path() not in self.selected_paths:
                self._jump_predicate(lambda item: item[0] in self.selected_paths, direction=1)
                return  # _show_current() already ran and refreshed the label
            self._update_file_info_label()
        else:
            self.filter_active = False
            self._update_file_info_label()

    def _disable_filter_if_nothing_selected(self):
        if self.filter_active and not self.selected_paths:
            self.filter_active = False

    def _update_selection_indicator(self):
        path = self.current_path()
        is_selected = bool(path) and path in self.selected_paths
        self.selection_indicator.setVisible(is_selected)
        self._position_overlays()

    def _position_overlays(self):
        margin = 20
        w = self.stack.width()

        # Top-left: "filename (x/total)".
        self.file_info_label.move(margin, margin)
        self.file_info_label.raise_()

        # Top-right: "[x]" selection indicator, then the time label
        # stacked directly beneath it.
        x_sel = w - self.selection_indicator.width() - margin
        self.selection_indicator.move(max(x_sel, 0), margin)
        self.selection_indicator.raise_()

        y_time = margin
        if self.selection_indicator.isVisible():
            y_time = margin + self.selection_indicator.height() + 6
        x_time = w - self.time_label.width() - margin
        self.time_label.move(max(x_time, 0), y_time)
        self.time_label.raise_()

        # Timestamp-tag links continue the same top-right stack directly
        # below the duration label.
        y_tags = y_time + self.time_label.height() + 6
        x_tags = w - self.timestamp_tags_widget.width() - margin
        self.timestamp_tags_widget.move(max(x_tags, 0), y_tags)
        self.timestamp_tags_widget.raise_()

    # ------------------------------------------------------------------
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_overlays()

    # ------------------------------------------------------------------
    # Global input handling (installed as an application-wide event filter
    # so keyboard and mouse bindings work regardless of which media-viewer
    # child widget receives the event).
    # ------------------------------------------------------------------
    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress and isinstance(event, QKeyEvent):
            # if self._handle_active_dialog_input(event, obj):
            #     return True
            if self._handle_key_press(event):
                return True
        elif event.type() == QEvent.MouseButtonPress and isinstance(event, QMouseEvent):
            # if self._handle_active_dialog_input(event, obj):
            #     return True
            # Timestamp tags are buttons, so let them receive the click
            # before evaluating MouseLeft as the video's pause shortcut.
            if self._is_timestamp_tag_click(obj, event):
                return super().eventFilter(obj, event)
            # The seek bar is a direct manipulation control, so it keeps
            # priority over configurable mouse bindings.
            if not self._is_video_progress_bar_click(obj, event):
                if self._handle_key_press(event):
                    return True
        elif event.type() == QEvent.KeyRelease and isinstance(event, QKeyEvent):
            if event.key() == Qt.Key_Control:
                self.video_viewer.set_ctrl_pressed(False)
        elif event.type() == QEvent.Wheel and isinstance(event, QWheelEvent):
            if self._handle_key_press(event):
                return True
        return super().eventFilter(obj, event)

    def _handle_active_dialog_input(self, event, obj) -> bool:
        """Route configurable bindings to the modal dialog, if it has any."""
        if not self._dialog_open or self._active_dialog is None:
            return False

        dialog = self._active_dialog
        # QMessageBox instances (for example, the confirmation to create a
        # destination folder) are separate top-level windows.  Do not send
        # their Enter/Escape keys back to the dialog underneath, otherwise
        # confirming the message box can reopen the same question in a loop.
        if isinstance(obj, QWidget) and obj.window() is not dialog:
            return False

        if isinstance(dialog, FileOperationDialog):
            return dialog._handle_dialog_key(event, obj)
        if isinstance(dialog, (BrowseDialog, TagAssignDialog)):
            return dialog._handle_key(event, obj)
        return False

    def _is_timestamp_tag_click(self, obj, event=None) -> bool:
        """Whether an event is aimed at the timestamp-tag overlay.

        The application-wide filter does not always report the button as
        ``obj``: depending on the Qt backend it may be its parent or the
        stacked page below it.  Check the widget physically under the mouse
        too, so MouseLeft can never steal a timestamp-tag click.
        """
        if self.timestamp_tags_widget.isHidden():
            return False

        if isinstance(obj, QWidget) and (
            obj is self.timestamp_tags_widget
            or self.timestamp_tags_widget.isAncestorOf(obj)
        ):
            return True

        if event is None:
            return False
        if hasattr(event, "globalPosition"):
            global_position = event.globalPosition().toPoint()
        else:
            global_position = event.globalPos()
        target = QApplication.widgetAt(global_position)
        return isinstance(target, QWidget) and (
            target is self.timestamp_tags_widget
            or self.timestamp_tags_widget.isAncestorOf(target)
        )

    def _is_video_progress_bar_click(self, obj, event: QMouseEvent) -> bool:
        """Whether a click is aimed at the video's timeline seek bar."""
        if self.current_kind() != "video":
            return False

        # The application-wide event filter can receive the event from the
        # view, its viewport, or another child. Its local coordinates are
        # therefore not reliably viewport coordinates. Convert through the
        # global position before asking the graphics view which item is hit.
        if hasattr(event, "globalPosition"):
            global_position = event.globalPosition().toPoint()
        else:
            global_position = event.globalPos()
        viewport_position = self.video_viewer.viewport().mapFromGlobal(global_position)
        item = self.video_viewer.itemAt(viewport_position)
        while item is not None:
            if item is self.video_viewer.progress_bar:
                return True
            item = item.parentItem()
        return False

    def _handle_key_press(self, event) -> bool:
        # Track CTRL state for the video progress-bar zoom effect. Never
        # consume it so it also reaches whichever widget has focus.
        if isinstance(event, QKeyEvent) and event.key() == Qt.Key_Control:
            self.video_viewer.set_ctrl_pressed(True)
            return False

        if self._dialog_open:
            return False  # let the open dialog handle its own bindings

        kind = self.current_kind()
        nav_keys = self.settings.get("navigation_keys", default={})
        video_keys = self.settings.get("video_keys", default={})
        quick_tags = self.settings.get("quick_tags", default={})

        if matches_any(event, nav_keys.get("quit", ["Escape"])):
            self.close()
            return True

        # Toggle selection of the current file.
        if matches_any(event, nav_keys.get("toggle_select", ["/"])):
            self._toggle_selection()
            return True

        # Toggle "show only selected files" filter mode.
        if matches_any(event, nav_keys.get("toggle_filter", ["F"])):
            self._toggle_filter()
            return True

        # In tag-browse mode, Next/Prev always walk through tag instances,
        # taking priority over both video seeking and normal navigation -
        # this must be checked before the video-context keys below,
        # otherwise Right/Left would just seek 15s instead of jumping to
        # the next tag instance while looking at a video.
        if self.tag_mode_active:
            if matches_any(event, nav_keys.get("next", ["Right", "PgDown"])):
                self.next_item()
                return True
            if matches_any(event, nav_keys.get("prev", ["Left", "PgUp"])):
                self.prev_item()
                return True

        # Context-specific VIDEO keys take priority over the general
        # next/prev for whichever physical key they share (by default,
        # Right/Left) - but only while a video is actually showing. Any
        # key NOT claimed here (e.g. PgDown/PgUp) falls through to the
        # general navigation check below regardless of kind.
        if kind == "video":
            seconds_small = video_keys.get("seek_small_seconds", 5)
            seconds = video_keys.get("seek_seconds", 15)
            seconds_big = video_keys.get("seek_big_seconds", 60)
            if matches_any(event, video_keys.get("small_seek_forward", ["Right"])):
                self.video_viewer.seek_seconds(seconds_small)
                return True
            if matches_any(event, video_keys.get("small_seek_backward", ["Left"])):
                self.video_viewer.seek_seconds(-seconds_small)
                return True
            if matches_any(event, video_keys.get("seek_forward", ["Shift+Right"])):
                self.video_viewer.seek_seconds(seconds)
                return True
            if matches_any(event, video_keys.get("seek_backward", ["Shift+Left"])):
                self.video_viewer.seek_seconds(-seconds)
                return True
            if matches_any(event, video_keys.get("big_seek_forward", ["Ctrl+Right"])):
                self.video_viewer.seek_seconds(seconds_big)
                return True
            if matches_any(event, video_keys.get("big_seek_backward", ["Ctrl+Left"])):
                self.video_viewer.seek_seconds(-seconds_big)
                return True
            if matches_any(event, video_keys.get("toggle_pause", ["Space", "MouseLeft"])):
                self.video_viewer.toggle_pause()
                return True
            if matches_any(event, video_keys.get("next_timestamp_tag", ["E"])):
                self._jump_to_timestamp_tag(1)
                return True
            if matches_any(event, video_keys.get("prev_timestamp_tag", ["Q"])):
                self._jump_to_timestamp_tag(-1)
                return True

        # General next/prev - always moves to the next/previous file in
        # the folder, regardless of whether it's an image or a video.
        if matches_any(event, nav_keys.get("next", ["Right", "PgDown"])):
            self.next_item()
            return True
        if matches_any(event, nav_keys.get("prev", ["Left", "PgUp"])):
            self.prev_item()
            return True

        # File operation dialog triggers (available for both images and videos)
        if matches_any(event, nav_keys.get("show_copy_dialog", ["C"])):
            self._open_file_dialog(default_action="copy")
            return True
        if matches_any(event, nav_keys.get("show_move_dialog", ["M"])):
            self._open_file_dialog(default_action="move")
            return True
        if matches_any(event, nav_keys.get("show_browse_dialog", ["O"])):
            self._open_browse_dialog()
            return True

        # Tags Library
        if matches_any(event, nav_keys.get("show_tag_selected_dialog", ["Ctrl+T"])):
            self._open_tag_assign_dialog()
            return True
        if matches_any(event, nav_keys.get("show_manage_tags_dialog", ["T"])):
            self._open_tag_management_dialog()
            return True
        if matches_any(event, nav_keys.get("show_browse_tag_dialog", ["Alt+T"])):
            self._open_tag_browse_dialog()
            return True

        # Quick Tags
        matching_quick_tag = matching_trigger(event, quick_tags.keys())
        if matching_quick_tag:
            self.tags_db.assign_tag(quick_tags.get(matching_quick_tag),self.current_path())


        return False

    # ------------------------------------------------------------------
    # File operation dialog
    # ------------------------------------------------------------------
    @_pause_video_while_open
    def _open_file_dialog(self, default_action):
        current = self.current_path()
        if not current:
            return
        self._dialog_open = True
        dialog = FileOperationDialog(
            current_file=current,
            settings=self.settings,
            default_action=default_action,
            media_items=self.media_items,
            selected_paths=self.selected_paths,
            tags_db=self.tags_db,
            parent=self,
        )
        self._active_dialog = dialog
        dialog.exec()
        self._dialog_open = False
        self._active_dialog = None

        if dialog.performed_action == "move" and dialog.affected_paths:
            self._remove_paths_and_advance(dialog.affected_paths)
        else:
            # Even on copy/cancel, the selection may have changed via the
            # dialog's invert/select-all actions - refresh the indicator.
            self._disable_filter_if_nothing_selected()
            self._update_selection_indicator()

    @_pause_video_while_open
    def _open_browse_dialog(self):
        self._dialog_open = True
        dialog = BrowseDialog(
            current_folder=self.folder,
            settings=self.settings,
            tags_db=self.tags_db,
            parent=self,
        )
        self._active_dialog = dialog
        dialog.exec()
        self._dialog_open = False
        self._active_dialog = None

        if dialog.confirmed:
            self.browse_custom(dialog.result_items, folder_for_context=dialog.result_folder)


    # ------------------------------------------------------------------
    # Tags Library
    # ------------------------------------------------------------------
    @_pause_video_while_open
    def _open_tag_assign_dialog(self):
        current = self.current_path()
        if not current:
            return
        self._dialog_open = True
        dialog = TagAssignDialog(
            current_file=current,
            settings=self.settings,
            tags_db=self.tags_db,
            media_items=self.media_items if not self.tag_mode_active else [(current, self.current_kind())],
            selected_paths=self.selected_paths,
            parent=self,
        )
        self._active_dialog = dialog
        dialog.exec()
        self._dialog_open = False
        self._active_dialog = None
        self._disable_filter_if_nothing_selected()
        self._update_selection_indicator()


    @_pause_video_while_open
    def _open_tag_management_dialog(self):
        current = self.current_path()
        if not current:
            return
        is_video = self.current_kind() == "video"
        if is_video:
            current_ts = self.video_viewer.player.position() // 1000
        else:
            current_ts = 0

        self._dialog_open = True
        dialog = TagManagementDialog(
            current_file=current,
            is_video=is_video,
            current_timestamp_sec=current_ts,
            settings=self.settings,
            tags_db=self.tags_db,
            parent=self,
        )
        dialog.exec()
        self._dialog_open = False
        if is_video:
            self._update_timestamp_tags()

    @_pause_video_while_open
    def _open_tag_browse_dialog(self):
        self._dialog_open = True
        dialog = TagBrowseDialog(settings=self.settings, tags_db=self.tags_db, parent=self)
        dialog.exec()
        self._dialog_open = False

        if dialog.confirmed and dialog.selected_tag:
            self.enter_tag_browse_mode(dialog.selected_tag)

    def closeEvent(self, event):
        app = QApplication.instance()
        app.removeEventFilter(self)
        super().closeEvent(event)
