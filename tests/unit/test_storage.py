"""Storage contract regressions with explicit independent PCM/hash oracles."""

from __future__ import annotations

import errno
import hashlib
import io
import json
import os
import sqlite3
import subprocess
import sys
import wave
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from recoryn.domain import AudioFormat, PCMBlock, SessionState, StateConflict, ValidationError
from recoryn.storage import ChunkDescriptor, ChunkWriter, Library, _safe, verify_bundle
from recoryn.storage import chunks as chunk_module
from recoryn.storage import library as catalog
from recoryn.storage.chunks import scan_prefix

pytestmark = pytest.mark.unit


def block(
    sequence: int = 0,
    *,
    session: str = "s",
    track: str = "mic",
    epoch: str = "e",
    sample: bytes = b"\x01\x00",
    **kwargs: Any,
) -> PCMBlock:
    return PCMBlock(
        session,
        track,
        epoch,
        sequence,
        AudioFormat(48_000, 1),
        2,
        sample * 2,
        sequence * 1000,
        sequence * 1000,
        **kwargs,
    )


def bundle(root: Path, name: str = "chunk", sequence: int = 0, **kwargs: Any) -> ChunkDescriptor:
    item = block(sequence, **kwargs)
    writer = ChunkWriter(root, item, name)
    writer.append(item)
    return writer.seal()


def ending(lib: Library, session: str = "s") -> None:
    current = lib.get_session(session)
    lib.transition(session, SessionState.FINALIZING, current.state_version)


def rewrite_record(value: dict[str, Any]) -> bytes:
    """Independent spec encoder, deliberately not importing storage.canonical."""
    value.pop("record_sha256", None)
    value["record_sha256"] = hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def child_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).parents[2] / "src")
    return env


def test_constructor_does_not_append_or_create(tmp_path: Path) -> None:
    root = tmp_path / "unused"
    writer = ChunkWriter(root, block())
    assert not root.exists()
    with pytest.raises(ValueError):
        writer.seal()


@pytest.mark.parametrize(
    "sample_type,width", [("s16le", 2), ("s24le", 3), ("s32le", 4), ("f32le", 4)]
)
def test_bundle_roundtrip_and_canonical_checksums(
    tmp_path: Path, sample_type: str, width: int
) -> None:
    fmt = AudioFormat(44_100, 2, sample_type)
    item = PCMBlock("s", "mic", "e", 7, fmt, 3, bytes(range(width * 6)), None, 500)
    writer = ChunkWriter(tmp_path, item, "c")
    writer.append(item)
    result = writer.seal()
    assert (result.frame_count, result.byte_count, result.first_sequence) == (3, width * 6, 7)
    assert result.sha256 == hashlib.sha256(item.payload).hexdigest()
    assert ChunkDescriptor.from_dict(result.to_dict()) == result
    assert verify_bundle(tmp_path / result.relative_path) == result
    record = json.loads((tmp_path / result.relative_path / "blocks.jsonl").read_bytes())
    checksum = record.pop("record_sha256")
    assert (
        checksum
        == hashlib.sha256(
            json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
    )
    with pytest.raises(ValueError):
        writer.append(item)


def test_duplicate_final_identity_never_overwrites(tmp_path: Path) -> None:
    first = bundle(tmp_path)
    original = (tmp_path / first.relative_path / "audio.pcm").read_bytes()
    with pytest.raises(FileExistsError):
        bundle(tmp_path, sample=b"\xff\x00")
    assert (tmp_path / first.relative_path / "audio.pcm").read_bytes() == original


@pytest.mark.parametrize(
    "change",
    ["offset", "identity", "sequence", "fragment", "format", "checksum", "metadata", "schema"],
)
def test_strict_record_mutations_rejected(tmp_path: Path, change: str) -> None:
    writer = ChunkWriter(tmp_path, block(), "c")
    writer.append(block())
    writer.append(block(1))
    descriptor = writer.seal()
    path = tmp_path / descriptor.relative_path
    lines = (path / "blocks.jsonl").read_bytes().splitlines(keepends=True)
    value = json.loads(lines[1])
    if change == "offset":
        value["offset"] = 0
    elif change == "identity":
        value["metadata"]["track_id"] = "other"
    elif change == "sequence":
        value["metadata"]["sequence"] = 0
    elif change == "fragment":
        value["metadata"]["fragment_index"] = 1
    elif change == "format":
        value["metadata"]["format"]["sample_rate"] = 16_000
    elif change == "metadata":
        value["metadata"]["unknown"] = "extra"
    elif change == "schema":
        value["schema_version"] = 2
    else:
        value["payload_sha256"] = "0" * 64
    (path / "blocks.jsonl").write_bytes(lines[0] + rewrite_record(value))
    with pytest.raises(ValidationError):
        verify_bundle(path)
    assert scan_prefix(path).frame_count == 2


def test_duplicate_json_and_nonfinite_rejected(tmp_path: Path) -> None:
    for text in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1.2}', b"[]", b"\xff"):
        with pytest.raises(ValidationError):
            _safe.strict_json(text)
    with pytest.raises(ValidationError):
        _safe.strict_json(b'{"x":"' + b"a" * 65536 + b'"}')


