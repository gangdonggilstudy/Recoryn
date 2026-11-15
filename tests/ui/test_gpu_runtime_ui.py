"""GPU runtime choice through the real window, bridge, Task and ResourceScheduler (L07).

Only the GPU probe, the CUDA source checks, the runtime's status/generation and the
transcription worker are fakes; no process, model, GPU or network is used. Covers the
review findings L07-U01 (failure tracking), L07-U02 (codes reach the user) and L07-U03
(pending runtime removal versus a new transcription).
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

import recoryn.models
import recoryn.transcription
from recoryn.app.desktop import DesktopRecorder, TrackSelection
from recoryn.domain import AudioFormat, PCMBlock, StateConflict
from recoryn.models.gpu_runtime import GpuRuntimeManager
from recoryn.models.resources import GPUInfo
from recoryn.providers import ProviderError, STTResult, TranscriptSegment
from recoryn.storage import Library
from recoryn.ui import ai_bridge
from recoryn.ui.main import MainWindow

pytestmark = pytest.mark.ui


def spin(app: QApplication, predicate: Any, *, timeout: float = 5) -> None:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.001)
    app.processEvents()
    assert predicate()


class Source:
    def start(self, session: Any, track: Any, epoch: Any, submit: Any, on_health: Any) -> Any:
        return AudioFormat(8000, 1)

    def stop(self, timeout: float = 5) -> None:
        pass


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    app = QApplication.instance() or QApplication([])
    plan = SimpleNamespace(status="READY", generation=(1, 1), gpu=True, fail_gpu=False, created=[])

    class FakeLocal:
        def __init__(self, model: Path, *, device: str = "cpu", gpu_runtime: Any = None) -> None:
            self.device = device
            self.gpu_runtime = gpu_runtime if device == "cuda" else None
            self.gpu_failure: str | None = None
            self.closed = False
            plan.created.append(self)

        def transcribe(self, request: Any, context: Any = None) -> STTResult:
            if self.gpu_runtime is not None and plan.fail_gpu:
                self.gpu_failure = "GPU_RUNTIME_DAMAGED"
                raise ProviderError("GPU_RUNTIME_DAMAGED")
            segment = TranscriptSegment("line", request.offset_ms, request.offset_ms + 500, "x")
            return STTResult("fake", "local-model", (segment,), True)

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(ai_bridge, "LocalSTTProcess", FakeLocal)
    monkeypatch.setattr(
        recoryn.models,
        "probe_gpus",
        lambda: (
            ("OBSERVED", (GPUInfo(0, "fake", 8 * 2**30, 8 * 2**30),))
            if plan.gpu
            else ("UNAVAILABLE", ())
        ),
    )
    monkeypatch.setattr(recoryn.transcription, "cuda_runtime_available", lambda: False)
    monkeypatch.setattr(GpuRuntimeManager, "status", lambda self: plan.status)
    monkeypatch.setattr(
        GpuRuntimeManager,
        "generation",
        lambda self: None if plan.status == "NOT_INSTALLED" else plan.generation,
    )
    windows: list[MainWindow] = []

    def open_window(library: Library) -> MainWindow:
        recorder = DesktopRecorder(library, lambda *args: Source())
        window = MainWindow(library, recorder=recorder)
        window.timer.stop()
        window.local_model.setText(str(model))
        window.device_policy.setCurrentText("GPU_WITH_CPU_FALLBACK_ALLOWED")
        windows.append(window)
        return window

    def close_window(window: MainWindow) -> None:
        window.ai_bridge._preparation_cancel.set()
        spin(app, lambda: not window.ai_bridge.busy)
        window.model_panel.task = None
        window.close()
        spin(app, lambda: window._closing)
        window.deleteLater()
        app.processEvents()
        windows.remove(window)

    model = tmp_path / "model"
    model.mkdir()
    for name in ("model.bin", "config.json", "tokenizer.json"):
        (model / name).write_bytes(b"synthetic-" + name.encode())
    with Library(tmp_path / "library") as library:
        window = open_window(library)
        session = window.recorder.start(
            (TrackSelection("mic", "fake", False, AudioFormat(8000, 1)),)
        )
        recording = window.recorder.recording
        recording.chunk_frames = 8000
        assert recording.submit(
            PCMBlock(
                recording.session_id,
                "mic",
                recording.epochs["mic"],
                0,
                AudioFormat(8000, 1),
                8000,
                b"\0\x40" * 8000,
                1_000_000_000,
                1_000_000_000,
                device_frame_position=0,
            )
        )
        window.recorder.stop()
        try:
            yield SimpleNamespace(
                app=app,
                plan=plan,
                library=library,
                session=session,
                window=window,
                open_window=open_window,
                close_window=close_window,
            )
        finally:
            for item in list(windows):
                close_window(item)


def run(world: Any, window: MainWindow) -> Any:
    """One explicit transcription; its final job record, or None when none was created."""
    window.refresh_sessions()
    window.sessions.setCurrentRow(0)
    bridge = window.ai_bridge
    service = bridge.service
    known = len(service.jobs.list_for_session(world.session)) if service else 0
    bridge._transcribe(session_id=world.session, retry=True)
    spin(world.app, lambda: not bridge.busy)
    service = bridge.service
    jobs = service.jobs.list_for_session(world.session) if service else []
    if len(jobs) == known:
        return None
    final = {"SUCCEEDED", "FAILED", "CANCELLED", "BLOCKED"}
    spin(
        world.app,
        lambda: service.jobs.list_for_session(world.session)[-1].state.value in final,
    )
    return service.jobs.list_for_session(world.session)[-1]


def test_runtime_failure_is_tracked_per_install_in_this_run_only(world: Any) -> None:
    """L07-U01: the worker's own failure blocks that install; history never does."""
    plan, window = world.plan, world.window
    plan.fail_gpu = True
    first = run(world, window)
    assert plan.created[-1].device == "cuda" and plan.created[-1].gpu_runtime is not None
    assert first.state.value == "FAILED"
    plan.fail_gpu = False
    run(world, window)
    assert plan.created[-1].device == "cpu"  # this install failed in this run
    run(world, window)
    assert plan.created[-1].device == "cpu"  # a later success does not erase it
    plan.generation = (1, 2)  # the user removed and downloaded the runtime again
    run(world, window)
    assert plan.created[-1].device == "cuda"
    # A new run on the same library: the stored GPU failure job is not a new failure.
    world.close_window(window)
    plan.generation = (1, 1)
    again = world.open_window(world.library)
    job = run(world, again)
    assert plan.created[-1].device == "cuda" and job.state.value == "SUCCEEDED"


