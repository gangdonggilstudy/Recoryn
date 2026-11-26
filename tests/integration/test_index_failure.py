"""GS02 real authority leases, forced interleavings, reopen and PCM preservation."""

import json
import os
import subprocess
import sys
import threading
import time
from itertools import product
from pathlib import Path

import pytest

from recoryn.app.recording import RecordingService
from recoryn.domain import AudioFormat, PCMBlock, StateConflict, ValidationError
from recoryn.jobs import JobStore
from recoryn.storage import ChunkWriter, Library
from tests.unit import test_index_failure as shared
from tests.unit.test_index_failure import (
    BASE,
    FAULTS,
    T,
    consume,
    fault,
    intent,
    repair,
    stamp,
)

pytestmark = pytest.mark.integration
env = shared.env


def pcm(track, index, offset=0):
    return PCMBlock(
        "s",
        track,
        "e1",
        index,
        AudioFormat(48000, 1),
        4,
        bytes([index + 1, offset + 9]) * 4,
        index * 100_000,
        index * 100_000,
        index * 4,
    )


C = list(product(FAULTS, (1, 2), (False, True)))


@pytest.mark.parametrize(
    "cause,tracks,observe_first", C, ids=[f"GS02-C-{n:03}" for n in range(1, 25)]
)
def test_management_failure_does_not_poison_capture_or_lose_accepted_pcm(
    env, monkeypatch, cause, tracks, observe_first
):
    library, clock = env
    writers, expected = {}, {}
    try:
        for offset, track in enumerate(("mic", "system")[:tracks]):
            first = pcm(track, 0, offset)
            writer = ChunkWriter(library.root, first)
            writers[track] = writer
            writer.append(first)
            expected[track] = first.payload
        fault(library, monkeypatch, cause)
        stamp(library, BASE + 1000)  # a real new publication, not a settled same-stamp rewrite
        if observe_first:
            assert consume(library, "read") == "HISTORY_UNAVAILABLE"
        for index in (1, 2):
            for offset, (track, writer) in enumerate(writers.items()):
                block = pcm(track, index, offset)
                if cause == "tmp":
                    with pytest.raises(ValidationError, match="Incomplete deletion intent"):
                        writer.append(block)
                else:
                    writer.append(block)
                    expected[track] += block.payload
            if index == 1 and not observe_first:
                assert consume(library, "read") == "HISTORY_UNAVAILABLE"
        # Explicit fixture repair of an ambiguous unfinished publication, before sealing.
        if cause == "tmp":
            (library.root / "deletion-journal/.tmp-pending").unlink()
            stamp(library, BASE + 2000)
        for track, writer in writers.items():
            sealed = writer.seal_chunk()
            try:
                library.register_chunk(sealed)
                descriptor = sealed.descriptor
                assert (
                    library.root / descriptor.relative_path / "audio.pcm"
                ).read_bytes() == expected[track]
                assert descriptor.frame_count == (4 if cause == "tmp" else 12)
            finally:
                sealed.release()
    finally:
        for writer in writers.values():
            writer.abort()


R = list(
    product(
        ("long_same_tick", "publish", "db_only", "repair", "invalidate"),
        (False, True),
        ("read", "job", "writer"),
    )
)


