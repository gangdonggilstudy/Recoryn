"""L01 D7 PCM playback. Case space: docs/testing/l04-media-backend-cases.md (R, O, D).

Oracles are hand-computed or the independent standard-library helpers in
``recoryn.audio`` (decode, equal-weight mono, ties-to-even 16-bit encode), which
share no code with the fast production mix.
"""

from __future__ import annotations

import hashlib
import random
import struct
import sys
import types
import wave
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from recoryn.audio import decode_pcm, downmix_mono, encode_pcm
from recoryn.domain import AudioFormat, StateConflict
from recoryn.ui.pcm_playback import MAX_CLIP_BYTES, PlaybackPcm, SinkPlayback, prepare_playback


def write_wav(path: Path, rate: int, channels: int, data: bytes, width: int = 2) -> str:
    with wave.open(str(path), "wb") as clip:
        clip.setnchannels(channels)
        clip.setsampwidth(width)
        clip.setframerate(rate)
        clip.writeframes(data)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def samples(count: int, seed: int) -> bytes:
    generator = random.Random(seed)
    values = [generator.randint(-32768, 32767) for _ in range(count)]
    values[: min(2, count)] = [-32768, 32767][: min(2, count)]  # full-scale ends included
    return struct.pack(f"<{count}h", *values)


@pytest.mark.parametrize("rate", [8000, 44100, 48000])
@pytest.mark.parametrize("channels", [1, 2, 3, 6, 12, 16, 64])
def test_exact_frame_cut_and_independent_mono_oracle(
    tmp_path: Path, channels: int, rate: int
) -> None:
    frames = rate * 40 // 1000
    raw = samples(frames * channels, seed=channels * 100_003 + rate)
    path = tmp_path / "clip.wav"
    digest = write_wav(path, rate, channels, raw)
    before = path.read_bytes()
    pcm = prepare_playback(path, digest, 20)
    start = 20 * rate // 1000
    tail = raw[start * channels * 2 :]
    assert path.read_bytes() == before  # the verified clip is never rewritten
    if channels <= 2:
        assert pcm == PlaybackPcm(rate, channels, start, tail)
        return
    # Exact oracle: per-frame Fraction mean, rounded half to even by round().
    values = struct.unpack(f"<{len(tail) // 2}h", tail)
    totals = [sum(values[i : i + channels]) for i in range(0, len(values), channels)]
    exact = [round(Fraction(total, channels)) for total in totals]
    assert pcm == PlaybackPcm(rate, 1, start, struct.pack(f"<{len(exact)}h", *exact))
    # The float helpers agree except on exact .5 ties, where 1/6- or 1/12-style
    # weights are inexact; there they may differ by one LSB, never more.
    helper = struct.unpack(
        f"<{len(exact)}h",
        encode_pcm(
            tuple(
                (value,) for value in downmix_mono(decode_pcm(tail, AudioFormat(rate, channels)))
            ),
            AudioFormat(rate, 1),
        ),
    )
    for total, ours, theirs in zip(totals, exact, helper, strict=True):
        tie = Fraction(total, channels).denominator == 2
        assert ours == theirs or (tie and abs(ours - theirs) == 1)


@pytest.mark.parametrize(
    ("position_ms", "start_frame"),
    [
        (0, 0),
        (1, 44),  # 44.1 frames, floored
        (10, 441),
        (333, 14685),
        (999, 44055),
        (1000, 44100),  # exactly the end: nothing left to play
        (1500, 44100),  # beyond the end is clamped, never an error
        (-5, 0),  # a negative offset is clamped to the first frame
    ],
)
def test_position_partitions(tmp_path: Path, position_ms: int, start_frame: int) -> None:
    raw = samples(44100 * 2, seed=7)
    path = tmp_path / "clip.wav"
    pcm = prepare_playback(path, write_wav(path, 44100, 2, raw), position_ms)
    assert (pcm.start_frame, pcm.payload) == (start_frame, raw[start_frame * 4 :])


@pytest.mark.parametrize(
    ("frame", "expected"),
    [
        ((1, 2, 4), 2),
        ((-1, -2, -4), -2),
        ((1, 1, 0, 0), 0),  # 0.5 rounds half to even
        ((3, 1, 0, 0), 1),
        ((1, 2, 0, 0), 1),  # 0.75
        ((-32768,) * 64, -32768),
        ((32767,) * 64, 32767),
    ],
)
def test_mono_mean_rounding_by_hand(tmp_path: Path, frame: tuple[int, ...], expected: int) -> None:
    path = tmp_path / "clip.wav"
    digest = write_wav(path, 16000, len(frame), struct.pack(f"<{len(frame)}h", *frame))
    pcm = prepare_playback(path, digest, 0)
    assert (pcm.channels, pcm.payload) == (1, struct.pack("<h", expected))


