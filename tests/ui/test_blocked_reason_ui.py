"""Actual widget activation with independent navigation/continue side-effect oracles."""

from __future__ import annotations

from dataclasses import replace
from itertools import product
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QTabWidget,
    QWidget,
)

from recoryn.app.status import AIStatus, ai_status
from recoryn.jobs import JobStore
from recoryn.ui.ai_bridge import DesktopAI
from recoryn.ui.content import ContentPanel
from tests.resource_fakes import STT
from tests.ui.test_secret_lifetime_ui import privacy_action


def _spin(app, condition, *, timeout=15):
    import time

    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.001)
    app.processEvents()
    assert condition()


@pytest.mark.parametrize(
    "reason,preparation,reader_active",
    list(
        product(
            ("CONSENT", "AUTH", "CAPABILITY", "RESOURCE", "BUDGET"),
            ("same", "stale", "changed"),
            (False, True),
        )
    ),
    ids=[f"G07-F-{i:02}" for i in range(1, 31)],
)
def test_continue_preparation_space_uses_actual_authority_and_reader_boundaries(
    app, tmp_path, monkeypatch, reason, preparation, reader_active
):
    import recoryn.security as security
    from recoryn.security import ConsentScope, CredentialVault, Gateway
    from recoryn.storage import Library
    from recoryn.ui.main import MainWindow
    from tests.e2e.test_ai_workflow import recording

    class Vault:
        def read(self, key):
            return b"G07-F-FAKE-KEY"

        def write(self, *args):
            pytest.fail("no credential writes")

        def delete(self, *args):
            pytest.fail("no credential deletion")

    monkeypatch.setattr(
        security,
        "CredentialVault",
        lambda: CredentialVault(backend=Vault(), namespace="g07-f"),
    )

    class Wire:
        opens = 0
        output = b""

        def open(self, *args):
            self.opens += 1
            self.output = b'{"text":"synthetic"}'
            return self

        def write(self, data, timeout):
            pass

        def read(self, limit, timeout):
            block, self.output = self.output[:limit], self.output[limit:]
            return block

        def close(self):
            pass

    with Library(tmp_path / "library") as library:
        session = recording(library)
        window = MainWindow(library)
        window.timer.stop()
        claimed = None
        original_submit = None
        try:
            window.refresh_sessions()
            _spin(app, lambda: window.sessions.count() == 1)
            window.sessions.setCurrentRow(0)
            bridge, privacy, wire = window.ai_bridge, window.privacy_panel, Wire()
            service = bridge._service()
            control = privacy.controls["stt"]
            control.provider.setCurrentIndex(control.provider.findData("openai"))
            control.endpoint.setText("https://g07-f.invalid/v1")
            control.model.setText("fake-model")
            control.context_window.setValue(32768)
            control.max_output.setValue(256)
            control.total.setValue(1)
            control.per_request.setValue(0.01)
            privacy._confirm_general = lambda _: True
            control.cost_mode.setCurrentIndex(control.cost_mode.findData("general"))
            privacy_action(privacy, "stt", "budget")
            privacy.backend.gateway = Gateway(
                privacy.consents, ledger=privacy.ledger, transport=wire
            )
            scope = ConsentScope.session(session)

            def grant():
                privacy.consents.grant(
                    "openai",
                    control.endpoint.text(),
                    "audio",
                    capability="stt",
                    scope=scope,
                    policy_version=privacy.consents.policy_version,
                )

            grant()
            preparations = []
            original_prepare = privacy.backend.prepare_execution

            def prepare(*args):
                execution = original_prepare(*args)
                preparations.append(execution)
                return execution

            monkeypatch.setattr(privacy.backend, "prepare_execution", prepare)
            # Only fixture setup holds the first QUEUED intent without dispatch.
            # Restore the real runner before the observed UI continue operation.
            original_submit = service.runner.submit
            monkeypatch.setattr(service.runner, "submit", lambda *args, **kwargs: True)
            bridge.transcribe()
            _spin(app, lambda: not bridge.busy)
            monkeypatch.setattr(service.runner, "submit", original_submit)
            job = service.jobs.list_for_session(session)[-1]
            code = {
                "CONSENT": "CONSENT_REQUIRED",
                "AUTH": "AUTH_REQUIRED",
                "CAPABILITY": "CAPABILITY_UNSUPPORTED",
                "RESOURCE": "OOM",
                "BUDGET": "COST_CAP_EXCEEDED",
            }[reason]
            if reader_active:
                claimed = service.jobs.claim(job.job_id, "fixture-reader")
                service.jobs.reader_started(claimed)
                before = service.jobs.fail(job.job_id, claimed.attempt_id, claimed.fence, code)
            else:
                before = service.jobs.block_pending(
                    job.job_id, reason, code, expected_version=job.state_version
                )
            if preparation == "stale":
                privacy.consents.revoke(
                    "openai",
                    control.endpoint.text(),
                    "audio",
                    capability="stt",
                    scope=scope,
                    policy_version=privacy.consents.policy_version,
                )
            elif preparation == "changed":
                control.model.setText("different-model")
                grant()
            bridge.tick()
            assert bridge.panel.blocked_continue.isEnabled() is (not reader_active)
            QTest.mouseClick(bridge.panel.blocked_continue, Qt.MouseButton.LeftButton)
            _spin(app, lambda: not bridge.busy and not service.runner.snapshot()["active"])
            after = service.jobs.get(job.job_id)
            authorized = not reader_active and preparation == "same"
            assert wire.opens == int(authorized)
            assert len(service.jobs.list_for_session(session)) == 1
            reservations = privacy.ledger._db.execute(
                "SELECT reservation_id,quote_kind FROM security_cost_requests_v2"
            ).fetchall()
            assert len(reservations) == int(authorized)
            if authorized:
                assert after.state.value == "SUCCEEDED" and after.attempt_count == 1
                assert len(preparations) == 2 and preparations[1] is not preparations[0]
                assert preparations[1].config_key == preparations[0].config_key
                assert reservations[0][1] == "USER_CAP"
            else:
                assert after == before
                if not reader_active:
                    if preparation == "stale":
                        assert "CONSENT" in bridge.panel.job_status.text()
                    else:
                        assert "새 작업 필요" in bridge.panel.job_status.text()
            expected_reader = True if reader_active else False if authorized else None
            assert service.jobs.local_reader_active(job.job_id) is expected_reader
        finally:
            if original_submit is not None:
                monkeypatch.setattr(window.ai_bridge.service.runner, "submit", original_submit)
            if claimed is not None:
                window.ai_bridge.service.jobs.reader_finished(claimed)
            window.close()
            _spin(app, lambda: window._closing)
            window.deleteLater()
            app.processEvents()


