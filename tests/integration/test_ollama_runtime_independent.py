"""BR30 helper follow-up: synthetic files, fake sockets and owned Python children.

No Ollama executable, daemon, real weights, download or credential is used.
These tests are separate from the previously rechecked engine checkpoint.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import socket
import struct
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from ctypes import wintypes
from pathlib import Path
from typing import Any

import pytest

from recoryn.domain import StateConflict, ValidationError
from recoryn.models import _owned as native_owned
from recoryn.models import ollama
from recoryn.models.ollama import ManagedOllama, verify_local_model
from recoryn.providers import (
    ExecutionContext,
    ProviderConfig,
    ProviderError,
    SummaryRequest,
    TranscriptSegment,
)
from recoryn.security import ConsentStore, Gateway
from recoryn.security._core import SecurityError
from recoryn.summarization import OllamaSummarizer

pytestmark = pytest.mark.integration


def synthetic_model(root: Path) -> Path:
    """Build integrity fixtures only; these bytes cannot run inference."""
    blobs = root / "blobs"
    blobs.mkdir(parents=True)
    records: list[dict[str, object]] = []
    for body, media in (
        (b"{}", "application/vnd.docker.container.image.v1+json"),
        (b"synthetic-only-not-real-weights", "application/vnd.ollama.image.model"),
    ):
        digest = hashlib.sha256(body).hexdigest()
        (blobs / ("sha256-" + digest)).write_bytes(body)
        records.append({"digest": "sha256:" + digest, "size": len(body), "mediaType": media})
    target = root / "manifests" / "registry.ollama.ai" / "library" / "synthetic" / "local"
    target.parent.mkdir(parents=True)
    target.write_text(
        json.dumps({"schemaVersion": 2, "config": records[0], "layers": [records[1]]}),
        encoding="utf-8",
    )
    return target


class FakeProcess:
    def __init__(self, exit_code: int | None = None) -> None:
        self.exit_code = exit_code
        self.calls: list[str] = []
        self.terminate_error = False
        self.hung = False
        self.pid = 424242
        self.job_handle = 101

    def poll(self) -> int | None:
        return self.exit_code

    def close(self) -> None:
        self.calls.append("close")
        if self.terminate_error:
            raise OSError("BR30-PRIVATE-PROCESS-CANARY")
        if self.hung:
            raise StateConflict("OLLAMA_STOP_ACK_PENDING")
        self.exit_code = 0


class LaunchHarness:
    """Inject the explicit owned-process/listener seam; never launch a daemon."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.process = FakeProcess()
        self.spawns: list[tuple[Path, dict[str, str]]] = []
        self.binds: list[tuple[str, int]] = []
        self.spawn_error = False
        self.listener_ready = True
        harness = self

        class Reservation:
            def __enter__(self) -> Reservation:
                return self

            def __exit__(self, *args: object) -> None:
                self.close()

            def bind(self, address: tuple[str, int]) -> None:
                harness.binds.append(address)

            def getsockname(self) -> tuple[str, int]:
                return "127.0.0.1", 39271

            def close(self) -> None:
                pass

            def connect(self, address: object) -> None:
                raise ConnectionRefusedError("synthetic fixture has no listener")

        def owned(executable: Path, environment: dict[str, str]) -> FakeProcess:
            self.spawns.append((executable, environment))
            if self.spawn_error:
                raise OSError("BR30-PRIVATE-LAUNCH-CANARY")
            return self.process

        monkeypatch.setattr(socket, "socket", lambda *args, **kwargs: Reservation())
        monkeypatch.setattr(ollama, "OwnedServer", owned)
        monkeypatch.setattr(
            ollama, "listener_matches", lambda pid, port, **kwargs: self.listener_ready
        )


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> LaunchHarness:
    return LaunchHarness(monkeypatch)


@pytest.fixture
def artifacts(tmp_path: Path) -> tuple[Path, Path]:
    models = tmp_path / "synthetic-models"
    synthetic_model(models)
    executable = tmp_path / "never-executed.exe"
    executable.write_bytes(b"not-an-executable; Popen is injected")
    return executable, models


