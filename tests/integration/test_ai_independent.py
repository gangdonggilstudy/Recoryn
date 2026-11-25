"""BR13 independent AI integration oracles; no device, model or network access.

OPEN regressions use strict xfail. Run with --runxfail to see the counterexamples
as failures; an XPASS requires reviewer recheck rather than silent acceptance.
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
import wave
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from recoryn.app.ai import AIService
from recoryn.app.media import prepare_clips
from recoryn.app.recording import RecordingService
from recoryn.content import ContentStore, Segment
from recoryn.domain import AudioFormat, PCMBlock, StateConflict
from recoryn.models import FileSpec, ModelManager, ModelSpec
from recoryn.providers import (
    SegmentSpan,
    STTResult,
    SummaryCheckpoint,
    SummaryClaim,
    SummaryResult,
    TranscriptSegment,
)
from recoryn.security import ConsentRequest, ConsentScope, ConsentStore, Gateway, SecurityError
from recoryn.storage import Library
from tests.resource_fakes import STT, SUMMARY

pytestmark = pytest.mark.integration


def _record(library: Library, *, frames: int = 800, quality: str = "DEVICE_CORRELATED") -> str:
    fmt = AudioFormat(8000, 1)
    recording = RecordingService(library, {"mic": fmt}, chunk_frames=max(frames, 800))
    recording.start()
    assert recording.submit(
        PCMBlock(
            recording.session_id,
            "mic",
            recording.epochs["mic"],
            0,
            fmt,
            frames,
            b"\0\x40" * frames,
            1_000_000_000,
            2_000_000_000,
            device_frame_position=0,
            clock_quality=quality,
        )
    )
    recording.stop()
    return recording.session_id


@contextmanager
def _service(tmp_path: Path) -> Iterator[tuple[Library, ContentStore, AIService, str]]:
    with Library(tmp_path / "library") as library, ContentStore(library) as content:
        session = _record(library)
        service = AIService(library, content)
        try:
            yield library, content, service, session
        finally:
            service.close()


def _finished(service: AIService, job_id: str):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = service.jobs.get(job_id)
        if job.state.value in {"SUCCEEDED", "FAILED", "CANCELLED", "BLOCKED"}:
            return job
        time.sleep(0.005)
    pytest.fail(f"AI completion timeout: {service.jobs.get(job_id).state}")


class _Provider:
    def __init__(self, *, gated: bool = False, unknown: bool = False) -> None:
        self.entered, self.release = threading.Event(), threading.Event()
        self.unknown, self.calls = unknown, 0
        if not gated:
            self.release.set()

    def _wait(self) -> None:
        self.calls += 1
        self.entered.set()
        assert self.release.wait(5), "test barrier was not released"

    def transcribe(self, request, context=None):
        self._wait()
        return STTResult(
            "fixture",
            "pinned-model",
            (
                TranscriptSegment(
                    "source-1",
                    request.offset_ms,
                    request.offset_ms + 50,
                    "Synthetic source",
                    track_id=request.track_id,
                    timing_quality="clip",
                ),
            ),
            not self.unknown,
            error_code="REMOTE_OUTCOME_UNKNOWN" if self.unknown else None,
            outcome_known=not self.unknown,
        )

    def summarize(self, request, context=None):
        self._wait()
        spans = tuple(SegmentSpan(s.segment_id, 0, len(s.text)) for s in request.segments)
        return SummaryResult(
            "fixture",
            "pinned-model",
            request.transcript_revision_id,
            (SummaryClaim("Unverified claim", (request.segments[0].segment_id,)),),
            spans,
            (),
            not self.unknown,
            SummaryCheckpoint("a" * 64),
            error_code="REMOTE_OUTCOME_UNKNOWN" if self.unknown else None,
            outcome_known=not self.unknown,
        )


def _submit(kind: str, service: AIService, session: str, provider: _Provider) -> str:
    if kind == "stt":
        return service.transcribe(session, provider, config_key="fixture-stt", resource_request=STT)
    if service.content.active_transcript(session) is None:
        service.content.create_transcript(
            session, [Segment("source-1", 0, 50, "Synthetic source", track_id="mic")]
        )
    return service.summarize(
        session, provider, config_key="fixture-summary", resource_request=SUMMARY
    )


@pytest.mark.parametrize("kind", ["stt", "summary"])
def test_cancelled_unknown_result_remains_remote_unknown(tmp_path: Path, kind: str) -> None:
    with _service(tmp_path) as (library, content, service, session):
        provider = _Provider(gated=True, unknown=True)
        try:
            job = _submit(kind, service, session, provider)
            assert provider.entered.wait(5)
            service.cancel_session(session)  # durable fence before the remote result
            provider.release.set()
            result = _finished(service, job)
            assert (result.state.value, result.blocked_reason) == ("BLOCKED", "REMOTE_UNKNOWN")
            with closing(sqlite3.connect(library.db_path)) as connection:
                assert connection.execute(
                    "SELECT state FROM attempts WHERE job_id=?", (job,)
                ).fetchall() == [("UNKNOWN",)]
            assert provider.calls == 1
            assert (
                content.list_revisions(session, "summary" if kind == "summary" else "transcript")
                == []
            )
        finally:
            provider.release.set()


@pytest.mark.parametrize("kind", ["stt", "summary"])
def test_unknown_without_cancel_keeps_partial_candidate_and_no_retry(
    tmp_path: Path, kind: str
) -> None:
    with _service(tmp_path) as (_, content, service, session):
        provider = _Provider(unknown=True)
        job = _submit(kind, service, session, provider)
        result = _finished(service, job)
        assert (result.state.value, result.blocked_reason) == ("BLOCKED", "REMOTE_UNKNOWN")
        revisions = content.list_revisions(
            session, "summary" if kind == "summary" else "transcript"
        )
        assert len(revisions) == 1 and not revisions[0]["complete"]
        assert (
            content.active_summary(session)
            if kind == "summary"
            else content.active_transcript(session)
        ) is None
        assert provider.calls == 1


@pytest.mark.parametrize("kind", ["stt", "summary"])
def test_duplicate_submission_preserves_running_job(tmp_path: Path, kind: str) -> None:
    with _service(tmp_path) as (_, _, service, session):
        provider = _Provider(gated=True)
        try:
            first = _submit(kind, service, session, provider)
            assert provider.entered.wait(5)
            try:
                second = _submit(kind, service, session, provider)
            except StateConflict:
                second = None
            assert service.jobs.get(first).state.value == "RUNNING"
            assert second in (None, first)  # rejection or reuse must preserve the original
            provider.release.set()
            assert _finished(service, first).state.value == "SUCCEEDED"
            assert provider.calls == 1
        finally:
            provider.release.set()


@pytest.mark.parametrize("kind", ["stt", "summary"])
def test_cancel_then_delete_fences_late_known_result(tmp_path: Path, kind: str) -> None:
    with _service(tmp_path) as (library, content, service, session):
        provider = _Provider(gated=True)
        try:
            job = _submit(kind, service, session, provider)
            assert provider.entered.wait(5)
            service.cancel_session(session)
            assert library.delete_session(session)["state"] == "DELETE_PENDING"
            provider.release.set()
            assert _finished(service, job).state.value == "CANCELLED"
            assert library.delete_session(session)["state"] == "DELETED_LOCAL"
            assert not (library.root / "sessions" / session).exists()
            with pytest.raises((StateConflict, KeyError)):
                content.active_transcript(session)
            with pytest.raises((StateConflict, KeyError)):
                prepare_clips(library, session)
            assert not (library.root / "sessions" / session).exists()
        finally:
            provider.release.set()


def test_changed_clock_origin_does_not_reuse_old_result(tmp_path: Path) -> None:
    with _service(tmp_path) as (_, content, service, session):
        provider = _Provider()
        first = service.transcribe(
            session, provider, config_key="same", origin_ns=1_000_000_000, resource_request=STT
        )
        assert _finished(service, first).state.value == "SUCCEEDED"
        assert content.active_transcript(session)["segments"][0]["start_ms"] == 0
        second = service.transcribe(
            session, provider, config_key="same", origin_ns=0, resource_request=STT
        )
        assert second != first
        assert _finished(service, second).state.value == "SUCCEEDED"
        assert content.active_transcript(session)["segments"][0]["start_ms"] == 1000


def test_model_cancel_before_activation_preserves_only_partial(tmp_path: Path) -> None:
    payload = b"synthetic-model-no-download"
    spec = ModelSpec(
        "fixture",
        "whisper",
        "MIT",
        "https://example.invalid/license",
        (
            FileSpec(
                "model.bin",
                "https://example.invalid/model",
                len(payload),
                hashlib.sha256(payload).hexdigest(),
            ),
        ),
    )
    manager = ModelManager(
        tmp_path / "models", downloader=lambda url, offset: iter([payload[offset:]])
    )
    cancel = threading.Event()

    def progress(done: int, total: int) -> None:
        if done == total:
            cancel.set()

    with pytest.raises(StateConflict, match="CANCELLED"):
        manager.install(spec, approved=True, cancel=cancel, progress=progress)
    assert not (manager.root / spec.model_id).exists()
    assert manager.list_installed() == []
    cancel.clear()
    installed = manager.install(spec, approved=True, cancel=cancel)
    assert (installed / "model.bin").read_bytes() == payload


@pytest.mark.parametrize("seconds,limit", [(3, 1), (31, 30)])
def test_clip_limit_splits_oversized_source_block_without_loss(
    tmp_path: Path, seconds: int, limit: int
) -> None:
    with Library(tmp_path / "library") as library:
        session = _record(library, frames=8000 * seconds)
        _, clips = prepare_clips(library, session, max_seconds=limit)
        assert all(clip.duration_ms <= 1000 * limit for clip in clips)
        total = 0
        for clip in clips:
            assert clip.offset_ms == total * 1000 // 8000
            assert clip.source_ranges[0]["source_chunk_frame_start"] == total
            assert clip.source_ranges[0]["output_frame_start"] == 0
            assert (
                clip.source_ranges[0]["capture_mono_ns"]
                == 1_000_000_000 + total * 1_000_000_000 // 8000
            )
            with wave.open(str(clip.path), "rb") as audio:
                assert audio.readframes(audio.getnframes()) == b"\0\x40" * audio.getnframes()
                total += audio.getnframes()
        assert total == 8000 * seconds


def test_source_track_quality_and_bytes_survive_ai_round_trip(tmp_path: Path) -> None:
    with _service(tmp_path) as (library, content, service, session):
        before = [chunk.sha256 for chunk in library.chunks(session)]
        job = service.transcribe(session, _Provider(), config_key="mapping", resource_request=STT)
        assert _finished(service, job).state.value == "SUCCEEDED"
        revision = content.active_transcript(session)
        segment = revision["segments"][0]
        assert (segment["track_id"], segment["timing_quality"]) == ("mic", "clip")
        source = revision["coverage"]["source_ranges"][0]
        assert source["offset_ms"] == segment["start_ms"] == 0
        assert source["track_id"] == "mic"
        assert source["ranges"][0]["frame_count"] == 800
        assert source["ranges"][0]["source_chunk_frame_start"] == 0
        assert before == [chunk.sha256 for chunk in library.chunks(session)]


def test_summary_reference_navigation_uses_original_revision(tmp_path: Path) -> None:
    # Exercise actual Qt signal payloads without multimedia or a physical display.
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from recoryn.content import Claim
    from recoryn.ui.content import ContentPanel

    application = QApplication.instance() or QApplication([])
    with Library(tmp_path / "library") as library, ContentStore(library) as content:
        session = _record(library)
        original = content.create_transcript(
            session,
            [Segment("original", 0, 50, "Before edit", track_id="mic", timing_quality="clip")],
        )
        content.create_summary(
            session, original, [Claim("Unverified", ("original",))], expected_transcript=original
        )
        edited = content.edit_segment(
            session, original, "original", "User assertion", expected_active=original
        )
        panel = ContentPanel(content, lambda *args: None)
        try:
            seen: list[tuple[str, int, str]] = []
            panel.seekRequested.connect(lambda *args: seen.append(args))
            panel.load(session)
            assert panel.revision["revision_id"] == edited
            panel._seek(0, 0)
            assert seen == []  # user assertion has no automatically inherited audio proof
            panel._claim_clicked("claim:0:0")
            assert panel.revision["revision_id"] == original
            assert seen == [("mic", 0, original)]
            assert content.active_transcript(session)["revision_id"] == edited
        finally:
            panel.close()
            panel.deleteLater()
            application.processEvents()


def test_queue_capacity_rejects_only_new_work_and_preserves_existing_jobs(tmp_path: Path) -> None:
    with Library(tmp_path / "library") as library, ContentStore(library) as content:
        session = _record(library)
        service = AIService(library, content, capacity=1)
        gate = _Provider(gated=True)
        try:
            first = service.transcribe(session, gate, config_key="first", resource_request=STT)
            assert gate.entered.wait(5)
            second = service.transcribe(
                session, _Provider(), config_key="second", resource_request=STT
            )
            with pytest.raises(StateConflict, match="AI_QUEUE_FULL_OR_JOB_NOT_READY"):
                service.transcribe(session, _Provider(), config_key="third", resource_request=STT)
            assert service.jobs.get(first).state.value == "RUNNING"
            assert service.jobs.get(second).state.value == "QUEUED"
            assert sorted(job.state.value for job in service.jobs.list_for_session(session)) == [
                "CANCELLED",
                "QUEUED",
                "RUNNING",
            ]
            gate.release.set()
            assert _finished(service, first).state.value == "SUCCEEDED"
            assert _finished(service, second).state.value == "SUCCEEDED"
        finally:
            gate.release.set()
            service.close()


@pytest.mark.parametrize("kind", ["stt", "summary"])
def test_simultaneous_duplicate_submission_preserves_one_execution(
    tmp_path: Path, kind: str
) -> None:
    with _service(tmp_path) as (_, content, service, session):
        if kind == "summary":
            content.create_transcript(session, [Segment("source-1", 0, 50, "Synthetic source")])
        barrier = threading.Barrier(2)

        class AdmissionBarrier(dict):
            def get(self, key, default=None):
                # Schedule both callers after an initially absent-key lookup;
                # equivalent to a thread switch before either marks admission.
                observed = super().get(key, default)
                try:
                    barrier.wait(timeout=0.25)
                except threading.BrokenBarrierError:
                    pass  # a serialized implementation need not admit both callers
                return observed

        service._session_jobs = AdmissionBarrier()
        provider = _Provider(gated=True)
        try:

            def submit():
                try:
                    return _submit(kind, service, session, provider)
                except StateConflict:
                    return None

            with ThreadPoolExecutor(max_workers=2) as workers:
                futures = [workers.submit(submit) for _ in range(2)]
                ids = [future.result(timeout=5) for future in futures]
            assert len(set(ids) - {None}) == 1
            job = next(value for value in ids if value is not None)
            assert service.jobs.get(job).state.value in {"RUNNING", "QUEUED"}
            assert provider.entered.wait(5)
            assert service.jobs.get(job).state.value == "RUNNING"
            provider.release.set()
            assert _finished(service, job).state.value == "SUCCEEDED"
            assert provider.calls == 1
        finally:
            provider.release.set()


@pytest.mark.parametrize("kind", ["stt", "summary"])
def test_local_publication_error_cannot_hide_observed_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    with _service(tmp_path) as (_, content, service, session):

        def publication_error(*args, **kwargs):
            raise StateConflict("INJECTED_LOCAL_PUBLICATION_FAILURE")

        monkeypatch.setattr(
            content, "publish_transcript" if kind == "stt" else "publish_summary", publication_error
        )
        provider = _Provider(unknown=True)
        result = _finished(service, _submit(kind, service, session, provider))
        assert (result.state.value, result.blocked_reason) == ("BLOCKED", "REMOTE_UNKNOWN")
        assert provider.calls == 1


@pytest.mark.parametrize("kind", ["stt", "summary"])
def test_remote_unknown_does_not_prevent_local_media_deletion_after_worker_ack(
    tmp_path: Path, kind: str
) -> None:
    with _service(tmp_path) as (library, _, service, session):
        provider = _Provider(unknown=True)
        job = _submit(kind, service, session, provider)
        assert _finished(service, job).blocked_reason == "REMOTE_UNKNOWN"
        service.cancel_session(session)
        service.runner.stop(timeout=5)  # explicit local worker ack; no media reader remains
        result = library.delete_session(session)
        assert result["state"] == "DELETED_LOCAL"
        assert not (library.root / "sessions" / session).exists()
        preserved = service.jobs.get(job)
        assert (preserved.state.value, preserved.blocked_reason) == ("BLOCKED", "REMOTE_UNKNOWN")
        assert provider.calls == 1  # deletion is independent of an external retry/settlement


def test_br13_07_gui_tick_cannot_wait_for_inflight_owner_handoff_lock(tmp_path: Path) -> None:
    """A helper idle in its model lane can still hold a lease in the AI runner."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from recoryn.models.ollama import ManagedOllama
    from recoryn.providers import LocalModelAttestation
    from recoryn.ui.ai_bridge import DesktopAI
    from recoryn.ui.models import ModelPanel

    app = QApplication.instance() or QApplication([])
    panel = ModelPanel(tmp_path / "model-list")
    owner = ManagedOllama()
    # Static synthetic proof avoids native listener/file/process access. Only the
    # production attestation lock and production GUI polling path are exercised.
    proof = LocalModelAttestation(
        "http://127.0.0.1:1/api/chat", "fake", "a" * 64, True, time.monotonic() + 60
    )
    owner._attestation = proof
    panel.ollama, panel._ollama_proof = owner, proof
    entered, release, heartbeat, forced = (threading.Event() for _ in range(4))

    def inflight_handoff() -> None:
        with owner._lock:
            entered.set()
            release.wait(3)

    def rescue_gui() -> None:
        # Release only our synthetic owner if the GUI cannot process its queued
        # heartbeat. This bounds the original defect without hanging pytest.
        if not heartbeat.wait(0.25):
            forced.set()
            release.set()

    worker = threading.Thread(target=inflight_handoff)
    rescuer = threading.Thread(target=rescue_gui)
    worker.start()
    assert entered.wait(3)
    bridge = DesktopAI.__new__(DesktopAI)
    bridge.window = SimpleNamespace(model_panel=panel, selected_session=lambda: None)
    bridge._live_tick = lambda: None
    try:
        assert panel.task is None
        QTimer.singleShot(0, heartbeat.set)
        rescuer.start()
        bridge.tick()
        app.processEvents()
        assert heartbeat.is_set()
        assert not forced.is_set(), "GUI tick waited for the owner's active network handoff lease"
    finally:
        release.set()
        worker.join(3)
        if rescuer.ident is not None:
            rescuer.join(3)
        panel.shutdown()
        panel.close()
        panel.deleteLater()
        app.processEvents()


