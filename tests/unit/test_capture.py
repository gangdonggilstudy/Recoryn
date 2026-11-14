"""Capture contracts using hand-checkable PCM and controlled thread races."""

from collections.abc import Callable
from queue import Empty
from struct import unpack
from threading import Barrier, Event, Thread, get_ident
from typing import Any, cast

import pytest

from recoryn.capture import BoundedCaptureQueue, SyntheticSource
from recoryn.domain import AudioFormat, PCMBlock, ValidationError

pytestmark = pytest.mark.unit


def block(sequence: int = 0, frames: int = 1, channels: int = 1) -> PCMBlock:
    return PCMBlock(
        session_id="session",
        track_id="mic",
        epoch_id="epoch",
        sequence=sequence,
        format=AudioFormat(48_000, channels),
        frame_count=frames,
        payload=bytes([sequence % 256]) * (frames * channels * 2),
        capture_mono_ns=sequence * 10_000_000,
        arrival_mono_ns=sequence * 10_000_000,
        device_frame_position=sequence * frames,
    )


def join(thread: Thread) -> None:
    thread.join(timeout=3)
    assert not thread.is_alive(), "capture operation did not finish"


@pytest.mark.parametrize("bad", [0, -1, True, 1.5, "2", None])
@pytest.mark.parametrize("argument", ["max_blocks", "max_bytes"])
def test_queue_requires_positive_integer_bounds(argument: str, bad: Any) -> None:
    values = {"max_blocks": 2, "max_bytes": 8}
    values[argument] = bad
    with pytest.raises(ValidationError):
        BoundedCaptureQueue(**values)


def test_slot_bound_drops_newest_and_preserves_fifo() -> None:
    queue = BoundedCaptureQueue(max_blocks=2, max_bytes=100)
    first, second, newest = block(0, 2), block(1, 3), block(2, 7)
    assert queue.offer(first)
    assert queue.offer(second)
    assert not queue.offer(newest)
    assert queue.get(timeout=0) is first
    assert queue.get(timeout=0) is second
    stats = queue.snapshot()
    assert stats["accepted_blocks"] == 2
    assert stats["accepted_frames"] == 5
    assert stats["accepted_bytes"] == 10
    assert stats["dropped_blocks"] == 1
    assert stats["dropped_frames"] == 7
    assert stats["dropped_bytes"] == 14
    assert stats["high_water_blocks"] == 2
    assert stats["high_water_bytes"] == 10
    assert stats["queued_blocks"] == stats["queued_bytes"] == 0


def test_byte_bound_accepts_exact_capacity_and_reuses_freed_bytes() -> None:
    queue = BoundedCaptureQueue(max_blocks=10, max_bytes=6)
    first, too_large, exact = block(0, 2), block(1, 2), block(2)
    assert queue.offer(first)
    assert not queue.offer(too_large)
    assert queue.offer(exact)
    assert queue.snapshot()["queued_bytes"] == 6
    assert queue.get(timeout=0) is first
    assert queue.offer(too_large)
    assert queue.get(timeout=0) is exact
    assert queue.get(timeout=0) is too_large
    assert queue.snapshot()["accepted_frames"] == 5
    assert queue.snapshot()["dropped_frames"] == 2
    assert queue.snapshot()["high_water_bytes"] == 6


def test_oversized_block_does_not_evict_or_overfill() -> None:
    queue = BoundedCaptureQueue(2, 4)
    assert not queue.offer(block(frames=3))
    assert queue.snapshot()["queued_blocks"] == 0
    assert queue.snapshot()["dropped_frames"] == 3
    assert queue.snapshot()["dropped_bytes"] == 6
    with pytest.raises(Empty):
        queue.get(timeout=0)


def test_close_full_queue_is_idempotent_and_drains_without_sentinel() -> None:
    queue = BoundedCaptureQueue(1, 2)
    accepted = block()
    assert queue.offer(accepted)
    queue.close()
    queue.close()
    before = queue.snapshot()
    assert not queue.offer(block(1, 99))
    assert queue.snapshot() == before  # Privacy rejection is not queue loss.
    assert queue.get() is accepted
    for _ in range(2):
        with pytest.raises(EOFError):
            queue.get(timeout=0)
    assert queue.snapshot()["closed"] is True
    assert queue.snapshot()["accepted_frames"] == 1
    assert queue.snapshot()["dropped_frames"] == 0


def test_snapshot_is_detached_from_queue_state() -> None:
    queue = BoundedCaptureQueue(1, 2)
    first = queue.snapshot()
    first["closed"] = True
    first["accepted_frames"] = 999
    assert queue.offer(block())
    assert first["queued_blocks"] == 0
    assert queue.snapshot()["accepted_frames"] == 1


@pytest.mark.parametrize("timeout", [0, 0.001])
def test_empty_open_queue_raises_empty_at_deadline(timeout: float) -> None:
    queue = BoundedCaptureQueue(1, 2)
    with pytest.raises(Empty):
        queue.get(timeout=timeout)
    assert queue.snapshot()["closed"] is False


