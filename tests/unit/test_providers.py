"""Pure/fake provider contracts; never load weights or contact a service."""

from __future__ import annotations

import hashlib
import json
import threading
import time
import wave
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from recoryn.providers import (
    ChunkSummary,
    ExecutionContext,
    LocalModelAttestation,
    ProviderConfig,
    ProviderError,
    SegmentSpan,
    STTRequest,
    SummaryCheckpoint,
    SummaryClaim,
    SummaryRequest,
    TranscriptSegment,
)
from recoryn.providers._common import Run, decode, encode
from recoryn.summarization import (
    AnthropicSummarizer,
    GeminiSummarizer,
    OllamaSummarizer,
    OpenAISummarizer,
    plan_summary,
)
from recoryn.summarization.adapters import parse_claims
from recoryn.transcription import FasterWhisperProvider, GeminiTranscriber, OpenAITranscriber
from recoryn.transcription import adapters as stt_module

pytestmark = pytest.mark.unit


class FakeGateway:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail_at: int | None = None
        self.response: bytes | None = None
        self.error: Exception = RuntimeError("CANARY should not reach error messages")
        self.bad_refs = False

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
        self.calls.append(
            {
                "provider": provider_id,
                "endpoint": endpoint,
                "data_type": data_type,
                "body": body,
                "headers": headers,
                "reservation": reservation_id,
                "cancel": cancel,
            }
        )
        if len(self.calls) == self.fail_at:
            raise self.error
        if self.response is not None:
            return self.response
        if data_type == "audio":
            if provider_id == "openai":
                return b'{"text":"hello"}'
            return encode(
                {
                    "candidates": [
                        {"finishReason": "STOP", "content": {"parts": [{"text": "hello"}]}}
                    ]
                }
            )
        value = json.loads(body)
        if provider_id in {"ollama", "anthropic"}:
            data = json.loads(value["messages"][-1]["content"])
        elif provider_id == "openai":
            data = json.loads(value["input"])
        else:
            data = json.loads(value["contents"][0]["parts"][0]["text"])
        if data["mode"] == "core":
            claims = [
                {
                    "text": "fact " + s["segment_id"],
                    "segment_ids": ["invented" if self.bad_refs else s["segment_id"]],
                }
                for s in data["core"]
            ]
        else:
            claims = [claim for group in data["summaries"] for claim in group]
        text = json.dumps({"claims": claims})
        return {
            "ollama": lambda: encode(
                {"done": True, "done_reason": "stop", "message": {"content": text}}
            ),
            "openai": lambda: encode(
                {
                    "status": "completed",
                    "output": [
                        {"type": "message", "content": [{"type": "output_text", "text": text}]}
                    ],
                }
            ),
            "anthropic": lambda: encode(
                {"stop_reason": "end_turn", "content": [{"type": "text", "text": text}]}
            ),
            "gemini": lambda: encode(
                {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": text}]}}]}
            ),
        }[provider_id]()


@pytest.fixture
def audio(tmp_path: Path) -> Path:
    path = tmp_path / "sensitive-private-name.wav"
    with wave.open(str(path), "wb") as stream:
        stream.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        stream.writeframes(b"\x01\x00" * 1600)
    return path


def config(provider: str = "openai", **kwargs: Any) -> ProviderConfig:
    values: dict[str, Any] = {
        "provider_id": provider,
        "model": "user-selected-model",
        "context_window_tokens": 8192,
        "max_output_tokens": 512,
    }
    if provider == "ollama":
        endpoint = "http://127.0.0.1:11434/api/chat"
        values.update(
            execution_location="local",
            endpoint=endpoint,
            local_attestation=LocalModelAttestation(
                endpoint, "user-selected-model", "a" * 64, True, time.monotonic() + 60
            ),
        )
    values.update(kwargs)
    return ProviderConfig(**values)


def transcript(count: int = 1, text_size: int = 20) -> SummaryRequest:
    return SummaryRequest(
        "fixed-revision",
        tuple(
            TranscriptSegment(f"s{i}", i * 100, i * 100 + 100, "가" * text_size)
            for i in range(count)
        ),
    )


def model_dir(tmp_path: Path) -> Path:
    path = tmp_path / "local-model"
    path.mkdir()
    for name in ("model.bin", "config.json", "tokenizer.json"):
        (path / name).write_bytes(b"fake, not model weights")
    return path


def test_frozen_values_and_secret_context_repr() -> None:
    ctx = ExecutionContext(headers={"Authorization": "CANARY"})
    assert "CANARY" not in repr(ctx)
    with pytest.raises(TypeError):
        ctx.headers["Authorization"] = "other"  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        ctx.progress = None  # type: ignore[misc]
    assert str(ProviderError("unsafe secret")) == "PROVIDER_FAILED"


@pytest.mark.parametrize(
    "values",
    [
        {"provider_id": "unknown"},
        {"model": ""},
        {"model": "x\nkey"},
        {"timeout_seconds": True},
        {"timeout_seconds": float("nan")},
        {"timeout_seconds": 0},
        {"max_output_tokens": 0},
        {"max_requests": True},
        {"max_response_bytes": -1},
        {"context_window_tokens": False},
        {"execution_location": "unknown"},
    ],
)
def test_invalid_provider_configuration(values: dict[str, Any]) -> None:
    with pytest.raises(ProviderError):
        config(**values)


@pytest.mark.parametrize(
    "provider,adapter",
    [
        ("openai", OpenAISummarizer),
        ("anthropic", AnthropicSummarizer),
        ("gemini", GeminiSummarizer),
        ("ollama", OllamaSummarizer),
    ],
)
def test_summary_wire_fixtures_and_uncertain_claims(provider: str, adapter: Any) -> None:
    gateway = FakeGateway()
    instance = adapter(gateway, config(provider))
    assert instance.capabilities().summarization and not instance.capabilities().transcription
    result = instance.summarize(transcript())
    assert result.complete and result.transcript_revision_id == "fixed-revision"
    assert result.claims[0].segment_ids == ("s0",) and result.claims[0].status == "uncertain"
    assert result.coverage == (SegmentSpan("s0", 0, 20),) and not result.missing
    assert len(gateway.calls) == 1 and gateway.calls[0]["data_type"] == "transcript"
    body = json.loads(gateway.calls[0]["body"])
    if provider == "openai":
        assert body["store"] is False and body["truncation"] == "disabled"
    if provider == "anthropic":
        assert gateway.calls[0]["headers"]["anthropic-version"] == "2026-10-21"
    if provider == "ollama":
        assert body["stream"] is False and body["format"] == "json"


def test_long_context_core_overlap_and_synthesis_have_original_refs() -> None:
    gateway = FakeGateway()
    reservations: list[str] = []

    def reserve(provider: str, endpoint: str, kind: str, byte_count: int) -> str:
        assert provider == "openai" and endpoint.startswith("https://") and byte_count > 0
        value = "r" + str(len(reservations))
        reservations.append(value)
        return value

    request = transcript(12, 300)
    result = OpenAISummarizer(gateway, config()).summarize(
        request, ExecutionContext(reservation_factory=reserve)
    )
    assert result.complete and not result.missing
    assert len(gateway.calls) > 2 and len(reservations) == len(gateway.calls)
    assert {call["data_type"] for call in gateway.calls} == {"transcript", "context"}
    assert {ref for c in result.claims for ref in c.segment_ids} == {
        s.segment_id for s in request.segments
    }
    spans = [s.span for chunk in plan_summary(request, config()) for s in chunk.core]
    assert set(result.coverage) == set(spans)
    assert any(chunk.context for chunk in plan_summary(request, config()))


def test_cancel_partial_checkpoint_resume_and_configuration_mismatch() -> None:
    gateway = FakeGateway()
    cancel = threading.Event()
    request = transcript(6, 500)

    def stop_after_first(event: Any) -> None:
        if event.stage == "summarizing":
            cancel.set()

    adapter = OpenAISummarizer(gateway, config())
    partial = adapter.summarize(request, ExecutionContext(cancel=cancel, progress=stop_after_first))
    assert partial.cancelled and not partial.complete and partial.missing and partial.coverage
    count = len(gateway.calls)
    resumed = adapter.summarize(replace(request, checkpoint=partial.checkpoint))
    assert resumed.complete and len(gateway.calls) > count
    changed = adapter.summarize(replace(request, template="tasks", checkpoint=partial.checkpoint))
    assert changed.error_code == "CHECKPOINT_MISMATCH" and not changed.complete


def test_unknown_core_outcome_retains_prior_results_without_retry() -> None:
    gateway = FakeGateway()
    gateway.fail_at = 2
    result = OpenAISummarizer(gateway, config()).summarize(transcript(6, 500))
    assert not result.complete and result.error_code == "REMOTE_OUTCOME_UNKNOWN"
    assert not result.outcome_known and result.coverage and result.missing
    assert len(gateway.calls) == 2
    assert "CANARY" not in repr(result.error_code)


def test_invalid_refs_block_whole_core_and_never_mark_supported() -> None:
    gateway = FakeGateway()
    gateway.bad_refs = True
    result = OpenAISummarizer(gateway, config()).summarize(transcript())
    assert result.error_code == "REFERENCE_INVALID" and not result.coverage and result.missing
    parsed = parse_claims(
        {
            "claims": [
                {"text": "human changed", "segment_ids": ["s"], "status": "supported"},
                {"text": "guess", "segment_ids": []},
            ]
        },
        {"s"},
        {"s": "user_assertion"},
    )
    assert parsed[0].status == "user_assertion" and parsed[0].basis == "user_assertion"
    assert parsed[1].status == "unsupported" and parsed[1].basis == "model_inference"


@pytest.mark.parametrize("change", ["proof", "expiry", "model", "cloud", "endpoint"])
def test_ollama_requires_current_endpoint_bound_offline_attestation(change: str) -> None:
    gateway = FakeGateway()
    selected = config("ollama")
    proof = selected.local_attestation
    assert proof is not None
    if change == "proof":
        selected = replace(selected, local_attestation=None)
    elif change == "expiry":
        selected = replace(selected, local_attestation=replace(proof, expires_at_monotonic=0))
    elif change == "model":
        selected = replace(selected, model="cloud-model")
    elif change == "cloud":
        selected = replace(selected, local_attestation=replace(proof, cloud_disabled=False))
    else:
        selected = replace(selected, endpoint="http://192.0.2.1:11434/api/chat")
    result = OllamaSummarizer(gateway, selected).summarize(transcript())
    assert result.error_code == "LOCAL_EXECUTION_UNVERIFIED" and not gateway.calls


def test_limits_unknown_context_reused_budget_and_empty_input() -> None:
    gateway = FakeGateway()
    assert (
        OpenAISummarizer(gateway, config(context_window_tokens=None))
        .summarize(transcript())
        .error_code
        == "CONTEXT_LIMIT_UNKNOWN"
    )
    assert (
        OpenAISummarizer(gateway, config(context_window_tokens=1000))
        .summarize(transcript())
        .error_code
        == "CONTEXT_LIMIT"
    )
    result = OpenAISummarizer(gateway, config()).summarize(
        transcript(8, 500), ExecutionContext(reservation_factory=lambda *args: "same")
    )
    assert result.error_code == "BUDGET_RESERVATION_REUSED" and result.coverage
    limited = OpenAISummarizer(FakeGateway(), config(max_requests=1)).summarize(transcript(8, 500))
    assert limited.error_code == "REQUEST_LIMIT" and not limited.complete
    assert OpenAISummarizer(FakeGateway(), config()).summarize(transcript(0)).complete


def test_openai_audio_multipart_is_gateway_only_and_hides_source_path(audio: Path) -> None:
    gateway = FakeGateway()
    request = STTRequest(audio, language="ko", offset_ms=1000, track_id="mic")
    adapter = OpenAITranscriber(gateway, config())
    result = adapter.transcribe(request)
    assert result.complete and result.processed_ms == 100 and result.segments[0].start_ms == 1000
    assert result.segments[0].timing_quality == "clip"
    call = gateway.calls[0]
    assert call["data_type"] == "audio" and b'filename="audio.wav"' in call["body"]
    assert audio.name.encode() not in call["body"] and b'name="language"' in call["body"]
    assert result.audio_sha256 == hashlib.sha256(audio.read_bytes()).hexdigest()
    assert adapter.transcribe(request).segments == result.segments


def test_openai_verbose_segments_and_invalid_model_timestamp_gate(audio: Path) -> None:
    gateway = FakeGateway()
    gateway.response = b'{"segments":[{"start":0,"end":0.1,"text":"hello"}]}'
    adapter = OpenAITranscriber(gateway, config(model="whisper-1"), timestamps=True)
    assert adapter.capabilities().segment_timestamps
    assert adapter.transcribe(STTRequest(audio)).complete
    assert b"timestamp_granularities[]" in gateway.calls[0]["body"]
    with pytest.raises(ProviderError):
        OpenAITranscriber(gateway, config(), timestamps=True)


def test_gemini_audio_inline_fixture_and_incomplete_response(audio: Path) -> None:
    gateway = FakeGateway()
    adapter = GeminiTranscriber(gateway, config("gemini"))
    result = adapter.transcribe(STTRequest(audio))
    assert result.complete and result.segments[0].timing_quality == "clip"
    sent = json.loads(gateway.calls[0]["body"])
    assert sent["contents"][0]["parts"][1]["inlineData"]["mimeType"] == "audio/wav"
    gateway.response = b'{"candidates":[{"finishReason":"MAX_TOKENS"}]}'
    assert adapter.transcribe(STTRequest(audio)).error_code == "RESULT_INCOMPLETE"


def test_local_model_is_lazy_local_files_only_and_keeps_partial_results(
    tmp_path: Path, audio: Path
) -> None:
    calls: list[dict[str, Any]] = []

    def factory(path: str, **kwargs: Any) -> Any:
        calls.append(kwargs)

        def generate() -> Any:
            yield SimpleNamespace(start=0.0, end=0.05, text="first")
            raise MemoryError("CANARY")

        return SimpleNamespace(
            supported_languages=["ko"],
            transcribe=lambda *a, **k: (generate(), SimpleNamespace(language="ko")),
        )

    adapter = FasterWhisperProvider(model_dir(tmp_path), model_factory=factory)
    assert not calls
    result = adapter.transcribe(STTRequest(audio, language="ko"))
    assert result.error_code == "RESOURCE_EXHAUSTED" and result.segments[0].text == "first"
    assert (
        result.processed_ms == 50 and not result.complete and calls[0]["local_files_only"] is True
    )
    assert calls[0]["device"] == "cpu" and len(calls) == 1
    assert adapter.transcribe(STTRequest(audio, language="en")).error_code == "LANGUAGE_UNSUPPORTED"


def test_local_missing_files_dependency_and_cancel_never_download(
    tmp_path: Path, audio: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = FasterWhisperProvider(tmp_path / "not-installed")
    assert adapter.transcribe(STTRequest(audio)).error_code == "MODEL_MISSING"
    path = model_dir(tmp_path)
    (path / "tokenizer.json").unlink()
    assert FasterWhisperProvider(path).transcribe(STTRequest(audio)).error_code == "MODEL_MISSING"
    (path / "tokenizer.json").write_bytes(b"fake")

    def missing_package(name: str) -> Any:
        raise ImportError("CANARY")

    monkeypatch.setattr(stt_module.importlib, "import_module", missing_package)
    assert (
        FasterWhisperProvider(path).transcribe(STTRequest(audio)).error_code == "DEPENDENCY_MISSING"
    )
    cancelled = threading.Event()
    cancelled.set()
    assert (
        FasterWhisperProvider(path)
        .transcribe(STTRequest(audio), ExecutionContext(cancel=cancelled))
        .cancelled
    )


def test_local_success_and_safe_runtime_failure(tmp_path: Path, audio: Path) -> None:
    model = SimpleNamespace(
        transcribe=lambda *a, **k: (
            iter([SimpleNamespace(start=0, end=0.1, text="ok")]),
            SimpleNamespace(language="en"),
        )
    )
    adapter = FasterWhisperProvider(
        model_dir(tmp_path), device="cuda", model_factory=lambda *a, **k: model
    )
    assert adapter.transcribe(STTRequest(audio)).complete
    model.transcribe = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("CANARY"))
    assert adapter.transcribe(STTRequest(audio)).error_code == "PROVIDER_FAILED"


@pytest.mark.parametrize("data", [b"[]", b'{"a":1,"a":2}', b'{"a":NaN}', b"{", b"\xff"])
def test_strict_response_parsing(data: bytes) -> None:
    with pytest.raises(ProviderError):
        decode(data, 4096)


def test_deadline_bad_progress_errors_and_bounded_response() -> None:
    run = Run(config(), None)
    run.deadline = 0
    with pytest.raises(ProviderError, match="TIMEOUT"):
        run.check()
    ctx = ExecutionContext(progress=lambda e: (_ for _ in ()).throw(RuntimeError("CANARY")))
    result = OpenAISummarizer(FakeGateway(), config()).summarize(transcript(), ctx)
    assert result.error_code == "PROGRESS_CALLBACK_FAILED" and result.coverage
    with pytest.raises(ProviderError, match="RESPONSE_TOO_LARGE"):
        decode(b"{}", 1)
    with pytest.raises(ProviderError):
        encode({"value": b"not JSON"})


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://user:password@example.com/api",
        "https://example.com/a?key=x",
        "https://example.com/a#x",
        "http://example.com/a",
        "https://example.com:invalid/a",
    ],
)
def test_invalid_endpoint_never_calls_gateway(endpoint: str) -> None:
    gateway = FakeGateway()
    result = OpenAISummarizer(gateway, config(endpoint=endpoint)).summarize(transcript())
    assert not result.complete and not gateway.calls


