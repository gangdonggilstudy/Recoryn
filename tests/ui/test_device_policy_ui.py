"""G16 UI rows: S (snapshots 180) and U (keys 80) through the real MainWindow, plus
G16-X-01, the entry point's wiring: ``run()`` saves and restores through LOCALAPPDATA.

Expected policies, devices, refusals and status texts are written by hand from
docs/testing/g16-device-policy-cases.md sections 3-5 and the G11 table; the product's
tables, labels or parser are never used to build an expected value. Settings files are
real TEMP files (tests/ui/conftest.py isolates every window). No device, model,
credential store, local server or network is used: providers are test doubles and the
CT2 device plan is a hand-written no-GPU table.
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections.abc import Callable, Iterator
from itertools import product
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from recoryn.app.device_policy import DevicePolicyStore, PolicyIo, PolicyWriteResult
from recoryn.domain import StateConflict
from recoryn.models import ResourceRequest
from recoryn.providers import ExecutionContext
from recoryn.security import CredentialVault as REAL_VAULT
from tests.e2e.test_ai_workflow import FakeSTT, FakeSummary, finished, recording

pytestmark = pytest.mark.ui

CPU, GPU, FALLBACK = "CPU_ONLY", "GPU_ONLY", "GPU_WITH_CPU_FALLBACK_ALLOWED"
POLICIES = (CPU, GPU, FALLBACK)
PV, GU = "RESOURCE_POLICY_UNVERIFIED", "RESOURCE_GPU_UNSUPPORTED"
AUTO_TEXT = "AUTO — GPU 우선, CPU 사용 허용"
SHOWN = {CPU: "CPU_ONLY", GPU: "GPU_ONLY", FALLBACK: AUTO_TEXT}
NOTE = ". 로컬 Ollama 요약은 이 정책에서 차단됩니다(필요하면 AUTO를 직접 선택)"
TAIL = {
    "LOADING": "저장된 설정 확인 중",
    "DEFAULT": "저장된 설정 없음 · 기본값",
    "RESTORED": "저장된 설정 복원됨",
    "SAVING": "저장 중",
    "SAVED": "저장됨 · 다음 시작에도 유지",
    "INVALID": "설정 파일 손상 · 저장 안 됨, 다음 시작에 유지되지 않을 수 있음. "
    "‘설정 재설정’으로 교체할 수 있습니다",
    "FUTURE_VERSION": "다른(새) 버전의 설정을 보존 · 이 버전에서는 저장하지 않음",
    "SAVE_FAILED": "저장 안 됨, 다음 시작에 유지되지 않을 수 있음",
    "CONFLICT": "저장 안 됨 · 다른 곳에서 설정이 바뀌었습니다(파일: "
    + AUTO_TEXT
    + "). 다시 선택하면 저장합니다",
}


def v1(policy: str) -> bytes:
    return b'{"schema_version":1,"execution_policy":"' + policy.encode() + b'"}'


def shown(policy: str, state: str) -> str:
    """The status label, by hand: the current run and, separately, its persistence."""
    text = "현재 실행: " + SHOWN[policy] + " · " + TAIL[state]
    return text + (NOTE if policy != FALLBACK else "")


def spin(app: QApplication, condition: Callable[[], bool], timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.001)
    app.processEvents()
    assert condition()


def settle(app: QApplication, window: Any) -> None:
    """Every submitted settings read/write has run and its answer was delivered."""
    spin(app, lambda: not window._policy_tasks)


def select(app: QApplication, window: Any, policy: str) -> None:
    """A user's choice as Qt reports it (U rows below use real keys instead)."""
    combo = window.device_policy
    index = combo.findData(policy)
    combo.setCurrentIndex(index)
    combo.activated.emit(index)
    settle(app, window)


class Vault:
    def read(self, key: str) -> bytes | None:
        return None

    def write(self, *args: Any) -> None:
        pytest.fail("no credential writes")

    def delete(self, *args: Any) -> None:
        pytest.fail("no credential deletion")


# --- S: old 3 x new 3 x Job stage 5 x backend 4 = 180 -------------------------------

