"""Central stylesheet definitions for MediaSort.

Every UI style lives in this module so widgets only ever reference named
constants (e.g. ``styles.DIALOG``, ``styles.INFO_LABEL``) instead of
inline stylesheet strings. Constants are named without a ``_STYLE`` suffix;
usage pattern:

    from . import styles
    widget.setStyleSheet(styles.INFO_LABEL)
"""

# Base dark theme applied to every dialog (and to labels inside them, so
# they stay readable regardless of the system palette).
DIALOG = (
        "QDialog { background-color: #2b2b2b; color: #fefefe; } "
        "QLabel { color: #fefefe; } "
        "QGroupBox { color: #fefefe; font-weight: bold; } "
        "QRadioButton { color: #fefefe; }"
        "padding: 4px 6px; border: 1px solid #555; background-color: #222; "
        "color: white; border-radius: 3px;"
        "QPushButton { color: #fefefe; text-decoration: underline; "
        "border: none; background: transparent; padding: 0; }"
        "QPushButton:hover { color: #ffb3b3; }"
)

# Neutral (non-destructive) link-style button, e.g. "Show".
LINK = (
        "QPushButton { color: #fefefe; text-decoration: underline; "
        "border: none; background: transparent; padding: 0; }"
        "QPushButton:hover { color: #ffb3b3; }"
)

# Destructive link-style button, e.g. "Usuń".
DEL_LINK = (
        "QPushButton { color: #ff8080; text-decoration: underline; "
        "border: none; background: transparent; padding: 0; }"
        "QPushButton:hover { color: #ffb3b3; }"
)

# Muted italic text used for small descriptive labels.
INFO = (
        "color: gray; font-style: italic; "
)

# Small gray hint text shown at the bottom of dialogs.
HINT = ("color: gray; font-size: 11px;")

# Overlay label in the top corners of the main window (file info, time).
INFO_LABEL = (
        "color: #fefefe; background-color: rgba(0, 0, 0, 140); "
        "font-size: 12px; padding: 2px 8px; border-radius: 3px;"
)

# Big bold count shown between the first/last thumbnails in the
# selection preview row.
SELECTION_PREVIEW = (
        "font-size: 22px; font-weight: bold; color: #fefefe; padding: 0 12px;"
)

# Thumbnail tile background/border.
THUMB = (
        "background-color: #1a1a1a; border: 1px solid #444;"
)

# Timestamp-tag seek link overlaid on the video (inactive).
TS_LINK = (
        "QPushButton { color: white; background-color: rgba(0, 0, 0, 140); "
        f"font-size: 12px; padding: 2px 8px; border: none; border-radius: 3px; }}"
        "QPushButton:hover { background-color: rgba(60, 60, 60, 180); }"
)
# Timestamp-tag seek link overlaid on the video (active interval).
ACTIVE_TS_LINK = (
        "QPushButton { color: white; background-color: rgba(0, 0, 0, 140); "
        f"font-size: 12px; font-weight: bold; padding: 2px 8px; border: none; border-radius: 3px; }}"
        "QPushButton:hover { background-color: rgba(60, 60, 60, 180); }"
)

# "[x]" selected-file indicator shown in the top-right corner.
SELECTION = (
        "color: #33ff66; background-color: rgba(0, 0, 0, 160); "
        "font-size: 20px; font-weight: bold; padding: 4px 10px; border-radius: 4px;"
)

# Plain black background used by the main window and the media viewers.
BLACK_BG = "background-color: black;"

# Full-screen message text (e.g. "no media files in folder", image errors).
MESSAGE_TEXT = "color: white; background-color: black; font-size: 18px;"

# Video viewer canvas: black, without any frame/border.
VIDEO_VIEW = "background-color: black; border: none;"

# Bold label, e.g. the browse dialog's match count.
BOLD_LABEL = "font-weight: bold;"

# Fully transparent background (timestamp-tag overlay container).
TRANSPARENT = "background: transparent;"
