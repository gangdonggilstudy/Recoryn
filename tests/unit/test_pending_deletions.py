"""G05 pending deletions: inventory (INV), generations (GEN), history faults (HISTORY), types (TYPE).

Expected values are hand-written from docs/testing/g05-pending-deletion-cases.md sections 2.2
and 5.1/5.4; they are never derived from Library internals. Fixtures are real SQLite rows,
journal files and sealed PCM bundles in OS TEMP; no device, model or network.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import shutil
import sqlite3
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from recoryn.domain import AudioFormat, PCMBlock, SessionState, StateConflict, ValidationError
from recoryn.storage import ChunkWriter, Library
from recoryn.storage import library as library_module

pytestmark = pytest.mark.unit

FMT = AudioFormat(48000, 1)
SID = "s"
MAX = 2**63 - 1
HISTORY_UNAVAILABLE = "DELETION_HISTORY_UNAVAILABLE"


def pcm(session: str, epoch: str, sequence: int) -> PCMBlock:
    return PCMBlock(
        session,
        "mic",
        epoch,
        sequence,
        FMT,
        4,
        bytes([20 + sequence, 1]) * 4,
        1_000 + sequence * 100,
        1_000 + sequence * 100,
        device_frame_position=sequence * 4,
    )


def sealed(root: Path, session: str, chunk_id: str, sequences: tuple[int, ...]) -> Any:
    writer = ChunkWriter(root, pcm(session, "e1", sequences[0]), chunk_id=chunk_id)
    for sequence in sequences:
        writer.append(pcm(session, "e1", sequence))
    return writer.seal()


def build_template(root: Path, *, finalized: bool = True) -> Path:
    """One session with two real sealed bundles (six files) and, if finalized, a manifest."""
    with Library(root) as library:
        library.create_session(SID)
        library.transition(SID, SessionState.RECORDING, 0)
        library.register_chunk(sealed(root, SID, "c1", (0, 1)))
        library.register_chunk(sealed(root, SID, "c2", (2, 3)))
        if finalized:
            library.transition(SID, SessionState.FINALIZING, 1)
            library.finalize_session(SID)
        else:
            library.transition(SID, SessionState.INTERRUPTED, 1)
    return root


def clone(template: Path, target: Path) -> Path:
    shutil.copytree(template, target)
    return target


def media(root: Path, session: str = SID) -> dict[str, str]:
    """Relative file name -> SHA256 of everything under the session folder."""
    base = root / "sessions" / session
    if not base.exists():
        return {}
    return {
        path.relative_to(base).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(base.rglob("*"))
        if path.is_file()
    }


def journal_files(root: Path) -> dict[str, bytes] | str:
    journal = root / "deletion-journal"
    if journal.is_file():
        return "FILE:" + hashlib.sha256(journal.read_bytes()).hexdigest()
    if not journal.is_dir():
        return "MISSING"
    return {path.name: path.read_bytes() for path in sorted(journal.iterdir()) if path.is_file()}


def logical(library: Library) -> dict[str, list[str] | None]:
    """Logical SQL rows (raw), so WAL/checkpoint byte changes are not called writes."""
    rows: dict[str, list[str] | None] = {}
    for table in ("sessions", "chunks", "storage_events", "deleted_sessions"):
        try:
            found = library._db.execute(f"SELECT * FROM {table}").fetchall()  # noqa: S608
        except sqlite3.OperationalError:
            rows[table] = None
        else:
            rows[table] = sorted(repr(tuple(row)) for row in found)
    return rows


def snapshot(library: Library, root: Path) -> tuple[Any, ...]:
    return logical(library), journal_files(root), media(root)


def deleted_row(library: Library, session: str = SID) -> tuple[Any, ...] | None:
    row = library._db.execute(
        "SELECT generation,status FROM deleted_sessions WHERE session_id=?", (session,)
    ).fetchone()
    return None if row is None else tuple(row)


def journal_generation(root: Path, session: str = SID) -> int | None:
    path = root / "deletion-journal" / f"{session}.json"
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    assert value["session_id"] == session and value["state"] == "DELETE_REQUESTED"
    return int(value["generation"])


def write_journal(root: Path, value: Any, name: str = f"{SID}.json") -> None:
    (root / "deletion-journal" / name).write_text(json.dumps(value), encoding="utf-8")


def intent(value: int, session: str = SID) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "session_id": session,
        "generation": value,
        "state": "DELETE_REQUESTED",
    }


def raw(library: Library, statement: str, *args: Any) -> None:
    library._db.execute(statement, args)
    library._db.commit()


def drop_catalog(library: Library, session: str = SID) -> None:
    for table in ("chunks", "storage_events", "sessions"):
        raw(library, f"DELETE FROM {table} WHERE session_id=?", session)  # noqa: S608


class Remover:
    """Counts real removal attempts; an optional test blocker raises PermissionError."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls = 0
        self.locked = False
        self.original = library_module.remove_tree
        monkeypatch.setattr(library_module, "remove_tree", self)

    def __call__(self, path: Path) -> None:
        self.calls += 1
        if self.locked:
            raise PermissionError("G05 injected locked media")
        self.original(path)


