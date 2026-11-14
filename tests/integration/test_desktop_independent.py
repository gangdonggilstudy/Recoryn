"""BR12 independent lifecycle/source-mapping oracles; never opens a device."""

from __future__ import annotations

import os
import threading
import wave
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from recoryn.app.desktop import DesktopRecorder, TrackSelection
from recoryn.app.media import prepare_clips
from recoryn.app.recording import RecordingError, RecordingService
from recoryn.domain import AudioFormat, PCMBlock, SessionState, StateConflict
from recoryn.storage import Library

pytestmark = pytest.mark.integration
_FORMAT = AudioFormat(48_000, 1)
_QT_APPLICATION: Any = None


class ControlledSource:
    """Explicit fake gate/ack and health callbacks, independent of WASAPI."""

    def __init__(self, *, start_fails: bool = False, native_health: bool = False) -> None:
        self.running = False
        self.start_fails = start_fails
        self.native_health = native_health
        self.stop_pending = False
        self.stop_calls = 0
        self.identity: tuple[str, str, str] | None = None
        self.submit: Callable[[PCMBlock], bool] | None = None
        self.on_health: Callable[[dict[str, Any]], None] | None = None

    def start(
        self,
        session_id: str,
        track_id: str,
        epoch_id: str,
        submit: Callable[[PCMBlock], bool],
        on_health: Callable[[dict[str, Any]], None],
    ) -> AudioFormat:
        self.running = True
        self.identity = (session_id, track_id, epoch_id)
        self.submit, self.on_health = submit, on_health
        if self.start_fails:
            raise RecordingError("DEVICE_UNAVAILABLE")
        if self.native_health:
            on_health({"event": "ready", "experimental": True})
            self.emit()
            on_health({"event": "packet", "accepted": True, "frame_count": 48, "flags": []})
        return _FORMAT

    def emit(self, *, frames: int = 48, sequence: int = 0) -> bool:
        assert self.identity is not None and self.submit is not None
        return self.submit(
            PCMBlock(
                *self.identity,
                sequence,
                _FORMAT,
                frames,
                b"\x01\0" * frames,
                sequence * 1_000_000,
                sequence * 1_000_000,
                sequence * frames,
            )
        )

    def stop(self, timeout: float = 5.0) -> None:
        self.stop_calls += 1
        if self.stop_pending:
            raise RecordingError("STOP_TIMEOUT")
        self.running = False


def choices(*tracks: str) -> tuple[TrackSelection, ...]:
    return tuple(TrackSelection(track, track, track == "system", _FORMAT) for track in tracks)


def clean(controller: DesktopRecorder, sources: list[ControlledSource]) -> None:
    for source in sources:
        source.stop_pending = False
        source.stop()
    if controller.recording is not None:
        controller.recording.join_writer()


def test_partial_start_failure_waits_for_all_source_stops_and_keeps_media(tmp_path: Path) -> None:
    sources = [ControlledSource(native_health=True), ControlledSource(start_fails=True)]
    with Library(tmp_path / "library") as library:
        controller = DesktopRecorder(library, lambda device, loopback: sources[device == "system"])
        try:
            with pytest.raises(RecordingError, match="MEDIA_PRESERVED"):
                controller.start(choices("mic", "system"))
            assert not any(source.running for source in sources)
            assert all(source.stop_calls for source in sources)
            assert controller.session_id is not None
            assert library.get_session(controller.session_id).state is SessionState.PAUSED
            assert sum(chunk.frame_count for chunk in library.chunks(controller.session_id)) == 48
        finally:
            clean(controller, sources)


@pytest.mark.parametrize("control", ["pause", "stop", "close"])
def test_missing_stop_ack_preserves_source_ownership_and_library_lock(
    tmp_path: Path, control: str
) -> None:
    source = ControlledSource()
    with Library(tmp_path / "library") as library:
        controller = DesktopRecorder(library, lambda device, loopback: source)
        try:
            session = controller.start(choices("mic"))
            source.stop_pending = True
            with pytest.raises(RecordingError, match="ACK_PENDING"):
                getattr(controller, control)()
            assert source.running
            assert library.get_session(session).state is SessionState.RECORDING
            with pytest.raises(StateConflict):
                Library(library.root)
            source.stop_pending = False
            controller.stop()
            assert not source.running
            assert library.get_session(session).state is SessionState.FINALIZED
        finally:
            clean(controller, [source])


