"""Bounded recording pipeline with an explicit cutoff and writer acknowledgement.

This first increment accepts PCM blocks from an external source. It does not open
audio devices and makes no hard real-time or power-loss durability guarantees.
"""

from __future__ import annotations

import copy
import queue
import threading
import time
import uuid
from typing import Any

from recoryn.capture import BoundedCaptureQueue
from recoryn.capture.queue import CaptureItem, packet_blocks, queue_byte_budget
from recoryn.domain import AudioFormat, PCMBlock, SessionState, StateConflict, ValidationError
from recoryn.domain.capture_health import (
    CaptureReceipt,
    GapFact,
    stable_id,
    track_loss,
    transition_track,
)
from recoryn.storage import ChunkWriter, Library
from recoryn.storage.library import CaptureControlContext

# Full chunks waiting for the sealer (about 8 s of audio at the default size).
# When it is full the consumer waits; the capture queue records any drops.
SEAL_CAPACITY = 4
_STOP = object()
_PROCESS_CLOCK_ID = uuid.uuid4().hex


def _copy_track(value: dict[str, Any]) -> dict[str, Any]:
    """Copy the closed RAM DTO without recursively walking scalar gap fields."""
    return {
        **value,
        "gaps": [dict(gap) for gap in value.get("gaps", [])],
        "loss_ranges": [list(pair) for pair in value.get("loss_ranges", [])],
    }


class RecordingError(RuntimeError):
    """A safe application error, separate from the underlying diagnostic cause."""


