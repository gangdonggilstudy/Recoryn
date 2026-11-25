"""Explicit local ONNX adapter, called only inside an owned resource-limited child."""

from __future__ import annotations

import hashlib
import importlib
import io
import json
import math
import wave
from pathlib import Path
from typing import Any

from recoryn.providers import ProviderError
from recoryn.storage._safe import open_file

from .contracts import (
    MAX_TURNS,
    DiarizationConfig,
    DiarizationRequest,
    DiarizationResult,
    SpeakerTurn,
)
from .models import read_local


def audio_snapshot(request: DiarizationRequest, max_audio_ms: int) -> tuple[bytes, int, str]:
    data = read_local(request.audio_path, 32 * max_audio_ms + 64 * 1024)
    try:
        with wave.open(io.BytesIO(data), "rb") as stream:
            if (
                stream.getnchannels(),
                stream.getsampwidth(),
                stream.getframerate(),
                stream.getcomptype(),
            ) != (1, 2, 16000, "NONE"):
                raise ProviderError("DIARIZATION_AUDIO_UNSUPPORTED")
            frames = stream.getnframes()
            if frames <= 0 or frames > max_audio_ms * 16 or frames * 2 > len(data):
                raise ProviderError("DIARIZATION_INPUT_TOO_LARGE")
            pcm = stream.readframes(frames)
            if len(pcm) != frames * 2:
                raise ProviderError("DIARIZATION_AUDIO_INVALID")
        return pcm, (frames + 15) // 16, hashlib.sha256(data).hexdigest()
    except (EOFError, wave.Error):
        raise ProviderError("DIARIZATION_AUDIO_INVALID") from None


def audit_onnx(data: bytes, onnx: Any) -> None:
    # Explicit protobuf parsing from bytes does not resolve external data paths.
    model = onnx.load_model_from_string(data, format="protobuf")
    if not model.HasField("graph"):
        raise ProviderError("DIARIZATION_MODEL_INVALID")
    pending: list[tuple[Any, int]] = [(model, 0)]
    count = 0
    while pending:
        message, depth = pending.pop()
        count += 1
        if depth > 64 or count > 100_000:
            raise ProviderError("DIARIZATION_MODEL_INVALID")
        if message.DESCRIPTOR.full_name == "onnx.TensorProto" and (
            message.external_data or message.data_location != 0
        ):
            raise ProviderError("DIARIZATION_EXTERNAL_DATA_DENIED")
        for descriptor, value in message.ListFields():
            if descriptor.type == 11:  # protobuf TYPE_MESSAGE, including nested/sparse tensors
                children = value if descriptor.is_repeated else (value,)
                pending.extend((child, depth + 1) for child in children)
                if len(pending) + count > 100_000:
                    raise ProviderError("DIARIZATION_MODEL_INVALID")


def _module(name: str, version: str | None = None) -> Any:
    try:
        module = importlib.import_module(name)
    except ImportError:
        raise ProviderError("DEPENDENCY_MISSING") from None
    if version is not None and getattr(module, "__version__", None) != version:
        raise ProviderError("DEPENDENCY_VERSION_UNSUPPORTED")
    return module


def bundle_models(bundle: object) -> dict[str, tuple[Path, bytes]]:
    """The sealed bundle's two models (path and bytes), each compared with its digest."""
    from recoryn.models._artifact_io import diarization_files

    paths = diarization_files(bundle)
    models: dict[str, tuple[Path, bytes]] = {}
    for role in ("segmentation", "embedding"):
        path = paths[role + ".onnx"]
        with open_file(path, "rb") as stream:
            data = stream.read(128 * 1024 * 1024 + 1)
        models[role] = (path, data)
    return models


