"""Capture observations: loss, inactive control intervals and uncertainty are distinct.

No storage, Qt or device SDK dependency. Coordinates are half-open and comparable
only within the same track/epoch/clock. An unknown tail is not a measured loss.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, fields
from typing import Any

from recoryn.domain import ValidationError, _identifier, _integer

REASONS = {
    "QUEUE_DROP": "APP_QUEUE",
    "DEVICE_DISCONTINUITY": "DEVICE",
    "DEVICE_LOST": "DEVICE",
    "PAUSE": "CONTROL",
    "SUSPEND": "CONTROL",
    "STORAGE_FAILED": "STORAGE",
    "NO_PACKETS": "DEVICE",
    "UNKNOWN_TAIL": "RECOVERY",
}
STATES = frozenset({"OK", "DEGRADED", "UNAVAILABLE", "STOPPED"})
MAX_EVENTS = 256
MAX_PAYLOAD = 4096


def encoded(value: Any) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
    except (TypeError, ValueError):
        raise ValidationError("HEALTH_UNREADABLE") from None


def stable_id(*parts: object) -> str:
    return hashlib.sha256(encoded(parts).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class GapFact:
    session_id: str
    capture_run_id: str
    track_id: str
    epoch_id: str
    event_id: str
    gap_id: str
    ordinal: int
    reason: str
    source: str
    clock_ref: str
    start: int | None = None
    end: int | None = None
    range_quality: str = "UNKNOWN"
    lost_frames: int | None = None
    count_quality: str = "UNKNOWN"
    open: bool = True
    detail_complete: bool = True
    kind: str = "OPEN"
    observation_bounds: tuple[int | None, int | None] = (None, None)

    def __post_init__(self) -> None:
        for name in (
            "session_id",
            "capture_run_id",
            "track_id",
            "epoch_id",
            "event_id",
            "gap_id",
            "clock_ref",
        ):
            _identifier(getattr(self, name), name)
        _integer(self.ordinal, "ordinal")
        if (
            not isinstance(self.reason, str)
            or self.reason not in REASONS
            or REASONS[self.reason] != self.source
        ):
            raise ValidationError("HEALTH_UNREADABLE")
        if not isinstance(self.range_quality, str) or self.range_quality not in {
            "EXACT_SOURCE",
            "OBSERVED_CONTROL",
            "UNKNOWN",
        }:
            raise ValidationError("HEALTH_UNREADABLE")
        if (
            not isinstance(self.count_quality, str)
            or not isinstance(self.kind, str)
            or self.count_quality not in {"EXACT", "UNKNOWN"}
            or self.kind
            not in {
                "OPEN",
                "CLOSE",
                "UNKNOWN_TAIL",
            }
        ):
            raise ValidationError("HEALTH_UNREADABLE")
        if (
            not isinstance(self.observation_bounds, (tuple, list))
            or len(self.observation_bounds) != 2
        ):
            raise ValidationError("HEALTH_UNREADABLE")
        for value in (self.start, self.end, self.lost_frames, *self.observation_bounds):
            if value is not None:
                _integer(value, "health value")
        object.__setattr__(self, "observation_bounds", tuple(self.observation_bounds))
        if (
            len(self.observation_bounds) != 2
            or type(self.open) is not bool
            or type(self.detail_complete) is not bool
        ):
            raise ValidationError("HEALTH_UNREADABLE")
        if self.start is not None and self.end is not None and self.end < self.start:
            raise ValidationError("HEALTH_UNREADABLE")
        if (self.lost_frames is None) != (self.count_quality == "UNKNOWN"):
            raise ValidationError("HEALTH_UNREADABLE")
        if (
            self.reason
            in {"PAUSE", "SUSPEND", "DEVICE_LOST", "NO_PACKETS", "STORAGE_FAILED", "UNKNOWN_TAIL"}
            and self.lost_frames is not None
        ):
            raise ValidationError("HEALTH_UNREADABLE")
        if self.reason == "QUEUE_DROP" and self.lost_frames is None:
            raise ValidationError("HEALTH_UNREADABLE")
        if self.reason == "UNKNOWN_TAIL" and (
            self.start is not None or self.end is not None or self.kind != "UNKNOWN_TAIL"
        ):
            raise ValidationError("HEALTH_UNREADABLE")
        if self.range_quality == "EXACT_SOURCE" and (
            self.start is None or self.end is None or self.lost_frames != self.end - self.start
        ):
            raise ValidationError("HEALTH_UNREADABLE")
        if self.range_quality == "OBSERVED_CONTROL" and self.source != "CONTROL":
            raise ValidationError("HEALTH_UNREADABLE")
        if len(encoded(self.to_dict()).encode()) > MAX_PAYLOAD:
            raise ValidationError("HEALTH_PAYLOAD_TOO_LARGE")

    def to_dict(self) -> dict[str, Any]:
        # Values are immutable scalars/coordinate pairs; recursive deepcopy is
        # unnecessary on the capture rejection path.
        return {field.name: getattr(self, field.name) for field in fields(self)}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> GapFact:
        try:
            return cls(**value)
        except (TypeError, KeyError):
            raise ValidationError("HEALTH_UNREADABLE") from None


@dataclass(frozen=True, slots=True)
class CaptureReceipt:
    """Caller contract: facts taken from cutoff, source.stop and BOTH worker joins."""

    capture_run_id: str
    cutoff: bool
    sources_ack: bool
    workers_ack: bool
    storage_failed: bool

    def complete(self, run_id: str) -> bool:
        return (
            self.capture_run_id == run_id
            and self.cutoff is True
            and self.sources_ack is True
            and self.workers_ack is True
            and self.storage_failed is False
        )


def transition_track(state: str, reason: str, event: str) -> tuple[str, str]:
    """The closed per-run state machine; invalid/late transitions change nothing."""
    if state not in STATES:
        raise ValidationError("HEALTH_UNREADABLE")
    if event == "DUPLICATE_EVENT":
        return state, reason
    if state == "STOPPED":
        if reason == "PAUSED" and event == "BEGIN_RESUME":
            return "UNAVAILABLE", "STARTING"
        if reason == "PAUSED" and event == "STOP_CONFIRMED":
            return "STOPPED", "FINAL"
        return state, reason
    if reason == "STORAGE_FAILED":
        return state, reason
    if event == "STORAGE_FAILED":
        return "UNAVAILABLE", "STORAGE_FAILED"
    if event in {"PAUSE_CONFIRMED", "SUSPEND_CONFIRMED"}:
        return "STOPPED", "PAUSED"
    if event == "STOP_CONFIRMED":
        return "STOPPED", "FINAL"
    if event == "DEVICE_LOST":
        return "UNAVAILABLE", "DEVICE_LOST"
    if reason == "DEVICE_LOST":
        return state, reason
    if event in {"QUEUE_REJECT", "BAD_CLOCK", "NO_PACKETS", "DEVICE_DISCONTINUITY"}:
        return "DEGRADED", event
    if event == "ACCEPT_GOOD" or (event == "READY" and state == "UNAVAILABLE"):
        return "OK", "NONE"
    return state, reason


def _union_frames(intervals: list[tuple[int, int]]) -> int:
    end = -1
    total = 0
    for start, stop in sorted(intervals):
        total += max(0, stop - max(start, end))
        end = max(end, stop)
    return total


def loss_totals(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Exact union only when every media-loss fact has comparable source bounds."""
    facts: dict[str, GapFact] = {}
    for raw_event in events:
        if raw_event.get("source") == "AI_TAP":
            continue
        fact = GapFact.from_dict(raw_event)
        if fact.event_id in facts and facts[fact.event_id] != fact:
            raise ValidationError("HEALTH_EVENT_CONFLICT")
        facts[fact.event_id] = fact
    gaps: dict[str, GapFact] = {}
    for fact in sorted(facts.values(), key=lambda e: (e.kind == "CLOSE", e.ordinal)):
        prior = gaps.get(fact.gap_id)
        if prior is not None and any(
            getattr(prior, key) != getattr(fact, key)
            for key in (
                "session_id",
                "capture_run_id",
                "track_id",
                "epoch_id",
                "reason",
                "source",
                "clock_ref",
                "lost_frames",
                "count_quality",
            )
        ):
            raise ValidationError("HEALTH_EVENT_CONFLICT")
        gaps[fact.gap_id] = fact
    media = [e for e in gaps.values() if e.source in {"APP_QUEUE", "DEVICE", "RECOVERY", "STORAGE"}]
    sources: dict[str, int] = {}
    for event in media:
        if event.lost_frames is not None:
            sources[event.source] = sources.get(event.source, 0) + event.lost_frames
    groups: dict[tuple[str, str, str], list[tuple[int, int]]] = {}
    exact = True
    for e in media:
        if e.range_quality != "EXACT_SOURCE" or e.start is None or e.end is None:
            exact = False
            continue
        groups.setdefault((e.track_id, e.epoch_id, e.clock_ref), []).append((e.start, e.end))
    union = sum(_union_frames(intervals) for intervals in groups.values())
    # Different tracks/epochs/clocks are not one common lost-time coordinate.
    comparable = exact and len(groups) <= 1
    return {
        "sources": sources,
        "known_loss_frames": union if comparable else None,
        "known_lower_bound": union if comparable else max(sources.values(), default=0),
        "has_unknown": not exact,
    }


