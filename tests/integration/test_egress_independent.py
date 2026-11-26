"""BR23 independent egress oracles; fake vault/transport and synthetic data only."""

from __future__ import annotations

import json
import os
import threading
import time
import zipfile
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import pytest

from recoryn.diagnostics import register_secret, support_bundle
from recoryn.providers import (
    LocalModelAttestation,
    ProviderError,
    STTRequest,
    SummaryRequest,
    TranscriptSegment,
)
from recoryn.security import (
    ConsentRequest,
    ConsentScope,
    ConsentStore,
    CostLedger,
    CredentialVault,
    Gateway,
    SecurityError,
)
from recoryn.security._core import Endpoint
from recoryn.summarization import OllamaSummarizer, OpenAISummarizer
from recoryn.transcription import OpenAITranscriber
from tests.ui.test_cost_cap_ui import fixture_panel_balance, fixture_panel_catalog
from tests.ui.test_secret_lifetime_ui import (
    close_privacy,
    privacy_action,
    privacy_context,
    privacy_gateway,
    settle_privacy,
)
from tests.unit.test_cost_cap import fixture_balance, fixture_reservation, fixture_wire

pytestmark = pytest.mark.integration
URL = "https://api.example.test/v1/audio"


class _Connection:
    def __init__(self, response: bytes = b'{"text":"synthetic"}') -> None:
        self.writes: list[bytes] = []
        self.response = response
        self.closed = False

    def write(self, data: bytes, timeout: float) -> None:
        self.writes.append(data)

    def read(self, limit: int, timeout: float) -> bytes:
        piece, self.response = self.response[:limit], self.response[limit:]
        return piece

    def close(self) -> None:
        self.closed = True


class _Transport:
    def __init__(self) -> None:
        self.connections: list[_Connection] = []
        self.headers: list[dict[str, str]] = []
        self.response = b'{"text":"synthetic"}'

    def open(
        self, target: Endpoint, headers: Mapping[str, str], body_length: int, timeout: float
    ) -> _Connection:
        connection = _Connection(self.response)
        self.connections.append(connection)
        self.headers.append(dict(headers))
        return connection


class _Vault:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}
        self.reads = 0

    def read(self, target: str) -> bytes | None:
        self.reads += 1
        return self.values.get(target)

    def write(self, target: str, value: bytes) -> None:
        self.values[target] = value

    def delete(self, target: str) -> None:
        self.values.pop(target, None)


@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@contextmanager
def _panel(tmp_path: Path):
    from recoryn.ui.privacy import PrivacyPanel

    backend, transport = _Vault(), _Transport()
    with (
        ConsentStore(tmp_path / "security.sqlite") as policy,
        CostLedger(tmp_path / "security.sqlite") as ledger,
        pytest.MonkeyPatch.context() as prices,
    ):
        panel = PrivacyPanel(
            policy,
            ledger,
            CredentialVault(backend=backend, namespace="BR23-fake"),
            gateway=Gateway(policy, ledger=ledger, transport=transport),
        )
        panel._g06_prices = lambda: fixture_panel_catalog(panel, prices)
        # These older model/transport cases explicitly choose the former library scope.
        panel.select_session("session")
        panel._confirm_library = lambda *args: True
        for control in panel.controls.values():
            control.scope.setCurrentIndex(1)
        try:
            yield panel, backend, transport
        finally:
            close_privacy(panel)
            panel.deleteLater()


def _configure(panel, kind: str = "stt"):
    panel.select_session("session")
    panel._confirm_library = lambda *args: True
    panel.controls[kind].scope.setCurrentIndex(panel.controls[kind].scope.findData("library"))
    control = panel.controls[kind]
    control.provider.setCurrentIndex(control.provider.findData("openai"))
    control.endpoint.setText(URL)
    control.model.setText("model-A")
    if kind == "summary" and hasattr(control, "context_window"):
        control.context_window.setValue(
            8192
        )  # explicit fixture model bound; never a guessed default
    control.total.setValue(1)
    control.per_request.setValue(0.1)
    panel._g06_prices()
    control.key.setText("BR23-FAKE-KEY-A")
    privacy_action(panel, kind, "save")
    privacy_action(panel, kind, "budget")
    privacy_action(panel, kind, "grant")
    return control


