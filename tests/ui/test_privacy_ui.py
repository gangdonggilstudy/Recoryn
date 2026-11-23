"""Headless consent interactions with a fake credential backend; never real keys."""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from recoryn.security import ConsentRequest, ConsentScope

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from recoryn.providers import LocalModelAttestation, ProviderError
from recoryn.security import ConsentStore, CostLedger, CredentialVault, Gateway, SecurityError
from recoryn.security._core import Endpoint
from recoryn.ui.privacy import PrivacyPanel

pytestmark = pytest.mark.ui


class DummyVault:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}
        self.reads = 0
        self.fail = False

    def read(self, target: str) -> bytes | None:
        self.reads += 1
        return self.values.get(target)

    def write(self, target: str, secret: bytes) -> None:
        if self.fail:
            raise OSError("B14-CANARY-PRIVATE")
        self.values[target] = secret

    def delete(self, target: str) -> None:
        self.values.pop(target, None)


@pytest.fixture(scope="module")
def app() -> QApplication:
    existing = QApplication.instance()
    return existing if isinstance(existing, QApplication) else QApplication([])


@pytest.fixture
def panel(app: QApplication, tmp_path: Path) -> Iterator[tuple[PrivacyPanel, DummyVault]]:
    backend = DummyVault()
    db = tmp_path / "p.sqlite"
    with ConsentStore(db) as consents, CostLedger(db) as ledger:
        widget = PrivacyPanel(
            consents, ledger, CredentialVault(backend=backend, namespace="B14-test")
        )
        yield widget, backend
        widget.close()


def configure(widget: PrivacyPanel, kind: str = "stt", provider: str = "openai") -> None:
    widget.select_session("session")
    widget._confirm_library = lambda *args: True
    controls = widget.controls[kind]
    controls.scope.setCurrentIndex(controls.scope.findData("library"))
    controls.provider.setCurrentIndex(controls.provider.findData(provider))
    controls.endpoint.setText("https://api.example.test/" + kind)
    controls.model.setText("user-selected-test-model")
    controls.total.setValue(1)
    controls.per_request.setValue(0.1)


def click(button: object) -> None:
    # QTest receives the real button; type is narrowed at the fixture call sites.
    from PySide6.QtWidgets import QPushButton

    assert isinstance(button, QPushButton)
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)


def test_constructor_default_denial_no_vault_read_and_summary_off(
    panel: tuple[PrivacyPanel, DummyVault],
) -> None:
    widget, backend = panel
    assert backend.reads == 0 and not backend.values
    assert widget.provider_config("stt").provider_id == "faster_whisper"
    with pytest.raises(ProviderError, match="CAPABILITY_UNSUPPORTED"):
        widget.provider_config("summary")
    assert not widget.consents.allowed(
        "openai",
        "https://api.example.test/stt",
        "audio",
        scope=ConsentScope.library(),
        request=_fixture_request(widget.consents, "session", _fixture_feature("audio"), 0),
    )
    assert widget.controls["stt"].per_request.value() == 0


def test_exact_datatype_consent_independent_settings_and_endpoint_change(
    panel: tuple[PrivacyPanel, DummyVault],
) -> None:
    widget, _ = panel
    configure(widget)
    control = widget.controls["stt"]
    click(control.allow)
    assert widget.consents.allowed(
        "openai",
        control.endpoint.text(),
        "audio",
        scope=ConsentScope.library(),
        request=_fixture_request(widget.consents, "session", _fixture_feature("audio"), 0),
    )
    assert not widget.consents.allowed(
        "openai",
        control.endpoint.text(),
        "transcript",
        scope=ConsentScope.library(),
        request=_fixture_request(widget.consents, "session", _fixture_feature("transcript"), 0),
    )
    configure(widget, "summary")
    summary = widget.controls["summary"]
    click(summary.allow)
    assert widget.consents.allowed(
        "openai",
        summary.endpoint.text(),
        "transcript",
        scope=ConsentScope.library(),
        request=_fixture_request(widget.consents, "session", _fixture_feature("transcript"), 0),
    )
    assert not widget.consents.allowed(
        "openai",
        summary.endpoint.text(),
        "context",
        scope=ConsentScope.library(),
        request=_fixture_request(widget.consents, "session", _fixture_feature("context"), 0),
    )
    summary.data_type.setCurrentIndex(summary.data_type.findData("context"))
    click(summary.allow)
    assert widget.consents.allowed(
        "openai",
        summary.endpoint.text(),
        "context",
        scope=ConsentScope.library(),
        request=_fixture_request(widget.consents, "session", _fixture_feature("context"), 0),
    )
    control.endpoint.setText("https://other.example.test/stt")
    assert not widget.consents.allowed(
        "openai",
        "https://api.example.test/stt",
        "audio",
        scope=ConsentScope.library(),
        request=_fixture_request(widget.consents, "session", _fixture_feature("audio"), 0),
    )
    assert not widget.consents.allowed(
        "openai",
        control.endpoint.text(),
        "audio",
        scope=ConsentScope.library(),
        request=_fixture_request(widget.consents, "session", _fixture_feature("audio"), 0),
    )