@pytest.mark.parametrize("event,b_first,consumer", R, ids=[f"GS02-R-{n:03}" for n in range(1, 31)])
def test_authority_interleavings_never_publish_an_older_result(
    env, monkeypatch, event, b_first, consumer
):
    library, clock = env
    clock.now = BASE + (T - 1 if event == "long_same_tick" else 10 * T)
    if event == "repair":
        fault(library, monkeypatch, "json")
    with library._mutex:
        try:
            library._refresh_intent_index()
        except ValidationError:
            pass
    ready, release = threading.Event(), threading.Event()
    read = library._read_journal
    errors, observations = [], []

    def parked():
        try:
            return read()
        finally:
            if threading.current_thread().name == "gs02-observe":
                ready.set()
                assert release.wait(5)

    monkeypatch.setattr(library, "_read_journal", parked)

    def action():
        if event == "long_same_tick":
            (library.root / "deletion-journal/s.json").write_text(
                json.dumps(intent("s")), encoding="utf-8"
            )
            stamp(library)
            clock.now += T + 1
        elif event == "publish":
            with library._mutex:
                library._publish_intent("s", 1)
        elif event == "db_only":
            with library._mutex:
                library._db.execute("INSERT INTO deleted_sessions VALUES('s',1,'DELETE_PENDING')")
                library._db.commit()
        elif event == "repair":
            repair(library)
            assert library.verify_deletion_history(fresh=True)["status"] == "READY"
            assert [s.session_id for s in library.list_sessions()] == ["s"]
        else:
            fault(library, monkeypatch, "json")
            assert library.verify_deletion_history(fresh=True)["status"] == "UNAVAILABLE"
            with pytest.raises(ValidationError, match="DELETION_HISTORY_UNAVAILABLE"):
                library.list_sessions()

    def observe():
        try:
            result = library._journal_prefetch(fresh=True)
            with library._mutex:
                observations.append(library._accept_observation(result))
        except BaseException as error:
            errors.append(error)

    writer = None
    store = None
    try:
        if consumer == "writer":
            writer = ChunkWriter(library.root, pcm("mic", 0))
            writer.append(pcm("mic", 0))
        if consumer == "job":
            store = JobStore(library.db_path)
            job = store.create("stt", "fixed")
            store.bind_session(job.job_id, "s")
        if b_first:
            action()
        thread = threading.Thread(target=observe, name="gs02-observe")
        thread.start()
        try:
            assert ready.wait(5)
            if not b_first:
                action()
        finally:
            release.set()
            thread.join(5)
        assert not thread.is_alive() and errors == [] and len(observations) == 1
        allowed = event == "repair" or (event == "invalidate" and consumer == "writer")
        if writer is not None:
            before = (writer.staging_path / "audio.pcm").read_bytes()
            if allowed:
                writer.append(pcm("mic", 1))
                assert (writer.staging_path / "audio.pcm").read_bytes() == before + pcm(
                    "mic", 1
                ).payload
            else:
                with pytest.raises((ValidationError, StateConflict), match="deletion intent"):
                    writer.append(pcm("mic", 1))
                assert (writer.staging_path / "audio.pcm").read_bytes() == before
        elif store is not None:
            # Explicit management discovery, not an implicit read in claim().
            library.verify_deletion_history(fresh=True)
            if allowed:
                assert store.claim(job.job_id, "worker").attempt_no == 1
            else:
                with pytest.raises(
                    StateConflict, match="JOB_SESSION_DELETED|DELETION_HISTORY_UNAVAILABLE"
                ):
                    store.claim(job.job_id, "worker")
                assert store.get(job.job_id) == job
        else:
            assert (consume(library, "read") == "VALID") is allowed
    finally:
        if writer is not None:
            writer.abort()
        if store is not None:
            store.close()


REOPEN = list(
    product(
        ("valid", "failed_settled", "failed_unsettled", "capture"), (False, True), (False, True)
    )
)


