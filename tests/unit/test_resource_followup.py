"""G-P11c F, TTL and A rows, the 87-row census and the G11BR-01 order delta.

Expectations are hand-written from the G-P11c scope section of the G11 contract (and
section 4.3 for the order). Product plan/fact/status functions are only under test.
"""

from __future__ import annotations

from itertools import product
from pathlib import Path
from typing import Any

import pytest

from recoryn.app.status import ai_status
from recoryn.domain import StateConflict
from recoryn.jobs import JobStore
from recoryn.jobs.failures import NormalizedFailure
from recoryn.models import ResourceRequest
from recoryn.models.resources import (
    OBSERVED,
    GpuDevice,
    GpuObservation,
    MemoryObservation,
    ResourceScheduler,
    ResourceSnapshot,
    ResourceSource,
    check_facts,
)
from tests.integration import test_resource_followup as integration
from tests.resource_fakes import profile
from tests.unit import test_resource_policy as policy_tests

NATIVE = ResourceSource("native", "READY")
TTL = 2_000_000_000  # G11 section 4.3: the proposed default, written by hand
# The request the known CPU profile describes (same model and runtime identity).
KNOWN_CPU = ResourceRequest(
    "stt",
    "LOCAL_CT2",
    "CPU_ONLY",
    model_identity="model-fixture",
    runtime_identity="runtime-fixture",
)


# --- F: plan device x reported device_index ----------------------------------------------
F_INDEX = (None, 0, 1, "0")
F = list(product(("cpu", "cuda"), F_INDEX))
F_IDS = [f"G11C-F-{n}" for n in range(1, 9)]


def f_oracle(row: tuple[str, Any]) -> bool:
    """True = facts accepted. A CPU reports no index or 0; CUDA reports its int ordinal 0."""
    device, index = row
    if device == "cpu":
        return index is None or (type(index) is int and index == 0)
    return type(index) is int and index == 0


class Loaded:
    def __init__(self, facts: dict[str, Any]) -> None:
        self.facts = facts

    def load(self, context: Any = None) -> dict[str, Any]:
        return self.facts


@pytest.mark.parametrize("row", F, ids=F_IDS)
def test_f_loaded_device_index_must_match_the_plan(row: tuple[str, Any]) -> None:
    device, index = row
    if device == "cpu":
        plan = _cpu_plan()
        compute = "int8"
    else:
        plan = _cuda_plan()
        compute = "float16"
    worker = Loaded({"device": device, "device_index": index, "compute_type": compute})
    if f_oracle(row):
        check_facts(plan, worker)
    else:
        with pytest.raises(StateConflict, match="^RESOURCE_DEVICE_MISMATCH$"):
            check_facts(plan, worker)


def _snapshot(now: int, age: int, *, gpu: bool) -> ResourceSnapshot:
    taken = now - age
    device = GpuDevice("GPU-A", 0, 0, "fixture", 1 << 30, 1 << 31)
    return ResourceSnapshot(
        now,
        GpuObservation(OBSERVED, taken, (device,), True, "fixture")
        if gpu
        else GpuObservation("NOT_OBSERVED"),
        MemoryObservation(OBSERVED, taken, 1 << 30, 1 << 31, "fixture"),
        NATIVE,
    )


def _cpu_plan() -> Any:
    now = 10 * TTL
    known = (profile("cpu-known", kind="stt", backend="LOCAL_CT2", cpu=100),)
    scheduler = ResourceScheduler(profiles=known, clock=lambda: now, ram_headroom_bytes=0)
    return scheduler.plan(KNOWN_CPU, _snapshot(now, 1, gpu=False))


def _cuda_plan() -> Any:
    now = 10 * TTL
    scheduler = ResourceScheduler(clock=lambda: now, headroom_bytes=0)
    return scheduler.plan(
        ResourceRequest("stt", "LOCAL_CT2", "GPU_ONLY"), _snapshot(now, 1, gpu=True)
    )


# --- TTL: observation age x device, at the default TTL --------------------------------
TTL_ROWS = list(product((TTL - 1, TTL, TTL + 1), ("known_cpu", "cuda")))
TTL_IDS = [f"G11C-TTL-{n}" for n in range(1, 7)]


@pytest.mark.parametrize("row", TTL_ROWS, ids=TTL_IDS)
def test_ttl_default_is_two_seconds(row: tuple[int, str]) -> None:
    age, device = row
    now = 10 * TTL
    if device == "known_cpu":
        known = (profile("cpu-known", kind="stt", backend="LOCAL_CT2", cpu=100),)
        scheduler = ResourceScheduler(profiles=known, clock=lambda: now, ram_headroom_bytes=0)
        request = KNOWN_CPU
    else:
        scheduler = ResourceScheduler(clock=lambda: now, headroom_bytes=0)
        request = ResourceRequest("stt", "LOCAL_CT2", "GPU_ONLY")
    snapshot = _snapshot(now, age, gpu=device == "cuda")
    if age < TTL:  # fresh strictly inside the TTL
        plan = scheduler.plan(request, snapshot)
        assert plan.device == ("cpu" if device == "known_cpu" else "cuda")
        if device == "known_cpu":  # the RAM observation really applied
            assert plan.estimate_status == "RESOURCE_ESTIMATE_KNOWN" and plan.planned_ram == 100
    else:
        with pytest.raises(StateConflict, match="^RESOURCE_SNAPSHOT_STALE$"):
            scheduler.plan(request, snapshot)


