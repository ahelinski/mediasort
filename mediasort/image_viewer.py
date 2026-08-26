"""Full screen image viewer widget with a black background."""
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout
from PySide6.QtGui import QPixmap, QImageReader
from PySide6.QtCore import Qt

from .i18n import tr


class ImageViewer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background-color: black;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.label = QLabel(self)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setStyleSheet("background-color: black;")
        layout.addWidget(self.label)

        self._pixmap = None

    def load(self, path):
        # QPixmap(path) ignores the EXIF "Orientation" tag, so photos taken
        # with the camera held sideways/upside-down come out rotated
        # incorrectly. QImageReader with autoTransform enabled applies that
        # tag automatically, matching how other viewers display the photo.
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        image = reader.read()
        self._pixmap = QPixmap.fromImage(image) if not image.isNull() else QPixmap()
        self._rescale()

    def clear(self):
        self._pixmap = None
        self.label.clear()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rescale()

    def _rescale(self):
        if self._pixmap is not None and not self._pixmap.isNull():
            scaled = self._pixmap.scaled(
                self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self.label.setStyleSheet("background-color: black;")
            self.label.setPixmap(scaled)
        else:
            self.label.setPixmap(QPixmap())
            self.label.setText(tr("image_viewer.load_error"))
            self.label.setStyleSheet("background-color: black; color: white; font-size: 18px;")

