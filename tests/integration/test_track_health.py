"""G08 actual SQLite, fake sources, barriers and accepted-PCM accounting."""

import copy
import json
import sqlite3
import threading
from itertools import product
from pathlib import Path
from types import SimpleNamespace

import pytest

from recoryn.app.recording import RecordingService
from recoryn.domain import AudioFormat, PCMBlock, SessionState, StateConflict
from recoryn.domain.capture_health import CaptureReceipt
from recoryn.storage import ChunkWriter, Library
from tests.unit.test_track_health import seed, snapshot

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "drops,checkpoint_every,epochs",
    [(132, 8, 1), (40, 0, 2), (16, 0, 1), (17, 8, 1)],
    ids=[f"G08-FIX3-I{n:02}" for n in range(1, 5)],
)
def test_gap_projection_marks_omission_without_losing_canonical_facts(
    tmp_path, monkeypatch, drops, checkpoint_every, epochs
):
    """Nonadjacent real queue rejects: PCM and canonical facts are hand-counted."""
    with Library(tmp_path) as library:
        service = RecordingService(
            library, {t: AudioFormat(48000, 1) for t in ("mic", "system")}, max_blocks=2048
        )
        expected = {t: b"" for t in service.formats}
        runs = []
        try:
            service.start()
            for epoch in range(epochs):
                runs.append(service._capture_run_id)
                pending = service._queue
                offer = pending.offer

                def patterned(block, pending=pending, offer=offer):
                    if block.sequence % 2 == 0:
                        return offer(block)
                    # Exercise queue accounting as well as RecordingService's False path.
                    # submit serializes this temporary capacity change with health snapshots.
                    limit = pending._max_bytes
                    pending._max_bytes = 0
                    try:
                        return offer(block)
                    finally:
                        pending._max_bytes = limit

                with monkeypatch.context() as patch:
                    patch.setattr(pending, "offer", patterned)
                    for sequence in range(drops * 2):
                        for index, track in enumerate(service.formats):
                            data = bytes([(sequence + epoch) % 256, index + 7]) * 480
                            block = PCMBlock(
                                service.session_id,
                                track,
                                service.epochs[track],
                                sequence,
                                service.formats[track],
                                480,
                                data,
                                sequence * 10_000_000,
                                sequence * 10_000_000,
                                sequence * 480,
                            )
                            assert service.submit(block) is (sequence % 2 == 0)
                            if sequence % 2 == 0:
                                expected[track] += data
                        if checkpoint_every and (sequence + 1) % checkpoint_every == 0:
                            service._checkpoint_health(force=True)
                queue = pending.snapshot()
                assert queue["dropped_frames"] == drops * 480 * 2
                assert queue["accepted_frames"] == drops * 480 * 2
                if epoch + 1 < epochs:
                    service.pause(timeout=60)
                    service.resume()
            result = service.stop(timeout=60)
            assert result["state"] == "FINALIZED"
            projection = library.capture_health(service.session_id)
            by_run = {e["capture_run_id"]: e for e in projection["epochs"]}
            canonical = [
                json.loads(row[0])
                for row in library._db.execute("SELECT payload FROM capture_health_events")
            ]
            track_rows = [
                json.loads(row[0])
                for row in library._db.execute("SELECT payload FROM capture_health_tracks")
            ]
            for run in runs:
                for track in service.formats:
                    value = by_run[run]["tracks"][track]
                    assert value["accepted_frames"] == value["dropped_frames"] == drops * 480
                    assert value["known_loss_frames"] == value["known_lower_bound"] == drops * 480
                    assert len(value["gaps"]) == min(drops, 16)
                    assert bool(value.get("gap_detail_truncated")) is (drops > 16)
                    assert sum(g["frame_count"] for g in value["gaps"]) == min(drops, 16) * 480
                    events = [
                        e
                        for e in canonical
                        if e["capture_run_id"] == run
                        and e["track_id"] == track
                        and e["reason"] == "QUEUE_DROP"
                    ]
                    assert len(events) == drops
                    assert sum(e["lost_frames"] for e in events) == drops * 480
                    raw = next(
                        v
                        for v in track_rows
                        if v["capture_run_id"] == run and v["track_id"] == track
                    )
                    assert raw["dropped_frames"] == drops * 480
                    assert sum(g["frame_count"] for g in raw["gaps"]) == drops * 480
            for track, data in expected.items():
                value = projection["tracks"][track]
                assert bool(value.get("gap_detail_truncated")) is (drops > 16)
                assert value["dropped_frames"] == drops * 480
                assert value["known_loss_frames"] == value["known_lower_bound"] == drops * 480
                stored = b"".join(
                    (library.root / chunk.relative_path / "audio.pcm").read_bytes()
                    for chunk in library.chunks(service.session_id)
                    if chunk.track_id == track
                )
                assert stored == data
            print(
                json.dumps(
                    {
                        "drops_per_track": drops,
                        "epochs": epochs,
                        "dropped_frames_per_track_per_epoch": drops * 480,
                        "retained_gap_frames": min(drops, 16) * 480,
                    }
                )
            )
        finally:
            service.join_writer()


R = list(
    product(
        ("OPEN", "UNCLEAN", "CLOSED", "LEGACY", "MISSING", "FUTURE", "CORRUPT"),
        ("none", "db", "journal", "tombstone"),
        (False, True),
        (False, True),
        (1, 2),
    )
)
ORDERS = list(product(range(6), (False, True), (1, 2)))
Q = list(product(("accept", "queue", "gate"), ("fixed", "variable", "silent"), (1, 2)))
P = list(product(("pending", "ok", "failed"), (False, True), (1, 2)))
F = list(
    product(("OPEN", "CLOSED", "FAIL", "CORRUPT", "FUTURE"), ("recover", "finalize"), (False, True))
)


FIX2_RUNS = list(product(("store", "transaction"), (1, 2), (1, 2), (False, True)))


@pytest.mark.parametrize(
    "fault,tracks,following,blocked",
    FIX2_RUNS,
    ids=[f"G08-FIX2-{n:02}" for n in range(1, 17)],
)
def test_session_debt_survives_marker_failure_and_new_runs(
    tmp_path, monkeypatch, fault, tracks, following, blocked
):
    from contextlib import contextmanager

    with Library(tmp_path) as library:
        service = RecordingService(
            library, {t: AudioFormat(48000, 1) for t in ("mic", "system")[:tracks]}
        )
        expected = {t: b"" for t in service.formats}

        def send(sequence):
            for i, track in enumerate(service.formats):
                block = PCMBlock(
                    service.session_id,
                    track,
                    service.epochs[track],
                    sequence,
                    AudioFormat(48000, 1),
                    3,
                    bytes([sequence + 1, i + 7]) * 3,
                    sequence * 62500,
                    sequence * 62500,
                    sequence * 3,
                )
                assert service.submit(block)
                expected[track] += block.payload

        try:
            service.start()
            send(0)
            service._checkpoint_health(force=True)
            with monkeypatch.context() as patch:
                if fault == "store":

                    def fail_store(*a, **k):
                        raise sqlite3.OperationalError("health store only")

                    patch.setattr(library, "_store_health", fail_store)
                    patch.setattr(library, "defer_capture_health", fail_store)
                else:
                    transaction = library._transaction

                    @contextmanager
                    def fail_transaction():
                        if threading.current_thread().name.startswith("recoryn-writer"):
                            raise sqlite3.OperationalError("health consumer commit only")
                        with transaction() as connection:
                            yield connection

                    patch.setattr(library, "_transaction", fail_transaction)
                observer = threading.Thread(
                    target=lambda: service._checkpoint_health(force=True),
                    name="recoryn-writer-health-fault",
                )
                observer.start()
                observer.join(5)
                assert not observer.is_alive()
                assert service.health_snapshot()["health_status"] == "DEFERRED"
                assert library.capture_health(service.session_id)["has_unknown"] is True
                send(1)
            service.pause(timeout=30)
            for _ in range(following):
                service.resume()
                assert service.health_snapshot()["health_status"] == "DEFERRED"
                assert library.capture_health(service.session_id)["has_unknown"] is True
                persisted = json.loads(
                    library._db.execute(
                        "SELECT capture_health FROM sessions WHERE session_id=?",
                        (service.session_id,),
                    ).fetchone()[0]
                )
                assert persisted["has_unknown"] is True and persisted["health_status"] == "DEFERRED"
                send(0)
                if _ < following - 1:
                    service.pause(timeout=30)
            if blocked:
                with monkeypatch.context() as patch:

                    def unavailable(*a, **k):
                        raise sqlite3.OperationalError("tail store still unavailable")

                    patch.setattr(library, "_store_health", unavailable)
                    result = service.stop(timeout=30)
                    assert result["finalized"] is False
                    assert result["state"] == "PAUSED"
                    assert library.capture_health(service.session_id)["has_unknown"] is True
                    assert not service.worker_alive and not service.storage_failed
                result = library.finalize_unfinished(service.session_id)
            else:
                result = service.stop(timeout=30)
            assert result["state"] == "FINALIZED"
            health = library.capture_health(service.session_id)
            assert health["has_unknown"] is True and health.get("health_status") != "DEFERRED"
            runs = library._db.execute(
                "SELECT status FROM capture_health_runs WHERE session_id=?", (service.session_id,)
            ).fetchall()
            assert runs and all(r[0] in {"CLOSED", "RECOVERED_UNCLEAN"} for r in runs)
            assert any(r[0] == "RECOVERED_UNCLEAN" for r in runs)
            for track, data in expected.items():
                stored = b"".join(
                    (library.root / c.relative_path / "audio.pcm").read_bytes()
                    for c in library.chunks(service.session_id)
                    if c.track_id == track
                )
                assert stored == data
            tails = [
                json.loads(r[0])
                for r in library._db.execute(
                    "SELECT payload FROM capture_health_events WHERE session_id=? AND kind='UNKNOWN_TAIL'",
                    (service.session_id,),
                )
            ]
            assert {e["track_id"] for e in tails} == set(expected)
            assert all(e["lost_frames"] is None for e in tails)
        finally:
            service.join_writer()


