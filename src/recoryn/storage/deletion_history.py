"""Process-local deletion authority. Call state mutations under the owner's root lock.

Canonical I/O and materialization belong to the control lane, never a hot lookup.
The immutable cut/delta references also keep retired objects alive until that lane
has left the root lock; publishing a receipt must not deallocate an O(H) map there.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from math import ceil
from pathlib import Path
from time import get_clock_info as _clock_info
from time import monotonic_ns as _monotonic_ns
from time import time_ns as _utc_ns
from types import MappingProxyType
from typing import Any
from uuid import uuid4

from recoryn.domain import ValidationError

from ._safe import (
    canonical,
    check_path,
    identifier,
    integer,
    read_json,
    safe_path,
    schema,
)

LIFETIME_NS = 30_000_000_000
REQUEST_INTERVAL_NS = 5_000_000_000
OBSERVATION_PRECISION_NS = 1_000_000


def _integer(value: int, *, minimum: int = 0) -> None:
    if type(value) is not int or value < minimum:
        raise ValidationError("DELETION_HISTORY_UNAVAILABLE")


@dataclass(frozen=True)
class HistoryClockSample:
    monotonic_ns: int
    utc_ns: int
    span_ns: int = 0
    precision_ns: int = 0

    def __post_init__(self) -> None:
        for value in (self.monotonic_ns, self.utc_ns, self.span_ns, self.precision_ns):
            _integer(value)

    @classmethod
    def now(cls) -> HistoryClockSample:
        # Runtime clock granularity can exceed our observation floor. Precision
        # permits only clock comparison uncertainty; neither expiry bound grows.
        precision = max(
            OBSERVATION_PRECISION_NS,
            ceil(_clock_info("time").resolution * 1_000_000_000),
            ceil(_clock_info("monotonic").resolution * 1_000_000_000),
        )
        before = _monotonic_ns()
        utc = _utc_ns()
        after = _monotonic_ns()
        return cls(before, utc, after - before, precision)

    def within(self, start: HistoryClockSample, lifetime_ns: int = LIFETIME_NS) -> bool:
        """Observation uncertainty never extends either clock's expiry bound."""
        _integer(lifetime_ns, minimum=1)
        mono = self.monotonic_ns - start.monotonic_ns
        wall = self.utc_ns - start.utc_ns
        uncertainty = self.span_ns + start.span_ns + self.precision_ns + start.precision_ns
        return (
            0 <= mono
            and mono + self.span_ns < lifetime_ns
            and 0 <= wall < lifetime_ns
            and abs(mono - wall) <= uncertainty
        )


@dataclass(frozen=True)
class HistoryEntry:
    journal_generation: int | None = None
    journal_digest: str | None = None
    db_generation: int | None = None
    db_status: str | None = None

    def __post_init__(self) -> None:
        if self.journal_generation is None and self.db_generation is None:
            raise ValidationError("DELETION_HISTORY_UNAVAILABLE")
        if self.journal_generation is not None:
            _integer(self.journal_generation, minimum=1)
            digest = self.journal_digest
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or any(c not in "0123456789abcdef" for c in digest)
            ):
                raise ValidationError("DELETION_HISTORY_UNAVAILABLE")
        elif self.journal_digest is not None:
            raise ValidationError("DELETION_HISTORY_UNAVAILABLE")
        if self.db_generation is not None:
            _integer(self.db_generation, minimum=1)
            if self.db_status not in {"DELETE_PENDING", "DELETED_LOCAL"}:
                raise ValidationError("DELETION_HISTORY_UNAVAILABLE")
        elif self.db_status is not None:
            raise ValidationError("DELETION_HISTORY_UNAVAILABLE")

    @property
    def generation(self) -> int:
        return max(self.journal_generation or 0, self.db_generation or 0)

    def advance(self, newer: HistoryEntry) -> HistoryEntry:
        """A trusted delta cannot lower any existing negative authority."""
        if newer.generation < self.generation or (
            self.db_status == "DELETED_LOCAL" and newer.db_status == "DELETE_PENDING"
        ):
            raise ValidationError("DELETION_HISTORY_UNAVAILABLE")
        for old, new in (
            (self.journal_generation, newer.journal_generation),
            (self.db_generation, newer.db_generation),
        ):
            if old is not None and new is not None and new < old:
                raise ValidationError("DELETION_HISTORY_UNAVAILABLE")
        return HistoryEntry(
            newer.journal_generation
            if newer.journal_generation is not None
            else self.journal_generation,
            newer.journal_digest if newer.journal_generation is not None else self.journal_digest,
            newer.db_generation if newer.db_generation is not None else self.db_generation,
            newer.db_status if newer.db_generation is not None else self.db_status,
        )


