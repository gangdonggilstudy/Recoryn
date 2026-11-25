"""A capacity-bounded transport with an independent close control path.

Offers never wait for capacity, but Python locks and the GIL can still delay
callers. This implementation makes no hard real-time guarantee.
"""

from collections import deque
from collections.abc import Iterable
from math import isfinite
from queue import Empty
from threading import TIMEOUT_MAX, Condition, Lock
from time import monotonic

from recoryn.domain import MAX_PCM_BLOCK_BYTES, AudioFormat, PCMBlock, ValidationError

CaptureItem = PCMBlock | tuple[PCMBlock, ...]


def validate_fragments(fragments: tuple[PCMBlock, ...], *, minimum: int = 1) -> None:
    """Validate one complete immutable packet before any queue/accounting mutation."""
    if type(fragments) is not tuple or len(fragments) < minimum:
        raise ValidationError("Expected a complete packet tuple")
    first = fragments[0]
    if not isinstance(first, PCMBlock):
        raise ValidationError("Packet fragments must be PCMBlock values")
    identity = (first.session_id, first.track_id, first.epoch_id, first.sequence, first.format)
    for index, block in enumerate(fragments):
        if (
            not isinstance(block, PCMBlock)
            or (block.session_id, block.track_id, block.epoch_id, block.sequence, block.format)
            != identity
            or block.fragment_index != index
            or block.fragment_count != len(fragments)
            or len(block.payload) > MAX_PCM_BLOCK_BYTES
        ):
            raise ValidationError("Invalid packet fragment identity, order or size")


def packet_blocks(item: CaptureItem) -> tuple[PCMBlock, ...]:
    """Keep legacy single-block calls; tuples must contain a whole split packet."""
    if isinstance(item, PCMBlock):
        return (item,)
    validate_fragments(item, minimum=2)
    return item


def queue_byte_budget(formats: Iterable[AudioFormat]) -> int:
    """Two 200ms periods of the fastest track, bounded by the approved policy."""
    values = tuple(formats)
    if not values or any(not isinstance(value, AudioFormat) for value in values):
        raise ValidationError("Queue budget requires audio formats")
    fastest = max(values, key=lambda value: value.sample_rate * value.frame_bytes)
    period = ((fastest.sample_rate + 4) // 5) * fastest.frame_bytes
    return max(MAX_PCM_BLOCK_BYTES, min(128 * 1024 * 1024, 2 * period))


class BoundedCaptureQueue:
    """Keep accepted blocks in FIFO order and drop new arrivals at capacity.

    Counters are cumulative, including after drain. Closed offers are privacy
    rejections and do not change acceptance or loss counters. The condition lock
    linearizes concurrent offer/get/close operations. Close needs no queue slot.
    """

    def __init__(self, max_blocks: int, max_bytes: int) -> None:
        for name, value in (("max_blocks", max_blocks), ("max_bytes", max_bytes)):
            if type(value) is not int or value <= 0:
                raise ValidationError(f"{name} must be a positive integer")
        self._max_blocks = max_blocks
        self._max_bytes = max_bytes
        self._condition = Condition(Lock())
        self._blocks: deque[PCMBlock] = deque()
        self._queued_bytes = 0
        self._accepted_blocks = 0
        self._accepted_frames = 0
        self._accepted_bytes = 0
        self._dropped_blocks = 0
        self._dropped_frames = 0
        self._dropped_bytes = 0
        self._high_water_blocks = 0
        self._high_water_bytes = 0
        self._closed = False

    def offer(self, block: PCMBlock) -> bool:
        """Accept immediately when both bounds allow it; never evict old data."""
        if not isinstance(block, PCMBlock):
            raise ValidationError("offer requires a PCMBlock")
        return self._offer((block,))

    def offer_packet(self, fragments: tuple[PCMBlock, ...]) -> bool:
        """Linearize all fragments, or reject the entire packet without eviction."""
        validate_fragments(fragments)
        return self._offer(fragments)

    def _offer(self, fragments: tuple[PCMBlock, ...]) -> bool:
        count = len(fragments)
        byte_count = sum(len(block.payload) for block in fragments)
        frame_count = sum(block.frame_count for block in fragments)
        with self._condition:
            if self._closed:
                return False
            if (
                len(self._blocks) + count > self._max_blocks
                or self._queued_bytes + byte_count > self._max_bytes
            ):
                self._dropped_blocks += count
                self._dropped_frames += frame_count
                self._dropped_bytes += byte_count
                return False
            self._blocks.extend(fragments)
            self._queued_bytes += byte_count
            self._accepted_blocks += count
            self._accepted_frames += frame_count
            self._accepted_bytes += byte_count
            self._high_water_blocks = max(self._high_water_blocks, len(self._blocks))
            self._high_water_bytes = max(self._high_water_bytes, self._queued_bytes)
            self._condition.notify(count)
            return True

    def get(self, timeout: float | None = None) -> PCMBlock:
        """Wait up to timeout seconds; None waits indefinitely and zero polls.

        An open empty queue raises queue.Empty at the deadline. Once closed,
        already accepted blocks remain readable; closed and drained raises
        EOFError immediately, even for an unbounded wait.
        """
        if timeout is not None:
            if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
                raise ValidationError("timeout must be a finite nonnegative number or None")
            try:
                timeout = float(timeout)
            except OverflowError as exc:
                raise ValidationError("timeout is too large") from exc
            if not isfinite(timeout) or timeout < 0:
                raise ValidationError("timeout must be a finite nonnegative number or None")
        deadline = None if timeout is None else monotonic() + timeout
        with self._condition:
            while not self._blocks:
                if self._closed:
                    raise EOFError("capture queue is closed and drained")
                if deadline is None:
                    self._condition.wait()
                else:
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        raise Empty
                    self._condition.wait(min(remaining, TIMEOUT_MAX))
            block = self._blocks.popleft()
            self._queued_bytes -= len(block.payload)
            return block

    def close(self) -> None:
        """Reject future input and wake all readers without consuming capacity."""
        with self._condition:
            self._closed = True
            self._condition.notify_all()

    def snapshot(self) -> dict[str, int | bool]:
        """Return one consistent, detached view of capacity and frame accounting."""
        with self._condition:
            return {
                "max_blocks": self._max_blocks,
                "max_bytes": self._max_bytes,
                "queued_blocks": len(self._blocks),
                "queued_bytes": self._queued_bytes,
                "accepted_blocks": self._accepted_blocks,
                "accepted_frames": self._accepted_frames,
                "accepted_bytes": self._accepted_bytes,
                "dropped_blocks": self._dropped_blocks,
                "dropped_frames": self._dropped_frames,
                "dropped_bytes": self._dropped_bytes,
                "high_water_blocks": self._high_water_blocks,
                "high_water_bytes": self._high_water_bytes,
                "closed": self._closed,
            }
