"""L02 STT input without PyAV: PCM WAV decode and 16 kHz bandlimited resampling.

Case space: docs/testing/l02-stt-input-cases.md. Oracles are hand-written integer
codes with exact fractions, analytic sinusoids sampled at the target rate and the
counting definition of the output length. None of them reuse the implementation.
"""

from __future__ import annotations

import io
import math
import wave
from fractions import Fraction

import numpy as np
import pytest

from recoryn.transcription import audio_input

RATES = (8_000, 11_025, 16_000, 22_050, 32_000, 44_100, 48_000, 88_200, 96_000)
CHANNELS = (1, 2, 3, 6)
# Five codes per width: minimum, -1 LSB, zero, +1 LSB, maximum with exact values.
CODES: dict[int, list[tuple[int, Fraction]]] = {
    1: [
        (0, Fraction(-1)),
        (127, Fraction(-1, 128)),
        (128, Fraction(0)),
        (129, Fraction(1, 128)),
        (255, Fraction(127, 128)),
    ],
    2: [
        (-32_768, Fraction(-1)),
        (-1, Fraction(-1, 32_768)),
        (0, Fraction(0)),
        (1, Fraction(1, 32_768)),
        (32_767, Fraction(32_767, 32_768)),
    ],
    3: [
        (-8_388_608, Fraction(-1)),
        (-1, Fraction(-1, 8_388_608)),
        (0, Fraction(0)),
        (1, Fraction(1, 8_388_608)),
        (8_388_607, Fraction(8_388_607, 8_388_608)),
    ],
    4: [
        (-(2**31), Fraction(-1)),
        (-1, Fraction(-1, 2**31)),
        (0, Fraction(0)),
        (1, Fraction(1, 2**31)),
        (2**31 - 1, Fraction(2**31 - 1, 2**31)),
    ],
}
DECODE_ROWS = [(width, channels) for width in CODES for channels in CHANNELS]
PASS_ROWS = [
    (rate, tone) for rate in RATES for tone in (100, 1_000, 4_000, 6_000) if tone < rate / 2
]
STOP_ROWS = [
    (rate, tone)
    for rate in RATES
    if rate > 16_000
    for tone in (9_000, 10_000, 12_000, 20_000)
    if tone < rate / 2
]
SMALL_COUNTS = (0, 1, 2, 3, 1_000)


def make_wav(width: int, channels: int, rate: int, frames: bytes) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as stream:
        stream.setnchannels(channels)
        stream.setsampwidth(width)
        stream.setframerate(rate)
        stream.writeframes(frames)
    return buffer.getvalue()


def encode(width: int, code: int) -> bytes:
    return bytes([code]) if width == 1 else code.to_bytes(width, "little", signed=True)


def expected_length(count: int, rate: int) -> int:
    # Number of output instants n / 16000 strictly before the input end count / rate.
    return math.ceil(Fraction(count * 16_000, rate))


def interior(values: np.ndarray, seconds: float = 0.05) -> np.ndarray:
    margin = int(16_000 * seconds)
    return values[margin:-margin]


def test_declared_finite_denominators_are_exact() -> None:
    assert (len(DECODE_ROWS), len(PASS_ROWS), len(STOP_ROWS), len(RATES)) == (16, 33, 21, 9)
    assert len({*DECODE_ROWS}) == 16 and len({*PASS_ROWS}) == 33 and len({*STOP_ROWS}) == 21


@pytest.mark.parametrize(("width", "channels"), DECODE_ROWS)
def test_decode_exact_codes_and_channel_mean(width: int, channels: int) -> None:
    codes = CODES[width]
    frames = b"".join(
        encode(width, codes[(frame + channel) % 5][0])
        for frame in range(5)
        for channel in range(channels)
    )
    samples, rate = audio_input.decode_pcm_wav(make_wav(width, channels, 22_050, frames), np)
    assert rate == 22_050 and samples.dtype == np.float64 and samples.shape == (5,)
    for frame in range(5):
        exact = sum((codes[(frame + c) % 5][1] for c in range(channels)), Fraction(0)) / channels
        assert abs(samples[frame] - float(exact)) <= 2**-50


