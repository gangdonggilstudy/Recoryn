from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path

import pytest

from recoryn.app.desktop import DesktopRecorder, TrackSelection
from recoryn.app.power import PowerCoordinator
from recoryn.domain import AudioFormat, PCMBlock, SessionState
from recoryn.storage import Library


class Source:
    def __init__(self) -> None:
        self.running = False
        self.epoch = ""

    def start(self, session, track, epoch, submit, on_health):
        self.running, self.epoch = True, epoch
        fmt = AudioFormat(48_000, 1)
        submit(PCMBlock(session, track, epoch, 0, fmt, 48, b"\0" * 96, 0, 0))
        return fmt

    def stop(self, timeout=5):
        self.running = False


def test_suspend_requires_explicit_new_epoch_resume_and_keeps_originals(tmp_path: Path) -> None:
    sources: list[Source] = []

    def factory(device, loopback):
        source = Source()
        sources.append(source)
        return source

    with Library(tmp_path / "library") as library:
        recorder = DesktopRecorder(library, factory)
        power = PowerCoordinator(recorder)
        assert not power.suspend()
        session = recorder.start((TrackSelection("mic", "fake", False, AudioFormat(48000, 1)),))
        epoch = sources[0].epoch
        assert power.suspend() and power.resume_required
        assert library.get_session(session).state is SessionState.PAUSED
        assert not sources[0].running and len(sources) == 1
        assert not power.suspend() and power.resume_required
        # Wake notifications never call resume. Only this explicit action does.
        power.resume()
        assert len(sources) == 2 and sources[1].epoch != epoch
        assert not power.resume_required
        recorder.stop()
        assert sum(chunk.frame_count for chunk in library.chunks(session)) == 96
        recorder.close()


@pytest.mark.parametrize("event,expected", [(4, "suspend"), (7, "resume"), (18, "resume")])
def test_power_filter_reads_fake_windows_message_without_blocking(
    event: int, expected: str
) -> None:
    from recoryn.ui.power import WindowsPowerFilter

    calls: list[str] = []
    adapter = WindowsPowerFilter(calls.append)
    message = wintypes.MSG()
    message.message, message.wParam = 0x218, event
    assert adapter.nativeEventFilter(b"windows_generic_MSG", ctypes.addressof(message)) == (
        False,
        0,
    )
    assert calls == [expected]
    assert adapter.nativeEventFilter(b"other-platform", 0) == (False, 0)
