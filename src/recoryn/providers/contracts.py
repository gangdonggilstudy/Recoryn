"""Immutable provider values. Import and construction do not perform I/O."""

from __future__ import annotations

import math
import re
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Protocol


class ProviderError(ValueError):
    """Safe machine code only; never retain a provider body in the message."""

    def __init__(self, code: str, *, retryable: bool = False, outcome_known: bool = True) -> None:
        if re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", code) is None:
            code = "PROVIDER_FAILED"
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.outcome_known = outcome_known


def checked_text(value: object, *, maximum: int = 256, empty: bool = False) -> str:
    if not isinstance(value, str) or (not empty and not value) or len(value) > maximum:
        raise ProviderError("INPUT_INVALID")
    if any(ord(char) < 32 for char in value):
        raise ProviderError("INPUT_INVALID")
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise ProviderError("INPUT_INVALID") from None
    return value


def checked_int(value: object, *, minimum: int = 0, maximum: int = 2**63 - 1) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ProviderError("INPUT_INVALID")
    return value


@dataclass(frozen=True)
class LocalModelAttestation:
    """Evidence supplied by the trusted model/server manager, not a checkbox.

    This object does not itself prove a third-party daemon's egress isolation.
    The caller must bind a verified artifact and offline runtime to this endpoint.
    """

    endpoint: str
    model: str
    artifact_sha256: str
    cloud_disabled: bool
    expires_at_monotonic: float
    lifetime_guard: Callable[[], AbstractContextManager[None]] | None = field(
        default=None, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        checked_text(self.endpoint, maximum=2048)
        checked_text(self.model)
        if re.fullmatch(r"[0-9a-f]{64}", self.artifact_sha256) is None:
            raise ProviderError("LOCAL_EXECUTION_UNVERIFIED")
        if (
            type(self.cloud_disabled) is not bool
            or isinstance(self.expires_at_monotonic, bool)
            or not isinstance(self.expires_at_monotonic, (int, float))
            or not math.isfinite(self.expires_at_monotonic)
            or self.lifetime_guard is not None
            and not callable(self.lifetime_guard)
        ):
            raise ProviderError("LOCAL_EXECUTION_UNVERIFIED")

    @contextmanager
    def execution_guard(self) -> Iterator[None]:
        """Hold a managed owner's lifetime lock for one outbound handoff unit."""
        with self.lifetime_guard() if self.lifetime_guard is not None else nullcontext():
            if not self.cloud_disabled or self.expires_at_monotonic <= time.monotonic():
                raise ProviderError("LOCAL_EXECUTION_UNVERIFIED")
            yield


@dataclass(frozen=True)
class ProviderConfig:
    provider_id: str
    model: str
    endpoint: str = ""
    execution_location: str = "remote"
    timeout_seconds: float = 60.0
    max_response_bytes: int = 4 * 1024 * 1024
    context_window_tokens: int | None = None
    max_output_tokens: int = 1024
    max_requests: int = 128
    local_attestation: LocalModelAttestation | None = None
    api_version: str = "2026-10-21"

    def __post_init__(self) -> None:
        if self.provider_id not in {"faster_whisper", "ollama", "openai", "anthropic", "gemini"}:
            raise ProviderError("CAPABILITY_UNSUPPORTED")
        checked_text(self.model)
        checked_text(self.endpoint, maximum=2048, empty=True)
        checked_text(self.api_version)
        if self.local_attestation is not None and not isinstance(
            self.local_attestation, LocalModelAttestation
        ):
            raise ProviderError("LOCAL_EXECUTION_UNVERIFIED")
        if self.execution_location not in {"local", "remote"}:
            raise ProviderError("LOCAL_EXECUTION_UNVERIFIED")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise ProviderError("INPUT_INVALID")
        checked_int(self.max_response_bytes, minimum=1, maximum=16 * 1024 * 1024)
        checked_int(self.max_output_tokens, minimum=1, maximum=131072)
        checked_int(self.max_requests, minimum=1, maximum=4096)
        if self.context_window_tokens is not None:
            checked_int(self.context_window_tokens, minimum=1, maximum=2_000_000)


@dataclass(frozen=True)
class ProviderCapabilities:
    provider_id: str
    transcription: bool = False
    summarization: bool = False
    segment_timestamps: bool = False
    streaming: bool = False
    audio_formats: tuple[str, ...] = ()
    actual_service_status: str = "NOT_RUN"


@dataclass(frozen=True)
class ProgressEvent:
    stage: str
    completed: int
    total: int | None
    unit: str


ReservationFactory = Callable[[str, str, str, int], str | None]


@dataclass(frozen=True)
class ExecutionContext:
    cancel: threading.Event = field(default_factory=threading.Event, compare=False, repr=False)
    progress: Callable[[ProgressEvent], None] | None = field(
        default=None, compare=False, repr=False
    )
    reservation_factory: ReservationFactory | None = field(default=None, compare=False, repr=False)
    headers: Mapping[str, str] = field(default_factory=dict, compare=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.cancel, threading.Event):
            raise ProviderError("INPUT_INVALID")
        if not isinstance(self.headers, Mapping):
            raise ProviderError("INPUT_INVALID")
        copied: dict[str, str] = {}
        for key, value in self.headers.items():
            checked_text(key, maximum=128)
            checked_text(value, maximum=8192)
            copied[key] = value
        object.__setattr__(self, "headers", MappingProxyType(copied))


class GatewayLike(Protocol):
    def request(
        self,
        provider_id: str,
        endpoint: str,
        data_type: str,
        body: bytes,
        /,
        *,
        headers: dict[str, str] | None = None,
        reservation_id: str | None = None,
        cancel: threading.Event | None = None,
    ) -> bytes: ...


@dataclass(frozen=True)
class TranscriptSegment:
    segment_id: str
    start_ms: int
    end_ms: int
    text: str
    speaker: str | None = None
    provenance: str = "audio"
    track_id: str = "audio"
    timing_quality: str = "model"

    def __post_init__(self) -> None:
        checked_text(self.segment_id, maximum=128)
        checked_text(self.track_id, maximum=128)
        checked_int(self.start_ms)
        checked_int(self.end_ms, minimum=self.start_ms)
        if not isinstance(self.text, str) or len(self.text) > 2_000_000:
            raise ProviderError("INPUT_INVALID")
        if "\x00" in self.text:
            raise ProviderError("INPUT_INVALID")
        try:
            self.text.encode("utf-8")
        except UnicodeError:
            raise ProviderError("INPUT_INVALID") from None
        if self.speaker is not None:
            checked_text(self.speaker, maximum=128)
        if self.provenance not in {"audio", "user_assertion", "unresolved"}:
            raise ProviderError("INPUT_INVALID")
        if self.timing_quality not in {"model", "clip", "unverified"}:
            raise ProviderError("INPUT_INVALID")


@dataclass(frozen=True)
class STTRequest:
    audio_path: Path
    language: str | None = None
    offset_ms: int = 0
    track_id: str = "audio"
    audio_revision_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.audio_path, Path):
            raise ProviderError("INPUT_INVALID")
        checked_int(self.offset_ms)
        checked_text(self.track_id, maximum=128)
        checked_text(self.audio_revision_id, maximum=256, empty=True)
        if self.language is not None:
            if (
                not isinstance(self.language, str)
                or re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})?", self.language) is None
            ):
                raise ProviderError("LANGUAGE_UNSUPPORTED")