def test_live_vad_checkpoint_restores_absolute_origin_and_keeps_edit(tmp_path: Path) -> None:
    """Silent sealed chunks count as processed; a restart does not reset source time."""
    fmt = AudioFormat(1000, 1)
    speech = b"\0\0" * 400 + b"\0\x40" * 200 + b"\0\0" * 400
    observed = []

    class Provider(_Provider):
        def transcribe(self, request, context=None):
            with wave.open(str(request.audio_path), "rb") as audio:
                observed.append((request.offset_ms, audio.readframes(audio.getnframes())))
            return super().transcribe(request, context)

    with Library(tmp_path / "library") as library, ContentStore(library) as store:
        recorder = RecordingService(library, {"mic": fmt}, chunk_frames=1000)
        recorder.start()
        session = recorder.session_id
        service, provider = AIService(library, store), Provider()

        def seal(stamp, payload):
            assert recorder.submit(
                PCMBlock(
                    session,
                    "mic",
                    recorder.epochs["mic"],
                    0,
                    fmt,
                    1000,
                    payload,
                    stamp,
                    stamp,
                    device_frame_position=0,
                )
            )
            recorder.pause()

        try:
            seal(1_000_000_000, speech)
            first = service.transcribe(
                session,
                provider,
                config_key="independent-vad",
                provisional=True,
                resource_request=STT,
            )
            assert _finished(service, first).state.value == "SUCCEEDED"
            assert observed == [(300, speech[600:1400])]
            assert (
                service.transcribe(
                    session,
                    provider,
                    config_key="independent-vad",
                    provisional=True,
                    resource_request=STT,
                )
                == first
            )
            draft = store.active_transcript(session)
            edited = store.edit_segment(
                session,
                draft["revision_id"],
                draft["segments"][0]["segment_id"],
                "user edit stays active",
                expected_active=draft["revision_id"],
            )
            assert store.select_transcript(session, edited, expected_active=draft["revision_id"])
            recorder.resume()
            seal(3_000_000_000, b"\0\0" * 1000)
            silence = service.transcribe(
                session,
                provider,
                config_key="independent-vad",
                provisional=True,
                resource_request=STT,
            )
            assert _finished(service, silence).state.value == "SUCCEEDED"
            checkpoint = store.transcript(service.jobs.get(silence).result_ref)["coverage"][
                "checkpoint"
            ]
            assert len(checkpoint["processed_chunk_ids"]) == 2 and len(observed) == 1
            service.close()
            service = AIService(library, store)
            recorder.resume()
            seal(5_000_000_000, speech)
            final = service.transcribe(
                session,
                provider,
                config_key="independent-vad",
                provisional=True,
                resource_request=STT,
            )
            assert _finished(service, final).state.value == "SUCCEEDED"
            assert [item[0] for item in observed] == [300, 4300]
            candidate = store.transcript(service.jobs.get(final).result_ref)
            assert candidate["coverage"]["checkpoint"]["resolved_origin_ns"] == 1_000_000_000
            assert len(candidate["coverage"]["checkpoint"]["processed_chunk_ids"]) == 3
            assert len(candidate["segments"]) == 2
            assert store.active_transcript(session)["revision_id"] == edited
            for chunk in library.chunks(session):
                pcm = library.root / chunk.relative_path / "audio.pcm"
                assert pcm.read_bytes() in (speech, b"\0\0" * 1000)
        finally:
            recorder.join_writer()
            service.close()


