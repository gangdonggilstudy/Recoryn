"""D90/S63: independent literals and fake-observation traces, no native or I/O."""

from __future__ import annotations

import itertools
import json
import socket
import sys
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from recoryn.providers import (
    FactIdentity,
    MetadataDescriptor,
    ObservationOutcome,
    ObservationState,
    ProviderEvidenceLevel,
    ProviderObservation,
    describe,
    facts,
    parse_observation,
)
from recoryn.providers.contracts import ProviderConfig
from tests.property.test_provider_facts_case_space import execution_audit as execution_audit

pytestmark = pytest.mark.unit
EXECUTED: list[str] = []
PROVIDERS = ("faster_whisper", "openai", "anthropic", "gemini", "ollama")
SUPPORT = {
    "faster_whisper": (True, False),
    "openai": (True, True),
    "anthropic": (False, True),
    "gemini": (True, True),
    "ollama": (False, True),
}
D_CASES = [
    pytest.param(f"GS04-D-{n:03d}", *row, id=f"GS04-D-{n:03d}")
    for n, row in enumerate(
        itertools.product(
            PROVIDERS,
            ("stt", "summary"),
            ("CPU_ONLY", "GPU_ONLY", "GPU_WITH_CPU_FALLBACK_ALLOWED"),
            ("UNKNOWN", "OBSERVED-empty", "OBSERVED-GPU"),
        ),
        1,
    )
]
S_CASES = [
    pytest.param(f"GS04-S-{n:03d}", *row, id=f"GS04-S-{n:03d}")
    for n, row in enumerate(itertools.product(("unknown", "true", "false"), range(1, 22)), 1)
]


