"""G13 integration rows: R (source changes 144), P (paths 112), L (bundle lifetime 100),
D (strict diarization 48), I (keys, evidence and queued snapshots 64) and J (failure
classification 64).

Real OS TEMP files, real share-deny guards (Windows) and the product's re-check, copy,
seal and child-side reads; loaders and sherpa are fakes that record exactly the bytes they
received. Expected outcomes are hand-written from docs/testing/g13-manual-model-cases.md
sections 5-7 and the G-P07 table in its revision section. No model weights, network, GPU,
download or user folder is used.
"""

from __future__ import annotations

import errno
import hashlib
import itertools
import json
import os
import shutil
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from recoryn.app.inference import LocalSTTProcess
from recoryn.diarization import DiarizationConfig, DiarizationRequest, LocalDiarizationProcess
from recoryn.diarization import backend as diarization_backend
from recoryn.diarization.models import verified_bundle
from recoryn.domain import ValidationError
from recoryn.jobs import JobStore
from recoryn.jobs.runner import BoundedRunner
from recoryn.models import ModelManager
from recoryn.models import artifacts as art
from recoryn.models._artifact_io import (
    ArtifactError,
    ArtifactIo,
    acquire,
    diarization_files,
    diarization_snapshot,
    freeze,
    hash_file,
    managed_snapshot,
    release,
    release_idle,
    whisper_files,
    whisper_snapshot,
)
from recoryn.models.manager import FileSpec, ModelSpec, spec_digest
from recoryn.models.resources import ResourcePlan, ResourceRequest
from recoryn.providers import ProviderError
from recoryn.transcription import FasterWhisperProvider
from recoryn.ui.ai_bridge import OwnedDiarization, OwnedSTT, local_result_key, model_request

pytestmark = pytest.mark.integration

FILES = {
    "config.json": b'{"synthetic":1}',
    "model.bin": b"synthetic model bytes, not weights",
    "tokenizer.json": b'{"tokens":[]}',
}
LICENSE = b"Synthetic license text"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write(folder: Path, files: dict[str, bytes]) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (folder / name).write_bytes(data)
    return folder


def confirm(registry: art.ConfirmationRegistry, snapshot: Any) -> Any:
    return registry.confirm(
        snapshot, shown=registry.key(snapshot), accepted=True, acknowledged=True
    )


def manifest(
    folder: Path, *, variant: bytes = b"", extra: dict[str, Any] | None = None
) -> DiarizationConfig:
    folder.mkdir(parents=True, exist_ok=True)
    models = {}
    for role in ("segmentation", "embedding"):
        data = b"synthetic-not-onnx-" + role.encode() + variant
        (folder / f"{role}.onnx").write_bytes(data)
        (folder / f"LICENSE.{role}.txt").write_bytes(LICENSE)
        models[role] = {
            "file": f"{role}.onnx",
            "size": len(data),
            "sha256": sha(data),
            "license_id": "test-only",
            "license_url": "https://publisher.invalid/license",
            "license_file": f"LICENSE.{role}.txt",
            "license_sha256": sha(LICENSE),
        }
    value: dict[str, Any] = {
        "schema_version": 1,
        "runtime": "sherpa-onnx",
        "runtime_version": "2.0.1",
        "models": models,
    }
    value.update(extra or {})
    path = folder / "manifest.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return DiarizationConfig(path, sha(path.read_bytes()), True)


def diarization_of(config: DiarizationConfig, io: ArtifactIo | None = None) -> Any:
    files, terms = verified_bundle(config)
    return diarization_snapshot(
        files,
        config.manifest_path.parent,
        license_id=terms["license_id"],
        license_url=terms["license_url"],
        reference=config.manifest_sha256,
        io=io,
    )


class Factory:
    """A fake Whisper loader: reads back exactly what the mapping gave it."""

    def __init__(self, during: Any = None) -> None:
        self.received: dict[str, bytes] | None = None
        self.during = during

    def __call__(self, identifier: str, **options: Any) -> Any:
        if self.during is not None:
            self.during()  # a change while the loader runs
        self.received = {
            name: value if isinstance(value, bytes) else value.read()
            for name, value in options["files"].items()
        }
        return SimpleNamespace(model=None)


def whisper_load(bundle: Any, folder: Path, during: Any = None) -> dict[str, bytes]:
    factory = Factory(during)
    provider = FasterWhisperProvider(folder, model_factory=factory, bundle=bundle.description())
    provider.load()
    provider.close()
    assert factory.received is not None
    return factory.received


class _Execution:
    cancel = None