def test_unknown_and_cancelled_cloud_outcomes_are_safe(audio: Path) -> None:
    gateway = FakeGateway()
    gateway.fail_at = 1
    result = OpenAITranscriber(gateway, config()).transcribe(STTRequest(audio))
    assert result.error_code == "REMOTE_OUTCOME_UNKNOWN" and not result.outcome_known
    assert "CANARY" not in repr(result.error_code)
    cancel = threading.Event()
    cancel.set()
    assert (
        GeminiTranscriber(gateway, config("gemini"))
        .transcribe(STTRequest(audio), ExecutionContext(cancel=cancel))
        .cancelled
    )


def test_checkpoint_invalid_coverage_and_claim_references() -> None:
    request = transcript()
    result = OpenAISummarizer(FakeGateway(), config()).summarize(request)
    first = result.checkpoint.completed[0]
    bad = replace(result.checkpoint, completed=(replace(first, coverage=()),))
    assert (
        OpenAISummarizer(FakeGateway(), config())
        .summarize(replace(request, checkpoint=bad))
        .error_code
        == "CHECKPOINT_MISMATCH"
    )
    bad = replace(
        result.checkpoint, completed=(replace(first, claims=(SummaryClaim("bad", ("missing",)),)),)
    )
    assert (
        OpenAISummarizer(FakeGateway(), config())
        .summarize(replace(request, checkpoint=bad))
        .error_code
        == "CHECKPOINT_MISMATCH"
    )


