"""Public Job transitions against hand-seeded, independent deletion facts."""

from __future__ import annotations

import json
import os
from dataclasses import replace
from itertools import product

import pytest

from recoryn.domain import StateConflict, ValidationError
from recoryn.jobs import JobStore
from recoryn.storage import Library
from recoryn.storage.deletion_history import HistoryClockSample

pytestmark = pytest.mark.integration


def allowed_result(call):
    """Independent success oracle: a closed domain rejection is still rejection."""
    result, rejected = None, None
    try:
        result = call()
    except (StateConflict, ValidationError) as error:
        rejected = (type(error).__name__, error.args)
    assert rejected is None, ("an explicitly allowed operation was rejected", rejected)
    return result


BASE = 100_000_000_000
STATES = (
    "valid",
    "db",
    "journal",
    "both",
    "tombstone",
    "db_newer",
    "journal_newer",
    "session_newer",
    "missing",
    "unprepared",
    "expired",
    "failed",
    "foreign",
    "repeat",
)
OPERATIONS = ("claim", "reader", "block", "resume", "ack", "complete", "publisher")
B_ROWS = list(product(STATES, OPERATIONS))


class Clock:
    age = 0

    def __call__(self):
        return HistoryClockSample(BASE + self.age, BASE + self.age)


def intent(sid, generation):
    return {
        "schema_version": 1,
        "session_id": sid,
        "generation": generation,
        "state": "DELETE_REQUESTED",
    }


def prepare_job(root, operation):
    with Library(root) as library, JobStore(library.db_path) as jobs:
        library.create_session("s")
        job = jobs.create("stt", "fixed", "job")
        jobs.bind_session(job.job_id, "s")
        attempt = None
        if operation in {"reader", "ack", "complete", "publisher"}:
            attempt = jobs.claim(job.job_id, "owner")
        elif operation == "resume":
            jobs.block_pending(job.job_id, "CONSENT", "CONSENT_REQUIRED", expected_version=0)
        jobs._db.execute("CREATE TABLE proof(value TEXT)")
    return attempt


@pytest.mark.parametrize("state,operation", B_ROWS, ids=[f"GS11-B-{i:03}" for i in range(1, 99)])
def test_each_public_transition_uses_current_exact_authority(tmp_path, state, operation):
    import sqlite3
    from contextlib import closing

    root = tmp_path / "library"
    attempt = prepare_job(root, operation)
    # Literal canonical fixtures, prepared with no live Library or product parser.
    with closing(sqlite3.connect(root / "library.sqlite")) as db:
        if state in {"db", "both", "tombstone", "db_newer", "journal_newer", "session_newer"}:
            generation = 2 if state in {"db_newer", "journal_newer", "session_newer"} else 1
            status = "DELETED_LOCAL" if state == "tombstone" else "DELETE_PENDING"
            db.execute("INSERT INTO deleted_sessions VALUES(?,?,?)", ("s", generation, status))
        if state == "session_newer":
            db.execute("UPDATE sessions SET generation=3 WHERE session_id='s'")
        if state == "missing":
            db.execute("DELETE FROM sessions WHERE session_id='s'")
        db.commit()
    if state in {"journal", "both", "tombstone", "db_newer", "journal_newer", "repeat"}:
        sid = "past" if state == "repeat" else "s"
        generation = 3 if state == "journal_newer" else 1
        (root / "deletion-journal" / f"{sid}.json").write_text(
            json.dumps(intent(sid, generation)), encoding="utf-8"
        )
    if state == "failed":
        (root / "deletion-journal" / "broken.json").write_text("{", encoding="utf-8")
    clock = Clock()
    with (
        Library(root, history_clock=clock, defer_history=state == "unprepared") as library,
        JobStore(library.db_path) as jobs,
    ):
        if state == "expired":
            clock.age = 30_000_000_000
        if state == "foreign":
            receipt = library._authority.receipt
            assert receipt is not None
            library._authority.receipt = replace(receipt, instance="foreign")
        if state == "repeat":
            assert library.verify_deletion_history()["status"] == "READY"
        before = jobs.get("job")
        calls = []

        def publisher(db):
            calls.append("called")
            db.execute("INSERT INTO proof VALUES('published')")
            return "proof"

        def act():
            if operation == "claim":
                return jobs.claim("job", "owner")
            if operation == "block":
                return jobs.block_pending(
                    "job", "CONSENT", "CONSENT_REQUIRED", expected_version=before.state_version
                )
            if operation == "resume":
                return jobs.resume("job", expected_version=before.state_version)
            assert attempt is not None
            if operation == "reader":
                return jobs.reader_started(attempt)
            if operation == "ack":
                return jobs.fail("job", attempt.attempt_id, attempt.fence, "AUTH_REQUIRED")
            if operation == "complete":
                return jobs.complete("job", attempt.attempt_id, attempt.fence, "proof")
            return jobs.complete_with("job", attempt.attempt_id, attempt.fence, publisher)

        # Hand oracle: only VALID/repeated unchanged records grant new work.
        allowed = state in {"valid", "repeat"}
        if allowed or operation == "ack":
            allowed_result(act)
            after = jobs.get("job")
            expected = {
                "claim": "RUNNING",
                "reader": "RUNNING",
                "block": "BLOCKED",
                "resume": "QUEUED",
                "complete": "SUCCEEDED",
                "publisher": "SUCCEEDED",
            }
            if operation == "ack":
                assert after.state.value == ("BLOCKED" if allowed else "FAILED")
                assert after.blocked_reason == ("AUTH" if allowed else None)
            else:
                assert after.state.value == expected[operation]
            if operation == "reader":
                assert jobs._db.execute("SELECT active FROM job_local_readers").fetchone()[0] == 1
        else:
            code = (
                "DELETION_HISTORY_UNAVAILABLE"
                if state in {"session_newer", "unprepared", "expired", "failed", "foreign"}
                else "JOB_SESSION_MISSING"
                if state == "missing"
                else "JOB_SESSION_DELETED"
            )
            with pytest.raises(StateConflict) as error:
                act()
            assert error.value.args == (code,)
            assert jobs.get("job") == before
        published = operation == "publisher" and allowed
        assert calls == (["called"] if published else [])
        assert [row[0] for row in jobs._db.execute("SELECT value FROM proof")] == (
            ["published"] if published else []
        )