@dataclass(frozen=True)
class FormatOneJournal:
    records: dict[str, HistoryEntry]
    names: frozenset[str]


def read_format_one(
    root: Path, *, reader: Callable[[Path], dict[str, Any]] = read_json
) -> FormatOneJournal:
    """Shared format-1 parser; pin the bounded, strictly parsed logical record.

    The control caller rechecks its observation cut before publishing authority.
    OSError is deliberately not recast as persistent content damage.
    """
    journal = safe_path(root, "deletion-journal")
    if not journal.is_dir():
        raise ValidationError("DELETION_HISTORY_UNAVAILABLE")
    records = {}
    names = set()
    for path in journal.iterdir():
        check_path(path)
        if path.name.startswith(".tmp-"):
            raise ValidationError("Incomplete deletion history")
        if not path.is_file() or path.suffix != ".json":
            raise ValidationError("Unrecognized deletion history")
        value = reader(path)
        schema(value)
        sid = identifier(value.get("session_id"))
        generation = integer(value.get("generation"), minimum=1)
        if path.name != sid + ".json" or value.get("state") != "DELETE_REQUESTED":
            raise ValidationError("Invalid deletion intent")
        records[sid] = HistoryEntry(generation, sha256(canonical(value)).hexdigest())
        names.add(path.name)
    return FormatOneJournal(records, frozenset(names))


@dataclass(frozen=True)
class HistoryDelta:
    version: int
    session_id: str
    entry: HistoryEntry
    previous: HistoryDelta | None


@dataclass(frozen=True)
class HistoryCut:
    instance: str
    version: int
    base_version: int
    base: Mapping[str, HistoryEntry]
    head: HistoryDelta | None

    def materialize(self) -> dict[str, HistoryEntry]:
        """O(H+D), control lane only; the cut contains no mutable map."""
        result = dict(self.base)
        pending = []
        delta = self.head
        while delta is not None and delta.version > self.base_version:
            pending.append(delta)
            delta = delta.previous
        for delta in reversed(pending):
            result[delta.session_id] = delta.entry
        return result


@dataclass(frozen=True)
class HistoryScan:
    instance: str
    observation: int
    epoch: int
    started: HistoryClockSample
    cut: HistoryCut
    fresh: bool
    initialized: bool


@dataclass(frozen=True)
class HistoryReceipt:
    instance: str
    observation: int
    started: HistoryClockSample
    cut_version: int


@dataclass(frozen=True)
class PreparedHistory:
    scan: HistoryScan
    cut: HistoryCut
    base: Mapping[str, HistoryEntry]
    working: dict[str, HistoryEntry]


