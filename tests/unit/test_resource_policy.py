"""G11 / G-P11a static device policy: A36, C001-016, C097-100, T19, T20.

Every expected value below is transcribed by hand from the G11 contract (section 3.1 table,
section 6 code table, G-P07 decision rules). Nothing here imports the product catalog,
CODE_GROUPS or a decision function to build an expectation.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import replace
from itertools import product
from pathlib import Path
from typing import Any

import pytest

import recoryn.models.resources as resources_module
from recoryn.app.ai import AIService
from recoryn.content import ContentStore
from recoryn.domain import StateConflict, ValidationError
from recoryn.jobs import JobStore
from recoryn.jobs.runner import BoundedRunner
from recoryn.models import GPUInfo, ResourcePlan, ResourceRequest, plan_static
from recoryn.providers import ProviderCapabilities, ProviderError
from recoryn.storage import Library
from tests.e2e.test_ai_workflow import FakeSTT, FakeSummary, finished, recording

POLICIES = ("CPU_ONLY", "GPU_ONLY", "GPU_WITH_CPU_FALLBACK_ALLOWED")
KINDS = ("stt", "summary", "diarization")
BACKENDS = ("LOCAL_CT2", "LOCAL_SHERPA", "OLLAMA", "REMOTE")
U, PV, GU = "CAPABILITY_UNSUPPORTED", "RESOURCE_POLICY_UNVERIFIED", "RESOURCE_GPU_UNSUPPORTED"
NA, SU = "not_applicable", "server_unknown"
# G11 section 3.1, by hand: (kind, backend) -> (CPU_ONLY, GPU_ONLY, FALLBACK).
TABLE = {
    ("stt", "LOCAL_CT2"): ("cpu", "cuda", "auto"),
    ("stt", "LOCAL_SHERPA"): (U, U, U),
    ("stt", "OLLAMA"): (U, U, U),
    ("stt", "REMOTE"): (NA, NA, NA),
    ("summary", "LOCAL_CT2"): (U, U, U),
    ("summary", "LOCAL_SHERPA"): (U, U, U),
    ("summary", "OLLAMA"): (PV, PV, SU),
    ("summary", "REMOTE"): (NA, NA, NA),
    ("diarization", "LOCAL_CT2"): (U, U, U),
    ("diarization", "LOCAL_SHERPA"): ("cpu", GU, "cpu"),
    ("diarization", "OLLAMA"): (U, U, U),
    ("diarization", "REMOTE"): (U, U, U),
}
REFUSALS = {U, PV, GU}
A = list(product(POLICIES, KINDS, BACKENDS))
A_IDS = [f"G11-A-{n:02}" for n in range(1, 37)]


def expected(policy: str, kind: str, backend: str) -> str:
    return TABLE[(kind, backend)][POLICIES.index(policy)]


# G11 section 6 + G-P07: both P11a codes are CAPABILITY; unknown outcome outranks it.
C_CODES = ("RESOURCE_POLICY_UNVERIFIED", "RESOURCE_GPU_UNSUPPORTED")
C = list(product(C_CODES, (False, True), (False, True), ("direct", "runner")))
C_IDS = [f"G11-C-{n:03}" for n in range(1, 17)]
C_PENDING = list(product(C_CODES, ("matching", "mismatching")))
C_PENDING_IDS = [f"G11-C-{n:03}" for n in range(97, 101)]
T_IDS = ("G11-T-19", "G11-T-20")


def test_family_manifest() -> None:
    assert len(A) == len(set(A)) == 3 * 3 * 4 == len(A_IDS) == 36
    assert len(C) == len(set(C)) == 16 and len(C_PENDING) == 4
    assert {expected(*row) for row in A} == {"cpu", "cuda", "auto", NA, SU, U, PV, GU}
    assert sum(expected(*row) in REFUSALS for row in A) == 36 - 3 - 6 - 1 - 2  # 24 refused


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Any]:
    root = tmp_path_factory.mktemp("g11a-unit")
    with Library(root / "library") as library, ContentStore(library) as content:
        session = recording(library)
        service = AIService(library, content)
        try:
            seed = service.transcribe(
                session,
                FakeSTT(),
                config_key="seed",
                resource_request=ResourceRequest("stt", "LOCAL_CT2", "CPU_ONLY"),
            )
            assert finished(service, seed).state.value == "SUCCEEDED"
            yield service, session
        finally:
            service.close()


class Counting:
    """A provider that records every call; a refused admission must leave it untouched."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.stt, self.summary = FakeSTT(), FakeSummary()

    def capabilities(self) -> ProviderCapabilities:
        self.calls.append("capabilities")
        return ProviderCapabilities("fake", transcription=True, summarization=True)

    def transcribe(self, request: Any, context: Any = None) -> Any:
        self.calls.append("transcribe")
        return self.stt.transcribe(request, context)

    def summarize(self, request: Any, context: Any = None) -> Any:
        self.calls.append("summarize")
        return self.summary.summarize(request, context)


def submit(service: AIService, session: str, request: ResourceRequest, key: str, provider: Any):
    if request.kind == "stt":
        return service.transcribe(session, provider, config_key=key, resource_request=request)
    if request.kind == "summary":
        return service.summarize(session, provider, config_key=key, resource_request=request)
    return service.admit_diarization(request)


