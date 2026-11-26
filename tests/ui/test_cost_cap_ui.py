"""G06 cost mode confirmation, frozen GUI plans and honest quote displays."""

from __future__ import annotations

import itertools
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import QApplication, QMessageBox

from recoryn.security import ConsentStore, CostLedger, CostRequest, CredentialVault, SecurityError
from recoryn.ui.privacy import PrivacyPanel
from tests.ui.test_secret_lifetime_ui import (
    close_privacy,
    prepare_privacy,
    privacy_action,
    privacy_click,
    settle_privacy,
)
from tests.unit.test_cost_cap import FIXTURE_END, Clock, flat_price, install_catalog, price

pytestmark = pytest.mark.ui
URL = "https://ui-cost.invalid/v1"
UI = list(
    itertools.product(
        ("strict", "general"),
        ("valid", "unknown", "expired"),
        (12, 13),
        (False, True),
        ("stt", "summary"),
    )
)


def test_ui_case_space_manifest() -> None:
    assert len(UI) == len(set(UI)) == 2 * 3 * 2 * 2 * 2 == 48


class Vault:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}

    def read(self, key: str) -> bytes | None:
        return self.values.get(key)

    def write(self, key: str, value: bytes) -> None:
        self.values[key] = value

    def delete(self, key: str) -> None:
        self.values.pop(key, None)