class DeletionHistoryIndex:
    """Exact negative floor plus bounded permission for global management work.

    The Library root lock owns this object. These methods acquire no other lock,
    perform no I/O and start no thread. prepare() runs outside that lock on cuts.
    """

    def __init__(
        self, root: Path, *, clock: Callable[[], HistoryClockSample] = HistoryClockSample.now
    ) -> None:
        self.root = root
        self.instance = uuid4().hex
        self.clock = clock
        self.version = 0
        self.epoch = 0
        self.observation = 0
        self.published = 0
        self.initialized = False
        self.closed = False
        self.needs_fresh = False
        self.receipt: HistoryReceipt | None = None
        self._entries: dict[str, HistoryEntry] = {}
        self._base: Mapping[str, HistoryEntry] = MappingProxyType({})
        self._base_version = 0
        self._head: HistoryDelta | None = None

    def cut(self) -> HistoryCut:
        return HistoryCut(self.instance, self.version, self._base_version, self._base, self._head)

    def known(self, session_id: str) -> HistoryEntry | None:
        return self._entries.get(session_id) or self._base.get(session_id)

    def __contains__(self, session_id: str) -> bool:
        return self.known(session_id) is not None

    def trusted_delta(self, session_id: str, entry: HistoryEntry) -> None:
        identifier(session_id)
        if self.closed:
            raise ValidationError("DELETION_HISTORY_UNAVAILABLE")
        before = self.known(session_id)
        entry = before.advance(entry) if before is not None else entry
        self.version += 1
        self._entries[session_id] = entry
        self._head = HistoryDelta(self.version, session_id, entry, self._head)
        # A per-key change is not a new full validation; receipt.started is untouched.

    def valid(self, now: HistoryClockSample | None = None) -> bool:
        receipt = self.receipt
        if self.closed or self.needs_fresh or receipt is None or receipt.instance != self.instance:
            return False
        try:
            return (now if now is not None else self.clock()).within(receipt.started)
        except (ValueError, OSError, OverflowError):
            return False  # a broken observer grants nothing and cannot stop capture

    def due(self, now: HistoryClockSample | None = None) -> bool:
        sample = now or self.clock()
        return not self.closed and (
            self.receipt is None or not sample.within(self.receipt.started, REQUEST_INTERVAL_NS)
        )

    def invalidate(self) -> None:
        self.epoch += 1
        self.receipt = None

    def begin_scan(self, *, fresh: bool = False) -> HistoryScan:
        if self.closed:
            raise ValidationError("DELETION_HISTORY_UNAVAILABLE")
        if fresh:
            self.invalidate()
        self.observation += 1
        return HistoryScan(
            self.instance,
            self.observation,
            self.epoch,
            self.clock(),
            self.cut(),
            fresh,
            self.initialized,
        )

    def current_scan(self, scan: HistoryScan) -> bool:
        return (
            not self.closed
            and scan.instance == self.instance
            and scan.epoch == self.epoch
            and scan.observation >= self.published
        )

    @staticmethod
    def prepare(
        scan: HistoryScan, records: Mapping[str, HistoryEntry], cut: HistoryCut
    ) -> PreparedHistory:
        """Validate full canonical input against pinned knowledge and trusted deltas."""
        if cut.instance != scan.instance or cut.version < scan.cut.version:
            raise ValidationError("DELETION_HISTORY_UNAVAILABLE")
        starting = scan.cut.materialize()
        allowed_journal: dict[str, set[tuple[int | None, str | None]]] = {}
        allowed_db: dict[str, set[tuple[int | None, str | None]]] = {}
        for sid, entry in starting.items():
            allowed_journal[sid] = {(entry.journal_generation, entry.journal_digest)}
            allowed_db[sid] = {(entry.db_generation, entry.db_status)}
        delta = cut.head
        while delta is not None and delta.version > scan.cut.version:
            allowed_journal.setdefault(delta.session_id, {(None, None)}).add(
                (delta.entry.journal_generation, delta.entry.journal_digest)
            )
            allowed_db.setdefault(delta.session_id, {(None, None)}).add(
                (delta.entry.db_generation, delta.entry.db_status)
            )
            delta = delta.previous
        if scan.initialized:
            for sid in starting.keys() | records.keys():
                candidate = records.get(sid)
                journal = (
                    (candidate.journal_generation, candidate.journal_digest)
                    if candidate
                    else (None, None)
                )
                db = (candidate.db_generation, candidate.db_status) if candidate else (None, None)
                if journal not in allowed_journal.get(sid, set()) or db not in allowed_db.get(
                    sid, set()
                ):
                    raise ValidationError("DELETION_HISTORY_UNAVAILABLE")
            current = cut.materialize()
        else:
            current = dict(records)
            for sid, entry in cut.materialize().items():
                current[sid] = current[sid].advance(entry) if sid in current else entry
        # Both maps are built off root. The working copy must never alias the base.
        return PreparedHistory(scan, cut, MappingProxyType(current), dict(current))

    def publish(self, prepared: PreparedHistory) -> tuple[object, ...]:
        """O(1) publication. Caller drops returned retired references off root."""
        scan = prepared.scan
        if not self.current_scan(scan) or self.needs_fresh and not scan.fresh:
            return ()
        in_window = self.clock().within(scan.started)
        retired: tuple[object, ...] = (self._base, self._head, self._entries)
        self._base = prepared.base
        self._base_version = prepared.cut.version
        if self.version == prepared.cut.version:
            self._entries = prepared.working
            self._head = None
        self.initialized = True
        self.needs_fresh = False
        self.published = scan.observation
        # Verified negative facts outlive positive permission. A long initial
        # scan must not forget a tombstone merely because it cannot grant a TTL.
        self.receipt = (
            HistoryReceipt(self.instance, scan.observation, scan.started, prepared.cut.version)
            if in_window
            else None
        )
        return retired

    def failed(self, scan: HistoryScan, *, io_error: bool) -> None:
        if self.current_scan(scan):
            self.published = scan.observation
            self.receipt = None
            if not io_error:
                self.needs_fresh = True

    def close(self) -> None:
        self.closed = True
        self.invalidate()
