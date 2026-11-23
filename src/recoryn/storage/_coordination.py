"""Shared ordering for cooperating Library control and ChunkWriter threads."""

from __future__ import annotations

import sqlite3
import threading
import weakref
from collections.abc import Callable
from contextlib import closing
from pathlib import Path

from recoryn.domain import StateConflict, ValidationError

from ._safe import check_path, safe_path

_guard = threading.Lock()
_roots: dict[Path, threading.RLock] = {}
# The open Library of this process answers "does this session have a deletion
# intent?" from its journal index (Library._writer_intent). Held weakly.
_intent_checks: dict[Path, weakref.WeakMethod[Callable[[str], bool | None]]] = {}


def root_mutex(root: Path) -> threading.RLock:
    with _guard:
        return _roots.setdefault(root, threading.RLock())


def register_intent_check(root: Path, check: Callable[[str], bool | None]) -> None:
    with _guard:
        _intent_checks[root] = weakref.WeakMethod(check)


def unregister_intent_check(root: Path, check: Callable[[str], bool | None]) -> None:
    with _guard:
        reference = _intent_checks.get(root)
        if reference is not None and reference() == check:
            del _intent_checks[root]


def check_write_allowed(root: Path, session_id: str) -> None:
    """Caller holds root_mutex through the ensuing write/handoff.

    Terminal tombstones make session IDs non-reusable. With an open Library in this
    process, its index answers in O(1): the Library publishes every deletion intent
    and updates that index inside one root_mutex section, so a write that passes
    here under the same mutex happens before the intent (I1). Without one, check the
    durable intent before touching media and the SQLite deletion generation even if
    its journal was lost. The Library OS lock still owns interprocess exclusion.
    An unverifiable answer raises ValidationError either way (the write is refused).
    """
    with _guard:
        reference = _intent_checks.get(root)
    check = reference() if reference is not None else None
    # None: the Library closed after the lookup; fall through to the durable check.
    verdict = check(session_id) if check is not None else None
    if verdict is not None:
        if verdict:
            raise StateConflict("Writer session has a deletion intent")
        return
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
