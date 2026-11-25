"""Connect Qt actions to recording-independent AI and local source playback."""

from __future__ import annotations

import hashlib
import threading
import wave
from collections.abc import Callable
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any
from uuid import uuid4

from PySide6.QtCore import QThreadPool, QTimer

from recoryn.app.ai import AIService
from recoryn.app.inference import LocalSTTProcess
from recoryn.app.status import EXECUTION_POLICY_ACTION, AIStatus, admission_status, ai_status
from recoryn.content import ContentStore, Segment
from recoryn.domain import AudioFormat, StateConflict
from recoryn.jobs import JobStore
from recoryn.jobs.failures import NormalizedFailure, normalize_failure
from recoryn.models.gpu_inventory import PROBE_OWNERS, Inventory
from recoryn.models.resource_catalog import PROVIDER_BACKENDS
from recoryn.models.resources import (
    ESTIMATE_UNKNOWN,
    INTERACTIVE,
    LIVE,
    OBSERVED,
    ResourcePlan,
    ResourceRequest,
    ResourceScheduler,
    ResourceSource,
    plan_static,
    resolve_profile,
)
from recoryn.providers import ExecutionContext, ProviderCapabilities, ProviderError
from recoryn.storage._coordination import root_mutex
from recoryn.storage._safe import mkdir, open_file, safe_path
from recoryn.storage.chunks import verify_bundle
from recoryn.ui import a11y
from recoryn.ui.content import ContentPanel
from recoryn.ui.pcm_playback import PlaybackPcm, SinkPlayback, prepare_playback
from recoryn.ui.tasks import Task

# Device-policy refusals that the user resolves in the execution policy control.
POLICY_CODES = frozenset({"RESOURCE_POLICY_UNVERIFIED", "RESOURCE_GPU_UNSUPPORTED"})
_GUIDANCE = {
    "RESOURCE_POLICY_UNVERIFIED": (
        "로컬 Ollama는 CPU·GPU 사용을 보장할 수 없어 {policy}에서 요약을 시작하지 않습니다. "
        "AI 실행 정책에서 GPU_WITH_CPU_FALLBACK_ALLOWED를 직접 선택한 뒤 새로 요청하세요"
        " · 정책은 자동으로 바뀌지 않으며, 앱을 다시 시작하면 기본값 CPU_ONLY로 돌아갑니다"
    ),
    "RESOURCE_GPU_UNSUPPORTED": (
        "화자 구분은 CPU로만 실행하므로 {policy}에서 시작하지 않습니다. "
        "CPU를 허용하는 AI 실행 정책을 직접 선택한 뒤 새로 요청하세요 · 자동 변경 없음"
    ),
}


def policy_block_status(
    code: str, policy: str, prefix: str = "실행 준비 차단·작업 미접수"
) -> AIStatus:
    """A device-policy refusal points at the execution policy control (G-P07 action)."""
    return AIStatus(
        f"{prefix} · {code} · " + _GUIDANCE[code].format(policy=policy),
        "CAPABILITY",
        EXECUTION_POLICY_ACTION,
    )


# The production observer factory; tests replace it with fakes (no nvidia-smi/RAM API).
make_observer: Callable[[], Any] = Inventory


def _mib(value: int | None) -> str:
    return "?" if value is None else f"{value // 2**20:,} MiB"


_PHASE_TEXT = {
    "WAITING": "자원 대기",
    "ACTIVE": "자원 사용 중",
    "REAP_PENDING": "작업자 종료 ACK 대기 · RESOURCE_LEASE_HELD · 다음 무거운 작업 배정 안 함",
    "RELEASED": "자원 해제됨",
}


def resource_detail(view: dict[str, Any] | None, profile_text: str | None) -> str:
    """Estimate, device, observation and lease facts of an owned Job (G11 section 6).

    UNKNOWN stays "메모리 요구량 미확인" during and after the run; an unobserved RAM is
    shown as such, never as a free value. Nothing here changes a setting.
    """
    if view is None or view.get("estimate_status") is None:
        return (profile_text or "메모리 요구량 미확인") + " · 자원 계획은 실행 직전에 다시 관측"
    parts = []
    if view["estimate_status"] == ESTIMATE_UNKNOWN:
        parts.append("메모리 요구량 미확인")
    else:
        needed = f"계획 요구량 RAM {_mib(view['planned_ram'])}"
        if view["device"] == "cuda":
            needed += f" · VRAM {_mib(view['planned_vram'])}"
        parts.append(needed)
    if view["device"] == "cuda":
        parts.append(f"장치 GPU {view['gpu_name']} (CUDA 논리 index {view['cuda_index']})")
        parts.append(
            f"VRAM 여유 {_mib(view['vram_free'])} · 여유 기준 {_mib(view['gpu_headroom'])}"
        )
    else:
        parts.append("장치 CPU")
    if view["ram_state"] == OBSERVED:
        parts.append(f"RAM 여유 {_mib(view['ram_free'])}")
    else:
        parts.append(f"RAM 관측 {view['ram_state']}")
    parts.append(_PHASE_TEXT[view["phase"]])
    if view.get("outcome_unknown"):
        parts.append("결과 미확인 유지")
    return " · ".join(parts)


def resource_note(
    request: ResourceRequest | None,
    selected: str | None,
    view: dict[str, Any] | None = None,
    profile_text: str | None = None,
) -> str:
    """The policy a Job was admitted with, never the control's current value."""
    if request is None:
        return "실행 정책: 이 실행에서 접수한 기록 없음"
    if request.backend == "REMOTE":
        return "원격 실행 — 이 PC의 장치 정책 적용 안 됨"
    if request.backend == "OLLAMA":
        text = f"로컬 Ollama · 접수 정책 {request.policy} · 장치 미보장·서버 메모리 통제 불가"
    else:
        text = f"이 PC · 접수 정책 {request.policy} · " + resource_detail(view, profile_text)
    if selected and selected != request.policy:
        text += f" · 현재 선택 {selected}은 새 요청부터 적용"
    return text


def local_source(
    policy: str,
    native_cuda: Callable[[], bool],
    status: Callable[[], str],
    root: Path,
    *,
    runtime_blocked: bool,
) -> ResourceSource:
    """Where CUDA would come from for a local STT request (L-P07, G11 section 6).

    CPU_ONLY consults neither the runtime nor the CUDA source. A failure or pending
    change of this runtime install excludes only that runtime, never a verified source
    CUDA (``gpu_source``).
    """
    from recoryn.models.gpu_runtime import gpu_source

    where = gpu_source(policy, native_cuda, status, runtime_blocked=runtime_blocked)
    state = "NOT_CHECKED" if policy == "CPU_ONLY" else status()
    return ResourceSource(where, state, root if where == "runtime" else None)


