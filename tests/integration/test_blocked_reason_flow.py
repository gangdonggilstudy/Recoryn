"""G07 failure ACK order, typed wire boundaries and explicit same-plan admission."""

from __future__ import annotations

import runpy
import threading
from itertools import product
from pathlib import Path

import pytest

from recoryn.app.ai import AIService
from recoryn.domain import StateConflict
from recoryn.jobs import JobStore
from recoryn.jobs.runner import BoundedRunner
from recoryn.providers import ExecutionContext, ProviderConfig, ProviderError
from recoryn.providers._common import Run
from recoryn.security import SecurityError

ORACLE = runpy.run_path(str(Path(__file__).parents[1] / "unit/test_blocked_reasons.py"))["ORACLE"]
WIRE = (
    ORACLE["CONSENT"]
    + ORACLE["BUDGET"]
    + "COST_REQUEST_INVALID COST_AMOUNT_OVERFLOW INVALID_CONSENT_CONTEXT INVALID_CONSENT_SCOPE INVALID_CONSENT_SCOPES INVALID_CONSENT_BINDING INVALID_SESSION_GENERATION SESSION_REVOKED LOCAL_EXECUTION_UNVERIFIED".split()
)
W = list(product(WIRE, ("factory", "gateway"), (False, True)))


@pytest.mark.parametrize(
    "ending,tracks",
    [("stop", 1), ("pause", 1), ("stop", 2), ("pause", 2)],
    ids=[f"G07-FIX1-PCM-{i:02}" for i in range(1, 5)],
)
def test_inflight_and_peer_pcm_are_preserved_until_the_epoch_closes(tmp_path, ending, tracks):
    from recoryn.app.desktop import DesktopRecorder, TrackSelection
    from recoryn.app.status import capture_status
    from recoryn.domain import AudioFormat, PCMBlock
    from recoryn.storage import Library

    fmt = AudioFormat(48_000, 1)
    sources = {}
    offered = {}
    decisions = []

    class Source:
        running = False

        def start(self, session, track, epoch, submit, health):
            self.identity, self.submit = (session, track, epoch), submit
            self.track, self.sequence, self.running = track, 0, True
            sources[track] = self
            offered[track] = []
            return fmt

        def packet(self):
            # Track/sequence-tagged bytes make missing/reordered PCM visible.
            payload = bytes((11 if self.track == "mic" else 29, self.sequence)) * 480
            offered[self.track].append(payload)
            result = self.submit(PCMBlock(*self.identity, self.sequence, fmt, 480, payload, 0, 0))
            self.sequence += 1
            decisions.append(result)

        def stop(self, timeout=5):
            if self.running and self.track == "mic":
                self.packet()  # Capture passed its stop check before this stop request.
                if tracks == 2:
                    for _ in range(5):
                        sources["system"].packet()  # The peer has not received stop yet.
            self.running = False

    with Library(tmp_path / "library") as library:
        controller = DesktopRecorder(library, lambda *_: Source())
        session = controller.start(
            tuple(
                TrackSelection(track, "fake", track == "system", fmt)
                for track in (["mic"] if tracks == 1 else ["mic", "system"])
            )
        )
        try:
            for source in sources.values():
                for _ in range(2 if tracks == 1 else 1):
                    source.packet()
            if ending == "pause":
                controller.pause()
            else:
                controller.stop()
            expected_frames = {"mic": 1440} if tracks == 1 else {"mic": 960, "system": 2880}
            assert decisions and all(decisions)
            chunks = library.chunks(session)
            for track, frames in expected_frames.items():
                retained = [chunk for chunk in chunks if chunk.track_id == track]
                assert sum(chunk.frame_count for chunk in retained) == frames
                assert b"".join(
                    (library.root / chunk.relative_path / "audio.pcm").read_bytes()
                    for chunk in retained
                ) == b"".join(offered[track])
                assert controller.recording.health_snapshot()["tracks"][track] == {
                    "accepted_frames": frames,
                    "dropped_frames": 0,
                }
            assert "REC" not in capture_status(controller.capture_progress())
        finally:
            controller.close()


