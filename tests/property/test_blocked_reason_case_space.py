"""G07 finite cube, hand-written policy oracle and real SQLite resume/queue transitions."""

from __future__ import annotations

import runpy
from itertools import product
from pathlib import Path

import pytest

from recoryn.domain import StateConflict
from recoryn.jobs import JobStore
from recoryn.jobs.failures import failure_decision

ORACLE = runpy.run_path(str(Path(__file__).parents[1] / "unit/test_blocked_reasons.py"))["ORACLE"]
CODES = [(g, c) for g, cs in ORACLE.items() for c in cs]
D = list(product(CODES, (False, True), (False, True), (1, 2, 3), (False, True)))
REASONS = (
    "CONSENT",
    "AUTH",
    "CAPABILITY",
    "RESOURCE",
    "BUDGET",
    "ABANDONED",
    "REMOTE_UNKNOWN",
    "INVALID",
)
R = list(
    product(
        REASONS,
        ("BLOCKED", "QUEUED", "FAILED", "CANCELLED", "SUCCEEDED"),
        range(6),
        (False, True),
        (False, True),
    )
)
P = list(
    product(
        REASONS[:5],
        ("QUEUED", "RUNNING", "BLOCKED", "SUCCEEDED", "FAILED", "CANCELLED"),
        (-1, 0, 1),
        (False, True),
        (False, True),
    )
)


@pytest.mark.parametrize("row", D, ids=[f"G07-D-{i:04}" for i in range(1, len(D) + 1)])
def test_failure_cube(row):
    (group, code), retry, known, attempt, valid = row
    if not known or code == "REMOTE_OUTCOME_UNKNOWN":
        expected = ("BLOCKED", "UNKNOWN", "REMOTE_UNKNOWN")
    elif not valid:
        expected = ("FAILED", "FAILED", None)
    elif group in {"CONSENT", "AUTH", "CAPABILITY", "RESOURCE", "BUDGET"}:
        expected = ("BLOCKED", "FAILED", group)
    elif group == "TRANSIENT" and retry and attempt < 3:
        expected = ("BACKOFF", "FAILED", None)
    else:
        expected = ("FAILED", "FAILED", None)
    actual = failure_decision(code, retry, known, attempt, session_valid=valid)
    assert (actual.state, actual.attempt_state, actual.blocked_reason) == expected
    # The same independent cube also observes durable Attempt/reader/checkpoint
    # state; a pure decision result is not evidence that fail() persisted it.
    with JobStore(Path(":memory:")) as store:
        store._db.execute("CREATE TABLE sessions(session_id TEXT PRIMARY KEY)")
        store._db.execute("INSERT INTO sessions VALUES('s')")
        job = store.create("transcription", "same-input")
        store.bind_session(job.job_id, "s")
        for index in range(attempt):
            claimed = store.claim(job.job_id, "worker")
            if index < attempt - 1:
                store.fail(job.job_id, claimed.attempt_id, claimed.fence, "TEMPORARY", True, True)
        store.reader_started(claimed)
        store._publish_with(
            job.job_id,
            claimed.attempt_id,
            claimed.fence,
            lambda db: "preserved-checkpoint",
            complete=False,
        )
        before = store.get(job.job_id)
        checkpoints = store._db.execute("SELECT * FROM job_checkpoints").fetchall()
        if not valid:
            store._db.execute("DELETE FROM sessions")
        failed = store.fail(job.job_id, claimed.attempt_id, claimed.fence, code, retry, known)
        attempt_state = store._db.execute(
            "SELECT state FROM attempts WHERE attempt_id=?", (claimed.attempt_id,)
        ).fetchone()[0]
        assert (failed.state.value, attempt_state, failed.blocked_reason) == expected
        assert failed.input_key == before.input_key and failed.attempt_count == attempt
        assert failed.fence == before.fence + 1
        assert store._db.execute("SELECT * FROM job_checkpoints").fetchall() == checkpoints
        assert store.local_reader_active(job.job_id) is True
        store.reader_finished(claimed)
        assert store.local_reader_active(job.job_id) is False


