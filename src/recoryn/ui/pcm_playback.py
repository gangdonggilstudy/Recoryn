"""Recoryn's own playback of verified derived WAV clips (license policy L01 D7).

Qt Multimedia's media decoder backends (FFmpeg and Windows Media Foundation) are
not distributed. A derived clip is 16-bit PCM WAV of at most 8 MiB (``app.media``)
that keeps the source channel count (1..64) and rate. The exact bytes whose
SHA-256 was verified are parsed here, cut at the requested frame and handed to a
``QAudioSink``. One or two channels play bit-exact; more channels are averaged to
mono with equal weights (not a layout-aware surround downmix).
"""

from __future__ import annotations

import hashlib
import io
import sys
import wave
from array import array
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from recoryn.domain import StateConflict
from recoryn.storage._safe import open_file

# app.media caps a clip's PCM at 8 MiB; allow the RIFF header on top of it.
MAX_CLIP_BYTES = 8 * 1024 * 1024 + 4096
MAX_CHANNELS = 64
SAMPLE_BYTES = 2


@dataclass(frozen=True)
class PlaybackPcm:
    sample_rate: int
    channels: int  # 1 or 2 after mixing
    start_frame: int  # in the source clip
    payload: bytes  # little-endian Int16, interleaved


def mix_to_mono(payload: bytes, channels: int) -> bytes:
    """Equal-weight mean per frame, rounded half to even; never exceeds Int16."""
    samples = array("h")
    samples.frombytes(payload)
    if sys.byteorder == "big":  # pragma: no cover - Windows/x86 is little-endian
        samples.byteswap()
    columns = [samples[channel::channels] for channel in range(channels)]
    mixed = array("h", (round(total / channels) for total in map(sum, zip(*columns, strict=True))))
    if sys.byteorder == "big":  # pragma: no cover
        mixed.byteswap()
    return mixed.tobytes()


def prepare_playback(path: Path, sha256: str, position_ms: int) -> PlaybackPcm:
    """Read once, verify the bytes that will play, and cut at the exact frame."""
    with open_file(path, "rb") as stream:
        data = stream.read(MAX_CLIP_BYTES + 1)
    if len(data) > MAX_CLIP_BYTES or hashlib.sha256(data).hexdigest() != sha256:
        raise StateConflict("PLAYBACK_SOURCE_INVALID")
    try:
        with wave.open(io.BytesIO(data), "rb") as audio:
            rate = audio.getframerate()
            channels = audio.getnchannels()
            frames = audio.getnframes()
            if audio.getsampwidth() != SAMPLE_BYTES or not 1 <= channels <= MAX_CHANNELS:
                raise StateConflict("PLAYBACK_SOURCE_INVALID")
            start = min(frames, max(0, position_ms) * rate // 1000)
            audio.setpos(start)
            payload = audio.readframes(frames - start)
    except (EOFError, wave.Error):
        raise StateConflict("PLAYBACK_SOURCE_INVALID") from None
    if rate <= 0 or len(payload) != (frames - start) * channels * SAMPLE_BYTES:
        raise StateConflict("PLAYBACK_SOURCE_INVALID")
    if channels > 2:
        payload, channels = mix_to_mono(payload, channels), 1
    return PlaybackPcm(rate, channels, start, payload)


def _name(value: Any) -> str:
    # PySide6 6.12 returns QtAudio enums that do not compare equal to the QAudio
    # aliases, so states and errors are compared by their stable names.
    return str(getattr(value, "name", value))


class SinkPlayback:
    """At most one ``QAudioSink`` at a time. Qt is imported only when playing."""

    def __init__(self, parent: Any = None, on_error: Callable[[str], None] | None = None) -> None:
        self._parent = parent
        self._on_error = on_error
        self._sink: Any = None
        self._buffer: Any = None
        self._start_frame = 0
        self._rate = 1

    def start(self, pcm: PlaybackPcm, *, volume: float = 1.0) -> None:
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice
        from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices

        self.stop()
        audio_format = QAudioFormat()
        audio_format.setSampleRate(pcm.sample_rate)
        audio_format.setChannelCount(pcm.channels)
        audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        device = QMediaDevices.defaultAudioOutput()
        if device.isNull():
            raise StateConflict("PLAYBACK_OUTPUT_UNAVAILABLE")
        if not device.isFormatSupported(audio_format):
            raise StateConflict("PLAYBACK_FORMAT_UNSUPPORTED")
        buffer = QBuffer(self._parent)
        buffer.setData(QByteArray(pcm.payload))
        buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        sink = QAudioSink(device, audio_format, self._parent)
        sink.setVolume(volume)
        # A zero-argument slot: PySide6 6.12 cannot convert the QAudio::State argument.
        sink.stateChanged.connect(lambda: self._state_changed(sink))
        self._sink, self._buffer = sink, buffer
        self._start_frame, self._rate = pcm.start_frame, pcm.sample_rate
        sink.start(buffer)
        if _name(sink.error()) != "NoError":
            self.stop()
            raise StateConflict("PLAYBACK_OUTPUT_FAILED")

    def _state_changed(self, sink: Any) -> None:
        # A replaced sink, or one this object is stopping itself, is ignored.
        if sink is not self._sink:
            return
        state = _name(sink.state())
        if state == "IdleState":  # the buffer is exhausted: release the device
            self.stop()
        elif state == "StoppedState":
            # Stopped by Qt after starting, e.g. the device failed or vanished
            # (L04-D04): release everything and report an error, never stay silent.
            failed = _name(sink.error()) != "NoError"
            self.stop()
            if failed and self._on_error is not None:
                self._on_error("PLAYBACK_OUTPUT_FAILED")

    def active(self) -> bool:
        return self._sink is not None and _name(self._sink.state()) == "ActiveState"

    def position_ms(self) -> int | None:
        if self._sink is None:
            return None
        return int(self._start_frame * 1000 // self._rate + self._sink.processedUSecs() // 1000)

    def stop(self) -> None:
        sink, buffer = self._sink, self._buffer
        self._sink = self._buffer = None
        if sink is not None:
            sink.stop()
            sink.deleteLater()
        if buffer is not None:
            buffer.close()
            buffer.deleteLater()
