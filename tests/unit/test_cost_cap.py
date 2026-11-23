"""G06 hand-calculated money, DTO boundaries and event category oracles.

All price entries below are a synthetic wire protocol's accounting fixtures.
They are injected into TEMP tests; the shipped catalog stays empty.
"""

from __future__ import annotations

import io
import json
import wave
from pathlib import Path
from typing import Any

import pytest

from recoryn.security import (
    CostCatalog,
    CostLedger,
    CostPolicy,
    CostRequest,
    PriceEntry,
    SecurityError,
    cost,
    cost_catalog,
)

pytestmark = pytest.mark.unit
URL = "https://cost.invalid/v1/responses"
MAX = (1 << 63) - 1
FIXTURE_END = 4_102_444_800  # Toy period only; not a real price validity claim.


class Clock:
    def __init__(self, utc: float = 1000.0) -> None:
        self.utc = utc
        self.tick = 10.0

    def now(self) -> float:
        return self.utc

    def monotonic(self) -> float:
        return self.tick


def price(**changes: Any) -> PriceEntry:
    values = dict(
        provider_id="p",
        endpoint=URL,
        model_revision="model",
        api_version="v1",
        operation="summary",
        currency="USD",
        profile_id="SYNTHETIC_TEST_ONLY",
        wire_protocol="text-fixture-v1",
        bound_kind="text_bytes",
        price_as_of_utc=0,
        valid_from_utc=0,
        valid_until_utc=2000,
        source_url="https://source.invalid/fixture",
        source_sha256="a" * 64,
        acquired_utc=0,
        review_id="NOT_A_REAL_PRICE",
        input_numerator=2,
        input_denominator=3,
        output_numerator=5,
        output_denominator=2,
        fixed_fee=7,
        input_overhead=3,
        max_input=4096,
        max_output=32,
    )
    values.update(changes)
    return PriceEntry(**values)


def install_catalog(monkeypatch: pytest.MonkeyPatch, *entries: PriceEntry) -> CostCatalog:
    catalog = CostCatalog(tuple(entries))
    monkeypatch.setattr(cost_catalog, "_ENTRIES", catalog.entries)
    monkeypatch.setattr(cost_catalog, "_EXPECTED_DIGEST", catalog.sha256)
    # Synthetic wire profiles never enter the production catalog loader.
    monkeypatch.setattr(cost_catalog, "load_catalog", lambda: catalog)
    return catalog


def policy(catalog: CostCatalog, **changes: Any) -> CostPolicy:
    values = dict(
        mode="strict",
        currency="USD",
        period_start_utc=0,
        period_end_utc=2000,
        cap=100,
        limit=100,
        policy_version=1,
        catalog_digest=catalog.sha256,
    )
    values.update(changes)
    return CostPolicy(**values)


def text_request(size: int = 1, output: object = 1, **changes: Any) -> CostRequest:
    body = json.dumps(
        {"model": "model", "text": "x" * size, "max_output_tokens": output}, separators=(",", ":")
    ).encode()
    values = dict(
        provider_id="p",
        endpoint=URL,
        model_revision="model",
        api_version="v1",
        operation="summary",
        data_type="transcript",
        body=body,
    )
    values.update(changes)
    return CostRequest(**values)