FAULTS = (
    "normal",
    "json",
    "semantic",
    "missing",
    "added",
    "directory",
    "tmp",
    "link",
    "database",
    "future",
    "overflow",
    "io",
)
TIMES = ("first", "window", "expired", "delayed", "reopen")
OBSERVERS = ("claim", "page", "fresh")
A_ROWS = list(product(FAULTS, TIMES, OBSERVERS))


@pytest.mark.parametrize(
    "fault,timing,observer", A_ROWS, ids=[f"GS11-A-{i:03}" for i in range(1, 181)]
)
def test_full_audit_detection_and_the_explicit_unnotified_window(
    tmp_path, monkeypatch, fault, timing, observer
):
    import recoryn.storage.library as module

    root = tmp_path / "library"
    clock = Clock()
    library = Library(root, history_clock=clock)
    try:
        library.create_session("s")
        library.create_session("past")
        assert library.delete_session("past")["state"] == "DELETED_LOCAL"
        past = root / "deletion-journal/past.json"
        record = intent("past", 1) | {"note": "seed"}
        past.write_text(json.dumps(record), encoding="utf-8")
        library.close()
        library = Library(root, history_clock=clock, defer_history=timing == "first")
        if timing == "reopen":
            library.close()
        journal = root / "deletion-journal"
        directory_times = journal.stat()
        file_times = past.stat()
        if fault == "json":
            past.write_bytes(b"{malformed-canary")
        elif fault == "semantic":
            before = past.read_bytes()
            past.write_bytes(before.replace(b"seed", b"evil"))
            assert past.stat().st_size == len(before)
        elif fault == "missing":
            past.unlink()
        elif fault == "added":
            (journal / "external.json").write_text(
                json.dumps(intent("external", 1)), encoding="utf-8"
            )
        elif fault == "directory":
            past.unlink()
            journal.rmdir()
        elif fault == "tmp":
            (journal / ".tmp-pending").write_bytes(b"unfinished")
        elif fault == "link":
            outside = tmp_path / "linked.json"
            outside.write_bytes(past.read_bytes())
            past.unlink()
            os.link(outside, past)
        elif fault == "database":
            import sqlite3
            from contextlib import closing

            with closing(sqlite3.connect(root / "library.sqlite")) as db:
                db.execute("UPDATE deleted_sessions SET status='UNRECOGNIZED'")
                db.commit()
        elif fault == "future":
            past.write_text(json.dumps(record | {"schema_version": 99}), encoding="utf-8")
        elif fault == "io":
            original = module.read_json

            def denied(path, **kwargs):
                if path == past:
                    raise PermissionError("private reader canary")
                return original(path, **kwargs)

            monkeypatch.setattr(module, "read_json", denied)
        if journal.exists():
            if past.exists():
                os.utime(past, ns=(file_times.st_atime_ns, file_times.st_mtime_ns))
            os.utime(journal, ns=(directory_times.st_atime_ns, directory_times.st_mtime_ns))
        if timing == "reopen":
            library = Library(root, history_clock=clock)
        if fault == "overflow":
            library.invalidate_deletion_history()
        if timing == "expired":
            clock.age = 30_000_000_000
        if timing == "delayed":
            library.invalidate_deletion_history()
            read = library._read_journal

            def slow_audit():
                result = read()
                clock.age += 30_000_000_000
                return result

            monkeypatch.setattr(library, "_read_journal", slow_audit)
        if timing == "first":
            library.verify_deletion_history(fresh=True)

        # No prior digest can authenticate a valid record's earlier note, an
        # external valid intent, or the missing journal of a DB-only tombstone.
        # This cold-open limitation is explicit; known tombstones still deny.
        cold_valid = fault in {"normal", "semantic", "missing", "added", "overflow"}
        if observer == "fresh":
            result = library.verify_deletion_history(fresh=True)
            expected = timing != "delayed" and (
                cold_valid if timing in {"first", "reopen"} else fault in {"normal", "overflow"}
            )
            assert result == {
                "status": "READY" if expected else "UNAVAILABLE",
                "code": "" if expected else "DELETION_HISTORY_UNAVAILABLE",
            }
        else:
            expected = (timing == "window" and fault not in {"directory", "overflow"}) or (
                timing in {"first", "reopen"}
                and cold_valid
                and (fault != "overflow" or timing == "first")
            )
            if observer == "claim":
                with JobStore(library.db_path) as jobs:
                    job = jobs.create("stt", "fixed", "job")
                    jobs.bind_session(job.job_id, "s")
                    if expected:
                        assert jobs.claim("job", "owner").job_id == "job"
                    else:
                        with pytest.raises(StateConflict) as error:
                            jobs.claim("job", "owner")
                        assert error.value.args == ("DELETION_HISTORY_UNAVAILABLE",)
                        assert jobs.get("job") == job
            elif expected:
                assert [s.session_id for s in library.sessions_page()["sessions"]] == ["s"]
            else:
                with pytest.raises((ValidationError, OSError)):
                    library.sessions_page()
        try:
            assert library._writer_intent("past") is True
        except ValidationError:
            assert library.deletion_history_status()["status"] == "UNAVAILABLE"
    finally:
        library.close()


