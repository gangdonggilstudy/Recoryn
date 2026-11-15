"""L02 independent scalar reconstruction and fake Whisper handoff; no models/IO egress."""

from __future__ import annotations

import hashlib
import importlib
import math
import struct
import threading
from collections import Counter
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from recoryn.providers import ExecutionContext, ProviderError, STTRequest
from recoryn.transcription import FasterWhisperProvider, adapters, audio_input

pytestmark = pytest.mark.integration

RATES = (8000, 11025, 16000, 22050, 44100, 48000, 96000)
SMALL = tuple((rate, count) for rate in RATES for count in (0, 1, 7, 31)) + (
    (15999, 7),
    (16001, 7),
)
DECODE = tuple((width, channels) for width in (1, 2, 3, 4) for channels in (1, 2, 64))
SEEN: Counter[str] = Counter()


def wav(data: bytes, width: int, channels: int, rate: int, *, tag: int = 1) -> bytes:
    # A legal JUNK chunk ensures no oracle assumes a fixed 44-byte WAV header.
    fmt = struct.pack(
        "<HHIIHH", tag, channels, rate, rate * channels * width, channels * width, width * 8
    )
    chunks = b"JUNK\x04\0\0\0testfmt " + struct.pack("<I", 16) + fmt
    chunks += b"data" + struct.pack("<I", len(data)) + data + bytes(len(data) % 2)
    return b"RIFF" + struct.pack("<I", len(chunks) + 4) + b"WAVE" + chunks


def i0(value: float) -> float:
    """Scalar modified Bessel series; independent of numpy's window implementation."""
    result, term, k = 1.0, 1.0, 0
    while True:
        k += 1
        term *= (value / (2 * k)) ** 2
        previous, result = result, result + term
        if result == previous:
            return result


def direct(samples: list[float], rate: int) -> list[float]:
    # Rational time instants and direct scalar sinc summation, no phase table,
    # offsets/gather/einsum, product constants or product output_length helper.
    times = []
    j = 0
    while Fraction(j, 16000) < Fraction(len(samples), rate):
        times.append(Fraction(j * rate, 16000))
        j += 1
    if rate == 16000:
        return samples[:]
    bandwidth = 0.94 * min(rate, 16000) / rate
    radius = 16 / bandwidth
    result = []
    for instant in times:
        weights, contributions = [], []
        for index in range(math.floor(instant - radius) - 1, math.ceil(instant + radius) + 2):
            distance = float(Fraction(index) - instant)
            if abs(distance) >= radius:
                continue
            z = math.pi * bandwidth * distance
            sinc = math.sin(z) / z if z else 1.0
            weight = bandwidth * sinc * i0(8.6 * math.sqrt(1 - (distance / radius) ** 2)) / i0(8.6)
            weights.append(weight)
            contributions.append(weight * samples[index] if 0 <= index < len(samples) else 0.0)
        result.append(math.fsum(contributions) / math.fsum(weights))
    return result


@pytest.mark.parametrize("rate,count", SMALL, ids=[f"r{r}-n{n}" for r, n in SMALL])
def test_small_signal_matches_direct_scalar_sum(rate: int, count: int) -> None:
    source = [((index * 7) % 11 - 5) / 8 for index in range(count)]
    expected = direct(source, rate)
    result = audio_input.resample(source, rate, np)
    assert result.shape == (len(expected),), "L02_SCALAR_LENGTH"
    assert result.dtype == np.float32
    np.testing.assert_allclose(result, expected, atol=6e-8, rtol=6e-8, err_msg="L02_SCALAR_SINC")
    SEEN[f"R-{rate}-{count}"] += 1


@pytest.mark.parametrize("width,channels", DECODE)
def test_pcm_extremes_multichannel_with_nonstandard_header(width: int, channels: int) -> None:
    half = 1 << (8 * width - 1)
    signed = (-half, half - 1, -1, 0, 1)
    frames = [[signed[(frame + channel) % 5] for channel in range(channels)] for frame in range(5)]
    raw = b"".join(
        (value + 128).to_bytes(1, "little")
        if width == 1
        else value.to_bytes(width, "little", signed=True)
        for row in frames
        for value in row
    )
    payload = wav(raw, width, channels, 22050)
    before = hashlib.sha256(payload).digest()
    result, rate = audio_input.decode_pcm_wav(payload, np)
    assert rate == 22050 and result.dtype == np.float64
    expected = [
        float(sum((Fraction(value, half) for value in row), Fraction()) / channels)
        for row in frames
    ]
    np.testing.assert_allclose(result, expected, rtol=0, atol=2**-51)
    assert hashlib.sha256(payload).digest() == before
    SEEN[f"D-{width}-{channels}"] += 1


@pytest.mark.parametrize("case", ("garbage", "float", "width5", "zero_rate", "truncated"))
def test_decoder_rejections_have_only_stable_codes(case: str) -> None:
    payloads = {
        "garbage": b"L02_PRIVATE_CANARY",
        "float": wav(bytes(8), 4, 1, 16000, tag=3),
        "width5": wav(bytes(10), 5, 1, 16000),
        "zero_rate": wav(bytes(8), 2, 1, 0),
        "truncated": wav(bytes(100), 2, 1, 16000)[:-4],
    }
    with pytest.raises(audio_input.AudioInputError) as error:
        audio_input.decode_pcm_wav(payloads[case], np)
    assert str(error.value) == ("INPUT_INVALID" if case == "truncated" else "AUDIO_UNSUPPORTED")


