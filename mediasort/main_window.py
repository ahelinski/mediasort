"""Main application window for MediaSort."""
import os
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QStackedWidget, QApplication, QLabel, QPushButton,
    QVBoxLayout, QWidget, QMessageBox,
)
from PySide6.QtCore import Qt, QEvent, QUrl
from PySide6.QtGui import QKeyEvent, QMouseEvent, QWheelEvent
from PySide6.QtMultimedia import QMediaPlayer

from .config import Settings
from .i18n import tr
from . import styles
from .key_utils import matches_any, matching_trigger
from .file_scanner import scan_media, kind_for_path
from .image_viewer import ImageViewer
from .video_viewer import VideoViewer
from .file_operation_dialog import FileOperationDialog
from .browse_dialog import BrowseDialog
from .cut_dialog import CutDialog, format_time
from .tags_db import TagsDatabase
from .tag_assign_dialog import TagAssignDialog
from .tag_management_dialog import TagManagementDialog
from .tag_browse_dialog import TagBrowseDialog
from .db_management_dialog import DbManagementDialog


def _format_ms(ms):
    """Format a millisecond duration as mm:ss (minutes can exceed 2 digits)."""
    if ms is None or ms < 0:
        ms = 0
    total_seconds = int(ms) // 1000
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes:02d}:{seconds:02d}"


# Default maximum number of timestamp-tag links shown overlaid on the
# video at once (overridable via the "max_visible_timestamp_tags"
# setting). The shown window follows the playback position - see
# _visible_timestamp_tags.
MAX_VISIBLE_TIMESTAMP_TAGS = 20