@pytest.mark.parametrize(
    "feature,revocation",
    list(
        product(
            ("stt", "summary"),
            ("fresh", "before_prepare", "after_prepare", "changed_plan", "history_unavailable"),
        )
    ),
    ids=[f"G07-FIX1-CONTINUE-{i:02}" for i in range(1, 11)],
)
def test_ui_continue_uses_real_privacy_ledger_gateway_and_fresh_authority(
    app, tmp_path, monkeypatch, feature, revocation
):
    import json
    import threading
    from contextlib import contextmanager

    import recoryn.security as security
    from recoryn.security import ConsentScope, CredentialVault, Gateway, SecurityError
    from recoryn.storage import Library
    from recoryn.ui.main import MainWindow
    from tests.e2e.test_ai_workflow import FakeSTT, recording

    class NoVaultIO:
        def read(self, key):
            return b"G07-FAKE-KEY"

        def write(self, *args):
            pytest.fail("real UI continue must not write a credential")

        def delete(self, *args):
            pytest.fail("real UI continue must not delete a credential")

    # Replace only OS/vault/transport boundaries. Privacy, quote/reservation,
    # SendPermit, actual adapters, JobStore and UI continue are production code.
    monkeypatch.setattr(
        security,
        "CredentialVault",
        lambda: CredentialVault(backend=NoVaultIO(), namespace="g07-continue"),
    )

    class Wire:
        opens = 0
        writes = 0
        remaining = b""

        def open(self, *args):
            self.opens += 1
            if self.opens == 1:
                raise SecurityError("CONSENT_REVOKED", outcome_known=True)
            reply = (
                {
                    "text": "fixture",
                    "language": "en",
                    "segments": [{"start": 0, "end": 0.5, "text": "fixture"}],
                }
                if feature == "stt"
                else {
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": '{"claims":[]}'}],
                        }
                    ],
                }
            )
            self.remaining = json.dumps(reply).encode()
            return self

        def write(self, data, timeout):
            self.writes += 1

        def read(self, limit, timeout):
            data, self.remaining = self.remaining[:limit], self.remaining[limit:]
            return data

        def close(self):
            pass

    with Library(tmp_path / "library") as library:
        session = recording(library)
        window = MainWindow(library)
        window.timer.stop()
        wire = Wire()
        release, entered = threading.Event(), threading.Event()
        history_blocked = False
        try:
            window.refresh_sessions()
            _spin(app, lambda: window.sessions.count() == 1)
            window.sessions.setCurrentRow(0)
            bridge, privacy = window.ai_bridge, window.privacy_panel
            service = bridge._service()
            if feature == "summary":
                seed = service.transcribe(
                    session, FakeSTT(), config_key="seed", resource_request=STT
                )
                _spin(app, lambda: service.jobs.get(seed).state.value == "SUCCEEDED")
                bridge.panel.load(session)
            control = privacy.controls[feature]
            control.provider.setCurrentIndex(control.provider.findData("openai"))
            control.endpoint.setText("https://g07-continue.invalid/v1")
            control.model.setText("fake-model")
            control.context_window.setValue(32768)
            control.max_output.setValue(256)
            control.total.setValue(1)
            control.per_request.setValue(0.01)
            privacy._confirm_general = lambda _: True
            control.cost_mode.setCurrentIndex(control.cost_mode.findData("general"))
            assert control.general_acknowledged
            privacy_action(privacy, feature, "budget")
            privacy.backend.gateway = Gateway(
                privacy.consents, ledger=privacy.ledger, transport=wire
            )
            scope = ConsentScope.session(session)
            types = ("audio",) if feature == "stt" else ("transcript", "context")

            def grant():
                for data_type in types:
                    privacy.consents.grant(
                        "openai",
                        control.endpoint.text(),
                        data_type,
                        capability=feature,
                        scope=scope,
                        policy_version=privacy.consents.policy_version,
                    )

            def revoke():
                for data_type in types:
                    privacy.consents.revoke(
                        "openai",
                        control.endpoint.text(),
                        data_type,
                        capability=feature,
                        scope=scope,
                        policy_version=privacy.consents.policy_version,
                    )

            grant()
            prepared, requests, preparation_calls = [], [], []
            prepare = privacy.backend.prepare_execution

            def observed_prepare(*args):
                preparation_calls.append((args[0].kind, args[0].session_id))
                execution = prepare(*args)
                original_factory = execution.context.reservation_factory

                def reserved(request):
                    requests.append(request)
                    return original_factory(request)

                prepared.append(execution)
                return replace(
                    execution,
                    context=replace(execution.context, reservation_factory=reserved),
                )

            monkeypatch.setattr(privacy.backend, "prepare_execution", observed_prepare)
            (bridge.transcribe if feature == "stt" else lambda: bridge.summarize("meeting"))()

            def terminal():
                jobs = service.jobs.list_for_session(session)
                return bool(jobs and jobs[-1].state.value == "BLOCKED" and not bridge.busy)

            _spin(app, terminal)
            job = service.jobs.list_for_session(session)[-1]
            assert job.blocked_reason == "CONSENT" and job.attempt_count == 1
            assert wire.opens == 1 and wire.writes == 0
            old_reservations = {
                row[0]
                for row in privacy.ledger._db.execute(
                    "SELECT reservation_id FROM security_cost_requests_v2"
                )
            }
            assert len(old_reservations) == 1 and len(prepared) == len(requests) == 1
            revoke()
            with pytest.raises(SecurityError):
                prepared[0].context.reservation_factory(requests[0])
            grant()
            original_call = getattr(service, "transcribe" if feature == "stt" else "summarize")

            def observed_service(*args, **kwargs):
                if revocation == "after_prepare" and kwargs.get("expected_job_id"):
                    entered.set()
                    assert release.wait(15)
                return original_call(*args, **kwargs)

            monkeypatch.setattr(
                service, "transcribe" if feature == "stt" else "summarize", observed_service
            )
            if revocation == "before_prepare":
                revoke()
            elif revocation == "changed_plan":
                control.model.setText("a-different-model")
                grant()
            elif revocation == "history_unavailable":
                authority = Library.job_authority

                @contextmanager
                def blocked_authority(db_path, sid):
                    if history_blocked:
                        yield "HISTORY_UNAVAILABLE"
                    else:
                        with authority(db_path, sid) as state:
                            yield state

                history_blocked = True
                monkeypatch.setattr(Library, "job_authority", staticmethod(blocked_authority))
            bridge.tick()
            assert bridge.panel.blocked_continue.isEnabled()
            QTest.mouseClick(bridge.panel.blocked_continue, Qt.MouseButton.LeftButton)
            if revocation == "after_prepare":
                _spin(app, entered.is_set)
                revoke()  # Preparation < revocation < the actual worker/SendPermit.
                release.set()
            _spin(app, lambda: not bridge.busy and not service.runner.snapshot()["active"])
            current = service.jobs.get(job.job_id)
            assert len(preparation_calls) == 2
            expected = {
                "fresh": ("SUCCEEDED", 2, 2),
                "before_prepare": ("BLOCKED", 1, 1),
                "after_prepare": ("BLOCKED", 2, 1),
                "changed_plan": ("BLOCKED", 1, 1),
                "history_unavailable": ("BLOCKED", 1, 1),
            }[revocation]
            assert (current.state.value, current.attempt_count, wire.opens) == expected
            assert len(service.jobs.list_for_session(session)) == (2 if feature == "summary" else 1)
            reservations = {
                row[0]
                for row in privacy.ledger._db.execute(
                    "SELECT reservation_id FROM security_cost_requests_v2"
                )
            }
            assert old_reservations <= reservations
            assert len(reservations - old_reservations) == int(revocation == "fresh")
            if revocation != "before_prepare":
                assert len(prepared) == 2
                assert (prepared[1].config_key == prepared[0].config_key) is (
                    revocation != "changed_plan"
                )
                assert prepared[1].gateway.expected_grants != prepared[0].gateway.expected_grants
            if revocation != "fresh":
                assert current.blocked_reason == "CONSENT" and wire.writes == 0
                if revocation == "changed_plan":
                    assert "새 작업 필요" in bridge.panel.job_status.text()
                elif revocation == "history_unavailable":
                    assert "삭제 이력 확인 불가" in bridge.panel.job_status.text()
                    assert bridge._blocked_target[3] == "deletion_history"
                    assert bridge.panel.blocked_continue.isEnabled()
            else:
                assert wire.writes > 0
        finally:
            history_blocked = False
            release.set()
            _spin(app, lambda: not window.ai_bridge.busy)
            window.close()
            _spin(app, lambda: window._closing)
            window.deleteLater()
            app.processEvents()


