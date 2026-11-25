"""GS06 input partitions and independent packet/queue oracles; synthetic bytes only."""

from __future__ import annotations

import json
from dataclasses import replace
from itertools import product
from queue import Empty
from threading import Barrier, Thread

import pytest

from recoryn.capture.queue import BoundedCaptureQueue, packet_blocks
from recoryn.capture.wasapi import (
    DATA_DISCONTINUITY,
    SILENT,
    TIMESTAMP_ERROR,
    NativePacket,
    split_packet,
)
from recoryn.domain import AudioFormat, PCMBlock, ValidationError

pytestmark = pytest.mark.unit
FMT = AudioFormat(44100, 1)
FORMATS = (
    FMT,
    AudioFormat(44100, 2),
    AudioFormat(44100, 3, "s24le"),
    AudioFormat(44100, 64, "s24le"),
)
FLAGS = (0, SILENT, DATA_DISCONTINUITY, TIMESTAMP_ERROR, DATA_DISCONTINUITY | 8)
S = list(product(range(4), range(2), range(8), range(5), range(4)))
OVERFLOWS = list(product((False, True), (False, True), (2, 3)))
A = list(product((1, 2, 3), (-1, 0, 1), (-1, 0, 1), (False, True), (False, True)))


def group(count, *, sequence=0, track="mic", epoch="e", session="s", format=FMT):
    return tuple(
        PCMBlock(
            session,
            track,
            epoch,
            sequence,
            format,
            2,
            bytes([1 + (sequence + k) % 250]) * (2 * format.frame_bytes),
            1_000_000 + k * 2_000_000_000 // format.sample_rate,
            2_000_000,
            sequence * count * 2 + k * 2,
            "DEVICE_CORRELATED",
            k,
            count,
        )
        for k in range(count)
    )


def reference(packet, format, limit):
    """Manual frame cursor model; no product fragment/metadata helper is used."""
    width = {("s16le", 1): 2, ("s16le", 2): 4, ("s24le", 3): 9, ("s24le", 64): 192}[
        (format.sample_type, format.channels)
    ]
    capacity = limit // width
    cursor, expected = 0, []
    stamp = (
        None
        if packet.flags & TIMESTAMP_ERROR or packet.qpc_position_100ns is None
        else packet.qpc_position_100ns * 100
    )
    if stamp is not None and stamp >= 2**63:
        stamp = None
    quality = "INVALID" if stamp is None else "DEVICE_CORRELATED"
    packet_flags = []
    for bit, name in ((1, "DATA_DISCONTINUITY"), (2, "SILENT"), (4, "TIMESTAMP_ERROR")):
        if packet.flags & bit:
            packet_flags.append(name)
    if packet.flags & ~7:
        packet_flags.append(f"RAW_FLAGS_{packet.flags & ~7:08X}")
    while cursor < packet.frame_count:
        n = min(capacity, packet.frame_count - cursor)
        pos = (
            None if packet.device_frame_position is None else packet.device_frame_position + cursor
        )
        ns = None if stamp is None else stamp + cursor * 1_000_000_000 // format.sample_rate
        if pos is not None and pos >= 2**63:
            pos = None
        if ns is not None and ns >= 2**63:
            ns = None
        begin = cursor * width
        data = (
            bytes(n * width) if packet.flags & SILENT else packet.payload[begin : begin + n * width]
        )
        flags = tuple(
            packet_flags
            if cursor == 0
            else [v for v in packet_flags if v in ("SILENT", "TIMESTAMP_ERROR")]
        )
        expected.append((n, data, ns, pos, quality, flags))
        cursor += n
    return expected


