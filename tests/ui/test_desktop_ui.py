from __future__ import annotations

import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from recoryn.app.desktop import DesktopRecorder
from recoryn.domain import AudioFormat, PCMBlock, SessionState
from recoryn.storage import Library
from recoryn.ui.main import MainWindow
from recoryn.ui.meter import peak_percent

pytestmark = pytest.mark.ui


@pytest.fixture(scope="module")
def application():
    return QApplication.instance() or QApplication([])


def settle(window: MainWindow, application: QApplication) -> None:
    deadline = time.monotonic() + 5
    while window.busy and time.monotonic() < deadline:
        application.processEvents()
        time.sleep(0.001)
    application.processEvents()
    assert not window.busy


def test_ui_has_no_implicit_device_start_and_keyboard_actions(application, tmp_path: Path) -> None:
    def forbidden(device, loopback):
        pytest.fail("device opened without explicit Record")

    with Library(tmp_path / "library") as library:
        window = MainWindow(library, recorder=DesktopRecorder(library, forbidden))
        window.show()
        application.processEvents()
        assert library.list_sessions() == []
        assert "로컬" in window.indicator.text()
        assert not window.live_stt.isHidden() and not window.live_stt.isChecked()
        assert window.microphone.accessibleName()
        assert window.meters["mic"].accessibleName()
        shortcuts = {action.shortcut().toString() for action in window.actions()}
        assert {"Ctrl+R", "Ctrl+."} <= shortcuts
        window.start_recording()
        assert "선택" in window.warning.text()
        assert library.list_sessions() == []
        window.close()
        settle(window, application)
        window.close()


def test_worker_exception_is_redacted_and_controls_recover(application, tmp_path: Path) -> None:
    with Library(tmp_path / "library") as library:
        window = MainWindow(library)

        def fail():
            raise RuntimeError("Authorization: Bearer sk-secret-canary")

        window.operation(fail)
        settle(window, application)
        assert "secret" not in window.warning.text()
        assert "OPERATION_FAILED_MEDIA_PRESERVED" in window.warning.text()
        assert window.record_button.isEnabled()
        window.close()
        settle(window, application)


def test_end_to_end_record_pause_resume_stop_ui(application, monkeypatch, tmp_path: Path) -> None:
    class Source:
        running = False

        def start(self, session, track, epoch, submit, on_health):
            self.running = True
            submit(
                PCMBlock(
                    session, track, epoch, 0, AudioFormat(48000, 1), 48, b"\x00\x40" * 48, 0, 0
                )
            )
            return AudioFormat(48000, 1)

        def stop(self, timeout=5.0):
            self.running = False

    import sys
    import types

    devices = types.ModuleType("recoryn.capture.devices")
    devices.probe_device = lambda device, loopback=False: AudioFormat(48000, 1)
    monkeypatch.setitem(sys.modules, "recoryn.capture.devices", devices)
    with Library(tmp_path / "library") as library:
        recorder = DesktopRecorder(library, lambda device, loopback: Source())
        window = MainWindow(library, recorder=recorder)
        window.microphone.addItem("fake mic", "fake-id")
        window.microphone.setCurrentIndex(1)
        window.start_recording()
        settle(window, application)
        assert "REC" in window.indicator.text()
        assert not window.record_button.isEnabled()
        assert recorder.session_id is not None
        window._tick()
        assert window.meters["mic"].value() == 50
        window.pause_resume()
        settle(window, application)
        assert library.get_session(recorder.session_id).state == SessionState.PAUSED
        window.pause_resume()
        settle(window, application)
        window.stop_recording()
        settle(window, application)
        assert library.get_session(recorder.session_id).state == SessionState.FINALIZED
        assert sum(c.frame_count for c in library.chunks(recorder.session_id)) == 96
        window.close()
        settle(window, application)


@pytest.mark.parametrize(
    "sample_type,payload,expected",
    [
        ("s16le", b"\x00\x80", 100),
        ("s24le", b"\x00\x00\x40", 50),
        ("s32le", b"\x00\x00\x00\x20", 25),
        ("f32le", b"\x00\x00\x00\x3f", 50),
        ("f32le", b"\x00\x00\xc0\x7f", 0),
    ],
)
def test_meter_real_pcm_values(sample_type: str, payload: bytes, expected: int) -> None:
    block = PCMBlock("s", "mic", "e", 0, AudioFormat(48000, 1, sample_type), 1, payload, 0, 0)
    assert peak_percent(block) == expected
