"""A capacity-bounded transport with an independent close control path.

Offers never wait for capacity, but Python locks and the GIL can still delay
callers. This implementation makes no hard real-time guarantee.
"""

from collections import deque
from math import isfinite
from queue import Empty
from threading import TIMEOUT_MAX, Condition, Lock
from time import monotonic

from recoryn.domain import PCMBlock, ValidationError


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
        byte_count = len(block.payload)
        with self._condition:
            if self._closed:
                return False
            if (
                len(self._blocks) >= self._max_blocks
                or self._queued_bytes + byte_count > self._max_bytes
            ):
                self._dropped_blocks += 1
                self._dropped_frames += block.frame_count
                self._dropped_bytes += byte_count
                return False
            self._blocks.append(block)
            self._queued_bytes += byte_count
            self._accepted_blocks += 1
            self._accepted_frames += block.frame_count
            self._accepted_bytes += byte_count
            self._high_water_blocks = max(self._high_water_blocks, len(self._blocks))
            self._high_water_bytes = max(self._high_water_bytes, self._queued_bytes)
            self._condition.notify()
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