@pytest.fixture
def audio(tmp_path: Path) -> Path:
    import wave

    path = tmp_path / "synthetic.wav"
    with wave.open(str(path), "wb") as output:
        output.setparams((1, 2, 8000, 0, "NONE", "synthetic"))
        output.writeframes(b"\0\0" * 80)
    return path


def test_privacy_summary_supplies_explicit_bounded_context(app, tmp_path: Path) -> None:
    with _panel(tmp_path) as (panel, _, transport):
        _configure(panel, "summary")
        transport.response = json.dumps(
            {
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(
                                    {"claims": [{"text": "Synthetic", "segment_ids": ["s"]}]}
                                ),
                            }
                        ],
                    }
                ],
            }
        ).encode()
        config = panel.provider_config("summary")
        assert config.context_window_tokens == 8192
        before = panel.config_key("summary", session_id="session")
        # Caller-facing DTO must be usable without patching a private Qt control.
        result = OpenAISummarizer(
            privacy_gateway(panel, "summary-session", kind="summary"), config
        ).summarize(
            SummaryRequest("revision", (TranscriptSegment("s", 0, 10, "Synthetic source"),)),
            privacy_context(panel, "summary", threading.Event(), session_id="session"),
        )
        assert result.complete and result.claims[0].segment_ids == ("s",)
        assert transport.connections
        panel.controls["summary"].context_window.setValue(16384)
        assert panel.config_key("summary", session_id="session") != before
        settle_privacy(panel)
        assert not panel.consents.allowed(
            "openai",
            URL,
            "transcript",
            scope=ConsentScope.library(),
            request=_fixture_request(panel.consents, "session", _fixture_feature("transcript"), 0),
        )


@pytest.mark.parametrize("change", ["model", "key"])
def test_new_grant_cannot_revive_old_model_or_key_context(
    app, tmp_path: Path, audio: Path, change: str
) -> None:
    with _panel(tmp_path) as (panel, _, transport):
        control = _configure(panel)
        old_config = panel.provider_config("stt")
        old_context = privacy_context(panel, "stt", threading.Event(), session_id="session")
        old_gateway = privacy_gateway(panel, "old-job", kind="stt")
        if change == "model":
            control.model.setText("model-B")
        else:
            privacy_action(panel, "stt", "delete")
            control.key.setText("BR23-FAKE-KEY-B")
            privacy_action(panel, "stt", "save")
        settle_privacy(panel)
        assert not panel.consents.allowed(
            "openai",
            URL,
            "audio",
            scope=ConsentScope.library(),
            request=_fixture_request(panel.consents, "session", _fixture_feature("audio"), 0),
        )
        privacy_action(panel, "stt", "grant")  # a new plan can run; old plan remains revoked
        assert panel.consents.allowed(
            "openai",
            URL,
            "audio",
            scope=ConsentScope.library(),
            request=_fixture_request(panel.consents, "session", _fixture_feature("audio"), 0),
        )
        result = OpenAITranscriber(old_gateway, old_config).transcribe(
            STTRequest(audio), old_context
        )
        if result.complete:
            assert b"model-A" in b"".join(transport.connections[0].writes)
            assert transport.headers[0]["authorization"] == "Bearer BR23-FAKE-KEY-A"
        assert not result.complete
        assert not transport.connections
        fresh = OpenAITranscriber(
            privacy_gateway(panel, "new-job", kind="stt"), panel.provider_config("stt")
        ).transcribe(
            STTRequest(audio),
            privacy_context(panel, "stt", threading.Event(), session_id="session"),
        )
        assert fresh.complete and len(transport.connections) == 1
        assert (b"model-B" if change == "model" else b"model-A") in b"".join(
            transport.connections[0].writes
        )
        assert transport.headers[0]["authorization"] == (
            "Bearer BR23-FAKE-KEY-B" if change == "key" else "Bearer BR23-FAKE-KEY-A"
        )


