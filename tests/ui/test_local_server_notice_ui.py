"""L72: default/custom server boundaries, real timer ticks and user intent invalidation."""

from __future__ import annotations

import itertools
import time
from typing import Any

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from recoryn.providers import LocalModelAttestation, parse_observation
from recoryn.security import SecurityError
from tests.property.test_provider_facts_case_space import execution_audit as execution_audit
from tests.ui.test_provider_facts_ui import facts_world as facts_world
from tests.ui.test_provider_facts_ui import focus, select
from tests.unit.test_provider_facts import EXECUTED, body, descriptor, no_io

pytestmark = pytest.mark.ui
L_CASES = [
    pytest.param(f"GS04-L-{n:03d}", *row, id=f"GS04-L-{n:03d}")
    for n, row in enumerate(
        itertools.product(range(12), range(2), ("UNKNOWN", "DECLARED", "OBSERVED")), 1
    )
]


@pytest.mark.parametrize("case_id,profile,phase,evidence", L_CASES)
def test_server_notice_and_facts(
    case_id: str,
    profile: int,
    phase: int,
    evidence: str,
    facts_world: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    EXECUTED.append(case_id)
    world = facts_world
    calls = no_io(monkeypatch)
    announced: list[str] = []
    monkeypatch.setattr("recoryn.ui.a11y.qt_announce", lambda w, text, p: announced.append(text))
    provider, kind, endpoint = (
        ("ollama", "summary", "http://127.0.0.1:12345/fixture"),
        ("ollama", "summary", "http://127.0.0.1:23456/fixture"),
        ("ollama", "summary", "http://[::1]:23456/fixture"),
        ("ollama", "summary", "http://127.0.0.1:23456/fixture"),
        ("ollama", "summary", "https://custom.invalid/fixture"),
        ("openai", "summary", "https://api.openai.com/v1/responses"),
        ("anthropic", "summary", "https://api.anthropic.com/v1/messages"),
        ("openai", "summary", "http://127.0.0.1:1234/v1/chat/completions"),
        ("openai", "stt", "http://127.0.0.1:8000/v1/audio/transcriptions"),
        ("gemini", "summary", "https://llm-gateway.example.com/v1beta/models/x:generateContent"),
        ("anthropic", "summary", "https://proxy.example.com/v1/messages"),
        (
            "gemini",
            "summary",
            "https://generativelanguage.googleapis.com/v1beta/models/chosen:generateContent",
        ),
    )[profile]
    world.panel._attestation = None
    control = select(world, provider, endpoint, kind=kind)
    world.panel._facts_timer.setInterval(10)  # interval change never starts an inactive timer
    if profile == 3:
        control.model.setText("fixture:cloud")
    if profile == 0:
        world.panel.set_local_attestation(
            LocalModelAttestation(endpoint, "chosen", "a" * 64, True, time.monotonic() + 60)
        )
    key = world.panel.provider_identity(kind)
    if evidence == "OBSERVED":
        world.states[kind].accept(
            key, parse_observation(body(), descriptor(), key.model), observed_at=1700000000
        )
    world.panel.refresh_provider_facts(kind)
    focus(world, control.model)
    QTest.keyClick(control.model, Qt.Key.Key_Tab)
    world.app.processEvents()
    assert control.fact_declaration.hasFocus()
    if phase:
        focus(world, control.scope)  # scope preview only; no grant activation
        QTest.keyClick(control.scope, Qt.Key.Key_Down)
        QTest.keyClick(control.scope, Qt.Key.Key_Up)
        world.app.processEvents()
    visible = profile in (0, 1, 2, 3, 4, 7, 8, 9, 10)
    assert control.server_trust.isVisible() is visible
    if visible:
        for literal in (
            "후속 전송",
            "실제 추론 위치",
            "원격 주소·redirect·proxy",
        ):
            assert literal in control.server_trust.text()
    if profile < 5:
        assert "cloud 모델" in control.server_trust.text()
        assert "목록 응답은 로컬 추론·외부 무전송의 증거가 아닙니다" in control.server_trust.text()
        if profile == 0:
            assert "앱 소유 서버 증명과 모델 실행 조건은 별도 확인" in control.server_trust.text()
        else:
            with pytest.raises(SecurityError, match="LOCAL_EXECUTION_UNVERIFIED"):
                world.panel.provider_config("summary")
    else:
        assert "Ollama" not in control.server_trust.text()
        assert "cloud 모델" not in control.server_trust.text()
    assert control.fact_declaration.text() == (
        "기능 선언: 전사 지원 · adapter 선언, 실제 서비스 미검증"
        if kind == "stt"
        else "기능 선언: 요약 지원 · adapter 선언, 실제 서비스 미검증"
    )
    if evidence == "OBSERVED":
        assert "최근 관측:" in control.fact_observation.text()
        assert "인증·실행 보장 아님" in control.fact_observation.text()
        if profile == 3:
            assert (
                "선택한 모델이 목록에 없었습니다 · 기능 미지원 판정 아님"
                in control.fact_observation.text()
            )
    else:
        assert (
            control.fact_observation.text()
            == "최근 관측 없음 · 이 버전은 제공업체에 확인 요청을 보내지 않습니다"
        )
    count = len(announced)
    world.panel._refresh_fact_views()
    world.panel._refresh_fact_views()
    assert len(announced) == count
    if case_id == "GS04-L-003":

        def inject() -> None:
            world.clock[0] = 1000.0
            current = world.panel.provider_identity(kind)
            world.states[kind].bind(current)
            world.states[kind].accept(
                current,
                parse_observation(body(), descriptor(), current.model),
                observed_at=1700000000,
            )
            world.panel.refresh_provider_facts(kind)
            assert control.fact_observation.text().startswith("최근 관측:")

        focus(world, control.context_window)
        QTest.keyClick(control.context_window, Qt.Key.Key_Up)
        world.app.processEvents()
        assert control.fact_observation.text().startswith("최근 관측 없음")
        world.panel.consents.bind_session("gs04-session")
        writes: list[object] = []
        deletes: list[object] = []
        monkeypatch.setattr(world.backend, "write", lambda *args: writes.append(args))
        monkeypatch.setattr(world.backend, "delete", lambda *args: deletes.append(args))
        for action, button in (
            ("grant", control.allow),
            ("revoke", control.revoke),
            ("save", control.save_key),
            ("delete", control.delete_key),
        ):
            inject()
            if action == "save":
                focus(world, control.key)
                QTest.keyClicks(control.key, "GS04-fake-key")
            focus(world, button)
            QTest.keyClick(button, Qt.Key.Key_Space)
            world.app.processEvents()
            assert control.fact_observation.text().startswith("최근 관측 없음"), action
            if action == "grant":
                assert "동의 활성" in control.status.text()
        assert len(writes) == len(deletes) == 1
        inject()
    if evidence == "OBSERVED":
        world.clock[0] += 300
        deadline = time.monotonic() + 1
        while (
            not control.fact_observation.text().startswith("관측 만료")
            and time.monotonic() < deadline
        ):
            QTest.qWait(5)
        assert (
            control.fact_observation.text()
            == "관측 만료 · 이 버전은 제공업체에 확인 요청을 보내지 않습니다"
        )
        control.model.setText("new-model")
        assert "최근 관측 없음" in control.fact_observation.text()
    if profile == 7:
        world.panel._attestation = LocalModelAttestation(
            endpoint, "chosen", "a" * 64, True, time.monotonic() + 60
        )
        world.panel.refresh_provider_facts(kind)
        assert "앱 소유 서버" not in control.server_trust.text()
        control.endpoint.setText("http://[::1]:1234/v1/chat/completions")
        assert control.server_trust.isVisible() and "Ollama" not in control.server_trust.text()
    if profile in (5, 6, 11):
        control.endpoint.clear()
        assert not control.server_trust.isVisible()
    if profile == 11:
        control.model.setText("alternate.model-2")
        control.endpoint.setText(
            "https://generativelanguage.googleapis.com/v1beta/models/alternate.model-2:generateContent"
        )
        assert not control.server_trust.isVisible()
        control.model.setText("changed-again")
        assert control.server_trust.isVisible()
        control.endpoint.setText("invalid URL")
        assert control.server_trust.isVisible()
    assert calls == [] and world.backend.reads == 0
