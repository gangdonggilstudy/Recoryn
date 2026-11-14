"""Standard-library PCM decoding, equal-weight downmix and basic energy VAD."""

from __future__ import annotations

import math
import struct
from collections.abc import Sequence
from dataclasses import dataclass

from recoryn.domain import AudioFormat, PCMBlock, ValidationError


def _samples(values: Sequence[float]) -> tuple[float, ...]:
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in values):
        raise ValidationError("audio samples must be finite numbers")
    try:
        result = tuple(float(x) for x in values)
    except OverflowError:
        raise ValidationError("audio samples must be finite numbers") from None
    if not all(math.isfinite(x) for x in result):
        raise ValidationError("audio samples must be finite numbers")
    return result


def _positive_int(value: int, name: str) -> None:
    if type(value) is not int or value <= 0:
        raise ValidationError(f"{name} must be a positive integer")


def decode_pcm(payload: bytes, format: AudioFormat) -> tuple[tuple[float, ...], ...]:
    """Decode interleaved little-endian PCM into frame rows, normalized by 2**(bits-1).

    Integer full scale is [-1, 1); float32 is preserved, including finite values
    outside that interval. Nonfinite float data is rejected in this derived path.
    """
    if not isinstance(format, AudioFormat) or type(payload) is not bytes:
        raise ValidationError("PCM requires bytes and an AudioFormat")
    if len(payload) % format.frame_bytes:
        raise ValidationError("partial PCM frame")
    width = format.frame_bytes // format.channels
    values: list[float] = []
    for start in range(0, len(payload), width):
        if format.sample_type == "f32le":
            value = float(struct.unpack_from("<f", payload, start)[0])
            if not math.isfinite(value):
                raise ValidationError("nonfinite float PCM")
        else:
            value = int.from_bytes(payload[start : start + width], "little", signed=True)
            value /= 1 << (width * 8 - 1)
        values.append(value)
    return tuple(
        tuple(values[i : i + format.channels]) for i in range(0, len(values), format.channels)
    )


def downmix_mono(
    frames: Sequence[Sequence[float]],
    *,
    weights: Sequence[float] | None = None,
) -> tuple[float, ...]:
    """Average channels by default; explicit nonnegative weights are normalized.

    Equal weighting is not speaker-layout-aware surround mixing. Callers must
    select layout-specific weights when that interpretation is needed.
    """
    if not frames:
        if weights is not None:
            parsed = _samples(weights)
            if not parsed or any(x < 0 for x in parsed) or sum(parsed) <= 0:
                raise ValidationError("invalid downmix weights")
        return ()
    channels = len(frames[0])
    if not channels or any(len(frame) != channels for frame in frames):
        raise ValidationError("inconsistent channel layout")
    parsed = (1.0,) * channels if weights is None else _samples(weights)
    if len(parsed) != channels or any(x < 0 for x in parsed):
        raise ValidationError("invalid downmix weights")
    try:
        total = math.fsum(parsed)
    except OverflowError:
        raise ValidationError("invalid downmix weights") from None
    if not math.isfinite(total) or total <= 0:
        raise ValidationError("invalid downmix weights")
    normalized = tuple(x / total for x in parsed)
    return tuple(
        math.fsum(x * w for x, w in zip(_samples(row), normalized, strict=True)) for row in frames
    )


def encode_pcm(frames: Sequence[Sequence[float]], format: AudioFormat) -> bytes:
    """Encode a derived interleaved PCM artifact, leaving source bytes untouched.

    Integer output clips to its representable range and rounds ties to even.
    Float32 output preserves finite amplitude, rejecting unrepresentable values.
    """
    if not isinstance(format, AudioFormat):
        raise ValidationError("encoding requires an AudioFormat")
    width = format.frame_bytes // format.channels
    payload = bytearray()
    for row in frames:
        values = _samples(row)
        if len(values) != format.channels:
            raise ValidationError("inconsistent channel layout")
        for sample in values:
            if format.sample_type == "f32le":
                try:
                    payload.extend(struct.pack("<f", sample))
                except OverflowError:
                    raise ValidationError("sample does not fit float32") from None
            else:
                scale = 1 << (width * 8 - 1)
                clipped = max(-1.0, min(1.0, sample))
                value = min(scale - 1, max(-scale, round(clipped * scale)))
                payload.extend(value.to_bytes(width, "little", signed=True))
    return bytes(payload)


