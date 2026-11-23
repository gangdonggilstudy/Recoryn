"""G15 seal phases: writer states, one verification per seal, damaged staging, fsync count,
and (PART2) the registration path, overlap ranges and the append deletion check.

Expected values are literal tables from docs/testing/g15-seal-mutex-cases.md section 4.3,
never derived from the writer's own state helpers. Synthetic PCM in temporary folders.
"""

from __future__ import annotations

import copy
import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from recoryn.domain import AudioFormat, PCMBlock, SessionState, StateConflict, ValidationError
from recoryn.storage import ChunkWriter, Library, chunks
from recoryn.storage import _coordination as coordination
from recoryn.storage import library as library_module
from recoryn.storage.chunks import SealedChunk, has_active_writer, is_issued

pytestmark = pytest.mark.unit

FMT = AudioFormat(48000, 1)


def block(index: int, epoch: str = "e1", track: str = "mic", session: str = "s") -> PCMBlock:
    return PCMBlock(
        session,
        track,
        epoch,
        index,
        FMT,
        4,
        bytes([10 + index, 0]) * 4,
        1_000 + index * 100,
        1_000 + index * 100,
        device_frame_position=index * 4,
    )


def opened(root: Path, count: int = 2) -> ChunkWriter:
    writer = ChunkWriter(root, block(0))
    for index in range(count):
        writer.append(block(index))
    return writer


def state(root: Path, name: str) -> ChunkWriter:
    writer = opened(root)
    if name == "SEALING":
        writer.hold()  # sealed and published, still active until unhold()
        writer.seal()
    elif name == "PUBLISHED":
        writer.seal()
    elif name == "ABORTED":
        writer.abort()
    return writer


def attempt(writer: ChunkWriter, operation: str) -> object:
    try:
        if operation == "append":
            writer.append(block(2))
        elif operation == "seal":
            writer.seal()
        elif operation == "abort":
            writer.abort()
        else:
            return has_active_writer(writer.root, "s")
    except (ValueError, OSError):
        return "REFUSED"
    return "OK"


# Section 4.3, by hand. abort never raises; it only closes what is still open.
TABLE = {
    "OPEN": {"append": "OK", "seal": "OK", "abort": "OK", "active": True},
    "SEALING": {"append": "REFUSED", "seal": "REFUSED", "abort": "OK", "active": True},
    "PUBLISHED": {"append": "REFUSED", "seal": "REFUSED", "abort": "OK", "active": False},
    "ABORTED": {"append": "REFUSED", "seal": "REFUSED", "abort": "OK", "active": False},
}
CASES = [
    pytest.param(name, operation, id=f"G15-W-{name}-{operation}")
    for name in TABLE
    for operation in ("append", "seal", "abort", "active")
]


@pytest.mark.parametrize(("name", "operation"), CASES)
def test_writer_state_table(tmp_path: Path, name: str, operation: str) -> None:
    writer = state(tmp_path, name)
    try:
        assert attempt(writer, operation) == TABLE[name][operation]
        if name == "SEALING" and operation == "abort":
            assert has_active_writer(writer.root, "s")  # abort cannot end a held seal
    finally:
        writer.unhold()
        writer.abort()
    assert not has_active_writer(tmp_path, "s")


def counting(monkeypatch: pytest.MonkeyPatch, name: str) -> list[int]:
    calls = [0]
    original: Callable[..., Any] = getattr(chunks, name)

    def counted(*args: Any, **kwargs: Any) -> Any:
        calls[0] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(chunks, name, counted)
    return calls


def test_one_disk_verification_per_seal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """G15-U-verify-once"""
    writer = opened(tmp_path, 3)
    scans = counting(monkeypatch, "scan_prefix")
    bundles = counting(monkeypatch, "verify_bundle")
    descriptor = writer.seal()
    assert scans[0] == 1 and bundles[0] == 0
    monkeypatch.undo()
    assert chunks.verify_bundle(tmp_path / descriptor.relative_path) == descriptor


def corrupt_payload(staging: Path) -> None:
    with (staging / "audio.pcm").open("r+b") as stream:
        first = stream.read(1)
        stream.seek(0)
        stream.write(bytes([first[0] ^ 0xFF]))


def torn_journal(staging: Path) -> None:
    data = (staging / "blocks.jsonl").read_bytes()
    with (staging / "blocks.jsonl").open("r+b") as stream:
        stream.truncate(len(data) - 5)


