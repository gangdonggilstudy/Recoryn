"""Q24 finite permission/history cubes, exact boundaries and cost partition law."""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from itertools import product
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

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
from tests.unit.test_cost_cap import fixture_balance, fixture_reservation, fixture_wire

pytestmark = pytest.mark.property
URL = "https://q24.example.test/chat"
MAX_MONEY = 2**63 - 1
ADMISSION = tuple(product((False, True), repeat=7))
HANDOFF = tuple(product(("open", "first"), tuple(product((False, True), repeat=4))))
TIMES = tuple(product(("grant", "permit", "local", "deadline"), (-1, 0, 1)))
ALLOCATIONS = ((3, 0, 0), (0, 3, 0), (0, 0, 3), (1, 1, 1))
BUDGETS = tuple(product(ALLOCATIONS, (4, 5, 6)))
INTEGER_VALUES = (
    ("negative", -1),
    ("zero", 0),
    ("one", 1),
    ("max-minus-one", MAX_MONEY - 1),
    ("max", MAX_MONEY),
    ("overflow", MAX_MONEY + 1),
    ("bool", True),
)
INTEGERS = tuple(product(("amount", "limit"), INTEGER_VALUES))


def bits(values: tuple[bool, ...]) -> str:
    return "".join("1" if value else "0" for value in values)


def budget_id(allocation: tuple[int, ...], limit: int) -> str:
    c, r, u = allocation
    return f"budget-c{c}r{r}u{u}-limit{limit}"


CASE_IDS = {
    "admit": tuple("admit-" + bits(row) for row in ADMISSION),
    "handoff": tuple(f"handoff-{boundary}-{bits(row)}" for boundary, row in HANDOFF),
    "time": tuple(f"time-{kind}-{delta:+d}" for kind, delta in TIMES),
    "budget": tuple(budget_id(allocation, limit) for allocation, limit in BUDGETS),
    "integer": tuple(f"int-{field}-{name}" for field, (name, _) in INTEGERS),
}


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    attempts: list[bool] = []

    def forbidden(*args: object, **kwargs: object) -> None:
        attempts.append(True)
        raise AssertionError("Q24 forbids live DNS/socket transport")

    for name in ("getaddrinfo", "gethostbyname", "create_connection"):
        monkeypatch.setattr(socket, name, forbidden)
    for name in ("connect", "connect_ex", "send", "sendall", "sendto"):
        monkeypatch.setattr(socket.socket, name, forbidden)
    yield
    assert not attempts, "a swallowed network exception is still an attempted transmission"


class Wire:
    def __init__(self) -> None:
        self.opens = 0
        self.writes: list[bytes] = []
        self.closed = False
        self.response = b"OK"
        self.after_open: Callable[[], None] = lambda: None
        self.after_first: Callable[[], None] = lambda: None

    def open(
        self, endpoint: Endpoint, headers: Mapping[str, str], body_length: int, timeout: float
    ) -> Wire:
        self.opens += 1
        self.after_open()
        return self

    def write(self, data: bytes, timeout: float) -> None:
        self.writes.append(data)
        if len(self.writes) == 1:
            self.after_first()

    def read(self, limit: int, timeout: float) -> bytes:
        value, self.response = self.response[:limit], self.response[limit:]
        return value

    def close(self) -> None:
        self.closed = True


class Owner:
    def __init__(self, live: bool = True) -> None:
        self.live = live

    @contextmanager
    def guard(self, permit: SendPermit) -> Iterator[None]:
        if not self.live:
            raise SecurityError("LOCAL_EXECUTION_UNVERIFIED")
        yield


def test_declared_finite_manifest_has_no_missing_or_duplicate_rows() -> None:
    # Counts come from independently grouped factors, not len(generator).
    counts = {
        "admit": 8 * 4 * 2 * 2,
        "handoff": 2 * 16,
        "time": 4 * 3,
        "budget": 4 * 3,
        "integer": 2 * 7,
    }
    assert sum(counts.values()) == 198
    for family, declared in counts.items():
        assert len(CASE_IDS[family]) == len(set(CASE_IDS[family])) == declared
    assert set(CASE_IDS["admit"]) == {f"admit-{n:07b}" for n in range(128)}
    assert set(CASE_IDS["handoff"]) == {
        f"handoff-{boundary}-{n:04b}" for boundary in ("open", "first") for n in range(16)
    }


