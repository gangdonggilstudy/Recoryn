"""BR14 independent oracles; synthetic audio and controlled transport only."""

from __future__ import annotations

import importlib
import json
import threading
import time
import wave
from collections.abc import Iterator, Mapping
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from recoryn.providers import (
    ExecutionContext,
    LocalModelAttestation,
    ProviderConfig,
    STTRequest,
    SummaryClaim,
    SummaryRequest,
    TranscriptSegment,
)
from recoryn.security import (
    ConsentRequest,
    ConsentScope,
    ConsentStore,
    CostLedger,
    CostRequest,
    Gateway,
    SecurityError,
)
from recoryn.security._core import Endpoint
from recoryn.summarization import OllamaSummarizer, OpenAISummarizer
from recoryn.transcription import FasterWhisperProvider, OpenAITranscriber
from tests.unit.test_cost_cap import fixture_balance, fixture_reservation

pytestmark = pytest.mark.integration
STT_ENDPOINT = "https://api.example.test/audio"
SUMMARY_ENDPOINT = "https://api.example.test/summary"


def summary_response(claims: list[dict[str, object]]) -> bytes:
    return json.dumps(
        {
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps({"claims": claims}),
                        }
                    ],
                }
            ],
        }
    ).encode()


def config(**kwargs: Any) -> ProviderConfig:
    return ProviderConfig(
        "openai",
        "test-model",
        endpoint=SUMMARY_ENDPOINT,
        context_window_tokens=8192,
        max_output_tokens=256,
        **kwargs,
    )


def summary_request(*, provenance: str = "audio") -> SummaryRequest:
    return SummaryRequest(
        "immutable-revision",
        (TranscriptSegment("s1", 0, 1000, "UNTRUSTED-CONTENT-CANARY", provenance=provenance),),
    )


@pytest.fixture
def audio(tmp_path: Path) -> Path:
    target = tmp_path / "B14-PRIVATE-PATH-CANARY.wav"
    with wave.open(str(target), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8000)
        output.writeframes(b"\0\0" * 800)
    return target


class Connection:
    def __init__(self, response: bytes, fail: bool = False) -> None:
        self.response, self.fail = response, fail
        self.writes: list[bytes] = []
        self.closed = False

    def write(self, data: bytes, timeout: float) -> None:
        self.writes.append(data)
        if self.fail:
            raise OSError("B14-REMOTE-SECRET-CANARY")

    def read(self, limit: int, timeout: float) -> bytes:
        part, self.response = self.response[:limit], self.response[limit:]
        return part

    def close(self) -> None:
        self.closed = True


class Transport:
    def __init__(self, response: bytes, *, fail: bool = False) -> None:
        self.response, self.fail = response, fail
        self.connections: list[Connection] = []
        self.headers: list[dict[str, str]] = []

    def open(
        self, target: Endpoint, headers: Mapping[str, str], body_length: int, timeout: float
    ) -> Connection:
        connection = Connection(self.response, self.fail)
        self.connections.append(connection)
        self.headers.append(dict(headers))
        return connection


class ScriptedGateway:
    def __init__(self, response: bytes) -> None:
        self.response = response
        self.calls: list[tuple[str, str, str, bytes]] = []

    def request(
        self,
        provider_id: str,
        endpoint: str,
        data_type: str,
        body: bytes,
        *,
        headers: dict[str, str] | None = None,
        reservation_id: str | None = None,
        cancel: threading.Event | None = None,
    ) -> bytes:
        self.calls.append((provider_id, endpoint, data_type, body))
        return self.response


@pytest.mark.parametrize("wrong_scope", ("provider", "endpoint", "data_type", "session"))
def test_stt_exact_scope_and_deleted_session_deny_before_transport(
    tmp_path: Path,
    audio: Path,
    wrong_scope: str,
) -> None:
    before = audio.read_bytes()
    fake = Transport(b'{"text":"synthetic transcription"}')
    with ConsentStore(tmp_path / "security.sqlite") as policy:
        provider = "gemini" if wrong_scope == "provider" else "openai"
        target = SUMMARY_ENDPOINT if wrong_scope == "endpoint" else STT_ENDPOINT
        datatype = "transcript" if wrong_scope == "data_type" else "audio"
        policy.grant(
            provider,
            target,
            datatype,
            capability="stt",
            scope=_fixture_grant_scope(policy),
            policy_version=2,
        )
        gateway = _fixture_gateway(policy, transport=fake, session_id="session")
        if wrong_scope == "session":
            policy.revoke_session("session")
        result = OpenAITranscriber(
            gateway,
            ProviderConfig(
                "openai",
                "test-model",
                endpoint=STT_ENDPOINT,
            ),
        ).transcribe(STTRequest(audio))
        assert not result.complete
        assert result.error_code in {"CONSENT_REQUIRED", "SESSION_REVOKED"}
        assert not fake.connections
    assert audio.read_bytes() == before


