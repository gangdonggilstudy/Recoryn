"""Independent value and transition boundary oracles."""

import json
from dataclasses import FrozenInstanceError, replace
from itertools import product
from typing import Any

import pytest

from recoryn.domain import (
    AudioFormat,
    PCMBlock,
    Session,
    SessionState,
    StateConflict,
    ValidationError,
    transition_session,
)


def block(**changes: Any) -> PCMBlock:
    values: dict[str, Any] = dict(
        session_id="session-1",
        track_id="mic",
        epoch_id="epoch_1",
        sequence=0,
        format=AudioFormat(48_000, 2),
        frame_count=2,
        payload=b"\x01\x00\x02\x00" * 2,
        capture_mono_ns=1_000_000_000,
        arrival_mono_ns=1_000_000_050,
        device_frame_position=48_000,
        flags=("SILENT",),
    )
    values.update(changes)
    return PCMBlock(**values)


@pytest.mark.parametrize(
    ("sample_type", "channels", "expected"),
    [
        ("s16le", 1, 2),
        ("s16le", 2, 4),
        ("s24le", 2, 6),
        ("s32le", 2, 8),
        ("f32le", 1, 4),
    ],
)
def test_format_frame_bytes_and_roundtrip(sample_type: str, channels: int, expected: int) -> None:
    value = AudioFormat(44_100, channels, sample_type)
    assert value.frame_bytes == expected
    assert AudioFormat.from_dict(json.loads(json.dumps(value.to_dict()))) == value
    with pytest.raises(FrozenInstanceError):
        value.channels = 99  # type: ignore[misc]


@pytest.mark.parametrize(
    "changes",
    [
        {"sample_rate": True},
        {"sample_rate": 0},
        {"sample_rate": -1},
        {"sample_rate": 48_000.0},
        {"sample_rate": "48000"},
        {"sample_rate": 768_001},
        {"channels": False},
        {"channels": 0},
        {"channels": 65},
        {"sample_type": "float"},
        {"sample_type": []},
    ],
)
def test_audio_format_rejects_invalid_values(changes: dict[str, Any]) -> None:
    values: dict[str, Any] = {"sample_rate": 48_000, "channels": 2}
    values.update(changes)
    with pytest.raises(ValidationError):
        AudioFormat(**values)


@pytest.mark.parametrize(
    "data",
    [
        None,
        [],
        {},
        {"sample_rate": 48_000},
        {"schema_version": True, "sample_rate": 48_000, "channels": 2},
        {"schema_version": 2, "sample_rate": 48_000, "channels": 2},
        {1: "bad"},
    ],
)
def test_format_corrupt_metadata(data: Any) -> None:
    with pytest.raises(ValidationError):
        AudioFormat.from_dict(data)


def test_pcm_json_roundtrip_and_no_mutable_references() -> None:
    value = block()
    metadata = json.loads(json.dumps(value.to_metadata()))
    assert "payload" not in metadata
    restored = PCMBlock.from_metadata(metadata, value.payload)
    assert restored == value
    metadata["flags"].append("NEW_FLAG")
    metadata["format"]["channels"] = 1
    assert restored.flags == ("SILENT",)
    assert restored.format.channels == 2
    with pytest.raises(FrozenInstanceError):
        restored.sequence = 5  # type: ignore[misc]


@pytest.mark.parametrize(
    "sample_type, payload",
    [
        ("s16le", b"\x00" * 8),
        ("s24le", b"\x00" * 12),
        ("s32le", b"\x00" * 16),
        ("f32le", b"\x00" * 16),
    ],
)
def test_pcm_exact_format_lengths(sample_type: str, payload: bytes) -> None:
    assert block(format=AudioFormat(48_000, 2, sample_type), payload=payload).payload == payload
    with pytest.raises(ValidationError):
        block(format=AudioFormat(48_000, 2, sample_type), payload=payload[:-1])