U = list(
    product(
        (
            "CONSENT",
            "AUTH",
            "CAPABILITY",
            "RESOURCE",
            "BUDGET",
            "REMOTE_UNKNOWN",
            "FAILED_INPUT",
            "FAILED_OTHER",
        ),
        ("stt", "summary", "diarization"),
        ("render", "open", "continue"),
        (False, True),
    )
)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("row", U, ids=[f"G07-U-{n:03}" for n in range(1, len(U) + 1)])
def test_reason_actions_are_explicit_and_selection_bound(app, row):
    reason, feature, action, current = row
    calls = []

    class Privacy(QWidget):
        def focus_blocked_action(self, kind, action_id):
            calls.append(("navigate", kind, action_id))

    with JobStore(Path(":memory:")) as store:
        kind = {"stt": "transcription", "summary": "summarization", "diarization": "diarization"}[
            feature
        ]
        job = store.create(kind, "plan")
        store.bind_session(job.job_id, "s")
        code = {
            "CONSENT": "CONSENT_REQUIRED",
            "AUTH": "AUTH_REQUIRED",
            "CAPABILITY": "CAPABILITY_UNSUPPORTED",
            "RESOURCE": "OOM",
            "BUDGET": "COST_CAP_EXCEEDED",
            "REMOTE_UNKNOWN": "REMOTE_OUTCOME_UNKNOWN",
            "FAILED_INPUT": "INPUT_INVALID",
            "FAILED_OTHER": "TASK_FAILED",
        }[reason]
        if reason in {"CONSENT", "AUTH", "CAPABILITY", "RESOURCE", "BUDGET"}:
            job = store.block_pending(job.job_id, reason, code, expected_version=0)
        else:
            a = store.claim(job.job_id, "worker")
            job = store.fail(job.job_id, a.attempt_id, a.fence, code)
        before = store.get(job.job_id)
        panel = ContentPanel(
            SimpleNamespace(
                active_transcript=lambda _: None,
                list_revisions=lambda *_: [],
                active_summary=lambda _: None,
            ),
            lambda *_: None,
        )
        tabs, privacy, models = QTabWidget(), Privacy(), QWidget()
        models.installed = QListWidget(models)
        tabs.addTab(privacy, "privacy")
        tabs.addTab(models, "models")
        tabs.setCurrentIndex(0)
        model = QLineEdit(models)
        policy = QComboBox(models)
        policy.addItems(["GPU_ONLY", "CPU_ONLY", "GPU_WITH_CPU_FALLBACK_ALLOWED"])
        bridge = DesktopAI.__new__(DesktopAI)
        bridge.panel, bridge._history, bridge.privacy = panel, store, privacy
        bridge.window = SimpleNamespace(
            selected_session=lambda: "s",
            tabs=tabs,
            model_panel=models,
            local_model=model,
            device_policy=policy,
            busy=False,
        )
        bridge._blocked_target = ("s", job.job_id, job.state_version, "unused")
        bridge._preparation_action = None
        bridge._job_options = {job.job_id: (feature, None, "meeting")}
        bridge.busy = bridge._shutting_down = False
        bridge._transcribe = lambda **kw: calls.append(("continue", "stt", kw))
        bridge.summarize = lambda template, **kw: calls.append(("continue", "summary", kw))
        panel.blockedOpenRequested.connect(bridge.open_blocked_action)
        panel.blockedContinueRequested.connect(bridge.continue_blocked)
        models.request_attestation_check = lambda: None
        bridge.local, bridge._last_snapshot = None, ""
        bridge._live_tick = lambda: None
        bridge.tick()
        allowed_reason = reason in {"CONSENT", "AUTH", "CAPABILITY", "RESOURCE", "BUDGET"}
        assert panel.blocked_continue.isEnabled() is (allowed_reason and feature != "diarization")
        bridge.window.selected_session = lambda: "s" if current else "other"
        assert code in panel.job_status.text()
        assert "SECRET" not in panel.job_status.text()
        if action == "open":
            QTest.mouseClick(panel.blocked_open, Qt.MouseButton.LeftButton)
        elif action == "continue":
            QTest.mouseClick(panel.blocked_continue, Qt.MouseButton.LeftButton)
        expected_continue = (
            action == "continue" and current and allowed_reason and feature != "diarization"
        )
        assert sum(c[0] == "continue" for c in calls) == int(expected_continue)
        if expected_continue:
            assert calls[-1][2]["expected"] == (job.job_id, job.state_version)
        expected_nav = action == "open" and current and allowed_reason
        assert (bool(calls) or tabs.currentWidget() is models) is (
            expected_continue or expected_nav
        )
        assert store.get(job.job_id) == before
        assert policy.currentText() == "GPU_ONLY"
        assert store._db.execute("SELECT COUNT(*) FROM job_remote_intents").fetchone()[0] == 0
        panel.deleteLater()
        tabs.deleteLater()
        app.processEvents()


