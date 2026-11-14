"""Durable local jobs. No model execution or remote requests are performed."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from threading import RLock
from uuid import uuid4

from recoryn.domain import StateConflict, ValidationError

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

    All methods except claim return JobRecord; recover_abandoned returns a list
    of affected JobRecords. Missing IDs raise KeyError. Stale execution tokens
    raise StateConflict. Cancellation is a durable request, not a worker kill.
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

    def close(self) -> None:
        with self._lock:
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
        with self._transaction():
            job = self._get(job_id)
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
            self._event(job_id)
            return attempt

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

    def _active(self, job_id: str, attempt_id: str, fence: int) -> JobRecord:
        job = self._get(job_id)
        if (
            job.state != JobState.RUNNING
            or job.cancel_requested
            or job.attempt_id != attempt_id
            or job.fence != fence
        ):
            raise StateConflict("attempt is stale or no longer authorized to publish")
        return job

    def complete(self, job_id: str, attempt_id: str, fence: int, result_ref: str) -> JobRecord:
        _text(job_id, "job_id", 128)
        _text(attempt_id, "attempt_id", 128)
        _fence(fence)
        _text(result_ref, "result_ref")
        with self._transaction():
            job = self._get(job_id)
            if (
                job.state == JobState.SUCCEEDED
                and job.attempt_id == attempt_id
                and job.fence == fence
                and job.result_ref == result_ref
            ):
                return job
            self._active(job_id, attempt_id, fence)
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
        with self._transaction():
            job = self._active(job_id, attempt_id, fence)
            if not outcome_known or error_code == "REMOTE_OUTCOME_UNKNOWN":
                state, attempt_state, reason = (
                    JobState.BLOCKED,
                    AttemptState.UNKNOWN,
                    "REMOTE_UNKNOWN",
                )
            else:
                state = (
                    JobState.BACKOFF
                    if retryable and job.attempt_count < self.MAX_ATTEMPTS
                    else JobState.FAILED
                )
                attempt_state, reason = AttemptState.FAILED, None
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

    def recover_abandoned(self) -> list[JobRecord]:
        """Explicit sole-coordinator recovery; never invoke while workers are alive."""
        recovered = []
        with self._transaction():
            rows = self._db.execute(
                "SELECT job_id FROM jobs WHERE state IN ('RUNNING','CANCEL_REQUESTED') ORDER BY job_id"
            ).fetchall()
            for row in rows:
                job = self._get(row[0])
                if job.cancel_requested:
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
