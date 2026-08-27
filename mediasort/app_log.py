"""Application error log.

Errors from maintenance operations (database compact / export / import)
are appended - together with their full stack trace - to ``log.txt`` in
the application folder.  The log is append-only: existing content is kept
and new entries are added at the end, so consecutive runs never overwrite
earlier traces.
"""
import traceback
from datetime import datetime
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
LOG_PATH = APP_DIR / "log.txt"


def log_exception(operation, exc):
    """Append a timestamped entry with the full stack trace of `exc` to
    ``log.txt`` (created on first use).  Logging failures are swallowed -
    writing the log must never break the calling code."""
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"\n[{datetime.now().isoformat(timespec='seconds')}] {operation}\n")
            f.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
            f.write("\n")
    except OSError:
        pass
