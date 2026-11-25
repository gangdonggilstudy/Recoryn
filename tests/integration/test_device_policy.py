"""G16 integration rows: W (writes 108), R (named orders 72), F (kept files 32), N (canaries 36).

Real TEMP files, real cooperating stores, a deterministic manual worker for the
controller (barrier-like control of run and delivery order) and fault writers. Expected
bytes and states are written by hand from docs/testing/g16-device-policy-cases.md
sections 2 and 5. The user's real settings, Credential Manager, SQLite, models and the
network are never used. No device.
"""

from __future__ import annotations

import itertools
import logging
import os
import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from recoryn.app.device_policy import DevicePolicyStore, PolicyController, PolicyIo
from recoryn.app.recording import RecordingService
from recoryn.domain import AudioFormat, PCMBlock
from recoryn.storage import Library

pytestmark = pytest.mark.integration

CPU, GPU, FALLBACK = "CPU_ONLY", "GPU_ONLY", "GPU_WITH_CPU_FALLBACK_ALLOWED"
POLICIES = (CPU, GPU, FALLBACK)  # hand-written, not imported from the product


def v1(policy: str) -> bytes:
    return b'{"schema_version":1,"execution_policy":"' + policy.encode() + b'"}'


def settings_path(tmp_path: Path) -> Path:
    return tmp_path / "LocalAppData" / "Recoryn" / "preferences" / "device-policy.json"


def leftovers(path: Path) -> list[str]:
    """Anything in the settings folder other than the setting and its lock."""
    if not path.parent.exists():
        return []
    return sorted(
        p.name for p in path.parent.iterdir() if p.name not in (path.name, "device-policy.lock")
    )


