"""Bounded wire processing and safe errors; all egress belongs to B14."""

from __future__ import annotations

import hashlib
import io
import json
import math
import stat
import time
import wave
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from recoryn.security.cost import COST_CODES, CostRequest, cost_headers, wire_api_version

from .contracts import (
    ExecutionContext,
    GatewayLike,
    ProgressEvent,
    ProviderConfig,
    ProviderError,
    STTRequest,
    TranscriptSegment,
)


def encode(value: object) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False
        ).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ProviderError("INPUT_INVALID") from None


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProviderError("RESULT_INVALID")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise ProviderError("RESULT_INVALID")


def decode(data: bytes, maximum: int) -> dict[str, Any]:
    if type(data) is not bytes or len(data) > maximum:
        raise ProviderError("RESPONSE_TOO_LARGE")
    try:
        result = json.loads(
            data.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant
        )
    except (ValueError, UnicodeError, RecursionError):
        raise ProviderError("RESULT_INVALID") from None
    if not isinstance(result, dict) or "error" in result and result["error"] is not None:
        raise ProviderError("PROVIDER_REJECTED")
    return result


def checked_local_path(path: Path) -> None:
    if not path.is_absolute() or str(path).startswith(("\\\\", "//")):
        raise ProviderError("INPUT_INVALID")
    for part in [*reversed(path.parents), path]:
        try:
            info = part.lstat()
        except OSError:
            raise ProviderError("INPUT_MISSING") from None
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ProviderError("INPUT_INVALID")
        if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            raise ProviderError("INPUT_INVALID")


def read_audio(request: STTRequest, maximum: int = 8 * 1024 * 1024) -> tuple[bytes, int, str]:
    checked_local_path(request.audio_path)
    try:
        if (
            request.audio_path.suffix.lower() != ".wav"
            or request.audio_path.stat().st_size > maximum
        ):
            raise ProviderError("AUDIO_UNSUPPORTED")
        with request.audio_path.open("rb") as stream:
            payload = stream.read(maximum + 1)
        if len(payload) > maximum:
            raise ProviderError("INPUT_TOO_LARGE")
        with wave.open(io.BytesIO(payload), "rb") as audio:
            if audio.getcomptype() != "NONE" or not 1 <= audio.getnchannels() <= 64:
                raise ProviderError("AUDIO_UNSUPPORTED")
            frames, rate = audio.getnframes(), audio.getframerate()
            if frames <= 0 or rate <= 0:
                raise ProviderError("AUDIO_UNSUPPORTED")
            if frames * audio.getnchannels() * audio.getsampwidth() > len(payload):
                raise ProviderError("INPUT_INVALID")
            if (
                len(audio.readframes(frames))
                != frames * audio.getnchannels() * audio.getsampwidth()
            ):
                raise ProviderError("INPUT_INVALID")
        return payload, (frames * 1000 + rate - 1) // rate, hashlib.sha256(payload).hexdigest()
    except (OSError, EOFError, wave.Error):
        raise ProviderError("AUDIO_UNSUPPORTED") from None


def segment(
    request: STTRequest,
    audio_hash: str,
    index: int,
    start: object,
    end: object,
    text: object,
    duration_ms: int,
    *,
    timing: str = "model",
) -> TranscriptSegment:
    if (
        isinstance(start, bool)
        or isinstance(end, bool)
        or not isinstance(start, (int, float))
        or not isinstance(end, (int, float))
        or not math.isfinite(start)
        or not math.isfinite(end)
        or start < 0
        or end < start
        or end * 1000 > duration_ms + 1
        or not isinstance(text, str)
    ):
        raise ProviderError("RESULT_INVALID")
    start_ms, end_ms = int(start * 1000), min(duration_ms, int(end * 1000))
    segment_id = hashlib.sha256(
        encode(
            [
                request.audio_revision_id,
                audio_hash,
                request.track_id,
                request.offset_ms,
                index,
                start_ms,
                end_ms,
                text,
            ]
        )
    ).hexdigest()[:32]
    return TranscriptSegment(
        segment_id,
        request.offset_ms + start_ms,
        request.offset_ms + end_ms,
        text,
        track_id=request.track_id,
        timing_quality=timing,
    )