def test_split_arithmetic_all_1280_rows(request):
    seen = []
    for number, (fi, remainder, ni, flag, clocks) in enumerate(S, 1):
        ident = f"GS06-S-{number:04}"
        seen.append(ident)
        fmt = FORMATS[fi]
        width = (2, 4, 9, 192)[fi]
        assert fmt.frame_bytes == width
        limit = 3 * width + (width - 1 if remainder else 0)
        n = (1, 2, 3, 4, 5, 6, 7, 15)[ni]
        data = bytes((i * 17 + 3) % 256 for i in range(n * width))
        packet = NativePacket(
            data,
            n,
            FLAGS[flag],
            123 if clocks in (0, 1) else None,
            90_071_992_547_410 if clocks in (0, 2) else None,
            8_000_000,
        )
        expected = reference(packet, fmt, limit)
        try:
            actual = split_packet(packet, ("s", "mic", "e"), 7, fmt, max_block_bytes=limit)
        except ValueError as error:
            raise AssertionError((ident, "valid packet was rejected")) from error
        assert len(actual) == len(expected), ident
        for k, (value, oracle) in enumerate(zip(actual, expected, strict=True)):
            assert (
                value.frame_count,
                value.payload,
                value.capture_mono_ns,
                value.device_frame_position,
                value.clock_quality,
                value.flags,
            ) == oracle, (ident, k)
            assert (
                value.session_id,
                value.track_id,
                value.epoch_id,
                value.sequence,
                value.fragment_index,
                value.fragment_count,
            ) == ("s", "mic", "e", 7, k, len(expected)), ident
            assert value.format == fmt and value.arrival_mono_ns == 8_000_000, ident
            assert len(value.payload) <= limit and len(value.payload) % fmt.frame_bytes == 0, ident
        assert b"".join(v.payload for v in actual) == (
            bytes(len(data)) if FLAGS[flag] & SILENT else data
        ), ident
    assert len(seen) == len(set(seen)) == 1280
    request.node.user_properties.append(("gs06_case_ids", json.dumps(seen)))


@pytest.mark.parametrize(
    "pos_over,time_over,count", OVERFLOWS, ids=[f"GS06-O-{i:03}" for i in range(1, 9)]
)
def test_integer_overflow_never_wraps_or_saturates(pos_over, time_over, count):
    fmt = AudioFormat(1000, 1)
    pos = 2**63 - (2 if pos_over else 20)
    qpc = (2**63 - (1000 if time_over else 20_000_000)) // 100
    packet = NativePacket(b"\x12\x34" * (count * 2), count * 2, 0, pos, qpc, 50)
    values = split_packet(packet, ("s", "mic", "e"), 0, fmt, max_block_bytes=4)
    assert [
        (
            v.frame_count,
            v.payload,
            v.capture_mono_ns,
            v.device_frame_position,
            v.clock_quality,
            v.flags,
        )
        for v in values
    ] == reference(packet, fmt, 4)
    assert all(v.clock_quality == "DEVICE_CORRELATED" for v in values)
    assert (values[1].device_frame_position is None) == pos_over
    assert (values[1].capture_mono_ns is None) == time_over


def queue_oracle(prefix, packet, other, byte_capacity, block_capacity, closed, order):
    """Hand ledger of the two permissible producer linearizations."""
    fifo = list(prefix)
    accepted = [
        len(prefix),
        sum(v.frame_count for v in prefix),
        sum(len(v.payload) for v in prefix),
    ]
    dropped = [0, 0, 0]
    remaining_slots = block_capacity - len(prefix)
    remaining_bytes = byte_capacity - accepted[2]
    replies = {}
    for label in order:
        values = packet if label == "packet" else (other,)
        frames, size = sum(v.frame_count for v in values), sum(len(v.payload) for v in values)
        ok = not closed and remaining_slots >= len(values) and remaining_bytes >= size
        replies[label] = ok
        if ok:
            remaining_slots -= len(values)
            remaining_bytes -= size
            fifo.extend(values)
        if not closed:
            account = accepted if ok else dropped
            for i, n in enumerate((len(values), frames, size)):
                account[i] += n
    return replies, fifo, accepted, dropped