@pytest.fixture(scope="module")
def template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_template(tmp_path_factory.mktemp("g05-unit-template") / "library")


@pytest.fixture
def opened(template: Path, tmp_path: Path) -> Iterator[tuple[Library, Path]]:
    root = clone(template, tmp_path / "library")
    library = Library(root)
    try:
        yield library, root
    finally:
        library.close()


# --- INV: DB 3 x journal 4 x session row 2 x folder 3 = 72 ------------------------------

INV_DIMENSIONS = list(
    itertools.product(
        ("none", "pending", "local"),
        ("none", "valid", "corrupt", "tmp"),
        (True, False),
        ("none", "full", "partial"),
    )
)
INV_CASES = [
    pytest.param(*dims, id=f"G05-INV-{index:04d}") for index, dims in enumerate(INV_DIMENSIONS)
]


def expected_inventory(db: str, journal: str, session: bool, folder: str) -> dict[str, Any] | str:
    """Section 2.2 reconciliation table, written by hand. A string means a whole-list failure."""
    if journal in ("corrupt", "tmp"):
        return "HISTORY_UNAVAILABLE"
    if db == "none" and journal == "none":
        return "NOT_LISTED"
    if db == "local" and journal == "valid" and not session and folder == "none":
        return "NOT_LISTED"  # a normal completed tombstone
    if journal == "none":
        reason = "JOURNAL_REPAIR_REQUIRED"
    elif folder == "none":
        reason = "CATALOG_CLEANUP_REQUIRED"
    else:
        reason = "RETRY_REQUIRED"
    sources = {
        ("pending", "none"): ("db",),
        ("local", "none"): ("db",),
        ("none", "valid"): ("journal",),
    }.get((db, journal), ("db", "journal"))
    return {
        "session_id": SID,
        "generation": 2,
        "state": "DELETE_PENDING",
        "deleted": False,
        "db_status": {"none": None, "pending": "DELETE_PENDING", "local": "DELETED_LOCAL"}[db],
        "intent_sources": sources,
        "session_present": session,
        "media_present": folder != "none",
        "live": False,
        "active_reader_or_writer": False,
        "reason": reason,
        # One side missing; the fixture keeps S at g whenever D exists.
        "repair_required": db == "none" or journal == "none",
    }


def inv_world(library: Library, root: Path, db: str, journal: str, session: bool, folder: str):
    if session:
        raw(
            library,
            "UPDATE sessions SET generation=? WHERE session_id=?",
            2 if db != "none" else 1,
            SID,
        )
    else:
        drop_catalog(library)
    if folder == "none":
        shutil.rmtree(root / "sessions" / SID)
    elif folder == "partial":
        (root / "sessions" / SID / "tracks" / "mic" / "e1" / "c1" / "audio.pcm").unlink()
    if db != "none":
        status = "DELETE_PENDING" if db == "pending" else "DELETED_LOCAL"
        raw(library, "INSERT INTO deleted_sessions VALUES(?,?,?)", SID, 2, status)
    if journal == "valid":
        write_journal(root, intent(2))
    elif journal == "corrupt":
        (root / "deletion-journal" / f"{SID}.json").write_bytes(b'{"schema_version":1,')
    elif journal == "tmp":
        (root / "deletion-journal" / ".tmp-orphan").write_bytes(b"{")


