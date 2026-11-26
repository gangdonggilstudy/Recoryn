"""GS05 real ledger/gateway/provider/Job boundaries with fake vault and transport."""

from __future__ import annotations

import json
import threading
import wave
from collections.abc import Callable, Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, replace
from itertools import product
from pathlib import Path
from typing import Any

import pytest

from recoryn.security import ConsentStore, CostLedger, SecurityError
from recoryn.security.credentials import CredentialEvent, CredentialLease
from tests.property.test_secret_lifetime_case_space import execution_audit as execution_audit
from tests.unit.test_cost_cap import fixture_reservation, fixture_wire
from tests.unit.test_secret_lifetime import (
    K_B,
    World,
    key_command,
    secret_world,
)

pytestmark = pytest.mark.integration

_CLOSED_STORES: tuple[tuple[str, bytes], ...] = ()
_TEMPLATE_EXECUTION = ""


@pytest.fixture(scope="module", autouse=True)
def closed_empty_stores(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """Amortize schema DDL only; every row opens its own real closed-file clone."""
    global _CLOSED_STORES, _TEMPLATE_EXECUTION
    source = tmp_path_factory.mktemp("gs05-empty-stores")
    with ConsentStore(source / "policy.db", clock=lambda: 1000) as policy:
        _TEMPLATE_EXECUTION = policy.execution_id
        assert policy._db.execute("SELECT COUNT(*) FROM security_grants_v2").fetchone()[0] == 0
    with CostLedger(source / "cost.db", clock=lambda: 1000) as ledger:
        witness = ledger._witness
        assert (
            ledger._db.execute("SELECT COUNT(*) FROM security_cost_requests_v2").fetchone()[0] == 0
        )
    assert not (source / "policy.db-wal").exists() and not (source / "cost.db-wal").exists()
    files = (source / "policy.db", source / "cost.db", witness)
    _CLOSED_STORES = tuple((path.name, path.read_bytes()) for path in files)
    try:
        yield
    finally:
        _CLOSED_STORES = ()
        _TEMPLATE_EXECUTION = ""


class WireConnection:
    def __init__(self, owner: Wire, headers: Mapping[str, str]) -> None:
        self.owner, self._headers = owner, dict(headers)
        self.output = owner.response
        self.started = False
        self.closed = False

    def write(self, data: bytes, timeout: float) -> None:
        try:
            if not self.started:
                self.owner.headers += 1
                self.owner.wire_auth.append(dict(self._headers))
                self.started = True
                self.owner.on_header()
            if data:
                self.owner.writes.append(data[:1] if self.owner.partial else data)
            self.owner.on_write()
            if self.owner.partial:
                raise OSError("GS05-PRIVATE-PARTIAL-CANARY")
        finally:
            self._headers.clear()

    def read(self, limit: int, timeout: float) -> bytes:
        self.owner.on_read()
        part, self.output = self.output[:limit], self.output[limit:]
        if not part:
            self.owner.eof = True
        return part

    def close(self) -> None:
        self.closed = True
        self._headers.clear()
        if self.owner.close_error:
            raise OSError("GS05-PRIVATE-CLOSE-CANARY")


class Wire:
    def __init__(self) -> None:
        self.dns = self.opens = self.headers = 0
        self.writes: list[bytes] = []
        self.wire_auth: list[dict[str, str]] = []
        self.connections: list[WireConnection] = []
        self.gateway_headers: Mapping[str, str] = {}
        self.response = b"{}"
        self.eof = self.partial = self.close_error = False
        self.on_header: Callable[[], None] = lambda: None
        self.on_write: Callable[[], None] = lambda: None
        self.on_read: Callable[[], None] = lambda: None

    def open(
        self, target: Any, headers: Mapping[str, str], size: int, timeout: float
    ) -> WireConnection:
        self.dns += 1
        self.opens += 1
        self.gateway_headers = headers
        connection = WireConnection(self, headers)
        self.connections.append(connection)
        return connection


@dataclass
class LedgerWorld:
    base: World
    ledger: CostLedger
    request: Any
    reservation: str
    wire: Wire

    def send(self, **kwargs: Any) -> bytes:
        provider, _, data, target = self.base.route
        return self.base.gateway.request(
            provider,
            target,
            data,
            self.request.body,
            reservation_id=self.reservation,
            **kwargs,
        )

    def balance(self) -> dict[str, int]:
        return self.ledger.account_snapshot(self.base.route[0], "USD", 0, 4_102_444_800)

    def row(self) -> Any:
        return self.ledger._request(self.reservation)


@contextmanager
def ledger_world(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    route: int = 0,
    hook: Callable[[CredentialEvent], None] | None = None,
    *,
    initialize: bool = True,
) -> Iterator[LedgerWorld]:
    for name, content in _CLOSED_STORES:
        target = tmp_path / name
        assert not target.exists(), "each semantic row must own a fresh DB/witness clone"
        target.write_bytes(content)
    with ConsentStore(tmp_path / "policy.db", clock=lambda: 1000) as policy:
        assert policy.execution_id != _TEMPLATE_EXECUTION
        with secret_world(policy, route, hook) as base:
            with CostLedger(
                tmp_path / "cost.db", clock=lambda: 1000, monotonic=base.clock
            ) as ledger:
                provider, kind, data, endpoint = base.route
                request = fixture_wire(
                    provider, endpoint, data, b"abcdef", operation=kind, model="fixture"
                )
                reservation = (
                    fixture_reservation(ledger, monkeypatch, request, 80, 100, "wire")
                    if initialize
                    else ""
                )
                base.gateway.ledger = ledger
                wire = Wire()
                base.gateway.transport = wire
                yield LedgerWorld(base, ledger, request, reservation, wire)


def track_leases(monkeypatch: pytest.MonkeyPatch) -> list[CredentialLease]:
    leases: list[CredentialLease] = []
    original = CredentialLease._bind

    def bind(lease: CredentialLease, *args: Any) -> None:
        leases.append(lease)
        original(lease, *args)

    monkeypatch.setattr(CredentialLease, "_bind", bind)
    return leases


def assert_released(leases: list[CredentialLease]) -> None:
    assert all(
        lease.released and lease._secret is None and lease._headers == {} for lease in leases
    )


B_CASES = [
    pytest.param(f"GS05-B-{route}-{value}", route, value, id=f"GS05-B-{route}-{value}")
    for route, value in product(range(5), range(8))
]


@pytest.mark.parametrize("case_id,route,value", B_CASES)
def test_read_results(
    case_id: str,
    route: int,
    value: int,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    leases = track_leases(monkeypatch)
    with ledger_world(tmp_path, monkeypatch, route) as world:
        base = world.base
        key = base.vault._target(base.auth.ref.target.vault_key)
        if value == 1:
            base.backend.values.pop(key)
        elif value in (2, 3, 4, 5):
            base.backend.values[key] = {2: b"", 3: b"nul\0value", 4: b"x" * 2561, 5: b"\xff"}[value]
        elif value == 6:
            base.backend.error = OSError("GS05-PRIVATE-BACKEND-CANARY")
        elif value == 7:
            base.backend.reading = lambda: setattr(base.clock, "value", 1031)
        before = world.ledger._witness.read_bytes()
        if value:
            code = (
                "AUTH_REQUIRED" if value == 1 else "TIMEOUT" if value == 7 else "VAULT_READ_FAILED"
            )
            with pytest.raises(SecurityError, match="^" + code + "$") as failure:
                world.send()
            assert failure.value.outcome_known and not failure.value.retryable
            assert world.wire.dns == world.wire.opens == world.wire.headers == 0
            assert world.wire.writes == []
            assert (world.row()["state"], world.row()["dispatch_id"]) == ("RESERVED", None)
            assert world.balance()["reserved"] == 80 and world.balance()["unknown_exposure"] == 0
            assert world.ledger._witness.read_bytes() == before
            assert "CANARY" not in str(failure.value)
        else:
            assert world.send() == b"{}"
            assert world.wire.opens == world.wire.headers == 1
            assert world.wire.writes == [b"abc", b"def"]
            assert world.balance()["unknown_exposure"] == 80
        assert base.backend.reads == 1, case_id
        assert_released(leases)


def auth_pipeline(
    world: LedgerWorld, route: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Any, Any, list[Any]]:
    from recoryn.jobs import JobStore
    from recoryn.jobs.runner import BoundedRunner
    from recoryn.providers import (
        ExecutionContext,
        ProviderConfig,
        ProviderError,
        STTRequest,
        SummaryRequest,
        TranscriptSegment,
    )
    from recoryn.summarization import AnthropicSummarizer, GeminiSummarizer, OpenAISummarizer
    from recoryn.transcription import GeminiTranscriber, OpenAITranscriber

    base = world.base
    provider, kind, data_type, endpoint = base.route
    config = ProviderConfig(provider, "fixture", endpoint=endpoint, context_window_tokens=100_000)
    if route == 4:
        config = replace(config, context_window_tokens=8192)
    claims = (
        '{"claims":[{"text":"x","segment_ids":["s0"]}]}'
        if route == 4
        else '{"claims":[{"text":"x","segment_ids":["s"]}]}'
    )
    replies = (
        {"text": "hello"},
        {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "hello"}]}}]},
        {
            "status": "completed",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": claims}]}],
        },
        {"stop_reason": "end_turn", "content": [{"type": "text", "text": claims}]},
        {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": claims}]}}]},
    )
    world.wire.response = json.dumps(replies[route]).encode()
    # Larger chunks keep this pipeline test about AUTH; C/L own the two-body oracle.
    base.gateway.chunk_bytes = 1_000_000
    audio = tmp_path / "synthetic.wav"
    with wave.open(str(audio), "wb") as wav:
        wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        wav.writeframes(b"\x00\x00" * 160)
    original_audio = audio.read_bytes()
    summary_request = SummaryRequest(
        "GS05-synthetic-revision", (TranscriptSegment("s", 0, 1000, "synthetic"),)
    )
    if route == 4:
        # Build a real, validated checkpoint using a separate toy Gateway.
        # Its three synthetic cores are fixture INPUT, not an expected oracle.
        # The observed vault/ledger/transport see only the one context request.
        seed_request = SummaryRequest(
            "GS05-synthetic-revision",
            tuple(
                TranscriptSegment(f"s{index}", index * 1000, (index + 1) * 1000, "z" * 800)
                for index in range(6)
            ),
            overlap_segments=0,
        )

        class CheckpointGateway:
            def __init__(self) -> None:
                self.core_calls = self.context_calls = 0

            def request(
                self, provider: str, target: str, data: str, body: bytes, **kwargs: Any
            ) -> bytes:
                assert (provider, target) == ("gemini", endpoint)
                if data == "context":
                    self.context_calls += 1
                    raise SecurityError("CONSENT_REQUIRED")
                assert data == "transcript"
                # Toy response generation is separate from the hand AUTH/job oracle.
                envelope = json.loads(body)
                prompt = json.loads(envelope["contents"][0]["parts"][0]["text"])
                ref = prompt["core"][0]["segment_id"]
                self.core_calls += 1
                text = json.dumps({"claims": [{"text": "seed", "segment_ids": [ref]}]})
                return json.dumps(
                    {
                        "candidates": [
                            {"finishReason": "STOP", "content": {"parts": [{"text": text}]}}
                        ]
                    }
                ).encode()

        seed_gateway = CheckpointGateway()
        seed_result = GeminiSummarizer(seed_gateway, config).summarize(seed_request)
        assert (seed_gateway.core_calls, seed_gateway.context_calls) == (3, 1), seed_result
        assert seed_result.error_code == "CONSENT_REQUIRED" and not seed_result.complete
        assert sorted(
            [(span.segment_id, span.start_char, span.end_char) for span in seed_result.coverage]
        ) == [
            (f"s{index}", start, end)
            for index in range(6)
            for start, end in ((0, 213), (213, 426), (426, 639), (639, 800))
        ]
        assert (
            len(seed_result.checkpoint.completed) == 3
            and base.backend.reads == world.wire.opens == 0
        )
        summary_request = replace(seed_request, checkpoint=seed_result.checkpoint)
    observed: list[Any] = []
    jobs = JobStore(tmp_path / "jobs.db")
    job = jobs.create(kind, "GS05-synthetic-input")
    jobs.bind_session(job.job_id, base.request.session_id)
    runner = BoundedRunner(jobs, workers=1, capacity=1)

    def task(attempt: Any, cancel: threading.Event) -> str:
        assert jobs.local_reader_active(job.job_id) is True

        def reserve_request(request: Any) -> str:
            assert request.data_type == data_type
            world.request = request
            world.reservation = fixture_reservation(
                world.ledger, monkeypatch, request, 80, 100, "pipeline"
            )
            jobs.mark_remote_intent(attempt, world.reservation)
            return world.reservation

        context = ExecutionContext(cancel=cancel, reservation_factory=reserve_request)
        try:
            if route < 2:
                adapter = (OpenAITranscriber, GeminiTranscriber)[route](base.gateway, config)
                result = adapter.transcribe(STTRequest(audio), context)
                observed.append(result)
                if result.error_code:
                    raise ProviderError(result.error_code, outcome_known=result.outcome_known)
                assert result.complete and result.segments[0].text == "hello"
            else:
                adapter = (OpenAISummarizer, AnthropicSummarizer, GeminiSummarizer)[route - 2](
                    base.gateway, config
                )
                result = adapter.summarize(summary_request, context)
                observed.append(result)
                if result.error_code:
                    raise ProviderError(result.error_code, outcome_known=result.outcome_known)
                assert result.complete
                assert [(claim.text, claim.segment_ids) for claim in result.claims] == [
                    ("x", ("s0",) if route == 4 else ("s",))
                ]
        except ProviderError as error:
            observed.append(error)
            raise
        return "GS05-safe-result"

    try:
        runner.start()
        assert runner.submit(job.job_id, task)
        with runner._condition:
            assert runner._condition.wait_for(lambda: not runner._active and not runner._queue, 3)
        final = jobs.get(job.job_id)
        attempt_row = jobs._db.execute(
            "SELECT state,error_code FROM attempts WHERE job_id=?", (job.job_id,)
        ).fetchall()
        assert len(attempt_row) == 1 and final.attempt_count == 1
        assert jobs.local_reader_active(job.job_id) is False
        assert runner.snapshot()["reader_ack_error"] is None
        assert audio.read_bytes() == original_audio
        return final, tuple(attempt_row[0]), observed
    finally:
        runner.stop()
        assert not runner.running
        jobs.close()