def sherpa(monkeypatch: pytest.MonkeyPatch, seen: list[bytes], external: bool = False) -> None:
    """A fake sherpa-onnx/onnx pair reading the bundle paths it is given."""
    import numpy as np

    class Proto:
        def __init__(self) -> None:
            self.DESCRIPTOR = SimpleNamespace(full_name="onnx.ModelProto")

        def HasField(self, name: str) -> bool:  # noqa: N802 - protobuf API
            return True

        def ListFields(self) -> list[Any]:  # noqa: N802 - protobuf API
            if not external:
                return []
            tensor = SimpleNamespace(
                DESCRIPTOR=SimpleNamespace(full_name="onnx.TensorProto"),
                external_data=[1],
                data_location=1,
                ListFields=lambda: [],
            )
            return [(SimpleNamespace(type=11, is_repeated=False), tensor)]

    def settings(**kwargs: Any) -> Any:
        return SimpleNamespace(**kwargs, validate=lambda: True)

    class Native:
        sample_rate = 16000

        def __init__(self, value: Any) -> None:
            for part in (value.segmentation.pyannote, value.embedding):
                seen.append(Path(part.model).read_bytes())

        def process(self, samples: Any, callback: Any) -> Any:
            return SimpleNamespace(
                sort_by_start_time=lambda: [SimpleNamespace(start=0.0, end=0.5, speaker=0)]
            )

    sdk = SimpleNamespace(
        **{
            name: settings
            for name in (
                "OfflineSpeakerDiarizationConfig",
                "OfflineSpeakerSegmentationModelConfig",
                "OfflineSpeakerSegmentationPyannoteModelConfig",
                "SpeakerEmbeddingExtractorConfig",
                "FastClusteringConfig",
            )
        },
        OfflineSpeakerDiarization=Native,
    )
    parser = SimpleNamespace(load_model_from_string=lambda data, format: Proto())
    monkeypatch.setattr(
        diarization_backend,
        "_module",
        lambda name, version=None: {"sherpa_onnx": sdk, "onnx": parser, "numpy": np}[name],
    )


def wav(tmp: Path) -> DiarizationRequest:
    import wave

    path = tmp / "audio.wav"
    with wave.open(str(path), "wb") as stream:
        stream.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        stream.writeframes(b"\x01\x00" * 16000)
    return DiarizationRequest(path)


def managed(tmp: Path, files: dict[str, bytes]) -> tuple[Any, str]:
    specs = tuple(
        FileSpec(name, f"https://publisher.invalid/{name}", len(data), sha(data))
        for name, data in files.items()
    )
    spec = ModelSpec("whisper-r", "whisper", "test-only", "https://publisher.invalid/l", specs)
    urls = {f"https://publisher.invalid/{name}": value for name, value in files.items()}
    manager = ModelManager(
        tmp / "models", downloader=lambda url, offset: iter([urls[url][offset:]])
    )
    manager.install(spec, approved=True)
    return manager, spec_digest(spec)


@pytest.fixture(autouse=True)
def _idle_copies_released() -> Any:
    """Sealed copies kept for reuse never outlive one row (G13R-03 a)."""
    yield
    release_idle()


# --- R: change time 6 x change 6 x managed/manual 2 x role 2 = 144 --------------------

R_TIMES = ("preview", "yes", "queued", "copy", "sealed", "native")
R_CHANGES = ("bytes", "metadata", "optional", "license", "same_size", "root")
R_ROWS = list(
    itertools.product(R_TIMES, R_CHANGES, ("managed", "manual"), ("whisper", "diarization"))
)
R_CASES = [pytest.param(*row, id=f"G13-R-{i:03d}") for i, row in enumerate(R_ROWS, 1)]


class Hook(ArtifactIo):
    """Runs ``change`` once, right after the first byte block is written to the bundle."""

    def __init__(self, change: Any) -> None:
        self.change, self.done = change, False

    def write(self, stream: Any, data: bytes) -> None:
        super().write(stream, data)
        if not self.done:
            self.done = True
            self.change()


def whisper_change(folder: Path, change: str) -> None:
    if change == "bytes":
        (folder / "model.bin").write_bytes(b"other synthetic model bytes")
    elif change == "metadata":
        (folder / "config.json").write_bytes(b'{"synthetic":2}')
    elif change == "optional":
        (folder / "preprocessor_config.json").write_bytes(b'{"feature_size":80}')
    elif change == "license":
        (folder / "LICENSE").write_bytes(b"Another license text")
    elif change == "same_size":
        (folder / "model.bin").write_bytes(bytes(reversed(FILES["model.bin"])))
    else:  # the folder is replaced by another one with the same bytes
        moved = folder.with_name(folder.name + "-old")
        os.replace(folder, moved)
        shutil.copytree(moved, folder)


def diarization_change(folder: Path, change: str) -> None:
    if change == "bytes":
        (folder / "segmentation.onnx").write_bytes(b"synthetic-not-onnx-other")
    elif change == "metadata":
        manifest(folder, extra={})  # rewritten with other bytes below
        value = json.loads((folder / "manifest.json").read_bytes())
        value["models"]["segmentation"]["license_id"] = "changed-id"
        (folder / "manifest.json").write_text(json.dumps(value), encoding="utf-8")
    elif change == "optional":
        value = json.loads((folder / "manifest.json").read_bytes())
        value["extra_model"] = {"file": "extra.onnx"}  # outside the manifest contract
        (folder / "manifest.json").write_text(json.dumps(value), encoding="utf-8")
    elif change == "license":
        (folder / "LICENSE.segmentation.txt").write_bytes(b"Another license text!!")
    elif change == "same_size":
        data = (folder / "segmentation.onnx").read_bytes()
        (folder / "segmentation.onnx").write_bytes(bytes(reversed(data)))
    else:
        moved = folder.with_name(folder.name + "-old")
        os.replace(folder, moved)
        shutil.copytree(moved, folder)


