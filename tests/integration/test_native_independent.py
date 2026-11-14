"""BR11 independent oracles. Native DLLs/capture are forbidden, including on Windows."""

from __future__ import annotations

import ctypes as ct
import math
import random
import struct
from collections import deque
from collections.abc import Callable
from dataclasses import replace
from fractions import Fraction
from threading import Event, get_ident
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from recoryn.audio import (
    align_blocks,
    decode_pcm,
    downmix_mono,
    encode_pcm,
    energy_vad,
    estimate_drift,
    measure_level,
    resample_linear,
)
from recoryn.capture import devices, wasapi
from recoryn.capture.devices import NativeFormat, WasapiError
from recoryn.capture.wasapi import NativePacket, NativeWasapiBackend, WasapiSource
from recoryn.domain import AudioFormat, PCMBlock, ValidationError

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def forbid_system_dlls(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("BR11 forbids actual DLL/device/capture access")

    monkeypatch.setattr(ct, "WinDLL", forbidden, raising=False)


def native_format() -> NativeFormat:
    # Hand-built 24 valid bits in 32-bit stereo containers, FL/FR speaker mask.
    raw = struct.pack("<HHIIHHHHI", 0xFFFE, 2, 48_000, 384_000, 8, 32, 22, 24, 3)
    raw += UUID("00000001-0000-0010-8000-00aa00389b71").bytes_le
    return devices._parse_wave_format(raw)


class MemoryCom:
    """Independent SDK slot layout; only owned Python allocations are invoked."""

    def __init__(self, count: int) -> None:
        self.table = (ct.c_void_p * count)()
        self.table_address = ct.c_void_p(ct.addressof(self.table))
        self.interface = ct.pointer(self.table_address)
        self.pointer = ct.cast(self.interface, ct.c_void_p)
        self.callbacks: list[Any] = []

    def slot(self, index: int, args: tuple[Any, ...], callback: Callable[..., int]) -> None:
        convention = getattr(ct, "WINFUNCTYPE", ct.CFUNCTYPE)
        function = convention(ct.c_int32, ct.c_void_p, *args)(callback)
        self.callbacks.append(function)
        self.table[index] = ct.cast(function, ct.c_void_p).value


@pytest.mark.parametrize("loopback", [False, True])
def test_sdk_slots_64bit_positions_copy_before_release_and_thread_lifetime(
    monkeypatch: pytest.MonkeyPatch, loopback: bool
) -> None:
    log: list[tuple[str, int]] = []
    init_args: list[tuple[int, int, int, int, bytes, object]] = []
    released: list[int] = []
    fmt = native_format()
    original = struct.pack("<ii", -(2**31), 2**31 - 256)
    payload = ct.create_string_buffer(original)
    capture, client, device, enumerator = [MemoryCom(n) for n in (6, 15, 3, 3)]

    def note(name: str) -> int:
        log.append((name, get_ident()))
        return 0

    def initialize(
        this: object,
        share: int,
        flags: int,
        duration: int,
        period: int,
        raw: int,
        session: object,
    ) -> int:
        init_args.append((share, flags, duration, period, ct.string_at(raw, 40), session))
        return note("initialize_stream")

    def service(this: object, iid: int, output: int) -> int:
        assert ct.string_at(iid, 16) == UUID("c8adbd64-e71e-48a0-a4de-185c395cd317").bytes_le
        ct.cast(output, ct.POINTER(ct.c_void_p))[0] = capture.pointer
        return note("get_service")

    def next_size(this: object, output: int) -> int:
        ct.cast(output, ct.POINTER(ct.c_uint32))[0] = 1
        return note("next")

    def get_buffer(this: object, data: int, frames: int, flags: int, pos: int, qpc: int) -> int:
        ct.cast(data, ct.POINTER(ct.c_void_p))[0] = ct.cast(payload, ct.c_void_p)
        ct.cast(frames, ct.POINTER(ct.c_uint32))[0] = 1
        ct.cast(flags, ct.POINTER(ct.c_uint32))[0] = 0
        ct.cast(pos, ct.POINTER(ct.c_uint64))[0] = 2**40 + 3
        ct.cast(qpc, ct.POINTER(ct.c_uint64))[0] = 2**45 + 9
        return note("get")

    def release_buffer(this: object, frames: int) -> int:
        released.append(frames)
        ct.memset(payload, 0xCC, len(original))
        return note("release_buffer")

    for obj, name in (
        (capture, "capture"),
        (client, "client"),
        (device, "device"),
        (enumerator, "enumerator"),
    ):
        obj.slot(2, (), lambda this, name=name: note("release_" + name))
    client.slot(
        3, (ct.c_int32, ct.c_uint32, ct.c_int64, ct.c_int64, ct.c_void_p, ct.c_void_p), initialize
    )
    client.slot(10, (), lambda this: note("start"))
    client.slot(11, (), lambda this: note("stop"))
    client.slot(14, (ct.c_void_p, ct.c_void_p), service)
    capture.slot(3, (ct.c_void_p,) * 5, get_buffer)
    capture.slot(4, (ct.c_uint32,), release_buffer)
    capture.slot(5, (ct.c_void_p,), next_size)

    class Api:
        def __enter__(self) -> Api:
            note("com_enter")
            return self

        def __exit__(self) -> None:
            note("com_exit")

        def enumerator(self) -> ct.c_void_p:
            return ct.c_void_p(enumerator.pointer.value)

        def now_ns(self) -> int:
            return 2**55 + 7

    monkeypatch.setattr(wasapi, "_WinAPI", Api)
    monkeypatch.setattr(wasapi, "_get_device", lambda *args: ct.c_void_p(device.pointer.value))
    monkeypatch.setattr(
        wasapi, "_activate_client", lambda *args, **kw: ct.c_void_p(client.pointer.value)
    )
    monkeypatch.setattr(wasapi, "_mix_format", lambda *args: fmt)
    backend = NativeWasapiBackend()
    backend.initialize()
    try:
        assert backend.open("fake", loopback=loopback) == fmt
        backend.start()
        packet = backend.read_packet()
        assert packet is not None
        assert packet.payload == original and bytes(payload)[:8] != original
        assert packet.device_frame_position == 2**40 + 3
        assert packet.qpc_position_100ns == 2**45 + 9
        assert packet.arrival_mono_ns == 2**55 + 7
        assert released == [1]
        assert init_args == [(0, 0x20000 if loopback else 0, 1_000_000, 0, fmt.raw, None)]
    finally:
        backend.close()
    assert [name for name, _ in log][-6:] == [
        "stop",
        "release_capture",
        "release_client",
        "release_device",
        "release_enumerator",
        "com_exit",
    ]
    assert {thread for _, thread in log} == {get_ident()}


@pytest.mark.parametrize("ticks,frequency", [(1234567890123, 3579545), (2**52 + 7, 10_000_000)])
def test_arrival_clock_integer_conversion_has_no_float_origin_loss(
    ticks: int, frequency: int
) -> None:
    def counter(output: Any) -> int:
        ct.cast(output, ct.POINTER(ct.c_int64))[0] = ticks
        return 1

    api = devices._WinAPI()
    api._owner, api._frequency = get_ident(), frequency
    api.kernel32 = SimpleNamespace(QueryPerformanceCounter=counter)
    assert api.now_ns() == int(Fraction(ticks * 10**9, frequency))


class ScriptBackend:
    def __init__(self, packets: list[NativePacket]) -> None:
        self.packets = deque(packets)
        self.calls: list[tuple[str, int]] = []
        self.read_entered, self.read_gate = Event(), Event()
        self.read_gate.set()
        self.close_entered, self.close_gate = Event(), Event()
        self.close_gate.set()
        self.error: WasapiError | None = None
        self.format = NativeFormat(AudioFormat(48_000, 1), 16)

    def note(self, name: str) -> None:
        self.calls.append((name, get_ident()))

    def initialize(self) -> None:
        self.note("initialize")

    def probe(self, device_id: str, *, loopback: bool) -> NativeFormat:
        self.note("probe")
        return self.format

    def open(self, device_id: str, *, loopback: bool) -> NativeFormat:
        self.note("open")
        return self.format

    def start(self) -> None:
        self.note("start")

    def read_packet(self) -> NativePacket | None:
        self.note("read")
        self.read_entered.set()
        assert self.read_gate.wait(3)
        if self.error:
            raise self.error
        return self.packets.popleft() if self.packets else None

    def stop(self) -> None:
        self.note("stop")

    def close(self) -> None:
        self.close_entered.set()
        assert self.close_gate.wait(3)
        self.note("close")


def test_worker_packet_clock_flags_silence_and_ack_oracle() -> None:
    backend = ScriptBackend(
        [
            NativePacket(b"\x00\x80", 1, 0, 2**35, 90_001, 9_999_999),
            NativePacket(b"ignored", 2, 2 | 4 | 32, 2**35 + 1, 90_002, 10_000_000),
        ]
    )
    blocks: list[PCMBlock] = []
    health: list[dict[str, object]] = []
    done = Event()

    def submit(block: PCMBlock) -> bool:
        blocks.append(block)
        return True

    def observe(event: dict[str, object]) -> None:
        health.append(event)
        if event.get("event") == "packet" and event["sequence"] == 1:
            done.set()

    source = WasapiSource("fake", backend_factory=lambda: backend)
    source.start("s", "t", "e", submit, observe)
    try:
        assert done.wait(3)
    finally:
        source.stop()
    assert blocks[0].capture_mono_ns == 9_000_100
    assert blocks[0].capture_mono_ns != blocks[0].arrival_mono_ns
    assert blocks[1].capture_mono_ns is None and blocks[1].payload == b"\0" * 4
    assert set(blocks[1].flags) == {"SILENT", "TIMESTAMP_ERROR", "RAW_FLAGS_00000020"}
    assert align_blocks(blocks)[1].start_ns is None
    assert health[-1]["release_ack"] is True and not source.running
    assert len({thread for _, thread in backend.calls}) == 1
    assert backend.calls[0][1] != get_ident()


def test_stop_timeout_does_not_submit_late_packet_or_ack_release() -> None:
    backend = ScriptBackend([NativePacket(b"\0\0", 1, 0, 0, 10, 1100)])
    backend.read_gate.clear()
    backend.close_gate.clear()
    received: list[PCMBlock] = []
    health: list[dict[str, object]] = []

    def submit(block: PCMBlock) -> bool:
        received.append(block)
        return True

    source = WasapiSource("fake", backend_factory=lambda: backend)
    source.start("s", "t", "e", submit, health.append)
    try:
        assert backend.read_entered.wait(3)
        with pytest.raises(WasapiError, match="STOP_TIMEOUT"):
            source.stop(0)
        assert source.running and all(event["event"] != "stopped" for event in health)
        backend.read_gate.set()
        assert backend.close_entered.wait(3)
        with pytest.raises(WasapiError, match="STOP_TIMEOUT"):
            source.stop(0)
        assert received == [] and all(event["event"] != "stopped" for event in health)
    finally:
        backend.read_gate.set()
        backend.close_gate.set()
        source.stop()
    assert health[-1]["release_ack"] is True


@pytest.mark.parametrize("code", ["DEVICE_UNAVAILABLE", "NATIVE_CALL_FAILED"])
def test_disconnect_or_suspend_failure_stops_without_endpoint_replacement(code: str) -> None:
    backend = ScriptBackend([])
    backend.read_gate.clear()
    health: list[dict[str, object]] = []
    failed = Event()

    def observe(event: dict[str, object]) -> None:
        health.append(event)
        if event["event"] == "error":
            failed.set()

    source = WasapiSource("fake", backend_factory=lambda: backend)
    source.start("s", "t", "e", lambda block: True, observe)
    try:
        assert backend.read_entered.wait(3)
        backend.error = WasapiError(code)
        backend.read_gate.set()
        assert failed.wait(3)
    finally:
        backend.read_gate.set()
        source.stop()
    assert {"event": "error", "code": code} in health
    assert [name for name, _ in backend.calls].count("open") == 1
    with pytest.raises(WasapiError, match="EPOCH_REUSE"):
        source.start("s", "t", "e", lambda block: True, observe)


def clock_block(i: int, *, time_ns: int | None = None) -> PCMBlock:
    return PCMBlock(
        "s",
        "t",
        "e",
        i,
        AudioFormat(48_000, 1),
        480,
        bytes(960),
        10**9 + i * 10_000_000 if time_ns is None else time_ns,
        10**15,
        i * 480,
    )


@pytest.mark.parametrize(
    "change",
    [
        {"device_frame_position": 0},
        {"capture_mono_ns": 900_000_000},
        {"sequence": 4},
        {"epoch_id": "e2"},
        {"flags": ("DATA_DISCONTINUITY",)},
    ],
)
def test_clock_reset_drop_and_epoch_are_not_fit_across(change: dict[str, Any]) -> None:
    blocks = [clock_block(0), replace(clock_block(1), **change)]
    with pytest.raises(ValidationError):
        estimate_drift(blocks)
    assert len({span.segment for span in align_blocks(blocks)}) == 2


def test_drift_oracle_separate_tracks_and_source_values_unchanged() -> None:
    # Exactly 100 ppm slower sample clock, against a very large host clock origin.
    anchor = 8_000_000_000_000_000
    blocks = [clock_block(i, time_ns=anchor + i * 10_001_000) for i in range(5)]
    before = tuple(block.to_metadata() for block in blocks)
    estimate = estimate_drift(blocks)
    assert estimate.ns_per_frame == pytest.approx(Fraction(10_001_000, 480))
    assert estimate.drift_ppm == pytest.approx(float(Fraction(-1_000_000, 10_001)))
    assert estimate.residual_ns == 0
    other = replace(blocks[0], track_id="loopback", capture_mono_ns=anchor + 7_000_000)
    spans = align_blocks([*blocks, other], origin_ns=anchor)
    assert spans[-1].start_ns == 7_000_000
    assert spans[-1].segment != spans[0].segment
    assert tuple(block.to_metadata() for block in blocks) == before


def test_br11_01_forward_clock_jump_cannot_be_hidden_as_correlated_drift() -> None:
    # Simulated resume/clock fault: contiguous frame positions, 60s host-clock gap.
    # Independent oracle: no piece of 480 frames may silently become 30 seconds.
    blocks = [clock_block(0), clock_block(1), clock_block(2, time_ns=61_020_000_000)]
    spans = align_blocks(blocks, origin_ns=10**9)
    assert len({span.segment for span in spans}) >= 2, spans
    assert spans[0].start_ns == 0 and spans[1].end_ns == 20_000_000
    assert spans[2].start_ns == 60_020_000_000
    assert spans[2].quality == "UNCERTAIN_CLOCK" and spans[2].drift_ppm is None
    for span in spans:
        if span.start_ns is not None and span.end_ns is not None:
            assert 0 <= span.start_ns < span.end_ns
            assert span.end_ns - span.start_ns < 20_000_000


@pytest.mark.parametrize("jump_ns", [250_000_000, 60_000_000_000])
def test_br11_recheck_two_point_zero_residual_jump_and_epoch_taint(jump_ns: int) -> None:
    blocks = [clock_block(0), clock_block(1, time_ns=1_010_000_000 + jump_ns)]
    with pytest.raises(ValidationError):
        estimate_drift(blocks)  # Two points have zero fit residual, yet an invalid rate.
    blocks.extend(
        [
            replace(clock_block(2), capture_mono_ns=None),
            clock_block(3, time_ns=1_030_000_000 + jump_ns),
            replace(clock_block(0), epoch_id="new_epoch"),
        ]
    )
    before = [block.to_metadata() for block in blocks]
    spans = align_blocks(blocks, origin_ns=10**9)
    assert spans[1].start_ns == 10_000_000 + jump_ns
    assert [span.quality for span in spans] == [
        "DEVICE_CORRELATED",
        "UNCERTAIN_CLOCK",
        "UNKNOWN",
        "UNCERTAIN_CLOCK",
        "DEVICE_CORRELATED",
    ]
    assert [block.to_metadata() for block in blocks] == before


@pytest.mark.parametrize("step_ns", [9_995_000, 10_003_000])
def test_br11_recheck_hundreds_ppm_remains_correlated(step_ns: int) -> None:
    blocks = [clock_block(i, time_ns=10**9 + i * step_ns) for i in range(10)]
    estimate = estimate_drift(blocks)
    assert estimate.drift_ppm == pytest.approx((10_000_000 / step_ns - 1) * 10**6)
    spans = align_blocks(blocks, origin_ns=10**9)
    assert {span.quality for span in spans} == {"DEVICE_CORRELATED"}
    assert len({span.segment for span in spans}) == 1
    assert spans[-1].start_ns == 9 * step_ns


def test_br11_recheck_global_bad_fit_cannot_hide_residual_with_valid_local_steps() -> None:
    # A 0.5% local rate change at halfway cannot share one trustworthy affine fit.
    stamps = [10**9]
    for i in range(400):
        stamps.append(stamps[-1] + (10_050_000 if i < 200 else 9_950_000))
    blocks = [clock_block(i, time_ns=stamp) for i, stamp in enumerate(stamps)]
    with pytest.raises(ValidationError):
        estimate_drift(blocks)
    spans = align_blocks(blocks, origin_ns=10**9)
    assert {span.quality for span in spans} == {"UNCERTAIN_CLOCK"}
    for span, stamp in zip(spans, stamps, strict=True):
        assert span.start_ns == stamp - 10**9
        assert span.end_ns == stamp - 10**9 + 10_000_000
        assert span.drift_ppm is None


@pytest.mark.parametrize("sample,width", [("s16le", 2), ("s24le", 3), ("s32le", 4)])
def test_integer_pcm_independent_bit_oracle_and_source_immutability(
    sample: str, width: int
) -> None:
    generator = random.Random(20261114)
    low, high = -(1 << (width * 8 - 1)), (1 << (width * 8 - 1)) - 1
    values = [low, high, -1, 0, 1] + [generator.randint(low, high) for _ in range(95)]
    payload = b"".join(value.to_bytes(width, "little", signed=True) for value in values)
    source_hash = __import__("hashlib").sha256(payload).hexdigest()
    fmt = AudioFormat(44_100, 2, sample)
    decoded = decode_pcm(payload, fmt)
    assert [sample for row in decoded for sample in row] == [
        float(Fraction(value, 1 << (width * 8 - 1))) for value in values
    ]
    assert encode_pcm(decoded, fmt) == payload
    assert __import__("hashlib").sha256(payload).hexdigest() == source_hash


def test_float_boundary_vad_antiphase_and_meter_source_immutability() -> None:
    frames = [(0.0, 0.0)] * 40 + [(0.5, -0.5)] * 80 + [(0.0, 0.0)] * 40
    fmt = AudioFormat(1000, 2, "f32le")
    payload = struct.pack("<" + "ff" * len(frames), *(x for row in frames for x in row))
    block = PCMBlock("s", "t", "e", 0, fmt, 160, payload, 0, 0, 0)
    assert downmix_mono(decode_pcm(payload, fmt)) == (0.0,) * 160
    regions = energy_vad(block, window_ms=20, min_speech_ms=40, padding_ms=0)
    assert [(region.start_frame, region.end_frame) for region in regions] == [(40, 120)]
    assert block.payload == payload and encode_pcm(decode_pcm(payload, fmt), fmt) == payload
    assert measure_level([0.5, -0.5]).rms_dbfs == pytest.approx(20 * math.log10(0.5))
    assert decode_pcm(struct.pack("<f", 1.25), AudioFormat(1, 1, "f32le")) == ((1.25,),)
    for invalid in (float("nan"), float("inf"), -float("inf")):
        with pytest.raises(ValidationError):
            decode_pcm(struct.pack("<f", invalid), AudioFormat(1, 1, "f32le"))


@pytest.mark.parametrize("source_rate,target_rate", [(3, 7), (7, 3), (48_000, 16_000)])
def test_resampling_count_and_linear_rational_oracle(source_rate: int, target_rate: int) -> None:
    source = (0.0, 0.25, 0.5, 0.75)
    count = math.ceil(Fraction(len(source) * target_rate, source_rate))
    expected = [
        float(min(Fraction(index * source_rate, target_rate * 4), Fraction(3, 4)))
        for index in range(count)
    ]
    assert resample_linear(source, source_rate, target_rate) == pytest.approx(expected)
    assert source == (0.0, 0.25, 0.5, 0.75)


@pytest.mark.parametrize("value", [True, False, 0, -1, 1.5])
def test_pcm_processing_integer_boundaries(value: Any) -> None:
    with pytest.raises(ValidationError):
        resample_linear([0.0], value, 48_000)