def test_gpu_only_without_gpu_shows_the_reason(world: Any) -> None:
    """L07-U02: the real Task passes RESOURCE_GPU_UNAVAILABLE to the status line."""
    plan, window = world.plan, world.window
    plan.status = "NOT_INSTALLED"
    window.device_policy.setCurrentText("GPU_ONLY")
    created = len(plan.created)
    assert run(world, window) is None  # refused while preparing; no job, no worker
    assert len(plan.created) == created
    assert "RESOURCE_GPU_UNAVAILABLE" in window.ai_bridge.panel.job_status.text()


def test_pending_runtime_removal_and_new_transcription_never_interleave(
    world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """L07-U03: both orders, through the real window guard and panel queue."""
    plan, window = world.plan, world.window
    panel = window.model_panel
    run(world, window)
    gpu_worker = plan.created[-1]
    assert gpu_worker.device == "cuda" and window.ai_bridge.local is gpu_worker
    # AI first: while the bridge is busy, removal is not even offered.
    window.ai_bridge.busy = True
    asked: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args: asked.append("asked") or QMessageBox.StandardButton.Yes,
    )
    panel.remove_gpu()
    assert asked == [] and panel.task is None
    window.ai_bridge.busy = False
    # Removal first: the idle GPU worker is closed, the removal is queued (held here)...
    held: list[Any] = []
    monkeypatch.setattr(panel.pool, "start", held.append)
    spin(world.app, window._models_idle)  # the runner has retired the finished job
    panel.remove_gpu()
    assert asked == ["asked"] and len(held) == 1 and panel.gpu_busy
    assert gpu_worker.closed and window.ai_bridge.local is None
    # ...and a transcription started meanwhile does not choose the runtime.
    run(world, window)
    assert plan.created[-1].device == "cpu" and plan.created[-1].gpu_runtime is None


def test_ai_started_during_the_delete_confirmation_keeps_its_worker(
    world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """L07-U06: the confirmation's nested event loop may start AI work; re-check after it."""
    plan, window = world.plan, world.window
    panel = window.model_panel
    run(world, window)
    gpu_worker = plan.created[-1]
    assert gpu_worker.device == "cuda"
    spin(world.app, window._models_idle)
    held: list[Any] = []
    monkeypatch.setattr(panel.pool, "start", held.append)

    def answer_after_ai_started(*args: Any) -> Any:
        window.ai_bridge.busy = True  # e.g. the live STT timer fired inside the dialog
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", answer_after_ai_started)
    try:
        panel.remove_gpu()
        assert held == [] and not panel.gpu_busy and not gpu_worker.closed
        assert window.ai_bridge.local is gpu_worker and "AI가 사용 중" in panel.gpu_status.text()
        # The bridge itself also refuses, whatever the caller checked before.
        with pytest.raises(StateConflict, match="AI_MODEL_CHANGE_REQUIRES_IDLE"):
            window.ai_bridge.release_gpu_runtime()
        assert not gpu_worker.closed
    finally:
        window.ai_bridge.busy = False
        panel.task = None