@pytest.mark.parametrize("row", A, ids=A_IDS)
def test_a_static_table_and_service_admission(world: Any, row: tuple[str, str, str]) -> None:
    policy, kind, backend = row
    service, session = world
    outcome = expected(*row)
    request = ResourceRequest(kind, backend, policy)
    provider = Counting()
    jobs_before = service.jobs.list_for_session(session)
    case = A_IDS[A.index(row)]
    if outcome in REFUSALS:
        with pytest.raises(StateConflict, match=f"^{outcome}$"):
            plan_static(request)
        # The direct product API refuses before any Job, read or provider call.
        with pytest.raises(StateConflict, match=f"^{outcome}$"):
            submit(service, session, request, case, provider)
        assert service.jobs.list_for_session(session) == jobs_before
        assert provider.calls == []
        return
    plan = plan_static(request)
    assert type(plan) is ResourcePlan and plan.request_digest == request.digest
    assert plan.device == outcome
    owned = outcome in {"cpu", "cuda", "auto"}
    # G11R-06: the owned stage and the policy's applicability are separate facts;
    # an allowed Ollama is under the policy yet has no owned stage, REMOTE has neither.
    assert plan.owned is owned
    assert plan.policy_applies is (outcome != NA)
    # An owned path without a profile is the display state, never an error (G11 4.1).
    assert plan.estimate_status == ("RESOURCE_ESTIMATE_UNKNOWN" if owned else outcome.upper())
    result = submit(service, session, request, case, provider)
    if kind == "diarization":
        assert result is request
        return
    done = finished(service, result)
    assert service.resource_request(result) is request
    if outcome == "cuda":
        # G-P11b: this service observes nothing, so GPU_ONLY has no CUDA source at
        # dispatch: refused with the existing code, never run on a CPU instead.
        assert (done.state.value, done.blocked_reason, done.error_code) == (
            "BLOCKED",
            "RESOURCE",
            "RESOURCE_GPU_UNAVAILABLE",
        )
        assert provider.calls.count("transcribe") == 0
        return
    assert done.state.value == "SUCCEEDED"  # CPU, fallback-to-CPU, server, remote
    assert provider.calls.count("transcribe" if kind == "stt" else "summarize") == 1


@pytest.mark.parametrize(
    "value",
    [
        dict(kind="STT"),
        dict(backend="CT2"),
        dict(policy="AUTO"),
        dict(priority=True),
        dict(priority=3),
        dict(model_identity=""),
        dict(model_identity="a\x00b"),
        dict(preferred_gpu=0),
        dict(input_envelope=[("frames", 1)]),
        dict(input_envelope=(("frames", -1),)),
        dict(input_envelope=(("frames", True),)),
    ],
    ids=lambda value: "G11-AUX-DTO-" + "-".join(f"{k}" for k in value),
)
def test_request_dto_is_strict(value: dict[str, Any]) -> None:
    fields: dict[str, Any] = dict(kind="stt", backend="LOCAL_CT2", policy="CPU_ONLY")
    fields.update(value)
    with pytest.raises(ValidationError, match="^INVALID_RESOURCE_REQUEST$"):
        ResourceRequest(**fields)


def test_plan_static_requires_the_request_type() -> None:
    for wrong in (None, object(), ("stt", "LOCAL_CT2", "CPU_ONLY")):
        with pytest.raises(ValidationError, match="^INVALID_RESOURCE_REQUEST$"):
            plan_static(wrong)  # type: ignore[arg-type]


def test_service_requires_a_typed_matching_request(world: Any) -> None:
    service, session = world
    before = service.jobs.list_for_session(session)
    provider = Counting()
    with pytest.raises(TypeError):
        service.transcribe(session, provider, config_key="missing")  # type: ignore[call-arg]
    for wrong in (None, "CPU_ONLY", ResourceRequest("summary", "REMOTE", "CPU_ONLY")):
        with pytest.raises(ValidationError, match="^INVALID_RESOURCE_REQUEST$"):
            service.transcribe(session, provider, config_key="wrong", resource_request=wrong)  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="^INVALID_RESOURCE_REQUEST$"):
        service.summarize(
            session,
            provider,
            config_key="wrong",
            resource_request=ResourceRequest("stt", "REMOTE", "CPU_ONLY"),
        )
    with pytest.raises(ValidationError, match="^INVALID_RESOURCE_REQUEST$"):
        service.admit_diarization(ResourceRequest("stt", "LOCAL_CT2", "CPU_ONLY"))
    assert service.jobs.list_for_session(session) == before and provider.calls == []


def test_estimate_unknown_is_a_display_state_not_an_error_code() -> None:
    from recoryn.jobs.failures import CODE_GROUPS, normalize_failure

    assert "RESOURCE_ESTIMATE_UNKNOWN" not in CODE_GROUPS
    assert normalize_failure(StateConflict("RESOURCE_ESTIMATE_UNKNOWN")).code == "TASK_FAILED"


def _job(store: JobStore, name: str) -> Any:
    return store.create("summarization", name)


@pytest.mark.parametrize("row", C, ids=C_IDS)
def test_c_new_codes_fail_and_runner(tmp_path: Path, row: tuple[str, bool, bool, str]) -> None:
    code, retryable, known, call = row
    with JobStore(tmp_path / "jobs.sqlite") as store:
        job = _job(store, "c")
        if call == "direct":
            attempt = store.claim(job.job_id, "worker")
            old = store.get(job.job_id)
            after = store.fail(
                job.job_id, attempt.attempt_id, attempt.fence, code, retryable, known
            )
            assert after.fence == old.fence + 1 and after.state_version == old.state_version + 1
        else:
            runner = BoundedRunner(store)
            runner.start()
            try:

                def task(attempt: Any, cancel: Any) -> str:
                    raise ProviderError(code, retryable=retryable, outcome_known=known)

                assert runner.submit(job.job_id, task)
                # Wait for the runner to finish its own bookkeeping, not just the DB state:
                # stop() cancels work still listed active, even right after fail() wrote
                # BLOCKED (same pattern as tests/unit/test_runner.py::idle).
                with runner._condition:
                    assert runner._condition.wait_for(
                        lambda: not runner._queue and not runner._active, timeout=10
                    )
            finally:
                runner.stop()
            after = store.get(job.job_id)
        reason = "CAPABILITY" if known else "REMOTE_UNKNOWN"
        assert (after.state.value, after.blocked_reason) == ("BLOCKED", reason)
        assert after.attempt_count == 1
        if known:
            assert after.error_code == code


@pytest.mark.parametrize("row", C_PENDING, ids=C_PENDING_IDS)
def test_c_new_codes_block_pending(tmp_path: Path, row: tuple[str, str]) -> None:
    code, match = row
    with JobStore(tmp_path / "jobs.sqlite") as store:
        job = _job(store, "pending")
        before = store.get(job.job_id)
        if match == "matching":
            after = store.block_pending(
                job.job_id, "CAPABILITY", code, expected_version=before.state_version
            )
            assert (after.state.value, after.blocked_reason, after.error_code) == (
                "BLOCKED",
                "CAPABILITY",
                code,
            )
            assert after.attempt_count == before.attempt_count == 0
            assert store._db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0
        else:
            with pytest.raises(ValidationError, match="^BLOCK_REASON_MISMATCH$"):
                store.block_pending(
                    job.job_id, "RESOURCE", code, expected_version=before.state_version
                )
            assert store.get(job.job_id) == before


