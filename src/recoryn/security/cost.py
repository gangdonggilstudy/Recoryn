"""Immutable request/price facts and integer upper bounds. No network or disk I/O."""

from __future__ import annotations

import base64
import io
import json
import math
import re
import wave
from dataclasses import asdict, dataclass, field
from email import policy as email_policy
from email.parser import BytesParser
from typing import Any
from urllib.parse import urlsplit

from ._core import SecurityError, canonical, digest, endpoint, identifier

MAX = 2**63 - 1
MAX_BODY = 20 * 1024 * 1024
COST_CODES = frozenset(
    {
        "COST_PRICE_UNKNOWN",
        "COST_PRICE_EXPIRED",
        "COST_BOUND_UNVERIFIED",
        "COST_CAP_REQUIRED",
        "COST_CAP_EXCEEDED",
        "COST_REQUEST_INVALID",
        "COST_AMOUNT_OVERFLOW",
        "COST_QUOTE_MISMATCH",
        "COST_QUOTE_EXPIRED",
        "COST_CURRENCY_MISMATCH",
        "COST_PERIOD_CHANGED",
        "COST_LEGACY_UNSCOPED",
        "COST_UNRESOLVED_EXPOSURE",
        "COST_CLOCK_INVALID",
        "COST_PLAN_UNDERESTIMATED",
    }
)


