"""Immutable recording values and pure state transitions (no I/O)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

__all__ = [
    "AudioFormat",
    "MAX_PCM_BLOCK_BYTES",
    "PCMBlock",
    "Session",
    "SessionState",
    "StateConflict",
    "ValidationError",
    "transition_session",
]

MAX_PCM_BLOCK_BYTES = 16 * 1024 * 1024


class ValidationError(ValueError):
    """A value cannot satisfy the recording contract."""


class StateConflict(ValueError):
    """The requested transition conflicts with the current durable state."""


def _integer(value: object, name: str, minimum: int = 0, maximum: int = 2**63 - 1) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValidationError(f"{name} must be an integer in [{minimum}, {maximum}]")
    return value


def _identifier(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value) is None
    ):
        raise ValidationError(f"{name} must be a safe ASCII identifier")
    if value.upper() in {"CON", "PRN", "AUX", "NUL"} or re.fullmatch(
        r"(?:COM|LPT)[1-9]", value.upper()
    ):
        raise ValidationError(f"{name} is a reserved Windows filename")
    return value


def _mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(k, str) for k in value):
        raise ValidationError("metadata must be a mapping with string keys")
    return value


def _version(data: Mapping[str, Any]) -> None:
    if _integer(data.get("schema_version", 1), "schema_version", 1) != 1:
        raise ValidationError("unsupported schema_version")


@dataclass(frozen=True, slots=True)
class AudioFormat:
    sample_rate: int
    channels: int
    sample_type: str = "s16le"

    def __post_init__(self) -> None:
        _integer(self.sample_rate, "sample_rate", 1, 768_000)
        _integer(self.channels, "channels", 1, 64)
        if not isinstance(self.sample_type, str) or self.sample_type not in {
            "s16le",
            "s24le",
            "s32le",
            "f32le",
        }:
            raise ValidationError("unsupported sample_type")

    @property
    def frame_bytes(self) -> int:
        return self.channels * {"s16le": 2, "s24le": 3, "s32le": 4, "f32le": 4}[self.sample_type]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "sample_type": self.sample_type,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> AudioFormat:
        data = _mapping(data)
        _version(data)
        try:
            return cls(data["sample_rate"], data["channels"], data.get("sample_type", "s16le"))
        except KeyError as exc:
            raise ValidationError(f"missing audio format field: {exc.args[0]}") from exc


@dataclass(frozen=True, slots=True)
class PCMBlock:
    session_id: str
    track_id: str
    epoch_id: str
    sequence: int
    format: AudioFormat
    frame_count: int
    payload: bytes
    capture_mono_ns: int | None
    arrival_mono_ns: int
    device_frame_position: int | None = None
    clock_quality: str = "DEVICE_CORRELATED"
    fragment_index: int = 0
    fragment_count: int = 1
    flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("session_id", "track_id", "epoch_id"):
            _identifier(getattr(self, name), name)
        _integer(self.sequence, "sequence")
        if not isinstance(self.format, AudioFormat):
            raise ValidationError("format must be AudioFormat")
        _integer(self.frame_count, "frame_count", 1)
        if (
            type(self.payload) is not bytes
            or len(self.payload) != self.frame_count * self.format.frame_bytes
        ):
            raise ValidationError("payload bytes must match frame_count * frame_bytes")
        for name in ("capture_mono_ns", "device_frame_position"):
            value = getattr(self, name)
            if value is not None:
                _integer(value, name)
        _integer(self.arrival_mono_ns, "arrival_mono_ns")
        _integer(self.fragment_count, "fragment_count", 1)
        _integer(self.fragment_index, "fragment_index", 0, self.fragment_count - 1)
        _identifier(self.clock_quality, "clock_quality")
        if type(self.flags) is not tuple:
            raise ValidationError("flags must be an immutable tuple")
        for flag in self.flags:
            _identifier(flag, "flag")
        if len(set(self.flags)) != len(self.flags):
            raise ValidationError("flags must be unique")

    def to_metadata(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "session_id": self.session_id,
            "track_id": self.track_id,
            "epoch_id": self.epoch_id,
            "sequence": self.sequence,
            "format": self.format.to_dict(),
            "frame_count": self.frame_count,
            "capture_mono_ns": self.capture_mono_ns,
            "arrival_mono_ns": self.arrival_mono_ns,
            "device_frame_position": self.device_frame_position,
            "clock_quality": self.clock_quality,
            "fragment_index": self.fragment_index,
            "fragment_count": self.fragment_count,
            "flags": list(self.flags),
        }

    @classmethod
    def from_metadata(cls, metadata: Mapping[str, Any], payload: bytes) -> PCMBlock:
        data = _mapping(metadata)
        _version(data)
        flags = data.get("flags", [])
        if not isinstance(flags, (list, tuple)):
            raise ValidationError("flags must be a sequence of strings")
        try:
            return cls(
                session_id=data["session_id"],
                track_id=data["track_id"],
                epoch_id=data["epoch_id"],
                sequence=data["sequence"],
                format=AudioFormat.from_dict(data["format"]),
                frame_count=data["frame_count"],
                payload=payload,
                capture_mono_ns=data["capture_mono_ns"],
                arrival_mono_ns=data["arrival_mono_ns"],
                device_frame_position=data.get("device_frame_position"),
                clock_quality=data.get("clock_quality", "DEVICE_CORRELATED"),
                fragment_index=data.get("fragment_index", 0),
                fragment_count=data.get("fragment_count", 1),
                flags=tuple(flags),
            )
        except KeyError as exc:
            raise ValidationError(f"missing PCM metadata field: {exc.args[0]}") from exc


class SessionState(StrEnum):
    CREATED = "CREATED"
    RECORDING = "RECORDING"
    PAUSED = "PAUSED"
    FINALIZING = "FINALIZING"
    FINALIZED = "FINALIZED"
    INTERRUPTED = "INTERRUPTED"


@dataclass(frozen=True, slots=True)
class Session:
    session_id: str
    state: SessionState = SessionState.CREATED
    state_version: int = 0

    def __post_init__(self) -> None:
        _identifier(self.session_id, "session_id")
        if not isinstance(self.state, SessionState):
            raise ValidationError("state must be SessionState")
        _integer(self.state_version, "state_version")


_TRANSITIONS = {
    SessionState.CREATED: frozenset({SessionState.RECORDING, SessionState.FINALIZING}),
    SessionState.RECORDING: frozenset(
        {SessionState.PAUSED, SessionState.FINALIZING, SessionState.INTERRUPTED}
    ),
    SessionState.PAUSED: frozenset(
        {SessionState.RECORDING, SessionState.FINALIZING, SessionState.INTERRUPTED}
    ),
    SessionState.FINALIZING: frozenset({SessionState.FINALIZED, SessionState.INTERRUPTED}),
    SessionState.FINALIZED: frozenset(),
    SessionState.INTERRUPTED: frozenset({SessionState.PAUSED, SessionState.FINALIZING}),
}


def transition_session(session: Session, target: SessionState, expected_version: int) -> Session:
    if not isinstance(session, Session) or not isinstance(target, SessionState):
        raise ValidationError("transition requires Session and SessionState")
    _integer(expected_version, "expected_version")
    if session.state_version != expected_version or target not in _TRANSITIONS[session.state]:
        raise StateConflict(
            f"cannot transition {session.state} to {target} at version {expected_version}"
        )
    return Session(session.session_id, target, session.state_version + 1)
