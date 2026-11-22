"""Synthetic diarization contracts; never execute a real model or daemon."""

from __future__ import annotations

import ctypes
import hashlib
import importlib.metadata
import json
import multiprocessing
import socket
import sys
import threading
import time
import types
import wave
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest

from recoryn.diarization import (
    DiarizationConfig,
    DiarizationRequest,
    DiarizationResult,
    LocalDiarizationProcess,
    _job,
    process,
)
from recoryn.providers import ExecutionContext, ProviderError

pytestmark = pytest.mark.unit


def _observer() -> Any:
    from ctypes import wintypes

    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    api.OpenProcess.restype = wintypes.HANDLE
    api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    api.WaitForSingleObject.restype = wintypes.DWORD
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.CloseHandle.restype = wintypes.BOOL
    return api


class FakeJobAPI:
    def __init__(self, failure: str = "") -> None:
        self.failure = failure
        self.closed: list[int] = []
        self.limits: tuple[int, int, int] | None = None

    def CreateJobObjectW(self, *args: Any) -> int:
        return 0 if self.failure == "create" else 100

    def SetInformationJobObject(self, handle: int, kind: int, value: Any, size: int) -> bool:
        assert handle == 100 and kind == 9 and size == ctypes.sizeof(_job._Extended)
        data = ctypes.cast(value, ctypes.POINTER(_job._Extended)).contents
        self.limits = (
            data.BasicLimitInformation.LimitFlags,
            data.BasicLimitInformation.ActiveProcessLimit,
            data.ProcessMemoryLimit,
        )
        return self.failure != "set"

    def OpenProcess(self, access: int, inherit: bool, pid: int) -> int:
        assert access == 0x101 and inherit is False and pid == 123
        return 0 if self.failure == "open" else 200

    def AssignProcessToJobObject(self, job: int, process: int) -> bool:
        assert (job, process) == (100, 200)
        return self.failure != "assign"

    def CloseHandle(self, handle: int) -> bool:
        self.closed.append(handle)
        return self.failure != "close"


def test_guard_attaches_before_release_and_closes_owned_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = FakeJobAPI()
    monkeypatch.setattr(_job, "_api", lambda: api)
    guard = _job.ChildJob()
    assert api.closed == [] and api.limits is None
    guard.attach(123)
    assert api.limits == (0x2108, 1, 1024 * 1024 * 1024)
    assert api.closed == [200]  # process handle released, job stays with parent
    guard.close()
    guard.close()
    assert api.closed == [200, 100]


