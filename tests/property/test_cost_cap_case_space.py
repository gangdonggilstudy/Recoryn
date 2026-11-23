"""G06 integer quote partitions and bounded money-state model; no HTTP/model."""

from __future__ import annotations

import itertools
import math
import shutil
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from recoryn.security import CostCatalog, CostLedger, SecurityError
from recoryn.security.cost import quote
from tests.unit.test_cost_cap import (
    Clock,
    balance,
    flat_price,
    flat_request,
    install_catalog,
    policy,
    price,
    reserve,
    text_request,
    usage,
)

pytestmark = pytest.mark.property
TEXT = list(
    itertools.product(
        ("valid", "unknown", "expired"),
        (0, 1, 33, 4096, 4097),
        (None, 1, 32, 33),
        ("none", "small", "exact", "large"),
        ("strict", "general"),
        (True, False),
    )
)
ALPHABET = (
    "reserve60",
    "first_write",
    "timeout",
    "release",
    "provisional1",
    "final40v2",
    "final41v2",
)
STATE = [trace for length in range(5) for trace in itertools.product(ALPHABET, repeat=length)]


def reference(trace: tuple[str, ...]) -> tuple[str, int, bool]:
    """Literal financial automaton, independent of SQL and quote implementation."""
    state, actual, accepted = "ABSENT", 0, True
    events: dict[str, tuple[int, bool, int]] = {}
    for command in trace:
        accepted = True
        if command == "reserve60":
            if state == "ABSENT":
                state = "RESERVED"
        elif command == "first_write":
            accepted = state in {"RESERVED", "UNKNOWN"}
            if accepted:
                state = "UNKNOWN"
        elif command == "release":
            accepted = state in {"RESERVED", "RELEASED"}
            if accepted:
                state = "RELEASED"
        elif command == "timeout":
            pass
        else:
            key, record = (
                ("provisional", (1, False, 9))
                if command == "provisional1"
                else ("final", (2, True, 40 if command == "final40v2" else 41))
            )
            prior = events.get(key)
            accepted = state != "ABSENT" and (
                prior == record
                or (
                    prior is None
                    and state in {"RESERVED", "UNKNOWN"}
                    and record[0] > max((v[0] for v in events.values()), default=0)
                )
            )
            if accepted and prior is None:
                events[key] = record
                if record[1]:
                    state, actual = "SETTLED", record[2]
    return state, actual, accepted


def rejected_code(trace: tuple[str, ...]) -> str:
    """Independent diagnosis for a rejected final command of the literal model."""
    assert trace and not reference(trace)[2]
    prior = reference(trace[:-1])[0]
    if prior == "ABSENT":
        return "RESERVATION_NOT_FOUND"
    if trace[-1] == "first_write":
        return "RESERVATION_CONFLICT"
    if trace[-1] == "release":
        return "RESERVATION_MAY_BE_SENT"
    return "SETTLEMENT_CONFLICT"


def assert_trace(ledger: CostLedger, trace: tuple[str, ...]) -> None:
    state, actual, _ = reference(trace)
    confirmed = actual if state == "SETTLED" else 0
    reserved = 60 if state == "RESERVED" else 0
    unknown = 60 if state == "UNKNOWN" else 0
    assert balance(ledger) == {
        "confirmed": confirmed,
        "reserved": reserved,
        "unknown_exposure": unknown,
        "limit": 100,
        "available": 100 - confirmed - reserved - unknown,
    }
    rows = ledger.reservations("p")
    assert len(rows) == (0 if state == "ABSENT" else 1)
    if rows:
        assert rows[0]["state"] == state


