"""Bounded recording pipeline with an explicit cutoff and writer acknowledgement.

This first increment accepts PCM blocks from an external source. It does not open
audio devices and makes no hard real-time or power-loss durability guarantees.
"""

from __future__ import annotations

import queue
import threading
import time
import uuid
from typing import Any

from recoryn.capture import BoundedCaptureQueue
from recoryn.domain import AudioFormat, PCMBlock, SessionState, ValidationError
from recoryn.storage import ChunkWriter, Library

# Full chunks waiting for the sealer (about 8 s of audio at the default size).
# When it is full the consumer waits; the capture queue records any drops.
SEAL_CAPACITY = 4
_STOP = object()


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
        max_bytes: int = 16 * 1024 * 1024,
    ) -> None:
        if not formats or chunk_frames <= 0:
            raise ValidationError("Tracks and a positive chunk frame target are required")
        self.library = library
        self.formats = dict(formats)
        self.session_id = session_id or uuid.uuid4().hex
        self.chunk_frames = chunk_frames
        self.max_blocks = max_blocks
        self.max_bytes = max_bytes
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
        library.create_session(self.session_id)
        # Recovery and finalization refuse a session this service may still write.
        library.register_live_owner(self.session_id, self)

    def is_live(self) -> bool:
        """Accepting input, or a consumer or sealer still holds unregistered chunks.

        Library calls this under its root mutex, so it reads state without taking
        the capture gate (whose holders may wait for that mutex).
        """
        return self._accepting or self.worker_alive

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

    def health_snapshot(self) -> dict[str, Any]:
        """Nonpersistent health for UI observation; durable totals are sealed on drain."""
        with self._gate:
            return {
                "accepting": self._accepting,
                "storage_failed": self._writer_error is not None,
                "queue": self._queue.snapshot() if self._queue is not None else None,
                "tracks": {
                    track: {
                        "accepted_frames": value["accepted_frames"],
                        "dropped_frames": value["dropped_frames"],
                    }
                    for track, value in self._track_health.items()
                },
            }

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
                }
                for track, epoch in self._epochs.items()
            }
            self._writer_error = None
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
            self._sealer.start()
            self._thread.start()
            try:
                self._transition(SessionState.RECORDING)
            except BaseException:
                # No input is admitted before the durable start acknowledgement.
                self._queue.close()
                self._thread.join()
                self._sealer.join()
                raise
            self._accepting = True

    def submit(self, block: PCMBlock) -> bool:
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
            accepted = self._queue.offer(block)
            health = self._track_health[block.track_id]
            if accepted:
                health["accepted_frames"] += block.frame_count
                health["last_accepted_sequence"] = block.sequence
            else:
                health["dropped_frames"] += block.frame_count
                gaps: list[dict[str, Any]] = health["gaps"]
                # Coalesce adjacent drops to keep metadata bounded under sustained overload.
                if gaps and gaps[-1]["last_sequence"] + 1 == block.sequence:
                    gaps[-1]["last_sequence"] = block.sequence
                    gaps[-1]["frame_count"] += block.frame_count
                elif len(gaps) < 256:
                    gaps.append(
                        {
                            "reason": "QUEUE_DROP",
                            "first_sequence": block.sequence,
                            "last_sequence": block.sequence,
                            "frame_count": block.frame_count,
                            "capture_mono_ns": block.capture_mono_ns,
                        }
                    )
                else:
                    health["gap_detail_truncated"] = True
            return accepted

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
                    continue
                except EOFError:
                    break
                key = (block.track_id, block.epoch_id)
                if key not in writers:
                    writers[key] = ChunkWriter(self.library.root, block)
                    frames[key] = 0
                writers[key].append(block)
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
        self._join_workers(timeout)
        if self._queue is not None:
            self._history.append({"tracks": self._track_health, "queue": self._queue.snapshot()})
            self._queue = None
        try:
            self.library.record_capture_health(self.session_id, {"epochs": self._history})
        except Exception as error:
            try:
                self._transition(SessionState.INTERRUPTED)
            except Exception:
                # If even the state cannot be stored, recovery sees an unclean run.
                pass
            raise RecordingError("HEALTH_PERSISTENCE_FAILED_MEDIA_PRESERVED") from error
        if self._writer_error is not None:
            self._mark_interrupted()
            raise RecordingError("STORAGE_FAILED_PARTIAL_MEDIA_PRESERVED") from self._writer_error

    def pause(self, timeout: float | None = 5.0) -> None:
        if self.library.get_session(self.session_id).state != SessionState.RECORDING:
            raise RecordingError("PAUSE_REQUIRES_RECORDING")
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
            return self.library.finalize_session(self.session_id)
        if state not in {SessionState.CREATED, SessionState.RECORDING, SessionState.PAUSED}:
            raise RecordingError("STOP_REQUIRES_ACTIVE_SESSION")
        if state == SessionState.RECORDING:
            self._drain(timeout)
        if health_extra is not None:
            try:
                health = self.library.capture_health(self.session_id)
                health.update(health_extra)
                self.library.record_capture_health(self.session_id, health)
            except Exception as error:
                try:
                    self._mark_interrupted()
                except Exception:
                    pass
                raise RecordingError("HEALTH_PERSISTENCE_FAILED_MEDIA_PRESERVED") from error
        self._transition(SessionState.FINALIZING)
        return self.library.finalize_session(self.session_id)

    def join_writer(self) -> None:
        """Retain the Library lock until a timed-out writer has actually stopped."""
        with self._gate:
            self._accepting = False
            if self._queue is not None:
                self._queue.close()
        self._join_workers(None)
