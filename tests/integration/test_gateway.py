"""No live HTTP: controlled transport barriers establish revoke/handoff ordering."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

import pytest

from recoryn.security import (
    ConsentRequest,
    ConsentScope,
    ConsentStore,
    CostLedger,
    Gateway,
    SecurityError,
    SendPermit,
)
from recoryn.security._core import Endpoint
from recoryn.storage import Library
from tests.unit.test_cost_cap import fixture_balance, fixture_reservation, fixture_wire

pytestmark = pytest.mark.integration
URL = "https://api.example.test/v1"


class FakeConnection:
    def __init__(self, response: bytes = b"OK") -> None:
        self.writes: list[bytes] = []
        self.response = response
        self.closed = False
        self.fail_write = False

    def write(self, data: bytes, timeout: float) -> None:
        if self.fail_write:
            raise OSError("B14-PRIVATE-RESPONSE-CANARY")
        self.writes.append(data)

    def read(self, limit: int, timeout: float) -> bytes:
        data, self.response = self.response[:limit], self.response[limit:]
        return data

    def close(self) -> None:
        self.closed = True


class FakeTransport:
    def __init__(self, response: bytes = b"OK") -> None:
        self.connection = FakeConnection(response)
        self.opens = 0

    def open(
        self, endpoint: Endpoint, headers: Mapping[str, str], body_length: int, timeout: float
    ) -> FakeConnection:
        self.opens += 1
        return self.connection


def test_default_gateway_blocks_before_dns(tmp_path: Path) -> None:
    with ConsentStore(tmp_path / "p.sqlite") as policy:
        with pytest.raises(SecurityError, match="CONSENT_REQUIRED"):
            Gateway(policy).request("p", URL, "audio", b"dummy")


@pytest.mark.parametrize("boundary", (1, 2, 3, 4, None))
def test_dispatch_guard_checks_open_each_write_and_final_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: int | None
) -> None:
    calls: list[SendPermit] = []
    transport = FakeTransport()

    @contextmanager
    def guard(permit: SendPermit) -> Iterator[None]:
        calls.append(permit)
        if len(calls) == boundary:
            raise RuntimeError("PRIVATE-OWNER-GUARD-CANARY")
        yield

    db = tmp_path / "guard.sqlite"
    with ConsentStore(db) as policy, CostLedger(db) as ledger:
        policy.grant(
            "p",
            URL,
            "audio",
            capability="stt",
            scope=_fixture_grant_scope(policy),
            policy_version=2,
        )
        reservation = fixture_reservation(
            ledger,
            monkeypatch,
            fixture_wire("p", URL, "audio", b"abcd"),
            60,
            100,
            "guarded-request",
        )
        gateway = _fixture_gateway(
            policy,
            ledger=ledger,
            transport=transport,
            chunk_bytes=2,
            dispatch_guard=guard,
            session_id="source",
        )
        assert gateway.dispatch_guard is guard
        if boundary is None:
            assert gateway.request("p", URL, "audio", b"abcd", reservation_id=reservation) == b"OK"
        else:
            with pytest.raises(SecurityError, match="LOCAL_EXECUTION_UNVERIFIED") as failure:
                gateway.request("p", URL, "audio", b"abcd", reservation_id=reservation)
            assert failure.value.outcome_known is (boundary <= 2)
            assert "PRIVATE" not in str(failure.value)
        assert len(calls) == (boundary if boundary is not None else 4)
        assert all(
            (p.provider_id, p.endpoint, p.data_type, p.session_id, p.reservation_id)
            == ("p", URL, "audio", "source", reservation)
            for p in calls
        )
        assert transport.opens == (0 if boundary == 1 else 1)
        expected_writes = [] if boundary in (1, 2) else [b"ab"] if boundary == 3 else [b"ab", b"cd"]
        assert transport.connection.writes == expected_writes
        assert (
            fixture_balance(ledger)["reserved" if boundary in (1, 2) else "unknown_exposure"] == 60
        )
        assert transport.connection.closed is (boundary != 1)


@pytest.mark.parametrize("boundary", (1, 2))
def test_guard_exit_failure_after_first_write_remains_unknown(
    tmp_path: Path, boundary: int
) -> None:
    calls = 0
    transport = FakeTransport()

    @contextmanager
    def guard(permit: SendPermit) -> Iterator[None]:
        nonlocal calls
        calls += 1
        current = calls
        yield
        if current == boundary:
            raise RuntimeError("PRIVATE-OWNER-EXIT-CANARY")

    with ConsentStore(tmp_path / "guard.sqlite") as policy:
        policy.grant(
            "p",
            URL,
            "audio",
            capability="stt",
            scope=_fixture_grant_scope(policy),
            policy_version=2,
        )
        with pytest.raises(SecurityError, match="LOCAL_EXECUTION_UNVERIFIED") as failure:
            _fixture_gateway(policy, transport=transport, dispatch_guard=guard).request(
                "p", URL, "audio", b"abcd"
            )
        assert failure.value.outcome_known is (boundary == 1)
        assert transport.connection.writes == ([] if boundary == 1 else [b"abcd"])
        assert transport.connection.closed


def test_owner_guard_holds_through_handoff_and_blocks_later_result(tmp_path: Path) -> None:
    owner_lock = threading.RLock()
    write_entered, release_write = threading.Event(), threading.Event()
    revoke_started, revoked = threading.Event(), threading.Event()
    valid = True
    transport = FakeTransport()
    original_write, original_read = transport.connection.write, transport.connection.read
    order: list[str] = []

    @contextmanager
    def guard(permit: SendPermit) -> Iterator[None]:
        with owner_lock:
            if not valid:
                raise RuntimeError("owner revoked")
            yield

    def held_write(data: bytes, timeout: float) -> None:
        write_entered.set()
        assert release_write.wait(5)
        original_write(data, timeout)
        order.append("write")

    def read_after_revoke(limit: int, timeout: float) -> bytes:
        assert revoked.wait(5)
        return original_read(limit, timeout)

    def revoke_owner() -> None:
        nonlocal valid
        revoke_started.set()
        with owner_lock:
            valid = False
            order.append("revoke")
            revoked.set()

    transport.connection.write = held_write  # type: ignore[method-assign]
    transport.connection.read = read_after_revoke  # type: ignore[method-assign]
    with ConsentStore(tmp_path / "guard.sqlite") as policy:
        policy.grant(
            "p",
            URL,
            "audio",
            capability="stt",
            scope=_fixture_grant_scope(policy),
            policy_version=2,
        )
        gateway = _fixture_gateway(policy, transport=transport, dispatch_guard=guard)
        with ThreadPoolExecutor(max_workers=2) as worker:
            request = worker.submit(gateway.request, "p", URL, "audio", b"abcd")
            try:
                assert write_entered.wait(5)
                revoke = worker.submit(revoke_owner)
                assert revoke_started.wait(5)
                assert not revoked.is_set()
            finally:
                release_write.set()
            revoke.result(timeout=5)
            with pytest.raises(SecurityError, match="LOCAL_EXECUTION_UNVERIFIED") as failure:
                request.result(timeout=5)
            assert not failure.value.outcome_known
        assert order == ["write", "revoke"]
        assert transport.connection.writes == [b"abcd"] and transport.connection.closed


@pytest.mark.parametrize("exit_behavior", ("suppress", "raise"))
def test_guard_exit_cannot_hide_failed_handoff_or_unknown_cost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exit_behavior: str
) -> None:
    transport = FakeTransport()
    transport.connection.fail_write = True

    @contextmanager
    def guard(permit: SendPermit) -> Iterator[None]:
        try:
            yield
        except Exception:
            if exit_behavior == "raise":
                raise RuntimeError("PRIVATE-EXIT-CANARY") from None
            # A buggy optional guard must not swallow the write failure.

    db = tmp_path / "guard.sqlite"
    with ConsentStore(db) as policy, CostLedger(db) as ledger:
        policy.grant(
            "p",
            URL,
            "audio",
            capability="stt",
            scope=_fixture_grant_scope(policy),
            policy_version=2,
        )
        reservation = fixture_reservation(
            ledger, monkeypatch, fixture_wire("p", URL, "audio", b"abcd"), 60, 100, "request"
        )
        gateway = _fixture_gateway(policy, ledger=ledger, transport=transport, dispatch_guard=guard)
        with pytest.raises(SecurityError, match="REMOTE_OUTCOME_UNKNOWN") as failure:
            gateway.request("p", URL, "audio", b"abcd", reservation_id=reservation)
        assert not failure.value.outcome_known
        assert fixture_balance(ledger)["unknown_exposure"] == 60
        assert transport.connection.closed


@pytest.mark.parametrize("revoke", ("grant", "session", "execution"))
@pytest.mark.parametrize("boundary", (1, 2))
def test_revoke_before_first_or_second_handoff_blocks_unsent_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, revoke: str, boundary: int
) -> None:
    ready, release = threading.Event(), threading.Event()
    transport = FakeTransport()
    db = tmp_path / "p.sqlite"
    original = Gateway._write
    calls = [0]

    def controlled_write(
        self: Gateway,
        connection: FakeConnection,
        permit: SendPermit,
        data: bytes,
        remaining: Callable[[], float],
        *,
        first: bool,
    ) -> None:
        calls[0] += 1
        if calls[0] == boundary:
            ready.set()
            assert release.wait(5)
        original(self, connection, permit, data, remaining, first=first)

    monkeypatch.setattr(Gateway, "_write", controlled_write)
    with ConsentStore(db) as policy, CostLedger(db) as ledger:
        policy.grant(
            "p",
            URL,
            "audio",
            capability="stt",
            scope=_fixture_grant_scope(policy),
            policy_version=2,
        )
        reservation = fixture_reservation(
            ledger, monkeypatch, fixture_wire("p", URL, "audio", b"abcd"), 60, 100, "r"
        )
        gateway = _fixture_gateway(
            policy, ledger=ledger, transport=transport, chunk_bytes=2, session_id="s"
        )
        with ThreadPoolExecutor(max_workers=1) as worker:
            outcome = worker.submit(
                gateway.request, "p", URL, "audio", b"abcd", reservation_id=reservation
            )
            try:
                assert ready.wait(5)
                if revoke == "session":
                    policy.revoke_session("s")
                elif revoke == "grant":
                    policy.revoke(
                        "p",
                        URL,
                        "audio",
                        capability="stt",
                        scope=ConsentScope.library(),
                        policy_version=2,
                    )
                else:
                    with ConsentStore(db):
                        pass
            finally:
                release.set()
            with pytest.raises(SecurityError) as error:
                outcome.result(timeout=5)
            assert error.value.outcome_known is (boundary == 1)
        assert transport.connection.writes == ([] if boundary == 1 else [b"ab"])
        assert transport.connection.closed
        expected = "reserved" if boundary == 1 else "unknown_exposure"
        assert fixture_balance(ledger)[expected] == 60


def test_write_first_finishes_before_revoke_commit_without_blocking_media_db(
    tmp_path: Path,
) -> None:
    entered, release, revoke_started = threading.Event(), threading.Event(), threading.Event()
    revoke_committed = threading.Event()
    order: list[str] = []
    transport = FakeTransport()
    original_write = transport.connection.write
    original_read = transport.connection.read

    def held_write(data: bytes, timeout: float) -> None:
        entered.set()
        assert release.wait(5)
        original_write(data, timeout)
        order.append("write")

    transport.connection.write = held_write  # type: ignore[method-assign]

    def delayed_response(limit: int, timeout: float) -> bytes:
        assert revoke_committed.wait(5)
        return original_read(limit, timeout)

    transport.connection.read = delayed_response  # type: ignore[method-assign]
    with Library(tmp_path) as library, ConsentStore(tmp_path / "library.sqlite") as policy:
        policy.grant(
            "p",
            URL,
            "audio",
            capability="stt",
            scope=_fixture_grant_scope(policy),
            policy_version=2,
        )
        gateway = _fixture_gateway(policy, transport=transport)

        def revoke() -> None:
            revoke_started.set()
            policy.revoke(
                "p", URL, "audio", capability="stt", scope=ConsentScope.library(), policy_version=2
            )
            order.append("revoke")
            revoke_committed.set()

        with ThreadPoolExecutor(max_workers=2) as pool:
            sent = pool.submit(gateway.request, "p", URL, "audio", b"abcd")
            try:
                assert entered.wait(5)
                # Policy handoff does not hold Library's RLock or an SQLite write tx.
                assert library.create_session("recorder").session_id == "recorder"
                revoked = pool.submit(revoke)
                assert revoke_started.wait(5)
            finally:
                release.set()
            with pytest.raises(SecurityError, match="CONSENT_REQUIRED") as error:
                sent.result(timeout=5)
            assert not error.value.outcome_known
            revoked.result(timeout=5)
        assert order == ["write", "revoke"]


def test_unknown_cost_survives_failed_write_restart_and_session_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "library.sqlite"
    transport = FakeTransport()
    transport.connection.fail_write = True
    with Library(tmp_path) as library, ConsentStore(db) as policy, CostLedger(db) as ledger:
        library.create_session("session")
        policy.grant(
            "p",
            URL,
            "audio",
            capability="stt",
            scope=_fixture_grant_scope(policy),
            policy_version=2,
        )
        reservation = fixture_reservation(
            ledger, monkeypatch, fixture_wire("p", URL, "audio", b"dummy"), 80, 100, "request"
        )
        gateway = _fixture_gateway(policy, ledger=ledger, transport=transport, session_id="session")
        with pytest.raises(SecurityError, match="REMOTE_OUTCOME_UNKNOWN") as error:
            gateway.request("p", URL, "audio", b"dummy", reservation_id=reservation)
        assert not error.value.outcome_known
        assert "CANARY" not in str(error.value)
        policy.revoke_session("session")
        assert library.delete_session("session")["deleted"]
    with CostLedger(db) as restarted:
        assert fixture_balance(restarted)["unknown_exposure"] == 80
        assert fixture_balance(restarted)["available"] == 20
        with pytest.raises(SecurityError):
            restarted.release(reservation)


def test_gateway_limits_safe_headers_cancel_and_response(tmp_path: Path) -> None:
    with ConsentStore(tmp_path / "p.sqlite") as policy:
        policy.grant(
            "p", URL, "text", capability="stt", scope=_fixture_grant_scope(policy), policy_version=2
        )
        transport = FakeTransport(b"oversized")
        gateway = _fixture_gateway(
            policy, transport=transport, max_request_bytes=4, max_response_bytes=2
        )
        with pytest.raises(SecurityError, match="REQUEST_TOO_LARGE"):
            gateway.request("p", URL, "text", b"12345")
        with pytest.raises(SecurityError, match="INVALID_HEADER"):
            gateway.request("p", URL, "text", b"ok", headers={"Host": "attacker.test"})
        cancelled = threading.Event()
        cancelled.set()
        with pytest.raises(SecurityError, match="CANCELLED"):
            gateway.request("p", URL, "text", b"ok", cancel=cancelled)
        assert transport.opens == 0
        with pytest.raises(SecurityError, match="RESPONSE_TOO_LARGE"):
            gateway.request("p", URL, "text", b"ok")
        assert transport.opens == 1 and transport.connection.closed


@pytest.mark.parametrize("failure", ("open", "read", "invalid_response", "close"))
def test_transport_faults_are_safe_and_always_close(
    tmp_path: Path, failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport = FakeTransport()

    def unavailable(*args: object) -> bytes:
        raise OSError("B14-SECRET-TRANSPORT-CANARY")

    if failure == "open":
        monkeypatch.setattr(transport, "open", unavailable)
    elif failure == "read":
        monkeypatch.setattr(transport.connection, "read", unavailable)
    elif failure == "invalid_response":
        monkeypatch.setattr(transport.connection, "read", lambda *args: "not-bytes")
    else:
        monkeypatch.setattr(transport.connection, "close", unavailable)
    with ConsentStore(tmp_path / "security.sqlite") as policy:
        policy.grant(
            "p",
            URL,
            "audio",
            capability="stt",
            scope=_fixture_grant_scope(policy),
            policy_version=2,
        )
        gateway = _fixture_gateway(policy, transport=transport)
        if failure == "close":
            assert gateway.request("p", URL, "audio", b"") == b"OK"
            assert transport.connection.writes == [b""]
            return
        with pytest.raises(SecurityError) as caught:
            gateway.request("p", URL, "audio", b"synthetic")
        assert (
            caught.value.code
            == {
                "open": "TRANSPORT_FAILED",
                "read": "REMOTE_OUTCOME_UNKNOWN",
                "invalid_response": "INVALID_RESPONSE",
            }[failure]
        )
        assert caught.value.outcome_known is (failure == "open")
        assert "CANARY" not in str(caught.value)
        if failure != "open":
            assert transport.connection.closed


@pytest.mark.parametrize("when", ("before", "after"))
@pytest.mark.parametrize("failure", ("timeout", "cancel"))
def test_deadline_and_cancel_preserve_unsent_or_unknown_cost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, when: str, failure: str
) -> None:
    clock = [100.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    transport = FakeTransport()
    cancel = threading.Event()

    def interrupt() -> None:
        if failure == "timeout":
            clock[0] = 200
        else:
            cancel.set()

    original_open = transport.open
    original_write = transport.connection.write

    def opened(
        endpoint: Endpoint, headers: Mapping[str, str], body_length: int, timeout: float
    ) -> FakeConnection:
        result = original_open(endpoint, headers, body_length, timeout)
        if when == "before":
            interrupt()
        return result

    def written(data: bytes, timeout: float) -> None:
        original_write(data, timeout)
        if when == "after":
            interrupt()

    transport.open = opened  # type: ignore[method-assign]
    transport.connection.write = written  # type: ignore[method-assign]
    db = tmp_path / "security.sqlite"
    with ConsentStore(db) as policy, CostLedger(db) as ledger:
        policy.grant(
            "p",
            URL,
            "audio",
            capability="stt",
            scope=_fixture_grant_scope(policy),
            policy_version=2,
        )
        reservation = fixture_reservation(
            ledger, monkeypatch, fixture_wire("p", URL, "audio", b"synthetic"), 80, 100, "r"
        )
        with pytest.raises(SecurityError) as caught:
            _fixture_gateway(policy, ledger=ledger, transport=transport).request(
                "p", URL, "audio", b"synthetic", cancel=cancel, reservation_id=reservation
            )
        expected = "TIMEOUT" if failure == "timeout" else "CANCELLED"
        assert caught.value.code == (expected if when == "before" else "REMOTE_OUTCOME_UNKNOWN")
        assert caught.value.outcome_known is (when == "before")
        assert transport.connection.writes == ([] if when == "before" else [b"synthetic"])
        assert transport.connection.closed
        assert fixture_balance(ledger)["reserved" if when == "before" else "unknown_exposure"] == 80


def test_budget_and_header_failures_never_open_transport(tmp_path: Path) -> None:
    db = tmp_path / "security.sqlite"
    transport = FakeTransport()
    with ConsentStore(db) as policy, CostLedger(db) as ledger:
        policy.grant(
            "p",
            URL,
            "audio",
            capability="stt",
            scope=_fixture_grant_scope(policy),
            policy_version=2,
        )
        with pytest.raises(SecurityError, match="BUDGET_REQUIRED"):
            _fixture_gateway(policy, ledger=ledger, transport=transport).request(
                "p", URL, "audio", b"ok"
            )
        with pytest.raises(SecurityError, match="LEDGER_REQUIRED"):
            _fixture_gateway(policy, transport=transport).request(
                "p", URL, "audio", b"ok", reservation_id="r"
            )
        for headers in (
            {"Authorization": "a", "authorization": "b"},
            {"authorization": "x\r\nleak"},
        ):
            with pytest.raises(SecurityError, match="INVALID_HEADER"):
                _fixture_gateway(policy, transport=transport).request(
                    "p", URL, "audio", b"ok", headers=headers
                )
        with pytest.raises(SecurityError, match="INVALID_SIZE_LIMIT"):
            _fixture_gateway(policy, max_response_bytes=0)
        assert transport.opens == 0


def test_real_process_restart_denies_old_consent_and_preserves_unknown(tmp_path: Path) -> None:
    db = tmp_path / "security.sqlite"
    with ConsentStore(db) as policy, CostLedger(db) as ledger:
        policy.grant(
            "p",
            URL,
            "audio",
            capability="stt",
            scope=_fixture_grant_scope(policy),
            policy_version=2,
        )
        policy.bind_session("deleted")
        policy.revoke_session("deleted")
        reservation = ledger.reserve("p", "durable-request", 80, 100)
        ledger.mark_unknown(reservation)
    script = """
