"""Fixture wire and real-policy/fake-transport boundaries, never live services."""

from __future__ import annotations

import json
import threading
import wave
from pathlib import Path
from typing import Any

import pytest

from recoryn.providers import (
    ExecutionContext,
    ProviderConfig,
    STTRequest,
    SummaryRequest,
    TranscriptSegment,
)
from recoryn.providers._common import encode
from recoryn.security import ConsentRequest, ConsentScope, ConsentStore, Gateway, SecurityError
from recoryn.storage import Library
from recoryn.summarization import AnthropicSummarizer, GeminiSummarizer, OpenAISummarizer
from recoryn.transcription import GeminiTranscriber, OpenAITranscriber

pytestmark = pytest.mark.contract


class WireGateway:
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


def request() -> SummaryRequest:
    return SummaryRequest("rev-fixed", (TranscriptSegment("s", 0, 100, "an explicit decision"),))


def configured(provider_id: str, **kwargs: Any) -> ProviderConfig:
    return ProviderConfig(
        provider_id, "model-from-user", context_window_tokens=8192, max_output_tokens=512, **kwargs
    )


@pytest.mark.parametrize(
    "provider,adapter,response,code",
    [
        ("openai", OpenAISummarizer, b'{"status":"incomplete","output":[]}', "RESULT_INCOMPLETE"),
        ("openai", OpenAISummarizer, b'{"status":"completed","output":null}', "RESULT_INVALID"),
        (
            "openai",
            OpenAISummarizer,
            b'{"status":"completed","output":[{"type":"message","content":[]}]}',
            "RESULT_INVALID",
        ),
        (
            "anthropic",
            AnthropicSummarizer,
            b'{"stop_reason":"max_tokens","content":[]}',
            "RESULT_INCOMPLETE",
        ),
        (
            "anthropic",
            AnthropicSummarizer,
            b'{"stop_reason":"tool_use","content":[]}',
            "RESULT_INCOMPLETE",
        ),
        (
            "anthropic",
            AnthropicSummarizer,
            b'{"stop_reason":"end_turn","content":[{}]}',
            "RESULT_INVALID",
        ),
        ("gemini", GeminiSummarizer, b'{"candidates":[]}', "RESULT_INVALID"),
        (
            "gemini",
            GeminiSummarizer,
            b'{"candidates":[{"finishReason":"SAFETY"}]}',
            "RESULT_INCOMPLETE",
        ),
        (
            "gemini",
            GeminiSummarizer,
            b'{"candidates":[{"finishReason":"STOP","content":{"parts":[{"thought":true,"text":"CANARY"}]}}]}',
            "RESULT_INVALID",
        ),
        ("openai", OpenAISummarizer, b'{"error":{"message":"CANARY"}}', "PROVIDER_REJECTED"),
        (
            "openai",
            OpenAISummarizer,
            b'{"status":"completed","status":"incomplete"}',
            "RESULT_INVALID",
        ),
    ],
)
def test_truncation_refusal_and_malformed_outputs_never_complete(
    provider: str, adapter: Any, response: bytes, code: str
) -> None:
    gateway = WireGateway(response)
    result = adapter(gateway, configured(provider)).summarize(request())
    assert not result.complete and result.error_code == code and result.missing
    assert not result.claims and len(gateway.calls) == 1
    assert "CANARY" not in repr(result.error_code)


@pytest.mark.parametrize(
    "claim",
    [
        {"text": "bad", "segment_ids": ["not-in-source"]},
        {"text": "bad", "segment_ids": ["s", "s"]},
        {"text": "bad", "segment_ids": "s"},
        {"text": "bad", "segment_ids": [3]},
        {"text": "", "segment_ids": ["s"]},
    ],
)
def test_claim_schema_rejects_fabricated_or_malformed_references(claim: dict[str, Any]) -> None:
    response = encode(
        {
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": json.dumps({"claims": [claim]})}],
        }
    )
    result = AnthropicSummarizer(WireGateway(response), configured("anthropic")).summarize(
        request()
    )
    assert not result.complete and not result.coverage
    assert result.error_code in {"REFERENCE_INVALID", "RESULT_INVALID"}