class Clock:
    """A fake monotonic clock: every reading advances, so a deadline passes at once."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps = 0

    def monotonic(self) -> float:
        self.now += 0.75
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps += 1


class FaultIo(PolicyIo):
    def __init__(self, fault: str = "success") -> None:
        self.fault = fault
        self.hooks: dict[str, int] = {"open_new": 0, "write": 0, "fsync": 0, "replace": 0}

    def open_new(self, path: Path) -> Any:
        self.hooks["open_new"] += 1
        if self.fault == "temp_denied":
            raise PermissionError("G16 TEMP open denied")
        return super().open_new(path)

    def write(self, stream: Any, data: bytes) -> None:
        self.hooks["write"] += 1
        if self.fault == "short_write":
            stream.write(data[: len(data) // 2])
            raise OSError("Short write")
        super().write(stream, data)

    def fsync(self, stream: Any) -> None:
        self.hooks["fsync"] += 1
        if self.fault == "fsync":
            raise OSError("G16 fsync failure")
        super().fsync(stream)

    def replace(self, source: Path, target: Path) -> None:
        self.hooks["replace"] += 1
        if self.fault == "replace":
            raise PermissionError("G16 sharing violation")
        super().replace(source, target)

    def try_lock(self, path: Path, *, create: bool) -> Any:
        if self.fault == "lock_timeout" and create:
            return None  # a writer's lock is always held by another cooperating store
        return super().try_lock(path, create=create)


# --- W: existing 3 x new 3 x result 6 x same run/restart 2 = 108 --------------------

RESULTS = ("success", "temp_denied", "short_write", "fsync", "replace", "lock_timeout")
W_ROWS = list(itertools.product(POLICIES, POLICIES, RESULTS, ("same", "restart")))
W_CASES = [pytest.param(*row, id=f"G16-W-{i:03d}") for i, row in enumerate(W_ROWS, 1)]


@pytest.mark.parametrize(("old", "new", "result", "mode"), W_CASES)
def test_only_complete_old_or_new_settings_exist(
    tmp_path: Path, old: str, new: str, result: str, mode: str
) -> None:
    path = settings_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_bytes(v1(old))
    clock, io = Clock(), FaultIo(result)
    store = DevicePolicyStore(path, io=io, monotonic=clock.monotonic, sleep=clock.sleep)
    observed = store.load()
    assert (observed.state, observed.policy) == ("RESTORED", old)
    written = store.save(new, observed_revision=observed.revision)
    if result == "lock_timeout":
        expected_state, reason, on_disk = "FAILED", "LOCK_TIMEOUT", old
    elif old == new:
        expected_state, reason, on_disk = "SAVED", "", old  # idempotent: no write is reached
    elif result == "success":
        expected_state, reason, on_disk = "SAVED", "", new
    else:
        expected_state, reason, on_disk = "FAILED", "WRITE_FAILED", old
    assert (written.state, written.reason) == (expected_state, reason)
    assert path.read_bytes() == v1(on_disk)  # a whole old or whole new file, nothing else
    assert leftovers(path) == []  # no TEMP file is left behind
    if old == new or result == "lock_timeout":
        assert io.hooks == {"open_new": 0, "write": 0, "fsync": 0, "replace": 0}
    reader = store if mode == "same" else DevicePolicyStore(path)  # restart: a new instance
    assert reader.load().policy == on_disk


# --- R: named orders 8 x old 3 x new 3 = 72 -----------------------------------------

ORDERS = (
    "load_select_save",
    "select_load_save",
    "select_save_late_load",
    "save1_then_save2",
    "select_select_late_save1",
    "delivered_2_then_1",
    "closed_while_saving",
    "other_process_changed",
)
R_ROWS = list(itertools.product(ORDERS, POLICIES, POLICIES))
R_CASES = [pytest.param(*row, id=f"G16-R-{i:02d}") for i, row in enumerate(R_ROWS, 1)]


SETTINGS_THREAD = "g16-settings-worker"


class Manual:
    """The settings worker, step by step: run (in a worker thread) and deliver separately."""

    def __init__(self) -> None:
        self.jobs: list[dict[str, Any]] = []
        self.gui = threading.get_ident()
        self.worker_threads: list[int] = []

    def submit(self, work: Callable[[], Any], done: Callable[[Any], None]) -> None:
        self.jobs.append({"work": work, "done": done})

    def run(self, index: int) -> None:
        job = self.jobs[index]

        def target() -> None:
            self.worker_threads.append(threading.get_ident())
            job["result"] = job["work"]()

        thread = threading.Thread(target=target, name=SETTINGS_THREAD)
        thread.start()
        thread.join(10)
        assert "result" in job

    def deliver(self, index: int) -> None:
        self.jobs[index]["done"](self.jobs[index]["result"])

    def run_all(self) -> None:
        for index, job in enumerate(self.jobs):
            if "result" not in job:
                self.run(index)


class Views:
    def __init__(self) -> None:
        self.views: list[Any] = []
        self.announced: list[Any] = []

    def __call__(self, view: Any, announce: bool) -> None:
        self.views.append(view)
        if announce:
            self.announced.append(view)


class CountingStore(DevicePolicyStore):
    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.thread_ids: list[int] = []

    def load(self) -> Any:
        self.thread_ids.append(threading.get_ident())
        return super().load()

    def save(self, policy: str, *, observed_revision: str | None) -> Any:
        self.thread_ids.append(threading.get_ident())
        return super().save(policy, observed_revision=observed_revision)


def other_policy(*excluded: str) -> str:
    return next(policy for policy in POLICIES if policy not in excluded)


@pytest.mark.parametrize(("order", "old", "new"), R_CASES)
def test_late_answers_never_replace_newer_choices(
    tmp_path: Path, order: str, old: str, new: str
) -> None:
    path = settings_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_bytes(v1(old))
    identity = (os.stat(path).st_ino, os.stat(path).st_mtime_ns)
    store, worker, views = CountingStore(path), Manual(), Views()
    controller = PolicyController(store, worker.submit, views)
    controller.start()
    assert controller.view().state == "LOADING"
    final, state, on_disk = new, "SAVED", new  # the common expectation, by hand
    if order == "load_select_save":
        worker.run(0), worker.deliver(0)
        assert (controller.current, controller.state) == (old, "RESTORED")
        controller.select(new, user=True)
        worker.run(1), worker.deliver(1)
    elif order == "select_load_save":
        controller.select(new, user=True)
        worker.run_all()
        worker.deliver(0)  # the old load answer arrives first and is ignored
        assert controller.state == "SAVING" and controller.current == new
        worker.deliver(1)
    elif order == "select_save_late_load":
        controller.select(new, user=True)
        worker.run_all()
        worker.deliver(1)
        worker.deliver(0)  # an even later old load answer
    elif order == "save1_then_save2":
        worker.run(0), worker.deliver(0)
        controller.select(new, user=True)
        worker.run(1), worker.deliver(1)
        controller.select(old, user=True)
        worker.run(2), worker.deliver(2)
        final, on_disk = old, old
    elif order == "select_select_late_save1":
        worker.run(0), worker.deliver(0)
        controller.select(new, user=True)
        controller.select(old, user=True)
        worker.run_all()
        before = len(views.views)
        worker.deliver(1)  # the first save's answer is older than the second selection
        assert len(views.views) == before and controller.state == "SAVING"
        worker.deliver(2)
        final, on_disk = old, old
    elif order == "delivered_2_then_1":
        worker.run(0), worker.deliver(0)
        controller.select(new, user=True)
        worker.run(1)
        controller.select(old, user=True)
        worker.run(2)
        worker.deliver(2)
        worker.deliver(1)
        final, on_disk = old, old
    elif order == "closed_while_saving":
        worker.run(0), worker.deliver(0)
        controller.select(new, user=True)
        worker.run(1)  # the started write completes on the worker
        controller.close()
        before = len(views.views)
        worker.deliver(1)
        assert len(views.views) == before  # a closed window ignores the late answer
        state = "CLOSED"
    else:
        worker.run(0), worker.deliver(0)
        third = other_policy(old)
        outside = DevicePolicyStore(path).save(third, observed_revision=None)  # another app
        assert outside.state == "SAVED"
        controller.select(new, user=True)
        worker.run(1), worker.deliver(1)
        state, on_disk = "CONFLICT", third
        assert controller.view().file_policy == third
        controller.select(new, user=True)  # the user saw the conflict and chooses again
        worker.run(2), worker.deliver(2)
        assert controller.state == "SAVED" and path.read_bytes() == v1(new)
        state, on_disk = "SAVED", new
    assert controller.current == final
    assert controller.state == state
    assert path.read_bytes() == v1(on_disk)
    assert all(thread != worker.gui for thread in store.thread_ids)  # never the GUI thread
    assert len(views.announced) == len({(v.state, v.current) for v in views.announced})
    if old == new and order != "other_process_changed":  # every save was of the same bytes
        assert (os.stat(path).st_ino, os.stat(path).st_mtime_ns) == identity  # zero writes


def test_a_program_selection_before_the_load_answer_is_kept_and_not_saved(
    tmp_path: Path,
) -> None:
    """G16-X-02 (compatibility): existing callers set the control right after the window
    is built. That programmatic choice applies to new requests at once, a later restore
    never replaces it, and it is never saved (only a user activation is)."""
    path = settings_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_bytes(v1(GPU))
    store, worker, views = CountingStore(path), Manual(), Views()
    controller = PolicyController(store, worker.submit, views)
    controller.start()
    controller.select(FALLBACK, user=False)
    worker.run(0), worker.deliver(0)
    assert (controller.current, controller.state) == (FALLBACK, "RESTORED")
    assert controller.view().file_policy == GPU
    assert len(worker.jobs) == 1 and path.read_bytes() == v1(GPU)  # no save was queued


CHILD = """
import pathlib, sys
import recoryn
from recoryn.app.device_policy import PolicyIo
print(recoryn.__file__, flush=True)
lock = PolicyIo().try_lock(pathlib.Path(sys.argv[1]), create=True)
print("HELD" if lock is not None else "BUSY", flush=True)
sys.stdin.readline()
lock.release()
print("RELEASED", flush=True)
"""


def test_a_lock_held_by_another_process_fails_closed_then_frees(tmp_path: Path) -> None:
    """G16-X-04: a cooperating process holds the settings lock (a real OS lock in an
    owned child that imports this copy's code): a write waits at most its bound and
    reports LOCK_TIMEOUT with the file untouched; a read reports UNAVAILABLE."""
    import os
    import subprocess
    import sys

    import recoryn

    path = settings_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_bytes(v1(CPU))
    source = Path(recoryn.__file__).resolve().parents[1]
    child = subprocess.Popen(
        [sys.executable, "-B", "-c", CHILD, str(path.with_name("device-policy.lock"))],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        env={**os.environ, "PYTHONPATH": str(source), "PYTHONDONTWRITEBYTECODE": "1"},
    )
    try:
        assert child.stdout is not None and child.stdin is not None
        origin = Path(child.stdout.readline().strip()).resolve()
        assert origin.is_relative_to(source)  # the child runs this copy, not another tree
        assert child.stdout.readline().strip() == "HELD"
        store = DevicePolicyStore(path, lock_timeout=0.2)
        written = store.save(GPU, observed_revision=None)
        assert (written.state, written.reason) == ("FAILED", "LOCK_TIMEOUT")
        read = store.load()
        assert (read.state, read.reason, read.policy) == ("UNAVAILABLE", "LOCK_TIMEOUT", CPU)
        assert path.read_bytes() == v1(CPU) and leftovers(path) == []
        child.stdin.write("\n")
        child.stdin.flush()
        assert child.stdout.readline().strip() == "RELEASED"
        assert child.wait(30) == 0
        assert store.save(GPU, observed_revision=None).state == "SAVED"  # nothing lasting
        assert path.read_bytes() == v1(GPU)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(30)
        for stream in (child.stdin, child.stdout):
            if stream is not None:
                stream.close()


def test_two_stores_saving_at_once_never_both_win(tmp_path: Path) -> None:
    """G16-X-05: two cooperating stores observed the same file and save together: one
    complete file is published and the other writer sees CONFLICT (no lost update)."""
    path = settings_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_bytes(v1(CPU))
    stores = (DevicePolicyStore(path), DevicePolicyStore(path))
    observed = [store.load().revision for store in stores]
    assert observed[0] == observed[1]
    barrier, results = threading.Barrier(2), [None, None]

    def save(index: int, policy: str) -> None:
        barrier.wait(10)
        results[index] = stores[index].save(policy, observed_revision=observed[index])

    threads = [threading.Thread(target=save, args=pair) for pair in ((0, GPU), (1, FALLBACK))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    states = sorted(result.state for result in results if result is not None)
    assert states == ["CONFLICT", "SAVED"]
    winner = next(result for result in results if result is not None and result.state == "SAVED")
    assert path.read_bytes() == v1(winner.policy) and leftovers(path) == []


def test_a_missing_user_location_is_shown_and_never_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G16-X-06 (section 2.1): without LOCALAPPDATA the policy is CPU_ONLY with "check
    the location"; nothing falls back to the working directory or anywhere else."""
    monkeypatch.chdir(tmp_path)
    for environ in ({}, {"LOCALAPPDATA": ""}):
        store = DevicePolicyStore.for_user(environ)
        read = store.load()
        assert (read.state, read.policy, read.reason) == (
            "UNAVAILABLE",
            CPU,
            "LOCATION_UNAVAILABLE",
        )
        written = store.save(GPU, observed_revision=None)
        assert (written.state, written.reason) == ("FAILED", "LOCATION_UNAVAILABLE")
        worker, views = Manual(), Views()
        controller = PolicyController(store, worker.submit, views)
        controller.start()
        worker.run(0), worker.deliver(0)
        assert (controller.state, controller.current) == ("UNAVAILABLE", CPU)
        assert views.views[-1].text == (
            "현재 실행: CPU_ONLY · 설정 위치 확인 필요 · 저장된 설정을 읽지 못함"
            ". 로컬 Ollama 요약은 이 정책에서 차단됩니다(필요하면 AUTO를 직접 선택)"
        )
    assert list(tmp_path.iterdir()) == []  # no cwd fallback


def test_non_finite_and_float_headers_are_damaged_not_future(tmp_path: Path) -> None:
    """G16-X-07 (section 2.1): NaN/Infinity are syntax errors; a float version is never
    v1 nor a future version (only an exact int above 1 is preserved as future)."""
    cases = {
        b'{"schema_version":NaN,"execution_policy":"CPU_ONLY"}': ("INVALID", "SYNTAX"),
        b'{"schema_version":1,"execution_policy":"CPU_ONLY","x":-Infinity}': (
            "INVALID",
            "SYNTAX",
        ),
        b'{"schema_version":1.0,"execution_policy":"GPU_ONLY"}': ("INVALID", "VERSION_UNSUPPORTED"),
        b'{"schema_version":2.0,"execution_policy":"GPU_ONLY"}': ("INVALID", "VERSION_UNSUPPORTED"),
        b'{"schema_version":1,"execution_policy":1.5}': ("INVALID", "POLICY_UNSUPPORTED"),
    }
    path = settings_path(tmp_path)
    path.parent.mkdir(parents=True)
    for content, (state, reason) in cases.items():
        path.write_bytes(content)
        read = DevicePolicyStore(path).load()
        assert (read.state, read.policy, read.reason) == (state, CPU, reason), content
        assert path.read_bytes() == content


def test_a_reset_after_the_file_was_fixed_elsewhere_is_a_conflict(tmp_path: Path) -> None:
    """G16-X-08 (section 2.3): the worker re-checks the target. A damaged file another app
    has fixed in the meantime is never replaced by a confirmed reset; an unconfirmed reset
    does no I/O at all."""
    path = settings_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"{")
    io = FaultIo()
    unconfirmed = DevicePolicyStore(path, io=io).reset_invalid(
        CPU, observed_revision=None, confirmed=False
    )
    assert (unconfirmed.state, unconfirmed.reason) == ("REFUSED", "NOT_CONFIRMED")
    assert io.hooks == {"open_new": 0, "write": 0, "fsync": 0, "replace": 0}
    worker, views = Manual(), Views()
    controller = PolicyController(DevicePolicyStore(path), worker.submit, views)
    controller.start()
    worker.run(0), worker.deliver(0)
    assert controller.state == "INVALID"
    path.write_bytes(v1(GPU))  # another app repaired the file
    controller.reset(confirmed=True)
    worker.run(1), worker.deliver(1)
    assert controller.state == "CONFLICT" and controller.view().file_policy == GPU
    assert path.read_bytes() == v1(GPU) and leftovers(path) == []


