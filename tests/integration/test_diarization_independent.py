"""BR41 independent file/protobuf/result/lifetime oracles; no real inference or weights."""

from __future__ import annotations

import ctypes
import hashlib
import importlib
import importlib.metadata
import json
import multiprocessing
import os
import subprocess
import sys
import threading
import time
import wave
from ctypes import wintypes
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from recoryn.content import Segment
from recoryn.diarization import (
    DiarizationConfig,
    DiarizationRequest,
    DiarizationResult,
    LocalDiarizationProcess,
    SpeakerTurn,
    assign_speakers,
    backend,
    process,
)
from recoryn.diarization.models import verified_models
from recoryn.providers import ExecutionContext, ProviderError

pytestmark = pytest.mark.integration


def synthetic_audio(tmp_path: Path) -> DiarizationRequest:
    path = tmp_path / "derived.wav"
    with wave.open(str(path), "wb") as stream:
        stream.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        stream.writeframes(b"\x01\x00\xff\xff" * 8000)
    return DiarizationRequest(path, 4000, "system")


def synthetic_manifest(tmp_path: Path) -> DiarizationConfig:
    records = {}
    for role in ("embedding", "segmentation"):
        data = b"not weights: " + role.encode()
        license_bytes = b"SYNTHETIC LICENSE TEXT FOR BR41 ONLY"
        (tmp_path / f"{role}.onnx").write_bytes(data)
        (tmp_path / f"LICENSE.{role}.txt").write_bytes(license_bytes)
        records[role] = {
            "file": f"{role}.onnx",
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "license_id": "BR41-fixture",
            "license_url": "https://publisher.invalid/license",
            "license_file": f"LICENSE.{role}.txt",
            "license_sha256": hashlib.sha256(license_bytes).hexdigest(),
        }
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "runtime": "sherpa-onnx",
                "runtime_version": "2.0.1",
                "models": records,
            }
        )
    )
    return DiarizationConfig(path, hashlib.sha256(path.read_bytes()).hexdigest(), True)


@pytest.mark.parametrize(
    "mutation", ["duplicate", "empty_license", "model_changed", "license_changed"]
)
def test_pinned_local_bytes_and_license_are_checked_before_optional_import(
    tmp_path: Path, mutation: str
) -> None:
    config = synthetic_manifest(tmp_path)
    if mutation == "duplicate":
        raw = config.manifest_path.read_bytes().replace(
            b'"schema_version": 1', b'"schema_version": 1,"schema_version": 1'
        )
        config.manifest_path.write_bytes(raw)
        config = replace(config, manifest_sha256=hashlib.sha256(raw).hexdigest())
    elif mutation == "empty_license":
        (tmp_path / "LICENSE.embedding.txt").write_bytes(b" \r\n")
        value = json.loads(config.manifest_path.read_bytes())
        value["models"]["embedding"]["license_sha256"] = hashlib.sha256(b" \r\n").hexdigest()
        raw = json.dumps(value).encode()
        config.manifest_path.write_bytes(raw)
        config = replace(config, manifest_sha256=hashlib.sha256(raw).hexdigest())
    else:
        (
            tmp_path
            / ("embedding.onnx" if mutation == "model_changed" else "LICENSE.embedding.txt")
        ).write_bytes(b"tampered bytes")
    with pytest.raises(ProviderError):
        verified_models(config)


