"""G05 retry, crash checkpoints, live owners, orderings and export boundaries.

Real SQLite, journal files and sealed PCM bundles in OS TEMP. Crash rows kill only child
processes this test started, after an atomically published checkpoint marker. Expected
results are the hand tables of docs/testing/g05-pending-deletion-cases.md sections 5.1-5.3.
No device, model or network.
"""

from __future__ import annotations

import itertools
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
import types
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from recoryn import cli as cli_module
from recoryn.app.recording import RecordingService
from recoryn.cli import _export
from recoryn.domain import PCMBlock, StateConflict, ValidationError
from recoryn.jobs import JobStore
from recoryn.storage import ChunkWriter, Library
from recoryn.storage import _coordination as coordination_module
from recoryn.storage import library as library_module
from tests.unit.test_pending_deletions import (
    FMT,
    SID,
    Remover,
    build_template,
    clone,
    deleted_row,
    journal_generation,
    media,
    pcm,
    raw,
    snapshot,
    write_journal,
)
from tests.unit.test_pending_deletions import intent as journal_intent

pytestmark = pytest.mark.integration

SRC = Path(__file__).resolve().parents[2] / "src"


@pytest.fixture(scope="module")
def template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_template(tmp_path_factory.mktemp("g05-integration-template") / "library")


def generation_of(library: Library) -> int:
    return int(
        library._db.execute(
            "SELECT generation FROM sessions WHERE session_id=?", (SID,)
        ).fetchone()[0]
    )


def completed(generation: int, already: bool) -> dict[str, Any]:
    return {
        "session_id": SID,
        "state": "DELETED_LOCAL",
        "deleted": True,
        "already_deleted": already,
        "generation": generation,
    }


def pending(generation: int, reason: str) -> dict[str, Any]:
    return {
        "session_id": SID,
        "state": "DELETE_PENDING",
        "deleted": False,
        "reason": reason,
        "generation": generation,
    }


def assert_complete(library: Library, root: Path, generation: int) -> None:
    """Section 5.5: folder gone, catalog cleaned, both minimal intents kept, no resurrection."""
    assert not (root / "sessions" / SID).exists()
    assert deleted_row(library) == (generation, "DELETED_LOCAL")
    assert journal_generation(root) == generation
    for table in ("sessions", "chunks", "storage_events"):
        count = library._db.execute(
            f"SELECT COUNT(*) FROM {table} WHERE session_id=?",  # noqa: S608
            (SID,),
        ).fetchone()[0]
        assert count == 0, table
    assert library.pending_deletions() == []
    assert_no_resurrection(library, root)


def assert_no_resurrection(library: Library, root: Path) -> None:
    assert all(item.session_id != SID for item in library.list_sessions())
    assert all(item["session_id"] != SID for item in library.unfinished_sessions())
    report = library.recover_session(SID)
    assert (report["adopted"], report["recovered"], report["state"]) == (0, 0, "DELETE_PENDING")
    with pytest.raises(StateConflict):
        library.create_session(SID)


def remaining_subset(before: dict[str, str], after: dict[str, str]) -> bool:
    """Every remaining original keeps its baseline hash; nothing new appears."""
    return all(before.get(name) == digest for name, digest in after.items())


# --- RETRY: intent source 3 x outcome 5 x same/reopened Library 2 = 30 -----------------

RETRY_DIMENSIONS = list(
    itertools.product(
        ("db", "journal", "both"),
        ("normal", "locked_first", "locked_after_one", "metadata_commit", "other_actor"),
        ("same", "reopen"),
    )
)
RETRY_CASES = [
    pytest.param(*dims, id=f"G05-RETRY-{index:04d}") for index, dims in enumerate(RETRY_DIMENSIONS)
]


class FailingConnection:
    """Connection proxy: the first statement starting with trigger raises sqlite3.Error."""

    def __init__(self, real: sqlite3.Connection, trigger: str) -> None:
        self.real = real
        self.trigger = trigger
        self.armed = True

    def execute(self, sql: str, *args: Any) -> Any:
        if self.armed and sql.startswith(self.trigger):
            self.armed = False
            raise sqlite3.OperationalError("G05 injected metadata failure")
        return self.real.execute(sql, *args)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.real, name)


def make_intent(library: Library, root: Path, source: str, monkeypatch: pytest.MonkeyPatch) -> int:
    generation = generation_of(library) + 1
    if source == "db":
        raw(library, "UPDATE sessions SET generation=? WHERE session_id=?", generation, SID)
        raw(library, "INSERT INTO deleted_sessions VALUES(?,?,'DELETE_PENDING')", SID, generation)
    elif source == "journal":
        write_journal(root, journal_intent(generation))  # C2-like: DB not yet committed
    else:
        with monkeypatch.context() as patch:
            locked = Remover(patch)
            locked.locked = True
            first = library.delete_session(SID)
        assert first == {
            "session_id": SID,
            "state": "DELETE_PENDING",
            "deleted": False,
            "reason": "MEDIA_REMOVAL_FAILED",
        }
    return generation