def audio_bytes(milliseconds: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(1000)
        stream.writeframes(b"\0\x01" * milliseconds)
    return buffer.getvalue()


def flat_price(amount: int, **changes: Any) -> PriceEntry:
    values = dict(
        wire_protocol="opaque-fixture-v1",
        model_revision=f"fee{amount}",
        input_numerator=0,
        output_numerator=0,
        fixed_fee=amount,
        input_overhead=0,
        max_input=20 * 1024 * 1024,
        max_output=131072,
    )
    values.update(changes)
    return price(**values)


def flat_request(amount: int = 60, **changes: Any) -> CostRequest:
    return text_request(model_revision=f"fee{amount}", body=b"synthetic-packet", **changes)


def reserve(ledger: CostLedger, request: CostRequest, settings: CostPolicy, name: str) -> str:
    quoted = ledger.quote_request(request, settings)
    return ledger.reserve_quote(name, quoted, settings, request)


def fixture_reservation(
    ledger: CostLedger,
    monkeypatch: pytest.MonkeyPatch,
    request: CostRequest,
    amount: int,
    limit: int,
    name: str,
) -> str:
    """Explicit toy-wire charges for older consent/transport fixtures only."""
    catalog = install_catalog(
        monkeypatch,
        flat_price(
            amount,
            provider_id=request.provider_id,
            endpoint=request.endpoint,
            model_revision=request.model_revision,
            api_version=request.api_version,
            operation=request.operation,
            valid_until_utc=FIXTURE_END,
        ),
    )
    settings = policy(catalog, cap=amount, limit=limit, period_end_utc=FIXTURE_END)
    ledger.apply_policy(request.provider_id, settings)
    return reserve(ledger, request, settings, name)


def fixture_balance(ledger: CostLedger, provider: str = "p") -> dict[str, int]:
    return ledger.account_snapshot(provider, "USD", 0, FIXTURE_END)


def fixture_wire(
    provider: str,
    target: str,
    data: str,
    body: bytes,
    *,
    operation: str = "stt",
    model: str = "fixture",
    headers: dict[str, str] | None = None,
) -> CostRequest:
    return CostRequest(
        provider,
        target,
        model,
        cost.wire_api_version(provider, target, headers),
        operation,
        data,
        body,
        cost.cost_headers(headers),
    )


def balance(ledger: CostLedger, provider: str = "p", **changes: Any) -> dict[str, int]:
    values = dict(currency_code="USD", start=0, end=2000)
    values.update(changes)
    return ledger.account_snapshot(provider, **values)


def usage(
    ledger: CostLedger,
    reservation: str,
    version: int,
    amount: int,
    *,
    final: bool = True,
    event: str = "event",
    code: str = "USD",
    period: str | None = None,
) -> None:
    account = ledger.account("p", "USD", 0, 2000)
    assert account is not None
    ledger.apply_usage(
        reservation,
        source="fixture",
        event_id=event,
        version=version,
        final=final,
        currency_code=code,
        period_id=period or account["account_id"],
        amount=amount,
    )


COMPOSITIONS = [(3, 0, 0), (0, 3, 0), (0, 0, 3), (1, 1, 1)]
BALANCE = [
    (parts, limit, code) for parts in COMPOSITIONS for limit in (4, 5, 6) for code in ("USD", "EUR")
]


@pytest.mark.parametrize("row", BALANCE, ids=[f"G06-BALANCE-{i:03}" for i in range(24)])
def test_scoped_balance_boundary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, row: Any) -> None:
    parts, limit, code = row
    catalog = install_catalog(monkeypatch, *(flat_price(n, currency=code) for n in (1, 2, 3)))
    settings = policy(catalog, currency=code, limit=limit)
    clock = Clock()
    with CostLedger(tmp_path / "cost.sqlite", clock=clock.now, monotonic=clock.monotonic) as ledger:
        ledger.apply_policy("p", settings)
        for state, amount in zip(("SETTLED", "RESERVED", "UNKNOWN"), parts, strict=True):
            if not amount:
                continue
            reservation = reserve(ledger, flat_request(amount), settings, state)
            if state == "SETTLED":
                ledger.settle(reservation, amount)
            elif state == "UNKNOWN":
                ledger.mark_unknown(reservation)
        observed = balance(ledger, currency_code=code)
        assert (observed["confirmed"], observed["reserved"], observed["unknown_exposure"]) == parts
        if limit == 4:
            with pytest.raises(SecurityError, match="BUDGET_EXCEEDED"):
                reserve(ledger, flat_request(2), settings, "next")
        else:
            reserve(ledger, flat_request(2), settings, "next")
            assert balance(ledger, currency_code=code)["available"] == limit - 5


EVENTS = [
    (state, incoming, reopen)
    for state in ("ABSENT", "RESERVED", "UNKNOWN", "SETTLED", "RELEASED")
    for incoming in (
        "provisional",
        "same_final",
        "different_final",
        "reverse",
        "duplicate_conflict",
        "currency",
        "period",
    )
    for reopen in (False, True)
]


@pytest.mark.parametrize("row", EVENTS, ids=[f"G06-EVENTS-{i:03}" for i in range(70)])
def test_usage_event_order_and_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, row: Any
) -> None:
    state, incoming, reopen = row
    catalog = install_catalog(monkeypatch, flat_price(60))
    settings = policy(catalog)
    clock = Clock()
    db = tmp_path / "cost.sqlite"
    ledger = CostLedger(db, clock=clock.now, monotonic=clock.monotonic)
    try:
        ledger.apply_policy("p", settings)
        reservation = "absent"
        if state != "ABSENT":
            reservation = reserve(ledger, flat_request(), settings, "r")
            usage(ledger, reservation, 2, 1, final=False, event="base")
            if state == "UNKNOWN":
                ledger.mark_unknown(reservation)
            elif state == "SETTLED":
                usage(ledger, reservation, 3, 40, event="final")
            elif state == "RELEASED":
                ledger.release(reservation)
        if reopen:
            ledger.close()
            ledger = CostLedger(db, clock=clock.now, monotonic=clock.monotonic)
        before = balance(ledger)
        version, amount, final, event, code, period = 4, 9, False, "provisional", "USD", None
        if incoming == "same_final":
            version, amount, final, event = 3, 40, True, "final"
        elif incoming == "different_final":
            version, amount, final, event = 4, 41, True, "different"
        elif incoming == "reverse":
            version, amount, final = 1, 40, True
        elif incoming == "duplicate_conflict":
            version, event = 2, "base"
        elif incoming == "currency":
            code = "EUR"
        elif incoming == "period":
            period = "other-period"
        accepted = state in {"RESERVED", "UNKNOWN"} and incoming in {
            "provisional",
            "same_final",
            "different_final",
        }
        accepted |= state == "SETTLED" and incoming == "same_final"
        if accepted:
            usage(
                ledger,
                reservation,
                version,
                amount,
                final=final,
                event=event,
                code=code,
                period=period,
            )
        else:
            expected_code = (
                "RESERVATION_NOT_FOUND"
                if state == "ABSENT"
                else "COST_CURRENCY_MISMATCH"
                if incoming == "currency"
                else "COST_PERIOD_CHANGED"
                if incoming == "period"
                else "SETTLEMENT_CONFLICT"
            )
            with pytest.raises(SecurityError, match="^" + expected_code + "$"):
                usage(
                    ledger,
                    reservation,
                    version,
                    amount,
                    final=final,
                    event=event,
                    code=code,
                    period=period,
                )
        expected = dict(before)
        if accepted and final:
            expected.update(
                confirmed=amount, reserved=0, unknown_exposure=0, available=100 - amount
            )
        assert balance(ledger) == expected
    finally:
        ledger.close()


