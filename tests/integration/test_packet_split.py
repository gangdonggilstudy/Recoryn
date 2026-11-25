"""GS06 actual queue/service/storage histories, no real devices or audio."""

from __future__ import annotations

import json
import threading
import wave
from contextlib import contextmanager
from dataclasses import replace
from itertools import product

import pytest

from recoryn.app import desktop as desktop_module
from recoryn.app.desktop import DesktopRecorder, TrackSelection
from recoryn.app.media import prepare_clips
from recoryn.app.recording import RecordingError, RecordingService
from recoryn.capture.queue import BoundedCaptureQueue, queue_byte_budget
from recoryn.capture.wasapi import DATA_DISCONTINUITY, TIMESTAMP_ERROR, NativePacket, split_packet
from recoryn.domain import MAX_PCM_BLOCK_BYTES, AudioFormat, PCMBlock, SessionState, ValidationError
from recoryn.storage import ChunkWriter, Library, _safe
from recoryn.storage.chunks import scan_prefix
from tests.unit.test_packet_split import group

pytestmark = pytest.mark.integration
FMT = AudioFormat(48000, 1)
R = list(product((1, 2, 3), (False, True), ("none", "adjacent", "separate"), (False, True)))
W = list(product((1, 2, 3), ("before", "at", "after"), (1, 2), (False, True)))
C = [(k, n, strict) for k in (2, 3) for n in range(1, k) for strict in (False, True)]
M = list(product(("correlated", "invalid", "no_position"), (False, True), (2, 3)))
G = list(product((1, 3), (False, True), (False, True)))


