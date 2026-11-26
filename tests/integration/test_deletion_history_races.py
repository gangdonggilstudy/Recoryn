"""Barrier schedules and byte conservation, independent of authority internals."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import threading
import time
from contextlib import closing, contextmanager
from itertools import product

import pytest

from recoryn.domain import ValidationError
from recoryn.storage import Library
from recoryn.storage.deletion_history import HistoryClockSample

pytestmark = pytest.mark.integration
C_ROWS = list(product(range(1, 9), ("delete", "scan", "repair"), (False, True)))


@pytest.mark.parametrize(
    "schedule,opponent,receipt", C_ROWS, ids=[f"GS11-C-{i:03}" for i in range(1, 49)]
)
def test_observation_and_action_barriers_have_literal_winners(
    tmp_path, monkeypatch, schedule, opponent, receipt
):
    root = tmp_path / "library"

    def clock():
        return HistoryClockSample(100_000_000_000, 100_000_000_000)

    library = Library(root, history_clock=clock)
    instances = [library]
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    outcomes, errors = [], []
    worker = None
    try:
        library.create_session("s")
        library.create_session("target")
        library.create_session("past")
        assert library.delete_session("past")["deleted"]
        assert library.verify_deletion_history()["status"] == "READY"
        if not receipt:
            library.invalidate_deletion_history()
        path = root / "deletion-journal/past.json"
        original = path.read_bytes()
        deleted = False

        def repair():
            path.write_bytes(original)
            assert library.verify_deletion_history(fresh=True)["status"] == "READY"

        def act():
            nonlocal deleted
            if opponent == "delete":
                try:
                    deleted = library.delete_session("target")["deleted"]
                except ValidationError as error:
                    assert error.args == ("DELETION_HISTORY_UNAVAILABLE",)
            elif opponent == "scan":
                library.verify_deletion_history()
            else:
                repair()

        if schedule == 1:
            act()
            assert library.verify_deletion_history(fresh=True)["status"] == "READY"
        elif schedule == 3:
            attempted = threading.Event()

            def contender():
                attempted.set()
                try:
                    with library._mutex:
                        pass  # the opponent's first control admission
                    act()
                except BaseException as error:
                    errors.append(error)
                finally:
                    finished.set()

            with Library.job_authority(library.db_path, "s") as authority:
                assert authority == ("VALID" if receipt else "HISTORY_UNAVAILABLE")
                worker = threading.Thread(target=contender, name="gs11-contender")
                worker.start()
                assert attempted.wait(5)
                assert not finished.wait(0.02), "the held authority lease must serialize admission"
            worker.join(10)
            assert not worker.is_alive() and not errors
            assert library.verify_deletion_history(fresh=True)["status"] == "READY"
        else:
            actual_read = library._read_journal

            def blocked_read():
                result, failure = None, None
                try:
                    result = actual_read()
                except BaseException as error:
                    failure = error
                if threading.current_thread().name == "gs11-old":
                    assert not library._mutex._is_owned()
                    entered.set()
                    assert release.wait(10)
                if failure is not None:
                    raise failure
                return result

            monkeypatch.setattr(library, "_read_journal", blocked_read)
            if schedule in {6, 7}:
                path.write_bytes(b"{corrupt")

            def old_scan():
                try:
                    outcomes.append(library.verify_deletion_history())
                except BaseException as error:
                    errors.append(error)
                finally:
                    finished.set()

            worker = threading.Thread(target=old_scan, name="gs11-old")
            worker.start()
            assert entered.wait(5)
            if schedule == 2:
                act()
            elif schedule == 4:
                act()
                library.invalidate_deletion_history()
            elif schedule == 5:
                act()
                assert library.verify_deletion_history(fresh=True)["status"] == "READY"
            elif schedule == 6:
                release.set()
                assert finished.wait(10)
                assert outcomes[0]["status"] == "UNAVAILABLE"
                act()
                repair()
            elif schedule == 7:
                repair()
                act()
                assert library.verify_deletion_history(fresh=True)["status"] == "READY"
            elif schedule == 8:
                old = library
                old.close()
                library = Library(root, history_clock=clock)
                instances.append(library)
                assert library.deletion_history_instance != old.deletion_history_instance
                act()
                assert library.verify_deletion_history(fresh=True)["status"] == "READY"
            release.set()
            worker.join(10)
            assert not worker.is_alive() and not errors
            assert len(outcomes) == 1
            if schedule == 4:
                assert library.deletion_history_status()["status"] == "UNAVAILABLE"
            elif schedule in {5, 6, 7, 8}:
                assert library.deletion_history_status()["status"] == "READY"
            else:
                # A still-valid scan may complete, but an explicit invalidation
                # by a fresh opponent may discard it. Neither forgets a deletion.
                assert outcomes[0]["status"] in {"READY", "UNAVAILABLE"}
        assert path.read_bytes() == original
        assert library._writer_intent("past") is True
        assert library._writer_intent("target") is deleted
        if deleted:
            with Library.job_authority(library.db_path, "target") as authority:
                assert authority != "VALID"
    finally:
        release.set()
        if worker is not None:
            worker.join(10)
            assert not worker.is_alive()
        for instance in reversed(instances):
            instance.close()


H_GLOBAL = list(product((0, 100, 1000, 10000), (1, 2), ("job", "page", "delete", "compact")))
H_ROWS = [
    pytest.param(h, tracks, op, id=f"GS11-H-{i:03}")
    for i, (h, tracks, op) in enumerate(H_GLOBAL, 1)
    if op in {"job", "delete"}
]


@pytest.fixture(scope="module")
def history_templates(tmp_path_factory):
    cached = {}

    def get(count):
        if count not in cached:
            root = tmp_path_factory.mktemp(f"gs11-history-{count}") / "library"
            with Library(root):
                pass
            with closing(sqlite3.connect(root / "library.sqlite")) as db:
                db.executemany(
                    "INSERT INTO deleted_sessions VALUES(?,1,'DELETED_LOCAL')",
                    [(f"past-{i:05}",) for i in range(count)],
                )
                db.execute("DELETE FROM storage_pending_deletions")
                db.commit()
            for i in range(count):
                sid = f"past-{i:05}"
                (root / f"deletion-journal/{sid}.json").write_text(
                    json.dumps(
                        {
                            "schema_version": 1,
                            "session_id": sid,
                            "generation": 1,
                            "state": "DELETE_REQUESTED",
                        }
                    ),
                    encoding="utf-8",
                )
            old = time.time_ns() - 10_000_000_000
            os.utime(root / "deletion-journal", ns=(old, old))
            cached[count] = root
        return cached[count]

    return get


@pytest.fixture(scope="module")
def scale_call_oracle():
    return {}


@pytest.fixture(scope="module")
def clone_file():
    """Physical copies, never hard links; avoid Python's per-file stream setup."""
    if sys.platform != "win32":
        return shutil.copyfile
    import ctypes
    from ctypes import wintypes

    copy = ctypes.WinDLL("kernel32", use_last_error=True).CopyFileW
    copy.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.BOOL]
    copy.restype = wintypes.BOOL

    def independent(source, target):
        if not copy(str(source), str(target), True):
            raise ctypes.WinError(ctypes.get_last_error())
        return target

    return independent