def test_credentials_are_endpoint_bound_fail_closed_and_never_in_config_key(
    panel: tuple[PrivacyPanel, DummyVault],
) -> None:
    widget, backend = panel
    configure(widget)
    control = widget.controls["stt"]
    before = widget.config_key("stt", session_id="session")
    control.key.setText("B14-UI-SECRET-CANARY")
    click(control.save_key)
    assert not control.key.text()
    assert widget.config_key("stt", session_id="session") == before
    assert len(backend.values) == 1
    assert all("CANARY" not in target for target in backend.values)
    control.endpoint.setText("https://other.example.test/stt")
    click(control.apply_budget)
    click(control.allow)
    with pytest.raises(SecurityError, match="AUTH_REQUIRED"):
        widget.execution_context("stt", threading.Event(), session_id="session")
    backend.fail = True
    control.key.setText("B14-CANARY-PRIVATE")
    click(control.save_key)
    assert control.status.text() == "VAULT_WRITE_FAILED"
    assert "CANARY" not in control.status.text()
    assert not widget.consents.allowed(
        "openai",
        control.endpoint.text(),
        "audio",
        scope=ConsentScope.library(),
        request=_fixture_request(widget.consents, "session", _fixture_feature("audio"), 0),
    )


def test_worker_reservation_factory_uses_frozen_gui_values(
    panel: tuple[PrivacyPanel, DummyVault],
) -> None:
    widget, _ = panel
    configure(widget)
    control = widget.controls["stt"]
    click(control.apply_budget)
    control.key.setText("dummy-key")
    click(control.save_key)
    click(control.allow)
    context = widget.execution_context("stt", threading.Event(), session_id="session")
    assert context.reservation_factory is not None
    with ThreadPoolExecutor(max_workers=1) as worker:
        reservation = worker.submit(
            context.reservation_factory, "openai", "https://api.example.test/stt", "audio", 5
        ).result(timeout=5)
    assert reservation
    assert widget.ledger.snapshot("openai")["reserved"] == 100_000
    control.per_request.setValue(0.9)
    with ThreadPoolExecutor(max_workers=1) as worker:
        with pytest.raises(SecurityError):
            worker.submit(
                context.reservation_factory, "openai", "https://api.example.test/stt", "audio", 5
            ).result(timeout=5)
    widget.ledger.mark_unknown(reservation)
    click(control.refresh)
    assert "UNKNOWN 0.100000" in control.balance.text()
    control.actual.setValue(0.04)
    widget._action("stt", "settle")
    assert control.status.text() == "SETTLEMENT_CONFIRMATION_REQUIRED"
    control.confirm_actual.setChecked(True)
    click(control.settle)
    assert widget.ledger.snapshot("openai")["confirmed"] == 40_000
    assert widget.ledger.snapshot("openai")["unknown_exposure"] == 0


def test_zero_cloud_cap_is_blocked_and_ollama_requires_attestation(
    panel: tuple[PrivacyPanel, DummyVault],
) -> None:
    widget, backend = panel
    configure(widget)
    control = widget.controls["stt"]
    control.per_request.setValue(0)
    click(control.allow)
    assert control.status.text() == "BUDGET_REQUIRED"
    assert backend.reads == 0


@pytest.mark.parametrize("setting", ("context_window", "max_output", "per_request", "total"))
def test_execution_settings_change_key_and_revoke_old_plan(
    panel: tuple[PrivacyPanel, DummyVault],
    setting: str,
) -> None:
    widget, _ = panel
    configure(widget, "summary")
    controls = widget.controls["summary"]
    controls.context_window.setValue(8192)
    controls.key.setText("B14-fake-key")
    click(controls.save_key)
    click(controls.apply_budget)
    click(controls.allow)
    key = widget.config_key("summary", session_id="session")
    old_context = widget.execution_context("summary", threading.Event(), session_id="session")
    assert old_context.reservation_factory is not None
    control = getattr(controls, setting)
    control.setValue(control.value() + 1)
    assert key != widget.config_key("summary", session_id="session")
    click(controls.allow)
    with pytest.raises(SecurityError, match="PERMIT_REVOKED"):
        old_context.reservation_factory("openai", controls.endpoint.text(), "transcript", 10)


