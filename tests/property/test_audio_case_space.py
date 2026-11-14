"""Q22 bounded case spaces; independent bytes, set geometry and rational oracles.

The final ledger is meaningful for a complete, single-process run of this file.
No physical devices, model weights, provider or network calls are involved.
"""

from __future__ import annotations

import bisect
import hashlib
import itertools
import json
import math
import os
import shutil
import struct
import subprocess
import sys
from collections import defaultdict
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from recoryn.audio import (
    align_blocks,
    decode_pcm,
    downmix_mono,
    encode_pcm,
    energy_vad,
    measure_level,
    resample_linear,
)
from recoryn.domain import AudioFormat, PCMBlock, ValidationError

pytestmark = pytest.mark.property

FORMATS = ("s16le", "s24le", "s32le", "f32le")
CHANNELS = (1, 2, 3, 64)
INTEGER_FORMATS = FORMATS[:3]
QUANTIZERS = (
    "low_clip",
    "negative_full",
    "negative_max",
    "neg_two_half",
    "neg_odd_tie",
    "neg_half",
    "pos_half",
    "pos_odd_tie",
    "pos_two_half",
    "positive_max",
    "positive_full",
    "high_clip",
)
NONFINITE_WORDS = (0x7F800000, 0xFF800000, 0x7FC00000, 0xFFC00000, 0x7F800001, 0xFF800001)
THRESHOLDS: dict[str, tuple[Any, bool]] = {
    "below": (-201, False),
    "lower": (-200, True),
    "middle": (-20, True),
    "upper": (0, True),
    "above": (1, False),
    "nan": (math.nan, False),
    "inf": (math.inf, False),
    "negative_inf": (-math.inf, False),
    "bool": (True, False),
    "text": ("-20", False),
}
WINDOWS: dict[str, tuple[Any, bool]] = {
    "valid": (1, True),
    "zero": (0, False),
    "bool": (True, False),
}
MINIMUMS: dict[str, tuple[Any, bool]] = {
    "valid": (0, True),
    "negative": (-1, False),
    "none": (None, False),
}
PADDINGS: dict[str, tuple[Any, bool]] = {
    "valid": (0, True),
    "negative": (-1, False),
    "bool": (False, False),
}
RATES: dict[str, tuple[Any, bool]] = {
    "negative": (-1, False),
    "zero": (0, False),
    "bool": (True, False),
    "float": (1.0, False),
    "none": (None, False),
    "text": ("1", False),
    "one": (1, True),
    "three": (3, True),
}
INVALID_SAMPLES: dict[str, Any] = {
    "bool": True,
    "none": None,
    "text": "0",
    "nan": math.nan,
    "inf": math.inf,
    "negative_inf": -math.inf,
    "overflow": 10**500,
}
QUALITIES = ("DEVICE_CORRELATED", "SYNTHETIC", "UNKNOWN", "ARRIVAL_ONLY", "INVALID")


def _product(*domains: Any) -> tuple[tuple[Any, ...], ...]:
    return tuple(itertools.product(*domains))


