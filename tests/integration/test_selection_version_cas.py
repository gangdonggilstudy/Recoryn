"""G03 selection version CAS (architecture-v1, metadata and artifact versions).

Expected outcomes are closed predicates and hand-computed order tables written
from the design text: a late result is selected only while both selection
versions and the requested summary settings are unchanged since it was planned.
They never reuse the store's selection expression. Real SQLite and temporary
files only; no device, model or network. Case IDs follow
docs/testing/g03-selection-version-cases.md.
"""

from __future__ import annotations

import itertools
import os
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from recoryn.app.ai import AIService
from recoryn.app.media import prepare_clips
from recoryn.app.recording import RecordingService
from recoryn.content import Claim, ContentStore, Segment
from recoryn.domain import AudioFormat, PCMBlock, StateConflict
from recoryn.jobs import AttemptRecord, JobState, JobStore
from recoryn.providers import (
    ProviderCapabilities,
    SegmentSpan,
    STTResult,
    SummaryCheckpoint,
    SummaryClaim,
    SummaryResult,
    TranscriptSegment,
)
from recoryn.storage import Library

pytestmark = pytest.mark.integration

SESSION = "s"
JOB_KEY, NEWER_KEY = "settings-k1", "settings-k2"
T_HISTORIES = ("T0", "AWAY", "ABA", "EDIT")
S_HISTORIES = ("S0", "AWAY", "ABA", "PUB")
SETTINGS = ("NONE", "SAME", "NEWER")
MODES = ("VER", "LEGACY")
KINDS = ("corrected", "streaming", "partial")


@dataclass
class World:
    library: Library
    content: ContentStore
    jobs: JobStore
    t1: str
    t2: str
    s1: str
    s2: str

    def state(self) -> dict[str, Any]:
        return self.content.selection_state(SESSION)

    def claim(self, kind: str = "summarization") -> AttemptRecord:
        job = self.jobs.create(kind, uuid4().hex)
        self.jobs.bind_session(job.job_id, SESSION)
        return self.jobs.claim(job.job_id, "g03")

    def revision_rows(self) -> int:
        uri = self.library.db_path.as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            return int(connection.execute("SELECT COUNT(*) FROM content_revisions").fetchone()[0])


@contextmanager
def world(tmp_path: Path) -> Iterator[World]:
    """T1/S1 selected; T2 and S2 exist as unselected candidates of the same session."""
    with Library(tmp_path / "library") as library:
        library.create_session(SESSION)
        with ContentStore(library) as content, JobStore(library.db_path) as jobs:
            t1 = content.create_transcript(SESSION, [Segment("a", 0, 10, "one")])
            t2 = content.create_transcript(SESSION, [Segment("a", 0, 10, "two")])
            s1 = content.create_summary(SESSION, t1, [Claim("one", ("a",))], expected_transcript=t1)
            s2 = content.create_summary(SESSION, t1, [Claim("alt", ("a",))], expected_transcript=t1)
            current = content.selection_state(SESSION)
            assert (current["transcript_id"], current["summary_id"]) == (t1, s1)
            yield World(library, content, jobs, t1, t2, s1, s2)


def transcript_history(w: World, name: str) -> None:
    if name in {"AWAY", "ABA"}:
        assert w.content.select_transcript(SESSION, w.t2, expected_active=w.t1)
    if name == "ABA":
        assert w.content.select_transcript(SESSION, w.t1, expected_active=w.t2)
    if name == "EDIT":
        w.content.edit_segment(SESSION, w.t1, "a", "user text", expected_active=w.t1)


def summary_history(w: World, name: str) -> None:
    if name in {"AWAY", "ABA"}:
        assert w.content.select_summary(SESSION, w.s2, expected_active=w.s1)
    if name == "ABA":
        assert w.content.select_summary(SESSION, w.s1, expected_active=w.s2)
    if name == "PUB":
        other = w.claim()
        current = w.state()["transcript_id"]
        published = w.content.publish_summary(
            w.jobs,
            other,
            SESSION,
            current,
            [Claim("other job", ("a",))],
            expected_transcript=current,
            expected_summary=w.s1,
        )
        assert w.state()["summary_id"] == published


