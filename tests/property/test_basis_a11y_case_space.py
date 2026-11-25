"""G12 / G-P12 case space: the independent census of all 2,506 rows and three models.

The family formulas are transcribed from the G12 contract (section 6.1 and the amendment
section 4, decision 7 included): every ID must be parametrized, batched or named by
exactly one node. The announcement model, the canonical-basis precedence and the
browse-writes-nothing property use hand rules and never call the product functions to
compute an expectation.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from itertools import count
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from recoryn.content import Claim, ContentStore, Segment, canonical_basis
from recoryn.storage import Library
from tests.integration import test_basis_publication as integration
from tests.ui import test_basis_a11y_ui as ui
from tests.unit import test_claim_basis as unit

FAMILIES = {
    "B": ("G12-B-{:03}", 3 * 4 * 8 * 8),
    "W": ("G12-W-{:03}", 7 * 5 * 4),
    "P": ("G12-P-{:03}", 3 * 4 * 3 * 2 * 4),
    "K": ("G12-K-{:03}", 4 * 7 * 4 * 3),
    "E": ("G12-E-{:02}", 4 * 2 * 2 * 4),
    "F": ("G12-F-{:03}", 6 * 3 * 4 * 2 * 2),
    "N": ("G12-N-{:02}", 12 * 2 * 2 * 2),
    "C": ("G12-C-{:03}", 3 * 4 * 5 * 3 * 2),
    "R": ("G12-R-{:02}", 3 * 2 * 3 * 2),
    "D": ("G12-D-{:02}", 6 * 4 * 2 * 2),
    "T": ("G12-T-{:02}", 26),
    "Z": ("G12-Z-{:02}", 2 * 2 * 2),
    # FIX1: the independent review's counterexamples and untested rules (G12R-01..09).
    "X": ("G12-X-{:02}", 16),
    "Y": ("G12-Y-{:02}", 3 * 2 * 3 + 2 * 3 + 3 * 3),
}
_serial = count(1)


def ids(family: str) -> list[str]:
    pattern, size = FAMILIES[family]
    return [pattern.format(n) for n in range(1, size + 1)]


def _parametrized(function: Any) -> list[str]:
    """The ids actually attached to a test function's parametrize mark."""
    found: list[str] = []
    for mark in getattr(function, "pytestmark", []):
        if mark.name == "parametrize":
            found.extend(mark.kwargs.get("ids") or [])
    return found


def declared() -> list[str]:
    nodes = [
        *unit.B_IDS,  # batched: one node walks every B row with a strict zip
        *_parametrized(unit.test_w_parser_normalization_and_canonical_store),
        *_parametrized(unit.test_t_data_and_type_boundaries),
        *_parametrized(integration.test_p_publication_keeps_reference_basis_candidates_and_sources),
        *_parametrized(integration.test_d_candidate_selection_compares_the_whole_snapshot),
        *_parametrized(integration.test_t_selection_rollback_and_partial_job),
        *_parametrized(ui.test_k_keys_activate_only_valid_targets_once),
        *_parametrized(ui.test_e_editing_and_filters_never_seek_or_lose_input),
        *_parametrized(ui.test_f_modals_default_to_no_and_return_focus_only_when_safe),
        *_parametrized(ui.test_n_announcements_once_per_meaning_and_never_move_focus),
        *_parametrized(ui.test_c_browse_then_confirm_selects_only_the_presented_snapshot),
        *_parametrized(ui.test_r_polls_keep_browsing_search_and_edits_and_never_select),
        *_parametrized(ui.test_z_no_claims_partial_and_legacy_never_read_as_verified),
        *_parametrized(ui.test_t_ui_boundaries),
        *_parametrized(ui.test_x_fix1_rows),
        *_parametrized(ui.test_y_followup_rows),
    ]
    return nodes


def test_full_amended_denominator() -> None:
    every = [case for family in FAMILIES for case in ids(family)]
    assert len(every) == len(set(every)) == 2_555
    assert sum(size for _, size in FAMILIES.values()) == 2_232 + 96 + 144 + 32 + 2 + 16 + 33


