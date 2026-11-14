"""Deterministic core/context plans preserving immutable source spans."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from recoryn.providers import ProviderConfig, ProviderError, SegmentSpan, SummaryRequest
from recoryn.providers._common import encode


@dataclass(frozen=True)
class TextSlice:
    span: SegmentSpan
    text: str
    start_ms: int
    end_ms: int
    provenance: str
    speaker: str | None = None
    track_id: str = "audio"
    timing_quality: str = "model"

    def to_dict(self) -> dict[str, Any]:
        return {
            "segment_id": self.span.segment_id,
            "start_char": self.span.start_char,
            "end_char": self.span.end_char,
            "text": self.text,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "provenance": self.provenance,
            "speaker": self.speaker,
            "track_id": self.track_id,
            "timing_quality": self.timing_quality,
        }


@dataclass(frozen=True)
class SummaryChunk:
    chunk_id: str
    core: tuple[TextSlice, ...]
    context: tuple[TextSlice, ...]


def input_budget(config: ProviderConfig) -> int:
    if config.context_window_tokens is None:
        raise ProviderError("CONTEXT_LIMIT_UNKNOWN")
    budget = config.context_window_tokens - config.max_output_tokens - 2048
    if budget < 512:
        raise ProviderError("CONTEXT_LIMIT")
    # UTF-8 bytes are deliberately conservative sizing units, not a claim that
    # this is the provider's tokenizer. The final wire envelope is bounded too.
    return min(budget, 1_000_000)


def plan_summary(request: SummaryRequest, config: ProviderConfig) -> tuple[SummaryChunk, ...]:
    budget = input_budget(config)
    slice_chars = max(1, min(request.chunk_chars, budget // 24))
    slices: list[TextSlice] = []
    for segment in request.segments:
        starts = range(0, len(segment.text), slice_chars) if segment.text else (0,)
        for start in starts:
            end = min(len(segment.text), start + slice_chars)
            slices.append(
                TextSlice(
                    SegmentSpan(segment.segment_id, start, end),
                    segment.text[start:end],
                    segment.start_ms,
                    segment.end_ms,
                    segment.provenance,
                    segment.speaker,
                    segment.track_id,
                    segment.timing_quality,
                )
            )
            if len(slices) > 100_000:
                raise ProviderError("INPUT_TOO_LARGE")
    chunks: list[SummaryChunk] = []
    core: list[TextSlice] = []
    core_size = 0
    history: list[TextSlice] = []

    def emit() -> None:
        context: list[TextSlice] = []
        size = 0
        for item in reversed(
            history[-request.overlap_segments :] if request.overlap_segments else []
        ):
            item_size = len(encode(item.to_dict())) + 1
            if size + item_size > budget // 4:
                break
            context.insert(0, item)
            size += item_size
        chunk_id = hashlib.sha256(
            encode([request.transcript_revision_id, [item.to_dict() for item in core]])
        ).hexdigest()[:32]
        chunks.append(SummaryChunk(chunk_id, tuple(core), tuple(context)))
        history.extend(core)

    for item in slices:
        size = len(encode(item.to_dict())) + 1
        if size > budget * 3 // 4:
            raise ProviderError("CONTEXT_LIMIT")
        if core and core_size + size > budget * 3 // 4:
            emit()
            core, core_size = [], 0
        core.append(item)
        core_size += size
    if core:
        emit()
    return tuple(chunks)


def plan_digest(request: SummaryRequest, config: ProviderConfig) -> str:
    return hashlib.sha256(
        encode(
            {
                "schema_version": 1,
                "revision": request.transcript_revision_id,
                "segments": [
                    {
                        "id": s.segment_id,
                        "text": s.text,
                        "start": s.start_ms,
                        "end": s.end_ms,
                        "basis": s.provenance,
                        "track": s.track_id,
                        "speaker": s.speaker,
                        "timing_quality": s.timing_quality,
                    }
                    for s in request.segments
                ],
                "template": request.template,
                "language": request.output_language,
                "chunk_chars": request.chunk_chars,
                "overlap": request.overlap_segments,
                "provider": config.provider_id,
                "model": config.model,
                "endpoint": config.endpoint,
                "location": config.execution_location,
                "context": config.context_window_tokens,
                "output": config.max_output_tokens,
                "version": config.api_version,
                "artifact": config.local_attestation.artifact_sha256
                if config.local_attestation
                else None,
            }
        )
    ).hexdigest()
