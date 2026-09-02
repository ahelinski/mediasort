"""Cutting a fragment out of a video without transcoding the whole file.

The heavy lifting is delegated to the ffmpeg/ffprobe command-line tools in
*stream copy* mode (``-c copy``): packets are only re-muxed, never decoded,
so the operation is lossless and roughly disk-speed fast.  Depending on the
chosen mode, a short segment at the cut boundary may be re-encoded, but the
whole movie is never transcoded.

Why this is needed at all: a compressed stream cannot start at an arbitrary
frame - a decoder needs the previous key frame (I-frame).  Stream-copy cuts
are therefore limited by the source's GOP structure, which is why this
module offers three modes (see build_plan):

* ``"fast"``  - plain ``-ss A -to B -i in -c copy``.  FFmpeg keeps a hidden
  "pre-roll" (the frames between the previous key frame and A) but hides it
  with negative timestamps + an MP4 edit list, so playback in modern players
  (including QtMultimedia) starts *exactly* at A.  Verified empirically on
  the repo's sample video (ffmpeg 6.1): frame at t=0 of the output is
  bit-identical to the original frame at A.
* ``"clean"`` - same remux, but A is snapped to a key frame found through
  ffprobe, so the output file itself starts at a real key frame and plays
  on *any* player (no edit-list dependency).  The start may shift by up to
  one GOP (typically < 1-2 s).
* ``"exact"`` - only the segment between A and the *next* key frame is
  re-encoded with the source's parameters; the rest is stream-copied; the
  two parts are then concatenated.  Frame-accurate A, clean file, at the
  cost of a few seconds of encoding and one extra generation on that short
  segment.

PySide6 ships the FFmpeg *libraries* used by QtMultimedia but no ffmpeg
CLI, so the tools are looked up in this order: explicit paths in settings
(``ffmpeg_path``/``ffprobe_path``) -> PATH -> bundled binaries next to the
app (``tools/`` next to the repository root).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import tempfile
from pathlib import Path

from PySide6.QtCore import QThread, Signal

# Modes ---------------------------------------------------------------

MODE_FAST = "fast"     # lossless stream copy (edit-list based exactness)
MODE_CLEAN = "clean"   # stream copy with A snapped to a key frame
MODE_EXACT = "exact"   # re-encode only the boundary segment, copy the rest

SUPPORTED_MODES = (MODE_FAST, MODE_CLEAN, MODE_EXACT)

# Codecs that can be re-encoded for the "exact" boundary segment without
# extra system codec packs (libx264 ships with every ffmpeg build; libx265
# is common but not guaranteed).
_EXACT_ENCODERS = {
    "h264": "libx264",
    "hevc": "libx265",
}

_APP_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Tool discovery
# ---------------------------------------------------------------------------
def _binary_name(name):
    return name + (".exe" if os.name == "nt" else "")


def _bundled_candidates(name):
    exe = _binary_name(name)
    candidates = [
        _APP_ROOT / "tools" / exe,
        _APP_ROOT / "tools" / "ffmpeg" / "bin" / exe,
    ]
    return [str(p) for p in candidates if p.is_file()]


def find_tool(settings, which):
    """Locate one CLI (``"ffmpeg"`` or ``"ffprobe"``).

    Order: explicit ``settings.<which>_path`` (only when it exists) ->
    PATH -> bundled binaries in ``tools/``.  Returns a path string or None.
    """
    key = f"{which}_path"
    configured = settings.get(key, default=None) if settings is not None else None
    if configured:
        configured = str(configured)
        if Path(configured).is_file():
            return configured
        # The sibling may still exist even if the configured one doesn't -
        # fall through to the normal lookup rather than failing hard.
    found = shutil.which(which)
    if found:
        return found
    bundled = _bundled_candidates(which)
    return bundled[0] if bundled else None


def find_tools(settings=None):
    """Return ``(ffmpeg_path, ffprobe_path)``, each possibly None.

    When only one of the two is configured in settings, its sibling next to
    it (same directory, other binary name) is used as the other tool.
    """
    ffmpeg = find_tool(settings, "ffmpeg")
    ffprobe = find_tool(settings, "ffprobe")
    if ffmpeg and not ffprobe:
        sibling = Path(ffmpeg).with_name(_binary_name("ffprobe"))
        if sibling.is_file():
            ffprobe = str(sibling)
    if ffprobe and not ffmpeg:
        sibling = Path(ffprobe).with_name(_binary_name("ffmpeg"))
        if sibling.is_file():
            ffmpeg = str(sibling)
    return ffmpeg, ffprobe


# ---------------------------------------------------------------------------
# ffprobe helpers
# ---------------------------------------------------------------------------
def _run_json(ffprobe, args):
    """Run ffprobe with ``args`` and return parsed JSON (or None on error)."""
    try:
        proc = subprocess.run(
            [ffprobe, "-v", "error", "-of", "json"] + args,
            capture_output=True, text=True, timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return None


def probe_media_info(ffprobe, path):
    """Return dict(ffprobe) describing the file, or None on failure.

    Keys: ``duration_ms`` and ``video`` (the first video stream's codec
    parameters: codec_name, profile, width, height, pix_fmt, fps) plus
    ``has_audio``.
    """
    data = _run_json(ffprobe, [
        "-show_entries",
        "format=duration:stream=index,codec_type,codec_name,profile,width,"
        "height,pix_fmt,avg_frame_rate,r_frame_rate",
        str(path),
    ])
    if not data:
        return None
    duration_ms = None
    try:
        duration_ms = int(float(data.get("format", {}).get("duration", 0)) * 1000)
    except (TypeError, ValueError):
        pass

    video = None
    has_audio = False
    for stream in data.get("streams", []):
        ctype = stream.get("codec_type")
        if ctype == "video" and video is None:
            fps = stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "0/0"
            video = {
                "codec_name": stream.get("codec_name"),
                "profile": stream.get("profile"),
                "width": stream.get("width"),
                "height": stream.get("height"),
                "pix_fmt": stream.get("pix_fmt"),
                "fps": fps,
            }
        elif ctype == "audio":
            has_audio = True
    return {"duration_ms": duration_ms, "video": video, "has_audio": has_audio}


def probe_keyframes_around(ffprobe, path, center_ms, window_ms=80000):
    """Return the sorted list of key-frame pts (seconds) near ``center_ms``.

    Read time is bounded to a window around ``center_ms``, and decoding is
    avoided entirely whenever possible:

    1. Fast path (demux only): ``-show_entries packet=...flags`` - key frames
       are the packets the *container* flags as sync samples (MP4/MOV read
       this from the ``stss`` sample table, so nothing is decoded).
    2. Fallback (only when the container does not flag key packets, e.g. some
       Matroska files): ``-skip_frame nokey -show_frames`` decodes just the
       key frames inside the same bounded window.

    The interval is expressed in *seconds* (``start%+duration``); note that
    ``%+#N`` would mean N *frames* and is intentionally not used here.
    """
    start_s = max(0.0, (center_ms - 10000) / 1000.0)
    rel_s = max(5.0, window_ms / 1000.0)
    interval = f"{start_s:.3f}%+{rel_s:.3f}"

    # 1) demux-only packet scan: container key-frame flags (no decoding).
    data = _run_json(ffprobe, [
        "-select_streams", "v:0",
        "-read_intervals", interval,
        "-show_entries", "packet=pts_time,flags",
        str(path),
    ])
    if data:
        keyframes = []
        for packet in data.get("packets", []):
            if "K" in packet.get("flags", ""):
                try:
                    keyframes.append(float(packet["pts_time"]))
                except (KeyError, TypeError, ValueError):
                    continue
        if keyframes:
            return sorted(keyframes)

    # 2) decode fallback for containers without packet key flags.
    data = _run_json(ffprobe, [
        "-select_streams", "v:0",
        "-skip_frame", "nokey",
        "-read_intervals", interval,
        "-show_entries", "frame=pts_time,pict_type",
        str(path),
    ])
    if not data:
        return []
    keyframes = []
    for frame in data.get("frames", []):
        if frame.get("pict_type") != "I":
            continue
        try:
            keyframes.append(float(frame["pts_time"]))
        except (KeyError, TypeError, ValueError):
            continue
    return sorted(keyframes)


def next_keyframe_at_or_after(ffprobe, path, sec):
    """First key frame with pts >= ``sec`` (seconds), or None."""
    keys = probe_keyframes_around(ffprobe, path, sec * 1000)
    for kf in keys:
        if kf >= sec - 0.002:  # tolerance for timestamp rounding
            return kf
    return None


def previous_keyframe_at_or_before(ffprobe, path, sec):
    """Last key frame with pts <= ``sec`` (seconds), or None."""
    keys = probe_keyframes_around(ffprobe, path, sec * 1000)
    prev = None
    for kf in keys:
        if kf <= sec + 0.002:
            prev = kf
        else:
            break
    return prev


# ---------------------------------------------------------------------------
# Command building
# ---------------------------------------------------------------------------
def _ts(ms):
    """FFmpeg timestamp string with millisecond precision."""
    return f"{ms / 1000.0:.3f}"


def _ffmpeg_base(ffmpeg, a_ms, b_ms, source):
    return [
        ffmpeg, "-hide_banner", "-v", "error", "-y",
        "-ss", _ts(a_ms), "-to", _ts(b_ms), "-i", str(source),
    ]


def _stream_copy_opts():
    # Copy the first video stream and (when present) the first audio stream
    # without re-encoding; drop other streams (subtitles, extra audio).
    return ["-map", "0:v:0", "-map", "0:a:0?", "-map_metadata", "0",
            "-c", "copy", "-movflags", "+faststart"]


def _progress_opts():
    return ["-progress", "pipe:1", "-nostats"]


class CutPlan:
    """Everything needed to cut one fragment: metadata for the UI preview
    plus the ffmpeg command lines for the worker.

    Attributes
    ----------
    mode : str
        One of MODE_FAST / MODE_CLEAN / MODE_EXACT.
    source : Path
    a_ms, b_ms : int
        Requested marks (ms).
    effective_a_ms : int
        Where the output will actually start (equals a_ms except when the
        start is snapped forward to a key frame).
    hidden_preroll_ms : int
        Only meaningful for fast mode: frames kept in the file (but hidden
        from playback) before A; 0 when the file is clean.
    info : list[str]
        Human-readable preview lines for the dialog.
    stages : list[dict]
        Each stage: {"label": str, "argv": list[str],
        "duration_ms": int, "out_is_final": bool}.
    needs_concat : bool
        Whether the stages must be concatenated afterwards (exact mode).
    """

    def __init__(self):
        self.mode = MODE_FAST
        self.clean_file = False
        self.snap_forward = True
        self.source = None
        self.a_ms = 0
        self.b_ms = 0
        self.effective_a_ms = 0
        self.hidden_preroll_ms = 0
        self.head_dur_ms = 0  # exact mode: duration of the re-encoded boundary
        self.info = []
        self.stages = []
        self.needs_concat = False
        self._errors = []

    @property
    def ok(self):
        return not self._errors

    def error_text(self):
        return "\n".join(self._errors)


def build_plan(ffmpeg, ffprobe, source, a_ms, b_ms, mode=MODE_FAST,
               clean_file=False, snap_forward=True, media_info=None):
    """Build a CutPlan for cutting [a_ms, b_ms) out of ``source``.

    ``mode`` selects MODE_FAST / MODE_CLEAN / MODE_EXACT.  ``clean_file``
    and ``snap_forward`` only matter for MODE_FAST: snapping A to the next
    (``snap_forward=True``) or previous (False) key frame removes the hidden
    pre-roll at the cost of shifting the start.  ``media_info`` may carry a
    previously probed result (see probe_media_info) to avoid re-probing when
    the plan is rebuilt repeatedly (e.g. live in the cut dialog).
    """
    plan = CutPlan()
    plan.source = Path(source)
    plan.a_ms = max(0, int(a_ms))
    plan.b_ms = int(b_ms)
    if plan.b_ms <= plan.a_ms:
        plan._errors.append("empty range")
        return plan

    mode = mode if mode in SUPPORTED_MODES else MODE_FAST
    if mode == MODE_CLEAN:
        mode = MODE_FAST
        clean_file = True
    plan.mode = mode
    plan.clean_file = bool(clean_file)
    plan.snap_forward = bool(snap_forward)

    info = media_info if media_info is not None else probe_media_info(
        ffprobe, str(plan.source)
    )
    if info is None or info["video"] is None:
        plan._errors.append("cannot probe the video stream")
        return plan
    duration_ms = info["duration_ms"]
    if duration_ms and plan.b_ms > duration_ms:
        plan.b_ms = duration_ms

    a_sec = plan.a_ms / 1000.0
    effective_a_ms = plan.a_ms
    snap_distance_ms = 0

    if mode == MODE_FAST:
        if clean_file:
            if snap_forward:
                kf = next_keyframe_at_or_after(ffprobe, plan.source, a_sec)
                direction = "after"
            else:
                kf = previous_keyframe_at_or_before(ffprobe, plan.source, a_sec)
                direction = "before"
            if kf is None:
                plan.info.append(
                    "No key frame found near the start mark - keeping the mark as is."
                )
            else:
                effective_a_ms = int(round(kf * 1000))
                snap_distance_ms = effective_a_ms - plan.a_ms
        # Note: the plain "fast" mode deliberately does NOT scan for key
        # frames here - FFmpeg's own seek handles the cut and modern players
        # honour the edit list. Scanning would only produce an informational
        # "hidden pre-roll length" number, and on large files a key-frame
        # scan is the slowest part of the whole feature.

        plan.effective_a_ms = effective_a_ms
        plan.stages.append({
            "label": "remux",
            "duration_ms": plan.b_ms - effective_a_ms,
            "argv": (_ffmpeg_base(ffmpeg, effective_a_ms, plan.b_ms, plan.source)
                     + _stream_copy_opts() + _progress_opts()),
            "out_is_final": True,
        })
        _describe_fast_plan(plan, snap_distance_ms, snap_forward,
                            clean_requested=clean_file)
        return plan

    # --- exact mode -------------------------------------------------
    video_codec = (info["video"] or {}).get("codec_name")
    encoder = _EXACT_ENCODERS.get(video_codec)
    if encoder is None:
        plan._errors.append(
            f"exact cut unsupported for codec '{video_codec}' "
            "(only H.264/HEVC); use fast mode"
        )
        return plan

    kf = next_keyframe_at_or_after(ffprobe, plan.source, a_sec)
    if kf is None:
        plan._errors.append("no key frame found near the start mark")
        return plan
    head_end_ms = min(int(round(kf * 1000)), plan.b_ms)
    if head_end_ms > plan.a_ms:
        plan.effective_a_ms = plan.a_ms  # re-encode starts exactly at A
    else:
        # A is already on a key frame - nothing to re-encode.
        head_end_ms = plan.a_ms
        plan.effective_a_ms = plan.a_ms

    if head_end_ms > plan.a_ms:
        v = info["video"]
        head_argv = _ffmpeg_base(ffmpeg, plan.a_ms, head_end_ms, plan.source)
        head_argv += ["-map", "0:v:0", "-map", "0:a:0?",
                      "-c:v", encoder, "-preset", "veryfast", "-crf", "18"]
        if video_codec == "hevc":
            head_argv += ["-tag:v", "hvc1"]
        profile = v.get("profile")
        if encoder == "libx264" and profile in ("High", "Main", "Baseline"):
            head_argv += ["-profile:v", str(profile).lower()]
        pix_fmt = v.get("pix_fmt")
        if pix_fmt and pix_fmt != "yuv420p":
            head_argv += ["-pix_fmt", "yuv420p"]  # mp4/mkv-safe everywhere
        fps = v.get("fps")
        if fps and fps not in ("0/0", "0"):
            head_argv += ["-r", str(fps)]
        if info["has_audio"]:
            head_argv += ["-c:a", "aac", "-b:a", "192k"]
        head_argv += _progress_opts()
        plan.stages.append({
            "label": "re-encode boundary",
            "duration_ms": head_end_ms - plan.a_ms,
            "argv": head_argv,
            "out_is_final": False,
        })

    if head_end_ms < plan.b_ms:
        tail_argv = _ffmpeg_base(ffmpeg, head_end_ms, plan.b_ms, plan.source)
        tail_argv += _stream_copy_opts() + _progress_opts()
        plan.stages.append({
            "label": "copy remainder",
            "duration_ms": plan.b_ms - head_end_ms,
            "argv": tail_argv,
            "out_is_final": False,
        })

    if len(plan.stages) == 1:
        plan.stages[0]["out_is_final"] = True
    else:
        plan.needs_concat = True

    head_sec = (head_end_ms - plan.a_ms) / 1000.0
    plan.head_dur_ms = max(0, head_end_ms - plan.a_ms)
    plan.info.append(
        f"Re-encoding {head_sec:.1f} s at the start (frame-accurate), "
        "stream-copying the rest - no whole-file transcoding."
    )
    return plan


def _describe_fast_plan(plan, snap_distance_ms, snap_forward, clean_requested):
    def fmt(ms):
        return f"{ms / 1000:.1f} s"

    if clean_requested and snap_distance_ms > 0:
        where = "after" if snap_forward else "before"
        plan.info.append(
            f"Start snapped to the key frame {where} the mark: "
            f"{fmt(plan.effective_a_ms)} instead of {fmt(plan.a_ms)}."
        )
    elif clean_requested and snap_distance_ms < 0:
        plan.info.append(
            f"Start moved to the previous key frame "
            f"({fmt(plan.effective_a_ms)}) so nothing before the mark is lost."
        )
    elif clean_requested:
        plan.info.append("Start mark is exactly on a key frame - no shift needed.")
    else:
        plan.info.append(
            "Lossless stream copy: playback starts exactly at the mark "
            "(modern players honour the hidden pre-roll)."
        )
    if plan.hidden_preroll_ms > 0:
        plan.info.append(
            f"The file keeps {plan.hidden_preroll_ms / 1000:.1f} s of hidden "
            "pre-roll before the mark (plays correctly in modern players)."
        )


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------
def _concat_escape(path):
    return str(path).replace("\\", "\\\\").replace("'", "\\'")


def run_stage(argv, cancel_event, progress_callback, stderr_path):
    """Run one ffmpeg command.

    Parses ``-progress pipe:1`` output (``out_time_us``/``out_time_ms``/
    ``out_time``) and forwards 0..1 fractions through ``progress_callback``.
    Returns ``(ok, message)``; on failure ``message`` contains the tail of
    ffmpeg's stderr.
    """
    proc = None
    try:
        with open(stderr_path, "w", encoding="utf-8", errors="replace") as err_f:
            proc = subprocess.Popen(
                argv, stdout=subprocess.PIPE, stderr=err_f, text=True,
                errors="replace",
            )
            assert proc.stdout is not None
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                    return False, "cancelled"
                line = proc.stdout.readline()
                if not line:
                    break
                fraction = _parse_progress_fraction(line)
                if fraction is not None and progress_callback is not None:
                    progress_callback(fraction)
            proc.wait()
        if proc.returncode == 0:
            return True, ""
        tail = _stderr_tail(stderr_path)
        return False, tail or f"ffmpeg exited with code {proc.returncode}"
    except OSError as e:
        return False, str(e)
    finally:
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait()


def _parse_progress_fraction(line):
    """Return the fractional progress encoded in one -progress line, or None."""
    line = line.strip()
    if line.startswith("out_time_us="):
        try:
            return max(0.0, int(line.split("=", 1)[1]) / 1_000_000.0)
        except ValueError:
            return None
    if line.startswith("out_time_ms="):
        try:
            return max(0.0, int(line.split("=", 1)[1]) / 1000.0)
        except ValueError:
            return None
    if line.startswith("out_time="):
        try:
            hours, minutes, rest = line.split("=", 1)[1].strip().split(":")
            seconds = float(rest)
            return max(0.0, float(hours) * 3600 + float(minutes) * 60 + seconds)
        except (ValueError, IndexError):
            return None
    return None


def _stderr_tail(stderr_path, limit=4000):
    try:
        text = Path(stderr_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    text = text.strip()
    if len(text) <= limit:
        return text
    return "..." + text[-limit:]


def run_plan(plan, out_path, progress_callback=None, cancel_event=None):
    """Execute a CutPlan synchronously (no Qt involved).

    Writes temporary files in a hidden work directory next to ``out_path``,
    then atomically renames the finished file into place.  Returns
    ``(True, final_path)`` on success or ``(False, message)`` - the message
    is ``"cancelled"`` when ``cancel_event`` was set mid-run.
    """
    out_path = Path(out_path)
    work_dir = None
    try:
        out_dir = out_path.parent
        out_dir.mkdir(parents=True, exist_ok=True)
        work_dir = Path(tempfile.mkdtemp(prefix=".ms_cut_", dir=str(out_dir)))
        stderr_path = work_dir / "ffmpeg_err.log"

        total_duration = max(1, plan.b_ms - plan.a_ms)
        completed_duration = 0
        stage_mapping = []
        for stage in plan.stages:
            stage_mapping.append((stage, completed_duration))
            completed_duration += stage["duration_ms"]

        def overall(fraction, start_dur, dur):
            return (start_dur + min(1.0, fraction) * dur) / total_duration

        produced = []
        for index, (stage, start_dur) in enumerate(stage_mapping):
            out_tmp = work_dir / f"part{index}{out_path.suffix}"
            argv = list(stage["argv"]) + [str(out_tmp)]
            dur = max(1, stage["duration_ms"])

            def cb(f, start_dur=start_dur, dur=dur):
                if progress_callback is not None:
                    progress_callback(overall(f, start_dur, dur))

            ok, message = run_stage(argv, cancel_event, cb, str(stderr_path))
            if cancel_event is not None and cancel_event.is_set():
                return False, "cancelled"
            if not ok:
                return False, _friendly_error(message)
            produced.append(out_tmp)

        if plan.needs_concat and len(produced) > 1:
            final_tmp = work_dir / ("final" + out_path.suffix)
            list_file = work_dir / "concat.txt"
            with open(list_file, "w", encoding="utf-8") as f:
                for p in produced:
                    f.write(f"file '{_concat_escape(p)}'\n")
            ffmpeg = plan.stages[0]["argv"][0]
            concat_argv = [
                ffmpeg, "-hide_banner", "-v", "error", "-y",
                "-f", "concat", "-safe", "0", "-i", str(list_file),
                "-c", "copy", "-movflags", "+faststart",
            ] + _progress_opts() + [str(final_tmp)]
            if progress_callback is not None:
                progress_callback(0.95)
            ok, message = run_stage(
                concat_argv, cancel_event,
                (lambda f: progress_callback(0.95 + 0.05 * min(1.0, f)))
                if progress_callback is not None else None,
                str(stderr_path),
            )
            if cancel_event is not None and cancel_event.is_set():
                return False, "cancelled"
            if not ok:
                return False, _friendly_error(message)
            produced = [final_tmp]

        os.replace(str(produced[-1]), str(out_path))
        if progress_callback is not None:
            progress_callback(1.0)
        return True, str(out_path)
    except OSError as e:
        return False, str(e)
    finally:
        if work_dir is not None:
            shutil.rmtree(work_dir, ignore_errors=True)


def _friendly_error(message):
    message = (message or "").strip()
    if "does not support" in message or "Invalid argument" in message:
        return (
            "FFmpeg could not write this fragment in the source container. "
            f"Details:\n{message}"
        )
    if not message:
        return "Unknown FFmpeg error."
    return message


class CutWorker(QThread):
    """Runs a video cut in the background; emits Qt signals for the dialog.

    The worker either receives a ready ``plan`` or a ``plan_fn`` callable
    that builds it inside the worker thread - the latter is used when
    building the plan needs slow ffprobe key-frame scans (clean/exact
    modes), so the dialog never blocks on them.

    Signals: ``plan_ready(object)`` (the built CutPlan), ``progress(float)``
    (0..1 overall, only during the actual FFmpeg run), ``finished_ok(str)``
    (final output path), ``failed(str)`` and ``cancelled()``.
    """

    plan_ready = Signal(object)
    progress = Signal(float)
    finished_ok = Signal(str)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, plan=None, out_path=None, plan_fn=None, parent=None):
        super().__init__(parent)
        assert plan is not None or plan_fn is not None, "plan or plan_fn required"
        self._plan = plan
        self._plan_fn = plan_fn
        self._out_path = Path(out_path) if out_path is not None else None
        self._cancel_event = threading.Event()

    def cancel(self):
        self._cancel_event.set()

    def run(self):
        plan = self._plan
        if plan is None and self._plan_fn is not None:
            try:
                plan = self._plan_fn()
            except Exception as e:  # noqa: BLE001 - report every failure
                self.failed.emit(f"Analysis error: {e}")
                return
            if plan is None or not plan.ok:
                self.failed.emit(plan.error_text() if plan is not None
                                 else "Could not build a cut plan.")
                return
            if self._cancel_event.is_set():
                self.cancelled.emit()
                return
            self.plan_ready.emit(plan)

        ok, result = run_plan(
            plan, self._out_path,
            progress_callback=lambda f: self.progress.emit(float(f)),
            cancel_event=self._cancel_event,
        )
        if not ok and result == "cancelled":
            self.cancelled.emit()
        elif not ok:
            self.failed.emit(result)
        else:
            self.finished_ok.emit(result)


# ---------------------------------------------------------------------------
# Console entry point (also used by the automated tests)
# ---------------------------------------------------------------------------
def _main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description="Cut a video fragment (lossless).")
    parser.add_argument("source")
    parser.add_argument("start", type=float, help="start in seconds")
    parser.add_argument("end", type=float, help="end in seconds")
    parser.add_argument("output")
    parser.add_argument("--mode", choices=SUPPORTED_MODES, default=MODE_FAST)
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--ffmpeg", default=None)
    parser.add_argument("--ffprobe", default=None)
    parser.add_argument("--no-wait", action="store_true")
    args = parser.parse_args(argv)

    class _Settings:
        def get(self, *keys, default=None):
            return default

    settings = _Settings()
    ffmpeg = args.ffmpeg or find_tool(settings, "ffmpeg")
    ffprobe = args.ffprobe or find_tool(settings, "ffprobe")
    if not ffmpeg or not ffprobe:
        print("ERROR: ffmpeg/ffprobe not found", file=sys.stderr)
        return 2

    plan = build_plan(
        ffmpeg, ffprobe, args.source,
        int(args.start * 1000), int(args.end * 1000),
        mode=args.mode, clean_file=args.clean,
    )
    if not plan.ok:
        print("ERROR: " + plan.error_text(), file=sys.stderr)
        return 3
    for line in plan.info:
        print("plan:", line)
    if args.no_wait:
        print("plan-only (--no-wait), not running ffmpeg")
        return 0

    ok, result = run_plan(plan, args.output)
    if ok:
        print("OK:", result)
        return 0
    print("ERROR:", result, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(_main())
