"""Real SQLite persistence and controlled concurrent publication oracles."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import FrozenInstanceError
from pathlib import Path
from threading import Barrier
from typing import Any

import pytest

from recoryn.domain import StateConflict, ValidationError
from recoryn.jobs import AttemptState, JobState, JobStore


def test_records_and_context_lifecycle(tmp_path: Path) -> None:
    with JobStore(tmp_path / "library.sqlite") as store:
        job = store.create("STT", "input", "job")
        assert job.state == JobState.QUEUED
        with pytest.raises(FrozenInstanceError):
            job.state = JobState.RUNNING  # type: ignore[misc]
        attempt = store.claim("job", "worker")
        assert attempt.state == AttemptState.RUNNING and attempt.attempt_no == 1
        with pytest.raises(FrozenInstanceError):
            attempt.fence = 0  # type: ignore[misc]
    store.close()
    with pytest.raises(StateConflict):
        store.get("job")


def test_complete_then_cancel_is_idempotent_and_durable(tmp_path: Path) -> None:
    path = tmp_path / "library.sqlite"
    with JobStore(path) as store:
        store.create("STT", "input", "job")
        attempt = store.claim("job", "worker")
        completed = store.complete("job", attempt.attempt_id, attempt.fence, "result-1")
        assert store.cancel("job") == completed
        assert store.complete("job", attempt.attempt_id, attempt.fence, "result-1") == completed
        with pytest.raises(StateConflict):
            store.complete("job", attempt.attempt_id, attempt.fence, "different-result")
        assert store.create("STT", "input").job_id == "job"
    with JobStore(path) as reopened:
        assert reopened.get("job") == completed
        assert reopened.recover_abandoned() == []


def test_cancel_then_complete_rejects_old_publication_and_preserves_intent(tmp_path: Path) -> None:
    path = tmp_path / "library.sqlite"
    with JobStore(path) as store:
        store.create("STT", "input", "job")
        attempt = store.claim("job", "worker")
        cancelled = store.cancel("job")
        assert cancelled.state == JobState.CANCEL_REQUESTED
        assert cancelled.fence > attempt.fence and cancelled.cancel_requested
        assert store.cancel("job") == cancelled
        with pytest.raises(StateConflict):
            store.complete("job", attempt.attempt_id, attempt.fence, "late-result")
        with pytest.raises(StateConflict):
            store.fail("job", attempt.attempt_id, attempt.fence, "late-error", retryable=True)
    with JobStore(path) as reopened:
        assert reopened.recover_abandoned()[0].state == JobState.CANCELLED
        assert reopened.get("job").result_ref is None
        assert reopened.recover_abandoned() == []
        with pytest.raises(StateConflict):
            reopened.claim("job", "new-worker")


def test_cancel_queued_then_manual_new_job(tmp_path: Path) -> None:
    with JobStore(tmp_path / "library.sqlite") as store:
        job = store.create("STT", "input", "job")
        assert store.create("STT", "input", "other").job_id == job.job_id
        assert store.cancel("job").state == JobState.CANCELLED
        assert store.cancel("job").state == JobState.CANCELLED
        assert store.create("STT", "input").job_id != job.job_id
        assert store.create("STT", "input", "job").state == JobState.CANCELLED
        with pytest.raises(StateConflict):
            store.create("SUMMARY", "different", "job")


@pytest.mark.parametrize("terminal", ["cancel", "fail"])
def test_explicit_dedup_request_replay_remains_bound_after_terminal_and_restart(
    tmp_path: Path, terminal: str
) -> None:
    path = tmp_path / "library.sqlite"
    with JobStore(path) as first, JobStore(path) as second:
        original = first.create("STT", "input", "original")
        assert second.create("STT", "input", "request-id").job_id == original.job_id
        if terminal == "cancel":
            ended = first.cancel(original.job_id)
        else:
            attempt = first.claim(original.job_id, "worker")
            ended = first.fail(original.job_id, attempt.attempt_id, attempt.fence, "INPUT_INVALID")
        assert first.create("STT", "input", "request-id") == ended
        assert second.create("STT", "input", "request-id") == ended

    with JobStore(path) as restarted:
        assert restarted.create("STT", "input", "request-id") == ended
        with closing(sqlite3.connect(path)) as db:
            assert db.execute("SELECT COUNT(*) FROM jobs").fetchone() == (1,)
            before_events = db.execute("SELECT COUNT(*) FROM events").fetchone()
        assert restarted.create("STT", "input", "request-id") == ended
        with closing(sqlite3.connect(path)) as db:
            assert db.execute("SELECT COUNT(*) FROM events").fetchone() == before_events
        fresh = restarted.create("STT", "input", "explicit-new-run")
        assert fresh.job_id != original.job_id
        assert fresh.state == JobState.QUEUED
        # Historical receipts cannot silently attach to a later active run.
        assert restarted.create("STT", "input", "request-id") == ended
        for kind, key in (("STT", "different-input"), ("SUMMARY", "input")):
            with pytest.raises(StateConflict):
                restarted.create(kind, key, "request-id")
        with closing(sqlite3.connect(path)) as db:
            assert db.execute("SELECT COUNT(*) FROM jobs").fetchone() == (2,)


def test_competing_payloads_cannot_bind_the_same_dedup_request_identity(tmp_path: Path) -> None:
    path = tmp_path / "library.sqlite"
    with JobStore(path) as first, JobStore(path) as second:
        first.create("STT", "input-a", "original-a")
        first.create("SUMMARY", "input-b", "original-b")
        barrier = Barrier(2)

        def create_request(store: JobStore, kind: str, key: str) -> str:
            barrier.wait(timeout=5)
            try:
                return store.create(kind, key, "shared-request-id").job_id
            except StateConflict:
                return "conflict"

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(create_request, first, "STT", "input-a"),
                pool.submit(create_request, second, "SUMMARY", "input-b"),
            ]
            results = [future.result(timeout=10) for future in futures]
        assert results.count("conflict") == 1
        with closing(sqlite3.connect(path)) as db:
            assert db.execute("SELECT COUNT(*) FROM jobs").fetchone() == (2,)


def test_receipt_failure_does_not_accept_or_create_a_request(tmp_path: Path) -> None:
    path = tmp_path / "library.sqlite"
    with JobStore(path) as store:
        original = store.create("STT", "input", "original")
        with closing(sqlite3.connect(path)) as db, db:
            db.execute(
                "CREATE TRIGGER fail_receipt BEFORE INSERT ON job_create_receipts "
                "WHEN NEW.request_job_id='request-id' BEGIN SELECT RAISE(ABORT,'injected'); END"
            )
        with pytest.raises(sqlite3.IntegrityError):
            store.create("STT", "input", "request-id")
        assert store.get("original") == original
        with closing(sqlite3.connect(path)) as db, db:
            assert db.execute("SELECT COUNT(*) FROM jobs").fetchone() == (1,)
            assert (
                db.execute(
                    "SELECT job_id FROM job_create_receipts WHERE request_job_id='request-id'"
                ).fetchall()
                == []
            )
            db.execute("DROP TRIGGER fail_receipt")
        store.cancel("original")
        # A failed create was not acknowledged, so retry may make a new run.
        assert store.create("STT", "input", "request-id").job_id == "request-id"


def test_existing_concrete_job_id_backfills_receipt_without_changing_library_version(
    tmp_path: Path,
) -> None:
    path = tmp_path / "library.sqlite"
    with JobStore(path) as store:
        store.create("STT", "input", "legacy-job")
        ended = store.cancel("legacy-job")
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("DROP TABLE job_create_receipts")
        db.execute("PRAGMA user_version=1")
    with JobStore(path) as upgraded:
        assert upgraded.create("STT", "input", "legacy-job") == ended
        with pytest.raises(StateConflict):
            upgraded.create("SUMMARY", "input", "legacy-job")
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("PRAGMA user_version").fetchone() == (1,)


def test_bounded_retries_keep_all_attempts_and_fence_old_results(tmp_path: Path) -> None:
    path = tmp_path / "library.sqlite"
    with JobStore(path) as store:
        store.create("STT", "input", "job")
        attempts = []
        for number in range(1, 4):
            attempt = store.claim("job", "worker")
            attempts.append(attempt)
            assert attempt.attempt_no == number
            job = store.fail("job", attempt.attempt_id, attempt.fence, "TEMPORARY", retryable=True)
            assert job.state == (JobState.FAILED if number == 3 else JobState.BACKOFF)
            with pytest.raises(StateConflict):
                store.complete("job", attempt.attempt_id, attempt.fence, "late")
        with pytest.raises(StateConflict):
            store.claim("job", "worker")
        assert len({a.attempt_id for a in attempts}) == 3
        assert len({a.fence for a in attempts}) == 3
        with closing(sqlite3.connect(path)) as db, db:
            assert db.execute("SELECT state FROM attempts ORDER BY attempt_no").fetchall() == [
                ("FAILED",),
                ("FAILED",),
                ("FAILED",),
            ]


def test_unknown_outcome_dominates_retry_and_survives_restart(tmp_path: Path) -> None:
    path = tmp_path / "library.sqlite"
    with JobStore(path) as store:
        store.create("SUMMARY", "input", "job")
        attempt = store.claim("job", "worker")
        job = store.fail(
            "job", attempt.attempt_id, attempt.fence, "TIMEOUT", retryable=True, outcome_known=False
        )
        assert job.state == JobState.BLOCKED and job.blocked_reason == "REMOTE_UNKNOWN"
        with pytest.raises(StateConflict):
            store.claim("job", "worker")
        assert store.cancel("job").state == JobState.BLOCKED
        assert store.get("job").cancel_requested
        assert store.cancel("job") == store.get("job")
    with JobStore(path) as reopened:
        assert reopened.recover_abandoned() == []
        assert reopened.get("job").state == JobState.BLOCKED
        with closing(sqlite3.connect(path)) as db, db:
            assert db.execute("SELECT state FROM attempts").fetchone() == ("UNKNOWN",)


def test_explicit_unknown_error_overrides_default_outcome_flag(tmp_path: Path) -> None:
    with JobStore(tmp_path / "library.sqlite") as store:
        store.create("SUMMARY", "input", "job")
        attempt = store.claim("job", "worker")
        result = store.fail(
            "job", attempt.attempt_id, attempt.fence, "REMOTE_OUTCOME_UNKNOWN", retryable=True
        )
        assert result.state == JobState.BLOCKED and result.blocked_reason == "REMOTE_UNKNOWN"
        with pytest.raises(StateConflict):
            store.claim("job", "retry-worker")


def test_abandoned_recovery_fences_previous_worker(tmp_path: Path) -> None:
    path = tmp_path / "library.sqlite"
    with JobStore(path) as first:
        first.create("STT", "input", "job")
        old = first.claim("job", "old-worker")
    with JobStore(path) as restarted:
        recovered = restarted.recover_abandoned()
        assert recovered[0].state == JobState.BLOCKED
        assert recovered[0].blocked_reason == "ABANDONED"
        assert restarted.recover_abandoned() == []
        current = restarted.claim("job", "new-worker")
        assert current.attempt_no == 2 and current.fence > old.fence
        with pytest.raises(StateConflict):
            restarted.complete("job", old.attempt_id, old.fence, "stale")
        assert (
            restarted.complete("job", current.attempt_id, current.fence, "new").result_ref == "new"
        )
        with closing(sqlite3.connect(path)) as db, db:
            assert db.execute("SELECT state FROM attempts ORDER BY attempt_no").fetchall() == [
                ("ABANDONED",),
                ("SUCCEEDED",),
            ]


def test_repeated_abandonment_is_bounded(tmp_path: Path) -> None:
    with JobStore(tmp_path / "library.sqlite") as store:
        store.create("STT", "input", "job")
        for _ in range(3):
            store.claim("job", "worker")
            store.recover_abandoned()
        assert store.get("job").state == JobState.FAILED
        with pytest.raises(StateConflict):
            store.claim("job", "worker")


def test_sqlite_schema_is_shared_without_owning_session_or_user_version(tmp_path: Path) -> None:
    path = tmp_path / "library.sqlite"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("PRAGMA user_version=1")
        db.execute("CREATE TABLE sessions(session_id TEXT PRIMARY KEY)")
        db.execute("INSERT INTO sessions VALUES('existing')")
    with JobStore(path) as store:
        store.create("STT", "input")
    with closing(sqlite3.connect(path)) as db, db:
        assert db.execute("PRAGMA user_version").fetchone() == (1,)
        assert db.execute("SELECT * FROM sessions").fetchall() == [("existing",)]
        assert db.execute("PRAGMA journal_mode").fetchone() == ("wal",)
        events = db.execute("SELECT state FROM events").fetchall()
        assert events == [("QUEUED",)]


def test_future_schema_rejected_without_changes(tmp_path: Path) -> None:
    path = tmp_path / "library.sqlite"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("PRAGMA user_version=2")
    with pytest.raises(ValidationError):
        JobStore(path)
    with closing(sqlite3.connect(path)) as db, db:
        assert db.execute("SELECT name FROM sqlite_master WHERE name='jobs'").fetchall() == []
        assert db.execute("PRAGMA user_version").fetchone() == (2,)


def test_two_connections_claim_and_complete_cancel_compete(tmp_path: Path) -> None:
    path = tmp_path / "library.sqlite"
    with JobStore(path) as first, JobStore(path) as second:
        first.create("STT", "input", "job")
        barrier = Barrier(2)

        def claim(store: JobStore) -> str:
            barrier.wait(timeout=5)
            try:
                return store.claim("job", "worker").attempt_id
            except StateConflict:
                return "conflict"

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(claim, (first, second)))
        assert results.count("conflict") == 1
        job = first.get("job")
        assert job.attempt_id is not None
        attempt_id = job.attempt_id
        barrier.reset()

        def complete() -> None:
            barrier.wait(timeout=5)
            try:
                first.complete("job", attempt_id, job.fence, "result")
            except StateConflict:
                pass

        def cancel() -> None:
            barrier.wait(timeout=5)
            second.cancel("job")

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(complete), pool.submit(cancel)]
            for future in futures:
                future.result(timeout=10)
        final = first.get("job")
        assert (final.state, final.result_ref) in {
            (JobState.SUCCEEDED, "result"),
            (JobState.CANCEL_REQUESTED, None),
        }


def test_event_insert_failure_rolls_back_result_and_attempt(tmp_path: Path) -> None:
    path = tmp_path / "library.sqlite"
    with JobStore(path) as store:
        store.create("STT", "input", "job")
        attempt = store.claim("job", "worker")
        before = store.get("job")
        with closing(sqlite3.connect(path)) as db, db:
            db.execute(
                "CREATE TRIGGER fail_event BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT,'injected'); END"
            )
        with pytest.raises(sqlite3.IntegrityError):
            store.complete("job", attempt.attempt_id, attempt.fence, "result")
        assert store.get("job") == before
        with closing(sqlite3.connect(path)) as db, db:
            assert db.execute("SELECT state, result_ref FROM attempts").fetchone() == (
                "RUNNING",
                None,
            )


@pytest.mark.parametrize("bad", [True, False, 0, -1, 1.0, "1", 2**63])
def test_fence_type_boundaries(tmp_path: Path, bad: Any) -> None:
    with JobStore(tmp_path / "library.sqlite") as store:
        store.create("STT", "input", "job")
        attempt = store.claim("job", "worker")
        with pytest.raises(ValidationError):
            store.complete("job", attempt.attempt_id, bad, "result")
        with pytest.raises(ValidationError):
            store.fail("job", attempt.attempt_id, bad, "ERROR")


def test_validation_and_missing_job(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        JobStore("not-a-Path")  # type: ignore[arg-type]
    with JobStore(tmp_path / "library.sqlite") as store:
        for method in (store.get, store.cancel):
            with pytest.raises(KeyError):
                method("missing")
        with pytest.raises(ValidationError):
            store.create("", "input")
        with pytest.raises(ValidationError):
            store.create("STT", "\x00")
        store.create("STT", "input", "job")
        attempt = store.claim("job", "worker")
        with pytest.raises(ValidationError):
            store.fail("job", attempt.attempt_id, attempt.fence, "ERROR", retryable=1)  # type: ignore[arg-type]
        with pytest.raises(ValidationError):
            store.fail("job", attempt.attempt_id, attempt.fence, "ERROR", outcome_known=0)  # type: ignore[arg-type]