# backend -> (feature, provider, ResourceRequest backend), by hand.
BACKENDS = {
    "CT2": ("stt", "faster_whisper", "LOCAL_CT2"),
    "SHERPA": ("diarization", "sherpa_onnx", "LOCAL_SHERPA"),
    "OLLAMA": ("summary", "ollama", "OLLAMA"),
    "REMOTE": ("stt", "openai", "REMOTE"),
}
# G11 section 3.1 by hand: the refused (backend, policy) pairs; everything else admits.
REFUSED = {("SHERPA", GPU): GU, ("OLLAMA", CPU): PV, ("OLLAMA", GPU): PV}
# This fixture has no GPU: the CT2 plan device per policy (None: refused at planning).
DEVICE = {CPU: "cpu", GPU: None, FALLBACK: "cpu"}
STAGES = ("prepare", "queued", "running", "blocked", "remote_unknown")
S_ROWS = list(product(POLICIES, POLICIES, STAGES, tuple(BACKENDS)))
S_CASES = [pytest.param(*row, id=f"G16-S-{i:03d}") for i, row in enumerate(S_ROWS, 1)]
MODEL_FILES = {"model.bin": b"g16-model", "config.json": b"{}", "tokenizer.json": b"[]"}
# G-P13 (C00-approved oracle change): the CT2 key digest is the canonical artifact
# digest, written out by hand: the domain tag, then the exact canonical JSON of the
# name-sorted (name, size, SHA-256, state) rows; the absent preprocessor is the fixed
# default and the absent vocabulary is recorded as absent. Not the product's helper.
_ROWS = ",".join(
    f'["{name}",{len(MODEL_FILES[name])},"{hashlib.sha256(MODEL_FILES[name]).hexdigest()}","PRESENT"]'
    if name in MODEL_FILES
    else f'["{name}",0,"","{state}"]'
    for name, state in (
        ("config.json", "PRESENT"),
        ("model.bin", "PRESENT"),
        ("preprocessor_config.json", "ABSENT_DEFAULT"),
        ("tokenizer.json", "PRESENT"),
        ("vocabulary.json", "ABSENT"),
        ("vocabulary.txt", "ABSENT"),  # G13R-01: the second vocabulary form, absent
    )
)
CANONICAL = (
    '{"files":['
    + _ROWS
    + '],"kind":"whisper","loader":"faster-whisper-1.2.1-files-v1","version":1}'
).encode("ascii")
DIGEST = hashlib.sha256(b"recoryn.model-artifact.v1\x00" + CANONICAL).hexdigest()