@pytest.mark.parametrize("case", range(17, 21), ids=[f"G08-FIX2-{n:02}" for n in range(17, 21)])
def test_marker_retry_is_bounded_and_survives_until_a_later_opportunity(
    tmp_path, monkeypatch, case
):
    import time

    with Library(tmp_path) as library:
        service = RecordingService(library, {"mic": AudioFormat(48000, 1)})
        try:
            service.start()
            service.pause(timeout=30)
            original = library.defer_capture_health
            calls = []
            with monkeypatch.context() as patch:
                if case == 19:
                    other = sqlite3.connect(library.db_path)
                    other.execute("BEGIN IMMEDIATE")
                if case == 20:
                    assert library.delete_session(service.session_id)["deleted"]

                def marker(*args):
                    calls.append(1)
                    if case in {17, 18} and (case == 18 or len(calls) == 1):
                        raise sqlite3.OperationalError("temporary marker failure")
                    return original(*args)

                patch.setattr(library, "defer_capture_health", marker)
                if case == 18:
                    times = iter((0.0, 0.0, 1.0))
                    patch.setattr(time, "monotonic", lambda: next(times))
                elif case in {19, 20}:
                    patch.setattr(time, "monotonic", lambda: 0.0)
                try:
                    service._defer_health()
                finally:
                    if case == 19:
                        other.rollback()
                        other.close()
                assert len(calls) == (1 if case == 18 else 2)
                if case != 17:
                    assert service._defer_marker_pending
                if case == 19:
                    assert library._db.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
            if case == 20:
                with pytest.raises(ValueError):
                    library.capture_health(service.session_id)
                assert not library._db.execute(
                    "SELECT 1 FROM sessions WHERE session_id=?", (service.session_id,)
                ).fetchone()
            else:
                service._checkpoint_health(force=True)
                assert service._defer_marker_pending is False
                raw = json.loads(
                    library._db.execute(
                        "SELECT capture_health FROM sessions WHERE session_id=?",
                        (service.session_id,),
                    ).fetchone()[0]
                )
                assert raw["health_status"] == "DEFERRED" and raw["has_unknown"] is True
                assert service.stop(timeout=30)["state"] == "FINALIZED"
        finally:
            service.join_writer()


@pytest.mark.parametrize("opened", (True, False), ids=["G08-FIX2-21", "G08-FIX2-22"])
def test_stop_authority_checks_open_runs_even_if_projection_looks_healthy(
    tmp_path, monkeypatch, opened
):
    with Library(tmp_path) as library:
        value, version = seed(library)
        if not opened:
            value["checkpoint_seq"] = 1
            library.finish_capture_health(
                "s",
                value,
                expected_health_version=version,
                receipt=CaptureReceipt("run", True, True, True, False),
            )
        monkeypatch.setattr(
            library, "capture_health", lambda *a, **k: {"health_status": "OBSERVED"}
        )
        assert library.capture_health_pending("s") is opened


@pytest.mark.parametrize(
    "marker,old_id,new_id",
    [(m, a, b) for m in (False, True) for a, b in (("a", "z"), ("z", "a"))],
    ids=[f"G08-FIX2-{n:02}" for n in range(23, 27)],
)
def test_final_unknown_tail_display_depends_on_final_facts_not_marker_or_run_order(
    tmp_path, marker, old_id, new_id
):
    with Library(tmp_path) as library:
        seed(library, capture_run_id=old_id)
        if marker:
            library.defer_capture_health("s", old_id)
        else:
            library.note_capture_health_deferred("s")
        library.transition("s", SessionState.PAUSED, library.get_session("s").state_version)
        value = snapshot(
            capture_run_id=new_id,
            tracks={
                "mic": {
                    "epoch_id": "second",
                    "state": "OK",
                    "reason": "NONE",
                    "accepted_frames": 0,
                    "dropped_frames": 0,
                    "detail_complete": True,
                }
            },
        )
        version = library.begin_capture_health(
            "s", value, expected_state_version=library.get_session("s").state_version
        )
        value["checkpoint_seq"] = 1
        library.finish_capture_health(
            "s",
            value,
            expected_health_version=version,
            receipt=CaptureReceipt(new_id, True, True, True, False),
        )
        library.transition("s", SessionState.PAUSED, library.get_session("s").state_version)
        result = library.recover_session("s")
        assert result["health_recovery"]["status"] == "RECOVERED_UNCLEAN"
        summary = library.capture_health("s")
        assert summary["has_unknown"] is True
        assert summary.get("health_status") != "DEFERRED" and "health_error" not in summary
        events = [
            json.loads(r[0])
            for r in library._db.execute(
                "SELECT payload FROM capture_health_events WHERE kind='UNKNOWN_TAIL'"
            )
        ]
        assert len(events) == 1 and events[0]["capture_run_id"] == old_id
        assert events[0]["lost_frames"] is None
        assert library.recover_session("s")["health_recovery"]["has_unknown"] is True


@pytest.mark.parametrize("change", ("metadata", "open"), ids=["G08-FIX2-27", "G08-FIX2-28"])
def test_resolving_deferred_health_rechecks_authority_and_keeps_new_facts(
    tmp_path, monkeypatch, change
):
    from contextlib import contextmanager

    with Library(tmp_path) as library:
        value, version = seed(library)
        value["checkpoint_seq"] = 1
        library.finish_capture_health(
            "s",
            value,
            expected_health_version=version,
            receipt=CaptureReceipt("run", True, True, True, False),
        )
        library.transition("s", SessionState.PAUSED, library.get_session("s").state_version)
        library.note_capture_health_deferred("s")
        library.defer_capture_health("s", "run")
        original = library._health_authority
        calls = []

        @contextmanager
        def race(*args, **kwargs):
            with original(*args, **kwargs) as authority:
                calls.append(1)
                if len(calls) != 2:
                    yield authority
                    return
                if change == "open":
                    library._db.execute("UPDATE capture_health_runs SET status='OPEN'")
                else:
                    row = json.loads(
                        library._db.execute(
                            "SELECT capture_health FROM sessions WHERE session_id='s'"
                        ).fetchone()[0]
                    )
                    row["backend_marker"] = "new"
                    library.record_capture_health("s", row)
                library._db.commit()
                yield authority

        with monkeypatch.context() as patch:
            patch.setattr(library, "_health_authority", race)
            with pytest.raises(StateConflict):
                library._resolve_capture_health_deferred("s")
        assert len(calls) == 2
        assert library.capture_health("s")["has_unknown"] is True
        assert library.capture_health("s")["health_status"] == "DEFERRED"
        assert library.recover_session("s")["health_recovery"]["status"] != "DEFERRED"
        assert library.capture_health("s").get("health_status") != "DEFERRED"
        if change == "metadata":
            assert library.capture_health("s")["backend_marker"] == "new"


