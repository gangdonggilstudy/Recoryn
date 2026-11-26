"""G11 / G-P11a service and product-path rows: T27, T28 and the admission boundaries.

T27/T28 run the real MainWindow bridge, PrivacyPanel, ConsentStore, CostLedger, Gateway,
OpenAI adapter, AIService and JobStore. Only the OS vault and the transport are fakes,
so a device-policy exemption that skipped consent or cost would reach the fake wire.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtWidgets import QApplication

import recoryn.app.ai as ai_module
from recoryn.app.ai import AIService
from recoryn.content import ContentStore
from recoryn.domain import StateConflict
from recoryn.models import ResourceRequest
from recoryn.storage import Library
from tests.e2e.test_ai_workflow import FakeSTT, finished, recording
from tests.ui.test_secret_lifetime_ui import privacy_action

pytestmark = pytest.mark.integration
POLICIES = ("CPU_ONLY", "GPU_ONLY", "GPU_WITH_CPU_FALLBACK_ALLOWED")
T_IDS = ("G11-T-27", "G11-T-28")
# Hand-written G-P07 groups of the independent guards (consent/auth and cost).
CONSENT_OR_AUTH = {"CONSENT_REQUIRED", "AUTH_REQUIRED", "PERMIT_REVOKED", "CONSENT_REVOKED"}
COST = {
    "BUDGET_REQUIRED",
    "BUDGET_BLOCKED",
    "COST_CAP_REQUIRED",
    "COST_PRICE_UNKNOWN",
    "COST_BOUND_UNVERIFIED",
    "LEDGER_REQUIRED",
}


def spin(app: QApplication, condition: Callable[[], bool], timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.001)
    app.processEvents()
    assert condition()


class Wire:
    def __init__(self) -> None:
        self.opens = 0
        self.remaining = b""

    def open(self, *args: Any) -> Wire:
        self.opens += 1
        reply = {
            "text": "fixture",
            "language": "en",
            "segments": [{"start": 0, "end": 0.5, "text": "fixture"}],
        }
        self.remaining = json.dumps(reply).encode()
        return self

    def write(self, data: bytes, timeout: float) -> None:
        pass

    def read(self, limit: int, timeout: float) -> bytes:
        data, self.remaining = self.remaining[:limit], self.remaining[limit:]
        return data

    def close(self) -> None:
        pass


@pytest.mark.parametrize("case", T_IDS, ids=T_IDS)
def test_t_remote_exemption_never_bypasses_consent_or_cost(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    import recoryn.security as security
    from recoryn.security import ConsentScope, CredentialVault, Gateway
    from recoryn.ui.main import MainWindow

    class Vault:
        def read(self, key: str) -> bytes:
            return b"G11-FAKE-KEY"

        def write(self, *args: Any) -> None:
            pytest.fail("no credential writes")

        def delete(self, *args: Any) -> None:
            pytest.fail("no credential deletion")

    monkeypatch.setattr(
        security, "CredentialVault", lambda: CredentialVault(backend=Vault(), namespace="g11")
    )
    app = QApplication.instance() or QApplication([])
    with Library(tmp_path / "library") as library:
        session = recording(library)
        window = MainWindow(library)
        window.timer.stop()
        try:
            window.refresh_sessions()
            spin(app, lambda: window.sessions.count() == 1)
            window.sessions.setCurrentRow(0)
            bridge, privacy, wire = window.ai_bridge, window.privacy_panel, Wire()
            service = bridge._service()
            privacy.backend.gateway = Gateway(
                privacy.consents, ledger=privacy.ledger, transport=wire
            )
            control = privacy.controls["stt"]
            control.provider.setCurrentIndex(control.provider.findData("openai"))
            control.endpoint.setText("https://g11-remote.invalid/v1")
            control.context_window.setValue(32768)
            control.max_output.setValue(256)
            control.total.setValue(1)
            control.per_request.setValue(0.01)
            privacy._confirm_general = lambda _: True
            prepared: list[str] = []
            raised: list[str] = []
            original = privacy.backend.prepare_execution

            def prepare(*args: Any) -> Any:
                # G11R-05: the refusal code is read from the guard's own exception, never
                # searched for in the status text.
                prepared.append(args[0].kind)
                try:
                    return original(*args)
                except Exception as error:
                    code = getattr(error, "code", None) or (error.args[0] if error.args else "")
                    raised.append(str(code))
                    raise

            monkeypatch.setattr(privacy.backend, "prepare_execution", prepare)

            def grant() -> None:
                privacy.consents.grant(
                    "openai",
                    control.endpoint.text(),
                    "audio",
                    capability="stt",
                    scope=ConsentScope.session(session),
                    policy_version=privacy.consents.policy_version,
                )

            def revoke() -> None:
                privacy.consents.revoke(
                    "openai",
                    control.endpoint.text(),
                    "audio",
                    capability="stt",
                    scope=ConsentScope.session(session),
                    policy_version=privacy.consents.policy_version,
                )

            def mode(name: str) -> None:
                control.cost_mode.setCurrentIndex(control.cost_mode.findData(name))
                privacy_action(privacy, "stt", "budget")

            def run(model: str) -> tuple[str, str | None, list[Any]]:
                """Click, settle, then read the refusal from the record or the status."""
                control.model.setText(model)
                before = len(service.jobs.list_for_session(session))
                failures = len(raised)
                bridge.transcribe()
                spin(app, lambda: not bridge.busy and not service.runner.snapshot()["active"])
                created = [
                    finished(service, job.job_id)
                    for job in service.jobs.list_for_session(session)[before:]
                ]
                text = bridge.panel.job_status.text()  # the preparation outcome, if any
                if created:
                    bridge.tick()  # a Job's later refusal is shown by the next tick
                    return bridge.panel.job_status.text(), created[0].error_code, created
                return text, raised[-1] if len(raised) > failures else None, []

            for index, policy in enumerate(POLICIES):
                window.device_policy.setCurrentText(policy)
                opens, calls = wire.opens, len(prepared)
                if case == "G11-T-27":
                    # Valid cost (acknowledged user cap), no consent: the consent guard.
                    mode("general")
                    text, code, jobs = run(f"t27-{index}")
                    assert code in CONSENT_OR_AUTH, (text, jobs)
                    assert all(job.blocked_reason in {"CONSENT", "AUTH"} for job in jobs)
                else:
                    # Valid consent, strict cost without a verified price (empty production
                    # catalog): the cost guard refuses at the reservation.
                    grant()
                    mode("strict")
                    text, code, jobs = run(f"t28-{index}")
                    assert code in COST, (text, jobs)
                    assert [(job.state.value, job.blocked_reason) for job in jobs] == [
                        ("BLOCKED", "BUDGET")
                    ]
                    assert service.resource_request(jobs[0].job_id) == ResourceRequest(
                        "stt", "REMOTE", policy
                    )
                    revoke()
                assert code is not None and code in text
                assert "RESOURCE_" not in text and "CAPABILITY_UNSUPPORTED" not in text
                assert wire.opens == opens and len(prepared) == calls + 1
                # Control leg under the same policy: valid consent and an acknowledged user
                # cap reach the fake transport exactly once and succeed.
                grant()
                mode("general")
                text, code, jobs = run(f"{case}-ok-{index}")
                assert [job.state.value for job in jobs] == ["SUCCEEDED"], text
                assert wire.opens == opens + 1 and len(prepared) == calls + 2
                assert service.resource_request(jobs[0].job_id) == ResourceRequest(
                    "stt", "REMOTE", policy
                )
                assert "원격 실행 — 이 PC의 장치 정책 적용 안 됨" in text
                revoke()
        finally:
            window.close()
            spin(app, lambda: window._closing)
            window.deleteLater()
            app.processEvents()


def test_dispatch_rechecks_the_captured_policy_before_the_provider(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G11-AUX-DISPATCH: section 3.2's dispatch re-check, separate from admission."""
    calls: list[str] = []
    real = ai_module.plan_static

    def once_then_refuse(request: ResourceRequest) -> Any:
        calls.append(request.policy)
        if len(calls) > 1:
            raise StateConflict("RESOURCE_POLICY_UNVERIFIED")
        return real(request)

    class Provider(FakeSTT):
        used = 0

        def transcribe(self, request: Any, context: Any = None) -> Any:
            Provider.used += 1
            return super().transcribe(request, context)

    monkeypatch.setattr(ai_module, "plan_static", once_then_refuse)
    with Library(tmp_path / "library") as library, ContentStore(library) as content:
        session = recording(library)
        service = AIService(library, content)
        try:
            job = service.transcribe(
                session,
                Provider(),
                config_key="dispatch",
                resource_request=ResourceRequest("stt", "LOCAL_CT2", "CPU_ONLY"),
            )
            done = finished(service, job)
        finally:
            service.close()
    assert calls == ["CPU_ONLY", "CPU_ONLY"] and Provider.used == 0
    assert (done.state.value, done.blocked_reason, done.error_code) == (
        "BLOCKED",
        "CAPABILITY",
        "RESOURCE_POLICY_UNVERIFIED",
    )