@pytest.mark.parametrize("stage", ["create", "set", "open", "assign"])
def test_failed_lifetime_guard_cannot_be_treated_as_ready(
    monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    api = FakeJobAPI(stage)
    monkeypatch.setattr(_job, "_api", lambda: api)
    guard = _job.ChildJob()
    with pytest.raises(ProviderError, match="DIARIZATION_GUARD_FAILED"):
        guard.attach(123)
    guard.close()
    assert api.closed == ([] if stage == "create" else [200, 100] if stage == "assign" else [100])


@pytest.mark.parametrize("pid", [True, 0, -1])
def test_invalid_guard_identity_has_no_platform_side_effect(pid: int) -> None:
    with pytest.raises(ProviderError, match="DIARIZATION_GUARD_INVALID"):
        _job.ChildJob().attach(pid)


def test_guard_close_failure_keeps_handle_for_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    api = FakeJobAPI()
    monkeypatch.setattr(_job, "_api", lambda: api)
    guard = _job.ChildJob()
    guard.attach(123)
    api.failure = "close"
    with pytest.raises(ProviderError, match="DIARIZATION_GUARD_CLOSE_FAILED"):
        guard.close()
    api.failure = ""
    guard.close()
    assert api.closed == [200, 100, 100]


def _synthetic(tmp_path: Path, timeout: float = 10) -> tuple[DiarizationConfig, DiarizationRequest]:
    audio = tmp_path / "derived.wav"
    with wave.open(str(audio), "wb") as stream:
        stream.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        stream.writeframes(b"\0\0" * 160)
    config = DiarizationConfig(
        tmp_path / "no-real-model.json", "a" * 64, True, timeout_seconds=timeout
    )
    return config, DiarizationRequest(audio)


def _hung_child(
    config: Any, request: Any, audio_hash: str, gate: Any, cancel: Any, reply: Any
) -> None:
    def denied(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("network forbidden")

    socket.__dict__["socket"] = denied
    socket.__dict__["getaddrinfo"] = denied
    if gate.wait(5):
        request.audio_path.with_suffix(".started").write_text("gated fake child", encoding="utf-8")
        threading.Event().wait(30)  # deliberately ignores cooperative cancellation
    reply.close()


def _slow_start_hung_child(
    config: Any, request: Any, audio_hash: str, gate: Any, cancel: Any, reply: Any
) -> None:
    # Start-up slower than the whole provider timeout, then hang like _hung_child.
    if gate.wait(5):
        time.sleep(2.0)
        request.audio_path.with_suffix(".started").write_text("slow child", encoding="utf-8")
        threading.Event().wait(30)
    reply.close()


class _MarkerClock:
    """Provider clock that starts only once the hung child has written its marker.

    Before the marker exists it stands still at 0, so start-up time never uses the
    provider deadline (GT-P01, review GT01R-01).
    """

    def __init__(self, marker: Path) -> None:
        self.marker = marker
        self.origin: float | None = None
        self.calls = 0

    def monotonic(self) -> float:
        self.calls += 1
        if self.origin is None:
            if not self.marker.exists():
                return 0.0
            self.origin = time.monotonic()
        return time.monotonic() - self.origin


def _success_child(
    config: Any, request: Any, audio_hash: str, gate: Any, cancel: Any, reply: Any
) -> None:
    try:
        assert gate.wait(5)
        result = DiarizationResult(
            (),
            True,
            audio_sha256=audio_hash,
            model_manifest_sha256=config.manifest_sha256,
            warnings=("ANONYMOUS_ESTIMATE",),
        )
        reply.send_bytes(json.dumps(asdict(result)).encode())
    finally:
        reply.close()


def _available(self: Any) -> dict[str, Any]:
    return {"platform_supported": True, "dependencies": {"fake": "installed"}}


@pytest.mark.parametrize(
    "state,code",
    [("missing", "DEPENDENCY_MISSING"), ("unsupported", "DEPENDENCY_VERSION_UNSUPPORTED")],
)
def test_dependency_state_does_not_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str, code: str
) -> None:
    config, request = _synthetic(tmp_path)
    monkeypatch.setattr(
        LocalDiarizationProcess,
        "capabilities",
        lambda self: {"platform_supported": True, "dependencies": {"fake": state}},
    )
    provider = LocalDiarizationProcess(config)
    result = provider.diarize(request)
    assert not result.complete and result.error_code == code
    assert provider._process is None


def test_missing_distribution_is_reported_without_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _ = _synthetic(tmp_path)

    def missing(name: str) -> str:
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", missing)
    caps = LocalDiarizationProcess(config).capabilities()
    assert not caps["diarization"] and set(caps["dependencies"].values()) == {"missing"}


def test_precancel_closed_and_platform_fail_without_model_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, request = _synthetic(tmp_path)
    provider = LocalDiarizationProcess(config)
    event = threading.Event()
    event.set()
    assert provider.diarize(request, ExecutionContext(cancel=event)).cancelled
    monkeypatch.setattr(process, "_platform_supported", lambda: False)
    assert provider.diarize(request).error_code == "DIARIZATION_PLATFORM_UNSUPPORTED"
    provider.close()
    assert provider.diarize(request).cancelled


@pytest.mark.parametrize("mode", ["timeout", "cancel", "close"])
def test_owned_hung_child_ack_before_return(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    assert sys.platform == "win32", "Windows guard test requires the designated Windows runner"
    config, request = _synthetic(tmp_path, timeout=1.5 if mode == "timeout" else 10)
    marker = request.audio_path.with_suffix(".started")
    # GT-P01: the provider deadline starts before spawn, so under a loaded full run
    # child start-up alone used the whole 1.5 s. The provider clock now starts only once
    # the hung child is proven running; start-up has its own bound below (all modes).
    clock = _MarkerClock(marker)
    monkeypatch.setattr(process, "time", types.SimpleNamespace(monotonic=clock.monotonic))
    monkeypatch.setattr(LocalDiarizationProcess, "capabilities", _available)
    monkeypatch.setattr(process, "_worker", _hung_child)
    provider = LocalDiarizationProcess(config)
    event = threading.Event()
    results: list[DiarizationResult] = []
    errors: list[BaseException] = []

    def run() -> None:
        try:
            results.append(provider.diarize(request, ExecutionContext(cancel=event)))
        except BaseException as error:
            errors.append(error)

    worker = threading.Thread(target=run)
    worker.start()
    started_by = time.monotonic() + 15  # child start-up bound, real clock
    while not marker.exists():
        assert worker.is_alive(), f"provider returned before the child marker: {results or errors}"
        assert time.monotonic() < started_by, "child marker did not appear within 15 s"
        time.sleep(0.01)
    child = provider._process
    api = _observer()
    handle = api.OpenProcess(0x100000, False, child.pid)
    assert handle
    try:
        if mode == "cancel":
            event.set()
        elif mode == "close":
            provider.close()
        worker.join(8)
        assert not worker.is_alive() and not errors
        assert results[0].error_code == ("TIMEOUT" if mode == "timeout" else "CANCELLED")
        assert not results[0].complete and provider._process is None
        assert api.WaitForSingleObject(handle, 0) == 0
        # Fails loudly if the provider ever stops reading its module-level time. Cancel and
        # close may return before the clock is read again after the marker.
        assert clock.calls > 0
        assert clock.origin is not None or mode != "timeout"
    finally:
        event.set()
        provider.close()
        worker.join(8)
        api.CloseHandle(handle)


def test_slow_child_start_does_not_use_the_provider_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # GT-P01: a 2 s start-up against a 1.5 s timeout must still time out only after the
    # child is running, so the test observes the hung child instead of a lost race.
    config, request = _synthetic(tmp_path, timeout=1.5)
    marker = request.audio_path.with_suffix(".started")
    clock = _MarkerClock(marker)
    monkeypatch.setattr(process, "time", types.SimpleNamespace(monotonic=clock.monotonic))
    monkeypatch.setattr(LocalDiarizationProcess, "capabilities", _available)
    monkeypatch.setattr(process, "_worker", _slow_start_hung_child)
    provider = LocalDiarizationProcess(config)
    try:
        started = time.monotonic()
        result = provider.diarize(request)
        assert result.error_code == "TIMEOUT" and not result.complete
        assert marker.exists() and clock.origin is not None
        assert time.monotonic() - started >= 3.4  # 2 s start-up + 1.5 s deadline
        assert provider._process is None
    finally:
        provider.close()


def test_owned_success_reaps_child_and_preserves_audio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, request = _synthetic(tmp_path)
    monkeypatch.setattr(LocalDiarizationProcess, "capabilities", _available)
    monkeypatch.setattr(process, "_worker", _success_child)
    provider = LocalDiarizationProcess(config)
    before = hashlib.sha256(request.audio_path.read_bytes()).hexdigest()
    result = provider.diarize(request)
    assert result.complete and result.turns == () and provider._process is None
    assert (
        result.audio_sha256 == before == hashlib.sha256(request.audio_path.read_bytes()).hexdigest()
    )
    provider.close()


def test_guard_failure_never_opens_model_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, request = _synthetic(tmp_path)
    monkeypatch.setattr(LocalDiarizationProcess, "capabilities", _available)
    monkeypatch.setattr(process, "_worker", _hung_child)

    def failed(self: Any, pid: int) -> None:
        raise ProviderError("DIARIZATION_GUARD_FAILED")

    monkeypatch.setattr(_job.ChildJob, "attach", failed)
    provider = LocalDiarizationProcess(config)
    assert provider.diarize(request).error_code == "DIARIZATION_GUARD_FAILED"
    assert provider._process is None and not request.audio_path.with_suffix(".started").exists()


def test_ack_failure_retains_owned_child(tmp_path: Path) -> None:
    config, _ = _synthetic(tmp_path)

    class Stubborn:
        pid = 123
        closed = False

        def is_alive(self) -> bool:
            return True

        def join(self, timeout: float) -> None:
            pass

        def terminate(self) -> None:
            pass

        def close(self) -> None:
            self.closed = True

    child = Stubborn()
    provider = LocalDiarizationProcess(config)
    provider._process = child
    with pytest.raises(ProviderError, match="DIARIZATION_ACK_PENDING"):
        provider.close()
    assert provider._process is child and not child.closed


def _guard_supervisor(config: Any, request: Any, report: Any) -> None:
    spawn = multiprocessing.get_context("spawn")
    gate, cancel = spawn.Event(), spawn.Event()
    reader, sender = spawn.Pipe(duplex=False)
    child = spawn.Process(
        target=_hung_child, args=(config, request, "unused", gate, cancel, sender)
    )
    child.start()
    guard = _job.ChildJob()
    try:
        assert child.pid is not None
        guard.attach(child.pid)
        gate.set()
        report.send_bytes(str(child.pid).encode("ascii"))
        threading.Event().wait(30)
    finally:
        guard.close()
        child.join(3)
        if child.is_alive():
            child.terminate()
            child.join(3)
        child.close()
        reader.close()
        sender.close()
        report.close()


def test_parent_death_os_guard_ends_only_owned_fake_child(tmp_path: Path) -> None:
    config, request = _synthetic(tmp_path)
    spawn = multiprocessing.get_context("spawn")
    reader, sender = spawn.Pipe(duplex=False)
    supervisor = spawn.Process(target=_guard_supervisor, args=(config, request, sender))
    supervisor.start()
    sender.close()
    handle = None
    api = _observer()
    try:
        assert reader.poll(8)
        child_pid = int(reader.recv_bytes(32))
        handle = api.OpenProcess(0x100000, False, child_pid)
        assert handle
        deadline = time.monotonic() + 8
        while not request.audio_path.with_suffix(".started").exists():
            assert time.monotonic() < deadline
            time.sleep(0.01)
        # Terminate only the supervisor created by this test. Its non-inherited
        # Job handle must die even though the fake child ignores its cancel event.
        supervisor.terminate()
        supervisor.join(5)
        assert not supervisor.is_alive()
        assert api.WaitForSingleObject(handle, 5000) == 0
    finally:
        if supervisor.is_alive():
            supervisor.terminate()
            supervisor.join(5)
        supervisor.close()
        reader.close()
        if handle:
            api.CloseHandle(handle)