@pytest.mark.parametrize(("db", "journal", "session", "folder"), INV_CASES)
def test_inventory_reconciliation_is_read_only(
    opened: tuple[Library, Path],
    monkeypatch: pytest.MonkeyPatch,
    db: str,
    journal: str,
    session: bool,
    folder: str,
) -> None:
    library, root = opened
    inv_world(library, root, db, journal, session, folder)
    remover = Remover(monkeypatch)
    before = snapshot(library, root)
    expected = expected_inventory(db, journal, session, folder)
    if expected == "HISTORY_UNAVAILABLE":
        with pytest.raises(ValidationError) as refused:
            library.pending_deletions()
        assert refused.value.args == (HISTORY_UNAVAILABLE,)
    else:
        listed = library.pending_deletions()
        assert listed == ([] if expected == "NOT_LISTED" else [expected])
        assert json.loads(json.dumps(listed)) is not None  # closed, JSON-safe fields only
        unfinished = {item["session_id"] for item in library.unfinished_sessions()}
        has_intent = db != "none" or journal == "valid"
        # Intents never leak into the G-P04 list. Without one, the FINALIZED row is not
        # unfinished and a folder without a row is DIRECTORY_ONLY (never a deletion).
        assert (SID in unfinished) == (not has_intent and not session and folder != "none")
    assert snapshot(library, root) == before  # logical rows, journal bytes, file hashes
    assert remover.calls == 0


# --- GEN: D status 2 x generation shape 5 x folder 3 = 30 ---------------------------------

SHAPES = {
    # name: (D, J, S, g or None for a conflict)
    "same": (2, 2, 2, 2),
    "journal_newer": (2, 3, 2, 3),
    "db_newer": (3, 2, 2, 3),
    "catalog_newer": (2, 2, 3, None),
    "max": (MAX, MAX, MAX, MAX),
}
GEN_DIMENSIONS = list(
    itertools.product(
        ("DELETE_PENDING", "DELETED_LOCAL"), tuple(SHAPES), ("none", "full", "partial")
    )
)
GEN_CASES = [
    pytest.param(*dims, id=f"G05-GEN-{index:04d}") for index, dims in enumerate(GEN_DIMENSIONS)
]
GEN_REASON = {
    "same": None,
    "journal_newer": None,
    "db_newer": "JOURNAL_REPAIR_REQUIRED",
    "max": None,
}
GEN_REPAIR = {"same": False, "journal_newer": True, "db_newer": True, "max": False}


@pytest.mark.parametrize(("status", "shape", "folder"), GEN_CASES)
def test_generation_is_the_maximum_and_never_decreases(
    opened: tuple[Library, Path],
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    shape: str,
    folder: str,
) -> None:
    library, root = opened
    d, j, s, g = SHAPES[shape]
    raw(library, "UPDATE sessions SET generation=? WHERE session_id=?", s, SID)
    raw(library, "INSERT INTO deleted_sessions VALUES(?,?,?)", SID, d, status)
    write_journal(root, intent(j))
    if folder == "none":
        shutil.rmtree(root / "sessions" / SID)
    elif folder == "partial":
        (root / "sessions" / SID / "tracks" / "mic" / "e1" / "c2" / "blocks.jsonl").unlink()
    remover = Remover(monkeypatch)
    before = snapshot(library, root)
    if g is None:
        with pytest.raises(StateConflict) as conflict:
            library.pending_deletions()
        assert conflict.value.args == ("DELETE_HISTORY_CONFLICT",)
        for expected in (2, 3):
            with pytest.raises(StateConflict) as refused:
                library.retry_deletion(SID, expected_generation=expected)
            assert refused.value.args == ("DELETE_HISTORY_CONFLICT",)
        assert snapshot(library, root) == before and remover.calls == 0
        return
    [row] = library.pending_deletions()
    reason = GEN_REASON[shape] or (
        "CATALOG_CLEANUP_REQUIRED" if folder == "none" else "RETRY_REQUIRED"
    )
    assert (row["generation"], row["reason"], row["repair_required"]) == (
        g,
        reason,
        GEN_REPAIR[shape],
    )
    assert row["db_status"] == status and row["session_present"] is True
    with pytest.raises(StateConflict) as stale:
        library.retry_deletion(SID, expected_generation=g - 1)
    assert stale.value.args == ("STALE_DELETE_GENERATION",)
    assert snapshot(library, root) == before and remover.calls == 0
    result = library.retry_deletion(SID, expected_generation=g)
    assert result == {
        "session_id": SID,
        "state": "DELETED_LOCAL",
        "deleted": True,
        "already_deleted": False,
        "generation": g,
    }
    assert remover.calls == (0 if folder == "none" else 1)
    assert deleted_row(library) == (g, "DELETED_LOCAL") and journal_generation(root) == g
    assert media(root) == {} and not (root / "sessions" / SID).exists()
    assert library._db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
    assert library._db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 0
    assert library.pending_deletions() == []
    completed = snapshot(library, root)
    again = library.retry_deletion(SID, expected_generation=g)
    assert again == dict(result, already_deleted=True)
    assert snapshot(library, root) == completed  # no new generation or record