def integer(value: object, *, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= MAX:
        raise SecurityError("COST_REQUEST_INVALID")
    return value


def input_size(value: object) -> int:
    size = integer(value)
    if size > MAX_BODY:
        raise SecurityError("COST_REQUEST_INVALID")
    return size


def currency(value: str) -> str:
    if type(value) is not str or not re.fullmatch(r"[A-Z]{3}", value):
        raise SecurityError("COST_CURRENCY_MISMATCH")
    return value


def clock_value(value: float) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise SecurityError("COST_CLOCK_INVALID")
    return float(value)


def cost_headers(headers: dict[str, str] | None) -> tuple[tuple[str, str], ...]:
    # Credential/header values outside this closed set never enter a quote or DB.
    result: dict[str, str] = {}
    for key, value in (headers or {}).items():
        if type(key) is not str:
            raise SecurityError("COST_REQUEST_INVALID")
        name = key.lower()
        if name not in {"content-type", "anthropic-version"}:
            continue
        if (
            name in result
            or type(value) is not str
            or len(value) > 256
            or "\r" in value
            or "\n" in value
        ):
            raise SecurityError("COST_REQUEST_INVALID")
        result[name] = value
    return tuple(sorted(result.items()))


def wire_api_version(provider: str, target: str, headers: dict[str, str] | None) -> str:
    if provider == "anthropic":
        return dict(cost_headers(headers)).get("anthropic-version", "unversioned")
    part = urlsplit(target).path.strip("/").split("/", 1)[0]
    return part if re.fullmatch(r"v\d+(?:beta\d*)?", part) else "unversioned"


@dataclass(frozen=True)
class CostRequest:
    provider_id: str
    endpoint: str
    model_revision: str
    api_version: str
    operation: str
    data_type: str
    body: bytes = field(repr=False)
    headers: tuple[tuple[str, str], ...] = ()
    body_sha256: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        identifier(self.provider_id)
        identifier(self.data_type)
        if (
            type(self.operation) is not str
            or endpoint(self.endpoint).url != self.endpoint
            or self.operation
            not in {
                "stt",
                "summary",
                "diarization",
            }
        ):
            raise SecurityError("COST_REQUEST_INVALID")
        for value in (self.model_revision, self.api_version):
            if type(value) is not str or not value or len(value) > 256:
                raise SecurityError("COST_REQUEST_INVALID")
        if type(self.body) is not bytes or not self.body:
            raise SecurityError("COST_REQUEST_INVALID")
        input_size(len(self.body))
        try:
            valid_headers = type(self.headers) is tuple and self.headers == cost_headers(
                dict(self.headers)
            )
        except (ValueError, TypeError, AttributeError):
            valid_headers = False
        if not valid_headers:
            raise SecurityError("COST_REQUEST_INVALID")
        object.__setattr__(self, "body_sha256", digest(self.body))

    @property
    def key(self) -> tuple[str, str, str, str, str]:
        return (
            self.provider_id,
            self.endpoint,
            self.model_revision,
            self.api_version,
            self.operation,
        )

    def metadata(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "endpoint": self.endpoint,
            "model_revision": self.model_revision,
            "api_version": self.api_version,
            "operation": self.operation,
            "data_type": self.data_type,
            "headers": self.headers,
            "body_sha256": self.body_sha256,
            "byte_length": len(self.body),
        }

    @property
    def fingerprint(self) -> str:
        return digest(canonical(self.metadata()))


@dataclass(frozen=True)
class CostPolicy:
    mode: str
    currency: str
    period_start_utc: int
    period_end_utc: int
    cap: int
    limit: int
    policy_version: int
    catalog_digest: str
    general_acknowledged: bool = False

    def __post_init__(self) -> None:
        if (
            type(self.mode) is not str
            or self.mode not in {"strict", "general"}
            or type(self.general_acknowledged) is not bool
        ):
            raise SecurityError("COST_REQUEST_INVALID")
        currency(self.currency)
        for value in (self.period_start_utc, self.period_end_utc, self.cap, self.limit):
            integer(value)
        integer(self.policy_version, minimum=1)
        if (
            self.period_end_utc <= self.period_start_utc
            or type(self.catalog_digest) is not str
            or not re.fullmatch(r"[0-9a-f]{64}", self.catalog_digest)
        ):
            raise SecurityError("COST_REQUEST_INVALID")

    @property
    def fingerprint(self) -> str:
        return digest(canonical(asdict(self)))


@dataclass(frozen=True)
class PriceEntry:
    provider_id: str
    endpoint: str
    model_revision: str
    api_version: str
    operation: str
    currency: str
    profile_id: str
    wire_protocol: str
    bound_kind: str
    price_as_of_utc: int | None
    valid_from_utc: int | None
    valid_until_utc: int | None
    source_url: str
    source_sha256: str
    acquired_utc: int
    review_id: str
    input_numerator: int = 0
    input_denominator: int = 1
    output_numerator: int = 0
    output_denominator: int = 1
    fixed_fee: int = 0
    input_overhead: int = 0
    max_input: int = MAX_BODY
    max_output: int = 131072

    def __post_init__(self) -> None:
        identifier(self.provider_id)
        endpoint(self.endpoint)
        currency(self.currency)
        for metadata in (
            self.model_revision,
            self.api_version,
            self.profile_id,
            self.review_id,
            self.wire_protocol,
        ):
            if type(metadata) is not str or not metadata or len(metadata) > 256:
                raise SecurityError("COST_REQUEST_INVALID")
        if (
            type(self.operation) is not str
            or type(self.bound_kind) is not str
            or self.operation not in {"stt", "summary", "diarization"}
            or self.bound_kind
            not in {
                "text_bytes",
                "audio_seconds",
                "unverified",
            }
        ):
            raise SecurityError("COST_REQUEST_INVALID")
        for value in (
            self.input_numerator,
            self.output_numerator,
            self.fixed_fee,
            self.input_overhead,
            self.max_input,
            self.acquired_utc,
        ):
            integer(value)
        for value in (self.input_denominator, self.output_denominator, self.max_output):
            integer(value, minimum=1)
        for timestamp in (self.price_as_of_utc, self.valid_from_utc, self.valid_until_utc):
            if timestamp is not None:
                integer(timestamp)
        times = (self.price_as_of_utc, self.valid_from_utc, self.valid_until_utc)
        if any(v is None for v in times) and not all(v is None for v in times):
            raise SecurityError("COST_REQUEST_INVALID")
        if (
            self.valid_from_utc is not None
            and self.valid_until_utc is not None
            and self.valid_from_utc >= self.valid_until_utc
        ):
            raise SecurityError("COST_REQUEST_INVALID")
        if (
            type(self.source_url) is not str
            or not self.source_url.startswith("https://")
            or type(self.source_sha256) is not str
            or not re.fullmatch(r"[0-9a-f]{64}", self.source_sha256)
            or not self.review_id
            or not self.profile_id
        ):
            raise SecurityError("COST_REQUEST_INVALID")

    @property
    def key(self) -> tuple[str, str, str, str, str]:
        return (
            self.provider_id,
            self.endpoint,
            self.model_revision,
            self.api_version,
            self.operation,
        )


@dataclass(frozen=True)
class CostCatalog:
    entries: tuple[PriceEntry, ...]

    def __post_init__(self) -> None:
        if (
            type(self.entries) is not tuple
            or any(type(e) is not PriceEntry for e in self.entries)
            or len({e.key for e in self.entries}) != len(self.entries)
        ):
            raise SecurityError("COST_REQUEST_INVALID")

    @property
    def sha256(self) -> str:
        return digest(canonical([asdict(e) for e in sorted(self.entries, key=lambda e: e.key)]))

    def find(self, request: CostRequest) -> PriceEntry | None:
        return next((e for e in self.entries if e.key == request.key), None)


@dataclass(frozen=True)
class WireFacts:
    input_bytes: int
    output_limit: int | None
    audio_frames: int | None = None
    sample_rate: int | None = None


def _json(body: bytes) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate field")
            result[key] = value
        return result

    value = json.loads(
        body, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError())
    )
    if type(value) is not dict:
        raise ValueError
    return value