def fixture(store, *, state, reason, history, cancel, valid):
    """Malformed cross-products are defensive DB fixtures, not reachable-state claims."""
    job = store.create("stt", "input")
    store.bind_session(job.job_id, "s")
    store._db.execute("CREATE TABLE sessions(session_id TEXT PRIMARY KEY)")
    if valid:
        store._db.execute("INSERT INTO sessions VALUES('s')")
    if history:
        count = 2 if history == 4 else 3 if history == 5 else 1
        # Build the complete Attempt history before removing the session or
        # installing intentionally inconsistent state cross-products.
        if not valid:
            store._db.execute("INSERT INTO sessions VALUES('s')")
        for ordinal in range(count):
            attempt = store.claim(job.job_id, "owner")
            assert attempt.attempt_no == ordinal + 1
            if history == 2:
                store.reader_started(attempt)
            store.fail(job.job_id, attempt.attempt_id, attempt.fence, "TEMPORARY", True)
        assert store._db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == count
        if not valid:
            store._db.execute("DELETE FROM sessions")
        if history == 3:
            store._db.execute("DELETE FROM job_local_readers")
    store._db.execute(
        "UPDATE jobs SET state=?,blocked_reason=?,cancel_requested=?,result_ref='keep'",
        (state, reason, int(cancel)),
    )
    return store.get(job.job_id)


@pytest.mark.parametrize("row", R, ids=[f"G07-R-{i:04}" for i in range(1, len(R) + 1)])
def test_resume_cube(row):
    reason, state, history, cancel, valid = row
    allowed = (
        state == "BLOCKED"
        and reason in REASONS[:6]
        and history in (0, 1, 4)
        and not cancel
        and valid
    )
    with JobStore(Path(":memory:")) as store:
        before = fixture(
            store, state=state, reason=reason, history=history, cancel=cancel, valid=valid
        )
        attempts = store._db.execute("SELECT * FROM attempts").fetchall()
        reader = store.local_reader_active(before.job_id)
        if allowed:
            after = store.resume(before.job_id, expected_version=before.state_version)
            assert after.state.value == "QUEUED" and after.blocked_reason is None
            assert (
                after.fence == before.fence + 1 and after.state_version == before.state_version + 1
            )
        else:
            with pytest.raises(StateConflict):
                store.resume(before.job_id, expected_version=before.state_version)
            after = store.get(before.job_id)
            assert after == before
        assert after.result_ref == "keep" and after.attempt_count == before.attempt_count
        assert store._db.execute("SELECT * FROM attempts").fetchall() == attempts
        assert store.local_reader_active(before.job_id) is reader


@pytest.mark.parametrize("row", P, ids=[f"G07-P-{i:04}" for i in range(1, len(P) + 1)])
def test_pending_cube(row):
    reason, state, delta, valid, previous = row
    code = {
        "CONSENT": "CONSENT_REQUIRED",
        "AUTH": "AUTH_REQUIRED",
        "CAPABILITY": "CAPABILITY_UNSUPPORTED",
        "RESOURCE": "OOM",
        "BUDGET": "COST_CAP_EXCEEDED",
    }[reason]
    with JobStore(Path(":memory:")) as store:
        before = fixture(
            store, state=state, reason=None, history=int(previous), cancel=False, valid=valid
        )
        # Nonnegative old/current/future versions, including never-dispatched jobs.
        store._db.execute("UPDATE jobs SET state_version=10")
        before = store.get(before.job_id)
        attempts = store._db.execute("SELECT * FROM attempts").fetchall()
        if state == "QUEUED" and delta == 0 and valid:
            after = store.block_pending(before.job_id, reason, code, expected_version=10)
            assert (after.state.value, after.blocked_reason, after.error_code) == (
                "BLOCKED",
                reason,
                code,
            )
            assert after.fence == before.fence + 1 and after.state_version == 11
        else:
            with pytest.raises(StateConflict):
                store.block_pending(before.job_id, reason, code, expected_version=10 + delta)
            after = store.get(before.job_id)
            assert after == before
        assert after.attempt_count == before.attempt_count and after.result_ref == "keep"
        assert store._db.execute("SELECT * FROM attempts").fetchall() == attempts


def test_family_census():
    assert len(D) == len(set(D)) == 2640
    assert len(R) == len(set(R)) == 960
    assert len(P) == len(set(P)) == 360