@pytest.mark.parametrize("case", [pytest.param(1, id="G08-FIX2-X-PROJECTION")])
def test_new_run_persists_unknown_while_every_marker_write_still_fails(tmp_path, monkeypatch, case):
    with Library(tmp_path) as library:
        service = RecordingService(library, {"mic": AudioFormat(48000, 1)})
        try:
            service.start()
            assert service.submit(pcm(service, 0))

            def unavailable(*args, **kwargs):
                raise sqlite3.OperationalError("only the marker remains unavailable")

            with monkeypatch.context() as marker_patch:
                marker_patch.setattr(library, "defer_capture_health", unavailable)
                with monkeypatch.context() as checkpoint_patch:
                    checkpoint_patch.setattr(library, "checkpoint_capture_health", unavailable)
                    service._checkpoint_health(force=True)
                service.pause(timeout=30)
                service.resume()
                assert service.submit(pcm(service, 0))
                raw = json.loads(
                    library._db.execute(
                        "SELECT capture_health FROM sessions WHERE session_id=?",
                        (service.session_id,),
                    ).fetchone()[0]
                )
                assert raw["health_status"] == "DEFERRED" and raw["has_unknown"] is True
                assert service.health_snapshot()["accepting"] and not service.storage_failed
                assert service.stop(timeout=30)["state"] == "FINALIZED"
            assert library.capture_health(service.session_id).get("health_status") != "DEFERRED"
        finally:
            service.join_writer()


@pytest.mark.parametrize("case", [pytest.param(1, id="G08-FIX2-X-DRAIN")])
def test_drain_persists_a_source_failure_even_without_a_consumer_checkpoint(
    tmp_path, monkeypatch, case
):
    with Library(tmp_path) as library:
        service = RecordingService(library, {"mic": AudioFormat(48000, 1)})
        try:
            service.start()

            def unavailable(*args):
                raise OSError("source bookkeeping only")

            with monkeypatch.context() as patch:
                patch.setattr(service, "_track_event", unavailable)
                patch.setattr(service, "_checkpoint_health", lambda *, force=False: None)
                assert service.observe_health("mic", service.epochs["mic"], {"event": "ready"})
                service.pause(timeout=30)
            raw = json.loads(
                library._db.execute(
                    "SELECT capture_health FROM sessions WHERE session_id=?", (service.session_id,)
                ).fetchone()[0]
            )
            assert raw["health_status"] == "DEFERRED" and raw["has_unknown"] is True
            assert service.stop(timeout=30)["state"] == "FINALIZED"
        finally:
            service.join_writer()


@pytest.mark.parametrize("case", [pytest.param(1, id="G08-FIX2-X-RETRY-RATE")])
def test_consumer_retry_has_a_checkpoint_cadence_but_explicit_controls_can_flush(
    tmp_path, monkeypatch, case
):
    import time

    with Library(tmp_path) as library:
        service = RecordingService(library, {"mic": AudioFormat(48000, 1)})
        try:
            service.start()
            service.pause(timeout=30)
            calls, now = [], [10.0]

            def unavailable(*args):
                calls.append(now[0])
                raise sqlite3.OperationalError("marker remains unavailable")

            with monkeypatch.context() as patch:
                patch.setattr(time, "monotonic", lambda: now[0])
                patch.setattr(library, "defer_capture_health", unavailable)
                service._defer_health()
                assert len(calls) == 2
                for _ in range(100):
                    service._checkpoint_health()
                assert len(calls) == 2
                now[0] = 10.999
                service._checkpoint_health()
                assert len(calls) == 2
                now[0] = 11.0
                service._checkpoint_health()
                assert len(calls) == 4
                service._checkpoint_health(force=True)
                assert len(calls) == 6
                assert library.capture_health(service.session_id)["has_unknown"] is True
            assert service.stop(timeout=30)["state"] == "FINALIZED"
        finally:
            service.join_writer()


@pytest.mark.parametrize("case", range(1, 7), ids=[f"G08-FIX1-{n:02}" for n in range(1, 7)])
def test_health_failure_does_not_fail_pcm(case, tmp_path, monkeypatch):
    from recoryn.app.desktop import DesktopRecorder

    with Library(tmp_path) as library:
        service = RecordingService(library, {t: AudioFormat(48000, 1) for t in ("mic", "system")})
        names = {
            1: "begin_capture_health",
            2: "checkpoint_capture_health",
            3: "finish_capture_health",
            4: "capture_health",
            5: "record_capture_health",
            6: "checkpoint_capture_health",
        }
        method = names[case]
        original = getattr(library, method)
        calls = []

        def fail(*args, **kwargs):
            calls.append(1)
            if case == 6:
                raise StateConflict("HEALTH_SNAPSHOT_CHANGED")
            raise OSError("health-only injection")

        try:
            if case == 1:
                monkeypatch.setattr(library, method, fail)
            service.start()
            monkeypatch.setattr(library, method, fail)
            if case == 2:
                import time

                service._last_checkpoint = 0
                deadline = time.monotonic() + 5
                while (
                    not service._health_deferred
                    and not service.storage_failed
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.001)
                assert service._health_deferred and not service.storage_failed
            elif case == 6:
                service._checkpoint_health(force=True)
            elif case in {4, 5}:
                desktop = object.__new__(DesktopRecorder)
                desktop.recording, desktop.library = service, library
                desktop._lock = threading.Lock()
                desktop._health, desktop._native_formats = [], {}
                desktop._persist_backend_health()
            for track in service.formats:
                assert service.submit(pcm(service, 0, track))
            service.pause(timeout=30)
            assert calls and service._writer_error is None
            assert not service.health_snapshot()["storage_failed"]
            assert library.get_session(service.session_id).state == SessionState.PAUSED
            assert service.health_snapshot()["health_status"] == (
                "OBSERVED" if case == 6 else "DEFERRED"
            )
            if case != 6:
                assert all(
                    v["known_loss_frames"] is None
                    for v in service.health_snapshot()["track_health"].values()
                )
            monkeypatch.setattr(library, method, original)
            if case == 3:
                service.resume()
                for track in service.formats:
                    assert service.submit(pcm(service, 0, track))
                service.pause(timeout=30)
            service.stop(timeout=30)
            assert sum(c.frame_count for c in library.chunks(service.session_id)) == (
                12 if case == 3 else 6
            )
        finally:
            monkeypatch.setattr(library, method, original)
            service.join_writer()


@pytest.mark.parametrize(
    "path", ("submit", "observe"), ids=["G08-FIX1-X-SUBMIT", "G08-FIX1-X-OBSERVE"]
)
def test_health_callback_failure_keeps_pcm_and_never_writes_db(path, tmp_path, monkeypatch):
    with Library(tmp_path) as library:
        service = RecordingService(library, {"mic": AudioFormat(48000, 1)})
        try:
            service.start()
            calls, original = [], library.defer_capture_health

            def marker(*args):
                calls.append(threading.current_thread().name)
                return original(*args)

            monkeypatch.setattr(library, "defer_capture_health", marker)
            target = "_track_event" if path == "submit" else "_gap"
            saved = getattr(service, target)
            monkeypatch.setattr(
                service, target, lambda *a, **k: (_ for _ in ()).throw(OSError("health callback"))
            )
            if path == "observe":
                assert service.observe_health("mic", service.epochs["mic"], {"event": "idle"})
                monkeypatch.setattr(service, target, saved)
            assert service.submit(pcm(service, 0))
            assert threading.current_thread().name not in calls
            monkeypatch.setattr(service, target, saved)
            assert service.health_snapshot()["accepting"] and not service.storage_failed
            service.pause(timeout=30)
            assert service._health_deferred
            assert sum(c.frame_count for c in library.chunks(service.session_id)) == 3
            service.stop(timeout=30)
        finally:
            service.join_writer()


