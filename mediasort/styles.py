"""Central stylesheet definitions for MediaSort.

Every UI style lives in this module so widgets only ever reference named
constants (e.g. ``styles.DIALOG``, ``styles.INFO_LABEL``) instead of
inline stylesheet strings. Constants are named without a ``_STYLE`` suffix;
usage pattern:

    from . import styles
    widget.setStyleSheet(styles.INFO_LABEL)

Palette: a dark-blue theme. All backgrounds share one base color
(COLOR_BG) with no variations; panels, lists and inputs are separated by a
brighter matching border (COLOR_BORDER). Colors and font sizes are defined
once as variables and reused by every style instead of being hardcoded per
style. RGB-component variables (``*_RGB``) exist for painting code
(QColor, scene brushes, progress bar).
"""

# ---------------------------------------------------------------------------
# Palette: colors
# ---------------------------------------------------------------------------
# Base dark-blue background - used for every background, no variations.
COLOR_BG = "#010b13"
# Translucent variant of COLOR_BG for overlays drawn on top of media
# (file info, time label, timestamp chips, selection indicator).
COLOR_BG_TRANSLUCENT = "rgba(4, 28, 50, 200)"
# RGB components of COLOR_BG, for painting code.
COLOR_BG_RGB = (1, 11, 19)

# Brighter matching blue used for panel/list/input borders.
COLOR_BORDER = "#1868ad"
# RGB components of COLOR_BORDER, for painting code.
COLOR_BORDER_RGB = (24, 104, 173)
# Slightly lighter blue for focused/hovered borders.
COLOR_BORDER_ACTIVE = "#2f8fd8"
# Translucent accent for hover states drawn on top of media.
COLOR_ACCENT_TRANSLUCENT = "rgba(24, 104, 173, 180)"

# Main text color.
COLOR_TEXT = "#fefefe"
# RGB components of COLOR_TEXT, for painting code.
COLOR_TEXT_RGB = (254, 254, 254)
# Muted text (hints, secondary/info labels).
COLOR_TEXT_MUTED = "#9db4c8"
# Hover tint for links and flat buttons.
COLOR_HOVER = "#8ec8ff"
# Destructive action color (delete links).
COLOR_DANGER = "#ff8080"
# Selected-file indicator accent.
COLOR_SELECTION = "#33ff66"

# Video progress bar (functional accents, kept as-is for readability).
COLOR_PROGRESS_TRACK = (10, 44, 80)    # unfilled track, slightly lighter than bg
COLOR_PROGRESS_FILL = (220, 30, 30)    # played portion, red

# ---------------------------------------------------------------------------
# Palette: font sizes (px)
# ---------------------------------------------------------------------------
FONT_SIZE_HINT = 11        # small gray hint lines at the bottom of dialogs
FONT_SIZE_SMALL = 12       # overlay labels, timestamp chips
FONT_SIZE_MESSAGE = 18     # full-screen messages (no media, load errors)
FONT_SIZE_INDICATOR = 20   # "[x]" selection indicator
FONT_SIZE_COUNT = 22       # big count in the selection preview row

# ---------------------------------------------------------------------------
# Base theme for every dialog
# ---------------------------------------------------------------------------
DIALOG = " ".join([
    f"QDialog {{ background-color: {COLOR_BG}; color: {COLOR_TEXT}; }}",
    f"QLabel, QCheckBox, QRadioButton {{ color: {COLOR_TEXT}; }}",
    f"QGroupBox {{ color: {COLOR_TEXT}; font-weight: bold; "
    f"border: 1px solid {COLOR_BORDER}; border-radius: 4px; margin-top: 8px; }}",
    "QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }",
    f"QLineEdit {{ background-color: {COLOR_BG}; color: {COLOR_TEXT}; "
    f"border: 1px solid {COLOR_BORDER}; border-radius: 3px; padding: 2px 4px; "
    f"selection-background-color: {COLOR_BORDER}; selection-color: {COLOR_TEXT}; }}",
    f"QListWidget {{ background-color: {COLOR_BG}; color: {COLOR_TEXT}; "
    f"border: 1px solid {COLOR_BORDER}; border-radius: 3px; }}",
    f"QLineEdit:focus, QListWidget:focus {{ border-color: {COLOR_BORDER_ACTIVE}; }}",
    f"QListWidget::item:selected {{ background-color: {COLOR_BORDER}; }}",
    f"QPushButton {{ color: {COLOR_TEXT}; text-decoration: underline; "
    "border: none; background: transparent; padding: 0; }",
    f"QPushButton:hover {{ color: {COLOR_HOVER}; }}",
])


