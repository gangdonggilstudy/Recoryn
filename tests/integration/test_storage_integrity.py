"""Real SQLite/filesystem checks using distinguishable independent PCM samples."""

import hashlib
import json
from pathlib import Path

import pytest

import recoryn.storage.library as storage_library
from recoryn.domain import AudioFormat, PCMBlock, SessionState
from recoryn.storage import ChunkWriter, Library, verify_bundle

pytestmark = pytest.mark.integration


def known_block(sequence: int = 0, epoch: str = "epoch1") -> PCMBlock:
    return PCMBlock(
        session_id="integrity",
        track_id="mic",
        epoch_id=epoch,
        sequence=sequence,
        format=AudioFormat(48000, 1),
        frame_count=3,
        payload=bytes((sequence + index) % 256 for index in range(6)),
        capture_mono_ns=sequence * 62500,
        arrival_mono_ns=sequence * 62500,
        device_frame_position=sequence * 3,
    )


def create_bundle(root: Path) -> Path:
    with Library(root) as library:
        library.create_session("integrity")
        writer = ChunkWriter(root, known_block(), chunk_id="known")
        writer.append(known_block())
        writer.append(known_block(1))
        descriptor = writer.seal()
        library.register_chunk(descriptor)
        return root / descriptor.relative_path


def test_constructor_does_not_implicitly_append_first_block(tmp_path: Path) -> None:
    bundle = create_bundle(tmp_path)
    descriptor = verify_bundle(bundle)
    assert descriptor.frame_count == 6
    assert descriptor.byte_count == 12
    assert (bundle / "audio.pcm").read_bytes() == bytes(range(6)) + bytes(range(1, 7))