class TempLeft(FaultIo):
    def remove(self, path: Path) -> None:
        self.removed = path
        raise PermissionError("G16 TEMP still open elsewhere")


def test_a_temp_file_that_cannot_be_removed_is_reported_and_kept(tmp_path: Path) -> None:
    """G16-X-09 (section 2.3): a failed write whose TEMP cleanup also fails reports
    WRITE_FAILED_TEMP_LEFT; the original setting is whole and only the TEMP file of
    this write remains (nothing else is deleted); the next save starts fresh."""
    path = settings_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_bytes(v1(CPU))
    io = TempLeft("fsync")
    written = DevicePolicyStore(path, io=io).save(GPU, observed_revision=None)
    assert (written.state, written.reason) == ("FAILED", "WRITE_FAILED_TEMP_LEFT")
    assert path.read_bytes() == v1(CPU)
    left = leftovers(path)
    assert (
        len(left) == 1 and left[0].startswith(".device-policy.json.") and left[0].endswith(".tmp")
    )
    assert io.removed == path.parent / left[0]  # only that TEMP file was ever removed
    assert DevicePolicyStore(path).save(GPU, observed_revision=None).state == "SAVED"
    assert path.read_bytes() == v1(GPU)


def test_saves_queued_before_a_conflict_was_seen_never_overwrite(tmp_path: Path) -> None:
    """G16-X-10 (section 2.3): two choices queued behind one stale observation: the
    first meets the other app's change (CONFLICT); the second is reported as the same
    conflict without writing. A choice made after the conflict was shown saves."""
    path = settings_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_bytes(v1(CPU))
    worker, views = Manual(), Views()
    controller = PolicyController(CountingStore(path), worker.submit, views)
    controller.start()
    worker.run(0), worker.deliver(0)
    assert DevicePolicyStore(path).save(FALLBACK, observed_revision=None).state == "SAVED"
    identity = os.stat(path).st_ino, os.stat(path).st_mtime_ns
    controller.select(GPU, user=True)
    controller.select(CPU, user=True)
    worker.run(1), worker.run(2)
    assert worker.jobs[1]["result"].state == worker.jobs[2]["result"].state == "CONFLICT"
    assert (os.stat(path).st_ino, os.stat(path).st_mtime_ns) == identity  # no write
    worker.deliver(1), worker.deliver(2)
    assert controller.state == "CONFLICT" and controller.view().file_policy == FALLBACK
    controller.select(GPU, user=True)
    worker.run(3), worker.deliver(3)
    assert controller.state == "SAVED" and path.read_bytes() == v1(GPU)