@contextmanager
def hot_calls(library, jobs, monkeypatch):
    """Count the manager's actual OS/SQL calls; recording threads are separate."""
    owner = threading.get_ident()
    counts = {
        name: 0
        for name in (
            "open",
            "stat",
            "lstat",
            "fstat",
            "scandir",
            "names",
            "sql",
            "body",
            "full_sql",
        )
    }
    active = True

    def tick(name):
        if active and threading.get_ident() == owner:
            counts[name] += 1

    with monkeypatch.context() as patch:
        for name in ("open", "stat", "lstat", "fstat"):
            original = getattr(os, name)

            def observed(*args, _name=name, _original=original, **kwargs):
                tick(_name)
                if _name == "open" and threading.get_ident() == owner and active:
                    path = os.fspath(args[0])
                    if isinstance(path, str) and "deletion-journal" in path:
                        tick("body")
                return _original(*args, **kwargs)

            patch.setattr(os, name, observed)
        scan = os.scandir

        class Entries:
            def __init__(self, entries):
                self.entries = entries

            def __enter__(self):
                self.entries.__enter__()
                return self

            def __exit__(self, *args):
                return self.entries.__exit__(*args)

            def __iter__(self):
                return self

            def __next__(self):
                result = next(self.entries)
                tick("names")
                return result

        def scan_counted(*args, **kwargs):
            tick("scandir")
            return Entries(scan(*args, **kwargs))

        patch.setattr(os, "scandir", scan_counted)

        def sql(statement):
            tick("sql")
            if active and threading.get_ident() == owner:
                normalized = " ".join(statement.lower().split())
                if "from deleted_sessions" in normalized and "where" not in normalized:
                    tick("full_sql")

        with library._mutex:
            library._db.set_trace_callback(sql)
        jobs._db.set_trace_callback(sql)
        try:
            yield counts
        finally:
            active = False
            with library._mutex:
                library._db.set_trace_callback(None)
            jobs._db.set_trace_callback(None)