@pytest.mark.parametrize(
    "shape",
    ["absent", "non_bool", "getter_error", "local_arguments", "explicit_false", "explicit_true"],
    ids=[f"G07-FIX1-WIRE-{i:02}" for i in range(1, 7)],
)
def test_gateway_requires_an_explicit_boolean_known_outcome(shape):
    class Error(Exception):
        code = "CONSENT_REVOKED"

    class Broken(Error):
        @property
        def outcome_known(self):
            raise RuntimeError("SECRET")

    error = Broken() if shape == "getter_error" else Error("SECRET")
    if shape == "non_bool":
        error.outcome_known = 1
    elif shape.startswith("explicit_"):
        error.outcome_known = shape == "explicit_true"
    elif shape == "local_arguments":
        error = StateConflict("CONSENT_REVOKED")

    class Gateway:
        def request(self, *args, **kwargs):
            raise error

    with pytest.raises(ProviderError) as caught:
        Run(ProviderConfig("openai", "fake"), ExecutionContext()).request(
            Gateway(), "https://example.invalid/api", "audio", b"fake", operation="stt"
        )
    assert caught.value.outcome_known is (shape == "explicit_true")
    assert caught.value.code == (
        "REMOTE_OUTCOME_UNKNOWN" if shape == "local_arguments" else "CONSENT_REVOKED"
    )
    with JobStore(Path(":memory:")) as store:
        job = store.create("transcription", "key")
        attempt = store.claim(job.job_id, "fake")
        result = store.fail(
            job.job_id, attempt.attempt_id, attempt.fence, *BoundedRunner._failure(caught.value)
        )
        assert result.state.value == "BLOCKED"
        assert result.blocked_reason == (
            "CONSENT" if shape == "explicit_true" else "REMOTE_UNKNOWN"
        )


@pytest.mark.parametrize(
    "boundary,persistent",
    list(product(("claim", "reader"), (False, True))),
    ids=[f"G07-FIX1-HISTORY-{i:02}" for i in range(1, 5)],
)
def test_history_refusal_releases_admission_cache_and_remains_fail_closed(
    tmp_path, monkeypatch, boundary, persistent
):
    import time
    from contextlib import contextmanager

    from recoryn.app.status import admission_status
    from recoryn.content import ContentStore
    from recoryn.storage import Library
    from tests.e2e.test_ai_workflow import FakeSTT, recording

    class Provider(FakeSTT):
        calls = 0

        def transcribe(self, request, context=None):
            self.calls += 1
            return super().transcribe(request, context)

    with Library(tmp_path / "library") as library, ContentStore(library) as content:
        session, provider = recording(library), Provider()
        media = {
            chunk.relative_path: (library.root / chunk.relative_path / "audio.pcm").read_bytes()
            for chunk in library.chunks(session)
        }
        service = AIService(library, content)
        calls, closed = 0, False
        origin = Library.job_authority
        released = threading.Event()
        actual_release = service._admission_refused

        def on_refused(job_id):
            assert not service.runner._condition._is_owned()
            assert not library._mutex._is_owned()
            actual_release(job_id)
            released.set()

        service.runner.on_admission_refused = on_refused

        @contextmanager
        def authority(db_path, sid):
            nonlocal calls
            calls += 1
            if not closed and (
                calls == (1 if boundary == "claim" else 2)
                or persistent
                and calls >= (1 if boundary == "claim" else 2)
            ):
                yield "HISTORY_UNAVAILABLE"
            else:
                with origin(db_path, sid) as state:
                    yield state

        monkeypatch.setattr(Library, "job_authority", staticmethod(authority))

        def settled():
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                snap = service.runner.snapshot()
                if not snap["active"] and not snap["pending"]:
                    return
                time.sleep(0.001)
            pytest.fail("fake admission did not settle")

        try:
            job_id = service.transcribe(session, provider, config_key="same")
            assert released.wait(10)
            settled()
            before = service.jobs.get(job_id)
            assert provider.calls == 0 and job_id not in service._admitted
            assert (before.state.value, before.attempt_count) == (
                ("QUEUED", 0) if boundary == "claim" else ("FAILED", 1)
            )
            assert service.runner.admission_error(job_id) == "DELETION_HISTORY_UNAVAILABLE"
            status = admission_status(
                service.runner.admission_error(job_id), failed=boundary == "reader"
            )
            assert "삭제 이력 확인 불가" in status.text and not status.can_continue
            pending_id = job_id if boundary == "claim" else None
            if persistent:
                again = service.transcribe(session, provider, config_key="same")
                settled()
                assert (again == job_id) is (boundary == "claim")
                assert provider.calls == 0
                assert service.jobs.get(again).state.value == "QUEUED"
                pending_id = again
            closed = True  # The canonical authority is verifiable again.
            again = service.transcribe(session, provider, config_key="same")
            settled()
            assert service.jobs.get(again).state.value == "SUCCEEDED" and provider.calls == 1
            assert (again == pending_id) if pending_id else (again != job_id)
            assert service.runner.admission_error(again) is None
            for relative, data in media.items():
                assert (library.root / relative / "audio.pcm").read_bytes() == data
        finally:
            closed = True
            service.close()


