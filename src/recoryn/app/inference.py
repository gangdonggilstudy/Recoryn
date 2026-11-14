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


def _worker(model_path: str, device: str, requests: Any, replies: Any) -> None:
    # No Qt, capture, provider discovery, download or device fallback in this process.
    os.environ.update({"HF_HUB_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1", "DO_NOT_TRACK": "1"})
    parent = multiprocessing.parent_process()

    def watch_parent() -> None:
        while parent is not None and parent.is_alive():
            time.sleep(0.25)
        if parent is not None:
            # Exit only this application's owned child after coordinator death.
            os._exit(0)

    threading.Thread(target=watch_parent, daemon=True, name="recoryn-parent-watch").start()
    from recoryn.transcription import FasterWhisperProvider

    provider = FasterWhisperProvider(Path(model_path), device=device)
    while True:
        command = requests.get()
        if command is None:
            return
        token, request = command
        try:
            result = provider.transcribe(request)
            replies.put((token, result))
        except Exception:
            replies.put((token, "INFERENCE_PROCESS_FAILED"))


class LocalSTTProcess:
    """One reusable model process; cancellation may terminate only this owned child.

    The worker reads fixed derived clips. All publication and original media writes
    remain in the parent. A killed process cannot publish a stale result itself.
    """

    def __init__(self, model_path: Path, *, device: str = "cpu", timeout: float = 600) -> None:
        if (
            device not in ("cpu", "cuda")
            or isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or not 0 < timeout <= 86400
        ):
            raise ProviderError("INPUT_INVALID")
        self.model_path, self.device, self.timeout = model_path, device, timeout
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
            args=(str(self.model_path), self.device, self._requests, self._replies),
            name="recoryn-local-stt",
            daemon=True,
        )
        self._process.start()

    def transcribe(self, request: STTRequest, context: ExecutionContext | None = None) -> STTResult:
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
                if not isinstance(result, STTResult):
                    raise ProviderError("INFERENCE_PROCESS_FAILED")
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