class PrefixSnapshots:
    """Clone closed, checkpointed parent DB+witness fixtures; no oracle caching."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.paths: dict[tuple[str, ...], Path] = {}

    def build(self, trace: tuple[str, ...], settings: Any, clock: Clock) -> Path:
        if trace in self.paths:
            return self.paths[trace]
        name = "".join(str(ALPHABET.index(command)) for command in trace) or "empty"
        db = self.root / (name + ".sqlite")
        if trace:
            parent = self.build(trace[:-1], settings, clock)
            # The only connection was closed before publication. Refuse to
            # copy an uncheckpointed WAL rather than guessing it is current.
            assert not parent.with_name(parent.name + "-wal").exists()
            shutil.copyfile(parent, db)
            shutil.copyfile(
                parent.with_name(parent.name + ".cost-witness"),
                db.with_name(db.name + ".cost-witness"),
            )
        with CostLedger(db, clock=clock.now, monotonic=clock.monotonic) as ledger:
            if not trace:
                ledger.apply_policy("p", settings)
            else:
                rows = ledger.reservations("p")
                reservation = str(rows[0]["reservation_id"]) if rows else "missing"
                if reference(trace)[2]:
                    perform(ledger, trace[-1], reservation, settings)
                else:
                    with pytest.raises(SecurityError, match="^" + rejected_code(trace) + "$"):
                        perform(ledger, trace[-1], reservation, settings)
        self.paths[trace] = db
        return db


@pytest.fixture(scope="module")
def prefixes(tmp_path_factory: pytest.TempPathFactory) -> PrefixSnapshots:
    return PrefixSnapshots(tmp_path_factory.mktemp("g06-prefixes"))


def perform(ledger: CostLedger, command: str, reservation: str, settings: Any) -> str | None:
    if command == "reserve60":
        return reserve(ledger, flat_request(), settings, "one-request")
    if command == "first_write":
        ledger.mark_unknown(reservation)
    elif command == "release":
        ledger.release(reservation)
    elif command in {"provisional1", "final40v2", "final41v2"}:
        if command == "provisional1":
            usage(ledger, reservation, 1, 9, final=False, event="provisional")
        else:
            usage(ledger, reservation, 2, 40 if command == "final40v2" else 41, event="final")
    return None


@pytest.mark.parametrize("row", TEXT, ids=[f"G06-TEXT-{i:04}" for i in range(960)])
def test_text_price_request_cap_partitions(row: Any) -> None:
    status, size, output, cap_kind, mode, bounded = row
    # Fraction arithmetic is independent of production's integer ceiling formula.
    upper = math.ceil(Fraction(2 * (size + 3), 3)) + math.ceil(Fraction(5 * (output or 1), 2)) + 7
    cap = {"none": 0, "small": upper - 1, "exact": upper, "large": upper + 1}[cap_kind]
    entry = price(bound_kind="text_bytes" if bounded else "unverified")
    if status == "unknown":
        entry = replace(entry, price_as_of_utc=None, valid_from_utc=None, valid_until_utc=None)
    elif status == "expired":
        entry = replace(entry, valid_until_utc=1000)
    catalog = CostCatalog((entry,))
    settings = policy(catalog, cap=cap, mode=mode, general_acknowledged=mode == "general")
    request = text_request(size, output)
    invalid = size > 4096 or output not in (1, 32)
    unknown = status != "valid" or not bounded
    accepted = cap > 0 and not invalid and (mode == "general" or not unknown)
    accepted &= unknown or cap >= upper
    if not accepted:
        expected_code = (
            "COST_CAP_REQUIRED"
            if cap <= 0
            else "COST_REQUEST_INVALID"
            if invalid
            else "COST_PRICE_UNKNOWN"
            if status == "unknown" and mode == "strict"
            else "COST_PRICE_EXPIRED"
            if status == "expired" and mode == "strict"
            else "COST_BOUND_UNVERIFIED"
            if not bounded and mode == "strict"
            else "COST_CAP_EXCEEDED"
        )
        with pytest.raises(SecurityError, match="^" + expected_code + "$"):
            quote(request, settings, catalog, 1000)
    else:
        observed = quote(request, settings, catalog, 1000)
        assert (
            (observed.kind, observed.amount) == ("USER_CAP", cap)
            if unknown
            else (observed.kind, observed.amount) == ("VERIFIED", upper)
        )
        assert observed.input_upper is None if unknown else observed.input_upper == size + 3
        assert observed.output_upper is None if unknown else observed.output_upper == output


@pytest.mark.parametrize("trace", STATE, ids=[f"G06-STATE-{i:04}" for i in range(2801)])
def test_bounded_cost_state_model(
    monkeypatch: pytest.MonkeyPatch, prefixes: PrefixSnapshots, trace: tuple[str, ...]
) -> None:
    catalog = install_catalog(monkeypatch, flat_price(60))
    settings, clock = policy(catalog), Clock()
    db = prefixes.build(trace, settings, clock)
    # Every approved row independently reopens its durable final snapshot.
    with CostLedger(db, clock=clock.now, monotonic=clock.monotonic) as ledger:
        assert_trace(ledger, trace)


def test_case_space_literal_counts_and_unique_coordinates() -> None:
    assert len(TEXT) == len(set(TEXT)) == 960
    assert len(STATE) == len(set(STATE)) == 2801
    # Independent divisors recreate the approved coordinate space, not len(TEXT).
    observed = set()
    axes = [3, 5, 4, 4, 2, 2]
    for number in range(960):
        remainder = number
        digits = []
        for radix in reversed(axes):
            remainder, digit = divmod(remainder, radix)
            digits.append(digit)
        assert remainder == 0
        observed.add(tuple(reversed(digits)))
    assert observed == set(
        itertools.product(range(3), range(5), range(4), range(4), range(2), range(2))
    )


def test_quote_monotonicity_and_catalog_order() -> None:
    entries = (price(), price(model_revision="other"))
    catalog = CostCatalog(entries)
    assert CostCatalog(tuple(reversed(entries))).sha256 == catalog.sha256
    settings = policy(catalog, cap=10000)
    amounts = [
        quote(text_request(size, 1), settings, catalog, 1000).amount for size in (0, 1, 33, 4096)
    ]
    assert amounts == sorted(amounts)
    assert [
        quote(text_request(1, output), settings, catalog, 1000).amount for output in (1, 2, 32)
    ] == [13, 15, 90]


@pytest.mark.parametrize(
    "trace",
    [
        ("reserve60", "first_write", "release", "final40v2"),
        ("reserve60", "provisional1", "first_write", "final40v2"),
        ("reserve60", "final40v2", "provisional1", "timeout"),
        ("reserve60", "release", "reserve60", "first_write"),
        ("reserve60", "final40v2", "final41v2", "timeout"),
        ("provisional1", "final40v2", "timeout", "reserve60"),
        ("reserve60", "timeout", "first_write", "release"),
    ],
    ids=[f"G06-AUX-CONT-{i}" for i in range(7)],
)
def test_prefix_snapshots_match_continuous_ledger_lifetimes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    prefixes: PrefixSnapshots,
    trace: tuple[str, ...],
) -> None:
    catalog = install_catalog(monkeypatch, flat_price(60))
    settings, clock = policy(catalog), Clock()
    with CostLedger(
        tmp_path / "continuous.sqlite", clock=clock.now, monotonic=clock.monotonic
    ) as ledger:
        ledger.apply_policy("p", settings)
        reservation = "missing"
        for count, command in enumerate(trace, 1):
            prefix = trace[:count]
            if reference(prefix)[2]:
                result = perform(ledger, command, reservation, settings)
                if command == "reserve60":
                    assert result is not None
                    reservation = result
            else:
                with pytest.raises(SecurityError, match="^" + rejected_code(prefix) + "$"):
                    perform(ledger, command, reservation, settings)
            assert_trace(ledger, prefix)
        db = prefixes.build(trace, settings, clock)
        with CostLedger(db, clock=clock.now, monotonic=clock.monotonic) as restarted:
            assert balance(ledger) == balance(restarted)
