"""G11 / G-P11a service and product-path rows: T27, T28 and the admission boundaries.

T27/T28 run the real MainWindow bridge, PrivacyPanel, ConsentStore, CostLedger, Gateway,
OpenAI adapter, AIService and JobStore. Only the OS vault and the transport are fakes,
so a device-policy exemption that skipped consent or cost would reach the fake wire.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

import pytest
from PySide6.QtWidgets import QApplication

import recoryn.app.ai as ai_module
from recoryn.app.ai import AIService
from recoryn.content import ContentStore
from recoryn.domain import StateConflict
from recoryn.models import ResourceRequest
from recoryn.storage import Library
from tests.e2e.test_ai_workflow import FakeSTT, finished, recording

pytestmark = pytest.mark.integration
POLICIES = ("CPU_ONLY", "GPU_ONLY", "GPU_WITH_CPU_FALLBACK_ALLOWED")
T_IDS = ("G11-T-27", "G11-T-28")
# Hand-written G-P07 groups of the independent guards (consent/auth and cost).
CONSENT_OR_AUTH = {"CONSENT_REQUIRED", "AUTH_REQUIRED", "PERMIT_REVOKED", "CONSENT_REVOKED"}
COST = {
    "BUDGET_REQUIRED",
    "BUDGET_BLOCKED",
    "COST_CAP_REQUIRED",
    "COST_PRICE_UNKNOWN",
    "COST_BOUND_UNVERIFIED",
    "LEDGER_REQUIRED",
}


def spin(app: QApplication, condition: Callable[[], bool], timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.001)
    app.processEvents()
    assert condition()


class Wire:
    def __init__(self) -> None:
        self.opens = 0
        self.remaining = b""

    def open(self, *args: Any) -> Wire:
        self.opens += 1
        reply = {
            "text": "fixture",
            "language": "en",
            "segments": [{"start": 0, "end": 0.5, "text": "fixture"}],
        }
        self.remaining = json.dumps(reply).encode()
        return self

    def write(self, data: bytes, timeout: float) -> None:
        pass

    def read(self, limit: int, timeout: float) -> bytes:
        data, self.remaining = self.remaining[:limit], self.remaining[limit:]
        return data

    def close(self) -> None:
        pass


@pytest.mark.parametrize("case", T_IDS, ids=T_IDS)
def test_t_remote_exemption_never_bypasses_consent_or_cost(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    import recoryn.security as security
    from recoryn.security import ConsentScope, CredentialVault, Gateway
    from recoryn.ui.main import MainWindow

    class Vault:
        def read(self, key: str) -> bytes:
            return b"G11-FAKE-KEY"

        def write(self, *args: Any) -> None:
            pytest.fail("no credential writes")

        def delete(self, *args: Any) -> None:
            pytest.fail("no credential deletion")

    monkeypatch.setattr(
        security, "CredentialVault", lambda: CredentialVault(backend=Vault(), namespace="g11")
    )
    app = QApplication.instance() or QApplication([])
    with Library(tmp_path / "library") as library:
        session = recording(library)
        window = MainWindow(library)
        window.timer.stop()
        try:
            window.refresh_sessions()
            spin(app, lambda: window.sessions.count() == 1)
            window.sessions.setCurrentRow(0)
            bridge, privacy, wire = window.ai_bridge, window.privacy_panel, Wire()
            service = bridge._service()
            privacy._gateway = Gateway(privacy.consents, ledger=privacy.ledger, transport=wire)
            control = privacy.controls["stt"]
            control.provider.setCurrentIndex(control.provider.findData("openai"))
            control.endpoint.setText("https://g11-remote.invalid/v1")
            control.context_window.setValue(32768)
            control.max_output.setValue(256)
            control.total.setValue(1)
            control.per_request.setValue(0.01)
            privacy._confirm_general = lambda _: True
            prepared: list[str] = []
            original = privacy.prepare_execution

            def prepare(*args: Any) -> Any:
                prepared.append(args[0])
                return original(*args)

            monkeypatch.setattr(privacy, "prepare_execution", prepare)

            def grant() -> None:
                privacy.consents.grant(
                    "openai",
                    control.endpoint.text(),
                    "audio",
                    capability="stt",
                    scope=ConsentScope.session(session),
                    policy_version=privacy.consents.policy_version,
                )

            def revoke() -> None:
                privacy.consents.revoke(
                    "openai",
                    control.endpoint.text(),
                    "audio",
                    capability="stt",
                    scope=ConsentScope.session(session),
                    policy_version=privacy.consents.policy_version,
                )

            def mode(name: str) -> None:
                control.cost_mode.setCurrentIndex(control.cost_mode.findData(name))
                privacy._action("stt", "budget")

            def run(model: str) -> tuple[str, str | None, list[Any]]:
                """Click, settle, then read the refusal from the record or the status."""
                control.model.setText(model)
                before = len(service.jobs.list_for_session(session))
                bridge.transcribe()
                spin(app, lambda: not bridge.busy and not service.runner.snapshot()["active"])
                created = [
                    finished(service, job.job_id)
                    for job in service.jobs.list_for_session(session)[before:]
                ]
                text = bridge.panel.job_status.text()  # the preparation outcome, if any
                if created:
                    bridge.tick()  # a Job's later refusal is shown by the next tick
                    return bridge.panel.job_status.text(), created[0].error_code, created
                return text, next((c for c in CONSENT_OR_AUTH | COST if c in text), None), []

            for index, policy in enumerate(POLICIES):
                window.device_policy.setCurrentText(policy)
                opens, calls = wire.opens, len(prepared)
                if case == "G11-T-27":
                    # Valid cost (acknowledged user cap), no consent: the consent guard.
                    mode("general")
                    text, code, jobs = run(f"t27-{index}")
                    assert code in CONSENT_OR_AUTH, (text, jobs)
                    assert all(job.blocked_reason in {"CONSENT", "AUTH"} for job in jobs)
                else:
                    # Valid consent, strict cost without a verified price (empty production
                    # catalog): the cost guard refuses at the reservation.
                    grant()
                    mode("strict")
                    text, code, jobs = run(f"t28-{index}")
                    assert code in COST, (text, jobs)
                    assert [(job.state.value, job.blocked_reason) for job in jobs] == [
                        ("BLOCKED", "BUDGET")
                    ]
                    assert service.resource_request(jobs[0].job_id) == ResourceRequest(
                        "stt", "REMOTE", policy
                    )
                    revoke()
                assert code is not None and code in text
                assert "RESOURCE_" not in text and "CAPABILITY_UNSUPPORTED" not in text
                assert wire.opens == opens and len(prepared) == calls + 1
                # Control leg under the same policy: valid consent and an acknowledged user
                # cap reach the fake transport exactly once and succeed.
                grant()
                mode("general")
                text, code, jobs = run(f"{case}-ok-{index}")
                assert [job.state.value for job in jobs] == ["SUCCEEDED"], text
                assert wire.opens == opens + 1 and len(prepared) == calls + 2
                assert service.resource_request(jobs[0].job_id) == ResourceRequest(
                    "stt", "REMOTE", policy
                )
                assert "원격 실행 — 이 PC의 장치 정책 적용 안 됨" in text
                revoke()
        finally:
            window.close()
            spin(app, lambda: window._closing)
            window.deleteLater()
            app.processEvents()


def test_dispatch_rechecks_the_captured_policy_before_the_provider(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G11-AUX-DISPATCH: section 3.2's dispatch re-check, separate from admission."""
    calls: list[str] = []
    real = ai_module.plan_static

    def once_then_refuse(request: ResourceRequest) -> Any:
        calls.append(request.policy)
        if len(calls) > 1:
            raise StateConflict("RESOURCE_POLICY_UNVERIFIED")
        return real(request)

    class Provider(FakeSTT):
        used = 0

        def transcribe(self, request: Any, context: Any = None) -> Any:
            Provider.used += 1
            return super().transcribe(request, context)

    monkeypatch.setattr(ai_module, "plan_static", once_then_refuse)
    with Library(tmp_path / "library") as library, ContentStore(library) as content:
        session = recording(library)
        service = AIService(library, content)
        try:
            job = service.transcribe(
                session,
                Provider(),
                config_key="dispatch",
                resource_request=ResourceRequest("stt", "LOCAL_CT2", "CPU_ONLY"),
            )
            done = finished(service, job)
        finally:
            service.close()
    assert calls == ["CPU_ONLY", "CPU_ONLY"] and Provider.used == 0
    assert (done.state.value, done.blocked_reason, done.error_code) == (
        "BLOCKED",
        "CAPABILITY",
        "RESOURCE_POLICY_UNVERIFIED",
    )