@pytest.mark.parametrize("rate,tone", ((22050, 6500), (44100, 7500), (48000, 8000), (96000, 8500)))
def test_transition_band_has_no_invented_amplitude_guarantee(rate: int, tone: int) -> None:
    count = 31
    source = [math.sin(2 * math.pi * tone * n / rate + 0.17) for n in range(count)]
    expected = direct(source, rate)
    result = audio_input.resample(source, rate, np)
    np.testing.assert_allclose(result, expected, rtol=8e-8, atol=8e-8)


def model_dir(root: Path) -> Path:
    path = root / "fake-model"
    path.mkdir()
    for name in ("model.bin", "config.json", "tokenizer.json"):
        (path / name).write_bytes(b"fake; never opened by a runtime")
    return path


@pytest.mark.parametrize("rate,count", ((8000, 7), (11025, 31), (44100, 31), (96000, 31)))
def test_fake_whisper_time_axis_duration_and_original(
    rate: int, count: int, tmp_path: Path
) -> None:
    path = tmp_path / "source.wav"
    path.write_bytes(wav(b"\x00\x40\x00\xc0" * count, 2, 2, rate))
    before = path.read_bytes()
    seen: list[Any] = []

    def infer(samples: Any, **kwargs: Any) -> Any:
        seen.append(samples)
        # The last array instant is inside the source interval, even though
        # its ceil sample count can describe an end < 1/16000 s beyond it.
        assert Fraction(len(samples) - 1, 16000) < Fraction(count, rate)
        assert Fraction(len(samples), 16000) >= Fraction(count, rate)
        return iter(
            [SimpleNamespace(start=0, end=count / rate, text="synthetic")]
        ), SimpleNamespace()

    provider = FasterWhisperProvider(
        model_dir(tmp_path), model_factory=lambda *a, **k: SimpleNamespace(transcribe=infer)
    )
    result = provider.transcribe(STTRequest(path, offset_ms=137))
    assert result.complete and result.processed_ms == math.ceil(Fraction(count * 1000, rate))
    assert len(seen) == 1 and seen[0].ndim == 1 and seen[0].dtype == np.float32
    assert np.count_nonzero(seen[0]) == 0  # antiphase stereo channel mean
    assert result.segments[0].start_ms == 137
    assert result.segments[0].end_ms == 137 + int(count * 1000 / rate)
    assert path.read_bytes() == before and result.audio_sha256 == hashlib.sha256(before).hexdigest()


def test_cancel_during_resampling_is_not_swallowed() -> None:
    token = ProviderError("CANCELLED")

    def cancel() -> None:
        raise token

    with pytest.raises(ProviderError) as error:
        audio_input.prepare_whisper_audio(wav(bytes(300), 2, 1, 48000), np, check=cancel)
    assert error.value is token


@pytest.mark.parametrize("failure", ("missing_numpy", "decoder", "backend"))
def test_fake_provider_failure_is_safe_and_source_stays_unchanged(
    failure: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "source.wav"
    path.write_bytes(wav(bytes(200), 2, 1, 48000))
    before = path.read_bytes()
    original = importlib.import_module

    def import_module(name: str) -> Any:
        if name == "numpy" and failure == "missing_numpy":
            raise ImportError("L02_PRIVATE_CANARY")
        return original(name)

    def bad_decoder(*args: Any, **kwargs: Any) -> Any:
        raise audio_input.AudioInputError("INPUT_INVALID")

    def infer(*args: Any, **kwargs: Any) -> Any:
        if failure != "backend":
            pytest.fail("must not reach inference")
        raise RuntimeError("L02_PRIVATE_CANARY")

    monkeypatch.setattr(importlib, "import_module", import_module)
    if failure == "decoder":
        monkeypatch.setattr(adapters, "prepare_whisper_audio", bad_decoder)
    provider = FasterWhisperProvider(
        model_dir(tmp_path), model_factory=lambda *a, **k: SimpleNamespace(transcribe=infer)
    )
    result = provider.transcribe(STTRequest(path), ExecutionContext(cancel=threading.Event()))
    assert (
        result.error_code
        == {
            "missing_numpy": "DEPENDENCY_MISSING",
            "decoder": "INPUT_INVALID",
            "backend": "PROVIDER_FAILED",
        }[failure]
    )
    assert not result.complete and result.processed_ms == 0
    assert "L02_PRIVATE_CANARY" not in repr(result) and path.read_bytes() == before


def test_actual_independent_matrix_census() -> None:
    expected = {
        f"R-{r}-{n}"
        for r in (8000, 11025, 16000, 22050, 44100, 48000, 96000)
        for n in (0, 1, 7, 31)
    }
    expected |= {"R-15999-7", "R-16001-7"}
    expected |= {f"D-{w}-{c}" for w in range(1, 5) for c in (1, 2, 64)}
    assert len(expected) == 7 * 4 + 2 + 4 * 3 == 42
    assert set(SEEN) == expected and set(SEEN.values()) == {1}