K_ROWS = list(product((PermissionError, OSError), ("get", "chunks", "create", "stop")))


@pytest.mark.parametrize("failure,operation", K_ROWS, ids=[f"GS11-K-{i:03}" for i in range(1, 9)])
def test_one_global_io_failure_never_freezes_healthy_local_capture(
    tmp_path, monkeypatch, failure, operation
):
    import recoryn.storage.library as module
    from recoryn.app.recording import RecordingService
    from recoryn.domain import AudioFormat, PCMBlock

    with Library(tmp_path / "library") as library:
        library.create_session("past")
        assert library.delete_session("past")["deleted"]
        fmt = AudioFormat(48000, 1)
        service = RecordingService(library, {"mic": fmt}, session_id="s")
        service.start()
        payload = b"\x19\x23" * 4
        assert service.submit(
            PCMBlock("s", "mic", service.epochs["mic"], 0, fmt, 4, payload, 0, 0, 0)
        )
        if operation != "stop":
            service.stop(timeout=60)
        original = module.read_json
        failures = []

        def once(path, **kwargs):
            if path.name == "past.json" and not failures:
                failures.append("one")
                raise failure("private path/body canary")
            return original(path, **kwargs)

        monkeypatch.setattr(module, "read_json", once)
        try:
            assert library.verify_deletion_history(fresh=True) == {
                "status": "UNAVAILABLE",
                "code": "DELETION_HISTORY_UNAVAILABLE",
            }
            if operation == "get":
                assert allowed_result(lambda: library.get_session("s")).state.value == "FINALIZED"
            elif operation == "chunks":
                assert len(allowed_result(lambda: library.chunks("s"))) == 1
            elif operation == "create":
                assert (
                    allowed_result(lambda: library.create_session("new")).state.value == "CREATED"
                )
            else:
                assert allowed_result(lambda: service.stop(timeout=60))["state"] == "FINALIZED"
                assert service._writer_error is None and not service.worker_alive
            # Local progress cannot mint permission for management as a side effect.
            assert library.deletion_history_status()["status"] == "UNAVAILABLE"
            descriptors = library.chunks("s")
            assert len(descriptors) == 1 and descriptors[0].frame_count == 4
            assert (
                library.root / descriptors[0].relative_path / "audio.pcm"
            ).read_bytes() == payload
            assert library._writer_intent("past") is True
            with pytest.raises(StateConflict, match="deletion intent"):
                library.get_session("past")
            assert failures == ["one"]
            assert library.verify_deletion_history()["status"] == "READY"
        finally:
            service.join_writer()


