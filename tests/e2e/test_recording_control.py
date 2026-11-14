"""Barrier-driven checks of application cutoff and persistence semantics."""

from __future__ import annotations

import threading
from dataclasses import replace
from pathlib import Path

import pytest

from recoryn.app import RecordingError, RecordingService
from recoryn.capture import BoundedCaptureQueue
from recoryn.domain import AudioFormat, PCMBlock, SessionState, ValidationError
from recoryn.storage import ChunkWriter, Library

pytestmark = pytest.mark.integration


def block(service: RecordingService, sequence: int = 0) -> PCMBlock:
    return PCMBlock(
        service.session_id,
        "mic",
        service.epochs["mic"],
        sequence,
        AudioFormat(48000, 1),
        480,
        b"\x01\x00" * 480,
        sequence * 10_000_000,
        sequence * 10_000_000,
    )


def test_pause_is_acknowledged_after_drain_and_resume_uses_new_epoch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered, release, closed, paused = (threading.Event() for _ in range(4))
    original_append, original_close = ChunkWriter.append, BoundedCaptureQueue.close
    failures: list[BaseException] = []

    def slow_append(writer: ChunkWriter, pcm: PCMBlock) -> None:
        entered.set()
        assert release.wait(5)
        original_append(writer, pcm)

    def observe_close(pending: BoundedCaptureQueue) -> None:
        original_close(pending)
        closed.set()

    monkeypatch.setattr(ChunkWriter, "append", slow_append)
    monkeypatch.setattr(BoundedCaptureQueue, "close", observe_close)
    with Library(tmp_path / "library") as library:
        service = RecordingService(library, {"mic": AudioFormat(48000, 1)}, max_blocks=1)
        service.start()
        original = block(service)
        assert service.submit(original)
        assert entered.wait(5)
        assert service.submit(replace(original, sequence=1))
        assert not service.submit(replace(original, sequence=2))

        def pause() -> None:
            try:
                service.pause(timeout=None)
                paused.set()
            except BaseException as error:
                failures.append(error)

        control = threading.Thread(target=pause)
        control.start()
        try:
            assert closed.wait(5)
            assert not paused.is_set()
            assert not service.submit(replace(original, sequence=3))
        finally:
            release.set()
            control.join(5)
            service.join_writer()
        assert not control.is_alive()
        assert not failures
        assert paused.is_set()
        assert library.get_session(service.session_id).state == SessionState.PAUSED
        health = library.capture_health(service.session_id)
        first = health["epochs"][0]["tracks"]["mic"]
        assert first["accepted_frames"] == 960
        assert first["dropped_frames"] == 480
        assert first["gaps"][0]["frame_count"] == 480
        service.resume()
        assert service.epochs["mic"] != original.epoch_id
        with pytest.raises(ValidationError):
            service.submit(original)
        assert service.submit(block(service))
        service.stop()
        assert sum(item.frame_count for item in library.chunks(service.session_id)) == 1440
        assert len({item.epoch_id for item in library.chunks(service.session_id)}) == 2


def test_storage_failure_is_not_reported_as_finalized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_append(writer: ChunkWriter, pcm: PCMBlock) -> None:
        raise OSError("a private diagnostic must not be copied into a CLI message")

    monkeypatch.setattr(ChunkWriter, "append", fail_append)
    with Library(tmp_path / "library") as library:
        service = RecordingService(library, {"mic": AudioFormat(48000, 1)})
        service.start()
        assert service.submit(block(service))
        with pytest.raises(RecordingError, match="STORAGE_FAILED"):
            service.stop()
        service.join_writer()
        assert library.get_session(service.session_id).state == SessionState.INTERRUPTED
        assert not service.submit(block(service, 1))