def test_ui_budget_and_headers_are_immutable_but_revocation_blocks_worker(
    app, tmp_path: Path
) -> None:
    with _panel(tmp_path) as (panel, backend, _):
        assert backend.reads == 0 and not backend.values
        control = _configure(panel)
        context = privacy_context(panel, "stt", threading.Event(), session_id="session")
        assert dict(context.headers) == {} and backend.reads == 0
        assert context.reservation_factory is not None
        with ThreadPoolExecutor(max_workers=1) as workers:
            reservation = workers.submit(
                context.reservation_factory,
                fixture_wire("openai", URL, "audio", b"x" * 80, model="model-A"),
            ).result(timeout=5)
        assert reservation and fixture_panel_balance(panel)["reserved"] == 50_000
        control.per_request.setValue(0.9)  # new contract: changing budget invalidates old plan
        control.key.setText("UNSAVED-DIFFERENT-KEY")
        assert dict(context.headers) == {} and backend.reads == 0
        with ThreadPoolExecutor(max_workers=1) as workers:
            with pytest.raises(SecurityError):
                workers.submit(
                    context.reservation_factory,
                    fixture_wire("openai", URL, "audio", b"x" * 80, model="model-A"),
                ).result(5)


@pytest.mark.parametrize("scope", ["provider", "path", "port", "data", "session"])
def test_mismatched_scope_blocks_before_transport(tmp_path: Path, scope: str) -> None:
    fake = _Transport()
    with ConsentStore(tmp_path / "security.sqlite") as policy:
        policy.grant(
            "openai",
            URL,
            "audio",
            capability="stt",
            scope=_fixture_grant_scope(policy),
            policy_version=2,
        )
        gateway = _fixture_gateway(policy, transport=fake, session_id="session")
        if scope == "session":
            policy.revoke_session("session")
        with pytest.raises(SecurityError):
            gateway.request(
                "anthropic" if scope == "provider" else "openai",
                URL + "/other"
                if scope == "path"
                else URL.replace(".test/", ".test:444/")
                if scope == "port"
                else URL,
                "transcript" if scope == "data" else "audio",
                b"PRIVATE-SYNTHETIC-CANARY",
            )
        assert fake.connections == []


def test_bundle_never_copies_private_project_files_or_registered_secret(tmp_path: Path) -> None:
    canary = "BR23-REGISTERED-SECRET-CANARY"
    register_secret(canary)
    private = tmp_path / "raw-audio.wav"
    private.write_bytes(b"BR23-RAW-CANARY")
    destination = support_bundle(
        tmp_path / "support.zip",
        [{"event": "STT_FAILED", "code": canary, "audio": str(private), "transcript": canary}],
        metadata={"app_version": "0.2.0", "api_key": canary, "path": str(private)},
    )
    with zipfile.ZipFile(destination) as bundle:
        assert set(bundle.namelist()) == {"diagnostics.jsonl", "environment.json"}
        combined = b"".join(bundle.read(name) for name in bundle.namelist())
        assert canary.encode() not in combined and b"BR23-RAW-CANARY" not in combined
        assert private.name.encode() not in combined
        assert json.loads(bundle.read("environment.json")) == {"app_version": "0.2.0"}


def test_default_transport_no_consent_never_reaches_network_guard(tmp_path: Path) -> None:
    # Integration conftest rejects even attempted DNS/socket calls.
    with ConsentStore(tmp_path / "security.sqlite") as policy:
        with pytest.raises(SecurityError, match="CONSENT_REQUIRED"):
            Gateway(policy).request("openai", URL, "audio", b"SYNTHETIC")


@pytest.mark.parametrize("session_revoke", [False, True])
def test_committed_revocation_before_first_write_sends_no_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, session_revoke: bool
) -> None:
    waiting, release = threading.Event(), threading.Event()

    class HandoffGate(Gateway):
        def _write(self, *args, **kwargs):
            waiting.set()
            assert release.wait(5)
            return super()._write(*args, **kwargs)

    fake = _Transport()
    with (
        ConsentStore(tmp_path / "security.sqlite") as policy,
        CostLedger(tmp_path / "security.sqlite") as ledger,
    ):
        policy.grant(
            "openai",
            URL,
            "audio",
            capability="stt",
            scope=_fixture_grant_scope(policy),
            policy_version=2,
        )
        policy.bind_session("session")
        reservation = fixture_reservation(
            ledger,
            monkeypatch,
            fixture_wire("openai", URL, "audio", b"CANARY"),
            80,
            100,
            "first-write",
        )
        gateway = _fixture_gateway(policy, ledger=ledger, transport=fake, factory=HandoffGate)
        assert gateway.session_id == "session"
        with ThreadPoolExecutor(max_workers=1) as workers:
            sent = workers.submit(
                gateway.request, "openai", URL, "audio", b"CANARY", reservation_id=reservation
            )
            try:
                assert waiting.wait(5)
                if session_revoke:
                    policy.revoke_session("session")
                else:
                    policy.revoke(
                        "openai",
                        URL,
                        "audio",
                        capability="stt",
                        scope=ConsentScope.library(),
                        policy_version=2,
                    )
            finally:
                release.set()
            with pytest.raises(SecurityError) as error:
                sent.result(timeout=5)
        assert error.value.outcome_known
        assert len(fake.connections) == 1 and fake.connections[0].writes == []
        assert fake.connections[0].closed


