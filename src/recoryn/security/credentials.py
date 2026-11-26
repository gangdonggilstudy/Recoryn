"""Memory-only credential references, one-shot reads and bounded native commands."""

from __future__ import annotations

import hashlib
import math
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field

from ._core import SecurityError, identifier
from ._core import endpoint as parse_endpoint
from .consent import ConsentBinding, ConsentStore
from .vault import CredentialVault

_AUTH_NAMES = {"openai": "authorization", "anthropic": "x-api-key", "gemini": "x-goog-api-key"}


@dataclass(frozen=True)
class CredentialTarget:
    provider_id: str
    endpoint: str

    def __post_init__(self) -> None:
        identifier(self.provider_id)
        object.__setattr__(self, "endpoint", parse_endpoint(self.endpoint).url)

    @property
    def vault_key(self) -> str:
        return self.provider_id + "_" + hashlib.sha256(self.endpoint.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CredentialRef:
    target: CredentialTarget
    execution_id: str
    epoch: int


@dataclass(frozen=True)
class PlanBinding:
    slot: str
    epoch: int


@dataclass(frozen=True)
class AuthBinding:
    ref: CredentialRef
    service: CredentialService = field(repr=False, compare=False)
    plan: PlanBinding | None = None


@dataclass(frozen=True)
class ReadScope:
    request_id: str
    target: CredentialTarget
    binding: ConsentBinding
    body_sha256: str
    reservation_id: str
    deadline: float


@dataclass(frozen=True)
class ReadTicket:
    nonce: str
    _owner: object = field(repr=False, compare=False)


@dataclass(frozen=True)
class ReadClaim:
    nonce: str
    _owner: object = field(repr=False, compare=False)


@dataclass
class _Ticket:
    ref: CredentialRef
    scope: ReadScope
    plan: PlanBinding | None
    state: str = "ISSUED"
    claim: ReadClaim | None = None


@dataclass(frozen=True)
class CredentialEvent:
    stage: str
    nonce: str
    thread_id: int
    checked: bool = False
    committed: bool = False


CredentialHook = Callable[[CredentialEvent], None]


class CredentialLease:
    """Only app-owned slots are cleared; immutable/OS copies are not zeroized."""

    __slots__ = ("_secret", "_headers", "_release", "released")

    def __init__(self) -> None:
        self._secret: str | None = None
        self._headers: dict[str, str] = {}
        self._release: Callable[[], None] | None = None
        self.released = False

    def _bind(self, secret: str, provider: str, release: Callable[[], None]) -> None:
        name = _AUTH_NAMES.get(provider)
        if name is None:
            raise SecurityError("AUTH_REQUIRED")
        self._secret = secret
        self._headers = {name: "Bearer " + secret if provider == "openai" else secret}
        self._release = release

    def __repr__(self) -> str:
        return f"CredentialLease(released={self.released})"

    def add_headers(self, destination: dict[str, str]) -> None:
        if self.released or any(name in destination for name in _AUTH_NAMES.values()):
            raise SecurityError("AUTH_REQUIRED")
        destination.update(self._headers)

    def release(self) -> None:
        self._secret = None
        self._headers.clear()
        callback, self._release = self._release, None
        self.released = True
        if callback is not None:
            callback()


@dataclass(frozen=True)
class KeyResult:
    target: CredentialTarget
    command_nonce: str
    selection_generation: int
    epoch: int
    error_code: str | None = None


@dataclass
class _KeyCommand:
    target: CredentialTarget
    action: str
    secret: str | None = field(repr=False)
    nonce: str
    generation: int
    done: Callable[[KeyResult], None] = field(repr=False)


class CredentialService:
    """Trusted Gateway metadata operations never authorize network on their own."""

    def __init__(
        self,
        vault: CredentialVault,
        *,
        consents: ConsentStore,
        clock: Callable[[], float] = time.monotonic,
        hook: CredentialHook | None = None,
        native_workers: int = 4,
        pending_limit: int = 8,
        target_limit: int = 2,
    ) -> None:
        if any(
            type(n) is not int or not 1 <= n <= maximum
            for n, maximum in ((native_workers, 4), (pending_limit, 8), (target_limit, 2))
        ):
            raise SecurityError("INPUT_INVALID")
        self.vault = vault
        self.consents = consents
        self.execution_id = consents.execution_id
        self._clock, self._hook = clock, hook
        self._mutex = threading.RLock()
        self._condition = threading.Condition(self._mutex)
        self._owner = object()
        self._epochs: dict[CredentialTarget, int] = {}
        self._plans: dict[str, int] = {}
        self._tickets: dict[str, _Ticket] = {}
        self._claims: dict[str, str] = {}
        self._queues: dict[CredentialTarget, deque[_KeyCommand]] = {}
        self._grant_active: set[CredentialTarget] = set()
        self._pending = 0
        self._reads = 0
        self._requests = 0
        self._closing = False
        self._native_workers = native_workers
        self._pending_limit, self._target_limit = pending_limit, target_limit
        self._executor: ThreadPoolExecutor | None = None

    def _emit(
        self, stage: str, nonce: str, *, checked: bool = False, committed: bool = False
    ) -> None:
        if self._hook is not None:
            self._hook(CredentialEvent(stage, nonce, threading.get_ident(), checked, committed))

    def invalidate_plan(self, slot: str) -> None:
        with self._mutex:
            self._plans[slot] = self._plans.get(slot, 0) + 1

    def capture_plan(self, slot: str) -> PlanBinding:
        with self._mutex:
            return PlanBinding(slot, self._plans.get(slot, 0))

    def assert_plan(self, plan: PlanBinding) -> None:
        with self._mutex:
            if self._closing or self._plans.get(plan.slot, 0) != plan.epoch:
                raise SecurityError("PERMIT_REVOKED")

    @property
    def idle(self) -> bool:
        with self._mutex:
            return self._pending == 0 and self._reads == 0 and self._requests == 0

    def begin_request(self) -> None:
        with self._condition:
            if self._closing:
                raise SecurityError("AUTH_REQUIRED")
            self._requests += 1

    def end_request(self) -> None:
        with self._condition:
            self._requests -= 1
            self._condition.notify_all()

    def capture_binding(self, target: CredentialTarget, slot: str) -> AuthBinding:
        with self._mutex:
            return AuthBinding(
                CredentialRef(target, self.execution_id, self._epochs.get(target, 0)),
                self,
                PlanBinding(slot, self._plans.get(slot, 0)),
            )

    def capture_ref(self, target: CredentialTarget) -> CredentialRef:
        return self.capture_binding(target, "").ref

    def _current(self, reference: CredentialRef, plan: PlanBinding | None) -> None:
        if (
            self._closing
            or reference.execution_id != self.execution_id
            or reference.epoch != self._epochs.get(reference.target, 0)
            or self._queues.get(reference.target)
        ):
            raise SecurityError("AUTH_REQUIRED")
        if plan is not None and self._plans.get(plan.slot, 0) != plan.epoch:
            raise SecurityError("PERMIT_REVOKED")

    def assert_current(self, reference: CredentialRef, plan: PlanBinding | None = None) -> None:
        with self._mutex:
            self._current(reference, plan)

    def _scope_current(self, reference: CredentialRef, scope: ReadScope) -> None:
        if (
            type(scope) is not ReadScope
            or reference.target != scope.target
            or type(scope.binding) is not ConsentBinding
            or scope.binding.execution_id != self.execution_id
            or scope.binding.provider_id != scope.target.provider_id
            or scope.binding.endpoint != scope.target.endpoint
        ):
            raise SecurityError("AUTH_REQUIRED")
        if type(scope.deadline) not in (int, float) or not math.isfinite(scope.deadline):
            raise SecurityError("AUTH_REQUIRED")
        if self._clock() >= scope.deadline:
            raise SecurityError("TIMEOUT")

    def issue_ticket(
        self, reference: CredentialRef, scope: ReadScope, plan: PlanBinding | None = None
    ) -> ReadTicket:
        with self._mutex:
            self._current(reference, plan)
            self._scope_current(reference, scope)
            ticket = ReadTicket(uuid.uuid4().hex, self._owner)
            self._tickets[ticket.nonce] = _Ticket(reference, scope, plan)
        self._emit("ticket_issued", ticket.nonce)
        return ticket

    def consume_ticket(self, ticket: ReadTicket, scope: ReadScope) -> ReadClaim:
        self._emit("ticket_enter", ticket.nonce)
        with self._mutex:
            record = self._tickets.get(ticket.nonce)
            if (
                ticket._owner is not self._owner
                or record is None
                or record.state != "ISSUED"
                or record.scope != scope
            ):
                raise SecurityError("AUTH_REQUIRED")
            self._current(record.ref, record.plan)
            self._scope_current(record.ref, scope)
            self._emit("ticket_checked", ticket.nonce, checked=True)
            record.state = "CONSUMED"
            claim = ReadClaim(uuid.uuid4().hex, self._owner)
            record.claim = claim
            self._claims[claim.nonce] = ticket.nonce
            self._emit("ticket_committed", ticket.nonce, checked=True, committed=True)
        self._emit("ticket_released", ticket.nonce, checked=True, committed=True)
        return claim

    def read_claim(self, claim: ReadClaim) -> CredentialLease:
        with self._mutex:
            ticket_nonce = self._claims.get(claim.nonce)
            record = self._tickets.get(ticket_nonce or "")
            if (
                claim._owner is not self._owner
                or record is None
                or record.claim is not claim
                or record.state != "CONSUMED"
            ):
                raise SecurityError("AUTH_REQUIRED")
            record.state = "READING"
            self._reads += 1
            target = record.ref.target
        secret: str | None = None
        lease: CredentialLease | None = None
        try:
            self._emit("native_enter", claim.nonce)
            try:
                secret = self.vault.get(target.vault_key)
            except SecurityError as error:
                code = (
                    "VAULT_UNAVAILABLE"
                    if error.code == "VAULT_UNAVAILABLE"
                    else "VAULT_READ_FAILED"
                )
                raise SecurityError(code) from None
            except Exception:
                raise SecurityError("VAULT_READ_FAILED") from None
            if secret is None:
                raise SecurityError("AUTH_REQUIRED")
            try:
                valid = type(secret) is str and bool(secret) and "\0" not in secret
                valid = valid and len(secret.encode("utf-8")) <= 2560
            except (UnicodeError, AttributeError):
                valid = False
            if not valid:
                raise SecurityError("VAULT_READ_FAILED")
            lease = CredentialLease()
            lease._bind(secret, target.provider_id, lambda: self.discard_claim(claim))
            secret = None
            with self._mutex:
                record.state = "RETURNED"
            self._emit("native_return", claim.nonce)
            return lease
        except BaseException:
            if lease is not None:
                lease.release()
            self.discard_claim(claim)
            raise
        finally:
            secret = None
            with self._condition:
                self._reads -= 1
                self._condition.notify_all()

    def discard_ticket(self, ticket: ReadTicket) -> None:
        with self._mutex:
            if ticket._owner is self._owner:
                record = self._tickets.pop(ticket.nonce, None)
                if record is not None and record.claim is not None:
                    self._claims.pop(record.claim.nonce, None)

    def discard_claim(self, claim: ReadClaim) -> None:
        with self._mutex:
            if claim._owner is self._owner:
                nonce = self._claims.pop(claim.nonce, None)
                if nonce is not None:
                    self._tickets.pop(nonce, None)

    @contextmanager
    def grant_gate(self, target: CredentialTarget) -> Iterator[None]:
        with self.consents.coordinator.hold():
            with self._mutex:
                if self._closing or self._queues.get(target) or target in self._grant_active:
                    raise SecurityError("AUTH_REQUIRED")
                self._grant_active.add(target)
            try:
                yield
            finally:
                with self._mutex:
                    self._grant_active.discard(target)

    def check_grant_allowed(self, target: CredentialTarget) -> None:
        with self._mutex:
            if self._closing or self._queues.get(target):
                raise SecurityError("AUTH_REQUIRED")

    def try_enqueue_key_change(
        self,
        target: CredentialTarget,
        action: str,
        secret: str | None,
        *,
        command_nonce: str,
        selection_generation: int,
        done: Callable[[KeyResult], None],
    ) -> bool:
        if action not in {"save", "delete"}:
            raise SecurityError("INPUT_INVALID")
        identifier(command_nonce)
        if not self._mutex.acquire(blocking=False):
            return False
        try:
            queue = self._queues.get(target)
            if (
                self._closing
                or self._pending >= self._pending_limit
                or len(queue or ()) >= self._target_limit
                or target in self._grant_active
            ):
                return False
            first = not queue
            if queue is None:
                queue = self._queues[target] = deque()
            queue.append(
                _KeyCommand(target, action, secret, command_nonce, selection_generation, done)
            )
            self._pending += 1
            if self._executor is None:
                self._executor = ThreadPoolExecutor(
                    max_workers=self._native_workers, thread_name_prefix="recoryn-key"
                )
            if first:
                self._executor.submit(self._run_target, target)
            return True
        finally:
            self._mutex.release()

    def _run_target(self, target: CredentialTarget) -> None:
        while True:
            with self._mutex:
                queue = self._queues.get(target)
                if not queue:
                    return
                command = queue[0]
            error_code: str | None = None
            try:
                with self.consents.coordinator.hold():
                    with self._mutex:
                        self._epochs[target] = self._epochs.get(target, 0) + 1
                    self.consents.revoke_endpoint(target.provider_id, target.endpoint)
                self._emit("key_native_enter", command.nonce)
                if command.action == "save":
                    self.vault.set(target.vault_key, command.secret or "")
                else:
                    self.vault.delete(target.vault_key)
            except SecurityError as error:
                allowed = {
                    "VAULT_UNAVAILABLE",
                    "VAULT_WRITE_FAILED",
                    "VAULT_DELETE_FAILED",
                    "VAULT_INVALID_VALUE",
                    "CONSENT_CLOCK_INVALID",
                    "EXECUTION_CHANGED",
                    "LEDGER_ROLLBACK_DETECTED",
                    "CANCELLED",
                }
                error_code = error.code if error.code in allowed else "VAULT_WRITE_FAILED"
            except Exception:
                error_code = (
                    "VAULT_WRITE_FAILED" if command.action == "save" else "VAULT_DELETE_FAILED"
                )
            finally:
                command.secret = None
            with self._condition:
                queue = self._queues[target]
                queue.popleft()
                self._pending -= 1
                epoch = self._epochs.get(target, 0)
                if not queue:
                    del self._queues[target]
                self._condition.notify_all()
            try:
                command.done(
                    KeyResult(target, command.nonce, command.generation, epoch, error_code)
                )
            except Exception:
                pass  # A closing GUI cannot revive/repeat a completed native command.

    def begin_shutdown(self) -> None:
        with self._mutex:
            self._closing = True
            for slot in self._plans:
                self._plans[slot] += 1

    def await_shutdown(self, timeout: float = 5.0) -> bool:
        self.begin_shutdown()
        with self._condition:
            complete = self._condition.wait_for(
                lambda: self._pending == 0 and self._reads == 0 and self._requests == 0, timeout
            )
            executor = self._executor
        if complete and executor is not None:
            executor.shutdown(wait=True)
        return complete
