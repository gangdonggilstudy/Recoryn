"""Independent application-level recording, cutoff, failure, and export checks."""

import json
import wave
from pathlib import Path
from threading import Event

import pytest

from recoryn.app import RecordingService
from recoryn.app.recording import RecordingError
from recoryn.cli import main
from recoryn.domain import AudioFormat, PCMBlock, SessionState, ValidationError
from recoryn.jobs import JobState, JobStore
from recoryn.storage import ChunkWriter, Library

pytestmark = pytest.mark.integration


def block_for(service: RecordingService, sequence: int, track: str = "mic") -> PCMBlock:
    audio_format = service.formats[track]
    return PCMBlock(
        session_id=service.session_id,
        track_id=track,
        epoch_id=service.epochs[track],
        sequence=sequence,
        format=audio_format,
        frame_count=3,
        payload=bytes([sequence + 1]) * (audio_format.frame_bytes * 3),
        capture_mono_ns=sequence * 100000,
        arrival_mono_ns=sequence * 100000,
        device_frame_position=sequence * 3,
    )


def test_pause_resume_preserves_separate_track_epochs_and_privacy(tmp_path: Path) -> None:
    with Library(tmp_path) as library:
        service = RecordingService(
            library, {"mic": AudioFormat(44100, 1), "system": AudioFormat(48000, 2)}
        )
        expected: dict[tuple[str, str], bytes] = {}
        try:
            service.start()
            old_epochs = service.epochs
            old = block_for(service, 0)
            for track in service.formats:
                block = block_for(service, 0, track)
                assert service.submit(block)
                expected[(track, block.epoch_id)] = block.payload
            service.pause()
            assert library.get_session(service.session_id).state is SessionState.PAUSED
            assert not service.worker_alive
            assert not service.submit(old)
            service.resume()
            assert all(service.epochs[track] != old_epochs[track] for track in old_epochs)
            with pytest.raises(ValidationError):
                service.submit(old)
            for track in service.formats:
                block = block_for(service, 1, track)
                assert service.submit(block)
                expected[(track, block.epoch_id)] = block.payload
            stopped = service.stop()
            assert stopped["frame_count"] == 12
            assert not service.submit(block_for(service, 2))
            assert not service.worker_alive
            chunks = library.chunks(service.session_id)
            assert len(chunks) == 4
            for chunk in chunks:
                assert (tmp_path / chunk.relative_path / "audio.pcm").read_bytes() == expected[
                    (chunk.track_id, chunk.epoch_id)
                ]
            health = library.capture_health(service.session_id)
            assert len(health["epochs"]) == 2
            assert sum(epoch["queue"]["dropped_frames"] for epoch in health["epochs"]) == 0
            manifest = library.write_manifest(service.session_id)
            assert manifest["capture_health"] == health
        finally:
            service.join_writer()


def test_full_queue_close_preserves_last_drop_and_cutoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered, release = Event(), Event()
    original_append = ChunkWriter.append

    def held_append(writer: ChunkWriter, block: PCMBlock) -> None:
        if block.sequence == 0:
            entered.set()
            if not release.wait(10):
                raise RuntimeError("P04 synchronization timeout")
        original_append(writer, block)

    monkeypatch.setattr(ChunkWriter, "append", held_append)
    with Library(tmp_path) as library:
        service = RecordingService(library, {"mic": AudioFormat(48000, 1)}, max_blocks=1)
        try:
            service.start()
            assert service.submit(block_for(service, 0))
            assert entered.wait(5)
            assert service.submit(block_for(service, 1))
            assert not service.submit(block_for(service, 2))
            assert not service.submit(block_for(service, 3))
            with pytest.raises(RecordingError, match="WRITER_ACK_PENDING"):
                service.pause(timeout=0.01)
            assert library.get_session(service.session_id).state is SessionState.RECORDING
            assert not service.submit(block_for(service, 4))
            with pytest.raises(RecordingError):
                service.resume()
            release.set()
            service.join_writer()
            result = service.stop()
            assert result["frame_count"] == 6
            epoch = library.capture_health(service.session_id)["epochs"][0]
            assert epoch["queue"]["accepted_frames"] == 6
            assert epoch["queue"]["dropped_frames"] == 6
            track = epoch["tracks"]["mic"]
            assert track["last_accepted_sequence"] == 1
            assert track["dropped_frames"] == 6
            assert sum(gap["frame_count"] for gap in track["gaps"]) == 6
            assert (
                b"".join(
                    (tmp_path / chunk.relative_path / "audio.pcm").read_bytes()
                    for chunk in library.chunks(service.session_id)
                )
                == b"\x01" * 6 + b"\x02" * 6
            )
        finally:
            release.set()
            service.join_writer()


def test_storage_failure_interrupts_without_claiming_finalized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_append(writer: ChunkWriter, block: PCMBlock) -> None:
        raise OSError("P04 injected storage failure")

    monkeypatch.setattr(ChunkWriter, "append", fail_append)
    with Library(tmp_path) as library:
        service = RecordingService(library, {"mic": AudioFormat(48000, 1)})
        try:
            service.start()
            service.submit(block_for(service, 0))
            with pytest.raises(RecordingError, match="STORAGE_FAILED"):
                service.stop()
            assert library.get_session(service.session_id).state is SessionState.INTERRUPTED
            assert not service.worker_alive
        finally:
            service.join_writer()


