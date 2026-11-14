"""Fake worker and fake ctypes COM ABI tests. No real endpoint is ever opened."""

from __future__ import annotations

import ctypes as ct
import struct
import sys
from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from itertools import count
from threading import Event, get_ident
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from recoryn.capture import devices
from recoryn.capture import wasapi as wasapi_module
from recoryn.capture.devices import DeviceInfo, NativeFormat, WasapiError, probe_device
from recoryn.capture.wasapi import (
    DATA_DISCONTINUITY,
    SILENT,
    TIMESTAMP_ERROR,
    NativePacket,
    NativeWasapiBackend,
    WasapiSource,
)
from recoryn.domain import AudioFormat, PCMBlock, ValidationError

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def no_real_system_dlls(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("real system DLL/device access is forbidden in unit tests")

    monkeypatch.setattr(ct, "WinDLL", forbidden, raising=False)


def wave_format(*, extensible: bool = False, floating: bool = False) -> bytes:
    bits = 32 if floating else 16
    extra = 22 if extensible else 0
    tag = 0xFFFE if extensible else (3 if floating else 1)
    header = struct.pack("<HHIIHHH", tag, 2, 48_000, 48_000 * bits // 4, bits // 4, bits, extra)
    if extensible:
        subtype = UUID(
            "00000003-0000-0010-8000-00aa00389b71"
            if floating
            else "00000001-0000-0010-8000-00aa00389b71"
        )
        header += struct.pack("<HI", bits, 3) + subtype.bytes_le
    return header


class FakeBackend:
    def __init__(self, packets: list[NativePacket] | None = None) -> None:
        self.format = NativeFormat(AudioFormat(48_000, 1), 16)
        self.open_format = self.format
        self.packets = deque(packets or [])
        self.calls: list[tuple[str, int]] = []
        self.fail: str | None = None
        self.read_gate: Event | None = None
        self.read_entered = Event()
        self.close_gate: Event | None = None
        self.close_entered = Event()

    def note(self, method: str) -> None:
        self.calls.append((method, get_ident()))
        if self.fail == method:
            raise WasapiError("DEVICE_UNAVAILABLE")

    def initialize(self) -> None:
        self.note("initialize")

    def probe(self, device_id: str, *, loopback: bool) -> NativeFormat:
        self.note("probe")
        return self.format

    def open(self, device_id: str, *, loopback: bool) -> NativeFormat:
        self.note("open")
        return self.open_format

    def start(self) -> None:
        self.note("start")

    def read_packet(self) -> NativePacket | None:
        self.note("read")
        self.read_entered.set()
        if self.read_gate is not None:
            assert self.read_gate.wait(3)
        return self.packets.popleft() if self.packets else None

    def stop(self) -> None:
        self.note("stop")

    def close(self) -> None:
        self.close_entered.set()
        if self.close_gate is not None:
            assert self.close_gate.wait(3)
        self.note("close")


def test_construct_and_stop_without_start_never_call_native_code() -> None:
    source = WasapiSource("endpoint")
    assert not source.running
    source.stop()
    native = NativeWasapiBackend()
    native.close()
    assert not source.running


def test_worker_packet_units_flags_rejection_and_thread_owned_cleanup() -> None:
    packets = [
        NativePacket(b"\x01\0\x02\0", 2, DATA_DISCONTINUITY, 480, 20_000, 2_100_000),
        NativePacket(None, 3, SILENT | TIMESTAMP_ERROR | 8, 482, 20_500, 2_200_000),
    ]
    backend = FakeBackend(packets)
    received: list[PCMBlock] = []
    health: list[dict[str, object]] = []
    processed = Event()

    def submit(block: PCMBlock) -> bool:
        received.append(block)
        return block.sequence == 0

    def on_health(event: dict[str, object]) -> None:
        health.append(event)
        if event.get("event") == "packet" and event["sequence"] == 1:
            processed.set()

    source = WasapiSource("endpoint", backend_factory=lambda: backend)
    assert source.start("session", "mic", "epoch", submit, on_health) == backend.format.audio_format
    assert processed.wait(3)
    source.stop()
    assert not source.running
    assert [b.sequence for b in received] == [0, 1]
    assert received[0].capture_mono_ns == 2_000_000
    assert received[0].device_frame_position == 480
    assert received[0].payload == b"\x01\0\x02\0"
    assert received[1].payload == bytes(6)
    assert received[1].capture_mono_ns is None
    assert received[1].arrival_mono_ns == 2_200_000
    assert set(received[1].flags) == {"SILENT", "TIMESTAMP_ERROR", "RAW_FLAGS_00000008"}
    assert health[-1] == {
        "event": "stopped",
        "last_sequence": 1,
        "accepted_frames": 2,
        "rejected_frames": 3,
        "release_ack": True,
    }
    assert len({thread for _, thread in backend.calls}) == 1
    assert backend.calls[0][1] != get_ident()
    assert [name for name, _ in backend.calls][-2:] == ["stop", "close"]
    with pytest.raises(WasapiError, match="EPOCH_REUSE"):
        source.start("session", "mic", "epoch", submit, on_health)


@pytest.mark.parametrize("stage", ["initialize", "probe", "open", "start"])
def test_startup_errors_release_partial_backend(stage: str) -> None:
    backend = FakeBackend()
    backend.fail = stage
    source = WasapiSource("endpoint", backend_factory=lambda: backend)
    with pytest.raises(WasapiError, match="DEVICE_UNAVAILABLE"):
        source.start("s", "t", "e", lambda b: True, lambda event: None)
    source.stop()
    assert [name for name, _ in backend.calls][-1] == "close"
    assert not source.running


@pytest.mark.parametrize("external_probe", [False, True])
def test_native_or_ui_probe_format_mismatch_fails_before_start(external_probe: bool) -> None:
    backend = FakeBackend()
    changed = AudioFormat(44_100, 1)
    if not external_probe:
        backend.open_format = NativeFormat(changed, 16)
    source = WasapiSource(
        "endpoint",
        backend_factory=lambda: backend,
        expected_format=changed if external_probe else None,
    )
    with pytest.raises(WasapiError, match="FORMAT_CHANGED"):
        source.start("s", "t", "e", lambda b: True, lambda event: None)
    source.stop()
    assert "start" not in [name for name, _ in backend.calls]


def test_stop_timeout_does_not_claim_release_ack_and_blocks_late_packet() -> None:
    backend = FakeBackend([NativePacket(b"\1\0", 1, 0, 0, 0, 0)])
    backend.read_gate = Event()
    received: list[PCMBlock] = []
    source = WasapiSource("endpoint", backend_factory=lambda: backend)

    def submit(block: PCMBlock) -> bool:
        received.append(block)
        return True

    source.start("s", "t", "e", submit, lambda e: None)
    assert backend.read_entered.wait(3)
    with pytest.raises(WasapiError, match="STOP_TIMEOUT"):
        source.stop(timeout=0)
    assert source.running
    backend.read_gate.set()
    source.stop()
    assert received == [] and not source.running


def test_stop_waits_for_device_release_and_reports_release_failure() -> None:
    backend = FakeBackend()
    backend.close_gate = Event()
    backend.fail = "close"
    health: list[dict[str, object]] = []
    source = WasapiSource("endpoint", backend_factory=lambda: backend)
    source.start("s", "t", "e", lambda b: True, health.append)
    with pytest.raises(WasapiError, match="STOP_TIMEOUT"):
        source.stop(0)
    assert backend.close_entered.wait(3)
    backend.close_gate.set()
    with pytest.raises(WasapiError, match="DEVICE_RELEASE_FAILED"):
        source.stop()
    assert health[-1]["release_ack"] is False


def test_worker_backend_disconnect_is_safe_and_cleans_up() -> None:
    backend = FakeBackend()
    backend.read_gate = Event()
    health: list[dict[str, object]] = []
    failed = Event()

    def on_health(event: dict[str, object]) -> None:
        health.append(event)
        if event["event"] == "error":
            failed.set()

    source = WasapiSource("endpoint", backend_factory=lambda: backend)
    source.start("s", "t", "e", lambda b: True, on_health)
    assert backend.read_entered.wait(3)
    backend.fail = "read"
    backend.read_gate.set()
    assert failed.wait(3)
    source.stop()
    assert {"event": "error", "code": "DEVICE_UNAVAILABLE"} in health


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), True])
def test_invalid_timeout_and_device_arguments(value: Any) -> None:
    with pytest.raises(ValidationError):
        WasapiSource("endpoint").stop(value)
    with pytest.raises(ValidationError):
        WasapiSource("endpoint", startup_timeout=value)