@pytest.mark.parametrize(("source", "outcome", "mode"), RETRY_CASES)
def test_retry_completes_only_after_confirmed_removal(
    template: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source: str,
    outcome: str,
    mode: str,
) -> None:
    root = clone(template, tmp_path / "library")
    baseline = media(root)
    assert len(baseline) >= 2
    library = Library(root)
    try:
        generation = make_intent(library, root, source, monkeypatch)
        # External seed precedes the first audit. The separate mode=reopen below
        # still tests one additional restart after an already validated actor.
        if source != "both":
            library.close()
            library = Library(root)
        if outcome == "other_actor":
            assert library.retry_deletion(SID, expected_generation=generation) == completed(
                generation, False
            )
        if mode == "reopen":
            library.close()
            library = Library(root)
        remover = Remover(monkeypatch)
        first_original = "tracks/mic/e1/c1/audio.pcm"
        if outcome == "locked_first":
            remover.locked = True
        elif outcome == "locked_after_one":

            def partial(path: Path) -> None:
                remover.calls += 1
                (path / first_original).unlink()
                raise PermissionError("G05 injected lock after one file")

            monkeypatch.setattr(library_module, "remove_tree", partial)
        elif outcome == "metadata_commit":
            monkeypatch.setattr(
                library, "_connection", FailingConnection(library._connection, "DELETE FROM chunks")
            )
        before = snapshot(library, root)
        if outcome == "metadata_commit":
            with pytest.raises(ValidationError) as failed:
                library.retry_deletion(SID, expected_generation=generation)
            assert failed.value.args == ("DELETION_METADATA_PENDING",)
            monkeypatch.setattr(library, "_connection", library._connection.real)
            assert not (root / "sessions" / SID).exists()
            assert deleted_row(library) == (generation, "DELETE_PENDING")  # rolled back
            assert journal_generation(root) == generation
            [row] = library.pending_deletions()
            assert (row["reason"], row["media_present"], row["session_present"]) == (
                "CATALOG_CLEANUP_REQUIRED",
                False,
                True,
            )
        elif outcome in ("locked_first", "locked_after_one"):
            result = library.retry_deletion(SID, expected_generation=generation)
            assert result == pending(generation, "MEDIA_REMOVAL_FAILED")
            assert remover.calls == 1
            expected_media = dict(baseline)
            if outcome == "locked_after_one":
                expected_media.pop(first_original)
            assert media(root) == expected_media  # never restored, never more removed
            # Both minimal intents were repaired before the destructive step.
            assert deleted_row(library) == (generation, "DELETE_PENDING")
            assert journal_generation(root) == generation
            assert generation_of(library) == generation
            [row] = library.pending_deletions()
            assert (row["reason"], row["repair_required"], row["intent_sources"]) == (
                "RETRY_REQUIRED",
                False,
                ("db", "journal"),
            )
            assert_no_resurrection(library, root)
            monkeypatch.setattr(library_module, "remove_tree", remover.original)
        elif outcome == "other_actor":
            assert library.retry_deletion(SID, expected_generation=generation) == completed(
                generation, True
            )
            assert snapshot(library, root) == before  # no new generation or record
            assert_complete(library, root, generation)
            return
        else:
            assert library.retry_deletion(SID, expected_generation=generation) == completed(
                generation, False
            )
            assert remover.calls == 1
            assert_complete(library, root, generation)
            return
        # The next explicit retry finishes from what remains and stays idempotent.
        assert library.retry_deletion(SID, expected_generation=generation) == completed(
            generation, False
        )
        assert_complete(library, root, generation)
        assert library.retry_deletion(SID, expected_generation=generation) == completed(
            generation, True
        )
    finally:
        library.close()


# --- CRASH: checkpoint 8 x unwind/kill 2 x next removal policy 3 = 48 ------------------

HOOKS = r'''
import os
import pathlib

from recoryn.storage import library as _library_module


class _CommitProxy:
    """Reach the checkpoint around the tombstone commit (C6 before, C7 after)."""

    def __init__(self, real, before, reach):
        self._real, self._before, self._reach, self._armed = real, before, reach, False

    def execute(self, sql, *args):
        if "status='DELETED_LOCAL'" in sql:
            self._armed = True
        return self._real.execute(sql, *args)

    def commit(self):
        armed, self._armed = self._armed, False
        if armed and self._before:
            self._reach()
        self._real.commit()
        if armed and not self._before:
            self._reach()

    def rollback(self):
        self._armed = False
        self._real.rollback()

    def __getattr__(self, name):
        return getattr(self._real, name)


def install(library, checkpoint, reach):
    undo = []

    def patch(owner, name, value):
        old = getattr(owner, name)
        setattr(owner, name, value)
        undo.append(lambda: setattr(owner, name, old))

    session_dir = os.path.abspath(os.path.join(str(library.root), "sessions", "s"))
    if checkpoint == "C0":
        original_atomic = type(library)._prepare_intent

        def atomic(self, path, temporary, value):
            staged = path.parent == library.root and path.name.startswith(".deletion-stage-")
            if staged:
                reach()
            original_atomic(self, path, temporary, value)

        patch(type(library), "_prepare_intent", atomic)
    elif checkpoint in ("C1", "C2"):
        original_replace = os.replace

        def replace(source, target, *args, **kwargs):
            publication = (pathlib.Path(target).parent.name == "deletion-journal"
                           and pathlib.Path(source).name.startswith(".deletion-stage-"))
            if publication and checkpoint == "C1":
                reach()
            result = original_replace(source, target, *args, **kwargs)
            if publication and checkpoint == "C2":
                reach()
            return result

        patch(os, "replace", replace)
    elif checkpoint in ("C3", "C5"):
        original_remove = _library_module.remove_tree

        def remove(path):
            if checkpoint == "C3":
                reach()
            original_remove(path)
            if checkpoint == "C5":
                reach()

        patch(_library_module, "remove_tree", remove)
    elif checkpoint == "C4":
        original_unlink = pathlib.Path.unlink
        seen = []

        def unlink(self, missing_ok=False):
            original_unlink(self, missing_ok=missing_ok)
            if not seen and os.path.abspath(self).startswith(session_dir + os.sep):
                seen.append(self.name)
                reach()

        patch(pathlib.Path, "unlink", unlink)
    else:
        patch(library, "_connection", _CommitProxy(library._connection, checkpoint == "C6", reach))
    return undo
'''

CHILD = r"""
import sys
import time
from pathlib import Path

from recoryn.storage import Library

root, checkpoint, marker = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])


def reach():
    temporary = marker.with_name(marker.name + ".tmp")
    temporary.write_text(checkpoint, encoding="utf-8")
    deadline = time.monotonic() + 30
    while True:  # a scanner may hold the new file for a moment on Windows
        try:
            temporary.replace(marker)  # atomic: the parent never reads a partial marker
            break
        except PermissionError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.01)
    while True:
        time.sleep(60)


library = Library(root)
install(library, checkpoint, reach)
library.delete_session("s")
marker.with_name("finished").write_text("checkpoint was not reached", encoding="utf-8")
"""

