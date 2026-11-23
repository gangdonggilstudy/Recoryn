"""Pure, safe presentation of capture facts and AI admission failures."""

from __future__ import annotations

from dataclasses import dataclass

from recoryn.jobs import JobRecord
from recoryn.jobs.failures import BLOCK_REASONS, CODE_GROUPS, NormalizedFailure


@dataclass(frozen=True, slots=True)
class CaptureProgress:
    session_id: str | None = None
    run_generation: int = 0
    epochs: tuple[tuple[str, str], ...] = ()
    control_mode: str = "IDLE"
    all_sources_ready: bool = False
    current_accepted_frames: int = 0
    accepting: bool = False
    storage_failed: bool = False
    generation_match: bool = True
    failure: bool = False
    ack_pending: bool = False
    manifest_sync_pending: bool = False


def capture_status(facts: CaptureProgress) -> str:
    if facts.storage_failed:
        return "저장 오류 · 확정된 원본 보존 · 종료 확인 필요"
    if facts.ack_pending:
        return "종료 확인 대기 · 일부 원본 보존"
    if facts.failure:
        return "장치 오류 · 일부 원본 보존 · 상태 확인 필요"
    if facts.control_mode == "START_FAILED":
        return "시작 실패 · 기존 원본 보존 · 시작 조건을 확인하세요"
    if facts.control_mode == "PAUSED":
        return "Ⅱ 일시정지 · 중단 구간은 복원되지 않습니다"
    if facts.control_mode == "STOPPING":
        return "정지 중 · 종료 확인 대기"
    if facts.control_mode in {"IDLE", "ENDED"}:
        if facts.control_mode == "ENDED" and facts.manifest_sync_pending:
            return "■ 원본 확정 · manifest 동기화 대기 · AI 처리는 별도"
        return "■ 원본 저장 완료 · AI 처리는 별도" if facts.control_mode == "ENDED" else "녹음 대기"
    valid_frames = type(facts.current_accepted_frames) is int and facts.current_accepted_frames > 0
    if (
        facts.generation_match
        and facts.control_mode == "ACTIVE"
        and facts.all_sources_ready
        and facts.accepting
        and valid_frames
    ):
        return "● REC · 녹음 중 · 로컬 저장"
    if valid_frames and facts.generation_match and not facts.all_sources_ready:
        return "시작 중 · 일부 오디오 수락 · 장치 준비 확인 중"
    return "시작 중 · 첫 오디오 블록 대기"


@dataclass(frozen=True, slots=True)
class AIStatus:
    text: str
    reason: str | None = None
    action_id: str | None = None
    can_continue: bool = False


EXECUTION_POLICY_ACTION = "execution_policy"

_ACTIONS = {
    "CONSENT": ("동의/전송 정책 확인", "consent"),
    "AUTH": ("제공업체 키 설정 확인", "auth"),
    "CAPABILITY": ("모델·기능·언어·컨텍스트/사용 조건 확인", "model"),
    "RESOURCE": ("메모리·GPU·로컬 모델·종료 확인", "resource"),
    "BUDGET": ("예산·가격·시각·원장·미정산 확인", "budget"),
    "ABANDONED": ("이전 실행 종료·권한 재확인", "resource"),
}


def _action(reason: str, code: str) -> tuple[str, str] | None:
    if code == "TRANSCRIPTION_REQUIRES_FINALIZED_AUDIO":
        return "원본 확정 필요; 녹음 중이면 정지 후 세션 확정 화면을 확인하세요", "finalize"
    if code == "SUMMARY_REQUIRES_COMPLETE_TRANSCRIPT":
        return "완전한 전사 필요; 전사 화면에서 범위·완료 상태를 확인하세요", "transcription"
    if reason == "RESOURCE" and code == "RESOURCE_GPU_UNAVAILABLE":
        return (
            "GPU 실행 조건을 확인하거나 장치 실행 정책을 직접 선택하세요",
            EXECUTION_POLICY_ACTION,
        )
    if reason == "BUDGET":
        if code in {
            "COST_PRICE_UNKNOWN",
            "COST_PRICE_EXPIRED",
            "COST_BOUND_UNVERIFIED",
            "COST_QUOTE_MISMATCH",
            "COST_QUOTE_EXPIRED",
        }:
            return "검증된 가격·요청 상한 근거 필요; cap 증액만으로 해결되지 않음", "price"
        if code == "COST_CLOCK_INVALID":
            return "시계 기준·비용 이력 확인; 기준 재설정은 별도 명시 확인 필요", "clock"
        if code in {
            "LEDGER_ROLLBACK_DETECTED",
            "COST_LEGACY_UNSCOPED",
            "COST_UNRESOLVED_EXPOSURE",
            "COST_CURRENCY_MISMATCH",
            "COST_PERIOD_CHANGED",
            "BUDGET_SCOPE_MISMATCH",
            "SETTLEMENT_CONFLICT",
            "RESERVATION_MAY_BE_SENT",
        }:
            return "원장·미정산·통화·기간 확인; 비용 이력을 자동 해제하지 않음", "cost_history"
    return _ACTIONS.get(reason)