@pytest.mark.parametrize(("time", "change", "source", "role"), R_CASES)
def test_only_confirmed_bytes_reach_native_and_later_changes_need_a_new_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, time: str, change: str, source: str, role: str
) -> None:
    registry = art.ConfirmationRegistry()
    if role == "whisper":
        files = dict(FILES, LICENSE=LICENSE)
        if source == "managed":
            manager, pin = managed(tmp_path, files)
            folder = manager.root / "whisper-r"

            def snap() -> Any:
                return managed_snapshot(manager, "whisper-r", pin)

        else:
            folder = write(tmp_path / "user" / "whisper", files)

            def snap() -> Any:
                return whisper_snapshot(folder)

        def apply() -> None:
            whisper_change(folder, change)

    else:
        base = tmp_path / ("models" if source == "managed" else "user") / "diarization"
        config = manifest(base)
        folder = base

        def snap() -> Any:
            return diarization_of(config)

        def apply() -> None:
            diarization_change(folder, change)

    shown = snap()  # the preview
    expected_bytes = {
        entry.name: entry.sha256 for entry in shown.entries if entry.state == "PRESENT"
    }
    if time == "preview":
        apply()  # before Yes: the dialog still answers for the shown bytes only
    confirm(registry, shown)
    if time == "yes":
        apply()
    try:
        admitted = snap()
        evidence = registry.evidence(admitted)  # admission captures the evidence
    except ProviderError:
        evidence = None
    if time in ("preview", "yes"):
        assert evidence is None  # MODEL_CONFIRMATION_REQUIRED: nothing admitted or loaded
        return
    assert evidence is not None
    if time == "queued":
        apply()
    io: ArtifactIo = Hook(apply) if time == "copy" else ArtifactIo()
    native: dict[str, bytes] | None = None
    seen: list[bytes] = []
    try:
        if role == "whisper":
            bundle = freeze(evidence, parent=tmp_path, io=io)
        else:
            provider = LocalDiarizationProcess(
                config, model_evidence=evidence, bundle_parent=tmp_path
            )
            if time == "copy":
                monkeypatch.setattr(
                    "recoryn.models._artifact_io.ArtifactIo", lambda: io, raising=True
                )
            bundle = provider._seal(_Execution())  # type: ignore[arg-type]
            monkeypatch.undo()
    except ProviderError:
        bundle = None
    if time in ("queued",) or (time == "copy" and role == "whisper"):
        assert bundle is None  # changed before the seal: refused, native 0
        assert not [p for p in tmp_path.iterdir() if p.name.startswith("recoryn-model-bundle")]
        return
    assert bundle is not None
    try:
        if time == "sealed":
            apply()
        if role == "whisper":
            native = whisper_load(bundle, folder, apply if time == "native" else None)
            got = {name: sha(data) for name, data in native.items() if name in expected_bytes}
        else:
            sherpa(monkeypatch, seen)
            if time == "native":
                apply()
            diarization_backend.compute(
                config,
                wav(tmp_path),
                threading.Event(),
                sha(wav(tmp_path).audio_path.read_bytes()),
                bundle.description(),
            )
            got = {
                "segmentation.onnx": sha(seen[0]),
                "embedding.onnx": sha(seen[1]),
            }
            expected_bytes = {name: expected_bytes[name] for name in got}
        assert got == {name: expected_bytes[name] for name in got}  # the confirmed bytes
    finally:
        release(bundle)  # the product's end of use (the idle copy is retired per row)
    # The next request re-checks the original source: the change needs a new confirmation.
    try:
        following = registry.evidence(snap())
    except ProviderError:
        following = None
    assert following is None  # the old confirmation never covers the changed source


# --- P: path 14 x stage 4 x role 2 = 112 --------------------------------------------

P_KINDS = (
    "fixed",
    "removable",
    "ramdisk",
    "relative",
    "unc",
    "device",
    "extended",
    "network",
    "symlink",
    "junction",
    "hardlink",
    "ads",
    "case_alias",
    "short_alias",
)
P_STAGES = ("preview", "hash", "copy", "child")
P_ROWS = list(itertools.product(P_KINDS, P_STAGES, ("whisper", "diarization")))
P_CASES = [pytest.param(*row, id=f"G13-P-{i:03d}") for i, row in enumerate(P_ROWS, 1)]
ALLOWED = {"fixed", "removable", "ramdisk", "case_alias", "short_alias"}
NO_ACCESS = {"relative", "unc", "device", "extended", "ads"}


def _local_only(path: Path) -> None:
    """A watched call must never receive a UNC/device path (no OS or network access)."""
    text = str(path)
    assert not text.startswith(("\\\\", "//")), "a non-local path reached the filesystem"


class Spy(ArtifactIo):
    def __init__(self, drive: int = 3, link: bool = False) -> None:
        self.drive, self.link, self.calls = drive, link, []

    def drive_type(self, anchor: str) -> int:
        self.calls.append("drive")
        return self.drive

    def check(self, path: Path) -> None:
        self.calls.append("check")
        _local_only(path)
        if self.link:
            raise ValidationError("Links and reparse points are not supported")
        super().check(path)

    def stat(self, path: Path) -> os.stat_result:
        self.calls.append("stat")
        _local_only(path)
        return super().stat(path)

    def open_read(self, path: Path) -> Any:
        self.calls.append("open")
        _local_only(path)
        return super().open_read(path)

    def realpath(self, path: Path) -> str:
        self.calls.append("realpath")
        _local_only(path)
        return super().realpath(path)


def short_name(path: Path) -> Path:
    import ctypes
    from ctypes import wintypes

    function = ctypes.windll.kernel32.GetShortPathNameW
    function.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
    buffer = ctypes.create_unicode_buffer(32768)
    length = function(str(path), buffer, 32768)
    return Path(buffer.value) if length else path  # a volume without 8.3 names: same path