def publish_summary(
    w: World,
    attempt: AttemptRecord,
    captured: dict[str, Any],
    mode: str,
    *,
    key: str | None = JOB_KEY,
    complete: bool = True,
) -> str:
    extra: dict[str, Any] = {}
    if mode == "VER":
        extra = {
            "expected_transcript_version": captured["transcript_version"],
            "expected_summary_version": captured["summary_version"],
            "settings_key": key,
        }
    return w.content.publish_summary(
        w.jobs,
        attempt,
        SESSION,
        captured["transcript_id"],
        [Claim("late result", ("a",))],
        complete=complete,
        expected_transcript=captured["transcript_id"],
        expected_summary=captured["summary_id"],
        **extra,
    )


def selected_by_design(ht: str, hs: str, settings: str, mode: str) -> bool:
    """Design oracle. LEGACY documents today's ID-only behaviour, kept for old callers."""
    if mode == "VER":
        return ht == "T0" and hs == "S0" and settings != "NEWER"
    return ht in {"T0", "ABA"} and hs in {"S0", "ABA"}


CUBE = [
    pytest.param(*values, id="G03-S-" + "-".join(values))
    for values in itertools.product(T_HISTORIES, S_HISTORIES, SETTINGS, MODES)
]
REDUCED = list(itertools.product(T_HISTORIES, S_HISTORIES))
PARTIAL = [pytest.param(*pair, id="G03-SP-" + "-".join(pair)) for pair in REDUCED]
CANCELLED = [pytest.param(*pair, id="G03-SC-" + "-".join(pair)) for pair in REDUCED]
DELETED = [pytest.param(*pair, id="G03-SD-" + "-".join(pair)) for pair in REDUCED]
TRANSCRIPT_CUBE = [
    pytest.param(*values, id="G03-T-" + "-".join(values))
    for values in itertools.product(T_HISTORIES, MODES, KINDS)
]


def planned(w: World, settings: str) -> tuple[AttemptRecord, dict[str, Any]]:
    if settings != "NONE":
        w.content.request_summary_settings(SESSION, JOB_KEY)
    attempt = w.claim()
    return attempt, w.state()


@pytest.mark.parametrize(("ht", "hs", "settings", "mode"), CUBE)
def test_summary_publication_decision_cube(
    tmp_path: Path, ht: str, hs: str, settings: str, mode: str
) -> None:
    with world(tmp_path) as w:
        attempt, captured = planned(w, settings)
        transcript_history(w, ht)
        summary_history(w, hs)
        if settings == "NEWER":
            w.content.request_summary_settings(SESSION, NEWER_KEY)
        before = w.state()
        revision = publish_summary(w, attempt, captured, mode)
        after = w.state()
        result = w.content.summary(revision)
        assert result["transcript_revision_id"] == w.t1
        assert result["transcript_hash"] == w.content.transcript(w.t1)["content_hash"]
        assert result.get("settings_key") == (JOB_KEY if mode == "VER" else None)
        assert w.jobs.get(attempt.job_id).state is JobState.SUCCEEDED
        if selected_by_design(ht, hs, settings, mode):
            assert after["summary_id"] == revision
            assert after["summary_version"] == before["summary_version"] + 1
            assert after["transcript_id"] == before["transcript_id"]
            assert after["transcript_version"] == before["transcript_version"]
        else:
            assert after == before, "a late result replaced the current selection"


@pytest.mark.parametrize(("ht", "hs"), PARTIAL)
def test_partial_result_is_never_selected(tmp_path: Path, ht: str, hs: str) -> None:
    with world(tmp_path) as w:
        attempt, captured = planned(w, "SAME")
        transcript_history(w, ht)
        summary_history(w, hs)
        before = w.state()
        revision = publish_summary(w, attempt, captured, "VER", complete=False)
        assert w.state() == before
        assert w.content.summary(revision)["complete"] is False
        assert w.jobs.get(attempt.job_id).state is JobState.RUNNING


@pytest.mark.parametrize(("ht", "hs"), CANCELLED)
def test_cancelled_job_cannot_publish(tmp_path: Path, ht: str, hs: str) -> None:
    with world(tmp_path) as w:
        attempt, captured = planned(w, "SAME")
        transcript_history(w, ht)
        summary_history(w, hs)
        w.jobs.cancel(attempt.job_id)
        before, rows = w.state(), w.revision_rows()
        with pytest.raises(StateConflict):
            publish_summary(w, attempt, captured, "VER")
        assert (w.state(), w.revision_rows()) == (before, rows)


