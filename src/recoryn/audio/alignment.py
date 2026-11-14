"""Per-contiguous-epoch clock fits and traceable, non-destructive alignment.

QPC correlation does not remove ADC, transport, Bluetooth or acoustic latency.
Original blocks are never rewritten or filled with synthetic silence here.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from recoryn.domain import PCMBlock, ValidationError

# Conservative implementation gates, pending hardware characterization. They are
# rejection limits, not measured oscillator/QPC accuracy or a device guarantee.
_MAX_PERIOD_ERROR = 0.01
_STEP_ROUNDING_NS = 1_000
_MAX_FIT_RESIDUAL_NS = 1_000_000


def _valid_clock(block: PCMBlock) -> bool:
    return (
        block.capture_mono_ns is not None
        and block.device_frame_position is not None
        and "TIMESTAMP_ERROR" not in block.flags
        and block.clock_quality in ("DEVICE_CORRELATED", "SYNTHETIC")
    )


def _same_identity(left: PCMBlock, right: PCMBlock) -> bool:
    return (left.session_id, left.track_id, left.epoch_id, left.format) == (
        right.session_id,
        right.track_id,
        right.epoch_id,
        right.format,
    )


def _clock_step_ok(left: PCMBlock, right: PCMBlock) -> bool:
    """Compare sample time with device progress, including non-adjacent packets."""
    assert left.device_frame_position is not None and right.device_frame_position is not None
    assert left.capture_mono_ns is not None and right.capture_mono_ns is not None
    frames = right.device_frame_position - left.device_frame_position
    elapsed = right.capture_mono_ns - left.capture_mono_ns
    if frames <= 0 or elapsed <= 0:
        return False
    expected = frames * 1_000_000_000 / left.format.sample_rate
    return abs(elapsed - expected) <= max(_STEP_ROUNDING_NS, expected * _MAX_PERIOD_ERROR)


def _contiguous(left: PCMBlock, right: PCMBlock) -> bool:
    if not _valid_clock(left) or not _valid_clock(right):
        return False
    assert left.device_frame_position is not None
    fragment_next = (
        right.sequence == left.sequence
        and right.fragment_index == left.fragment_index + 1
        and right.fragment_count == left.fragment_count
    )
    packet_next = (
        right.sequence == left.sequence + 1
        and right.fragment_index == 0
        and left.fragment_index == left.fragment_count - 1
    )
    return (
        _same_identity(left, right)
        and (fragment_next or packet_next)
        and right.device_frame_position == left.device_frame_position + left.frame_count
        and _clock_step_ok(left, right)
        and "DATA_DISCONTINUITY" not in right.flags
    )


@dataclass(frozen=True, slots=True)
class ClockEstimate:
    session_id: str
    track_id: str
    epoch_id: str
    anchor_frame: int
    anchor_mono_ns: int
    ns_per_frame: float
    drift_ppm: float
    residual_ns: float
    sample_count: int

    def map_frame(self, frame: int) -> int:
        if type(frame) is not int or frame < 0:
            raise ValidationError("invalid frame coordinate")
        return self.anchor_mono_ns + round((frame - self.anchor_frame) * self.ns_per_frame)


def estimate_drift(blocks: Sequence[PCMBlock]) -> ClockEstimate:
    """Fit one ordered contiguous run; gaps/epochs/invalid samples are rejected.

    One valid packet uses nominal rate and reports sample_count=1. Regression
    uncertainty is exposed as residual_ns, not a hardware accuracy guarantee.
    Step error and fitted period error must stay within the 1% rejection policy
    (a 1us step-rounding floor), and max fit residual within 1ms. These unmeasured
    policy limits must be characterized at the hardware gate before adoption.
    """
    if not blocks or any(not isinstance(block, PCMBlock) for block in blocks):
        raise ValidationError("clock fit requires PCM blocks")
    if any(not _valid_clock(block) for block in blocks):
        raise ValidationError("clock fit requires valid correlated timestamps")
    if any(not _contiguous(a, b) for a, b in zip(blocks, blocks[1:], strict=False)):
        raise ValidationError("clock fit cannot cross gaps or epochs")
    first = blocks[0]
    assert first.device_frame_position is not None and first.capture_mono_ns is not None
    anchor_frame, anchor_ns = first.device_frame_position, first.capture_mono_ns
    xs = [
        block.device_frame_position - anchor_frame
        for block in blocks
        if block.device_frame_position is not None
    ]
    ys = [
        block.capture_mono_ns - anchor_ns for block in blocks if block.capture_mono_ns is not None
    ]
    x_mean, y_mean = math.fsum(xs) / len(xs), math.fsum(ys) / len(ys)
    variance = math.fsum((x - x_mean) ** 2 for x in xs)
    slope = (
        math.fsum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys, strict=True)) / variance
        if variance
        else 1_000_000_000 / first.format.sample_rate
    )
    if not math.isfinite(slope) or slope <= 0:
        raise ValidationError("invalid clock slope")
    nominal = 1_000_000_000 / first.format.sample_rate
    if abs(slope / nominal - 1) > _MAX_PERIOD_ERROR + 1e-12:
        raise ValidationError("clock rate exceeds fit policy")
    intercept = round(y_mean - slope * x_mean)
    residual = max(abs(y - (intercept + slope * x)) for x, y in zip(xs, ys, strict=True))
    if residual > _MAX_FIT_RESIDUAL_NS:
        raise ValidationError("clock residual exceeds fit policy")
    drift = (1_000_000_000 / slope / first.format.sample_rate - 1) * 1_000_000
    return ClockEstimate(
        first.session_id,
        first.track_id,
        first.epoch_id,
        anchor_frame,
        anchor_ns + intercept,
        slope,
        drift,
        residual,
        len(blocks),
    )


@dataclass(frozen=True, slots=True)
class AlignedSpan:
    session_id: str
    track_id: str
    epoch_id: str
    sequence: int
    fragment_index: int
    source_start_frame: int
    source_end_frame: int
    device_frame_position: int | None
    start_ns: int | None
    end_ns: int | None
    quality: str
    segment: int
    drift_ppm: float | None


def align_blocks(
    blocks: Sequence[PCMBlock],
    *,
    origin_ns: int | None = None,
) -> tuple[AlignedSpan, ...]:
    """Align independent tracks to correlated clock time, preserving every split.

    Input order is preserved within a track. A missing/invalid timestamp stays
    unknown; arrival timestamps never replace sample time. Output is a mapping,
    not a mix. Caller must supply blocks from one host/run clock domain.

    A clock jump splits the run and taints that identity until a new epoch. Such
    spans use UNCERTAIN_CLOCK, retain observed timestamp positions and nominal
    packet lengths, and carry no fitted drift. Their apparent gaps/overlaps are
    clock observations, not claims of a measured physical loss or precise time.
    A failed global fit similarly falls back to individual uncertain spans.
    """
    if origin_ns is not None and (type(origin_ns) is not int or origin_ns < 0):
        raise ValidationError("invalid alignment origin")
    grouped: dict[tuple[str, str], list[PCMBlock]] = {}
    for block in blocks:
        if not isinstance(block, PCMBlock):
            raise ValidationError("alignment requires PCM blocks")
        grouped.setdefault((block.session_id, block.track_id), []).append(block)
    if len({block.session_id for block in blocks}) > 1:
        raise ValidationError("alignment cannot mix sessions")
    mapped: list[AlignedSpan] = []
    segment = 0

    def emit(run: list[PCMBlock], uncertain: bool) -> None:
        nonlocal segment
        if not run:
            return
        estimate = None
        if _valid_clock(run[0]) and not uncertain:
            try:
                estimate = estimate_drift(run)
            except ValidationError:
                uncertain = True
        for block in run:
            position = block.device_frame_position
            if uncertain and _valid_clock(block):
                start = block.capture_mono_ns
                assert start is not None
                end = start + round(block.frame_count * 1_000_000_000 / block.format.sample_rate)
                quality = "UNCERTAIN_CLOCK"
            elif estimate and position is not None:
                start = estimate.map_frame(position)
                end = estimate.map_frame(position + block.frame_count)
                quality = "DEVICE_CORRELATED"
            else:
                start, end, quality = None, None, "UNKNOWN"
            mapped.append(
                AlignedSpan(
                    block.session_id,
                    block.track_id,
                    block.epoch_id,
                    block.sequence,
                    block.fragment_index,
                    0,
                    block.frame_count,
                    position,
                    start,
                    end,
                    quality,
                    segment,
                    estimate.drift_ppm if estimate else None,
                )
            )
            if uncertain:
                segment += 1
        if not uncertain:
            segment += 1
        run.clear()

    for track_blocks in grouped.values():
        run: list[PCMBlock] = []
        uncertain = False
        previous: PCMBlock | None = None
        for block in track_blocks:
            if run and not _contiguous(run[-1], block):
                emit(run, uncertain)
            if previous is not None:
                if not _same_identity(previous, block):
                    uncertain = False
                elif (
                    _valid_clock(previous)
                    and _valid_clock(block)
                    and not _clock_step_ok(previous, block)
                ):
                    uncertain = True
            run.append(block)
            if not _valid_clock(block):
                emit(run, uncertain)
            previous = block
        emit(run, uncertain)
    origin = (
        origin_ns
        if origin_ns is not None
        else min((span.start_ns for span in mapped if span.start_ns is not None), default=0)
    )
    return tuple(
        AlignedSpan(
            s.session_id,
            s.track_id,
            s.epoch_id,
            s.sequence,
            s.fragment_index,
            s.source_start_frame,
            s.source_end_frame,
            s.device_frame_position,
            s.start_ns - origin if s.start_ns is not None else None,
            s.end_ns - origin if s.end_ns is not None else None,
            s.quality,
            s.segment,
            s.drift_ppm,
        )
        for s in mapped
    )