def test_a_task_error_cannot_claim_that_no_reader_or_dispatch_was_admitted():
    with JobStore(Path(":memory:")) as store:
        job = store.create("transcription", "same")
        runner = BoundedRunner(store)
        runner.start()
        try:

            def task(attempt, cancel):
                raise StateConflict("DELETION_HISTORY_UNAVAILABLE")

            assert runner.submit(job.job_id, task)
            import time

            deadline = time.monotonic() + 10
            while store.get(job.job_id).state.value != "FAILED" and time.monotonic() < deadline:
                time.sleep(0.001)
            assert store.get(job.job_id).state.value == "FAILED"
            assert runner.admission_error(job.job_id) is None
        finally:
            runner.stop()


@pytest.mark.parametrize("row", W, ids=[f"G07-W-{n:03}" for n in range(1, len(W) + 1)])
def test_typed_boundary_preserves_code_and_outcome(row):
    code, boundary, known = row
    calls = []

    def reserve(request):
        calls.append("reserve")
        if boundary == "factory":
            raise SecurityError(code, outcome_known=known)
        return "reservation"

    class Gateway:
        def request(self, *args, **kwargs):
            calls.append("gateway")
            raise SecurityError(code, outcome_known=known)

    run = Run(
        ProviderConfig("openai", "model", endpoint="https://example.invalid/api"),
        ExecutionContext(reservation_factory=reserve),
    )
    with pytest.raises(ProviderError) as caught:
        run.request(Gateway(), "https://example.invalid/api", "audio", b"body", operation="stt")
    assert caught.value.code == code and caught.value.outcome_known is known
    assert calls == (["reserve"] if boundary == "factory" else ["reserve", "gateway"])
    with JobStore(Path(":memory:")) as store:
        job = store.create("stt", "x")
        attempt = store.claim(job.job_id, "runner")
        normalized = BoundedRunner._failure(caught.value)
        failed = store.fail(job.job_id, attempt.attempt_id, attempt.fence, *normalized)
        expected = (
            ("BLOCKED", "REMOTE_UNKNOWN")
            if not known
            else (
                ("BLOCKED", "CONSENT")
                if code in ORACLE["CONSENT"]
                else ("BLOCKED", "BUDGET")
                if code in ORACLE["BUDGET"]
                else ("BLOCKED", "CAPABILITY")
                if code == "LOCAL_EXECUTION_UNVERIFIED"
                else ("FAILED", None)
            )
        )
        assert (failed.state.value, failed.blocked_reason) == expected


C = list(
    product(
        (
            "CONSENT_REQUIRED",
            "AUTH_REQUIRED",
            "CAPABILITY_UNSUPPORTED",
            "OOM",
            "COST_CAP_EXCEEDED",
            "TEMPORARY",
            "INPUT_INVALID",
            "REMOTE_OUTCOME_UNKNOWN",
            "G07_UNREGISTERED_ERROR",
        ),
        (False, True),
        (False, True),
        ("cancel-first", "failure-first"),
    )
)


@pytest.mark.parametrize("row", C, ids=[f"G07-C-{n:03}" for n in range(1, len(C) + 1)])
def test_cancel_and_failure_ack_order(row):
    code, retry, known, order = row
    effective_known = known and code != "REMOTE_OUTCOME_UNKNOWN"
    with JobStore(Path(":memory:")) as store:
        job = store.create("stt", "x")
        a = store.claim(job.job_id, "worker")
        store.reader_started(a)
        if order == "cancel-first":
            store.cancel(job.job_id)
            error = ProviderError(code, retryable=retry, outcome_known=known)
            facts = BoundedRunner._failure(error)
            store._ack_cancelled(a, outcome_known=facts[2])
        else:
            store.fail(job.job_id, a.attempt_id, a.fence, code, retry, known)
            store.cancel(job.job_id)
        final = store.get(job.job_id)
        if not effective_known:
            assert final.state.value == "BLOCKED" and final.blocked_reason == "REMOTE_UNKNOWN"
            assert final.cancel_requested
        elif order == "failure-first" and (
            code in {"INPUT_INVALID", "G07_UNREGISTERED_ERROR"}
            or (code == "TEMPORARY" and not retry)
        ):
            assert final.state.value == "FAILED"
        else:
            assert final.state.value == "CANCELLED"
        assert store.local_reader_active(job.job_id) is True
        store.reader_finished(a)
        assert store.local_reader_active(job.job_id) is False


