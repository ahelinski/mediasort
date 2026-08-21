"""Small thumbnail helpers used by the file operation dialog's selection panel.

For images we simply load and downscale the real file. For videos, decoding
a real frame would require pulling in extra dependencies (ffmpeg CLI,
OpenCV, etc.) just for a tiny preview icon, so - per spec, this is
explicitly an optional nice-to-have - we draw a small generic "video" icon
instead (a dark tile with a play triangle). This keeps thumbnail lookups
fast and dependency-free while still visually distinguishing videos from
images in the selection summary.
"""
from pathlib import Path

from PySide6.QtGui import QPixmap, QPainter, QColor, QPolygon
from PySide6.QtCore import Qt, QPoint

_cache = {}


def get_thumbnail(path: str, kind: str, size: int = 48) -> QPixmap:
    """Return a small (size x size max) QPixmap preview for the given file."""
    key = (path, kind, size)
    cached = _cache.get(key)
    if cached is not None:
        return cached

    if kind == "image":
        pm = QPixmap(path)
        if pm.isNull():
            pm = _broken_icon(size)
        else:
            pm = pm.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    else:
        pm = _video_icon(size)

    _cache[key] = pm
    return pm


def _video_icon(size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(QColor(35, 35, 35))
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(225, 225, 225))
    cx, cy = size / 2.0, size / 2.0
    tri = size * 0.32
    points = [
        QPoint(int(cx - tri / 2), int(cy - tri * 0.62)),
        QPoint(int(cx - tri / 2), int(cy + tri * 0.62)),
        QPoint(int(cx + tri * 0.75), int(cy)),
    ]
    painter.drawPolygon(QPolygon(points))
    painter.end()
    return pm


def _broken_icon(size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(QColor(60, 25, 25))
    return pm


def clear_cache():
    _cache.clear()
