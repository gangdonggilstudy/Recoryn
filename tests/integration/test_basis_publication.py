"""G12 / G-P12 P, D and transaction T rows: publication and explicit candidate selection.

Real SQLite (two connections), the real AIService publication path and a fake
summary provider; no device, model, network or paid call. Expectations are written by
hand from G12 sections 3.2, 4.3 and the amendment (P Job states follow the G-P07
decision table: a partial summary is a FAILED/TASK_FAILED Job whose revision is a
``complete=false`` candidate).
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import ExitStack, closing
from itertools import count, product
from pathlib import Path
from typing import Any

import pytest

from recoryn.app.ai import AIService
from recoryn.content import Claim, ContentStore, Segment, SummarySelectionExpectation
from recoryn.domain import StateConflict
from recoryn.jobs import JobStore
from recoryn.providers import SegmentSpan, SummaryCheckpoint, SummaryClaim, SummaryResult
from recoryn.storage import Library
from tests.resource_fakes import SUMMARY

pytestmark = pytest.mark.integration
_serial = count(1)

SEGMENTS = (
    Segment("a", 0, 100, "spoken words", track_id="mic", timing_quality="clip"),
    Segment("u", 100, 200, "typed note", provenance="user_assertion"),
    Segment("r", 200, 300, "unclear words", provenance="unresolved"),
)
# Which source segment a provider claim cites for each canonical basis (G12 3.1).
SOURCE_REFS = {
    "transcript": ("a",),
    "user_assertion": ("u",),
    "unresolved": ("r",),
    "model_inference": (),
}


_READERS: dict[Path, sqlite3.Connection] = {}


def _rows(db: Path, sql: str, *args: Any) -> list[tuple[Any, ...]]:
    """Read through a second, independent connection (one autocommit reader per DB)."""
    reader = _READERS.get(db)
    if reader is None:
        reader = _READERS[db] = sqlite3.connect(db, isolation_level=None, check_same_thread=False)
    return reader.execute(sql, args).fetchall()


@pytest.fixture(scope="module", autouse=True)
def _close_readers() -> Iterator[None]:
    yield
    while _READERS:
        _READERS.popitem()[1].close()


def _selection_row(db: Path, session: str) -> tuple[Any, ...]:
    """The selection as a second connection sees it (independent of the store API)."""
    selected = _rows(
        db,
        "SELECT transcript_id,transcript_version,summary_id,summary_version "
        "FROM content_selections WHERE session_id=?",
        session,
    )
    key = _rows(db, "SELECT settings_key FROM content_summary_requests WHERE session_id=?", session)
    return (*(selected[0] if selected else (None, 0, None, 0)), key[0][0] if key else None)


def _events(db: Path, session: str) -> int:
    return _rows(db, "SELECT COUNT(*) FROM content_events WHERE session_id=?", session)[0][0]


def _hash(db: Path, revision: str) -> str:
    return _rows(db, "SELECT sha256 FROM content_revisions WHERE revision_id=?", revision)[0][0]


# --- P: provider basis x source canonical x template x complete x result order --------
P_PROVIDER = ("transcript", "user_assertion", "model_inference")
P_SOURCE = ("transcript", "user_assertion", "unresolved", "model_inference")
P_TEMPLATE = ("decisions", "tasks", "meeting")
P_ORDER = ("normal", "select_aba", "cancel_first", "delete_first")
P = list(product(P_PROVIDER, P_SOURCE, P_TEMPLATE, (True, False), P_ORDER))
P_IDS = [f"G12-P-{n:03}" for n in range(1, 289)]


def p_oracle(row: tuple[Any, ...]) -> dict[str, Any]:
    provider, source, template, complete, order = row
    if order == "cancel_first":
        return {"job": ("CANCELLED", None), "published": 0, "summary_delta": 0}
    if order == "delete_first":
        return {"job": ("FAILED", "TASK_FAILED"), "published": None}
    selected = complete and order == "normal"
    return {
        "job": ("SUCCEEDED", None) if complete else ("FAILED", "TASK_FAILED"),
        "published": 1,
        "complete": complete,
        "selected": selected,
        "summary_delta": 1 if selected else (2 if order == "select_aba" else 0),
        "basis": source,
        "provider": provider,
        "area": "transcript_reference"
        if source == "transcript" and provider == "transcript"
        else "review",
        "kind": template if template in ("decisions", "tasks") else "other",
    }


class _Gate:
    def __init__(self, provider_basis: str, refs: tuple[str, ...], complete: bool) -> None:
        self.entered, self.release = threading.Event(), threading.Event()
        self.provider_basis, self.refs, self.complete = provider_basis, refs, complete
        self.calls = 0

    def summarize(self, request: Any, context: Any = None) -> SummaryResult:
        self.calls += 1
        self.entered.set()
        assert self.release.wait(5), "test barrier was not released"
        spans = tuple(SegmentSpan(s.segment_id, 0, len(s.text)) for s in request.segments)
        done = spans if self.complete else spans[:1]
        return SummaryResult(
            "fixture",
            "pinned-model",
            request.transcript_revision_id,
            (SummaryClaim("논의한 내용", self.refs, "uncertain", self.provider_basis),),
            done,
            () if self.complete else spans[1:],
            self.complete,
            SummaryCheckpoint("a" * 64),
            outcome_known=True,
        )


def _finished(service: AIService, job_id: str) -> Any:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        job = service.jobs.get(job_id)
        if job.state.value in {"SUCCEEDED", "FAILED", "CANCELLED", "BLOCKED"}:
            return job
        time.sleep(0.002)
    pytest.fail(f"summary job did not finish: {service.jobs.get(job_id).state}")


@pytest.fixture(scope="module")
def ai(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[Library, ContentStore, Any]]:
    root = tmp_path_factory.mktemp("g12-p")
    with Library(root / "library") as library, ContentStore(library) as content:
        service = AIService(library, content)
        try:
            yield library, content, service
        finally:
            service.close()


class _Rotating:
    """Private stores for deleting rows, replaced every ``size`` rows.

    A completed deletion keeps its journal record and every later Job transition
    re-reads the journal, so deleting rows must not share the main library; rotating
    keeps each private history small while preserving every row.
    """

    def __init__(self, root: Path, open_world: Any, size: int = 8) -> None:
        self.root, self.open_world, self.size = root, open_world, size
        self.uses, self.stack, self.world = 0, ExitStack(), None

    def get(self) -> Any:
        if self.uses % self.size == 0:
            self.stack.close()
            self.stack = ExitStack()
            self.world = self.open_world(self.stack, self.root / f"rotation-{self.uses}")
        self.uses += 1
        return self.world

    def close(self) -> None:
        self.stack.close()


def _open_ai(stack: ExitStack, root: Path) -> tuple[Library, ContentStore, AIService]:
    library = stack.enter_context(Library(root / "library"))
    content = stack.enter_context(ContentStore(library))
    service = AIService(library, content)
    stack.callback(service.close)
    return library, content, service


def _open_stores(stack: ExitStack, root: Path) -> tuple[Library, ContentStore, JobStore]:
    library = stack.enter_context(Library(root / "library"))
    content = stack.enter_context(ContentStore(library))
    return library, content, stack.enter_context(JobStore(library.db_path))


@pytest.fixture(scope="module")
def deleting(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, _Rotating]]:
    root = tmp_path_factory.mktemp("g12-deleting")
    pools = {
        "ai": _Rotating(root / "ai", _open_ai),
        "stores": _Rotating(root / "stores", _open_stores),
    }
    try:
        yield pools
    finally:
        for pool in pools.values():
            pool.close()


@pytest.mark.parametrize("row", P, ids=P_IDS)
def test_p_publication_keeps_reference_basis_candidates_and_sources(
    ai: tuple[Library, ContentStore, AIService],
    deleting: dict[str, _Rotating],
    row: tuple[Any, ...],
) -> None:
    _run_p(deleting["ai"].get() if row[-1] == "delete_first" else ai, row)


def _run_p(world: tuple[Library, ContentStore, AIService], row: tuple[Any, ...]) -> None:
    from recoryn.ui.content import claim_area, claim_kind

    library, content, service = world
    provider, source, template, complete, order = row
    want = p_oracle(row)
    session = f"p{next(_serial)}"
    library.create_session(session)
    transcript = content.create_transcript(session, list(SEGMENTS))
    base = content.create_summary(
        session, transcript, [Claim("base", ("a",))], expected_transcript=transcript
    )
    other = content.create_summary(
        session,
        transcript,
        [Claim("other", ("a",))],
        expected_transcript=transcript,
        expected_summary=None,
    )
    db = library.db_path
    before = _selection_row(db, session)
    source_hash = _hash(db, transcript)
    gate = _Gate(provider, SOURCE_REFS[source], complete)
    if order == "normal":
        gate.release.set()
    status = library.verify_deletion_history(fresh=True)
    assert status == {"status": "READY", "code": ""}, status
    job_id = service.summarize(
        session, gate, config_key="g12-p", resource_request=SUMMARY, template=template
    )
    if order != "normal":
        assert gate.entered.wait(5)
        if order == "select_aba":
            peer = ContentStore(library)  # a second connection changes the selection
            try:
                assert peer.select_summary(session, other, expected_active=base)
                assert peer.select_summary(session, base, expected_active=other)
            finally:
                peer.close()
        elif order == "cancel_first":
            service.cancel_session(session)
        else:
            assert library.delete_session(session)["deleted"] is False  # a reader is active
        gate.release.set()
    job = _finished(service, job_id)
    assert (job.state.value, job.error_code) == want["job"]
    assert gate.calls == 1  # one provider call; nothing is re-sent
    if want["published"] is None:
        with pytest.raises(StateConflict):
            content.list_revisions(session, "summary")
        assert library.delete_session(session)["deleted"] is True
        assert _rows(db, "SELECT COUNT(*) FROM content_revisions WHERE session_id=?", session) == [
            (0,)
        ]
        return
    summaries = content.list_revisions(session, "summary")
    new = [item for item in summaries if item["revision_id"] not in (base, other)]
    assert len(new) == want["published"]
    after = _selection_row(db, session)
    assert after[:2] == before[:2]  # the transcript selection never moves
    assert _hash(db, transcript) == source_hash  # the fixed source is untouched
    assert after[3] - before[3] == want["summary_delta"]
    if not new:
        assert after[2] == base
        return
    (published,) = new
    assert published["complete"] is want["complete"]
    assert published["transcript_revision_id"] == transcript  # pinned to its source
    assert (after[2] == published["revision_id"]) is want["selected"]
    if not want["selected"]:
        assert after[2] == base
    (view,) = content.claim_evidence(published["revision_id"])
    assert (view["basis"], view["provider_basis"], view["status"]) == (
        want["basis"],
        want["provider"],
        "uncertain",
    )
    assert view["problem"] is None and view["basis_recorded"] is True
    assert (
        claim_area(view["status"], view["basis"], view["provider_basis"], view["problem"])
        == want["area"]
    )
    assert claim_kind(content.summary(published["revision_id"])["template"]) == want["kind"]
    if want["complete"]:
        assert job.result_ref == published["revision_id"]


# --- D: CAS situation x target x allow_outdated x deletion intent ----------------------
D_CAS = (
    "unchanged",
    "summary_id",
    "summary_aba",
    "transcript_id",
    "transcript_aba",
    "settings_key",
)
D_TARGET = ("complete_current", "complete_old_transcript", "complete_old_settings", "partial")
D = list(product(D_CAS, D_TARGET, (False, True), (False, True)))
D_IDS = [f"G12-D-{n:02}" for n in range(1, 97)]


def d_oracle(row: tuple[Any, ...]) -> object:
    cas, target, allow, deleting = row
    if deleting:
        return "SESSION_DELETING"
    if target == "partial":
        return "CONTENT_SUMMARY_NOT_COMPLETE"
    if cas != "unchanged":
        return False
    if target == "complete_current" or allow:
        return True
    return "CONTENT_SUMMARY_OUTDATED_CONFIRMATION_REQUIRED"


def publish(
    content: ContentStore,
    jobs: JobStore,
    session: str,
    source: str,
    *,
    complete: bool = True,
    key: str | None = None,
    select: bool = False,
    text: str = "candidate",
) -> str:
    """A summary published through the real G-P03 path (selected only if asked)."""
    job = jobs.create("summarization", f"g12-{next(_serial)}")
    jobs.bind_session(job.job_id, session)
    attempt = jobs.claim(job.job_id, "fixture")
    state = content.selection_state(session)
    revision = content.publish_summary(
        jobs,
        attempt,
        session,
        source,
        [Claim(text, ("a",))],
        complete=complete,
        expected_transcript=source,
        expected_summary=state["summary_id"],
        expected_summary_version=state["summary_version"] + (0 if select else 1_000),
        settings_key=key,
    )
    if not complete:
        # A partial checkpoint keeps its attempt; end it so no live reader lingers.
        jobs.fail(job.job_id, attempt.attempt_id, attempt.fence, "SUMMARY_PARTIAL")
    return revision


@pytest.fixture(scope="module")
def stores(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[tuple[Library, ContentStore, JobStore]]:
    root = tmp_path_factory.mktemp("g12-d")
    with Library(root / "library") as library, ContentStore(library) as content:
        with JobStore(library.db_path) as jobs:
            yield library, content, jobs


def candidate_world(
    library: Library, content: ContentStore, jobs: JobStore, target: str
) -> dict[str, str]:
    session = f"d{next(_serial)}"
    library.create_session(session)
    old = content.create_transcript(session, list(SEGMENTS))
    current = content.create_transcript(session, list(SEGMENTS), expected_active=old)
    content.request_summary_settings(session, "K")
    status = library.verify_deletion_history(fresh=True)
    assert status == {"status": "READY", "code": ""}, status
    base = publish(content, jobs, session, current, key="K", select=True, text="selected")
    other = publish(content, jobs, session, current, key="K", text="other")
    source, key, complete = {
        "complete_current": (current, "K", True),
        "complete_old_transcript": (old, "K", True),
        "complete_old_settings": (current, "K-old", True),
        "partial": (current, "K", False),
    }[target]
    chosen = publish(content, jobs, session, source, key=key, complete=complete, text="target")
    return {
        "session": session,
        "old": old,
        "current": current,
        "base": base,
        "other": other,
        "target": chosen,
    }


def compete(library: Library, world: dict[str, str], cas: str) -> None:
    """The change another window/job makes between presenting and confirming."""
    if cas == "unchanged":
        return
    peer = ContentStore(library)
    try:
        session = world["session"]
        if cas in ("summary_id", "summary_aba"):
            assert peer.select_summary(session, world["other"], expected_active=world["base"])
            if cas == "summary_aba":
                assert peer.select_summary(session, world["base"], expected_active=world["other"])
        elif cas in ("transcript_id", "transcript_aba"):
            assert peer.select_transcript(session, world["old"], expected_active=world["current"])
            if cas == "transcript_aba":
                assert peer.select_transcript(
                    session, world["current"], expected_active=world["old"]
                )
        else:
            peer.request_summary_settings(session, "K-new")
    finally:
        peer.close()


@pytest.mark.parametrize("row", D, ids=D_IDS)
def test_d_candidate_selection_compares_the_whole_snapshot(
    stores: tuple[Library, ContentStore, JobStore],
    deleting: dict[str, _Rotating],
    row: tuple[Any, ...],
) -> None:
    _run_d(deleting["stores"].get() if row[-1] else stores, row)


def _run_d(world: tuple[Library, ContentStore, JobStore], row: tuple[Any, ...]) -> None:
    library, content, jobs = world
    cas, target, allow, deleting = row
    want = d_oracle(row)
    world = candidate_world(library, content, jobs, target)
    session, db = world["session"], library.db_path
    snapshot = SummarySelectionExpectation.from_state(content.selection_state(session))
    compete(library, world, cas)
    if deleting:
        reader = jobs.create("summarization", f"g12-reader-{next(_serial)}")
        jobs.bind_session(reader.job_id, session)
        held = jobs.claim(reader.job_id, "reader")
        assert library.delete_session(session)["deleted"] is False
    observed, events = _selection_row(db, session), _events(db, session)
    target_hash = _hash(db, world["target"])
    if isinstance(want, str):
        with pytest.raises(StateConflict) as error:
            content.select_summary_candidate(
                session, world["target"], expected=snapshot, allow_outdated=allow
            )
        if want != "SESSION_DELETING":
            assert str(error.value) == want
    else:
        assert (
            content.select_summary_candidate(
                session, world["target"], expected=snapshot, allow_outdated=allow
            )
            is want
        )
    after = _selection_row(db, session)
    if want is True:
        assert after == (*observed[:2], world["target"], observed[3] + 1, observed[4])
        assert _events(db, session) == events + 1
        assert _rows(
            db,
            "SELECT revision_id,revision_type FROM content_events WHERE session_id=? ORDER BY event_id DESC LIMIT 1",
            session,
        ) == [(world["target"], "select_summary")]
    else:
        assert after == observed and _events(db, session) == events
    assert _hash(db, world["target"]) == target_hash  # selecting never rewrites a body
    assert after[4] == observed[4]  # nor the requested settings
    if deleting:
        jobs.fail(reader.job_id, held.attempt_id, held.fence, "G12_READER_DONE")
        assert library.delete_session(session)["deleted"] is True


# --- named transaction / partial rows -------------------------------------------------
T_INTEGRATION = ("G12-T-21", "G12-T-25")


@pytest.mark.parametrize("case", T_INTEGRATION, ids=T_INTEGRATION)
def test_t_selection_rollback_and_partial_job(
    stores: tuple[Library, ContentStore, JobStore],
    ai: tuple[Library, ContentStore, AIService],
    case: str,
) -> None:
    if case == "G12-T-21":
        library, content, jobs = stores
        world = candidate_world(library, content, jobs, "complete_current")
        session, db = world["session"], library.db_path
        snapshot = SummarySelectionExpectation.from_state(content.selection_state(session))
        observed, events = _selection_row(db, session), _events(db, session)
        with closing(sqlite3.connect(db)) as connection, connection:
            connection.execute(
                "CREATE TRIGGER g12_event_fault BEFORE INSERT ON content_events "
                "WHEN NEW.revision_type='select_summary' BEGIN SELECT RAISE(ABORT,'G12_FAULT'); END"
            )
        try:
            with pytest.raises(sqlite3.IntegrityError, match="G12_FAULT"):
                content.select_summary_candidate(session, world["target"], expected=snapshot)
        finally:
            with closing(sqlite3.connect(db)) as connection, connection:
                connection.execute("DROP TRIGGER g12_event_fault")
        assert _selection_row(db, session) == observed and _events(db, session) == events
        assert content.select_summary_candidate(session, world["target"], expected=snapshot) is True
        return
    # G12-T-25: the partial Job is FAILED by the G-P07 table, yet the candidate is
    # classified by its revision (complete=false) and cannot be selected as a whole.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from recoryn.ui.content import ContentPanel

    library, content, service = ai
    session = f"t25-{next(_serial)}"
    library.create_session(session)
    transcript = content.create_transcript(session, list(SEGMENTS))
    gate = _Gate("transcript", ("a",), complete=False)
    gate.release.set()
    status = library.verify_deletion_history(fresh=True)
    assert status == {"status": "READY", "code": ""}, status
    job = _finished(
        service, service.summarize(session, gate, config_key="t25", resource_request=SUMMARY)
    )
    assert (job.state.value, job.error_code) == ("FAILED", "TASK_FAILED")
    (partial,) = content.list_revisions(session, "summary")
    assert partial["complete"] is False and partial["transcript_revision_id"] == transcript
    snapshot = SummarySelectionExpectation.from_state(content.selection_state(session))
    with pytest.raises(StateConflict, match="CONTENT_SUMMARY_NOT_COMPLETE"):
        content.select_summary_candidate(
            session, partial["revision_id"], expected=snapshot, allow_outdated=True
        )
    application = QApplication.instance() or QApplication([])
    panel = ContentPanel(content, lambda *args, **kwargs: None)
    try:
        panel.show()
        panel.load(session)
        index = panel.summary_candidates.findData(partial["revision_id"])
        assert index >= 0 and "부분" in panel.summary_candidates.itemText(index)
        panel.summary_candidates.setCurrentIndex(index)
        assert not panel.select_summary_button.isEnabled()
        assert "부분 결과" in panel.candidate_info.text()
    finally:
        panel.close()
        panel.deleteLater()
        application.processEvents()
