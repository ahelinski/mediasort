"""Local SQLite database for the Tags Library feature.

Stores tags and their assignments to files - either a whole-file
assignment, or a "timestamp tag" pinned to a specific second of a video.
A tag is a short string (validated/truncated to MAX_TAG_LENGTH elsewhere,
but also enforced here as a safety net).

Schema:
  tags(id, name UNIQUE, last_assigned_at, last_viewed_at)
      last_assigned_at drives the "recently assigned tags" list used by
      the assign-tag dialog; last_viewed_at drives the "recently viewed
      tags" list used by the browse-by-tag dialog.
  tag_assignments(id, tag_id, file_path, timestamp_sec, created_at)
      timestamp_sec is WHOLE_FILE_MARKER (-1) for a whole-file tag, or a
      non-negative integer second for a video-timestamp tag. Note: NULL
      can't be used for this because SQL UNIQUE constraints treat every
      NULL as distinct from every other NULL, which would silently defeat
      the "don't add the same tag twice" requirement for whole-file tags.
      The UNIQUE constraint on (tag_id, file_path, timestamp_sec) is what
      makes assigning the same tag twice a silent no-op instead of an
      error.
"""
import sqlite3
import time
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = APP_DIR / "tags.db"

MAX_TAG_LENGTH = 16
WHOLE_FILE_MARKER = -1