def test_decode_rejects_float_garbage_and_truncated_input() -> None:
    # IEEE float WAV (format tag 3) is not integer PCM.
    float_header = (
        b"RIFF"
        + (36 + 8).to_bytes(4, "little")
        + b"WAVEfmt "
        + (16).to_bytes(4, "little")
        + (3).to_bytes(2, "little")
        + (1).to_bytes(2, "little")
        + (16_000).to_bytes(4, "little")
        + (64_000).to_bytes(4, "little")
        + (4).to_bytes(2, "little")
        + (32).to_bytes(2, "little")
        + b"data"
        + (8).to_bytes(4, "little")
        + bytes(8)
    )
    for payload, code in (
        (float_header, "AUDIO_UNSUPPORTED"),
        (b"not a riff wave file at all", "AUDIO_UNSUPPORTED"),
        (make_wav(2, 2, 16_000, bytes(400))[:-3], "INPUT_INVALID"),
    ):
        with pytest.raises(audio_input.AudioInputError, match=code):
            audio_input.decode_pcm_wav(payload, np)
    empty, rate = audio_input.decode_pcm_wav(make_wav(2, 1, 44_100, b""), np)
    assert empty.shape == (0,) and rate == 44_100
    assert audio_input.resample(empty, rate, np).shape == (0,)


@pytest.mark.parametrize(("rate", "tone"), PASS_ROWS)
def test_passband_tone_matches_analytic_signal_at_16k(rate: int, tone: int) -> None:
    source = np.sin(2 * np.pi * tone * np.arange(rate) / rate + 0.3)
    result = audio_input.resample(source, rate, np)
    analytic = np.sin(2 * np.pi * tone * np.arange(result.size) / 16_000 + 0.3)
    assert result.dtype == np.float32 and result.size == expected_length(rate, rate)
    assert float(np.max(np.abs(interior(result) - interior(analytic)))) <= 1e-3


@pytest.mark.parametrize(("rate", "tone"), STOP_ROWS)
def test_tones_above_16k_nyquist_are_attenuated_not_aliased(rate: int, tone: int) -> None:
    source = np.sin(2 * np.pi * tone * np.arange(rate) / rate)
    result = interior(audio_input.resample(source, rate, np)).astype(np.float64)
    attenuation = 20 * math.log10(math.sqrt(float(np.mean(result**2))) / math.sqrt(0.5))
    assert attenuation <= -60.0


@pytest.mark.parametrize("rate", RATES)
def test_constant_input_stays_constant(rate: int) -> None:
    result = interior(audio_input.resample(np.full(rate, 0.25), rate, np))
    assert float(np.max(np.abs(result.astype(np.float64) - 0.25))) <= 1e-7


@pytest.mark.parametrize("rate", RATES)
@pytest.mark.parametrize("count", SMALL_COUNTS)
def test_output_length_counts_instants_before_input_end(rate: int, count: int) -> None:
    result = audio_input.resample(np.linspace(-0.5, 0.5, count), rate, np)
    assert result.shape == (expected_length(count, rate),)
    assert bool(np.all(np.isfinite(result)))


@pytest.mark.parametrize("rate", RATES)
@pytest.mark.parametrize("delta", (-1, 0, 1))
def test_output_length_across_processing_block_boundary(rate: int, delta: int) -> None:
    # Upsampling rates cannot produce every length (8 kHz gives only even counts),
    # so take the smallest input whose output reaches the wanted block boundary.
    wanted = audio_input.BLOCK + delta
    count = max(0, (wanted - 1) * rate // 16_000 - 2)
    while expected_length(count, rate) < wanted:
        count += 1
    result = audio_input.resample(np.zeros(count), rate, np)
    assert result.shape == (expected_length(count, rate),)
    assert wanted <= result.size < wanted + math.ceil(16_000 / rate)


def test_cancellation_is_checked_once_per_block_and_propagates() -> None:
    calls: list[int] = []

    def check() -> None:
        calls.append(1)

    total = 3 * audio_input.BLOCK + 1
    audio_input.resample(np.zeros(total), 16_001, np, check=check, target=16_001)
    assert calls == []  # identity rate performs no work
    audio_input.resample(np.zeros(total * 3), 48_000, np, check=check)
    assert len(calls) == 4

    def cancel() -> None:
        calls.append(2)
        if calls.count(2) == 2:
            raise RuntimeError("CANCELLED")

    with pytest.raises(RuntimeError, match="CANCELLED"):
        audio_input.resample(np.zeros(total * 3), 48_000, np, check=cancel)
    assert calls.count(2) == 2


def test_invalid_rate_and_shape_are_rejected() -> None:
    with pytest.raises(audio_input.AudioInputError, match="AUDIO_UNSUPPORTED"):
        audio_input.resample(np.zeros(4), 0, np)
    with pytest.raises(audio_input.AudioInputError, match="INPUT_INVALID"):
        audio_input.resample(np.zeros((2, 2)), 48_000, np)


def test_prepare_48k_stereo_constant_end_to_end() -> None:
    frame = encode(2, 4_096) + encode(2, 4_096)
    result = audio_input.prepare_whisper_audio(make_wav(2, 2, 48_000, frame * 24_000), np)
    assert result.dtype == np.float32 and result.shape == (8_000,)
    assert float(np.max(np.abs(interior(result).astype(np.float64) - 0.125))) <= 1e-7