def test_import_and_capability_do_not_load_optional_native_modules(tmp_path: Path) -> None:
    # A fresh interpreter makes this independent of pytest's earlier module cache.
    program = """
import importlib.abc, json, socket, sys
from pathlib import Path
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'onnx','sherpa_onnx','numpy','onnxruntime'}:
            raise AssertionError('BR41_OPTIONAL_IMPORT:' + fullname)
sys.meta_path.insert(0, Block())
def deny(event, args):
    if event in {'socket.connect','socket.getaddrinfo'}:
        raise AssertionError('BR41_NETWORK')
sys.addaudithook(deny)
from recoryn.diarization import LocalDiarizationProcess, DiarizationConfig
value = LocalDiarizationProcess(DiarizationConfig(Path(sys.argv[1]), 'a'*64))
caps = value.capabilities()
assert caps['model_state'] == 'not_checked' and caps['quality_validation'] == 'NOT_RUN'
assert caps['devices'] == ('cpu',)
value.close()
print(json.dumps({'status':'PASS','optional_imports':False}))
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(tmp_path / "absent.json")],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")},
        capture_output=True,
        check=True,
        timeout=15,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    assert json.loads(result.stdout)["status"] == "PASS"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "placement", ["initializer", "attribute_graph", "sparse", "function", "training"]
)
def test_real_onnx_protobuf_nested_external_tensor_cannot_read_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, placement: str
) -> None:
    # A metadata-only protobuf has no actual weights and is never run by an engine.
    if sys.version_info < (3, 12):
        caps = LocalDiarizationProcess(
            DiarizationConfig(tmp_path / "absent.json", "a" * 64)
        ).capabilities()
        assert not caps["diarization"] and not caps["platform_supported"]
        return  # Explicit N/A real-parser oracle; fake external-tensor cases remain mandatory.
    try:
        installed = importlib.metadata.version("onnx")
    except importlib.metadata.PackageNotFoundError:
        caps = LocalDiarizationProcess(
            DiarizationConfig(tmp_path / "absent.json", "a" * 64)
        ).capabilities()
        assert not caps["diarization"] and caps["dependencies"]["onnx"] == "missing"
        return  # Explicit N/A, not a parser PASS and not a pytest skip.
    if installed != "1.23.2":
        caps = LocalDiarizationProcess(
            DiarizationConfig(tmp_path / "absent.json", "a" * 64)
        ).capabilities()
        assert not caps["diarization"] and caps["dependencies"]["onnx"] == "unsupported"
        return
    onnx = importlib.import_module("onnx")
    assert onnx.__version__ == "1.23.2"
    model = onnx.ModelProto()
    model.graph.name = "BR41 synthetic graph"
    if placement == "initializer":
        tensor = model.graph.initializer.add()
    elif placement == "attribute_graph":
        node = model.graph.node.add()
        tensor = node.attribute.add().graphs.add().initializer.add()
    elif placement == "sparse":
        tensor = model.graph.sparse_initializer.add().values
    elif placement == "function":
        tensor = model.functions.add().node.add().attribute.add().t
    else:
        tensor = model.training_info.add().initialization.initializer.add()
    tensor.name = "unapproved external tensor"
    tensor.data_type = 1
    tensor.dims.append(1)
    tensor.data_location = 1
    location = tensor.external_data.add()
    location.key, location.value = "location", str(tmp_path / "must-not-read.bin")
    # Byte parser must not try the path, even when that external file does not exist.
    attempted = []
    original = Path.open

    def no_sidecar(path: Path, *args: Any, **kwargs: Any) -> Any:
        if path.name == "must-not-read.bin":
            attempted.append(path)
            raise AssertionError("BR41 external file access")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", no_sidecar)
    with pytest.raises(ProviderError, match="DIARIZATION_EXTERNAL_DATA_DENIED"):
        backend.audit_onnx(model.SerializeToString(), onnx)
    assert attempted == [] and not list(tmp_path.iterdir())
    tensor.ClearField("external_data")
    tensor.data_location = 0
    backend.audit_onnx(model.SerializeToString(), onnx)


def test_annotation_union_has_independent_coverage_and_preserves_evidence() -> None:
    original = (
        Segment("union", 0, 1000, "keep", track_id="system"),
        Segment("ambiguous", 1000, 2000, "keep ambiguous", track_id="system"),
        Segment("assertion", 0, 1000, "insert", provenance="user_assertion", track_id="system"),
        Segment(
            "unresolved", 0, 1000, "unknown source", provenance="unresolved", track_id="system"
        ),
    )
    turns = (
        SpeakerTurn(0, 450, "speaker_scope_0", "system"),
        SpeakerTurn(250, 800, "speaker_scope_0", "system"),
        SpeakerTurn(1000, 1900, "speaker_scope_0", "system"),
        SpeakerTurn(1900, 2000, "speaker_scope_1", "system"),
        SpeakerTurn(0, 1000, "speaker_other_1", "mic"),
    )
    before = tuple(asdict(item) for item in original)
    assert assign_speakers(original, turns, min_coverage=0.81)[0].speaker is None
    annotated = assign_speakers(original, turns, min_coverage=0.8)
    assert [item.speaker for item in annotated] == ["speaker_scope_0", None, None, None]
    assert tuple(asdict(item) for item in original) == before
    assert all(
        replace(new, speaker=old.speaker) == old and new is not old
        for old, new in zip(original, annotated, strict=True)
    )


@pytest.mark.parametrize("depth", [0, 1, 3, 8, 32])
@pytest.mark.parametrize("marker", ["external_field", "external_location"])
def test_external_tensor_fake_oracle_is_mandatory_without_optional_packages(
    depth: int, marker: str
) -> None:
    tensor = SimpleNamespace(
        DESCRIPTOR=SimpleNamespace(full_name="onnx.TensorProto"),
        external_data=[("location", "forbidden-sidecar")] if marker == "external_field" else [],
        data_location=1 if marker == "external_location" else 0,
        ListFields=lambda: [],
    )
    root = tensor
    for _ in range(depth):
        children = [root]
        root = SimpleNamespace(
            DESCRIPTOR=SimpleNamespace(full_name="onnx.GraphProto"),
            ListFields=lambda children=children: [
                (SimpleNamespace(type=11, is_repeated=True), children)
            ],
        )
    root.HasField = lambda name: True
    parser = SimpleNamespace(load_model_from_string=lambda data, format: root)
    with pytest.raises(ProviderError, match="DIARIZATION_EXTERNAL_DATA_DENIED"):
        backend.audit_onnx(b"synthetic-protobuf-stand-in", parser)
    tensor.external_data = []
    tensor.data_location = 0
    backend.audit_onnx(b"synthetic-protobuf-stand-in", parser)


def _spawn_probe(
    config: Any, request: Any, audio_hash: str, gate: Any, cancel: Any, reply: Any
) -> None:
    import time

    assert gate.wait(5)
    report = request.audio_path.with_suffix(".spawn.json")
    staging = report.with_suffix(".tmp")
    staging.write_text(json.dumps({"pid": os.getpid(), "executable": sys.executable}))
    staging.replace(report)
    release = request.audio_path.with_suffix(".release")
    deadline = time.monotonic() + 8
    while not release.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert release.exists()
    value = DiarizationResult(
        (),
        True,
        audio_sha256=audio_hash,
        model_manifest_sha256=config.manifest_sha256,
        warnings=("ANONYMOUS_ESTIMATE",),
    )
    reply.send_bytes(json.dumps(asdict(value)).encode())
    reply.close()


def test_product_multiprocessing_owns_actual_base_interpreter_not_venv_launcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = synthetic_audio(tmp_path)
    config = DiarizationConfig(tmp_path / "absent.json", "b" * 64, True, timeout_seconds=15)
    provider = LocalDiarizationProcess(config)
    monkeypatch.setattr(
        LocalDiarizationProcess,
        "capabilities",
        lambda self: {"platform_supported": True, "dependencies": {"fake": "installed"}},
    )
    monkeypatch.setattr(process, "_worker", _spawn_probe)
    results: list[DiarizationResult] = []
    errors: list[BaseException] = []

    def invoke() -> None:
        try:
            results.append(provider.diarize(request))
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=invoke)
    thread.start()
    try:
        report = request.audio_path.with_suffix(".spawn.json")
        for _ in range(800):
            if report.exists():
                break
            assert thread.is_alive(), errors
            threading.Event().wait(0.01)
        assert report.exists()
        value = json.loads(report.read_bytes())
        assert value["pid"] == provider._process.pid
        api = _win_observer()
        api.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        api.QueryFullProcessImageNameW.restype = wintypes.BOOL
        handle = api.OpenProcess(0x1000, False, value["pid"])
        assert handle
        try:
            buffer, size = ctypes.create_unicode_buffer(32768), wintypes.DWORD(32768)
            assert api.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size))
            assert (
                Path(buffer.value).resolve()
                == Path(getattr(sys, "_base_executable", sys.executable)).resolve()
            )
        finally:
            api.CloseHandle(handle)
        request.audio_path.with_suffix(".release").write_text("release only our fake child")
        thread.join(10)
        assert not thread.is_alive() and not errors
        assert results[0].complete and provider._process is None
    finally:
        request.audio_path.with_suffix(".release").touch()
        provider.close()
        thread.join(10)


@pytest.mark.parametrize(
    "mutation",
    [
        "audio_hash",
        "manifest_hash",
        "track",
        "before",
        "after",
        "bool",
        "partial_turns",
        "no_estimate",
    ],
)
def test_parent_rejects_cross_input_or_malformed_byte_reply(tmp_path: Path, mutation: str) -> None:
    request = DiarizationRequest(tmp_path / "derived.wav", 4000, "system")
    value = asdict(
        DiarizationResult(
            (SpeakerTurn(4000, 5000, "speaker_anonymous_0", "system"),),
            True,
            audio_sha256="a" * 64,
            model_manifest_sha256="b" * 64,
            warnings=("ANONYMOUS_ESTIMATE",),
        )
    )
    if mutation == "audio_hash":
        value["audio_sha256"] = "c" * 64
    elif mutation == "manifest_hash":
        value["model_manifest_sha256"] = "c" * 64
    elif mutation == "track":
        value["turns"][0]["track_id"] = "mic"
    elif mutation == "before":
        value["turns"][0]["start_ms"] = 3999
    elif mutation == "after":
        value["turns"][0]["end_ms"] = 5001
    elif mutation == "bool":
        value["complete"] = 1
    elif mutation == "partial_turns":
        value["complete"] = False
    else:
        value["warnings"] = []
    with pytest.raises(ProviderError, match="DIARIZATION_RESULT_INVALID"):
        process._decode(json.dumps(value).encode(), request, 1000, "a" * 64, "b" * 64)


@pytest.mark.parametrize("boundary", ["cancel", "close", "deadline"])
def test_result_during_child_cleanup_respects_cancellation_and_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    request = synthetic_audio(tmp_path)
    config = DiarizationConfig(tmp_path / "absent.json", "b" * 64, True, timeout_seconds=1)
    provider = LocalDiarizationProcess(config)
    execution = ExecutionContext()
    clock = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        LocalDiarizationProcess,
        "capabilities",
        lambda self: {"platform_supported": True, "dependencies": {"fake": "installed"}},
    )
    closed = []

    class Guard:
        def attach(self, pid: int) -> None:
            assert pid == 123456  # pure fake identity, never passed to the OS

        def close(self) -> None:
            closed.append("guard")

    class Reply:
        data = b""

        def poll(self, timeout: float) -> bool:
            return True

        def recv_bytes(self, maximum: int) -> bytes:
            return self.data

        def close(self) -> None:
            closed.append("reply")

    reply = Reply()

    class Child:
        pid = 123456
        alive = True

        def start(self) -> None:
            pass

        def is_alive(self) -> bool:
            return self.alive

        def join(self, timeout: float) -> None:
            # Decoded success exists, but final owned-child ACK is still in flight.
            if boundary == "cancel":
                execution.cancel.set()
            elif boundary == "close":
                provider._closed.set()
            else:
                clock[0] = 2.0
            self.alive = False

        def close(self) -> None:
            closed.append("child")

    def make_child(**kwargs: Any) -> Child:
        audio_hash = kwargs["args"][2]
        reply.data = json.dumps(
            asdict(
                DiarizationResult(
                    (),
                    True,
                    audio_sha256=audio_hash,
                    model_manifest_sha256=config.manifest_sha256,
                    warnings=("ANONYMOUS_ESTIMATE",),
                )
            )
        ).encode()
        return Child()

    fake = SimpleNamespace(
        Event=threading.Event,
        Pipe=lambda duplex: (reply, SimpleNamespace(close=lambda: None)),
        Process=make_child,
    )
    monkeypatch.setattr(multiprocessing, "get_context", lambda mode: fake)
    monkeypatch.setattr(process, "ChildJob", Guard)
    result = provider.diarize(request, execution)
    assert closed == ["child", "guard", "reply"]
    assert not result.complete, "A result cannot be final before owned-child cleanup ACK"
    assert result.error_code == ("TIMEOUT" if boundary == "deadline" else "CANCELLED")


def _win_observer() -> Any:
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    api.OpenProcess.restype = wintypes.HANDLE
    api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    api.WaitForSingleObject.restype = wintypes.DWORD
    api.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    api.TerminateProcess.restype = wintypes.BOOL
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.CloseHandle.restype = wintypes.BOOL
    return api


@pytest.mark.parametrize("boundary", ["closed_gate", "precancel", "allowed_fake"])
def test_production_worker_cannot_read_or_compute_before_start_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    calls: list[str] = []
    replies: list[bytes] = []
    for name in ("HF_HUB_OFFLINE", "HF_HUB_DISABLE_TELEMETRY", "DO_NOT_TRACK"):
        monkeypatch.setenv(name, "1")

    def fake_compute(*args: Any) -> DiarizationResult:
        calls.append("compute")
        return DiarizationResult((), False, error_code="SYNTHETIC_NO_MODEL")

    def wait(timeout: float) -> bool:
        assert timeout == 10
        calls.append("gate")
        return boundary != "closed_gate"

    monkeypatch.setattr(process, "compute", fake_compute)
    reply = SimpleNamespace(send_bytes=replies.append, close=lambda: calls.append("close"))
    process._worker(
        DiarizationConfig(tmp_path / "must-not-read.json", "a" * 64, True),
        DiarizationRequest(tmp_path / "must-not-read.wav"),
        "b" * 64,
        SimpleNamespace(wait=wait),
        SimpleNamespace(is_set=lambda: boundary == "precancel"),
        reply,
    )
    assert list(tmp_path.iterdir()) == []
    if boundary == "allowed_fake":
        assert calls == ["gate", "compute", "close"]
        assert json.loads(replies[0])["error_code"] == "SYNTHETIC_NO_MODEL"
    else:
        assert calls == ["gate", "close"] and replies == []


def test_real_job_parent_death_kills_attached_child_and_preserves_unrelated_owned_child(
    tmp_path: Path,
) -> None:
    assert sys.platform == "win32"
    base_executable = getattr(sys, "_base_executable", sys.executable)
    assert Path(base_executable).is_file()
    child_program = "import threading; threading.Event().wait(40)"
    report = tmp_path / "owned-child.json"
    supervisor_program = """