@pytest.mark.parametrize(
    "kind,changes",
    [
        ("segment", {"segment_id": ""}),
        ("segment", {"start_ms": -1}),
        ("segment", {"end_ms": 0, "start_ms": 1}),
        ("segment", {"text": None}),
        ("segment", {"text": "\x00"}),
        ("segment", {"text": "\ud800"}),
        ("segment", {"speaker": "bad\n"}),
        ("segment", {"provenance": "invented"}),
        ("segment", {"timing_quality": "precise"}),
        ("segment", {"track_id": ""}),
        ("claim", {"text": ""}),
        ("claim", {"segment_ids": []}),
        ("claim", {"segment_ids": ("s", "s")}),
        ("claim", {"segment_ids": (None,)}),
        ("claim", {"text": "x\x00"}),
        ("claim", {"text": "\ud800"}),
        ("claim", {"status": "supported"}),
        ("claim", {"basis": "verified"}),
        ("summary", {"template": "shell"}),
        ("summary", {"segments": []}),
        ("summary", {"segments": (TranscriptSegment("s", 0, 1, "x"),) * 2}),
        ("summary", {"checkpoint": {}}),
        ("summary", {"overlap_segments": 9}),
        ("summary", {"chunk_chars": False}),
        ("summary", {"output_language": "bad\n"}),
    ],
)
def test_frozen_dto_input_boundaries(kind: str, changes: dict[str, Any]) -> None:
    value: Any = {
        "segment": TranscriptSegment("s", 0, 100, "x"),
        "claim": SummaryClaim("x", ("s",)),
        "summary": transcript(),
    }[kind]
    with pytest.raises(ProviderError):
        replace(value, **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"audio_path": "file.wav"},
        {"offset_ms": -1},
        {"language": "ko_KR"},
        {"language": 3},
    ],
)
def test_stt_request_rejects_unsupported_values(changes: dict[str, Any]) -> None:
    with pytest.raises(ProviderError):
        replace(STTRequest(Path("file.wav")), **changes)