def _float_wav(path: Path) -> str:
    data = struct.pack("<4f", 0.0, 0.25, -0.25, 0.5)
    header = struct.pack("<4sI4s", b"RIFF", 36 + len(data), b"WAVE")
    header += struct.pack("<4sIHHIIHH", b"fmt ", 16, 3, 1, 16000, 64000, 4, 32)
    path.write_bytes(header + struct.pack("<4sI", b"data", len(data)) + data)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _truncated(path: Path) -> str:
    write_wav(path, 16000, 1, bytes(200))
    path.write_bytes(path.read_bytes()[:-10])  # the header still declares 100 frames
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _oversized(path: Path) -> str:
    write_wav(path, 48000, 2, bytes(MAX_CLIP_BYTES))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bad_hash(path: Path) -> str:
    actual = write_wav(path, 16000, 1, bytes(64))
    return "0" * 64 if actual != "0" * 64 else "1" * 64


REJECTED = {
    "hash_mismatch": _bad_hash,
    "over_limit": _oversized,
    "8_bit": lambda path: write_wav(path, 16000, 1, bytes(32), width=1),
    "24_bit": lambda path: write_wav(path, 16000, 1, bytes(48), width=3),
    "32_bit": lambda path: write_wav(path, 16000, 1, bytes(64), width=4),
    "ieee_float": _float_wav,
    "not_riff": lambda path: (
        path.write_bytes(b"not a wave file"),
        hashlib.sha256(b"not a wave file").hexdigest(),
    )[1],
    "short_data": _truncated,
    "65_channels": lambda path: write_wav(path, 16000, 65, bytes(65 * 2 * 4)),
}


@pytest.mark.parametrize("case", sorted(REJECTED))
def test_unverifiable_or_unsupported_clip_never_plays(tmp_path: Path, case: str) -> None:
    path = tmp_path / "clip.wav"
    digest = REJECTED[case](path)
    with pytest.raises(StateConflict, match="PLAYBACK_SOURCE_INVALID"):
        prepare_playback(path, digest, 0)


# --- Output O: a memory fake replaces PySide6.QtMultimedia; QtCore stays real. ---


class _Name:
    def __init__(self, name: str) -> None:
        self.name = name


class _Signal:
    def __init__(self) -> None:
        self.slots: list[Any] = []

    def connect(self, slot: Any) -> None:
        self.slots.append(slot)

    def emit(self) -> None:
        for slot in list(self.slots):
            slot()


class _Format:
    class SampleFormat:
        Int16 = "Int16"

    def __init__(self) -> None:
        self.values: dict[str, Any] = {}

    def setSampleRate(self, value: int) -> None:
        self.values["rate"] = value

    def setChannelCount(self, value: int) -> None:
        self.values["channels"] = value

    def setSampleFormat(self, value: str) -> None:
        self.values["format"] = value


class _Sink:
    fail_on_start = False

    def __init__(self, device: Any, audio_format: _Format, parent: Any) -> None:
        self.format = audio_format.values
        self.stateChanged = _Signal()
        self._state = _Name("StoppedState")
        self._error = _Name("NoError")
        self.processed = 0
        self.volume: float | None = None
        self.played = b""
        self.stops = 0
        self.deleted = False

    def setVolume(self, value: float) -> None:
        self.volume = value

    def start(self, buffer: Any) -> None:
        self.played = bytes(buffer.data())
        self._state = _Name("ActiveState")
        if self.fail_on_start:
            self._error = _Name("OpenError")

    def stop(self) -> None:
        self.stops += 1
        self._state = _Name("StoppedState")
        self.stateChanged.emit()

    def state(self) -> _Name:
        return self._state

    def error(self) -> _Name:
        return self._error

    def processedUSecs(self) -> int:
        return self.processed

    def deleteLater(self) -> None:
        self.deleted = True

    def go_idle(self) -> None:
        self._state = _Name("IdleState")
        self.stateChanged.emit()

    def stopped_by_qt(self, error: str) -> None:
        # e.g. the device vanished after a successful start (L04-D04)
        self._state = _Name("StoppedState")
        self._error = _Name(error)
        self.stateChanged.emit()


@pytest.fixture
def fake_qt(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    state = SimpleNamespace(null=False, supported=True, sinks=[], fail=False)

    class Device:
        def isNull(self) -> bool:
            return bool(state.null)

        def isFormatSupported(self, audio_format: _Format) -> bool:
            return bool(state.supported)

    def sink(device: Any, audio_format: _Format, parent: Any) -> _Sink:
        created = _Sink(device, audio_format, parent)
        created.fail_on_start = state.fail
        state.sinks.append(created)
        return created

    module = types.ModuleType("PySide6.QtMultimedia")
    module.QAudioFormat = _Format  # type: ignore[attr-defined]
    module.QAudioSink = sink  # type: ignore[attr-defined]
    module.QMediaDevices = SimpleNamespace(defaultAudioOutput=Device)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "PySide6.QtMultimedia", module)
    return state


PCM = PlaybackPcm(16000, 1, 32000, bytes(range(256)) * 4)