def test_capture_health_write_failure_cannot_leave_recording_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_health(session_id: str, health: dict[str, object]) -> None:
        raise OSError("P04 injected health persistence failure")

    with Library(tmp_path) as library:
        service = RecordingService(library, {"mic": AudioFormat(48000, 1)})
        try:
            service.start()
            assert service.submit(block_for(service, 0))
            monkeypatch.setattr(library, "record_capture_health", fail_health)
            with pytest.raises((RecordingError, OSError)):
                service.stop()
            assert not service.worker_alive
            assert library.get_session(service.session_id).state is SessionState.INTERRUPTED
        finally:
            service.join_writer()


def test_failed_start_does_not_leak_a_live_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Library(tmp_path) as library:
        service = RecordingService(library, {"mic": AudioFormat(48000, 1)})

        def fail_transition(session_id: str, target: SessionState, expected_version: int) -> None:
            raise OSError("P04 injected start transition failure")

        monkeypatch.setattr(library, "transition", fail_transition)
        try:
            with pytest.raises((RecordingError, OSError)):
                service.start()
            assert not service.worker_alive
        finally:
            service.join_writer()


def test_job_failure_and_cancel_do_not_end_recording(tmp_path: Path) -> None:
    with Library(tmp_path) as library:
        service = RecordingService(library, {"mic": AudioFormat(48000, 1)})
        try:
            service.start()
            assert service.submit(block_for(service, 0))
            with JobStore(tmp_path / "library.sqlite") as jobs:
                job = jobs.create("transcribe", "p04-ai-input")
                attempt = jobs.claim(job.job_id, "failing-worker")
                jobs.fail(job.job_id, attempt.attempt_id, attempt.fence, "OOM")
                assert jobs.get(job.job_id).state is JobState.FAILED
                cancelled = jobs.create("summarize", "p04-summary-input")
                jobs.cancel(cancelled.job_id)
            assert library.get_session(service.session_id).state is SessionState.RECORDING
            assert service.submit(block_for(service, 1))
            assert service.stop()["frame_count"] == 6
        finally:
            service.join_writer()