# --- A: code x entry -> action -----------------------------------------------------------
A_CODES = (
    "RESOURCE_POLICY_UNVERIFIED",
    "RESOURCE_GPU_UNSUPPORTED",
    "RESOURCE_GPU_UNAVAILABLE",
    "RESOURCE_MEMORY_INSUFFICIENT",
    "LANGUAGE_UNSUPPORTED",
)
A = list(product(A_CODES, ("preparation", "blocked_job")))
A_IDS = [f"G11C-A-{n:02}" for n in range(1, 11)]
A_ACTION = {  # G11 decision 6 and G11R-04, by hand
    "RESOURCE_POLICY_UNVERIFIED": "execution_policy",
    "RESOURCE_GPU_UNSUPPORTED": "execution_policy",
    "RESOURCE_GPU_UNAVAILABLE": "execution_policy",
    "RESOURCE_MEMORY_INSUFFICIENT": "resource",
    "LANGUAGE_UNSUPPORTED": "model",
}


@pytest.mark.parametrize("row", A, ids=A_IDS)
def test_a_policy_codes_point_at_the_execution_policy(row: tuple[str, str]) -> None:
    code, entry = row
    if entry == "preparation":
        status = ai_status(preparation=NormalizedFailure(code))
    else:
        with JobStore(Path(":memory:")) as store:
            job = store.create("transcription", code)
            attempt = store.claim(job.job_id, "worker")
            blocked = store.fail(job.job_id, attempt.attempt_id, attempt.fence, code)
            assert blocked.state.value == "BLOCKED"
            status = ai_status(blocked)
    assert status.action_id == A_ACTION[code]
    assert code in status.text


# --- census and the G11BR-01 delta ---------------------------------------------------------
FAMILIES = {
    "L": (integration.L_IDS, 24),
    "S": (integration.S_IDS, 15),
    "R": (integration.R_IDS, 24),
    "F": (F_IDS, 8),
    "TTL": (TTL_IDS, 6),
    "A": (A_IDS, 10),
}


def test_census_87_rows_once_each() -> None:
    every = [case for names, _ in FAMILIES.values() for case in names]
    assert len(every) == len(set(every)) == 87
    for names, size in FAMILIES.values():
        assert len(names) == len(set(names)) == size
    assert len(integration.L) == 24 and len(integration.S) == 15 and len(integration.R) == 24
    assert len(F) == 8 and len(TTL_ROWS) == 6 and len(A) == 10


def _old_order_gpu(row: tuple[Any, ...]) -> tuple[Any, ...]:
    """The pre-G-P11c GPU order (GPU observation -> VRAM -> host RAM), for the delta only."""
    policy, kind, backend, gprobe, rprobe, gfree, rfree, state = row
    gpu_known = backend != "LOCAL_SHERPA" and state in ("both_known", "cpu_unknown")
    if gprobe != OBSERVED:
        return ("refused", policy_tests.GPU_PROBE[gprobe])
    if gfree < (80 + policy_tests.GPU_HEAD if gpu_known else policy_tests.GPU_HEAD):
        return ("refused", policy_tests.MI)
    if gpu_known:
        if rprobe != OBSERVED:
            return ("refused", policy_tests.CPU_PROBE[rprobe])
        if rfree < 100 + policy_tests.RAM_HEAD:
            return ("refused", policy_tests.MI)
    return ("gpu-ok",)


def test_aux_contract_order_changes_exactly_the_reviewed_256_rows() -> None:
    """G11BR-01: only GPU_ONLY x LOCAL_CT2 x known GPU profile rows change code."""
    changed = []
    for case, row in zip(policy_tests.P_IDS, policy_tests.P, strict=True):
        policy, kind, backend, gprobe, rprobe, gfree, rfree, state = row
        if policy != "GPU_ONLY" or (kind, backend) != ("stt", "LOCAL_CT2"):
            continue
        new = policy_tests.p_oracle(row)
        old = _old_order_gpu(row)
        if new[0] == "refused" and old[0] == "refused" and new[1] != old[1]:
            changed.append((case, state))
    assert len(changed) == 256
    assert {state for _, state in changed} <= {"both_known", "cpu_unknown"}


# =====================================================================================
# G-P11d (G-P11c review G11CR-01, G11CR-03): O and TTL2 rows and the G11D census.
# =====================================================================================
O_REASONS = ("UUID", "BUS_ID", "CUDA_VISIBLE_DEVICES", "MIG", "CUDA_COUNT", "CUDA_COUNT_UNKNOWN")
O_PINS = ("pinned_absent", "auto_empty", "auto_present")
ORDER = list(product(O_REASONS, O_PINS))
O_IDS = [f"G11D-O-{n:02}" for n in range(1, 19)]


