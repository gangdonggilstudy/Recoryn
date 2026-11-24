"""G08 Qt presentation plus legacy prefix uncertainty; no capture device."""

import copy
import time
from itertools import product

import pytest
from PySide6.QtWidgets import QApplication

from recoryn.app.recovery import finalize_lines, recovery_view
from recoryn.app.status import track_health_lines
from recoryn.storage import Library
from recoryn.ui.main import MainWindow

pytestmark = pytest.mark.ui
U = [
    (state, tracks, path)
    for state, tracks, path in product(range(5), (1, 2), ("live", "recovery", "export"))
    if path != "export"
]
ALL_U = list(product(range(5), (1, 2), ("live", "recovery", "export")))
H = list(product(range(8), ("recovery", "finalize")))


@pytest.mark.parametrize(
    "case", (20, 21, 22, 28, 29), ids=[f"G08-FIX1-{n:02}" for n in (20, 21, 22, 28, 29)]
)
def test_reviewer_presentation_and_late_diagnostics(case, tmp_path, application, monkeypatch):
    import json
    import threading

    from recoryn.app.desktop import DesktopRecorder
    from recoryn.app.recording import RecordingService
    from recoryn.cli import _export
    from recoryn.domain import AudioFormat, SessionState

    with Library(tmp_path / "library") as library:
        if case == 22:
            library.create_session("s")
            library.transition("s", SessionState.FINALIZING, 0)
            library.finalize_session("s")
            _export(library, "s", tmp_path / "export")
            value = json.loads((tmp_path / "export/export.json").read_text())
            assert value["capture_health_details"] == {
                "available": False,
                "reason": "LEGACY_HEALTH_DETAILS_UNAVAILABLE",
            }
            return
        service = RecordingService(library, {"mic": AudioFormat(48000, 1)}, session_id="s")
        try:
            service.start()
            if case == 21:
                before = "\n".join(track_health_lines(service.health_snapshot()))
                assert "메모리 관측 누계" in before and "checkpoint: 0" in before
                service._checkpoint_health(force=True)
                after = "\n".join(track_health_lines(service.health_snapshot()))
                assert "마지막 영속 checkpoint: 1" in after
                service.stop(timeout=30)
            elif case == 20:
                service.stop(timeout=30)
                library._db.execute("UPDATE capture_health_runs SET schema_version=3")
                library._db.commit()
                result = library.finalize_unfinished("s")
                assert result["already_finalized"] and not result["finalized"]
                text = "\n".join(finalize_lines(result, [], library.capture_health("s")))
                assert "이미 확정됨" in text and "확정하지 않았습니다" not in text
                window = MainWindow(library)
                window.timer.stop()
                try:
                    monkeypatch.setattr(window, "selected_session", lambda: "s")
                    monkeypatch.setattr(window, "_finalize_allowed", lambda: True)
                    monkeypatch.setattr(window, "_confirm_finalize", lambda: True)
                    window._inventory["s"] = {
                        "state_version": library.get_session("s").state_version
                    }
                    window.finalize_selected()
                    until = time.monotonic() + 10
                    while window.busy and time.monotonic() < until:
                        application.processEvents()
                        time.sleep(0.001)
                    assert "이미 확정됨" in window.warning.text()
                finally:
                    window.close()
                    until = time.monotonic() + 10
                    while not window._closing and time.monotonic() < until:
                        application.processEvents()
                        time.sleep(0.001)
            else:
                service.pause(timeout=30)
                desktop = object.__new__(DesktopRecorder)
                desktop._lock, desktop._run_generation = threading.Lock(), 3
                desktop.recording, desktop._control_mode = service, "STOPPING"
                desktop._health, desktop._native_formats = [], {}
                desktop._ready, desktop._meters = {"mic"}, {"mic": object()}
                desktop._on_health(
                    "mic",
                    {"event": "stopped", "release_ack": False},
                    generation=3 if case == 28 else 2,
                    epoch=service.epochs["mic"],
                )
                if case == 28:
                    assert desktop._health
                    assert desktop._health[0]["code"] == "DEVICE_RELEASE_UNCONFIRMED"
                    assert desktop._meters == {}
                else:
                    assert desktop._health == [] and "mic" in desktop._meters
                service.stop(timeout=30)
        finally:
            service.join_writer()


@pytest.fixture(scope="module")
def application():
    return QApplication.instance() or QApplication([])


def display_snapshot(state, tracks):
    value = {
        "tracks": {
            t: {
                "epoch_id": "epoch",
                "state": "UNAVAILABLE" if state == 3 and t == "mic" else "OK",
                "reason": "DEVICE_LOST" if state == 3 and t == "mic" else "NONE",
                "accepted_frames": 12,
                "dropped_frames": 6 if state == 1 else 0,
                "detail_complete": state not in {1, 2, 4},
                "count_complete": state not in {1, 2, 4},
            }
            for t in ("mic", "system")[:tracks]
        },
        "has_unknown": state in {1, 2, 4},
    }
    if state == 4:
        for item in value["tracks"].values():
            item.pop("dropped_frames")
    return value