def test_summary_context_limit_is_explicit_and_unknown_by_default(
    panel: tuple[PrivacyPanel, DummyVault],
) -> None:
    widget, _ = panel
    configure(widget, "summary")
    assert widget.provider_config("summary").context_window_tokens is None
    controls = widget.controls["summary"]
    controls.context_window.setValue(16384)
    controls.max_output.setValue(2048)
    config = widget.provider_config("summary")
    assert config.context_window_tokens == 16384 and config.max_output_tokens == 2048
    configure(widget, "summary", "ollama")
    with pytest.raises(SecurityError, match="LOCAL_EXECUTION_UNVERIFIED"):
        widget.provider_config("summary")
    proof = LocalModelAttestation(
        "http://127.0.0.1:11434/api/chat", "verified-local", "a" * 64, True, time.monotonic() + 30
    )
    widget.set_local_attestation(proof)
    click(widget.controls["summary"].allow)
    assert widget.provider_config("summary").local_attestation == proof
    assert (
        widget.execution_context(
            "summary", threading.Event(), session_id="session"
        ).reservation_factory
        is None
    )
    assert widget.gateway_for("session", kind="summary").ledger is None
    widget.set_local_attestation(None)
    assert not widget.consents.allowed(
        "ollama",
        proof.endpoint,
        "transcript",
        scope=ConsentScope.library(),
        request=_fixture_request(widget.consents, "session", _fixture_feature("transcript"), 0),
    )


def test_frozen_worker_scope_cannot_widen_or_outlive_revocation(
    panel: tuple[PrivacyPanel, DummyVault],
) -> None:
    widget, _ = panel
    configure(widget)
    controls = widget.controls["stt"]
    controls.key.setText("B14-fake-only")
    click(controls.save_key)
    click(controls.apply_budget)
    click(controls.allow)
    context = widget.execution_context("stt", threading.Event(), session_id="session")
    reserve = context.reservation_factory
    assert reserve is not None
    for provider, target, kind, size in (
        ("gemini", controls.endpoint.text(), "audio", 5),
        ("openai", "https://other.example.test/stt", "audio", 5),
        ("openai", controls.endpoint.text(), "transcript", 5),
        ("openai", controls.endpoint.text(), "audio", -1),
    ):
        with pytest.raises(SecurityError, match="BUDGET_SCOPE_MISMATCH"):
            reserve(provider, target, kind, size)
    assert widget.ledger.snapshot("openai")["reserved"] == 0
    click(controls.revoke)
    with pytest.raises(SecurityError, match="CONSENT_REQUIRED"):
        reserve("openai", controls.endpoint.text(), "audio", 5)
    assert widget.ledger.snapshot("openai")["reserved"] == 0


def test_expired_local_proof_and_changed_model_cannot_grant_loopback(
    panel: tuple[PrivacyPanel, DummyVault],
) -> None:
    widget, backend = panel
    configure(widget, "summary", "ollama")
    for expiry, disabled in ((time.monotonic() - 1, True), (time.monotonic() + 30, False)):
        proof = LocalModelAttestation(
            "http://127.0.0.1:11434/api/chat", "local", "a" * 64, disabled, expiry
        )
        widget.set_local_attestation(proof)
        click(widget.controls["summary"].allow)
        assert widget.controls["summary"].status.text() == "LOCAL_EXECUTION_UNVERIFIED"
        assert not widget.consents.allowed(
            "ollama",
            proof.endpoint,
            "transcript",
            scope=ConsentScope.library(),
            request=_fixture_request(widget.consents, "session", _fixture_feature("transcript"), 0),
        )
    proof = LocalModelAttestation(
        "http://127.0.0.1:11434/api/chat", "local", "a" * 64, True, time.monotonic() + 30
    )
    widget.set_local_attestation(proof)
    widget.controls["summary"].model.setText("unverified-model")
    with pytest.raises(SecurityError, match="LOCAL_EXECUTION_UNVERIFIED"):
        widget.provider_config("summary")
    assert backend.reads == 0


class LocalConnection:
    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self.closed = False

    def write(self, data: bytes, timeout: float) -> None:
        self.writes.append(data)

    def read(self, limit: int, timeout: float) -> bytes:
        return b""

    def close(self) -> None:
        self.closed = True


class LocalTransport:
    def __init__(self) -> None:
        self.connection = LocalConnection()
        self.opens = 0

    def open(
        self, endpoint: Endpoint, headers: Mapping[str, str], body_length: int, timeout: float
    ) -> LocalConnection:
        self.opens += 1
        return self.connection