def p_path(real: Path, kind: str) -> tuple[Path, Spy]:
    if kind in ("removable", "ramdisk", "network"):
        return real, Spy(drive={"removable": 2, "ramdisk": 6, "network": 4}[kind])
    if kind == "relative":
        return Path("relative") / real.name, Spy()
    if kind == "unc":
        return Path(r"\\g13-server\share") / real.name, Spy()
    if kind == "device":
        return Path("\\\\.\\" + str(real)), Spy()
    if kind == "extended":
        return Path("\\\\?\\" + str(real)), Spy()
    if kind == "symlink":
        return real, Spy(link=True)  # the OS answers that a component is a link
    if kind == "junction":
        import _winapi

        moved = real.with_name(real.name + "-target")
        os.replace(real, moved)
        _winapi.CreateJunction(str(moved), str(real))
        return real, Spy()
    if kind == "hardlink":
        target = real / ("model.bin" if (real / "model.bin").exists() else "segmentation.onnx")
        os.link(target, real.parent / (target.name + ".alias"))
        return real, Spy()
    if kind == "ads":
        return Path(str(real) + ":stream"), Spy()
    if kind == "case_alias":
        return Path(str(real).upper()), Spy()
    if kind == "short_alias":
        return short_name(real), Spy()
    return real, Spy()


@pytest.mark.parametrize(("kind", "stage", "role"), P_CASES)
def test_only_local_inspected_paths_are_read(
    tmp_path: Path, kind: str, stage: str, role: str
) -> None:
    if role == "whisper":
        real = write(tmp_path / "model", FILES)
        name = "model.bin"
    else:
        config = manifest(tmp_path / "model")
        real = config.manifest_path.parent
        name = "segmentation.onnx"
    registry = art.ConfirmationRegistry()
    canonical = whisper_snapshot(real) if role == "whisper" else diarization_of(config)
    evidence = confirm(registry, canonical)
    sealed = None
    if stage == "child":
        sealed = (
            freeze(evidence, parent=tmp_path)
            if role == "whisper"
            else freeze(evidence, data=verified_bundle(config)[0], parent=tmp_path)
        )
        real = sealed.directory
    if stage == "child" and kind in ("symlink", "junction", "hardlink"):
        path, spy = real, Spy(link=True)  # a sealed bundle is never relinked: the OS answer
    else:
        path, spy = p_path(real, kind)
    before = {p.name: p.read_bytes() for p in Path(real).iterdir() if p.is_file()}
    try:
        if stage == "preview":
            if role == "whisper":
                result: Any = whisper_snapshot(path, io=spy)
            else:
                result = diarization_snapshot(
                    verified_bundle(config)[0],
                    path,
                    license_id="x",
                    license_url="https://publisher.invalid/l",
                    reference=config.manifest_sha256,
                    io=spy,
                )
        elif stage == "hash":
            result = hash_file(path / name, spy)
        elif stage == "copy":
            shown = replace(canonical, root=str(path))
            forged = art.ModelUseEvidence(evidence.record_id, evidence.key, shown, registry)
            if role == "whisper":
                result = freeze(forged, parent=tmp_path, io=spy)
            else:
                result = diarization_snapshot(
                    verified_bundle(config)[0],
                    path,
                    license_id="x",
                    license_url="https://publisher.invalid/l",
                    reference=config.manifest_sha256,
                    io=spy,
                )
        else:
            description = dict(sealed.description(), directory=str(path))
            result = (whisper_files if role == "whisper" else diarization_files)(description, spy)
        allowed = True
    except (ProviderError, ValidationError):
        allowed = False
        result = None
    try:
        assert allowed is (kind in ALLOWED), (kind, stage, role)
        if kind in NO_ACCESS:
            assert spy.calls == []  # judged by its text: nothing resolved, stat'ed or opened
        if kind == "network":
            assert spy.calls == ["drive"]  # the local mount table only
        if allowed and stage == "preview" and role == "whisper":
            assert result.root_identity[:2] == canonical.root_identity[:2]
            assert result.root_identity[2] == canonical.root_identity[2]  # one real root
        if allowed and stage == "hash":
            assert result[1] == sha(before[name])
        if stage == "copy" and allowed and role == "whisper":
            result.close()
        if stage == "child" and allowed and role == "whisper":
            for stream in result[1]:
                stream.close()
        assert {p.name: p.read_bytes() for p in Path(real).iterdir() if p.is_file()} == before
    finally:
        if sealed is not None:
            sealed.close()


@pytest.mark.parametrize("case_id", ["G13-X-01"], ids=["G13-X-01"])
def test_a_sibling_with_the_root_as_prefix_is_another_root(tmp_path: Path, case_id: str) -> None:
    """G13-X-01 (P supplement): ``models-evil`` is not inside ``models``."""
    inside = whisper_snapshot(write(tmp_path / "models", FILES))
    sibling = whisper_snapshot(write(tmp_path / "models-evil", FILES))
    assert inside.root_identity != sibling.root_identity
    registry = art.ConfirmationRegistry()
    confirm(registry, inside)
    assert registry.evidence(sibling) is None


