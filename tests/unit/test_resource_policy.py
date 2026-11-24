"""G11 / G-P11a static device policy: A36, C001-016, C097-100, T19, T20.

Every expected value below is transcribed by hand from the G11 contract (section 3.1 table,
section 6 code table, G-P07 decision rules). Nothing here imports the product catalog,
CODE_GROUPS or a decision function to build an expectation.
"""

from __future__ import annotations

from collections.abc import Iterator
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
    assert plan.applies is owned
    # An owned path without a profile is the display state, never an error (G11 4.1).
    assert plan.estimate_status == ("RESOURCE_ESTIMATE_UNKNOWN" if owned else outcome.upper())
    result = submit(service, session, request, case, provider)
    if kind == "diarization":
        assert result is request
        return
    assert finished(service, result).state.value == "SUCCEEDED"
    assert service.resource_request(result) is request
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