@pytest.mark.parametrize("timeout", [-1, float("nan"), float("inf"), True, "1", 10**500])
def test_invalid_get_timeout(timeout: Any) -> None:
    with pytest.raises(ValidationError):
        BoundedCaptureQueue(1, 2).get(timeout=timeout)


def test_offer_rejects_non_block() -> None:
    with pytest.raises(ValidationError):
        BoundedCaptureQueue(1, 2).offer(cast(PCMBlock, object()))


def test_close_wakes_all_readers_without_capacity(monkeypatch: pytest.MonkeyPatch) -> None:
    queue = BoundedCaptureQueue(1, 2)
    ready = Barrier(5)
    results: list[str] = []
    all_waiting = Event()
    waiting_readers: set[int] = set()
    original_wait = queue._condition.wait

    def observed_wait(timeout: float | None = None) -> bool:
        # Scheduling instrumentation: close can acquire the queue lock only
        # after the last reader enters the real Condition.wait and releases it.
        waiting_readers.add(get_ident())
        if len(waiting_readers) == 4:
            all_waiting.set()
        return original_wait(timeout)

    monkeypatch.setattr(queue._condition, "wait", observed_wait)

    def reader() -> None:
        ready.wait(timeout=3)
        try:
            queue.get()
        except EOFError:
            results.append("closed")

    readers = [Thread(target=reader, daemon=True) for _ in range(4)]
    for thread in readers:
        thread.start()
    ready.wait(timeout=3)
    assert all_waiting.wait(timeout=3)
    queue.close()
    for thread in readers:
        join(thread)
    assert results == ["closed"] * 4


def test_waiting_reader_receives_offered_data() -> None:
    queue = BoundedCaptureQueue(1, 2)
    ready = Event()
    received: list[PCMBlock] = []

    def reader() -> None:
        ready.set()
        received.append(queue.get(timeout=2))

    thread = Thread(target=reader, daemon=True)
    thread.start()
    assert ready.wait(timeout=3)
    offered = block()
    assert queue.offer(offered)
    join(thread)
    assert received == [offered]


@pytest.mark.parametrize("prefilled", [False, True])
def test_close_offer_race_has_linearizable_accounting(prefilled: bool) -> None:
    # Either lock acquisition order is valid; no timing/scheduling order assumed.
    def producer(
        ready: Barrier, queue: BoundedCaptureQueue, racing: PCMBlock, outcome: list[bool]
    ) -> None:
        ready.wait(timeout=3)
        outcome.append(queue.offer(racing))

    for _ in range(40):
        queue = BoundedCaptureQueue(1, 2)
        initial, racing = block(), block(1)
        if prefilled:
            assert queue.offer(initial)
        ready = Barrier(2)
        outcome: list[bool] = []

        thread = Thread(target=producer, args=(ready, queue, racing, outcome), daemon=True)
        thread.start()
        ready.wait(timeout=3)
        queue.close()
        join(thread)
        stats = queue.snapshot()
        if prefilled:
            assert outcome == [False]
            assert queue.get() is initial
            assert stats["accepted_frames"] == 1
            assert stats["dropped_frames"] in (0, 1)
            assert stats["dropped_bytes"] == stats["dropped_frames"] * 2
        else:
            assert stats["dropped_frames"] == 0
            assert stats["accepted_frames"] == int(outcome[0])
            if outcome[0]:
                assert queue.get() is racing
        with pytest.raises(EOFError):
            queue.get()
        closed_stats = queue.snapshot()
        assert not queue.offer(block(2, 3))
        assert queue.snapshot() == closed_stats


def test_concurrent_producer_consumer_accounts_for_variable_frames() -> None:
    queue = BoundedCaptureQueue(3, 24)
    offered = [block(index, index % 5 + 1) for index in range(200)]
    accepted: list[PCMBlock] = []
    dropped: list[PCMBlock] = []
    drained: list[PCMBlock] = []
    ready = Barrier(3)

    def producer() -> None:
        ready.wait(timeout=3)
        for candidate in offered:
            (accepted if queue.offer(candidate) else dropped).append(candidate)
        queue.close()

    def consumer() -> None:
        ready.wait(timeout=3)
        while True:
            try:
                drained.append(queue.get())
            except EOFError:
                return

    threads = [Thread(target=producer, daemon=True), Thread(target=consumer, daemon=True)]
    for thread in threads:
        thread.start()
    ready.wait(timeout=3)
    for thread in threads:
        join(thread)
    assert drained == accepted
    stats = queue.snapshot()
    assert stats["accepted_frames"] == sum(item.frame_count for item in accepted)
    assert stats["dropped_frames"] == sum(item.frame_count for item in dropped)
    assert stats["accepted_bytes"] + stats["dropped_bytes"] == 1200
    assert stats["accepted_frames"] + stats["dropped_frames"] == 600
    assert stats["queued_blocks"] == stats["queued_bytes"] == 0
    assert stats["high_water_blocks"] <= 3
    assert stats["high_water_bytes"] <= 24


