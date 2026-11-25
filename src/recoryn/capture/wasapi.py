"""Experimental native WASAPI capture with an injectable low-level boundary.

No DLL/device/COM activity occurs on import or source construction. All native
stream calls, acquired buffers and COM releases live on the capture worker.
The polling worker and Python callbacks are not hard real-time. Physical
device/driver/long-session validation remains NOT_RUN until explicitly tested.

References (Microsoft primary documentation, checked 2026-11-14):
https://learn.microsoft.com/windows/win32/api/audioclient/nf-audioclient-iaudioclient-initialize
https://learn.microsoft.com/windows/win32/api/audioclient/nf-audioclient-iaudiocaptureclient-getbuffer
https://learn.microsoft.com/windows/win32/coreaudio/loopback-recording
"""

from __future__ import annotations

import ctypes as ct
import math
from collections.abc import Callable
from dataclasses import dataclass
from threading import Event, RLock, Thread, get_ident
from time import monotonic
from typing import Protocol, cast

from recoryn.capture.devices import (
    _IID_CAPTURE_CLIENT,
    _PTR,
    NativeFormat,
    WasapiError,
    _activate_client,
    _check,
    _device_id,
    _get_device,
    _invoke,
    _mix_format,
    _release,
    _WinAPI,
)
from recoryn.domain import MAX_PCM_BLOCK_BYTES, AudioFormat, PCMBlock, ValidationError

from .queue import CaptureItem

DATA_DISCONTINUITY = 1
SILENT = 2
TIMESTAMP_ERROR = 4
_MAX_PACKET_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class NativePacket:
    """Owned packet bytes; qpc_position_100ns is never a raw QPC tick value."""

    payload: bytes | None
    frame_count: int
    flags: int
    device_frame_position: int | None
    qpc_position_100ns: int | None
    arrival_mono_ns: int

    def __post_init__(self) -> None:
        if self.payload is not None and type(self.payload) is not bytes:
            raise ValidationError("packet payload must be owned bytes")
        if type(self.frame_count) is not int or self.frame_count <= 0:
            raise ValidationError("invalid packet frames")
        if type(self.flags) is not int or not 0 <= self.flags <= 0xFFFFFFFF:
            raise ValidationError("invalid packet flags")
        for value in (self.device_frame_position, self.qpc_position_100ns):
            if value is not None and (type(value) is not int or not 0 <= value < 2**63):
                raise ValidationError("invalid packet clock")
        if type(self.arrival_mono_ns) is not int or not 0 <= self.arrival_mono_ns < 2**63:
            raise ValidationError("invalid arrival clock")


def split_packet(
    packet: NativePacket,
    identity: tuple[str, str, str],
    sequence: int,
    format: AudioFormat,
    *,
    max_block_bytes: int | None = None,
) -> tuple[PCMBlock, ...]:
    """Own a frame-aligned packet group, preserving its clock/flag semantics."""
    limit = MAX_PCM_BLOCK_BYTES if max_block_bytes is None else max_block_bytes
    if type(limit) is not int or limit < format.frame_bytes:
        raise ValidationError("Packet fragment limit must contain a whole frame")
    size = packet.frame_count * format.frame_bytes
    if size > _MAX_PACKET_BYTES:
        raise WasapiError("PACKET_TOO_LARGE")
    silent = bool(packet.flags & SILENT)
    if not silent and (packet.payload is None or len(packet.payload) != size):
        raise WasapiError("INVALID_PACKET")
    frames_per_block = limit // format.frame_bytes
    count = (packet.frame_count + frames_per_block - 1) // frames_per_block
    flags = tuple(
        name
        for bit, name in (
            (DATA_DISCONTINUITY, "DATA_DISCONTINUITY"),
            (SILENT, "SILENT"),
            (TIMESTAMP_ERROR, "TIMESTAMP_ERROR"),
        )
        if packet.flags & bit
    )
    if packet.flags & ~7:
        flags += (f"RAW_FLAGS_{packet.flags & ~7:08X}",)
    capture_ns = (
        packet.qpc_position_100ns * 100
        if packet.qpc_position_100ns is not None and not packet.flags & TIMESTAMP_ERROR
        else None
    )
    if capture_ns is not None and capture_ns >= 2**63:
        capture_ns = None
    quality = "DEVICE_CORRELATED" if capture_ns is not None else "INVALID"
    result = []
    for index in range(count):
        offset = index * frames_per_block
        frames = min(frames_per_block, packet.frame_count - offset)
        position = (
            packet.device_frame_position + offset
            if packet.device_frame_position is not None
            else None
        )
        stamp = (
            capture_ns + offset * 1_000_000_000 // format.sample_rate
            if capture_ns is not None
            else None
        )
        if position is not None and position >= 2**63:
            position = None
        if stamp is not None and stamp >= 2**63:
            stamp = None
        begin = offset * format.frame_bytes
        payload = (
            bytes(frames * format.frame_bytes)
            if silent
            else cast(bytes, packet.payload)[begin : begin + frames * format.frame_bytes]
        )
        result.append(
            PCMBlock(
                *identity,
                sequence,
                format,
                frames,
                payload,
                stamp,
                packet.arrival_mono_ns,
                position,
                quality,
                index,
                count,
                flags
                if index == 0
                else tuple(f for f in flags if f in {"SILENT", "TIMESTAMP_ERROR"}),
            )
        )
    return tuple(result)