@pytest.mark.parametrize("state,child,media", REOPEN, ids=[f"GS02-O-{n:03}" for n in range(1, 17)])
def test_reopen_revalidates_authority_without_persisting_cache(env, tmp_path, state, child, media):
    from tests.unit.test_index_failure import prepare

    library, clock = env
    saved = None
    if media:
        writer = ChunkWriter(library.root, pcm("mic", 0))
        try:
            writer.append(pcm("mic", 0))
            sealed = writer.seal_chunk()
            try:
                library.register_chunk(sealed)
                saved = library.root / sealed.descriptor.relative_path / "audio.pcm"
            finally:
                sealed.release()
        finally:
            writer.abort()
    if state == "capture":
        library._intent_journal = None
        library._writer_names()
        assert library._journal_listing is not None
    else:
        prepare(library, clock, state)
    root = library.root
    library.close()
    if child:
        source = Path(__file__).resolve().parents[2] / "src"
        script = """import json,sys,recoryn
from pathlib import Path
from recoryn.storage import Library
from recoryn.domain import ValidationError
with Library(Path(sys.argv[1])) as lib:
    try:
        lib.check_management_history();lib.get_session('s');result='VALID'
    except ValidationError as error:
        assert error.args==('DELETION_HISTORY_UNAVAILABLE',);result='HISTORY_UNAVAILABLE'
    print(json.dumps({'state':result,'origin':recoryn.__file__}))
"""
        result = subprocess.run(
            [sys.executable, "-c", script, str(root)],
            env={**os.environ, "PYTHONPATH": str(source), "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr
        value = json.loads(result.stdout)
        assert Path(value["origin"]).is_relative_to(source)
        actual = value["state"]
    else:
        with Library(root) as reopened:
            actual = consume(reopened, "read")
    assert actual == ("HISTORY_UNAVAILABLE" if state.startswith("failed") else "VALID")
    if saved is not None:
        assert saved.read_bytes() == pcm("mic", 0).payload
    with Library(root) as reopened:
        repair(reopened)
        assert reopened.verify_deletion_history(fresh=True)["status"] == "READY"
        assert [s.session_id for s in reopened.list_sessions()] == ["s"]
        assert reopened._intent_failure is None


def recording_block(service, track, index):
    return PCMBlock(
        service.session_id,
        track,
        service.epochs[track],
        index,
        AudioFormat(48000, 1),
        480,
        bytes([index % 251 + 1, 9]) * 480,
        index * 10_000_000,
        index * 10_000_000,
        index * 480,
    )


@pytest.mark.parametrize(
    "where,tracks",
    list(product(("open", "refresh"), (1, 2))),
    ids=[f"GS02-F1-LIFE-{i:02}" for i in range(1, 5)],
)
def test_one_sharing_denial_cannot_latch_recording_creation_or_stop(
    tmp_path, monkeypatch, where, tracks
):
    root = tmp_path / "library"
    with Library(root):
        pass
    path = root / "deletion-journal/ext.json"
    path.write_text(json.dumps(intent("ext")), encoding="utf-8")
    past = time.time_ns() - 60_000_000_000
    os.utime(path.parent, ns=(past, past))
    from recoryn.storage import library as module

    original, denied = module.read_json, []
    armed = [where == "open"]

    def sharing_denial(entry, **kwargs):
        if armed[0] and entry == path:
            armed[0] = False
            denied.append(1)
            raise PermissionError("one-time-sharing-denial")
        return original(entry, **kwargs)

    monkeypatch.setattr(module, "read_json", sharing_denial)
    with Library(root) as library:
        service = RecordingService(
            library,
            {t: AudioFormat(48000, 1) for t in ("mic", "system")[:tracks]},
            session_id="rec",
        )
        expected = {track: b"" for track in service.formats}
        try:
            service.start()
            for index in range(8):
                for track in service.formats:
                    block = recording_block(service, track, index)
                    assert service.submit(block)
                    expected[track] += block.payload
            if where == "refresh":
                os.utime(path.parent, ns=(past + 1000, past + 1000))
                armed[0] = True
                assert library.verify_deletion_history(fresh=True)["status"] == "UNAVAILABLE"
                assert service.health_snapshot()["accepting"]
            assert library._intent_failure is None
            result = service.stop(timeout=30)
            assert result["state"] == "FINALIZED"
            library.create_session("next")
            chunks = library.chunks("rec")
            for track, payload in expected.items():
                actual = b"".join(
                    (library.root / c.relative_path / "audio.pcm").read_bytes()
                    for c in chunks
                    if c.track_id == track
                )
                assert actual == payload
            assert denied == [1] and service._writer_error is None
        finally:
            service.join_writer()


@pytest.mark.parametrize("tracks", (1, 2), ids=("GS02-F1-PCM-01", "GS02-F1-PCM-02"))
def test_external_corruption_is_read_once_during_unsettled_recording(
    env, monkeypatch, tmp_path, tracks
):
    library, clock = env
    for index in range(1000):
        sid = f"t{index:04}"
        (library.root / "deletion-journal" / f"{sid}.json").write_text(
            json.dumps(intent(sid)), encoding="utf-8"
        )
    with library._mutex:
        library._db.executemany(
            "INSERT INTO deleted_sessions VALUES(?,1,'DELETED_LOCAL')",
            [(f"t{i:04}",) for i in range(1000)],
        )
        library._db.commit()
    stamp(library)
    # This is pre-existing fixture history, not an unsupported live external delta.
    root = library.root
    library.close()
    library = Library(root)
    service = RecordingService(
        library, {t: AudioFormat(48000, 1) for t in ("mic", "system")[:tracks]}, session_id="rec"
    )
    original, reads, errors, replies = library._read_journal, [], [], []

    def counted():
        reads.append(1)
        return original()

    monkeypatch.setattr(library, "_read_journal", counted)
    quit_tick, corrupted = threading.Event(), threading.Event()

    def tick():
        assert corrupted.wait(10)
        while not quit_tick.is_set():
            try:
                # Explicit control observation still exercises the GS02 memo.
                assert consume(library, "read") == "HISTORY_UNAVAILABLE"
                replies.append(("DELETION_HISTORY_UNAVAILABLE",))
                # Healthy local capture lookup is independent of that global failure.
                library.chunks("rec")
            except BaseException as error:
                errors.append(error)
                return
            quit_tick.wait(0.05)

    thread = threading.Thread(target=tick, name="gs02-unsettled-tick")
    accepted = {t: b"" for t in service.formats}
    rejected = 0
    try:
        service.start()
        thread.start()
        began = time.monotonic()
        for index in range(200):
            if index == 25:
                fault(library, monkeypatch, "name")
                stamp(library, BASE + 1000)
                clock.now = BASE + 1000 + T - 1
                reads.clear()
                corrupted.set()
            for track in service.formats:
                block = recording_block(service, track, index)
                if service.submit(block):
                    accepted[track] += block.payload
                else:
                    rejected += 1
            remaining = began + (index + 1) * 0.01 - time.monotonic()
            if remaining > 0:
                time.sleep(remaining)
        quit_tick.set()
        thread.join(30)
        assert not thread.is_alive() and errors == []
        assert len(replies) >= 2 and set(replies) == {("DELETION_HISTORY_UNAVAILABLE",)}
        assert len(reads) == 1  # Later unsettled ticks enumerate names, never reparse bodies.
        repair(library)
        assert library.verify_deletion_history(fresh=True)["status"] == "READY"
        library.list_sessions()  # Explicit content repair before finalization.
        service.stop(timeout=30)
        chunks = library.chunks("rec")
        for track, payload in accepted.items():
            assert (
                b"".join(
                    (library.root / c.relative_path / "audio.pcm").read_bytes()
                    for c in chunks
                    if c.track_id == track
                )
                == payload
            )
        assert service._writer_error is None
        health = library.capture_health("rec")
        assert (
            sum(
                track["dropped_frames"]
                for epoch in health["epochs"]
                for track in epoch["tracks"].values()
            )
            == rejected * 480
        )
        measurement = {"tracks": tracks, "rejected": rejected, "body_reads": 1}
        (tmp_path / "measurement.json").write_text(json.dumps(measurement), encoding="utf-8")
        print(json.dumps(measurement))
    finally:
        corrupted.set()
        quit_tick.set()
        if thread.is_alive():
            thread.join(30)
        service.join_writer()
        library.close()