def ai_status(
    job: JobRecord | None = None,
    *,
    preparation: NormalizedFailure | None = None,
    reader_active: bool | None = None,
    resource_acknowledged: bool = False,
) -> AIStatus:
    if preparation is not None:
        if preparation.outcome_known is not True or preparation.code == "REMOTE_OUTCOME_UNKNOWN":
            return AIStatus(
                "실행 준비 결과 미확인 · 자동 재전송/계속 없음 · 기존 원본·결과 보존",
                reason="REMOTE_UNKNOWN",
            )
        if preparation.code == "DELETION_HISTORY_UNAVAILABLE":
            return AIStatus(
                "실행 준비 차단·작업 미접수 · 삭제 이력 확인 불가 · 새 전송 없음; "
                "삭제 이력을 확인한 뒤 다시 요청하세요",
                action_id="deletion_history",
            )
        reason = CODE_GROUPS.get(preparation.code)
        action = _action(reason or "", preparation.code)
        return AIStatus(
            "실행 준비 차단·작업 미접수 · "
            + preparation.code
            + (" · " + action[0] if action else " · 입력·설정 확인"),
            reason if reason in BLOCK_REASONS else None,
            action[1] if action else None,
        )
    if job is None:
        return AIStatus("AI 대기 · 녹음 조작과 독립적으로 실행합니다.")
    code = job.error_code or ""
    if code not in CODE_GROUPS:
        code = "TASK_FAILED" if code else ""
    prefix = f"AI: {job.state.value}" + (f" · {code}" if code else "")
    if job.blocked_reason == "REMOTE_UNKNOWN":
        return AIStatus(
            prefix
            + " · 결과·비용 미확인, 자동 재전송 없음"
            + (" · 취소 요청됨" if job.cancel_requested else ""),
            "REMOTE_UNKNOWN",
        )
    action = _action(job.blocked_reason or "", code) if job.state.value == "BLOCKED" else None
    if action:
        can_continue = (
            not job.cancel_requested
            and job.attempt_count < 3
            and (
                code not in {"INFERENCE_ACK_PENDING", "DIARIZATION_ACK_PENDING"}
                or resource_acknowledged is True
            )
            and (
                reader_active is False
                or (reader_active is None and job.attempt_count == 0 and job.attempt_id is None)
            )
        )
        refusal = (
            " · 취소 요청됨"
            if job.cancel_requested
            else " · 시도 한도 소진; 명시 새 작업 필요"
            if job.attempt_count >= 3
            else " · 종료 ACK 확인 전 계속 불가"
            if not can_continue
            else ""
        )
        return AIStatus(
            prefix + " · " + action[0] + refusal, job.blocked_reason, action[1], can_continue
        )
    return AIStatus(prefix + " · 기존 원본·결과 보존")


def admission_status(code: str, *, failed: bool = False) -> AIStatus:
    """Admission observation is separate from a durable BLOCKED/error catalog."""
    if code == "DELETION_HISTORY_UNAVAILABLE":
        return AIStatus(
            "삭제 이력 확인 불가 · 새 전송 없음; "
            + (
                "현재 작업 종료 · 이력 확인 후 명시 새 작업으로 다시 요청하세요"
                if failed
                else "작업 입장 보류 · 이력 확인 후 같은 요청을 명시 접수하세요"
            ),
            action_id="deletion_history",
        )
    return AIStatus("작업 입장 상태를 확인하세요 · 기존 원본·결과 보존")