class SEnv:
    """One real MainWindow with a finished recording and a complete transcript."""

    def __init__(self, root: Path, mp: pytest.MonkeyPatch) -> None:
        import recoryn.diarization as diarization
        import recoryn.security as security
        import recoryn.summarization as summarization
        import recoryn.transcription as transcription
        from recoryn.storage import Library
        from recoryn.ui.main import MainWindow

        mp.setattr(
            security, "CredentialVault", lambda: REAL_VAULT(backend=Vault(), namespace="g16")
        )
        self.app = QApplication.instance() or QApplication([])
        self._library = Library(root / "library")
        self.library = self._library.__enter__()
        self.session = recording(self.library)
        self.window = window = MainWindow(self.library)
        window.timer.stop()
        settle(self.app, window)
        assert window.policy.state == "DEFAULT"
        self.settings = window.policy.store.path()
        window.refresh_sessions()
        spin(self.app, lambda: window.sessions.count() == 1)
        window.sessions.setCurrentRow(0)
        self.bridge = window.ai_bridge
        self.service = self.bridge._service()
        seed = self.service.transcribe(
            self.session,
            FakeSTT(),
            config_key="seed",
            resource_request=ResourceRequest("stt", "LOCAL_CT2", CPU),
        )
        assert finished(self.service, seed).state.value == "SUCCEEDED"
        self.bridge.panel.load(self.session)
        self.dispatched: list[str] = []

        def dispatch(job_id: str, *args: Any, **kwargs: Any) -> bool:
            self.dispatched.append(job_id)  # fixture only: admitted intents stay QUEUED
            return True

        mp.setattr(self.service.runner, "submit", dispatch)
        mp.setattr(window.model_panel, "request_attestation_check", lambda: None)
        self.prepared: list[str] = []
        self.policies: list[str] = []
        self.configs: list[str] = []
        self.ready: tuple[str, str] | None = None

        def prepare(kind: str, *args: Any) -> Any:
            self.prepared.append(kind)
            if self.ready is None:
                raise StateConflict("CONSENT_REQUIRED")  # the independent consent step
            provider, key = self.ready
            return SimpleNamespace(
                config=SimpleNamespace(provider_id=provider),
                context=ExecutionContext(),
                config_key=key,
                gateway=object(),
            )

        mp.setattr(
            window.privacy_panel.backend, "prepare_execution", lambda intent: prepare(intent.kind)
        )
        request = self.bridge._request

        def spy(kind: str, provider: Any, policy: str, **kwargs: Any) -> Any:
            self.policies.append(policy)  # the policy each request captured
            return request(kind, provider, policy, **kwargs)

        mp.setattr(self.bridge, "_request", spy)

        def config(*args: Any, **kwargs: Any) -> Any:
            self.configs.append("config")
            raise ValueError("fixture manifest")

        mp.setattr(diarization, "DiarizationConfig", config)
        model = root / "model"
        model.mkdir()
        for name, data in MODEL_FILES.items():
            (model / name).write_bytes(data)
        window.local_model.setText(str(model))
        # G-P13 explicit approval fixture: the real snapshot recorded in this window's run
        # registry with Yes and the responsibility check (no always-passing gate).
        registry = window.model_panel.confirmations
        snapshot = window.model_panel.model_snapshot(model)
        assert snapshot.artifact_digest == DIGEST  # the hand-written oracle above
        assert registry.confirm(
            snapshot, shown=registry.key(snapshot), accepted=True, acknowledged=True
        )
        mp.setattr(transcription, "cuda_runtime_available", lambda: False)
        mp.setattr(transcription, "OpenAITranscriber", lambda gateway, config: FakeSTT())
        mp.setattr(summarization, "OllamaSummarizer", lambda gateway, config: FakeSummary())

        def plan(request: ResourceRequest, *args: Any, **kwargs: Any) -> Any:
            device = DEVICE[request.policy]
            if device is None:
                raise StateConflict("DEVICE_UNAVAILABLE")
            return SimpleNamespace(device=device)

        mp.setattr(self.service.scheduler, "prepare", plan)

    def close(self) -> None:
        self.window.close()
        spin(self.app, lambda: self.window._closing)
        self.window.deleteLater()
        self.app.processEvents()
        self._library.__exit__(None, None, None)

    def provider(self, kind: str, provider: str) -> None:
        if kind in ("stt", "summary"):
            control = self.window.privacy_panel.controls[kind].provider
            control.setCurrentIndex(control.findData(provider))

    def choose(self, policy: str) -> None:
        select(self.app, self.window, policy)
        assert self.window.policy.state == "SAVED" and self.window.policy.current == policy
        assert self.settings.read_bytes() == v1(policy)

    def choose_only(self, policy: str) -> None:
        """A saved choice that requests nothing: no AI request, preparation or config."""
        self.prepared.clear()
        self.policies.clear()
        self.configs.clear()
        self.choose(policy)
        assert self.prepared == [] and self.policies == [] and self.configs == []

    def click(self, kind: str) -> str:
        bridge = self.bridge
        self.prepared.clear()
        self.policies.clear()
        self.configs.clear()
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
        return str(bridge.panel.job_status.text())

    def check_new_request(self, kind: str, backend: str, policy: str) -> None:
        """A new request captures ``policy`` and meets its own, independent gate."""
        jobs = self.service.jobs.list_for_session(self.session)
        text = self.click(kind)
        assert self.policies and set(self.policies) == {policy}
        assert self.service.jobs.list_for_session(self.session) == jobs  # no Job either way
        code = REFUSED.get((backend, policy))
        if code is not None:
            assert code in text and self.prepared == [] and self.configs == []
        elif kind == "diarization":
            assert self.configs == ["config"] and self.prepared == []
        else:
            assert self.prepared == [kind] and "CONSENT_REQUIRED" in text


@pytest.fixture(scope="module")
def senv(tmp_path_factory: pytest.TempPathFactory) -> Iterator[SEnv]:
    mp = pytest.MonkeyPatch()
    env: SEnv | None = None
    try:
        env = SEnv(tmp_path_factory.mktemp("g16-s"), mp)
        yield env
    finally:
        if env is not None:
            env.close()
        mp.undo()


def make_job(
    env: SEnv, backend: str, policy: str, key: str, case: str
) -> tuple[str, ResourceRequest]:
    """A real admitted Job whose captured request names ``policy``.

    A refused pair is admitted under an allowed policy of the same backend and then
    holds the refused capture, as a request captured before this build refused it (the
    G11 Ua note). CT2 rows share a semantic key, so each carries its own request nonce,
    remembered the way the bridge remembers the nonce of a request it made.
    """
    kind, _, name = BACKENDS[backend]
    request = ResourceRequest(
        kind, name, policy, model_identity=DIGEST if backend == "CT2" else None
    )
    admitted = request
    if (backend, policy) in REFUSED:
        admitted = ResourceRequest(kind, name, FALLBACK if backend == "OLLAMA" else CPU)
    service = env.service
    if kind == "stt":
        nonce = case if backend == "CT2" else None
        job_id = service.transcribe(
            env.session,
            FakeSTT(),
            config_key=key,
            resource_request=admitted,
            request_nonce=nonce,
        )
        env.bridge._job_options[job_id] = ("stt", nonce, "")
    elif kind == "summary":
        job_id = service.summarize(
            env.session, FakeSummary(), config_key=key, resource_request=admitted
        )
    else:
        job = service.jobs.create("diarization", key)
        service.jobs.bind_session(job.job_id, env.session)
        service.capture_diarization(job.job_id, admitted)
        job_id = job.job_id
    assert service.jobs.get(job_id).state.value == "QUEUED"  # a new Job of this row
    service._resource_requests[job_id] = request
    return job_id, request