def test_a_missing_worker_answer_fails_safe(tmp_path: Path) -> None:
    """G16-X-11: a settings task that failed delivers no result; the load shows
    UNAVAILABLE with CPU_ONLY and the save shows "not saved", never success."""
    path = settings_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_bytes(v1(GPU))
    views = Views()
    controller = PolicyController(DevicePolicyStore(path), lambda work, done: done(None), views)
    controller.start()
    assert (controller.state, controller.current) == ("UNAVAILABLE", CPU)
    controller.select(FALLBACK, user=True)
    assert (controller.state, controller.current) == ("SAVE_FAILED", FALLBACK)
    assert path.read_bytes() == v1(GPU)
    assert [v.state for v in views.announced] == ["UNAVAILABLE", "SAVE_FAILED"]


# --- F: kept settings 8 x action 4 = 32 ---------------------------------------------

F_STATES = {
    "future_basic": (b'{"schema_version":2}', "FUTURE_VERSION"),
    "future_extra": (
        b'{"schema_version":3,"execution_policy":"GPU_ONLY","origin":"newer-app"}',
        "FUTURE_VERSION",
    ),
    "future_type": (b'{"schema_version":2,"execution_policy":{"device":[0.5]}}', "FUTURE_VERSION"),
    "broken": (b'{"schema_version":1,"execution_policy":', "INVALID"),
    "type_error": (b'{"schema_version":1,"execution_policy":1}', "INVALID"),
    "utf8": (b'{"schema_version":1,"execution_policy":"\xc3\x28"}', "INVALID"),
    "uninspectable": (v1(GPU), "UNAVAILABLE"),
    "normal": (v1(GPU), "RESTORED"),
}
F_ACTIONS = ("load", "select_save", "reset_confirmed", "reset_cancelled")
F_ROWS = list(itertools.product(tuple(F_STATES), F_ACTIONS))
F_CASES = [pytest.param(*row, id=f"G16-F-{i:02d}") for i, row in enumerate(F_ROWS, 1)]


