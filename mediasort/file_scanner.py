"""Helpers for scanning folders for media files and subfolders."""
import os
from pathlib import Path


def kind_for_path(path, image_exts, video_exts):
    """Return "image", "video", or None based on the file's extension.
    Used for tag instances, which can point at files outside the
    currently open folder."""
    suffix = Path(path).suffix.lower()
    if suffix in image_exts:
        return "image"
    if suffix in video_exts:
        return "video"
    return None


def scan_media(folder, image_exts, video_exts):
    """Return a sorted list of (path, kind) tuples for media files directly
    inside `folder`. `kind` is either "image" or "video"."""
    folder = Path(folder)
    items = []
    try:
        with os.scandir(folder) as it:
            for entry in it:
                if entry.is_file():
                    suffix = Path(entry.name).suffix.lower()
                    if suffix in image_exts:
                        items.append((entry.path, "image"))
                    elif suffix in video_exts:
                        items.append((entry.path, "video"))
    except OSError:
        pass
    items.sort(key=lambda t: os.path.basename(t[0]).lower())
    return items


def list_subfolders(folder):
    """Return a sorted list of subfolder paths directly inside `folder`."""
    folder = Path(folder)
    subs = []
    try:
        with os.scandir(folder) as it:
            for entry in it:
                if entry.is_dir():
                    subs.append(entry.path)
    except OSError:
        pass
    subs.sort(key=lambda p: os.path.basename(p).lower())
    return subs


def scan_media_recursive(folder, image_exts, video_exts, max_depth=1):
    """Like scan_media(), but also descends into subfolders up to
    `max_depth` levels deep (0 = only `folder` itself, 1 = `folder` plus
    its immediate subfolders, 2 = plus their subfolders, and so on).
    Returns a single sorted list of (path, kind) tuples covering every
    folder visited."""
    all_items = []
    _scan_recursive(Path(folder), image_exts, video_exts, max_depth, all_items)
    all_items.sort(key=lambda t: t[0].lower())
    return all_items


def _scan_recursive(folder, image_exts, video_exts, depth_remaining, out):
    out.extend(scan_media(folder, image_exts, video_exts))
    if depth_remaining <= 0:
        return
    for sub in list_subfolders(folder):
        _scan_recursive(sub, image_exts, video_exts, depth_remaining - 1, out)