@pytest.mark.parametrize("tail", [b'{"schema_version":', b'{"offset":1,"offset":2}\n', b"\n"])
def test_recovery_prefix_is_new_id_and_repeat_is_idempotent(tmp_path: Path, tail: bytes) -> None:
    with Library(tmp_path) as lib:
        lib.create_session("s")
        lib.transition("s", SessionState.RECORDING, 0)
        writer = ChunkWriter(tmp_path, block(), "original")
        writer.append(block())
        staging = writer.staging_path
        writer.abort()
        with (staging / "blocks.jsonl").open("ab") as stream:
            stream.write(tail)
        with (staging / "audio.pcm").open("ab") as stream:
            stream.write(b"uncommitted")
        before = {p.name: p.read_bytes() for p in staging.iterdir()}
        result = lib.recover_session("s")
        assert (result["recovered"], result["state"]) == (1, "INTERRUPTED")
        assert lib.chunks("s")[0].chunk_id != "original"
        assert lib.chunks("s")[0].frame_count == 2
        assert {p.name: p.read_bytes() for p in staging.iterdir()} == before
        second = lib.recover_session("s")
        assert (second["adopted"], second["recovered"]) == (0, 0)
        assert len(lib.chunks("s")) == 1
        assert {p.name: p.read_bytes() for p in staging.iterdir()} == before


def test_fragment_and_sequence_rules(tmp_path: Path) -> None:
    first = block(fragment_count=2)
    writer = ChunkWriter(tmp_path, first)
    writer.append(first)
    with pytest.raises(ValidationError):
        writer.append(block(1))
    writer.append(block(fragment_index=1, fragment_count=2))
    writer.append(block(3))  # known capture gaps consume sequence numbers
    assert writer.seal().frame_count == 6


def test_orphan_adoption_and_finalized_orphan_is_not_adopted(tmp_path: Path) -> None:
    with Library(tmp_path) as lib:
        lib.create_session("s")
        one = bundle(tmp_path, "one")
        assert lib.recover_session("s")["adopted"] == 1
        assert lib.get_session("s").state == SessionState.CREATED
        lib.register_chunk(one)
        ending(lib)
        assert lib.finalize_session("s")["chunk_count"] == 1
        sealed = (tmp_path / "sessions/s/manifest.json").read_bytes()
        bundle(tmp_path, "two", 1)
        result = lib.recover_session("s")
        assert result["adopted"] == 0 and result["quarantined"] == 1
        assert len(lib.chunks("s")) == 1
        assert (tmp_path / "sessions/s/manifest.json").read_bytes() == sealed


def test_reverse_uuid_catalog_manifest_and_wav_order(tmp_path: Path) -> None:
    with Library(tmp_path) as lib:
        lib.create_session("s")
        early = bundle(tmp_path, "z-later-lexically", 0, sample=b"\x11\x00")
        late = bundle(tmp_path, "a-earlier-lexically", 1, sample=b"\x22\x00")
        lib.register_chunk(late)  # insertion order must not override source sequence
        lib.register_chunk(early)
        assert [c.first_sequence for c in lib.chunks("s")] == [0, 1]
        ending(lib)
        lib.finalize_session("s")
        manifest = json.loads((tmp_path / "sessions/s/manifest.json").read_bytes())
        assert [c["chunk_id"] for c in manifest["chunks"]] == [early.chunk_id, late.chunk_id]
        output = io.BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setparams((1, 2, 48_000, 0, "NONE", "not compressed"))
            for descriptor in lib.chunks("s"):
                wav.writeframes((tmp_path / descriptor.relative_path / "audio.pcm").read_bytes())
        output.seek(0)
        with wave.open(output, "rb") as wav:
            assert wav.readframes(4) == b"\x11\x00" * 2 + b"\x22\x00" * 2


def test_overlapping_chunks_rejected_and_quarantined_on_recovery(tmp_path: Path) -> None:
    with Library(tmp_path) as lib:
        lib.create_session("s")
        one, duplicate = bundle(tmp_path, "one"), bundle(tmp_path, "duplicate")
        lib.register_chunk(one)
        with pytest.raises(StateConflict):
            lib.register_chunk(duplicate)
        result = lib.recover_session("s")
        assert result["quarantined"] == 1
        assert lib.chunks("s") == [one]


