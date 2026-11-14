from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from recoryn.app.desktop import DesktopRecorder, TrackSelection
from recoryn.app.recording import RecordingError
from recoryn.domain import AudioFormat, PCMBlock, SessionState, StateConflict
from recoryn.storage import Library


class FakeSource:
    running = False
    fail_stop = False
    fail_start = False

    def start(self, session_id, track_id, epoch_id, submit, on_health):
        self.running = True
        if self.fail_start:
            raise RuntimeError("private device details")
        self.submit = submit
        self.on_health = on_health
        self.identity = (session_id, track_id, epoch_id)
        self.emit()
        return AudioFormat(48000, 1)

    def emit(self):
        session, track, epoch = self.identity
        self.submit(PCMBlock(session, track, epoch, 0, AudioFormat(48000, 1), 48, b"\0" * 96, 0, 0))

    def stop(self, timeout=5.0):
        if self.fail_stop:
            raise TimeoutError("device did not acknowledge")
        self.running = False


def selection() -> tuple[TrackSelection, ...]:
    return (TrackSelection("mic", "fake", False, AudioFormat(48000, 1)),)


def test_pause_resume_stop_new_epoch_and_original_preservation(tmp_path: Path) -> None:
    sources: list[FakeSource] = []

    def factory(device: str, loopback: bool) -> Any:
        source = FakeSource()
        sources.append(source)
        return source

    with Library(tmp_path / "library") as library:
        controller = DesktopRecorder(library, factory)
        session = controller.start(selection())
        first_epoch = sources[0].identity[2]
        controller.pause()
        assert library.get_session(session).state == SessionState.PAUSED
        controller.resume()
        assert sources[1].identity[2] != first_epoch
        controller.stop()
        assert library.get_session(session).state == SessionState.FINALIZED
        assert sum(item.frame_count for item in library.chunks(session)) == 96
        controller.close()


def test_stop_timeout_never_acknowledges_paused(tmp_path: Path) -> None:
    source = FakeSource()
    with Library(tmp_path / "library") as library:
        controller = DesktopRecorder(library, lambda device, loopback: source)
        session = controller.start(selection())
        source.fail_stop = True
        with pytest.raises(RecordingError, match="ACK_PENDING"):
            controller.pause()
        assert library.get_session(session).state == SessionState.RECORDING
        source.fail_stop = False
        controller.close()


def test_failed_start_preserves_partial_audio_and_safe_health(tmp_path: Path) -> None:
    first, second = FakeSource(), FakeSource()
    second.fail_start = True

    def factory(device: str, loopback: bool) -> Any:
        return first if device == "first" else second

    with Library(tmp_path / "library") as library:
        controller = DesktopRecorder(library, factory)
        choices = (
            TrackSelection("mic", "first", False, AudioFormat(48000, 1)),
            TrackSelection("system", "second", True, AudioFormat(48000, 1)),
        )
        with pytest.raises(RecordingError, match="MEDIA_PRESERVED"):
            controller.start(choices)
        assert not first.running and not second.running
        assert controller.session_id is not None
        assert library.get_session(controller.session_id).state == SessionState.PAUSED
        assert sum(item.frame_count for item in library.chunks(controller.session_id)) == 48
        controller.close()


def test_empty_and_duplicate_track_rejected(tmp_path: Path) -> None:
    with Library(tmp_path / "library") as library:
        controller = DesktopRecorder(library, lambda device, loopback: FakeSource())
        with pytest.raises(StateConflict):
            controller.start(())
        with pytest.raises(StateConflict):
            controller.start(selection() + selection())
        with pytest.raises(StateConflict):
            controller.pause()
        with pytest.raises(StateConflict):
            controller.resume()
        with pytest.raises(StateConflict):
            controller.stop()


def test_native_ready_metadata_survives_pause_finalization_and_idle_meter(tmp_path: Path) -> None:
    source = FakeSource()
    with Library(tmp_path / "library") as library:
        controller = DesktopRecorder(library, lambda device, loopback: source)
        session = controller.start(selection())
        source.on_health(
            {
                "event": "ready",
                "format": AudioFormat(48000, 1).to_dict(),
                "valid_bits": 16,
                "container_bits": 16,
                "channel_mask": 4,
            }
        )
        assert controller.observations()[0]
        controller.pause()
        assert controller.observations()[0] == {}
        native = library.capture_health(session)["native_formats"]["mic"]
        assert native["valid_bits"] == 16 and native["channel_mask"] == 4
        controller.stop()
        assert library.capture_health(session)["native_formats"]["mic"] == native
        controller.close()