@pytest.mark.parametrize(
    "unavailable",
    ("expired", "invalidated", "io"),
    ids=["GS11-X-STOP-expired", "GS11-X-STOP-invalidated", "GS11-X-STOP-io"],
)
def test_local_stop_repairs_its_health_without_granting_management_permission(
    tmp_path, monkeypatch, unavailable
):
    from recoryn.app.recording import RecordingService
    from recoryn.domain import AudioFormat, PCMBlock

    clock = Clock()
    with Library(tmp_path / "library", history_clock=clock) as library:
        service = RecordingService(library, {"mic": AudioFormat(48000, 1)}, session_id="s")
        service.start()
        data = b"\x17\x22" * 4
        block = PCMBlock(
            "s", "mic", service.epochs["mic"], 0, AudioFormat(48000, 1), 4, data, 0, 0, 0
        )
        assert service.submit(block)
        service._defer_health()
        if unavailable == "expired":
            clock.age = 30_000_000_000
        elif unavailable == "invalidated":
            library.invalidate_deletion_history()
        else:

            def unreadable():
                raise PermissionError("private audit canary")

            monkeypatch.setattr(library, "_read_journal", unreadable)
            assert library.verify_deletion_history(fresh=True)["status"] == "UNAVAILABLE"
        calls = []
        recover, finalize = library.recover_session, library.finalize_session

        def repairing(sid, *, capture_control=None):
            calls.append(("recover", capture_control))
            return recover(sid, capture_control=capture_control)

        def finalizing(sid, *, capture_control=None):
            calls.append(("finalize", capture_control))
            return finalize(sid, capture_control=capture_control)

        monkeypatch.setattr(library, "recover_session", repairing)
        monkeypatch.setattr(library, "finalize_session", finalizing)
        try:
            assert service.stop(timeout=60)["state"] == "FINALIZED"
            assert [name for name, _ in calls] == ["recover", "finalize"]
            assert calls[0][1] is not None and calls[0][1] is calls[1][1]
            assert not service.worker_alive and service._writer_error is None
            descriptors = library.chunks("s")
            assert len(descriptors) == 1 and descriptors[0].frame_count == 4
            assert (library.root / descriptors[0].relative_path / "audio.pcm").read_bytes() == data
            assert library.deletion_history_status()["status"] == "UNAVAILABLE"
            with pytest.raises(ValidationError, match="DELETION_HISTORY_UNAVAILABLE"):
                recover("s")
            with pytest.raises(ValidationError, match="DELETION_HISTORY_UNAVAILABLE"):
                finalize("s")
        finally:
            service.join_writer()


def test_GS11_X_STOP_requires_real_source_release_even_after_both_workers_end(tmp_path):
    from recoryn.app.recording import RecordingService
    from recoryn.domain import AudioFormat

    with Library(tmp_path / "library") as library:
        service = RecordingService(
            library, {"mic": AudioFormat(48000, 1)}, session_id="s", source_managed=True
        )
        service.start()
        library.invalidate_deletion_history()
        try:
            with pytest.raises(StateConflict, match="SESSION_LIVE"):
                service.stop(timeout=60)
            assert not service.worker_alive
            assert library.get_session("s").state.value != "FINALIZED"
            service.sources_released()
            assert service.stop(timeout=60)["state"] == "FINALIZED"
            assert library.deletion_history_status()["status"] == "UNAVAILABLE"
        finally:
            service.join_writer()