@pytest.mark.parametrize(
    "kind", ("future", "corrupt"), ids=["G08-FIX1-X-FUTURESTOP", "G08-FIX1-X-CORRUPTSTOP"]
)
def test_unreadable_health_does_not_prevent_recording_or_stop(kind, tmp_path):
    with Library(tmp_path) as library:
        service = RecordingService(library, {"mic": AudioFormat(48000, 1)})
        try:
            service.start()
            if kind == "future":
                library._db.execute("UPDATE capture_health_runs SET schema_version=3")
            else:
                library._db.execute("UPDATE sessions SET capture_health='{' ")
            library._db.commit()
            service._checkpoint_health(force=True)
            assert service.health_snapshot()["accepting"] and not service.storage_failed
            assert service.submit(pcm(service, 0))
            result = service.stop(timeout=30)
            assert result["health_status"] == "DEFERRED" and result["finalized"] is False
            assert result["frame_count"] == 3 and not service.storage_failed
            assert library.get_session(service.session_id).state == SessionState.PAUSED
        finally:
            service.join_writer()


@pytest.mark.parametrize("operation", ["begin_capture_health"], ids=["G08-FIX1-X-RESUMEBEGIN"])
def test_begin_failure_after_a_closed_run_gets_its_own_unknown_tail(
    operation, tmp_path, monkeypatch
):
    with Library(tmp_path) as library:
        service = RecordingService(library, {"mic": AudioFormat(48000, 1)})
        try:
            service.start()
            assert service.submit(pcm(service, 0))
            previous = service.epochs["mic"]
            service.pause(timeout=30)
            original = getattr(library, operation)
            monkeypatch.setattr(
                library, operation, lambda *a, **k: (_ for _ in ()).throw(OSError("resume health"))
            )
            service.resume()
            current = service.epochs["mic"]
            assert service.submit(pcm(service, 0))
            monkeypatch.setattr(library, operation, original)
            assert service.stop(timeout=30)["frame_count"] == 6
            tails = [
                json.loads(r[0])
                for r in library._db.execute("SELECT payload FROM capture_health_events")
                if json.loads(r[0])["reason"] == "UNKNOWN_TAIL"
            ]
            assert {tail["epoch_id"] for tail in tails} == {current}
            assert current != previous and tails[0]["lost_frames"] is None
        finally:
            service.join_writer()


@pytest.mark.parametrize("case", range(7, 11), ids=[f"G08-FIX1-{n:02}" for n in range(7, 11)])
def test_compatibility_projection_has_a_byte_budget(case, tmp_path):
    with Library(tmp_path) as library:
        service = RecordingService(
            library, {t: AudioFormat(48000, 1) for t in ("mic", "system")}, session_id="s"
        )
        original = {
            "epochs": [
                {"tracks": {"mic": {"epoch_id": f"old-{i}", "dropped_frames": i}}}
                for i in range(300 if case == 9 else 2)
            ]
        }
        library.record_capture_health("s", original)
        try:
            service.start()
            for run in range(12):
                for track in service.formats:
                    assert service.submit(pcm(service, 0, track))
                    service.observe_health(track, service.epochs[track], {"event": "idle"})
                    if case == 8:
                        from dataclasses import replace

                        offer = service._queue.offer
                        service._queue.offer = lambda _: False
                        for index in range(1, 21):
                            assert not service.submit(
                                replace(
                                    pcm(service, index, track),
                                    device_frame_position=518_400_000 + index * 10_000,
                                )
                            )
                        service._queue.offer = offer
                service._checkpoint_health(force=True)
                health = library.capture_health("s")
                health["backend_events"] = [
                    {"code": ("경고" if case == 10 else "X") * (300 if case == 8 else 100), "n": i}
                    for i in range(256)
                ]
                failures = []
                try:
                    library.record_capture_health("s", health)
                except ValueError as error:
                    failures.append(type(error).__name__)
                assert failures == []
                service.pause(timeout=30)
                raw = library._db.execute(
                    "SELECT capture_health FROM sessions WHERE session_id='s'"
                ).fetchone()[0]
                assert len(raw.encode()) <= 65536
                assert not service.storage_failed and not service._health_deferred
                if run != 11:
                    service.resume()
            archived = [
                json.loads(row[0]).get("legacy_projection")
                for row in library._db.execute(
                    "SELECT payload FROM capture_health_runs WHERE session_id='s'"
                )
            ]
            assert original in archived
            assert len(library.chunks("s")) == 24
            service.stop(timeout=30)
        finally:
            service.join_writer()


@pytest.mark.parametrize("case", (11, 12, 13), ids=[f"G08-FIX1-{n:02}" for n in (11, 12, 13)])
def test_device_continuity_requires_proof(case, tmp_path):
    from dataclasses import replace

    from recoryn.app.status import track_health_lines

    with Library(tmp_path) as library:
        service = RecordingService(library, {"mic": AudioFormat(48000, 1)})
        try:
            service.start()
            for i, position in enumerate((0, 480, 4800, 5280)):
                block = replace(
                    pcm(service, i, frames=480),
                    device_frame_position=None if case == 12 else position,
                    flags=("TIMESTAMP_ERROR",) if case == 13 and i == 1 else (),
                )
                assert service.submit(block)
            if case != 11:
                assert service._pending_events
                assert service._pending_events[0]["lost_frames"] is None
            live = service.health_snapshot()
            service.stop(timeout=30)
            stored = library.capture_health(service.session_id)
            for value in (live, stored):
                track = value.get("track_health", value.get("tracks"))["mic"]
                assert track["known_loss_frames"] == (3840 if case == 11 else None)
                text = "\n".join(track_health_lines(value))
                if case != 11:
                    assert "장치 유실 미상" in text and "확인된 유실 union 0" not in text
        finally:
            service.join_writer()


@pytest.mark.parametrize("case", (14, 15, 16), ids=[f"G08-FIX1-{n:02}" for n in (14, 15, 16)])
def test_all_legacy_tracks_survive_partial_repair(case, tmp_path, monkeypatch):
    with Library(tmp_path) as library:
        library.create_session("s")
        library.transition("s", SessionState.RECORDING, 0)
        library.record_capture_health(
            "s",
            {
                "epochs": [
                    {
                        "tracks": {
                            t: {"epoch_id": "legacy-" + t, "dropped_frames": n}
                            for t, n in (("mic", 6), ("system", 0))
                        }
                    }
                ]
            },
        )
        original, calls = library._store_health, []

        def fault(*a, **k):
            calls.append(1)
            if len(calls) == 2:
                raise sqlite3.OperationalError("second legacy commit failed")
            return original(*a, **k)

        if case != 14:
            monkeypatch.setattr(library, "_store_health", fault)
            first = library.recover_session("s")
            assert first["health_recovery"]["status"] == "DEFERRED"
            monkeypatch.setattr(library, "_store_health", original)
            if case == 16:
                library.close()
                with Library(tmp_path) as reopened:
                    fixed = reopened.recover_session("s")
                    assert fixed["health_recovery"]["status"] == "RECOVERED_UNCLEAN"
                    tails = [
                        json.loads(r[0])
                        for r in reopened._db.execute("SELECT payload FROM capture_health_events")
                    ]
                    assert {e["track_id"] for e in tails} == {"mic", "system"}
                    assert set(reopened.capture_health("s")["tracks"]) == {"mic", "system"}
                    before = rows(reopened)
                    reopened.recover_session("s")
                    assert rows(reopened) == before
                return
        result = library.recover_session("s")
        assert result["health_recovery"]["status"] == "RECOVERED_UNCLEAN"
        tails = [
            json.loads(r[0])
            for r in library._db.execute("SELECT payload FROM capture_health_events")
        ]
        assert {e["track_id"] for e in tails} == {"mic", "system"}
        assert all(e["lost_frames"] is None for e in tails)
        assert set(library.capture_health("s")["tracks"]) == {"mic", "system"}
        before = rows(library)
        assert library.recover_session("s")["health_recovery"] == result["health_recovery"]
        assert rows(library) == before


@pytest.mark.parametrize("case", (17, 18, 19), ids=[f"G08-FIX1-{n:02}" for n in (17, 18, 19)])
def test_idle_is_one_observation_interval(case, tmp_path):
    with Library(tmp_path) as library:
        service = RecordingService(library, {"mic": AudioFormat(48000, 1)})
        try:
            service.start()
            for _ in range(100):
                assert service.observe_health("mic", service.epochs["mic"], {"event": "idle"})
            assert sum(e["reason"] == "NO_PACKETS" for e in service._pending_events) == 1
            if case != 17:
                assert service.submit(pcm(service, 0))
                assert (
                    sum(
                        e["reason"] == "NO_PACKETS" and e["kind"] == "CLOSE"
                        for e in service._pending_events
                    )
                    == 1
                )
                if case == 19:
                    service.observe_health("mic", service.epochs["mic"], {"event": "idle"})
            service.stop(timeout=30)
            events = [
                json.loads(r[0])
                for r in library._db.execute("SELECT payload FROM capture_health_events")
            ]
            assert sum(e["reason"] == "NO_PACKETS" and e["kind"] == "CLOSE" for e in events) == (
                2 if case == 19 else 1
            )
        finally:
            service.join_writer()