def test_interrupted_session_close_must_still_ack_live_sources(tmp_path: Path) -> None:
    """BR12-01: capture ownership cannot be inferred from persisted media state."""
    source = ControlledSource()
    with Library(tmp_path / "library") as library:
        controller = DesktopRecorder(library, lambda device, loopback: source)
        try:
            session_id = controller.start(choices("mic"))
            state = library.get_session(session_id)
            library.transition(session_id, SessionState.INTERRUPTED, state.state_version)
            controller.close()
            assert not source.running, "close returned while the source was still live"
            assert source.stop_calls > 0
        finally:
            clean(controller, [source])


def test_new_start_cannot_orphan_an_interrupted_source_with_missing_ack(tmp_path: Path) -> None:
    """BR12-08: new media state does not relinquish previous device ownership."""
    sources = [ControlledSource(), ControlledSource()]
    opened = iter(sources)
    with Library(tmp_path / "library") as library:
        controller = DesktopRecorder(library, lambda device, loopback: next(opened))
        original_recording: RecordingService | None = None
        try:
            original_session = controller.start(choices("mic"))
            original_recording = controller.recording
            state = library.get_session(original_session)
            library.transition(original_session, SessionState.INTERRUPTED, state.state_version)
            sources[0].stop_pending = True
            with pytest.raises((RecordingError, StateConflict)):
                controller.start(choices("mic"))
            assert controller.recording is original_recording
            assert controller.session_id == original_session
            assert sources[0].running and not sources[1].running
            sources[0].stop_pending = False
            next_session = controller.start(choices("mic"))
            assert next_session != original_session
            assert original_recording is not None and not original_recording.worker_alive
            assert not sources[0].running and sources[1].running
        finally:
            clean(controller, sources)
            if original_recording is not None:
                original_recording.join_writer()


