"""Shared ordering for cooperating Library control and ChunkWriter threads."""

from __future__ import annotations

import sqlite3
import threading
import weakref
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from time import monotonic as _read_clock
from time import sleep as _read_wait
from typing import TypeVar

from recoryn.domain import StateConflict, ValidationError

from ._safe import check_path, safe_path

_guard = threading.Lock()
_roots: dict[Path, threading.RLock] = {}
# The open Library of this process answers "does this session have a deletion
# intent?" from its journal index (Library._writer_intent). Held weakly.
_intent_checks: dict[Path, weakref.WeakMethod[Callable[[str], bool | None]]] = {}
_intent_generations: dict[Path, weakref.WeakMethod[Callable[[], int | None]]] = {}
_T = TypeVar("_T")


def root_mutex(root: Path) -> threading.RLock:
    with _guard:
        return _roots.setdefault(root, threading.RLock())


def register_intent_check(
    root: Path,
    check: Callable[[str], bool | None],
    generation: Callable[[], int | None] | None = None,
) -> None:
    with _guard:
        _intent_checks[root] = weakref.WeakMethod(check)
        if generation is not None:
            _intent_generations[root] = weakref.WeakMethod(generation)
        else:
            _intent_generations.pop(root, None)


def unregister_intent_check(root: Path, check: Callable[[str], bool | None]) -> None:
    with _guard:
        reference = _intent_checks.get(root)
        if reference is not None and reference() == check:
            del _intent_checks[root]
            _intent_generations.pop(root, None)


def write_generation(root: Path) -> tuple[object, int] | None:
    """Root held: identify the open Library and its in-process intent generation.

    This is only a continuation fence for the same append after its full check.
    Missing/closed/replaced owners fall back to a full durable authority check.
    """
    with _guard:
        reference = _intent_generations.get(root)
    generation = reference() if reference is not None else None
    value = generation() if generation is not None else None
    return (reference, value) if type(value) is int else None


def retry_sealed_read(operation: Callable[[], _T]) -> _T:
    """Retry only transient access/sharing errors of our just-written bundle.

    Callers hold no root/registry/capture lock. Integrity errors and other I/O
    errors propagate immediately; expiry preserves the original access exception.
    """
    deadline = _read_clock() + 1.0
    while True:
        try:
            return operation()
        except OSError as error:
            if not isinstance(error, PermissionError) and getattr(error, "winerror", None) not in (
                32,
                33,
            ):
                raise
            remaining = deadline - _read_clock()
            if remaining <= 0:
                raise
        _read_wait(min(0.01, remaining))


def check_write_allowed(root: Path, session_id: str) -> None:
    """Caller holds root_mutex through each ensuing logical write/handoff.

    PER_BLOCK callers fence each write: full admission, then same-process generation
    checks across fsync (or another full check when that generation is unavailable).
    Their unbuffered-file fsyncs and same-writer operation waits run outside root;
    a pre-sync check cannot authorize a later write after a deletion intent.

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
            with closing(
                sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=0)
            ) as connection:
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
