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
# Darker text for disabled/inactive fields - still readable on the dark
# background, but clearly distinguishable from active widgets.
COLOR_TEXT_DISABLED = "#4a5d72"
# Dimmer border for disabled input fields (line edits, lists, checkbox
# indicators), so inactive fields don't look like active ones.
COLOR_BORDER_DISABLED = "#0d3a63"
# Hover tint for links and flat buttons.
COLOR_HOVER = "#8ec8ff"
# Destructive action color (delete links).
COLOR_DANGER = "#ff8080"
# Selected-file indicator accent.
COLOR_SELECTION = "#33ff66"

# Video progress bar (functional accents, kept as-is for readability).
COLOR_PROGRESS_TRACK = (10, 44, 80)    # unfilled track, slightly lighter than bg
COLOR_PROGRESS_FILL = (220, 30, 30)    # played portion, red

# Cut-range markers drawn on the video progress bar: start (A) is green,
# end (B) is orange, the selected range gets a translucent highlight.
COLOR_CUT_RANGE_RGB = (24, 104, 173)
COLOR_CUT_START_RGB = (51, 255, 102)
COLOR_CUT_END_RGB = (255, 170, 40)

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
    # Checkbox indicators must be clearly visible on the dark background:
    # a bordered box that fills with the accent color when checked.
    f"QCheckBox::indicator {{ width: 14px; height: 14px; "
    f"border: 1px solid {COLOR_BORDER}; border-radius: 2px; "
    f"background-color: {COLOR_BG}; }}",
    f"QCheckBox::indicator:hover {{ border-color: {COLOR_BORDER_ACTIVE}; }}",
    f"QCheckBox::indicator:checked {{ background-color: {COLOR_BORDER}; "
    f"border-color: {COLOR_BORDER_ACTIVE}; }}",
    f"QCheckBox::indicator:checked:hover {{ background-color: {COLOR_BORDER_ACTIVE}; }}",
    # Disabled/inactive fields: clearly dimmed text (and borders for
    # inputs and group boxes), so they don't look almost identical to
    # active ones.
    f"QLabel:disabled, QCheckBox:disabled, QRadioButton:disabled, "
    f"QGroupBox:disabled, QPushButton:disabled {{ color: {COLOR_TEXT_DISABLED}; }}",
    f"QGroupBox:disabled {{ border-color: {COLOR_BORDER_DISABLED}; }}",
    f"QLineEdit:disabled, QListWidget:disabled {{ color: {COLOR_TEXT_DISABLED}; "
    f"border-color: {COLOR_BORDER_DISABLED}; }}",
    f"QCheckBox::indicator:disabled {{ border-color: {COLOR_BORDER_DISABLED}; }}",
    # A list inside a group box (e.g. the Browse dialog's folder list)
    # inherits the frame from the group box - drop its own border so it
    # doesn't render a double frame; focus restores a bright border.
    "QGroupBox QListWidget { border: none; background: transparent; }",
    f"QGroupBox QListWidget:focus {{ border: 1px solid {COLOR_BORDER_ACTIVE}; }}",
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

# Compact "×" remove icon for list rows (destructive, but without the
# underline that DEL_LINK gives to text links).
REMOVE_ICON = " ".join([
    f"QPushButton {{ color: {COLOR_DANGER}; border: none; background: transparent; "
    "padding: 0 6px; font-size: 15px; font-weight: bold; }",
    f"QPushButton:hover {{ color: {COLOR_HOVER}; }}",
])

# Compact, borderless icon-only button used in list rows (the magnifier and
# trash of the "Manage tags" window). The icon itself carries the colour,
# the stylesheet only provides the hover highlight.
ICON_BUTTON = " ".join([
    "QPushButton { background: transparent; border: none; padding: 2px; }",
    f"QPushButton:hover {{ background-color: {COLOR_BORDER}; border-radius: 3px; }}",
    "QPushButton:disabled { background: transparent; }",
])

# ---------------------------------------------------------------------------
# Real (non-link) push buttons for primary/secondary dialog actions.
# A widget-level stylesheet overrides the flat link look that styles.DIALOG
# gives to every QPushButton, so these read as actual buttons.
# ---------------------------------------------------------------------------

