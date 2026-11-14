from __future__ import annotations

import os
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from recoryn.domain import StateConflict
from recoryn.providers import LocalModelAttestation
from recoryn.ui.models import ModelPanel

pytestmark = pytest.mark.ui


def settle(app, panel):
    deadline = time.monotonic() + 5
    while (
        panel.task is not None or panel._attestation_task is not None
    ) and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.001)
    app.processEvents()
    assert panel.task is None
    assert panel._attestation_task is None


def test_owned_helper_is_explicit_and_invalidates_proof_before_stop(tmp_path: Path, monkeypatch):
    from recoryn.models import ollama

    app = QApplication.instance() or QApplication([])
    calls = []
    instances = []
    proof = LocalModelAttestation(
        "http://127.0.0.1:12345/api/chat", "fake:local", "a" * 64, True, time.monotonic() + 60
    )

    class FakeOwned:
        alive = True

        def __init__(self):
            instances.append(self)

        def start(self, executable, models, model, *, cancel=None):
            calls.append((executable, models, model))
            return proof

        def attestation(self):
            if not self.alive:
                raise StateConflict("OLLAMA_OWNED_SERVER_NOT_RUNNING")
            return proof

        def close(self):
            # Proof was revoked on the GUI thread before close entered a worker.
            assert seen[-1] is None
            self.alive = False

    monkeypatch.setattr(ollama, "ManagedOllama", FakeOwned)
    panel = ModelPanel(tmp_path / "models")
    seen = []
    panel.attestationChanged.connect(seen.append)
    try:
        assert calls == [] and not panel.ollama_owned
        panel.ollama_executable.setText(str(tmp_path / "fake.exe"))
        panel.ollama_models.setText(str(tmp_path / "local-models"))
        panel.ollama_model.setText("fake:local")
        panel.start_ollama()
        assert calls == []  # explicit server approval is separate from download approval
        panel.ollama_approval.setChecked(True)
        panel.start_ollama()
        settle(app, panel)
        assert len(calls) == 1 and seen == [None, proof]
        assert panel.checked_attestation() == proof
        assert seen == [None, proof]  # reading the GUI snapshot never queries or revokes
        panel.stop_ollama()
        assert seen[-1] is None
        settle(app, panel)
        assert not panel.ollama_owned
        assert not instances[0].alive
    finally:
        panel.shutdown()
        panel.close()
        panel.deleteLater()
        app.processEvents()


def test_stale_helper_getter_revokes_proof_and_never_reuses_it(tmp_path: Path):
    app = QApplication.instance() or QApplication([])
    panel = ModelPanel(tmp_path / "models")
    seen = []
    panel.attestationChanged.connect(seen.append)

    class DeadOwned:
        def attestation(self):
            raise StateConflict("OLLAMA_OWNED_SERVER_NOT_RUNNING")

        def close(self):
            pass

    panel.ollama = DeadOwned()
    panel._ollama_proof = object()
    try:
        with pytest.raises(StateConflict):
            panel.checked_attestation()
        settle(app, panel)
        assert seen == [None] and panel._ollama_proof is None
        with pytest.raises(StateConflict):
            panel.checked_attestation()
        assert seen == [None]
    finally:
        panel.shutdown()
        panel.close()
        panel.deleteLater()
        app.processEvents()


def test_gui_getter_does_not_wait_for_owned_helper_preparation(tmp_path: Path, monkeypatch):
    from recoryn.models import ollama

    app = QApplication.instance() or QApplication([])
    entered, release = threading.Event(), threading.Event()
    proof = LocalModelAttestation(
        "http://127.0.0.1:12345/api/chat", "fake:local", "a" * 64, True, time.monotonic() + 60
    )
    calls = []

    class PreparingOwned:
        def start(self, *args, **kwargs):
            entered.set()
            assert release.wait(5)
            return proof

        def attestation(self):
            calls.append("getter")
            assert release.is_set(), "GUI attempted a potentially blocking helper getter"
            return proof

        def close(self):
            pass

    monkeypatch.setattr(ollama, "ManagedOllama", PreparingOwned)
    panel = ModelPanel(tmp_path / "models")
    panel.ollama_executable.setText(str(tmp_path / "fake.exe"))
    panel.ollama_models.setText(str(tmp_path / "models"))
    panel.ollama_model.setText("fake:local")
    panel.ollama_approval.setChecked(True)
    try:
        panel.start_ollama()
        assert entered.wait(3)
        with pytest.raises(StateConflict):
            panel.checked_attestation()
        assert calls == [] and panel.task is not None
    finally:
        release.set()
        settle(app, panel)
        panel.shutdown()
        panel.close()
        panel.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("race", ["stop", "replace", "shutdown"])
def test_attestation_poll_is_coalesced_and_late_reply_cannot_restore_retired_owner(
    tmp_path: Path, race: str
):
    from concurrent.futures import ThreadPoolExecutor

    from PySide6.QtCore import QTimer

    app = QApplication.instance() or QApplication([])
    panel = ModelPanel(tmp_path / "models")
    entered, release, heartbeat = threading.Event(), threading.Event(), threading.Event()
    proof = LocalModelAttestation(
        "http://127.0.0.1:12345/api/chat", "old:local", "a" * 64, True, time.monotonic() + 60
    )
    newer = LocalModelAttestation(
        "http://127.0.0.1:23456/api/chat", "new:local", "b" * 64, True, time.monotonic() + 60
    )
    calls = []

    class BlockedOwner:
        def attestation(self):
            calls.append(threading.get_ident())
            entered.set()
            assert release.wait(5)
            return proof

        def close(self):
            pass

    class Replacement:
        def attestation(self):
            return newer

        def close(self):
            pass

    panel.ollama = BlockedOwner()
    panel._accept_proof(proof, panel._ollama_generation)
    seen = []
    panel.attestationChanged.connect(seen.append)
    executor = ThreadPoolExecutor(max_workers=1)
    future = None
    try:
        panel.request_attestation_check()
        assert entered.wait(3)
        pending = panel._attestation_task
        for _ in range(20):
            panel.request_attestation_check()
            assert panel.checked_attestation() is proof
        assert panel._attestation_task is pending and len(calls) == 1
        assert calls[0] != threading.get_ident()
        QTimer.singleShot(0, heartbeat.set)
        app.processEvents()
        assert heartbeat.is_set()  # model worker remains blocked throughout
        if race == "stop":
            panel.stop_ollama()
        elif race == "replace":
            # A replacement is already selected while an old queued GUI result
            # is pending. Its immutable proof must survive that old completion.
            panel._invalidate_owned_proof()
            panel.ollama = Replacement()
            panel._accept_proof(newer, panel._ollama_generation)
        else:
            future = executor.submit(panel.shutdown)
            deadline = time.monotonic() + 3
            while not panel._shutdown_requested and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.001)
            assert panel._shutdown_requested
        release.set()
        if future is not None:
            future.result(timeout=3)
        settle(app, panel)
        assert proof not in seen
        if race == "replace":
            assert panel.checked_attestation() is newer
            assert seen == [None, newer]
        else:
            assert panel._ollama_proof is None
            assert all(value is None for value in seen)
    finally:
        release.set()
        executor.shutdown(wait=True)
        panel.shutdown()
        panel.close()
        panel.deleteLater()
        app.processEvents()
