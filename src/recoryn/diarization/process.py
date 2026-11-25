"""Bounded owned child and byte-only result IPC for optional offline inference."""

from __future__ import annotations

import importlib.metadata
import multiprocessing
import os
import platform
import sys
import threading
import time
from dataclasses import asdict
from typing import Any

from recoryn.domain import ValidationError
from recoryn.providers import ExecutionContext, ProviderError
from recoryn.storage._safe import canonical, strict_json

from ._job import ChildJob
from .backend import audio_snapshot, compute
from .contracts import DiarizationConfig, DiarizationRequest, DiarizationResult, SpeakerTurn

_MAX_REPLY = 1024 * 1024
_PINS = {"sherpa-onnx": "2.0.1", "onnx": "1.23.2", "numpy": "2.3.5"}


def _platform_supported() -> bool:
    return (
        sys.platform == "win32"
        and sys.version_info >= (3, 12)
        and platform.machine() in ("AMD64", "x86_64")
    )


def _worker(
    config: DiarizationConfig,
    request: DiarizationRequest,
    audio_hash: str,
    gate: Any,
    cancel: Any,
    reply: Any,
    bundle: Any = None,
) -> None:
    # The owner must attach its OS lifetime guard before this gate opens.
    try:
        if not gate.wait(10) or cancel.is_set():
            return
        os.environ.update(
            {"HF_HUB_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1", "DO_NOT_TRACK": "1"}
        )
        try:
            result = compute(config, request, cancel, audio_hash, bundle)
        except ProviderError as error:
            result = DiarizationResult((), False, error.code == "CANCELLED", error.code)
        except Exception:
            result = DiarizationResult((), False, error_code="DIARIZATION_PROCESS_FAILED")
        encoded = canonical(asdict(result))
        if len(encoded) <= _MAX_REPLY:
            reply.send_bytes(encoded)
    finally:
        reply.close()


def _decode(
    data: bytes, request: DiarizationRequest, duration: int, audio_hash: str, manifest_hash: str
) -> DiarizationResult:
    try:
        value = strict_json(data, limit=_MAX_REPLY)
        if set(value) != {
            "turns",
            "complete",
            "cancelled",
            "error_code",
            "audio_sha256",
            "model_manifest_sha256",
            "warnings",
        } or not isinstance(value["turns"], list):
            raise ValueError
        value["turns"] = tuple(SpeakerTurn(**turn) for turn in value["turns"])
        value["warnings"] = tuple(value["warnings"])
        result = DiarizationResult(**value)
        if result.complete and (
            result.audio_sha256 != audio_hash
            or result.model_manifest_sha256 != manifest_hash
            or "ANONYMOUS_ESTIMATE" not in result.warnings
            or any(
                turn.track_id != request.track_id
                or not request.offset_ms
                <= turn.start_ms
                < turn.end_ms
                <= request.offset_ms + duration
                for turn in result.turns
            )
        ):
            raise ValueError
        return result
    except (ProviderError, ValidationError, TypeError, ValueError, KeyError):
        raise ProviderError("DIARIZATION_RESULT_INVALID") from None


