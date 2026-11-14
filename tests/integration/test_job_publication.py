"""Exercise independent SQLite connections and durable cancellation ordering."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from recoryn.domain import StateConflict
from recoryn.jobs import JobState, JobStore
from recoryn.storage import Library

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("cancel_first", (True, False))
def test_cancel_and_completion_order_is_durable(tmp_path: Path, cancel_first: bool) -> None:
    with Library(tmp_path) as library:
        library.create_session("jobs")
        with JobStore(tmp_path / "library.sqlite") as publisher:
            job = publisher.create("transcribe", "sha256:independent-input")
            attempt = publisher.claim(job.job_id, "test-worker")
            with JobStore(tmp_path / "library.sqlite") as canceller:
                if cancel_first:
                    canceller.cancel(job.job_id)
                    with pytest.raises(StateConflict):
                        publisher.complete(job.job_id, attempt.attempt_id, attempt.fence, "result")
                    assert publisher.get(job.job_id).result_ref is None
                else:
                    publisher.complete(job.job_id, attempt.attempt_id, attempt.fence, "result")
                    assert canceller.cancel(job.job_id).state is JobState.SUCCEEDED
    with JobStore(tmp_path / "library.sqlite") as restarted:
        record = restarted.get(job.job_id)
        if cancel_first:
            assert record.state is JobState.CANCEL_REQUESTED
            restarted.recover_abandoned()
            assert restarted.get(job.job_id).state is JobState.CANCELLED
            with pytest.raises(StateConflict):
                restarted.complete(job.job_id, attempt.attempt_id, attempt.fence, "late")
        else:
            assert record.state is JobState.SUCCEEDED
            assert record.result_ref == "result"


def test_competing_connections_cannot_both_claim_one_job(tmp_path: Path) -> None:
    with Library(tmp_path), JobStore(tmp_path / "library.sqlite") as jobs:
        job = jobs.create("transcribe", "same-input")
    barrier = Barrier(2)

    def claim(owner: str) -> bool:
        with JobStore(tmp_path / "library.sqlite") as connection:
            barrier.wait(timeout=10)
            try:
                connection.claim(job.job_id, owner)
            except StateConflict:
                return False
            return True

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(claim, ("worker-a", "worker-b")))
    assert outcomes.count(True) == 1
    assert outcomes.count(False) == 1
