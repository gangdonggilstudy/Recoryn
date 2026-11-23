"""Handwritten contract oracle; expected values never use the product catalog."""

from __future__ import annotations

from pathlib import Path

import pytest

from recoryn.domain import StateConflict, ValidationError
from recoryn.jobs import JobStore
from recoryn.jobs.failures import CODE_GROUPS, normalize_failure
from recoryn.providers import ProviderError

# Approved G07 table, independently transcribed by category, including the sentinel.
ORACLE = {
    "CONSENT": "CONSENT_REQUIRED CONSENT_REVOKED CONSENT_POLICY_CHANGED CONSENT_CLOCK_INVALID PERMIT_REVOKED EXECUTION_CHANGED ENDPOINT_CHANGED NETWORK_POLICY_DENIED DNS_TARGET_DENIED REDIRECT_DENIED".split(),
    "AUTH": "AUTH_REQUIRED VAULT_UNAVAILABLE VAULT_READ_FAILED".split(),
    "CAPABILITY": "CAPABILITY_UNSUPPORTED LANGUAGE_UNSUPPORTED AUDIO_UNSUPPORTED CONTEXT_LIMIT CONTEXT_LIMIT_UNKNOWN DEPENDENCY_MISSING DEPENDENCY_VERSION_UNSUPPORTED LOCAL_EXECUTION_UNVERIFIED DIARIZATION_PLATFORM_UNSUPPORTED DIARIZATION_AUDIO_UNSUPPORTED DIARIZATION_LICENSE_REQUIRED OLLAMA_LOCAL_EXECUTION_UNVERIFIED OLLAMA_REMOTE_MODEL_BLOCKED TRANSCRIPTION_REQUIRES_FINALIZED_AUDIO SUMMARY_REQUIRES_COMPLETE_TRANSCRIPT".split(),
    "RESOURCE": "OOM RESOURCE_EXHAUSTED RESOURCE_GPU_UNAVAILABLE RESOURCE_ESTIMATE_REQUIRED MODEL_MISSING LOCAL_MODEL_REQUIRED GPU_RUNTIME_UNAVAILABLE GPU_RUNTIME_DAMAGED GPU_RUNTIME_NOT_INSTALLED GPU_RUNTIME_LATE GPU_RUNTIME_UNSUPPORTED INFERENCE_ACK_PENDING DIARIZATION_ACK_PENDING MODEL_OPERATION_ACTIVE GPU_RUNTIME_IN_USE LOCAL_READER_ACK_REQUIRED LOCAL_READER_STILL_ACTIVE".split(),
    "BUDGET": "BUDGET_BLOCKED BUDGET_REQUIRED BUDGET_EXCEEDED BUDGET_POLICY_CHANGED BUDGET_SCOPE_MISMATCH LEDGER_REQUIRED LEDGER_ROLLBACK_DETECTED RESERVATION_CONFLICT RESERVATION_NOT_DISPATCHABLE RESERVATION_MAY_BE_SENT SETTLEMENT_CONFLICT COST_PRICE_UNKNOWN COST_PRICE_EXPIRED COST_BOUND_UNVERIFIED COST_CAP_REQUIRED COST_CAP_EXCEEDED COST_QUOTE_MISMATCH COST_QUOTE_EXPIRED COST_CURRENCY_MISMATCH COST_PERIOD_CHANGED COST_LEGACY_UNSCOPED COST_UNRESOLVED_EXPOSURE COST_CLOCK_INVALID COST_PLAN_UNDERESTIMATED".split(),
    "TRANSIENT": "TEMPORARY UNSENT TIMEOUT NETWORK_TIMEOUT TRANSPORT_FAILED CONNECTION_FAILED CONNECTION_CLOSED POLICY_BUSY".split(),
    "FAILED": "INPUT_INVALID INPUT_MISSING INPUT_TOO_LARGE REQUEST_TOO_LARGE RESPONSE_TOO_LARGE RESULT_INVALID RESULT_INCOMPLETE REFERENCE_INVALID CHECKPOINT_MISMATCH PROGRESS_CALLBACK_FAILED PROVIDER_FAILED TASK_FAILED COST_REQUEST_INVALID COST_AMOUNT_OVERFLOW SESSION_REVOKED SESSION_DELETED CANCELLED RESOURCE_CANCELLED MODEL_CHECKSUM_MISMATCH DIARIZATION_MODEL_CHECKSUM BUDGET_RESERVATION_REUSED REMOTE_REJECTED REQUEST_LIMIT INVALID_CONSENT_CONTEXT INVALID_CONSENT_SCOPE INVALID_CONSENT_SCOPES INVALID_CONSENT_BINDING INVALID_SESSION_GENERATION DELETE_PENDING JOB_SESSION_DELETED JOB_SESSION_MISSING".split(),
    "UNKNOWN": ["REMOTE_OUTCOME_UNKNOWN", "G07_UNREGISTERED_ERROR"],
}


