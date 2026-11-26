"""GS05 request admission, ticket/key model and nonregistering preflight literals."""

from __future__ import annotations

# Independent, tiny collaborators exercise the real Gateway/credential/consent core.
import hashlib
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from itertools import product
from pathlib import Path
from typing import Any

import pytest

from recoryn.providers import ExecutionContext, ProviderError
from recoryn.security import (
    ConsentRequest,
    ConsentScope,
    ConsentStore,
    CostLedger,
    CredentialVault,
    Gateway,
    SecurityError,
)
from recoryn.security.credentials import (
    AuthBinding,
    CredentialEvent,
    CredentialService,
    CredentialTarget,
    ReadScope,
)
from recoryn.security.ledger import CostPreflight
from tests.property.test_secret_lifetime_case_space import execution_audit as execution_audit
from tests.unit.test_cost_cap import (
    Clock,
    flat_price,
    flat_request,
    install_catalog,
    policy,
    reserve,
)

ROUTES = (
    ("openai", "stt", "audio", "https://openai.gs05.invalid/v1/audio/transcriptions"),
    ("gemini", "stt", "audio", "https://gemini.gs05.invalid/v1beta/models/toy:generateContent"),
    ("openai", "summary", "transcript", "https://openai.gs05.invalid/v1/responses"),
    ("anthropic", "summary", "transcript", "https://anthropic.gs05.invalid/v1/messages"),
    (
        "gemini",
        "summary",
        "context",
        "https://gemini.gs05.invalid/v1beta/models/toy:generateContent",
    ),
)
K_A = "GS05-FAKE-CANARY-A"
K_B = "GS05-FAKE-CANARY-B"


def fake_auth_binding(
    policy: ConsentStore,
    provider: str,
    endpoint: str,
    kind: str,
    *,
    secret: str = "GS05-FAKE-REGRESSION-KEY",
) -> AuthBinding:
    backend = MemoryCredentials()
    vault = CredentialVault(backend=backend, namespace="GS05-REGRESSION")
    target = CredentialTarget(provider, endpoint)
    backend.values[vault._target(target.vault_key)] = secret.encode()
    credentials = CredentialService(vault, consents=policy)
    return credentials.capture_binding(target, kind)


class Tick:
    def __init__(self) -> None:
        self.value = 1000.0

    def __call__(self) -> float:
        return self.value


class MemoryCredentials:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}
        self.reads = 0
        self.read_threads: list[int] = []
        self.writes: list[str] = []
        self.deletes: list[str] = []
        self.error: BaseException | None = None
        self.write_error = False
        self.reading: Callable[[], None] = lambda: None

    def read(self, target: str) -> bytes | None:
        self.reads += 1
        self.read_threads.append(threading.get_ident())
        self.reading()
        if self.error is not None:
            raise self.error
        return self.values.get(target)

    def write(self, target: str, secret: bytes) -> None:
        self.writes.append(target)
        if self.write_error:
            raise OSError("GS05-PRIVATE-WRITE-CANARY")
        self.values[target] = secret

    def delete(self, target: str) -> None:
        self.deletes.append(target)
        if self.write_error:
            raise OSError("GS05-PRIVATE-DELETE-CANARY")
        self.values.pop(target, None)


class TinyLedger:
    def __init__(self, consents: ConsentStore) -> None:
        self.coordinator = consents.coordinator
        self.error: str | None = None
        self.state = "RESERVED"
        self.registered = 0
        self.preflights = 0
        self.dispatches: set[str] = set()

    def check_reservation(self, reservation: str, provider: str) -> None:
        if self.error is not None:
            raise SecurityError(self.error)

    def preflight_request(
        self, reservation: str, provider: str, target: str, body: bytes, **kwargs: Any
    ) -> CostPreflight:
        self.check_reservation(reservation, provider)
        self.preflights += 1
        return CostPreflight(self, reservation, hashlib.sha256(body).hexdigest(), 2000.0)

    def validate_dispatch(
        self,
        reservation: str,
        provider: str,
        target: str,
        body: bytes,
        *,
        dispatch_id: str,
        phase: str = "open",
        **kwargs: Any,
    ) -> None:
        self.check_reservation(reservation, provider)
        if phase == "open":
            assert not self.dispatches
            self.registered += 1
            self.dispatches.add(dispatch_id)
        else:
            assert dispatch_id in self.dispatches

    def mark_unknown(self, reservation: str) -> None:
        self.state = "UNKNOWN"

    def finish_dispatch(self, dispatch: str) -> None:
        self.dispatches.discard(dispatch)