CHECKPOINTS = ("C0", "C1", "C2", "C3", "C4", "C5", "C6", "C7")
POLICIES = ("normal", "locked", "gone")
CRASH_DIMENSIONS = list(itertools.product(CHECKPOINTS, ("unwind", "kill"), POLICIES))
CRASH_CASES = [
    pytest.param(*dims, id=f"G05-CRASH-{index:04d}") for index, dims in enumerate(CRASH_DIMENSIONS)
]
# After the interruption and reopening (section 5.2), written by hand:
# (intent sources, media, catalog row, DB status, listed reason) or a closed outcome.
AFTER_CRASH: dict[tuple[str, str], Any] = {
    ("C0", "unwind"): "NO_INTENT",
    ("C0", "kill"): "NO_INTENT",
    ("C1", "unwind"): "NO_INTENT",  # the live actor unwinds its own registered stage
    ("C1", "kill"): "HISTORY_UNAVAILABLE",  # killed root stage stays, never guessed away
    **{
        (checkpoint, mode): value
        for mode in ("unwind", "kill")
        for checkpoint, value in {
            "C2": (("journal",), "all", True, None, "RETRY_REQUIRED"),
            "C3": (("db", "journal"), "all", True, "DELETE_PENDING", "RETRY_REQUIRED"),
            "C4": (("db", "journal"), "partial", True, "DELETE_PENDING", "RETRY_REQUIRED"),
            "C5": (("db", "journal"), "none", True, "DELETE_PENDING", "CATALOG_CLEANUP_REQUIRED"),
            "C6": (("db", "journal"), "none", True, "DELETE_PENDING", "CATALOG_CLEANUP_REQUIRED"),
            "C7": "COMPLETE",
        }.items()
    },
}


class Checkpoint(Exception):
    pass


def hooks() -> dict[str, Any]:
    namespace: dict[str, Any] = {}
    exec(HOOKS, namespace)  # noqa: S102 - the same source the killed children run
    return namespace


def read_published(path: Path, deadline: float) -> str:
    """Read a file a child published atomically; Windows may briefly deny the first open
    (for example while a scanner inspects the just-renamed file). The content is never
    partial, so only the open is retried, within the fixture's own deadline."""
    while True:
        try:
            return path.read_text(encoding="utf-8")
        except PermissionError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.01)


def child_environment() -> dict[str, str]:
    values = os.environ.copy()
    values["PYTHONPATH"] = str(SRC)
    values["PYTHONDONTWRITEBYTECODE"] = "1"
    values["PYTHONNOUSERSITE"] = "1"
    return values


