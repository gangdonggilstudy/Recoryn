from __future__ import annotations

import hashlib
import struct
import wave
from pathlib import Path

import pytest

from recoryn.app.media import _int16, prepare_clips
from recoryn.app.recording import RecordingService
from recoryn.cli import _export
from recoryn.domain import AudioFormat, PCMBlock, ValidationError
from recoryn.storage import Library


def record(library: Library, sample_type="s16le", *, gaps=False, unknown=False):
    fmt = AudioFormat(48000, 1, sample_type)
    recorder = RecordingService(library, {"mic": fmt}, chunk_frames=480)
    recorder.start()
    for index in range(3):
        seq = index * 2 if gaps else index
        stamp = None if unknown else 1_000_000_000 + index * (1_000_000_000 if gaps else 10_000_000)
        sample = struct.pack("<f", 0.5) if sample_type == "f32le" else b"\x00\x40"
        block = PCMBlock(
            recorder.session_id,
            "mic",
            recorder.epochs["mic"],
            seq,
            fmt,
            480,
            sample * 480,
            stamp,
            1_100_000_000 + index * 1_000_000_000,
            device_frame_position=seq * 480,
            clock_quality="UNKNOWN" if unknown else "DEVICE_CORRELATED",
        )
        assert recorder.submit(block)
    recorder.stop()
    return recorder.session_id


def test_derived_clip_order_frames_and_immutable_source(tmp_path: Path) -> None:
    with Library(tmp_path / "library") as library:
        session = record(library)
        chunks = library.chunks(session)
        originals = {
            c.relative_path: hashlib.sha256(
                (library.root / c.relative_path / "audio.pcm").read_bytes()
            ).hexdigest()
            for c in chunks
        }
        snapshot, clips = prepare_clips(library, session)
        assert len(snapshot) == 64
        assert len(clips) == 1
        clip = clips[0]
        assert clip.offset_ms == 0 and clip.duration_ms == 30
        assert [r["output_frame_start"] for r in clip.source_ranges] == [0, 480, 960]
        with wave.open(str(clip.path), "rb") as audio:
            assert audio.getnframes() == 1440
            assert audio.readframes(1440) == b"\x00\x40" * 1440
        assert originals == {
            c.relative_path: hashlib.sha256(
                (library.root / c.relative_path / "audio.pcm").read_bytes()
            ).hexdigest()
            for c in chunks
        }


def test_gap_offsets_stay_on_original_timeline(tmp_path: Path) -> None:
    with Library(tmp_path / "library") as library:
        session = record(library, gaps=True)
        _, clips = prepare_clips(library, session)
        assert [clip.offset_ms for clip in clips] == [0, 1000, 2000]
        assert [clip.duration_ms for clip in clips] == [10, 10, 10]


def test_unknown_capture_clock_is_never_replaced_by_arrival(tmp_path: Path) -> None:
    with Library(tmp_path / "library") as library:
        session = record(library, unknown=True)
        _, clips = prepare_clips(library, session)
        assert len(clips) == 3
        assert all(c.offset_ms is None and c.timing_quality == "unknown" for c in clips)


def test_native_float_export_is_explicit_derived_integer_wav(tmp_path: Path) -> None:
    with Library(tmp_path / "library") as library:
        session = record(library, "f32le")
        result = _export(library, session, tmp_path / "export")
        assert result["complete"]
        path = tmp_path / "export" / result["files"][0]["file"]
        with wave.open(str(path), "rb") as audio:
            assert audio.getsampwidth() == 2
            assert audio.getnframes() == 1440
            assert struct.unpack("<h", audio.readframes(1))[0] == 16384


@pytest.mark.parametrize(
    "sample_type,payload,expected",
    [
        ("s24le", b"\x00\x00\x80", -32768),
        ("s32le", b"\x00\x00\x00\x40", 16384),
        ("f32le", struct.pack("<f", 2.0), 32767),
        ("f32le", struct.pack("<f", -2.0), -32767),
    ],
)
def test_integer_conversion_bounds(sample_type, payload, expected):
    assert struct.unpack("<h", _int16(payload, AudioFormat(48000, 1, sample_type)))[0] == expected


def test_nonfinite_float_refused():
    with pytest.raises(ValidationError, match="NONFINITE"):
        _int16(struct.pack("<f", float("nan")), AudioFormat(48000, 1, "f32le"))


def test_vad_derived_clip_keeps_absolute_source_frames_and_wav_checksum(tmp_path: Path) -> None:
    with Library(tmp_path / "library") as library:
        fmt = AudioFormat(1000, 1)
        recorder = RecordingService(library, {"mic": fmt})
        recorder.start()
        source = b"\0\0" * 400 + b"\0\x40" * 200 + b"\0\0" * 400
        assert recorder.submit(
            PCMBlock(
                recorder.session_id,
                "mic",
                recorder.epochs["mic"],
                0,
                fmt,
                1000,
                source,
                1_000_000_000,
                1_000_000_000,
                device_frame_position=0,
            )
        )
        recorder.stop()
        _, clips = prepare_clips(library, recorder.session_id, speech_only=True)
        assert len(clips) == 1
        clip = clips[0]
        assert clip.offset_ms == 300 and clip.duration_ms == 400
        assert clip.source_ranges[0]["source_chunk_frame_start"] == 300
        assert clip.source_ranges[0]["output_frame_start"] == 0
        assert clip.source_ranges[0]["capture_mono_ns"] == 1_300_000_000
        assert hashlib.sha256(clip.path.read_bytes()).hexdigest() == clip.sha256
        with wave.open(str(clip.path), "rb") as audio:
            assert audio.getnframes() == 400
            assert audio.readframes(400) == source[600:1400]


def test_forward_clock_jump_cannot_be_compressed_into_one_correlated_clip(tmp_path: Path) -> None:
    with Library(tmp_path / "library") as library:
        fmt = AudioFormat(48000, 1)
        recorder = RecordingService(library, {"mic": fmt})
        recorder.start()
        for seq, stamp in enumerate((1_000_000_000, 1_010_000_000, 61_020_000_000)):
            assert recorder.submit(
                PCMBlock(
                    recorder.session_id,
                    "mic",
                    recorder.epochs["mic"],
                    seq,
                    fmt,
                    480,
                    b"\0\x40" * 480,
                    stamp,
                    stamp,
                    device_frame_position=seq * 480,
                )
            )
        recorder.stop()
        _, clips = prepare_clips(library, recorder.session_id)
        assert [clip.duration_ms for clip in clips] == [20, 10]
        assert clips[0].offset_ms == 0
        assert clips[1].offset_ms is None and clips[1].timing_quality == "unknown"
        assert sum(item["frame_count"] for clip in clips for item in clip.source_ranges) == 1440