import json, socket, sys
from pathlib import Path
from recoryn.security import ConsentStore, CostLedger, Gateway, SecurityError, ConsentRequest, ConsentScope
def forbidden(*args, **kwargs):
    raise AssertionError("DNS/socket must never be used on restart")
socket.getaddrinfo = socket.socket = forbidden
with ConsentStore(Path(sys.argv[1])) as policy, CostLedger(Path(sys.argv[1])) as ledger:
    assert not policy.allowed("p", sys.argv[2], "audio", scope=ConsentScope.library(), request=ConsentRequest("session",0,"stt",2))
    try:
        Gateway(policy).request("p", sys.argv[2], "audio", b"synthetic")
    except SecurityError as error:
        assert error.code == "CONSENT_REQUIRED"
    else:
        raise AssertionError("fresh process reused consent")
    try:
        policy.bind_session("deleted")
    except SecurityError as error:
        assert error.code == "SESSION_REVOKED"
    else:
        raise AssertionError("deleted session was rebound")
    print(json.dumps(ledger.snapshot("p")))
"""
    child = subprocess.run(
        [sys.executable, "-c", script, str(db), URL],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert child.returncode == 0, child.stderr
    balance = json.loads(child.stdout)
    assert balance["unknown_exposure"] == 80 and balance["available"] == 20


def test_frozen_gateway_rejects_regrant_after_reservation_before_permit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "security.sqlite"
    transport = FakeTransport()
    with ConsentStore(db) as policy, CostLedger(db) as ledger:
        policy.grant(
            "p",
            URL,
            "audio",
            capability="stt",
            scope=_fixture_grant_scope(policy),
            policy_version=2,
        )
        bindings = policy.capture_bindings(
            "p",
            URL,
            ("audio",),
            scope=ConsentScope.library(),
            request=_fixture_request(policy, "session", "stt", 0),
        )
        gateway = _fixture_gateway(
            policy,
            ledger=ledger,
            transport=transport,
            expected_grants=bindings,
            session_id="session",
        )
        policy.validate_binding(bindings[0])
        reservation = fixture_reservation(
            ledger,
            monkeypatch,
            fixture_wire("p", URL, "audio", b"old-plan"),
            80,
            100,
            "validated-old-plan",
        )
        policy.revoke(
            "p", URL, "audio", capability="stt", scope=ConsentScope.library(), policy_version=2
        )
        policy.grant(
            "p",
            URL,
            "audio",
            capability="stt",
            scope=_fixture_grant_scope(policy),
            policy_version=2,
        )
        with pytest.raises(SecurityError, match="PERMIT_REVOKED"):
            gateway.request("p", URL, "audio", b"old-plan", reservation_id=reservation)
        assert transport.opens == 0 and fixture_balance(ledger)["reserved"] == 80
        policy.grant(
            "p",
            URL,
            "transcript",
            capability="stt",
            scope=_fixture_grant_scope(policy),
            policy_version=2,
        )
        with pytest.raises(SecurityError, match="CONSENT_REQUIRED"):
            gateway.request("p", URL, "transcript", b"widened-plan", reservation_id=reservation)
        assert transport.opens == 0


# The older tests exercise revocation/transport, with an explicitly chosen library
# grant. G02's separate cases exercise the default session-only permission.
def _fixture_request(
    policy: ConsentStore, session_id: str = "session", capability: str = "stt", generation: int = 0
) -> ConsentRequest:
    try:
        policy.bind_session(session_id, generation)
    except SecurityError:
        pass  # Registration grants nothing; the tested API still checks the fence.
    return ConsentRequest(session_id, generation, capability, 2)


def _fixture_grant_scope(policy: ConsentStore) -> ConsentScope:
    _fixture_request(policy)
    return ConsentScope.library()


def _fixture_gateway(
    policy: ConsentStore,
    *,
    session_id: str = "session",
    generation: int = 0,
    factory=Gateway,
    **kwargs,
):
    root = factory(policy, **kwargs)
    request = _fixture_request(policy, session_id)
    if "expected_grants" not in kwargs:
        bindings = []
        rows = policy._db.execute(
            "SELECT DISTINCT provider,endpoint,data_type FROM security_grants_v2 WHERE capability='stt' AND scope_kind='library' AND scope_id='' AND policy_version=2"
        ).fetchall()
        for provider, endpoint, data_type in rows:
            bindings.extend(
                policy.capture_bindings(
                    provider, endpoint, (data_type,), scope=ConsentScope.library(), request=request
                )
            )
        kwargs["expected_grants"] = tuple(bindings)
        root = factory(policy, **kwargs)
    return root.for_session(
        session_id, generation, capability="stt", scope=ConsentScope.library(), policy_version=2
    )