def test_merge_keeps_the_captured_request_and_continue_replaces_it(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G11-AUX-CAPTURE: a same-key request never rewrites a queued Job's policy (M24);
    an explicit continue is a new admission whose snapshot is captured (decision 7)."""
    with Library(tmp_path / "library") as library, ContentStore(library) as content:
        session = recording(library)
        service = AIService(library, content)
        try:
            real_submit = service.runner.submit
            # Fixture only: hold the first intent QUEUED without dispatch.
            monkeypatch.setattr(service.runner, "submit", lambda *args, **kwargs: True)
            queued = ResourceRequest("stt", "LOCAL_CT2", "CPU_ONLY", runtime_identity="queued")
            job = service.transcribe(session, FakeSTT(), config_key="same", resource_request=queued)
            later = ResourceRequest("stt", "LOCAL_CT2", "GPU_WITH_CPU_FALLBACK_ALLOWED")
            again = service.transcribe(
                session, FakeSTT(), config_key="same", resource_request=later
            )
            assert again == job and service.resource_request(job) is queued
            record = service.jobs.get(job)
            blocked = service.jobs.block_pending(
                job, "BUDGET", "COST_CAP_EXCEEDED", expected_version=record.state_version
            )
            # A plain same-key request only observes the BLOCKED Job (G-P07, no resume).
            assert (
                service.transcribe(session, FakeSTT(), config_key="same", resource_request=later)
                == job
            )
            assert service.jobs.get(job) == blocked and service.resource_request(job) is queued
            monkeypatch.setattr(service.runner, "submit", real_submit)
            resumed = service.transcribe(
                session,
                FakeSTT(),
                config_key="same",
                resource_request=later,
                expected_job_id=job,
                expected_job_version=blocked.state_version,
            )
            assert resumed == job and service.resource_request(job) is later
            assert finished(service, job).state.value == "SUCCEEDED"
        finally:
            service.close()


# =====================================================================================
# G-P11b: G, R, L, S families and T16-18/T23 through the real inventory join, plan,
# lease, bridge factory and AIService owned path. Hand-written oracles only.
# =====================================================================================

from itertools import product  # noqa: E402

from recoryn.models.gpu_inventory import HostGpu, join_identity  # noqa: E402
from recoryn.models.resources import (  # noqa: E402
    OBSERVED,
    GpuObservation,
    MemoryObservation,
    ResourceScheduler,
    ResourceSource,
)
from recoryn.providers import ProviderError, STTResult  # noqa: E402
from tests.resource_fakes import Factory, Observer, profile  # noqa: E402

HEAD = 10  # GPU headroom of these fixtures; RAM headroom is 20
UNKNOWN_CODE = {
    "identity": "RESOURCE_GPU_IDENTITY_UNVERIFIED",
    "absent": "RESOURCE_GPU_UNAVAILABLE",
    "fit": "RESOURCE_MEMORY_INSUFFICIENT",
}


class Recorded:
    """Stands in for LocalSTTProcess: records the bridge factory's arguments and reports
    the facts a loaded object with those arguments would report."""

    created: list[Recorded] = []

    def __init__(self, model: Any, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.calls: list[str] = []
        self.alive = True
        Recorded.created.append(self)

    def load(self, context: Any = None) -> dict[str, Any]:
        self.calls.append("load")
        return {
            "device": self.kwargs["device"],
            "device_index": self.kwargs["device_index"],
            "compute_type": self.kwargs["compute_type"],
        }

    def transcribe(self, request: Any, context: Any = None) -> Any:
        self.calls.append("transcribe")
        return None

    def close(self) -> None:
        self.alive = False

    def is_live(self) -> bool:
        return self.alive


def _owned(monkeypatch: pytest.MonkeyPatch, source: ResourceSource, device: str) -> Any:
    from recoryn.ui import ai_bridge

    Recorded.created = []
    monkeypatch.setattr(ai_bridge, "LocalSTTProcess", Recorded)
    return ai_bridge.OwnedSTT(Path("model"), source=source, semantic_device=device)


def _run_lease(
    scheduler: ResourceScheduler, request: ResourceRequest, factory: Any
) -> tuple[str, Any]:
    """Prepare (bridge), then dispatch through the lease exactly as owned_worker does."""
    from recoryn.models.resources import check_facts

    try:
        prepared = scheduler.prepare(request, factory.resource_source)
    except StateConflict as error:
        return "refused-at-preparation", str(error)
    factory.semantic_device = prepared.device
    try:
        with scheduler.lease(
            request,
            cancel=threading.Event(),
            job_id="job",
            source=factory.resource_source,
            device=prepared.device,
        ) as lease:
            worker = lease.open(factory.open)
            check_facts(lease.plan, worker)
            worker.transcribe(None)
            return "ran", (lease.plan, worker)
    except StateConflict as error:
        return "refused-at-dispatch", str(error)


# --- G: GPU fit x identity correspondence x preference x policy -------------------------
G_FIT = {"gpu0_only": (100, 5), "gpu1_only": (5, 100), "both": (100, 200), "neither": (5, 5)}
G_IDENTITY = ("verified", "swapped", "missing", "duplicate", "changed")
G_PREF = {"auto": None, "present": "GPU-0", "absent": "GPU-9"}
G = list(product(G_FIT, G_IDENTITY, G_PREF, ("GPU_ONLY", "GPU_WITH_CPU_FALLBACK_ALLOWED")))
G_IDS = [f"G11-G-{n:03}" for n in range(1, 121)]


def _rows(identity: str, free: tuple[int, int], swapped: bool) -> tuple[HostGpu, ...]:
    buses = ("0000:02:00.0", "0000:01:00.0") if swapped else ("0000:01:00.0", "0000:02:00.0")
    uuids = {"missing": ("GPU-0", ""), "duplicate": ("GPU-0", "GPU-0")}.get(
        identity, ("GPU-0", "GPU-1")
    )
    return tuple(
        HostGpu(
            index, uuids[index], buses[index], f"fixture-{index}", free[index], 1000, "Disabled"
        )
        for index in (0, 1)
    )


def g_oracle(row: tuple[str, str, str, str]) -> tuple[str, Any]:
    fit, identity, pref, policy = row
    free = dict(zip(("GPU-0", "GPU-1"), G_FIT[fit], strict=True))
    if identity in ("missing", "duplicate"):
        failure = UNKNOWN_CODE["identity"]
    else:
        pinned = G_PREF[pref]
        names = [pinned] if pinned else ["GPU-0", "GPU-1"]
        present = [name for name in names if name in free]
        fitting = [name for name in present if free[name] >= HEAD]
        if not present:
            failure = UNKNOWN_CODE["absent"]
        elif not fitting:
            failure = UNKNOWN_CODE["fit"]
        else:
            chosen = sorted(fitting, key=lambda name: (-free[name], name))[0]
            # The ordinal follows PCI bus order of the mapping at dispatch time.
            final_swapped = identity in ("swapped", "changed")
            ordinal = {"GPU-0": 1, "GPU-1": 0} if final_swapped else {"GPU-0": 0, "GPU-1": 1}
            return "cuda", (chosen, ordinal[chosen])
    return ("cpu", None) if policy != "GPU_ONLY" else ("refused", failure)


@pytest.mark.parametrize("row", G, ids=G_IDS)
def test_g_gpu_identity_and_placement(monkeypatch: pytest.MonkeyPatch, row: Any) -> None:
    fit, identity, pref, policy = row
    observations = {"count": 0}

    def gpu() -> GpuObservation:
        observations["count"] += 1
        # "changed": the identity map moves between the preparation plan and dispatch.
        swapped = identity == "swapped" or (identity == "changed" and observations["count"] > 1)
        rows = _rows(identity, G_FIT[fit], swapped)
        return join_identity(OBSERVED, rows, 2, {}, time.monotonic_ns())

    scheduler = ResourceScheduler(observe=Observer(gpu), headroom_bytes=HEAD, ram_headroom_bytes=20)
    request = ResourceRequest("stt", "LOCAL_CT2", policy, preferred_gpu=G_PREF[pref])
    factory = _owned(monkeypatch, ResourceSource("native", "READY"), "cuda")
    outcome, detail = _run_lease(scheduler, request, factory)
    want, value = g_oracle(row)
    if want == "refused":
        assert (outcome, detail) == ("refused-at-preparation", value)
        assert Recorded.created == []  # no worker before a plan
        return
    assert outcome == "ran"
    plan, worker = detail
    assert [item.kwargs["device"] for item in Recorded.created] == [want]
    if want == "cuda":
        uuid, ordinal = value
        assert (plan.gpu_uuid, plan.cuda_index) == (uuid, ordinal)
        # The worker gets the logical CUDA ordinal, never the host index (G11 4.2).
        assert worker.kwargs["device_index"] == ordinal
        assert worker.kwargs["compute_type"] == "float16"
    else:
        assert worker.kwargs["device_index"] is None and worker.kwargs["compute_type"] == "int8"
    assert worker.calls == ["load", "transcribe"] and not worker.alive  # reaped


# --- R: L-P07 runtime source x policy x GPU/CPU conditions ------------------------------
R_RUNTIME = ("READY", "NOT_INSTALLED", "DAMAGED", "UNSUPPORTED", "IN_USE", "EXCLUDED")
R = list(product(POLICIES, R_RUNTIME, (False, True), (False, True), (False, True)))
R_IDS = [f"G11-R-{n:03}" for n in range(1, 145)]


def r_oracle(row: tuple[str, str, bool, bool, bool]) -> tuple[str, str | None]:
    policy, runtime, native, gpu_ok, cpu_ok = row
    cpu = ("cpu", None) if cpu_ok else ("refused", "RESOURCE_MEMORY_INSUFFICIENT")
    if policy == "CPU_ONLY":
        return cpu
    source = "native" if native else "runtime" if runtime == "READY" else "none"
    if source == "none":
        gpu = ("refused", "RESOURCE_GPU_UNAVAILABLE")
    elif gpu_ok:
        gpu = ("cuda", source)
    else:
        gpu = ("refused", "RESOURCE_MEMORY_INSUFFICIENT")
    if policy == "GPU_ONLY" or gpu[0] == "cuda":
        return gpu
    return cpu


@pytest.mark.parametrize("row", R, ids=R_IDS)
def test_r_runtime_source_and_policy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, row: Any
) -> None:
    policy, runtime, native, gpu_ok, cpu_ok = row
    checks: list[str] = []

    def native_cuda() -> bool:
        checks.append("native")
        return native

    def status() -> str:
        checks.append("status")
        return "READY" if runtime == "EXCLUDED" else runtime

    from recoryn.ui.ai_bridge import local_source

    # EXCLUDED = this install failed in this run or a change is pending: only it is out.
    root = tmp_path / "gpu-runtime"
    source = local_source(policy, native_cuda, status, root, runtime_blocked=runtime == "EXCLUDED")

    def gpu() -> GpuObservation:
        rows = (HostGpu(0, "GPU-0", "0000:01:00.0", "fixture", 1000 if gpu_ok else 5, 1000, "N/A"),)
        return join_identity(OBSERVED, rows, 1, {}, time.monotonic_ns())

    def ram() -> MemoryObservation:
        return MemoryObservation(OBSERVED, time.monotonic_ns(), 1000 if cpu_ok else 50, 1000, "x")

    observer = Observer(gpu, ram)
    known_cpu = profile("r", model="model-R", runtime="runtime-R", cpu=100)
    scheduler = ResourceScheduler(
        observe=observer, profiles=(known_cpu,), headroom_bytes=HEAD, ram_headroom_bytes=20
    )
    request = ResourceRequest(
        "stt", "LOCAL_CT2", policy, model_identity="model-R", runtime_identity="runtime-R"
    )
    factory = _owned(monkeypatch, source, "cpu")
    outcome, detail = _run_lease(scheduler, request, factory)
    want, value = r_oracle(row)
    if policy == "CPU_ONLY":
        # CPU_ONLY never consults the runtime or the source and never probes a GPU.
        assert checks == [] and observer.gpu_probes == 0
    if want == "refused":
        assert (outcome, detail) == ("refused-at-preparation", value)
        assert Recorded.created == []
        return
    assert outcome == "ran"
    _, worker = detail
    assert worker.kwargs["device"] == want
    # The app runtime is passed only when it is the chosen CUDA source.
    expected_runtime = root if want == "cuda" and value == "runtime" else None
    assert worker.kwargs["gpu_runtime"] == expected_runtime


# --- L: lease state x event x other waiter x policy, on the real scheduler ---------------
L_STATES = (
    "QUEUED",
    "GRANTED_NO_CHILD",
    "CHILD_RUNNING",
    "INFERENCE_REPLIED",
    "REAP_PENDING",
    "REAP_ACKED",
)
L_EVENTS = ("success_result", "local_error", "cancel", "unknown_result")
L = list(product(L_STATES, L_EVENTS, (False, True), ("CPU_ONLY", "GPU_WITH_CPU_FALLBACK_ALLOWED")))
L_IDS = [f"G11-L-{n:02}" for n in range(1, 97)]
# Hand-written legal transitions (G11 7.2); anything else is refused and changes nothing.
L_LEGAL = {
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


class Child:
    def __init__(self) -> None:
        self.allow, self.alive = False, True

    def close(self) -> None:
        if not self.allow:
            raise ProviderError("INFERENCE_ACK_PENDING")
        self.alive = False

    def is_live(self) -> bool:
        return self.alive


def _wait(predicate: Callable[[], bool], timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline
        time.sleep(0.001)


@pytest.mark.parametrize("row", L, ids=L_IDS)
def test_l_lease_transitions_ack_and_other_waiter(row: Any) -> None:
    state, event, other_waiter, policy = row
    scheduler = ResourceScheduler()
    request = ResourceRequest("stt", "LOCAL_CT2", policy)
    child = Child()
    leases: dict[str, Any] = {}
    stop, inside = threading.Event(), threading.Event()
    errors: list[str] = []
    cancel = threading.Event()
    blocker_release = threading.Event()

    def blocker() -> None:
        with scheduler.lease(request, cancel=threading.Event(), job_id="blocker"):
            inside.set()
            assert blocker_release.wait(10)

    def holder() -> None:
        try:
            with scheduler.lease(request, cancel=cancel, job_id="holder") as lease:
                leases["holder"] = lease
                if state in ("CHILD_RUNNING", "INFERENCE_REPLIED", "REAP_PENDING", "REAP_ACKED"):
                    lease.open(lambda plan: child)
                if state == "INFERENCE_REPLIED":
                    lease.record("success_result")
                if state == "REAP_ACKED":
                    child.allow = True
                if state not in ("REAP_PENDING", "REAP_ACKED"):
                    inside.set()
                    assert stop.wait(10)
        except StateConflict as error:
            errors.append(str(error))

    threads = []
    if state == "QUEUED":
        threads.append(threading.Thread(target=blocker))
        threads[-1].start()
        assert inside.wait(10)
        inside.clear()
    threads.append(threading.Thread(target=holder))
    threads[-1].start()
    if state == "QUEUED":
        _wait(lambda: any(item.job_id == "holder" for item in scheduler._waiters))
        leases["holder"] = next(item for item in scheduler._waiters if item.job_id == "holder")
    elif state in ("REAP_PENDING", "REAP_ACKED"):
        threads[-1].join(10)
    else:
        assert inside.wait(10)
    lease = leases["holder"]
    assert lease.state == state
    # The other waiter's factory must not run before the holder's exit ACK.
    opened: list[str] = []
    waiter_result: list[str] = []

    def other() -> None:
        try:
            with scheduler.lease(request, cancel=threading.Event(), job_id="other") as mine:
                mine.open(lambda plan: opened.append("other") or Child())
                mine.worker.allow = True
        except StateConflict as error:
            waiter_result.append(str(error))

    waiter = threading.Thread(target=other)
    acked = state == "REAP_ACKED"  # the holder's worker exit is already acknowledged
    if other_waiter:
        waiter.start()
        time.sleep(0.02)
        if not acked:
            assert opened == []
    want = L_LEGAL.get((state, event))
    if state == "QUEUED" and event == "cancel":
        cancel.set()
        threads[-1].join(10)
        assert lease.state == "REAP_ACKED" and errors == ["RESOURCE_CANCELLED"]
    elif want is None:
        with pytest.raises(StateConflict, match="RESOURCE_LEASE_TRANSITION_INVALID"):
            lease.record(event)
        assert lease.state == state
    else:
        assert lease.record(event) == want
    unknown = event == "unknown_result" and want is not None
    if other_waiter and not acked:
        assert opened == []  # still nothing for the other waiter before the ACK
    # Finish: the holder exits; a worker that will not exit keeps the slot held.
    stop.set()
    blocker_release.set()
    for thread in threads:
        thread.join(10)
    if lease.state == "REAP_PENDING" and lease.ack_code is not None:
        assert scheduler.held() == ("holder",)
        if other_waiter:
            waiter.join(10)
            assert opened == [] and waiter_result == ["RESOURCE_LEASE_HELD"]
        child.allow = True
        scheduler.reap_held()
    assert lease.state == "REAP_ACKED" and scheduler.held() == ()
    assert lease.outcome_unknown is unknown  # the logical UNKNOWN survives the ACK
    if other_waiter:
        waiter.join(10)
        assert opened in ([], ["other"])
        if opened == []:
            assert waiter_result == ["RESOURCE_LEASE_HELD"]


# --- S: UNKNOWN does not block admission or success; OOM keeps the estimate --------------
S = list(
    product(
        ("known", "unknown"),
        ("stt", "diarization"),
        ("prepared", "queued", "active", "success", "oom"),
    )
)
S_IDS = [f"G11-S-{n:02}" for n in range(1, 21)]


@pytest.mark.parametrize("row", S, ids=S_IDS)
def test_s_estimate_status_through_the_owned_path(tmp_path: Path, row: Any) -> None:
    from recoryn.content import ContentStore

    estimate, kind, moment = row
    backend = "LOCAL_CT2" if kind == "stt" else "LOCAL_SHERPA"
    known = estimate == "known"
    profiles = (
        (profile("s", kind=kind, backend=backend, model="model-S", runtime="runtime-S", cpu=100),)
        if known
        else ()
    )
    observer = Observer(
        ram=lambda: MemoryObservation(OBSERVED, time.monotonic_ns(), 10_000, 10_000, "x")
    )
    scheduler = ResourceScheduler(
        observe=observer, profiles=profiles, headroom_bytes=HEAD, ram_headroom_bytes=20
    )
    request = ResourceRequest(
        kind, backend, "CPU_ONLY", model_identity="model-S", runtime_identity="runtime-S"
    )
    status = "RESOURCE_ESTIMATE_KNOWN" if known else "RESOURCE_ESTIMATE_UNKNOWN"
    plan = scheduler.prepare(request)
    assert (plan.estimate_status, plan.planned_ram) == (status, 100 if known else None)
    assert observer.ram_reads == int(known)  # an UNKNOWN requirement never reads RAM
    if moment == "prepared":
        return
    gate = threading.Event()

    def outcome(request: Any) -> STTResult:
        if moment == "oom":
            return STTResult("fake", "model", (), False, error_code="RESOURCE_EXHAUSTED")
        from recoryn.providers import TranscriptSegment

        item = TranscriptSegment("s", request.offset_ms, request.offset_ms + 1, "x")
        return STTResult("fake", "model", (item,), True, processed_ms=1)

    factory = Factory(
        "faster_whisper" if kind == "stt" else "sherpa_onnx",
        gate=gate if moment == "active" else None,
        result=outcome,
    )
    with Library(tmp_path / "library") as library, ContentStore(library) as content:
        session = recording(library)
        service = AIService(library, content, resources=scheduler)
        try:
            real_submit = service.runner.submit
            if moment == "queued":
                service.runner.submit = lambda *args, **kwargs: True  # type: ignore[method-assign]
            if kind == "stt":
                job_id = service.transcribe(
                    session, factory, config_key="s", resource_request=request
                )
            else:
                admitted = service.admit_diarization(request, factory)
                job = service.jobs.create("diarization", "s")
                service.jobs.bind_session(job.job_id, session)
                service.capture_diarization(job.job_id, admitted)
                job_id = job.job_id

                def task(attempt: Any, cancel: threading.Event) -> str:
                    with service.owned_worker(admitted, factory, attempt, cancel, session) as use:
                        result = use().transcribe(SimpleRequest())
                        if not result.complete:
                            raise ProviderError(result.error_code or "PROVIDER_FAILED")
                    return "diarized"

                assert service.runner.submit(job_id, task)
            if moment == "queued":
                assert service.jobs.get(job_id).state.value == "QUEUED"  # admitted, not blocked
                assert service.resource_view(job_id) is None  # no lease before dispatch
                return
            if moment == "active":
                _wait(lambda: bool(factory.opened) and factory.opened[0].entered.is_set())
                view = service.resource_view(job_id)
                assert view is not None and (view["phase"], view["estimate_status"]) == (
                    "ACTIVE",
                    status,
                )
                gate.set()
            done = finished(service, job_id)
            view = service.resource_view(job_id)
            assert view is not None and view["estimate_status"] == status  # never upgraded
            assert view["phase"] == "RELEASED"
            if moment == "oom":
                assert (done.state.value, done.blocked_reason, done.error_code) == (
                    "BLOCKED",
                    "RESOURCE",
                    "RESOURCE_EXHAUSTED",
                )
            else:
                assert done.state.value == "SUCCEEDED"
        finally:
            service.runner.submit = real_submit  # type: ignore[method-assign]
            gate.set()
            service.close()


class SimpleRequest:
    offset_ms = 0
    track_id = "mic"


# --- T16-18 and T23 through the AIService owned path ------------------------------------
T_SERVICE = ("G11-T-16", "G11-T-17", "G11-T-18", "G11-T-23")


@pytest.mark.parametrize("case", T_SERVICE, ids=T_SERVICE)
def test_t_device_facts_and_fixed_semantic_device(tmp_path: Path, case: str) -> None:
    from recoryn.content import ContentStore
    from recoryn.models.resources import GpuDevice

    def gpu() -> GpuObservation:
        devices = (GpuDevice("GPU-0", 1, 0, "fixture", 10_000, 10_000),)
        return GpuObservation(OBSERVED, time.monotonic_ns(), devices, True, "fixture")

    native = ResourceSource("native", "READY")
    facts = {
        "G11-T-16": {"device": "cuda", "device_index": 1, "compute_type": "float32"},
        "G11-T-17": {"device": "cpu", "device_index": None, "compute_type": "float16"},
        "G11-T-18": {"device": "cuda", "device_index": 0, "compute_type": "float16"},
    }.get(case)
    policy = "GPU_ONLY" if case != "G11-T-23" else "GPU_WITH_CPU_FALLBACK_ALLOWED"
    observer = Observer(gpu if case != "G11-T-23" else None)
    scheduler = ResourceScheduler(observe=observer, headroom_bytes=HEAD, ram_headroom_bytes=20)
    factory = Factory(source=native, semantic_device="cuda", facts=facts)
    with Library(tmp_path / "library") as library, ContentStore(library) as content:
        session = recording(library)
        service = AIService(library, content, resources=scheduler)
        try:
            job_id = service.transcribe(
                session,
                factory,
                config_key="t",
                resource_request=ResourceRequest("stt", "LOCAL_CT2", policy),
            )
            done = finished(service, job_id)
        finally:
            service.close()
    if case == "G11-T-23":
        # The Job's key fixed cuda; no GPU now. Never silently the CPU under the same key.
        assert factory.opened == []
        assert (done.state.value, done.error_code) == ("BLOCKED", "RESOURCE_GPU_PROBE_UNAVAILABLE")
        return
    worker = factory.opened[0]
    assert worker.calls == ["load", "close"]  # facts checked before any inference
    assert (done.state.value, done.blocked_reason, done.error_code) == (
        "BLOCKED",
        "RESOURCE",
        "RESOURCE_DEVICE_MISMATCH",
    )


# --- G11R-02: stop() never turns a settled BLOCKED into CANCELLED -----------------------
@pytest.mark.parametrize(
    "code,known",
    [
        ("RESOURCE_MEMORY_INSUFFICIENT", True),
        ("COST_CAP_EXCEEDED", True),
        ("REMOTE_OUTCOME_UNKNOWN", False),
    ],
    ids=["G11-AUX-STOP-resource", "G11-AUX-STOP-budget", "G11-AUX-STOP-unknown"],
)
def test_stop_waits_for_and_preserves_a_settled_block(code: str, known: bool) -> None:
    from recoryn.jobs import JobStore
    from recoryn.jobs.runner import BoundedRunner

    with JobStore(Path(":memory:")) as store:
        written, release = threading.Event(), threading.Event()
        real_fail = store.fail

        def held_fail(*args: Any, **kwargs: Any) -> Any:
            record = real_fail(*args, **kwargs)
            written.set()  # BLOCKED is committed; the work is still listed active
            assert release.wait(10)
            return record

        store.fail = held_fail  # type: ignore[method-assign]
        runner = BoundedRunner(store)
        runner.start()
        job = store.create("transcription", "stop")

        def task(attempt: Any, cancel: Any) -> str:
            raise ProviderError(code, outcome_known=known)

        assert runner.submit(job.job_id, task)
        assert written.wait(10)
        stopped = threading.Event()
        stopper = threading.Thread(target=lambda: (runner.stop(10), stopped.set()))
        stopper.start()
        time.sleep(0.05)
        assert not stopped.is_set()  # stop waits for the in-flight settlement
        release.set()
        stopper.join(10)
        assert stopped.is_set()
        after = store.get(job.job_id)
        reason = (
            "REMOTE_UNKNOWN"
            if not known
            else "RESOURCE"
            if code.startswith("RESOURCE")
            else "BUDGET"
        )
        assert (after.state.value, after.blocked_reason) == ("BLOCKED", reason)


# --- G11R-03: the dispatch re-check also guards summary and diarization -------------------
def test_dispatch_recheck_guards_summary_and_diarization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G11-AUX-DISPATCH-2: as for transcription, a refusal at dispatch blocks the Job
    before any provider or worker call (summary task and the owned diarization path)."""
    from recoryn.content import ContentStore
    from tests.e2e.test_ai_workflow import FakeSummary

    with Library(tmp_path / "library") as library, ContentStore(library) as content:
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
            real = ai_module.plan_static
            calls: list[str] = []

            def once_then_refuse(request: ResourceRequest) -> Any:
                calls.append(request.kind)
                if calls.count(request.kind) > 1:
                    raise StateConflict("RESOURCE_POLICY_UNVERIFIED")
                return real(request)

            monkeypatch.setattr(ai_module, "plan_static", once_then_refuse)

            class Summary(FakeSummary):
                used = 0

                def summarize(self, request: Any, context: Any = None) -> Any:
                    Summary.used += 1
                    return super().summarize(request, context)

            summary = service.summarize(
                session,
                Summary(),
                config_key="dispatch-summary",
                resource_request=ResourceRequest("summary", "REMOTE", "CPU_ONLY"),
            )
            done = finished(service, summary)
            assert (done.state.value, done.error_code, Summary.used) == (
                "BLOCKED",
                "RESOURCE_POLICY_UNVERIFIED",
                0,
            )
            factory = Factory("sherpa_onnx")
            admitted = ResourceRequest("diarization", "LOCAL_SHERPA", "CPU_ONLY")
            job = service.jobs.create("diarization", "dispatch")
            service.jobs.bind_session(job.job_id, session)
            calls.append("diarization")  # the bridge's admission already ran once

            def task(attempt: Any, cancel: threading.Event) -> str:
                with service.owned_worker(admitted, factory, attempt, cancel, session) as use:
                    use()
                return "unreachable"

            assert service.runner.submit(job.job_id, task)
            done = finished(service, job.job_id)
            assert (done.state.value, done.error_code, factory.opened) == (
                "BLOCKED",
                "RESOURCE_POLICY_UNVERIFIED",
                [],
            )
        finally:
            service.close()


# --- held lease and UNKNOWN through the AIService owned path -----------------------------
def test_held_lease_refuses_the_next_job_before_its_worker_exists(tmp_path: Path) -> None:
    """G11-AUX-HELD-NEXT (L): a Job whose worker did not exit keeps the slot; the next
    owned Job is refused RESOURCE_LEASE_HELD and its factory is never called."""
    from recoryn.content import ContentStore

    stuck = Factory(close_ok=False)
    following = Factory()
    with Library(tmp_path / "library") as library, ContentStore(library) as content:
        session = recording(library)
        service = AIService(library, content)
        try:
            first = service.transcribe(session, stuck, config_key="a", resource_request=STT_CPU)
            finished(service, first)
            assert service.scheduler.held() == (first,)
            assert service.jobs.local_reader_active(first) is True  # deletion waits
            second = service.transcribe(
                session, following, config_key="b", resource_request=STT_CPU
            )
            done = finished(service, second)
            assert (done.state.value, done.error_code) == ("BLOCKED", "RESOURCE_LEASE_HELD")
            assert following.opened == []
            stuck.opened[0].close_ok = True
            service.scheduler.reap_held()
            assert service.scheduler.held() == ()
            assert service.jobs.local_reader_active(first) is False
        finally:
            for factory in (stuck, following):
                for worker in factory.opened:
                    worker.close_ok = True
            service.close()


def test_unknown_outcome_survives_a_held_worker(tmp_path: Path) -> None:
    """G11-AUX-UNKNOWN-HELD (C/L): an UNKNOWN result whose worker also did not exit stays
    BLOCKED(REMOTE_UNKNOWN); the exit ACK code never converts it into a known failure."""
    from recoryn.content import ContentStore

    def unknown(request: Any) -> STTResult:
        return STTResult(
            "fake", "model", (), False, outcome_known=False, error_code="REMOTE_OUTCOME_UNKNOWN"
        )

    factory = Factory(close_ok=False, result=unknown)
    with Library(tmp_path / "library") as library, ContentStore(library) as content:
        session = recording(library)
        service = AIService(library, content)
        try:
            job = service.transcribe(session, factory, config_key="u", resource_request=STT_CPU)
            done = finished(service, job)
            assert (done.state.value, done.blocked_reason) == ("BLOCKED", "REMOTE_UNKNOWN")
            view = service.resource_view(job)
            assert view is not None and view["outcome_unknown"] and view["phase"] == "REAP_PENDING"
        finally:
            for worker in factory.opened:
                worker.close_ok = True
            service.scheduler.reap_held()
            service.close()


STT_CPU = ResourceRequest("stt", "LOCAL_CT2", "CPU_ONLY")
