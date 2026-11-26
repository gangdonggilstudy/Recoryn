"""G-P11c L, S and R rows: runner outcome writes off the lock, stop() races, held reap.

Real JobStore/Library/BoundedRunner/ResourceScheduler/AIService; only the task bodies,
the owned worker and the timing hooks are fakes. No device, model or network. Every
expected value is written by hand from the G-P11c scope section (G11 doc) and the
G-P07 decision table.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import closing
from itertools import count, product
from pathlib import Path
from typing import Any

import pytest

from recoryn.app.ai import AIService
from recoryn.content import ContentStore
from recoryn.jobs import JobStore
from recoryn.jobs.runner import BoundedRunner
from recoryn.models import ResourceRequest
from recoryn.models.resources import ResourceScheduler
from recoryn.providers import ProviderError, STTResult
from recoryn.storage import Library
from recoryn.storage._coordination import root_mutex
from tests.e2e.test_ai_workflow import finished, recording
from tests.resource_fakes import Factory, Worker

pytestmark = pytest.mark.integration
_serial = count(1)
HOLD = 0.4  # how long a blocker keeps the outcome write waiting
QUICK = 0.1  # a display read must return well inside this


# --- shared task bodies ---------------------------------------------------------------
def outcome_task(
    kind: str, gate: threading.Event | None = None, entered: threading.Event | None = None
) -> Callable[..., str]:
    calls = {"n": 0}

    def task(attempt: Any, cancel: threading.Event) -> str:
        calls["n"] += 1
        if entered is not None:
            entered.set()
        if gate is not None:
            assert gate.wait(10)
        if kind == "SUCCEEDED" or (kind == "BACKOFF" and calls["n"] > 1):
            return "result-ref"
        if kind == "BACKOFF":
            raise ProviderError("TIMEOUT", retryable=True)
        if kind == "CANCEL":
            return "result-ref"  # returns after a user cancel was recorded
        raise {
            "BLOCKED_RESOURCE": ProviderError("RESOURCE_EXHAUSTED"),
            "BLOCKED_BUDGET": ProviderError("COST_CAP_EXCEEDED"),
            "FAILED": ValueError("fixture failure"),
            "UNKNOWN": ProviderError("REMOTE_OUTCOME_UNKNOWN", outcome_known=False),
        }[kind]

    return task


def wait_terminal(store: JobStore, job_id: str, timeout: float = 10) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = store.get(job_id)
        if job.state.value in {"SUCCEEDED", "FAILED", "CANCELLED", "BLOCKED"}:
            return job
        time.sleep(0.005)
    pytest.fail(f"job did not finish: {store.get(job_id).state}")


@pytest.fixture(scope="module")
def library(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Library]:
    with Library(tmp_path_factory.mktemp("g11c-l") / "library") as value:
        yield value


# --- L: outcome x blocker x observer ---------------------------------------------------
L_OUTCOMES = ("SUCCEEDED", "BLOCKED_RESOURCE", "FAILED", "BACKOFF", "CANCEL", "UNKNOWN")
L = list(product(L_OUTCOMES, ("root_mutex", "sqlite_lock"), ("admission_error", "snapshot")))
L_IDS = [f"G11C-L-{n:02}" for n in range(1, 25)]
L_FINAL = {  # (state, blocked_reason, error_code, attempts) by hand (G-P07 table)
    "SUCCEEDED": ("SUCCEEDED", None, None, 1),
    "BLOCKED_RESOURCE": ("BLOCKED", "RESOURCE", "RESOURCE_EXHAUSTED", 1),
    "FAILED": ("FAILED", None, "TASK_FAILED", 1),
    "BACKOFF": ("SUCCEEDED", None, None, 2),
    "CANCEL": ("CANCELLED", None, None, 1),
    "UNKNOWN": ("BLOCKED", "REMOTE_UNKNOWN", "REMOTE_OUTCOME_UNKNOWN", 1),
}


def l_write_waits(row: tuple[str, str, str]) -> bool:
    outcome, cause, _ = row
    return cause == "sqlite_lock" or outcome in (
        "SUCCEEDED",
        "BLOCKED_RESOURCE",
        "FAILED",
        "BACKOFF",
        "UNKNOWN",
    )


@pytest.mark.parametrize("row", L, ids=L_IDS)
def test_l_display_reads_never_wait_for_an_outcome_write(
    library: Library, row: tuple[str, str, str]
) -> None:
    outcome, cause, observer = row
    want = L_FINAL[outcome]
    session = f"l{next(_serial)}"
    library.create_session(session)
    with JobStore(library.db_path) as store:
        runner = BoundedRunner(store)
        job = store.create("transcription", f"g11c-{session}")
        store.bind_session(job.job_id, session)
        gate, acked, writing, free = (
            threading.Event(),
            threading.Event(),
            threading.Event(),
            threading.Event(),
        )
        real_finished = store.reader_finished
        first_ack = {"done": False}
        durations: list[float] = []

        def reader_finished(attempt: Any) -> None:
            try:
                real_finished(attempt)  # after a user cancel the fence moved: it raises
            finally:
                if not first_ack["done"]:
                    first_ack["done"] = True
                    acked.set()
                    assert free.wait(10)  # the blocker is in place before the outcome write

        def watch(name: str) -> None:
            real = getattr(store, name)

            def wrapped(*args: Any, **kwargs: Any) -> Any:
                writing.set()
                started = time.perf_counter()
                try:
                    return real(*args, **kwargs)
                finally:
                    durations.append(time.perf_counter() - started)

            setattr(store, name, wrapped)

        store.reader_finished = reader_finished  # type: ignore[method-assign]
        for name in ("complete", "fail", "_ack_cancelled"):
            watch(name)
        runner.start()
        try:
            started_task = threading.Event()
            assert runner.submit(job.job_id, outcome_task(outcome, gate, started_task))
            assert started_task.wait(10)
            if outcome == "CANCEL":
                runner.cancel(job.job_id)  # a user cancel while the task runs
            gate.set()
            assert acked.wait(10)
            held = threading.Event()
            helper_done = threading.Event()

            def hold() -> None:
                if cause == "root_mutex":
                    with root_mutex(library.root):
                        held.set()
                        time.sleep(HOLD)
                else:
                    with closing(sqlite3.connect(library.db_path, isolation_level=None)) as other:
                        other.execute("BEGIN IMMEDIATE")
                        held.set()
                        time.sleep(HOLD)
                        other.execute("ROLLBACK")
                helper_done.set()

            threading.Thread(target=hold, daemon=True).start()
            assert held.wait(5)
            free.set()
            assert writing.wait(5)
            time.sleep(0.03)  # the worker is now inside the blocked outcome write
            started = time.perf_counter()
            if observer == "admission_error":
                assert runner.admission_error(job.job_id) is None
            else:
                assert isinstance(runner.snapshot()["active"], tuple)
            elapsed = time.perf_counter() - started
            blocked_meanwhile = not helper_done.is_set()
            assert helper_done.wait(10)
            done = wait_terminal(store, job.job_id)
        finally:
            gate.set()
            free.set()
            runner.stop(10)
    assert blocked_meanwhile, "the blocker ended before the display read"
    # The row really exercised a waiting outcome write (hand rule: the root mutex is
    # taken by fail's acknowledgement authority and new complete publication
    # authority; every write takes the SQLite lock).
    assert (max(durations) >= HOLD / 2) is l_write_waits(row), durations
    assert elapsed < QUICK, f"display read waited {elapsed:.3f}s on the outcome write"
    attempts = len(store_rows(library, job.job_id))
    assert (done.state.value, done.blocked_reason, done.error_code, attempts) == want


def store_rows(library: Library, job_id: str) -> list[tuple[Any, ...]]:
    with closing(sqlite3.connect(library.db_path)) as connection:
        return connection.execute(
            "SELECT attempt_id FROM attempts WHERE job_id=?", (job_id,)
        ).fetchall()


# --- S: stop timing x outcome ----------------------------------------------------------
S_OUTCOMES = ("SUCCEEDED", "BLOCKED_RESOURCE", "BLOCKED_BUDGET", "FAILED", "UNKNOWN")
S = list(product(("before", "during", "after"), S_OUTCOMES))
S_IDS = [f"G11C-S-{n:02}" for n in range(1, 16)]
S_SETTLED = {
    "SUCCEEDED": ("SUCCEEDED", None),
    "BLOCKED_RESOURCE": ("BLOCKED", "RESOURCE"),
    "BLOCKED_BUDGET": ("BLOCKED", "BUDGET"),
    "FAILED": ("FAILED", None),
    "UNKNOWN": ("BLOCKED", "REMOTE_UNKNOWN"),
}


def s_oracle(row: tuple[str, str]) -> tuple[str, str | None]:
    """A stop decided before the outcome cancels a known outcome (UNKNOWN stays UNKNOWN);
    an outcome being written or already written is kept (G11R-02)."""
    timing, outcome = row
    if timing == "before":
        return ("BLOCKED", "REMOTE_UNKNOWN") if outcome == "UNKNOWN" else ("CANCELLED", None)
    return S_SETTLED[outcome]


@pytest.mark.parametrize("row", S, ids=S_IDS)
def test_s_stop_keeps_settled_outcomes_and_cancels_only_unsettled_work(
    row: tuple[str, str],
) -> None:
    timing, outcome = row
    assert _stop_case(timing, outcome)[:2] == s_oracle(row)


def _stop_case(timing: str, outcome: str) -> tuple[str, str | None, bool]:
    """Run one stop() race; returns (state, blocked_reason, cancel_requested)."""
    if timing == "listed_then_finished":
        return _stop_after_listing(outcome)
    with JobStore(Path(":memory:")) as store:
        gate, entered, release = threading.Event(), threading.Event(), threading.Event()
        written = threading.Event()
        real = {name: getattr(store, name) for name in ("complete", "fail", "cancel", "get")}
        state = {"outcome_done": False, "held_once": False}

        def write(name: str) -> Callable[..., Any]:
            def wrapped(*args: Any, **kwargs: Any) -> Any:
                value = real[name](*args, **kwargs)
                state["outcome_done"] = True
                if timing == "during" and not state["held_once"]:
                    state["held_once"] = True
                    written.set()
                    assert release.wait(10)  # the write is committed, still in progress
                return value

            return wrapped

        def get(job_id: str) -> Any:
            value = real["get"](job_id)
            if timing == "after" and state["outcome_done"] and not state["held_once"]:
                state["held_once"] = True
                written.set()
                assert release.wait(10)  # settled; the worker still lists the work active
            return value

        def cancel(job_id: str) -> Any:
            if timing == "before":
                gate.set()  # the task finishes while stop's own cancellation is in flight
                time.sleep(0.1)
            return real["cancel"](job_id)

        store.complete = write("complete")  # type: ignore[method-assign]
        store.fail = write("fail")  # type: ignore[method-assign]
        store.get = get  # type: ignore[method-assign]
        store.cancel = cancel  # type: ignore[method-assign]
        runner = BoundedRunner(store)
        runner.start()
        job = store.create("transcription", "s")
        body = outcome_task(outcome)  # one body: BACKOFF fails once, then succeeds

        def task(attempt: Any, cancel_event: threading.Event) -> str:
            entered.set()
            assert gate.wait(10)
            return body(attempt, cancel_event)

        assert runner.submit(job.job_id, task)
        assert entered.wait(10)
        if timing != "before":
            gate.set()
            assert written.wait(10)
        stopper = threading.Thread(target=lambda: runner.stop(10), daemon=True)
        stopper.start()
        if timing != "before":
            time.sleep(0.05)
            assert stopper.is_alive()  # stop waits for the settlement in progress
            release.set()
        stopper.join(15)
        assert not stopper.is_alive()
        after = real["get"](job.job_id)
    return after.state.value, after.blocked_reason, after.cancel_requested


def _stop_after_listing(outcome: str) -> tuple[str, str | None, bool]:
    """stop() fixes its active list, then (while it cancels a queued Job) the active Job
    settles and leaves the active list (reviewer's probe_stop_window shape)."""
    with JobStore(Path(":memory:")) as store:
        active = store.create("transcription", "active")
        queued = store.create("transcription", "queued")
        gate = threading.Event()
        runner = BoundedRunner(store)
        real_cancel = store.cancel

        def cancel(job_id: str) -> Any:
            if job_id == queued.job_id:
                gate.set()  # the active task ends now
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    if active.job_id not in runner.snapshot()["active"]:
                        break  # settled and gone from the active list
                    if store.get(active.job_id).state.value == "BACKOFF":
                        break  # a retry wait: still active, still unsettled
                    time.sleep(0.005)
            return real_cancel(job_id)

        store.cancel = cancel  # type: ignore[method-assign]
        runner.start()
        body = outcome_task(outcome)

        def task(attempt: Any, cancel_event: threading.Event) -> str:
            assert gate.wait(10)
            return body(attempt, cancel_event)

        assert runner.submit(active.job_id, task)
        deadline = time.monotonic() + 10
        while active.job_id not in runner.snapshot()["active"] and time.monotonic() < deadline:
            time.sleep(0.005)
        assert runner.submit(queued.job_id, lambda attempt, cancel_event: "never")
        runner.stop(10)
        after = store.get(active.job_id)
        assert store.get(queued.job_id).state.value == "CANCELLED"
    return after.state.value, after.blocked_reason, after.cancel_requested


# --- R: hold cause x worker exit x release path x outcome -------------------------------
R = list(
    product(
        ("close_raises", "close_ok_child_live"),
        ("exits", "never_exits"),
        ("periodic", "next_grant"),
        ("published", "local_error", "unknown"),
    )
)
R_IDS = [f"G11C-R-{n:02}" for n in range(1, 25)]
STT_CPU = ResourceRequest("stt", "LOCAL_CT2", "CPU_ONLY")
R_FIRST = {
    "published": ("SUCCEEDED", None),
    "local_error": ("BLOCKED", "RESOURCE"),
    "unknown": ("BLOCKED", "REMOTE_UNKNOWN"),
}


def r_oracle(row: tuple[str, str, str, str]) -> dict[str, Any]:
    cause, later, path, outcome = row
    released = later == "exits"
    return {
        "first": R_FIRST[outcome],
        "released": released,
        "second": None
        if path == "periodic"
        else (("SUCCEEDED", None) if released else ("BLOCKED", "RESOURCE")),
    }


class HeldWorker(Worker):
    """An owned worker whose exit is not acknowledged at first.

    ``close_raises``: close fails while the process lives. ``close_ok_child_live``:
    close returns normally but the process is still alive (Python's return value alone
    is not an exit ACK). ``exit()`` makes the process end on its own.
    """

    cause: str = "close_raises"

    def close(self) -> None:
        self.calls.append("close")
        if self.alive and self.cause == "close_raises":
            raise ProviderError("INFERENCE_ACK_PENDING")

    def exit(self) -> None:
        self.alive = False


class HeldFactory(Factory):
    def __init__(self, cause: str, outcome: str) -> None:
        def result(request: Any) -> STTResult:
            if outcome == "local_error":
                raise ProviderError("INFERENCE_PROCESS_FAILED")
            return STTResult(
                "fake", "model", (), False, outcome_known=False, error_code="REMOTE_OUTCOME_UNKNOWN"
            )

        super().__init__(**({} if outcome == "published" else {"result": result}))
        self.cause = cause

    def open(self, plan: Any) -> Worker:
        worker = HeldWorker(plan, **self.worker)
        worker.cause = self.cause
        self.opened.append(worker)
        return worker


def _until(condition: Callable[[], bool], timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return condition()


@pytest.mark.parametrize("row", R, ids=R_IDS)
def test_r_a_held_slot_is_released_only_after_the_worker_really_exits(
    tmp_path: Path, row: tuple[str, str, str, str]
) -> None:
    cause, later, path, outcome = row
    want = r_oracle(row)
    scheduler = ResourceScheduler(reap_interval=0.05 if path == "periodic" else 3600)
    factory = HeldFactory(cause, outcome)
    with Library(tmp_path / "library") as library, ContentStore(library) as content:
        session = recording(library)
        service = AIService(library, content, resources=scheduler)
        try:
            job = service.transcribe(session, factory, config_key="held", resource_request=STT_CPU)
            first = finished(service, job)
            assert (first.state.value, first.blocked_reason) == want["first"]
            worker = factory.opened[0]
            # Held: slot, Job local reader and deletion wait (also for UNKNOWN, G11BR-04).
            assert scheduler.held() == (job,)
            assert service.jobs.local_reader_active(job) is True
            assert job in service.runner.snapshot()["active"]  # N12: held counts as active
            closes = worker.calls.count("close")
            time.sleep(0.2)  # several reaper turns: a live worker is never released
            assert scheduler.held() == (job,) and worker.alive
            # ... and never closed again by the periodic check (G11CR-03, Q05).
            assert worker.calls.count("close") == closes
            if later == "exits":
                worker.exit()
            second = None
            if path == "next_grant":
                other = recording(library)
                follow = service.transcribe(
                    other, Factory(), config_key="next", resource_request=STT_CPU
                )
                done = finished(service, follow)
                second = (done.state.value, done.blocked_reason)
                if done.state.value == "BLOCKED":
                    assert done.error_code == "RESOURCE_LEASE_HELD"
            else:
                _until(lambda: scheduler.held() == (), 2.0 if later == "exits" else 0.3)
            assert second == want["second"]
            released = scheduler.held() == ()
            assert released is want["released"]
            assert service.jobs.local_reader_active(job) is (not want["released"])
            assert (job in service.runner.snapshot()["active"]) is (not want["released"])
            deleted = library.delete_session(session)
            assert deleted["deleted"] is want["released"]
            if not want["released"]:
                assert deleted.get("reason") == "ACTIVE_READER_OR_WRITER"
            assert service.jobs.get(job).state.value == want["first"][0]  # logic kept
        finally:
            for item in factory.opened:
                item.exit()
            try:
                scheduler.reap_held()
            except Exception:
                pass
            service.close()


# =====================================================================================
# G-P11d (G-P11c review G11CR-02, G11CR-03): S2 and C rows. Hand-written expectations.
# =====================================================================================
S2_OUTCOMES = (*S_OUTCOMES, "BACKOFF")
S2 = [("listed_then_finished", outcome) for outcome in S2_OUTCOMES] + [
    (timing, "BACKOFF") for timing in ("before", "during", "after")
]
S2_IDS = [f"G11D-S-{n:02}" for n in range(1, 10)]


def s2_oracle(row: tuple[str, str]) -> tuple[str, str | None]:
    """A Job that settled and left the active list keeps its outcome (Q01); a retry wait
    (BACKOFF) is unsettled work, so stop cancels it once its write is done (Q06) - only
    a stop after the retry's own success sees SUCCEEDED."""
    timing, outcome = row
    if outcome == "BACKOFF":
        return ("SUCCEEDED", None) if timing == "after" else ("CANCELLED", None)
    return S_SETTLED[outcome]


@pytest.mark.parametrize("row", S2, ids=S2_IDS)
def test_s2_stop_list_and_backoff(row: tuple[str, str]) -> None:
    timing, outcome = row
    state, reason, cancel_requested = _stop_case(timing, outcome)
    assert (state, reason) == s2_oracle(row)
    if (state, reason) == ("CANCELLED", None):
        assert cancel_requested is True  # stop's own durable cancellation


C_STATES = ("no_held", "held_live", "held_exits_after_close")
C = list(product(C_STATES, ("scheduler_close", "service_close")))
C_IDS = [f"G11D-C-{n:02}" for n in range(1, 7)]


@pytest.mark.parametrize("row", C, ids=C_IDS)
def test_c_closing_stops_the_reaper_and_writes_nothing_after(
    tmp_path: Path, row: tuple[str, str]
) -> None:
    """G11CR-02: after close the reaper is joined, a held slot stays held, and no exit
    receipt reaches the (closing) JobStore even when the worker exits later."""
    held_state, via = row
    scheduler = ResourceScheduler(reap_interval=0.05)
    factory = HeldFactory("close_raises", "published") if held_state != "no_held" else Factory()
    with Library(tmp_path / "library") as library, ContentStore(library) as content:
        session = recording(library)
        service = AIService(library, content, resources=scheduler)
        closed_service = False
        try:
            job = service.transcribe(session, factory, config_key="c", resource_request=STT_CPU)
            assert finished(service, job).state.value == "SUCCEEDED"
            # The result is published before the lease's exit ACK fails and the reaper
            # starts, so a held slot's reaper is awaited (bounded) rather than raced.
            _until(
                lambda: scheduler._reaper is not None and scheduler._reaper.is_alive(),
                2.0 if held_state != "no_held" else 0.2,
            )
            reaper = scheduler._reaper
            assert (reaper is not None and reaper.is_alive()) is (held_state != "no_held")
            receipts: list[Any] = []
            real_finished = service.jobs.reader_finished
            service.jobs.reader_finished = lambda attempt: (  # type: ignore[method-assign]
                receipts.append(attempt),
                real_finished(attempt),
            )[1]
            if via == "scheduler_close":
                scheduler.close()
            else:
                service.close()
                closed_service = True
            assert reaper is None or not reaper.is_alive()  # joined, not left behind
            assert scheduler._reaper is None
            if held_state == "held_exits_after_close":
                factory.opened[0].exit()
            time.sleep(0.25)  # several former reaper periods
            try:
                scheduler.reap_held()  # an explicit retry after close (e.g. runtime removal)
            except Exception:
                pass  # a live worker still refuses; that is not a receipt either
            assert receipts == []  # nothing is written after close
            assert scheduler.held() == ((job,) if held_state != "no_held" else ())
            if via == "scheduler_close" and held_state != "no_held":
                # The DB reader stays for the next start's recovery; nothing released it.
                assert service.jobs.local_reader_active(job) is True
        finally:
            for item in getattr(factory, "opened", []):
                if hasattr(item, "exit"):
                    item.exit()
            if not closed_service:
                service.close()
