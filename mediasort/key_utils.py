"""Helpers for matching QKeyEvent/QMouseEvent instances against configurable
button strings.

Each action in settings.json maps to a LIST of one or more trigger
strings, e.g.:

    "quit": ["Escape"]
    "toggle_pause": ["Space", "MouseLeft"]

A trigger string is either:
  * a keyboard shortcut in Qt's portable-text format, e.g. "Right",
    "Space", "Alt+C", "Ctrl+D";
  * a mouse button name: "MouseLeft", "MouseRight", "MouseMiddle",
    "MouseBack", "MouseForward" - optionally prefixed with keyboard
    modifiers, e.g. "Ctrl+MouseLeft".

For backward compatibility, a bare string (instead of a list containing
one string) is also accepted everywhere a trigger list is expected.
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QKeyEvent, QMouseEvent, QWheelEvent

_MODIFIER_KEYS = (
    Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta, Qt.Key_AltGr
)

_MOUSE_BUTTONS = {
    "mouseleft": Qt.LeftButton,
    "mouseright": Qt.RightButton,
    "mousemiddle": Qt.MiddleButton,
    "mouseback": Qt.BackButton,
    "mouseforward": Qt.ForwardButton,
}

_MODIFIER_NAMES = {
    "ctrl": Qt.ControlModifier,
    "control": Qt.ControlModifier,
    "alt": Qt.AltModifier,
    "shift": Qt.ShiftModifier,
    "meta": Qt.MetaModifier,
}

_WHEEL_TRIGGERS = {
    "mousewheelup",
    "mousewheeldown",
}




def event_to_string(event) -> str:
    """Convert a QKeyEvent (key + modifiers) into a canonical shortcut string."""
    key = event.key()
    if key in _MODIFIER_KEYS:
        return ""
    try:
        # Qt6 style: QKeyEvent.keyCombination() -> QKeyCombination
        seq = QKeySequence(event.keyCombination())
    except AttributeError:
        seq = QKeySequence(int(event.modifiers()) | key)
    return seq.toString(QKeySequence.PortableText)


def _is_mouse_trigger(trigger: str) -> bool:
    last = trigger.split("+")[-1].strip().lower()
    return last in _MOUSE_BUTTONS

def _is_mouse_wheel(trigger: str) -> bool:
    last = trigger.split("+")[-1].strip().lower()
    return last in _WHEEL_TRIGGERS

def _matches_mouse(event, trigger: str) -> bool:
    if not isinstance(event, QMouseEvent):
        return False
    parts = [p.strip() for p in trigger.split("+")]
    button = _MOUSE_BUTTONS.get(parts[-1].lower())
    if button is None or event.button() != button:
        return False
    required_mods = Qt.NoModifier
    for mod_name in parts[:-1]:
        required_mods |= _MODIFIER_NAMES.get(mod_name.lower(), Qt.NoModifier)
    return event.modifiers() == required_mods

def _matches_wheel(event, trigger: str) -> bool:
    if not isinstance(event, QWheelEvent):
        return False

    parts = [p.strip() for p in trigger.split("+")]
    direction = parts[-1].lower()
    if direction not in _WHEEL_TRIGGERS:
        return False

    required_mods = Qt.NoModifier
    for mod_name in parts[:-1]:
        required_mods |= _MODIFIER_NAMES.get(mod_name.lower(), Qt.NoModifier)

    delta = event.angleDelta().y()
    return (
        event.modifiers() == required_mods
        and ((direction == "mousewheelup" and delta > 0)
             or (direction == "mousewheeldown" and delta < 0))
    )


def _matches_key(event, trigger: str) -> bool:
    if not isinstance(event, QKeyEvent):
        return False
    ev_str = event_to_string(event)
    if not ev_str:
        return False
    # Normalize both sides through QKeySequence's canonical text form, so
    # spelling variants accepted by Qt (e.g. "Escape" vs "Esc") are treated
    # as equivalent instead of relying on a naive string comparison.
    normalized_config = QKeySequence(trigger).toString(QKeySequence.PortableText)
    if not normalized_config:
        return False
    return ev_str.strip().lower() == normalized_config.strip().lower()


def matches(event, trigger: str) -> bool:
    """Return True if `event` matches a single trigger string (keyboard or mouse)."""
    if not trigger:
        return False
    if _is_mouse_trigger(trigger):
        return _matches_mouse(event, trigger)
    if _is_mouse_wheel(trigger):
        return _matches_wheel(event, trigger)
    return _matches_key(event, trigger)


def matches_any(event, triggers) -> bool:
    """Return True if `event` matches any of the given trigger(s).

    `triggers` may be a single string or a list of strings, so both plain
    single-shortcut settings and multi-shortcut settings work the same way.
    """
    if not triggers:
        return False
    if isinstance(triggers, str):
        triggers = [triggers]
    return any(matches(event, t) for t in triggers)

def matching_trigger(event, triggers) -> str:
    """Return True if `event` matches any of the given trigger(s).

    `triggers` may be a single string or a list of strings, so both plain
    single-shortcut settings and multi-shortcut settings work the same way.
    """
    if not triggers:
        return False
    if isinstance(triggers, str):
        triggers = [triggers]
    for t in triggers:
        if matches(event, t):
            return t
    return None
