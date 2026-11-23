"""G02 scope selection/confirmation with an offscreen UI and fake vault/transport."""

from __future__ import annotations

import itertools
import os
import threading
import time
import wave
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QTabWidget,
)

from recoryn.security import (
    ConsentScope,
    ConsentStore,
    CostLedger,
    CredentialVault,
    Gateway,
    SecurityError,
)
from recoryn.security._core import Endpoint
from recoryn.ui.privacy import PrivacyPanel

URL = "https://scope.example.test/v1"
ACTION = list(
    itertools.product(
        (None, "A", "B"),
        ("stt", "summary"),
        ("session", "library"),
        range(4),
        ("grant", "revoke", "context"),
    )
)
CANCEL = list(itertools.product((None, "A", "B"), ("stt", "summary"), ("cancel", "escape")))
SNAPSHOT = list(
    itertools.product(
        ("session", "library"),
        ("stt", "summary"),
        ("selection", "scope", "policy"),
        ("before", "after"),
    )
)
CASE_IDS = {
    "UI": [f"G02-UI-ACTION-{i:03d}" for i in range(144)]
    + [f"G02-UI-CANCEL-{i:02d}" for i in range(12)]
    + [f"G02-UI-SNAPSHOT-{i:02d}" for i in range(24)]
    + [f"G02-UI-DEFAULT-{kind}" for kind in ("stt", "summary")],
    "UI_FIX": [f"G02-UI-FIX-{i:02d}" for i in range(30)],
}
G02B_CASE_IDS = {
    "STATUS": [f"G02B-STATUS-{i:02d}" for i in range(20)],
    "GAP": [f"G02B-GAP-{i:02d}" for i in range(40)],
    "DELETE": [f"G02B-DELETE-{i:02d}" for i in range(12)],
    "CHECKING": [f"G02B-CHECKING-{i:02d}" for i in range(2)],
}


class Backend:
    def __init__(self) -> None:
        self.reads = 0

    def read(self, target: str) -> bytes:
        self.reads += 1
        return b"FAKE-G02-CREDENTIAL"

    def write(self, target: str, secret: bytes) -> None:
        raise AssertionError("no vault writes in scope tests")

    def delete(self, target: str) -> None:
        raise AssertionError("no vault deletion in scope tests")


class Wire:
    def __init__(self) -> None:
        self.opens = 0
        self.writes: list[bytes] = []

    def open(
        self, endpoint: Endpoint, headers: Mapping[str, str], body_length: int, timeout: float
    ) -> Wire:
        self.opens += 1
        return self

    def write(self, data: bytes, timeout: float) -> None:
        self.writes.append(data)

    def read(self, limit: int, timeout: float) -> bytes:
        return b""

    def close(self) -> None:
        pass


@pytest.fixture(scope="module")
def app() -> QApplication:
    existing = QApplication.instance()
    return existing if isinstance(existing, QApplication) else QApplication([])


@contextmanager
def panel(
    tmp_path: Path,
    kind: str,
    clock: Callable[[], float] | None = None,
    *,
    existing_grants: int = 0,
) -> Iterator[tuple[PrivacyPanel, Backend, Wire]]:
    backend, wire = Backend(), Wire()
    db = tmp_path / "scope.db"
    options = {"clock": clock} if clock is not None else {}
    with ConsentStore(db, **options) as policy, CostLedger(db) as ledger:
        widget = PrivacyPanel(
            policy,
            ledger,
            CredentialVault(backend=backend, namespace="G02-test"),
            gateway=Gateway(policy, transport=wire),
        )
        controls = widget.controls[kind]
        # Only batch empty-fixture setup. All observed actions, grants and later
        # setting changes below use real signals and the production handlers.
        assert not widget._granted[kind]
        assert (
            policy._db.execute("SELECT COUNT(*) FROM security_grants_v2").fetchone()[0]
            == existing_grants
        )
        blocked = [
            (control, control.blockSignals(True))
            for control in (
                controls.provider,
                controls.endpoint,
                controls.model,
                controls.context_window,
                controls.per_request,
                controls.total,
            )
        ]
        try:
            controls.provider.setCurrentIndex(controls.provider.findData("openai"))
            controls.endpoint.setText(URL)
            controls.model.setText("fake-model")
            controls.context_window.setValue(4096)
            controls.per_request.setValue(0.01)
            controls.total.setValue(1)
        finally:
            for control, previous in blocked:
                control.blockSignals(previous)
        widget._changed(kind)
        yield widget, backend, wire
        widget.close()


def seed(
    widget: PrivacyPanel, kind: str, scopes: tuple[ConsentScope, ...], version: int = 2
) -> str:
    data = "audio" if kind == "stt" else "transcript"
    for scope in scopes:
        widget.consents.grant(
            "openai", URL, data, capability=kind, scope=scope, policy_version=version
        )
    return data


