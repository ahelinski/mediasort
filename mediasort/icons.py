"""Tiny vector icons drawn at runtime.

The interface uses a few small pictograms (the "Manage tags" magnifier and
trash buttons).  They are painted with QPainter instead of relying on emoji
glyphs or external image files, so they always render and follow the
application's dark theme.  Each icon is drawn at 2x and exposed as a
device-independent 16 px icon, which keeps it crisp on HiDPI screens.
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

from . import styles

ICON_SIZE = 16     # logical (device-independent) icon size
_SCALE = 2         # rendered at this multiple for HiDPI
_PEN_WIDTH = 1.5


def _draw(painter_fn, color):
    """Render one pictogram with `color` and return it as a QIcon."""
    pixmap = QPixmap(ICON_SIZE * _SCALE, ICON_SIZE * _SCALE)
    pixmap.fill(Qt.transparent)
    pixmap.setDevicePixelRatio(float(_SCALE))

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    pen = QPen(QColor(color))
    pen.setWidthF(_PEN_WIDTH)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    # NOTE: QPainter already maps logical coordinates to the pixmap's
    # device pixels through its devicePixelRatio, so the drawing below uses
    # plain ICON_SIZE coordinates - an extra painter.scale() here would
    # scale twice and only show the top-left fragment of the icon.
    painter_fn(painter)
    painter.end()
    return QIcon(pixmap)


def magnifier_icon(color=None):
    """A magnifying glass (a circle with a handle in the lower right)."""
    def draw(p):
        p.drawEllipse(3.0, 3.0, 8.0, 8.0)
        p.drawLine(10.2, 10.2, 13.5, 13.5)

    return _draw(draw, color or styles.COLOR_TEXT)


def trash_icon(color=None):
    """A trash can (lid with a handle and a tapered body)."""
    def draw(p):
        p.drawLine(3.0, 4.5, 13.0, 4.5)              # lid
        p.drawLine(6.5, 4.5, 6.5, 2.5)               # handle
        p.drawLine(6.5, 2.5, 9.5, 2.5)
        p.drawLine(9.5, 2.5, 9.5, 4.5)
        p.drawLine(5.0, 6.5, 5.8, 13.0)              # body (left)
        p.drawLine(5.8, 13.0, 10.2, 13.0)            # body (bottom)
        p.drawLine(10.2, 13.0, 11.0, 6.5)            # body (right)

    return _draw(draw, color or styles.COLOR_DANGER)


def pencil_icon(color=None):
    """A pencil (a diagonal body with a point in the lower-left corner)."""
    def draw(p):
        tip = (3.5, 13.5)          # writing point
        body = (5.5, 11.5)         # where the point meets the body
        end = (12.5, 4.5)          # eraser end
        dx, dy = 1.0, 1.0          # half width, perpendicular to the body
        p.drawLine(tip[0], tip[1], body[0] - dx, body[1] - dy)
        p.drawLine(tip[0], tip[1], body[0] + dx, body[1] + dy)
        p.drawLine(body[0] - dx, body[1] - dy, end[0] - dx, end[1] - dy)
        p.drawLine(body[0] + dx, body[1] + dy, end[0] + dx, end[1] + dy)
        p.drawLine(end[0] - dx, end[1] - dy, end[0] + dx, end[1] + dy)

    return _draw(draw, color or styles.COLOR_TEXT)