def test_closed_catalog_matches_independent_table():
    rows = [(code, group) for group, codes in ORACLE.items() for code in codes]
    assert len(rows) == len(dict(rows)) == 110
    assert dict(CODE_GROUPS) == {
        code: group for code, group in rows if code != "G07_UNREGISTERED_ERROR"
    }


@pytest.mark.parametrize("group,code", [(g, c) for g, cs in ORACLE.items() for c in cs])
def test_store_failure_matches_catalog(group, code):
    with JobStore(Path(":memory:")) as store:
        job = store.create("stt", "input")
        attempt = store.claim(job.job_id, "worker")
        store.reader_started(attempt)
        store._publish_with(
            job.job_id,
            attempt.attempt_id,
            attempt.fence,
            lambda db: "checkpoint-preserved",
            complete=False,
        )
        checkpoint = store._db.execute("SELECT * FROM job_checkpoints").fetchall()
        old = store.get(job.job_id)
        failed = store.fail(job.job_id, attempt.attempt_id, attempt.fence, code, True, True)
        if code == "REMOTE_OUTCOME_UNKNOWN":
            expected, reason = "BLOCKED", "REMOTE_UNKNOWN"
        elif group in {"CONSENT", "AUTH", "CAPABILITY", "RESOURCE", "BUDGET"}:
            expected, reason = "BLOCKED", group
        elif group == "TRANSIENT":
            expected, reason = "BACKOFF", None
        else:
            expected, reason = "FAILED", None
        assert (failed.state.value, failed.blocked_reason) == (expected, reason)
        assert failed.fence == old.fence + 1 and failed.state_version == old.state_version + 1
        assert failed.result_ref == old.result_ref
        assert store._db.execute("SELECT * FROM job_checkpoints").fetchall() == checkpoint
        assert store.local_reader_active(job.job_id) is True
        store.reader_finished(attempt)
        assert store.local_reader_active(job.job_id) is False


@pytest.mark.parametrize("case", range(1, 21), ids=lambda n: f"G07-N-{n:02}")
def test_normalization(case):
    from recoryn.security import SecurityError

    class Hostile(Exception):
        def __getattribute__(self, name):
            if name == {10: "code", 11: "retryable", 12: "outcome_known"}.get(case):
                raise RuntimeError("SECRET_CANARY")
            return super().__getattribute__(name)

    error = Hostile("SECRET_CANARY")
    error.code = "CONSENT_REQUIRED"
    error.retryable, error.outcome_known = False, True
    code, retry, known = "CONSENT_REQUIRED", False, True
    if case == 1:
        error = ProviderError("CONSENT_REQUIRED")
    elif case == 2:
        error = SecurityError("CONSENT_REVOKED")
        code = "CONSENT_REVOKED"
    elif case in (3, 4):
        error = (StateConflict if case == 3 else ValidationError)("COST_CAP_EXCEEDED")
        code = "COST_CAP_EXCEEDED"
    elif case == 5:
        error, code = MemoryError(), "OOM"
    elif case == 6:
        error, code = RuntimeError("CONSENT_REQUIRED SECRET_CANARY"), "TASK_FAILED"
    elif case in (7, 8, 9):
        error.code = {7: "UNREGISTERED", 8: "consent_required", 9: "SECRET_CANARY\n"}[case]
        code = "TASK_FAILED"
    elif case == 10:
        code = "TASK_FAILED"
    elif case == 12:
        known = False
    elif case in (13, 14):
        error.retryable = 1 if case == 13 else None
    elif case in (15, 16):
        error.outcome_known = 1 if case == 15 else None
        known = False
    elif case == 17:
        del error.outcome_known
    elif case == 18:
        error.code, code, known = "REMOTE_OUTCOME_UNKNOWN", "REMOTE_OUTCOME_UNKNOWN", False
    elif case == 19:
        error.code, error.retryable, error.outcome_known = "OOM", True, False
        code, retry, known = "OOM", True, False
    elif case == 20:
        error.code, code = "COST_CAP_EXCEEDED", "COST_CAP_EXCEEDED"
    facts = normalize_failure(error)
    assert (facts.code, facts.retryable, facts.outcome_known) == (code, retry, known)
    assert "SECRET_CANARY" not in repr(facts)