def test_live_writer_failure_is_visible_without_user_pause_or_stop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BR12-02: persistable disk/registration failure must leave REC state."""
    source = ControlledSource()
    failed = threading.Event()
    with Library(tmp_path / "library") as library:
        controller = DesktopRecorder(library, lambda device, loopback: source)
        original_register = library.register_chunk

        def reject_chunk(descriptor: Any) -> None:
            failed.set()
            raise OSError("BR12 deterministic disk failure")

        monkeypatch.setattr(library, "register_chunk", reject_chunk)
        try:
            session = controller.start(choices("mic"))
            assert source.emit(frames=96_000)
            assert failed.wait(3)
            assert controller.recording is not None
            controller.recording.join_writer()
            assert library.get_session(session).state is SessionState.INTERRUPTED, (
                "writer is dead but persistent state still says RECORDING"
            )
        finally:
            monkeypatch.setattr(library, "register_chunk", original_register)
            clean(controller, [source])


def store_block(
    library: Library,
    *,
    frames: int,
    quality: str = "DEVICE_CORRELATED",
    flags: tuple[str, ...] = (),
) -> str:
    recorder = RecordingService(library, {"mic": _FORMAT})
    try:
        recorder.start()
        assert recorder.submit(
            PCMBlock(
                recorder.session_id,
                "mic",
                recorder.epochs["mic"],
                0,
                _FORMAT,
                frames,
                b"\x01\0" * frames,
                1_000_000_000,
                2_000_000_000,
                0,
                flags=flags,
                clock_quality=quality,
            )
        )
        recorder.stop()
        return recorder.session_id
    finally:
        recorder.join_writer()


def test_single_large_packet_cannot_bypass_clip_duration_or_source_mapping(tmp_path: Path) -> None:
    """BR12-03: max_seconds bounds every clip, including one large PCM record."""
    with Library(tmp_path / "library") as library:
        session = store_block(library, frames=96_000)
        _, clips = prepare_clips(library, session, max_seconds=1)
        lengths = []
        for clip in clips:
            with wave.open(str(clip.path), "rb") as audio:
                lengths.append(audio.getnframes())
        assert lengths == [48_000, 48_000], "large single record exceeded max_seconds"
        assert [clip.source_ranges[0]["source_chunk_frame_start"] for clip in clips] == [0, 48_000]
        assert [clip.source_ranges[0]["output_frame_start"] for clip in clips] == [0, 0]
        assert [clip.offset_ms for clip in clips] == [0, 1000]


@pytest.mark.parametrize("quality", ["UNKNOWN", "ARRIVAL_ONLY", "INVALID"])
def test_uncertain_clock_is_not_promoted_to_correlated_clip_time(
    tmp_path: Path, quality: str
) -> None:
    """BR12-04: an integer timestamp alone does not establish clock quality."""
    with Library(tmp_path / "library") as library:
        session = store_block(library, frames=48, quality=quality)
        _, clips = prepare_clips(library, session)
        assert clips[0].offset_ms is None and clips[0].timing_quality == "unknown"


def test_timestamp_error_flag_overrides_correlated_quality(tmp_path: Path) -> None:
    with Library(tmp_path / "library") as library:
        session = store_block(library, frames=48, flags=("TIMESTAMP_ERROR",))
        _, clips = prepare_clips(library, session)
        assert clips[0].offset_ms is None and clips[0].timing_quality == "unknown"


def test_disconnect_and_timestamp_health_remain_visible_without_replacement(tmp_path: Path) -> None:
    source = ControlledSource()
    opened: list[str] = []

    def factory(device: str, loopback: bool) -> ControlledSource:
        opened.append(device)
        return source

    with Library(tmp_path / "library") as library:
        controller = DesktopRecorder(library, factory)
        try:
            controller.start(choices("mic"))
            assert source.on_health is not None
            source.on_health({"event": "packet", "flags": ["TIMESTAMP_ERROR"]})
            source.on_health({"event": "error", "code": "DEVICE_UNAVAILABLE"})
            _, events = controller.observations()
            assert [event["code"] for event in events] == [
                "CAPTURE_PACKET_FLAGS",
                "DEVICE_UNAVAILABLE",
            ]
            assert opened == ["mic"], "disconnect silently chose a replacement source"
        finally:
            clean(controller, [source])


def application() -> Any:
    global _QT_APPLICATION
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    _QT_APPLICATION = QApplication.instance() or QApplication([])
    return _QT_APPLICATION


def wait_ui(predicate: Callable[[], bool]) -> None:
    from PySide6.QtCore import QEventLoop, QTimer

    if predicate():
        return
    loop = QEventLoop()
    timer, deadline = QTimer(), QTimer()
    timer.setInterval(1)
    timer.timeout.connect(lambda: loop.quit() if predicate() else None)
    deadline.setSingleShot(True)
    deadline.timeout.connect(loop.quit)
    deadline.start(3000)
    timer.start()
    loop.exec()
    timer.stop()
    deadline.stop()
    assert predicate(), "Qt operation did not reach its expected state"


def finish_window(window: Any) -> None:
    window.close()
    wait_ui(lambda: window._closing and not window.busy)


def test_control_task_is_nonblocking_and_delivers_completion_on_gui_thread(tmp_path: Path) -> None:
    app = application()
    from recoryn.ui.main import MainWindow

    entered, release = threading.Event(), threading.Event()
    done: list[tuple[int, int]] = []
    main_thread = threading.get_ident()
    with Library(tmp_path / "library") as library:
        window = MainWindow(
            library, recorder=DesktopRecorder(library, lambda device, loopback: ControlledSource())
        )

        def work() -> int:
            entered.set()
            assert release.wait(3)
            return threading.get_ident()

        try:
            window.operation(
                work, lambda worker_id: done.append((worker_id, threading.get_ident()))
            )
            assert entered.wait(1)
            assert window.busy
            app.processEvents()
            assert not done
            release.set()
            wait_ui(lambda: not window.busy and bool(done))
            assert done[0][0] != main_thread
            assert done[0][1] == main_thread, "Qt widgets were updated from the worker"
        finally:
            release.set()
            wait_ui(lambda: not window.busy)
            finish_window(window)


def test_normal_native_status_is_not_presented_as_capture_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BR12-05: ordinary ready/packet health must not become CAPTURE_WARNING."""
    application()
    from recoryn.capture import devices
    from recoryn.ui.main import MainWindow

    source = ControlledSource(native_health=True)
    monkeypatch.setattr(devices, "probe_device", lambda device_id, loopback=False: _FORMAT)
    with Library(tmp_path / "library") as library:
        controller = DesktopRecorder(library, lambda device, loopback: source)
        window = MainWindow(library, recorder=controller)
        try:
            window.microphone.addItem("BR12 fake", "fake")
            window.microphone.setCurrentIndex(1)
            window.start_recording()
            wait_ui(lambda: not window.busy)
            window._tick()
            assert "CAPTURE_WARNING" not in window.warning.text(), (
                "normal native packet was rendered as an error"
            )
        finally:
            wait_ui(lambda: not window.busy)
            finish_window(window)


