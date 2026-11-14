"""Independent small sample/clock oracles; no real device or model input."""

from dataclasses import replace
from struct import pack

import pytest

from recoryn.audio import (
    FrameRegion,
    align_blocks,
    decode_pcm,
    downmix_mono,
    encode_pcm,
    energy_vad,
    estimate_drift,
    measure_level,
    resample_linear,
)
from recoryn.domain import AudioFormat, PCMBlock, ValidationError

pytestmark = pytest.mark.unit


def clock_block(index: int, *, track: str = "mic", epoch: str = "epoch") -> PCMBlock:
    return PCMBlock(
        "session",
        track,
        epoch,
        index,
        AudioFormat(48_000, 1),
        480,
        bytes(960),
        1_000_000_000 + index * 10_000_000,
        1_001_000_000 + index * 10_000_000,
        index * 480,
    )


@pytest.mark.parametrize("kind,width", [("s16le", 2), ("s24le", 3), ("s32le", 4)])
def test_integer_decode_and_encode_extremes(kind: str, width: int) -> None:
    scale = 1 << (width * 8 - 1)
    source = b"".join(x.to_bytes(width, "little", signed=True) for x in (-scale, -1, 0, scale - 1))
    format = AudioFormat(44_100, 2, kind)
    frames = decode_pcm(source, format)
    assert frames == ((-1.0, -1 / scale), (0.0, (scale - 1) / scale))
    assert encode_pcm(frames, format) == source
    assert encode_pcm(((-2.0, 2.0),), format) == source[:width] + source[-width:]


def test_float_samples_are_preserved_and_nonfinite_is_rejected() -> None:
    format = AudioFormat(48_000, 2, "f32le")
    payload = pack("<ffff", -1.5, 0.5, 0, 1.25)
    assert decode_pcm(payload, format) == ((-1.5, 0.5), (0, 1.25))
    assert encode_pcm(decode_pcm(payload, format), format) == payload
    for value in (float("nan"), float("inf")):
        with pytest.raises(ValidationError):
            decode_pcm(pack("<f", value), AudioFormat(1, 1, "f32le"))
    with pytest.raises(ValidationError):
        encode_pcm(((1e100,),), AudioFormat(1, 1, "f32le"))


def test_invalid_pcm_shape_and_empty_data() -> None:
    format = AudioFormat(48_000, 2)
    assert decode_pcm(b"", format) == ()
    assert encode_pcm((), format) == b""
    with pytest.raises(ValidationError):
        decode_pcm(b"\0", format)
    with pytest.raises(ValidationError):
        decode_pcm(bytearray(4), format)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        encode_pcm(((0.0,),), format)


def test_downmix_hand_oracle_and_level() -> None:
    assert downmix_mono(((1, -1), (0.5, 0.5))) == (0, 0.5)
    assert downmix_mono(((1, 0),), weights=(3, 1)) == (0.75,)
    assert downmix_mono(()) == ()
    silent = measure_level(())
    assert silent.peak == silent.rms == 0 and silent.rms_dbfs is None
    level = measure_level((1, -1, 0, 0))
    assert level.peak == 1 and level.rms == pytest.approx(2**-0.5)
    assert level.clipped_samples == 2 and level.peak_dbfs == 0
    assert measure_level((1e300, -1e300)).rms == 1e300


@pytest.mark.parametrize("weights", [(0, 0), (-1, 1), (1,), (float("inf"), 1), (1e308, 1e308)])
def test_downmix_rejects_invalid_weights(weights: tuple[float, ...]) -> None:
    with pytest.raises(ValidationError):
        downmix_mono(((1, 0),), weights=weights)


@pytest.mark.parametrize("samples", [(float("nan"),), (True,), (10**500,)])
def test_sample_validation(samples: tuple[float, ...]) -> None:
    with pytest.raises(ValidationError):
        measure_level(samples)


def test_downmix_rejects_ragged_and_empty_channel_rows() -> None:
    for frames in (((),), ((1,), (1, 2))):
        with pytest.raises(ValidationError):
            downmix_mono(frames)


def test_linear_interpolation_has_explicit_length_and_endpoint_rule() -> None:
    assert resample_linear((0, 1), 2, 4) == (0, 0.5, 1, 1)
    assert resample_linear((0, 1, 2, 3), 4, 2) == (0, 2)
    assert resample_linear((0, 1, 2), 3, 2) == (0, 1.5)
    assert len(resample_linear((0,) * 441, 44_100, 16_000)) == 160
    assert resample_linear((), 48_000, 16_000) == ()
    assert resample_linear((0.25,), 1, 1) == (0.25,)
    for rate in (0, -1, True):
        with pytest.raises(ValidationError):
            resample_linear((0,), rate, 16_000)


