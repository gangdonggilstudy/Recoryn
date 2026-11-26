"""All outbound content crosses revocable policy checks before connection and each write."""

from __future__ import annotations

import re
import threading
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager, nullcontext

from ._core import SecurityError, digest, duration
from ._core import endpoint as parse_endpoint
from .consent import ConsentBinding, ConsentRequest, ConsentScope, ConsentStore, SendPermit
from .cost import cost_headers
from .credentials import AuthBinding, CredentialLease, CredentialTarget, ReadScope, ReadTicket
from .ledger import CostLedger, CostPreflight
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
        auth_binding: AuthBinding | None = None,
    ) -> None:
        self.consents, self.ledger = consents, ledger
        self.auth_binding = auth_binding
        self._plan_check: Callable[[], None] | None = None
        self._clock: Callable[[], float] | None = None
        self.transport = transport if transport is not None else DirectTransport()
        self.timeout = duration(timeout)
        if expected_grants is not None and (
            type(expected_grants) is not tuple
            or any(not isinstance(binding, ConsentBinding) for binding in expected_grants)
        ):
            raise SecurityError("INVALID_CONSENT_BINDING")
        self._expected_grants = expected_grants
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
        self._request: ConsentRequest | None = None
        self._scope: ConsentScope | None = None

    @property
    def expected_grants(self) -> tuple[ConsentBinding, ...] | None:
        return self._expected_grants

    @property
    def session_id(self) -> str | None:
        return self._request.session_id if self._request else None

    @property
    def session_generation(self) -> int:
        return self._request.session_generation if self._request else 0

    def for_session(
        self,
        session_id: str,
        generation: int = 0,
        *,
        capability: str,
        scope: ConsentScope,
        policy_version: int,
    ) -> Gateway:
        request = ConsentRequest(session_id, generation, capability, policy_version)
        if type(scope) is not ConsentScope:
            raise SecurityError("INVALID_CONSENT_SCOPE")
        if (
            self._request is not None and (self._request != request or self._scope != scope)
        ) or any(
            binding.request != request or binding.scope != scope
            for binding in self.expected_grants or ()
        ):
            raise SecurityError("PERMIT_REVOKED")
        self.consents.bind_session(session_id, generation)
        view = type(self)(
            self.consents,
            ledger=self.ledger,
            transport=self.transport,
            timeout=self.timeout,
            max_request_bytes=self.max_request_bytes,
            max_response_bytes=self.max_response_bytes,
            chunk_bytes=self.chunk_bytes,
            expected_grants=self.expected_grants,
            dispatch_guard=self.dispatch_guard,
            auth_binding=self.auth_binding,
        )
        view._request, view._scope = request, scope
        view._plan_check = self._plan_check
        view._clock = self._clock
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

    def _auth_current(self, permit: SendPermit) -> None:
        if self._plan_check is not None:
            self._plan_check()
        binding = self.auth_binding
        cloud = permit.provider_id in {"openai", "anthropic", "gemini"}
        if binding is None:
            if cloud:
                raise SecurityError("AUTH_REQUIRED")
            return
        if not cloud:
            raise SecurityError("INPUT_INVALID")
        if binding.ref.target != CredentialTarget(permit.provider_id, permit.endpoint):
            raise SecurityError("AUTH_REQUIRED")
        binding.service.assert_current(binding.ref, binding.plan)

    def _now(self) -> float:
        return self._clock() if self._clock is not None else time.monotonic()

    def _auth_event(self, stage: str, nonce: str) -> None:
        if self.auth_binding is not None:
            self.auth_binding.service._emit(stage, nonce)

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
        auth_names = {"authorization", "x-api-key", "x-goog-api-key"}
        if auth_names.intersection(safe_headers):
            raise SecurityError("INPUT_INVALID")
        price_headers = dict(cost_headers(safe_headers))
        lease: CredentialLease | None = None
        ticket: ReadTicket | None = None
        preflight: CostPreflight | None = None
        deadline = self._now() + self.timeout
        connection: Connection | None = None
        handed_off = False
        dispatch_id = uuid.uuid4().hex
        write_end = 0
        request_started = False

        def remaining() -> float:
            if cancel is not None and cancel.is_set():
                raise SecurityError(
                    "CANCELLED" if not handed_off else "REMOTE_OUTCOME_UNKNOWN",
                    outcome_known=not handed_off,
                )
            result = deadline - self._now()
            if result <= 0:
                raise SecurityError(
                    "TIMEOUT" if not handed_off else "REMOTE_OUTCOME_UNKNOWN",
                    outcome_known=not handed_off,
                )
            return result

        def write_remaining() -> float:
            # _write calls this under consent -> ledger locks, before owner guard.
            if self.ledger is not None:
                assert reservation_id is not None and self._request is not None
                self.ledger.validate_dispatch(
                    reservation_id,
                    provider_id,
                    target_endpoint.url,
                    body,
                    data_type=data_type,
                    operation=self._request.capability,
                    headers=price_headers,
                    dispatch_id=dispatch_id,
                    phase="write",
                    bytes_sent=write_end,
                )
            return remaining()

        def release_auth() -> None:
            if lease is not None:
                lease.release()
            for name in auth_names:
                safe_headers.pop(name, None)

        try:
            if self.auth_binding is not None:
                self.auth_binding.service.begin_request()
                request_started = True
            remaining()
            if self._request is None or self._scope is None or not self.expected_grants:
                raise SecurityError("CONSENT_REQUIRED")
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
                scope=self._scope,
                request=self._request,
                reservation_id=reservation_id,
                expected_grant=expected,
            )
            if self.ledger is not None:
                if reservation_id is None:
                    raise SecurityError("BUDGET_REQUIRED")
                self.ledger.check_reservation(reservation_id, provider_id)
            elif reservation_id is not None:
                raise SecurityError("LEDGER_REQUIRED")
            elif provider_id in {"openai", "anthropic", "gemini"}:
                raise SecurityError("LEDGER_REQUIRED")
            if provider_id in {"openai", "anthropic", "gemini"}:
                if self.auth_binding is None:
                    raise SecurityError("AUTH_REQUIRED")
                assert self.ledger is not None and reservation_id is not None
                request_ledger, request_policy = self.ledger, self._request
                binding = self.auth_binding
                scope = ReadScope(
                    dispatch_id,
                    CredentialTarget(provider_id, target_endpoint.url),
                    permit.binding,
                    digest(body),
                    reservation_id,
                    deadline,
                )
                self._auth_event("i_enter", dispatch_id)

                def before_read() -> None:
                    nonlocal preflight
                    remaining()
                    self.consents.validate(permit)
                    preflight = request_ledger.preflight_request(
                        reservation_id,
                        provider_id,
                        target_endpoint.url,
                        body,
                        data_type=data_type,
                        operation=request_policy.capability,
                        headers=price_headers,
                        prior=preflight,
                    )
                    self._auth_current(permit)

                with self.consents.coordinator.hold(), self.ledger.coordinator.hold():
                    before_read()
                    ticket = binding.service.issue_ticket(binding.ref, scope, binding.plan)
                self._auth_event("i_released", ticket.nonce)
                with self.consents.coordinator.hold(), self.ledger.coordinator.hold():
                    before_read()
                    claim = binding.service.consume_ticket(ticket, scope)
                self._auth_event("u_released", ticket.nonce)
                try:
                    lease = binding.service.read_claim(claim)
                except SecurityError:
                    # A concurrent revoke/delete may make the native result absent.
                    # The r policy/deadline gate still precedes its public read error.
                    with self.consents.coordinator.hold(), self.ledger.coordinator.hold():
                        before_read()
                    raise
                with self.consents.coordinator.hold(), self.ledger.coordinator.hold():
                    before_read()
                self._auth_event("r_released", ticket.nonce)
                lease.add_headers(safe_headers)
            elif self.auth_binding is not None:
                raise SecurityError("INPUT_INVALID")
            self._auth_event("o_enter", dispatch_id)
            with (
                self.consents.coordinator.hold(),
                self.ledger.coordinator.hold() if self.ledger is not None else nullcontext(),
            ):
                self.consents.validate(permit)
                self._auth_current(permit)
                if self.ledger is not None:
                    assert reservation_id is not None
                    if preflight is None:
                        self.ledger.validate_dispatch(
                            reservation_id,
                            provider_id,
                            target_endpoint.url,
                            body,
                            data_type=data_type,
                            operation=self._request.capability,
                            headers=price_headers,
                            dispatch_id=dispatch_id,
                        )
                    else:
                        self.ledger.validate_dispatch(
                            reservation_id,
                            provider_id,
                            target_endpoint.url,
                            body,
                            data_type=data_type,
                            operation=self._request.capability,
                            headers=price_headers,
                            dispatch_id=dispatch_id,
                            preflight=preflight,
                        )
                with self._execution_guard(permit):
                    connection = self.transport.open(
                        target_endpoint, safe_headers, len(body), remaining()
                    )
            self._auth_event("o_released", dispatch_id)
            chunk_bytes = self.chunk_bytes
            sent_bytes = 0
            pieces = range(0, len(body), chunk_bytes) if body else (0,)
            for offset in pieces:
                piece = body[offset : offset + chunk_bytes]
                write_end = sent_bytes + len(piece)
                try:
                    self._write(
                        connection,
                        permit,
                        piece,
                        write_remaining,
                        first=not handed_off,
                    )
                finally:
                    if not handed_off:
                        release_auth()
                sent_bytes = write_end
                handed_off = True
                self._auth_event("write_released", dispatch_id)
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
                        self._auth_current(permit)
                        with self._execution_guard(permit):
                            remaining()
                            return bytes(output)
        except SecurityError as error:
            if (handed_off or not error.outcome_known) and error.code in {
                "AUTH_REQUIRED",
                "VAULT_UNAVAILABLE",
                "VAULT_READ_FAILED",
            }:
                raise SecurityError("REMOTE_OUTCOME_UNKNOWN", outcome_known=False) from None
            if handed_off and error.outcome_known:
                raise SecurityError(error.code, outcome_known=False) from None
            raise
        except Exception:
            raise SecurityError(
                "REMOTE_OUTCOME_UNKNOWN" if handed_off else "TRANSPORT_FAILED",
                outcome_known=not handed_off,
            ) from None
        finally:
            try:
                release_auth()
                if ticket is not None and self.auth_binding is not None:
                    self.auth_binding.service.discard_ticket(ticket)
                if self.ledger is not None:
                    self.ledger.finish_dispatch(dispatch_id)
                if connection is not None:
                    try:
                        connection.close()
                    except Exception:
                        pass
            finally:
                if request_started and self.auth_binding is not None:
                    self.auth_binding.service.end_request()

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
            self._auth_current(permit)
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
                if write_started and error.code in {
                    "AUTH_REQUIRED",
                    "VAULT_UNAVAILABLE",
                    "VAULT_READ_FAILED",
                }:
                    raise SecurityError("REMOTE_OUTCOME_UNKNOWN", outcome_known=False) from None
                if write_started and error.outcome_known:
                    raise SecurityError(error.code, outcome_known=False) from None
                raise
            except Exception:
                # A write may have partially reached the OS even when it raises.
                raise SecurityError(
                    "REMOTE_OUTCOME_UNKNOWN" if write_started else "TRANSPORT_FAILED",
                    outcome_known=not write_started,
                ) from None