def service_fixture(store):
    """Admission exercised without starting a model, worker or physical reader."""
    service = AIService.__new__(AIService)
    service.jobs = store
    service._admission_lock = threading.RLock()
    service._admitted, service._session_jobs = set(), {}
    service._closed = False
    return service


@pytest.mark.parametrize(
    "kind,reason,code",
    [
        (kind, reason, code)
        for kind in ("transcription", "summarization")
        for reason, code in zip(
            ("CONSENT", "AUTH", "CAPABILITY", "RESOURCE", "BUDGET"),
            (
                "CONSENT_REQUIRED",
                "AUTH_REQUIRED",
                "CAPABILITY_UNSUPPORTED",
                "OOM",
                "COST_CAP_EXCEEDED",
            ),
            strict=True,
        )
    ],
    ids=[f"G07-A-{n:02}" for n in range(1, 11)],
)
def test_normal_request_cannot_implicitly_resume(reason, code, kind):
    with JobStore(Path(":memory:")) as store:
        service = service_fixture(store)
        original, admitted, _ = service._admit("s", kind, "same-plan")
        assert admitted
        blocked = store.block_pending(
            original.job_id, reason, code, expected_version=original.state_version
        )
        before = store._db.execute("SELECT * FROM events").fetchall()
        again, admitted, created = service._admit("s", kind, "same-plan")
        assert again == blocked and not admitted and not created
        assert store._db.execute("SELECT * FROM events").fetchall() == before
        assert store._db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0


F = list(
    product(
        ("CONSENT", "AUTH", "CAPABILITY", "RESOURCE", "BUDGET"),
        ("same", "stale", "changed"),
        (False, True),
    )
)


@pytest.mark.parametrize("row", F, ids=[f"G07-FIX1-CAS-{n:02}" for n in range(1, len(F) + 1)])
def test_continue_requires_same_plan_current_version_and_reader_ack(row):
    reason, preparation, active = row
    code = {
        "CONSENT": "CONSENT_REQUIRED",
        "AUTH": "AUTH_REQUIRED",
        "CAPABILITY": "CAPABILITY_UNSUPPORTED",
        "RESOURCE": "OOM",
        "BUDGET": "COST_CAP_EXCEEDED",
    }[reason]
    with JobStore(Path(":memory:")) as store:
        service = service_fixture(store)
        job, _, _ = service._admit("s", "transcription", "same")
        a = store.claim(job.job_id, "worker")
        store.reader_started(a)
        before = store.fail(job.job_id, a.attempt_id, a.fence, code)
        if not active:
            store.reader_finished(a)
        version = before.state_version - (preparation == "stale")
        if preparation == "same" and not active:
            after, admitted, created = service._admit(
                "s",
                "transcription",
                "same",
                expected_job_id=job.job_id,
                expected_job_version=version,
            )
            assert admitted and not created and after.job_id == job.job_id
            assert after.attempt_count == 1 and after.state.value == "QUEUED"
        else:
            with pytest.raises(StateConflict):
                service._admit(
                    "s",
                    "transcription",
                    "different" if preparation == "changed" else "same",
                    expected_job_id=job.job_id,
                    expected_job_version=version,
                )
            assert store.get(job.job_id) == before
        assert len(store.list_for_session("s")) == 1
        assert store._db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 1


def test_boundary_and_order_census():
    assert len(WIRE) == len(set(WIRE)) == 43
    assert len(W) == len(set(W)) == 172
    assert len(C) == len(set(C)) == 72
    assert len(F) == len(set(F)) == 30


# All original ordinals are now active against the G-P15 canonical authority API.
L_ROWS = list(
    product(
        ("valid", "db_pending", "journal_only", "both", "tombstone", "missing", "unavailable"),
        ("claim", "pending", "resume"),
    )
) + list(
    product(
        ("valid", "db_pending", "journal_only", "both", "tombstone", "missing", "unavailable"),
        ("known_ack", "unknown_ack"),
    )
)
L_WAITING: frozenset[int] = frozenset()
L_READY = [(ordinal, *row) for ordinal, row in enumerate(L_ROWS, 1) if ordinal not in L_WAITING]


