"""G17 bounded command histories and virtual arrival/sync scheduling, strict mode."""

from __future__ import annotations

import json
from collections import deque
from itertools import product
from queue import Empty

import pytest

from recoryn.capture.queue import BoundedCaptureQueue
from recoryn.domain import StateConflict
from recoryn.storage.chunks import has_active_writer
from tests.unit.test_append_durability import Harness, block

pytestmark = pytest.mark.property
ALPHABET = ("accept", "append", "sync_ok", "sync_error", "delete", "seal", "close")
TRACES = [trace for n in range(4) for trace in product(ALPHABET, repeat=n)]
M = list(product((1, 2), TRACES))


def reference(trace, tracks):
    """Small hand-specified component model; never reads product state/predicates."""
    queue = deque()
    states = {t: "NEW" for t in tracks}
    committed = {t: [] for t in tracks}
    next_sequence = 0
    deleted = closed = False
    observed = []
    for command in trace:
        replies = []
        if command == "accept":
            for track in tracks:
                ok = not closed and len(queue) < 4
                replies.append(ok)
                if ok:
                    queue.append((track, next_sequence))
            next_sequence += 1
        elif command == "append":
            for _ in tracks:
                if not queue:
                    replies.append("EMPTY")
                    break
                track, sequence = queue.popleft()
                states.setdefault(track, "NEW")
                committed.setdefault(track, [])
                if states[track] in {"CLOSED", "FAILED", "SEALED"}:
                    replies.append(False)
                elif deleted:
                    # Rejected before any media I/O: the previous cut is unchanged.
                    replies.append(False)
                else:
                    states[track] = "OPEN"
                    committed[track].append(sequence)
                    replies.append(True)
        elif command in {"sync_ok", "sync_error"}:
            for track, state in list(states.items()):
                if state in {"NEW", "SEALED"}:
                    replies.append(True)  # historical final confirmation, no new I/O
                elif state in {"FAILED", "CLOSED"}:
                    replies.append(False)
                elif deleted or command == "sync_error":
                    states[track] = "FAILED"
                    replies.append(False)
                else:
                    replies.append(True)
            if not states:
                replies = ["EMPTY"]
        elif command == "delete":
            deleted = True
            replies = [True]
        elif command == "seal":
            for track, state in list(states.items()):
                ok = state == "OPEN" and not deleted
                if ok:
                    states[track] = "SEALED"
                replies.append(ok)
            if not states:
                replies = ["EMPTY"]
        else:
            closed = True
            for track in states:
                states[track] = "CLOSED"
            replies = [True]
        observed.append(replies)
    return observed, committed, states


@pytest.mark.parametrize("count,trace", M, ids=[f"G17-M-{i:04}" for i in range(1, 801)])
def test_every_strict_command_trace_matches_a_separate_model(tmp_path, monkeypatch, count, trace):
    tracks = ("mic", "system")[:count]
    h = Harness(tmp_path, monkeypatch, durable=False)
    q = BoundedCaptureQueue(4, 64)
    writers = {t: h.writer(track=t) for t in tracks}
    actual, sequence = [], 0
    try:
        for command in trace:
            replies = []
            before = len(h.io.events)
            if command == "accept":
                replies = [q.offer(block(sequence, track=t)) for t in tracks]
                sequence += 1
            elif command == "append":
                for _ in tracks:
                    try:
                        item = q.get(0)
                    except (Empty, EOFError):
                        replies.append("EMPTY")
                        break
                    writer = writers[item.track_id]
                    try:
                        writer.append(item)
                    except (ValueError, OSError, StateConflict):
                        replies.append(False)
                    else:
                        replies.append(True)
                successful = sum(value is True for value in replies)
                assert [p for kind, p in h.io.events[before:] if kind == "sync_done"] == [
                    "audio.pcm",
                    "blocks.jsonl",
                ] * successful
            elif command in {"sync_ok", "sync_error"}:

                def fault(phase, path, stream, command=command):
                    if command == "sync_error" and phase == "before":
                        raise OSError("virtual sync failure")

                h.io.sync_hook = fault
                for writer in writers.values():
                    try:
                        writer._sync()
                    except (ValueError, OSError, StateConflict):
                        replies.append(False)
                    else:
                        replies.append(True)
                h.io.sync_hook = None
                if not writers:
                    replies = ["EMPTY"]
            elif command == "delete":
                h.authority.deleted = True
                h.io.events.append(("D", "s"))
                replies = [True]
            elif command == "seal":
                for writer in writers.values():
                    try:
                        writer.seal()
                    except (ValueError, OSError, StateConflict):
                        replies.append(False)
                    else:
                        replies.append(True)
                if not writers:
                    replies = ["EMPTY"]
                successful = sum(value is True for value in replies)
                assert [p for kind, p in h.io.events[before:] if kind == "sync_done"] == [
                    "audio.pcm",
                    "blocks.jsonl",
                    "descriptor.json",
                ] * successful
            else:
                q.close()
                for writer in writers.values():
                    writer.abort()
                replies = [True]
            actual.append(replies)
        expected, committed, states = reference(trace, tracks)
        assert actual == expected
        assert has_active_writer(h.root, "s") is any(state == "OPEN" for state in states.values())
        for track, writer in writers.items():
            path = writer.path if writer.path.exists() else writer.staging_path
            wanted = committed[track]
            if not path.exists():
                assert wanted == []
                continue
            records = [
                json.loads(line) for line in (path / "blocks.jsonl").read_bytes().splitlines()
            ]
            assert [r["metadata"]["sequence"] for r in records] == wanted
            assert (path / "audio.pcm").read_bytes() == b"".join(
                block(i, track=track).payload for i in wanted
            )
            assert writer._count == len(wanted)
        if "delete" in trace:
            after = h.io.events[h.io.events.index(("D", "s")) + 1 :]
            assert not [e for e in after if e[0] in {"create", "write"}]
        snapshot = q.snapshot()
        before_close = trace[: trace.index("close")] if "close" in trace else trace
        assert (
            snapshot["accepted_frames"] + snapshot["dropped_frames"]
            == before_close.count("accept") * count * 4
        )
        assert snapshot["high_water_blocks"] <= 4
    finally:
        h.io.sync_hook = None
        h.close()


