"""Device lifecycle orchestration, independent of Qt and inference workers."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import Any, Protocol

from recoryn.app.recording import RecordingError, RecordingService
from recoryn.app.status import CaptureProgress
from recoryn.capture.queue import CaptureItem, packet_blocks
from recoryn.domain import AudioFormat, PCMBlock, SessionState, StateConflict
from recoryn.storage import Library


class CaptureSource(Protocol):
    @property
    def running(self) -> bool: ...

    def start(
        self,
        session_id: str,
        track_id: str,
        epoch_id: str,
        submit: Callable[[CaptureItem], bool],
        on_health: Callable[[dict[str, Any]], None],
    ) -> AudioFormat: ...

    def stop(self, timeout: float = 5.0) -> None: ...


@dataclass(frozen=True, slots=True)
class TrackSelection:
    track_id: str
    device_id: str
    loopback: bool
    format: AudioFormat


class DesktopRecorder:
    """Control methods are caller-serialized; sources acknowledge before state changes.

    Source callbacks only submit to the recording queue and replace a bounded meter
    snapshot. Meter conversion, UI, and inference run elsewhere. A failed device is
    reported independently; it cannot silently select a replacement endpoint.
    """

    def __init__(
        self,
        library: Library,
        source_factory: Callable[[str, bool], CaptureSource],
    ) -> None:
        self.library = library
        self._factory = source_factory
        self.recording: RecordingService | None = None
        self._sources: dict[str, CaptureSource] = {}
        self._selections: tuple[TrackSelection, ...] = ()
        self._lock = threading.Lock()
        self._meters: dict[str, PCMBlock] = {}
        self._health: list[dict[str, Any]] = []
        self._native_formats: dict[str, dict[str, Any]] = {}
        self._run_generation = 0
        self._control_mode = "IDLE"
        self._ready: set[str] = set()
        self._accepted_frames = 0
        self._failure = False
        self._ack_pending = False
        self._manifest_sync_pending = False

    def _begin_run(self) -> None:
        with self._lock:
            self._run_generation += 1
            self._control_mode = "STARTING"
            self._ready.clear()
            self._accepted_frames = 0
            self._failure = self._ack_pending = False
            self._manifest_sync_pending = False

    def capture_progress(self) -> CaptureProgress:
        # Never wait for the recording gate while holding the callback lock.
        with self._lock:
            recorder, generation = self.recording, self._run_generation
        if recorder is None:
            return CaptureProgress()
        health = recorder.health_snapshot()
        epochs = tuple(sorted(recorder.epochs.items()))
        with self._lock:
            return CaptureProgress(
                recorder.session_id,
                generation,
                epochs,
                self._control_mode,
                self._ready == {item.track_id for item in self._selections},
                self._accepted_frames,
                bool(health["accepting"]),
                bool(health["storage_failed"]),
                recorder is self.recording and generation == self._run_generation,
                self._failure,
                self._ack_pending,
                self._manifest_sync_pending,
            )

    @property
    def session_id(self) -> str | None:
        return self.recording.session_id if self.recording else None

    def start(self, selections: tuple[TrackSelection, ...]) -> str:
        if self.recording and self.library.get_session(self.recording.session_id).state in {
            SessionState.CREATED,
            SessionState.RECORDING,
            SessionState.PAUSED,
        }:
            raise StateConflict("RECORDING_ALREADY_ACTIVE")
        if self.recording is not None:
            # INTERRUPTED describes media state, not acknowledgement of the old
            # device/writer lifetimes. Retain both handles if close cannot ack.
            self.close()
        if not selections or len({item.track_id for item in selections}) != len(selections):
            raise StateConflict("SELECT_DISTINCT_TRACKS")
        self._selections = selections
        self._sources = {}
        with self._lock:
            self._meters.clear()
            self._health.clear()
            self._native_formats.clear()
        self._begin_run()
        try:
            self.recording = RecordingService(
                self.library,
                {item.track_id: item.format for item in selections},
                source_managed=True,
            )
            self.recording.start()
        except Exception:
            with self._lock:
                self._control_mode = "START_FAILED"
            raise
        self._open_sources()
        return self.recording.session_id

    def _submit(self, item: CaptureItem, *, generation: int | None = None) -> bool:
        fragments = packet_blocks(item)
        block = fragments[0]
        with self._lock:
            recorder, run = self.recording, self._run_generation
        if recorder is None:
            return False
        if (
            generation is not None
            and generation != run
            or block.session_id != recorder.session_id
            or recorder.epochs.get(block.track_id) != block.epoch_id
        ):
            return False
        # Epoch access waits for RecordingService._gate, outside the callback lock.
        # Stop/pause only suppress REC: in-flight PCM still belongs to the open epoch.
        with self._lock:
            if run != self._run_generation or recorder is not self.recording:
                return False
        accepted = recorder.submit(item)
        if not accepted and (
            recorder.storage_failed
            if hasattr(recorder, "storage_failed")
            else recorder.health_snapshot()["storage_failed"]
        ):
            raise RecordingError("STORAGE_FAILED_CAPTURE_STOP")
        with self._lock:
            if run != self._run_generation or recorder is not self.recording:
                return accepted
            if accepted:
                self._accepted_frames += sum(part.frame_count for part in fragments)
            self._meters[block.track_id] = fragments[-1]
        return accepted

    def _on_health(
        self,
        track_id: str,
        event: dict[str, Any],
        *,
        generation: int | None = None,
        epoch: str | None = None,
    ) -> None:
        # Never acquire the recording gate while holding the desktop callback lock.
        with self._lock:
            recorder, run = self.recording, self._run_generation
            if generation is not None and generation != run:
                return
        if recorder is not None and epoch is not None:
            if recorder.epochs.get(track_id) != epoch:
                return
            recorder.observe_health(track_id, epoch, event)
        kind = event.get("event")
        metadata = (
            {
                key: event[key]
                for key in ("format", "valid_bits", "container_bits", "channel_mask")
                if key in event
            }
            if kind == "ready"
            else {}
        )
        if kind == "stopped" and event.get("release_ack") is False:
            event = {**event, "code": "DEVICE_RELEASE_UNCONFIRMED"}
        warning = True
        if kind in {"ready", "packet", "stopped"} and not event.get("code"):
            if kind != "packet" or not (set(event.get("flags", ())) - {"SILENT"}):
                warning = False
            else:
                event = {**event, "code": "CAPTURE_PACKET_FLAGS"}
        safe = {
            key: value
            for key, value in event.items()
            if key
            in {"code", "running", "dropped_frames", "unknown_frames", "clock_quality", "flags"}
            and isinstance(value, (str, int, bool, type(None), tuple, list))
        }
        safe["track_id"] = track_id
        with self._lock:
            if run != self._run_generation or recorder is not self.recording:
                return
            if kind == "error" and self._control_mode in {"STARTING", "ACTIVE"}:
                self._failure = True
                self._ready.discard(track_id)
            if metadata:
                self._native_formats[track_id] = metadata
            if kind in {"error", "stopped"}:
                self._meters.pop(track_id, None)
            if warning:
                if len(self._health) >= 256:
                    self._health.pop(0)
                self._health.append(safe)

    def _open_sources(self) -> None:
        assert self.recording is not None
        generation = self._run_generation
        try:
            for item in self._selections:
                source = self._factory(item.device_id, item.loopback)
                self._sources[item.track_id] = source
                actual = source.start(
                    self.recording.session_id,
                    item.track_id,
                    self.recording.epochs[item.track_id],
                    partial(self._submit, generation=generation),
                    partial(
                        self._on_health,
                        item.track_id,
                        generation=generation,
                        epoch=self.recording.epochs[item.track_id],
                    ),
                )
                if actual != item.format:
                    raise RecordingError("DEVICE_FORMAT_CHANGED")
                self.recording.observe_health(
                    item.track_id, self.recording.epochs[item.track_id], {"event": "ready"}
                )
                with self._lock:
                    if generation != self._run_generation or self._control_mode != "STARTING":
                        return
                    self._ready.add(item.track_id)
            with self._lock:
                if generation == self._run_generation and self._control_mode == "STARTING":
                    self._control_mode = "ACTIVE"
        except Exception as error:
            with self._lock:
                self._control_mode = "STOPPING"
            # A source can start before a later source fails. Stop acknowledgements
            # remain necessary before draining or releasing the library lock.
            try:
                self._close_sources()
                self.recording.pause()
                self._persist_backend_health()
                with self._lock:
                    self._control_mode = "PAUSED"
                    self._ack_pending = False
            except Exception:
                with self._lock:
                    self._ack_pending = True
                raise RecordingError("CAPTURE_START_FAILED_ACK_PENDING") from error
            raise RecordingError("CAPTURE_START_FAILED_MEDIA_PRESERVED") from error

    def _close_sources(self, timeout: float = 5.0) -> None:
        with self._lock:
            self._control_mode = "STOPPING"
        failed = False
        for source in self._sources.values():
            try:
                source.stop(timeout)
            except Exception:
                failed = True
        if failed:
            with self._lock:
                self._ack_pending = True
            raise RecordingError("CAPTURE_ACK_PENDING")
        self._sources.clear()
        if self.recording is not None:
            self.recording.sources_released()
        with self._lock:
            self._meters.clear()

    def _persist_backend_health(self) -> None:
        assert self.recording is not None
        try:
            snapshot = self.library.capture_health(self.recording.session_id)
            with self._lock:
                snapshot["backend_events"] = list(self._health)
                snapshot["native_formats"] = dict(self._native_formats)
            self.library.record_capture_health(self.recording.session_id, snapshot)
        except Exception:
            self.recording._defer_health()

    def pause(self, *, reason: str = "PAUSE") -> None:
        if self.recording is None:
            raise StateConflict("NO_RECORDING")
        self._close_sources()
        try:
            self.recording.pause(reason=reason)
            self._persist_backend_health()
        except Exception:
            with self._lock:
                self._ack_pending = True
            raise
        with self._lock:
            self._control_mode = "PAUSED"
            self._ack_pending = False

    def resume(self) -> None:
        if self.recording is None:
            raise StateConflict("NO_RECORDING")
        self.recording.resume()
        self._begin_run()
        self._open_sources()

    def stop(self) -> dict[str, Any]:
        if self.recording is None:
            raise StateConflict("NO_RECORDING")
        self._close_sources()
        with self._lock:
            extra = {
                "backend_events": list(self._health),
                "native_formats": dict(self._native_formats),
            }
        try:
            result = self.recording.stop(health_extra=extra)
        except Exception:
            with self._lock:
                self._ack_pending = True
            raise
        with self._lock:
            self._control_mode = "ENDED"
            self._ack_pending = False
            self._manifest_sync_pending = result.get("manifest_sync_pending") is True
        return result

    def observations(self) -> tuple[dict[str, PCMBlock], list[dict[str, Any]]]:
        with self._lock:
            return dict(self._meters), list(self._health)

    def close(self) -> None:
        self._close_sources()
        if self.recording is not None:
            state = self.library.get_session(self.recording.session_id).state
            if state in {SessionState.CREATED, SessionState.RECORDING, SessionState.PAUSED}:
                self.stop()
            self.recording.join_writer()
