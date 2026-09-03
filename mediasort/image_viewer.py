"""Full screen image viewer widget with a black background."""
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout
from PySide6.QtGui import QPixmap, QImageReader
from PySide6.QtCore import Qt

from . import styles
from .i18n import tr

# Fallback when the "image_max_zoom" setting is missing/invalid: photos
# may be enlarged at most 400% of their native size.
DEFAULT_MAX_ZOOM = 4.0


class ImageViewer(QWidget):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setStyleSheet(styles.BG)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.label = QLabel(self)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setStyleSheet(styles.BG)
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

    def _max_zoom(self):
        """Return the "image_max_zoom" setting as a float (1.0 = native
        size). A "maximum zoom" below 1.0 makes no sense (it could only
        shrink photos that fit the screen), so such values - and any
        non-numeric junk in settings.json - are treated as 1.0."""
        try:
            zoom = float(self.settings.get("image_max_zoom", default=DEFAULT_MAX_ZOOM))
        except (TypeError, ValueError):
            zoom = DEFAULT_MAX_ZOOM
        return zoom if zoom >= 1.0 else 1.0

    def _rescale(self):
        pixmap = self._pixmap
        if pixmap is None or pixmap.isNull():
            self.label.setPixmap(QPixmap())
            self.label.setText(tr("image_viewer.load_error"))
            self.label.setStyleSheet(styles.MESSAGE_TEXT)
            return

        width = pixmap.width()
        height = pixmap.height()
        if width <= 0 or height <= 0 or self.width() <= 0 or self.height() <= 0:
            return

        # The photo is normally scaled (keeping the aspect ratio) to fill
        # the whole window. Small photos would then be blown up far beyond
        # their native resolution, which looks blurry - so enlargement is
        # capped at the "image_max_zoom" setting (default 400%): e.g. a
        # 500 px wide photo on a 3840 px screen is shown at most 2000 px
        # wide, centered on the black background. Photos larger than the
        # window are still shrunk to fit it, as before.
        fit_scale = min(self.width() / width, self.height() / height)
        scale = min(fit_scale, self._max_zoom())
        scaled = pixmap.scaled(
            max(1, round(width * scale)),
            max(1, round(height * scale)),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.label.setStyleSheet(styles.BG)
        self.label.setPixmap(scaled)