def test_invalid_source_and_packet_metadata() -> None:
    with pytest.raises(ValidationError):
        WasapiSource("bad\0id")
    with pytest.raises(ValidationError):
        WasapiSource("endpoint", loopback=1)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        NativePacket(b"", 0, 0, None, None, 0)
    with pytest.raises(ValidationError):
        NativePacket(bytearray(2), 1, 0, 0, 0, 0)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        NativePacket(b"\0\0", 1, -1, 0, 0, 0)


def test_format_parsing_matches_sdk_sizes_and_rejects_unknown_formats() -> None:
    assert ct.sizeof(devices._GUID) == 16
    assert ct.sizeof(devices._WaveFormatEx) == 18
    assert ct.sizeof(devices._PropVariant) == (24 if ct.sizeof(ct.c_void_p) == 8 else 16)
    for extended in (False, True):
        for floating in (False, True):
            raw = wave_format(extensible=extended, floating=floating)
            parsed = devices._parse_wave_format(raw)
            assert parsed.audio_format == AudioFormat(48_000, 2, "f32le" if floating else "s16le")
            assert parsed.valid_bits == (32 if floating else 16)
            assert parsed.channel_mask == (3 if extended else None)
            assert parsed.raw == raw
    for raw in (
        b"",
        bytes(5000),
        wave_format()[:-1],
        b"\xff\0" + wave_format()[2:],
        wave_format(extensible=True)[:-16] + bytes(16),
    ):
        with pytest.raises(WasapiError, match="UNSUPPORTED_FORMAT"):
            devices._parse_wave_format(raw)