@pytest.mark.parametrize("histories,tracks,operation", H_ROWS)
def test_history_scale_management_preserves_every_accepted_recording_block(
    tmp_path,
    history_templates,
    histories,
    tracks,
    operation,
    scale_call_oracle,
    clone_file,
    monkeypatch,
):
    from recoryn.app.recording import RecordingService
    from recoryn.domain import AudioFormat, PCMBlock
    from recoryn.jobs import JobStore

    root = tmp_path / "library"
    template = history_templates(histories)
    cloning = time.perf_counter()
    # Independent files (nlink=1), same bytes. Per-file timestamps/ACL copying
    # adds no authority evidence; only the directory stamp is an observation hint.
    shutil.copytree(template, root, copy_function=clone_file)
    clone_seconds = time.perf_counter() - cloning

    def clock():
        return HistoryClockSample(100_000_000_000, 100_000_000_000)

    opening = time.perf_counter()
    with Library(root, history_clock=clock) as library, JobStore(library.db_path) as jobs:
        open_seconds = time.perf_counter() - opening
        assert library.deletion_history_status()["status"] == "READY"
        assert (
            library._db.execute("SELECT count(*) FROM deleted_sessions").fetchone()[0] == histories
        )
        library.create_session("management")
        if operation == "delete":
            for i in range(3):
                library.create_session(f"discard-{i}")
        fmt = AudioFormat(48000, 1)
        names = ("mic", "system")[:tracks]
        service = RecordingService(library, {track: fmt for track in names}, session_id="recording")
        service.start()
        epochs = service.epochs
        offered = {track: [] for track in names}
        accepted = {track: [] for track in names}
        errors, durations = [], []
        go = threading.Event()

        def produce():
            assert go.wait(5)
            try:
                for i in range(24):
                    for track in names:
                        payload = bytes((11 if track == "mic" else 29, i)) * 480
                        block = PCMBlock(
                            "recording",
                            track,
                            epochs[track],
                            i,
                            fmt,
                            480,
                            payload,
                            i * 10_000_000,
                            i * 10_000_000,
                            i * 480,
                        )
                        offered[track].append(payload)
                        if service.submit(block):
                            accepted[track].append(payload)
                    time.sleep(0.001)
            except BaseException as error:
                errors.append(error)

        worker = threading.Thread(target=produce, name="gs11-capture")
        worker.start()
        try:
            go.set()
            with hot_calls(library, jobs, monkeypatch) as calls:
                for i in range(3):
                    started = time.perf_counter()
                    if operation == "job":
                        job = jobs.create("stt", f"fixed-{i}")
                        jobs.bind_session(job.job_id, "management")
                        attempt = jobs.claim(job.job_id, "owner")
                        jobs.fail(job.job_id, attempt.attempt_id, attempt.fence, "AUTH_REQUIRED")
                    else:
                        assert library.delete_session(f"discard-{i}")["deleted"]
                    durations.append(time.perf_counter() - started)
            assert calls["scandir"] == calls["names"] == calls["full_sql"] == 0
            assert calls["body"] == (0 if operation == "job" else 3)
            if histories in {1000, 10000}:
                key = (tracks, operation)
                if key in scale_call_oracle:
                    assert calls == scale_call_oracle[key]
                else:
                    scale_call_oracle[key] = dict(calls)
            worker.join(10)
            assert not worker.is_alive() and not errors
            memory = service.health_snapshot()
            assert (
                service._writer_error is None
                and memory["accepting"]
                and not memory["storage_failed"]
            )
            stopping = time.perf_counter()
            result = service.stop(timeout=60)
            stop_seconds = time.perf_counter() - stopping
            assert result["state"] == "FINALIZED"
            descriptors = library.chunks("recording")
            measurement = {"histories": histories, "tracks": tracks, "operation": operation}
            measurement["hot_calls"] = calls
            measurement.update(
                clone_seconds=clone_seconds, open_seconds=open_seconds, stop_seconds=stop_seconds
            )
            for track in names:
                expected = b"".join(accepted[track])
                retained = [item for item in descriptors if item.track_id == track]
                assert sum(item.frame_count for item in retained) == len(accepted[track]) * 480
                assert (
                    b"".join(
                        (root / item.relative_path / "audio.pcm").read_bytes() for item in retained
                    )
                    == expected
                )
                dropped = (24 - len(accepted[track])) * 480
                assert memory["tracks"][track] == {
                    "accepted_frames": len(accepted[track]) * 480,
                    "dropped_frames": dropped,
                }
                measurement[track + "_rejected"] = dropped // 480
            measurement["management_max_seconds"] = max(durations)
            print(json.dumps(measurement, sort_keys=True))
        finally:
            go.set()
            worker.join(10)
            service.join_writer()