@pytest.mark.parametrize(("ht", "hs"), DELETED)
def test_deleted_session_cannot_receive_late_result(tmp_path: Path, ht: str, hs: str) -> None:
    with world(tmp_path) as w:
        attempt, captured = planned(w, "SAME")
        transcript_history(w, ht)
        summary_history(w, hs)
        rows = w.revision_rows()
        assert w.library.delete_session(SESSION)["state"] == "DELETE_PENDING"
        with pytest.raises(StateConflict):
            publish_summary(w, attempt, captured, "VER")
        assert w.revision_rows() == rows


@pytest.mark.parametrize(("ht", "mode", "kind"), TRANSCRIPT_CUBE)
def test_transcript_publication_cube(tmp_path: Path, ht: str, mode: str, kind: str) -> None:
    with world(tmp_path) as w:
        attempt = w.claim("streaming_transcription" if kind == "streaming" else "transcription")
        captured = w.state()
        transcript_history(w, ht)
        before = w.state()
        extra = {"expected_transcript_version": captured["transcript_version"]}
        revision = w.content.publish_transcript(
            w.jobs,
            attempt,
            SESSION,
            [Segment("n", 0, 10, "new result")],
            complete=kind != "partial",
            kind="corrected" if kind == "corrected" else "draft",
            expected_active=captured["transcript_id"],
            **(extra if mode == "VER" else {}),
        )
        after = w.state()
        if mode == "VER":
            expected = kind != "partial" and ht == "T0"
        else:
            expected = kind != "partial" and ht in {"T0", "ABA"}
        if expected:
            assert after["transcript_id"] == revision
            assert after["transcript_version"] == before["transcript_version"] + 1
            assert (after["summary_id"], after["summary_version"]) == (
                before["summary_id"],
                before["summary_version"],
            )
        else:
            assert after == before
        assert w.jobs.get(attempt.job_id).state is (
            JobState.RUNNING if kind == "partial" else JobState.SUCCEEDED
        )


def linear_extensions(*chains: tuple[str, ...]) -> set[tuple[str, ...]]:
    events = [event for chain in chains for event in chain]
    return {
        order
        for order in itertools.permutations(events)
        if all(
            order.index(chain[i]) < order.index(chain[i + 1])
            for chain in chains
            for i in range(len(chain) - 1)
        )
    }


# order -> (late result selected right after P, first user CAS, second user CAS, final)
HB1 = {
    ("C", "P", "s1", "s2"): (True, False, False, "P"),
    ("C", "s1", "P", "s2"): (False, True, True, "S1"),
    ("C", "s1", "s2", "P"): (False, True, True, "S1"),
    ("s1", "C", "P", "s2"): (True, True, False, "P"),
    ("s1", "C", "s2", "P"): (False, True, True, "S1"),
    ("s1", "s2", "C", "P"): (True, True, True, "P"),
}
HB2 = {
    ("C", "P", "t1", "t2"): (True, True, True, "P"),
    ("C", "t1", "P", "t2"): (False, True, True, "S1"),
    ("C", "t1", "t2", "P"): (False, True, True, "S1"),
    ("t1", "C", "P", "t2"): (True, True, True, "P"),
    ("t1", "C", "t2", "P"): (False, True, True, "S1"),
    ("t1", "t2", "C", "P"): (True, True, True, "P"),
}
HB3 = {("r", "C1", "P1"): True, ("C1", "r", "P1"): False, ("C1", "P1", "r"): True}
HB4 = {
    ("C1", "C2", "P1", "P2"): "J2",
    ("C1", "C2", "P2", "P1"): "J2",
    ("C1", "P1", "C2", "P2"): "J2",
    ("C2", "C1", "P1", "P2"): "J1",
    ("C2", "C1", "P2", "P1"): "J1",
    ("C2", "P2", "C1", "P1"): "J1",
}


