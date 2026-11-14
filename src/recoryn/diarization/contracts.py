"""Frozen local diarization values; validation performs no I/O."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

from recoryn.providers import ProviderError

MAX_AUDIO_MS = 300_000
MAX_TURNS = 4096


def integer(value: object, minimum: int = 0, maximum: int = 2**63 - 1) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ProviderError("DIARIZATION_INPUT_INVALID")
    return value


def fraction(value: object, maximum: float = 1) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProviderError("DIARIZATION_INPUT_INVALID")
    if not math.isfinite(value) or not 0 < value <= maximum:
        raise ProviderError("DIARIZATION_INPUT_INVALID")
    return float(value)


def sha256(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ProviderError("DIARIZATION_MANIFEST_INVALID")
    return value


def label(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) is None:
        raise ProviderError("DIARIZATION_INPUT_INVALID")
    return value


@dataclass(frozen=True)
class DiarizationConfig:
    manifest_path: Path
    manifest_sha256: str
    license_accepted: bool = False
    device: str = "cpu"
    num_threads: int = 1
    num_speakers: int | None = None
    threshold: float = 0.5
    max_audio_ms: int = MAX_AUDIO_MS
    timeout_seconds: float = 300

    def __post_init__(self) -> None:
        if not isinstance(self.manifest_path, Path) or not self.manifest_path.is_absolute():
            raise ProviderError("DIARIZATION_INPUT_INVALID")
        sha256(self.manifest_sha256)
        if type(self.license_accepted) is not bool:
            raise ProviderError("DIARIZATION_INPUT_INVALID")
        if self.device != "cpu":
            raise ProviderError("CAPABILITY_UNSUPPORTED")
        integer(self.num_threads, 1, 4)
        if self.num_speakers is not None:
            integer(self.num_speakers, 1, 32)
        fraction(self.threshold, 2)
        integer(self.max_audio_ms, 1, MAX_AUDIO_MS)
        fraction(self.timeout_seconds, 3600)


@dataclass(frozen=True)
class DiarizationRequest:
    audio_path: Path
    offset_ms: int = 0
    track_id: str = "mic"

    def __post_init__(self) -> None:
        if not isinstance(self.audio_path, Path) or not self.audio_path.is_absolute():
            raise ProviderError("DIARIZATION_INPUT_INVALID")
        integer(self.offset_ms, 0, 2**63 - 1 - MAX_AUDIO_MS)
        label(self.track_id)


@dataclass(frozen=True)
class SpeakerTurn:
    start_ms: int
    end_ms: int
    speaker: str
    track_id: str = "mic"
    uncertain: bool = True

    def __post_init__(self) -> None:
        integer(self.start_ms)
        integer(self.end_ms, self.start_ms + 1)
        if (
            not isinstance(self.speaker, str)
            or re.fullmatch(r"speaker_[a-z0-9_]{1,64}", self.speaker) is None
        ):
            raise ProviderError("DIARIZATION_RESULT_INVALID")
        label(self.track_id)
        if self.uncertain is not True:
            raise ProviderError("DIARIZATION_RESULT_INVALID")


@dataclass(frozen=True)
class DiarizationResult:
    turns: tuple[SpeakerTurn, ...]
    complete: bool
    cancelled: bool = False
    error_code: str | None = None
    audio_sha256: str = ""
    model_manifest_sha256: str = ""
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            type(self.turns) is not tuple
            or len(self.turns) > MAX_TURNS
            or any(not isinstance(turn, SpeakerTurn) for turn in self.turns)
            or type(self.complete) is not bool
            or type(self.cancelled) is not bool
            or self.complete
            and (self.cancelled or self.error_code is not None)
            or not self.complete
            and self.turns
        ):
            raise ProviderError("DIARIZATION_RESULT_INVALID")
        if self.error_code is not None and (
            not isinstance(self.error_code, str)
            or re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", self.error_code) is None
        ):
            raise ProviderError("DIARIZATION_RESULT_INVALID")
        for digest in (self.audio_sha256, self.model_manifest_sha256):
            if digest:
                sha256(digest)
        if type(self.warnings) is not tuple or any(
            item not in {"ANONYMOUS_ESTIMATE", "OVERLAP_UNCERTAIN"} for item in self.warnings
        ):
            raise ProviderError("DIARIZATION_RESULT_INVALID")