def test_manifest_only_failure_preserves_db_finalization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Library(tmp_path) as lib:
        lib.create_session("s")
        lib.register_chunk(bundle(tmp_path))
        ending(lib)
        original = catalog.atomic_json

        def fail_manifest(path: Path, value: object) -> None:
            if path.name == "manifest.json":
                raise PermissionError("injected projection failure")
            original(path, value)

        monkeypatch.setattr(catalog, "atomic_json", fail_manifest)
        result = lib.finalize_session("s")
        assert result == {
            "state": "FINALIZED",
            "manifest_sync_pending": True,
            "chunk_count": 1,
            "frame_count": 2,
        }
        assert lib.get_session("s").state == SessionState.FINALIZED
        monkeypatch.setattr(catalog, "atomic_json", original)
        assert "MANIFEST_SYNC_PENDING" not in lib.recover_session("s")["warnings"]


def test_health_and_cross_thread_writes_survive_reopen(tmp_path: Path) -> None:
    health = {
        "epochs": [
            {
                "tracks": {
                    "mic": {"accepted_frames": 4, "dropped_frames": 2, "gaps": [{"frame_count": 2}]}
                },
                "queue": {"closed": True},
            }
        ]
    }
    with Library(tmp_path) as lib:
        lib.create_session("s")
        descriptors = [bundle(tmp_path, f"chunk{i}", i) for i in range(2)]
        with ThreadPoolExecutor(2) as pool:
            list(pool.map(lib.register_chunk, descriptors))
        lib.record_capture_health("s", health)
        ending(lib)
        lib.finalize_session("s")
    with Library(tmp_path) as lib:
        assert lib.capture_health("s") == health
        assert lib.write_manifest("s")["capture_health"] == health
        assert lib.get_session("s").state == SessionState.FINALIZED


def test_delete_intent_before_files_and_no_resurrection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Library(tmp_path) as lib:
        lib.create_session("s")
        lib.register_chunk(bundle(tmp_path))
        original = catalog.remove_tree

        def locked(path: Path) -> None:
            assert (tmp_path / "deletion-journal/s.json").exists()
            raise PermissionError("injected locked media")

        monkeypatch.setattr(catalog, "remove_tree", locked)
        assert lib.delete_session("s")["state"] == "DELETE_PENDING"
        assert lib.list_sessions() == []
        assert lib.recover_session("s")["adopted"] == 0
        with pytest.raises(StateConflict):
            lib.create_session("s")
        monkeypatch.setattr(catalog, "remove_tree", original)
        assert lib.delete_session("s")["state"] == "DELETED_LOCAL"
        assert lib.recover_session("s")["warnings"] == ["DELETION_INTENT"]
        assert lib.delete_session("missing")["state"] == "NOT_FOUND"
    with Library(tmp_path) as lib:
        assert lib.list_sessions() == []
        assert lib.recover_session("s")["adopted"] == 0


def test_delete_and_recover_do_not_race_live_writer(tmp_path: Path) -> None:
    with Library(tmp_path) as lib:
        lib.create_session("s")
        writer = ChunkWriter(tmp_path, block())
        writer.append(block())
        with pytest.raises(StateConflict):
            lib.recover_session("s")
        assert lib.delete_session("s")["state"] == "DELETE_PENDING"
        assert writer.staging_path.exists()
        writer.abort()
        assert lib.delete_session("s")["deleted"]


def test_corrupt_deletion_history_blocks_auto_recovery(tmp_path: Path) -> None:
    with Library(tmp_path) as lib:
        lib.create_session("s")
        (tmp_path / "deletion-journal/bad.json").write_bytes(b"{")
        with pytest.raises(ValidationError):
            lib.recover_session("s")


def test_future_sqlite_schema_is_not_changed(tmp_path: Path) -> None:
    db = tmp_path / "library.sqlite"
    with closing(sqlite3.connect(db)) as connection, connection:
        connection.execute("PRAGMA user_version=42")
        connection.execute("CREATE TABLE future(value TEXT)")
    before = db.read_bytes()
    with pytest.raises(ValidationError):
        Library(tmp_path)
    assert db.read_bytes() == before


def test_future_manifest_not_overwritten(tmp_path: Path) -> None:
    with Library(tmp_path) as lib:
        lib.create_session("s")
        manifest = tmp_path / "sessions/s/manifest.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_bytes(b'{"schema_version":2}')
        ending(lib)
        assert lib.finalize_session("s")["manifest_sync_pending"]
        assert manifest.read_bytes() == b'{"schema_version":2}'