@pytest.mark.parametrize("row", ACTION, ids=CASE_IDS["UI"][:144])
def test_scope_actions(
    app: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, row: tuple[Any, ...]
) -> None:
    sid, kind, scope_kind, catalog, action = row
    with panel(tmp_path, kind) as (widget, backend, wire):
        assert widget.controls[kind].scope.currentData() == "session"
        for target in ("A", "B"):
            widget.consents.bind_session(target)
        widget.select_session(sid)
        control = widget.controls[kind]
        control.scope.setCurrentIndex(control.scope.findData(scope_kind))
        scopes = (
            (ConsentScope.session("A"),)
            if catalog == 1
            else (ConsentScope.library(),)
            if catalog == 2
            else (ConsentScope.session("A"), ConsentScope.library())
            if catalog == 3
            else ()
        )
        data = seed(widget, kind, scopes)
        confirmations: list[str] = []

        def yes(parent: Any, title: str, text: str, *args: Any) -> Any:
            confirmations.append(text)
            return QMessageBox.StandardButton.Yes

        monkeypatch.setattr(QMessageBox, "question", yes)
        before = widget.consents._db.execute("SELECT COUNT(*) FROM security_grants_v2").fetchone()[
            0
        ]
        if action == "grant":
            control.allow.click()
            enabled = sid is not None or scope_kind == "library"
            selected = (
                ConsentScope.library()
                if scope_kind == "library"
                else ConsentScope.session(sid or "A")
            )
            info = widget.consents.grant_info(
                "openai", URL, data, capability=kind, scope=selected, policy_version=2
            )
            if enabled:
                assert info and info["active"]
            else:
                assert (
                    widget.consents._db.execute(
                        "SELECT COUNT(*) FROM security_grants_v2"
                    ).fetchone()[0]
                    == before
                )
            assert len(confirmations) == int(scope_kind == "library")
            if confirmations:
                for text in (
                    "현재·새 세션",
                    "현재 실행만",
                    "만료",
                    kind,
                    data,
                    URL,
                    "정책 version: 2",
                ):
                    assert text in confirmations[0]
        elif action == "revoke":
            control.revoke.click()
            if sid is not None or scope_kind == "library":
                selected = (
                    ConsentScope.library() if scope_kind == "library" else ConsentScope.session(sid)
                )
                info = widget.consents.grant_info(
                    "openai", URL, data, capability=kind, scope=selected, policy_version=2
                )
                assert not info or not info["active"]
        else:
            expected = sid is not None and (
                (scope_kind == "session" and sid == "A" and catalog in (1, 3))
                or (scope_kind == "library" and catalog in (2, 3))
            )
            if expected:
                execution = widget.prepare_execution(kind, sid, threading.Event())
                assert execution.gateway is not None
                assert execution.gateway.session_id == sid
                assert execution.context.reservation_factory is not None
            else:
                with pytest.raises(SecurityError):
                    widget.prepare_execution(kind, sid, threading.Event())
                assert backend.reads == 0
        assert wire.opens == 0 and not wire.writes
        assert control.scope.accessibleName() and control.scope_info.accessibleName()
        if scope_kind == "library" or sid is not None:
            assert "정책" in control.scope_info.text()


@pytest.mark.parametrize("row", CANCEL, ids=CASE_IDS["UI"][144:156])
def test_library_confirmation_cancel(
    app: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, row: tuple[Any, ...]
) -> None:
    sid, kind, how = row
    with panel(tmp_path, kind) as (widget, backend, wire):
        widget.select_session(sid)
        control = widget.controls[kind]
        control.scope.setCurrentIndex(1)
        response = (
            QMessageBox.StandardButton.No if how == "cancel" else QMessageBox.StandardButton.Cancel
        )
        monkeypatch.setattr(QMessageBox, "question", lambda *args: response)
        control.allow.click()
        assert (
            widget.consents._db.execute("SELECT COUNT(*) FROM security_grants_v2").fetchone()[0]
            == 0
        )
        assert backend.reads == 0 and wire.opens == 0