# --- HISTORY: 22 hand-written corruptions --------------------------------------------------

HISTORY = [
    "journal_directory_missing",
    "tmp_left",
    "json_syntax",
    "duplicate_key",
    "name_id_mismatch",
    "traversal_id",
    "future_schema",
    "wrong_state",
    "generation_zero",
    "generation_negative",
    "generation_bool",
    "generation_overflow",
    "generation_missing",
    "db_status_unsupported",
    "db_generation_zero",
    "db_generation_text",
    "db_generation_real",
    "json_list",
    "journal_is_file",
    "unknown_entry",
    "db_table_missing",
    "journal_permission_denied",
]
HISTORY_CASES = [
    pytest.param(name, id=f"G05-HISTORY-{index:04d}") for index, name in enumerate(HISTORY)
]


def pending_intent(library: Library, root: Path, generation: int = 6) -> int:
    raw(library, "UPDATE sessions SET generation=? WHERE session_id=?", generation, SID)
    raw(library, "INSERT INTO deleted_sessions VALUES(?,?,'DELETE_PENDING')", SID, generation)
    write_journal(root, intent(generation))
    return generation


def corrupt(library: Library, root: Path, name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    journal = root / "deletion-journal"
    body = intent(6)
    if name == "journal_directory_missing":
        shutil.rmtree(journal)
    elif name == "tmp_left":
        (journal / ".tmp-abandoned").write_bytes(b'{"schema_version":1')
    elif name == "json_syntax":
        (journal / "x.json").write_bytes(b'{"schema_version":1,,}')
    elif name == "duplicate_key":
        (journal / f"{SID}.json").write_text(
            '{"schema_version":1,"session_id":"s","generation":6,"generation":7,'
            '"state":"DELETE_REQUESTED"}',
            encoding="utf-8",
        )
    elif name == "name_id_mismatch":
        write_journal(root, body, "other.json")
    elif name == "traversal_id":
        write_journal(root, dict(body, session_id="../s"))
    elif name == "future_schema":
        write_journal(root, dict(body, schema_version=2))
    elif name == "wrong_state":
        write_journal(root, dict(body, state="DELETED"))
    elif name == "generation_zero":
        write_journal(root, dict(body, generation=0))
    elif name == "generation_negative":
        write_journal(root, dict(body, generation=-6))
    elif name == "generation_bool":
        write_journal(root, dict(body, generation=True))
    elif name == "generation_overflow":
        write_journal(root, dict(body, generation=MAX + 1))
    elif name == "generation_missing":
        write_journal(root, {key: value for key, value in body.items() if key != "generation"})
    elif name == "db_status_unsupported":
        raw(library, "UPDATE deleted_sessions SET status='DELETED' WHERE session_id=?", SID)
    elif name == "db_generation_zero":
        raw(library, "UPDATE deleted_sessions SET generation=0 WHERE session_id=?", SID)
    elif name == "db_generation_text":
        raw(library, "UPDATE deleted_sessions SET generation='six' WHERE session_id=?", SID)
    elif name == "db_generation_real":
        raw(library, "UPDATE deleted_sessions SET generation=6.5 WHERE session_id=?", SID)
    elif name == "json_list":
        (journal / f"{SID}.json").write_text(json.dumps([body]), encoding="utf-8")
    elif name == "journal_is_file":
        shutil.rmtree(journal)
        journal.write_bytes(b"not a directory")
    elif name == "unknown_entry":
        (journal / "notes.txt").write_bytes(b"x")
    elif name == "db_table_missing":
        raw(library, "DROP TABLE deleted_sessions")
    else:
        original = library_module.read_json

        def denied(path: Path, **kwargs: Any) -> dict[str, Any]:
            if path.parent.name == "deletion-journal":
                raise PermissionError("G05 injected journal read denial")
            return original(path, **kwargs)

        monkeypatch.setattr(library_module, "read_json", denied)


@pytest.mark.parametrize("name", HISTORY_CASES)
def test_damaged_history_is_never_an_empty_or_completed_list(
    opened: tuple[Library, Path], monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    library, root = opened
    generation = pending_intent(library, root)
    remover = Remover(monkeypatch)
    with monkeypatch.context() as patch:
        corrupt(library, root, name, patch)
        before = snapshot(library, root)
        with pytest.raises(ValidationError) as listed:
            library.pending_deletions()
        assert listed.value.args == (HISTORY_UNAVAILABLE,)
        with pytest.raises(ValidationError) as retried:
            library.retry_deletion(SID, expected_generation=generation)
        assert retried.value.args == (HISTORY_UNAVAILABLE,)
        with pytest.raises(ValueError):
            library.delete_session(SID)  # the shared progression fails closed too
        with pytest.raises(ValueError):
            library.recover_session(SID)  # never re-adopted on an unreadable history
    assert remover.calls == 0
    assert snapshot(library, root) == before  # no repair, removal or record change


# --- TYPE: ID 5 + expected_generation 7 single-change fixtures = 12 -----------------------

TYPE_VALUES: list[tuple[Any, Any]] = [
    ("", 6),
    ("../s", 6),
    ("C:\\abs", 6),
    (None, 6),
    (True, 6),
    (SID, 0),
    (SID, -1),
    (SID, True),
    (SID, 1.5),
    (SID, "6"),
    (SID, None),
    (SID, MAX + 1),
]
TYPE_CASES = [
    pytest.param(*value, id=f"G05-TYPE-{index:04d}") for index, value in enumerate(TYPE_VALUES)
]


@pytest.mark.parametrize(("session_id", "expected"), TYPE_CASES)
def test_invalid_retry_arguments_change_nothing(
    opened: tuple[Library, Path], monkeypatch: pytest.MonkeyPatch, session_id: Any, expected: Any
) -> None:
    library, root = opened
    pending_intent(library, root)
    remover = Remover(monkeypatch)
    before = snapshot(library, root)
    with pytest.raises(ValidationError):
        library.retry_deletion(session_id, expected_generation=expected)
    assert remover.calls == 0 and snapshot(library, root) == before
    assert library.pending_deletions()[0]["generation"] == 6  # the baseline stays valid


# --- FIX1 (G05R-03): properties the first test set did not pin down ------------------
# Additional rows outside the 3,166 contract rows: G05-FIX1-0000..0003 here.


@pytest.mark.parametrize("action", ("retry", "delete"), ids=["G05-FIX1-0000", "G05-FIX1-0001"])
def test_a_completed_tombstone_is_never_demoted_while_repairing(
    opened: tuple[Library, Path], monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    """Section 2.2 table row 6 / 2.3-3: DELETED_LOCAL + newer journal + leftover media."""
    library, root = opened
    raw(library, "UPDATE sessions SET generation=2 WHERE session_id=?", SID)
    raw(library, "INSERT INTO deleted_sessions VALUES(?,2,'DELETED_LOCAL')", SID)
    write_journal(root, intent(3))  # the newer side wins: g=3
    remover = Remover(monkeypatch)
    remover.locked = True
    before = media(root)
    if action == "retry":
        result = library.retry_deletion(SID, expected_generation=3)
        assert result == {
            "session_id": SID,
            "state": "DELETE_PENDING",
            "deleted": False,
            "reason": "MEDIA_REMOVAL_FAILED",
            "generation": 3,
        }
    else:
        assert library.delete_session(SID)["reason"] == "MEDIA_REMOVAL_FAILED"
    assert remover.calls == 1 and media(root) == before
    # Reinforced to g, never demoted to DELETE_PENDING and never removed.
    assert deleted_row(library) == (3, "DELETED_LOCAL") and journal_generation(root) == 3
    [row] = library.pending_deletions()
    assert (row["db_status"], row["reason"], row["generation"]) == (
        "DELETED_LOCAL",
        "RETRY_REQUIRED",
        3,
    )


def completed_tombstone(library: Library, root: Path) -> int:
    assert library.delete_session(SID)["state"] == "DELETED_LOCAL"
    generation = journal_generation(root)
    assert generation is not None and deleted_row(library) == (generation, "DELETED_LOCAL")
    return generation


@pytest.mark.parametrize("case", [pytest.param(2, id="G05-FIX1-0002")])
def test_an_uninspectable_session_path_is_never_reported_completed(
    opened: tuple[Library, Path], monkeypatch: pytest.MonkeyPatch, case: int
) -> None:
    """G05-FIX1-0002: a path check failure is not absence (section 2.1, no completion guess)."""
    library, root = opened
    generation = completed_tombstone(library, root)
    original = library_module.safe_path

    def refused(base: Path, *parts: str) -> Path:
        if parts == (f"sessions/{SID}",):
            raise ValidationError("Links and reparse points are not supported")
        return original(base, *parts)

    monkeypatch.setattr(library_module, "safe_path", refused)
    remover = Remover(monkeypatch)
    [row] = library.pending_deletions()
    assert (row["media_present"], row["reason"], row["db_status"]) == (
        True,
        "RETRY_REQUIRED",
        "DELETED_LOCAL",
    )
    result = library.retry_deletion(SID, expected_generation=generation)
    assert (result["state"], result["deleted"], result["reason"]) == (
        "DELETE_PENDING",
        False,
        "MEDIA_REMOVAL_FAILED",
    )
    assert remover.calls == 0 and deleted_row(library) == (generation, "DELETED_LOCAL")


@pytest.mark.skipif(sys.platform != "win32", reason="actual NTFS junction requires Windows")
@pytest.mark.parametrize("case", [pytest.param(3, id="G05-FIX1-0003")])
def test_a_junction_at_a_completed_session_path_is_not_completed_or_followed(
    opened: tuple[Library, Path], tmp_path: Path, case: int
) -> None:
    """G05-FIX1-0003: real junction after completion; the outside target is untouched."""
    import _winapi

    library, root = opened
    generation = completed_tombstone(library, root)
    outside = tmp_path / "outside"
    outside.mkdir()
    victim = outside / "victim.bin"
    victim.write_bytes(b"keep" * 64)
    digest = hashlib.sha256(victim.read_bytes()).hexdigest()
    link = root / "sessions" / SID
    link.parent.mkdir(parents=True, exist_ok=True)
    _winapi.CreateJunction(str(outside), str(link))
    try:
        assert getattr(link.lstat(), "st_file_attributes", 0) & 0x400
        [row] = library.pending_deletions()
        assert (row["media_present"], row["reason"]) == (True, "RETRY_REQUIRED")
        result = library.retry_deletion(SID, expected_generation=generation)
        assert (result["deleted"], result["reason"]) == (False, "MEDIA_REMOVAL_FAILED")
        assert deleted_row(library) == (generation, "DELETED_LOCAL")
        assert hashlib.sha256(victim.read_bytes()).hexdigest() == digest
    finally:
        # Remove only the junction itself, never recurse into its target.
        assert getattr(link.lstat(), "st_file_attributes", 0) & 0x400
        link.rmdir()
    assert victim.is_file()


def test_declared_unit_denominators_are_complete_and_unique() -> None:
    groups = {"INV": INV_CASES, "GEN": GEN_CASES, "HISTORY": HISTORY_CASES, "TYPE": TYPE_CASES}
    sizes = {name: len(cases) for name, cases in groups.items()}
    assert sizes == {"INV": 3 * 4 * 2 * 3, "GEN": 2 * 5 * 3, "HISTORY": 22, "TYPE": 5 + 7}
    for name, cases in groups.items():
        assert [case.id for case in cases] == [f"G05-{name}-{i:04d}" for i in range(sizes[name])]
