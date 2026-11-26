"""P20 and shared offscreen fixture: no credential, DNS or socket access."""

from __future__ import annotations

import itertools
import json
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QTabWidget

from recoryn.providers import ObservationOutcome, ObservationState, parse_observation
from recoryn.security import ConsentStore, CostLedger, CredentialVault
from recoryn.ui.privacy import PrivacyPanel
from tests.property.test_provider_facts_case_space import execution_audit as execution_audit
from tests.ui.test_secret_lifetime_ui import close_privacy, settle_privacy
from tests.unit.test_provider_facts import EXECUTED, descriptor, no_io

pytestmark = pytest.mark.ui
P_CASES = [
    pytest.param(f"GS04-P-{n:03d}", *row, id=f"GS04-P-{n:03d}")
    for n, row in enumerate(itertools.product(range(5), range(4)), 1)
]


class Vault:
    def __init__(self) -> None:
        self.reads = 0

    def read(self, target: str) -> None:
        self.reads += 1

    def write(self, *args: Any) -> None:
        raise AssertionError("vault writes are outside GS04a")

    def delete(self, *args: Any) -> None:
        raise AssertionError("vault writes are outside GS04a")


@pytest.fixture(scope="module")
def facts_world(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Any]:
    app = QApplication.instance() or QApplication([])
    root = tmp_path_factory.mktemp("gs04-facts-ui")
    backend = Vault()
    clock = [1000.0]
    states = {k: ObservationState(clock=lambda: clock[0]) for k in ("stt", "summary")}
    (root / "settings.json").write_text('{"execution_policy":"CPU_ONLY"}')
    (root / "support.txt").write_text("safe support fixture")
    with ConsentStore(root / "db.sqlite") as consents, CostLedger(root / "db.sqlite") as ledger:
        panel = PrivacyPanel(
            consents,
            ledger,
            CredentialVault(backend=backend, namespace="GS04-test"),
            provider_facts=states,
        )
        panel.select_session("gs04-session")
        panel.resize(900, 1100)
        panel.show()
        panel.activateWindow()
        app.processEvents()
        yield SimpleNamespace(
            app=app, panel=panel, root=root, backend=backend, clock=clock, states=states
        )
        close_privacy(panel)
        panel.deleteLater()
        app.processEvents()


def select(
    world: Any,
    provider: str = "ollama",
    endpoint: str = "http://127.0.0.1:12345/fixture",
    *,
    kind: str = "summary",
) -> Any:
    panel = world.panel
    panel.findChild(QTabWidget).setCurrentIndex(0 if kind == "stt" else 1)
    control = panel.controls[kind]
    control.provider.setCurrentIndex(control.provider.findData(provider))
    control.endpoint.setText(endpoint)
    control.model.setText("chosen")
    world.states[kind].invalidate()
    panel.refresh_provider_facts(kind)
    world.clock[0] = 1000.0
    return control


def focus(world: Any, widget: Any) -> None:
    world.panel.activateWindow()
    widget.setFocus()
    world.app.processEvents()
    assert widget.hasFocus() and QApplication.activeWindow() is world.panel


@pytest.mark.parametrize("case_id,canary_kind,surface", P_CASES)
def test_fake_inputs_leave_no_private_material(
    case_id: str,
    canary_kind: int,
    surface: int,
    facts_world: Any,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    EXECUTED.append(case_id)
    world = facts_world
    calls = no_io(monkeypatch)
    control = select(world)
    canary = f"GS04-private-{canary_kind}"
    raw = json.dumps({"all": True, "items": [{"name": "chosen"}], "echo": canary}).encode()
    kwargs: dict[str, Any] = {}
    if canary_kind == 0:
        raw = canary.encode()  # invalid raw response bytes
    elif canary_kind == 1:
        kwargs = {"raw_error": canary, "outcome": ObservationOutcome.TRANSPORT_FAILED}
    elif canary_kind == 2:
        kwargs = {
            "redirect_url": "https://denied.invalid/" + canary,
            "outcome": ObservationOutcome.UNSUPPORTED,
        }
    elif canary_kind == 3:
        raw = json.dumps({"all": True, "items": [{"name": "chosen"}, {"name": canary}]}).encode()
    else:
        raw = json.dumps(
            {
                "all": True,
                "items": [{"name": "chosen"}],
                "authentication": canary,
                "audio": canary,
                "transcript": canary,
            }
        ).encode()
    settle_privacy(world.panel)
    before = {p.name: p.read_bytes() for p in world.root.iterdir() if p.is_file()}
    observed = parse_observation(raw, descriptor(), "chosen", **kwargs)
    key = world.panel.provider_identity("summary")
    world.states["summary"].accept(key, observed, observed_at=1700000000)
    world.panel.refresh_provider_facts("summary")
    focus(world, control.model)
    QTest.keyClick(control.model, Qt.Key.Key_Tab)
    world.app.processEvents()
    assert control.fact_declaration.hasFocus()
    if surface == 0:
        material = (
            repr(observed)
            + repr(world.states["summary"].snapshot())
            + repr(vars(world.states["summary"]))
        )
    elif surface == 1:
        material = "\n".join(
            w.text() + w.accessibleName() + w.accessibleDescription()
            for w in world.panel.findChildren(QLabel)
        )
    elif surface == 2:
        material = caplog.text
    else:
        settle_privacy(world.panel)
        after = {p.name: p.read_bytes() for p in world.root.iterdir() if p.is_file()}
        assert before == after
        material = repr(after)
    assert canary not in material
    assert calls == [] and world.backend.reads == 0
    assert not any("관측 요청" in b.text() for b in world.panel.findChildren(QPushButton))
    assert "확인 요청을 보내지 않습니다" in control.fact_observation.text() or (
        "인증·실행 보장 아님" in control.fact_observation.text()
    )
