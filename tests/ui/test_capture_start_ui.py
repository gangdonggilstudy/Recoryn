"""G07 accepted-frame display oracle with controlled fake capture callbacks."""

from __future__ import annotations

import threading
from itertools import permutations, product
from types import SimpleNamespace

import pytest

from recoryn.app.desktop import DesktopRecorder, TrackSelection
from recoryn.app.recording import RecordingError
from recoryn.app.status import CaptureProgress, capture_status
from recoryn.domain import AudioFormat, PCMBlock, SessionState

V = list(
    product(
        ("IDLE", "STARTING", "ACTIVE", "PAUSED", "STOPPING", "ENDED"),
        (False, True),
        (0, 1, 2),
        (False, True),
        (False, True),
        (False, True),
    )
)
ORDERS = list(
    product(
        permutations("DARE"),
        ("pause", "stop", "start-failure", "storage-failure", "device-failure"),
    )
)
E = list(
    product(
        (0, 48),
        ("none", "packet", "rejected", "silence"),
        ("none", "ready", "pcm"),
        ("continue", "pause", "stop"),
    )
)


@pytest.mark.parametrize("row", V, ids=[f"G07-V-{n:03}" for n in range(1, len(V) + 1)])
def test_capture_display_cube(row):
    mode, ready, frames, accepting, failed, current = row
    facts = CaptureProgress(
        "s", 1, (("mic", "e"),), mode, ready, frames, accepting, failed, current
    )
    # Exactly two true tuples, independent of the implementation's branches.
    expected = row in {
        ("ACTIVE", True, 1, True, False, True),
        ("ACTIVE", True, 2, True, False, True),
    }
    assert ("REC" in capture_status(facts)) is expected


class FakeLibrary:
    state = SessionState.CREATED

    def get_session(self, session_id):
        return SimpleNamespace(state=self.state)

    def capture_health(self, session_id):
        return {}

    def record_capture_health(self, session_id, value):
        pass


class FakeRecording:
    def __init__(self, library, formats):
        self.library, self.formats = library, formats
        self.session_id = "s"
        self.epochs = {track: "epoch-1" for track in formats}
        self.accepting, self.storage_failed, self.reject = False, False, False
        self.frames = 0

    def start(self):
        self.accepting, self.library.state = True, SessionState.RECORDING

    def submit(self, block):
        if self.reject or not self.accepting or self.storage_failed:
            self.reject = False
            return False
        self.frames += block.frame_count
        return True

    def health_snapshot(self):
        return {"accepting": self.accepting, "storage_failed": self.storage_failed}

    def pause(self):
        self.accepting, self.library.state = False, SessionState.PAUSED

    def resume(self):
        self.epochs = {track: "epoch-2" for track in self.formats}
        self.accepting, self.library.state = True, SessionState.RECORDING

    def stop(self, **kwargs):
        self.accepting, self.library.state = False, SessionState.FINALIZED
        return {"frames": self.frames}

    def join_writer(self):
        pass


class Source:
    def __init__(self, *, gated=False):
        self.ready = threading.Event()
        self.entered = threading.Event()
        if not gated:
            self.ready.set()
        self.running = False

    def start(self, session, track, epoch, submit, on_health):
        self.running = True
        self.identity = session, track, epoch
        self.submit, self.health = submit, on_health
        self.entered.set()
        assert self.ready.wait(3)
        if getattr(self, "fail_start", False):
            raise RecordingError("DEVICE_UNAVAILABLE")
        return AudioFormat(48000, 1)

    def emit(self):
        if not self.running:
            return False
        return self.submit(PCMBlock(*self.identity, 0, AudioFormat(48000, 1), 48, bytes(96), 0, 0))

    def stop(self, timeout=5):
        self.running = False
        self.ready.set()