class FakeFunction:
    def __init__(self, call: Callable[..., int | None]) -> None:
        self.call = call
        self.argtypes: Any = None
        self.restype: Any = None

    def __call__(self, *args: Any) -> int | None:
        return self.call(*args)


class FakeCom:
    """Real ctypes vtable memory; callbacks never enter an OS audio API."""

    def __init__(self, methods: dict[int, tuple[tuple[Any, ...], Callable[..., int]]]) -> None:
        self.callbacks: list[Any] = []
        self.table = (ct.c_void_p * 15)()
        for index, (argtypes, method) in {2: ((), lambda this: 0), **methods}.items():
            callback = devices._CALL(ct.c_int32, ct.c_void_p, *argtypes)(method)
            self.callbacks.append(callback)
            self.table[index] = ct.cast(callback, ct.c_void_p).value
        self.object = (ct.POINTER(ct.c_void_p) * 1)(ct.cast(self.table, ct.POINTER(ct.c_void_p)))
        self.pointer = ct.cast(self.object, ct.c_void_p)


def put(pointer: Any, value: int | None, type: Any = ct.c_void_p) -> None:
    ct.cast(pointer, ct.POINTER(type))[0] = value


class FakeWindows:
    """Fake WinDLL functions and full MMDevice/IAudioClient vtable graph."""

    def __init__(self) -> None:
        self.log: list[str] = []
        self.buffers: list[Any] = []
        self.raw = wave_format(extensible=True)
        self.packet_flags = 0
        self.packet_frames = 2
        self.packet_payload = b"\x01\0\x02\0\x03\0\x04\0"
        self.coresult = 0
        self.frequency_ok = True
        self.counter_ok = True
        self.get_buffer_error = 0
        self.no_identity = False
        self.no_mix_format = False
        self.no_default = False
        self.property_kind = 31
        self.property_error = 0
        self.device_count = 1
        self.null_payload = False
        self.next_frames_override: int | None = None
        self.packets = 1
        self.capture = FakeCom(
            {
                3: ((ct.c_void_p,) * 5, self.get_buffer),
                4: ((ct.c_uint32,), self.release_buffer),
                5: ((ct.c_void_p,), self.next_packet),
            }
        )
        self.client = FakeCom(
            {
                3: (
                    (ct.c_int32, ct.c_uint32, ct.c_int64, ct.c_int64, ct.c_void_p, ct.c_void_p),
                    self.initialize_audio,
                ),
                8: ((ct.c_void_p,), self.mix_format),
                10: ((), lambda this: self.note("start")),
                11: ((), lambda this: self.note("stop")),
                14: ((ct.c_void_p, ct.c_void_p), self.get_service),
            }
        )
        self.properties = FakeCom({5: ((ct.c_void_p, ct.c_void_p), self.property_value)})
        self.endpoints = [FakeCom({3: ((ct.c_void_p,), self.flow_getter(flow))}) for flow in (0, 1)]
        self.devices = [self.make_device(flow) for flow in (0, 1)]
        self.collections = [
            FakeCom(
                {
                    3: ((ct.c_void_p,), self.count),
                    4: ((ct.c_uint32, ct.c_void_p), self.item_getter(flow)),
                }
            )
            for flow in (0, 1)
        ]
        self.enumerator = FakeCom(
            {
                3: ((ct.c_int32, ct.c_uint32, ct.c_void_p), self.enum_endpoints),
                4: ((ct.c_int32, ct.c_int32, ct.c_void_p), self.default),
                5: ((ct.c_wchar_p, ct.c_void_p), self.get_device),
            }
        )
        self.ole32 = SimpleNamespace(
            CoInitializeEx=FakeFunction(lambda ptr, flag: self.coresult),
            CoUninitialize=FakeFunction(lambda: self.note("uninitialize")),
            CoCreateInstance=FakeFunction(self.create),
            CoTaskMemFree=FakeFunction(lambda ptr: self.note("free")),
            PropVariantClear=FakeFunction(lambda ptr: self.note("variant_clear")),
        )
        self.kernel32 = SimpleNamespace(
            QueryPerformanceFrequency=FakeFunction(self.frequency),
            QueryPerformanceCounter=FakeFunction(self.counter),
        )

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr(
            sys, "getwindowsversion", lambda: SimpleNamespace(major=10), raising=False
        )
        monkeypatch.setattr(ct, "WinDLL", lambda name, **kw: getattr(self, name), raising=False)

    def note(self, name: str) -> int:
        self.log.append(name)
        return 0

    def allocate(self, buffer: Any) -> int:
        self.buffers.append(buffer)
        value = ct.cast(buffer, ct.c_void_p).value
        assert value is not None
        return value

    def create(self, clsid: Any, outer: Any, context: Any, iid: Any, out: Any) -> int:
        put(out, self.enumerator.pointer.value)
        return self.note("enumerator")

    def frequency(self, out: Any) -> int:
        put(out, 10_000_000, ct.c_int64)
        return int(self.frequency_ok)

    def counter(self, out: Any) -> int:
        put(out, 25_000, ct.c_int64)
        return int(self.counter_ok)

    def enum_endpoints(self, this: Any, flow: int, state: int, out: Any) -> int:
        put(out, self.collections[flow].pointer.value)
        return self.note("enumerate")

    def default(self, this: Any, flow: int, role: int, out: Any) -> int:
        if self.no_default:
            return -2147023728
        put(out, self.devices[flow].pointer.value)
        return 0

    def count(self, this: Any, out: Any) -> int:
        put(out, self.device_count, ct.c_uint32)
        return 0

    def item_getter(self, flow: int) -> Callable[..., int]:
        def item(this: Any, index: int, out: Any) -> int:
            put(out, self.devices[flow].pointer.value)
            return 0

        return item

    def flow_getter(self, flow: int) -> Callable[..., int]:
        def get_flow(this: Any, out: Any) -> int:
            put(out, flow, ct.c_int32)
            return 0

        return get_flow

    def make_device(self, flow: int) -> FakeCom:
        def endpoint(this: Any, iid: Any, out: Any) -> int:
            put(out, self.endpoints[flow].pointer.value)
            return 0

        def identity(this: Any, out: Any) -> int:
            if self.no_identity:
                put(out, None)
                return 0
            put(out, self.allocate(ct.create_unicode_buffer("render" if flow == 0 else "capture")))
            return 0

        def activate(this: Any, iid: Any, context: int, params: Any, out: Any) -> int:
            put(out, self.client.pointer.value)
            return self.note("activate")

        def properties(this: Any, access: int, out: Any) -> int:
            assert access == 0
            put(out, self.properties.pointer.value)
            return 0

        return FakeCom(
            {
                0: ((ct.c_void_p, ct.c_void_p), endpoint),
                3: ((ct.c_void_p, ct.c_uint32, ct.c_void_p, ct.c_void_p), activate),
                4: ((ct.c_uint32, ct.c_void_p), properties),
                5: ((ct.c_void_p,), identity),
            }
        )

    def property_value(self, this: Any, key: Any, out: Any) -> int:
        if self.property_error:
            return self.property_error
        value = ct.cast(out, ct.POINTER(devices._PropVariant)).contents
        value.vt = self.property_kind
        value.value.pointer = self.allocate(ct.create_unicode_buffer("Fake endpoint"))
        return 0

    def get_device(self, this: Any, identity: str, out: Any) -> int:
        put(out, self.devices[0 if identity == "render" else 1].pointer.value)
        return 0

    def mix_format(self, this: Any, out: Any) -> int:
        put(out, None if self.no_mix_format else self.allocate(ct.create_string_buffer(self.raw)))
        return self.note("mix_format")

    def initialize_audio(
        self,
        this: Any,
        mode: int,
        flags: int,
        duration: int,
        periodicity: int,
        format: Any,
        session: Any,
    ) -> int:
        assert mode == 0 and flags in (0, 0x20000)
        assert duration == 1_000_000 and periodicity == 0
        assert ct.string_at(format, len(self.raw)) == self.raw
        return self.note("initialize_audio")

    def get_service(self, this: Any, iid: Any, out: Any) -> int:
        put(out, self.capture.pointer.value)
        return 0

    def next_packet(self, this: Any, out: Any) -> int:
        count = self.packet_frames if self.packets else 0
        put(
            out,
            self.next_frames_override if self.next_frames_override is not None else count,
            ct.c_uint32,
        )
        return 0

    def get_buffer(
        self, this: Any, data: Any, frames: Any, flags: Any, position: Any, qpc: Any
    ) -> int:
        if self.get_buffer_error:
            return self.get_buffer_error
        put(
            data,
            None
            if self.packet_flags & SILENT or self.null_payload
            else self.allocate(ct.create_string_buffer(self.packet_payload)),
        )
        put(frames, self.packet_frames, ct.c_uint32)
        put(flags, self.packet_flags, ct.c_uint32)
        put(position, 480, ct.c_uint64)
        put(qpc, 20_000, ct.c_uint64)
        return self.note("get_buffer")

    def release_buffer(self, this: Any, frames: int) -> int:
        assert frames == self.packet_frames
        self.packets = 0
        return self.note("release_buffer")


