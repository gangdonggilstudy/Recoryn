"""Durable local jobs. No model execution or remote requests are performed."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from threading import RLock
from uuid import uuid4

from recoryn.domain import StateConflict, ValidationError
from recoryn.jobs.failures import BLOCK_REASONS, CODE_GROUPS, failure_decision

__all__ = ["AttemptRecord", "AttemptState", "JobRecord", "JobState", "JobStore"]


class JobState(StrEnum):
    QUEUED = "QUEUED"
    BLOCKED = "BLOCKED"
    RUNNING = "RUNNING"
    BACKOFF = "BACKOFF"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class AttemptState(StrEnum):
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    ABANDONED = "ABANDONED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class JobRecord:
    job_id: str
    kind: str
    input_key: str
    state: JobState
    fence: int
    attempt_count: int
    attempt_id: str | None
    owner: str | None
    result_ref: str | None
    error_code: str | None
    blocked_reason: str | None
    cancel_requested: bool
    state_version: int


@dataclass(frozen=True, slots=True)
class AttemptRecord:
    job_id: str
    attempt_id: str
    attempt_no: int
    state: AttemptState
    fence: int
    owner: str
    result_ref: str | None = None
    error_code: str | None = None


def _text(value: object, name: str, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value or len(value) > maximum:
        raise ValidationError(f"{name} must be a nonempty string of at most {maximum} characters")
    return value


def _fence(value: object) -> int:
    if type(value) is not int or not 0 < value < 2**63:
        raise ValidationError("fence must be a positive SQLite integer")
    return value


class JobStore:
    """SQLite-linearized Job/Attempt state, with at most three local attempts.

    Mutating state transitions return JobRecord; claim returns AttemptRecord,
    recovery returns affected JobRecords, reader/intent writes return None and
    local_reader_active returns bool or unknown(None). Missing IDs raise KeyError.
    Stale execution tokens raise StateConflict. Cancellation is a durable request,
    not a worker kill.
    Recovery must only be invoked by the sole restarting coordinator after all
    previous workers have stopped; it does not infer owner liveness from a PID.
    Explicit create job_id values are durable request identities: deduplication
    may return another Job, but replay always resolves to that original Job.
    """

    MAX_ATTEMPTS = 3

    def __init__(self, db_path: Path) -> None:
        if not isinstance(db_path, Path):
            raise ValidationError("db_path must be a Path")
        self._lock = RLock()
        self._closed = False
        self._in_publication = False
        self._db_path = db_path.absolute()
        self._db = sqlite3.connect(
            db_path, timeout=5.0, isolation_level=None, check_same_thread=False
        )
        self._db.row_factory = sqlite3.Row
        try:
            version = self._db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise ValidationError("unsupported library schema version")
            self._db.execute("PRAGMA foreign_keys=ON")
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=FULL")
            self._db.executescript("""
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY, kind TEXT NOT NULL, input_key TEXT NOT NULL,
                    state TEXT NOT NULL, fence INTEGER NOT NULL DEFAULT 0,
                    attempt_count INTEGER NOT NULL DEFAULT 0, attempt_id TEXT, owner TEXT,
                    result_ref TEXT, error_code TEXT, blocked_reason TEXT,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    state_version INTEGER NOT NULL DEFAULT 0
                );
                CREATE UNIQUE INDEX IF NOT EXISTS jobs_dedup
                    ON jobs(kind, input_key) WHERE state NOT IN ('FAILED', 'CANCELLED');
                CREATE TABLE IF NOT EXISTS attempts (
                    attempt_id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(job_id),
                    attempt_no INTEGER NOT NULL, state TEXT NOT NULL, fence INTEGER NOT NULL,
                    owner TEXT NOT NULL, result_ref TEXT, error_code TEXT,
                    UNIQUE(job_id, attempt_no)
                );
                CREATE TABLE IF NOT EXISTS events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL REFERENCES jobs(job_id),
                    attempt_id TEXT, state TEXT NOT NULL, fence INTEGER NOT NULL,
                    state_version INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS job_create_receipts (
                    request_job_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL REFERENCES jobs(job_id)
                );
                INSERT OR IGNORE INTO job_create_receipts(request_job_id, job_id)
                    SELECT job_id, job_id FROM jobs;
                CREATE TABLE IF NOT EXISTS job_sessions (
                    job_id TEXT PRIMARY KEY REFERENCES jobs(job_id), session_id TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS job_session_lookup ON job_sessions(session_id);
                CREATE TABLE IF NOT EXISTS job_local_readers (
                    job_id TEXT PRIMARY KEY REFERENCES jobs(job_id),
                    attempt_id TEXT NOT NULL REFERENCES attempts(attempt_id),
                    fence INTEGER NOT NULL CHECK(fence > 0),
                    active INTEGER NOT NULL CHECK(active IN (0,1))
                );
                CREATE TABLE IF NOT EXISTS job_remote_intents (
                    attempt_id TEXT NOT NULL REFERENCES attempts(attempt_id),
                    reservation_id TEXT NOT NULL, job_id TEXT NOT NULL REFERENCES jobs(job_id),
                    fence INTEGER NOT NULL CHECK(fence > 0),
                    PRIMARY KEY(attempt_id,reservation_id)
                );
                COMMIT;
            """)
        except BaseException:
            self._db.close()
            self._closed = True
            raise

    def __enter__(self) -> JobStore:
        self._ensure_open()
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _ensure_open(self) -> None:
        if self._closed:
            raise StateConflict("JobStore is closed")
        if self._in_publication:
            raise StateConflict("Job publication callbacks cannot reenter JobStore")

    def close(self) -> None:
        with self._lock:
            if self._in_publication:
                raise StateConflict("Job publication callbacks cannot close JobStore")
            if not self._closed:
                self._db.close()
                self._closed = True

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        with self._lock:
            self._ensure_open()
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise

    @contextmanager
    def _session_transaction(self, job_id: str, *, acknowledgement: bool = False) -> Iterator[bool]:
        # Copy immutable binding before asking storage for authority: root -> Job
        # ordering, never Job transaction/lock -> journal I/O/root mutex.
        with self._lock:
            self._ensure_open()
            row = self._db.execute(
                "SELECT session_id FROM job_sessions WHERE job_id=?", (job_id,)
            ).fetchone()
            session_id = row[0] if row is not None else None
            library_schema = self._db.execute("PRAGMA user_version").fetchone()[0] != 0

        @contextmanager
        def transaction(valid: bool) -> Iterator[bool]:
            with self._transaction():
                current = self._db.execute(
                    "SELECT session_id FROM job_sessions WHERE job_id=?", (job_id,)
                ).fetchone()
                if (current[0] if current is not None else None) != session_id:
                    raise StateConflict("JOB_VERSION_CHANGED")
                yield valid

        if session_id is None or not library_schema:
            # Standalone Job databases retain their existing DB-only contract.
            with transaction(True) as valid:
                yield valid
            return
        from recoryn.storage import Library

        with Library.job_authority(self._db_path, session_id) as authority:
            valid = authority == "VALID"
            if not acknowledgement and not valid:
                code = (
                    "DELETION_HISTORY_UNAVAILABLE"
                    if authority == "HISTORY_UNAVAILABLE"
                    else "JOB_SESSION_MISSING"
                    if authority == "MISSING"
                    else "JOB_SESSION_DELETED"
                )
                raise StateConflict(code)
            with transaction(valid) as valid:
                yield valid
                if not acknowledgement:
                    Library.assert_job_authority_current(self._db_path, session_id)

    def _get(self, job_id: str) -> JobRecord:
        row = self._db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return JobRecord(
            job_id=row["job_id"],
            kind=row["kind"],
            input_key=row["input_key"],
            state=JobState(row["state"]),
            fence=row["fence"],
            attempt_count=row["attempt_count"],
            attempt_id=row["attempt_id"],
            owner=row["owner"],
            result_ref=row["result_ref"],
            error_code=row["error_code"],
            blocked_reason=row["blocked_reason"],
            cancel_requested=bool(row["cancel_requested"]),
            state_version=row["state_version"],
        )

    def get(self, job_id: str) -> JobRecord:
        _text(job_id, "job_id", 128)
        with self._lock:
            self._ensure_open()
            return self._get(job_id)

    def _event(self, job_id: str) -> JobRecord:
        job = self._get(job_id)
        self._db.execute(
            "INSERT INTO events(job_id, attempt_id, state, fence, state_version) VALUES(?,?,?,?,?)",
            (job_id, job.attempt_id, job.state.value, job.fence, job.state_version),
        )
        return job

    def create(self, kind: str, input_key: str, job_id: str | None = None) -> JobRecord:
        _text(kind, "kind", 128)
        _text(input_key, "input_key")
        if job_id is not None:
            _text(job_id, "job_id", 128)
        with self._transaction():
            if job_id is not None:
                existing = self._db.execute(
                    "SELECT job_id FROM job_create_receipts WHERE request_job_id=?", (job_id,)
                ).fetchone()
                if existing is not None:
                    job = self._get(existing[0])
                    if (job.kind, job.input_key) != (kind, input_key):
                        raise StateConflict("create request identity already has different input")
                    return job
            duplicate = self._db.execute(
                "SELECT job_id FROM jobs WHERE kind=? AND input_key=? AND state NOT IN ('FAILED','CANCELLED')",
                (kind, input_key),
            ).fetchone()
            if duplicate is not None:
                job = self._get(duplicate[0])
                if job_id is not None:
                    self._db.execute(
                        "INSERT INTO job_create_receipts(request_job_id,job_id) VALUES(?,?)",
                        (job_id, job.job_id),
                    )
                return job
            new_id = job_id if job_id is not None else uuid4().hex
            self._db.execute(
                "INSERT INTO jobs(job_id,kind,input_key,state) VALUES(?,?,?,?)",
                (new_id, kind, input_key, JobState.QUEUED.value),
            )
            self._db.execute(
                "INSERT INTO job_create_receipts(request_job_id,job_id) VALUES(?,?)",
                (new_id, new_id),
            )
            return self._event(new_id)

    def claim(self, job_id: str, owner: str) -> AttemptRecord:
        _text(job_id, "job_id", 128)
        _text(owner, "owner", 256)
        with self._session_transaction(job_id):
            job = self._get(job_id)
            self._session_live(job_id)
            reader = self._db.execute(
                "SELECT active FROM job_local_readers WHERE job_id=?", (job_id,)
            ).fetchone()
            if reader is not None and reader[0]:
                raise StateConflict("LOCAL_READER_STILL_ACTIVE")
            claimable = job.state in (JobState.QUEUED, JobState.BACKOFF) or (
                job.state == JobState.BLOCKED and job.blocked_reason == "ABANDONED"
            )
            if not claimable or job.cancel_requested or job.attempt_count >= self.MAX_ATTEMPTS:
                raise StateConflict("job is not claimable")
            attempt = AttemptRecord(
                job_id,
                uuid4().hex,
                job.attempt_count + 1,
                AttemptState.RUNNING,
                job.fence + 1,
                owner,
            )
            self._db.execute(
                "INSERT INTO attempts(attempt_id,job_id,attempt_no,state,fence,owner) VALUES(?,?,?,?,?,?)",
                (
                    attempt.attempt_id,
                    job_id,
                    attempt.attempt_no,
                    attempt.state.value,
                    attempt.fence,
                    owner,
                ),
            )
            self._db.execute(
                "UPDATE jobs SET state='RUNNING', fence=?, attempt_count=?, attempt_id=?, owner=?, "
                "error_code=NULL, blocked_reason=NULL, state_version=state_version+1 WHERE job_id=?",
                (attempt.fence, attempt.attempt_no, attempt.attempt_id, owner, job_id),
            )
            self._db.execute(
                "INSERT INTO job_local_readers VALUES(?,?,?,0) ON CONFLICT(job_id) DO UPDATE SET "
                "attempt_id=excluded.attempt_id,fence=excluded.fence,active=0",
                (job_id, attempt.attempt_id, attempt.fence),
            )
            self._event(job_id)
            return attempt

    def _reader_identity(self, attempt: AttemptRecord) -> None:
        if not isinstance(attempt, AttemptRecord):
            raise ValidationError("READER_ATTEMPT_REQUIRED")
        _text(attempt.job_id, "job_id", 128)
        _text(attempt.attempt_id, "attempt_id", 128)
        _text(attempt.owner, "owner", 256)
        _fence(attempt.fence)
        if type(attempt.attempt_no) is not int or not 1 <= attempt.attempt_no <= self.MAX_ATTEMPTS:
            raise ValidationError("INVALID_READER_ATTEMPT_NUMBER")
        row = self._db.execute(
            "SELECT r.active FROM job_local_readers r JOIN attempts a "
            "ON a.attempt_id=r.attempt_id WHERE r.job_id=? AND r.attempt_id=? AND r.fence=? "
            "AND a.job_id=r.job_id AND a.fence=r.fence AND a.owner=? AND a.attempt_no=?",
            (attempt.job_id, attempt.attempt_id, attempt.fence, attempt.owner, attempt.attempt_no),
        ).fetchone()
        if row is None:
            raise StateConflict("STALE_LOCAL_READER")

    def reader_started(self, attempt: AttemptRecord) -> None:
        """Persist local-reader ownership before task I/O; cancellation/deletion win.

        Only one physical task may use the current attempt. This receipt is not
        a remote outcome and does not authorize publication or detached readers.
        """
        if not isinstance(attempt, AttemptRecord):
            raise ValidationError("READER_ATTEMPT_REQUIRED")
        with self._session_transaction(attempt.job_id):
            self._reader_identity(attempt)
            self._active(attempt.job_id, attempt.attempt_id, attempt.fence)
            self._db.execute(
                "UPDATE job_local_readers SET active=1 WHERE job_id=?", (attempt.job_id,)
            )

    def reader_finished(self, attempt: AttemptRecord) -> None:
        """Idempotent local I/O ACK after task exit, independent of logical fence.

        Cancel/failure can advance the Job fence while the original task is
        unwinding. Its immutable Attempt identity may ACK only its own receipt,
        including after session deletion. A replaced attempt may never ACK it.
        """
        with self._transaction():
            self._reader_identity(attempt)
            self._db.execute(
                "UPDATE job_local_readers SET active=0 WHERE job_id=?", (attempt.job_id,)
            )

    def local_reader_active(self, job_id: str) -> bool | None:
        """True=local reader alive, False=explicit inactive, None=legacy/unknown."""
        _text(job_id, "job_id", 128)
        with self._lock:
            self._ensure_open()
            self._get(job_id)
            row = self._db.execute(
                "SELECT active FROM job_local_readers WHERE job_id=?", (job_id,)
            ).fetchone()
            return bool(row[0]) if row is not None else None

    def mark_remote_intent(self, attempt: AttemptRecord, reservation_id: str) -> None:
        """Commit a reservation identity before any remote dispatch may occur.

        Store IDs only, never credentials, request/response bodies or endpoints.
        This conservative marker is not proof that bytes were sent. Recovery of
        its still-running attempt must preserve UNKNOWN rather than redispatch.
        Split requests can record multiple immutable reservation IDs per attempt.
        """
        _text(reservation_id, "reservation_id", 128)
        with self._transaction():
            self._reader_identity(attempt)
            self._active(attempt.job_id, attempt.attempt_id, attempt.fence)
            self._db.execute(
                "INSERT OR IGNORE INTO job_remote_intents VALUES(?,?,?,?)",
                (attempt.attempt_id, reservation_id, attempt.job_id, attempt.fence),
            )

    def cancel(self, job_id: str) -> JobRecord:
        _text(job_id, "job_id", 128)
        with self._transaction():
            job = self._get(job_id)
            if job.state in (
                JobState.SUCCEEDED,
                JobState.FAILED,
                JobState.CANCELLED,
                JobState.CANCEL_REQUESTED,
            ):
                return job
            if job.state == JobState.RUNNING:
                state = JobState.CANCEL_REQUESTED
            elif job.state == JobState.BLOCKED and job.blocked_reason == "REMOTE_UNKNOWN":
                if job.cancel_requested:
                    return job
                state = JobState.BLOCKED
            else:
                state = JobState.CANCELLED
            self._db.execute(
                "UPDATE jobs SET state=?, cancel_requested=1, fence=fence+1, "
                "state_version=state_version+1 WHERE job_id=?",
                (state.value, job_id),
            )
            return self._event(job_id)

    def block_pending(
        self, job_id: str, reason: str, error_code: str, *, expected_version: int
    ) -> JobRecord:
        """Record a known preparation refusal without inventing an Attempt."""
        _text(job_id, "job_id", 128)
        self._version(expected_version)
        if type(reason) is not str or reason not in BLOCK_REASONS:
            raise ValidationError("BLOCK_REASON_INVALID")
        if type(error_code) is not str or error_code not in CODE_GROUPS:
            raise ValidationError("BLOCK_REASON_INVALID")
        if CODE_GROUPS[error_code] != reason:
            raise ValidationError("BLOCK_REASON_MISMATCH")
        with self._session_transaction(job_id):
            job = self._get(job_id)
            self._session_live(job_id)
            if job.state_version != expected_version:
                raise StateConflict("JOB_VERSION_CHANGED")
            if job.state != JobState.QUEUED or job.cancel_requested:
                raise StateConflict("JOB_NOT_BLOCKABLE")
            self._reader_inactive(job)
            self._db.execute(
                "UPDATE jobs SET state='BLOCKED',blocked_reason=?,error_code=?,owner=NULL,"
                "fence=fence+1,state_version=state_version+1 WHERE job_id=?",
                (reason, error_code, job_id),
            )
            return self._event(job_id)

    @staticmethod
    def _version(value: object) -> None:
        if type(value) is not int or not 0 <= value < 2**63:
            raise ValidationError("INVALID_JOB_VERSION")

    def _reader_inactive(self, job: JobRecord) -> None:
        reader = self._db.execute(
            "SELECT active FROM job_local_readers WHERE job_id=?", (job.job_id,)
        ).fetchone()
        if (reader is not None and reader[0]) or (
            reader is None and (job.attempt_id is not None or job.attempt_count != 0)
        ):
            raise StateConflict("LOCAL_READER_ACK_REQUIRED")
        if job.attempt_id is not None:
            attempt = self._db.execute(
                "SELECT state FROM attempts WHERE attempt_id=? AND job_id=?",
                (job.attempt_id, job.job_id),
            ).fetchone()
            if attempt is None or attempt[0] == "RUNNING":
                raise StateConflict("LOCAL_READER_ACK_REQUIRED")

    def resume(self, job_id: str, *, expected_version: int | None = None) -> JobRecord:
        """Explicitly retry known blocked work after caller policy revalidation.

        This does not grant consent/budget or settle remote outcomes. UNKNOWN
        and unconfirmed cancellation are never cleared. A never-dispatched Job
        needs no reader ACK; a previous attempt requires an explicit inactive
        receipt. Attempts/checkpoints/history and the three-attempt cap remain.
        """
        _text(job_id, "job_id", 128)
        if expected_version is not None:
            self._version(expected_version)
        with self._session_transaction(job_id):
            job = self._get(job_id)
            self._session_live(job_id)
            if expected_version is not None and job.state_version != expected_version:
                raise StateConflict("JOB_VERSION_CHANGED")
            if (
                job.state != JobState.BLOCKED
                or job.blocked_reason
                not in {"CONSENT", "AUTH", "RESOURCE", "BUDGET", "CAPABILITY", "ABANDONED"}
                or job.cancel_requested
                or job.attempt_count >= self.MAX_ATTEMPTS
            ):
                raise StateConflict("JOB_NOT_RESUMABLE")
            self._reader_inactive(job)
            self._db.execute(
                "UPDATE jobs SET state='QUEUED',blocked_reason=NULL,error_code=NULL,owner=NULL, "
                "fence=fence+1,state_version=state_version+1 WHERE job_id=?",
                (job_id,),
            )
            return self._event(job_id)

    def _active(
        self, job_id: str, attempt_id: str, fence: int, *, check_session: bool = True
    ) -> JobRecord:
        job = self._get(job_id)
        if check_session:
            self._session_live(job_id)
        if (
            job.state != JobState.RUNNING
            or job.cancel_requested
            or job.attempt_id != attempt_id
            or job.fence != fence
        ):
            raise StateConflict("attempt is stale or no longer authorized to publish")
        return job

    def bind_session(self, job_id: str, session_id: str) -> None:
        """One immutable binding; terminal metadata survives session deletion."""
        _text(job_id, "job_id", 128)
        _text(session_id, "session_id", 128)
        with self._transaction():
            self._get(job_id)
            row = self._db.execute(
                "SELECT session_id FROM job_sessions WHERE job_id=?", (job_id,)
            ).fetchone()
            if row is not None:
                if row[0] != session_id:
                    raise StateConflict("JOB_SESSION_REBIND_FORBIDDEN")
                return
            self._db.execute("INSERT INTO job_sessions VALUES(?,?)", (job_id, session_id))
            self._session_live(job_id)

    def list_for_session(self, session_id: str) -> list[JobRecord]:
        _text(session_id, "session_id", 128)
        with self._lock:
            self._ensure_open()
            rows = self._db.execute(
                "SELECT j.job_id FROM jobs j JOIN job_sessions s "
                "ON j.job_id=s.job_id WHERE s.session_id=? ORDER BY j.rowid",
                (session_id,),
            ).fetchall()
            return [self._get(row[0]) for row in rows]

    def _session_live(self, job_id: str) -> None:
        row = self._db.execute(
            "SELECT session_id FROM job_sessions WHERE job_id=?", (job_id,)
        ).fetchone()
        if row is None:
            return
        tables = {
            r[0] for r in self._db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if (
            "deleted_sessions" in tables
            and self._db.execute(
                "SELECT 1 FROM deleted_sessions WHERE session_id=?", (row[0],)
            ).fetchone()
            is not None
        ):
            raise StateConflict("JOB_SESSION_DELETED")
        if (
            "sessions" in tables
            and self._db.execute("SELECT 1 FROM sessions WHERE session_id=?", (row[0],)).fetchone()
            is None
        ):
            raise StateConflict("JOB_SESSION_MISSING")

    def complete(self, job_id: str, attempt_id: str, fence: int, result_ref: str) -> JobRecord:
        _text(job_id, "job_id", 128)
        _text(attempt_id, "attempt_id", 128)
        _fence(fence)
        _text(result_ref, "result_ref")
        with self._lock:
            self._ensure_open()
            job = self._get(job_id)
            if (
                job.state == JobState.SUCCEEDED
                and job.attempt_id == attempt_id
                and job.fence == fence
                and job.result_ref == result_ref
            ):
                return job
        with self._session_transaction(job_id):
            job = self._get(job_id)
            if (
                job.state == JobState.SUCCEEDED
                and job.attempt_id == attempt_id
                and job.fence == fence
                and job.result_ref == result_ref
            ):
                return job
            self._active(job_id, attempt_id, fence)
            return self._finish(job_id, attempt_id, result_ref)

    def _finish(self, job_id: str, attempt_id: str, result_ref: str) -> JobRecord:
        self._db.execute(
            "UPDATE attempts SET state='SUCCEEDED', result_ref=? WHERE attempt_id=?",
            (result_ref, attempt_id),
        )
        self._db.execute(
            "UPDATE jobs SET state='SUCCEEDED', result_ref=?, owner=NULL, "
            "state_version=state_version+1 WHERE job_id=?",
            (result_ref, job_id),
        )
        return self._event(job_id)

    def complete_with(
        self,
        job_id: str,
        attempt_id: str,
        fence: int,
        publisher: Callable[[sqlite3.Connection], str],
    ) -> JobRecord:
        """Commit a trusted SQL-only publisher, result and terminal event atomically.

        The callback must not reenter stores, do external I/O, alter transaction
        boundaries or retain the connection. Python code is trusted, not sandboxed.
        Successful replay returns the committed result without calling it twice.
        """
        return self._publish_with(job_id, attempt_id, fence, publisher, complete=True)[0]

    @staticmethod
    def _publication_authorizer(
        action: int, name: str | None, value: str | None, database: str | None, trigger: str | None
    ) -> int:
        allowed = {
            sqlite3.SQLITE_SELECT,
            sqlite3.SQLITE_READ,
            sqlite3.SQLITE_INSERT,
            sqlite3.SQLITE_UPDATE,
            sqlite3.SQLITE_DELETE,
            sqlite3.SQLITE_FUNCTION,
            sqlite3.SQLITE_RECURSIVE,
        }
        protected = {
            "jobs",
            "attempts",
            "events",
            "job_sessions",
            "job_create_receipts",
            "job_checkpoints",
            "job_local_readers",
            "job_remote_intents",
            "sessions",
            "chunks",
            "storage_events",
            "deleted_sessions",
            "storage_visible_sessions",
            "storage_pending_deletions",
            "storage_catalog_meta",
        }
        if (
            action in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE)
            and name in protected
        ):
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_PRAGMA and name == "user_version" and value is None:
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY

    def _publish_with(
        self,
        job_id: str,
        attempt_id: str,
        fence: int,
        publisher: Callable[[sqlite3.Connection], str],
        *,
        complete: bool,
    ) -> tuple[JobRecord, str]:
        _text(job_id, "job_id", 128)
        _text(attempt_id, "attempt_id", 128)
        _fence(fence)
        if not callable(publisher) or type(complete) is not bool:
            raise ValidationError("Invalid Job publisher")
        with self._lock:
            self._ensure_open()
            job = self._get(job_id)
            if (
                complete
                and job.state == JobState.SUCCEEDED
                and job.attempt_id == attempt_id
                and job.fence == fence
                and job.result_ref is not None
            ):
                return job, job.result_ref
        with self._session_transaction(job_id):
            job = self._get(job_id)
            if (
                complete
                and job.state == JobState.SUCCEEDED
                and job.attempt_id == attempt_id
                and job.fence == fence
                and job.result_ref is not None
            ):
                return job, job.result_ref
            self._active(job_id, attempt_id, fence)
            self._in_publication = True
            self._db.set_authorizer(self._publication_authorizer)
            try:
                result_ref = publisher(self._db)
                _text(result_ref, "result_ref")
            finally:
                self._db.set_authorizer(None)
                self._in_publication = False
            self._active(job_id, attempt_id, fence)
            if complete:
                return self._finish(job_id, attempt_id, result_ref), result_ref
            # A checkpoint is discoverable after restart, but is not the final
            # Job result and does not confer permission to change active content.
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS job_checkpoints ("
                "job_id TEXT NOT NULL REFERENCES jobs(job_id), attempt_id TEXT NOT NULL, "
                "result_ref TEXT NOT NULL, UNIQUE(job_id,result_ref))"
            )
            self._db.execute(
                "INSERT OR IGNORE INTO job_checkpoints VALUES(?,?,?)",
                (job_id, attempt_id, result_ref),
            )
            self._db.execute(
                "UPDATE jobs SET state_version=state_version+1 WHERE job_id=?", (job_id,)
            )
            return self._event(job_id), result_ref

    def _ack_cancelled(self, attempt: AttemptRecord, *, outcome_known: bool = True) -> JobRecord:
        """Local worker acknowledged cancellation; never infer a remote abort."""
        with self._transaction():
            job = self._get(attempt.job_id)
            if (
                job.state != JobState.CANCEL_REQUESTED
                or job.attempt_id != attempt.attempt_id
                or job.fence != attempt.fence + 1
            ):
                return job
            self._db.execute(
                "UPDATE attempts SET state=? WHERE attempt_id=? AND state='RUNNING'",
                ("CANCELLED" if outcome_known else "UNKNOWN", attempt.attempt_id),
            )
            self._db.execute(
                "UPDATE jobs SET state=?, blocked_reason=?, owner=NULL, "
                "state_version=state_version+1 WHERE job_id=?",
                (
                    "CANCELLED" if outcome_known else "BLOCKED",
                    None if outcome_known else "REMOTE_UNKNOWN",
                    attempt.job_id,
                ),
            )
            return self._event(attempt.job_id)

    def fail(
        self,
        job_id: str,
        attempt_id: str,
        fence: int,
        error_code: str,
        retryable: bool = False,
        outcome_known: bool = True,
    ) -> JobRecord:
        _text(job_id, "job_id", 128)
        _text(attempt_id, "attempt_id", 128)
        _fence(fence)
        _text(error_code, "error_code", 128)
        if type(retryable) is not bool or type(outcome_known) is not bool:
            raise ValidationError("retryable and outcome_known must be bool")
        with self._session_transaction(job_id, acknowledgement=True) as authority_valid:
            # Retiring an authorized attempt writes no content. Permit failure
            # acknowledgement after deletion so cleanup cannot remain RUNNING.
            job = self._active(job_id, attempt_id, fence, check_session=False)
            session_valid = authority_valid
            try:
                self._session_live(job_id)
            except StateConflict:
                # Deletion outranks local retry, while remote UNKNOWN remains
                # UNKNOWN below until it can be reconciled without new dispatch.
                session_valid = False
            decision = failure_decision(
                error_code, retryable, outcome_known, job.attempt_count, session_valid=session_valid
            )
            state = JobState(decision.state)
            attempt_state = AttemptState(decision.attempt_state)
            reason = decision.blocked_reason
            self._db.execute(
                "UPDATE attempts SET state=?, error_code=? WHERE attempt_id=?",
                (attempt_state.value, error_code, attempt_id),
            )
            self._db.execute(
                "UPDATE jobs SET state=?, error_code=?, blocked_reason=?, owner=NULL, "
                "fence=fence+1, state_version=state_version+1 WHERE job_id=?",
                (state.value, error_code, reason, job_id),
            )
            return self._event(job_id)

    def recover_abandoned(self, *, coordinator_exclusive: bool = False) -> list[JobRecord]:
        """Recover logical work; only proven coordinator exclusivity clears readers.

        The caller must establish that all previous tasks/owned reader processes
        have exited. A flag is an explicit attestation, not an OS liveness probe.
        UNKNOWN outcomes remain UNKNOWN, even when local readers are released.
        Legacy receipts are made explicit only with that attestation.
        """
        if type(coordinator_exclusive) is not bool:
            raise ValidationError("INVALID_COORDINATOR_EXCLUSIVITY")
        recovered = []
        with self._transaction():
            if coordinator_exclusive:
                self._db.execute("UPDATE job_local_readers SET active=0 WHERE active=1")
                self._db.execute(
                    "INSERT OR IGNORE INTO job_local_readers "
                    "SELECT j.job_id,a.attempt_id,a.fence,0 FROM jobs j "
                    "JOIN attempts a ON a.attempt_id=j.attempt_id AND a.job_id=j.job_id"
                )
            elif (
                self._db.execute(
                    "SELECT 1 FROM job_local_readers WHERE active=1 LIMIT 1"
                ).fetchone()
                is not None
            ):
                raise StateConflict("LOCAL_READERS_REQUIRE_EXCLUSIVE_RECOVERY")
            rows = self._db.execute(
                "SELECT job_id FROM jobs WHERE state IN ('RUNNING','CANCEL_REQUESTED') ORDER BY job_id"
            ).fetchall()
            for row in rows:
                job = self._get(row[0])
                remote = (
                    self._db.execute(
                        "SELECT 1 FROM job_remote_intents WHERE job_id=? AND attempt_id=? LIMIT 1",
                        (job.job_id, job.attempt_id),
                    ).fetchone()
                    is not None
                )
                if remote:
                    state, attempt_state, reason = (
                        JobState.BLOCKED,
                        AttemptState.UNKNOWN,
                        "REMOTE_UNKNOWN",
                    )
                elif job.cancel_requested:
                    state, attempt_state, reason = JobState.CANCELLED, AttemptState.CANCELLED, None
                elif job.attempt_count >= self.MAX_ATTEMPTS:
                    state, attempt_state, reason = JobState.FAILED, AttemptState.ABANDONED, None
                else:
                    state, attempt_state, reason = (
                        JobState.BLOCKED,
                        AttemptState.ABANDONED,
                        "ABANDONED",
                    )
                self._db.execute(
                    "UPDATE attempts SET state=? WHERE attempt_id=? AND state='RUNNING'",
                    (attempt_state.value, job.attempt_id),
                )
                self._db.execute(
                    "UPDATE jobs SET state=?, blocked_reason=?, owner=NULL, fence=fence+1, "
                    "state_version=state_version+1 WHERE job_id=?",
                    (state.value, reason, job.job_id),
                )
                recovered.append(self._event(job.job_id))
        return recovered