class WasapiBackend(Protocol):
    """Methods run on one worker; read_packet must promptly return None if idle.

    probe/open query independent native formats. open initializes but does not
    start the stream. close must release resources, including partial opens.
    A fake can implement this protocol without COM, DLLs or device access.
    """

    def initialize(self) -> None: ...
    def probe(self, device_id: str, *, loopback: bool) -> NativeFormat: ...
    def open(self, device_id: str, *, loopback: bool) -> NativeFormat: ...
    def start(self) -> None: ...
    def read_packet(self) -> NativePacket | None: ...
    def stop(self) -> None: ...
    def close(self) -> None: ...


class NativeWasapiBackend:
    """Shared-mode capture/loopback using Windows SDK 10.0.22621 COM slots."""

    def __init__(self) -> None:
        self._api: _WinAPI | None = None
        self._enumerator, self._device, self._client, self._capture = (
            _PTR(),
            _PTR(),
            _PTR(),
            _PTR(),
        )
        self._format: NativeFormat | None = None
        self._started = False
        self._owner: int | None = None

    def initialize(self) -> None:
        self._owner = get_ident()
        self._api = _WinAPI().__enter__()

    def _check_thread(self) -> _WinAPI:
        if self._api is None or self._owner != get_ident():
            raise WasapiError("THREAD_VIOLATION")
        return self._api

    def probe(self, device_id: str, *, loopback: bool) -> NativeFormat:
        api = self._check_thread()
        enumerator, device, client = _PTR(), _PTR(), _PTR()
        try:
            enumerator = api.enumerator()
            device = _get_device(enumerator, device_id)
            client = _activate_client(device, loopback=loopback)
            return _mix_format(api, client)
        finally:
            _release(client)
            _release(device)
            _release(enumerator)

    def open(self, device_id: str, *, loopback: bool) -> NativeFormat:
        api = self._check_thread()
        self._enumerator = api.enumerator()
        self._device = _get_device(self._enumerator, device_id)
        self._client = _activate_client(self._device, loopback=loopback)
        self._format = _mix_format(api, self._client)
        # Preserve the exact native format bytes, valid bits and speaker mask.
        format_buffer = ct.create_string_buffer(self._format.raw)
        flags = 0x00020000 if loopback else 0  # AUDCLNT_STREAMFLAGS_LOOPBACK
        _check(
            _invoke(
                self._client,
                3,
                (ct.c_int32, ct.c_uint32, ct.c_int64, ct.c_int64, _PTR, _PTR),
                0,
                flags,
                1_000_000,
                0,
                ct.cast(format_buffer, _PTR),
                None,
            )
        )
        _check(
            _invoke(
                self._client,
                14,
                (_PTR, _PTR),
                ct.byref(_IID_CAPTURE_CLIENT),
                ct.byref(self._capture),
            )
        )
        return self._format

    def start(self) -> None:
        self._check_thread()
        _check(_invoke(self._client, 10, ()))
        self._started = True

    def read_packet(self) -> NativePacket | None:
        api = self._check_thread()
        if not self._started or self._format is None:
            raise WasapiError("NOT_RUNNING")
        next_frames = ct.c_uint32()
        _check(_invoke(self._capture, 5, (_PTR,), ct.byref(next_frames)))
        if next_frames.value == 0:
            return None
        pointer, frames, flags = _PTR(), ct.c_uint32(), ct.c_uint32()
        position, qpc = ct.c_uint64(), ct.c_uint64()
        _check(
            _invoke(
                self._capture,
                3,
                (_PTR, _PTR, _PTR, _PTR, _PTR),
                ct.byref(pointer),
                ct.byref(frames),
                ct.byref(flags),
                ct.byref(position),
                ct.byref(qpc),
            )
        )
        try:
            if not frames.value:
                return None
            size = frames.value * self._format.audio_format.frame_bytes
            if size > _MAX_PACKET_BYTES:
                raise WasapiError("PACKET_TOO_LARGE")
            if flags.value & SILENT:
                payload = None  # SILENT explicitly ignores any pointer contents.
            elif pointer.value:
                payload = ct.string_at(pointer, size)
            else:
                raise WasapiError("INVALID_PACKET")
            return NativePacket(
                payload, frames.value, flags.value, position.value, qpc.value, api.now_ns()
            )
        finally:
            # The acquired pointer never escapes; release on the same worker,
            # including metadata/copy failures. Source callbacks see owned bytes.
            _check(_invoke(self._capture, 4, (ct.c_uint32,), frames.value))

    def stop(self) -> None:
        self._check_thread()
        if self._started:
            try:
                _check(_invoke(self._client, 11, ()))
            finally:
                self._started = False

    def close(self) -> None:
        if self._api is None:
            return
        api = self._check_thread()
        try:
            self.stop()
        finally:
            try:
                failure: Exception | None = None
                for pointer in (self._capture, self._client, self._device, self._enumerator):
                    try:
                        _release(pointer)
                    except Exception as exc:
                        if failure is None:
                            failure = exc
                if failure is not None:
                    raise failure
            finally:
                try:
                    api.__exit__()
                finally:
                    self._api = None


