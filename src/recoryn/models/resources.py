"""Device policy, resource observation, memory admission and the owned-heavy lease.

G-P11a fixed the static backend table (:func:`plan_static`). G-P11b adds the dynamic
plan for the owned paths (LOCAL_CT2 STT, LOCAL_SHERPA diarization): GPU and host RAM
observations with their own states, offline memory profiles (UNKNOWN when absent),
UUID/ordinal placement and one global owned-heavy lease whose release waits for the
worker's real exit acknowledgement (contract G11 sections 3-6).

The legacy ``choose``/``acquire`` helpers stay for their small existing contract; the
product paths use :meth:`ResourceScheduler.plan` and :meth:`ResourceScheduler.lease`.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import astuple, dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from recoryn.domain import StateConflict, ValidationError
from recoryn.models.resource_catalog import (
    AUTO,
    BACKENDS,
    CATALOG_DIGEST,
    CPU,
    CUDA,
    KINDS,
    NOT_APPLICABLE,
    POLICIES,
    PROFILES,
    REFUSALS,
    SERVER_UNKNOWN,
    MemoryProfile,
    backend_rule,
    profile_intact,
)

MIB = 2**20
_COUNT_LIMIT = 2**63


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


INTERACTIVE, LIVE, BACKGROUND = 0, 1, 2
PRIORITIES = (INTERACTIVE, LIVE, BACKGROUND)
ESTIMATE_UNKNOWN = "RESOURCE_ESTIMATE_UNKNOWN"  # a display state, never an error code
ESTIMATE_KNOWN = "RESOURCE_ESTIMATE_KNOWN"

# Observation states. UNAVAILABLE is "no means to observe", never "no GPU"; an OBSERVED
# empty device list is the real absence. NOT_OBSERVED marks an observation the plan did
# not need (CPU_ONLY never probes a GPU; an UNKNOWN requirement never reads RAM).
OBSERVED, UNKNOWN, UNAVAILABLE, NOT_OBSERVED = "OBSERVED", "UNKNOWN", "UNAVAILABLE", "NOT_OBSERVED"
OBSERVATION_STATES = (OBSERVED, UNKNOWN, UNAVAILABLE, NOT_OBSERVED)

# G-P11b refusal codes (closed G-P07 catalog, RESOURCE group).
PROFILE_MISMATCH = "RESOURCE_PROFILE_MISMATCH"
GPU_PROBE_UNKNOWN = "RESOURCE_GPU_PROBE_UNKNOWN"
GPU_PROBE_UNAVAILABLE = "RESOURCE_GPU_PROBE_UNAVAILABLE"
CPU_PROBE_UNKNOWN = "RESOURCE_CPU_PROBE_UNKNOWN"
CPU_PROBE_UNAVAILABLE = "RESOURCE_CPU_PROBE_UNAVAILABLE"
MEMORY_INSUFFICIENT = "RESOURCE_MEMORY_INSUFFICIENT"
IDENTITY_UNVERIFIED = "RESOURCE_GPU_IDENTITY_UNVERIFIED"
SNAPSHOT_STALE = "RESOURCE_SNAPSHOT_STALE"
LEASE_HELD = "RESOURCE_LEASE_HELD"
DEVICE_MISMATCH = "RESOURCE_DEVICE_MISMATCH"
GPU_UNAVAILABLE = "RESOURCE_GPU_UNAVAILABLE"  # existing code: no usable CUDA device
CUDA_SOURCES = ("native", "runtime", "none")


def _optional_text(value: object, maximum: int) -> bool:
    return value is None or (
        type(value) is str and 0 < len(value) <= maximum and "\x00" not in value
    )


def _text(value: object, maximum: int = 256) -> bool:
    return value is not None and _optional_text(value, maximum)


def _count(value: object) -> bool:
    return type(value) is int and 0 <= value < _COUNT_LIMIT


def _invalid() -> ValidationError:
    return ValidationError("INVALID_RESOURCE_OBSERVATION")


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
            or self.priority not in PRIORITIES
            or type(envelope) is not tuple
            or not all(
                type(item) is tuple
                and len(item) == 2
                and _optional_text(item[0], 64)
                and item[0] is not None
                and type(item[1]) is int
                and 0 <= item[1] < _COUNT_LIMIT
                for item in envelope
            )
            or len({item[0] for item in envelope}) != len(envelope)
        ):
            raise ValidationError("INVALID_RESOURCE_REQUEST")

    @property
    def digest(self) -> str:
        return hashlib.sha256(json.dumps(astuple(self), separators=(",", ":")).encode()).hexdigest()


# --- observations ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GpuDevice:
    """One verified CUDA device: ``ordinal`` is the logical index in the verified
    runtime, ``host_index`` the host tool's index (display only, never passed on)."""

    uuid: str
    ordinal: int
    host_index: int
    name: str
    free_bytes: int
    total_bytes: int

    def __post_init__(self) -> None:
        if (
            not _text(self.uuid, 128)
            or not (type(self.ordinal) is int and 0 <= self.ordinal < 1024)
            or not (type(self.host_index) is int and 0 <= self.host_index < 1024)
            or not _text(self.name, 256)
            or not _count(self.free_bytes)
            or not _count(self.total_bytes)
            or self.total_bytes <= 0
            or self.free_bytes > self.total_bytes
        ):
            raise _invalid()