def test_corrupt_database_not_rebuilt_over(tmp_path: Path) -> None:
    path = tmp_path / "library.sqlite"
    path.write_bytes(b"not a sqlite database")
    with pytest.raises(sqlite3.DatabaseError):
        Library(tmp_path)
    assert path.read_bytes() == b"not a sqlite database"


def test_path_and_hardlink_defenses(tmp_path: Path) -> None:
    descriptor = bundle(tmp_path)
    with pytest.raises(ValidationError):
        replace(descriptor, relative_path="../outside")
    pcm = tmp_path / descriptor.relative_path / "audio.pcm"
    os.link(pcm, tmp_path / "linked.pcm")
    with pytest.raises(ValidationError):
        verify_bundle(tmp_path / descriptor.relative_path)
    for bad in ("../escape", "CON", "a:b", "x/y"):
        with pytest.raises(ValidationError):
            ChunkWriter(tmp_path, block(), bad)


def test_unc_rejected_without_filesystem_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_stat(path: Path) -> None:
        raise AssertionError("Network root must be rejected before lstat")

    monkeypatch.setattr(_safe, "check_path", no_stat)
    with pytest.raises(ValidationError):
        _safe.root_path(Path("//example.invalid/share/library"))


@pytest.mark.skipif(sys.platform != "win32", reason="Windows local drive classification")
@pytest.mark.parametrize("drive_type", [0, 1, 4])
def test_remote_or_unknown_mapped_drive_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, drive_type: int
) -> None:
    import ctypes

    class FakeDriveType:
        def __call__(self, anchor: str) -> int:
            assert anchor.endswith("\\")
            return drive_type

    monkeypatch.setattr(ctypes.windll.kernel32, "GetDriveTypeW", FakeDriveType())
    with pytest.raises(ValidationError):
        Library(tmp_path)


def test_directory_reparse_point_blocks_external_writes(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "library"
    root.mkdir()
    if sys.platform == "win32":
        command = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(root / "sessions"), str(outside)],
            capture_output=True,
            timeout=10,
        )
        assert command.returncode == 0
    else:
        (root / "sessions").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValidationError):
        bundle(root)
    assert list(outside.iterdir()) == []


def test_single_writer_lock_blocks_other_process_and_releases(tmp_path: Path) -> None:
    code = "from pathlib import Path; import sys; from recoryn.storage import Library; Library(Path(sys.argv[1]))"
    with Library(tmp_path):
        result = subprocess.run(
            [sys.executable, "-c", code, str(tmp_path)],
            env=child_env(),
            capture_output=True,
            timeout=10,
        )
        assert result.returncode != 0 and b"StateConflict" in result.stderr
        with pytest.raises(StateConflict):
            Library(tmp_path)
    with Library(tmp_path) as lib:
        assert lib.list_sessions() == []


