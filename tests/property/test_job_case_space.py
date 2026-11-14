"""Q21 finite Job histories: independent state model, case census and SQL oracles."""

from __future__ import annotations

import json
import os
from collections import Counter
from dataclasses import dataclass, field
from itertools import product
from pathlib import Path

import pytest

import recoryn.jobs as jobs_module
from recoryn.domain import StateConflict, ValidationError
from recoryn.jobs import AttemptRecord, JobStore

pytestmark = pytest.mark.property
ALPHABET = "CXPRUA"
WORDS = tuple(product(ALPHABET, repeat=4))
DEEP = tuple(product("RA", repeat=3))
SEEDS = ("CRC", "CRCX", "CRCU", "CRCP", "CRCR", "CRCRCR", "CRCXA", "CRCA")
FENCES = tuple(product(SEEDS, ("first", "latest"), (-1, 0, 1), ("out", "other")))
RECOVERY = tuple(product((1, 3), (False, True), (False, True), (False, True), (False, True)))
OBSERVED: Counter[str] = Counter()
PREFIXES: set[str] = set()
EDGES: Counter[tuple[str, str, str, str]] = Counter()


@dataclass
class History:
    """Contract-level attempt identity is its ordinal, not the generated UUID."""

    fence: int
    owner: str
    state: str = "RUNNING"
    result: str | None = None
    error: str | None = None


@dataclass
class Oracle:
    state: str = "QUEUED"
    fence: int = 0
    version: int = 0
    cancelled: bool = False
    owner: str | None = None
    result: str | None = None
    error: str | None = None
    reason: str | None = None
    attempts: list[History] = field(default_factory=list)
    events: list[tuple[int, str, int, int]] = field(default_factory=lambda: [(0, "QUEUED", 0, 0)])
    reader: bool = False
    remote: bool = False

    def event(self) -> None:
        self.version += 1
        self.events.append((len(self.attempts), self.state, self.fence, self.version))

    def complete(self, ordinal: int, fence: int, result: str) -> type[Exception] | None:
        if fence <= 0:
            return ValidationError
        current = ordinal == len(self.attempts) and ordinal > 0
        if self.state == "SUCCEEDED" and current and fence == self.fence and result == self.result:
            return None  # Only this exact successful result may replay.
        if not (self.state == "RUNNING" and current and fence == self.fence and not self.cancelled):
            return StateConflict
        self.state, self.result, self.owner = "SUCCEEDED", result, None
        self.attempts[-1].state, self.attempts[-1].result = "SUCCEEDED", result
        self.event()
        return None

    def command(self, command: str, *, exclusive: bool = False) -> type[Exception] | None:
        count = len(self.attempts)
        if command == "C":
            available = self.state in {"QUEUED", "BACKOFF"} or (
                self.state == "BLOCKED" and self.reason == "ABANDONED"
            )
            if not available or self.cancelled or count >= 3 or self.reader:
                return StateConflict
            self.fence += 1
            self.owner = f"owner-{count + 1}"
            self.attempts.append(History(self.fence, self.owner))
            self.state, self.error, self.reason, self.remote = "RUNNING", None, None, False
            self.event()
        elif command == "X":
            if self.state in {"SUCCEEDED", "FAILED", "CANCELLED", "CANCEL_REQUESTED"}:
                return None
            if self.state == "BLOCKED" and self.reason == "REMOTE_UNKNOWN":
                if self.cancelled:
                    return None
            else:
                self.state = "CANCEL_REQUESTED" if self.state == "RUNNING" else "CANCELLED"
            self.cancelled = True
            self.fence += 1
            self.event()
        elif command == "P":
            return self.complete(count, self.attempts[-1].fence if count else 1, "out")
        elif command in {"R", "U"}:
            if self.state != "RUNNING" or self.cancelled:
                return StateConflict
            unknown = command == "U"
            self.error = "TIMEOUT" if unknown else "TEMPORARY"
            self.attempts[-1].state = "UNKNOWN" if unknown else "FAILED"
            self.attempts[-1].error = self.error
            self.state = "BLOCKED" if unknown else "BACKOFF" if count < 3 else "FAILED"
            self.reason, self.owner = "REMOTE_UNKNOWN" if unknown else None, None
            self.fence += 1
            self.event()
        elif command == "A":
            if self.reader and not exclusive:
                return StateConflict
            if exclusive:
                self.reader = False
            if self.state not in {"RUNNING", "CANCEL_REQUESTED"}:
                return None
            # Outcome priority is independent of retryability and cancellation.
            if self.remote:
                self.state, self.reason, outcome = "BLOCKED", "REMOTE_UNKNOWN", "UNKNOWN"
            elif self.cancelled:
                self.state, self.reason, outcome = "CANCELLED", None, "CANCELLED"
            elif count == 3:
                self.state, self.reason, outcome = "FAILED", None, "ABANDONED"
            else:
                self.state, self.reason, outcome = "BLOCKED", "ABANDONED", "ABANDONED"
            self.attempts[-1].state = outcome
            self.owner = None
            self.fence += 1
            self.event()
        else:
            raise AssertionError(f"unknown test command: {command}")
        return None