@pytest.mark.parametrize(
    "feature,approved",
    list(product(("stt", "summary", "diarization"), (False, True))),
    ids=[f"G07-U-{n:03}" for n in range(145, 151)],
)
def test_unknown_new_request_confirmation_is_explicit(app, monkeypatch, feature, approved):
    bridge = DesktopAI.__new__(DesktopAI)
    bridge.window = QWidget()
    prompts = []

    def question(*args):
        prompts.append(args)
        return QMessageBox.StandardButton.Yes if approved else QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", question)
    assert bridge._confirm_retry() is approved
    assert len(prompts) == 1
    assert "중복" in prompts[0][2] and "비용" in prompts[0][2]
    assert prompts[0][-1] == QMessageBox.StandardButton.No
    bridge.window.deleteLater()


def test_preparation_status_is_not_a_fabricated_job(app):
    from recoryn.jobs.failures import NormalizedFailure

    panel = ContentPanel(SimpleNamespace(), lambda *_: None)
    status = ai_status(preparation=NormalizedFailure("CONSENT_POLICY_CHANGED"))
    panel.show_ai_status(status)
    assert "작업 미접수" in panel.job_status.text()
    assert panel.blocked_open.isEnabled() and not panel.blocked_continue.isEnabled()
    panel.show_ai_status(AIStatus("설정이 달라 새 작업 필요"))
    assert not panel.blocked_open.isEnabled() and not panel.blocked_continue.isEnabled()
    panel.deleteLater()