def test_context_attestation_and_checkpoint_validation() -> None:
    with pytest.raises(ProviderError):
        ExecutionContext(cancel=False)  # type: ignore[arg-type]
    with pytest.raises(ProviderError):
        ExecutionContext(headers={"Authorization": "key\r\ninject"})
    with pytest.raises(ProviderError):
        ExecutionContext(headers=[])  # type: ignore[arg-type]
    selected = config("ollama").local_attestation
    assert selected is not None
    for changes in (
        {"artifact_sha256": "bad"},
        {"cloud_disabled": "yes"},
        {"expires_at_monotonic": float("inf")},
        {"expires_at_monotonic": "bad"},
    ):
        with pytest.raises(ProviderError):
            replace(selected, **changes)
    with pytest.raises(ProviderError):
        config(local_attestation={})
    with pytest.raises(ProviderError):
        SummaryCheckpoint("bad")
    with pytest.raises(ProviderError):
        SummaryCheckpoint("a" * 64, [])  # type: ignore[arg-type]
    with pytest.raises(ProviderError):
        ChunkSummary("chunk", (), [SegmentSpan("s", 0, 1)])  # type: ignore[arg-type]
    with pytest.raises(ProviderError):
        ProviderConfig("openai", "\ud800")


@pytest.mark.parametrize(
    "data",
    [
        None,
        [None],
        [{"text": "x"}],
        [{"text": 1, "segment_ids": ["s"]}],
        [{"text": "x", "segment_ids": []}] * 257,
    ],
)
def test_invalid_claim_array_is_safe(data: Any) -> None:
    with pytest.raises(ProviderError):
        parse_claims({"claims": data}, {"s"}, {"s": "audio"})