@pytest.mark.parametrize("session_revoke", [False, True])
def test_write_before_revocation_cannot_send_next_chunk_after_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, session_revoke: bool
) -> None:
    first_write, release, committed = (threading.Event() for _ in range(3))

    class Writes(_Connection):
        def write(self, data: bytes, timeout: float) -> None:
            super().write(data, timeout)
            first_write.set()
            assert release.wait(5)

    class Transport(_Transport):
        def open(self, *args, **kwargs):
            connection = Writes()
            self.connections.append(connection)
            return connection

    class SecondHandoffGate(Gateway):
        count = 0

        def _write(self, *args, **kwargs):
            self.count += 1
            if self.count == 2:
                assert committed.wait(5)  # outside the coordinator's write lock
            return super()._write(*args, **kwargs)

    fake = Transport()
    db = tmp_path / "security.sqlite"
    with ConsentStore(db) as policy, CostLedger(db) as ledger:
        policy.grant(
            "openai",
            URL,
            "audio",
            capability="stt",
            scope=_fixture_grant_scope(policy),
            policy_version=2,
        )
        policy.bind_session("session")
        reservation = fixture_reservation(
            ledger,
            monkeypatch,
            fixture_wire("openai", URL, "audio", b"abcdef"),
            80,
            100,
            "request",
        )
        gateway = _fixture_gateway(
            policy, ledger=ledger, transport=fake, chunk_bytes=3, factory=SecondHandoffGate
        )
        assert gateway.session_id == "session"

        def revoke() -> None:
            if session_revoke:
                policy.revoke_session("session")
            else:
                policy.revoke(
                    "openai",
                    URL,
                    "audio",
                    capability="stt",
                    scope=ConsentScope.library(),
                    policy_version=2,
                )
            committed.set()

        with ThreadPoolExecutor(max_workers=2) as workers:
            sent = workers.submit(
                gateway.request, "openai", URL, "audio", b"abcdef", reservation_id=reservation
            )
            try:
                assert first_write.wait(5)
                revoked = workers.submit(revoke)
            finally:
                release.set()
            revoked.result(timeout=5)
            with pytest.raises(SecurityError) as error:
                sent.result(timeout=5)
        assert not error.value.outcome_known
        assert fake.connections[0].writes == [b"abc"] and fake.connections[0].closed
        assert fixture_balance(ledger, "openai")["unknown_exposure"] == 80


def test_unknown_exposure_is_reserved_once_and_settlement_is_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "security.sqlite"
    with CostLedger(db) as ledger:
        reservation = ledger.reserve("openai", "one-request", 80, 100)
        assert ledger.reserve("openai", "one-request", 80, 100) == reservation
        ledger.mark_unknown(reservation)
        with pytest.raises(SecurityError, match="RESERVATION_MAY_BE_SENT"):
            ledger.release(reservation)
    with CostLedger(db) as ledger:
        assert ledger.snapshot("openai")["available"] == 20
        ledger.settle(reservation, 40)
        ledger.settle(reservation, 40)
        assert ledger.snapshot("openai") == {
            "confirmed": 40,
            "reserved": 0,
            "unknown_exposure": 0,
            "available": 60,
            "limit": 100,
        }
        with pytest.raises(SecurityError, match="SETTLEMENT_CONFLICT"):
            ledger.settle(reservation, 30)


def test_concurrent_budget_reservations_cannot_exceed_limit(tmp_path: Path) -> None:
    with CostLedger(tmp_path / "security.sqlite") as ledger:
        barrier = threading.Barrier(2)

        def reserve(index: int):
            barrier.wait(timeout=5)
            try:
                return ledger.reserve("openai", f"r{index}", 60, 100)
            except SecurityError as error:
                return error.code

        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(reserve, range(2)))
        assert results.count("BUDGET_EXCEEDED") == 1
        assert ledger.snapshot("openai")["reserved"] == 60


