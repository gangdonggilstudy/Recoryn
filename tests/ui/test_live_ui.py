from __future__ import annotations

import hashlib
import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from recoryn.app.desktop import DesktopRecorder, TrackSelection
from recoryn.domain import AudioFormat, PCMBlock, SessionState
from recoryn.providers import STTResult, TranscriptSegment
from recoryn.storage import Library
from recoryn.ui import ai_bridge
from recoryn.ui.main import MainWindow

pytestmark = pytest.mark.ui


def spin(app, predicate, *, timeout=5):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.001)
    app.processEvents()
    assert predicate()


class Source:
    def __init__(self):
        self.running = False

    def start(self, session, track, epoch, submit, on_health):
        self.running = True
        return AudioFormat(8000, 1)

    def stop(self, timeout=5):
        self.running = False


class Provider:
    def __init__(self):
        self.calls = []
        self.unknown = False

    def transcribe(self, request, context=None):
        self.calls.append(request.offset_ms)
        return STTResult(
            "fake",
            "local-model",
            (TranscriptSegment("line", request.offset_ms, request.offset_ms + 500, "fixture"),),
            not self.unknown,
            outcome_known=not self.unknown,
            error_code="REMOTE_OUTCOME_UNKNOWN" if self.unknown else None,
        )

    def close(self):
        pass


def confirm_model(window, snapshot):
    """G-P13 explicit approval fixture: the real snapshot recorded in this window's run
    registry with Yes and the responsibility check (no always-passing gate)."""
    registry = window.model_panel.confirmations
    evidence = registry.confirm(
        snapshot, shown=registry.key(snapshot), accepted=True, acknowledged=True
    )
    assert evidence is not None
    return evidence