class TinyConnection:
    def __init__(self, owner: TinyTransport, headers: Mapping[str, str]) -> None:
        self.owner = owner
        self._headers = dict(headers)
        self.output = b"{}"
        self.started = False
        self.closed = False

    def write(self, data: bytes, timeout: float) -> None:
        try:
            if not self.started:
                self.owner.headers += 1
                self.owner.wire_auth.append(dict(self._headers))
                self.started = True
            self.owner.writes.append(data)
            self.owner.on_write()
        finally:
            self._headers.clear()

    def read(self, limit: int, timeout: float) -> bytes:
        self.owner.on_read()
        result, self.output = self.output[:limit], self.output[limit:]
        return result

    def close(self) -> None:
        self.closed = True
        self._headers.clear()


class TinyTransport:
    def __init__(self) -> None:
        self.opens = self.dns = self.headers = 0
        self.writes: list[bytes] = []
        self.wire_auth: list[dict[str, str]] = []
        self.connections: list[TinyConnection] = []
        self.on_write: Callable[[], None] = lambda: None
        self.on_read: Callable[[], None] = lambda: None

    def open(
        self, target: Any, headers: Mapping[str, str], size: int, timeout: float
    ) -> TinyConnection:
        self.dns += 1
        self.opens += 1
        connection = TinyConnection(self, headers)
        self.connections.append(connection)
        return connection


@dataclass
class World:
    policy: ConsentStore
    ledger: TinyLedger
    backend: MemoryCredentials
    vault: CredentialVault
    credentials: CredentialService
    auth: AuthBinding
    wire: TinyTransport
    gateway: Gateway
    scope: ConsentScope
    request: ConsentRequest
    route: tuple[str, str, str, str]
    clock: Tick

    def send(self, body: bytes = b"abcdef", **kwargs: Any) -> bytes:
        provider, _, data, target = self.route
        return self.gateway.request(
            provider, target, data, body, reservation_id="reservation", **kwargs
        )


@contextmanager
def secret_world(
    policy: ConsentStore,
    route: int = 0,
    hook: Callable[[CredentialEvent], None] | None = None,
) -> Iterator[World]:
    provider, kind, data, endpoint = ROUTES[route]
    session = "gs05-" + uuid.uuid4().hex
    scope = ConsentScope.session(session)
    policy.bind_session(session)
    request = ConsentRequest(session, 0, kind, policy.policy_version)
    policy.grant(
        provider,
        endpoint,
        data,
        capability=kind,
        scope=scope,
        policy_version=request.policy_version,
    )
    bindings = policy.capture_bindings(provider, endpoint, (data,), scope=scope, request=request)
    backend, tick = MemoryCredentials(), Tick()
    vault = CredentialVault(backend=backend, namespace="GS05-FAKE")
    target = CredentialTarget(provider, endpoint)
    backend.values[vault._target(target.vault_key)] = K_A.encode()
    service = CredentialService(vault, consents=policy, clock=tick, hook=hook)
    auth = service.capture_binding(target, kind)
    ledger, wire = TinyLedger(policy), TinyTransport()
    root = Gateway(
        policy,
        ledger=ledger,
        transport=wire,
        expected_grants=bindings,
        chunk_bytes=3,
        auth_binding=auth,
    )
    root._clock = tick
    view = root.for_session(
        session, capability=kind, scope=scope, policy_version=request.policy_version
    )
    try:
        yield World(
            policy,
            ledger,
            backend,
            vault,
            service,
            auth,
            wire,
            view,
            scope,
            request,
            ROUTES[route],
            tick,
        )
    finally:
        assert service.await_shutdown(2), "owned key/read/request workers still active"


@pytest.fixture(scope="module")
def unit_policy(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ConsentStore]:
    with ConsentStore(
        tmp_path_factory.mktemp("gs05-unit") / "policy.db", clock=lambda: 1000
    ) as store:
        yield store


A_CASES = [
    pytest.param("GS05-A-" + "-".join(map(str, row)), *row, id="GS05-A-" + "-".join(map(str, row)))
    for row in product(range(5), range(4), range(3), range(2), range(2))
]


