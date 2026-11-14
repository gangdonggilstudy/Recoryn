"""Real SQLite persistence and controlled concurrent publication oracles."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import FrozenInstanceError, replace
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


@pytest.mark.parametrize(
    "violation", ["raise", "commit", "savepoint", "reenter", "close", "attach", "control"]
)
def test_atomic_callback_rolls_back_and_rejects_boundary_violation(
    tmp_path: Path, violation: str
) -> None:
    path = tmp_path / "library.sqlite"
    with JobStore(path) as jobs:
        job = jobs.create("STT", "input")
        attempt = jobs.claim(job.job_id, "worker")
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("CREATE TABLE callback_values(value TEXT)")

        def publisher(connection: sqlite3.Connection) -> str:
            connection.execute("INSERT INTO callback_values VALUES('candidate')")
            if violation == "raise":
                raise RuntimeError("safe injected failure")
            if violation == "commit":
                connection.commit()
            elif violation == "savepoint":
                connection.execute("SAVEPOINT invalid")
            elif violation == "reenter":
                jobs.get(job.job_id)
            elif violation == "close":
                jobs.close()
            elif violation == "control":
                connection.execute("UPDATE jobs SET fence=fence+1 WHERE job_id=?", (job.job_id,))
            else:
                connection.execute("ATTACH DATABASE ':memory:' AS forbidden")
            return "result"

        with pytest.raises((RuntimeError, sqlite3.DatabaseError, StateConflict)):
            jobs.complete_with(job.job_id, attempt.attempt_id, attempt.fence, publisher)
        assert jobs.get(job.job_id).state == JobState.RUNNING
        with closing(sqlite3.connect(path)) as db:
            assert db.execute("SELECT COUNT(*) FROM callback_values").fetchone() == (0,)
        assert (
            jobs.complete_with(
                job.job_id, attempt.attempt_id, attempt.fence, lambda db: "good"
            ).result_ref
            == "good"
        )


def test_session_binding_is_immutable_durable_and_preserves_terminal_metadata(
    tmp_path: Path,
) -> None:
    from recoryn.storage import Library

    with Library(tmp_path) as library, JobStore(library.db_path) as jobs:
        library.create_session("first")
        library.create_session("second")
        job = jobs.create("STT", "input")
        jobs.bind_session(job.job_id, "first")
        jobs.bind_session(job.job_id, "first")
        with pytest.raises(StateConflict):
            jobs.bind_session(job.job_id, "second")
        assert jobs.list_for_session("second") == []
        assert jobs.list_for_session("first") == [job]
        cancelled = jobs.cancel(job.job_id)
        assert library.delete_session("first")["deleted"] is True
        jobs.bind_session(job.job_id, "first")
        assert jobs.list_for_session("first") == [cancelled]
    with JobStore(tmp_path / "library.sqlite") as reopened:
        assert reopened.list_for_session("first") == [cancelled]
        with pytest.raises(StateConflict):
            reopened.bind_session(job.job_id, "second")


def test_new_binding_and_dispatch_to_deleted_or_missing_session_are_denied(tmp_path: Path) -> None:
    from recoryn.storage import Library

    with Library(tmp_path) as library, JobStore(library.db_path) as jobs:
        library.create_session("deleted")
        job = jobs.create("STT", "input")
        jobs.bind_session(job.job_id, "deleted")
        library.delete_session("deleted")
        with pytest.raises(StateConflict):
            jobs.claim(job.job_id, "worker")
        jobs.cancel(job.job_id)
        assert library.delete_session("deleted")["deleted"] is True
        other = jobs.create("STT", "other-input")
        for invalid in ("deleted", "missing"):
            with pytest.raises(StateConflict):
                jobs.bind_session(other.job_id, invalid)
        assert jobs.list_for_session("missing") == []
        with pytest.raises(KeyError):
            jobs.bind_session("missing-job", "deleted")


def test_atomic_publisher_input_and_result_validation(tmp_path: Path) -> None:
    with JobStore(tmp_path / "library.sqlite") as jobs:
        job = jobs.create("STT", "input")
        attempt = jobs.claim(job.job_id, "worker")
        with pytest.raises(ValidationError):
            jobs.complete_with(job.job_id, attempt.attempt_id, attempt.fence, None)  # type: ignore[arg-type]
        with pytest.raises(ValidationError):
            jobs.complete_with(job.job_id, attempt.attempt_id, attempt.fence, lambda db: True)  # type: ignore[arg-type,return-value]
        assert jobs.get(job.job_id).state == JobState.RUNNING


def test_deleted_session_blocks_publication_but_allows_failure_ack(tmp_path: Path) -> None:
    from recoryn.storage import Library

    with Library(tmp_path) as library, JobStore(library.db_path) as jobs:
        library.create_session("session")
        job = jobs.create("STT", "input")
        jobs.bind_session(job.job_id, "session")
        attempt = jobs.claim(job.job_id, "worker")
        assert not library.delete_session("session")["deleted"]
        with pytest.raises(StateConflict):
            jobs.complete(job.job_id, attempt.attempt_id, attempt.fence, "late")
        ended = jobs.fail(
            job.job_id, attempt.attempt_id, attempt.fence, "SESSION_DELETED", retryable=True
        )
        assert ended.state == JobState.FAILED and ended.result_ref is None
        assert library.delete_session("session")["deleted"]


@pytest.mark.parametrize("ending", ["success", "failed", "unknown", "cancel_unknown"])
def test_local_reader_ack_is_persistent_and_separate_from_logical_outcome(
    tmp_path: Path, ending: str
) -> None:
    path = tmp_path / "library.sqlite"
    with JobStore(path) as first, JobStore(path) as second:
        job = first.create("STT", "input")
        assert first.local_reader_active(job.job_id) is None
        attempt = first.claim(job.job_id, "worker")
        assert second.local_reader_active(job.job_id) is False
        first.reader_started(attempt)
        first.reader_started(attempt)
        assert second.local_reader_active(job.job_id) is True
        if ending == "success":
            ended = first.complete(job.job_id, attempt.attempt_id, attempt.fence, "result")
        elif ending == "cancel_unknown":
            first.cancel(job.job_id)
            ended = first._ack_cancelled(attempt, outcome_known=False)
        else:
            ended = first.fail(
                job.job_id,
                attempt.attempt_id,
                attempt.fence,
                "FAILURE",
                outcome_known=ending != "unknown",
            )
        assert second.local_reader_active(job.job_id) is True
    with JobStore(path) as restarted:
        assert restarted.local_reader_active(job.job_id) is True
        restarted.reader_finished(attempt)
        restarted.reader_finished(attempt)
        assert restarted.local_reader_active(job.job_id) is False
        assert restarted.get(job.job_id) == ended
        with pytest.raises(StateConflict):
            restarted.reader_started(attempt)
        if ending in ("unknown", "cancel_unknown"):
            assert ended.state == JobState.BLOCKED and ended.blocked_reason == "REMOTE_UNKNOWN"
            with closing(sqlite3.connect(path)) as db:
                assert db.execute("SELECT state FROM attempts").fetchone()[0] == "UNKNOWN"


def test_reader_ack_cannot_clear_replacement_attempt_and_retry_waits_for_exit(
    tmp_path: Path,
) -> None:
    with JobStore(tmp_path / "library.sqlite") as jobs:
        job = jobs.create("STT", "input")
        old = jobs.claim(job.job_id, "worker")
        jobs.reader_started(old)
        jobs.fail(job.job_id, old.attempt_id, old.fence, "TEMPORARY", retryable=True)
        with pytest.raises(StateConflict, match="LOCAL_READER_STILL_ACTIVE"):
            jobs.claim(job.job_id, "another")
        jobs.reader_finished(old)
        new = jobs.claim(job.job_id, "another")
        jobs.reader_started(new)
        with pytest.raises(StateConflict, match="STALE_LOCAL_READER"):
            jobs.reader_finished(old)
        assert jobs.local_reader_active(job.job_id) is True
        jobs.reader_finished(new)


def test_live_reader_recovery_requires_explicit_exclusivity_and_preserves_unknown(
    tmp_path: Path,
) -> None:
    path = tmp_path / "library.sqlite"
    with JobStore(path) as jobs:
        first = jobs.create("STT", "one")
        active = jobs.claim(first.job_id, "old")
        jobs.reader_started(active)
        unknown_job = jobs.create("STT", "two")
        unknown = jobs.claim(unknown_job.job_id, "old")
        jobs.reader_started(unknown)
        before = jobs.fail(
            unknown_job.job_id,
            unknown.attempt_id,
            unknown.fence,
            "REMOTE_OUTCOME_UNKNOWN",
            outcome_known=False,
        )
    with JobStore(path) as restarted:
        with pytest.raises(StateConflict, match="EXCLUSIVE_RECOVERY"):
            restarted.recover_abandoned()
        assert restarted.get(first.job_id).state == JobState.RUNNING
        assert restarted.local_reader_active(unknown_job.job_id) is True
        recovered = restarted.recover_abandoned(coordinator_exclusive=True)
        assert [record.job_id for record in recovered] == [first.job_id]
        assert restarted.local_reader_active(first.job_id) is False
        assert restarted.local_reader_active(unknown_job.job_id) is False
        assert restarted.get(unknown_job.job_id) == before
        newer = restarted.claim(first.job_id, "new")
        restarted.reader_started(newer)
        with pytest.raises(StateConflict):
            restarted.reader_finished(active)
        assert restarted.local_reader_active(first.job_id) is True
        restarted.reader_finished(newer)


def test_legacy_unknown_reader_is_unknown_until_exclusive_recovery(tmp_path: Path) -> None:
    path = tmp_path / "library.sqlite"
    with JobStore(path) as jobs:
        job = jobs.create("STT", "legacy")
        attempt = jobs.claim(job.job_id, "old")
        jobs.fail(job.job_id, attempt.attempt_id, attempt.fence, "UNKNOWN", outcome_known=False)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("DROP TABLE job_local_readers")
    with JobStore(path) as restarted:
        assert restarted.local_reader_active(job.job_id) is None
        assert restarted.recover_abandoned() == []
        assert restarted.local_reader_active(job.job_id) is None
        assert restarted.recover_abandoned(coordinator_exclusive=True) == []
        assert restarted.local_reader_active(job.job_id) is False
        assert restarted.get(job.job_id).state == JobState.BLOCKED


@pytest.mark.parametrize(
    "changes,error",
    [
        ({"fence": True}, ValidationError),
        ({"attempt_no": True}, ValidationError),
        ({"owner": "forged"}, StateConflict),
        ({"job_id": "other"}, StateConflict),
        ({"attempt_id": "forged"}, StateConflict),
        ({"attempt_no": 2}, StateConflict),
    ],
)
def test_reader_identity_boundaries_reject_forged_ack(
    tmp_path: Path, changes: dict[str, Any], error: type[Exception]
) -> None:
    with JobStore(tmp_path / "library.sqlite") as jobs:
        job = jobs.create("STT", "input")
        attempt = jobs.claim(job.job_id, "worker")
        jobs.reader_started(attempt)
        with pytest.raises(error):
            jobs.reader_finished(replace(attempt, **changes))
        assert jobs.local_reader_active(job.job_id) is True


def test_publisher_cannot_forge_physical_reader_ack(tmp_path: Path) -> None:
    with JobStore(tmp_path / "library.sqlite") as jobs:
        job = jobs.create("STT", "input")
        attempt = jobs.claim(job.job_id, "worker")
        jobs.reader_started(attempt)

        def malicious(connection: sqlite3.Connection) -> str:
            connection.execute("UPDATE job_local_readers SET active=0")
            return "result"

        with pytest.raises(sqlite3.DatabaseError):
            jobs.complete_with(job.job_id, attempt.attempt_id, attempt.fence, malicious)
        assert jobs.local_reader_active(job.job_id) is True
        assert jobs.get(job.job_id).state == JobState.RUNNING


@pytest.mark.parametrize("value", [0, 1, None, "yes"])
def test_exclusive_recovery_flag_requires_bool(tmp_path: Path, value: Any) -> None:
    with JobStore(tmp_path / "library.sqlite") as jobs:
        with pytest.raises(ValidationError):
            jobs.recover_abandoned(coordinator_exclusive=value)


@pytest.mark.parametrize("delete_first", [False, True])
def test_reader_start_and_session_delete_orders_never_authorize_late_io(
    tmp_path: Path, delete_first: bool
) -> None:
    from recoryn.storage import Library

    with Library(tmp_path) as library, JobStore(library.db_path) as jobs:
        library.create_session("session")
        job = jobs.create("STT", "input")
        jobs.bind_session(job.job_id, "session")
        attempt = jobs.claim(job.job_id, "worker")
        if delete_first:
            assert library.delete_session("session")["deleted"] is False
            with pytest.raises(StateConflict, match="SESSION_DELETED"):
                jobs.reader_started(attempt)
        else:
            jobs.reader_started(attempt)
            assert library.delete_session("session")["deleted"] is False
            jobs.reader_finished(attempt)
        assert jobs.local_reader_active(job.job_id) is False
        with pytest.raises(StateConflict):
            jobs.complete(job.job_id, attempt.attempt_id, attempt.fence, "late")
        jobs.fail(job.job_id, attempt.attempt_id, attempt.fence, "DELETED")
        assert library.delete_session("session")["deleted"] is True


def test_reader_api_invalid_input_missing_job_and_closed_store(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "library.sqlite")
    job = store.create("STT", "input")
    attempt = store.claim(job.job_id, "worker")
    with pytest.raises(ValidationError):
        store.reader_started(None)  # type: ignore[arg-type]
    with pytest.raises(KeyError):
        store.local_reader_active("missing")
    with pytest.raises(ValidationError):
        store.local_reader_active(True)  # type: ignore[arg-type]
    store.cancel(job.job_id)
    with pytest.raises(StateConflict):
        store.reader_started(attempt)
    assert store.local_reader_active(job.job_id) is False
    store.close()
    with pytest.raises(StateConflict):
        store.local_reader_active(job.job_id)


@pytest.mark.parametrize("cancel_first", [False, True])
def test_remote_intent_survives_crash_and_fences_replay_even_after_cancel(
    tmp_path: Path, cancel_first: bool
) -> None:
    path = tmp_path / "library.sqlite"
    with JobStore(path) as jobs:
        job = jobs.create("STT", "remote-input")
        attempt = jobs.claim(job.job_id, "remote-worker")
        jobs.reader_started(attempt)
        jobs.mark_remote_intent(attempt, "reservation-one")
        jobs.mark_remote_intent(attempt, "reservation-one")
        jobs.mark_remote_intent(attempt, "reservation-two")
        if cancel_first:
            jobs.cancel(job.job_id)
        with closing(sqlite3.connect(path)) as db:
            assert db.execute("SELECT COUNT(*) FROM job_remote_intents").fetchone()[0] == 2
    with JobStore(path) as restarted:
        with pytest.raises(StateConflict):
            restarted.recover_abandoned()
        recovered = restarted.recover_abandoned(coordinator_exclusive=True)[0]
        assert recovered.state == JobState.BLOCKED
        assert recovered.blocked_reason == "REMOTE_UNKNOWN"
        assert recovered.cancel_requested is cancel_first
        assert restarted.local_reader_active(job.job_id) is False
        assert restarted.recover_abandoned(coordinator_exclusive=True) == []
        with pytest.raises(StateConflict):
            restarted.claim(job.job_id, "new-worker")
        with pytest.raises(StateConflict):
            restarted.resume(job.job_id)
        with closing(sqlite3.connect(path)) as db:
            assert db.execute("SELECT state FROM attempts").fetchone()[0] == "UNKNOWN"


def test_old_remote_marker_does_not_poison_recovery_of_a_known_unsent_retry(tmp_path: Path) -> None:
    path = tmp_path / "library.sqlite"
    with JobStore(path) as jobs:
        job = jobs.create("STT", "remote-input")
        first = jobs.claim(job.job_id, "worker")
        jobs.mark_remote_intent(first, "reserved-but-proven-unsent")
        jobs.fail(job.job_id, first.attempt_id, first.fence, "UNSENT", retryable=True)
        second = jobs.claim(job.job_id, "worker")
        with pytest.raises(StateConflict):
            jobs.mark_remote_intent(first, "stale")
    with JobStore(path) as restarted:
        recovered = restarted.recover_abandoned(coordinator_exclusive=True)[0]
        assert recovered.state == JobState.BLOCKED and recovered.blocked_reason == "ABANDONED"
        assert recovered.attempt_id == second.attempt_id
        restarted.resume(job.job_id)
        assert restarted.claim(job.job_id, "third").attempt_no == 3


@pytest.mark.parametrize("reservation", [True, "", "with\0nul", "x" * 129])
def test_remote_intent_rejects_invalid_reservation_identity(
    tmp_path: Path, reservation: Any
) -> None:
    with JobStore(tmp_path / "library.sqlite") as jobs:
        job = jobs.create("STT", "input")
        attempt = jobs.claim(job.job_id, "worker")
        with pytest.raises(ValidationError):
            jobs.mark_remote_intent(attempt, reservation)


def test_remote_intent_is_revoked_by_cancel_delete_and_sql_publisher(tmp_path: Path) -> None:
    from recoryn.storage import Library

    with Library(tmp_path) as library, JobStore(library.db_path) as jobs:
        library.create_session("session")
        job = jobs.create("STT", "input")
        jobs.bind_session(job.job_id, "session")
        attempt = jobs.claim(job.job_id, "worker")

        def forged(connection: sqlite3.Connection) -> str:
            connection.execute(
                "INSERT INTO job_remote_intents VALUES(?,?,?,?)",
                (attempt.attempt_id, "forged", job.job_id, attempt.fence),
            )
            return "result"

        with pytest.raises(sqlite3.DatabaseError):
            jobs.complete_with(job.job_id, attempt.attempt_id, attempt.fence, forged)
        assert library.delete_session("session")["deleted"] is False
        with pytest.raises(StateConflict, match="SESSION_DELETED"):
            jobs.mark_remote_intent(attempt, "deleted")
        jobs.cancel(job.job_id)
        with pytest.raises(StateConflict):
            jobs.mark_remote_intent(attempt, "cancelled")


@pytest.mark.parametrize(
    "reason", ["CONSENT", "AUTH", "RESOURCE", "BUDGET", "CAPABILITY", "ABANDONED"]
)
def test_resume_known_blocked_preserves_identity_history_checkpoint_and_attempt_limit(
    tmp_path: Path, reason: str
) -> None:
    path = tmp_path / "library.sqlite"
    with JobStore(path) as jobs:
        job = jobs.create("STT", "fixed-input")
        attempt = jobs.claim(job.job_id, "worker")
        jobs._publish_with(
            job.job_id,
            attempt.attempt_id,
            attempt.fence,
            lambda connection: "fixed-checkpoint",
            complete=False,
        )
        jobs.fail(job.job_id, attempt.attempt_id, attempt.fence, "KNOWN_FAILURE")
        with closing(sqlite3.connect(path)) as db, db:
            db.execute(
                "UPDATE jobs SET state='BLOCKED',blocked_reason=? WHERE job_id=?",
                (reason, job.job_id),
            )
        before = jobs.get(job.job_id)
        resumed = jobs.resume(job.job_id)
        assert resumed.state == JobState.QUEUED and resumed.blocked_reason is None
        assert resumed.fence == before.fence + 1
        assert resumed.state_version == before.state_version + 1
        assert resumed.attempt_count == 1 and resumed.attempt_id == attempt.attempt_id
        assert resumed.input_key == job.input_key and resumed.job_id == job.job_id
        with closing(sqlite3.connect(path)) as db:
            assert db.execute("SELECT result_ref FROM job_checkpoints").fetchall() == [
                ("fixed-checkpoint",)
            ]
            assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 1
        assert jobs.claim(job.job_id, "retry").attempt_no == 2


@pytest.mark.parametrize(
    "condition", ["unknown", "unconfirmed", "cancelled", "limit", "active", "legacy"]
)
def test_resume_rejects_unsafe_blocked_conditions(tmp_path: Path, condition: str) -> None:
    path = tmp_path / "library.sqlite"
    with JobStore(path) as jobs:
        job = jobs.create("STT", "input")
        attempt = jobs.claim(job.job_id, "worker")
        jobs.reader_started(attempt)
        jobs.fail(job.job_id, attempt.attempt_id, attempt.fence, "KNOWN_FAILURE")
        if condition != "active":
            jobs.reader_finished(attempt)
        with closing(sqlite3.connect(path)) as db, db:
            db.execute(
                "UPDATE jobs SET state='BLOCKED',blocked_reason='AUTH' WHERE job_id=?",
                (job.job_id,),
            )
            if condition in ("unknown", "unconfirmed"):
                db.execute(
                    "UPDATE jobs SET blocked_reason=?",
                    ("REMOTE_UNKNOWN" if condition == "unknown" else "CANCEL_UNCONFIRMED",),
                )
            elif condition == "cancelled":
                db.execute("UPDATE jobs SET cancel_requested=1")
            elif condition == "limit":
                db.execute("UPDATE jobs SET attempt_count=3")
            elif condition == "legacy":
                db.execute("DELETE FROM job_local_readers")
        before = jobs.get(job.job_id)
        with pytest.raises(StateConflict):
            jobs.resume(job.job_id)
        assert jobs.get(job.job_id) == before


def test_resume_undispatched_known_block_and_deleted_session(tmp_path: Path) -> None:
    from recoryn.storage import Library

    with Library(tmp_path) as library, JobStore(library.db_path) as jobs:
        library.create_session("session")
        job = jobs.create("STT", "input")
        jobs.bind_session(job.job_id, "session")
        with closing(sqlite3.connect(library.db_path)) as db, db:
            db.execute("UPDATE jobs SET state='BLOCKED',blocked_reason='CONSENT'")
        assert jobs.local_reader_active(job.job_id) is None
        assert jobs.resume(job.job_id).state == JobState.QUEUED
        with pytest.raises(StateConflict):
            jobs.resume(job.job_id)
        with closing(sqlite3.connect(library.db_path)) as db, db:
            db.execute("UPDATE jobs SET state='BLOCKED',blocked_reason='CONSENT'")
        assert library.delete_session("session")["deleted"] is False
        with pytest.raises(StateConflict, match="SESSION_DELETED"):
            jobs.resume(job.job_id)