def test_rolled_back_cost_witness_blocks_before_transport(tmp_path: Path) -> None:
    db = tmp_path / "security.sqlite"
    fake = _Transport()
    with ConsentStore(db) as policy, CostLedger(db) as ledger:
        witness = tmp_path / "security.sqlite.cost-witness"
        stale = witness.read_bytes()
        reservation = ledger.reserve("openai", "r1", 80, 100)
        witness.write_bytes(stale)
        policy.grant(
            "openai",
            URL,
            "audio",
            capability="stt",
            scope=_fixture_grant_scope(policy),
            policy_version=2,
        )
        with pytest.raises(SecurityError, match="LEDGER_ROLLBACK_DETECTED"):
            _fixture_gateway(policy, ledger=ledger, transport=fake).request(
                "openai", URL, "audio", b"CANARY", reservation_id=reservation
            )
        assert fake.connections == []


@pytest.mark.parametrize(
    "headers",
    [
        {"Host": "evil.example.test"},
        {"Content-Length": "0"},
        {"Authorization": "Bearer KEY\r\nInjected: yes"},
        {"Authorization": "one", "authorization": "two"},
        {"Proxy-Authorization": "secret"},
    ],
)
def test_untrusted_headers_are_denied_before_transport(tmp_path: Path, headers) -> None:
    fake = _Transport()
    with ConsentStore(tmp_path / "security.sqlite") as policy:
        policy.grant(
            "openai",
            URL,
            "audio",
            capability="stt",
            scope=_fixture_grant_scope(policy),
            policy_version=2,
        )
        with pytest.raises(SecurityError, match="INVALID_HEADER"):
            _fixture_gateway(policy, transport=fake).request(
                "openai", URL, "audio", b"x", headers=headers
            )
        assert fake.connections == []


@pytest.mark.parametrize("loopback", [False, True])
def test_resolved_addresses_are_all_screened_before_socket_connect(
    monkeypatch: pytest.MonkeyPatch, loopback: bool
) -> None:
    import socket

    from recoryn.security import transport
    from recoryn.security._core import endpoint

    addresses = ["127.0.0.1", "8.8.8.8"] if loopback else ["8.8.8.8", "127.0.0.1"]
    monkeypatch.setattr(
        transport.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443)) for address in addresses
        ],
    )
    calls: list[object] = []

    def socket_forbidden(*args, **kwargs):
        calls.append(args)
        raise AssertionError("mixed DNS answers must fail before socket creation")

    monkeypatch.setattr(transport.socket, "socket", socket_forbidden)
    target = endpoint("http://127.0.0.1/api/chat" if loopback else URL)
    with pytest.raises(SecurityError, match="DNS_TARGET_DENIED"):
        transport._socket(target, 1)
    assert calls == []


def test_direct_tls_uses_exact_host_ignores_proxy_and_never_follows_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from recoryn.security import transport
    from recoryn.security._core import endpoint

    events: list[tuple] = []
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example.test:3128")
    monkeypatch.setenv("ALL_PROXY", "http://proxy.example.test:3128")

    class Socket:
        def settimeout(self, timeout: float) -> None:
            events.append(("timeout", timeout))

        def close(self) -> None:
            events.append(("socket-close",))

    stream = Socket()

    def direct_socket(target, timeout):
        events.append(("connect", target.host, target.port))
        return stream

    class TLS:
        def wrap_socket(self, raw, *, server_hostname):
            assert raw is stream
            events.append(("tls", server_hostname))
            return raw

    class Response:
        status = 307

        def read1(self, limit: int) -> bytes:
            raise AssertionError("redirect bodies must not be returned as provider responses")

    class HTTP:
        def __init__(self, host, port, timeout):
            events.append(("http", host, port))
            self.sock = None
            self.auto_open = 1

        def putrequest(self, method, target, **kwargs):
            assert self.auto_open == 0 and self.sock is stream
            events.append(("request", method, target))

        def putheader(self, name, value):
            events.append(("header", name.lower(), value))

        def endheaders(self):
            events.append(("endheaders",))

        def send(self, data):
            events.append(("body", data))

        def getresponse(self):
            return Response()

        def close(self):
            events.append(("close",))

    monkeypatch.setattr(transport, "_socket", direct_socket)
    monkeypatch.setattr(transport.ssl, "create_default_context", lambda: TLS())
    monkeypatch.setattr(transport.http.client, "HTTPConnection", HTTP)
    connection = transport.DirectTransport().open(
        endpoint(URL), {"authorization": "Bearer FAKE"}, 1, 1
    )
    try:
        connection.write(b"x", 1)
        with pytest.raises(SecurityError, match="REDIRECT_DENIED") as error:
            connection.read(100, 1)
        assert not error.value.outcome_known
    finally:
        connection.close()
    assert [item for item in events if item[0] == "connect"] == [
        ("connect", "api.example.test", 443)
    ]
    assert ("tls", "api.example.test") in events
    assert ("request", "POST", "/v1/audio") in events
    assert not any("proxy" in str(item) for item in events)