def test_context_only_claims_and_unresolved_basis() -> None:
    raw = {
        "claims": [
            {"text": "overlap", "segment_ids": ["context"]},
            {"text": "core", "segment_ids": ["s"], "status": ["malformed-status"]},
        ]
    }
    result = parse_claims(raw, {"s", "context"}, {"s": "unresolved", "context": "audio"}, {"s"})
    assert len(result) == 1 and result[0].basis == "model_inference"
    assert result[0].status == "uncertain"


def test_safe_gateway_codes_budget_callback_and_exact_response_bounds() -> None:
    gateway = FakeGateway()
    gateway.fail_at = 1
    gateway.error = ProviderError("CONSENT_REVOKED", outcome_known=False)
    result = OpenAISummarizer(gateway, config()).summarize(transcript())
    assert result.error_code == "CONSENT_REVOKED" and not result.outcome_known
    blocked = OpenAISummarizer(FakeGateway(), config()).summarize(
        transcript(),
        ExecutionContext(
            reservation_factory=lambda *a: (_ for _ in ()).throw(ValueError("CANARY"))
        ),
    )
    assert blocked.error_code == "BUDGET_BLOCKED"
    with pytest.raises(ProviderError, match="RESPONSE_TOO_LARGE"):
        decode("not bytes", 100)  # type: ignore[arg-type]
    with pytest.raises(ProviderError, match="INPUT_TOO_LARGE"):
        Run(config(), None).request(
            FakeGateway(), "https://example.com/a", "text", b"x" * (20 * 1024 * 1024 + 1)
        )