@contextmanager
def held_consumer(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = BoundedCaptureQueue.get

    def get(self, *args, **kwargs):
        if threading.current_thread().name.startswith("recoryn-writer") and not entered.is_set():
            entered.set()
            assert release.wait(10), "controlled consumer was not released"
        return original(self, *args, **kwargs)

    monkeypatch.setattr(BoundedCaptureQueue, "get", get)
    try:
        yield entered, release
    finally:
        release.set()


def submit_group(service, count, sequence, accepted):
    values = group(count, sequence=sequence, epoch=service.epochs["mic"], format=FMT)
    size = sum(len(v.payload) for v in values)
    pending = service._queue
    with pending._condition:
        pending._max_bytes = pending._queued_bytes + size - (0 if accepted else 1)
    return service.submit(values[0] if count == 1 else values), values


def completes(operation):
    """A valid synthetic capture/control operation must complete normally."""
    try:
        return operation()
    except (RecordingError, ValidationError) as error:
        raise AssertionError("valid packet/control history was rejected") from error


@pytest.mark.parametrize(
    "count,accepted,history,closed", R, ids=[f"GS06-R-{i:03}" for i in range(1, 37)]
)
def test_service_whole_packet_accounting_never_creates_a_partial_offer(
    tmp_path, monkeypatch, count, accepted, history, closed
):
    with Library(tmp_path) as library, held_consumer(monkeypatch) as (entered, release):
        service = RecordingService(library, {"mic": FMT}, session_id="s")
        service.start()
        assert entered.wait(5)
        expected, lost, sequence = [], 0, 0
        try:
            if history != "none":
                result, values = submit_group(service, count, 0, False)
                assert result is False
                lost += sum(v.frame_count for v in values)
                sequence = 1
                if history == "separate":
                    result, values = submit_group(service, count, 1, True)
                    assert result is True
                    expected.extend(values)
                    sequence = 2
            before = service.health_snapshot()
            if closed:
                with service._gate:
                    service._accepting = False
            if closed:
                values = group(count, sequence=sequence, epoch=service.epochs["mic"], format=FMT)
                result = service.submit(values[0] if count == 1 else values)
            else:
                result, values = submit_group(service, count, sequence, accepted)
            assert result is (accepted and not closed)
            if not closed:
                if accepted:
                    expected.extend(values)
                else:
                    lost += sum(v.frame_count for v in values)
            observed = service.health_snapshot()
            assert observed["tracks"]["mic"] == {
                "accepted_frames": sum(v.frame_count for v in expected),
                "dropped_frames": lost,
            }
            gaps = observed["track_health"]["mic"]["gaps"]
            assert sum(v["frame_count"] for v in gaps) == lost
            expected_gaps = int(history != "none") + int(
                not closed and not accepted and history != "adjacent"
            )
            assert len(gaps) == expected_gaps
            if closed:
                assert observed["queue"] == before["queue"]
            pending = service._queue
            with pending._condition:
                pending._max_bytes = 16 * 1024 * 1024
            release.set()
            result = service.stop(timeout=30)
            assert result["state"] == "FINALIZED" and result["frame_count"] == sum(
                v.frame_count for v in expected
            )
            assert b"".join(
                (library.root / d.relative_path / "audio.pcm").read_bytes()
                for d in library.chunks("s")
            ) == b"".join(v.payload for v in expected)
        finally:
            release.set()
            service.join_writer()


@pytest.mark.parametrize("count,cut,tracks,resume", W, ids=[f"GS06-W-{i:03}" for i in range(1, 37)])
def test_source_desktop_storage_keeps_whole_packets_and_epoch_boundaries(
    tmp_path, monkeypatch, count, cut, tracks, resume
):
    from recoryn.capture import wasapi

    monkeypatch.setattr(wasapi, "MAX_PCM_BLOCK_BYTES", 6)
    frames = {1: 2, 2: 4, 3: 7}[count]
    threshold = {"before": frames + 1, "at": frames, "after": max(1, frames - 1)}[cut]
    expected, old_calls = {}, []
    original = desktop_module.RecordingService

    def recording(*args, **kwargs):
        return original(*args, chunk_frames=threshold, **kwargs)

    monkeypatch.setattr(desktop_module, "RecordingService", recording)

    class Source:
        running = False

        def __init__(self, device, loopback):
            self.device = device

        def start(self, session, track, epoch, submit, health):
            self.running = True
            health({"event": "ready"})
            for sequence in range(2):
                data = bytes([sequence + 1, 17 if track == "mic" else 29]) * frames
                packet = NativePacket(
                    data,
                    frames,
                    0,
                    sequence * frames,
                    (1_000_000 + sequence * frames * 1_000_000_000 // FMT.sample_rate) // 100,
                    2_000_000,
                )
                values = split_packet(packet, (session, track, epoch), sequence, FMT)
                item = values[0] if len(values) == 1 else values
                assert submit(item)
                expected.setdefault((track, epoch), []).append(data)
                old_calls.append((submit, item))
            return FMT

        def stop(self, timeout=5):
            self.running = False

    with Library(tmp_path) as library:
        desktop = DesktopRecorder(library, Source)
        try:
            completes(
                lambda: desktop.start(
                    tuple(
                        TrackSelection(t, t, t == "system", FMT) for t in ("mic", "system")[:tracks]
                    )
                )
            )
            assert desktop.capture_progress().current_accepted_frames == frames * 2 * tracks
            meters, _ = desktop.observations()
            assert all(value.fragment_index == count - 1 for value in meters.values())
            if resume:
                previous = list(old_calls)
                completes(desktop.pause)
                completes(desktop.resume)
                before = desktop.recording.health_snapshot()["tracks"]
                for callback, item in previous:
                    assert callback(item) is False
                assert desktop.recording.health_snapshot()["tracks"] == before
            result = completes(desktop.stop)
            assert result["state"] == "FINALIZED"
            assert result["frame_count"] == frames * 2 * tracks * (2 if resume else 1)
            descriptors = library.chunks(desktop.session_id)
            for key, packets in expected.items():
                selected = [d for d in descriptors if (d.track_id, d.epoch_id) == key]
                assert b"".join(
                    (library.root / d.relative_path / "audio.pcm").read_bytes() for d in selected
                ) == b"".join(packets)
                for d in selected:
                    records = scan_prefix(library.root / d.relative_path, strict=True).blocks
                    assert (
                        records[-1]["metadata"]["fragment_index"] + 1
                        == records[-1]["metadata"]["fragment_count"]
                    )
                    assert all(r["metadata"]["fragment_count"] == count for r in records)
            assert not desktop.recording.worker_alive
        finally:
            desktop.close()


@pytest.mark.parametrize("count,partial,strict", C, ids=[f"GS06-C-{i:03}" for i in range(1, 7)])
def test_recovery_keeps_only_complete_packet_prefix(tmp_path, count, partial, strict):
    with Library(tmp_path) as library:
        library.create_session("s")
        first = group(1, format=FMT)[0]
        writer = ChunkWriter(library.root, first)
        try:
            writer.append(first)
            for value in group(count, sequence=1, format=FMT)[:partial]:
                writer.append(value)
            writer.abort()
            if strict:
                with pytest.raises(ValidationError, match="Incomplete final packet fragments"):
                    scan_prefix(writer.staging_path, strict=True)
            else:
                prefix = scan_prefix(writer.staging_path, strict=False)
                assert (
                    prefix.byte_count == len(first.payload)
                    and prefix.frame_count == first.frame_count
                )
                assert len(prefix.blocks) == 1 and prefix.blocks[0]["metadata"]["sequence"] == 0
                assert (writer.staging_path / "audio.pcm").read_bytes()[
                    : prefix.byte_count
                ] == first.payload
        finally:
            writer.abort()


@pytest.mark.parametrize("number", (1, 2, 6, 7, 8), ids=[f"GS06-B-{i:03}" for i in (1, 2, 6, 7, 8)])
def test_real_fragment_and_queue_budget_boundaries(tmp_path, number):
    if number >= 6:
        formats, expected = {
            6: ([AudioFormat(48000, 2)], 16 * 1024 * 1024),
            7: ([AudioFormat(48000, 2), AudioFormat(768000, 64, "s24le")], 58_982_400),
            8: ([AudioFormat(768000, 64, "f32le")], 78_643_200),
        }[number]
        assert queue_byte_budget(formats) == expected
        assert expected <= 128 * 1024 * 1024
        with Library(tmp_path) as library:
            configured = {f"t{i}": value for i, value in enumerate(formats)}
            service = RecordingService(library, configured)
            try:
                assert service.max_bytes == expected
                service.start()
                assert service.health_snapshot()["queue"]["max_bytes"] == expected
                wanted = 0
                if number >= 7:
                    fmt = formats[-1]
                    frames = (16 * 1024 * 1024) // fmt.frame_bytes + 1
                    packet = NativePacket(
                        bytes(frames * fmt.frame_bytes), frames, 0, 0, 1000, 100000
                    )
                    track = f"t{len(formats) - 1}"
                    values = split_packet(
                        packet, (service.session_id, track, service.epochs[track]), 0, fmt
                    )
                    assert len(values) == 2 and service.submit(values)
                    wanted = frames
                result = service.stop(timeout=30)
                assert result["state"] == "FINALIZED" and result["frame_count"] == wanted
                assert not service.storage_failed
            finally:
                service.join_writer()
        return
    assert MAX_PCM_BLOCK_BYTES == _safe.MAX_BLOCK_BYTES == 16 * 1024 * 1024
    if number == 2:
        fmt = AudioFormat(768000, 63, "s32le")
        frames = (64 * 1024 * 1024) // 252
        packet = NativePacket(bytes(frames * 252), frames, 0, 0, 1000, 100000)
        with Library(tmp_path) as library:
            service = RecordingService(library, {"mic": fmt}, session_id="s")
            try:
                service.start()
                values = split_packet(packet, ("s", "mic", service.epochs["mic"]), 0, fmt)
                assert len(values) == 5
                assert all(
                    len(v.payload) <= 16 * 1024 * 1024 and len(v.payload) % 252 == 0 for v in values
                )
                assert sum(v.frame_count for v in values) == frames
                assert service.max_bytes == 77_414_400 and service.submit(values)
                assert service.stop(timeout=30)["frame_count"] == frames
                descriptors = library.chunks("s")
                assert len(descriptors) == 1
                assert (
                    library.root / descriptors[0].relative_path / "audio.pcm"
                ).read_bytes() == packet.payload
            finally:
                service.join_writer()
        return
    with Library(tmp_path) as library:
        library.create_session("s")
        data = b"\x11\x22" * (8 * 1024 * 1024)
        value = PCMBlock("s", "mic", "e", 0, FMT, len(data) // 2, data, 0, 0, 0)
        writer = ChunkWriter(library.root, value)
        try:
            writer.append(value)
            descriptor = writer.seal()
            library.register_chunk(descriptor)
            assert descriptor.byte_count == 16 * 1024 * 1024
            assert (library.root / descriptor.relative_path / "audio.pcm").read_bytes() == data
        finally:
            writer.abort()


def publish(library, sid, packets):
    session = library.create_session(sid)
    session = library.transition(sid, SessionState.RECORDING, session.state_version)
    writer = None
    try:
        for values in packets:
            for value in values:
                if writer is None:
                    writer = ChunkWriter(library.root, value)
                writer.append(value)
        library.register_chunk(writer.seal())
        session = library.transition(sid, SessionState.FINALIZING, session.state_version)
        library.finalize_session(sid)
    finally:
        if writer is not None:
            writer.abort()


@pytest.mark.parametrize(
    "clock,discontinuity,count", M, ids=[f"GS06-M-{i:03}" for i in range(1, 13)]
)
def test_derived_audio_is_invariant_under_packet_fragmentation(
    tmp_path, clock, discontinuity, count
):
    frames = 4 if count == 2 else 7
    with Library(tmp_path) as library:
        outputs = []
        for limit, sid in ((1000, "whole"), (6, "split")):
            packets = []
            for sequence in range(2):
                flags = TIMESTAMP_ERROR if clock == "invalid" else 0
                if discontinuity and sequence == 1:
                    flags |= DATA_DISCONTINUITY
                packet = NativePacket(
                    b"\x12\x34" * frames,
                    frames,
                    flags,
                    None if clock == "no_position" else sequence * frames,
                    (1_000_000 + sequence * frames * 1_000_000_000 // 48000) // 100,
                    3_000_000,
                )
                packets.append(
                    split_packet(packet, (sid, "mic", "e"), sequence, FMT, max_block_bytes=limit)
                )
            publish(library, sid, packets)
            _, clips = prepare_clips(library, sid)
            data = []
            for clip in clips:
                with wave.open(str(clip.path), "rb") as stream:
                    data.append(stream.readframes(stream.getnframes()))
            outputs.append(
                (
                    data,
                    [c.timing_quality for c in clips],
                    [c.offset_ms for c in clips],
                    sum(v["frame_count"] for c in clips for v in c.source_ranges),
                    [c.duration_ms for c in clips],
                    [
                        (
                            min(v["source_chunk_frame_start"] for v in c.source_ranges),
                            max(
                                v["source_chunk_frame_start"] + v["frame_count"]
                                for v in c.source_ranges
                            ),
                        )
                        for c in clips
                    ],
                )
            )
        assert outputs[0] == outputs[1]
        separate = clock == "invalid" or discontinuity
        clip_frames = [frames, frames] if separate else [frames * 2]
        assert outputs[0] == (
            [b"\x12\x34" * n for n in clip_frames],
            ["unknown" if clock == "invalid" else "correlated"] * len(clip_frames),
            [None if clock == "invalid" else 0] * len(clip_frames),
            frames * 2,
            [1] * len(clip_frames),
            [(0, frames), (frames, frames * 2)] if separate else [(0, frames * 2)],
        )


@pytest.mark.parametrize(
    "boundary",
    (
        "same",
        "no_position",
        "start_event",
        "quality",
        "state_error",
        "state_silent",
        "discontinuity",
        "raw_event",
        "position_gap",
        "position_missing",
        "arrival",
        "clock_jump",
    ),
    ids=[f"GS06-XM-{i:03}" for i in range(1, 13)],
)
def test_unknown_packet_clip_join_requires_verified_fragment_continuity(tmp_path, boundary):
    flags = 1 | 8 if boundary == "start_event" else 0
    packet = NativePacket(b"\x12\x34" * 4, 4, flags, 10, None, 30)
    first, second = split_packet(packet, ("s", "mic", "e"), 0, FMT, max_block_bytes=4)
    if boundary == "no_position":
        first = replace(first, device_frame_position=None)
        second = replace(second, device_frame_position=None)
    changes = {
        "quality": {"clock_quality": "UNKNOWN"},
        "state_error": {"flags": ("TIMESTAMP_ERROR",)},
        "state_silent": {"flags": ("SILENT",)},
        "discontinuity": {"flags": ("DATA_DISCONTINUITY",)},
        "raw_event": {"flags": ("RAW_FLAGS_00000008",)},
        "position_gap": {"device_frame_position": 13},
        "position_missing": {"device_frame_position": None},
        "arrival": {"arrival_mono_ns": 31},
    }
    if boundary in changes:
        second = replace(second, **changes[boundary])
    if boundary == "clock_jump":
        first = replace(first, capture_mono_ns=1000, clock_quality="DEVICE_CORRELATED")
        second = replace(second, capture_mono_ns=1_000_001_000, clock_quality="DEVICE_CORRELATED")
    joined = boundary in {"same", "no_position", "start_event"}
    with Library(tmp_path) as library:
        publish(library, "s", [(first, second)])
        _, clips = prepare_clips(library, "s")
        assert len(clips) == (1 if joined else 2)
        expected = [b"\x12\x34" * 4] if joined else [b"\x12\x34" * 2] * 2
        for clip, payload in zip(clips, expected, strict=True):
            with wave.open(str(clip.path), "rb") as stream:
                assert stream.readframes(stream.getnframes()) == payload
        if boundary == "clock_jump":
            assert [c.timing_quality for c in clips] == ["correlated", "unknown"]
            assert [c.offset_ms for c in clips] == [0, None]
        else:
            assert all(c.timing_quality == "unknown" and c.offset_ms is None for c in clips)


@pytest.mark.parametrize("count,accepted,after", G, ids=[f"GS06-G-{i:03}" for i in range(1, 9)])
def test_health_checkpoint_counts_packet_once_and_finishes_at_its_last_fragment(
    tmp_path, monkeypatch, count, accepted, after
):
    appended, checkpoints = [], []
    at_last, control_done = threading.Event(), threading.Event()
    original_append, original_checkpoint = ChunkWriter.append, RecordingService._checkpoint_health

    def append(self, value):
        original_append(self, value)
        appended.append(value)

    def checkpoint(self, *args, **kwargs):
        if threading.current_thread().name.startswith("recoryn-writer") and appended:
            checkpoints.append(appended[-1].fragment_index)
            if after and accepted and len(appended) == count:
                at_last.set()
                assert control_done.wait(5)
        return original_checkpoint(self, *args, **kwargs)

    monkeypatch.setattr(ChunkWriter, "append", append)
    monkeypatch.setattr(RecordingService, "_checkpoint_health", checkpoint)
    with Library(tmp_path) as library, held_consumer(monkeypatch) as (entered, release):
        service = RecordingService(library, {"mic": FMT}, session_id="s")
        service.start()
        assert entered.wait(5)
        try:
            result, values = submit_group(service, count, 0, accepted)
            assert result is accepted
            frames = count * 2
            if not after:
                service._checkpoint_health(force=True)
                assert appended == []
            else:
                release.set()
                if accepted:
                    assert at_last.wait(5)
                service._checkpoint_health(force=True)
                control_done.set()
            pending = service._queue
            with pending._condition:
                pending._max_bytes = 16 * 1024 * 1024
            release.set()
            result = service.stop(timeout=30)
            assert result["state"] == "FINALIZED" and result["frame_count"] == (
                frames if accepted else 0
            )
            snapshot = service.health_snapshot()
            assert snapshot["tracks"]["mic"] == {
                "accepted_frames": frames if accepted else 0,
                "dropped_frames": 0 if accepted else frames,
            }
            canonical = [
                json.loads(row[0])
                for row in library._db.execute(
                    "SELECT payload FROM capture_health_events WHERE session_id='s'"
                )
            ]
            queue_gaps = [v for v in canonical if v["reason"] == "QUEUE_DROP"]
            assert len(queue_gaps) == (0 if accepted else 1)
            if queue_gaps:
                assert queue_gaps[0]["lost_frames"] == frames
            assert all(index == count - 1 for index in checkpoints)
            if accepted:
                assert len(appended) == count and appended[-1].fragment_index == count - 1
                d = library.chunks("s")[-1]
                last = scan_prefix(library.root / d.relative_path, strict=True).blocks[-1][
                    "metadata"
                ]
                assert (last["sequence"], last["fragment_index"]) == (0, count - 1)
                assert snapshot["track_health"]["mic"]["last_accepted_sequence"] == 0
        finally:
            control_done.set()
            release.set()
            service.join_writer()


def test_GS06_X001_invalid_tuple_does_not_change_service_accounting(tmp_path):
    with Library(tmp_path) as library:
        service = RecordingService(library, {"mic": FMT}, session_id="s")
        try:
            service.start()
            values = group(3, epoch=service.epochs["mic"], format=FMT)
            before = service.health_snapshot()["queue"]
            for invalid in (
                (),
                (values[0],),
                (values[0], values[2]),
                (values[0], "bad", values[2]),
                list(values),
                None,
            ):
                with pytest.raises(ValidationError):
                    service.submit(invalid)
                assert service.health_snapshot()["queue"] == before
                assert service.health_snapshot()["tracks"]["mic"] == {
                    "accepted_frames": 0,
                    "dropped_frames": 0,
                }
            assert service.stop(timeout=30)["frame_count"] == 0
        finally:
            service.join_writer()


def test_GS06_X002_invalid_format_budget_does_not_create_a_recording(tmp_path):
    with Library(tmp_path) as library:
        for invalid in ((), (None,), ("not a format",)):
            with pytest.raises(ValidationError, match="Queue budget requires audio formats"):
                queue_byte_budget(invalid)
        with pytest.raises(ValidationError, match="Queue budget requires audio formats"):
            RecordingService(library, {"mic": None}, session_id="invalid")
        assert library.list_sessions() == []