@pytest.mark.parametrize(
    "field",
    [
        "sequence",
        "frame_count",
        "capture_mono_ns",
        "arrival_mono_ns",
        "device_frame_position",
        "fragment_index",
        "fragment_count",
    ],
)
@pytest.mark.parametrize("invalid", [True, False, -1, 1.0, "1", 2**63])
def test_pcm_numeric_boundaries(field: str, invalid: Any) -> None:
    with pytest.raises(ValidationError):
        block(**{field: invalid})


@pytest.mark.parametrize(
    "changes",
    [
        {"session_id": "../escape"},
        {"track_id": "a/b"},
        {"epoch_id": "a\\b"},
        {"track_id": "마이크"},
        {"track_id": "CON"},
        {"track_id": "lpt1"},
        {"track_id": ""},
        {"session_id": "a" * 129},
        {"format": {}},
        {"payload": bytearray(8)},
        {"payload": b""},
        {"frame_count": 0},
        {"flags": ["SILENT"]},
        {"flags": ("SILENT", "SILENT")},
        {"flags": (True,)},
        {"clock_quality": ""},
        {"fragment_index": 1, "fragment_count": 1},
        {"fragment_count": 0},
    ],
)
def test_pcm_invalid_shape(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        block(**changes)


def test_pcm_nullable_clock_and_valid_fragment() -> None:
    value = block(
        capture_mono_ns=None,
        device_frame_position=None,
        clock_quality="UNKNOWN",
        fragment_index=1,
        fragment_count=2,
    )
    assert PCMBlock.from_metadata(value.to_metadata(), value.payload) == value


@pytest.mark.parametrize(
    "changes",
    [
        {"schema_version": 99},
        {"schema_version": False},
        {"flags": "SILENT"},
        {"format": []},
        {"frame_count": True},
    ],
)
def test_pcm_corrupt_metadata(changes: dict[str, Any]) -> None:
    value = block()
    metadata = value.to_metadata()
    metadata.update(changes)
    with pytest.raises(ValidationError):
        PCMBlock.from_metadata(metadata, value.payload)


def test_pcm_missing_metadata() -> None:
    value = block()
    metadata = value.to_metadata()
    del metadata["arrival_mono_ns"]
    with pytest.raises(ValidationError):
        PCMBlock.from_metadata(metadata, value.payload)


# This is an explicit contract oracle, not the implementation transition map.
LEGAL_EDGES = {
    ("CREATED", "RECORDING"),
    ("CREATED", "FINALIZING"),
    ("RECORDING", "PAUSED"),
    ("RECORDING", "FINALIZING"),
    ("RECORDING", "INTERRUPTED"),
    ("PAUSED", "RECORDING"),
    ("PAUSED", "FINALIZING"),
    ("PAUSED", "INTERRUPTED"),
    ("FINALIZING", "FINALIZED"),
    ("FINALIZING", "INTERRUPTED"),
    ("INTERRUPTED", "PAUSED"),
    ("INTERRUPTED", "FINALIZING"),
}


@pytest.mark.parametrize("source,target", list(product(SessionState, repeat=2)))
def test_session_transition_matrix(source: SessionState, target: SessionState) -> None:
    original = Session("session-1", source, 4)
    if (source.value, target.value) in LEGAL_EDGES:
        changed = transition_session(original, target, 4)
        assert changed.state == target and changed.state_version == 5
        assert original.state == source and original.state_version == 4
    else:
        with pytest.raises(StateConflict):
            transition_session(original, target, 4)


def test_session_version_and_type_guards() -> None:
    value = Session("session-1")
    with pytest.raises(StateConflict):
        transition_session(value, SessionState.RECORDING, 1)
    with pytest.raises(ValidationError):
        transition_session(value, SessionState.RECORDING, True)
    with pytest.raises(ValidationError):
        transition_session(value, "RECORDING", 0)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        replace(value, state_version=True)
    with pytest.raises(ValidationError):
        Session("bad/id")
    with pytest.raises(ValidationError):
        replace(value, state="CREATED")  # type: ignore[arg-type]
