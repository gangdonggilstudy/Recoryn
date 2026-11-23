"""SQLite-authoritative catalog, manifest projection and conservative recovery."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
import uuid
import weakref
from collections.abc import Iterator
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

from ._coordination import root_mutex
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
    has_active_writer,
    scan_prefix,
    verify_bundle,
)

_UNFINISHED = frozenset(
    {
        SessionState.CREATED,
        SessionState.RECORDING,
        SessionState.PAUSED,
        SessionState.FINALIZING,
        SessionState.INTERRUPTED,
    }
)


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

    def _deletion_intents(self) -> set[str]:
        if self._missing_deletion_history:
            raise ValidationError("Deletion history is unavailable")
        journal = safe_path(self.root, "deletion-journal")
        if not journal.is_dir():
            raise ValidationError("Deletion history is unavailable")
        intents = {row[0] for row in self._db.execute("SELECT session_id FROM deleted_sessions")}
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
            integer(value.get("generation"), minimum=1)
            if path.name != sid + ".json" or value.get("state") != "DELETE_REQUESTED":
                raise ValidationError("Invalid deletion intent")
            intents.add(sid)
        return intents

    def _live(self, session_id: str) -> None:
        identifier(session_id)
        if session_id in self._deletion_intents():
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
        with self._mutex:
            deleted = self._deletion_intents()
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
    ) -> bool:
        """Root mutex held: decide every refusal before publishing any claim."""
        if expected_version is not None:
            integer(expected_version)
        if session_id in self._deletion_intents():
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
            with self._mutex:
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

    def register_chunk(self, descriptor: ChunkDescriptor) -> None:
        # Hashing a sealed chunk must not stall another session's capture writer.
        path = safe_path(self.root, descriptor.relative_path)
        if verify_bundle(path) != descriptor:
            raise ValidationError("Catalog descriptor differs from verified bundle")
        with self._mutex:
            # Admission must never create an exclusive claim over a live
            # recorder. Even if that invariant is broken, preserve its writer.
            if not self._is_live(descriptor.session_id):
                self._check_claim(descriptor.session_id)
            self._live(descriptor.session_id)
            with self._transaction() as connection:
                existing = connection.execute(
                    "SELECT descriptor FROM chunks WHERE chunk_id=?", (descriptor.chunk_id,)
                ).fetchone()
                encoded = canonical(descriptor.to_dict()).decode("utf-8")
                if existing:
                    if existing[0] != encoded:
                        raise StateConflict("Conflicting chunk identity")
                    return
                session = self.get_session(descriptor.session_id)
                if session.state == SessionState.FINALIZED:
                    raise StateConflict("Finalized original list is immutable")
                for previous in self.chunks(descriptor.session_id):
                    if (
                        previous.track_id == descriptor.track_id
                        and previous.epoch_id == descriptor.epoch_id
                        and previous.first_sequence <= descriptor.last_sequence
                        and descriptor.first_sequence <= previous.last_sequence
                    ):
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
            with self._mutex:
                identifier(session_id)
                intents = self._deletion_intents()
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
        with self._mutex:
            deleted = self._deletion_intents()
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
            with self._mutex:
                identifier(session_id)
                if expected_version is not None:
                    integer(expected_version)
                if session_id in self._deletion_intents():
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
        with self._mutex:
            identifier(session_id)
            intents = self._deletion_intents()
            row = self._db.execute(
                "SELECT generation FROM sessions WHERE session_id=?", (session_id,)
            ).fetchone()
            if row is None and session_id not in intents:
                return {"session_id": session_id, "state": "NOT_FOUND", "deleted": False}
            self._check_version()
            path = safe_path(self.root, f"deletion-journal/{session_id}.json")
            if not path.exists():
                old_intent = self._db.execute(
                    "SELECT generation FROM deleted_sessions WHERE session_id=?", (session_id,)
                ).fetchone()
                atomic_json(
                    path,
                    {
                        "schema_version": 1,
                        "session_id": session_id,
                        "generation": max(row[0] if row else 0, old_intent[0] if old_intent else 0)
                        + 1,
                        "state": "DELETE_REQUESTED",
                    },
                )
            generation = read_json(path)["generation"]
            with self._transaction() as connection:
                connection.execute(
                    "INSERT INTO deleted_sessions VALUES(?,?,'DELETE_PENDING') "
                    "ON CONFLICT(session_id) DO UPDATE SET status='DELETE_PENDING'",
                    (session_id, generation),
                )
                connection.execute(
                    "UPDATE sessions SET generation=? WHERE session_id=?", (generation, session_id)
                )
            if session_id in self._claims:
                return {
                    "session_id": session_id,
                    "state": "DELETE_PENDING",
                    "deleted": False,
                    "reason": "SESSION_OPERATION_IN_PROGRESS",
                }
            if has_active_writer(self.root, session_id) or self._active_jobs(session_id):
                return {
                    "session_id": session_id,
                    "state": "DELETE_PENDING",
                    "deleted": False,
                    "reason": "ACTIVE_READER_OR_WRITER",
                }
        with self._session_operation(session_id):
            try:
                remove_tree(safe_path(self.root, f"sessions/{session_id}"))
            except (OSError, ValueError):
                return {
                    "session_id": session_id,
                    "state": "DELETE_PENDING",
                    "deleted": False,
                    "reason": "MEDIA_REMOVAL_FAILED",
                }
            with self._mutex:
                with self._transaction() as connection:
                    connection.execute("DELETE FROM chunks WHERE session_id=?", (session_id,))
                    connection.execute(
                        "DELETE FROM storage_events WHERE session_id=?", (session_id,)
                    )
                    connection.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))
                    connection.execute(
                        "UPDATE deleted_sessions SET status='DELETED_LOCAL' WHERE session_id=?",
                        (session_id,),
                    )
            return {"session_id": session_id, "state": "DELETED_LOCAL", "deleted": True}

    def _active_jobs(self, session_id: str | None = None) -> bool:
        exists = self._db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='jobs'"
        ).fetchone()
        if not exists:
            return False
        bindings = self._db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='job_sessions'"
        ).fetchone()
        if bindings and session_id is not None:
            readers = self._db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='job_local_readers'"
            ).fetchone()
            if readers:
                scope = "(job_sessions.session_id IS NULL OR job_sessions.session_id=?)"
                if (
                    self._db.execute(
                        "SELECT 1 FROM jobs LEFT JOIN job_sessions USING(job_id) "
                        "JOIN job_local_readers USING(job_id) WHERE job_local_readers.active=1 "
                        "AND " + scope + " LIMIT 1",
                        (session_id,),
                    ).fetchone()
                    is not None
                ):
                    return True
                return (
                    self._db.execute(
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
                self._db.execute(
                    "SELECT 1 FROM jobs LEFT JOIN job_sessions USING(job_id) "
                    "WHERE jobs.state NOT IN ('SUCCEEDED','FAILED','CANCELLED') "
                    "AND (job_sessions.session_id IS NULL OR job_sessions.session_id=?) LIMIT 1",
                    (session_id,),
                ).fetchone()
                is not None
            )
        # Legacy stores cannot identify the source media of an active job.
        return (
            self._db.execute(
                "SELECT 1 FROM jobs WHERE state NOT IN ('SUCCEEDED','FAILED','CANCELLED') LIMIT 1"
            ).fetchone()
            is not None
        )

    def close(self) -> None:
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