class RecordingService:
    """Own the capture gate, a consumer thread and a sealer thread for a session.

    Control calls (start/pause/resume/stop) must be serialized by the caller.
    submit may be called by multiple producers. The consumer only appends blocks;
    full chunks go through a bounded FIFO to the sealer, which verifies, publishes
    and registers them in order, so sealing never stops the capture queue from
    draining. Pause waits for accepted blocks to be sealed and registered before
    acknowledging; resuming always creates fresh epochs.
    """

    def __init__(
        self,
        library: Library,
        formats: dict[str, AudioFormat],
        *,
        session_id: str | None = None,
        chunk_frames: int = 96_000,
        max_blocks: int = 256,
        max_bytes: int | None = None,
        source_managed: bool = False,
    ) -> None:
        if not formats or chunk_frames <= 0:
            raise ValidationError("Tracks and a positive chunk frame target are required")
        self.library = library
        self.formats = dict(formats)
        self.session_id = session_id or uuid.uuid4().hex
        self.chunk_frames = chunk_frames
        self.max_blocks = max_blocks
        self.max_bytes = (
            queue_byte_budget(self.formats.values()) if max_bytes is None else max_bytes
        )
        self._gate = threading.Lock()
        self._accepting = False
        self._queue: BoundedCaptureQueue | None = None
        self._thread: threading.Thread | None = None
        self._sealer: threading.Thread | None = None
        self._seals: queue.Queue[Any] | None = None
        self._error_lock = threading.Lock()
        self._writer_error: Exception | None = None
        self._epochs: dict[str, str] = {}
        self._history: list[dict[str, Any]] = []
        self._track_health: dict[str, dict[str, Any]] = {}
        self._capture_run_id = ""
        self._health_version = 0
        self._checkpoint_seq = 0
        self._pending_events: list[dict[str, Any]] = []
        self._event_ordinal = 0
        self._health_started = False
        self._last_checkpoint = time.monotonic()
        self._source_managed = source_managed
        self._sources_ack = not source_managed
        self._last_positions: dict[str, int] = {}
        self._control_reason = "STOP"
        self._gate_open_ns: int | None = None
        self._health_deferred = False
        self._defer_marker_pending = False
        self._deferred_health_runs: set[str] = set()
        self._pending_health_markers: set[str] = set()
        self._next_defer_retry = 0.0
        self._persisted_checkpoint: dict[str, Any] | None = None
        self._open_observation_gaps: dict[str, dict[str, Any]] = {}
        self._cutoff_ns: int | None = None
        library.create_session(self.session_id)
        # Recovery and finalization refuse a session this service may still write.
        library.register_live_owner(self.session_id, self)
        self._control_root = library.root
        self._control_instance = library.deletion_history_instance
        self._control_session = self.session_id
        self._control_registration = library.register_capture_controller(self.session_id, self)

    def is_live(self) -> bool:
        """Accepting input, or a consumer or sealer still holds unregistered chunks.

        Library calls this under its root mutex, so it reads state without taking
        the capture gate (whose holders may wait for that mutex).
        """
        return self._accepting or self.worker_alive

    def capture_control_state(self) -> tuple[str, bool, bool, bool]:
        """Observe real termination ACKs without a gate, wait or filesystem I/O.

        Library calls this under its root mutex and separately verifies the
        registered controller, session fence and absence of active storage work.
        Control methods are caller-serialized; every resumed run has a new ID.
        """
        return (
            self._capture_run_id,
            self._sources_ack and not self._accepting,
            self._thread is None or not self._thread.is_alive(),
            self._sealer is None or not self._sealer.is_alive(),
        )

    def _capture_control(self) -> CaptureControlContext:
        """Mint a local stop proof only after this instance's real drain ACK."""
        if (
            self.library.root != self._control_root
            or self.library.deletion_history_instance != self._control_instance
            or self.session_id != self._control_session
            or not all(self.capture_control_state()[1:])
        ):
            raise StateConflict("SESSION_LIVE")
        return self.library.capture_control(self.session_id, self, self._control_registration)

    @property
    def epochs(self) -> dict[str, str]:
        with self._gate:
            return dict(self._epochs)

    @property
    def worker_alive(self) -> bool:
        return any(
            thread is not None and thread.is_alive() for thread in (self._thread, self._sealer)
        )

    def _fail(self, error: Exception) -> None:
        """Keep the first storage failure and stop accepting input."""
        with self._error_lock:
            if self._writer_error is None:
                self._writer_error = error
        with self._gate:
            self._accepting = False
            for track in self._track_health:
                self._track_event(track, "STORAGE_FAILED")

    def health_snapshot(self) -> dict[str, Any]:
        """Nonpersistent health for UI observation; durable totals are sealed on drain."""
        with self._gate:
            result: dict[str, Any] = {
                "accepting": self._accepting,
                "storage_failed": self._writer_error is not None,
                "health_status": "DEFERRED"
                if self._health_deferred or self._deferred_health_runs
                else "OBSERVED",
                "memory_observation": True,
                "persisted_checkpoint": copy.deepcopy(self._persisted_checkpoint),
                "queue": self._queue.snapshot() if self._queue is not None else None,
                "track_health": {
                    track: {
                        **_copy_track(value),
                    }
                    for track, value in self._track_health.items()
                },
            }
        for value in result["track_health"].values():
            if result["health_status"] == "DEFERRED":
                value.update(detail_complete=False, media_loss_unknown=True, count_complete=False)
            value.update(track_loss(value))
        result["tracks"] = {
            track: {
                "accepted_frames": value["accepted_frames"],
                "dropped_frames": value["dropped_frames"],
            }
            for track, value in result["track_health"].items()
        }
        return result

    @property
    def storage_failed(self) -> bool:
        return self._writer_error is not None

    def _defer_health(self) -> None:
        """Ancillary observation failure never closes the PCM gate."""
        with self._gate:
            self._health_deferred = True
            self._deferred_health_runs.add(self._capture_run_id)
            self._pending_health_markers.add(self._capture_run_id)
            self._defer_marker_pending = True
        try:
            self.library.note_capture_health_deferred(self.session_id)
        except Exception:
            pass
        self._retry_defer_markers(force=True)

    def _retry_defer_markers(self, *, force: bool = False) -> None:
        """Bound attempts; retain failed facts for the next control/consumer opportunity."""
        started = time.monotonic()
        if not force and started < self._next_defer_retry:
            return
        deadline = started + 0.05
        for _ in range(2):
            with self._gate:
                if not self._pending_health_markers or time.monotonic() >= deadline:
                    break
                run_id = next(iter(self._pending_health_markers))
            try:
                self.library.defer_capture_health(self.session_id, run_id)
            except Exception:
                continue
            with self._gate:
                self._pending_health_markers.discard(run_id)
        with self._gate:
            self._defer_marker_pending = bool(self._pending_health_markers)
            self._next_defer_retry = started + 1.0 if self._defer_marker_pending else 0.0

    def _transition(self, target: SessionState) -> None:
        session = self.library.get_session(self.session_id)
        self.library.transition(self.session_id, target, session.state_version)

    def _mark_interrupted(self) -> None:
        session = self.library.get_session(self.session_id)
        if session.state != SessionState.INTERRUPTED:
            self.library.transition(
                self.session_id, SessionState.INTERRUPTED, session.state_version
            )

    def start(self) -> None:
        if self.library.get_session(self.session_id).state != SessionState.CREATED:
            raise RecordingError("START_REQUIRES_CREATED")
        self._begin_epoch()

    def _begin_epoch(self) -> None:
        self._retry_defer_markers(force=True)
        with self._gate:
            self._queue = BoundedCaptureQueue(self.max_blocks, self.max_bytes)
            self._epochs = {track: uuid.uuid4().hex for track in self.formats}
            self._track_health = {
                track: {
                    "epoch_id": epoch,
                    "accepted_frames": 0,
                    "dropped_frames": 0,
                    "last_accepted_sequence": None,
                    "gaps": [],
                    "state": "UNAVAILABLE",
                    "reason": "STARTING",
                    "detail_complete": True,
                    "device_lost_frames": 0,
                    "media_loss_unknown": False,
                    "loss_ranges": [],
                }
                for track, epoch in self._epochs.items()
            }
            self._writer_error = None
            self._capture_run_id = uuid.uuid4().hex
            self._checkpoint_seq = self._event_ordinal = 0
            self._pending_events = []
            self._last_positions = {}
            self._sources_ack = not self._source_managed
            self._health_started = False
            self._gate_open_ns = None
            self._health_deferred = False
            self._defer_marker_pending = bool(self._pending_health_markers)
            self._persisted_checkpoint = None
            self._open_observation_gaps = {}
            self._cutoff_ns = None
            self._seals = queue.Queue(maxsize=SEAL_CAPACITY)
            self._sealer = threading.Thread(
                target=self._seal_loop,
                args=(self._seals,),
                name=f"recoryn-sealer-{self.session_id}",
                daemon=False,
            )
            self._thread = threading.Thread(
                target=self._consume, name=f"recoryn-writer-{self.session_id}", daemon=False
            )
        try:
            self._sealer.start()
            self._thread.start()
        except BaseException:
            # G15R-02: a thread that cannot start leaves nothing running that keeps
            # the session live. The sealer only stops on _STOP, which the consumer
            # would have sent; the handles go so join and is_live see no workers.
            if self._sealer.is_alive():
                self._seals.put(_STOP)
                self._sealer.join()
            self._queue.close()
            self._sealer = self._thread = None
            raise
        try:
            session = self.library.get_session(self.session_id)
            self._health_version = self.library.begin_capture_health(
                self.session_id, self._health_record(), expected_state_version=session.state_version
            )
        except Exception:
            # Health is ancillary; only the session state is required for capture.
            self._defer_health()
            try:
                if self.library.get_session(self.session_id).state != SessionState.RECORDING:
                    self._transition(SessionState.RECORDING)
            except BaseException:
                self._queue.close()
                self._thread.join()
                self._sealer.join()
                raise
        with self._gate:
            self._health_started = True
            self._last_checkpoint = time.monotonic()
            if not self._health_deferred:
                self._persisted_checkpoint = {
                    "checkpoint_seq": 0,
                    "health_version": self._health_version,
                    "tracks": {track: 0 for track in self.formats},
                }
            self._gate_open_ns = time.monotonic_ns()
            self._accepting = True

    def _health_record(self) -> dict[str, Any]:
        with self._gate:
            return {
                "schema_version": 2,
                "session_id": self.session_id,
                "capture_run_id": self._capture_run_id,
                "process_clock_id": _PROCESS_CLOCK_ID,
                "checkpoint_seq": self._checkpoint_seq,
                "event_ordinal": self._event_ordinal,
                "gate_open_mono_ns": self._gate_open_ns,
                "observed_mono_ns": time.monotonic_ns(),
                "tracks": {
                    track: _copy_track(value) for track, value in self._track_health.items()
                },
                "events": [dict(event) for event in self._pending_events],
                "queue": self._queue.snapshot() if self._queue is not None else None,
            }

    def _gap(
        self,
        track: str,
        reason: str,
        *,
        start: int | None = None,
        end: int | None = None,
        frames: int | None = None,
        source_clock: bool = False,
    ) -> None:
        health = self._track_health[track]
        if reason == "NO_PACKETS" and track in self._open_observation_gaps:
            return
        self._event_ordinal += 1
        identity = stable_id(self.session_id, self._capture_run_id, track, self._event_ordinal)
        source = {
            "QUEUE_DROP": "APP_QUEUE",
            "STORAGE_FAILED": "STORAGE",
            "PAUSE": "CONTROL",
            "SUSPEND": "CONTROL",
        }.get(reason, "DEVICE")
        quality = (
            "EXACT_SOURCE"
            if source_clock and start is not None and end is not None
            else "OBSERVED_CONTROL"
            if source == "CONTROL"
            else "UNKNOWN"
        )
        if source == "DEVICE" and frames is not None:
            health["device_lost_frames"] += frames
        if source != "CONTROL":
            if quality == "EXACT_SOURCE":
                assert start is not None and end is not None
                ranges = health["loss_ranges"]
                if ranges and start <= ranges[-1][1] and end >= ranges[-1][0]:
                    ranges[-1][0] = min(ranges[-1][0], start)
                    ranges[-1][1] = max(ranges[-1][1], end)
                elif len(ranges) < 256:
                    ranges.append([start, end])
                else:
                    health["media_loss_unknown"] = True
                while (
                    len(ranges) > 1
                    and ranges[-1][0] <= ranges[-2][1]
                    and ranges[-1][1] >= ranges[-2][0]
                ):
                    end_range = ranges.pop()
                    ranges[-1] = [
                        min(ranges[-1][0], end_range[0]),
                        max(ranges[-1][1], end_range[1]),
                    ]
            else:
                health["media_loss_unknown"] = True
        if len(self._pending_events) >= 256 and reason not in {
            "PAUSE",
            "SUSPEND",
            "DEVICE_LOST",
            "STORAGE_FAILED",
        }:
            health["detail_complete"] = False
            return
        fact = GapFact(
            self.session_id,
            self._capture_run_id,
            track,
            health["epoch_id"],
            identity,
            identity,
            self._event_ordinal,
            reason,
            source,
            "source" if quality == "EXACT_SOURCE" else _PROCESS_CLOCK_ID,
            start,
            end,
            quality,
            frames,
            "EXACT" if frames is not None else "UNKNOWN",
            end is None,
            True,
            observation_bounds=(None, None)
            if quality == "EXACT_SOURCE"
            else (health.get("last_observed_mono_ns"), time.monotonic_ns()),
        ).to_dict()
        if reason == "NO_PACKETS":
            self._open_observation_gaps[track] = fact
        if len(self._pending_events) < 256:
            self._pending_events.append(fact)
        else:
            health["detail_complete"] = False
            if reason in {"PAUSE", "SUSPEND", "DEVICE_LOST", "STORAGE_FAILED"}:
                # Keep control/lifetime facts; omitted detail is explicit, counters remain.
                for index, old in enumerate(self._pending_events):
                    if old["reason"] in {"QUEUE_DROP", "DEVICE_DISCONTINUITY", "NO_PACKETS"}:
                        self._pending_events.pop(index)
                        self._pending_events.append(fact)
                        break

    def _close_observation_gap(self, track: str) -> None:
        opening = self._open_observation_gaps.pop(track, None)
        if opening is None:
            return
        self._event_ordinal += 1
        event = {
            **opening,
            "event_id": stable_id(opening["gap_id"], "close"),
            "kind": "CLOSE",
            "open": False,
            "ordinal": self._event_ordinal,
            "observation_bounds": (opening["observation_bounds"][0], time.monotonic_ns()),
        }
        if len(self._pending_events) < 256:
            self._pending_events.append(event)
        else:
            self._track_health[track]["detail_complete"] = False

    def _track_event(self, track: str, event: str) -> None:
        health = self._track_health[track]
        health["state"], health["reason"] = transition_track(
            health["state"], health["reason"], event
        )

    def observe_health(self, track: str, epoch: str, event: dict[str, Any]) -> bool:
        """Current source observations only; backend rejected totals are never re-added."""
        with self._gate:
            if self._epochs.get(track) != epoch or not self._health_started or not self._accepting:
                return False
            try:
                kind = event.get("event")
                if kind == "ready":
                    self._track_event(track, "READY")
                elif kind == "error":
                    if self._track_health[track]["reason"] != "DEVICE_LOST":
                        self._track_event(track, "DEVICE_LOST")
                        self._gap(track, "DEVICE_LOST")
                elif kind == "idle":
                    self._track_event(track, "NO_PACKETS")
                    self._gap(track, "NO_PACKETS")
            except Exception:
                self._health_deferred = self._defer_marker_pending = True
            return True

    def sources_released(self) -> None:
        """Called by the control owner only after every source.stop returned."""
        with self._gate:
            self._sources_ack = True

    def _checkpoint_health(self, *, force: bool = False) -> None:
        if self._defer_marker_pending:
            if self._health_deferred and self._capture_run_id not in self._deferred_health_runs:
                self._defer_health()
            else:
                self._retry_defer_markers(force=force)
        if self._health_deferred:
            return
        try:
            self._write_health_checkpoint(force=force)
        except Exception:
            self._defer_health()

    def _write_health_checkpoint(self, *, force: bool = False) -> None:
        if self._health_deferred:
            return
        if not self._health_started or (not force and time.monotonic() - self._last_checkpoint < 1):
            return
        with self._gate:
            self._checkpoint_seq += 1
        snapshot = self._health_record()
        try:
            version = self.library.checkpoint_capture_health(
                self.session_id, snapshot, expected_health_version=self._health_version
            )
        except StateConflict as error:
            if str(error) != "HEALTH_SNAPSHOT_CHANGED":
                raise
            # An opportunistic checkpoint may be deferred; pending facts stay in RAM.
            try:
                current = self.library.capture_health(self.session_id, for_capture=True)
            except StateConflict as changed:
                if str(changed) != "HEALTH_SNAPSHOT_CHANGED":
                    raise
                return
            with self._gate:
                if (
                    current.get("capture_run_id") != self._capture_run_id
                    or current.get("run_status") != "OPEN"
                ):
                    raise StateConflict("HEALTH_EVENT_CONFLICT") from error
                self._health_version = current["health_version"]
                self._checkpoint_seq = max(self._checkpoint_seq, current["checkpoint_seq"])
            return
        with self._gate:
            self._health_version = version
            committed = {e["event_id"] for e in snapshot["events"]}
            self._pending_events = [
                e for e in self._pending_events if e["event_id"] not in committed
            ]
            self._last_checkpoint = time.monotonic()
            self._persisted_checkpoint = {
                "checkpoint_seq": snapshot["checkpoint_seq"],
                "health_version": version,
                "tracks": {k: v["dropped_frames"] for k, v in snapshot["tracks"].items()},
            }

    def submit(self, item: CaptureItem) -> bool:
        fragments = packet_blocks(item)
        block = fragments[0]
        with self._gate:
            if not self._accepting:
                return False
            if (
                block.session_id != self.session_id
                or block.track_id not in self.formats
                or block.format != self.formats[block.track_id]
                or block.epoch_id != self._epochs[block.track_id]
            ):
                raise ValidationError("Block does not match the active track and epoch")
            assert self._queue is not None
            if self._track_health[block.track_id]["reason"] == "DEVICE_LOST":
                return False
            accepted = (
                self._queue.offer(block)
                if isinstance(item, PCMBlock)
                else self._queue.offer_packet(fragments)
            )
            try:
                if isinstance(item, PCMBlock):
                    self._observe_block(block, accepted)
                else:
                    self._observe_block(
                        block, accepted, packet_frames=sum(part.frame_count for part in fragments)
                    )
            except Exception:
                self._health_deferred = self._defer_marker_pending = True
            return accepted

    def _observe_block(
        self, block: PCMBlock, accepted: bool, *, packet_frames: int | None = None
    ) -> None:
        frame_count = block.frame_count if packet_frames is None else packet_frames
        position = block.device_frame_position
        if position is not None and position + frame_count >= 2**63:
            position = None
        health = self._track_health[block.track_id]
        if accepted:
            self._close_observation_gap(block.track_id)
            health["accepted_frames"] += frame_count
            health["last_accepted_sequence"] = block.sequence
            health["last_observed_mono_ns"] = time.monotonic_ns()
            self._track_event(
                block.track_id,
                "BAD_CLOCK" if "TIMESTAMP_ERROR" in block.flags else "ACCEPT_GOOD",
            )
        else:
            health["dropped_frames"] += frame_count
            self._track_event(block.track_id, "QUEUE_REJECT")
            position = None if "TIMESTAMP_ERROR" in block.flags else position
            self._gap(
                block.track_id,
                "QUEUE_DROP",
                start=position,
                end=position + frame_count if position is not None else None,
                frames=frame_count,
                source_clock=True,
            )
            gaps: list[dict[str, Any]] = health["gaps"]
            # Coalesce adjacent drops to keep metadata bounded under sustained overload.
            if gaps and gaps[-1]["last_sequence"] + 1 == block.sequence:
                gaps[-1]["last_sequence"] = block.sequence
                gaps[-1]["frame_count"] += frame_count
            elif len(gaps) < 256:
                gaps.append(
                    {
                        "reason": "QUEUE_DROP",
                        "first_sequence": block.sequence,
                        "last_sequence": block.sequence,
                        "frame_count": frame_count,
                        "capture_mono_ns": block.capture_mono_ns,
                    }
                )
            else:
                health["gap_detail_truncated"] = True
        previous = self._last_positions.get(block.track_id)
        if position is not None and "TIMESTAMP_ERROR" not in block.flags:
            if previous is not None and position > previous:
                self._track_event(block.track_id, "DEVICE_DISCONTINUITY")
                self._gap(
                    block.track_id,
                    "DEVICE_DISCONTINUITY",
                    start=previous,
                    end=position,
                    frames=position - previous,
                    source_clock=True,
                )
            elif (
                "DATA_DISCONTINUITY" in block.flags or previous is not None and position < previous
            ):
                self._track_event(block.track_id, "DEVICE_DISCONTINUITY")
                self._gap(block.track_id, "DEVICE_DISCONTINUITY")
            self._last_positions[block.track_id] = position + frame_count
        elif "DATA_DISCONTINUITY" in block.flags:
            self._last_positions.pop(block.track_id, None)
            self._gap(block.track_id, "DEVICE_DISCONTINUITY")
        else:
            # A bad/missing clock packet still contains accepted PCM; do not
            # bridge over it and falsely count those frames as device loss.
            self._last_positions.pop(block.track_id, None)
            if not health["media_loss_unknown"]:
                self._gap(block.track_id, "DEVICE_DISCONTINUITY")

    def _hand_off(self, seals: queue.Queue[Any], writer: ChunkWriter) -> None:
        """Give a full chunk to the sealer; wait while its FIFO is full."""
        while True:
            if self._writer_error is not None:
                raise RecordingError("SEALER_FAILED")
            try:
                seals.put(writer, timeout=0.1)
                return
            except queue.Full:
                continue

    def _consume(self) -> None:
        writers: dict[tuple[str, str], ChunkWriter] = {}
        frames: dict[tuple[str, str], int] = {}
        pending = self._queue
        seals = self._seals
        assert pending is not None and seals is not None
        try:
            while True:
                if self._writer_error is not None:
                    raise RecordingError("SEALER_FAILED")
                try:
                    block = pending.get(timeout=0.1)
                except queue.Empty:
                    self._checkpoint_health()
                    continue
                except EOFError:
                    break
                key = (block.track_id, block.epoch_id)
                if key not in writers:
                    writers[key] = ChunkWriter(self.library.root, block)
                    frames[key] = 0
                writers[key].append(block)
                if block.fragment_index + 1 == block.fragment_count:
                    self._checkpoint_health()
                frames[key] += block.frame_count
                if (
                    frames[key] >= self.chunk_frames
                    and block.fragment_index + 1 == block.fragment_count
                ):
                    # The sealer owns it from here; the writer stays active until
                    # its catalog registration, so a delete waits for it.
                    self._hand_off(seals, writers[key])
                    del writers[key]
                    frames.pop(key)
            for key in list(writers):
                self._hand_off(seals, writers[key])
                del writers[key]
        except Exception as error:
            self._fail(error)
            pending.close()
            for writer in writers.values():
                try:
                    writer.abort()
                except Exception:
                    # The original failure remains primary. Recovery inspects staging.
                    pass
            try:
                self._mark_interrupted()
            except Exception:
                # A failed metadata store/deletion intent must not restart capture.
                # health_snapshot still reports the in-memory storage failure.
                pass
        finally:
            # The sealer drains everything handed off before this marker.
            seals.put(_STOP)

    def _seal_loop(self, seals: queue.Queue[Any]) -> None:
        """Verify, publish and register handed-off chunks in FIFO order."""
        failed = False
        while True:
            item = seals.get()
            if item is _STOP:
                return
            if failed or self._writer_error is not None:
                try:
                    item.abort()  # staging stays for recovery
                except Exception:
                    pass
                continue
            item.hold()
            try:
                descriptor = item.seal()
                # The held writer's capability lets registration skip a second full
                # verification of the bundle this sealer verified once.
                self.library.register_chunk(item.capability or descriptor)
            except Exception as error:
                failed = True
                self._fail(error)
                try:
                    item.abort()  # idempotent; an unsealed staging stays for recovery
                except Exception:
                    pass
                try:
                    self._mark_interrupted()
                except Exception:
                    pass
            finally:
                item.unhold()

    def _join_workers(self, timeout: float | None) -> None:
        deadline = None if timeout is None else time.monotonic() + timeout
        for thread in (self._thread, self._sealer):
            if thread is None:
                continue
            thread.join(None if deadline is None else max(0.0, deadline - time.monotonic()))
            if thread.is_alive():
                # Keep storage ownership until the caller has joined the writer.
                raise RecordingError("WRITER_ACK_PENDING")

    def _drain(self, timeout: float | None) -> None:
        with self._gate:
            self._accepting = False
            if self._queue is not None:
                self._queue.close()
            first_cutoff = self._cutoff_ns is None
            if first_cutoff:
                self._cutoff_ns = time.monotonic_ns()
                try:
                    for track in self._track_health:
                        self._close_observation_gap(track)
                except Exception:
                    self._health_deferred = self._defer_marker_pending = True
            cutoff = self._cutoff_ns
            if first_cutoff and self._control_reason in {"PAUSE", "SUSPEND"}:
                try:
                    for track in self._track_health:
                        self._gap(track, self._control_reason, start=cutoff)
                except Exception:
                    self._health_deferred = self._defer_marker_pending = True
        self._join_workers(timeout)
        if self._defer_marker_pending:
            if self._health_deferred and self._capture_run_id not in self._deferred_health_runs:
                self._defer_health()
            else:
                self._retry_defer_markers(force=True)
        try:
            if self._writer_error is None and not self._health_deferred:
                with self._gate:
                    for track in self._track_health:
                        self._track_event(
                            track,
                            "PAUSE_CONFIRMED"
                            if self._control_reason in {"PAUSE", "SUSPEND"}
                            else "STOP_CONFIRMED",
                        )
                    self._checkpoint_seq += 1
                snapshot = self._health_record()
                self._health_version = self.library.finish_capture_health(
                    self.session_id,
                    snapshot,
                    expected_health_version=self._health_version,
                    receipt=CaptureReceipt(
                        self._capture_run_id,
                        not self._accepting,
                        self._sources_ack,
                        not self.worker_alive,
                        False,
                    ),
                )
                with self._gate:
                    self._persisted_checkpoint = {
                        "checkpoint_seq": snapshot["checkpoint_seq"],
                        "health_version": self._health_version,
                        "tracks": {k: v["dropped_frames"] for k, v in snapshot["tracks"].items()},
                    }
                    self._pending_events = []
                    self._health_started = False
                    self._queue = None
            elif self._writer_error is not None:
                # Preserve the last observable failure/prefix without issuing a close ACK.
                self._checkpoint_health(force=True)
        except Exception:
            self._defer_health()
        if self._writer_error is not None:
            self._mark_interrupted()
            raise RecordingError("STORAGE_FAILED_PARTIAL_MEDIA_PRESERVED") from self._writer_error

    def pause(self, timeout: float | None = 5.0, *, reason: str = "PAUSE") -> None:
        if self.library.get_session(self.session_id).state != SessionState.RECORDING:
            raise RecordingError("PAUSE_REQUIRES_RECORDING")
        if reason not in {"PAUSE", "SUSPEND"}:
            raise ValidationError("HEALTH_UNREADABLE")
        self._control_reason = reason
        self._drain(timeout)
        self._transition(SessionState.PAUSED)

    def resume(self) -> None:
        if self.library.get_session(self.session_id).state != SessionState.PAUSED:
            raise RecordingError("RESUME_REQUIRES_PAUSED")
        self._begin_epoch()

    def stop(
        self, timeout: float | None = 5.0, *, health_extra: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        state = self.library.get_session(self.session_id).state
        if state == SessionState.FINALIZED:
            return self.library.finalize_session(
                self.session_id, capture_control=self._capture_control()
            )
        if state not in {SessionState.CREATED, SessionState.RECORDING, SessionState.PAUSED}:
            raise RecordingError("STOP_REQUIRES_ACTIVE_SESSION")
        if state == SessionState.RECORDING:
            self._control_reason = "STOP"
            self._drain(timeout)
        capture_control = self._capture_control()
        if health_extra is not None:
            try:
                health = self.library.capture_health(self.session_id)
                health.update(health_extra)
                self.library.record_capture_health(self.session_id, health)
            except Exception:
                self._defer_health()
        pending_health = self._health_deferred or bool(self._deferred_health_runs)
        try:
            pending_health = pending_health or self.library.capture_health_pending(self.session_id)
        except Exception:
            self._defer_health()
            pending_health = True
        if pending_health:
            if self.library.get_session(self.session_id).state == SessionState.RECORDING:
                self._transition(SessionState.PAUSED)
            try:
                recovery = self.library.recover_session(
                    self.session_id, capture_control=capture_control
                )
            except Exception:
                recovery = {
                    "health_recovery": {"status": "DEFERRED", "code": "HEALTH_RECOVERY_PENDING"}
                }
            if recovery.get("health_recovery", {}).get("status") == "DEFERRED":
                chunks = self.library.chunks(self.session_id)
                return {
                    "session_id": self.session_id,
                    "state": self.library.get_session(self.session_id).state.value,
                    "chunk_count": len(chunks),
                    "frame_count": sum(c.frame_count for c in chunks),
                    "manifest_sync_pending": True,
                    "finalized": False,
                    "health_status": "DEFERRED",
                    "health_recovery": recovery["health_recovery"],
                }
            with self._gate:
                self._health_deferred = self._defer_marker_pending = False
                self._deferred_health_runs.clear()
                self._pending_health_markers.clear()
        self._transition(SessionState.FINALIZING)
        return self.library.finalize_session(self.session_id, capture_control=capture_control)

    def join_writer(self) -> None:
        """Retain the Library lock until a timed-out writer has actually stopped."""
        with self._gate:
            self._accepting = False
            if self._queue is not None:
                self._queue.close()
        self._join_workers(None)