def test_model_supported_label_is_not_human_evidence() -> None:
    text = json.dumps(
        {"claims": [{"text": "unreviewed claim", "segment_ids": ["s"], "status": "supported"}]}
    )
    response = encode(
        {
            "status": "completed",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}],
        }
    )
    result = OpenAISummarizer(WireGateway(response), configured("openai")).summarize(request())
    assert result.complete and result.claims[0].status == "uncertain"
    from recoryn.content import Claim

    persisted = Claim(result.claims[0].text, result.claims[0].segment_ids, result.claims[0].status)
    assert persisted.status == "uncertain"


class Connection:
    def __init__(self, response: bytes) -> None:
        self.response = response
        self.written = bytearray()

    def write(self, data: bytes, timeout: float) -> None:
        self.written.extend(data)

    def read(self, limit: int, timeout: float) -> bytes:
        result, self.response = self.response[:limit], self.response[limit:]
        return result

    def close(self) -> None:
        pass


class Transport:
    def __init__(self, response: bytes) -> None:
        self.response = response
        self.connections: list[Connection] = []

    def open(
        self, endpoint: Any, headers: dict[str, str], length: int, timeout: float
    ) -> Connection:
        connection = Connection(self.response)
        self.connections.append(connection)
        return connection


def test_session_bound_real_gateway_blocks_without_consent_then_uses_fake_transport(
    tmp_path: Path,
) -> None:
    response = encode(
        {
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": '{"claims":[{"text":"x","segment_ids":["s"]}]}',
                        }
                    ],
                }
            ],
        }
    )
    transport = Transport(response)
    with Library(tmp_path) as library, ConsentStore(library.db_path) as consents:
        library.create_session("session")
        gateway = _fixture_gateway(consents, transport=transport, session_id="session")
        adapter = OpenAISummarizer(gateway, configured("openai"))
        denied = adapter.summarize(request())
        assert denied.error_code == "CONSENT_REQUIRED" and not transport.connections
        consents.grant(
            "openai",
            adapter.endpoint,
            "transcript",
            capability="stt",
            scope=_fixture_grant_scope(consents),
            policy_version=2,
        )
        assert adapter.summarize(request()).error_code == "CONSENT_REQUIRED"
        adapter = OpenAISummarizer(
            _fixture_gateway(consents, transport=transport), configured("openai")
        )
        assert adapter.summarize(request()).complete
        assert len(transport.connections) == 1
        consents.revoke_session("session")
        revoked = adapter.summarize(request())
        assert revoked.error_code in {"SESSION_REVOKED", "CONSENT_REQUIRED"}
        assert len(transport.connections) == 1


@pytest.mark.parametrize(
    "adapter,provider", [(OpenAITranscriber, "openai"), (GeminiTranscriber, "gemini")]
)
def test_invalid_audio_and_cancel_do_not_dispatch(
    tmp_path: Path, adapter: Any, provider: str
) -> None:
    gateway = WireGateway(b"{}")
    audio = tmp_path / "bad.wav"
    audio.write_bytes(b"not an audio file")
    instance = adapter(gateway, configured(provider))
    result = instance.transcribe(STTRequest(audio))
    assert not result.complete and not gateway.calls
    assert result.error_code == "AUDIO_UNSUPPORTED"
    cancel = threading.Event()
    cancel.set()
    assert instance.transcribe(
        STTRequest(tmp_path / "missing.wav"), ExecutionContext(cancel=cancel)
    ).cancelled
    assert not gateway.calls


def test_audio_header_cannot_claim_unbounded_or_missing_payload(tmp_path: Path) -> None:
    path = tmp_path / "truncated.wav"
    with wave.open(str(path), "wb") as stream:
        stream.setparams((1, 2, 16000, 0, "NONE", "none"))
        stream.writeframes(b"\0\0" * 32)
    path.write_bytes(path.read_bytes()[:-10])
    gateway = WireGateway(b'{"text":"fake"}')
    result = OpenAITranscriber(gateway, configured("openai")).transcribe(STTRequest(path))
    assert result.error_code == "INPUT_INVALID" and not gateway.calls


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
    factory=Gateway,
    **kwargs,
):
    root = factory(policy, **kwargs)
    request = _fixture_request(policy, session_id)
    if "expected_grants" not in kwargs:
        bindings = []
        rows = policy._db.execute(
            "SELECT DISTINCT provider,endpoint,data_type FROM security_grants_v2 WHERE capability='stt' AND scope_kind='library' AND scope_id='' AND policy_version=2"
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
        session_id, generation, capability="stt", scope=ConsentScope.library(), policy_version=2
    )
