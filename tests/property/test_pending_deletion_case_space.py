"""G05 TRACE: every command sequence of length 0..4 over seven commands (2,801 traces).

The model below keeps only (intent, g, catalog row, original files, tombstone, removal lock,
finalized) and its transitions are written by hand from section 5.3; it never imports
Library internals. Every trace runs on its own copy of a real library in OS TEMP. Traces are
independent, so they run in child processes; no prefix state is shared between traces.
Depth 5 and longer histories are not verified here. No device, model or network.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from recoryn.cli import _export
from recoryn.domain import StateConflict
from recoryn.storage import Library
from recoryn.storage import library as library_module
from tests.unit.test_pending_deletions import SID, build_template, clone

pytestmark = pytest.mark.property

COMMANDS = ("delete", "retry", "reopen", "unlock", "recover", "finalize", "export")
DEPTHS = (0, 1, 2, 3, 4)
TRACES = [seq for depth in DEPTHS for seq in itertools.product(COMMANDS, repeat=depth)]
TRACE_IDS = [f"G05-TRACE-{index:04d}" for index in range(len(TRACES))]


@dataclass
class Model:
    """Independent model state (section 5.3)."""

    intent: bool = False
    generation: int | None = None
    catalog: bool = True
    files: bool = True
    tombstone: bool = False
    locked: bool = True
    finalized: bool = False


def step(model: Model, command: str) -> str:
    """Hand-written transition table; returns the expected closed outcome label."""
    if command == "reopen":
        return "REOPENED"  # UI/process state is gone; the intent and the lock are not
    if command == "unlock":
        model.locked = False
        return "UNLOCKED"
    if command in ("delete", "retry"):
        if command == "retry" and not model.intent:
            return "NOT_PENDING"  # retry never creates a new deletion
        if model.tombstone:
            return "DELETED" if command == "delete" else "DELETED:ALREADY"
        model.intent = True
        if model.locked:
            return "PENDING:MEDIA_REMOVAL_FAILED"
        model.tombstone, model.files, model.catalog = True, False, False
        return "DELETED" if command == "delete" else "DELETED:NEW"
    if command == "recover":
        if model.intent:
            return "RECOVER:DELETE_PENDING:0"
        return "RECOVER:" + ("FINALIZED" if model.finalized else "INTERRUPTED") + ":0"
    if command == "finalize":
        if model.intent:
            return "REFUSED:DELETE_PENDING"
        already, model.finalized = model.finalized, True
        return "FINALIZED_ALREADY" if already else "FINALIZED"
    if model.intent:
        return "REFUSED:Session has a deletion intent"
    return "EXPORTED" if model.finalized else "NOT_FINALIZED"


@dataclass
class Run:
    root: Path
    library: Library
    model: Model = field(default_factory=Model)
    exports: int = 0


def observe(run: Run, command: str) -> str:
    library = run.library
    try:
        if command == "reopen":
            library.close()
            run.library = Library(run.root)
            return "REOPENED"
        if command == "unlock":
            unlock(run.root)
            return "UNLOCKED"
        if command == "delete":
            value = library.delete_session(SID)
        elif command == "retry":
            expected = run.model.generation or 1
            value = library.retry_deletion(SID, expected_generation=expected)
            if value["state"] != "NOT_PENDING":
                assert value["generation"] == run.model.generation, value
        elif command == "recover":
            value = library.recover_session(SID)
            return f"RECOVER:{value['state']}:{value['adopted'] + value['recovered']}"
        elif command == "finalize":
            value = library.finalize_unfinished(SID)
            return "FINALIZED_ALREADY" if value["already_finalized"] else "FINALIZED"
        else:
            run.exports += 1
            value = _export(library, SID, run.root.parent / f"export-{run.exports}")
            assert value["complete"] is True
            return "EXPORTED"
    except StateConflict as error:
        return "REFUSED:" + str(error)
    except ValueError as error:
        if str(error) == "Only finalized sessions can be exported":
            return "NOT_FINALIZED"
        raise
    if value["state"] == "DELETED_LOCAL":
        if command == "retry":
            return "DELETED:ALREADY" if value["already_deleted"] else "DELETED:NEW"
        return "DELETED"
    if value["state"] == "DELETE_PENDING":
        return "PENDING:" + str(value["reason"])
    return str(value["state"])


def originals(root: Path) -> dict[str, str]:
    tracks = root / "sessions" / SID / "tracks"
    if not tracks.exists():
        return {}
    return {
        path.relative_to(tracks).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(tracks.rglob("*"))
        if path.is_file()
    }


def check(run: Run, baseline: dict[str, str]) -> None:
    """Invariants after every prefix, from raw SQL and files (never product helpers)."""
    model, library, root = run.model, run.library, run.root
    row = library._db.execute(
        "SELECT generation,status FROM deleted_sessions WHERE session_id=?", (SID,)
    ).fetchone()
    journal = root / "deletion-journal" / f"{SID}.json"
    if model.intent:
        assert row is not None and journal.is_file()
        value = json.loads(journal.read_text(encoding="utf-8"))
        if model.generation is None:
            model.generation = row[0]
        # Never a lower or new generation after the first intent.
        assert row[0] == value["generation"] == model.generation
        assert row[1] == ("DELETED_LOCAL" if model.tombstone else "DELETE_PENDING")
        assert all(item.session_id != SID for item in library.list_sessions())
    else:
        assert row is None and not journal.exists()
    catalog = library._db.execute("SELECT 1 FROM sessions WHERE session_id=?", (SID,)).fetchone()
    assert (catalog is not None) == model.catalog
    if model.files:
        assert originals(root) == baseline  # every original byte kept
    else:
        assert not (root / "sessions" / SID).exists()  # never resurrected


def run_trace(index: int, template: Path, base: Path, baseline: dict[str, str]) -> str | None:
    commands = TRACES[index]
    root = clone(template, base / TRACE_IDS[index] / "library")
    LOCKED.add(str(root))
    run = Run(root, Library(root))
    done: list[str] = []
    try:
        check(run, baseline)
        for command in commands:
            expected = step(run.model, command)
            actual = observe(run, command)
            done.append(f"{command}->{actual}")
            assert actual == expected, f"expected {expected}"
            check(run, baseline)
        return None
    except BaseException as error:  # reported with the minimal failing prefix
        return f"{TRACE_IDS[index]} {' '.join(done)} | {type(error).__name__}: {error}"
    finally:
        unlock(root)
        run.library.close()


LOCKED: set[str] = set()


def unlock(root: Path) -> None:
    LOCKED.discard(str(root))


def blocker(original: Callable[[Path], None]) -> Callable[[Path], None]:
    """The test-owned removal lock: PermissionError while this trace's root is locked."""

    def remove(path: Path) -> None:
        if any(str(path).startswith(root + os.sep) for root in LOCKED):
            raise PermissionError("G05 trace removal blocker")
        original(path)

    return remove