def test_every_id_is_claimed_exactly_once() -> None:
    every = {case for family in FAMILIES for case in ids(family)}
    nodes = declared()
    missing, extra = every - set(nodes), set(nodes) - every
    duplicates = len(nodes) - len(set(nodes))
    assert (len(missing), duplicates, len(extra)) == (0, 0, 0), (
        sorted(missing)[:5],
        sorted(extra)[:5],
    )


def test_family_tuples_match_their_ids_and_axes() -> None:
    pairs = (
        (unit.B, unit.B_IDS),
        (unit.W, unit.W_IDS),
        (integration.P, integration.P_IDS),
        (integration.D, integration.D_IDS),
        (ui.K, ui.K_IDS),
        (ui.E, ui.E_IDS),
        (ui.F, ui.F_IDS),
        (ui.N, ui.N_IDS),
        (ui.C, ui.C_IDS),
        (ui.R, ui.R_IDS),
        (ui.Z, ui.Z_IDS),
        (ui.Y, ui.Y_IDS),
    )
    for rows, names in pairs:
        assert len(rows) == len(set(rows)) == len(names) == len(set(names))
    assert len(unit.T_UNIT) + len(integration.T_INTEGRATION) + len(ui.T_UI) == 26
    # The amendment's axes, by hand.
    assert len(ui.K_WIDGETS) == 7 and len(ui.F_MODALS) == 6 and len(ui.N_STATES) == 12
    assert {"clock_reset", "legacy_adoption", "unknown_retry"} <= set(ui.F_MODALS)
    assert {"continue", "settings_nav"} <= set(ui.K_WIDGETS)
    assert {"BLOCKED", "BACKOFF", "ABANDONED", "FAILED"} <= set(ui.N_STATES)
    assert (len(ui.Y_F), len(ui.Y_B), len(ui.Y_D)) == (18, 6, 9)


# --- the announcement state model ---------------------------------------------------
KINDS = ui.N_STATES
operations = st.lists(
    st.one_of(
        st.tuples(
            st.just("announce"),
            st.sampled_from(KINDS),
            st.integers(0, 2),
            st.booleans(),
        ),
        st.tuples(st.just("advance")),
    ),
    max_size=24,
)


@settings(max_examples=150, deadline=None, derandomize=True, database=None)
@given(operations)
def test_announcer_matches_the_once_per_meaning_model(
    app: Any, steps: list[tuple[Any, ...]]
) -> None:
    from recoryn.ui import a11y

    sink = ui.Sink()
    announcer = a11y.Announcer(sink)
    generation, seen, expected = 0, set(), []
    for step in steps:
        if step[0] == "advance":
            announcer.advance("content")
            generation, seen = generation + 1, set()
            continue
        _, kind, version, stale = step
        used = generation - 1 if stale else generation
        announcer.announce("content", app, kind, kind, version=version, generation=used)
        key = (used, version, kind)
        # FIX1 G12R-07: a meaning already announced in this generation stays silent,
        # even with other announcements in between.
        if used == generation and key not in seen:
            expected.append((kind, "assertive" if kind in ui.ASSERTIVE else "polite"))
            seen.add(key)
    assert [(message, politeness) for _, message, politeness in sink.events] == expected


@pytest.fixture(scope="module")
def app() -> Any:
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


# --- canonical basis precedence -----------------------------------------------------
def precedence(provenances: set[str], refs: bool) -> str:
    """G12 3.1 by hand: unresolved, then user assertion, then transcript; no refs = inference."""
    if not refs:
        return "model_inference"
    for provenance, basis in (
        ("unresolved", "unresolved"),
        ("user_assertion", "user_assertion"),
        ("audio", "transcript"),
    ):
        if provenance in provenances:
            return basis
    raise AssertionError("a reference always has a provenance")


PROVENANCE = ("audio", "user_assertion", "unresolved")
references = st.lists(st.sampled_from(PROVENANCE), min_size=0, max_size=6)