def track_loss(value: dict[str, Any]) -> dict[str, int | None]:
    """Bounded per-epoch interval union for the live/persistent presentation."""
    total = _union_frames([(pair[0], pair[1]) for pair in value.get("loss_ranges", [])])
    unknown = value.get("media_loss_unknown", False)
    return {
        "known_loss_frames": None if unknown else total,
        "known_lower_bound": max(value.get("dropped_frames", 0), value.get("device_lost_frames", 0))
        if unknown
        else total,
    }


def observed_interval(
    start: object, end: object, before_clock: str | None, after_clock: str | None
) -> tuple[int | None, int | None]:
    if (
        before_clock is not None
        and before_clock == after_clock
        and type(start) is int
        and type(end) is int
        and 0 <= start <= end <= 2**63 - 1
    ):
        return start, end
    return None, None


def validate_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    if set(snapshot) - {
        "schema_version",
        "session_id",
        "capture_run_id",
        "process_clock_id",
        "checkpoint_seq",
        "observed_mono_ns",
        "event_ordinal",
        "gate_open_mono_ns",
        "tracks",
        "events",
        "queue",
        "legacy_projection",
    }:
        raise ValidationError("HEALTH_UNREADABLE")
    if snapshot.get("schema_version") != 2 or type(snapshot.get("schema_version")) is not int:
        raise ValidationError("HEALTH_VERSION_UNSUPPORTED")
    for name in ("session_id", "capture_run_id", "process_clock_id"):
        _identifier(snapshot.get(name), name)
    _integer(snapshot.get("checkpoint_seq"), "checkpoint_seq")
    _integer(snapshot.get("observed_mono_ns"), "observed_mono_ns")
    for name in ("event_ordinal", "gate_open_mono_ns"):
        if snapshot.get(name) is not None:
            _integer(snapshot[name], name)
    if "legacy_projection" in snapshot:
        if (
            not isinstance(snapshot["legacy_projection"], dict)
            or len(encoded(snapshot["legacy_projection"]).encode()) > 8 * 1024 * 1024
        ):
            raise ValidationError("HEALTH_UNREADABLE")
    tracks = snapshot.get("tracks")
    if not isinstance(tracks, dict) or not 1 <= len(tracks) <= 64:
        raise ValidationError("HEALTH_UNREADABLE")
    for track, value in tracks.items():
        _identifier(track, "track_id")
        if not isinstance(value, dict) or set(value) - {
            "epoch_id",
            "state",
            "reason",
            "accepted_frames",
            "dropped_frames",
            "last_accepted_sequence",
            "last_observed_mono_ns",
            "gaps",
            "gap_detail_truncated",
            "detail_complete",
            "device_lost_frames",
            "media_loss_unknown",
            "loss_ranges",
            "legacy_prefix_known",
            "count_complete",
        }:
            raise ValidationError("HEALTH_UNREADABLE")
        _identifier(value.get("epoch_id"), "epoch_id")
        if value.get("state") not in STATES:
            raise ValidationError("HEALTH_UNREADABLE")
        for field in ("accepted_frames", "dropped_frames"):
            _integer(value.get(field), field)
        if type(value.get("detail_complete")) is not bool:
            raise ValidationError("HEALTH_UNREADABLE")
        if value.get("reason") not in {
            "STARTING",
            "NONE",
            "UNCLEAN",
            "PAUSED",
            "FINAL",
            "QUEUE_REJECT",
            "BAD_CLOCK",
            "NO_PACKETS",
            "DEVICE_DISCONTINUITY",
            "DEVICE_LOST",
            "STORAGE_FAILED",
        }:
            raise ValidationError("HEALTH_UNREADABLE")
        for name in (
            "gap_detail_truncated",
            "media_loss_unknown",
            "legacy_prefix_known",
            "count_complete",
        ):
            if name in value and type(value[name]) is not bool:
                raise ValidationError("HEALTH_UNREADABLE")
        for name in ("last_accepted_sequence", "last_observed_mono_ns", "device_lost_frames"):
            if value.get(name) is not None:
                _integer(value[name], name)
        if "device_lost_frames" in value:
            _integer(value["device_lost_frames"], "device_lost_frames")
        ranges = value.get("loss_ranges", [])
        if not isinstance(ranges, list) or len(ranges) > MAX_EVENTS:
            raise ValidationError("HEALTH_UNREADABLE")
        for bounds in ranges:
            if not isinstance(bounds, (tuple, list)) or len(bounds) != 2:
                raise ValidationError("HEALTH_UNREADABLE")
            _integer(bounds[0], "range start")
            _integer(bounds[1], "range end", minimum=bounds[0])
        gaps = value.get("gaps", [])
        if not isinstance(gaps, list) or len(gaps) > MAX_EVENTS:
            raise ValidationError("HEALTH_UNREADABLE")
        for gap in gaps:
            if (
                not isinstance(gap, dict)
                or set(gap)
                != {"reason", "first_sequence", "last_sequence", "frame_count", "capture_mono_ns"}
                or gap["reason"] != "QUEUE_DROP"
            ):
                raise ValidationError("HEALTH_UNREADABLE")
            for name in ("first_sequence", "last_sequence", "frame_count", "capture_mono_ns"):
                if gap[name] is not None:
                    _integer(gap[name], name)
    queue = snapshot.get("queue")
    if queue is not None:
        if not isinstance(queue, dict) or set(queue) - {
            "max_blocks",
            "max_bytes",
            "queued_blocks",
            "queued_bytes",
            "accepted_blocks",
            "accepted_frames",
            "accepted_bytes",
            "dropped_blocks",
            "dropped_frames",
            "dropped_bytes",
            "high_water_blocks",
            "high_water_bytes",
            "closed",
        }:
            raise ValidationError("HEALTH_UNREADABLE")
        for name, value in queue.items():
            if name == "closed":
                if type(value) is not bool:
                    raise ValidationError("HEALTH_UNREADABLE")
            else:
                _integer(value, name)
    events = snapshot.get("events")
    if not isinstance(events, list) or len(events) > MAX_EVENTS:
        raise ValidationError("HEALTH_PAYLOAD_TOO_LARGE")
    for value in events:
        event = GapFact.from_dict(value)
        if (event.session_id, event.capture_run_id) != (
            snapshot["session_id"],
            snapshot["capture_run_id"],
        ):
            raise ValidationError("HEALTH_EVENT_CONFLICT")
        if event.track_id not in tracks or event.epoch_id != tracks[event.track_id]["epoch_id"]:
            raise ValidationError("HEALTH_EVENT_CONFLICT")
        if event.source == "CONTROL" and event.clock_ref != snapshot["process_clock_id"]:
            raise ValidationError("HEALTH_EVENT_CONFLICT")
    return snapshot