class SelfReportingOllama(Counting):
    """A server that claims a full GPU load and accepts num_gpu; neither is evidence."""

    reported = {"size": 4096, "size_vram": 4096, "options": {"num_gpu": 999}}

    def ps(self) -> dict[str, Any]:
        self.calls.append("ps")
        return self.reported


@pytest.mark.parametrize("case", T_IDS, ids=T_IDS)
def test_t_ollama_self_report_and_num_gpu_are_not_strict_evidence(
    world: Any, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    service, session = world
    observed: list[str] = []

    def plenty() -> tuple[str, tuple[GPUInfo, ...]]:
        observed.append("probe")
        return "OBSERVED", (GPUInfo(0, "fixture", 1 << 40, 1 << 40),)

    # A local GPU with ample memory is observed (T19); it must not be read as an Ollama
    # device guarantee, and no probe is needed for the static decision at all.
    monkeypatch.setattr(resources_module, "probe_gpus", plenty)
    before = service.jobs.list_for_session(session)
    for policy in ("CPU_ONLY", "GPU_ONLY"):
        provider = SelfReportingOllama()
        fields: dict[str, Any] = {}
        if case == "G11-T-20":
            fields = dict(runtime_identity="ollama;num_gpu=999", model_identity="gpu-100%")
        request = ResourceRequest("summary", "OLLAMA", policy, **fields)
        with pytest.raises(StateConflict, match="^RESOURCE_POLICY_UNVERIFIED$"):
            service.summarize(session, provider, config_key=case + policy, resource_request=request)
        assert provider.calls == []  # no ps, capabilities or summarize (transport 0)
    with pytest.raises(TypeError):
        ResourceRequest("summary", "OLLAMA", "GPU_ONLY", gpu_fraction=1.0)  # type: ignore[call-arg]
    assert observed == [] and service.jobs.list_for_session(session) == before


# =====================================================================================
# G-P11b: P cube, E, C017-096 + C101-120, T rows, lease transitions, G11R auxiliaries.
# Every expectation below is hand-written from G11 sections 4.3, 5 and 6; the product
# plan/lease functions are only ever the thing under test.
# =====================================================================================

from recoryn.models.resource_catalog import MemoryProfile  # noqa: E402
from recoryn.models.resources import (  # noqa: E402
    LEASE_EVENTS,
    LEASE_STATES,
    NOT_OBSERVED,
    OBSERVED,
    UNAVAILABLE,
    UNKNOWN,
    GpuDevice,
    GpuObservation,
    Lease,
    MemoryObservation,
    ResourceScheduler,
    ResourceSnapshot,
    ResourceSource,
    plan_resources,
)
from tests.resource_fakes import Observer, profile  # noqa: E402

NATIVE = ResourceSource("native", "READY")
# P fixture (section 7.1): CPU host 100, GPU host 100, VRAM 80, RAM headroom 20, GPU 10.
RAM_HEAD, GPU_HEAD = 20, 10
GPU_BOUNDS = (9, 10, 11, 89, 90, 91)
RAM_BOUNDS = (0, 119, 120, 121)
PROBES = (OBSERVED, UNKNOWN, UNAVAILABLE)
PROFILE_STATES = ("both_known", "gpu_unknown", "cpu_unknown", "both_unknown")
P = list(product(POLICIES, KINDS, BACKENDS, PROBES, PROBES, GPU_BOUNDS, RAM_BOUNDS, PROFILE_STATES))
P_IDS = [f"G11-P-{n:05}" for n in range(1, len(P) + 1)]
MI, CPI, CPU_PROBE_U, CPU_PROBE_NA = (
    "RESOURCE_MEMORY_INSUFFICIENT",
    "RESOURCE_CPU_PROBE_UNKNOWN",
    "RESOURCE_CPU_PROBE_UNKNOWN",
    "RESOURCE_CPU_PROBE_UNAVAILABLE",
)
GPU_PROBE = {UNKNOWN: "RESOURCE_GPU_PROBE_UNKNOWN", UNAVAILABLE: "RESOURCE_GPU_PROBE_UNAVAILABLE"}
CPU_PROBE = {UNKNOWN: "RESOURCE_CPU_PROBE_UNKNOWN", UNAVAILABLE: "RESOURCE_CPU_PROBE_UNAVAILABLE"}


def p_oracle(row: tuple[Any, ...]) -> tuple[Any, ...]:
    """(outcome, device-or-code, estimate, planned_ram, planned_vram) by hand."""
    policy, kind, backend, gprobe, rprobe, gfree, rfree, state = row
    static = expected(policy, kind, backend)
    if static in REFUSALS:
        return ("refused", static)
    if static in (NA, SU):
        return ("plan", static, static.upper(), None, None)
    sherpa = backend == "LOCAL_SHERPA"
    cpu_req = 100 if state in ("both_known", "gpu_unknown") else None
    gpu_known = not sherpa and state in ("both_known", "cpu_unknown")

    def ram_ok(required: int) -> str | None:
        if rprobe != OBSERVED:
            return CPU_PROBE[rprobe]
        return None if rfree >= required + RAM_HEAD else MI

    def cpu() -> tuple[Any, ...]:
        if cpu_req is None:
            return ("plan", "cpu", "RESOURCE_ESTIMATE_UNKNOWN", None, None)
        failure = ram_ok(cpu_req)
        if failure:
            return ("refused", failure)
        return ("plan", "cpu", "RESOURCE_ESTIMATE_KNOWN", 100, None)

    def gpu() -> tuple[Any, ...]:
        if gprobe != OBSERVED:
            return ("refused", GPU_PROBE[gprobe])
        if gfree < (80 + GPU_HEAD if gpu_known else GPU_HEAD):
            return ("refused", MI)
        if gpu_known:
            failure = ram_ok(100)
            if failure:
                return ("refused", failure)
            return ("plan", "cuda", "RESOURCE_ESTIMATE_KNOWN", 100, 80)
        return ("plan", "cuda", "RESOURCE_ESTIMATE_UNKNOWN", None, None)

    if static == "cpu":
        return cpu()
    if static == "cuda":
        return gpu()
    first = gpu()
    return first if first[0] == "plan" else cpu()


def _p_profiles(kind: str, backend: str, state: str) -> tuple[MemoryProfile, ...]:
    owned = {("stt", "LOCAL_CT2"), ("diarization", "LOCAL_SHERPA")}
    if (kind, backend) not in owned or state == "both_unknown":
        return ()
    cpu = 100 if state in ("both_known", "gpu_unknown") else None
    gpu = backend == "LOCAL_CT2" and state in ("both_known", "cpu_unknown")
    return (
        profile(
            "p-" + state,
            kind=kind,
            backend=backend,
            cpu=cpu,
            gpu_host=100 if gpu else None,
            gpu=80 if gpu else None,
        ),
    )


def _p_snapshot(now: int, gprobe: str, rprobe: str, gfree: int, rfree: int) -> ResourceSnapshot:
    device = GpuDevice("GPU-A", 0, 0, "fixture", gfree, 1000)
    observed = GpuObservation(OBSERVED, now - 1, (device,), True, "fixture")
    ram = MemoryObservation(OBSERVED, now - 1, rfree, 1000, "fixture")
    # A failed probe has no current value; the boundary value is only in the cache.
    return ResourceSnapshot(
        now,
        observed if gprobe == OBSERVED else GpuObservation(gprobe),
        ram if rprobe == OBSERVED else MemoryObservation(rprobe),
        NATIVE,
        last_gpu=observed,
        last_ram=ram,
    )


def test_p_cube_matches_the_independent_plan_model() -> None:
    """G11-P-00001..31104, batched: every tuple and ID, no Qt or process."""
    now = 10_000_000_000
    profiles: dict[tuple[str, str, str], tuple[MemoryProfile, ...]] = {}
    mismatches: list[tuple[str, Any, Any]] = []
    for case, row in zip(P_IDS, P, strict=True):
        policy, kind, backend, gprobe, rprobe, gfree, rfree, state = row
        key = (kind, backend, state)
        if key not in profiles:
            profiles[key] = _p_profiles(kind, backend, state)
        request = ResourceRequest(
            kind,
            backend,
            policy,
            model_identity="model-fixture",
            runtime_identity="runtime-fixture",
        )
        snapshot = _p_snapshot(now, gprobe, rprobe, gfree, rfree)
        try:
            plan = plan_resources(
                request,
                snapshot,
                now_ns=now,
                profiles=profiles[key],
                ram_headroom=RAM_HEAD,
                gpu_headroom=GPU_HEAD,
            )
            actual: tuple[Any, ...] = (
                "plan",
                plan.device,
                plan.estimate_status,
                plan.planned_ram,
                plan.planned_vram,
            )
        except StateConflict as error:
            actual = ("refused", str(error))
        want = p_oracle(row)
        if actual != want:
            mismatches.append((case, want, actual))
    assert len(P) == len(set(P)) == 31_104
    assert mismatches == [], mismatches[:5]


# --- E: explicit profile application, artifacts, envelopes ------------------------------
E_STATES = ("matching", "none", "artifact", "runtime", "envelope", "record")
E = list(product(("stt", "diarization"), ("cpu", "cuda"), E_STATES, (99, 100, 101)))
E_IDS = [f"G11-E-{n:02}" for n in range(1, 73)]


def e_oracle(row: tuple[Any, ...]) -> tuple[Any, ...]:
    kind, device, state, frames = row
    if kind == "diarization" and device == "cuda":
        return ("refused", GU)
    if state == "none":
        return ("plan", device, "RESOURCE_ESTIMATE_UNKNOWN", None)
    if state != "matching" or frames > 100:
        return ("refused", "RESOURCE_PROFILE_MISMATCH")
    # CPU and CUDA host requirements differ, so the device's own number is read.
    return ("plan", device, "RESOURCE_ESTIMATE_KNOWN", 100 if device == "cpu" else 150)


@pytest.mark.parametrize("row", E, ids=E_IDS)
def test_e_profiles_are_applied_or_refused_never_downgraded(row: tuple[Any, ...]) -> None:
    kind, device, state, frames = row
    backend = "LOCAL_CT2" if kind == "stt" else "LOCAL_SHERPA"
    stt = kind == "stt"
    good = profile(
        "e-profile",
        kind=kind,
        backend=backend,
        model="model-E",
        runtime="runtime-E",
        envelope=(("frames", 100),),
        cpu=100,
        gpu_host=150 if stt else None,
        gpu=80 if stt else None,
    )
    variants = {
        "matching": good,
        "artifact": replace(good, model_identity="model-other"),
        "runtime": replace(good, runtime_identity="runtime-other"),
        "envelope": replace(good, envelope=(("beam", 100),)),
        "record": replace(good, evidence="not-a-hash"),
    }
    chosen = variants.get(state)
    if chosen is not None and state != "record":
        chosen = profile(
            chosen.profile_id,
            kind=kind,
            backend=backend,
            model=chosen.model_identity,
            runtime=chosen.runtime_identity,
            envelope=chosen.envelope,
            cpu=chosen.cpu_host_ram,
            gpu_host=chosen.gpu_host_ram,
            gpu=chosen.gpu_bytes,
        )
    request = ResourceRequest(
        kind,
        backend,
        "CPU_ONLY" if device == "cpu" else "GPU_ONLY",
        model_identity="model-E",
        runtime_identity="runtime-E",
        profile_identity=None if chosen is None else "e-profile",
        input_envelope=(("frames", frames),),
    )
    now = 10_000_000_000
    gpu = GpuDevice("GPU-A", 0, 0, "fixture", 10_000, 10_000)
    snapshot = ResourceSnapshot(
        now,
        GpuObservation(OBSERVED, now - 1, (gpu,), True, "fixture"),
        MemoryObservation(OBSERVED, now - 1, 10_000, 10_000, "fixture"),
        NATIVE,
    )
    try:
        plan = plan_resources(
            request,
            snapshot,
            now_ns=now,
            profiles=() if chosen is None else (chosen,),
            ram_headroom=RAM_HEAD,
            gpu_headroom=GPU_HEAD,
        )
        actual: tuple[Any, ...] = ("plan", plan.device, plan.estimate_status, plan.planned_ram)
    except StateConflict as error:
        actual = ("refused", str(error))
    assert actual == e_oracle(row)


# --- C017-096 and C101-120: the ten resource codes -------------------------------------
RESOURCE_CODES = (
    "RESOURCE_PROFILE_MISMATCH",
    "RESOURCE_GPU_PROBE_UNKNOWN",
    "RESOURCE_GPU_PROBE_UNAVAILABLE",
    "RESOURCE_CPU_PROBE_UNKNOWN",
    "RESOURCE_CPU_PROBE_UNAVAILABLE",
    "RESOURCE_MEMORY_INSUFFICIENT",
    "RESOURCE_GPU_IDENTITY_UNVERIFIED",
    "RESOURCE_SNAPSHOT_STALE",
    "RESOURCE_LEASE_HELD",
    "RESOURCE_DEVICE_MISMATCH",
)
C_B = list(product(RESOURCE_CODES, (False, True), (False, True), ("direct", "runner")))
C_B_IDS = [f"G11-C-{n:03}" for n in range(17, 97)]
C_B_PENDING = list(product(RESOURCE_CODES, ("matching", "mismatching")))
C_B_PENDING_IDS = [f"G11-C-{n:03}" for n in range(101, 121)]


def _fail_through(store: JobStore, call: str, code: str, retryable: bool, known: bool) -> Any:
    job = store.create("transcription", "c")
    if call == "direct":
        attempt = store.claim(job.job_id, "worker")
        return store.fail(job.job_id, attempt.attempt_id, attempt.fence, code, retryable, known)
    runner = BoundedRunner(store)
    runner.start()
    try:

        def task(attempt: Any, cancel: Any) -> str:
            raise ProviderError(code, retryable=retryable, outcome_known=known)

        assert runner.submit(job.job_id, task)
        with runner._condition:
            assert runner._condition.wait_for(
                lambda: not runner._queue and not runner._active, timeout=10
            )
    finally:
        runner.stop()
    return store.get(job.job_id)


@pytest.mark.parametrize("row", C_B, ids=C_B_IDS)
def test_c_resource_codes_fail_and_runner(row: tuple[str, bool, bool, str]) -> None:
    code, retryable, known, call = row
    with JobStore(Path(":memory:")) as store:
        after = _fail_through(store, call, code, retryable, known)
        reason = "RESOURCE" if known else "REMOTE_UNKNOWN"
        assert (after.state.value, after.blocked_reason) == ("BLOCKED", reason)
        assert after.attempt_count == 1
        if known:
            assert after.error_code == code


@pytest.mark.parametrize("row", C_B_PENDING, ids=C_B_PENDING_IDS)
def test_c_resource_codes_block_pending(row: tuple[str, str]) -> None:
    code, match = row
    with JobStore(Path(":memory:")) as store:
        job = store.create("transcription", "pending")
        if match == "matching":
            after = store.block_pending(
                job.job_id, "RESOURCE", code, expected_version=job.state_version
            )
            assert (after.state.value, after.blocked_reason, after.error_code) == (
                "BLOCKED",
                "RESOURCE",
                code,
            )
            assert after.attempt_count == 0
        else:
            with pytest.raises(ValidationError, match="^BLOCK_REASON_MISMATCH$"):
                store.block_pending(
                    job.job_id, "CAPABILITY", code, expected_version=job.state_version
                )
            assert store.get(job.job_id) == job


# --- T rows that are pure DTO / plan / lease facts ----------------------------------------
T_UNIT = (
    "G11-T-01",
    "G11-T-02",
    "G11-T-03",
    "G11-T-04",
    "G11-T-05",
    "G11-T-06",
    "G11-T-07",
    "G11-T-08",
    "G11-T-09",
    "G11-T-10",
    "G11-T-11",
    "G11-T-12",
    "G11-T-13",
    "G11-T-14",
    "G11-T-15",
    "G11-T-21",
    "G11-T-22",
    "G11-T-24",
    "G11-T-25",
    "G11-T-26",
)


def _gpu(uuid: str = "GPU-A", ordinal: int = 0, host: int = 0, free: int = 1000) -> GpuDevice:
    return GpuDevice(uuid, ordinal, host, "fixture", free, 1000)


def _plan(request: ResourceRequest, snapshot: ResourceSnapshot, **options: Any) -> Any:
    return plan_resources(
        request,
        snapshot,
        now_ns=options.pop("now_ns", 10_000_000_000),
        ram_headroom=RAM_HEAD,
        gpu_headroom=GPU_HEAD,
        **options,
    )


def _code(call: Callable[[], Any]) -> str:
    try:
        call()
    except (StateConflict, ValidationError) as error:
        return str(error)
    return "ADMITTED"


@pytest.mark.parametrize("case", T_UNIT, ids=T_UNIT)
def test_t_types_identities_and_lifetimes(case: str) -> None:
    invalid = "INVALID_RESOURCE_OBSERVATION"
    now = 10_000_000_000
    gpu_policy = ResourceRequest("stt", "LOCAL_CT2", "GPU_ONLY")
    fresh_gpu = GpuObservation(OBSERVED, now - 1, (_gpu(),), True, "fixture")
    if case == "G11-T-01":  # required bytes = True
        with pytest.raises(ValidationError, match="INVALID_MEMORY_PROFILE"):
            profile("t1", cpu=True)  # type: ignore[arg-type]
        assert _code(lambda: _gpu(free=True)) == invalid  # type: ignore[arg-type]
    elif case == "G11-T-02":  # negative bytes
        with pytest.raises(ValidationError, match="INVALID_MEMORY_PROFILE"):
            profile("t2", cpu=-1)
        assert _code(lambda: _gpu(free=-1)) == invalid
        assert _code(lambda: MemoryObservation(OBSERVED, 1, -1, 10, "x")) == invalid
    elif case == "G11-T-03":  # i64 overflow
        with pytest.raises(ValidationError, match="INVALID_MEMORY_PROFILE"):
            profile("t3", cpu=2**63)
        assert _code(lambda: GpuDevice("U", 0, 0, "n", 2**63, 2**63)) == invalid
        assert _code(lambda: MemoryObservation(OBSERVED, 1, 1, 2**63, "x")) == invalid
        assert profile("t3-ok", cpu=2**63 - 1).cpu_host_ram == 2**63 - 1
    elif case == "G11-T-04":  # free > total
        assert _code(lambda: GpuDevice("U", 0, 0, "n", 11, 10)) == invalid
        assert _code(lambda: MemoryObservation(OBSERVED, 1, 11, 10, "x")) == invalid
    elif case == "G11-T-05":  # duplicate host index
        devices = (_gpu("A", 0, 0), _gpu("B", 1, 0))
        assert _code(lambda: GpuObservation(OBSERVED, 1, devices, True, "x")) == invalid
    elif case == "G11-T-06":  # duplicate UUID
        devices = (_gpu("A", 0, 0), _gpu("A", 1, 1))
        assert _code(lambda: GpuObservation(OBSERVED, 1, devices, True, "x")) == invalid
    elif case == "G11-T-07":  # CUDA index = True
        assert _code(lambda: GpuDevice("U", True, 0, "n", 1, 1)) == invalid  # type: ignore[arg-type]
    elif case == "G11-T-08":  # absent pinned UUID: never another GPU, CPU only by policy
        snapshot = ResourceSnapshot(now, fresh_gpu, source=NATIVE)
        pinned = replace(gpu_policy, preferred_gpu="GPU-ABSENT")
        assert _code(lambda: _plan(pinned, snapshot)) == "RESOURCE_GPU_UNAVAILABLE"
        fallback = replace(pinned, policy="GPU_WITH_CPU_FALLBACK_ALLOWED")
        assert _plan(fallback, snapshot).device == "cpu"
    elif case == "G11-T-09":  # NaN observation time
        assert _code(lambda: GpuObservation(OBSERVED, math.nan, (), True, "x")) == invalid  # type: ignore[arg-type]
        assert _code(lambda: MemoryObservation(OBSERVED, math.nan, 1, 1, "x")) == invalid  # type: ignore[arg-type]
    elif case == "G11-T-10":  # future observation, backward clock
        assert (
            _code(lambda: ResourceSnapshot(now, GpuObservation(OBSERVED, now + 1, (), True, "x")))
            == invalid
        )
        snapshot = ResourceSnapshot(now, fresh_gpu, source=NATIVE)
        assert (
            _code(lambda: _plan(gpu_policy, snapshot, now_ns=now - 1)) == "RESOURCE_SNAPSHOT_STALE"
        )
    elif case == "G11-T-11":  # TTL exact expiry is stale; one less is fresh
        old = GpuObservation(OBSERVED, now - 100, (_gpu(),), True, "x")
        snapshot = ResourceSnapshot(now, old, source=NATIVE)
        assert _code(lambda: _plan(gpu_policy, snapshot, ttl_ns=100)) == "RESOURCE_SNAPSHOT_STALE"
        assert _plan(gpu_policy, snapshot, ttl_ns=101).device == "cuda"
    elif case == "G11-T-12":  # an UNKNOWN probe cannot carry current values
        assert _code(lambda: GpuObservation(UNKNOWN, now, (_gpu(),), False, "x")) == invalid
        assert _code(lambda: MemoryObservation(UNKNOWN, now, 1, 1, "x")) == invalid
        cached = ResourceSnapshot(now, GpuObservation(UNKNOWN), source=NATIVE, last_gpu=fresh_gpu)
        assert _code(lambda: _plan(gpu_policy, cached)) == "RESOURCE_GPU_PROBE_UNKNOWN"
    elif case == "G11-T-13":  # CPU_ONLY never probes a GPU
        observer = Observer(
            lambda: GpuObservation(OBSERVED, time.monotonic_ns(), (_gpu(),), True, "x")
        )
        scheduler = ResourceScheduler(
            observe=observer, headroom_bytes=GPU_HEAD, ram_headroom_bytes=RAM_HEAD
        )
        plan = scheduler.prepare(ResourceRequest("stt", "LOCAL_CT2", "CPU_ONLY"), NATIVE)
        assert plan.device == "cpu" and observer.gpu_probes == 0
        assert scheduler.prepare(gpu_policy, NATIVE).device == "cuda" and observer.gpu_probes == 1
    elif case in ("G11-T-14", "G11-T-15"):  # explicit profile, other model / runtime
        good = profile("tp", model="model-T", runtime="runtime-T", cpu=100)
        wrong = (
            profile("tp", model="model-OTHER", runtime="runtime-T", cpu=100)
            if case == "G11-T-14"
            else profile("tp", model="model-T", runtime="runtime-OTHER", cpu=100)
        )
        request = ResourceRequest(
            "stt",
            "LOCAL_CT2",
            "CPU_ONLY",
            model_identity="model-T",
            runtime_identity="runtime-T",
            profile_identity="tp",
        )
        ram = MemoryObservation(OBSERVED, now - 1, 1000, 1000, "x")
        snapshot = ResourceSnapshot(now, ram=ram)
        assert _plan(request, snapshot, profiles=(good,)).planned_ram == 100
        assert (
            _code(lambda: _plan(request, snapshot, profiles=(wrong,)))
            == "RESOURCE_PROFILE_MISMATCH"
        )
    elif case == "G11-T-21":  # RELEASE of a child that did not exit: the slot stays held
        scheduler = ResourceScheduler()
        stuck = _StuckWorker()
        with pytest.raises(StateConflict, match="^INFERENCE_ACK_PENDING$"):
            with scheduler.lease(STT_CPU, cancel=threading.Event(), job_id="j1") as lease:
                lease.open(lambda plan: stuck)
        assert scheduler.held() == ("j1",) and stuck.is_live()
        opened: list[str] = []
        with pytest.raises(StateConflict, match="^RESOURCE_LEASE_HELD$"):
            with scheduler.lease(STT_CPU, cancel=threading.Event(), job_id="j2") as other:
                other.open(lambda plan: opened.append("j2"))
        assert opened == []
        stuck.allow = True
        scheduler.reap_held()
        assert scheduler.held() == () and not stuck.is_live()
    elif case == "G11-T-22":  # a cancelled waiter is never granted
        scheduler = ResourceScheduler()
        release, granted = threading.Event(), threading.Event()
        created: list[str] = []

        def holder() -> None:
            with scheduler.lease(STT_CPU, cancel=threading.Event(), job_id="h"):
                granted.set()
                assert release.wait(10)

        thread = threading.Thread(target=holder)
        thread.start()
        assert granted.wait(10)
        cancel = threading.Event()
        cancel.set()
        with pytest.raises(StateConflict, match="^RESOURCE_CANCELLED$"):
            with scheduler.lease(STT_CPU, cancel=cancel, job_id="w") as lease:
                lease.open(lambda plan: created.append("w"))
        release.set()
        thread.join(10)
        assert created == [] and scheduler.held() == ()
    elif case == "G11-T-24":  # invalid priority, at the request and at the runner
        for wrong in (True, -1, 3, 1.0):
            with pytest.raises(ValidationError, match="^INVALID_RESOURCE_REQUEST$"):
                ResourceRequest("stt", "LOCAL_CT2", "CPU_ONLY", priority=wrong)  # type: ignore[arg-type]
        with JobStore(Path(":memory:")) as store:
            runner = BoundedRunner(store)
            runner.start()
            try:
                job = store.create("transcription", "p")
                with pytest.raises(ValidationError, match="INVALID_RUNNER_PRIORITY"):
                    runner.submit(job.job_id, lambda *a: "x", priority=True)
            finally:
                runner.stop()
    elif case == "G11-T-25":  # UNKNOWN CPU profile, RAM probe UNKNOWN: admitted, shown
        snapshot = ResourceSnapshot(now, ram=MemoryObservation(UNKNOWN))
        plan = _plan(ResourceRequest("stt", "LOCAL_CT2", "CPU_ONLY"), snapshot)
        assert (plan.device, plan.estimate_status, plan.planned_ram) == (
            "cpu",
            "RESOURCE_ESTIMATE_UNKNOWN",
            None,
        )
        assert plan.ram_state == UNKNOWN
    elif case == "G11-T-26":  # UNKNOWN GPU profile, VRAM = headroom - 1: refused, no CPU
        snapshot = ResourceSnapshot(
            now,
            GpuObservation(OBSERVED, now - 1, (_gpu(free=GPU_HEAD - 1),), True, "x"),
            source=NATIVE,
        )
        assert _code(lambda: _plan(gpu_policy, snapshot)) == MI
        edge = ResourceSnapshot(
            now, GpuObservation(OBSERVED, now - 1, (_gpu(free=GPU_HEAD),), True, "x"), source=NATIVE
        )
        assert _plan(gpu_policy, edge).device == "cuda"


STT_CPU = ResourceRequest("stt", "LOCAL_CT2", "CPU_ONLY")


class _StuckWorker:
    def __init__(self) -> None:
        self.allow, self.alive = False, True

    def close(self) -> None:
        if not self.allow:
            raise ProviderError("INFERENCE_ACK_PENDING")
        self.alive = False

    def is_live(self) -> bool:
        return self.alive


# --- lease transition table (pure part of L) ---------------------------------------------
# Hand-written (G11 7.2): which (state, event) pairs are legal and where they lead.
L_TABLE = {
    "QUEUED": {"cancel": "REAP_ACKED"},
    "GRANTED_NO_CHILD": {"local_error": "REAP_PENDING", "cancel": "REAP_PENDING"},
    "CHILD_RUNNING": {
        "success_result": "INFERENCE_REPLIED",
        "local_error": "REAP_PENDING",
        "cancel": "REAP_PENDING",
        "unknown_result": "REAP_PENDING",
    },
    "INFERENCE_REPLIED": {
        "success_result": "INFERENCE_REPLIED",
        "local_error": "REAP_PENDING",
        "cancel": "REAP_PENDING",
        "unknown_result": "REAP_PENDING",
    },
    "REAP_PENDING": {
        "local_error": "REAP_PENDING",
        "cancel": "REAP_PENDING",
        "unknown_result": "REAP_PENDING",
    },
    "REAP_ACKED": {},
}


def test_lease_state_and_event_axes_are_the_contract_ones() -> None:
    assert LEASE_STATES == tuple(L_TABLE)
    assert LEASE_EVENTS == ("success_result", "local_error", "cancel", "unknown_result")


@pytest.mark.parametrize(
    "state,event", list(product(tuple(L_TABLE), LEASE_EVENTS)), ids=lambda v: str(v)
)
def test_lease_record_follows_the_table(state: str, event: str) -> None:
    """Auxiliary to L: the pure transition (the L rows add the real waiter/ACK trace)."""
    lease = Lease(STT_CPU)
    lease.state = state
    want = L_TABLE[state].get(event)
    if want is None:
        with pytest.raises(StateConflict, match="RESOURCE_LEASE_TRANSITION_INVALID"):
            lease.record(event)
        assert lease.state == state
    else:
        assert lease.record(event) == want
        assert lease.outcome_unknown is (event == "unknown_result")


# --- G11R auxiliaries ---------------------------------------------------------------------
@pytest.mark.parametrize(
    "fields",
    [
        dict(input_envelope=(("frames", 1), ("frames", 2))),
        dict(input_envelope=(("frames", 2**63),)),
    ],
    ids=["G11-AUX-DTO-duplicate-key", "G11-AUX-DTO-i64-bound"],
)
def test_request_envelope_duplicate_and_bound(fields: dict[str, Any]) -> None:
    """G11R-03 (R11, R12): a duplicate key and 2**63 are refused; 2**63 - 1 is not."""
    with pytest.raises(ValidationError, match="^INVALID_RESOURCE_REQUEST$"):
        ResourceRequest("stt", "LOCAL_CT2", "CPU_ONLY", **fields)
    assert ResourceRequest(
        "stt", "LOCAL_CT2", "CPU_ONLY", input_envelope=(("frames", 2**63 - 1),)
    ).input_envelope == (("frames", 2**63 - 1),)


class _Identified(Counting):
    def __init__(self, identity: str) -> None:
        super().__init__()
        self.identity = identity

    def capabilities(self) -> ProviderCapabilities:
        self.calls.append("capabilities")
        return ProviderCapabilities(self.identity, transcription=True, summarization=True)


@pytest.mark.parametrize(
    "identity,backend,kind",
    [
        ("ollama", "REMOTE", "summary"),
        ("faster_whisper", "REMOTE", "stt"),
        ("openai", "LOCAL_CT2", "stt"),
    ],
    ids=["G11-AUX-ID-ollama-as-remote", "G11-AUX-ID-local-as-remote", "G11-AUX-ID-remote-as-local"],
)
def test_registered_identity_must_match_the_requested_backend(
    world: Any, identity: str, backend: str, kind: str
) -> None:
    """G11R-01: a registered provider labelled with another backend is refused at admission."""
    service, session = world
    before = service.jobs.list_for_session(session)
    for policy in POLICIES:
        provider = _Identified(identity)
        request = ResourceRequest(kind, backend, policy)
        with pytest.raises(ValidationError, match="^INVALID_RESOURCE_REQUEST$"):
            submit(service, session, request, f"id-{identity}-{policy}", provider)
        assert provider.calls == ["capabilities"]
    assert service.jobs.list_for_session(session) == before


# --- the production observer, with every probe injected (no nvidia-smi, API or child) ---
def test_inventory_host_gpu_rows_are_parsed_or_unknown() -> None:
    """G11-AUX-INV-PARSE: one read-only query's rows; malformed output is UNKNOWN."""
    from recoryn.models import gpu_inventory

    class Done:
        def __init__(self, stdout: str) -> None:
            self.stdout = stdout

    def run_with(stdout: str) -> Callable[..., Any]:
        return lambda *args, **kwargs: Done(stdout)

    tool = lambda name: "nvidia-smi"  # noqa: E731
    good = "0, GPU-a, 0000:01:00.0, Card, 100, 200, Disabled\n1, GPU-b, 0000:02:00.0, Card, 50, 200, [N/A]\n"
    state, rows = gpu_inventory.host_gpus(run=run_with(good), which=tool)
    assert state == OBSERVED and [row.uuid for row in rows] == ["GPU-a", "GPU-b"]
    assert (rows[0].free_bytes, rows[0].total_bytes, rows[1].mig) == (
        100 * 2**20,
        200 * 2**20,
        "[N/A]",
    )
    assert gpu_inventory.host_gpus(run=run_with(good), which=lambda name: None) == (UNAVAILABLE, ())
    for bad in (
        "0, GPU-a, 0000:01:00.0, Card, 100\n",
        "0, GPU-a, 0000:01:00.0, Card, 300, 200, Disabled\n",
    ):
        assert gpu_inventory.host_gpus(run=run_with(bad), which=tool) == (UNKNOWN, ())

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise OSError("tool failed")

    assert gpu_inventory.host_gpus(run=broken, which=tool) == (UNKNOWN, ())


def test_inventory_identity_join_verifies_only_under_its_conditions() -> None:
    """G11-AUX-INV-JOIN: ordinals follow PCI bus order; each failed condition is UNVERIFIED."""
    from recoryn.models.gpu_inventory import HostGpu, join_identity

    rows = (
        HostGpu(0, "GPU-a", "0000:02:00.0", "Card", 10, 20, "Disabled"),
        HostGpu(1, "GPU-b", "0000:01:00.0", "Card", 10, 20, "Disabled"),
    )
    verified = join_identity(OBSERVED, rows, 2, {}, 5)
    assert verified.identity_verified and [
        (item.uuid, item.ordinal, item.host_index) for item in verified.devices
    ] == [
        ("GPU-b", 0, 1),
        ("GPU-a", 1, 0),
    ]
    cases = {
        "CUDA_VISIBLE_DEVICES": (rows, 2, {"CUDA_VISIBLE_DEVICES": "1"}),
        "MIG": ((replace(rows[0], mig="Enabled"), rows[1]), 2, {}),
        "UUID": ((rows[0], replace(rows[1], uuid="GPU-a")), 2, {}),
        "BUS_ID": ((rows[0], replace(rows[1], bus_id="0000:02:00.0")), 2, {}),
        "CUDA_COUNT_UNKNOWN": (rows, None, {}),
        "CUDA_COUNT": (rows, 1, {}),
    }
    for reason, (given, count, environ) in cases.items():
        observation = join_identity(OBSERVED, given, count, environ, 5)
        assert (observation.state, observation.identity_verified, observation.reason) == (
            OBSERVED,
            False,
            reason,
        )
    assert join_identity(UNKNOWN, rows, 2, {}, 5).state == UNKNOWN


def test_inventory_observes_only_what_the_plan_needs_and_caches_the_count() -> None:
    """G11-AUX-INV-NEEDS: nothing is probed when nothing is needed; the CUDA count child
    runs once per (source, runtime, remapping, host identities) and again on a change."""
    from recoryn.models.gpu_inventory import HostGpu, Inventory

    calls: list[str] = []
    host = [HostGpu(0, "GPU-a", "0000:01:00.0", "Card", 10, 20, "Disabled")]

    def memory() -> MemoryObservation:
        calls.append("memory")
        return MemoryObservation(OBSERVED, time.monotonic_ns(), 5, 10, "fake")

    def gpus() -> tuple[str, tuple[Any, ...]]:
        calls.append("gpus")
        return OBSERVED, tuple(host)

    def count(runtime: Any) -> int:
        calls.append("count")
        return len(host)

    inventory = Inventory(memory=memory, gpus=gpus, count=count, environ={})
    empty = inventory(False, False, NATIVE)
    assert (empty.gpu.state, empty.ram.state, calls) == (NOT_OBSERVED, NOT_OBSERVED, [])
    first = inventory(True, True, NATIVE)
    assert first.gpu.identity_verified and first.ram.state == OBSERVED
    second = inventory(True, False, NATIVE)
    assert calls == ["memory", "gpus", "count", "gpus"] and second.last_gpu is not None
    host.append(HostGpu(1, "GPU-b", "0000:02:00.0", "Card", 10, 20, "Disabled"))
    third = inventory(True, False, NATIVE)
    assert calls[-2:] == ["gpus", "count"] and len(third.gpu.devices) == 2