def test_action_census():
    assert len(U) == len(set(U)) == 144


def test_diarization_direct_continue_uses_the_product_kind_guard(app):
    with JobStore(Path(":memory:")) as store:
        job = store.create("diarization", "same")
        job = store.block_pending(job.job_id, "RESOURCE", "OOM", expected_version=0)
        calls = []
        bridge = DesktopAI.__new__(DesktopAI)
        bridge._history = store
        bridge.window = SimpleNamespace(selected_session=lambda: "s")
        bridge.panel = ContentPanel(SimpleNamespace(), lambda *_: None)
        bridge.busy = bridge._shutting_down = False
        bridge._blocked_target = ("s", job.job_id, job.state_version, "resource")
        bridge._job_options = {job.job_id: ("diarization", None, "meeting")}
        bridge._transcribe = lambda **kwargs: calls.append(kwargs)
        bridge.summarize = lambda *args, **kwargs: calls.append(kwargs)
        bridge.continue_blocked()
        assert calls == [] and store.get(job.job_id) == job
        bridge.panel.deleteLater()


@pytest.mark.parametrize(
    "code,finalize_enabled",
    [
        ("TRANSCRIPTION_REQUIRES_FINALIZED_AUDIO", False),
        ("TRANSCRIPTION_REQUIRES_FINALIZED_AUDIO", True),
        ("SUMMARY_REQUIRES_COMPLETE_TRANSCRIPT", False),
    ],
    ids=[f"G07-FIX1-NAV-{i:02}" for i in range(1, 4)],
)
def test_input_preconditions_navigate_to_finalize_or_transcription_only(
    app, code, finalize_enabled
):
    from PySide6.QtWidgets import QPlainTextEdit, QPushButton, QVBoxLayout

    from recoryn.jobs.failures import NormalizedFailure

    root = QWidget()
    layout = QVBoxLayout(root)
    finalize = QPushButton("finalize")
    finalize.setEnabled(finalize_enabled)
    layout.addWidget(finalize)
    tabs = QTabWidget()
    layout.addWidget(tabs)
    details = QPlainTextEdit()
    panel = ContentPanel(SimpleNamespace(), lambda *_: pytest.fail("navigation executed work"))
    unrelated = QWidget()
    tabs.addTab(unrelated, "unrelated")
    tabs.addTab(details, "details")
    tabs.addTab(panel, "content")
    bridge = DesktopAI.__new__(DesktopAI)
    bridge.window = SimpleNamespace(
        selected_session=lambda: "s", tabs=tabs, details=details, finalize_button=finalize
    )
    bridge.panel, bridge.privacy = panel, None
    bridge._blocked_target = bridge._preparation_action = None
    bridge._show_preparation(NormalizedFailure(code))
    panel.blockedOpenRequested.connect(bridge.open_blocked_action)
    root.show()
    tabs.setCurrentWidget(panel)
    app.processEvents()
    QTest.mouseClick(panel.blocked_open, Qt.MouseButton.LeftButton)
    app.processEvents()
    if code.startswith("TRANSCRIPTION"):
        assert tabs.currentWidget() is details
        assert (finalize if finalize_enabled else details).hasFocus()
        assert "정지 후 세션 확정" in panel.job_status.text()
    else:
        assert tabs.currentWidget() is panel and panel.transcribe_button.hasFocus()
        assert "완전한 전사 필요" in panel.job_status.text()
    assert not panel.blocked_continue.isEnabled()
    root.close()
    root.deleteLater()


