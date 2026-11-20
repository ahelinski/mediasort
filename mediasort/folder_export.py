"""Export / import the tag data of a whole folder tree.

The database stores absolute file paths, so moving a folder elsewhere (another
drive, disk, machine or operating system) would otherwise lose the link
between the files and their tags.  The *folder export* writes every tag entry
of the files inside a folder (and its subfolders) to a small JSON file placed
**inside that folder**, with paths relative to it.  After moving the folder,
the *folder import* reads that file back and recreates the entries for the new
absolute paths.

The stored paths always use ``/`` as the separator, so an export written on
Windows imports fine on Linux and vice versa; on import both separators are
accepted and converted to the local one.

Import is idempotent: entries that already exist are skipped (an existing
score is kept), and files listed in the export but absent from the folder are
reported and skipped instead of polluting the database.
"""
import json
import os
import time
from pathlib import Path

# Name of the file written into the exported folder and looked for on import.
EXPORT_FILE_NAME = "mediasort-export.json"
# Marker + schema version stored in the export ("format" / "version").
FORMAT_NAME = "mediasort-folder-export"
FORMAT_VERSION = 1


def export_folder(tags_db, folder):
    """Write the tag data of every file below `folder` to
    ``<folder>/mediasort-export.json``.

    Returns a stats dict ``{path, files, entries}``.  Raises
    :class:`NotADirectoryError` when `folder` is not a directory and lets
    I/O errors propagate - the caller reports them.
    """
    folder_path = Path(os.path.abspath(folder))
    if not folder_path.is_dir():
        raise NotADirectoryError(str(folder_path))

    files = {}
    for file_path, name, timestamp_sec, score in tags_db.all_assignments():
        parts = relative_parts(file_path, folder_path)
        if parts is None:
            continue                    # the file lives outside this folder
        relative = "/".join(parts)
        files.setdefault(relative, []).append({
            "name": name,
            "timestamp": timestamp_sec,
            "score": int(score),
        })

    document = {
        "format": FORMAT_NAME,
        "version": FORMAT_VERSION,
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "root": folder_path.name,
        "files": [
            {
                "path": relative,
                "tags": sorted(
                    entries,
                    key=lambda entry: (
                        entry["timestamp"] is not None,
                        entry["timestamp"] or 0,
                        str(entry["name"]).lower(),
                    ),
                ),
            }
            for relative, entries in sorted(files.items(), key=lambda item: item[0].lower())
        ],
    }

    target = folder_path / EXPORT_FILE_NAME
    target.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "path": str(target),
        "files": len(files),
        "entries": sum(len(entries) for entries in files.values()),
    }


def find_export_file(folder):
    """Locate the export file inside `folder` (only the top level).

    The canonical name is tried first; as a fallback any ``*.json`` that
    carries the export marker is accepted, so a renamed export still works.
    Returns a :class:`Path` or ``None``."""
    folder_path = Path(folder)
    candidate = folder_path / EXPORT_FILE_NAME
    if candidate.is_file():
        return candidate
    try:
        candidates = sorted(folder_path.glob("*.json"))
    except OSError:
        return None
    for path in candidates:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                document = json.load(handle)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(document, dict) and document.get("format") == FORMAT_NAME:
            return path
    return None


