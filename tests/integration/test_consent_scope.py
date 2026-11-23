"""G02: real consent/ledger decisions and deterministic handoff orders, fake wire only."""

from __future__ import annotations

import itertools
import threading
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from recoryn.security import (
    ConsentRequest,
    ConsentScope,
    ConsentStore,
    CostLedger,
    Gateway,
    SecurityError,
)
from recoryn.security._core import Endpoint
from tests.unit.test_cost_cap import fixture_balance, fixture_reservation, fixture_wire

URL = "https://scope.example.test/v1"
FEATURES = ("stt", "summary", "diarization")
DATA = ("audio", "transcript", "context", "attachment")
FROZEN = list(
    itertools.product(
        ("session", "library"), FEATURES, DATA, range(7), ("reserve", "open", "first")
    )
)
HB = list(itertools.product(("session", "library"), FEATURES, range(6), range(5)))
CASE_IDS = {
    "FROZEN": [f"G02-FROZEN-{i:03d}" for i in range(504)],
    "HB": [f"G02-HB-{i:03d}" for i in range(180)],
}


class Wire:
    def __init__(self) -> None:
        self.opens = 0
        self.writes: list[bytes] = []
        self.response = b"OK"
        self.on_result: Callable[[], None] = lambda: None

    def open(
        self, endpoint: Endpoint, headers: Mapping[str, str], body_length: int, timeout: float
    ) -> Wire:
        self.opens += 1
        return self

    def write(self, data: bytes, timeout: float) -> None:
        self.writes.append(data)

    def read(self, limit: int, timeout: float) -> bytes:
        result, self.response = self.response[:limit], self.response[limit:]
        if not result:
            self.on_result()
        return result

    def close(self) -> None:
        pass


def view(
    policy: ConsentStore,
    wire: Wire,
    scope: ConsentScope,
    request: ConsentRequest,
    data: str,
    provider: str = "p",
    **kwargs: Any,
) -> Gateway:
    policy.bind_session(request.session_id, request.session_generation)
    bindings = policy.capture_bindings(provider, URL, (data,), scope=scope, request=request)
    return Gateway(policy, transport=wire, expected_grants=bindings, **kwargs).for_session(
        request.session_id,
        request.session_generation,
        capability=request.capability,
        scope=scope,
        policy_version=request.policy_version,
    )


def test_original_p1_session_denies_b_and_explicit_library_allows_both(tmp_path: Path) -> None:
    wire = Wire()
    with ConsentStore(tmp_path / "p1.db") as policy:
        session, library = ConsentScope.session("A"), ConsentScope.library()
        policy.grant("p", URL, "audio", capability="stt", scope=session, policy_version=2)
        a, b = ConsentRequest("A", 0, "stt", 2), ConsentRequest("B", 0, "stt", 2)
        view(policy, wire, session, a, "audio").request("p", URL, "audio", b"A")
        with pytest.raises(SecurityError, match="CONSENT_REQUIRED"):
            view(policy, wire, session, b, "audio").request("p", URL, "audio", b"B")
        assert wire.opens == 1 and wire.writes == [b"A"]
        policy.grant("p", URL, "audio", capability="stt", scope=library, policy_version=2)
        for request in (a, b):
            view(policy, wire, library, request, "audio").request("p", URL, "audio", b"all")
        assert wire.opens == 3 and wire.writes == [b"A", b"all", b"all"]


@pytest.fixture
def frozen_stores(tmp_path: Path):
    # Independent consent rows are reset in one setup transaction. Separate
    # provider IDs isolate cost accounts, keeping previous UNKNOWN exposure.
    db = tmp_path / "policy.db"
    with ConsentStore(db) as policy, CostLedger(db) as ledger:
        yield policy, ledger


