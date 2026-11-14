"""Managed local runtime contracts, using synthetic artifacts and owned children."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import socket
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any

import pytest

from recoryn.domain import StateConflict, ValidationError
from recoryn.models import ollama
from recoryn.models._owned import OwnedServer, listener_matches
from recoryn.providers import LocalModelAttestation, ProviderError


def model_fixture(root: Path) -> Path:
    records = []
    for payload, kind in ((b"{}", "config"), (b"synthetic fixture", "model")):
        sha = hashlib.sha256(payload).hexdigest()
        path = root / "blobs" / ("sha256-" + sha)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        records.append(
            {
                "digest": "sha256:" + sha,
                "size": len(payload),
                "mediaType": "application/vnd.ollama.image." + kind,
            }
        )
    manifest = root / "manifests/registry.ollama.ai/library/synthetic/local"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps({"schemaVersion": 2, "config": records[0], "layers": records[1:]}),
        encoding="utf-8",
    )
    return manifest


class FakeServer:
    pid = 123
    job_handle = 456

    def __init__(self) -> None:
        self.alive = True
        self.ready = True
        self.close_failure = False

    def poll(self) -> int | None:
        return None if self.alive else 1

    def close(self) -> None:
        if self.close_failure:
            raise StateConflict("OLLAMA_STOP_ACK_PENDING")
        self.alive = False


@pytest.fixture
def runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, ...]:
    executable = tmp_path / "never-run.exe"
    executable.write_bytes(b"fixture")
    models = tmp_path / "models"
    manifest = model_fixture(models)
    server = FakeServer()
    launched: list[dict[str, str]] = []

    def launch(path: Path, environment: dict[str, str]) -> FakeServer:
        assert path == executable
        launched.append(environment)
        return server

    monkeypatch.setattr(ollama, "OwnedServer", launch)
    monkeypatch.setattr(ollama, "listener_matches", lambda pid, port, **kwargs: server.ready)
    return executable, models, manifest, server, launched


@pytest.mark.parametrize("value", [True, 0, -1, float("nan"), float("inf"), 61])
def test_startup_timeout_must_be_bounded(value: Any) -> None:
    with pytest.raises(ValidationError):
        ollama.ManagedOllama(startup_timeout=value)


@pytest.mark.parametrize("failure", ["exit", "listener", "cancel"])
def test_no_proof_before_readiness(runtime: tuple[Any, ...], failure: str) -> None:
    exe, models, _, server, launched = runtime
    cancel = threading.Event()
    if failure == "exit":
        server.alive = False
    if failure == "listener":
        server.ready = False
    if failure == "cancel":
        cancel.set()
    owner = ollama.ManagedOllama(startup_timeout=0.01)
    with pytest.raises(StateConflict):
        owner.start(exe, models, "synthetic:local", cancel=cancel)
    assert owner.process is None
    assert len(launched) == (0 if failure == "cancel" else 1)
    with pytest.raises(StateConflict):
        owner.attestation()


@pytest.mark.parametrize("mutation", ["close", "exit", "listener", "manifest", "blob", "exe"])
def test_frozen_proof_has_live_owner_and_file_binding(
    runtime: tuple[Any, ...], mutation: str
) -> None:
    exe, models, manifest, server, launched = runtime
    owner = ollama.ManagedOllama()
    proof = owner.start(exe, models, "synthetic:local")
    assert launched[0]["OLLAMA_NO_CLOUD"] == "1"
    with proof.execution_guard():
        pass
    if mutation == "close":
        owner.close()
    elif mutation == "exit":
        server.alive = False
    elif mutation == "listener":
        server.ready = False
    else:
        target = {"manifest": manifest, "blob": next((models / "blobs").iterdir()), "exe": exe}[
            mutation
        ]
        target.write_bytes(b"changed fixture")
    with pytest.raises(ProviderError, match="LOCAL_EXECUTION_UNVERIFIED"):
        with proof.execution_guard():
            pytest.fail("revoked proof admitted a handoff")
    owner.close()


def test_stale_generation_cannot_revoke_replacement(runtime: tuple[Any, ...]) -> None:
    exe, models, _, server, _ = runtime
    owner = ollama.ManagedOllama()
    first = owner.start(exe, models, "synthetic:local")
    owner.close()
    server.alive = True
    second = owner.start(exe, models, "synthetic:local")
    with pytest.raises(ProviderError):
        with first.execution_guard():
            pass
    assert owner.attestation() is second
    owner.close()


def test_cleanup_failure_revokes_proof_and_keeps_retry_handle(runtime: tuple[Any, ...]) -> None:
    exe, models, _, server, _ = runtime
    owner = ollama.ManagedOllama()
    proof = owner.start(exe, models, "synthetic:local")
    server.close_failure = True
    with pytest.raises(StateConflict):
        owner.close()
    assert owner.process is server
    with pytest.raises(ProviderError):
        with proof.execution_guard():
            pass
    server.close_failure = False
    owner.close()
    assert owner.process is None


def test_close_serializes_after_inflight_unit(runtime: tuple[Any, ...]) -> None:
    exe, models, _, _, _ = runtime
    owner = ollama.ManagedOllama()
    proof = owner.start(exe, models, "synthetic:local")
    entered, release, closing, closed = (threading.Event() for _ in range(4))

    def handoff() -> None:
        with proof.execution_guard():
            entered.set()
            assert release.wait(3)

    def stop() -> None:
        closing.set()
        owner.close()
        closed.set()

    writer = threading.Thread(target=handoff)
    writer.start()
    assert entered.wait(3)
    stopper = threading.Thread(target=stop)
    stopper.start()
    assert closing.wait(3)
    try:
        assert not closed.wait(0.02)
    finally:
        release.set()
        writer.join(3)
        stopper.join(3)
    assert closed.is_set()
    with pytest.raises(ProviderError):
        with proof.execution_guard():
            pass


def test_static_guard_preserves_errors_from_handoff() -> None:
    proof = LocalModelAttestation(
        "http://127.0.0.1:1/api/chat", "fixture", "a" * 64, True, time.monotonic() + 10
    )
    expected = OSError("owned synthetic error")
    with pytest.raises(OSError) as error:
        with proof.execution_guard():
            raise expected
    assert error.value is expected


def test_native_job_listener_and_descendant_ack(tmp_path: Path) -> None:
    if sys.platform != "win32":
        with pytest.raises(StateConflict, match="UNSUPPORTED"):
            OwnedServer(Path(sys.executable), dict(os.environ))
        return
    status = tmp_path / "owned.json"
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    script = (
        "import socket,subprocess,sys,time,json;from pathlib import Path;"
        "s=socket.socket();s.bind(('127.0.0.1',int(sys.argv[1])));s.listen();"
        "c=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
        "p=Path(sys.argv[2]+'.tmp');p.write_text(json.dumps({'pid':c.pid}));"
        "p.replace(sys.argv[2]);time.sleep(60)"
    )
    child = OwnedServer(
        Path(sys.executable), dict(os.environ), arguments=("-c", script, str(port), str(status))
    )
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    api.OpenProcess.restype = wintypes.HANDLE
    api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    api.WaitForSingleObject.restype = wintypes.DWORD
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.CloseHandle.restype = wintypes.BOOL
    handle = None
    try:
        deadline = time.monotonic() + 5
        while not status.exists() and time.monotonic() < deadline:
            threading.Event().wait(0.01)
        assert status.exists()
        assert listener_matches(child.pid, port, job=child.job_handle)
        assert not listener_matches(child.pid + 1, port)
        handle = api.OpenProcess(0x00100000, False, json.loads(status.read_bytes())["pid"])
        assert handle and api.WaitForSingleObject(handle, 0) == 0x102
        child.close()
        assert child.poll() is not None
        assert api.WaitForSingleObject(handle, 0) == 0
        assert not listener_matches(child.pid, port)
        child.close()
    finally:
        child.close()
        if handle:
            api.CloseHandle(handle)