@pytest.mark.parametrize("sample_type", ["s16le", "s24le", "s32le", "f32le"])
@pytest.mark.parametrize("channels", [1, 2, 6])
def test_source_preserves_format_and_is_repeatable(sample_type: str, channels: int) -> None:
    audio_format = AudioFormat(48_000, channels, sample_type)
    source = SyntheticSource("session", "system", "epoch", audio_format, 1003)
    blocks = list(source)
    assert blocks == list(source)
    assert [item.frame_count for item in blocks] == [480, 480, 43]
    assert [item.sequence for item in blocks] == [0, 1, 2]
    assert [item.device_frame_position for item in blocks] == [0, 480, 960]
    assert [item.capture_mono_ns for item in blocks] == [0, 10_000_000, 20_000_000]
    assert all(item.arrival_mono_ns == item.capture_mono_ns for item in blocks)
    assert all(item.clock_quality == "SYNTHETIC" for item in blocks)
    assert all(item.format == audio_format for item in blocks)
    assert all(len(item.payload) == item.frame_count * audio_format.frame_bytes for item in blocks)
    assert all(
        (item.session_id, item.track_id, item.epoch_id) == ("session", "system", "epoch")
        for item in blocks
    )


def test_source_fractional_sample_clock_uses_frame_position_without_rounding_drift() -> None:
    source = SyntheticSource("s", "t", "e", AudioFormat(44_100, 1), 442, 147, 123)
    blocks = list(source)
    assert [item.frame_count for item in blocks] == [147, 147, 147, 1]
    assert [item.capture_mono_ns for item in blocks] == [123, 3_333_456, 6_666_789, 10_000_123]


@pytest.mark.parametrize(
    ("sample_type", "decode", "expected"),
    [
        ("s16le", lambda data: unpack("<hhhh", data), (-32768, -28416, -32512, -28160)),
        (
            "s24le",
            lambda data: tuple(
                int.from_bytes(data[i : i + 3], "little", signed=True) for i in range(0, 12, 3)
            ),
            (-8388608, -7274496, -8323072, -7208960),
        ),
        (
            "s32le",
            lambda data: unpack("<iiii", data),
            (-2147483648, -1862270976, -2130706432, -1845493760),
        ),
        ("f32le", lambda data: unpack("<ffff", data), (-1.0, -0.8671875, -0.9921875, -0.859375)),
    ],
)
def test_source_samples_match_hand_checked_interleaved_oracle(
    sample_type: str,
    decode: Callable[[bytes], tuple[int | float, ...]],
    expected: tuple[int | float, ...],
) -> None:
    source = SyntheticSource("s", "t", "e", AudioFormat(48_000, 2, sample_type), 2)
    assert decode(next(iter(source)).payload) == expected


def test_source_signal_is_independent_of_block_partitioning() -> None:
    audio_format = AudioFormat(44_100, 2)
    first = SyntheticSource("s", "t", "e", audio_format, 1003, block_frames=480)
    second = SyntheticSource("s", "t", "e", audio_format, 1003, block_frames=127)
    assert b"".join(item.payload for item in first) == b"".join(item.payload for item in second)


def test_source_zero_length_and_large_total_are_lazy() -> None:
    audio_format = AudioFormat(48_000, 1)
    assert list(SyntheticSource("s", "t", "e", audio_format, 0)) == []
    first = next(iter(SyntheticSource("s", "t", "e", audio_format, 2**40)))
    assert first.frame_count == 480
    assert len(first.payload) == 960


@pytest.mark.parametrize(
    ("argument", "bad"),
    [
        ("total_frames", -1),
        ("total_frames", True),
        ("total_frames", 1.5),
        ("block_frames", 0),
        ("block_frames", -1),
        ("block_frames", True),
        ("start_ns", -1),
        ("start_ns", 0.1),
        ("start_ns", True),
    ],
)
def test_source_rejects_invalid_counters(argument: str, bad: Any) -> None:
    values: dict[str, Any] = {
        "session_id": "s",
        "track_id": "t",
        "epoch_id": "e",
        "format": AudioFormat(48_000, 1),
        "total_frames": 1,
    }
    values[argument] = bad
    with pytest.raises(ValidationError):
        SyntheticSource(**values)


@pytest.mark.parametrize("argument", ["session_id", "track_id", "epoch_id"])
def test_source_validates_identity_even_with_no_frames(argument: str) -> None:
    values: dict[str, Any] = {
        "session_id": "s",
        "track_id": "t",
        "epoch_id": "e",
        "format": AudioFormat(48_000, 1),
        "total_frames": 0,
    }
    values[argument] = "../unsafe"
    with pytest.raises(ValidationError):
        SyntheticSource(**values)


def test_source_requires_domain_audio_format() -> None:
    with pytest.raises(ValidationError):
        SyntheticSource("s", "t", "e", cast(AudioFormat, object()), 1)


def test_source_rejects_unrepresentable_timeline_before_yielding() -> None:
    with pytest.raises(ValidationError):
        SyntheticSource("s", "t", "e", AudioFormat(1, 1), 2**63)