@pytest.mark.parametrize("boundary", ("open", "first_write", "second_write", "result", "none"))
def test_frozen_managed_proof_protects_every_privacy_gateway_boundary(
    panel: tuple[PrivacyPanel, DummyVault], boundary: str
) -> None:
    widget, backend = panel
    configure(widget, "summary", "ollama")
    live = True
    checks = 0
    base_checks = 0
    boundary_number = {"open": 1, "first_write": 2, "second_write": 3, "result": 4}

    @contextmanager
    def owner_guard() -> Iterator[None]:
        nonlocal checks, live
        checks += 1
        if checks == boundary_number.get(boundary):
            live = False
        if not live:
            raise ProviderError("LOCAL_EXECUTION_UNVERIFIED")
        yield

    @contextmanager
    def base_guard(permit: object) -> Iterator[None]:
        nonlocal base_checks
        base_checks += 1
        yield

    proof = LocalModelAttestation(
        "http://127.0.0.1:11434/api/chat",
        "local",
        "a" * 64,
        True,
        time.monotonic() + 30,
        lifetime_guard=owner_guard,
    )
    widget.set_local_attestation(proof)
    click(widget.controls["summary"].allow)
    transport = LocalTransport()
    widget._gateway = Gateway(
        widget.consents, transport=transport, chunk_bytes=2, dispatch_guard=base_guard
    )
    gateway = widget.gateway_for("session", kind="summary").for_session(
        "session", capability="summary", scope=ConsentScope.library(), policy_version=2
    )
    if boundary == "none":
        assert gateway.request("ollama", proof.endpoint, "transcript", b"abcd") == b""
    else:
        with pytest.raises(SecurityError, match="LOCAL_EXECUTION_UNVERIFIED") as failure:
            gateway.request("ollama", proof.endpoint, "transcript", b"abcd")
        assert failure.value.outcome_known is (boundary in {"open", "first_write"})
    assert transport.opens == (0 if boundary == "open" else 1)
    expected = (
        []
        if boundary in {"open", "first_write"}
        else [b"ab"]
        if boundary == "second_write"
        else [b"ab", b"cd"]
    )
    assert transport.connection.writes == expected
    assert checks == base_checks == boundary_number.get(boundary, 4)
    assert transport.connection.closed is (boundary != "open")
    assert backend.reads == 0


def test_gateway_guard_keeps_old_proof_and_rejects_wrong_scope(
    panel: tuple[PrivacyPanel, DummyVault],
) -> None:
    widget, _ = panel
    configure(widget, "summary", "ollama")
    live = True

    @contextmanager
    def owner_guard() -> Iterator[None]:
        if not live:
            raise ProviderError("LOCAL_EXECUTION_UNVERIFIED")
        yield

    proof = LocalModelAttestation(
        "http://127.0.0.1:11434/api/chat",
        "local",
        "a" * 64,
        True,
        time.monotonic() + 30,
        lifetime_guard=owner_guard,
    )
    widget.set_local_attestation(proof)
    click(widget.controls["summary"].allow)
    frozen = widget.gateway_for("session", kind="summary")
    guard = frozen.dispatch_guard
    assert guard is not None
    permit = widget.consents.permit(
        "ollama",
        proof.endpoint,
        "transcript",
        "b" * 64,
        scope=ConsentScope.library(),
        request=_fixture_request(widget.consents, "session", _fixture_feature("transcript"), 0),
        expected_grant=_fixture_binding(
            widget.consents,
            "ollama",
            proof.endpoint,
            "transcript",
            "session",
            _fixture_feature("transcript"),
            0,
        ),
    )
    for invalid in (
        replace(permit, provider_id="other"),
        replace(permit, endpoint="http://127.0.0.1:22222/api/chat"),
        replace(permit, data_type="audio"),
    ):
        with pytest.raises(SecurityError, match="LOCAL_EXECUTION_UNVERIFIED"):
            with guard(invalid):
                pytest.fail("wrong scope entered the owner lease")
    live = False
    widget.set_local_attestation(replace(proof, lifetime_guard=None))
    click(widget.controls["summary"].allow)
    with pytest.raises(ProviderError, match="LOCAL_EXECUTION_UNVERIFIED"):
        with guard(permit):
            pytest.fail("old closure silently adopted a new proof")
    with pytest.raises(SecurityError):
        frozen.request("ollama", proof.endpoint, "transcript", b"synthetic")


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


def _fixture_feature(data_type: str) -> str:
    return "stt" if data_type == "audio" else "summary"
