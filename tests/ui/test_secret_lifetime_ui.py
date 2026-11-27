"""GS05 actual UI entries, worker boundaries and shared offscreen migration helpers."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from itertools import product
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from recoryn.security import ConsentStore, CostLedger, SecurityError
from recoryn.ui.privacy import PrivacyPanel, PrivacyReply
from tests.property.test_secret_lifetime_case_space import execution_audit as execution_audit

pytestmark = pytest.mark.ui
_CLOSED_UI_STORES: tuple[tuple[str, bytes], ...] = ()
_TEMPLATE_UI_EXECUTION = ""


@pytest.fixture(scope="module", autouse=True)
def closed_ui_store(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    global _CLOSED_UI_STORES, _TEMPLATE_UI_EXECUTION
    source = tmp_path_factory.mktemp("gs05-empty-ui")
    with (
        ConsentStore(source / "privacy.db", clock=lambda: 1000) as policy,
        CostLedger(source / "privacy.db", clock=lambda: 1000) as ledger,
    ):
        witness = ledger._witness
        _TEMPLATE_UI_EXECUTION = policy.execution_id
        assert policy._db.execute("SELECT COUNT(*) FROM security_grants_v2").fetchone()[0] == 0
        assert (
            ledger._db.execute("SELECT COUNT(*) FROM security_cost_requests_v2").fetchone()[0] == 0
        )
    assert not (source / "privacy.db-wal").exists()
    _CLOSED_UI_STORES = tuple(
        (path.name, path.read_bytes()) for path in (source / "privacy.db", witness)
    )
    try:
        yield
    finally:
        _CLOSED_UI_STORES = ()
        _TEMPLATE_UI_EXECUTION = ""


def spin_privacy(predicate: Callable[[], bool], timeout: float = 5) -> None:
    app = QApplication.instance()
    assert app is not None
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        app.processEvents()
        if predicate():
            app.processEvents()
            if predicate():
                return
        time.sleep(0.001)
    raise AssertionError("privacy worker/Qt completion did not reach its bounded fixture gate")


def settle_privacy(panel: Any, timeout: float = 5) -> None:
    spin_privacy(lambda: panel.backend.idle and not any(panel._view_pending.values()), timeout)
    # A scope query intentionally tries its lock without waiting. If setup held
    # that lock, its first result may be CHECKING after all work has exited.
    # Drive one real retry; persistent journal uncertainty remains CHECKING.
    if not panel._closed and any(
        view.scope.get("state") == "checking" for view in panel._views.values()
    ):
        panel._retry_scope_views()
        spin_privacy(lambda: panel.backend.idle and not any(panel._view_pending.values()), timeout)


def prepare_privacy(
    panel: Any, kind: str, session_id: str, cancel: threading.Event | None = None
) -> Any:
    intent = panel.capture_execution(kind, session_id, cancel or threading.Event())
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(panel.backend.prepare_execution, intent)
        spin_privacy(future.done)
        return future.result()


def privacy_context(panel: Any, kind: str, cancel: threading.Event, *, session_id: str) -> Any:
    return prepare_privacy(panel, kind, session_id, cancel).context


def privacy_gateway(panel: Any, session_id: str, *, kind: str = "summary") -> Any:
    intent = panel.capture_execution(kind, session_id, threading.Event())
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(panel.backend.prepare_gateway, intent)
        spin_privacy(future.done)
        return future.result()


def privacy_action(panel: Any, kind: str, action: str) -> None:
    panel._action(kind, action)
    settle_privacy(panel)


def privacy_click(button: Any) -> None:
    owner = button.parentWidget()
    while owner is not None and not isinstance(owner, PrivacyPanel):
        owner = owner.parentWidget()
    if owner is not None and not owner._closed and not owner._selection_pending:
        settle_privacy(owner)
    button.click()
    if owner is not None and not owner._closed:
        settle_privacy(owner)


def close_privacy(panel: Any) -> None:
    backend = panel.backend
    backend.begin_shutdown()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(backend.await_shutdown)
        spin_privacy(future.done, 6)
        assert future.result(), "native/policy workers still own the stores"
    panel.close()
    app = QApplication.instance()
    assert app is not None
    app.processEvents()


@contextmanager
def ui_world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str = "stt") -> Iterator[Any]:
    from tests.ui.test_cost_cap_ui import fixture_panel_catalog
    from tests.unit.test_secret_lifetime import secret_world

    app = QApplication.instance() or QApplication([])
    for name, content in _CLOSED_UI_STORES:
        target = tmp_path / name
        assert not target.exists(), "each UI row owns its DB and witness"
        target.write_bytes(content)
    with ConsentStore(tmp_path / "privacy.db", clock=lambda: 1000) as policy:
        assert policy.execution_id != _TEMPLATE_UI_EXECUTION
        with secret_world(policy, 0 if kind == "stt" else 2) as world:
            with CostLedger(policy.db_path, clock=lambda: 1000) as ledger:
                panel = PrivacyPanel(policy, ledger, world.vault, gateway=world.gateway)
                world._ui_ledger = ledger
                panel.backend.credentials = world.credentials
                panel._confirm_proposal = lambda proposal: True
                panel.select_session(world.request.session_id)
                control = panel.controls[kind]
                control.provider.setCurrentIndex(control.provider.findData("openai"))
                control.endpoint.setText(world.route[3])
                control.model.setText("fixture")
                control.context_window.setValue(100_000)
                control.period_start.setText("1970-01-01T00:00:00+00:00")
                control.period_end.setText("2100-01-01T00:00:00+00:00")
                control.total.setValue(1)
                control.per_request.setValue(0.1)
                fixture_panel_catalog(panel, monkeypatch)
                privacy_action(panel, kind, "budget")
                world.auth = world.credentials.capture_binding(world.auth.ref.target, kind)
                world.gateway.auth_binding = world.auth
                try:
                    yield world, panel
                finally:
                    close_privacy(panel)
                    app.processEvents()


@contextmanager
def ui_entry_spy(
    world: Any, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[list[str], list[str]]]:
    gui = threading.get_ident()
    forbidden: list[str] = []
    worker: list[str] = []

    class LockProbe:
        def __init__(self, lock: Any) -> None:
            self.lock = lock

        def acquire(self, *args: Any, **kwargs: Any) -> bool:
            if threading.get_ident() == gui:
                forbidden.append("coordinator")
                if kwargs.get("blocking") is False or args == (False,):
                    return False
                raise SecurityError("TASK_FAILED")
            worker.append("coordinator-enter")
            return bool(self.lock.acquire(*args, **kwargs))

        def release(self) -> None:
            self.lock.release()
            worker.append("coordinator-exit")

        def __enter__(self) -> None:
            self.acquire()

        def __exit__(self, *args: Any) -> None:
            self.release()

    read, write, delete = world.backend.read, world.backend.write, world.backend.delete

    def native(name: str, operation: Any) -> Any:
        def observed(*args: Any) -> Any:
            if threading.get_ident() == gui:
                forbidden.append(name)
                raise SecurityError("TASK_FAILED")
            worker.append(name)
            return operation(*args)

        return observed

    with monkeypatch.context() as spy:
        for coordinator in (world.policy.coordinator, world._ui_ledger.coordinator):
            spy.setattr(coordinator, "lock", LockProbe(coordinator.lock))
        spy.setattr(world.backend, "read", native("native-read", read))
        spy.setattr(world.backend, "write", native("native-write", write))
        spy.setattr(world.backend, "delete", native("native-delete", delete))
        yield forbidden, worker


def security_entry(panel: Any, kind: str, entry: int) -> None:
    control = panel.controls[kind]
    if entry < 6:
        panel._action(kind, ("grant", "budget", "refresh", "reset_clock", "adopt", "settle")[entry])
    elif entry == 6:
        panel._show_scope(kind)
        panel.select_session("gs05-ui-selected-other")
        panel._retry_scope_views()
    elif entry == 7:
        panel._cost_policy(kind)
        panel._mode_changed(kind)
        panel._request_currency(kind)
        control.period_end.setText("2100-01-02T00:00:00+00:00")
    elif entry == 8:
        raise AssertionError("entry 8 is an actual constructor inside the delay gate")
    else:
        nonce = "GS05-command-success" if entry == 9 else "GS05-command-failure"
        panel._command_nonces[kind] = nonce
        panel._on_work_ready(
            PrivacyReply(
                kind,
                nonce,
                panel._selection_generation,
                "committed",
                error_code=None if entry == 9 else "VAULT_WRITE_FAILED",
            )
        )


V_CASES = [
    pytest.param("GS05-V-" + "-".join(map(str, row)), *row, id="GS05-V-" + "-".join(map(str, row)))
    for row in product(range(11), range(2), range(2), range(2))
]


@pytest.mark.parametrize("case_id,entry,kind_index,generation,delay", V_CASES)
def test_all_security_entries(
    case_id: str,
    entry: int,
    kind_index: int,
    generation: int,
    delay: int,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kind = ("stt", "summary")[kind_index]
    with ui_world(tmp_path, monkeypatch, kind) as (world, panel), ExitStack() as extras:
        entered, release = threading.Event(), threading.Event()
        heartbeat, recorder_control = [], []
        replies: list[Any] = []
        panel.work_ready.connect(replies.append)

        def native_pause() -> None:
            assert not getattr(world.policy.coordinator._local, "depth", 0)
            entered.set()
            assert release.wait(3)

        def coordinator_pause() -> None:
            with world.policy.coordinator.hold():
                entered.set()
                assert release.wait(3)

        world.backend.reading = native_pause
        with ui_entry_spy(world, monkeypatch) as (forbidden, worker):
            with ThreadPoolExecutor(max_workers=1) as pool:
                delayed = pool.submit(coordinator_pause if delay else world.send)
                try:
                    assert entered.wait(3)
                    before = len(worker)
                    old_generation = panel._selection_generation
                    try:
                        if entry == 8:
                            panel = PrivacyPanel(
                                world.policy, world._ui_ledger, world.vault, gateway=world.gateway
                            )
                            extras.callback(close_privacy, panel)
                            panel.work_ready.connect(replies.append)
                            old_generation = panel._selection_generation
                        else:
                            security_entry(panel, kind, entry)
                    except SecurityError:
                        if not forbidden:
                            raise
                    assert forbidden == [], "GUI entered a coordinator/native operation"
                    if generation:
                        panel.select_session("GS05-next-selection")
                    QTimer.singleShot(0, lambda: heartbeat.append("tick"))
                    QTimer.singleShot(0, lambda: recorder_control.append("synthetic-stop-ack"))
                    spin_privacy(
                        lambda: bool(heartbeat and recorder_control and len(worker) > before)
                    )
                    assert forbidden == [], case_id
                    assert not delayed.done()
                    if delay:
                        assert panel.backend._active > 0
                        assert "coordinator-enter" in worker[before:]
                    else:
                        spin_privacy(lambda: panel.backend._active == 0)
                        assert "coordinator-exit" in worker[before:], (
                            "native R must not block policy/query lane"
                        )
                    if generation:
                        assert panel._selection_generation != old_generation
                        nonce = panel._command_nonces.get(kind, "old-command")
                        panel._on_work_ready(
                            PrivacyReply(
                                kind, nonce, old_generation, "key", error_code="VAULT_DELETE_FAILED"
                            )
                        )
                        assert panel.controls[kind].status.text() != "VAULT_DELETE_FAILED"
                finally:
                    release.set()
                try:
                    delayed.result(3)
                except SecurityError as error:
                    assert error.code in ("CONSENT_REQUIRED", "PERMIT_REVOKED", "AUTH_REQUIRED")
            settle_privacy(panel)
            assert forbidden == []
            assert heartbeat == ["tick"] and recorder_control == ["synthetic-stop-ack"]


S_CASES = [
    pytest.param(f"GS05-S-{outcome}-{view}", outcome, view, id=f"GS05-S-{outcome}-{view}")
    for outcome, view in product(range(4), range(4))
]


@pytest.mark.parametrize("case_id,outcome,view", S_CASES)
def test_save_admission(
    case_id: str, outcome: int, view: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from recoryn.security.credentials import CredentialTarget
    from tests.unit.test_secret_lifetime import K_B

    with ui_world(tmp_path, monkeypatch) as (world, panel):
        control = panel.controls["stt"]
        entered, release = threading.Event(), threading.Event()
        callbacks: list[Any] = []
        panel.work_ready.connect(callbacks.append)
        write = world.backend.write

        def blocked_write(*args: Any) -> None:
            entered.set()
            assert release.wait(3)
            write(*args)

        world.backend.write = blocked_write
        if outcome == 0:
            world.credentials._pending_limit = 1
            other = CredentialTarget("openai", "https://capacity.gs05.invalid/stt")
            assert world.credentials.try_enqueue_key_change(
                other,
                "save",
                K_B,
                command_nonce="capacity",
                selection_generation=0,
                done=lambda value: None,
            )
            assert entered.wait(3)
        if outcome == 2:
            world.backend.write_error = True
        control.key.setText(K_B)
        with ui_entry_spy(world, monkeypatch) as (forbidden, worker):
            try:
                panel._action("stt", "save")
                command_nonce = panel._command_nonces["stt"]
                command_generation = panel._selection_generation
                if outcome == 0:
                    assert control.key.text() == K_B
                    assert control.status.text() == "RESOURCE_EXHAUSTED"
                    assert not world.backend.writes
                    assert not world.credentials._queues.get(world.auth.ref.target)
                else:
                    assert control.key.text() == "", case_id
                    assert entered.wait(3)
                    assert world.credentials._pending == 1
                    assert not any(reply.tag == "key" for reply in callbacks)
                    if view == 1:
                        panel.select_session("GS05-other-selection")
                    elif view == 2:
                        panel._action("stt", "refresh")
                    elif view == 3:
                        panel.close()
                    assert not world.credentials.idle
            finally:
                release.set()
            spin_privacy(lambda: world.credentials.idle)
            if outcome:
                spin_privacy(
                    lambda: any(
                        reply.kind == "stt"
                        and reply.tag == "key"
                        and reply.nonce == command_nonce
                        and reply.generation == command_generation
                        for reply in callbacks
                    )
                )
            if not panel._closed:
                settle_privacy(panel)
            assert forbidden == []
            if outcome:
                assert control.key.text() == ""
                assert len(world.backend.writes) == 1
                if outcome == 2 and view == 0:
                    assert control.status.text() == "VAULT_WRITE_FAILED"
                elif view in (1, 2, 3):
                    assert control.status.text() != "VAULT_WRITE_FAILED"
                assert all(K_B not in repr(reply) for reply in callbacks)
                if outcome == 3 and view != 3:
                    # A new explicit consent/binding may try the failed read;
                    # it cannot reuse the pre-change permission/ref.
                    def next_request() -> bytes:
                        world.policy.grant(
                            world.route[0],
                            world.route[3],
                            world.route[2],
                            capability="stt",
                            scope=world.scope,
                            policy_version=world.request.policy_version,
                        )
                        bindings = world.policy.capture_bindings(
                            world.route[0],
                            world.route[3],
                            (world.route[2],),
                            scope=world.scope,
                            request=world.request,
                        )
                        from recoryn.security import Gateway

                        root = Gateway(
                            world.policy,
                            ledger=world.ledger,
                            transport=world.wire,
                            expected_grants=bindings,
                            auth_binding=world.credentials.capture_binding(
                                world.auth.ref.target, "stt"
                            ),
                        )
                        root._clock = world.clock
                        world.gateway = root.for_session(
                            world.request.session_id,
                            capability="stt",
                            scope=world.scope,
                            policy_version=world.request.policy_version,
                        )
                        world.backend.error = OSError("GS05-PRIVATE-NEXT-READ-CANARY")
                        return world.send()

                    with ThreadPoolExecutor(max_workers=1) as pool:
                        with pytest.raises(SecurityError, match="^VAULT_READ_FAILED$") as failure:
                            pool.submit(next_request).result(3)
                    assert failure.value.outcome_known and world.wire.opens == 0
                    assert forbidden == []


U_CASES = [
    pytest.param(
        f"GS05-U-{action}-{generation}", action, generation, id=f"GS05-U-{action}-{generation}"
    )
    for action, generation in product(range(8), range(2))
]


@pytest.mark.parametrize("case_id,action,generation", U_CASES)
def test_existing_ui_bounds(
    case_id: str, action: int, generation: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kind = "summary" if action == 1 else "stt"
    with ui_world(tmp_path, monkeypatch, kind) as (world, panel):
        old_generation = panel._selection_generation
        with ui_entry_spy(world, monkeypatch) as (forbidden, worker):
            if action in (0, 1):
                intent = panel.capture_execution(kind, world.request.session_id, threading.Event())
                with ThreadPoolExecutor(max_workers=1) as pool:
                    task = pool.submit(panel.backend.prepare_execution, intent)
                    if generation:
                        panel.select_session("GS05-new-selection")
                    spin_privacy(task.done)
                    prepared = task.result()
                    assert dict(prepared.context.headers) == {} and world.backend.reads == 0
            elif action in (2, 3):
                panel.controls[kind].key.setText("GS05-FAKE-CANARY-B")
                panel._action(kind, "save" if action == 2 else "delete")
            elif action == 4:
                panel._action(kind, "revoke")
            elif action == 5:
                panel.controls[kind].model.setText("changed-model")
            elif action == 6:
                panel.close()
            else:
                panel._command_nonces[kind] = "completion"
                if generation:
                    panel.select_session("GS05-new-selection")
                panel._on_work_ready(
                    PrivacyReply(
                        kind, "completion", old_generation, "key", error_code="VAULT_WRITE_FAILED"
                    )
                )
                assert (panel.controls[kind].status.text() == "VAULT_WRITE_FAILED") is (
                    not generation
                )
            if generation and action not in (0, 1, 7):
                panel.select_session("GS05-new-selection")
            if not panel._closed:
                settle_privacy(panel)
            assert forbidden == [], case_id
            assert world.backend.reads == 0


@pytest.mark.parametrize(
    "case_id,row",
    [pytest.param(f"GS05-T-{row:02}", row, id=f"GS05-T-{row:02}") for row in (13, 14, 15, 17)],
)
def test_control_during_read(
    case_id: str, row: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if row == 17:
        from recoryn.security import Gateway
        from tests.unit.test_secret_lifetime import key_command

        with ui_world(tmp_path, monkeypatch) as (world, panel):
            entered, release = threading.Event(), threading.Event()
            write = world.backend.write

            def pending_write(*args: Any) -> None:
                entered.set()
                assert release.wait(3)
                write(*args)

            world.backend.write = pending_write
            done, result = key_command(world, "save")
            app_replies: list[Any] = []
            panel.work_ready.connect(app_replies.append)
            try:
                assert entered.wait(3)
                panel._action("stt", "grant")
                nonce = panel._command_nonces["stt"]
                spin_privacy(
                    lambda: any(
                        reply.nonce == nonce
                        and (reply.error_code is not None or reply.tag == "committed")
                        for reply in app_replies
                    )
                )
                current_grant = world.policy.grant_info(
                    world.route[0],
                    world.route[3],
                    world.route[2],
                    capability="stt",
                    scope=world.scope,
                    policy_version=world.request.policy_version,
                )
                assert current_grant is not None and not current_grant["active"], (
                    "pending app grant was accepted"
                )
                assert panel.controls["stt"].status.text() == "AUTH_REQUIRED"
                assert not done.is_set() and world.credentials._pending == 1

                def out_of_band() -> None:
                    world.policy.grant(
                        world.route[0],
                        world.route[3],
                        world.route[2],
                        capability="stt",
                        scope=world.scope,
                        policy_version=world.request.policy_version,
                    )
                    bindings = world.policy.capture_bindings(
                        world.route[0],
                        world.route[3],
                        (world.route[2],),
                        scope=world.scope,
                        request=world.request,
                    )
                    root = Gateway(
                        world.policy,
                        ledger=world.ledger,
                        transport=world.wire,
                        expected_grants=bindings,
                        auth_binding=world.credentials.capture_binding(
                            world.auth.ref.target, "stt"
                        ),
                    )
                    root._clock = world.clock
                    gateway = root.for_session(
                        world.request.session_id,
                        capability="stt",
                        scope=world.scope,
                        policy_version=world.request.policy_version,
                    )
                    gateway.request(
                        world.route[0],
                        world.route[3],
                        world.route[2],
                        b"abcdef",
                        reservation_id="reservation",
                    )

                with ThreadPoolExecutor(max_workers=1) as pool:
                    with pytest.raises(SecurityError, match="^AUTH_REQUIRED$"):
                        pool.submit(out_of_band).result(3)
                assert world.backend.reads == world.wire.opens == 0
                assert not world.credentials._tickets
            finally:
                release.set()
            assert done.wait(3) and result[0].error_code is None
        return
    from PySide6.QtWidgets import QMessageBox

    import recoryn.security as security
    from recoryn.app.desktop import DesktopRecorder
    from recoryn.app.recording import RecordingService
    from recoryn.domain import AudioFormat, PCMBlock
    from recoryn.jobs import JobStore
    from recoryn.security import CredentialVault
    from recoryn.storage import Library
    from recoryn.ui.main import MainWindow
    from tests.unit.test_secret_lifetime import MemoryCredentials, secret_world

    app = QApplication.instance() or QApplication([])
    fake = MemoryCredentials()
    monkeypatch.setattr(
        security, "CredentialVault", lambda: CredentialVault(backend=fake, namespace="GS05-CONTROL")
    )
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    source_acks: list[str] = []

    class SyntheticSource:
        def stop(self, timeout: float = 5) -> None:
            source_acks.append("source-ack")

    def forbidden_source(*args: Any) -> None:
        pytest.fail("control fixture must not open a capture device")

    with Library(tmp_path / "library") as library:
        recorder = DesktopRecorder(library, forbidden_source)
        window = MainWindow(library, recorder=recorder)
        window.timer.stop()
        entered, release = threading.Event(), threading.Event()
        try:
            with secret_world(window.consents) as world:
                sid = world.request.session_id
                fmt = AudioFormat(8000, 1)
                recording = RecordingService(
                    library, {"mic": fmt}, session_id=sid, chunk_frames=800
                )
                recorder.recording = recording
                recording.start()
                recorder._sources["mic"] = SyntheticSource()
                assert recording.submit(
                    PCMBlock(
                        sid,
                        "mic",
                        recording.epochs["mic"],
                        0,
                        fmt,
                        80,
                        b"\0\x40" * 80,
                        1_000_000_000,
                        2_000_000_000,
                        device_frame_position=0,
                        clock_quality="DEVICE_CORRELATED",
                    )
                )
                with JobStore(library.db_path) as jobs:
                    job = jobs.create("stt", "GS05-reader")
                    jobs.bind_session(job.job_id, sid)
                    attempt = jobs.claim(job.job_id, "GS05-real-reader")
                    jobs.reader_started(attempt)

                    def read_pause() -> None:
                        assert not getattr(world.policy.coordinator._local, "depth", 0)
                        entered.set()
                        assert release.wait(4)

                    world.backend.reading = read_pause

                    def reader() -> bytes:
                        try:
                            return world.send()
                        finally:
                            jobs.reader_finished(attempt)

                    with ThreadPoolExecutor(max_workers=2) as pool:
                        read = pool.submit(reader)
                        results: list[Any] = []
                        try:
                            assert entered.wait(3)
                            if row == 13:

                                def stop() -> Any:
                                    world.policy.revoke_endpoint(world.route[0], world.route[3])
                                    return recorder.stop()

                                stopped = pool.submit(stop).result(3)
                                assert (
                                    stopped and recorder.capture_progress().control_mode == "ENDED"
                                )
                            elif row == 14:
                                window.refresh_sessions()
                                spin_privacy(
                                    lambda: window.sessions.count() == 1 and not window.busy
                                )
                                window.sessions.setCurrentRow(0)
                                delete = library.delete_session

                                def observe_delete(session_id: str) -> Any:
                                    value = delete(session_id)
                                    results.append(value)
                                    return value

                                monkeypatch.setattr(library, "delete_session", observe_delete)
                                window.delete_selected()
                                spin_privacy(lambda: bool(results) and not window.busy)
                                assert (
                                    results[0]["state"] == "DELETE_PENDING"
                                    and not results[0]["deleted"]
                                )
                            else:
                                pending = pool.submit(library.delete_session, sid).result(3)
                                assert pending["state"] == "DELETE_PENDING"
                                records = library.pending_deletions()
                                generation = next(
                                    item["generation"]
                                    for item in records
                                    if item["session_id"] == sid
                                )
                                retried = pool.submit(window._retry_one, sid, generation).result(3)
                                assert "result" in retried, retried
                                assert retried["result"]["state"] == "DELETE_PENDING"
                            assert source_acks == ["source-ack"], case_id
                            assert not read.done() and jobs.local_reader_active(job.job_id) is True
                            assert recorder._sources == {}
                            assert world.wire.opens == 0
                            if row != 13:
                                assert library.pending_deletions(), (
                                    "durable pending intent must exist before read ACK"
                                )
                        finally:
                            release.set()
                        with pytest.raises(
                            SecurityError, match="^(CONSENT_REQUIRED|SESSION_REVOKED)$"
                        ):
                            read.result(3)
                    assert jobs.local_reader_active(job.job_id) is False
                    recorder.close()
        finally:
            release.set()
            # Actual fixture-owned source/writer ACK also runs on a failed T15;
            # it is cleanup, never credited as the retry control's success.
            if row == 15 and recorder.recording is not None:
                recorder._close_sources()
                recorder.recording.join_writer()
                recorder.recording = None
            window.close()
            spin_privacy(lambda: window._closing)
            window.deleteLater()
            app.processEvents()
