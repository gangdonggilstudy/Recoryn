"""SQLite-authoritative catalog, manifest projection and conservative recovery."""

from __future__ import annotations

import os
import sqlite3
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import TracebackType
from typing import Any, BinaryIO

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
from .chunks import ChunkDescriptor, ChunkWriter, has_active_writer, scan_prefix, verify_bundle


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

    def create_session(self, session_id: str) -> Session:
        with self._mutex:
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

    def transition(self, session_id: str, target: SessionState, expected_version: int) -> Session:
        with self._mutex:
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
        with self._mutex:
            self._live(descriptor.session_id)
            path = safe_path(self.root, descriptor.relative_path)
            if verify_bundle(path) != descriptor:
                raise ValidationError("Catalog descriptor differs from verified bundle")
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
            descriptors = [
                ChunkDescriptor.from_dict(strict_json(row[0].encode("utf-8")))
                for row in self._db.execute(
                    "SELECT descriptor FROM chunks WHERE session_id=? ORDER BY rowid", (session_id,)
                )
            ]
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
        session = self.get_session(session_id)
        descriptors = self.chunks(session_id)
        for descriptor in descriptors:
            if verify_bundle(safe_path(self.root, descriptor.relative_path)) != descriptor:
                raise ValidationError("Catalog media changed")
        row = self._db.execute(
            "SELECT generation FROM sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        return {
            "schema_version": 1,
            "session_id": session_id,
            "state": session.state.value,
            "state_version": session.state_version,
            "generation": row[0],
            "chunks": [descriptor.to_dict() for descriptor in descriptors],
            "chunk_count": len(descriptors),
            "frame_count": sum(descriptor.frame_count for descriptor in descriptors),
            "capture_health": self.capture_health(session_id),
        }

    def write_manifest(self, session_id: str) -> dict[str, Any]:
        with self._mutex:
            self._check_version()
            manifest = self._manifest(session_id)
            path = safe_path(self.root, f"sessions/{session_id}/manifest.json")
            if path.exists():
                try:
                    existing_manifest = read_json(path, limit=8 * 1024 * 1024)
                except ValidationError:
                    # Repair only this DB projection, never a deletion journal.
                    # Preserve the malformed original under a unique local ID.
                    quarantine = safe_path(self.root, f"sessions/{session_id}/quarantine")
                    mkdir(quarantine)
                    path.rename(quarantine / ("manifest-" + uuid.uuid4().hex + ".json"))
                else:
                    schema(existing_manifest)  # Valid future versions remain untouched.
            atomic_json(path, manifest)
            with self._transaction() as connection:
                connection.execute(
                    "UPDATE sessions SET manifest_sync_pending=0 "
                    "WHERE session_id=? AND generation=?",
                    (session_id, manifest["generation"]),
                )
            return manifest

    def finalize_session(self, session_id: str) -> dict[str, Any]:
        with self._mutex:
            if has_active_writer(self.root, session_id):
                raise StateConflict("Writer has not drained")
            manifest = self._manifest(session_id)
            with self._transaction() as connection:
                session = self.get_session(session_id)
                if session.state != SessionState.FINALIZED:
                    changed = transition_session(
                        session, SessionState.FINALIZED, session.state_version
                    )
                    connection.execute(
                        "UPDATE sessions SET state=?,state_version=?,finalized_chunks=?,"
                        "generation=generation+1,manifest_sync_pending=1 WHERE session_id=?",
                        (
                            changed.state.value,
                            changed.state_version,
                            canonical(manifest["chunks"]).decode("utf-8"),
                            session_id,
                        ),
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

    def _salvage(self, session_id: str, staging: Path) -> tuple[ChunkDescriptor, bool]:
        descriptor_path = staging / "descriptor.json"
        check_path(descriptor_path)
        if descriptor_path.exists():
            schema(read_json(descriptor_path))
        prefix = scan_prefix(staging)
        first = prefix.blocks[0]["metadata"]
        if first["session_id"] != session_id:
            raise ValidationError("Staging session identity mismatch")
        # Source ID plus verified content/metadata produces an idempotent new ID.
        recovery_id = (
            "recovered-"
            + sha256(
                canonical(
                    {"source": staging.name, "records": prefix.blocks, "sha256": prefix.sha256}
                )
            )[:40]
        )
        target = safe_path(
            self.root,
            f"sessions/{session_id}/tracks/{first['track_id']}/{first['epoch_id']}/{recovery_id}",
        )
        if target.exists():
            existing = verify_bundle(target)
            if (existing.sha256, existing.byte_count) != (prefix.sha256, prefix.byte_count):
                raise ValidationError("Recovery identity conflict")
            return existing, prefix.complete
        with open_file(staging / "audio.pcm", "rb") as source:
            initial = PCMBlock.from_metadata(first, source.read(prefix.blocks[0]["length"]))
            writer = ChunkWriter(self.root, initial, recovery_id)
            # A killed salvage attempt must not block retries or become a new
            # independent original staging source. Keep work outside that scan.
            writer.staging_path = safe_path(
                self.root, f"sessions/{session_id}/recovery-work/{uuid.uuid4().hex}"
            )
            try:
                writer.append(initial)
                for record in prefix.blocks[1:]:
                    writer.append(
                        PCMBlock.from_metadata(record["metadata"], source.read(record["length"]))
                    )
                return writer.seal(), prefix.complete
            finally:
                writer.abort()

    def recover_session(self, session_id: str) -> dict[str, Any]:
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
                }
            if has_active_writer(self.root, session_id):
                raise StateConflict("Live writer cannot be recovered")
            try:
                session = self.get_session(session_id)
            except KeyError:
                session_root = safe_path(self.root, f"sessions/{session_id}")
                if not session_root.is_dir():
                    raise
                session = self.create_session(session_id)
            result: dict[str, Any] = {
                "session_id": session_id,
                "adopted": 0,
                "recovered": 0,
                "quarantined": 0,
                "warnings": [],
                "state": session.state.value,
            }
            known = {descriptor.chunk_id: descriptor for descriptor in self.chunks(session_id)}
            discovered: set[str] = set()
            for path in self._bundle_paths(session_id):
                try:
                    descriptor = verify_bundle(path)
                    discovered.add(descriptor.chunk_id)
                    if descriptor.chunk_id in known:
                        if descriptor != known[descriptor.chunk_id]:
                            raise ValidationError("Catalog mismatch")
                        continue
                    if session.state == SessionState.FINALIZED:
                        result["quarantined"] += 1
                        result["warnings"].append("FINALIZED_ORPHAN")
                        continue
                    self.register_chunk(descriptor)
                    known[descriptor.chunk_id] = descriptor
                    result["adopted"] += 1
                except (ValueError, OSError):
                    result["quarantined"] += 1
                    result["warnings"].append("INVALID_BUNDLE")
            for chunk_id in set(known) - discovered:
                result["warnings"].append("MISSING_OR_INVALID_CATALOG_MEDIA:" + chunk_id)
            staging_root = safe_path(self.root, f"sessions/{session_id}/staging")
            if staging_root.exists():
                for path in list(staging_root.iterdir()):
                    try:
                        check_path(path)
                        identifier(path.name)
                        if session.state == SessionState.FINALIZED:
                            result["quarantined"] += 1
                            result["warnings"].append("FINALIZED_STAGING")
                            continue
                        recovered, complete_prefix = self._salvage(session_id, path)
                        if not complete_prefix:
                            result["warnings"].append("STAGING_TAIL_NOT_ADOPTED")
                        if recovered.chunk_id not in known:
                            self.register_chunk(recovered)
                            known[recovered.chunk_id] = recovered
                            result["recovered"] += 1
                    except (ValueError, OSError):
                        result["quarantined"] += 1
                        result["warnings"].append("INVALID_STAGING")
            if session.state in (SessionState.RECORDING, SessionState.FINALIZING):
                session = self.transition(
                    session_id, SessionState.INTERRUPTED, session.state_version
                )
            result["state"] = session.state.value
            try:
                self.write_manifest(session_id)
            except (OSError, ValueError, sqlite3.Error):
                result["warnings"].append("MANIFEST_SYNC_PENDING")
                with self._transaction() as connection:
                    connection.execute(
                        "UPDATE sessions SET manifest_sync_pending=1 WHERE session_id=?",
                        (session_id,),
                    )
            return result

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
            if has_active_writer(self.root, session_id) or self._active_jobs(session_id):
                return {
                    "session_id": session_id,
                    "state": "DELETE_PENDING",
                    "deleted": False,
                    "reason": "ACTIVE_READER_OR_WRITER",
                }
            try:
                remove_tree(safe_path(self.root, f"sessions/{session_id}"))
            except (OSError, ValueError):
                return {
                    "session_id": session_id,
                    "state": "DELETE_PENDING",
                    "deleted": False,
                    "reason": "MEDIA_REMOVAL_FAILED",
                }
            with self._transaction() as connection:
                connection.execute("DELETE FROM chunks WHERE session_id=?", (session_id,))
                connection.execute("DELETE FROM storage_events WHERE session_id=?", (session_id,))
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
