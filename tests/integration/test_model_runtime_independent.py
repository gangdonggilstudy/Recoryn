"""BR30 model/runtime oracles: synthetic artifacts, fakes, owned children only."""

from __future__ import annotations

import ctypes
import hashlib
import http.client
import json
import multiprocessing
import os
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from ctypes import wintypes
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from recoryn.app import inference
from recoryn.app.inference import LocalSTTProcess
from recoryn.domain import StateConflict, ValidationError
from recoryn.models import FileSpec, ModelManager, ModelSpec
from recoryn.models import manager as model_manager
from recoryn.providers import ExecutionContext, ProviderError, STTRequest

pytestmark = pytest.mark.integration
PAYLOAD = b"BR30 synthetic artifact; not executable model weights"


def model_spec() -> ModelSpec:
    return ModelSpec(
        "test-model",
        "whisper",
        "MIT",
        "https://models.example.test/LICENSE",
        (
            FileSpec(
                "model.bin",
                "https://models.example.test/model.bin",
                len(PAYLOAD),
                hashlib.sha256(PAYLOAD).hexdigest(),
            ),
        ),
    )


def complete_download(url: str, offset: int) -> Iterator[bytes]:
    yield PAYLOAD[offset:]


@pytest.mark.parametrize("stage", ("partial", "installed"))
def test_manifest_unlisted_artifact_cannot_be_activated_or_verified(
    tmp_path: Path,
    stage: str,
) -> None:
    manager = ModelManager(tmp_path / "models", downloader=complete_download)
    if stage == "partial":
        partial = manager.root / ".partial-test-model" / "files"
        partial.mkdir(parents=True)
        (partial / "preprocessor_config.json").write_text(
            '{"unverified":"BR30-CANARY"}', encoding="utf-8"
        )
        try:
            installed = manager.install(model_spec(), approved=True)
        except (ValidationError, StateConflict):
            assert not (manager.root / "test-model").exists()
        else:
            assert not (installed / "preprocessor_config.json").exists()
    else:
        installed = manager.install(model_spec(), approved=True)
        (installed / "preprocessor_config.json").write_text(
            '{"unverified":"BR30-CANARY"}', encoding="utf-8"
        )
        with pytest.raises((ValidationError, StateConflict)):
            manager.verify("test-model")


@pytest.mark.parametrize("damage", ("future", "missing", "bool", "extra"))
def test_unknown_installed_manifest_version_fails_closed(tmp_path: Path, damage: str) -> None:
    manager = ModelManager(tmp_path / "models", downloader=complete_download)
    installed = manager.install(model_spec(), approved=True)
    receipt = installed / "installed.json"
    value = json.loads(receipt.read_bytes())
    if damage == "missing":
        value.pop("schema_version")
    elif damage == "extra":
        value["unknown_versioned_contract"] = 1
    else:
        value["schema_version"] = True if damage == "bool" else 99
    receipt.write_text(json.dumps(value), encoding="utf-8")
    before = receipt.read_bytes()
    with pytest.raises(ValidationError):
        manager.verify("test-model")
    assert receipt.read_bytes() == before


def test_license_approval_and_cancel_at_complete_boundary_never_activate(tmp_path: Path) -> None:
    calls: list[int] = []

    def download(url: str, offset: int) -> Iterator[bytes]:
        calls.append(offset)
        yield PAYLOAD[offset:]

    cancel = threading.Event()
    manager = ModelManager(tmp_path / "models", downloader=download)
    with pytest.raises(ValidationError, match="APPROVAL"):
        manager.install(model_spec())
    assert not calls and not manager.root.exists()

    def progress(completed: int, total: int) -> None:
        if completed == total:
            cancel.set()

    with pytest.raises(StateConflict, match="CANCELLED"):
        manager.install(model_spec(), approved=True, cancel=cancel, progress=progress)
    assert not (manager.root / "test-model").exists()
    cancel.clear()
    installed = manager.install(model_spec(), approved=True, cancel=cancel)
    assert calls == [0]  # A fully received prefix is verified, never fetched twice.
    assert (installed / "model.bin").read_bytes() == PAYLOAD


