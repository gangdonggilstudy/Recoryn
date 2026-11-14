"""Compare capture accounting against a small, independent deque model."""

from collections import deque
from queue import Empty

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from recoryn.capture import BoundedCaptureQueue
from recoryn.domain import AudioFormat, PCMBlock

pytestmark = pytest.mark.property


@settings(max_examples=100, deadline=None, derandomize=True, database=None)
@given(
    slots=st.integers(min_value=1, max_value=6),
    byte_limit=st.integers(min_value=1, max_value=64),
    actions=st.lists(
        st.tuples(st.sampled_from(("offer", "get", "close")), st.integers(1, 20)),
        min_size=1,
        max_size=100,
    ),
)
def test_queue_matches_independent_model(
    slots: int, byte_limit: int, actions: list[tuple[str, int]]
) -> None:
    queue = BoundedCaptureQueue(max_blocks=slots, max_bytes=byte_limit)
    model: deque[PCMBlock] = deque()
    queued_bytes = accepted_frames = dropped_frames = 0
    closed = False
    for sequence, (action, frames) in enumerate(actions):
        if action == "close":
            queue.close()
            closed = True
        elif action == "get":
            if model:
                expected = model.popleft()
                actual = queue.get(timeout=0)
                assert actual == expected
                queued_bytes -= len(expected.payload)
            else:
                with pytest.raises(EOFError if closed else Empty):
                    queue.get(timeout=0)
        else:
            block = PCMBlock(
                session_id="model",
                track_id="mic",
                epoch_id="epoch1",
                sequence=sequence,
                format=AudioFormat(48000, 1),
                frame_count=frames,
                payload=bytes([sequence % 251]) * (frames * 2),
                capture_mono_ns=sequence,
                arrival_mono_ns=sequence,
            )
            expected_accept = (
                not closed and len(model) < slots and queued_bytes + frames * 2 <= byte_limit
            )
            assert queue.offer(block) is expected_accept
            if expected_accept:
                model.append(block)
                queued_bytes += frames * 2
                accepted_frames += frames
            elif not closed:
                dropped_frames += frames
        snapshot = queue.snapshot()
        assert snapshot["accepted_frames"] == accepted_frames
        assert snapshot["dropped_frames"] == dropped_frames
        assert snapshot["accepted_bytes"] == accepted_frames * 2
        assert snapshot["dropped_bytes"] == dropped_frames * 2
        assert snapshot["closed"] is closed
        assert 0 <= queued_bytes <= byte_limit
        assert len(model) <= slots
    queue.close()
    while model:
        assert queue.get(timeout=0) == model.popleft()
    with pytest.raises(EOFError):
        queue.get(timeout=0)