def test_GS11_X_STAGE_fences_media_before_the_first_durable_intent_byte(tmp_path, monkeypatch):
    """A staged fsync may wait, but its reserved ID may accept no later media."""
    from recoryn.domain import AudioFormat, PCMBlock, StateConflict
    from recoryn.storage import ChunkWriter

    with Library(tmp_path / "library") as library:
        library.create_session("s")
        block = PCMBlock("s", "mic", "epoch", 0, AudioFormat(48000, 1), 4, b"\x01\x02" * 4, 0, 0, 0)
        writer = ChunkWriter(library.root, block, "candidate")
        writer.append(block)
        following = PCMBlock(
            "s", "mic", "epoch", 1, AudioFormat(48000, 1), 4, b"\x03\x04" * 4, 1000, 1000, 4
        )
        entered, release = threading.Event(), threading.Event()
        original = Library._prepare_intent
        results, errors = [], []

        def staged(self, path, temporary, value):
            if path.name.startswith(".deletion-stage-"):
                entered.set()
                assert release.wait(10)
            return original(self, path, temporary, value)

        monkeypatch.setattr(Library, "_prepare_intent", staged)

        def deleting():
            try:
                results.append(library.delete_session("s"))
            except BaseException as error:
                errors.append(error)

        worker = threading.Thread(target=deleting, name="gs11-stage")
        worker.start()
        try:
            assert entered.wait(5)
            assert not (library.root / "deletion-journal/s.json").exists()
            with library._mutex:
                assert (
                    library._db.execute("SELECT count(*) FROM deleted_sessions").fetchone()[0] == 0
                )
            before = (writer.staging_path / "audio.pcm").read_bytes()
            with pytest.raises(StateConflict, match="Writer session has a deletion intent"):
                writer.append(following)
            assert (writer.staging_path / "audio.pcm").read_bytes() == before
            release.set()
            worker.join(10)
            assert not worker.is_alive() and not errors
            assert len(results) == 1 and results[0]["state"] == "DELETE_PENDING"
            writer.abort()
            assert library.delete_session("s")["state"] == "DELETED_LOCAL"
        finally:
            release.set()
            worker.join(10)
            assert not worker.is_alive()
            writer.abort()