def test_pause_resume_keeps_simulated_suspend_gap_and_epoch_source_map(tmp_path: Path) -> None:
    """Clock fixture only: this does not execute an actual OS sleep/wake."""
    with Library(tmp_path / "library") as library:
        service = RecordingService(library, {"mic": _FORMAT})
        try:
            service.start()
            first_epoch = service.epochs["mic"]
            assert service.submit(
                PCMBlock(
                    service.session_id,
                    "mic",
                    first_epoch,
                    0,
                    _FORMAT,
                    48,
                    b"\1\0" * 48,
                    1_000_000_000,
                    1_000_000_000,
                    0,
                )
            )
            service.pause()
            service.resume()
            next_epoch = service.epochs["mic"]
            assert next_epoch != first_epoch
            assert service.submit(
                PCMBlock(
                    service.session_id,
                    "mic",
                    next_epoch,
                    0,
                    _FORMAT,
                    48,
                    b"\2\0" * 48,
                    61_000_000_000,
                    61_000_000_000,
                    0,
                )
            )
            service.stop()
            _, clips = prepare_clips(library, service.session_id)
            assert [clip.offset_ms for clip in clips] == [0, 60_000]
            assert [clip.duration_ms for clip in clips] == [1, 1]
            assert {clip.epoch_id for clip in clips} == {first_epoch, next_epoch}
        finally:
            service.join_writer()


def test_capture_observation_storage_is_count_bounded(tmp_path: Path) -> None:
    source = ControlledSource()
    with Library(tmp_path / "library") as library:
        controller = DesktopRecorder(library, lambda device, loopback: source)
        try:
            controller.start(choices("mic"))
            assert source.on_health is not None
            for index in range(1000):
                source.on_health({"event": "packet", "flags": [], "sequence": index})
            _, events = controller.observations()
            assert len(events) <= 256
        finally:
            clean(controller, [source])


def test_arbitrary_uppercase_exception_text_is_not_a_trusted_ui_code() -> None:
    """BR12-06: formatting alone cannot classify exception text as a safe code."""
    application()
    from recoryn.ui.tasks import Task

    emitted: list[str] = []

    def operation() -> None:
        raise RuntimeError("BR12SECRETCANARY123")

    task = Task(operation)
    task.signals.failed.connect(emitted.append)
    task.run()
    assert emitted == ["OPERATION_FAILED_MEDIA_PRESERVED"]