def test_regrant_between_reservation_and_permit_cannot_reauthorize_old_request(
    app, tmp_path: Path, audio: Path
) -> None:
    with _panel(tmp_path) as (panel, _, transport):
        _configure(panel)
        config = panel.provider_config("stt")
        context = privacy_context(panel, "stt", threading.Event(), session_id="session")
        gateway = privacy_gateway(panel, "session", kind="stt")
        reserve = context.reservation_factory
        assert reserve is not None

        def reserve_then_regrant(*args):
            reservation = reserve(*args)
            panel.consents.revoke(
                "openai",
                URL,
                "audio",
                capability=_fixture_feature("audio"),
                scope=ConsentScope.library(),
                policy_version=2,
            )
            panel.consents.grant(
                "openai",
                URL,
                "audio",
                capability=_fixture_feature("audio"),
                scope=_fixture_grant_scope(panel.consents),
                policy_version=2,
            )
            return reservation

        result = OpenAITranscriber(gateway, config).transcribe(
            STTRequest(audio), replace(context, reservation_factory=reserve_then_regrant)
        )
        assert not result.complete and result.outcome_known
        assert transport.connections == []
        assert fixture_panel_balance(panel)["unknown_exposure"] == 0


def test_local_ollama_gateway_binding_blocks_old_model_after_regrant(app, tmp_path: Path) -> None:
    with _panel(tmp_path) as (panel, _, transport):
        control = panel.controls["summary"]
        control.provider.setCurrentIndex(control.provider.findData("ollama"))
        target = "http://127.0.0.1:11434/api/chat"
        proof = LocalModelAttestation(target, "local-A", "a" * 64, True, time.monotonic() + 30)
        panel.set_local_attestation(proof)
        control.context_window.setValue(8192)
        privacy_action(panel, "summary", "grant")
        config = panel.provider_config("summary")
        context = privacy_context(panel, "summary", threading.Event(), session_id="session")
        assert context.reservation_factory is None
        gateway = privacy_gateway(panel, "old-local-job", kind="summary")
        panel.set_local_attestation(replace(proof, model="local-B", artifact_sha256="b" * 64))
        privacy_action(panel, "summary", "grant")
        result = OllamaSummarizer(gateway, config).summarize(
            SummaryRequest("revision", (TranscriptSegment("s", 0, 10, "Synthetic"),)), context
        )
        assert not result.complete and not transport.connections


def test_previously_ungranted_context_scope_cannot_widen_existing_gateway(
    app, tmp_path: Path
) -> None:
    with _panel(tmp_path) as (panel, _, transport):
        control = _configure(panel, "summary")
        context = privacy_context(panel, "summary", threading.Event(), session_id="session")
        gateway = privacy_gateway(panel, "session", kind="summary")
        control.data_type.setCurrentIndex(control.data_type.findData("context"))
        privacy_action(panel, "summary", "grant")
        assert panel.consents.allowed(
            "openai",
            URL,
            "context",
            scope=ConsentScope.library(),
            request=_fixture_request(panel.consents, "session", _fixture_feature("context"), 0),
        )
        assert context.reservation_factory is not None
        with pytest.raises(SecurityError):
            context.reservation_factory(
                fixture_wire("openai", URL, "context", b"ctx", operation="summary", model="model-A")
            )
        with pytest.raises(SecurityError):
            gateway.request("openai", URL, "context", b"ctx")
        assert not transport.connections