class LocalDiarizationProcess:
    """One bounded invocation at a time; close is final and waits for owned-child ACK."""

    def __init__(
        self,
        config: DiarizationConfig,
        *,
        model_evidence: Any = None,
        bundle_parent: Any = None,
    ) -> None:
        """``model_evidence`` is the run's confirmation of these strictly verified bytes
        (G-P13); without it the object is created but no child or loader is started."""
        if not isinstance(config, DiarizationConfig):
            raise ProviderError("DIARIZATION_INPUT_INVALID")
        self.config = config
        self.model_evidence = model_evidence
        self.bundle_parent = bundle_parent
        self._bundle: Any = None  # sealed only while this owned child may read it
        self.bundle_cleanup_pending = False
        self._lock = threading.Lock()
        self._closed = threading.Event()
        self._process: Any = None
        self._reply: Any = None
        self._guard: ChildJob | None = None
        self._cancel: Any = None

    def is_live(self) -> bool:
        """Lock-free: whether the owned child still exists (Library may ask under its mutex)."""
        child = self._process
        try:
            return child is not None and child.pid is not None and bool(child.is_alive())
        except (ValueError, OSError):
            return False

    def device_facts(self) -> dict[str, Any]:
        """The fixed CPU-only backend this configuration runs (sherpa-onnx CPU provider)."""
        return {"device": self.config.device, "device_index": None, "compute_type": "float32"}

    def capabilities(self) -> dict[str, Any]:
        # Distribution metadata only: no optional import, file/model probe or network.
        dependencies = {}
        for name, pin in _PINS.items():
            try:
                dependencies[name] = (
                    "installed" if importlib.metadata.version(name) == pin else "unsupported"
                )
            except importlib.metadata.PackageNotFoundError:
                dependencies[name] = "missing"
        supported = _platform_supported()
        return {
            "provider_id": "sherpa_onnx",
            "diarization": supported
            and all(state == "installed" for state in dependencies.values()),
            "platform_supported": supported,
            "dependencies": dependencies,
            "runtime_version": "2.0.1",
            "devices": ("cpu",),
            "audio_formats": ("wav_s16le_mono_16000",),
            "max_audio_ms": self.config.max_audio_ms,
            "anonymous_only": True,
            "uncertain": True,
            "streaming": False,
            "model_state": "not_checked",
            "quality_validation": "NOT_RUN",
        }

    def diarize(
        self, request: DiarizationRequest, context: ExecutionContext | None = None
    ) -> DiarizationResult:
        if not isinstance(request, DiarizationRequest):
            raise ProviderError("DIARIZATION_INPUT_INVALID")
        execution = context or ExecutionContext()
        deadline = time.monotonic() + self.config.timeout_seconds
        acquired = False
        try:
            while not acquired:
                self._check(execution, deadline)
                acquired = self._lock.acquire(timeout=0.02)
            self._check(execution, deadline)
            # An earlier failed shutdown must be acknowledged before a new child exists.
            self._reap()
            if not self.config.license_accepted:
                raise ProviderError("DIARIZATION_LICENSE_REQUIRED")
            capabilities = self.capabilities()
            if not capabilities["platform_supported"]:
                raise ProviderError("DIARIZATION_PLATFORM_UNSUPPORTED")
            states = capabilities["dependencies"].values()
            if "missing" in states:
                raise ProviderError("DEPENDENCY_MISSING")
            if "unsupported" in states:
                raise ProviderError("DEPENDENCY_VERSION_UNSUPPORTED")
            _, duration, audio_hash = audio_snapshot(request, self.config.max_audio_ms)
            self._check(execution, deadline)
            self._bundle = self._seal(execution)
            self._check(execution, deadline)
            spawn = multiprocessing.get_context("spawn")
            gate, cancel = spawn.Event(), spawn.Event()
            self._cancel = cancel
            self._guard = ChildJob()
            self._reply, sender = spawn.Pipe(duplex=False)
            try:
                self._process = spawn.Process(
                    target=_worker,
                    args=(
                        self.config,
                        request,
                        audio_hash,
                        gate,
                        cancel,
                        sender,
                        self._bundle.description(),
                    ),
                    name="recoryn-diarization",
                    daemon=True,
                )
                self._process.start()
            finally:
                sender.close()
            self._guard.attach(self._process.pid)
            self._check(execution, deadline)
            gate.set()
            while True:
                self._check(execution, deadline)
                if self._reply.poll(0.02):
                    result = _decode(
                        self._reply.recv_bytes(_MAX_REPLY),
                        request,
                        duration,
                        audio_hash,
                        self.config.manifest_sha256,
                    )
                    self._check(execution, deadline)
                    # A reply is provisional until our child and handles are
                    # acknowledged. Cancellation/timeout also cover this wait.
                    self._reap()
                    self._check(execution, deadline)
                    return result
                if not self._process.is_alive():
                    raise ProviderError("DIARIZATION_PROCESS_FAILED")
        except ProviderError as error:
            return DiarizationResult((), False, error.code == "CANCELLED", error.code)
        except Exception:
            return DiarizationResult((), False, error_code="DIARIZATION_PROCESS_FAILED")
        finally:
            if acquired:
                try:
                    self._reap()
                finally:
                    self._lock.release()

    def _seal(self, execution: ExecutionContext) -> Any:
        """Right before native: re-verify the original strictly, compare it with the
        confirmed snapshot and seal exactly those bytes (G13 §5.2-6)."""
        from recoryn.models._artifact_io import ArtifactError, acquire, diarization_snapshot

        from .models import verified_bundle

        evidence = self.model_evidence
        if evidence is None or not evidence.valid():
            raise ArtifactError("CAPABILITY_UNSUPPORTED", "MODEL_CONFIRMATION_REQUIRED")
        files, terms = verified_bundle(self.config)  # the same strict checks as before
        current = diarization_snapshot(
            files,
            self.config.manifest_path.parent,
            license_id=terms["license_id"],
            license_url=terms["license_url"],
            reference=self.config.manifest_sha256,
        )
        expected = evidence.snapshot
        if (current.root_identity, current.artifact_digest, current.terms_digest) != (
            expected.root_identity,
            expected.artifact_digest,
            expected.terms_digest,
        ):
            raise ProviderError("DIARIZATION_MODEL_CHECKSUM")  # a new confirmation is needed
        return acquire(evidence, data=files, parent=self.bundle_parent, cancel=execution.cancel)

    def _check(self, execution: ExecutionContext, deadline: float) -> None:
        if self._closed.is_set() or execution.cancel.is_set():
            raise ProviderError("CANCELLED")
        if time.monotonic() >= deadline:
            raise ProviderError("TIMEOUT")

    def _reap(self) -> None:
        child = self._process
        if self._cancel is not None:
            self._cancel.set()
        try:
            if child is not None and child.pid is not None:
                if child.is_alive():
                    child.join(0.05)
                if child.is_alive():
                    child.terminate()
                    child.join(2)
                if child.is_alive():
                    # Keep every owned handle for an explicit retry; never report completion.
                    raise ProviderError("DIARIZATION_ACK_PENDING")
            if child is not None:
                child.close()
        except (OSError, ValueError):
            raise ProviderError("DIARIZATION_ACK_PENDING") from None
        self._process = None
        self._cancel = None
        bundle, self._bundle = self._bundle, None
        if bundle is not None:
            from recoryn.models._artifact_io import release

            # Only after the child's exit ACK (the guards stay until then).
            self.bundle_cleanup_pending = not release(bundle)
        if self._guard is not None:
            self._guard.close()
            self._guard = None
        if self._reply is not None:
            self._reply.close()
            self._reply = None

    def close(self) -> None:
        self._closed.set()
        with self._lock:
            self._reap()
