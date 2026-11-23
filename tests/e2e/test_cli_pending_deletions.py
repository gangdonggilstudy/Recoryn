"""G05 CLI: `list --delete-pending`, `delete ID --retry-only` and their closed exit/codes.

Each row runs once in-process (`main`) and once as a new `python -m recoryn` process that
imports this checkout's src. Expected outputs and exits are the hand table of section 4.2.
No device, model or network.
"""

from __future__ import annotations

import itertools
import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from recoryn.cli import main
from recoryn.jobs import JobStore
from recoryn.storage import Library
from tests.unit.test_pending_deletions import SID, build_template, clone, media

pytestmark = pytest.mark.e2e

SRC = Path(__file__).resolve().parents[2] / "src"
COMMANDS = {
    "plain_list": ["list"],
    "unfinished_list": ["list", "--unfinished"],
    "pending_list": ["list", "--delete-pending"],
    "retry": ["delete", SID, "--retry-only"],
}
FIXTURES = ("normal", "pending", "completed", "damaged")
MODES = ("main", "process")
CLI_DIMENSIONS = list(itertools.product(tuple(COMMANDS), FIXTURES, MODES))
CLI_CASES = [
    pytest.param(*dims, id=f"G05-CLI-{index:04d}") for index, dims in enumerate(CLI_DIMENSIONS)
]
PARSER_CASES = [
    pytest.param(args, id=f"G05-CLI-{32 + index:04d}")
    for index, args in enumerate(
        (
            ["list", "--unfinished", "--delete-pending"],
            ["delete", SID, "--expected-generation", "3"],
            ["delete", SID, "--retry-only", "--expected-generation", "x1"],
        )
    )
]


def environment() -> dict[str, str]:
    values = os.environ.copy()
    values["PYTHONPATH"] = str(SRC)
    values["PYTHONDONTWRITEBYTECODE"] = "1"
    values["PYTHONNOUSERSITE"] = "1"
    return values


def build(template: Path, root: Path, fixture: str) -> int | None:
    """Returns the deletion generation the fixture created, if any."""
    clone(template, root)
    if fixture == "damaged":
        (root / "deletion-journal" / ".tmp-interrupted").write_bytes(b"{")
        return None
    if fixture == "normal":
        return None
    with Library(root) as library:
        if fixture == "pending":
            with JobStore(library.db_path) as jobs:
                jobs.create("g05-unbound", "legacy-input")  # unbound work keeps media
            result = library.delete_session(SID)
            assert result["reason"] == "ACTIVE_READER_OR_WRITER"
        else:
            assert library.delete_session(SID)["state"] == "DELETED_LOCAL"
        return int(
            library._db.execute(
                "SELECT generation FROM deleted_sessions WHERE session_id=?", (SID,)
            ).fetchone()[0]
        )


def expected(command: str, fixture: str, generation: int | None) -> tuple[int, Any]:
    """Section 4.2, written by hand: (exit code, JSON output or closed error code)."""
    if fixture == "damaged":
        return 1, {
            "plain_list": None,  # the historical list error carries no code
            "unfinished_list": "STORAGE_ERROR",
            "pending_list": "DELETION_HISTORY_UNAVAILABLE",
            "retry": "DELETION_HISTORY_UNAVAILABLE",
        }[command]
    if command == "plain_list":
        return 0, [{"session_id": SID, "state": "FINALIZED"}] if fixture == "normal" else []
    if command == "unfinished_list":
        return 0, []
    if command == "pending_list":
        if fixture != "pending":
            return 0, []
        return 0, [
            {
                "session_id": SID,
                "generation": generation,
                "state": "DELETE_PENDING",
                "deleted": False,
                "db_status": "DELETE_PENDING",
                "intent_sources": ["db", "journal"],
                "session_present": True,
                "media_present": True,
                "live": False,
                "active_reader_or_writer": True,
                "reason": "ACTIVE_READER_OR_WRITER",
                "repair_required": False,
            }
        ]
    if fixture == "normal":
        return 2, {"session_id": SID, "state": "NOT_PENDING", "deleted": False}
    if fixture == "pending":
        return 2, {
            "session_id": SID,
            "state": "DELETE_PENDING",
            "deleted": False,
            "reason": "ACTIVE_READER_OR_WRITER",
            "generation": generation,
        }
    return 0, {
        "session_id": SID,
        "state": "DELETED_LOCAL",
        "deleted": True,
        "already_deleted": True,
        "generation": generation,
    }