@dataclass(frozen=True, slots=True)
class GpuObservation:
    state: str = NOT_OBSERVED
    observed_ns: int | None = None
    devices: tuple[GpuDevice, ...] = ()
    identity_verified: bool = False
    source: str = "none"
    reason: str | None = None

    def __post_init__(self) -> None:
        devices = self.devices
        if (
            self.state not in OBSERVATION_STATES
            or type(devices) is not tuple
            or not all(type(item) is GpuDevice for item in devices)
            or type(self.identity_verified) is not bool
            or not _text(self.source, 64)
            or not _optional_text(self.reason, 128)
        ):
            raise _invalid()
        if self.state == OBSERVED:
            if not _count(self.observed_ns):
                raise _invalid()
            for attribute in ("uuid", "host_index", "ordinal"):
                values = [getattr(item, attribute) for item in devices]
                if len(set(values)) != len(values):
                    raise _invalid()  # duplicate identity, host index or ordinal
        elif devices or self.identity_verified or self.observed_ns is not None:
            # An UNKNOWN probe has no current values; the cache is separate.
            raise _invalid()


@dataclass(frozen=True, slots=True)
class MemoryObservation:
    state: str = NOT_OBSERVED
    observed_ns: int | None = None
    free_bytes: int | None = None
    total_bytes: int | None = None
    source: str = "none"

    def __post_init__(self) -> None:
        if self.state not in OBSERVATION_STATES or not _text(self.source, 64):
            raise _invalid()
        if self.state == OBSERVED:
            free, total = self.free_bytes, self.total_bytes
            if (
                not _count(self.observed_ns)
                or type(free) is not int
                or type(total) is not int
                or not _count(free)
                or not _count(total)
                or total <= 0
                or free > total
            ):
                raise _invalid()
        elif not (
            self.observed_ns is None and self.free_bytes is None and self.total_bytes is None
        ):
            raise _invalid()


@dataclass(frozen=True, slots=True)
class ResourceSource:
    """Where CUDA would come from for this request (L-P07 ``gpu_source``)."""

    cuda_source: str = "none"
    runtime_state: str = "NOT_INSTALLED"
    runtime_root: Path | None = None

    def __post_init__(self) -> None:
        if (
            self.cuda_source not in CUDA_SOURCES
            or not _text(self.runtime_state, 64)
            or (self.runtime_root is not None and not isinstance(self.runtime_root, Path))
            or (self.cuda_source == "runtime") != (self.runtime_root is not None)
        ):
            raise _invalid()


NO_SOURCE = ResourceSource()


@dataclass(frozen=True, slots=True)
class ResourceSnapshot:
    taken_ns: int
    gpu: GpuObservation = field(default_factory=GpuObservation)
    ram: MemoryObservation = field(default_factory=MemoryObservation)
    source: ResourceSource = NO_SOURCE
    last_gpu: GpuObservation | None = None  # display cache only, never for placement
    last_ram: MemoryObservation | None = None

    def __post_init__(self) -> None:
        if (
            not _count(self.taken_ns)
            or type(self.gpu) is not GpuObservation
            or type(self.ram) is not MemoryObservation
            or type(self.source) is not ResourceSource
            or not (self.last_gpu is None or type(self.last_gpu) is GpuObservation)
            or not (self.last_ram is None or type(self.last_ram) is MemoryObservation)
        ):
            raise _invalid()
        for item in (self.gpu, self.ram):
            if item.observed_ns is not None and item.observed_ns > self.taken_ns:
                raise _invalid()  # an observation from the future


