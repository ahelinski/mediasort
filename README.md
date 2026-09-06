# MediaSort

A Python application for full-screen browsing and sorting of photos and
videos, with configurable keyboard shortcuts and a built-in dialog for
quickly copying/moving files to chosen folders.

## Installation

Requires Python 3.9+.

```bash
pip install -r requirements.txt
```

The application uses **PySide6** (Qt) together with the `QtMultimedia` module
for video playback. On Linux, video playback requires an installed multimedia
backend (usually FFmpeg is already bundled with PySide6 — check whether you
see the `Using Qt multimedia with FFmpeg` message at startup). If
audio/video do not work, install the system GStreamer/FFmpeg libraries
according to the Qt documentation for your distribution.

### Windows — in-place installation

The scripts in the repository install the application directly into the
project directory and do not require administrator privileges:

```bat
install_windows.cmd
```

To also install ffmpeg right away (required by the "Cut fragment" feature,
key `X`), run the installer with the `-WithFFmpeg` option — it will download
`ffmpeg.exe`/`ffprobe.exe` into the `tools\` directory and write their paths
into the settings:

```bat
install_windows.cmd -WithFFmpeg
```

The installer:
1. creates the `.venv` virtual environment and installs the dependencies
   from `requirements.txt` into it;
2. builds a small `MediaSort.exe` from `packaging/windows/launcher.py`
   (PyInstaller, no console), which launches the actual application from the
   venv — the Windows equivalent of the Linux `ms.desktop` file pointing to
   `.venv/bin/python3`;
3. registers `MediaSort.exe` in the **Open with** menu for images
   (`.jpg .jpeg .png .gif .bmp .webp .tif .tiff`) and videos
   (`.mp4 .avi .mkv .mov .webm .m4v .wmv .flv`) — the extension list is read
   directly from `mediasort/config.py`.

After installation, double-clicking a photo/video (or right-click → *Open
with* → MediaSort) opens the folder containing that file and jumps to it.

To make MediaSort the **default** application for a given type, choose it
once: right-click a file → *Open with* → *Choose another app* → MediaSort →
check *Always*. The installer deliberately does not overwrite default file
associations: modern Windows protects the user's choice (the `UserChoice`
mechanism), and forcing default programs from a script is ineffective or
requires user interaction.

Uninstalling (removes `MediaSort.exe`, the `.venv` and its own registry
entries; source code and application data are kept):

```bat
uninstall_windows.cmd
```

Because the installer does not overwrite other programs' default
associations, there is nothing to "restore" — the uninstaller removes only
its own entries under `HKCU\Software\Classes` (ProgID `MediaSort.Media`,
`OpenWithProgids` entries and `Applications\MediaSort.exe`). If MediaSort
was previously chosen as the default program, Windows will offer a program
choice the next time such a file is opened. Additional uninstaller options:
`-Force` (no questions) and `-DeleteData` (also remove `settings.json`,
`tags.db`, logs).

Updating the code after a `git pull` does not require reinstallation (the
exe runs the code directly from the repo). `MediaSort.exe` is rebuilt
automatically only when `packaging/windows/launcher.py` changes; force a
package update with
`.venv\Scripts\python.exe -m pip install --upgrade -r requirements.txt`.

## Running

Open a whole folder (starts at the first file alphabetically):

```bash
python main.py /path/to/folder/with/photos
```

Open a **specific file** — the application loads the folder it resides in
and immediately jumps to that file (the `←`/`→` arrows still switch to
other files in the same folder):

```bash
python main.py /path/to/folder/photo.jpg
```

If nothing is given, the current directory is used:

```bash
python main.py
```

A custom settings file:

```bash
python main.py /path/to/folder --settings /path/to/my_settings.json
```

By default, settings are kept in `mediasort/settings.json` (the file is
created automatically at first launch if it does not exist).

## Features

### Navigation
- `→` — next file in the folder (while viewing photos); while viewing a
  video it instead seeks by 15 s (see the Video section) — the video context
  takes priority for this key.
- `←` — analogously, previous file for photos / seek backward for videos.
- `PgDown` / `PgUp` — always go to the next/previous file in the folder,
  **regardless of whether a photo or a video is currently displayed** — this
  guarantees you can always move from a video to a photo and back, even when
  `→`/`←` are busy seeking. Navigation wraps around at the ends of the
  list.

### File information (small on-screen text)
- Top-left corner: `{file name} ({number}/{total number of files})`, always
  visible, updated on every file change.
- Top-right corner, videos only: `{current time mm:ss} / {total time mm:ss}`,
  updated live during playback. If the file is also selected (see below),
  the time label moves down so it does not overlap the `[x]` marker.

### Selecting multiple files
- `/` — selects or deselects the current file. The selection persists until
  the application is closed or the browsed file set changes (e.g. through
  the Open/Browse dialog, `O`) — the selection from a previous set is not
  carried over.
- When the current file is selected, an `[x]` marker appears in the
  top-right corner of the screen.
- The copy/move dialog has an additional panel on the right side:
  - **Operation context**: "Selected" (default) or "Current file" — decides
    whether `Enter`/`Alt+C`/`Alt+M` apply to all selected files or only to
    the currently displayed one. If the "Selected" context is chosen but
    nothing is actually selected, the operation defaults to the current file
    (without an extra warning).
  - **Invert selection (i)** — selects all unselected files in the folder
    and deselects those selected so far.
  - **Select all (a)** — selects all files in the folder.
  - **Selection summary** — three sections, "Selected", "Remaining" and
    "Folder" (preview of the folder currently chosen in the destination
    list), with small file previews: if a group contains 3 files or fewer,
    each one is previewed; otherwise the first and last file are shown with
    a count of the files in between. Videos show a generic play icon
    (no frame decoding).
- **Filter (`F`)** — toggles a mode that shows only selected files:
  - If the current file is not selected when the filter is enabled, the
    application immediately jumps to the next selected file.
  - While the filter is on, `→`/`←` jump only between selected files
    (wrapping at the ends).
  - The label in the top-left corner then takes the form
    `{file name} (x/y -selected)`, where `x` is the current file's position
    among the selected ones and `y` is the total number of selected files.
  - Pressing `F` again disables the filter and restores normal
    navigation/label.
  - If nothing is selected, `F` does nothing (there is nothing to filter).
    The filter turns itself off if the selection drops to zero while it is
    active (e.g. after deselecting the last file or after moving all
    selected files).

### Photos
- Full-screen display on a black background.
- A photo is scaled to fill the screen while keeping its aspect ratio, but
  is never enlarged by more than the `image_max_zoom` setting (default
  `4.0` = 400% of its native size). Small photos are therefore shown
  centered with black bars around them instead of being stretched across
  the whole screen, which would look blurry (e.g. a 500 px wide photo on a
  3840 px screen is displayed at most 2000 px wide). Photos **larger** than
  the screen are still shrunk to fit it. Set `image_max_zoom` to a very
  large value (e.g. `1000.0`) to restore the old "always fill the screen"
  behaviour.
- `Esc` — closes the application.
- `→` — next photo/file in the folder.
- `←` — previous photo/file in the folder.
- Photo orientation is read from the EXIF `Orientation` tag (just like in
  other viewers), so photos taken with a rotated camera display in the
  correct, upright orientation.

### Videos
- Full-screen playback.
- `→` — seek 15 s forward (configurable interval).
- `←` — seek 15 s backward.
- `Space` or the **left mouse button** (clicking outside the progress bar) —
  pauses or resumes playback.
- `E` — jumps to the **next timestamp tag** in the current file relative to
  the current frame; `Q` — to the **previous** one. It takes into account
  ALL timestamp tags in that file, regardless of their name (and when
  browsing by a specific tag — also timestamps of other tags, not only the
  browsed one; when the "Filter timestamp tags" option of the Open/Browse
  dialog is active — only the selected tags' timestamps). Navigation wraps
  at the ends of the tag list. Works only while watching a video.
- Progress bar:
  - normally takes up 0.5% of the screen height,
  - when the cursor is in the bottom quarter of the screen, the bar grows to
    10% of the screen height and becomes semi-transparent (50% opacity),
  - holding `Ctrl` "zooms" the bar — at the moment the key is pressed the
    range freezes at a slice of the video length (25% by default,
    configurable via the `video_zoom_ratio` setting in settings.json),
    anchored on the **mouse cursor**: the slice's start slides
    proportionally with the cursor's horizontal position (cursor at the
    left edge -> the very start of the video, at the right edge -> the
    very end), so the time under the cursor stays exactly under it inside
    the zoomed slice. The range does not move further while `Ctrl` is
    held, even if the video keeps playing,
  - **clicking (or dragging with the left mouse button held) on the bar
    seeks the video to the corresponding position** — in normal mode relative
    to the whole video length, and in zoom mode (`Ctrl`) relative to the
    currently displayed, frozen range.
  - The bar can also show **cutting marks** (see below).

### Cutting a video fragment (without transcoding)

- `[` — sets the **start** (A) of the fragment to cut at the current
  position; `]` — the **end** (B). The marks are drawn on the progress bar
  (green and orange tick, highlighted A–B range) and shown in the time label
  in the top-right corner (`[A 0:10,7 · B 0:15,0]`). Changing the file
  clears the marks.
- `X` — opens the **"Cut fragment"** dialog (the video is paused then). The
  dialog lets you adjust the A/B times (format `m:ss` or `m:ss.t`, e.g.
  `1:30.5`), choose the cut mode and the destination folder, and the name of
  the new file (the source is never overwritten; name collisions are
  resolved by appending ` (1)`, ` (2)`, …). The window opens immediately —
  it does not scan keyframes before the user confirms the choice.
- After clicking **"Cut"** a progress bar appears right away, and all the
  work (keyframe analysis for the exact/clean mode and the FFmpeg cut
  itself) runs in the background on a separate thread — the window does not
  freeze even with very large files. The bar is "working" during analysis
  and shows a percentage during the cut; the exact result range (after
  snapping to a keyframe) appears as soon as the analysis finishes. The
  operation can be cancelled. A file saved to the currently browsed folder
  is immediately visible in navigation.
- **Timestamp tags follow the fragment**: tags assigned to seconds of the
  source that fall inside the cut fragment are automatically copied to the
  new file with the time shifted by the fragment start — e.g. a tag `@0:12`
  in a fragment cut from 0:10,7 becomes the `@0:01` tag of the new file
  (the actual, possibly keyframe-snapped, start is taken into account). A
  tag satisfying `start ≤ tag time < end` of the fragment is copied; a mark
  exactly at the fragment end and tags assigned to the whole file (not to a
  second) are not copied. Duplicates are skipped and the source is left
  untouched.

Cutting is based on FFmpeg in **stream copy** mode (`-c copy`), i.e. a
remux of packets — the video is **not transcoded**, so the operation is
lossless and takes a fraction of a second per amount of material. The
`ffmpeg` and `ffprobe` tools are required (PySide6 ships only the FFmpeg
libraries for QtMultimedia, without a CLI). The application looks for them
in this order: `ffmpeg_path`/`ffprobe_path` from `settings.json` → PATH →
binaries in `tools/` next to the code. On Windows the simplest way is to
run the installer with `-WithFFmpeg`:

```bat
install_windows.cmd -WithFFmpeg
```

Cut modes in the dialog:
- **Fast (lossless remux)** — default. `ffmpeg -ss A -to B -c copy`: modern
  players (including MediaSort) start playback exactly at A; the file may
  physically contain a few hidden frames ("pre-roll") from the previous
  keyframe, invisible during playback.
- **Exact (boundary re-encode)** — only the few-second segment between A and
  the next keyframe is transcoded (with the source's parameters), the rest is
  copied losslessly and then joined. The fragment starts exactly at the
  requested frame and the file is "clean". Available for H.264/HEVC.
- **Clean file (keyframe)** — an option of the fast mode: the start is
  snapped to the nearest keyframe (before or after the mark), so the file
  begins at a real keyframe and plays everywhere, but the mark may shift by
  a fraction of a second. Keyframe analysis happens only after the cut is
  confirmed (in the background), and the actual result range is shown in the
  window as soon as the analysis finishes — opening the dialog and editing
  times never requires scanning the file.

Detailed technical description and tests: `docs/plan-wycinanie-wideo.md`.

### File operation dialog (copy / move)

This dialog serves only to copy and move files — browsing files (formerly
the third action, "Open") has been moved into a separate Open/Browse dialog
(`O`), described in the next section.

- `C` — opens the dialog with the default action **Copy**.
- `M` — opens the dialog with the default action **Move**.
- **In Relative mode**: `Enter` **navigates** to the selected position in
  the list (enters a subfolder or goes up via `...`) instead of running the
  action — so you can freely descend and come back. To still run the
  default action (copy/move) in Relative mode, use `Ctrl+Enter`.
- **In History/Favourites modes** (where there is no subfolder navigation):
  `Enter` normally runs the default action, as before.
- `Ctrl+Enter` — always runs the default action (copy/move), regardless of
  the mode.
- `Alt+C` — forces **copying**, regardless of the default action the dialog
  was opened with.
- `Alt+M` — forces **moving**, analogously.
- After **copying** the dialog closes and the application stays on the same
  file.
- After **moving** the dialog closes and the next file from the list is
  loaded automatically.
- If the operation context is "Selected" but nothing is selected, the
  operation defaults to the current file (see the "Selecting" section).
- The `↑`/`↓` arrows — navigate the location list (the first entry is
  selected by default).
- Above the list there is a location field that normally mirrors the
  selected entry of the list. Clicking it or pressing `F2` turns it into an
  editable text field with the same value — you can type your own path
  freely:
  - `Enter` confirms the change and immediately runs the dialog's default
    action (copy or move) with the typed value, regardless of the list
    selection,
  - `Esc` cancels editing (the label returns to the previous value).
  - After clicking Copy/Move the system tries to use exactly that value as
    the destination — if the folder does not exist, it offers to create it;
    if the path is invalid (e.g. points to an existing file instead of a
    folder), it shows an error and does not close the window.
- Location list modes (`R`/`H`/`F` switch the mode):
  - **Relative (R)** — shows the subfolders of the folder containing the
    current file. The `...` entry goes one level up (hidden when at the
    filesystem root). Selecting any subfolder and pressing `Enter` enters it
    (and so on, arbitrarily deep).
  - **History (H)** — up to 20 most recently used locations (newest first).
    If the history is empty, the current file's folder is selected by
    default.
  - **Favourites (F)** — a list of folders added manually by the user. The
    most recently used location is selected by default (if it is on the
    favourites list).
- `Ctrl+D` (or the "Favourites +/-" button) — adds/removes the currently
  selected location from favourites (available in Relative and History
  modes; in Favourites mode it only allows removing an entry).
- The application remembers the most recently used list mode and restores it
  by default the next time the dialog opens (first launch = Relative mode).

### Open / Browse dialog

A separate dialog (key `O`) for choosing **what to browse** — it replaces
the old "Open" action of the copy/move dialog. It has three columns next to
each other:

1. **Folder** — works exactly like the location list in the copy/move dialog
   (Relative/History/Favourites modes, `R`/`H`/`F`, subfolder navigation
   via `Enter` in Relative mode, manual path editing via `F2`/clicking) —
   with the difference that **nothing is selected by default**: choosing a
   folder is optional. The "Clear folder" button clears the choice.
   - Below the folder choice there is an **"Include subfolders"** checkbox —
     when checked, the system also shows files from the subfolders of the
     chosen folder (by default 1 level deep, to avoid scanning huge folder
     trees). The depth can be changed in `settings.json` via
     `browse_subfolder_depth` (0 = the folder itself only, 1 = folder +
     immediate subfolders [default], 2 = also their subfolders, etc.).
2. **Tag** — a list of all known tags, alphabetically; you can select
   **one or several** (Ctrl/Shift+click, or none). The "Clear tag" button
   clears the choice. Below the list there is a **"Union (OR)" /
   "Intersection (AND)"** toggle deciding how the selected tags are
   combined.
3. **File type** — "Photos and videos" (default), "Photos only" or "Videos
   only". Below there is a **"Filter timestamp tags"** checkbox: when
   checked, at least one tag must be selected, and while a video plays only
   the timestamp tags of the selected tags are shown on screen, while `E`/`Q`
   navigation (previous/next mark) jumps only between them. Dialogs (e.g.
   "File tags", `T`) still show all tags, without filtering. The filter
   stays active until the Open/Browse dialog is confirmed again (or another
   folder is opened).

You must choose a **folder OR a tag** (both are allowed) — if both fields
are empty, the "Open" button shows an error. Combining rules:

- **Folder only** (no tag) — shows all files from that folder (of the
  relevant type).
- **Tag only** (no folder) — shows files matching the selected tags across
  the whole database, **regardless of the folder** they reside in (of the
  relevant type). With several tags: **Union (OR)** mode shows files with
  **any** of the selected tags, while **Intersection (AND)** mode only files
  that have **all** selected tags (with one tag both modes give the same
  result).
- **Folder + tag** — shows only files that are simultaneously in that
  folder **and** match the selected tag combination (intersection with the
  folder).

A live "Found: N files" counter reflects the current selection. After
confirming (`Enter` or the "Open" button) the application switches to the
resulting file list — the usual `→`/`←`/`PgUp`/`PgDown` navigation,
selection, filtering, etc. work on it exactly as with ordinary folder
browsing (even if the result spans files from many different folders,
because it comes from tag filtering). File selection is reset on each such
switch.

### Tag library

Tags and file references are stored in a local SQLite database
(`mediasort/tags.db`, created automatically). A tag is a short string (up
to 24 characters, longer ones are truncated; spaces inside are allowed).
The same tag cannot be assigned twice to the same file, nor twice to the
same second of a video — such an attempt is silently ignored (without an
error message).

**Tags and the file lifecycle:**
- When a tagged file is **moved** (copy/move dialog, Move action), all of
  its tag-database entries **follow it** to the new location automatically —
  no need to re-tag anything. If the destination file happened to already
  have the same tag, the duplicate is silently skipped (without an error).
- If while browsing by tag (`Alt+T`) the system comes across a file that
  **no longer exists** on disk (e.g. it was deleted outside the
  application), it automatically removes all of its entries from the tag
  database and **silently moves to the next file** — without an error
  dialog.

- **`Ctrl+T` — assign tag** — opens a dialog with the list of **most
  recently assigned tags** (newest on top); tags already assigned to the
  current file are marked with `✓`. You can choose a tag from the list or
  type a new one. Typing in the field also autocompletes: after two
  characters a small popup lists existing tags starting with those
  letters (case-insensitive) — the first `↓` fills the field with the
  first suggestion, further `↓`/`↑` walk through the rest. The dialog
  keeps the full feature set of the file
  operation dialog — the "Selected/Current file" context, "Invert
  selection"/"Select all" and the "Selected"/"Remaining" previews. The
  third preview panel, "Tag", shows the first and last file carrying the
  currently typed/selected tag plus the total number of its occurrences.
  `Enter` (or the button) assigns the tag to the selected files or to the
  current file (depending on the context) — files already tagged with it are
  skipped without an error.
- **`T` — tag management for the current file** — opens a window with a tag
  text field, the list of recently used tags on the left (up/down arrows
  select, filling the text field) and the list of the current file's tags on
  the right (tags at video seconds shown as `{TAG}@{MM:SS}`). The text field
  has the same tag autocomplete as the assign dialog (suggestions after two
  typed characters, walked with `↓`/`↑`). The video is
  automatically paused when this window opens and resumed when it closes.
  - `Enter` / the "Tag file" button — assigns the tag to the whole file.
  - `Shift+Enter` / the "Timestamp tag" button (visible only for videos) —
    assigns the tag to the current playback second.
  - Each tag on the current file's tag list has a "Remove" link next to it —
    clicking it removes exactly that tag (if the tag is assigned to several
    different seconds of the same video, only the chosen instance is
    removed, leaving the others untouched).
- While a video plays, all tags assigned to a specific time are visible in
  the top-right corner, below the time information. Clicking a `{TAG}@{MM:SS}`
  tag moves playback to the assigned second.
  - `Esc` / the "Close" button — closes the window.
- **`Alt+T` — browse by tag** — opens a dialog with the list of **recently
  browsed tags** (separate from the Open/Browse dialog — this one shows each
  OCCURRENCE of the tag separately, including timestamp marks in videos):
  you choose a tag (from the list or by typing), see its preview (first and
  last file + number of occurrences), and after confirming the application
  shows the first file with that tag. From then on `→`/`←` move between
  successive **occurrences** of the tag — a file tagged at the whole-file
  level, or a specific video second (this even works while watching a video,
  where `→`/`←` normally seek by 15 s). If the same tag is assigned both to
  a whole video and to second 5:11 of that same file, browsing that tag
  first shows the file from the beginning, and the next "Next" jumps to 5:11
  in the same file (without reloading the file — just a seek). The file
  label then shows the format `{file name} (x/y -tag:{tag name})`.
  - Navigation is **aware of the current frame**, not just a counter: if the
    user also seeks/plays the video so that the current position lands
    *between* two timestamp marks of the same tag (e.g. watching a file with
    tags at 1:01 and 3:00 while the player is at 2:00), `Next`/`Previous`
    correctly choose the nearest next/previous mark relative to the actual
    position, rather than rigidly following the list order.

## Configuring keyboard shortcuts

Every action can have **one or more** triggers (key and/or mouse button) —
just provide a list in `settings.json`. The old format (a single string
instead of a list) still works, for convenience and backward compatibility.

Keys are written in the Qt format, e.g. `"Right"`, `"Escape"`, `"Space"`,
`"C"`, `"Alt+C"`, `"Ctrl+D"`. Mouse buttons are written as `"MouseLeft"`,
`"MouseRight"`, `"MouseMiddle"`, `"MouseBack"`, `"MouseForward"`
(optionally with a modifier, e.g. `"Ctrl+MouseLeft"`). Assigning a mouse
button works for all configurable actions in the sections below. The video
progress bar keeps left-button handling so that clicking it always seeks the
material.

### Three sections, one priority rule

- **`navigation_keys`** — general shortcuts active whenever browsing
  (regardless of whether a photo or a video is displayed).
- **`video_keys`** — shortcuts active **only** while watching a video.
- **`file_dialog`** — shortcuts active **only** when the copy/move dialog
  **or** the Open/Browse dialog is open (both share the same list-mode keys:
  `R`/`H`/`F`, `F2`, `Esc`).

**Priority rule**: if the same physical button is set in both
`navigation_keys` and a context section (`video_keys`), the contextual
action wins **while that context is active**. In the default configuration
`→`/`←` are assigned to both `navigation_keys.next`/`prev` and
`video_keys.seek_forward`/`seek_backward` — so while viewing a photo `→`
goes to the next file, and while viewing a video `→` seeks by 15 s. The
`PgDown`/`PgUp` keys are set **only** in `navigation_keys`, so they always
act as "next/previous file", **regardless of whether a photo or a video is
currently displayed** — this guarantees you can always move from a video to
a photo and back, even when the arrows are busy seeking.

```json
{
  "navigation_keys": {
    "quit": ["Escape"],
    "next": ["Right", "PgDown"],
    "prev": ["Left", "PgUp"],
    "show_copy_dialog": ["C"],
    "show_move_dialog": ["M"],
    "show_browse_dialog": ["O"],
    "toggle_select": ["/"],
    "toggle_filter": ["F"],
    "show_tag_selected_dialog": ["Ctrl+T"],
    "show_manage_tags_dialog": ["T"],
    "show_browse_tag_dialog": ["Alt+T"]
  },
  "video_keys": {
    "seek_forward": ["Right"],
    "seek_backward": ["Left"],
    "seek_seconds": 15,
    "toggle_pause": ["Space", "MouseLeft"],
    "next_timestamp_tag": ["E"],
    "prev_timestamp_tag": ["Q"],
    "set_cut_start": ["["],
    "set_cut_end": ["]"],
    "show_cut_dialog": ["X"]
  },
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
  }
}
```

Note: the "browse by tag" mode (`Alt+T`) has even higher priority than the
video context — while it is active, `→`/`←` always move between tag
occurrences, even while watching a video (see the Tag library section
above).

Example: to make quitting work under both `Esc` and `Q`, just set
`"quit": ["Escape", "Q"]`.

You can also change the list of extensions treated as photos/videos
(`image_extensions`, `video_extensions`), the history limit
(`history_max_size`) and the subfolder search depth in the Open/Browse
dialog (`browse_subfolder_depth`, default 1). How much a small photo may
be enlarged to fill the screen is controlled by `image_max_zoom` (default
`4.0` = 400%, see the Photos section above).

Video cutting settings: `ffmpeg_path` / `ffprobe_path` (explicit paths to
the binaries; `null` = search in PATH and in `tools/`), `cut_default_mode`
(`"fast"` or `"exact"` — the mode preselected in the dialog) and
`cut_clean_file` (whether the "clean file" option is enabled by default).

## UI language

The UI language is set with the `language` key in `settings.json` and can
be changed to any language that has a file in `mediasort/translations/`
(e.g. `"language": "en"` for English or `"language": "pl"` for Polish).
English is the default.

## Project structure

```
MediaSort/
├── main.py                     # application entry point
├── requirements.txt
├── README.md
└── mediasort/
    ├── config.py                # settings, history, favourites
    ├── key_utils.py              # keyboard shortcut matching
    ├── file_scanner.py            # scanning folders for media
    ├── image_viewer.py            # photo display widget
    ├── video_viewer.py            # video widget + progress bar
    ├── video_cutter.py            # cutting a video fragment (ffmpeg -c copy, 3 modes)
    ├── cut_dialog.py              # "Cut fragment" dialog (X key)
    ├── thumbnails.py               # thumbnail generation (previews)
    ├── selection_preview.py        # selection summary widget
    ├── file_operation_dialog.py   # copy/move dialog + selection
    ├── tags_db.py                  # local tag database (SQLite)
    ├── tag_assign_dialog.py        # tag assignment dialog (Ctrl+T)
    ├── tag_suggestions.py          # tag autocomplete popup for the tagging dialogs
    ├── tag_management_dialog.py    # tag management for the current file (T)
    ├── tag_browse_dialog.py        # browsing files by tag (Alt+T)
    ├── i18n.py                     # UI translations (tr / tr_plural)
    ├── translations/               # translation files (en.json, pl.json)
    ├── main_window.py             # main application window
    ├── settings.json              # settings file (auto-created)
    └── tags.db                     # tag database (auto-created)
```