@pytest.mark.parametrize("row", ADMISSION, ids=CASE_IDS["admit"])
def test_admission_case_space(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
    row: tuple[bool, ...],
) -> None:
    provider_match, endpoint_match, data_match, regrant, revoked, live, reserved = row
    owner, wire = Owner(live), Wire()
    db = tmp_path / "cube.sqlite"
    with ConsentStore(db, clock=lambda: 1000.0) as policy, CostLedger(db) as ledger:
        policy.grant(
            "p",
            URL,
            "transcript",
            capability="stt",
            scope=_fixture_grant_scope(policy),
            policy_version=2,
        )
        binding = policy.capture_bindings(
            "p",
            URL,
            ("transcript",),
            scope=ConsentScope.library(),
            request=_fixture_request(policy, "session", "stt", 0),
        )
        reservation = fixture_reservation(
            ledger, monkeypatch, fixture_wire("p", URL, "transcript", b"abcd"), 7, 10, "request"
        )
        if not reserved:
            ledger.mark_unknown(reservation)
        if regrant:
            policy.revoke(
                "p",
                URL,
                "transcript",
                capability="stt",
                scope=ConsentScope.library(),
                policy_version=2,
            )
            policy.grant(
                "p",
                URL,
                "transcript",
                capability="stt",
                scope=_fixture_grant_scope(policy),
                policy_version=2,
            )
        if revoked:
            policy.revoke(
                "p",
                URL,
                "transcript",
                capability="stt",
                scope=ConsentScope.library(),
                policy_version=2,
            )
        gateway = _fixture_gateway(
            policy,
            ledger=ledger,
            transport=wire,
            chunk_bytes=2,
            expected_grants=binding,
            dispatch_guard=owner.guard,
        )
        # Conjunction is mandatory; diagnostic order among simultaneous failures
        # is not a separately established API contract. Keep every negative row.
        safe_errors: set[str] = set()
        if not (provider_match and data_match):
            safe_errors.add("CONSENT_REQUIRED")
        if not endpoint_match:
            safe_errors.update(("CONSENT_REQUIRED", "ENDPOINT_CHANGED"))
        if revoked:
            safe_errors.update(("CONSENT_REQUIRED", "CONSENT_REVOKED", "PERMIT_REVOKED"))
        if regrant:
            safe_errors.add("PERMIT_REVOKED")
        if not reserved:
            safe_errors.add("RESERVATION_NOT_DISPATCHABLE")
        if not live:
            safe_errors.add("LOCAL_EXECUTION_UNVERIFIED")
        args = (
            "p" if provider_match else "q",
            URL if endpoint_match else URL + "-other",
            "transcript" if data_match else "context",
            b"abcd",
        )
        if not safe_errors:
            assert gateway.request(*args, reservation_id=reservation) == b"OK"
            request.node.user_properties.append(("diagnostic", "SUCCESS"))
        else:
            observed: SecurityError | None = None
            try:
                gateway.request(*args, reservation_id=reservation)
            except SecurityError as error:
                observed = error
            assert observed is not None, "denied admission row reached a successful dispatch"
            assert observed.code in safe_errors
            assert observed.outcome_known
            request.node.user_properties.append(("diagnostic", observed.code))
        assert wire.opens == (0 if safe_errors else 1)
        assert wire.writes == ([] if safe_errors else [b"ab", b"cd"])
        assert wire.closed is (not safe_errors)
        unknown = not reserved or not safe_errors
        assert fixture_balance(ledger) == {
            "confirmed": 0,
            "reserved": 0 if unknown else 7,
            "unknown_exposure": 7 if unknown else 0,
            "available": 3,
            "limit": 10,
        }


