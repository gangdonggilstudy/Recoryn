from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from recoryn.app.ai import AIService
from recoryn.app.recording import RecordingService
from recoryn.content import ContentStore, Segment
from recoryn.domain import AudioFormat, PCMBlock
from recoryn.providers import (
    ProviderCapabilities,
    SegmentSpan,
    STTResult,
    SummaryCheckpoint,
    SummaryClaim,
    SummaryResult,
    TranscriptSegment,
)
from recoryn.storage import Library

pytestmark = pytest.mark.e2e


def recording(library):
    service = RecordingService(library, {"mic": AudioFormat(48000, 1)})
    service.start()
    assert service.submit(
        PCMBlock(
            service.session_id,
            "mic",
            service.epochs["mic"],
            0,
            AudioFormat(48000, 1),
            48000,
            b"\x00\x40" * 48000,
            1000000000,
            1000000000,
            device_frame_position=0,
        )
    )
    service.stop()
    return service.session_id


def finished(service, job_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = service.jobs.get(job_id)
        if job.state.value in {"SUCCEEDED", "FAILED", "CANCELLED", "BLOCKED"}:
            return job
        time.sleep(0.005)
    pytest.fail("AI job did not finish")


class FakeSTT:
    def __init__(self, *, complete=True, barrier=None):
        self.complete, self.barrier = complete, barrier

    def capabilities(self):
        return ProviderCapabilities("fake", transcription=True)

    def transcribe(self, request, context=None):
        if self.barrier:
            self.barrier[0].set()
            assert self.barrier[1].wait(5)
        item = TranscriptSegment(
            "sentence",
            request.offset_ms,
            request.offset_ms + 500,
            "A source sentence",
            track_id=request.track_id,
        )
        return STTResult(
            "fake",
            "model",
            (item,),
            self.complete,
            error_code=None if self.complete else "MODEL_FAILED",
            processed_ms=1000,
        )


class FakeSummary:
    def capabilities(self):
        return ProviderCapabilities("fake", summarization=True)

    def summarize(self, request, context=None):
        refs = tuple(item.segment_id for item in request.segments)
        coverage = tuple(
            SegmentSpan(item.segment_id, 0, len(item.text)) for item in request.segments
        )
        return SummaryResult(
            "fake",
            "model",
            request.transcript_revision_id,
            (SummaryClaim("A source-backed claim", refs),),
            coverage,
            (),
            True,
            SummaryCheckpoint("a" * 64),
        )


def test_record_transcribe_summary_edit_and_repeatable_srt(tmp_path: Path):
    with Library(tmp_path / "library") as library, ContentStore(library) as content:
        session = recording(library)
        source_hashes = [item.sha256 for item in library.chunks(session)]
        service = AIService(library, content)
        try:
            job = service.transcribe(session, FakeSTT(), config_key="fake-v1")
            assert finished(service, job).state.value == "SUCCEEDED"
            transcript = content.active_transcript(session)
            assert transcript["complete"] and transcript["coverage"]["missing"] == []
            assert transcript["segments"][0]["track_id"] == "mic"
            first = content.export_transcript(transcript["revision_id"], "srt")
            assert "00:00:00,000 --> 00:00:00,500" in first
            summary_job = service.summarize(session, FakeSummary(), config_key="fake-summary-v1")
            assert finished(service, summary_job).state.value == "SUCCEEDED"
            summary = content.active_summary(session)
            assert summary["claims"][0]["segment_ids"] == ["sentence"]
            assert summary["claims"][0]["status"] == "uncertain"
            edited = content.edit_segment(
                session,
                transcript["revision_id"],
                "sentence",
                "User-added statement",
                expected_active=transcript["revision_id"],
            )
            assert content.transcript(edited)["segments"][0]["provenance"] == "user_assertion"
            assert content.active_summary(session)["stale"]
            assert content.export_transcript(transcript["revision_id"], "srt") == first
            assert source_hashes == [item.sha256 for item in library.chunks(session)]
        finally:
            service.close()


def test_partial_inference_keeps_candidate_without_false_ready(tmp_path: Path):
    with Library(tmp_path / "library") as library, ContentStore(library) as content:
        session = recording(library)
        service = AIService(library, content)
        try:
            job = service.transcribe(session, FakeSTT(complete=False), config_key="partial")
            assert finished(service, job).state.value == "FAILED"
            assert content.active_transcript(session) is None
            revisions = content.list_revisions(session, "transcript")
            assert len(revisions) == 1
            assert not revisions[0]["complete"]
            assert revisions[0]["segments"][0]["text"] == "A source sentence"
        finally:
            service.close()


def test_user_edit_wins_against_late_complete_transcript(tmp_path: Path):
    with Library(tmp_path / "library") as library, ContentStore(library) as content:
        session = recording(library)
        original = content.create_transcript(session, [Segment("old", 0, 500, "old words")])
        entered, release = threading.Event(), threading.Event()
        service = AIService(library, content)
        try:
            job = service.transcribe(
                session, FakeSTT(barrier=(entered, release)), config_key="late"
            )
            assert entered.wait(5)
            edited = content.edit_segment(
                session, original, "old", "User correction", expected_active=original
            )
            release.set()
            assert finished(service, job).state.value == "SUCCEEDED"
            assert content.active_transcript(session)["revision_id"] == edited
            assert service.jobs.get(job).result_ref != edited
        finally:
            release.set()
            service.close()


def test_cancel_revokes_publication_even_when_model_ignores_cancel(tmp_path: Path):
    with Library(tmp_path / "library") as library, ContentStore(library) as content:
        session = recording(library)
        entered, release = threading.Event(), threading.Event()
        service = AIService(library, content)
        try:
            job = service.transcribe(
                session, FakeSTT(barrier=(entered, release)), config_key="cancel"
            )
            assert entered.wait(5)
            service.cancel_session(session)
            release.set()
            assert finished(service, job).state.value == "CANCELLED"
            assert content.list_revisions(session) == []
            assert len(library.chunks(session)) == 1
        finally:
            release.set()
            service.close()


class CountingSTT(FakeSTT):
    def __init__(self):
        super().__init__()
        self.calls = []

    def transcribe(self, request, context=None):
        self.calls.append(request.offset_ms)
        return super().transcribe(request, context)


def emit_epoch(recorder, *, stamp=1_000_000_000, silent=False):
    assert recorder.submit(
        PCMBlock(
            recorder.session_id,
            "mic",
            recorder.epochs["mic"],
            0,
            AudioFormat(8000, 1),
            8000,
            (b"\0\0" if silent else b"\0\x40") * 8000,
            stamp,
            stamp,
            device_frame_position=0,
        )
    )
    recorder.pause()


def test_streaming_accumulates_only_fresh_chunks_and_protects_edits_and_config(tmp_path: Path):
    with Library(tmp_path / "library") as library, ContentStore(library) as content:
        recorder = RecordingService(library, {"mic": AudioFormat(8000, 1)})
        recorder.start()
        emit_epoch(recorder)
        session = recorder.session_id
        first = frozenset(item.chunk_id for item in library.chunks(session))
        service, provider = AIService(library, content), CountingSTT()
        options = dict(config_key="live", provisional=True, origin_ns=1_000_000_000)
        try:
            job = service.transcribe(session, provider, chunk_ids=first, **options)
            assert finished(service, job).state.value == "SUCCEEDED"
            draft = content.active_transcript(session)
            assert draft["kind"] == "draft" and not draft["complete"]
            recorder.resume()
            emit_epoch(recorder, stamp=3_000_000_000)
            all_ids = frozenset(item.chunk_id for item in library.chunks(session))
            job = service.transcribe(session, provider, chunk_ids=all_ids, **options)
            assert finished(service, job).state.value == "SUCCEEDED"
            draft = content.active_transcript(session)
            assert len(draft["segments"]) == 2 and provider.calls == [0, 2000]
            assert len({segment["segment_id"] for segment in draft["segments"]}) == 2
            coverage = draft["coverage"]
            assert len(coverage["planned"]) == len(coverage["completed"]) == 2
            assert len(coverage["source_ranges"]) == 2
            assert all(len(source["sha256"]) == 64 for source in coverage["source_ranges"])
            edited = content.edit_segment(
                session,
                draft["revision_id"],
                draft["segments"][0]["segment_id"],
                "User selected correction",
                expected_active=draft["revision_id"],
            )
            assert content.select_transcript(session, edited, expected_active=draft["revision_id"])
            other = service.transcribe(
                session,
                provider,
                config_key="different",
                provisional=True,
                chunk_ids=first,
                origin_ns=1_000_000_000,
            )
            assert finished(service, other).state.value == "SUCCEEDED"
            candidate = content.transcript(service.jobs.get(other).result_ref)
            assert len(candidate["segments"]) == 1  # Different scope never merges.
            recorder.stop()
            full = service.transcribe(session, provider, config_key="full")
            assert finished(service, full).state.value == "SUCCEEDED"
            assert content.transcript(service.jobs.get(full).result_ref)["complete"]
            assert content.active_transcript(session)["revision_id"] == edited
        finally:
            recorder.join_writer()
            service.close()


def test_vad_silence_completes_coverage_without_an_stt_request(tmp_path: Path):
    with Library(tmp_path / "library") as library, ContentStore(library) as content:
        recorder = RecordingService(library, {"mic": AudioFormat(8000, 1)})
        recorder.start()
        emit_epoch(recorder, silent=True)
        service, provider = AIService(library, content), CountingSTT()
        try:
            job = service.transcribe(
                recorder.session_id,
                provider,
                config_key="silent",
                provisional=True,
                origin_ns=1_000_000_000,
            )
            assert finished(service, job).state.value == "SUCCEEDED"
            result = content.active_transcript(recorder.session_id)
            assert result["segments"] == [] and provider.calls == []
            assert result["coverage"]["completed"] == result["coverage"]["planned"]
            assert result["coverage"]["missing"] == []
        finally:
            recorder.join_writer()
            service.close()


def test_slow_ai_conversion_does_not_hold_recording_writer_or_pause(tmp_path: Path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    from recoryn.app import media

    entered, release = threading.Event(), threading.Event()
    original = media._int16

    def gated(payload, fmt):
        entered.set()
        assert release.wait(5)
        return original(payload, fmt)

    with Library(tmp_path / "library") as library, ContentStore(library) as content:
        recorder = RecordingService(library, {"mic": AudioFormat(8000, 1)})
        recorder.start()
        emit_epoch(recorder)
        service = AIService(library, content)
        monkeypatch.setattr(media, "_int16", gated)
        try:
            job = service.transcribe(
                recorder.session_id, CountingSTT(), config_key="gated", provisional=True
            )
            assert entered.wait(3)
            recorder.resume()
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(emit_epoch, recorder, stamp=3_000_000_000)
                try:
                    future.result(timeout=2)
                finally:
                    release.set()
            assert len(library.chunks(recorder.session_id)) == 2
            assert finished(service, job).state.value == "SUCCEEDED"
        finally:
            release.set()
            recorder.join_writer()
            service.close()


def test_streaming_origin_is_restored_from_checkpoint_after_service_restart(tmp_path: Path):
    with Library(tmp_path / "library") as library, ContentStore(library) as content:
        recorder = RecordingService(library, {"mic": AudioFormat(8000, 1)})
        recorder.start()
        emit_epoch(recorder)
        provider = CountingSTT()
        service = AIService(library, content)
        try:
            first = service.transcribe(
                recorder.session_id, provider, config_key="live", provisional=True
            )
            assert finished(service, first).state.value == "SUCCEEDED"
        finally:
            service.close()
        recorder.resume()
        emit_epoch(recorder, stamp=3_000_000_000)
        restarted = AIService(library, content)
        try:
            second = restarted.transcribe(
                recorder.session_id, provider, config_key="live", provisional=True
            )
            assert finished(restarted, second).state.value == "SUCCEEDED"
            assert provider.calls == [0, 2000]
            draft = content.active_transcript(recorder.session_id)
            assert [segment["start_ms"] for segment in draft["segments"]] == [0, 2000]
            assert draft["coverage"]["checkpoint"]["resolved_origin_ns"] == 1_000_000_000
        finally:
            restarted.close()
            recorder.join_writer()


def test_unknown_requires_new_nonce_and_keeps_old_job_and_originals(tmp_path: Path):
    class UnknownThenKnown(CountingSTT):
        unknown = True

        def transcribe(self, request, context=None):
            known = super().transcribe(request, context)
            return STTResult(
                known.provider_id,
                known.model,
                known.segments,
                not self.unknown,
                outcome_known=not self.unknown,
                error_code="REMOTE_OUTCOME_UNKNOWN" if self.unknown else None,
            )

    with Library(tmp_path / "library") as library, ContentStore(library) as content:
        session = recording(library)
        hashes = [chunk.sha256 for chunk in library.chunks(session)]
        service, provider = AIService(library, content), UnknownThenKnown()
        try:
            first = service.transcribe(session, provider, config_key="same")
            assert finished(service, first).blocked_reason == "REMOTE_UNKNOWN"
            assert service.transcribe(session, provider, config_key="same") == first
            assert provider.calls == [0]
            provider.unknown = False
            retry = service.transcribe(
                session, provider, config_key="same", request_nonce="explicit-user-action"
            )
            assert retry != first and finished(service, retry).state.value == "SUCCEEDED"
            assert service.jobs.get(first).blocked_reason == "REMOTE_UNKNOWN"
            assert provider.calls == [0, 0]
            assert [chunk.sha256 for chunk in library.chunks(session)] == hashes
        finally:
            service.close()