def test_actual_killed_writer_recovers_fsynced_prefix(tmp_path: Path) -> None:
    code = """
from pathlib import Path
import sys
from recoryn.storage import Library, ChunkWriter
from recoryn.domain import AudioFormat, PCMBlock, SessionState
lib = Library(Path(sys.argv[1]))
lib.create_session('s')
lib.transition('s', SessionState.RECORDING, 0)
b = PCMBlock('s','mic','e',0,AudioFormat(48000,1),2,b'\\x01\\x00'*2,0,0)
w = ChunkWriter(lib.root,b,'crashed')
w.append(b)
print('READY',flush=True)
sys.stdin.read(1)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", code, str(tmp_path)],
        env=child_env(),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == b"READY"
        process.kill()
        process.communicate(timeout=10)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=10)
    with Library(tmp_path) as lib:
        assert lib.recover_session("s")["recovered"] == 1
        descriptors = lib.chunks("s")
        assert len(descriptors) == 1
        assert (
            tmp_path / descriptors[0].relative_path / "audio.pcm"
        ).read_bytes() == b"\x01\x00" * 2
        assert lib.recover_session("s")["recovered"] == 0


def test_sqlite_commit_failure_not_reported_finalized(tmp_path: Path) -> None:
    with Library(tmp_path) as lib:
        lib.create_session("s")
        ending(lib)
        denied = False

        def authorizer(
            action: int, first: str | None, second: str | None, db: str | None, source: str | None
        ) -> int:
            nonlocal denied
            if action == sqlite3.SQLITE_TRANSACTION and first == "COMMIT" and not denied:
                denied = True
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        lib._db.set_authorizer(authorizer)
        with pytest.raises(sqlite3.DatabaseError):
            lib.finalize_session("s")
        lib._db.set_authorizer(None)
        assert lib.get_session("s").state == SessionState.FINALIZING


def test_p11_late_writer_is_fenced_after_delete(tmp_path: Path) -> None:
    with Library(tmp_path) as lib:
        lib.create_session("s")
        writer = ChunkWriter(tmp_path, block(), "delayed")
        assert lib.delete_session("s")["deleted"]
        for action in (
            lambda: writer.append(block()),
            writer.seal,
            lambda: ChunkWriter(tmp_path, block(), "new").append(block()),
        ):
            with pytest.raises(StateConflict):
                action()
        assert not writer.path.exists() and not writer.staging_path.exists()


@pytest.mark.parametrize("deletion_first", [True, False])
def test_p11_open_delete_barrier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, deletion_first: bool
) -> None:
    import threading

    with Library(tmp_path) as lib:
        lib.create_session("s")
        writer = ChunkWriter(tmp_path, block(), "race")
        reached, proceed, deleting = threading.Event(), threading.Event(), threading.Event()
        original = writer._open

        def held_open() -> None:
            reached.set()
            assert proceed.wait(5)
            original()

        def delayed_append() -> None:
            reached.set()
            assert proceed.wait(5)
            writer.append(block())

        def deletion() -> dict[str, Any]:
            deleting.set()
            return lib.delete_session("s")

        with ThreadPoolExecutor(2) as pool:
            if deletion_first:
                future = pool.submit(delayed_append)
                assert reached.wait(5)
                assert lib.delete_session("s")["deleted"]
                proceed.set()
                with pytest.raises(StateConflict):
                    future.result(timeout=5)
            else:
                monkeypatch.setattr(writer, "_open", held_open)
                future = pool.submit(writer.append, block())
                assert reached.wait(5)
                deletion_future = pool.submit(deletion)
                assert deleting.wait(5) and not deletion_future.done()
                proceed.set()
                future.result(timeout=5)
                assert deletion_future.result(timeout=5)["state"] == "DELETE_PENDING"
                with pytest.raises(StateConflict):
                    writer.seal()
                writer.abort()
                assert lib.delete_session("s")["deleted"]
        assert not writer.path.exists() and not writer.staging_path.exists()


@pytest.mark.parametrize("earlier_complete", [False, True])
def test_p11_incomplete_fragment_is_not_normal_bundle(
    tmp_path: Path, earlier_complete: bool
) -> None:
    with Library(tmp_path) as lib:
        lib.create_session("s")
        writer = ChunkWriter(tmp_path, block(), "partial")
        if earlier_complete:
            writer.append(block())
        writer.append(block(1, fragment_count=2))
        with pytest.raises(ValidationError):
            writer.seal()
        writer.abort()
        before = {p.name: p.read_bytes() for p in writer.staging_path.iterdir()}
        first = lib.recover_session("s")
        assert first["recovered"] == int(earlier_complete)
        if earlier_complete:
            assert "STAGING_TAIL_NOT_ADOPTED" in first["warnings"]
            assert lib.chunks("s")[0].frame_count == 2
        else:
            assert first["quarantined"] == 1 and not lib.chunks("s")
        assert lib.recover_session("s")["recovered"] == 0
        assert {p.name: p.read_bytes() for p in writer.staging_path.iterdir()} == before


def test_p11_malformed_and_missing_projection_rebuilt(tmp_path: Path) -> None:
    with Library(tmp_path) as lib:
        lib.create_session("s")
        descriptor = bundle(tmp_path)
        lib.register_chunk(descriptor)
        ending(lib)
        lib.finalize_session("s")
        manifest = tmp_path / "sessions/s/manifest.json"
        manifest.write_bytes(b"{")
        assert "MANIFEST_SYNC_PENDING" not in lib.recover_session("s")["warnings"]
        assert json.loads(manifest.read_bytes())["state"] == "FINALIZED"
        assert next((manifest.parent / "quarantine").glob("manifest-*.json")).read_bytes() == b"{"
        manifest.unlink()
        assert "MANIFEST_SYNC_PENDING" not in lib.recover_session("s")["warnings"]
        assert verify_bundle(tmp_path / descriptor.relative_path) == descriptor


@pytest.mark.parametrize(
    "fault", ["partial_payload", "payload_fsync", "journal_fsync", "descriptor_open"]
)
def test_storage_faults_preserve_verified_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    with Library(tmp_path) as lib:
        lib.create_session("s")
        writer = ChunkWriter(tmp_path, block(), "faulted")
        writer.append(block())
        pcm, journal = writer._pcm, writer._journal
        original_write, original_sync, original_open = (
            chunk_module.write_all,
            chunk_module.sync,
            chunk_module.open_file,
        )

        def failed_write(stream: Any, data: bytes) -> None:
            if stream is pcm:
                stream.write(data[:2])
                raise OSError(errno.ENOSPC, "injected disk full")
            original_write(stream, data)

        def failed_sync(stream: Any) -> None:
            if (fault == "payload_fsync" and stream is pcm) or (
                fault == "journal_fsync" and stream is journal
            ):
                raise OSError("injected fsync failure")
            original_sync(stream)

        def failed_open(path: Path, mode: str) -> Any:
            if path.name == "descriptor.json":
                raise PermissionError("injected descriptor open failure")
            return original_open(path, mode)

        with monkeypatch.context() as patch:
            if fault == "partial_payload":
                patch.setattr(chunk_module, "write_all", failed_write)
            elif fault == "descriptor_open":
                patch.setattr(chunk_module, "open_file", failed_open)
            else:
                patch.setattr(chunk_module, "sync", failed_sync)
            with pytest.raises(OSError):
                writer.seal() if fault == "descriptor_open" else writer.append(block(1))
        saved = {p.name: p.read_bytes() for p in writer.staging_path.iterdir()}
        assert lib.recover_session("s")["recovered"] == 1
        assert lib.chunks("s")[0].frame_count == (4 if fault == "journal_fsync" else 2)
        assert {p.name: p.read_bytes() for p in writer.staging_path.iterdir()} == saved


def test_open_and_close_failures_release_both_handles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    writer = ChunkWriter(tmp_path, block(), "open-failure")
    original = chunk_module.open_file
    opened: list[Any] = []

    def fail_second(path: Path, mode: str) -> Any:
        if path.name == "blocks.jsonl":
            raise PermissionError("injected journal open failure")
        stream = original(path, mode)
        opened.append(stream)
        return stream

    with monkeypatch.context() as patch:
        patch.setattr(chunk_module, "open_file", fail_second)
        with pytest.raises(PermissionError):
            writer.append(block())
    assert opened[0].closed
    assert (writer.staging_path / "audio.pcm").read_bytes() == b""
    writer = ChunkWriter(tmp_path, block(), "close-failure")
    writer.append(block())
    pcm, journal = writer._pcm, writer._journal
    assert pcm is not None and journal is not None

    class BadClose:
        def close(self) -> None:
            pcm.close()
            raise OSError("injected close failure")

    writer._pcm = BadClose()  # type: ignore[assignment]
    with pytest.raises(OSError):
        writer.abort()
    assert pcm.closed and journal.closed
    writer.abort()


@pytest.mark.parametrize(
    "mutations",
    [
        {"schema_version": 2},
        {"schema_version": True},
        {"frame_count": True},
        {"sha256": "bad"},
        {"format": []},
        {"relative_path": 1},
        {"extra": 0},
        {"byte_count": 2},
        {"last_sequence": -1},
        {"block_count": 100_001},
        {"frame_count": 2**30, "byte_count": 2**31},
    ],
)
def test_untrusted_descriptor_boundaries(tmp_path: Path, mutations: dict[str, Any]) -> None:
    value = bundle(tmp_path).to_dict()
    value.update(mutations)
    with pytest.raises(ValidationError):
        ChunkDescriptor.from_dict(value)


@pytest.mark.parametrize(
    "corruption",
    [
        "fields",
        "record_hash",
        "metadata",
        "empty",
        "pcm_tail",
        "descriptor_count",
        "descriptor_identity",
        "location",
        "fragment",
    ],
)
def test_strict_bundle_boundary_errors(tmp_path: Path, corruption: str) -> None:
    descriptor = bundle(tmp_path)
    path = tmp_path / descriptor.relative_path
    record = json.loads((path / "blocks.jsonl").read_bytes())
    if corruption == "fields":
        record["unknown"] = 0
    elif corruption == "record_hash":
        record["record_sha256"] = "0" * 64
    elif corruption == "metadata":
        record["metadata"] = []
    elif corruption == "empty":
        (path / "audio.pcm").write_bytes(b"")
        (path / "blocks.jsonl").write_bytes(b"")
    elif corruption == "pcm_tail":
        with (path / "audio.pcm").open("ab") as stream:
            stream.write(b"tail")
    elif corruption.startswith("descriptor"):
        value = descriptor.to_dict()
        if corruption == "descriptor_count":
            value["block_count"] = 2
        else:
            value["track_id"], value["relative_path"] = "other", "sessions/s/tracks/other/e/chunk"
        (path / "descriptor.json").write_text(json.dumps(value))
    elif corruption == "location":
        moved = path.with_name("moved")
        path.rename(moved)
        path = moved
    else:
        record["metadata"]["fragment_count"] = 2
    if corruption in {"fields", "metadata", "fragment"}:
        (path / "blocks.jsonl").write_bytes(rewrite_record(record))
    elif corruption == "record_hash":
        (path / "blocks.jsonl").write_bytes(json.dumps(record).encode() + b"\n")
    with pytest.raises(ValidationError):
        verify_bundle(path)


@pytest.mark.parametrize(
    "entry", ["missing", "temporary", "directory", "wrong_name", "db_only", "journal_only"]
)
def test_deletion_history_and_single_intent_priority(tmp_path: Path, entry: str) -> None:
    with Library(tmp_path) as lib:
        lib.create_session("s")
        lib.register_chunk(bundle(tmp_path))
        journal = tmp_path / "deletion-journal"
        if entry == "missing":
            journal.rmdir()
        elif entry == "temporary":
            (journal / ".tmp-orphan").write_bytes(b"{")
        elif entry == "directory":
            (journal / "unexpected").mkdir()
        elif entry == "wrong_name":
            (journal / "wrong.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "session_id": "s",
                        "generation": 5,
                        "state": "DELETE_REQUESTED",
                    }
                )
            )
        elif entry == "db_only":
            lib._db.execute("INSERT INTO deleted_sessions VALUES('s',5,'DELETE_PENDING')")
            lib._db.commit()
        else:
            (journal / "s.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "session_id": "s",
                        "generation": 5,
                        "state": "DELETE_REQUESTED",
                    }
                )
            )
        if entry.endswith("only"):
            assert lib.recover_session("s")["adopted"] == 0 and lib.list_sessions() == []
            assert lib.delete_session("s")["deleted"]
        else:
            with pytest.raises(ValidationError):
                lib.recover_session("s")


def test_missing_history_and_unknown_session_recovery(tmp_path: Path) -> None:
    bundle(tmp_path)
    with Library(tmp_path) as lib:
        assert lib.recover_session("s")["adopted"] == 1
        with pytest.raises(KeyError):
            lib.recover_session("missing")
    (tmp_path / "deletion-journal").rmdir()
    with Library(tmp_path) as lib, pytest.raises(ValidationError):
        lib.recover_session("s")


def test_missing_media_is_degraded_and_projection_pending(tmp_path: Path) -> None:
    with Library(tmp_path) as lib:
        lib.create_session("s")
        descriptor = bundle(tmp_path)
        lib.register_chunk(descriptor)
        lib.write_manifest("s")
        (tmp_path / descriptor.relative_path / "audio.pcm").unlink()
        report = lib.recover_session("s")
        assert any(w.startswith("MISSING_OR_INVALID_CATALOG_MEDIA") for w in report["warnings"])
        assert "MANIFEST_SYNC_PENDING" in report["warnings"]
        assert lib._db.execute("SELECT manifest_sync_pending FROM sessions").fetchone()[0] == 1


def test_future_staging_and_finalized_candidate_preserved(tmp_path: Path) -> None:
    with Library(tmp_path) as lib:
        lib.create_session("s")
        writer = ChunkWriter(tmp_path, block(), "future")
        writer.append(block())
        writer.abort()
        (writer.staging_path / "descriptor.json").write_bytes(b'{"schema_version":99}')
        before = (writer.staging_path / "audio.pcm").read_bytes()
        assert lib.recover_session("s")["quarantined"] == 1
        assert (writer.staging_path / "audio.pcm").read_bytes() == before
        ending(lib)
        lib.finalize_session("s")
        assert "FINALIZED_STAGING" in lib.recover_session("s")["warnings"]


def test_library_close_failure_still_releases_os_lock(tmp_path: Path) -> None:
    lib = Library(tmp_path)
    real = lib._connection
    assert real is not None

    class BadClose:
        def close(self) -> None:
            real.close()
            raise OSError("injected sqlite close failure")

    lib._connection = BadClose()  # type: ignore[assignment]
    with pytest.raises(OSError):
        lib.close()
    lib.close()
    with pytest.raises(ValueError):
        lib.list_sessions()
    with Library(tmp_path):
        pass


def test_pending_job_prevents_media_deletion(tmp_path: Path) -> None:
    from recoryn.jobs import JobStore

    with Library(tmp_path) as lib, JobStore(lib.db_path) as jobs:
        lib.create_session("s")
        job = jobs.create("transcribe", "opaque-session-input")
        assert lib.delete_session("s")["state"] == "DELETE_PENDING"
        jobs.cancel(job.job_id)
        assert lib.delete_session("s")["deleted"]


@pytest.mark.parametrize(
    "fault", ["db_only_intent", "future_db", "corrupt_db", "unfinished_intent"]
)
def test_writer_checks_durable_deletion_and_schema_before_open(tmp_path: Path, fault: str) -> None:
    with Library(tmp_path) as lib:
        lib.create_session("s")
        writer = ChunkWriter(tmp_path, block(), "fenced")
        if fault == "db_only_intent":
            lib._db.execute("INSERT INTO deleted_sessions VALUES('s',7,'DELETE_PENDING')")
            lib._db.commit()
        elif fault == "future_db":
            lib._db.execute("PRAGMA user_version=2")
        elif fault == "unfinished_intent":
            (tmp_path / "deletion-journal/.tmp-uncommitted").write_bytes(b"{")
        else:
            lib.close()
            (tmp_path / "library.sqlite").write_bytes(b"invalid sqlite")
        with pytest.raises((ValidationError, StateConflict)):
            writer.append(block())
        assert not writer.staging_path.exists()


@pytest.mark.parametrize("relative", ["../outside", "a\\..\\outside", "/absolute", "safe:stream"])
def test_own_root_rejects_unsafe_join(tmp_path: Path, relative: str) -> None:
    with pytest.raises(ValidationError):
        _safe.safe_path(tmp_path, relative)


def test_short_write_and_failed_atomic_replace_preserve_old_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class NoProgress(io.BytesIO):
        def write(self, data: Any) -> int:
            return 0

    with pytest.raises(OSError):
        _safe.write_all(NoProgress(), b"1234")

    class Partial(io.BytesIO):
        def write(self, data: Any) -> int:
            return super().write(data[:1])

    stream = Partial()
    _safe.write_all(stream, b"1234")
    assert stream.getvalue() == b"1234"
    path = tmp_path / "projection.json"
    path.write_bytes(b'{"schema_version":1,"value":"original"}')

    def denied(source: Any, target: Any) -> None:
        raise PermissionError("injected replace failure")

    monkeypatch.setattr(_safe.os, "replace", denied)
    with pytest.raises(PermissionError):
        _safe.atomic_json(path, {"schema_version": 1, "value": "new"})
    assert json.loads(path.read_bytes())["value"] == "original"
    assert not list(tmp_path.glob(".tmp-*"))
    with pytest.raises(ValidationError):
        _safe.canonical({"payload": b"binary"})
    with pytest.raises(ValidationError):
        _safe.atomic_json(path, {"schema_version": 1, "value": "x" * (8 * 1024 * 1024)})


def test_conflicting_ids_finalized_registration_and_live_finalization(tmp_path: Path) -> None:
    with Library(tmp_path) as lib:
        lib.create_session("s")
        with pytest.raises(StateConflict):
            lib.create_session("s")
        with pytest.raises(StateConflict):
            lib.transition("s", SessionState.FINALIZED, 0)
        first = bundle(tmp_path, "same")
        other = bundle(tmp_path, "same", track="system")
        lib.register_chunk(first)
        with pytest.raises(StateConflict):
            lib.register_chunk(other)
        with pytest.raises(ValidationError):
            lib.register_chunk(replace(first, sha256="0" * 64))
        writer = ChunkWriter(tmp_path, block(1), "active")
        writer.append(block(1))
        ending(lib)
        with pytest.raises(StateConflict):
            lib.finalize_session("s")
        writer.abort()
        lib.finalize_session("s")
        with pytest.raises(StateConflict):
            lib.register_chunk(bundle(tmp_path, "late", 1))


@pytest.mark.parametrize("location", ["track", "epoch"])
def test_recovery_rejects_non_directory_identity_nodes(tmp_path: Path, location: str) -> None:
    with Library(tmp_path) as lib:
        lib.create_session("s")
        tracks = tmp_path / "sessions/s/tracks"
        tracks.mkdir(parents=True)
        if location == "track":
            (tracks / "mic").write_bytes(b"not a directory")
        else:
            (tracks / "mic").mkdir()
            (tracks / "mic/e").write_bytes(b"not a directory")
        with pytest.raises(ValidationError):
            lib.recover_session("s")


def test_bounded_writer_and_first_fragment_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(ValidationError):
        ChunkWriter(tmp_path, block(fragment_index=1, fragment_count=2)).append(
            block(fragment_index=1, fragment_count=2)
        )
    writer = ChunkWriter(tmp_path, block(), "bounded")
    with monkeypatch.context() as patch:
        patch.setattr(chunk_module, "MAX_BLOCK_BYTES", 2)
        with pytest.raises(ValidationError):
            writer.append(block())
    assert not writer.staging_path.exists()
    huge = block(flags=tuple(f"FLAG{i}_" + "a" * 100 for i in range(1000)))
    oversized = ChunkWriter(tmp_path, huge, "oversized-metadata")
    try:
        with pytest.raises(ValidationError):
            oversized.append(huge)
    finally:
        oversized.abort()