def test_pause_timeout_keeps_gate_closed_until_actual_writer_ack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered, release = threading.Event(), threading.Event()
    original_append = ChunkWriter.append

    def stalled_append(writer: ChunkWriter, pcm: PCMBlock) -> None:
        entered.set()
        assert release.wait(5)
        original_append(writer, pcm)

    monkeypatch.setattr(ChunkWriter, "append", stalled_append)
    with Library(tmp_path / "library") as library:
        service = RecordingService(library, {"mic": AudioFormat(48000, 1)})
        try:
            service.start()
            assert service.submit(block(service))
            assert entered.wait(5)
            with pytest.raises(RecordingError, match="WRITER_ACK_PENDING"):
                service.pause(timeout=0)
            assert service.worker_alive
            assert library.get_session(service.session_id).state == SessionState.RECORDING
            assert not service.submit(block(service, 1))
            with pytest.raises(RecordingError, match="RESUME_REQUIRES_PAUSED"):
                service.resume()
            release.set()
            service.pause()
            assert library.get_session(service.session_id).state == SessionState.PAUSED
            assert service.stop()["frame_count"] == 480
        finally:
            release.set()
            service.join_writer()


def test_rotation_failure_releases_writer_for_prefix_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_seal = ChunkWriter.seal

    def fail_seal(writer: ChunkWriter) -> None:
        raise OSError("injected failure at rotation before descriptor publication")

    with Library(tmp_path / "library") as library:
        service = RecordingService(library, {"mic": AudioFormat(48000, 1)}, chunk_frames=1)
        service.start()
        monkeypatch.setattr(ChunkWriter, "seal", fail_seal)
        assert service.submit(block(service))
        with pytest.raises(RecordingError, match="STORAGE_FAILED"):
            service.stop()
        service.join_writer()
        monkeypatch.setattr(ChunkWriter, "seal", original_seal)
        recovered = library.recover_session(service.session_id)
        assert recovered["recovered"] == 1
        assert sum(item.frame_count for item in library.chunks(service.session_id)) == 480


def test_empty_session_and_idempotent_stop_keep_finalized_state(tmp_path: Path) -> None:
    with Library(tmp_path / "library") as library:
        with pytest.raises(ValidationError):
            RecordingService(library, {})
        assert library.list_sessions() == []
        service = RecordingService(library, {"mic": AudioFormat(48000, 1)})
        with pytest.raises(RecordingError, match="PAUSE_REQUIRES_RECORDING"):
            service.pause()
        assert service.stop()["frame_count"] == 0
        assert service.stop()["frame_count"] == 0
        with pytest.raises(RecordingError, match="START_REQUIRES_CREATED"):
            service.start()


def test_rotation_does_not_split_a_fragmented_packet(tmp_path: Path) -> None:
    with Library(tmp_path / "library") as library:
        service = RecordingService(library, {"mic": AudioFormat(48000, 1)}, chunk_frames=1)
        service.start()
        first = replace(block(service), fragment_count=2)
        second = replace(first, fragment_index=1)
        try:
            assert service.submit(first)
            assert service.submit(second)
            service.stop()
            chunks = library.chunks(service.session_id)
            assert len(chunks) == 1
            assert chunks[0].frame_count == 960
        finally:
            service.join_writer()


def test_export_splits_a_source_gap_inside_one_chunk(tmp_path: Path) -> None:
    import json
    import wave

    from recoryn.cli import main

    root = tmp_path / "library"
    with Library(root) as library:
        service = RecordingService(library, {"mic": AudioFormat(48000, 1)})
        service.start()
        assert service.submit(block(service, 0))
        assert service.submit(block(service, 2))
        service.stop()
        assert len(library.chunks(service.session_id)) == 1
    output = tmp_path / "output"
    assert main(["--root", str(root), "export", service.session_id, "--output", str(output)]) == 0
    manifest = json.loads((output / "export.json").read_text(encoding="utf-8"))
    assert len(manifest["files"]) == 2
    assert manifest["files"][1]["gap_before"] == "SEQUENCE_GAP"
    for file in manifest["files"]:
        with wave.open(str(output / file["file"]), "rb") as audio:
            assert audio.getnframes() == 480