@pytest.mark.parametrize("change", ("license", "source", "hash"))
def test_partial_resume_requires_exact_approved_plan(tmp_path: Path, change: str) -> None:
    calls: list[int] = []

    def download(url: str, offset: int) -> Iterator[bytes]:
        calls.append(offset)
        yield PAYLOAD[:3]
        raise OSError("controlled download interruption")

    manager = ModelManager(tmp_path / "models", downloader=download)
    original = model_spec()
    with pytest.raises(OSError):
        manager.install(original, approved=True)
    if change == "license":
        changed = replace(original, license_id="Apache-2.0")
    else:
        changed_file = (
            replace(original.files[0], url="https://other.example.test/model.bin")
            if change == "source"
            else replace(original.files[0], sha256="0" * 64)
        )
        changed = replace(original, files=(changed_file,))
    with pytest.raises(StateConflict, match="PLAN_MISMATCH"):
        manager.install(changed, approved=True)
    assert calls == [0] and not (manager.root / "test-model").exists()


@pytest.mark.parametrize("timeout", (float("nan"), float("inf"), True))
def test_local_process_requires_finite_numeric_deadline(tmp_path: Path, timeout: float) -> None:
    with pytest.raises(ProviderError, match="INPUT_INVALID"):
        LocalSTTProcess(tmp_path / "not-a-model", timeout=timeout)


def _hanging_owned_worker(model_path: str, device: str, requests: Any, replies: Any) -> None:
    """No model import or I/O except this test's synthetic readiness receipt."""
    requests.get()
    ready = Path(model_path + ".ready")
    staging = ready.with_name(ready.name + ".tmp")
    staging.write_text(str(os.getpid()), encoding="ascii")
    staging.replace(ready)
    while True:
        time.sleep(0.1)


def _owned_supervisor(status: str) -> None:
    """Host an actual idle production worker; never submit an inference request."""
    provider = LocalSTTProcess(Path(status).parent / "no-model-loaded")
    provider._start()
    receipt = Path(status)
    staging = receipt.with_name(receipt.name + ".tmp")
    staging.write_text(json.dumps({"child_pid": provider._process.pid}), encoding="ascii")
    staging.replace(receipt)
    while True:
        time.sleep(0.1)


def _await_file(path: Path) -> None:
    deadline = time.monotonic() + 15
    while not path.exists() and time.monotonic() < deadline:
        threading.Event().wait(0.01)
    assert path.exists(), "owned test child did not announce readiness"


@contextmanager
def _owned_child_handle(pid: int) -> Iterator[tuple[Any, Any]]:
    """Open only the exact PID supplied by our still-running owned parent.

    https://learn.microsoft.com/windows/win32/api/processthreadsapi/nf-processthreadsapi-openprocess
    https://learn.microsoft.com/windows/win32/api/synchapi/nf-synchapi-waitforsingleobject
    https://learn.microsoft.com/windows/win32/api/processthreadsapi/nf-processthreadsapi-terminateprocess
    """
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    api.OpenProcess.restype = wintypes.HANDLE
    api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    api.WaitForSingleObject.restype = wintypes.DWORD
    api.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    api.TerminateProcess.restype = wintypes.BOOL
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.CloseHandle.restype = wintypes.BOOL
    # SYNCHRONIZE|PROCESS_TERMINATE. No name search, PID enumeration or privilege change.
    handle = api.OpenProcess(0x00100001, False, pid)
    assert handle, "cannot observe this test's owned process"
    try:
        yield api, handle
    finally:
        if api.WaitForSingleObject(handle, 0) == 0x102:
            assert api.TerminateProcess(handle, 98)
            assert api.WaitForSingleObject(handle, 5000) == 0
        assert api.CloseHandle(handle)