def pcm_tail(staging: Path) -> None:
    with (staging / "audio.pcm").open("ab") as stream:
        stream.write(b"tail")


DAMAGE = [
    pytest.param(corrupt_payload, id="G15-U-damage-payload-bit"),
    pytest.param(torn_journal, id="G15-U-damage-torn-journal"),
    pytest.param(pcm_tail, id="G15-U-damage-unjournaled-tail"),
]


@pytest.mark.parametrize("damage", DAMAGE)
def test_damaged_staging_is_never_published(tmp_path: Path, damage: Callable[[Path], None]) -> None:
    writer = opened(tmp_path, 3)
    staging = writer.staging_path
    damage(staging)
    with pytest.raises(ValueError):
        writer.seal()
    assert not writer.path.exists()  # nothing under tracks/
    assert staging.is_dir()  # kept for recovery
    assert not has_active_writer(tmp_path, "s")


def test_fsync_count_per_append_and_seal_is_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G15-U-fsync-count: two per append (payload, journal), three per seal (I5)."""
    syncs = counting(monkeypatch, "sync")
    writer = ChunkWriter(tmp_path, block(0))
    for index in range(3):
        writer.append(block(index))
    assert syncs[0] == 6
    writer.seal()
    assert syncs[0] == 9


CAPABILITY = [
    pytest.param("issued", True, id="G15-U-cap-issued"),
    pytest.param("released", False, id="G15-U-cap-released"),
    pytest.param("constructed", False, id="G15-U-cap-constructed"),
    pytest.param("copied", False, id="G15-U-cap-copied"),
]


@pytest.mark.parametrize(("kind", "accepted"), CAPABILITY)
def test_sealed_chunk_capability_cannot_be_forged(
    tmp_path: Path, kind: str, accepted: bool
) -> None:
    """C00 condition: only the live object issued by this process's sealer counts."""
    writer = opened(tmp_path)
    sealed = writer.seal_chunk()
    try:
        candidate: object = sealed
        if kind == "released":
            sealed.release()
        elif kind == "constructed":
            candidate = SealedChunk(writer, sealed.descriptor)
        elif kind == "copied":
            candidate = copy.copy(sealed)
        assert is_issued(candidate) is accepted
        assert is_issued(sealed.descriptor) is False  # public data alone never counts
    finally:
        sealed.release()
    assert not has_active_writer(tmp_path, "s")


def recording_library(root: Path) -> Library:
    library = Library(root)
    library.create_session("s")
    library.transition("s", SessionState.RECORDING, 0)
    return library


def held_writer(root: Path, blocks: list[PCMBlock]) -> ChunkWriter:
    writer = ChunkWriter(root, blocks[0])
    for item in blocks:
        writer.append(item)
    writer.hold()
    writer.seal()
    return writer


def capability_of(writer: ChunkWriter) -> SealedChunk:
    capability = writer.capability
    assert capability is not None
    return capability


OVERLAP = "Overlapping source sequence ranges"


def test_overlap_with_an_older_chunk_of_the_same_track_and_epoch(tmp_path: Path) -> None:
    """G15-U-overlap-older-chunk (MU8): every earlier range counts, not only the last."""
    with recording_library(tmp_path) as library:

        def register(blocks: list[PCMBlock]) -> str:
            writer = held_writer(tmp_path, blocks)
            try:
                library.register_chunk(capability_of(writer))
            except StateConflict as error:
                return str(error)
            finally:
                writer.unhold()
            return "ACCEPTED"

        assert register([block(0), block(1)]) == "ACCEPTED"  # A: 0-1
        assert register([block(2), block(3)]) == "ACCEPTED"  # B: 2-3, now the last
        outcomes = {
            "C-overlaps-older-A": register([block(1)]),
            "D-other-epoch": register([block(1, "e2")]),
            "E-other-track": register([block(1, track="system")]),
            "F-adjacent-to-B": register([block(4), block(5)]),
            "G-overlaps-older-B": register([block(3)]),
        }
        assert outcomes == {
            "C-overlaps-older-A": OVERLAP,
            "D-other-epoch": "ACCEPTED",
            "E-other-track": "ACCEPTED",
            "F-adjacent-to-B": "ACCEPTED",
            "G-overlaps-older-B": OVERLAP,
        }
        assert len(library.chunks("s")) == 5