@pytest.mark.parametrize("kind", ["stt", "summary"])
def test_explicit_unknown_retry_preserves_old_job_without_automatic_resend(
    tmp_path: Path, kind: str
) -> None:
    with _service(tmp_path) as (_, _, service, session):
        provider = _Provider(unknown=True)
        old = _submit(kind, service, session, provider)
        assert _finished(service, old).blocked_reason == "REMOTE_UNKNOWN"
        assert _submit(kind, service, session, provider) == old and provider.calls == 1
        provider.unknown = False
        retry = (
            service.transcribe(
                session,
                provider,
                config_key="fixture-stt",
                request_nonce="user-new-plan",
                resource_request=STT,
            )
            if kind == "stt"
            else service.summarize(
                session,
                provider,
                config_key="fixture-summary",
                request_nonce="user-new-plan",
                resource_request=SUMMARY,
            )
        )
        assert retry != old and _finished(service, retry).state.value == "SUCCEEDED"
        assert service.jobs.get(old).blocked_reason == "REMOTE_UNKNOWN" and provider.calls == 2


def test_playback_verification_reader_blocks_delete_until_finally_ack(
    tmp_path: Path, monkeypatch
) -> None:
    from recoryn.ui.ai_bridge import DesktopAI

    with _service(tmp_path) as (library, content, service, session):
        job = service.transcribe(
            session, _Provider(), config_key="playback-snapshot", resource_request=STT
        )
        assert _finished(service, job).state.value == "SUCCEEDED"
        source = content.active_transcript(session)["coverage"]["source_ranges"][0]
        bridge = DesktopAI.__new__(DesktopAI)
        bridge.window = SimpleNamespace(library=library)
        bridge.service = service
        bridge.store = content
        entered, release = threading.Event(), threading.Event()
        checked = bridge._checked_playback_path

        def held(*args):
            entered.set()
            assert release.wait(3)
            return checked(*args)

        monkeypatch.setattr(bridge, "_checked_playback_path", held)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(bridge._verify_playback, session, source)
            try:
                assert entered.wait(3)
                result = library.delete_session(session)
                assert not result["deleted"] and result["state"] == "DELETE_PENDING"
                assert (library.root / "sessions" / session).exists()
            finally:
                release.set()
            with pytest.raises((StateConflict, KeyError)):
                future.result(timeout=3)
        assert library.delete_session(session)["deleted"]