@pytest.mark.parametrize("case_id", ["G13-X-06"], ids=["G13-X-06"])
def test_a_queued_job_never_swaps_in_a_newer_confirmation(tmp_path: Path, case_id: str) -> None:
    """G13-X-06 (I/R supplement): a queued worker keeps the evidence of its admission.
    The source changed and the user confirmed the new bytes meanwhile: the queued Job
    still refuses (its own bytes are gone) instead of running the newer ones."""
    folder = write(tmp_path / "model", FILES)
    registry = art.ConfirmationRegistry()
    admitted = confirm(registry, whisper_snapshot(folder))
    bundles = tmp_path / "bundles"
    bundles.mkdir()
    queued = LocalSTTProcess(folder, model_evidence=admitted, bundle_parent=bundles)
    (folder / "model.bin").write_bytes(b"newer synthetic bytes")
    newer = confirm(registry, whisper_snapshot(folder))
    assert newer is not None and admitted.valid()
    with pytest.raises(ProviderError, match="MODEL_CHECKSUM_MISMATCH"):
        queued._start()
    assert queued._process is None and list(bundles.iterdir()) == []


# --- L: lifetime state 5 x event 5 x other waiter 2 x role 2 = 100 --------------------

L_STATES = ("QUEUED", "SEALED", "NATIVE_RUNNING", "REAP_PENDING", "CLOSED")
L_EVENTS = ("cancel", "load_fail", "disk_full", "delete_model", "replace_source")
L_ROWS = list(itertools.product(L_STATES, L_EVENTS, (False, True), ("whisper", "diarization")))
L_CASES = [pytest.param(*row, id=f"G13-L-{i:03d}") for i, row in enumerate(L_ROWS, 1)]


class Child:
    def __init__(self, stays: bool) -> None:
        self.alive, self.stays, self.pid = True, stays, 123456

    def is_alive(self) -> bool:
        return self.alive

    def join(self, timeout: float | None = None) -> None:
        if not self.stays:
            self.alive = False

    def terminate(self) -> None:
        if not self.stays:
            self.alive = False

    def close(self) -> None:
        pass


class Channel:
    def put_nowait(self, item: Any) -> None:
        pass

    def cancel_join_thread(self) -> None:
        pass

    def close(self) -> None:
        pass


def l_owner(role: str, evidence: Any, folder: Path, config: Any, bundles: Path) -> Any:
    if role == "whisper":
        return LocalSTTProcess(folder, model_evidence=evidence, bundle_parent=bundles)
    return LocalDiarizationProcess(config, model_evidence=evidence, bundle_parent=bundles)


def l_seal(owner: Any, role: str) -> Any:
    """The product's per-Job acquisition (re-check, then reuse or seal)."""
    if role == "whisper":
        owner._bundle = acquire(owner.model_evidence, parent=owner.bundle_parent)
    else:
        owner._bundle = owner._seal(_Execution())
    return owner._bundle


def l_close(owner: Any, role: str) -> None:
    if role == "whisper":
        owner.close()
    else:
        owner._reap()


@pytest.mark.parametrize(("state", "event", "waiter", "role"), L_CASES)
def test_a_bundle_lives_exactly_until_the_child_exit_ack(
    tmp_path: Path, state: str, event: str, waiter: bool, role: str
) -> None:
    bundles = tmp_path / "bundles"
    bundles.mkdir()
    if role == "whisper":
        folder = write(tmp_path / "model", FILES)
        snapshot_of = lambda: whisper_snapshot(folder)  # noqa: E731
        config = None
    else:
        config = manifest(tmp_path / "model")
        folder = config.manifest_path.parent
        snapshot_of = lambda: diarization_of(config)  # noqa: E731
    registry = art.ConfirmationRegistry()
    evidence = confirm(registry, snapshot_of())
    source = {p.name: p.read_bytes() for p in folder.iterdir()}
    owner = l_owner(role, evidence, folder, config, bundles)
    other = l_owner(role, evidence, folder, config, bundles) if waiter else None
    other_bundle = l_seal(other, role) if other is not None else None
    bundle = None
    if state != "QUEUED":
        bundle = l_seal(owner, role)
        if state in ("NATIVE_RUNNING", "REAP_PENDING", "CLOSED"):
            owner._process = Child(stays=state == "REAP_PENDING")
            if role == "whisper":
                owner._requests = owner._replies = Channel()
        if state == "CLOSED":
            l_close(owner, role)
    # The event.
    if event == "delete_model":
        shutil.rmtree(folder)  # the user's explicit deletion (never this code's)
    elif event == "replace_source":
        whisper_change(folder, "root") if role == "whisper" else diarization_change(folder, "root")
    outcome = None
    if state == "QUEUED":
        try:
            if event == "disk_full":

                class Full(ArtifactIo):
                    def write(self, stream: Any, data: bytes) -> None:
                        raise OSError(errno.ENOSPC, "full")

                if role == "whisper":
                    freeze(evidence, parent=bundles, io=Full())
                else:
                    freeze(evidence, data=verified_bundle(config)[0], parent=bundles, io=Full())
            elif event == "cancel":
                cancel = threading.Event()
                cancel.set()
                if role == "whisper":
                    freeze(evidence, parent=bundles, cancel=cancel)
                else:
                    freeze(evidence, data=verified_bundle(config)[0], parent=bundles, cancel=cancel)
            elif event in ("delete_model", "replace_source"):
                l_seal(owner, role)
            outcome = "started" if event == "load_fail" else "sealed"
        except ProviderError as error:
            outcome = error.code
        expected = {
            "cancel": "CANCELLED",
            "load_fail": "started",  # a late answer for nothing started: no effect
            "disk_full": "RESOURCE_EXHAUSTED",
            "delete_model": "refused",
            "replace_source": "refused",
        }[event]
        if expected == "refused":
            assert outcome not in ("sealed", "started") and outcome is not None
        else:
            assert outcome == expected
        own = [p for p in bundles.iterdir() if other_bundle is None or p != other_bundle.directory]
        assert own == []  # no partial bundle is ever left behind
    else:
        if event in ("cancel", "load_fail") and state in ("SEALED", "NATIVE_RUNNING"):
            l_close(owner, role)  # the owner closes after the child's exit ACK
        if state == "REAP_PENDING":
            with pytest.raises(ProviderError, match="ACK_PENDING"):
                l_close(owner, role)  # the child did not exit: the guard stays
        assert bundle is not None
        ended = state == "CLOSED" or (event in ("cancel", "load_fail") and state != "REAP_PENDING")
        assert (owner._bundle is None) is ended  # this Job's use ended only after the ACK
        # The copy stays sealed either way: in use, or idle for the next Job of the same
        # confirmation (C00 decision a). Its bytes are still the confirmed ones.
        assert bundle.sealed and bundle.directory.exists()
        for entry in bundle.snapshot.entries:
            if entry.state == "PRESENT":
                assert sha((bundle.directory / entry.name).read_bytes()) == entry.sha256
        if other_bundle is not None:
            assert other_bundle is bundle  # the waiter reuses the same sealed copy
        release_idle()  # retire idle copies: only a copy nobody uses is removed
        in_use = not ended or other_bundle is not None
        assert bundle.sealed is in_use and bundle.directory.exists() is in_use
    if event not in ("delete_model", "replace_source"):
        assert {p.name: p.read_bytes() for p in folder.iterdir()} == source  # source intact
    if other_bundle is not None:
        assert other_bundle.sealed and other_bundle.directory.exists()  # still in use
        release(other_bundle)
    if state == "REAP_PENDING":
        owner._process.stays = False  # the child exits at last
    if owner._bundle is not None:
        l_close(owner, role)  # the remaining use ends after its exit ACK
    release_idle()
    assert bundle is None or not bundle.directory.exists()  # nothing outlives its users