Q = list(product((1, 2), (0, 50, 100, 200, 500), ("all", "tenth", "first"), (False, True)))


def scheduled_reference(tracks, delay, distribution, contender):
    """Independent integer-time FIFO simulation, ten arrivals per track."""
    now = calls = offered = rejected = arrival = 0
    queue, accepted = deque(), []

    def arrivals(until):
        nonlocal arrival, offered, rejected
        while arrival < 10 and arrival * 10 <= until:
            for track in range(tracks):
                offered += 1
                if len(queue) == 4:
                    rejected += 1
                else:
                    queue.append((track, arrival))
            arrival += 1

    arrivals(0)
    while queue or arrival < 10:
        if not queue:
            now = arrival * 10
            arrivals(now)
        accepted.append(queue.popleft())
        for _ in range(2):
            calls += 1
            extra = (
                delay
                if (
                    distribution == "all"
                    or distribution == "first"
                    and calls == 1
                    or distribution == "tenth"
                    and calls % 10 == 0
                )
                and now < 100
                else 0
            )
            now += extra + int(contender)
            arrivals(now)
    return accepted, offered, rejected


@pytest.mark.parametrize(
    "count,delay,distribution,contender", Q, ids=[f"G17-Q-{i:03}" for i in range(1, 61)]
)
def test_virtual_sync_delays_drive_real_writers_and_bounded_queue(
    tmp_path, monkeypatch, count, delay, distribution, contender
):
    h = Harness(tmp_path, monkeypatch, durable=False)
    tracks = ("mic", "system")[:count]
    queue = BoundedCaptureQueue(4, 64)
    now = calls = tick = 0
    observed, writers = [], {}

    def arrive(until):
        nonlocal tick
        while tick < 10 and tick * 10 <= until:
            for track in tracks:
                queue.offer(block(tick, track=track))
            tick += 1
        if tick == 10:
            queue.close()

    def timed(phase, path, stream):
        nonlocal now, calls
        if phase != "before":
            return
        calls += 1
        enabled = (
            distribution == "all"
            or distribution == "first"
            and calls == 1
            or (distribution == "tenth" and calls % 10 == 0)
        )
        elapsed = delay if enabled and now < 100 else 0
        if contender:
            assert not h.io.mutex.owned
            with h.io.mutex:
                pass  # a real independent management critical section between I/O steps
        now += elapsed + int(contender)
        arrive(now)

    h.io.sync_hook = timed
    try:
        arrive(0)
        while True:
            try:
                item = queue.get(0)
            except Empty:
                now = tick * 10
                arrive(now)
                continue
            except EOFError:
                break
            if item.track_id not in writers:
                writers[item.track_id] = h.writer(track=item.track_id)
            writers[item.track_id].append(item)
            observed.append((tracks.index(item.track_id), item.sequence))
        expected, offered, rejected = scheduled_reference(count, delay, distribution, contender)
        assert observed == expected
        snapshot = queue.snapshot()
        assert snapshot["accepted_blocks"] == len(expected)
        assert snapshot["dropped_blocks"] == rejected
        assert snapshot["accepted_blocks"] + snapshot["dropped_blocks"] == offered == count * 10
        assert snapshot["high_water_blocks"] <= 4
        for track, writer in writers.items():
            descriptor = writer.seal()
            sequences = [i for t, i in expected if tracks[t] == track]
            assert descriptor.frame_count == len(sequences) * 4
            assert (writer.path / "audio.pcm").read_bytes() == b"".join(
                block(i, track=track).payload for i in sequences
            )
        assert not has_active_writer(h.root, "s")
    finally:
        h.io.sync_hook = None
        h.close()