@pytest.mark.parametrize("race", ["edit", "cancel", "bad_hash"])
def test_diarization_selection_preserves_parent_and_cas_with_fake_runtime(
    tmp_path: Path, monkeypatch, race: str
) -> None:
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from recoryn import diarization
    from recoryn.ui.main import MainWindow

    app = QApplication.instance() or QApplication([])
    entered, release, closed = (threading.Event() for _ in range(3))

    class Runtime:
        def __init__(self, config, model_evidence=None):
            assert model_evidence is not None and model_evidence.valid()  # G-P13
            self.config = config

        def diarize(self, request, context):
            entered.set()
            assert release.wait(3)
            return diarization.DiarizationResult(
                (diarization.SpeakerTurn(0, 100, "speaker_independent_0"),),
                True,
                audio_sha256="0" * 64
                if race == "bad_hash"
                else hashlib.sha256(request.audio_path.read_bytes()).hexdigest(),
                model_manifest_sha256=self.config.manifest_sha256,
                warnings=("ANONYMOUS_ESTIMATE",),
            )

        def close(self):
            closed.set()

    monkeypatch.setattr(diarization, "LocalDiarizationProcess", Runtime)
    with Library(tmp_path / "library") as library, ContentStore(library) as store:
        session = _record(library)
        _, clips = prepare_clips(library, session)
        clip = clips[0]
        parent = store.create_transcript(
            session,
            [Segment("line", 0, 100, "immutable text", track_id="mic")],
            coverage={
                "schema_version": 1,
                "planned": ["range"],
                "completed": ["range"],
                "failed": [],
                "missing": [],
                "source_ranges": [
                    {
                        "track_id": "mic",
                        "offset_ms": 0,
                        "duration_ms": 100,
                        "path": clip.path.relative_to(library.root).as_posix(),
                        "sha256": clip.sha256,
                        "ranges": list(clip.source_ranges),
                    }
                ],
            },
        )
        before = store.transcript(parent)
        window = MainWindow(library)
        window.timer.stop()
        bridge = window.ai_bridge
        bridge.panel.load(session)
        _approved_manifest(window, tmp_path / "synthetic-model")
        window.diarization_approval.setChecked(True)
        edited = None

        def spin(predicate):
            deadline = time.monotonic() + 4
            while not predicate() and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.001)
            assert predicate()

        try:
            bridge.diarize()
            spin(entered.is_set)
            if race == "edit":
                edited = store.edit_segment(
                    session, parent, "line", "user owns selection", expected_active=parent
                )
            elif race == "cancel":
                bridge.service.cancel_session(session)
            release.set()
            spin(
                lambda: (
                    bridge.service.jobs.list_for_session(session)[-1].state.value
                    in {"SUCCEEDED", "FAILED", "CANCELLED"}
                )
            )
            job = bridge.service.jobs.list_for_session(session)[-1]
            assert store.transcript(parent) == before and closed.is_set()
            if race == "edit":
                assert job.state.value == "SUCCEEDED"
                candidate = store.transcript(job.result_ref)
                assert candidate["parent_revision_id"] == parent
                assert candidate["segments"][0]["text"] == "immutable text"
                assert candidate["segments"][0]["speaker"] == "speaker_independent_0"
                assert candidate["coverage"]["checkpoint"]["diarization"]["anonymous_estimate"]
            else:
                assert job.state.value != "SUCCEEDED"
            assert store.active_transcript(session)["revision_id"] == (edited or parent)
        finally:
            release.set()
            spin(lambda: not bridge.busy)
            window.close()
            spin(lambda: window._closing)
            window.deleteLater()
            app.processEvents()


