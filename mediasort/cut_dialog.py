"""Dialog for cutting a fragment out of the currently viewed video.

The heavy lifting happens in :mod:`mediasort.video_cutter`; this dialog:

* lets the user type (or keep the A/B marks set during playback with the
  ``[``/``]`` keys) the start and end of the fragment;
* chooses the cut mode: fast lossless remux (default), or an "exact" cut
  that re-encodes only the few seconds at the boundary;
* optionally snaps the start to a key frame ("clean file");
* writes to a brand-new file (the source is never modified).

Performance / responsiveness contract:

* Opening the dialog and editing the time fields is **instant** - the
  preview is derived locally from the requested range, no ffprobe key-frame
  scan is started (a key-frame scan can take seconds on large files).
* Confirming ("Wytnij") shows the progress bar **immediately**. Everything
  that can take time - probing key frames (clean/exact modes), building the
  final plan and running FFmpeg - happens on a worker thread. The progress
  bar is indeterminate while the plan is being analysed and turns into a
  percentage bar while FFmpeg runs; a precise preview of the actual range
  appears as soon as the analysis finishes.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout, QLabel,
    QLineEdit, QPushButton, QRadioButton, QCheckBox, QGroupBox, QProgressBar,
    QFileDialog, QMessageBox, QWidget,
)

from . import styles
from . import video_cutter as vc
from .i18n import tr


def parse_time_to_ms(text):
    """Parse a user-typed time into milliseconds.

    Accepted forms (the fractional part may use '.' or ','):
      * ``5`` / ``5.3``          - plain seconds
      * ``1:30`` / ``1:30.5``    - minutes:seconds
      * ``1:02:03.4``            - hours:minutes:seconds
    Returns None when the text is not a valid time.
    """
    if text is None:
        return None
    text = str(text).strip().replace(",", ".")
    if not text:
        return None
    try:
        if ":" in text:
            parts = text.split(":")
            if len(parts) > 3:
                return None
            values = [float(p) for p in parts]
            if any(v < 0 for v in values):
                return None
            seconds = 0.0
            for v in values:
                seconds = seconds * 60 + v
            return int(round(seconds * 1000))
        seconds = float(text)
        if seconds < 0:
            return None
        return int(round(seconds * 1000))
    except ValueError:
        return None


def format_time(ms, force_minutes=True):
    """Format milliseconds as ``m:ss.t`` (Polish decimal comma)."""
    if ms is None or ms < 0:
        ms = 0
    total_tenths = ms // 100
    tenths = total_tenths % 10
    total_seconds = total_tenths // 10
    minutes, seconds = divmod(total_seconds, 60)
    if force_minutes:
        return f"{minutes}:{seconds:02d},{tenths}"
    return f"{seconds},{tenths}"


def format_seconds(seconds):
    """Format a seconds value with one decimal, Polish comma."""
    return f"{seconds:.1f}".replace(".", ",")


def _filename_time(ms):
    """Windows-safe fragment label used in default output names."""
    ms = max(0, int(ms))
    total_tenths = ms // 100
    tenths = total_tenths % 10
    total_seconds = total_tenths // 10
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}m{seconds:02d}.{tenths}s"


def default_output_name(stem, suffix, a_ms, b_ms):
    return f"{stem}_cut_{_filename_time(a_ms)}-{_filename_time(b_ms)}{suffix}"


def unique_output_path(directory, filename):
    """Return a Path in ``directory`` that does not exist yet, appending
    ' (1)', ' (2)', ... on collision."""
    directory = Path(directory)
    candidate = directory / filename
    stem, suffix = candidate.stem, candidate.suffix
    n = 1
    while candidate.exists():
        candidate = directory / f"{stem} ({n}){suffix}"
        n += 1
    return candidate


class CutDialog(QDialog):
    """Modal cut dialog (see module docstring)."""

    def __init__(self, source_path, folder, settings, duration_ms,
                 a_ms=None, b_ms=None, parent=None):
        super().__init__(parent)
        self._source = Path(source_path)
        self._folder = folder
        self._settings = settings
        self._duration_ms = max(0, int(duration_ms or 0))
        self._ffmpeg, self._ffprobe = vc.find_tools(settings)
        # Cheap single ffprobe call (stream parameters, ~0.1 s): used only
        # to gate the "exact" mode on supported codecs and as a duration
        # fallback. Never scans key frames.
        self._media_info = None
        self._plan = None          # precise plan, set by plan_ready signal
        self._worker = None
        self._running = False
        self._busy = False
        self.result_path = None
        # Actual fragment range of the produced file (ms) - the start is the
        # key-frame-snapped one when a "clean file" cut shifted it. Used by
        # the caller to copy the source's timestamp tags into the fragment.
        self.result_start_ms = None
        self.result_end_ms = None
        self._name_auto = True
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(200)
        self._debounce.timeout.connect(self._refresh_preview)

        self.setWindowTitle(tr("cut.title"))
        self.setStyleSheet(styles.DIALOG)
        self.setModal(True)
        self.setMinimumWidth(580)

        self._build_ui()
        self._probe_media()

        # Initial values: the dialog opener passes the A/B marks set during
        # playback; a bare end defaults to the whole remaining video.
        if a_ms is None:
            a_ms = 0
        if b_ms is None:
            b_ms = self._duration_ms
        self._start_edit.setText(format_time(a_ms))
        self._end_edit.setText(format_time(b_ms))

        self._update_filename()
        self._refresh_preview()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        root = QVBoxLayout(self)

        src = QLabel(tr("cut.source_file", filename=self._source.name))
        src.setStyleSheet(styles.INFO)
        src.setWordWrap(True)
        root.addWidget(src)

        # Range row: start / end time inputs.
        range_group = QGroupBox(tr("cut.range_group"), self)
        grid = QGridLayout(range_group)
        self._start_edit = QLineEdit(range_group)
        self._end_edit = QLineEdit(range_group)
        for edit in (self._start_edit, self._end_edit):
            edit.setAlignment(Qt.AlignRight)
            edit.setMaximumWidth(120)
            edit.textChanged.connect(self._schedule_refresh)
        grid.addWidget(QLabel(tr("cut.start_label"), range_group), 0, 0)
        grid.addWidget(self._start_edit, 0, 1)
        grid.addWidget(QLabel(tr("cut.end_label"), range_group), 1, 0)
        grid.addWidget(self._end_edit, 1, 1)
        grid.setColumnStretch(2, 1)
        root.addWidget(range_group)

        # Mode radios.
        mode_group = QGroupBox(tr("cut.mode_group"), self)
        mode_box = QVBoxLayout(mode_group)
        self._fast_radio = QRadioButton(tr("cut.mode_fast"), mode_group)
        self._exact_radio = QRadioButton(tr("cut.mode_exact"), mode_group)
        mode_box.addWidget(self._fast_radio)
        mode_box.addWidget(self._exact_radio)
        for radio in (self._fast_radio, self._exact_radio):
            radio.toggled.connect(self._schedule_refresh)
        root.addWidget(mode_group)

        # "Clean file" (snap to key frame) - only meaningful in fast mode.
        self._clean_check = QCheckBox(tr("cut.clean_file"), self)
        self._snap_forward = QRadioButton(tr("cut.snap_forward"), self)
        self._snap_backward = QRadioButton(tr("cut.snap_backward"), self)
        snap_row = QWidget(self)
        snap_layout = QHBoxLayout(snap_row)
        snap_layout.setContentsMargins(24, 0, 0, 0)
        snap_layout.setSpacing(8)
        snap_layout.addWidget(self._snap_forward)
        snap_layout.addWidget(self._snap_backward)
        self._snap_forward.setChecked(True)
        for widget in (self._clean_check, self._snap_forward, self._snap_backward):
            widget.toggled.connect(self._schedule_refresh)
        root.addWidget(self._clean_check)
        root.addWidget(snap_row)
        root.addSpacing(4)

        # Destination folder + output file name.
        form = QFormLayout()
        dest_row = QWidget(self)
        dest_layout = QHBoxLayout(dest_row)
        dest_layout.setContentsMargins(0, 0, 0, 0)
        self._dest_edit = QLineEdit(str(self._folder), dest_row)
        browse_btn = QPushButton(tr("cut.browse_btn"), dest_row)
        browse_btn.clicked.connect(self._browse_destination)
        dest_layout.addWidget(self._dest_edit, 1)
        dest_layout.addWidget(browse_btn)
        form.addRow(tr("cut.dest_label"), dest_row)

        self._name_edit = QLineEdit(dest_row)
        self._name_edit.textEdited.connect(self._on_name_edited)
        form.addRow(tr("cut.name_label"), self._name_edit)
        root.addLayout(form)

        # Preview of the output range. Shown instantly from the requested
        # range; when the worker finishes analysing (clean/exact modes) the
        # precise, key-frame-accurate range replaces it via plan_ready.
        self._preview_label = QLabel("", self)
        self._preview_label.setWordWrap(True)
        self._preview_label.setTextFormat(Qt.RichText)
        root.addWidget(self._preview_label)

        # Progress + status. Indeterminate (busy) while the worker analyses
        # the file, a percentage bar while FFmpeg actually runs.
        self._progress = QProgressBar(self)
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setStyleSheet(styles.PROGRESS)
        self._progress.hide()
        self._status_label = QLabel("", self)
        self._status_label.setStyleSheet(styles.INFO)
        root.addWidget(self._status_label)

        # Buttons. Real buttons (not flat links): "Wytnij" is the dialog's
        # default action, so pressing Enter anywhere in the dialog confirms
        # the cut (it is disabled while the cut is running).
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self._cancel_btn = QPushButton(tr("cut.cancel_btn"), self)
        self._cancel_btn.setStyleSheet(styles.SECONDARY_BUTTON)
        self._cancel_btn.setAutoDefault(False)
        self._cancel_btn.clicked.connect(self._on_cancel_clicked)
        self._cut_btn = QPushButton(tr("cut.cut_btn"), self)
        self._cut_btn.setStyleSheet(styles.PRIMARY_BUTTON)
        self._cut_btn.setDefault(True)
        self._cut_btn.clicked.connect(self._on_cut_clicked)
        buttons.addWidget(self._cancel_btn)
        buttons.addWidget(self._cut_btn)
        root.addLayout(buttons)

        # Initial mode selection.
        default_mode = self._settings.get("cut_default_mode", default="fast")
        (self._exact_radio if default_mode == "exact" else self._fast_radio).setChecked(True)
        self._clean_check.setChecked(
            bool(self._settings.get("cut_clean_file", default=False))
        )
        self._sync_mode_widgets()

    def _sync_mode_widgets(self):
        fast = self._fast_radio.isChecked()
        can_exact = self._exact_supported()
        self._exact_radio.setEnabled(can_exact)
        if not can_exact and self._exact_radio.isChecked():
            self._fast_radio.setChecked(True)
        clean = fast and self._clean_check.isChecked()
        self._clean_check.setEnabled(fast)
        self._snap_forward.setEnabled(clean)
        self._snap_backward.setEnabled(clean)

    def _exact_supported(self):
        if not self._media_info or not self._media_info.get("video"):
            return False
        return (self._media_info["video"].get("codec_name") or "") in vc._EXACT_ENCODERS

    # ------------------------------------------------------------------
    # Probing (light, non-blocking by design)
    # ------------------------------------------------------------------
    def _probe_media(self):
        if not self._ffprobe:
            return
        # A single cheap call for stream parameters (codec support gating
        # and a duration fallback). Deliberately no key-frame scanning here.
        self._media_info = vc.probe_media_info(self._ffprobe, str(self._source))
        if self._duration_ms <= 0 and self._media_info:
            self._duration_ms = self._media_info.get("duration_ms") or 0
        self._sync_mode_widgets()

    def _schedule_refresh(self, *_args):
        self._sync_mode_widgets()
        self._debounce.start()

    # ------------------------------------------------------------------
    # Local preview (no ffprobe at all)
    # ------------------------------------------------------------------
    def _refresh_preview(self):
        if not (self._ffmpeg and self._ffprobe):
            self._set_error(tr("cut.error_no_tools"))
            return
        a_ms = parse_time_to_ms(self._start_edit.text())
        b_ms = parse_time_to_ms(self._end_edit.text())
        if a_ms is None or b_ms is None:
            self._set_error(tr("cut.error_bad_time"))
            return
        if b_ms <= a_ms:
            self._set_error(tr("cut.error_range"))
            return
        if self._duration_ms and a_ms >= self._duration_ms:
            self._set_error(tr("cut.error_start_past_end"))
            return
        if self._duration_ms and b_ms > self._duration_ms:
            b_ms = self._duration_ms

        lines = [tr(
            "cut.preview_range",
            a=format_time(a_ms),
            b=format_time(b_ms),
        )]
        if self._exact_radio.isChecked():
            lines.append(tr("cut.preview_exact"))
        elif self._clean_check.isChecked():
            lines.append(tr("cut.preview_clean_deferred"))
        else:
            lines.append(tr("cut.preview_fast"))
        self._preview_label.setText(
            " · ".join(f'<span style="color:{styles.COLOR_TEXT_MUTED};">{line}</span>'
                       for line in lines)
        )
        self._cut_btn.setEnabled(True)

    def _set_error(self, text):
        self._preview_label.setText(
            f'<span style="color:{styles.COLOR_DANGER};">{text}</span>'
        )
        self._cut_btn.setEnabled(False)

    # ------------------------------------------------------------------
    # Precise preview once the worker has analysed the file
    # ------------------------------------------------------------------
    def _show_analysed_preview(self, plan):
        """Replaces the generic preview with the exact one after the worker
        has probed key frames (emitted on the plan_ready signal)."""
        lines = []
        if plan.mode == vc.MODE_EXACT:
            lines.append(tr(
                "cut.preview_exact_detail",
                head=format_seconds(plan.head_dur_ms / 1000.0),
                out_a=format_time(plan.effective_a_ms),
                out_b=format_time(plan.b_ms),
            ))
        elif plan.clean_file:
            if plan.effective_a_ms != plan.a_ms:
                if plan.snap_forward:
                    lines.append(tr(
                        "cut.preview_snap_after",
                        req=format_time(plan.a_ms),
                        eff=format_time(plan.effective_a_ms),
                    ))
                else:
                    lines.append(tr(
                        "cut.preview_snap_before",
                        req=format_time(plan.a_ms),
                        eff=format_time(plan.effective_a_ms),
                    ))
            else:
                lines.append(tr("cut.preview_clean_no_shift"))
        else:
            lines.append(tr("cut.preview_fast"))
        lines.append(tr(
            "cut.preview_range",
            a=format_time(plan.effective_a_ms),
            b=format_time(plan.b_ms),
        ))
        self._preview_label.setText(
            " · ".join(f'<span style="color:{styles.COLOR_TEXT_MUTED};">{line}</span>'
                       for line in lines)
        )

    # ------------------------------------------------------------------
    # Output naming
    # ------------------------------------------------------------------
    def _on_name_edited(self, _text):
        self._name_auto = False

    def _update_filename(self):
        if not self._name_auto:
            return
        a_ms = parse_time_to_ms(self._start_edit.text())
        b_ms = parse_time_to_ms(self._end_edit.text())
        if a_ms is None or b_ms is None or b_ms <= a_ms:
            return
        if self._duration_ms and b_ms > self._duration_ms:
            b_ms = self._duration_ms
        self._name_edit.setText(default_output_name(
            self._source.stem, self._source.suffix, a_ms, b_ms,
        ))

    def _browse_destination(self):
        directory = QFileDialog.getExistingDirectory(
            self, tr("cut.dest_title"), self._dest_edit.text()
        )
        if directory:
            self._dest_edit.setText(directory)

    # ------------------------------------------------------------------
    # Cut execution (all heavy work on the worker thread)
    # ------------------------------------------------------------------
    def _on_cut_clicked(self):
        self._refresh_preview()
        if not self._cut_btn.isEnabled():
            return  # the preview shows why
        a_ms = parse_time_to_ms(self._start_edit.text())
        b_ms = parse_time_to_ms(self._end_edit.text())
        if a_ms is None or b_ms is None or b_ms <= a_ms:
            return
        if self._duration_ms and b_ms > self._duration_ms:
            b_ms = self._duration_ms

        out_dir = Path(self._dest_edit.text().strip()).expanduser()
        if not out_dir.is_dir():
            QMessageBox.warning(
                self, tr("common.error_title"),
                tr("cut.error_dest_missing", path=str(out_dir)),
            )
            return
        name = self._name_edit.text().strip()
        if not name:
            self._update_filename()
            name = self._name_edit.text().strip()
        if not Path(name).suffix:
            name += self._source.suffix
        out_path = unique_output_path(out_dir, name)

        mode = vc.MODE_FAST if self._fast_radio.isChecked() else vc.MODE_EXACT
        clean = bool(self._fast_radio.isChecked() and self._clean_check.isChecked())
        ffmpeg, ffprobe = self._ffmpeg, self._ffprobe
        source = str(self._source)
        media_info = self._media_info
        snap_forward = self._snap_forward.isChecked()

        def plan_fn():
            # Runs inside the worker thread: probes key frames (clean/exact)
            # and builds the final plan - never blocks the UI.
            return vc.build_plan(
                ffmpeg, ffprobe, source, a_ms, b_ms,
                mode=mode, clean_file=clean, snap_forward=snap_forward,
                media_info=media_info,
            )

        from .video_cutter import CutWorker
        self._worker = CutWorker(out_path=str(out_path), plan_fn=plan_fn,
                                 parent=self)
        self._worker.plan_ready.connect(self._on_plan_ready)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_ok.connect(self._on_success)
        self._worker.failed.connect(self._on_failure)
        self._worker.cancelled.connect(self._on_worker_cancelled)

        needs_analysis = mode == vc.MODE_EXACT or clean
        self._set_running(True, busy=True)
        self._status_label.setText(
            tr("cut.status_analysing") if needs_analysis else tr("cut.status_running")
        )
        self._worker.start()

    # ------------------------------------------------------------------
    # Worker signal handlers
    # ------------------------------------------------------------------
    def _on_plan_ready(self, plan):
        self._plan = plan
        # Analysis finished - from now on the bar shows the real percentage.
        self._set_busy(False)
        self._status_label.setText(tr("cut.status_running"))
        self._show_analysed_preview(plan)

    def _on_progress(self, fraction):
        if self._busy:
            self._set_busy(False)
            self._status_label.setText(tr("cut.status_running"))
        self._progress.setValue(int(fraction * 100))

    def _set_running(self, running, busy=False):
        self._running = running
        self._busy = busy
        self._cut_btn.setEnabled(not running)
        for widget in (self._start_edit, self._end_edit, self._dest_edit,
                       self._name_edit, self._clean_check, self._snap_forward,
                       self._snap_backward, self._fast_radio, self._exact_radio):
            widget.setEnabled(not running)
        self._progress.setVisible(running)
        if running:
            if busy:
                self._progress.setRange(0, 0)  # indeterminate / busy
                self._progress.setValue(0)
            else:
                self._progress.setRange(0, 100)
                self._progress.setValue(0)
        else:
            self._progress.setRange(0, 100)
            self._progress.setValue(0)
            self._status_label.setText("")

    def _set_busy(self, busy):
        self._busy = busy
        if busy:
            self._progress.setRange(0, 0)
        else:
            self._progress.setRange(0, 100)

    def _on_success(self, path):
        self._wait_worker()
        self.result_path = path
        if self._plan is not None:
            self.result_start_ms = self._plan.effective_a_ms
            self.result_end_ms = self._plan.b_ms
        self._set_running(False)
        self.accept()

    def _on_failure(self, message):
        self._wait_worker()
        self._set_running(False)
        QMessageBox.critical(
            self, tr("cut.error_run_title"), tr("cut.error_run", error=message)
        )

    def _on_worker_cancelled(self):
        self._wait_worker()
        self._set_running(False)
        self._cancel_btn.setEnabled(True)
        if self._close_after_cancel:
            self.reject()
        else:
            self._status_label.setText(tr("cut.status_cancelled"))

    def _wait_worker(self):
        """Block until the worker thread has fully returned (it emits its
        terminal signal just before run() ends, so this is near-instant)
        and let Qt delete it safely afterwards."""
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.wait()
            worker.deleteLater()

    def _on_cancel_clicked(self):
        if self._running and self._worker is not None:
            self._status_label.setText(tr("cut.status_cancelling"))
            self._cancel_btn.setEnabled(False)
            self._close_after_cancel = True
            self._worker.cancel()
            return
        self.reject()
