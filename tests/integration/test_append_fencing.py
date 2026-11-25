"""G17 strict write/delete histories and real recording-control acknowledgements."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from itertools import product

import pytest

from recoryn.app import desktop as desktop_module
from recoryn.app.desktop import DesktopRecorder, TrackSelection
from recoryn.app.power import PowerCoordinator
from recoryn.app.recording import RecordingError, RecordingService
from recoryn.capture.queue import BoundedCaptureQueue
from recoryn.domain import StateConflict, ValidationError
from recoryn.storage import ChunkWriter, Library
from recoryn.storage import library as library_module
from recoryn.storage.chunks import has_active_writer, is_issued
from tests.unit.test_append_durability import FORMAT, IOTrace, TrackedLock, block, start_action

pytestmark = pytest.mark.integration
AUTHORITIES = ("db", "journal", "both", "tombstone", "unknown")
ROLES = ("payload", "journal", "descriptor", "recovery")
D = list(product(ROLES, AUTHORITIES, ("before", "written", "synced")))


def authority(library, kind):
    """Fault-input fixture: a real DB/journal cut, not a copy of the verdict."""
    with library._mutex:
        library._history_version += 1  # publish the injected control-side authority cut
        if kind == "unknown":
            (library.root / "deletion-journal").rename(library.root / "hidden-history")
        else:
            if kind in {"db", "both", "tombstone"}:
                library._db.execute(
                    "INSERT INTO deleted_sessions VALUES('s',1,?)",
                    ("DELETED_LOCAL" if kind == "tombstone" else "DELETE_PENDING",),
                )
                library._db.commit()
            if kind in {"journal", "both"}:
                library._publish_intent("s", 1)


@pytest.mark.parametrize("role,kind,point", D, ids=[f"G17-D-{i:03}" for i in range(1, 61)])
def test_no_media_write_starts_after_each_blocking_authority(
    tmp_path, monkeypatch, role, kind, point
):
    with Library(tmp_path) as library:
        library.create_session("s")
        trace = IOTrace(library.root, monkeypatch, library=library)
        writer = ChunkWriter(library.root, block(), "original")
        writer.append(block())
        if role == "recovery":
            writer.append(block(1))
            writer.abort()
        original_bytes = {path.name: path.read_bytes() for path in writer.staging_path.iterdir()}
        trace.events.clear()
        entered = []

        def publish():
            if not entered:
                authority(library, kind)
                trace.events.append(("D", kind))
                entered.append(1)

        original_append = ChunkWriter._append
        original_sync = ChunkWriter._sync
        original_publish = ChunkWriter._publish

        def append(self, value):
            target = role == "payload" or (
                role == "recovery" and "recovery-work" in self.staging_path.parts
            )
            if target and point == "before":
                publish()
            return original_append(self, value)

        def synced(self):
            result = original_sync(self)
            if role == "descriptor" and point == "before":
                publish()
            return result

        def publishing(self):
            trace.events.append(("publish", self.session_id))
            return original_publish(self)

        def sync_hook(phase, path, stream):
            name = (
                "descriptor.json"
                if role == "descriptor"
                else ("blocks.jsonl" if role == "journal" else "audio.pcm")
            )
            target = role != "recovery" or "recovery-work" in path.parts
            if (
                target
                and path.name == name
                and phase == ("before" if point == "written" else "after")
                and point != "before"
            ):
                publish()
            if (
                role == "journal"
                and point == "before"
                and phase == "after"
                and path.name == "audio.pcm"
            ):
                publish()

        monkeypatch.setattr(ChunkWriter, "_append", append)
        monkeypatch.setattr(ChunkWriter, "_sync", synced)
        monkeypatch.setattr(ChunkWriter, "_publish", publishing)
        trace.sync_hook = sync_hook
        try:

            def operation():
                if role == "recovery":
                    return library.recover_session("s")
                if role == "descriptor":
                    return writer.seal_chunk()
                return writer.append(block(1))

            try:
                result = operation()
            except (StateConflict, ValidationError):
                result = None
            assert entered == [1]
            after = trace.events[trace.events.index(("D", kind)) + 1 :]
            assert not [x for x in after if x[0] in {"create", "write", "publish"}], after
            assert library._db.execute("SELECT count(*) FROM chunks").fetchone()[0] == 0
            assert not writer.path.exists()
            if role == "recovery":
                assert {
                    p.name: p.read_bytes() for p in writer.staging_path.iterdir()
                } == original_bytes
                assert result is None or result.get("recovered", 0) == 0
            else:
                assert result is None
        finally:
            trace.sync_hook = None
            writer.abort()


HB = list(product(range(6), (1, 2), ("journal", "db", "tombstone")))


@pytest.mark.parametrize("cut,tracks,kind", HB, ids=[f"G17-HB-{i:03}" for i in range(1, 37)])
def test_strict_payload_sync_journal_sync_completion_chain(
    tmp_path, monkeypatch, cut, tracks, kind
):
    with Library(tmp_path) as library:
        library.create_session("s")
        trace = IOTrace(library.root, monkeypatch, library=library)
        writers = [ChunkWriter(library.root, block(track=t)) for t in ("mic", "system")[:tracks]]
        for writer in writers:
            writer.append(block(track=writer.track_id))
        trace.events.clear()
        deleted = []

        def delete():
            if not deleted:
                authority(library, kind)
                trace.events.append(("D", kind))
                deleted.append(1)

        def hook(phase, path, stream):
            point = {
                ("before", "audio.pcm"): 1,
                ("after", "audio.pcm"): 2,
                ("before", "blocks.jsonl"): 3,
                ("after", "blocks.jsonl"): 4,
            }.get((phase, path.name))
            if cut == point:
                delete()

        trace.sync_hook = hook
        accepted = []
        try:
            if cut == 0:
                delete()
            for writer in writers:
                try:
                    writer.append(block(1, track=writer.track_id))
                except StateConflict:
                    accepted.append(False)
                else:
                    accepted.append(True)
            if cut == 5:
                delete()
            assert accepted == ([True] * tracks if cut == 5 else [False] * tracks)
            assert not [
                e
                for e in trace.events[trace.events.index(("D", kind)) + 1 :]
                if e[0] in {"create", "write"}
            ]
            for ordinal, writer in enumerate(writers):
                records = [
                    json.loads(line)
                    for line in (writer.staging_path / "blocks.jsonl").read_bytes().splitlines()
                ]
                expected_records = 2 if cut == 5 or (ordinal == 0 and cut >= 3) else 1
                assert [r["metadata"]["sequence"] for r in records] == list(range(expected_records))
                raw = (writer.staging_path / "audio.pcm").read_bytes()
                expected = block(track=writer.track_id).payload
                if cut == 5 or (ordinal == 0 and cut > 0):
                    expected += block(1, track=writer.track_id).payload
                assert raw == expected
                with pytest.raises(StateConflict):
                    writer.seal()
        finally:
            trace.sync_hook = None
            for writer in writers:
                writer.abort()


L = list(
    product(
        (1, 2),
        ("pause", "stop", "partial_start", "restart", "suspend", "delete", "sealer_error"),
        ("none", "dirty", "sync", "fifo"),
    )
)


def await_condition(predicate, deadline=5):
    end = time.monotonic() + deadline
    while not predicate():
        assert time.monotonic() < end, "controlled lifecycle checkpoint missing"
        time.sleep(0.001)


@pytest.mark.parametrize("count,event,pending", L, ids=[f"G17-L-{i:03}" for i in range(1, 57)])
def test_control_events_keep_real_storage_ack_and_source_lifetimes(
    tmp_path, monkeypatch, count, event, pending
):
    with Library(tmp_path) as library:
        trace = IOTrace(library.root, monkeypatch, library=library)
        ready, release, joining, failed = (threading.Event() for _ in range(4))
        sources, expected, context = [], {}, {"armed": False, "prepared": False}
        original_get = BoundedCaptureQueue.get

        def get(queue, *args, **kwargs):
            value = original_get(queue, *args, **kwargs)
            if context["armed"] and pending == "dirty" and value.sequence > 0:
                ready.set()
                assert release.wait(10)
            return value

        monkeypatch.setattr(BoundedCaptureQueue, "get", get)

        def sync(phase, path, stream):
            service = context.get("service")
            if service is not None:
                assert not service._gate.owned
            target = "audio.pcm" if pending == "sync" else "descriptor.json"
            if (
                context["armed"]
                and pending in {"sync", "fifo"}
                and phase == "before"
                and path.name == target
            ):
                ready.set()
                assert release.wait(10)

        trace.sync_hook = sync

        def service_factory(*args, **kwargs):
            service = RecordingService(*args, **kwargs, chunk_frames=4)
            context["service"] = service
            monkeypatch.setattr(service, "_gate", TrackedLock(service._gate))
            original_join = service._join_workers

            def join(timeout):
                assert not trace.mutex.owned and not service._gate.owned
                assert not trace.registry.owned
                joining.set()
                return original_join(timeout)

            monkeypatch.setattr(service, "_join_workers", join)
            return service

        monkeypatch.setattr(desktop_module, "RecordingService", service_factory)

        def prepare():
            if context["prepared"]:
                return
            context["prepared"] = True
            context["armed"] = pending != "none"
            if pending != "none":
                for source in sources:
                    if source.running:
                        source.emit(1)
                if pending == "fifo" and count == 1:
                    sources[0].emit(2)
                assert ready.wait(5)
                if pending == "fifo":
                    await_condition(lambda: context["service"]._seals.qsize() >= 1)

        class Source:
            running = False

            def __init__(self, device, loopback):
                self.device = device
                sources.append(self)

            def start(self, session, track, epoch, submit, health):
                self.session, self.track, self.epoch, self.submit = session, track, epoch, submit
                self.running = True
                self.emit(0)
                await_condition(
                    lambda: any(
                        c.track_id == track and c.epoch_id == epoch for c in library.chunks(session)
                    )
                )
                if event == "partial_start" and len(sources) == count:
                    prepare()
                    raise RecordingError("SYNTHETIC_START_FAILED")
                return FORMAT

            def emit(self, index):
                value = block(index, track=self.track, session=self.session, epoch=self.epoch)
                assert self.submit(value)
                expected.setdefault((self.track, self.epoch), []).append(value.payload)

            def stop(self, timeout=5):
                self.running = False
                if event == "partial_start":
                    release.set()  # real startup cleanup must drain the accepted blocks

        desktop = DesktopRecorder(library, Source)
        power = PowerCoordinator(desktop)
        choices = tuple(
            TrackSelection(track, track, track == "system", FORMAT)
            for track in ("mic", "system")[:count]
        )
        actor = None
        try:
            if event == "partial_start":
                with pytest.raises(RecordingError, match="CAPTURE_START_FAILED_MEDIA_PRESERVED"):
                    desktop.start(choices)
                service = desktop.recording
                assert library.get_session(service.session_id).state.value == "PAUSED"
                assert not service.worker_alive and not any(s.running for s in sources)
            else:
                desktop.start(choices)
                service = desktop.recording
                original_epochs = service.epochs
                prepare()
                joining.clear()
                if event == "delete":
                    state = library.delete_session(service.session_id)
                    assert state["state"] == "DELETE_PENDING"
                    cut = len(trace.events)
                    desktop._close_sources()
                    release.set()
                    service.join_writer()
                    assert not [e for e in trace.events[cut:] if e[0] in {"create", "write"}]
                    generation = library.deletion_generation(service.session_id)
                    assert (
                        library.retry_deletion(service.session_id, expected_generation=generation)[
                            "state"
                        ]
                        == "DELETED_LOCAL"
                    )
                    refused = library.recover_session(service.session_id)
                    assert refused["state"] == "DELETE_PENDING"
                    assert refused["adopted"] == 0 and refused["recovered"] == 0
                    assert not (library.root / "sessions" / service.session_id).exists()
                    return
                if event == "sealer_error":
                    original_register = library.register_chunk

                    def register(value):
                        descriptor = getattr(value, "descriptor", value)
                        if descriptor.first_sequence > 0:
                            failed.set()
                            raise OSError("synthetic catalog registration failure")
                        return original_register(value)

                    monkeypatch.setattr(library, "register_chunk", register)
                    if pending == "none":
                        for source in sources:
                            source.emit(1)
                    release.set()
                    assert failed.wait(5)
                    desktop._close_sources()
                    service.join_writer()
                    assert service.health_snapshot()["storage_failed"]
                    assert not service.worker_alive and not has_active_writer(
                        library.root, service.session_id
                    )
                    for (track, epoch), payloads in expected.items():
                        saved = [
                            c
                            for c in library.chunks(service.session_id)
                            if c.track_id == track and c.epoch_id == epoch
                        ]
                        raw = b"".join(
                            (library.root / c.relative_path / "audio.pcm").read_bytes()
                            for c in saved
                        )
                        assert b"".join(payloads).startswith(raw) and len(raw) >= len(payloads[0])
                    return

                def restart():
                    desktop.pause()
                    desktop.resume()

                action = {
                    "pause": desktop.pause,
                    "stop": desktop.stop,
                    "restart": restart,
                    "suspend": power.suspend,
                }[event]
                actor = start_action(action)
                assert joining.wait(5)
                if pending != "none":
                    assert service.worker_alive and service.is_live() and not actor[1].is_set()
                    assert service.epochs == original_epochs
                    with library._mutex:
                        assert not trace.registry.owned
                    assert (
                        library._db.execute(
                            "SELECT status FROM capture_health_runs WHERE session_id=? ORDER BY rowid DESC",
                            (service.session_id,),
                        ).fetchone()[0]
                        == "OPEN"
                    )
                release.set()
                actor[0].join(10)
                assert not actor[0].is_alive() and actor[3] == []
                if event == "restart":
                    assert service.epochs != original_epochs
                    assert (
                        sources[0].submit(
                            block(
                                99,
                                track=sources[0].track,
                                session=service.session_id,
                                epoch=original_epochs[sources[0].track],
                            )
                        )
                        is False
                    )
                    desktop.stop()
                elif event == "stop":
                    assert library.get_session(service.session_id).state.value == "FINALIZED"
                else:
                    assert library.get_session(service.session_id).state.value == "PAUSED"
                    if event == "suspend":
                        assert power.resume_required
            assert not service.worker_alive
            assert not has_active_writer(library.root, service.session_id)
            for (track, epoch), payloads in expected.items():
                saved = sorted(
                    (
                        c
                        for c in library.chunks(service.session_id)
                        if c.track_id == track and c.epoch_id == epoch
                    ),
                    key=lambda c: c.first_sequence,
                )
                assert b"".join(
                    (library.root / c.relative_path / "audio.pcm").read_bytes() for c in saved
                ) == b"".join(payloads)
        finally:
            release.set()
            context["armed"] = False
            if actor is not None:
                actor[0].join(10)
                assert not actor[0].is_alive()
            desktop._close_sources()
            if desktop.recording is not None:
                desktop.recording.join_writer()


@contextmanager
def sqlite_writer_lock(library):
    connection = sqlite3.connect(library.db_path, timeout=1, isolation_level=None)
    try:
        connection.execute("BEGIN EXCLUSIVE")
        yield connection
    finally:
        connection.rollback()
        connection.close()


def registration_trace(library, prefix):
    entered, begins = threading.Event(), []

    def trace(sql):
        if sql == "BEGIN IMMEDIATE" and threading.current_thread().name.startswith(prefix):
            begins.append(time.perf_counter())
            entered.set()

    library._db.set_trace_callback(trace)
    return entered, begins


@pytest.mark.parametrize("count", (1, 2), ids=["G17-R-01", "G17-R-02"])
def test_external_sqlite_lock_does_not_own_the_capture_root(tmp_path, monkeypatch, count, request):
    """G08's native 1.5 + EXCLUSIVE 3 + 2 second probe, one/two fake tracks.

    QUEUE_DROP from the consumer's own PER_BLOCK disk latency is a measurement;
    the hard oracles are no root-held SQLite busy wait and accepted-byte conservation.
    """
    with Library(tmp_path) as library:
        trace = IOTrace(library.root, monkeypatch, library=library)
        service = RecordingService(
            library, {t: FORMAT for t in ("mic", "system")[:count]}, session_id="s"
        )
        service._gate = TrackedLock(service._gate)
        accepted = {t: [] for t in service.formats}
        rejected = {t: 0 for t in service.formats}
        stop, errors, threads = threading.Event(), [], []
        service.start()
        _, registration_begins = registration_trace(library, "recoryn-sealer")

        def source(track):
            try:
                index, next_at = 0, time.perf_counter()
                while not stop.is_set():
                    value = block(index, track=track, epoch=service.epochs[track], frames=480)
                    if service.submit(value):
                        accepted[track].append(value.payload)
                    else:
                        rejected[track] += 1
                    index += 1
                    next_at += 0.01
                    stop.wait(max(0, next_at - time.perf_counter()))
            except BaseException as error:
                errors.append(error)

        try:
            for track in service.formats:
                thread = threading.Thread(target=source, args=(track,), name=f"g17-src-{track}")
                threads.append(thread)
                thread.start()
            time.sleep(1.5)
            with sqlite_writer_lock(library):
                started = time.perf_counter()
                time.sleep(3)
            released = time.perf_counter()
            time.sleep(2)
            live = service.health_snapshot()
            assert live["accepting"] and not live["storage_failed"]
            stop.set()
            for thread in threads:
                thread.join(10)
                assert not thread.is_alive()
            assert not errors
            result = service.stop(timeout=30)
            assert result["state"] == "FINALIZED"
            descriptors = library.chunks("s")
            for track in service.formats:
                saved = b"".join(
                    (library.root / d.relative_path / "audio.pcm").read_bytes()
                    for d in descriptors
                    if d.track_id == track
                )
                assert saved == b"".join(accepted[track])
            assert result["frame_count"] == sum(map(len, accepted.values())) * 480
            observed = service.health_snapshot()
            assert (
                sum(v["dropped_frames"] for v in observed["tracks"].values())
                == sum(rejected.values()) * 480
            )
            persisted = library.capture_health("s")
            health = persisted["epochs"][-1]["tracks"]
            persisted_drops = sum(v["dropped_frames"] for v in health.values())
            # A deferred checkpoint can outlive the in-memory DEFERRED state.
            # Classify the persisted cut by its own uncertainty, not live status.
            if persisted["has_unknown"]:
                assert persisted_drops <= sum(rejected.values()) * 480
                assert persisted["detail_complete"] is False
                assert any(
                    value["media_loss_unknown"]
                    and value["known_loss_frames"] is None
                    and value["count_complete"] is False
                    for value in persisted["tracks"].values()
                ), "an old zero counter must not claim complete, known loss"
            else:
                assert persisted_drops == sum(rejected.values()) * 480
            if observed["health_status"] == "DEFERRED":
                assert persisted["has_unknown"] is True
            overlap = [
                end - begin
                for name, begin, end in trace.mutex.intervals
                if name.startswith("recoryn-sealer") and begin < released and end > started
            ]
            attempts_in_lock = sum(started <= stamp <= released for stamp in registration_begins)
            if attempts_in_lock:
                assert overlap and max(overlap) < 0.5
            # Native PER_BLOCK can be too slow to fill a default chunk before
            # this finite observation window. Do not turn no observation into proof.
            metrics = {
                "registration_observation": "OBSERVED" if attempts_in_lock else "NOT_OBSERVED",
                "registration_attempts_during_lock": attempts_in_lock,
                "tracks": count,
                "lock_seconds": released - started,
                "accepted": {k: len(v) for k, v in accepted.items()},
                "rejected": rejected,
                "sealer_root_during_lock_ms": max(overlap) * 1000 if overlap else None,
                "root_max_ms": max(s for _, s in trace.mutex.holds) * 1000,
                "writer_root_max_ms": max(
                    (s for n, s in trace.mutex.holds if n.startswith("recoryn-writer")), default=0
                )
                * 1000,
                "live_health": live["health_status"],
                "persisted_dropped_frames": persisted_drops,
                "observed_dropped_frames": sum(
                    v["dropped_frames"] for v in observed["tracks"].values()
                ),
                "persisted_has_unknown": persisted.get("has_unknown"),
                "stored_frames": result["frame_count"],
            }
            request.node.user_properties.append(
                ("g17_sqlite_metrics", json.dumps(metrics, sort_keys=True))
            )
        finally:
            stop.set()
            for thread in threads:
                thread.join(10)
            service.join_writer()
            library._db.set_trace_callback(None)


@pytest.mark.parametrize("count", (1, 2), ids=["G17-R-03", "G17-R-04"])
def test_registration_busy_keeps_live_capabilities_and_withholds_pause_ack(
    tmp_path, monkeypatch, count
):
    with Library(tmp_path) as library:
        IOTrace(library.root, monkeypatch, library=library)
        service = RecordingService(
            library, {t: FORMAT for t in ("mic", "system")[:count]}, session_id="s", chunk_frames=4
        )
        service._gate = TrackedLock(service._gate)
        service.start()
        entered, _ = registration_trace(library, "recoryn-sealer")
        try:
            with sqlite_writer_lock(library):
                for track in service.formats:
                    assert service.submit(block(track=track, epoch=service.epochs[track]))
                assert entered.wait(5)
                with pytest.raises(RecordingError, match="WRITER_ACK_PENDING"):
                    service.pause(timeout=0.01)
                assert service.worker_alive and has_active_writer(library.root, "s")
                assert library._db.execute("SELECT count(*) FROM chunks").fetchone()[0] == 0
                assert (
                    library._db.execute("SELECT status FROM capture_health_runs").fetchone()[0]
                    == "OPEN"
                )
                assert not service.storage_failed
            service.pause(timeout=30)
            assert library.get_session("s").state.value == "PAUSED"
            assert len(library.chunks("s")) == count
            assert not service.worker_alive and not has_active_writer(library.root, "s")
            assert (
                library._db.execute("SELECT status FROM capture_health_runs").fetchone()[0]
                == "CLOSED"
            )
        finally:
            service.join_writer()
            library._db.set_trace_callback(None)


def raw_capabilities(library, count):
    library.create_session("s")
    writers, caps = [], []
    for track in ("mic", "system")[:count]:
        writer = ChunkWriter(library.root, block(track=track))
        writer.append(block(track=track))
        writers.append(writer)
        caps.append(writer.seal_chunk())
    return writers, caps


def close_raw(writers, caps):
    for cap in caps:
        cap.release()
    for writer in writers:
        writer.abort()


@pytest.mark.parametrize("count", (1, 2), ids=["G17-R-05", "G17-R-06"])
def test_registration_rechecks_a_new_journal_intent_after_busy(tmp_path, monkeypatch, count):
    with Library(tmp_path) as library:
        trace = IOTrace(library.root, monkeypatch, library=library)
        writers, caps = raw_capabilities(library, count)
        entered, _ = registration_trace(library, "g17-register")
        actor = None
        try:
            with sqlite_writer_lock(library):

                def register():
                    errors = []
                    for cap in caps:
                        try:
                            library.register_chunk(cap)
                        except StateConflict as error:
                            errors.append(str(error))
                    return errors

                actor = start_action(register, "g17-register")
                assert entered.wait(5)
                with trace.mutex:
                    library._publish_intent("s", 1)  # durable journal-only authority, DB busy
                actor[0].join(1)
                assert not actor[0].is_alive() and actor[3] == []
                assert actor[2] == [["Session has a deletion intent"] * count]
                assert library._db.execute("SELECT count(*) FROM chunks").fetchone()[0] == 0
                assert all(is_issued(cap) for cap in caps)
            assert library._db.execute("SELECT count(*) FROM chunks").fetchone()[0] == 0
            close_raw(writers, caps)
            assert library.delete_session("s")["deleted"]
            assert library.recover_session("s")["state"] == "DELETE_PENDING"
            assert not (library.root / "sessions/s").exists()
        finally:
            if actor is not None:
                actor[0].join(10)
            close_raw(writers, caps)
            library._db.set_trace_callback(None)


def test_released_capability_is_not_reused_on_registration_retry(tmp_path, monkeypatch):
    """G17-R-07: a fast-path fact captured before waiting is not lifetime authority."""
    with Library(tmp_path) as library:
        IOTrace(library.root, monkeypatch, library=library)
        writers, caps = raw_capabilities(library, 1)
        entered, _ = registration_trace(library, "g17-register")
        actor = None
        try:
            with sqlite_writer_lock(library):
                actor = start_action(lambda: library.register_chunk(caps[0]), "g17-register")
                assert entered.wait(5)
                caps[0].release()
                actor[0].join(1)
                assert not actor[0].is_alive()
                assert len(actor[3]) == 1 and isinstance(actor[3][0], StateConflict)
                assert str(actor[3][0]) == "Sealed chunk released before registration"
                assert library._db.execute("SELECT count(*) FROM chunks").fetchone()[0] == 0
        finally:
            if actor is not None:
                actor[0].join(10)
            close_raw(writers, caps)
            library._db.set_trace_callback(None)


def test_registration_honors_its_original_busy_deadline(tmp_path, monkeypatch):
    """G17-R-08: a parent assertion judges bounded completion; cleanup releases the lock."""
    with Library(tmp_path) as library:
        trace = IOTrace(library.root, monkeypatch, library=library)
        writers, caps = raw_capabilities(library, 1)
        library._db.execute("PRAGMA busy_timeout=60")
        entered, attempts = registration_trace(library, "g17-register")
        actor = None
        try:
            with sqlite_writer_lock(library):
                actor = start_action(lambda: library.register_chunk(caps[0]), "g17-register")
                assert entered.wait(5)
                actor[0].join(1)
                assert not actor[0].is_alive(), "registration exceeded its 60ms busy budget"
                assert len(actor[3]) == 1 and isinstance(actor[3][0], sqlite3.OperationalError)
                assert actor[3][0].sqlite_errorcode & 0xFF == sqlite3.SQLITE_BUSY
                assert len(attempts) >= 2
                assert is_issued(caps[0]) and has_active_writer(library.root, "s")
                assert library._db.execute("PRAGMA busy_timeout").fetchone()[0] == 60
                assert library._db.execute("SELECT count(*) FROM chunks").fetchone()[0] == 0
                assert max(s for n, s in trace.mutex.holds if n == "g17-register") < 0.5
        finally:
            if actor is not None:
                actor[0].join(10)
            close_raw(writers, caps)
            library._db.set_trace_callback(None)
            library._db.execute("PRAGMA busy_timeout=5000")


def test_registration_does_not_retry_readonly_failures(tmp_path, monkeypatch):
    """G17-R-09: SQLITE_READONLY is not transient merely because it is OperationalError."""
    with Library(tmp_path) as library:
        IOTrace(library.root, monkeypatch, library=library)
        writers, caps = raw_capabilities(library, 1)
        library._db.execute("PRAGMA query_only=ON")
        actor = start_action(lambda: library.register_chunk(caps[0]), "g17-register")
        try:
            actor[0].join(1)
            assert not actor[0].is_alive(), "non-busy SQLite error was retried"
            assert len(actor[3]) == 1 and isinstance(actor[3][0], sqlite3.OperationalError)
            assert actor[3][0].sqlite_errorcode == sqlite3.SQLITE_READONLY
            assert library._db.execute("SELECT count(*) FROM chunks").fetchone()[0] == 0
            assert library._db.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
            assert is_issued(caps[0])
        finally:
            library._db.execute("PRAGMA query_only=OFF")
            actor[0].join(10)
            close_raw(writers, caps)


@pytest.mark.parametrize(
    "code",
    (sqlite3.SQLITE_LOCKED, sqlite3.SQLITE_BUSY_RECOVERY, sqlite3.SQLITE_BUSY_SNAPSHOT),
    ids=["G17-R-10", "G17-R-11", "G17-R-12"],
)
def test_busy_error_families_retry_without_any_shared_lock(tmp_path, monkeypatch, code):
    with Library(tmp_path) as library:
        trace = IOTrace(library.root, monkeypatch, library=library)
        writers, caps = raw_capabilities(library, 1)
        transaction, calls, sleeps = library._transaction, [], []
        timeouts = []
        sleep = time.sleep

        @contextmanager
        def temporary():
            timeouts.append(library._db.execute("PRAGMA busy_timeout").fetchone()[0])
            calls.append(1)
            if len(calls) == 1:
                error = sqlite3.OperationalError("injected transient registration fault")
                error.sqlite_errorcode = code
                raise error
            with transaction() as connection:
                yield connection

        def pause(seconds):
            assert (
                not trace.mutex.owned and not trace.registry.owned and not trace.coordination.owned
            )
            sleeps.append(seconds)
            sleep(seconds)

        monkeypatch.setattr(library, "_transaction", temporary)
        monkeypatch.setattr(library_module, "_registration_wait", pause)
        try:
            library.register_chunk(caps[0])
            assert len(calls) == 2 and len(sleeps) == 1 and 0 < sleeps[0] <= 0.01
            assert timeouts == [0, 0]
            assert library._db.execute("SELECT count(*) FROM chunks").fetchone()[0] == 1
            assert library._db.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
            assert is_issued(caps[0])
        finally:
            close_raw(writers, caps)


@pytest.mark.parametrize("count", (1, 2), ids=["G17-R-13", "G17-R-14"])
def test_sqlite_busy_preserves_fifo_registration_and_final_ack(tmp_path, monkeypatch, count):
    with Library(tmp_path) as library:
        IOTrace(library.root, monkeypatch, library=library)
        service = RecordingService(
            library, {t: FORMAT for t in ("mic", "system")[:count]}, session_id="s", chunk_frames=4
        )
        service.start()
        entered, _ = registration_trace(library, "recoryn-sealer")
        original, completed, expected = library.register_chunk, [], []

        def registered(candidate):
            original(candidate)
            assert is_issued(candidate)  # caller has not received registration ACK yet
            d = candidate.descriptor
            completed.append((d.track_id, d.first_sequence))

        monkeypatch.setattr(library, "register_chunk", registered)
        try:
            with sqlite_writer_lock(library):
                for index in range(3):
                    for track in service.formats:
                        assert service.submit(
                            block(index, track=track, epoch=service.epochs[track])
                        )
                        expected.append((track, index))
                assert entered.wait(5)
                with pytest.raises(RecordingError, match="WRITER_ACK_PENDING"):
                    service.stop(timeout=0.01)
                assert completed == [] and has_active_writer(library.root, "s")
            result = service.stop(timeout=30)
            assert result["state"] == "FINALIZED" and result["frame_count"] == 3 * count * 4
            assert completed == expected
            descriptors = library.chunks("s")
            assert len(descriptors) == 3 * count
            # An explicit idempotent repeat does not duplicate or reorder catalog rows.
            original(descriptors[0])
            assert library.chunks("s") == descriptors
            assert not has_active_writer(library.root, "s") and not service.worker_alive
            for track in service.formats:
                assert b"".join(
                    (library.root / d.relative_path / "audio.pcm").read_bytes()
                    for d in descriptors
                    if d.track_id == track
                ) == b"".join(block(i, track=track).payload for i in range(3))
        finally:
            service.join_writer()
            library._db.set_trace_callback(None)


@pytest.mark.parametrize(
    "stage,name",
    (
        ("readback", "blocks.jsonl"),
        ("readback", "audio.pcm"),
        ("readback", "descriptor.json"),
        ("identity", "descriptor.json"),
        ("identity", "audio.pcm"),
    ),
    ids=[
        "G17-F1-IO-journal",
        "G17-F1-IO-payload",
        "G17-F1-IO-descriptor",
        "G17-F1-IO-identity",
        "G17-F1-IO-size",
    ],
)
def test_transient_sealed_reads_keep_recording_and_every_accepted_byte(
    tmp_path, monkeypatch, stage, name
):
    from recoryn.storage import _coordination as coordination
    from recoryn.storage import _safe, chunks

    with Library(tmp_path) as library:
        trace = IOTrace(library.root, monkeypatch, library=library)
        target = (
            library_module
            if stage == "identity"
            else (_safe if name == "descriptor.json" else chunks)
        )
        original, calls, waits = target.open_file, [], []
        wait = coordination._read_wait

        def sharing_once(path, mode):
            if (
                mode == "rb"
                and path.name == name
                and threading.current_thread().name.startswith("recoryn-sealer")
                and not calls
            ):
                calls.append(str(path))
                raise PermissionError("first just-written open denied")
            return original(path, mode)

        def pause(seconds):
            assert (
                not trace.mutex.owned and not trace.registry.owned and not trace.coordination.owned
            )
            waits.append(seconds)
            wait(seconds)

        monkeypatch.setattr(target, "open_file", sharing_once)
        monkeypatch.setattr(coordination, "_read_wait", pause)
        service = RecordingService(library, {"mic": FORMAT}, session_id="s", chunk_frames=12)
        service.start()
        submitted = [block(i, epoch=service.epochs["mic"]) for i in range(12)]
        try:
            for value in submitted[:6]:
                assert service.submit(value)
            await_condition(lambda: bool(calls) or service.storage_failed)
            await_condition(lambda: bool(library.chunks("s")) or service.storage_failed)
            live = service.health_snapshot()
            assert live["accepting"] and not live["storage_failed"]
            assert service._writer_error is None
            for value in submitted[6:]:
                assert service.submit(value)
            result = service.stop(timeout=30)
            assert len(calls) == 1 and waits
            assert result["state"] == "FINALIZED" and result["frame_count"] == 48
            assert service._writer_error is None and not service.health_snapshot()["storage_failed"]
            descriptors = library.chunks("s")
            assert sum(d.frame_count for d in descriptors) == 48
            assert b"".join(
                (library.root / d.relative_path / "audio.pcm").read_bytes() for d in descriptors
            ) == b"".join(value.payload for value in submitted)
            assert not service.worker_alive and not has_active_writer(library.root, "s")
        finally:
            service.join_writer()


@pytest.mark.parametrize(
    "stage", ("readback", "identity"), ids=["G17-F1-EXPIRE-readback", "G17-F1-EXPIRE-identity"]
)
def test_persistent_read_denial_keeps_exact_unregistered_prefix_for_recovery(
    tmp_path, monkeypatch, stage
):
    from recoryn.storage import _coordination as coordination
    from recoryn.storage import chunks

    with Library(tmp_path) as library:
        library.create_session("s")
        trace = IOTrace(library.root, monkeypatch, library=library)
        writer = ChunkWriter(library.root, block(), "preserved")
        writer.append(block())
        target = chunks if stage == "readback" else library_module
        original, clock, calls = target.open_file, [0.0], []
        expected = "blocks.jsonl" if stage == "readback" else "descriptor.json"
        error = PermissionError("persistent sharing denial")

        def deny(path, mode):
            if path.name == expected and mode == "rb":
                calls.append(1)
                raise error
            return original(path, mode)

        def wait(seconds):
            assert (
                not trace.mutex.owned and not trace.registry.owned and not trace.coordination.owned
            )
            clock[0] += 0.5

        monkeypatch.setattr(coordination, "_read_clock", lambda: clock[0])
        monkeypatch.setattr(coordination, "_read_wait", wait)
        cap = None
        try:
            if stage == "identity":
                cap = writer.seal_chunk()
            monkeypatch.setattr(target, "open_file", deny)
            with pytest.raises(PermissionError) as caught:
                library.register_chunk(cap) if cap is not None else writer.seal_chunk()
            assert caught.value is error and len(calls) == 3
            assert library._db.execute("SELECT count(*) FROM chunks").fetchone()[0] == 0
            path = writer.path if stage == "identity" else writer.staging_path
            assert (path / "audio.pcm").read_bytes() == block().payload
            assert len((path / "blocks.jsonl").read_bytes().splitlines()) == 1
        finally:
            monkeypatch.setattr(target, "open_file", original)
            if cap is not None:
                cap.release()
            writer.abort()
        recovered = library.recover_session("s")
        assert (recovered["recovered"], recovered["adopted"]) == (
            (1, 0) if stage == "readback" else (0, 1)
        )
        descriptors = library.chunks("s")
        assert sum(d.frame_count for d in descriptors) == 4
        assert (
            b"".join(
                (library.root / d.relative_path / "audio.pcm").read_bytes() for d in descriptors
            )
            == block().payload
        )