@pytest.mark.parametrize("protocol", ("stage", "atomic", "legacy"))
@pytest.mark.parametrize("body_kind", ("valid", "partial", "future"))
@pytest.mark.parametrize("when", ("initial", "fresh"))
def test_GS11_X_ORPHAN_stays_in_place_and_never_becomes_permission(
    tmp_path, protocol, body_kind, when
):
    """미완료 파일은 원위치 보존, 식별한 대상만 부정 fence, 무관 capture는 독립."""
    from recoryn.app.recording import RecordingService
    from recoryn.domain import AudioFormat, PCMBlock, StateConflict
    from recoryn.storage import ChunkWriter

    root = tmp_path / "library"
    with Library(root) as seed:
        seed.create_session("s")
    nonce = "a" * 32
    name = f".tmp-{nonce}" if protocol == "legacy" else f".deletion-{protocol}-{nonce}.json"
    payload = (
        b'{"schema_version":1,"session_id":"s","generation":1,"state":"DELETE_REQUESTED"}'
        if body_kind == "valid"
        else b'{"session_id":'
        if body_kind == "partial"
        else b'{"schema_version":999}'
    )
    if when == "initial":
        (root / name).write_bytes(payload)
    with Library(root) as library:
        if when == "fresh":
            (root / name).write_bytes(payload)
        assert library.verify_deletion_history(fresh=True) == {
            "status": "UNAVAILABLE",
            "code": "DELETION_HISTORY_UNAVAILABLE",
        }
        assert (root / name).exists()
        assert (root / name).read_bytes() == payload
        assert not (root / "deletion-journal/s.json").exists()
        fmt = AudioFormat(48000, 1)
        if body_kind == "valid":
            block = PCMBlock("s", "mic", "e", 0, fmt, 4, b"\1\0" * 4, 0, 0, 0)
            writer = ChunkWriter(root, block, "orphan-fence")
            try:
                with pytest.raises(StateConflict, match="Writer session has a deletion intent"):
                    writer.append(block)
                assert not writer.path.exists() and not writer.staging_path.exists()
            finally:
                writer.abort()
        service = RecordingService(library, {"mic": fmt}, session_id="unrelated")
        service.start()
        audio = b"\2\3" * 4
        try:
            assert service.submit(
                PCMBlock("unrelated", "mic", service.epochs["mic"], 0, fmt, 4, audio, 0, 0, 0)
            )
            assert service.stop(timeout=60)["state"] == "FINALIZED"
            assert service._writer_error is None
            descriptors = library.chunks("unrelated")
            assert sum(d.frame_count for d in descriptors) == 4
            assert (root / descriptors[0].relative_path / "audio.pcm").read_bytes() == audio
        finally:
            service.join_writer()
        assert library.deletion_history_status()["status"] == "UNAVAILABLE"
        assert library.verify_deletion_history(fresh=True)["status"] == "UNAVAILABLE"
        assert (root / name).read_bytes() == payload
        assert sorted(
            p.name for p in root.iterdir() if p.name.startswith((".deletion-", ".tmp-"))
        ) == [name]
        with library._mutex:
            assert library._db.execute("SELECT count(*) FROM deleted_sessions").fetchone()[0] == 0


