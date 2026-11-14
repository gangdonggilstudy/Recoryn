"""Deterministic PCM for tests and explicitly requested simulation.

The signal is an eight-bit sawtooth, offset by 17 steps per channel and scaled
to the requested sample representation. Its samples depend on absolute frame
position, not block size. The clock is simulated, with no hardware or wall-clock
access, and iteration neither sleeps nor performs I/O.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from struct import pack

from recoryn.domain import AudioFormat, PCMBlock, ValidationError


@dataclass(frozen=True, slots=True)
class SyntheticSource:
    """A lazy, repeatable source with exact integer sample-position timestamps."""

    session_id: str
    track_id: str
    epoch_id: str
    format: AudioFormat
    total_frames: int
    block_frames: int = 480
    start_ns: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.format, AudioFormat):
            raise ValidationError("format must be an AudioFormat")
        for name, value, minimum in (
            ("total_frames", self.total_frames, 0),
            ("block_frames", self.block_frames, 1),
            ("start_ns", self.start_ns, 0),
        ):
            if type(value) is not int or value < minimum:
                raise ValidationError(f"{name} must be an integer >= {minimum}")
        # Validate identity and the entire simulated timeline without generating
        # its payload. Empty sources still validate their IDs and starting clock.
        last_frame = max(0, self.total_frames - 1)
        last_timestamp = self.start_ns + last_frame * 1_000_000_000 // self.format.sample_rate
        PCMBlock(
            session_id=self.session_id,
            track_id=self.track_id,
            epoch_id=self.epoch_id,
            sequence=last_frame // self.block_frames,
            format=self.format,
            frame_count=1,
            payload=bytes(self.format.frame_bytes),
            capture_mono_ns=last_timestamp,
            arrival_mono_ns=last_timestamp,
            device_frame_position=last_frame,
            clock_quality="SYNTHETIC",
        )

    def __iter__(self) -> Iterator[PCMBlock]:
        frame_start = 0
        sequence = 0
        while frame_start < self.total_frames:
            frame_count = min(self.block_frames, self.total_frames - frame_start)
            timestamp = self.start_ns + frame_start * 1_000_000_000 // self.format.sample_rate
            yield PCMBlock(
                session_id=self.session_id,
                track_id=self.track_id,
                epoch_id=self.epoch_id,
                sequence=sequence,
                format=self.format,
                frame_count=frame_count,
                payload=self._payload(frame_start, frame_count),
                capture_mono_ns=timestamp,
                arrival_mono_ns=timestamp,
                device_frame_position=frame_start,
                clock_quality="SYNTHETIC",
            )
            frame_start += frame_count
            sequence += 1

    def _payload(self, frame_start: int, frame_count: int) -> bytes:
        payload = bytearray()
        sample_width = self.format.frame_bytes // self.format.channels
        for frame in range(frame_start, frame_start + frame_count):
            for channel in range(self.format.channels):
                step = (frame + 17 * channel) % 256 - 128
                if self.format.sample_type == "f32le":
                    payload.extend(pack("<f", step / 128))
                else:
                    sample = step << (sample_width * 8 - 8)
                    payload.extend(sample.to_bytes(sample_width, "little", signed=True))
        return bytes(payload)