def _visible_timestamp_tags(tags, current_second, limit=MAX_VISIBLE_TIMESTAMP_TAGS):
    """Pick which timestamp tags to display around the playback position.

    ``tags`` is the file's full list of (name, ts) timestamp tags sorted
    by ts (ascending); ``current_second`` is the integer playback second.

    Returns ``(visible, hidden_before, hidden_after)``:

    * ``visible`` - the (name, ts) tags to show, at most ``limit``;
    * ``hidden_before`` - True when some earlier tags were cut off;
    * ``hidden_after`` - True when some later tags were cut off.

    Selection rules (per spec):

    * All tags at the exact current second ("current" tags) are always
      kept together, in the middle of the window.
    * The remaining slots are split roughly evenly between the tags just
      before and just after the current group; the "after" side gets the
      extra slot when the split is uneven.
    * When one side has fewer tags than its share, the unused slots go to
      the other side - so with no tag at the very start of the video the
      first ``limit`` tags are shown, and with no tag at the very end the
      last ``limit`` tags are shown.
    """
    before = [t for t in tags if t[1] < current_second]
    group = [t for t in tags if t[1] == current_second]
    after = [t for t in tags if t[1] > current_second]

    remaining = limit - len(group)
    if remaining <= 0:
        return group[:limit], bool(before), bool(after)

    take_before = min(remaining // 2, len(before))
    take_after = min(remaining - remaining // 2, len(after))
    unused = remaining - take_before - take_after
    if unused > 0:
        if len(before) > take_before:
            take_before = min(len(before), take_before + unused)
        elif len(after) > take_after:
            take_after = min(len(after), take_after + unused)

    visible = before[len(before) - take_before:] + group + after[:take_after]
    return visible, take_before < len(before), take_after < len(after)


def _compute_skip_ranges(tags, skip_names, duration_ms):
    """Compute the video regions that playback must jump over automatically.

    ``tags`` is the file's complete list of timestamp tags as
    ``(name, second)`` pairs; ``skip_names`` the set of tag names that
    start a skipped region; ``duration_ms`` the video's length in
    milliseconds (used only for a region that runs to the end of the file).

    A region starts at a skip tag's second and ends at the next timestamp
    tag of the file - whatever its name - or at the end of the video when
    no later tag exists. Directly following skip tags extend the same
    region, so playback jumps once instead of stepping through each of
    them. A region whose end is not known yet (no later tag and no known
    duration) is left out; it appears once the duration is known.

    Returns an ascending list of ``(start_ms, end_ms)`` pairs (with
    ``start_ms < end_ms``), non-overlapping and with no contained ranges.
    Whole-file tags (timestamp ``None``) are ignored.
    """
    if not tags or not skip_names:
        return []
    timestamps = sorted({ts for _name, ts in tags if ts is not None})
    skip_seconds = {
        ts for name, ts in tags if ts is not None and name in skip_names
    }
    if not skip_seconds:
        return []

    ranges = []
    for start_sec in sorted(skip_seconds):
        end_sec = None
        for ts in timestamps:
            if ts <= start_sec:
                continue
            if ts in skip_seconds:
                continue  # another skip tag - the region simply goes on
            end_sec = ts
            break
        start_ms = start_sec * 1000
        if end_sec is not None:
            end_ms = end_sec * 1000
        elif duration_ms and duration_ms > 0:
            end_ms = duration_ms
        else:
            continue  # unknown end (still loading) - recomputed later
        if end_ms <= start_ms:
            continue
        if ranges and end_ms <= ranges[-1][1]:
            continue  # already covered by the region that started earlier
        ranges.append((start_ms, end_ms))
    return ranges


def _tag_file_sort_key(path):
    """Sort key used to order tag instances by file - the same order the
    folder browser uses (by file name, case-insensitively)."""
    return (os.path.basename(path).lower(), path)


def _order_tag_instances(instances, current_path, current_folder):
    """Order a tag's instances for tag browsing / the magnifier button.

    Files are ordered so that browsing starts where the user is and
    continues with the current folder before moving on:

      1. the current file,
      2. the rest of the current folder, starting from the next file name
         and wrapping around to the beginning of the folder,
      3. the files from every other folder (by name).

    ``instances`` is the tag's ``[(path, timestamp_or_None), ...]`` list
    (as returned by TagsDatabase.instances_for_tag); within one file the
    instances keep their order (whole-file first, then timestamps
    ascending). Only the paths present in ``instances`` appear in the
    result, so a stale entry never gets its own position.

    The result is a list of ``(path, timestamp_or_None)`` pairs.
    """
    by_file = {}
    for path, ts in instances:
        by_file.setdefault(path, []).append(ts)
    if not by_file:
        return []

    folder = str(Path(current_folder).resolve()) if current_folder else None

    def in_current_folder(path):
        return folder is not None and str(Path(path).parent.resolve()) == folder

    files = sorted(by_file, key=_tag_file_sort_key)
    if current_path and current_path in by_file:
        current_key = _tag_file_sort_key(current_path)
        same_folder = [p for p in files if in_current_folder(p)]
        after = [p for p in same_folder if _tag_file_sort_key(p) > current_key]
        before = [p for p in same_folder if _tag_file_sort_key(p) < current_key]
        others = [p for p in files if not in_current_folder(p)]
        ordered_files = [current_path] + after + before + others
    else:
        same_folder = [p for p in files if in_current_folder(p)]
        others = [p for p in files if not in_current_folder(p)]
        ordered_files = same_folder + others

    ordered = []
    for path in ordered_files:
        ordered.extend((path, ts) for ts in by_file[path])
    return ordered


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

        self.image_viewer = ImageViewer(self.settings, self)
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
        # "Skip" tags: jump over the region that starts at such a tag (see
        # _compute_skip_ranges). Connected here so it runs on every seek/playback
        # step, whatever moved the position.
        self.video_viewer.player.positionChanged.connect(self._enforce_skip_tags)
        # Whether the next video FILE should start playing: tag-based
        # navigation (the Manage-tags magnifier and the arrows in tag mode)
        # follows the playback state of the file shown before - a playing
        # video is followed by a playing one, a paused video by a paused
        # one. Kept in sync with the real player state, and reset to
        # "play" whenever an image is shown (there is no video state to
        # carry over then).
        self._video_play_intent = True
        self.video_viewer.player.playbackStateChanged.connect(self._on_playback_state_changed)
        # A/B cut marks set with [ / ] - reflect them in the time label.
        self.video_viewer.cut_marks_changed.connect(self._update_time_label)

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
        # Full sorted list of this video's (name, ts) timestamp tags,
        # independent of the currently visible window (which follows the
        # playback position - see _refresh_timestamp_tags_window).
        self._all_timestamp_tags = []
        # The file's COMPLETE timestamp-tag list - unlike _all_timestamp_tags
        # it is never narrowed by the "timestamp tag filter", because the
        # skip-tag regions must follow the media, not the overlay.
        self._file_timestamp_tags = []
        # Cached regions to jump over (see _compute_skip_ranges and
        # _recompute_skip_ranges) plus the duration they were computed
        # for, so a region running to the end of the video is refreshed
        # once the duration is known.
        self._skip_ranges = []
        self._skip_ranges_duration_ms = None
        self._checking_skip = False
        # The (name, ts) tags currently shown as buttons, used to detect
        # whether the visible window changed and needs a rebuild.
        self._visible_keys = []
        # Optional "timestamp tag filter" set by the Browse dialog's
        # "Filtruj znaczniki czasowe" option: a set of tag names whose
        # timestamp tags are the only ones shown over the video and used
        # by the next/previous-timestamp navigation (E/Q). None = no
        # filter (all timestamp tags are shown).
        self.timestamp_tag_filter = None
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
        # Optional custom order of tag_mode_instances: {path: rank} built
        # by the Manage-tags magnifier (current file first, then the rest
        # of the current folder, then the other folders). None = the
        # standard (path, timestamp) order used by Alt+T.
        self._tag_mode_rank = None
        # State of the magnifier "tour" (see goto_tag_instance): which tag
        # is being walked, its ordered files and the current position in
        # that order. None = no tour in progress.
        self._magnifier_tour = None

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

    def release_video_handle(self):
        # Zatrzymanie NIE wystarczy - trzeba zwolnić samo źródło,
        # inaczej QMediaPlayer/WMF nadal trzyma uchwyt pliku.
        self.video_viewer.player.stop()
        self.video_viewer.player.setSource(QUrl())

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
        self._tag_mode_rank = None
        self._magnifier_tour = None
        # A fresh folder is a new browsing context - drop any timestamp
        # tag filter coming from an earlier Browse dialog confirmation.
        self.timestamp_tag_filter = None
        self.video_viewer.stop()
        if self.media_items:
            self._show_current()
        else:
            self._show_message(tr("main_window.no_media_in_folder"))

    def browse_custom(self, media_items, folder_for_context=None,
                      timestamp_tag_filter=None):
        """Show a custom, precomputed list of (path, kind) files - used by
        the Browse dialog's folder/tag/type combination, which may span
        multiple folders (or none at all, if filtering by tag only).
        Reuses the normal media_items/current_index machinery, so next/
        prev, selection, filter, etc. all keep working unchanged.

        ``timestamp_tag_filter`` optionally receives the names of the
        tags chosen with the Browse dialog's "Filtruj znaczniki czasowe"
        option - from then on, only those tags' timestamp markers are
        shown over videos and used by the E/Q next/previous-timestamp
        navigation (pass None/empty to clear any previous filter)."""
        if folder_for_context:
            self.folder = str(Path(folder_for_context).resolve())
        self.media_items = list(media_items)
        self.current_index = 0
        self.selected_paths = set()
        self.filter_active = False
        self.tag_mode_active = False
        self._tag_mode_rank = None
        self._magnifier_tour = None
        self.timestamp_tag_filter = set(timestamp_tag_filter) if timestamp_tag_filter else None
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
        # Alt+T uses the standard (path, timestamp) order.
        self._tag_mode_rank = None
        self._magnifier_tour = None
        self._show_current()

    def goto_tag_instance(self, tag_name):
        """Magnifier action of the "Manage tags" window: show the next
        occurrence of `tag_name`.

        The sequence is a "tour" of every file carrying the tag, ordered
        from where the user is (the current file, then the rest of the
        current folder - wrapping around - and only then the other
        folders), so repeated clicks walk through all of the tag's files
        and all of its timestamps and finally wrap around to the start:

          * on the current file the FIRST timestamp is used, unless the
            playback is already exactly on one of them, in which case the
            NEXT one is used; when there is none, the tour moves on;
          * a newly reached file starts at its FIRST timestamp (a timestamp
            wins over a whole-file entry on the same file); a file carrying
            only the whole-file entry is simply opened;
          * a fresh tour is built whenever the tag, the database contents
            or the displayed file changed (e.g. after using the arrow keys).

        The window stays open - the file is changed through the normal
        display path, and the application switches to tag-browse mode with
        the instances in the tour's order, so the arrow keys keep walking
        exactly the same sequence once the window is closed."""
        instances = [
            (path, ts) for path, ts in self.tags_db.instances_for_tag(tag_name)
            if Path(path).exists()
        ]
        if not instances:
            return
        # Instances per file, keeping the database order (whole-file entry
        # first, then timestamps ascending) and the timestamps alone.
        by_file = {}
        for path, ts in instances:
            by_file.setdefault(path, []).append(ts)
        timestamps = {
            path: sorted(ts for ts in ts_list if ts is not None)
            for path, ts_list in by_file.items()
        }

        current = self.current_path()
        folder = str(Path(current).parent) if current else self.folder
        second = (
            self.video_viewer.player.position() // 1000
            if self.current_kind() == "video" else 0
        )

        tour = self._magnifier_tour
        tour_current = (
            tour is not None
            and tour["tag"] == tag_name
            and tour["instances"] == instances
            and tour["files"]
            and tour["files"][tour["file_index"]] == current
        )
        if not tour_current:
            ordered = _order_tag_instances(instances, current, folder)
            files = list(dict.fromkeys(path for path, _ts in ordered))
            if not files:
                return
            if current in files:
                file_index = files.index(current)
                seconds = timestamps.get(current, [])
                # -1 = "the first timestamp is still ahead"; otherwise the
                # playback already sits on that timestamp and the tour
                # continues with the following one.
                ts_index = seconds.index(second) if second in seconds else -1
            else:
                file_index = 0
                ts_index = -1
            tour = {
                "tag": tag_name,
                "instances": instances,
                "files": files,
                "file_index": file_index,
                "ts_index": ts_index,
            }

        # Advance the tour by one occurrence.
        files = tour["files"]
        file_index = tour["file_index"]
        ts_index = tour["ts_index"]
        seconds = timestamps.get(files[file_index], [])
        if ts_index + 1 < len(seconds):
            ts_index += 1
        else:
            file_index = (file_index + 1) % len(files)
            ts_index = 0 if timestamps.get(files[file_index]) else -1
        path = files[file_index]
        seconds = timestamps.get(path, [])
        timestamp_sec = seconds[ts_index] if ts_index >= 0 else None
        tour["file_index"] = file_index
        tour["ts_index"] = ts_index
        self._magnifier_tour = tour

        self.tags_db.mark_tag_viewed(tag_name)
        # Tag-browse mode gets the very order of the tour, so the arrow
        # keys continue exactly where the magnifier left off.
        ordered = [
            (path, ts) for path in files for ts in by_file.get(path, [])
        ]
        self.tag_mode_active = True
        self.tag_mode_name = tag_name
        self.tag_mode_instances = ordered
        self._tag_mode_rank = {p: i for i, p in enumerate(files)}
        self.tag_mode_index = next(
            (
                i for i, (p, ts) in enumerate(ordered)
                if p == path and ts == timestamp_sec
            ),
            0,
        )
        self._show_current()

    def on_tag_deleted(self, tag_name):
        """Called by the "Manage tags" window right after a tag was removed
        from the database: leave tag-browse mode when that tag was being
        browsed, drop it from the timestamp-tag filter and refresh the
        overlays - without disturbing the file currently displayed."""
        if self.timestamp_tag_filter:
            self.timestamp_tag_filter.discard(tag_name)
            if not self.timestamp_tag_filter:
                self.timestamp_tag_filter = None
        if self.tag_mode_active and self.tag_mode_name == tag_name:
            target = self.current_path()
            self.tag_mode_active = False
            self.tag_mode_name = None
            self.tag_mode_instances = []
            self.tag_mode_index = 0
            self._tag_mode_rank = None
            self._magnifier_tour = None
            if target and os.path.exists(target):
                # Keep showing the same file, now as an ordinary folder
                # entry, so navigation and the info label stay correct.
                self.folder = str(Path(target).parent)
                self._rescan_media()
                self.current_index = self._find_index(target)
            self._show_current()
            return
        if self.current_kind() == "video":
            self._update_timestamp_tags()

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
            # No video state to carry over from an image - the next video
            # shown by the Manage-tags magnifier starts playing.
            self._video_play_intent = True
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
                # A whole-file tag carries no time, so the current frame
                # stays as it is; a timestamp tag seeks to its second.
                if timestamp_sec is not None:
                    self.video_viewer.player.setPosition(target_ms)
            else:
                # Follow the playback state of the file shown before: a
                # playing video is followed by a playing one, a paused
                # video by a paused one (captured before stop(), which
                # itself reports the "stopped" state).
                autoplay = self._video_play_intent
                self.video_viewer.stop()
                self.video_viewer.load(path, seek_ms=target_ms, autoplay=autoplay)
                self.stack.setCurrentWidget(self.video_viewer)
            self.time_label.show()
            self._update_timestamp_tags()
            self._update_time_label()
        else:
            self.video_viewer.stop()
            # No video state to carry over from an image - the next video
            # starts playing unless the user pauses it.
            self._video_play_intent = True
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
        text = f"{_format_ms(player.position())} / {_format_ms(player.duration())}"
        cut_a, cut_b = self.video_viewer.get_cut_marks()
        if cut_a is not None or cut_b is not None:
            parts = []
            if cut_a is not None:
                parts.append(f"A {format_time(cut_a)}")
            if cut_b is not None:
                parts.append(f"B {format_time(cut_b)}")
            text += "  [" + " · ".join(parts) + "]"
        self.time_label.setText(text)
        self.time_label.adjustSize()
        self._refresh_timestamp_tags_window()
        self._position_overlays()

    def _clear_timestamp_tags(self):
        """Remove the whole timestamp-tag overlay (chips and "+" markers)
        and forget the current video's tag list. Used when switching away
        from a video or when showing a full-screen message."""
        self._timestamp_tag_buttons = []
        self._visible_keys = []
        self._all_timestamp_tags = []
        self._file_timestamp_tags = []
        self._skip_ranges = []
        self._skip_ranges_duration_ms = None
        self._remove_timestamp_tag_items()

    def _remove_timestamp_tag_items(self):
        """Delete every widget in the timestamp-tag overlay layout without
        touching the cached tag list (so the window can be rebuilt)."""
        self._timestamp_tag_buttons = []
        self._visible_keys = []
        while self.timestamp_tags_layout.count():
            item = self.timestamp_tags_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.timestamp_tags_widget.hide()

    def _update_timestamp_tags(self):
        """Reload the current video's timestamp tags and rebuild the
        overlay around the current playback position."""
        path = self.current_path()
        if self.current_kind() != "video" or not path:
            self._clear_timestamp_tags()
            return

        all_timestamp_tags = sorted(
            ((name, int(ts)) for name, ts in self.tags_db.file_tags(path) if ts is not None),
            key=lambda tag: tag[1],
        )
        # The skip-tag regions always follow the whole file, even while the
        # display filter below hides some tags.
        self._file_timestamp_tags = all_timestamp_tags
        # With the Browse dialog's "Filtruj znaczniki czasowe" option
        # active, only timestamp tags of the chosen tags are shown.
        timestamp_tags = all_timestamp_tags
        if self.timestamp_tag_filter:
            timestamp_tags = [
                t for t in all_timestamp_tags if t[0] in self.timestamp_tag_filter
            ]
        self._all_timestamp_tags = list(timestamp_tags)
        self._recompute_skip_ranges()
        self._refresh_timestamp_tags_window(force=True)
        self._position_overlays()

    # -- "skip" tags ------------------------------------------------------
    def _skip_tag_names(self):
        """Names of the timestamp tags that mark a region to jump over -
        the "skip_tags" setting (a list; a plain string is accepted too,
        for convenience). The camelCase spelling "skipTags" is accepted as
        an alias. Anything else (including a missing key) means "no skip
        tags" - the feature is simply off."""
        names = self.settings.get("skip_tags", default=None)
        if names is None:
            names = self.settings.get("skipTags", default=[])
        if isinstance(names, str):
            names = [names]
        if not isinstance(names, (list, tuple, set)):
            return set()
        return {str(name).strip() for name in names if str(name).strip()}

    def _recompute_skip_ranges(self):
        """Refresh the cached regions to jump over for the current video
        (see _compute_skip_ranges). The current duration is remembered so the
        regions are refreshed automatically once it becomes known."""
        duration_ms = self.video_viewer.player.duration()
        self._skip_ranges_duration_ms = duration_ms
        self._skip_ranges = _compute_skip_ranges(
            self._file_timestamp_tags, self._skip_tag_names(), duration_ms
        )

    def _enforce_skip_tags(self, position_ms):
        """Jump over a skip-tag region as soon as the playback position
        reaches its start. Regions running to the end of the video are
        refreshed lazily, because the duration can become known only after
        the file's tags were loaded."""
        if self._checking_skip:
            return
        if self.video_viewer.player.duration() != self._skip_ranges_duration_ms:
            self._recompute_skip_ranges()
        for start_ms, end_ms in self._skip_ranges:
            if start_ms <= position_ms < end_ms:
                self._checking_skip = True
                try:
                    self.video_viewer.player.setPosition(int(end_ms))
                finally:
                    self._checking_skip = False
                return

    def _on_playback_state_changed(self, state):
        """Keep _video_play_intent in sync with the real playback state, so
        tag-based navigation can start the next file the same way the
        current one is playing (or paused)."""
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self._video_play_intent = True
        elif state in (QMediaPlayer.PlaybackState.PausedState,
                       QMediaPlayer.PlaybackState.StoppedState):
            self._video_play_intent = False

    def _refresh_timestamp_tags_window(self, force=False):
        """Recompute which timestamp tags fit on screen around the current
        playback position and rebuild the overlay when that window changes.

        Called on every playback position change (via _update_time_label)
        and after the tag set itself changes (_update_timestamp_tags).
        Rebuilding the buttons is skipped while the visible window is
        unchanged - only the active-interval highlight is updated then.
        """
        if not self._all_timestamp_tags:
            self._remove_timestamp_tag_items()
            return
        limit = self.settings.get(
            "max_visible_timestamp_tags", default=MAX_VISIBLE_TIMESTAMP_TAGS
        )
        try:
            limit = max(1, int(limit))
        except (TypeError, ValueError):
            limit = MAX_VISIBLE_TIMESTAMP_TAGS
        current_second = max(self.video_viewer.player.position(), 0) // 1000
        visible, hidden_before, hidden_after = _visible_timestamp_tags(
            self._all_timestamp_tags, current_second, limit
        )

        if not force and visible == self._visible_keys:
            self._update_active_timestamp_tag(self.video_viewer.player.position())
            return

        self._rebuild_timestamp_tag_buttons(visible, hidden_before, hidden_after)
        self._update_active_timestamp_tag(self.video_viewer.player.position())

    def _rebuild_timestamp_tag_buttons(self, visible, hidden_before, hidden_after):
        """(Re)create the timestamp-tag chips for ``visible`` and the "+"
        overflow markers, in order: hidden-previous marker, chips,
        hidden-next marker."""
        self._remove_timestamp_tag_items()
        self._visible_keys = list(visible)

        plus_above = QLabel("+", self.timestamp_tags_widget)
        plus_above.setStyleSheet(styles.TS_MORE)
        plus_above.setAlignment(Qt.AlignCenter)
        plus_above.setVisible(hidden_before)
        self.timestamp_tags_layout.addWidget(plus_above, 0, Qt.AlignRight)

        for name, ts in visible:
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

        plus_below = QLabel("+", self.timestamp_tags_widget)
        plus_below.setStyleSheet(styles.TS_MORE)
        plus_below.setAlignment(Qt.AlignCenter)
        plus_below.setVisible(hidden_after)
        self.timestamp_tags_layout.addWidget(plus_below, 0, Qt.AlignRight)

        self.timestamp_tags_widget.adjustSize()
        self.timestamp_tags_widget.show()

    @staticmethod
    def _set_timestamp_tag_button_active(button, active):
        """Apply the standard timestamp style, optionally emphasizing it."""
        button.setProperty("timestamp_tag_active", active)
        if active:
            button.setStyleSheet(styles.ACTIVE_TS_LINK)
        else:
            button.setStyleSheet(styles.TS_LINK)

    def _update_active_timestamp_tag(self, position_ms):
        """Bold the timestamp interval containing the playback position
        among the currently visible tags."""
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
        every timestamp tag on the file regardless of tag name (or only
        the timestamp tags of the tags chosen via the Browse dialog's
        "Filtruj znaczniki czasowe" option when that filter is active),
        and works the same way whether browsing a folder or by tag."""
        if self.current_kind() != "video":
            return
        path = self.current_path()
        if not path:
            return
        timestamps = self.tags_db.file_timestamps(path)
        if self.timestamp_tag_filter:
            timestamps = sorted({
                ts for name, ts in self.tags_db.file_tags(path)
                if ts is not None and name in self.timestamp_tag_filter
            })
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

    def _tag_instance_key(self, path, timestamp_sec):
        """Sort key of one tag instance, matching the order of
        tag_mode_instances.

        Alt+T keeps the standard (path, timestamp) order; the Manage-tags
        magnifier installs a custom file order (current file first, then
        the rest of the current folder, then the other folders) in
        _tag_mode_rank. ``timestamp_sec`` None (whole-file) sorts as 0."""
        position = 0 if timestamp_sec is None else timestamp_sec
        rank = self._tag_mode_rank.get(path) if self._tag_mode_rank else None
        if rank is None:
            return (0, path, position)
        return (1, rank, position)

    def _tag_mode_step(self, direction):
        """Move to the next/previous tag instance, based on the ACTUAL
        current file and playback position rather than a stored index -
        so if the video has kept playing (or been seeked manually) past
        a tagged timestamp, Next/Prev still figures out the correct
        instance to jump to instead of relying on a stale counter.

        Instances are compared with _tag_instance_key: file order first,
        then the effective position (0 for a whole-file tag, the second
        for a timestamp tag). "Next" is the first instance strictly after
        the current position, "previous" the last one strictly before it -
        wrapping around at either end.
        """
        if not self.tag_mode_instances:
            return

        current_file = self.current_path()
        if self.current_kind() == "video":
            current_frame = self.video_viewer.player.position() // 1000
        else:
            current_frame = 0
        current_key = self._tag_instance_key(current_file, current_frame)

        if direction > 0:
            for i, (path, ts) in enumerate(self.tag_mode_instances):
                if self._tag_instance_key(path, ts) > current_key:
                    self.tag_mode_index = i
                    self._show_current()
                    return
            self.tag_mode_index = 0  # wrap around to the first instance
        else:
            for i in range(len(self.tag_mode_instances) - 1, -1, -1):
                path, ts = self.tag_mode_instances[i]
                if self._tag_instance_key(path, ts) < current_key:
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
            # Cutting: set the A/B marks and open the cut dialog.
            if matches_any(event, video_keys.get("set_cut_start", ["["])):
                self._set_cut_mark("start")
                return True
            if matches_any(event, video_keys.get("set_cut_end", ["]"])):
                self._set_cut_mark("end")
                return True
            if matches_any(event, video_keys.get("show_cut_dialog", ["X"])):
                self._open_cut_dialog()
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

        # Database management
        if matches_any(event, nav_keys.get("show_db_management_dialog", ["F10"])):
            self._open_db_management_dialog()
            return True

        # Quick Tags
        matching_quick_tag = matching_trigger(event, quick_tags.keys())
        if matching_quick_tag:
            self.tags_db.assign_tag(quick_tags.get(matching_quick_tag),self.current_path())


        return False

    # ------------------------------------------------------------------
    # Video cutting
    # ------------------------------------------------------------------
    def _set_cut_mark(self, which):
        """Set the A ("start") or B ("end") cut mark at the current
        playback position (keys [ / ] while watching a video)."""
        if self.current_kind() != "video":
            return
        position = self.video_viewer.player.position()
        if position < 0:
            return
        if which == "start":
            self.video_viewer.set_cut_start(position)
        else:
            self.video_viewer.set_cut_end(position)
        self._update_time_label()

    @_pause_video_while_open
    def _open_cut_dialog(self):
        current = self.current_path()
        if not current or self.current_kind() != "video":
            return
        cut_a, cut_b = self.video_viewer.get_cut_marks()
        duration = self.video_viewer.player.duration()
        self._dialog_open = True
        dialog = CutDialog(
            source_path=current,
            folder=Path(current).parent,
            settings=self.settings,
            duration_ms=duration,
            a_ms=cut_a,
            b_ms=cut_b,
            parent=self,
        )
        self._active_dialog = dialog
        dialog.exec()
        self._dialog_open = False
        self._active_dialog = None

        if dialog.result_path:
            self._handle_cut_result(dialog, source_path=current)

    def _handle_cut_result(self, dialog, source_path):
        """Post-cut bookkeeping shared by the dialog flow and tests:
        copy the source's timestamp tags that fall inside the fragment,
        jump to the new file when it landed in the browsed folder and
        confirm the result."""
        out_path = dialog.result_path
        if not out_path:
            return

        # Copy timestamp tags from the source video that lie within the
        # produced fragment, shifted by its (possibly key-frame-snapped)
        # start - e.g. a tag at 0:12 of a fragment cut from 0:10.7 becomes
        # a tag at ~0:01 of the new file. Whole-file tags stay behind.
        if (dialog.result_start_ms is not None
                and dialog.result_end_ms is not None
                and Path(out_path).suffix.lower() in self.settings.get(
                    "video_extensions", default=[])):
            try:
                self.tags_db.copy_timestamp_tags_to_fragment(
                    source_path, out_path,
                    dialog.result_start_ms, dialog.result_end_ms,
                )
            except Exception:  # noqa: BLE001 - never block the cut on tag copies
                pass

        same_folder = Path(out_path).parent.resolve() == Path(self.folder).resolve()
        if same_folder:
            # The new file appeared in the currently browsed folder - rescan
            # and jump straight to it so it is immediately visible/playable.
            self._rescan_media()
            self.current_index = self._find_index(out_path)
            if self.media_items:
                self._show_current()
            else:
                self._show_message(tr("main_window.no_media_in_folder"))
            # The freshly loaded cut file auto-plays - pause it so no audio
            # runs behind the confirmation box (the _pause_video_while_open
            # wrapper resumes playback once the box closes).
            if self.current_kind() == "video" and not self.video_viewer.is_paused():
                self.video_viewer.pause()
        # Modal confirmation. The app-wide event filter must not interpret
        # clicks/keys aimed at the message box as global shortcuts (e.g.
        # MouseLeft = pause/resume while a video is showing), otherwise the
        # OK button would never receive the click. Keeping _dialog_open set
        # suppresses all global bindings for the box's lifetime.
        self._dialog_open = True
        try:
            QMessageBox.information(
                self,
                tr("cut.success_title"),
                tr("cut.saved_to", path=out_path),
            )
        finally:
            self._dialog_open = False


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
            self.browse_custom(
                dialog.result_items,
                folder_for_context=dialog.result_folder,
                timestamp_tag_filter=dialog.result_filter_tags,
            )


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

    def _open_db_management_dialog(self):
        """Open the database window (F10) and its "Manage tags" window.

        A playing video is paused while the windows are open (so the
        database work isn't done over running playback), but the Manage-tags
        Play/Pause button can start it again; when the user did use that
        button the playback state is left exactly as they set it, otherwise
        the state from opening is restored."""
        is_video = self.current_kind() == "video"
        was_playing = is_video and not self.video_viewer.is_paused()
        if was_playing:
            self.video_viewer.toggle_pause()

        self._dialog_open = True
        dialog = DbManagementDialog(
            tags_db=self.tags_db, parent=self, main_window=self
        )
        self._active_dialog = dialog
        dialog.exec()
        self._dialog_open = False
        self._active_dialog = None

        if is_video and was_playing and not dialog.playback_touched:
            # Resume the video the window was opened over - but only while a
            # video is really shown (a magnifier jump to a photo must not
            # start the hidden player in the background).
            if self.current_kind() == "video":
                self.video_viewer.toggle_pause()
        if is_video:
            self._update_timestamp_tags()
        dialog.deleteLater()

    def closeEvent(self, event):
        app = QApplication.instance()
        app.removeEventFilter(self)
        super().closeEvent(event)