@pytest.mark.parametrize("missing", ["file", "extension", "nonwav", "empty"])
def test_stt_preflight_errors_are_safe_and_unsent(tmp_path: Path, missing: str) -> None:
    path = tmp_path / ("input.txt" if missing == "extension" else "input.wav")
    if missing == "nonwav" or missing == "extension":
        path.write_bytes(b"CANARY")
    elif missing == "empty":
        with wave.open(str(path), "wb") as stream:
            stream.setparams((1, 2, 16000, 0, "NONE", "none"))
    gateway = FakeGateway()
    result = OpenAITranscriber(gateway, config()).transcribe(STTRequest(path))
    assert not result.complete and not gateway.calls


def test_nonabsolute_and_hardlinked_audio_rejected(audio: Path) -> None:
    import os

    gateway = FakeGateway()
    assert (
        not OpenAITranscriber(gateway, config())
        .transcribe(STTRequest(Path("relative.wav")))
        .complete
    )
    os.link(audio, audio.with_name("hardlink.wav"))
    assert (
        OpenAITranscriber(gateway, config()).transcribe(STTRequest(audio)).error_code
        == "INPUT_INVALID"
    )
    assert not gateway.calls


@pytest.mark.parametrize(
    "response",
    [
        b"{}",
        b'{"segments":{}}',
        b'{"segments":[3]}',
        b'{"segments":[{"start":true,"end":0.1,"text":"x"}]}',
        b'{"segments":[{"start":0,"end":999,"text":"x"}]}',
    ],
)
def test_bad_timestamp_responses_do_not_become_complete(audio: Path, response: bytes) -> None:
    gateway = FakeGateway()
    gateway.response = response
    result = OpenAITranscriber(gateway, config(model="whisper-1"), timestamps=True).transcribe(
        STTRequest(audio)
    )
    assert result.error_code == "RESULT_INVALID" and not result.complete


def test_empty_speech_results_do_not_fabricate_text(audio: Path) -> None:
    gateway = FakeGateway()
    gateway.response = b'{"text":""}'
    result = OpenAITranscriber(gateway, config()).transcribe(STTRequest(audio))
    assert result.complete and not result.segments and result.processed_ms == 100
    gateway.response = b'{"text":3}'
    assert (
        OpenAITranscriber(gateway, config()).transcribe(STTRequest(audio)).error_code
        == "RESULT_INVALID"
    )
    gateway.response = b'{"segments":[]}'
    assert (
        OpenAITranscriber(gateway, config(model="whisper-1"), timestamps=True)
        .transcribe(STTRequest(audio))
        .complete
    )
    gateway.response = b'{"candidates":[{"finishReason":"STOP","content":{"parts":[{"text":""}]}}]}'
    assert GeminiTranscriber(gateway, config("gemini")).transcribe(STTRequest(audio)).complete


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"candidates": [{}, {}]},
        {"candidates": [{"finishReason": "STOP", "content": {"parts": None}}]},
        {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": 3}]}}]},
        {"candidates": [{"finishReason": "STOP"}]},
    ],
)
def test_gemini_missing_candidates_or_nontext_output_is_invalid(response: dict[str, Any]) -> None:
    with pytest.raises(ProviderError):
        stt_module.gemini_text(response)


def test_unsupported_provider_and_model_parameters_never_infer(tmp_path: Path) -> None:
    with pytest.raises(ProviderError):
        FasterWhisperProvider(tmp_path, device="auto")
    with pytest.raises(ProviderError):
        FasterWhisperProvider(tmp_path, compute_type="auto")
    with pytest.raises(ProviderError):
        GeminiTranscriber(FakeGateway(), config("openai"))
    with pytest.raises(ProviderError):
        OpenAITranscriber(FakeGateway(), config("gemini"))
    with pytest.raises(ProviderError):
        OpenAISummarizer(FakeGateway(), config("anthropic"))
    with pytest.raises(ProviderError):
        GeminiTranscriber(FakeGateway(), config("gemini", model="models/escape"))


