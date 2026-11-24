"""G11 case space: Q (pending priority/fair turn) on the real runner, and the census.

The family formulas are transcribed from the G11 contract (section 7.1 and the amendment
section 6). G-P11a owns A36 + Ua144 + C001-016 + C097-100 + T19/20/27/28/30/31 = 206;
G-P11b owns the other 32,593. Every ID must be parametrized or named by exactly one node.
The Q oracle is an independent rule model; it never calls the runner's selection.
"""

from __future__ import annotations

import inspect
import threading
from itertools import product
from pathlib import Path
from typing import Any

import pytest

from recoryn.jobs import JobStore
from recoryn.jobs.runner import BoundedRunner
from recoryn.models import ResourceRequest
from tests.integration import test_resource_policy as integration
from tests.ui import test_resource_policy_ui as ui
from tests.unit import test_resource_policy as unit

FAMILIES = {
    "A": ("G11-A-{:02}", 36),
    "P": ("G11-P-{:05}", 31104),
    "E": ("G11-E-{:02}", 72),
    "G": ("G11-G-{:03}", 120),
    "R": ("G11-R-{:03}", 144),
    "Q": ("G11-Q-{:03}", 864),
    "L": ("G11-L-{:02}", 96),
    "UA": ("G11-UA-{:03}", 144),
    "UB": ("G11-UB-{:02}", 48),
    "C": ("G11-C-{:03}", 120),
    "S": ("G11-S-{:02}", 20),
    "T": ("G11-T-{:02}", 31),
}
P11A_RULE = {
    "A": set(range(1, 37)),
    "UA": set(range(1, 145)),
    "C": set(range(1, 17)) | set(range(97, 101)),
    "T": {19, 20, 27, 28, 30, 31},
}

# --- Q: three waiters, priority combos, cancel mask, already-running, fair counter ------
Q = list(
    product(product((0, 1, 2), repeat=3), product((False, True), repeat=3), (False, True), (0, 3))
)
Q_IDS = [f"G11-Q-{n:03}" for n in range(1, 865)]


def q_oracle(row: tuple[Any, ...]) -> list[str]:
    """Hand rule (G11 5.2): cancelled never chosen, the running task is not preempted,
    a normal turn takes the lowest priority then the oldest, and the turn after three
    priority picks takes the oldest regardless of priority."""
    priorities, cancelled, running, counter = row
    waiting = [index for index in range(3) if not cancelled[index]]
    order = ["running"] if running else []
    turns = counter
    while waiting:
        if turns >= 3:
            pick = min(waiting)
            turns = 0
        else:
            pick = min(waiting, key=lambda index: (priorities[index], index))
            turns += 1
        order.append(f"w{pick}")
        waiting.remove(pick)
    return order


def _trace(row: tuple[Any, ...]) -> list[str]:
    priorities, cancelled, running, counter = row
    order: list[str] = []
    started, release = threading.Event(), threading.Event()
    with JobStore(Path(":memory:")) as store:
        runner = BoundedRunner(store)
        runner.start()
        try:
            if running:
                blocker = store.create("transcription", "running")

                def hold(attempt: Any, cancel: threading.Event) -> str:
                    started.set()
                    assert release.wait(10)
                    order.append("running")
                    return "ok"

                assert runner.submit(blocker.job_id, hold, priority=2)
                assert started.wait(10)
            ids = []
            # Hold the single selection point while queuing, so all three are pending.
            with runner._condition:
                for index, priority in enumerate(priorities):
                    job = store.create("transcription", f"w{index}")
                    ids.append(job.job_id)

                    def work(attempt: Any, cancel: threading.Event, name: str = f"w{index}") -> str:
                        order.append(name)
                        return "ok"

                    assert runner.submit(job.job_id, work, priority=priority)
                for index, flag in enumerate(cancelled):
                    if flag:
                        runner.cancel(ids[index])
                runner._turns = counter  # fixture: the fair-turn counter at this moment
            release.set()
            with runner._condition:
                assert runner._condition.wait_for(
                    lambda: not runner._queue and not runner._active, timeout=10
                )
        finally:
            release.set()
            runner.stop()
    return order


def test_q_pending_selection_on_the_real_runner() -> None:
    """G11-Q-001..864: every row runs a real BoundedRunner trace (batched in one node)."""
    mismatches = []
    for case, row in zip(Q_IDS, Q, strict=True):
        actual, want = _trace(row), q_oracle(row)
        if actual != want:
            mismatches.append((case, row, want, actual))
    assert len(Q) == len(set(Q)) == 864
    assert mismatches == [], mismatches[:3]


def test_background_waiter_progresses_under_continuous_interactive_arrivals() -> None:
    """G11-AUX-Q-STARVATION: each interactive task admits a new one, yet the older
    background waiter runs at the fourth dispatch (a bounded trace, not a time SLA)."""
    order: list[str] = []
    with JobStore(Path(":memory:")) as store:
        runner = BoundedRunner(store)
        runner.start()
        try:
            arrivals = {"n": 0}

            def interactive(attempt: Any, cancel: threading.Event) -> str:
                order.append("interactive")
                if arrivals["n"] < 6:
                    arrivals["n"] += 1
                    job = store.create("transcription", f"i{arrivals['n']}")
                    assert runner.submit(job.job_id, interactive, priority=0)
                return "ok"

            def background(attempt: Any, cancel: threading.Event) -> str:
                order.append("background")
                return "ok"

            with runner._condition:
                runner._turns = 0
                old = store.create("transcription", "b")
                assert runner.submit(old.job_id, background, priority=2)
                first = store.create("transcription", "i0")
                assert runner.submit(first.job_id, interactive, priority=0)
            with runner._condition:
                assert runner._condition.wait_for(
                    lambda: not runner._queue and not runner._active and arrivals["n"] == 6,
                    timeout=10,
                )
        finally:
            runner.stop()
    assert order.index("background") == 3 and order.count("interactive") == 7