def _audio(payload: bytes) -> tuple[int, int]:
    if (
        payload[:4] != b"RIFF"
        or len(payload) < 44
        or int.from_bytes(payload[4:8], "little") != len(payload) - 8
    ):
        raise ValueError
    with wave.open(io.BytesIO(payload), "rb") as stream:
        frames, rate = stream.getnframes(), stream.getframerate()
        data = stream.readframes(frames + 1)
        if (
            not frames
            or rate <= 0
            or len(data) != frames * stream.getnchannels() * stream.getsampwidth()
        ):
            raise ValueError
    return frames, rate


def inspect_wire(request: CostRequest, entry: PriceEntry | None) -> WireFacts:
    """Parse the actual wire, never a caller's claimed byte/token/audio counts."""
    try:
        protocol = entry.wire_protocol if entry else request.provider_id
        if protocol == "audio-fixture-v1":
            frames, rate = _audio(request.body)
            return WireFacts(len(request.body), None, frames, rate)
        if protocol == "opaque-fixture-v1":
            return WireFacts(len(request.body), 1)
        if protocol == "text-fixture-v1":
            value = _json(request.body)
            if (
                set(value) != {"model", "text", "max_output_tokens"}
                or value["model"] != request.model_revision
                or type(value["text"]) is not str
            ):
                raise ValueError
            return WireFacts(
                len(value["text"].encode()), integer(value["max_output_tokens"], minimum=1)
            )
        headers = dict(request.headers)
        if headers.get("content-type", "").startswith("multipart/form-data"):
            if request.provider_id != "openai" or request.operation != "stt":
                raise ValueError
            message = BytesParser(policy=email_policy.default).parsebytes(
                (
                    "Content-Type: " + headers["content-type"] + "\r\nMIME-Version: 1.0\r\n\r\n"
                ).encode()
                + request.body
            )
            if not message.is_multipart() or message.defects:
                raise ValueError
            fields: dict[str, bytes] = {}
            for part in message.iter_parts():
                name = part.get_param("name", header="content-disposition")
                if (
                    not isinstance(name, str)
                    or name
                    not in {
                        "model",
                        "file",
                        "response_format",
                        "language",
                        "timestamp_granularities[]",
                    }
                    or name in fields
                    or part.defects
                ):
                    raise ValueError
                data = part.get_payload(decode=True)
                if type(data) is not bytes:
                    raise ValueError
                fields[name] = data
            if fields.get("model") != request.model_revision.encode() or "file" not in fields:
                raise ValueError
            frames, rate = _audio(fields["file"])
            return WireFacts(len(fields["file"]), None, frames, rate)
        value = _json(request.body)
        texts: list[str] = []
        audio: bytes | None = None
        if request.provider_id == "openai":
            if (
                set(value)
                - {
                    "model",
                    "instructions",
                    "input",
                    "max_output_tokens",
                    "store",
                    "stream",
                    "background",
                    "truncation",
                }
                or value.get("model") != request.model_revision
                or type(value.get("input")) is not str
            ):
                raise ValueError
            texts = [value["input"], value.get("instructions", "")]
            output = integer(value.get("max_output_tokens"), minimum=1)
        elif request.provider_id == "anthropic":
            if (
                set(value) - {"model", "system", "messages", "max_tokens", "stream"}
                or value.get("model") != request.model_revision
                or headers.get("anthropic-version") != request.api_version
            ):
                raise ValueError
            texts = [value.get("system", "")]
            for message in value["messages"]:
                if (
                    set(message) != {"role", "content"}
                    or message["role"] not in {"user", "assistant"}
                    or type(message["content"]) is not str
                ):
                    raise ValueError
                texts.append(message["content"])
            output = integer(value.get("max_tokens"), minimum=1)
        elif request.provider_id == "gemini":
            if set(value) - {"systemInstruction", "contents", "generationConfig"} or not urlsplit(
                request.endpoint
            ).path.endswith("/models/" + request.model_revision + ":generateContent"):
                raise ValueError
            system = value.get("systemInstruction", {"parts": []})
            if set(system) != {"parts"}:
                raise ValueError
            parts = list(system["parts"])
            for content in value["contents"]:
                if set(content) != {"role", "parts"} or content["role"] not in {"user", "model"}:
                    raise ValueError
                parts.extend(content["parts"])
            for part in parts:
                if set(part) == {"text"} and type(part["text"]) is str:
                    texts.append(part["text"])
                elif set(part) == {"inlineData"} and audio is None and request.operation == "stt":
                    item = part["inlineData"]
                    if set(item) != {"mimeType", "data"} or item["mimeType"] != "audio/wav":
                        raise ValueError
                    audio = base64.b64decode(item["data"], validate=True)
                else:
                    raise ValueError
            config = value["generationConfig"]
            if set(config) - {"maxOutputTokens", "responseMimeType"}:
                raise ValueError
            output = integer(config.get("maxOutputTokens"), minimum=1)
        else:
            raise ValueError
        if any(type(t) is not str for t in texts) or output > 131072:
            raise ValueError
        if audio is not None:
            frames, rate = _audio(audio)
            return WireFacts(len(audio), output, frames, rate)
        if request.operation == "stt":
            raise ValueError
        return WireFacts(sum(len(t.encode()) for t in texts), output)
    except (
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        OverflowError,
        RecursionError,
        wave.Error,
    ):
        raise SecurityError("COST_REQUEST_INVALID") from None