# --- D: diarization state 8 x confirmation 3 x stage 2 = 48 -------------------------

D_STATES = (
    "normal",
    "manifest_hash",
    "model_hash",
    "license",
    "future_schema",
    "onnx_external",
    "wrong_role",
    "license_refused",
)
D_ROWS = list(itertools.product(D_STATES, ("none", "current", "old"), ("parent", "child")))
D_CASES = [pytest.param(*row, id=f"G13-D-{i:02d}") for i, row in enumerate(D_ROWS, 1)]
# Hand table: the strict code each damaged state keeps (never relaxed by a confirmation).
D_CODES = {
    "manifest_hash": "DIARIZATION_MANIFEST_CHECKSUM",
    "model_hash": "DIARIZATION_MODEL_CHECKSUM",
    "license": "DIARIZATION_LICENSE_INVALID",
    "future_schema": "DIARIZATION_MANIFEST_INVALID",
    "wrong_role": "DIARIZATION_MANIFEST_INVALID",
    "license_refused": "DIARIZATION_LICENSE_REQUIRED",
}


def d_state(folder: Path, state: str, config: DiarizationConfig) -> DiarizationConfig:
    if state == "manifest_hash":
        return replace(config, manifest_sha256="b" * 64)
    if state == "model_hash":
        (folder / "embedding.onnx").write_bytes(b"synthetic-not-onnx-embeddinG")
    elif state == "license":
        (folder / "LICENSE.embedding.txt").write_bytes(b"Changed license text!!")
    elif state in ("future_schema", "wrong_role"):
        value = json.loads(config.manifest_path.read_bytes())
        if state == "future_schema":
            value["schema_version"] = 2
        else:
            value["models"]["segmentation"]["file"] = "embedding.onnx"
        config.manifest_path.write_text(json.dumps(value), encoding="utf-8")
        return replace(config, manifest_sha256=sha(config.manifest_path.read_bytes()))
    elif state == "license_refused":
        return replace(config, license_accepted=False)
    return config


@pytest.mark.parametrize(("state", "confirmation", "stage"), D_CASES)
def test_diarization_stays_strict_whatever_was_confirmed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str, confirmation: str, stage: str
) -> None:
    folder = tmp_path / "model"
    registry = art.ConfirmationRegistry()
    evidence = None
    if confirmation == "old":  # a confirmation of earlier, valid bytes
        evidence = confirm(registry, diarization_of(manifest(folder, variant=b"-old")))
    config = manifest(folder)
    config = d_state(folder, state, config)
    confirmation_code = None
    if confirmation == "current":
        try:
            evidence = confirm(registry, diarization_of(config))
        except ProviderError as error:
            confirmation_code = error.code  # the strict check refuses the confirmation
    provider = LocalDiarizationProcess(config, model_evidence=evidence, bundle_parent=tmp_path)
    try:
        bundle = provider._seal(_Execution())  # type: ignore[arg-type]
        parent = "SEALED"
    except ProviderError as error:
        bundle, parent = None, error.code
    seen: list[bytes] = []
    try:
        if stage == "parent":
            if confirmation == "none":
                assert parent == "CAPABILITY_UNSUPPORTED"
            elif confirmation == "current":
                if state in ("normal", "onnx_external"):
                    assert parent == "SEALED"
                else:
                    assert (
                        confirmation_code == D_CODES[state] and parent == "CAPABILITY_UNSUPPORTED"
                    )
            elif state in ("normal", "onnx_external"):
                assert parent == "DIARIZATION_MODEL_CHECKSUM"  # other bytes than confirmed
            else:
                assert parent == D_CODES[state]
            return
        sherpa(monkeypatch, seen, external=state == "onnx_external")
        request = wav(tmp_path)
        audio = sha(request.audio_path.read_bytes())
        description = bundle.description() if bundle is not None else None
        try:
            result = diarization_backend.compute(
                config, request, threading.Event(), audio, description
            )
            child = "COMPLETE" if result.complete else result.error_code
        except ProviderError as error:
            child = error.code
        if bundle is None:
            assert child == "CAPABILITY_UNSUPPORTED" and seen == []  # no bundle, no native
        elif state == "onnx_external":
            assert child == "DIARIZATION_EXTERNAL_DATA_DENIED" and seen == []
        else:
            assert child == "COMPLETE" and len(seen) == 2
    finally:
        if bundle is not None:
            release(bundle)