def run_order(
    w: World, order: tuple[str, ...], user: dict[str, Callable[[], bool]]
) -> tuple[bool, dict[str, bool], str]:
    attempt: AttemptRecord | None = None
    captured: dict[str, Any] = {}
    revision, selected, returns = "", False, {}
    for event in order:
        if event == "C":
            attempt, captured = w.claim(), w.state()
        elif event == "P":
            assert attempt is not None
            revision = publish_summary(w, attempt, captured, "VER", key=None)
            selected = w.state()["summary_id"] == revision
        else:
            returns[event] = user[event]()
    return selected, returns, revision


@pytest.mark.parametrize("order", list(HB1), ids=lambda o: "G03-HB1-" + "-".join(o))
def test_hb1_summary_selection_orders(tmp_path: Path, order: tuple[str, ...]) -> None:
    with world(tmp_path) as w:
        user = {
            "s1": lambda: w.content.select_summary(SESSION, w.s2, expected_active=w.s1),
            "s2": lambda: w.content.select_summary(SESSION, w.s1, expected_active=w.s2),
        }
        selected, returns, revision = run_order(w, order, user)
        expected_selected, first, second, final = HB1[order]
        assert (selected, returns["s1"], returns["s2"]) == (expected_selected, first, second)
        assert w.state()["summary_id"] == (revision if final == "P" else w.s1)


@pytest.mark.parametrize("order", list(HB2), ids=lambda o: "G03-HB2-" + "-".join(o))
def test_hb2_transcript_selection_orders(tmp_path: Path, order: tuple[str, ...]) -> None:
    with world(tmp_path) as w:
        user = {
            "t1": lambda: w.content.select_transcript(SESSION, w.t2, expected_active=w.t1),
            "t2": lambda: w.content.select_transcript(SESSION, w.t1, expected_active=w.t2),
        }
        selected, returns, revision = run_order(w, order, user)
        expected_selected, first, second, final = HB2[order]
        assert (selected, returns["t1"], returns["t2"]) == (expected_selected, first, second)
        assert w.state()["summary_id"] == (revision if final == "P" else w.s1)


@pytest.mark.parametrize("order", list(HB3), ids=lambda o: "G03-HB3-" + "-".join(o))
def test_hb3_newer_settings_request(tmp_path: Path, order: tuple[str, ...]) -> None:
    with world(tmp_path) as w:
        attempt: AttemptRecord | None = None
        captured: dict[str, Any] = {}
        revision = ""
        for event in order:
            if event == "C1":
                w.content.request_summary_settings(SESSION, JOB_KEY)
                attempt, captured = w.claim(), w.state()
            elif event == "r":
                w.content.request_summary_settings(SESSION, NEWER_KEY)
            else:
                assert attempt is not None
                revision = publish_summary(w, attempt, captured, "VER", key=JOB_KEY)
                assert (w.state()["summary_id"] == revision) is HB3[order]
        assert w.state()["summary_id"] == (revision if HB3[order] else w.s1)


def two_jobs(w: World, order: tuple[str, ...], *, versioned: bool) -> tuple[dict[str, str], str]:
    attempts: dict[str, AttemptRecord] = {}
    captured: dict[str, dict[str, Any]] = {}
    revisions: dict[str, str] = {}
    keys = {"1": JOB_KEY, "2": NEWER_KEY}
    for event in order:
        index = event[1]
        if event[0] == "C":
            if versioned:
                w.content.request_summary_settings(SESSION, keys[index])
            attempts[index], captured[index] = w.claim(), w.state()
        else:
            revisions["J" + index] = publish_summary(
                w,
                attempts[index],
                captured[index],
                "VER" if versioned else "LEGACY",
                key=keys[index],
            )
    return revisions, w.state()["summary_id"]


@pytest.mark.parametrize("order", list(HB4), ids=lambda o: "G03-HB4-" + "-".join(o))
def test_hb4_latest_settings_request_wins(tmp_path: Path, order: tuple[str, ...]) -> None:
    with world(tmp_path) as w:
        revisions, active = two_jobs(w, order, versioned=True)
        assert active == revisions[HB4[order]]


def test_hb4_legacy_contrast_older_request_wins(tmp_path: Path) -> None:
    """G03-HB4-LEGACY: ID-only callers let the job finishing first take the selection."""
    with world(tmp_path) as w:
        revisions, active = two_jobs(w, ("C1", "C2", "P1", "P2"), versioned=False)
        assert active == revisions["J1"]