def test_energy_vad_preserves_source_frames_and_detects_opposite_phase() -> None:
    format = AudioFormat(1000, 2)
    frames = [(0.0, 0.0)] * 20 + [(0.5, -0.5)] * 40 + [(0, 0)] * 40
    payload = encode_pcm(frames, format)
    block = PCMBlock("s", "t", "e", 5, format, 100, payload, 0, 0, 100)
    assert energy_vad(block, window_ms=10, padding_ms=0) == (FrameRegion(20, 60),)
    assert energy_vad(block, window_ms=10, padding_ms=10) == (FrameRegion(10, 70),)
    assert block.payload == payload and block.device_frame_position == 100
    assert energy_vad(replace(block, payload=bytes(len(payload)))) == ()
    assert energy_vad(block, min_speech_ms=1000) == ()


def test_vad_padding_merges_only_regions_inside_the_same_block() -> None:
    format = AudioFormat(1000, 1)
    frames = [(0.5,)] * 20 + [(0.0,)] * 20 + [(0.5,)] * 20
    block = PCMBlock("s", "t", "e", 0, format, 60, encode_pcm(frames, format), 0, 0, 0)
    assert energy_vad(block, window_ms=10, min_speech_ms=10, padding_ms=10) == (FrameRegion(0, 60),)
    for options in (
        {"threshold_dbfs": float("nan")},
        {"threshold_dbfs": 1},
        {"window_ms": 0},
        {"padding_ms": -1},
        {"min_speech_ms": True},
    ):
        with pytest.raises(ValidationError):
            energy_vad(block, **options)


def test_clock_fit_uses_correlated_samples_not_arrival_and_preserves_epoch() -> None:
    blocks = [replace(clock_block(i), arrival_mono_ns=50_000_000_000) for i in range(4)]
    fit = estimate_drift(blocks)
    assert fit.drift_ppm == pytest.approx(0, abs=1e-8)
    assert fit.map_frame(48_000) == 2_000_000_000
    assert fit.residual_ns == 0
    assert estimate_drift(blocks[:1]).sample_count == 1
    assert estimate_drift(blocks[:1]).drift_ppm == pytest.approx(0)
    for altered in (
        replace(blocks[1], epoch_id="other"),
        replace(blocks[1], capture_mono_ns=None),
        replace(blocks[1], sequence=99),
        replace(blocks[1], flags=("TIMESTAMP_ERROR",)),
    ):
        with pytest.raises(ValidationError):
            estimate_drift([blocks[0], altered])
    with pytest.raises(ValidationError):
        estimate_drift([])
    with pytest.raises(ValidationError):
        fit.map_frame(-1)


def test_drift_sign_and_numerical_anchor() -> None:
    # 48,000 nominal frames advance 0.9999s: effective source is ~100.01ppm faster.
    first = replace(
        clock_block(0),
        frame_count=48_000,
        payload=bytes(96_000),
        capture_mono_ns=8_000_000_000_000_000,
    )
    second = replace(
        first, sequence=1, device_frame_position=48_000, capture_mono_ns=8_000_000_999_900_000
    )
    fit = estimate_drift([first, second])
    assert fit.drift_ppm == pytest.approx(100.010001, abs=0.000001)
    assert fit.map_frame(48_000) == second.capture_mono_ns


@pytest.mark.parametrize("jump_ns", [60_000_000_000, -15_000_000])
def test_clock_jump_is_not_a_drift_fit_and_exposes_uncertain_observed_gap(jump_ns: int) -> None:
    blocks = [
        clock_block(0),
        clock_block(1),
        replace(clock_block(2), capture_mono_ns=1_020_000_000 + jump_ns),
        replace(clock_block(3), capture_mono_ns=1_030_000_000 + jump_ns),
    ]
    before = tuple(block.to_metadata() for block in blocks)
    with pytest.raises(ValidationError):
        estimate_drift(blocks)
    spans = align_blocks(blocks, origin_ns=1_000_000_000)
    assert spans[0].start_ns == 0 and spans[1].start_ns == 10_000_000
    assert spans[2].segment != spans[1].segment
    assert spans[2].start_ns == 20_000_000 + jump_ns
    assert spans[2].end_ns == 30_000_000 + jump_ns
    assert spans[2].quality == spans[3].quality == "UNCERTAIN_CLOCK"
    assert spans[2].drift_ppm is None
    assert all(
        span.start_ns is not None
        and span.end_ns is not None
        and span.end_ns - span.start_ns == 10_000_000
        for span in spans
    )
    assert tuple(block.to_metadata() for block in blocks) == before