@pytest.mark.parametrize(("name", "action"), F_CASES)
def test_future_and_damaged_settings_are_kept_until_an_explicit_reset(
    tmp_path: Path, name: str, action: str
) -> None:
    content, loaded = F_STATES[name]
    path = settings_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    if name == "uninspectable":
        (path.parent / "other-name.json").hardlink_to(path)  # the file cannot be trusted
    worker, views = Manual(), Views()
    controller = PolicyController(DevicePolicyStore(path), worker.submit, views)
    controller.start()
    worker.run(0), worker.deliver(0)
    assert controller.state == loaded
    assert controller.current == (GPU if loaded == "RESTORED" else CPU)
    writes_expected = None
    if action == "select_save":
        controller.select(FALLBACK, user=True)
        worker.run(1), worker.deliver(1)
        expected = {
            "FUTURE_VERSION": "FUTURE_VERSION",
            "INVALID": "INVALID",
            "UNAVAILABLE": "SAVE_FAILED",
            "RESTORED": "SAVED",
        }[loaded]
        assert controller.state == expected and controller.current == FALLBACK
        writes_expected = v1(FALLBACK) if loaded == "RESTORED" else content
    elif action == "reset_confirmed":
        assert controller.view().reset_allowed is (loaded == "INVALID")
        controller.reset(confirmed=True)
        if loaded == "INVALID":
            worker.run(1), worker.deliver(1)
            assert controller.state == "SAVED"
            writes_expected = v1(CPU)  # the current choice replaces only a damaged file
        else:
            assert len(worker.jobs) == 1  # nothing submitted for a kept or valid file
            writes_expected = content
        if loaded == "FUTURE_VERSION":  # even a direct store call never overwrites it
            direct = DevicePolicyStore(path).reset_invalid(
                CPU, observed_revision=None, confirmed=True
            )
            assert (direct.state, direct.reason) == ("REFUSED", "FUTURE_VERSION")
    elif action == "reset_cancelled":
        for _answer in ("No", "Escape"):  # both answers decline; neither writes
            controller.reset(confirmed=False)
        assert len(worker.jobs) == 1
        writes_expected = content
    else:
        writes_expected = content
    assert path.read_bytes() == writes_expected
    assert leftovers(path) == (["other-name.json"] if name == "uninspectable" else [])


