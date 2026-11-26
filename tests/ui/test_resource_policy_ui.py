"""G11 / G-P11a UI rows: Ua 144, T30 and T31 through the real MainWindow bridge.

Expected outcomes come from the hand-written G11 table in tests/unit/test_resource_policy.py.
The provider-to-backend registry is injected as data, so every (kind, backend) pair can
reach the bridge's static gate; the gate itself, AIService, JobStore and tick are real.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from itertools import product
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PySide6.QtWidgets import QApplication

import recoryn.ui.ai_bridge as bridge_module
from recoryn.diarization import DiarizationConfig as REAL_DIARIZATION_CONFIG
from recoryn.domain import StateConflict
from recoryn.models import ResourceRequest
from recoryn.providers import ExecutionContext
from recoryn.security import CredentialVault as REAL_VAULT
from tests.e2e.test_ai_workflow import FakeSTT, FakeSummary, finished, recording
from tests.unit.test_resource_policy import (
    BACKENDS,
    GU,
    KINDS,
    POLICIES,
    PV,
    REFUSALS,
    U,
    expected,
)

pytestmark = pytest.mark.ui
STAGES = ("prepare", "queued", "active", "blocked")
UA = list(product(POLICIES, KINDS, BACKENDS, STAGES))
UA_IDS = [f"G11-UA-{n:03}" for n in range(1, 145)]
T_IDS = ("G11-T-30", "G11-T-31")
FALLBACK = "GPU_WITH_CPU_FALLBACK_ALLOWED"
PROVIDERS = ("faster_whisper", "ollama", "openai", "gemini", "anthropic", "sherpa_onnx")
JOB_KIND = {"stt": "transcription", "summary": "summarization", "diarization": "diarization"}
# G-P07 action identifiers, by hand: the execution policy location and model settings.
POLICY_ACTION, MODEL_ACTION = "execution_policy", "model"


def test_ua_manifest() -> None:
    assert len(UA) == len(set(UA)) == 3 * 3 * 4 * 4 == len(UA_IDS) == 144


def spin(app: QApplication, condition: Callable[[], bool], timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.001)
    app.processEvents()
    assert condition()


class Vault:
    def read(self, key: str) -> bytes | None:
        return None

    def write(self, *args: Any) -> None:
        pytest.fail("no credential writes")

    def delete(self, *args: Any) -> None:
        pytest.fail("no credential deletion")


class Window:
    """One real MainWindow with a finalized session and a complete transcript."""

    def __init__(self, root: Path, mp: pytest.MonkeyPatch) -> None:
        import recoryn.security as security
        from recoryn.storage import Library
        from recoryn.ui.main import MainWindow

        mp.setattr(
            security, "CredentialVault", lambda: REAL_VAULT(backend=Vault(), namespace="g11")
        )
        self.app = QApplication.instance() or QApplication([])
        self._library = Library(root / "library")
        self.library = self._library.__enter__()
        self.session = recording(self.library)
        self.window = MainWindow(self.library)
        self.window.timer.stop()
        self.window.refresh_sessions()
        spin(self.app, lambda: self.window.sessions.count() == 1)
        self.window.sessions.setCurrentRow(0)
        # A chosen summary provider (the injected registry maps it per row).
        summary = self.window.privacy_panel.controls["summary"].provider
        summary.setCurrentIndex(summary.findData("ollama"))
        self.bridge = self.window.ai_bridge
        self.service = self.bridge._service()
        seed = self.service.transcribe(
            self.session,
            FakeSTT(),
            config_key="seed",
            resource_request=ResourceRequest("stt", "LOCAL_CT2", "CPU_ONLY"),
        )
        assert finished(self.service, seed).state.value == "SUCCEEDED"
        self.bridge.panel.load(self.session)
        self.real_submit = self.service.runner.submit
        # Fixture only: admitted intents stay QUEUED so each stage is set explicitly.
        mp.setattr(self.service.runner, "submit", lambda *args, **kwargs: True)
        self.prepared: list[str] = []
        self.attestations: list[str] = []
        self.diarization_configs: list[str] = []
        privacy, panel = self.window.privacy_panel, self.window.model_panel

        def prepare(kind: str, *args: Any) -> Any:
            # The independent consent/cost preparation is reached; stop here.
            self.prepared.append(kind)
            raise StateConflict("CONSENT_REQUIRED")

        mp.setattr(privacy.backend, "prepare_execution", lambda intent: prepare(intent.kind))
        mp.setattr(panel, "request_attestation_check", lambda: self.attestations.append("req"))

    def close(self) -> None:
        self.window.close()
        spin(self.app, lambda: self.window._closing)
        self.window.deleteLater()
        self.app.processEvents()
        self._library.__exit__(None, None, None)

    def click(self, kind: str) -> None:
        bridge = self.bridge
        if kind == "stt":
            bridge.transcribe()
        elif kind == "summary":
            bridge.summarize(bridge.panel.templates.currentData())
        else:
            panel = bridge.panel
            panel.revision = {
                "complete": True,
                "session_id": self.session,
                "revision_id": "fixture",
                "segments": [],
                "coverage": {},
                "kind": "corrected",
            }
            panel.diarization_ranges.clear()
            panel.diarization_ranges.addItem("fixture", {"offset_ms": 0, "track_id": "mic"})
            self.window.diarization_approval.setChecked(True)
            bridge.diarize()
        spin(self.app, lambda: not bridge.busy)

    def text(self) -> str:
        return str(self.bridge.panel.job_status.text())


@pytest.fixture(scope="module")
def env(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Window]:
    import recoryn.diarization as diarization

    mp = pytest.MonkeyPatch()
    window: Window | None = None
    try:
        window = Window(tmp_path_factory.mktemp("g11a-ui"), mp)

        def config(*args: Any, **kwargs: Any) -> Any:
            assert window is not None
            window.diarization_configs.append("config")
            raise ValueError("fixture manifest")

        mp.setattr(diarization, "DiarizationConfig", config)
        yield window
    finally:
        if window is not None:
            window.close()
        mp.undo()


def note(kind: str, backend: str, policy: str, selected: str) -> list[str]:
    """Hand-written captured-policy display (G11 section 6)."""
    if backend == "REMOTE":
        return ["원격 실행 — 이 PC의 장치 정책 적용 안 됨"]
    tail = [f"현재 선택 {selected}은 새 요청부터 적용"] if selected != policy else []
    if backend == "OLLAMA":
        return [f"접수 정책 {policy}", "장치 미보장·서버 메모리 통제 불가", *tail]
    return [f"접수 정책 {policy}", "메모리 요구량 미확인", *tail]


def admit(env: Window, kind: str, request: ResourceRequest, key: str) -> str:
    service = env.service
    if kind == "stt":
        return service.transcribe(env.session, FakeSTT(), config_key=key, resource_request=request)
    if kind == "summary":
        return service.summarize(
            env.session, FakeSummary(), config_key=key, resource_request=request
        )
    job = service.jobs.create("diarization", key)
    service.jobs.bind_session(job.job_id, env.session)
    service.capture_diarization(job.job_id, request)
    return job.job_id


def inject_late(env: Window, kind: str, request: ResourceRequest, key: str) -> str:
    """An old request or late callback the fixed table refuses (Ua note in section 7.1)."""
    job = env.service.jobs.create(JOB_KIND[kind], key)
    env.service.jobs.bind_session(job.job_id, env.session)
    env.service._resource_requests[job.job_id] = request
    return job.job_id


@pytest.mark.parametrize("row", UA, ids=UA_IDS)
def test_ua_policy_display_and_gate(
    env: Window, monkeypatch: pytest.MonkeyPatch, row: tuple[str, str, str, str]
) -> None:
    policy, kind, backend, stage = row
    case = UA_IDS[UA.index(row)]
    outcome = expected(policy, kind, backend)
    refused = outcome in REFUSALS
    window, bridge, service = env.window, env.bridge, env.service
    monkeypatch.setattr(bridge_module, "PROVIDER_BACKENDS", dict.fromkeys(PROVIDERS, backend))
    window.device_policy.setCurrentText(policy)
    request = ResourceRequest(kind, backend, policy)
    if stage == "prepare":
        jobs = service.jobs.list_for_session(env.session)
        env.prepared.clear()
        env.attestations.clear()
        env.diarization_configs.clear()
        env.click(kind)
        text = env.text()
        assert service.jobs.list_for_session(env.session) == jobs  # no Job either way
        assert env.attestations == [] and window.device_policy.currentText() == policy
        if refused:
            assert env.prepared == [] and env.diarization_configs == []
            assert outcome in text and "작업 미접수" in text
            action = bridge._preparation_action[2]
            if outcome in {PV, GU}:
                assert action == POLICY_ACTION and "자동" in text
                assert ("GPU_WITH_CPU_FALLBACK_ALLOWED를 직접 선택" in text) is (outcome == PV)
                bridge.open_blocked_action()
                assert window.tabs.currentWidget().isAncestorOf(window.device_policy)
            else:
                assert action == MODEL_ACTION
        elif kind == "diarization":
            assert env.prepared == [] and env.diarization_configs == ["config"]
            assert "화자 분리 manifest" in text
        else:
            # REMOTE exemption and allowed Ollama still go through consent/cost first.
            assert env.prepared == [kind] and "CONSENT_REQUIRED" in text
        return
    if refused:
        job_id = inject_late(env, kind, request, case)
    else:
        job_id = admit(env, kind, request, case)
    if stage == "active":
        service.jobs.claim(job_id, "fixture")
    elif stage == "blocked":
        record = service.jobs.get(job_id)
        reason, code = ("CAPABILITY", outcome) if refused else ("BUDGET", "COST_CAP_EXCEEDED")
        service.jobs.block_pending(job_id, reason, code, expected_version=record.state_version)
    selected = POLICIES[(POLICIES.index(policy) + 1) % 3]
    window.device_policy.setCurrentText(selected)
    before = service.jobs.get(job_id)
    if stage == "queued" and kind != "diarization" and not refused:
        # A same-key request under the new selection never rewrites the captured policy.
        later = ResourceRequest(kind, backend, selected)
        try:
            assert admit(env, kind, later, case) == job_id
        except StateConflict as error:
            assert str(error) == expected(selected, kind, backend)
    bridge.tick()
    text = env.text()
    assert service.resource_request(job_id) is request
    assert service.jobs.get(job_id) == before and window.device_policy.currentText() == selected
    assert not bridge.panel.blocked_continue.isEnabled() or not refused
    if refused:
        assert outcome in text
        if outcome == U:
            assert "이 작업·실행 위치 조합은 실행하지 않습니다" in text
        else:
            assert "직접 선택한 뒤 새로 요청하세요" in text and "자동" in text
        assert "메모리 요구량 미확인" not in text and "원격 실행" not in text
        assert bridge.panel.blocked_open.isEnabled()
        target = bridge._blocked_target if stage == "blocked" else bridge._preparation_action
        assert target is not None and target[-1] == (
            POLICY_ACTION if outcome in {PV, GU} else MODEL_ACTION
        )
    else:
        for piece in note(kind, backend, policy, selected):
            assert piece in text, (piece, text)
        assert f"접수 정책 {selected}" not in text


@pytest.fixture
def lone(tmp_path: Path) -> Iterator[Window]:
    mp = pytest.MonkeyPatch()
    window: Window | None = None
    try:
        window = Window(tmp_path, mp)
        yield window
    finally:
        if window is not None:
            window.close()
        mp.undo()


def test_t31_strict_ollama_refusal_precedes_attestation(
    lone: Window, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G11-T-31: no attestation request, prepare_execution or adapter for a refused policy."""
    import recoryn.summarization as summarization
    from recoryn.ui.models import ModelPanel

    window, bridge = lone.window, lone.bridge
    control = window.privacy_panel.controls["summary"]
    control.provider.setCurrentIndex(control.provider.findData("ollama"))
    monkeypatch.setattr(ModelPanel, "ollama_owned", property(lambda self: True))
    adapters: list[str] = []
    monkeypatch.setattr(summarization, "OllamaSummarizer", lambda *args: adapters.append("ollama"))
    for policy in ("CPU_ONLY", "GPU_ONLY"):
        window.device_policy.setCurrentText(policy)
        lone.prepared.clear()
        lone.attestations.clear()
        lone.click("summary")
        assert PV in lone.text() and bridge._preparation_action[2] == POLICY_ACTION
        assert lone.attestations == [] and lone.prepared == [] and adapters == []
    # Control: the fallback policy keeps the existing attestation order (real check,
    # unverified proof -> one attestation request and LOCAL_EXECUTION_UNVERIFIED).
    window.device_policy.setCurrentText(FALLBACK)
    lone.click("summary")
    assert "LOCAL_EXECUTION_UNVERIFIED" in lone.text()
    assert lone.attestations == ["req"] and lone.prepared == [] and adapters == []