@pytest.mark.parametrize(
    "fault",
    (
        "none",
        "instance",
        "nonce",
        "identity",
        "unproven",
        "unregistered",
        "lifetime",
        "late_lifetime",
    ),
)
def test_GS11_X_OWNED_staging_exception_requires_the_exact_live_registration(
    tmp_path, monkeypatch, fault
):
    entered, release = threading.Event(), threading.Event()
    errors, results = [], []
    with Library(tmp_path / "library") as library:
        library.create_session("s")
        original = os.replace

        def waiting(source, target, *args, **kwargs):
            if ".deletion-atomic-" in str(source):
                entered.set()
                assert release.wait(15)
            return original(source, target, *args, **kwargs)

        monkeypatch.setattr(os, "replace", waiting)

        def deleting():
            try:
                results.append(library.delete_session("s"))
            except BaseException as error:
                errors.append(error)

        worker = threading.Thread(target=deleting)
        worker.start()
        try:
            assert entered.wait(5)
            path = next(p for p in library.root.iterdir() if p.name.startswith(".deletion-atomic-"))
            before = path.read_bytes()
            with library._mutex:
                saved = library._staged_files[path]
                instance, nonce, token, identity = saved
                if fault == "unregistered":
                    del library._staged_files[path]
                elif fault == "lifetime":
                    library._staged_lifetimes.remove(token)
                elif fault not in {"none", "late_lifetime"}:
                    library._staged_files[path] = (
                        instance + "foreign" if fault == "instance" else instance,
                        "b" * 32 if fault == "nonce" else nonce,
                        token,
                        (0, 0)
                        if fault == "identity"
                        else None
                        if fault == "unproven"
                        else identity,
                    )
                library._stage_epoch += 1
            if fault == "late_lifetime":
                inspected, publish = threading.Event(), threading.Event()
                calls, observed, observer_errors = [0], [], []
                inspect = library._inspect_staged_intents

                def pause_after_observation():
                    answer = inspect()
                    calls[0] += 1
                    if calls[0] == 2:
                        inspected.set()
                        assert publish.wait(10)
                    return answer

                monkeypatch.setattr(library, "_inspect_staged_intents", pause_after_observation)

                def verify():
                    try:
                        observed.append(library.verify_deletion_history(fresh=True))
                    except BaseException as error:
                        observer_errors.append(error)

                observer = threading.Thread(target=verify)
                observer.start()
                try:
                    assert inspected.wait(5)
                    root_stamp = library._stage_root_stamp()
                    with library._mutex:
                        library._staged_lifetimes.remove(token)
                        library._stage_epoch += 1
                    assert root_stamp == library._stage_root_stamp()
                    publish.set()
                    observer.join(10)
                    assert not observer.is_alive() and not observer_errors
                    assert observed == [
                        {"status": "UNAVAILABLE", "code": "DELETION_HISTORY_UNAVAILABLE"}
                    ]
                finally:
                    publish.set()
                    observer.join(10)
                    assert not observer.is_alive()
            else:
                assert library.verify_deletion_history(fresh=True)["status"] == (
                    "READY" if fault == "none" else "UNAVAILABLE"
                )
            assert path.read_bytes() == before
            with library._mutex:
                library._staged_files[path] = saved
                library._staged_lifetimes.add(token)
                library._stage_epoch += 1
            if fault == "unproven":
                assert library.verify_deletion_history()["status"] == "READY"
            assert library.verify_deletion_history(fresh=True)["status"] == "READY"
            release.set()
            worker.join(15)
            assert not worker.is_alive() and not errors
            assert len(results) == 1 and results[0]["state"] == "DELETED_LOCAL"
        finally:
            release.set()
            worker.join(15)
            assert not worker.is_alive()


def test_GS11_X_STAGE_RACE_a_new_orphan_after_the_final_scan_cannot_publish(tmp_path, monkeypatch):
    import os

    with Library(tmp_path / "library") as library:
        library.create_session("s")
        original = library._inspect_staged_intents
        reached, proceed = threading.Event(), threading.Event()
        count, results, errors = [0], [], []

        def paused():
            answer = original()
            count[0] += 1
            if count[0] == 2:
                reached.set()
                assert proceed.wait(10)
            return answer

        monkeypatch.setattr(library, "_inspect_staged_intents", paused)

        def verifying():
            try:
                results.append(library.verify_deletion_history(fresh=True))
            except BaseException as error:
                errors.append(error)

        worker = threading.Thread(target=verifying)
        worker.start()
        try:
            assert reached.wait(5)
            leftover = library.root / (".deletion-stage-" + "c" * 32 + ".json")
            payload = (
                b'{"schema_version":1,"session_id":"s","generation":1,"state":"DELETE_REQUESTED"}'
            )
            before = library.root.stat()
            leftover.write_bytes(payload)
            os.utime(library.root, ns=(before.st_atime_ns, before.st_mtime_ns + 10**9))
            proceed.set()
            worker.join(10)
            assert not worker.is_alive() and not errors
            assert results == [{"status": "UNAVAILABLE", "code": "DELETION_HISTORY_UNAVAILABLE"}]
            assert leftover.read_bytes() == payload
            assert library.deletion_history_status()["status"] == "UNAVAILABLE"
        finally:
            proceed.set()
            worker.join(10)
            assert not worker.is_alive()