# --- plan ----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ResourcePlan:
    """The admission of one request.

    ``owned`` is True only for the local owned resource stage (lease, memory, device);
    ``policy_applies`` is False only for REMOTE (G11R-06): an allowed Ollama request is
    subject to the device policy yet has no owned stage (``device == "server_unknown"``).
    Requirements of an UNKNOWN estimate are None, never 0 or the headroom.
    """

    request_digest: str
    owned: bool
    device: str
    estimate_status: str
    catalog_digest: str = CATALOG_DIGEST
    policy_applies: bool = True
    gpu_uuid: str | None = None
    cuda_index: int | None = None
    host_index: int | None = None
    gpu_name: str | None = None
    compute_type: str | None = None
    cuda_source: str | None = None
    planned_ram: int | None = None
    planned_vram: int | None = None
    ram_headroom: int | None = None
    gpu_headroom: int | None = None
    profile_id: str | None = None
    ram_state: str = NOT_OBSERVED
    ram_free: int | None = None
    gpu_state: str = NOT_OBSERVED
    vram_free: int | None = None
    observed_ns: int | None = None
    fallback_reasons: tuple[str, ...] = ()


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
    owned = device not in (NOT_APPLICABLE, SERVER_UNKNOWN)
    status = ESTIMATE_UNKNOWN if owned else device.upper()
    return ResourcePlan(
        request.digest, owned, device, status, policy_applies=device != NOT_APPLICABLE
    )