@pytest.mark.parametrize(
    "case", (23, 24, 25, 26, 27), ids=[f"G08-FIX1-{n:02}" for n in (23, 24, 25, 26, 27)]
)
def test_reviewer_guard_boundaries(case, tmp_path, monkeypatch):
    from recoryn.app.status import track_health_lines
    from recoryn.cli import _export

    with Library(tmp_path / "library") as library:
        value, version = tracked_seed(library)
        if case == 23:
            library.transition("s", SessionState.FINALIZING, 1)
            with pytest.raises(StateConflict, match="HEALTH_RECOVERY_PENDING"):
                library.finalize_session("s")
        elif case == 24:
            library._db.execute("INSERT INTO deleted_sessions VALUES('s',1000,'DELETE_PENDING')")
            library._db.commit()
            value["checkpoint_seq"] += 1
            with pytest.raises(StateConflict, match="DELETE_PENDING"):
                library.checkpoint_capture_health("s", value, expected_health_version=version)
        elif case == 25:
            close_run(library, value, version)
            library.transition("s", SessionState.FINALIZING, 2)
            library.finalize_session("s")
            original = library.capture_health_details

            def changed(*a, **k):
                page = original(*a, **k)
                if page["next_cursor"] is None:
                    current = library.capture_health("s")
                    current["health_version"] += 1
                    library._db.execute(
                        "UPDATE sessions SET capture_health=? WHERE session_id='s'",
                        (json.dumps(current),),
                    )
                    library._db.execute(
                        "UPDATE capture_health_runs SET health_version=? WHERE session_id='s'",
                        (current["health_version"],),
                    )
                    library._db.commit()
                return page

            monkeypatch.setattr(library, "capture_health_details", changed)
            with pytest.raises(ValueError, match="HEALTH_SNAPSHOT_CHANGED"):
                _export(library, "s", tmp_path / "out")
            assert not (tmp_path / "out/export.json").exists()
        elif case == 26:
            text = "\n".join(track_health_lines({"tracks": {"mic": {"media_loss_unknown": True}}}))
            assert "장치 유실 또는 미관측 범위 미상" in text
        else:
            service = RecordingService(library, {"mic": AudioFormat(48000, 1)})
            try:
                service.start()
                original = library.checkpoint_capture_health

                def race(*a, **k):
                    raise StateConflict("HEALTH_SNAPSHOT_CHANGED")

                monkeypatch.setattr(library, "checkpoint_capture_health", race)
                service._checkpoint_health(force=True)
                assert not service._health_deferred and service.health_snapshot()["accepting"]
                monkeypatch.setattr(library, "checkpoint_capture_health", original)
                service.stop(timeout=30)
            finally:
                service.join_writer()


@pytest.mark.parametrize("case", (30, 31), ids=[f"G08-FIX1-{n:02}" for n in (30, 31)])
def test_control_cutoff_is_idempotent(case, tmp_path, monkeypatch):
    from recoryn.app.recording import RecordingError

    with Library(tmp_path) as library:
        service = RecordingService(library, {"mic": AudioFormat(48000, 1)})
        try:
            service.start()
            original = service._join_workers
            monkeypatch.setattr(
                service,
                "_join_workers",
                lambda _: (_ for _ in ()).throw(RecordingError("WRITER_ACK_PENDING")),
            )
            reason = "PAUSE" if case == 30 else "SUSPEND"
            with pytest.raises(RecordingError):
                service.pause(reason=reason)
            monkeypatch.setattr(service, "_join_workers", original)
            service.pause(timeout=30, reason=reason)
            events = [
                json.loads(r[0])
                for r in library._db.execute("SELECT payload FROM capture_health_events")
            ]
            assert sum(e["reason"] == reason and e["kind"] == "OPEN" for e in events) == 1
            service.stop(timeout=30)
        finally:
            service.join_writer()


@pytest.mark.parametrize("case", (32, 33), ids=[f"G08-FIX1-{n:02}" for n in (32, 33)])
def test_recovery_conflict_is_not_corruption(case, tmp_path, monkeypatch):
    with Library(tmp_path) as library:
        tracked_seed(library)
        code = "HEALTH_SNAPSHOT_CHANGED" if case == 32 else "DELETION_HISTORY_UNAVAILABLE"
        monkeypatch.setattr(
            library, "_store_health", lambda *a, **k: (_ for _ in ()).throw(StateConflict(code))
        )
        result = library.recover_session("s")
        assert result["health_recovery"]["code"] == (
            "HEALTH_RECOVERY_PENDING" if case == 32 else code
        )


@pytest.mark.parametrize("case", (34, 35), ids=[f"G08-FIX1-{n:02}" for n in (34, 35)])
def test_overload_keeps_bounded_detail_and_exact_counts(case, tmp_path, monkeypatch):
    import recoryn.app.recording as module

    with Library(tmp_path) as library:
        service = RecordingService(library, {"mic": AudioFormat(48000, 1)})
        try:
            service.start()
            monkeypatch.setattr(service._queue, "offer", lambda _: False)
            original, made = module.GapFact, []

            def counted(*a, **k):
                made.append(1)
                return original(*a, **k)

            monkeypatch.setattr(module, "GapFact", counted)
            total = 0
            for i in range(1000):
                frames = 3 if case == 34 else i % 5 + 1
                block = pcm(service, i, frames=frames)
                total += frames
                assert not service.submit(block)
            assert len(made) <= 256
            assert service.health_snapshot()["tracks"]["mic"]["dropped_frames"] == total
            assert len(service._pending_events) <= 256
            service.stop(timeout=30)
        finally:
            service.join_writer()


def tracked_seed(library, tracks=1, prefix=6):
    values = snapshot()["tracks"]
    values["mic"]["dropped_frames"] = prefix
    if tracks == 2:
        values["system"] = {**values["mic"], "epoch_id": "system-epoch"}
    return seed(library, tracks=values)


def rows(library):
    return [
        tuple(tuple(r) for r in library._db.execute(f"SELECT * FROM {table} ORDER BY 1,2"))
        for table in ("capture_health_runs", "capture_health_tracks", "capture_health_events")
    ]


def close_run(library, value, version):
    value = copy.deepcopy(value)
    value["checkpoint_seq"] += 1
    library.finish_capture_health(
        "s",
        value,
        expected_health_version=version,
        receipt=CaptureReceipt("run", True, True, True, False),
    )
    state = library.get_session("s")
    library.transition("s", SessionState.PAUSED, state.state_version)