@pytest.mark.parametrize(
    "write_first", [True, False], ids=["GS11-X-P11-write-first", "GS11-X-P11-delete-first"]
)
def test_GS11_X_P11_completion_requires_the_observed_writer_and_media_state(tmp_path, write_first):
    from recoryn.domain import AudioFormat, PCMBlock, StateConflict
    from recoryn.storage import ChunkWriter
    from recoryn.storage.chunks import has_active_writer

    with Library(tmp_path / "library") as library:
        library.create_session("s")
        block = PCMBlock("s", "mic", "e", 0, AudioFormat(48000, 1), 4, b"\5\0" * 4, 0, 0, 0)
        writer = ChunkWriter(library.root, block, "ordered")
        try:
            if write_first:
                writer.append(block)
                assert has_active_writer(library.root, "s")
                before = (writer.staging_path / "audio.pcm").read_bytes()
                result = library.delete_session("s")
                assert result["state"] == "DELETE_PENDING" and result["deleted"] is False
                assert has_active_writer(library.root, "s")
                assert (writer.staging_path / "audio.pcm").read_bytes() == before
            else:
                result = library.delete_session("s")
                assert result["state"] == "DELETED_LOCAL" and result["deleted"] is True
                with pytest.raises(StateConflict, match="Writer session has a deletion intent"):
                    writer.append(block)
                assert not has_active_writer(library.root, "s")
                assert not writer.path.exists() and not writer.staging_path.exists()
            with pytest.raises(StateConflict):
                writer.seal()
        finally:
            writer.abort()
        assert library.delete_session("s")["state"] == "DELETED_LOCAL"
        assert not writer.path.exists() and not writer.staging_path.exists()


@pytest.mark.parametrize(
    "protocol,variant",
    [
        ("stage", "upper_name"),
        ("stage", "upper_nonce"),
        ("atomic", "upper_name"),
        ("atomic", "upper_nonce"),
        ("legacy", "upper_name"),
        ("legacy", "upper_nonce"),
    ],
    ids=[
        "GS11-X-CASE-stage-upper_name",
        "GS11-X-CASE-stage-upper_nonce",
        "GS11-X-CASE-atomic-upper_name",
        "GS11-X-CASE-atomic-upper_nonce",
        "GS11-X-CASE-legacy-upper_name",
        "GS11-X-CASE-legacy-upper_nonce",
    ],
)
def test_GS11_X_CASE_ascii_aliases_preserve_the_same_incomplete_intent(tmp_path, protocol, variant):
    from recoryn.app.recording import RecordingService
    from recoryn.domain import AudioFormat, PCMBlock, StateConflict

    root = tmp_path / "library"
    with Library(root) as seed:
        seed.create_session("s")
    nonce = "abcdef0123456789abcdef0123456789"
    prefix, suffix = (".tmp-", "") if protocol == "legacy" else (f".deletion-{protocol}-", ".json")
    canonical_name = prefix + nonce + suffix
    filename = (
        canonical_name.upper() if variant == "upper_name" else prefix + nonce.upper() + suffix
    )
    path = root / filename
    before = b'{"schema_version":1,"session_id":"s","generation":1,"state":"DELETE_REQUESTED"}'
    path.write_bytes(before)
    if os.name == "nt":
        assert os.path.samefile(path, root / canonical_name)
    with Library(root) as library:
        assert library.deletion_history_status() == {
            "status": "UNAVAILABLE",
            "code": "DELETION_HISTORY_UNAVAILABLE",
        }
        with pytest.raises(StateConflict, match="^Session has a deletion intent$"):
            library.get_session("s")
        service = RecordingService(library, {"mic": AudioFormat(48000, 1)}, session_id="other")
        try:
            service.start()
            block = PCMBlock(
                "other",
                "mic",
                service.epochs["mic"],
                0,
                AudioFormat(48000, 1),
                4,
                b"\x01\0" * 4,
                0,
                0,
                0,
            )
            assert service.submit(block)
            result = service.stop(timeout=10)
            assert result["state"] == "FINALIZED" and result["frame_count"] == 4
            descriptors = library.chunks("other")
            assert (
                b"".join((root / d.relative_path / "audio.pcm").read_bytes() for d in descriptors)
                == block.payload
            )
        finally:
            service.join_writer()
        with Library.job_authority(library.db_path, "other") as authority:
            assert authority == "HISTORY_UNAVAILABLE"
        assert path.read_bytes() == before and list((root / "deletion-journal").iterdir()) == []
        with library._mutex:
            assert library._db.execute("SELECT count(*) FROM deleted_sessions").fetchone()[0] == 0
