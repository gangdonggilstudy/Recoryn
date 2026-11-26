"""One coalesced audit request for the existing application control executor.

This module creates no worker, pool or parser. The GUI/CLI supplies execution
and reports its actual completion; cancelling a request is never a thread ACK.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic_ns as _monotonic_ns
from typing import Protocol

from recoryn.storage.deletion_history import REQUEST_INTERVAL_NS


class HistoryOwner(Protocol):
    @property
    def deletion_history_instance(self) -> str: ...

    def verify_deletion_history(
        self, *, fresh: bool = False, can_publish: Callable[[], bool] | None = None
    ) -> dict[str, str]: ...


@dataclass(frozen=True)
class HistoryAuditRequest:
    instance: str
    generation: int
    fresh: bool


class HistoryAuditCoordinator:
    """Owner-lane state: one in flight, at most one latest request queued."""

    def __init__(
        self,
        owner: HistoryOwner,
        *,
        clock: Callable[[], int] = _monotonic_ns,
        initially_verified: bool = False,
    ) -> None:
        self.owner = owner
        self.clock = clock
        self.generation = 0
        self.closed = False
        self.suspended = False
        self.inflight: HistoryAuditRequest | None = None
        self._pending = False
        self._pending_fresh = False
        # This only schedules the next request. It never creates/extends a receipt.
        self._last_requested: int | None = clock() if initially_verified else None

    def request(self, *, fresh: bool = False, force: bool = False) -> HistoryAuditRequest | None:
        if self.closed or self.suspended:
            return None
        now = self.clock()
        due = (
            self._last_requested is None
            or now < self._last_requested
            or now - self._last_requested >= REQUEST_INTERVAL_NS
        )
        if not (fresh or force or due):
            return None
        self._last_requested = now
        if self.inflight is not None:
            self._pending = True
            self._pending_fresh |= fresh
            return None
        self.generation += 1
        self.inflight = HistoryAuditRequest(
            self.owner.deletion_history_instance, self.generation, fresh
        )
        return self.inflight

    def execute(self, request: HistoryAuditRequest) -> dict[str, str]:
        """Caller runs this in its existing worker/control lane."""
        if (
            self.closed
            or self.suspended
            or request.instance != self.owner.deletion_history_instance
        ):
            return {"status": "UNAVAILABLE", "code": "DELETION_HISTORY_UNAVAILABLE"}
        return self.owner.verify_deletion_history(
            fresh=request.fresh,
            can_publish=lambda: (
                not self.closed
                and not self.suspended
                and request.instance == self.owner.deletion_history_instance
            ),
        )

    def is_current(self, request: HistoryAuditRequest) -> bool:
        return (
            not self.closed
            and not self.suspended
            and not self._pending_fresh
            and request == self.inflight
            and request.instance == self.owner.deletion_history_instance
        )

    def completed(self, request: HistoryAuditRequest) -> HistoryAuditRequest | None:
        """An actual worker ACK, even when its result is stale or the UI is closed."""
        if request != self.inflight:
            return None
        self.inflight = None
        pending, fresh = self._pending, self._pending_fresh
        self._pending = self._pending_fresh = False
        if self.closed or not pending:
            return None
        return self.request(fresh=fresh, force=True)

    def close(self) -> None:
        self.closed = True
        self._pending = self._pending_fresh = False
        # Keep inflight until completed(): the executor still owns a Library reader.

    def set_suspended(self, value: bool) -> None:
        self.suspended = value
        if value:
            self._pending = self._pending_fresh = False
        # Queued/running work still needs its real completion ACK.