@pytest.mark.parametrize(("old", "new", "stage", "backend"), S_CASES)
def test_a_saved_choice_reaches_only_new_snapshots(
    senv: SEnv, request: pytest.FixtureRequest, old: str, new: str, stage: str, backend: str
) -> None:
    case = request.node.callspec.id
    kind, provider, _ = BACKENDS[backend]
    env, service = senv, senv.service
    env.provider(kind, provider)
    env.choose(old)
    if stage == "prepare":
        env.check_new_request(kind, backend, old)
        env.choose_only(new)
        env.check_new_request(kind, backend, new)
        if (backend, new) in REFUSED:  # G-P07 navigation only moves focus; never a save
            saved = env.settings.read_bytes()
            env.bridge.open_blocked_action()
            assert env.window.tabs.currentWidget().isAncestorOf(env.window.device_policy)
            settle(env.app, env.window)
            assert env.settings.read_bytes() == saved and env.window.policy.state == "SAVED"
        return
    # The semantic key: the CT2 key names the planned device (digest:device), by hand.
    key = DIGEST + (":cuda" if old == GPU else ":cpu") if backend == "CT2" else case
    job_id, captured = make_job(env, backend, old, key, case)
    refused_old = REFUSED.get((backend, old))
    if stage in ("running", "remote_unknown"):
        attempt = service.jobs.claim(job_id, "fixture")
        if stage == "remote_unknown":
            service.jobs.fail(job_id, attempt.attempt_id, attempt.fence, "REMOTE_OUTCOME_UNKNOWN")
    elif stage == "blocked":
        reason, code = (
            ("CAPABILITY", refused_old) if refused_old else ("BUDGET", "COST_CAP_EXCEEDED")
        )
        record = service.jobs.get(job_id)
        service.jobs.block_pending(job_id, reason, code, expected_version=record.state_version)
    env.bridge.tick()
    before, dispatched = service.jobs.get(job_id), len(env.dispatched)
    env.ready = (provider, "prepared-" + case if backend == "CT2" else key)
    try:  # even with consent ready, a choice alone is never a continue or a request
        env.choose_only(new)  # saved, and the next start restores it
        env.bridge.tick()
    finally:
        env.ready = None
    # The captured request, the Job record (state, version, input key) and the dispatch
    # count are unchanged: a selection is neither an implicit resume nor a rewrite.
    assert service.resource_request(job_id) is captured
    assert service.jobs.get(job_id) == before and len(env.dispatched) == dispatched
    if stage in ("queued", "running"):
        env.check_new_request(kind, backend, new)
        assert service.jobs.get(job_id) == before and service.resource_request(job_id) is captured
        return
    # G-P07: a known block continues explicitly (diarization has no continue); the
    # continue captures the current selection as a new snapshot, then meets its gate.
    continuable = stage == "blocked" and backend != "SHERPA"
    env.prepared.clear()
    env.ready = (provider, "prepared-" + case if backend == "CT2" else key)
    try:
        env.bridge.continue_blocked()  # the explicit G-P07 continue
        spin(env.app, lambda: not env.bridge.busy)
    finally:
        env.ready = None
    after = service.jobs.get(job_id)
    text = str(env.bridge.panel.job_status.text())
    if not continuable:  # REMOTE_UNKNOWN or diarization: no continue
        assert after == before and env.prepared == [] and len(env.dispatched) == dispatched
        assert service.resource_request(job_id) is captured
        return
    resumed = not (
        (backend == "OLLAMA" and new != FALLBACK)  # PV before any preparation
        or (backend == "CT2" and DEVICE[new] is None)  # the plan refuses: no GPU here
        or (backend == "CT2" and old == GPU)  # cuda -> cpu: another semantic key
    )
    if not resumed:
        assert after == before and service.resource_request(job_id) is captured
        assert len(env.dispatched) == dispatched
        if backend == "OLLAMA":
            assert PV in text and "기존 Job BLOCKED 유지" in text and env.prepared == []
        else:
            assert env.prepared == ["stt"]
        return
    assert after.state.value == "QUEUED" and after.input_key == before.input_key
    assert after.attempt_count == before.attempt_count
    assert env.dispatched[dispatched:] == [job_id]  # one dispatch of the same Job
    fresh = service.resource_request(job_id)
    assert fresh is not captured and fresh.policy == new and fresh.backend == captured.backend
    assert env.prepared == [{"OLLAMA": "summary"}.get(backend, "stt")]


# --- U: UI state 10 x key 4 x same poll / new meaning 2 = 80 -------------------------

