"""Deterministic local worker, bounded dispatch and safe error-policy tests."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from recoryn.content import ContentStore, Segment
from recoryn.domain import StateConflict, ValidationError
from recoryn.jobs import AttemptRecord, JobState, JobStore
from recoryn.jobs.runner import BoundedRunner
from recoryn.storage import Library


class TaskError(ValueError):
    def __init__(
        self, code: str = "TEMPORARY", *, retryable: bool = False, outcome_known: bool = True
    ) -> None:
        super().__init__("SECRET_PROVIDER_BODY")
        self.code, self.retryable, self.outcome_known = code, retryable, outcome_known


@pytest.fixture
def jobs(tmp_path: Path) -> Iterator[JobStore]:
    with JobStore(tmp_path / "library.sqlite") as store:
        yield store


def idle(runner: BoundedRunner) -> None:
    with runner._condition:
        assert runner._condition.wait_for(
            lambda: not runner._queue and not runner._active, timeout=5
        )


def test_constructor_is_inert_and_start_stop_restart_are_explicit(jobs: JobStore) -> None:
    runner = BoundedRunner(jobs)
    assert not runner.running
    job = jobs.create("STT", "input")
    with pytest.raises(StateConflict):
        runner.submit(job.job_id, lambda attempt, cancel: "result")
    runner.stop()
    for _ in range(2):
        runner.start()
        runner.start()
        assert runner.running
        runner.stop()
        assert not runner.running


def test_capacity_dedup_and_queued_cancellation(jobs: JobStore) -> None:
    runner = BoundedRunner(jobs, capacity=1)
    started, release = threading.Event(), threading.Event()
    first, second, third = [jobs.create("STT", f"input-{i}") for i in range(3)]

    def task(attempt: AttemptRecord, cancel: threading.Event) -> str:
        started.set()
        assert release.wait(5)
        return "result"

    runner.start()
    try:
        assert runner.submit(first.job_id, task)
        assert started.wait(5)
        assert runner.submit(second.job_id, task)
        assert not runner.submit(third.job_id, task)
        assert not runner.submit(first.job_id, task)
        assert runner.snapshot()["pending"] == 1
        assert runner.cancel(second.job_id).state == JobState.CANCELLED
        assert runner.submit(third.job_id, task)
        release.set()
        idle(runner)
        assert jobs.get(first.job_id).state == jobs.get(third.job_id).state == JobState.SUCCEEDED
        assert runner.snapshot()["high_water"] == 1
        assert runner.snapshot()["succeeded"] == 2
    finally:
        release.set()
        runner.stop()


def test_cancelled_task_cannot_publish_and_stop_waits_for_ack(jobs: JobStore) -> None:
    started = threading.Event()
    runner = BoundedRunner(jobs)
    job = jobs.create("STT", "input")

    def task(attempt: AttemptRecord, cancel: threading.Event) -> str:
        started.set()
        assert cancel.wait(5)
        return "late-result"

    runner.start()
    assert runner.submit(job.job_id, task)
    assert started.wait(5)
    runner.cancel(job.job_id)
    idle(runner)
    runner.stop()
    assert jobs.get(job.job_id).state == JobState.CANCELLED
    assert jobs.get(job.job_id).result_ref is None


def test_stop_timeout_never_claims_worker_has_stopped(jobs: JobStore) -> None:
    started, release = threading.Event(), threading.Event()
    runner = BoundedRunner(jobs)
    job = jobs.create("STT", "input")

    def hung(attempt: AttemptRecord, cancel: threading.Event) -> str:
        started.set()
        assert release.wait(5)
        return "late-result"

    runner.start()
    runner.submit(job.job_id, hung)
    assert started.wait(5)
    try:
        with pytest.raises(TimeoutError):
            runner.stop(timeout=0)
        assert runner.running and not runner.snapshot()["accepting"]
        with pytest.raises(StateConflict):
            runner.start()
        assert jobs.get(job.job_id).state == JobState.CANCEL_REQUESTED
    finally:
        release.set()
        runner.stop()
    assert jobs.get(job.job_id).state == JobState.CANCELLED


@pytest.mark.parametrize("known", [True, False])
def test_error_policy_retries_are_bounded_and_unknown_dominates(
    jobs: JobStore, known: bool
) -> None:
    runner = BoundedRunner(jobs)
    job = jobs.create("STT", "input")
    attempts = []

    def failing(attempt: AttemptRecord, cancel: threading.Event) -> str:
        attempts.append(attempt.attempt_id)
        raise TaskError(retryable=True, outcome_known=known)

    runner.start()
    try:
        runner.submit(job.job_id, failing)
        idle(runner)
        assert len(attempts) == (3 if known else 1)
        assert jobs.get(job.job_id).state == (JobState.FAILED if known else JobState.BLOCKED)
        assert runner.snapshot()["last_error"] == "TEMPORARY"
        assert "SECRET" not in str(runner.snapshot())
    finally:
        runner.stop()


def test_retry_uses_new_attempt_and_cancellation_during_backoff(jobs: JobStore) -> None:
    runner = BoundedRunner(jobs)
    job = jobs.create("STT", "input")
    seen = []

    def task(attempt: AttemptRecord, cancel: threading.Event) -> str:
        seen.append(attempt.attempt_id)
        if len(seen) == 1:
            raise TaskError(retryable=True)
        return "recovered"

    runner.start()
    try:
        runner.submit(job.job_id, task)
        idle(runner)
        assert len(set(seen)) == 2 and jobs.get(job.job_id).result_ref == "recovered"
    finally:
        runner.stop()


def test_partial_content_survives_safe_error_and_new_runner(tmp_path: Path) -> None:
    with (
        Library(tmp_path) as library,
        ContentStore(library) as content,
        JobStore(library.db_path) as jobs,
    ):
        library.create_session("session")
        job = jobs.create("STT", "input")
        runner = BoundedRunner(jobs)
        partials = []

        def task(attempt: AttemptRecord, cancel: threading.Event) -> str:
            partials.append(
                content.publish_transcript(
                    jobs, attempt, "session", [Segment("s", 0, 1, "preserved")], complete=False
                )
            )
            raise TaskError("REMOTE_OUTCOME_UNKNOWN", retryable=True, outcome_known=False)

        runner.start()
        try:
            runner.submit(job.job_id, task)
            idle(runner)
            assert jobs.get(job.job_id).state == JobState.BLOCKED
            assert content.transcript(partials[0])["segments"][0]["text"] == "preserved"
            assert content.active_transcript("session") is None
        finally:
            runner.stop()
        with closing(sqlite3.connect(library.db_path)) as db:
            assert db.execute("SELECT result_ref FROM job_checkpoints").fetchone() == (partials[0],)


@pytest.mark.parametrize(
    "values",
    [{"capacity": True}, {"capacity": 0}, {"workers": False}, {"workers": 33}, {"owner": ""}],
)
def test_configuration_boundaries(jobs: JobStore, values: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        BoundedRunner(jobs, **values)


@pytest.mark.parametrize("timeout", [True, -1, float("inf"), "bad"])
def test_stop_timeout_input_boundary(jobs: JobStore, timeout: Any) -> None:
    with pytest.raises(ValidationError):
        BoundedRunner(jobs).stop(timeout)


def test_invalid_task_and_completed_submission(jobs: JobStore) -> None:
    runner = BoundedRunner(jobs)
    job = jobs.create("STT", "input")
    with pytest.raises(ValidationError):
        runner.submit(job.job_id, None)  # type: ignore[arg-type]
    jobs.cancel(job.job_id)
    assert not runner.submit(job.job_id, lambda attempt, cancel: "unused")


def test_stop_cancels_pending_and_self_join_is_rejected(jobs: JobStore) -> None:
    runner = BoundedRunner(jobs)
    started = threading.Event()
    first, second = [jobs.create("STT", f"input-{i}") for i in range(2)]

    def task(attempt: AttemptRecord, cancel: threading.Event) -> str:
        with pytest.raises(StateConflict):
            runner.stop()
        started.set()
        assert cancel.wait(5)
        return "late"

    runner.start()
    runner.submit(first.job_id, task)
    assert started.wait(5)
    runner.submit(second.job_id, lambda attempt, cancel: "never-runs")
    runner.stop()
    assert jobs.get(first.job_id).state == jobs.get(second.job_id).state == JobState.CANCELLED


@pytest.mark.parametrize("remote_unknown", [False, True])
def test_cancelled_error_preserves_unknown(jobs: JobStore, remote_unknown: bool) -> None:
    runner = BoundedRunner(jobs)
    started = threading.Event()
    job = jobs.create("STT", "input")

    def task(attempt: AttemptRecord, cancel: threading.Event) -> str:
        started.set()
        assert cancel.wait(5)
        raise TaskError("NETWORK_TIMEOUT", outcome_known=not remote_unknown)

    runner.start()
    runner.submit(job.job_id, task)
    assert started.wait(5)
    runner.cancel(job.job_id)
    idle(runner)
    runner.stop()
    assert jobs.get(job.job_id).state == (
        JobState.BLOCKED if remote_unknown else JobState.CANCELLED
    )


def test_bad_error_code_is_sanitized_and_invalid_result_fails(jobs: JobStore) -> None:
    runner = BoundedRunner(jobs)
    first, second = [jobs.create("STT", f"input-{i}") for i in range(2)]

    def unsafe(attempt: AttemptRecord, cancel: threading.Event) -> str:
        raise TaskError("secret:should-not-log")

    runner.start()
    try:
        runner.submit(first.job_id, unsafe)
        runner.submit(second.job_id, lambda attempt, cancel: None)  # type: ignore[arg-type,return-value]
        idle(runner)
        assert jobs.get(first.job_id).error_code == "TASK_FAILED"
        assert jobs.get(second.job_id).state == JobState.FAILED
        assert "secret" not in str(runner.snapshot())
    finally:
        runner.stop()


def test_backoff_can_be_cancelled_without_second_attempt(
    jobs: JobStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = BoundedRunner(jobs)
    backoff = threading.Event()
    original = jobs.fail

    def fail(*args: Any, **kwargs: Any) -> Any:
        result = original(*args, **kwargs)
        backoff.set()
        return result

    monkeypatch.setattr(jobs, "fail", fail)
    monkeypatch.setattr(runner, "RETRY_DELAY", 10)
    job = jobs.create("STT", "input")

    def temporary(attempt: AttemptRecord, cancel: threading.Event) -> str:
        raise TaskError(retryable=True)

    runner.start()
    try:
        runner.submit(job.job_id, temporary)
        assert backoff.wait(5)
        runner.cancel(job.job_id)
        idle(runner)
        assert jobs.get(job.job_id).attempt_count == 1
    finally:
        runner.stop()


def test_store_errors_are_safe_and_do_not_escape_thread(
    jobs: JobStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = BoundedRunner(jobs)
    job = jobs.create("STT", "input")

    def fail_claim(*args: Any, **kwargs: Any) -> Any:
        raise sqlite3.OperationalError("SECRET_DATABASE_DETAIL")

    monkeypatch.setattr(jobs, "claim", fail_claim)
    runner.start()
    try:
        runner.submit(job.job_id, lambda attempt, cancel: "unused")
        idle(runner)
        assert runner.snapshot()["last_error"] == "RUNNER_STORE_FAILED"
    finally:
        runner.stop()


@pytest.mark.parametrize("unknown_before_cancel", [False, True])
def test_unknown_local_reader_exit_releases_deletion_without_rewriting_remote_outcome(
    tmp_path: Path, unknown_before_cancel: bool
) -> None:
    with Library(tmp_path) as library, JobStore(library.db_path) as jobs:
        library.create_session("session")
        job = jobs.create("STT", "input")
        jobs.bind_session(job.job_id, "session")
        runner = BoundedRunner(jobs)
        started, release = threading.Event(), threading.Event()

        def task(attempt: AttemptRecord, cancel: threading.Event) -> str:
            assert jobs.local_reader_active(job.job_id) is True
            if unknown_before_cancel:
                jobs.fail(
                    job.job_id,
                    attempt.attempt_id,
                    attempt.fence,
                    "REMOTE_OUTCOME_UNKNOWN",
                    outcome_known=False,
                )
            started.set()
            assert release.wait(5)
            raise TaskError("REMOTE_OUTCOME_UNKNOWN", outcome_known=False)

        runner.start()
        try:
            assert runner.submit(job.job_id, task)
            assert started.wait(5)
            assert library.delete_session("session")["deleted"] is False
            runner.cancel(job.job_id)
            with pytest.raises(TimeoutError):
                runner.stop(0)
            assert jobs.local_reader_active(job.job_id) is True
            assert library.delete_session("session")["deleted"] is False
        finally:
            release.set()
            runner.stop()
        assert jobs.local_reader_active(job.job_id) is False
        assert jobs.get(job.job_id).state == JobState.BLOCKED
        assert jobs.get(job.job_id).blocked_reason == "REMOTE_UNKNOWN"
        assert library.delete_session("session")["deleted"] is True
        with closing(sqlite3.connect(library.db_path)) as db:
            assert db.execute("SELECT state FROM attempts").fetchone()[0] == "UNKNOWN"


def test_successful_publication_cannot_release_live_task_reader(tmp_path: Path) -> None:
    with Library(tmp_path) as library, JobStore(library.db_path) as jobs:
        library.create_session("session")
        job = jobs.create("STT", "input")
        jobs.bind_session(job.job_id, "session")
        runner = BoundedRunner(jobs)
        published, release = threading.Event(), threading.Event()

        def task(attempt: AttemptRecord, cancel: threading.Event) -> str:
            jobs.complete(job.job_id, attempt.attempt_id, attempt.fence, "published")
            published.set()
            assert release.wait(5)
            return "published"

        runner.start()
        try:
            runner.submit(job.job_id, task)
            assert published.wait(5)
            assert jobs.get(job.job_id).state == JobState.SUCCEEDED
            assert library.delete_session("session")["deleted"] is False
            assert jobs.local_reader_active(job.job_id) is True
        finally:
            release.set()
            runner.stop()
        assert jobs.local_reader_active(job.job_id) is False
        assert library.delete_session("session")["deleted"] is True


def test_retry_has_reader_receipt_for_each_task_and_releases_before_next_claim(
    jobs: JobStore,
) -> None:
    job = jobs.create("STT", "input")
    attempts: list[AttemptRecord] = []
    runner = BoundedRunner(jobs)

    def task(attempt: AttemptRecord, cancel: threading.Event) -> str:
        assert jobs.local_reader_active(job.job_id) is True
        attempts.append(attempt)
        if attempt.attempt_no == 1:
            raise TaskError(retryable=True)
        with pytest.raises(StateConflict):
            jobs.reader_finished(attempts[0])
        assert jobs.local_reader_active(job.job_id) is True
        return "result"

    runner.start()
    try:
        runner.submit(job.job_id, task)
        idle(runner)
    finally:
        runner.stop()
    assert len(attempts) == 2
    assert jobs.get(job.job_id).state == JobState.SUCCEEDED
    assert jobs.local_reader_active(job.job_id) is False


@pytest.mark.parametrize("cancel_first", [False, True])
def test_ack_storage_failure_preserves_task_unknown_and_safe_observation(
    tmp_path: Path, cancel_first: bool
) -> None:
    with Library(tmp_path) as library, JobStore(library.db_path) as jobs:
        library.create_session("session")
        job = jobs.create("STT", "input")
        jobs.bind_session(job.job_id, "session")
        with closing(sqlite3.connect(library.db_path)) as db, db:
            db.execute(
                "CREATE TRIGGER ack_fault BEFORE UPDATE ON job_local_readers "
                "WHEN OLD.active=1 AND NEW.active=0 "
                "BEGIN SELECT RAISE(ABORT, 'SECRET_STORAGE_DETAIL'); END"
            )
        runner = BoundedRunner(jobs)
        entered, release = threading.Event(), threading.Event()

        def task(attempt: AttemptRecord, cancel: threading.Event) -> str:
            entered.set()
            assert release.wait(5)
            raise TaskError("REMOTE_OUTCOME_UNKNOWN", outcome_known=False)

        runner.start()
        try:
            runner.submit(job.job_id, task)
            assert entered.wait(5)
            if cancel_first:
                runner.cancel(job.job_id)
            release.set()
            idle(runner)
        finally:
            release.set()
            runner.stop()
        assert jobs.get(job.job_id).state == JobState.BLOCKED
        assert jobs.get(job.job_id).blocked_reason == "REMOTE_UNKNOWN"
        assert jobs.local_reader_active(job.job_id) is True
        assert library.delete_session("session")["deleted"] is False
        assert runner.snapshot()["reader_ack_error"] == "LOCAL_READER_ACK_FAILED"
        assert "SECRET_STORAGE_DETAIL" not in str(runner.snapshot())


def test_ack_failure_after_normal_task_return_stays_fail_closed_until_exclusive_recovery(
    tmp_path: Path,
) -> None:
    with Library(tmp_path) as library, JobStore(library.db_path) as jobs:
        library.create_session("session")
        job = jobs.create("STT", "input")
        jobs.bind_session(job.job_id, "session")
        with closing(sqlite3.connect(library.db_path)) as db, db:
            db.execute(
                "CREATE TRIGGER ack_fault BEFORE UPDATE ON job_local_readers "
                "WHEN OLD.active=1 AND NEW.active=0 "
                "BEGIN SELECT RAISE(ABORT, 'SECRET_STORAGE_DETAIL'); END"
            )
        runner = BoundedRunner(jobs)
        runner.start()
        try:
            runner.submit(job.job_id, lambda attempt, cancel: "result")
            idle(runner)
        finally:
            runner.stop()
        assert jobs.get(job.job_id).state == JobState.FAILED
        assert jobs.get(job.job_id).result_ref is None
        assert jobs.local_reader_active(job.job_id) is True
        assert library.delete_session("session")["deleted"] is False
        assert runner.snapshot()["reader_ack_error"] == "LOCAL_READER_ACK_FAILED"
        with closing(sqlite3.connect(library.db_path)) as db, db:
            db.execute("DROP TRIGGER ack_fault")
        jobs.recover_abandoned(coordinator_exclusive=True)
        assert jobs.local_reader_active(job.job_id) is False
        assert library.delete_session("session")["deleted"] is True