def run_process(root: Path, args: list[str]) -> tuple[int, str]:
    completed = subprocess.run(
        [sys.executable, "-m", "recoryn", "--root", str(root), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        env=environment(),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return completed.returncode, completed.stdout


@pytest.fixture(scope="module")
def template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_template(tmp_path_factory.mktemp("g05-cli-template") / "library")


@pytest.fixture(scope="module")
def processes(
    template: Path, tmp_path_factory: pytest.TempPathFactory
) -> dict[tuple[str, str], tuple[Path, int | None, dict[str, str], int, str]]:
    """Every process row on its own library copy, launched concurrently."""
    base = tmp_path_factory.mktemp("g05-cli-processes")
    rows = {}
    for command, fixture in itertools.product(tuple(COMMANDS), FIXTURES):
        root = base / f"{command}-{fixture}" / "library"
        generation = build(template, root, fixture)
        rows[command, fixture] = (root, generation, media(root))
    with ThreadPoolExecutor(max_workers=16) as pool:
        outputs = dict(
            zip(
                rows,
                pool.map(lambda key: run_process(rows[key][0], COMMANDS[key[0]]), rows),
                strict=True,
            )
        )
    return {key: (*rows[key], *outputs[key]) for key in rows}


@pytest.mark.parametrize(("command", "fixture", "mode"), CLI_CASES)
def test_pending_deletion_commands_print_closed_json_and_exit(
    template: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    processes: dict[tuple[str, str], tuple[Path, int | None, dict[str, str], int, str]],
    command: str,
    fixture: str,
    mode: str,
) -> None:
    if mode == "process":
        root, generation, before, code, stdout = processes[command, fixture]
    else:
        root = tmp_path / "library"
        generation = build(template, root, fixture)
        before = media(root)
        code = main(["--root", str(root), *COMMANDS[command]])
        stdout = capsys.readouterr().out
    exit_code, output = expected(command, fixture, generation)
    printed = json.loads(stdout)
    assert code == exit_code, stdout
    if exit_code == 1:
        assert printed.get("code") == output and "message" in printed
        assert set(printed) <= {"error", "message", "code"}
    else:
        assert printed == output
    # No absolute path (raw or JSON-escaped) and no exception text.
    assert str(root) not in stdout and json.dumps(str(root))[1:-1] not in stdout
    assert "Traceback" not in stdout and "injected" not in stdout
    # Only a retry of an existing intent runs the existing session revocation first;
    # listing, NOT_PENDING and damaged history never touch consent state.
    revoked = command == "retry" and fixture in ("pending", "completed")
    assert (root / "security.sqlite").exists() == revoked
    assert media(root) == before  # nothing here removes media (completion was earlier)


@pytest.mark.parametrize("args", PARSER_CASES)
def test_parser_rejects_before_opening_the_library(tmp_path: Path, args: list[str]) -> None:
    root = tmp_path / "never-created"
    with pytest.raises(SystemExit) as refused:
        main(["--root", str(root), *args])
    assert refused.value.code == 2
    assert not root.exists()


# FIX1 (G05R-03): an explicit --expected-generation is passed through, never replaced.
FIX_CASES = [
    pytest.param("match", id="G05-FIX1-0009"),
    pytest.param("mismatch", id="G05-FIX1-0010"),
]


@pytest.mark.parametrize("kind", FIX_CASES)
def test_explicit_expected_generation_is_pinned(
    template: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], kind: str
) -> None:
    for mode in MODES:
        root = tmp_path / mode / "library"
        generation = build(template, root, "pending")
        assert generation is not None
        before = media(root)
        shown = generation if kind == "match" else generation + 1
        args = ["delete", SID, "--retry-only", "--expected-generation", str(shown)]
        if mode == "main":
            code = main(["--root", str(root), *args])
            stdout = capsys.readouterr().out
        else:
            code, stdout = run_process(root, args)
        printed = json.loads(stdout)
        if kind == "match":
            assert code == 2 and printed == {
                "session_id": SID,
                "state": "DELETE_PENDING",
                "deleted": False,
                "reason": "ACTIVE_READER_OR_WRITER",
                "generation": generation,
            }
        else:
            assert code == 1 and printed["code"] == "STALE_DELETE_GENERATION"
        assert media(root) == before  # a stale or blocked retry removes nothing


def test_declared_cli_denominator_is_complete_and_unique() -> None:
    ids = [case.id for case in CLI_CASES + PARSER_CASES]
    assert len(CLI_CASES) == 4 * 4 * 2 and len(PARSER_CASES) == 3
    assert ids == [f"G05-CLI-{i:04d}" for i in range(35)]


def test_existing_delete_keeps_its_exit_meaning(tmp_path: Path, template: Path) -> None:
    """Not a G05 row: plain `delete` stays exit 0 for a pending result (no retroactive exit 2)."""
    root = tmp_path / "library"
    build(template, root, "normal")
    with Library(root) as library, JobStore(library.db_path) as jobs:
        jobs.create("g05-unbound", "legacy-input")
    assert main(["--root", str(root), "delete", SID]) == 0
    shutil.rmtree(root)