TABLES = (
    "jobs",
    "attempts",
    "events",
    "job_create_receipts",
    "job_sessions",
    "job_local_readers",
    "job_remote_intents",
)


def sql_snapshot(store: JobStore) -> tuple[tuple[tuple[object, ...], ...], ...]:
    return tuple(
        tuple(tuple(row) for row in store._db.execute(f"SELECT * FROM {table} ORDER BY rowid"))
        for table in TABLES
    )


def check(store: JobStore, model: Oracle, tokens: list[AttemptRecord], context: str) -> None:
    job = store.get("job")
    actual = (
        job.state.value,
        job.fence,
        job.state_version,
        job.cancel_requested,
        job.owner,
        job.result_ref,
        job.error_code,
        job.blocked_reason,
        job.attempt_count,
        job.attempt_id,
    )
    expected = (
        model.state,
        model.fence,
        model.version,
        model.cancelled,
        model.owner,
        model.result,
        model.error,
        model.reason,
        len(model.attempts),
        tokens[-1].attempt_id if tokens else None,
    )
    assert actual == expected, (
        f"{context}: job state/fence/version/outcome mismatch: {actual!r} != {expected!r}"
    )
    assert len(tokens) == len(model.attempts)
    assert len({token.attempt_id for token in tokens}) == len(tokens), context
    rows = store._db.execute("SELECT * FROM attempts ORDER BY attempt_no").fetchall()
    actual_attempts = [
        tuple(
            row[key]
            for key in ("attempt_no", "state", "fence", "owner", "result_ref", "error_code")
        )
        for row in rows
    ]
    expected_attempts = [
        (index, item.state, item.fence, item.owner, item.result, item.error)
        for index, item in enumerate(model.attempts, 1)
    ]
    assert actual_attempts == expected_attempts, f"{context}: complete attempt history mismatch"
    assert [row["attempt_id"] for row in rows] == [token.attempt_id for token in tokens], context
    ordinal = {token.attempt_id: index for index, token in enumerate(tokens, 1)}
    events = [
        (ordinal.get(row[0], 0), row[1], row[2], row[3])
        for row in store._db.execute(
            "SELECT attempt_id,state,fence,state_version FROM events ORDER BY event_id"
        )
    ]
    assert events == model.events, f"{context}: durable event history mismatch"
    assert store.local_reader_active("job") is (model.reader if tokens else None), context


