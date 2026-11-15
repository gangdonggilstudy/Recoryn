"""Decode verified integer PCM WAV into 16 kHz mono float32 without PyAV/FFmpeg.

License review L01 D1 removes PyAV from the distribution. Local Whisper therefore
receives an already decoded array. The resampler is a Kaiser-windowed sinc
polyphase interpolator evaluated at exact rational output positions; it is a
bandlimited derived conversion and never modifies the source WAV bytes.
"""

from __future__ import annotations

import io
import math
import wave
from collections.abc import Callable
from fractions import Fraction
from typing import Any

TARGET_RATE = 16_000
ZERO_CROSSINGS = 16
ROLLOFF = 0.94
KAISER_BETA = 8.6
BLOCK = 16_384
_SCALES = {1: 128.0, 2: 32_768.0, 3: 8_388_608.0, 4: 2_147_483_648.0}


class AudioInputError(ValueError):
    """Stable code only; raw decoder state is never exposed."""


def decode_pcm_wav(payload: bytes, np: Any) -> tuple[Any, int]:
    """Return float64 mono samples (channel mean, full scale [-1, 1)) and the rate."""
    try:
        with wave.open(io.BytesIO(payload), "rb") as audio:
            channels, width = audio.getnchannels(), audio.getsampwidth()
            rate, frames = audio.getframerate(), audio.getnframes()
            if audio.getcomptype() != "NONE" or width not in _SCALES or channels < 1 or rate < 1:
                raise AudioInputError("AUDIO_UNSUPPORTED")
            data = audio.readframes(frames)
    except (EOFError, wave.Error):
        raise AudioInputError("AUDIO_UNSUPPORTED") from None
    if len(data) != frames * channels * width:
        raise AudioInputError("INPUT_INVALID")
    if width == 1:
        values = np.frombuffer(data, dtype=np.uint8).astype(np.int64) - 128
    elif width == 2:
        values = np.frombuffer(data, dtype="<i2").astype(np.int64)
    elif width == 3:
        triples = np.frombuffer(data, dtype=np.uint8).reshape(-1, 3).astype(np.int64)
        values = triples[:, 0] | (triples[:, 1] << 8) | (triples[:, 2] << 16)
        values = np.where(values >= 1 << 23, values - (1 << 24), values)
    else:
        values = np.frombuffer(data, dtype="<i4").astype(np.int64)
    mono = values.reshape(frames, channels).astype(np.float64).mean(axis=1)
    return mono / _SCALES[width], rate


def output_length(count: int, rate: int, target: int = TARGET_RATE) -> int:
    """ceil(count * target / rate): every output position t < count / rate."""
    return -(-count * target // rate)


def _phase_table(rate: int, target: int, np: Any) -> tuple[Any, Any, int, int]:
    ratio = Fraction(target, rate)
    up, down = ratio.numerator, ratio.denominator
    # Cutoff in cycles per input sample: below the narrower of both Nyquist limits.
    cutoff = 0.5 * min(1.0, target / rate) * ROLLOFF
    half_width = ZERO_CROSSINGS / (2.0 * cutoff)
    taps = math.ceil(half_width)
    offsets = np.arange(-taps + 1, taps + 1, dtype=np.int64)
    phases = np.arange(up, dtype=np.float64)[:, None] / up
    distance = offsets[None, :].astype(np.float64) - phases
    inside = np.abs(distance) < half_width
    ratio_sq = np.clip(1.0 - (distance / half_width) ** 2, 0.0, 1.0)
    window = np.where(inside, np.i0(KAISER_BETA * np.sqrt(ratio_sq)) / np.i0(KAISER_BETA), 0.0)
    kernel = 2.0 * cutoff * np.sinc(2.0 * cutoff * distance) * window
    # Unit DC gain for every phase: a constant input stays constant.
    kernel /= kernel.sum(axis=1, keepdims=True)
    return kernel, offsets, up, down


def resample(
    samples: Any,
    rate: int,
    np: Any,
    *,
    target: int = TARGET_RATE,
    check: Callable[[], None] | None = None,
) -> Any:
    """Bandlimited conversion of mono float samples to ``target`` Hz as float32."""
    if rate < 1 or target < 1:
        raise AudioInputError("AUDIO_UNSUPPORTED")
    source = np.asarray(samples, dtype=np.float64)
    if source.ndim != 1:
        raise AudioInputError("INPUT_INVALID")
    if rate == target or source.size == 0:
        return source.astype(np.float32)
    kernel, offsets, up, down = _phase_table(rate, target, np)
    pad = int(offsets[-1])
    padded = np.concatenate((np.zeros(pad), source, np.zeros(pad)))
    total = output_length(int(source.size), rate, target)
    result = np.empty(total, dtype=np.float32)
    for start in range(0, total, BLOCK):
        if check is not None:
            check()
        index = np.arange(start, min(total, start + BLOCK), dtype=np.int64) * down
        base, phase = index // up, index % up
        gathered = padded[base[:, None] + offsets[None, :] + pad]
        result[start : start + index.size] = np.einsum("ij,ij->i", kernel[phase], gathered)
    return result


def prepare_whisper_audio(
    payload: bytes, np: Any, *, check: Callable[[], None] | None = None
) -> Any:
    samples, rate = decode_pcm_wav(payload, np)
    return resample(samples, rate, np, check=check)