import json, subprocess, sys, threading
from pathlib import Path
from recoryn.diarization._job import ChildJob
base = getattr(sys, '_base_executable', sys.executable)
assert Path(base).is_file()
child = subprocess.Popen([base, '-c', sys.argv[2]], creationflags=subprocess.CREATE_NO_WINDOW)
guard = ChildJob()
try:
    guard.attach(child.pid)
    report = Path(sys.argv[1])
    staging = report.with_suffix('.tmp')
    staging.write_text(json.dumps({'pid':child.pid}))
    staging.replace(report)
    threading.Event().wait(40)
finally:
    guard.close()
    child.wait(timeout=5)
"""
    environment = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")}
    supervisor = subprocess.Popen(
        [base_executable, "-c", supervisor_program, str(report), child_program],
        env=environment,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    bystander = subprocess.Popen(
        [base_executable, "-c", child_program], creationflags=subprocess.CREATE_NO_WINDOW
    )
    api, handle = _win_observer(), None
    try:
        for _ in range(500):
            if report.exists():
                break
            assert supervisor.poll() is None
            threading.Event().wait(0.01)
        assert report.exists(), "owned supervisor did not report guard attachment"
        pid = json.loads(report.read_text())["pid"]
        assert pid not in {supervisor.pid, bystander.pid, os.getpid()}
        handle = api.OpenProcess(0x100001, False, pid)  # synchronize + terminate, this child only
        assert handle and api.WaitForSingleObject(handle, 0) == 258
        supervisor.terminate()
        supervisor.wait(timeout=5)
        assert api.WaitForSingleObject(handle, 5000) == 0
        assert bystander.poll() is None
    finally:
        for owned in (supervisor, bystander):
            if owned.poll() is None:
                owned.terminate()
            owned.wait(timeout=5)
        if handle:
            if api.WaitForSingleObject(handle, 0) == 258:
                api.TerminateProcess(handle, 1)
                assert api.WaitForSingleObject(handle, 5000) == 0
            api.CloseHandle(handle)
