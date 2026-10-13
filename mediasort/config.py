"""Configuration management for MediaSort.

Handles loading/saving the settings.json file which contains all
configurable key bindings, the seek interval for videos, and the
persisted history / favourites lists used by the file operation dialog.
"""
import json
from pathlib import Path

from .i18n import load_translations

APP_DIR = Path(__file__).resolve().parent
DEFAULT_SETTINGS_PATH = APP_DIR / "settings.json"

DEFAULT_SETTINGS = {
    # UI language code - selects the translation file
    # mediasort/translations/<language>.json (e.g. "en", "pl").
    "language": "en",
    # General navigation and action keys - active whenever an image or
    # video is being displayed (i.e. whenever the file operation dialog
    # ISN'T open). Each action accepts one OR MORE trigger strings
    # (keyboard shortcuts and/or mouse buttons/wheel).
    #
    # IMPORTANT PRIORITY RULE: if a physical key is bound both here and in
    # a context-specific section below (currently just video_keys), the
    # context-specific binding wins WHILE that context is active. E.g. by
    # default "Right" is bound to both navigation_keys.next and
    # video_keys.small_seek_forward - while viewing a video, "Right" seeks
    # by the small interval; while viewing an image, "Right" advances to
    # the next file. "PgDown" is only bound here, so it always advances to
    # the next file regardless of whether an image or a video is showing.
    "navigation_keys": {
        "quit": ["Escape"],
        "next": ["Right", "PgDown", "MouseWheelUp", "MouseForward"],
        "prev": ["Left", "PgUp", "MouseWheelDown", "MouseBack"],
        "show_copy_dialog": ["C"],
        "show_move_dialog": ["M"],
        "show_browse_dialog": ["O"],
        "toggle_select": ["/", "MouseMiddle"],
        "trash_file": ["Delete"],
        "toggle_filter": ["F"],
        "show_tag_selected_dialog": ["Ctrl+T"],
        "show_manage_tags_dialog": ["T"],
        "show_manage_all_tags_dialog": ["F9"],
        "show_browse_tag_dialog": ["Alt+T"],
        "show_db_management_dialog": ["F10"]
    },
    # Keys active only while a VIDEO is being displayed - see the priority
    # rule above. Seeking has three steps, each with its own key binding
    # and interval: small (plain arrow keys), normal (Shift+arrow) and
    # big (Ctrl+arrow).
    "video_keys": {
        "small_seek_forward": ["Right"],
        "small_seek_backward": ["Left"],
        "seek_forward": ["Shift+Right"],
        "seek_backward": ["Shift+Left"],
        "big_seek_forward": ["Ctrl+Right"],
        "big_seek_backward": ["Ctrl+Left"],
        "seek_small_seconds": 5,
        "seek_seconds": 15,
        "seek_big_seconds": 60,
        "toggle_pause": ["Space", "MouseLeft"],
        "next_timestamp_tag": ["E", "MouseWheelUp"],
        "prev_timestamp_tag": ["Q", "MouseWheelDown"],
        # Video cutting: "[" sets the start mark (A) at the current
        # position, "]" sets the end mark (B); "X" opens the cut dialog.
        "set_cut_start": ["["],
        "set_cut_end": ["]"],
        "show_cut_dialog": ["X"]
    },
    # Fraction of the video shown on the progress bar while the CTRL zoom
    # is held (0.25 = 25%). The zoomed window is anchored on the mouse
    # cursor position at the moment CTRL is pressed: its start slides
    # proportionally with the cursor, so the time under the cursor stays
    # exactly under it inside the zoomed window.
    "video_zoom_ratio": 0.25,
    # Maximum enlargement of a photo that is SMALLER than the window when
    # displayed full-screen (4.0 = up to 400% of its native size). Small
    # photos are never blown up further than this, so e.g. a 500 px wide
    # photo on a 3840 px screen is shown at most 2000 px wide (centered,
    # with black bars) instead of being stretched over the whole screen,
    # which looks blurry. Only enlargement is limited - photos LARGER than
    # the window are still shrunk to fit it. Set a very large value (e.g.
    # 1000.0) to restore the old "always fill the screen" behaviour.
    "image_max_zoom": 4.0,
    # Keys active only while the file operation (copy/move/open) dialog is
    # open.
    "file_dialog": {
        "copy": ["Alt+C"],
        "move": ["Alt+M"],
        "confirm_action": ["Ctrl+Return"],
        "mode_relative": ["R"],
        "mode_history": ["H"],
        "mode_favourites": ["F"],
        "toggle_favourite": ["Ctrl+D"],
        "edit_location": ["F2"],
        "cancel": ["Escape"],
        "invert_selection": ["I"],
        "select_all": ["A"]
    },
    "history_max_size": 20,
    # Paths of the ffmpeg/ffprobe CLIs used for cutting video fragments.
    # None = look them up in PATH (and next to the app). PySide6 ships the
    # FFmpeg *libraries* used by QtMultimedia, but no command-line tools.
    "ffmpeg_path": None,
    "ffprobe_path": None,
    # Default video-cut mode chosen in the cut dialog: "fast" (lossless
    # stream copy, exact playback thanks to the MP4 edit list) or "exact"
    # (only the few seconds at the cut boundary are re-encoded, so the
    # file itself starts at the exact requested frame).
    "cut_default_mode": "fast",
    # Whether the "clean file" (snap to keyframe) option is checked by
    # default in the cut dialog.
    "cut_clean_file": False,
    # How many levels of subfolders "Uwzglednij podfoldery" descends into
    # in the Open/Browse dialog (0 = folder only, 1 = folder + immediate
    # subfolders, 2 = also their subfolders, etc.). Kept small by default
    # to avoid scanning huge trees.
    "browse_subfolder_depth": 1,
    # Maximum number of timestamp-tag links shown overlaid on the video at
    # once. The shown window follows the playback position (see
    # main_window._visible_timestamp_tags); "+" markers indicate hidden
    # tags before/after the window.
    "max_visible_timestamp_tags": 20,
    # Tag names that mark a fragment of a video to jump over while
    # watching (see main_window._compute_skip_ranges). As soon as playback reaches
    # such a timestamp tag, it jumps to the next timestamp tag of the file
    # (whatever its name) or to the end of the video, so the tagged
    # fragment is never played. E.g. ["skip"] makes the time from every
    # "skip@MM:SS" tag up to the next tag (or the end) play automatically
    # skipped. The camelCase spelling "skipTags" is accepted as an alias.
    # Empty list = the feature is off.
    "skip_tags": [],
    # Persisted runtime state below - user-specific, so fresh installs
    # start with the neutral values (the live settings.json overrides
    # them anyway via the deep merge).
    "history": [],
    "favourites": [],
    "last_dialog_mode": "relative",
    "last_used_location": None,
    "image_extensions": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff"],
    "video_extensions": [".mp4", ".avi", ".mkv", ".mov", ".webm", ".m4v", ".wmv", ".flv"],
    # Quick-assign tags: keyboard key -> tag name (e.g. "1": "TEST_1").
    # Pressing the key assigns that tag to the current file (see
    # MainWindow._handle_key_press).
    "quick_tags": {"1": "Rating 1", "2": "Rating 2", "3": "Rating 3", "4": "Rating 4", "5": "Rating 5"}
}


