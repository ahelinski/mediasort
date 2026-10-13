"""Move files to the operating system's trash / recycle bin.

The application intentionally has no third-party runtime dependencies, so
the platform work is done here directly:

* **Windows** - ``SHFileOperationW`` with ``FOF_ALLOWUNDO``: the documented
  way to send a file to the Recycle Bin (the item stays restorable).
* **Linux/BSD** - the freedesktop.org trash specification: the home trash
  (``$XDG_DATA_HOME/Trash``) with its ``files/`` + ``info/`` folders and a
  ``.trashinfo`` per item, or the per-mount trash directory when the file
  lives on another device (so the move stays a cheap rename).  GLib's
  ``gio trash`` is tried first when it is installed, because it handles the
  corner cases (mounts without a trash directory, sticky-bit rules, ...).
* **macOS** - ``~/.Trash``.

:func:`move_to_trash` never raises for a single file: it returns the list of
files that went to the trash and a list of ``(path, error)`` pairs that did
not, so the caller can report a partial success.
"""
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path


def move_to_trash(paths):
    """Move every path in `paths` to the trash.

    Returns ``(trashed, failed)``: the paths that were moved and a list of
    ``(path, error)`` for the ones that were not (e.g. a file that had
    already disappeared).  Nothing is raised for individual failures.
    """
    trashed = []
    failed = []
    for path in paths:
        try:
            trash_path(str(path))
        except Exception as exc:            # noqa: BLE001 - reported to the UI
            failed.append((str(path), exc))
        else:
            trashed.append(str(path))
    return trashed, failed


def trash_path(path):
    """Send one file or folder to the trash; raise on failure."""
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    if sys.platform.startswith("win"):
        _trash_windows(path)
    elif sys.platform == "darwin":
        _trash_macos(path)
    else:
        _trash_freedesktop(path)


# ----------------------------------------------------------------------
# Windows: the Recycle Bin
# ----------------------------------------------------------------------
def _trash_windows(path):
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", wintypes.UINT),
            ("pFrom", ctypes.c_wchar_p),
            ("pTo", ctypes.c_wchar_p),
            ("fFlags", ctypes.c_uint16),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", ctypes.c_void_p),
            ("lpszProgressTitle", ctypes.c_wchar_p),
        ]

    FO_DELETE = 3
    FOF_SILENT = 0x0004
    FOF_NOCONFIRMATION = 0x0010
    FOF_ALLOWUNDO = 0x0040          # -> Recycle Bin instead of a hard delete
    FOF_NOERRORUI = 0x0400

    operation = SHFILEOPSTRUCTW()
    operation.hwnd = None
    operation.wFunc = FO_DELETE
    # pFrom must be a double-NUL terminated list; the Python string below
    # contributes one NUL and c_wchar_p appends the second one.
    operation.pFrom = os.path.abspath(path) + "\0"
    operation.pTo = None
    operation.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_NOERRORUI | FOF_SILENT

    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))
    if result != 0:
        raise OSError(result, f"SHFileOperationW failed (code {result}) for {path}")
    if operation.fAnyOperationsAborted:
        raise OSError(f"moving {path} to the Recycle Bin was aborted")


# ----------------------------------------------------------------------
# macOS
# ----------------------------------------------------------------------
def _trash_macos(path):
    trash_dir = Path.home() / ".Trash"
    trash_dir.mkdir(parents=True, exist_ok=True)
    target = trash_dir / _unique_name(trash_dir, None, Path(path).name)
    shutil.move(path, str(target))


# ----------------------------------------------------------------------
# Linux / BSD: freedesktop.org trash specification
# ----------------------------------------------------------------------
def _trash_freedesktop(path):
    if _gio_trash(path):
        return
    _trash_manually(path)


def _gio_trash(path):
    """Try GLib's ``gio trash``; return True when it handled the file."""
    executable = shutil.which("gio")
    if not executable:
        return False
    try:
        result = subprocess.run(
            [executable, "trash", "--", path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _trash_manually(path):
    """Implement the freedesktop trash spec ourselves (no GLib needed)."""
    source = Path(os.path.abspath(path))
    trash_dir = _trash_directory_for(source)
    files_dir = trash_dir / "files"
    info_dir = trash_dir / "info"
    files_dir.mkdir(parents=True, exist_ok=True)
    info_dir.mkdir(parents=True, exist_ok=True)

    name = _unique_name(files_dir, info_dir, source.name)
    # The .trashinfo is written before the file moves: a crash then leaves
    # an orphan metadata file (harmless) instead of a file in the trash
    # that the desktop cannot restore to its original place.
    info_path = info_dir / f"{name}.trashinfo"
    info_path.write_text(
        "[Trash Info]\n"
        f"Path={urllib.parse.quote(str(source))}\n"
        f"DeletionDate={time.strftime('%Y-%m-%dT%H:%M:%S')}\n",
        encoding="utf-8",
    )
    target = files_dir / name
    try:
        try:
            os.rename(source, target)     # same device: a plain move
        except OSError:
            shutil.move(str(source), str(target))   # different device: copy
    except OSError:
        info_path.unlink(missing_ok=True)
        raise


def _home_trash_dir():
    data_home = os.environ.get("XDG_DATA_HOME")
    if not data_home:
        data_home = str(Path.home() / ".local" / "share")
    return Path(data_home) / "Trash"


def _trash_directory_for(source):
    """The trash directory the spec assigns to `source`: the home trash for
    files on the same device, otherwise the mount's own trash folder (which
    keeps the operation a rename on the same filesystem)."""
    home_trash = _home_trash_dir()
    try:
        if source.stat().st_dev == home_trash.stat().st_dev:
            return home_trash
    except OSError:
        return home_trash                  # no home trash yet -> create it

    uid = os.getuid()
    mount_point = _mount_point(source)
    shared = Path(mount_point) / ".Trash" / str(uid)
    if shared.is_dir() and os.access(shared, os.W_OK):
        return shared
    own = Path(mount_point) / f".Trash-{uid}"
    if own.is_dir() and os.access(own, os.W_OK):
        return own
    try:
        own.mkdir(parents=True, exist_ok=True)
        return own
    except OSError:
        # Read-only mount (or no permission): the home trash still works,
        # at the price of copying the file across filesystems.
        return home_trash


def _mount_point(path):
    """Filesystem root that `path` lives on (walks up while the device id
    stays the same)."""
    current = Path(path)
    if not current.is_dir():
        current = current.parent
    try:
        device = current.stat().st_dev
    except OSError:
        return current
    while True:
        parent = current.parent
        if parent == current:
            return current
        try:
            if parent.stat().st_dev != device:
                return current
        except OSError:
            return current
        current = parent


def _unique_name(files_dir, info_dir, name):
    """First free name in the trash's ``files/`` (and ``info/``) folder:
    ``name``, then ``name.2``, ``name.3``, ..."""
    candidate = name
    counter = 1
    while True:
        taken = (files_dir / candidate).exists()
        if not taken and info_dir is not None:
            taken = (info_dir / f"{candidate}.trashinfo").exists()
        if not taken:
            return candidate
        counter += 1
        candidate = f"{name}.{counter}"
