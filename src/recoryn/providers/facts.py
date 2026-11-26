"""Display-only provider facts. No transport, credentials, SDK or persistent store."""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, cast

from .contracts import GatewayLike, ProviderCapabilities, ProviderConfig, ProviderError

PRODUCTION_ROUTES: MappingProxyType[str, MetadataDescriptor] = MappingProxyType({})
MAX_RESPONSE_BYTES = 1024 * 1024
TTL_SECONDS = 300


class ProviderEvidenceLevel(Enum):
    DECLARED = "DECLARED"
    OBSERVED = "OBSERVED"
    UNKNOWN = "UNKNOWN"


class ObservationOutcome(Enum):
    RESPONSE = "RESPONSE"
    TRANSPORT_FAILED = "TRANSPORT_FAILED"
    CANCELLED = "CANCELLED"
    UNSUPPORTED = "UNSUPPORTED"


_SUPPORT = {
    "faster_whisper": frozenset({"stt"}),
    "openai": frozenset({"stt", "summary"}),
    "anthropic": frozenset({"summary"}),
    "gemini": frozenset({"stt", "summary"}),
    "ollama": frozenset({"summary"}),
}


@dataclass(frozen=True)
class ProviderDeclaration:
    capabilities: ProviderCapabilities
    kind: str
    supported: bool
    level: ProviderEvidenceLevel = ProviderEvidenceLevel.DECLARED

    def __post_init__(self) -> None:
        if type(self.level) is not ProviderEvidenceLevel:
            raise ValueError("INVALID_PROVIDER_EVIDENCE")


def describe(provider_id: str, kind: str) -> ProviderDeclaration:
    """Static table; the D rows also compare every supported pair to its adapter."""
    if provider_id not in _SUPPORT or kind not in {"stt", "summary"}:
        raise ProviderError("CAPABILITY_UNSUPPORTED")
    supported = kind in _SUPPORT[provider_id]
    audio = kind == "stt" and supported
    caps = ProviderCapabilities(
        provider_id,
        transcription=audio,
        summarization=kind == "summary" and supported,
        segment_timestamps=audio and provider_id == "faster_whisper",
        audio_formats=("wav",) if audio else (),
    )
    return ProviderDeclaration(caps, kind, supported)


def default_endpoint(provider_id: str, kind: str, model: str) -> str | None:
    """Derive the inference default from lazy adapters, never from a second URL table."""
    if provider_id == "faster_whisper" or kind not in _SUPPORT.get(provider_id, ()):
        return None
    from recoryn.summarization import (
        AnthropicSummarizer,
        GeminiSummarizer,
        OllamaSummarizer,
        OpenAISummarizer,
    )
    from recoryn.transcription import GeminiTranscriber, OpenAITranscriber

    factories: dict[tuple[str, str], Callable[[GatewayLike, ProviderConfig], Any]] = {
        ("openai", "stt"): OpenAITranscriber,
        ("gemini", "stt"): GeminiTranscriber,
        ("openai", "summary"): OpenAISummarizer,
        ("anthropic", "summary"): AnthropicSummarizer,
        ("gemini", "summary"): GeminiSummarizer,
        ("ollama", "summary"): OllamaSummarizer,
    }
    try:
        config = ProviderConfig(provider_id, model or "unconfigured")
        adapter = factories[provider_id, kind](cast(GatewayLike, None), config)
        return str(adapter.endpoint)
    except ProviderError:
        return None


@dataclass(frozen=True)
class FactIdentity:
    provider_id: str
    kind: str
    endpoint: str
    model: str
    inference_endpoint: str = ""
    adapter_revision: str = "1"
    api_revision: str = "1"
    route_revision: str = "1"
    credential_revision: int = 0
    consent_epoch: int = 0
    session_generation: str = ""


@dataclass(frozen=True)
class MetadataDescriptor:
    """A caller-supplied fixture schema, never a registered vendor route."""

    list_key: str
    id_key: str
    complete_key: str

    def __post_init__(self) -> None:
        keys = (self.list_key, self.id_key, self.complete_key)
        if any(type(k) is not str or not k or len(k) > 128 for k in keys):
            raise ValueError("INVALID_METADATA_DESCRIPTOR")
        if len(set(keys)) != 3:
            raise ValueError("INVALID_METADATA_DESCRIPTOR")


