"""Conservative anonymous annotations, without changing transcript evidence."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import replace

from recoryn.content import Segment
from recoryn.providers import ProviderError

from .contracts import MAX_TURNS, SpeakerTurn, fraction


def assign_speakers(
    segments: Sequence[Segment], turns: Sequence[SpeakerTurn], *, min_coverage: float = 0.8
) -> tuple[Segment, ...]:
    threshold = fraction(min_coverage)
    if len(segments) > 10_000 or len(turns) > MAX_TURNS:
        raise ProviderError("DIARIZATION_INPUT_TOO_LARGE")
    if any(not isinstance(s, Segment) for s in segments) or any(
        not isinstance(t, SpeakerTurn) for t in turns
    ):
        raise ProviderError("DIARIZATION_INPUT_INVALID")
    result: list[Segment] = []
    for segment in segments:
        if (
            segment.speaker is not None
            or segment.provenance != "audio"
            or segment.timing_quality != "model"
            or segment.end_ms == segment.start_ms
            or segment.track_id is None
        ):
            result.append(replace(segment))
            continue
        intervals: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for turn in turns:
            if turn.track_id != segment.track_id:
                continue
            left, right = max(segment.start_ms, turn.start_ms), min(segment.end_ms, turn.end_ms)
            if left < right:
                intervals[turn.speaker].append((left, right))
        # A sentence spanning different speakers is ambiguous even if their
        # turns do not overlap. Never split or retime text to manufacture alignment.
        speaker: str | None = None
        if len(intervals) == 1:
            candidate, spans = next(iter(intervals.items()))
            end, covered = -1, 0
            for left, right in sorted(spans):
                covered += max(0, right - max(left, end))
                end = max(end, right)
            if covered / (segment.end_ms - segment.start_ms) >= threshold:
                speaker = candidate
        result.append(replace(segment, speaker=speaker))
    return tuple(result)