# --- N: policy 3 x load/change/reset 3 x canary 4 = 36 ------------------------------

CANARIES = {
    "key": "sk-g16-key-CANARY",
    "credential": "cred-ref-g16-CANARY",
    "grant": "grant-g16-CANARY",
    "body": "body-g16-CANARY",
}
N_ROWS = list(itertools.product(POLICIES, ("load", "change", "reset"), tuple(CANARIES)))
N_CASES = [pytest.param(*row, id=f"G16-N-{i:02d}") for i, row in enumerate(N_ROWS, 1)]
FMT = AudioFormat(48000, 1)


class Leaky(PolicyIo):
    """A writer whose OS error carries the canary; blocks until released if asked."""

    def __init__(self, canary: str, *, fail: bool, gate: threading.Event | None) -> None:
        self.canary, self.fail, self.gate = canary, fail, gate
        self.entered = threading.Event()

    def open_new(self, path: Path) -> Any:
        self.entered.set()
        if self.gate is not None:
            assert self.gate.wait(10)
        if self.fail:
            raise PermissionError("denied " + self.canary)
        return super().open_new(path)


def record_once(root: Path) -> int:
    """A real recording start/submit/stop while the settings worker is blocked."""
    with Library(root) as library:
        service = RecordingService(library, {"mic": FMT}, session_id="n-rec", chunk_frames=480)
        service.start()
        try:
            block = PCMBlock(
                "n-rec",
                "mic",
                service.epochs["mic"],
                0,
                FMT,
                480,
                b"\0\x01" * 480,
                1,
                1,
                device_frame_position=0,
            )
            assert service.submit(block)
            service.stop(timeout=30)
        finally:
            service.join_writer()
        return sum(chunk.frame_count for chunk in library.chunks("n-rec"))