@pytest.mark.parametrize(
    "ordinal,authority,operation", L_READY, ids=[f"G07-L-{row[0]:02}" for row in L_READY]
)
def test_canonical_authority_admission_and_failure_ack(tmp_path, ordinal, authority, operation):
    from recoryn.storage import Library

    with Library(tmp_path / "library") as library, JobStore(library.db_path) as store:
        library.create_session("s")
        canary = library.root / "sessions" / "s" / "authority-canary.bin"
        canary.parent.mkdir(parents=True)
        original = b"synthetic-original-preservation-canary"
        canary.write_bytes(original)
        job = store.create("stt", "immutable-plan")
        store.bind_session(job.job_id, "s")
        attempt = None
        if operation == "resume":
            job = store.block_pending(
                job.job_id, "CONSENT", "CONSENT_REQUIRED", expected_version=job.state_version
            )
        if operation in {"known_ack", "unknown_ack"}:
            attempt = store.claim(job.job_id, "reader")
            store.reader_started(attempt)
        before = store.get(job.job_id)
        before_attempts = store._db.execute("SELECT * FROM attempts").fetchall()
        # Independent storage facts: journal-only and DB-only must not collapse.
        if authority in {"db_pending", "both", "tombstone"}:
            status = "DELETED_LOCAL" if authority == "tombstone" else "DELETE_PENDING"
            store._db.execute("INSERT INTO deleted_sessions VALUES('s',1,?)", (status,))
        if authority == "journal_only":
            # Durable input can precede this process's index (restore/reopen or
            # outside change). Do not seed the cache through the production writer.
            import json

            (library.root / "deletion-journal" / "s.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "session_id": "s",
                        "generation": 1,
                        "state": "DELETE_REQUESTED",
                    }
                ),
                encoding="utf-8",
            )
        elif authority == "both":
            with library._mutex:
                library._publish_intent("s", 1)
        if authority == "missing":
            store._db.execute("DELETE FROM sessions WHERE session_id='s'")
        if authority == "unavailable":
            (library.root / "deletion-journal" / ".tmp-uncommitted").write_bytes(b"incomplete")
        assert store._db.execute("SELECT COUNT(*) FROM deleted_sessions").fetchone()[0] == int(
            authority in {"db_pending", "both", "tombstone"}
        )
        expected_authority = {
            "valid": "VALID",
            "db_pending": "DB_ONLY",
            "journal_only": "JOURNAL_ONLY",
            "both": "BOTH",
            "tombstone": "TOMBSTONE",
            "missing": "MISSING",
            "unavailable": "HISTORY_UNAVAILABLE",
        }[authority]
        with Library.job_authority(library.db_path, "s") as actual_authority:
            assert actual_authority == expected_authority
        if attempt is not None:
            known = operation == "known_ack"
            result = store.fail(
                job.job_id,
                attempt.attempt_id,
                attempt.fence,
                "CONSENT_REQUIRED",
                outcome_known=known,
            )
            expected = (
                ("BLOCKED", "REMOTE_UNKNOWN")
                if not known
                else ("BLOCKED", "CONSENT")
                if authority == "valid"
                else ("FAILED", None)
            )
            assert (result.state.value, result.blocked_reason) == expected
            assert result.attempt_count == before.attempt_count
            assert store.local_reader_active(job.job_id) is True
            store.reader_finished(attempt)
            assert store.local_reader_active(job.job_id) is False
        else:

            def invoke():
                if operation == "claim":
                    return store.claim(job.job_id, "reader")
                if operation == "pending":
                    return store.block_pending(
                        job.job_id,
                        "CONSENT",
                        "CONSENT_REQUIRED",
                        expected_version=before.state_version,
                    )
                return store.resume(job.job_id, expected_version=before.state_version)

            if authority == "valid":
                result = invoke()
                assert result.job_id == job.job_id
                assert (
                    result.state.value
                    == {"claim": "RUNNING", "pending": "BLOCKED", "resume": "QUEUED"}[operation]
                )
            else:
                with pytest.raises(StateConflict):
                    invoke()
                assert store.get(job.job_id) == before
                assert store._db.execute("SELECT * FROM attempts").fetchall() == before_attempts
        assert canary.read_bytes() == original


def test_authority_case_partition_is_explicit():
    assert len(L_ROWS) == len(set(L_ROWS)) == 35
    assert len(L_READY) == 35
    assert {row[0] for row in L_READY} | L_WAITING == set(range(1, 36))
    assert not ({row[0] for row in L_READY} & L_WAITING)