@pytest.fixture(scope="module")
def killed(template: Path, tmp_path_factory: pytest.TempPathFactory) -> dict[tuple[str, str], Path]:
    """Start every kill row's own child at once; kill each only after its marker appears."""
    base = tmp_path_factory.mktemp("g05-kills")
    children: dict[tuple[str, str], tuple[subprocess.Popen[bytes], Path, Path]] = {}
    for checkpoint, policy in itertools.product(CHECKPOINTS, POLICIES):
        folder = base / f"{checkpoint}-{policy}"
        root = clone(template, folder / "library")
        marker = folder / "marker"
        log = (folder / "child.log").open("wb")
        process = subprocess.Popen(
            [sys.executable, "-c", HOOKS + CHILD, str(root), checkpoint, str(marker)],
            stdout=log,
            stderr=subprocess.STDOUT,
            env=child_environment(),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        log.close()
        children[checkpoint, policy] = (process, root, marker)
    deadline = time.monotonic() + 120
    try:
        for (checkpoint, policy), (process, _root, marker) in children.items():
            while not marker.exists():
                if process.poll() is not None or time.monotonic() > deadline:
                    log_text = (marker.parent / "child.log").read_text(errors="replace")
                    pytest.fail(f"{checkpoint}/{policy} child never reached it: {log_text}")
                time.sleep(0.01)
            assert read_published(marker, deadline) == checkpoint
    finally:
        for process, _, _ in children.values():
            if process.poll() is None:
                process.kill()
            process.wait(60)
    return {key: root for key, (_, root, _) in children.items()}


@pytest.mark.parametrize(("checkpoint", "mode", "policy"), CRASH_CASES)
def test_interrupted_deletion_is_rediscovered_never_resurrected(
    template: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    killed: dict[tuple[str, str], Path],
    checkpoint: str,
    mode: str,
    policy: str,
) -> None:
    baseline = media(template)
    if mode == "kill":
        root = killed[checkpoint, policy]
    else:
        root = clone(template, tmp_path / "library")
        library = Library(root)
        undo = hooks()["install"](library, checkpoint, _raise(checkpoint))
        try:
            with pytest.raises(Checkpoint):
                library.delete_session(SID)
        finally:
            for step in reversed(undo):
                step()
            library.close()
    with Library(root) as library:
        start_generation = _template_generation(template)
        generation = start_generation + 1
        expected = AFTER_CRASH[checkpoint, mode]
        remover = Remover(monkeypatch)
        if policy == "locked":
            remover.locked = True
        elif policy == "gone":

            def gone(path: Path) -> None:
                remover.calls += 1
                shutil.rmtree(path)  # already removed when the remover is reached
                remover.original(path)

            monkeypatch.setattr(library_module, "remove_tree", gone)
        if expected == "NO_INTENT":
            assert library.pending_deletions() == [] and deleted_row(library) is None
            assert journal_generation(root) is None and media(root) == baseline
            assert not list((root / "deletion-journal").iterdir())
            assert library.retry_deletion(SID, expected_generation=generation) == {
                "session_id": SID,
                "state": "NOT_PENDING",
                "deleted": False,
            }
            assert remover.calls == 0 and media(root) == baseline
            assert [item.session_id for item in library.list_sessions()] == [SID]
            return
        if expected == "HISTORY_UNAVAILABLE":
            assert not list((root / "deletion-journal").iterdir())
            leftovers = list(root.glob(".deletion-stage-*.json"))
            assert len(leftovers) == 1
            staged_bytes = leftovers[0].read_bytes()
            assert json.loads(staged_bytes) == journal_intent(generation)
            before = snapshot(library, root)
            for call in (
                library.pending_deletions,
                lambda: library.retry_deletion(SID, expected_generation=generation),
                lambda: library.recover_session(SID),
            ):
                with pytest.raises(ValidationError):
                    call()
            assert remover.calls == 0 and snapshot(library, root) == before
            assert leftovers[0].read_bytes() == staged_bytes
            assert media(root) == baseline
            return
        if expected == "COMPLETE":
            assert_complete(library, root, generation)
            assert library.retry_deletion(SID, expected_generation=generation) == completed(
                generation, True
            )
            assert remover.calls == 0
            return
        sources, files, catalog, status, reason = expected
        [row] = library.pending_deletions()
        assert (row["generation"], row["intent_sources"], row["reason"]) == (
            generation,
            sources,
            reason,
        )
        assert (row["session_present"], row["db_status"]) == (catalog, status)
        current = media(root)
        assert remaining_subset(baseline, current)
        if files == "all":
            assert current == baseline
        elif files == "partial":
            assert set(baseline) - set(current) == {"manifest.json"}  # first unlink only
        else:
            assert current == {}
        assert_no_resurrection(library, root)
        result = library.retry_deletion(SID, expected_generation=generation)
        reached = files != "none"  # the remover runs only when a folder remains
        assert remover.calls == int(reached)
        if policy == "locked" and reached:
            assert result == pending(generation, "MEDIA_REMOVAL_FAILED")
            assert media(root) == current and deleted_row(library) == (generation, "DELETE_PENDING")
            assert journal_generation(root) == generation
        else:
            assert result == completed(generation, False)
            assert_complete(library, root, generation)


def _raise(checkpoint: str) -> Callable[[], None]:
    def reach() -> None:
        raise Checkpoint(checkpoint)

    return reach


_GENERATIONS: dict[Path, int] = {}


def _template_generation(template: Path) -> int:
    if template not in _GENERATIONS:
        uri = (template / "library.sqlite").as_uri() + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        try:
            _GENERATIONS[template] = connection.execute(
                "SELECT generation FROM sessions WHERE session_id=?", (SID,)
            ).fetchone()[0]
        finally:
            connection.close()
    return _GENERATIONS[template]


# --- LIVE: blocker 6 x intent source 3 x before/after end-or-ACK 2 = 36 -----------------

BLOCKERS = ("none", "owner_live", "owner_ended", "writer", "reader", "remote_unknown")
LIVE_DIMENSIONS = list(itertools.product(BLOCKERS, ("db", "journal", "both"), ("before", "after")))
LIVE_CASES = [
    pytest.param(*dims, id=f"G05-LIVE-{index:04d}") for index, dims in enumerate(LIVE_DIMENSIONS)
]
# Hand table: (live, active_reader_or_writer, blocking reason or None).
LIVE_EXPECT = {
    "none": (False, False, None),
    "owner_live": (True, False, "SESSION_LIVE"),
    "owner_ended": (False, False, None),
    "writer": (True, True, "SESSION_LIVE"),
    "reader": (False, True, "ACTIVE_READER_OR_WRITER"),
    "remote_unknown": (False, True, "ACTIVE_READER_OR_WRITER"),
}


class Owner:
    def __init__(self, live: bool) -> None:
        self.live = live

    def is_live(self) -> bool:
        return self.live


@pytest.mark.parametrize(("blocker", "source", "phase"), LIVE_CASES)
def test_live_owner_and_reader_keep_deletion_pending_until_end(
    template: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    blocker: str,
    source: str,
    phase: str,
) -> None:
    root = clone(template, tmp_path / "library")
    library = Library(root)
    jobs: JobStore | None = None
    owner = writer = attempt = job = None  # strong references until the end of the row
    try:
        library.create_session("other")  # independent work must never be globally blocked
        if blocker in ("owner_live", "owner_ended"):
            owner = Owner(blocker == "owner_live")
            library.register_live_owner(SID, owner)
        elif blocker == "writer":
            writer = ChunkWriter(root, pcm(SID, "e9", 0), chunk_id="live-writer")
            writer.append(pcm(SID, "e9", 0))
        elif blocker in ("reader", "remote_unknown"):
            jobs = JobStore(library.db_path)
            job = jobs.create("g05-reader", "fixed-input")
            jobs.bind_session(job.job_id, SID)
            attempt = jobs.claim(job.job_id, "g05-controlled-reader")
            jobs.reader_started(attempt)
            if blocker == "remote_unknown":
                jobs.fail(
                    job.job_id,
                    attempt.attempt_id,
                    attempt.fence,
                    "REMOTE_OUTCOME_UNKNOWN",
                    outcome_known=False,
                )
        live, active, reason = LIVE_EXPECT[blocker]
        if blocker in ("owner_live", "writer"):
            # Before any intent, G-P04's live refusals still apply.
            for call in (
                lambda: library.recover_session(SID),
                lambda: library.finalize_unfinished(SID),
            ):
                with pytest.raises(StateConflict) as refused:
                    call()
                assert str(refused.value) in ("SESSION_LIVE", "Live writer cannot be recovered")
        baseline = media(root)
        generation = generation_of(library) + 1
        if source == "both":
            with monkeypatch.context() as patch:
                locked = Remover(patch)
                locked.locked = True
                first = library.delete_session(SID)  # the initial delete shares the guard
            assert first["state"] == "DELETE_PENDING" and first["deleted"] is False
            assert first["reason"] == (reason or "MEDIA_REMOVAL_FAILED")
            assert locked.calls == (0 if reason else 1)
        elif source == "db":
            raw(library, "UPDATE sessions SET generation=? WHERE session_id=?", generation, SID)
            raw(
                library,
                "INSERT INTO deleted_sessions VALUES(?,?,'DELETE_PENDING')",
                SID,
                generation,
            )
        else:
            write_journal(root, journal_intent(generation))
        if source != "both":
            library.close()
            library = Library(root)
            if owner is not None:
                library.register_live_owner(SID, owner)
        assert media(root) == baseline
        [row] = library.pending_deletions()
        assert (row["live"], row["active_reader_or_writer"]) == (live, active)
        idle_reason = "JOURNAL_REPAIR_REQUIRED" if source == "db" else "RETRY_REQUIRED"
        assert row["reason"] == (reason or idle_reason)
        # The same session is deletion-first for every other action.
        report = library.recover_session(SID)
        assert (report["adopted"], report["state"]) == (0, "DELETE_PENDING")
        with pytest.raises(StateConflict, match="DELETE_PENDING"):
            library.finalize_unfinished(SID)
        with pytest.raises(StateConflict):
            _export(library, SID, tmp_path / "export")
        assert not (tmp_path / "export").exists()
        remover = Remover(monkeypatch)
        if phase == "after":
            if owner is not None:
                owner.live = False
            if writer is not None:
                writer.abort()
            if jobs is not None and attempt is not None and job is not None:
                jobs.reader_finished(attempt)
                if blocker == "reader":
                    jobs.fail(job.job_id, attempt.attempt_id, attempt.fence, "G05_DONE")
        result = library.retry_deletion(SID, expected_generation=generation)
        if phase == "before" and reason is not None:
            assert result == pending(generation, reason)
            assert remover.calls == 0 and media(root) == baseline
            # Both intents were reinforced; no source was stopped and no ACK fabricated.
            assert deleted_row(library) == (generation, "DELETE_PENDING")
            assert journal_generation(root) == generation
            if owner is not None:
                assert owner.live is True
            if writer is not None:
                assert writer._pcm is not None
            if jobs is not None and job is not None:
                assert jobs.local_reader_active(job.job_id) is True
            assert library.delete_session("other")["state"] == "DELETED_LOCAL"
            return
        assert result == completed(generation, False)
        assert_complete(library, root, generation)
        if blocker == "remote_unknown" and jobs is not None and job is not None:
            assert jobs.get(job.job_id).blocked_reason == "REMOTE_UNKNOWN"  # not resolved
        assert library.delete_session("other")["state"] == "DELETED_LOCAL"
    finally:
        if writer is not None:
            writer.abort()
        if jobs is not None:
            if attempt is not None:
                jobs.reader_finished(attempt)
            jobs.close()
        library.close()


# --- ORDER: other action 4 x new/pending deletion 2 x which goes first 2 = 16 ----------

ORDER_DIMENSIONS = list(
    itertools.product(
        ("recover", "finalize", "export", "delete"),
        ("new", "pending"),
        ("other_first", "delete_first"),
    )
)
ORDER_CASES = [
    pytest.param(*dims, id=f"G05-ORDER-{index:04d}") for index, dims in enumerate(ORDER_DIMENSIONS)
]


def in_thread(call: Callable[[], Any]) -> tuple[threading.Thread, dict[str, Any]]:
    box: dict[str, Any] = {}

    def target() -> None:
        try:
            box["value"] = call()
        except BaseException as error:  # the result is asserted by the caller
            box["value"] = error

    thread = threading.Thread(target=target)
    thread.start()
    return thread, box


def describe(value: Any) -> str:
    """Closed outcome labels for the hand table below."""
    if isinstance(value, StateConflict):
        return "REFUSED:" + str(value)
    if isinstance(value, BaseException):
        return "ERROR:" + type(value).__name__
    if "adopted" in value:
        return f"RECOVER:{value['state']}:{value['adopted']}"
    if "already_finalized" in value:
        return "FINALIZED_ALREADY" if value["already_finalized"] else "FINALIZED"
    if "complete" in value:
        return "EXPORTED"
    if value["state"] == "DELETED_LOCAL":
        return "DELETED" + (":ALREADY" if value.get("already_deleted") else "")
    return "PENDING:" + str(value.get("reason"))


# (other action outcome, deletion outcome, whether the other action had to wait).
ORDER_EXPECT = {
    ("recover", "new", "other_first"): ("RECOVER:FINALIZED:0", "DELETED", False),
    ("recover", "new", "delete_first"): ("RECOVER:DELETE_PENDING:0", "DELETED", True),
    ("recover", "pending", "other_first"): ("RECOVER:DELETE_PENDING:0", "DELETED", False),
    ("recover", "pending", "delete_first"): ("RECOVER:DELETE_PENDING:0", "DELETED", True),
    ("finalize", "new", "other_first"): ("FINALIZED_ALREADY", "DELETED", False),
    ("finalize", "new", "delete_first"): ("REFUSED:DELETE_PENDING", "DELETED", True),
    ("finalize", "pending", "other_first"): ("REFUSED:DELETE_PENDING", "DELETED", False),
    ("finalize", "pending", "delete_first"): ("REFUSED:DELETE_PENDING", "DELETED", True),
    ("export", "new", "other_first"): ("EXPORTED", "DELETED", False),
    ("export", "new", "delete_first"): ("REFUSED:Session has a deletion intent", "DELETED", False),
    ("export", "pending", "other_first"): (
        "REFUSED:Session has a deletion intent",
        "DELETED",
        False,
    ),
    ("export", "pending", "delete_first"): (
        "REFUSED:Session has a deletion intent",
        "DELETED",
        False,
    ),
    ("delete", "new", "other_first"): ("DELETED", "DELETED", False),
    ("delete", "new", "delete_first"): ("PENDING:SESSION_OPERATION_IN_PROGRESS", "DELETED", False),
    ("delete", "pending", "other_first"): ("DELETED", "DELETED:ALREADY", False),
    ("delete", "pending", "delete_first"): (
        "PENDING:SESSION_OPERATION_IN_PROGRESS",
        "DELETED",
        False,
    ),
}


@pytest.mark.parametrize(("other", "mode", "order"), ORDER_CASES)
def test_deletion_linearizes_with_same_session_actions(
    template: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    other: str,
    mode: str,
    order: str,
) -> None:
    root = clone(template, tmp_path / "library")
    baseline = media(root)
    output = tmp_path / "export"
    with Library(root) as library:
        generation = generation_of(library) + 1
        if mode == "pending":
            with monkeypatch.context() as patch:
                locked = Remover(patch)
                locked.locked = True
                assert library.delete_session(SID)["reason"] == "MEDIA_REMOVAL_FAILED"

        def deletion() -> Any:
            if mode == "new":
                return library.delete_session(SID)
            return library.retry_deletion(SID, expected_generation=generation)

        def action() -> Any:
            if other == "recover":
                return library.recover_session(SID)
            if other == "finalize":
                return library.finalize_unfinished(SID)
            if other == "export":
                return _export(library, SID, output)
            return deletion()

        if order == "other_first":
            first = describe(_call(action))
            exported = media_tree(output)
            if mode == "new" and other in {"recover", "finalize"}:
                generation = generation_of(library) + 1
            second = describe(_call(deletion))
            waited = False
        else:
            entered, release = threading.Event(), threading.Event()
            original = library_module.remove_tree

            def parked(path: Path) -> None:
                entered.set()
                assert release.wait(10)
                original(path)

            monkeypatch.setattr(library_module, "remove_tree", parked)
            one, box_one = in_thread(deletion)
            assert entered.wait(10)
            two, box_two = in_thread(action)
            two.join(0.3)
            waited = two.is_alive()
            release.set()
            one.join(10)
            two.join(10)
            assert not one.is_alive() and not two.is_alive()
            first, second = describe(box_two["value"]), describe(box_one["value"])
            exported = media_tree(output)
        assert (first, second, waited) == ORDER_EXPECT[other, mode, order]
        if other == "export" and first == "EXPORTED":
            assert exported and media_tree(output) == exported  # an earlier copy remains
        else:
            assert not output.exists()  # no export after the intent, not even a folder
        if second != "DELETED:ALREADY" and first.startswith("PENDING"):
            assert library.retry_deletion(SID, expected_generation=generation) == completed(
                generation, True
            )
        assert baseline and not (root / "sessions" / SID).exists()
        assert_complete(library, root, generation)


def _call(call: Callable[[], Any]) -> Any:
    try:
        return call()
    except BaseException as error:  # outcomes are compared as closed labels
        return error


def media_tree(folder: Path) -> dict[str, bytes]:
    if not folder.exists():
        return {}
    return {
        path.relative_to(folder).as_posix(): path.read_bytes()
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


# --- EXPORT: four copy/delete boundaries ------------------------------------------------

EXPORT_CASES = [
    pytest.param(name, id=f"G05-EXPORT-{index:04d}")
    for index, name in enumerate(
        (
            "copy_then_delete",
            "delete_then_export",
            "delete_before_first_open",
            "delete_while_reading",
        )
    )
]


@pytest.mark.parametrize("boundary", EXPORT_CASES)
def test_export_and_deletion_boundaries(
    template: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    if boundary == "delete_while_reading" and sys.platform != "win32":
        pytest.skip("an open read handle blocks unlink only on Windows")
    root = clone(template, tmp_path / "library")
    output = tmp_path / "export"
    with Library(root) as library:
        generation = generation_of(library) + 1
        if boundary == "copy_then_delete":
            assert _export(library, SID, output)["complete"] is True
            copy = media_tree(output)
            assert library.delete_session(SID)["state"] == "DELETED_LOCAL"
            assert media_tree(output) == copy  # the external copy is not recalled
        elif boundary == "delete_then_export":
            assert library.delete_session(SID)["state"] == "DELETED_LOCAL"
            with pytest.raises(StateConflict):
                _export(library, SID, output)
            assert not output.exists()
        else:
            entered, release = threading.Event(), threading.Event()
            if boundary == "delete_before_first_open":
                original_runs = cli_module._export_contiguous_runs

                def runs(*args: Any) -> Any:
                    entered.set()
                    assert release.wait(10)
                    return original_runs(*args)

                monkeypatch.setattr(cli_module, "_export_contiguous_runs", runs)
            else:
                import wave

                def opened(*args: Any) -> Any:
                    entered.set()  # the first chunk's audio.pcm and blocks.jsonl are open
                    assert release.wait(10)
                    return wave.open(*args)

                monkeypatch.setattr(
                    cli_module,
                    "wave",
                    types.SimpleNamespace(open=opened, Wave_write=wave.Wave_write),
                )
            baseline = media(root)
            worker, box = in_thread(lambda: _export(library, SID, output))
            assert entered.wait(10)
            deleted = library.delete_session(SID)
            during = media(root)
            release.set()
            worker.join(30)
            assert not worker.is_alive()
            if boundary == "delete_before_first_open":
                assert deleted["state"] == "DELETED_LOCAL"
                assert isinstance(box["value"], OSError)  # input vanished: safe failure
                assert not (output / "export.json").exists()  # partial output is not complete
            else:
                assert deleted == {
                    "session_id": SID,
                    "state": "DELETE_PENDING",
                    "deleted": False,
                    "reason": "MEDIA_REMOVAL_FAILED",
                }
                # The open input blocked removal: what remains keeps its bytes.
                assert during and remaining_subset(baseline, during)
                assert "tracks/mic/e1/c1/audio.pcm" in during
                # The reader then reached the final catalog check, which sees the
                # intent: a partial output is never marked complete.
                assert isinstance(box["value"], StateConflict)
                assert not (output / "export.json").exists()
                # The reader has finished (its handles are closed): retry completes.
                assert library.retry_deletion(SID, expected_generation=generation) == completed(
                    generation, False
                )
        assert_complete(library, root, generation)


# --- C00-required root mutex holds while another session records (G05-PERF, 2 rows) ---


class RootHoldMeter:
    """Outermost root mutex ownership per thread, excluding the wait to acquire it."""

    def __init__(self, lock: Any) -> None:
        self.lock = lock
        self.local = threading.local()
        self.holds: list[float] = []
        self.management_holds: list[float] = []
        self.long_holds: list[dict[str, Any]] = []
        self.management_fs_under_mutex: list[str] = []
        self.management_fs_outside = 0
        self.active = True

    def holding(self) -> bool:
        return getattr(self.local, "depth", 0) > 0

    def note_fs(self, name: str) -> None:
        # Folder walks and removal must run outside the root mutex (GC-P02).
        if threading.current_thread().name != "g05-management":
            return
        if self.holding():
            self.management_fs_under_mutex.append(name)
        else:
            self.management_fs_outside += 1

    def __enter__(self) -> RootHoldMeter:
        self.lock.acquire()
        depth = getattr(self.local, "depth", 0)
        if depth == 0:
            self.local.started = time.perf_counter()
        self.local.depth = depth + 1
        return self

    def __exit__(self, *exc: Any) -> None:
        self.local.depth -= 1
        if self.local.depth == 0 and self.active:
            elapsed = time.perf_counter() - self.local.started
            self.holds.append(elapsed)
            if threading.current_thread().name == "g05-management":
                self.management_holds.append(elapsed)
            if elapsed >= 0.05:
                self.long_holds.append(
                    {
                        "thread": threading.current_thread().name,
                        "seconds": elapsed,
                        "stack": [f"{f.name}:{f.lineno}" for f in traceback.extract_stack(limit=6)],
                    }
                )
        self.lock.release()


# 관리 스레드 한 번의 root mutex 보유 판정 상한(GT-P05). CI 3.11 러너에서 정상 retry의
# 짧은 commit이 81.4ms까지 늘어났다(run 45190482741). G-P04의 GT-P04와 같은 기준으로
# 0.5초를 쓴다. 녹음 큐 256블록(10ms 블록 기준 약 2.56초, 실제 앱 2트랙 공유 약 1.28초)
# 보다 작고, 폴더 제거를 mutex 안으로 되돌린 변이(5.6~7.4초)보다 충분히 작다.
# 목록 전체를 mutex 안으로 되돌린 변이는 0.2~0.4초라 이 상한으로는 구별되지 않으므로,
# 관리 스레드가 root mutex를 가진 동안 iterdir·remove_tree를 부르지 않는다는 구조 판정을
# 함께 둔다(G05R-08). 50ms 이상 보유는 진단용 long_holds에 계속 기록한다.
MANAGEMENT_HOLD_LIMIT_SECONDS = 0.5


PERF_CASES = [
    pytest.param("inventory", id="G05-PERF-inventory-400"),
    pytest.param("retry", id="G05-PERF-retry-10800"),
]


@pytest.mark.parametrize("action", PERF_CASES)
def test_pending_management_never_blocks_another_recording(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, action: str, request: pytest.FixtureRequest
) -> None:
    """관리 작업 완료까지 측정한다(상한 300초). writer seal 지연은 G-P15 후속이다."""
    root = tmp_path / "library"
    with Library(root) as library:
        if action == "inventory":
            sessions = [f"p{index:04d}" for index in range(400)]
            for session in sessions:
                folder = root / "sessions" / session
                folder.mkdir(parents=True)
                (folder / "left.pcm").write_bytes(b"x")
                write_journal(root, journal_intent(1, session), f"{session}.json")
        else:
            library.create_session(SID)
            epoch = root / "sessions" / SID / "tracks" / "mic" / "epoch1"
            for index in range(3600):
                bundle = epoch / f"b{index:06d}"
                bundle.mkdir(parents=True)
                for name in ("audio.pcm", "blocks.jsonl", "descriptor.json"):
                    (bundle / name).write_bytes(b"x")
            assert library.verify_deletion_history(fresh=True)["status"] == "READY"
            with monkeypatch.context() as patch:
                locked = Remover(patch)
                locked.locked = True
                assert library.delete_session(SID)["reason"] == "MEDIA_REMOVAL_FAILED"
        if action == "inventory":
            library.close()
            library = Library(root)
            request.addfinalizer(library.close)
        generation = deleted_row(library)[0] if action == "retry" else 1
        meter = RootHoldMeter(library._mutex)
        monkeypatch.setattr(library, "_mutex", meter)
        monkeypatch.setitem(coordination_module._roots, library.root, meter)
        real_iterdir = Path.iterdir
        real_scandir = os.scandir
        real_listdir = os.listdir
        real_stat = os.stat
        real_remove_tree = library_module.remove_tree
        real_remove_and_seal = library._remove_and_seal
        real_media_present = library._media_present
        completion_scope = threading.local()
        stat_targets = {
            root / "sessions" / sid for sid in (sessions if action == "inventory" else [SID])
        }
        point_calls = {
            "stat_inside": 0,
            "stat_outside": 0,
            "completion_stat_inside": 0,
            "completion_calls": 0,
            "remove_outside": 0,
        }

        def measured_remove_and_seal(*args: Any, **kwargs: Any) -> Any:
            completion_scope.removing = True
            try:
                return real_remove_and_seal(*args, **kwargs)
            finally:
                completion_scope.removing = False

        def measured_media_present(session_id: str) -> bool:
            completion = (
                action == "retry"
                and session_id == SID
                and threading.current_thread().name == "g05-management"
                and meter.holding()
                and getattr(completion_scope, "removing", False)
                and point_calls["completion_calls"] == 0
            )
            if completion:
                point_calls["completion_calls"] += 1
                completion_scope.confirming = True
            try:
                return real_media_present(session_id)
            finally:
                if completion:
                    completion_scope.confirming = False

        def counted_iterdir(path: Path) -> Iterator[Path]:
            meter.note_fs("iterdir")
            return real_iterdir(path)

        def counted_scandir(*args: Any) -> Any:
            meter.note_fs("scandir")
            return real_scandir(*args)

        def counted_listdir(*args: Any) -> Any:
            meter.note_fs("listdir")
            return real_listdir(*args)

        def counted_remove_tree(*args: Any, **kwargs: Any) -> Any:
            meter.note_fs("remove_tree")
            if threading.current_thread().name == "g05-management" and not meter.holding():
                point_calls["remove_outside"] += 1
            return real_remove_tree(*args, **kwargs)

        def counted_stat(path: Any, *args: Any, **kwargs: Any) -> Any:
            # Lexical comparison only: never resolve/stat while classifying a call.
            if (
                threading.current_thread().name == "g05-management"
                and isinstance(path, (str, Path))
                and Path(path) in stat_targets
            ):
                if meter.holding() and getattr(completion_scope, "confirming", False):
                    point_calls["completion_stat_inside"] += 1
                else:
                    meter.note_fs("session_stat")
                    point_calls["stat_inside" if meter.holding() else "stat_outside"] += 1
            return real_stat(path, *args, **kwargs)

        # A walk rewritten with os.scandir or os.listdir must still be seen (G05R-09).
        monkeypatch.setattr(Path, "iterdir", counted_iterdir)
        monkeypatch.setattr(os, "scandir", counted_scandir)
        monkeypatch.setattr(os, "listdir", counted_listdir)
        monkeypatch.setattr(os, "stat", counted_stat)
        monkeypatch.setattr(library_module, "remove_tree", counted_remove_tree)
        monkeypatch.setattr(library, "_remove_and_seal", measured_remove_and_seal)
        monkeypatch.setattr(library, "_media_present", measured_media_present)
        service = RecordingService(library, {"mic": FMT}, session_id="rec")
        service.start()
        result: dict[str, Any] = {}
        done = threading.Event()

        def management() -> None:
            started = time.perf_counter()
            try:
                if action == "inventory":
                    listed = library.pending_deletions()
                    assert [row["session_id"] for row in listed] == sessions
                    assert all(row["reason"] == "RETRY_REQUIRED" for row in listed)
                else:
                    outcome = library.retry_deletion(SID, expected_generation=generation)
                    assert outcome == completed(generation, False)
                    assert not (root / "sessions" / SID).exists()
                result["ok"] = True
            except BaseException as error:
                result["error"] = repr(error)
            finally:
                result["seconds"] = time.perf_counter() - started
                done.set()

        worker = threading.Thread(target=management, name="g05-management")
        epoch_id = service.epochs["mic"]
        rejected = index = 0
        started = time.perf_counter()
        try:
            while index < 600 or not done.is_set():
                assert time.perf_counter() - started < 300, "management exceeded 300 seconds"
                if index == 50:
                    worker.start()
                stamp = 1_000_000 + index * 10_000_000
                block = PCMBlock(
                    "rec",
                    "mic",
                    epoch_id,
                    index,
                    FMT,
                    480,
                    b"\0\x01" * 480,
                    stamp,
                    stamp,
                    device_frame_position=index * 480,
                )
                rejected += not service.submit(block)
                index += 1
                delay = started + index * 0.01 - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)
            worker.join(30)
        finally:
            meter.active = False
            service.stop(timeout=60)
            if worker.ident is not None:
                worker.join(60)
        health = service.health_snapshot()["tracks"]["mic"]
        measurement = {
            "action": action,
            "seconds": result["seconds"],
            "root_max_seconds": max(meter.holds),
            "management_root_max_seconds": max(meter.management_holds),
            "management_holds": len(meter.management_holds),
            "long_holds": meter.long_holds,
            "management_long_holds": [
                hold
                for hold in meter.long_holds
                if hold["thread"] == "g05-management"
                and hold["seconds"] >= MANAGEMENT_HOLD_LIMIT_SECONDS
            ],
            "management_fs_under_mutex": len(meter.management_fs_under_mutex),
            "management_fs_outside": meter.management_fs_outside,
            "management_target_stat_inside": point_calls["stat_inside"]
            + point_calls["completion_stat_inside"],
            "management_other_target_stat_inside": point_calls["stat_inside"],
            "management_completion_stat_inside": point_calls["completion_stat_inside"],
            "management_completion_calls": point_calls["completion_calls"],
            "management_target_stat_outside": point_calls["stat_outside"],
            "management_remove_outside": point_calls["remove_outside"],
            "rejected": rejected,
            "dropped_frames": health["dropped_frames"],
            "submitted_frames": index * 480,
            "stored_frames": sum(item.frame_count for item in library.chunks("rec")),
        }
        (tmp_path / "measurement.json").write_text(json.dumps(measurement), encoding="utf-8")
        print(json.dumps(measurement))
        assert result.get("ok"), result
        # Writer seal holds and rejected/dropped blocks are recorded only (G-P15).
        # Structural check first: it does not depend on runner speed (GC-P02). The
        # positive control proves the counters see this action's folder work at all.
        assert meter.management_fs_outside > 0, measurement
        if action == "inventory":
            assert point_calls["stat_outside"] > 0, measurement
        else:
            assert point_calls["remove_outside"] > 0, measurement
            assert point_calls["completion_calls"] == 1, measurement
            assert point_calls["completion_stat_inside"] > 0, measurement
        assert point_calls["stat_inside"] == 0, measurement
        assert meter.management_fs_under_mutex == [], measurement
        assert max(meter.management_holds) < MANAGEMENT_HOLD_LIMIT_SECONDS, measurement
        assert measurement["management_long_holds"] == [], measurement


def test_declared_integration_denominators_are_complete_and_unique() -> None:
    groups = {
        "RETRY": RETRY_CASES,
        "CRASH": CRASH_CASES,
        "LIVE": LIVE_CASES,
        "ORDER": ORDER_CASES,
        "EXPORT": EXPORT_CASES,
    }
    sizes = {name: len(cases) for name, cases in groups.items()}
    assert sizes == {
        "RETRY": 3 * 5 * 2,
        "CRASH": 8 * 2 * 3,
        "LIVE": 6 * 3 * 2,
        "ORDER": 16,
        "EXPORT": 4,
    }
    for name, cases in groups.items():
        assert [case.id for case in cases] == [f"G05-{name}-{i:04d}" for i in range(sizes[name])]
    assert set(AFTER_CRASH) == set(itertools.product(CHECKPOINTS, ("unwind", "kill")))
    assert set(ORDER_EXPECT) == set(ORDER_DIMENSIONS)


@pytest.fixture(autouse=True)
def _no_stray_hooks() -> Iterator[None]:
    yield
    assert library_module.atomic_json.__module__ == "recoryn.storage._safe"