@pytest.mark.parametrize("row", FROZEN, ids=CASE_IDS["FROZEN"])
def test_captured_request_cannot_be_retargeted(
    frozen_stores: tuple[ConsentStore, CostLedger],
    monkeypatch: pytest.MonkeyPatch,
    row: tuple[Any, ...],
) -> None:
    scope_kind, feature, data, change, boundary = row
    scope = ConsentScope.session("A") if scope_kind == "session" else ConsentScope.library()
    other_scope = ConsentScope.library() if scope_kind == "session" else ConsentScope.session("A")
    request = ConsentRequest("A", 0, feature, 2)
    wire = Wire()
    policy, ledger = frozen_stores
    provider = "frozen-" + str(FROZEN.index(row))
    other_feature = "summary" if feature != "summary" else "stt"
    other_data = "context" if data != "context" else "audio"
    with policy.coordinator.hold():
        policy._db.execute("BEGIN")
        policy._db.execute("DELETE FROM security_grants_v2")
        policy._db.execute("DELETE FROM security_sessions")
        policy._db.execute("UPDATE security_consent_meta SET policy_version=2")
        policy.bind_session("A")
        policy.bind_session("B")
        for target_scope, capability, endpoint, kind in itertools.product(
            (scope, other_scope),
            (feature, other_feature),
            (URL, URL + "-other"),
            (data, other_data),
        ):
            policy.grant(
                provider,
                endpoint,
                kind,
                capability=capability,
                scope=target_scope,
                policy_version=2,
            )
        policy._db.execute("COMMIT")
    gateway = view(policy, wire, scope, request, data, provider=provider, ledger=ledger)
    binding = gateway.expected_grants[0]
    actual_request, actual_scope, actual_endpoint, actual_data = request, scope, URL, data
    if change == 1:
        actual_request = replace(request, session_id="B")
    elif change == 2:
        actual_request = replace(request, capability=other_feature)
    elif change == 3:
        actual_data = other_data
    elif change == 4:
        actual_endpoint = URL + "-other"
    elif change == 5:
        actual_scope = other_scope
    elif change == 6:
        actual_request = replace(request, policy_version=3)

    rebinding_outcomes: list[str] = []

    def attempt() -> None:
        if change == 6:
            policy.advance_policy_version(3)
            policy.grant(provider, URL, data, capability=feature, scope=scope, policy_version=3)
        if change in (1, 2, 5, 6):
            # A captured view must refuse rebinding even if a later permit could reject it.
            try:
                gateway.for_session(
                    actual_request.session_id,
                    capability=actual_request.capability,
                    scope=actual_scope,
                    policy_version=actual_request.policy_version,
                )
            except SecurityError as error:
                rebinding_outcomes.append(error.code)
                raise
            rebinding_outcomes.append("ACCEPTED")
            raise AssertionError("captured view accepted a changed request context")
        policy.permit(
            provider,
            actual_endpoint,
            actual_data,
            "a" * 64,
            scope=actual_scope,
            request=actual_request,
            expected_grant=binding,
        )

    reservation: str | None = None
    if boundary == "reserve":
        if change:
            with pytest.raises(SecurityError):
                attempt()
            assert ledger.reservations(provider) == []
        else:
            attempt()
            reservation = fixture_reservation(
                ledger,
                monkeypatch,
                fixture_wire(provider, URL, data, b"a", operation=feature),
                7,
                10,
                "frozen",
            )
    elif boundary == "open":
        reservation = fixture_reservation(
            ledger,
            monkeypatch,
            fixture_wire(provider, URL, data, b"a", operation=feature),
            7,
            10,
            "frozen",
        )
        if change:
            with pytest.raises(SecurityError):
                attempt()
        else:
            attempt()
    else:
        reservation = fixture_reservation(
            ledger,
            monkeypatch,
            fixture_wire(provider, URL, data, b"a", operation=feature),
            7,
            10,
            "frozen",
        )
        original = gateway._write

        def before_write(*args: Any, **kwargs: Any) -> None:
            attempt()
            original(*args, **kwargs)

        monkeypatch.setattr(gateway, "_write", before_write)
    if not change:
        assert reservation is not None
        assert gateway.request(provider, URL, data, b"a", reservation_id=reservation) == b"OK"
        assert wire.opens == 1 and wire.writes == [b"a"]
    elif boundary == "first":
        with pytest.raises(SecurityError):
            gateway.request(provider, URL, data, b"a", reservation_id=reservation)
        assert wire.opens == 1 and wire.writes == []
    else:
        assert wire.opens == 0 and wire.writes == []
    if change in (1, 2, 5, 6):
        # Gateway can translate the hook's AssertionError to TRANSPORT_FAILED.
        # Observe the rebind API itself outside that exception boundary.
        assert rebinding_outcomes == ["PERMIT_REVOKED"]


