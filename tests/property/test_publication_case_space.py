"""Q23 bounded publication histories, independent prefix oracle and isolated mutant."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from recoryn.content import ContentStore, Segment
from recoryn.domain import AudioFormat, PCMBlock, SessionState, StateConflict
from recoryn.jobs import AttemptRecord, JobStore
from recoryn.storage import ChunkWriter, Library

pytestmark = pytest.mark.property

EVENTS = ("ER", "EW", "SR", "SW", "PR", "PW", "C")
EDGES = (("ER", "EW"), ("EW", "SW"), ("SR", "SW"), ("PR", "PW"))
# SW is last within edit/selection; ER<EW leaves 3!/2=3 internal orders.
# Interleave their four slots with the publication pair and cancellation.
ORDER_DENOMINATOR = 3 * math.comb(7, 4) * math.comb(3, 2)
ROW_DENOMINATOR = 2 * ORDER_DENOMINATOR


def histories() -> tuple[tuple[str, ...], ...]:
    return tuple(
        order
        for order in itertools.permutations(EVENTS)
        if all(order.index(before) < order.index(after) for before, after in EDGES)
    )


def case_id(complete: bool, order: tuple[str, ...]) -> str:
    return ("full" if complete else "partial") + ":" + "-".join(order)


CASES = tuple((complete, order) for complete in (False, True) for order in histories())


@pytest.fixture(scope="module")
def executed_ids() -> list[str]:
    return []


@pytest.fixture(scope="module")
def observations() -> dict[str, list[str]]:
    return {"prefix": [], "sr_before_ew": [], "stale_sw": []}


@dataclass
class Oracle:
    """Labels and contract transitions only; no product transition/selection helpers."""

    active: str = "base"
    revisions: set[str] = field(default_factory=lambda: {"base"})
    captured: dict[str, str] = field(default_factory=dict)
    state: str = "RUNNING"
    attempt_state: str = "RUNNING"
    result: str | None = None
    cancelled: bool = False
    checkpoint: bool = False
    content_events: int = 1

    def advance(self, event: str, complete: bool) -> bool:
        """Return whether the command succeeds; stale/after-cancel inputs stay in F."""
        if event in {"ER", "SR", "PR"}:
            self.captured[event] = self.active
        elif event == "EW":
            self.revisions.add("edit")
            self.content_events += 1
            if self.active == self.captured["ER"]:
                self.active = "edit"
        elif event == "SW":
            if self.active != self.captured["SR"]:
                return False
            self.active = "edit"
            self.content_events += 1
        elif event == "C":
            if self.state != "SUCCEEDED":
                self.cancelled = True
                self.state = "CANCEL_REQUESTED"
        elif event == "PW":
            if self.cancelled:
                return False
            self.revisions.add("machine")
            self.content_events += 1
            if complete:
                if self.active == self.captured["PR"]:
                    self.active = "machine"
                self.state = self.attempt_state = "SUCCEEDED"
                self.result = "machine"
            else:
                self.checkpoint = True
        return True


@dataclass
class Fixture:
    library: Library
    content: ContentStore
    jobs: JobStore
    attempt: AttemptRecord
    ids: dict[str, str]
    originals: dict[Path, str]
    base: dict[str, Any]


@contextmanager
def fixture(root: Path) -> Iterator[Fixture]:
    with (
        Library(root) as library,
        ContentStore(library) as content,
        JobStore(library.db_path) as jobs,
    ):
        library.create_session("s")
        block = PCMBlock(
            "s",
            "mic",
            "epoch",
            0,
            AudioFormat(8000, 1),
            4,
            b"\x01\x00\x02\x00\x03\x00\x04\x00",
            0,
            0,
        )
        writer = ChunkWriter(root, block)
        writer.append(block)
        descriptor = writer.seal()
        library.register_chunk(descriptor)
        library.transition("s", SessionState.FINALIZING, library.get_session("s").state_version)
        library.finalize_session("s")
        original_paths = list((root / descriptor.relative_path).iterdir()) + [
            root / "sessions/s/manifest.json"
        ]
        originals = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in original_paths}
        base = content.create_transcript("s", [Segment("line", 0, 1, "original", track_id="mic")])
        job = jobs.create("transcription", "fixed-input")
        jobs.bind_session(job.job_id, "s")
        attempt = jobs.claim(job.job_id, "q23")
        yield Fixture(
            library, content, jobs, attempt, {"base": base}, originals, content.transcript(base)
        )


def publish(f: Fixture, complete: bool, expected: str) -> str:
    return f.content.publish_transcript(
        f.jobs,
        f.attempt,
        "s",
        [Segment("line", 0, 1, "machine", track_id="mic")],
        complete=complete,
        expected_active=expected,
        parent_revision_id=f.ids["base"],
    )


def assert_state(f: Fixture, model: Oracle, complete: bool, context: str) -> None:
    """Observe public revisions and independent SQLite rows after each commit."""
    inverse = {value: key for key, value in f.ids.items()}
    active = f.content.active_transcript("s")
    assert active is not None
    assert inverse[active["revision_id"]] == model.active, "Q23_ACTIVE_CAS:" + context
    revisions = f.content.list_revisions("s", "transcript")
    assert {inverse[row["revision_id"]] for row in revisions} == model.revisions, context
    assert {inverse[row["revision_id"]] for row in revisions if row["selected"]} == {model.active}
    assert f.content.transcript(f.ids["base"]) == f.base
    for row in revisions:
        name = inverse[row["revision_id"]]
        assert (
            row["segments"][0]["text"]
            == {"base": "original", "edit": "edited", "machine": "machine"}[name]
        )
        if name == "edit":
            assert row["kind"] == "edited" and row["parent_revision_id"] == f.ids["base"]
            assert row["segments"][0]["provenance"] == "user_assertion"
            assert row["segments"][0]["timing_quality"] == "unverified"
        if name == "machine":
            assert row["complete"] is complete
            assert row["kind"] == ("corrected" if complete else "draft")
            assert row["parent_revision_id"] == f.ids["base"]
    job = f.jobs.get(f.attempt.job_id)
    expected_ref = f.ids[model.result] if model.result else None
    assert (job.state.value, job.cancel_requested, job.result_ref) == (
        model.state,
        model.cancelled,
        expected_ref,
    ), context
    assert job.fence == f.attempt.fence + int(model.cancelled), context
    with closing(sqlite3.connect(f.library.db_path)) as db:
        assert db.execute(
            "SELECT state,result_ref,fence FROM attempts WHERE attempt_id=?",
            (f.attempt.attempt_id,),
        ).fetchone() == (model.attempt_state, expected_ref, f.attempt.fence), context
        assert db.execute("SELECT COUNT(*) FROM content_events").fetchone() == (
            model.content_events,
        ), context
        assert db.execute("SELECT COUNT(*) FROM events WHERE state='SUCCEEDED'").fetchone() == (
            int(model.state == "SUCCEEDED"),
        ), context
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        checkpoints = (
            db.execute(
                "SELECT result_ref FROM job_checkpoints WHERE job_id=?", (f.attempt.job_id,)
            ).fetchall()
            if "job_checkpoints" in tables
            else []
        )
        assert checkpoints == ([(f.ids["machine"],)] if model.checkpoint else []), context
    assert {
        path: hashlib.sha256(path.read_bytes()).hexdigest() for path in f.originals
    } == f.originals, context


@pytest.mark.parametrize("complete,order", CASES, ids=[case_id(*row) for row in CASES])
def test_publication_dag(
    complete: bool,
    order: tuple[str, ...],
    tmp_path: Path,
    executed_ids: list[str],
    observations: dict[str, list[str]],
) -> None:
    name = case_id(complete, order)
    with fixture(tmp_path) as f:
        model, captured = Oracle(), {}
        assert_state(f, model, complete, "initial")
        observations["prefix"].append(name + "/initial")
        for event in order:
            accepted = model.advance(event, complete)
            if event in {"ER", "SR", "PR"}:
                active = f.content.active_transcript("s")
                assert active is not None
                captured[event] = active["revision_id"]
            elif event == "EW":
                f.ids["edit"] = f.content.edit_segment(
                    "s", f.ids["base"], "line", "edited", expected_active=captured["ER"]
                )
            elif event == "SW":
                assert (
                    f.content.select_transcript("s", f.ids["edit"], expected_active=captured["SR"])
                    is accepted
                )
                if not accepted:
                    observations["stale_sw"].append(name)
            elif event == "PW":
                if accepted:
                    f.ids["machine"] = publish(f, complete, captured["PR"])
                else:
                    with pytest.raises(StateConflict):
                        publish(f, complete, captured["PR"])
            else:
                f.jobs.cancel(f.attempt.job_id)
            assert_state(f, model, complete, case_id(complete, order) + "/" + event)
            observations["prefix"].append(name + "/" + event)
    if order.index("SR") < order.index("EW"):
        observations["sr_before_ew"].append(name)
    executed_ids.append(case_id(complete, order))


def test_case_space_has_exact_unique_ids_and_all_invalid_outcomes_are_retained() -> None:
    assert math.factorial(len(EVENTS)) == 5040 and ORDER_DENOMINATOR == 315
    assert ROW_DENOMINATOR == 630
    ids = [case_id(*row) for row in CASES]
    assert len(ids) == len(set(ids)) == ROW_DENOMINATOR
    # Independent constructive enumeration: choose the 4 positions of edit/selection,
    # then 2 of the remaining 3 for publication; cancellation takes the last slot.
    # Enumerate the internal orders explicitly, independently of EDGES/filtering.
    expected = set()
    for edit_slots in itertools.combinations(range(7), 4):
        rest = set(range(7)) - set(edit_slots)
        for pub_slots in itertools.combinations(sorted(rest), 2):
            for internal in (
                ("ER", "EW", "SR", "SW"),
                ("ER", "SR", "EW", "SW"),
                ("SR", "ER", "EW", "SW"),
            ):
                row = ["C"] * 7
                for slot, event in zip(edit_slots, internal, strict=True):
                    row[slot] = event
                for slot, event in zip(pub_slots, ("PR", "PW"), strict=True):
                    row[slot] = event
                expected.add(tuple(row))
    assert set(histories()) == expected
    assert not (expected - set(histories())) and not (set(histories()) - expected)
    outcomes: set[tuple[str, bool]] = set()
    for complete, order in CASES:
        model = Oracle()
        for event in order:
            accepted = model.advance(event, complete)
            if event in {"PW", "SW"}:
                outcomes.add((event, accepted))
    assert outcomes == {("PW", True), ("PW", False), ("SW", True), ("SW", False)}


@pytest.mark.parametrize("complete", (False, True), ids=("partial", "full"))
@pytest.mark.parametrize("first", ("publish", "cancel"))
def test_three_connections_observe_atomic_first_commit(
    first: str, complete: bool, tmp_path: Path, executed_ids: list[str]
) -> None:
    with (
        fixture(tmp_path) as f,
        ContentStore(f.library) as editor,
        JobStore(f.library.db_path) as canceller,
    ):
        gate, release, edit_called, other_called, rival_sql = (threading.Event() for _ in range(5))
        expired = []
        connection = f.jobs._db if first == "publish" else canceller._db
        needle = "INSERT INTO content_events" if first == "publish" else "INSERT INTO events"

        def pause_commit(statement: str) -> None:
            if statement.lstrip().startswith(needle) and not gate.is_set():
                gate.set()
                if not release.wait(5):
                    expired.append("gate expired")

        connection.set_trace_callback(pause_commit)
        rival = canceller._db if first == "publish" else f.jobs._db
        rival.set_trace_callback(
            lambda sql: (
                rival_sql.set() if sql.strip().upper().startswith("BEGIN IMMEDIATE") else None
            )
        )

        def pub() -> str | None:
            if first == "cancel":
                other_called.set()
            try:
                return publish(f, complete, f.ids["base"])
            except StateConflict:
                return None

        def cancel() -> None:
            if first == "publish":
                other_called.set()
            canceller.cancel(f.attempt.job_id)

        def edit() -> str:
            edit_called.set()
            return editor.edit_segment(
                "s", f.ids["base"], "line", "edited", expected_active=f.ids["base"]
            )

        with ThreadPoolExecutor(max_workers=3) as pool:
            leading = pool.submit(pub if first == "publish" else cancel)
            try:
                assert gate.wait(5)
                # The leading transaction has already changed rows, but a distinct
                # SQLite reader must see only the previous committed snapshot.
                with closing(sqlite3.connect(f.library.db_path)) as observer:
                    assert observer.execute(
                        "SELECT state,result_ref,fence FROM jobs WHERE job_id=?",
                        (f.attempt.job_id,),
                    ).fetchone() == ("RUNNING", None, f.attempt.fence)
                    assert observer.execute(
                        "SELECT transcript_id FROM content_selections WHERE session_id='s'"
                    ).fetchone() == (f.ids["base"],)
                    assert observer.execute(
                        "SELECT COUNT(*) FROM content_revisions"
                    ).fetchone() == (1,)
                    assert observer.execute("SELECT COUNT(*) FROM content_events").fetchone() == (
                        1,
                    )
                    assert observer.execute(
                        "SELECT state,result_ref,fence FROM attempts WHERE attempt_id=?",
                        (f.attempt.attempt_id,),
                    ).fetchone() == ("RUNNING", None, f.attempt.fence)
                trailing = pool.submit(cancel if first == "publish" else pub)
                assert other_called.wait(5) and rival_sql.wait(5)
                editing = pool.submit(edit)
                assert edit_called.wait(5) and not editing.done() and not trailing.done()
            finally:
                release.set()
            first_result = leading.result(timeout=5)
            other_result = trailing.result(timeout=5)
            f.ids["edit"] = editing.result(timeout=5)
        connection.set_trace_callback(None)
        rival.set_trace_callback(None)
        assert not expired
        machine = first_result if first == "publish" else other_result
        model = Oracle()
        model.captured = {"PR": "base", "ER": "base"}
        if first == "publish":
            model.advance("PW", complete)
            assert isinstance(machine, str)
            f.ids["machine"] = machine
            model.advance("EW", complete)
            model.advance("C", complete)
        else:
            model.advance("C", complete)
            assert machine is None
            model.advance("EW", complete)
        assert_state(f, model, complete, "three-real-connections-after-commit")
    executed_ids.append("sql:" + first + ":" + ("full" if complete else "partial"))


def test_completed_case_ids_have_no_missing_or_duplicate_rows(
    executed_ids: list[str], observations: dict[str, list[str]]
) -> None:
    expected = {case_id(*row) for row in CASES} | {
        "sql:publish:full",
        "sql:publish:partial",
        "sql:cancel:full",
        "sql:cancel:partial",
    }
    observed = set(executed_ids)
    assert len(executed_ids) == len(observed) == ROW_DENOMINATOR + 4
    assert expected - observed == set() and observed - expected == set()
    expected_prefixes = {
        case_id(complete, order) + "/" + prefix
        for complete, order in CASES
        for prefix in ("initial", *EVENTS)
    }
    assert len(observations["prefix"]) == len(set(observations["prefix"])) == 5040
    assert set(observations["prefix"]) == expected_prefixes
    expected_early_read = {
        case_id(complete, order)
        for complete, order in CASES
        if order.index("SR") < order.index("EW")
    }
    assert len(expected_early_read) == 2 * 2 * math.comb(7, 4) * math.comb(3, 2) == 420
    assert set(observations["sr_before_ew"]) == expected_early_read
    assert len(observations["sr_before_ew"]) == 420
    assert len(observations["stale_sw"]) == len(set(observations["stale_sw"]))
    assert set(observations["stale_sw"]) <= expected
    # The review counterexample must execute, including the actual stale rejection.
    counterexample = ("ER", "SR", "EW", "SW", "PR", "PW", "C")
    assert {case_id(mode, counterexample) for mode in (False, True)} <= set(
        observations["stale_sw"]
    )
    print(
        json.dumps(
            {
                "dag_denominator": ROW_DENOMINATOR,
                "actual_dag_ids": sum(not name.startswith("sql:") for name in executed_ids),
                "actual_sql_ids": sum(name.startswith("sql:") for name in executed_ids),
                "missing": len(expected - observed),
                "unexpected": len(observed - expected),
                "duplicate": len(executed_ids) - len(observed),
                "initial_and_prefix_observations": len(observations["prefix"]),
                "sr_before_ew": len(observations["sr_before_ew"]),
                "stale_sw_rejected": len(observations["stale_sw"]),
            }
        )
    )


MUTANT = "PUB_CAS_DROP_EXPECTED"
MUTANT_ORDER = ("PR", "ER", "EW", "SR", "SW", "PW", "C")


def test_named_cas_mutant_is_killed_by_target_assertion(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    source = root / "src/recoryn/content/store.py"
    original = source.read_bytes()
    index = root / ".git/index"
    index_before = index.read_bytes() if index.is_file() else None
    isolated = tmp_path / "isolated"
    shutil.copytree(
        root / "src/recoryn", isolated / "src/recoryn", ignore=shutil.ignore_patterns("__pycache__")
    )
    test = isolated / "test_publication_case_space.py"
    shutil.copyfile(Path(__file__), test)
    shutil.copyfile(root / "pyproject.toml", isolated / "pyproject.toml")
    selected = "test_publication_dag[" + case_id(True, MUTANT_ORDER) + "]"
    # coverage's subprocess patch uses COVERAGE_PROCESS_CONFIG at site startup;
    # pytest-cov/PYTEST_ADDOPTS can also restart instrumentation in a child.
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith(("COVERAGE", "COV_CORE", "PYTEST"))
    }
    environment.update(PYTHONDONTWRITEBYTECODE="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    program = """import pathlib, sys