def execute(
    store: JobStore,
    model: Oracle,
    tokens: list[AttemptRecord],
    command: str,
    context: str,
    *,
    exclusive: bool = False,
    ordinal: int | None = None,
    delta: int = 0,
    result: str = "out",
) -> None:
    before, model_before = sql_snapshot(store), repr(model)
    state_before = model.state
    token = tokens[-1] if tokens else None
    if ordinal is not None:
        token = tokens[ordinal - 1]
        error = model.complete(ordinal, token.fence + delta, result)
    else:
        error = model.command(command, exclusive=exclusive)
    caught: Exception | None = None
    try:
        if command == "C":
            tokens.append(store.claim("job", f"owner-{len(tokens) + 1}"))
        elif command == "X":
            store.cancel("job")
        elif command == "A":
            store.recover_abandoned(coordinator_exclusive=exclusive)
        else:
            identity, fence = (
                (token.attempt_id, token.fence + delta) if token else ("never-issued", 1)
            )
            if command == "P":
                store.complete("job", identity, fence, result)
            else:
                store.fail(
                    "job",
                    identity,
                    fence,
                    "TIMEOUT" if command == "U" else "TEMPORARY",
                    retryable=True,
                    outcome_known=command != "U",
                )
    except (StateConflict, ValidationError) as failure:
        caught = failure
    assert caught is None if error is None else type(caught) is error, (
        f"{context}: expected {error}, got {caught!r}"
    )
    check(store, model, tokens, context)
    if error is not None or repr(model) == model_before:
        assert sql_snapshot(store) == before, (
            f"{context}: rejected/idempotent command mutated durable tables"
        )
    EDGES[(state_before, command, model.state, "reject" if error else "accept")] += 1


def start() -> tuple[JobStore, Oracle, list[AttemptRecord]]:
    expected_root = os.environ.get("Q21_EXPECTED_SOURCE_ROOT")
    if expected_root:
        assert Path(jobs_module.__file__).resolve().is_relative_to(Path(expected_root).resolve())
    store = JobStore(Path(":memory:"))
    store.create("STT", "fixed-input", "job")
    model = Oracle()
    check(store, model, [], "create")
    return store, model, []


def observed(case_id: str) -> None:
    OBSERVED[case_id] += 1
    assert OBSERVED[case_id] == 1, f"duplicate execution: {case_id}"


@pytest.mark.parametrize("word", WORDS, ids=lambda word: "H-" + "".join(word))
def test_job_command_words(word: tuple[str, ...]) -> None:
    store, model, tokens = start()
    case_id = "H-" + "".join(word)
    try:
        PREFIXES.add("")
        for index, command in enumerate(word, 1):
            prefix = "".join(word[:index])
            execute(store, model, tokens, command, f"{case_id} prefix={prefix}")
            PREFIXES.add(prefix)
        observed(case_id)
    finally:
        store.close()


@pytest.mark.parametrize("outcomes", DEEP, ids=lambda items: "D-" + "".join(items))
def test_retry_recovery_at_attempt_cap(outcomes: tuple[str, ...]) -> None:
    store, model, tokens = start()
    case_id = "D-" + "".join(outcomes)
    try:
        for outcome in outcomes:
            execute(store, model, tokens, "C", case_id)
            execute(store, model, tokens, outcome, case_id)
        assert model.state == "FAILED" and len(tokens) == 3
        for command in "CPXA":
            execute(store, model, tokens, command, case_id)
        observed(case_id)
    finally:
        store.close()


def fence_id(case: tuple[str, str, int, str]) -> str:
    seed, token, delta, result = case
    return f"F-{seed}-{token}-{delta:+d}-{result}"


@pytest.mark.parametrize("case", FENCES, ids=fence_id)
def test_late_token_fence_and_result_replay(case: tuple[str, str, int, str]) -> None:
    seed, token, delta, result = case
    store, model, tokens = start()
    case_id = fence_id(case)
    try:
        for command in seed:
            execute(store, model, tokens, command, case_id)
        assert len(tokens) >= 2
        execute(
            store,
            model,
            tokens,
            "P",
            case_id,
            ordinal=1 if token == "first" else len(tokens),
            delta=delta,
            result=result,
        )
        observed(case_id)
    finally:
        store.close()