# Primary action (e.g. "Wytnij"): filled accent button.
PRIMARY_BUTTON = " ".join([
    f"QPushButton {{ background-color: {COLOR_BORDER}; color: {COLOR_TEXT}; "
    "border: 1px solid #2f8fd8; border-radius: 4px; padding: 6px 20px; "
    "font-weight: bold; min-height: 18px; }",
    f"QPushButton:hover {{ background-color: {COLOR_BORDER_ACTIVE}; }}",
    "QPushButton:pressed { background-color: #0f4a7d; }",
    f"QPushButton:focus {{ border: 1px solid {COLOR_HOVER}; }}",
    f"QPushButton:disabled {{ background-color: {COLOR_BG}; color: "
    f"{COLOR_TEXT_DISABLED}; border-color: {COLOR_BORDER_DISABLED}; }}",
])

# Secondary action (e.g. "Anuluj"): outline button.
SECONDARY_BUTTON = " ".join([
    f"QPushButton {{ background-color: {COLOR_BG}; color: {COLOR_TEXT}; "
    f"border: 1px solid {COLOR_BORDER}; border-radius: 4px; "
    "padding: 6px 20px; min-height: 18px; }",
    f"QPushButton:hover {{ border-color: {COLOR_BORDER_ACTIVE}; "
    "background-color: rgba(24, 104, 173, 70); }",
    f"QPushButton:focus {{ border: 1px solid {COLOR_HOVER}; }}",
    f"QPushButton:disabled {{ color: {COLOR_TEXT_DISABLED}; "
    f"border-color: {COLOR_BORDER_DISABLED}; background-color: {COLOR_BG}; }}",
])

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
    interval containing the playback position.  Plain dark background, no
    border - the translucent chip alone stands out on video."""
    weight = "font-weight: bold; " if bold else ""
    return " ".join([
        f"QPushButton {{ color: {COLOR_TEXT}; background-color: {COLOR_BG_TRANSLUCENT}; "
        f"font-size: {FONT_SIZE_SMALL}px; {weight}padding: 2px 8px; "
        f"border-radius: 3px; }}",
        f"QPushButton:hover {{ background-color: {COLOR_ACCENT_TRANSLUCENT}; }}",
    ])


# Timestamp-tag seek chip (inactive).
TS_LINK = _ts_link_style()
# Timestamp-tag seek chip (active interval).
ACTIVE_TS_LINK = _ts_link_style(bold=True)

# Small "+" marker shown above/below the timestamp-tag stack when tags
# exist that are hidden (don't fit in the visible window).
TS_MORE = (
    f"color: {COLOR_TEXT_MUTED}; background-color: {COLOR_BG_TRANSLUCENT}; "
    f"font-size: {FONT_SIZE_SMALL}px; font-weight: bold; "
    "padding: 0px 8px; border-radius: 3px;"
)

# Row label of a tag list in the tag windows. These are deliberately tiny
# stylesheets (not the whole DIALOG sheet): the active one is re-applied on
# every playback step, and a heavy sheet on a child widget forces Qt to
# re-polish the style tree each time.
FILE_TAG_ROW = f"color: {COLOR_TEXT};"

# Row label of the tag(s) currently shown at the playback position in the
# "Manage File Tags" window - mirrors the emphasized chip over the video.
FILE_TAG_ACTIVE = f"color: {COLOR_HOVER}; font-weight: bold;"

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

# Progress bar inside dialogs (e.g. the cut dialog while FFmpeg runs).
PROGRESS = " ".join([
    f"QProgressBar {{ background-color: {COLOR_BG}; border: 1px solid "
    f"{COLOR_BORDER}; border-radius: 3px; text-align: center; "
    f"color: {COLOR_TEXT}; }}",
    f"QProgressBar::chunk {{ background-color: {COLOR_BORDER}; "
    "border-radius: 2px; }",
])

# Fully transparent background (timestamp-tag overlay container).
TRANSPARENT = "background: transparent;"