def _timeout(value: float, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError("invalid timeout")
    try:
        result = float(value)
    except OverflowError:
        raise ValidationError("invalid timeout") from None
    if not math.isfinite(result) or result < 0 or (positive and result == 0):
        raise ValidationError("invalid timeout")
    return result


class WasapiSource:
    """Explicit start/ready and stop/release acknowledgments.

    Callbacks execute on the worker and must return promptly. Returning False
    from submit records a rejection, not necessarily a queue loss (a closed
    RecordingService may reject for privacy). The core queue owns loss counters.
    The source never changes endpoint or reconnects to another device silently.
    """

    def __init__(
        self,
        device_id: str,
        *,
        loopback: bool = False,
        backend_factory: Callable[[], WasapiBackend] | None = None,
        expected_format: AudioFormat | None = None,
        startup_timeout: float = 5.0,
        poll_interval: float = 0.005,
    ) -> None:
        _device_id(device_id)
        if type(loopback) is not bool:
            raise ValidationError("loopback must be bool")
        if expected_format is not None and not isinstance(expected_format, AudioFormat):
            raise ValidationError("invalid expected format")
        if backend_factory is not None and not callable(backend_factory):
            raise ValidationError("invalid backend factory")
        self.device_id, self.loopback = device_id, loopback
        self._factory = backend_factory or NativeWasapiBackend
        self._expected_format = expected_format
        self._startup_timeout = _timeout(startup_timeout, positive=True)
        self._poll_interval = _timeout(poll_interval, positive=True)
        self._lock = RLock()
        self._thread: Thread | None = None
        self._stop, self._ready, self._running = Event(), Event(), Event()
        self._format: AudioFormat | None = None
        self._error: WasapiError | None = None
        self._cleanup_error: WasapiError | None = None
        self._epochs: set[tuple[str, str, str]] = set()

    @property
    def running(self) -> bool:
        return self._running.is_set()

    def start(
        self,
        session_id: str,
        track_id: str,
        epoch_id: str,
        submit: Callable[[CaptureItem], bool],
        on_health: Callable[[dict[str, object]], None],
    ) -> AudioFormat:
        # Validate IDs without native activity, even on a failing startup.
        PCMBlock(session_id, track_id, epoch_id, 0, AudioFormat(1, 1), 1, b"\0\0", 0, 0)
        if not callable(submit) or not callable(on_health):
            raise ValidationError("callbacks must be callable")
        identity = (session_id, track_id, epoch_id)
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise WasapiError("ALREADY_RUNNING")
            if identity in self._epochs:
                raise WasapiError("EPOCH_REUSE")
            self._epochs.add(identity)
            self._stop, self._ready, self._running = Event(), Event(), Event()
            self._error = self._cleanup_error = None
            self._format = None
            self._thread = Thread(
                target=self._worker,
                args=(identity, submit, on_health),
                daemon=True,
                name="recoryn-wasapi",
            )
            self._thread.start()
        if not self._ready.wait(self._startup_timeout):
            self._stop.set()
            raise WasapiError("START_TIMEOUT")
        if self._error is not None:
            raise self._error
        if self._format is None:
            raise WasapiError("START_FAILED")
        return self._format

    def stop(self, timeout: float = 5.0) -> None:
        timeout = _timeout(timeout)
        with self._lock:
            thread = self._thread
            self._stop.set()
        if thread is None:
            return
        if thread.ident == get_ident():
            raise WasapiError("STOP_FROM_CALLBACK")
        thread.join(timeout)
        if thread.is_alive():
            raise WasapiError("STOP_TIMEOUT")
        if self._cleanup_error is not None:
            raise self._cleanup_error

    def _worker(
        self,
        identity: tuple[str, str, str],
        submit: Callable[[CaptureItem], bool],
        health: Callable[[dict[str, object]], None],
    ) -> None:
        backend: WasapiBackend | None = None
        started = False
        sequence = accepted = rejected = 0
        last_sequence: int | None = None
        try:
            backend = self._factory()
            backend.initialize()
            probed = backend.probe(self.device_id, loopback=self.loopback)
            opened = backend.open(self.device_id, loopback=self.loopback)
            if opened != probed or (
                self._expected_format is not None and opened.audio_format != self._expected_format
            ):
                raise WasapiError("FORMAT_CHANGED")
            if self._stop.is_set():
                raise WasapiError("START_CANCELLED")
            backend.start()
            started = True
            self._format = opened.audio_format
            self._running.set()
            health({"event": "ready", **opened.metadata(), "loopback": self.loopback})
            self._ready.set()
            last_idle = monotonic()
            while not self._stop.is_set():
                packet = backend.read_packet()
                if packet is None:
                    if monotonic() - last_idle >= 1:
                        health({"event": "idle", "code": "NO_PACKETS_UNKNOWN"})
                        last_idle = monotonic()
                    self._stop.wait(self._poll_interval)
                    continue
                if self._stop.is_set():
                    break
                size = packet.frame_count * opened.audio_format.frame_bytes
                if size > _MAX_PACKET_BYTES:
                    raise WasapiError("PACKET_TOO_LARGE")
                fragments = split_packet(packet, identity, sequence, opened.audio_format)
                first = fragments[0]
                accepted_block = submit(first if len(fragments) == 1 else fragments)
                if type(accepted_block) is not bool:
                    raise WasapiError("INVALID_SUBMIT_RESULT")
                if accepted_block:
                    accepted += packet.frame_count
                else:
                    rejected += packet.frame_count
                last_sequence = sequence
                health(
                    {
                        "event": "packet",
                        "sequence": sequence,
                        "flags": list(first.flags),
                        "accepted": accepted_block,
                        "frame_count": packet.frame_count,
                        "fragment_count": len(fragments),
                        "capture_mono_ns": first.capture_mono_ns,
                        "arrival_mono_ns": packet.arrival_mono_ns,
                        "device_frame_position": packet.device_frame_position,
                    }
                )
                sequence += 1
        except Exception as exc:
            self._error = exc if isinstance(exc, WasapiError) else WasapiError("CAPTURE_FAILED")
            try:
                health({"event": "error", "code": self._error.code})
            except Exception:
                pass
        finally:
            if backend is not None:
                try:
                    if started:
                        backend.stop()
                except Exception:
                    self._cleanup_error = WasapiError("DEVICE_STOP_FAILED")
                try:
                    backend.close()
                except Exception:
                    self._cleanup_error = WasapiError("DEVICE_RELEASE_FAILED")
            self._running.clear()
            self._ready.set()
            try:
                health(
                    {
                        "event": "stopped",
                        "last_sequence": last_sequence,
                        "accepted_frames": accepted,
                        "rejected_frames": rejected,
                        "release_ack": self._cleanup_error is None,
                    }
                )
            except Exception:
                pass
