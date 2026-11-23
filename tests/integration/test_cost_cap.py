"""G06 actual wire, expiry, scope, handoff and durable migration boundaries.

Synthetic prices have independent literal charges; all transports are in-memory.
"""

from __future__ import annotations

import importlib.util
import itertools
import json
import shutil
import sqlite3
import sys
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
    CostCatalog,
    CostLedger,
    CostRequest,
    Gateway,
    SecurityError,
)
from recoryn.security.cost import quote
from recoryn.storage import Library
from tests.unit.test_cost_cap import (
    Clock,
    audio_bytes,
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

pytestmark = pytest.mark.integration
AUDIO = list(
    itertools.product(
        ("valid", "unknown", "expired"),
        (0, 1, 999, 1000, 1001),
        ("duration", "tokens_unknown", "bad_header"),
        ("none", "small", "exact", "large"),
        ("strict", "general"),
    )
)
BIND = list(itertools.product((False, True), repeat=8))
PRICE_TIME = list(
    itertools.product(
        (999, 1000, 1099, 1100, 1101),
        ("reserve", "open", "second_write"),
        (False, True),
        ("strict", "general"),
    )
)
ORDER = list(
    itertools.product(range(4), ("grant", "session", "cancel"), ("normal", "open_fail", "partial"))
)
PERIOD = list(
    itertools.product(
        (True, False),
        (999, 1000, 1999, 2000, 2001),
        (None, "RESERVED", "UNKNOWN", "SETTLED"),
        ("strict", "general"),
    )
)
DB = list(range(1, 17))
LOCAL = ("faster_whisper", "ollama", "unverified_remote")


def test_integration_case_space_manifest() -> None:
    for rows, expected in (
        (AUDIO, 360),
        (BIND, 256),
        (PRICE_TIME, 60),
        (ORDER, 36),
        (PERIOD, 80),
        (DB, 16),
        (LOCAL, 3),
    ):
        assert len(rows) == len(set(rows)) == expected
    assert 360 + 256 + 60 + 36 + 80 + 16 + 3 == 811


@pytest.mark.parametrize(
    "field", ["request", "meta"], ids=["G06-AUX-WITNESS-request", "G06-AUX-WITNESS-meta"]
)
def test_v2_quote_and_meta_tampering_cannot_hide_behind_legacy_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    catalog = install_catalog(monkeypatch, price())
    settings, clock = policy(catalog), Clock()
    with CostLedger(tmp_path / "cost.sqlite", clock=clock.now, monotonic=clock.monotonic) as ledger:
        ledger.apply_policy("p", settings)
        reserve(ledger, text_request(), settings, "tampered")
        original_revision = ledger._db.execute(
            "SELECT revision FROM security_cost_meta"
        ).fetchone()[0]
        if field == "request":
            ledger._db.execute("UPDATE security_cost_requests_v2 SET quote_json='{}'")
        else:
            ledger._db.execute("UPDATE security_cost_meta_v2 SET adopted_providers='[\"other\"]'")
        assert (
            ledger._db.execute("SELECT revision FROM security_cost_meta").fetchone()[0]
            == original_revision
        )
        with pytest.raises(SecurityError, match="LEDGER_ROLLBACK_DETECTED"):
            ledger.reservations("p")


def test_currency_is_part_of_the_account_identity_without_a_price_mismatch_mask(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = install_catalog(
        monkeypatch,
        flat_price(13, model_revision="usd-model", currency="USD"),
        flat_price(13, model_revision="eur-model", currency="EUR"),
    )
    clock = Clock()
    with CostLedger(tmp_path / "cost.sqlite", clock=clock.now, monotonic=clock.monotonic) as ledger:
        usd = policy(catalog, cap=13)
        eur = replace(usd, currency="EUR")
        usd_id, eur_id = ledger.apply_policy("p", usd), ledger.apply_policy("p", eur)
        assert usd_id != eur_id
        reserve(ledger, replace(flat_request(13), model_revision="eur-model"), eur, "eur-request")
        assert balance(ledger, currency_code="EUR")["reserved"] == 13
        assert balance(ledger, currency_code="USD")["reserved"] == 0
        assert ledger.reservations("p")[0]["currency"] == "EUR"


@pytest.mark.parametrize(
    "case,cap,mode,expected",
    [
        ("small", 2819, "strict", "COST_CAP_EXCEEDED"),
        ("exact", 2820, "strict", "VERIFIED"),
        ("unknown", 2820, "strict", "COST_PRICE_UNKNOWN"),
        ("expired", 2820, "strict", "COST_PRICE_EXPIRED"),
        ("unverified-general", 13, "general", "USER_CAP"),
    ],
    ids=[f"G06-AUX-P1-{i}" for i in range(5)],
)
def test_original_counterexample_at_actual_fake_transport_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    cap: int,
    mode: str,
    expected: str,
) -> None:
    # Hand oracle: ceil(2*(4096+3)/3) + ceil(5*32/2) + 7 = 2820.
    entry = price(valid_until_utc=1000 if case == "expired" else 2000)
    if case in {"unknown", "unverified-general"}:
        entry = replace(entry, price_as_of_utc=None, valid_from_utc=None, valid_until_utc=None)
    catalog = install_catalog(monkeypatch, entry)
    settings = policy(
        catalog, cap=cap, limit=10000, mode=mode, general_acknowledged=mode == "general"
    )
    request, clock, wire = text_request(4096, 32), Clock(), Wire()
    with (
        ConsentStore(tmp_path / "consent.sqlite") as consent,
        CostLedger(tmp_path / "cost.sqlite", clock=clock.now, monotonic=clock.monotonic) as ledger,
    ):
        view = gateway(consent, ledger, wire, request)
        view.chunk_bytes = len(request.body)
        ledger.apply_policy("p", settings)
        if expected.startswith("COST_"):
            with pytest.raises(SecurityError, match=expected):
                reservation = reserve(ledger, request, settings, "large-input")
                view.request(
                    "p",
                    request.endpoint,
                    request.data_type,
                    request.body,
                    reservation_id=reservation,
                )
            assert wire.opens == 0 and wire.writes == []
            assert balance(ledger)["reserved"] == balance(ledger)["unknown_exposure"] == 0
        else:
            reservation = reserve(ledger, request, settings, "large-input")
            assert (
                view.request(
                    "p",
                    request.endpoint,
                    request.data_type,
                    request.body,
                    reservation_id=reservation,
                )
                == b"OK"
            )
            assert wire.opens == 1 and b"".join(wire.writes) == request.body
            record = ledger.reservations("p")[0]
            assert record["quote_kind"] == expected
            assert record["amount_microunits"] == (2820 if expected == "VERIFIED" else 13)
            assert record["input_upper"] == (4099 if expected == "VERIFIED" else None)
            assert record["output_upper"] == (32 if expected == "VERIFIED" else None)


@pytest.mark.parametrize(
    "mode", ["strict", "general"], ids=["G06-AUX-EMPTY-strict", "G06-AUX-EMPTY-general"]
)
def test_empty_production_catalog_and_real_wire_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    catalog = install_catalog(monkeypatch)
    clock, wire = Clock(), Wire()
    settings = policy(catalog, cap=13, mode=mode, general_acknowledged=mode == "general")
    request = CostRequest(
        "openai",
        "https://empty.invalid/v1/responses",
        "unpriced-model",
        "v1",
        "summary",
        "transcript",
        b'{"model":"unpriced-model","input":"synthetic text","max_output_tokens":1}',
    )
    with (
        ConsentStore(tmp_path / "consent.sqlite") as consent,
        CostLedger(tmp_path / "cost.sqlite", clock=clock.now, monotonic=clock.monotonic) as ledger,
    ):
        view = gateway(consent, ledger, wire, request)
        view.chunk_bytes = len(request.body)
        ledger.apply_policy("openai", settings)
        if mode == "strict":
            with pytest.raises(SecurityError, match="COST_PRICE_UNKNOWN"):
                reserve(ledger, request, settings, "unpriced")
            assert wire.opens == 0 and wire.writes == []
        else:
            reservation = reserve(ledger, request, settings, "unpriced")
            assert (
                view.request(
                    "openai",
                    request.endpoint,
                    "transcript",
                    request.body,
                    reservation_id=reservation,
                )
                == b"OK"
            )
            row = ledger.reservations("openai")[0]
            assert (row["quote_kind"], row["amount_microunits"]) == ("USER_CAP", 13)
            assert row["input_upper"] is row["output_upper"] is row["price_as_of_utc"] is None
            assert wire.opens == 1 and b"".join(wire.writes) == request.body


class Wire:
    def __init__(self) -> None:
        self.opens = 0
        self.writes: list[bytes] = []
        self.response = b"OK"
        self.on_open: Callable[[], None] = lambda: None
        self.on_write: Callable[[], None] = lambda: None
        self.fail_open = self.fail_write = False
        self.closed = False

    def open(self, target: Any, headers: Mapping[str, str], size: int, timeout: float) -> Wire:
        self.opens += 1
        self.on_open()
        if self.fail_open:
            raise OSError("private-open-canary")
        return self

    def write(self, data: bytes, timeout: float) -> None:
        if self.fail_write:
            self.writes.append(data[:1])
            self.on_write()
            raise OSError("private-partial-canary")
        self.writes.append(data)
        self.on_write()

    def read(self, maximum: int, timeout: float) -> bytes:
        result, self.response = self.response[:maximum], self.response[maximum:]
        return result

    def close(self) -> None:
        self.closed = True


def gateway(consent: ConsentStore, ledger: CostLedger, wire: Wire, request: CostRequest) -> Gateway:
    scope = ConsentScope.session("s")
    consent.bind_session("s")
    version = consent.policy_version
    context = ConsentRequest("s", 0, request.operation, version)
    consent.grant(
        request.provider_id,
        request.endpoint,
        request.data_type,
        capability=request.operation,
        scope=scope,
        policy_version=version,
    )
    bindings = consent.capture_bindings(
        request.provider_id, request.endpoint, (request.data_type,), scope=scope, request=context
    )
    return Gateway(
        consent, ledger=ledger, transport=wire, expected_grants=bindings, chunk_bytes=3
    ).for_session("s", capability=request.operation, scope=scope, policy_version=version)


@pytest.mark.parametrize("row", AUDIO, ids=[f"G06-AUDIO-{i:03}" for i in range(360)])
def test_audio_duration_and_payload_boundaries(row: Any) -> None:
    status, milliseconds, bounded, cap_kind, mode = row
    # One-second ceiling, 11 micro-units per begun second plus fixed 7.
    upper = {0: 7, 1: 18, 999: 18, 1000: 18, 1001: 29}[milliseconds]
    cap = {"none": 0, "small": upper - 1, "exact": upper, "large": upper + 1}[cap_kind]
    entry = price(
        operation="stt",
        wire_protocol="audio-fixture-v1",
        bound_kind="audio_seconds",
        input_numerator=11,
        input_denominator=1,
        output_numerator=0,
        input_overhead=0,
        max_input=4096,
    )
    if bounded == "tokens_unknown":
        entry = replace(entry, bound_kind="unverified")
    if status == "unknown":
        entry = replace(entry, price_as_of_utc=None, valid_from_utc=None, valid_until_utc=None)
    elif status == "expired":
        entry = replace(entry, valid_until_utc=1000)
    catalog = CostCatalog((entry,))
    settings = policy(catalog, mode=mode, cap=cap, general_acknowledged=mode == "general")
    body = audio_bytes(milliseconds)
    if bounded == "bad_header":
        body = body[:4] + (len(body) + 100).to_bytes(4, "little") + body[8:]
    request = text_request(operation="stt", data_type="audio", body=body)
    unknown = status != "valid" or bounded == "tokens_unknown"
    accepted = milliseconds > 0 and bounded != "bad_header" and cap > 0
    accepted &= mode == "general" or not unknown
    accepted &= unknown or cap >= upper
    if accepted:
        quoted = quote(request, settings, catalog, 1000)
        assert (quoted.kind, quoted.amount) == (
            ("USER_CAP", cap) if unknown else ("VERIFIED", upper)
        )
    else:
        expected_code = (
            "COST_CAP_REQUIRED"
            if cap <= 0
            else "COST_REQUEST_INVALID"
            if milliseconds == 0 or bounded == "bad_header"
            else "COST_PRICE_UNKNOWN"
            if status == "unknown" and mode == "strict"
            else "COST_PRICE_EXPIRED"
            if status == "expired" and mode == "strict"
            else "COST_BOUND_UNVERIFIED"
            if bounded == "tokens_unknown" and mode == "strict"
            else "COST_CAP_EXCEEDED"
        )
        with pytest.raises(SecurityError, match="^" + expected_code + "$"):
            quote(request, settings, catalog, 1000)


@pytest.mark.parametrize("bits", BIND, ids=[f"G06-BIND-{i:03}" for i in range(256)])
def test_actual_dispatch_cannot_retarget_a_quote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bits: Any
) -> None:
    catalog = install_catalog(monkeypatch, price())
    settings, clock, original = policy(catalog), Clock(), text_request()
    with (
        ConsentStore(tmp_path / "consent.sqlite") as consent,
        CostLedger(
            tmp_path / "cost.sqlite",
            clock=clock.now,
            monotonic=clock.monotonic,
        ) as ledger,
    ):
        ledger.apply_policy("p", settings)
        reservation = reserve(ledger, original, settings, "request")
        provider, endpoint = (
            ("q" if bits[0] else "p"),
            original.endpoint + ("/other" if bits[1] else ""),
        )
        value = json.loads(original.body)
        headers: dict[str, str] = {}
        if bits[2]:
            value["model"] = "other-model"
            headers["anthropic-version"] = "v2"
        if bits[4]:
            value["text"] = "y"
        if bits[5]:
            value["max_output_tokens"] = 2
        # Preserve the original exact wire in the unmutated row.
        body = json.dumps(value, separators=(",", ":")).encode()
        actual = replace(
            original,
            provider_id=provider,
            endpoint=endpoint,
            operation="stt" if bits[3] else "summary",
            body=body,
        )
        if bits[6]:
            install_catalog(monkeypatch, price(), price(model_revision="new-profile"))
        if bits[7]:
            ledger.apply_policy("p", replace(settings, policy_version=2))
        wire = Wire()
        # Authorize the actual destination/feature so consent cannot mask a cost
        # binding defect. The old reservation must itself reject retargeting.
        view = gateway(consent, ledger, wire, actual)
        if any(bits):
            # Composite rows may fail at any independent, earlier guard.
            expected_codes = set()
            if bits[0]:
                expected_codes.add("RESERVATION_NOT_DISPATCHABLE")
            if any(bits[1:7]):
                expected_codes.add("COST_QUOTE_MISMATCH")
            if bits[7]:
                expected_codes.add("BUDGET_POLICY_CHANGED")
            with pytest.raises(SecurityError) as refused:
                view.request(
                    provider,
                    endpoint,
                    actual.data_type,
                    body,
                    headers=headers,
                    reservation_id=reservation,
                )
            assert refused.value.code in expected_codes
            assert wire.opens == 0 and not wire.writes
            assert balance(ledger)["reserved"] == 13
        else:
            assert (
                view.request(provider, endpoint, actual.data_type, body, reservation_id=reservation)
                == b"OK"
            )
            assert wire.opens == 1 and b"".join(wire.writes) == original.body
            assert balance(ledger)["unknown_exposure"] == 13


