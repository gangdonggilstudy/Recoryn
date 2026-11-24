"""Owned subprocess isolation for local inference; recording never waits on models."""

from __future__ import annotations

import math
import multiprocessing
import os
import queue
import threading
import time
from pathlib import Path
from typing import Any

from recoryn.providers import (
    ExecutionContext,
    ProviderCapabilities,
    ProviderError,
    STTRequest,
    STTResult,
)

_LOAD_CODES = frozenset({"MODEL_MISSING", "DEPENDENCY_MISSING", "CANCELLED", "TIMEOUT"})
_COMPUTE_TYPES = frozenset({"int8", "int8_float16", "int8_float32", "float16", "float32"})

# Explicit failures of the opt-in GPU runtime (L01 D10); the parent re-raises them as is.
GPU_RUNTIME_CODES = frozenset(
    {
        "GPU_RUNTIME_UNAVAILABLE",
        "GPU_RUNTIME_DAMAGED",
        "GPU_RUNTIME_NOT_INSTALLED",
        "GPU_RUNTIME_LATE",
        "GPU_RUNTIME_UNSUPPORTED",
    }
)


def _activate_gpu(gpu_runtime: str | None) -> str | None:
    """Activate the user's GPU runtime before CTranslate2 is imported; None when ready."""
    if gpu_runtime is None:
        return None  # a CUDA-capable CTranslate2 is already the installed one (source run)
    try:
        from recoryn.models.gpu_runtime import activate, supported

        if not supported():
            return "GPU_RUNTIME_UNSUPPORTED"
        activate(Path(gpu_runtime))
    except Exception as exc:
        code = str(exc.args[0]) if exc.args else ""
        return code if code in GPU_RUNTIME_CODES else "GPU_RUNTIME_UNAVAILABLE"
    return None


def _worker(
    model_path: str,
    device: str,
    requests: Any,
    replies: Any,
    gpu_runtime: str | None = None,
    device_index: int | None = None,
    compute_type: str | None = None,
) -> None:
    # No Qt, capture, provider discovery, download or device fallback in this process.
    # CUDA enumerates by PCI bus id, the order the GPU inventory verified (G11 4.2).
    os.environ.update(
        {
            "HF_HUB_OFFLINE": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1",
            "DO_NOT_TRACK": "1",
            "CUDA_DEVICE_ORDER": "PCI_BUS_ID",
        }
    )
    parent = multiprocessing.parent_process()

    def watch_parent() -> None:
        while parent is not None and parent.is_alive():
            time.sleep(0.25)
        if parent is not None:
            # Exit only this application's owned child after coordinator death.
            os._exit(0)

    threading.Thread(target=watch_parent, daemon=True, name="recoryn-parent-watch").start()
    failure = _activate_gpu(gpu_runtime) if device == "cuda" else None
    if failure is not None:
        # Answer every request with the explicit code; never fall back silently here.
        while True:
            command = requests.get()
            if command is None:
                return
            replies.put((command[0], failure))
    from recoryn.transcription import FasterWhisperProvider

    provider = FasterWhisperProvider(
        Path(model_path), device=device, device_index=device_index, compute_type=compute_type
    )
    while True:
        command = requests.get()
        if command is None:
            return
        token, request = command
        try:
            if request == "load":
                replies.put((token, {"facts": provider.load()}))
                continue
            result = provider.transcribe(request)
            replies.put((token, result))
        except ProviderError as error:
            replies.put((token, error.code if request == "load" else "INFERENCE_PROCESS_FAILED"))
        except Exception:
            replies.put((token, "INFERENCE_PROCESS_FAILED"))