@pytest.mark.parametrize("row", SNAPSHOT, ids=CASE_IDS["UI"][156:180])
def test_scope_snapshot_is_fixed(app: QApplication, tmp_path: Path, row: tuple[Any, ...]) -> None:
    scope_kind, kind, change, when = row
    with panel(tmp_path, kind) as (widget, backend, wire):
        widget.select_session("A")
        control = widget.controls[kind]
        control.scope.setCurrentIndex(control.scope.findData(scope_kind))
        scopes = (ConsentScope.session("A"), ConsentScope.library())
        data = seed(widget, kind, scopes)
        if when == "after":
            execution = widget.prepare_execution(kind, "A", threading.Event())
        if change == "selection":
            widget.select_session("B")
        elif change == "scope":
            control.scope.setCurrentIndex(1 - control.scope.currentIndex())
        else:
            widget.consents.advance_policy_version(3)
            seed(widget, kind, scopes, 3)
        if when == "before":
            execution = widget.prepare_execution(kind, "A", threading.Event())
        assert execution.gateway is not None
        assert execution.gateway.session_id == "A"
        binding = execution.gateway.expected_grants[0]
        assert binding.request.capability == kind
        assert binding.request.policy_version == (
            3 if change == "policy" and when == "before" else 2
        )
        if when == "after":
            assert binding.scope.kind == scope_kind
        elif change == "scope":
            assert binding.scope.kind != scope_kind
        elif change == "selection":
            assert binding.scope == ConsentScope.session("A")
        reserve = execution.context.reservation_factory
        assert reserve is not None
        if change == "policy" and when == "after":
            with pytest.raises(SecurityError, match="CONSENT_POLICY_CHANGED"):
                reserve("openai", URL, data, 1)
            assert widget.ledger.reservations("openai") == []
        else:
            reservation = reserve("openai", URL, data, 1)
            execution.gateway.request("openai", URL, data, b"a", reservation_id=reservation)
            assert wire.opens == 1 and wire.writes == [b"a"]
        assert backend.reads == 1


@pytest.mark.parametrize("kind", ("stt", "summary"), ids=CASE_IDS["UI"][180:])
def test_session_default_and_selection_clear(app: QApplication, tmp_path: Path, kind: str) -> None:
    from recoryn.ui.ai_bridge import DesktopAI

    with panel(tmp_path, kind) as (widget, backend, wire):
        assert widget.controls[kind].scope.currentData() == "session"
        assert not widget.controls[kind].allow.isEnabled()
        tabs, sessions = QTabWidget(), QListWidget()
        window = SimpleNamespace(tabs=tabs, sessions=sessions)
        window.selected_session = lambda: (
            sessions.currentItem().data(Qt.ItemDataRole.UserRole)
            if sessions.currentItem()
            else None
        )
        bridge = object.__new__(DesktopAI)
        bridge.window = window
        bridge.panel = SimpleNamespace(load=lambda sid: None)
        bridge.attach_privacy(widget)
        item = QListWidgetItem("A")
        item.setData(Qt.ItemDataRole.UserRole, "A")
        sessions.addItem(item)
        sessions.setCurrentItem(item)
        assert widget._selected_session == "A"
        sessions.clear()
        assert widget._selected_session is None
        assert not widget.controls[kind].allow.isEnabled()
        assert not widget.controls[kind].revoke.isEnabled()
        assert backend.reads == 0 and wire.opens == 0
        tabs.close()
        sessions.close()