@pytest.mark.parametrize("row", ORDERS, ids=[f"G07-O-{n:03}" for n in range(1, len(ORDERS) + 1)])
def test_ready_accept_reject_and_end_order(monkeypatch, row):
    import recoryn.app.desktop as desktop

    monkeypatch.setattr(desktop, "RecordingService", FakeRecording)
    order, ending = row
    source, library = Source(gated=True), FakeLibrary()
    controller = DesktopRecorder(library, lambda *_: source)
    choices = (TrackSelection("mic", "fake", False, AudioFormat(48000, 1)),)
    errors = []

    def start():
        try:
            controller.start(choices)
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=start)
    thread.start()
    assert source.entered.wait(3)
    accepted = 0
    ended = False
    ready = False
    try:
        for event in order:
            if event == "D":
                source.ready.set()
                thread.join(3)
                assert not thread.is_alive() and not errors
                ready = not ended
            elif event in {"A", "R"}:
                controller.recording.reject = event == "R"
                try:
                    result = source.emit()
                except RecordingError:
                    result = False
                expected = event == "A" and not ended
                assert result is expected
                accepted += 48 if expected else 0
            else:
                ended = True
                if ending == "pause":
                    controller.pause()
                elif ending == "start-failure":
                    controller.pause()
                    thread.join(3)
                    assert not thread.is_alive() and not errors
                    source.fail_start = True
                    with pytest.raises(
                        RecordingError, match="^CAPTURE_START_FAILED_MEDIA_PRESERVED$"
                    ):
                        controller.resume()
                    accepted = 0  # The failed new run must not inherit the old frames.
                elif ending == "stop":
                    controller.stop()
                elif ending == "storage-failure":
                    controller.recording.storage_failed = True
                    controller.recording.accepting = False
                else:
                    source.health({"event": "error", "code": "DEVICE_UNAVAILABLE"})
                    source.running = False
            facts = controller.capture_progress()
            assert facts.current_accepted_frames == accepted
            assert ("REC" in capture_status(facts)) is (not ended and ready and accepted > 0)
    finally:
        source.ready.set()
        thread.join(3)
        controller.close()


@pytest.mark.parametrize("row", E, ids=[f"G07-E-{n:03}" for n in range(1, len(E) + 1)])
def test_resume_uses_only_current_run_and_accepts_silence(monkeypatch, row):
    import recoryn.app.desktop as desktop

    monkeypatch.setattr(desktop, "RecordingService", FakeRecording)
    prior, offer, late, ending = row
    sources = []

    def factory(*_):
        source = Source()
        sources.append(source)
        return source

    controller = DesktopRecorder(FakeLibrary(), factory)
    choices = (TrackSelection("mic", "fake", False, AudioFormat(48000, 1)),)
    controller.start(choices)
    old = sources[0]
    if prior:
        assert old.emit()
    generation = controller.capture_progress().run_generation
    controller.pause()
    controller.resume()
    assert controller.capture_progress().run_generation == generation + 1
    if late == "ready":
        old.health({"event": "ready"})
    elif late == "pcm":
        assert (
            old.submit(PCMBlock(*old.identity, 0, AudioFormat(48000, 1), 48, bytes(96), 0, 0))
            is False
        )
    current = sources[1]
    if offer == "packet":
        current.health({"event": "packet", "flags": ["SILENT"]})
    elif offer in {"rejected", "silence"}:
        controller.recording.reject = offer == "rejected"
        assert current.emit() is (offer == "silence")
    if ending == "pause":
        controller.pause()
    elif ending == "stop":
        controller.stop()
    facts = controller.capture_progress()
    assert facts.current_accepted_frames == (48 if offer == "silence" else 0)
    assert ("REC" in capture_status(facts)) is (offer == "silence" and ending == "continue")
    controller.close()


def test_capture_census():
    assert len(V) == len(set(V)) == 288
    assert len(ORDERS) == len(set(ORDERS)) == 120
    assert len(E) == len(set(E)) == 72


def test_submit_reads_recording_epochs_without_holding_callback_lock(monkeypatch):
    import recoryn.app.desktop as desktop

    checks = []
    change_run = False

    class GatedRecording(FakeRecording):
        @property
        def epochs(self):
            assert not controller._lock.locked(), "epoch query nested the two capture locks"
            checks.append("outside")
            if change_run:
                controller._begin_run()
            return self._epochs

        @epochs.setter
        def epochs(self, value):
            self._epochs = value

    monkeypatch.setattr(desktop, "RecordingService", GatedRecording)
    source = Source()
    controller = DesktopRecorder(FakeLibrary(), lambda *_: source)
    controller.start((TrackSelection("mic", "fake", False, AudioFormat(48000, 1)),))
    try:
        assert source.emit()
        assert checks and controller.recording.frames == 48
        change_run = True  # Run changes while the independent epoch query is in flight.
        assert source.emit() is False
        assert controller.recording.frames == 48
    finally:
        change_run = False
        controller.close()