@pytest.mark.parametrize(
    "count,byte_delta,slot_delta,closed,concurrent",
    A,
    ids=[f"GS06-A-{i:03}" for i in range(1, 109)],
)
def test_packet_offer_matches_a_whole_linearized_hand_ledger(
    count, byte_delta, slot_delta, closed, concurrent
):
    packet = group(count)
    prefix = [group(1, sequence=i, track="old")[0] for i in range(3 - slot_delta)]
    other = group(1, track="system")[0]
    size = sum(len(v.payload) for v in packet)
    slots = len(prefix) + count + slot_delta
    capacity = sum(len(v.payload) for v in prefix) + size + byte_delta
    pending = BoundedCaptureQueue(slots, capacity)
    for value in prefix:
        assert pending.offer(value)
    if closed:
        pending.close()
    replies, errors = {}, []
    barrier = Barrier(2)

    def producer(label):
        try:
            barrier.wait(3)
            replies[label] = (
                pending.offer_packet(packet) if label == "packet" else pending.offer(other)
            )
        except BaseException as error:
            errors.append(error)

    if concurrent:
        workers = [Thread(target=producer, args=(label,)) for label in ("packet", "other")]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(5)
            assert not worker.is_alive()
        assert not errors
    else:
        replies["packet"] = pending.offer_packet(packet)
    observed = []
    while True:
        try:
            observed.append(pending.get(0))
        except (Empty, EOFError):
            break
    snapshot = pending.snapshot()
    actual = (
        replies,
        observed,
        [snapshot[k] for k in ("accepted_blocks", "accepted_frames", "accepted_bytes")],
        [snapshot[k] for k in ("dropped_blocks", "dropped_frames", "dropped_bytes")],
    )
    orders = (("packet", "other"), ("other", "packet")) if concurrent else (("packet",),)
    assert any(
        actual == queue_oracle(prefix, packet, other, capacity, slots, closed, order)
        for order in orders
    )
    assert snapshot["queued_blocks"] == snapshot["queued_bytes"] == 0


@pytest.mark.parametrize("number", range(1, 13), ids=[f"GS06-T-{i:03}" for i in range(1, 13)])
def test_invalid_input_groups_have_no_queue_side_effect(number):
    packet = NativePacket(b"\x12\x34" * 2, 2, 0, 0, 100, 1000)
    if number <= 5:
        if number <= 3:
            with pytest.raises(ValidationError):
                split_packet(
                    packet, ("s", "mic", "e"), 0, FMT, max_block_bytes=(1, True, 1.5)[number - 1]
                )
        elif number == 4:
            from recoryn.capture.devices import WasapiError

            with pytest.raises(WasapiError, match="INVALID_PACKET"):
                split_packet(replace(packet, payload=b"bad"), ("s", "mic", "e"), 0, FMT)
        else:
            with pytest.raises(ValidationError):
                replace(packet, frame_count=0)
        return
    values = group(3)
    variants = {
        6: [()],
        7: [(values[0],)],
        8: [(values[0], replace(values[1], sequence=1), values[2])],
        9: [(values[0], replace(values[1], fragment_index=i), values[2]) for i in (0, 2)],
        10: [
            (values[0], replace(values[1], **change), values[2])
            for change in (
                {"session_id": "other"},
                {"track_id": "other"},
                {"epoch_id": "other"},
                {"format": AudioFormat(22050, 1)},
            )
        ],
        11: [(values[0], "not PCM", values[2]), ("not PCM", values[1], values[2])],
        12: [(values[0], replace(values[1], fragment_count=4), values[2])],
    }[number]
    pending = BoundedCaptureQueue(20, 1000)
    before = pending.snapshot()
    for variant in variants:
        with pytest.raises(ValidationError):
            packet_blocks(variant)
        if number != 7:
            with pytest.raises(ValidationError):
                pending.offer_packet(variant)
        assert pending.snapshot() == before


def test_GS06_X003_unrepresentable_base_clock_stays_unknown():
    packet = NativePacket(b"\x12\x34" * 5, 5, 0, None, 2**63 - 1, 1000)
    values = split_packet(packet, ("s", "mic", "e"), 0, FMT, max_block_bytes=4)
    assert len(values) == 3
    assert all(v.capture_mono_ns is None and v.clock_quality == "INVALID" for v in values)
    assert b"".join(v.payload for v in values) == packet.payload