def test_merge_keeps_the_captured_request_and_continue_replaces_it(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G11-AUX-CAPTURE: a same-key request never rewrites a queued Job's policy (M24);
    an explicit continue is a new admission whose snapshot is captured (decision 7)."""
    with Library(tmp_path / "library") as library, ContentStore(library) as content:
        session = recording(library)
        service = AIService(library, content)
        try:
            real_submit = service.runner.submit
            # Fixture only: hold the first intent QUEUED without dispatch.
            monkeypatch.setattr(service.runner, "submit", lambda *args: True)
            queued = ResourceRequest("stt", "LOCAL_CT2", "CPU_ONLY", runtime_identity="queued")
            job = service.transcribe(session, FakeSTT(), config_key="same", resource_request=queued)
            later = ResourceRequest("stt", "LOCAL_CT2", "GPU_WITH_CPU_FALLBACK_ALLOWED")
            again = service.transcribe(
                session, FakeSTT(), config_key="same", resource_request=later
            )
            assert again == job and service.resource_request(job) is queued
            record = service.jobs.get(job)
            blocked = service.jobs.block_pending(
                job, "BUDGET", "COST_CAP_EXCEEDED", expected_version=record.state_version
            )
            # A plain same-key request only observes the BLOCKED Job (G-P07, no resume).
            assert (
                service.transcribe(session, FakeSTT(), config_key="same", resource_request=later)
                == job
            )
            assert service.jobs.get(job) == blocked and service.resource_request(job) is queued
            monkeypatch.setattr(service.runner, "submit", real_submit)
            resumed = service.transcribe(
                session,
                FakeSTT(),
                config_key="same",
                resource_request=later,
                expected_job_id=job,
                expected_job_version=blocked.state_version,
            )
            assert resumed == job and service.resource_request(job) is later
            assert finished(service, job).state.value == "SUCCEEDED"
        finally:
            service.close()