@pytest.mark.parametrize(
    "action",
    ["partial-start", "pause", "stop"],
    ids=[f"G07-FIX1-ACK-{i:02}" for i in range(1, 4)],
)
def test_actual_capture_ack_failures_keep_pending_facts(monkeypatch, action):
    import recoryn.app.desktop as desktop

    class Recording(FakeRecording):
        refuse = True

        def pause(self):
            if action == "pause" and self.refuse:
                raise RecordingError("WRITER_ACK_PENDING")
            return super().pause()

        def stop(self, **kwargs):
            if action == "stop" and self.refuse:
                raise RecordingError("WRITER_ACK_PENDING")
            return super().stop(**kwargs)

    class First(Source):
        refuse = action == "partial-start"

        def stop(self, timeout=5):
            if self.refuse:
                raise RecordingError("CAPTURE_ACK_PENDING")
            return super().stop(timeout)

    first, second = First(), Source()
    second.fail_start = True
    created = iter((first, second))
    monkeypatch.setattr(desktop, "RecordingService", Recording)
    controller = DesktopRecorder(FakeLibrary(), lambda *_: next(created))
    choices = tuple(
        TrackSelection(track, "fake", track == "system", AudioFormat(48000, 1))
        for track in (["mic", "system"] if action == "partial-start" else ["mic"])
    )
    try:
        if action == "partial-start":
            with pytest.raises(RecordingError, match="^CAPTURE_START_FAILED_ACK_PENDING$"):
                controller.start(choices)
        else:
            controller.start(choices)
            with pytest.raises(RecordingError, match="^WRITER_ACK_PENDING$"):
                getattr(controller, action)()
        facts = controller.capture_progress()
        assert facts.ack_pending and controller.library.state == SessionState.RECORDING
        assert capture_status(facts) == "종료 확인 대기 · 일부 원본 보존"
        assert "REC" not in capture_status(facts) and "일시정지" not in capture_status(facts)
    finally:
        first.refuse = False
        if controller.recording is not None:
            controller.recording.refuse = False
        controller.close()


def test_restart_storage_failure_cannot_reuse_the_prior_stopping_indicator(monkeypatch):
    import recoryn.app.desktop as desktop

    class Recording(FakeRecording):
        count = 0

        def start(self):
            type(self).count += 1
            if self.count == 2:
                raise RecordingError("START_TRANSITION_FAILED")
            super().start()

    monkeypatch.setattr(desktop, "RecordingService", Recording)
    controller = DesktopRecorder(FakeLibrary(), lambda *_: Source())
    choices = (TrackSelection("mic", "fake", False, AudioFormat(48000, 1)),)
    controller.start(choices)
    controller.stop()
    try:
        with pytest.raises(RecordingError, match="^START_TRANSITION_FAILED$"):
            controller.start(choices)
        assert controller.capture_progress().control_mode == "START_FAILED"
        text = capture_status(controller.capture_progress())
        assert "시작 실패" in text and "정지 중" not in text and "REC" not in text
    finally:
        controller.close()


@pytest.mark.parametrize(
    "action",
    ["partial-start", "pause", "stop", "power"],
    ids=[f"G07-FIX1-WINDOW-{i:02}" for i in range(1, 5)],
)
def test_control_failure_and_suspend_indicators_survive_real_window_ticks(
    tmp_path, monkeypatch, action
):
    import sys
    import types

    from PySide6.QtWidgets import QApplication

    from recoryn.storage import Library
    from recoryn.ui.main import MainWindow
    from tests.ui.test_blocked_reason_ui import _spin

    app = QApplication.instance() or QApplication([])
    devices = types.ModuleType("recoryn.capture.devices")
    devices.probe_device = lambda *args, **kwargs: AudioFormat(48000, 1)
    monkeypatch.setitem(sys.modules, "recoryn.capture.devices", devices)
    sources = []

    class Controlled(Source):
        refuse_stop = False

        def stop(self, timeout=5):
            if self.refuse_stop:
                raise RecordingError("CAPTURE_ACK_PENDING")
            super().stop(timeout)

    def factory(*_):
        source = Controlled()
        if action == "partial-start":
            source.refuse_stop = not sources
            source.fail_start = bool(sources)
        sources.append(source)
        return source

    with Library(tmp_path / "library") as library:
        controller = DesktopRecorder(library, factory)
        window = MainWindow(library, recorder=controller)
        window.timer.stop()
        restore = None
        try:
            window.microphone.addItem("synthetic", "fake")
            window.microphone.setCurrentIndex(1)
            if action == "partial-start":
                window.system.addItem("synthetic-system", "fake-system")
                window.system.setCurrentIndex(1)
            window.start_recording()
            _spin(app, lambda: not window.busy)
            if action == "power":
                window._power_event("suspend")
                _spin(app, lambda: not window.busy)
                for _ in range(3):
                    window._tick()
                    assert "절전 일시정지" in window.indicator.text()
                    assert "사용자 동작" in window.indicator.text()
                window.pause_resume()
                _spin(app, lambda: not window.busy)
                assert not window.power.resume_required
                assert "절전" not in window.indicator.text()
            else:
                if action in {"pause", "stop"}:
                    restore = action, getattr(controller.recording, action)

                    def no_writer_ack(*args, **kwargs):
                        raise RecordingError("WRITER_ACK_PENDING")

                    monkeypatch.setattr(controller.recording, action, no_writer_ack)
                    (window.pause_resume if action == "pause" else window.stop_recording)()
                    _spin(app, lambda: not window.busy)
                assert window._capture_request is None
                assert controller.capture_progress().ack_pending
                for _ in range(3):
                    window._tick()
                    assert window.indicator.text() == "종료 확인 대기 · 일부 원본 보존"
                    assert "REC" not in window.indicator.text()
        finally:
            for source in sources:
                source.refuse_stop = False
            if restore:
                setattr(controller.recording, *restore)
            window.close()
            _spin(app, lambda: window._closing)
            window.deleteLater()
            app.processEvents()