@pytest.mark.parametrize(("policy", "action", "kind"), N_CASES)
def test_only_the_policy_is_stored_and_recording_never_waits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    policy: str,
    action: str,
    kind: str,
) -> None:
    canary = CANARIES[kind]
    caplog.set_level(logging.DEBUG)
    import recoryn.security as security

    def guarded(original: Any) -> Any:
        """Refuse the call on the settings worker only; recording keeps its own SQLite."""

        def call(*args: Any, **kwargs: Any) -> Any:
            if threading.current_thread().name == SETTINGS_THREAD:
                touched.append(getattr(original, "__name__", "?"))
                raise AssertionError("the policy setting touched a vault or SQLite")
            return original(*args, **kwargs)

        return call

    touched: list[str] = []
    monkeypatch.setattr(security, "CredentialVault", guarded(security.CredentialVault))
    monkeypatch.setattr(sqlite3, "connect", guarded(sqlite3.connect))
    path = settings_path(tmp_path)
    path.parent.mkdir(parents=True)
    other = other_policy(policy)
    if action == "load":
        path.write_bytes(v1(policy)[:-1] + b',"extra":"' + canary.encode() + b'"}')
    elif action == "change":
        path.write_bytes(v1(other))
    else:
        path.write_bytes(b'{"schema_version":1,"execution_policy":"' + canary.encode() + b'"')
    gate = threading.Event()
    io = Leaky(canary, fail=action == "change", gate=gate if action != "load" else None)
    worker, views = Manual(), Views()
    controller = PolicyController(DevicePolicyStore(path, io=io), worker.submit, views)
    controller.start()
    worker.run(0), worker.deliver(0)
    assert controller.state == ("INVALID" if action != "change" else "RESTORED")
    frames = 0
    if action == "change":
        controller.select(policy, user=True)
    elif action == "reset":
        controller.select(policy, user=False)  # the current choice; never saved by itself
        controller.reset(confirmed=True)
    if action != "load":
        blocked = threading.Thread(target=lambda: worker.run(1))
        blocked.start()
        assert io.entered.wait(10)
        frames = record_once(tmp_path / "library")  # completes while the setting is blocked
        gate.set()
        blocked.join(10)
        worker.deliver(1)
    if action == "change":
        assert (controller.state, controller.current) == ("SAVE_FAILED", policy)
        assert path.read_bytes() == v1(other)  # the failed write left the old file whole
        io.fail = False
        controller.select(policy, user=True)
        worker.run(2), worker.deliver(2)
    if action != "load":
        assert frames == 480
        assert controller.state == "SAVED" and path.read_bytes() == v1(policy)  # two keys only
    texts = " ".join(v.text for v in views.views) + " " + caplog.text
    assert canary not in texts  # neither a label, a reason nor a log line carries it
    refused = DevicePolicyStore(path).save("AUTO", observed_revision=None)
    assert (refused.state, refused.reason) == ("REFUSED", "POLICY_UNSUPPORTED")
    controller.select("AUTO", user=True)  # never a fourth stored policy
    assert controller.current in POLICIES
    assert len(worker.jobs) == {"load": 1, "change": 3, "reset": 2}[action]
    assert touched == [] and worker.worker_threads  # load, save and reset all guarded


def test_declared_integration_denominators_are_complete_and_unique() -> None:
    groups = {"W": (W_CASES, 108, 3), "R": (R_CASES, 72, 2), "F": (F_CASES, 32, 2)}
    groups["N"] = (N_CASES, 36, 2)
    for name, (cases, size, width) in groups.items():
        assert len(cases) == size
        assert [c.id for c in cases] == [f"G16-{name}-{i:0{width}d}" for i in range(1, size + 1)]