@pytest.mark.parametrize("row", U, ids=[f"G08-U-{ALL_U.index(r) + 1:02}" for r in U])
def test_health_is_shown_without_unknown_zero(row, tmp_path, application):
    state, tracks, path = row
    data = display_snapshot(state, tracks)
    with Library(tmp_path) as library:
        window = MainWindow(library)
        window.timer.stop()
        try:
            text = "\n".join(track_health_lines(data))
            window.track_health.setText(text)
            assert "트랙별 건강" in window.track_health.accessibleName()
            assert ("6 frame" in window.track_health.text()) == (state == 1)
            assert ("미상" in text) == (state != 0)
            if state == 3:
                assert "사용 불가" in text and "전체 일시정지/재개" in text
            if tracks == 2:
                assert "system: 정상" in text
            if path == "recovery":
                result = {
                    "session_id": "s",
                    "state": "INTERRUPTED",
                    "verified_chunk_ids": [],
                    "health_recovery": {
                        "status": "RECOVERED_UNCLEAN" if state in {1, 2} else "CLOSED"
                    },
                }
                lines = recovery_view(result, [], data).lines()
                assert (any("이후 미상" in line for line in lines)) == data["has_unknown"]
        finally:
            window.close()
            deadline = time.monotonic() + 10
            while not window._closing and time.monotonic() < deadline:
                application.processEvents()
                time.sleep(0.001)
            application.processEvents()
            assert window._closing


@pytest.mark.parametrize("row", H, ids=[f"G08-H-{i:02}" for i in range(1, 17)])
def test_legacy_invalid_prefix_is_never_known_zero(row):
    state, renderer = row
    from recoryn.app.recovery import _known_epochs

    values = [0, 6, None, None, True, -1, "6", 6]
    value = {"epoch_id": "epoch", "dropped_frames": values[state]}
    if state == 3:
        value.pop("dropped_frames")
    health = {"epochs": [] if state == 2 else [{"tracks": {"mic": value}}]}
    if state == 7:
        health["epochs"].append({"tracks": {"mic": {"epoch_id": "epoch", "dropped_frames": 9}}})
    before = copy.deepcopy(health)
    from types import SimpleNamespace

    chunk = SimpleNamespace(
        track_id="mic",
        epoch_id="epoch",
        chunk_id="chunk",
        frame_count=48,
        format=SimpleNamespace(sample_rate=48000),
    )
    result = {"session_id": "s", "state": "INTERRUPTED", "verified_chunk_ids": ["chunk"]}
    lines = (
        recovery_view(result, [chunk], health).lines()
        if renderer == "recovery"
        else finalize_lines({"state": "FINALIZED", "recovery": result}, [chunk], health)
    )
    assert _known_epochs(health).get(("mic", "epoch")) == (
        values[state] if state in {0, 1} else None
    )
    assert any("큐 유실 0프레임" in line for line in lines) == (state == 0)
    assert any("큐 유실 6프레임" in line for line in lines) == (state == 1)
    assert any("유실 누계 알 수 없음" in line for line in lines) == (state not in {0, 1})
    assert health == before


def test_g08_x_actual_live_window_keeps_the_other_track(tmp_path, application):
    from recoryn.app.desktop import DesktopRecorder
    from tests.integration.test_desktop_independent import ControlledSource, choices

    sources = [ControlledSource(), ControlledSource()]
    with Library(tmp_path) as library:
        recorder = DesktopRecorder(library, lambda device, loopback: sources[device == "system"])
        window = MainWindow(library, recorder=recorder)
        window.timer.stop()
        try:
            recorder.start(choices("mic", "system"))
            assert sources[0].emit() and sources[1].emit()
            sources[0].on_health({"event": "error", "code": "DEVICE_DISCONNECTED"})
            assert sources[1].emit(sequence=1)
            window._tick()
            assert "mic: 사용 불가" in window.track_health.text()
            assert "system: 정상" in window.track_health.text()
            assert "수락 96 frame" in window.track_health.text()
            assert "REC" not in window.indicator.text()
            recorder.stop()
            assert (
                sum(
                    c.frame_count
                    for c in library.chunks(recorder.session_id)
                    if c.track_id == "system"
                )
                == 96
            )
        finally:
            window.close()
            until = time.monotonic() + 10
            while not window._closing and time.monotonic() < until:
                application.processEvents()
                time.sleep(0.001)
            assert window._closing


def test_g08_x_detail_query_is_worker_owned_and_stale_result_is_ignored(
    tmp_path, application, monkeypatch
):
    import threading

    from PySide6.QtCore import QThread

    from tests.unit.test_track_health import seed

    with Library(tmp_path) as library:
        seed(library)
        library.create_session("other")
        window = MainWindow(library)
        window.timer.stop()
        entered, release = threading.Event(), threading.Event()
        original = library.capture_health_details
        threads = []

        def held(*args, **kwargs):
            threads.append(QThread.currentThread() == application.thread())
            entered.set()
            assert release.wait(5)
            return original(*args, **kwargs)

        monkeypatch.setattr(library, "capture_health_details", held)
        try:
            until = time.monotonic() + 10
            while window._inventory_loading and time.monotonic() < until:
                application.processEvents()
                time.sleep(0.001)
            items = {
                window.sessions.item(n).data(256): window.sessions.item(n)
                for n in range(window.sessions.count())
            }
            window.sessions.setCurrentItem(items["s"])
            window.show_track_health_details()
            assert entered.wait(2)
            assert "확인 중" in window.details.toPlainText()
            generation = window._health_query_generation
            window._session_selected()  # same-ID inventory notification is idempotent
            assert window._health_query_generation == generation
            window.sessions.setCurrentItem(items["other"])
            selected_text = window.details.toPlainText()
            release.set()
            until = time.monotonic() + 5
            while window.busy and time.monotonic() < until:
                application.processEvents()
                time.sleep(0.001)
            assert not window.busy and threads == [False]
            assert window.details.toPlainText() == selected_text
        finally:
            release.set()
            window.close()
            until = time.monotonic() + 10
            while not window._closing and time.monotonic() < until:
                application.processEvents()
                time.sleep(0.001)
            assert window._closing
