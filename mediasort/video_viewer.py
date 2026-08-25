"""Full screen video viewer widget with a custom animated, clickable progress bar.

Uses QGraphicsVideoItem inside a QGraphicsView instead of QVideoWidget.
QVideoWidget can render through a native, hardware-accelerated overlay
window on some platforms/backends; that overlay sits outside Qt's normal
widget compositing, which caused the progress-bar overlay to be painted
"underneath" it (invisible) and could swallow keyboard shortcuts before
they reached the application's global event filter. QGraphicsVideoItem
paints video frames as part of the normal QGraphicsScene/QPainter
pipeline, so both the progress bar and keyboard shortcuts behave
correctly.

Progress bar behaviour (per spec):
  * Normally takes 0.5% of the screen's height.
  * When the cursor is in the lower quarter of the screen, it grows to
    10% of the screen's height, at 50% opacity.
  * While CTRL is held, the bar zooms in to show only 25% of the video's
    length, centered on the playback position at the moment CTRL was
    pressed (the zoomed window stays fixed while CTRL is held, it does
    not keep re-centering as playback continues).
  * Clicking (or dragging with the left mouse button) anywhere on the bar
    seeks the video to the corresponding position within whichever
    window is currently displayed (the full duration, or the zoomed-in
    slice while CTRL is held).
"""
from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsObject
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
from PySide6.QtCore import Qt, QUrl, QRectF, QSizeF, Signal
from PySide6.QtGui import QPainter, QColor, QPen, QBrush

class ProgressBarItem(QGraphicsObject):
    """Progress bar drawn as a QGraphicsItem so it is always composited
    on top of the video frame (no native overlay window involved).

    The bar always displays a "window" of the timeline - either the full
    video duration, or (while CTRL is held) a zoomed-in slice set via
    set_window(). Clicking/dragging on the bar emits seek_requested with
    a fraction (0.0-1.0) of the *currently displayed window* - the
    VideoViewer translates that fraction into an actual position.
    """

    BASE_HEIGHT_RATIO = 0.005   # 0.5% of screen height (normal state)
    HOVER_HEIGHT_RATIO = 0.10   # 10% of screen height (hovered state)
    HOVER_OPACITY = 0.5
    ZOOM_WINDOW_RATIO = 0.25    # show 25% of video length when zoomed

    seek_requested = Signal(float)  # fraction within the current window

    def __init__(self):
        super().__init__()
        self.setZValue(10)  # always draw above the video item (zValue 0)
        self.setAcceptedMouseButtons(Qt.LeftButton)
        self.setCursor(Qt.PointingHandCursor)
        self._w = 100.0
        self._h = 2.0
        self._duration_ms = 0
        self._position_ms = 0
        self._hovered = False
        self._window_start_ms = 0.0
        self._window_end_ms = 1.0

    # -- Qt API ------------------------------------------------------
    def boundingRect(self):
        return QRectF(0, 0, self._w, self._h)

    # -- state setters -------------------------------------------------
    def set_size(self, w, h):
        if w == self._w and h == self._h:
            return
        self.prepareGeometryChange()
        self._w = max(w, 1.0)
        self._h = max(h, 1.0)
        self.update()

    def set_duration(self, duration_ms):
        self._duration_ms = max(duration_ms, 0)
        self.update()

    def set_position(self, position_ms):
        self._position_ms = position_ms
        self.update()

    def set_hovered(self, hovered):
        if hovered != self._hovered:
            self._hovered = hovered
            self.update()

    def is_hovered(self):
        return self._hovered

    def set_window(self, start_ms, end_ms):
        """Set the timeline window (in ms) currently displayed by the bar."""
        if end_ms <= start_ms:
            end_ms = start_ms + 1
        if start_ms == self._window_start_ms and end_ms == self._window_end_ms:
            return
        self._window_start_ms = start_ms
        self._window_end_ms = end_ms
        self.update()

    def window(self):
        return self._window_start_ms, self._window_end_ms

    def height_for(self, view_height):
        if self._hovered:
            return max(view_height * self.HOVER_HEIGHT_RATIO, 6.0)
        return max(view_height * self.BASE_HEIGHT_RATIO, 2.0)

    # -- painting -------------------------------------------------------
    def paint(self, painter: QPainter, option, widget=None):
        w, h = self._w, self._h
        painter.setRenderHint(QPainter.Antialiasing)

        opacity = self.HOVER_OPACITY if self._hovered else 1.0
        painter.setOpacity(opacity)
        painter.fillRect(QRectF(0, 0, w, h), QColor(40, 40, 40))

        if self._duration_ms <= 0:
            return

        window_len = self._window_end_ms - self._window_start_ms
        if window_len <= 0:
            return
        progress = (self._position_ms - self._window_start_ms) / window_len
        progress = max(0.0, min(1.0, progress))
        fill_w = w * progress
        painter.fillRect(QRectF(0, 0, fill_w, h), QColor(220, 30, 30))

        painter.setPen(QPen(QColor(255, 255, 255), 2))
        painter.drawLine(int(fill_w), 0, int(fill_w), int(h))

    # -- mouse interaction (click / drag to seek) -----------------------
    def _emit_seek_for_pos(self, x):
        if self._w <= 0:
            return
        fraction = max(0.0, min(1.0, x / self._w))
        self.seek_requested.emit(fraction)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._emit_seek_for_pos(event.pos().x())
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self._emit_seek_for_pos(event.pos().x())
            event.accept()
        else:
            super().mouseMoveEvent(event)