VALUES = [-1, 0, 1, MAX - 1, MAX, MAX + 1, True, 1.0, "1", None, float("nan"), float("inf")]
FIELDS = ["B", "O", "rate_n", "rate_d", "cap", "limit", "usage", "version", "start", "end"]
NUMERIC = [(field, value) for field in FIELDS for value in VALUES]


@pytest.mark.parametrize("row", NUMERIC, ids=[f"G06-NUMERIC-{i:03}" for i in range(120)])
def test_integer_representations_without_large_allocations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    row: Any,
) -> None:
    field, value = row
    valid = type(value) is int and 0 <= value <= MAX
    if field in {"O", "rate_d", "version", "end"}:
        valid &= type(value) is int and value > 0
    if field == "B":
        valid &= type(value) is int and value <= 20 * 1024 * 1024
    if field == "O":
        valid &= type(value) is int and value <= 32
    if field == "start":
        valid &= type(value) is int and value < MAX
    catalog = install_catalog(monkeypatch, price(), flat_price(60))

    def attempt() -> None:
        if field == "B":
            cost.input_size(value)
        elif field == "O":
            cost.quote(text_request(output=value), policy(catalog, cap=1000), catalog, 1000)
        elif field in {"rate_n", "rate_d"}:
            price(**{"input_numerator" if field == "rate_n" else "input_denominator": value})
        elif field in {"cap", "limit", "version", "start", "end"}:
            name = {
                "version": "policy_version",
                "start": "period_start_utc",
                "end": "period_end_utc",
            }.get(field, field)
            kwargs = {name: value}
            if field == "start":
                kwargs["period_end_utc"] = MAX
            policy(catalog, **kwargs)
        else:
            clock = Clock()
            with CostLedger(
                tmp_path / "cost.sqlite", clock=clock.now, monotonic=clock.monotonic
            ) as ledger:
                settings = policy(catalog)
                ledger.apply_policy("p", settings)
                reservation = reserve(ledger, flat_request(), settings, "usage")
                usage(ledger, reservation, 1, value)

    if valid:
        attempt()
    else:
        with pytest.raises(
            SecurityError,
            match="^" + ("INVALID_AMOUNT" if field == "usage" else "COST_REQUEST_INVALID") + "$",
        ):
            attempt()


def test_independent_hand_calculations_and_no_cap_promotion() -> None:
    catalog = CostCatalog((price(),))
    assert cost.quote(text_request(), policy(catalog, cap=13), catalog, 1000).amount == 13
    assert cost.quote(text_request(33, 32), policy(catalog, cap=1000), catalog, 1000).amount == 111
    with pytest.raises(SecurityError, match="COST_CAP_EXCEEDED"):
        cost.quote(text_request(4096, 32), policy(catalog, cap=13), catalog, 1000)
    assert (
        cost.quote(text_request(4096, 32), policy(catalog, cap=2820), catalog, 1000).amount == 2820
    )
    assert cost.quote(text_request(), policy(catalog, cap=1000), catalog, 1000).amount == 13


def test_compiled_catalog_is_empty_and_canonical(monkeypatch: pytest.MonkeyPatch) -> None:
    assert cost_catalog.load_catalog().entries == ()
    catalog = CostCatalog((price(),))
    monkeypatch.setattr(cost_catalog, "_ENTRIES", catalog.entries)
    with pytest.raises(SecurityError, match="COST_QUOTE_MISMATCH"):
        cost_catalog.load_catalog()


@pytest.mark.parametrize(
    "code",
    [
        "COST_PRICE_UNKNOWN",
        "COST_PRICE_EXPIRED",
        "COST_BOUND_UNVERIFIED",
        "COST_CAP_REQUIRED",
        "COST_CAP_EXCEEDED",
        "COST_REQUEST_INVALID",
        "COST_AMOUNT_OVERFLOW",
        "COST_QUOTE_MISMATCH",
        "COST_CURRENCY_MISMATCH",
        "COST_CLOCK_INVALID",
    ],
    ids=lambda code: "G06-FIX1-CODE-" + code,
)
def test_single_cause_quote_codes_are_exact(code: str) -> None:
    from dataclasses import replace

    entry, request, now = price(), text_request(), 1000.0
    if code == "COST_PRICE_UNKNOWN":
        entry = replace(entry, price_as_of_utc=None, valid_from_utc=None, valid_until_utc=None)
    elif code == "COST_PRICE_EXPIRED":
        entry = replace(entry, valid_until_utc=1000)
    elif code == "COST_BOUND_UNVERIFIED":
        entry = replace(entry, bound_kind="unverified")
    elif code == "COST_REQUEST_INVALID":
        request = text_request(output=0)
    elif code == "COST_AMOUNT_OVERFLOW":
        entry = replace(entry, fixed_fee=MAX)
    elif code == "COST_CLOCK_INVALID":
        now = float("nan")
    catalog = CostCatalog((entry,))
    settings = policy(catalog, cap=MAX)
    if code in {"COST_CAP_REQUIRED", "COST_CAP_EXCEEDED"}:
        settings = replace(settings, cap=0 if code == "COST_CAP_REQUIRED" else 12)
    elif code == "COST_QUOTE_MISMATCH":
        settings = replace(settings, catalog_digest="0" * 64)
    elif code == "COST_CURRENCY_MISMATCH":
        settings = replace(settings, currency="EUR")
    with pytest.raises(SecurityError) as refused:
        cost.quote(request, settings, catalog, now)
    assert refused.value.code == code