class TagsDatabase:
    def __init__(self, path=None):
        self.path = Path(path) if path else DEFAULT_DB_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                last_assigned_at REAL DEFAULT 0,
                last_viewed_at REAL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS tag_assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
                file_path TEXT NOT NULL,
                timestamp_sec INTEGER NOT NULL DEFAULT -1,
                created_at REAL DEFAULT 0,
                UNIQUE(tag_id, file_path, timestamp_sec)
            );
            CREATE INDEX IF NOT EXISTS idx_assignments_file ON tag_assignments(file_path);
            CREATE INDEX IF NOT EXISTS idx_assignments_tag ON tag_assignments(tag_id);
            """
        )
        self.conn.commit()

    # -- helpers ----------------------------------------------------------
    @staticmethod
    def normalize_tag(text):
        """Trim and truncate a tag to MAX_TAG_LENGTH. Spaces inside are
        preserved (only leading/trailing whitespace is stripped)."""
        return (text or "").strip()[:MAX_TAG_LENGTH]

    @staticmethod
    def _to_db_timestamp(timestamp_sec):
        return WHOLE_FILE_MARKER if timestamp_sec is None else int(timestamp_sec)

    @staticmethod
    def _from_db_timestamp(db_value):
        return None if db_value == WHOLE_FILE_MARKER else db_value

    def _find_tag_id(self, name):
        cur = self.conn.execute("SELECT id FROM tags WHERE name = ?", (name,))
        row = cur.fetchone()
        return row["id"] if row else None

    def _get_or_create_tag(self, name):
        tag_id = self._find_tag_id(name)
        if tag_id is not None:
            return tag_id
        cur = self.conn.execute("INSERT INTO tags(name) VALUES (?)", (name,))
        self.conn.commit()
        return cur.lastrowid

    # -- assignment ---------------------------------------------------------
    def assign_tag(self, name, file_path, timestamp_sec=None):
        """Assign `name` to `file_path` (whole file if timestamp_sec is
        None, otherwise that second of a video). Returns True if a new
        assignment was created, False if it already existed (silent, not
        an error) or the tag name was empty."""
        name = self.normalize_tag(name)
        if not name:
            return False
        tag_id = self._get_or_create_tag(name)
        now = time.time()
        db_ts = self._to_db_timestamp(timestamp_sec)
        try:
            self.conn.execute(
                "INSERT INTO tag_assignments(tag_id, file_path, timestamp_sec, created_at) "
                "VALUES (?, ?, ?, ?)",
                (tag_id, str(file_path), db_ts, now),
            )
        except sqlite3.IntegrityError:
            return False
        self.conn.execute("UPDATE tags SET last_assigned_at = ? WHERE id = ?", (now, tag_id))
        self.conn.commit()
        return True

    def remove_tag(self, name, file_path, timestamp_sec=None):
        name = self.normalize_tag(name)
        tag_id = self._find_tag_id(name)
        if tag_id is None:
            return
        db_ts = self._to_db_timestamp(timestamp_sec)
        self.conn.execute(
            "DELETE FROM tag_assignments WHERE tag_id = ? AND file_path = ? AND timestamp_sec = ?",
            (tag_id, str(file_path), db_ts),
        )
        self.conn.commit()

    # -- queries ----------------------------------------------------------
    def file_tags(self, file_path):
        """Return [(tag_name, timestamp_sec_or_None), ...] for a file,
        oldest assignment first."""
        cur = self.conn.execute(
            """
            SELECT t.name AS name, a.timestamp_sec AS ts
            FROM tag_assignments a JOIN tags t ON t.id = a.tag_id
            WHERE a.file_path = ?
            ORDER BY a.created_at ASC
            """,
            (str(file_path),),
        )
        return [(r["name"], self._from_db_timestamp(r["ts"])) for r in cur.fetchall()]

    def file_has_tag(self, name, file_path):
        """True if `file_path` has `name` assigned at the whole-file level
        (used for the 'v' checkmark in the assign-tag dialog)."""
        name = self.normalize_tag(name)
        tag_id = self._find_tag_id(name)
        if tag_id is None:
            return False
        cur = self.conn.execute(
            "SELECT 1 FROM tag_assignments WHERE tag_id = ? AND file_path = ? AND timestamp_sec = ?",
            (tag_id, str(file_path), WHOLE_FILE_MARKER),
        )
        return cur.fetchone() is not None

    def recent_assigned_tags(self, limit=20):
        cur = self.conn.execute(
            "SELECT name FROM tags WHERE last_assigned_at > 0 ORDER BY last_assigned_at DESC LIMIT ?",
            (limit,),
        )
        return [r["name"] for r in cur.fetchall()]

    def recent_viewed_tags(self, limit=20):
        cur = self.conn.execute(
            "SELECT name FROM tags WHERE last_viewed_at > 0 ORDER BY last_viewed_at DESC LIMIT ?",
            (limit,),
        )
        return [r["name"] for r in cur.fetchall()]

    def mark_tag_viewed(self, name):
        name = self.normalize_tag(name)
        if not name:
            return
        tag_id = self._get_or_create_tag(name)
        self.conn.execute("UPDATE tags SET last_viewed_at = ? WHERE id = ?", (time.time(), tag_id))
        self.conn.commit()

    def instances_for_tag(self, name):
        """Return [(file_path, timestamp_sec_or_None), ...] for every
        instance of a tag (one row per whole-file or per-timestamp
        assignment), ordered by file path then timestamp so that a
        file-level tag on a video is visited right before its own
        timestamp tags."""
        tag_id = self._find_tag_id(self.normalize_tag(name))
        if tag_id is None:
            return []
        cur = self.conn.execute(
            """
            SELECT file_path, timestamp_sec FROM tag_assignments
            WHERE tag_id = ?
            ORDER BY file_path ASC, timestamp_sec ASC
            """,
            (tag_id,),
        )
        return [(r["file_path"], self._from_db_timestamp(r["timestamp_sec"])) for r in cur.fetchall()]

    def instance_count_for_tag(self, name):
        return len(self.instances_for_tag(name))

    def file_timestamps(self, file_path):
        """Return the sorted list of distinct timestamp seconds carrying
        ANY tag (regardless of tag name) on this file - used for the
        "next/previous timestamp" video navigation feature, which jumps
        between every timestamp tag in the current file rather than
        instances of one specific tag."""
        cur = self.conn.execute(
            """
            SELECT DISTINCT timestamp_sec FROM tag_assignments
            WHERE file_path = ? AND timestamp_sec != ?
            ORDER BY timestamp_sec ASC
            """,
            (str(file_path), WHOLE_FILE_MARKER),
        )
        return [r["timestamp_sec"] for r in cur.fetchall()]

    def all_tags(self):
        """Return every known tag name, sorted alphabetically (case
        insensitive) - used for the Open/Browse dialog's tag list."""
        cur = self.conn.execute("SELECT name FROM tags ORDER BY name COLLATE NOCASE ASC")
        return [r["name"] for r in cur.fetchall()]

    def files_for_tag(self, name):
        """Return the sorted list of DISTINCT file paths carrying `name`
        anywhere (whole-file or any timestamp) - each file listed once,
        regardless of how many timestamp tags it has. Used by the
        Open/Browse dialog's "tag only" / "folder + tag" filtering."""
        tag_id = self._find_tag_id(self.normalize_tag(name))
        if tag_id is None:
            return []
        cur = self.conn.execute(
            "SELECT DISTINCT file_path FROM tag_assignments WHERE tag_id = ? ORDER BY file_path ASC",
            (tag_id,),
        )
        return [r["file_path"] for r in cur.fetchall()]

    def retarget_file(self, old_path, new_path):
        """Repoint every tag assignment for `old_path` to `new_path` -
        called after a tagged file is moved, so its tags follow it
        instead of becoming orphaned. If `new_path` already happens to
        carry the exact same tag (whole-file or same-second timestamp),
        that specific old row is dropped instead of duplicated."""
        old_path, new_path = str(old_path), str(new_path)
        if old_path == new_path:
            return
        self.conn.execute(
            "UPDATE OR IGNORE tag_assignments SET file_path = ? WHERE file_path = ?",
            (new_path, old_path),
        )
        # Any rows that couldn't move because of a conflict (new_path
        # already had that exact tag) are now redundant leftovers still
        # pointing at old_path - remove them.
        self.conn.execute("DELETE FROM tag_assignments WHERE file_path = ?", (old_path,))
        self.conn.commit()

    def remove_file(self, file_path):
        """Delete every tag assignment (whole-file and every timestamp)
        for `file_path` - used when a tagged file no longer exists on
        disk, so the stale database entries don't keep coming up."""
        self.conn.execute("DELETE FROM tag_assignments WHERE file_path = ?", (str(file_path),))
        self.conn.commit()

    def close(self):
        self.conn.close()