@pytest.mark.parametrize("row", PRICE_TIME, ids=[f"G06-PRICE-TIME-{i:03}" for i in range(60)])
def test_price_time_at_reserve_open_and_next_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, row: Any
) -> None:
    now, phase, reversed_clock, mode = row
    catalog = install_catalog(
        monkeypatch, price(price_as_of_utc=1000, valid_from_utc=1000, valid_until_utc=1100)
    )
    settings = policy(catalog, mode=mode, general_acknowledged=mode == "general")
    clock = Clock(now if phase == "reserve" else 1000)
    request, wire = text_request(), Wire()
    with CostLedger(tmp_path / "cost.sqlite", clock=clock.now, monotonic=clock.monotonic) as ledger:
        ledger.apply_policy("p", settings)
        reservation = "missing"
        if phase != "reserve":
            reservation = reserve(ledger, request, settings, "request")
            if phase == "second_write":
                ledger.validate_dispatch(
                    reservation,
                    "p",
                    request.endpoint,
                    request.body,
                    data_type=request.data_type,
                    operation="summary",
                    dispatch_id="dispatch",
                )
                wire.open(None, {}, len(request.body), 1)
                ledger.validate_dispatch(
                    reservation,
                    "p",
                    request.endpoint,
                    request.body,
                    data_type=request.data_type,
                    operation="summary",
                    dispatch_id="dispatch",
                    phase="write",
                    bytes_sent=5,
                )
                ledger.mark_unknown(reservation)
                wire.write(b"first", 1)
        if reversed_clock:
            clock.utc = now + 1
            try:
                ledger.quote_request(request, settings)
            except SecurityError:
                pass  # The clock high-water still advanced before price refusal.
        clock.utc = now
        accepted = not reversed_clock and 1000 <= now < 1100
        if phase == "reserve" and mode == "general" and not reversed_clock:
            accepted = True

        def action() -> None:
            if phase == "reserve":
                reserve(ledger, request, settings, "request")
            else:
                ledger.validate_dispatch(
                    reservation,
                    "p",
                    request.endpoint,
                    request.body,
                    data_type=request.data_type,
                    operation="summary",
                    dispatch_id="dispatch",
                    phase="open" if phase == "open" else "write",
                    bytes_sent=9 if phase == "second_write" else None,
                )
                if phase == "open":
                    wire.open(None, {}, len(request.body), 1)
                else:
                    wire.write(b"next", 1)

        if accepted:
            action()
        else:
            expected_code = (
                "COST_CLOCK_INVALID"
                if reversed_clock or now < 1000 and phase != "reserve"
                else "COST_PRICE_EXPIRED"
                if phase == "reserve"
                else "COST_QUOTE_EXPIRED"
            )
            with pytest.raises(SecurityError, match="^" + expected_code + "$"):
                action()
        assert wire.opens == (int(accepted) if phase == "open" else int(phase == "second_write"))
        assert wire.writes == (
            [b"first", b"next"]
            if phase == "second_write" and accepted
            else [b"first"]
            if phase == "second_write"
            else []
        )
        if phase == "second_write":
            assert balance(ledger)["unknown_exposure"] == 13


@pytest.mark.parametrize("row", PERIOD, ids=[f"G06-PERIOD-{i:03}" for i in range(80)])
def test_currency_period_and_old_unsettled_exposure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, row: Any
) -> None:
    currency_matches, now, previous, mode = row
    catalog = install_catalog(monkeypatch, flat_price(13, valid_until_utc=3000))
    clock, request = Clock(999), flat_request(13)
    with CostLedger(tmp_path / "cost.sqlite", clock=clock.now, monotonic=clock.monotonic) as ledger:
        if previous is not None:
            old = policy(catalog, period_end_utc=1000)
            ledger.apply_policy("p", old)
            prior = reserve(ledger, request, old, "previous")
            if previous == "UNKNOWN":
                ledger.mark_unknown(prior)
            elif previous == "SETTLED":
                ledger.settle(prior, 13)
        current = policy(
            catalog,
            period_start_utc=1000,
            currency="USD" if currency_matches else "EUR",
            mode=mode,
            general_acknowledged=mode == "general",
        )
        ledger.apply_policy("p", current)
        clock.utc = now
        accepted = currency_matches and 1000 <= now < 2000 and previous in (None, "SETTLED")
        if accepted:
            reserve(ledger, request, current, "current")
        else:
            expected_code = (
                "COST_CLOCK_INVALID"
                if now < 999
                else "COST_CURRENCY_MISMATCH"
                if not currency_matches
                else "COST_PERIOD_CHANGED"
                if not 1000 <= now < 2000
                else "COST_UNRESOLVED_EXPOSURE"
            )
            with pytest.raises(SecurityError, match="^" + expected_code + "$"):
                reserve(ledger, request, current, "current")
        observed = ledger.account_snapshot("p", current.currency, 1000, 2000)
        assert observed["reserved"] == (13 if accepted else 0)
        if previous == "UNKNOWN":
            assert ledger.account_snapshot("p", "USD", 0, 1000)["unknown_exposure"] == 13


@pytest.mark.parametrize("row", ORDER, ids=[f"G06-ORDER-{i:03}" for i in range(36)])
def test_revocation_and_cost_handoff_orders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, row: Any
) -> None:
    from PySide6.QtWidgets import QApplication

    from recoryn.providers import ProviderError
    from recoryn.providers._common import Run
    from recoryn.security import CredentialVault
    from recoryn.ui.privacy import PrivacyPanel
    from tests.ui.test_cost_cap_ui import URL, Vault, configure

    position, invalidation, failure = row
    app = QApplication.instance() or QApplication([])
    install_catalog(
        monkeypatch,
        price(
            provider_id="openai",
            endpoint=URL,
            wire_protocol="opaque-fixture-v1",
            fixed_fee=60,
            input_numerator=0,
            output_numerator=0,
            input_overhead=0,
        ),
    )
    clock, wire, cancel = Clock(), Wire(), threading.Event()
    db = tmp_path / "privacy.sqlite"
    with (
        ConsentStore(db) as consents,
        CostLedger(db, clock=clock.now, monotonic=clock.monotonic) as ledger,
    ):
        panel = PrivacyPanel(
            consents,
            ledger,
            CredentialVault(backend=Vault(), namespace="g06-order"),
            gateway=Gateway(consents, transport=wire, chunk_bytes=3),
        )
        try:
            control = configure(panel, "summary", 60)
            panel._action("summary", "budget")
            control.key.setText("FAKE-ORDER-KEY")
            panel._action("summary", "save")
            panel._action("summary", "grant")
            control.data_type.setCurrentIndex(control.data_type.findData("context"))
            panel._action("summary", "grant")
            plan = panel.prepare_execution("summary", "s", cancel)
            assert plan.gateway is not None and plan.context.reservation_factory is not None
            request = CostRequest("openai", URL, "model", "v1", "summary", "transcript", b"abcdef")

            def invalidate() -> None:
                if invalidation == "cancel":
                    cancel.set()
                elif invalidation == "session":
                    consents.revoke_session("s")
                else:
                    consents.revoke(
                        "openai",
                        URL,
                        "transcript",
                        capability="summary",
                        scope=ConsentScope.session("s"),
                        policy_version=consents.policy_version,
                    )

            factory = plan.context.reservation_factory

            def reserved(actual: CostRequest) -> str | None:
                result = factory(actual)
                if position == 1:
                    invalidate()
                return result

            if position == 0:
                invalidate()
            wire.fail_open = failure == "open_fail"
            wire.fail_write = failure == "partial"
            if position == 2:
                wire.on_open = invalidate
            elif position == 3:
                wire.on_write = invalidate
            run = Run(plan.config, replace(plan.context, reservation_factory=reserved))
            with pytest.raises(ProviderError):
                run.request(plan.gateway, URL, "transcript", request.body, operation="summary")
            expected_open = int(position >= 2)
            expected_write = int(position == 3 and failure != "open_fail")
            assert wire.opens == expected_open
            assert len(wire.writes) == expected_write
            snapshot = ledger.account_snapshot("openai", "USD", 0, 2000)
            assert snapshot["confirmed"] == 0
            assert snapshot["reserved"] == (60 if position > 0 and not expected_write else 0)
            assert snapshot["unknown_exposure"] == (60 if expected_write else 0)
            app.processEvents()
        finally:
            panel.close()