@pytest.mark.parametrize("row", R, ids=[f"G08-R-{i:03}" for i in range(1, 225)])
def test_recovery_authority_and_idempotence(row, tmp_path, request):
    health, deletion, live, repeat, tracks = row
    with Library(tmp_path) as library:
        if health in {"LEGACY", "MISSING"}:
            library.create_session("s")
            library.transition("s", SessionState.RECORDING, 0)
            if health == "LEGACY":
                library.record_capture_health(
                    "s",
                    {
                        "epochs": [
                            {
                                "tracks": {
                                    t: {"epoch_id": "epoch-" + t, "dropped_frames": 6}
                                    for t in ("mic", "system")[:tracks]
                                }
                            }
                        ]
                    },
                )
                library.transition("s", SessionState.PAUSED, 1)
            else:
                for track in ("mic", "system")[:tracks]:
                    block = PCMBlock(
                        "s",
                        track,
                        "epoch-" + track,
                        0,
                        AudioFormat(48000, 1),
                        3,
                        b"\x01\0" * 3,
                        0,
                        0,
                        0,
                    )
                    writer = ChunkWriter(library.root, block)
                    writer.append(block)
                    library.register_chunk(writer.seal())
        else:
            value, version = tracked_seed(library, tracks)
            if health == "CLOSED":
                close_run(library, value, version)
            elif health == "UNCLEAN":
                library.recover_session("s")
            elif health == "FUTURE":
                library._db.execute("UPDATE capture_health_runs SET schema_version=3")
                library._db.commit()
            elif health == "CORRUPT":
                library._db.execute("UPDATE capture_health_runs SET payload='{' ")
                library._db.commit()
        owner = SimpleNamespace(is_live=lambda: True)

        # SimpleNamespace is not weak-referenceable; use an actual owner object.
        class Owner:
            def is_live(self):
                return True

        if live:
            owner = Owner()
            library.register_live_owner("s", owner)
        if deletion in {"db", "tombstone"}:
            library._db.execute(
                "INSERT INTO deleted_sessions VALUES('s',1000,?)",
                ("DELETED_LOCAL" if deletion == "tombstone" else "DELETE_PENDING",),
            )
            library._db.commit()
        elif deletion == "journal":
            library.close()
            (tmp_path / "deletion-journal" / "s.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "session_id": "s",
                        "generation": 1000,
                        "state": "DELETE_REQUESTED",
                    }
                ),
                encoding="utf-8",
            )
            library = Library(tmp_path)
            request.addfinalizer(library.close)
            if live:
                library.register_live_owner("s", owner)
        before = rows(library)
        if live and deletion == "none":
            with pytest.raises(StateConflict, match="SESSION_LIVE"):
                library.recover_session("s")
            assert rows(library) == before
            return
        result = library.recover_session("s")
        if deletion != "none":
            assert result["state"] == "DELETE_PENDING" and rows(library) == before
            return
        if health in {"FUTURE", "CORRUPT"}:
            assert result["health_recovery"]["status"] == "DEFERRED"
            assert rows(library) == before
        else:
            marker = library._db.execute("SELECT payload FROM capture_health_events").fetchall()
            tails = [
                json.loads(r[0]) for r in marker if json.loads(r[0])["reason"] == "UNKNOWN_TAIL"
            ]
            assert len(tails) == (tracks if health in {"OPEN", "UNCLEAN", "MISSING"} else 0)
            assert all(e["lost_frames"] is None for e in tails)
            if health in {"OPEN", "UNCLEAN", "CLOSED"}:
                assert library.capture_health("s")["tracks"]["mic"]["dropped_frames"] == 6
        if repeat:
            after = rows(library)
            again = library.recover_session("s")
            assert rows(library) == after
            assert again["health_recovery"] == result["health_recovery"]


def pcm(service, sequence, track="mic", frames=3, silent=False):
    return PCMBlock(
        service.session_id,
        track,
        service.epochs[track],
        sequence,
        service.formats[track],
        frames,
        (b"\0\0" if silent else b"\x01\0") * frames,
        sequence * 1000,
        sequence * 1000,
        sequence * frames,
        flags=("SILENT",) if silent else (),
    )


@pytest.mark.parametrize("row", Q, ids=[f"G08-Q-{i:02}" for i in range(1, 19)])
def test_offer_has_one_loss_authority(row, tmp_path):
    outcome, pattern, tracks = row
    with Library(tmp_path) as library:
        service = RecordingService(
            library, {t: AudioFormat(48000, 1) for t in ("mic", "system")[:tracks]}
        )
        try:
            service.start()
            original = service._queue.offer
            submitted, accepted = [], []
            if outcome == "queue":
                service._queue.offer = lambda block: False
            elif outcome == "gate":
                with service._gate:
                    service._accepting = False
            for n, frames in enumerate((120, 480, 960) if pattern == "variable" else (480,) * 3):
                block = pcm(service, n, frames=frames, silent=pattern == "silent")
                from dataclasses import replace

                block = replace(block, device_frame_position=sum(b.frame_count for b in submitted))
                submitted.append(block)
                got = service.submit(block)
                accepted.append(got)
                assert got is (outcome == "accept")
                service.observe_health(
                    "mic",
                    block.epoch_id,
                    {
                        "event": "packet",
                        "accepted": got,
                        "rejected_frames": frames,
                        "frame_count": frames,
                    },
                )
            if outcome == "queue":
                service._queue.offer = original
            result = service.stop(timeout=60)
            summary = library.capture_health(service.session_id)
            total = sum(b.frame_count for b in submitted)
            assert summary["tracks"]["mic"]["device_lost_frames"] == 0
            assert summary["tracks"]["mic"]["dropped_frames"] == (
                total if outcome == "queue" else 0
            )
            assert result["frame_count"] == sum(
                b.frame_count for b, yes in zip(submitted, accepted, strict=True) if yes
            )
            actual = b"".join(
                (library.root / c.relative_path / "audio.pcm").read_bytes()
                for c in library.chunks(service.session_id)
            )
            assert actual == b"".join(
                b.payload for b, yes in zip(submitted, accepted, strict=True) if yes
            )
            losses = [
                json.loads(r[0])
                for r in library._db.execute("SELECT payload FROM capture_health_events")
                if json.loads(r[0])["reason"] == "QUEUE_DROP"
            ]
            assert sum(e["lost_frames"] for e in losses) == (total if outcome == "queue" else 0)
        finally:
            service.join_writer()


@pytest.mark.parametrize("row", P, ids=[f"G08-P-{i:02}" for i in range(1, 13)])
def test_closed_needs_all_receipts(row, tmp_path):
    workers, sources, tracks = row
    with Library(tmp_path) as library:
        value, version = tracked_seed(library, tracks)
        value["checkpoint_seq"] += 1
        receipt = CaptureReceipt("run", True, sources, workers == "ok", workers == "failed")
        if workers == "ok" and sources:
            library.finish_capture_health(
                "s", value, expected_health_version=version, receipt=receipt
            )
            assert (
                library._db.execute("SELECT status FROM capture_health_runs").fetchone()[0]
                == "CLOSED"
            )
        else:
            before = rows(library)
            with pytest.raises(StateConflict, match="HEALTH_ACK_PENDING"):
                library.finish_capture_health(
                    "s", value, expected_health_version=version, receipt=receipt
                )
            assert rows(library) == before


@pytest.mark.parametrize("row", F, ids=[f"G08-F-{i:02}" for i in range(1, 21)])
def test_deferred_health_blocks_finalization(row, tmp_path, monkeypatch):
    state, action, repeat = row
    with Library(tmp_path) as library:
        value, version = tracked_seed(library)
        if state == "CLOSED":
            close_run(library, value, version)
        elif state in {"FUTURE", "CORRUPT"}:
            library._db.execute(
                "UPDATE capture_health_runs SET schema_version=3"
                if state == "FUTURE"
                else "UPDATE capture_health_runs SET payload='{' "
            )
            library._db.commit()
        elif state == "FAIL":
            original = library._store_health

            def fail(*args, **kwargs):
                if kwargs.get("status") == "RECOVERED_UNCLEAN":
                    raise OSError("injected tail persistence failure")
                return original(*args, **kwargs)

            monkeypatch.setattr(library, "_store_health", fail)
        call = library.recover_session if action == "recover" else library.finalize_unfinished
        for _ in range(2 if repeat else 1):
            error = None
            try:
                result = call("s")
            except ValueError as caught:
                error = caught
            assert error is None, "건강 보류는 구조화한 결과로 반환해야 합니다: " + str(error)
            recovered = result.get("recovery", result)
            if state in {"FAIL", "CORRUPT", "FUTURE"}:
                assert recovered["health_recovery"]["status"] == "DEFERRED"
                assert library.get_session("s").state is not SessionState.FINALIZED
            elif action == "finalize":
                assert result["state"] == "FINALIZED"
            else:
                assert recovered["health_recovery"]["status"] in {"CLOSED", "RECOVERED_UNCLEAN"}