@pytest.mark.parametrize(
    "cause",
    (
        "missing_owner",
        "closed_mid_read",
        "future",
        "bad_status",
        "bad_generation",
        "newer_session",
        "moving_stamp",
        "changing_version",
    ),
)
def test_authority_uncertainty_is_not_permission(tmp_path, monkeypatch, cause):
    from recoryn.storage import Library

    library = Library(tmp_path / "library")
    store = JobStore(library.db_path)
    try:
        library.create_session("s")
        job = store.create("stt", "fixed")
        store.bind_session(job.job_id, "s")
        if cause == "missing_owner":
            library.close()
        elif cause == "closed_mid_read":
            read = library._journal_prefetch

            def close_after_read():
                result = read()
                library.close()
                return result

            monkeypatch.setattr(library, "_journal_prefetch", close_after_read)
        elif cause == "future":
            store._db.execute("PRAGMA user_version=2")
        elif cause in {"bad_status", "bad_generation", "newer_session"}:
            store._db.execute(
                "INSERT INTO deleted_sessions VALUES('s',?,?)",
                (
                    0 if cause == "bad_generation" else 1,
                    "FUTURE" if cause == "bad_status" else "DELETE_PENDING",
                ),
            )
            if cause == "newer_session":
                store._db.execute("UPDATE sessions SET generation=2")
        elif cause == "moving_stamp":
            counter = [0]

            def moving():
                counter[0] += 1
                return (1, 2, counter[0])

            monkeypatch.setattr(library, "_journal_stamp", moving)
        else:
            read = library._journal_prefetch

            def changed():
                result = read()
                with library._mutex:
                    library._history_version += 1
                return result

            monkeypatch.setattr(library, "_journal_prefetch", changed)
        with Library.job_authority(library.db_path, "s") as state:
            assert state == "HISTORY_UNAVAILABLE"
        before = store.get(job.job_id)
        with pytest.raises(StateConflict, match="DELETION_HISTORY_UNAVAILABLE"):
            store.claim(job.job_id, "reader")
        assert store.get(job.job_id) == before
    finally:
        store.close()
        library.close()


def test_old_library_close_does_not_unregister_a_new_owner(tmp_path):
    from recoryn.storage import Library

    old = Library(tmp_path / "library")
    old.create_session("s")
    old.close()
    with Library(old.root) as current:
        old.close()
        with Library.job_authority(current.db_path, "s") as state:
            assert state == "VALID"


def test_in_place_corrupt_history_is_not_hidden_by_an_unchanged_directory_index(tmp_path):
    from recoryn.storage import Library

    with Library(tmp_path / "library") as library, JobStore(library.db_path) as store:
        library.create_session("s")
        job = store.create("stt", "fixed")
        store.bind_session(job.job_id, "s")
        with library._mutex:
            library._publish_intent("past", 1)
        directory = library.root / "deletion-journal"
        before = directory.stat().st_mtime_ns
        (directory / "past.json").write_bytes(b"{malformed")
        assert directory.stat().st_mtime_ns == before
        with Library.job_authority(library.db_path, "s") as state:
            assert state == "HISTORY_UNAVAILABLE"
        with pytest.raises(StateConflict, match="DELETION_HISTORY_UNAVAILABLE"):
            store.claim(job.job_id, "reader")
        assert store.get(job.job_id) == job


def test_authority_enumeration_is_outside_root_job_transaction_and_job_lock(tmp_path, monkeypatch):
    import os

    import recoryn.storage.library as library_module
    from recoryn.storage import Library

    with Library(tmp_path / "library") as library, JobStore(library.db_path) as store:
        library.create_session("s")
        job = store.create("stt", "fixed")
        store.bind_session(job.job_id, "s")
        actual_lock = library._mutex
        depth = threading.local()

        class ObservedLock:
            def __enter__(self):
                actual_lock.acquire()
                depth.value = getattr(depth, "value", 0) + 1

            def __exit__(self, *_):
                depth.value -= 1
                actual_lock.release()

        monkeypatch.setattr(library, "_mutex", ObservedLock())
        counts = {name: 0 for name in ("iterdir", "scandir", "listdir", "remove_tree")}

        def watch(owner, name):
            original = getattr(owner, name)

            def wrapped(*args, **kwargs):
                counts[name] += 1
                assert not getattr(depth, "value", 0), name + " under root mutex"
                assert not store._db.in_transaction, name + " inside Job transaction"
                assert not store._lock._is_owned(), name + " under Job lock"
                return original(*args, **kwargs)

            monkeypatch.setattr(owner, name, wrapped)

        watch(Path, "iterdir")
        watch(os, "scandir")
        watch(os, "listdir")
        watch(library_module, "remove_tree")
        a = store.claim(job.job_id, "reader")
        store.reader_started(a)
        blocked = store.fail(job.job_id, a.attempt_id, a.fence, "CONSENT_REQUIRED")
        store.reader_finished(a)
        store.resume(job.job_id, expected_version=blocked.state_version)
        current = store.get(job.job_id)
        store.block_pending(
            job.job_id, "CONSENT", "CONSENT_REQUIRED", expected_version=current.state_version
        )
        assert counts["iterdir"] >= 5 and counts["remove_tree"] == 0