def test_failed_handoff_preserves_unknown_and_only_safe_error(
    tmp_path: Path,
    audio: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = Transport(b"", fail=True)
    db = tmp_path / "security.sqlite"
    with ConsentStore(db) as policy, CostLedger(db) as ledger:
        policy.grant(
            "openai",
            STT_ENDPOINT,
            "audio",
            capability="stt",
            scope=_fixture_grant_scope(policy),
            policy_version=2,
        )
        reservations: list[str] = []

        def reserve(request: CostRequest) -> str:
            assert (request.provider_id, request.endpoint, request.data_type) == (
                "openai",
                STT_ENDPOINT,
                "audio",
            )
            assert len(request.body) > 44 and request.operation == "stt"
            reservation = fixture_reservation(ledger, monkeypatch, request, 70, 100, "one-call")
            reservations.append(reservation)
            return reservation

        result = OpenAITranscriber(
            _fixture_gateway(policy, ledger=ledger, transport=fake),
            ProviderConfig("openai", "test-model", endpoint=STT_ENDPOINT),
        ).transcribe(
            STTRequest(audio),
            ExecutionContext(
                reservation_factory=reserve,
                headers={"Authorization": "Bearer B14-FAKE-KEY"},
            ),
        )
        assert result.error_code == "REMOTE_OUTCOME_UNKNOWN" and not result.outcome_known
        assert len(reservations) == len(fake.connections) == 1
        assert fixture_balance(ledger, "openai")["unknown_exposure"] == 70
        assert "CANARY" not in str(result.error_code)
        assert b"B14-PRIVATE-PATH-CANARY" not in b"".join(fake.connections[0].writes)
        assert fake.connections[0].closed
    with CostLedger(db) as restarted:
        assert fixture_balance(restarted, "openai")["available"] == 30


def test_cloud_without_reservation_is_blocked_by_injected_real_ledger(
    tmp_path: Path,
    audio: Path,
) -> None:
    fake = Transport(b'{"text":"unused"}')
    db = tmp_path / "security.sqlite"
    with ConsentStore(db) as policy, CostLedger(db) as ledger:
        policy.grant(
            "openai",
            STT_ENDPOINT,
            "audio",
            capability="stt",
            scope=_fixture_grant_scope(policy),
            policy_version=2,
        )
        adapter = OpenAITranscriber(
            _fixture_gateway(policy, ledger=ledger, transport=fake),
            ProviderConfig("openai", "test-model", endpoint=STT_ENDPOINT),
        )
        result = adapter.transcribe(STTRequest(audio))
        assert result.error_code == "BUDGET_REQUIRED" and not fake.connections


@pytest.mark.parametrize("bad_proof", ("missing", "cloud", "expired", "model", "endpoint"))
def test_ollama_does_not_trust_loopback_without_matching_local_evidence(bad_proof: str) -> None:
    target = "http://127.0.0.1:11434/api/chat"
    proof = LocalModelAttestation(target, "local-model", "a" * 64, True, time.monotonic() + 30)
    if bad_proof == "missing":
        evidence = None
    elif bad_proof == "cloud":
        evidence = replace(proof, cloud_disabled=False)
    elif bad_proof == "expired":
        evidence = replace(proof, expires_at_monotonic=time.monotonic() - 1)
    elif bad_proof == "model":
        evidence = replace(proof, model="different")
    else:
        evidence = replace(proof, endpoint=target + "/other")
    gateway = ScriptedGateway(b"{}")
    result = OllamaSummarizer(
        gateway,
        ProviderConfig(
            "ollama",
            "local-model",
            endpoint=target,
            execution_location="local",
            local_attestation=evidence,
            context_window_tokens=8192,
            max_output_tokens=256,
        ),
    ).summarize(summary_request())
    assert not result.complete and result.error_code == "LOCAL_EXECUTION_UNVERIFIED"
    assert not gateway.calls


def test_prompt_data_is_separate_and_model_claim_never_becomes_verified() -> None:
    gateway = ScriptedGateway(
        summary_response(
            [
                {
                    "text": "unverified model claim",
                    "segment_ids": ["s1"],
                    "status": "supported",
                }
            ]
        )
    )
    result = OpenAISummarizer(gateway, config()).summarize(summary_request())
    assert result.complete and result.claims[0].status == "uncertain"
    wire = json.loads(gateway.calls[0][3])
    assert "UNTRUSTED-CONTENT-CANARY" not in wire["instructions"]
    data = json.loads(wire["input"])
    assert data["core"][0]["text"] == "UNTRUSTED-CONTENT-CANARY"
    assert wire["store"] is False and wire["stream"] is False
    assert gateway.calls[0][:3] == ("openai", SUMMARY_ENDPOINT, "transcript")


@pytest.mark.parametrize("provenance", ("user_assertion", "unresolved"))
def test_resume_revalidates_claim_basis_from_source_provenance(provenance: str) -> None:
    gateway = ScriptedGateway(summary_response([{"text": "claim", "segment_ids": ["s1"]}]))
    adapter = OpenAISummarizer(gateway, config())
    request = summary_request(provenance=provenance)
    original = adapter.summarize(request)
    assert original.complete
    valid_resume = adapter.summarize(replace(request, checkpoint=original.checkpoint))
    assert valid_resume.complete and valid_resume.claims == original.claims
    assert len(gateway.calls) == 1
    completed = original.checkpoint.completed[0]
    forged = replace(completed, claims=(SummaryClaim("claim", ("s1",), "uncertain", "transcript"),))
    checkpoint = replace(original.checkpoint, completed=(forged,))
    resumed = adapter.summarize(replace(request, checkpoint=checkpoint))
    # Either refuse inconsistent cache metadata or recompute the same evidence class.
    assert resumed.error_code == "CHECKPOINT_MISMATCH" or (
        resumed.claims[0].basis == original.claims[0].basis
        and resumed.claims[0].status == original.claims[0].status
    )
    if resumed.error_code == "CHECKPOINT_MISMATCH":
        assert not resumed.claims and not resumed.coverage
        assert not resumed.checkpoint.completed and resumed.missing
    assert len(gateway.calls) == 1


def test_resume_rejects_unsupported_claim_masquerading_as_transcript() -> None:
    gateway = ScriptedGateway(summary_response([{"text": "inference", "segment_ids": []}]))
    adapter = OpenAISummarizer(gateway, config())
    request = summary_request()
    original = adapter.summarize(request)
    completed = original.checkpoint.completed[0]
    forged = replace(completed, claims=(SummaryClaim("inference", (), "uncertain", "transcript"),))
    resumed = adapter.summarize(
        replace(request, checkpoint=replace(original.checkpoint, completed=(forged,)))
    )
    assert resumed.error_code == "CHECKPOINT_MISMATCH" or (
        resumed.claims[0].status == "unsupported" and resumed.claims[0].basis == "model_inference"
    )
    if resumed.error_code == "CHECKPOINT_MISMATCH":
        assert not resumed.claims and not resumed.checkpoint.completed
    assert len(gateway.calls) == 1


_BUNDLES: list[Any] = []


@pytest.fixture(autouse=True)
def _close_bundles() -> Iterator[None]:
    yield
    while _BUNDLES:
        _BUNDLES.pop().close()


def confirmed(path: Path) -> dict[str, Any]:
    """G-P13 explicit approval fixture: this run's Yes and responsibility check of the
    synthetic folder, then the sealed bundle the loader is given (never the folder)."""
    from recoryn.models import artifacts
    from recoryn.models._artifact_io import freeze, whisper_snapshot

    snapshot = whisper_snapshot(path)
    registry = artifacts.ConfirmationRegistry()
    evidence = registry.confirm(
        snapshot, shown=registry.key(snapshot), accepted=True, acknowledged=True
    )
    assert evidence is not None
    bundle = freeze(evidence, parent=path.parent)
    _BUNDLES.append(bundle)
    return bundle.description()


def test_local_backend_exception_with_broken_str_still_returns_safe_result(
    tmp_path: Path,
    audio: Path,
) -> None:
    model = tmp_path / "fake-model"
    model.mkdir()
    for name in ("model.bin", "config.json", "tokenizer.json"):
        (model / name).write_bytes(b"fake-only")

    class BackendFailure(Exception):
        def __str__(self) -> str:
            raise RuntimeError("B14-SECRET-BROKEN-STR-CANARY")

    class Model:
        def transcribe(self, *args: object, **kwargs: object) -> object:
            raise BackendFailure()

    calls: list[dict[str, object]] = []

    def factory(*args: object, **kwargs: object) -> Model:
        calls.append(kwargs)
        return Model()

    adapter = FasterWhisperProvider(model, model_factory=factory, bundle=confirmed(model))
    assert not calls
    result = adapter.transcribe(STTRequest(audio))
    assert result.error_code == "PROVIDER_FAILED" and not result.complete
    assert calls[0]["local_files_only"] is True


def test_broken_backend_formatter_preserves_partial_and_releases_model_lock(
    tmp_path: Path,
    audio: Path,
) -> None:
    model = tmp_path / "partial-fake-model"
    model.mkdir()
    for name in ("model.bin", "config.json", "tokenizer.json"):
        (model / name).write_bytes(b"fake-only")

    class Failure(Exception):
        def __str__(self) -> str:
            raise ValueError("B14-FORMATTER-CANARY")

    class Model:
        def transcribe(self, *args: object, **kwargs: object) -> object:
            def segments() -> Iterator[SimpleNamespace]:
                yield SimpleNamespace(start=0, end=0.05, text="partial fact")
                raise Failure()

            return segments(), SimpleNamespace(language="ko")

    provider = FasterWhisperProvider(
        model,
        timeout_seconds=1,
        model_factory=lambda *a, **kw: Model(),
        bundle=confirmed(model),
    )
    for _ in range(2):
        result = provider.transcribe(STTRequest(audio))
        assert result.error_code == "PROVIDER_FAILED" and not result.complete
        assert result.processed_ms == 50 and result.segments[0].text == "partial fact"


def test_missing_tokenizer_is_denied_before_optional_model_import(
    tmp_path: Path,
    audio: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = tmp_path / "incomplete-local-model"
    model.mkdir()
    (model / "model.bin").write_bytes(b"fake-only")
    (model / "config.json").write_bytes(b"{}")
    imports: list[str] = []

    def no_model_import(name: str) -> object:
        imports.append(name)
        pytest.fail("incomplete local artifacts must fail before optional SDK/model import")

    from recoryn.models._artifact_io import whisper_snapshot
    from recoryn.providers import ProviderError

    # G-P13: an incomplete folder is never confirmed, and nothing reaches an import.
    with pytest.raises(ProviderError, match="MODEL_MISSING"):
        whisper_snapshot(model)
    (model / "tokenizer.json").write_bytes(b"fake-only")
    complete = confirmed(model)
    (model / "tokenizer.json").unlink()
    monkeypatch.setattr(importlib, "import_module", no_model_import)
    instance = FasterWhisperProvider(model)
    result = instance.transcribe(STTRequest(audio))
    assert result.error_code == "CAPABILITY_UNSUPPORTED" and not result.complete
    # A bundle description without the tokenizer stops before any optional import.
    forged = dict(
        complete, entries=[row for row in complete["entries"] if row[0] != "tokenizer.json"]
    )
    result = FasterWhisperProvider(model, bundle=forged).transcribe(STTRequest(audio))
    assert result.error_code == "MODEL_MISSING" and not result.complete
    assert not imports


def test_multi_core_synthesis_needs_separate_context_consent_and_resumes_only_synthesis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class GeneratedConnection(Connection):
        def __init__(self) -> None:
            super().__init__(b"")
            self.generated = False

        def read(self, limit: int, timeout: float) -> bytes:
            if not self.generated:
                self.generated = True
                prompt = json.loads(json.loads(b"".join(self.writes))["input"])
                refs = (
                    [prompt["core"][0]["segment_id"]]
                    if prompt["mode"] == "core"
                    else list(
                        dict.fromkeys(
                            ref
                            for group in prompt["summaries"]
                            for claim in group
                            for ref in claim["segment_ids"]
                        )
                    )
                )
                self.response = summary_response([{"text": "bounded claim", "segment_ids": refs}])
            return super().read(limit, timeout)

    class GeneratedTransport(Transport):
        def open(
            self, target: Endpoint, headers: Mapping[str, str], body_length: int, timeout: float
        ) -> Connection:
            connection = GeneratedConnection()
            self.connections.append(connection)
            return connection

    fake = GeneratedTransport(b"")
    request = SummaryRequest(
        "fixed-long-revision",
        tuple(
            TranscriptSegment(f"s{i}", i * 1000, (i + 1) * 1000, f"PRIVATE-RAW-{i}-" + "z" * 800)
            for i in range(6)
        ),
    )
    db = tmp_path / "security.sqlite"
    with ConsentStore(db) as policy, CostLedger(db) as ledger:
        calls = 0

        def reserve(wire: CostRequest) -> str:
            nonlocal calls
            calls += 1
            return fixture_reservation(ledger, monkeypatch, wire, 1, 100, f"summary-{calls}")

        context = ExecutionContext(reservation_factory=reserve)
        policy.grant(
            "openai",
            SUMMARY_ENDPOINT,
            "transcript",
            capability="summary",
            scope=_fixture_grant_scope(policy),
            policy_version=2,
        )
        adapter = OpenAISummarizer(
            _fixture_gateway(policy, ledger=ledger, transport=fake, capability="summary"), config()
        )
        partial = adapter.summarize(request, context)
        assert not partial.complete and partial.error_code == "CONSENT_REQUIRED"
        assert partial.coverage and not partial.missing
        calls_before = len(fake.connections)
        assert calls_before > 1
        policy.grant(
            "openai",
            SUMMARY_ENDPOINT,
            "context",
            capability="summary",
            scope=_fixture_grant_scope(policy),
            policy_version=2,
        )
        assert (
            adapter.summarize(replace(request, checkpoint=partial.checkpoint), context).error_code
            == "CONSENT_REQUIRED"
        )
        assert len(fake.connections) == calls_before
        adapter = OpenAISummarizer(
            _fixture_gateway(policy, ledger=ledger, transport=fake, capability="summary"), config()
        )
        resumed = adapter.summarize(replace(request, checkpoint=partial.checkpoint), context)
        assert resumed.complete and not resumed.missing
        assert len(fake.connections) == calls_before + 1
        synthesis_body = b"".join(fake.connections[-1].writes)
        assert b"PRIVATE-RAW-" not in synthesis_body
        assert all(c.status == "uncertain" for c in resumed.claims)
        changed = adapter.summarize(
            replace(request, template="tasks", checkpoint=partial.checkpoint), context
        )
        assert changed.error_code == "CHECKPOINT_MISMATCH" and not changed.complete
        assert len(fake.connections) == calls_before + 1


# The older tests exercise revocation/transport, with an explicitly chosen library
# grant. G02's separate cases exercise the default session-only permission.
def _fixture_request(
    policy: ConsentStore, session_id: str = "session", capability: str = "stt", generation: int = 0
) -> ConsentRequest:
    try:
        policy.bind_session(session_id, generation)
    except SecurityError:
        pass  # Registration grants nothing; the tested API still checks the fence.
    return ConsentRequest(session_id, generation, capability, 2)


def _fixture_grant_scope(policy: ConsentStore) -> ConsentScope:
    _fixture_request(policy)
    return ConsentScope.library()


def _fixture_gateway(
    policy: ConsentStore,
    *,
    session_id: str = "session",
    generation: int = 0,
    capability: str = "stt",
    factory=Gateway,
    **kwargs,
):
    root = factory(policy, **kwargs)
    request = _fixture_request(policy, session_id, capability)
    if "expected_grants" not in kwargs:
        bindings = []
        rows = policy._db.execute(
            "SELECT DISTINCT provider,endpoint,data_type FROM security_grants_v2 WHERE capability=? AND scope_kind='library' AND scope_id='' AND policy_version=2",
            (capability,),
        ).fetchall()
        for provider, endpoint, data_type in rows:
            bindings.extend(
                policy.capture_bindings(
                    provider, endpoint, (data_type,), scope=ConsentScope.library(), request=request
                )
            )
        kwargs["expected_grants"] = tuple(bindings)
        root = factory(policy, **kwargs)
    return root.for_session(
        session_id,
        generation,
        capability=capability,
        scope=ConsentScope.library(),
        policy_version=2,
    )