# --- I: key component 8 x role 2 x stage 2 x same/changed 2 = 64 --------------------

COMPONENTS = (
    "artifact_digest",
    "loader_contract",
    "source_kind",
    "terms_digest",
    "root_identity",
    "execution_generation",
    "device_policy",
    "actual_device",
)
I_ROWS = list(
    itertools.product(COMPONENTS, ("whisper", "diarization"), ("prepare", "queued"), (False, True))
)
I_CASES = [pytest.param(*row, id=f"G13-I-{i:02d}") for i, row in enumerate(I_ROWS, 1)]
# Hand table (G13 revision section 2): what changes the result key and what needs a new
# confirmation; device policy and the real device never touch the evidence.
KEY_CHANGES = {"artifact_digest", "loader_contract", "actual_device"}
EVIDENCE_CHANGES = {
    "artifact_digest",
    "loader_contract",
    "source_kind",
    "terms_digest",
    "root_identity",
    "execution_generation",
}


@pytest.mark.parametrize(("component", "role", "stage", "changed"), I_CASES)
def test_result_key_evidence_and_queued_snapshot_are_separate(
    tmp_path: Path, component: str, role: str, stage: str, changed: bool
) -> None:
    registry = art.ConfirmationRegistry()
    if role == "whisper":
        folder = write(tmp_path / "model", dict(FILES, LICENSE=LICENSE))

        def snapshot_of(root: Path = folder, kind: str = art.MANUAL) -> Any:
            return whisper_snapshot(root, source_kind=kind)

    else:
        config = manifest(tmp_path / "model")
        folder = config.manifest_path.parent

        def snapshot_of(root: Path = folder, kind: str = art.MANUAL) -> Any:
            return diarization_of(
                DiarizationConfig(root / "manifest.json", config.manifest_sha256, True)
            )

    base = snapshot_of()
    evidence = confirm(registry, base)
    request = ResourceRequest(
        "stt" if role == "whisper" else "diarization",
        "LOCAL_CT2" if role == "whisper" else "LOCAL_SHERPA",
        "CPU_ONLY",
    )
    queued = OwnedSTT(folder, source=SimpleNamespace(), semantic_device="cpu", evidence=evidence)
    device, policy, variant = "cpu", "CPU_ONLY", base
    if changed:
        if component == "artifact_digest":
            target = "model.bin" if role == "whisper" else None
            if target:
                (folder / target).write_bytes(b"other synthetic bytes")
            else:
                config = manifest(folder, variant=b"-new")
            variant = snapshot_of() if role == "whisper" else diarization_of(config)
        elif component == "loader_contract":
            with pytest.raises(ValidationError):
                art.artifact_digest(base.kind, "another-loader-v9", base.entries)
            variant = None
        elif component == "source_kind":
            variant = (
                snapshot_of(kind=art.MANAGED)
                if role == "whisper"
                else replace(
                    base,
                    source_kind=art.MANAGED,
                    terms=replace(base.terms, source_kind=art.MANAGED),
                    terms_digest="",
                )
            )
        elif component == "terms_digest":
            if role == "whisper":
                (folder / "LICENSE").write_bytes(b"Another license text")
            else:
                (folder / "LICENSE.embedding.txt").write_bytes(b"Another license!!!!!!")
                value = json.loads(config.manifest_path.read_bytes())
                value["models"]["embedding"]["license_sha256"] = sha(b"Another license!!!!!!")
                config.manifest_path.write_text(json.dumps(value), encoding="utf-8")
                config = replace(config, manifest_sha256=sha(config.manifest_path.read_bytes()))
            variant = snapshot_of() if role == "whisper" else diarization_of(config)
        elif component == "root_identity":
            copy = tmp_path / "copy"
            shutil.copytree(folder, copy)
            variant = snapshot_of(copy)
        elif component == "execution_generation":
            registry.new_generation()
        elif component == "device_policy":
            policy = "GPU_WITH_CPU_FALLBACK_ALLOWED"
        elif role == "whisper":
            device = "cuda"
        else:
            with pytest.raises(ProviderError, match="CAPABILITY_UNSUPPORTED"):
                DiarizationConfig(
                    folder / "manifest.json", config.manifest_sha256, True, device="cuda"
                )
            return  # diarization is CPU-only: refused before any confirmation
    if variant is None:  # another loader contract: no snapshot, no key, no evidence
        assert registry.evidence(base) is not None
        return
    if role == "whisper":
        same_key = local_result_key(base.artifact_digest, "cpu") == local_result_key(
            variant.artifact_digest, device
        )
    else:
        same_key = (base.artifact_digest, "cpu") == (variant.artifact_digest, device)
    # A diarization license hash lives inside the pinned manifest (an artifact input), so
    # its terms never change alone: the manifest, and with it the result key, changes too.
    key_changes = KEY_CHANGES | ({"terms_digest"} if role == "diarization" else set())
    assert same_key is not (changed and component in key_changes)
    reusable = registry.evidence(variant) is not None and (
        component != "execution_generation" or not changed
    )
    assert reusable is not (changed and component in EVIDENCE_CHANGES)
    bound = model_request(replace(request, policy=policy), variant)
    assert bound.policy == policy and bound.model_identity == variant.artifact_digest
    if stage == "queued":
        if changed and component in ("artifact_digest", "terms_digest") and art.eligible(variant):
            newer = confirm(registry, variant)  # the panel confirms the new bytes meanwhile
            assert newer is not evidence
        # G13R-09 c: the worker the product creates inside the lease (not an attribute
        # read back) carries the evidence captured at admission, never the panel's newer one.
        owner = queued if role == "whisper" else OwnedDiarization(config, evidence=evidence)
        worker = owner.open(ResourcePlan("0" * 64, True, "cpu", "KNOWN"))
        assert worker.model_evidence is evidence
        refused = changed and component in (
            "artifact_digest",
            "terms_digest",
            "execution_generation",
        )
        try:
            if role == "whisper":
                release(acquire(worker.model_evidence, parent=tmp_path))
            else:
                release(worker._seal(_Execution()))  # type: ignore[arg-type]
            ran = True
        except ProviderError:
            ran = False
        assert ran is not refused