@pytest.mark.parametrize("kind", LOCAL, ids=[f"G06-LOCAL-{i:03}" for i in range(3)])
def test_local_execution_is_independent_of_empty_price_catalog(tmp_path: Path, kind: str) -> None:
    import time

    from PySide6.QtWidgets import QApplication

    from recoryn.providers import LocalModelAttestation
    from recoryn.security import CredentialVault
    from recoryn.ui.privacy import PrivacyPanel
    from tests.ui.test_cost_cap_ui import Vault

    app = QApplication.instance() or QApplication([])
    with (
        ConsentStore(tmp_path / "p.sqlite") as consents,
        CostLedger(tmp_path / "p.sqlite") as ledger,
    ):
        panel = PrivacyPanel(
            consents, ledger, CredentialVault(backend=Vault(), namespace="g06-local")
        )
        try:
            if kind == "faster_whisper":
                execution = panel.prepare_execution("stt", "s", threading.Event())
                assert execution.gateway is None and execution.context.reservation_factory is None
            else:
                target = "http://127.0.0.1:11434/api/chat"
                control = panel.controls["summary"]
                panel.select_session("s")
                control.provider.setCurrentIndex(control.provider.findData("ollama"))
                control.endpoint.setText(target)
                control.model.setText("local")
                if kind == "unverified_remote":
                    with pytest.raises(SecurityError, match="LOCAL_EXECUTION_UNVERIFIED"):
                        panel.prepare_execution("summary", "s", threading.Event())
                else:
                    proof = LocalModelAttestation(
                        target, "local", "b" * 64, True, time.monotonic() + 60
                    )
                    panel.set_local_attestation(proof)
                    panel._action("summary", "grant")
                    control.data_type.setCurrentIndex(control.data_type.findData("context"))
                    panel._action("summary", "grant")
                    execution = panel.prepare_execution("summary", "s", threading.Event())
                    assert execution.context.reservation_factory is None
            app.processEvents()
        finally:
            panel.close()


def legacy_class(tmp_path: Path) -> Any:
    import hashlib
    from types import ModuleType

    from recoryn.security import _core

    assert hashlib.sha256(LEGACY_V1_SOURCE.encode()).hexdigest() == LEGACY_V1_SHA256
    path = tmp_path / "ledger-v1-234dd31.py"
    path.write_text(LEGACY_V1_SOURCE, encoding="utf-8", newline="\n")
    package_name = "g06_legacy_v1_fixture"
    package = ModuleType(package_name)
    package.__path__ = []
    sys.modules[package_name] = package
    sys.modules[package_name + "._core"] = _core
    name = package_name + ".ledger"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module.CostLedger


@pytest.mark.parametrize("case", DB, ids=[f"G06-DB-{i:02}" for i in range(1, 17)])
def test_durable_versions_witnesses_and_legacy_adoption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: int,
) -> None:
    from recoryn.security import ledger as ledger_module

    catalog = install_catalog(monkeypatch, flat_price(60))
    settings, clock = policy(catalog), Clock()
    db = tmp_path / "cost.sqlite"
    witness = db.with_name(db.name + ".cost-witness")
    Legacy = legacy_class(tmp_path)

    def opened() -> CostLedger:
        return CostLedger(db, clock=clock.now, monotonic=clock.monotonic)

    if case in (2, 3, 4, 5, 6, 13, 14):
        with Legacy(db) as old:
            if case in (3, 4, 5, 6):
                identifier = old.reserve("p", "legacy", 60, 100)
                if case == 4:
                    old.mark_unknown(identifier)
                elif case == 5:
                    old.settle(identifier, 40)
        if case == 6:
            witness.unlink()
            with pytest.raises(SecurityError, match="LEDGER_ROLLBACK_DETECTED"):
                opened()
            return
        if case == 13:
            original = ledger_module.os.replace

            def fail_replace(source: Any, target: Any) -> None:
                if Path(target) == witness:
                    raise OSError("injected witness publication failure")
                original(source, target)

            with monkeypatch.context() as patch:
                patch.setattr(ledger_module.os, "replace", fail_replace)
                with pytest.raises(SecurityError, match="^SECURITY_STATE_UNAVAILABLE$"):
                    opened()
            with Legacy(db) as old:
                assert old.snapshot("p")["unknown_exposure"] == 0
        elif case == 14:
            original_connect = ledger_module.connect
            injected: list[int] = []

            class CommitFailure:
                def __init__(self, connection: sqlite3.Connection) -> None:
                    self.connection = connection

                def __getattr__(self, name: str) -> Any:
                    return getattr(self.connection, name)

                def execute(self, sql: str, *args: Any) -> Any:
                    if sql == "COMMIT":
                        injected.append(json.loads(witness.read_text())["schema_version"])
                        raise sqlite3.OperationalError("injected after witness publication")
                    return self.connection.execute(sql, *args)

            with monkeypatch.context() as patch:
                patch.setattr(
                    ledger_module, "connect", lambda path: CommitFailure(original_connect(path))
                )
                with pytest.raises(SecurityError, match="^SECURITY_STATE_UNAVAILABLE$"):
                    opened()
            assert injected == [2]
            assert json.loads(witness.read_text())["schema_version"] == 2
            with pytest.raises(SecurityError, match="LEDGER_ROLLBACK_DETECTED"):
                opened()
            return
        with opened() as ledger:
            ledger.apply_policy("p", settings)
            if case in (3, 4, 5):
                assert ledger.legacy_unscoped("p")
                with pytest.raises(SecurityError, match="COST_LEGACY_UNSCOPED"):
                    reserve(ledger, flat_request(), settings, "new")
                if case in (4, 5):
                    ledger.adopt_legacy("p", settings, confirmed=True)
                    expected = {
                        "confirmed": 40 if case == 5 else 0,
                        "reserved": 0,
                        "unknown_exposure": 60 if case == 4 else 0,
                        "limit": 100,
                        "available": 60 if case == 5 else 40,
                    }
                    assert balance(ledger) == expected
            else:
                assert not ledger.legacy_unscoped("p")
        with opened() as ledger:
            if case in (4, 5):
                assert balance(ledger) == expected
        return

    if case == 1:
        for _ in range(3):
            with opened() as ledger:
                ledger.apply_policy("p", settings)
                assert (
                    ledger._db.execute("SELECT COUNT(*) FROM security_cost_accounts_v2").fetchone()[
                        0
                    ]
                    == 1
                )
                assert balance(ledger)["available"] == 100
        return

    if case == 9:
        with opened() as ledger:
            ledger.apply_policy("p", settings)
        backup = tmp_path / "earlier.sqlite"
        with sqlite3.connect(db) as source, sqlite3.connect(backup) as target:
            source.backup(target)
        source.close()
        target.close()
        with opened() as ledger:
            reserve(ledger, flat_request(), settings, "later")
        shutil.copyfile(backup, db)
        with pytest.raises(SecurityError, match="LEDGER_ROLLBACK_DETECTED"):
            opened()
        return

    with opened() as ledger:
        ledger.apply_policy("p", settings)
        reservation = reserve(ledger, flat_request(), settings, "request")
        ledger.mark_unknown(reservation)
    if case == 7:
        witness.unlink()
    elif case == 8:
        witness.write_text("{}")
    elif case == 10:
        db.unlink()
    elif case in (11, 12):
        tables = (
            ["security_cost_usage_events"]
            if case == 11
            else [
                "security_cost_requests_v2",
                "security_cost_accounts_v2",
                "security_cost_usage_events",
                "security_cost_meta_v2",
            ]
        )
        connection = sqlite3.connect(db)
        try:
            for name in tables:
                connection.execute("DROP TABLE " + name)
            connection.commit()
        finally:
            connection.close()
    elif case == 15:
        with pytest.raises(SecurityError, match="LEDGER_ROLLBACK_DETECTED"):
            Legacy(db)
        with opened() as ledger:
            assert balance(ledger)["unknown_exposure"] == 60
        return
    elif case == 16:
        with Library(tmp_path / "library") as library:
            library.create_session("deleted")
            assert library.delete_session("deleted")["deleted"]
            assert not library.list_sessions()
        with opened() as ledger:
            assert balance(ledger)["unknown_exposure"] == 60
            usage(ledger, reservation, 2, 40, event="late-final")
            assert balance(ledger) == {
                "confirmed": 40,
                "reserved": 0,
                "unknown_exposure": 0,
                "available": 60,
                "limit": 100,
            }
        return
    with pytest.raises(SecurityError, match="LEDGER_ROLLBACK_DETECTED"):
        opened()