def test_failed_edit_refresh_and_explicit_retry_keep_input_and_new_active(tmp_path: Path) -> None:
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from recoryn.ui.content import ContentPanel

    app = QApplication.instance() or QApplication([])
    with Library(tmp_path / "library") as library, ContentStore(library) as store:
        library.create_session("editing")
        parent = store.create_transcript("editing", [Segment("line", 0, 100, "original")])
        panel = ContentPanel(store, lambda *args, **kwargs: False)
        try:
            panel.load("editing")
            panel.table.item(0, 1).setText("unsaved independent input")
            assert panel._unsaved_edit and not panel._edit_pending
            active = store.create_transcript(
                "editing", [Segment("later", 0, 100, "new result")], expected_active=parent
            )
            panel.load("editing")
            assert panel.table.item(0, 1).text() == "unsaved independent input"
            assert panel.revision["revision_id"] == parent and panel._expected_active == parent

            def save(action, done, *, failed=None):
                done(action())
                return True

            panel.operation = save
            panel._retry_edit()
            assert not panel._unsaved_edit
            assert panel.revision["parent_revision_id"] == parent
            assert panel.revision["segments"][0]["text"] == "unsaved independent input"
            assert panel.revision["segments"][0]["provenance"] == "user_assertion"
            assert store.active_transcript("editing")["revision_id"] == active
            assert store.transcript(parent)["segments"][0]["text"] == "original"
        finally:
            panel.close()
            panel.deleteLater()
            app.processEvents()