def test_desktop_stop_preserves_manifest_only_failure_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BR12-07: post-finalization health projection must preserve pending success."""
    source = ControlledSource()
    with Library(tmp_path / "library") as library:
        controller = DesktopRecorder(library, lambda device, loopback: source)
        original_manifest = library.write_manifest

        def fail_projection(session_id: str) -> dict[str, Any]:
            raise OSError("BR12 manifest-only failure")

        try:
            session = controller.start(choices("mic"))
            assert source.emit()
            monkeypatch.setattr(library, "write_manifest", fail_projection)
            result = controller.stop()
            assert result["state"] == "FINALIZED" and result["manifest_sync_pending"] is True
            assert library.get_session(session).state is SessionState.FINALIZED
            assert sum(chunk.frame_count for chunk in library.chunks(session)) == 48
            assert not source.running
        finally:
            monkeypatch.setattr(library, "write_manifest", original_manifest)
            clean(controller, [source])


def test_ui_model_ack_failure_does_not_close_content_store_or_resume_polling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application()
    from recoryn.ui.main import MainWindow

    with Library(tmp_path / "library") as library:
        window = MainWindow(
            library, recorder=DesktopRecorder(library, lambda device, loopback: ControlledSource())
        )
        original_ai_close = window.ai_bridge.close
        original_model_close = window.model_panel.shutdown
        closed_ai: list[bool] = []

        def ai_close() -> None:
            closed_ai.append(True)
            original_ai_close()

        def model_pending() -> None:
            raise StateConflict("MODEL_DOWNLOAD_ACK_PENDING")

        def forbidden_tick() -> None:
            raise AssertionError("shutdown-pending window polled a partially closed service")

        monkeypatch.setattr(window.ai_bridge, "close", ai_close)
        monkeypatch.setattr(window.model_panel, "shutdown", model_pending)
        monkeypatch.setattr(window.ai_bridge, "tick", forbidden_tick)
        try:
            window.close()
            wait_ui(lambda: not window.busy)
            assert not window._closing and not closed_ai
            assert "ACK_PENDING" in window.warning.text()
            window._tick()
        finally:
            monkeypatch.setattr(window.model_panel, "shutdown", original_model_close)
            finish_window(window)
        assert closed_ai == [True]


def test_b21_recording_stop_is_independent_of_held_ai_preparation(tmp_path: Path) -> None:
    application()
    from recoryn.ui.main import MainWindow

    entered, release = threading.Event(), threading.Event()
    source = ControlledSource()
    with Library(tmp_path / "library") as library:
        recorder = DesktopRecorder(library, lambda device, loopback: source)
        window = MainWindow(library, recorder=recorder)
        window.timer.stop()
        try:
            session = recorder.start(choices("mic"))
            assert source.emit()
            window._update_controls()

            def preparation() -> None:
                entered.set()
                assert release.wait(5)
                raise RuntimeError("BR12SECRETCANARY_AFTER_CAPTURE_FINALIZED")

            assert window.ai_bridge.operation(preparation)
            assert entered.wait(2)
            assert window.ai_bridge.busy and not window.busy and window.stop_button.isEnabled()
            window.stop_recording()
            wait_ui(lambda: not window.busy)
            assert window.ai_bridge.busy and not source.running
            assert library.get_session(session).state is SessionState.FINALIZED
            originals = {chunk.relative_path: chunk.sha256 for chunk in library.chunks(session)}
            assert sum(chunk.frame_count for chunk in library.chunks(session)) == 48
            release.set()
            wait_ui(lambda: not window.ai_bridge.busy)
            assert {
                chunk.relative_path: chunk.sha256 for chunk in library.chunks(session)
            } == originals
            assert "BR12SECRETCANARY" not in window.ai_bridge.panel.job_status.text()
        finally:
            release.set()
            wait_ui(lambda: not window.ai_bridge.busy and not window.busy)
            finish_window(window)


@pytest.mark.parametrize("boundary", ["pause", "error", "stopped"])
def test_b21_meter_zeroes_when_last_track_snapshot_is_released(
    tmp_path: Path, boundary: str
) -> None:
    application()
    from recoryn.ui.main import MainWindow

    source = ControlledSource()
    with Library(tmp_path / "library") as library:
        recorder = DesktopRecorder(library, lambda device, loopback: source)
        window = MainWindow(library, recorder=recorder)
        window.timer.stop()
        try:
            recorder.start(choices("mic"))
            assert source.identity is not None and source.submit is not None
            assert source.submit(
                PCMBlock(*source.identity, 0, _FORMAT, 48, b"\x00\x40" * 48, 0, 0, 0)
            )
            window._tick()
            assert window.meters["mic"].value() == 50
            if boundary == "pause":
                recorder.pause()
            else:
                assert source.on_health is not None
                source.on_health(
                    {
                        "event": boundary,
                        **({"code": "DEVICE_UNAVAILABLE"} if boundary == "error" else {}),
                    }
                )
            window._tick()
            assert window.meters["mic"].value() == 0
        finally:
            finish_window(window)


def test_b21_power_notice_serializes_capture_ack_and_requires_new_epoch(tmp_path: Path) -> None:
    application()
    from recoryn.ui.main import MainWindow

    source = ControlledSource()
    entered, release = threading.Event(), threading.Event()
    with Library(tmp_path / "library") as library:
        recorder = DesktopRecorder(library, lambda device, loopback: source)
        window = MainWindow(library, recorder=recorder)
        window.timer.stop()
        try:
            session = recorder.start(choices("mic"))
            assert source.emit()
            assert recorder.recording is not None
            epoch = recorder.recording.epochs
            window.live_stt.setChecked(True)

            def held_control() -> None:
                entered.set()
                assert release.wait(5)

            window.operation(held_control)
            assert entered.wait(2)
            window._power_event("suspend")
            window._power_event("resume")
            assert window._pending_suspend and source.running
            assert library.get_session(session).state is SessionState.RECORDING
            assert not window.live_stt.isChecked()
            release.set()
            wait_ui(lambda: not window.busy and not window._pending_suspend)
            assert library.get_session(session).state is SessionState.PAUSED
            assert window.power.resume_required and not source.running
            original = tuple(library.chunks(session))
            for _ in range(3):
                window._power_event("resume")
            assert recorder.recording.epochs == epoch and not source.running
            window.pause_resume()
            wait_ui(lambda: not window.busy)
            assert recorder.recording.epochs != epoch and source.running
            assert tuple(library.chunks(session)) == original
        finally:
            release.set()
            wait_ui(lambda: not window.busy)
            finish_window(window)


@pytest.mark.parametrize("ack_pending", [False, True])
def test_b21_delete_keeps_pending_capture_handle_then_clears_stale_polling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ack_pending: bool
) -> None:
    application()
    from PySide6.QtWidgets import QMessageBox

    from recoryn.ui.main import MainWindow

    source = ControlledSource()
    with Library(tmp_path / "library") as library:
        recorder = DesktopRecorder(library, lambda device, loopback: source)
        window = MainWindow(library, recorder=recorder)
        window.timer.stop()
        try:
            session = recorder.start(choices("mic"))
            assert source.emit()
            window.refresh_sessions()
            window.sessions.setCurrentRow(0)
            monkeypatch.setattr(
                QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes
            )
            old = recorder.recording
            source.stop_pending = ack_pending
            window.delete_selected()
            wait_ui(lambda: not window.busy)
            if ack_pending:
                assert recorder.recording is old and source.running
                assert library.get_session(session).state is SessionState.RECORDING
                assert not window._closing and "ACK_PENDING" in window.warning.text()
                window._tick()
                source.stop_pending = False
                window.delete_selected()
                wait_ui(lambda: not window.busy)
            assert recorder.recording is None and not source.running
            assert library.list_sessions() == []
            for _ in range(3):
                window._tick()
                window._update_controls()
            assert window.record_button.isEnabled()
        finally:
            source.stop_pending = False
            wait_ui(lambda: not window.busy)
            finish_window(window)


def test_b21_incremental_stt_reuses_origin_across_gap_epochs_and_preserves_originals(
    tmp_path: Path,
) -> None:
    application()
    from recoryn.app.ai import AIService
    from recoryn.content import ContentStore
    from recoryn.providers import ProviderCapabilities, STTResult, TranscriptSegment

    class Provider:
        def __init__(self) -> None:
            self.offsets: list[int] = []

        def capabilities(self) -> ProviderCapabilities:
            return ProviderCapabilities("br12_fake", transcription=True, segment_timestamps=True)

        def transcribe(self, request: Any, context: Any = None) -> STTResult:
            self.offsets.append(request.offset_ms)
            return STTResult(
                "br12-fake",
                "no-model",
                (
                    TranscriptSegment(
                        "line",
                        request.offset_ms,
                        request.offset_ms + 100,
                        "synthetic speech result",
                    ),
                ),
                True,
            )

    with Library(tmp_path / "library") as library, ContentStore(library) as content:
        recorder = RecordingService(library, {"mic": _FORMAT})
        service = AIService(library, content)
        provider = Provider()
        try:
            recorder.start()
            for stamp in (1_000_000_000, 61_000_000_000):
                assert recorder.submit(
                    PCMBlock(
                        recorder.session_id,
                        "mic",
                        recorder.epochs["mic"],
                        0,
                        _FORMAT,
                        48000,
                        b"\x00\x40" * 48000,
                        stamp,
                        stamp,
                        0,
                    )
                )
                recorder.pause()
                job = service.transcribe(
                    recorder.session_id, provider, config_key="fixed-no-model", provisional=True
                )

                def completed(identifier: str = job) -> bool:
                    return service.jobs.get(identifier).state.value in {
                        "SUCCEEDED",
                        "FAILED",
                        "BLOCKED",
                    }

                wait_ui(completed)
                assert service.jobs.get(job).state.value == "SUCCEEDED"
                if stamp == 1_000_000_000:
                    recorder.resume()
            assert provider.offsets == [0, 60_000]
            chunks = tuple(library.chunks(recorder.session_id))
            assert len({chunk.epoch_id for chunk in chunks}) == 2
            original = tuple(chunk.sha256 for chunk in chunks)
            replay = service.transcribe(
                recorder.session_id, provider, config_key="fixed-no-model", provisional=True
            )
            assert service.jobs.get(replay).state.value == "SUCCEEDED"
            assert provider.offsets == [0, 60_000]
            selected = content.active_transcript(recorder.session_id)
            assert selected is not None and not selected["complete"] and selected["kind"] == "draft"
            assert [segment["start_ms"] for segment in selected["segments"]] == [0, 60_000]
            assert selected["coverage"]["checkpoint"]["resolved_origin_ns"] == 1_000_000_000
            assert tuple(chunk.sha256 for chunk in library.chunks(recorder.session_id)) == original
        finally:
            service.close()
            recorder.stop()
            recorder.join_writer()


def test_b21_delete_pending_reader_is_visible_as_pending_not_silent_disappearance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    application()
    from PySide6.QtWidgets import QMessageBox

    from recoryn.ui.main import MainWindow

    source = ControlledSource()
    with Library(tmp_path / "library") as library:
        recorder = DesktopRecorder(library, lambda device, loopback: source)
        window = MainWindow(library, recorder=recorder)
        window.timer.stop()
        attempt = None
        jobs = None
        try:
            session = recorder.start(choices("mic"))
            assert source.emit()
            recorder.stop()
            media = library.root / library.chunks(session)[0].relative_path / "audio.pcm"
            before = media.read_bytes()
            service = window.ai_bridge._service()
            jobs = service.jobs
            job = jobs.create("br12-pending-reader", "fixed-input")
            jobs.bind_session(job.job_id, session)
            attempt = jobs.claim(job.job_id, "br12-controlled-reader")
            jobs.reader_started(attempt)
            jobs.fail(
                job.job_id,
                attempt.attempt_id,
                attempt.fence,
                "REMOTE_OUTCOME_UNKNOWN",
                outcome_known=False,
            )
            window.refresh_sessions()
            window.sessions.setCurrentRow(0)
            monkeypatch.setattr(
                QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes
            )
            window.delete_selected()
            wait_ui(lambda: not window.busy)
            assert jobs.local_reader_active(job.job_id) is True
            assert media.read_bytes() == before and library.list_sessions() == []
            for _ in range(3):
                window._tick()
            message = window.warning.text()
            assert "삭제" in message and any(
                word in message for word in ("대기", "진행", "DELETE_PENDING")
            ), (
                "DELETE_PENDING must remain visible while original bytes are still retained: "
                + message
            )
            assert window.retry_delete_button.isEnabled()
            window.retry_delete_button.click()
            wait_ui(lambda: not window.busy)
            assert jobs.local_reader_active(job.job_id) is True
            assert media.read_bytes() == before and session in window._pending_deletions
            jobs.reader_finished(attempt)
            window.retry_delete_button.click()
            wait_ui(lambda: not window.busy)
            assert not media.exists() and not window._pending_deletions
            assert "완료" in window.deletion_status.text()
            assert not window.retry_delete_button.isEnabled()
            assert jobs.get(job.job_id).blocked_reason == "REMOTE_UNKNOWN"
            window._tick()
        finally:
            if attempt is not None and jobs is not None:
                jobs.reader_finished(attempt)
                library.delete_session(session)
            finish_window(window)