U_STATES = (
    "LOADING",
    "DEFAULT",
    "RESTORED",
    "SAVING",
    "SAVED",
    "INVALID",
    "FUTURE_VERSION",
    "SAVE_FAILED",
    "CONFLICT",
    "CLOSED",
)
U_KEYS = ("Tab", "Enter", "Space", "Arrow")
U_ROWS = list(product(U_STATES, U_KEYS, ("same", "new")))
U_CASES = [pytest.param(*row, id=f"G16-U-{i:02d}") for i, row in enumerate(U_ROWS, 1)]
FUTURE = b'{"schema_version":2,"execution_policy":"GPU_ONLY"}'
# State -> (current policy shown once established), by hand.
U_CURRENT = {
    "LOADING": CPU,
    "DEFAULT": CPU,
    "RESTORED": GPU,
    "SAVING": FALLBACK,
    "SAVED": CPU,
    "INVALID": CPU,
    "FUTURE_VERSION": CPU,
    "SAVE_FAILED": CPU,
    "CONFLICT": CPU,
}


class FailingReplace(PolicyIo):
    def replace(self, source: Path, target: Path) -> None:
        raise PermissionError("G16 sharing violation")


class Gated(DevicePolicyStore):
    """A real store that records each call and can hold the settings worker."""

    def __init__(
        self, path: Path, io: PolicyIo | None = None, *, lock_timeout: float = 2.0
    ) -> None:
        super().__init__(path, io=io, lock_timeout=lock_timeout)
        self.calls: list[str] = []
        self.load_gate: threading.Event | None = None
        self.save_gate: threading.Event | None = None

    @staticmethod
    def worker_only() -> None:
        assert threading.current_thread() is not threading.main_thread(), "GUI-thread I/O"

    def load(self) -> Any:
        self.worker_only()
        self.calls.append("load")
        if self.load_gate is not None:
            assert self.load_gate.wait(30)
        return super().load()

    def save(self, policy: str, *, observed_revision: str | None) -> Any:
        self.worker_only()
        self.calls.append("save")
        if self.save_gate is not None:
            assert self.save_gate.wait(30)
        return super().save(policy, observed_revision=observed_revision)

    def reset_invalid(self, policy: str, *, observed_revision: str | None, confirmed: bool) -> Any:
        self.worker_only()
        self.calls.append("reset")
        return super().reset_invalid(
            policy, observed_revision=observed_revision, confirmed=confirmed
        )

    def release(self) -> None:
        for gate in (self.load_gate, self.save_gate):
            if gate is not None:
                gate.set()


class UEnv:
    def __init__(self, root: Path, mp: pytest.MonkeyPatch) -> None:
        from recoryn.storage import Library
        from recoryn.ui.main import MainWindow

        self.app = QApplication.instance() or QApplication([])
        self._library = Library(root / "library")
        self.library = self._library.__enter__()
        self.window = MainWindow(self.library)
        self.window.timer.stop()
        mp.setattr(self.window.model_panel, "request_attestation_check", lambda: None)
        self.window.show()
        tabs = self.window.tabs  # the page that holds the policy control, as a user opens it
        page = next(
            tabs.widget(i)
            for i in range(tabs.count())
            if tabs.widget(i).isAncestorOf(self.window.device_policy)
        )
        tabs.setCurrentWidget(page)
        settle(self.app, self.window)
        assert self.window.policy_reset_button.isVisible()
        self.announced: list[tuple[str, str]] = []
        self.window._policy_announce = lambda target, text, priority: self.announced.append(
            (text, priority)
        )
        self.questions: list[str] = []
        self.answer = QMessageBox.StandardButton.No

        def question(*args: Any, **kwargs: Any) -> Any:
            self.questions.append(str(args[1]))
            return self.answer

        mp.setattr(QMessageBox, "question", question)
        self.store: Gated | None = None

    def bind(self, store: Gated) -> None:
        """A fresh controller on this window's own callbacks (the __init__ wiring)."""
        from recoryn.app.device_policy import PolicyController

        window = self.window
        window.policy.close()
        window.policy = PolicyController(store, window._policy_submit, window._show_policy)
        self.store = store
        window.policy.start()

    def finish(self) -> None:
        if self.store is not None:
            self.store.release()
        settle(self.app, self.window)

    def close(self) -> None:
        self.finish()
        self.window.close()
        spin(self.app, lambda: self.window._closing)
        self.window.deleteLater()
        self.app.processEvents()
        self._library.__exit__(None, None, None)


@pytest.fixture(scope="module")
def uenv(tmp_path_factory: pytest.TempPathFactory) -> Iterator[UEnv]:
    mp = pytest.MonkeyPatch()
    env: UEnv | None = None
    try:
        env = UEnv(tmp_path_factory.mktemp("g16-u"), mp)
        yield env
    finally:
        if env is not None:
            env.close()
        mp.undo()