def worker_main(arguments: list[str]) -> None:
    """Child process: run the assigned traces one at a time, then publish the results."""
    template, base, assigned, output = (Path(value) for value in arguments)
    library_module.remove_tree = blocker(library_module.remove_tree)  # type: ignore[assignment]
    baseline = originals(template)
    results = {
        TRACE_IDS[index]: run_trace(index, template, base, baseline)
        for index in json.loads(assigned.read_text(encoding="utf-8"))
    }
    temporary = output.with_name(output.name + ".tmp")
    temporary.write_text(json.dumps(results), encoding="utf-8")
    retry_denied(lambda: temporary.replace(output))


def retry_denied(call: Callable[[], object]) -> object:
    """Windows may briefly deny opening/renaming a just-written file (e.g. a scanner).
    Only that transient PermissionError is retried, for at most 30 seconds."""
    deadline = time.monotonic() + 30
    while True:
        try:
            return call()
        except PermissionError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.01)


ROOT = Path(__file__).resolve().parents[2]
WORKER = (
    "import sys\n"
    "from tests.property.test_pending_deletion_case_space import worker_main\n"
    "worker_main(sys.argv[1:])\n"
)


def child_environment() -> dict[str, str]:
    values = os.environ.copy()
    values["PYTHONPATH"] = os.pathsep.join((str(ROOT / "src"), str(ROOT)))
    values["PYTHONDONTWRITEBYTECODE"] = "1"
    values["PYTHONNOUSERSITE"] = "1"
    return values


@pytest.fixture(scope="module")
def template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_template(
        tmp_path_factory.mktemp("g05-trace-template") / "library", finalized=False
    )


DEPTH_CASES = [pytest.param(depth, id=f"G05-TRACE-depth-{depth}") for depth in DEPTHS]


@pytest.mark.parametrize("depth", DEPTH_CASES)
def test_bounded_command_sequences_follow_the_model(
    template: Path, tmp_path: Path, depth: int
) -> None:
    """Traces are independent, so they are spread over child processes (no shared prefix)."""
    assert len(originals(template)) == 6
    indexes = [index for index, seq in enumerate(TRACES) if len(seq) == depth]
    workers = max(1, min(16, os.cpu_count() or 4, len(indexes) // 20))
    processes = []
    for worker in range(workers):
        assigned = tmp_path / f"assigned-{worker}.json"
        assigned.write_text(json.dumps(indexes[worker::workers]), encoding="utf-8")
        output = tmp_path / f"results-{worker}.json"
        log = tmp_path / f"worker-{worker}.log"
        with log.open("wb") as stream:
            process = subprocess.Popen(
                [sys.executable, "-W", "error::ResourceWarning", "-c", WORKER]
                + [str(template), str(tmp_path / f"w{worker}"), str(assigned), str(output)],
                cwd=ROOT,
                stdout=stream,
                stderr=subprocess.STDOUT,
                env=child_environment(),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        processes.append((process, output, log))
    results: dict[str, str | None] = {}
    try:
        for process, output, log in processes:
            assert process.wait(600) == 0, log.read_text(errors="replace")
            text = log.read_text(errors="replace")
            assert "Warning" not in text and "Exception ignored" not in text, text
            published = retry_denied(lambda path=output: path.read_text(encoding="utf-8"))
            assert isinstance(published, str)
            for case_id, failure in json.loads(published).items():
                assert case_id not in results, case_id
                results[case_id] = failure
    finally:
        for process, _, _ in processes:
            if process.poll() is None:
                process.kill()
                process.wait(60)
    executed = sorted(results)
    (tmp_path / "trace-ids.json").write_text(json.dumps(executed), encoding="utf-8")
    failures = [failure for failure in results.values() if failure is not None]
    print(json.dumps({"depth": depth, "executed": len(executed), "workers": workers}))
    assert failures == [], "\n".join(sorted(failures)[:5])
    assert executed == sorted(TRACE_IDS[index] for index in indexes)
    assert len(executed) == len(COMMANDS) ** depth


def test_declared_trace_denominator_is_complete_and_unique() -> None:
    assert len(TRACES) == 1 + 7 + 49 + 343 + 2401 == 2801
    assert len(set(TRACES)) == 2801 and len(set(TRACE_IDS)) == 2801
    assert TRACE_IDS == [f"G05-TRACE-{i:04d}" for i in range(2801)]
    core = ("delete", "reopen", "unlock", "retry")  # section 5.3's key length-4 trace
    assert core in TRACES
