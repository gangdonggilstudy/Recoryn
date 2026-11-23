"""G05 UI: pending deletions restored from storage, selected/all retry, unconfirmed history.

Offscreen Qt with real SQLite/journal/PCM in OS TEMP. Expected screens are the hand table of
docs/testing/g05-pending-deletion-cases.md section 4.1 and 5.1 (UI 54 + U1-U6). The removal
lock is a test blocker on the remover; no device, model or network.
"""

from __future__ import annotations

import itertools
import os
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

from recoryn.app.desktop import DesktopRecorder
from recoryn.app.recording import RecordingService
from recoryn.domain import PCMBlock, SessionState
from recoryn.storage import Library
from recoryn.storage import library as library_module
from recoryn.ui.main import MainWindow
from tests.unit.test_pending_deletions import (
    FMT,
    SID,
    build_template,
    clone,
    deleted_row,
    journal_generation,
    media,
    raw,
    sealed,
    write_journal,
)
from tests.unit.test_pending_deletions import intent as journal_intent

pytestmark = pytest.mark.ui


@pytest.fixture(scope="module")
def application() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_template(tmp_path_factory.mktemp("g05-ui-template") / "library")


def forbidden(device: str, loopback: bool) -> Any:
    pytest.fail("no device may be opened by G05 UI tests")


