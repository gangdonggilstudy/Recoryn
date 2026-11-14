"""Explicit, bounded local dispatch. Inference never runs on a capture caller."""

from __future__ import annotations

import math
import re
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from recoryn.domain import StateConflict, ValidationError

from . import AttemptRecord, JobRecord, JobState, JobStore

Task = Callable[[AttemptRecord, threading.Event], str]


@dataclass(frozen=True)
class _Work:
    job_id: str
    task: Task
    cancel: threading.Event


class BoundedRunner:
    """At most ``workers`` active tasks plus ``capacity`` queued task closures.

    start/stop are explicit. stop cancels accepted unfinished work and waits for
    local acknowledgement; a timeout leaves running=True and is never success.
    Tasks receive a new Attempt on retry, must cooperate with cancel, and may
    save partial content through ContentStore's fenced publication API. Python
    threads cannot kill a hung model; isolation belongs to the runtime adapter.
    """

    RETRY_DELAY = 0.05

    def __init__(
        self, jobs: JobStore, *, capacity: int = 16, workers: int = 1, owner: str = "local"
    ) -> None:
        if not isinstance(jobs, JobStore):
            raise ValidationError("RUNNER_JOB_STORE_REQUIRED")
        for name, value, maximum in (("capacity", capacity, 65536), ("workers", workers, 32)):
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValidationError("INVALID_RUNNER_" + name.upper())
        if not isinstance(owner, str) or not owner.strip() or len(owner) > 128 or "\x00" in owner:
            raise ValidationError("INVALID_RUNNER_OWNER")
        self.jobs = jobs
        self.capacity, self.workers, self.owner = capacity, workers, owner
        self._condition = threading.Condition(threading.RLock())
        self._queue: deque[_Work] = deque()
        self._active: dict[str, _Work] = {}
        self._threads: list[threading.Thread] = []
        self._accepting = False
        self._stopping = False
        self._counts = {
            "submitted": 0,
            "succeeded": 0,
            "failed": 0,
            "cancelled": 0,
            "blocked": 0,
            "high_water": 0,
        }
        self._last_error: str | None = None
        self._reader_ack_error: str | None = None

    @property
    def running(self) -> bool:
        with self._condition:
            return any(thread.is_alive() for thread in self._threads)

    def snapshot(self) -> dict[str, Any]:
        with self._condition:
            return {
                **self._counts,
                "pending": len(self._queue),
                "active": tuple(self._active),
                "running": any(thread.is_alive() for thread in self._threads),
                "accepting": self._accepting,
                "last_error": self._last_error,
                "reader_ack_error": self._reader_ack_error,
            }

    def start(self) -> None:
        with self._condition:
            self.jobs._ensure_open()
            if any(thread.is_alive() for thread in self._threads):
                if self._accepting:
                    return
                raise StateConflict("RUNNER_STOP_INCOMPLETE")
            self._accepting, self._stopping = True, False
            self._threads = [
                threading.Thread(target=self._worker, name=f"recoryn-ai-{index}", daemon=True)
                for index in range(self.workers)
            ]
            for thread in self._threads:
                thread.start()

    def submit(self, job_id: str, task: Task) -> bool:
        if not callable(task):
            raise ValidationError("INVALID_RUNNER_TASK")
        job = self.jobs.get(job_id)
        if job.state not in (JobState.QUEUED, JobState.BACKOFF) and not (
            job.state == JobState.BLOCKED and job.blocked_reason == "ABANDONED"
        ):
            return False
        with self._condition:
            if not self._accepting:
                raise StateConflict("RUNNER_NOT_RUNNING")
            if (
                len(self._queue) >= self.capacity
                or job_id in self._active
                or any(item.job_id == job_id for item in self._queue)
            ):
                return False
            self._queue.append(_Work(job_id, task, threading.Event()))
            self._counts["submitted"] += 1
            self._counts["high_water"] = max(self._counts["high_water"], len(self._queue))
            self._condition.notify()
            return True

    def cancel(self, job_id: str) -> JobRecord:
        # Commit the fence revocation before telling the task to return.
        job = self.jobs.cancel(job_id)
        with self._condition:
            if job_id in self._active:
                self._active[job_id].cancel.set()
            retained: deque[_Work] = deque()
            for item in self._queue:
                if item.job_id == job_id:
                    item.cancel.set()
                    self._counts["cancelled"] += 1
                else:
                    retained.append(item)
            self._queue = retained
            self._condition.notify_all()
        return job

    def stop(self, timeout: float = 5.0) -> None:
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout < 0
        ):
            raise ValidationError("INVALID_RUNNER_TIMEOUT")
        if threading.current_thread() in self._threads:
            raise StateConflict("RUNNER_CANNOT_JOIN_ITSELF")
        deadline = time.monotonic() + timeout
        with self._condition:
            self._accepting, self._stopping = False, True
            work = [*self._queue, *self._active.values()]
            self._counts["cancelled"] += len(self._queue)
            self._queue.clear()
            self._condition.notify_all()
        for item in work:
            self.jobs.cancel(item.job_id)
            item.cancel.set()
        for thread in self._threads:
            thread.join(max(0.0, deadline - time.monotonic()))
        if self.running:
            raise TimeoutError("RUNNER_STOP_TIMEOUT")

    def _worker(self) -> None:
        while True:
            with self._condition:
                while not self._queue and not self._stopping:
                    self._condition.wait()
                if self._stopping:
                    return
                item = self._queue.popleft()
                self._active[item.job_id] = item
            try:
                self._execute(item)
            finally:
                with self._condition:
                    self._active.pop(item.job_id, None)
                    self._condition.notify_all()

    @staticmethod
    def _failure(exc: Exception) -> tuple[str, bool, bool]:
        code = getattr(exc, "code", "TASK_FAILED")
        if not isinstance(code, str) or re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", code) is None:
            code = "TASK_FAILED"
        return (
            code,
            getattr(exc, "retryable", False) is True,
            getattr(exc, "outcome_known", True) is True,
        )

    def _execute(self, item: _Work) -> None:
        try:
            while not item.cancel.is_set():
                attempt = self.jobs.claim(item.job_id, self.owner)
                try:
                    self.jobs.reader_started(attempt)
                    task_error: BaseException | None = None
                    try:
                        result_ref = item.task(attempt, item.cancel)
                    except BaseException as exc:
                        task_error = exc
                        raise
                    finally:
                        # A logical UNKNOWN/SUCCEEDED result is not a physical
                        # read ACK. Record exit only after task I/O has unwound.
                        try:
                            self.jobs.reader_finished(attempt)
                        except Exception:
                            with self._condition:
                                self._reader_ack_error = "LOCAL_READER_ACK_FAILED"
                            if task_error is None:
                                raise
                            # ACK storage failure must not mask a remote UNKNOWN
                            # with an ordinary local error (or release its reader).
                    if item.cancel.is_set():
                        self.jobs._ack_cancelled(attempt)
                    else:
                        self.jobs.complete(
                            item.job_id, attempt.attempt_id, attempt.fence, result_ref
                        )
                    break
                except Exception as exc:
                    code, retryable, known = self._failure(exc)
                    with self._condition:
                        self._last_error = code
                    current = self.jobs.get(item.job_id)
                    if current.state == JobState.CANCEL_REQUESTED:
                        self.jobs._ack_cancelled(attempt, outcome_known=known)
                        break
                    if current.state != JobState.RUNNING or current.fence != attempt.fence:
                        break
                    failed = self.jobs.fail(
                        item.job_id,
                        attempt.attempt_id,
                        attempt.fence,
                        code,
                        retryable=retryable,
                        outcome_known=known,
                    )
                    if failed.state != JobState.BACKOFF:
                        break
                    # Retries occupy their existing worker slot, never a new
                    # unbounded queue/timer or a blocking put into a full queue.
                    if item.cancel.wait(min(1.0, self.RETRY_DELAY * 2 ** (attempt.attempt_no - 1))):
                        break
        except (StateConflict, KeyError):
            with self._condition:
                self._last_error = "JOB_UNAVAILABLE"
        except Exception:
            with self._condition:
                self._last_error = "RUNNER_STORE_FAILED"
        finally:
            try:
                state = self.jobs.get(item.job_id).state
                key = {
                    JobState.SUCCEEDED: "succeeded",
                    JobState.FAILED: "failed",
                    JobState.CANCELLED: "cancelled",
                    JobState.BLOCKED: "blocked",
                }.get(state)
                if key is not None:
                    with self._condition:
                        self._counts[key] += 1
            except (StateConflict, KeyError):
                pass
