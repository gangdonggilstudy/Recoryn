"""SQLite-authoritative catalog, manifest projection and conservative recovery."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
import time
import uuid
import weakref
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
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

from ._coordination import register_intent_check, root_mutex, unregister_intent_check
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


class LiveOwner(Protocol):
    """An in-process owner, such as a recording service, that may still write a session."""

    def is_live(self) -> bool: ...


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

    def __init__(self, root: Path) -> None:
        self.root = root_path(root)
        self._mutex = root_mutex(self.root)
        self._lock_file: BinaryIO | None = None
        self._connection: sqlite3.Connection | None = None
        self._live_owners: dict[str, dict[int, weakref.ref[LiveOwner]]] = {}
        self._session_locks: dict[str, Any] = {}
        self._claims: dict[str, int] = {}
        self._exclusive_claims: set[str] = set()
        # Bumped under root_mutex before this Library writes a deletion journal,
        # so a journal read outside the mutex can be validated cheaply.
        self._history_version = 0
        # Validated journal (session -> generation) and the journal directory stamp
        # it was read at. Updated in the same root_mutex section that publishes an
        # intent; any other change to the directory forces a full re-validation.
        self._intent_journal: dict[str, int] | None = None
        self._intent_stamp: tuple[int, int, int] | None = None
        self._intent_names: frozenset[str] = frozenset()  # entry names the index implies
        self._intent_settled = False  # a settled listing at _intent_stamp matched them
        # Capture-path listing (stamp, names, unfinished, settled) while the index is
        # not current. It never opens an entry.
        self._journal_listing: _Listing | None = None
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
                PRAGMA user_version=1;
                COMMIT;
            """)
            if not self._missing_deletion_history:
                mkdir(journal)
        except BaseException:
            self.close()
            raise
        with self._mutex:
            try:
                self._refresh_intent_index()  # once at open; no other thread waits yet
            except (ValueError, OSError):
                self._intent_journal = None  # every intent query fails closed until valid
        register_intent_check(self.root, self._append_check)

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
        journal = safe_path(self.root, "deletion-journal")
        if not journal.is_dir():
            raise ValidationError(_HISTORY_UNAVAILABLE)
        entries: dict[str, int] = {}
        for path in journal.iterdir():
            check_path(path)
            if path.name.startswith(".tmp-"):
                # An uncommitted intent cannot safely be interpreted as absence.
                raise ValidationError("Incomplete deletion history")
            if not path.is_file() or path.suffix != ".json":
                raise ValidationError("Unrecognized deletion history")
            value = read_json(path)
            schema(value)
            sid = identifier(value.get("session_id"))
            generation = integer(value.get("generation"), minimum=1)
            if path.name != sid + ".json" or value.get("state") != "DELETE_REQUESTED":
                raise ValidationError("Invalid deletion intent")
            entries[sid] = generation
        return entries

    def _journal_prefetch(self) -> tuple[int, dict[str, int] | None]:
        """Read the journal outside root_mutex; _deletion_history re-reads if it changed."""
        with self._mutex:
            version = self._history_version
        try:
            return version, self._read_journal()
        except (ValueError, OSError):
            return version, None  # the locked re-read reports the failure

    def _journal_stamp(self) -> tuple[int, int, int]:
        status = os.stat(safe_path(self.root, "deletion-journal"))
        return (status.st_dev, status.st_ino, status.st_mtime_ns)

    def _list_journal(self, stamp: tuple[int, int, int]) -> tuple[frozenset[str], bool]:
        """Root mutex held: entry names (no entry is opened) and whether stamp settled."""
        observed = time.time_ns()
        journal = safe_path(self.root, "deletion-journal")
        check_path(journal)
        with os.scandir(journal) as entries:
            names = frozenset(entry.name for entry in entries)
        settled = observed - stamp[2] > _STAMP_SETTLE_NS and self._journal_stamp() == stamp
        return names, settled

    def _set_index(self, journal: dict[str, int], stamp: tuple[int, int, int]) -> None:
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
        before = self._journal_stamp()
        journal = self._read_journal()
        if self._journal_stamp() != before:
            raise ValidationError(_HISTORY_UNAVAILABLE)  # changed while reading
        self._set_index(journal, before)
        return journal

    def _indexed_journal(self) -> dict[str, int]:
        """Root mutex held: the validated journal, re-read only when its entries changed.

        A new .tmp, an unknown entry or an added or removed intent changes the entry
        names, so it is always re-validated in full (fail closed).
        """
        try:
            if self._missing_deletion_history:
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
                names = self._writer_names()
                row = connection.execute(
                    "SELECT 1 FROM deleted_sessions WHERE session_id=?", (session_id,)
                ).fetchone()
            except ValidationError as exc:
                if exc.args == ("Incomplete deletion intent",):
                    raise
                raise ValidationError("Cannot verify writer deletion intent") from None
            except (ValueError, OSError, sqlite3.Error):
                raise ValidationError("Cannot verify writer deletion intent") from None
            return f"{session_id}.json" in names or row is not None

    def _writer_names(self) -> frozenset[str]:
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

    def _append_check(self, session_id: str) -> bool | None:
        """_coordination callback; None once closed, so the writer checks durably."""
        with self._mutex:
            if self._connection is None:
                return None
            return self._writer_intent(session_id)

    def _deletion_history(
        self, prefetched: tuple[int, dict[str, int] | None] | None = None
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
                journal = prefetched[1] if prefetched[0] == self._history_version else None
                if journal is None:
                    journal = self._read_journal()  # re-read so the failure is reported
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
        self, prefetched: tuple[int, dict[str, int] | None] | None = None
    ) -> set[str]:
        rows, journal = self._deletion_history(prefetched)
        return set(rows) | set(journal)

    def _live(self, session_id: str) -> None:
        """Root mutex held: refuse a session with a deletion intent, in O(1).

        Uses the stamp-checked journal index and this session's DB record only, so
        frequent calls (get_session, chunks, create_session) no longer read every
        journal file under the mutex. History that cannot be validated fails closed.
        """
        identifier(session_id)
        self._db  # noqa: B018 - a closed Library reports itself, not a history error
        try:
            intent = session_id in self._indexed_journal() or self._db_intent(session_id)
        except (ValueError, OSError, sqlite3.Error):
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

    def list_sessions(self) -> list[Session]:
        # Full journal validation on every call, read outside the root mutex.
        prefetched = self._journal_prefetch()
        with self._mutex:
            deleted = self._deletion_intents(prefetched)
            return [
                Session(row[0], SessionState(row[1]), row[2])
                for row in self._db.execute(
                    "SELECT session_id,state,state_version FROM sessions ORDER BY session_id"
                )
                if row[0] not in deleted
            ]

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
        prefetched: tuple[int, dict[str, int] | None] | None = None,
    ) -> bool:
        """Root mutex held: decide every refusal before publishing any claim."""
        if expected_version is not None:
            integer(expected_version)
        if session_id in self._deletion_intents(prefetched):
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
    ) -> Iterator[None]:
        """Serialize one session without holding the capture writer's root mutex."""
        identifier(session_id)
        with self._mutex:
            lock = self._session_locks.setdefault(session_id, threading.RLock())
        # Waiting is deliberately outside root_mutex. Nested recovery/manifest
        # operations on the same thread retain the original claim.
        with lock:
            # Admission validates the whole journal, read outside the root mutex.
            prefetched = self._journal_prefetch() if admission is not None else None
            with self._mutex:
                nested = session_id in self._claims
                admitted = admission is None or self._admit_session(
                    session_id, admission, expected_version, prefetched
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
                    deleted = session_id in self._deletion_intents()
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
        verified and uses the management deletion check, as before.
        """
        sealed = issued_descriptor(descriptor, self.root)
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
        with self._mutex:
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

    @staticmethod
    def _check_sealed_identity(path: Path, descriptor: ChunkDescriptor) -> None:
        """The bundle a sealer just published is still that bundle (no re-hash)."""
        expected = canonical(descriptor.to_dict()) + b"\n"
        with open_file(path / "descriptor.json", "rb") as stream:
            if stream.read(len(expected) + 1) != expected:
                raise ValidationError("Sealed chunk changed before registration")
        with open_file(path / "audio.pcm", "rb") as stream:
            if os.fstat(stream.fileno()).st_size != descriptor.byte_count:
                raise ValidationError("Sealed chunk changed before registration")

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
        with self._mutex:
            self._check_claim(session_id)
            self.get_session(session_id)
            encoded = canonical(health)
            strict_json(encoded)
            # Metadata size is bounded; callers must only supply the health DTO,
            # never audio, secrets or free-form provider exception bodies.
            with self._transaction() as connection:
                connection.execute(
                    "UPDATE sessions SET capture_health=?,generation=generation+1,"
                    "manifest_sync_pending=1 WHERE session_id=?",
                    (encoded.decode("utf-8"), session_id),
                )

    def capture_health(self, session_id: str) -> dict[str, Any]:
        with self._mutex:
            self.get_session(session_id)
            row = self._db.execute(
                "SELECT capture_health FROM sessions WHERE session_id=?", (session_id,)
            ).fetchone()
            return strict_json(row[0].encode("utf-8"))

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

    def finalize_session(self, session_id: str) -> dict[str, Any]:
        with self._session_operation(session_id, admission="seal"):
            with self._mutex:
                if self._is_live(session_id):
                    raise StateConflict("Writer has not drained")
            manifest = self._manifest(session_id)
            encoded = canonical(manifest["chunks"]).decode("utf-8")
            with self._mutex:
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
                # This private recovery writer is exclusively protected by the
                # session claim, including against delete's file removal. Its
                # fsync/hash work must not acquire the capture root mutex.
                with self._mutex:
                    self._live(session_id)
                writer._append(initial)
                for record in prefix.blocks[1:]:
                    with self._mutex:
                        self._live(session_id)
                    writer._append(
                        PCMBlock.from_metadata(record["metadata"], source.read(record["length"]))
                    )
                with self._mutex:
                    self._live(session_id)
                return writer._seal(), prefix.complete, tail
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

    def recover_session(self, session_id: str) -> dict[str, Any]:
        with self._session_operation(session_id, admission="recover"):
            prefetched = self._journal_prefetch()
            with self._mutex:
                identifier(session_id)
                intents = self._deletion_intents(prefetched)
                if session_id in intents:
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
        prefetched = self._journal_prefetch()
        with self._mutex:
            deleted = self._deletion_intents(prefetched)
            rows = self._db.execute(
                "SELECT session_id,state,state_version FROM sessions ORDER BY session_id"
            ).fetchall()
            snapshots: list[tuple[str, str, int, set[str], bool]] = []
            for session_id, state, version in rows:
                if session_id in deleted or SessionState(state) not in _UNFINISHED:
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
            prefetched = self._journal_prefetch()
            with self._mutex:
                identifier(session_id)
                if expected_version is not None:
                    integer(expected_version)
                if session_id in self._deletion_intents(prefetched):
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
                    "previous_state": previous_state,
                    "recovery": recovery,
                    "chunk_count": len(sealed_list),
                    "frame_count": sum(int(item["frame_count"]) for item in sealed_list),
                    "manifest_sync_pending": bool(sealed_row[1]),
                }
            if expected_version is not None and expected_version != previous_version:
                raise StateConflict("STALE_SESSION_VERSION")
            recovery = self.recover_session(session_id)
            session = self.get_session(session_id)
            if session.state != SessionState.FINALIZING:
                self.transition(session_id, SessionState.FINALIZING, session.state_version)
            sealed = self.finalize_session(session_id)
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
        prefetched = self._journal_prefetch()
        with self._mutex:
            rows, journal = self._deletion_history(prefetched)
            if session_id not in rows and session_id not in journal:
                return None
            return max(rows.get(session_id, (0, ""))[0], journal.get(session_id, 0))

    def pending_deletions(self) -> list[dict[str, Any]]:
        """Read-only inventory of durable deletion intents requiring completion or repair.

        DB rows, journal and catalog generations are one observation under root_mutex;
        in-process owner/reader flags are read in short bounded batches and folder
        presence outside the mutex. Nothing is repaired, removed or ACKed. History
        corruption raises ValidationError and a newer catalog generation raises
        StateConflict DELETE_HISTORY_CONFLICT; neither becomes an empty list.
        """
        prefetched = self._journal_prefetch()
        observed: list[dict[str, Any]] = []
        with self._mutex:
            self._check_version()
            rows, journal = self._deletion_history(prefetched)
            identities = sorted(set(rows) | set(journal))
            connection = self._db
            catalog: dict[str, int] = {}
            for start in range(0, len(identities), 500):
                part = identities[start : start + 500]
                marks = ",".join("?" * len(part))
                catalog.update(
                    connection.execute(
                        f"SELECT session_id,generation FROM sessions WHERE session_id IN ({marks})",  # noqa: S608
                        part,
                    ).fetchall()
                )
            for session_id in identities:
                current = rows.get(session_id)
                published = journal.get(session_id)
                generation = max(current[0] if current else 0, published or 0)
                if catalog.get(session_id, 0) > generation:
                    raise StateConflict("DELETE_HISTORY_CONFLICT")
                observed.append(
                    {
                        "session_id": session_id,
                        "generation": generation,
                        "current": current,
                        "published": published,
                        "session_generation": catalog.get(session_id),
                    }
                )
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

    def _publish_intent(self, session_id: str, generation: int) -> None:
        """Root mutex held: atomically publish the minimal journal intent at generation.

        The journal index is updated in this same root_mutex section, so no append,
        seal or registration can pass its deletion check between the published
        intent and the index (I1). The index is invalid while the file is written;
        a failed write leaves it invalid and the next query re-validates in full.
        """
        self._history_version += 1
        try:
            current = self._index_current()
        except (ValueError, OSError):
            current = False
        snapshot = dict(self._intent_journal) if current and self._intent_journal else {}
        self._intent_journal = None
        atomic_json(
            safe_path(self.root, f"deletion-journal/{session_id}.json"),
            {
                "schema_version": 1,
                "session_id": session_id,
                "generation": generation,
                "state": "DELETE_REQUESTED",
            },
        )
        if current:
            snapshot[session_id] = generation
            try:
                # Not settled: the next query lists the entry names once more.
                self._set_index(snapshot, self._journal_stamp())
            except OSError:
                pass  # stays invalid; the next query re-validates

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
        prefetched = self._journal_prefetch()
        with self._mutex:
            self._check_version()
            rows, journal = self._deletion_history(prefetched)
            row = self._db.execute(
                "SELECT generation FROM sessions WHERE session_id=?", (session_id,)
            ).fetchone()
            current = rows.get(session_id)
            published = journal.get(session_id)
            if current is None and published is None:
                if not create:
                    return {"session_id": session_id, "state": "NOT_PENDING", "deleted": False}
                if row is None:
                    return {"session_id": session_id, "state": "NOT_FOUND", "deleted": False}
                generation = integer(row[0] + 1, minimum=1)
                self._publish_intent(session_id, generation)
                self._project_intent(session_id, generation)
            else:
                # Existing intent: keep the maximum valid generation, never a new one.
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
                # Both minimal intents and the catalog fence reach g before removal.
                if published != generation:
                    self._metadata_write(
                        strict, lambda: self._publish_intent(session_id, generation)
                    )
                if (
                    current is None
                    or current[0] != generation
                    or (row is not None and row[0] != generation)
                ):
                    self._metadata_write(
                        strict, lambda: self._project_intent(session_id, generation)
                    )
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
        with self._mutex:
            try:
                published = self._journal_generation(session_id)
            except (ValueError, OSError):
                if strict:
                    raise ValidationError(_HISTORY_UNAVAILABLE) from None
                raise
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

            self._metadata_write(strict, cleanup)
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

    def __enter__(self) -> Library:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