def test_local_invalid_timing_directory_file_and_wait_cancel(tmp_path: Path, audio: Path) -> None:
    path = model_dir(tmp_path)
    invalid = SimpleNamespace(
        transcribe=lambda *a, **k: (
            iter(
                [
                    SimpleNamespace(start=0.05, end=0.1, text="first"),
                    SimpleNamespace(start=0, end=0.01, text="out of order"),
                ]
            ),
            SimpleNamespace(),
        )
    )
    adapter = FasterWhisperProvider(path, model_factory=lambda *a, **k: invalid)
    result = adapter.transcribe(STTRequest(audio))
    assert result.error_code == "RESULT_INVALID" and len(result.segments) == 1
    (path / "model.bin").unlink()
    (path / "model.bin").mkdir()
    assert FasterWhisperProvider(path).transcribe(STTRequest(audio)).error_code == "MODEL_MISSING"
    (path / "model.bin").rmdir()
    (path / "model.bin").write_bytes(b"fake")
    context = ExecutionContext()

    class Waiting:
        def acquire(self, timeout: float) -> bool:
            context.cancel.set()
            return False

        def release(self) -> None:
            raise AssertionError("unacquired lock released")

    adapter = FasterWhisperProvider(path)
    adapter._lock = Waiting()  # type: ignore[assignment]
    assert adapter.transcribe(STTRequest(audio), context).cancelled


def test_speaker_and_timing_changes_invalidate_summary_checkpoint() -> None:
    request = transcript()
    adapter = OpenAISummarizer(FakeGateway(), config())
    result = adapter.summarize(request)
    changed = replace(
        request,
        segments=(replace(request.segments[0], speaker="speaker-2"),),
        checkpoint=result.checkpoint,
    )
    assert adapter.summarize(changed).error_code == "CHECKPOINT_MISMATCH"


def test_checkpoint_duplicate_or_unknown_chunk_is_rejected() -> None:
    request = transcript()
    adapter = OpenAISummarizer(FakeGateway(), config())
    checkpoint = adapter.summarize(request).checkpoint
    first = checkpoint.completed[0]
    for completed in ((first, first), (replace(first, chunk_id="unknown"),)):
        result = adapter.summarize(
            replace(request, checkpoint=replace(checkpoint, completed=completed))
        )
        assert result.error_code == "CHECKPOINT_MISMATCH"


def test_metadata_that_cannot_fit_is_not_silently_cut() -> None:
    request = SummaryRequest(
        "rev", (TranscriptSegment("s" * 128, 0, 1, "x", speaker="a" * 128, track_id="b" * 128),)
    )
    with pytest.raises(ProviderError, match="CONTEXT_LIMIT"):
        plan_summary(request, config(context_window_tokens=3072, max_output_tokens=512))


def test_final_synthesis_failure_keeps_all_core_results() -> None:
    class LargeClaims(FakeGateway):
        def request(self, *args: Any, **kwargs: Any) -> bytes:
            original = super().request(*args, **kwargs)
            value = json.loads(original)
            text = json.loads(value["output"][0]["content"][0]["text"])
            for claim in text["claims"]:
                claim["text"] = "x" * 6000
            value["output"][0]["content"][0]["text"] = json.dumps(text)
            return encode(value)

    result = OpenAISummarizer(LargeClaims(), config()).summarize(transcript(6, 500))
    assert result.error_code == "CONTEXT_LIMIT" and not result.complete
    assert result.coverage and not result.missing and result.checkpoint.completed


@pytest.mark.parametrize(
    "provenance,refs", [("user_assertion", ("s0",)), ("unresolved", ("s0",)), ("audio", ())]
)
def test_resume_cannot_promote_cached_claim_evidence(
    provenance: str, refs: tuple[str, ...]
) -> None:
    request = SummaryRequest(
        "immutable", (TranscriptSegment("s0", 0, 100, "Original", provenance=provenance),)
    )
    gateway = FakeGateway()
    adapter = OpenAISummarizer(gateway, config())
    original = adapter.summarize(request)
    item = original.checkpoint.completed[0]
    forged = replace(item, claims=(SummaryClaim("forged", refs, "uncertain", "transcript"),))
    checkpoint = replace(original.checkpoint, completed=(forged,))
    before = len(gateway.calls)
    result = adapter.summarize(replace(request, checkpoint=checkpoint))
    assert result.error_code == "CHECKPOINT_MISMATCH" and not result.complete
    assert not result.claims and len(gateway.calls) == before
    assert not result.coverage and result.missing