def test_intent_racing_with_preflight_forces_recheck_before_admission(tmp_path, monkeypatch):
    from recoryn.storage import Library

    with Library(tmp_path / "library") as library, JobStore(library.db_path) as store:
        library.create_session("s")
        job = store.create("stt", "fixed")
        store.bind_session(job.job_id, "s")
        begin, done = threading.Event(), threading.Event()
        failures = []

        def publish():
            try:
                assert begin.wait(5)
                with library._mutex:
                    library._publish_intent("s", 1)
            except BaseException as error:
                failures.append(error)
            finally:
                done.set()

        publisher = threading.Thread(target=publish)
        publisher.start()
        read = library._journal_prefetch
        calls = [0]

        def raced():
            result = read()
            calls[0] += 1
            if calls[0] == 1:
                begin.set()
                assert done.wait(5), "journal I/O/preflight retained root mutex"
            return result

        monkeypatch.setattr(library, "_journal_prefetch", raced)
        try:
            with pytest.raises(StateConflict, match="JOB_SESSION_DELETED"):
                store.claim(job.job_id, "reader")
        finally:
            begin.set()
            publisher.join(5)
        assert not publisher.is_alive() and not failures and calls[0] >= 2
        assert store.get(job.job_id) == job


def test_intent_after_claim_blocks_reader_start_but_never_its_exit_ack(tmp_path):
    from recoryn.storage import Library

    with Library(tmp_path / "library") as library, JobStore(library.db_path) as store:
        library.create_session("s")
        job = store.create("stt", "fixed")
        store.bind_session(job.job_id, "s")
        a = store.claim(job.job_id, "reader")
        with library._mutex:
            library._publish_intent("s", 1)
        with pytest.raises(StateConflict, match="JOB_SESSION_DELETED"):
            store.reader_started(a)
        assert store.local_reader_active(job.job_id) is False
        failed = store.fail(job.job_id, a.attempt_id, a.fence, "CONSENT_REQUIRED")
        assert failed.state.value == "FAILED"
        store.reader_finished(a)
        assert store.local_reader_active(job.job_id) is False