@pytest.mark.parametrize("case_id,route,consent,budget,cancel,epoch", A_CASES)
def test_admission_cube(
    case_id: str,
    route: int,
    consent: int,
    budget: int,
    cancel: int,
    epoch: int,
    unit_policy: ConsentStore,
) -> None:
    with secret_world(unit_policy, route) as world:
        ticket_events: list[str] = []
        world.credentials._hook = lambda event: ticket_events.append(event.stage)
        provider, kind, data, endpoint = world.route
        if consent == 1:
            world.policy._db.execute(
                "DELETE FROM security_grants_v2 WHERE provider=? AND endpoint=? AND capability=? "
                "AND data_type=? AND scope_kind='session' AND scope_id=?",
                (provider, endpoint, kind, data, world.request.session_id),
            )
        elif consent in (2, 3):
            world.policy.revoke(
                provider,
                endpoint,
                data,
                capability=kind,
                scope=world.scope,
                policy_version=world.request.policy_version,
            )
            if consent == 3:
                world.policy.grant(
                    provider,
                    endpoint,
                    data,
                    capability=kind,
                    scope=ConsentScope.session("other-session"),
                    policy_version=world.request.policy_version,
                )
        if budget == 2:
            world.ledger.error = "LEDGER_ROLLBACK_DETECTED"
        if epoch:
            world.credentials._epochs[world.auth.ref.target] = world.auth.ref.epoch + 1
        event = threading.Event()
        if cancel:
            event.set()
        expected = (
            "CANCELLED"
            if cancel
            else "CONSENT_REQUIRED"
            if consent
            else "BUDGET_REQUIRED"
            if budget == 1
            else "LEDGER_ROLLBACK_DETECTED"
            if budget == 2
            else "AUTH_REQUIRED"
            if epoch
            else None
        )
        assert world.backend.reads == 0
        if expected:
            with pytest.raises(SecurityError, match="^" + expected + "$"):
                world.gateway.request(
                    provider,
                    endpoint,
                    data,
                    b"abcdef",
                    reservation_id=None if budget == 1 else "reservation",
                    cancel=event,
                )
            assert world.backend.reads == world.wire.dns == world.wire.opens == 0, case_id
            assert world.wire.headers == 0 and world.wire.writes == []
            assert ticket_events.count("ticket_issued") == 0
        else:
            assert world.send() == b"{}"
            assert world.backend.reads == world.wire.opens == world.wire.headers == 1
            assert world.wire.writes == [b"abc", b"def"]
            assert world.ledger.state == "UNKNOWN"
            assert ticket_events.count("ticket_issued") == 1


F_CASES = [
    pytest.param(f"GS05-F-{route}-{field}", route, field, id=f"GS05-F-{route}-{field}")
    for route, field in product(range(5), range(8))
]


@pytest.mark.parametrize("case_id,route,field", F_CASES)
def test_binding(case_id: str, route: int, field: int, unit_policy: ConsentStore) -> None:
    with secret_world(unit_policy, route) as world:
        auth = world.auth
        provider, kind, data, endpoint = world.route
        expected = "AUTH_REQUIRED"
        if field == 0:
            target = CredentialTarget("other-provider", endpoint)
            world.gateway.auth_binding = replace(auth, ref=replace(auth.ref, target=target))
        elif field == 1:
            target = CredentialTarget(provider, endpoint + "/other")
            world.gateway.auth_binding = replace(auth, ref=replace(auth.ref, target=target))
        elif field == 2:
            world.gateway._request = replace(
                world.request, capability="summary" if kind == "stt" else "stt"
            )
            expected = "CONSENT_REQUIRED"
        elif field == 3:
            data = "context" if data != "context" else "audio"
            expected = "CONSENT_REQUIRED"
        elif field == 4:
            world.gateway._request = replace(world.request, session_id="other-session")
            expected = "CONSENT_REQUIRED"
        elif field == 5:
            world.gateway._request = replace(world.request, session_generation=1)
            expected = "PERMIT_REVOKED"
        elif field == 6:
            world.gateway.auth_binding = replace(
                auth, ref=replace(auth.ref, execution_id="old-execution")
            )
        else:
            world.gateway.auth_binding = replace(
                auth, ref=replace(auth.ref, epoch=auth.ref.epoch + 1)
            )
        with pytest.raises(SecurityError, match="^" + expected + "$"):
            world.gateway.request(provider, endpoint, data, b"abcdef", reservation_id="reservation")
        assert world.backend.reads == world.wire.opens == 0, case_id
        assert world.wire.writes == []