@pytest.mark.parametrize("reason", ("timeout", "cancel"))
def test_hung_owned_inference_child_exits_before_error_ack(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reason: str,
) -> None:
    monkeypatch.setattr(inference, "_worker", _hanging_owned_worker)
    model = tmp_path / "fake-model"
    provider = LocalSTTProcess(model, timeout=3)
    context = ExecutionContext()
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            result = executor.submit(
                provider.transcribe, STTRequest(tmp_path / "synthetic.wav"), context
            )
            ready = Path(str(model) + ".ready")
            _await_file(ready)
            pid = int(ready.read_text(encoding="ascii"))
            assert provider._process.pid == pid
            with _owned_child_handle(pid) as (api, handle):
                if reason == "cancel":
                    context.cancel.set()
                with pytest.raises(
                    ProviderError, match="TIMEOUT" if reason == "timeout" else "CANCELLED"
                ):
                    result.result(timeout=10)
                assert api.WaitForSingleObject(handle, 0) == 0
                assert provider._process is None
    finally:
        provider.close()


def test_parent_watch_retires_actual_owned_idle_worker_after_parent_death(tmp_path: Path) -> None:
    status = tmp_path / "owned-supervisor.json"
    parent = multiprocessing.get_context("spawn").Process(
        target=_owned_supervisor, args=(str(status),)
    )
    parent.start()
    try:
        _await_file(status)
        child_pid = json.loads(status.read_text(encoding="ascii"))["child_pid"]
        with _owned_child_handle(child_pid) as (api, handle):
            parent.terminate()  # Only this test's supervisor is terminated.
            parent.join(timeout=5)
            assert not parent.is_alive()
            assert api.WaitForSingleObject(handle, 10000) == 0
    finally:
        if parent.is_alive():
            parent.terminate()
            parent.join(timeout=5)
        parent.close()


@pytest.mark.parametrize(
    "case", ("full", "resume", "redirect", "ignored_range", "wrong_range", "gzip")
)
def test_default_download_transport_has_no_redirect_retry_or_implicit_proxy(
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    offset = 0 if case in {"full", "redirect"} else 4
    status = 302 if case == "redirect" else 200 if case in {"full", "ignored_range"} else 206
    requests: list[tuple[str, str, dict[str, str]]] = []
    closed: list[bool] = []
    origins: list[tuple[str, int | None, float]] = []

    class Response:
        def __init__(self) -> None:
            self.status = status
            self.body = b"synthetic bytes"

        def getheader(self, name: str, default: str | None = None) -> str | None:
            return {
                "Content-Range": "bytes 3-17/18" if case == "wrong_range" else "bytes 4-17/18",
                "Content-Encoding": "gzip" if case == "gzip" else "identity",
                "Location": "https://must-not-follow.example.test/",
            }.get(name, default)

        def read(self, count: int) -> bytes:
            value, self.body = self.body[:count], self.body[count:]
            return value

    class Connection:
        def __init__(self, host: str, port: int | None, timeout: float) -> None:
            origins.append((host, port, timeout))

        def request(self, method: str, path: str, *, headers: dict[str, str]) -> None:
            requests.append((method, path, headers))

        def getresponse(self) -> Response:
            return Response()

        def close(self) -> None:
            closed.append(True)

    monkeypatch.setattr(http.client, "HTTPSConnection", Connection)
    monkeypatch.setenv("HTTPS_PROXY", "http://must-not-use.example.test:3128")
    if case in {"full", "resume"}:
        assert list(model_manager._download("https://models.example.test/file", offset)) == [
            b"synthetic bytes"
        ]
    else:
        with pytest.raises(ValidationError):
            list(model_manager._download("https://models.example.test/file", offset))
    assert origins == [("models.example.test", None, 20)]
    assert len(requests) == 1 and requests[0][:2] == ("GET", "/file")
    assert requests[0][2].get("Range") == (f"bytes={offset}-" if offset else None)
    assert not any("authorization" in key.lower() for key in requests[0][2])
    assert closed == [True]
