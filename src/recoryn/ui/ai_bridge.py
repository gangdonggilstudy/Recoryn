"""Connect Qt actions to recording-independent AI and local source playback."""

from __future__ import annotations

import hashlib
import threading
import wave
from collections.abc import Callable
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import uuid4

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QMessageBox

from recoryn.app.ai import AIService
from recoryn.app.inference import LocalSTTProcess
from recoryn.content import ContentStore, Segment
from recoryn.domain import AudioFormat, StateConflict
from recoryn.jobs import JobStore
from recoryn.providers import ExecutionContext, ProviderError
from recoryn.storage._coordination import root_mutex
from recoryn.storage._safe import mkdir, open_file, safe_path
from recoryn.storage.chunks import verify_bundle
from recoryn.ui.content import ContentPanel
from recoryn.ui.pcm_playback import PlaybackPcm, SinkPlayback, prepare_playback
from recoryn.ui.tasks import Task


class DesktopAI:
    def __init__(self, window: Any) -> None:
        self.window = window
        self.store = ContentStore(window.library)
        self._history = JobStore(window.library.db_path)
        self.service: AIService | None = None
        self.local: LocalSTTProcess | None = None
        self.local_key: str | None = None
        # L01 D7: Recoryn plays verified PCM itself; no Qt media decoder backend.
        self.playback = SinkPlayback(window, on_error=self._report_playback)
        self._playback_generation = 0
        self.pool = QThreadPool(window)
        self.pool.setMaxThreadCount(1)
        self.busy = False
        self._tasks: set[Task] = set()
        self._shutting_down = False
        self._preparation_cancel = threading.Event()
        self._live_jobs: dict[str, str] = {}
        self._live_snapshots: dict[str, frozenset[str]] = {}
        self._live_blocked: set[str] = set()
        self._live_nonces: dict[str, str] = {}
        self.panel = ContentPanel(self.store, self.operation)
        window.tabs.addTab(self.panel, "전사 · 요약 · 근거")
        self.panel.transcribeRequested.connect(self.transcribe)
        self.panel.summarizeRequested.connect(self.summarize)
        self.panel.cancelRequested.connect(self.cancel)
        self.panel.retryTranscribeRequested.connect(self.retry_transcribe)
        self.panel.retrySummaryRequested.connect(self.retry_summary)
        self.panel.diarizeRequested.connect(self.diarize)
        self.panel.seekRequested.connect(self.seek)
        self._last_snapshot = ""
        self.privacy: Any = None

    def operation(
        self,
        action: Callable[[], Any],
        done: Callable[[Any], None] | None = None,
        *,
        failed: Callable[[str], None] | None = None,
    ) -> bool:
        """AI preparation and editing never occupy the recording control lane."""
        if self.busy or self._shutting_down:
            return False
        self.busy = True
        task = Task(action)
        self._tasks.add(task)

        def finished(value: Any) -> None:
            self._tasks.discard(task)
            self.busy = False
            if not self._shutting_down and done:
                done(value)

        def failure(code: str) -> None:
            self._tasks.discard(task)
            self.busy = False
            if not self._shutting_down:
                if failed:
                    failed(code)
                self.panel.job_status.setText("AI 작업 중단: " + code + " · 원본은 보존됩니다.")

        task.signals.finished.connect(finished)
        task.signals.failed.connect(failure)
        self.pool.start(task)
        return True

    def attach_privacy(self, panel: Any) -> None:
        self.privacy = panel
        self.window.tabs.addTab(panel, "제공업체 · 동의 · 비용")

    def _service(self) -> AIService:
        if self.service is None:
            self.service = AIService(self.window.library, self.store)
        return self.service

    def selection(self, session_id: str) -> None:
        self.panel.load(session_id)

    @staticmethod
    def _context_factory(context: ExecutionContext) -> Any:
        def create(cancel: threading.Event) -> ExecutionContext:
            return ExecutionContext(
                cancel=cancel,
                headers=context.headers,
                reservation_factory=context.reservation_factory,
            )

        return create

    def transcribe(self) -> None:
        self._transcribe()

    def _transcribe(
        self, *, session_id: str | None = None, provisional: bool = False, retry: bool = False
    ) -> None:
        window = self.window
        session_id = session_id or window.selected_session()
        if session_id is None or self.busy or self._shutting_down:
            return
        fixed_session = session_id
        chunks = frozenset(item.chunk_id for item in window.library.chunks(session_id))
        if provisional and (not chunks or self._live_snapshots.get(session_id) == chunks):
            return
        try:
            config = self.privacy.provider_config("stt") if self.privacy else None
            context = (
                self.privacy.execution_context("stt", threading.Event())
                if self.privacy and config is not None and config.provider_id != "faster_whisper"
                else ExecutionContext()
            )
            config_key = self.privacy.config_key("stt") if self.privacy else "local"
            gateway = (
                self.privacy.gateway_for(session_id, kind="stt")
                if self.privacy and config is not None and config.provider_id != "faster_whisper"
                else None
            )
        except Exception:
            self.panel.job_status.setText("전사 제공업체·권한·예산 설정을 확인하세요.")
            if provisional:
                self._live_blocked.add(session_id)
            return
        model, policy = window.local_model.text(), window.device_policy.currentText()
        preparation_cancel = threading.Event()
        self._preparation_cancel = preparation_cancel
        nonce = uuid4().hex if retry else self._live_nonces.get(session_id) if provisional else None

        def check_cancel() -> None:
            if preparation_cancel.is_set():
                raise StateConflict("CANCELLED")

        def submit() -> str:
            check_cancel()
            service = self._service()
            options: dict[str, Any] = {
                "provisional": provisional,
                "chunk_ids": chunks,
                "request_nonce": nonce,
            }
            if config is None or config.provider_id == "faster_whisper":
                if not model:
                    raise StateConflict("LOCAL_MODEL_REQUIRED")
                from recoryn.models import ResourceScheduler, probe_gpus

                hasher = hashlib.sha256()
                for name in ("model.bin", "config.json", "tokenizer.json"):
                    with open_file(Path(model).absolute() / name, "rb") as stream:
                        while block := stream.read(1024 * 1024):
                            check_cancel()
                            hasher.update(block)
                digest = hasher.hexdigest()
                from recoryn.transcription import cuda_runtime_available

                # L01 D9: without a CUDA-capable CTranslate2 no GPU is a candidate.
                gpu_ready = policy != "CPU_ONLY" and cuda_runtime_available()
                _, gpus = probe_gpus() if gpu_ready else ("UNAVAILABLE", ())
                # Runtime adapter currently binds GPU zero; do not budget another GPU.
                device, _ = ResourceScheduler().choose(
                    policy, 1024 * 2**20, tuple(gpu for gpu in gpus if gpu.index == 0)
                )
                key = digest + ":" + device
                if self.local_key != key:
                    activity = service.runner.snapshot()
                    if activity["active"] or activity["pending"]:
                        raise StateConflict("AI_MODEL_CHANGE_REQUIRES_IDLE")
                    if self.local:
                        self.local.close()
                    self.local = LocalSTTProcess(Path(model).absolute(), device=device)
                    self.local_key = key
                assert self.local is not None
                check_cancel()
                return service.transcribe(fixed_session, self.local, config_key=key, **options)
            from recoryn.transcription import GeminiTranscriber, OpenAITranscriber

            adapter = OpenAITranscriber if config.provider_id == "openai" else GeminiTranscriber
            assert gateway is not None
            provider = adapter(gateway, config)
            check_cancel()
            return service.transcribe(
                fixed_session,
                provider,
                config_key=config_key,
                context_factory=self._context_factory(context),
                **options,
            )

        def submitted(job_id: str) -> None:
            if provisional:
                self._live_jobs[fixed_session] = job_id
                self._live_snapshots[fixed_session] = chunks
            self.panel.job_status.setText(
                ("임시 전사" if provisional else "전체 정정 전사") + " 작업 등록: " + job_id[:12]
            )

        self.operation(
            submit,
            submitted,
            failed=lambda code: self._live_blocked.add(fixed_session) if provisional else None,
        )

    def summarize(self, template: str, *, retry: bool = False) -> None:
        window = self.window
        session_id = window.selected_session()
        if session_id is None or self.busy or self.privacy is None:
            self.panel.job_status.setText("요약 제공업체와 데이터 범위를 설정하세요.")
            return
        try:
            if (
                self.window.model_panel.ollama_owned
                and self.privacy.controls["summary"].provider.currentData() == "ollama"
            ):
                self.window.model_panel.checked_attestation()
            config = self.privacy.provider_config("summary")
            context = self.privacy.execution_context("summary", threading.Event())
            config_key = self.privacy.config_key("summary")
            gateway = self.privacy.gateway_for(session_id, kind="summary")
        except Exception:
            self.panel.job_status.setText("요약 제공업체·권한·예산 설정을 확인하세요.")
            return
        nonce = uuid4().hex if retry else None
        preparation_cancel = threading.Event()
        self._preparation_cancel = preparation_cancel

        def submit() -> str:
            if preparation_cancel.is_set():
                raise StateConflict("CANCELLED")
            from recoryn.summarization import (
                AnthropicSummarizer,
                GeminiSummarizer,
                OllamaSummarizer,
                OpenAISummarizer,
            )

            adapters = {
                "ollama": OllamaSummarizer,
                "openai": OpenAISummarizer,
                "anthropic": AnthropicSummarizer,
                "gemini": GeminiSummarizer,
            }
            provider = adapters[config.provider_id](gateway, config)
            if preparation_cancel.is_set():
                raise StateConflict("CANCELLED")
            return self._service().summarize(
                session_id,
                provider,
                config_key=config_key,
                template=template,
                context_factory=self._context_factory(context),
                request_nonce=nonce,
            )

        self.operation(
            submit, lambda job_id: self.panel.job_status.setText("요약 작업 등록: " + job_id[:12])
        )

    def _confirm_retry(self) -> bool:
        return (
            QMessageBox.question(
                self.window,
                "새 AI 작업으로 명시 재실행",
                "이전 결과·취소·원격 UNKNOWN 이력을 유지한 채 새 작업을 실행합니다. "
                "원격 처리와 비용이 미확인이라면 중복 처리·과금이 발생할 수 있습니다. "
                "현재 권한과 새 비용 예약을 검사하여 실행할까요?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            == QMessageBox.StandardButton.Yes
        )

    def retry_transcribe(self) -> None:
        if not self.busy and self._confirm_retry():
            self._transcribe(retry=True)

    def retry_summary(self, template: str) -> None:
        if not self.busy and self._confirm_retry():
            self.summarize(template, retry=True)

    def retry_live(self) -> None:
        session = self.window.recorder.session_id
        if session and not self.busy and self._confirm_retry():
            self._live_blocked.discard(session)
            self._live_jobs.pop(session, None)
            self._live_snapshots.pop(session, None)
            self._live_nonces[session] = uuid4().hex
            self.window.live_stt.setChecked(True)

    def diarize(self) -> None:
        """Annotate one explicit source range through the existing fenced runner."""
        if self.busy or self.panel.revision is None:
            return
        revision = deepcopy(self.panel.revision)
        source = deepcopy(self.panel.diarization_ranges.currentData())
        if not revision["complete"] or source is None:
            self.panel.job_status.setText(
                "전체 정정/편집 전사와 시간 매핑이 있는 구간을 선택하세요."
            )
            return
        if not self.window.diarization_approval.isChecked():
            self.panel.job_status.setText(
                "AI 설정에서 로컬 모델 manifest·SHA256·라이선스·CPU 사용을 확인하세요."
            )
            return
        from recoryn.diarization import DiarizationConfig

        try:
            config = DiarizationConfig(
                Path(self.window.diarization_manifest.text()).absolute(),
                self.window.diarization_hash.text().strip(),
                license_accepted=True,
            )
        except Exception:
            self.panel.job_status.setText("화자 분리 manifest 경로와 신뢰한 SHA256을 확인하세요.")
            return
        selected = self.store.active_transcript(revision["session_id"])
        expected = selected["revision_id"] if selected else None
        if expected != revision["revision_id"]:
            expected = uuid4().hex  # browsing an old revision produces a candidate
        preparation_cancel = threading.Event()
        self._preparation_cancel = preparation_cancel

        def submit() -> str:
            if preparation_cancel.is_set():
                raise StateConflict("CANCELLED")
            service = self._service()
            job = service.jobs.create("diarization", uuid4().hex)
            service.jobs.bind_session(job.job_id, revision["session_id"])

            def task(attempt: Any, cancel: threading.Event) -> str:
                from recoryn.diarization import (
                    DiarizationRequest,
                    LocalDiarizationProcess,
                    assign_speakers,
                )

                with service.scheduler.acquire(cancel):
                    if cancel.is_set():
                        raise ProviderError("CANCELLED")
                    path = self._checked_playback_path(revision["session_id"], source)
                    derived = self._diarization_audio(revision["session_id"], path, cancel)
                    digest = hashlib.sha256(derived.read_bytes()).hexdigest()
                    request = DiarizationRequest(derived, source["offset_ms"], source["track_id"])
                    provider = LocalDiarizationProcess(config)
                    try:
                        result = provider.diarize(request, ExecutionContext(cancel=cancel))
                    finally:
                        provider.close()
                    if cancel.is_set() or not result.complete:
                        raise ProviderError(result.error_code or "CANCELLED")
                    if (
                        result.audio_sha256 != digest
                        or result.model_manifest_sha256 != config.manifest_sha256
                    ):
                        raise ProviderError("RESULT_INVALID")
                    segments = assign_speakers(
                        tuple(Segment(**segment) for segment in revision["segments"]), result.turns
                    )
                    coverage = deepcopy(revision["coverage"])
                    checkpoint = coverage.setdefault("checkpoint", {})
                    checkpoint["diarization"] = {
                        "range": source,
                        "audio_path": derived.relative_to(self.window.library.root).as_posix(),
                        "audio_sha256": digest,
                        "manifest_sha256": config.manifest_sha256,
                        "device": "cpu",
                        "algorithm": "equal-channel-downmix-linear-resample-v1",
                        "complete": True,
                        "anonymous_estimate": True,
                        "warnings": list(result.warnings),
                        "turns": [asdict(turn) for turn in result.turns],
                    }
                    return self.store.publish_transcript(
                        service.jobs,
                        attempt,
                        revision["session_id"],
                        segments,
                        kind=revision["kind"],
                        parent_revision_id=revision["revision_id"],
                        expected_active=expected,
                        audio_revision_id=revision.get("audio_revision_id"),
                        coverage=coverage,
                    )

            if not service.runner.submit(job.job_id, task):
                service.jobs.cancel(job.job_id)
                raise StateConflict("AI_QUEUE_FULL_OR_JOB_NOT_READY")
            return job.job_id

        self.operation(
            submit,
            lambda job: self.panel.job_status.setText(
                "선택 구간 익명 화자 추정 등록: " + job[:12] + " · 원문·기존 버전은 보존됩니다."
            ),
        )

    def _diarization_audio(self, session_id: str, path: Path, cancel: threading.Event) -> Path:
        from recoryn.audio import decode_pcm, downmix_mono, encode_pcm, resample_linear

        with open_file(path, "rb") as stream, wave.open(stream, "rb") as audio:
            fmt = AudioFormat(audio.getframerate(), audio.getnchannels())
            frames = audio.getnframes()
            if (
                audio.getsampwidth() != 2
                or frames <= 0
                or frames * 1000 > fmt.sample_rate * 300_000
                or frames * fmt.frame_bytes > 8 * 1024 * 1024
            ):
                raise ProviderError("DIARIZATION_INPUT_TOO_LARGE")
            payload = audio.readframes(frames)
        mono = downmix_mono(decode_pcm(payload, fmt))
        samples = resample_linear(mono, fmt.sample_rate, 16000)
        if cancel.is_set():
            raise ProviderError("CANCELLED")
        library = self.window.library
        output = safe_path(
            library.root, "sessions", session_id, "derived", "speaker-" + uuid4().hex
        )
        with root_mutex(library.root):
            library.get_session(session_id)
            mkdir(output)
        destination = safe_path(output, "audio.wav")
        with open_file(destination, "xb") as stream, wave.open(stream, "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(
                encode_pcm(tuple((sample,) for sample in samples), AudioFormat(16000, 1))
            )
        return destination

    def cancel(self) -> None:
        self._preparation_cancel.set()
        self.window.live_stt.setChecked(False)
        session_id = self.window.selected_session()
        if self.service is not None and session_id is not None:
            service = self.service
            # Queue the durable cancel on the independent AI lane even while
            # cooperative preparation is unwinding. Recording stop stays free.
            task = Task(lambda: service.cancel_session(session_id))
            self._tasks.add(task)
            task.signals.finished.connect(lambda value: self._tasks.discard(task))
            task.signals.failed.connect(lambda code: self._tasks.discard(task))
            self.pool.start(task)
            self.panel.job_status.setText(
                "취소 요청됨 · 로컬 종료 확인과 원격 UNKNOWN은 별도로 표시됩니다."
            )

    def before_delete(self, session_id: str) -> None:
        if self.privacy is not None:
            self.privacy.consents.revoke_session(session_id)
        else:
            from recoryn.security import ConsentStore

            with ConsentStore(self.window.library.root / "security.sqlite") as consent:
                consent.revoke_session(session_id)
        if self.service is not None:
            self.service.cancel_session(session_id)

    def stop_playback(self) -> None:
        self._playback_generation += 1
        self.playback.stop()

    def seek(self, track_id: str, position_ms: int, revision_id: str) -> None:
        revision = self.store.transcript(revision_id)
        ranges = revision.get("coverage", {}).get("source_ranges", [])
        target = next(
            (
                item
                for item in ranges
                if item["track_id"] == track_id
                and item["offset_ms"] is not None
                and item["offset_ms"] <= position_ms < item["offset_ms"] + item["duration_ms"]
            ),
            None,
        )
        if target is None:
            self.panel.status.setText("이 버전에는 재생 가능한 정확한 원본 매핑이 없습니다.")
            return
        if self.busy:
            return
        generation = self._playback_generation

        def play(pcm: PlaybackPcm) -> None:
            if generation != self._playback_generation:
                return
            self.window.library.get_session(revision["session_id"])
            self._play(pcm)

        self.operation(
            lambda: self._verify_playback(
                revision["session_id"], target, position_ms - target["offset_ms"]
            ),
            play,
        )

    def _verify_playback(
        self, session_id: str, target: dict[str, Any], position_ms: int = 0
    ) -> PlaybackPcm:
        service = self._service()
        job = service.jobs.create("playback_verification", uuid4().hex)
        service.jobs.bind_session(job.job_id, session_id)
        attempt = service.jobs.claim(job.job_id, "desktop-playback")
        service.jobs.reader_started(attempt)
        try:
            path = self._checked_playback_path(session_id, target)
            # Still under the reader lease: the bytes that play are the verified ones.
            pcm = prepare_playback(path, target["sha256"], position_ms)
            service.jobs.complete(job.job_id, attempt.attempt_id, attempt.fence, str(path))
            return pcm
        except Exception:
            service.jobs.fail(
                job.job_id, attempt.attempt_id, attempt.fence, "PLAYBACK_SOURCE_INVALID"
            )
            raise
        finally:
            service.jobs.reader_finished(attempt)

    def _checked_playback_path(self, session_id: str, target: dict[str, Any]) -> Path:
        library = self.window.library
        library.get_session(session_id)  # deletion intent prevents new playback
        path = safe_path(library.root, target["path"])
        expected_root = library.root / "sessions" / session_id / "derived"
        if not path.is_relative_to(expected_root) or path.suffix != ".wav":
            raise StateConflict("PLAYBACK_SOURCE_INVALID")
        digest = hashlib.sha256()
        with open_file(path, "rb") as stream:
            while part := stream.read(256 * 1024):
                digest.update(part)
        if digest.hexdigest() != target.get("sha256"):
            raise StateConflict("PLAYBACK_SOURCE_INVALID")
        chunks = {item.chunk_id: item for item in library.chunks(session_id)}
        total = 0
        for source in target.get("ranges", []):
            chunk = chunks.get(source["chunk_id"])
            if (
                chunk is None
                or chunk.track_id != target["track_id"]
                or verify_bundle(safe_path(library.root, chunk.relative_path)) != chunk
                or source["output_frame_start"] != total
                or source["frame_count"] <= 0
                or source["source_chunk_frame_start"] < 0
                or source["source_chunk_frame_start"] + source["frame_count"] > chunk.frame_count
            ):
                raise StateConflict("PLAYBACK_SOURCE_INVALID")
            total += source["frame_count"]
        with open_file(path, "rb") as stream, wave.open(stream, "rb") as audio:
            if not total or audio.getnframes() != total:
                raise StateConflict("PLAYBACK_SOURCE_INVALID")
        library.get_session(session_id)
        return path

    def _play(self, pcm: PlaybackPcm) -> None:
        try:
            self.playback.start(pcm)
        except StateConflict as exc:
            self._report_playback(str(exc))

    def _report_playback(self, code: str) -> None:
        # Start failures and failures after starting (L04-D04) are both shown.
        self.panel.status.setText("재생할 수 없습니다: " + code + " · 원본은 보존됩니다.")

    def tick(self) -> None:
        self.window.model_panel.request_attestation_check()
        session_id = self.window.selected_session()
        if session_id:
            jobs = self._history.list_for_session(session_id)
            key = str([asdict(job) for job in jobs])
            if key != self._last_snapshot:
                if not self.busy and not self.window.busy:
                    self._last_snapshot = key
                    self.panel.load(session_id)
                if jobs:
                    job = jobs[-1]
                    self.panel.job_status.setText(
                        f"AI: {job.state.value} · {job.error_code or job.blocked_reason or ''}"
                        + (
                            " · 원격 처리·비용 미확인, 자동 재전송 없음. 명시 재실행만 가능합니다."
                            if job.blocked_reason == "REMOTE_UNKNOWN"
                            else ""
                        )
                    )
        self._live_tick()

    def _live_tick(self) -> None:
        session = self.window.recorder.session_id
        if (
            not session
            or not self.window.live_stt.isChecked()
            or self.busy
            or self.window.busy
            or self._shutting_down
            or session in self._live_blocked
        ):
            return
        from recoryn.domain import SessionState

        if self.window.library.get_session(session).state not in {
            SessionState.RECORDING,
            SessionState.PAUSED,
        }:
            return
        previous = self._live_jobs.get(session)
        if previous is None and session not in self._live_nonces:
            interrupted = any(
                job.kind == "streaming_transcription" and job.state.value != "SUCCEEDED"
                for job in self._history.list_for_session(session)
            )
            if interrupted:
                self._live_blocked.add(session)
                self.panel.job_status.setText(
                    "미완료 임시 전사 이력 · 자동 재전송 없음. 새 작업으로 명시 재개하세요."
                )
                return
        if previous and self.service is not None:
            job = self.service.jobs.get(previous)
            if job.state.value == "SUCCEEDED":
                pass
            elif job.state.value in {"FAILED", "CANCELLED", "BLOCKED"}:
                self._live_blocked.add(session)
                self.panel.job_status.setText(
                    "임시 전사 중단 · "
                    + (job.blocked_reason or job.error_code or job.state.value)
                    + " · 자동 재전송하지 않습니다. 명시 재개를 선택하세요."
                )
                return
            else:
                return
        self._transcribe(session_id=session, provisional=True)

    def close(self) -> None:
        self._shutting_down = True
        self._preparation_cancel.set()
        if not self.pool.waitForDone(5000):
            raise StateConflict("INFERENCE_ACK_PENDING")
        if self.service:
            self.service.close()
        if self.local:
            self.local.close()
        self.store.close()
        self._history.close()