def test_manifest_pending_is_never_displayed_as_fully_synchronized():
    text = capture_status(CaptureProgress(control_mode="ENDED", manifest_sync_pending=True))
    assert "manifest 동기화 대기" in text and "저장 완료" not in text and "REC" not in text


def test_old_callback_cannot_adopt_current_epoch_or_report_a_new_failure(monkeypatch):
    import recoryn.app.desktop as desktop

    monkeypatch.setattr(desktop, "RecordingService", FakeRecording)
    sources = []

    def factory(*_):
        source = Source()
        sources.append(source)
        return source

    controller = DesktopRecorder(FakeLibrary(), factory)
    controller.start((TrackSelection("mic", "fake", False, AudioFormat(48000, 1)),))
    old = sources[0]
    controller.pause()
    controller.resume()
    current = sources[1]
    # Even a late backend using freshly observed PCM identity has its original
    # callback generation; original RecordingService validation alone is insufficient.
    assert (
        old.submit(PCMBlock(*current.identity, 0, AudioFormat(48000, 1), 48, bytes(96), 0, 0))
        is False
    )
    old.health({"event": "error", "code": "DEVICE_UNAVAILABLE"})
    facts = controller.capture_progress()
    assert facts.current_accepted_frames == 0 and not facts.failure
    assert current.emit()
    assert "REC" in capture_status(controller.capture_progress())
    controller.close()


def test_real_window_waits_for_an_accepted_frame_after_start_and_resume(tmp_path, monkeypatch):
    import sys
    import time
    import types

    from PySide6.QtWidgets import QApplication

    from recoryn.storage import Library
    from recoryn.ui.main import MainWindow

    app = QApplication.instance() or QApplication([])
    sources = []
    entered, release = threading.Event(), threading.Event()
    devices = types.ModuleType("recoryn.capture.devices")

    def probe(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return AudioFormat(48000, 1)

    devices.probe_device = probe
    monkeypatch.setitem(sys.modules, "recoryn.capture.devices", devices)

    def settle(window):
        deadline = time.monotonic() + 10
        while window.busy and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.001)
        app.processEvents()
        assert not window.busy

    def factory(*_):
        source = Source()
        sources.append(source)
        return source

    with Library(tmp_path / "library") as library:
        controller = DesktopRecorder(library, factory)
        window = MainWindow(library, recorder=controller)
        try:
            window.microphone.addItem("synthetic", "fake")
            window.microphone.setCurrentIndex(1)
            window.start_recording()
            assert entered.wait(5)
            assert controller.recording is None
            assert "시작 중" in window.indicator.text() and "REC" not in window.indicator.text()
            release.set()
            settle(window)
            assert "시작 중" in window.indicator.text() and "REC" not in window.indicator.text()
            assert "녹음 중입니다" not in window.warning.text()
            submit = controller.recording.submit
            monkeypatch.setattr(controller.recording, "submit", lambda block: False)
            assert sources[0].emit() is False
            window._show_capture_status()
            assert "REC" not in window.indicator.text()
            monkeypatch.setattr(controller.recording, "submit", submit)
            assert sources[0].emit()
            window._show_capture_status()
            assert "REC" in window.indicator.text()
            window.pause_resume()
            assert "REC" not in window.indicator.text()
            settle(window)
            window.pause_resume()
            assert "REC" not in window.indicator.text()
            settle(window)
            assert "시작 중" in window.indicator.text() and "REC" not in window.indicator.text()
            assert sources[1].emit()
            window._show_capture_status()
            assert "REC" in window.indicator.text()
            window.stop_recording()
            assert "REC" not in window.indicator.text()
            settle(window)
        finally:
            release.set()
            window.close()
            deadline = time.monotonic() + 10
            while not window._closing and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.001)
            assert window._closing
        assert sum(item.frame_count for item in library.chunks(controller.session_id)) == 96