def test_cli_export_samples_no_overwrite_and_original_invariance(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, output = tmp_path / "library", tmp_path / "export"
    with Library(root) as library:
        service = RecordingService(
            library, {"mic": AudioFormat(44100, 1), "system": AudioFormat(48000, 2)}
        )
        try:
            service.start()
            expected: dict[str, bytes] = {}
            for track in service.formats:
                block = block_for(service, 0, track)
                expected[track] = block.payload
                assert service.submit(block)
            service.stop()
            originals = {
                root / chunk.relative_path / "audio.pcm": (
                    root / chunk.relative_path / "audio.pcm"
                ).read_bytes()
                for chunk in library.chunks(service.session_id)
            }
        finally:
            service.join_writer()
    arguments = ["--root", str(root), "export", service.session_id, "--output", str(output)]
    assert main(arguments) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["complete"] is True
    for item in result["files"]:
        with wave.open(str(output / item["file"]), "rb") as audio:
            assert audio.getnframes() == 3
            assert audio.readframes(4) == expected[item["track_id"]]
            assert audio.getsampwidth() == 2
            assert audio.getframerate() == (44100 if item["track_id"] == "mic" else 48000)
            assert audio.getnchannels() == (1 if item["track_id"] == "mic" else 2)
    before = {path: path.read_bytes() for path in output.iterdir()}
    assert main(arguments) == 1
    capsys.readouterr()
    assert all(path.read_bytes() == content for path, content in before.items())
    assert all(path.read_bytes() == content for path, content in originals.items())
    assert (
        main(
            ["--root", str(root), "export", service.session_id, "--output", str(root / "forbidden")]
        )
        == 1
    )
    assert not (root / "forbidden").exists()


def test_cli_export_orders_audio_by_sequence_not_random_chunk_id(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, output = tmp_path / "library", tmp_path / "export"
    with Library(root) as library:
        session = library.create_session("ordered")
        session = library.transition("ordered", SessionState.RECORDING, session.state_version)
        for sequence, chunk_id in enumerate(("z-first", "a-second")):
            block = PCMBlock(
                "ordered",
                "mic",
                "epoch1",
                sequence,
                AudioFormat(48000, 1),
                3,
                bytes([sequence + 1]) * 6,
                sequence * 62500,
                sequence * 62500,
                device_frame_position=sequence * 3,
            )
            writer = ChunkWriter(root, block, chunk_id=chunk_id)
            writer.append(block)
            library.register_chunk(writer.seal())
        library.transition("ordered", SessionState.FINALIZING, session.state_version)
        library.finalize_session("ordered")
    assert main(["--root", str(root), "export", "ordered", "--output", str(output)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert len(result["files"]) == 1
    with wave.open(str(output / result["files"][0]["file"]), "rb") as audio:
        assert audio.readframes(7) == b"\x01" * 6 + b"\x02" * 6


def test_rotation_waits_for_the_complete_fragment_group(tmp_path: Path) -> None:
    with Library(tmp_path) as library:
        service = RecordingService(library, {"mic": AudioFormat(48000, 1)}, chunk_frames=1)
        try:
            service.start()
            for fragment in range(3):
                block = PCMBlock(
                    service.session_id,
                    "mic",
                    service.epochs["mic"],
                    0,
                    AudioFormat(48000, 1),
                    2,
                    bytes([fragment + 1]) * 4,
                    fragment * 41666,
                    fragment * 41666,
                    device_frame_position=fragment * 2,
                    fragment_index=fragment,
                    fragment_count=3,
                )
                assert service.submit(block)
            assert service.stop()["frame_count"] == 6
            chunks = library.chunks(service.session_id)
            assert len(chunks) == 1
            assert (tmp_path / chunks[0].relative_path / "audio.pcm").read_bytes() == (
                b"\x01" * 4 + b"\x02" * 4 + b"\x03" * 4
            )
        finally:
            service.join_writer()


def test_threshold_seal_failure_releases_writer_and_preserves_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_seal(writer: ChunkWriter) -> None:
        raise OSError("P04 injected threshold seal failure")

    with Library(tmp_path) as library:
        service = RecordingService(library, {"mic": AudioFormat(48000, 1)}, chunk_frames=3)
        try:
            service.start()
            with monkeypatch.context() as patch:
                patch.setattr(ChunkWriter, "seal", fail_seal)
                assert service.submit(block_for(service, 0))
                with pytest.raises(RecordingError, match="STORAGE_FAILED"):
                    service.stop()
            assert not service.worker_alive
            assert library.get_session(service.session_id).state is SessionState.INTERRUPTED
            library.recover_session(service.session_id)
            chunks = library.chunks(service.session_id)
            assert sum(chunk.frame_count for chunk in chunks) == 3
            assert (tmp_path / chunks[0].relative_path / "audio.pcm").read_bytes() == b"\x01" * 6
        finally:
            service.join_writer()


@pytest.mark.parametrize("gap", ("none", "sequence", "position", "flag"))
def test_export_preserves_source_gap_and_independent_frame_mapping(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], gap: str
) -> None:
    root, output = tmp_path / "library", tmp_path / "mapped-export"
    first_payload, second_payload = b"\x11\x00\x12\x00", b"\x21\x00\x22\x00"
    second_sequence = 2 if gap == "sequence" else 1
    second_position = 9 if gap == "position" else 2
    second_time = 10_000_000 + second_position * 62_500
    first = PCMBlock(
        "mapped",
        "mic",
        "epoch1",
        0,
        AudioFormat(16000, 1),
        2,
        first_payload,
        10_000_000,
        10_000_000,
        device_frame_position=0,
    )
    second = PCMBlock(
        "mapped",
        "mic",
        "epoch1",
        second_sequence,
        AudioFormat(16000, 1),
        2,
        second_payload,
        second_time,
        second_time,
        device_frame_position=second_position,
        flags=("DATA_DISCONTINUITY",) if gap == "flag" else (),
    )
    with Library(root) as library:
        session = library.create_session("mapped")
        library.transition("mapped", SessionState.FINALIZING, session.state_version)
        writer = ChunkWriter(root, first, chunk_id="mappedchunk")
        writer.append(first)
        writer.append(second)
        descriptor = writer.seal()
        library.register_chunk(descriptor)
        library.finalize_session("mapped")
        original_path = root / descriptor.relative_path / "audio.pcm"
    assert main(["--root", str(root), "export", "mapped", "--output", str(output)]) == 0
    result = json.loads(capsys.readouterr().out)
    entries = result["files"]
    assert len(entries) == (1 if gap == "none" else 2)
    if gap != "none":
        assert (
            entries[1]["gap_before"]
            == {
                "sequence": "SEQUENCE_GAP",
                "position": "DEVICE_POSITION_GAP",
                "flag": "BACKEND_DISCONTINUITY",
            }[gap]
        )
    mappings = [span for entry in entries for span in entry["source_ranges"]]
    assert [span["source_chunk_frame_start"] for span in mappings] == [0, 2]
    assert [span["output_frame_start"] for span in mappings] == [0, 2 if gap == "none" else 0]
    assert [span["capture_mono_ns"] for span in mappings] == [10_000_000, second_time]
    assert [span["sequence"] for span in mappings] == [0, second_sequence]
    assert [span["frame_count"] for span in mappings] == [2, 2]
    assert all(span["chunk_id"] == "mappedchunk" for span in mappings)
    payloads = []
    for entry in entries:
        with wave.open(str(output / entry["file"]), "rb") as audio:
            assert audio.getnframes() == entry["frame_count"]
            payloads.append(audio.readframes(5))
    assert b"".join(payloads) == first_payload + second_payload
    assert original_path.read_bytes() == first_payload + second_payload