@pytest.mark.parametrize("race", ["stop", "replacement", "shutdown"])
@pytest.mark.parametrize("old_result", ["success", "failure"])
def test_late_attestation_result_cannot_restore_retired_privacy_proof(
    tmp_path: Path,
    monkeypatch,
    race: str,
    old_result: str,
) -> None:
    """GUI cache publication is separate from actual frozen dispatch authority."""
    import os
    import socket

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from recoryn.providers import LocalModelAttestation, ProviderError
    from recoryn.security import ConsentStore, CostLedger, SecurityError
    from recoryn.ui.models import ModelPanel
    from recoryn.ui.privacy import PrivacyPanel

    def no_network(*args, **kwargs):
        raise AssertionError("BR13 network forbidden")

    monkeypatch.setattr(socket, "getaddrinfo", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    app = QApplication.instance() or QApplication([])
    entered, release = threading.Event(), threading.Event()
    checks, leases, delivered = [], [], []
    local = "http://127.0.0.1:12345/api/chat"

    class Owner:
        def __init__(self, name):
            self.name, self.live = name, True

        @contextmanager
        def guard(self):
            if not self.live:
                raise ProviderError("LOCAL_EXECUTION_UNVERIFIED")
            leases.append(self.name)
            yield

        def attestation(self):
            checks.append((self.name, threading.get_ident()))
            if self.name == "retired":
                entered.set()
                assert release.wait(4)
                if old_result == "failure":
                    raise StateConflict("SYNTHETIC_OLD_OWNER_FAILURE")
                return old
            return newer

        def close(self):
            self.live = False

    class Connection:
        def write(self, data, timeout):
            delivered.append(data)

        def read(self, limit, timeout):
            return b""

        def close(self):
            pass

    class Transport:
        def open(self, *args):
            return Connection()

    retired, replacement = Owner("retired"), Owner("replacement")
    old = LocalModelAttestation(
        local, "fixed-model", "a" * 64, True, time.monotonic() + 60, lifetime_guard=retired.guard
    )
    # Same visible config/hash/endpoint; only the owner generation differs.
    newer = replace(old, lifetime_guard=replacement.guard)
    assert old == newer and old is not newer
    with ConsentStore(tmp_path / "policy.db") as policy, CostLedger(tmp_path / "cost.db") as ledger:
        vault = SimpleNamespace(get=no_network, set=no_network, delete=no_network)
        privacy = PrivacyPanel(
            policy, ledger, vault, gateway=Gateway(policy, transport=Transport())
        )
        privacy.select_session("retired-job")
        privacy._confirm_library = lambda *args: True
        privacy.controls["summary"].scope.setCurrentIndex(1)
        model = ModelPanel(tmp_path / "models")
        seen = []
        model.attestationChanged.connect(privacy.set_local_attestation)
        model.attestationChanged.connect(seen.append)
        controls = privacy.controls["summary"]
        controls.provider.setCurrentIndex(controls.provider.findData("ollama"))
        controls.context_window.setValue(8192)
        model.ollama = retired
        model._accept_proof(old, model._ollama_generation)
        privacy._action("summary", "grant")
        frozen = privacy.gateway_for("retired-job", kind="summary")
        assert frozen.request("ollama", local, "transcript", b"positive-control") == b""
        assert leases == ["retired"] * 3
        delivered.clear()
        seen.clear()

        def spin(predicate):
            deadline = time.monotonic() + 4
            while not predicate() and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.001)
            assert predicate()

        try:
            model.request_attestation_check()
            assert entered.wait(3)
            pending = model._attestation_task
            for _ in range(20):
                model.request_attestation_check()
                assert model.checked_attestation() is old
            assert model._attestation_task is pending and len(checks) == 1
            assert checks[0][1] != threading.get_ident()
            if race == "stop":
                model.stop_ollama()
            elif race == "replacement":
                model._invalidate_owned_proof()
                retired.live = False
                model.ollama = replacement
                model._accept_proof(newer, model._ollama_generation)
                privacy._action("summary", "grant")
            else:
                # Revoke synchronously, then let only our pending fake getter
                # finish while shutdown waits. Its queued GUI result arrives later.
                model.attestationChanged.connect(
                    lambda value: release.set() if model._shutdown_requested else None
                )
                model.shutdown()
            release.set()
            spin(lambda: model._attestation_task is None and model.task is None)
            assert all(value is not old for value in seen)
            with pytest.raises(SecurityError):
                frozen.request("ollama", local, "transcript", b"old-plan-must-stay-dead")
            assert delivered == []
            if race == "replacement":
                assert model.checked_attestation() is newer
                assert privacy._attestation is newer
                assert policy.allowed(
                    "ollama",
                    local,
                    "transcript",
                    scope=ConsentScope.library(),
                    request=_fixture_request(policy, "session", _fixture_feature("transcript"), 0),
                )
                fresh = privacy.gateway_for("replacement-job", kind="summary")
                assert fresh.request("ollama", local, "transcript", b"new-plan") == b""
                assert leases[-3:] == ["replacement"] * 3
                replacement.live = False
                with pytest.raises(SecurityError, match="LOCAL_EXECUTION_UNVERIFIED"):
                    fresh.request("ollama", local, "transcript", b"invalid-owner")
                assert delivered == [b"new-plan"]
            else:
                assert privacy._attestation is None and model._ollama_proof is None
                assert not policy.allowed(
                    "ollama",
                    local,
                    "transcript",
                    scope=ConsentScope.library(),
                    request=_fixture_request(policy, "session", _fixture_feature("transcript"), 0),
                )
        finally:
            release.set()
            model.shutdown()
            model.close()
            model.deleteLater()
            privacy.close()
            privacy.deleteLater()
            app.processEvents()