def test_hb5_selection_moved_by_another_connection(tmp_path: Path) -> None:
    """G03-HB5: HB1 order 3 where the user selections use a second connection."""
    with world(tmp_path) as w, ContentStore(w.library) as other:
        attempt, captured = w.claim(), w.state()
        assert other.select_summary(SESSION, w.s2, expected_active=w.s1)
        assert other.select_summary(SESSION, w.s1, expected_active=w.s2)
        revision = publish_summary(w, attempt, captured, "VER", key=None)
        assert w.state()["summary_id"] == other.selection_state(SESSION)["summary_id"] == w.s1
        assert w.content.summary(revision)["revision_id"] == revision


def test_declared_denominators_are_complete_and_unique() -> None:
    summary_ids = [param.id for param in CUBE + PARTIAL + CANCELLED + DELETED]
    assert len(CUBE) == 4 * 4 * 3 * 2 == 96
    assert len(summary_ids) == len(set(summary_ids)) == 96 + 3 * 16
    assert len({param.id for param in TRANSCRIPT_CUBE}) == 4 * 2 * 3 == 24
    assert set(HB1) == linear_extensions(("C", "P"), ("s1", "s2"))
    assert set(HB2) == linear_extensions(("C", "P"), ("t1", "t2"))
    assert set(HB3) == linear_extensions(("C1", "P1"), ("r",))
    assert set(HB4) == linear_extensions(("C1", "P1"), ("C2", "P2"))
    # HB1 6 + HB2 6 + HB3 3 + HB4 6 + LEGACY contrast 1 + HB5 1
    assert len(HB1) + len(HB2) + len(HB3) + len(HB4) + 2 == 23


# Application paths: AIService captures and records; providers are fakes.


def record(library: Library) -> str:
    fmt = AudioFormat(48000, 1)
    service = RecordingService(library, {"mic": fmt})
    service.start()
    assert service.submit(
        PCMBlock(
            service.session_id,
            "mic",
            service.epochs["mic"],
            0,
            fmt,
            48000,
            b"\x00\x40" * 48000,
            1_000_000_000,
            1_000_000_000,
            device_frame_position=0,
        )
    )
    service.stop()
    return service.session_id


class GatedSummary:
    """Blocks only its first call until released; later calls return at once."""

    def __init__(self) -> None:
        self.entered, self.release = threading.Event(), threading.Event()
        self.calls = 0

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities("fake", summarization=True)

    def summarize(self, request: Any, context: Any = None) -> SummaryResult:
        self.calls += 1
        if self.calls == 1:
            self.entered.set()
            assert self.release.wait(5)
        refs = tuple(item.segment_id for item in request.segments)
        coverage = tuple(
            SegmentSpan(item.segment_id, 0, len(item.text)) for item in request.segments
        )
        return SummaryResult(
            "fake",
            "model",
            request.transcript_revision_id,
            (SummaryClaim("claim", refs),),
            coverage,
            (),
            True,
            SummaryCheckpoint("a" * 64),
        )


class GatedSTT:
    def __init__(self) -> None:
        self.entered, self.release = threading.Event(), threading.Event()

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities("fake", transcription=True)

    def transcribe(self, request: Any, context: Any = None) -> STTResult:
        self.entered.set()
        assert self.release.wait(5)
        item = TranscriptSegment(
            "late", request.offset_ms, request.offset_ms + 500, "late", track_id=request.track_id
        )
        return STTResult("fake", "model", (item,), True, processed_ms=1000)


@dataclass
class App:
    library: Library
    content: ContentStore
    service: AIService
    session: str
    t1: str
    t2: str
    s1: str
    s2: str


@contextmanager
def app_world(tmp_path: Path, *, capacity: int = 8) -> Iterator[App]:
    with Library(tmp_path / "library") as library, ContentStore(library) as content:
        session = record(library)
        t1 = content.create_transcript(session, [Segment("a", 0, 500, "one", track_id="mic")])
        t2 = content.create_transcript(session, [Segment("a", 0, 500, "two", track_id="mic")])
        s1 = content.create_summary(session, t1, [Claim("one", ("a",))], expected_transcript=t1)
        s2 = content.create_summary(session, t1, [Claim("alt", ("a",))], expected_transcript=t1)
        service = AIService(library, content, capacity=capacity)
        try:
            yield App(library, content, service, session, t1, t2, s1, s2)
        finally:
            service.close()