CHANGED = "Sealed chunk changed before registration"
REGISTRATION = [
    pytest.param("capability", 0, None, id="G15-U-reg-capability-skips-verify"),
    pytest.param("descriptor", 1, None, id="G15-U-reg-descriptor-verifies"),
    pytest.param("released", 1, None, id="G15-U-reg-released-capability-verifies"),
    pytest.param("descriptor-json-changed", 0, CHANGED, id="G15-U-reg-descriptor-json-changed"),
    pytest.param("pcm-size-changed", 0, CHANGED, id="G15-U-reg-pcm-size-changed"),
]


@pytest.mark.parametrize(("kind", "verifications", "error"), REGISTRATION)
def test_registration_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    verifications: int,
    error: str | None,
) -> None:
    """C00 decision 2: only a live capability skips verify_bundle, never the identity check."""
    calls = [0]
    original = library_module.verify_bundle

    def counted(path: Path) -> Any:
        calls[0] += 1
        return original(path)

    monkeypatch.setattr(library_module, "verify_bundle", counted)
    with recording_library(tmp_path) as library:
        writer = held_writer(tmp_path, [block(0), block(1)])
        capability = capability_of(writer)
        candidate: Any = capability
        if kind == "descriptor":
            candidate = capability.descriptor
        elif kind == "released":
            writer.unhold()  # no longer issued: treated like any other caller
        elif kind == "descriptor-json-changed":
            path = writer.path / "descriptor.json"
            path.write_bytes(path.read_bytes() + b" ")
        elif kind == "pcm-size-changed":
            with (writer.path / "audio.pcm").open("ab") as stream:
                stream.write(bytes(2))
        try:
            if error is None:
                library.register_chunk(candidate)
            else:
                with pytest.raises(ValidationError) as raised:
                    library.register_chunk(candidate)
                assert str(raised.value) == error
        finally:
            writer.unhold()
        assert len(library.chunks("s")) == (1 if error is None else 0)
    assert calls[0] == verifications


COORDINATION = [
    pytest.param("open", id="G15-U-append-open-library-index"),
    pytest.param("closed", id="G15-U-append-closed-library-durable"),
]


@pytest.mark.parametrize("library_state", COORDINATION)
def test_append_deletion_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, library_state: str
) -> None:
    """Section 12.4 (1): an open Library answers from its index, else the durable check."""
    library = recording_library(tmp_path)
    live = ChunkWriter(tmp_path, block(0))
    gone = None
    try:
        live.append(block(0))
        library.create_session("gone")
        gone = ChunkWriter(tmp_path, block(0, session="gone"))
        gone.append(block(0, session="gone"))
        # The open writer keeps it pending; G-P05 reports an active writer as live first.
        pending = library.delete_session("gone")
        assert (pending["state"], pending["reason"]) == ("DELETE_PENDING", "SESSION_LIVE")
        if library_state == "closed":
            library.close()
        connects = [0]
        original = coordination.sqlite3.connect

        def counted(*args: Any, **kwargs: Any) -> Any:
            connects[0] += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(coordination.sqlite3, "connect", counted)
        live.append(block(1))  # its own session has no intent
        with pytest.raises(StateConflict) as refused:
            gone.append(block(1, session="gone"))
        monkeypatch.undo()
        assert str(refused.value) == "Writer session has a deletion intent"
        # Open: the index answers without a SQLite connection per append (was ~1 ms).
        assert (connects[0] == 0) is (library_state == "open")
    finally:
        live.abort()
        if gone is not None:
            gone.abort()
        library.close()
    assert not has_active_writer(tmp_path, "s") and not has_active_writer(tmp_path, "gone")


HISTORY_UNAVAILABLE = "DELETION_HISTORY_UNAVAILABLE"


def history_unavailable(call: Callable[[], Any]) -> bool:
    try:
        call()
    except ValidationError as error:
        return error.args == (HISTORY_UNAVAILABLE,)
    return False


def intent_file(root: Path, session: str) -> None:
    body = {
        "schema_version": 1,
        "session_id": session,
        "generation": 1,
        "state": "DELETE_REQUESTED",
    }
    (root / "deletion-journal" / f"{session}.json").write_text(json.dumps(body), encoding="utf-8")


