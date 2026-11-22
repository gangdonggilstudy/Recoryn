"""Content oracles use fixed text/times and real SQLite, never an AI model."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import FrozenInstanceError
from pathlib import Path
from threading import Barrier
from typing import Any

import pytest

from recoryn.content import Claim, ContentStore, Segment
from recoryn.domain import AudioFormat, PCMBlock, StateConflict, ValidationError
from recoryn.jobs import AttemptRecord, JobState, JobStore
from recoryn.storage import ChunkWriter, Library


@pytest.fixture
def content(tmp_path: Path) -> Iterator[ContentStore]:
    with Library(tmp_path) as library:
        library.create_session("session")
        with ContentStore(library) as store:
            yield store


def test_revision_roundtrip_cas_and_immutability(content: ContentStore) -> None:
    first = content.create_transcript("session", [Segment("s1", 0, 1000, "안녕")])
    candidate = content.create_transcript("session", [Segment("s2", 0, 1000, "candidate")])
    assert content.active_transcript("session")["revision_id"] == first  # type: ignore[index]
    assert content.transcript(candidate)["segments"][0]["text"] == "candidate"
    loaded = content.transcript(first)
    loaded["segments"][0]["text"] = "mutation"
    assert content.transcript(first)["segments"][0]["text"] == "안녕"
    with closing(sqlite3.connect(content.library.db_path)) as db, db:
        with pytest.raises(sqlite3.IntegrityError, match="IMMUTABLE_CONTENT_REVISION"):
            db.execute("UPDATE content_revisions SET body='{}' WHERE revision_id=?", (first,))
        assert db.execute("PRAGMA user_version").fetchone() == (1,)


def test_edits_are_new_user_assertion_and_competing_edit_is_candidate(
    content: ContentStore,
) -> None:
    original = content.create_transcript("session", [Segment("s1", 10, 1000, "준비", "화자")])
    edited = content.edit_segment("session", original, "s1", "승인", expected_active=original)
    conflict = content.edit_segment("session", original, "s1", "미승인", expected_active=original)
    assert content.active_transcript("session")["revision_id"] == edited  # type: ignore[index]
    assert content.transcript(original)["segments"][0]["provenance"] == "audio"
    assert content.transcript(edited)["segments"][0]["provenance"] == "user_assertion"
    assert content.transcript(conflict)["segments"][0]["text"] == "미승인"
    assert content.transcript(edited)["parent_revision_id"] == original
    with pytest.raises(KeyError):
        content.edit_segment("session", edited, "missing", "bad", expected_active=edited)


def test_summary_is_pinned_stale_and_late_summary_cannot_replace(content: ContentStore) -> None:
    t1 = content.create_transcript("session", [Segment("s1", 0, 1, "one")])
    s1 = content.create_summary("session", t1, [Claim("one", ("s1",))], expected_transcript=t1)
    assert content.active_summary("session")["revision_id"] == s1  # type: ignore[index]
    t2 = content.edit_segment("session", t1, "s1", "two", expected_active=t1)
    assert content.summary(s1)["stale"] is True
    s2 = content.create_summary(
        "session", t2, [Claim("two", ("s1",))], expected_transcript=t2, expected_summary=s1
    )
    late = content.create_summary(
        "session", t1, [Claim("old", ("s1",))], expected_transcript=t1, expected_summary=s1
    )
    template = content.create_summary(
        "session",
        t2,
        [Claim("older template", ("s1",))],
        template="lecture",
        expected_transcript=t2,
        expected_summary=s1,
    )
    assert content.active_summary("session")["revision_id"] == s2  # type: ignore[index]
    assert content.summary(s2)["claims"][0]["basis"] == "user_assertion"
    assert content.summary(s2)["stale"] is False
    assert content.summary(late)["stale"] is True
    assert content.summary(template)["template"] == "lecture"


def test_summary_none_expectation_is_not_unconditional_overwrite(content: ContentStore) -> None:
    revision = content.create_transcript("session", [Segment("s", 0, 1, "text")])
    candidate = content.create_summary("session", revision, [Claim("text", ("s",))])
    assert content.active_summary("session") is None
    assert content.summary(candidate)["claims"][0]["status"] == "uncertain"


def test_missing_and_non_audio_evidence_are_distinguished(content: ContentStore) -> None:
    revision = content.create_transcript(
        "session", [Segment("s", 0, 1, "text", provenance="unresolved")]
    )
    with pytest.raises(ValidationError, match="UNKNOWN_CLAIM_SEGMENT"):
        content.create_summary("session", revision, [Claim("bad", ("missing",))])
    summary = content.create_summary(
        "session", revision, [Claim("unclear", ("s",)), Claim("inference", ())]
    )
    claims = content.summary(summary)["claims"]
    assert claims[0]["basis"] == "unresolved" and claims[1]["basis"] == "model_inference"


def test_exports_have_independent_timestamp_and_unicode_oracles(content: ContentStore) -> None:
    revision = content.create_transcript(
        "session",
        [Segment("s", 0, 1, "한글"), Segment("hour", 3_599_999, 3_600_001, "&<tag>\r\n\r\n끝")],
    )
    assert content.export_transcript(revision, "txt") == "한글\n&<tag>\r\n\r\n끝"
    assert content.export_transcript(revision, "srt") == (
        "1\n00:00:00,000 --> 00:00:00,001\n한글\n\n2\n00:59:59,999 --> 01:00:00,001\n&<tag>\n끝\n"
    )
    vtt = content.export_transcript(revision, "vtt")
    assert vtt.startswith("WEBVTT\n\n1\n00:00:00.000 --> 00:00:00.001")
    assert "&amp;&lt;tag&gt;" in vtt
    assert json.loads(content.export_transcript(revision, "json"))["revision_id"] == revision
    with pytest.raises(ValidationError):
        content.export_transcript(revision, "unsupported")


def test_empty_transcript_and_search_match_only_selected_revision(content: ContentStore) -> None:
    assert content.active_transcript("session") is None
    assert content.search("session", "test") == []
    empty = content.create_transcript("session", [])
    assert content.transcript(empty)["complete"] is True
    assert content.export_transcript(empty, "srt") == ""
    assert content.export_transcript(empty, "vtt") == "WEBVTT\n\n"
    current = content.create_transcript(
        "session", [Segment("s", 0, 1, "Hello %_")], expected_active=empty
    )
    content.create_transcript("session", [Segment("candidate", 0, 1, "hidden")])
    assert content.search("session", "HELLO")[0].text == "Hello %_"
    assert content.search("session", "%_")[0].segment_id == "s"
    assert content.search("session", "hidden") == content.search("session", "") == []
    assert content.active_transcript("session")["revision_id"] == current  # type: ignore[index]


def test_reopen_persists_content(tmp_path: Path) -> None:
    with Library(tmp_path) as library:
        library.create_session("session")
        with ContentStore(library) as first:
            revision = first.create_transcript("session", [Segment("s", 1, 2, "persist")])
    with Library(tmp_path) as library, ContentStore(library) as reopened:
        assert reopened.active_transcript("session")["revision_id"] == revision  # type: ignore[index]


def test_two_connections_compete_without_losing_candidate(tmp_path: Path) -> None:
    with Library(tmp_path) as library, ContentStore(library) as a, ContentStore(library) as b:
        library.create_session("session")
        barrier = Barrier(2)

        def write(store: ContentStore) -> str:
            barrier.wait(timeout=5)
            return store.create_transcript("session", [Segment("s", 0, 1, "content")])

        with ThreadPoolExecutor(2) as pool:
            ids = list(pool.map(write, [a, b]))
        assert len(set(ids)) == 2
        assert a.active_transcript("session")["revision_id"] in ids  # type: ignore[index]
        assert all(a.transcript(revision)["segments"] for revision in ids)


def test_delete_cascades_and_pending_intent_blocks_reads_and_writes(content: ContentStore) -> None:
    library = content.library
    revision = content.create_transcript("session", [Segment("s", 0, 1, "private")])
    content.create_summary("session", revision, [Claim("private", ("s",))])
    pcm = PCMBlock("session", "mic", "epoch", 0, AudioFormat(48_000, 1), 1, b"\x01\x00", 0, 0)
    writer = ChunkWriter(library.root, pcm)
    writer.append(pcm)
    assert library.delete_session("session")["deleted"] is False
    with pytest.raises(StateConflict):
        content.transcript(revision)
    with pytest.raises(StateConflict):
        content.create_transcript("session", [])
    writer.abort()
    assert library.delete_session("session")["deleted"] is True
    with closing(sqlite3.connect(library.db_path)) as db:
        for table in ("content_revisions", "content_selections", "content_events"):
            assert db.execute(f"SELECT COUNT(*) FROM {table}").fetchone() == (0,)
    with pytest.raises(KeyError):
        content.transcript(revision)
    with pytest.raises(StateConflict):
        content.create_summary("session", revision, [])


def test_cross_session_parent_and_summary_are_rejected(content: ContentStore) -> None:
    content.library.create_session("other")
    revision = content.create_transcript("session", [Segment("s", 0, 1, "text")])
    with pytest.raises(ValidationError):
        content.create_transcript("other", [], parent_revision_id=revision)
    with pytest.raises(ValidationError):
        content.create_summary("other", revision, [])
    with pytest.raises(ValidationError):
        content.edit_segment("other", revision, "s", "changed", expected_active=revision)
    with pytest.raises(ValidationError):
        content.summary(revision)


@pytest.mark.parametrize(
    "field,value",
    [
        ("start_ms", True),
        ("end_ms", False),
        ("start_ms", -1),
        ("start_ms", 1.0),
        ("end_ms", 2**63),
        ("segment_id", ""),
        ("segment_id", 1),
        ("text", "bad\x00"),
        ("text", "\ud800"),
        ("speaker", ""),
        ("provenance", "verified"),
        ("end_ms", -1),
    ],
)
def test_segment_input_boundaries(field: str, value: Any) -> None:
    values: dict[str, Any] = {"segment_id": "s", "start_ms": 0, "end_ms": 1, "text": "text"}
    values[field] = value
    with pytest.raises(ValidationError):
        Segment(**values)


def test_segment_values_are_frozen_and_intervals_checked() -> None:
    with pytest.raises(ValidationError):
        Segment("s", 2, 1, "text")
    value = Segment("s", 0, 1, "text")
    with pytest.raises(FrozenInstanceError):
        value.text = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    "values",
    [
        {"text": ""},
        {"segment_ids": ["s"]},
        {"segment_ids": ("s", "s")},
        {"segment_ids": (False,)},
        {"status": "supported"},
        {"status": "made-up"},
    ],
)
def test_claim_input_boundaries(values: dict[str, Any]) -> None:
    data: dict[str, Any] = {"text": "text", "segment_ids": ("s",)}
    data.update(values)
    with pytest.raises(ValidationError):
        Claim(**data)


@pytest.mark.parametrize(
    "segments",
    [
        "text",
        b"text",
        [None],
        [Segment("s", 0, 1, "a"), Segment("s", 1, 2, "b")],
        [Segment("a", 2, 3, "a"), Segment("b", 0, 1, "b")],
    ],
)
def test_invalid_segment_sets(content: ContentStore, segments: Any) -> None:
    with pytest.raises(ValidationError):
        content.create_transcript("session", segments)


def test_invalid_kind_expectation_and_claim_collection(content: ContentStore) -> None:
    with pytest.raises(ValidationError):
        content.create_transcript("session", [], kind="unknown")
    with pytest.raises(ValidationError):
        content.create_transcript("session", [], expected_active=True)  # type: ignore[arg-type]
    revision = content.create_transcript("session", [])
    for values in ("text", [None]):
        with pytest.raises(ValidationError):
            content.create_summary("session", revision, values)  # type: ignore[arg-type]


def test_size_failure_rolls_back_and_unknown_revision(
    content: ContentStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    import recoryn.content.store as module

    monkeypatch.setattr(module, "_MAX_REVISION_BYTES", 10)
    with pytest.raises(ValidationError):
        content.create_transcript("session", [Segment("s", 0, 1, "text")])
    assert content.active_transcript("session") is None
    with pytest.raises(KeyError):
        content.transcript("missing")


def test_closed_and_future_schema_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        ContentStore(None)  # type: ignore[arg-type]
    with Library(tmp_path) as library:
        library.create_session("session")
        store = ContentStore(library)
        with closing(sqlite3.connect(library.db_path)) as db:
            db.execute("PRAGMA user_version=2")
        with pytest.raises(ValidationError):
            store.create_transcript("session", [])
        store.close()
        store.close()
        with pytest.raises(StateConflict):
            store.transcript("missing")
        with pytest.raises(ValidationError):
            ContentStore(library)


@pytest.mark.parametrize("kind", ["transcript", "summary"])
@pytest.mark.parametrize("late_binding", [False, True])
@pytest.mark.parametrize("complete", [False, True])
def test_bound_job_cannot_publish_different_session_even_with_preflight_binding_race(
    content: ContentStore,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    late_binding: bool,
    complete: bool,
) -> None:
    content.library.create_session("other")
    source = content.create_transcript("other", [Segment("s", 0, 1, "other source")])
    before = content.list_revisions("other")
    with JobStore(content.library.db_path) as jobs, JobStore(content.library.db_path) as peer:
        job = jobs.create(kind, "bound-source-input")
        attempt = jobs.claim(job.job_id, "worker")
        if late_binding:
            original = content._publication_preflight

            def preflight(store: JobStore, token: AttemptRecord, session: str) -> None:
                original(store, token, session)
                peer.bind_session(job.job_id, "session")

            monkeypatch.setattr(content, "_publication_preflight", preflight)
        else:
            peer.bind_session(job.job_id, "session")
        with pytest.raises(StateConflict, match="CONTENT_JOB_SESSION_MISMATCH"):
            if kind == "transcript":
                content.publish_transcript(
                    jobs, attempt, "other", [Segment("s", 0, 1, "wrong")], complete=complete
                )
            else:
                content.publish_summary(
                    jobs,
                    attempt,
                    "other",
                    source,
                    [Claim("wrong", ("s",))],
                    expected_transcript=source,
                    complete=complete,
                )
        assert content.list_revisions("other") == before
        assert content.list_revisions("session") == []
        assert jobs.get(job.job_id).state == JobState.RUNNING
        assert jobs.get(job.job_id).result_ref is None


@pytest.mark.parametrize("kind", ["transcript", "summary"])
def test_completed_bound_job_replay_cannot_return_result_for_different_session(
    content: ContentStore, kind: str
) -> None:
    content.library.create_session("other")
    source = content.create_transcript("session", [Segment("s", 0, 1, "source")])
    with JobStore(content.library.db_path) as jobs:
        job = jobs.create(kind, "input")
        jobs.bind_session(job.job_id, "session")
        attempt = jobs.claim(job.job_id, "worker")
        if kind == "transcript":
            revision = content.publish_transcript(
                jobs, attempt, "session", [], expected_active=source
            )
        else:
            revision = content.publish_summary(
                jobs, attempt, "session", source, [], expected_transcript=source
            )
        with pytest.raises(StateConflict, match="CONTENT_JOB_SESSION_MISMATCH"):
            if kind == "transcript":
                content.publish_transcript(jobs, attempt, "other", [])
            else:
                content.publish_summary(jobs, attempt, "other", source, [])
        assert jobs.get(job.job_id).result_ref == revision
        assert content.list_revisions("other") == []


@pytest.mark.parametrize("cancel_first", [True, False])
def test_atomic_cancel_completion_orders(content: ContentStore, cancel_first: bool) -> None:
    with JobStore(content.library.db_path) as jobs:
        job = jobs.create("STT", "fixed-input")
        attempt = jobs.claim(job.job_id, "worker")
        if cancel_first:
            jobs.cancel(job.job_id)
            with pytest.raises(StateConflict):
                content.publish_transcript(jobs, attempt, "session", [Segment("s", 0, 1, "text")])
            assert content.list_revisions("session") == []
            assert jobs.get(job.job_id).result_ref is None
        else:
            revision = content.publish_transcript(
                jobs, attempt, "session", [Segment("s", 0, 1, "text")]
            )
            assert jobs.cancel(job.job_id).state == JobState.SUCCEEDED
            assert jobs.get(job.job_id).result_ref == revision
            assert content.active_transcript("session")["revision_id"] == revision  # type: ignore[index]
            assert content.publish_transcript(jobs, attempt, "session", []) == revision
            assert len(content.list_revisions("session")) == 1


def test_atomic_event_failure_rolls_back_all_content(content: ContentStore) -> None:
    path = content.library.db_path
    with JobStore(path) as jobs:
        job = jobs.create("STT", "fixed-input")
        attempt = jobs.claim(job.job_id, "worker")
        before = jobs.get(job.job_id)
        with closing(sqlite3.connect(path)) as db, db:
            db.execute(
                "CREATE TRIGGER publication_fault BEFORE INSERT ON events "
                "BEGIN SELECT RAISE(ABORT,'injected'); END"
            )
        with pytest.raises(sqlite3.IntegrityError):
            content.publish_transcript(jobs, attempt, "session", [Segment("s", 0, 1, "text")])
        assert content.active_transcript("session") is None
        assert content.list_revisions("session") == []
        assert jobs.get(job.job_id) == before
        with closing(sqlite3.connect(path)) as db:
            assert db.execute("SELECT state,result_ref FROM attempts").fetchone() == (
                "RUNNING",
                None,
            )


@pytest.mark.parametrize("edit_first", [True, False])
def test_atomic_job_edit_cas_orders(content: ContentStore, edit_first: bool) -> None:
    original = content.create_transcript("session", [Segment("s", 0, 1, "original")])
    with JobStore(content.library.db_path) as jobs:
        job = jobs.create("STT", "fixed-input")
        attempt = jobs.claim(job.job_id, "worker")
        if edit_first:
            edited = content.edit_segment(
                "session", original, "s", "user", expected_active=original
            )
        machine = content.publish_transcript(
            jobs, attempt, "session", [Segment("s", 0, 1, "machine")], expected_active=original
        )
        if not edit_first:
            edited = content.edit_segment(
                "session", original, "s", "user", expected_active=original
            )
        active = content.active_transcript("session")
        assert active is not None and active["revision_id"] == (edited if edit_first else machine)
        assert content.transcript(edited)["segments"][0]["text"] == "user"
        assert jobs.get(job.job_id).state == JobState.SUCCEEDED


@pytest.mark.parametrize("delete_first", [True, False])
def test_atomic_job_deletion_orders(content: ContentStore, delete_first: bool) -> None:
    with JobStore(content.library.db_path) as jobs:
        job = jobs.create("STT", "fixed-input")
        attempt = jobs.claim(job.job_id, "worker")
        if delete_first:
            assert content.library.delete_session("session")["deleted"] is False
            with pytest.raises(StateConflict):
                content.publish_transcript(jobs, attempt, "session", [])
            assert jobs.get(job.job_id).state == JobState.RUNNING
            jobs.cancel(job.job_id)
            jobs._ack_cancelled(attempt)
        else:
            content.publish_transcript(jobs, attempt, "session", [Segment("s", 0, 1, "private")])
        assert content.library.delete_session("session")["deleted"] is True
        with closing(sqlite3.connect(content.library.db_path)) as db:
            assert db.execute("SELECT COUNT(*) FROM content_revisions").fetchone() == (0,)


def test_partial_checkpoint_preserves_without_selection_or_success(content: ContentStore) -> None:
    with JobStore(content.library.db_path) as jobs:
        job = jobs.create("STT", "fixed-input")
        attempt = jobs.claim(job.job_id, "worker")
        partial = content.publish_transcript(
            jobs, attempt, "session", [Segment("s", 0, 1, "partial")], complete=False
        )
        assert content.transcript(partial)["complete"] is False
        assert content.active_transcript("session") is None
        assert jobs.get(job.job_id).state == JobState.RUNNING
        assert jobs.get(job.job_id).result_ref is None
        jobs.cancel(job.job_id)
        assert content.transcript(partial)["segments"][0]["text"] == "partial"
        with pytest.raises(StateConflict):
            content.publish_transcript(jobs, attempt, "session", [], complete=False)


def test_atomic_summary_and_incomplete_source(content: ContentStore) -> None:
    transcript = content.create_transcript("session", [Segment("s", 0, 1, "source")])
    with JobStore(content.library.db_path) as jobs:
        job = jobs.create("SUMMARY", "fixed-input")
        attempt = jobs.claim(job.job_id, "worker")
        checkpoint = content.publish_summary(
            jobs, attempt, "session", transcript, [Claim("partial", ("s",))], complete=False
        )
        assert not content.summary(checkpoint)["complete"]
        assert content.active_summary("session") is None
        final = content.publish_summary(
            jobs,
            attempt,
            "session",
            transcript,
            [Claim("final", ("s",))],
            expected_transcript=transcript,
        )
        assert content.active_summary("session")["revision_id"] == final  # type: ignore[index]
        assert jobs.get(job.job_id).result_ref == final
        partial = content.create_transcript("session", [], kind="draft")
        second = jobs.create("SUMMARY", "partial-input")
        a2 = jobs.claim(second.job_id, "worker")
        with pytest.raises(ValidationError):
            content.publish_summary(jobs, a2, "session", partial, [])


def test_history_selection_cas_and_session(content: ContentStore) -> None:
    first = content.create_transcript("session", [Segment("a", 0, 1, "first")])
    other = content.create_transcript("session", [Segment("b", 0, 1, "other")])
    assert not content.select_transcript("session", other, expected_active=None)
    assert content.select_transcript("session", other, expected_active=first)
    summary = content.create_summary("session", first, [Claim("old", ("a",))])
    assert content.select_summary("session", summary, expected_active=None)
    assert content.active_summary("session")["stale"] is True  # type: ignore[index]
    assert not content.select_summary("session", summary, expected_active="wrong")
    assert len(content.list_revisions("session", "transcript")) == 2
    assert len(content.list_revisions("session", "corrected")) == 2
    assert len(content.list_revisions("session", "summary")) == 1
    content.library.create_session("other")
    with pytest.raises(ValidationError):
        content.select_transcript("other", first, expected_active=None)
    with pytest.raises(ValidationError):
        content.list_revisions("session", "bad")


def test_track_and_audio_snapshot_edit(content: ContentStore) -> None:
    revision = content.create_transcript(
        "session",
        [Segment("s", 0, 1, "source", track_id="mic", timing_quality="clip")],
        audio_revision_id="a" * 64,
    )
    edited = content.edit_segment("session", revision, "s", "edit", expected_active=revision)
    value = content.transcript(edited)
    assert value["audio_revision_id"] == "a" * 64
    assert value["segments"][0]["track_id"] == "mic"
    assert value["segments"][0]["timing_quality"] == "unverified"


def test_coverage_partial_cannot_finish_job(content: ContentStore) -> None:
    coverage = {
        "schema_version": 1,
        "planned": ["clip-1", "clip-2"],
        "completed": ["clip-1"],
        "failed": ["clip-2"],
        "missing": [],
        "source_ranges": [{"offset_ms": None}],
    }
    revision = content.create_transcript(
        "session", [Segment("s", 0, 1, "partial")], coverage=coverage
    )
    assert content.transcript(revision)["kind"] == "draft"
    assert content.active_transcript("session") is None
    with JobStore(content.library.db_path) as jobs:
        job = jobs.create("STT", "input")
        attempt = jobs.claim(job.job_id, "worker")
        with pytest.raises(ValidationError):
            content.publish_transcript(jobs, attempt, "session", [], coverage=coverage)
        content.publish_transcript(jobs, attempt, "session", [], coverage=coverage, complete=False)
        assert jobs.get(job.job_id).state == JobState.RUNNING


def test_streaming_snapshot_job_success_is_not_final_transcript_ready(
    content: ContentStore,
) -> None:
    with JobStore(content.library.db_path) as jobs:
        job = jobs.create("streaming_transcription", "sealed-snapshot")
        attempt = jobs.claim(job.job_id, "worker")
        revision = content.publish_transcript(
            jobs,
            attempt,
            "session",
            [Segment("s", 0, 1, "draft")],
            kind="draft",
            audio_revision_id="b" * 64,
        )
        assert jobs.get(job.job_id).state == JobState.SUCCEEDED
        assert content.transcript(revision)["complete"] is False
        assert content.active_transcript("session")["revision_id"] == revision  # type: ignore[index]


@pytest.mark.parametrize(
    "changes",
    [
        {"schema_version": True},
        {"extra": 1},
        {"planned": "bad"},
        {"completed": ["a", "a"]},
        {"completed": ["outside"]},
        {"failed": ["a"]},
        {"missing": ["a"]},
        {"missing": [None]},
        {"source_ranges": "bad"},
        {"source_ranges": [{"bad": object()}]},
    ],
)
def test_coverage_validation_never_changes_active(
    content: ContentStore, changes: dict[str, Any]
) -> None:
    coverage = {"schema_version": 1, "planned": ["a"], "completed": ["a"], "failed": []}
    coverage.update(changes)
    with pytest.raises(ValidationError):
        content.create_transcript("session", [], coverage=coverage)
    assert content.active_transcript("session") is None


def test_coverage_missing_and_defensive_copy(content: ContentStore) -> None:
    coverage: dict[str, Any] = {
        "schema_version": 1,
        "planned": ["a", "b"],
        "completed": ["a"],
        "failed": [],
        "source_ranges": [{"offset_ms": None}],
    }
    revision = content.create_transcript("session", [], coverage=coverage)
    coverage["source_ranges"][0]["offset_ms"] = 99
    body = content.transcript(revision)
    assert body["coverage"]["missing"] == ["b"]
    assert body["coverage"]["source_ranges"] == [{"offset_ms": None}]
    assert body["complete"] is False
    with pytest.raises(ValidationError):
        Segment("bad", 0, 1, "text", timing_quality="fake")
    content.create_transcript(
        "session",
        [
            Segment("a", 10, 20, "a", track_id="mic"),
            Segment("b", 0, 5, "b", track_id="system"),
            Segment("c", 0, 1, "c", track_id="mic", timing_quality="unverified"),
        ],
    )


@pytest.mark.parametrize("corruption", ["hash", "schema", "json"])
def test_corrupt_content_safe_code(content: ContentStore, corruption: str) -> None:
    import hashlib

    revision = content.create_transcript("session", [])
    with closing(sqlite3.connect(content.library.db_path)) as db, db:
        db.execute("DROP TRIGGER content_revision_immutable")
        value = "{}" if corruption != "json" else "{"
        checksum = "bad" if corruption == "hash" else hashlib.sha256(value.encode()).hexdigest()
        db.execute(
            "UPDATE content_revisions SET body=?,sha256=? WHERE revision_id=?",
            (value, checksum, revision),
        )
    with pytest.raises(ValidationError, match="CONTENT_REVISION_(INTEGRITY|SCHEMA)"):
        content.transcript(revision)


def test_publication_context_guards(content: ContentStore, tmp_path: Path) -> None:
    with JobStore(content.library.db_path) as jobs, JobStore(tmp_path / "other.sqlite") as other:
        job = jobs.create("STT", "input")
        attempt = jobs.claim(job.job_id, "worker")
        with pytest.raises(ValidationError):
            content.publish_transcript(other, attempt, "session", [])
        with pytest.raises(ValidationError):
            content.publish_transcript(jobs, None, "session", [])  # type: ignore[arg-type]
        with pytest.raises(ValidationError):
            content.publish_transcript(None, attempt, "session", [])  # type: ignore[arg-type]
        with pytest.raises(ValidationError):
            content.publish_transcript(jobs, attempt, "session", [], kind="draft")
        with pytest.raises(ValidationError):
            content.publish_summary(jobs, attempt, "session", "missing", [], complete=1)  # type: ignore[arg-type]


def test_uncommitted_content_invisible_and_cancel_waits(
    content: ContentStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    from threading import Event

    path = content.library.db_path
    with JobStore(path) as jobs, JobStore(path) as canceller:
        job = jobs.create("STT", "input")
        attempt = jobs.claim(job.job_id, "worker")
        wrote, release, cancelling = Event(), Event(), Event()
        original = content._save

        def held_save(
            connection: sqlite3.Connection, body: dict[str, Any], revision_type: str, selected: bool
        ) -> None:
            original(connection, body, revision_type, selected)
            wrote.set()
            assert release.wait(5)

        monkeypatch.setattr(content, "_save", held_save)

        def cancel() -> Any:
            cancelling.set()
            return canceller.cancel(job.job_id)

        with ThreadPoolExecutor(2) as pool:
            publishing = pool.submit(content.publish_transcript, jobs, attempt, "session", [])
            assert wrote.wait(5)
            with closing(sqlite3.connect(path)) as observer:
                assert observer.execute("SELECT COUNT(*) FROM content_revisions").fetchone() == (0,)
                assert observer.execute("SELECT state FROM jobs").fetchone() == ("RUNNING",)
            waiting = pool.submit(cancel)
            assert cancelling.wait(5) and not waiting.done()
            release.set()
            revision = publishing.result(timeout=5)
            assert waiting.result(timeout=5).state == JobState.SUCCEEDED
        assert jobs.get(job.job_id).result_ref == revision


def test_atomic_summary_late_candidate(content: ContentStore) -> None:
    t1 = content.create_transcript("session", [Segment("s", 0, 1, "one")])
    with JobStore(content.library.db_path) as jobs:
        job = jobs.create("SUMMARY", "old-input")
        attempt = jobs.claim(job.job_id, "worker")
        t2 = content.edit_segment("session", t1, "s", "two", expected_active=t1)
        selected = content.create_summary(
            "session", t2, [Claim("two", ("s",))], expected_transcript=t2
        )
        late = content.publish_summary(
            jobs, attempt, "session", t1, [Claim("one", ("s",))], expected_transcript=t1
        )
        assert content.summary(late)["stale"] is True
        assert content.active_summary("session")["revision_id"] == selected  # type: ignore[index]
        assert jobs.get(job.job_id).state == JobState.SUCCEEDED


def test_checkpoint_is_json_copied_and_bounded(
    content: ContentStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkpoint: dict[str, Any] = {"config_key": "config", "chunks": [{"claims": ["preserved"]}]}
    coverage = {
        "schema_version": 1,
        "planned": ["a"],
        "completed": [],
        "failed": [],
        "checkpoint": checkpoint,
    }
    revision = content.create_transcript("session", [], coverage=coverage)
    checkpoint["chunks"][0]["claims"].append("mutation")
    assert content.transcript(revision)["coverage"]["checkpoint"]["chunks"][0]["claims"] == [
        "preserved"
    ]
    invalid_values: list[Any] = [[], {"bad": object()}, {"nan": float("nan")}]
    for invalid in invalid_values:
        with pytest.raises(ValidationError):
            content.create_transcript("session", [], coverage={**coverage, "checkpoint": invalid})
    import recoryn.content.store as module

    monkeypatch.setattr(module, "_MAX_REVISION_BYTES", 10)
    with pytest.raises(ValidationError):
        content.create_transcript("session", [], coverage=coverage)


# G03 selection version CAS: value validation and storage contract.
# Case IDs follow docs/testing/g03-selection-version-cases.md.


def _g03_attempt(jobs: JobStore, kind: str = "SUMMARY") -> AttemptRecord:
    from uuid import uuid4

    job = jobs.create(kind, uuid4().hex)
    jobs.bind_session(job.job_id, "session")
    return jobs.claim(job.job_id, "g03")


@pytest.mark.parametrize(
    "version",
    [-1, 2**63, True, 1.0, "1"],
    ids=["G03-V-minus1", "G03-V-2pow63", "G03-V-bool", "G03-V-float", "G03-V-text"],
)
def test_g03_invalid_selection_versions_are_rejected(content: ContentStore, version: Any) -> None:
    t1 = content.create_transcript("session", [Segment("s", 0, 1, "one")])
    with JobStore(content.library.db_path) as jobs:
        attempt = _g03_attempt(jobs)
        with pytest.raises(ValidationError):
            content.publish_transcript(
                jobs,
                attempt,
                "session",
                [Segment("n", 0, 1, "new")],
                expected_active=t1,
                expected_transcript_version=version,
            )
        for name in ("expected_transcript_version", "expected_summary_version"):
            with pytest.raises(ValidationError):
                content.publish_summary(
                    jobs,
                    attempt,
                    "session",
                    t1,
                    [Claim("claim", ("s",))],
                    expected_transcript=t1,
                    **{name: version},
                )
        assert jobs.get(attempt.job_id).state is JobState.RUNNING
    assert [item["revision_id"] for item in content.list_revisions("session")] == [t1]


@pytest.mark.parametrize(
    ("version", "selected"),
    [(0, False), (1, True), (2**63 - 1, False)],
    ids=["G03-V-0", "G03-V-1", "G03-V-max"],
)
def test_g03_version_boundaries_select_only_on_equality(
    content: ContentStore, version: int, selected: bool
) -> None:
    t1 = content.create_transcript("session", [Segment("s", 0, 1, "one")])
    assert content.selection_state("session")["transcript_version"] == 1  # one selection so far
    with JobStore(content.library.db_path) as jobs:
        attempt = _g03_attempt(jobs, "TRANSCRIPTION")
        revision = content.publish_transcript(
            jobs,
            attempt,
            "session",
            [Segment("n", 0, 1, "new")],
            expected_active=t1,
            expected_transcript_version=version,
        )
    assert (content.selection_state("session")["transcript_id"] == revision) is selected


@pytest.mark.parametrize(
    "key",
    ["", "   ", "x" * 257, "a\x00b"],
    ids=["G03-K-empty", "G03-K-blank", "G03-K-257", "G03-K-nul"],
)
def test_g03_invalid_settings_keys_are_rejected(content: ContentStore, key: str) -> None:
    t1 = content.create_transcript("session", [Segment("s", 0, 1, "one")])
    with pytest.raises(ValidationError):
        content.request_summary_settings("session", key)
    with JobStore(content.library.db_path) as jobs:
        attempt = _g03_attempt(jobs)
        with pytest.raises(ValidationError):
            content.publish_summary(
                jobs, attempt, "session", t1, [Claim("claim", ("s",))], settings_key=key
            )
    assert content.selection_state("session")["summary_settings_key"] is None


@pytest.mark.parametrize(
    "key",
    [None, "", "x" * 257],
    ids=["G03-KR-none", "G03-KR-empty", "G03-KR-257"],
)
def test_g03_required_settings_key_is_validated_before_sql(content: ContentStore, key: Any) -> None:
    # request_summary_settings requires a key; only publish_summary keeps None as LEGACY.
    content.request_summary_settings("session", "known")
    with pytest.raises(ValidationError):
        content.request_summary_settings("session", key)
    assert _g03_requests(content.library.db_path) == [("session", "known", 1)]
    assert content.selection_state("session")["summary_settings_key"] == "known"


@pytest.mark.parametrize("key", ["x" * 256, "k"], ids=["G03-K-256", "G03-K-short"])
def test_g03_settings_key_boundaries_are_stored_and_published(
    content: ContentStore, key: str
) -> None:
    t1 = content.create_transcript("session", [Segment("s", 0, 1, "one")])
    content.request_summary_settings("session", key)
    assert content.selection_state("session")["summary_settings_key"] == key
    with JobStore(content.library.db_path) as jobs:
        attempt = _g03_attempt(jobs)
        revision = content.publish_summary(
            jobs,
            attempt,
            "session",
            t1,
            [Claim("claim", ("s",))],
            expected_transcript=t1,
            settings_key=key,
        )
    assert content.summary(revision)["settings_key"] == key
    assert content.active_summary("session")["revision_id"] == revision  # type: ignore[index]


def test_g03_selection_state_defaults_for_a_session_without_content(content: ContentStore) -> None:
    assert content.selection_state("session") == {
        "session_id": "session",
        "transcript_id": None,
        "transcript_version": 0,
        "summary_id": None,
        "summary_version": 0,
        "summary_settings_key": None,
    }


def _g03_requests(path: Path) -> list[tuple[Any, ...]]:
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as raw:
        return raw.execute("SELECT * FROM content_summary_requests").fetchall()


def test_g03_pre_g03_database_gains_the_table_and_reopen_is_idempotent(tmp_path: Path) -> None:
    with Library(tmp_path) as library:
        library.create_session("session")
        with ContentStore(library) as store:
            t1 = store.create_transcript("session", [Segment("s", 0, 1, "one")])
        with closing(sqlite3.connect(library.db_path)) as raw, raw:
            raw.execute("DROP TABLE content_summary_requests")  # a database written before G03
        with ContentStore(library) as store:
            assert store.selection_state("session")["summary_settings_key"] is None
            assert store.selection_state("session")["transcript_id"] == t1
            store.request_summary_settings("session", "k")
        first = _g03_requests(library.db_path)
        with ContentStore(library) as store, ContentStore(library) as again:
            assert store.selection_state("session") == again.selection_state("session")
        assert _g03_requests(library.db_path) == first == [("session", "k", 1)]
        with closing(sqlite3.connect(library.db_path.as_uri() + "?mode=ro", uri=True)) as raw:
            assert raw.execute("PRAGMA user_version").fetchone()[0] == 1


def test_g03_requests_count_without_moving_selection_versions(content: ContentStore) -> None:
    t1 = content.create_transcript("session", [Segment("s", 0, 1, "one")])
    content.create_summary("session", t1, [Claim("one", ("s",))], expected_transcript=t1)
    before = content.selection_state("session")
    content.request_summary_settings("session", "a")
    content.request_summary_settings("session", "b")
    after = content.selection_state("session")
    assert {key: value for key, value in after.items() if key != "summary_settings_key"} == {
        key: value for key, value in before.items() if key != "summary_settings_key"
    }
    assert after["summary_settings_key"] == "b"
    assert _g03_requests(content.library.db_path) == [("session", "b", 2)]


def test_g03_legacy_publication_records_no_settings_key(content: ContentStore) -> None:
    t1 = content.create_transcript("session", [Segment("s", 0, 1, "one")])
    with JobStore(content.library.db_path) as jobs:
        attempt = _g03_attempt(jobs)
        revision = content.publish_summary(
            jobs, attempt, "session", t1, [Claim("claim", ("s",))], expected_transcript=t1
        )
    assert "settings_key" not in content.summary(revision)


def test_g03_session_deletion_cascades_requested_settings(content: ContentStore) -> None:
    content.request_summary_settings("session", "k")
    assert content.library.delete_session("session")["deleted"]
    assert _g03_requests(content.library.db_path) == []


def test_g03_deletion_intent_blocks_a_settings_request(content: ContentStore) -> None:
    with JobStore(content.library.db_path) as jobs:
        _g03_attempt(jobs)
        assert content.library.delete_session("session")["state"] == "DELETE_PENDING"
        with pytest.raises(StateConflict):
            content.request_summary_settings("session", "k")
    assert _g03_requests(content.library.db_path) == []


def test_g03_second_connection_reads_the_same_selection_state(content: ContentStore) -> None:
    t1 = content.create_transcript("session", [Segment("s", 0, 1, "one")])
    content.request_summary_settings("session", "k")
    with ContentStore(content.library) as other:
        assert other.selection_state("session") == content.selection_state("session")
        assert other.select_transcript("session", t1, expected_active=t1)
        assert content.selection_state("session")["transcript_version"] == 2