@pytest.mark.parametrize("boundary,row", HANDOFF, ids=CASE_IDS["handoff"])
def test_handoff_case_space(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
    boundary: str,
    row: tuple[bool, ...],
) -> None:
    revoke, owner_revoke, cancel_now, expire = row
    clock, owner, wire = [100.0], Owner(), Wire()
    cancel = threading.Event()
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    db = tmp_path / "handoff.sqlite"
    with ConsentStore(db, clock=lambda: 1000.0) as policy, CostLedger(db) as ledger:
        policy.grant(
            "p",
            URL,
            "transcript",
            capability="stt",
            scope=_fixture_grant_scope(policy),
            policy_version=2,
        )
        reservation = fixture_reservation(
            ledger, monkeypatch, fixture_wire("p", URL, "transcript", b"abcd"), 7, 10, "request"
        )

        def interrupt() -> None:
            if revoke:
                policy.revoke(
                    "p",
                    URL,
                    "transcript",
                    capability="stt",
                    scope=ConsentScope.library(),
                    policy_version=2,
                )
            if owner_revoke:
                owner.live = False
            if cancel_now:
                cancel.set()
            if expire:
                clock[0] = 110.0

        if boundary == "open":
            wire.after_open = interrupt
        else:
            wire.after_first = interrupt
        gateway = _fixture_gateway(
            policy,
            ledger=ledger,
            transport=wire,
            chunk_bytes=2,
            timeout=10,
            dispatch_guard=owner.guard,
        )
        if any(row):
            with pytest.raises(SecurityError) as error:
                gateway.request(
                    "p", URL, "transcript", b"abcd", reservation_id=reservation, cancel=cancel
                )
            safe_errors: set[str] = set()
            if revoke:
                safe_errors.update(("CONSENT_REQUIRED", "CONSENT_REVOKED", "PERMIT_REVOKED"))
            if cancel_now:
                safe_errors.add("CANCELLED")
            if expire:
                safe_errors.add("TIMEOUT")
            if owner_revoke:
                safe_errors.add("LOCAL_EXECUTION_UNVERIFIED")
            if boundary == "first":
                safe_errors.add("REMOTE_OUTCOME_UNKNOWN")
            assert error.value.code in safe_errors
            request.node.user_properties.append(("diagnostic", error.value.code))
            assert error.value.outcome_known is (boundary == "open")
            assert wire.writes == ([] if boundary == "open" else [b"ab"])
        else:
            assert (
                gateway.request(
                    "p", URL, "transcript", b"abcd", reservation_id=reservation, cancel=cancel
                )
                == b"OK"
            )
            assert wire.writes == [b"ab", b"cd"]
            request.node.user_properties.append(("diagnostic", "SUCCESS"))
        assert wire.opens == 1 and wire.closed
        unknown = boundary == "first" or not any(row)
        assert fixture_balance(ledger)["unknown_exposure"] == (7 if unknown else 0)
        assert fixture_balance(ledger)["reserved"] == (0 if unknown else 7)
        assert fixture_balance(ledger)["available"] == 3


@pytest.mark.parametrize("kind,delta", TIMES, ids=CASE_IDS["time"])
def test_exact_time_boundaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, delta: int
) -> None:
    wall, mono, wire = [1000.0], [100.0], Wire()
    monkeypatch.setattr(time, "monotonic", lambda: mono[0])
    with ConsentStore(
        tmp_path / "time.sqlite", ttl_seconds=10 if kind == "grant" else 60, clock=lambda: wall[0]
    ) as policy:
        target = "http://127.0.0.1:39271/chat" if kind == "local" else URL
        if kind == "local":
            policy.approve_local_endpoint(target, "a" * 64, ttl_seconds=10)
        policy.grant(
            "p",
            target,
            "transcript",
            capability="stt",
            scope=_fixture_grant_scope(policy),
            policy_version=2,
        )
        if kind == "permit":
            permit = policy.permit(
                "p",
                target,
                "transcript",
                "a" * 64,
                scope=ConsentScope.library(),
                request=_fixture_request(policy, "session", "stt", 0),
                expected_grant=_fixture_binding(
                    policy, "p", target, "transcript", "session", "stt", 0
                ),
            )
            wall[0] = 1030 + delta
            if delta < 0:
                policy.validate(permit)
            else:
                with pytest.raises(SecurityError, match="PERMIT_REVOKED"):
                    policy.validate(permit)
            return
        if kind == "deadline":
            wire.after_open = lambda: mono.__setitem__(0, 110 + delta)
        else:
            wall[0] = 1010 + delta
        gateway = _fixture_gateway(policy, transport=wire, timeout=10, chunk_bytes=2)
        if delta < 0:
            assert gateway.request("p", target, "transcript", b"abcd") == b"OK"
            assert wire.writes == [b"ab", b"cd"]
        else:
            with pytest.raises(SecurityError) as error:
                gateway.request("p", target, "transcript", b"abcd")
            assert error.value.code == ("TIMEOUT" if kind == "deadline" else "CONSENT_REQUIRED")
            assert error.value.outcome_known and wire.writes == []
            assert wire.opens == (1 if kind == "deadline" else 0)