def test_unverified_summary_context_stays_blocked_with_no_dispatch(app, tmp_path: Path) -> None:
    with _panel(tmp_path) as (panel, _, transport):
        control = panel.controls["summary"]
        assert control.context_window.value() == 0
        _configure(panel, "summary")
        control.context_window.setValue(0)
        privacy_action(panel, "summary", "grant")
        config = panel.provider_config("summary")
        assert config.context_window_tokens is None
        result = OpenAISummarizer(
            privacy_gateway(panel, "unknown", kind="summary"), config
        ).summarize(
            SummaryRequest("revision", (TranscriptSegment("s", 0, 10, "Synthetic"),)),
            privacy_context(panel, "summary", threading.Event(), session_id="session"),
        )
        assert result.error_code == "CONTEXT_LIMIT_UNKNOWN" and not result.complete
        assert not transport.connections


@pytest.mark.parametrize("boundary", ["open", "first_write", "second_write", "result"])
@pytest.mark.parametrize("failure_side", ["enter", "exit"])
def test_dispatch_guard_faults_preserve_exact_handoff_and_cost(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
    failure_side: str,
) -> None:
    """Boundary selection follows observed I/O, independent of guard call count."""
    events: list[str] = []
    writes: list[bytes] = []
    closed = False

    class Connection:
        def write(self, data, timeout):
            writes.append(data)
            events.append("write")

        def read(self, limit, timeout):
            events.append("eof")
            return b""

        def close(self):
            nonlocal closed
            closed = True

    class Transport:
        def open(self, *args):
            events.append("open")
            return Connection()

    def at_boundary() -> bool:
        return {
            "open": events == [],
            "first_write": events == ["open"],
            "second_write": events == ["open", "write"],
            "result": events[-1:] == ["eof"],
        }[boundary]

    @contextmanager
    def guard(permit):
        selected = at_boundary()
        if selected and failure_side == "enter":
            raise RuntimeError("PRIVATE-GUARD-CANARY")
        yield
        if selected and failure_side == "exit":
            raise RuntimeError("PRIVATE-GUARD-CANARY")

    with ConsentStore(tmp_path / "policy.db") as policy, CostLedger(tmp_path / "cost.db") as ledger:
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
            80,
            100,
            "independent-guard",
        )
        gateway = _fixture_gateway(
            policy,
            ledger=ledger,
            transport=Transport(),
            chunk_bytes=2,
            dispatch_guard=guard,
            session_id="bound-session",
        )
        with pytest.raises(SecurityError, match="LOCAL_EXECUTION_UNVERIFIED") as failure:
            gateway.request("p", URL, "audio", b"abcd", reservation_id=reservation)
        assert "CANARY" not in str(failure.value)
        delivered = {
            ("open", "enter"): [],
            ("open", "exit"): [],
            ("first_write", "enter"): [],
            ("first_write", "exit"): [b"ab"],
            ("second_write", "enter"): [b"ab"],
            ("second_write", "exit"): [b"ab", b"cd"],
            ("result", "enter"): [b"ab", b"cd"],
            ("result", "exit"): [b"ab", b"cd"],
        }[(boundary, failure_side)]
        assert writes == delivered
        assert failure.value.outcome_known is (not delivered)
        state = fixture_balance(ledger)
        assert state["unknown_exposure"] == (80 if delivered else 0)
        assert state["reserved"] == (0 if delivered else 80)
        assert closed is not (boundary == "open" and failure_side == "enter")


def test_guard_cannot_suppress_partial_write_exception(tmp_path: Path) -> None:
    class Suppressor:
        def __enter__(self):
            return None

        def __exit__(self, *args):
            return True

    transport = _Transport()

    def fail_write(data, timeout):
        transport.connections[0].writes.append(data[:1])
        raise OSError("PARTIAL-SECRET-CANARY")

    original = transport.open

    def opened(*args):
        connection = original(*args)
        connection.write = fail_write
        return connection

    transport.open = opened
    with ConsentStore(tmp_path / "policy.db") as policy:
        policy.grant(
            "p",
            URL,
            "audio",
            capability="stt",
            scope=_fixture_grant_scope(policy),
            policy_version=2,
        )
        gateway = _fixture_gateway(
            policy, transport=transport, dispatch_guard=lambda permit: Suppressor()
        )
        with pytest.raises(SecurityError) as failure:
            gateway.request("p", URL, "audio", b"ab")
        assert not failure.value.outcome_known and "CANARY" not in str(failure.value)
        assert transport.connections[0].writes == [b"a"]
        assert transport.connections[0].closed