def pump(application: QApplication, predicate: Callable[[], bool], timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        application.processEvents()
        time.sleep(0.001)
    application.processEvents()
    assert predicate()


def settle(window: MainWindow, application: QApplication) -> None:
    pump(
        application,
        lambda: (
            window._closing
            or not (window.busy or window._inventory_loading or window._pending_loading)
        ),
    )


class Blocker:
    """Test-owned removal lock per session folder, with a call count."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.locked: set[str] = set()
        self.calls = 0
        self.original = library_module.remove_tree
        monkeypatch.setattr(library_module, "remove_tree", self)

    def __call__(self, path: Path) -> None:
        self.calls += 1
        if path.name in self.locked:
            raise PermissionError("G05 UI injected locked media")
        self.original(path)


class Windows:
    def __init__(self, application: QApplication) -> None:
        self.application = application
        self.opened: list[tuple[MainWindow, Library]] = []

    def open(self, root: Path, recorder: DesktopRecorder | None = None) -> MainWindow:
        library = Library(root)
        window = MainWindow(library, recorder=recorder or DesktopRecorder(library, forbidden))
        window.timer.stop()
        self.opened.append((window, library))
        settle(window, self.application)
        return window

    def close(self, window: MainWindow) -> None:
        for index, (candidate, library) in enumerate(self.opened):
            if candidate is window:
                window.close()
                settle(window, self.application)
                window.close()
                pump(self.application, lambda: window._closing)
                if window.recorder.recording is not None:
                    window.recorder.recording.join_writer()
                library.close()
                del self.opened[index]
                return


@pytest.fixture
def windows(application: QApplication) -> Iterator[Windows]:
    manager = Windows(application)
    yield manager
    for window, _ in list(manager.opened):
        manager.close(window)


def select_session(window: MainWindow, session_id: str) -> None:
    for row in range(window.sessions.count()):
        item = window.sessions.item(row)
        if item.data(Qt.ItemDataRole.UserRole) == session_id:
            window.sessions.setCurrentItem(item)
            return
    raise AssertionError(session_id)


def labels(window: MainWindow) -> list[str]:
    return [window.pending_list.item(row).text() for row in range(window.pending_list.count())]


def answer_yes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)


def forbid_dialog(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    calls: list[Any] = []

    def asked(*args: Any) -> Any:
        calls.append(args)
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", asked)
    return calls


def add_session(library: Library, session_id: str) -> None:
    library.create_session(session_id)
    library.transition(session_id, SessionState.RECORDING, 0)
    library.register_chunk(sealed(library.root, session_id, session_id + "-c1", (0, 1)))
    library.transition(session_id, SessionState.INTERRUPTED, 1)


def pend_in_window(window: MainWindow, application: QApplication, session_id: str) -> None:
    select_session(window, session_id)
    window.delete_selected()
    settle(window, application)
    assert session_id in window._pending_deletions


def pend_offline(root: Path, blocker: Blocker, *sessions: str) -> None:
    with Library(root) as library:
        for session_id in sessions:
            if session_id != SID and session_id not in {
                s.session_id for s in library.list_sessions()
            }:
                add_session(library, session_id)
            blocker.locked.add(session_id)
            assert library.delete_session(session_id)["reason"] == "MEDIA_REMOVAL_FAILED"


def counted_retries(monkeypatch: pytest.MonkeyPatch, library: Library) -> list[tuple[str, int]]:
    calls: list[tuple[str, int]] = []
    original = library.retry_deletion

    def retry(session_id: str, *, expected_generation: int) -> dict[str, Any]:
        calls.append((session_id, expected_generation))
        return original(session_id, expected_generation=expected_generation)

    monkeypatch.setattr(library, "retry_deletion", retry)
    return calls


def conflict(library: Library, root: Path) -> None:
    """A list-only failure: the catalog generation is newer than the intent (section 2.2).

    A corrupt journal would already stop ContentStore (and so the window) from opening;
    that existing fail-closed startup is not changed here.
    """
    generation = journal_generation(root)
    assert generation is not None
    raw(library, "UPDATE sessions SET generation=? WHERE session_id=?", generation + 1, SID)


# --- UI 54: inventory 3 x existing/new window 2 x action 3 x next retry result 3 --------

UI_DIMENSIONS = list(
    itertools.product(
        ("empty", "pending", "error"),
        ("existing", "new"),
        ("query", "selected", "all"),
        ("complete", "locked", "between"),
    )
)
UI_CASES = [
    pytest.param(*dims, id=f"G05-UI-{index:04d}") for index, dims in enumerate(UI_DIMENSIONS)
]


@pytest.mark.parametrize(("inventory", "window_kind", "action", "outcome"), UI_CASES)
def test_pending_deletions_are_restored_and_retried_from_storage(
    application: QApplication,
    template: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    windows: Windows,
    inventory: str,
    window_kind: str,
    action: str,
    outcome: str,
) -> None:
    root = clone(template, tmp_path / "library")
    blocker = Blocker(monkeypatch)
    answer_yes(monkeypatch)
    if window_kind == "existing":
        window = windows.open(root)
        if inventory != "empty":
            blocker.locked.add(SID)
            pend_in_window(window, application, SID)
        if inventory == "error":
            conflict(window.library, root)
            window.refresh_sessions()
            settle(window, application)
    else:
        if inventory != "empty":
            pend_offline(root, blocker, SID)
        if inventory == "error":
            with Library(root) as offline:
                conflict(offline, root)
        window = windows.open(root)  # a new Library and a new window: storage is the source
    library = window.library
    generation = None if inventory == "empty" else journal_generation(root)
    if outcome == "complete":
        blocker.locked.discard(SID)
    elif outcome == "between" and inventory == "pending":
        blocker.locked.discard(SID)
        assert library.retry_deletion(SID, expected_generation=generation)["deleted"] is True
    before = media(root)
    retries = counted_retries(monkeypatch, library)
    dialogs = forbid_dialog(monkeypatch)
    blocker.calls = 0
    if action == "query":
        window.refresh_sessions()
    elif action == "selected":
        if window.pending_list.count():
            window.pending_list.setCurrentRow(0)
        window.retry_delete_button.click()
    else:
        window.retry_all_button.click()
    settle(window, application)
    status = window.deletion_status.text()
    shown = labels(window)
    assert dialogs == []  # an approved deletion is never re-confirmed
    if inventory == "empty":
        assert shown == [] and retries == [] and blocker.calls == 0
        assert "삭제 대기" not in status and "확인 불가" not in status
        assert not window.retry_delete_button.isEnabled()
        assert not window.retry_all_button.isEnabled()
        assert media(root) == before
        return
    if inventory == "error":
        assert retries == [] and blocker.calls == 0 and media(root) == before
        assert "삭제 이력 확인 불가" in status and "0건" not in status
        assert not window.retry_delete_button.isEnabled()
        assert not window.retry_all_button.isEnabled()
        if window_kind == "existing":
            assert len(shown) == 1 and "확인 전" in shown[0]  # last list kept, unconfirmed
        else:
            assert shown == []  # first failure: never shown as zero pending
        return
    finished = outcome == "between" or (action != "query" and outcome == "complete")
    if finished:
        assert shown == [] and "삭제 대기" not in status
        assert not window.retry_delete_button.isEnabled()
        assert deleted_row(library) == (generation, "DELETED_LOCAL")
        assert not (root / "sessions" / SID).exists()
    if action == "query":
        assert retries == [] and blocker.calls == 0
        if not finished:
            [label] = shown
            assert label.startswith(SID[:12] + " · ") and "원본 폴더 남음" in label
            # A restart keeps no earlier error; this window remembers its own attempt.
            reason = "원본 파일 제거 실패" if window_kind == "existing" else "이전 제거 실패"
            assert reason in label
            assert "삭제 대기 1건" in status and "원본 제거 보류" in status
            assert window.retry_delete_button.isEnabled() and window.retry_all_button.isEnabled()
            assert media(root) == before
        return
    assert retries == [(SID, generation)]  # exactly the shown (ID, generation)
    if outcome == "locked":
        [label] = shown
        assert "원본 파일 제거 실패" in label and blocker.calls == 1
        assert "삭제 대기 1건" in status and "삭제 완료" not in status
        assert media(root) == before and deleted_row(library) == (generation, "DELETE_PENDING")
        assert window.retry_delete_button.isEnabled()
    else:
        assert "삭제 완료 1건" in status
        assert blocker.calls == (1 if outcome == "complete" else 0)


# --- U1-U6: multiple items, late callbacks, unconfirmed lists, live recording, restart ---

U_CASES = [pytest.param(index, id=f"G05-UI-{54 + index:04d}") for index in range(6)]


def u_case(index: int) -> Any:
    return pytest.mark.parametrize("case", [U_CASES[index]])


@u_case(0)
def test_u1_one_failure_keeps_the_other_completion(
    case: int,
    application: QApplication,
    template: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    windows: Windows,
) -> None:
    """G05-UI-0054: A fails, B completes; neither result hides the other."""
    root = clone(template, tmp_path / "library")
    blocker = Blocker(monkeypatch)
    pend_offline(root, blocker, "a", "b")
    blocker.locked = {"a"}
    window = windows.open(root)
    assert [label[:1] for label in labels(window)] == ["a", "b"]
    forbid_dialog(monkeypatch)
    window.retry_all_button.click()
    settle(window, application)
    [label] = labels(window)
    assert label.startswith("a · 원본 파일 제거 실패")
    status = window.deletion_status.text()
    assert "삭제 완료 1건" in status and "삭제 대기 1건" in status
    assert not (root / "sessions" / "b").exists() and (root / "sessions" / "a").exists()
    assert "b" not in window._pending_deletions


@u_case(1)
def test_u2_retry_all_completes_every_item(
    case: int,
    application: QApplication,
    template: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    windows: Windows,
) -> None:
    """G05-UI-0055"""
    root = clone(template, tmp_path / "library")
    blocker = Blocker(monkeypatch)
    pend_offline(root, blocker, "a", "b")
    blocker.locked.clear()
    window = windows.open(root)
    assert len(labels(window)) == 2
    window.retry_all_button.click()
    settle(window, application)
    assert labels(window) == [] and "삭제 완료 2건" in window.deletion_status.text()
    assert not window.retry_all_button.isEnabled()
    assert window.library.pending_deletions() == []


@u_case(2)
def test_u3_late_result_of_an_older_generation_never_completes_the_newer_row(
    case: int,
    application: QApplication,
    template: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    windows: Windows,
) -> None:
    """G05-UI-0056"""
    root = clone(template, tmp_path / "library")
    blocker = Blocker(monkeypatch)
    pend_offline(root, blocker, SID)
    window = windows.open(root)
    library = window.library
    old = journal_generation(root)
    entered, release = threading.Event(), threading.Event()

    def late(session_id: str, *, expected_generation: int) -> dict[str, Any]:
        entered.set()
        assert release.wait(10)
        return {
            "session_id": session_id,
            "state": "DELETED_LOCAL",
            "deleted": True,
            "already_deleted": False,
            "generation": expected_generation,
        }

    monkeypatch.setattr(library, "retry_deletion", late)
    seen: list[tuple[bool, str]] = []
    render = window._render_pending

    def observed() -> None:
        render()
        seen.append((SID in window._pending_deletions, window.deletion_status.text()))

    monkeypatch.setattr(window, "_render_pending", observed)
    window.retry_delete_button.click()
    pump(application, entered.is_set)
    with library._mutex:  # a newer intent generation becomes the durable state
        raw(library, "UPDATE deleted_sessions SET generation=? WHERE session_id=?", old + 1, SID)
        raw(library, "UPDATE sessions SET generation=? WHERE session_id=?", old + 1, SID)
        write_journal(root, journal_intent(old + 1))
    window.refresh_sessions()
    pump(application, lambda: window._pending_deletions.get(SID, {}).get("generation") == old + 1)
    seen.clear()
    release.set()
    settle(window, application)
    assert seen and all(present for present, _ in seen), seen
    assert all("삭제 완료" not in text for _, text in seen)
    assert window._pending_deletions[SID]["generation"] == old + 1


@u_case(3)
def test_u4_failed_query_after_a_success_keeps_an_unconfirmed_list(
    case: int,
    application: QApplication,
    template: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    windows: Windows,
) -> None:
    """G05-UI-0057"""
    root = clone(template, tmp_path / "library")
    blocker = Blocker(monkeypatch)
    pend_offline(root, blocker, SID)
    window = windows.open(root)
    assert window.retry_delete_button.isEnabled()
    leftover = root / "deletion-journal" / ".tmp-g05"
    leftover.write_bytes(b"{")
    window.refresh_sessions()
    settle(window, application)
    [label] = labels(window)
    assert "확인 전" in label
    status = window.deletion_status.text()
    assert "삭제 이력 확인 불가" in status and "마지막으로 확인한 목록" in status
    assert not window.retry_delete_button.isEnabled() and not window.retry_all_button.isEnabled()
    refresh = next(
        button for button in window.findChildren(QPushButton) if button.text() == "새로고침"
    )
    assert refresh.isEnabled()
    leftover.unlink()
    refresh.click()
    settle(window, application)
    assert "확인 전" not in labels(window)[0] and window.retry_delete_button.isEnabled()


@u_case(4)
def test_u5_restored_pending_item_does_not_disturb_live_recording_or_unfinished_notice(
    case: int,
    application: QApplication,
    template: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    windows: Windows,
) -> None:
    """G05-UI-0058"""
    root = clone(template, tmp_path / "library")
    blocker = Blocker(monkeypatch)
    pend_offline(root, blocker, SID)
    with Library(root) as library:
        add_session(library, "old")  # a stale INTERRUPTED session for the G-P04 notice
    library = Library(root)
    recorder = DesktopRecorder(library, forbidden)
    service = RecordingService(library, {"mic": FMT}, session_id="live", chunk_frames=96_000)
    recorder.recording = service
    service.start()
    window = MainWindow(library, recorder=recorder)
    window.timer.stop()
    windows.opened.append((window, library))
    settle(window, application)
    assert [label[: len(SID) + 3] for label in labels(window)] == [SID + " · "]
    assert "확정되지 않은 세션 1건" in window.recovery_status.text()
    assert "삭제" not in window.recovery_status.text()
    assert window.stop_button.isEnabled()
    window.stop_recording()
    pump(application, lambda: library.get_session("live").state == SessionState.FINALIZED)
    settle(window, application)
    assert SID in window._pending_deletions and "live" not in window._pending_deletions


@u_case(5)
def test_u6_last_completion_clears_the_list_and_a_new_window_stays_empty(
    case: int,
    application: QApplication,
    template: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    windows: Windows,
) -> None:
    """G05-UI-0059"""
    root = clone(template, tmp_path / "library")
    blocker = Blocker(monkeypatch)
    pend_offline(root, blocker, SID)
    blocker.locked.clear()
    window = windows.open(root)
    assert window.pending_list.accessibleName() == "삭제 대기 세션 목록"
    assert window.pending_detail.accessibleName() and SID in window.pending_detail.text()
    window.pending_list.setFocus()
    window.retry_delete_button.click()
    settle(window, application)
    assert labels(window) == [] and not window.retry_delete_button.isEnabled()
    assert not window.retry_all_button.isEnabled() and window.pending_detail.text() == ""
    assert "삭제 완료 1건" in window.deletion_status.text()
    windows.close(window)
    again = windows.open(root)
    assert labels(again) == [] and "삭제 대기" not in again.deletion_status.text()
    assert not again.retry_delete_button.isEnabled()


# --- C00-required extras (not counted in the 60 UI rows) --------------------------------


def test_uix_deleting_the_selection_reaches_the_privacy_panel_as_none(
    application: QApplication,
    template: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    windows: Windows,
) -> None:
    """G05-UIX-0000: a rebuild that drops the selection still notifies listeners (G-P02 2.4)."""
    root = clone(template, tmp_path / "library")
    Blocker(monkeypatch)
    window = windows.open(root)
    select_session(window, SID)
    application.processEvents()
    assert window.privacy_panel._selected_session == SID
    answer_yes(monkeypatch)
    window.delete_selected()
    settle(window, application)
    pump(application, lambda: window.privacy_panel._selected_session is None)
    assert window.selected_session() is None


def test_uix_pending_query_runs_off_gui_and_older_results_never_win(
    application: QApplication,
    template: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    windows: Windows,
) -> None:
    """G05-UIX-0001"""
    root = clone(template, tmp_path / "library")
    blocker = Blocker(monkeypatch)
    pend_offline(root, blocker, SID)
    window = windows.open(root)
    library = window.library
    original = library.pending_deletions
    gui = threading.get_ident()
    entered = [threading.Event(), threading.Event()]
    release = [threading.Event(), threading.Event()]
    threads: list[int] = []

    def inspect() -> list[dict[str, Any]]:
        index = len(threads)
        threads.append(threading.get_ident())
        rows = original()
        rows = [dict(row, reason="SESSION_LIVE" if index == 0 else row["reason"]) for row in rows]
        entered[index].set()
        assert release[index].wait(10)
        return rows

    monkeypatch.setattr(library, "pending_deletions", inspect)
    try:
        started = time.perf_counter()
        window.refresh_sessions()
        assert time.perf_counter() - started < 0.1 and not window.busy
        pulse: list[bool] = []
        QTimer.singleShot(0, lambda: pulse.append(True))
        pump(application, lambda: entered[0].is_set() and bool(pulse))
        window.refresh_sessions()
        release[0].set()
        pump(application, entered[1].is_set)
        assert window._pending_deletions[SID]["reason"] != "SESSION_LIVE"  # older result dropped
        release[1].set()
        settle(window, application)
        assert window._pending_deletions[SID]["reason"] == "RETRY_REQUIRED"
    finally:
        for event in release:
            event.set()
        settle(window, application)
    assert threads and all(thread != gui for thread in threads)


# --- FIX1 (G05R-01, G05R-03): warning priority and revocation before a UI retry --------
# Additional rows outside the 60 UI contract rows: G05-FIX1-0004..0008.
DROP_WARNING = "오디오 저장 큐 포화로 유실된 프레임이 있습니다. 건강 정보에 누계를 보존합니다."


@pytest.mark.parametrize("scope", ("selected", "all"), ids=["G05-FIX1-0004", "G05-FIX1-0005"])
def test_ui_retry_revokes_transfers_before_each_retry(
    application: QApplication,
    template: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    windows: Windows,
    scope: str,
) -> None:
    """Section 3.2: stop_playback, then before_delete (revoke/cancel) before each retry."""
    root = clone(template, tmp_path / "library")
    blocker = Blocker(monkeypatch)
    sessions = ("a", "b") if scope == "all" else (SID,)
    pend_offline(root, blocker, *sessions)
    blocker.locked.clear()
    window = windows.open(root)
    library = window.library
    expected = {sid: window._pending_deletions[sid]["generation"] for sid in sessions}
    log: list[tuple[Any, ...]] = []
    bridge = window.ai_bridge
    stop, revoke, retry = bridge.stop_playback, bridge.before_delete, library.retry_deletion

    def stopped() -> None:
        log.append(("stop_playback",))
        stop()

    def revoked(session_id: str) -> None:
        log.append(("before_delete", session_id))
        revoke(session_id)

    def retried(session_id: str, *, expected_generation: int) -> dict[str, Any]:
        log.append(("retry", session_id, expected_generation))
        return retry(session_id, expected_generation=expected_generation)

    monkeypatch.setattr(bridge, "stop_playback", stopped)
    monkeypatch.setattr(bridge, "before_delete", revoked)
    monkeypatch.setattr(library, "retry_deletion", retried)
    (window.retry_all_button if scope == "all" else window.retry_delete_button).click()
    settle(window, application)
    assert log[0] == ("stop_playback",)
    calls = [item for item in log if item[0] != "stop_playback"]
    assert calls == [
        step
        for sid in sorted(sessions)
        for step in (("before_delete", sid), ("retry", sid, expected[sid]))
    ]
    for sid in sessions:  # the session transfer revocation was persisted
        row = window.consents._db.execute(
            "SELECT revoked FROM security_sessions WHERE session_id=?", (sid,)
        ).fetchone()
        assert row is not None and row[0] == 1
    assert labels(window) == []


def record_with_drops(root: Path) -> tuple[Library, DesktopRecorder, RecordingService]:
    library = Library(root)
    recorder = DesktopRecorder(library, forbidden)
    service = RecordingService(library, {"mic": FMT}, session_id="live", max_blocks=1)
    recorder.recording = service
    service.start()
    return library, recorder, service


def overflow(service: RecordingService) -> None:
    epoch = service.epochs["mic"]
    for index in range(200):
        stamp = 1_000_000 + index * 10_000_000
        service.submit(
            PCMBlock(
                "live",
                "mic",
                epoch,
                index,
                FMT,
                480,
                b"\0\x01" * 480,
                stamp,
                stamp,
                device_frame_position=index * 480,
            )
        )
    assert service.health_snapshot()["tracks"]["mic"]["dropped_frames"] > 0


@pytest.mark.parametrize("case", [pytest.param(6, id="G05-FIX1-0006")])
def test_restored_pending_never_hides_the_frame_loss_warning(
    application: QApplication,
    template: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    windows: Windows,
    case: int,
) -> None:
    """G05R-01 with the real 250ms timer: frame loss keeps the warning slot."""
    root = clone(template, tmp_path / "library")
    blocker = Blocker(monkeypatch)
    pend_offline(root, blocker, SID)
    library, recorder, service = record_with_drops(root)
    window = MainWindow(library, recorder=recorder)  # timer left running
    windows.opened.append((window, library))
    settle(window, application)
    assert SID in window._pending_deletions  # restored from storage after the restart
    overflow(service)
    window.refresh_sessions()  # a background pending observation lands meanwhile
    seen: list[str] = []
    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline:
        application.processEvents()
        if window.warning.text() == DROP_WARNING or seen:
            seen.append(window.warning.text())
        time.sleep(0.01)
    settle(window, application)
    seen.append(window.warning.text())
    assert seen and set(seen) == {DROP_WARNING}, set(seen)
    status = window.deletion_status.text()
    assert "삭제 대기 1건" in status and "원본 제거 보류" in status


def device_alert(window: MainWindow, monkeypatch: pytest.MonkeyPatch, code: str) -> str:
    events = [({}, [{"code": code}])]
    original = window.recorder.observations

    def observations() -> Any:
        return events.pop() if events else original()

    monkeypatch.setattr(window.recorder, "observations", observations)
    window._tick()
    assert window.warning.text() == "장치 상태: " + code
    return window.warning.text()


@pytest.mark.parametrize("case", [pytest.param(7, id="G05-FIX1-0007")])
def test_device_warning_survives_ticks_and_pending_refresh(
    application: QApplication,
    template: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    windows: Windows,
    case: int,
) -> None:
    """G05R-01: a one-off device warning is not replaced by the restored pending notice."""
    root = clone(template, tmp_path / "library")
    blocker = Blocker(monkeypatch)
    pend_offline(root, blocker, SID)
    window = windows.open(root)
    alert = device_alert(window, monkeypatch, "G05_DEVICE_LOST")
    for _ in range(3):
        window._tick()
    window.refresh_sessions()
    settle(window, application)
    window._tick()
    assert window.warning.text() == alert
    assert "삭제 대기 1건" in window.deletion_status.text()


@pytest.mark.parametrize("case", [pytest.param(8, id="G05-FIX1-0008")])
def test_a_retry_result_does_not_replace_an_active_device_warning(
    application: QApplication,
    template: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    windows: Windows,
    case: int,
) -> None:
    """G05R-01: the user's own retry result goes to deletion_status while an alert shows."""
    root = clone(template, tmp_path / "library")
    blocker = Blocker(monkeypatch)
    pend_offline(root, blocker, SID)  # the lock stays: the retry fails again
    window = windows.open(root)
    alert = device_alert(window, monkeypatch, "G05_DEVICE_CHANGED")
    window.retry_delete_button.click()
    settle(window, application)
    assert window.warning.text() == alert
    [label] = labels(window)
    assert "원본 파일 제거 실패" in label
    assert "삭제 대기 1건" in window.deletion_status.text()


def test_declared_ui_denominator_is_complete_and_unique() -> None:
    ids = [case.id for case in UI_CASES + U_CASES]
    assert len(UI_CASES) == 3 * 2 * 3 * 3 and len(U_CASES) == 6
    assert ids == [f"G05-UI-{i:04d}" for i in range(60)]