# --- J: failure code 8 x role 2 x path 2 x outcome known 2 = 64 ---------------------

J_CODES = (
    "CAPABILITY_UNSUPPORTED",
    "MODEL_MISSING",
    "MODEL_CHECKSUM_MISMATCH",
    "DIARIZATION_MODEL_CHECKSUM",
    "DIARIZATION_LICENSE_REQUIRED",
    "DIARIZATION_LICENSE_INVALID",
    "RESOURCE_EXHAUSTED",
    "ACK_PENDING",
)
J_ROWS = list(
    itertools.product(J_CODES, ("whisper", "diarization"), ("runner", "direct"), (True, False))
)
J_CASES = [pytest.param(*row, id=f"G13-J-{i:02d}") for i, row in enumerate(J_ROWS, 1)]
# Hand table (G13 revision section 3, the G-P07 closed table): (state, blocked reason).
J_KNOWN = {
    "CAPABILITY_UNSUPPORTED": ("BLOCKED", "CAPABILITY"),
    "MODEL_MISSING": ("BLOCKED", "RESOURCE"),
    "MODEL_CHECKSUM_MISMATCH": ("FAILED", None),
    "DIARIZATION_MODEL_CHECKSUM": ("FAILED", None),
    "DIARIZATION_LICENSE_REQUIRED": ("BLOCKED", "CAPABILITY"),
    "DIARIZATION_LICENSE_INVALID": ("FAILED", None),
    "RESOURCE_EXHAUSTED": ("BLOCKED", "RESOURCE"),
    "ACK_PENDING": ("BLOCKED", "RESOURCE"),
}


@pytest.mark.parametrize(("code", "role", "path", "known"), J_CASES)
def test_model_failures_keep_the_closed_classification(
    tmp_path: Path, code: str, role: str, path: str, known: bool
) -> None:
    if code == "ACK_PENDING":
        code = "INFERENCE_ACK_PENDING" if role == "whisper" else "DIARIZATION_ACK_PENDING"
    kind = "transcription" if role == "whisper" else "diarization"
    with JobStore(tmp_path / "jobs.sqlite") as store:
        job = store.create(kind, "g13-j")
        if path == "direct":
            attempt = store.claim(job.job_id, "worker")
            after = store.fail(job.job_id, attempt.attempt_id, attempt.fence, code, True, known)
        else:
            runner = BoundedRunner(store)
            runner.start()
            try:

                def task(attempt: Any, cancel: Any) -> str:
                    # Through the G13 error wrapper the model paths raise.
                    raise ArtifactError(code, retryable=True, outcome_known=known)

                assert runner.submit(job.job_id, task)
                with runner._condition:
                    assert runner._condition.wait_for(
                        lambda: not runner._queue and not runner._active, timeout=10
                    )
            finally:
                runner.stop()
            after = store.get(job.job_id)
    table = "ACK_PENDING" if code.endswith("_ACK_PENDING") else code
    state, reason = J_KNOWN[table] if known else ("BLOCKED", "REMOTE_UNKNOWN")
    assert (after.state.value, after.blocked_reason) == (state, reason)
    assert after.attempt_count == 1  # retryable=True never turns these into a retry


def test_declared_integration_denominators() -> None:
    assert len(R_CASES) == 6 * 6 * 2 * 2 == 144 and len(P_CASES) == 14 * 4 * 2 == 112
    assert len(L_CASES) == 5 * 5 * 2 * 2 == 100 and len(D_CASES) == 8 * 3 * 2 == 48
    assert len(I_CASES) == 8 * 2 * 2 * 2 == 64 and len(J_CASES) == 8 * 2 * 2 * 2 == 64
