"""Fake resource intents, profiles, observers and owned workers for G11 tests.

None of these is a real device or memory profile. ``STT`` (LOCAL_CT2 under CPU_ONLY)
forces the CPU and needs no observation at all: no GPU probe, no RAM read, no profile.
``SUMMARY`` is REMOTE, outside this PC's device policy. Tests of the policy itself build
their own requests. Profiles here exist only to exercise the arithmetic of section 4.3
with small integers; they are never added to the production catalog.

Expected values never come from this module: it builds inputs, the test files hold the
hand-written oracles.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

from recoryn.models import ResourceRequest
from recoryn.models.resource_catalog import MemoryProfile, profile_digest
from recoryn.models.resources import (
    NO_SOURCE,
    NOT_OBSERVED,
    GpuObservation,
    MemoryObservation,
    ResourceSnapshot,
    ResourceSource,
)
from recoryn.providers import ProviderCapabilities, ProviderError, STTResult, TranscriptSegment

EVIDENCE = "e" * 64  # a well-formed (fake) evidence hash; never a real measurement


def stt_request(
    policy: str = "CPU_ONLY", backend: str = "LOCAL_CT2", **fields: Any
) -> ResourceRequest:
    return ResourceRequest("stt", backend, policy, **fields)


def summary_request(
    policy: str = "CPU_ONLY", backend: str = "REMOTE", **fields: Any
) -> ResourceRequest:
    return ResourceRequest("summary", backend, policy, **fields)


STT = stt_request()
SUMMARY = summary_request()


def profile(
    profile_id: str,
    *,
    kind: str = "stt",
    backend: str = "LOCAL_CT2",
    model: str = "model-fixture",
    runtime: str = "runtime-fixture",
    envelope: tuple[tuple[str, int], ...] = (),
    cpu: int | None = None,
    gpu_host: int | None = None,
    gpu: int | None = None,
    evidence: str = EVIDENCE,
    status: str = "MEASURED",
    digest: str | None = None,
) -> MemoryProfile:
    """A fake profile with a correct digest unless ``digest`` is forced."""
    draft = MemoryProfile(
        profile_id,
        kind,
        backend,
        model,
        runtime,
        envelope,
        cpu,
        gpu_host,
        gpu,
        evidence,
        status,
        "",
    )
    return replace(draft, digest=profile_digest(draft) if digest is None else digest)


class Observer:
    """Returns configured observations and records what the plan asked to observe."""

    def __init__(
        self,
        gpu: GpuObservation | Callable[[], GpuObservation] | None = None,
        ram: MemoryObservation | Callable[[], MemoryObservation] | None = None,
    ) -> None:
        self.gpu, self.ram = gpu, ram
        self.calls: list[tuple[bool, bool, str]] = []

    def __call__(self, need_gpu: bool, need_ram: bool, source: ResourceSource) -> ResourceSnapshot:
        self.calls.append((need_gpu, need_ram, source.cuda_source))
        gpu = self.gpu() if callable(self.gpu) else self.gpu
        ram = self.ram() if callable(self.ram) else self.ram
        stamps = [item.observed_ns or 0 for item in (gpu, ram) if item is not None]
        now = max([time.monotonic_ns(), *stamps])
        return ResourceSnapshot(
            now,
            (gpu or GpuObservation(NOT_OBSERVED)) if need_gpu else GpuObservation(NOT_OBSERVED),
            (ram or MemoryObservation(NOT_OBSERVED))
            if need_ram
            else MemoryObservation(NOT_OBSERVED),
            source,
        )

    @property
    def gpu_probes(self) -> int:
        return sum(1 for need_gpu, _, _ in self.calls if need_gpu)

    @property
    def ram_reads(self) -> int:
        return sum(1 for _, need_ram, _ in self.calls if need_ram)


@dataclass
class Worker:
    """An owned worker: records its creation plan, load facts, inference and exit ACK."""

    plan: Any
    facts: dict[str, Any] | None = None
    close_ok: bool = True
    gate: threading.Event | None = None
    entered: threading.Event = field(default_factory=threading.Event)
    result: Callable[[Any], STTResult] | None = None
    calls: list[str] = field(default_factory=list)
    alive: bool = True

    def load(self, context: Any = None) -> dict[str, Any]:
        self.calls.append("load")
        if self.facts is not None:
            return self.facts
        cuda = self.plan.device == "cuda"
        return {
            "device": self.plan.device,
            "device_index": self.plan.cuda_index if cuda else None,
            "compute_type": self.plan.compute_type,
        }

    def transcribe(self, request: Any, context: Any = None) -> STTResult:
        self.calls.append("transcribe")
        self.entered.set()
        if self.gate is not None:
            assert self.gate.wait(10)
        if self.result is not None:
            return self.result(request)
        item = TranscriptSegment("fixture", request.offset_ms, request.offset_ms + 500, "x")
        return STTResult("fake", "model", (item,), True, processed_ms=1)

    def close(self) -> None:
        self.calls.append("close")
        if not self.close_ok:
            raise ProviderError("INFERENCE_ACK_PENDING")
        self.alive = False

    def is_live(self) -> bool:
        return self.alive


class Factory:
    """An owned backend factory: one Worker per ``open(plan)``, after the lease grant."""

    def __init__(
        self,
        identity: str = "faster_whisper",
        *,
        source: ResourceSource = NO_SOURCE,
        semantic_device: str | None = None,
        **worker: Any,
    ) -> None:
        self.identity = identity
        self.resource_source = source
        self.semantic_device = semantic_device
        self.worker = worker
        self.opened: list[Worker] = []

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(self.identity, transcription=True)

    def open(self, plan: Any) -> Worker:
        worker = Worker(plan, **self.worker)
        self.opened.append(worker)
        return worker