def finished(service: AIService, job_id: str) -> Any:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = service.jobs.get(job_id)
        if job.state.value in {"SUCCEEDED", "FAILED", "CANCELLED", "BLOCKED"}:
            return job
        time.sleep(0.005)
    pytest.fail("AI job did not finish")


def test_a1_summary_selection_aba_keeps_late_job_a_candidate(tmp_path: Path) -> None:
    with app_world(tmp_path) as app:
        provider = GatedSummary()
        job_id = app.service.summarize(app.session, provider, config_key="cfg")
        assert provider.entered.wait(5)
        assert app.content.select_summary(app.session, app.s2, expected_active=app.s1)
        assert app.content.select_summary(app.session, app.s1, expected_active=app.s2)
        provider.release.set()
        job = finished(app.service, job_id)
        assert job.state is JobState.SUCCEEDED and job.result_ref not in {app.s1, app.s2}
        assert app.content.active_summary(app.session)["revision_id"] == app.s1


def test_a2_transcript_selection_aba_during_summary_keeps_candidate(tmp_path: Path) -> None:
    with app_world(tmp_path) as app:
        provider = GatedSummary()
        job_id = app.service.summarize(app.session, provider, config_key="cfg")
        assert provider.entered.wait(5)
        assert app.content.select_transcript(app.session, app.t2, expected_active=app.t1)
        assert app.content.select_transcript(app.session, app.t1, expected_active=app.t2)
        provider.release.set()
        assert finished(app.service, job_id).state is JobState.SUCCEEDED
        assert app.content.active_summary(app.session)["revision_id"] == app.s1


def test_a3_latest_template_request_wins_over_older_running_job(tmp_path: Path) -> None:
    with app_world(tmp_path) as app:
        provider = GatedSummary()
        older = app.service.summarize(app.session, provider, config_key="cfg", template="meeting")
        assert provider.entered.wait(5)
        newer = app.service.summarize(app.session, provider, config_key="cfg", template="lecture")
        provider.release.set()
        older_job, newer_job = finished(app.service, older), finished(app.service, newer)
        assert older_job.state is newer_job.state is JobState.SUCCEEDED
        assert app.content.active_summary(app.session)["revision_id"] == newer_job.result_ref
        old, new = (
            app.content.summary(older_job.result_ref),
            app.content.summary(newer_job.result_ref),
        )
        assert (old["template"], new["template"]) == ("meeting", "lecture")
        assert old["settings_key"] != new["settings_key"]
        assert (
            app.content.selection_state(app.session)["summary_settings_key"] == new["settings_key"]
        )


def test_a4_uncontested_summary_is_selected_and_records_its_settings(tmp_path: Path) -> None:
    with app_world(tmp_path) as app:
        provider = GatedSummary()
        provider.release.set()
        job = finished(app.service, app.service.summarize(app.session, provider, config_key="cfg"))
        assert job.state is JobState.SUCCEEDED
        assert app.content.active_summary(app.session)["revision_id"] == job.result_ref
        key = app.content.summary(job.result_ref)["settings_key"]
        assert key == app.content.selection_state(app.session)["summary_settings_key"]
        assert len(key) == 64 and int(key, 16) >= 0


def test_a5_transcript_selection_aba_during_transcription_keeps_candidate(tmp_path: Path) -> None:
    with app_world(tmp_path) as app:
        provider = GatedSTT()
        job_id = app.service.transcribe(app.session, provider, config_key="stt")
        assert provider.entered.wait(5)
        assert app.content.select_transcript(app.session, app.t2, expected_active=app.t1)
        assert app.content.select_transcript(app.session, app.t1, expected_active=app.t2)
        provider.release.set()
        job = finished(app.service, job_id)
        assert job.state is JobState.SUCCEEDED
        assert app.content.active_transcript(app.session)["revision_id"] == app.t1
        assert app.content.transcript(job.result_ref)["kind"] == "corrected"