def no_io(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record forbidden calls without throwing an unrelated mutant failure."""
    calls: list[str] = []
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: calls.append("dns") or [])
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: calls.append("socket"))
    monkeypatch.setattr(socket, "socket", lambda *a, **k: calls.append("socket"))
    from recoryn.security import CredentialVault

    monkeypatch.setattr(CredentialVault, "get", lambda *a, **k: calls.append("vault"))
    from recoryn.models import resources

    monkeypatch.setattr(resources, "probe_gpus", lambda: calls.append("gpu") or ("UNKNOWN", ()))
    return calls


def identity() -> FactIdentity:
    return FactIdentity(
        "ollama",
        "summary",
        "http://127.0.0.1:12345/fixture",
        "chosen",
        inference_endpoint="http://127.0.0.1:12345/infer",
        session_generation="run-1",
    )


def body(found: bool = True) -> bytes:
    return json.dumps({"items": [{"name": "chosen" if found else "other"}], "all": True}).encode()


def descriptor() -> MetadataDescriptor:
    return MetadataDescriptor("items", "name", "all")


@pytest.mark.parametrize("case_id,provider,kind,policy,resource", D_CASES)
def test_declarations_match_literals_and_adapters(
    case_id: str,
    provider: str,
    kind: str,
    policy: str,
    resource: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    EXECUTED.append(case_id)
    calls = no_io(monkeypatch)
    before = {
        name
        for name in sys.modules
        if name.split(".")[0] in {"faster_whisper", "ctranslate2", "torch"}
    }
    declaration = describe(provider, kind)
    caps = declaration.capabilities
    supported = SUPPORT[provider][0 if kind == "stt" else 1]
    assert declaration.level.value == "DECLARED"
    assert declaration.supported is supported
    assert caps.actual_service_status == "NOT_RUN"
    assert (
        caps.transcription,
        caps.summarization,
        caps.segment_timestamps,
        caps.audio_formats,
    ) == (
        supported and kind == "stt",
        supported and kind == "summary",
        supported and kind == "stt" and provider == "faster_whisper",
        ("wav",) if supported and kind == "stt" else (),
    )
    if supported:
        from recoryn.summarization import (
            AnthropicSummarizer,
            GeminiSummarizer,
            OllamaSummarizer,
            OpenAISummarizer,
        )
        from recoryn.transcription import (
            FasterWhisperProvider,
            GeminiTranscriber,
            OpenAITranscriber,
        )

        adapters = {
            ("openai", "stt"): OpenAITranscriber,
            ("gemini", "stt"): GeminiTranscriber,
            ("ollama", "summary"): OllamaSummarizer,
            ("openai", "summary"): OpenAISummarizer,
            ("anthropic", "summary"): AnthropicSummarizer,
            ("gemini", "summary"): GeminiSummarizer,
        }
        instance = (
            FasterWhisperProvider(Path("synthetic"))
            if provider == "faster_whisper"
            else (
                adapters[provider, kind](
                    SimpleNamespace(request=lambda *a, **k: calls.append("gateway") or b""),
                    ProviderConfig(provider, "fixture"),
                )
            )
        )
        assert caps == instance.capabilities()
        if provider != "faster_whisper":
            for model in ("fixture", "alternate.model-2"):
                expected_url = {
                    ("openai", "stt"): "https://api.openai.com/v1/audio/transcriptions",
                    ("openai", "summary"): "https://api.openai.com/v1/responses",
                    ("anthropic", "summary"): "https://api.anthropic.com/v1/messages",
                    ("ollama", "summary"): "http://127.0.0.1:11434/api/chat",
                }.get(
                    (provider, kind),
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                )
                actual_adapter = adapters[provider, kind](
                    SimpleNamespace(request=lambda *a, **k: calls.append("gateway") or b""),
                    ProviderConfig(provider, model),
                )
                assert actual_adapter.endpoint == expected_url
                assert facts.default_endpoint(provider, kind, model) == expected_url
    if provider == "faster_whisper" or not supported:
        assert facts.default_endpoint(provider, kind, "fixture") is None
    # Resource observation strings (same spelling), objects and policy names are not evidence.
    for wrong in (resource.split("-")[0], policy, object()):
        with pytest.raises(ValueError, match="INVALID_PROVIDER_EVIDENCE"):
            replace(declaration, level=wrong)
    assert not facts.PRODUCTION_ROUTES
    with pytest.raises(TypeError):
        facts.PRODUCTION_ROUTES["fixture"] = descriptor()
    with pytest.raises(FrozenInstanceError):
        declaration.supported = False
    assert calls == []
    assert {
        name
        for name in sys.modules
        if name.split(".")[0] in {"faster_whisper", "ctranslate2", "torch"}
    } == before


@pytest.mark.parametrize("case_id,prior,event", S_CASES)
def test_observation_lifetime(
    case_id: str,
    prior: str,
    event: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    EXECUTED.append(case_id)
    calls = no_io(monkeypatch)
    clock = [1000.0]
    state = ObservationState(clock=lambda: clock[0])
    key = identity()
    state.bind(key)
    if prior != "unknown":
        state.accept(
            key,
            parse_observation(body(prior == "true"), descriptor(), "chosen"),
            observed_at=1700000000,
        )
    expected = "UNKNOWN"
    listed: bool | None = None
    if event in (1, 2):
        raw = body(event == 1)
        raw += b" " * (1048576 - len(raw))
        state.accept(key, parse_observation(raw, descriptor(), "chosen"), observed_at=1700000000)
        expected, listed = "OBSERVED", event == 1
    elif event in (3, 17, 18):
        outcome = {
            3: ObservationOutcome.TRANSPORT_FAILED,
            17: ObservationOutcome.CANCELLED,
            18: ObservationOutcome.UNSUPPORTED,
        }[event]
        state.accept(
            key,
            parse_observation(body(), descriptor(), "chosen", outcome=outcome),
            observed_at=1700000000,
        )
    elif event == 4:
        malformed = [
            b"",
            b"\xff",
            b"[]",
            b'{"all":true,"items":null}',
            b'{"all":false,"items":[]}',
            b'{"all":1,"items":[]}',
            b'{"all":"yes","items":[]}',
            b'{"all":true,"items":[null]}',
            b'{"all":true,"items":[{"name":""}]}',
            b'{"all":true,"items":[{"name":1}]}',
            b'{"all":true,"items":[{"name":"x"},{"name":"x"}]}',
            b'{"all":true,"items":[],"items":[]}',
            b'{"all":NaN,"items":[]}',
            b"[" * 1100,
            json.dumps({"all": True, "items": [{"name": "a" * 257}]}).encode(),
        ]
        for raw in malformed:
            result = parse_observation(raw, descriptor(), "chosen")
            assert result.level.value == "UNKNOWN"
            state.accept(key, result, observed_at=1700000000)
    elif event in (5, 6, 7):
        clock[0] += {5: 299.999, 6: 300, 7: 300.001}[event]
        if event == 5 and prior != "unknown":
            expected, listed = "OBSERVED", prior == "true"
    elif 8 <= event <= 15:
        field, value = {
            8: ("endpoint", "http://127.0.0.1:23456/fixture"),
            9: ("inference_endpoint", "http://127.0.0.1:12345/else"),
            10: ("model", "new"),
            11: ("adapter_revision", "2"),
            12: ("api_revision", "2"),
            13: ("route_revision", "2"),
            14: ("credential_revision", 1),
            15: ("consent_epoch", 1),
        }[event]
        state.bind(replace(key, **{field: value}))
        assert not state.accept(
            key, parse_observation(body(), descriptor(), "chosen"), observed_at=1700000000
        )  # late reply cannot follow another identity
    elif event == 16:
        state.bind(replace(key, session_generation="run-2"))
        assert state.snapshot().observation.level.value == "UNKNOWN"
        assert not state.accept(
            key, parse_observation(body(), descriptor(), "chosen"), observed_at=1700000000
        )
        state = ObservationState(clock=lambda: clock[0])
        state.bind(replace(key, session_generation="run-2"))
    elif event == 19:
        state.accept(
            key,
            parse_observation(body() + b" " * 1048576, descriptor(), "chosen"),
            observed_at=1700000000,
        )
    elif event == 20:
        clock[0] = 999.0
        if prior == "unknown":
            assert state.snapshot().observation.level.value == "UNKNOWN"
    else:
        for bad in (float("nan"), float("inf"), -1, True, "bad", 1e300):
            state.accept(key, parse_observation(body(), descriptor(), "chosen"), observed_at=bad)
            assert state.snapshot().observation.level.value == "UNKNOWN"
        clock[0] = float("nan")
        assert not state.accept(
            key, parse_observation(body(), descriptor(), "chosen"), observed_at=1700000000
        )
        clock[0] = 1000.0
        state.accept(key, parse_observation(body(), descriptor(), "chosen"), observed_at=1700000000)
        clock[0] = float("nan")
        assert state.snapshot().observation.level.value == "UNKNOWN"
        for wrong in ("OBSERVED", object()):
            with pytest.raises(ValueError):
                ProviderObservation(level=wrong)
        for kwargs in (
            {"reason": "PRIVATE"},
            {"level": ProviderEvidenceLevel.DECLARED},
            {"level": ProviderEvidenceLevel.OBSERVED},
        ):
            with pytest.raises(ValueError):
                ProviderObservation(**kwargs)
        with pytest.raises(ValueError):
            state.bind(object())
        with pytest.raises(ValueError):
            state.accept(key, object(), observed_at=0)
        for args in (("", "name", "all"), ("items", "items", "all"), (None, "name", "all")):
            with pytest.raises(ValueError):
                MetadataDescriptor(*args)
        assert parse_observation(b"", None, "chosen").level.value == "UNKNOWN"
        assert parse_observation("bad", descriptor(), "chosen").level.value == "UNKNOWN"
        assert (
            parse_observation(b"", descriptor(), "chosen", outcome="bad").level.value == "UNKNOWN"
        )
        for args in (("unknown", "summary"), ("openai", "unknown")):
            with pytest.raises(Exception, match="CAPABILITY_UNSUPPORTED"):
                describe(*args)
            assert facts.default_endpoint(*args, "fixture") is None
        assert facts.default_endpoint("gemini", "summary", "not a model") is None
    result = state.snapshot().observation
    assert result.level.value == expected
    assert result.selected_model_listed is listed
    assert describe("ollama", "summary").supported is True
    assert describe("ollama", "summary").capabilities.actual_service_status == "NOT_RUN"
    assert calls == []