@pytest.mark.parametrize(
    "protocol",
    ["text-fixture-v1", "audio-fixture-v1", "opaque-fixture-v1"],
    ids=lambda value: "G06-FIX1-CATALOG-" + value,
)
def test_production_catalog_never_selects_test_wire_profiles(
    monkeypatch: pytest.MonkeyPatch,
    protocol: str,
) -> None:
    catalog = CostCatalog((price(wire_protocol=protocol),))
    monkeypatch.setattr(cost_catalog, "_ENTRIES", catalog.entries)
    monkeypatch.setattr(cost_catalog, "_EXPECTED_DIGEST", catalog.sha256)
    with pytest.raises(SecurityError, match="^COST_BOUND_UNVERIFIED$"):
        cost_catalog.load_catalog()


def test_restart_clock_high_water_and_explicit_reset_keep_future_spending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace

    catalog = install_catalog(monkeypatch, flat_price(60, valid_until_utc=4000))
    clock, db = Clock(1000), tmp_path / "clock.sqlite"
    future = policy(catalog, cap=60, period_start_utc=1000, period_end_utc=3000)
    with CostLedger(db, clock=clock.now, monotonic=clock.monotonic) as ledger:
        ledger.apply_policy("p", future)
        reservation = reserve(ledger, flat_request(), future, "future")
        ledger.settle(reservation, 40)
        clock.utc = 1800
        ledger.apply_policy("p", replace(future, policy_version=2))
    clock.utc = 100
    with CostLedger(db, clock=clock.now, monotonic=clock.monotonic) as ledger:
        assert ledger.availability() == "COST_CLOCK_INVALID"
        with pytest.raises(SecurityError, match="^COST_CLOCK_INVALID$"):
            ledger.quote_request(flat_request(), future)
        with pytest.raises(SecurityError, match="^COST_CLOCK_INVALID$"):
            ledger.reset_clock(confirmed=False)
        assert (
            ledger._db.execute("SELECT clock_reset_audit FROM security_cost_meta_v2").fetchone()[0]
            == "[]"
        )
        ledger.reset_clock(confirmed=True)
        assert ledger.availability() is None
        witness = json.loads(db.with_name(db.name + ".cost-witness").read_text())
        assert witness["schema_version"] == 2 and witness["clock_reset_protocol_version"] == 1
        assert set(witness) == {
            "schema_version",
            "revision",
            "sha256",
            "clock_reset_protocol_version",
        }
        audits = json.loads(
            ledger._db.execute("SELECT clock_reset_audit FROM security_cost_meta_v2").fetchone()[0]
        )
        assert (
            len(audits) == 1
            and audits[0]["previous_high_water"] == 1800
            and audits[0]["utc"] == 100
        )
        present = replace(future, period_start_utc=0, period_end_utc=1000)
        ledger.apply_policy("p", present)
        observed = ledger.account_snapshot("p", "USD", 0, 1000)
        assert observed["confirmed"] == 40 and observed["available"] == 60
        reserve(ledger, flat_request(), present, "exact_remaining")
        with pytest.raises(SecurityError, match="^BUDGET_EXCEEDED$"):
            reserve(ledger, flat_request(), present, "exceeds")
    with CostLedger(db, clock=clock.now, monotonic=clock.monotonic) as ledger:
        assert ledger.availability() is None
        observed = ledger.account_snapshot("p", "USD", 0, 1000)
        assert observed["confirmed"] == 40 and observed["reserved"] == 60


def test_unavailable_ui_ledger_does_not_reauthenticate_corrupt_witness(tmp_path: Path) -> None:
    db = tmp_path / "bad.sqlite"
    with CostLedger(db):
        pass
    witness = db.with_name(db.name + ".cost-witness")
    witness.write_bytes(b"broken")
    before = db.read_bytes(), witness.read_bytes()
    with CostLedger.open_for_ui(db) as ledger:
        assert ledger.availability() == "LEDGER_ROLLBACK_DETECTED"
        with pytest.raises(SecurityError, match="^LEDGER_ROLLBACK_DETECTED$"):
            ledger.account_snapshot("p", "USD", 0, 2000)
        with pytest.raises(SecurityError, match="^LEDGER_ROLLBACK_DETECTED$"):
            ledger.reset_clock(confirmed=True)
    assert (db.read_bytes(), witness.read_bytes()) == before


def test_same_version_cannot_change_limit_or_clear_spending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace

    catalog = install_catalog(monkeypatch, price())
    settings, clock = policy(catalog), Clock()
    with CostLedger(tmp_path / "cost.sqlite", clock=clock.now) as ledger:
        ledger.apply_policy("p", settings)
        with pytest.raises(SecurityError, match="^BUDGET_POLICY_CHANGED$"):
            ledger.apply_policy("p", replace(settings, limit=99))
        assert ledger.account("p", "USD", 0, 2000)["amount_limit"] == 100


def test_witness_authenticates_empty_table_schema_as_well_as_rows(tmp_path: Path) -> None:
    with CostLedger(tmp_path / "schema.sqlite") as ledger:
        ledger._db.execute("ALTER TABLE security_cost_requests_v2 ADD COLUMN injected TEXT")
        with pytest.raises(SecurityError, match="^LEDGER_ROLLBACK_DETECTED$"):
            ledger.reservations("p")