def test_t30_continue_after_policy_change_takes_a_new_snapshot(
    lone: Window, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G11-T-30 (decision 7 (a)): an explicit continue is a new admission.

    The original T30 wording assumed a Job BLOCKED by RESOURCE_POLICY_UNVERIFIED; admission
    refuses that before a Job exists, so the reachable trace is a BLOCKED(BUDGET) Ollama
    Job whose continue meets a changed policy (see the G11 implementation section).
    """
    import recoryn.summarization as summarization

    window, bridge, service = lone.window, lone.bridge, lone.service
    control = window.privacy_panel.controls["summary"]
    control.provider.setCurrentIndex(control.provider.findData("ollama"))
    window.device_policy.setCurrentText(FALLBACK)
    other = ResourceRequest("summary", "OLLAMA", FALLBACK, runtime_identity="other")
    other_job = admit(lone, "summary", other, "t30-other")
    original = ResourceRequest("summary", "OLLAMA", FALLBACK, runtime_identity="t30-original")
    job_id = admit(lone, "summary", original, "t30")
    queued = service.jobs.get(job_id)
    blocked = service.jobs.block_pending(
        job_id, "BUDGET", "COST_CAP_EXCEEDED", expected_version=queued.state_version
    )
    bridge.tick()
    assert bridge.panel.blocked_continue.isEnabled()
    # 1. The selection changed to CPU_ONLY: continue is refused before any preparation.
    window.device_policy.setCurrentText("CPU_ONLY")
    lone.prepared.clear()
    bridge.continue_blocked()
    spin(lone.app, lambda: not bridge.busy)
    text = lone.text()
    assert PV in text and "기존 Job BLOCKED 유지" in text and lone.prepared == []
    assert service.jobs.get(job_id) == blocked and service.resource_request(job_id) is original
    assert bridge._blocked_target is not None and bridge._blocked_target[3] == POLICY_ACTION
    # 2. The user selects the fallback policy again: continue admits a new snapshot.
    window.device_policy.setCurrentText(FALLBACK)
    executions: list[str] = []

    def prepare(kind: str, *args: Any) -> Any:
        executions.append(kind)
        return SimpleNamespace(
            config=SimpleNamespace(provider_id="ollama"),
            context=ExecutionContext(),
            config_key="t30",
            gateway=None,
        )

    monkeypatch.setattr(
        window.privacy_panel.backend, "prepare_execution", lambda intent: prepare(intent.kind)
    )
    monkeypatch.setattr(summarization, "OllamaSummarizer", lambda *args: FakeSummary())
    monkeypatch.setattr(service.runner, "submit", lone.real_submit)
    bridge.continue_blocked()
    spin(lone.app, lambda: not bridge.busy)
    assert executions == ["summary"]
    done = finished(service, job_id)
    assert done.state.value == "SUCCEEDED" and done.attempt_count == blocked.attempt_count + 1
    captured = service.resource_request(job_id)
    assert captured == ResourceRequest("summary", "OLLAMA", FALLBACK) and captured != original
    # The other queued request keeps its captured policy and state.
    assert service.resource_request(other_job) is other
    assert service.jobs.get(other_job).state.value == "QUEUED"
    bridge.tick()
    assert f"접수 정책 {FALLBACK}" in lone.text()


def test_aux_second_gate_uses_the_prepared_provider(
    lone: Window, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G11-AUX-GATE2: the prepared configuration, not the selection, names the backend."""
    window, bridge, service = lone.window, lone.bridge, lone.service
    window.device_policy.setCurrentText("CPU_ONLY")
    summary = window.privacy_panel.controls["summary"].provider
    summary.setCurrentIndex(summary.findData("openai"))  # REMOTE passes the first gate
    prepared: list[str] = []

    def prepare_as(provider: str) -> Callable[..., Any]:
        def prepare(kind: str, *args: Any) -> Any:
            prepared.append(kind)
            return SimpleNamespace(
                config=SimpleNamespace(provider_id=provider),
                context=ExecutionContext(),
                config_key="gate2",
                gateway=None,
            )

        return prepare

    before = service.jobs.list_for_session(lone.session)
    for kind, provider, code in (
        ("summary", "ollama", PV),
        ("summary", "mystery", U),
        ("stt", "ollama", U),
        ("stt", "mystery", U),
    ):
        monkeypatch.setattr(
            window.privacy_panel.backend,
            "prepare_execution",
            lambda intent, provider=provider: prepare_as(provider)(intent.kind),
        )
        prepared.clear()
        lone.click(kind)
        assert prepared == [kind] and code in lone.text() and "작업 미접수" in lone.text()
        expected_action = POLICY_ACTION if code == PV else MODEL_ACTION
        assert bridge._preparation_action[2] == expected_action
    assert service.jobs.list_for_session(lone.session) == before


def test_aux_blocked_policy_job_without_a_capture_is_shown_honestly(lone: Window) -> None:
    """G11-AUX-NOCAPTURE: a policy-blocked Job this run never admitted (another process
    or before a restart) shows the refusal, the selection and no invented captured policy."""
    service, bridge = lone.service, lone.bridge
    job = service.jobs.create("summarization", "nocapture")
    service.jobs.bind_session(job.job_id, lone.session)
    service.jobs.block_pending(job.job_id, "CAPABILITY", PV, expected_version=job.state_version)
    lone.window.device_policy.setCurrentText("GPU_ONLY")
    bridge.tick()
    text = lone.text()
    assert service.resource_request(job.job_id) is None
    assert PV in text and "GPU_ONLY에서 요약을 시작하지 않습니다" in text
    assert "실행 정책: 이 실행에서 접수한 기록 없음" in text and "접수 정책" not in text
    assert bridge._blocked_target is not None and bridge._blocked_target[3] == POLICY_ACTION


# =====================================================================================
# G-P11b UI: Ub 48 (estimate, device, observation, lease/ACK display), T29, and the
# diarize() submit row (G11R-03). Expected display pieces are written by hand.
# =====================================================================================

from recoryn.models import ResourceScheduler  # noqa: E402
from recoryn.models.resources import (  # noqa: E402
    OBSERVED,
    GpuDevice,
    GpuObservation,
    MemoryObservation,
    ResourceSource,
)
from tests.resource_fakes import Factory, Observer, profile  # noqa: E402

MIB = 2**20
UB_PATHS = ("ct2_stt", "sherpa_diarization")
UB_STAGES = ("queued", "blocked", "active", "ack_wait")
UB = list(product(POLICIES, UB_PATHS, UB_STAGES, ("known", "unknown")))
UB_IDS = [f"G11-UB-{n:02}" for n in range(1, 49)]
NATIVE = ResourceSource("native", "READY")


def test_ub_manifest() -> None:
    assert len(UB) == len(set(UB)) == 3 * 2 * 4 * 2 == len(UB_IDS)


def _ub_scheduler(path: str, known: bool) -> tuple[ResourceScheduler, Observer]:
    def gpu() -> GpuObservation:
        device = GpuDevice("GPU-UB", 0, 3, "fixture", 8192 * MIB, 8192 * MIB)
        return GpuObservation(OBSERVED, time.monotonic_ns(), (device,), True, "fake")

    def ram() -> MemoryObservation:
        return MemoryObservation(OBSERVED, time.monotonic_ns(), 16384 * MIB, 32768 * MIB, "fake")

    stt = path == "ct2_stt"
    profiles = (
        (
            profile(
                "ub",
                kind="stt" if stt else "diarization",
                backend="LOCAL_CT2" if stt else "LOCAL_SHERPA",
                model="model-UB",
                runtime="runtime-UB",
                cpu=1024 * MIB,
                gpu_host=1024 * MIB if stt else None,
                gpu=2048 * MIB if stt else None,
            ),
        )
        if known
        else ()
    )
    observer = Observer(gpu, ram)
    return ResourceScheduler(observe=observer, profiles=profiles), observer


def ub_expected(row: tuple[str, str, str, str]) -> tuple[str, list[str]]:
    """(kind of display, pieces) by hand from G11 section 6."""
    policy, path, stage, estimate = row
    if path == "sherpa_diarization" and policy == "GPU_ONLY":
        return "refused", ["RESOURCE_GPU_UNSUPPORTED", "직접 선택한 뒤 새로 요청하세요"]
    known = estimate == "known"
    cuda = path == "ct2_stt" and policy != "CPU_ONLY"
    pieces = [f"접수 정책 {policy}"]
    if stage == "queued":
        pieces.append("profile ub" if known else "메모리 요구량 미확인")
        pieces.append("자원 계획은 실행 직전에 다시 관측")
        return "note", pieces
    if known:
        pieces.append("계획 요구량 RAM 1,024 MiB" + (" · VRAM 2,048 MiB" if cuda else ""))
        pieces.append("RAM 여유 16,384 MiB")
    else:
        pieces.append("메모리 요구량 미확인")
        pieces.append("RAM 관측 NOT_OBSERVED")  # an UNKNOWN requirement never reads RAM
    if cuda:
        # The logical CUDA index, never the host tool's index 3.
        pieces += [
            "장치 GPU fixture (CUDA 논리 index 0)",
            "VRAM 여유 8,192 MiB · 여유 기준 512 MiB",
        ]
    else:
        pieces.append("장치 CPU")
    pieces.append(
        {
            "active": "자원 사용 중",
            "blocked": "자원 해제됨",
            "ack_wait": "작업자 종료 ACK 대기 · RESOURCE_LEASE_HELD",
        }[stage]
    )
    if stage == "blocked":
        pieces.append("RESOURCE_DEVICE_MISMATCH")
    return "note", pieces


@pytest.mark.parametrize("row", UB, ids=UB_IDS)
def test_ub_owned_resource_display(
    env: Window, monkeypatch: pytest.MonkeyPatch, row: tuple[str, str, str, str]
) -> None:
    policy, path, stage, estimate = row
    case = UB_IDS[UB.index(row)]
    window, bridge, service = env.window, env.bridge, env.service
    kind, backend = ("stt", "LOCAL_CT2") if path == "ct2_stt" else ("diarization", "LOCAL_SHERPA")
    request = ResourceRequest(
        kind, backend, policy, model_identity="model-UB", runtime_identity="runtime-UB"
    )
    scheduler, observer = _ub_scheduler(path, estimate == "known")
    monkeypatch.setattr(service, "scheduler", scheduler)
    monkeypatch.setattr(service.runner, "held", scheduler.held)
    window.device_policy.setCurrentText(policy)
    shown, pieces = ub_expected(row)
    if shown == "refused":
        job_id = inject_late(env, kind, request, case)
        bridge.tick()
        text = env.text()
        assert all(piece in text for piece in pieces), text
        assert "메모리 요구량" not in text
        return
    gate = threading.Event()
    facts = (
        {
            "device": "cuda" if path == "ct2_stt" and policy != "CPU_ONLY" else "cpu",
            "device_index": 9,
            "compute_type": "wrong",
        }
        if stage == "blocked"
        else None
    )
    factory = Factory(
        "faster_whisper" if kind == "stt" else "sherpa_onnx",
        source=NATIVE,
        gate=gate if stage in ("active", "ack_wait") else None,
        facts=facts,
        close_ok=stage != "ack_wait",
    )
    if stage != "queued":
        monkeypatch.setattr(service.runner, "submit", env.real_submit)
    try:
        if kind == "stt":
            job_id = service.transcribe(
                env.session, factory, config_key=case, resource_request=request
            )
        else:
            admitted = service.admit_diarization(request, factory)
            job = service.jobs.create("diarization", case)
            service.jobs.bind_session(job.job_id, env.session)
            service.capture_diarization(job.job_id, admitted)
            job_id = job.job_id

            def task(attempt: Any, cancel: threading.Event) -> str:
                with service.owned_worker(admitted, factory, attempt, cancel, env.session) as use:
                    use().transcribe(_Clip())
                return "diarized"

            assert service.runner.submit(job_id, task)
        if stage in ("active", "ack_wait"):
            spin(env.app, lambda: bool(factory.opened) and factory.opened[0].entered.is_set())
        if stage == "ack_wait":
            gate.set()
            # The worker did not exit: the lease stays held whatever the Job's logical
            # outcome (STT published its result under its fence before the exit ACK).
            spin(
                env.app,
                lambda: (
                    scheduler.held() == (job_id,)
                    and service.jobs.get(job_id).state.value != "RUNNING"
                ),
            )
        elif stage == "blocked":
            spin(env.app, lambda: service.jobs.get(job_id).state.value == "BLOCKED")
        bridge.tick()
        text = env.text()
        for piece in pieces:
            assert piece in text, (piece, text)
        if stage == "ack_wait":
            done = service.jobs.get(job_id)
            if kind == "stt":
                assert done.state.value == "SUCCEEDED"  # logical result, physical exit pending
            else:
                assert (done.state.value, done.error_code) == ("BLOCKED", "INFERENCE_ACK_PENDING")
            assert service.jobs.local_reader_active(job_id) is True  # deletion still waits
            assert not bridge.panel.blocked_continue.isEnabled()
        # Displaying never changes a setting or the captured intent.
        assert window.device_policy.currentText() == policy
        assert service.resource_request(job_id) == request
        if estimate == "unknown":
            assert observer.ram_reads == 0
    finally:
        gate.set()
        if stage == "ack_wait" and factory.opened:
            factory.opened[0].close_ok = True
            spin(env.app, lambda: service.jobs.get(job_id).state.value != "RUNNING")
            scheduler.reap_held()
            assert service.jobs.local_reader_active(job_id) is False  # finished on the ACK
        if stage in ("active", "blocked"):
            spin(env.app, lambda: service.jobs.get(job_id).state.value in {"SUCCEEDED", "BLOCKED"})


class _Clip:
    offset_ms = 0
    track_id = "mic"


def test_t29_unknown_requirement_never_reaches_the_legacy_helper(
    lone: Window, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """G11-T-29: the real bridge local STT path never calls the legacy 1 GiB ``choose``;
    an UNKNOWN requirement is admitted, run and shown as unknown, not RESOURCE_ESTIMATE_REQUIRED."""
    from recoryn.providers import STTResult, TranscriptSegment

    window, bridge, service = lone.window, lone.bridge, lone.service
    legacy: list[Any] = []
    monkeypatch.setattr(
        ResourceScheduler, "choose", lambda *args: legacy.append(args) or ("cpu", 0)
    )
    model = tmp_path / "model"
    model.mkdir()
    for name in ("model.bin", "config.json", "tokenizer.json"):
        (model / name).write_bytes(b"synthetic-" + name.encode())
    window.local_model.setText(str(model))
    # G-P13 explicit approval fixture: the real snapshot recorded in this window's run
    # registry with Yes and the responsibility check (no always-passing gate).
    registry = window.model_panel.confirmations
    snapshot = window.model_panel.model_snapshot(model)
    assert registry.confirm(
        snapshot, shown=registry.key(snapshot), accepted=True, acknowledged=True
    )
    created: list[dict[str, Any]] = []

    class Local:
        def __init__(self, path: Any, **kwargs: Any) -> None:
            evidence = kwargs.pop("model_evidence", None)  # G-P13: always the confirmation
            assert evidence is not None and evidence.valid()
            self.kwargs = kwargs
            created.append(kwargs)

        def load(self, context: Any = None) -> dict[str, Any]:
            return {"device": "cpu", "device_index": None, "compute_type": "int8"}

        def transcribe(self, request: Any, context: Any = None) -> STTResult:
            item = TranscriptSegment("t29", request.offset_ms, request.offset_ms + 1, "x")
            return STTResult("faster_whisper", "local", (item,), True, processed_ms=1)

        def close(self) -> None:
            pass

    monkeypatch.setattr(bridge_module, "LocalSTTProcess", Local)
    monkeypatch.setattr(service.runner, "submit", lone.real_submit)

    def prepare(kind: str, *args: Any) -> Any:
        return SimpleNamespace(
            config=SimpleNamespace(provider_id="faster_whisper"),
            context=ExecutionContext(),
            config_key="local",
            gateway=None,
        )

    monkeypatch.setattr(
        window.privacy_panel.backend, "prepare_execution", lambda intent: prepare(intent.kind)
    )
    window.device_policy.setCurrentText("CPU_ONLY")
    before = len(service.jobs.list_for_session(lone.session))
    bridge.transcribe()
    spin(lone.app, lambda: not bridge.busy)
    jobs = service.jobs.list_for_session(lone.session)[before:]
    assert len(jobs) == 1
    done = finished(service, jobs[0].job_id)
    assert done.state.value == "SUCCEEDED" and legacy == []
    assert created == [
        {"device": "cpu", "gpu_runtime": None, "device_index": None, "compute_type": "int8"}
    ]
    view = service.resource_view(jobs[0].job_id)
    assert view is not None and view["estimate_status"] == "RESOURCE_ESTIMATE_UNKNOWN"
    bridge.tick()
    assert "메모리 요구량 미확인" in lone.text() and "자원 해제됨" in lone.text()


def test_aux_diarize_submit_admits_and_captures(
    lone: Window, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """G11-AUX-DIARIZE (G11R-03): the real diarize() submit runs the service admission
    before the Job exists and captures the request the tick then shows."""
    import recoryn.diarization as diarization

    window, bridge, service = lone.window, lone.bridge, lone.service
    monkeypatch.setattr(diarization, "DiarizationConfig", REAL_DIARIZATION_CONFIG)
    window.device_policy.setCurrentText("GPU_WITH_CPU_FALLBACK_ALLOWED")
    admissions: list[int] = []
    captures: list[str] = []
    real_admit, real_capture = service.admit_diarization, service.capture_diarization

    def admit(request: Any, provider: Any = None) -> Any:
        admissions.append(len(service.jobs.list_for_session(lone.session)))
        return real_admit(request, provider)

    def capture(job_id: str, request: Any) -> None:
        captures.append(job_id)
        real_capture(job_id, request)

    monkeypatch.setattr(service, "admit_diarization", admit)
    monkeypatch.setattr(service, "capture_diarization", capture)
    panel = bridge.panel
    panel.revision = {
        "complete": True,
        "session_id": lone.session,
        "revision_id": "fixture",
        "segments": [],
        "coverage": {},
        "kind": "corrected",
    }
    panel.diarization_ranges.clear()
    panel.diarization_ranges.addItem("fixture", {"offset_ms": 0, "track_id": "mic"})
    _approved_manifest(window, tmp_path / "synthetic-model")
    window.diarization_approval.setChecked(True)
    before = len(service.jobs.list_for_session(lone.session))
    bridge.diarize()
    spin(lone.app, lambda: not bridge.busy)
    jobs = [
        job
        for job in service.jobs.list_for_session(lone.session)[before:]
        if job.kind == "diarization"
    ]
    assert len(jobs) == 1, lone.text()
    assert admissions == [before] and captures == [jobs[0].job_id]
    captured = service.resource_request(jobs[0].job_id)
    assert captured == ResourceRequest(
        "diarization", "LOCAL_SHERPA", "GPU_WITH_CPU_FALLBACK_ALLOWED"
    )
    bridge.tick()
    assert "접수 정책 GPU_WITH_CPU_FALLBACK_ALLOWED" in lone.text()


def _approved_manifest(window: Any, folder: Path) -> None:
    """G-P13 explicit approval fixture: a strictly valid synthetic manifest (not weights)
    entered in the window and recorded in its run registry with Yes and the license
    confirmation; the parent still re-verifies it right before sealing (no gate bypass)."""
    import hashlib as _hashlib
    import json as _json

    from recoryn.diarization import DiarizationConfig

    folder.mkdir(parents=True, exist_ok=True)
    models = {}
    for role in ("segmentation", "embedding"):
        data, license_bytes = b"synthetic-not-onnx-" + role.encode(), b"Synthetic license"
        (folder / f"{role}.onnx").write_bytes(data)
        (folder / f"LICENSE.{role}.txt").write_bytes(license_bytes)
        models[role] = {
            "file": f"{role}.onnx",
            "size": len(data),
            "sha256": _hashlib.sha256(data).hexdigest(),
            "license_id": "test-only",
            "license_url": "https://publisher.invalid/license",
            "license_file": f"LICENSE.{role}.txt",
            "license_sha256": _hashlib.sha256(license_bytes).hexdigest(),
        }
    manifest = folder / "manifest.json"
    manifest.write_text(
        _json.dumps(
            {
                "schema_version": 1,
                "runtime": "sherpa-onnx",
                "runtime_version": "2.0.1",
                "models": models,
            }
        ),
        encoding="utf-8",
    )
    digest = _hashlib.sha256(manifest.read_bytes()).hexdigest()
    window.diarization_manifest.setText(str(manifest))
    window.diarization_hash.setText(digest)
    snapshot = window.ai_bridge._diarization_snapshot(DiarizationConfig(manifest, digest, True))
    registry = window.model_panel.confirmations
    evidence = registry.confirm(
        snapshot, shown=registry.key(snapshot), accepted=True, acknowledged=True
    )
    assert evidence is not None