# 234dd31: 기존 ledger 전체 원문. 실행 중 Git/네트워크 없이 v1 소비자를 재현한다.
LEGACY_V1_SHA256 = "890baaf75eae21e3307c66eb38144407735572b9f66ef187ab3dfaea24dd7935"
LEGACY_V1_SOURCE = r'''"""Integer cost reservations with a fail-closed rollback witness, independent of sessions."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ._core import (
    Coordinator,
    SecurityError,
    canonical,
    check_path,
    connect,
    digest,
    identifier,
    money,
    safe_operation,
)


class CostLedger:
    @safe_operation
    def __init__(self, db_path: Path) -> None:
        self.coordinator = Coordinator(db_path)
        self.db_path = self.coordinator.path
        self._witness = check_path(self.db_path.with_name(self.db_path.name + ".cost-witness"))
        self._closed = False
        if self._witness.exists() and not self.db_path.exists():
            raise SecurityError("LEDGER_ROLLBACK_DETECTED")
        self._db = connect(self.db_path)
        try:
            with self.coordinator.hold():
                self._db.executescript("""
                    BEGIN IMMEDIATE;
                    CREATE TABLE IF NOT EXISTS security_cost_meta(id INTEGER PRIMARY KEY, revision INTEGER);
                    CREATE TABLE IF NOT EXISTS security_cost_accounts(provider TEXT PRIMARY KEY, amount_limit INTEGER);
                    CREATE TABLE IF NOT EXISTS security_cost_requests(
                        reservation_id TEXT PRIMARY KEY, provider TEXT, request_id TEXT,
                        amount INTEGER, actual INTEGER, state TEXT,
                        UNIQUE(provider,request_id));
                    COMMIT;
                """)
                meta = self._db.execute(
                    "SELECT revision FROM security_cost_meta WHERE id=1"
                ).fetchone()
                if meta is None:
                    if self._witness.exists():
                        raise SecurityError("LEDGER_ROLLBACK_DETECTED")
                    self._db.execute("INSERT INTO security_cost_meta VALUES(1,0)")
                    self._write_witness()
                self._verify()
        except BaseException:
            self._db.close()
            raise

    def __enter__(self) -> CostLedger:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        with self.coordinator.hold():
            if not self._closed:
                self._db.close()
                self._closed = True

    def _state(self) -> dict[str, Any]:
        revision = self._db.execute(
            "SELECT revision FROM security_cost_meta WHERE id=1"
        ).fetchone()[0]
        accounts = [
            list(row)
            for row in self._db.execute("SELECT * FROM security_cost_accounts ORDER BY provider")
        ]
        requests = [
            list(row)
            for row in self._db.execute(
                "SELECT * FROM security_cost_requests ORDER BY reservation_id"
            )
        ]
        return {"revision": revision, "accounts": accounts, "requests": requests}

    def _write_witness(self) -> None:
        state = self._state()
        payload = canonical(
            {"schema_version": 1, "revision": state["revision"], "sha256": digest(canonical(state))}
        )
        temporary = check_path(self._witness.with_name(self._witness.name + "." + uuid.uuid4().hex))
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            check_path(self._witness)
            os.replace(temporary, self._witness)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _verify(self) -> None:
        if self._closed:
            raise SecurityError("LEDGER_CLOSED")
        try:
            check_path(self._witness)
            if self._witness.stat().st_size > 4096:
                raise ValueError
            value = json.loads(self._witness.read_bytes())
            state = self._state()
            if value != {
                "schema_version": 1,
                "revision": state["revision"],
                "sha256": digest(canonical(state)),
            }:
                raise ValueError
        except (OSError, ValueError, TypeError, sqlite3.Error):
            raise SecurityError("LEDGER_ROLLBACK_DETECTED") from None

    def _change(self, operation: Callable[[], object]) -> None:
        self._verify()
        self._db.execute("BEGIN IMMEDIATE")
        try:
            operation()
            self._db.execute("UPDATE security_cost_meta SET revision=revision+1 WHERE id=1")
            # Witness precedes commit. A crash/commit failure between the two is
            # deliberately blocked on restart rather than silently freeing funds.
            self._write_witness()
            self._db.execute("COMMIT")
        except BaseException:
            self._db.execute("ROLLBACK")
            raise

    def _request(self, reservation_id: str) -> sqlite3.Row:
        row: sqlite3.Row | None = self._db.execute(
            "SELECT * FROM security_cost_requests WHERE reservation_id=?",
            (identifier(reservation_id),),
        ).fetchone()
        if row is None:
            raise SecurityError("RESERVATION_NOT_FOUND")
        return row

    def _snapshot(self, provider_id: str) -> dict[str, int]:
        account = self._db.execute(
            "SELECT amount_limit FROM security_cost_accounts WHERE provider=?", (provider_id,)
        ).fetchone()
        confirmed = reserved = unknown = 0
        for row in self._db.execute(
            "SELECT amount,actual,state FROM security_cost_requests WHERE provider=?",
            (provider_id,),
        ):
            if row["state"] == "SETTLED":
                confirmed += row["actual"]
            elif row["state"] == "RESERVED":
                reserved += row["amount"]
            elif row["state"] == "UNKNOWN":
                unknown += row["amount"]
        limit = account[0] if account else 0
        return {
            "confirmed": confirmed,
            "reserved": reserved,
            "unknown_exposure": unknown,
            "available": max(0, limit - confirmed - reserved - unknown),
            "limit": limit,
        }

    @safe_operation
    def snapshot(self, provider_id: str) -> dict[str, int]:
        with self.coordinator.hold():
            self._verify()
            return self._snapshot(identifier(provider_id))

    @safe_operation
    def set_limit(self, provider_id: str, limit_microunits: int) -> None:
        provider_id, limit = identifier(provider_id), money(limit_microunits)
        with self.coordinator.hold():

            def apply() -> None:
                self._db.execute(
                    "INSERT INTO security_cost_accounts VALUES(?,?) ON CONFLICT(provider) DO UPDATE SET amount_limit=excluded.amount_limit",
                    (provider_id, limit),
                )

            self._change(apply)

    @safe_operation
    def reservations(self, provider_id: str) -> list[dict[str, object]]:
        with self.coordinator.hold():
            self._verify()
            return [
                {
                    "reservation_id": row["reservation_id"],
                    "request_id": row["request_id"],
                    "state": row["state"],
                    "amount_microunits": row["amount"],
                    "actual_microunits": row["actual"],
                }
                for row in self._db.execute(
                    "SELECT * FROM security_cost_requests WHERE provider=? ORDER BY rowid",
                    (identifier(provider_id),),
                )
            ]

    @safe_operation
    def reserve(
        self, provider_id: str, request_id: str, amount_microunits: int, limit_microunits: int
    ) -> str:
        provider_id, request_id = identifier(provider_id), identifier(request_id)
        amount, limit = money(amount_microunits), money(limit_microunits)
        with self.coordinator.hold():
            self._verify()
            existing = self._db.execute(
                "SELECT * FROM security_cost_requests WHERE provider=? AND request_id=?",
                (provider_id, request_id),
            ).fetchone()
            account = self._db.execute(
                "SELECT amount_limit FROM security_cost_accounts WHERE provider=?", (provider_id,)
            ).fetchone()
            if account is not None and account[0] != limit:
                raise SecurityError("BUDGET_POLICY_CHANGED")
            if existing:
                if existing["amount"] != amount:
                    raise SecurityError("RESERVATION_CONFLICT")
                return str(existing["reservation_id"])
            current = self._snapshot(provider_id)
            exposure = current["confirmed"] + current["reserved"] + current["unknown_exposure"]
            if exposure + amount > limit:
                raise SecurityError("BUDGET_EXCEEDED")
            reservation = uuid.uuid4().hex

            def create() -> None:
                self._db.execute(
                    "INSERT OR IGNORE INTO security_cost_accounts VALUES(?,?)", (provider_id, limit)
                )
                self._db.execute(
                    "INSERT INTO security_cost_requests VALUES(?,?,?,?,NULL,'RESERVED')",
                    (reservation, provider_id, request_id, amount),
                )

            self._change(create)
            return reservation

    @safe_operation
    def check_reservation(self, reservation_id: str, provider_id: str) -> None:
        with self.coordinator.hold():
            self._verify()
            row = self._request(reservation_id)
            if row["provider"] != provider_id or row["state"] != "RESERVED":
                raise SecurityError("RESERVATION_NOT_DISPATCHABLE")
            balance = self._snapshot(provider_id)
            if (
                balance["confirmed"] + balance["reserved"] + balance["unknown_exposure"]
                > balance["limit"]
            ):
                raise SecurityError("BUDGET_EXCEEDED")

    @safe_operation
    def mark_unknown(self, reservation_id: str) -> None:
        with self.coordinator.hold():
            self._verify()
            row = self._request(reservation_id)
            if row["state"] == "UNKNOWN":
                return
            if row["state"] != "RESERVED":
                raise SecurityError("RESERVATION_CONFLICT")
            self._change(
                lambda: (
                    self._db.execute(
                        "UPDATE security_cost_requests SET state='UNKNOWN' WHERE reservation_id=?",
                        (reservation_id,),
                    )
                    and None
                )
            )

    @safe_operation
    def settle(self, reservation_id: str, actual_microunits: int) -> None:
        actual = money(actual_microunits)
        with self.coordinator.hold():
            self._verify()
            row = self._request(reservation_id)
            if row["state"] == "SETTLED":
                if row["actual"] != actual:
                    raise SecurityError("SETTLEMENT_CONFLICT")
                return
            if row["state"] not in {"RESERVED", "UNKNOWN"}:
                raise SecurityError("RESERVATION_CONFLICT")
            self._change(
                lambda: (
                    self._db.execute(
                        "UPDATE security_cost_requests SET state='SETTLED',actual=? WHERE reservation_id=?",
                        (actual, reservation_id),
                    )
                    and None
                )
            )

    @safe_operation
    def release(self, reservation_id: str) -> None:
        with self.coordinator.hold():
            self._verify()
            row = self._request(reservation_id)
            if row["state"] == "RELEASED":
                return
            if row["state"] != "RESERVED":
                raise SecurityError("RESERVATION_MAY_BE_SENT")
            self._change(
                lambda: (
                    self._db.execute(
                        "UPDATE security_cost_requests SET state='RELEASED' WHERE reservation_id=?",
                        (reservation_id,),
                    )
                    and None
                )
            )
'''


@pytest.mark.parametrize(
    "change,expected",
    [
        ("expiry", "COST_QUOTE_EXPIRED"),
        ("policy", "BUDGET_POLICY_CHANGED"),
        ("clock", "COST_CLOCK_INVALID"),
        ("underestimate", "COST_PLAN_UNDERESTIMATED"),
        ("legacy", "COST_LEGACY_UNSCOPED"),
        ("foreign_period", "COST_UNRESOLVED_EXPOSURE"),
    ],
    ids=lambda value: "G06-FIX1-WRITE-" + value,
)
def test_gateway_rechecks_actual_next_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
    expected: str,
) -> None:
    catalog = install_catalog(monkeypatch, price(valid_until_utc=1100))
    clock, settings, request, wire = Clock(), policy(catalog), text_request(), Wire()
    with (
        ConsentStore(tmp_path / "consent.sqlite") as consent,
        CostLedger(
            tmp_path / "cost.sqlite",
            clock=clock.now,
            monotonic=clock.monotonic,
        ) as ledger,
    ):
        ledger.apply_policy("p", settings)
        reservation = reserve(ledger, request, settings, "sent")
        other = reserve(ledger, request, settings, "other")
        view = gateway(consent, ledger, wire, request)

        def after_first() -> None:
            if len(wire.writes) != 1:
                return
            if change == "expiry":
                clock.utc = 1100
            elif change == "clock":
                clock.utc = 999
            elif change == "policy":
                ledger.apply_policy("p", replace(settings, policy_version=2))
            elif change in {"legacy", "foreign_period"}:
                ledger.reserve("p", "legacy_during_dispatch", 1, 100)
                if change == "foreign_period":
                    ledger.adopt_legacy(
                        "p",
                        replace(settings, period_start_utc=2000, period_end_utc=3000),
                        confirmed=True,
                    )
            else:
                ledger.settle(other, 14)

        wire.on_write = after_first
        with pytest.raises(SecurityError) as refused:
            view.request(
                "p", request.endpoint, request.data_type, request.body, reservation_id=reservation
            )
        assert refused.value.code == expected and refused.value.outcome_known is False
        assert wire.opens == 1 and wire.writes == [request.body[:3]]
        assert ledger.reservations("p")[0]["state"] in {"UNKNOWN", "RESERVED", "SETTLED"}
        rows = {r["request_id"]: r for r in ledger.reservations("p")}
        assert rows["sent"]["state"] == "UNKNOWN" and rows["sent"]["amount_microunits"] == 13