# The older tests exercise revocation/transport, with an explicitly chosen library
# grant. G02's separate cases exercise the default session-only permission.
def _fixture_request(
    policy: ConsentStore, session_id: str = "session", capability: str = "stt", generation: int = 0
) -> ConsentRequest:
    try:
        policy.bind_session(session_id, generation)
    except SecurityError:
        pass  # Registration grants nothing; the tested API still checks the fence.
    return ConsentRequest(session_id, generation, capability, 2)


def _fixture_feature(data_type: str) -> str:
    return "stt" if data_type == "audio" else "summary"


def _approved_manifest(window: Any, folder: Path) -> None:
    """G-P13 explicit approval fixture: a strictly valid synthetic manifest (not weights)
    entered in the window and recorded in its run registry with Yes and the license
    confirmation; the parent still re-verifies it right before sealing (no gate bypass)."""
    import hashlib as _hashlib
    import json as _json

    from recoryn.diarization import DiarizationConfig

    folder.mkdir(parents=True, exist_ok=True)
    models = {}
    for role in ("segmentation", "embedding"):
        data, license_bytes = b"synthetic-not-onnx-" + role.encode(), b"Synthetic license"
        (folder / f"{role}.onnx").write_bytes(data)
        (folder / f"LICENSE.{role}.txt").write_bytes(license_bytes)
        models[role] = {
            "file": f"{role}.onnx",
            "size": len(data),
            "sha256": _hashlib.sha256(data).hexdigest(),
            "license_id": "test-only",
            "license_url": "https://publisher.invalid/license",
            "license_file": f"LICENSE.{role}.txt",
            "license_sha256": _hashlib.sha256(license_bytes).hexdigest(),
        }
    manifest = folder / "manifest.json"
    manifest.write_text(
        _json.dumps(
            {
                "schema_version": 1,
                "runtime": "sherpa-onnx",
                "runtime_version": "2.0.1",
                "models": models,
            }
        ),
        encoding="utf-8",
    )
    digest = _hashlib.sha256(manifest.read_bytes()).hexdigest()
    window.diarization_manifest.setText(str(manifest))
    window.diarization_hash.setText(digest)
    snapshot = window.ai_bridge._diarization_snapshot(DiarizationConfig(manifest, digest, True))
    registry = window.model_panel.confirmations
    evidence = registry.confirm(
        snapshot, shown=registry.key(snapshot), accepted=True, acknowledged=True
    )
    assert evidence is not None
