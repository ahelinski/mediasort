"""Inline tag suggestions for the tagging dialogs.

While the user types in a tag edit field, after the second character a
small popup appears listing existing tags whose name starts with what was
typed (case-insensitive). The suggestions can be walked with the Up/Down
arrow keys: the FIRST Down press fills the field with the first suggested
tag, further presses move through the rest (wrapping around at the ends).
Enter confirms whatever the field currently holds (the dialog's own
action runs unchanged); Escape hides the popup first (a second Escape
falls through to the dialog); clicking a suggestion fills the field too.

The popup is driven by ``textEdited`` only - i.e. real typing - so
programmatic fills (choosing from the "recently used" lists, clearing the
field after an assignment, etc.) never trigger suggestions.
"""
from PySide6.QtCore import Qt, QEvent, QPoint, QObject
from PySide6.QtWidgets import QListWidget, QListWidgetItem


class TagSuggestionBox(QObject):
    """Attach a tag-suggestion popup to one ``line_edit``.

    ``tag_names`` is a zero-argument callable returning the current list
    of existing tag names (typically ``tags_db.all_tags``). It is queried
    on every typed edit, so newly created tags appear immediately.

    The popup is a child of ``parent`` (the dialog) and is shown directly
    below the line edit, reusing the dialog's dark list styling.
    """

    MIN_CHARS = 2          # suggestions start after the 2nd character
    MAX_VISIBLE = 8        # popup rows before a scrollbar appears
    MIN_WIDTH = 220        # popup never narrower than this

    def __init__(self, parent, line_edit, tag_names):
        super().__init__(parent)
        self._parent = parent
        self._edit = line_edit
        self._tag_names = tag_names
        self._items = []       # currently suggested tag names
        self._index = -1       # walked position inside _items (-1 = none)
        self._applying = False  # True while a suggestion fills the field

        self._popup = QListWidget(parent)
        self._popup.setFocusPolicy(Qt.NoFocus)  # keep typing in the edit
        self._popup.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._popup.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._popup.itemClicked.connect(self._on_item_clicked)
        self._popup.hide()

        line_edit.textEdited.connect(self._on_text_edited)
        line_edit.installEventFilter(self)

    # ------------------------------------------------------------------
    # Popup content / geometry
    # ------------------------------------------------------------------
    def _on_text_edited(self, text):
        prefix = text.strip()
        if len(prefix) < self.MIN_CHARS:
            self.hide()
            return
        lower = prefix.lower()
        names = [name for name in self._tag_names()
                 if name.lower().startswith(lower)]
        if not names:
            self.hide()
            return
        self._items = names
        self._index = -1  # nothing chosen until the first Down press
        self._populate()
        self._reposition()
        self._popup.show()
        self._popup.raise_()

    def _populate(self):
        self._popup.blockSignals(True)
        self._popup.clear()
        for name in self._items:
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, name)
            self._popup.addItem(item)
        self._popup.setCurrentRow(-1)
        self._popup.blockSignals(False)

    def _reposition(self):
        edit = self._edit
        width = max(edit.width(), self.MIN_WIDTH)
        pos = edit.mapTo(self._parent, QPoint(0, edit.height() + 2))
        x = max(0, min(pos.x(), self._parent.width() - width))
        self._popup.setGeometry(x, pos.y(), width, self._popup_height())
        self._popup.raise_()

    def _popup_height(self):
        row_h = self._popup.sizeHintForRow(0)
        if row_h <= 0:
            row_h = 26
        rows = min(len(self._items), self.MAX_VISIBLE)
        return int(rows * row_h + 2 * self._popup.frameWidth() + 4)

    # ------------------------------------------------------------------
    # Walking / choosing a suggestion
    # ------------------------------------------------------------------
    def _step(self, delta):
        """Fill the field with the next/previous suggestion. The first
        Down press picks the first suggestion (index -1 -> 0), Up goes to
        the last; afterwards the walk wraps around."""
        if not self._items:
            return
        n = len(self._items)
        if self._index < 0:
            self._index = 0 if delta > 0 else n - 1
        else:
            self._index = (self._index + delta) % n
        self._apply(self._items[self._index])

    def _apply(self, name):
        self._applying = True
        self._edit.setText(name)
        self._edit.setCursorPosition(len(name))
        self._applying = False
        row = self._items.index(name)
        item = self._popup.item(row)
        self._popup.setCurrentRow(row)
        self._popup.scrollToItem(item)

    def _on_item_clicked(self, item):
        name = item.data(Qt.UserRole)
        if name in self._items:
            self._index = self._items.index(name)
        self._apply(name)
        self.hide()

    def hide(self):
        """Hide the popup and forget any walked position."""
        self._index = -1
        self._popup.hide()

    # ------------------------------------------------------------------
    # Keyboard handling on the line edit
    # ------------------------------------------------------------------
    def eventFilter(self, obj, event):
        if obj is self._edit:
            if event.type() == QEvent.KeyPress:
                key = event.key()
                if self._popup.isVisible():
                    if key in (Qt.Key_Down, Qt.Key_Up):
                        self._step(1 if key == Qt.Key_Down else -1)
                        return True
                    if key == Qt.Key_Escape:
                        self.hide()
                        return True
                    if key in (Qt.Key_Return, Qt.Key_Enter):
                        self.hide()  # let the dialog run its own action
                        return False
            elif event.type() == QEvent.FocusOut:
                self.hide()
        return False