@dataclass(frozen=True)
class STTResult:
    provider_id: str
    model: str
    segments: tuple[TranscriptSegment, ...]
    complete: bool
    cancelled: bool = False
    error_code: str | None = None
    processed_ms: int = 0
    audio_sha256: str = ""
    language: str | None = None
    outcome_known: bool = True


@dataclass(frozen=True)
class SegmentSpan:
    segment_id: str
    start_char: int
    end_char: int

    def __post_init__(self) -> None:
        checked_text(self.segment_id, maximum=128)
        checked_int(self.start_char)
        checked_int(self.end_char, minimum=self.start_char)


@dataclass(frozen=True)
class SummaryClaim:
    text: str
    segment_ids: tuple[str, ...]
    status: str = "uncertain"
    basis: str = "transcript"

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text.strip() or len(self.text) > 16_384:
            raise ProviderError("RESULT_INVALID")
        if type(self.segment_ids) is not tuple:
            raise ProviderError("RESULT_INVALID")
        for segment_id in self.segment_ids:
            checked_text(segment_id, maximum=128)
        if len(set(self.segment_ids)) != len(self.segment_ids) or "\x00" in self.text:
            raise ProviderError("RESULT_INVALID")
        try:
            self.text.encode("utf-8")
        except UnicodeError:
            raise ProviderError("RESULT_INVALID") from None
        if self.status not in {"uncertain", "unsupported", "disputed", "user_assertion"}:
            raise ProviderError("RESULT_INVALID")
        if self.basis not in {"transcript", "user_assertion", "model_inference"}:
            raise ProviderError("RESULT_INVALID")