def test_GS11_X_PUBLISH_receipt_must_still_be_current_at_the_protected_commit(tmp_path):
    clock = Clock()
    with (
        Library(tmp_path / "library", history_clock=clock) as library,
        JobStore(library.db_path) as jobs,
    ):
        library.create_session("s")
        job = jobs.create("summary", "fixed", "job")
        jobs.bind_session(job.job_id, "s")
        attempt = jobs.claim(job.job_id, "owner")
        before = jobs.get(job.job_id)
        jobs._db.execute("CREATE TABLE proof(value TEXT NOT NULL)")
        called = []

        def publisher(db):
            called.append("entered")
            db.execute("INSERT INTO proof VALUES('candidate')")
            clock.age = 30_000_000_000
            return "candidate"

        with pytest.raises(StateConflict, match="DELETION_HISTORY_UNAVAILABLE"):
            jobs.complete_with(job.job_id, attempt.attempt_id, attempt.fence, publisher)
        assert called == ["entered"]
        assert jobs.get(job.job_id) == before
        assert jobs._db.execute("SELECT count(*) FROM proof").fetchone()[0] == 0


def test_GS11_X_HOT_claim_never_starts_an_audit_and_control_reads_hold_no_root(
    tmp_path, monkeypatch
):
    with Library(tmp_path / "library") as library, JobStore(library.db_path) as jobs:
        library.create_session("s")
        job = jobs.create("stt", "fixed", "job")
        jobs.bind_session(job.job_id, "s")
        read = library._read_journal
        observations = []

        def observing():
            observations.append(library._mutex._is_owned())
            assert not observations[-1], "full canonical reads must be outside root"
            return read()

        monkeypatch.setattr(library, "_read_journal", observing)
        assert jobs.claim(job.job_id, "owner").job_id == job.job_id
        assert observations == [], "a current receipt needs only exact lookup"
        assert library.verify_deletion_history(fresh=True)["status"] == "READY"
        assert observations == [False]


@pytest.fixture(scope="module")
def history_application():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize(
    "preparation", ("initial", "changed"), ids=["GS11-X-AUDIT-initial", "GS11-X-AUDIT-changed"]
)
def test_denied_peeks_do_not_cancel_a_scan_of_the_same_metadata(tmp_path, monkeypatch, preparation):
    import threading

    with (
        Library(
            tmp_path / "library", history_clock=Clock(), defer_history=preparation == "initial"
        ) as library,
        JobStore(library.db_path) as jobs,
    ):
        library.create_session("s")
        before = jobs.create("stt", "fixed", "job")
        jobs.bind_session(before.job_id, "s")
        if preparation == "changed":
            journal = library.root / "deletion-journal"
            stamp = journal.stat()
            os.utime(journal, ns=(stamp.st_atime_ns, stamp.st_mtime_ns - 1))
        with Library.job_authority(library.db_path, "s") as state:
            assert state == "HISTORY_UNAVAILABLE"
        entered, release = threading.Event(), threading.Event()
        results, errors = [], []
        reading = library._read_journal

        def blocked():
            assert not library._mutex._is_owned()
            entered.set()
            assert release.wait(10)
            return reading()

        monkeypatch.setattr(library, "_read_journal", blocked)

        def scan():
            try:
                results.append(library.verify_deletion_history(fresh=True))
            except BaseException as error:
                errors.append(error)

        worker = threading.Thread(target=scan, name="gs11-audit")
        worker.start()
        try:
            assert entered.wait(5)
            with library._mutex:
                epoch = library._authority.epoch
            for _ in range(5):
                with pytest.raises(StateConflict, match="DELETION_HISTORY_UNAVAILABLE"):
                    jobs.claim(before.job_id, "owner")
                with pytest.raises(ValidationError, match="DELETION_HISTORY_UNAVAILABLE"):
                    library.sessions_page()
                assert jobs.get(before.job_id) == before
            with library._mutex:
                assert library._authority.epoch == epoch
            release.set()
            worker.join(10)
            assert not worker.is_alive() and not errors
            assert results == [{"status": "READY", "code": ""}]
            assert jobs.claim(before.job_id, "owner").attempt_no == 1
        finally:
            release.set()
            worker.join(10)
            assert not worker.is_alive()