@pytest.mark.parametrize(
    "corruption",
    (
        "duplicate",
        "partial",
        "payload",
        "offset",
        "epoch",
        "sequence",
        "frame_count",
        "record_hash",
    ),
)
def test_sealed_bundle_rejects_journal_and_payload_corruption(
    tmp_path: Path, corruption: str
) -> None:
    bundle = create_bundle(tmp_path)
    journal = bundle / "blocks.jsonl"
    lines = journal.read_bytes().splitlines(keepends=True)
    assert len(lines) >= 2
    if corruption == "duplicate":
        journal.write_bytes(lines[0] + lines[0] + b"".join(lines[1:]))
    elif corruption == "partial":
        journal.write_bytes(b"".join(lines) + b'{"incomplete":')
    elif corruption == "payload":
        pcm = bundle / "audio.pcm"
        content = pcm.read_bytes()
        pcm.write_bytes(bytes([content[0] ^ 1]) + content[1:])
    else:
        record = json.loads(lines[1])
        if corruption == "offset":
            record["offset"] = 0
        elif corruption == "epoch":
            record["metadata"]["epoch_id"] = "epoch2"
        elif corruption == "sequence":
            record["metadata"]["sequence"] = 0
        elif corruption == "frame_count":
            record["metadata"]["frame_count"] = 4
        unsigned = {key: value for key, value in record.items() if key != "record_sha256"}
        encoded = json.dumps(
            unsigned, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        record["record_sha256"] = (
            "0" * 64 if corruption == "record_hash" else hashlib.sha256(encoded).hexdigest()
        )
        # Semantic corruptions carry a valid fresh checksum: identity/range/order
        # validation, not merely checksum failure, must reject them.
        journal.write_bytes(
            lines[0]
            + json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
            + b"\n"
            + b"".join(lines[2:])
        )
    with pytest.raises((ValueError, OSError)):
        verify_bundle(bundle)


def test_append_rejects_other_epoch_and_preserves_accepted_pcm(tmp_path: Path) -> None:
    with Library(tmp_path) as library:
        library.create_session("integrity")
        writer = ChunkWriter(tmp_path, known_block(), chunk_id="known")
        writer.append(known_block())
        with pytest.raises(ValueError):
            writer.append(known_block(1, epoch="epoch2"))
        descriptor = writer.seal()
        assert descriptor.frame_count == 3
        assert (tmp_path / descriptor.relative_path / "audio.pcm").read_bytes() == bytes(range(6))


def test_finalize_recovery_never_mutates_original(tmp_path: Path) -> None:
    bundle = create_bundle(tmp_path)
    before = {
        path.relative_to(tmp_path): hashlib.sha256(path.read_bytes()).digest()
        for path in bundle.iterdir()
        if path.is_file()
    }
    with Library(tmp_path) as library:
        session = library.get_session("integrity")
        session = library.transition("integrity", SessionState.RECORDING, session.state_version)
        library.transition("integrity", SessionState.FINALIZING, session.state_version)
        result = library.finalize_session("integrity")
        assert result["frame_count"] == 6
        assert result["chunk_count"] == 1
        assert library.get_session("integrity").state is SessionState.FINALIZED
        for _ in range(2):
            library.recover_session("integrity")
            assert library.get_session("integrity").state is SessionState.FINALIZED
            assert len(library.chunks("integrity")) == 1
    for relative_path, digest in before.items():
        assert hashlib.sha256((tmp_path / relative_path).read_bytes()).digest() == digest


def test_deleted_media_cannot_be_resurrected_from_a_stale_bundle(tmp_path: Path) -> None:
    bundle = create_bundle(tmp_path)
    stale_copy = {
        path.relative_to(tmp_path): path.read_bytes() for path in bundle.iterdir() if path.is_file()
    }
    with Library(tmp_path) as library:
        library.delete_session("integrity")
    for relative_path, content in stale_copy.items():
        restored = tmp_path / relative_path
        restored.parent.mkdir(parents=True, exist_ok=True)
        restored.write_bytes(content)
    with Library(tmp_path) as library:
        for _ in range(2):
            report = library.recover_session("integrity")
            assert report["adopted"] == 0
            assert report["recovered"] == 0
            assert all(session.session_id != "integrity" for session in library.list_sessions())


@pytest.mark.parametrize("tail", ("torn_record", "unrecorded_payload", "duplicate_record"))
def test_recovery_uses_only_verified_prefix_without_changing_staging(
    tmp_path: Path, tail: str
) -> None:
    with Library(tmp_path) as library:
        library.create_session("integrity")
        writer = ChunkWriter(tmp_path, known_block(), chunk_id="prefix")
        writer.append(known_block())
        writer.abort()
        journals = list(tmp_path.rglob("blocks.jsonl"))
        assert len(journals) == 1
        journal = journals[0]
        pcm = journal.with_name("audio.pcm")
        if tail == "torn_record":
            with journal.open("ab") as stream:
                stream.write(b'{"torn":')
        elif tail == "unrecorded_payload":
            with pcm.open("ab") as stream:
                stream.write(b"\xff\xff\xff")
        else:
            content = journal.read_bytes()
            journal.write_bytes(content + content)
        before = {journal: journal.read_bytes(), pcm: pcm.read_bytes()}
        for _ in range(2):
            library.recover_session("integrity")
            chunks = library.chunks("integrity")
            assert len(chunks) == 1
            assert chunks[0].frame_count == 3
            assert (tmp_path / chunks[0].relative_path / "audio.pcm").read_bytes() == bytes(
                range(6)
            )
            assert all(path.read_bytes() == content for path, content in before.items())


def test_manifest_only_failure_keeps_finalized_media(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = create_bundle(tmp_path)
    before = (bundle / "audio.pcm").read_bytes()
    with Library(tmp_path) as library:
        session = library.get_session("integrity")
        library.transition("integrity", SessionState.FINALIZING, session.state_version)
        original_write = library.write_manifest

        def fail_projection(session_id: str) -> dict[str, object]:
            raise OSError("P04 manifest-only failure")

        monkeypatch.setattr(library, "write_manifest", fail_projection)
        result = library.finalize_session("integrity")
        assert result["manifest_sync_pending"] is True
        assert library.get_session("integrity").state is SessionState.FINALIZED
        assert (bundle / "audio.pcm").read_bytes() == before
        monkeypatch.setattr(library, "write_manifest", original_write)
        assert library.finalize_session("integrity")["manifest_sync_pending"] is False


def test_journal_only_deletion_intent_blocks_recovery_and_can_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_bundle(tmp_path)
    original_replace = storage_library.os.replace

    def fail_after_intent(source: Path, target: Path) -> None:
        original_replace(source, target)
        if Path(target) == tmp_path / "deletion-journal" / "integrity.json":
            raise OSError("P04 injected failure after journal publication")

    with Library(tmp_path) as library:
        with monkeypatch.context() as patch:
            patch.setattr(storage_library.os, "replace", fail_after_intent)
            with pytest.raises(OSError):
                library.delete_session("integrity")
    with Library(tmp_path) as restarted:
        report = restarted.recover_session("integrity")
        assert report["adopted"] == report["recovered"] == 0
        assert restarted.list_sessions() == []
        assert restarted.delete_session("integrity")["deleted"] is True
        assert restarted.recover_session("integrity")["recovered"] == 0


def test_corrupt_deletion_history_fails_closed(tmp_path: Path) -> None:
    bundle = create_bundle(tmp_path)
    stale = {path.relative_to(tmp_path): path.read_bytes() for path in bundle.iterdir()}
    with Library(tmp_path) as library:
        library.delete_session("integrity")
    for relative_path, content in stale.items():
        restored = tmp_path / relative_path
        restored.parent.mkdir(parents=True, exist_ok=True)
        restored.write_bytes(content)
    (tmp_path / "deletion-journal" / "integrity.json").write_bytes(b'{"torn":')
    with Library(tmp_path) as restarted:
        with pytest.raises(ValueError):
            restarted.recover_session("integrity")
    assert all((tmp_path / path).read_bytes() == content for path, content in stale.items())


def test_overlapping_chunk_sequence_is_rejected_without_mutating_original(tmp_path: Path) -> None:
    original = create_bundle(tmp_path)
    before = (original / "audio.pcm").read_bytes()
    with Library(tmp_path) as library:
        duplicate = known_block(1)
        writer = ChunkWriter(tmp_path, duplicate, chunk_id="overlap")
        writer.append(duplicate)
        descriptor = writer.seal()
        with pytest.raises(ValueError):
            library.register_chunk(descriptor)
        library.recover_session("integrity")
        assert len(library.chunks("integrity")) == 1
        assert (original / "audio.pcm").read_bytes() == before


def test_finalized_orphan_cannot_change_the_sealed_original_list(tmp_path: Path) -> None:
    create_bundle(tmp_path)
    with Library(tmp_path) as library:
        session = library.get_session("integrity")
        library.transition("integrity", SessionState.FINALIZING, session.state_version)
        library.finalize_session("integrity")
        before = [chunk.to_dict() for chunk in library.chunks("integrity")]
        block = known_block(2)
        writer = ChunkWriter(tmp_path, block, chunk_id="late-orphan")
        writer.append(block)
        writer.seal()
        for _ in range(2):
            report = library.recover_session("integrity")
            assert report["quarantined"] >= 1
            assert [chunk.to_dict() for chunk in library.chunks("integrity")] == before
            assert library.get_session("integrity").state is SessionState.FINALIZED


def test_malformed_manifest_is_rebuilt_from_verified_db_and_media(tmp_path: Path) -> None:
    bundle = create_bundle(tmp_path)
    before = (bundle / "audio.pcm").read_bytes()
    with Library(tmp_path) as library:
        session = library.get_session("integrity")
        library.transition("integrity", SessionState.FINALIZING, session.state_version)
        library.finalize_session("integrity")
        manifest = tmp_path / "sessions" / "integrity" / "manifest.json"
        manifest.write_bytes(b"{")
        for _ in range(2):
            report = library.recover_session("integrity")
            assert "MANIFEST_SYNC_PENDING" not in report["warnings"]
            projection = json.loads(manifest.read_text(encoding="utf-8"))
            assert projection["frame_count"] == 6
            assert projection["state"] == "FINALIZED"
            assert (bundle / "audio.pcm").read_bytes() == before


def test_delayed_writer_cannot_recreate_media_after_successful_delete(tmp_path: Path) -> None:
    with Library(tmp_path) as library:
        library.create_session("integrity")
        writer = ChunkWriter(tmp_path, known_block(), chunk_id="delayed")
        try:
            deleted = library.delete_session("integrity")
            if not deleted["deleted"]:
                writer.abort()
                deleted = library.delete_session("integrity")
            assert deleted["deleted"] is True
            with pytest.raises(ValueError):
                writer.append(known_block())
            assert not list((tmp_path / "sessions").rglob("audio.pcm"))
        finally:
            writer.abort()
