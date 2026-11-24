"""BR24 independent publication/retirement oracles using real SQLite only."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

import pytest

from recoryn.app.ai import AIService
from recoryn.content import Claim, ContentStore, Segment
from recoryn.domain import StateConflict, ValidationError
from recoryn.jobs import AttemptState, JobState, JobStore
from recoryn.jobs.runner import BoundedRunner
from recoryn.providers import ExecutionContext, ProviderConfig
from recoryn.security import (
    ConsentRequest,
    ConsentScope,
    ConsentStore,
    CostLedger,
    CostRequest,
    Gateway,
    SecurityError,
)
from recoryn.security._core import Endpoint
from recoryn.storage import Library
from recoryn.summarization import OpenAISummarizer
from tests.resource_fakes import SUMMARY
from tests.unit.test_cost_cap import fixture_balance, fixture_reservation

pytestmark = pytest.mark.integration


def one_segment(text: str = "fixed source") -> list[Segment]:
    return [Segment("s1", 0, 100, text, track_id="microphone")]


@pytest.mark.parametrize("kind", ("transcript", "summary"))
def test_bound_job_cannot_publish_into_other_live_session(tmp_path: Path, kind: str) -> None:
    with (
        Library(tmp_path) as library,
        ContentStore(library) as content,
        JobStore(library.db_path) as jobs,
    ):
        library.create_session("source")
        library.create_session("other")
        target = content.create_transcript("other", one_segment())
        job = jobs.create(kind, "source-bound-input")
        jobs.bind_session(job.job_id, "source")
        attempt = jobs.claim(job.job_id, "br24")
        before = content.list_revisions("other")
        with pytest.raises((StateConflict, ValidationError)):
            if kind == "transcript":
                content.publish_transcript(jobs, attempt, "other", one_segment("cross-session"))
            else:
                content.publish_summary(
                    jobs,
                    attempt,
                    "other",
                    target,
                    [Claim("cross-session", ("s1",))],
                    expected_transcript=target,
                )
        assert content.list_revisions("other") == before
        assert jobs.get(job.job_id).state == JobState.RUNNING


def test_event_commit_failure_rolls_back_content_selection_job_and_attempt(tmp_path: Path) -> None:
    with (
        Library(tmp_path) as library,
        ContentStore(library) as content,
        JobStore(library.db_path) as jobs,
    ):
        library.create_session("session")
        job = jobs.create("transcription", "atomic-input")
        jobs.bind_session(job.job_id, "session")
        attempt = jobs.claim(job.job_id, "br24")
        running = jobs.get(job.job_id)
        with closing(sqlite3.connect(library.db_path)) as observer, observer:
            observer.execute("""CREATE TRIGGER br24_fail_terminal_event BEFORE INSERT ON events
              WHEN NEW.state='SUCCEEDED' BEGIN SELECT RAISE(ABORT, 'BR24_COMMIT_FAULT'); END""")
        with pytest.raises(sqlite3.IntegrityError, match="BR24_COMMIT_FAULT"):
            content.publish_transcript(jobs, attempt, "session", one_segment())
        assert content.active_transcript("session") is None
        assert not content.list_revisions("session")
        assert jobs.get(job.job_id) == running
        with closing(sqlite3.connect(library.db_path)) as observer:
            assert observer.execute(
                "SELECT state,result_ref FROM attempts WHERE attempt_id=?", (attempt.attempt_id,)
            ).fetchone() == (AttemptState.RUNNING.value, None)
            assert observer.execute("SELECT COUNT(*) FROM content_events").fetchone() == (0,)
            assert observer.execute(
                "SELECT COUNT(*) FROM events WHERE state='SUCCEEDED'"
            ).fetchone() == (0,)


def test_cancel_commit_first_blocks_every_late_publication(tmp_path: Path) -> None:
    with (
        Library(tmp_path) as library,
        ContentStore(library) as content,
        JobStore(library.db_path) as jobs,
    ):
        library.create_session("session")
        job = jobs.create("transcription", "late-input")
        jobs.bind_session(job.job_id, "session")
        attempt = jobs.claim(job.job_id, "br24")
        cancelled = jobs.cancel(job.job_id)
        assert cancelled.state == JobState.CANCEL_REQUESTED and cancelled.fence > attempt.fence
        for complete in (False, True):
            with pytest.raises(StateConflict):
                content.publish_transcript(
                    jobs, attempt, "session", one_segment(), complete=complete
                )
        assert not content.list_revisions("session")


def test_sql_publication_commit_first_wins_against_concurrent_cancel(tmp_path: Path) -> None:
    db = tmp_path / "jobs.sqlite"
    with JobStore(db) as publisher, JobStore(db) as canceller:
        with closing(sqlite3.connect(db)) as observer, observer:
            observer.execute("CREATE TABLE br24_payload(value TEXT)")
        job = publisher.create("local", "ordered-input")
        attempt = publisher.claim(job.job_id, "br24")
        ready, release, cancellation_started = (
            threading.Event(),
            threading.Event(),
            threading.Event(),
        )

        def save(connection: sqlite3.Connection) -> str:
            connection.execute("INSERT INTO br24_payload VALUES('one immutable result')")
            ready.set()
            assert release.wait(5)
            return "result-one"

        def cancel() -> JobState:
            cancellation_started.set()
            return canceller.cancel(job.job_id).state

        with ThreadPoolExecutor(max_workers=2) as pool:
            result = pool.submit(
                publisher.complete_with, job.job_id, attempt.attempt_id, attempt.fence, save
            )
            try:
                assert ready.wait(5)
                cancellation = pool.submit(cancel)
                assert cancellation_started.wait(5)
            finally:
                release.set()
            assert result.result(timeout=5).state == JobState.SUCCEEDED
            assert cancellation.result(timeout=5) == JobState.SUCCEEDED
        with closing(sqlite3.connect(db)) as observer:
            assert observer.execute("SELECT value FROM br24_payload").fetchall() == [
                ("one immutable result",)
            ]
        # Idempotent replay never invokes the publisher a second time.
        assert (
            publisher.complete_with(
                job.job_id,
                attempt.attempt_id,
                attempt.fence,
                lambda connection: pytest.fail("publisher replayed"),
            ).result_ref
            == "result-one"
        )


def test_edit_cas_keeps_machine_candidate_and_original_evidence(tmp_path: Path) -> None:
    with (
        Library(tmp_path) as library,
        ContentStore(library) as content,
        JobStore(library.db_path) as jobs,
    ):
        library.create_session("session")
        source = content.create_transcript("session", one_segment())
        source_before = content.transcript(source)
        job = jobs.create("transcription", "edit-race-input")
        jobs.bind_session(job.job_id, "session")
        attempt = jobs.claim(job.job_id, "br24")
        edit = content.edit_segment(
            "session", source, "s1", "user supplied correction", expected_active=source
        )
        machine = content.publish_transcript(
            jobs, attempt, "session", one_segment("late machine"), expected_active=source
        )
        assert jobs.get(job.job_id).result_ref == machine
        assert jobs.get(job.job_id).state == JobState.SUCCEEDED
        assert content.active_transcript("session")["revision_id"] == edit  # type: ignore[index]
        assert content.transcript(source) == source_before
        assert content.transcript(machine)["segments"][0]["text"] == "late machine"
        edited = content.transcript(edit)["segments"][0]
        assert edited["provenance"] == "user_assertion" and edited["timing_quality"] == "unverified"
        summary = content.create_summary(
            "session", edit, [Claim("from correction", ("s1",))], expected_transcript=edit
        )
        assert content.summary(summary)["claims"][0]["basis"] == "user_assertion"


def test_unknown_job_remains_unknown_across_cancel_reopen_and_recovery(tmp_path: Path) -> None:
    db = tmp_path / "jobs.sqlite"
    with JobStore(db) as jobs:
        job = jobs.create("cloud", "uncertain-input")
        attempt = jobs.claim(job.job_id, "br24")
        failed = jobs.fail(
            job.job_id,
            attempt.attempt_id,
            attempt.fence,
            "REMOTE_OUTCOME_UNKNOWN",
            retryable=True,
            outcome_known=False,
        )
        assert failed.state == JobState.BLOCKED and failed.blocked_reason == "REMOTE_UNKNOWN"
        jobs.cancel(job.job_id)
    with JobStore(db) as restarted:
        assert not restarted.recover_abandoned()
        recovered = restarted.get(job.job_id)
        assert recovered.state == JobState.BLOCKED and recovered.blocked_reason == "REMOTE_UNKNOWN"
        with pytest.raises(StateConflict):
            restarted.claim(job.job_id, "new-owner")


@pytest.mark.parametrize("sent", (False, True))
@pytest.mark.parametrize("cancelled", (False, True))
def test_crash_after_remote_handoff_cannot_become_locally_retryable(
    tmp_path: Path,
    sent: bool,
    cancelled: bool,
) -> None:
    jobs_db, cost_db = tmp_path / "jobs.sqlite", tmp_path / "security.sqlite"
    with JobStore(jobs_db) as jobs, CostLedger(cost_db) as ledger:
        job = jobs.create("transcription", "remote-execution-input")
        attempt = jobs.claim(job.job_id, "departed-cloud-worker")
        jobs.reader_started(attempt)
        reservation = ledger.reserve("openai", "sent-request", 50, 100)
        jobs.mark_remote_intent(attempt, reservation)
        if sent:
            ledger.mark_unknown(reservation)
        if cancelled:
            jobs.cancel(job.job_id)
        # Process exit after an irreversible handoff, before JobStore.fail/complete.
    with JobStore(jobs_db) as restarted, CostLedger(cost_db) as ledger:
        assert ledger.snapshot("openai")["unknown_exposure" if sent else "reserved"] == 50
        restarted.recover_abandoned(coordinator_exclusive=True)
        recovered = restarted.get(job.job_id)
        assert recovered.blocked_reason == "REMOTE_UNKNOWN"
        with pytest.raises(StateConflict):
            restarted.claim(job.job_id, "retry-owner")


@pytest.mark.parametrize("outcome", ("success", "failure", "unknown"))
def test_logical_completion_cannot_delete_live_reader_but_ack_allows_deletion(
    tmp_path: Path,
    outcome: str,
) -> None:
    with Library(tmp_path) as library, JobStore(library.db_path) as jobs:
        library.create_session("source")
        library.create_session("independent")
        job = jobs.create("transcription", "reader-input")
        jobs.bind_session(job.job_id, "source")
        attempt = jobs.claim(job.job_id, "reader")
        jobs.reader_started(attempt)
        if outcome == "success":
            jobs.complete(job.job_id, attempt.attempt_id, attempt.fence, "published-ref")
        else:
            jobs.fail(
                job.job_id,
                attempt.attempt_id,
                attempt.fence,
                "REMOTE_OUTCOME_UNKNOWN" if outcome == "unknown" else "TASK_FAILED",
                outcome_known=outcome != "unknown",
            )
        terminal = jobs.get(job.job_id)
        assert jobs.local_reader_active(job.job_id) is True
        assert library.delete_session("independent")["deleted"] is True
        held = library.delete_session("source")
        assert held["state"] == "DELETE_PENDING" and not held["deleted"]
        jobs.reader_finished(attempt)
        assert jobs.local_reader_active(job.job_id) is False
        assert library.delete_session("source")["deleted"] is True
        assert jobs.get(job.job_id) == terminal
        jobs.reader_finished(attempt)  # Physical ACK is idempotent even after deletion.


def test_stale_ack_cannot_clear_replacement_reader_and_default_recovery_cannot_clear_live_reader(
    tmp_path: Path,
) -> None:
    with JobStore(tmp_path / "jobs.sqlite") as jobs:
        job = jobs.create("local", "replacement-input")
        first = jobs.claim(job.job_id, "old")
        jobs.reader_started(first)
        jobs.fail(job.job_id, first.attempt_id, first.fence, "TEMPORARY", retryable=True)
        with pytest.raises(StateConflict, match="LOCAL_READER_STILL_ACTIVE"):
            jobs.claim(job.job_id, "new")
        with pytest.raises(StateConflict, match="LOCAL_READERS_REQUIRE_EXCLUSIVE_RECOVERY"):
            jobs.recover_abandoned()
        assert jobs.local_reader_active(job.job_id) is True
        jobs.reader_finished(first)
        second = jobs.claim(job.job_id, "new")
        jobs.reader_started(second)
        with pytest.raises(StateConflict, match="STALE_LOCAL_READER"):
            jobs.reader_finished(first)
        assert jobs.local_reader_active(job.job_id) is True
        jobs.reader_finished(second)


def test_reader_ack_storage_failure_does_not_erase_remote_unknown(tmp_path: Path) -> None:
    class RemoteUnknown(RuntimeError):
        code = "REMOTE_OUTCOME_UNKNOWN"
        outcome_known = False
        retryable = False

    with Library(tmp_path) as library, JobStore(library.db_path) as jobs:
        library.create_session("source")
        job = jobs.create("transcription", "ack-failure-input")
        jobs.bind_session(job.job_id, "source")
        with closing(sqlite3.connect(library.db_path)) as observer, observer:
            observer.execute("""CREATE TRIGGER br24_ack_fail BEFORE UPDATE ON job_local_readers
              WHEN OLD.active=1 AND NEW.active=0
              BEGIN SELECT RAISE(ABORT, 'BR24_ACK_STORAGE_FAULT'); END""")
        runner = BoundedRunner(jobs)
        entered = threading.Event()

        def task(attempt: object, cancel: threading.Event) -> str:
            entered.set()
            raise RemoteUnknown("fake-only")

        runner.start()
        try:
            assert runner.submit(job.job_id, task)
            assert entered.wait(5)
            deadline = time.monotonic() + 5
            while jobs.get(job.job_id).state == JobState.RUNNING and time.monotonic() < deadline:
                threading.Event().wait(0.005)
            result = jobs.get(job.job_id)
            assert result.state == JobState.BLOCKED and result.blocked_reason == "REMOTE_UNKNOWN"
            assert jobs.local_reader_active(job.job_id) is True
            assert runner.snapshot()["reader_ack_error"] == "LOCAL_READER_ACK_FAILED"
            assert library.delete_session("source")["state"] == "DELETE_PENDING"
        finally:
            runner.stop(timeout=5)


def test_remote_marker_is_attempt_specific_and_not_inherited_after_known_failure(
    tmp_path: Path,
) -> None:
    db = tmp_path / "jobs.sqlite"
    with JobStore(db) as jobs:
        job = jobs.create("transcription", "known-failure")
        first = jobs.claim(job.job_id, "first")
        jobs.reader_started(first)
        jobs.mark_remote_intent(first, "one-remote-reservation")
        jobs.mark_remote_intent(first, "one-remote-reservation")
        jobs.reader_finished(first)
        jobs.fail(
            job.job_id,
            first.attempt_id,
            first.fence,
            "TRANSPORT_FAILED",
            retryable=True,
            outcome_known=True,
        )
        second = jobs.claim(job.job_id, "second")
        jobs.reader_started(second)
    with JobStore(db) as restarted:
        restarted.recover_abandoned(coordinator_exclusive=True)
        assert restarted.get(job.job_id).blocked_reason == "ABANDONED"
        third = restarted.claim(job.job_id, "third")
        assert third.attempt_no == 3


@pytest.mark.parametrize("marker_failure", (False, True))
def test_real_ai_reservation_wrapper_commits_marker_before_gateway(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    marker_failure: bool,
) -> None:
    target = "https://api.example.test/summary"
    with (
        Library(tmp_path) as library,
        ContentStore(library) as content,
        ConsentStore(tmp_path / "security.sqlite") as policy,
        CostLedger(tmp_path / "security.sqlite") as ledger,
    ):
        library.create_session("session")
        content.create_transcript("session", one_segment())
        policy.grant(
            "openai",
            target,
            "transcript",
            capability="summary",
            scope=_fixture_grant_scope(policy),
            policy_version=2,
        )
        reservations: list[str] = []
        opened: list[bool] = []

        class Connection:
            def __init__(self) -> None:
                self.response = json.dumps(
                    {
                        "status": "completed",
                        "output": [
                            {
                                "type": "message",
                                "content": [
                                    {
                                        "type": "output_text",
                                        "text": '{"claims":[{"text":"fixed claim","segment_ids":["s1"]}]}',
                                    }
                                ],
                            }
                        ],
                    }
                ).encode()

            def write(self, data: bytes, timeout: float) -> None:
                pass

            def read(self, limit: int, timeout: float) -> bytes:
                result, self.response = self.response[:limit], self.response[limit:]
                return result

            def close(self) -> None:
                pass

        class Transport:
            def open(
                self,
                endpoint: Endpoint,
                headers: Mapping[str, str],
                body_length: int,
                timeout: float,
            ) -> Connection:
                with closing(sqlite3.connect(library.db_path)) as observer:
                    rows = observer.execute(
                        "SELECT reservation_id FROM job_remote_intents"
                    ).fetchall()
                    assert rows == [(reservations[0],)]
                opened.append(True)
                return Connection()

        def reserve(request: CostRequest) -> str:
            assert (
                request.provider_id,
                request.endpoint,
                request.data_type,
                request.operation,
            ) == ("openai", target, "transcript", "summary")
            reservation = fixture_reservation(
                ledger, monkeypatch, request, 10, 100, "one-paid-request"
            )
            reservations.append(reservation)
            return reservation

        service = AIService(library, content)
        try:
            if marker_failure:
                with closing(sqlite3.connect(library.db_path)) as observer, observer:
                    observer.execute("""CREATE TRIGGER br24_marker_failure BEFORE INSERT ON job_remote_intents
                        BEGIN SELECT RAISE(ABORT, 'BR24_MARKER_FAILURE'); END""")
            provider = OpenAISummarizer(
                _fixture_gateway(
                    policy, ledger=ledger, transport=Transport(), capability="summary"
                ),
                ProviderConfig("openai", "test-model", endpoint=target, context_window_tokens=8192),
            )
            job_id = service.summarize(
                "session",
                provider,
                config_key="br24-marker",
                context_factory=lambda cancel: ExecutionContext(
                    cancel=cancel, reservation_factory=reserve
                ),
                resource_request=SUMMARY,
            )
            deadline = time.monotonic() + 5
            while (
                service.jobs.get(job_id).state in {JobState.QUEUED, JobState.RUNNING}
                and time.monotonic() < deadline
            ):
                threading.Event().wait(0.005)
            result = service.jobs.get(job_id)
            if marker_failure:
                assert not opened and result.error_code == "BUDGET_BLOCKED"
                assert fixture_balance(ledger, "openai")["reserved"] == 10
            else:
                assert opened == [True] and result.state == JobState.SUCCEEDED
                assert fixture_balance(ledger, "openai")["unknown_exposure"] == 10
        finally:
            service.close()


# The older tests exercise revocation/transport, with an explicitly chosen library
# grant. G02's separate cases exercise the default session-only permission.
def _fixture_request(
    policy: ConsentStore, session_id: str = "session", capability: str = "stt", generation: int = 0
) -> ConsentRequest:
    try:
        policy.bind_session(session_id, generation)
    except SecurityError:
        pass  # Registration grants nothing; the tested API still checks the fence.
    return ConsentRequest(session_id, generation, capability, 2)


def _fixture_grant_scope(policy: ConsentStore) -> ConsentScope:
    _fixture_request(policy)
    return ConsentScope.library()


def _fixture_gateway(
    policy: ConsentStore,
    *,
    session_id: str = "session",
    generation: int = 0,
    capability: str = "stt",
    factory=Gateway,
    **kwargs,
):
    root = factory(policy, **kwargs)
    request = _fixture_request(policy, session_id, capability)
    if "expected_grants" not in kwargs:
        bindings = []
        rows = policy._db.execute(
            "SELECT DISTINCT provider,endpoint,data_type FROM security_grants_v2 WHERE capability=? AND scope_kind='library' AND scope_id='' AND policy_version=2",
            (capability,),
        ).fetchall()
        for provider, endpoint, data_type in rows:
            bindings.extend(
                policy.capture_bindings(
                    provider, endpoint, (data_type,), scope=ConsentScope.library(), request=request
                )
            )
        kwargs["expected_grants"] = tuple(bindings)
        root = factory(policy, **kwargs)
    return root.for_session(
        session_id,
        generation,
        capability=capability,
        scope=ConsentScope.library(),
        policy_version=2,
    )