def test_playback_jobs_never_hide_a_blocked_ai_job_and_unknown_codes_are_safe(app):
    with JobStore(Path(":memory:")) as store:
        job = store.create("summarization", "same")
        store.bind_session(job.job_id, "s")
        job = store.block_pending(job.job_id, "CONSENT", "CONSENT_REQUIRED", expected_version=0)
        playback = store.create("playback_verification", "playback")
        store.bind_session(playback.job_id, "s")
        attempt = store.claim(playback.job_id, "reader")
        store.complete(playback.job_id, attempt.attempt_id, attempt.fence, "verified")
        panel = ContentPanel(
            SimpleNamespace(
                active_transcript=lambda _: None,
                list_revisions=lambda *_: [],
                active_summary=lambda _: None,
            ),
            lambda *_: None,
        )
        bridge = DesktopAI.__new__(DesktopAI)
        bridge.window = SimpleNamespace(
            selected_session=lambda: "s",
            busy=False,
            model_panel=SimpleNamespace(request_attestation_check=lambda: None),
        )
        bridge.panel, bridge._history, bridge.local = panel, store, None
        bridge._last_snapshot, bridge._gpu_failed = "", None
        bridge._live_tick = lambda: None
        bridge.busy = False
        bridge.tick()
        assert bridge._blocked_target is not None
        assert bridge._blocked_target[1] == job.job_id
        assert panel.blocked_continue.isEnabled() and "CONSENT_REQUIRED" in panel.job_status.text()
        failed = store.create("transcription", "other")
        store.bind_session(failed.job_id, "s")
        attempt = store.claim(failed.job_id, "reader")
        store.fail(failed.job_id, attempt.attempt_id, attempt.fence, "SECRET_UNREGISTERED_ERROR")
        bridge.tick()
        assert "TASK_FAILED" in panel.job_status.text() and "SECRET" not in panel.job_status.text()
        panel.deleteLater()


def test_real_window_updates_a_queued_history_refusal_and_allows_explicit_readmission(
    app, tmp_path, monkeypatch
):
    import threading
    from contextlib import contextmanager

    from recoryn.storage import Library
    from recoryn.ui.main import MainWindow
    from tests.e2e.test_ai_workflow import FakeSTT, recording

    entered, release = threading.Event(), threading.Event()
    blocked = True
    authority = Library.job_authority

    @contextmanager
    def guarded(db_path, sid):
        if blocked:
            entered.set()
            assert release.wait(15)
            yield "HISTORY_UNAVAILABLE"
        else:
            with authority(db_path, sid) as state:
                yield state

    with Library(tmp_path / "library") as library:
        session = recording(library)
        window = MainWindow(library)
        window.timer.stop()
        try:
            window.refresh_sessions()
            _spin(app, lambda: window.sessions.count() == 1)
            window.sessions.setCurrentRow(0)
            bridge = window.ai_bridge
            service = bridge._service()
            monkeypatch.setattr(Library, "job_authority", staticmethod(guarded))
            job = service.transcribe(session, FakeSTT(), config_key="same", resource_request=STT)
            _spin(app, entered.is_set)
            bridge.tick()
            assert "QUEUED" in bridge.panel.job_status.text()
            release.set()
            _spin(app, lambda: not service.runner.snapshot()["active"])
            bridge.tick()
            assert service.jobs.get(job).state.value == "QUEUED"
            assert "삭제 이력 확인 불가" in bridge.panel.job_status.text()
            assert bridge.panel.blocked_open.isEnabled()
            assert not bridge.panel.blocked_continue.isEnabled()
            QTest.mouseClick(bridge.panel.blocked_open, Qt.MouseButton.LeftButton)
            assert window.tabs.currentWidget() is window.details
            assert "삭제 journal" in window.details.toPlainText()
            blocked = False
            same = service.transcribe(session, FakeSTT(), config_key="same", resource_request=STT)
            assert same == job
            _spin(app, lambda: service.jobs.get(job).state.value == "SUCCEEDED")
            bridge.tick()
            assert "삭제 이력 확인 불가" not in bridge.panel.job_status.text()
        finally:
            blocked = False
            release.set()
            window.close()
            _spin(app, lambda: window._closing)
            window.deleteLater()
            app.processEvents()


@pytest.mark.parametrize(
    "code", ("COST_PRICE_UNKNOWN", "COST_PRICE_EXPIRED", "COST_BOUND_UNVERIFIED")
)
def test_missing_price_guidance_never_presents_cap_increase_as_sufficient(app, code):
    with JobStore(Path(":memory:")) as store:
        job = store.create("summary", "fixed")
        job = store.block_pending(job.job_id, "BUDGET", code, expected_version=0)
        status = ai_status(job)
        assert "검증된 가격·요청 상한 근거 필요" in status.text
        assert "cap 증액만으로 해결되지 않음" in status.text
        assert status.action_id == "price"