def test_smooth_clock_excursion_with_large_fit_residual_stays_uncertain() -> None:
    # Each adjacent step is within 1%, yet no single affine clock fits this run.
    blocks = [
        replace(
            clock_block(index),
            capture_mono_ns=1_000_000_000 + index * 10_000_000 + min(index, 400 - index) * 80_000,
        )
        for index in range(401)
    ]
    with pytest.raises(ValidationError):
        estimate_drift(blocks)
    spans = align_blocks(blocks)
    assert all(span.quality == "UNCERTAIN_CLOCK" and span.drift_ppm is None for span in spans)
    assert all(
        span.start_ns is not None
        and span.end_ns is not None
        and span.end_ns - span.start_ns == 10_000_000
        for span in spans
    )


def test_implausible_clock_slope_is_rejected_even_for_short_packets() -> None:
    first = replace(clock_block(0), frame_count=1, payload=bytes(2))
    second = replace(first, sequence=1, device_frame_position=1, capture_mono_ns=1_000_021_500)
    # 21.5us vs nominal 20.833us fits the rounding floor but exceeds the slope gate.
    with pytest.raises(ValidationError):
        estimate_drift([first, second])
    assert {span.quality for span in align_blocks([first, second])} == {"UNCERTAIN_CLOCK"}


@pytest.mark.parametrize("step_ns", [9_900_000, 10_100_000])
def test_exact_period_policy_boundary_is_not_rejected_by_float_rounding(step_ns: int) -> None:
    fit = estimate_drift(
        [clock_block(0), replace(clock_block(1), capture_mono_ns=1_000_000_000 + step_ns)]
    )
    assert fit.map_frame(480) == 1_000_000_000 + step_ns


def test_jump_taint_survives_invalid_packet_but_resets_at_new_epoch() -> None:
    blocks = [
        clock_block(0),
        replace(clock_block(1), capture_mono_ns=61_010_000_000),
        replace(clock_block(2), capture_mono_ns=None),
        replace(clock_block(3), capture_mono_ns=61_030_000_000),
        clock_block(0, epoch="fresh"),
    ]
    spans = align_blocks(blocks)
    assert [span.quality for span in spans] == [
        "DEVICE_CORRELATED",
        "UNCERTAIN_CLOCK",
        "UNKNOWN",
        "UNCERTAIN_CLOCK",
        "DEVICE_CORRELATED",
    ]
    assert spans[2].start_ns is None and spans[2].end_ns is None


def test_alignment_keeps_gaps_and_unknown_time_and_separate_tracks() -> None:
    blocks = [
        clock_block(0),
        clock_block(1),
        clock_block(3),
        replace(clock_block(4), capture_mono_ns=None, flags=("TIMESTAMP_ERROR",)),
        clock_block(5),
        clock_block(0, epoch="new"),
        replace(clock_block(0, track="system"), capture_mono_ns=1_005_000_000),
    ]
    spans = align_blocks(blocks)
    assert [s.segment for s in spans[:6]] == [0, 0, 1, 2, 3, 4]
    assert spans[2].start_ns == 30_000_000  # Missing 10ms remains missing.
    assert spans[3].start_ns is None and spans[3].end_ns is None
    assert spans[3].quality == "UNKNOWN"
    assert spans[-1].start_ns == 5_000_000
    assert all(s.source_start_frame == 0 and s.source_end_frame == 480 for s in spans)
    assert spans[0].epoch_id == "epoch" and spans[5].epoch_id == "new"
    assert align_blocks([]) == ()
    assert align_blocks([replace(clock_block(0), capture_mono_ns=None)])[0].start_ns is None
    assert align_blocks([clock_block(0)], origin_ns=1_000_000_000)[0].start_ns == 0


def test_fragment_continuity_and_discontinuity_flags_split_alignment() -> None:
    first = replace(clock_block(0), fragment_index=0, fragment_count=2)
    second = replace(clock_block(1), sequence=0, fragment_index=1, fragment_count=2)
    assert len({span.segment for span in align_blocks([first, second])}) == 1
    flagged = replace(clock_block(1), flags=("DATA_DISCONTINUITY",))
    assert len({span.segment for span in align_blocks([clock_block(0), flagged])}) == 2
    with pytest.raises(ValidationError):
        align_blocks([clock_block(0), replace(clock_block(1), session_id="other")])
    with pytest.raises(ValidationError):
        align_blocks([], origin_ns=-1)


def test_empty_downmix_weights_and_invalid_processing_types() -> None:
    assert downmix_mono((), weights=(1, 1)) == ()
    with pytest.raises(ValidationError):
        downmix_mono((), weights=(0, 0))
    with pytest.raises(ValidationError):
        encode_pcm(((0.0,),), "not-a-format")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        energy_vad(None)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        energy_vad(clock_block(0), threshold_dbfs=True)
    with pytest.raises(ValidationError):
        align_blocks([None])  # type: ignore[list-item]