sys.dont_write_bytecode = True
sys.path.insert(0, str(pathlib.Path(sys.argv[1]) / 'src'))
import coverage
assert coverage.Coverage.current() is None, 'Q23_CHILD_COVERAGE_ACTIVE'
import recoryn.content.store as store
assert pathlib.Path(store.__file__).resolve().is_relative_to(pathlib.Path(sys.argv[1]).resolve())
import pytest
raise SystemExit(pytest.main(sys.argv[2:]))
"""

    def run(name: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                program,
                str(isolated),
                str(test) + "::" + selected,
                "-c",
                str(isolated / "pyproject.toml"),
                "-o",
                "pythonpath=" + str(isolated / "src"),
                "-p",
                "no:cacheprovider",
                "--basetemp",
                str(tmp_path / name),
                "-q",
                "--tb=short",
                "-W",
                "error::ResourceWarning",
            ],
            cwd=isolated,
            env=environment,
            capture_output=True,
            text=True,
            timeout=40,
        )

    baseline = run("normal")
    assert baseline.returncode == 0, baseline.stdout + baseline.stderr
    target = isolated / "src/recoryn/content/store.py"
    text = target.read_text(encoding="utf-8")
    needle = (
        "selected = select and (complete or allow_draft_selection) and active == expected_active"
    )
    assert text.count(needle) == 1
    target.write_text(
        text.replace(needle, "selected = select and (complete or allow_draft_selection)"),
        encoding="utf-8",
    )
    mutated = run("mutant")
    assert mutated.returncode == 1, mutated.stdout + mutated.stderr
    assert "Q23_ACTIVE_CAS:" in mutated.stdout and "AssertionError" in mutated.stdout
    assert "1 failed" in mutated.stdout and selected in mutated.stdout
    assert "ImportError" not in mutated.stdout + mutated.stderr
    assert source.read_bytes() == original
    assert (index.read_bytes() if index.is_file() else None) == index_before
    print(
        json.dumps(
            {
                "mutant": MUTANT,
                "normal": baseline.returncode,
                "mutant_exit": mutated.returncode,
                "assertion": "Q23_ACTIVE_CAS",
                "target_node": selected,
                "source_sha256": hashlib.sha256(original).hexdigest(),
                "mutant_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            }
        )
    )