POLICY_NAME = "AI 실행 정책"
POLICY_DESCRIPTION = (
    "새 요청에 적용, 진행 중인 작업은 기존 정책 유지. "
    "CPU_ONLY는 GPU를 쓰지 않고, GPU_ONLY는 GPU가 없을 때 CPU로 바꾸지 않습니다. "
    "AUTO(GPU_WITH_CPU_FALLBACK_ALLOWED)는 GPU 우선이며 CPU 사용을 허용합니다. "
    "정책은 자동으로 바뀌지 않으며, 직접 고른 정책은 이 PC 사용자 설정에 저장됩니다."
)
_ANNOUNCEMENT_TEXT = {
    "QUEUED": "AI 작업 대기",
    "RUNNING": "AI 작업 실행 중",
    "CANCEL_REQUESTED": "취소 요청됨 · 종료 확인 대기",
    "LOCAL_ACK": "로컬 종료 확인",
    "REMOTE_UNKNOWN": "원격 결과·비용 미확인",
    "BLOCKED": "AI 작업 차단",
    "BACKOFF": "재시도 대기",
    "ABANDONED": "중단된 작업 · 확인 필요",
    "FAILED": "AI 작업 실패",
}


def job_announcement(job: Any) -> str | None:
    """Which fact a Job state announces (G12 5.2): a local cancel ACK is never a remote
    cancellation, and a cancel request on an UNKNOWN Job stays UNKNOWN."""
    state = job.state.value
    if state == "BLOCKED":
        if job.blocked_reason == "REMOTE_UNKNOWN":
            return "REMOTE_UNKNOWN"
        return "ABANDONED" if job.blocked_reason == "ABANDONED" else "BLOCKED"
    return {
        "QUEUED": "QUEUED",
        "RUNNING": "RUNNING",
        "CANCEL_REQUESTED": "CANCEL_REQUESTED",
        "CANCELLED": "LOCAL_ACK",
        "BACKOFF": "BACKOFF",
        "FAILED": "FAILED",
    }.get(state)


def announcement_version(job: Any) -> tuple[object, ...]:
    """A new meaning is a new state version, state, reason, code or cancel request."""
    return (
        job.job_id,
        job.state_version,
        job.state.value,
        job.blocked_reason,
        job.error_code,
        job.cancel_requested,
    )


def announcement_text(kind: str, job: Any) -> str:
    text = _ANNOUNCEMENT_TEXT[kind]
    if kind == "REMOTE_UNKNOWN" and job.cancel_requested:
        text = "취소 요청됨 · " + text
    return text


class OwnedSTT:
    """Creates one LocalSTTProcess per Job attempt from the lease's plan (G11 5.1).

    The worker is created only after the lease grant, with the plan's device, logical
    CUDA ordinal and compute type, and closed (exit ACK) before the lease is released.
    No warm worker is kept between Jobs.
    """

    def __init__(self, model_path: Path, *, source: ResourceSource, semantic_device: str) -> None:
        self.model_path = model_path
        self.resource_source = source
        self.semantic_device = semantic_device
        self.last: Any = None

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            "faster_whisper", transcription=True, segment_timestamps=True, audio_formats=("wav",)
        )

    def open(self, plan: ResourcePlan) -> Any:
        cuda = plan.device == "cuda"
        runtime = (
            self.resource_source.runtime_root if cuda and plan.cuda_source == "runtime" else None
        )
        options: dict[str, Any] = {"device": plan.device, "gpu_runtime": runtime}
        options["device_index"] = plan.cuda_index if cuda else None
        options["compute_type"] = plan.compute_type
        worker = LocalSTTProcess(self.model_path, **options)
        self.last = worker
        return worker


class OwnedDiarization:
    """Creates the CPU-only diarization worker inside the lease (G11 5.1)."""

    def __init__(self, config: Any) -> None:
        self.config = config

    def capabilities(self) -> dict[str, Any]:
        return {"provider_id": "sherpa_onnx", "diarization": True}

    def open(self, plan: ResourcePlan) -> Any:
        from recoryn import diarization

        return diarization.LocalDiarizationProcess(self.config)