@settings(max_examples=200, deadline=None, derandomize=True, database=None)
@given(references, st.randoms(use_true_random=False))
def test_canonical_basis_is_order_free_and_ignores_the_adapter(
    kinds: list[str], random: Any
) -> None:
    shuffled = list(kinds)
    random.shuffle(shuffled)
    want = precedence(set(kinds), bool(kinds))
    assert canonical_basis(set(kinds), bool(kinds)) == want
    assert canonical_basis(set(shuffled), bool(shuffled)) == want


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Any:
    root = tmp_path_factory.mktemp("g12-property")
    with Library(root / "library") as library, ContentStore(library) as content:
        yield library, content


@settings(max_examples=30, deadline=None, derandomize=True, database=None)
@given(
    st.lists(st.sampled_from(PROVENANCE), min_size=1, max_size=5),
    st.randoms(use_true_random=False),
    st.sampled_from((None, "transcript", "user_assertion", "model_inference")),
)
def test_stored_basis_survives_ref_reordering(
    store: Any, kinds: list[str], random: Any, provider: Any
) -> None:
    library, content = store
    session = f"prop{next(_serial)}"
    library.create_session(session)
    segments = [
        Segment(
            f"s{index}",
            index * 10,
            index * 10 + 5,
            f"text {index}",
            provenance=kind,
            track_id="mic",
        )
        for index, kind in enumerate(kinds)
    ]
    source = content.create_transcript(session, segments)
    refs = [segment.segment_id for segment in segments]
    reordered = list(refs)
    random.shuffle(reordered)
    first = content.create_summary(
        session, source, [Claim("a", tuple(refs), "uncertain", provider)]
    )
    second = content.create_summary(
        session, source, [Claim("b", tuple(reordered), "uncertain", provider)]
    )
    want = precedence(set(kinds), True)
    views = [content.claim_evidence(revision)[0] for revision in (first, second)]
    assert [view["basis"] for view in views] == [want, want]
    assert all(view["provider_basis"] == provider and view["problem"] is None for view in views)


# --- browsing never writes -----------------------------------------------------------
actions = st.lists(
    st.one_of(
        st.tuples(st.just("browse"), st.integers(0, 3)),
        st.tuples(st.just("poll")),
        st.tuples(st.just("search"), st.sampled_from(("", "spoken", "zzz"))),
        st.tuples(st.just("key"), st.sampled_from(("Tab", "Arrow"))),
    ),
    max_size=12,
)


@settings(max_examples=25, deadline=None, derandomize=True, database=None)
@given(actions)
def test_browsing_polling_and_moving_never_select(
    app: Any, store: Any, steps: list[tuple[Any, ...]]
) -> None:
    from recoryn.ui.content import ContentPanel

    library, content = store
    session = f"browse{next(_serial)}"
    library.create_session(session)
    source = content.create_transcript(session, list(ui.K_SEGMENTS))
    content.create_summary(session, source, [Claim("selected", ("a",))], expected_transcript=source)
    for text in ("one", "two"):
        content.create_summary(session, source, [Claim(text, ("a",))], expected_summary=None)
    before = content.selection_state(session)
    events = _events(library.db_path, session)
    panel = ContentPanel(content, ui.Ops())
    panel.show()
    try:
        panel.load(session)
        for step in steps:
            if step[0] == "browse":
                if panel.summary_candidates.count():
                    panel.summary_candidates.setCurrentIndex(
                        step[1] % panel.summary_candidates.count()
                    )
            elif step[0] == "poll":
                panel.load(session)
            elif step[0] == "search":
                panel.search.setText(step[1])
            else:
                ui.press(panel.claims, step[1])
                ui.press(panel.table, step[1])
        assert content.selection_state(session) == before
        assert _events(library.db_path, session) == events
    finally:
        ui.dispose(panel)


def _events(db: Path, session: str) -> int:
    with closing(sqlite3.connect(db)) as connection:
        return connection.execute(
            "SELECT COUNT(*) FROM content_events WHERE session_id=?", (session,)
        ).fetchone()[0]
