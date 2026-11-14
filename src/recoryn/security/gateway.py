"""All outbound content crosses revocable policy checks before connection and each write."""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager, nullcontext

from ._core import SecurityError, digest, duration
from ._core import endpoint as parse_endpoint
from .consent import ConsentBinding, ConsentStore, SendPermit
from .ledger import CostLedger
from .transport import Connection, DirectTransport, Transport

_HEADER_NAMES = {
    "authorization",
    "content-type",
    "accept",
    "anthropic-version",
    "x-api-key",
    "x-goog-api-key",
    "openai-organization",
    "openai-project",
    "idempotency-key",
}


class Gateway:
    def __init__(
        self,
        consents: ConsentStore,
        *,
        ledger: CostLedger | None = None,
        transport: Transport | None = None,
        timeout: float = 30,
        max_request_bytes: int = 32 * 1024 * 1024,
        max_response_bytes: int = 8 * 1024 * 1024,
        chunk_bytes: int = 64 * 1024,
        expected_grants: tuple[ConsentBinding, ...] | None = None,
        dispatch_guard: Callable[[SendPermit], AbstractContextManager[None]] | None = None,
    ) -> None:
        self.consents, self.ledger = consents, ledger
        self.transport = transport if transport is not None else DirectTransport()
        self.timeout = duration(timeout)
        if expected_grants is not None and (
            type(expected_grants) is not tuple
            or any(not isinstance(binding, ConsentBinding) for binding in expected_grants)
        ):
            raise SecurityError("INVALID_CONSENT_BINDING")
        self.expected_grants = expected_grants
        if dispatch_guard is not None and not callable(dispatch_guard):
            raise SecurityError("INVALID_DISPATCH_GUARD")
        self.dispatch_guard = dispatch_guard
        if any(
            type(value) is not int or value < 1
            for value in (max_request_bytes, max_response_bytes, chunk_bytes)
        ):
            raise SecurityError("INVALID_SIZE_LIMIT")
        self.max_request_bytes, self.max_response_bytes, self.chunk_bytes = (
            max_request_bytes,
            max_response_bytes,
            chunk_bytes,
        )
        self.session_id: str | None = None
        self.session_generation = 0

    def for_session(self, session_id: str, generation: int = 0) -> Gateway:
        self.consents.bind_session(session_id, generation)
        view = Gateway(
            self.consents,
            ledger=self.ledger,
            transport=self.transport,
            timeout=self.timeout,
            max_request_bytes=self.max_request_bytes,
            max_response_bytes=self.max_response_bytes,
            chunk_bytes=self.chunk_bytes,
            expected_grants=self.expected_grants,
            dispatch_guard=self.dispatch_guard,
        )
        view.session_id, view.session_generation = session_id, generation
        return view

    @contextmanager
    def _execution_guard(self, permit: SendPermit) -> Iterator[None]:
        """Keep the frozen runtime lease through a single transport handoff.

        Consent, then ledger (for writes), then owner is the lock order. Hooks
        must not enter consent/ledger while holding an owner lock. Hook failures
        carry no private diagnostics and cannot suppress a transport exception.
        """
        if self.dispatch_guard is None:
            yield
            return
        try:
            guard = self.dispatch_guard(permit)
            guard.__enter__()
        except Exception:
            raise SecurityError("LOCAL_EXECUTION_UNVERIFIED") from None
        try:
            yield
        except BaseException as error:
            try:
                guard.__exit__(type(error), error, error.__traceback__)
            except Exception:
                pass  # Preserve the original handoff/UNKNOWN rather than an exit error.
            raise
        else:
            try:
                guard.__exit__(None, None, None)
            except Exception:
                raise SecurityError("LOCAL_EXECUTION_UNVERIFIED") from None

    @staticmethod
    def _headers(headers: Mapping[str, str] | None) -> dict[str, str]:
        result: dict[str, str] = {}
        for name, value in (headers or {}).items():
            if (
                not isinstance(name, str)
                or not isinstance(value, str)
                or name.lower() not in _HEADER_NAMES
                or name.lower() in result
                or len(value) > 8192
                or any(ord(c) < 32 or ord(c) == 127 for c in value)
                or not re.fullmatch(r"[A-Za-z0-9-]+", name)
            ):
                raise SecurityError("INVALID_HEADER")
            result[name.lower()] = value
        return result

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
        if type(body) is not bytes or len(body) > self.max_request_bytes:
            raise SecurityError("REQUEST_TOO_LARGE")
        target_endpoint = parse_endpoint(endpoint)
        safe_headers = self._headers(headers)
        deadline = time.monotonic() + self.timeout
        connection: Connection | None = None
        handed_off = False

        def remaining() -> float:
            if cancel is not None and cancel.is_set():
                raise SecurityError(
                    "CANCELLED" if not handed_off else "REMOTE_OUTCOME_UNKNOWN",
                    outcome_known=not handed_off,
                )
            result = deadline - time.monotonic()
            if result <= 0:
                raise SecurityError(
                    "TIMEOUT" if not handed_off else "REMOTE_OUTCOME_UNKNOWN",
                    outcome_known=not handed_off,
                )
            return result

        try:
            expected = None
            if self.expected_grants is not None:
                expected = next(
                    (
                        binding
                        for binding in self.expected_grants
                        if (binding.provider_id, binding.endpoint, binding.data_type)
                        == (provider_id, target_endpoint.url, data_type)
                    ),
                    None,
                )
                if expected is None:
                    raise SecurityError("CONSENT_REQUIRED")
            permit = self.consents.permit(
                provider_id,
                target_endpoint.url,
                data_type,
                digest(body),
                session_id=self.session_id,
                session_generation=self.session_generation,
                reservation_id=reservation_id,
                expected_grant=expected,
            )
            if self.ledger is not None:
                if reservation_id is None:
                    raise SecurityError("BUDGET_REQUIRED")
                self.ledger.check_reservation(reservation_id, provider_id)
            elif reservation_id is not None:
                raise SecurityError("LEDGER_REQUIRED")
            with self.consents.coordinator.hold():
                self.consents.validate(permit)
                with self._execution_guard(permit):
                    connection = self.transport.open(
                        target_endpoint, safe_headers, len(body), remaining()
                    )
            pieces = range(0, len(body), self.chunk_bytes) if body else (0,)
            for offset in pieces:
                self._write(
                    connection,
                    permit,
                    body[offset : offset + self.chunk_bytes],
                    remaining,
                    first=not handed_off,
                )
                handed_off = True
            output = bytearray()
            while True:
                data = connection.read(
                    min(self.chunk_bytes, self.max_response_bytes + 1 - len(output)), remaining()
                )
                if type(data) is not bytes:
                    raise SecurityError("INVALID_RESPONSE", outcome_known=False)
                output.extend(data)
                if len(output) > self.max_response_bytes:
                    raise SecurityError("RESPONSE_TOO_LARGE", outcome_known=False)
                if not data:
                    with self.consents.coordinator.hold():
                        self.consents.validate(permit)
                        with self._execution_guard(permit):
                            remaining()
                            return bytes(output)
        except SecurityError as error:
            if handed_off and error.outcome_known:
                raise SecurityError(error.code, outcome_known=False) from None
            raise
        except Exception:
            raise SecurityError(
                "REMOTE_OUTCOME_UNKNOWN" if handed_off else "TRANSPORT_FAILED",
                outcome_known=not handed_off,
            ) from None
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass

    def _write(
        self,
        connection: Connection,
        permit: SendPermit,
        data: bytes,
        remaining: Callable[[], float],
        *,
        first: bool,
    ) -> None:
        with (
            self.consents.coordinator.hold(),
            self.ledger.coordinator.hold() if self.ledger is not None else nullcontext(),
        ):
            self.consents.validate(permit)
            timeout = remaining()
            write_started = False
            try:
                with self._execution_guard(permit):
                    if first and self.ledger is not None:
                        assert permit.reservation_id is not None
                        self.ledger.check_reservation(permit.reservation_id, permit.provider_id)
                        self.ledger.mark_unknown(permit.reservation_id)
                    write_started = True
                    connection.write(data, timeout)
            except SecurityError as error:
                if write_started and error.outcome_known:
                    raise SecurityError(error.code, outcome_known=False) from None
                raise
            except Exception:
                # A write may have partially reached the OS even when it raises.
                raise SecurityError(
                    "REMOTE_OUTCOME_UNKNOWN" if write_started else "TRANSPORT_FAILED",
                    outcome_known=not write_started,
                ) from None