@pytest.mark.parametrize(
    ("setting", "code"),
    [("null", "PLAYBACK_OUTPUT_UNAVAILABLE"), ("unsupported", "PLAYBACK_FORMAT_UNSUPPORTED")],
)
def test_missing_or_incapable_output_is_an_explicit_error(
    fake_qt: SimpleNamespace, setting: str, code: str
) -> None:
    if setting == "null":
        fake_qt.null = True
    else:
        fake_qt.supported = False
    player = SinkPlayback()
    with pytest.raises(StateConflict, match=code):
        player.start(PCM)
    assert fake_qt.sinks == [] and not player.active() and player.position_ms() is None


def test_start_sends_exact_payload_format_volume_and_reports_position(
    fake_qt: SimpleNamespace,
) -> None:
    player = SinkPlayback()
    player.start(PCM, volume=0.0)
    (sink,) = fake_qt.sinks
    assert sink.format == {"rate": 16000, "channels": 1, "format": "Int16"}
    assert sink.played == PCM.payload and sink.volume == 0.0 and player.active()
    sink.processed = 250_400
    assert player.position_ms() == 2000 + 250


def test_sink_error_after_start_releases_and_reports(fake_qt: SimpleNamespace) -> None:
    fake_qt.fail = True
    player = SinkPlayback()
    with pytest.raises(StateConflict, match="PLAYBACK_OUTPUT_FAILED"):
        player.start(PCM)
    (sink,) = fake_qt.sinks
    assert sink.stops == 1 and sink.deleted and not player.active()


def test_exhausted_buffer_releases_the_device(fake_qt: SimpleNamespace) -> None:
    player = SinkPlayback()
    player.start(PCM)
    (sink,) = fake_qt.sinks
    sink.go_idle()
    assert sink.stops == 1 and sink.deleted and player.position_ms() is None


def test_restart_stops_first_and_ignores_its_late_signal(fake_qt: SimpleNamespace) -> None:
    player = SinkPlayback()
    player.start(PCM)
    player.start(PlaybackPcm(48000, 2, 0, bytes(16)))
    first, second = fake_qt.sinks
    assert first.stops == 1 and first.deleted and second.stops == 0
    first.go_idle()  # stale sink: must not stop the current one
    assert second.stops == 0 and player.active()


@pytest.mark.parametrize(
    ("error", "messages"), [("IOError", ["PLAYBACK_OUTPUT_FAILED"]), ("NoError", [])]
)
def test_stop_by_qt_after_start_releases_and_reports_errors(
    fake_qt: SimpleNamespace, error: str, messages: list[str]
) -> None:
    # L04-D04: the original counterexample left the sink and buffer held and silent.
    reported: list[str] = []
    player = SinkPlayback(on_error=reported.append)
    player.start(PCM)
    (sink,) = fake_qt.sinks
    sink.stopped_by_qt(error)
    assert sink.deleted and sink.stops == 1 and player.position_ms() is None
    assert not player.active() and reported == messages


def test_stop_is_idempotent(fake_qt: SimpleNamespace) -> None:
    player = SinkPlayback()
    player.stop()
    player.start(PCM)
    player.stop()
    player.stop()
    (sink,) = fake_qt.sinks
    assert sink.stops == 1 and not player.active()


# --- Desktop path D ---


def test_desktop_play_reports_output_errors_and_stop_invalidates() -> None:
    from recoryn.ui.ai_bridge import DesktopAI

    class Playback:
        stopped = 0

        def start(self, pcm: PlaybackPcm) -> None:
            raise StateConflict("PLAYBACK_OUTPUT_UNAVAILABLE")

        def stop(self) -> None:
            self.stopped += 1

    status: list[str] = []
    bridge = DesktopAI.__new__(DesktopAI)
    bridge.playback = Playback()  # type: ignore[assignment]
    bridge.panel = SimpleNamespace(status=SimpleNamespace(setText=status.append))
    bridge._playback_generation = 3
    bridge._play(PCM)
    assert status and "PLAYBACK_OUTPUT_UNAVAILABLE" in status[0]
    bridge.stop_playback()
    assert bridge._playback_generation == 4 and bridge.playback.stopped == 1  # type: ignore[attr-defined]


def test_desktop_shows_output_failure_after_start(fake_qt: SimpleNamespace) -> None:
    # L04-D04 through the real DesktopAI._play -> SinkPlayback path.
    from recoryn.ui.ai_bridge import DesktopAI

    status: list[str] = []
    bridge = DesktopAI.__new__(DesktopAI)
    bridge.panel = SimpleNamespace(status=SimpleNamespace(setText=status.append))
    bridge.playback = SinkPlayback(on_error=bridge._report_playback)
    bridge._play(PCM)
    (sink,) = fake_qt.sinks
    assert status == [] and bridge.playback.active()
    sink.stopped_by_qt("IOError")
    assert len(status) == 1 and "PLAYBACK_OUTPUT_FAILED" in status[0]
    assert sink.deleted and not bridge.playback.active()