def test_gateway_requires_ledger_and_refuses_underestimated_account(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = install_catalog(monkeypatch, price(provider_id="openai"))
    request, clock, settings = text_request(provider_id="openai"), Clock(), policy(catalog)
    with (
        ConsentStore(tmp_path / "consent.sqlite") as consent,
        CostLedger(
            tmp_path / "cost.sqlite",
            clock=clock.now,
            monotonic=clock.monotonic,
        ) as ledger,
    ):
        wire = Wire()
        view = gateway(consent, None, wire, request)
        with pytest.raises(SecurityError, match="^LEDGER_REQUIRED$"):
            view.request("openai", request.endpoint, request.data_type, request.body)
        assert wire.opens == 0 and wire.writes == []
        ledger.apply_policy("openai", settings)
        first = reserve(ledger, request, settings, "first")
        second = reserve(ledger, request, settings, "second")
        ledger.settle(first, 14)
        view = gateway(consent, ledger, wire, request)
        with pytest.raises(SecurityError, match="^COST_PLAN_UNDERESTIMATED$"):
            view.request(
                "openai", request.endpoint, request.data_type, request.body, reservation_id=second
            )
        assert wire.opens == 0 and wire.writes == []
        ledger.apply_policy("openai", replace(settings, policy_version=2))
        assert ledger.account("openai", "USD", 0, 2000)["blocked"] == 1
        # Use the unchanged policy binding to isolate the underestimated guard.
        with pytest.raises(SecurityError, match="^COST_PLAN_UNDERESTIMATED$"):
            reserve(ledger, request, replace(settings, policy_version=2), "next")
        # A second reserved request made before settlement is blocked at Gateway.
        # Keep a separate period to avoid a stale-version guard masking it.
        wire = Wire()
        view = gateway(consent, ledger, wire, request)
        with pytest.raises(SecurityError, match="^BUDGET_POLICY_CHANGED$"):
            view.request(
                "openai", request.endpoint, request.data_type, request.body, reservation_id=second
            )
        assert wire.opens == 0 and wire.writes == []


def test_reservation_admission_rejects_forged_quote_before_creating_a_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = install_catalog(monkeypatch, price())
    settings, clock, request = policy(catalog), Clock(), text_request()
    with CostLedger(tmp_path / "cost.sqlite", clock=clock.now, monotonic=clock.monotonic) as ledger:
        ledger.apply_policy("p", settings)
        actual = ledger.quote_request(request, settings)
        with pytest.raises(SecurityError, match="^COST_QUOTE_MISMATCH$"):
            ledger.reserve_quote("forged", replace(actual, amount=1), settings, request)
        assert ledger.reservations("p") == [] and balance(ledger)["reserved"] == 0
        with pytest.raises(SecurityError, match="^COST_BOUND_UNVERIFIED$"):
            ledger.quote_request(
                request, replace(settings, mode="general", general_acknowledged=False)
            )


def test_gateway_clock_recovery_keeps_recording_independent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from recoryn.app.recording import RecordingService
    from recoryn.domain import AudioFormat, PCMBlock

    catalog = install_catalog(monkeypatch, price(valid_until_utc=4000))
    clock, settings, request = Clock(1000), policy(catalog, period_end_utc=4000), text_request()
    db = tmp_path / "cost.sqlite"
    with CostLedger(db, clock=clock.now, monotonic=clock.monotonic) as ledger:
        ledger.apply_policy("p", settings)
        reservation = reserve(ledger, request, settings, "before_restart")
        clock.utc = 2000
        ledger.apply_policy("p", replace(settings, policy_version=2))
    clock.utc = 1500
    with (
        ConsentStore(tmp_path / "consent.sqlite") as consent,
        CostLedger(
            db,
            clock=clock.now,
            monotonic=clock.monotonic,
        ) as ledger,
        Library(tmp_path / "library") as library,
    ):
        assert ledger.availability() == "COST_CLOCK_INVALID"
        wire = Wire()
        view = gateway(consent, ledger, wire, request)
        with pytest.raises(SecurityError, match="^COST_CLOCK_INVALID$"):
            view.request(
                "p", request.endpoint, request.data_type, request.body, reservation_id=reservation
            )
        assert wire.opens == 0 and wire.writes == []
        fmt = AudioFormat(16000, 1, "s16le")
        recorder = RecordingService(library, {"mic": fmt}, session_id="local")
        recorder.start()
        try:
            assert recorder.submit(
                PCMBlock("local", "mic", recorder.epochs["mic"], 0, fmt, 16, b"\x01\x00" * 16, 0, 0)
            )
        finally:
            result = recorder.stop(timeout=60)
        assert result["frame_count"] == 16
        ledger.reset_clock(confirmed=True)
        assert ledger.availability() is None


def test_v2_thread_reservations_and_duplicate_dispatch_have_one_winner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from concurrent.futures import ThreadPoolExecutor

    catalog = install_catalog(monkeypatch, flat_price(7))
    settings, clock, request = policy(catalog, cap=7, limit=10), Clock(), flat_request(7)
    db = tmp_path / "cost.sqlite"
    with (
        CostLedger(db, clock=clock.now, monotonic=clock.monotonic) as first,
        CostLedger(
            db,
            clock=clock.now,
            monotonic=clock.monotonic,
        ) as second,
        ConsentStore(tmp_path / "consent.sqlite") as consent,
    ):
        first.apply_policy("p", settings)
        barrier = threading.Barrier(8)

        def compete(index: int) -> str | None:
            barrier.wait(10)
            ledger = (first, second)[index % 2]
            try:
                return reserve(ledger, request, settings, f"compete{index}")
            except SecurityError as error:
                assert error.code == "BUDGET_EXCEEDED"
                return None

        with ThreadPoolExecutor(max_workers=8) as pool:
            winners = [r for r in pool.map(compete, range(8)) if r is not None]
        assert len(winners) == 1 and balance(first)["reserved"] == 7
        wire = Wire()
        one = gateway(consent, first, wire, request)
        two = Gateway(
            consent,
            ledger=second,
            transport=wire,
            expected_grants=one.expected_grants,
            chunk_bytes=3,
        ).for_session(
            "s",
            capability=request.operation,
            scope=ConsentScope.session("s"),
            policy_version=consent.policy_version,
        )
        views = [one, two]
        barrier = threading.Barrier(2)

        def dispatch(index: int) -> str:
            barrier.wait(10)
            try:
                views[index].request(
                    "p",
                    request.endpoint,
                    request.data_type,
                    request.body,
                    reservation_id=winners[0],
                )
                return "OK"
            except SecurityError as error:
                return error.code

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(dispatch, range(2)))
        assert sorted(outcomes) == ["OK", "RESERVATION_NOT_DISPATCHABLE"]
        assert wire.opens == 1 and b"".join(wire.writes) == request.body


@pytest.mark.parametrize("shape", ["stt5", "stt10", "text20MiB"])
@pytest.mark.parametrize("history", [0, 1200])
def test_large_production_wire_has_constant_cost_per_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    shape: str,
    history: int,
) -> None:
    import io
    import time
    import wave

    from recoryn.security import CostPolicy, cost_catalog
    from recoryn.security import cost as costs
    from recoryn.security.cost import cost_headers

    assert cost_catalog.load_catalog().entries == ()
    if shape.startswith("stt"):
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(b"\x01\x00" * (16000 * 60 * int(shape[3:])))
        boundary = "recoryn-fix1-offline"
        headers = {"Content-Type": "multipart/form-data; boundary=" + boundary}
        body = (
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="model"\r\n\r\nwhisper-1\r\n'
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="audio.wav"\r\n'
                f"Content-Type: audio/wav\r\n\r\n"
            ).encode()
            + buffer.getvalue()
            + f"\r\n--{boundary}--\r\n".encode()
        )
        request = CostRequest(
            "openai",
            "https://api.openai.com/v1/audio/transcriptions",
            "whisper-1",
            "v1",
            "stt",
            "audio",
            body,
            cost_headers(headers),
        )
    else:
        prefix = b'{"model":"unpriced","input":"'
        suffix = b'","max_output_tokens":1}'
        body = prefix + b"x" * (20 * 1024 * 1024 - len(prefix) - len(suffix)) + suffix
        headers = {}
        request = CostRequest(
            "openai",
            "https://api.openai.com/v1/responses",
            "unpriced",
            "v1",
            "summary",
            "transcript",
            body,
        )
    db = tmp_path / "security.sqlite"
    settings = CostPolicy(
        "general",
        "USD",
        0,
        4_000_000_000,
        1_000_000,
        10**15,
        1,
        cost_catalog.load_catalog().sha256,
        True,
    )
    with CostLedger(db) as ledger, ConsentStore(db) as consent:
        ledger.apply_policy("openai", settings)
        seed = CostRequest(
            "openai",
            "https://api.openai.com/v1/responses",
            "seed",
            "v1",
            "summary",
            "transcript",
            b'{"model":"seed","input":"x","max_output_tokens":1}',
        )
        seed_id = reserve(ledger, seed, settings, "seed")
        ledger.settle(seed_id, 0)
        if history:
            source = dict(ledger._request(seed_id))
            # _request includes a computed alias; insert real schema columns only.
            source.pop("amount", None)
            columns = list(source)
            rows = []
            for i in range(history):
                item = {
                    **source,
                    "reservation_id": f"history{i}",
                    "request_id": f"history{i}",
                    "actual": 1,
                }
                rows.append(tuple(item[c] for c in columns))
            ledger._change(
                lambda: ledger._db.executemany(
                    "INSERT INTO security_cost_requests_v2("
                    + ",".join(columns)
                    + ") VALUES("
                    + ",".join("?" for _ in columns)
                    + ")",
                    rows,
                )
            )
        counts = {"wire": 0, "witness": 0, "verify": 0}
        original_wire, original_witness, original_verify = (
            costs.inspect_wire,
            ledger._write_witness,
            ledger._verify,
        )

        def inspect(*args: Any) -> Any:
            counts["wire"] += 1
            return original_wire(*args)

        def witness() -> None:
            counts["witness"] += 1
            original_witness()

        def verify() -> None:
            counts["verify"] += 1
            original_verify()

        monkeypatch.setattr(costs, "inspect_wire", inspect)
        monkeypatch.setattr(ledger, "_write_witness", witness)
        monkeypatch.setattr(ledger, "_verify", verify)
        quoted = ledger.quote_request(request, settings)
        reservation = ledger.reserve_quote("measured", quoted, settings, request)
        assert quoted.kind == "USER_CAP" and quoted.amount == 1_000_000
        assert counts["wire"] == 1
        counts.update(witness=0, verify=0)
        wire = Wire()
        view = gateway(consent, ledger, wire, request)
        view.chunk_bytes = 65536
        samples = []
        original_dispatch = ledger.validate_dispatch

        def dispatch(*args: Any, **kwargs: Any) -> None:
            started = time.perf_counter()
            original_dispatch(*args, **kwargs)
            if kwargs.get("phase") == "write":
                samples.append(time.perf_counter() - started)

        monkeypatch.setattr(ledger, "validate_dispatch", dispatch)
        started = time.perf_counter()
        assert (
            view.request(
                request.provider_id,
                request.endpoint,
                request.data_type,
                body,
                headers=headers,
                reservation_id=reservation,
            )
            == b"OK"
        )
        elapsed = time.perf_counter() - started
        expected_writes = (len(body) + 65535) // 65536
        assert len(samples) == len(wire.writes) == expected_writes
        assert b"".join(wire.writes) == body
        # Deterministic complexity checks accompany the measured steady-state bound.
        assert counts["wire"] == 1 and counts["witness"] == 2 and counts["verify"] <= 12
        assert sum(samples) / len(samples) <= 0.002
        row = next(r for r in ledger.reservations("openai") if r["request_id"] == "measured")
        assert row["state"] == "UNKNOWN"  # successful handoff, not an UNKNOWN failure
        print(
            f"G06-FIX1-PERF {shape} history={history} bytes={len(body)} writes={len(samples)} "
            f"seconds={elapsed:.4f} mean_cost_ms={1000 * sum(samples) / len(samples):.4f} "
            f"max_cost_ms={1000 * max(samples):.4f} wire={counts['wire']} witness={counts['witness']}"
        )