def o_oracle(row: tuple[str, str]) -> str:
    """G11 section 4.3 as corrected by G-P11d: a UUID/bus-id defect has no device identity,
    so absence is unknowable and the identity fails first; with remapping, MIG or a CUDA
    count problem the nvidia-smi host list is complete, so an absent or empty list is
    GPU_UNAVAILABLE and present devices fail on the identity."""
    reason, pin = row
    if reason in ("UUID", "BUS_ID"):
        return "RESOURCE_GPU_IDENTITY_UNVERIFIED"
    return (
        "RESOURCE_GPU_IDENTITY_UNVERIFIED" if pin == "auto_present" else "RESOURCE_GPU_UNAVAILABLE"
    )


@pytest.mark.parametrize("row", ORDER, ids=O_IDS)
def test_o_identity_or_absence_first_by_the_reason(row: tuple[str, str]) -> None:
    reason, pin = row
    now = 10 * TTL
    device = GpuDevice("GPU-A", 0, 0, "fixture", 1 << 30, 1 << 31)
    devices = () if pin == "auto_empty" else (device,)
    snapshot = ResourceSnapshot(
        now,
        GpuObservation(OBSERVED, now - 1, devices, False, "nvidia-smi", reason),
        MemoryObservation("NOT_OBSERVED"),
        NATIVE,
    )
    request = ResourceRequest(
        "stt", "LOCAL_CT2", "GPU_ONLY", preferred_gpu="GPU-Z" if pin == "pinned_absent" else None
    )
    scheduler = ResourceScheduler(clock=lambda: now, headroom_bytes=0)
    with pytest.raises(StateConflict) as refused:
        scheduler.plan(request, snapshot)
    assert str(refused.value) == o_oracle(row)


TTL2 = list(product((TTL - 1, TTL, TTL + 1), ("unknown_gpu", "known_gpu")))
TTL2_IDS = [f"G11D-TTL-{n}" for n in range(1, 7)]
KNOWN_GPU = ResourceRequest(
    "stt",
    "LOCAL_CT2",
    "GPU_ONLY",
    model_identity="model-fixture",
    runtime_identity="runtime-fixture",
)


@pytest.mark.parametrize("row", TTL2, ids=TTL2_IDS)
def test_ttl2_stale_ram_only_matters_for_a_known_gpu_requirement(row: tuple[int, str]) -> None:
    """Q03: a fresh GPU with stale RAM. An UNKNOWN GPU requirement applies no RAM at all
    (section 4.3), so it is never stale; a known requirement's RAM is (TTL by hand)."""
    ram_age, device = row
    now = 10 * TTL
    gpu = GpuDevice("GPU-A", 0, 0, "fixture", 1 << 30, 1 << 31)
    snapshot = ResourceSnapshot(
        now,
        GpuObservation(OBSERVED, now - 1, (gpu,), True, "fixture"),
        MemoryObservation(OBSERVED, now - ram_age, 1 << 30, 1 << 31, "fixture"),
        NATIVE,
    )
    if device == "unknown_gpu":
        scheduler = ResourceScheduler(clock=lambda: now, headroom_bytes=0)
        plan = scheduler.plan(ResourceRequest("stt", "LOCAL_CT2", "GPU_ONLY"), snapshot)
        assert plan.device == "cuda" and plan.estimate_status == "RESOURCE_ESTIMATE_UNKNOWN"
        return
    known = (profile("gpu-known", kind="stt", backend="LOCAL_CT2", gpu_host=100, gpu=80),)
    scheduler = ResourceScheduler(
        profiles=known, clock=lambda: now, headroom_bytes=0, ram_headroom_bytes=0
    )
    if ram_age < TTL:
        plan = scheduler.plan(KNOWN_GPU, snapshot)
        assert plan.device == "cuda" and plan.planned_ram == 100 and plan.planned_vram == 80
    else:
        with pytest.raises(StateConflict, match="^RESOURCE_SNAPSHOT_STALE$"):
            scheduler.plan(KNOWN_GPU, snapshot)


G11D_FAMILIES = {
    "O": (O_IDS, 18),
    "TTL": (TTL2_IDS, 6),
    "S": (integration.S2_IDS, 9),
    "C": (integration.C_IDS, 6),
}


def test_census_g11d_39_rows_once_each() -> None:
    every = [case for names, _ in G11D_FAMILIES.values() for case in names]
    assert len(every) == len(set(every)) == 39
    for names, size in G11D_FAMILIES.values():
        assert len(names) == len(set(names)) == size
    assert not set(every) & {case for names, _ in FAMILIES.values() for case in names}
    assert (
        len(ORDER) == 18 and len(TTL2) == 6 and len(integration.S2) == 9 and len(integration.C) == 6
    )