def test_failed_continue_preparation_keeps_existing_job_and_explicit_retry_available(app):
    from recoryn.jobs.failures import NormalizedFailure

    with JobStore(Path(":memory:")) as store:
        job = store.create("transcription", "same")
        job = store.block_pending(job.job_id, "RESOURCE", "OOM", expected_version=0)
        bridge = DesktopAI.__new__(DesktopAI)
        bridge.panel = ContentPanel(SimpleNamespace(), lambda *_: None)
        bridge.window = SimpleNamespace(selected_session=lambda: "s")
        bridge._history = store
        bridge._blocked_target = ("s", job.job_id, job.state_version, "resource")
        bridge._preparation_action = None
        bridge._show_preparation(NormalizedFailure("CONSENT_REQUIRED"), preserve_job=True)
        assert "작업 미접수" in bridge.panel.job_status.text()
        assert "기존 Job BLOCKED 유지" in bridge.panel.job_status.text()
        assert bridge.panel.blocked_continue.isEnabled()
        assert bridge._blocked_target == ("s", job.job_id, job.state_version, "consent")
        assert store.get(job.job_id) == job
        bridge._show_preparation(AIStatus("설정이 달라 새 작업 필요"), preserve_job=True)
        assert not bridge.panel.blocked_continue.isEnabled()
        assert bridge._blocked_target is None
        bridge.panel.deleteLater()


@pytest.mark.parametrize(
    "code,known",
    [
        ("CONSENT_REVOKED", False),
        ("DELETION_HISTORY_UNAVAILABLE", False),
        ("REMOTE_OUTCOME_UNKNOWN", True),
    ],
    ids=["G07-FIX1-UNKNOWN-01", "G07-FIX1-UNKNOWN-02", "G07-FIX1-UNKNOWN-03"],
)
def test_unknown_preparation_never_reenables_continue_on_an_existing_blocked_job(app, code, known):
    from PySide6.QtCore import QThreadPool

    from recoryn.domain import StateConflict
    from recoryn.jobs.failures import NormalizedFailure

    with JobStore(Path(":memory:")) as store:
        job = store.create("transcription", "same")
        job = store.block_pending(job.job_id, "RESOURCE", "OOM", expected_version=0)
        bridge = DesktopAI.__new__(DesktopAI)
        bridge.window = SimpleNamespace(selected_session=lambda: "s")
        bridge.panel = ContentPanel(SimpleNamespace(), lambda *_: None)
        bridge._history, bridge.pool = store, QThreadPool()
        bridge._blocked_target = ("s", job.job_id, job.state_version, "resource")
        bridge._preparation_action = None
        bridge._tasks = set()
        bridge.busy = bridge._shutting_down = False
        error = StateConflict(code)
        error.outcome_known = known

        def refuse():
            raise error

        if code == "REMOTE_OUTCOME_UNKNOWN":
            # The explicit UNKNOWN code also wins over a contradictory DTO flag.
            bridge._show_preparation(
                NormalizedFailure(code, outcome_known=known), preserve_job=True
            )
        else:
            assert bridge.operation(refuse, continuing=True)
            _spin(app, lambda: not bridge.busy)
        assert "미확인" in bridge.panel.job_status.text()
        assert not bridge.panel.blocked_continue.isEnabled()
        assert bridge._blocked_target is None and store.get(job.job_id) == job
        bridge.pool.waitForDone()
        bridge.panel.deleteLater()


@pytest.mark.parametrize(
    "kind,action",
    list(
        product(
            ("stt", "summary"),
            ("consent", "auth", "budget", "model", "resource", "price", "clock", "cost_history"),
        )
    ),
)
def test_real_privacy_navigation_only_moves_focus(app, kind, action):
    from PySide6.QtWidgets import QVBoxLayout

    from recoryn.ui.privacy import PrivacyPanel, _Controls

    class Forbidden:
        def __getattr__(self, name):
            pytest.fail("navigation touched authorization, ledger or vault: " + name)

    panel = PrivacyPanel.__new__(PrivacyPanel)
    QWidget.__init__(panel)
    panel.controls = {value: _Controls(value) for value in ("stt", "summary")}
    panel.consents = panel.ledger = panel.vault = Forbidden()
    layout = QVBoxLayout(panel)
    for controls in panel.controls.values():
        layout.addWidget(controls)
    panel.show()
    app.processEvents()
    controls = panel.controls[kind]
    before = (controls.scope.currentData(), controls.key.text(), controls.per_request.value())
    panel.focus_blocked_action(kind, action)
    app.processEvents()
    target = {
        "consent": controls.scope,
        "auth": controls.key,
        "budget": controls.per_request,
        "price": controls.quote_info,
        "clock": controls.reset_clock,
        "cost_history": controls.requests,
        "model": controls.model,
        "resource": controls.model,
    }[action]
    assert target.hasFocus()
    assert (
        controls.scope.currentData(),
        controls.key.text(),
        controls.per_request.value(),
    ) == before
    panel.deleteLater()