def test_child_import_paths_belong_to_this_checkout():
    import json
    import os
    import subprocess
    import sys

    expected = Path(__file__).resolve().parents[2] / "src"
    program = (
        "import json,recoryn.jobs,recoryn.storage.library,recoryn.app.status;"
        "print(json.dumps([recoryn.jobs.__file__,recoryn.storage.library.__file__,recoryn.app.status.__file__]))"
    )
    env = dict(os.environ, PYTHONPATH=str(expected), PYTHONDONTWRITEBYTECODE="1")
    child = subprocess.run(
        [sys.executable, "-B", "-c", program],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    actual = [Path(value).resolve() for value in json.loads(child.stdout)]
    assert len(actual) == 3 and all(path.is_relative_to(expected) for path in actual)


def test_binding_added_after_authority_snapshot_cannot_bypass_preflight(monkeypatch):
    from contextlib import contextmanager

    with JobStore(Path(":memory:")) as store:
        job = store.create("stt", "fixed")
        original = store._transaction
        first = [True]

        @contextmanager
        def bind_before_transaction():
            if first[0]:
                first[0] = False
                store.bind_session(job.job_id, "s")
            with original():
                yield

        monkeypatch.setattr(store, "_transaction", bind_before_transaction)
        with pytest.raises(StateConflict, match="JOB_VERSION_CHANGED"):
            store.claim(job.job_id, "reader")
        assert store.get(job.job_id) == job
        assert store._db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0


def test_authority_lease_prevents_intent_until_job_commit(tmp_path, monkeypatch):
    from recoryn.storage import Library

    with Library(tmp_path / "library") as library, JobStore(library.db_path) as store:
        library.create_session("s")
        job = store.create("stt", "fixed")
        store.bind_session(job.job_id, "s")
        actual = library._mutex
        attempted, start = threading.Event(), threading.Event()
        order, errors = [], []

        class Lock:
            def __enter__(self):
                if threading.current_thread().name == "g07-delete":
                    attempted.set()
                actual.acquire()

            def __exit__(self, *_):
                actual.release()

        monkeypatch.setattr(library, "_mutex", Lock())

        def publish():
            try:
                assert start.wait(5)
                with library._mutex:
                    library._publish_intent("s", 1)
                    order.append("intent")
            except BaseException as error:
                errors.append(error)

        thread = threading.Thread(target=publish, name="g07-delete")
        thread.start()
        event = store._event

        def during_claim(job_id):
            start.set()
            assert attempted.wait(5)
            assert "intent" not in order
            return event(job_id)

        monkeypatch.setattr(store, "_event", during_claim)
        store._db.set_trace_callback(
            lambda sql: order.append("commit") if sql == "COMMIT" else None
        )
        try:
            a = store.claim(job.job_id, "reader")
        finally:
            start.set()
            thread.join(5)
        assert not thread.is_alive() and not errors
        assert order.index("commit") < order.index("intent")
        assert a.attempt_no == 1
        with pytest.raises(StateConflict, match="JOB_SESSION_DELETED"):
            store.reader_started(a)


@pytest.mark.parametrize(
    "reason,code",
    [
        ("CONSENT", "CONSENT_POLICY_CHANGED"),
        ("AUTH", "AUTH_REQUIRED"),
        ("CAPABILITY", "CAPABILITY_UNSUPPORTED"),
        ("RESOURCE", "OOM"),
        ("BUDGET", "COST_CAP_EXCEEDED"),
    ],
)
def test_real_runner_explicit_continue_preserves_an_independent_recording(tmp_path, reason, code):
    import time

    from recoryn.app.recording import RecordingService
    from recoryn.content import ContentStore
    from recoryn.domain import AudioFormat, PCMBlock
    from recoryn.providers import STTResult, TranscriptSegment
    from recoryn.storage import Library

    class Provider:
        def __init__(self):
            self.calls = 0
            self.block = True

        def transcribe(self, request, context=None):
            self.calls += 1
            if self.block:
                raise ProviderError(code, retryable=True)
            return STTResult(
                "fake",
                "model",
                (TranscriptSegment("s1", 0, 50, "fixed", track_id=request.track_id),),
                True,
                processed_ms=100,
            )

    def finish(service, job_id):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            job = service.jobs.get(job_id)
            if job.state.value in {"BLOCKED", "FAILED", "SUCCEEDED", "CANCELLED"}:
                return job
            time.sleep(0.001)
        pytest.fail("bounded fake did not finish")

    with Library(tmp_path / "library") as library, ContentStore(library) as content:
        fmt = AudioFormat(8000, 1)
        original = b"\x00\x40" * 800
        source = RecordingService(library, {"mic": fmt})
        source.start()
        assert source.submit(
            PCMBlock(source.session_id, "mic", source.epochs["mic"], 0, fmt, 800, original, 0, 0)
        )
        source.stop(timeout=60)
        live = RecordingService(library, {"mic": fmt})
        live.start()
        service = AIService(library, content)
        provider = Provider()
        try:
            job_id = service.transcribe(source.session_id, provider, config_key="same")
            blocked = finish(service, job_id)
            assert (blocked.state.value, blocked.blocked_reason, blocked.attempt_count) == (
                "BLOCKED",
                reason,
                1,
            )
            assert service.jobs.local_reader_active(job_id) is False
            assert service.transcribe(source.session_id, provider, config_key="same") == job_id
            assert service.jobs.get(job_id) == blocked and provider.calls == 1
            assert live.health_snapshot()["accepting"]
            assert live.submit(
                PCMBlock(live.session_id, "mic", live.epochs["mic"], 0, fmt, 800, original, 0, 0)
            )
            provider.block = False
            assert (
                service.transcribe(
                    source.session_id,
                    provider,
                    config_key="same",
                    expected_job_id=job_id,
                    expected_job_version=blocked.state_version,
                )
                == job_id
            )
            succeeded = finish(service, job_id)
            assert succeeded.state.value == "SUCCEEDED" and succeeded.attempt_count == 2
            assert (
                provider.calls == 2
                and content.active_transcript(source.session_id)["segments"][0]["text"] == "fixed"
            )
            assert live.health_snapshot()["accepting"]
        finally:
            service.close()
            live.stop(timeout=60)
        assert sum(item.frame_count for item in library.chunks(source.session_id)) == 800
        assert sum(item.frame_count for item in library.chunks(live.session_id)) == 800