SPACES: dict[str, tuple[tuple[Any, ...], ...]] = {
    "pcm_partition": tuple(
        (kind, channels, mask, mode)
        for kind, channels, mask in itertools.product(FORMATS, CHANNELS, range(32))
        for mode in (("packet",) if mask == 0 else ("packet", "fragment"))
    ),
    "byte_shape": _product(
        FORMATS, CHANNELS, (1, 6), ("less_frame", "less_byte", "exact", "extra_byte", "extra_frame")
    ),
    "quantization": _product(INTEGER_FORMATS, (1, 3), QUANTIZERS),
    "float_nonfinite": tuple(
        (word, channels, position)
        for word in NONFINITE_WORDS
        for channels in (1, 2, 64)
        for position in sorted({0, channels // 2, channels - 1})
    ),
    "vad_patterns": _product(range(32), ("s16le", "f32le"), (1, 2), (1, 2), (0, 2, 4), (0, 1)),
    "vad_equal": (("s16le", 1), ("f32le", 2)),
    "vad_rate_rounding": _product((11025, 44100, 48000), (-1, 0, 1), (0, 1), (0, 1), (1, 2)),
    "vad_guards": _product(THRESHOLDS, WINDOWS, MINIMUMS, PADDINGS),
    "rate_guards": _product(RATES, RATES),
    "sample_guards": _product(
        INVALID_SAMPLES, ("meter", "downmix", "resample", "s16_encode", "f32_encode")
    ),
    "clock_cube": _product(
        (0, 60_000_000_000, -15_000_000), (False, True), (False, True), QUALITIES, (False, True)
    ),
    "clock_taint": _product(
        (60_000_000_000, -15_000_000),
        ("no_time", "time_flag", "quality", "no_position"),
        (False, True),
    ),
}
# Closed counts deliberately do not call len(SPACES), its generators, or SUT.
DENOMINATORS = {
    "pcm_partition": 4 * 4 * (1 + (2**5 - 1) * 2),
    "byte_shape": 4 * 4 * 2 * 5,
    "quantization": 3 * 2 * 12,
    "float_nonfinite": 6 * (1 + 2 + 3),
    "vad_patterns": 2**5 * 2 * 2 * 2 * 3 * 2,
    "vad_equal": 2,
    "vad_rate_rounding": 3 * 3 * 2 * 2 * 2,
    "vad_guards": 10 * 3**3,
    "rate_guards": 8**2,
    "sample_guards": 7 * 5,
    "clock_cube": 3 * 2 * 2 * 5 * 2,
    "clock_taint": 2 * 4 * 2,
}
OBSERVED: dict[str, set[str]] = defaultdict(set)
PCM_INPUTS: set[tuple[Any, ...]] = set()


def _case_id(family: str, row: tuple[Any, ...]) -> str:
    return "Q22-" + family + "-" + "-".join(str(value) for value in row)


def _ids(family: str) -> list[str]:
    return [_case_id(family, row) for row in SPACES[family]]


def _observe(family: str, row: tuple[Any, ...]) -> None:
    identifier = _case_id(family, row)
    assert identifier not in OBSERVED[family], "Q22_DUPLICATE_EXECUTED_ROW"
    OBSERVED[family].add(identifier)


def _fixture(
    kind: str, channels: int, count: int = 6
) -> tuple[bytes, tuple[tuple[float, ...], ...]]:
    """Build from original signed words/IEEE bytes, never production encode()."""
    width = {"s16le": 2, "s24le": 3, "s32le": 4, "f32le": 4}[kind]
    if kind == "f32le":
        words = (-1.5, -0.5, -0.0, 0.25, 0.5, 1.25)
        rows = tuple(
            tuple(words[(frame + channel // (6**frame) % 6) % 6] for channel in range(channels))
            for frame in range(count)
        )
        return b"".join(struct.pack("<f", sample) for row in rows for sample in row), rows
    scale = 2 ** (8 * width - 1)
    words_i = (-scale, -1, 0, 1, scale - 1, scale // 2)
    values = tuple(
        tuple(words_i[(frame + channel // (6**frame) % 6) % 6] for channel in range(channels))
        for frame in range(count)
    )
    payload = b"".join(
        value.to_bytes(width, "little", signed=True) for row in values for value in row
    )
    return payload, tuple(tuple(float(Fraction(value, scale)) for value in row) for row in values)


def _partition(count: int, mask: int) -> tuple[tuple[int, int], ...]:
    cuts = (0, *(index for index in range(1, count) if mask & (1 << (index - 1))), count)
    return tuple(zip(cuts, cuts[1:], strict=False))


@pytest.mark.parametrize("case", SPACES["pcm_partition"], ids=_ids("pcm_partition"))
def test_pcm_all_partitions_preserve_values_bytes_frames_and_clock(case: tuple[Any, ...]) -> None:
    _observe("pcm_partition", case)
    kind, channels, mask, mode = case
    payload, expected = _fixture(kind, channels)
    assert len(set(zip(*expected, strict=True))) == channels, "Q22_DISTINCT_CHANNEL_SIGNATURES"
    before = bytes(payload)
    fmt = AudioFormat(1000, channels, kind)
    pieces = _partition(6, mask)
    restored: list[tuple[float, ...]] = []
    output = []
    blocks = []
    for index, (start, end) in enumerate(pieces):
        source = payload[start * fmt.frame_bytes : end * fmt.frame_bytes]
        decoded = decode_pcm(source, fmt)
        assert decoded == expected[start:end], "Q22_DECODE_PARTITION_VALUES"
        assert encode_pcm(expected[start:end], fmt) == source, "Q22_ENCODE_PARTITION_BYTES"
        restored.extend(decoded)
        output.append(encode_pcm(decoded, fmt))
        blocks.append(
            PCMBlock(
                "q22",
                "mic",
                "epoch",
                index if mode == "packet" else 0,
                fmt,
                end - start,
                source,
                1_000_000_000 + start * 1_000_000,
                99_000_000_000,
                start,
                fragment_index=index if mode == "fragment" else 0,
                fragment_count=len(pieces) if mode == "fragment" else 1,
            )
        )
    metadata = tuple(block.to_metadata() for block in blocks)
    signature = (
        kind,
        channels,
        tuple(
            (
                block.sequence,
                block.frame_count,
                block.payload,
                block.capture_mono_ns,
                block.device_frame_position,
                block.fragment_index,
                block.fragment_count,
            )
            for block in blocks
        ),
    )
    assert signature not in PCM_INPUTS, "Q22_DUPLICATE_EFFECTIVE_PCM_INPUT"
    PCM_INPUTS.add(signature)
    spans = align_blocks(blocks, origin_ns=1_000_000_000)
    assert tuple(restored) == expected and b"".join(output) == before
    assert sum(block.frame_count for block in blocks) == 6
    assert (
        sum(len(block.payload) for block in blocks)
        == 6 * channels * {"s16le": 2, "s24le": 3, "s32le": 4, "f32le": 4}[kind]
    )
    assert [(span.start_ns, span.end_ns) for span in spans] == [
        (start * 1_000_000, end * 1_000_000) for start, end in pieces
    ]
    assert {span.quality for span in spans} == {"DEVICE_CORRELATED"}
    assert payload == before and tuple(block.to_metadata() for block in blocks) == metadata


@pytest.mark.parametrize("case", SPACES["byte_shape"], ids=_ids("byte_shape"))
def test_byte_shape_acceptance_distinguishes_decoder_from_declared_block(
    case: tuple[Any, ...],
) -> None:
    _observe("byte_shape", case)
    kind, channels, frames, delta = case
    width = {"s16le": 2, "s24le": 3, "s32le": 4, "f32le": 4}[kind]
    frame_bytes = channels * width
    lengths = {
        "less_frame": (frames - 1) * frame_bytes,
        "less_byte": frames * frame_bytes - 1,
        "exact": frames * frame_bytes,
        "extra_byte": frames * frame_bytes + 1,
        "extra_frame": (frames + 1) * frame_bytes,
    }
    payload = bytes(lengths[delta])
    fmt = AudioFormat(48000, channels, kind)
    if delta in {"less_byte", "extra_byte"}:
        with pytest.raises(ValidationError):
            decode_pcm(payload, fmt)
    else:
        expected_frames = frames + {"less_frame": -1, "exact": 0, "extra_frame": 1}[delta]
        assert decode_pcm(payload, fmt) == ((0.0,) * channels,) * expected_frames
    if delta == "exact":
        assert PCMBlock("s", "t", "e", 0, fmt, frames, payload, 0, 0).payload == payload
    else:
        with pytest.raises(ValidationError):
            PCMBlock("s", "t", "e", 0, fmt, frames, payload, 0, 0)


@pytest.mark.parametrize("case", SPACES["quantization"], ids=_ids("quantization"))
def test_integer_ties_clipping_and_channel_identity(case: tuple[Any, ...]) -> None:
    _observe("quantization", case)
    kind, channels, role = case
    width = {"s16le": 2, "s24le": 3, "s32le": 4}[kind]
    scale = 2 ** (width * 8 - 1)
    table = {
        "low_clip": (Fraction(-2), -scale),
        "negative_full": (Fraction(-1), -scale),
        "negative_max": (Fraction(-scale + 1, scale), -scale + 1),
        "neg_two_half": (Fraction(-5, 2 * scale), -2),
        "neg_odd_tie": (Fraction(-3, 2 * scale), -2),
        "neg_half": (Fraction(-1, 2 * scale), 0),
        "pos_half": (Fraction(1, 2 * scale), 0),
        "pos_odd_tie": (Fraction(3, 2 * scale), 2),
        "pos_two_half": (Fraction(5, 2 * scale), 2),
        "positive_max": (Fraction(scale - 1, scale), scale - 1),
        "positive_full": (Fraction(1), scale - 1),
        "high_clip": (Fraction(2), scale - 1),
    }
    value, integer = table[role]
    row = (float(value),) if channels == 1 else (float(value), -0.5, 0.25)
    integers = (integer,) if channels == 1 else (integer, -scale // 2, scale // 4)
    expected = b"".join(number.to_bytes(width, "little", signed=True) for number in integers)
    assert encode_pcm((row,), AudioFormat(48000, channels, kind)) == expected, "Q22_ROUND_TIES_EVEN"


@pytest.mark.parametrize("case", SPACES["float_nonfinite"], ids=_ids("float_nonfinite"))
def test_nonfinite_ieee_word_is_rejected_at_channel_positions(case: tuple[Any, ...]) -> None:
    _observe("float_nonfinite", case)
    word, channels, position = case
    payload = b"".join(
        struct.pack("<I", word) if index == position else struct.pack("<f", 0.25)
        for index in range(channels)
    )
    before = bytes(payload)
    with pytest.raises(ValidationError):
        decode_pcm(payload, AudioFormat(48000, channels, "f32le"))
    assert payload == before


def _components(points: set[int]) -> tuple[tuple[int, int], ...]:
    groups = itertools.groupby(enumerate(sorted(points)), key=lambda item: item[1] - item[0])
    result = []
    for _, group in groups:
        values = [value for _, value in group]
        result.append((values[0], values[-1] + 1))
    return tuple(result)


def _vad_oracle(
    bits: tuple[bool, ...], window: int, minimum: int, padding: int
) -> tuple[tuple[int, int], ...]:
    active: set[int] = set()
    for start in range(0, len(bits), window):
        stop = min(start + window, len(bits))
        if any(bits[start:stop]):
            active.update(range(start, stop))
    retained = {
        point
        for left, right in _components(active)
        if right - left >= minimum
        for point in range(left, right)
    }
    expanded = {
        point + shift
        for point in retained
        for shift in range(-padding, padding + 1)
        if 0 <= point + shift < len(bits)
    }
    return _components(expanded)


@pytest.mark.parametrize("case", SPACES["vad_patterns"], ids=_ids("vad_patterns"))
def test_vad_all_small_signal_patterns_use_source_set_geometry(case: tuple[Any, ...]) -> None:
    _observe("vad_patterns", case)
    mask, kind, channels, window, minimum, padding = case
    bits = tuple(bool(mask & (1 << index)) for index in range(5))
    frames = tuple(
        (0.5 if bit else 0.0,) if channels == 1 else (0.5 if bit else 0.0, -0.5 if bit else 0.0)
        for bit in bits
    )
    # Direct PCM words keep the fixture independent of production encode().
    payload = b"".join(
        struct.pack("<f", value) if kind == "f32le" else struct.pack("<h", int(value * 32768))
        for frame in frames
        for value in frame
    )
    block = PCMBlock("s", "t", "e", 0, AudioFormat(1000, channels, kind), 5, payload, 0, 0, 77)
    before = block.to_metadata()
    actual = energy_vad(
        block, threshold_dbfs=-20, window_ms=window, min_speech_ms=minimum, padding_ms=padding
    )
    assert tuple((region.start_frame, region.end_frame) for region in actual) == _vad_oracle(
        bits, window, minimum, padding
    ), "Q22_VAD_SET_GEOMETRY"
    assert block.payload == payload and block.to_metadata() == before


@pytest.mark.parametrize("case", SPACES["vad_equal"], ids=_ids("vad_equal"))
def test_vad_threshold_equality_is_inclusive(case: tuple[Any, ...]) -> None:
    _observe("vad_equal", case)
    kind, channels = case
    payload = b"\x00\x80" * 5 if kind == "s16le" else struct.pack("<ff", 1.0, -1.0) * 5
    block = PCMBlock("s", "t", "e", 0, AudioFormat(1000, channels, kind), 5, payload, 0, 0)
    actual = energy_vad(block, threshold_dbfs=0, window_ms=1, min_speech_ms=0, padding_ms=0)
    assert tuple((region.start_frame, region.end_frame) for region in actual) == ((0, 5),), (
        "Q22_VAD_EQUAL_THRESHOLD"
    )


@pytest.mark.parametrize("case", SPACES["vad_rate_rounding"], ids=_ids("vad_rate_rounding"))
def test_vad_millisecond_floor_window_and_ceil_minimum_padding(case: tuple[Any, ...]) -> None:
    _observe("vad_rate_rounding", case)
    rate, delta, minimum_ms, padding_ms, channels = case
    window = math.floor(Fraction(rate, 1000))
    minimum = math.ceil(Fraction(rate * minimum_ms, 1000))
    padding = math.ceil(Fraction(rate * padding_ms, 1000))
    bits = (False,) * window + (True,) * (window + delta) + (False,) * window
    word = b"\x00\x40" if channels == 1 else b"\x00\x40\x00\xc0"
    payload = b"".join(word if bit else bytes(2 * channels) for bit in bits)
    block = PCMBlock("s", "t", "e", 0, AudioFormat(rate, channels), len(bits), payload, 0, 0)
    # At most 48 samples per window: a single +/-0.5 sample stays well above
    # -40dBFS, so binary occupancy is a valid, separated energy oracle.
    actual = energy_vad(
        block, threshold_dbfs=-40, window_ms=1, min_speech_ms=minimum_ms, padding_ms=padding_ms
    )
    assert tuple((region.start_frame, region.end_frame) for region in actual) == _vad_oracle(
        bits, window, minimum, padding
    ), "Q22_VAD_RATE_ROUNDING"
    assert block.payload == payload


@pytest.mark.parametrize("case", SPACES["vad_guards"], ids=_ids("vad_guards"))
def test_vad_parameter_cube_includes_multiple_invalid_inputs(case: tuple[Any, ...]) -> None:
    _observe("vad_guards", case)
    threshold, window, minimum, padding = [
        table[key]
        for table, key in zip((THRESHOLDS, WINDOWS, MINIMUMS, PADDINGS), case, strict=True)
    ]
    block = PCMBlock("s", "t", "e", 0, AudioFormat(1000, 1), 5, bytes(10), 0, 0)
    options = dict(
        threshold_dbfs=threshold[0],
        window_ms=window[0],
        min_speech_ms=minimum[0],
        padding_ms=padding[0],
    )
    if all(option[1] for option in (threshold, window, minimum, padding)):
        assert energy_vad(block, **options) == ()
    else:
        with pytest.raises(ValidationError):
            energy_vad(block, **options)


@pytest.mark.parametrize("case", SPACES["rate_guards"], ids=_ids("rate_guards"))
def test_both_resample_rate_positions_have_independent_type_guards(case: tuple[Any, ...]) -> None:
    _observe("rate_guards", case)
    source, target = (RATES[key] for key in case)
    if not (source[1] and target[1]):
        with pytest.raises(ValidationError):
            resample_linear((-0.5, 0.5), source[0], target[0])
    else:
        actual = resample_linear((-0.5, 0.5), source[0], target[0])
        assert actual == pytest.approx(
            _polyline((-4, 4), source[0], target[0]), abs=1e-12, rel=1e-12
        )


@pytest.mark.parametrize("case", SPACES["sample_guards"], ids=_ids("sample_guards"))
def test_nonfinite_and_non_numeric_samples_are_rejected_by_every_numeric_entry(
    case: tuple[Any, ...],
) -> None:
    _observe("sample_guards", case)
    name, operation = case
    value = INVALID_SAMPLES[name]
    with pytest.raises(ValidationError):
        if operation == "meter":
            measure_level((value,))
        elif operation == "downmix":
            downmix_mono(((value,),))
        elif operation == "resample":
            resample_linear((value,), 1, 3)
        else:
            encode_pcm(
                ((value,),), AudioFormat(1000, 1, "s16le" if operation == "s16_encode" else "f32le")
            )


def _clock(index: int) -> PCMBlock:
    return PCMBlock(
        "s",
        "t",
        "old",
        index,
        AudioFormat(48000, 1),
        480,
        bytes(960),
        1_000_000_000 + index * 10_000_000,
        900_000_000_000,
        index * 480,
    )


@pytest.mark.parametrize("case", SPACES["clock_cube"], ids=_ids("clock_cube"))
def test_clock_quality_epoch_timestamp_and_position_cube(case: tuple[Any, ...]) -> None:
    _observe("clock_cube", case)
    jump, fresh, timestamp_error, quality, missing_position = case
    epoch = "new" if fresh else "old"
    second = replace(
        _clock(1),
        epoch_id=epoch,
        sequence=0 if fresh else 1,
        capture_mono_ns=1_010_000_000 + jump,
        device_frame_position=None if missing_position else 0 if fresh else 480,
        clock_quality=quality,
        flags=("TIMESTAMP_ERROR",) if timestamp_error else (),
    )
    third = replace(
        _clock(2),
        epoch_id=epoch,
        sequence=1 if fresh else 2,
        capture_mono_ns=1_020_000_000 + jump,
        device_frame_position=480 if fresh else 960,
    )
    blocks = (_clock(0), second, third)
    before = tuple(block.to_metadata() for block in blocks)
    trusted = (
        quality in {"DEVICE_CORRELATED", "SYNTHETIC"}
        and not timestamp_error
        and not missing_position
    )
    tainted = trusted and not fresh and jump != 0
    expected = (
        "DEVICE_CORRELATED",
        "UNCERTAIN_CLOCK" if tainted else "DEVICE_CORRELATED" if trusted else "UNKNOWN",
        "UNCERTAIN_CLOCK" if tainted else "DEVICE_CORRELATED",
    )
    spans = align_blocks(blocks, origin_ns=1_000_000_000)
    assert tuple(span.quality for span in spans) == expected, "Q22_CLOCK_DECISION_TABLE"
    assert spans[0].start_ns == 0
    assert spans[1].start_ns == (10_000_000 + jump if trusted else None)
    assert spans[2].start_ns == 20_000_000 + jump
    assert all(span.source_start_frame == 0 and span.source_end_frame == 480 for span in spans)
    if tainted:
        assert spans[1].drift_ppm is None and spans[2].drift_ppm is None
    assert tuple(block.to_metadata() for block in blocks) == before


@pytest.mark.parametrize("case", SPACES["clock_taint"], ids=_ids("clock_taint"))
def test_clock_taint_survives_each_unknown_class_until_new_epoch(case: tuple[Any, ...]) -> None:
    _observe("clock_taint", case)
    jump, invalid, reset = case
    unknown = replace(_clock(2), capture_mono_ns=1_020_000_000 + jump)
    changes: dict[str, dict[str, Any]] = {
        "no_time": {"capture_mono_ns": None},
        "time_flag": {"flags": ("TIMESTAMP_ERROR",)},
        "quality": {"clock_quality": "UNKNOWN"},
        "no_position": {"device_frame_position": None},
    }
    unknown = replace(unknown, **changes[invalid])
    last = replace(
        _clock(3), epoch_id="fresh" if reset else "old", capture_mono_ns=1_030_000_000 + jump
    )
    blocks = (_clock(0), replace(_clock(1), capture_mono_ns=1_010_000_000 + jump), unknown, last)
    spans = align_blocks(blocks, origin_ns=1_000_000_000)
    assert tuple(span.quality for span in spans) == (
        "DEVICE_CORRELATED",
        "UNCERTAIN_CLOCK",
        "UNKNOWN",
        "DEVICE_CORRELATED" if reset else "UNCERTAIN_CLOCK",
    ), "Q22_TAINT_EPOCH_RESET"
    assert spans[2].start_ns is None and spans[2].end_ns is None
    assert spans[3].start_ns == 30_000_000 + jump


def test_finite_case_ledger_matches_closed_denominators_and_unique_executed_ids() -> None:
    report = {}
    assert sum(DENOMINATORS.values()) == 3391
    assert len(PCM_INPUTS) == DENOMINATORS["pcm_partition"]
    for family, denominator in DENOMINATORS.items():
        identifiers = _ids(family)
        expected = set(identifiers)
        actual = OBSERVED[family]
        missing, unexpected = expected - actual, actual - expected
        duplicates = len(identifiers) - len(expected)
        assert len(identifiers) == len(expected) == denominator, (family, denominator)
        assert not missing and not unexpected and not duplicates, (
            family,
            missing,
            unexpected,
            duplicates,
        )
        report[family] = {
            "denominator": denominator,
            "executed_unique": len(actual),
            "missing": len(missing),
            "duplicates": duplicates,
        }
    print("Q22_CASE_SPACE " + json.dumps(report, sort_keys=True))


def _polyline(values: tuple[int, ...], source: int, target: int) -> tuple[float, ...]:
    if not values:
        return ()
    times = tuple(Fraction(index, source) for index in range(len(values)))
    amplitudes = tuple(Fraction(value, 8) for value in values)
    result = []
    for index in range(math.ceil(Fraction(len(values) * target, source))):
        time = Fraction(index, target)
        if time >= times[-1]:
            value = amplitudes[-1]
        else:
            right = bisect.bisect_right(times, time)
            left = right - 1
            value = (
                (times[right] - time) * amplitudes[left] + (time - times[left]) * amplitudes[right]
            ) / (times[right] - times[left])
        result.append(float(value))
    return tuple(result)


@st.composite
def _integer_signal(draw: Any) -> tuple[str, int, int, tuple[int, ...], int]:
    kind = draw(st.sampled_from(INTEGER_FORMATS))
    channels = draw(st.integers(1, 4))
    count = draw(st.integers(1, 16))
    scale = 2 ** ({"s16le": 16, "s24le": 24, "s32le": 32}[kind] - 1)
    values = tuple(
        draw(
            st.lists(
                st.integers(-scale, scale - 1), min_size=count * channels, max_size=count * channels
            )
        )
    )
    return kind, channels, count, values, draw(st.integers(0, 2 ** (count - 1) - 1))


@settings(max_examples=120, deadline=None, derandomize=True, database=None)
@given(signal=_integer_signal())
def test_generated_integer_full_range_partition_round_trip(signal: tuple[Any, ...]) -> None:
    kind, channels, count, values, mask = signal
    width = {"s16le": 2, "s24le": 3, "s32le": 4}[kind]
    scale = 2 ** (width * 8 - 1)
    payload = b"".join(value.to_bytes(width, "little", signed=True) for value in values)
    expected = tuple(
        tuple(float(Fraction(value, scale)) for value in values[start : start + channels])
        for start in range(0, len(values), channels)
    )
    fmt = AudioFormat(44100, channels, kind)
    actual = tuple(
        row
        for left, right in _partition(count, mask)
        for row in decode_pcm(payload[left * channels * width : right * channels * width], fmt)
    )
    assert actual == expected and encode_pcm(actual, fmt) == payload


@settings(max_examples=100, deadline=None, derandomize=True, database=None)
@given(
    values=st.lists(
        st.floats(width=32, allow_nan=False, allow_infinity=False), min_size=1, max_size=16
    ),
    mask=st.integers(0, 32767),
)
def test_generated_finite_float32_preserves_ieee_bytes_and_signed_zero(
    values: list[float], mask: int
) -> None:
    payload = b"".join(struct.pack("<f", value) for value in values)
    fmt = AudioFormat(48000, 1, "f32le")
    reconstructed = b"".join(
        encode_pcm(decode_pcm(payload[left * 4 : right * 4], fmt), fmt)
        for left, right in _partition(len(values), mask)
    )
    assert reconstructed == payload, "Q22_FLOAT32_BYTE_IDENTITY"


@settings(max_examples=120, deadline=None, derandomize=True, database=None)
@given(
    values=st.lists(st.integers(-32, 32), min_size=0, max_size=20),
    source=st.integers(1, 64),
    target=st.integers(1, 64),
    scale=st.sampled_from((-1.0, 0.5, 2.0)),
    shift=st.integers(-8, 8),
)
def test_generated_resampling_matches_rational_knots_and_affine_transform(
    values: list[int], source: int, target: int, scale: float, shift: int
) -> None:
    samples = tuple(value / 8 for value in values)
    actual = resample_linear(samples, source, target)
    expected = _polyline(tuple(values), source, target)
    assert len(actual) == len(expected)
    assert actual == pytest.approx(expected, abs=1e-12, rel=1e-12)
    transformed = resample_linear(tuple(scale * value + shift for value in samples), source, target)
    assert transformed == pytest.approx(
        tuple(scale * value + shift for value in actual), abs=1e-12, rel=1e-12
    )


MUTANTS = (
    (
        "Q22-M01_TRUNCATE_TIES",
        "round(clipped * scale)",
        "int(clipped * scale)",
        "test_integer_ties_clipping_and_channel_identity[Q22-quantization-s16le-1-pos_odd_tie]",
        "Q22_ROUND_TIES_EVEN",
    ),
    (
        "Q22-M02_DROP_THRESHOLD_EQUALITY",
        "level >= threshold and speech_start is None",
        "level > threshold and speech_start is None",
        "test_vad_threshold_equality_is_inclusive[Q22-vad_equal-f32le-2]",
        "Q22_VAD_EQUAL_THRESHOLD",
    ),
)


@pytest.mark.parametrize("mutant", MUTANTS, ids=[row[0] for row in MUTANTS])
def test_named_mutant_is_killed_by_goal_assertion_in_isolated_source(
    tmp_path: Path, mutant: tuple[str, ...]
) -> None:
    name, original, replacement, node, goal = mutant
    repository = Path(__file__).resolve().parents[2]
    production = repository / "src" / "recoryn" / "audio" / "processing.py"
    before = production.read_bytes()
    source = before.decode("utf-8")
    assert source.count(original) == 1, "Q22_MUTANT_PATCH_INVALID"
    results = {}
    for variant in ("normal", "mutant"):
        directory = tmp_path / variant
        isolated = directory / "src"
        shutil.copytree(
            repository / "src" / "recoryn",
            isolated / "recoryn",
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        test = directory / "test_audio_case_space.py"
        shutil.copyfile(Path(__file__), test)
        config = directory / "pytest.ini"
        config.write_text(
            "[pytest]\nmarkers = property: bounded numerical contracts\n", encoding="utf-8"
        )
        target = isolated / "recoryn" / "audio" / "processing.py"
        if variant == "mutant":
            target.write_text(source.replace(original, replacement), encoding="utf-8", newline="")
        script = "\n".join(
            (
                "import pathlib,sys",
                "sys.path.insert(0,sys.argv[1])",
                "import recoryn.audio.processing as module",
                "assert pathlib.Path(module.__file__).resolve().is_relative_to(pathlib.Path(sys.argv[1]).resolve())",
                "import pytest",
                "raise SystemExit(pytest.main(['-c',sys.argv[2],sys.argv[3],'-q','-p','no:cacheprovider','--basetemp',sys.argv[4],'-W','error::ResourceWarning','--tb=short']))",
            )
        )
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("COVERAGE", "COV_CORE"))
            and key not in {"PYTHONPATH", "PYTEST_ADDOPTS"}
        }
        environment.update(PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTHONDONTWRITEBYTECODE="1")
        completed = subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                script,
                str(isolated),
                str(config),
                str(test) + "::" + node,
                str(directory / "pytest-temp"),
            ],
            cwd=directory,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        output = completed.stdout + completed.stderr
        (directory / "result.txt").write_text(output, encoding="utf-8")
        results[variant] = {
            "returncode": completed.returncode,
            "source_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "goal_node": node,
        }
        if variant == "normal":
            assert completed.returncode == 0 and "1 passed" in output, output
        else:
            assert completed.returncode == 1 and "1 failed" in output, output
            assert goal in output and "AssertionError" in output, output
            assert "ERROR collecting" not in output and "ImportError" not in output, output
    assert production.read_bytes() == before, "Q22_ORIGINAL_SOURCE_CHANGED"
    assert results["normal"]["source_sha256"] != results["mutant"]["source_sha256"]
    (tmp_path / "mutation.json").write_text(
        json.dumps(
            {"name": name, "original_sha256": hashlib.sha256(before).hexdigest(), "runs": results},
            sort_keys=True,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        "Q22_MUTATION "
        + json.dumps(
            {
                "name": name,
                "normal": "PASS",
                "mutant": "GOAL_ASSERTION_FAIL",
                "evidence": str(tmp_path / "mutation.json"),
            },
            sort_keys=True,
        )
    )
