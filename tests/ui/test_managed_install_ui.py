"""M36: actual manifest/approval/download/cancel keys on the real ModelPanel."""

from __future__ import annotations

import hashlib
import itertools
import json
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox, QFileDialog, QPushButton

from recoryn.domain import StateConflict
from recoryn.ui.models import ModelPanel
from tests.property.test_provider_facts_case_space import execution_audit as execution_audit
from tests.unit.test_provider_facts import EXECUTED, no_io

pytestmark = pytest.mark.ui
M_CASES = [
    pytest.param(f"GS04-M-{n:03d}", *row, id=f"GS04-M-{n:03d}")
    for n, row in enumerate(
        itertools.product(range(1, 10), ("whisper", "diarization"), ("mouse", "keyboard")), 1
    )
]


def spin(app: QApplication, predicate: Any) -> None:
    deadline = time.monotonic() + 8
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.001)
    app.processEvents()
    assert predicate()


def manifest(path: Path, kind: str, model: str) -> None:
    path.write_text(
        json.dumps(
            {
                "model_id": model,
                "kind": kind,
                "license_id": "TEST-ONLY",
                "license_url": "https://publisher.invalid/LICENSE",
                "files": [
                    {
                        "path": "one.bin",
                        "url": "https://publisher.invalid/one",
                        "size": 3,
                        "sha256": hashlib.sha256(b"one").hexdigest(),
                    },
                    {
                        "path": "two.bin",
                        "url": "https://publisher.invalid/two",
                        "size": 4,
                        "sha256": hashlib.sha256(b"two!").hexdigest(),
                    },
                ],
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.parametrize("case_id,trace,kind,method", M_CASES)
def test_managed_install_intent(
    case_id: str,
    trace: int,
    kind: str,
    method: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    EXECUTED.append(case_id)
    app = QApplication.instance() or QApplication([])
    calls = no_io(monkeypatch)
    panel = ModelPanel(tmp_path / "models")
    panel.resize(850, 1000)
    panel.show()
    panel.activateWindow()
    spin(app, lambda: panel.task is None)
    a, b, bad = (tmp_path / n for n in ("a.json", "b.json", "bad.json"))
    manifest(a, kind, "fixture-a")
    manifest(b, kind, "fixture-b")
    bad.write_text("{bad", encoding="utf-8")
    choices: list[str] = ["" if trace == 1 else str(a)]
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (choices.pop(0), "JSON"))
    choose = next(x for x in panel.findChildren(QPushButton) if "manifest 선택" in x.text())
    cancel = next(x for x in panel.findChildren(QPushButton) if "준비 취소" in x.text())
    installed: list[tuple[Any, Any, Any]] = []
    emitted: list[str] = []
    panel.modelSelected.connect(emitted.append)
    entered, release = threading.Event(), threading.Event()

    def activate(widget: Any) -> None:
        panel.activateWindow()
        widget.setFocus()
        app.processEvents()
        assert widget.hasFocus() and QApplication.activeWindow() is panel
        if method == "mouse":
            if isinstance(widget, QCheckBox):
                QTest.mouseClick(
                    widget, Qt.MouseButton.LeftButton, pos=QPoint(8, widget.height() // 2)
                )
            else:
                QTest.mouseClick(widget, Qt.MouseButton.LeftButton)
        else:
            QTest.keyClick(widget, Qt.Key.Key_Space)
        app.processEvents()

    def installer(plan: Any, *, approved: bool, cancel: Any, **kwargs: Any) -> Path:
        installed.append((plan, approved, cancel))
        if trace == 6:
            entered.set()
            assert release.wait(8)
            if cancel.is_set():
                raise StateConflict("MODEL_CANCELLED")
        return tmp_path / "models" / plan.model_id

    monkeypatch.setattr(panel.manager, "install", installer)
    try:
        activate(choose)
        shown = panel.plan
        if trace == 2:
            assert panel.approval.isChecked() is False
            assert panel.preview.toPlainText() == (
                f"모델: fixture-a\n종류: {kind}\n라이선스: TEST-ONLY\n"
                "https://publisher.invalid/LICENSE\n공간: 7 bytes\n"
                f"저장: {tmp_path / 'models' / 'fixture-a'}\n\n"
                f"one.bin\nhttps://publisher.invalid/one\nSHA256: {hashlib.sha256(b'one').hexdigest()}"
                f"\n\ntwo.bin\nhttps://publisher.invalid/two\nSHA256: {hashlib.sha256(b'two!').hexdigest()}"
            )
        elif trace in (1, 3):
            activate(panel.download_button)
            assert "다운로드 계획을 선택" in panel.status.text()
        elif trace == 4:
            activate(panel.approval)
            assert panel.approval.isChecked()
            activate(panel.approval)
            activate(panel.download_button)
            assert not panel.approval.isChecked()
        elif trace in (5, 9):
            activate(panel.approval)
            choices.append(str(b if trace == 5 else bad))
            activate(choose)
            activate(panel.download_button)
            assert not panel.approval.isChecked()
            if trace == 5:
                assert "fixture-b" in panel.preview.toPlainText()
            else:
                assert panel.plan is None
                assert panel.preview.toPlainText() in ("", "계획 없음")
                assert "다운로드 계획을 선택" in panel.status.text()
        elif trace in (6, 7):
            activate(panel.approval)
            assert not installed
            activate(panel.download_button)
            if trace == 6:
                spin(app, entered.is_set)
                activate(cancel)
                assert panel.cancel.is_set()
                release.set()
            spin(app, lambda: panel.task is None)
            assert len(installed) == 1
            assert installed[0][0] is shown and installed[0][1] is True
            assert installed[0][2] is panel.cancel
            assert (not panel.cancel.is_set()) is (trace == 7)
        else:
            activate(panel.approval)

            def busy() -> None:
                entered.set()
                assert release.wait(8)

            panel._run(busy, lambda _: None)
            spin(app, entered.is_set)
            original = panel.task
            choices.append(str(b))
            activate(choose)
            # Disabled controls cannot take focus: dispatch actual keys to the current button.
            QTest.keyClick(panel.download_button, Qt.Key.Key_Space)
            assert panel.plan is shown and panel.task is original and not panel.cancel.is_set()
            release.set()
            spin(app, lambda: panel.task is None)
        assert len(installed) == (1 if trace in (6, 7) else 0)
        assert len(emitted) == (1 if trace == 7 else 0)
        assert len(panel.confirmations) == 0 and calls == []
    finally:
        release.set()
        panel.shutdown()
        panel.close()
        panel.deleteLater()
        app.processEvents()