def synthetic_manifest(folder):
    """A strictly valid synthetic diarization manifest (not model weights)."""
    import json

    folder.mkdir(parents=True, exist_ok=True)
    models = {}
    for role in ("segmentation", "embedding"):
        data, license_bytes = b"synthetic-not-onnx-" + role.encode(), b"Synthetic license"
        (folder / f"{role}.onnx").write_bytes(data)
        (folder / f"LICENSE.{role}.txt").write_bytes(license_bytes)
        models[role] = {
            "file": f"{role}.onnx",
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "license_id": "test-only",
            "license_url": "https://publisher.invalid/license",
            "license_file": f"LICENSE.{role}.txt",
            "license_sha256": hashlib.sha256(license_bytes).hexdigest(),
        }
    path = folder / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "runtime": "sherpa-onnx",
                "runtime_version": "2.0.1",
                "models": models,
            }
        ),
        encoding="utf-8",
    )
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def ui(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    provider = Provider()
    monkeypatch.setattr(ai_bridge, "LocalSTTProcess", lambda *args, **kwargs: provider)
    with Library(tmp_path / "library") as library:
        recorder = DesktopRecorder(library, lambda *args: Source())
        window = MainWindow(library, recorder=recorder)
        window.timer.stop()  # deterministic ticks rather than a wall-clock race
        model = tmp_path / "model"
        model.mkdir()
        for name in ("model.bin", "config.json", "tokenizer.json"):
            (model / name).write_bytes(b"synthetic-" + name.encode())
        window.local_model.setText(str(model))
        confirm_model(window, window.model_panel.model_snapshot(model))
        session = recorder.start((TrackSelection("mic", "fake", False, AudioFormat(8000, 1)),))
        recorder.recording.chunk_frames = 8000
        window.refresh_sessions()
        window.sessions.setCurrentRow(0)
        window._update_controls()
        try:
            yield app, window, provider, session
        finally:
            window.ai_bridge._preparation_cancel.set()
            spin(app, lambda: not window.ai_bridge.busy)
            window.close()
            spin(app, lambda: window._closing)
            window.deleteLater()
            app.processEvents()


def emit(window, stamp):
    recorder = window.recorder.recording
    assert recorder.submit(
        PCMBlock(
            recorder.session_id,
            "mic",
            recorder.epochs["mic"],
            0,
            AudioFormat(8000, 1),
            8000,
            b"\0\x40" * 8000,
            stamp,
            stamp,
            device_frame_position=0,
        )
    )
    window.recorder.pause()
    window._update_controls()


def wait_live(app, window, session):
    def done():
        window._tick()
        bridge = window.ai_bridge
        job = bridge._live_jobs.get(session)
        return (
            job is not None
            and not bridge.busy
            and bridge.service.jobs.get(job).state.value in {"SUCCEEDED", "FAILED", "BLOCKED"}
        )

    spin(app, done)


def test_live_ui_reads_fresh_sealed_chunks_and_keeps_origin_across_epochs(ui):
    app, window, provider, session = ui
    emit(window, 1_000_000_000)
    window.live_stt.setChecked(True)
    wait_live(app, window, session)
    original = [chunk.sha256 for chunk in window.library.chunks(session)]
    assert provider.calls == [0]
    for _ in range(5):
        window._tick()
    assert provider.calls == [0]
    window.recorder.resume()
    emit(window, 3_000_000_000)
    old_job = window.ai_bridge._live_jobs[session]
    spin(app, lambda: len(window.library.chunks(session)) == 2)
    spin(app, lambda: (window._tick(), window.ai_bridge._live_jobs.get(session) != old_job)[1])
    wait_live(app, window, session)
    assert provider.calls == [0, 2000]
    draft = window.ai_bridge.store.active_transcript(session)
    assert draft["kind"] == "draft" and not draft["complete"]
    assert len(draft["segments"]) == 2
    assert draft["coverage"]["checkpoint"]["resolved_origin_ns"] == 1_000_000_000
    assert window.library.chunks(session)[0].sha256 == original[0]


def test_slow_model_preparation_cannot_disable_or_delay_recording_stop(ui, monkeypatch):
    app, window, provider, session = ui
    emit(window, 1_000_000_000)
    window.recorder.resume()
    window._update_controls()
    entered, release = threading.Event(), threading.Event()

    def gated(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return provider

    monkeypatch.setattr(ai_bridge, "LocalSTTProcess", gated)
    window.ai_bridge._transcribe(session_id=session, provisional=True)
    try:
        # G-P11b: the model worker is created inside the owned lease on the AI runner,
        # never on the UI or recording path; the slow creation holds only that runner.
        spin(app, entered.is_set)
        runner = window.ai_bridge.service.runner
        assert runner.snapshot()["active"] and not window.busy
        assert window.stop_button.isEnabled()
        window.stop_recording()
        spin(app, lambda: not window.busy)
        assert window.library.get_session(session).state is SessionState.FINALIZED
        assert runner.snapshot()["active"]  # stop completed before the model was released
    finally:
        release.set()
        spin(app, lambda: not window.ai_bridge.busy)
        spin(app, lambda: not window.ai_bridge.service.runner.snapshot()["active"])


def test_unknown_live_job_never_retries_new_chunks_without_explicit_action(ui, monkeypatch):
    app, window, provider, session = ui
    provider.unknown = True
    emit(window, 1_000_000_000)
    window.live_stt.setChecked(True)
    wait_live(app, window, session)
    window._tick()
    assert session in window.ai_bridge._live_blocked
    window.recorder.resume()
    emit(window, 3_000_000_000)
    for _ in range(5):
        window._tick()
    assert provider.calls == [0]
    previous = window.ai_bridge._live_jobs[session]
    assert window.ai_bridge.service.jobs.get(previous).blocked_reason == "REMOTE_UNKNOWN"
    provider.unknown = False
    seen = []

    def approve(parent, title, body, buttons, default):
        seen.append((body, default))
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", approve)
    window.ai_bridge.retry_live()
    wait_live(app, window, session)
    assert "중복" in seen[0][0] and seen[0][1] == QMessageBox.StandardButton.No
    assert window.ai_bridge._live_jobs[session] != previous
    assert provider.calls == [0, 0, 2000]
    assert window.ai_bridge.service.jobs.get(previous).blocked_reason == "REMOTE_UNKNOWN"


def test_power_notice_waits_for_control_ack_and_wake_never_reopens_capture(ui):
    app, window, provider, session = ui
    emit(window, 1_000_000_000)
    window.recorder.resume()
    old_epochs = window.recorder.recording.epochs
    entered, release = threading.Event(), threading.Event()

    def busy_control():
        entered.set()
        assert release.wait(5)

    window.operation(busy_control)
    try:
        spin(app, entered.is_set)
        window._power_event("suspend")
        window._power_event("resume")
        assert window._pending_suspend
        assert window.library.get_session(session).state is SessionState.RECORDING
    finally:
        release.set()
    spin(app, lambda: not window.busy and not window._pending_suspend)
    assert window.library.get_session(session).state is SessionState.PAUSED
    assert window.power.resume_required
    for _ in range(3):
        window._power_event("resume")
    assert window.recorder.recording.epochs == old_epochs
    window._tick()
    assert window.meters["mic"].value() == 0
    window.pause_resume()
    spin(app, lambda: not window.busy)
    assert window.recorder.recording.epochs != old_epochs
    assert not window.power.resume_required


def test_deleting_current_finalized_session_releases_polling_and_close_handles(ui, monkeypatch):
    app, window, provider, session = ui
    emit(window, 1_000_000_000)
    window.recorder.stop()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    window.delete_selected()
    spin(app, lambda: not window.busy)
    assert window.recorder.recording is None
    assert window.library.list_sessions() == []
    window._tick()
    assert window.record_button.isEnabled()


def test_delete_pending_keeps_visible_reason_and_retries_hidden_session_after_reader_ack(
    ui, monkeypatch
):
    app, window, provider, session = ui
    emit(window, 1_000_000_000)
    window.recorder.stop()
    jobs = window.ai_bridge._service().jobs
    job = jobs.create("pending-reader", "synthetic")
    jobs.bind_session(job.job_id, session)
    attempt = jobs.claim(job.job_id, "controlled-reader")
    jobs.reader_started(attempt)
    jobs.fail(
        job.job_id, attempt.attempt_id, attempt.fence, "REMOTE_OUTCOME_UNKNOWN", outcome_known=False
    )
    chunk = window.library.chunks(session)[0]
    path = window.library.root / chunk.relative_path / "audio.pcm"
    original = path.read_bytes()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    try:
        window.delete_selected()
        spin(app, lambda: not window.busy)
        assert not window.library.list_sessions()
        assert path.read_bytes() == original
        assert session in window._pending_deletions and window.retry_delete_button.isEnabled()
        for _ in range(3):
            window._tick()
        assert (
            "삭제 대기" in window.warning.text()
            and "원본 제거 보류" in window.deletion_status.text()
        )
        window.retry_pending_deletions()
        spin(app, lambda: not window.busy)
        assert path.read_bytes() == original and session in window._pending_deletions
        jobs.reader_finished(attempt)
        window.retry_pending_deletions()
        spin(app, lambda: not window.busy)
        assert not path.exists() and session not in window._pending_deletions
        assert not window.retry_delete_button.isEnabled()
        assert "삭제 완료" in window.deletion_status.text()
        assert jobs.get(job.job_id).blocked_reason == "REMOTE_UNKNOWN"
    finally:
        jobs.reader_finished(attempt)


def test_playback_verifies_derived_and_original_hashes_before_player(ui, monkeypatch):
    app, window, provider, session = ui
    emit(window, 1_000_000_000)
    window.recorder.stop()
    window.ai_bridge.transcribe()
    spin(app, lambda: not window.ai_bridge.busy)
    service = window.ai_bridge.service
    spin(app, lambda: service.jobs.list_for_session(session)[-1].state.value == "SUCCEEDED")
    revision = window.ai_bridge.store.active_transcript(session)
    source = revision["coverage"]["source_ranges"][0]
    path = window.library.root / source["path"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == source["sha256"]
    played = []
    monkeypatch.setattr(window.ai_bridge, "_play", lambda *args: played.append(args))
    window.ai_bridge.seek("mic", 0, revision["revision_id"])
    spin(app, lambda: not window.ai_bridge.busy)
    # L01 D7: the player receives the exact verified PCM, not a path to reopen later.
    import wave

    with wave.open(str(path), "rb") as clip:
        expected = (clip.getframerate(), clip.getnchannels(), clip.readframes(clip.getnframes()))
    assert len(played) == 1 and len(played[0]) == 1
    pcm = played[0][0]
    assert (pcm.sample_rate, pcm.channels, pcm.payload) == expected and pcm.start_frame == 0
    saved = path.read_bytes()
    path.write_bytes(saved[:-2] + b"!!")
    window.ai_bridge.seek("mic", 0, revision["revision_id"])
    spin(app, lambda: not window.ai_bridge.busy)
    assert len(played) == 1
    path.write_bytes(saved)
    chunk = window.library.chunks(session)[0]
    original = window.library.root / chunk.relative_path / "audio.pcm"
    original.write_bytes(b"!!" + original.read_bytes()[2:])
    window.ai_bridge.seek("mic", 0, revision["revision_id"])
    spin(app, lambda: not window.ai_bridge.busy)
    assert len(played) == 1


@pytest.mark.parametrize("race", ["none", "edit", "cancel"])
def test_optional_diarization_publishes_new_scoped_revision_and_preserves_parent(
    ui, monkeypatch, race
):
    import wave

    from recoryn import diarization

    app, window, stt, session = ui
    emit(window, 1_000_000_000)
    window.recorder.stop()
    bridge = window.ai_bridge
    bridge.transcribe()
    spin(app, lambda: not bridge.busy)
    spin(app, lambda: bridge.service.jobs.list_for_session(session)[-1].state.value == "SUCCEEDED")
    parent = bridge.store.active_transcript(session)
    bridge.panel.load(session)
    source_hashes = [chunk.sha256 for chunk in window.library.chunks(session)]
    entered, release, closed = threading.Event(), threading.Event(), threading.Event()

    class FakeDiarization:
        def __init__(self, config, model_evidence=None):
            self.config = config
            assert model_evidence is not None and model_evidence.valid()

        def diarize(self, request, context):
            with wave.open(str(request.audio_path), "rb") as audio:
                assert (audio.getframerate(), audio.getnchannels(), audio.getsampwidth()) == (
                    16000,
                    1,
                    2,
                )
                assert audio.getnframes() == 16000
            entered.set()
            assert release.wait(5)
            return diarization.DiarizationResult(
                (diarization.SpeakerTurn(0, 1000, "speaker_fixture_1", "mic"),),
                True,
                audio_sha256=hashlib.sha256(request.audio_path.read_bytes()).hexdigest(),
                model_manifest_sha256=self.config.manifest_sha256,
                warnings=("ANONYMOUS_ESTIMATE",),
            )

        def close(self):
            closed.set()

    monkeypatch.setattr(diarization, "LocalDiarizationProcess", FakeDiarization)
    manifest, digest = synthetic_manifest(window.library.root / "fake-diarization")
    window.diarization_manifest.setText(str(manifest))
    window.diarization_hash.setText(digest)
    confirm_model(
        window,
        bridge._diarization_snapshot(diarization.DiarizationConfig(manifest, digest, True)),
    )
    bridge.diarize()
    assert not entered.is_set() and not bridge.busy  # no implicit license or CPU approval
    window.diarization_approval.setChecked(True)
    bridge.diarize()
    edited = None
    try:
        spin(app, entered.is_set)
        spin(app, lambda: not bridge.busy)
        if race == "edit":
            segment = parent["segments"][0]
            edited = bridge.store.edit_segment(
                session,
                parent["revision_id"],
                segment["segment_id"],
                "User assertion wins",
                expected_active=parent["revision_id"],
            )
        elif race == "cancel":
            bridge.cancel()
            spin(
                app,
                lambda: (
                    bridge.service.jobs.list_for_session(session)[-1].state.value
                    == "CANCEL_REQUESTED"
                ),
            )
    finally:
        release.set()
    spin(
        app,
        lambda: (
            bridge.service.jobs.list_for_session(session)[-1].state.value
            in {"SUCCEEDED", "CANCELLED", "FAILED"}
        ),
    )
    job = bridge.service.jobs.list_for_session(session)[-1]
    assert closed.is_set()
    assert bridge.store.transcript(parent["revision_id"]) == parent
    assert [chunk.sha256 for chunk in window.library.chunks(session)] == source_hashes
    active = bridge.store.active_transcript(session)
    if race == "cancel":
        assert job.state.value == "CANCELLED"
        assert active["revision_id"] == parent["revision_id"]
    else:
        assert job.state.value == "SUCCEEDED"
        candidate = bridge.store.transcript(job.result_ref)
        assert candidate["parent_revision_id"] == parent["revision_id"]
        assert candidate["segments"][0]["text"] == parent["segments"][0]["text"]
        assert candidate["segments"][0]["speaker"] == "speaker_fixture_1"
        scope = candidate["coverage"]["checkpoint"]["diarization"]
        assert scope["complete"] and scope["anonymous_estimate"]
        assert scope["range"] == parent["coverage"]["source_ranges"][0]
        assert scope["manifest_sha256"] == digest  # the configured manifest (G-P13 fixture)
        assert active["revision_id"] == (edited if race == "edit" else candidate["revision_id"])