@pytest.mark.parametrize("phase", ["quoted", "reserved"])
def test_quote_reuse_cache_does_not_retain_a_discarded_original_body(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    import gc
    import weakref

    catalog = install_catalog(monkeypatch, price())
    settings, clock = policy(catalog), Clock()
    with CostLedger(tmp_path / "lifetime.sqlite", clock=clock.now) as ledger:
        ledger.apply_policy("p", settings)
        request = text_request()
        observed = weakref.ref(request)
        quoted = ledger.quote_request(request, settings)
        if phase == "reserved":
            ledger.reserve_quote("discarded", quoted, settings, request)
        del request
        gc.collect()
        assert observed() is None
        assert balance(ledger)["reserved"] == (13 if phase == "reserved" else 0)


def test_unit_case_space_manifest() -> None:
    assert len(BALANCE) == len(set(BALANCE)) == 4 * 3 * 2 == 24
    assert len(EVENTS) == len(set(EVENTS)) == 5 * 7 * 2 == 70
    # bool/int equality must not merge distinct type partitions.
    coordinates = {(field, type(value).__name__, repr(value)) for field, value in NUMERIC}
    assert len(NUMERIC) == len(coordinates) == 10 * 12 == 120


# FIX2 inputs are auxiliary partitions; they never replace G06's 4,834 semantic IDs.
COV2_REQ = [
    ("operation", False),
    ("operation", "translate"),
    ("endpoint", "https://COST.invalid/v1/responses"),
    ("model_revision", ""),
    ("model_revision", None),
    ("model_revision", "x" * 257),
    ("api_version", ""),
    ("api_version", None),
    ("api_version", "x" * 257),
    ("body", b""),
    ("body", bytearray(b"x")),
    ("body", "over-limit"),
    ("headers", []),
    ("headers", (("content-type", "a"), ("content-type", "b"))),
    ("headers", (("only-one-item",),)),
    ("headers", (("content-type", "a"), ("anthropic-version", "b"))),
]
COV2_POLICY = [
    ("mode", False),
    ("mode", "automatic"),
    ("general_acknowledged", 1),
    ("catalog_digest", None),
    ("catalog_digest", "A" * 64),
    ("catalog_digest", "a" * 63),
    ("period_end_utc", 0),
]
COV2_PRICE = [
    (field, value)
    for field in ("model_revision", "api_version", "profile_id", "review_id", "wire_protocol")
    for value in ("", None, "x" * 257)
] + [
    ("operation", False),
    ("operation", "translate"),
    ("bound_kind", False),
    ("bound_kind", "guessed_tokens"),
    ("price_as_of_utc", None),
    ("valid_until_utc", 0),
    ("source_url", None),
    ("source_url", "http://source.invalid"),
    ("source_sha256", False),
    ("source_sha256", "g" * 64),
    ("output_denominator", 0),
    ("max_output", 0),
    ("fixed_fee", -1),
]


@pytest.mark.parametrize("field,value", COV2_REQ, ids=[f"G06-COV2-REQ-{i:03}" for i in range(16)])
def test_cov2_request_rejects_noncanonical_or_mutable_input(field: str, value: Any) -> None:
    if field == "body" and value == "over-limit":
        value = b"x" * (20 * 1024 * 1024 + 1)
    with pytest.raises(SecurityError, match="^COST_REQUEST_INVALID$"):
        text_request(**{field: value})


@pytest.mark.parametrize(
    "field,value", COV2_POLICY, ids=[f"G06-COV2-POLICY-{i:03}" for i in range(7)]
)
def test_cov2_policy_rejects_ambiguous_settings(field: str, value: Any) -> None:
    with pytest.raises(SecurityError, match="^COST_REQUEST_INVALID$"):
        policy(CostCatalog(()), **{field: value})


@pytest.mark.parametrize(
    "field,value", COV2_PRICE, ids=[f"G06-COV2-PRICE-{i:03}" for i in range(28)]
)
def test_cov2_price_evidence_requires_complete_typed_metadata(field: str, value: Any) -> None:
    with pytest.raises(SecurityError, match="^COST_REQUEST_INVALID$"):
        price(**{field: value})


COV2_HEADERS = [
    {False: "value"},
    {"Content-Type": None},
    {"Content-Type": "x" * 257},
    {"Content-Type": "a\rb"},
    {"Content-Type": "a\nb"},
    {"Content-Type": "first", "content-type": "second"},
]


@pytest.mark.parametrize(
    "headers", COV2_HEADERS, ids=[f"G06-COV2-HEADERS-{i:03}" for i in range(6)]
)
def test_cov2_cost_headers_do_not_accept_smuggling_or_case_duplicates(headers: Any) -> None:
    with pytest.raises(SecurityError, match="^COST_REQUEST_INVALID$"):
        cost.cost_headers(headers)


@pytest.mark.parametrize(
    "value", ["usd", True, "EURO"], ids=[f"G06-COV2-CURRENCY-{i:03}" for i in range(3)]
)
def test_cov2_currency_has_an_exact_closed_rejection(value: Any) -> None:
    with pytest.raises(SecurityError, match="^COST_CURRENCY_MISMATCH$"):
        cost.currency(value)


COV2_CLOCK = [(x, False) for x in (False, "1", -1, float("inf"), float("nan"), None, object())]
COV2_CLOCK += [(0, True), (12.25, True)]


@pytest.mark.parametrize(
    "value,valid", COV2_CLOCK, ids=[f"G06-COV2-CLOCK-{i:03}" for i in range(9)]
)
def test_cov2_clock_distinguishes_finite_numbers_from_ambiguous_values(
    value: Any, valid: bool
) -> None:
    if valid:
        assert cost.clock_value(value) == value
        assert type(cost.clock_value(value)) is float
    else:
        with pytest.raises(SecurityError, match="^COST_CLOCK_INVALID$"):
            cost.clock_value(value)


@pytest.mark.parametrize(
    "shape",
    ["list", "wrong-element", "duplicate"],
    ids=[f"G06-COV2-CATALOG-{i:03}" for i in range(3)],
)
def test_cov2_catalog_cannot_hide_duplicate_price_identity(shape: str) -> None:
    entry = price()
    entries: Any = (
        [entry] if shape == "list" else (object(),) if shape == "wrong-element" else (entry, entry)
    )
    with pytest.raises(SecurityError, match="^COST_REQUEST_INVALID$"):
        CostCatalog(entries)


def cov2_wire(case: str) -> tuple[CostRequest, PriceEntry | None]:
    """Build explicit synthetic real-wire envelopes; never call an SDK or HTTP."""
    import base64

    headers: dict[str, str] = {}
    provider, target, api, operation = "openai", URL, "v1", "summary"
    value: Any = {"model": "model", "input": "é", "instructions": "a", "max_output_tokens": 3}
    if case.startswith("anthropic"):
        provider, api = "anthropic", "2023-06-01"
        headers = {"anthropic-version": api}
        value = {
            "model": "model",
            "system": "서",
            "messages": [{"role": "user", "content": "é"}, {"role": "assistant", "content": "ok"}],
            "max_tokens": 3,
        }
    elif case.startswith("gemini"):
        provider, api = "gemini", "v1beta"
        target = "https://generativelanguage.googleapis.com/v1beta/models/model:generateContent"
        value = {
            "systemInstruction": {"parts": [{"text": "서"}]},
            "contents": [{"role": "user", "parts": [{"text": "é"}]}],
            "generationConfig": {"maxOutputTokens": 3},
        }
        inline = {"mimeType": "audio/wav", "data": base64.b64encode(audio_bytes(500)).decode()}
        if case in {
            "gemini-audio-valid",
            "gemini-mime",
            "gemini-base64",
            "gemini-inline-extra",
            "gemini-double-audio",
            "gemini-audio-summary",
        }:
            operation = "stt" if case != "gemini-audio-summary" else "summary"
            value.pop("systemInstruction")
            value["contents"][0]["parts"] = [{"inlineData": inline}]
            if case == "gemini-mime":
                inline["mimeType"] = "audio/mpeg"
            if case == "gemini-base64":
                inline["data"] = "not base64!"
            if case == "gemini-inline-extra":
                inline["billing"] = "untrusted"
            if case == "gemini-double-audio":
                value["contents"][0]["parts"].append({"inlineData": dict(inline)})
    if case.startswith("fixture-"):
        value = {"model": "model", "text": "x", "max_output_tokens": 1}
        if case == "fixture-extra":
            value["extra"] = True
        elif case == "fixture-model":
            value["model"] = "other"
        else:
            value["text"] = 3
        return CostRequest(
            "p", URL, "model", "v1", "summary", "transcript", json.dumps(value).encode()
        ), price()
    if case.startswith("multipart"):
        provider, operation = "openai", "stt"
        boundary = "recoryn-cov2-boundary"
        headers = {"content-type": "multipart/form-data; boundary=" + boundary}
        fields: list[tuple[str | None, bytes]] = [("model", b"model"), ("file", audio_bytes(500))]
        if case == "multipart-provider":
            provider = "anthropic"
        if case == "multipart-operation":
            operation = "summary"
        if case == "multipart-extra-field":
            fields.append(("billing", b"x"))
        if case == "multipart-duplicate":
            fields.append(("model", b"model"))
        if case == "multipart-model-missing":
            fields = fields[1:]
        if case == "multipart-model-other":
            fields[0] = ("model", b"other")
        if case == "multipart-file-missing":
            fields = fields[:1]
        if case == "multipart-part-name":
            fields[1] = (None, fields[1][1])
        parts = []
        for name, payload in fields:
            disposition = "form-data" + ('; name="' + name + '"' if name is not None else "")
            media = ""
            if case == "multipart-nested" and name == "file":
                media = "Content-Type: multipart/mixed; boundary=inner\r\n"
                payload = (
                    b"--inner\r\nContent-Type: audio/wav\r\n\r\n" + payload + b"\r\n--inner--\r\n"
                )
            if case == "multipart-part-defect" and name == "file":
                media = "this header has no colon\r\n"
            parts.append(
                (
                    "--"
                    + boundary
                    + "\r\nContent-Disposition: "
                    + disposition
                    + "\r\n"
                    + media
                    + "\r\n"
                ).encode()
                + payload
                + b"\r\n"
            )
        body = b"".join(parts) + ("--" + boundary + "--\r\n").encode()
        if case == "multipart-no-boundary":
            headers["content-type"] = "multipart/form-data"
        if case == "multipart-broken":
            body = b"not a MIME envelope"
    elif case.startswith("wav-"):
        body = audio_bytes(0 if case == "wav-empty" else 500)
        if case == "wav-rate-zero":
            body = body[:24] + b"\0\0\0\0" + body[28:]
        if case == "wav-short":
            body = body[:-1]
            body = body[:4] + (len(body) - 8).to_bytes(4, "little") + body[8:]
        operation = "stt"
        request = CostRequest("p", URL, "model", "v1", operation, "audio", body)
        return request, price(
            operation="stt",
            wire_protocol="audio-fixture-v1",
            bound_kind="audio_seconds",
            output_numerator=0,
        )
    else:
        if case == "openai-extra":
            value["billing"] = "unknown"
        if case == "openai-model":
            value["model"] = "other"
        if case == "openai-input":
            value["input"] = []
        if case == "openai-instructions":
            value["instructions"] = 3
        if case == "openai-output-large":
            value["max_output_tokens"] = 131073
        if case == "openai-stt":
            operation = "stt"
        if case == "anthropic-extra":
            value["billing"] = "unknown"
        if case == "anthropic-model":
            value["model"] = "other"
        if case == "anthropic-version":
            headers["anthropic-version"] = "wrong"
        if case == "anthropic-message-extra":
            value["messages"][0]["extra"] = "unknown"
        if case == "anthropic-role":
            value["messages"][0]["role"] = "system"
        if case == "anthropic-content":
            value["messages"][0]["content"] = []
        if case == "anthropic-system":
            value["system"] = 3
        if case == "anthropic-messages-missing":
            del value["messages"]
        if case == "gemini-extra":
            value["billing"] = "unknown"
        if case == "gemini-endpoint":
            target += "/different"
        if case == "gemini-system":
            value["systemInstruction"]["extra"] = True
        if case == "gemini-content-extra":
            value["contents"][0]["extra"] = True
        if case == "gemini-role":
            value["contents"][0]["role"] = "assistant"
        if case == "gemini-text":
            value["contents"][0]["parts"] = [{"text": 3}]
        if case == "gemini-part":
            value["contents"][0]["parts"] = [{"unknown": "data"}]
        if case == "gemini-config-extra":
            value["generationConfig"]["unknown"] = 1
        if case == "gemini-config-output":
            del value["generationConfig"]["maxOutputTokens"]
        if case == "unknown-provider":
            provider = "unrecognized"
        body = json.dumps(value, separators=(",", ":")).encode()
        special = {
            "json-array": b"[]",
            "json-duplicate": b'{"input":"a","input":"b"}',
            "json-nan": b'{"input":NaN}',
            "json-invalid": b"{",
        }
        body = special.get(case, body)
    request = CostRequest(
        provider,
        target,
        "model",
        api,
        operation,
        "audio" if operation == "stt" else "transcript",
        body,
        cost.cost_headers(headers),
    )
    return request, None


COV2_WIRE = [
    "fixture-extra",
    "fixture-model",
    "fixture-text",
    "json-array",
    "json-duplicate",
    "json-nan",
    "json-invalid",
    "openai-extra",
    "openai-model",
    "openai-input",
    "openai-instructions",
    "openai-output-large",
    "openai-stt",
    "anthropic-extra",
    "anthropic-model",
    "anthropic-version",
    "anthropic-message-extra",
    "anthropic-role",
    "anthropic-content",
    "anthropic-system",
    "anthropic-messages-missing",
    "gemini-extra",
    "gemini-endpoint",
    "gemini-system",
    "gemini-content-extra",
    "gemini-role",
    "gemini-text",
    "gemini-part",
    "gemini-mime",
    "gemini-base64",
    "gemini-inline-extra",
    "gemini-double-audio",
    "gemini-audio-summary",
    "gemini-config-extra",
    "gemini-config-output",
    "multipart-provider",
    "multipart-operation",
    "multipart-no-boundary",
    "multipart-broken",
    "multipart-part-name",
    "multipart-extra-field",
    "multipart-duplicate",
    "multipart-model-missing",
    "multipart-model-other",
    "multipart-file-missing",
    "multipart-nested",
    "multipart-part-defect",
    "wav-empty",
    "wav-rate-zero",
    "wav-short",
    "unknown-provider",
]


@pytest.mark.parametrize("case", COV2_WIRE, ids=lambda case: "G06-COV2-WIRE-" + case)
def test_cov2_wire_rejection_has_a_single_visible_error(case: str) -> None:
    request, entry = cov2_wire(case)
    with pytest.raises(SecurityError, match="^COST_REQUEST_INVALID$"):
        cost.inspect_wire(request, entry)


@pytest.mark.parametrize("slot", range(3), ids=[f"G06-COV2-QUOTE-type-{i}" for i in range(3)])
def test_cov2_quote_rejects_wrong_dto_kinds(slot: int) -> None:
    catalog = CostCatalog((price(),))
    arguments: list[Any] = [text_request(), policy(catalog), catalog]
    arguments[slot] = object()
    with pytest.raises(SecurityError, match="^COST_REQUEST_INVALID$"):
        cost.quote(*arguments, 1000)


@pytest.mark.parametrize(
    "shape,mode",
    [
        (shape, mode)
        for shape in ("text-as-audio", "audio-as-text", "audio-output-rate")
        for mode in ("strict", "general")
    ],
    ids=[f"G06-COV2-QUOTE-bound-{i}" for i in range(6)],
)
def test_cov2_unproved_pricing_never_becomes_verified(shape: str, mode: str) -> None:
    if shape == "text-as-audio":
        request = text_request()
        entry = price(bound_kind="audio_seconds", output_numerator=0)
    else:
        request = CostRequest("p", URL, "model", "v1", "stt", "audio", audio_bytes(500))
        entry = price(
            operation="stt",
            wire_protocol="audio-fixture-v1",
            bound_kind="text_bytes" if shape == "audio-as-text" else "audio_seconds",
        )
    catalog = CostCatalog((entry,))
    settings = policy(catalog, mode=mode, general_acknowledged=True, cap=77)
    if mode == "strict":
        with pytest.raises(SecurityError, match="^COST_BOUND_UNVERIFIED$"):
            cost.quote(request, settings, catalog, 1000)
    else:
        quoted = cost.quote(request, settings, catalog, 1000)
        assert (quoted.kind, quoted.amount, quoted.reason) == (
            "USER_CAP",
            77,
            "COST_BOUND_UNVERIFIED",
        )
        assert quoted.input_upper is quoted.output_upper is None


@pytest.mark.parametrize("_case", ["G06-COV2-QUOTE-overflow"], ids=str)
def test_cov2_input_overhead_cannot_wrap_the_money_bound(_case: str) -> None:
    catalog = CostCatalog((price(input_overhead=MAX),))
    with pytest.raises(SecurityError, match="^COST_AMOUNT_OVERFLOW$"):
        cost.quote(text_request(), policy(catalog), catalog, 1000)


@pytest.mark.parametrize(
    "case,input_upper,output_upper,amount",
    [
        ("openai-valid", 6, 3, 19),
        ("anthropic-valid", 10, 3, 22),
        ("gemini-valid", 8, 3, 21),
        ("gemini-audio-valid", 1, 0, 11),
        ("multipart-valid", 1, 0, 11),
    ],
    ids=[f"G06-COV2-POS-wire-{i}" for i in range(5)],
)
def test_cov2_real_wire_bounds_use_literal_utf8_and_audio_oracles(
    case: str, input_upper: int, output_upper: int, amount: int
) -> None:
    request, _ = cov2_wire(case)
    audio = request.operation == "stt"
    entry = price(
        provider_id=request.provider_id,
        endpoint=request.endpoint,
        api_version=request.api_version,
        operation=request.operation,
        wire_protocol=request.provider_id,
        bound_kind="audio_seconds" if audio else "text_bytes",
        **({"input_numerator": 7, "input_denominator": 2, "output_numerator": 0} if audio else {}),
    )
    catalog = CostCatalog((entry,))
    quoted = cost.quote(request, policy(catalog), catalog, 1000)
    assert (quoted.kind, quoted.input_upper, quoted.output_upper, quoted.amount) == (
        "VERIFIED",
        input_upper,
        output_upper,
        amount,
    )


@pytest.mark.parametrize("_case", ["G06-COV2-POS-fingerprints"], ids=str)
def test_cov2_fingerprints_are_independent_canonical_json_digests(_case: str) -> None:
    import hashlib

    request = CostRequest("p", URL, "model", "v1", "summary", "transcript", b"abc")
    body_sha = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    metadata = {
        "provider_id": "p",
        "endpoint": URL,
        "model_revision": "model",
        "api_version": "v1",
        "operation": "summary",
        "data_type": "transcript",
        "headers": (),
        "body_sha256": body_sha,
        "byte_length": 3,
    }

    def sha(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    request_sha = sha(metadata)
    assert request.metadata() == metadata and request.fingerprint == request_sha
    policy_values = dict(
        mode="general",
        currency="USD",
        period_start_utc=0,
        period_end_utc=2000,
        cap=7,
        limit=100,
        policy_version=1,
        catalog_digest=CostCatalog(()).sha256,
        general_acknowledged=True,
    )
    settings = CostPolicy(**policy_values)
    assert settings.fingerprint == sha(policy_values)
    expected = dict(
        request_fingerprint=request_sha,
        body_sha256=body_sha,
        byte_length=3,
        kind="USER_CAP",
        amount=7,
        reason="COST_PRICE_UNKNOWN",
        input_upper=None,
        output_upper=None,
        price_as_of_utc=None,
        valid_from_utc=None,
        valid_until_utc=None,
        profile_id=None,
        policy=policy_values,
    )
    quoted = cost.CostQuote(**{**expected, "policy": settings})
    assert quoted.fingerprint == sha(expected)


@pytest.mark.parametrize("_case", ["G06-COV2-POS-headers"], ids=str)
def test_cov2_header_filter_and_api_version_preserve_only_billing_facts(_case: str) -> None:
    assert cost.cost_headers(
        {
            "Authorization": "G06-CANARY-SECRET",
            "X-Ignored": object(),
            "Content-Type": "application/json",
            "Anthropic-Version": "2023-06-01",
        }
    ) == (("anthropic-version", "2023-06-01"), ("content-type", "application/json"))
    assert (
        cost.wire_api_version("anthropic", URL, {"Anthropic-Version": "2023-06-01"}) == "2023-06-01"
    )
    assert cost.wire_api_version("anthropic", URL, None) == "unversioned"
    assert (
        cost.wire_api_version("openai", "https://cost.invalid/not-versioned", None) == "unversioned"
    )
    assert (
        cost.wire_api_version("gemini", "https://cost.invalid/v1beta2/models/x", None) == "v1beta2"
    )


@pytest.mark.parametrize("_case", ["G06-COV2-MANIFEST"], ids=str)
def test_cov2_literal_input_manifest_is_unique(_case: str) -> None:
    assert (
        len(COV2_REQ),
        len(COV2_POLICY),
        len(COV2_PRICE),
        len(COV2_HEADERS),
        len(COV2_CLOCK),
        len(COV2_WIRE),
    ) == (16, 7, 28, 6, 9, 51)
    assert len(set(COV2_WIRE)) == 51