def resample_linear(
    samples: Sequence[float],
    source_rate: int,
    target_rate: int,
) -> tuple[float, ...]:
    """Interpolate a single contiguous mono interval; never concatenate gaps.

    Output count is ceil(N * target/source). The last sample is held at the
    right boundary. This applies no antialias filter and is not bandlimited.
    """
    _positive_int(source_rate, "source_rate")
    _positive_int(target_rate, "target_rate")
    values = _samples(samples)
    if not values or source_rate == target_rate:
        return values
    count = (len(values) * target_rate + source_rate - 1) // source_rate
    result = []
    for index in range(count):
        left, remainder = divmod(index * source_rate, target_rate)
        right = min(left + 1, len(values) - 1)
        fraction = remainder / target_rate
        result.append(values[left] * (1 - fraction) + values[right] * fraction)
    return tuple(result)


@dataclass(frozen=True, slots=True)
class LevelMeter:
    peak: float
    rms: float
    peak_dbfs: float | None
    rms_dbfs: float | None
    clipped_samples: int


def measure_level(samples: Sequence[float]) -> LevelMeter:
    """Report None dBFS for silence, suitable for strict JSON metadata."""
    values = _samples(samples)
    peak = max((abs(x) for x in values), default=0.0)
    # Scale before squaring to avoid overflow with finite float32 extremes.
    rms = (
        peak * math.sqrt(math.fsum((x / peak) ** 2 for x in values) / len(values)) if peak else 0.0
    )
    return LevelMeter(
        peak,
        rms,
        20 * math.log10(peak) if peak else None,
        20 * math.log10(rms) if rms else None,
        sum(abs(x) >= 1 for x in values),
    )


@dataclass(frozen=True, slots=True)
class FrameRegion:
    """Half-open local source-block frame range, not a global session time."""

    start_frame: int
    end_frame: int


def energy_vad(
    block: PCMBlock,
    *,
    threshold_dbfs: float = -40.0,
    window_ms: int = 20,
    min_speech_ms: int = 40,
    padding_ms: int = 100,
) -> tuple[FrameRegion, ...]:
    """Find energy regions inside one immutable block, preserving source offsets.

    This stateless detector never merges blocks, gaps or epochs. It uses the
    mean channel energy (not phase-cancelling mono) for detection. Short blocks
    may require min_speech_ms=0; returned ranges remain local to this block.
    """
    if not isinstance(block, PCMBlock):
        raise ValidationError("VAD requires a PCMBlock")
    if isinstance(threshold_dbfs, bool) or not isinstance(threshold_dbfs, (int, float)):
        raise ValidationError("invalid VAD threshold")
    if not math.isfinite(threshold_dbfs) or not -200 <= threshold_dbfs <= 0:
        raise ValidationError("invalid VAD threshold")
    _positive_int(window_ms, "window_ms")
    for name, value in (("min_speech_ms", min_speech_ms), ("padding_ms", padding_ms)):
        if type(value) is not int or value < 0:
            raise ValidationError(f"{name} must be nonnegative")
    frames = decode_pcm(block.payload, block.format)
    rate = block.format.sample_rate
    window = max(1, rate * window_ms // 1000)
    minimum = (rate * min_speech_ms + 999) // 1000
    padding = (rate * padding_ms + 999) // 1000
    threshold = 10 ** (threshold_dbfs / 20)
    runs: list[FrameRegion] = []
    speech_start: int | None = None
    for start in range(0, len(frames), window):
        end = min(start + window, len(frames))
        level = measure_level(tuple(x for row in frames[start:end] for x in row)).rms
        if level >= threshold and speech_start is None:
            speech_start = start
        if level < threshold and speech_start is not None:
            if start - speech_start >= minimum:
                runs.append(FrameRegion(speech_start, start))
            speech_start = None
    if speech_start is not None and len(frames) - speech_start >= minimum:
        runs.append(FrameRegion(speech_start, len(frames)))
    padded: list[FrameRegion] = []
    for run in runs:
        start, end = max(0, run.start_frame - padding), min(len(frames), run.end_frame + padding)
        if padded and start <= padded[-1].end_frame:
            padded[-1] = FrameRegion(padded[-1].start_frame, max(padded[-1].end_frame, end))
        else:
            padded.append(FrameRegion(start, end))
    return tuple(padded)