def test_fake_native_enumeration_never_activates_audio_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    windows = FakeWindows()
    windows.install(monkeypatch)
    result = devices.list_devices()
    assert result == [
        DeviceInfo("render", "Fake endpoint", "render", True),
        DeviceInfo("capture", "Fake endpoint", "capture", True),
    ]
    assert "activate" not in windows.log and "start" not in windows.log
    assert windows.log.count("variant_clear") == 2
    assert windows.log[-1] == "uninitialize"


@pytest.mark.parametrize("loopback", [False, True])
def test_fake_native_probe_and_capture_slots_preserve_bytes_and_release(
    monkeypatch: pytest.MonkeyPatch,
    loopback: bool,
) -> None:
    windows = FakeWindows()
    windows.install(monkeypatch)
    endpoint = "render" if loopback else "capture"
    assert probe_device(endpoint, loopback=loopback) == AudioFormat(48_000, 2)
    assert "initialize_audio" not in windows.log and "start" not in windows.log
    backend = NativeWasapiBackend()
    backend.initialize()
    try:
        assert backend.probe(endpoint, loopback=loopback).valid_bits == 16
        assert backend.open(endpoint, loopback=loopback).channel_mask == 3
        backend.start()
        packet = backend.read_packet()
        assert packet is not None and packet.payload == windows.packet_payload
        assert packet.qpc_position_100ns == 20_000 and packet.arrival_mono_ns == 2_500_000
        assert backend.read_packet() is None
        backend.stop()
    finally:
        backend.close()
    assert windows.log.count("get_buffer") == windows.log.count("release_buffer") == 1
    assert windows.log[-1] == "uninitialize"