@pytest.mark.parametrize("allocation,limit", BUDGETS, ids=CASE_IDS["budget"])
def test_integer_budget_composition_boundary(
    tmp_path: Path, allocation: tuple[int, ...], limit: int
) -> None:
    confirmed, reserved, unknown = allocation
    with CostLedger(tmp_path / "budget.sqlite") as ledger:
        for name, amount in zip(("c", "r", "u"), allocation, strict=True):
            if amount:
                reference = ledger.reserve("p", name, amount, 10)
                if name == "c":
                    ledger.settle(reference, amount)
                elif name == "u":
                    ledger.mark_unknown(reference)
        ledger.set_limit("p", limit)
        before = ledger.snapshot("p")
        assert before == {
            "confirmed": confirmed,
            "reserved": reserved,
            "unknown_exposure": unknown,
            "available": limit - 3,
            "limit": limit,
        }
        if limit == 4:
            with pytest.raises(SecurityError, match="BUDGET_EXCEEDED"):
                ledger.reserve("p", "next", 2, limit)
            assert ledger.snapshot("p") == before
        else:
            refusal: SecurityError | None = None
            try:
                ledger.reserve("p", "next", 2, limit)
            except SecurityError as error:
                refusal = error
            assert refusal is None, "inclusive budget boundary rejected an affordable reservation"
            assert ledger.snapshot("p") == {
                **before,
                "reserved": reserved + 2,
                "available": {5: 0, 6: 1}[limit],
            }


@pytest.mark.parametrize("field,entry", INTEGERS, ids=CASE_IDS["integer"])
def test_integer_representation_boundaries(
    tmp_path: Path, field: str, entry: tuple[str, int]
) -> None:
    name, value = entry
    with CostLedger(tmp_path / "integer.sqlite") as ledger:
        if name in {"negative", "overflow", "bool"}:
            with pytest.raises(SecurityError, match="INVALID_AMOUNT"):
                ledger.reserve(
                    "p",
                    "request",
                    value if field == "amount" else 0,
                    MAX_MONEY if field == "amount" else value,
                )
            assert ledger.reservations("p") == []
            return
        ledger.reserve(
            "p",
            "request",
            value if field == "amount" else 0,
            MAX_MONEY if field == "amount" else value,
        )
        if field == "amount":
            available = {"zero": MAX_MONEY, "one": MAX_MONEY - 1, "max-minus-one": 1, "max": 0}[
                name
            ]
        else:
            available = value
        assert ledger.snapshot("p")["available"] == available


@settings(max_examples=30, deadline=None, derandomize=True, database=None)
@given(
    x=st.integers(0, 100000),
    y=st.integers(0, 100000),
    state=st.sampled_from(("RESERVED", "UNKNOWN", "SETTLED")),
)
def test_cost_partition_preserves_exposure(x: int, y: int, state: str) -> None:
    with TemporaryDirectory(prefix="recoryn-q24-partition-") as directory:
        snapshots: list[dict[str, int]] = []
        for name, amounts in (("whole", (x + y,)), ("split", (x, y))):
            with CostLedger(Path(directory) / (name + ".sqlite")) as ledger:
                for index, amount in enumerate(amounts):
                    reference = ledger.reserve("p", str(index), amount, x + y + 5)
                    if state == "UNKNOWN":
                        ledger.mark_unknown(reference)
                    elif state == "SETTLED":
                        ledger.settle(reference, amount)
                snapshots.append(ledger.snapshot("p"))
        assert snapshots[0] == snapshots[1]
        assert snapshots[0]["available"] == 5


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


def _fixture_binding(
    policy: ConsentStore,
    provider: str,
    endpoint: str,
    data_type: str,
    session_id: str = "session",
    capability: str = "stt",
    generation: int = 0,
):
    request = _fixture_request(policy, session_id, capability, generation)
    bindings = policy.capture_bindings(
        provider, endpoint, (data_type,), scope=ConsentScope.library(), request=request
    )
    if not bindings:
        raise SecurityError("CONSENT_REQUIRED")
    return bindings[0]


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
