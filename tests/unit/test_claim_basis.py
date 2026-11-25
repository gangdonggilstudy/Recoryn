"""G12 / G-P12 B, W and data T rows: claim basis, adapter reference value, expectations.

Every expectation is transcribed by hand from G12 sections 3-4 (canonical table, review
areas, parser normalization, snapshot DTO). The product basis/area/parser functions are
only ever the thing under test.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from itertools import product
from typing import Any

import pytest

from recoryn.content import Claim, ContentStore, Segment, SummarySelectionExpectation
from recoryn.domain import StateConflict, ValidationError
from recoryn.providers import ProviderError
from recoryn.storage import Library
from recoryn.summarization.adapters import parse_claims
from recoryn.ui.content import REVIEW_AREA, TRANSCRIPT_AREA, claim_area, claim_kind

# --- B: claim kind x adapter basis x referenced provenance set x input status ----------
KINDS = {"decisions": "decisions", "tasks": "tasks", "other": "meeting"}
PROVIDER = (None, "transcript", "user_assertion", "model_inference")
PROVENANCE_SETS = (
    (),
    ("audio",),
    ("user_assertion",),
    ("unresolved",),
    ("audio", "user_assertion"),
    ("audio", "unresolved"),
    ("user_assertion", "unresolved"),
    ("audio", "user_assertion", "unresolved"),
)
STATUSES = (
    "uncertain",
    "unreviewed",
    "unsupported",
    "disputed",
    "user_assertion",
    "model_inference",
    "supported",
    "unresolved",
)
B = list(product(KINDS, PROVIDER, PROVENANCE_SETS, STATUSES))
B_IDS = [f"G12-B-{n:03}" for n in range(1, 769)]
TITLES = {"decisions": "결정 제안 — 미확정", "tasks": "할 일 제안 — 미확정", "other": None}


def b_oracle(row: tuple[Any, ...]) -> tuple[str, str | None, str | None]:
    """(outcome, canonical basis, area) by hand (G12 3.1 table, 4.1 areas)."""
    kind, provider, provenances, status = row
    if status in ("supported", "unresolved"):
        return "rejected", None, None
    if "unresolved" in provenances:
        basis = "unresolved"
    elif "user_assertion" in provenances:
        basis = "user_assertion"
    elif provenances:
        basis = "transcript"
    else:
        basis = "model_inference"
    area = (
        "transcript_reference"
        if basis == "transcript"
        and status in ("uncertain", "unreviewed")
        and provider in (None, "transcript")
        else "review"
    )
    return "stored", basis, area


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Any]:
    root = tmp_path_factory.mktemp("g12-unit")
    with Library(root / "library") as library, ContentStore(library) as content:
        library.create_session("bsession")
        transcript = content.create_transcript(
            "bsession",
            [
                Segment("audio", 0, 100, "spoken", track_id="mic", timing_quality="clip"),
                Segment("user_assertion", 100, 200, "typed", provenance="user_assertion"),
                Segment("unresolved", 200, 300, "unknown", provenance="unresolved"),
            ],
        )
        yield library, content, transcript


def test_b_manifest() -> None:
    assert len(B) == len(set(B)) == 3 * 4 * 8 * 8 == len(B_IDS) == 768


def test_b_canonical_basis_areas_and_titles(world: Any) -> None:
    """G12-B-001..768 through the real DTO, store and area classifier (batched)."""
    library, content, transcript = world
    mismatches = []
    for case, row in zip(B_IDS, B, strict=True):
        kind, provider, provenances, status = row
        want = b_oracle(row)
        try:
            claim = Claim(f"claim {case}", tuple(provenances), status, provider)
        except ValidationError as error:
            actual: tuple[Any, ...] = ("rejected", None, None)
            if str(error) != "INVALID_AUTOMATIC_CLAIM_STATUS":
                mismatches.append((case, "code", str(error)))
        else:
            summary = content.create_summary(
                "bsession", transcript, [claim], template=KINDS[kind], expected_transcript=None
            )
            view = content.claim_evidence(summary)[0]
            area = claim_area(
                view["status"], view["basis"], view["provider_basis"], view["problem"]
            )
            actual = ("stored", view["basis"], area)
            if view["provider_basis"] != provider or view["computed_basis"] != view["basis"]:
                mismatches.append((case, "provider/computed", view))
            if claim_kind(content.summary(summary)["template"]) != kind:
                mismatches.append((case, "kind", kind))
        if actual != want:
            mismatches.append((case, want, actual))
    assert mismatches == [], mismatches[:5]
    assert TRANSCRIPT_AREA == "transcript_reference" and REVIEW_AREA == "review"


# --- W: raw status x reference kind x raw basis through the adapter parser --------------
RAW_STATUS = (
    "missing",
    "uncertain",
    "unsupported",
    "disputed",
    "user_assertion",
    "supported",
    "bogus",
)
REF_KINDS = {
    "audio": ["a"],
    "empty": [],
    "user_assertion": ["u"],
    "unresolved": ["r"],
    "missing": ["zz"],
}
RAW_BASIS = ("missing", "transcript", "user_assertion", "model_inference")
W = list(product(RAW_STATUS, REF_KINDS, RAW_BASIS))
W_IDS = [f"G12-W-{n:03}" for n in range(1, 141)]
W_PROVENANCE = {"a": "audio", "u": "user_assertion", "r": "unresolved"}


def w_oracle(row: tuple[str, str, str]) -> tuple[str, str, str] | str:
    """Hand rules: missing refs reject the whole result; the raw basis is never read."""
    raw_status, refs, _raw_basis = row
    if refs == "missing":
        return "REFERENCE_INVALID"
    status = raw_status if raw_status in ("unsupported", "disputed") else "uncertain"
    if refs == "empty":
        return ("unsupported", "model_inference", "model_inference")
    if refs == "user_assertion":
        return ("user_assertion", "user_assertion", "user_assertion")
    if refs == "unresolved":
        return (status, "model_inference", "unresolved")
    return (status, "transcript", "transcript")


@pytest.mark.parametrize("row", W, ids=W_IDS)
def test_w_parser_normalization_and_canonical_store(world: Any, row: tuple[str, str, str]) -> None:
    library, content, transcript = world
    raw_status, refs, raw_basis = row
    raw: dict[str, Any] = {"text": "parsed claim", "segment_ids": list(REF_KINDS[refs])}
    if raw_status != "missing":
        raw["status"] = raw_status
    if raw_basis != "missing":
        raw["basis"] = raw_basis  # a model-provided basis must never be trusted
    want = w_oracle(row)
    try:
        claims = parse_claims({"claims": [raw]}, {"a", "u", "r"}, W_PROVENANCE)
    except ProviderError as error:
        assert error.code == want
        return
    assert len(claims) == 1
    item = claims[0]
    # The adapter's basis becomes the reference value; the store recomputes canonical.
    segment_ids = tuple(
        {"a": "audio", "u": "user_assertion", "r": "unresolved"}[ref] for ref in item.segment_ids
    )
    summary = content.create_summary(
        "bsession",
        transcript,
        [Claim(item.text, segment_ids, item.status, item.basis)],
        expected_transcript=None,
    )
    view = content.claim_evidence(summary)[0]
    assert (item.status, item.basis, view["basis"]) == want
    assert view["provider_basis"] == item.basis and view["status"] != "supported"


# --- data / type T rows ----------------------------------------------------------------
T_UNIT = (
    "G12-T-01",
    "G12-T-02",
    "G12-T-03",
    "G12-T-04",
    "G12-T-05",
    "G12-T-10",
    "G12-T-18",
    "G12-T-19",
    "G12-T-20",
    "G12-T-24",
)


def _expectation(**changes: Any) -> SummarySelectionExpectation:
    fields: dict[str, Any] = dict(
        session_id="s",
        transcript_id=None,
        transcript_version=0,
        summary_id=None,
        summary_version=0,
        summary_settings_key=None,
    )
    fields.update(changes)
    return SummarySelectionExpectation(**fields)


def _tamper(library: Library, revision_id: str, change: Any) -> None:
    """Rewrite one stored body with a matching hash (simulates a legacy/foreign writer).

    The immutability trigger is lifted only for this one write and restored at once."""
    database = sqlite3.connect(library.db_path)
    try:
        (body_text,) = database.execute(
            "SELECT body FROM content_revisions WHERE revision_id=?", (revision_id,)
        ).fetchone()
        body = json.loads(body_text)
        change(body)
        encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        with database:
            database.execute("DROP TRIGGER content_revision_immutable")
            database.execute(
                "UPDATE content_revisions SET body=?,sha256=? WHERE revision_id=?",
                (encoded, hashlib.sha256(encoded.encode("utf-8")).hexdigest(), revision_id),
            )
            database.execute(
                "CREATE TRIGGER content_revision_immutable BEFORE UPDATE ON content_revisions "
                "BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_CONTENT_REVISION'); END"
            )
    finally:
        database.close()


@pytest.mark.parametrize("case", T_UNIT, ids=T_UNIT)
def test_t_data_and_type_boundaries(world: Any, case: str) -> None:
    library, content, transcript = world
    if case == "G12-T-01":
        with pytest.raises(ValidationError, match="^INVALID_CLAIM_PROVIDER_BASIS$"):
            Claim("x", (), "uncertain", True)  # type: ignore[arg-type]
    elif case == "G12-T-02":
        for value in ("supported", "unresolved", "Transcript", ""):
            with pytest.raises(ValidationError, match="^INVALID_CLAIM_PROVIDER_BASIS$"):
                Claim("x", (), "uncertain", value)
    elif case == "G12-T-03":
        summary = content.create_summary(
            "bsession", transcript, [Claim("legacy", ("audio",))], expected_transcript=None
        )
        body = content.summary(summary)
        assert "provider_basis" not in body["claims"][0]  # no field written for None
        view = content.claim_evidence(summary)[0]
        assert view["provider_basis"] is None and view["basis"] == "transcript"
    elif case == "G12-T-04":
        summary = content.create_summary(
            "bsession", transcript, [Claim("tampered", ("audio",))], expected_transcript=None
        )
        _tamper(library, summary, lambda body: body["claims"][0].update(basis="user_assertion"))
        view = content.claim_evidence(summary)[0]
        assert view["problem"] == "CONTENT_CLAIM_BASIS_MISMATCH"
        assert (
            claim_area(view["status"], view["basis"], view["provider_basis"], view["problem"])
            == REVIEW_AREA
        )
    elif case == "G12-T-05":
        summary = content.create_summary(
            "bsession", transcript, [Claim("future", ("audio",))], expected_transcript=None
        )
        _tamper(library, summary, lambda body: body.update(schema_version=2))
        with pytest.raises(ValidationError, match="CONTENT_REVISION_SCHEMA"):
            content.summary(summary)
    elif case == "G12-T-10":
        library.create_session("t10")
        source = content.create_transcript(
            "t10", [Segment("audio", 0, 10, "x", track_id="mic", timing_quality="clip")]
        )
        summary = content.create_summary(
            "t10", source, [Claim("c", ("audio",))], expected_transcript=None
        )
        _tamper(library, source, lambda body: body["segments"][0].update(text="changed"))
        view = content.claim_evidence(summary)[0]
        assert (
            view["problem"] == "CONTENT_CLAIM_SOURCE_UNAVAILABLE" and view["computed_basis"] is None
        )
    elif case == "G12-T-18":
        with pytest.raises(ValidationError, match="^INVALID_SUMMARY_SELECTION_EXPECTATION$"):
            _expectation(summary_version=True)
    elif case == "G12-T-19":
        with pytest.raises(ValidationError, match="^INVALID_SUMMARY_SELECTION_EXPECTATION$"):
            _expectation(transcript_version=-1)
    elif case == "G12-T-20":
        summary = content.create_summary(
            "bsession", transcript, [Claim("c", ("audio",))], expected_transcript=None
        )
        expected = SummarySelectionExpectation.from_state(content.selection_state("bsession"))
        before = content.selection_state("bsession")
        for flag in (1, "yes", None):
            with pytest.raises(ValidationError, match="^INVALID_SUMMARY_SELECTION_EXPECTATION$"):
                content.select_summary_candidate(
                    "bsession", summary, expected=expected, allow_outdated=flag
                )  # type: ignore[arg-type]
        assert content.selection_state("bsession") == before
    elif case == "G12-T-24":
        library.create_session("t24")
        source = content.create_transcript(
            "t24", [Segment("audio", 0, 10, "x", track_id="mic", timing_quality="clip")]
        )
        summary = content.create_summary(
            "t24", source, [Claim("c", ("audio",))], expected_transcript=None
        )
        expected = SummarySelectionExpectation.from_state(content.selection_state("t24"))
        assert expected.summary_settings_key is None
        content.request_summary_settings("t24", "new-key")  # None -> a key after the snapshot
        assert (
            content.select_summary_candidate("t24", summary, expected=expected, allow_outdated=True)
            is False
        )
        assert content.selection_state("t24")["summary_id"] != summary
        with pytest.raises(StateConflict):
            content.select_summary_candidate(
                "t24",
                summary,
                expected=SummarySelectionExpectation.from_state(content.selection_state("t24")),
            )


# --- auxiliary boundary nodes (not semantic rows) -----------------------------------
def test_aux_other_session_targets_and_snapshots_are_refused(world: Any) -> None:
    library, content, transcript = world
    for name in ("aux-a", "aux-b"):
        library.create_session(name)
    sources = {
        name: content.create_transcript(
            name, [Segment("a", 0, 10, "x", track_id="mic", timing_quality="clip")]
        )
        for name in ("aux-a", "aux-b")
    }
    foreign = content.create_summary(
        "aux-b", sources["aux-b"], [Claim("b", ("a",))], expected_transcript=None
    )
    snapshot = SummarySelectionExpectation.from_state(content.selection_state("aux-a"))
    before = content.selection_state("aux-a")
    with pytest.raises(ValidationError, match="^CONTENT_SELECTION_SESSION_MISMATCH$"):
        content.select_summary_candidate("aux-a", foreign, expected=snapshot, allow_outdated=True)
    with pytest.raises(ValidationError, match="^CONTENT_SELECTION_SESSION_MISMATCH$"):
        content.select_summary_candidate("aux-b", foreign, expected=snapshot, allow_outdated=True)
    assert content.selection_state("aux-a") == before


@pytest.mark.parametrize("change", ["provider_supported", "basis_missing"])
def test_aux_tampered_or_unrecorded_basis_needs_review(world: Any, change: str) -> None:
    library, content, transcript = world
    summary = content.create_summary(
        "bsession",
        transcript,
        [Claim("aux", ("audio",), "uncertain", "transcript")],
        expected_transcript=None,
    )
    if change == "provider_supported":
        _tamper(library, summary, lambda body: body["claims"][0].update(provider_basis="supported"))
    else:
        _tamper(library, summary, lambda body: body["claims"][0].pop("basis"))
    view = content.claim_evidence(summary)[0]
    if change == "provider_supported":
        # FIX1 G12R-05: an invalid stored value is a damaged record, never evidence.
        assert view["problem"] == "CONTENT_CLAIM_RECORD_INVALID" and view["refs"] == []
    else:
        assert (view["basis"], view["basis_recorded"], view["computed_basis"]) == (
            None,
            False,
            "transcript",
        )
    assert (
        claim_area(view["status"], view["basis"], view["provider_basis"], view["problem"])
        == REVIEW_AREA
    )