def import_folder(tags_db, folder):
    """Read the export file inside `folder` and recreate its tag entries.

    Returns a stats dict ``{source, files, added, skipped, missing, missing_paths}``.
    Raises :class:`FileNotFoundError` when there is no export file and
    :class:`ValueError` when the file is not a (supported) folder export.
    """
    folder_path = Path(os.path.abspath(folder))
    source = find_export_file(folder_path)
    if source is None:
        raise FileNotFoundError(str(folder_path))
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(str(exc)) from exc
    if not isinstance(document, dict) or document.get("format") != FORMAT_NAME:
        raise ValueError(f"{source} is not a {FORMAT_NAME} file")
    version = document.get("version", FORMAT_VERSION)
    try:
        version = int(version)
    except (TypeError, ValueError):
        version = FORMAT_VERSION
    if version > FORMAT_VERSION:
        raise ValueError(f"unsupported export version {version}")

    root_name = str(document.get("root") or "")
    added = 0
    skipped = 0
    missing_paths = []
    files = set()

    for file_entry in document.get("files") or []:
        if not isinstance(file_entry, dict):
            continue
        target = resolve_import_path(file_entry.get("path"), folder_path, root_name)
        if target is None:
            continue
        if not os.path.exists(target):
            missing_paths.append(str(file_entry.get("path")))
            continue
        files.add(str(target))
        for tag_entry in file_entry.get("tags") or []:
            if not isinstance(tag_entry, dict):
                continue
            name = str(tag_entry.get("name") or "").strip()
            if not name:
                continue
            timestamp_sec = tag_entry.get("timestamp")
            if timestamp_sec is not None:
                try:
                    timestamp_sec = int(timestamp_sec)
                except (TypeError, ValueError):
                    continue
                if timestamp_sec < 0:
                    timestamp_sec = None
            try:
                score = int(tag_entry.get("score") or 0)
            except (TypeError, ValueError):
                score = 0
            if tags_db.assign_tag(name, target, timestamp_sec, score=score):
                added += 1
            else:
                skipped += 1

    return {
        "source": str(source),
        "files": len(files),
        "added": added,
        "skipped": skipped,
        "missing": len(missing_paths),
        "missing_paths": missing_paths,
    }


# ----------------------------------------------------------------------
# Path helpers
# ----------------------------------------------------------------------
def relative_parts(file_path, root_path):
    """Split ``file_path`` into the parts below ``root_path`` (or ``None``
    when it does not live inside it).  Compared case-insensitively on
    Windows, where the stored path and the chosen folder may differ in case."""
    file_parts = Path(os.path.abspath(str(file_path))).parts
    root_parts = Path(os.path.abspath(str(root_path))).parts
    if len(file_parts) <= len(root_parts):
        return None
    if not _parts_equal(root_parts, file_parts[:len(root_parts)]):
        return None
    return list(file_parts[len(root_parts):])


def _parts_equal(left, right):
    if os.name == "nt":
        return [str(part).casefold() for part in left] == [str(part).casefold() for part in right]
    return list(left) == list(right)


def normalize_export_path(text):
    """Turn a stored export path into a list of local path parts.

    Accepts both separators (``sub/clip.mp4`` and ``sub\\clip.mp4``), drops a
    leading ``./`` and empty parts.  Returns ``None`` for a path that cannot
    be expressed relative to the import folder."""
    text = str(text or "").strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    text = text.strip()
    if not text:
        return None
    if _is_absolute_path(text):
        return None
    parts = [part for part in text.split("/") if part not in ("", ".")]
    if not parts or ".." in parts:
        return None                      # never escape the chosen folder
    return parts


def resolve_import_path(raw_path, folder_path, root_name=""):
    """Absolute local path for a stored export path, or ``None``.

    Relative paths are joined onto `folder_path`.  Absolute paths (only
    possible in hand-edited exports, since we always write relative ones) are
    mapped onto the folder by keeping whatever follows the exported root
    folder name, so an export can still be imported after somebody replaced
    the relative paths with full ones."""
    text = str(raw_path or "").strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    if not text:
        return None
    if _is_absolute_path(text):
        marker = f"/{root_name}/" if root_name else None
        if marker and marker in text:
            text = text.split(marker, 1)[1]
        else:
            return None
    parts = [part for part in text.split("/") if part not in ("", ".")]
    if not parts or ".." in parts:
        return None
    return str(Path(folder_path).joinpath(*parts))


def _is_absolute_path(text):
    if text.startswith(("/", "\\")):
        return True
    return len(text) >= 3 and text[1] == ":" and text[0].isalpha()   # C:/...