class _Refused(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def resolve_profile(
    request: ResourceRequest, profiles: tuple[MemoryProfile, ...]
) -> MemoryProfile | None:
    """The profile that applies, None when absent (UNKNOWN), or PROFILE_MISMATCH.

    An explicitly applied profile must match the model artifact, the runtime and every
    envelope bound; a record that is damaged or has unreviewed evidence is a mismatch,
    never downgraded to absence.
    """
    if request.profile_identity is not None:
        chosen = [item for item in profiles if item.profile_id == request.profile_identity]
    elif request.model_identity is None or request.runtime_identity is None:
        return None
    else:
        chosen = [
            item
            for item in profiles
            if (item.kind, item.backend, item.model_identity, item.runtime_identity)
            == (request.kind, request.backend, request.model_identity, request.runtime_identity)
        ]
        if not chosen:
            return None
    if len(chosen) != 1:
        raise StateConflict(PROFILE_MISMATCH)
    profile = chosen[0]
    bounds = dict(profile.envelope)
    given = dict(request.input_envelope)
    if (
        not profile_intact(profile)
        or (profile.kind, profile.backend) != (request.kind, request.backend)
        or profile.model_identity != request.model_identity
        or profile.runtime_identity != request.runtime_identity
        or set(bounds) != set(given)
        or any(given[name] > bounds[name] for name in bounds)
    ):
        raise StateConflict(PROFILE_MISMATCH)
    return profile


def _fresh(observed_ns: int | None, now_ns: int, ttl_ns: int) -> bool:
    return observed_ns is not None and 0 <= now_ns - observed_ns < ttl_ns


# G11 section 4.3: a snapshot is fresh for two seconds by default.
DEFAULT_TTL_NS = 2_000_000_000


def plan_resources(
    request: ResourceRequest,
    snapshot: ResourceSnapshot,
    *,
    now_ns: int,
    profiles: tuple[MemoryProfile, ...] = PROFILES,
    ttl_ns: int = DEFAULT_TTL_NS,
    ram_headroom: int = 512 * MIB,
    gpu_headroom: int = 512 * MIB,
    device: str | None = None,
) -> ResourcePlan:
    """Pure admission of one request against one snapshot (contract G11 section 4.3).

    Known CPU: RAM OBSERVED and free >= cpu_host_ram + RAM headroom. Known GPU: VRAM of
    the same UUID free >= gpu_bytes + GPU headroom and RAM free >= gpu_host_ram + RAM
    headroom. UNKNOWN CPU: no RAM comparison at all. UNKNOWN GPU: VRAM free >= GPU
    headroom. Equality admits. AUTO picks the largest free fitting GPU (stable UUID
    order on ties); a pinned UUID is never swapped. GPU_ONLY never produces a CPU;
    fallback tries CPU only by its own conditions and keeps the GPU reasons.
    ``device`` restricts the candidates to the device a Job's semantic key fixed.
    """
    if type(request) is not ResourceRequest or type(snapshot) is not ResourceSnapshot:
        raise ValidationError("INVALID_RESOURCE_REQUEST")
    if not all(_count(value) for value in (now_ns, ttl_ns, ram_headroom, gpu_headroom)):
        raise ValidationError("INVALID_RESOURCE_REQUEST")
    static = plan_static(request)
    if not static.owned:
        return static
    if snapshot.taken_ns > now_ns:
        raise StateConflict(SNAPSHOT_STALE)  # the clock went backward
    profile = resolve_profile(request, profiles)
    candidates = {CPU: [CPU], CUDA: [CUDA], AUTO: [CUDA, CPU]}[static.device]
    if device is not None:
        if device not in candidates:
            raise ValidationError("INVALID_RESOURCE_REQUEST")
        candidates = [device]
    reasons: list[str] = []
    for candidate in candidates:
        try:
            if candidate == CPU:
                return _cpu_plan(request, snapshot, profile, now_ns, ttl_ns, ram_headroom, reasons)
            return _gpu_plan(request, snapshot, profile, now_ns, ttl_ns, ram_headroom, gpu_headroom)
        except _Refused as refusal:
            reasons.append(refusal.code)
    raise StateConflict(reasons[-1])


def _ram_fit(
    snapshot: ResourceSnapshot, required: int, now_ns: int, ttl_ns: int, headroom: int
) -> int:
    ram = snapshot.ram
    if ram.state == UNKNOWN:
        raise _Refused(CPU_PROBE_UNKNOWN)
    if ram.state != OBSERVED:
        raise _Refused(CPU_PROBE_UNAVAILABLE)
    if not _fresh(ram.observed_ns, now_ns, ttl_ns):
        raise _Refused(SNAPSHOT_STALE)
    assert ram.free_bytes is not None
    if ram.free_bytes < required + headroom:
        raise _Refused(MEMORY_INSUFFICIENT)
    return ram.free_bytes


def _cpu_plan(
    request: ResourceRequest,
    snapshot: ResourceSnapshot,
    profile: MemoryProfile | None,
    now_ns: int,
    ttl_ns: int,
    ram_headroom: int,
    reasons: list[str],
) -> ResourcePlan:
    required = None if profile is None else profile.cpu_host_ram
    ram = snapshot.ram
    if required is not None:
        _ram_fit(snapshot, required, now_ns, ttl_ns, ram_headroom)
    return ResourcePlan(
        request.digest,
        True,
        CPU,
        ESTIMATE_UNKNOWN if required is None else ESTIMATE_KNOWN,
        compute_type="int8" if request.backend == "LOCAL_CT2" else "float32",
        planned_ram=required,
        ram_headroom=None if required is None else ram_headroom,
        profile_id=None if profile is None else profile.profile_id,
        ram_state=ram.state,
        ram_free=ram.free_bytes,
        gpu_state=snapshot.gpu.state,
        observed_ns=ram.observed_ns,
        fallback_reasons=tuple(reasons),
    )


def _gpu_plan(
    request: ResourceRequest,
    snapshot: ResourceSnapshot,
    profile: MemoryProfile | None,
    now_ns: int,
    ttl_ns: int,
    ram_headroom: int,
    gpu_headroom: int,
) -> ResourcePlan:
    if snapshot.source.cuda_source == "none":
        raise _Refused(GPU_UNAVAILABLE)
    gpu, ram = snapshot.gpu, snapshot.ram
    vram = None if profile is None else profile.gpu_bytes
    host = None if profile is None else profile.gpu_host_ram
    # G11 section 4.3 order: time validity of every applied observation -> known host
    # RAM observation -> GPU observation -> identity -> device presence -> host RAM
    # capacity -> VRAM capacity. An UNKNOWN GPU requirement applies no RAM at all.
    if gpu.state == OBSERVED and not _fresh(gpu.observed_ns, now_ns, ttl_ns):
        raise _Refused(SNAPSHOT_STALE)
    if host is not None and ram.state == OBSERVED and not _fresh(ram.observed_ns, now_ns, ttl_ns):
        raise _Refused(SNAPSHOT_STALE)
    if host is not None and ram.state != OBSERVED:
        raise _Refused(CPU_PROBE_UNKNOWN if ram.state == UNKNOWN else CPU_PROBE_UNAVAILABLE)
    if gpu.state == UNKNOWN:
        raise _Refused(GPU_PROBE_UNKNOWN)
    if gpu.state != OBSERVED:
        raise _Refused(GPU_PROBE_UNAVAILABLE)
    # A device can only be called absent once identities are verified: with a missing
    # or duplicated UUID a pinned device's absence is not knowable (G-P11c reading).
    if not gpu.identity_verified:
        raise _Refused(IDENTITY_UNVERIFIED)
    devices = list(gpu.devices)
    if request.preferred_gpu is not None:
        devices = [item for item in devices if item.uuid == request.preferred_gpu]
    if not devices:
        raise _Refused(GPU_UNAVAILABLE)
    if host is not None:
        _ram_fit(snapshot, host, now_ns, ttl_ns, ram_headroom)
    needed = gpu_headroom + (0 if vram is None else vram)
    fitting = [item for item in devices if item.free_bytes >= needed]
    if not fitting:
        raise _Refused(MEMORY_INSUFFICIENT)
    chosen = sorted(fitting, key=lambda item: (-item.free_bytes, item.uuid))[0]
    return ResourcePlan(
        request.digest,
        True,
        CUDA,
        ESTIMATE_UNKNOWN if vram is None else ESTIMATE_KNOWN,
        gpu_uuid=chosen.uuid,
        cuda_index=chosen.ordinal,
        host_index=chosen.host_index,
        gpu_name=chosen.name,
        compute_type="float16",
        cuda_source=snapshot.source.cuda_source,
        planned_ram=host,
        planned_vram=vram,
        ram_headroom=None if host is None else ram_headroom,
        gpu_headroom=gpu_headroom,
        profile_id=None if profile is None else profile.profile_id,
        ram_state=snapshot.ram.state,
        ram_free=snapshot.ram.free_bytes,
        gpu_state=gpu.state,
        vram_free=chosen.free_bytes,
        observed_ns=gpu.observed_ns,
    )


def observation_needs(
    request: ResourceRequest,
    source: ResourceSource,
    profiles: tuple[MemoryProfile, ...],
    device: str | None = None,
) -> tuple[bool, bool]:
    """(needs GPU, needs RAM): only what the plan can use is observed.

    CPU_ONLY and CPU-only backends never probe a GPU (L-P07); a GPU needs a CUDA
    source; RAM is read only for a known requirement of a candidate device.
    """
    static = backend_rule(request.backend, request.kind, request.policy)
    if static not in (CPU, CUDA, AUTO):
        return False, False
    try:
        profile = resolve_profile(request, profiles)
    except StateConflict:
        return False, False  # the plan refuses before any observation is used
    gpu_candidate = static in (CUDA, AUTO) and device != CPU
    cpu_candidate = static in (CPU, AUTO) and device != CUDA
    need_gpu = gpu_candidate and source.cuda_source != "none"
    need_ram = profile is not None and (
        (cpu_candidate and profile.cpu_host_ram is not None)
        or (need_gpu and profile.gpu_host_ram is not None)
    )
    return need_gpu, need_ram


# What CTranslate2 may report for a requested type (int8 on CPU runs as int8_float32).
COMPUTE_ALIASES = {
    "int8": frozenset({"int8", "int8_float32"}),
    "float16": frozenset({"float16"}),
    "float32": frozenset({"float32"}),
}


def facts_match(plan: ResourcePlan, facts: object) -> bool:
    """The loaded object's real device facts equal the plan (G11 section 6)."""
    if not isinstance(facts, dict) or plan.compute_type is None:
        return False
    allowed = COMPUTE_ALIASES.get(plan.compute_type, frozenset({plan.compute_type}))
    if facts.get("device") != plan.device or facts.get("compute_type") not in allowed:
        return False
    index = facts.get("device_index")
    if plan.device == CUDA:
        return type(index) is int and index == plan.cuda_index
    return index is None or index == 0


# --- lease -----------------------------------------------------------------------------

LEASE_STATES = (
    "QUEUED",
    "GRANTED_NO_CHILD",
    "CHILD_RUNNING",
    "INFERENCE_REPLIED",
    "REAP_PENDING",
    "REAP_ACKED",
)
LEASE_EVENTS = ("success_result", "local_error", "cancel", "unknown_result")
# (state, event) -> next state; anything absent is an illegal transition.
LEASE_TRANSITIONS = {
    ("QUEUED", "cancel"): "REAP_ACKED",
    ("GRANTED_NO_CHILD", "local_error"): "REAP_PENDING",
    ("GRANTED_NO_CHILD", "cancel"): "REAP_PENDING",
    ("CHILD_RUNNING", "success_result"): "INFERENCE_REPLIED",
    ("CHILD_RUNNING", "local_error"): "REAP_PENDING",
    ("CHILD_RUNNING", "cancel"): "REAP_PENDING",
    ("CHILD_RUNNING", "unknown_result"): "REAP_PENDING",
    ("INFERENCE_REPLIED", "success_result"): "INFERENCE_REPLIED",
    ("INFERENCE_REPLIED", "local_error"): "REAP_PENDING",
    ("INFERENCE_REPLIED", "cancel"): "REAP_PENDING",
    ("INFERENCE_REPLIED", "unknown_result"): "REAP_PENDING",
    ("REAP_PENDING", "local_error"): "REAP_PENDING",
    ("REAP_PENDING", "cancel"): "REAP_PENDING",
    ("REAP_PENDING", "unknown_result"): "REAP_PENDING",
}
_ACK_CODES = ("INFERENCE_ACK_PENDING", "DIARIZATION_ACK_PENDING")


class Lease:
    """One owned-heavy slot holding: state, plan and the worker it owns.

    ``is_live`` is lock-free (Library calls it under its root mutex). Release happens
    only after the worker's real exit acknowledgement; a worker that does not exit keeps
    the lease in REAP_PENDING and the slot held (RESOURCE_LEASE_HELD for the next one).
    """

    def __init__(
        self,
        request: ResourceRequest,
        *,
        job_id: str = "",
        attempt_id: str = "",
        session_id: str = "",
    ) -> None:
        self.lease_id = uuid4().hex
        self.request = request
        self.job_id, self.attempt_id, self.session_id = job_id, attempt_id, session_id
        self.state = "QUEUED"
        self.plan: ResourcePlan | None = None
        self.worker: Any = None
        self.cancel_requested = False
        self.outcome_unknown = False
        self.ack_code: str | None = None  # set only when a reap failed: the slot is held
        self._reaping = threading.Lock()
        self._owns_worker = False
        # Called once a held lease's worker exit is finally acknowledged (the Job local
        # reader retained by the runner is finished then).
        self.on_ack: Callable[[], None] | None = None

    def record(self, event: str) -> str:
        following = LEASE_TRANSITIONS.get((self.state, event))
        if following is None:
            raise StateConflict("RESOURCE_LEASE_TRANSITION_INVALID")
        self.cancel_requested = self.cancel_requested or event == "cancel"
        self.outcome_unknown = self.outcome_unknown or event == "unknown_result"
        self.state = following
        return following

    def open(self, factory: Callable[[ResourcePlan], Any]) -> Any:
        """Create the owned worker after the grant, never before (G11 section 5.1)."""
        if self.state != "GRANTED_NO_CHILD" or self.plan is None:
            raise StateConflict("RESOURCE_LEASE_TRANSITION_INVALID")
        worker = factory(self.plan)
        self.worker, self._owns_worker = worker, True
        self.state = "CHILD_RUNNING"
        return worker

    def attach(self, provider: Any) -> Any:
        """Use a caller-owned provider inside the lease; the caller keeps its lifetime."""
        if self.state != "GRANTED_NO_CHILD" or self.plan is None:
            raise StateConflict("RESOURCE_LEASE_TRANSITION_INVALID")
        self.worker, self._owns_worker = provider, False
        self.state = "CHILD_RUNNING"
        return provider

    def child_live(self) -> bool:
        worker = self.worker
        if worker is None or not self._owns_worker:
            return False
        check = getattr(worker, "is_live", None)
        return bool(check()) if callable(check) else False

    def is_live(self) -> bool:
        state = self.state
        if state in ("QUEUED", "REAP_ACKED"):
            return False
        if state == "REAP_PENDING":
            return self.child_live()
        return True

    def reap(self) -> None:
        """Close the worker and acknowledge its exit; REAP_PENDING when it survives."""
        with self._reaping:
            self._reap()

    def _reap(self) -> None:
        if self.state == "REAP_ACKED":
            return
        if self.state in ("GRANTED_NO_CHILD", "CHILD_RUNNING", "INFERENCE_REPLIED"):
            self.state = "REAP_PENDING"
        if self.state != "REAP_PENDING":
            raise StateConflict("RESOURCE_LEASE_TRANSITION_INVALID")
        worker = self.worker
        close = getattr(worker, "close", None) if self._owns_worker else None
        try:
            if callable(close):
                close()
        except Exception as error:
            code = getattr(error, "code", None) or (error.args[0] if error.args else None)
            self.ack_code = code if code in _ACK_CODES else "INFERENCE_ACK_PENDING"
            raise
        if self.child_live():
            self.ack_code = self.ack_code or "INFERENCE_ACK_PENDING"
            raise StateConflict(self.ack_code)
        self.ack_code = None
        self.state = "REAP_ACKED"

    def view(self) -> dict[str, Any]:
        plan = self.plan
        return {
            "lease_id": self.lease_id,
            "job_id": self.job_id,
            "attempt_id": self.attempt_id,
            "session_id": self.session_id,
            "request_digest": self.request.digest,
            "profile_id": None if plan is None else plan.profile_id,
            "device": None if plan is None else plan.device,
            "gpu_uuid": None if plan is None else plan.gpu_uuid,
            "cuda_index": None if plan is None else plan.cuda_index,
            "planned_ram": None if plan is None else plan.planned_ram,
            "planned_vram": None if plan is None else plan.planned_vram,
            "estimate_status": None if plan is None else plan.estimate_status,
            "priority": self.request.priority,
            "state": self.state,
            "phase": _PHASE[self.state],
            "cancel_requested": self.cancel_requested,
            "outcome_unknown": self.outcome_unknown,
            "ack_code": self.ack_code,
            "gpu_name": None if plan is None else plan.gpu_name,
            "ram_state": "NOT_OBSERVED" if plan is None else plan.ram_state,
            "ram_free": None if plan is None else plan.ram_free,
            "vram_free": None if plan is None else plan.vram_free,
            "ram_headroom": None if plan is None else plan.ram_headroom,
            "gpu_headroom": None if plan is None else plan.gpu_headroom,
            "observed_ns": None if plan is None else plan.observed_ns,
            "fallback_reasons": () if plan is None else plan.fallback_reasons,
        }


_PHASE = {
    "QUEUED": "WAITING",
    "GRANTED_NO_CHILD": "ACTIVE",
    "CHILD_RUNNING": "ACTIVE",
    "INFERENCE_REPLIED": "ACTIVE",
    "REAP_PENDING": "REAP_PENDING",
    "REAP_ACKED": "RELEASED",
}

Observer = Callable[[bool, bool, ResourceSource], ResourceSnapshot]


def unobserved(need_gpu: bool, need_ram: bool, source: ResourceSource) -> ResourceSnapshot:
    """The default observer: no probe, so whatever is needed is UNAVAILABLE."""
    return ResourceSnapshot(
        time.monotonic_ns(),
        GpuObservation(UNAVAILABLE if need_gpu else NOT_OBSERVED, source="none"),
        MemoryObservation(UNAVAILABLE if need_ram else NOT_OBSERVED, source="none"),
        source,
    )


class ResourceScheduler:
    def __init__(
        self,
        *,
        headroom_bytes: int = 512 * MIB,
        ram_headroom_bytes: int = 512 * MIB,
        observe: Observer | None = None,
        profiles: tuple[MemoryProfile, ...] = PROFILES,
        clock: Callable[[], int] = time.monotonic_ns,
        ttl_ns: int = DEFAULT_TTL_NS,
        reap_interval: float = 0.25,
    ) -> None:
        if type(headroom_bytes) is not int or headroom_bytes < 0:
            raise ValidationError("RESOURCE_HEADROOM")
        if (
            type(reap_interval) not in (int, float)
            or not 0 < reap_interval <= 3600
            or reap_interval != reap_interval
        ):
            raise ValidationError("RESOURCE_REAP_INTERVAL")
        if (
            not _count(ram_headroom_bytes)
            or not _count(ttl_ns)
            or ttl_ns == 0
            or type(profiles) is not tuple
            or not all(type(item) is MemoryProfile for item in profiles)
        ):
            raise ValidationError("RESOURCE_HEADROOM")
        self.headroom_bytes = headroom_bytes
        self.ram_headroom_bytes = ram_headroom_bytes
        self.profiles = profiles
        self.ttl_ns = ttl_ns
        self._observe: Observer = observe or unobserved
        self._clock = clock
        self._lease = threading.Lock()
        self._condition = threading.Condition()
        self._holder: Lease | None = None
        self._waiters: deque[Lease] = deque()
        self._recent: deque[Lease] = deque(maxlen=64)
        self.reap_interval = float(reap_interval)
        self._reaper: threading.Thread | None = None

    # legacy helpers (existing small contract; not used by the product paths)
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

    # product paths
    def observe(
        self,
        request: ResourceRequest,
        source: ResourceSource = NO_SOURCE,
        device: str | None = None,
    ) -> ResourceSnapshot:
        need_gpu, need_ram = observation_needs(request, source, self.profiles, device)
        snapshot = self._observe(need_gpu, need_ram, source)
        if type(snapshot) is not ResourceSnapshot:
            raise _invalid()
        return snapshot

    def plan(
        self, request: ResourceRequest, snapshot: ResourceSnapshot, *, device: str | None = None
    ) -> ResourcePlan:
        return plan_resources(
            request,
            snapshot,
            now_ns=self._clock(),
            profiles=self.profiles,
            ttl_ns=self.ttl_ns,
            ram_headroom=self.ram_headroom_bytes,
            gpu_headroom=self.headroom_bytes,
            device=device,
        )

    def prepare(
        self,
        request: ResourceRequest,
        source: ResourceSource = NO_SOURCE,
        device: str | None = None,
    ) -> ResourcePlan:
        return self.plan(request, self.observe(request, source, device), device=device)

    def leases(self) -> tuple[dict[str, Any], ...]:
        """Read model of current and recent leases (newest last)."""
        with self._condition:
            items = [*self._recent]
            for lease in (self._holder, *self._waiters):
                if lease is not None and lease not in items:
                    items.append(lease)
            return tuple(lease.view() for lease in items)

    def reap_held(self) -> None:
        """Retry the exit ACK of a held lease; raise its code while the worker lives."""
        with self._condition:
            holder = self._holder
        if holder is None or holder.state != "REAP_PENDING" or holder.ack_code is None:
            return
        holder.reap()
        self._released(holder)

    def held(self) -> tuple[str, ...]:
        """Job ids whose lease still occupies the slot (active or awaiting exit ACK)."""
        with self._condition:
            holder = self._holder
            return () if holder is None else (holder.job_id,)

    def _watch_held(self) -> None:
        """Start the reaper for a slot whose worker exit ACK failed (G11BR-03)."""
        with self._condition:
            if self._reaper is not None:
                return
            self._reaper = threading.Thread(
                target=self._reap_loop, name="recoryn-lease-reaper", daemon=True
            )
            self._reaper.start()

    def _reap_loop(self) -> None:
        """Release a held slot only after its worker really exited (lock-free check)."""
        while True:
            with self._condition:
                holder = self._holder
                if holder is None or holder.state != "REAP_PENDING" or holder.ack_code is None:
                    self._reaper = None  # decided under the lock that _watch_held reads
                    return
                self._condition.wait(self.reap_interval)
                if self._holder is not holder:
                    continue
            if not holder.child_live():
                self._try_ack(holder)

    def _try_ack(self, holder: Lease) -> None:
        try:
            holder.reap()
        except Exception:
            return
        self._released(holder)

    def _released(self, holder: Lease) -> None:
        with self._condition:
            if self._holder is not holder:
                return
            self._holder = None
            self._recent.append(holder)
            self._condition.notify_all()
        callback, holder.on_ack = holder.on_ack, None
        if callback is not None:
            try:
                callback()
            except Exception:
                pass  # an idempotent receipt; a later reader recovery still applies

    def _grant(self, lease: Lease, cancel: threading.Event) -> None:
        while True:
            with self._condition:
                if cancel.is_set():
                    self._waiters.remove(lease)
                    lease.record("cancel")
                    self._condition.notify_all()
                    raise StateConflict("RESOURCE_CANCELLED")
                holder = self._holder
                if holder is None and self._waiters[0] is lease:
                    self._waiters.popleft()
                    self._holder = lease
                    lease.state = "GRANTED_NO_CHILD"
                    return
                # A held slot: its owner's reap already failed (not one in progress).
                stuck = (
                    holder is not None
                    and holder.state == "REAP_PENDING"
                    and holder.ack_code is not None
                )
                if not stuck:
                    self._condition.wait(0.05)
                    continue
            assert holder is not None
            self._try_ack(holder)
            with self._condition:
                if self._holder is holder:
                    self._waiters.remove(lease)
                    lease.state = "REAP_ACKED"
                    self._recent.append(lease)
                    self._condition.notify_all()
                    raise StateConflict(LEASE_HELD)

    @contextmanager
    def lease(
        self,
        request: ResourceRequest,
        *,
        cancel: threading.Event,
        job_id: str = "",
        attempt_id: str = "",
        session_id: str = "",
        source: ResourceSource = NO_SOURCE,
        device: str | None = None,
        on_ack: Callable[[], None] | None = None,
    ) -> Iterator[Lease]:
        """Grant the owned-heavy slot, re-observe and plan, then reap before release.

        Order (G11 section 5.1): runner entry -> grant/re-observe -> worker creation
        (``Lease.open``) -> inference -> worker exit ACK -> release.
        """
        lease = Lease(request, job_id=job_id, attempt_id=attempt_id, session_id=session_id)
        lease.on_ack = on_ack
        with self._condition:
            self._waiters.append(lease)
        self._grant(lease, cancel)
        failure: BaseException | None = None
        try:
            lease.plan = self.plan(request, self.observe(request, source, device), device=device)
            yield lease
        except BaseException as error:
            failure = error
            event = (
                "cancel"
                if cancel.is_set()
                else "unknown_result"
                if getattr(error, "outcome_known", True) is False
                else "local_error"
            )
            if (lease.state, event) not in LEASE_TRANSITIONS:
                event = "local_error"
            if (lease.state, event) in LEASE_TRANSITIONS:
                lease.record(event)
            raise
        finally:
            try:
                lease.reap()
            except Exception as error:
                self._watch_held()
                if failure is None or getattr(failure, "outcome_known", True) is not False:
                    held = StateConflict(lease.ack_code or LEASE_HELD)
                    # The runner keeps the Job local reader active until on_ack, so
                    # deletion/recovery wait for the real exit (never seal/finalize).
                    held.reader_retained = True  # type: ignore[attr-defined]
                    raise held from error
                # A logical UNKNOWN is kept as raised, and so is the physical wait for
                # the worker's exit: the reader stays until on_ack (G11BR-04).
                try:
                    failure.reader_retained = True  # type: ignore[attr-defined]
                except AttributeError:
                    pass
            else:
                lease.on_ack = None
                with self._condition:
                    if self._holder is lease:
                        self._holder = None
                    self._recent.append(lease)
                    self._condition.notify_all()


def check_facts(plan: ResourcePlan, worker: Any, context: Any = None) -> None:
    """Load the worker's model and compare its real device facts before inference.

    ``load(context)`` loads without inferring (STT); ``device_facts()`` reports a fixed
    CPU-only backend (diarization). A worker with neither (an in-process test double)
    has no facts to check; every owned product worker has one.
    """
    load = getattr(worker, "load", None)
    declared = getattr(worker, "device_facts", None)
    if callable(load):
        facts = load(context)
    elif callable(declared):
        facts = declared()
    else:
        return
    if not facts_match(plan, facts):
        raise StateConflict(DEVICE_MISMATCH)