class LocalSTTProcess:
    """One reusable model process; cancellation may terminate only this owned child.

    The worker reads fixed derived clips. All publication and original media writes
    remain in the parent. A killed process cannot publish a stale result itself.
    """

    def __init__(
        self,
        model_path: Path,
        *,
        device: str = "cpu",
        timeout: float = 600,
        gpu_runtime: Path | None = None,
        device_index: int | None = None,
        compute_type: str | None = None,
    ) -> None:
        if (
            device not in ("cpu", "cuda")
            or isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or not 0 < timeout <= 86400
            or (
                device_index is not None
                and (type(device_index) is not int or not 0 <= device_index < 1024)
            )
            or (compute_type is not None and compute_type not in _COMPUTE_TYPES)
        ):
            raise ProviderError("INPUT_INVALID")
        self.model_path, self.device, self.timeout = model_path, device, timeout
        self.device_index, self.compute_type = device_index, compute_type
        self.gpu_runtime = gpu_runtime if device == "cuda" else None
        # The GPU runtime failure this worker answered with, if any (it answers every
        # later request the same way); the owner then stops offering that runtime.
        self.gpu_failure: str | None = None
        self._context = multiprocessing.get_context("spawn")
        self._process: Any = None
        self._requests: Any = None
        self._replies: Any = None
        self._lock = threading.Lock()
        self._sequence = 0

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            "faster_whisper", transcription=True, segment_timestamps=True, audio_formats=("wav",)
        )

    def _start(self) -> None:
        if self._process is not None and self._process.is_alive():
            return
        self.close()
        self._requests = self._context.Queue(maxsize=2)
        self._replies = self._context.Queue(maxsize=2)
        self._process = self._context.Process(
            target=_worker,
            # The four-argument worker contract stays as is; a GPU runtime adds one and
            # an explicit plan (device index / compute type) adds the last two.
            args=(str(self.model_path), self.device, self._requests, self._replies)
            + self._extra_args(),
            name="recoryn-local-stt",
            daemon=True,
        )
        self._process.start()

    def _extra_args(self) -> tuple[Any, ...]:
        runtime = None if self.gpu_runtime is None else str(self.gpu_runtime)
        if self.device_index is None and self.compute_type is None:
            return () if runtime is None else (runtime,)
        return (runtime, self.device_index, self.compute_type)

    def is_live(self) -> bool:
        """Lock-free: whether the owned child still exists (Library may ask under its mutex)."""
        child = self._process
        try:
            return child is not None and bool(child.is_alive())
        except (ValueError, OSError):
            return False

    def load(self, context: ExecutionContext | None = None) -> dict[str, Any]:
        """Start the child, load the model without inference, and return its real facts."""
        reply = self._call("load", context)
        facts = reply.get("facts") if isinstance(reply, dict) else None
        if not isinstance(facts, dict):
            raise ProviderError("INFERENCE_PROCESS_FAILED")
        return facts

    def transcribe(self, request: STTRequest, context: ExecutionContext | None = None) -> STTResult:
        result = self._call(request, context)
        if not isinstance(result, STTResult):
            raise ProviderError("INFERENCE_PROCESS_FAILED")
        return result

    def _call(self, request: Any, context: ExecutionContext | None) -> Any:
        execution = context or ExecutionContext()
        deadline = time.monotonic() + self.timeout
        while not self._lock.acquire(timeout=0.05):
            if execution.cancel.is_set():
                raise ProviderError("CANCELLED")
            if time.monotonic() >= deadline:
                raise ProviderError("TIMEOUT")
        try:
            if execution.cancel.is_set():
                raise ProviderError("CANCELLED")
            self._start()
            self._sequence += 1
            self._requests.put((self._sequence, request), timeout=1)
            while True:
                if execution.cancel.is_set() or time.monotonic() >= deadline:
                    self.close()
                    raise ProviderError("CANCELLED" if execution.cancel.is_set() else "TIMEOUT")
                try:
                    token, result = self._replies.get(timeout=0.05)
                except queue.Empty:
                    if not self._process.is_alive():
                        self.close()
                        raise ProviderError("INFERENCE_PROCESS_FAILED") from None
                    continue
                if token != self._sequence:
                    continue
                if isinstance(result, str) and result in GPU_RUNTIME_CODES:
                    self.gpu_failure = result
                    raise ProviderError(result)
                if isinstance(result, str):
                    raise ProviderError(
                        result
                        if request == "load" and result in _LOAD_CODES
                        else "INFERENCE_PROCESS_FAILED"
                    )
                return result
        finally:
            self._lock.release()

    def close(self) -> None:
        child = self._process
        if child is not None:
            if child.is_alive():
                try:
                    self._requests.put_nowait(None)
                except queue.Full:
                    pass
                child.join(0.2)
                if child.is_alive():
                    child.terminate()
                    child.join(2)
                if child.is_alive():
                    raise ProviderError("INFERENCE_ACK_PENDING")
            child.close()
            self._process = None
        for channel in (self._requests, self._replies):
            if channel is not None:
                channel.cancel_join_thread()
                channel.close()
        self._requests = self._replies = None