@pytest.mark.parametrize("damage", ("none", "blob", "size", "no_weights", "remote_hint"))
def test_local_ollama_manifest_requires_matching_local_artifacts(
    tmp_path: Path,
    damage: str,
) -> None:
    root = tmp_path / "synthetic-ollama"
    blobs = root / "blobs"
    target = synthetic_model(root)
    manifest = json.loads(target.read_bytes())
    records = [manifest["config"], manifest["layers"][0]]
    if damage == "blob":
        (blobs / ("sha256-" + str(records[1]["digest"])[7:])).write_bytes(b"corrupt")
    elif damage == "size":
        records[1]["size"] = 1
    elif damage == "no_weights":
        records[1]["mediaType"] = "application/vnd.ollama.image.license"
    elif damage == "remote_hint":
        manifest["remote_model"] = "cloud-model"
    target.write_text(json.dumps(manifest), encoding="utf-8")
    if damage == "none":
        digest = verify_local_model(root, "synthetic:local")
        assert len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)
    else:
        with pytest.raises(ValidationError):
            verify_local_model(root, "synthetic:local")


@pytest.mark.parametrize(
    "model", ("synthetic", "synthetic:cloud", "../synthetic:local", "a/b:local")
)
def test_unapproved_model_name_is_rejected_without_creating_files(
    tmp_path: Path, model: str
) -> None:
    root = tmp_path / "never-created"
    with pytest.raises(ValidationError):
        verify_local_model(root, model)
    assert not root.exists()


def test_missing_model_cannot_trigger_fetch_or_creation(tmp_path: Path) -> None:
    root = tmp_path / "missing-models"
    with pytest.raises((ValidationError, OSError)):
        verify_local_model(root, "synthetic:local")
    assert not root.exists()


@pytest.mark.parametrize("damage", ("future_schema", "duplicate_key", "digest", "size", "config"))
def test_malformed_manifest_is_rejected_without_rewriting_source(
    tmp_path: Path, damage: str
) -> None:
    root = tmp_path / "malformed"
    target = synthetic_model(root)
    value = json.loads(target.read_bytes())
    if damage == "future_schema":
        value["schemaVersion"] = 99
    elif damage == "digest":
        value["layers"][0]["digest"] = "sha256:../outside"
    elif damage == "size":
        value["layers"][0]["size"] = True
    elif damage == "config":
        value["config"] = None
    payload = json.dumps(value)
    if damage == "duplicate_key":
        payload = payload.replace('"schemaVersion": 2', '"schemaVersion": 99,"schemaVersion": 2')
    target.write_text(payload, encoding="utf-8")
    before = target.read_bytes()
    with pytest.raises(ValidationError):
        verify_local_model(root, "synthetic:local")
    assert target.read_bytes() == before


def test_helper_constructor_has_no_launch_or_bind(harness: LaunchHarness) -> None:
    owner = ManagedOllama()
    assert owner.process is None and harness.spawns == [] and harness.binds == []
    with pytest.raises(StateConflict):
        owner.attestation()
    owner.close()


@pytest.mark.parametrize("damage", ("executable", "manifest", "blob", "cloud_name"))
def test_invalid_artifacts_fail_before_bind_and_spawn(
    harness: LaunchHarness, artifacts: tuple[Path, Path], damage: str
) -> None:
    executable, models = artifacts
    model = "synthetic:local"
    if damage == "executable":
        executable.unlink()
    elif damage == "manifest":
        next((models / "manifests").rglob("local")).write_text("{}", encoding="utf-8")
    elif damage == "blob":
        next((models / "blobs").iterdir()).unlink()
    else:
        model = "synthetic:cloud"
    owner = ManagedOllama()
    with pytest.raises((ValidationError, OSError)):
        owner.start(executable, models, model)
    assert harness.spawns == [] and harness.binds == [] and owner.process is None


