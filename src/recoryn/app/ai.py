"""Bounded AI orchestration with immutable partial results and atomic completion."""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable
from dataclasses import asdict, replace
from types import TracebackType
from typing import Any, Literal
from uuid import uuid4

from recoryn.app.media import prepare_clips
from recoryn.content import Claim, ContentStore, Segment
from recoryn.domain import SessionState, StateConflict, ValidationError
from recoryn.jobs import AttemptRecord, JobRecord, JobStore
from recoryn.models import ResourceRequest, ResourceScheduler, plan_static
from recoryn.providers import (
    ChunkSummary,
    ExecutionContext,
    ProgressEvent,
    ProviderError,
    SegmentSpan,
    STTProvider,
    STTRequest,
    SummaryCheckpoint,
    SummaryClaim,
    SummaryProvider,
    SummaryRequest,
    TranscriptSegment,
)
from recoryn.security.cost import CostRequest
from recoryn.storage import Library
from recoryn.storage._safe import safe_path
from recoryn.storage.chunks import scan_prefix, verify_bundle


def _key(parts: object) -> str:
    return hashlib.sha256(
        json.dumps(parts, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _coverage(
    planned: list[str], completed: list[str], failed: list[str] | None = None
) -> dict[str, Any]:
    failures = failed or []
    return {
        "schema_version": 1,
        "planned": planned,
        "completed": completed,
        "failed": failures,
        "missing": [item for item in planned if item not in completed and item not in failures],
    }


class _OutcomeGuard:
    """A later local fence error cannot erase an observed unknown remote outcome."""

    def __init__(self) -> None:
        self.known = True

    def __enter__(self) -> _OutcomeGuard:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> Literal[False]:
        if error is not None and isinstance(error, Exception) and not self.known:
            raise ProviderError("REMOTE_OUTCOME_UNKNOWN", outcome_known=False) from None
        return False


class AIService:
    def __init__(self, library: Library, content: ContentStore, *, capacity: int = 8) -> None:
        from recoryn.jobs.runner import BoundedRunner

        self.library, self.content = library, content
        self.jobs = JobStore(library.db_path)
        self.jobs.recover_abandoned(coordinator_exclusive=True)
        self.runner = BoundedRunner(self.jobs, capacity=capacity, workers=1, owner="desktop-ai")
        self.scheduler = ResourceScheduler()
        self._progress_lock = threading.Lock()
        self._progress: dict[str, ProgressEvent] = {}
        self._session_jobs: dict[str, set[str]] = {}
        self._admission_lock = threading.RLock()
        self._admitted: set[str] = set()
        # The resource intent each admitted attempt runs with (G-P11a). A merged
        # duplicate never overwrites it; an explicit continue replaces it.
        self._resource_requests: dict[str, ResourceRequest] = {}
        self._closed = False
        self.runner.on_admission_refused = self._admission_refused
        self.runner.start()

    def _admission_refused(self, job_id: str) -> None:
        # No attempt/read/send was admitted. A later explicit request must build
        # fresh bindings and pass the canonical authority again, using the same
        # durable QUEUED intent rather than being merged with an absent worker.
        with self._admission_lock:
            self._admitted.discard(job_id)

    def _admit(
        self,
        session_id: str,
        kind: str,
        input_key: str,
        *,
        expected_job_id: str | None = None,
        expected_job_version: int | None = None,
    ) -> tuple[JobRecord, bool, bool]:
        with self._admission_lock:
            if self._closed:
                raise StateConflict("AI_SERVICE_CLOSED")
            if expected_job_id is not None:
                job = self.jobs.get(expected_job_id)
                if (
                    expected_job_version is None
                    or job.kind != kind
                    or job.input_key != input_key
                    or job.job_id
                    not in {item.job_id for item in self.jobs.list_for_session(session_id)}
                ):
                    raise StateConflict("CONTINUE_PLAN_CHANGED")
                job = self.jobs.resume(job.job_id, expected_version=expected_job_version)
                self._admitted.discard(job.job_id)
                created = False
            else:
                if expected_job_version is not None:
                    raise StateConflict("CONTINUE_PLAN_CHANGED")
                requested = uuid4().hex
                job = self.jobs.create(kind, input_key, job_id=requested)
                created = job.job_id == requested
            self.jobs.bind_session(job.job_id, session_id)
            group = self._session_jobs.get(session_id)
            if group is None:
                group = set()
                self._session_jobs[session_id] = group
            group.add(job.job_id)
            runnable = job.state.value in {"QUEUED", "BACKOFF"}
            if not runnable or job.job_id in self._admitted:
                return job, False, created
            self._admitted.add(job.job_id)
            return job, True, created

    @staticmethod
    def _admit_resources(request: object, kind: str) -> ResourceRequest:
        """Static admission before any Job, read or send (contract G11 section 3.2).

        The request is required: a direct caller cannot bypass the device policy the
        UI checks. A refusal raises before the Job exists, so it is a preparation block
        (G-P07 'not admitted'), never a fabricated attempt.
        """
        if type(request) is not ResourceRequest or request.kind != kind:
            raise ValidationError("INVALID_RESOURCE_REQUEST")
        plan_static(request)
        return request

    def _capture(self, job_id: str, request: ResourceRequest) -> None:
        with self._admission_lock:
            self._resource_requests[job_id] = request

    def admit_diarization(self, request: object) -> ResourceRequest:
        """The diarization bridge creates its own Job; it passes the same static
        admission first (contract G11 section 6) and captures the request afterwards."""
        return self._admit_resources(request, "diarization")

    def capture_diarization(self, job_id: str, request: ResourceRequest) -> None:
        if self.jobs.get(job_id).kind != "diarization":
            raise ValidationError("INVALID_RESOURCE_REQUEST")
        self._capture(job_id, self._admit_resources(request, "diarization"))

    def resource_request(self, job_id: str) -> ResourceRequest | None:
        """The resource intent captured when this service last admitted the Job."""
        with self._admission_lock:
            return self._resource_requests.get(job_id)

    def _submit(
        self,
        job: JobRecord,
        task: Callable[[AttemptRecord, threading.Event], str],
        *,
        created: bool,
    ) -> None:
        try:
            accepted = self.runner.submit(job.job_id, task)
        except Exception:
            with self._admission_lock:
                self._admitted.discard(job.job_id)
            raise
        if not accepted:
            with self._admission_lock:
                self._admitted.discard(job.job_id)
            if created:
                self.jobs.cancel(job.job_id)
            # Only our newly created, refused request can be cancelled. A
            # deduplicated existing Job retains its durable intent and fence.
            raise StateConflict("AI_QUEUE_FULL_OR_JOB_NOT_READY")

    def _observe(self, job_id: str, event: ProgressEvent) -> None:
        with self._progress_lock:
            self._progress[job_id] = event

    def progress(self) -> dict[str, ProgressEvent]:
        with self._progress_lock:
            return dict(self._progress)

    def _execution_context(
        self, attempt: AttemptRecord, cancel: threading.Event, supplied: ExecutionContext
    ) -> ExecutionContext:
        original = supplied.reservation_factory

        def reserve(request: CostRequest) -> str | None:
            if original is None:
                return None
            reservation_id = original(request)
            if reservation_id is not None:
                # This commits before the provider can call Gateway. A crash
                # anywhere after this point cannot blindly resend the attempt.
                self.jobs.mark_remote_intent(attempt, reservation_id)
            return reservation_id

        return ExecutionContext(
            cancel=cancel,
            headers=supplied.headers,
            reservation_factory=reserve if original is not None else None,
            progress=lambda event: self._observe(attempt.job_id, event),
        )

    def transcribe(
        self,
        session_id: str,
        provider: STTProvider,
        *,
        config_key: str,
        resource_request: ResourceRequest,
        language: str | None = None,
        provisional: bool = False,
        context_factory: Callable[[threading.Event], ExecutionContext] | None = None,
        chunk_ids: frozenset[str] | None = None,
        origin_ns: int | None = None,
        request_nonce: str | None = None,
        expected_job_id: str | None = None,
        expected_job_version: int | None = None,
    ) -> str:
        resources = self._admit_resources(resource_request, "stt")
        state = self.library.get_session(session_id).state
        if not provisional and state != SessionState.FINALIZED:
            raise StateConflict("TRANSCRIPTION_REQUIRES_FINALIZED_AUDIO")
        # Snapshot only descriptors here. Expensive checks/VAD/WAV conversion run
        # inside the bounded runner's durable local-reader lease, not UI/control.
        chunks = self.library.chunks(session_id)
        if chunk_ids is not None:
            chunks = [chunk for chunk in chunks if chunk.chunk_id in chunk_ids]
        if not chunks:
            raise StateConflict("TRANSCRIPTION_AUDIO_EMPTY")
        fixed_ids = frozenset(chunk.chunk_id for chunk in chunks)
        snapshot = _key([chunk.to_dict() for chunk in chunks])
        # Capture the selected ID and its version in one read; a later move away and
        # back to the same ID changes the version and keeps this result a candidate.
        selection = self.content.selection_state(session_id)
        expected_version = selection["transcript_version"]
        active = (
            self.content.transcript(selection["transcript_id"])
            if selection["transcript_id"]
            else None
        )
        expected = active["revision_id"] if active else None
        if active and active["kind"] == "edited":
            # Automatic results remain selectable candidates, never replace edits.
            expected = uuid4().hex
        job, admitted, created = self._admit(
            session_id,
            "streaming_transcription" if provisional else "transcription",
            _key(
                [session_id, snapshot, origin_ns, config_key, language, provisional, request_nonce]
            ),
            expected_job_id=expected_job_id,
            expected_job_version=expected_job_version,
        )
        if not admitted:
            return job.job_id
        self._capture(job.job_id, resources)
        scope = {"config_key": config_key, "language": language, "origin_ns": origin_ns}

        def task(attempt: AttemptRecord, cancel: threading.Event) -> str:
            plan_static(resources)  # dispatch re-check of the captured backend policy
            base: dict[str, Any] | None = None
            if provisional:
                for candidate in reversed(self.content.list_revisions(session_id, "transcript")):
                    checkpoint = candidate.get("coverage", {}).get("checkpoint", {})
                    if (
                        candidate["kind"] == "draft"
                        and checkpoint.get("stream_scope") == scope
                        and checkpoint.get("stream_complete") is True
                    ):
                        base = candidate
                        break
            old = base["coverage"] if base else _coverage([], [])
            seen = set(old.get("checkpoint", {}).get("processed_chunk_ids", []))
            fresh = fixed_ids - seen if provisional else fixed_ids
            if cancel.is_set():
                raise ProviderError("CANCELLED")
            effective_origin = origin_ns
            checkpoint = old.get("checkpoint", {})
            if provisional and origin_ns is None:
                if "resolved_origin_ns" in checkpoint:
                    effective_origin = checkpoint["resolved_origin_ns"]
                else:
                    # Resolve once under this task's durable reader lease. The
                    # control/UI lane never reads original bundles to plan AI.
                    stamps = []
                    for chunk in chunks:
                        if cancel.is_set():
                            raise ProviderError("CANCELLED")
                        bundle = safe_path(self.library.root, chunk.relative_path)
                        if verify_bundle(bundle) != chunk:
                            raise ProviderError("RESULT_INVALID")
                        for record in scan_prefix(bundle, strict=True).blocks:
                            meta = record["metadata"]
                            if (
                                meta["capture_mono_ns"] is not None
                                and meta["clock_quality"] in {"DEVICE_CORRELATED", "SYNTHETIC"}
                                and "TIMESTAMP_ERROR" not in meta["flags"]
                            ):
                                stamps.append(meta["capture_mono_ns"])
                    effective_origin = min(stamps) if stamps else None
            _, clips = (
                prepare_clips(
                    self.library,
                    session_id,
                    chunk_ids=frozenset(fresh),
                    origin_ns=effective_origin,
                    speech_only=provisional,
                )
                if fresh
                else (snapshot, ())
            )
            if cancel.is_set():
                raise ProviderError("CANCELLED")
            segments = [Segment(**item) for item in base["segments"]] if base else []
            completed = list(old["completed"])
            failed = list(old["failed"])
            planned = list(old["planned"])
            sources = list(old.get("source_ranges", []))
            units = [_key([clip.track_id, clip.epoch_id, clip.source_ranges]) for clip in clips]
            planned.extend(unit for unit in units if unit not in planned)
            # Silence is an explicitly processed sealed unit, not an STT request.
            if fresh and not clips:
                silence = ["silence-" + chunk for chunk in sorted(fresh)]
                planned.extend(silence)
                completed.extend(silence)
            sources.extend(
                {
                    "clip": unit,
                    "track_id": clip.track_id,
                    "offset_ms": clip.offset_ms,
                    "duration_ms": clip.duration_ms,
                    "path": clip.path.relative_to(self.library.root).as_posix(),
                    "sha256": clip.sha256,
                    "ranges": list(clip.source_ranges),
                }
                for unit, clip in zip(units, clips, strict=True)
            )
            all_ids = seen | fixed_ids if provisional else fixed_ids
            audio_snapshot = _key(
                [
                    item.to_dict()
                    for item in self.library.chunks(session_id)
                    if item.chunk_id in all_ids
                ]
            )
            expected_active = expected
            selected = self.content.active_transcript(session_id)
            if provisional and selected:
                if base and selected["revision_id"] == base["revision_id"]:
                    expected_active = base["revision_id"]
                else:
                    expected_active = uuid4().hex

            def coverage(complete: bool) -> dict[str, Any]:
                value = _coverage(planned, completed, failed)
                value["source_ranges"] = sources
                if provisional:
                    value["checkpoint"] = {
                        "stream_scope": scope,
                        "resolved_origin_ns": effective_origin,
                        "stream_complete": complete,
                        "processed_chunk_ids": sorted(all_ids if complete else seen),
                    }
                return value

            with self.scheduler.acquire(cancel), _OutcomeGuard() as observed:
                for unit, clip in zip(units, clips, strict=True):
                    if cancel.is_set():
                        raise ProviderError("CANCELLED")
                    if clip.offset_ms is None:
                        failed.append(unit)
                        continue
                    supplied = (
                        context_factory(cancel)
                        if context_factory
                        else ExecutionContext(cancel=cancel)
                    )
                    result = provider.transcribe(
                        STTRequest(
                            clip.path,
                            language=language,
                            offset_ms=clip.offset_ms,
                            track_id=clip.track_id,
                            audio_revision_id=audio_snapshot,
                        ),
                        self._execution_context(attempt, cancel, supplied),
                    )
                    observed.known = observed.known and result.outcome_known
                    if cancel.is_set() or result.complete and not observed.known:
                        raise ProviderError(
                            "CANCELLED" if observed.known else "REMOTE_OUTCOME_UNKNOWN",
                            outcome_known=observed.known,
                        )
                    ids = {segment.segment_id for segment in segments}
                    for item in result.segments:
                        identifier = item.segment_id
                        if provisional or identifier in ids:
                            identifier = _key([unit, identifier])
                        if identifier in ids:
                            continue
                        segments.append(
                            Segment(
                                identifier,
                                item.start_ms,
                                item.end_ms,
                                item.text,
                                item.speaker,
                                item.provenance,
                                track_id=clip.track_id,
                                timing_quality=item.timing_quality,
                            )
                        )
                        ids.add(identifier)
                    segments.sort(key=lambda item: (item.start_ms, item.end_ms, item.segment_id))
                    (completed if result.complete else failed).append(unit)
                    partial = self.content.publish_transcript(
                        self.jobs,
                        attempt,
                        session_id,
                        segments,
                        complete=False,
                        kind="draft",
                        expected_active=expected_active,
                        audio_revision_id=audio_snapshot,
                        parent_revision_id=base["revision_id"] if base else None,
                        coverage=coverage(False),
                        expected_transcript_version=expected_version,
                    )
                    selected = self.content.active_transcript(session_id)
                    if selected and selected["revision_id"] == partial:
                        expected_active = partial
                    self._observe(
                        job.job_id,
                        ProgressEvent("clips", len(completed) + len(failed), len(planned), "clips"),
                    )
                    if not result.complete:
                        raise ProviderError(
                            result.error_code or "TRANSCRIPTION_PARTIAL",
                            outcome_known=result.outcome_known,
                        )
                if failed:
                    self.content.publish_transcript(
                        self.jobs,
                        attempt,
                        session_id,
                        segments,
                        complete=False,
                        kind="draft",
                        expected_active=expected_active,
                        audio_revision_id=audio_snapshot,
                        coverage=coverage(False),
                        expected_transcript_version=expected_version,
                    )
                    raise ProviderError("CAPTURE_CLOCK_UNVERIFIED")
                return self.content.publish_transcript(
                    self.jobs,
                    attempt,
                    session_id,
                    segments,
                    complete=True,
                    kind="draft" if provisional else "corrected",
                    expected_active=expected_active,
                    audio_revision_id=audio_snapshot,
                    parent_revision_id=base["revision_id"] if base else None,
                    coverage=coverage(True),
                    expected_transcript_version=expected_version,
                )

        self._submit(job, task, created=created)
        return job.job_id

    def summarize(
        self,
        session_id: str,
        provider: SummaryProvider,
        *,
        config_key: str,
        resource_request: ResourceRequest,
        template: str = "meeting",
        context_factory: Callable[[threading.Event], ExecutionContext] | None = None,
        request_nonce: str | None = None,
        expected_job_id: str | None = None,
        expected_job_version: int | None = None,
    ) -> str:
        resources = self._admit_resources(resource_request, "summary")
        transcript = self.content.active_transcript(session_id)
        if not transcript or not transcript["complete"]:
            raise StateConflict("SUMMARY_REQUIRES_COMPLETE_TRANSCRIPT")
        revision_id = transcript["revision_id"]
        request = SummaryRequest(
            revision_id,
            tuple(
                TranscriptSegment(
                    **{
                        **{
                            key: value
                            for key, value in item.items()
                            if key in TranscriptSegment.__dataclass_fields__
                        },
                        "track_id": item.get("track_id") or "audio",
                    }
                )
                for item in transcript["segments"]
            ),
            template=template,
        )
        for candidate in reversed(self.content.list_revisions(session_id, "summary")):
            checkpoint = candidate.get("coverage", {}).get("checkpoint")
            if (
                not candidate["complete"]
                and candidate["transcript_revision_id"] == revision_id
                and candidate["template"] == template
                and isinstance(checkpoint, dict)
                and checkpoint.get("config_key") == config_key
            ):
                value = checkpoint["value"]
                restored = SummaryCheckpoint(
                    value["plan_digest"],
                    tuple(
                        ChunkSummary(
                            item["chunk_id"],
                            tuple(
                                SummaryClaim(
                                    claim["text"],
                                    tuple(claim["segment_ids"]),
                                    claim["status"],
                                    claim["basis"],
                                )
                                for claim in item["claims"]
                            ),
                            tuple(SegmentSpan(**span) for span in item["coverage"]),
                        )
                        for item in value["completed"]
                    ),
                )
                request = replace(request, checkpoint=restored)
                break
        settings_key = _key([config_key, template])
        job, admitted, created = self._admit(
            session_id,
            "summarization",
            _key([session_id, revision_id, config_key, template, request_nonce]),
            expected_job_id=expected_job_id,
            expected_job_version=expected_job_version,
        )
        if not admitted:
            # A request merged into an existing job is still the user's latest
            # request. That job is not ours, so a failure here leaves it running.
            self.content.request_summary_settings(session_id, settings_key)
            return job.job_id
        try:
            # A request refused before admission records nothing. Record before
            # capturing, so an older job finishing in between stays a candidate.
            self.content.request_summary_settings(session_id, settings_key)
            selection = self.content.selection_state(session_id)
        except Exception:
            with self._admission_lock:
                self._admitted.discard(job.job_id)
            if created:
                self.jobs.cancel(job.job_id)
            raise
        self._capture(job.job_id, resources)
        expected_summary = selection["summary_id"]

        def task(attempt: AttemptRecord, cancel: threading.Event) -> str:
            plan_static(resources)  # dispatch re-check of the captured backend policy
            with self.scheduler.acquire(cancel), _OutcomeGuard() as observed:
                supplied = (
                    context_factory(cancel) if context_factory else ExecutionContext(cancel=cancel)
                )
                execution = self._execution_context(attempt, cancel, supplied)
                result = provider.summarize(request, execution)
                observed.known = observed.known and result.outcome_known
                if cancel.is_set() or result.complete and not observed.known:
                    raise ProviderError(
                        "CANCELLED" if observed.known else "REMOTE_OUTCOME_UNKNOWN",
                        outcome_known=observed.known,
                    )
                claims = [Claim(item.text, item.segment_ids, item.status) for item in result.claims]

                def unit(item: Any) -> str:
                    return f"{item.segment_id}:{item.start_char}:{item.end_char}"

                completed = [unit(item) for item in result.coverage]
                missing = [unit(item) for item in result.missing]
                coverage = _coverage(completed + missing, completed)
                coverage["checkpoint"] = {
                    "config_key": config_key,
                    "value": asdict(result.checkpoint),
                }
                revision = self.content.publish_summary(
                    self.jobs,
                    attempt,
                    session_id,
                    revision_id,
                    claims,
                    complete=result.complete,
                    template=template,
                    expected_transcript=revision_id,
                    expected_summary=expected_summary,
                    coverage=coverage,
                    expected_transcript_version=selection["transcript_version"],
                    expected_summary_version=selection["summary_version"],
                    settings_key=settings_key,
                )
                if not result.complete:
                    raise ProviderError(
                        result.error_code or "SUMMARY_PARTIAL",
                        outcome_known=result.outcome_known,
                    )
                return revision

        self._submit(job, task, created=created)
        return job.job_id

    def cancel_session(self, session_id: str) -> None:
        for job in self.jobs.list_for_session(session_id):
            self.runner.cancel(job.job_id)

    def snapshot(self) -> dict[str, Any]:
        with self._admission_lock:
            identifiers = tuple(job_id for ids in self._session_jobs.values() for job_id in ids)
        return {
            "runner": self.runner.snapshot(),
            "progress": {key: asdict(value) for key, value in self.progress().items()},
            "jobs": [asdict(self.jobs.get(job_id)) for job_id in identifiers],
        }

    def close(self) -> None:
        with self._admission_lock:
            self._closed = True
        self.runner.stop(timeout=5)
        self.jobs.close()