class Closed:
    """A real window closed while a settings write was running."""

    def __init__(self, root: Path, mp: pytest.MonkeyPatch) -> None:
        from recoryn.storage import Library
        from recoryn.ui.main import MainWindow

        self.app = QApplication.instance() or QApplication([])
        self.path = root / "LocalAppData" / "Recoryn" / "preferences" / "device-policy.json"
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(v1(GPU))
        self.store = Gated(self.path)
        self._library = Library(root / "library")
        library = self._library.__enter__()
        self.window = window = MainWindow(library, policy_store=self.store)
        window.timer.stop()
        mp.setattr(window.model_panel, "request_attestation_check", lambda: None)
        window.show()
        settle(self.app, window)
        assert window.policy.state == "RESTORED"
        self.announced: list[tuple[str, str]] = []
        window._policy_announce = lambda target, text, priority: self.announced.append(
            (text, priority)
        )
        self.store.save_gate = threading.Event()
        index = window.device_policy.findData(CPU)
        window.device_policy.setCurrentIndex(index)
        window.device_policy.activated.emit(index)
        spin(self.app, lambda: self.store.calls == ["load", "save"])
        self.label = window.policy_status.text()
        window.close()
        spin(self.app, lambda: window._closing_requested)
        self.store.release()  # the started write completes; its answer arrives late
        spin(self.app, lambda: window._closing)
        assert self.path.read_bytes() == v1(CPU)  # a started write was never abandoned
        assert self.announced == [] and window.policy.state == "CLOSED"

    def close(self) -> None:
        self.window.deleteLater()
        self.app.processEvents()
        self._library.__exit__(None, None, None)


@pytest.fixture(scope="module")
def closed(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Closed]:
    mp = pytest.MonkeyPatch()
    env: Closed | None = None
    try:
        env = Closed(tmp_path_factory.mktemp("g16-closed"), mp)
        yield env
    finally:
        if env is not None:
            env.close()
        mp.undo()


def establish(env: UEnv, state: str, root: Path) -> tuple[Gated, Path]:
    path = root / "LocalAppData" / "Recoryn" / "preferences" / "device-policy.json"
    path.parent.mkdir(parents=True)
    content = {"DEFAULT": None, "INVALID": b"{", "FUTURE_VERSION": FUTURE}.get(state, v1(GPU))
    if content is not None:
        path.write_bytes(content)
    # A failing replace is retried within the call up to its bound (shortened here).
    failing = state == "SAVE_FAILED"
    store = Gated(path, FailingReplace() if failing else None, lock_timeout=0.2 if failing else 2.0)
    if state == "LOADING":
        store.load_gate = threading.Event()
    env.bind(store)
    if state == "LOADING":
        spin(env.app, lambda: store.calls == ["load"])
        return store, path
    settle(env.app, env.window)
    if state == "SAVING":
        store.save_gate = threading.Event()
        index = env.window.device_policy.findData(FALLBACK)
        env.window.device_policy.setCurrentIndex(index)
        env.window.device_policy.activated.emit(index)
        spin(env.app, lambda: store.calls == ["load", "save"])
    elif state in ("SAVED", "SAVE_FAILED", "CONFLICT"):
        if state == "CONFLICT":  # another app writes after this window read the file
            assert DevicePolicyStore(path).save(FALLBACK, observed_revision=None).state == "SAVED"
        select(env.app, env.window, CPU)
    return store, path


def arrow(env: UEnv) -> str:
    """One real arrow key on the focused policy control; returns the policy it lands on."""
    combo = env.window.device_policy
    combo.setFocus()
    index = combo.currentIndex()
    QTest.keyClick(combo, Qt.Key.Key_Down if index < 2 else Qt.Key.Key_Up)
    return POLICIES[index + 1 if index < 2 else index - 1]


def final_state(state: str, key: str, policy: str) -> str:
    """The persistence state after a new choice of ``policy``, by hand."""
    if state == "SAVE_FAILED":
        # The replace still fails; the file already holds GPU_ONLY, so that needs no write.
        return "SAVED" if policy == GPU else "SAVE_FAILED"
    if state == "INVALID" and key != "Enter":
        return "INVALID"  # only a confirmed reset replaces the damaged file
    if state == "FUTURE_VERSION":
        return "FUTURE_VERSION"
    return "SAVED"