@dataclass(frozen=True)
class ProviderObservation:
    level: ProviderEvidenceLevel = ProviderEvidenceLevel.UNKNOWN
    metadata_response_received: bool | None = None
    selected_model_listed: bool | None = None
    reason: str = "NO_OBSERVATION"

    def __post_init__(self) -> None:
        if type(self.level) is not ProviderEvidenceLevel:
            raise ValueError("INVALID_PROVIDER_EVIDENCE")
        if self.level is ProviderEvidenceLevel.OBSERVED:
            valid = (
                self.metadata_response_received is True
                and type(self.selected_model_listed) is bool
                and self.reason == "OK"
            )
        else:
            valid = (
                self.level is ProviderEvidenceLevel.UNKNOWN
                and self.metadata_response_received is None
                and self.selected_model_listed is None
                and self.reason
                in {
                    "NO_OBSERVATION",
                    "INVALID_RESPONSE",
                    "TRANSPORT_FAILED",
                    "CANCELLED",
                    "UNSUPPORTED",
                    "EXPIRED",
                    "INVALID_TIME",
                }
            )
        if not valid:
            raise ValueError("INVALID_PROVIDER_OBSERVATION")


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("INVALID_RESPONSE")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise ValueError("INVALID_RESPONSE")


def parse_observation(
    body: bytes,
    descriptor: MetadataDescriptor | None,
    model: str,
    *,
    outcome: ObservationOutcome = ObservationOutcome.RESPONSE,
    raw_error: object = None,
    redirect_url: object = None,
) -> ProviderObservation:
    """Reduce fake input to two booleans; discard raw errors, URLs and other models."""
    if type(outcome) is not ObservationOutcome:
        return ProviderObservation(reason="INVALID_RESPONSE")
    if outcome is not ObservationOutcome.RESPONSE:
        return ProviderObservation(reason=outcome.value)
    if type(descriptor) is not MetadataDescriptor:
        return ProviderObservation(reason="UNSUPPORTED")
    if type(body) is not bytes or len(body) > MAX_RESPONSE_BYTES:
        return ProviderObservation(reason="INVALID_RESPONSE")
    try:
        value = json.loads(
            body.decode("utf-8"), object_pairs_hook=_unique, parse_constant=_constant
        )
        if type(value) is not dict or value.get(descriptor.complete_key) is not True:
            raise ValueError("INVALID_RESPONSE")
        rows = value.get(descriptor.list_key)
        if type(rows) is not list:
            raise ValueError("INVALID_RESPONSE")
        ids: set[str] = set()
        for row in rows:
            name = row.get(descriptor.id_key) if type(row) is dict else None
            if type(name) is not str or not name or len(name) > 256 or name in ids:
                raise ValueError("INVALID_RESPONSE")
            ids.add(name)
        return ProviderObservation(ProviderEvidenceLevel.OBSERVED, True, model in ids, "OK")
    except (ValueError, RecursionError, UnicodeError):
        return ProviderObservation(reason="INVALID_RESPONSE")


@dataclass(frozen=True)
class ProviderFactSnapshot:
    identity: FactIdentity | None
    observation: ProviderObservation
    observed_at: float | None = None


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


class ObservationState:
    """Memory-only fake-observation lifetime. Reading never requests anything."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._identity: FactIdentity | None = None
        self._observation = ProviderObservation()
        self._stamp: float | None = None
        self._observed_at: float | None = None

    def bind(self, identity: FactIdentity) -> None:
        if type(identity) is not FactIdentity:
            raise ValueError("INVALID_PROVIDER_IDENTITY")
        if identity != self._identity:
            self._identity = identity
            self.invalidate()

    def invalidate(self, reason: str = "NO_OBSERVATION") -> None:
        self._observation = ProviderObservation(reason=reason)
        self._stamp = self._observed_at = None

    def accept(
        self, identity: FactIdentity, observation: ProviderObservation, *, observed_at: float
    ) -> bool:
        if type(observation) is not ProviderObservation:
            raise ValueError("INVALID_PROVIDER_OBSERVATION")
        if identity != self._identity:
            return False
        now = self._clock()
        if not _finite(now) or not _finite(observed_at) or not 0 <= observed_at <= 253402300799:
            self.invalidate("INVALID_TIME")
            return False
        self._observation = observation
        self._stamp, self._observed_at = now, observed_at
        return observation.level is ProviderEvidenceLevel.OBSERVED

    def snapshot(self) -> ProviderFactSnapshot:
        if self._observation.level is ProviderEvidenceLevel.OBSERVED:
            now = self._clock()
            assert self._stamp is not None
            if not _finite(now) or now < self._stamp:
                self.invalidate("INVALID_TIME")
            elif now - self._stamp >= TTL_SECONDS:
                self.invalidate("EXPIRED")
        return ProviderFactSnapshot(self._identity, self._observation, self._observed_at)