def compute(
    config: DiarizationConfig,
    request: DiarizationRequest,
    cancel: Any,
    expected_audio_sha256: str,
    bundle: object = None,
) -> DiarizationResult:
    """Run sherpa on the parent's sealed bundle only (G-P13): the parent re-verified the
    user's manifest, models and licenses right before sealing; no bundle, no native."""
    if cancel.is_set():
        raise ProviderError("CANCELLED")
    if bundle is None:
        from recoryn.models._artifact_io import ArtifactError

        raise ArtifactError("CAPABILITY_UNSUPPORTED", "MODEL_CONFIRMATION_REQUIRED")
    pcm, duration, audio_hash = audio_snapshot(request, config.max_audio_ms)
    if audio_hash != expected_audio_sha256:
        raise ProviderError("DIARIZATION_AUDIO_CHANGED")
    models = bundle_models(bundle)
    onnx = _module("onnx", "1.23.2")
    for _, data in models.values():
        audit_onnx(data, onnx)
    sdk, np = _module("sherpa_onnx", "2.0.1"), _module("numpy", "2.3.5")
    if cancel.is_set():
        raise ProviderError("CANCELLED")
    # The sealed bundle paths; no second copy and no original folder.
    segmentation, embedding = models["segmentation"][0], models["embedding"][0]
    native_config = sdk.OfflineSpeakerDiarizationConfig(
        segmentation=sdk.OfflineSpeakerSegmentationModelConfig(
            pyannote=sdk.OfflineSpeakerSegmentationPyannoteModelConfig(
                model=str(segmentation),
                window_shift_ratio=0.1,
            ),
            num_threads=config.num_threads,
            debug=False,
            provider="cpu",
        ),
        embedding=sdk.SpeakerEmbeddingExtractorConfig(
            model=str(embedding),
            num_threads=config.num_threads,
            debug=False,
            provider="cpu",
        ),
        clustering=sdk.FastClusteringConfig(
            num_clusters=config.num_speakers if config.num_speakers is not None else -1,
            threshold=config.threshold,
        ),
        min_duration_on=0.3,
        min_duration_off=0.5,
    )
    if not native_config.validate():
        raise ProviderError("DIARIZATION_MODEL_INVALID")
    native = sdk.OfflineSpeakerDiarization(native_config)
    if native.sample_rate != 16000:
        raise ProviderError("DIARIZATION_AUDIO_UNSUPPORTED")
    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32)
    samples *= 1 / 32768
    raw = native.process(samples, callback=lambda processed, total: int(cancel.is_set()))
    if cancel.is_set():
        raise ProviderError("CANCELLED")
    raw = raw.sort_by_start_time()
    scope = hashlib.sha256(
        json.dumps(
            [
                audio_hash,
                config.manifest_sha256,
                request.offset_ms,
                request.track_id,
                config.num_speakers,
                config.threshold,
            ]
        ).encode()
    ).hexdigest()[:12]
    turns = []
    for index, item in enumerate(raw):
        if (
            index >= MAX_TURNS
            or type(item.speaker) is not int
            or not 0 <= item.speaker < (config.num_speakers or 32)
            or isinstance(item.start, bool)
            or isinstance(item.end, bool)
            or not isinstance(item.start, (float, int))
            or not isinstance(item.end, (float, int))
            or not math.isfinite(item.start)
            or not math.isfinite(item.end)
            or not 0 <= item.start < item.end <= duration / 1000
        ):
            raise ProviderError("DIARIZATION_RESULT_INVALID")
        turns.append(
            SpeakerTurn(
                request.offset_ms + int(item.start * 1000),
                request.offset_ms + math.ceil(item.end * 1000),
                f"speaker_{scope}_{item.speaker}",
                request.track_id,
            )
        )
    turns.sort(key=lambda turn: (turn.start_ms, turn.end_ms, turn.speaker))
    warnings = ["ANONYMOUS_ESTIMATE"]
    active: dict[str, int] = {}
    for turn in turns:
        if any(end > turn.start_ms and speaker != turn.speaker for speaker, end in active.items()):
            warnings.append("OVERLAP_UNCERTAIN")
            break
        active[turn.speaker] = max(turn.end_ms, active.get(turn.speaker, 0))
    return DiarizationResult(
        tuple(turns),
        True,
        audio_sha256=audio_hash,
        model_manifest_sha256=config.manifest_sha256,
        warnings=tuple(warnings),
    )