@pytest.mark.parametrize(("state", "key", "poll"), U_CASES)
def test_keys_and_polls_show_one_honest_status(
    request: pytest.FixtureRequest, tmp_path: Path, state: str, key: str, poll: str
) -> None:
    if state == "CLOSED":
        closed_window(request.getfixturevalue("closed"), key, poll)
        return
    env: UEnv = request.getfixturevalue("uenv")
    window, app = env.window, env.app
    store, path = establish(env, state, tmp_path)
    try:
        current = U_CURRENT[state]
        shown_state = "SAVING" if state == "SAVING" else state
        assert window.policy_status.text() == shown(current, shown_state)
        assert window.device_policy.currentText() == current
        assert window.policy_reset_button.isEnabled() is (state == "INVALID")
        content = path.read_bytes() if path.exists() else None
        calls, said = list(store.calls), len(env.announced)
        env.questions.clear()
        gated = state in ("LOADING", "SAVING")
        # 1. The key, as real Qt input.
        if key == "Tab":
            window.device_policy.setFocus()
            spin(app, lambda: window.device_policy.hasFocus())
            QTest.keyClick(window.device_policy, Qt.Key.Key_Tab)
            app.processEvents()
            focused = QApplication.focusWidget()
            assert (focused is window.policy_reset_button) is (state == "INVALID")
            assert focused is not window.device_policy
            assert store.calls == calls and len(env.announced) == said
            assert window.device_policy.currentText() == current
        elif key == "Arrow":
            current = arrow(env)
            assert window.device_policy.currentText() == current == window.policy.current
            if gated:
                assert window.policy_status.text() == shown(current, "SAVING")
                assert store.calls == calls  # queued behind the held read/write
            else:
                settle(app, window)
                after = final_state(state, key, current)
                assert store.calls == [*calls, "save"]
                assert window.policy_status.text() == shown(current, after)
                assert len(env.announced) == said + 1
                if after == "SAVED":
                    assert path.read_bytes() == v1(current)
                else:
                    assert path.read_bytes() == content
        else:
            env.answer = (
                QMessageBox.StandardButton.Yes if key == "Enter" else QMessageBox.StandardButton.No
            )
            QTest.keyClick(
                window.policy_reset_button,
                Qt.Key.Key_Return if key == "Enter" else Qt.Key.Key_Space,
            )
            settle(app, window) if not gated else app.processEvents()
            if state == "INVALID":
                assert env.questions == ["AI 실행 정책 설정 재설정"]  # one question, never two
                if key == "Enter":
                    assert store.calls == [*calls, "reset"] and path.read_bytes() == v1(CPU)
                    assert window.policy_status.text() == shown(CPU, "SAVED")
                    assert len(env.announced) == said + 1
                else:  # No (the default) writes nothing
                    assert store.calls == calls and path.read_bytes() == content
                    assert window.policy_status.text() == shown(CPU, "INVALID")
                    assert len(env.announced) == said
            else:  # a disabled reset button takes no key
                assert env.questions == [] and store.calls == calls
                assert len(env.announced) == said
        # 2. The poll axis.
        text, index, said, calls = (
            window.policy_status.text(),
            window.device_policy.currentIndex(),
            len(env.announced),
            list(store.calls),
        )
        disk = path.read_bytes() if path.exists() else None
        if poll == "same":
            for _ in range(2):
                window.ai_bridge.tick()
                app.processEvents()
            assert window.policy_status.text() == text
            assert window.device_policy.currentIndex() == index
            assert len(env.announced) == said and store.calls == calls
            assert (path.read_bytes() if path.exists() else None) == disk
            return
        env.finish()  # a held read/write completes
        said = len(env.announced)
        current = arrow(env)
        settle(app, window)
        after = final_state(state, key, current)
        assert window.policy_status.text() == shown(current, after)
        # The new choice saves once; a choice queued behind a held read/write ran too.
        queued = 1 if gated and key == "Arrow" else 0
        assert store.calls[-1] == "save"
        assert store.calls.count("save") == calls.count("save") + 1 + queued
        assert env.announced[said:] == [
            (shown(current, after), "polite" if after == "SAVED" else "assertive")
        ]
        if after == "SAVED":
            assert path.read_bytes() == v1(current)
        else:
            assert path.read_bytes() == content
    finally:
        env.finish()


def closed_window(env: Closed, key: str, poll: str) -> None:
    window, app = env.window, env.app
    calls, said = list(env.store.calls), len(env.announced)
    target = window.policy_reset_button if key in ("Enter", "Space") else window.device_policy
    qt_key = {
        "Tab": Qt.Key.Key_Tab,
        "Enter": Qt.Key.Key_Return,
        "Space": Qt.Key.Key_Space,
        "Arrow": Qt.Key.Key_Down,
    }[key]
    QTest.keyClick(target, qt_key)
    app.processEvents()
    if poll == "same":
        window._show_policy(window.policy.view(), True)  # a repeated notification
    else:  # a late answer of a newer meaning
        controller = window.policy
        controller._saved(controller._ticket, PolicyWriteResult("SAVED", GPU, None))
    app.processEvents()
    assert env.store.calls == calls and len(env.announced) == said
    assert window.policy.state == "CLOSED" and window.policy_status.text() == env.label
    assert env.path.read_bytes() == v1(CPU)