def ticket_scope(world: World) -> ReadScope:
    binding = world.gateway.expected_grants[0]
    return ReadScope(
        "request",
        world.auth.ref.target,
        binding,
        hashlib.sha256(b"abcdef").hexdigest(),
        "reservation",
        1030.0,
    )


T_UNIT = [pytest.param(f"GS05-T-{row:02}", row, id=f"GS05-T-{row:02}") for row in range(12)]


@pytest.mark.parametrize("case_id,row", T_UNIT)
def test_ticket_once(case_id: str, row: int, unit_policy: ConsentStore) -> None:
    from concurrent.futures import ThreadPoolExecutor

    entered = threading.Barrier(2)
    split = threading.Barrier(2)
    observed: list[CredentialEvent] = []

    def hook(event: CredentialEvent) -> None:
        observed.append(event)
        if row == 0 and event.stage == "ticket_enter":
            assert not world.credentials._mutex._is_owned()
            assert not getattr(world.policy.coordinator._local, "depth", 0)
            entered.wait(3)
        if row == 0 and event.stage == "ticket_released" and event.checked and not event.committed:
            assert not world.credentials._mutex._is_owned()
            assert not getattr(world.policy.coordinator._local, "depth", 0)
            split.wait(3)

    with secret_world(unit_policy, hook=hook) as world:
        scope = ticket_scope(world)
        if row in (8, 9):
            cancelled = threading.Event()

            def invalidate(event: CredentialEvent) -> None:
                if event.stage != "i_released":
                    return
                if row == 8:
                    cancelled.set()
                else:
                    provider, kind, data, endpoint = world.route
                    world.policy.grant(
                        provider,
                        endpoint,
                        data,
                        capability=kind,
                        scope=world.scope,
                        policy_version=world.request.policy_version,
                    )

            world.credentials._hook = invalidate
            expected = "CANCELLED" if row == 8 else "PERMIT_REVOKED"
            with pytest.raises(SecurityError, match="^" + expected + "$"):
                world.send(cancel=cancelled)
            assert world.backend.reads == world.wire.opens == 0
            assert not world.credentials._tickets
            return
        ticket = world.credentials.issue_ticket(world.auth.ref, scope, world.auth.plan)
        if row == 0:
            claims: list[object] = []
            leases: list[object] = []

            def contender() -> str:
                try:
                    claim = world.credentials.consume_ticket(ticket, scope)
                    claims.append(claim)
                    lease = world.credentials.read_claim(claim)
                    leases.append(lease)
                    lease.release()
                    return "SUCCESS"
                except SecurityError as error:
                    return error.code

            with ThreadPoolExecutor(max_workers=2) as pool:
                calls = [pool.submit(contender) for _ in range(2)]
                results = [call.result(5) for call in calls]
            assert sorted(results) == ["AUTH_REQUIRED", "SUCCESS"]
            assert len(claims) == len(leases) == 1, "single transition winner/lease"
            assert sum(e.stage == "ticket_enter" for e in observed) == 2
            # Disable only the rendezvous for the terminal replay, not the real service.
            world.credentials._hook = lambda event: observed.append(event)
            assert contender() == "AUTH_REQUIRED"
            assert world.backend.reads == 1 and not world.credentials._tickets
            assert world.wire.opens == 0 and world.wire.writes == []
            return
        changed = scope
        expected = "AUTH_REQUIRED"
        if row == 1:
            ticket = replace(ticket, nonce="unknown")
        elif row in (2, 3):
            target = CredentialTarget(
                "other-provider" if row == 2 else scope.target.provider_id,
                scope.target.endpoint if row == 2 else scope.target.endpoint + "/other",
            )
            changed = replace(scope, target=target)
        elif row == 4:
            changed = replace(scope, request_id="other-request")
        elif row == 5:
            changed = replace(scope, body_sha256="0" * 64)
        elif row == 6:
            changed = replace(scope, reservation_id="other-reservation")
        elif row == 7:
            world.clock.value = 1031
            expected = "TIMEOUT"
        elif row == 8:
            world.credentials.discard_ticket(ticket)
            expected = "AUTH_REQUIRED"
        elif row == 9:
            provider, kind, data, endpoint = world.route
            world.policy.grant(
                provider,
                endpoint,
                data,
                capability=kind,
                scope=world.scope,
                policy_version=world.request.policy_version,
            )
            with pytest.raises(SecurityError, match="^PERMIT_REVOKED$"):
                world.policy.validate_binding(scope.binding)
            world.credentials.discard_ticket(ticket)
        elif row == 10:
            world.credentials._epochs[scope.target] = 1
        else:
            world.credentials.discard_ticket(ticket)
        with pytest.raises(SecurityError, match="^" + expected + "$"):
            world.credentials.consume_ticket(ticket, changed)
        assert world.backend.reads == world.wire.opens == 0, case_id