def fc_same_tick_name_change(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A change inside the same mtime tick keeps the stamp; the unsettled listing sees it."""
    with recording_library(root) as library:
        journal = root / "deletion-journal"
        before = os.stat(journal)
        (journal / "notes.txt").write_bytes(b"x")
        os.utime(journal, ns=(before.st_atime_ns, before.st_mtime_ns))
        after = os.stat(journal)
        assert (after.st_ino, after.st_mtime_ns) == (before.st_ino, before.st_mtime_ns)
        assert history_unavailable(lambda: library.get_session("s"))


def fc_changed_while_reading(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A journal that changes during the full re-validation is never trusted."""
    with recording_library(root) as library:
        journal = root / "deletion-journal"
        intent_file(root, "ext")  # outside change: the next query re-validates in full
        original = library_module.read_json

        def racing(path: Path, **kwargs: Any) -> Any:
            if path.parent.name == "deletion-journal" and not (journal / "ext2.json").exists():
                intent_file(root, "ext2")
                stamp = os.stat(journal)
                os.utime(journal, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 10**9))
            return original(path, **kwargs)

        monkeypatch.setattr(library_module, "read_json", racing)
        assert history_unavailable(lambda: library.get_session("s"))
        monkeypatch.undo()
        assert library.get_session("s").session_id == "s"