# --- X: the entry point's wiring ----------------------------------------------------


def test_entry_point_saves_and_restores_through_the_user_location(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G16-X-01 (C00): run() builds the window on the real per-user store."""
    import recoryn.ui.main as main_module

    appdata = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(appdata))
    settings = appdata / "Recoryn" / "preferences" / "device-policy.json"
    library_root = tmp_path / "library"
    app = QApplication.instance() or QApplication([])
    runs: list[tuple[str, str, str]] = []

    def window_of_this_run() -> Any:
        found = [
            widget
            for widget in QApplication.topLevelWidgets()
            if isinstance(widget, main_module.MainWindow)
            and Path(widget.library.root) == library_root
            and not widget._closing_requested
        ]
        assert len(found) == 1
        return found[0]

    def exec_(self: Any) -> int:
        window = window_of_this_run()
        window.timer.stop()
        monkeypatch.setattr(window.model_panel, "request_attestation_check", lambda: None)
        settle(app, window)
        store = window.policy.store  # the real per-user store at LOCALAPPDATA, not None
        assert store is not None and store.path() == settings, "run() did not wire the store"
        runs.append(
            (window.policy.state, window.device_policy.currentText(), window.policy_status.text())
        )
        if len(runs) == 1:
            combo = window.device_policy
            tabs = window.tabs  # open the page that holds the control, as a user does
            tabs.setCurrentWidget(
                next(
                    tabs.widget(i)
                    for i in range(tabs.count())
                    if tabs.widget(i).isAncestorOf(combo)
                )
            )
            combo.setFocus()
            QTest.keyClick(combo, Qt.Key.Key_Down)  # CPU_ONLY -> GPU_ONLY, by keyboard
            settle(app, window)
            assert window.policy.state == "SAVED"
        window.close()
        spin(app, lambda: window._closing)
        window.deleteLater()
        app.processEvents()
        return 0

    monkeypatch.setattr(QApplication, "exec", exec_)
    assert not settings.exists()
    assert main_module.run(str(library_root)) == 0
    assert settings.is_file() and settings.read_bytes() == v1(GPU)  # the per-PC location
    assert main_module.run(str(library_root)) == 0
    assert runs == [
        ("DEFAULT", CPU, shown(CPU, "DEFAULT")),
        ("RESTORED", GPU, shown(GPU, "RESTORED")),  # the next start restores it
    ]


def test_a_restore_never_starts_ai_work(senv: SEnv, tmp_path: Path) -> None:
    """G16-X-03: restoring a saved policy, with a session selected, requests nothing:
    no AI request, consent/cost preparation, diarization config, Job or dispatch."""
    from recoryn.app.device_policy import PolicyController

    env, window = senv, senv.window
    path = tmp_path / "LocalAppData" / "Recoryn" / "preferences" / "device-policy.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(v1(GPU))
    jobs, dispatched = env.service.jobs.list_for_session(env.session), len(env.dispatched)
    env.policies.clear()
    env.prepared.clear()
    env.configs.clear()
    original = window.policy
    window.policy = PolicyController(
        DevicePolicyStore(path), window._policy_submit, window._show_policy
    )
    try:
        window.policy.start()
        settle(env.app, window)
        assert window.policy.state == "RESTORED" and window.device_policy.currentText() == GPU
        env.bridge.tick()
        combo = window.device_policy  # section 4: the control's name and description
        assert combo.accessibleName() == "AI 실행 정책"
        assert "새 요청에 적용, 진행 중인 작업은 기존 정책 유지" in combo.accessibleDescription()
        assert [combo.itemText(i) for i in range(3)] == ["CPU_ONLY", "GPU_ONLY", AUTO_TEXT]
        assert env.policies == [] and env.prepared == [] and env.configs == []
        assert env.service.jobs.list_for_session(env.session) == jobs
        assert len(env.dispatched) == dispatched
    finally:
        window.policy.close()
        window.policy = original
        window._show_policy(original.view(), False)


def test_declared_ui_denominators_are_complete_and_unique() -> None:
    assert len(S_CASES) == 3 * 3 * 5 * 4 == 180 and len(U_CASES) == 10 * 4 * 2 == 80
    assert [c.id for c in S_CASES] == [f"G16-S-{i:03d}" for i in range(1, 181)]
    assert [c.id for c in U_CASES] == [f"G16-U-{i:02d}" for i in range(1, 81)]
    assert set(U_CURRENT) == set(U_STATES) - {"CLOSED"}