def test_r1_refused_before_admission_records_no_settings(tmp_path: Path) -> None:
    with app_world(tmp_path) as app:
        app.service.close()
        with pytest.raises(StateConflict, match="AI_SERVICE_CLOSED"):
            app.service.summarize(app.session, GatedSummary(), config_key="cfg")
        assert app.content.selection_state(app.session)["summary_settings_key"] is None


def test_r2_runner_refusal_after_admission_leaves_its_settings(tmp_path: Path) -> None:
    """Documented consequence: in-flight older requests stay candidates, nothing is lost."""
    with app_world(tmp_path, capacity=1) as app:
        provider = GatedSummary()
        first = app.service.summarize(app.session, provider, config_key="cfg", template="meeting")
        assert provider.entered.wait(5)
        second = app.service.summarize(app.session, provider, config_key="cfg", template="lecture")
        queued_key = app.content.selection_state(app.session)["summary_settings_key"]
        with pytest.raises(StateConflict, match="AI_QUEUE_FULL"):
            app.service.summarize(app.session, provider, config_key="cfg", template="key_points")
        refused = [job for job in app.service.jobs.list_for_session(app.session)][-1]
        assert refused.state is JobState.CANCELLED
        assert app.content.selection_state(app.session)["summary_settings_key"] != queued_key
        provider.release.set()
        jobs = [finished(app.service, first), finished(app.service, second)]
        assert all(job.state is JobState.SUCCEEDED for job in jobs)
        assert app.content.active_summary(app.session)["revision_id"] == app.s1
        assert all(app.content.summary(job.result_ref)["revision_id"] for job in jobs)