# --- census ----------------------------------------------------------------------------
def ids(family: str) -> list[str]:
    pattern, size = FAMILIES[family]
    return [pattern.format(n) for n in range(1, size + 1)]


def _named(function: Any, cases: tuple[str, ...]) -> list[str]:
    doc = inspect.getdoc(function) or ""
    return [case for case in cases if doc.startswith(case)]


def declared_p11a() -> list[str]:
    named = _named(
        ui.test_t30_continue_after_policy_change_takes_a_new_snapshot, ("G11-T-30",)
    ) + _named(ui.test_t31_strict_ollama_refusal_precedes_attestation, ("G11-T-31",))
    return [
        *unit.A_IDS,
        *unit.C_IDS,
        *unit.C_PENDING_IDS,
        *unit.T_IDS,
        *integration.T_IDS,
        *ui.UA_IDS,
        *named,
    ]


def declared_p11b() -> list[str]:
    return [
        *unit.P_IDS,
        *unit.E_IDS,
        *unit.C_B_IDS,
        *unit.C_B_PENDING_IDS,
        *unit.T_UNIT,
        *integration.G_IDS,
        *integration.R_IDS,
        *integration.L_IDS,
        *integration.S_IDS,
        *integration.T_SERVICE,
        *Q_IDS,
        *ui.UB_IDS,
        *_named(ui.test_t29_unknown_requirement_never_reaches_the_legacy_helper, ("G11-T-29",)),
    ]


def test_full_amended_denominator() -> None:
    every = [case for family in FAMILIES for case in ids(family)]
    assert len(every) == len(set(every)) == 32_799
    assert sum(size for _, size in FAMILIES.values()) == 32_772 + 24 + 3


def test_every_id_is_claimed_once_by_its_unit() -> None:
    every = {case for family in FAMILIES for case in ids(family)}
    rule_a = {FAMILIES[f][0].format(n) for f, numbers in P11A_RULE.items() for n in numbers}
    rule_b = every - rule_a
    a, b = declared_p11a(), declared_p11b()
    for nodes, rule, size in ((a, rule_a, 206), (b, rule_b, 32_593)):
        missing, extra = rule - set(nodes), set(nodes) - rule
        assert (len(rule), len(missing), len(nodes) - len(set(nodes)), len(extra)) == (
            size,
            0,
            0,
            0,
        ), sorted(missing)[:5]
    assert not set(a) & set(b) and set(a) | set(b) == every


def test_family_tuples_match_their_ids() -> None:
    assert len(unit.A) == len(unit.A_IDS) and len(ui.UA) == len(ui.UA_IDS)
    assert len(unit.C) == len(unit.C_IDS) and len(unit.C_PENDING) == len(unit.C_PENDING_IDS)
    assert ui.UA == list(product(unit.POLICIES, unit.KINDS, unit.BACKENDS, ui.STAGES))
    pairs = (
        (unit.P, unit.P_IDS),
        (unit.E, unit.E_IDS),
        (unit.C_B, unit.C_B_IDS),
        (unit.C_B_PENDING, unit.C_B_PENDING_IDS),
        (integration.G, integration.G_IDS),
        (integration.R, integration.R_IDS),
        (integration.L, integration.L_IDS),
        (integration.S, integration.S_IDS),
        (Q, Q_IDS),
        (ui.UB, ui.UB_IDS),
    )
    for rows, names in pairs:
        assert len(rows) == len(set(rows)) == len(names)


@pytest.mark.parametrize("unused", [None], ids=["G11-AUX-DIGEST"])
def test_request_digest_separates_every_static_field(unused: None) -> None:
    """Auxiliary: the captured snapshot identity distinguishes each field it carries."""
    requests = [
        ResourceRequest(kind, backend, policy, priority=priority)
        for (policy, kind, backend), priority in product(unit.A, (0, 1, 2))
    ]
    digests = {request.digest for request in requests}
    assert len(digests) == len(requests) == 108
    base = ResourceRequest("stt", "LOCAL_CT2", "CPU_ONLY")
    variants = [
        ResourceRequest("stt", "LOCAL_CT2", "CPU_ONLY", model_identity="m"),
        ResourceRequest("stt", "LOCAL_CT2", "CPU_ONLY", runtime_identity="m"),
        ResourceRequest("stt", "LOCAL_CT2", "CPU_ONLY", profile_identity="m"),
        ResourceRequest("stt", "LOCAL_CT2", "CPU_ONLY", preferred_gpu="m"),
        ResourceRequest("stt", "LOCAL_CT2", "CPU_ONLY", input_envelope=(("frames", 1),)),
    ]
    assert len({base.digest, *(item.digest for item in variants)}) == 6
