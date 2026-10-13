"""The Delete-key confirmation dialog: move the current file - or a whole
selection - to the system trash.

Three outcomes are possible when something is selected (plus cancelling):

* **selected files** - everything marked with the selection key (``/``),
* **unselected files** - the complement inside the list being browsed
  (i.e. "keep what I marked, throw away the rest"),
* **current file** - only the file on screen.

With an empty selection there is nothing to choose between, so the dialog
asks a plain yes/no question about the current file.  The primary answer is
the default one - "Yes" without a selection, "Selected files" with one - so
Return immediately accepts what the dialog is about; Escape still cancels
and every other answer is one click away.
"""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
)

from .i18n import tr, tr_plural
from . import styles

# Values stored in TrashConfirmDialog.choice.
TRASH_SELECTED = "selected"
TRASH_UNSELECTED = "unselected"
TRASH_CURRENT = "current"


class TrashConfirmDialog(QDialog):
    def __init__(self, current_file, selected_count, unselected_count, parent=None):
        super().__init__(parent)
        self.choice = None          # None = cancelled
        self.setWindowTitle(tr("trash_dialog.title"))
        self.setStyleSheet(styles.DIALOG)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)

        if selected_count:
            message = tr_plural("trash_dialog.confirm_selected", selected_count)
        else:
            message = tr("trash_dialog.confirm_current")
        message_label = QLabel(message, self)
        message_label.setWordWrap(True)
        layout.addWidget(message_label)

        hints = [tr("trash_dialog.current_file", name=Path(current_file).name)]
        if selected_count:
            hints.append(tr_plural("trash_dialog.unselected_hint", unselected_count))
        hint_label = QLabel("\n".join(hints), self)
        hint_label.setStyleSheet(styles.HINT)
        hint_label.setWordWrap(True)
        layout.addWidget(hint_label)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        if selected_count:
            primary_btn = self._add_button(
                buttons, tr("trash_dialog.selected_btn"), TRASH_SELECTED,
                tr_plural("trash_dialog.selected_tooltip", selected_count),
            )
            self._add_button(
                buttons, tr("trash_dialog.unselected_btn"), TRASH_UNSELECTED,
                tr_plural("trash_dialog.unselected_tooltip", unselected_count),
            )
            self._add_button(
                buttons, tr("trash_dialog.current_btn"), TRASH_CURRENT,
                tr("trash_dialog.current_tooltip"),
            )
            cancel_text = tr("trash_dialog.cancel_btn")
        else:
            primary_btn = self._add_button(
                buttons, tr("trash_dialog.yes_btn"), TRASH_CURRENT,
                tr("trash_dialog.current_tooltip"),
            )
            cancel_text = tr("trash_dialog.no_btn")
        cancel_btn = QPushButton(cancel_text, self)
        cancel_btn.setAutoDefault(False)
        cancel_btn.setDefault(False)
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(cancel_btn)
        layout.addLayout(buttons)

        # The main answer is the default one: Return accepts "Yes" / "Selected
        # files" straight away (Escape still cancels).
        primary_btn.setDefault(True)
        primary_btn.setAutoDefault(True)
        primary_btn.setFocus()

    def _add_button(self, layout, text, choice, tooltip):
        button = QPushButton(text, self)
        button.setAutoDefault(False)
        button.setDefault(False)
        button.setToolTip(tooltip)
        button.clicked.connect(lambda _checked=False, c=choice: self._choose(c))
        layout.addWidget(button)
        return button

    def _choose(self, choice):
        self.choice = choice
        self.accept()