@pytest.mark.parametrize("broken_str", [False, True])
def test_backend_error_classification_never_exposes_exception(
    audio: Path, tmp_path: Path, broken_str: bool
) -> None:
    class BackendError(Exception):
        def __str__(self) -> str:
            if broken_str:
                raise RuntimeError("SECRET-BROKEN-EXCEPTION")
            return "CUDA out of memory SECRET-RAW-EXCEPTION"

    def infer(*args: Any, **kwargs: Any) -> Any:
        raise BackendError()

    adapter = FasterWhisperProvider(
        model_dir(tmp_path), model_factory=lambda *args, **kwargs: SimpleNamespace(transcribe=infer)
    )
    result = adapter.transcribe(STTRequest(audio))
    assert not result.complete
    assert result.error_code == ("PROVIDER_FAILED" if broken_str else "RESOURCE_EXHAUSTED")
    assert "SECRET" not in repr(result)


def test_local_whisper_receives_decoded_16k_mono_float32_not_file_bytes(tmp_path: Path) -> None:
    # L02: no PyAV decoder is distributed. 0.25 s of 48 kHz stereo L=R=4096 must
    # arrive as 4000 float32 samples of 0.125; the source WAV stays unchanged.
    import numpy as np

    path = tmp_path / "clip.wav"
    with wave.open(str(path), "wb") as stream:
        stream.setparams((2, 2, 48_000, 0, "NONE", "not compressed"))
        stream.writeframes((4_096).to_bytes(2, "little", signed=True) * 2 * 12_000)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    received: list[Any] = []

    def infer(audio: Any, **kwargs: Any) -> Any:
        received.append((audio, kwargs))
        return iter([SimpleNamespace(start=0.0, end=0.25, text="ok")]), SimpleNamespace()

    adapter = FasterWhisperProvider(
        model_dir(tmp_path), model_factory=lambda *a, **k: SimpleNamespace(transcribe=infer)
    )
    result = adapter.transcribe(STTRequest(path))
    assert result.complete and result.processed_ms == 250
    samples, kwargs = received[0]
    assert isinstance(samples, np.ndarray) and samples.dtype == np.float32
    assert samples.shape == (4_000,)
    assert float(np.max(np.abs(samples[800:-800].astype(np.float64) - 0.125))) <= 1e-7
    assert kwargs == {"language": None, "vad_filter": False, "word_timestamps": False}
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


@pytest.mark.parametrize("rate", [16_000, 48_000])
@pytest.mark.parametrize("stop", ["cancel", "deadline"])
def test_local_whisper_never_starts_inference_after_preprocess_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rate: int, stop: str
) -> None:
    # L02-STT-01: a cancel/deadline reached exactly when conversion finishes (after
    # the last block check) must not reach the model.
    path = tmp_path / f"clip-{rate}.wav"
    with wave.open(str(path), "wb") as stream:
        stream.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        stream.writeframes(b"\x00\x08" * (rate // 10))
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    cancel = threading.Event()
    original = stt_module.prepare_whisper_audio
    clock = [0.0]
    import recoryn.providers._common as provider_common

    # Only the provider deadline clock is fake; threading and pytest keep real time.
    monkeypatch.setattr(provider_common, "time", SimpleNamespace(monotonic=lambda: clock[0]))

    def prepared_then_stopped(*args: Any, **kwargs: Any) -> Any:
        result = original(*args, **kwargs)
        if stop == "cancel":
            cancel.set()
        else:
            clock[0] = 10_000.0
        return result

    monkeypatch.setattr(stt_module, "prepare_whisper_audio", prepared_then_stopped)
    calls: list[object] = []

    def infer(*args: Any, **kwargs: Any) -> Any:
        calls.append(args)
        return iter([SimpleNamespace(start=0.0, end=0.1, text="late")]), SimpleNamespace()

    adapter = FasterWhisperProvider(
        model_dir(tmp_path), model_factory=lambda *a, **k: SimpleNamespace(transcribe=infer)
    )
    result = adapter.transcribe(STTRequest(path), ExecutionContext(cancel=cancel))
    assert calls == []
    assert result.error_code == ("CANCELLED" if stop == "cancel" else "TIMEOUT")
    assert not result.complete and not result.segments
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_local_whisper_without_numpy_reports_dependency_missing(
    tmp_path: Path, audio: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    original = stt_module.importlib.import_module

    def without_numpy(name: str) -> Any:
        calls.append(name)
        if name == "numpy":
            raise ImportError("CANARY")
        return original(name)

    monkeypatch.setattr(stt_module.importlib, "import_module", without_numpy)
    model = SimpleNamespace(transcribe=lambda *a, **k: pytest.fail("model must not run"))
    adapter = FasterWhisperProvider(model_dir(tmp_path), model_factory=lambda *a, **k: model)
    result = adapter.transcribe(STTRequest(audio))
    assert result.error_code == "DEPENDENCY_MISSING" and "numpy" in calls
    assert "CANARY" not in repr(result)