def test_fake_silent_packet_ignores_null_pointer_and_buffer_errors_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    windows = FakeWindows()
    windows.packet_flags = SILENT
    windows.install(monkeypatch)
    backend = NativeWasapiBackend()
    backend.initialize()
    try:
        backend.open("capture", loopback=False)
        backend.start()
        packet = backend.read_packet()
        assert packet is not None and packet.payload is None
        assert windows.log.count("release_buffer") == 1
        windows.packets = 1
        windows.packet_frames = 0xFFFFFFFF
        with pytest.raises(WasapiError, match="PACKET_TOO_LARGE"):
            backend.read_packet()
        assert windows.log.count("release_buffer") == 2
    finally:
        backend.close()


@pytest.mark.parametrize("code", [0x88890004, 0x80070005, 0x88890010, 0x80004005])
def test_hresult_failures_are_safe_codes(code: int) -> None:
    with pytest.raises(WasapiError) as error:
        devices._check(code)
    assert error.value.hresult == code
    assert str(error.value) == error.value.code


def test_wrong_endpoint_flow_and_com_clock_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    windows = FakeWindows()
    windows.install(monkeypatch)
    with pytest.raises(WasapiError, match="INVALID_DEVICE_FLOW"):
        probe_device("render")
    windows.frequency_ok = False
    with pytest.raises(WasapiError, match="CLOCK_UNAVAILABLE"):
        devices.list_devices()
    assert windows.log[-1] == "uninitialize"
    windows.frequency_ok = True
    windows.coresult = 1
    with devices._WinAPI() as api:
        assert api.now_ns() == 2_500_000
        windows.counter_ok = False
        with pytest.raises(WasapiError, match="CLOCK_UNAVAILABLE"):
            api.now_ns()


