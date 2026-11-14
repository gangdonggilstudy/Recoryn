"""Shared ordering for cooperating Library control and ChunkWriter threads."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import closing
from pathlib import Path

from recoryn.domain import StateConflict, ValidationError

from ._safe import check_path, safe_path

_guard = threading.Lock()
_roots: dict[Path, threading.RLock] = {}


def root_mutex(root: Path) -> threading.RLock:
    with _guard:
        return _roots.setdefault(root, threading.RLock())


def check_write_allowed(root: Path, session_id: str) -> None:
    """Caller holds root_mutex through the ensuing write/handoff.

    Terminal tombstones make session IDs non-reusable. Check the durable intent
    before touching media and the SQLite deletion generation even if its journal
    was lost. The Library OS lock still owns interprocess writer exclusion.
    """
    journal = safe_path(root, "deletion-journal")
    if journal.exists():
        check_path(journal)
        if any(path.name.startswith(".tmp-") for path in journal.iterdir()):
            raise ValidationError("Incomplete deletion intent")
        intent = safe_path(root, f"deletion-journal/{session_id}.json")
        if intent.exists():
            raise StateConflict("Writer session has a deletion intent")
    database = safe_path(root, "library.sqlite")
    if database.exists():
        try:
            with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
                if connection.execute("PRAGMA user_version").fetchone()[0] != 1:
                    raise ValidationError("Unsupported library schema")
                exists = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='deleted_sessions'"
                ).fetchone()
                if (
                    exists
                    and connection.execute(
                        "SELECT generation FROM deleted_sessions WHERE session_id=?", (session_id,)
                    ).fetchone()
                ):
                    raise StateConflict("Writer deletion generation has been revoked")
        except sqlite3.Error as exc:
            raise ValidationError("Cannot verify writer deletion generation") from exc