@pytest.mark.parametrize("row", HB, ids=CASE_IDS["HB"])
def test_invalidation_handoff_orders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, row: tuple[Any, ...]
) -> None:
    scope_kind, feature, action, position = row
    scope = ConsentScope.session("A") if scope_kind == "session" else ConsentScope.library()
    request = ConsentRequest("A", 0, feature, 2)
    clock = [1000.0]
    db = tmp_path / "policy.db"
    wire = Wire()
    with (
        ConsentStore(db, ttl_seconds=60, clock=lambda: clock[0]) as policy,
        CostLedger(db) as ledger,
    ):
        policy.grant("p", URL, "audio", capability=feature, scope=scope, policy_version=2)
        gateway = view(policy, wire, scope, request, "audio", ledger=ledger, chunk_bytes=1)
        reservation = fixture_reservation(
            ledger,
            monkeypatch,
            fixture_wire("p", URL, "audio", b"ab", operation=feature),
            7,
            10,
            "request",
        )
        go, committed = threading.Event(), threading.Event()
        failures: list[BaseException] = []

        def invalidate() -> None:
            try:
                assert go.wait(5)
                if action == 0:
                    policy.revoke(
                        "p", URL, "audio", capability=feature, scope=scope, policy_version=2
                    )
                elif action == 1:
                    policy.revoke_session("A")
                elif action == 2:
                    with policy.coordinator.hold():
                        clock[0] = 1060.0
                elif action == 3:
                    policy.advance_policy_version(3)
                elif action == 4:
                    with ConsentStore(db, clock=lambda: clock[0]):
                        pass
                else:
                    policy.grant(
                        "p", URL, "audio", capability=feature, scope=scope, policy_version=2
                    )
            except BaseException as exc:
                failures.append(exc)
            finally:
                committed.set()

        worker = threading.Thread(target=invalidate)
        worker.start()

        def commit() -> None:
            go.set()
            assert committed.wait(5), "invalidation failed to reach its linearization point"
            assert not failures

        original = gateway._write

        def write(*args: Any, **kwargs: Any) -> None:
            if (position == 1 and not wire.writes) or (position == 2 and len(wire.writes) == 1):
                commit()
            original(*args, **kwargs)

        monkeypatch.setattr(gateway, "_write", write)
        if position == 0:
            commit()
        if position == 3:
            wire.on_result = commit
        try:
            if position < 4:
                with pytest.raises(SecurityError) as observed:
                    gateway.request("p", URL, "audio", b"ab", reservation_id=reservation)
                assert observed.value.outcome_known is (position < 2)
            else:
                assert (
                    gateway.request("p", URL, "audio", b"ab", reservation_id=reservation) == b"OK"
                )
                commit()
        finally:
            go.set()
            worker.join(5)
        assert not worker.is_alive() and not failures
        assert wire.opens == (0 if position == 0 else 1)
        assert len(wire.writes) == (0, 0, 1, 2, 2)[position]
        balance = fixture_balance(ledger, "p")
        assert balance["unknown_exposure"] == (0 if position < 2 else 7)
        assert balance["reserved"] == (7 if position < 2 else 0)