def recovery_id(case: tuple[int, bool, bool, bool, bool]) -> str:
    number, marker, cancel, active, exclusive = case
    return f"K-n{number}-m{int(marker)}-c{int(cancel)}-r{int(active)}-e{int(exclusive)}"


@pytest.mark.parametrize("case", RECOVERY, ids=recovery_id)
def test_remote_recovery_decision_cube(case: tuple[int, bool, bool, bool, bool]) -> None:
    number, marker, cancel, active, exclusive = case
    store, model, tokens = start()
    case_id = recovery_id(case)
    try:
        for _ in range(number - 1):
            execute(store, model, tokens, "C", case_id)
            execute(store, model, tokens, "R", case_id)
        execute(store, model, tokens, "C", case_id)
        attempt = tokens[-1]
        if active:
            store.reader_started(attempt)
            model.reader = True
        if marker:
            store.mark_remote_intent(attempt, "fixed-reservation")
            model.remote = True
        if cancel:
            execute(store, model, tokens, "X", case_id)
        check(store, model, tokens, case_id)
        execute(store, model, tokens, "A", case_id, exclusive=exclusive)
        if active and not exclusive:
            # An inactive-reader attestation is not manufactured to allow recovery.
            assert model.state in {"RUNNING", "CANCEL_REQUESTED"}
        elif marker:
            assert model.state == "BLOCKED" and model.reason == "REMOTE_UNKNOWN"
            before = sql_snapshot(store)
            with pytest.raises(StateConflict):
                store.resume("job")
            assert sql_snapshot(store) == before
            execute(store, model, tokens, "C", case_id)
            execute(store, model, tokens, "P", case_id)
        observed(case_id)
    finally:
        store.close()


def test_executed_case_census_has_no_missing_or_duplicate_ids() -> None:
    """Rank decoding is independent of itertools.product and runtime outcomes."""
    expected: set[str] = set()
    assert set(ALPHABET) == {"C", "X", "P", "R", "U", "A"} and len(ALPHABET) == 6
    for rank in range(1296):
        value, word = rank, ""
        for _ in range(4):
            value, digit = divmod(value, 6)
            word = "CXPRUA"[digit] + word
        expected.add("H-" + word)
    for rank in range(8):
        expected.add("D-" + "".join("A" if rank & (1 << bit) else "R" for bit in (2, 1, 0)))
    for rank in range(96):
        value, output = divmod(rank, 2)
        value, fence = divmod(value, 3)
        seed, token = divmod(value, 2)
        expected.add(
            fence_id((SEEDS[seed], ("first", "latest")[token], fence - 1, ("out", "other")[output]))
        )
    for rank in range(32):
        expected.add(
            recovery_id(
                (
                    3 if rank & 16 else 1,
                    bool(rank & 8),
                    bool(rank & 4),
                    bool(rank & 2),
                    bool(rank & 1),
                )
            )
        )
    assert len(expected) == 1432
    assert set(OBSERVED) == expected, (
        f"missing={sorted(expected - OBSERVED.keys())}; extra={sorted(OBSERVED.keys() - expected)}"
    )
    assert set(OBSERVED.values()) == {1}
    assert len(PREFIXES) == (6**5 - 1) // 5 == 1555
    assert len({word[:length] for word in PREFIXES for length in range(len(word) + 1)}) == 1555
    counts = {space: sum(case.startswith(space + "-") for case in OBSERVED) for space in "HDFK"}
    assert counts == {"H": 1296, "D": 8, "F": 96, "K": 32}
    print(
        "Q21_CASE_AUDIT="
        + json.dumps(
            {
                "executed_unique": counts,
                "missing": 0,
                "duplicates": 0,
                "H_unique_prefixes": len(PREFIXES),
                "observed_edge_classes": len(EDGES),
            },
            sort_keys=True,
        )
    )