@dataclass(frozen=True)
class ChunkSummary:
    chunk_id: str
    claims: tuple[SummaryClaim, ...]
    coverage: tuple[SegmentSpan, ...]

    def __post_init__(self) -> None:
        checked_text(self.chunk_id, maximum=128)
        if (
            type(self.claims) is not tuple
            or any(not isinstance(c, SummaryClaim) for c in self.claims)
            or type(self.coverage) is not tuple
            or any(not isinstance(s, SegmentSpan) for s in self.coverage)
        ):
            raise ProviderError("CHECKPOINT_MISMATCH")


@dataclass(frozen=True)
class SummaryCheckpoint:
    plan_digest: str
    completed: tuple[ChunkSummary, ...] = ()

    def __post_init__(self) -> None:
        if (
            not isinstance(self.plan_digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", self.plan_digest) is None
            or type(self.completed) is not tuple
            or len(self.completed) > 100_000
            or any(not isinstance(c, ChunkSummary) for c in self.completed)
        ):
            raise ProviderError("CHECKPOINT_MISMATCH")


@dataclass(frozen=True)
class SummaryRequest:
    transcript_revision_id: str
    segments: tuple[TranscriptSegment, ...]
    template: str = "meeting"
    output_language: str = "ko"
    chunk_chars: int = 4000
    overlap_segments: int = 1
    checkpoint: SummaryCheckpoint | None = None

    def __post_init__(self) -> None:
        checked_text(self.transcript_revision_id, maximum=256)
        checked_text(self.output_language, maximum=32)
        if self.template not in {"meeting", "lecture", "key_points", "decisions", "tasks"}:
            raise ProviderError("CAPABILITY_UNSUPPORTED")
        checked_int(self.chunk_chars, minimum=1, maximum=100_000)
        checked_int(self.overlap_segments, maximum=8)
        if self.checkpoint is not None and not isinstance(self.checkpoint, SummaryCheckpoint):
            raise ProviderError("CHECKPOINT_MISMATCH")
        if type(self.segments) is not tuple or any(
            not isinstance(s, TranscriptSegment) for s in self.segments
        ):
            raise ProviderError("INPUT_INVALID")
        ids = [s.segment_id for s in self.segments]
        if len(ids) != len(set(ids)) or len(ids) > 100_000:
            raise ProviderError("INPUT_INVALID")


@dataclass(frozen=True)
class SummaryResult:
    provider_id: str
    model: str
    transcript_revision_id: str
    claims: tuple[SummaryClaim, ...]
    coverage: tuple[SegmentSpan, ...]
    missing: tuple[SegmentSpan, ...]
    complete: bool
    checkpoint: SummaryCheckpoint
    cancelled: bool = False
    error_code: str | None = None
    outcome_known: bool = True


class STTProvider(Protocol):
    def capabilities(self) -> ProviderCapabilities: ...
    def transcribe(
        self, request: STTRequest, context: ExecutionContext | None = None
    ) -> STTResult: ...


class SummaryProvider(Protocol):
    def capabilities(self) -> ProviderCapabilities: ...
    def summarize(
        self, request: SummaryRequest, context: ExecutionContext | None = None
    ) -> SummaryResult: ...
