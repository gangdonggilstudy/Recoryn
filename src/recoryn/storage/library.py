"""SQLite-authoritative catalog, manifest projection and conservative recovery."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import threading
import time
import uuid
import weakref
from collections.abc import Callable, Iterator
from collections.abc import Set as AbstractSet
from contextlib import closing, contextmanager
from dataclasses import dataclass
from hashlib import sha256 as _history_digest
from pathlib import Path
from time import monotonic as _registration_clock
from time import sleep as _registration_wait
from types import TracebackType
from typing import Any, BinaryIO, Protocol

from recoryn.domain import (
    PCMBlock,
    Session,
    SessionState,
    StateConflict,
    ValidationError,
    transition_session,
)
from recoryn.domain.capture_health import (
    CaptureReceipt,
    GapFact,
    observed_interval,
    stable_id,
    track_loss,
    validate_snapshot,
)
from recoryn.domain.capture_health import (
    encoded as health_encoded,
)

from . import _safe as _safe_io
from ._coordination import (
    register_intent_check,
    retry_sealed_read,
    root_mutex,
    unregister_intent_check,
)
from ._safe import (
    atomic_json,
    canonical,
    check_path,
    identifier,
    integer,
    mkdir,
    open_file,
    read_json,
    remove_tree,
    root_path,
    safe_path,
    schema,
    sha256,
    strict_json,
)
from .chunks import (
    ChunkDescriptor,
    ChunkWriter,
    JournalPrefix,
    SealedChunk,
    has_active_writer,
    issued_descriptor,
    scan_prefix,
    verify_bundle,
)
from .deletion_history import (
    LIFETIME_NS,
    DeletionHistoryIndex,
    HistoryClockSample,
    HistoryEntry,
    read_format_one,
)


def _bounded_health_projection(value: dict[str, Any]) -> dict[str, Any]:
    """A byte-bounded compatibility view; canonical rows keep the full facts."""
    result: dict[str, Any] = json.loads(health_encoded(value))
    if len(canonical(result)) <= 60 * 1024:
        return result
    result["detail_complete"] = False
    for key in ("backend_events", "epochs"):
        entries = result.get(key, [])
        while entries and len(canonical(result)) > 60 * 1024:
            removed = max(1, len(entries) // 2)
            del entries[:removed]
            result[key + "_omitted"] = result.get(key + "_omitted", 0) + removed
    for track in result.get("tracks", {}).values():
        for key in ("events", "gaps", "loss_ranges"):
            entries = track.get(key, [])
            while entries and len(canonical(result)) > 60 * 1024:
                removed = max(1, len(entries) // 2)
                del entries[:removed]
                track[key + "_omitted"] = track.get(key + "_omitted", 0) + removed
                track["detail_complete"] = False
                if key == "gaps":
                    track["gap_detail_truncated"] = True
    if len(canonical(result)) > 60 * 1024:
        keep = {
            "health_schema_version",
            "health_version",
            "capture_run_id",
            "checkpoint_seq",
            "run_status",
            "has_unknown",
            "detail_complete",
            "tracks",
            "health_status",
            "health_error",
            "legacy_archive_run_id",
            "deferred_run_id",
        }
        result = {key: val for key, val in result.items() if key in keep}
        for track in result.get("tracks", {}).values():
            for key in ("events", "gaps", "loss_ranges"):
                track.pop(key, None)
            track["detail_complete"] = False
    # Even unusual legacy metadata cannot make a compatibility view unbounded.
    while len(canonical(result)) > 60 * 1024 and result.get("tracks"):
        result["tracks"].pop(next(iter(result["tracks"])))
        result["tracks_omitted"] = result.get("tracks_omitted", 0) + 1
    return result


_Listing = tuple[tuple[int, int, int], frozenset[str], bool, bool]
_UNFINISHED = frozenset(
    {
        SessionState.CREATED,
        SessionState.RECORDING,
        SessionState.PAUSED,
        SessionState.FINALIZING,
        SessionState.INTERRUPTED,
    }
)
_DELETION_STATUSES = frozenset({"DELETE_PENDING", "DELETED_LOCAL"})
_HISTORY_UNAVAILABLE = "DELETION_HISTORY_UNAVAILABLE"
# A directory mtime ticks coarsely (0.5-1 ms measured on NTFS here, 2 s on FAT), so
# two changes in one tick share a stamp. A listing settles the stamp only when it was
# observed longer than this after that mtime; every later change lands in a later tick.
_STAMP_SETTLE_NS = 2_500_000_000


@dataclass(frozen=True)
class _JournalObservation:
    version: int
    epoch: int
    stamp: tuple[int, int, int] | None
    started_ns: int
    journal: dict[str, int] | None
    names: frozenset[str]
    settled: bool
    content_failure: bool = False


class LiveOwner(Protocol):
    """An in-process owner, such as a recording service, that may still write a session."""

    def is_live(self) -> bool: ...


@dataclass(frozen=True)
class CaptureControlContext:
    """Issued to one registered capture controller after real source/worker ACKs.

    This is an in-process capability, not a caller's statement about global
    deletion history, and not an OS liveness proof for arbitrary processes.
    """

    root: Path
    instance: str
    session_id: str
    owner: weakref.ref[LiveOwner]
    registration: object
    run_id: str
    thread_id: int
    issuer: object


def _detail(
    kind: str,
    source: str | None,
    status: str,
    chunk_id: str | None = None,
    frames: int = 0,
    tail_bytes: int = 0,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "source": source,
        "status": status,
        "chunk_id": chunk_id,
        "frames": frames,
        "tail_bytes": tail_bytes,
    }


def _display_name(name: str) -> str | None:
    try:
        return identifier(name)
    except ValueError:
        return None


class Library:
    """One writer per library, with an internal lock for cooperating threads.

    Methods serialize SQLite transactions and filesystem projection. WAL/FULL,
    file fsync and atomic rename do not promise physical power-loss durability.
    """

    # Bind JobStore's database identity to its existing owner, never a second
    # Library connection/OS lock or a copied journal/coordination implementation.
    _job_authorities: weakref.WeakValueDictionary[Path, Library] = weakref.WeakValueDictionary()

    def __init__(
        self,
        root: Path,
        *,
        history_clock: Callable[[], HistoryClockSample] | None = None,
        defer_history: bool = False,
    ) -> None:
        self.root = root_path(root)
        self._mutex = root_mutex(self.root)
        self._lock_file: BinaryIO | None = None
        self._connection: sqlite3.Connection | None = None
        self._authority = DeletionHistoryIndex(
            self.root, clock=history_clock or HistoryClockSample.now
        )
        self._history_reader = threading.local()
        self._authority_leases = threading.local()
        self._capture_scopes = threading.local()
        self._capture_issuer = object()
        self._capture_owners: dict[int, tuple[object, weakref.ref[LiveOwner], str]] = {}
        self._authority_stamp: tuple[int, int, int] | None = None
        self._authority_seen_stamp: tuple[int, int, int] | None = None
        self._visibility_ready = False
        self._intent_publication_locks: dict[str, Any] = {}
        self._reserved_intents: dict[str, int] = {}
        # Exact process-local ownership, never a PID/name-only exemption. The
        # optional identity is filled only after this actor opens its file xb.
        self._staged_files: dict[Path, tuple[str, str, object, tuple[int, int] | None]] = {}
        self._staged_lifetimes: set[object] = set()
        self._stage_epoch = 0
        self._history_conflict: str | None = None
        self._live_owners: dict[str, dict[int, weakref.ref[LiveOwner]]] = {}
        self._session_locks: dict[str, Any] = {}
        self._claims: dict[str, int] = {}
        self._exclusive_claims: set[str] = set()
        # Bumped under root_mutex before this Library writes a deletion journal,
        # so a journal read outside the mutex can be validated cheaply.
        self._history_version = 0
        self._observation_epoch = 0
        self._published_observation = 0
        self._intent_failure: _JournalObservation | None = None
        # Validated journal (session -> generation) and the journal directory stamp
        # it was read at. Updated in the same root_mutex section that publishes an
        # intent; any other change to the directory forces a full re-validation.
        self._intent_journal: dict[str, int] | None = None
        self._intent_stamp: tuple[int, int, int] | None = None
        self._intent_names: set[str] | frozenset[str] = set()  # entry names the index implies
        self._intent_settled = False  # a settled listing at _intent_stamp matched them
        # Capture-path listing (stamp, names, unfinished, settled) while the index is
        # not current. It never opens an entry.
        self._journal_listing: _Listing | None = None
        # Session-wide observation debt survives run changes even if marker I/O fails.
        self._deferred_health_sessions: set[str] = set()
        mkdir(self.root)
        self.db_path = safe_path(self.root, "library.sqlite")
        for suffix in ("-wal", "-shm", "-journal"):
            safe_path(self.root, "library.sqlite" + suffix)
        try:
            self._acquire_lock()
            connection = sqlite3.connect(self.db_path, timeout=5, check_same_thread=False)
            self._connection = connection
            connection.row_factory = sqlite3.Row
            self._check_version()
            existing = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sessions'"
            ).fetchone()
            journal = safe_path(self.root, "deletion-journal")
            self._missing_deletion_history = bool(existing and not journal.exists())
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.executescript("""
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY, state TEXT NOT NULL, state_version INTEGER NOT NULL,
                    generation INTEGER NOT NULL DEFAULT 0,
                    manifest_sync_pending INTEGER NOT NULL DEFAULT 1,
                    finalized_chunks TEXT, capture_health TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS chunks (
                    chunk_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                    relative_path TEXT UNIQUE NOT NULL, descriptor TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id)
                );
                CREATE TABLE IF NOT EXISTS storage_events (
                    event_id INTEGER PRIMARY KEY, session_id TEXT NOT NULL,
                    kind TEXT NOT NULL, state_version INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS deleted_sessions (
                    session_id TEXT PRIMARY KEY, generation INTEGER NOT NULL,
                    status TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS storage_visible_sessions (
                    session_id TEXT PRIMARY KEY,
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS storage_pending_deletions (
                    session_id TEXT PRIMARY KEY
                );
                CREATE TABLE IF NOT EXISTS storage_catalog_meta (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1), version INTEGER NOT NULL
                );
                INSERT OR IGNORE INTO storage_catalog_meta VALUES(1,0);
                CREATE TRIGGER IF NOT EXISTS storage_catalog_insert AFTER INSERT ON sessions
                BEGIN
                    UPDATE storage_catalog_meta SET version=version+1 WHERE singleton=1;
                END;
                CREATE TRIGGER IF NOT EXISTS storage_catalog_change
                AFTER UPDATE OF state,state_version,generation ON sessions
                WHEN OLD.state!=NEW.state OR OLD.state_version!=NEW.state_version OR OLD.generation!=NEW.generation
                BEGIN
                    UPDATE storage_catalog_meta SET version=version+1 WHERE singleton=1;
                END;
                CREATE TRIGGER IF NOT EXISTS storage_catalog_delete AFTER DELETE ON sessions
                BEGIN
                    UPDATE storage_catalog_meta SET version=version+1 WHERE singleton=1;
                END;
                CREATE TRIGGER IF NOT EXISTS storage_visible_insert AFTER INSERT ON sessions
                WHEN NOT EXISTS(SELECT 1 FROM deleted_sessions WHERE session_id=NEW.session_id)
                BEGIN
                    INSERT OR IGNORE INTO storage_visible_sessions VALUES(NEW.session_id);
                END;
                CREATE TRIGGER IF NOT EXISTS storage_visible_delete AFTER INSERT ON deleted_sessions
                BEGIN
                    DELETE FROM storage_visible_sessions WHERE session_id=NEW.session_id;
                    INSERT OR IGNORE INTO storage_pending_deletions VALUES(NEW.session_id);
                END;
                CREATE TABLE IF NOT EXISTS capture_health_runs (
                    session_id TEXT NOT NULL, capture_run_id TEXT NOT NULL,
                    schema_version INTEGER NOT NULL, health_version INTEGER NOT NULL,
                    checkpoint_seq INTEGER NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY(session_id,capture_run_id),
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS capture_health_tracks (
                    session_id TEXT NOT NULL, capture_run_id TEXT NOT NULL,
                    track_id TEXT NOT NULL, epoch_id TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY(session_id,capture_run_id,track_id,epoch_id),
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE,
                    FOREIGN KEY(session_id,capture_run_id) REFERENCES capture_health_runs(session_id,capture_run_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS capture_health_events (
                    session_id TEXT NOT NULL, event_id TEXT NOT NULL,
                    capture_run_id TEXT NOT NULL, ordinal INTEGER NOT NULL, payload TEXT NOT NULL,
                    gap_id TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL DEFAULT '', digest TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(session_id,event_id),
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE,
                    FOREIGN KEY(session_id,capture_run_id) REFERENCES capture_health_runs(session_id,capture_run_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS capture_health_event_order ON capture_health_events(session_id,capture_run_id,ordinal,event_id);
                CREATE UNIQUE INDEX IF NOT EXISTS capture_health_gap_phase ON capture_health_events(session_id,gap_id,kind);
                PRAGMA user_version=1;
                COMMIT;
            """)
            if not self._missing_deletion_history:
                mkdir(journal)
        except BaseException:
            self.close()
            raise
        try:
            if not defer_history:
                self.verify_deletion_history(fresh=True)
        except BaseException:
            self.close()
            raise
        register_intent_check(self.root, self._append_check, self._append_generation)
        with self._mutex:
            self._job_authorities[self.db_path] = self

    @property
    def deletion_history_instance(self) -> str:
        return self._authority.instance

    def deletion_history_status(self) -> dict[str, str]:
        with self._mutex:
            ready = self._connection is not None and self._authority.valid()
        return {
            "status": "READY" if ready else "UNAVAILABLE",
            "code": "" if ready else _HISTORY_UNAVAILABLE,
        }

    def invalidate_deletion_history(self) -> None:
        with self._mutex:
            self._authority.invalidate()

    def verify_deletion_history(
        self, *, fresh: bool = False, can_publish: Callable[[], bool] | None = None
    ) -> dict[str, str]:
        """Full, read-only audit on the worker/control lane; no shared DB I/O off root.

        The dedicated read connection has its own snapshot and is always closed.
        Publication is O(1), and retired maps are released after leaving root.
        Capture's directory-name fence is separate from permission for management.
        can_publish is a pure observation gate: no locks, I/O or waiting under root.
        """
        if getattr(self._mutex, "_is_owned", lambda: False)():
            raise StateConflict(_HISTORY_UNAVAILABLE)
        try:
            with self._mutex:
                if self._connection is None:
                    return {"status": "UNAVAILABLE", "code": _HISTORY_UNAVAILABLE}
                if can_publish is not None and can_publish() is not True:
                    return {"status": "UNAVAILABLE", "code": _HISTORY_UNAVAILABLE}
                if self._authority.needs_fresh and not fresh:
                    return {"status": "UNAVAILABLE", "code": _HISTORY_UNAVAILABLE}
                self._observe_history_stamp(self._journal_stamp())
                scan = self._authority.begin_scan(fresh=fresh)
                version = self._history_version
        except (ValueError, OSError, OverflowError):
            with self._mutex:
                self._authority.invalidate()
            return {"status": "UNAVAILABLE", "code": _HISTORY_UNAVAILABLE}
        stamp = None
        names: frozenset[str] = frozenset()
        started = time.time_ns()
        retired: tuple[object, ...] = ()
        capture_retired: tuple[object, ...] = ()
        unfinished = False
        try:
            if self._missing_deletion_history:
                raise ValidationError(_HISTORY_UNAVAILABLE)
            self._inspect_staged_intents()
            stamp = self._journal_stamp()
            started = time.time_ns()  # G15R-05: before any listing or body read
            names, _ = self._list_journal(stamp)
            unfinished = any(name.startswith(".tmp-") for name in names)
            mutable_names = set(names)
            self._history_reader.value = None
            generations = self._read_journal()
            parsed = self._history_reader.value
            if parsed is None or names != parsed.names:
                raise OSError("Deletion history observation changed")
            records = dict(parsed.records)
            database = safe_path(self.root, "library.sqlite")
            uri = database.as_uri() + "?mode=ro"
            with closing(sqlite3.connect(uri, uri=True, timeout=0)) as connection:
                connection.execute("BEGIN")
                if connection.execute("PRAGMA user_version").fetchone()[0] != 1:
                    raise ValidationError(_HISTORY_UNAVAILABLE)
                for sid, generation, status in connection.execute(
                    "SELECT session_id,generation,status FROM deleted_sessions"
                ):
                    identifier(sid)
                    integer(generation, minimum=1)
                    entry = HistoryEntry(db_generation=generation, db_status=status)
                    previous = records.get(sid)
                    records[sid] = (
                        HistoryEntry(
                            previous.journal_generation,
                            previous.journal_digest,
                            generation,
                            status,
                        )
                        if previous is not None
                        else entry
                    )
                session_rows = list(
                    connection.execute("SELECT session_id,generation FROM sessions")
                )
                for sid, generation in session_rows:
                    identifier(sid)
                    integer(generation)
                    if sid in records and generation > records[sid].generation:
                        with self._mutex:
                            if self._authority.current_scan(scan):
                                self._history_conflict = sid
                        raise ValidationError(_HISTORY_UNAVAILABLE)
                visible_ids = (
                    [
                        row[0]
                        for row in connection.execute(
                            "SELECT session_id FROM storage_visible_sessions"
                        )
                    ]
                    if not self._visibility_ready
                    else []
                )
                previous_pending = [
                    row[0]
                    for row in connection.execute(
                        "SELECT session_id FROM storage_pending_deletions"
                    )
                ]
                connection.rollback()
            with self._mutex:
                cut = self._authority.cut()
            prepared = self._authority.prepare(scan, records, cut)
            sessions_directory = safe_path(self.root, "sessions")
            media_names = (
                {entry.name for entry in sessions_directory.iterdir()}
                if sessions_directory.is_dir()
                else set()
            )
            catalog_ids = {sid for sid, _ in session_rows}
            pending_ids = {
                sid
                for sid, entry in prepared.base.items()
                if not (
                    entry.db_status == "DELETED_LOCAL"
                    and entry.db_generation == entry.journal_generation
                    and sid not in catalog_ids
                    and sid not in media_names
                    and not self._media_present(sid)
                )
            }
            pending_changes = sorted(pending_ids ^ set(previous_pending))
            for start in range(0, len(pending_changes), 128):
                with self._mutex:
                    if not self._authority.current_scan(scan):
                        raise OSError("Deletion history observation changed")
                    connection = self._db
                    connection.execute("PRAGMA busy_timeout=0")
                    try:
                        with self._transaction():
                            for sid in pending_changes[start : start + 128]:
                                if self._authority.known(sid) not in {None, prepared.base.get(sid)}:
                                    continue  # a newer trusted actor owns this exact key
                                if sid in pending_ids:
                                    connection.execute(
                                        "INSERT OR IGNORE INTO storage_pending_deletions VALUES(?)",
                                        (sid,),
                                    )
                                else:
                                    connection.execute(
                                        "DELETE FROM storage_pending_deletions WHERE session_id=?",
                                        (sid,),
                                    )
                    finally:
                        connection.execute("PRAGMA busy_timeout=5000")
            if not self._visibility_ready:
                # Rebuildable projection only. Never adopt it as deletion authority.
                # Prepare O(S+H) outside root and commit at most 128 exact keys at once.
                wanted_visible = {sid for sid, _ in session_rows if sid not in prepared.base}
                identities = sorted(wanted_visible ^ set(visible_ids))
                for start in range(0, len(identities), 128):
                    with self._mutex:
                        if not self._authority.current_scan(scan):
                            raise OSError("Deletion history observation changed")
                        connection = self._db
                        connection.execute("PRAGMA busy_timeout=0")
                        try:
                            with self._transaction():
                                for sid in identities[start : start + 128]:
                                    hidden = (
                                        sid in prepared.base
                                        or self._authority.known(sid) is not None
                                    )
                                    connection.execute(
                                        "DELETE FROM storage_visible_sessions WHERE session_id=?",
                                        (sid,),
                                    )
                                    if not hidden:
                                        connection.execute(
                                            "INSERT OR IGNORE INTO storage_visible_sessions "
                                            "SELECT session_id FROM sessions WHERE session_id=? "
                                            "AND NOT EXISTS(SELECT 1 FROM deleted_sessions WHERE session_id=?)",
                                            (sid, sid),
                                        )
                        finally:
                            connection.execute("PRAGMA busy_timeout=5000")
            stage_stamp, stage_epoch = self._inspect_staged_intents()
            with self._mutex:
                if can_publish is not None and can_publish() is not True:
                    return {"status": "UNAVAILABLE", "code": _HISTORY_UNAVAILABLE}
                if stage_epoch != self._stage_epoch or stage_stamp != self._stage_root_stamp():
                    raise OSError("Deletion staging observation changed")
                current_stamp = self._journal_stamp()
                if stamp != current_stamp and version == self._history_version:
                    raise OSError("Deletion history observation changed")
                # Only a stable cut may prime the old capture-name index. No H-copy
                # or name enumeration happens here; all containers were built above.
                if (
                    self._authority.current_scan(scan)
                    and version == self._history_version
                    and stamp == current_stamp
                ):
                    capture_retired += (
                        self._intent_journal,
                        self._intent_names,
                        self._intent_failure,
                    )
                    self._observation_epoch += 1
                    self._published_observation = self._observation_epoch
                    self._intent_failure = None
                    self._intent_journal = generations
                    self._intent_names = mutable_names
                    self._intent_stamp = stamp
                    self._intent_settled = started - stamp[2] > _STAMP_SETTLE_NS
                retired = self._authority.publish(prepared)
                if self._authority.published == scan.observation:
                    self._visibility_ready = True
                    self._history_conflict = None
                if (
                    self._authority.receipt is not None
                    and self._authority.receipt.observation == scan.observation
                    and version == self._history_version
                ):
                    self._authority_stamp = current_stamp
                ready = self._connection is not None and self._authority.valid()
            return {
                "status": "READY" if ready else "UNAVAILABLE",
                "code": "" if ready else _HISTORY_UNAVAILABLE,
            }
        except (ValueError, OSError, sqlite3.Error, MemoryError) as error:
            retryable_sql = isinstance(error, sqlite3.Error) and (
                getattr(error, "sqlite_errorcode", -1) & 0xFF
            ) in {
                sqlite3.SQLITE_BUSY,
                sqlite3.SQLITE_LOCKED,
                sqlite3.SQLITE_IOERR,
                sqlite3.SQLITE_CANTOPEN,
                sqlite3.SQLITE_INTERRUPT,
            }
            with self._mutex:
                self._authority.failed(
                    scan, io_error=isinstance(error, (OSError, MemoryError)) or retryable_sql
                )
                try:
                    stable = (
                        stamp is not None
                        and stamp == self._journal_stamp()
                        and version == self._history_version
                    )
                except (ValueError, OSError):
                    stable = False
                if stable:
                    assert stamp is not None
                    # A body failure is not permission to open other bodies on the
                    # capture path. Preserve the independently observed names only.
                    capture_retired += (self._journal_listing,)
                    self._journal_listing = (
                        stamp,
                        names,
                        unfinished,
                        started - stamp[2] > _STAMP_SETTLE_NS,
                    )
            return {"status": "UNAVAILABLE", "code": _HISTORY_UNAVAILABLE}
        finally:
            self._history_reader.value = None
            # Keep references out of the root section through this point.
            del retired
            del capture_retired

    @staticmethod
    @contextmanager
    def job_authority(db_path: Path, session_id: str) -> Iterator[str]:
        """Read-only authority lease for worker/control-lane Job transitions.

        VALID, DB_ONLY, JOURNAL_ONLY, BOTH, TOMBSTONE, MISSING or
        HISTORY_UNAVAILABLE. Call outside JobStore transactions/locks and outside
        the GUI lane. A current full-audit receipt and one session's exact facts
        are held through the caller's short transaction. Metadata hints are read
        outside root; no body, enumeration, full row scan or map copy is done.
        """
        identifier(session_id)
        owner = Library._job_authorities.get(db_path.absolute())
        if owner is None:
            yield "HISTORY_UNAVAILABLE"
            return
        for _ in range(3):
            with owner._mutex:
                version = owner._history_version
            try:
                stamp = owner._journal_stamp()
            except (ValueError, OSError):
                yield "HISTORY_UNAVAILABLE"
                return
            with owner._mutex:
                state = "HISTORY_UNAVAILABLE"
                try:
                    if owner._connection is None or owner._missing_deletion_history:
                        state = "HISTORY_UNAVAILABLE"
                    else:
                        owner._check_version()
                        if version != owner._history_version:
                            continue
                        owner._observe_history_stamp(stamp)
                        if stamp == owner._authority_stamp and owner._authority.valid():
                            state = owner._job_authority_state(session_id)
                except (ValueError, OSError, sqlite3.Error):
                    state = "HISTORY_UNAVAILABLE"
                previous = getattr(owner._authority_leases, "current", None)
                owner._authority_leases.current = (session_id, state)
                try:
                    yield state
                finally:
                    owner._authority_leases.current = previous
                return
        yield "HISTORY_UNAVAILABLE"  # concurrent intent changes never become absence

    @staticmethod
    def assert_job_authority_current(db_path: Path, session_id: str) -> None:
        """Pure expiry fence immediately before a protected Job commit.

        The active job_authority context already owns root. Never reacquire it
        behind a Job lock, or start an audit from a transaction.
        """
        owner = Library._job_authorities.get(db_path.absolute())
        if (
            owner is None
            or owner._connection is None
            or getattr(owner._authority_leases, "current", None) != (session_id, "VALID")
            or not owner._authority.valid()
        ):
            raise StateConflict(_HISTORY_UNAVAILABLE)

    def _job_authority_state(self, session_id: str) -> str:
        """Root mutex held through the caller's existing short Job transaction."""
        if session_id in self._reserved_intents:
            return "HISTORY_UNAVAILABLE"
        known = self._authority.known(session_id)
        published = known.journal_generation if known is not None else None
        row = self._db.execute(
            "SELECT generation,status FROM deleted_sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        session = self._db.execute(
            "SELECT generation FROM sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        if row is not None:
            integer(row[0], minimum=1)
            if row[1] not in _DELETION_STATUSES:
                raise ValidationError(_HISTORY_UNAVAILABLE)
        if session is not None:
            integer(session[0])
        generation = max(row[0] if row else 0, known.generation if known else 0)
        if session is not None and generation and session[0] > generation:
            raise ValidationError(_HISTORY_UNAVAILABLE)
        if (row is not None and row[1] == "DELETED_LOCAL") or (
            known is not None and known.db_status == "DELETED_LOCAL"
        ):
            return "TOMBSTONE"
        has_db = row is not None or known is not None and known.db_generation is not None
        if has_db and published is not None:
            return "BOTH"
        if has_db:
            return "DB_ONLY"
        if published is not None:
            return "JOURNAL_ONLY"
        return "VALID" if session is not None else "MISSING"

    def _acquire_lock(self) -> None:
        path = safe_path(self.root, ".writer.lock")
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags, 0o600)
        stream = os.fdopen(fd, "r+b", buffering=0)
        try:
            check_path(path)
            if os.fstat(fd).st_size == 0:
                stream.write(b"\0")
            stream.seek(0)
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            stream.close()
            raise StateConflict("Library already locked or lock unavailable") from None
        self._lock_file = stream

    @property
    def _db(self) -> sqlite3.Connection:
        if self._connection is None:
            raise ValueError("Library is closed")
        check_path(self.db_path)
        return self._connection

    def _check_version(self) -> None:
        version = self._db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1):
            raise ValidationError("Unsupported library schema")

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        self._check_version()
        connection = self._db
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise

    def _read_journal(self) -> dict[str, int]:
        """One validated journal level: session ID -> generation. Never repairs."""
        parsed = read_format_one(self.root, reader=read_json)
        self._history_reader.value = parsed
        return {sid: entry.generation for sid, entry in parsed.records.items()}

    def _journal_prefetch(self, *, fresh: bool = False) -> _JournalObservation:
        """Successful reads stay fresh; only content failures may be memoized."""
        with self._mutex:
            started = time.time_ns()
            try:
                failed = self._intent_failure if not fresh else None
                if failed is not None and failed.settled and self._failure_current():
                    return failed
            except (ValueError, OSError):
                failed = None
        if failed is not None and not failed.settled and failed.stamp is not None:
            try:
                # Job preflight is outside root: do not borrow _live's names-only
                # mutex exception. Recheck the candidate identity after listing.
                listed, _ = self._list_journal(failed.stamp)
                with self._mutex:
                    if failed is self._intent_failure and self._failure_current(names=listed):
                        return failed
            except (ValueError, OSError):
                pass
        with self._mutex:
            self._observation_epoch += 1
            epoch, version = self._observation_epoch, self._history_version
        stamp = None
        journal = None
        names: frozenset[str] = frozenset()
        content_failure = False
        try:
            stamp = self._journal_stamp()
            started = time.time_ns()  # before any entry enumeration or body I/O
            names, _ = self._list_journal(stamp)
            try:
                journal = self._read_journal()
            except ValueError:
                content_failure = True
            listed, _ = self._list_journal(stamp)
            if listed != names or (
                journal is not None and listed != frozenset(f"{sid}.json" for sid in journal)
            ):
                journal, names, content_failure = None, frozenset(), False
        except (ValueError, OSError):
            # An unavailable listing/read proves nothing about persistent content.
            journal, names, content_failure = None, frozenset(), False
        return _JournalObservation(
            version,
            epoch,
            stamp,
            started,
            journal,
            names,
            stamp is not None and started - stamp[2] > _STAMP_SETTLE_NS,
            content_failure,
        )

    def _failure_current(self, *, names: frozenset[str] | None = None) -> bool:
        """Root held: reuse content failures, never a transient filesystem refusal."""
        failed = self._intent_failure
        if not (
            failed is not None
            and failed.content_failure
            and failed.version == self._history_version
            and failed.epoch == self._published_observation
            and failed.stamp is not None
            and failed.stamp == self._journal_stamp()
            and time.time_ns() >= failed.started_ns >= failed.stamp[2]
        ):
            return False
        if failed.settled:
            return True
        # Before settling, names must still match, including changes in one tick.
        if names is None:
            names, _ = self._list_journal(failed.stamp)
        return names == failed.names

    def _newer_observation_current(self, observed: _JournalObservation) -> bool:
        """Root held: another completed read of this same snapshot won publication."""
        return bool(
            self._connection is not None
            and not self._missing_deletion_history
            and observed.version == self._history_version
            and observed.epoch < self._published_observation <= self._observation_epoch
            and observed.stamp is not None
            and observed.stamp == self._intent_stamp == self._journal_stamp()
        )

    def _accept_observation(self, observed: _JournalObservation) -> bool:
        """Publish only the latest-started observation of the same authority snapshot."""
        if (
            self._connection is None
            or self._missing_deletion_history
            or observed.version != self._history_version
            or observed.epoch < self._published_observation
            or observed.epoch > self._observation_epoch
            or observed.stamp is None
            or observed.stamp != self._journal_stamp()
        ):
            return False
        self._published_observation = observed.epoch
        self._intent_failure = observed if observed.content_failure else None
        self._intent_journal = observed.journal
        self._intent_stamp = observed.stamp
        self._intent_names = observed.names
        self._intent_settled = observed.settled and observed.journal is not None
        return True

    def _journal_stamp(self) -> tuple[int, int, int]:
        status = os.stat(safe_path(self.root, "deletion-journal"))
        return (status.st_dev, status.st_ino, status.st_mtime_ns)

    def _list_journal(self, stamp: tuple[int, int, int]) -> tuple[frozenset[str], bool]:
        """Names only. Off-root callers must recheck stamp/version before using them."""
        observed = time.time_ns()
        journal = safe_path(self.root, "deletion-journal")
        check_path(journal)
        with os.scandir(journal) as entries:
            names = frozenset(entry.name for entry in entries)
        settled = observed - stamp[2] > _STAMP_SETTLE_NS and self._journal_stamp() == stamp
        return names, settled

    def _set_index(self, journal: dict[str, int], stamp: tuple[int, int, int]) -> None:
        self._observation_epoch += 1
        self._published_observation = self._observation_epoch
        self._intent_failure = None
        self._intent_journal, self._intent_stamp = journal, stamp
        self._intent_names = frozenset(f"{sid}.json" for sid in journal)
        self._intent_settled = False

    def _index_current(self) -> bool:
        """Root mutex held: the validated index still describes the journal's entries.

        One stat once the stamp has settled; until then one listing of entry names, so
        a second change in the same mtime tick is still seen. In-place rewrites of an
        entry change neither; the management paths validate contents in full.
        """
        if self._intent_journal is None:
            return False
        stamp = self._journal_stamp()
        if stamp != self._intent_stamp:
            return False
        if self._intent_settled:
            return True
        names, settled = self._list_journal(stamp)
        if names != self._intent_names:
            return False
        self._intent_settled = settled
        return True

    def _refresh_intent_index(self) -> dict[str, int]:
        """Root mutex held: fully re-validate the journal (at open or after an outside change)."""
        self._intent_journal = None
        if self._missing_deletion_history:
            raise ValidationError(_HISTORY_UNAVAILABLE)
        observed = self._journal_prefetch(fresh=True)
        if not self._accept_observation(observed) or observed.journal is None:
            raise ValidationError(_HISTORY_UNAVAILABLE)
        return observed.journal

    def _indexed_journal(self) -> dict[str, int]:
        """Root mutex held: the validated journal, re-read only when its entries changed.

        A new .tmp, an unknown entry or an added or removed intent changes the entry
        names, so it is always re-validated in full (fail closed).
        """
        try:
            if self._missing_deletion_history:
                raise ValidationError(_HISTORY_UNAVAILABLE)
            if self._failure_current():
                raise ValidationError(_HISTORY_UNAVAILABLE)
            if self._index_current() and self._intent_journal is not None:
                return self._intent_journal
            return self._refresh_intent_index()
        except (ValueError, OSError):
            self._intent_journal = None
            raise ValidationError(_HISTORY_UNAVAILABLE) from None

    def _db_intent(self, session_id: str) -> bool:
        """Root mutex held: this session's DB deletion record only, validated."""
        row = self._db.execute(
            "SELECT generation,status FROM deleted_sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        if row is None:
            return False
        integer(row[0], minimum=1)
        if row[1] not in _DELETION_STATUSES:
            raise ValidationError("Unsupported deletion status")
        return True

    def _writer_intent(self, session_id: str) -> bool:
        """Deletion intent of this one session for the capture path (G05R-04).

        Used by catalog registration of a sealed chunk and, through _coordination, by
        every append and seal. It looks only at entry names and this session's DB row
        and never opens a journal file, so an I/O error on another session's intent
        cannot stop a recording. If the answer for this session cannot be established,
        the write is refused with a ValidationError (I1).
        """
        identifier(session_id)
        with self._mutex:
            connection = self._db  # a closed Library reports itself
            try:
                if self._missing_deletion_history:
                    raise ValidationError(_HISTORY_UNAVAILABLE)
                self._check_version()
                if (
                    session_id in self._reserved_intents
                    or self._authority.known(session_id) is not None
                ):
                    return True
                names = self._writer_names()
                row = connection.execute(
                    "SELECT generation,status FROM deleted_sessions WHERE session_id=?",
                    (session_id,),
                ).fetchone()
                if row is not None:
                    integer(row[0], minimum=1)
                    if row[1] not in _DELETION_STATUSES:
                        raise ValidationError(_HISTORY_UNAVAILABLE)
            except ValidationError as exc:
                if exc.args == ("Incomplete deletion intent",):
                    raise
                raise ValidationError("Cannot verify writer deletion intent") from None
            except (ValueError, OSError, sqlite3.Error):
                raise ValidationError("Cannot verify writer deletion intent") from None
            return f"{session_id}.json" in names or row is not None

    def _writer_names(self) -> AbstractSet[str]:
        """Root mutex held: journal entry names for the capture path."""
        if self._index_current():
            return self._intent_names
        # Changed outside this Library's own writes: names only, cached once settled.
        stamp = self._journal_stamp()
        cached = self._journal_listing
        if cached is not None and cached[0] == stamp and cached[3]:
            _, names, unfinished, _ = cached
        else:
            names, settled = self._list_journal(stamp)
            unfinished = any(name.startswith(".tmp-") for name in names)
            self._journal_listing = (stamp, names, unfinished, settled)
        if unfinished:
            # An unfinished publication may be this session's intent (as before G15).
            raise ValidationError("Incomplete deletion intent")
        return names

    def _append_generation(self) -> int | None:
        """Root held: cheap continuation fence, never an initial write admission."""
        return self._history_version if self._connection is not None else None

    def _append_check(self, session_id: str) -> bool | None:
        """_coordination callback; None once closed, so the writer checks durably."""
        with self._mutex:
            if self._connection is None:
                return None
            return self._writer_intent(session_id)

    def _deletion_history(
        self, prefetched: _JournalObservation | None = None
    ) -> tuple[dict[str, tuple[int, str]], dict[str, int]]:
        """Root mutex held: validated DB rows and journal. Corruption is never absence.

        With a prefetch the journal is read and validated in full on every call (the
        management paths); without one the stamp-checked index is used.
        """
        connection = self._db
        try:
            if self._missing_deletion_history:
                raise ValidationError(_HISTORY_UNAVAILABLE)
            if prefetched is not None:
                if self._accept_observation(prefetched):
                    journal = prefetched.journal
                    if journal is None:
                        raise ValidationError(_HISTORY_UNAVAILABLE)
                elif self._newer_observation_current(prefetched):
                    # This call already read in full off-root; a newer validated
                    # observation won publication. Never re-read O(N) under root
                    # merely because another worker completed the same snapshot.
                    journal = self._intent_journal
                    if journal is None:
                        raise ValidationError(_HISTORY_UNAVAILABLE)
                else:
                    journal = self._refresh_intent_index()
            else:
                journal = self._indexed_journal()
            rows: dict[str, tuple[int, str]] = {}
            for sid, generation, status in connection.execute(
                "SELECT session_id,generation,status FROM deleted_sessions"
            ):
                identifier(sid)
                integer(generation, minimum=1)
                if status not in _DELETION_STATUSES:
                    raise ValidationError("Unsupported deletion status")
                rows[sid] = (generation, status)
        except (ValueError, OSError, sqlite3.Error):
            raise ValidationError(_HISTORY_UNAVAILABLE) from None
        return rows, journal

    def _deletion_intents(
        self, prefetched: _JournalObservation | None = None
    ) -> DeletionHistoryIndex:
        """Exact pinned membership, never a copied H-set or implicit full audit."""
        context = getattr(self._capture_scopes, "current", None)
        if context is not None:
            self._validate_capture_control(context.session_id, context)
        else:
            self._require_history()
        return self._authority

    def _live(self, session_id: str) -> None:
        """Root mutex held: refuse a session with a deletion intent, in O(1).

        Uses the stamp-checked journal index and this session's DB record only, so
        frequent calls (get_session, chunks, create_session) no longer read every
        journal file under the mutex. History that cannot be validated fails closed.
        """
        identifier(session_id)
        self._db  # noqa: B018 - a closed Library reports itself, not a history error
        try:
            intent = self._writer_intent(session_id)
        except (ValueError, OSError, sqlite3.Error):
            self._authority.invalidate()
            raise ValidationError(_HISTORY_UNAVAILABLE) from None
        if intent:
            raise StateConflict("Session has a deletion intent")

    def register_live_owner(self, session_id: str, owner: LiveOwner) -> None:
        """Remember all owners weakly by identity, including unhashable owners."""
        identifier(session_id)
        if not callable(getattr(owner, "is_live", None)):
            raise ValidationError("Live owner must provide is_live")
        with self._mutex:
            self._live_owners.setdefault(session_id, {})[id(owner)] = weakref.ref(owner)

    def register_capture_controller(self, session_id: str, owner: LiveOwner) -> object:
        """Control registration is distinct from merely observing a live owner."""
        identifier(session_id)
        if not callable(getattr(owner, "capture_control_state", None)):
            raise StateConflict("SESSION_LIVE")
        with self._mutex:
            self.get_session(session_id)
            self.register_live_owner(session_id, owner)
            registration = object()
            self._capture_owners[id(owner)] = (registration, weakref.ref(owner), session_id)
            return registration

    @staticmethod
    def _capture_ack_state(owner: LiveOwner) -> str:
        # Registered implementations must answer by observation only, without
        # taking a capture gate, waiting, doing I/O or calling a source.
        inspect = getattr(owner, "capture_control_state", None)
        state = inspect() if callable(inspect) else None
        if (
            type(state) is not tuple
            or len(state) != 4
            or type(state[0]) is not str
            or any(type(ack) is not bool or ack is not True for ack in state[1:])
        ):
            raise StateConflict("SESSION_LIVE")
        return state[0]

    def capture_control(
        self, session_id: str, owner: LiveOwner, registration: object
    ) -> CaptureControlContext:
        """Issue only for this controller, library instance, run and ACK state."""
        with self._mutex:
            known = self._capture_owners.get(id(owner))
            if (
                known is None
                or known[0] is not registration
                or known[1]() is not owner
                or known[2] != session_id
            ):
                raise StateConflict("SESSION_LIVE")
            self.get_session(session_id)
            run = self._capture_ack_state(owner)
            if self._is_live(session_id):
                raise StateConflict("SESSION_LIVE")
            return CaptureControlContext(
                self.root,
                self._authority.instance,
                session_id,
                weakref.ref(owner),
                registration,
                run,
                threading.get_ident(),
                self._capture_issuer,
            )

    def _validate_capture_control(self, session_id: str, context: CaptureControlContext) -> None:
        """Root held; revalidate every use, never infer permission from an owner."""
        if (
            type(context) is not CaptureControlContext
            or context.issuer is not self._capture_issuer
            or context.root != self.root
            or context.instance != self._authority.instance
            or context.session_id != session_id
            or context.thread_id != threading.get_ident()
            or self._connection is None
        ):
            raise StateConflict("SESSION_LIVE")
        owner = context.owner()
        known = self._capture_owners.get(id(owner))
        if (
            owner is None
            or known is None
            or known[0] is not context.registration
            or known[1]() is not owner
            or known[2] != session_id
            or self._live_owners.get(session_id, {}).get(id(owner), lambda: None)() is not owner
            or self._capture_ack_state(owner) != context.run_id
            or self._is_live(session_id)
        ):
            raise StateConflict("SESSION_LIVE")
        self._live(session_id)

    @contextmanager
    def _capture_scope(
        self, session_id: str, context: CaptureControlContext | None
    ) -> Iterator[None]:
        with self._mutex:
            if context is not None:
                self._validate_capture_control(session_id, context)
            previous = getattr(self._capture_scopes, "current", None)
            self._capture_scopes.current = context
        try:
            yield
        finally:
            self._capture_scopes.current = previous

    def _require_management_or_capture(self, session_id: str) -> bool:
        context = getattr(self._capture_scopes, "current", None)
        if context is not None:
            self._validate_capture_control(session_id, context)
            return True
        self._require_history()
        return False

    def _is_live(self, session_id: str) -> bool:
        # Called under the root mutex; owners must answer without taking their own locks.
        if has_active_writer(self.root, session_id):
            return True
        owners = self._live_owners.get(session_id, {})
        live = False
        for identity, reference in tuple(owners.items()):
            owner = reference()
            if owner is None:
                owners.pop(identity, None)
            elif owner.is_live():
                live = True
        if not owners:
            self._live_owners.pop(session_id, None)
        return live

    def create_session(self, session_id: str) -> Session:
        with self._mutex:
            self._check_claim(session_id)
            self._live(session_id)
            with self._transaction() as connection:
                try:
                    connection.execute(
                        "INSERT INTO sessions(session_id,state,state_version) VALUES(?,?,0)",
                        (session_id, SessionState.CREATED.value),
                    )
                except sqlite3.IntegrityError as exc:
                    raise StateConflict("Session already exists") from exc
                self._event(connection, session_id, "CREATED", 0)
            return self.get_session(session_id)

    def get_session(self, session_id: str) -> Session:
        with self._mutex:
            self._live(session_id)
            row = self._db.execute(
                "SELECT state,state_version FROM sessions WHERE session_id=?", (session_id,)
            ).fetchone()
            if row is None:
                raise KeyError(session_id)
            return Session(session_id, SessionState(row[0]), row[1])

    def check_local_catalog(self) -> None:
        """Construction/cleanup check, not permission for management or publication."""
        with self._mutex:
            self._check_version()

    def check_management_history(self) -> None:
        """Control-lane preflight, with no implicit deep scan or permission fallback."""
        try:
            with self._mutex:
                self._check_version()
                self._require_history()
        except (ValueError, OSError, sqlite3.Error):
            raise ValidationError(_HISTORY_UNAVAILABLE) from None

    def authority_view(self, session_id: str) -> dict[str, Any]:
        """Exact public observation; callers must acquire a lease for an actual Job."""
        with self.job_authority(self.db_path, session_id) as state:
            if self._connection is None or self._job_authorities.get(self.db_path) is not self:
                raise ValidationError(_HISTORY_UNAVAILABLE)
            entry = self._authority.known(session_id)
            return {
                "session_id": session_id,
                "authority": state,
                "generation": entry.generation if entry else None,
            }

    def _observe_history_stamp(self, stamp: tuple[int, int, int]) -> None:
        """Root held: one invalidation per observed change, never per denied peek.

        A caller observing no permission must not cancel an in-flight initial or
        repair audit. This hint creates no receipt and never extends its lifetime.
        """
        previous = self._authority_seen_stamp
        self._authority_seen_stamp = stamp
        if previous is not None and previous != stamp:
            self._authority.invalidate()

    def _require_history(self) -> None:
        """Root held: positive authority is short-lived; negative floors are not."""
        try:
            stamp = self._journal_stamp()
        except (ValueError, OSError):
            self._authority.invalidate()
            raise ValidationError(_HISTORY_UNAVAILABLE) from None
        self._observe_history_stamp(stamp)
        if (
            stamp != self._authority_stamp
            or not self._authority.valid()
            or not self._visibility_ready
        ):
            raise ValidationError(_HISTORY_UNAVAILABLE)

    def sessions_page(
        self,
        *,
        cursor: str | None = None,
        limit: int = 128,
        expected_catalog_version: int | None = None,
    ) -> dict[str, Any]:
        """Exact keyset page. No OFFSET, H-row filtering or journal I/O."""
        if type(limit) is not int or not 1 <= limit <= 128:
            raise ValidationError("Invalid session page limit")
        position = None
        if cursor is not None:
            if type(cursor) is not str:
                raise ValidationError("Invalid session page cursor")
            position = strict_json(cursor.encode("utf-8"), limit=1024)
            if set(position) != {"schema_version", "instance", "version", "after"}:
                raise ValidationError("Invalid session page cursor")
            schema(position)
            integer(position["version"])
            identifier(position["after"])
        if expected_catalog_version is not None:
            integer(expected_catalog_version)
        with self._mutex:
            self._check_version()
            self._require_history()
            row = self._db.execute(
                "SELECT version FROM storage_catalog_meta WHERE singleton=1"
            ).fetchone()
            if row is None:
                raise ValidationError(_HISTORY_UNAVAILABLE)
            version = integer(row[0]) + self._history_version
            if (
                (
                    position is not None
                    and (
                        position["instance"] != self._authority.instance
                        or position["version"] != version
                    )
                )
                or expected_catalog_version is not None
                and expected_catalog_version != version
            ):
                raise StateConflict("STALE_SESSION_VERSION")
            after = position["after"] if position else ""
            rows = self._db.execute(
                "SELECT s.session_id,s.state,s.state_version FROM storage_visible_sessions v "
                "JOIN sessions s ON s.session_id=v.session_id "
                "WHERE v.session_id>? ORDER BY v.session_id LIMIT ?",
                (after, limit),
            ).fetchall()
            result = [
                Session(row[0], SessionState(row[1]), row[2])
                for row in rows
                if self._authority.known(row[0]) is None
                and row[0] not in self._reserved_intents
                and not self._db_intent(row[0])
            ]
            self._require_history()
            following = (
                canonical(
                    {
                        "schema_version": 1,
                        "instance": self._authority.instance,
                        "version": version,
                        "after": rows[-1][0],
                    }
                ).decode("utf-8")
                if len(rows) == limit
                else None
            )
            return {"sessions": result, "next": following, "catalog_version": version}

    def list_sessions(self) -> list[Session]:
        """Compatibility O(S) list. History size H never enters this hot path."""
        result: list[Session] = []
        cursor = None
        while True:
            page = self.sessions_page(cursor=cursor)
            result.extend(page["sessions"])
            cursor = page["next"]
            if cursor is None:
                return result

    @staticmethod
    def _event(connection: sqlite3.Connection, session_id: str, kind: str, version: int) -> None:
        connection.execute(
            "INSERT INTO storage_events(session_id,kind,state_version) VALUES(?,?,?)",
            (session_id, kind, version),
        )

    def _check_claim(self, session_id: str) -> None:
        owner = self._claims.get(session_id)
        if (
            owner is not None
            and owner != threading.get_ident()
            and session_id in self._exclusive_claims
        ):
            raise StateConflict("SESSION_OPERATION_IN_PROGRESS")

    def _admit_session(
        self,
        session_id: str,
        operation: str,
        expected_version: int | None,
        prefetched: _JournalObservation | None = None,
    ) -> bool:
        """Root mutex held: decide every refusal before publishing any claim."""
        if expected_version is not None:
            integer(expected_version)
        self._require_management_or_capture(session_id)
        if self._writer_intent(session_id):
            if operation == "recover":
                return False  # Preserve recover's read-only DELETE_PENDING result.
            raise StateConflict("DELETE_PENDING")
        if self._is_live(session_id):
            if operation == "seal":
                raise StateConflict("Writer has not drained")
            if operation == "recover" and has_active_writer(self.root, session_id):
                raise StateConflict("Live writer cannot be recovered")
            raise StateConflict("SESSION_LIVE")
        row = self._db.execute(
            "SELECT state,state_version FROM sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        version = row[1] if row else None
        if (
            expected_version is not None
            and expected_version != version
            and (row is None or row[0] != SessionState.FINALIZED.value)
        ):
            raise StateConflict("STALE_SESSION_VERSION")
        if row is None:
            if operation == "seal":
                raise KeyError(session_id)
            try:
                directory = safe_path(self.root, f"sessions/{session_id}")
                if not directory.is_dir():
                    raise KeyError(session_id)
            except ValidationError:
                raise StateConflict("INSPECTION_UNSAFE") from None
            except OSError:
                raise StateConflict("INSPECTION_UNAVAILABLE") from None
        elif operation == "seal" and row[0] != SessionState.FINALIZED.value:
            # A legacy direct seal call must also reject an illegal state
            # before a claim can interfere with any cooperating caller.
            transition_session(
                Session(session_id, SessionState(row[0]), row[1]),
                SessionState.FINALIZED,
                row[1],
            )
        return True

    @contextmanager
    def _session_operation(
        self,
        session_id: str,
        *,
        exclusive: bool = True,
        admission: str | None = None,
        expected_version: int | None = None,
        history_binding: tuple[str, int] | None = None,
    ) -> Iterator[None]:
        """Serialize one session without holding the capture writer's root mutex."""
        identifier(session_id)
        with self._mutex:
            lock = self._session_locks.setdefault(session_id, threading.RLock())
        # Waiting is deliberately outside root_mutex. Nested recovery/manifest
        # operations on the same thread retain the original claim.
        with lock:
            with self._mutex:
                if history_binding is not None and history_binding != (
                    self._authority.instance,
                    self._authority.epoch,
                ):
                    raise ValidationError(_HISTORY_UNAVAILABLE)
                nested = session_id in self._claims
                admitted = admission is None or self._admit_session(
                    session_id, admission, expected_version
                )
                self._check_claim(session_id)
                if admitted:
                    self._claims[session_id] = threading.get_ident()
                if admitted and not nested and exclusive:
                    self._exclusive_claims.add(session_id)
            try:
                yield
            except StateConflict:
                with self._mutex:
                    deleted = self._writer_intent(session_id)
                if deleted:
                    raise StateConflict("DELETE_PENDING") from None
                raise
            finally:
                if admitted and not nested:
                    with self._mutex:
                        self._claims.pop(session_id, None)
                        self._exclusive_claims.discard(session_id)

    def _manifest_current(self, manifest: dict[str, Any]) -> None:
        """Called under root mutex immediately before publishing a snapshot."""
        sid = manifest["session_id"]
        self._check_claim(sid)
        self._live(sid)
        row = self._db.execute(
            "SELECT generation,state_version FROM sessions WHERE session_id=?", (sid,)
        ).fetchone()
        if row is None or (row[0], row[1]) != (manifest["generation"], manifest["state_version"]):
            raise StateConflict("STALE_SESSION_VERSION")

    def transition(self, session_id: str, target: SessionState, expected_version: int) -> Session:
        with self._mutex:
            self._check_claim(session_id)
            if target == SessionState.FINALIZED:
                raise StateConflict("Use finalize_session to seal the original list")
            with self._transaction() as connection:
                current = self.get_session(session_id)
                changed = transition_session(current, target, expected_version)
                connection.execute(
                    """UPDATE sessions SET state=?,state_version=?,generation=generation+1,
                                      manifest_sync_pending=1 WHERE session_id=?""",
                    (changed.state.value, changed.state_version, session_id),
                )
                self._event(connection, session_id, changed.state.value, changed.state_version)
            return changed

    def register_chunk(self, descriptor: ChunkDescriptor | SealedChunk) -> None:
        """Catalog a sealed bundle; all hashing runs outside the root mutex.

        A SealedChunk issued by this process's sealer for this root was verified on
        disk exactly once while sealing; it gets a cheap identity check (descriptor
        bytes and PCM size) and a deletion test of its own session only, so another
        session's journal cannot stop a recording. Everything else (recovery
        adoption, external callers, a released or copied capability) is fully
        verified and uses the management deletion check, as before. SQLite busy
        is retried within the connection's original timeout, never under root.
        """
        candidate = descriptor
        sealed = issued_descriptor(candidate, self.root)
        if sealed is not None:
            descriptor = sealed
            self._check_sealed_identity(safe_path(self.root, descriptor.relative_path), sealed)
        else:
            if isinstance(descriptor, SealedChunk):
                descriptor = descriptor.descriptor
            path = safe_path(self.root, descriptor.relative_path)
            if verify_bundle(path) != descriptor:
                raise ValidationError("Catalog descriptor differs from verified bundle")
        session_id = descriptor.session_id

        def attempt() -> None:
            # Root held, busy_timeout=0. A retry never inherits old authority.
            if sealed is not None and issued_descriptor(candidate, self.root) != sealed:
                raise StateConflict("Sealed chunk released before registration")
            # Admission must never create an exclusive claim over a live
            # recorder. Even if that invariant is broken, preserve its writer.
            if not self._is_live(session_id):
                self._check_claim(session_id)
            if sealed is not None:
                if self._writer_intent(session_id):
                    raise StateConflict("Session has a deletion intent")
            else:
                self._live(session_id)
            with self._transaction() as connection:
                existing = connection.execute(
                    "SELECT descriptor FROM chunks WHERE chunk_id=?", (descriptor.chunk_id,)
                ).fetchone()
                encoded = canonical(descriptor.to_dict()).decode("utf-8")
                if existing:
                    if existing[0] != encoded:
                        raise StateConflict("Conflicting chunk identity")
                    return
                row = connection.execute(
                    "SELECT state FROM sessions WHERE session_id=?", (session_id,)
                ).fetchone()
                if row is None:
                    raise KeyError(session_id)
                if row[0] == SessionState.FINALIZED.value:
                    raise StateConflict("Finalized original list is immutable")
                # Only rows of the same track and epoch can overlap. SQLite evaluates
                # this in C instead of decoding every catalog row of the session.
                overlap = connection.execute(
                    "SELECT 1 FROM chunks WHERE session_id=? "
                    "AND json_extract(descriptor,'$.track_id')=? "
                    "AND json_extract(descriptor,'$.epoch_id')=? "
                    "AND json_extract(descriptor,'$.first_sequence')<=? "
                    "AND ?<=json_extract(descriptor,'$.last_sequence') LIMIT 1",
                    (
                        session_id,
                        descriptor.track_id,
                        descriptor.epoch_id,
                        descriptor.last_sequence,
                        descriptor.first_sequence,
                    ),
                ).fetchone()
                if overlap is not None:
                    raise StateConflict("Overlapping source sequence ranges")
                connection.execute(
                    "INSERT INTO chunks VALUES(?,?,?,?)",
                    (descriptor.chunk_id, descriptor.session_id, descriptor.relative_path, encoded),
                )
                connection.execute(
                    "UPDATE sessions SET generation=generation+1,manifest_sync_pending=1 "
                    "WHERE session_id=?",
                    (descriptor.session_id,),
                )

        with self._mutex:
            timeout_ms = self._db.execute("PRAGMA busy_timeout").fetchone()[0]
        # I/O deadlines use monotonic time, independent of journal wall-clock age.
        deadline = _registration_clock() + timeout_ms / 1000
        while True:
            try:
                with self._mutex:
                    connection = self._db
                    previous_timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]
                    connection.execute("PRAGMA busy_timeout=0")
                    try:
                        attempt()
                    finally:
                        connection.execute(f"PRAGMA busy_timeout={previous_timeout}")
                return
            except sqlite3.OperationalError as error:
                code = getattr(error, "sqlite_errorcode", None)
                if type(code) is not int or code & 0xFF not in (
                    sqlite3.SQLITE_BUSY,
                    sqlite3.SQLITE_LOCKED,
                ):
                    raise
                remaining = deadline - _registration_clock()
                if remaining <= 0:
                    raise
            # No root, registry, capture gate or transaction is held while waiting.
            _registration_wait(min(0.01, remaining))

    @staticmethod
    def _check_sealed_identity(path: Path, descriptor: ChunkDescriptor) -> None:
        """The bundle a sealer just published is still that bundle (no re-hash)."""

        def read_identity() -> None:
            expected = canonical(descriptor.to_dict()) + b"\n"
            with open_file(path / "descriptor.json", "rb") as stream:
                if stream.read(len(expected) + 1) != expected:
                    raise ValidationError("Sealed chunk changed before registration")
            with open_file(path / "audio.pcm", "rb") as stream:
                if os.fstat(stream.fileno()).st_size != descriptor.byte_count:
                    raise ValidationError("Sealed chunk changed before registration")

        retry_sealed_read(read_identity)

    def chunks(self, session_id: str) -> list[ChunkDescriptor]:
        with self._mutex:
            self.get_session(session_id)
            rows = self._chunk_rows(session_id)
        return self._decode_chunks(rows)

    def _chunk_rows(self, session_id: str) -> list[str]:
        # Caller holds root_mutex only while copying SQLite rows.
        return [
            row[0]
            for row in self._db.execute(
                "SELECT descriptor FROM chunks WHERE session_id=? ORDER BY rowid", (session_id,)
            )
        ]

    @staticmethod
    def _decode_chunks(rows: list[str]) -> list[ChunkDescriptor]:
        descriptors = [ChunkDescriptor.from_dict(strict_json(row.encode("utf-8"))) for row in rows]
        epochs: dict[tuple[str, str], int] = {}
        for descriptor in descriptors:
            key = (descriptor.track_id, descriptor.epoch_id)
            epochs.setdefault(key, len(epochs))
        return sorted(
            descriptors,
            key=lambda d: (
                d.track_id,
                epochs[(d.track_id, d.epoch_id)],
                d.first_sequence,
                d.chunk_id,
            ),
        )

    def record_capture_health(self, session_id: str, health: dict[str, Any]) -> None:
        encoded = canonical(
            _bounded_health_projection(health)
            if health.get("health_schema_version") == 2
            else health
        )
        strict_json(encoded)
        with self._mutex:
            self._check_claim(session_id)
            self.get_session(session_id)
            current = self._db.execute(
                "SELECT capture_health FROM sessions WHERE session_id=?", (session_id,)
            ).fetchone()[0]
            if '"health_schema_version":2' in current.replace(" ", ""):
                # Backend metadata is additive; legacy writers cannot erase v2 authority.
                existing = strict_json(current.encode())
                for key in (
                    "health_schema_version",
                    "health_version",
                    "epochs",
                    "tracks",
                    "has_unknown",
                    "detail_complete",
                    "capture_run_id",
                    "checkpoint_seq",
                    "run_status",
                ):
                    if key in existing and health.get(key) != existing[key]:
                        raise StateConflict("HEALTH_EVENT_CONFLICT")
            # Metadata size is bounded; callers must only supply the health DTO,
            # never audio, secrets or free-form provider exception bodies.
            with self._transaction() as connection:
                connection.execute(
                    "UPDATE sessions SET capture_health=?,generation=generation+1,"
                    "manifest_sync_pending=1 WHERE session_id=?",
                    (encoded.decode("utf-8"), session_id),
                )

    @contextmanager
    def _health_transaction(self) -> Iterator[sqlite3.Connection]:
        """Authority holds root_mutex: ancillary metadata never waits on SQLite busy."""
        connection = self._db
        timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]
        connection.execute("PRAGMA busy_timeout=0")
        try:
            with self._transaction() as transaction:
                yield transaction
        finally:
            connection.execute(f"PRAGMA busy_timeout={timeout}")

    def defer_capture_health(self, session_id: str, run_id: str) -> None:
        """Best-effort conservative marker; no CLOSED or fabricated observations."""
        old = self.capture_health(session_id, for_capture=True)
        previous = canonical(old).decode()
        old.update(
            health_status="DEFERRED",
            health_error="HEALTH_RECOVERY_PENDING",
            has_unknown=True,
            detail_complete=False,
            deferred_run_id=run_id,
        )
        for track in old.get("tracks", {}).values():
            track.update(detail_complete=False, media_loss_unknown=True, count_complete=False)
            track.update(track_loss(track))
        body = canonical(_bounded_health_projection(old)).decode()
        with self._health_authority(session_id, capture=True) as authority:
            if authority != "VALID":
                raise StateConflict("DELETE_PENDING")
            current = self._db.execute(
                "SELECT capture_health FROM sessions WHERE session_id=?", (session_id,)
            ).fetchone()[0]
            if current != previous:
                raise StateConflict("HEALTH_SNAPSHOT_CHANGED")
            with self._health_transaction() as connection:
                connection.execute(
                    "UPDATE sessions SET capture_health=?,generation=generation+1,manifest_sync_pending=1 WHERE session_id=?",
                    (body, session_id),
                )

    def note_capture_health_deferred(self, session_id: str) -> None:
        """Nonpersistent conservative read-model fact, independent of marker storage."""
        with self._mutex:
            self._deferred_health_sessions.add(session_id)

    @staticmethod
    def _deferred_health_view(health: dict[str, Any]) -> dict[str, Any]:
        health.update(
            health_status="DEFERRED",
            health_error="HEALTH_RECOVERY_PENDING",
            has_unknown=True,
            detail_complete=False,
        )
        for track in health.get("tracks", {}).values():
            track.update(detail_complete=False, media_loss_unknown=True, count_complete=False)
            track.update(track_loss(track))
        return health

    def capture_health_pending(self, session_id: str) -> bool:
        """Stop admission checks canonical OPEN runs, not only the last run's projection."""
        health = self.capture_health(session_id)
        with self._mutex:
            return health.get("health_status") == "DEFERRED" or bool(
                self._db.execute(
                    "SELECT 1 FROM capture_health_runs WHERE session_id=? AND status='OPEN' LIMIT 1",
                    (session_id,),
                ).fetchone()
            )

    def capture_health(self, session_id: str, *, for_capture: bool = False) -> dict[str, Any]:
        if for_capture:
            return self._health_input(session_id, capture=True)[0]
        with self._mutex:
            session = self.get_session(session_id)
            row = self._db.execute(
                "SELECT capture_health FROM sessions WHERE session_id=?", (session_id,)
            ).fetchone()
            raw = row[0]
            deferred = session_id in self._deferred_health_sessions
            open_runs = {
                r[0]
                for r in self._db.execute(
                    "SELECT capture_run_id FROM capture_health_runs WHERE session_id=? AND status='OPEN'",
                    (session_id,),
                )
            }
        health = strict_json(raw.encode("utf-8"))
        if (
            deferred
            or open_runs - {health.get("capture_run_id")}
            or (open_runs and session.state != SessionState.RECORDING)
        ):
            return self._deferred_health_view(health)
        return health

    @contextmanager
    def _health_authority(self, session_id: str, *, capture: bool = False) -> Iterator[str]:
        if not capture:
            with self._mutex:
                context = getattr(self._capture_scopes, "current", None)
                if context is not None:
                    self._validate_capture_control(session_id, context)
                    capture = True
        if not capture:
            with self.job_authority(self.db_path, session_id) as state:
                yield state
            return
        # Same per-session authority as capture's _writer_intent. Never open other
        # sessions' journal bodies on the recording path. Names are prepared off root.
        for _ in range(3):
            with self._mutex:
                version = self._history_version
            try:
                stamp = self._journal_stamp()
                with self._mutex:
                    if (
                        self._intent_journal is not None
                        and self._intent_stamp == stamp
                        and self._intent_settled
                    ):
                        names: AbstractSet[str] | None = self._intent_names
                        incomplete = False
                    elif (
                        self._journal_listing is not None
                        and self._journal_listing[0] == stamp
                        and self._journal_listing[3]
                    ):
                        _, names, incomplete, _ = self._journal_listing
                    else:
                        names = None
                if names is None:
                    names, _ = self._list_journal(stamp)
                    incomplete = any(name.startswith(".tmp-") for name in names)
            except (ValueError, OSError):
                yield "HISTORY_UNAVAILABLE"
                return
            with self._mutex:
                if version != self._history_version or stamp != self._journal_stamp():
                    continue
                self._check_version()
                if self._missing_deletion_history or incomplete:
                    state = "HISTORY_UNAVAILABLE"
                elif (
                    session_id in self._reserved_intents
                    or self._authority.known(session_id) is not None
                    or f"{session_id}.json" in names
                    or self._db_intent(session_id)
                ):
                    state = "DELETED"
                elif self._db.execute(
                    "SELECT 1 FROM sessions WHERE session_id=?", (session_id,)
                ).fetchone():
                    state = "VALID"
                else:
                    state = "MISSING"
                yield state
                return
        raise StateConflict("HEALTH_SNAPSHOT_CHANGED")

    def _health_input(
        self, session_id: str, *, capture: bool = False
    ) -> tuple[dict[str, Any], int]:
        # Prepare deletion authority off root; parse JSON after releasing its lease.
        with self._health_authority(session_id, capture=capture) as authority:
            if authority != "VALID":
                raise StateConflict(
                    "DELETE_PENDING" if authority != "HISTORY_UNAVAILABLE" else _HISTORY_UNAVAILABLE
                )
            raw = self._db.execute(
                "SELECT capture_health FROM sessions WHERE session_id=?", (session_id,)
            ).fetchone()[0]
        health = strict_json(raw.encode())
        version = health.get("health_version", 0)
        integer(version)
        marker = health.get("health_schema_version")
        if marker is not None and (type(marker) is not int or marker != 2):
            raise ValidationError("HEALTH_VERSION_UNSUPPORTED")
        with self._mutex:
            row = self._db.execute(
                "SELECT COUNT(*),MAX(health_version),MIN(schema_version),MAX(schema_version) FROM capture_health_runs WHERE session_id=?",
                (session_id,),
            ).fetchone()
        if row[0]:
            if row[2] != 2 or row[3] != 2:
                raise ValidationError("HEALTH_VERSION_UNSUPPORTED")
            if marker != 2 or row[1] != version:
                raise ValidationError("HEALTH_UNREADABLE")
        elif marker == 2:
            raise ValidationError("HEALTH_UNREADABLE")
        return health, version

    def begin_capture_health(
        self, session_id: str, snapshot: dict[str, Any], *, expected_state_version: int
    ) -> int:
        return self._store_health(
            session_id,
            snapshot,
            expected_health_version=self._health_input(session_id, capture=True)[1],
            begin_version=expected_state_version,
            capture=True,
        )

    def checkpoint_capture_health(
        self, session_id: str, snapshot: dict[str, Any], *, expected_health_version: int
    ) -> int:
        return self._store_health(
            session_id, snapshot, expected_health_version=expected_health_version, capture=True
        )

    def finish_capture_health(
        self,
        session_id: str,
        snapshot: dict[str, Any],
        *,
        expected_health_version: int,
        receipt: CaptureReceipt,
    ) -> int:
        if not isinstance(receipt, CaptureReceipt) or not receipt.complete(
            snapshot.get("capture_run_id", "")
        ):
            raise StateConflict("HEALTH_ACK_PENDING")
        return self._store_health(
            session_id,
            snapshot,
            expected_health_version=expected_health_version,
            status="CLOSED",
            capture=True,
        )

    def _store_health(
        self,
        session_id: str,
        snapshot: dict[str, Any],
        *,
        expected_health_version: int,
        begin_version: int | None = None,
        status: str = "OPEN",
        capture: bool = False,
    ) -> int:
        # Validation, encoding and projection happen outside the writer's root mutex.
        snapshot = json.loads(health_encoded(snapshot))
        validate_snapshot(snapshot)
        if snapshot["session_id"] != session_id:
            raise ValidationError("HEALTH_EVENT_CONFLICT")
        integer(expected_health_version)
        old, version = self._health_input(session_id, capture=capture)
        if version != expected_health_version:
            raise StateConflict("HEALTH_SNAPSHOT_CHANGED")
        if any(not e.get("capture_run_id") for e in old.get("epochs", [])) and not old.get(
            "legacy_archive_run_id"
        ):
            snapshot["legacy_projection"] = old
        run_id, seq = snapshot["capture_run_id"], snapshot["checkpoint_seq"]
        closing: list[dict[str, Any]] = []
        if snapshot.get("gate_open_mono_ns") is not None:
            with self._mutex:
                prior_events = self._db.execute(
                    "SELECT payload FROM capture_health_events WHERE session_id=? AND capture_run_id=(SELECT capture_run_id FROM capture_health_runs WHERE session_id=? AND capture_run_id!=? ORDER BY rowid DESC LIMIT 1) ORDER BY ordinal DESC LIMIT 256",
                    (session_id, session_id, run_id),
                ).fetchall()
            prior_facts = [json.loads(row[0]) for row in prior_events]
            closed_ids = {e["gap_id"] for e in prior_facts if e["kind"] == "CLOSE"}
            next_ordinal = max((e["ordinal"] for e in prior_facts), default=0) + 1
            for event in prior_facts:
                if (
                    event["reason"] in {"PAUSE", "SUSPEND"}
                    and event["kind"] == "OPEN"
                    and event["gap_id"] not in closed_ids
                ):
                    event.update(
                        event_id=stable_id(event["gap_id"], "close"),
                        kind="CLOSE",
                        open=False,
                        ordinal=next_ordinal,
                    )
                    next_ordinal += 1
                    event["start"], event["end"] = observed_interval(
                        event["start"],
                        snapshot["gate_open_mono_ns"],
                        event["clock_ref"],
                        snapshot["process_clock_id"],
                    )
                    if event["end"] is None:
                        event["range_quality"] = "UNKNOWN"
                    GapFact.from_dict(event)
                    closing.append(event)
        with self._mutex:
            previous = self._db.execute(
                "SELECT checkpoint_seq,status,payload FROM capture_health_runs WHERE session_id=? AND capture_run_id=?",
                (session_id, run_id),
            ).fetchone()
            event_rows = {
                event["event_id"]: self._db.execute(
                    "SELECT payload,digest FROM capture_health_events WHERE session_id=? AND event_id=?",
                    (session_id, event["event_id"]),
                ).fetchone()
                for event in snapshot["events"] + closing
            }
        payload = health_encoded({k: v for k, v in snapshot.items() if k != "events"})
        if previous is not None:
            prior = json.loads(previous[2])
            if "legacy_projection" in prior:
                snapshot["legacy_projection"] = prior["legacy_projection"]
                payload = health_encoded({k: v for k, v in snapshot.items() if k != "events"})
            if seq < previous[0] or (
                previous[1] != "OPEN"
                and not (previous[1] == status and seq == previous[0] and payload == previous[2])
            ):
                raise StateConflict("HEALTH_SNAPSHOT_CHANGED")
            for track, value in snapshot["tracks"].items():
                before = prior["tracks"].get(track)
                if before is None or value["epoch_id"] != before["epoch_id"]:
                    raise StateConflict("HEALTH_EVENT_CONFLICT")
                if any(
                    value.get(k, 0) < before.get(k, 0)
                    for k in ("accepted_frames", "dropped_frames", "device_lost_frames")
                ):
                    raise StateConflict("HEALTH_EVENT_CONFLICT")
            if seq == previous[0] and payload != previous[2]:
                raise StateConflict("HEALTH_EVENT_CONFLICT")
        elif begin_version is None and status != "RECOVERED_UNCLEAN":
            raise StateConflict("HEALTH_SNAPSHOT_CHANGED")
        events = [(e, health_encoded(e)) for e in snapshot["events"] + closing]
        event_digests = {event["event_id"]: sha256(body.encode()) for event, body in events}
        staged_ids: dict[str, str] = {}
        staged_phases: dict[tuple[str, str], str] = {}
        for event, body in events:
            phase_key = event["gap_id"], event["kind"]
            if (event["event_id"] in staged_ids and staged_ids[event["event_id"]] != body) or (
                phase_key in staged_phases and staged_phases[phase_key] != event["event_id"]
            ):
                raise StateConflict("HEALTH_EVENT_CONFLICT")
            staged_ids[event["event_id"]] = body
            staged_phases[phase_key] = event["event_id"]
            row = event_rows[event["event_id"]]
            if row is not None and (row[0] != body or row[1] != event_digests[event["event_id"]]):
                raise StateConflict("HEALTH_EVENT_CONFLICT")
            with self._mutex:
                phase = self._db.execute(
                    "SELECT event_id FROM capture_health_events WHERE session_id=? AND gap_id=? AND kind=?",
                    (session_id, event["gap_id"], event["kind"]),
                ).fetchone()
                opening = (
                    self._db.execute(
                        "SELECT payload FROM capture_health_events WHERE session_id=? AND gap_id=? AND kind='OPEN'",
                        (session_id, event["gap_id"]),
                    ).fetchone()
                    if event["kind"] == "CLOSE"
                    else None
                )
            if phase is not None and phase[0] != event["event_id"]:
                raise StateConflict("HEALTH_EVENT_CONFLICT")
            if event["kind"] == "CLOSE":
                before = (
                    json.loads(opening[0])
                    if opening is not None
                    else next(
                        (
                            e
                            for e, _ in events
                            if e["gap_id"] == event["gap_id"] and e["kind"] == "OPEN"
                        ),
                        None,
                    )
                )
                if before is None or any(
                    event[k] != before[k]
                    for k in (
                        "session_id",
                        "capture_run_id",
                        "track_id",
                        "epoch_id",
                        "reason",
                        "source",
                        "clock_ref",
                        "lost_frames",
                        "count_quality",
                    )
                ):
                    raise StateConflict("HEALTH_EVENT_CONFLICT")
        if previous is not None and seq == previous[0] and status == previous[1]:
            if any(event_rows[event["event_id"]] is None for event, _ in events):
                raise StateConflict("HEALTH_EVENT_CONFLICT")
            return version
        tracks = {
            k: {**v, **track_loss(v), "count_complete": status == "CLOSED"}
            for k, v in snapshot["tracks"].items()
        }
        epoch = {"capture_run_id": run_id, "tracks": tracks, "queue": snapshot.get("queue")}
        if snapshot["process_clock_id"] == "legacy":
            tracks = {**old.get("tracks", {}), **tracks}
        legacy_epochs = [e for e in old.get("epochs", []) if not e.get("capture_run_id")]
        epochs = [
            e
            for e in old.get("epochs", [])
            if e.get("capture_run_id") and e.get("capture_run_id") != run_id
        ]
        epochs.append(epoch)
        projection = json.loads(
            health_encoded(
                {
                    **old,
                    "health_schema_version": 2,
                    "health_version": version + 1,
                    "capture_run_id": run_id,
                    "checkpoint_seq": seq,
                    "run_status": status,
                    "epochs": legacy_epochs + epochs[-8:],
                    "tracks": tracks,
                    "has_unknown": old.get("has_unknown", False)
                    or any(e["source"] != "CONTROL" and e["lost_frames"] is None for e, _ in events)
                    or any(not v["detail_complete"] for v in tracks.values()),
                    "detail_complete": len(epochs) <= 8
                    and all(v["detail_complete"] for v in tracks.values()),
                    **(
                        {"legacy_archive_run_id": run_id}
                        if "legacy_projection" in snapshot and not old.get("legacy_archive_run_id")
                        else {}
                    ),
                }
            )
        )
        # Keep the compatibility projection bounded; canonical events never get evicted.
        for item in projection["epochs"]:
            if not item.get("capture_run_id"):
                continue  # Do not reinterpret, truncate or decorate legacy records.
            for value in item["tracks"].values():
                if len(value.get("gaps", [])) > 16:
                    value["gaps"] = value["gaps"][-16:]
                    value["gap_detail_truncated"] = True
                    value["detail_complete"] = projection["detail_complete"] = False
                if len(value.get("loss_ranges", [])) > 16:
                    value["loss_ranges"] = value["loss_ranges"][-16:]
                    value["detail_complete"] = projection["detail_complete"] = False
        for value in projection["tracks"].values():
            for key in ("gaps", "loss_ranges"):
                if len(value.get(key, [])) > 16:
                    value[key] = value[key][-16:]
                    if key == "gaps":
                        value["gap_detail_truncated"] = True
                    value["detail_complete"] = projection["detail_complete"] = False
        for track, value in projection["tracks"].items():
            prior_events = (
                old.get("tracks", {}).get(track, {}).get("events", [])
                if previous is not None
                else []
            )
            recent = {e["event_id"]: e for e in prior_events}
            recent.update(
                {
                    e["event_id"]: e
                    for e, _ in events
                    if e["track_id"] == track and e["capture_run_id"] == run_id
                }
            )
            value["events"] = list(recent.values())[-16:]
            omitted = (
                old.get("tracks", {}).get(track, {}).get("events_omitted", 0)
                if previous is not None
                else 0
            )
            value["events_omitted"] = omitted + max(0, len(recent) - 16)
            if value["events_omitted"]:
                projection["detail_complete"] = value["detail_complete"] = False
        with self._mutex:
            pending = session_id in self._deferred_health_sessions or bool(
                self._db.execute(
                    "SELECT 1 FROM capture_health_runs WHERE session_id=? AND capture_run_id!=? AND status='OPEN' LIMIT 1",
                    (session_id, run_id),
                ).fetchone()
            )
        if pending:
            self._deferred_health_view(projection)
        projection_body = canonical(_bounded_health_projection(projection))
        strict_json(projection_body)
        previous_body = canonical(old).decode()
        track_rows = [
            (
                track,
                value["epoch_id"],
                health_encoded(
                    {"session_id": session_id, "capture_run_id": run_id, "track_id": track, **value}
                ),
            )
            for track, value in snapshot["tracks"].items()
        ]
        with self._health_authority(session_id, capture=capture) as authority:
            if authority != "VALID":
                raise StateConflict(
                    "DELETE_PENDING" if authority != "HISTORY_UNAVAILABLE" else _HISTORY_UNAVAILABLE
                )
            self._check_claim(session_id)
            current = self._db.execute(
                "SELECT capture_health FROM sessions WHERE session_id=?", (session_id,)
            ).fetchone()[0]
            if current != previous_body:
                raise StateConflict("HEALTH_SNAPSHOT_CHANGED")
            with self._health_transaction() as connection:
                if begin_version is not None:
                    state_row = connection.execute(
                        "SELECT state,state_version FROM sessions WHERE session_id=?", (session_id,)
                    ).fetchone()
                    session = Session(session_id, SessionState(state_row[0]), state_row[1])
                    changed = transition_session(session, SessionState.RECORDING, begin_version)
                    connection.execute(
                        "UPDATE sessions SET state=?,state_version=? WHERE session_id=?",
                        (changed.state.value, changed.state_version, session_id),
                    )
                    self._event(connection, session_id, changed.state.value, changed.state_version)
                connection.execute(
                    "INSERT INTO capture_health_runs VALUES(?,?,2,?,?,?,?) ON CONFLICT(session_id,capture_run_id) DO UPDATE SET health_version=excluded.health_version,checkpoint_seq=excluded.checkpoint_seq,status=excluded.status,payload=excluded.payload",
                    (session_id, run_id, version + 1, seq, status, payload),
                )
                for track, epoch_id, body in track_rows:
                    connection.execute(
                        "INSERT INTO capture_health_tracks VALUES(?,?,?,?,?) ON CONFLICT(session_id,capture_run_id,track_id,epoch_id) DO UPDATE SET payload=excluded.payload",
                        (session_id, run_id, track, epoch_id, body),
                    )
                for event, body in events:
                    connection.execute(
                        "INSERT OR IGNORE INTO capture_health_events VALUES(?,?,?,?,?,?,?,?)",
                        (
                            session_id,
                            event["event_id"],
                            event["capture_run_id"],
                            event["ordinal"],
                            body,
                            event["gap_id"],
                            event["kind"],
                            event_digests[event["event_id"]],
                        ),
                    )
                connection.execute(
                    "UPDATE sessions SET capture_health=?,generation=generation+1,manifest_sync_pending=1 WHERE session_id=?",
                    (projection_body.decode(), session_id),
                )
        return version + 1

    def _resolve_capture_health_deferred(self, session_id: str) -> None:
        """Clear pending observation only after every run has a final health status."""
        old, _ = self._health_input(session_id)
        previous = canonical(old).decode()
        with self._mutex:
            pending = session_id in self._deferred_health_sessions
        if not pending and not any(
            key in old for key in ("health_status", "health_error", "deferred_run_id")
        ):
            return
        resolved = dict(old)
        for key in ("health_status", "health_error", "deferred_run_id"):
            resolved.pop(key, None)
        if pending:
            resolved["has_unknown"] = True
        body = canonical(
            _bounded_health_projection(resolved)
            if resolved.get("health_schema_version") == 2
            else resolved
        ).decode()
        with self._health_authority(session_id) as authority:
            if authority != "VALID":
                raise StateConflict("DELETE_PENDING")
            if self._db.execute(
                "SELECT 1 FROM capture_health_runs WHERE session_id=? AND status='OPEN' LIMIT 1",
                (session_id,),
            ).fetchone():
                raise StateConflict("HEALTH_RECOVERY_PENDING")
            current = self._db.execute(
                "SELECT capture_health FROM sessions WHERE session_id=?", (session_id,)
            ).fetchone()[0]
            if current != previous:
                raise StateConflict("HEALTH_SNAPSHOT_CHANGED")
            if body != previous:
                with self._health_transaction() as connection:
                    connection.execute(
                        "UPDATE sessions SET capture_health=?,generation=generation+1,manifest_sync_pending=1 WHERE session_id=?",
                        (body, session_id),
                    )
            self._deferred_health_sessions.discard(session_id)

    def _recover_capture_health(self, session_id: str) -> dict[str, Any]:
        """Called under the existing session claim, after deletion/live admission."""
        try:
            _, observed_version = self._health_input(session_id)
            cursor = None
            while True:
                page = self.capture_health_details(
                    session_id, cursor=cursor, expected_health_version=observed_version
                )
                cursor = page["next_cursor"]
                if cursor is None:
                    break
            with self._mutex:
                rows = self._db.execute(
                    "SELECT schema_version,status,payload FROM capture_health_runs WHERE session_id=? ORDER BY capture_run_id",
                    (session_id,),
                ).fetchall()
            # Validate the entire run set before making any repair.
            snapshots = []
            for row in rows:
                if type(row[0]) is not int or row[0] != 2:
                    raise ValidationError("HEALTH_VERSION_UNSUPPORTED")
                snapshot = strict_json(row[2].encode(), limit=8 * 1024 * 1024)
                validate_snapshot({**snapshot, "events": []})
                if row[1] not in {"OPEN", "CLOSED", "RECOVERED_UNCLEAN"}:
                    raise ValidationError("HEALTH_UNREADABLE")
                snapshots.append((row[1], snapshot))
            legacy = self.capture_health(session_id)
            sources = [legacy] + [
                s["legacy_projection"] for _, s in snapshots if "legacy_projection" in s
            ]
            known: dict[tuple[str, str], int | None] = {}
            for source in sources:
                for entry in source.get("epochs", []):
                    if entry.get("capture_run_id"):
                        continue
                    for track, value in entry.get("tracks", {}).items():
                        epoch = value.get("epoch_id")
                        if not isinstance(epoch, str):
                            continue
                        count = value.get("dropped_frames")
                        count = count if type(count) is int and count >= 0 else None
                        key = track, epoch
                        if key in known and known[key] != count:
                            count = None
                        known[key] = count
            represented = {
                (track, value["epoch_id"])
                for _, item in snapshots
                for track, value in item["tracks"].items()
            }
            if not rows or legacy.get("deferred_run_id"):
                for chunk in self.chunks(session_id):
                    key = chunk.track_id, chunk.epoch_id
                    if key not in represented:
                        known.setdefault(key, None)
            session = self.get_session(session_id)
            unclean = session.state in {
                SessionState.RECORDING,
                SessionState.INTERRUPTED,
                SessionState.FINALIZING,
            }
            unclean = unclean and not any(s["process_clock_id"] != "legacy" for _, s in snapshots)
            unclean = unclean or bool(legacy.get("deferred_run_id")) and not rows
            unknown = [key for key, count in known.items() if unclean or count is None]
            if unclean and not known and not rows:
                unknown = [("session", "unidentified")]
            completed = {
                (track, value["epoch_id"])
                for _, s in snapshots
                if s["process_clock_id"] == "legacy"
                for track, value in s["tracks"].items()
            }
            for track, epoch in unknown:
                if (track, epoch) in completed:
                    continue
                rid = stable_id(stable_id(session_id, "legacy"), track, epoch)
                snapshots.append(
                    (
                        "OPEN",
                        {
                            "schema_version": 2,
                            "session_id": session_id,
                            "capture_run_id": rid,
                            "process_clock_id": "legacy",
                            "checkpoint_seq": 0,
                            "observed_mono_ns": 0,
                            "tracks": {
                                track: {
                                    "epoch_id": epoch,
                                    "state": "STOPPED",
                                    "reason": "UNCLEAN",
                                    "accepted_frames": 0,
                                    "dropped_frames": known.get((track, epoch)) or 0,
                                    "legacy_prefix_known": known.get((track, epoch)) is not None,
                                    "detail_complete": False,
                                }
                            },
                            "events": [],
                        },
                    )
                )
            if not rows and not unknown:
                self._resolve_capture_health_deferred(session_id)
                return {
                    "status": "LEGACY",
                    "code": None,
                    "has_unknown": bool(self.capture_health(session_id).get("has_unknown")),
                }
            repaired = False
            for status, snapshot in snapshots:
                if status != "OPEN":
                    continue
                snapshot["events"] = []
                for track, value in snapshot["tracks"].items():
                    identity = stable_id(
                        session_id,
                        snapshot["capture_run_id"],
                        track,
                        value["epoch_id"],
                        snapshot["checkpoint_seq"],
                        "UNKNOWN_TAIL",
                    )
                    snapshot["events"].append(
                        GapFact(
                            session_id,
                            snapshot["capture_run_id"],
                            track,
                            value["epoch_id"],
                            identity,
                            identity,
                            snapshot.get("event_ordinal", snapshot["checkpoint_seq"]) + 1,
                            "UNKNOWN_TAIL",
                            "RECOVERY",
                            snapshot["process_clock_id"],
                            kind="UNKNOWN_TAIL",
                            detail_complete=False,
                            observation_bounds=(snapshot["observed_mono_ns"], None),
                        ).to_dict()
                    )
                    value.update(
                        state="STOPPED",
                        reason="UNCLEAN",
                        detail_complete=False,
                        media_loss_unknown=True,
                    )
                snapshot["checkpoint_seq"] += 1
                self._store_health(
                    session_id,
                    snapshot,
                    expected_health_version=self._health_input(session_id)[1],
                    status="RECOVERED_UNCLEAN",
                )
                repaired = True
            self._resolve_capture_health_deferred(session_id)
            return {
                "status": "RECOVERED_UNCLEAN"
                if repaired or any(s == "RECOVERED_UNCLEAN" for s, _ in snapshots)
                else "CLOSED",
                "code": None,
                "has_unknown": bool(self.capture_health(session_id).get("has_unknown")),
            }
        except StateConflict as error:
            code = str(error)
            if code not in {
                "DELETE_PENDING",
                "DELETION_HISTORY_UNAVAILABLE",
                "HEALTH_RECOVERY_PENDING",
            }:
                code = "HEALTH_RECOVERY_PENDING"
            return {"status": "DEFERRED", "code": code, "has_unknown": True}
        except (ValueError, TypeError, KeyError, OSError, sqlite3.Error) as error:
            code = (
                str(error)
                if str(error) in {"HEALTH_VERSION_UNSUPPORTED", "HEALTH_UNREADABLE"}
                else "HEALTH_RECOVERY_PENDING"
                if isinstance(error, (OSError, sqlite3.Error))
                else "HEALTH_UNREADABLE"
            )
            return {"status": "DEFERRED", "code": code, "has_unknown": True}

    def capture_health_details(
        self,
        session_id: str,
        *,
        cursor: str | None = None,
        limit: int = 128,
        expected_health_version: int | None = None,
    ) -> dict[str, Any]:
        """Indexed, bounded keyset pages; no full-history sort under root_mutex."""
        integer(limit, minimum=1)
        if limit > 256:
            raise ValidationError("HEALTH_PAGE_LIMIT")
        if expected_health_version is not None:
            integer(expected_health_version)
        summary, version = self._health_input(session_id)
        if expected_health_version is not None and expected_health_version != version:
            raise StateConflict("HEALTH_SNAPSHOT_CHANGED")
        phases = ("run", "track", "event")
        phase, key = "run", None
        if cursor is not None:
            if not isinstance(cursor, str):
                raise ValidationError("HEALTH_UNREADABLE")
            try:
                token = strict_json(cursor.encode(), limit=1024)
            except ValueError:
                raise ValidationError("HEALTH_UNREADABLE") from None
            if (
                set(token) != {"schema_version", "health_version", "phase", "key"}
                or type(token["schema_version"]) is not int
                or token["schema_version"] != 1
            ):
                raise ValidationError("HEALTH_UNREADABLE")
            integer(token["health_version"])
            if token["health_version"] != version:
                raise StateConflict("HEALTH_SNAPSHOT_CHANGED")
            phase, key = token["phase"], token["key"]
            if not isinstance(phase, str) or phase not in phases:
                raise ValidationError("HEALTH_UNREADABLE")
            if key is not None:
                if not isinstance(key, list) or len(key) != (1 if phase == "run" else 3):
                    raise ValidationError("HEALTH_UNREADABLE")
                for n, item in enumerate(key):
                    if phase == "event" and n == 1:
                        integer(item)
                    else:
                        identifier(item)
        page_rows: list[tuple[str, tuple[Any, ...], str, tuple[Any, ...]]] = []
        next_position: tuple[str, list[Any] | None] | None = None
        for current_phase in phases[phases.index(phase) :]:
            lower = key if current_phase == phase and key is not None else None
            remaining = limit - len(page_rows)
            with self._mutex:
                if current_phase == "run":
                    fetched = self._db.execute(
                        "SELECT capture_run_id,payload,status,health_version,schema_version FROM capture_health_runs WHERE session_id=? AND capture_run_id>? ORDER BY capture_run_id LIMIT ?",
                        (session_id, lower[0] if lower else "", remaining + 1),
                    ).fetchall()
                    prepared = [(current_phase, (r[0],), r[1], tuple(r[2:])) for r in fetched]
                elif current_phase == "track":
                    fetched = self._db.execute(
                        "SELECT capture_run_id,track_id,epoch_id,payload FROM capture_health_tracks WHERE session_id=? AND (capture_run_id,track_id,epoch_id)>(?,?,?) ORDER BY capture_run_id,track_id,epoch_id LIMIT ?",
                        (session_id, *(lower or ("", "", "")), remaining + 1),
                    ).fetchall()
                    prepared = [(current_phase, tuple(r[:3]), r[3], ()) for r in fetched]
                else:
                    fetched = self._db.execute(
                        "SELECT capture_run_id,ordinal,event_id,payload,gap_id,kind,digest FROM capture_health_events WHERE session_id=? AND (capture_run_id,ordinal,event_id)>(?,?,?) ORDER BY capture_run_id,ordinal,event_id LIMIT ?",
                        (session_id, *(lower or ("", -1, "")), remaining + 1),
                    ).fetchall()
                    prepared = [(current_phase, tuple(r[:3]), r[3], tuple(r[4:])) for r in fetched]
            page_rows.extend(prepared[:remaining])
            if len(prepared) > remaining:
                next_position = current_phase, list(prepared[remaining - 1][1])
                break
            if len(page_rows) == limit:
                n = phases.index(current_phase) + 1
                next_position = (phases[n], None) if n < len(phases) else None
                break
        items = []
        for kind, identity, raw, metadata in page_rows:
            try:
                value = strict_json(
                    raw.encode(), limit=4096 if kind == "event" else 8 * 1024 * 1024
                )
                if kind == "event":
                    event = GapFact.from_dict(value)
                    if (
                        event.session_id != session_id
                        or identity != (event.capture_run_id, event.ordinal, event.event_id)
                        or metadata != (event.gap_id, event.kind, sha256(raw.encode()))
                    ):
                        raise ValidationError("HEALTH_UNREADABLE")
                    with self._mutex:
                        parent = self._db.execute(
                            "SELECT 1 FROM capture_health_tracks WHERE session_id=? AND capture_run_id=? AND track_id=? AND epoch_id=?",
                            (session_id, event.capture_run_id, event.track_id, event.epoch_id),
                        ).fetchone()
                    if parent is None:
                        raise ValidationError("HEALTH_UNREADABLE")
                elif kind == "run":
                    validate_snapshot({**value, "events": []})
                    if (
                        metadata[0] not in {"OPEN", "CLOSED", "RECOVERED_UNCLEAN"}
                        or metadata[2] != 2
                        or value["session_id"] != session_id
                        or identity != (value["capture_run_id"],)
                    ):
                        raise ValidationError("HEALTH_UNREADABLE")
                else:
                    if value["session_id"] != session_id or identity != (
                        value["capture_run_id"],
                        value["track_id"],
                        value["epoch_id"],
                    ):
                        raise ValidationError("HEALTH_UNREADABLE")
                    validate_snapshot(
                        {
                            "schema_version": 2,
                            "session_id": value["session_id"],
                            "capture_run_id": value["capture_run_id"],
                            "process_clock_id": "validation",
                            "checkpoint_seq": 0,
                            "observed_mono_ns": 0,
                            "tracks": {
                                value["track_id"]: {
                                    k: v
                                    for k, v in value.items()
                                    if k not in {"session_id", "capture_run_id", "track_id"}
                                }
                            },
                            "events": [],
                        }
                    )
            except (ValueError, TypeError, KeyError):
                raise ValidationError("HEALTH_UNREADABLE") from None
            item = {"kind": kind, "value": value}
            if kind == "run":
                item.update(
                    status=metadata[0], health_version=metadata[1], schema_version=metadata[2]
                )
            items.append(item)
        if self._health_input(session_id)[1] != version:
            raise StateConflict("HEALTH_SNAPSHOT_CHANGED")
        next_cursor = (
            None
            if next_position is None
            else health_encoded(
                {
                    "schema_version": 1,
                    "health_version": version,
                    "phase": next_position[0],
                    "key": next_position[1],
                }
            )
        )
        return {
            "health_version": version,
            "rows": items,
            "next_cursor": next_cursor,
            "legacy_only": summary.get("health_schema_version") != 2,
        }

    def _manifest(self, session_id: str) -> dict[str, Any]:
        with self._mutex:
            session = self.get_session(session_id)
            rows = self._chunk_rows(session_id)
            row = self._db.execute(
                "SELECT generation FROM sessions WHERE session_id=?", (session_id,)
            ).fetchone()
            health = self.capture_health(session_id)
            generation = row[0]
        descriptors = self._decode_chunks(rows)
        for descriptor in descriptors:
            if verify_bundle(safe_path(self.root, descriptor.relative_path)) != descriptor:
                raise ValidationError("Catalog media changed")
        return {
            "schema_version": 1,
            "session_id": session_id,
            "state": session.state.value,
            "state_version": session.state_version,
            "generation": generation,
            "chunks": [descriptor.to_dict() for descriptor in descriptors],
            "chunk_count": len(descriptors),
            "frame_count": sum(descriptor.frame_count for descriptor in descriptors),
            "capture_health": health,
        }

    def write_manifest(self, session_id: str) -> dict[str, Any]:
        # A live writer may advance the catalog during projection. Keep deletion
        # from removing files, but never reject capture's chunk admission; the
        # generation comparison detects a stale projection instead.
        with self._session_operation(session_id, exclusive=False):
            with self._mutex:
                self._check_version()
            manifest = self._manifest(session_id)
            path = safe_path(self.root, f"sessions/{session_id}/manifest.json")
            if path.exists():
                try:
                    existing_manifest = read_json(path, limit=8 * 1024 * 1024)
                except ValidationError:
                    quarantine = safe_path(self.root, f"sessions/{session_id}/quarantine")
                    mkdir(quarantine)
                    path.rename(quarantine / ("manifest-" + uuid.uuid4().hex + ".json"))
                else:
                    schema(existing_manifest)
            with self._mutex:
                self._manifest_current(manifest)
            atomic_json(path, manifest)
            with self._mutex:
                self._manifest_current(manifest)
                with self._transaction() as connection:
                    connection.execute(
                        "UPDATE sessions SET manifest_sync_pending=0 "
                        "WHERE session_id=? AND generation=?",
                        (session_id, manifest["generation"]),
                    )
            return manifest

    def finalize_session(
        self,
        session_id: str,
        *,
        capture_control: CaptureControlContext | None = None,
        history_binding: tuple[str, int] | None = None,
    ) -> dict[str, Any]:
        if history_binding is not None:
            self._require_finalization_binding(history_binding)
        with self._capture_scope(session_id, capture_control):
            if history_binding is None:
                return self._finalize_session(session_id)
            return self._finalize_session(session_id, history_binding=history_binding)

    def _require_finalization_binding(self, history_binding: tuple[str, int]) -> None:
        """A binding restricts seal entry; it never grants management or capture rights."""
        with self._mutex:
            if history_binding != (self._authority.instance, self._authority.epoch):
                raise ValidationError(_HISTORY_UNAVAILABLE)

    def _refresh_finalization_history(self) -> tuple[str, int] | None:
        """Revalidate a coherently expired receipt before continuing management work."""
        if getattr(self._capture_scopes, "current", None) is not None:
            return None
        with self._mutex:
            state = self._authority
            receipt = state.receipt
            if receipt is None or state.needs_fresh or receipt.instance != state.instance:
                return None
            try:
                now = state.clock()
            except (ValueError, OSError, OverflowError):
                return None
            elapsed = max(
                now.monotonic_ns - receipt.started.monotonic_ns + now.span_ns,
                now.utc_ns - receipt.started.utc_ns,
            )
            # Use the existing clock continuity comparison, only to classify the expired
            # sample. A newly published ordinary receipt still has its normal lifetime.
            if elapsed < LIFETIME_NS or not now.within(receipt.started, elapsed + 1):
                return None
            observed = state.instance, state.epoch

        def can_publish() -> bool:
            current = self._authority
            return (current.instance, current.epoch) == observed and not current.needs_fresh

        if self.verify_deletion_history(can_publish=can_publish)["status"] != "READY":
            raise ValidationError(_HISTORY_UNAVAILABLE)
        return observed

    def _finalize_session(
        self, session_id: str, *, history_binding: tuple[str, int] | None = None
    ) -> dict[str, Any]:
        if history_binding is not None:
            self._require_finalization_binding(history_binding)
        operation = (
            self._session_operation(session_id, admission="seal")
            if history_binding is None
            else self._session_operation(
                session_id, admission="seal", history_binding=history_binding
            )
        )
        with operation:
            with self._mutex:
                if self._is_live(session_id):
                    raise StateConflict("Writer has not drained")
            _, health_version = self._health_input(session_id)
            cursor = None
            while True:
                page = self.capture_health_details(
                    session_id, cursor=cursor, expected_health_version=health_version
                )
                cursor = page["next_cursor"]
                if cursor is None:
                    break
            with self._mutex:
                if self._db.execute(
                    "SELECT 1 FROM capture_health_runs WHERE session_id=? AND status='OPEN' LIMIT 1",
                    (session_id,),
                ).fetchone():
                    raise StateConflict("HEALTH_RECOVERY_PENDING")
            manifest = self._manifest(session_id)
            encoded = canonical(manifest["chunks"]).decode("utf-8")
            observed = self._refresh_finalization_history()
            with self._mutex:
                if history_binding is not None and history_binding != (
                    self._authority.instance,
                    self._authority.epoch,
                ):
                    raise ValidationError(_HISTORY_UNAVAILABLE)
                if observed is not None and observed != (
                    self._authority.instance,
                    self._authority.epoch,
                ):
                    raise ValidationError(_HISTORY_UNAVAILABLE)
                self._require_management_or_capture(session_id)
                self._manifest_current(manifest)
                if self._is_live(session_id):
                    raise StateConflict("SESSION_LIVE")
                with self._transaction() as connection:
                    session = self.get_session(session_id)
                    if session.state != SessionState.FINALIZED:
                        changed = transition_session(
                            session, SessionState.FINALIZED, session.state_version
                        )
                        connection.execute(
                            "UPDATE sessions SET state=?,state_version=?,finalized_chunks=?,"
                            "generation=generation+1,manifest_sync_pending=1 WHERE session_id=?",
                            (changed.state.value, changed.state_version, encoded, session_id),
                        )
                        self._event(connection, session_id, "FINALIZED", changed.state_version)
            pending = False
            try:
                self.write_manifest(session_id)
            except (OSError, ValueError, sqlite3.Error):
                pending = True
            return {
                "state": SessionState.FINALIZED.value,
                "manifest_sync_pending": pending,
                "chunk_count": manifest["chunk_count"],
                "frame_count": manifest["frame_count"],
            }

    def _bundle_paths(self, session_id: str) -> Iterator[Path]:
        tracks = safe_path(self.root, f"sessions/{session_id}/tracks")
        if not tracks.exists():
            return
        for track in tracks.iterdir():
            check_path(track)
            identifier(track.name)
            if not track.is_dir():
                raise ValidationError("Invalid track directory")
            for epoch in track.iterdir():
                check_path(epoch)
                identifier(epoch.name)
                if not epoch.is_dir():
                    raise ValidationError("Invalid epoch directory")
                for bundle in epoch.iterdir():
                    check_path(bundle)
                    identifier(bundle.name)
                    yield bundle

    @staticmethod
    def _recovery_id(source: str, prefix: JournalPrefix) -> str:
        # Source ID plus verified content/metadata produces an idempotent new ID.
        return (
            "recovered-"
            + sha256(
                canonical({"source": source, "records": prefix.blocks, "sha256": prefix.sha256})
            )[:40]
        )

    def _staging_prefix(self, session_id: str, staging: Path) -> tuple[JournalPrefix, int]:
        """Read only: the verified prefix and the PCM bytes after it that are not adopted."""
        descriptor_path = staging / "descriptor.json"
        check_path(descriptor_path)
        if descriptor_path.exists():
            schema(read_json(descriptor_path))
        prefix = scan_prefix(staging)
        if prefix.blocks[0]["metadata"]["session_id"] != session_id:
            raise ValidationError("Staging session identity mismatch")
        with open_file(staging / "audio.pcm", "rb") as stream:
            size = os.fstat(stream.fileno()).st_size
        return prefix, max(0, size - prefix.byte_count)

    def _salvage(self, session_id: str, staging: Path) -> tuple[ChunkDescriptor, bool, int]:
        prefix, tail = self._staging_prefix(session_id, staging)
        first = prefix.blocks[0]["metadata"]
        recovery_id = self._recovery_id(staging.name, prefix)
        target = safe_path(
            self.root,
            f"sessions/{session_id}/tracks/{first['track_id']}/{first['epoch_id']}/{recovery_id}",
        )
        if target.exists():
            existing = verify_bundle(target)
            if (existing.sha256, existing.byte_count) != (prefix.sha256, prefix.byte_count):
                raise ValidationError("Recovery identity conflict")
            return existing, prefix.complete, tail
        with open_file(staging / "audio.pcm", "rb") as source:
            initial = PCMBlock.from_metadata(first, source.read(prefix.blocks[0]["length"]))
            writer = ChunkWriter(self.root, initial, recovery_id)
            # A killed salvage attempt must not block retries or become a new
            # independent original staging source. Keep work outside that scan.
            writer.staging_path = safe_path(
                self.root, f"sessions/{session_id}/recovery-work/{uuid.uuid4().hex}"
            )
            try:
                # The claim prevents removal, but not a new deletion intent.
                # Use the common writer guard at every actual write/publish;
                # fsync/hash work still runs outside the capture root mutex.
                with self._mutex:
                    self._live(session_id)
                writer.append(initial)
                for record in prefix.blocks[1:]:
                    with self._mutex:
                        self._live(session_id)
                    writer.append(
                        PCMBlock.from_metadata(record["metadata"], source.read(record["length"]))
                    )
                with self._mutex:
                    self._live(session_id)
                return writer.seal(), prefix.complete, tail
            finally:
                writer.abort()

    def _finalized_staging(
        self, session_id: str, staging: Path, known: dict[str, ChunkDescriptor]
    ) -> dict[str, Any]:
        """Classify staging kept after sealing without writing anything."""
        try:
            prefix, tail = self._staging_prefix(session_id, staging)
        except (ValueError, OSError):
            return _detail("staging", staging.name, "INVALID")
        recovery_id = self._recovery_id(staging.name, prefix)
        if recovery_id in known:
            status = "ALREADY_RECOVERED" if prefix.complete else "TAIL_NOT_ADOPTED"
            return _detail("staging", staging.name, status, recovery_id, prefix.frame_count, tail)
        return _detail(
            "staging", staging.name, "CANDIDATE_NOT_ADOPTED", None, prefix.frame_count, tail
        )

    def recover_session(
        self, session_id: str, *, capture_control: CaptureControlContext | None = None
    ) -> dict[str, Any]:
        with self._capture_scope(session_id, capture_control):
            return self._recover_session(session_id)

    def _recover_session(self, session_id: str) -> dict[str, Any]:
        with self._session_operation(session_id, admission="recover"):
            with self._mutex:
                identifier(session_id)
                self._require_management_or_capture(session_id)
                if self._writer_intent(session_id):
                    return {
                        "session_id": session_id,
                        "adopted": 0,
                        "recovered": 0,
                        "quarantined": 0,
                        "warnings": ["DELETION_INTENT"],
                        "state": "DELETE_PENDING",
                        "previous_state": "DELETE_PENDING",
                        "details": [],
                        "verified_chunk_ids": [],
                    }
                if has_active_writer(self.root, session_id):
                    raise StateConflict("Live writer cannot be recovered")
                if self._is_live(session_id):
                    # An accepting recorder may be between chunk writers (G04-CE1).
                    raise StateConflict("SESSION_LIVE")
            self._require_inspection_safe(session_id)
            try:
                session = self.get_session(session_id)
                previous = session.state.value
            except KeyError:
                session_root = safe_path(self.root, f"sessions/{session_id}")
                if not session_root.is_dir():
                    raise
                session = self.create_session(session_id)
                previous = "DIRECTORY_ONLY"
            details: list[dict[str, Any]] = []
            result: dict[str, Any] = {
                "session_id": session_id,
                "adopted": 0,
                "recovered": 0,
                "quarantined": 0,
                "warnings": [],
                "state": session.state.value,
                "previous_state": previous,
                "details": details,
            }
            known = {descriptor.chunk_id: descriptor for descriptor in self.chunks(session_id)}
            discovered: set[str] = set()
            verified: set[str] = set()
            for path in self._bundle_paths(session_id):
                try:
                    descriptor = verify_bundle(path)
                    if descriptor.chunk_id in known:
                        if descriptor != known[descriptor.chunk_id]:
                            raise ValidationError("Catalog mismatch")
                        discovered.add(descriptor.chunk_id)
                        verified.add(descriptor.chunk_id)
                        continue
                    if session.state == SessionState.FINALIZED:
                        result["quarantined"] += 1
                        result["warnings"].append("FINALIZED_ORPHAN")
                        details.append(
                            _detail(
                                "bundle",
                                path.name,
                                "CANDIDATE_NOT_ADOPTED",
                                descriptor.chunk_id,
                                descriptor.frame_count,
                            )
                        )
                        continue
                    self.register_chunk(descriptor)
                    known[descriptor.chunk_id] = descriptor
                    discovered.add(descriptor.chunk_id)
                    verified.add(descriptor.chunk_id)
                    result["adopted"] += 1
                    details.append(
                        _detail(
                            "bundle",
                            path.name,
                            "ADOPTED",
                            descriptor.chunk_id,
                            descriptor.frame_count,
                        )
                    )
                except (ValueError, OSError):
                    result["quarantined"] += 1
                    result["warnings"].append("INVALID_BUNDLE")
                    details.append(_detail("bundle", path.name, "INVALID"))
            for chunk_id in set(known) - discovered:
                result["warnings"].append("MISSING_OR_INVALID_CATALOG_MEDIA:" + chunk_id)
            staging_root = safe_path(self.root, f"sessions/{session_id}/staging")
            if staging_root.exists():
                for path in sorted(staging_root.iterdir(), key=lambda item: item.name):
                    try:
                        check_path(path)
                        identifier(path.name)
                        if session.state == SessionState.FINALIZED:
                            result["quarantined"] += 1
                            result["warnings"].append("FINALIZED_STAGING")
                            details.append(self._finalized_staging(session_id, path, known))
                            continue
                        recovered, complete_prefix, tail = self._salvage(session_id, path)
                        if not complete_prefix:
                            result["warnings"].append("STAGING_TAIL_NOT_ADOPTED")
                        new = recovered.chunk_id not in known
                        if new:
                            self.register_chunk(recovered)
                            known[recovered.chunk_id] = recovered
                            result["recovered"] += 1
                        elif recovered != known[recovered.chunk_id]:
                            raise ValidationError("Catalog mismatch")
                        verified.add(recovered.chunk_id)
                        status = (
                            "TAIL_NOT_ADOPTED"
                            if not complete_prefix
                            else "RECOVERED"
                            if new
                            else "ALREADY_RECOVERED"
                        )
                        details.append(
                            _detail(
                                "staging",
                                path.name,
                                status,
                                recovered.chunk_id,
                                recovered.frame_count,
                                tail,
                            )
                        )
                    except (ValueError, OSError):
                        result["quarantined"] += 1
                        result["warnings"].append("INVALID_STAGING")
                        details.append(_detail("staging", _display_name(path.name), "INVALID"))
            if session.state in (SessionState.RECORDING, SessionState.FINALIZING):
                session = self.transition(
                    session_id, SessionState.INTERRUPTED, session.state_version
                )
            result["state"] = session.state.value
            result["verified_chunk_ids"] = sorted(verified)
            result["health_recovery"] = self._recover_capture_health(session_id)
            try:
                self.write_manifest(session_id)
            except (OSError, ValueError, sqlite3.Error):
                result["warnings"].append("MANIFEST_SYNC_PENDING")
                with self._mutex:
                    self._live(session_id)
                    with self._transaction() as connection:
                        connection.execute(
                            "UPDATE sessions SET manifest_sync_pending=1 WHERE session_id=?",
                            (session_id,),
                        )
            return result

    def _inventory_item(
        self, session_id: str, state: str, version: int | None, catalog: set[str]
    ) -> dict[str, Any]:
        staging_entries = uncatalogued = 0
        inspection_error = None
        # Counts only: nothing is verified, adopted or written here.
        try:
            base = safe_path(self.root, f"sessions/{session_id}")
            staging = safe_path(base, "staging")
            if staging.is_dir():
                for entry in staging.iterdir():
                    self._inspect_media_path(entry)
                    staging_entries += 1
            tracks = safe_path(base, "tracks")
            if tracks.is_dir():
                for track in tracks.iterdir():
                    check_path(track)
                    if not track.is_dir():
                        continue
                    for epoch in track.iterdir():
                        check_path(epoch)
                        if not epoch.is_dir():
                            continue
                        for bundle in epoch.iterdir():
                            self._inspect_media_path(bundle)
                            uncatalogued += int(bundle.name not in catalog)
        except ValidationError:
            inspection_error = "INSPECTION_UNSAFE"
        except OSError:
            inspection_error = "INSPECTION_UNAVAILABLE"
        return {
            "session_id": session_id,
            "state": state,
            "state_version": version,
            "live": False,
            "catalog_chunks": len(catalog),
            "staging_entries": staging_entries if inspection_error is None else None,
            "uncatalogued_bundles": uncatalogued if inspection_error is None else None,
            "inspection_error": inspection_error,
        }

    @staticmethod
    def _inspect_media_path(path: Path) -> None:
        check_path(path)
        if path.is_dir():
            for name in ("audio.pcm", "blocks.jsonl", "descriptor.json"):
                check_path(path / name)

    def _require_inspection_safe(self, session_id: str) -> None:
        entry = self._inventory_item(session_id, "", None, set())
        if entry["inspection_error"] is not None:
            raise StateConflict(entry["inspection_error"])

    def _inventory(self) -> tuple[list[dict[str, Any]], int]:
        with self._mutex:
            deleted = self._deletion_intents()
            rows = self._db.execute(
                "SELECT session_id,state,state_version FROM sessions ORDER BY session_id"
            ).fetchall()
            snapshots: list[tuple[str, str, int, set[str], bool]] = []
            for session_id, state, version in rows:
                if (
                    session_id in deleted
                    or self._db_intent(session_id)
                    or SessionState(state) not in _UNFINISHED
                ):
                    continue
                catalog = {
                    row[0]
                    for row in self._db.execute(
                        "SELECT chunk_id FROM chunks WHERE session_id=?", (session_id,)
                    )
                }
                snapshots.append((session_id, state, version, catalog, self._is_live(session_id)))
        items = []
        for sid, state, version, catalog, live in snapshots:
            item = self._inventory_item(sid, state, version, catalog)
            item["live"] = live
            items.append(item)
        skipped = 0
        known = {row[0] for row in rows}
        sessions = safe_path(self.root, "sessions")
        if sessions.is_dir():
            for path in sorted(sessions.iterdir(), key=lambda item: item.name):
                if path.name in known or path.name in deleted:
                    continue
                try:
                    check_path(path)
                    identifier(path.name)
                    if not path.is_dir():
                        raise ValidationError("Not a session directory")
                except (ValueError, OSError):
                    skipped += 1
                    continue
                items.append(self._inventory_item(path.name, "DIRECTORY_ONLY", None, set()))
        return items, skipped

    def unfinished_inventory(self) -> tuple[list[dict[str, Any]], dict[str, int]]:
        """One read-only observation, not an admission token for later actions."""
        items, skipped = self._inventory()
        return items, {"skipped_entries": skipped}

    def unfinished_sessions(self) -> list[dict[str, Any]]:
        """Read-only inventory of sessions a user may need to finalize.

        FINALIZED sessions and deletion intents (DELETE_PENDING, tombstones) are excluded;
        listing pending deletions belongs to a later unit. A session directory without a
        catalog row is reported as DIRECTORY_ONLY and no row is created for it.
        """
        return self._inventory()[0]

    def inventory_warnings(self) -> dict[str, int]:
        """Entries under sessions/ that cannot be a session directory and were not listed."""
        return {"skipped_entries": self._inventory()[1]}

    def finalize_unfinished(
        self, session_id: str, *, expected_version: int | None = None
    ) -> dict[str, Any]:
        """Recover, then seal an unfinished session; idempotent for FINALIZED.

        Refusals change nothing: DELETE_PENDING (deletion intent), SESSION_LIVE (an
        in-process writer or owner), KeyError (no row and no directory) and
        STALE_SESSION_VERSION (expected_version differs before recovery).
        """
        with self._session_operation(
            session_id, admission="finalize", expected_version=expected_version
        ):
            with self._mutex:
                identifier(session_id)
                if expected_version is not None:
                    integer(expected_version)
                self._require_management_or_capture(session_id)
                if self._writer_intent(session_id):
                    raise StateConflict("DELETE_PENDING")
                if self._is_live(session_id):
                    raise StateConflict("SESSION_LIVE")
            self._require_inspection_safe(session_id)
            with self._mutex:
                row = self._db.execute(
                    "SELECT state,state_version FROM sessions WHERE session_id=?", (session_id,)
                ).fetchone()
            if row is None:
                if not safe_path(self.root, f"sessions/{session_id}").is_dir():
                    raise KeyError(session_id)
                previous_state, previous_version = "DIRECTORY_ONLY", None
            else:
                previous_state, previous_version = row[0], row[1]
            if previous_state == SessionState.FINALIZED.value:
                recovery = self.recover_session(session_id)
                with self._mutex:
                    self._live(session_id)
                    sealed_row = self._db.execute(
                        "SELECT finalized_chunks,manifest_sync_pending FROM sessions "
                        "WHERE session_id=?",
                        (session_id,),
                    ).fetchone()
                # Report the sealed list itself; a missing file is a recovery warning.
                sealed_list = json.loads(sealed_row[0] or "[]")
                return {
                    "session_id": session_id,
                    "state": SessionState.FINALIZED.value,
                    "already_finalized": True,
                    "finalized": recovery.get("health_recovery", {}).get("status") != "DEFERRED",
                    "previous_state": previous_state,
                    "recovery": recovery,
                    "chunk_count": len(sealed_list),
                    "frame_count": sum(int(item["frame_count"]) for item in sealed_list),
                    "manifest_sync_pending": bool(sealed_row[1]),
                }
            if expected_version is not None and expected_version != previous_version:
                raise StateConflict("STALE_SESSION_VERSION")
            recovery = self.recover_session(session_id)
            if recovery.get("health_recovery", {}).get("status") == "DEFERRED":
                return {
                    "session_id": session_id,
                    "state": self.get_session(session_id).state.value,
                    "finalized": False,
                    "health_recovery": recovery["health_recovery"],
                    "recovery": recovery,
                    "previous_state": previous_state,
                }
            observed = self._refresh_finalization_history()
            with self._mutex:
                if observed is not None and observed != (
                    self._authority.instance,
                    self._authority.epoch,
                ):
                    raise ValidationError(_HISTORY_UNAVAILABLE)
                session = self.get_session(session_id)
                if session.state != SessionState.FINALIZING:
                    self.transition(session_id, SessionState.FINALIZING, session.state_version)
            if observed is None:
                sealed = self.finalize_session(session_id)
            else:
                sealed = self.finalize_session(session_id, history_binding=observed)
            return {
                "session_id": session_id,
                "state": SessionState.FINALIZED.value,
                "already_finalized": False,
                "previous_state": previous_state,
                "recovery": recovery,
                "chunk_count": sealed["chunk_count"],
                "frame_count": sealed["frame_count"],
                "manifest_sync_pending": sealed["manifest_sync_pending"],
            }

    def delete_session(self, session_id: str) -> dict[str, Any]:
        """Record a durable intent first, then remove media when no owner remains.

        Returns DELETED_LOCAL, DELETE_PENDING (with reason) or NOT_FOUND. An
        existing intent keeps its generation; a completed tombstone is never
        demoted. Storage exceptions propagate as before.
        """
        return self._progress_deletion(
            session_id, expected_generation=None, create=True, strict=False
        )

    def retry_deletion(self, session_id: str, *, expected_generation: int) -> dict[str, Any]:
        """Retry an existing intent only; never turn an unknown ID into a new deletion.

        NOT_PENDING when no intent exists. StateConflict STALE_DELETE_GENERATION
        (expected_generation differs) or DELETE_HISTORY_CONFLICT, and
        ValidationError DELETION_HISTORY_UNAVAILABLE / DELETION_METADATA_PENDING,
        change no media and report no completion.
        """
        identifier(session_id)
        integer(expected_generation, minimum=1)
        return self._progress_deletion(
            session_id, expected_generation=expected_generation, create=False, strict=True
        )

    def deletion_generation(self, session_id: str) -> int | None:
        """Read only: the current deletion-intent generation (pending or completed)."""
        identifier(session_id)
        with self._mutex:
            self._require_history()
            current, published = self._deletion_record(session_id)
            return max(current[0] if current else 0, published or 0) or None

    def _deletion_record(self, session_id: str) -> tuple[tuple[int, str] | None, int | None]:
        """One exact DB key and pinned journal floor; root mutex held."""
        known = self._authority.known(session_id)
        row = self._db.execute(
            "SELECT generation,status FROM deleted_sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        current = (row[0], row[1]) if row is not None else None
        if current is not None:
            integer(current[0], minimum=1)
            if current[1] not in _DELETION_STATUSES:
                raise ValidationError(_HISTORY_UNAVAILABLE)
        if known is not None and known.db_generation is not None:
            if (
                current is None
                or current[0] < known.db_generation
                or (known.db_status == "DELETED_LOCAL" and current[1] != "DELETED_LOCAL")
            ):
                self._authority.invalidate()
                raise ValidationError(_HISTORY_UNAVAILABLE)
        return current, known.journal_generation if known is not None else None

    def pending_deletions(self) -> list[dict[str, Any]]:
        """Read-only inventory of durable deletion intents requiring completion or repair.

        DB rows, journal and catalog generations are one observation under root_mutex;
        in-process owner/reader flags are read in short bounded batches and folder
        presence outside the mutex. Nothing is repaired, removed or ACKed. History
        corruption raises ValidationError and a newer catalog generation raises
        StateConflict DELETE_HISTORY_CONFLICT; neither becomes an empty list.
        """
        observed: list[dict[str, Any]] = []
        after = ""
        while True:
            with self._mutex:
                self._check_version()
                if self._history_conflict:
                    raise StateConflict("DELETE_HISTORY_CONFLICT")
                self._require_history()
                identities = [
                    row[0]
                    for row in self._db.execute(
                        "SELECT session_id FROM storage_pending_deletions "
                        "WHERE session_id>? ORDER BY session_id LIMIT 128",
                        (after,),
                    )
                ]
                for session_id in identities:
                    current, published = self._deletion_record(session_id)
                    row = self._db.execute(
                        "SELECT generation FROM sessions WHERE session_id=?", (session_id,)
                    ).fetchone()
                    generation = max(current[0] if current else 0, published or 0)
                    if generation == 0:
                        raise ValidationError(_HISTORY_UNAVAILABLE)
                    if row is not None and row[0] > generation:
                        raise StateConflict("DELETE_HISTORY_CONFLICT")
                    observed.append(
                        {
                            "session_id": session_id,
                            "generation": generation,
                            "current": current,
                            "published": published,
                            "session_generation": row[0] if row else None,
                        }
                    )
            if len(identities) < 128:
                break
            after = identities[-1]
        for start in range(0, len(observed), 64):
            with self._mutex:
                connection = self._db
                for entry in observed[start : start + 64]:
                    session_id = entry["session_id"]
                    entry["live"] = self._is_live(session_id)
                    entry["active"] = has_active_writer(self.root, session_id) or self._active_jobs(
                        session_id, connection
                    )
                    entry["claimed"] = session_id in self._claims
        items = []
        for entry in observed:
            session_id, generation = entry["session_id"], entry["generation"]
            current, published = entry["current"], entry["published"]
            media = self._media_present(session_id)
            session_present = entry["session_generation"] is not None
            if (
                current == (generation, "DELETED_LOCAL")
                and published == generation
                and not session_present
                and not media
            ):
                continue  # a completed tombstone is history, not pending work
            journal_repair = published != generation
            repair = (
                journal_repair
                or current is None
                or current[0] != generation
                or (session_present and entry["session_generation"] != generation)
            )
            if entry["live"]:
                reason = "SESSION_LIVE"
            elif entry["active"]:
                reason = "ACTIVE_READER_OR_WRITER"
            elif entry["claimed"]:
                reason = "SESSION_OPERATION_IN_PROGRESS"
            elif journal_repair:
                reason = "JOURNAL_REPAIR_REQUIRED"
            elif not media:
                reason = "CATALOG_CLEANUP_REQUIRED"
            else:
                reason = "RETRY_REQUIRED"  # an earlier removal error is not persisted
            sources = tuple(
                name for name, value in (("db", current), ("journal", published)) if value
            )
            items.append(
                {
                    "session_id": session_id,
                    "generation": generation,
                    "state": "DELETE_PENDING",
                    "deleted": False,
                    "db_status": current[1] if current else None,
                    "intent_sources": sources,
                    "session_present": session_present,
                    "media_present": media,
                    "live": entry["live"],
                    "active_reader_or_writer": entry["active"],
                    "reason": reason,
                    "repair_required": repair,
                }
            )
        return items

    def _media_present(self, session_id: str) -> bool:
        """Folder presence only. An uninspectable path is never reported as absent."""
        try:
            return safe_path(self.root, f"sessions/{session_id}").exists()
        except (ValueError, OSError):
            return True

    def _deletion_blocker(self, session_id: str, *, claimed: bool = False) -> str | None:
        """Root mutex held. Never stops a source or fabricates a reader ACK.

        claimed=True means the caller holds this session's claim itself.
        """
        if self._is_live(session_id):
            return "SESSION_LIVE"
        if self._active_jobs(session_id):
            return "ACTIVE_READER_OR_WRITER"
        if not claimed and session_id in self._claims:
            return "SESSION_OPERATION_IN_PROGRESS"
        return None

    @staticmethod
    def _intent_value(session_id: str, generation: int) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "session_id": session_id,
            "generation": generation,
            "state": "DELETE_REQUESTED",
        }

    def _stage_root_stamp(self) -> tuple[int, int, int]:
        status = os.stat(self.root)
        return status.st_dev, status.st_ino, status.st_mtime_ns

    def _inspect_staged_intents(self) -> tuple[tuple[int, int, int], int]:
        """Control lane only: preserve/quarantine incomplete protocol files in place.

        A verified provisional body can add a negative self fence, never positive
        authority. No cleanup, adoption or journal enumeration happens here.
        """
        with self._mutex:
            active, epoch = dict(self._staged_files), self._stage_epoch
            lifetimes = frozenset(self._staged_lifetimes)
        stamp = self._stage_root_stamp()
        incomplete = False
        for path in self.root.iterdir():
            match = re.fullmatch(
                r"\.deletion-(?:stage|atomic)-([0-9a-f]{32})\.json|\.tmp-([0-9a-f]{32})",
                path.name,
                flags=re.IGNORECASE | re.ASCII,
            )
            if match is None:
                continue
            registered = active.get(path)
            if (
                registered is not None
                and registered[0] == self._authority.instance
                and registered[1] == match.group(1)
                and registered[2] in lifetimes
            ):
                if registered[3] is None:
                    raise OSError("Deletion staging ownership pending")
                check_path(path)
                state = path.stat()
                if (state.st_dev, state.st_ino) == registered[3]:
                    continue
            incomplete = True
            try:
                value = read_json(path)
                schema(value)
                sid = identifier(value.get("session_id"))
                generation = integer(value.get("generation"), minimum=1)
                if value.get("state") != "DELETE_REQUESTED":
                    continue
            except (ValueError, OSError):
                continue  # unknown target; do not invent an identity or remove bytes
            with self._mutex:
                if generation > self._reserved_intents.get(sid, 0):
                    self._reserved_intents[sid] = generation
                    self._history_version += 1
        if incomplete:
            raise ValidationError("Incomplete deletion history")
        if stamp != self._stage_root_stamp():
            raise OSError("Deletion staging observation changed")
        with self._mutex:
            if epoch != self._stage_epoch:
                raise OSError("Deletion staging ownership changed")
        return stamp, epoch

    def _prepare_intent(self, staged: Path, temporary: Path, value: dict[str, Any]) -> None:
        """Owned atomic write with a known nonce; fsync and cleanup stay off root."""
        opened = False
        identity: tuple[int, int] | None = None
        try:
            with open_file(temporary, "xb") as stream:
                opened = True
                state = os.fstat(stream.fileno())
                identity = state.st_dev, state.st_ino
                with self._mutex:
                    registration = self._staged_files[temporary]
                    self._staged_files[temporary] = (
                        *registration[:3],
                        (state.st_dev, state.st_ino),
                    )
                    self._stage_epoch += 1
                _safe_io.write_all(stream, canonical(value) + b"\n")
                _safe_io.sync(stream)
            check_path(staged)
            if staged.exists():
                raise FileExistsError("Deletion stage already exists")
            os.replace(temporary, staged)
            with self._mutex:
                self._staged_files[staged] = self._staged_files[temporary]
                del self._staged_files[temporary]
                self._stage_epoch += 1
        finally:
            # This call still owns the exact xb file and registration. A killed
            # actor does not execute this; later inspectors never clean its orphan.
            if opened and temporary.exists():
                check_path(temporary)
                state = temporary.stat()
                if identity == (state.st_dev, state.st_ino):
                    temporary.unlink()

    def _publish_intent(
        self, session_id: str, generation: int, *, prepared_path: Path | None = None
    ) -> None:
        """Root held: publish one exact key, never copy the full authority map.

        Public deletion stages and fsyncs first, outside root. The optional direct
        form remains the low-level format-1 fault-injection seam used by existing
        storage tests; public deletion never performs that form under root.
        """
        self._history_version += 1
        try:
            stamp = self._journal_stamp()
        except (ValueError, OSError):
            stamp = None
        current = (
            stamp is not None and self._intent_stamp == stamp and self._intent_journal is not None
        )
        if stamp is None:
            self._authority.invalidate()
        else:
            self._observe_history_stamp(stamp)
        self._intent_failure = None
        self._observation_epoch += 1
        self._published_observation = self._observation_epoch
        intent = self._intent_value(session_id, generation)
        target = safe_path(self.root, f"deletion-journal/{session_id}.json")
        try:
            if prepared_path is None:
                atomic_json(target, intent)
            else:
                check_path(prepared_path)
                check_path(target)
                os.replace(prepared_path, target)
        except BaseException:
            self._intent_stamp = None
            self._authority.invalidate()
            raise
        self._authority.trusted_delta(
            session_id, HistoryEntry(generation, _history_digest(canonical(intent)).hexdigest())
        )
        self._authority_stamp = self._journal_stamp()
        self._authority_seen_stamp = self._authority_stamp
        if current and self._intent_journal is not None:
            self._intent_journal[session_id] = generation
            if not isinstance(self._intent_names, set):
                # Legacy test observations use frozen names; normal audits already
                # build this mutable capture-only name map outside root.
                self._intent_names = set(self._intent_names)
            self._intent_names.add(session_id + ".json")
            self._intent_stamp = self._authority_stamp
            self._intent_settled = False
        else:
            self._intent_stamp = None
        self._reserved_intents.pop(session_id, None)

    def _stage_intent(self, session_id: str, generation: int) -> None:
        """Caller owns this ID's publication lock; reserve before all media I/O."""
        nonce, token = uuid.uuid4().hex, object()
        staged = safe_path(self.root, ".deletion-stage-" + nonce + ".json")
        temporary = safe_path(self.root, ".deletion-atomic-" + nonce + ".json")
        with self._mutex:
            self._history_version += 1
            self._reserved_intents[session_id] = generation
            registration = (self._authority.instance, nonce, token, None)
            self._staged_files[staged] = self._staged_files[temporary] = registration
            self._staged_lifetimes.add(token)
            self._stage_epoch += 1
        try:
            self._prepare_intent(staged, temporary, self._intent_value(session_id, generation))
            with self._mutex:
                row = self._db.execute(
                    "SELECT generation FROM sessions WHERE session_id=?", (session_id,)
                ).fetchone()
                if row is not None and row[0] > generation:
                    raise StateConflict("DELETE_HISTORY_CONFLICT")
                self._publish_intent(session_id, generation, prepared_path=staged)
        finally:
            try:
                with self._mutex:
                    owned = self._staged_files.get(staged)
                if owned is not None and owned[2] is token and owned[3] is not None:
                    if staged.exists():
                        check_path(staged)
                        state = staged.stat()
                        if (state.st_dev, state.st_ino) == owned[3]:
                            staged.unlink()
            finally:
                with self._mutex:
                    for path in (staged, temporary):
                        owned = self._staged_files.get(path)
                        if owned is not None and owned[2] is token:
                            del self._staged_files[path]
                    self._staged_lifetimes.discard(token)
                    self._stage_epoch += 1

    def _deletion_complete(self, session_id: str, generation: int) -> bool:
        """Root mutex held: tombstone at generation, no catalog row and no folder."""
        current = self._db.execute(
            "SELECT generation,status FROM deleted_sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        if current is None or (current[0], current[1]) != (generation, "DELETED_LOCAL"):
            return False
        if self._db.execute("SELECT 1 FROM sessions WHERE session_id=?", (session_id,)).fetchone():
            return False
        return not self._media_present(session_id)

    def _journal_generation(self, session_id: str) -> int | None:
        path = safe_path(self.root, f"deletion-journal/{session_id}.json")
        if not path.exists():
            return None
        value = read_json(path)
        schema(value)
        if value.get("session_id") != session_id or value.get("state") != "DELETE_REQUESTED":
            raise ValidationError("Invalid deletion intent")
        return integer(value.get("generation"), minimum=1)

    @staticmethod
    def _pending_result(
        session_id: str, reason: str, generation: int, strict: bool
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "session_id": session_id,
            "state": "DELETE_PENDING",
            "deleted": False,
            "reason": reason,
        }
        if strict:
            result["generation"] = generation
        return result

    @staticmethod
    def _completed_result(
        session_id: str, generation: int, already: bool, strict: bool
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "session_id": session_id,
            "state": "DELETED_LOCAL",
            "deleted": True,
        }
        if strict:
            result.update(already_deleted=already, generation=generation)
        return result

    @staticmethod
    def _metadata_write(strict: bool, call: Callable[[], None]) -> None:
        """retry_deletion reports a failed record write as a closed, non-sensitive code."""
        try:
            call()
        except (OSError, sqlite3.Error):
            if not strict:
                raise  # delete_session keeps its historical storage exceptions
            raise ValidationError("DELETION_METADATA_PENDING") from None

    def _project_intent(self, session_id: str, generation: int) -> None:
        """Root mutex held: DB intent and catalog fence at g; a tombstone stays DELETED_LOCAL."""
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO deleted_sessions VALUES(?,?,'DELETE_PENDING') "
                "ON CONFLICT(session_id) DO UPDATE SET generation=excluded.generation",
                (session_id, generation),
            )
            connection.execute(
                "UPDATE sessions SET generation=? WHERE session_id=?", (generation, session_id)
            )
        state = self._db.execute(
            "SELECT generation,status FROM deleted_sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        assert state is not None
        self._authority.trusted_delta(
            session_id, HistoryEntry(db_generation=state[0], db_status=state[1])
        )

    def _project_intent_retry(self, session_id: str, generation: int) -> None:
        deadline = _registration_clock() + 5.0
        while True:
            with self._mutex:
                connection = self._db
                connection.execute("PRAGMA busy_timeout=0")
                try:
                    self._project_intent(session_id, generation)
                    return
                except sqlite3.OperationalError as error:
                    code = getattr(error, "sqlite_errorcode", None)
                    if (
                        type(code) is not int
                        or code & 0xFF not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
                        or _registration_clock() >= deadline
                    ):
                        raise
                finally:
                    connection.execute("PRAGMA busy_timeout=5000")
            _registration_wait(0.01)

    def _progress_deletion(
        self,
        session_id: str,
        *,
        expected_generation: int | None,
        create: bool,
        strict: bool,
    ) -> dict[str, Any]:
        """Shared deletion progression for delete_session and retry_deletion.

        Root mutex is held only for history checks, intent records and the final
        catalog commit. Folder removal runs under the session claim alone, so
        another session's capture writer is never blocked by it.
        """
        identifier(session_id)
        with self._mutex:
            publication = self._intent_publication_locks.setdefault(session_id, threading.RLock())
        # Never wait for another intent writer or fsync while holding root.
        with publication:
            with self._mutex:
                self._check_version()
                if self._history_conflict == session_id:
                    raise StateConflict("DELETE_HISTORY_CONFLICT")
                self._require_history()
                current, published = self._deletion_record(session_id)
                row = self._db.execute(
                    "SELECT generation FROM sessions WHERE session_id=?", (session_id,)
                ).fetchone()
                if current is None and published is None:
                    if not create:
                        return {"session_id": session_id, "state": "NOT_PENDING", "deleted": False}
                    if row is None:
                        return {"session_id": session_id, "state": "NOT_FOUND", "deleted": False}
                    generation = integer(row[0] + 1, minimum=1)
                else:
                    generation = max(current[0] if current else 0, published or 0)
                    if row is not None and row[0] > generation:
                        raise StateConflict("DELETE_HISTORY_CONFLICT")
                    if expected_generation is not None and expected_generation != generation:
                        raise StateConflict("STALE_DELETE_GENERATION")
                    if (
                        current == (generation, "DELETED_LOCAL")
                        and published == generation
                        and row is None
                        and not self._media_present(session_id)
                    ):
                        return self._completed_result(session_id, generation, True, strict)
                needs_journal = published != generation
                needs_db = (
                    current is None
                    or current[0] != generation
                    or row is not None
                    and row[0] != generation
                )
            if needs_journal:
                self._metadata_write(strict, lambda: self._stage_intent(session_id, generation))
            if needs_db:
                self._metadata_write(
                    strict, lambda: self._project_intent_retry(session_id, generation)
                )
            with self._mutex:
                blocker = self._deletion_blocker(session_id)
                if blocker is not None:
                    return self._pending_result(session_id, blocker, generation, strict)
        stale = False
        with self._session_operation(session_id):
            with self._mutex:
                # Recheck under the claim: another actor may have finished meanwhile.
                current = self._db.execute(
                    "SELECT generation FROM deleted_sessions WHERE session_id=?", (session_id,)
                ).fetchone()
                stale = current is None or current[0] != generation
                if not stale:
                    if self._deletion_complete(session_id, generation):
                        return self._completed_result(session_id, generation, True, strict)
                    blocker = self._deletion_blocker(session_id, claimed=True)
                    if blocker is not None:
                        return self._pending_result(session_id, blocker, generation, strict)
            if not stale:
                return self._remove_and_seal(session_id, generation, strict)
        # Raised after the claim so it is not reported as a plain DELETE_PENDING.
        raise StateConflict("STALE_DELETE_GENERATION")

    def _remove_and_seal(self, session_id: str, generation: int, strict: bool) -> dict[str, Any]:
        """Session claim held, root mutex not held: remove media, then commit the tombstone."""
        try:
            directory = safe_path(self.root, f"sessions/{session_id}")
            if directory.exists():
                remove_tree(directory)
        except (OSError, ValueError):
            # Partial removal stays partial; nothing is restored or reported complete.
            return self._pending_result(session_id, "MEDIA_REMOVAL_FAILED", generation, strict)
        try:
            published = self._journal_generation(session_id)
        except (ValueError, OSError):
            if strict:
                raise ValidationError(_HISTORY_UNAVAILABLE) from None
            raise
        with self._mutex:
            if published != generation:
                # Completion requires a valid minimal journal at g.
                return self._pending_result(
                    session_id, "JOURNAL_REPAIR_REQUIRED", generation, strict
                )
            if self._media_present(session_id):
                return self._pending_result(session_id, "RETRY_REQUIRED", generation, strict)

            def cleanup() -> None:
                with self._transaction() as connection:
                    connection.execute("DELETE FROM chunks WHERE session_id=?", (session_id,))
                    connection.execute(
                        "DELETE FROM storage_events WHERE session_id=?", (session_id,)
                    )
                    connection.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))
                    connection.execute(
                        "UPDATE deleted_sessions SET status='DELETED_LOCAL',generation=? "
                        "WHERE session_id=?",
                        (generation, session_id),
                    )
                    connection.execute(
                        "DELETE FROM storage_pending_deletions WHERE session_id=?", (session_id,)
                    )

            self._metadata_write(strict, cleanup)
            self._authority.trusted_delta(
                session_id, HistoryEntry(db_generation=generation, db_status="DELETED_LOCAL")
            )
        return self._completed_result(session_id, generation, False, strict)

    def _active_jobs(
        self, session_id: str | None = None, connection: sqlite3.Connection | None = None
    ) -> bool:
        db = self._db if connection is None else connection  # caller holds root_mutex
        exists = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='jobs'"
        ).fetchone()
        if not exists:
            return False
        bindings = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='job_sessions'"
        ).fetchone()
        if bindings and session_id is not None:
            readers = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='job_local_readers'"
            ).fetchone()
            if readers:
                scope = "(job_sessions.session_id IS NULL OR job_sessions.session_id=?)"
                if (
                    db.execute(
                        "SELECT 1 FROM jobs LEFT JOIN job_sessions USING(job_id) "
                        "JOIN job_local_readers USING(job_id) WHERE job_local_readers.active=1 "
                        "AND " + scope + " LIMIT 1",
                        (session_id,),
                    ).fetchone()
                    is not None
                ):
                    return True
                return (
                    db.execute(
                        "SELECT 1 FROM jobs LEFT JOIN job_sessions USING(job_id) "
                        "LEFT JOIN job_local_readers USING(job_id) "
                        "WHERE jobs.state NOT IN ('SUCCEEDED','FAILED','CANCELLED') "
                        "AND " + scope + " AND (jobs.state!='BLOCKED' "
                        "OR job_sessions.session_id IS NULL OR job_local_readers.active IS NULL "
                        "OR job_local_readers.active!=0) LIMIT 1",
                        (session_id,),
                    ).fetchone()
                    is not None
                )
            # Unbound legacy work still fails closed. A known independent session
            # cannot keep this session's deletion pending forever.
            return (
                db.execute(
                    "SELECT 1 FROM jobs LEFT JOIN job_sessions USING(job_id) "
                    "WHERE jobs.state NOT IN ('SUCCEEDED','FAILED','CANCELLED') "
                    "AND (job_sessions.session_id IS NULL OR job_sessions.session_id=?) LIMIT 1",
                    (session_id,),
                ).fetchone()
                is not None
            )
        # Legacy stores cannot identify the source media of an active job.
        return (
            db.execute(
                "SELECT 1 FROM jobs WHERE state NOT IN ('SUCCEEDED','FAILED','CANCELLED') LIMIT 1"
            ).fetchone()
            is not None
        )

    def close(self) -> None:
        # Writers fall back to the durable check once this Library is gone.
        unregister_intent_check(self.root, self._append_check)
        with self._mutex:
            retired = (self._intent_failure, self._intent_journal, self._journal_listing)
            self._authority.close()
            self._intent_failure = None
            self._intent_journal = None
            self._observation_epoch += 1
            self._published_observation = self._observation_epoch
            if self._job_authorities.get(self.db_path) is self:
                del self._job_authorities[self.db_path]
            try:
                if self._connection is not None:
                    self._connection.close()
            finally:
                self._connection = None
                if self._lock_file is not None:
                    stream, self._lock_file = self._lock_file, None
                    try:
                        stream.seek(0)
                        if sys.platform == "win32":
                            import msvcrt

                            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                        else:
                            import fcntl

                            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
                    finally:
                        stream.close()
        del retired  # Large index containers are released after root_mutex.

    def __enter__(self) -> Library:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
