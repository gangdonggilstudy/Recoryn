"""G04 recovery UI (F-RECUI01): detection, structured review, finalize control and dialog.

Offscreen Qt with real SQLite in temporary folders; no device is opened. Expected values
are literal tables from docs/testing/g04-unfinished-session-cases.md section 4.2 and 3.4.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog

from recoryn.app.desktop import DesktopRecorder
from recoryn.app.recording import RecordingError, RecordingService
from recoryn.content import ContentStore, Segment
from recoryn.domain import AudioFormat, PCMBlock, SessionState
from recoryn.storage import ChunkWriter, Library
from recoryn.ui.main import MainWindow

pytestmark = pytest.mark.ui

FMT = AudioFormat(48000, 1)
DEFAULT_WARNING = "녹음 전 참여자 동의와 적용 규정을 확인하세요. 외부 전송은 기본 차단됩니다."


@pytest.fixture(scope="module")
def application() -> QApplication:
    return QApplication.instance() or QApplication([])


def settle(window: MainWindow, application: QApplication) -> None:
    deadline = time.monotonic() + 10
    while (
        not window._closing
        and (window.busy or window._inventory_loading)
        and time.monotonic() < deadline
    ):
        application.processEvents()
        time.sleep(0.001)
    application.processEvents()
    assert not window.busy
    assert window._closing or not window._inventory_loading


def forbidden(device: str, loopback: bool) -> Any:
    pytest.fail("no device may be opened by recovery UI tests")


def block(session: str, epoch: str, index: int) -> PCMBlock:
    return PCMBlock(
        session,
        "mic",
        epoch,
        index,
        FMT,
        4,
        bytes([10 + index]) * 8,
        1000 + index * 83333,
        1000 + index * 83333,
        device_frame_position=index * 4,
    )


def sealed(root: Path, session: str, epoch: str, indexes: range) -> Any:
    writer = ChunkWriter(root, block(session, epoch, indexes[0]))
    for index in indexes:
        writer.append(block(session, epoch, index))
    return writer.seal()


def stale(library: Library, session: str, *targets: SessionState) -> None:
    library.create_session(session)
    version = 0
    for target in targets:
        library.transition(session, target, version)
        version += 1
        if target == SessionState.RECORDING:
            library.register_chunk(sealed(library.root, session, "e1", range(2)))


def current(library: Library, kind: str, monkeypatch: pytest.MonkeyPatch) -> DesktopRecorder:
    recorder = DesktopRecorder(library, forbidden)
    if kind == "NONE":
        return recorder
    frames = 1 if kind == "INTERRUPTED" else 96_000
    service = RecordingService(library, {"mic": FMT}, session_id="s", chunk_frames=frames)
    recorder.recording = service
    service.start()
    if kind == "PAUSED":
        assert service.submit(block("s", service.epochs["mic"], 0))
        service.pause()
    elif kind == "INTERRUPTED":

        def fail_seal(writer: ChunkWriter) -> None:
            raise OSError("G04 injected seal failure")

        with monkeypatch.context() as patch:
            patch.setattr(ChunkWriter, "seal", fail_seal)
            assert service.submit(block("s", service.epochs["mic"], 0))
            with pytest.raises(RecordingError, match="STORAGE_FAILED"):
                service.stop()
    return recorder


def select(window: MainWindow, session_id: str) -> None:
    for row in range(window.sessions.count()):
        item = window.sessions.item(row)
        if item.data(Qt.ItemDataRole.UserRole) == session_id:
            window.sessions.setCurrentItem(item)
            return
    raise AssertionError(f"{session_id} is not listed")


def test_f3_refresh_uses_one_observational_inventory(
    application: QApplication,
    library: Library,
    opened: Callable[..., MainWindow],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stale(library, "old", SessionState.RECORDING, SessionState.INTERRUPTED)
    recorder = DesktopRecorder(library, source_factory=forbidden)
    window = opened(library, recorder)
    original = library._inventory
    calls: list[None] = []

    def counted() -> Any:
        calls.append(None)
        return original()

    monkeypatch.setattr(library, "_inventory", counted)
    window.refresh_sessions()
    settle(window, application)
    assert len(calls) == 1
    assert "조회 시점의 관찰" in window.recovery_status.text()
    select(window, "old")
    assert window.finalize_button.isEnabled()


def close(window: MainWindow, application: QApplication) -> None:
    window.close()
    settle(window, application)
    window.close()


def pump(application: QApplication, predicate: Callable[[], bool], timeout: float = 5) -> None:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        application.processEvents()
        time.sleep(0.001)
    application.processEvents()
    assert predicate()


def test_f4_inventory_runs_off_gui_and_returns_immediately(
    application: QApplication,
    library: Library,
    opened: Callable[..., MainWindow],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stale(library, "s", SessionState.RECORDING, SessionState.INTERRUPTED)
    window = opened(library, DesktopRecorder(library, forbidden))
    original = library.unfinished_inventory
    gui = threading.get_ident()
    entered, release = threading.Event(), threading.Event()
    threads = []

    def inspect() -> Any:
        threads.append(threading.get_ident())
        assert threads[-1] != gui, "folder inspection ran on the GUI thread"
        entered.set()
        assert release.wait(5)
        return original()

    monkeypatch.setattr(library, "unfinished_inventory", inspect)
    try:
        started = time.perf_counter()
        window.refresh_sessions()
        assert time.perf_counter() - started < 0.1
        assert "확인 중" in window.recovery_status.text() and not window.busy
        pulse = []
        QTimer.singleShot(0, lambda: pulse.append(True))
        pump(application, lambda: entered.is_set() and bool(pulse))
        assert not window.finalize_button.isEnabled()
    finally:
        release.set()
        settle(window, application)
    assert threads and all(thread != gui for thread in threads)


def test_f4_older_result_cannot_replace_newer_request(
    application: QApplication,
    library: Library,
    opened: Callable[..., MainWindow],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stale(library, "s", SessionState.RECORDING, SessionState.INTERRUPTED)
    window = opened(library, DesktopRecorder(library, forbidden))
    original = library.unfinished_inventory
    entered = [threading.Event(), threading.Event()]
    release = [threading.Event(), threading.Event()]
    calls = []

    def inspect() -> Any:
        index = len(calls)
        calls.append(index)
        result, warnings = original()
        result = [dict(item, staging_entries=100 + index) for item in result]
        entered[index].set()
        assert release[index].wait(5)
        return result, warnings

    monkeypatch.setattr(library, "unfinished_inventory", inspect)
    try:
        window.refresh_sessions()
        pump(application, entered[0].is_set)
        window.refresh_sessions()
        release[0].set()
        pump(application, entered[1].is_set)
        assert window._inventory["s"]["staging_entries"] != 100
        assert "확인 중" in window.recovery_status.text()
        release[1].set()
        settle(window, application)
        assert window._inventory["s"]["staging_entries"] == 101
    finally:
        for event in release:
            event.set()
        settle(window, application)


def test_f4_refresh_burst_is_coalesced_to_latest(
    application: QApplication,
    library: Library,
    opened: Callable[..., MainWindow],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = opened(library, DesktopRecorder(library, forbidden))
    original = library.unfinished_inventory
    entered, release = threading.Event(), threading.Event()
    calls = []

    def inspect() -> Any:
        calls.append(None)
        if len(calls) == 1:
            entered.set()
            assert release.wait(5)
        return original()

    monkeypatch.setattr(library, "unfinished_inventory", inspect)
    try:
        window.refresh_sessions()
        pump(application, entered.is_set)
        for _ in range(20):
            window.refresh_sessions()
        assert len(calls) == 1
    finally:
        release.set()
        settle(window, application)
    assert len(calls) == 2


def test_f4_inventory_failure_is_unavailable_and_retryable(
    application: QApplication,
    library: Library,
    opened: Callable[..., MainWindow],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stale(library, "s", SessionState.RECORDING, SessionState.INTERRUPTED)
    window = opened(library, DesktopRecorder(library, forbidden))
    select(window, "s")
    original = library.unfinished_inventory

    def fail() -> Any:
        raise OSError("PRIVATE-INVENTORY-CANARY")

    monkeypatch.setattr(library, "unfinished_inventory", fail)
    window.refresh_sessions()
    settle(window, application)
    assert "확인하지 못했습니다" in window.recovery_status.text()
    assert (
        "0건" not in window.recovery_status.text()
        and "PRIVATE" not in window.recovery_status.text()
    )
    assert not window.finalize_button.isEnabled()
    monkeypatch.setattr(library, "unfinished_inventory", original)
    window.refresh_sessions()
    settle(window, application)
    assert window.finalize_button.isEnabled()


def test_f4_close_ack_waits_for_inventory_reader(
    application: QApplication,
    library: Library,
    opened: Callable[..., MainWindow],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = opened(library, DesktopRecorder(library, forbidden))
    original = library.unfinished_inventory
    entered, release = threading.Event(), threading.Event()
    reader_done, wait_entered, after_wait = threading.Event(), threading.Event(), threading.Event()
    original_wait = window._inventory_pool.waitForDone
    original_shutdown = window.model_panel.shutdown

    def inspect() -> Any:
        entered.set()
        assert release.wait(5)
        assert library._connection is not None
        try:
            return original()
        finally:
            reader_done.set()

    def wait_for_reader(*args: Any) -> Any:
        assert threading.get_ident() != gui_thread
        wait_entered.set()
        return original_wait(*args)

    def next_shutdown_stage() -> None:
        after_wait.set()
        assert reader_done.is_set(), "shutdown passed the reader fence before its ACK"
        original_shutdown()

    gui_thread = threading.get_ident()
    monkeypatch.setattr(library, "unfinished_inventory", inspect)
    monkeypatch.setattr(window._inventory_pool, "waitForDone", wait_for_reader)
    monkeypatch.setattr(window.model_panel, "shutdown", next_shutdown_stage)
    try:
        window.refresh_sessions()
        pump(application, entered.is_set)
        window.close()
        pulse = []
        QTimer.singleShot(0, lambda: pulse.append(True))
        pump(application, lambda: bool(pulse) and (wait_entered.is_set() or after_wait.is_set()))
        assert wait_entered.is_set() and not after_wait.is_set()
        assert window.busy and not window._closing
        assert library._connection is not None
    finally:
        release.set()
        original_wait()

        def closed_or_retry() -> bool:
            if not window.busy and not window._closing:
                window.close()
            return window._closing

        pump(application, closed_or_retry)


def test_f4_stop_control_does_not_wait_behind_inventory(
    application: QApplication,
    library: Library,
    opened: Callable[..., MainWindow],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = current(library, "RECORDING", monkeypatch)
    window = opened(library, recorder)
    original = library.unfinished_inventory
    entered, release = threading.Event(), threading.Event()

    def inspect() -> Any:
        entered.set()
        assert release.wait(5)
        return original()

    monkeypatch.setattr(library, "unfinished_inventory", inspect)
    try:
        window.refresh_sessions()
        pump(application, entered.is_set)
        assert window.stop_button.isEnabled()
        window.stop_recording()
        pump(application, lambda: library.get_session("s").state == SessionState.FINALIZED)
        assert not release.is_set()
    finally:
        release.set()
        settle(window, application)


@pytest.fixture
def library(tmp_path: Path) -> Iterator[Library]:
    with Library(tmp_path / "library") as opened_library:
        yield opened_library


@pytest.fixture
def opened(
    application: QApplication, library: Library
) -> Iterator[Callable[[Library, DesktopRecorder], MainWindow]]:
    """Windows close (and acknowledge their recorder) before the library fixture closes."""
    windows: list[MainWindow] = []

    def open_window(target: Library, recorder: DesktopRecorder) -> MainWindow:
        window = MainWindow(target, recorder=recorder)
        window.timer.stop()
        windows.append(window)
        settle(window, application)
        return window

    yield open_window
    for window in windows:
        close(window, application)


def test_u1_startup_detects_unfinished_sessions_without_changing_them(
    application: QApplication,
    library: Library,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    opened: Callable[[Library, DesktopRecorder], MainWindow],
) -> None:
    """G04-U1-startup-detection"""
    stale(library, "a", SessionState.RECORDING, SessionState.INTERRUPTED)
    stale(library, "b", SessionState.RECORDING, SessionState.PAUSED)
    stale(library, "c", SessionState.FINALIZING)
    library.finalize_session("c")
    sealed(library.root, "d", "e1", range(1))  # a folder without a catalog row
    recorder = current(library, "RECORDING", monkeypatch)  # the live session "s"
    before = [(item.session_id, item.state, item.state_version) for item in library.list_sessions()]
    window = opened(library, recorder)
    assert not window.busy  # detection never starts an operation
    assert "확정되지 않은 세션 3건" in window.recovery_status.text()
    assert window.recovery_status.accessibleName() == "미확정 세션 안내"
    assert window.warning.text() == DEFAULT_WARNING
    labels = [window.sessions.item(row).text() for row in range(window.sessions.count())]
    assert labels[0].startswith("INTERRUPTED · 미확정")
    assert any(label.startswith("RECORDING  ") for label in labels)  # live: not marked
    assert labels[-1].startswith("폴더만 있음 · 복구 필요")
    after = [(item.session_id, item.state, item.state_version) for item in library.list_sessions()]
    assert after == before


def test_u2_recovery_review_is_structured_not_a_dict(
    application: QApplication,
    library: Library,
    tmp_path: Path,
    opened: Callable[[Library, DesktopRecorder], MainWindow],
) -> None:
    """G04-U2-structured-review"""
    stale(library, "s", SessionState.RECORDING)
    writer = ChunkWriter(library.root, block("s", "e1", 2))
    writer.append(block("s", "e1", 2))
    staging = writer.staging_path
    writer.abort()
    with (staging / "audio.pcm").open("ab") as stream:
        stream.write(b"tail")  # four unjournaled bytes
    bad = library.root / "sessions" / "s" / "tracks" / "mic" / "e1" / "badbundle"
    bad.mkdir(parents=True)
    (bad / "descriptor.json").write_text("{}", encoding="utf-8")
    window = opened(library, DesktopRecorder(library, forbidden))
    select(window, "s")
    window.recover_selected()
    settle(window, application)
    text = window.details.toPlainText()
    assert "상태: 녹음 중(RECORDING) → 중단됨(INTERRUPTED)" in text
    assert "넣지 않은 끝부분 4바이트" in text
    assert "검증할 수 없는 항목을 제자리에 보존했습니다 [bundle badbundle]" in text
    assert "유실 누계 알 수 없음" in text
    assert "다음 행동: 복구 검토 / 세션 확정 / 세션 삭제" in text
    assert text.rstrip().endswith("중단·누락 구간은 복원되지 않습니다.")
    assert "{" not in text and "'adopted'" not in text
    assert "복구 결과를 확인하세요" in window.warning.text()


ENABLED = [
    pytest.param("CREATED", "NONE", True, id="G04-U3-other-CREATED"),
    pytest.param("RECORDING", "NONE", True, id="G04-U3-other-RECORDING-stale"),
    pytest.param("PAUSED", "NONE", True, id="G04-U3-other-PAUSED-stale"),
    pytest.param("FINALIZING", "NONE", True, id="G04-U3-other-FINALIZING"),
    pytest.param("INTERRUPTED", "NONE", True, id="G04-U3-other-INTERRUPTED"),
    pytest.param("FINALIZED", "NONE", False, id="G04-U3-other-FINALIZED"),
    pytest.param("DIRECTORY_ONLY", "NONE", True, id="G04-U3-other-DIRECTORY_ONLY"),
    pytest.param(None, "RECORDING", False, id="G04-U3-current-RECORDING-live"),
    pytest.param(None, "PAUSED", False, id="G04-U3-current-PAUSED"),
    pytest.param(None, "INTERRUPTED", True, id="G04-U3-current-INTERRUPTED"),
]
_PATHS = {
    "CREATED": (),
    "RECORDING": (SessionState.RECORDING,),
    "PAUSED": (SessionState.RECORDING, SessionState.PAUSED),
    "FINALIZING": (SessionState.RECORDING, SessionState.FINALIZING),
    "INTERRUPTED": (SessionState.RECORDING, SessionState.INTERRUPTED),
}


@pytest.mark.parametrize(("state", "recorder_kind", "enabled"), ENABLED)
def test_u3_finalize_button_enable_matrix(
    application: QApplication,
    library: Library,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    opened: Callable[[Library, DesktopRecorder], MainWindow],
    state: str | None,
    recorder_kind: str,
    enabled: bool,
) -> None:
    if state == "FINALIZED":
        stale(library, "s", SessionState.RECORDING, SessionState.FINALIZING)
        library.finalize_session("s")
    elif state == "DIRECTORY_ONLY":
        sealed(library.root, "s", "e1", range(1))
    elif state is not None:
        stale(library, "s", *_PATHS[state])
    window = opened(library, current(library, recorder_kind, monkeypatch))
    select(window, "s")
    assert window.finalize_button.isEnabled() is enabled
    assert window.finalize_button.accessibleName() == "선택한 미확정 세션을 확정"


DIALOG = [
    pytest.param("Return", id="G04-U4-default-is-no"),
    pytest.param("Escape", id="G04-U4-escape-is-no"),
]


@pytest.mark.parametrize("key", DIALOG)
def test_u4_confirmation_never_defaults_or_escapes_to_finalize(
    application: QApplication,
    library: Library,
    tmp_path: Path,
    opened: Callable[[Library, DesktopRecorder], MainWindow],
    key: str,
) -> None:
    stale(library, "s", SessionState.RECORDING, SessionState.INTERRUPTED)
    window = opened(library, DesktopRecorder(library, forbidden))
    box = window._finalize_dialog()
    assert box.defaultButton() is box.escapeButton()
    assert box.escapeButton().text() == "아니요"
    box.show()
    application.processEvents()
    QTest.keyClick(box, getattr(Qt.Key, "Key_" + key))
    application.processEvents()
    assert box.clickedButton() is box.escapeButton()
    select(window, "s")
    window._confirm_finalize = lambda: False  # type: ignore[method-assign]
    window.finalize_selected()
    settle(window, application)
    assert library.get_session("s").state is SessionState.INTERRUPTED


def test_u5_finalize_then_export_from_the_list(
    application: QApplication,
    library: Library,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    opened: Callable[[Library, DesktopRecorder], MainWindow],
) -> None:
    """G04-U5-finalize-then-export"""
    stale(library, "s", SessionState.RECORDING, SessionState.INTERRUPTED)
    window = opened(library, DesktopRecorder(library, forbidden))
    select(window, "s")
    window._confirm_finalize = lambda: True  # type: ignore[method-assign]
    window.finalize_selected()
    settle(window, application)
    assert library.get_session("s").state is SessionState.FINALIZED
    assert "세션을 확정했습니다" in window.details.toPlainText()
    assert "다음 행동: 내보내기 / 전사 요청 / 세션 삭제" in window.details.toPlainText()
    assert "세션을 확정했습니다" in window.warning.text()
    select(window, "s")
    assert not window.finalize_button.isEnabled()
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *args: str(tmp_path / "exports")
    )
    (tmp_path / "exports").mkdir()
    window.export_selected()
    settle(window, application)
    assert window.warning.text().startswith("오디오 내보내기 완료")
    assert list((tmp_path / "exports").glob("*/export.json"))


def test_u6_directory_only_entry_is_listed_and_recoverable(
    application: QApplication,
    library: Library,
    tmp_path: Path,
    opened: Callable[[Library, DesktopRecorder], MainWindow],
) -> None:
    """G04-U6-directory-only"""
    sealed(library.root, "s", "e1", range(2))
    window = opened(library, DesktopRecorder(library, forbidden))
    select(window, "s")
    text = window.details.toPlainText()
    assert "폴더만 있음(DIRECTORY_ONLY)" in text and "목록 밖 저장 묶음 1개" in text
    assert "삭제는 복구 뒤에" in text
    assert library.list_sessions() == []  # selecting never creates a row
    assert window.finalize_button.isEnabled()
    window.recover_selected()
    settle(window, application)
    assert library.get_session("s").state is SessionState.CREATED
    assert "상태: 폴더만 있음(DIRECTORY_ONLY) → 생성됨(CREATED)" in window.details.toPlainText()


def test_u7_live_recording_refuses_recovery_review(
    application: QApplication,
    library: Library,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    opened: Callable[[Library, DesktopRecorder], MainWindow],
) -> None:
    """G04-U7-live-recovery-refused (the UI path of G04-CE1)"""
    recorder = current(library, "RECORDING", monkeypatch)
    window = opened(library, recorder)
    select(window, "s")
    window.recover_selected()
    settle(window, application)
    assert window.warning.text() == "녹음 중인 세션은 정지 후 복구하거나 확정할 수 있습니다."
    assert library.get_session("s").state is SessionState.RECORDING
    assert recorder.recording is not None
    assert recorder.recording.submit(block("s", recorder.recording.epochs["mic"], 0))


def test_declared_ui_denominators_are_complete_and_unique() -> None:
    ids = [
        "G04-U1-startup-detection",
        "G04-U2-structured-review",
        *(case.id for case in ENABLED),
        *(case.id for case in DIALOG),
        "G04-U5-finalize-then-export",
        "G04-U6-directory-only",
        "G04-U7-live-recovery-refused",
    ]
    assert len(ids) == len(set(ids)) == 17


@pytest.mark.parametrize(
    "damage", ("missing", "corrupt"), ids=[f"G04-FIX-UI-MEDIA-{i}" for i in range(2)]
)
def test_recovery_ui_never_calls_missing_or_corrupt_catalog_audio_preserved(
    application: QApplication,
    library: Library,
    opened: Callable[[Library, DesktopRecorder], MainWindow],
    damage: str,
) -> None:
    library.create_session("s")
    descriptor = sealed(library.root, "s", "e1", range(2))
    library.register_chunk(descriptor)
    audio = library.root / descriptor.relative_path / "audio.pcm"
    if damage == "missing":
        audio.unlink()
    else:
        audio.write_bytes(b"broken")
    window = opened(library, DesktopRecorder(library, forbidden))
    select(window, "s")
    window.recover_selected()
    settle(window, application)
    text = window.details.toPlainText()
    assert "목록상 예상 원본: 청크 1개 · 8프레임" in text
    assert "확인된 청크 없음" in text
    assert "파일이 없거나 손상된 청크" in text
    assert "원본은 보존" not in text


@pytest.mark.parametrize("edited", (False, True), ids=[f"G04-FIX-UI-SELECT-{i}" for i in range(2)])
def test_directory_only_disables_previous_edits_then_loads_another_normal_session(
    application: QApplication,
    library: Library,
    opened: Callable[[Library, DesktopRecorder], MainWindow],
    monkeypatch: pytest.MonkeyPatch,
    edited: bool,
) -> None:
    library.create_session("a")
    library.create_session("b")
    sealed(library.root, "orphan", "e1", range(1))
    with ContentStore(library) as store:
        store.create_transcript("a", [Segment("a-line", 0, 1, "original a")])
        revision_b = store.create_transcript("b", [Segment("b-line", 0, 1, "original b")])
        window = opened(library, DesktopRecorder(library, forbidden))
        select(window, "a")
        panel = window.ai_bridge.panel
        if edited:
            panel.table.item(0, 1).setText("saved edit a")
            settle(window, application)
        expected_text = "saved edit a" if edited else "original a"
        assert panel.table.item(0, 1).text() == expected_text
        before_revision = panel.revision["revision_id"]
        seen: list[str] = []
        load = panel.load

        def observe(session_id: str) -> None:
            seen.append(session_id)
            assert session_id != "orphan"
            load(session_id)

        monkeypatch.setattr(panel, "load", observe)
        select(window, "orphan")
        assert window.selected_session() == "orphan"
        assert not panel.isEnabled() and not panel.table.isEnabled()
        assert panel.revision["revision_id"] == before_revision
        assert panel.table.item(0, 1).text() == expected_text
        assert "orphan" not in seen
        QTest.keyClicks(panel.table, "forbidden orphan edit")
        assert panel.table.item(0, 1).text() == expected_text
        select(window, "b")
        assert panel.isEnabled() and panel.table.isEnabled()
        assert panel.session_id == "b" and panel.revision["revision_id"] == revision_b
        assert panel.table.item(0, 1).text() == "original b"
        assert store.active_transcript("a")["segments"][0]["text"] == expected_text


@pytest.mark.skipif(sys.platform != "win32", reason="actual NTFS junction/hard link")
@pytest.mark.parametrize(
    "kind", ("junction", "hardlink"), ids=[f"G04-FIX2-UI-{i}" for i in range(2)]
)
def test_bad_session_is_actionable_without_disabling_safe_session_finalize(
    application: QApplication,
    library: Library,
    tmp_path: Path,
    opened: Callable[[Library, DesktopRecorder], MainWindow],
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    import _winapi

    for sid in ("bad", "good"):
        stale(library, sid, SessionState.RECORDING, SessionState.INTERRUPTED)
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "private"
    target.write_bytes(b"private canary")
    if kind == "junction":
        link = library.root / "sessions/bad/staging"
        link.rmdir()
        _winapi.CreateJunction(str(outside), str(link))
    else:
        link = library.root / "sessions/bad/tracks/linked-file"
        link.hardlink_to(target)
    try:
        window = opened(library, DesktopRecorder(library, forbidden))
        select(window, "bad")
        assert not window._finalize_allowed() and not window.finalize_button.isEnabled()
        assert "INSPECTION_UNSAFE" in window.sessions.currentItem().text()
        assert "링크·하드 링크를 제거" in window.details.toPlainText()
        assert "새로고침" in window.details.toPlainText()
        window.recover_selected()
        assert "링크·하드 링크를 제거" in window.warning.text()
        settle(window, application)
        select(window, "good")
        assert window.finalize_button.isEnabled()
        monkeypatch.setattr(window, "_confirm_finalize", lambda: True)
        window.finalize_selected()
        settle(window, application)
        assert library.get_session("good").state is SessionState.FINALIZED
        assert library.get_session("bad").state is SessionState.INTERRUPTED
        assert target.read_bytes() == b"private canary"
    finally:
        assert link.parent.is_relative_to(library.root)
        if kind == "junction":
            assert getattr(link.lstat(), "st_file_attributes", 0) & 0x400
            link.rmdir()
        else:
            assert link.lstat().st_nlink == 2
            link.unlink()