@pytest.mark.parametrize(
    "code,action,phrase",
    [
        ("COST_CLOCK_INVALID", "clock", "시계 기준"),
        ("COST_UNRESOLVED_EXPOSURE", "cost_history", "미정산"),
        ("COST_QUOTE_MISMATCH", "price", "가격·요청 상한 근거"),
    ],
)
def test_preparation_and_existing_job_show_the_same_specific_budget_action(
    app, code, action, phrase
):
    from recoryn.jobs.failures import NormalizedFailure

    with JobStore(Path(":memory:")) as store:
        job = store.create("summary", "fixed")
        job = store.block_pending(job.job_id, "BUDGET", code, expected_version=0)
        for status in (ai_status(job), ai_status(preparation=NormalizedFailure(code))):
            assert status.action_id == action and phrase in status.text
        assert store.get(job.job_id) == job


def test_local_reader_receipt_cannot_replace_retained_inference_process_ack(app):
    """A worker that does not exit keeps its owned lease held (G-P11b); only a later
    successful reap acknowledges it, never a logical Job reader receipt."""
    import threading

    from recoryn.domain import StateConflict
    from recoryn.models import ResourceRequest, ResourceScheduler
    from recoryn.providers import ProviderError

    class Worker:
        allow_close = False
        alive = True

        def close(self):
            if not self.allow_close:
                raise ProviderError("INFERENCE_ACK_PENDING")
            self.alive = False

        def is_live(self):
            return self.alive

    with JobStore(Path(":memory:")) as store:
        job = store.create("transcription", "same")
        job = store.block_pending(
            job.job_id, "RESOURCE", "INFERENCE_ACK_PENDING", expected_version=0
        )
        scheduler, worker = ResourceScheduler(), Worker()
        request = ResourceRequest("stt", "LOCAL_CT2", "CPU_ONLY")
        with pytest.raises(StateConflict, match="^INFERENCE_ACK_PENDING$"):
            with scheduler.lease(request, cancel=threading.Event(), job_id=job.job_id) as lease:
                lease.open(lambda plan: worker)
        assert scheduler.held() == (job.job_id,)
        bridge = DesktopAI.__new__(DesktopAI)
        bridge._local_generation = None
        bridge._gpu_failed = None
        bridge.busy = False
        bridge.service = SimpleNamespace(
            scheduler=scheduler,
            runner=SimpleNamespace(snapshot=lambda: {"active": (), "pending": 0}),
        )
        status = ai_status(
            job, reader_active=False, resource_acknowledged=bridge._resource_acknowledged(job)
        )
        assert not status.can_continue and "종료 ACK" in status.text
        with pytest.raises(ProviderError, match="INFERENCE_ACK_PENDING"):
            bridge.release_gpu_runtime()
        assert scheduler.held() == (job.job_id,) and not bridge._resource_acknowledged(job)
        worker.allow_close = True
        bridge.release_gpu_runtime()
        assert scheduler.held() == () and bridge._resource_acknowledged(job)
        assert ai_status(job, reader_active=False, resource_acknowledged=True).can_continue
        assert store.get(job.job_id) == job


@pytest.mark.parametrize(
    "cancel,count,reader,phrase",
    [
        (True, 1, False, "취소 요청됨"),
        (False, 3, False, "시도 한도 소진"),
        (False, 1, True, "종료 ACK"),
    ],
)
def test_disabled_continue_has_an_explicit_reason(app, cancel, count, reader, phrase):
    with JobStore(Path(":memory:")) as store:
        job = store.create("stt", "same")
        job = store.block_pending(job.job_id, "RESOURCE", "OOM", expected_version=0)
        status = ai_status(
            replace(job, cancel_requested=cancel, attempt_count=count), reader_active=reader
        )
        assert not status.can_continue and phrase in status.text


def test_execution_policy_navigation_only_focuses_existing_control(app):
    from PySide6.QtWidgets import QVBoxLayout

    from recoryn.app.status import EXECUTION_POLICY_ACTION
    from recoryn.jobs.failures import CODE_GROUPS, NormalizedFailure

    status = ai_status(preparation=NormalizedFailure("RESOURCE_GPU_UNAVAILABLE"))
    assert status.action_id == EXECUTION_POLICY_ACTION == "execution_policy"
    assert "SUMMARY_PARTIAL" not in CODE_GROUPS
    tabs, page, other = QTabWidget(), QWidget(), QWidget()
    layout = QVBoxLayout(page)
    policy = QComboBox(page)
    policy.addItems(["GPU_ONLY", "CPU_ONLY", "GPU_WITH_CPU_FALLBACK_ALLOWED"])
    layout.addWidget(policy)
    tabs.addTab(page, "existing settings")
    tabs.addTab(other, "other")
    tabs.setCurrentWidget(other)
    tabs.show()
    app.processEvents()
    bridge = DesktopAI.__new__(DesktopAI)
    bridge.window = SimpleNamespace(selected_session=lambda: "s", tabs=tabs, device_policy=policy)
    bridge._blocked_target = None
    bridge._preparation_action = ("s", "stt", EXECUTION_POLICY_ACTION)
    bridge.open_blocked_action()
    app.processEvents()
    assert tabs.currentWidget() is page and policy.hasFocus()
    assert policy.currentText() == "GPU_ONLY"
    tabs.deleteLater()