def test_d1_diarization_publication_after_selection_aba_is_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G03-D1: ui/ai_bridge diarization publication carries the captured version."""
    import hashlib

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from recoryn import diarization
    from recoryn.ui.main import MainWindow

    qt = QApplication.instance() or QApplication([])
    entered, release = threading.Event(), threading.Event()

    class Runtime:
        def __init__(self, config: Any) -> None:
            self.config = config

        def diarize(self, request: Any, context: Any) -> Any:
            entered.set()
            assert release.wait(5)
            return diarization.DiarizationResult(
                (diarization.SpeakerTurn(0, 100, "speaker_independent_0"),),
                True,
                audio_sha256=hashlib.sha256(request.audio_path.read_bytes()).hexdigest(),
                model_manifest_sha256=self.config.manifest_sha256,
                warnings=("ANONYMOUS_ESTIMATE",),
            )

        def close(self) -> None:
            pass

    monkeypatch.setattr(diarization, "LocalDiarizationProcess", Runtime)

    def spin(predicate: Callable[[], bool]) -> None:
        deadline = time.monotonic() + 5
        while not predicate() and time.monotonic() < deadline:
            qt.processEvents()
            time.sleep(0.001)
        assert predicate()

    with Library(tmp_path / "library") as library, ContentStore(library) as store:
        session = record(library)
        clip = prepare_clips(library, session)[1][0]
        source = {
            "track_id": "mic",
            "offset_ms": 0,
            "duration_ms": clip.duration_ms,
            "path": clip.path.relative_to(library.root).as_posix(),
            "sha256": clip.sha256,
            "ranges": list(clip.source_ranges),
        }
        coverage = {
            "schema_version": 1,
            "planned": ["range"],
            "completed": ["range"],
            "failed": [],
            "missing": [],
            "source_ranges": [source],
        }
        line = [Segment("line", 0, clip.duration_ms, "text", track_id="mic")]
        parent = store.create_transcript(session, line, coverage=coverage)
        other = store.create_transcript(session, line, coverage=coverage)
        window = MainWindow(library)
        window.timer.stop()
        bridge = window.ai_bridge
        try:
            bridge.panel.load(session)
            window.diarization_manifest.setText(str(tmp_path / "unloaded-manifest.json"))
            window.diarization_hash.setText("b" * 64)
            window.diarization_approval.setChecked(True)
            bridge.diarize()
            spin(entered.is_set)
            assert store.select_transcript(session, other, expected_active=parent)
            assert store.select_transcript(session, parent, expected_active=other)
            release.set()
            spin(
                lambda: (
                    bridge.service.jobs.list_for_session(session)[-1].state.value
                    in {"SUCCEEDED", "FAILED", "CANCELLED"}
                )
            )
            job = bridge.service.jobs.list_for_session(session)[-1]
            assert job.state.value == "SUCCEEDED"
            assert store.transcript(job.result_ref)["parent_revision_id"] == parent
            assert store.active_transcript(session)["revision_id"] == parent
        finally:
            release.set()
            spin(lambda: not bridge.busy)
            window.close()
            spin(lambda: window._closing)
            window.deleteLater()
            qt.processEvents()


# Requests merged into an existing job (admitted=False) are the user's latest request.


def requests(library: Library) -> list[tuple[Any, ...]]:
    with closing(sqlite3.connect(library.db_path.as_uri() + "?mode=ro", uri=True)) as raw:
        return raw.execute(
            "SELECT settings_key, request_count FROM content_summary_requests"
        ).fetchall()


def test_mg1_request_merged_into_running_job_becomes_latest(tmp_path: Path) -> None:
    """G03-MG1: K1 -> K2 -> K1, the third merging into the running K1 job."""
    with app_world(tmp_path) as app:
        provider = GatedSummary()
        first = app.service.summarize(app.session, provider, config_key="cfg", template="meeting")
        assert provider.entered.wait(5)
        second = app.service.summarize(app.session, provider, config_key="cfg", template="lecture")
        third = app.service.summarize(app.session, provider, config_key="cfg", template="meeting")
        assert third == first != second
        assert {job.job_id for job in app.service.jobs.list_for_session(app.session)} == {
            first,
            second,
        }
        provider.release.set()
        k1_job, k2_job = finished(app.service, first), finished(app.service, second)
        assert k1_job.state is k2_job.state is JobState.SUCCEEDED
        k1, k2 = app.content.summary(k1_job.result_ref), app.content.summary(k2_job.result_ref)
        assert (k1["template"], k2["template"]) == ("meeting", "lecture")
        assert app.content.active_summary(app.session)["revision_id"] == k1["revision_id"]
        assert k2["revision_id"] not in {k1["revision_id"], app.s1, app.s2}
        assert requests(app.library) == [(k1["settings_key"], 3)]
        assert provider.calls == 2


def test_mg2_refusal_before_admission_is_not_a_merge(tmp_path: Path) -> None:
    """G03-MG2: the same request records while open and merging, nothing once refused."""
    with app_world(tmp_path) as app:
        provider = GatedSummary()
        provider.release.set()
        first = app.service.summarize(app.session, provider, config_key="cfg", template="meeting")
        k1 = app.content.summary(finished(app.service, first).result_ref)["settings_key"]
        second = app.service.summarize(app.session, provider, config_key="cfg", template="lecture")
        k2 = app.content.summary(finished(app.service, second).result_ref)["settings_key"]
        assert requests(app.library) == [(k2, 2)]
        again = app.service.summarize(app.session, provider, config_key="cfg", template="meeting")
        assert again == first and requests(app.library) == [(k1, 3)]
        again = app.service.summarize(app.session, provider, config_key="cfg", template="lecture")
        assert again == second and requests(app.library) == [(k2, 4)]
        app.service.close()
        with pytest.raises(StateConflict, match="AI_SERVICE_CLOSED"):
            app.service.summarize(app.session, provider, config_key="cfg", template="meeting")
        assert requests(app.library) == [(k2, 4)]
        assert provider.calls == 2


def test_mg3_failed_merge_record_leaves_the_existing_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G03-MG3: the merged job is not ours; a recording failure neither cancels nor forgets it."""
    with app_world(tmp_path) as app:
        provider = GatedSummary()
        first = app.service.summarize(app.session, provider, config_key="cfg")
        assert provider.entered.wait(5)

        def refuse(session_id: str, settings_key: str) -> None:
            raise StateConflict("INJECTED_REQUEST_FAILURE")

        with monkeypatch.context() as patch:
            patch.setattr(app.content, "request_summary_settings", refuse)
            with pytest.raises(StateConflict, match="INJECTED_REQUEST_FAILURE"):
                app.service.summarize(app.session, provider, config_key="cfg")
        assert app.service.summarize(app.session, provider, config_key="cfg") == first
        provider.release.set()
        job = finished(app.service, first)
        assert job.state is JobState.SUCCEEDED and provider.calls == 1
        assert app.content.active_summary(app.session)["revision_id"] == job.result_ref