def _link_style(color, hover):
    """Flat underlined link-style button with a single hover tint."""
    return " ".join([
        f"QPushButton {{ color: {color}; text-decoration: underline; "
        "border: none; background: transparent; padding: 0; }",
        f"QPushButton:hover {{ color: {hover}; }}",
    ])


# Neutral (non-destructive) link-style button, e.g. "Pokaż".
LINK = _link_style(COLOR_TEXT, COLOR_HOVER)

# Destructive link-style button, e.g. "Usuń".
DEL_LINK = _link_style(COLOR_DANGER, COLOR_HOVER)

# Muted italic text used for small descriptive labels.
INFO = f"color: {COLOR_TEXT_MUTED}; font-style: italic;"

# Small muted hint text shown at the bottom of dialogs.
HINT = f"color: {COLOR_TEXT_MUTED}; font-size: {FONT_SIZE_HINT}px;"

# Overlay label in the top corners of the main window (file info, time).
INFO_LABEL = (
    f"color: {COLOR_TEXT}; background-color: {COLOR_BG_TRANSLUCENT}; "
    f"font-size: {FONT_SIZE_SMALL}px; padding: 2px 8px; border-radius: 3px;"
)

# Big bold count shown between the first/last thumbnails in the
# selection preview row.
SELECTION_PREVIEW = (
    f"color: {COLOR_TEXT}; font-size: {FONT_SIZE_COUNT}px; "
    "font-weight: bold; padding: 0 12px;"
)

# Thumbnail tile: same background as everything else, separated by the
# standard brighter border.
THUMB = f"background-color: {COLOR_BG}; border: 1px solid {COLOR_BORDER};"


def _ts_link_style(bold=False):
    """Timestamp-tag seek chip overlaid on the video; ``bold`` marks the
    interval containing the playback position."""
    weight = "font-weight: bold; " if bold else ""
    return " ".join([
        f"QPushButton {{ color: {COLOR_TEXT}; background-color: {COLOR_BG_TRANSLUCENT}; "
        f"font-size: {FONT_SIZE_SMALL}px; {weight}padding: 2px 8px; "
        f"border: 1px solid {COLOR_BORDER}; border-radius: 3px; }}",
        f"QPushButton:hover {{ background-color: {COLOR_ACCENT_TRANSLUCENT}; }}",
    ])


# Timestamp-tag seek chip (inactive).
TS_LINK = _ts_link_style()
# Timestamp-tag seek chip (active interval).
ACTIVE_TS_LINK = _ts_link_style(bold=True)

# "[x]" selected-file indicator shown in the top-right corner.
SELECTION = (
    f"color: {COLOR_SELECTION}; background-color: {COLOR_BG_TRANSLUCENT}; "
    f"font-size: {FONT_SIZE_INDICATOR}px; font-weight: bold; "
    "padding: 4px 10px; border-radius: 4px;"
)

# Plain base background used by the main window and the media viewers.
BG = f"background-color: {COLOR_BG};"

# Full-screen message text (e.g. "no media files in folder", image errors).
MESSAGE_TEXT = (
    f"color: {COLOR_TEXT}; background-color: {COLOR_BG}; "
    f"font-size: {FONT_SIZE_MESSAGE}px;"
)

# Bold label, e.g. the browse dialog's match count.
BOLD_LABEL = f"font-weight: bold; color: {COLOR_TEXT};"

# Fully transparent background (timestamp-tag overlay container).
TRANSPARENT = "background: transparent;"
