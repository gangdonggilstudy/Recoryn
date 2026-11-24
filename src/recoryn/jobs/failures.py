"""Closed failure decisions shared by the runner and durable Job transitions."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from recoryn.domain import StateConflict, ValidationError

_GROUPS = {
    "CONSENT": """CONSENT_REQUIRED CONSENT_REVOKED CONSENT_POLICY_CHANGED CONSENT_CLOCK_INVALID
        PERMIT_REVOKED EXECUTION_CHANGED ENDPOINT_CHANGED NETWORK_POLICY_DENIED
        DNS_TARGET_DENIED REDIRECT_DENIED""",
    "AUTH": "AUTH_REQUIRED VAULT_UNAVAILABLE VAULT_READ_FAILED",
    "CAPABILITY": """CAPABILITY_UNSUPPORTED LANGUAGE_UNSUPPORTED AUDIO_UNSUPPORTED CONTEXT_LIMIT
        CONTEXT_LIMIT_UNKNOWN DEPENDENCY_MISSING DEPENDENCY_VERSION_UNSUPPORTED
        LOCAL_EXECUTION_UNVERIFIED DIARIZATION_PLATFORM_UNSUPPORTED DIARIZATION_AUDIO_UNSUPPORTED
        DIARIZATION_LICENSE_REQUIRED OLLAMA_LOCAL_EXECUTION_UNVERIFIED OLLAMA_REMOTE_MODEL_BLOCKED
        TRANSCRIPTION_REQUIRES_FINALIZED_AUDIO SUMMARY_REQUIRES_COMPLETE_TRANSCRIPT
        RESOURCE_POLICY_UNVERIFIED RESOURCE_GPU_UNSUPPORTED""",
    "RESOURCE": """OOM RESOURCE_EXHAUSTED RESOURCE_GPU_UNAVAILABLE RESOURCE_ESTIMATE_REQUIRED
        MODEL_MISSING LOCAL_MODEL_REQUIRED GPU_RUNTIME_UNAVAILABLE GPU_RUNTIME_DAMAGED
        GPU_RUNTIME_NOT_INSTALLED GPU_RUNTIME_LATE GPU_RUNTIME_UNSUPPORTED INFERENCE_ACK_PENDING
        DIARIZATION_ACK_PENDING MODEL_OPERATION_ACTIVE GPU_RUNTIME_IN_USE
        LOCAL_READER_ACK_REQUIRED LOCAL_READER_STILL_ACTIVE""",
    "BUDGET": """BUDGET_BLOCKED BUDGET_REQUIRED BUDGET_EXCEEDED BUDGET_POLICY_CHANGED
        BUDGET_SCOPE_MISMATCH LEDGER_REQUIRED LEDGER_ROLLBACK_DETECTED RESERVATION_CONFLICT
        RESERVATION_NOT_DISPATCHABLE RESERVATION_MAY_BE_SENT SETTLEMENT_CONFLICT
        COST_PRICE_UNKNOWN COST_PRICE_EXPIRED COST_BOUND_UNVERIFIED COST_CAP_REQUIRED
        COST_CAP_EXCEEDED COST_QUOTE_MISMATCH COST_QUOTE_EXPIRED COST_CURRENCY_MISMATCH
        COST_PERIOD_CHANGED COST_LEGACY_UNSCOPED COST_UNRESOLVED_EXPOSURE COST_CLOCK_INVALID
        COST_PLAN_UNDERESTIMATED""",
    "TRANSIENT": """TEMPORARY UNSENT TIMEOUT NETWORK_TIMEOUT TRANSPORT_FAILED CONNECTION_FAILED
        CONNECTION_CLOSED POLICY_BUSY""",
    "FAILED": """INPUT_INVALID INPUT_MISSING INPUT_TOO_LARGE REQUEST_TOO_LARGE RESPONSE_TOO_LARGE
        RESULT_INVALID RESULT_INCOMPLETE REFERENCE_INVALID CHECKPOINT_MISMATCH
        PROGRESS_CALLBACK_FAILED PROVIDER_FAILED TASK_FAILED COST_REQUEST_INVALID COST_AMOUNT_OVERFLOW
        SESSION_REVOKED SESSION_DELETED CANCELLED RESOURCE_CANCELLED MODEL_CHECKSUM_MISMATCH
        DIARIZATION_MODEL_CHECKSUM BUDGET_RESERVATION_REUSED REMOTE_REJECTED REQUEST_LIMIT
        INVALID_CONSENT_CONTEXT INVALID_CONSENT_SCOPE INVALID_CONSENT_SCOPES INVALID_CONSENT_BINDING
        INVALID_SESSION_GENERATION DELETE_PENDING JOB_SESSION_DELETED JOB_SESSION_MISSING""",
    "UNKNOWN": "REMOTE_OUTCOME_UNKNOWN",
}
CODE_GROUPS = MappingProxyType(
    {code: group for group, codes in _GROUPS.items() for code in codes.split()}
)
BLOCK_REASONS = frozenset({"CONSENT", "AUTH", "CAPABILITY", "RESOURCE", "BUDGET"})
BOUNDARY_CODES = frozenset(
    code for code, group in CODE_GROUPS.items() if group in {"CONSENT", "BUDGET"}
) | frozenset(
    {
        "COST_REQUEST_INVALID",
        "COST_AMOUNT_OVERFLOW",
        "INVALID_CONSENT_CONTEXT",
        "INVALID_CONSENT_SCOPE",
        "INVALID_CONSENT_SCOPES",
        "INVALID_CONSENT_BINDING",
        "INVALID_SESSION_GENERATION",
        "SESSION_REVOKED",
        "LOCAL_EXECUTION_UNVERIFIED",
    }
)


@dataclass(frozen=True, slots=True)
class NormalizedFailure:
    code: str
    retryable: bool = False
    outcome_known: bool = True


@dataclass(frozen=True, slots=True)
class FailureDecision:
    state: str
    attempt_state: str
    blocked_reason: str | None = None


def _attribute(error: BaseException, name: str, default: object) -> object:
    try:
        return getattr(error, name, default)
    except Exception:
        return None


def normalize_failure(error: BaseException, *, remote_boundary: bool = False) -> NormalizedFailure:
    """Never parse exception messages or persist arbitrary SDK text."""
    code = _attribute(error, "code", None)
    if isinstance(error, MemoryError):
        code = "OOM"
    elif not remote_boundary and isinstance(error, (StateConflict, ValidationError)):
        code = error.args[0] if len(error.args) == 1 else None
    if type(code) is not str or code not in CODE_GROUPS:
        code = "TASK_FAILED"
    retryable = _attribute(error, "retryable", False) is True
    known = _attribute(error, "outcome_known", not remote_boundary) is True
    return NormalizedFailure(code, retryable, known and code != "REMOTE_OUTCOME_UNKNOWN")


def failure_decision(
    error_code: str,
    retryable: bool,
    outcome_known: bool,
    attempt_count: int,
    *,
    session_valid: bool = True,
) -> FailureDecision:
    """Unknown outcome outranks deletion, retry hints and blocked categories."""
    if outcome_known is not True or error_code == "REMOTE_OUTCOME_UNKNOWN":
        return FailureDecision("BLOCKED", "UNKNOWN", "REMOTE_UNKNOWN")
    group = CODE_GROUPS.get(error_code)
    if session_valid and group in BLOCK_REASONS:
        return FailureDecision("BLOCKED", "FAILED", group)
    if session_valid and group == "TRANSIENT" and retryable is True and attempt_count < 3:
        return FailureDecision("BACKOFF", "FAILED")
    return FailureDecision("FAILED", "FAILED")