def test_frozen_privacy_proof_replacement_during_open_cannot_authorize_first_body(
    app,
    tmp_path: Path,
) -> None:
    with _panel(tmp_path) as (panel, backend, transport):
        control = panel.controls["summary"]
        control.provider.setCurrentIndex(control.provider.findData("ollama"))
        local = "http://127.0.0.1:11434/api/chat"
        owner_live = True
        seen: list[str] = []

        @contextmanager
        def old_owner():
            seen.append("old")
            if not owner_live:
                raise ProviderError("LOCAL_EXECUTION_UNVERIFIED")
            yield

        @contextmanager
        def replacement_owner():
            seen.append("replacement")
            yield

        proof = LocalModelAttestation(
            local, "fixed-model", "a" * 64, True, time.monotonic() + 60, lifetime_guard=old_owner
        )
        panel.set_local_attestation(proof)
        control.context_window.setValue(8192)
        privacy_action(panel, "summary", "grant")
        frozen = privacy_gateway(panel, "guard-session", kind="summary")
        original = transport.open

        def opened(*args):
            nonlocal owner_live
            connection = original(*args)
            owner_live = False
            # Simulate a new proof after the old plan has entered transport open.
            # No grant is changed, so the frozen owner guard is the sole barrier.
            panel._attestation = replace(proof, lifetime_guard=replacement_owner)
            return connection

        transport.open = opened
        with pytest.raises(SecurityError, match="LOCAL_EXECUTION_UNVERIFIED") as failure:
            frozen.request("ollama", local, "transcript", b"synthetic")
        assert failure.value.outcome_known and seen == ["old", "old"]
        assert transport.connections[0].writes == [] and transport.connections[0].closed
        assert backend.reads == 0


def test_attestation_ttl_is_checked_inside_acquired_owner_guard(monkeypatch) -> None:
    clock = [0.0]
    events: list[str] = []

    @contextmanager
    def owner():
        events.append("owner-enter")
        clock[0] = 11.0  # The proof expires while acquiring its managed owner lock.
        try:
            yield
        finally:
            events.append("owner-exit")

    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    proof = LocalModelAttestation(
        "http://127.0.0.1:1/api/chat", "fixed", "a" * 64, True, 10.0, lifetime_guard=owner
    )
    with pytest.raises(ProviderError, match="LOCAL_EXECUTION_UNVERIFIED"):
        with proof.execution_guard():
            pytest.fail("expired proof admitted a consumer")
    assert events == ["owner-enter", "owner-exit"]


def test_managed_attestation_does_not_rewrite_consumer_exception_or_compare_callback() -> None:
    events: list[str] = []

    @contextmanager
    def private_callback():
        events.append("enter")
        try:
            yield
        finally:
            events.append("exit")

    proof = LocalModelAttestation(
        "http://127.0.0.1:1/api/chat",
        "fixed",
        "a" * 64,
        True,
        time.monotonic() + 60,
        lifetime_guard=private_callback,
    )
    failure = OSError("synthetic consumer fault")
    with pytest.raises(OSError) as caught:
        with proof.execution_guard():
            assert events == ["enter"]
            raise failure
    assert caught.value is failure and events == ["enter", "exit"]
    assert proof == replace(proof, lifetime_guard=None)
    assert "lifetime_guard" not in repr(proof) and "private_callback" not in repr(proof)


def test_static_attestation_compatibility_keeps_ttl_and_exception_semantics() -> None:
    proof = LocalModelAttestation(
        "http://127.0.0.1:1/api/chat", "fixed", "a" * 64, True, time.monotonic() + 60
    )
    with proof.execution_guard():
        pass
    with pytest.raises(ProviderError, match="LOCAL_EXECUTION_UNVERIFIED"):
        with replace(proof, cloud_disabled=False).execution_guard():
            pytest.fail("unverified execution admitted")


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
        if "auth_binding" not in kwargs:
            from tests.unit.test_secret_lifetime import fake_auth_binding

            for binding in bindings:
                if binding.provider_id in {"openai", "anthropic", "gemini"}:
                    kwargs["auth_binding"] = fake_auth_binding(
                        policy, binding.provider_id, binding.endpoint, request.capability
                    )
                    break
        root = factory(policy, **kwargs)
    return root.for_session(
        session_id, generation, capability="stt", scope=ConsentScope.library(), policy_version=2
    )


def _fixture_feature(data_type: str) -> str:
    return "stt" if data_type == "audio" else "summary"