def fc_missing_history(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A library whose journal folder vanished refuses queries and capture alike."""
    with recording_library(root):
        pass
    (root / "deletion-journal").rmdir()
    with Library(root) as library:
        assert history_unavailable(lambda: library.get_session("s"))
        assert history_unavailable(lambda: library.create_session("t"))
        writer = None
        try:
            with pytest.raises(ValidationError) as refused:
                writer = ChunkWriter(root, block(0))
                writer.append(block(0))
        finally:
            if writer is not None:
                writer.abort()
        assert str(refused.value) == "Cannot verify writer deletion intent"


def fc_unsupported_db_status(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The session's own DB deletion row is validated, never read as absence."""
    with recording_library(root) as library:
        library._db.execute("INSERT INTO deleted_sessions VALUES('s',1,'DELETED')")
        library._db.commit()
        assert history_unavailable(lambda: library.get_session("s"))
        assert history_unavailable(library.list_sessions)


def fc_settled_listing_cache(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """After an outside change capture reads entry names only, cached once settled."""
    with recording_library(root):
        journal = root / "deletion-journal"
        writer = ChunkWriter(root, block(0))
        try:
            writer.append(block(0))
            intent_file(root, "ext")  # outside change; nothing re-validates the index
            past = time.time_ns() - 10 * 10**9
            os.utime(journal, ns=(past, past))  # observed long after this mtime: settled
            listings = [0]
            original = os.scandir

            def scandir(path: Any = ".") -> Any:
                if Path(path).name == "deletion-journal":
                    listings[0] += 1
                return original(path)

            monkeypatch.setattr(library_module.os, "scandir", scandir)
            writer.append(block(1))  # one listing, cached
            writer.append(block(2))  # from the cache
            monkeypatch.undo()
            assert listings[0] == 1
            intent_file(root, "s")  # its own intent, written outside: a new stamp
            with pytest.raises(StateConflict) as refused:
                writer.append(block(3))
            assert str(refused.value) == "Writer session has a deletion intent"
        finally:
            writer.abort()


def fc_closed_callback(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A writer that fetched the callback before close falls back to the durable check."""
    library = recording_library(root)
    reference = coordination._intent_checks[library.root]
    check = reference()
    assert check is not None and check("s") is False
    library.close()
    assert check("s") is None
    assert library.root not in coordination._intent_checks


def fc_register_unknown_session(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A capability for a session without a catalog row is refused, as before."""
    with recording_library(root) as library:
        writer = held_writer(root, [block(0, session="ghost")])
        try:
            with pytest.raises(KeyError):
                library.register_chunk(capability_of(writer))
        finally:
            writer.unhold()
        assert library._db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 0


def fc_prepare_mismatch(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A read-back that differs from the writer's own descriptor publishes nothing."""
    writer = opened(root)
    monkeypatch.setattr(chunks, "_verified", lambda path, location: object())
    with pytest.raises(ValidationError) as refused:
        writer.seal()
    assert str(refused.value) == "Sealed chunk differs from its writer"
    assert not writer.path.exists() and writer.staging_path.is_dir()
    assert not has_active_writer(root, "s")


def fc_final_bundle_exists(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An existing final folder is never replaced; the staging stays for recovery."""
    writer = opened(root)
    writer.path.mkdir(parents=True)
    with pytest.raises(FileExistsError):
        writer.seal()
    assert list(writer.path.iterdir()) == [] and writer.staging_path.is_dir()
    assert not has_active_writer(root, "s")


def _deleted_while(root: Path, monkeypatch: pytest.MonkeyPatch, inject: str) -> None:
    with recording_library(root) as library:
        library.create_session("gone")
        state = {"armed": False}
        original_publish = Library._publish_intent
        original_current = Library._index_current
        original_stamp = Library._journal_stamp
        original_atomic = library_module.atomic_json

        def publish(self: Library, session_id: str, generation: int) -> None:
            state["armed"] = inject == "index"
            try:
                original_publish(self, session_id, generation)
            finally:
                state["armed"] = False

        def current(self: Library) -> bool:
            if state["armed"]:
                state["armed"] = False
                raise OSError("G15 injected stat failure")
            return original_current(self)

        def atomic(path: Path, value: object) -> None:
            original_atomic(path, value)
            if inject == "stamp" and path.parent.name == "deletion-journal":
                state["armed"] = True

        def stamp(self: Library) -> tuple[int, int, int]:
            if inject == "stamp" and state["armed"]:
                state["armed"] = False
                raise OSError("G15 injected stat failure")
            return original_stamp(self)

        monkeypatch.setattr(Library, "_publish_intent", publish)
        monkeypatch.setattr(Library, "_index_current", current)
        monkeypatch.setattr(Library, "_journal_stamp", stamp)
        monkeypatch.setattr(library_module, "atomic_json", atomic)
        assert library.delete_session("gone")["state"] == "DELETED_LOCAL"
        monkeypatch.undo()
        # Nothing trusted a stale index: the next queries re-validate and see the intent.
        assert library.get_session("s").session_id == "s"
        with pytest.raises(StateConflict):
            library.get_session("gone")
        with pytest.raises(StateConflict):
            ChunkWriter(root, block(0, session="gone")).append(block(0, session="gone"))


def fc_publish_index_unknown(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The index cannot be checked while publishing: it is dropped, never extended."""
    _deleted_while(root, monkeypatch, "index")


def fc_publish_stamp_fails(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The stamp cannot be read after publishing: the index stays invalid."""
    _deleted_while(root, monkeypatch, "stamp")


FAIL_CLOSED = [
    pytest.param(fc_same_tick_name_change, id="G15-U-fc-same-tick-name-change"),
    pytest.param(fc_changed_while_reading, id="G15-U-fc-changed-while-reading"),
    pytest.param(fc_missing_history, id="G15-U-fc-missing-history"),
    pytest.param(fc_unsupported_db_status, id="G15-U-fc-unsupported-db-status"),
    pytest.param(fc_settled_listing_cache, id="G15-U-fc-settled-listing-cache"),
    pytest.param(fc_closed_callback, id="G15-U-fc-closed-callback"),
    pytest.param(fc_register_unknown_session, id="G15-U-fc-register-unknown-session"),
    pytest.param(fc_prepare_mismatch, id="G15-U-fc-prepare-mismatch"),
    pytest.param(fc_final_bundle_exists, id="G15-U-fc-final-bundle-exists"),
    pytest.param(fc_publish_index_unknown, id="G15-U-fc-publish-index-unknown"),
    pytest.param(fc_publish_stamp_fails, id="G15-U-fc-publish-stamp-fails"),
]


@pytest.mark.parametrize("case", FAIL_CLOSED)
def test_fail_closed_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: Callable[[Path, pytest.MonkeyPatch], None],
) -> None:
    case(tmp_path, monkeypatch)


def test_declared_unit_denominators_are_complete_and_unique() -> None:
    ids = (
        [case.id for case in CASES]
        + ["G15-U-verify-once", "G15-U-fsync-count"]
        + [case.id for case in DAMAGE]
        + [case.id for case in CAPABILITY]
        + ["G15-U-overlap-older-chunk"]
        + [case.id for case in REGISTRATION]
        + [case.id for case in COORDINATION]
        + [case.id for case in FAIL_CLOSED]
    )
    assert len(CASES) == 4 * 4 and len(DAMAGE) == 3 and len(CAPABILITY) == 4
    assert len(REGISTRATION) == 5 and len(COORDINATION) == 2 and len(FAIL_CLOSED) == 11
    assert len(ids) == len(set(ids)) == 16 + 1 + 3 + 1 + 4 + 1 + 5 + 2 + 11