class DesktopAI:
    def __init__(self, window: Any) -> None:
        self.window = window
        self.store = ContentStore(window.library)
        self._history = JobStore(window.library.db_path)
        self.service: AIService | None = None
        # The factory of the last local STT Job; its worker lived only inside the lease.
        self._local_factory: OwnedSTT | None = None
        # L01 D7: Recoryn plays verified PCM itself; no Qt media decoder backend.
        self.playback = SinkPlayback(window, on_error=self._report_playback)
        self._playback_generation = 0
        # L01 D10: the runtime install (folder generation) a worker of this run failed
        # on is not offered again; a newly installed runtime is. Only the local worker's
        # own explicit GPU_RUNTIME_* answer counts, never stored job history.
        self._gpu_failed: tuple[int, int] | None = None
        self._local_generation: tuple[int, int] | None = None
        self.pool = QThreadPool(window)
        self.pool.setMaxThreadCount(1)
        self.busy = False
        self._tasks: set[Task] = set()
        self._shutting_down = False
        self._preparation_cancel = threading.Event()
        self._live_jobs: dict[str, str] = {}
        self._live_snapshots: dict[str, frozenset[str]] = {}
        self._live_blocked: set[str] = set()
        self._live_nonces: dict[str, str] = {}
        self.panel = ContentPanel(self.store, self.operation)
        window.tabs.addTab(self.panel, "전사 · 요약 · 근거")
        self._announce_counter = 0
        # The window creates its policy control after this bridge: name it on the next
        # event-loop turn (and again from tick, idempotently).
        QTimer.singleShot(0, self._name_policy_control)
        self.panel.transcribeRequested.connect(self.transcribe)
        self.panel.summarizeRequested.connect(self.summarize)
        self.panel.cancelRequested.connect(self.cancel)
        self.panel.retryTranscribeRequested.connect(self.retry_transcribe)
        self.panel.retrySummaryRequested.connect(self.retry_summary)
        self.panel.diarizeRequested.connect(self.diarize)
        self.panel.seekRequested.connect(self.seek)
        self.panel.blockedOpenRequested.connect(self.open_blocked_action)
        self.panel.blockedContinueRequested.connect(self.continue_blocked)
        self._blocked_target: tuple[str, str, int, str] | None = None
        self._preparation_action: tuple[str, str, str] | None = None
        self._job_options: dict[str, tuple[str, str | None, str]] = {}
        self._selected_ai_session: str | None = None
        self._last_snapshot = ""
        self.privacy: Any = None

    def operation(
        self,
        action: Callable[[], Any],
        done: Callable[[Any], None] | None = None,
        *,
        failed: Callable[[str], None] | None = None,
        preparation_kind: str = "stt",
        continuing: bool = False,
    ) -> bool:
        """AI preparation and editing never occupy the recording control lane."""
        if self.busy or self._shutting_down:
            return False
        self.busy = True
        selected_at_start = self.window.selected_session()

        def guarded() -> Any:
            try:
                return action()
            except Exception as error:
                if isinstance(error, StateConflict) and error.args == (
                    "DELETION_HISTORY_UNAVAILABLE",
                ):
                    return NormalizedFailure(
                        "DELETION_HISTORY_UNAVAILABLE",
                        outcome_known=normalize_failure(error).outcome_known,
                    )
                normalized = normalize_failure(error)
                if normalized.code != "TASK_FAILED":
                    return normalized
                if isinstance(error, StateConflict) and error.args == ("CONTINUE_PLAN_CHANGED",):
                    return AIStatus("설정이 달라 새 작업 필요 · 기존 작업·결과 보존")
                raise

        task = Task(guarded)
        self._tasks.add(task)

        def finished(value: Any) -> None:
            self._tasks.discard(task)
            self.busy = False
            if isinstance(value, (NormalizedFailure, AIStatus)):
                if not self._shutting_down:
                    if self.window.selected_session() == selected_at_start:
                        self._show_preparation(
                            value, kind=preparation_kind, preserve_job=continuing
                        )
                    if failed:
                        failed(
                            value.code
                            if isinstance(value, NormalizedFailure)
                            else "CONTINUE_PLAN_CHANGED"
                        )
                return
            if not self._shutting_down and done:
                done(value)

        def failure(code: str) -> None:
            self._tasks.discard(task)
            self.busy = False
            if not self._shutting_down:
                if failed:
                    failed(code)
                self.panel.job_status.setText("AI 작업 중단: " + code + " · 원본은 보존됩니다.")

        task.signals.finished.connect(finished)
        task.signals.failed.connect(failure)
        self.pool.start(task)
        return True

    def attach_privacy(self, panel: Any) -> None:
        self.privacy = panel
        self.window.tabs.addTab(panel, "제공업체 · 동의 · 비용")

        def selected(current: Any, previous: Any) -> None:
            session_id = self.window.selected_session()
            if session_id is None:
                panel.selection_pending()
                # clear/rebuild/select is one logical refresh, not an A→None→A
                # user transition. Real deselection still settles to None.
                QTimer.singleShot(
                    0, panel, lambda: panel.select_session(self.window.selected_session())
                )
            else:
                panel.select_session(session_id)

        self.window.sessions.currentItemChanged.connect(selected)
        panel.select_session(self.window.selected_session())

    def _service(self) -> AIService:
        if self.service is None:
            self.service = AIService(
                self.window.library,
                self.store,
                resources=ResourceScheduler(observe=make_observer()),
            )
        return self.service

    def selection(self, session_id: str) -> None:
        if getattr(self, "_selected_ai_session", None) != session_id:
            self._blocked_target = self._preparation_action = None
            self._selected_ai_session = session_id
        if self.privacy is not None:
            self.privacy.select_session(session_id)
        self.panel.load(session_id)

    def _show_preparation(
        self,
        failure: NormalizedFailure | AIStatus,
        *,
        kind: str = "stt",
        preserve_job: bool = False,
    ) -> None:
        if not isinstance(failure, NormalizedFailure):
            status = failure
        elif failure.code in POLICY_CODES and failure.outcome_known is True:
            status = policy_block_status(failure.code, self._selected_policy())
        else:
            status = ai_status(preparation=failure)
        announcer = getattr(getattr(self, "panel", None), "announcer", None)
        if isinstance(failure, NormalizedFailure) and announcer is not None:
            self._announce_counter = getattr(self, "_announce_counter", 0) + 1
            unknown = failure.outcome_known is not True or failure.code == "REMOTE_OUTCOME_UNKNOWN"
            announcer.announce(
                "content",
                self.panel.job_status,
                "REMOTE_UNKNOWN" if unknown else "PREPARATION_BLOCKED",
                status.text,
                version=("preparation", self._announce_counter, failure.code),
            )
        if (
            preserve_job
            and isinstance(failure, NormalizedFailure)
            and failure.outcome_known is True
            and status.reason != "REMOTE_UNKNOWN"
        ):
            try:
                job = self._current_blocked()
                previous = ai_status(
                    job,
                    reader_active=self._history.local_reader_active(job.job_id),
                    resource_acknowledged=self._resource_acknowledged(job),
                )
                action = status.action_id or previous.action_id
                if self._blocked_target and action:
                    self._blocked_target = (*self._blocked_target[:3], action)
                    self.panel.show_ai_status(
                        AIStatus(
                            status.text + " · 기존 Job BLOCKED 유지",
                            status.reason,
                            action,
                            previous.can_continue,
                        )
                    )
                    return
            except (StateConflict, KeyError):
                pass
        self._blocked_target = None
        selected = self.window.selected_session()
        self._preparation_action = (
            (selected, kind, status.action_id) if selected and status.action_id else None
        )
        self.panel.show_ai_status(status)

    def _selected_policy(self) -> str:
        policy = getattr(self.window, "device_policy", None)
        return policy.currentText() if policy is not None else "CPU_ONLY"

    def _selected_provider(self, kind: str) -> str | None:
        controls = getattr(self.privacy, "controls", None)
        if kind == "diarization":
            return "sherpa_onnx"  # the only diarization backend (no CT2 diarization)
        if self.privacy is None:
            return "faster_whisper" if kind == "stt" else None
        if not isinstance(controls, dict) or kind not in controls:
            return None
        value = controls[kind].provider.currentData()
        return value if isinstance(value, str) else None

    @staticmethod
    def _request(
        kind: str, provider: str | None, policy: str, *, provisional: bool = False
    ) -> ResourceRequest | None:
        backend = PROVIDER_BACKENDS.get(provider or "")
        if backend is None:
            return None  # undecided until the prepared configuration names the provider
        return ResourceRequest(kind, backend, policy, priority=LIVE if provisional else INTERACTIVE)

    def _refused(self, request: ResourceRequest | None, kind: str, expected: Any) -> bool:
        """Static device-policy admission (G-P11a) before attestation, prepare_execution,
        an adapter or a Job: a refusal is a preparation block with nothing sent or read."""
        if request is None:
            return False
        try:
            plan_static(request)
        except StateConflict as error:
            self._show_preparation(
                normalize_failure(error), kind=kind, preserve_job=expected is not None
            )
            return True
        return False

    def _current_blocked(self) -> Any:
        target = self._blocked_target
        if target is None or self.window.selected_session() != target[0]:
            raise StateConflict("JOB_VERSION_CHANGED")
        job = self._history.get(target[1])
        if job.state_version != target[2] or job.state.value != "BLOCKED":
            raise StateConflict("JOB_VERSION_CHANGED")
        return job

    def _resource_acknowledged(self, job: Any) -> bool:
        # A worker that did not exit keeps its lease held; only a later successful
        # reap releases it. A logical Job reader receipt alone is insufficient.
        if job.error_code not in ("INFERENCE_ACK_PENDING", "DIARIZATION_ACK_PENDING"):
            return False
        scheduler = getattr(getattr(self, "service", None), "scheduler", None)
        held = getattr(scheduler, "held", None)
        return job.job_id not in (held() if callable(held) else ())

    def open_blocked_action(self) -> None:
        """Only change the visible settings location, never authorization."""
        if self._blocked_target is not None:
            try:
                job = self._current_blocked()
            except (KeyError, StateConflict):
                self.panel.show_ai_status(AIStatus("상태가 바뀌었습니다. 작업을 다시 선택하세요."))
                return
            status = ai_status(
                job,
                reader_active=self._history.local_reader_active(job.job_id),
                resource_acknowledged=self._resource_acknowledged(job),
            )
            kind = "summary" if job.kind == "summarization" else "stt"
            action = self._blocked_target[3] if self._blocked_target else status.action_id
        elif self._preparation_action is not None:
            session, kind, action = self._preparation_action
            if session != self.window.selected_session():
                return
        else:
            return
        if action == "deletion_history":
            self.window.tabs.setCurrentWidget(self.window.details)
            note = (
                "삭제 이력 확인 불가: 삭제 journal·저장 장치 상태를 확인하세요. "
                "이력을 임의로 지우면 원본이 부활할 수 있습니다. 새 전송은 하지 않았습니다."
            )
            if not self.window.details.toPlainText().endswith(note):
                self.window.details.appendPlainText(note)
            self.window.details.setFocus()
        elif action == "finalize":
            self.window.tabs.setCurrentWidget(self.window.details)
            target = (
                self.window.finalize_button
                if self.window.finalize_button.isEnabled()
                else self.window.details
            )
            target.setFocus()
        elif action == "transcription":
            self.window.tabs.setCurrentWidget(self.panel)
            self.panel.transcribe_button.setFocus()
        elif action == "resource":
            self.window.tabs.setCurrentWidget(self.window.model_panel)
            self.window.model_panel.installed.setFocus()
        elif action == EXECUTION_POLICY_ACTION:
            policy = self.window.device_policy
            parent = policy.parentWidget()
            while parent is not None and self.window.tabs.indexOf(parent) < 0:
                parent = parent.parentWidget()
            if parent is not None:
                self.window.tabs.setCurrentWidget(parent)
            policy.setFocus()
        elif action and self.privacy is not None:
            self.window.tabs.setCurrentWidget(self.privacy)
            self.privacy.focus_blocked_action(kind, action)

    def continue_blocked(self) -> None:
        if self.busy or self._shutting_down:
            return
        try:
            job = self._current_blocked()
            status = ai_status(
                job,
                reader_active=self._history.local_reader_active(job.job_id),
                resource_acknowledged=self._resource_acknowledged(job),
            )
            if not status.can_continue or job.kind not in {
                "transcription",
                "streaming_transcription",
                "summarization",
            }:
                return
        except (StateConflict, KeyError):
            self.panel.show_ai_status(AIStatus("상태가 바뀌었습니다. 작업을 다시 선택하세요."))
            return
        kind, nonce, template = self._job_options.get(
            job.job_id,
            (
                "summary"
                if job.kind == "summarization"
                else "live"
                if job.kind == "streaming_transcription"
                else "stt",
                None,
                self.panel.templates.currentData(),
            ),
        )
        expected = (job.job_id, job.state_version)
        if kind == "summary":
            self.summarize(template, expected=expected, nonce=nonce)
        else:
            self._transcribe(
                session_id=self._blocked_target[0] if self._blocked_target else None,
                provisional=kind == "live",
                expected=expected,
                nonce=nonce,
            )

    @staticmethod
    def _context_factory(context: ExecutionContext) -> Any:
        def create(cancel: threading.Event) -> ExecutionContext:
            return ExecutionContext(
                cancel=cancel,
                headers=context.headers,
                reservation_factory=context.reservation_factory,
            )

        return create

    def transcribe(self) -> None:
        self._transcribe()

    def _transcribe(
        self,
        *,
        session_id: str | None = None,
        provisional: bool = False,
        retry: bool = False,
        expected: tuple[str, int] | None = None,
        nonce: str | None = None,
    ) -> None:
        window = self.window
        session_id = session_id or window.selected_session()
        if session_id is None or self.busy or self._shutting_down:
            return
        fixed_session = session_id
        chunks = frozenset(item.chunk_id for item in window.library.chunks(session_id))
        if (
            provisional
            and not expected
            and (not chunks or self._live_snapshots.get(session_id) == chunks)
        ):
            return
        policy = self._selected_policy()  # captured once, on the UI thread, at request time
        early = self._request(
            "stt", self._selected_provider("stt"), policy, provisional=provisional
        )
        if self._refused(early, "stt", expected):
            if provisional:
                self._live_blocked.add(session_id)
            return
        try:
            if self.privacy is not None:
                execution = self.privacy.prepare_execution("stt", fixed_session, threading.Event())
                config, context = execution.config, execution.context
                config_key, gateway = execution.config_key, execution.gateway
            else:
                config, context, config_key, gateway = None, ExecutionContext(), "local", None
        except Exception as error:
            self._show_preparation(normalize_failure(error), preserve_job=expected is not None)
            if provisional:
                self._live_blocked.add(session_id)
            return
        resources = self._request(
            "stt",
            "faster_whisper" if config is None else config.provider_id,
            policy,
            provisional=provisional,
        )
        if resources is None or self._refused(resources, "stt", expected):
            if resources is None:
                self._show_preparation(
                    NormalizedFailure("CAPABILITY_UNSUPPORTED"), preserve_job=expected is not None
                )
            if provisional:
                self._live_blocked.add(session_id)
            return
        model = window.local_model.text()
        # Read on the UI thread: a queued GPU runtime install/removal excludes the runtime.
        # A removal is only queued while this bridge is idle, so the two never interleave.
        gpu_change_pending = bool(getattr(window.model_panel, "gpu_busy", False))
        preparation_cancel = threading.Event()
        self._preparation_cancel = preparation_cancel
        if expected is None:
            nonce = (
                uuid4().hex if retry else self._live_nonces.get(session_id) if provisional else None
            )

        def check_cancel() -> None:
            if preparation_cancel.is_set():
                raise StateConflict("CANCELLED")

        def submit() -> str:
            check_cancel()
            service = self._service()
            options: dict[str, Any] = {
                "provisional": provisional,
                "chunk_ids": chunks,
                "request_nonce": nonce,
                "expected_job_id": expected[0] if expected else None,
                "expected_job_version": expected[1] if expected else None,
            }
            if config is None or config.provider_id == "faster_whisper":
                if not model:
                    raise StateConflict("LOCAL_MODEL_REQUIRED")
                hasher = hashlib.sha256()
                for name in ("model.bin", "config.json", "tokenizer.json"):
                    with open_file(Path(model).absolute() / name, "rb") as stream:
                        while block := stream.read(1024 * 1024):
                            check_cancel()
                            hasher.update(block)
                digest = hasher.hexdigest()
                from recoryn.models.gpu_runtime import GpuRuntimeManager
                from recoryn.transcription import cuda_runtime_available

                # L01 D9/D10: a GPU is a candidate only with a CUDA-capable CTranslate2,
                # either the installed one (source run) or the user's verified runtime.
                runtime = GpuRuntimeManager(self.window.library.root / "gpu-runtime")
                self.observe_gpu_failure()
                generation = runtime.generation()
                failed = self._gpu_failed is not None and self._gpu_failed == generation
                source = local_source(
                    policy,
                    cuda_runtime_available,
                    runtime.status,
                    runtime.root,
                    runtime_blocked=gpu_change_pending or failed,
                )
                where = source.cuda_source
                request = replace(resources, model_identity=digest)
                # Plan now for the semantic key (digest:device, unchanged by G11); the lease
                # re-observes at dispatch and keeps this device or refuses, never swaps it.
                prepared = service.scheduler.prepare(request, source)
                device = prepared.device
                key = digest + ":" + device
                factory = OwnedSTT(Path(model).absolute(), source=source, semantic_device=device)
                self._local_factory = factory
                self._local_generation = (
                    generation if device == "cuda" and where == "runtime" else None
                )
                check_cancel()
                return service.transcribe(
                    fixed_session, factory, config_key=key, resource_request=request, **options
                )
            from recoryn.transcription import GeminiTranscriber, OpenAITranscriber

            adapter = OpenAITranscriber if config.provider_id == "openai" else GeminiTranscriber
            assert gateway is not None
            provider = adapter(gateway, config)
            check_cancel()
            return service.transcribe(
                fixed_session,
                provider,
                config_key=config_key,
                resource_request=resources,
                context_factory=self._context_factory(context),
                **options,
            )

        def submitted(job_id: str) -> None:
            self._last_snapshot = ""
            self._job_options[job_id] = ("live" if provisional else "stt", nonce, "")
            if expected:
                self._live_blocked.discard(fixed_session)
            if provisional:
                self._live_jobs[fixed_session] = job_id
                self._live_snapshots[fixed_session] = chunks
            self.panel.job_status.setText(
                ("임시 전사" if provisional else "전체 정정 전사")
                + " 작업 등록: "
                + job_id[:12]
                + " · "
                + resource_note(resources, policy)
            )

        self.operation(
            submit,
            submitted,
            failed=lambda code: self._live_blocked.add(fixed_session) if provisional else None,
            continuing=expected is not None,
        )

    def summarize(
        self,
        template: str,
        *,
        retry: bool = False,
        expected: tuple[str, int] | None = None,
        nonce: str | None = None,
    ) -> None:
        window = self.window
        session_id = window.selected_session()
        if session_id is None or self.busy or self.privacy is None:
            self.panel.job_status.setText("요약 제공업체와 데이터 범위를 설정하세요.")
            return
        policy = self._selected_policy()
        # T31: the strict Ollama refusal precedes the attestation check, so a refused
        # request never asks the local server anything.
        if self._refused(
            self._request("summary", self._selected_provider("summary"), policy),
            "summary",
            expected,
        ):
            return
        try:
            if (
                self.window.model_panel.ollama_owned
                and self.privacy.controls["summary"].provider.currentData() == "ollama"
            ):
                self.window.model_panel.checked_attestation()
            execution = self.privacy.prepare_execution("summary", session_id, threading.Event())
            config, context = execution.config, execution.context
            config_key, gateway = execution.config_key, execution.gateway
        except Exception as error:
            self._show_preparation(
                normalize_failure(error), kind="summary", preserve_job=expected is not None
            )
            return
        resources = self._request("summary", config.provider_id, policy)
        if resources is None or self._refused(resources, "summary", expected):
            if resources is None:
                self._show_preparation(
                    NormalizedFailure("CAPABILITY_UNSUPPORTED"),
                    kind="summary",
                    preserve_job=expected is not None,
                )
            return
        if expected is None:
            nonce = uuid4().hex if retry else None
        preparation_cancel = threading.Event()
        self._preparation_cancel = preparation_cancel

        def submit() -> str:
            if preparation_cancel.is_set():
                raise StateConflict("CANCELLED")
            from recoryn.summarization import (
                AnthropicSummarizer,
                GeminiSummarizer,
                OllamaSummarizer,
                OpenAISummarizer,
            )

            adapters = {
                "ollama": OllamaSummarizer,
                "openai": OpenAISummarizer,
                "anthropic": AnthropicSummarizer,
                "gemini": GeminiSummarizer,
            }
            provider = adapters[config.provider_id](gateway, config)
            if preparation_cancel.is_set():
                raise StateConflict("CANCELLED")
            return self._service().summarize(
                session_id,
                provider,
                config_key=config_key,
                resource_request=resources,
                template=template,
                context_factory=self._context_factory(context),
                request_nonce=nonce,
                expected_job_id=expected[0] if expected else None,
                expected_job_version=expected[1] if expected else None,
            )

        def submitted(job_id: str) -> None:
            self._last_snapshot = ""
            self._job_options[job_id] = ("summary", nonce, template)
            self.panel.job_status.setText(
                "요약 작업 등록: " + job_id[:12] + " · " + resource_note(resources, policy)
            )

        self.operation(
            submit, submitted, preparation_kind="summary", continuing=expected is not None
        )

    def _name_policy_control(self) -> None:
        """G-P12 decision 4 (a): only accessibility text; the value is never touched."""
        policy = getattr(getattr(self, "window", None), "device_policy", None)
        if policy is None or not a11y.alive(policy) or policy.accessibleName() == POLICY_NAME:
            return
        a11y.name(policy, POLICY_NAME, POLICY_DESCRIPTION)

    def _confirm_retry(self) -> bool:
        selected = getattr(getattr(self, "window", None), "selected_session", None)
        opened = selected() if callable(selected) else None
        return a11y.confirm(
            self.window,
            "새 AI 작업으로 명시 재실행",
            "이전 결과·취소·원격 UNKNOWN 이력을 유지한 채 새 작업을 실행합니다. "
            "원격 처리와 비용이 미확인이라면 중복 처리·과금이 발생할 수 있습니다. "
            "현재 권한과 새 비용 예약을 검사하여 실행할까요?",
            still_current=lambda: (selected() if callable(selected) else None) == opened,
            fallback=getattr(getattr(self, "panel", None), "versions", None),
        )[0]

    def retry_transcribe(self) -> None:
        if not self.busy and self._confirm_retry():
            self._transcribe(retry=True)

    def retry_summary(self, template: str) -> None:
        if not self.busy and self._confirm_retry():
            self.summarize(template, retry=True)

    def retry_live(self) -> None:
        session = self.window.recorder.session_id
        if session and not self.busy and self._confirm_retry():
            self._live_blocked.discard(session)
            self._live_jobs.pop(session, None)
            self._live_snapshots.pop(session, None)
            self._live_nonces[session] = uuid4().hex
            self.window.live_stt.setChecked(True)

    def diarize(self) -> None:
        """Annotate one explicit source range through the existing fenced runner."""
        if self.busy or self.panel.revision is None:
            return
        revision = deepcopy(self.panel.revision)
        source = deepcopy(self.panel.diarization_ranges.currentData())
        if not revision["complete"] or source is None:
            self.panel.job_status.setText(
                "전체 정정/편집 전사와 시간 매핑이 있는 구간을 선택하세요."
            )
            return
        if not self.window.diarization_approval.isChecked():
            self.panel.job_status.setText(
                "AI 설정에서 로컬 모델 manifest·SHA256·라이선스·CPU 사용을 확인하세요."
            )
            return
        policy = self._selected_policy()
        resources = self._request("diarization", self._selected_provider("diarization"), policy)
        if resources is None or self._refused(resources, "stt", None):
            if resources is None:
                self._show_preparation(NormalizedFailure("CAPABILITY_UNSUPPORTED"))
            return
        from recoryn.diarization import DiarizationConfig

        try:
            config = DiarizationConfig(
                Path(self.window.diarization_manifest.text()).absolute(),
                self.window.diarization_hash.text().strip(),
                license_accepted=True,
            )
        except Exception:
            self.panel.job_status.setText("화자 분리 manifest 경로와 신뢰한 SHA256을 확인하세요.")
            return
        selection = self.store.selection_state(revision["session_id"])
        expected = selection["transcript_id"]
        expected_version = selection["transcript_version"]
        if expected != revision["revision_id"]:
            expected = uuid4().hex  # browsing an old revision produces a candidate
        preparation_cancel = threading.Event()
        self._preparation_cancel = preparation_cancel

        def submit() -> str:
            if preparation_cancel.is_set():
                raise StateConflict("CANCELLED")
            service = self._service()
            worker = OwnedDiarization(config)
            admitted = service.admit_diarization(resources, worker)  # before the Job exists
            job = service.jobs.create("diarization", uuid4().hex)
            service.jobs.bind_session(job.job_id, revision["session_id"])
            service.capture_diarization(job.job_id, admitted)

            def task(attempt: Any, cancel: threading.Event) -> str:
                from recoryn.diarization import DiarizationRequest, assign_speakers

                # Dispatch re-check, lease grant, worker after the grant, exit ACK before
                # release (the same owned path as transcription).
                with service.owned_worker(
                    admitted, worker, attempt, cancel, revision["session_id"]
                ) as use:
                    if cancel.is_set():
                        raise ProviderError("CANCELLED")
                    path = self._checked_playback_path(revision["session_id"], source)
                    derived = self._diarization_audio(revision["session_id"], path, cancel)
                    digest = hashlib.sha256(derived.read_bytes()).hexdigest()
                    request = DiarizationRequest(derived, source["offset_ms"], source["track_id"])
                    provider = use()
                    try:
                        result = provider.diarize(request, ExecutionContext(cancel=cancel))
                    finally:
                        provider.close()
                    if cancel.is_set() or not result.complete:
                        raise ProviderError(result.error_code or "CANCELLED")
                    if (
                        result.audio_sha256 != digest
                        or result.model_manifest_sha256 != config.manifest_sha256
                    ):
                        raise ProviderError("RESULT_INVALID")
                    segments = assign_speakers(
                        tuple(Segment(**segment) for segment in revision["segments"]), result.turns
                    )
                    coverage = deepcopy(revision["coverage"])
                    checkpoint = coverage.setdefault("checkpoint", {})
                    checkpoint["diarization"] = {
                        "range": source,
                        "audio_path": derived.relative_to(self.window.library.root).as_posix(),
                        "audio_sha256": digest,
                        "manifest_sha256": config.manifest_sha256,
                        "device": "cpu",
                        "algorithm": "equal-channel-downmix-linear-resample-v1",
                        "complete": True,
                        "anonymous_estimate": True,
                        "warnings": list(result.warnings),
                        "turns": [asdict(turn) for turn in result.turns],
                    }
                    return self.store.publish_transcript(
                        service.jobs,
                        attempt,
                        revision["session_id"],
                        segments,
                        kind=revision["kind"],
                        parent_revision_id=revision["revision_id"],
                        expected_active=expected,
                        audio_revision_id=revision.get("audio_revision_id"),
                        coverage=coverage,
                        expected_transcript_version=expected_version,
                    )

            if not service.runner.submit(job.job_id, task):
                service.jobs.cancel(job.job_id)
                raise StateConflict("AI_QUEUE_FULL_OR_JOB_NOT_READY")
            return job.job_id

        self.operation(
            submit,
            lambda job: self.panel.job_status.setText(
                "선택 구간 익명 화자 추정 등록: "
                + job[:12]
                + " · 원문·기존 버전은 보존됩니다 · "
                + resource_note(resources, policy)
            ),
        )

    def _diarization_audio(self, session_id: str, path: Path, cancel: threading.Event) -> Path:
        from recoryn.audio import decode_pcm, downmix_mono, encode_pcm, resample_linear

        with open_file(path, "rb") as stream, wave.open(stream, "rb") as audio:
            fmt = AudioFormat(audio.getframerate(), audio.getnchannels())
            frames = audio.getnframes()
            if (
                audio.getsampwidth() != 2
                or frames <= 0
                or frames * 1000 > fmt.sample_rate * 300_000
                or frames * fmt.frame_bytes > 8 * 1024 * 1024
            ):
                raise ProviderError("DIARIZATION_INPUT_TOO_LARGE")
            payload = audio.readframes(frames)
        mono = downmix_mono(decode_pcm(payload, fmt))
        samples = resample_linear(mono, fmt.sample_rate, 16000)
        if cancel.is_set():
            raise ProviderError("CANCELLED")
        library = self.window.library
        output = safe_path(
            library.root, "sessions", session_id, "derived", "speaker-" + uuid4().hex
        )
        with root_mutex(library.root):
            library.get_session(session_id)
            mkdir(output)
        destination = safe_path(output, "audio.wav")
        with open_file(destination, "xb") as stream, wave.open(stream, "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(
                encode_pcm(tuple((sample,) for sample in samples), AudioFormat(16000, 1))
            )
        return destination

    def cancel(self) -> None:
        self._preparation_cancel.set()
        self.window.live_stt.setChecked(False)
        session_id = self.window.selected_session()
        if self.service is not None and session_id is not None:
            service = self.service
            # Queue the durable cancel on the independent AI lane even while
            # cooperative preparation is unwinding. Recording stop stays free.
            task = Task(lambda: service.cancel_session(session_id))
            self._tasks.add(task)
            task.signals.finished.connect(lambda value: self._tasks.discard(task))
            task.signals.failed.connect(lambda code: self._tasks.discard(task))
            self.pool.start(task)
            self.panel.job_status.setText(
                "취소 요청됨 · 로컬 종료 확인과 원격 UNKNOWN은 별도로 표시됩니다."
            )
            # Say which work the request reaches: a preparation not yet admitted as a
            # Job, existing Jobs, or both (G12 section 5.1, FIX1 G12R-07).
            parts = []
            if getattr(self, "busy", False):
                parts.append("실행 준비(작업 미접수) 취소")
            history = getattr(self, "_history", None)
            try:
                existing = [
                    job
                    for job in (history.list_for_session(session_id) if history else [])
                    if job.state.value not in ("SUCCEEDED", "FAILED", "CANCELLED")
                ]
            except Exception:
                existing = []
            if existing:
                parts.append(f"기존 AI 작업 {len(existing)}건 취소")
            self._announce_counter = getattr(self, "_announce_counter", 0) + 1
            self.panel.announcer.announce(
                "content",
                self.panel.job_status,
                "CANCEL_REQUESTED",
                "취소 요청됨 · "
                + (" · ".join(parts) or "대상 확인 중")
                + " · 로컬 종료 확인과 원격 결과는 아직 확인되지 않았습니다",
                version=("cancel", self._announce_counter, session_id),
            )

    def before_delete(self, session_id: str) -> None:
        if self.privacy is not None:
            self.privacy.consents.revoke_session(session_id)
        else:
            from recoryn.security import ConsentStore

            with ConsentStore(self.window.library.root / "security.sqlite") as consent:
                consent.revoke_session(session_id)
        if self.service is not None:
            self.service.cancel_session(session_id)

    def stop_playback(self) -> None:
        self._playback_generation += 1
        self.playback.stop()

    def seek(self, track_id: str, position_ms: int, revision_id: str) -> None:
        revision = self.store.transcript(revision_id)
        ranges = revision.get("coverage", {}).get("source_ranges", [])
        target = next(
            (
                item
                for item in ranges
                if item["track_id"] == track_id
                and item["offset_ms"] is not None
                and item["offset_ms"] <= position_ms < item["offset_ms"] + item["duration_ms"]
            ),
            None,
        )
        if target is None:
            self.panel.status.setText("이 버전에는 재생 가능한 정확한 원본 매핑이 없습니다.")
            return
        if self.busy:
            return
        generation = self._playback_generation

        def play(pcm: PlaybackPcm) -> None:
            if generation != self._playback_generation:
                return
            self.window.library.get_session(revision["session_id"])
            self._play(pcm)

        self.operation(
            lambda: self._verify_playback(
                revision["session_id"], target, position_ms - target["offset_ms"]
            ),
            play,
        )

    def _verify_playback(
        self, session_id: str, target: dict[str, Any], position_ms: int = 0
    ) -> PlaybackPcm:
        service = self._service()
        job = service.jobs.create("playback_verification", uuid4().hex)
        service.jobs.bind_session(job.job_id, session_id)
        attempt = service.jobs.claim(job.job_id, "desktop-playback")
        service.jobs.reader_started(attempt)
        try:
            path = self._checked_playback_path(session_id, target)
            # Still under the reader lease: the bytes that play are the verified ones.
            pcm = prepare_playback(path, target["sha256"], position_ms)
            service.jobs.complete(job.job_id, attempt.attempt_id, attempt.fence, str(path))
            return pcm
        except Exception:
            service.jobs.fail(
                job.job_id, attempt.attempt_id, attempt.fence, "PLAYBACK_SOURCE_INVALID"
            )
            raise
        finally:
            service.jobs.reader_finished(attempt)

    def _checked_playback_path(self, session_id: str, target: dict[str, Any]) -> Path:
        library = self.window.library
        library.get_session(session_id)  # deletion intent prevents new playback
        path = safe_path(library.root, target["path"])
        expected_root = library.root / "sessions" / session_id / "derived"
        if not path.is_relative_to(expected_root) or path.suffix != ".wav":
            raise StateConflict("PLAYBACK_SOURCE_INVALID")
        digest = hashlib.sha256()
        with open_file(path, "rb") as stream:
            while part := stream.read(256 * 1024):
                digest.update(part)
        if digest.hexdigest() != target.get("sha256"):
            raise StateConflict("PLAYBACK_SOURCE_INVALID")
        chunks = {item.chunk_id: item for item in library.chunks(session_id)}
        total = 0
        for source in target.get("ranges", []):
            chunk = chunks.get(source["chunk_id"])
            if (
                chunk is None
                or chunk.track_id != target["track_id"]
                or verify_bundle(safe_path(library.root, chunk.relative_path)) != chunk
                or source["output_frame_start"] != total
                or source["frame_count"] <= 0
                or source["source_chunk_frame_start"] < 0
                or source["source_chunk_frame_start"] + source["frame_count"] > chunk.frame_count
            ):
                raise StateConflict("PLAYBACK_SOURCE_INVALID")
            total += source["frame_count"]
        with open_file(path, "rb") as stream, wave.open(stream, "rb") as audio:
            if not total or audio.getnframes() != total:
                raise StateConflict("PLAYBACK_SOURCE_INVALID")
        library.get_session(session_id)
        return path

    def _play(self, pcm: PlaybackPcm) -> None:
        try:
            self.playback.start(pcm)
        except StateConflict as exc:
            self._report_playback(str(exc))

    def _report_playback(self, code: str) -> None:
        # Start failures and failures after starting (L04-D04) are both shown.
        self.panel.status.setText("재생할 수 없습니다: " + code + " · 원본은 보존됩니다.")

    def tick(self) -> None:
        self._name_policy_control()
        self.window.model_panel.request_attestation_check()
        session_id = self.window.selected_session()
        if session_id:
            # Playback verification has its own status, and must not hide an AI
            # condition the user still needs to resolve.
            jobs = [
                job
                for job in self._history.list_for_session(session_id)
                if job.kind
                in {"transcription", "streaming_transcription", "summarization", "diarization"}
            ]
            reader = self._history.local_reader_active(jobs[-1].job_id) if jobs else None
            resource_ack = self._resource_acknowledged(jobs[-1]) if jobs else False
            service = getattr(self, "service", None)
            read_refusal = getattr(getattr(service, "runner", None), "admission_error", None)
            admission_error = (
                read_refusal(jobs[-1].job_id) if callable(read_refusal) and jobs else None
            )
            selected_policy = self._selected_policy()
            key = str(
                [
                    session_id,
                    [asdict(job) for job in jobs],
                    reader,
                    resource_ack,
                    admission_error,
                    selected_policy,
                ]
            )
            if key != self._last_snapshot:
                if not self.busy and not self.window.busy:
                    self._last_snapshot = key
                    self.panel.load(session_id)
                if jobs:
                    job = jobs[-1]
                    self.observe_gpu_failure()
                    status = ai_status(
                        job, reader_active=reader, resource_acknowledged=resource_ack
                    )
                    if admission_error and job.state.value in {"QUEUED", "BACKOFF", "FAILED"}:
                        status = admission_status(
                            admission_error, failed=job.state.value == "FAILED"
                        )
                    status = self._with_resources(job, status, selected_policy)
                    if job.kind == "diarization":
                        status = AIStatus(status.text, status.reason, status.action_id, False)
                    self._preparation_action = (
                        (
                            session_id,
                            "summary" if job.kind == "summarization" else "stt",
                            status.action_id,
                        )
                        if status.action_id and job.state.value != "BLOCKED"
                        else None
                    )
                    self._blocked_target = (
                        (session_id, job.job_id, job.state_version, status.action_id)
                        if status.action_id and job.state.value == "BLOCKED"
                        else None
                    )
                    self.panel.show_ai_status(status)
                    kind = job_announcement(job)
                    if kind is not None:
                        self.panel.announcer.announce(
                            "content",
                            self.panel.job_status,
                            kind,
                            announcement_text(kind, job) + " · " + status.text,
                            version=announcement_version(job),
                        )
                    self.panel.job_status.setText(
                        status.text
                        + (
                            " · GPU 런타임으로 실행하지 못했습니다. 모델 관리 탭에서 상태를"
                            " 확인하세요."
                            if (job.error_code or "").startswith("GPU_RUNTIME_")
                            else ""
                        )
                        + (
                            " 이번 실행에서는 다시 받기 전까지 이 GPU 런타임을 쓰지 않습니다"
                            " (CPU 허용 정책은 CPU로, GPU 전용 정책은 전사를 시작하지 않음)."
                            if (job.error_code or "").startswith("GPU_RUNTIME_")
                            and self._gpu_failed is not None
                            else ""
                        )
                    )
        self._live_tick()

    def _with_resources(self, job: Any, status: AIStatus, selected: str) -> AIStatus:
        """Add the captured policy; a job whose captured request the fixed table refuses
        (a late callback of an old request) is shown refused, never as a normal run."""
        service = getattr(self, "service", None)
        reader = getattr(service, "resource_request", None)
        request = reader(job.job_id) if callable(reader) else None
        if job.kind not in {
            "transcription",
            "streaming_transcription",
            "summarization",
            "diarization",
        }:
            return status
        if request is not None:
            try:
                plan_static(request)
            except StateConflict as error:
                code = str(error)
                if code in POLICY_CODES:
                    refused = policy_block_status(code, request.policy, f"AI: {job.state.value}")
                    return AIStatus(refused.text, refused.reason, refused.action_id, False)
                return AIStatus(
                    f"AI: {job.state.value} · {code} · 이 작업·실행 위치 조합은 실행하지 않습니다",
                    "CAPABILITY",
                    "model",
                    False,
                )
        if job.state.value == "BLOCKED" and job.error_code in POLICY_CODES:
            policy = request.policy if request is not None else selected
            refused = policy_block_status(job.error_code, policy, f"AI: {job.state.value}")
            status = AIStatus(refused.text, refused.reason, refused.action_id, status.can_continue)
        view = getattr(service, "resource_view", None)
        lease = view(job.job_id) if callable(view) else None
        profile_text = None
        scheduler = getattr(service, "scheduler", None)
        if request is not None and request.backend in ("LOCAL_CT2", "LOCAL_SHERPA"):
            try:
                profile = resolve_profile(request, getattr(scheduler, "profiles", ()))
            except StateConflict:
                profile_text = "명시 profile 불일치(RESOURCE_PROFILE_MISMATCH)"
            else:
                if profile is not None:
                    profile_text = (
                        f"profile {profile.profile_id} · CPU RAM {_mib(profile.cpu_host_ram)}"
                        f" · GPU RAM {_mib(profile.gpu_host_ram)} · VRAM {_mib(profile.gpu_bytes)}"
                    )
        return AIStatus(
            status.text + " · " + resource_note(request, selected, lease, profile_text),
            status.reason,
            status.action_id,
            status.can_continue,
        )

    def _live_tick(self) -> None:
        session = self.window.recorder.session_id
        if (
            not session
            or not self.window.live_stt.isChecked()
            or self.busy
            or self.window.busy
            or self._shutting_down
            or session in self._live_blocked
        ):
            return
        from recoryn.domain import SessionState

        if self.window.library.get_session(session).state not in {
            SessionState.RECORDING,
            SessionState.PAUSED,
        }:
            return
        previous = self._live_jobs.get(session)
        if previous is None and session not in self._live_nonces:
            interrupted = any(
                job.kind == "streaming_transcription" and job.state.value != "SUCCEEDED"
                for job in self._history.list_for_session(session)
            )
            if interrupted:
                self._live_blocked.add(session)
                self.panel.job_status.setText(
                    "미완료 임시 전사 이력 · 자동 재전송 없음. 새 작업으로 명시 재개하세요."
                )
                return
        if previous and self.service is not None:
            job = self.service.jobs.get(previous)
            if job.state.value == "SUCCEEDED":
                pass
            elif job.state.value in {"FAILED", "CANCELLED", "BLOCKED"}:
                self._live_blocked.add(session)
                self.panel.job_status.setText(
                    "임시 전사 중단 · "
                    + (job.blocked_reason or job.error_code or job.state.value)
                    + " · 자동 재전송하지 않습니다. 명시 재개를 선택하세요."
                )
                return
            else:
                return
        self._transcribe(session_id=session, provisional=True)

    def observe_gpu_failure(self) -> None:
        """Record the runtime install the last local worker failed on (this run only)."""
        local = getattr(getattr(self, "_local_factory", None), "last", None)
        if (
            local is not None
            and getattr(local, "gpu_failure", None) is not None
            and self._local_generation is not None
        ):
            self._gpu_failed = self._local_generation

    def release_gpu_runtime(self) -> None:
        """Close an idle local worker that holds the GPU runtime open (before removal).

        Refuses while AI work is preparing, queued or running, so an active worker is
        never closed under a job.
        """
        if self.busy:
            raise StateConflict("AI_MODEL_CHANGE_REQUIRES_IDLE")
        if self.service is not None:
            reap = getattr(getattr(self.service, "scheduler", None), "reap_held", None)
            if callable(reap):
                reap()  # a worker that has not exited keeps the runtime in use
            activity = self.service.runner.snapshot()
            if activity["active"] or activity["pending"]:
                raise StateConflict("AI_MODEL_CHANGE_REQUIRES_IDLE")
        if PROBE_OWNERS.live():
            raise StateConflict("AI_MODEL_CHANGE_REQUIRES_IDLE")
        # Workers are per Job and already closed with their exit ACK; nothing stays warm.
        self.observe_gpu_failure()

    def close(self) -> None:
        self._shutting_down = True
        self._preparation_cancel.set()
        if not self.pool.waitForDone(5000):
            raise StateConflict("INFERENCE_ACK_PENDING")
        if self.service:
            self.service.close()
        self.store.close()
        self._history.close()