def test_launch_error_does_not_publish_proof(
    harness: LaunchHarness, artifacts: tuple[Path, Path]
) -> None:
    harness.spawn_error = True
    owner = ManagedOllama()
    with pytest.raises((OSError, StateConflict, ValidationError)):
        owner.start(*artifacts, "synthetic:local")
    with pytest.raises(StateConflict):
        owner.attestation()
    assert owner.process is None


def test_local_launch_pins_host_models_and_disables_cloud_proxy(
    harness: LaunchHarness, artifacts: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        monkeypatch.setenv(name, "http://proxy.invalid:8888")
    monkeypatch.setenv("OLLAMA_HOST", "0.0.0.0:11434")
    monkeypatch.setenv("OLLAMA_NO_CLOUD", "0")
    owner = ManagedOllama()
    try:
        proof = owner.start(*artifacts, "synthetic:local")
        executable, environment = harness.spawns[0]
        assert executable == artifacts[0]
        assert harness.binds == [("127.0.0.1", 0)]
        assert environment["OLLAMA_HOST"] == "127.0.0.1:39271"
        assert environment["OLLAMA_MODELS"] == str(artifacts[1])
        assert environment["OLLAMA_NO_CLOUD"] == "1"
        assert not any(
            key.lower() in {"http_proxy", "https_proxy", "all_proxy"} for key in environment
        )
        assert proof.endpoint == "http://127.0.0.1:39271/api/chat"
        assert proof.model == "synthetic:local" and proof.cloud_disabled
    finally:
        owner.close()


@pytest.mark.parametrize(
    "endpoint", ("http://127.0.0.1:39271/api/chat", "https://remote.example.test/chat")
)
def test_helper_proof_does_not_grant_gateway_transport_permission(
    tmp_path: Path, artifacts: tuple[Path, Path], harness: LaunchHarness, endpoint: str
) -> None:
    owner = ManagedOllama()
    owner.start(*artifacts, "synthetic:local")
    try:
        with ConsentStore(tmp_path / "policy.sqlite") as policy:
            with pytest.raises(SecurityError):
                Gateway(policy).request("ollama", endpoint, "transcript", b"synthetic")
    finally:
        owner.close()


@pytest.mark.parametrize("state", ("exited", "no_listener"))
def test_start_cannot_attest_exited_or_unready_process(
    harness: LaunchHarness, artifacts: tuple[Path, Path], state: str
) -> None:
    if state == "exited":
        harness.process.exit_code = 17
    else:
        harness.listener_ready = False
    owner = ManagedOllama(startup_timeout=0.03)
    try:
        with pytest.raises((StateConflict, ValidationError, OSError)):
            owner.start(*artifacts, "synthetic:local")
        with pytest.raises(StateConflict):
            owner.attestation()
    finally:
        owner.close()


@pytest.mark.parametrize("reason", ("normal", "hung"))
def test_close_waits_for_owned_process_and_invalidates_getter(
    harness: LaunchHarness, artifacts: tuple[Path, Path], reason: str
) -> None:
    owner = ManagedOllama()
    owner.start(*artifacts, "synthetic:local")
    harness.process.hung = reason == "hung"
    if reason == "hung":
        with pytest.raises(StateConflict, match="OLLAMA_STOP_ACK_PENDING"):
            owner.close()
        assert owner.process is harness.process
        with pytest.raises(StateConflict):
            owner.attestation()
        harness.process.hung = False
    owner.close()
    assert harness.process.poll() is not None
    assert harness.process.calls == (["close", "close"] if reason == "hung" else ["close"])
    assert owner.process is None
    with pytest.raises(StateConflict):
        owner.attestation()
    owner.close()


def test_termination_error_cannot_leave_attestation_usable(
    harness: LaunchHarness, artifacts: tuple[Path, Path]
) -> None:
    owner = ManagedOllama()
    owner.start(*artifacts, "synthetic:local")
    harness.process.terminate_error = True
    try:
        try:
            owner.close()
        except (StateConflict, OSError):
            pass
        with pytest.raises(StateConflict):
            owner.attestation()
    finally:
        harness.process.terminate_error = False
        owner.close()


@pytest.mark.parametrize("damage", ("manifest", "blob"))
def test_model_mutation_invalidates_live_attestation(
    harness: LaunchHarness, artifacts: tuple[Path, Path], damage: str
) -> None:
    owner = ManagedOllama()
    owner.start(*artifacts, "synthetic:local")
    models = artifacts[1]
    if damage == "manifest":
        target = next((models / "manifests").rglob("local"))
    else:
        target = next((models / "blobs").iterdir())
    target.write_bytes(b"changed-after-proof")
    try:
        with pytest.raises((StateConflict, ValidationError)):
            owner.attestation()
    finally:
        owner.close()


class SummaryGateway:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def request(
        self, provider_id: str, endpoint: str, data_type: str, body: bytes, **kwargs: Any
    ) -> bytes:
        self.calls.append(endpoint)
        return b'{"message":{"content":"{\\"claims\\":[]}"},"done":true}'


@pytest.mark.parametrize("state", ("closed", "exited", "expired"))
def test_frozen_proof_cannot_dispatch_after_owner_lifetime(
    harness: LaunchHarness,
    artifacts: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    state: str,
) -> None:
    owner = ManagedOllama()
    proof = owner.start(*artifacts, "synthetic:local")
    config = ProviderConfig(
        "ollama",
        "synthetic:local",
        endpoint=proof.endpoint,
        execution_location="local",
        local_attestation=proof,
        context_window_tokens=8192,
        max_output_tokens=256,
    )
    if state == "closed":
        owner.close()
    elif state == "exited":
        harness.process.exit_code = 17
    else:
        monkeypatch.setattr(time, "monotonic", lambda: proof.expires_at_monotonic + 1)
    gateway = SummaryGateway()
    request = SummaryRequest("fixed-revision", (TranscriptSegment("s1", 0, 10, "synthetic"),))
    try:
        result = OllamaSummarizer(gateway, config).summarize(request, ExecutionContext())
        assert gateway.calls == [], "stale owned-server proof reached dispatch"
        assert not result.complete
        assert result.error_code == "LOCAL_EXECUTION_UNVERIFIED"
    finally:
        owner.close()


def test_second_start_cannot_replace_an_owned_child(
    harness: LaunchHarness, artifacts: tuple[Path, Path]
) -> None:
    owner = ManagedOllama()
    owner.start(*artifacts, "synthetic:local")
    try:
        with pytest.raises(StateConflict):
            owner.start(*artifacts, "synthetic:local")
        assert len(harness.spawns) == 1
    finally:
        owner.close()


def test_old_generation_rejection_cannot_invalidate_new_proof(
    harness: LaunchHarness, artifacts: tuple[Path, Path]
) -> None:
    owner = ManagedOllama()
    old = owner.start(*artifacts, "synthetic:local")
    owner.close()
    harness.process = FakeProcess()
    try:
        new = owner.start(*artifacts, "synthetic:local")
        with pytest.raises(ProviderError, match="LOCAL_EXECUTION_UNVERIFIED"):
            with old.execution_guard():
                pytest.fail("old owner generation was revived")
        assert owner.attestation() is new
        with new.execution_guard():
            pass
    finally:
        owner.close()


@pytest.mark.parametrize("timeout", (True, 0, -1, float("nan"), float("inf"), 61))
def test_readiness_timeout_is_finite_and_bounded(timeout: float) -> None:
    with pytest.raises(ValidationError):
        ManagedOllama(startup_timeout=timeout)


@pytest.mark.parametrize("boundary", ("before_launch", "during_readiness"))
def test_start_cancellation_never_publishes_proof_and_cleans_owned_process(
    harness: LaunchHarness,
    artifacts: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
) -> None:
    cancel = threading.Event()
    if boundary == "before_launch":
        cancel.set()
    else:

        def unavailable(pid: int, port: int, **kwargs: object) -> bool:
            cancel.set()
            return False

        monkeypatch.setattr(ollama, "listener_matches", unavailable)
    owner = ManagedOllama(startup_timeout=0.1)
    with pytest.raises(StateConflict, match="CANCELLED"):
        owner.start(*artifacts, "synthetic:local", cancel=cancel)
    assert len(harness.spawns) == (0 if boundary == "before_launch" else 1)
    assert owner.process is None
    with pytest.raises(StateConflict):
        owner.attestation()


@pytest.mark.parametrize("damage", ("listener", "executable"))
def test_process_and_verified_executable_identity_remain_bound_to_proof(
    harness: LaunchHarness, artifacts: tuple[Path, Path], damage: str
) -> None:
    owner = ManagedOllama()
    proof = owner.start(*artifacts, "synthetic:local")
    if damage == "listener":
        harness.listener_ready = False
    else:
        artifacts[0].write_bytes(b"replaced-executable")
    try:
        with pytest.raises(ProviderError, match="LOCAL_EXECUTION_UNVERIFIED"):
            with proof.execution_guard():
                pytest.fail("changed owner identity retained execution authority")
        with pytest.raises(StateConflict):
            owner.attestation()
    finally:
        owner.close()


@contextmanager
def owned_process_handle(pid: int) -> Iterator[tuple[Any, Any]]:
    """Observe/clean only the exact child reported by our still-running fake server."""
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    api.OpenProcess.restype = wintypes.HANDLE
    api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    api.WaitForSingleObject.restype = wintypes.DWORD
    api.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    api.TerminateProcess.restype = wintypes.BOOL
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.CloseHandle.restype = wintypes.BOOL
    handle = api.OpenProcess(0x00100001, False, pid)
    assert handle, "cannot open the owned synthetic descendant for observation"
    try:
        yield api, handle
    finally:
        if api.WaitForSingleObject(handle, 0) == 0x102:
            # Job termination may already be in progress, in which case an
            # additional TerminateProcess can fail. The process signal is ACK.
            if api.WaitForSingleObject(handle, 1000) == 0x102:
                api.TerminateProcess(handle, 98)
            assert api.WaitForSingleObject(handle, 5000) == 0
        assert api.CloseHandle(handle)


def test_close_terminates_owned_descendant_before_ack(
    artifacts: tuple[Path, Path],
    harness: LaunchHarness,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Only replace the executable command payload: the actual production native
    # CreateProcess(SUSPENDED), Job assignment, resume and close ACK all execute.
    status = tmp_path / "owned-child.json"
    script = (
        "import json,subprocess,sys,time;from pathlib import Path;"
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
        f"p=Path({str(status) + '.tmp'!r});"
        "p.write_text(json.dumps({'pid':child.pid}));"
        f"p.replace({str(status)!r});"
        "time.sleep(60)"
    )

    original_command = subprocess.list2cmdline

    def synthetic_command(args: list[str]) -> str:
        assert args == [sys.executable, "serve"]
        return original_command([sys.executable, "-c", script])

    def launch(executable: Path, environment: dict[str, str]) -> native_owned.OwnedServer:
        return native_owned.OwnedServer(Path(sys.executable), environment)

    monkeypatch.setattr(subprocess, "list2cmdline", synthetic_command)
    monkeypatch.setattr(ollama, "OwnedServer", launch)
    owner = ManagedOllama()
    try:
        owner.start(*artifacts, "synthetic:local")
        parent = owner.process
        deadline = time.monotonic() + 10
        while not status.exists() and time.monotonic() < deadline:
            threading.Event().wait(0.01)
        assert status.exists(), "owned fake server did not create its child"
        pid = json.loads(status.read_bytes())["pid"]
        with owned_process_handle(pid) as (api, handle):
            assert api.WaitForSingleObject(handle, 0) == 0x102
            owner.close()
            assert parent.poll() is not None
            assert api.WaitForSingleObject(handle, 0) == 0, (
                "close acknowledged while the owned fake server's descendant was still alive"
            )
    finally:
        try:
            owner.close()
        except StateConflict:
            # Preserve the original test error while allowing an already dying
            # owned parent to signal before retrying this test's cleanup.
            if owner.process is not None:
                with owned_process_handle(owner.process.pid) as (api, handle):
                    assert api.WaitForSingleObject(handle, 5000) == 0
            owner.close()


def test_native_owned_job_kills_children_when_supervisor_dies(tmp_path: Path) -> None:
    """Abruptly kill our supervisor; Windows must close only its private Job."""
    status = tmp_path / "native-tree.json"
    child_script = (
        "import json,os,subprocess,sys,time;from pathlib import Path;"
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
        f"p=Path({str(status) + '.tmp'!r});"
        "p.write_text(json.dumps({'parent':os.getpid(),'descendant':child.pid}));"
        f"p.replace({str(status)!r});time.sleep(60)"
    )
    supervisor_script = (
        "import os,sys,time;from pathlib import Path;"
        "from recoryn.models import _owned;"
        "command=_owned.subprocess.list2cmdline;"
        f"_owned.subprocess.list2cmdline=lambda args:command([sys.executable,'-c',{child_script!r}]);"
        "owner=_owned.OwnedServer(Path(sys.executable),dict(os.environ));"
        "time.sleep(60)"
    )
    supervisor = subprocess.Popen(
        [sys.executable, "-c", supervisor_script],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        deadline = time.monotonic() + 10
        while not status.exists() and supervisor.poll() is None and time.monotonic() < deadline:
            threading.Event().wait(0.01)
        if not status.exists():
            supervisor.kill()
            _, error = supervisor.communicate(timeout=5)
            pytest.fail("synthetic owned Job supervisor failed: " + error.decode(errors="replace"))
        pids = json.loads(status.read_bytes())
        with (
            owned_process_handle(pids["parent"]) as (api, parent),
            owned_process_handle(pids["descendant"]) as (_, descendant),
        ):
            assert api.WaitForSingleObject(parent, 0) == 0x102
            assert api.WaitForSingleObject(descendant, 0) == 0x102
            supervisor.kill()
            supervisor.wait(timeout=5)
            assert api.WaitForSingleObject(parent, 5000) == 0
            assert api.WaitForSingleObject(descendant, 5000) == 0
    finally:
        if supervisor.poll() is None:
            supervisor.kill()
        supervisor.communicate(timeout=5)


def test_native_close_waits_for_process_signal_after_zero_job_accounting() -> None:
    """Job accounting and a process signal are separate observations."""

    class Kernel:
        def __init__(self) -> None:
            self.observations = 0
            self.closed: list[int] = []

        def TerminateJobObject(self, job: int, code: int) -> bool:
            return True

        def QueryInformationJobObject(self, *args: Any) -> bool:
            if args[1] == 3:
                ctypes.memmove(args[2], b"\0" * 8, 8)
            else:
                assert args[1] == 1
                args[2]._obj.active = 0
            return True

        def WaitForSingleObject(self, process: int, timeout: int) -> int:
            self.observations += 1
            return 0x102 if self.observations == 1 and timeout == 0 else 0

        def GetExitCodeProcess(self, process: int, code: Any) -> bool:
            code._obj.value = 1
            return True

        def CloseHandle(self, handle: int) -> bool:
            self.closed.append(handle)
            return True

    kernel = Kernel()
    owner = object.__new__(native_owned.OwnedServer)
    owner._api = kernel
    owner._job, owner._process = 101, 202
    owner._returncode = None
    owner._exit_handles = {}
    owner.pid = 424242
    owner.close(timeout=1)
    assert owner.poll() == 1
    assert sorted(kernel.closed) == [101, 202]
    owner.close(timeout=1)
    assert sorted(kernel.closed) == [101, 202]


@pytest.mark.parametrize("identity", ("owned", "foreign", "open_denied"))
def test_native_descendant_signal_is_required_and_failed_ack_retains_exact_handle(
    identity: str,
) -> None:
    class Kernel:
        def __init__(self) -> None:
            self.signaled = False
            self.closed: list[int] = []
            self.waited: list[int] = []
            self.opened = 0

        def QueryInformationJobObject(self, *args: Any) -> bool:
            if args[1] == 3:
                table = struct.pack("<II", 1, 1) + (303).to_bytes(
                    ctypes.sizeof(ctypes.c_size_t), "little"
                )
                ctypes.memmove(args[2], table, len(table))
            else:
                assert args[1] == 1
                args[2]._obj.active = 0
            return True

        def OpenProcess(self, rights: int, inherit: bool, pid: int) -> int:
            assert rights & 0x00100000 and rights & 0x1000 and not inherit and pid == 303
            self.opened += 1
            if identity == "open_denied":
                ctypes.set_last_error(5)
                return 0
            return 404

        def IsProcessInJob(self, handle: int, job: int, member: Any) -> bool:
            assert (handle, job) == (404, 101)
            member._obj.value = identity == "owned"
            return True

        def TerminateJobObject(self, job: int, code: int) -> bool:
            return True

        def WaitForSingleObject(self, handle: int, timeout: int) -> int:
            self.waited.append(handle)
            return 0x102 if handle == 404 and not self.signaled else 0

        def GetExitCodeProcess(self, process: int, code: Any) -> bool:
            code._obj.value = 1
            return True

        def CloseHandle(self, handle: int) -> bool:
            self.closed.append(handle)
            return True

    kernel = Kernel()
    owner = object.__new__(native_owned.OwnedServer)
    owner._api, owner._job, owner._process = kernel, 101, 202
    owner._returncode, owner._exit_handles, owner.pid = None, {}, 424242
    with pytest.raises(StateConflict, match="OLLAMA_STOP_ACK_PENDING"):
        owner.close(timeout=0.1)
    assert owner._job == 101 and owner._process == 202
    if identity != "owned":
        assert kernel.closed == ([404] if identity == "foreign" else [])
        assert kernel.waited == [] and owner._exit_handles == {}
        return
    assert kernel.closed == [] and owner._exit_handles == {303: 404}
    assert kernel.waited == [404]
    kernel.signaled = True
    owner.close(timeout=0.1)
    assert kernel.opened == 1  # Retry reuses the original process object handle.
    assert sorted(kernel.closed) == [101, 202, 404]
    assert owner._exit_handles == {}
    owner.close(timeout=1)
    assert sorted(kernel.closed) == [101, 202, 404]


@pytest.mark.parametrize("failure", ("job", "limits", "create", "assign", "resume"))
def test_native_failed_ownership_never_runs_uncontained_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: str
) -> None:
    events: list[str] = []
    closed: list[int] = []

    class Kernel:
        def CreateJobObjectW(self, *args: Any) -> int:
            return 0 if failure == "job" else 101

        def SetInformationJobObject(self, *args: Any) -> bool:
            assert args[2]._obj.basic.flags & 0x2000  # KILL_ON_JOB_CLOSE.
            return failure != "limits"

        def CreateProcessW(self, *args: Any) -> bool:
            assert not args[4]  # No inherited Job/credential handles.
            assert args[5] & 0x4  # CREATE_SUSPENDED before ownership assignment.
            if failure == "create":
                return False
            args[9]._obj.process = 202
            args[9]._obj.thread = 303
            args[9]._obj.pid = 404
            events.append("created_suspended")
            return True

        def AssignProcessToJobObject(self, job: int, process: int) -> bool:
            assert (job, process) == (101, 202)
            events.append("assign")
            return failure != "assign"

        def ResumeThread(self, thread: int) -> int:
            assert events == ["created_suspended", "assign"]
            assert failure != "assign"
            events.append("resume_failed")
            return 0xFFFFFFFF

        def TerminateProcess(self, process: int, code: int) -> bool:
            assert process == 202
            events.append("terminate")
            return True

        def WaitForSingleObject(self, process: int, timeout: int) -> int:
            assert process == 202
            events.append("exit_ack")
            return 0

        def CloseHandle(self, handle: int) -> bool:
            closed.append(handle)
            return True

    monkeypatch.setattr(native_owned, "_api", Kernel)
    with pytest.raises(StateConflict):
        native_owned.OwnedServer(tmp_path / "never-run.exe", {})
    if failure in {"assign", "resume"}:
        assert events[-2:] == ["terminate", "exit_ack"]
        assert sorted(closed) == [101, 202, 303]
    else:
        assert not events
        assert closed == ([] if failure == "job" else [101])


def test_os_listener_check_accepts_only_this_tests_loopback_pid_and_port() -> None:
    # A bound/listening synthetic socket only: no connect, accept, DNS or bytes.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        assert native_owned.listener_matches(os.getpid(), port)
        assert not native_owned.listener_matches(os.getpid() + 1, port)


def test_descendant_listener_requires_the_exact_owned_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    status = tmp_path / "descendant-listener.json"
    listener_script = (
        "import json,os,socket,time;from pathlib import Path;"
        "listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(1);"
        f"p=Path({str(status) + '.tmp'!r});"
        "p.write_text(json.dumps({'pid':os.getpid(),'port':listener.getsockname()[1]}));"
        f"p.replace({str(status)!r});time.sleep(60)"
    )
    server_script = (
        "import subprocess,sys,time;"
        f"child=subprocess.Popen([sys.executable,'-c',{listener_script!r}]);time.sleep(60)"
    )
    original_command = subprocess.list2cmdline
    monkeypatch.setattr(
        subprocess,
        "list2cmdline",
        lambda args: original_command([sys.executable, "-c", server_script]),
    )
    owner = native_owned.OwnedServer(Path(sys.executable), dict(os.environ))
    empty_job: Any = None
    kernel = native_owned._api()
    try:
        deadline = time.monotonic() + 10
        while not status.exists() and time.monotonic() < deadline:
            threading.Event().wait(0.01)
        assert status.exists(), "owned synthetic listener did not announce its identity"
        listener = json.loads(status.read_bytes())
        assert listener["pid"] != owner.pid
        empty_job = kernel.CreateJobObjectW(None, None)
        assert empty_job
        assert not native_owned.listener_matches(owner.pid, listener["port"])
        assert not native_owned.listener_matches(owner.pid, listener["port"], job=empty_job)
        assert native_owned.listener_matches(owner.pid, listener["port"], job=owner.job_handle)
    finally:
        if empty_job:
            assert kernel.CloseHandle(empty_job)
        owner.close()


@pytest.mark.parametrize(
    "damage", ("none", "pid", "address", "state", "port", "truncated", "error")
)
def test_listener_table_decoding_rejects_wrong_owner_or_malformed_table(
    monkeypatch: pytest.MonkeyPatch, damage: str
) -> None:
    pid, port = 424242, 39271
    # Independent fixed-width table oracle: count + six little-endian DWORDs.
    table = struct.pack(
        "<7I",
        2 if damage == "truncated" else 1,
        5 if damage == "state" else 2,
        0 if damage == "address" else int.from_bytes(b"\x7f\0\0\x01", "little"),
        socket.htons(port + (damage == "port")),
        0,
        0,
        pid + (damage == "pid"),
    )

    class ReadTable:
        def __call__(self, buffer: Any, size: Any, *args: Any) -> int:
            size._obj.value = len(table)
            if damage == "error":
                return 5  # Access denied must not become attestation evidence.
            if buffer is None:
                return 122
            ctypes.memmove(buffer, table, len(table))
            return 0

    class IPHelper:
        GetExtendedTcpTable = ReadTable()

    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: IPHelper())
    assert native_owned.listener_matches(pid, port) is (damage == "none")