pytestmark = pytest.mark.unit


class _ObservedQuotes(OrderedDict):
    def __init__(self, original: Any) -> None:
        self.events: list[str] = []
        self.armed = False
        super().__init__(original)
        self.armed = True

    def __setitem__(self, key: Any, value: Any) -> None:
        if self.armed:
            self.events.append("set")
        super().__setitem__(key, value)

    def pop(self, *args: Any) -> Any:
        self.events.append("pop")
        return super().pop(*args)

    def popitem(self, *args: Any, **kwargs: Any) -> Any:
        self.events.append("popitem")
        return super().popitem(*args, **kwargs)

    def move_to_end(self, *args: Any, **kwargs: Any) -> None:
        self.events.append("move")
        super().move_to_end(*args, **kwargs)


J_CASES = [
    pytest.param(
        f"GS05-J-{quote}-{cache}-{gate}", quote, cache, gate, id=f"GS05-J-{quote}-{cache}-{gate}"
    )
    for quote, cache, gate in product(range(2), range(2), range(3))
]


@pytest.mark.parametrize("case_id,quote_kind,cache_miss,gate", J_CASES)
def test_nonregistering_preflight(
    case_id: str,
    quote_kind: int,
    cache_miss: int,
    gate: int,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Fixed fee 13 is a hand oracle, independent of quote/parser implementation.
    entry = flat_price(13)
    if quote_kind:
        from dataclasses import replace

        entry = replace(entry, price_as_of_utc=None, valid_from_utc=None, valid_until_utc=None)
    catalog = install_catalog(monkeypatch, entry)
    settings = policy(
        catalog,
        cap=13,
        limit=100,
        mode="general" if quote_kind else "strict",
        general_acknowledged=bool(quote_kind),
    )
    clock, request = Clock(), flat_request(13)
    db = tmp_path / "cost.db"
    ledger = CostLedger(db, clock=clock.now, monotonic=clock.monotonic)
    try:
        ledger.apply_policy("p", settings)
        reservation = reserve(ledger, request, settings, "gs05-j")
        if cache_miss:
            ledger.close()
            ledger = CostLedger(db, clock=clock.now, monotonic=clock.monotonic)
        prepared, reserved = (
            _ObservedQuotes(ledger._prepared_quotes),
            _ObservedQuotes(ledger._reserved_quotes),
        )
        ledger._prepared_quotes, ledger._reserved_quotes = prepared, reserved
        before = (
            tuple(prepared.items()),
            tuple(reserved.items()),
            dict(ledger._quote_deadlines),
            dict(ledger._dispatches),
            ledger._witness.read_bytes(),
            tuple(ledger._request(reservation)),
            ledger._db.total_changes,
        )
        statements: list[str] = []
        ledger._db.set_trace_callback(statements.append)
        prior = None
        for stage in range(gate + 1):
            clock.tick = 10 + stage
            prior = ledger.preflight_request(
                reservation,
                "p",
                request.endpoint,
                request.body,
                data_type="transcript",
                operation="summary",
                headers={},
                prior=prior,
            )
            assert prior.deadline == 1010
        assert prepared.events == reserved.events == []
        after = (
            tuple(prepared.items()),
            tuple(reserved.items()),
            dict(ledger._quote_deadlines),
            dict(ledger._dispatches),
            ledger._witness.read_bytes(),
            tuple(ledger._request(reservation)),
            ledger._db.total_changes,
        )
        assert after == before, case_id
        assert not any(
            sql.lstrip().split(" ", 1)[0].upper()
            in {"INSERT", "UPDATE", "DELETE", "REPLACE", "BEGIN", "COMMIT"}
            for sql in statements
        ), statements
        row = ledger._request(reservation)
        assert (row["state"], row["dispatch_id"], row["reserved_amount"]) == ("RESERVED", None, 13)
        assert row["quote_kind"] == ("USER_CAP" if quote_kind else "VERIFIED")
    finally:
        ledger._db.set_trace_callback(None)
        ledger.close()


def key_command(world: World, action: str, secret: str = K_B) -> tuple[threading.Event, list[Any]]:
    done = threading.Event()
    results: list[Any] = []

    def completed(result: Any) -> None:
        results.append(result)
        done.set()

    assert world.credentials.try_enqueue_key_change(
        world.auth.ref.target,
        action,
        secret if action == "save" else None,
        command_nonce=uuid.uuid4().hex,
        selection_generation=0,
        done=completed,
    )
    return done, results


@contextmanager
def widget_for_world(world: World) -> Iterator[Any]:
    from PySide6.QtWidgets import QApplication

    from recoryn.ui.privacy import PrivacyPanel
    from tests.ui.test_secret_lifetime_ui import close_privacy, settle_privacy

    app = QApplication.instance() or QApplication([])
    with CostLedger(world.policy.db_path) as ledger:
        panel = PrivacyPanel(world.policy, ledger, world.vault)
        panel.backend.credentials = world.credentials
        panel.select_session(world.request.session_id)
        try:
            yield panel
        finally:
            if not panel._closed:
                settle_privacy(panel)
            close_privacy(panel)
            app.processEvents()


E_CASES = [pytest.param(f"GS05-E-{row:02}", row, id=f"GS05-E-{row:02}") for row in range(20)]


@pytest.mark.parametrize("case_id,row", E_CASES)
def test_key_model(case_id: str, row: int, unit_policy: ConsentStore, tmp_path: Path) -> None:
    with secret_world(unit_policy) as world:
        if row < 12:
            action, fail, phase = "save" if row < 6 else "delete", (row % 6) // 3, row % 3
            world.backend.write_error = bool(fail)
            results: list[Any] = []

            def change() -> None:
                done, received = key_command(world, action)
                assert done.wait(3)
                results.extend(received)

            if phase == 0:
                change()
            else:
                fired = False

                def hook(event: CredentialEvent) -> None:
                    nonlocal fired
                    stage = "i_released" if phase == 1 else "write_released"
                    if event.stage == stage and not fired:
                        fired = True
                        change()

                world.credentials._hook = hook
                with pytest.raises(SecurityError, match="^CONSENT_REQUIRED$") as error:
                    world.send()
                assert error.value.outcome_known is (phase == 1)
                assert world.backend.reads == (0 if phase == 1 else 1)
                assert world.wire.writes == ([] if phase == 1 else [b"abc"])
                assert world.ledger.state == ("RESERVED" if phase == 1 else "UNKNOWN")
            assert len(results) == 1
            expected = (
                ("VAULT_WRITE_FAILED" if action == "save" else "VAULT_DELETE_FAILED")
                if fail
                else None
            )
            assert results[0].error_code == expected
            with pytest.raises(SecurityError, match="^AUTH_REQUIRED$"):
                world.credentials.assert_current(world.auth.ref)
            assert results[0].epoch == 1
        elif row in (12, 13):
            target = CredentialTarget(
                "gemini" if row == 12 else world.auth.ref.target.provider_id,
                world.auth.ref.target.endpoint
                if row == 12
                else world.auth.ref.target.endpoint + "/b",
            )
            other = world.credentials.capture_ref(target)
            key = world.vault._target(target.vault_key)
            world.backend.values[key] = K_A.encode()
            done, results = key_command(world, "save")
            assert done.wait(3) and results[0].error_code is None
            world.credentials.assert_current(other)
            assert world.backend.values[key] == K_A.encode()
        elif row == 14:
            other = world.credentials.capture_binding(world.auth.ref.target, "summary")
            done, results = key_command(world, "save")
            assert done.wait(3) and results[0].error_code is None
            for ref in (world.auth.ref, other.ref):
                with pytest.raises(SecurityError, match="^AUTH_REQUIRED$"):
                    world.credentials.assert_current(ref)
        elif row == 15:
            with widget_for_world(world) as panel:
                before = world.credentials.capture_ref(world.auth.ref.target)
                values = dict(world.backend.values)
                panel.controls["stt"].key.setText(K_B)
                assert world.credentials.capture_ref(world.auth.ref.target) == before
                assert world.backend.values == values
                assert world.backend.writes == world.backend.deletes == []
                assert world.backend.reads == 0
        elif row in (16, 17):
            entered, release = threading.Event(), threading.Event()
            original_write = world.backend.write
            original_delete = world.backend.delete
            native_order: list[str] = []

            def before(kind: str) -> None:
                native_order.append(kind)
                assert not world.credentials._mutex._is_owned()
                assert not getattr(world.policy.coordinator._local, "depth", 0)
                if len(native_order) == 1:
                    entered.set()
                    assert release.wait(3)

            def write(target: str, value: bytes) -> None:
                before("save")
                original_write(target, value)

            def delete(target: str) -> None:
                before("delete")
                original_delete(target)

            world.backend.write, world.backend.delete = write, delete
            first = "save" if row == 16 else "delete"
            second = "delete" if row == 16 else "save"
            try:
                done1, result1 = key_command(world, first)
                assert entered.wait(3)
                done2, result2 = key_command(world, second)
                assert native_order == [first]
                release.set()
                assert done1.wait(3) and done2.wait(3)
                assert native_order == [first, second]
                assert result1[0].epoch == 1 and result2[0].epoch == 2
                key = world.vault._target(world.auth.ref.target.vault_key)
                assert world.backend.values.get(key) == (None if row == 16 else K_B.encode())
            finally:
                release.set()
        elif row == 18:
            from tests.ui.test_secret_lifetime_ui import settle_privacy, spin_privacy

            with widget_for_world(world) as panel:
                control = panel.controls["stt"]
                control.provider.setCurrentIndex(control.provider.findData("openai"))
                control.endpoint.setText(world.route[3])
                control.model.setText("fake-model")
                settle_privacy(panel)
                entered, release = threading.Event(), threading.Event()
                original = world.backend.write

                def write(target: str, secret: bytes) -> None:
                    entered.set()
                    assert release.wait(3)
                    original(target, secret)

                world.backend.write = write
                try:
                    control.key.setText(K_B)
                    panel._action("stt", "save")
                    assert entered.wait(3) and control.key.text() == ""
                    control.status.setText("CLOSED-VIEW")
                    panel.close()
                    assert not panel.backend.idle
                    release.set()
                    spin_privacy(lambda: panel.backend.idle)
                    assert control.status.text() == "CLOSED-VIEW"
                    assert control.key.text() == ""
                finally:
                    release.set()
        else:
            import sqlite3

            copy = sqlite3.connect(tmp_path / "restart.db")
            try:
                world.policy._db.backup(copy)
            finally:
                copy.close()
            with ConsentStore(tmp_path / "restart.db", clock=lambda: 1000) as restarted:
                next_run = CredentialService(world.vault, consents=restarted)
                try:
                    assert next_run.execution_id != world.auth.ref.execution_id
                    with pytest.raises(SecurityError, match="^AUTH_REQUIRED$"):
                        next_run.assert_current(world.auth.ref)
                    assert world.backend.reads == world.wire.opens == 0
                finally:
                    assert next_run.await_shutdown(1)


X_CASES = [pytest.param(f"GS05-X-{row:02}", row, id=f"GS05-X-{row:02}") for row in range(11)]


@pytest.mark.parametrize("case_id,row", X_CASES)
def test_closed_routes(case_id: str, row: int, unit_policy: ConsentStore) -> None:
    from recoryn.providers import LocalModelAttestation, ProviderConfig
    from recoryn.providers._common import Run
    from recoryn.ui.privacy import ExecutionIntent, PrivacyBackend, ProviderIntent

    with secret_world(unit_policy) as world:
        if row in (0, 1):
            local = row == 1
            provider = "ollama" if local else "faster_whisper"
            endpoint = "http://127.0.0.1:11434/api/chat" if local else ""
            kind = "summary" if local else "stt"
            proof = (
                LocalModelAttestation(endpoint, "toy", "a" * 64, True, time.monotonic() + 30)
                if local
                else None
            )
            backend = PrivacyBackend(
                world.policy,
                world.ledger,
                world.vault,
                gateway=Gateway(world.policy, transport=world.wire),
                notify_quote=lambda *args: None,
            )
            try:
                if local:
                    world.policy.approve_local_endpoint(endpoint, "a" * 64, ttl_seconds=30)
                    world.policy.grant(
                        provider,
                        endpoint,
                        "transcript",
                        capability=kind,
                        scope=world.scope,
                        policy_version=world.request.policy_version,
                    )
                intent = ExecutionIntent(
                    kind,
                    world.request.session_id,
                    ProviderIntent(provider, "toy", endpoint, 8192 if local else None, 10, proof),
                    world.scope,
                    None,
                    threading.Event(),
                    backend.credentials.capture_plan(kind),
                    None,
                )
                execution = backend.prepare_execution(intent)
                assert execution.context.headers == {}
                if local:
                    assert (
                        execution.gateway.request(provider, endpoint, "transcript", b"abcdef")
                        == b"{}"
                    )
                    assert world.wire.opens == 1
                else:
                    assert execution.gateway is None and world.wire.opens == 0
                assert world.backend.reads == 0
            finally:
                assert backend.await_shutdown(2)
        elif row == 2:
            endpoint = "http://127.0.0.1:11434/api/chat"
            world.policy.approve_local_endpoint(endpoint, "a" * 64, ttl_seconds=30)
            world.policy.grant(
                "ollama",
                endpoint,
                "audio",
                capability="stt",
                scope=world.scope,
                policy_version=world.request.policy_version,
            )
            bindings = world.policy.capture_bindings(
                "ollama", endpoint, ("audio",), scope=world.scope, request=world.request
            )
            bad = Gateway(
                world.policy,
                transport=world.wire,
                expected_grants=bindings,
                auth_binding=world.auth,
            ).for_session(
                world.request.session_id,
                capability="stt",
                scope=world.scope,
                policy_version=world.request.policy_version,
            )
            with pytest.raises(SecurityError, match="^INPUT_INVALID$"):
                bad.request("ollama", endpoint, "audio", b"abcdef")
            assert world.backend.reads == world.wire.opens == 0
        elif row == 3:
            with pytest.raises(ProviderError, match="^CAPABILITY_UNSUPPORTED$"):
                ProviderConfig("unknown-provider", "model")
            assert world.backend.reads == world.wire.opens == 0
        elif row == 4:
            world.gateway.auth_binding = None
            with pytest.raises(SecurityError, match="^AUTH_REQUIRED$"):
                world.send()
            assert world.backend.reads == world.wire.opens == 0
        elif row == 5:
            with pytest.raises(ProviderError, match="^INPUT_INVALID$"):
                ExecutionContext(headers={"Authorization": K_A})
            assert world.backend.reads == world.wire.opens == 0
        elif row == 6:
            config = ProviderConfig(world.route[0], "model", endpoint=world.route[3])
            run = Run(config, ExecutionContext())
            with pytest.raises(ProviderError, match="^INPUT_INVALID$"):
                run.request(
                    world.gateway,
                    world.route[3],
                    world.route[2],
                    b"abcdef",
                    headers={"x-api-key": K_A},
                    operation=world.route[1],
                )
            assert world.backend.reads == world.wire.opens == 0
            assert run.calls == 0
        elif row == 7:
            from itertools import count

            reservations = count()
            config = ProviderConfig(world.route[0], "model", endpoint=world.route[3])
            context = ExecutionContext(reservation_factory=lambda request: f"r{next(reservations)}")
            run = Run(config, context)
            for _ in range(2):
                assert (
                    run.request(
                        world.gateway,
                        world.route[3],
                        world.route[2],
                        b"abcdef",
                        operation=world.route[1],
                    )
                    == {}
                )
            assert world.backend.reads == world.wire.opens == 2
            assert len(run.reservations) == 2
        elif row == 8:
            assert world.send() == b"{}"
            assert world.backend.reads == world.wire.headers == 1
            assert world.wire.writes == [b"abc", b"def"]
        else:

            def partial() -> None:
                raise OSError("GS05-PRIVATE-PARTIAL-CANARY")

            world.wire.on_write = partial
            with pytest.raises(SecurityError, match="^REMOTE_OUTCOME_UNKNOWN$") as error:
                world.send(body=b"" if row == 10 else b"abcdef")
            assert not error.value.outcome_known
            assert world.backend.reads == world.wire.opens == world.wire.headers == 1
            assert world.wire.writes == ([b""] if row == 10 else [b"abc"])
            assert world.ledger.state == "UNKNOWN"