@pytest.mark.parametrize("row", ORDERS, ids=[f"G08-O-{i:02}" for i in range(1, 25)])
def test_ordered_capture_boundaries(row, tmp_path, monkeypatch):
    event, first, tracks = row
    with Library(tmp_path) as library:
        if event in {0, 1, 2, 4}:
            service = RecordingService(
                library, {t: AudioFormat(48000, 1) for t in ("mic", "system")[:tracks]}
            )
            try:
                service.start()
                if event == 4:
                    entered, release = threading.Event(), threading.Event()
                    original = library.checkpoint_capture_health

                    def held(*args, **kwargs):
                        entered.set()
                        assert release.wait(5)
                        return original(*args, **kwargs)

                    monkeypatch.setattr(library, "checkpoint_capture_health", held)
                    worker = threading.Thread(target=lambda: service._checkpoint_health(force=True))
                    worker.start()
                    assert entered.wait(5)
                    submitted = threading.Event()
                    result = []

                    def submit():
                        result.append(
                            service.submit(pcm(service, 0, "system" if tracks == 2 else "mic"))
                        )
                        submitted.set()

                    producer = threading.Thread(target=submit)
                    producer.start()
                    try:
                        assert submitted.wait(1), "checkpoint held the input gate"
                        assert result == [True]
                    finally:
                        release.set()
                        worker.join(5)
                        producer.join(5)
                    assert not worker.is_alive()
                elif event == 2:
                    if first:
                        assert service.submit(pcm(service, 0))
                    service.pause(timeout=60)
                    assert not service.submit(pcm(service, 1))
                    assert library.capture_health(service.session_id)["tracks"]["mic"][
                        "accepted_frames"
                    ] == (3 if first else 0)
                else:
                    if first:
                        service._checkpoint_health(force=True)
                    service.observe_health("mic", service.epochs["mic"], {"event": "error"})
                    if tracks == 2:
                        assert service.submit(pcm(service, 0, "system"))
                    assert not service.submit(pcm(service, 0))
                    if not first:
                        service._checkpoint_health(force=True)
                    assert (
                        service.health_snapshot()["track_health"]["mic"]["reason"] == "DEVICE_LOST"
                    )
                service.stop(timeout=60)
            finally:
                service.join_writer()
        else:
            value, version = tracked_seed(library, tracks)
            if event == 3:
                if first:
                    library.checkpoint_capture_health("s", value, expected_health_version=version)
                close_run(library, value, version)
                with pytest.raises(StateConflict):
                    library.checkpoint_capture_health("s", value, expected_health_version=version)
            else:
                from contextlib import contextmanager

                entered, release = threading.Event(), threading.Event()
                original_authority, original_store = library.job_authority, library._store_health
                errors = []
                inside_store = [False, 0]

                @contextmanager
                def held_authority(db, sid):
                    if threading.current_thread().name == "health-recovery" and inside_store[0]:
                        inside_store[1] += 1
                    if not first and inside_store[0] and inside_store[1] == 2:
                        entered.set()
                        assert release.wait(5)
                    with original_authority(db, sid) as authority:
                        yield authority

                def held_store(*args, **kwargs):
                    inside_store[:] = [True, 0]
                    try:
                        result = original_store(*args, **kwargs)
                    finally:
                        inside_store[0] = False
                    if first and kwargs.get("status") == "RECOVERED_UNCLEAN":
                        entered.set()
                        assert release.wait(5)
                    return result

                monkeypatch.setattr(library, "job_authority", held_authority)
                monkeypatch.setattr(library, "_store_health", held_store)

                def recover():
                    try:
                        library.recover_session("s")
                    except StateConflict as error:
                        errors.append(str(error))

                worker = threading.Thread(target=recover, name="health-recovery")
                worker.start()
                try:
                    assert entered.wait(5)
                    pending = library.delete_session("s")
                    assert pending["state"] == "DELETE_PENDING"
                finally:
                    release.set()
                    worker.join(5)
                assert not worker.is_alive()
                assert library._db.execute("SELECT COUNT(*) FROM capture_health_events").fetchone()[
                    0
                ] == (tracks if first else 0)
                assert library.retry_deletion(
                    "s", expected_generation=library.deletion_generation("s")
                )["deleted"]
                assert (
                    library._db.execute("SELECT COUNT(*) FROM capture_health_events").fetchone()[0]
                    == 0
                )


def test_g08_x_overflow_retains_exact_count_and_control_lifetime(tmp_path):
    with Library(tmp_path) as library:
        service = RecordingService(library, {"mic": AudioFormat(48000, 1)})
        try:
            service.start()
            offer = service._queue.offer
            service._queue.offer = lambda _: False
            for seq in range(300):
                assert not service.submit(pcm(service, seq))
            service._queue.offer = offer
            service.pause(timeout=60)
            health = library.capture_health(service.session_id)
            assert health["tracks"]["mic"]["dropped_frames"] == 900
            assert health["detail_complete"] is False
            events = [
                json.loads(r[0])
                for r in library._db.execute("SELECT payload FROM capture_health_events")
            ]
            pause = [e for e in events if e["reason"] == "PAUSE"]
            assert len(pause) == 1 and pause[0]["open"] is True
            service.resume()
            service.stop(timeout=60)
            events = [
                json.loads(r[0])
                for r in library._db.execute("SELECT payload FROM capture_health_events")
            ]
            closed = [
                e for e in events if e["gap_id"] == pause[0]["gap_id"] and e["kind"] == "CLOSE"
            ]
            assert len(closed) == 1 and closed[0]["end"] >= closed[0]["start"]
        finally:
            service.join_writer()


def test_g08_x_actual_sealer_must_ack_before_closed(tmp_path, monkeypatch):
    from recoryn.app.recording import RecordingError
    from recoryn.storage import ChunkWriter

    entered, release = threading.Event(), threading.Event()
    original = ChunkWriter.seal

    def seal(writer):
        entered.set()
        assert release.wait(5)
        return original(writer)

    monkeypatch.setattr(ChunkWriter, "seal", seal)
    with Library(tmp_path) as library:
        service = RecordingService(library, {"mic": AudioFormat(48000, 1)}, chunk_frames=3)
        try:
            service.start()
            assert service.submit(pcm(service, 0))
            assert entered.wait(5)
            with pytest.raises(RecordingError, match="WRITER_ACK_PENDING"):
                service.pause(timeout=0.01)
            assert service.is_live()
            assert (
                library._db.execute("SELECT status FROM capture_health_runs").fetchone()[0]
                == "OPEN"
            )
            release.set()
            service.join_writer()
            service.stop(timeout=60)
            assert (
                library._db.execute("SELECT status FROM capture_health_runs").fetchone()[0]
                == "CLOSED"
            )
        finally:
            release.set()
            service.join_writer()


def test_g08_x_suspend_and_current_source_tokens(tmp_path):
    from recoryn.app.desktop import DesktopRecorder
    from recoryn.app.power import PowerCoordinator
    from tests.integration.test_desktop_independent import ControlledSource, choices

    sources = [ControlledSource(), ControlledSource()]
    with Library(tmp_path) as library:
        controller = DesktopRecorder(library, lambda device, loopback: sources[device == "system"])
        try:
            controller.start(choices("mic", "system"))
            old_callback = sources[0].on_health
            assert sources[0].emit() and sources[1].emit()
            power = PowerCoordinator(controller)
            assert power.suspend() and power.resume_required
            assert all(not source.running for source in sources)
            power.resume()
            old_callback({"event": "error"})
            assert controller.recording.health_snapshot()["track_health"]["mic"]["state"] == "OK"
            assert sources[1].emit(sequence=1)
            controller.stop()
            events = [
                json.loads(r[0])
                for r in library._db.execute("SELECT payload FROM capture_health_events")
            ]
            assert len([e for e in events if e["reason"] == "SUSPEND" and e["kind"] == "OPEN"]) == 2
            assert not any(e["reason"] == "PAUSE" for e in events)
        finally:
            for source in sources:
                source.stop_pending = False
            controller.close()


def test_g08_x_control_cutoff_follows_all_source_acks(tmp_path):
    from recoryn.app.desktop import DesktopRecorder
    from tests.integration.test_desktop_independent import ControlledSource, choices

    class Inflight(ControlledSource):
        def stop(self, timeout=5):
            if self.running:
                self.last_accepted = self.emit()
            super().stop(timeout)

    sources = [Inflight(), Inflight()]
    with Library(tmp_path) as library:
        controller = DesktopRecorder(library, lambda device, loopback: sources[device == "system"])
        try:
            sid = controller.start(choices("mic", "system"))
            controller.pause()
            assert [s.last_accepted for s in sources] == [True, True]
            assert sum(c.frame_count for c in library.chunks(sid)) == 96
            assert all(
                v["accepted_frames"] == 48 for v in library.capture_health(sid)["tracks"].values()
            )
        finally:
            controller.close()


def test_g08_x_timestamp_error_never_fabricates_a_media_hole(tmp_path):
    from dataclasses import replace

    with Library(tmp_path) as library:
        service = RecordingService(library, {"mic": AudioFormat(48000, 1)})
        try:
            service.start()
            blocks = [pcm(service, i) for i in range(3)]
            blocks[1] = replace(blocks[1], flags=("TIMESTAMP_ERROR",))
            assert all(service.submit(b) for b in blocks)
            assert service.stop(timeout=60)["frame_count"] == 9
            assert (
                library.capture_health(service.session_id)["tracks"]["mic"]["device_lost_frames"]
                == 0
            )
            events = [
                json.loads(row[0])
                for row in library._db.execute("SELECT payload FROM capture_health_events")
            ]
            assert events and all(e["lost_frames"] is None for e in events)
            assert (
                library.capture_health(service.session_id)["tracks"]["mic"]["known_loss_frames"]
                is None
            )
        finally:
            service.join_writer()