@pytest.mark.parametrize("case", range(1, 19), ids=lambda n: f"G07-T-{n:02}")
def test_api_type_and_cas_guards(case):
    from recoryn.app.status import CaptureProgress, capture_status

    with JobStore(Path(":memory:")) as store:
        job = store.create("stt", "x")
        if case in (15, 16):
            value = -1 if case == 15 else True
            assert "REC" not in capture_status(
                CaptureProgress(
                    control_mode="ACTIVE",
                    all_sources_ready=True,
                    accepting=True,
                    current_accepted_frames=value,
                )
            )
            return
        if case in (17, 18):
            blocked = store.block_pending(
                job.job_id, "CONSENT", "CONSENT_REQUIRED", expected_version=0
            )
            with pytest.raises(StateConflict, match="JOB_VERSION_CHANGED"):
                store.resume(
                    job.job_id, expected_version=blocked.state_version + (-1 if case == 17 else 1)
                )
            assert store.get(job.job_id) == blocked
            return
        if case in (13, 14):
            a = store.claim(job.job_id, "worker")
            before = store.get(job.job_id)
            with pytest.raises(ValidationError):
                store.fail(
                    job.job_id,
                    a.attempt_id,
                    a.fence,
                    "OOM",
                    retryable=1 if case == 13 else False,
                    outcome_known=None if case == 14 else True,
                )
            assert store.get(job.job_id) == before
            return
        job_id, reason, code, version = job.job_id, "CONSENT", "CONSENT_REQUIRED", 0
        if case <= 2:
            job_id = "" if case == 1 else None
        elif case <= 6:
            reason = {3: "", 4: "consent", 5: "REMOTE_UNKNOWN", 6: "ABANDONED"}[case]
        elif case == 7:
            code = "OOM"
        elif case <= 9:
            code = "UNREGISTERED" if case == 8 else None
        else:
            version = {10: True, 11: -1, 12: "0"}[case]
        with pytest.raises(ValidationError):
            store.block_pending(job_id, reason, code, expected_version=version)
        assert store.get(job.job_id) == job


def test_pending_and_resume_require_attempt_termination_even_after_reader_ack():
    with JobStore(Path(":memory:")) as store:
        job = store.create("stt", "x")
        a = store.claim(job.job_id, "owner")
        store.reader_started(a)
        store.reader_finished(a)
        # A reader ACK proves only local I/O ended, not the logical Attempt.
        store._db.execute("UPDATE jobs SET state='QUEUED'")
        with pytest.raises(StateConflict, match="LOCAL_READER_ACK_REQUIRED"):
            store.block_pending(job.job_id, "AUTH", "AUTH_REQUIRED", expected_version=1)
        store._db.execute("UPDATE jobs SET state='BLOCKED',blocked_reason='AUTH'")
        with pytest.raises(StateConflict, match="LOCAL_READER_ACK_REQUIRED"):
            store.resume(job.job_id)