def fixture_panel_catalog(panel: PrivacyPanel, monkeypatch: pytest.MonkeyPatch) -> None:
    """Known flat toy charges, separate from consent/GUI regression oracles."""
    from recoryn.security.cost import wire_api_version

    entries = []
    for kind, control in panel.controls.items():
        provider = str(control.provider.currentData())
        if provider not in {"openai", "anthropic", "gemini"} or not control.model.text():
            continue
        amount = max(1, min(int(round(control.per_request.value() * 1_000_000)) // 2, 60000))
        models = {
            control.model.text(),
            "model-A",
            "model-B",
            "fake-model",
            "other-model",
            "new-model",
            "changed-model",
            "replacement",
            "user-selected-test-model",
        }
        headers = {"anthropic-version": "2023-06-01"} if provider == "anthropic" else None
        for model in sorted(models):
            entries.append(
                flat_price(
                    amount,
                    provider_id=provider,
                    endpoint=control.endpoint.text(),
                    model_revision=model,
                    api_version=wire_api_version(provider, control.endpoint.text(), headers),
                    operation=kind,
                    valid_until_utc=FIXTURE_END,
                )
            )
    install_catalog(monkeypatch, *entries)


def fixture_panel_balance(panel: PrivacyPanel, kind: str = "stt") -> dict[str, int]:
    control = panel.controls[kind]
    start, end = panel._period(kind)
    return panel.ledger.account_snapshot(
        str(control.provider.currentData()), control.currency.text(), start, end
    )


def configure(panel: PrivacyPanel, kind: str, cap: int) -> Any:
    panel.select_session("s")
    control = panel.controls[kind]
    control.provider.setCurrentIndex(control.provider.findData("openai"))
    control.endpoint.setText(URL)
    control.model.setText("model")
    control.period_start.setText(datetime.fromtimestamp(0, UTC).isoformat())
    control.period_end.setText(datetime.fromtimestamp(2000, UTC).isoformat())
    control.context_window.setValue(10000)
    control.max_output.setValue(32)
    control.total.setValue(0.000100)
    control.per_request.setValue(cap / 1_000_000)
    return control


@pytest.mark.parametrize("row", UI, ids=[f"G06-UI-{i:03}" for i in range(48)])
def test_cost_mode_quote_and_frozen_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, row: Any
) -> None:
    mode, status, cap, changed, kind = row
    app = QApplication.instance() or QApplication([])
    entry = price(
        provider_id="openai",
        endpoint=URL,
        operation=kind,
        wire_protocol="opaque-fixture-v1",
        input_numerator=0,
        output_numerator=0,
        input_overhead=0,
        fixed_fee=13,
    )
    if status == "unknown":
        entry = replace(entry, price_as_of_utc=None, valid_from_utc=None, valid_until_utc=None)
    elif status == "expired":
        entry = replace(entry, valid_until_utc=1000)
    install_catalog(monkeypatch, entry)
    clock = Clock()
    db = tmp_path / "privacy.sqlite"
    with (
        ConsentStore(db) as consents,
        CostLedger(db, clock=clock.now, monotonic=clock.monotonic) as ledger,
    ):
        panel = PrivacyPanel(
            consents, ledger, CredentialVault(backend=Vault(), namespace="g06-fixture")
        )
        try:
            control = configure(panel, kind, cap)
            panel._confirm_general = lambda selected: True
            if mode == "general":
                control.cost_mode.setCurrentIndex(1)
            privacy_action(panel, kind, "budget")
            control.key.setText("G06-FAKE-SECRET")
            privacy_action(panel, kind, "save")
            privacy_action(panel, kind, "grant")
            if kind == "summary":
                control.data_type.setCurrentIndex(control.data_type.findData("context"))
                privacy_action(panel, kind, "grant")
            execution = prepare_privacy(panel, kind, "s", threading.Event())
            factory = execution.context.reservation_factory
            assert factory is not None
            original_key = execution.config_key
            if changed:
                # Inject changed GUI memory without revoking the grant. This
                # isolates the worker's immutable policy from the separate
                # normal widget-change/revocation contract tested below.
                with QSignalBlocker(control.per_request), QSignalBlocker(control.total):
                    control.per_request.setValue(0.000099)
                    control.total.setValue(0.000999)
                assert panel.config_key(kind, session_id="s") == original_key
            request = CostRequest(
                "openai",
                URL,
                "model",
                "v1",
                kind,
                "audio" if kind == "stt" else "transcript",
                b"synthetic-packet",
            )
            accepted = status == "valid" and cap == 13 or status != "valid" and mode == "general"
            with ThreadPoolExecutor(max_workers=1) as worker:
                future = worker.submit(factory, request)
                if accepted:
                    reservation = future.result(5)
                    assert isinstance(reservation, str)
                else:
                    expected_code = (
                        "COST_CAP_EXCEEDED"
                        if status == "valid"
                        else "COST_PRICE_UNKNOWN"
                        if status == "unknown"
                        else "COST_PRICE_EXPIRED"
                    )
                    with pytest.raises(SecurityError, match="^" + expected_code + "$"):
                        future.result(5)
            app.processEvents()
            accounts = ledger.account_snapshot("openai", "USD", 0, 2000)
            expected_amount = (13 if status == "valid" else cap) if accepted else 0
            assert accounts["reserved"] == expected_amount
            display = control.quote_info.text()
            if accepted:
                assert ("VERIFIED" if status == "valid" else "USER_CAP") in display
                assert "통화 USD" in display and f"사용자 cap C 0.0000{cap}" in display
                assert ("가격 기준·만료 미상" in display) is (status != "valid")
            else:
                assert "요청 차단" in display
        finally:
            close_privacy(panel)


def test_general_mode_requires_explicit_confirmation_and_does_not_change_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = QApplication.instance() or QApplication([])
    with (
        ConsentStore(tmp_path / "p.sqlite") as consent,
        CostLedger(tmp_path / "p.sqlite") as ledger,
    ):
        panel = PrivacyPanel(
            consent, ledger, CredentialVault(backend=Vault(), namespace="g06-confirm")
        )
        seen = []

        def question(*args: Any) -> Any:
            seen.append(args)
            return QMessageBox.StandardButton.No

        try:
            monkeypatch.setattr(QMessageBox, "question", question)
            control = panel.controls["stt"]
            assert control.cost_mode.currentData() == "strict"
            control.cost_mode.setCurrentIndex(1)
            app.processEvents()
            assert seen and seen[0][-1] == QMessageBox.StandardButton.No
            assert "USER_CAP" in seen[0][2]
            assert "중복 청구 위험" in seen[0][2]
            assert "전송 동의를 대신하지" in seen[0][2]
            assert control.cost_mode.currentData() == "strict" and not control.general_acknowledged
        finally:
            close_privacy(panel)


def test_clock_recovery_confirmation_works_without_a_remote_provider_selected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = QApplication.instance() or QApplication([])
    clock, db = Clock(2000), tmp_path / "clock.sqlite"
    with CostLedger(db, clock=clock.now):
        pass
    clock.utc = 1000
    with ConsentStore(db) as consent, CostLedger(db, clock=clock.now) as ledger:
        panel = PrivacyPanel(consent, ledger, CredentialVault(backend=Vault()))
        try:
            control = panel.controls["stt"]
            settle_privacy(panel)
            assert control.provider.currentData() == "faster_whisper"
            assert "시계 확인 필요" in control.balance.text() and control.reset_clock.isEnabled()
            seen = []

            def refuse(*args: Any) -> Any:
                seen.append(args)
                return QMessageBox.StandardButton.No

            monkeypatch.setattr(QMessageBox, "question", refuse)
            privacy_click(control.reset_clock)
            assert seen[0][-1] == QMessageBox.StandardButton.No
            assert ledger.availability() == "COST_CLOCK_INVALID"
            monkeypatch.setattr(
                QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes
            )
            privacy_click(control.reset_clock)
            app.processEvents()
            assert ledger.availability() is None and not control.reset_clock.isEnabled()
            assert "재설정 완료" in control.balance.text()
            audits = ledger._db.execute(
                "SELECT clock_reset_audit FROM security_cost_meta_v2"
            ).fetchone()[0]
            assert '"previous_high_water":2000' in audits
        finally:
            close_privacy(panel)


def test_budget_apply_cannot_hide_or_clear_underestimated_spending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.unit.test_cost_cap import reserve

    app = QApplication.instance() or QApplication([])
    install_catalog(
        monkeypatch,
        price(
            provider_id="openai",
            endpoint=URL,
            operation="stt",
            wire_protocol="opaque-fixture-v1",
            input_numerator=0,
            output_numerator=0,
            fixed_fee=13,
        ),
    )
    clock, db = Clock(), tmp_path / "budget.sqlite"
    with ConsentStore(db) as consent, CostLedger(db, clock=clock.now) as ledger:
        panel = PrivacyPanel(consent, ledger, CredentialVault(backend=Vault()))
        try:
            control = configure(panel, "stt", 13)
            privacy_action(panel, "stt", "refresh")
            assert "예산 미적용" in control.balance.text()
            control.total.setValue(0)
            privacy_action(panel, "stt", "budget")
            assert ledger.account("openai", "USD", 0, 2000) is not None
            assert "예산 미적용" not in control.balance.text()
            control.total.setValue(0.000100)
            privacy_action(panel, "stt", "budget")
            request = CostRequest("openai", URL, "model", "v1", "stt", "audio", b"synthetic-packet")
            reservation = reserve(ledger, request, panel._cost_policy("stt"), "underestimated")
            ledger.settle(reservation, 14)
            privacy_action(panel, "stt", "refresh")
            assert "COST_PLAN_UNDERESTIMATED" in control.balance.text()
            privacy_action(panel, "stt", "budget")
            app.processEvents()
            assert ledger.account("openai", "USD", 0, 2000)["blocked"] == 1
            assert "COST_PLAN_UNDERESTIMATED" in control.balance.text()
        finally:
            close_privacy(panel)


def test_worker_model_scope_rejection_has_its_own_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = QApplication.instance() or QApplication([])
    install_catalog(
        monkeypatch,
        price(
            provider_id="openai",
            endpoint=URL,
            operation="stt",
            wire_protocol="opaque-fixture-v1",
            input_numerator=0,
            output_numerator=0,
            fixed_fee=13,
        ),
    )
    clock, db = Clock(), tmp_path / "scope.sqlite"
    with ConsentStore(db) as consent, CostLedger(db, clock=clock.now) as ledger:
        panel = PrivacyPanel(consent, ledger, CredentialVault(backend=Vault()))
        try:
            control = configure(panel, "stt", 13)
            privacy_action(panel, "stt", "budget")
            control.key.setText("FAKE-ONLY")
            privacy_action(panel, "stt", "save")
            privacy_action(panel, "stt", "grant")
            factory = prepare_privacy(
                panel, "stt", "s", threading.Event()
            ).context.reservation_factory
            assert factory is not None
            wrong = CostRequest(
                "openai", URL, "different-model", "v1", "stt", "audio", b"synthetic-packet"
            )
            with pytest.raises(SecurityError, match="^BUDGET_SCOPE_MISMATCH$"):
                factory(wrong)
            assert ledger.reservations("openai") == []
            app.processEvents()
        finally:
            close_privacy(panel)


@pytest.mark.parametrize("fault", ["clock", "integrity"])
def test_main_window_cost_failure_never_blocks_the_recording_controls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    import time

    import recoryn.security as security
    from recoryn.app.desktop import DesktopRecorder
    from recoryn.storage import Library
    from recoryn.ui.main import MainWindow
    from tests.ui.test_desktop_ui import settle

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(security, "CredentialVault", lambda: CredentialVault(backend=Vault()))
    with Library(tmp_path / "library") as library:
        db = library.root / "security.sqlite"
        with CostLedger(db, clock=lambda: time.time() + 3600):
            pass
        if fault == "integrity":
            db.with_name(db.name + ".cost-witness").write_bytes(b"broken")

        def no_device(*args: Any) -> Any:
            pytest.fail("real device must not be opened")

        window = MainWindow(library, recorder=DesktopRecorder(library, no_device))
        try:
            app.processEvents()
            assert window.record_button.isEnabled()
            assert window.ledger.availability() == (
                "COST_CLOCK_INVALID" if fault == "clock" else "LEDGER_ROLLBACK_DETECTED"
            )
            assert "유료 원격 전송 차단" in window.privacy_panel.controls["stt"].balance.text()
            assert library.list_sessions() == []
        finally:
            window.close()
            settle(window, app)
            window.close()


def test_user_cost_edit_revokes_old_binding_without_changing_result_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = QApplication.instance() or QApplication([])
    install_catalog(
        monkeypatch,
        price(
            provider_id="openai",
            endpoint=URL,
            operation="stt",
            wire_protocol="opaque-fixture-v1",
            input_numerator=0,
            output_numerator=0,
            fixed_fee=13,
        ),
    )
    clock = Clock()
    with (
        ConsentStore(tmp_path / "p.sqlite") as consent,
        CostLedger(tmp_path / "p.sqlite", clock=clock.now) as ledger,
    ):
        panel = PrivacyPanel(
            consent, ledger, CredentialVault(backend=Vault(), namespace="g06-revoke")
        )
        try:
            control = configure(panel, "stt", 13)
            privacy_action(panel, "stt", "budget")
            control.key.setText("G06-FAKE-SECRET")
            privacy_action(panel, "stt", "save")
            privacy_action(panel, "stt", "grant")
            plan = prepare_privacy(panel, "stt", "s", threading.Event())
            control.per_request.setValue(0.000099)
            assert panel.config_key("stt", session_id="s") == plan.config_key
            assert plan.context.reservation_factory is not None
            settle_privacy(panel)
            with pytest.raises(SecurityError, match="CONSENT_REVOKED|CONSENT_REQUIRED"):
                plan.context.reservation_factory(
                    CostRequest("openai", URL, "model", "v1", "stt", "audio", b"synthetic-packet")
                )
            assert ledger.account_snapshot("openai", "USD", 0, 2000)["reserved"] == 0
            app.processEvents()
        finally:
            close_privacy(panel)