def test_g08_x_indexed_pages_preserve_every_row_and_reject_stale_cursor(tmp_path):
    from tests.unit.test_track_health import fact

    with Library(tmp_path) as library:
        value, version = tracked_seed(library)
        value["tracks"]["mic"]["dropped_frames"] = 3000
        for batch in range(2):
            value["checkpoint_seq"] += 1
            value["events"] = [
                fact(event_id=f"event{n}", gap_id=f"gap{n}", ordinal=n).to_dict()
                for n in range(batch * 150, (batch + 1) * 150)
            ]
            version = library.checkpoint_capture_health("s", value, expected_health_version=version)
        queries, all_rows, cursor = [], [], None
        library._db.set_trace_callback(queries.append)
        try:
            while True:
                page = library.capture_health_details(
                    "s", cursor=cursor, limit=7, expected_health_version=version
                )
                all_rows.extend(page["rows"])
                cursor = page["next_cursor"]
                if cursor is None:
                    break
        finally:
            library._db.set_trace_callback(None)
        assert len(all_rows) == 302
        events = [r["value"]["event_id"] for r in all_rows if r["kind"] == "event"]
        assert len(events) == len(set(events)) == 300
        assert set(events) == {f"event{n}" for n in range(300)}
        orders = {q for q in queries if q.startswith("SELECT") and "ORDER BY" in q}
        assert len(orders) >= 3
        for query in orders:
            plan = [tuple(r) for r in library._db.execute("EXPLAIN QUERY PLAN " + query)]
            assert not any("TEMP B-TREE" in str(r) for r in plan), plan
        cursor = library.capture_health_details("s", limit=1)["next_cursor"]
        value["checkpoint_seq"] += 1
        value["events"] = []
        library.checkpoint_capture_health("s", value, expected_health_version=version)
        with pytest.raises(StateConflict, match="HEALTH_SNAPSHOT_CHANGED"):
            library.capture_health_details("s", cursor=cursor)


def test_g08_x_device_loss_prefix_cannot_decrease(tmp_path):
    with Library(tmp_path) as library:
        value, version = tracked_seed(library)
        value["tracks"]["mic"]["device_lost_frames"] = 6
        value["checkpoint_seq"] = 1
        version = library.checkpoint_capture_health("s", value, expected_health_version=version)
        before = library.capture_health("s")
        value["tracks"]["mic"]["device_lost_frames"] = 0
        value["checkpoint_seq"] = 2
        with pytest.raises(StateConflict, match="HEALTH_EVENT_CONFLICT"):
            library.checkpoint_capture_health("s", value, expected_health_version=version)
        assert library.capture_health("s") == before


def test_g08_x_legacy_epochs_are_not_destroyed_by_bounded_v2_projection(tmp_path):
    with Library(tmp_path) as library:
        library.create_session("s")
        library.transition("s", SessionState.RECORDING, 0)
        epochs = [
            {"tracks": {"mic": {"epoch_id": f"legacy{n}", "dropped_frames": n}}} for n in range(12)
        ]
        library.record_capture_health("s", {"epochs": copy.deepcopy(epochs)})
        assert library.recover_session("s")["health_recovery"]["status"] == "RECOVERED_UNCLEAN"
        summary = library.capture_health("s")
        assert [e for e in summary["epochs"] if not e.get("capture_run_id")] == epochs
        assert len([e for e in summary["epochs"] if e.get("capture_run_id")]) == 8
        assert library._db.execute("SELECT COUNT(*) FROM capture_health_runs").fetchone()[0] == 12
        assert library.recover_session("s")["health_recovery"]["status"] == "RECOVERED_UNCLEAN"
        assert [
            e for e in library.capture_health("s")["epochs"] if not e.get("capture_run_id")
        ] == epochs


@pytest.mark.parametrize(
    "cursor",
    [
        True,
        "{",
        '{"schema_version":2}',
        '{"schema_version":1,"health_version":1,"phase":"bad","key":null}',
        '{"schema_version":1,"health_version":1,"phase":"event","key":["run",true,"e"]}',
    ],
    ids=[f"G08-X-CURSOR-{i}" for i in range(5)],
)
def test_g08_x_cursor_is_a_closed_versioned_value(tmp_path, cursor):
    from recoryn.domain import ValidationError

    with Library(tmp_path) as library:
        tracked_seed(library)
        with pytest.raises(ValidationError):
            library.capture_health_details("s", cursor=cursor)


def test_g08_x_capture_checkpoint_does_not_read_another_intent_body(tmp_path, monkeypatch):
    from recoryn.storage import library as module

    with Library(tmp_path) as library:
        library.create_session("other")
        service = RecordingService(library, {"mic": AudioFormat(48000, 1)})
        try:
            service.start()
            library.delete_session("other")
            original = module.read_json
            denied = []

            def read(path, **kwargs):
                if path.parent.name == "deletion-journal" and path.name == "other.json":
                    denied.append(path.name)
                    raise PermissionError("unrelated intent unavailable")
                return original(path, **kwargs)

            with monkeypatch.context() as patch:
                patch.setattr(module, "read_json", read)
                assert service.submit(pcm(service, 0))
                service._checkpoint_health(force=True)
                assert denied == []
                assert service.health_snapshot()["accepting"]
                assert not service.health_snapshot()["storage_failed"]
            assert service.stop(timeout=60)["frame_count"] == 3
        finally:
            service.join_writer()


def test_g08_x_health_management_never_walks_under_root(tmp_path, monkeypatch):
    import os
    import time

    from tests.integration.test_pending_deletion_restart import RootHoldMeter

    with Library(tmp_path) as library:
        library.create_session("s")
        other = RecordingService(library, {"mic": AudioFormat(48000, 1)}, session_id="other")
        other.start()
        meter = RootHoldMeter(library._mutex)
        monkeypatch.setattr(library, "_mutex", meter)
        originals = {"iterdir": Path.iterdir, "scandir": os.scandir, "listdir": os.listdir}

        def iterdir(path):
            meter.note_fs("iterdir")
            return originals["iterdir"](path)

        def scandir(*args, **kwargs):
            meter.note_fs("scandir")
            return originals["scandir"](*args, **kwargs)

        def listdir(*args, **kwargs):
            meter.note_fs("listdir")
            return originals["listdir"](*args, **kwargs)

        monkeypatch.setattr(Path, "iterdir", iterdir)
        monkeypatch.setattr(os, "scandir", scandir)
        monkeypatch.setattr(os, "listdir", listdir)
        result, errors = [], []

        def manage():
            try:
                value = snapshot()
                version = library.begin_capture_health("s", value, expected_state_version=0)
                value["checkpoint_seq"] = 1
                version = library.checkpoint_capture_health(
                    "s", value, expected_health_version=version
                )
                value["checkpoint_seq"] = 2
                library.finish_capture_health(
                    "s",
                    value,
                    expected_health_version=version,
                    receipt=CaptureReceipt("run", True, True, True, False),
                )
                page = library.capture_health_details("s")
                result.append(page)
            except Exception as error:
                errors.append(error)

        # Reuse the GC-P02 meter's management-thread label; it measures this worker.
        worker = threading.Thread(target=manage, name="g05-management")
        try:
            worker.start()
            seq = 0
            while worker.is_alive():
                other.submit(pcm(other, seq))
                seq += 1
                time.sleep(0.001)
            worker.join(5)
            assert errors == [] and result
            assert meter.management_fs_outside > 0
            assert meter.management_fs_under_mutex == []
            assert max(meter.management_holds) < 0.5
            measurement = {
                "management_root_max_s": max(meter.management_holds),
                "management_fs_under_mutex": meter.management_fs_under_mutex,
                "management_fs_outside": meter.management_fs_outside,
                "submitted_blocks": seq,
                "tracks": other.health_snapshot()["tracks"],
            }
            (tmp_path / "g08-root-measurement.json").write_text(
                json.dumps(measurement), encoding="utf-8"
            )
            print(json.dumps(measurement))
        finally:
            other.stop(timeout=60)
            other.join_writer()