P_CASES = [
    pytest.param(f"GS05-P-{route}-{outcome}", route, outcome, id=f"GS05-P-{route}-{outcome}")
    for route, outcome in product(range(5), range(9))
]


@pytest.mark.parametrize("case_id,route,outcome", P_CASES)
def test_auth_pipeline(
    case_id: str, route: int, outcome: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from recoryn.security.credentials import AuthBinding

    leases = track_leases(monkeypatch)
    with ledger_world(tmp_path, monkeypatch, route, initialize=False) as world:
        base = world.base
        key = base.vault._target(base.auth.ref.target.vault_key)
        if outcome == 1:
            base.backend.values.pop(key)
        elif outcome == 2:
            base.gateway.auth_binding = AuthBinding(
                replace(base.auth.ref, epoch=999), base.credentials, base.auth.plan
            )
        elif outcome == 3:
            base.backend.error = SecurityError("VAULT_UNAVAILABLE")
        elif outcome in (4, 5, 6, 7):
            base.backend.values[key] = {4: b"", 5: b"nul\0key", 6: b"x" * 2561, 7: b"\xff"}[outcome]
        elif outcome == 8:
            base.backend.error = OSError("GS05-PRIVATE-PIPELINE-CANARY")
        final, attempt, observed = auth_pipeline(world, route, tmp_path, monkeypatch)
        if outcome:
            code = (
                "AUTH_REQUIRED"
                if outcome in (1, 2)
                else "VAULT_UNAVAILABLE"
                if outcome == 3
                else "VAULT_READ_FAILED"
            )
            assert (str(final.state), final.blocked_reason, final.error_code) == (
                "BLOCKED",
                "AUTH",
                code,
            ), case_id
            assert attempt == ("FAILED", code)
            error = observed[-1]
            assert error.code == code and error.outcome_known and not error.retryable
            assert observed[0].error_code == code and observed[0].outcome_known
            assert world.wire.dns == world.wire.opens == world.wire.headers == 0
            assert world.wire.writes == []
            assert world.balance()["reserved"] == 80 and world.balance()["unknown_exposure"] == 0
            assert (world.row()["state"], world.row()["dispatch_id"]) == ("RESERVED", None)
            assert "CANARY" not in str(error)
        else:
            assert str(final.state) == "SUCCEEDED" and attempt == ("SUCCEEDED", None)
            expected = (
                {"authorization": "Bearer GS05-FAKE-CANARY-A"},
                {"x-goog-api-key": "GS05-FAKE-CANARY-A"},
                {"authorization": "Bearer GS05-FAKE-CANARY-A"},
                {"x-api-key": "GS05-FAKE-CANARY-A"},
                {"x-goog-api-key": "GS05-FAKE-CANARY-A"},
            )[route]
            actual = {
                name: value
                for name, value in world.wire.wire_auth[0].items()
                if name in ("authorization", "x-api-key", "x-goog-api-key")
            }
            assert actual == expected
            assert world.wire.opens == world.wire.headers == 1
        assert base.backend.reads == (0 if outcome == 2 else 1)
        assert_released(leases)


Q_CASES = [
    pytest.param(
        f"GS05-Q-{route}-{boundary}-{code}",
        route,
        boundary,
        code,
        id=f"GS05-Q-{route}-{boundary}-{code}",
    )
    for route, boundary, code in product(range(5), range(2), range(2))
]


@pytest.mark.parametrize("case_id,route,boundary,code", Q_CASES)
def test_post_handoff(
    case_id: str,
    route: int,
    boundary: int,
    code: int,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    leases = track_leases(monkeypatch)
    with ledger_world(tmp_path, monkeypatch, route, initialize=False) as world:

        def auth_shaped_fault() -> None:
            raise SecurityError(("AUTH_REQUIRED", "VAULT_READ_FAILED")[code])

        if boundary == 0:
            world.wire.on_header = auth_shaped_fault
        else:
            world.wire.partial = True
            world.wire.on_write = auth_shaped_fault
        final, attempt, observed = auth_pipeline(world, route, tmp_path, monkeypatch)
        assert (str(final.state), final.blocked_reason, final.error_code) == (
            "BLOCKED",
            "REMOTE_UNKNOWN",
            "REMOTE_OUTCOME_UNKNOWN",
        ), case_id
        assert attempt == ("UNKNOWN", "REMOTE_OUTCOME_UNKNOWN")
        error = observed[-1]
        assert (
            error.code == "REMOTE_OUTCOME_UNKNOWN"
            and not error.outcome_known
            and not error.retryable
        )
        assert observed[0].error_code == "REMOTE_OUTCOME_UNKNOWN" and not observed[0].outcome_known
        assert world.base.backend.reads == world.wire.opens == world.wire.headers == 1
        assert len(world.wire.writes) == boundary
        if boundary:
            assert len(world.wire.writes[0]) == 1
        assert world.row()["state"] == "UNKNOWN"
        assert world.balance()["unknown_exposure"] == 80 and world.balance()["reserved"] == 0
        assert_released(leases)
        assert not world.base.credentials._tickets and not world.ledger._dispatches


K_CASES = [
    pytest.param(
        f"GS05-K-{route}-{cut}-{changed}", route, cut, changed, id=f"GS05-K-{route}-{cut}-{changed}"
    )
    for route, cut, changed in product(range(5), range(5), range(2))
]


@pytest.mark.parametrize("case_id,route,cut,changed", K_CASES)
def test_catalog_gate_orders(
    case_id: str,
    route: int,
    cut: int,
    changed: int,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from recoryn.security import cost_catalog

    events: list[str] = []
    leases = track_leases(monkeypatch)
    with ledger_world(tmp_path, monkeypatch, route) as world:
        original_catalog = cost_catalog.load_catalog()
        replacement = type(original_catalog)(
            tuple(replace(entry, review_id="GS05-C1-REVIEW") for entry in original_catalog.entries)
        )
        assert original_catalog.sha256 != replacement.sha256
        switched = False

        def switch() -> None:
            nonlocal switched
            assert not getattr(world.base.policy.coordinator._local, "depth", 0)
            assert not getattr(world.ledger.coordinator._local, "depth", 0)
            monkeypatch.setattr(cost_catalog, "load_catalog", lambda: replacement)
            switched = True

        def hook(event: CredentialEvent) -> None:
            events.append(event.stage)
            stage = {0: "i_enter", 1: "i_released", 3: "r_released", 4: "write_released"}.get(cut)
            if changed and not switched and event.stage == stage:
                switch()

        world.base.credentials._hook = hook
        if changed and cut == 2:
            world.base.backend.reading = switch
        witness = world.ledger._witness.read_bytes()
        if changed and cut < 4:
            with pytest.raises(SecurityError, match="^COST_QUOTE_MISMATCH$") as failure:
                world.send()
            assert failure.value.outcome_known and not failure.value.retryable
            assert world.wire.dns == world.wire.opens == world.wire.headers == 0
            assert world.wire.writes == []
            assert (world.row()["state"], world.row()["dispatch_id"]) == ("RESERVED", None)
            assert world.balance()["reserved"] == 80 and world.balance()["unknown_exposure"] == 0
            assert world.ledger._witness.read_bytes() == witness
            assert world.base.backend.reads == (0 if cut < 2 else 1)
            if cut == 2:
                assert "r_released" not in events and "o_enter" not in events
            elif cut == 3:
                assert "r_released" in events and "o_enter" in events
        else:
            assert world.send() == b"{}"
            assert world.wire.opens == world.wire.headers == 1
            assert world.wire.writes == [b"abc", b"def"]
            assert world.row()["state"] == "UNKNOWN"
            assert world.balance()["unknown_exposure"] == 80
            assert world.base.backend.reads == 1
        assert_released(leases)
        assert not world.ledger._dispatches, case_id


L_CASES = [
    pytest.param(f"GS05-L-{route}-{wait}", route, wait, id=f"GS05-L-{route}-{wait}")
    for route, wait in product(range(5), range(2))
]


@pytest.mark.parametrize("case_id,route,wait", L_CASES)
def test_first_write_release(
    case_id: str,
    route: int,
    wait: int,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    leases = track_leases(monkeypatch)
    paused, release = threading.Event(), threading.Event()
    with ledger_world(tmp_path, monkeypatch, route) as world:

        def pause() -> None:
            if paused.is_set():
                return
            assert not getattr(world.base.policy.coordinator._local, "depth", 0)
            assert not getattr(world.ledger.coordinator._local, "depth", 0)
            paused.set()
            assert release.wait(3)

        if wait:
            world.wire.on_read = pause
        else:
            world.base.credentials._hook = lambda event: (
                pause() if event.stage == "write_released" else None
            )
        with ThreadPoolExecutor(max_workers=1) as pool:
            task = pool.submit(world.send)
            try:
                assert paused.wait(3)
                assert not task.done()
                assert len(leases) == 1 and leases[0].released, case_id
                assert_released(leases)
                assert not any(
                    name in world.wire.gateway_headers
                    for name in ("authorization", "x-api-key", "x-goog-api-key")
                )
                assert world.wire.connections[0]._headers == {}
                assert not world.wire.connections[0].closed
            finally:
                release.set()
                assert task.result(3) == b"{}"


C_CASES = [
    pytest.param(f"GS05-C2-{cause}-{cut}", cause, cut, id=f"GS05-C2-{cause}-{cut}")
    for cause, cut in product(range(6), range(6))
]


@pytest.mark.parametrize("case_id,cause,cut", C_CASES)
def test_read_orders_b(
    case_id: str, cause: int, cut: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    leases = track_leases(monkeypatch)
    with ledger_world(tmp_path, monkeypatch) as world:
        base = world.base
        cancel, entered, release = threading.Event(), threading.Event(), threading.Event()
        events: list[str] = []
        committed = False
        held_at_read: list[int] = []

        def invalidate() -> None:
            nonlocal committed
            assert not getattr(base.policy.coordinator._local, "depth", 0)
            assert not getattr(world.ledger.coordinator._local, "depth", 0)
            if cause == 0:
                base.policy.revoke_endpoint(base.route[0], base.route[3])
            elif cause == 1:
                cancel.set()
            elif cause in (2, 3):
                done, results = key_command(base, "save" if cause == 2 else "delete")
                assert done.wait(3) and results[0].error_code is None
            elif cause == 4:
                base.policy.revoke_session(base.request.session_id)
            else:
                base.clock.value = 1031
            committed = True

        stage = {
            0: "i_enter",
            1: "i_released",
            2: "u_released",
            4: "o_released",
            5: "write_released",
        }.get(cut)

        def hook(event: CredentialEvent) -> None:
            events.append(event.stage)
            if event.stage == stage and not committed:
                invalidate()

        base.credentials._hook = hook
        if cut == 3:

            def blocked_read() -> None:
                held_at_read.extend(
                    [
                        getattr(base.policy.coordinator._local, "depth", 0),
                        getattr(world.ledger.coordinator._local, "depth", 0),
                    ]
                )
                entered.set()
                assert release.wait(3)

            base.backend.reading = blocked_read
        code = (
            "CONSENT_REQUIRED",
            "CANCELLED",
            "CONSENT_REQUIRED",
            "CONSENT_REQUIRED",
            "SESSION_REVOKED",
            "TIMEOUT",
        )[cause]
        if cut == 5 and cause in (1, 5):
            code = "REMOTE_OUTCOME_UNKNOWN"
        with ThreadPoolExecutor(max_workers=1) as pool:
            task = pool.submit(world.send, cancel=cancel)
            try:
                if cut == 3:
                    assert entered.wait(3)
                    assert held_at_read == [0, 0], "native R held a common coordinator"
                    invalidate()
                    assert committed and not task.done(), "Q commit must precede native ACK"
            finally:
                release.set()
            with pytest.raises(SecurityError, match="^" + code + "$") as failure:
                task.result(3)
        assert committed, case_id
        assert failure.value.outcome_known is (cut < 5)
        assert not failure.value.retryable
        assert base.backend.reads == (0 if cut < 2 else 1)
        assert world.wire.opens == world.wire.dns == (1 if cut >= 4 else 0)
        assert world.wire.headers == (1 if cut == 5 else 0)
        assert world.wire.writes == ([b"abc"] if cut == 5 else [])
        assert world.row()["state"] == ("UNKNOWN" if cut == 5 else "RESERVED")
        assert world.balance()["unknown_exposure"] == (80 if cut == 5 else 0)
        if cut in (2, 3):
            assert "r_released" not in events and "o_enter" not in events
        assert_released(leases)
        assert not base.credentials._tickets and not world.ledger._dispatches


D_CASES = [
    pytest.param(f"GS05-D-{route}-{fault}", route, fault, id=f"GS05-D-{route}-{fault}")
    for route, fault in product(range(5), range(9))
]


def assert_stdlib_header_cleanup(monkeypatch: pytest.MonkeyPatch, route: int) -> None:
    from recoryn.security import transport
    from recoryn.security._core import endpoint

    class Socket:
        def settimeout(self, timeout: float) -> None:
            pass

        def close(self) -> None:
            pass

    class TLS:
        def wrap_socket(self, raw: Any, **kwargs: Any) -> Any:
            return raw

    # Actual stdlib HTTPConnection.putrequest/putheader queues the bytes. The
    # endheaders fault is before any socket send; the socket itself is fake.
    auth = (
        {"authorization": "Bearer GS05-FAKE-CANARY-A"},
        {"x-goog-api-key": "GS05-FAKE-CANARY-A"},
        {"authorization": "Bearer GS05-FAKE-CANARY-A"},
        {"x-api-key": "GS05-FAKE-CANARY-A"},
        {"x-goog-api-key": "GS05-FAKE-CANARY-A"},
    )[route]
    with monkeypatch.context() as patch:
        patch.setattr(transport, "_socket", lambda *args: Socket())
        patch.setattr(transport.ssl, "create_default_context", lambda: TLS())
        connection = transport.DirectTransport().open(
            endpoint("https://headers.gs05.invalid/v1"), auth, 1, 1
        )
        before: list[bytes] = []

        def fail_headers() -> None:
            before.extend(connection._client._buffer)
            assert any(b"GS05-FAKE-CANARY-A" in part for part in before)
            raise OSError("GS05-header-before-send")

        patch.setattr(connection._client, "endheaders", fail_headers)
        try:
            with pytest.raises(OSError, match="GS05-header-before-send"):
                connection.write(b"x", 1)
            assert before and connection._client._buffer == [], (
                "stdlib pending authentication buffer survived first write failure"
            )
            assert not any(name in connection._headers for name in auth)
        finally:
            connection.close()


@pytest.mark.parametrize("case_id,route,fault", D_CASES)
def test_fault_cleanup(
    case_id: str, route: int, fault: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    leases = track_leases(monkeypatch)
    with ledger_world(tmp_path, monkeypatch, route) as world:
        base = world.base
        if fault == 0:

            def refuse(*args: Any, **kwargs: Any) -> None:
                raise SecurityError("AUTH_REQUIRED")

            monkeypatch.setattr(base.credentials, "issue_ticket", refuse)
        elif fault == 1:
            bind = CredentialLease._bind

            def broken_bind(lease: CredentialLease, *args: Any) -> None:
                bind(lease, *args)
                raise RuntimeError("GS05-PRIVATE-LEASE-CANARY")

            monkeypatch.setattr(CredentialLease, "_bind", broken_bind)

        @contextmanager
        def guard(*args: Any, **kwargs: Any) -> Iterator[None]:
            if (fault == 2 and not world.wire.opens) or (fault == 8 and world.wire.eof):
                raise SecurityError("LOCAL_EXECUTION_CHANGED")
            yield
            if fault == 3 and world.wire.opens and not world.wire.headers:
                raise SecurityError("LOCAL_EXECUTION_CHANGED")

        base.gateway.dispatch_guard = guard

        def io_failure() -> None:
            raise OSError("GS05-PRIVATE-IO-CANARY")

        if fault == 4:
            world.wire.on_header = io_failure
        elif fault == 5:
            world.wire.partial = True
        elif fault == 6:
            world.wire.on_read = io_failure
        elif fault == 7:
            world.wire.close_error = True
        if fault == 7:
            assert world.send() == b"{}"
        else:
            with pytest.raises(SecurityError) as failure:
                world.send()
            assert failure.value.outcome_known is (fault < 4)
            assert "CANARY" not in str(failure.value)
        # Literal R/O/H/body observations; no product enum/parser generates these.
        expected = (
            (0, 0, 0, []),
            (1, 0, 0, []),
            (1, 0, 0, []),
            (1, 1, 0, []),
            (1, 1, 1, []),
            (1, 1, 1, [b"a"]),
            (1, 1, 1, [b"abc", b"def"]),
            (1, 1, 1, [b"abc", b"def"]),
            (1, 1, 1, [b"abc", b"def"]),
        )[fault]
        assert (
            base.backend.reads,
            world.wire.opens,
            world.wire.headers,
            world.wire.writes,
        ) == expected, case_id
        assert world.wire.dns == expected[1]
        assert world.balance()["unknown_exposure"] == (80 if fault >= 4 else 0)
        assert_released(leases)
        assert all(
            connection.closed and connection._headers == {} for connection in world.wire.connections
        )
        assert not base.credentials._tickets and not world.ledger._dispatches

        if fault == 4:
            assert_stdlib_header_cleanup(monkeypatch, route)


@pytest.mark.parametrize(
    "case_id,row",
    [pytest.param(f"GS05-T-{row:02}", row, id=f"GS05-T-{row:02}") for row in (12, 16, 18, 19)],
)
def test_key_concurrency(
    case_id: str, row: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from recoryn.security.credentials import CredentialService, CredentialTarget

    leases = track_leases(monkeypatch)
    with ledger_world(tmp_path, monkeypatch) as world:
        base = world.base
        if row == 16:

            def revoke_after_b2(event: CredentialEvent) -> None:
                if event.stage == "write_released" and len(world.wire.writes) == 2:
                    base.policy.revoke_endpoint(base.route[0], base.route[3])

            base.credentials._hook = revoke_after_b2
            with pytest.raises(SecurityError, match="^CONSENT_REQUIRED$") as failure:
                world.send()
            assert not failure.value.outcome_known
            assert world.wire.writes == [b"abc", b"def"]
            assert world.balance()["unknown_exposure"] == 80
        elif row == 12:
            entered, release = threading.Event(), threading.Event()
            offered: list[str] = []
            bind = CredentialLease._bind

            def record_bind(lease: CredentialLease, secret: str, *args: Any) -> None:
                offered.append(secret)
                bind(lease, secret, *args)

            monkeypatch.setattr(CredentialLease, "_bind", record_bind)

            def read_pause() -> None:
                entered.set()
                assert release.wait(3)

            base.backend.reading = read_pause
            with ThreadPoolExecutor(max_workers=1) as pool:
                task = pool.submit(world.send)
                try:
                    assert entered.wait(3)
                    done, result = key_command(base, "save")
                    assert done.wait(3) and result[0].error_code is None
                    assert (
                        not task.done()
                        and base.backend.values[base.vault._target(base.auth.ref.target.vault_key)]
                        == K_B.encode()
                    )
                finally:
                    release.set()
                with pytest.raises(SecurityError, match="^CONSENT_REQUIRED$"):
                    task.result(3)
            assert offered == [K_B] and world.wire.opens == 0
        else:
            if row == 18:
                for limits in ({"native_workers": 5}, {"pending_limit": 9}, {"target_limit": 3}):
                    with pytest.raises(SecurityError, match="^INPUT_INVALID$"):
                        CredentialService(base.vault, consents=base.policy, **limits)
                assert base.backend.reads == 0 and base.backend.writes == []
            entered, release = threading.Event(), threading.Event()
            original = base.backend.write
            calls: list[tuple[str, bytes]] = []
            active = 0
            held_at_write: list[int] = []

            def paused_write(target: str, data: bytes) -> None:
                nonlocal active
                held_at_write.extend(
                    [
                        getattr(base.policy.coordinator._local, "depth", 0),
                        getattr(world.ledger.coordinator._local, "depth", 0),
                    ]
                )
                calls.append((target, data))
                if target == base.vault._target(base.auth.ref.target.vault_key):
                    active += 1
                    assert active == 1, "same-target native writes overlap"
                    if len(calls) == 1:
                        entered.set()
                        assert release.wait(3)
                    active -= 1
                original(target, data)

            base.backend.write = paused_write
            if row == 19:
                base.backend.write_error = True
            done, result = key_command(base, "save")
            try:
                assert entered.wait(3) and not done.is_set()
                assert held_at_write == [0, 0], "native write held a common coordinator"
                assert base.credentials._pending == 1
                if row == 18:
                    second_done, second = key_command(base, "save", "GS05-FAKE-FIFO-LAST")
                    assert not base.credentials.try_enqueue_key_change(
                        base.auth.ref.target,
                        "save",
                        "GS05-FAKE-OVERFLOW",
                        command_nonce="target-overflow",
                        selection_generation=0,
                        done=lambda reply: None,
                    )
                    other = CredentialTarget(
                        "openai", "https://other.gs05.invalid/v1/audio/transcriptions"
                    )
                    other_done = threading.Event()
                    assert base.credentials.try_enqueue_key_change(
                        other,
                        "save",
                        K_B,
                        command_nonce="other",
                        selection_generation=0,
                        done=lambda reply: other_done.set(),
                    )
                    assert other_done.wait(3), "other target must progress before first native ACK"
                    assert not done.is_set() and not second_done.is_set()
                else:
                    with pytest.raises(SecurityError, match="^CONSENT_REQUIRED$"):
                        world.send()
                    assert base.backend.reads == world.wire.opens == 0
            finally:
                release.set()
            assert done.wait(3)
            if row == 18:
                with base.credentials._condition:
                    assert base.credentials._condition.wait_for(
                        lambda: base.credentials._pending == 0, 3
                    )
                target_calls = [
                    data
                    for target, data in calls
                    if target == base.vault._target(base.auth.ref.target.vault_key)
                ]
                assert target_calls == [K_B.encode(), b"GS05-FAKE-FIFO-LAST"]
                assert second_done.wait(3) and second[0].error_code is None
                assert (
                    base.credentials.capture_ref(base.auth.ref.target).epoch
                    == base.auth.ref.epoch + 2
                )
            else:
                assert result[0].error_code == "VAULT_WRITE_FAILED"
                assert (
                    base.credentials.capture_ref(base.auth.ref.target).epoch
                    == base.auth.ref.epoch + 1
                )
                with pytest.raises(SecurityError, match="^CONSENT_REQUIRED$"):
                    world.send()
                assert base.backend.reads == world.wire.opens == 0
        assert_released(leases)