class VideoViewer(QGraphicsView):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings

        self.setStyleSheet("background-color: black; border: none;")
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)

        self.scene = QGraphicsScene(self)
        self.scene.setBackgroundBrush(QBrush(QColor(0, 0, 0)))
        self.setScene(self.scene)

        self.video_item = QGraphicsVideoItem()
        self.video_item.setZValue(0)
        self.scene.addItem(self.video_item)

        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.player.setVideoOutput(self.video_item)

        self.progress_bar = ProgressBarItem()
        self.scene.addItem(self.progress_bar)
        self.progress_bar.seek_requested.connect(self._on_seek_requested)

        self.player.durationChanged.connect(self._on_duration_changed)
        self.player.positionChanged.connect(self.progress_bar.set_position)
        self.player.mediaStatusChanged.connect(self._on_media_status_changed)

        self._ctrl_pressed = False
        # Frozen zoom window (in ms), computed once when CTRL is pressed.
        self._zoom_start_ms = None
        self._zoom_end_ms = None
        # A seek requested at load() time, applied once the media has
        # actually finished loading (see _on_duration_changed) - calling
        # setPosition() immediately after setSource()/play() can be lost,
        # since the player may reset position once loading completes.
        self._pending_seek_ms = None

    # ------------------------------------------------------------------
    def load(self, path, seek_ms=None):
        self._ctrl_pressed = False
        self._zoom_start_ms = None
        self._zoom_end_ms = None
        self._pending_seek_ms = seek_ms
        self.player.setSource(QUrl.fromLocalFile(path))
        self.player.play()
        self._refresh_window()

    def stop(self):
        self.player.stop()

    def seek_seconds(self, seconds):
        new_pos = self.player.position() + seconds * 1000
        new_pos = max(0, min(new_pos, self.player.duration()))
        self.player.setPosition(int(new_pos))

    def go_to_timestamp(self, ts):
        new_pos = ts * 1000
        new_pos = max(0, min(new_pos, self.player.duration()))
        self.player.setPosition(int(new_pos))

    def toggle_pause(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def pause(self):
        self.player.pause()

    def is_paused(self):
        return self.player.playbackState() != QMediaPlayer.PlayingState

    def set_ctrl_pressed(self, pressed):
        if pressed == self._ctrl_pressed:
            return
        self._ctrl_pressed = pressed
        if pressed:
            duration = self.player.duration()
            if duration > 0:
                position = self.player.position()
                window_len = max(duration * ProgressBarItem.ZOOM_WINDOW_RATIO, 1)
                start = position - window_len / 2
                start = max(0.0, min(start, duration - window_len))
                self._zoom_start_ms = start
                self._zoom_end_ms = start + window_len
            else:
                self._zoom_start_ms = None
                self._zoom_end_ms = None
        self._refresh_window()

    # ------------------------------------------------------------------
    def _on_duration_changed(self, duration_ms):
        self.progress_bar.set_duration(duration_ms)
        self._refresh_window()

    def _on_media_status_changed(self, status):
        # Calling setPosition() right after setSource()/play() can be
        # silently ignored by the backend while the media is still in the
        # "Loading" state - durationChanged can even fire before that. The
        # position only reliably sticks once the media reaches
        # LoadedMedia, so that's when we apply any pending seek.
        if status == QMediaPlayer.MediaStatus.LoadedMedia and self._pending_seek_ms is not None:
            duration = self.player.duration()
            target = self._pending_seek_ms
            if duration > 0:
                target = max(0, min(target, duration))
            self.player.setPosition(int(target))
            self._pending_seek_ms = None

    def _refresh_window(self):
        duration = self.player.duration()
        if self._ctrl_pressed and self._zoom_start_ms is not None:
            self.progress_bar.set_window(self._zoom_start_ms, self._zoom_end_ms)
        else:
            self.progress_bar.set_window(0, max(duration, 1))

    def _on_seek_requested(self, fraction):
        start, end = self.progress_bar.window()
        target = start + fraction * (end - start)
        target = max(0, min(target, self.player.duration()))
        self.player.setPosition(int(target))


    # ------------------------------------------------------------------
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_layout()

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        self._update_hover(pos)

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.progress_bar.set_hovered(False)
        self._update_layout()

    def _update_hover(self, pos):
        w = self.viewport().width()
        h = self.viewport().height()
        in_lower_quarter = 0 <= pos.x() <= w and h * 0.75 <= pos.y() <= h
        if in_lower_quarter != self.progress_bar.is_hovered():
            self.progress_bar.set_hovered(in_lower_quarter)
            self._update_layout()

    def _update_layout(self):
        w = self.viewport().width()
        h = self.viewport().height()
        if w <= 0 or h <= 0:
            return
        self.setSceneRect(0, 0, w, h)
        self.video_item.setSize(QSizeF(w, h))
        self.video_item.setPos(0, 0)

        bar_h = self.progress_bar.height_for(h)
        self.progress_bar.set_size(w, bar_h)
        self.progress_bar.setPos(0, h - bar_h)