@pytest.mark.parametrize("kind", ("stt", "summary"))
def test_bridge_submission_keeps_one_fixed_session_snapshot(
    app: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    from recoryn.ui.ai_bridge import DesktopAI

    with panel(tmp_path, kind) as (widget, backend, wire):
        selected = ["B" if kind == "stt" else "A"]
        widget.select_session(selected[0])
        data = seed(widget, kind, (ConsentScope.session("A"),))
        window = SimpleNamespace(
            library=SimpleNamespace(chunks=lambda sid: ()),
            selected_session=lambda: selected[0],
            local_model=SimpleNamespace(text=lambda: ""),
            device_policy=SimpleNamespace(currentText=lambda: "CPU_ONLY"),
            model_panel=SimpleNamespace(gpu_busy=False, ollama_owned=False),
        )
        bridge = object.__new__(DesktopAI)
        bridge.window, bridge.privacy = window, widget
        bridge.panel = SimpleNamespace(job_status=QLabel())
        bridge.busy, bridge._shutting_down = False, False
        bridge._live_snapshots, bridge._live_nonces, bridge._live_blocked = {}, {}, set()
        actions: list[Callable[[], Any]] = []
        prepared: list[Any] = []
        prepare = widget.prepare_execution

        def capture(*args: Any) -> Any:
            execution = prepare(*args)
            prepared.append(execution)
            return execution

        def queue(action: Callable[[], Any], *args: Any, **kwargs: Any) -> bool:
            actions.append(action)
            return True

        def submit(sid: str, provider: Any, **options: Any) -> str:
            assert sid == "A" and provider.gateway is prepared[0].gateway
            assert provider.config is prepared[0].config
            assert options["config_key"] == prepared[0].config_key
            context = options["context_factory"](threading.Event())
            assert context.reservation_factory is prepared[0].context.reservation_factory
            assert context.reservation_factory is not None
            reservation = context.reservation_factory("openai", URL, data, 1)
            provider.gateway.request("openai", URL, data, b"a", reservation_id=reservation)
            return "fake-job"

        monkeypatch.setattr(widget, "prepare_execution", capture)
        monkeypatch.setattr(bridge, "operation", queue)
        bridge.service = SimpleNamespace(transcribe=submit, summarize=submit)
        if kind == "stt":
            bridge._transcribe(session_id="A")
        else:
            bridge.summarize("meeting")
        assert len(prepared) == len(actions) == 1
        assert prepared[0].gateway.session_id == "A"
        selected[0] = "B"
        widget.select_session("B")
        assert actions[0]() == "fake-job"
        assert len(prepared) == 1 and backend.reads == 1
        assert wire.opens == 1 and wire.writes == [b"a"]


@pytest.mark.parametrize("kind,delay", list(itertools.product(("stt", "summary"), (1800, 3600))))
def test_library_confirmation_freezes_expiry(
    app: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, delay: int
) -> None:
    # Supplement to the approved representative matrix: a modal dialog must not
    # silently extend the deadline it displayed while the user considers it.
    clock = [1000.0]
    with panel(tmp_path, kind, clock=lambda: clock[0]) as (widget, backend, wire):
        widget.controls[kind].scope.setCurrentIndex(1)

        def delayed_yes(parent: Any, title: str, text: str, *args: Any) -> Any:
            expected = datetime.fromtimestamp(4600, UTC).astimezone().isoformat(timespec="seconds")
            assert expected in text
            clock[0] += delay
            return QMessageBox.StandardButton.Yes

        monkeypatch.setattr(QMessageBox, "question", delayed_yes)
        widget.controls[kind].allow.click()
        data = "audio" if kind == "stt" else "transcript"
        info = widget.consents.grant_info(
            "openai", URL, data, capability=kind, scope=ConsentScope.library(), policy_version=2
        )
        if delay == 1800:
            assert info and info["active"] and info["expires"] == 4600.0
        else:
            assert info is None
            assert widget.controls[kind].status.text() == "CONSENT_REQUIRED"
        assert backend.reads == 0 and wire.opens == 0


def linked_selection(widget: PrivacyPanel) -> tuple[Any, QListWidget, list[str]]:
    """Model main's signal order, including None during a synchronous rebuild."""
    from recoryn.ui.ai_bridge import DesktopAI

    tabs, sessions = QTabWidget(), QListWidget()
    loaded: list[str] = []
    window = SimpleNamespace(tabs=tabs, sessions=sessions)
    window.selected_session = lambda: (
        sessions.currentItem().data(Qt.ItemDataRole.UserRole) if sessions.currentItem() else None
    )
    bridge = object.__new__(DesktopAI)
    bridge.window = window
    bridge.privacy = None
    bridge.panel = SimpleNamespace(load=loaded.append)

    def main_selection(current: Any, previous: Any) -> None:
        sid = window.selected_session()
        if sid is not None:
            bridge.selection(sid)
            loaded.append("details:" + sid)

    sessions.currentItemChanged.connect(main_selection)
    bridge.attach_privacy(widget)
    return bridge, sessions, loaded


def add_session(sessions: QListWidget, sid: str) -> QListWidgetItem:
    item = QListWidgetItem(sid)
    item.setData(Qt.ItemDataRole.UserRole, sid)
    sessions.addItem(item)
    return item


@pytest.mark.parametrize(
    "kind,target",
    list(itertools.product(("stt", "summary"), ("A", "B", None))),
    ids=CASE_IDS["UI_FIX"][:6],
)
def test_refresh_scope_is_preserved_only_for_same_session(
    app: QApplication, tmp_path: Path, kind: str, target: str | None
) -> None:
    with panel(tmp_path, kind) as (widget, backend, wire):
        bridge, sessions, loaded = linked_selection(widget)
        try:
            sessions.setCurrentItem(add_session(sessions, "A"))
            control = widget.controls[kind]
            control.scope.setCurrentIndex(1)
            data = seed(widget, kind, (ConsentScope.library(),))
            rows = widget.consents._db.execute("SELECT COUNT(*) FROM security_sessions").fetchone()[
                0
            ]
            assert rows == 0  # choosing/browsing is not binding a request
            sessions.clear()
            assert widget._selected_session is None
            assert not control.allow.isEnabled()
            if target is not None:
                sessions.setCurrentItem(add_session(sessions, target))
            app.processEvents()
            assert widget._selected_session == target
            assert control.scope.currentData() == ("library" if target == "A" else "session")
            if target == "A":
                execution = widget.prepare_execution(kind, "new-recording", threading.Event())
                assert execution.gateway is not None
                assert execution.gateway.expected_grants[0].scope == ConsentScope.library()
            else:
                assert control.scope.currentIndex() == 0
            assert "A" in loaded
            assert wire.opens == 0 and backend.reads == int(target == "A")
            assert widget.consents.grant_info(
                "openai", URL, data, capability=kind, scope=ConsentScope.library(), policy_version=2
            )["active"]
        finally:
            bridge.window.tabs.close()
            sessions.close()


@pytest.mark.parametrize(
    "kind,reason",
    list(itertools.product(("stt", "summary"), ("revoked", "journal", "incomplete"))),
    ids=CASE_IDS["UI_FIX"][6:12],
)
def test_unavailable_session_never_leaves_previous_consent_target(
    app: QApplication, tmp_path: Path, kind: str, reason: str
) -> None:
    with panel(tmp_path, kind) as (widget, backend, wire):
        bridge, sessions, loaded = linked_selection(widget)
        try:
            sessions.setCurrentItem(add_session(sessions, "A"))
            if reason == "revoked":
                widget.consents.revoke_session("C")
            else:
                journal = tmp_path / "deletion-journal"
                journal.mkdir()
                (journal / ("C.json" if reason == "journal" else ".tmp-other")).write_bytes(b"{}")
            # This callback precedes the main details update; it must not raise.
            sessions.setCurrentItem(add_session(sessions, "C"))
            assert loaded[-2:] == ["C", "details:C"]
            assert widget._selected_session == "C"
            for control in widget.controls.values():
                assert "C" in control.scope_info.text()
                assert not control.allow.isEnabled() and not control.revoke.isEnabled()
                assert (
                    "확인 중" if reason == "incomplete" else "삭제 진행 중"
                ) in control.scope_info.text()
                control.allow.click()
            assert (
                widget.consents._db.execute("SELECT COUNT(*) FROM security_grants_v2").fetchone()[0]
                == 0
            )
            assert backend.reads == 0 and wire.opens == 0
        finally:
            bridge.window.tabs.close()
            sessions.close()


@pytest.mark.parametrize(
    "kind,state",
    list(itertools.product(("stt", "summary"), ("active", "revoked", "previous", "expired"))),
    ids=CASE_IDS["UI_FIX"][12:20],
)
def test_scope_labels_distinguish_inactive_grants_and_local_expiry(
    app: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, state: str
) -> None:
    import recoryn.ui.privacy as privacy

    class LocalDateTime(datetime):
        def astimezone(self, tz: Any = None) -> datetime:
            return super().astimezone(tz or timezone(timedelta(hours=5, minutes=45)))

    # Simulate a non-UTC user locale without changing OS/process timezone settings.
    monkeypatch.setattr(privacy, "datetime", LocalDateTime)
    clock = [1_700_000_000.0]
    data = "audio" if kind == "stt" else "transcript"
    if state == "previous":
        with ConsentStore(tmp_path / "scope.db", clock=lambda: clock[0]) as old:
            old.grant(
                "openai",
                URL,
                data,
                capability=kind,
                scope=ConsentScope.session("A"),
                policy_version=2,
            )
    with panel(
        tmp_path, kind, clock=lambda: clock[0], existing_grants=int(state == "previous")
    ) as (widget, backend, wire):
        widget.select_session("A")
        control = widget.controls[kind]
        seed(widget, kind, (ConsentScope.library(),))
        if state != "previous":
            control.allow.click()
        if state == "revoked":
            control.revoke.click()
        elif state == "expired":
            clock[0] += 3600
        widget._show_scope(kind)
        text = control.scope_info.text()
        assert "이 세션만: A" in text and "정책 version 2" in text and kind in text
        assert ("전체 허용 유지 중" in text) == (state != "expired")
        local_deadline = "2023-11-15T04:58:20+05:45"
        if state == "active":
            assert "만료 " + local_deadline in text
            assert "+00:00" not in text
        else:
            assert "만료 " not in text
            assert {"revoked": "철회됨", "previous": "이전 실행", "expired": "만료됨"}[
                state
            ] in text
        assert wire.opens == 0 and backend.reads == 0


@pytest.mark.parametrize("kind", ("stt", "summary"), ids=CASE_IDS["UI_FIX"][20:22])
def test_navigation_returns_while_remote_write_still_holds_policy(
    app: QApplication, tmp_path: Path, kind: str
) -> None:
    entered, release, returned = threading.Event(), threading.Event(), threading.Event()
    errors: list[BaseException] = []
    with panel(tmp_path, kind) as (widget, backend, wire):
        bridge, sessions, loaded = linked_selection(widget)
        sessions.setCurrentItem(add_session(sessions, "A"))
        control = widget.controls[kind]
        control.allow.click()
        if kind == "summary":
            seed(widget, kind, (ConsentScope.session("A"),))
            widget.consents.grant(
                "openai",
                URL,
                "context",
                capability=kind,
                scope=ConsentScope.session("A"),
                policy_version=2,
            )
        execution = widget.prepare_execution(kind, "A", threading.Event())
        factory = execution.context.reservation_factory
        assert execution.gateway is not None and factory is not None
        data = "audio" if kind == "stt" else "transcript"
        reservation = factory("openai", URL, data, 1)
        original_write = wire.write

        def stalled_write(data: bytes, timeout: float) -> None:
            entered.set()
            if not release.wait(5):
                raise TimeoutError("test cleanup deadline")
            original_write(data, timeout)

        wire.write = stalled_write

        def send() -> None:
            try:
                assert execution.gateway is not None
                execution.gateway.request("openai", URL, data, b"x", reservation_id=reservation)
            except BaseException as error:
                errors.append(error)

        worker = threading.Thread(target=send)
        worker.start()
        assert entered.wait(5)
        forced = threading.Event()

        def watchdog() -> None:
            if not returned.wait(0.5):
                forced.set()
                release.set()

        guard = threading.Thread(target=watchdog)
        guard.start()
        try:
            sessions.setCurrentItem(add_session(sessions, "B"))
            # Causal oracle: navigation completes while transport is still held.
            returned.set()
            assert not release.is_set() and not forced.is_set()
            assert loaded[-2:] == ["B", "details:B"]
            assert "확인 중" in control.scope_info.text()
            assert widget._selected_session == "B"
        finally:
            returned.set()
            release.set()
            worker.join(5)
            guard.join(5)
            bridge.window.tabs.close()
            sessions.close()
        assert not worker.is_alive() and not errors


@pytest.mark.parametrize(
    "kind,change",
    list(itertools.product(("stt", "summary"), ("scope", "policy", "model"))),
    ids=CASE_IDS["UI_FIX"][22:28],
)
def test_result_identity_is_separate_from_fresh_consent_bindings(
    app: QApplication, tmp_path: Path, kind: str, change: str
) -> None:
    with panel(tmp_path, kind) as (widget, backend, wire):
        widget.select_session("A")
        control = widget.controls[kind]
        seed(widget, kind, (ConsentScope.session("A"), ConsentScope.library()))
        if kind == "summary":
            for scope in (ConsentScope.session("A"), ConsentScope.library()):
                widget.consents.grant(
                    "openai", URL, "context", capability=kind, scope=scope, policy_version=2
                )
        first = widget.prepare_execution(kind, "A", threading.Event())
        assert first.gateway is not None
        first_binding = first.gateway.expected_grants[0]
        if change == "scope":
            control.scope.setCurrentIndex(1)
        elif change == "policy":
            widget.consents.advance_policy_version(3)
            for data in ("audio",) if kind == "stt" else ("transcript", "context"):
                widget.consents.grant(
                    "openai",
                    URL,
                    data,
                    capability=kind,
                    scope=ConsentScope.session("A"),
                    policy_version=3,
                )
        else:
            control.model.setText("different-model")
        if change == "model":
            assert widget.config_key(kind, session_id="A") != first.config_key
        else:
            second = widget.prepare_execution(kind, "A", threading.Event())
            assert second.config_key == first.config_key
            assert second.gateway is not None
            second_binding = second.gateway.expected_grants[0]
            assert second_binding != first_binding
            if change == "policy":
                assert second_binding.request.policy_version == 3
                with pytest.raises(SecurityError, match="CONSENT_POLICY_CHANGED"):
                    widget.consents.validate_binding(first_binding)
            else:
                assert second_binding.scope == ConsentScope.library()
                assert first_binding.scope == ConsentScope.session("A")
        assert wire.opens == 0


@pytest.mark.parametrize("change", ("scope", "policy"), ids=CASE_IDS["UI_FIX"][28:30])
def test_permission_only_change_sends_only_new_stream_chunk(
    app: QApplication, tmp_path: Path, change: str
) -> None:
    from recoryn.app.ai import AIService
    from recoryn.app.recording import RecordingService
    from recoryn.content import ContentStore
    from recoryn.domain import AudioFormat, PCMBlock
    from recoryn.providers import STTResult
    from recoryn.storage import Library

    fmt = AudioFormat(1000, 1)
    samples = b"\0\0" * 400 + b"\0\x40" * 200 + b"\0\0" * 400
    sent: list[bytes] = []

    class FakeSTT:
        def transcribe(self, request: Any, context: Any = None) -> STTResult:
            with wave.open(str(request.audio_path), "rb") as audio:
                sent.append(audio.readframes(audio.getnframes()))
            return STTResult("fake", "fake-model", (), True)

    def completed(service: AIService, job_id: str) -> None:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            state = service.jobs.get(job_id).state.value
            if state in {"SUCCEEDED", "FAILED", "CANCELLED", "BLOCKED"}:
                assert state == "SUCCEEDED"
                return
            time.sleep(0.005)
        pytest.fail("fake job did not complete")

    with Library(tmp_path / "media") as library, ContentStore(library) as store:
        recorder = RecordingService(library, {"mic": fmt}, chunk_frames=1000)
        recorder.start()
        sid = recorder.session_id
        service = AIService(library, store)
        try:
            with panel(tmp_path, "stt") as (widget, backend, wire):
                widget.select_session(sid)
                seed(widget, "stt", (ConsentScope.session(sid), ConsentScope.library()))
                first = widget.prepare_execution("stt", sid, threading.Event())

                def seal(stamp: int) -> None:
                    assert recorder.submit(
                        PCMBlock(
                            sid,
                            "mic",
                            recorder.epochs["mic"],
                            0,
                            fmt,
                            1000,
                            samples,
                            stamp,
                            stamp,
                            device_frame_position=0,
                        )
                    )
                    recorder.pause()

                seal(1_000_000_000)
                completed(
                    service,
                    service.transcribe(
                        sid, FakeSTT(), config_key=first.config_key, provisional=True
                    ),
                )
                assert len(sent) == 1
                recorder.resume()
                seal(3_000_000_000)
                if change == "scope":
                    widget.controls["stt"].scope.setCurrentIndex(1)
                else:
                    widget.consents.advance_policy_version(3)
                    seed(widget, "stt", (ConsentScope.session(sid),), version=3)
                second = widget.prepare_execution("stt", sid, threading.Event())
                completed(
                    service,
                    service.transcribe(
                        sid, FakeSTT(), config_key=second.config_key, provisional=True
                    ),
                )
                # Two input chunks, exactly two calls in total, never 1 + 2.
                assert len(sent) == 2
                assert first.config_key == second.config_key
                assert first.gateway.expected_grants != second.gateway.expected_grants
                assert wire.opens == 0
        finally:
            service.close()
            recorder.stop(timeout=60)


@pytest.mark.parametrize(
    "kind,state,action",
    list(
        itertools.product(
            ("stt", "summary"),
            ("active", "revoked", "previous", "expired", "none"),
            ("refresh", "budget"),
        )
    ),
    ids=G02B_CASE_IDS["STATUS"],
)
def test_nonissuing_action_reports_grant_facts_without_binding(
    app: QApplication, tmp_path: Path, kind: str, state: str, action: str
) -> None:
    clock = [1_700_000_000.0]
    data = "audio" if kind == "stt" else "transcript"
    if state == "previous":
        with ConsentStore(tmp_path / "scope.db", clock=lambda: clock[0]) as old:
            old.grant(
                "openai",
                URL,
                data,
                capability=kind,
                scope=ConsentScope.session("A"),
                policy_version=2,
            )
    with panel(
        tmp_path, kind, clock=lambda: clock[0], existing_grants=int(state == "previous")
    ) as (widget, backend, wire):
        widget.select_session("A")
        control = widget.controls[kind]
        if state in ("active", "revoked", "expired"):
            control.allow.click()
        if state == "revoked":
            control.revoke.click()
        if state == "expired":
            clock[0] += 3600
        (control.refresh if action == "refresh" else control.apply_budget).click()
        word = {
            "active": "동의 활성",
            "revoked": "철회됨",
            "previous": "이전 실행",
            "expired": "만료됨",
            "none": "동의 없음",
        }[state]
        assert word in control.status.text()
        assert ("만료 " in control.scope_info.text()) == (state == "active")
        assert not control.status.text().startswith("거부됨")
        assert (
            widget.consents._db.execute("SELECT COUNT(*) FROM security_sessions").fetchone()[0] == 0
        )
        assert backend.reads == 0 and wire.opens == 0


@pytest.mark.parametrize(
    "kind,scope_kind,state,phase",
    list(
        itertools.product(
            ("stt", "summary"),
            ("session", "library"),
            ("active", "revoked", "none", "expired", "deleted"),
            ("stable", "pending"),
        )
    ),
    ids=G02B_CASE_IDS["GAP"],
)
def test_fixed_request_uses_its_grant_across_selection_gap(
    app: QApplication, tmp_path: Path, kind: str, scope_kind: str, state: str, phase: str
) -> None:
    clock = [1000.0]
    with panel(tmp_path, kind, clock=lambda: clock[0]) as (widget, backend, wire):
        bridge, sessions, _ = linked_selection(widget)
        try:
            sessions.setCurrentItem(add_session(sessions, "R"))
            selected = (
                ConsentScope.session("R") if scope_kind == "session" else ConsentScope.library()
            )
            opposite = (
                ConsentScope.library() if scope_kind == "session" else ConsentScope.session("R")
            )
            data_types = ("audio",) if kind == "stt" else ("transcript", "context")
            for scope in (opposite,) if state == "none" else (selected, opposite):
                for data in data_types:
                    widget.consents.grant(
                        "openai", URL, data, capability=kind, scope=scope, policy_version=2
                    )
            if state == "revoked":
                for data in data_types:
                    widget.consents.revoke(
                        "openai", URL, data, capability=kind, scope=selected, policy_version=2
                    )
            elif state == "expired":
                clock[0] += 3600
            elif state == "deleted":
                widget.consents.revoke_session("R")
            sessions.setCurrentItem(add_session(sessions, "A"))
            control = widget.controls[kind]
            control.scope.setCurrentIndex(int(scope_kind == "library"))
            if phase == "pending":
                sessions.clear()
                add_session(sessions, "R")  # A disappeared; no selected row before queued settle.
                assert widget._selection_pending and widget._selected_session is None
                assert not control.allow.isEnabled() and not control.revoke.isEnabled()
                with pytest.raises(SecurityError, match="CONSENT_REQUIRED"):
                    widget._selected_scope(kind)  # screen-based action remains fail closed
            if state == "active":
                execution = widget.prepare_execution(kind, "R", threading.Event())
                assert execution.gateway is not None and execution.gateway.session_id == "R"
                assert all(
                    binding.scope == selected and binding.request.session_id == "R"
                    for binding in execution.gateway.expected_grants
                )
                assert backend.reads == 1
            else:
                expected = "SESSION_REVOKED" if state == "deleted" else "CONSENT_REQUIRED"
                with pytest.raises(SecurityError, match=expected):
                    widget.prepare_execution(kind, "R", threading.Event())
                assert backend.reads == 0
            assert wire.opens == 0
        finally:
            app.processEvents()
            bridge.window.tabs.close()
            sessions.close()


@pytest.mark.parametrize(
    "kind,action",
    list(
        itertools.product(
            ("stt", "summary"),
            ("delete_key", "revoke_library", "budget", "settle", "grant_session", "revoke_session"),
        )
    ),
    ids=G02B_CASE_IDS["DELETE"],
)
def test_deleted_selection_preserves_unrelated_privacy_controls(
    app: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, action: str
) -> None:
    with panel(tmp_path, kind) as (widget, backend, wire):
        data = seed(widget, kind, (ConsentScope.session("A"), ConsentScope.library()))
        removed_keys: list[str] = []
        monkeypatch.setattr(backend, "delete", removed_keys.append)
        widget.consents.revoke_session("C")
        widget.select_session("C")
        control = widget.controls[kind]
        assert control.isEnabled() and control.scope.isEnabled()
        assert not control.allow.isEnabled() and not control.revoke.isEnabled()
        assert "삭제 진행 중" in control.scope_info.text()
        if action == "delete_key":
            assert control.delete_key.isEnabled()
            control.delete_key.click()
            assert len(removed_keys) == 1
        elif action == "revoke_library":
            control.scope.setCurrentIndex(1)
            assert control.allow.isEnabled() and control.revoke.isEnabled()
            assert "삭제 진행 중" in control.scope_info.text()
            control.revoke.click()
        elif action == "budget":
            control.total.setValue(2)
            assert control.apply_budget.isEnabled()
            control.apply_budget.click()
            assert widget.ledger.snapshot("openai")["limit"] == 2_000_000
        elif action == "settle":
            reservation = widget.ledger.reserve("openai", "pending", 1000, 1_000_000)
            widget.ledger.mark_unknown(reservation)
            control.refresh.click()
            control.actual.setValue(0.0005)
            control.confirm_actual.setChecked(True)
            assert control.settle.isEnabled()
            control.settle.click()
            balance = widget.ledger.snapshot("openai")
            assert balance["confirmed"] == 500 and balance["unknown_exposure"] == 0
        else:
            before = [
                tuple(row)
                for row in widget.consents._db.execute(
                    "SELECT * FROM security_grants_v2 ORDER BY scope_kind,scope_id"
                )
            ]
            (control.allow if action == "grant_session" else control.revoke).click()
            assert [
                tuple(row)
                for row in widget.consents._db.execute(
                    "SELECT * FROM security_grants_v2 ORDER BY scope_kind,scope_id"
                )
            ] == before
        info = widget.consents.grant_info(
            "openai", URL, data, capability=kind, scope=ConsentScope.library(), policy_version=2
        )
        assert info and info["active"] == (action not in ("delete_key", "revoke_library"))
        if info["active"]:
            control.scope.setCurrentIndex(1)
        with pytest.raises(SecurityError, match="SESSION_REVOKED"):
            widget.prepare_execution(kind, "C", threading.Event())
        assert backend.reads == 0 and wire.opens == 0


@pytest.mark.parametrize("kind", ("stt", "summary"), ids=G02B_CASE_IDS["CHECKING"])
def test_busy_consent_view_does_not_claim_transmission_is_blocked(
    app: QApplication, tmp_path: Path, kind: str
) -> None:
    held, release = threading.Event(), threading.Event()
    with panel(tmp_path, kind) as (widget, backend, wire):

        def hold() -> None:
            with widget.consents.coordinator.lock:
                held.set()
                release.wait(5)

        worker = threading.Thread(target=hold)
        worker.start()
        assert held.wait(5)
        try:
            widget.select_session("A")
            text = widget.controls[kind].scope_info.text()
            assert "동의 정보 확인 중" in text and "전송 불가" not in text
            assert not release.is_set()
        finally:
            release.set()
            worker.join(5)
        assert not worker.is_alive()
        assert backend.reads == 0 and wire.opens == 0