@dataclass(frozen=True)
class CostQuote:
    request_fingerprint: str
    body_sha256: str
    byte_length: int
    kind: str
    amount: int
    reason: str | None
    input_upper: int | None
    output_upper: int | None
    price_as_of_utc: int | None
    valid_from_utc: int | None
    valid_until_utc: int | None
    profile_id: str | None
    policy: CostPolicy

    @property
    def fingerprint(self) -> str:
        return digest(canonical(asdict(self)))


def quote(request: CostRequest, policy: CostPolicy, catalog: CostCatalog, now: float) -> CostQuote:
    if (
        type(request) is not CostRequest
        or type(policy) is not CostPolicy
        or type(catalog) is not CostCatalog
    ):
        raise SecurityError("COST_REQUEST_INVALID")
    now = clock_value(now)
    if policy.catalog_digest != catalog.sha256:
        raise SecurityError("COST_QUOTE_MISMATCH")
    if policy.cap <= 0:
        raise SecurityError("COST_CAP_REQUIRED")
    if policy.mode == "general" and not policy.general_acknowledged:
        raise SecurityError("COST_BOUND_UNVERIFIED")
    entry = catalog.find(request)
    facts = inspect_wire(request, entry)
    input_size(facts.input_bytes)
    if entry is not None and entry.currency != policy.currency:
        raise SecurityError("COST_CURRENCY_MISMATCH")
    if entry and (
        facts.input_bytes > entry.max_input
        or facts.output_limit is not None
        and facts.output_limit > entry.max_output
    ):
        raise SecurityError("COST_REQUEST_INVALID")
    reason = None
    if entry is None or entry.price_as_of_utc is None:
        reason = "COST_PRICE_UNKNOWN"
    elif (
        entry.valid_from_utc is None
        or entry.valid_until_utc is None
        or not entry.valid_from_utc <= now < entry.valid_until_utc
    ):
        reason = "COST_PRICE_EXPIRED"
    elif entry.bound_kind == "unverified":
        reason = "COST_BOUND_UNVERIFIED"
    if reason is not None:
        if policy.mode == "strict":
            raise SecurityError(reason)
        return CostQuote(
            request.fingerprint,
            request.body_sha256,
            len(request.body),
            "USER_CAP",
            policy.cap,
            reason,
            None,
            None,
            None,
            None,
            None,
            None,
            policy,
        )
    assert entry is not None
    if entry.currency != policy.currency:
        raise SecurityError("COST_CURRENCY_MISMATCH")
    if (
        entry.bound_kind == "text_bytes"
        and facts.audio_frames is None
        and facts.output_limit is not None
    ):
        input_upper, output_upper = facts.input_bytes + entry.input_overhead, facts.output_limit
    elif (
        entry.bound_kind == "audio_seconds"
        and facts.audio_frames is not None
        and facts.sample_rate is not None
        and entry.output_numerator == 0
    ):
        input_upper = (facts.audio_frames + facts.sample_rate - 1) // facts.sample_rate
        output_upper = 0
    else:
        if policy.mode == "strict":
            raise SecurityError("COST_BOUND_UNVERIFIED")
        return CostQuote(
            request.fingerprint,
            request.body_sha256,
            len(request.body),
            "USER_CAP",
            policy.cap,
            "COST_BOUND_UNVERIFIED",
            None,
            None,
            None,
            None,
            None,
            None,
            policy,
        )
    if input_upper > MAX or output_upper > MAX:
        raise SecurityError("COST_AMOUNT_OVERFLOW")
    amount = (
        entry.fixed_fee
        + (input_upper * entry.input_numerator + entry.input_denominator - 1)
        // entry.input_denominator
        + (output_upper * entry.output_numerator + entry.output_denominator - 1)
        // entry.output_denominator
    )
    if not 0 <= amount <= MAX:
        raise SecurityError("COST_AMOUNT_OVERFLOW")
    if amount > policy.cap:
        raise SecurityError("COST_CAP_EXCEEDED")
    return CostQuote(
        request.fingerprint,
        request.body_sha256,
        len(request.body),
        "VERIFIED",
        amount,
        None,
        input_upper,
        output_upper,
        entry.price_as_of_utc,
        entry.valid_from_utc,
        entry.valid_until_utc,
        entry.profile_id,
        policy,
    )
