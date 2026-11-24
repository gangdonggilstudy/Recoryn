"""Read-only GPU discovery; explicit execution policy; one heavy inference lease."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import astuple, dataclass

from recoryn.domain import StateConflict, ValidationError
from recoryn.models.resource_catalog import (
    BACKENDS,
    CATALOG_DIGEST,
    KINDS,
    NOT_APPLICABLE,
    POLICIES,
    REFUSALS,
    SERVER_UNKNOWN,
    backend_rule,
)


@dataclass(frozen=True, slots=True)
class GPUInfo:
    index: int
    name: str
    free_bytes: int
    total_bytes: int


def probe_gpus() -> tuple[str, tuple[GPUInfo, ...]]:
    executable = shutil.which("nvidia-smi")
    if executable is None:
        return "UNAVAILABLE", ()
    try:
        result = subprocess.run(
            [
                executable,
                "--query-gpu=index,name,memory.free,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        gpus = []
        for row in result.stdout.splitlines():
            fields = row.split(",")
            if len(fields) != 4:
                return "UNKNOWN", ()
            index, free, total = int(fields[0]), int(fields[2]), int(fields[3])
            if not 0 <= index < 1024 or not 0 <= free <= total or total <= 0:
                return "UNKNOWN", ()
            gpus.append(GPUInfo(index, fields[1].strip(), free * 2**20, total * 2**20))
        return "OBSERVED", tuple(gpus)
    except (OSError, subprocess.SubprocessError, ValueError):
        return "UNKNOWN", ()


class ResourceScheduler:
    def __init__(self, *, headroom_bytes: int = 512 * 2**20) -> None:
        if type(headroom_bytes) is not int or headroom_bytes < 0:
            raise ValidationError("RESOURCE_HEADROOM")
        self.headroom_bytes = headroom_bytes
        self._lease = threading.Lock()

    def choose(
        self, policy: str, required_bytes: int, gpus: tuple[GPUInfo, ...]
    ) -> tuple[str, int]:
        if type(required_bytes) is not int or required_bytes < 0:
            raise ValidationError("RESOURCE_ESTIMATE_REQUIRED")
        if policy == "CPU_ONLY":
            return "cpu", 0
        if policy not in ("GPU_ONLY", "GPU_WITH_CPU_FALLBACK_ALLOWED"):
            raise ValidationError("RESOURCE_POLICY")
        for gpu in gpus:
            if gpu.free_bytes >= required_bytes + self.headroom_bytes:
                return "cuda", gpu.index
        if policy == "GPU_WITH_CPU_FALLBACK_ALLOWED":
            return "cpu", 0
        raise StateConflict("RESOURCE_GPU_UNAVAILABLE")

    @contextmanager
    def acquire(self, cancel: threading.Event | None = None) -> Iterator[None]:
        while not self._lease.acquire(timeout=0.1):
            if cancel is not None and cancel.is_set():
                raise StateConflict("RESOURCE_CANCELLED")
        try:
            if cancel is not None and cancel.is_set():
                raise StateConflict("RESOURCE_CANCELLED")
            yield
        finally:
            self._lease.release()


INTERACTIVE, LIVE, BACKGROUND = 0, 1, 2
ESTIMATE_UNKNOWN = "RESOURCE_ESTIMATE_UNKNOWN"  # a display state, never an error code


def _optional_text(value: object, maximum: int) -> bool:
    return value is None or (
        type(value) is str and 0 < len(value) <= maximum and "\x00" not in value
    )


@dataclass(frozen=True, slots=True)
class ResourceRequest:
    """One admission's immutable resource intent (contract G11 sections 3.2 and 6).

    The policy is the one the user selected when preparing the request. A later UI
    change applies to new requests only. Missing identities stay None (UNKNOWN); they
    are never filled with a fixed 1 GiB, GPU 0 or an arbitrary CPU.
    """

    kind: str
    backend: str
    policy: str
    model_identity: str | None = None
    runtime_identity: str | None = None
    profile_identity: str | None = None
    input_envelope: tuple[tuple[str, int], ...] = ()
    preferred_gpu: str | None = None
    priority: int = INTERACTIVE

    def __post_init__(self) -> None:
        envelope = self.input_envelope
        if (
            self.kind not in KINDS
            or self.backend not in BACKENDS
            or self.policy not in POLICIES
            or not all(
                _optional_text(value, 256)
                for value in (self.model_identity, self.runtime_identity, self.profile_identity)
            )
            or not _optional_text(self.preferred_gpu, 128)
            or type(self.priority) is not int
            or self.priority not in (INTERACTIVE, LIVE, BACKGROUND)
            or type(envelope) is not tuple
            or not all(
                type(item) is tuple
                and len(item) == 2
                and _optional_text(item[0], 64)
                and item[0] is not None
                and type(item[1]) is int
                and 0 <= item[1] < 2**63
                for item in envelope
            )
            or len({item[0] for item in envelope}) != len(envelope)
        ):
            raise ValidationError("INVALID_RESOURCE_REQUEST")

    @property
    def digest(self) -> str:
        return hashlib.sha256(json.dumps(astuple(self), separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ResourcePlan:
    """The static admission of one request: whether the device policy applies and the
    device it commits to. Memory observation and leases are a later unit (G-P11b)."""

    request_digest: str
    applies: bool
    device: str
    estimate_status: str
    catalog_digest: str = CATALOG_DIGEST


def plan_static(request: ResourceRequest) -> ResourcePlan:
    """Admit a request by the fixed backend table, before any preparation side effect.

    Refusals raise StateConflict with a closed-catalog code: RESOURCE_POLICY_UNVERIFIED
    (Ollama under a strict policy), RESOURCE_GPU_UNSUPPORTED (CPU-only backend under
    GPU_ONLY) or CAPABILITY_UNSUPPORTED (a task the backend does not run). A REMOTE
    provider is not subject to this PC's device policy; its consent and cost guards
    are separate and still apply.
    """
    if type(request) is not ResourceRequest:
        raise ValidationError("INVALID_RESOURCE_REQUEST")
    device = backend_rule(request.backend, request.kind, request.policy)
    if device in REFUSALS:
        raise StateConflict(device)
    applies = device not in (NOT_APPLICABLE, SERVER_UNKNOWN)
    status = ESTIMATE_UNKNOWN if applies else device.upper()
    return ResourcePlan(request.digest, applies, device, status)
