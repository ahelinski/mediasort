"""A small summary widget showing a preview of a group of files.

Per spec: shows a small preview of the first and last file with the count
in between, unless there are 3 or fewer files, in which case it shows a
preview of every one of them instead.
"""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel
from PySide6.QtCore import Qt

from .thumbnails import get_thumbnail

THUMB_SIZE = 48


class SelectionPreviewWidget(QWidget):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self.title_label = QLabel(title, self)
        self.title_label.setStyleSheet("font-weight: bold; color: #eeeeee;")
        layout.addWidget(self.title_label)

        self.row = QHBoxLayout()
        self.row.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.row.setSpacing(6)
        layout.addLayout(self.row)

    def set_items(self, items):
        """items: list of (path, kind) tuples."""
        self._clear_row()
        n = len(items)

        if n == 0:
            empty = QLabel("Brak plikow", self)
            empty.setStyleSheet("color: gray; font-style: italic;")
            self.row.addWidget(empty)
            return

        if n <= 3:
            for path, kind in items:
                self.row.addWidget(self._make_thumb(path, kind))
        else:
            first_path, first_kind = items[0]
            last_path, last_kind = items[-1]
            self.row.addWidget(self._make_thumb(first_path, first_kind))

            count_label = QLabel(str(n), self)
            count_label.setAlignment(Qt.AlignCenter)
            count_label.setStyleSheet(
                "font-size: 22px; font-weight: bold; color: white; padding: 0 12px;"
            )
            self.row.addWidget(count_label)

            self.row.addWidget(self._make_thumb(last_path, last_kind))

    def _make_thumb(self, path, kind):
        label = QLabel(self)
        label.setFixedSize(THUMB_SIZE, THUMB_SIZE)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("background-color: #1a1a1a; border: 1px solid #444;")
        label.setPixmap(get_thumbnail(path, kind, THUMB_SIZE))
        label.setToolTip(path)
        return label

    def _clear_row(self):
        while self.row.count():
            item = self.row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # takeAt() only removes the widget from the LAYOUT; the
                # widget itself stays visible at its old position until
                # deleteLater() actually runs on the next event loop pass.
                # If set_items() is called again before that happens (as it
                # is during dialog construction), the old widget would still
                # be on screen, overlapping the newly added one - hide it
                # immediately so there's never a visible duplicate.
                widget.hide()
                widget.deleteLater()