class Run:
    def __init__(self, config: ProviderConfig, context: ExecutionContext | None) -> None:
        self.config = config
        self.context = context if context is not None else ExecutionContext()
        self.deadline = time.monotonic() + config.timeout_seconds
        self.calls = 0
        self.reservations: set[str] = set()

    def check(self) -> None:
        if self.context.cancel.is_set():
            raise ProviderError("CANCELLED")
        if time.monotonic() >= self.deadline:
            raise ProviderError("TIMEOUT")

    def progress(self, stage: str, completed: int, total: int | None, unit: str) -> None:
        self.check()
        if self.context.progress is not None:
            try:
                self.context.progress(ProgressEvent(stage, completed, total, unit))
            except Exception:
                raise ProviderError("PROGRESS_CALLBACK_FAILED") from None
        self.check()

    def request(
        self,
        gateway: GatewayLike,
        endpoint: str,
        data_type: str,
        body: bytes,
        headers: dict[str, str] | None = None,
        *,
        operation: str,
    ) -> dict[str, Any]:
        self.check()
        if self.calls >= self.config.max_requests:
            raise ProviderError("REQUEST_LIMIT")
        if len(body) > 20 * 1024 * 1024:
            raise ProviderError("INPUT_TOO_LARGE")
        reservation: str | None = None
        if self.context.reservation_factory is not None:
            try:
                cost_request = CostRequest(
                    self.config.provider_id,
                    endpoint,
                    self.config.model,
                    wire_api_version(self.config.provider_id, endpoint, headers),
                    operation,
                    data_type,
                    body,
                    cost_headers(headers),
                )
                reservation = self.context.reservation_factory(cost_request)
            except Exception as exc:
                code = getattr(exc, "code", None)
                if code in COST_CODES or code in {
                    "BUDGET_REQUIRED",
                    "BUDGET_EXCEEDED",
                    "BUDGET_POLICY_CHANGED",
                    "RESERVATION_CONFLICT",
                    "LEDGER_ROLLBACK_DETECTED",
                }:
                    raise ProviderError(str(code), outcome_known=True) from None
                raise ProviderError("BUDGET_BLOCKED") from None
        if reservation is not None:
            if (
                not isinstance(reservation, str)
                or not reservation
                or reservation in self.reservations
            ):
                raise ProviderError("BUDGET_RESERVATION_REUSED")
            self.reservations.add(reservation)
        self.check()
        combined = dict(self.context.headers)
        combined.update(headers or {})
        self.calls += 1
        try:
            result = gateway.request(
                self.config.provider_id,
                endpoint,
                data_type,
                body,
                headers=combined,
                reservation_id=reservation,
                cancel=self.context.cancel,
            )
        except Exception as exc:
            safe_codes = {
                "CONSENT_REQUIRED",
                "CONSENT_REVOKED",
                "ENDPOINT_CHANGED",
                "NETWORK_POLICY_DENIED",
                "BUDGET_BLOCKED",
                "AUTH_REQUIRED",
                "CANCELLED",
                "LOCAL_EXECUTION_UNVERIFIED",
                "REQUEST_TOO_LARGE",
                "RESPONSE_TOO_LARGE",
                "REMOTE_OUTCOME_UNKNOWN",
                "SESSION_REVOKED",
                "PERMIT_REVOKED",
                "EXECUTION_CHANGED",
                "TIMEOUT",
                "TRANSPORT_FAILED",
                "BUDGET_REQUIRED",
                "BUDGET_EXCEEDED",
                "LEDGER_REQUIRED",
                "LEDGER_ROLLBACK_DETECTED",
                "RESERVATION_NOT_DISPATCHABLE",
            }
            code = getattr(exc, "code", None)
            safe_codes.update(COST_CODES)
            safe_codes.update(
                {"BUDGET_POLICY_CHANGED", "RESERVATION_CONFLICT", "SETTLEMENT_CONFLICT"}
            )
            if isinstance(code, str) and code in safe_codes:
                raise ProviderError(
                    code, outcome_known=getattr(exc, "outcome_known", False) is True
                ) from None
            raise ProviderError("REMOTE_OUTCOME_UNKNOWN", outcome_known=False) from None
        self.check()
        return decode(result, self.config.max_response_bytes)


def require_endpoint(config: ProviderConfig, endpoint: str, *, local: bool = False) -> None:
    try:
        url = urlsplit(endpoint)
        port = url.port
    except ValueError:
        raise ProviderError("INPUT_INVALID") from None
    if (
        not url.hostname
        or url.username is not None
        or url.password is not None
        or url.query
        or url.fragment
        or url.scheme not in {"http", "https"}
    ):
        raise ProviderError("INPUT_INVALID")
    if local:
        proof = config.local_attestation
        if (
            config.execution_location != "local"
            or url.hostname not in {"127.0.0.1", "::1", "localhost"}
            or port is None
            or proof is None
            or not proof.cloud_disabled
            or proof.endpoint != endpoint
            or proof.model != config.model
            or proof.expires_at_monotonic <= time.monotonic()
        ):
            raise ProviderError("LOCAL_EXECUTION_UNVERIFIED")
        with proof.execution_guard():
            pass
    elif config.execution_location != "remote" or url.scheme != "https":
        raise ProviderError("NETWORK_POLICY_DENIED")
