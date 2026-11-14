"""Offline API fixtures and immutable annotation boundaries, without real weights."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import socket
import threading
import wave
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from recoryn.content import ContentStore, Segment
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
from recoryn.providers import ProviderError
from recoryn.storage import Library

pytestmark = pytest.mark.contract


@pytest.fixture(autouse=True)
def deny_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Network attempted")

    monkeypatch.setattr(socket, "socket", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)
    monkeypatch.setattr(socket, "create_connection", denied)


def manifest(tmp_path: Path) -> DiarizationConfig:
    models = {}
    for role in ("segmentation", "embedding"):
        data, license_bytes = (b"synthetic-not-onnx-" + role.encode()), b"Synthetic test license"
        (tmp_path / f"{role}.onnx").write_bytes(data)
        (tmp_path / f"LICENSE.{role}.txt").write_bytes(license_bytes)
        models[role] = {
            "file": f"{role}.onnx",
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "license_id": "test-only",
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
                "models": models,
            }
        ),
        encoding="utf-8",
    )
    return DiarizationConfig(path, hashlib.sha256(path.read_bytes()).hexdigest(), True)


def wav(
    tmp_path: Path, *, channels: int = 1, rate: int = 16000, frames: int = 16000
) -> DiarizationRequest:
    path = tmp_path / "derived.wav"
    with wave.open(str(path), "wb") as stream:
        stream.setparams((channels, 2, rate, 0, "NONE", "not compressed"))
        stream.writeframes(b"\x00\x00" * channels * frames)
    return DiarizationRequest(path, 2000, "mic")


@pytest.mark.parametrize(
    "field,value",
    [
        ("device", "cuda"),
        ("max_audio_ms", 300001),
        ("num_threads", True),
        ("num_speakers", 33),
        ("threshold", float("nan")),
        ("timeout_seconds", float("inf")),
        ("manifest_sha256", "x" * 64),
    ],
)
def test_invalid_configuration_has_no_io(tmp_path: Path, field: str, value: Any) -> None:
    config = DiarizationConfig(tmp_path / "absent.json", "a" * 64)
    with pytest.raises(ProviderError):
        replace(config, **{field: value})
    assert not list(tmp_path.iterdir())


def test_constructor_and_capability_do_not_import_or_open_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = LocalDiarizationProcess(DiarizationConfig(tmp_path / "absent.json", "a" * 64))
    monkeypatch.setattr(importlib.metadata, "version", lambda name: "bad-version")
    caps = provider.capabilities()
    assert not caps["diarization"] and caps["model_state"] == "not_checked"
    assert set(caps["dependencies"].values()) == {"unsupported"}
    assert caps["devices"] == ("cpu",) and caps["max_audio_ms"] == 300000
    provider.close()
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "kind,code",
    [
        ("license", "DIARIZATION_LICENSE_REQUIRED"),
        ("manifest_hash", "DIARIZATION_MANIFEST_CHECKSUM"),
        ("model_hash", "DIARIZATION_MODEL_CHECKSUM"),
        ("license_hash", "DIARIZATION_LICENSE_INVALID"),
        ("schema", "DIARIZATION_MANIFEST_INVALID"),
        ("traversal", "DIARIZATION_MANIFEST_INVALID"),
        ("url_type", "DIARIZATION_MANIFEST_INVALID"),
        ("runtime", "DIARIZATION_MANIFEST_INVALID"),
    ],
)
def test_manifest_failure_before_native_loader(tmp_path: Path, kind: str, code: str) -> None:
    config = manifest(tmp_path)
    if kind == "license":
        config = replace(config, license_accepted=False)
    elif kind == "manifest_hash":
        config = replace(config, manifest_sha256="0" * 64)
    elif kind == "model_hash":
        (tmp_path / "embedding.onnx").write_bytes(b"changed")
    elif kind == "license_hash":
        (tmp_path / "LICENSE.embedding.txt").write_bytes(b"changed")
    else:
        value = json.loads(config.manifest_path.read_bytes())
        if kind == "schema":
            value["schema_version"] = True
        elif kind == "traversal":
            value["models"]["embedding"]["file"] = "../embedding.onnx"
        elif kind == "url_type":
            value["models"]["embedding"]["license_url"] = []
        else:
            value["runtime_version"] = "latest"
        raw = json.dumps(value).encode()
        config.manifest_path.write_bytes(raw)
        config = replace(config, manifest_sha256=hashlib.sha256(raw).hexdigest())
    with pytest.raises(ProviderError, match=code):
        verified_models(config)


def test_hardlinked_model_is_rejected(tmp_path: Path) -> None:
    config = manifest(tmp_path)
    (tmp_path / "alias").hardlink_to(tmp_path / "embedding.onnx")
    with pytest.raises(ProviderError):
        verified_models(config)


@pytest.mark.parametrize(
    "channels,rate,frames,limit",
    [
        (2, 16000, 16000, 1000),
        (1, 8000, 8000, 1000),
        (1, 16000, 16001, 1000),
        (1, 16000, 0, 1000),
    ],
)
def test_audio_format_and_bound(
    tmp_path: Path, channels: int, rate: int, frames: int, limit: int
) -> None:
    request = wav(tmp_path, channels=channels, rate=rate, frames=frames)
    before = request.audio_path.read_bytes()
    with pytest.raises(ProviderError):
        backend.audio_snapshot(request, limit)
    assert request.audio_path.read_bytes() == before


class Proto:
    def __init__(
        self, name: str, children: list[Any] | None = None, external: bool = False
    ) -> None:
        self.DESCRIPTOR = SimpleNamespace(full_name=name)
        self.external_data = ["unapproved"] if external else []
        self.data_location = 0
        self.children = children or []

    def HasField(self, name: str) -> bool:
        return True

    def ListFields(self) -> list[Any]:
        return (
            [(SimpleNamespace(type=11, is_repeated=True), self.children)] if self.children else []
        )


def test_onnx_nested_external_tensor_is_denied() -> None:
    tensor = Proto("onnx.TensorProto", external=True)
    parser = SimpleNamespace(
        load_model_from_string=lambda data, format: Proto(
            "model", [Proto("graph", [Proto("attribute", [tensor])])]
        )
    )
    with pytest.raises(ProviderError, match="DIARIZATION_EXTERNAL_DATA_DENIED"):
        backend.audit_onnx(b"not-real-weights", parser)
    tensor.external_data = []
    backend.audit_onnx(b"not-real-weights", parser)
    tensor.data_location = 1
    with pytest.raises(ProviderError, match="DIARIZATION_EXTERNAL_DATA_DENIED"):
        backend.audit_onnx(b"not-real-weights", parser)


@pytest.mark.parametrize("invalid", ["", "nan", "time", "speaker", "config", "rate", "cancel"])
def test_fake_offline_api_scope_overlap_and_source_immutability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    invalid: str,
) -> None:
    # NumPy alone is used for synthetic sample conversion; no ONNX or sherpa import.
    import numpy as np

    config, request = manifest(tmp_path), wav(tmp_path)
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    calls: list[dict[str, Any]] = []
    cancel = threading.Event()

    def settings(**kwargs: Any) -> Any:
        calls.append(kwargs)
        return SimpleNamespace(**kwargs, validate=lambda: invalid != "config")

    class Native:
        sample_rate = 8000 if invalid == "rate" else 16000

        def __init__(self, value: Any) -> None:
            assert value.segmentation.provider == value.embedding.provider == "cpu"
            for part in (value.segmentation.pyannote, value.embedding):
                assert Path(part.model).read_bytes().startswith(b"synthetic-not-onnx-")
                assert Path(part.model).parent != tmp_path

        def process(self, samples: Any, callback: Any) -> Any:
            assert len(samples) == 16000 and samples.dtype == np.float32
            assert callback(1, 2) == 0
            if invalid == "cancel":
                cancel.set()
                assert callback(2, 2) == 1
            return SimpleNamespace(
                sort_by_start_time=lambda: [
                    SimpleNamespace(
                        start=float("nan") if invalid == "nan" else 0.0,
                        end=1.001 if invalid == "time" else 0.7,
                        speaker=32 if invalid == "speaker" else 0,
                    ),
                    SimpleNamespace(start=0.5, end=1.0, speaker=1),
                ]
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
    parser = SimpleNamespace(load_model_from_string=lambda data, format: Proto("model"))
    monkeypatch.setattr(
        backend,
        "_module",
        lambda name, version=None: {"sherpa_onnx": sdk, "onnx": parser, "numpy": np}[name],
    )
    audio_hash = hashlib.sha256(request.audio_path.read_bytes()).hexdigest()
    if invalid:
        with pytest.raises(
            ProviderError,
            match={
                "config": "DIARIZATION_MODEL_INVALID",
                "rate": "DIARIZATION_AUDIO_UNSUPPORTED",
                "cancel": "CANCELLED",
            }.get(invalid, "DIARIZATION_RESULT_INVALID"),
        ):
            backend.compute(config, request, cancel, audio_hash)
        assert before == {path.name: path.read_bytes() for path in tmp_path.iterdir()}
        return
    result = backend.compute(config, request, cancel, audio_hash)
    assert result.complete and result.warnings == ("ANONYMOUS_ESTIMATE", "OVERLAP_UNCERTAIN")
    assert [(turn.start_ms, turn.end_ms) for turn in result.turns] == [(2000, 2700), (2500, 3000)]
    assert all(turn.uncertain and turn.track_id == "mic" for turn in result.turns)
    second = backend.compute(
        config, replace(request, offset_ms=3000), threading.Event(), audio_hash
    )
    assert result.turns[0].speaker != second.turns[0].speaker
    assert before == {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    assert calls


def test_optional_runtime_version_mismatch_is_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        importlib, "import_module", lambda name: SimpleNamespace(__version__="unapproved")
    )
    with pytest.raises(ProviderError, match="DEPENDENCY_VERSION_UNSUPPORTED"):
        backend._module("sherpa_onnx", "2.0.1")


def test_conservative_assignment_preserves_text_timing_provenance() -> None:
    original = (
        Segment("single", 0, 1000, "original", track_id="mic"),
        Segment("overlap", 1000, 2000, "two speakers", track_id="mic"),
        Segment("insert", 0, 1000, "user", provenance="user_assertion", track_id="mic"),
        Segment("other", 0, 1000, "system", track_id="system"),
        Segment("fixed", 0, 1000, "named", speaker="existing", track_id="mic"),
        Segment("unknown", 0, 1000, "unverified", timing_quality="clip", track_id="mic"),
    )
    before = tuple(asdict(segment) for segment in original)
    turns = (
        SpeakerTurn(0, 800, "speaker_scope_0"),
        SpeakerTurn(1000, 1700, "speaker_scope_0"),
        SpeakerTurn(1500, 2000, "speaker_scope_1"),
    )
    derived = assign_speakers(original, turns)
    assert tuple(segment.speaker for segment in derived) == (
        "speaker_scope_0",
        None,
        None,
        None,
        "existing",
        None,
    )
    assert before == tuple(asdict(segment) for segment in original)
    assert all(
        replace(new, speaker=old.speaker) == old and new is not old
        for old, new in zip(original, derived, strict=True)
    )
    assert assign_speakers(original[:1], (turns[0], turns[0]), min_coverage=0.9)[0].speaker is None


def test_reply_binding_rejects_wrong_hash_track_or_range(tmp_path: Path) -> None:
    request = DiarizationRequest(tmp_path / "audio.wav", 1000, "mic")
    good = DiarizationResult(
        (SpeakerTurn(1000, 2000, "speaker_scope_0"),),
        True,
        audio_sha256="a" * 64,
        model_manifest_sha256="b" * 64,
        warnings=("ANONYMOUS_ESTIMATE",),
    )
    for value in (
        replace(good, audio_sha256="c" * 64),
        replace(good, turns=(replace(good.turns[0], track_id="system"),)),
        replace(good, turns=(replace(good.turns[0], end_ms=2001),)),
    ):
        with pytest.raises(ProviderError, match="DIARIZATION_RESULT_INVALID"):
            process._decode(json.dumps(asdict(value)).encode(), request, 1000, "a" * 64, "b" * 64)
    decoded = process._decode(json.dumps(asdict(good)).encode(), request, 1000, "a" * 64, "b" * 64)
    assert decoded == good


def test_model_change_between_snapshot_and_child_is_denied(tmp_path: Path) -> None:
    config, request = manifest(tmp_path), wav(tmp_path)
    with pytest.raises(ProviderError, match="DIARIZATION_AUDIO_CHANGED"):
        backend.compute(config, request, threading.Event(), "0" * 64)


def test_truncated_wave_is_rejected(tmp_path: Path) -> None:
    request = wav(tmp_path)
    request.audio_path.write_bytes(request.audio_path.read_bytes()[:-2])
    with pytest.raises(ProviderError, match="DIARIZATION_AUDIO_INVALID"):
        backend.audio_snapshot(request, 1000)


def test_annotations_publish_as_derived_revision_and_keep_concurrent_edit(tmp_path: Path) -> None:
    original = (Segment("s1", 0, 1000, "original text", track_id="mic"),)
    annotated = assign_speakers(original, (SpeakerTurn(0, 1000, "speaker_scope_0"),))
    with Library(tmp_path / "library") as library:
        library.create_session("session")
        with ContentStore(library) as store:
            first = store.create_transcript("session", original)
            before = store.transcript(first)
            edited = store.edit_segment(
                "session", first, "s1", "user changed text", expected_active=first
            )
            derived = store.create_transcript(
                "session", annotated, parent_revision_id=first, expected_active=first
            )
            assert store.transcript(first) == before
            candidate = store.transcript(derived)
            assert candidate["parent_revision_id"] == first
            assert candidate["segments"][0]["speaker"] == "speaker_scope_0"
            assert candidate["segments"][0]["text"] == "original text"
            active = store.active_transcript("session")
            assert active is not None and active["revision_id"] == edited