@pytest.mark.parametrize(
    "history",
    ("initial", "io", "content"),
    ids=["GS11-X-UI-initial", "GS11-X-UI-io", "GS11-X-UI-content"],
)
def test_unverified_history_opens_an_honest_window_and_keeps_local_recording_available(
    tmp_path, monkeypatch, history_application, history
):
    import sys
    import threading
    import time

    import recoryn.security as security
    from recoryn.app.desktop import DesktopRecorder, TrackSelection
    from recoryn.app.device_policy import DevicePolicyStore
    from recoryn.domain import AudioFormat, PCMBlock
    from recoryn.ui.main import MainWindow

    class NoVault:
        def __getattr__(self, name):
            raise AssertionError(
                "startup and local recording must not touch the credential backend"
            )

    monkeypatch.setattr(security, "CredentialVault", NoVault)
    with Library(tmp_path / "library", defer_history=True) as library:
        if history == "content":
            (library.root / "deletion-journal/broken.json").write_bytes(b"{invalid")
        entered, release = threading.Event(), threading.Event()
        read = library._read_journal
        failure_notes = []
        failed = library._authority.failed

        def failed_audit(scan, *, io_error):
            failure_notes.append(repr(sys.exception()))
            return failed(scan, io_error=io_error)

        monkeypatch.setattr(library._authority, "failed", failed_audit)

        def blocked():
            assert not library._mutex._is_owned()
            entered.set()
            assert release.wait(10)
            if history == "io":
                raise PermissionError("private audit reader canary")
            return read()

        monkeypatch.setattr(library, "_read_journal", blocked)
        window = None
        service = None
        fmt = AudioFormat(48000, 1)
        payload = b"\x17\x22" * 4
        sources = []

        class SyntheticSource:
            running = False

            def start(self, sid, track, epoch, submit, on_health):
                self.running = True
                assert submit(PCMBlock(sid, track, epoch, 0, fmt, 4, payload, 0, 0, 0))
                return fmt

            def stop(self, timeout=5):
                self.running = False

        def factory(device_id, loopback):
            assert device_id == "synthetic" and loopback is False
            source = SyntheticSource()
            sources.append(source)
            return source

        recorder = DesktopRecorder(library, factory)
        try:
            window = MainWindow(
                library,
                recorder=recorder,
                policy_store=DevicePolicyStore(tmp_path / "preferences/device-policy.json"),
            )
            window.show()
            assert entered.wait(5), "the existing worker must actually start the audit"
            assert "확인 중" in window.history_status.text()
            assert library.deletion_history_status()["status"] == "UNAVAILABLE"
            with pytest.raises(ValidationError, match="DELETION_HISTORY_UNAVAILABLE"):
                library.list_sessions()
            sid = recorder.start((TrackSelection("mic", "synthetic", False, fmt),))
            service = recorder.recording
            assert service is not None
            assert recorder.stop()["state"] == "FINALIZED"
            assert len(sources) == 1 and not sources[0].running
            [descriptor] = library.chunks(sid)
            assert (library.root / descriptor.relative_path / "audio.pcm").read_bytes() == payload
            release.set()
            deadline = time.monotonic() + 10
            while window._history_tasks and time.monotonic() < deadline:
                history_application.processEvents()
                time.sleep(0.001)
            assert not window._history_tasks
            if history == "initial":
                assert "검증됨" in window.history_status.text(), failure_notes
            else:
                assert "확인 불가" in window.history_status.text()
                assert library.deletion_history_status()["status"] == "UNAVAILABLE"
        finally:
            release.set()
            if service is not None:
                service.join_writer()
            if window is not None:
                window.close()
                history_application.processEvents()


def test_GS11_X_POWER_window_revokes_before_suspend_and_rechecks_after_resume(
    tmp_path, monkeypatch, history_application
):
    import time

    import recoryn.security as security
    from recoryn.app.desktop import DesktopRecorder
    from recoryn.app.device_policy import DevicePolicyStore
    from recoryn.ui.main import MainWindow

    class NoVault:
        def __getattr__(self, name):
            raise AssertionError("power handling must not use credentials")

    def no_source(*args):
        pytest.fail("power tests never open a physical source")

    monkeypatch.setattr(security, "CredentialVault", NoVault)
    with Library(tmp_path / "library") as library:
        window = MainWindow(
            library,
            recorder=DesktopRecorder(library, no_source),
            policy_store=DevicePolicyStore(tmp_path / "preferences/device-policy.json"),
        )
        window.timer.stop()
        try:
            assert library.deletion_history_status()["status"] == "READY"
            window._power_event("suspend")
            assert window.history.suspended
            assert library.deletion_history_status()["status"] == "UNAVAILABLE"
            window._request_history(force=True)
            assert not window._history_tasks
            assert "보류" in window.history_status.text()
            window._power_event("resume")
            assert not window.history.suspended
            deadline = time.monotonic() + 10
            while (window._history_tasks or window.busy) and time.monotonic() < deadline:
                history_application.processEvents()
                time.sleep(0.001)
            assert not window._history_tasks and not window.busy
            assert library.deletion_history_status()["status"] == "READY"
            assert "검증됨" in window.history_status.text()
        finally:
            window.close()
            history_application.processEvents()