class Settings:
    """Loads, merges (with defaults) and persists MediaSort's settings.json."""

    def __init__(self, path=None):
        self.path = Path(path) if path else DEFAULT_SETTINGS_PATH
        self.data = self._load()
        # Make the UI language from settings.json take effect immediately
        # (looks up mediasort/translations/<language>.json).
        load_translations(self.get("language", default="en"))

    # -- loading / saving -------------------------------------------------
    def _load(self):
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                merged = json.loads(json.dumps(DEFAULT_SETTINGS))  # deep copy of defaults
                self._deep_merge(merged, loaded)
                self.data = merged
                return merged
            except (json.JSONDecodeError, OSError):
                pass
        data = json.loads(json.dumps(DEFAULT_SETTINGS))
        self.data = data
        self.save()
        return data

    @staticmethod
    def _deep_merge(base, override):
        for k, v in override.items():
            if isinstance(v, dict) and isinstance(base.get(k), dict):
                Settings._deep_merge(base[k], v)
            else:
                base[k] = v

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
        except OSError as e:
            print(f"Warning: could not save settings to {self.path}: {e}")

    # -- generic access -----------------------------------------------------
    def get(self, *keys, default=None):
        d = self.data
        for k in keys:
            if isinstance(d, dict) and k in d:
                d = d[k]
            else:
                return default
        return d

    def set(self, *keys_and_value):
        *keys, value = keys_and_value
        d = self.data
        for k in keys[:-1]:
            d = d.setdefault(k, {})
        d[keys[-1]] = value
        self.save()

    # -- history --------------------------------------------------------
    def add_history(self, path):
        path = str(path)
        history = [p for p in self.data.get("history", []) if p != path]
        history.insert(0, path)
        max_size = self.data.get("history_max_size", 20)
        self.data["history"] = history[:max_size]
        self.save()

    def get_history(self):
        return list(self.data.get("history", []))

    # -- favourites -------------------------------------------------------
    def add_favourite(self, path):
        path = str(path)
        favs = self.data.get("favourites", [])
        if path not in favs:
            favs.append(path)
            self.data["favourites"] = favs
            self.save()

    def remove_favourite(self, path):
        path = str(path)
        favs = self.data.get("favourites", [])
        if path in favs:
            favs.remove(path)
            self.data["favourites"] = favs
            self.save()

    def is_favourite(self, path):
        return str(path) in self.data.get("favourites", [])

    def get_favourites(self):
        return list(self.data.get("favourites", []))

    # -- dialog state -----------------------------------------------------
    def set_last_dialog_mode(self, mode):
        self.data["last_dialog_mode"] = mode
        self.save()

    def get_last_dialog_mode(self):
        return self.data.get("last_dialog_mode", "relative")

    def set_last_used_location(self, path):
        self.data["last_used_location"] = str(path)
        self.save()

    def get_last_used_location(self):
        return self.data.get("last_used_location")