def test_v2_separate_process_reservations_have_one_winner(tmp_path: Path) -> None:
    import os
    import subprocess
    import time
    from contextlib import ExitStack

    from recoryn.security import CostPolicy, cost_catalog
    from recoryn.security import ledger as ledger_module

    db = tmp_path / "process.sqlite"
    # This test tree's own src (an isolated copy tests itself), not another installed copy.
    tree_src = Path(__file__).resolve().parents[2] / "src"
    expected_ledger = (tree_src / "recoryn" / "security" / "ledger.py").resolve()
    assert Path(ledger_module.__file__).resolve() == expected_ledger, ledger_module.__file__
    child_env = os.environ.copy()
    child_env["PYTHONPATH"] = str(tree_src)
    catalog = cost_catalog.load_catalog()
    settings = CostPolicy("general", "USD", 0, 4_000_000_000, 7, 10, 1, catalog.sha256, True)
    with CostLedger(db) as ledger:
        ledger.apply_policy("openai", settings)
    script = tmp_path / "owned_reserver.py"
    script.write_text(
        """import json,sys,time
from pathlib import Path
import recoryn
from recoryn.security import CostLedger,CostPolicy,CostRequest,SecurityError,cost_catalog
from recoryn.security import ledger as ledger_module
db,ready,gate,index,expected_origin=map(str,sys.argv[1:])
assert Path(ledger_module.__file__).resolve()==Path(expected_origin),ledger_module.__file__
assert Path(recoryn.__file__).resolve().parent==Path(expected_origin).parents[1],recoryn.__file__
settings=CostPolicy("general","USD",0,4_000_000_000,7,10,1,cost_catalog.load_catalog().sha256,True)
request=CostRequest("openai","https://process.invalid/v1/responses","unpriced","v1","summary","transcript",b'{"model":"unpriced","input":"x","max_output_tokens":1}')
with CostLedger(Path(db)) as ledger:
 Path(ready).write_text("ready")
 deadline=time.monotonic()+30
 while not Path(gate).exists():
  if time.monotonic()>deadline: raise RuntimeError("owned test barrier timeout")
  time.sleep(.005)
 try:
  q=ledger.quote_request(request,settings)
  ledger.reserve_quote("child"+index,q,settings,request)
  print(json.dumps({"winner":1}))
 except SecurityError as e:
  assert e.code=="BUDGET_EXCEEDED",e.code
  print(json.dumps({"winner":0}))
""",
        encoding="utf-8",
    )
    gate = tmp_path / "go"
    with ExitStack() as stack:
        children = [
            stack.enter_context(
                subprocess.Popen(
                    [
                        sys.executable,
                        "-B",
                        "-W",
                        "error::ResourceWarning",
                        str(script),
                        str(db),
                        str(tmp_path / f"ready{i}"),
                        str(gate),
                        str(i),
                        str(expected_ledger),
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=child_env,
                )
            )
            for i in range(4)
        ]
        try:
            deadline = time.monotonic() + 30
            while not all((tmp_path / f"ready{i}").exists() for i in range(4)):
                exited = [c for c in children if c.poll() is not None]
                # An early exit (e.g. the child's own import-origin assert) is reported.
                assert not exited, [c.communicate(timeout=30) for c in exited]
                assert time.monotonic() < deadline
                time.sleep(0.01)
            gate.write_text("go")
            outcomes = [c.communicate(timeout=30) for c in children]
            assert all(c.returncode == 0 for c in children), outcomes
            assert all(not err for _, err in outcomes), outcomes
            assert sum(json.loads(out)["winner"] for out, _ in outcomes) == 1
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
                    child.communicate(timeout=30)
    with CostLedger(db) as ledger:
        observed = ledger.account_snapshot("openai", "USD", 0, 4_000_000_000)
        assert observed["reserved"] == 7 and observed["available"] == 3


def test_reserved_dispatch_claim_is_exclusive_before_the_first_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from concurrent.futures import ThreadPoolExecutor

    catalog = install_catalog(monkeypatch, price())
    settings, clock, request = policy(catalog), Clock(), text_request()
    with (
        ConsentStore(tmp_path / "consent.sqlite") as consent,
        CostLedger(
            tmp_path / "cost.sqlite",
            clock=clock.now,
            monotonic=clock.monotonic,
        ) as ledger,
    ):
        ledger.apply_policy("p", settings)
        reservation = reserve(ledger, request, settings, "exclusive")
        wire = Wire()
        first = gateway(consent, ledger, wire, request)
        second = Gateway(
            consent, ledger=ledger, transport=wire, expected_grants=first.expected_grants
        ).for_session(
            "s",
            capability=request.operation,
            scope=ConsentScope.session("s"),
            policy_version=consent.policy_version,
        )
        arrived, release = threading.Event(), threading.Event()
        original_write = first._write

        def pause_before_write(*args: Any, **kwargs: Any) -> None:
            arrived.set()
            assert release.wait(30)
            original_write(*args, **kwargs)

        monkeypatch.setattr(first, "_write", pause_before_write)
        with ThreadPoolExecutor(max_workers=1) as pool:
            running = pool.submit(
                first.request,
                "p",
                request.endpoint,
                request.data_type,
                request.body,
                reservation_id=reservation,
            )
            try:
                assert arrived.wait(30)
                assert wire.opens == 1 and wire.writes == []
                with pytest.raises(SecurityError, match="^RESERVATION_NOT_DISPATCHABLE$"):
                    second.request(
                        "p",
                        request.endpoint,
                        request.data_type,
                        request.body,
                        reservation_id=reservation,
                    )
                assert wire.opens == 1 and wire.writes == []
            finally:
                release.set()
                running.result(timeout=30)
        assert b"".join(wire.writes) == request.body


@pytest.mark.parametrize(
    "case,expected",
    [
        ("missing", "COST_REQUEST_INVALID"),
        ("bool", "COST_REQUEST_INVALID"),
        ("negative", "COST_REQUEST_INVALID"),
        ("overflow", "COST_PLAN_UNDERESTIMATED"),
    ],
)
def test_dispatch_byte_bound_refuses_the_next_handoff_before_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    expected: str,
) -> None:
    catalog = install_catalog(monkeypatch, price())
    settings, clock, request = policy(catalog), Clock(), text_request()
    with (
        ConsentStore(tmp_path / "consent.sqlite") as consent,
        CostLedger(
            tmp_path / "cost.sqlite",
            clock=clock.now,
            monotonic=clock.monotonic,
        ) as ledger,
    ):
        ledger.apply_policy("p", settings)
        reservation = reserve(ledger, request, settings, "bound")
        wire = Wire()
        view = gateway(consent, ledger, wire, request)
        original = ledger.validate_dispatch

        def exceed(*args: Any, **kwargs: Any) -> None:
            if kwargs.get("phase") == "write":
                kwargs["bytes_sent"] = {
                    "missing": None,
                    "bool": True,
                    "negative": -1,
                    "overflow": len(request.body) + 1,
                }[case]
            original(*args, **kwargs)

        monkeypatch.setattr(ledger, "validate_dispatch", exceed)
        with pytest.raises(SecurityError, match="^" + expected + "$"):
            view.request(
                "p", request.endpoint, request.data_type, request.body, reservation_id=reservation
            )
        assert wire.opens == 1 and wire.writes == []
        assert balance(ledger)["reserved"] == 13 and balance(ledger)["unknown_exposure"] == 0