def test_native_platform_and_null_interface_guards(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(WasapiError, match="UNSUPPORTED_PLATFORM"):
        devices.list_devices()
    with pytest.raises(WasapiError, match="THREAD_VIOLATION"):
        NativeWasapiBackend().read_packet()
    with pytest.raises(WasapiError, match="NULL_INTERFACE"):
        devices._invoke(ct.c_void_p(), 3, ())


@pytest.mark.parametrize("field,value", [("name", ""), ("flow", "other"), ("default", 1)])
def test_device_info_rejects_invalid_display_metadata(field: str, value: Any) -> None:
    values: dict[str, Any] = dict(device_id="device", name="Name", flow="capture", default=False)
    values[field] = value
    with pytest.raises(ValidationError):
        DeviceInfo(**values)


@pytest.mark.parametrize(
    "changes",
    [{"audio_format": None}, {"valid_bits": 0}, {"channel_mask": -1}, {"raw": bytearray()}],
)
def test_native_format_rejects_invalid_precision_and_metadata(changes: dict[str, Any]) -> None:
    values: dict[str, Any] = dict(audio_format=AudioFormat(48_000, 2), valid_bits=16)
    values.update(changes)
    with pytest.raises(ValidationError):
        NativeFormat(**values)
    with pytest.raises(ValidationError):
        NativeFormat(AudioFormat(48_000, 1, "f32le"), 16)


@pytest.mark.parametrize("mutation", ["length", "short_ext", "alignment", "mask", "precision"])
def test_corrupt_wave_format_is_rejected(mutation: str) -> None:
    raw = bytearray(wave_format(extensible=True))
    if mutation == "length":
        struct.pack_into("<H", raw, 16, 21)
    elif mutation == "short_ext":
        raw = bytearray(wave_format())
        struct.pack_into("<H", raw, 0, 0xFFFE)
    elif mutation == "alignment":
        struct.pack_into("<H", raw, 12, 1)
    elif mutation == "mask":
        struct.pack_into("<I", raw, 20, 1)
    else:
        struct.pack_into("<H", raw, 18, 0)
    with pytest.raises(WasapiError, match="UNSUPPORTED_FORMAT"):
        devices._parse_wave_format(bytes(raw))


def test_enumeration_handles_missing_default_and_nonstring_or_unreadable_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    windows = FakeWindows()
    windows.install(monkeypatch)
    windows.no_default = True
    windows.property_kind = 0
    result = devices.list_devices()
    assert [d.name for d in result] == ["render", "capture"]
    assert not any(d.default for d in result)
    windows.property_error = -2147467259
    assert len(devices.list_devices()) == 2
    windows.device_count = 4097
    with pytest.raises(WasapiError, match="DEVICE_LIMIT_EXCEEDED"):
        devices.list_devices()
    windows.device_count = 1
    windows.no_identity = True
    windows.no_default = False
    with pytest.raises(WasapiError, match="INVALID_DEVICE_ID"):
        devices.list_devices()


def test_probe_rejects_missing_or_oversized_format_and_invalid_bool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    windows = FakeWindows()
    windows.install(monkeypatch)
    windows.no_mix_format = True
    with pytest.raises(WasapiError, match="UNSUPPORTED_FORMAT"):
        probe_device("capture")
    windows.no_mix_format = False
    raw = bytearray(wave_format())
    struct.pack_into("<H", raw, 16, 4090)
    windows.raw = bytes(raw)
    with pytest.raises(WasapiError, match="UNSUPPORTED_FORMAT"):
        probe_device("capture")
    with pytest.raises(ValidationError):
        probe_device("capture", loopback=1)  # type: ignore[arg-type]


def test_com_existing_apartment_is_not_uninitialized_by_this_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    windows = FakeWindows()
    windows.install(monkeypatch)
    windows.coresult = -2147417850
    assert len(devices.list_devices()) == 2
    assert "uninitialize" not in windows.log
    monkeypatch.setattr(sys, "getwindowsversion", lambda: SimpleNamespace(major=8), raising=False)
    with pytest.raises(WasapiError, match="UNSUPPORTED_WINDOWS"):
        devices.list_devices()
    empty = FakeCom({})
    with pytest.raises(WasapiError, match="NULL_METHOD"):
        devices._invoke(empty.pointer, 3, ())


@pytest.mark.parametrize("failure", ["unacquired", "null_payload", "zero_frames"])
def test_native_packet_failure_release_rules(monkeypatch: pytest.MonkeyPatch, failure: str) -> None:
    windows = FakeWindows()
    windows.install(monkeypatch)
    backend = NativeWasapiBackend()
    backend.initialize()
    try:
        backend.open("capture", loopback=False)
        with pytest.raises(WasapiError, match="NOT_RUNNING"):
            backend.read_packet()
        backend.start()
        if failure == "unacquired":
            windows.get_buffer_error = -2004287484
            with pytest.raises(WasapiError, match="DEVICE_UNAVAILABLE"):
                backend.read_packet()
            assert "release_buffer" not in windows.log
        elif failure == "null_payload":
            windows.null_payload = True
            with pytest.raises(WasapiError, match="INVALID_PACKET"):
                backend.read_packet()
            assert windows.log.count("release_buffer") == 1
        else:
            windows.packet_frames = 0
            windows.next_frames_override = 1
            assert backend.read_packet() is None
            assert windows.log.count("release_buffer") == 1
    finally:
        backend.close()


def test_start_timeout_cancels_startup_and_closes_before_retry() -> None:
    gate = Event()
    backend = FakeBackend()

    def slow_probe(device_id: str, *, loopback: bool) -> NativeFormat:
        assert gate.wait(3)
        return backend.format

    backend.probe = slow_probe  # type: ignore[method-assign]
    source = WasapiSource("device", backend_factory=lambda: backend, startup_timeout=0.01)
    try:
        with pytest.raises(WasapiError, match="START_TIMEOUT"):
            source.start("s", "t", "e", lambda b: True, lambda event: None)
    finally:
        gate.set()
        source.stop()
    assert "start" not in [name for name, _ in backend.calls]


@pytest.mark.parametrize(
    "mode", ["invalid_packet", "oversized", "invalid_submit", "health", "factory", "stop"]
)
def test_worker_failures_have_safe_codes_and_release(mode: str) -> None:
    backend = FakeBackend()
    if mode == "oversized":
        backend.packets.append(NativePacket(None, 100_000_000, 0, 0, 0, 0))
    elif mode == "invalid_packet":
        backend.packets.append(NativePacket(None, 1, 0, 0, 0, 0))
    else:
        backend.packets.append(NativePacket(b"\0\0", 1, 0, None, None, 0))
    health: list[dict[str, object]] = []
    done = Event()

    def factory() -> FakeBackend:
        if mode == "factory":
            raise RuntimeError("secret sentinel")
        return backend

    def on_health(event: dict[str, object]) -> None:
        if event["event"] == "stopped":
            done.set()
        if mode == "health":
            raise RuntimeError("secret sentinel")
        health.append(event)

    def submit(block: PCMBlock) -> bool:
        return None if mode == "invalid_submit" else True  # type: ignore[return-value]

    if mode == "stop":
        backend.fail = "stop"
    source = WasapiSource("device", backend_factory=factory)
    try:
        try:
            source.start("s", "t", "e", submit, on_health)
        except WasapiError:
            pass
        if mode == "stop":
            with pytest.raises(WasapiError, match="DEVICE_STOP_FAILED"):
                source.stop()
        else:
            assert done.wait(3)
            source.stop()
        assert "secret sentinel" not in str(health)
    finally:
        if source.running:
            try:
                source.stop()
            except WasapiError:
                pass


def test_source_rejects_bad_callbacks_and_double_start() -> None:
    with pytest.raises(ValidationError):
        WasapiSource("device", expected_format="bad")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        WasapiSource("device", backend_factory=1)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        WasapiSource("device", startup_timeout=10**500)
    source = WasapiSource("device", backend_factory=FakeBackend)
    with pytest.raises(ValidationError):
        source.start("s", "t", "e", None, lambda event: None)  # type: ignore[arg-type]
    source.start("s", "t", "e", lambda b: True, lambda event: None)
    try:
        with pytest.raises(WasapiError, match="ALREADY_RUNNING"):
            source.start("s", "t", "e2", lambda b: True, lambda event: None)
    finally:
        source.stop()


def test_qpc_access_rejects_another_thread_before_calling_native_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    windows = FakeWindows()
    windows.install(monkeypatch)
    with devices._WinAPI() as api, ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(api.now_ns)
        with pytest.raises(WasapiError, match="THREAD_VIOLATION"):
            future.result(timeout=3)


def test_idle_status_does_not_invent_silent_packets(monkeypatch: pytest.MonkeyPatch) -> None:
    times = count(0, 2)
    monkeypatch.setattr(wasapi_module, "monotonic", lambda: float(next(times)))
    backend = FakeBackend()
    idle = Event()
    packets: list[PCMBlock] = []
    health: list[dict[str, object]] = []

    def submit(block: PCMBlock) -> bool:
        packets.append(block)
        return True

    def observe(event: dict[str, object]) -> None:
        health.append(event)
        if event["event"] == "idle":
            idle.set()

    source = WasapiSource("device", backend_factory=lambda: backend)
    source.start("s", "t", "e", submit, observe)
    assert idle.wait(3)
    source.stop()
    assert packets == []
    assert {"event": "idle", "code": "NO_PACKETS_UNKNOWN"} in health


def test_stop_called_from_worker_does_not_join_itself() -> None:
    source = WasapiSource("device", backend_factory=FakeBackend)
    errors: list[str] = []

    def observe(event: dict[str, object]) -> None:
        if event["event"] == "ready":
            try:
                source.stop()
            except WasapiError as error:
                errors.append(error.code)

    source.start("s", "t", "e", lambda b: True, observe)
    source.stop()
    assert errors == ["STOP_FROM_CALLBACK"]


@pytest.mark.parametrize("clock,arrival", [(-1, 0), (True, 0), (None, -1)])
def test_packet_clock_boundaries(clock: Any, arrival: Any) -> None:
    with pytest.raises(ValidationError):
        NativePacket(b"\0\0", 1, 0, clock, clock, arrival)


def test_native_release_failure_still_releases_other_interfaces_and_com(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    windows = FakeWindows()
    windows.install(monkeypatch)
    backend = NativeWasapiBackend()
    backend.initialize()
    backend.open("capture", loopback=False)
    original_release = devices._release
    visited: list[int | None] = []

    def failing_release(pointer: ct.c_void_p) -> None:
        visited.append(pointer.value)
        if pointer.value == windows.capture.pointer.value:
            raise WasapiError("NATIVE_CALL_FAILED")
        original_release(pointer)

    monkeypatch.setattr(wasapi_module, "_release", failing_release)
    with pytest.raises(WasapiError, match="NATIVE_CALL_FAILED"):
        backend.close()
    assert len(visited) == 4
    assert windows.log[-1] == "uninitialize"
    backend.close()  # Already released, no second COM uninitialization.