def test_gateway_rejects_stored_user_cap_in_strict_policy_even_with_valid_witness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise dispatch's independent guard against a malformed authenticated row.

    The fixture deliberately bypasses admission using the owned DB connection;
    it does not claim that an external attacker can forge a ledger witness.
    """
    catalog = install_catalog(
        monkeypatch, price(price_as_of_utc=None, valid_from_utc=None, valid_until_utc=None)
    )
    settings = policy(catalog, mode="general", general_acknowledged=True, cap=13)
    clock, request, wire = Clock(), text_request(), Wire()
    with (
        ConsentStore(tmp_path / "consent.sqlite") as consent,
        CostLedger(
            tmp_path / "cost.sqlite",
            clock=clock.now,
            monotonic=clock.monotonic,
        ) as ledger,
    ):
        ledger.apply_policy("p", settings)
        reservation = reserve(ledger, request, settings, "user_cap")
        row = ledger._request(reservation)
        stored_policy = json.loads(row["policy_json"])
        stored_policy.update(mode="strict", general_acknowledged=False)
        stored_quote = json.loads(row["quote_json"])
        stored_quote["policy"] = stored_policy
        ledger._change(
            lambda: ledger._db.execute(
                "UPDATE security_cost_requests_v2 SET policy_json=?,quote_json=? WHERE reservation_id=?",
                (json.dumps(stored_policy), json.dumps(stored_quote), reservation),
            )
        )
        view = gateway(consent, ledger, wire, request)
        with pytest.raises(SecurityError, match="^COST_QUOTE_MISMATCH$"):
            view.request(
                "p", request.endpoint, request.data_type, request.body, reservation_id=reservation
            )
        assert wire.opens == 0 and wire.writes == []
        assert balance(ledger)["reserved"] == 13 and balance(ledger)["unknown_exposure"] == 0


def test_actual_run_keeps_quote_analysis_once_and_drops_body_after_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import gc
    import weakref

    from recoryn.providers import ExecutionContext, ProviderConfig
    from recoryn.providers._common import Run
    from recoryn.security import cost as costs

    catalog = install_catalog(monkeypatch, flat_price(13, provider_id="openai"))
    settings, clock = policy(catalog), Clock()
    request = flat_request(13, provider_id="openai")
    count = []
    original_inspect = costs.inspect_wire

    def inspect(*args: Any) -> Any:
        count.append(1)
        return original_inspect(*args)

    monkeypatch.setattr(costs, "inspect_wire", inspect)
    with (
        ConsentStore(tmp_path / "consent.sqlite") as consent,
        CostLedger(
            tmp_path / "cost.sqlite",
            clock=clock.now,
            monotonic=clock.monotonic,
        ) as ledger,
    ):
        ledger.apply_policy("openai", settings)
        wire = Wire()
        wire.response = b"{}"
        view = gateway(consent, ledger, wire, request)
        observed = []

        def factory(actual: CostRequest) -> str:
            observed.append(weakref.ref(actual))
            return reserve(ledger, actual, settings, "actual_run")

        context = ExecutionContext(reservation_factory=factory)
        result = Run(ProviderConfig("openai", "fee13", endpoint=request.endpoint), context).request(
            view, request.endpoint, request.data_type, request.body, operation=request.operation
        )
        assert result == {} and wire.opens == 1
        assert b"".join(wire.writes) == request.body and len(count) == 1
        gc.collect()
        assert len(observed) == 1 and observed[0]() is None


@pytest.fixture
def cov2_account(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    catalog = install_catalog(monkeypatch, price())
    settings, clock, request = policy(catalog), Clock(), text_request()
    ledger = CostLedger(tmp_path / "cov2.sqlite", clock=clock.now, monotonic=clock.monotonic)
    try:
        ledger.apply_policy("p", settings)
        yield ledger, request, settings, clock
    finally:
        ledger.close()


def cov2_open(ledger: CostLedger, request: CostRequest, reservation: str) -> None:
    ledger.validate_dispatch(
        reservation,
        "p",
        request.endpoint,
        request.body,
        data_type=request.data_type,
        operation=request.operation,
        headers=dict(request.headers),
        dispatch_id="cov2",
    )


COV2_WRITE = [
    ("reservation", "COST_QUOTE_MISMATCH"),
    ("provider", "COST_QUOTE_MISMATCH"),
    ("endpoint", "COST_QUOTE_MISMATCH"),
    ("data", "COST_QUOTE_MISMATCH"),
    ("operation", "COST_QUOTE_MISMATCH"),
    ("headers", "COST_QUOTE_MISMATCH"),
    ("body-copy", "COST_QUOTE_MISMATCH"),
    ("missing-dispatch", "RESERVATION_NOT_DISPATCHABLE"),
    ("settled", "RESERVATION_NOT_DISPATCHABLE"),
    ("row-dispatch", "RESERVATION_NOT_DISPATCHABLE"),
    ("quote", "COST_QUOTE_MISMATCH"),
    ("blocked", "COST_PLAN_UNDERESTIMATED"),
    ("over-budget", "BUDGET_EXCEEDED"),
    ("expired-period", "COST_PERIOD_CHANGED"),
]


@pytest.mark.parametrize("case,code", COV2_WRITE, ids=[f"G06-COV2-WRITE-{i:03}" for i in range(14)])
def test_cov2_direct_write_refuses_binding_and_authenticated_state_changes(
    cov2_account: Any, case: str, code: str
) -> None:
    ledger, request, settings, clock = cov2_account
    reservation = reserve(ledger, request, settings, "write")
    cov2_open(ledger, request, reservation)
    arguments: dict[str, Any] = dict(
        reservation_id=reservation,
        provider="p",
        target=request.endpoint,
        body=request.body,
        data_type=request.data_type,
        operation=request.operation,
        headers=dict(request.headers),
        dispatch_id="cov2",
        phase="write",
        bytes_sent=1,
    )
    changes = {
        "reservation": ("reservation_id", "other"),
        "provider": ("provider", "q"),
        "endpoint": ("target", "https://cost.invalid/v1/another"),
        "data": ("data_type", "context"),
        "operation": ("operation", "stt"),
        "headers": ("headers", {"content-type": "text/plain"}),
        "missing-dispatch": ("dispatch_id", "unknown"),
    }
    if case in changes:
        key, value = changes[case]
        arguments[key] = value
    elif case == "body-copy":
        copied = bytes(bytearray(request.body))
        assert copied == request.body and copied is not request.body
        arguments["body"] = copied
    elif case == "settled":
        ledger.settle(reservation, 10)
    elif case == "row-dispatch":
        ledger._change(
            lambda: ledger._db.execute(
                "UPDATE security_cost_requests_v2 SET dispatch_id='other' WHERE reservation_id=?",
                (reservation,),
            )
        )
    elif case == "quote":
        ledger._change(
            lambda: ledger._db.execute(
                "UPDATE security_cost_requests_v2 SET quote_json='{}' WHERE reservation_id=?",
                (reservation,),
            )
        )
    elif case == "blocked":
        ledger._change(lambda: ledger._db.execute("UPDATE security_cost_accounts_v2 SET blocked=1"))
    elif case == "over-budget":
        # Authenticated malformed financial state is a defensive input, not a valid quote.
        ledger._change(
            lambda: ledger._db.execute(
                "UPDATE security_cost_requests_v2 SET reserved_amount=101 WHERE reservation_id=?",
                (reservation,),
            )
        )
    else:
        clock.utc = 2000
    before = tuple(
        ledger._db.execute(
            "SELECT state,reserved_amount,actual,dispatch_id,quote_json FROM security_cost_requests_v2"
        ).fetchone()
    )
    witness = ledger._witness.read_bytes()
    with pytest.raises(SecurityError, match="^" + code + "$"):
        ledger.validate_dispatch(**arguments)
    assert (
        tuple(
            ledger._db.execute(
                "SELECT state,reserved_amount,actual,dispatch_id,quote_json FROM security_cost_requests_v2"
            ).fetchone()
        )
        == before
    )
    assert ledger._witness.read_bytes() == witness


@pytest.mark.parametrize(
    "case,code",
    [
        ("tamper", "LEDGER_ROLLBACK_DETECTED"),
        ("settle", None),
        ("legacy", "COST_LEGACY_UNSCOPED"),
        ("foreign", "COST_UNRESOLVED_EXPOSURE"),
    ],
    ids=[f"G06-COV2-EXTERNAL-{i:03}" for i in range(4)],
)
def test_cov2_external_connection_changes_are_reauthenticated(
    cov2_account: Any, case: str, code: str | None
) -> None:
    ledger, request, settings, clock = cov2_account
    reservation = reserve(ledger, request, settings, "active")
    other = reserve(ledger, request, settings, "other")
    cov2_open(ledger, request, reservation)
    if case == "tamper":
        connection = sqlite3.connect(ledger.db_path)
        try:
            connection.execute(
                "UPDATE security_cost_requests_v2 SET reserved_amount=0 WHERE reservation_id=?",
                (other,),
            )
            connection.commit()
        finally:
            connection.close()
    else:
        with CostLedger(ledger.db_path, clock=clock.now, monotonic=clock.monotonic) as external:
            if case == "settle":
                external.settle(other, 7)
            else:
                external.reserve("p", "legacy-external", 1, 100)
                if case == "foreign":
                    external.adopt_legacy(
                        "p",
                        replace(settings, period_start_utc=2000, period_end_utc=3000),
                        confirmed=True,
                    )
    arguments = dict(
        data_type=request.data_type,
        operation=request.operation,
        dispatch_id="cov2",
        phase="write",
        bytes_sent=1,
    )
    if code is None:
        ledger.validate_dispatch(reservation, "p", request.endpoint, request.body, **arguments)
        assert (balance(ledger)["confirmed"], balance(ledger)["reserved"]) == (7, 13)
    else:
        with pytest.raises(SecurityError, match="^" + code + "$"):
            ledger.validate_dispatch(reservation, "p", request.endpoint, request.body, **arguments)
    row = ledger._db.execute(
        "SELECT state,reserved_amount FROM security_cost_requests_v2 WHERE reservation_id=?",
        (reservation,),
    ).fetchone()
    assert tuple(row) == ("RESERVED", 13)


@pytest.mark.parametrize(
    "case,code",
    [
        ("phase", "COST_REQUEST_INVALID"),
        ("provider", "COST_QUOTE_MISMATCH"),
        ("fingerprint", "COST_QUOTE_MISMATCH"),
        ("catalog", "COST_QUOTE_MISMATCH"),
        ("quote", "COST_QUOTE_MISMATCH"),
    ],
    ids=[f"G06-COV2-OPEN-{i:03}" for i in range(5)],
)
def test_cov2_dispatch_open_does_not_accept_inconsistent_quotes(
    cov2_account: Any, case: str, code: str
) -> None:
    ledger, request, settings, _ = cov2_account
    reservation = reserve(ledger, request, settings, "open")
    if case == "fingerprint":
        ledger._change(
            lambda: ledger._db.execute(
                "UPDATE security_cost_requests_v2 SET request_fingerprint=?", ("0" * 64,)
            )
        )
    elif case == "catalog":
        value = json.loads(ledger._request(reservation)["policy_json"])
        value["catalog_digest"] = "0" * 64
        ledger._change(
            lambda: ledger._db.execute(
                "UPDATE security_cost_requests_v2 SET policy_json=?", (json.dumps(value),)
            )
        )
    elif case == "quote":
        value = json.loads(ledger._request(reservation)["quote_json"])
        value["amount"] = 14
        ledger._change(
            lambda: ledger._db.execute(
                "UPDATE security_cost_requests_v2 SET quote_json=?", (json.dumps(value),)
            )
        )
    with pytest.raises(SecurityError, match="^" + code + "$"):
        ledger.validate_dispatch(
            reservation,
            "q" if case == "provider" else "p",
            request.endpoint,
            request.body,
            data_type=request.data_type,
            operation=request.operation,
            dispatch_id="cov2",
            phase="wrong" if case == "phase" else "open",
        )
    assert ledger._request(reservation)["dispatch_id"] is None
    assert ledger._request(reservation)["state"] == "RESERVED"


# G-P06b / G06R-10: a USER_CAP open never re-quotes, so the stored catalog digest is its
# only catalog binding. Each negative row changes only that relation; 000 is the control.
COV3_OPEN = [
    pytest.param("unchanged", id="G06-COV3-OPEN-000"),
    pytest.param("stored-digest", id="G06-COV3-OPEN-001"),
    pytest.param("catalog-updated", id="G06-COV3-OPEN-002"),
    pytest.param("catalog-updated-gateway", id="G06-COV3-OPEN-003"),
]


@pytest.mark.parametrize("case", COV3_OPEN)
def test_cov3_user_cap_open_is_bound_to_the_reserving_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    unpriced = dict(price_as_of_utc=None, valid_from_utc=None, valid_until_utc=None)
    catalog = install_catalog(monkeypatch, price(**unpriced))
    settings = policy(catalog, mode="general", general_acknowledged=True, cap=13)
    clock, request, wire = Clock(), text_request(), Wire()
    with (
        ConsentStore(tmp_path / "consent.sqlite") as consent,
        CostLedger(tmp_path / "cost.sqlite", clock=clock.now, monotonic=clock.monotonic) as ledger,
    ):
        ledger.apply_policy("p", settings)
        reservation = reserve(ledger, request, settings, "cov3")
        row = ledger._request(reservation)
        assert (row["quote_kind"], row["reserved_amount"], row["catalog_digest"]) == (
            "USER_CAP",
            13,
            catalog.sha256,
        )
        if case == "stored-digest":
            # An authenticated row whose reserving catalog differs from the loaded one
            # (fixture via the owned connection; not a claim about forging the witness).
            stored_policy = json.loads(row["policy_json"])
            stored_policy["catalog_digest"] = "0" * 64
            stored_quote = json.loads(row["quote_json"])
            stored_quote["policy"] = stored_policy
            ledger._change(
                lambda: ledger._db.execute(
                    "UPDATE security_cost_requests_v2 SET policy_json=?,quote_json=? "
                    "WHERE reservation_id=?",
                    (json.dumps(stored_policy), json.dumps(stored_quote), reservation),
                )
            )
        elif case.startswith("catalog-updated"):
            # The compiled catalog changed between reservation and dispatch (an update):
            # same wire entry, so only the digest relation differs.
            updated = install_catalog(monkeypatch, price(**unpriced, review_id="UPDATED_FIXTURE"))
            assert updated.sha256 != catalog.sha256 and updated.find(request) is not None
        witness = ledger._witness.read_bytes()
        if case == "unchanged":
            cov2_open(ledger, request, reservation)  # control: the same row does open
            assert ledger._request(reservation)["dispatch_id"] == "cov2"
            return
        with pytest.raises(SecurityError, match="^COST_QUOTE_MISMATCH$"):
            if case.endswith("gateway"):
                view = gateway(consent, ledger, wire, request)
                view.chunk_bytes = len(request.body)
                view.request(
                    "p",
                    request.endpoint,
                    request.data_type,
                    request.body,
                    reservation_id=reservation,
                )
            else:
                cov2_open(ledger, request, reservation)
        after = ledger._request(reservation)
        assert (after["state"], after["dispatch_id"], after["reserved_amount"]) == (
            "RESERVED",
            None,
            13,
        )
        assert balance(ledger)["reserved"] == 13 and balance(ledger)["unknown_exposure"] == 0
        assert wire.opens == 0 and wire.writes == []
        assert ledger._witness.read_bytes() == witness  # a refused open writes nothing


@pytest.mark.parametrize("slot", range(4), ids=[f"G06-COV2-TYPED-{i:03}" for i in range(4)])
def test_cov2_ledger_public_apis_require_actual_dtos(cov2_account: Any, slot: int) -> None:
    ledger, request, settings, _ = cov2_account
    quoted = ledger.quote_request(request, settings)
    before = ledger._witness.read_bytes()
    with pytest.raises(SecurityError, match="^COST_REQUEST_INVALID$"):
        if slot == 0:
            ledger.apply_policy("p", None)
        else:
            arguments: list[Any] = ["typed", quoted, settings, request]
            arguments[slot] = None
            ledger.reserve_quote(*arguments)
    assert ledger.reservations("p") == [] and ledger._witness.read_bytes() == before


@pytest.mark.parametrize("_case", ["G06-COV2-CACHE"], ids=str)
def test_cov2_bounded_quote_caches_do_not_drop_durable_money(cov2_account: Any, _case: str) -> None:
    ledger, _, initial, _ = cov2_account
    settings = replace(initial, limit=1000, policy_version=2)
    ledger.apply_policy("p", settings)
    requests = [text_request(i) for i in range(1, 7)]
    quotes = [ledger.quote_request(request, settings) for request in requests]
    assert [q.amount for q in quotes] == [13, 14, 14, 15, 16, 16]
    assert len(ledger._prepared_quotes) == 4
    reservations = [
        ledger.reserve_quote("cache" + str(i), quoted, settings, request)
        for i, (quoted, request) in enumerate(zip(quotes, requests, strict=True))
    ]
    assert len(ledger._reserved_quotes) == 4
    assert balance(ledger)["reserved"] == 88 and len(ledger.reservations("p")) == 6
    cov2_open(ledger, requests[0], reservations[0])  # evicted fast path must revalidate
    assert ledger._request(reservations[0])["state"] == "RESERVED"


@pytest.mark.parametrize("_case", ["G06-COV2-OLDV2"], ids=str)
def test_cov2_authenticated_old_v2_gets_an_audit_column_without_spending_loss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _case: str
) -> None:
    catalog = install_catalog(monkeypatch, price())
    settings, clock, db = policy(catalog), Clock(), tmp_path / "old-v2.sqlite"
    with CostLedger(db, clock=clock.now) as ledger:
        ledger.apply_policy("p", settings)
        reserve(ledger, text_request(), settings, "preserved")
        # A known old schema fixture. Signing is setup, not the result oracle.
        ledger._db.execute("ALTER TABLE security_cost_meta_v2 DROP COLUMN clock_reset_audit")
        ledger._write_witness()
        revision = ledger._db.execute("SELECT revision FROM security_cost_meta_v2").fetchone()[0]
    with CostLedger(db, clock=clock.now) as ledger:
        meta = ledger._db.execute(
            "SELECT revision,clock_high_water_utc,clock_reset_audit FROM security_cost_meta_v2"
        ).fetchone()
        assert tuple(meta) == (revision + 1, 1000, "[]")
        assert balance(ledger)["reserved"] == 13 and ledger.availability() is None
        assert "clock_reset_protocol_version" not in json.loads(ledger._witness.read_bytes())


@pytest.mark.parametrize(
    "kind", ["upgrade", "change"], ids=["G06-COV2-IO-upgrade", "G06-COV2-IO-change"]
)
def test_cov2_witness_failure_rolls_back_without_resigning_old_money(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    db, clock = tmp_path / "io.sqlite", Clock()
    catalog = install_catalog(monkeypatch, price())
    settings = policy(catalog)
    if kind == "upgrade":
        Legacy = legacy_class(tmp_path)
        with Legacy(db) as old:
            old.reserve("p", "original", 1, 100)
        ledger = None
    else:
        ledger = CostLedger(db, clock=clock.now)
    witness = db.with_name(db.name + ".cost-witness")
    before = witness.read_bytes()

    def failed_witness(self: Any) -> None:
        raise OSError("G06-FAULT-CANARY")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(CostLedger, "_write_witness", failed_witness)
            with pytest.raises(SecurityError, match="^SECURITY_STATE_UNAVAILABLE$"):
                if ledger is None:
                    CostLedger(db, clock=clock.now)
                else:
                    ledger.apply_policy("p", settings)
        assert witness.read_bytes() == before
    finally:
        if ledger is not None:
            ledger.close()
    connection = sqlite3.connect(db)
    try:
        if kind == "upgrade":
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE name='security_cost_meta_v2'"
                ).fetchone()[0]
                == 0
            )
            assert tuple(
                connection.execute("SELECT amount,state FROM security_cost_requests").fetchone()
            ) == (1, "RESERVED")
        else:
            assert (
                connection.execute("SELECT COUNT(*) FROM security_cost_accounts_v2").fetchone()[0]
                == 0
            )
    finally:
        connection.close()


@pytest.mark.parametrize(
    "kind",
    ["oversize", "not-object", "missing-meta"],
    ids=[f"G06-COV2-WITNESS-{i:03}" for i in range(3)],
)
def test_cov2_legacy_witness_shapes_are_not_blessed_as_v2(tmp_path: Path, kind: str) -> None:
    db, Legacy = tmp_path / "legacy.sqlite", legacy_class(tmp_path)
    with Legacy(db):
        pass
    witness = db.with_name(db.name + ".cost-witness")
    if kind == "missing-meta":
        connection = sqlite3.connect(db)
        try:
            connection.execute("DELETE FROM security_cost_meta")
            connection.commit()
        finally:
            connection.close()
    else:
        witness.write_bytes(b"x" * 4097 if kind == "oversize" else b"[]")
    before = witness.read_bytes()
    with pytest.raises(SecurityError, match="^LEDGER_ROLLBACK_DETECTED$"):
        CostLedger(db)
    assert witness.read_bytes() == before


@pytest.mark.parametrize("_case", ["G06-COV2-AVAILABILITY"], ids=str)
def test_cov2_cost_io_failure_is_a_closed_availability_not_an_app_failure(
    cov2_account: Any, monkeypatch: pytest.MonkeyPatch, _case: str
) -> None:
    ledger = cov2_account[0]
    before = ledger._witness.read_bytes()

    def failed_verify() -> None:
        raise OSError("G06-PRIVATE-ERROR-CANARY")

    monkeypatch.setattr(ledger, "_verify", failed_verify)
    assert ledger.availability() == "SECURITY_STATE_UNAVAILABLE"
    assert ledger._witness.read_bytes() == before


@pytest.mark.parametrize("_case", ["G06-COV2-CLOSED"], ids=str)
def test_cov2_closed_and_unavailable_ledgers_keep_their_safe_contract(
    tmp_path: Path, _case: str
) -> None:
    db = tmp_path / "closed.sqlite"
    ledger = CostLedger(db)
    ledger.close()
    ledger.close()
    with pytest.raises(SecurityError, match="^LEDGER_CLOSED$"):
        ledger.reservations("p")
    with pytest.raises(SecurityError, match="^LEDGER_CLOSED$"):
        ledger.validate_dispatch(
            "closed",
            "p",
            "https://cost.invalid/v1/responses",
            b"x",
            data_type="transcript",
            operation="summary",
            dispatch_id="closed",
            phase="write",
            bytes_sent=1,
        )
    witness = db.with_name(db.name + ".cost-witness")
    witness.write_bytes(b"bad")
    with CostLedger.open_for_ui(db) as unavailable:
        unavailable.finish_dispatch("never-opened")
        assert unavailable.availability() == "LEDGER_ROLLBACK_DETECTED"
    assert witness.read_bytes() == b"bad"


@pytest.mark.parametrize(
    "case,code",
    [
        ("zero-version", "SETTLEMENT_CONFLICT"),
        ("ambiguous-final", "SETTLEMENT_CONFLICT"),
        ("currency", "COST_CURRENCY_MISMATCH"),
        ("legacy", "COST_LEGACY_UNSCOPED"),
    ],
    ids=[f"G06-COV2-USAGE-{i:03}" for i in range(4)],
)
def test_cov2_usage_rejection_preserves_exposure_and_event_history(
    cov2_account: Any, case: str, code: str
) -> None:
    ledger, request, settings, _ = cov2_account
    reservation = (
        ledger.reserve("p", "unscoped", 1, 100)
        if case == "legacy"
        else reserve(ledger, request, settings, "usage")
    )
    account = ledger.account("p", "USD", 0, 2000)
    before = ledger._witness.read_bytes()
    with pytest.raises(SecurityError, match="^" + code + "$"):
        ledger.apply_usage(
            reservation,
            source="fixture",
            event_id="cov2",
            version=0 if case == "zero-version" else 1,
            final=1 if case == "ambiguous-final" else True,
            currency_code="EUR" if case == "currency" else "USD",
            period_id=account["account_id"],
            amount=1,
        )
    assert ledger._db.execute("SELECT COUNT(*) FROM security_cost_usage_events").fetchone()[0] == 0
    assert ledger._witness.read_bytes() == before
    assert ledger._request(reservation)["state"] == "RESERVED"
