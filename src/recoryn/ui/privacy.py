"""Explicit consent, credentials and scoped, quoted remote cost controls."""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from recoryn.jobs.failures import CODE_GROUPS
from recoryn.providers import (
    ExecutionContext,
    FactIdentity,
    LocalModelAttestation,
    ObservationState,
    ProviderConfig,
    ProviderError,
    ProviderEvidenceLevel,
    default_endpoint,
    describe,
)
from recoryn.security import (
    ConsentBinding,
    ConsentRequest,
    ConsentScope,
    ConsentStore,
    CostLedger,
    CostPolicy,
    CostQuote,
    CostRequest,
    CredentialVault,
    Gateway,
    SecurityError,
    SendPermit,
    cost_catalog,
)
from recoryn.security._core import endpoint as parse_endpoint
from recoryn.security.credentials import (
    AuthBinding,
    CredentialService,
    CredentialTarget,
    KeyResult,
    PlanBinding,
)
from recoryn.ui import a11y

FACTS_UNKNOWN = "최근 관측 없음 · 이 버전은 제공업체에 확인 요청을 보내지 않습니다"
SERVER_TRUST_GENERAL = (
    "이 주소는 연결 대상입니다. loopback 주소만으로 실제 추론 위치나 서버의 후속 전송을 "
    "확인할 수 없습니다. 사용자 지정 서버의 설정과 신뢰 범위는 사용자가 확인해야 합니다. "
    "loopback 예외는 원격 주소·redirect·proxy 전송을 허용하지 않습니다."
)
SERVER_TRUST = SERVER_TRUST_GENERAL + (
    " "
    "Ollama는 cloud 모델 경로를 사용할 수 있습니다. 목록 응답은 로컬 추론·외부 무전송의 "
    "증거가 아닙니다. 로컬 실행 증명이 없으면 추론은 차단됩니다."
)


def _micros(control: QDoubleSpinBox) -> int:
    return int(Decimal(str(control.value())) * 1_000_000)


def _usd(value: int) -> str:
    return f"{Decimal(value) / 1_000_000:.6f}"


def _local_expiry(value: object) -> str:
    return datetime.fromtimestamp(float(str(value)), UTC).astimezone().isoformat(timespec="seconds")


@dataclass(frozen=True)
class PrivacyExecution:
    config: ProviderConfig
    config_key: str
    context: ExecutionContext
    gateway: Gateway | None


@dataclass(frozen=True)
class _Snapshot:
    config: ProviderConfig
    scope: ConsentScope
    request: ConsentRequest
    bindings: tuple[ConsentBinding, ...]
    data_types: tuple[str, ...]
    cap: int
    limit: int
    config_key: str
    cost_policy: CostPolicy | None


def _execution_key(config: ProviderConfig, kind: str, session_id: str) -> str:
    data = [
        config.provider_id,
        config.model,
        config.endpoint,
        config.execution_location,
        config.local_attestation.artifact_sha256 if config.local_attestation else None,
        config.context_window_tokens,
        config.max_output_tokens,
        kind,
        session_id,
    ]
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class CostIntent:
    mode: str
    currency: str
    start: int
    end: int
    cap: int
    limit: int
    general_acknowledged: bool


@dataclass(frozen=True)
class ProviderIntent:
    provider_id: str
    model: str
    endpoint: str
    context_window: int | None
    max_output: int
    proof: LocalModelAttestation | None = field(repr=False, compare=False)


@dataclass(frozen=True)
class ExecutionIntent:
    kind: str
    session_id: str
    settings: ProviderIntent
    scope: ConsentScope
    cost: CostIntent | None
    cancel: threading.Event = field(repr=False, compare=False)
    plan: PlanBinding
    auth: AuthBinding | None = field(repr=False, compare=False)


@dataclass(frozen=True)
class ViewIntent:
    kind: str
    provider: str | None
    endpoint: str | None
    data_type: str | None
    scope: ConsentScope | None
    session_id: str | None
    cost: CostIntent | None


@dataclass(frozen=True)
class PrivacyView:
    scope: dict[str, Any]
    unavailable: str | None
    account: dict[str, Any] | None
    balance: dict[str, int] | None
    legacy: bool
    records: list[dict[str, Any]]


@dataclass(frozen=True)
class ActionIntent:
    kind: str
    action: str
    provider: str
    endpoint: str
    data_type: str
    scope: ConsentScope
    config: ProviderConfig | None
    cost: CostIntent | None
    plan: PlanBinding
    reservation_id: str | None = None
    actual: int = 0
    confirmed: bool = False


@dataclass(frozen=True)
class ActionProposal:
    intent: ActionIntent
    version: int
    deadline: float
    cost_policy: CostPolicy | None = None


@dataclass(frozen=True)
class PrivacyReply:
    kind: str
    nonce: str
    generation: int
    tag: str
    value: object = field(default=None, repr=False)
    error_code: str | None = None


class PrivacyBackend:
    """No widget references; policy/query and native command lanes are separate."""

    def __init__(
        self,
        consents: ConsentStore,
        ledger: CostLedger,
        vault: CredentialVault,
        *,
        gateway: Gateway | None,
        notify_quote: Callable[[str, object], None],
    ) -> None:
        self.consents, self.ledger = consents, ledger
        self.credentials = CredentialService(vault, consents=consents)
        self.gateway = gateway
        self._notify_quote = notify_quote
        self._condition = threading.Condition()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="recoryn-privacy")
        self._capacity = threading.BoundedSemaphore(32)
        self._active = 0
        self._closing = False
        self._changes: dict[str, int] = {}
        self._revision = 0
        self.granted: dict[str, set[tuple[str, str, str, ConsentScope, int]]] = {
            "stt": set(),
            "summary": set(),
        }

    @property
    def closing(self) -> bool:
        with self._condition:
            return self._closing

    @property
    def idle(self) -> bool:
        with self._condition:
            return self._active == 0 and self.credentials.idle

    def submit(
        self,
        operation: Callable[[], object],
        *,
        kind: str,
        nonce: str,
        generation: int,
        tag: str,
        reply: Callable[[PrivacyReply], None],
    ) -> bool:
        if not self._capacity.acquire(blocking=False):
            return False
        with self._condition:
            if self._closing:
                self._capacity.release()
                return False
            self._active += 1

        def work() -> None:
            try:
                try:
                    answer = PrivacyReply(kind, nonce, generation, tag, operation())
                except Exception as error:
                    allowed = set(CODE_GROUPS) | {
                        "VAULT_WRITE_FAILED",
                        "VAULT_DELETE_FAILED",
                        "VAULT_INVALID_VALUE",
                        "SECURITY_STATE_UNAVAILABLE",
                        "INVALID_PRIVACY_ACTION",
                        "SETTLEMENT_CONFIRMATION_REQUIRED",
                    }
                    code = getattr(error, "code", None)
                    safe = code if type(code) is str and code in allowed else "TASK_FAILED"
                    answer = PrivacyReply(kind, nonce, generation, tag, error_code=safe)
                try:
                    reply(answer)
                except RuntimeError:
                    pass
            finally:
                with self._condition:
                    self._active -= 1
                    self._capacity.release()
                    self._condition.notify_all()

        self._pool.submit(work)
        return True

    def invalidate_kind(self, kind: str) -> int:
        self.credentials.invalidate_plan(kind)
        with self._condition:
            self._revision += 1
            self._changes[kind] = self._revision
            return self._revision

    def revoke_pending(self, kind: str) -> None:
        with self._condition:
            revision = self._changes.get(kind)
        if revision is None:
            return
        with self.consents.coordinator.hold():
            for provider, target, data_type, scope, version in tuple(self.granted[kind]):
                self.consents.revoke(
                    provider,
                    target,
                    data_type,
                    capability=kind,
                    scope=scope,
                    policy_version=version,
                )
            self.granted[kind].clear()
        with self._condition:
            if self._changes.get(kind) == revision:
                self._changes.pop(kind, None)

    def cost_policy(
        self, provider: str, values: CostIntent, *, advance: bool = False
    ) -> CostPolicy:
        old = self.ledger.account(provider, values.currency, values.start, values.end)
        version = int(old["policy_version"]) + int(advance) if old else 1
        return CostPolicy(
            values.mode,
            values.currency,
            values.start,
            values.end,
            values.cap,
            values.limit,
            version,
            cost_catalog.load_catalog().sha256,
            values.general_acknowledged,
        )

    def read_view(self, intent: ViewIntent) -> PrivacyView:
        self.revoke_pending(intent.kind)
        scope = self.consents.scope_view(
            intent.provider,
            intent.endpoint,
            intent.data_type,
            capability=intent.kind,
            scope=intent.scope,
            session_id=intent.session_id,
        )
        unavailable = self.ledger.availability()
        if unavailable is not None or intent.provider is None or intent.cost is None:
            return PrivacyView(scope, unavailable, None, None, False, [])
        values = intent.cost
        account = self.ledger.account(intent.provider, values.currency, values.start, values.end)
        balance = self.ledger.account_snapshot(
            intent.provider, values.currency, values.start, values.end
        )
        legacy = self.ledger.legacy_unscoped(intent.provider)
        records = self.ledger.reservations(intent.provider)
        return PrivacyView(scope, None, account, balance, legacy, records)

    def prepare_action(self, intent: ActionIntent) -> ActionProposal:
        self.revoke_pending(intent.kind)
        self.credentials.assert_plan(intent.plan)
        if intent.action == "reset_clock":
            return ActionProposal(intent, 0, 0)
        version, deadline = self.consents.policy_version, self.consents.grant_deadline
        policy = None
        if intent.action == "grant":
            self.credentials.check_grant_allowed(CredentialTarget(intent.provider, intent.endpoint))
            if intent.provider != "ollama" and (
                intent.cost is None or intent.cost.cap <= 0 or intent.cost.limit <= 0
            ):
                raise SecurityError("BUDGET_REQUIRED")
        if intent.action in {"budget", "adopt"}:
            if intent.cost is None:
                raise SecurityError("COST_REQUEST_INVALID")
            policy = self.cost_policy(
                intent.provider, intent.cost, advance=intent.action == "budget"
            )
        return ActionProposal(intent, version, deadline, policy)

    def commit_action(self, proposal: ActionProposal) -> None:
        intent = proposal.intent
        self.credentials.assert_plan(intent.plan)
        provider, target, kind = intent.provider, intent.endpoint, intent.kind
        with self.consents.coordinator.hold():
            self.credentials.assert_plan(intent.plan)
            if (
                intent.action not in {"reset_clock"}
                and proposal.version != self.consents.policy_version
            ):
                raise SecurityError("CONSENT_POLICY_CHANGED")
            if intent.action == "grant":
                with self.credentials.grant_gate(CredentialTarget(provider, target)):
                    if provider == "ollama":
                        proof = (
                            intent.config.local_attestation if intent.config is not None else None
                        )
                        if proof is None:
                            raise SecurityError("LOCAL_EXECUTION_UNVERIFIED")
                        self.consents.approve_local_endpoint(
                            target,
                            proof.artifact_sha256,
                            ttl_seconds=proof.expires_at_monotonic - time.monotonic(),
                        )
                    self.consents.grant(
                        provider,
                        target,
                        intent.data_type,
                        capability=kind,
                        scope=intent.scope,
                        policy_version=proposal.version,
                        expires_at=proposal.deadline,
                    )
                    self.granted[kind].add(
                        (provider, target, intent.data_type, intent.scope, proposal.version)
                    )
            elif intent.action == "revoke":
                self.consents.revoke(
                    provider,
                    target,
                    intent.data_type,
                    capability=kind,
                    scope=intent.scope,
                    policy_version=proposal.version,
                )
                self.granted[kind].discard(
                    (provider, target, intent.data_type, intent.scope, proposal.version)
                )
            elif intent.action == "budget":
                assert proposal.cost_policy is not None
                self.ledger.apply_policy(provider, proposal.cost_policy)
            elif intent.action == "adopt":
                assert proposal.cost_policy is not None
                self.ledger.adopt_legacy(provider, proposal.cost_policy, confirmed=True)
            elif intent.action == "settle":
                if not intent.confirmed or not intent.reservation_id:
                    raise SecurityError("SETTLEMENT_CONFIRMATION_REQUIRED")
                self.ledger.settle(intent.reservation_id, intent.actual)
            elif intent.action == "reset_clock":
                self.ledger.reset_clock(confirmed=True)
            elif intent.action != "refresh":
                raise SecurityError("INVALID_PRIVACY_ACTION")

    def _configuration(self, intent: ExecutionIntent) -> ProviderConfig:
        self.revoke_pending(intent.kind)
        self.credentials.assert_plan(intent.plan)
        values = intent.settings
        provider = values.provider_id
        config = ProviderConfig(
            provider,
            values.model or ("local" if provider == "faster_whisper" else ""),
            endpoint="" if provider == "faster_whisper" else parse_endpoint(values.endpoint).url,
            execution_location="local" if provider in {"faster_whisper", "ollama"} else "remote",
            local_attestation=values.proof if provider == "ollama" else None,
            context_window_tokens=values.context_window,
            max_output_tokens=values.max_output,
        )
        if provider == "ollama" and (
            values.proof is None
            or not values.proof.cloud_disabled
            or values.proof.endpoint != config.endpoint
            or values.proof.model != config.model
            or values.proof.expires_at_monotonic <= time.monotonic()
        ):
            raise SecurityError("LOCAL_EXECUTION_UNVERIFIED")
        return config

    def _snapshot(self, intent: ExecutionIntent, config: ProviderConfig) -> _Snapshot:
        key = _execution_key(config, intent.kind, intent.session_id)
        with self.consents.coordinator.hold():
            version = self.consents.policy_version
            self.consents.bind_session(intent.session_id)
            request = ConsentRequest(intent.session_id, 0, intent.kind, version)
            types = ("audio",) if intent.kind == "stt" else ("transcript", "context")
            bindings = self.consents.capture_bindings(
                config.provider_id, config.endpoint, types, scope=intent.scope, request=request
            )
            policy = (
                None
                if config.provider_id == "ollama" or intent.cost is None
                else self.cost_policy(config.provider_id, intent.cost)
            )
        snapshot = _Snapshot(
            config,
            intent.scope,
            request,
            bindings,
            types,
            intent.cost.cap if intent.cost is not None else 0,
            intent.cost.limit if intent.cost is not None else 0,
            key,
            policy,
        )
        return snapshot

    def prepare_execution(self, intent: ExecutionIntent) -> PrivacyExecution:
        config = self._configuration(intent)
        if config.provider_id == "faster_whisper":
            return PrivacyExecution(
                config,
                _execution_key(config, intent.kind, intent.session_id),
                ExecutionContext(cancel=intent.cancel),
                None,
            )
        snapshot = self._snapshot(intent, config)
        context = self._execution_context(snapshot, intent.cancel, intent.auth)
        gateway = self._gateway_for(snapshot, intent.plan, intent.auth)
        return PrivacyExecution(config, snapshot.config_key, context, gateway)

    def prepare_gateway(self, intent: ExecutionIntent) -> Gateway | None:
        """Prepare an unprivileged frozen root; the Gateway still checks every grant."""
        config = self._configuration(intent)
        if config.provider_id == "faster_whisper":
            return None
        return self._gateway_for(self._snapshot(intent, config), intent.plan, intent.auth)

    def _execution_context(
        self, snapshot: _Snapshot, cancel: threading.Event, auth: AuthBinding | None
    ) -> ExecutionContext:
        config = snapshot.config
        if not snapshot.bindings:
            raise SecurityError("CONSENT_REQUIRED")
        if config.provider_id == "ollama":
            return ExecutionContext(cancel=cancel)
        if snapshot.cap <= 0 or snapshot.limit <= 0:
            raise SecurityError("BUDGET_REQUIRED")
        cost_policy = snapshot.cost_policy
        if cost_policy is None:
            raise SecurityError("COST_REQUEST_INVALID")
        policy, ledger, notify = self.consents, self.ledger, self._notify_quote
        types, bindings = snapshot.data_types, snapshot.bindings
        provider, target = config.provider_id, config.endpoint

        def reserve(request: CostRequest) -> str:
            if (
                type(request) is not CostRequest
                or request.provider_id != provider
                or request.endpoint != target
                or request.model_revision != config.model
                or request.operation != snapshot.request.capability
                or request.data_type not in types
            ):
                raise SecurityError("BUDGET_SCOPE_MISMATCH")
            binding = next((item for item in bindings if item.data_type == request.data_type), None)
            if binding is None:
                raise SecurityError("CONSENT_REQUIRED")
            with policy.coordinator.hold():
                policy.validate_binding(binding)
                if auth is not None:
                    auth.service.assert_current(auth.ref, auth.plan)
                try:
                    quoted = ledger.quote_request(request, cost_policy)
                    reservation = ledger.reserve_quote(
                        uuid.uuid4().hex, quoted, cost_policy, request
                    )
                except SecurityError as error:
                    try:
                        notify(snapshot.request.capability, error.code)
                    except RuntimeError:
                        pass
                    raise
                try:
                    notify(snapshot.request.capability, quoted)
                except RuntimeError:
                    pass
                return reservation

        return ExecutionContext(cancel=cancel, reservation_factory=reserve)

    def _gateway_for(
        self, snapshot: _Snapshot, plan: PlanBinding, auth: AuthBinding | None
    ) -> Gateway:
        config, base = snapshot.config, self.gateway
        base_guard = base.dispatch_guard if base else None
        proof = config.local_attestation

        @contextmanager
        def plan_guard(permit: SendPermit) -> Iterator[None]:
            if (
                permit.provider_id != config.provider_id
                or permit.endpoint != config.endpoint
                or permit.data_type not in snapshot.data_types
                or permit.request != snapshot.request
                or permit.scope != snapshot.scope
            ):
                raise SecurityError("LOCAL_EXECUTION_UNVERIFIED")
            with ExitStack() as stack:
                if base_guard is not None:
                    stack.enter_context(base_guard(permit))
                if config.provider_id == "ollama":
                    if (
                        proof is None
                        or proof.endpoint != config.endpoint
                        or proof.model != config.model
                    ):
                        raise SecurityError("LOCAL_EXECUTION_UNVERIFIED")
                    stack.enter_context(proof.execution_guard())
                yield

        view = Gateway(
            self.consents,
            ledger=None if config.provider_id == "ollama" else self.ledger,
            transport=base.transport if base else None,
            timeout=base.timeout if base else 30,
            max_request_bytes=base.max_request_bytes if base else 32 * 1024 * 1024,
            max_response_bytes=base.max_response_bytes if base else 8 * 1024 * 1024,
            chunk_bytes=base.chunk_bytes if base else 64 * 1024,
            expected_grants=snapshot.bindings,
            dispatch_guard=plan_guard,
            auth_binding=auth,
        ).for_session(
            snapshot.request.session_id,
            snapshot.request.session_generation,
            capability=snapshot.request.capability,
            scope=snapshot.scope,
            policy_version=snapshot.request.policy_version,
        )
        view._plan_check = lambda: self.credentials.assert_plan(plan)
        return view

    def begin_shutdown(self) -> None:
        with self._condition:
            self._closing = True
        self.credentials.begin_shutdown()

    def await_shutdown(self, timeout: float = 5) -> bool:
        self.begin_shutdown()
        until = time.monotonic() + timeout
        with self._condition:
            done = self._condition.wait_for(lambda: self._active == 0, timeout)
        if not done or not self.credentials.await_shutdown(max(0, until - time.monotonic())):
            return False
        self._pool.shutdown(wait=True)
        return True


class _Controls(QGroupBox):
    def __init__(self, kind: str) -> None:
        super().__init__("음성 전사" if kind == "stt" else "선택적 요약")
        layout = QFormLayout(self)
        self.provider = QComboBox()
        choices = (
            (("로컬 Faster-Whisper", "faster_whisper"), ("OpenAI", "openai"), ("Gemini", "gemini"))
            if kind == "stt"
            else (
                ("요약 끔", "none"),
                ("로컬 Ollama", "ollama"),
                ("OpenAI", "openai"),
                ("Anthropic", "anthropic"),
                ("Gemini", "gemini"),
            )
        )
        for label, value in choices:
            self.provider.addItem(label, value)
        self.endpoint, self.model = QLineEdit(), QLineEdit()
        self.fact_declaration, self.fact_observation, self.server_trust = (
            QLabel(),
            QLabel(),
            QLabel(),
        )
        for fact_label in (self.fact_declaration, self.fact_observation, self.server_trust):
            fact_label.setWordWrap(True)
            fact_label.setTextFormat(Qt.TextFormat.PlainText)
            fact_label.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.context_window, self.max_output = QSpinBox(), QSpinBox()
        self.context_window.setRange(0, 2_000_000)
        self.context_window.setSpecialValueText("미확인 — 요약 실행 차단")
        self.max_output.setRange(1, 131072)
        self.max_output.setValue(1024)
        self.endpoint.setPlaceholderText("데이터를 받을 정확한 전체 API endpoint")
        self.model.setPlaceholderText("사용할 모델 ID — 자동 다운로드하지 않음")
        self.data_type = QComboBox()
        self.scope = QComboBox()
        self.scope.addItem("이 세션만 (기본)", "session")
        self.scope.addItem("현재 라이브러리 전체", "library")
        self.scope_info = QLabel("세션을 선택하세요 — 기본 거부")
        self.scope_info.setWordWrap(True)
        for label, value in (
            (("원본 음성", "audio"),)
            if kind == "stt"
            else (("전사 원문", "transcript"), ("중간 요약·문맥", "context"))
        ):
            self.data_type.addItem(label, value)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("명시적으로 저장할 새 키")
        self.save_key, self.delete_key = (
            QPushButton("이 endpoint 키 저장"),
            QPushButton("키 삭제·권한 철회"),
        )
        self.total, self.per_request = QDoubleSpinBox(), QDoubleSpinBox()
        for spin in (self.total, self.per_request):
            spin.setDecimals(6)
            spin.setRange(0, 1_000_000)
            spin.setPrefix("USD ")
        self.apply_budget = QPushButton("제공업체·통화·기간 한도 적용")
        self.reset_clock = QPushButton("시계 기준 재설정 (확인 필요)")
        self.cost_mode = QComboBox()
        self.cost_mode.addItem("엄격 예산 (기본)", "strict")
        self.cost_mode.addItem("일반 — 미검증 cap 위험 확인 필요", "general")
        self.general_acknowledged = False
        self.currency = QLineEdit("USD")
        self.currency.setMaxLength(3)
        self.currency.setPlaceholderText("ISO 통화 코드")
        start = int(time.time()) // 86400 * 86400
        self.period_start = QLineEdit(
            datetime.fromtimestamp(start, UTC).isoformat(timespec="seconds")
        )
        self.period_end = QLineEdit(
            datetime.fromtimestamp(start + 86400, UTC).isoformat(timespec="seconds")
        )
        for edit in (self.period_start, self.period_end):
            edit.setMaxLength(32)
        self.period_info = QLabel("UTC 반개구간 — 새 기간은 명시적으로 적용하세요")
        self.period_info.setWordWrap(True)
        self.quote_info = QLabel(
            "요청 생성 전 — 상한 미계산 / 검증 가격 없음 / strict는 미확인 유료 전송을 차단합니다"
        )
        self.quote_info.setWordWrap(True)
        self.adopt_legacy = QPushButton("이전 비용 이력의 통화·기간 확인 후 승계")
        self.allow, self.revoke = (
            QPushButton("선택한 데이터 범위만 허용"),
            QPushButton("선택 범위 철회"),
        )
        self.status = QLabel("기본 거부 — 아직 전송을 허용하지 않았습니다")
        self.status.setWordWrap(True)
        self.balance = QLabel("미확인 비용은 재시작·세션 삭제로 사라지지 않습니다")
        self.balance.setWordWrap(True)
        self.requests = QComboBox()
        self.actual = QDoubleSpinBox()
        self.actual.setDecimals(6)
        self.actual.setRange(0, 1_000_000)
        self.actual.setPrefix("확인 금액 USD ")
        self.confirm_actual = QCheckBox("제공업체 사용량·청구에서 실제 금액을 확인했습니다")
        self.settle, self.refresh = (
            QPushButton("선택 요청의 확인 금액 정산"),
            QPushButton("비용 갱신"),
        )
        self.settle.setEnabled(False)
        self.confirm_actual.toggled.connect(self.settle.setEnabled)
        for label, widget in (
            ("제공업체", self.provider),
            ("수신 endpoint", self.endpoint),
            ("모델", self.model),
            ("제공업체 기능 선언", self.fact_declaration),
            ("제공업체 최근 관측", self.fact_observation),
            ("서버 신뢰 범위", self.server_trust),
            ("검증한 모델 컨텍스트 한도", self.context_window),
            ("최대 출력 토큰", self.max_output),
            ("동의할 데이터", self.data_type),
            ("동의 범위 선택", self.scope),
            ("범위·만료·정책", self.scope_info),
            ("새 BYOK 키", self.key),
            ("키 저장", self.save_key),
            ("키 폐기", self.delete_key),
            ("비용 모드", self.cost_mode),
            ("비용 통화", self.currency),
            ("기간 시작 UTC (포함)", self.period_start),
            ("기간 종료 UTC (미포함)", self.period_end),
            ("기간 현지 시각", self.period_info),
            ("제공업체 전체 한도", self.total),
            ("요청 1회 비용 상한", self.per_request),
            ("예산", self.apply_budget),
            ("시계 복구", self.reset_clock),
            ("이전 이력", self.adopt_legacy),
            ("요청 상한·가격 근거", self.quote_info),
            ("동의", self.allow),
            ("철회", self.revoke),
            ("권한 상태", self.status),
            ("비용 상태", self.balance),
            ("요청 내역", self.requests),
            ("실제 확인 금액", self.actual),
            ("정산 확인", self.confirm_actual),
            ("정산", self.settle),
            ("갱신", self.refresh),
        ):
            widget.setObjectName(f"{kind}_{widget.__class__.__name__}_{label}")
            widget.setAccessibleName(label)
            layout.addRow(label, widget)


class PrivacyPanel(QWidget):
    quote_ready = Signal(str, object)
    work_ready = Signal(object)

    def __init__(
        self,
        consents: ConsentStore,
        ledger: CostLedger,
        vault: CredentialVault,
        *,
        gateway: Gateway | None = None,
        parent: QWidget | None = None,
        provider_facts: Mapping[str, ObservationState] | None = None,
    ) -> None:
        super().__init__(parent)
        self.consents, self.ledger, self.vault, self._gateway = consents, ledger, vault, gateway
        self.backend = PrivacyBackend(
            consents, ledger, vault, gateway=gateway, notify_quote=self.quote_ready.emit
        )
        self._selection_generation = 0
        self._closed = False
        self._views: dict[str, PrivacyView] = {}
        self._desired_views: dict[str, ViewIntent] = {}
        self._sent_views: dict[str, ViewIntent] = {}
        self._view_pending: dict[str, bool] = {}
        self._view_nonces: dict[str, str] = {}
        self._command_nonces: dict[str, str] = {}
        self._status_errors: dict[str, str] = {}
        self.work_ready.connect(self._on_work_ready)
        self.announcer = a11y.Announcer()
        self._attestation: LocalModelAttestation | None = None
        self._selected_session: str | None = None
        self._selection_pending = False
        self._selection_origin: str | None = None
        self._scope_retry = QTimer(self)
        self._scope_retry.setSingleShot(True)
        self._scope_retry.setInterval(50)
        self._scope_retry.timeout.connect(self._retry_scope_views)
        self._granted = self.backend.granted
        self.controls = {kind: _Controls(kind) for kind in ("stt", "summary")}
        self.provider_facts = {
            kind: provider_facts[kind]
            if provider_facts and kind in provider_facts
            else ObservationState()
            for kind in self.controls
        }
        self._fact_epochs = {kind: 0 for kind in self.controls}
        self._fact_notice = {kind: "" for kind in self.controls}
        self._facts_timer = QTimer(self)
        self._facts_timer.setInterval(1000)
        self._facts_timer.timeout.connect(self._refresh_fact_views)
        self._request_info: dict[str, list[dict[str, object]]] = {"stt": [], "summary": []}
        self.quote_ready.connect(self._quote_display)
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel("외부 전송은 기본 거부입니다. 음성 전사와 요약은 독립적으로 허용하세요.")
        )
        layout.addWidget(
            QLabel(
                "로컬 Whisper 경로·CPU/GPU는 녹음 화면에서 설정합니다. 표시한 비용 상한은 가격표가 아닙니다."
            )
        )
        tabs = QTabWidget()
        layout.addWidget(tabs)
        for kind, controls in self.controls.items():
            tabs.addTab(controls, "전사" if kind == "stt" else "요약")
            controls.allow.clicked.connect(lambda checked=False, k=kind: self._action(k, "grant"))
            controls.revoke.clicked.connect(lambda checked=False, k=kind: self._action(k, "revoke"))
            # G-P12: Enter and Space activate these explicit commands once; arrows/Tab only move.
            for button in (
                controls.allow,
                controls.revoke,
                controls.apply_budget,
                controls.reset_clock,
                controls.adopt_legacy,
                controls.settle,
                controls.refresh,
            ):
                a11y.activate_button(button)
            a11y.name(
                controls.revoke,
                "선택 범위 전송 동의 철회",
                "이 기능·범위의 동의를 철회합니다. 이후 새 전송이 차단되며 이미 넘긴 데이터는 "
                "회수할 수 없습니다. 다른 범위의 동의는 바꾸지 않습니다.",
            )
            a11y.name(
                controls.allow,
                "선택한 데이터 범위만 전송 동의",
                "확인 창이 뜨면 기본은 거부(아니요)이며 Esc도 거부입니다.",
            )
            controls.save_key.clicked.connect(lambda checked=False, k=kind: self._action(k, "save"))
            controls.delete_key.clicked.connect(
                lambda checked=False, k=kind: self._action(k, "delete")
            )
            controls.apply_budget.clicked.connect(
                lambda checked=False, k=kind: self._action(k, "budget")
            )
            controls.reset_clock.clicked.connect(
                lambda checked=False, k=kind: self._action(k, "reset_clock")
            )
            controls.refresh.clicked.connect(
                lambda checked=False, k=kind: self._action(k, "refresh")
            )
            controls.settle.clicked.connect(lambda checked=False, k=kind: self._action(k, "settle"))
            controls.requests.currentIndexChanged.connect(
                lambda index, k=kind: self._request_currency(k)
            )
            controls.adopt_legacy.clicked.connect(
                lambda checked=False, k=kind: self._action(k, "adopt")
            )
            controls.cost_mode.currentIndexChanged.connect(
                lambda index, k=kind: self._mode_changed(k)
            )
            for edit in (controls.currency, controls.period_start, controls.period_end):
                edit.textChanged.connect(lambda text, k=kind: self._cost_changed(k))
            controls.provider.currentIndexChanged.connect(lambda index, k=kind: self._changed(k))
            controls.endpoint.textChanged.connect(lambda text, k=kind: self._changed(k))
            controls.model.textChanged.connect(lambda text, k=kind: self._changed(k))
            controls.scope.currentIndexChanged.connect(lambda index, k=kind: self._show_scope(k))
            controls.data_type.currentIndexChanged.connect(
                lambda index, k=kind: self._show_scope(k)
            )
            for setting in (
                controls.context_window,
                controls.max_output,
                controls.total,
                controls.per_request,
            ):
                setting.valueChanged.connect(lambda value, k=kind: self._changed(k))
            self._show_scope(kind)
            self._cost_unavailable(kind)
            self.refresh_provider_facts(kind)
        self._facts_timer.start()

    def _refresh_fact_views(self) -> None:
        for kind in self.controls:
            self.refresh_provider_facts(kind)

    def provider_identity(self, kind: str) -> FactIdentity:
        """Display identity only; deliberately bypasses execution/vault preparation."""
        control = self.controls[kind]
        endpoint = control.endpoint.text()
        try:
            endpoint = parse_endpoint(endpoint).url
        except SecurityError:
            endpoint = ""  # invalid URL remains editable, never an observed destination
        return FactIdentity(
            str(control.provider.currentData()),
            kind,
            endpoint,
            control.model.text(),
            inference_endpoint=endpoint,
            credential_revision=self._fact_epochs[kind],
            consent_epoch=self._fact_epochs[kind],
            session_generation=self._selected_session or "",
        )

    def refresh_provider_facts(self, kind: str) -> None:
        """Render memory-only facts, including expiry; never ask a service anything."""
        control = self.controls[kind]
        identity = self.provider_identity(kind)
        state = self.provider_facts[kind]
        state.bind(identity)
        try:
            declaration = describe(identity.provider_id, kind)
        except ProviderError:
            text = "기능 선언 없음 · 실제 서비스 미검증"
        else:
            feature = "전사" if kind == "stt" else "요약"
            text = (
                f"기능 선언: {feature} {'지원' if declaration.supported else '미지원'}"
                " · adapter 선언, 실제 서비스 미검증"
            )
        control.fact_declaration.setText(text)
        snapshot = state.snapshot()
        observed = snapshot.observation
        text = FACTS_UNKNOWN
        if observed.level is ProviderEvidenceLevel.OBSERVED:
            assert snapshot.observed_at is not None
            stamp = datetime.fromtimestamp(snapshot.observed_at, UTC).isoformat(timespec="seconds")
            text = (
                f"최근 관측: 이 앱이 {identity.endpoint}에서 {stamp}에 모델 목록 응답을 "
                "받았습니다 · 인증·실행 보장 아님"
            )
            if observed.selected_model_listed is False:
                text += " · 선택한 모델이 목록에 없었습니다 · 기능 미지원 판정 아님"
        elif observed.reason == "EXPIRED":
            text = "관측 만료 · 이 버전은 제공업체에 확인 요청을 보내지 않습니다"
        control.fact_observation.setText(text)
        note = SERVER_TRUST if identity.provider_id == "ollama" else ""
        if identity.provider_id in {"openai", "anthropic", "gemini"} and control.endpoint.text():
            standard = default_endpoint(identity.provider_id, kind, identity.model)
            if standard is None or identity.endpoint != parse_endpoint(standard).url:
                note = SERVER_TRUST_GENERAL
        if (
            note
            and identity.provider_id == "ollama"
            and self._attestation is not None
            and self._attestation.endpoint == identity.endpoint
            and self._attestation.model == identity.model
            and self._attestation.expires_at_monotonic > time.monotonic()
        ):
            note += " 앱 소유 서버 증명과 모델 실행 조건은 별도 확인합니다."
        control.server_trust.setText(note)
        form = control.layout()
        assert isinstance(form, QFormLayout)
        form.setRowVisible(control.server_trust, bool(note))
        if note != self._fact_notice[kind]:
            self._fact_notice[kind] = note
            if note:
                a11y.qt_announce(control.server_trust, note, a11y.POLITE)

    def focus_blocked_action(self, kind: str, action_id: str) -> None:
        """Navigation only: no grant, vault read, cost reservation or execution."""
        controls = self.controls.get(kind)
        if controls is None:
            return
        target = {
            "consent": controls.scope,
            "auth": controls.key,
            "budget": controls.per_request,
            "price": controls.quote_info,
            "clock": controls.reset_clock,
            "cost_history": controls.requests,
            "model": controls.model,
            "resource": controls.model,
        }.get(action_id)
        if target is not None:
            if action_id == "price":
                target.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            target.setFocus()
            controls.ensurePolished()

    def select_session(self, session_id: str | None) -> None:
        previous = self._selection_origin if self._selection_pending else self._selected_session
        changed = session_id != previous
        if changed:
            self._selection_generation += 1
            self._views.clear()
        self._selected_session = session_id
        self._selection_pending = False
        for kind, control in self.controls.items():
            if changed:
                self.provider_facts[kind].invalidate()
                control.scope.setCurrentIndex(0)
            self._show_scope(kind)
            self.refresh_provider_facts(kind)

    def selection_pending(self) -> None:
        """A list rebuild may briefly have no row; never authorize that gap."""
        if not self._selection_pending:
            self._selection_origin = self._selected_session
        self._selected_session = None
        self._selection_pending = True
        for control in self.controls.values():
            control.allow.setEnabled(False)
            control.revoke.setEnabled(False)
            control.scope_info.setText("선택 갱신 중 — 전송 불가")

    def _retry_scope_views(self) -> None:
        for kind in self.controls:
            self._show_scope(kind)

    def closeEvent(self, event: Any) -> None:
        self._closed = True
        self.backend.begin_shutdown()
        self._scope_retry.stop()
        self._facts_timer.stop()
        super().closeEvent(event)

    def _selected_scope(self, kind: str, session_id: str | None = None) -> ConsentScope:
        if self._selection_pending and session_id is None:
            raise SecurityError("CONSENT_REQUIRED")
        if self._controls(kind).scope.currentData() == "library":
            return ConsentScope.library()
        selected = self._selected_session if session_id is None else session_id
        if selected is None:
            raise SecurityError("CONSENT_REQUIRED")
        return ConsentScope.session(selected)

    def _render_scope(self, kind: str) -> str:
        control = self._controls(kind)
        if self._selection_pending:
            return "선택 갱신 중 — 실행 준비 시 대상·권한을 확인합니다"
        control.setEnabled(True)
        library = control.scope.currentData() == "library"
        enabled = library or self._selected_session is not None
        control.allow.setEnabled(enabled)
        control.revoke.setEnabled(enabled)
        label = (
            "현재 라이브러리의 현재·새 세션"
            if library
            else f"이 세션만: {self._selected_session or '선택 없음'}"
        )
        cached = self._views.get(kind)
        view = (
            cached.scope
            if cached is not None
            else {
                "state": "checking",
                "library": None,
                "selected": None,
            }
        )
        state = view["state"]
        if state != "ready" and not (state == "deleted" and library):
            control.allow.setEnabled(False)
            control.revoke.setEnabled(False)
            message = {
                "deleted": "삭제 진행 중 — 전송 불가",
                "checking": "동의 정보 확인 중",
                "unavailable": "동의 정보 확인 불가 — 전송 불가",
            }[str(state)]
            control.scope_info.setText(label + f" / 기능 {kind} / " + message)
            if state == "checking":
                self._scope_retry.start()
            return message
        detail = f"{label} / 기능 {kind} / 정책 version {view['version']} / 현재 실행만"
        if state == "deleted":
            detail += f" / 선택 세션 {self._selected_session}: 삭제 진행 중 — 이 세션 전송 불가"
        whole = view["library"]
        if isinstance(whole, dict) and whole["state"] == "active":
            detail += " / 전체 허용 유지 중 — 전체 범위를 선택해 철회"
        info = view["selected"]
        status = "동의 없음 — 실행 준비 시 새 동의가 필요합니다"
        if isinstance(info, dict):
            if info["state"] == "active":
                detail += " / 만료 " + _local_expiry(info["expires"])
                status = "동의 활성 — 실행 준비 시 세션·권한을 다시 확인합니다"
            else:
                status = {
                    "previous": "이전 실행 — 다시 동의 필요",
                    "revoked": "철회됨 — 다시 동의 필요",
                    "expired": "만료됨 — 다시 동의 필요",
                    "local_unverified": "로컬 실행 확인 필요",
                }[str(info["state"])]
                detail += " / " + status
        else:
            detail += " / 기본 거부"
        control.scope_info.setText(detail)
        return status

    def _confirm_library(
        self, kind: str, provider: str, target: str, data_type: str, version: int, deadline: float
    ) -> bool:
        text = (
            f"현재 라이브러리의 현재·새 세션 전체를 허용합니다. 현재 실행만 유효합니다.\n"
            f"기능: {kind}\n데이터 종류: {data_type}\n제공업체: {provider}\nendpoint: {target}\n"
            f"정책 version: {version}\n만료: {_local_expiry(deadline)}\n"
            "철회 뒤 새 전송 단위는 차단되지만 이미 OS/TLS에 넘긴 bytes는 회수할 수 없습니다."
        )
        return a11y.confirm(
            self,
            "라이브러리 전체 전송 동의",
            text,
            still_current=self._same_selection(),
            fallback=self._safe_focus(kind),
        )[0]

    def _controls(self, kind: str) -> _Controls:
        if kind not in self.controls:
            raise SecurityError("INVALID_PROVIDER_KIND")
        return self.controls[kind]

    def _scope(self, kind: str) -> tuple[str, str, str]:
        control = self._controls(kind)
        provider = str(control.provider.currentData())
        if provider in {"none", "faster_whisper"}:
            raise ProviderError("CAPABILITY_UNSUPPORTED")
        return (
            provider,
            parse_endpoint(control.endpoint.text()).url,
            str(control.data_type.currentData()),
        )

    @staticmethod
    def _vault_key(provider: str, endpoint: str) -> str:
        return provider + "_" + hashlib.sha256(endpoint.encode("utf-8")).hexdigest()

    def _changed(self, kind: str) -> None:
        self._fact_epochs[kind] += 1
        self.refresh_provider_facts(kind)
        self._command_nonces[kind] = uuid.uuid4().hex
        self._status_errors.pop(kind, None)
        self._views.pop(kind, None)
        self.backend.invalidate_kind(kind)
        self.controls[kind].status.setText("설정 변경 — 선택한 범위를 다시 허용하세요")
        self._request_view(kind)

    def set_local_attestation(self, attestation: LocalModelAttestation | None) -> None:
        self._changed("summary")
        self._attestation = attestation
        if attestation is not None:
            control = self.controls["summary"]
            control.endpoint.setText(attestation.endpoint)
            control.model.setText(attestation.model)

    def provider_config(self, kind: str) -> ProviderConfig:
        control = self._controls(kind)
        provider = str(control.provider.currentData())
        if provider == "none":
            raise ProviderError("CAPABILITY_UNSUPPORTED")
        if provider == "faster_whisper":
            return ProviderConfig(
                provider, control.model.text() or "local", execution_location="local"
            )
        _, target, _ = self._scope(kind)
        proof = self._attestation if provider == "ollama" else None
        if provider == "ollama" and (
            proof is None
            or not proof.cloud_disabled
            or proof.endpoint != target
            or proof.model != control.model.text()
            or proof.expires_at_monotonic <= time.monotonic()
        ):
            raise SecurityError("LOCAL_EXECUTION_UNVERIFIED")
        return ProviderConfig(
            provider,
            control.model.text(),
            endpoint=target,
            execution_location="local" if provider == "ollama" else "remote",
            local_attestation=proof,
            context_window_tokens=control.context_window.value() or None,
            max_output_tokens=control.max_output.value(),
        )

    def config_key(self, kind: str, *, session_id: str) -> str:
        if str(self._controls(kind).provider.currentData()) == "none":
            return hashlib.sha256(b"summary:none").hexdigest()
        config = self.provider_config(kind)
        return self._config_key(config, kind, session_id)

    def _config_key(self, config: ProviderConfig, kind: str, session_id: str) -> str:
        return _execution_key(config, kind, session_id)

    def _period(self, kind: str) -> tuple[int, int]:
        control = self._controls(kind)
        values: list[int] = []
        try:
            for text in (control.period_start.text(), control.period_end.text()):
                value = datetime.fromisoformat(text)
                if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
                    raise ValueError
                stamp = value.timestamp()
                if stamp < 0 or int(stamp) != stamp:
                    raise ValueError
                values.append(int(stamp))
            if values[1] <= values[0]:
                raise ValueError
        except (ValueError, OverflowError, OSError):
            raise SecurityError("COST_PERIOD_CHANGED") from None
        return values[0], values[1]

    def _cost_policy(self, kind: str, *, advance: bool = False) -> CostPolicy:
        values = self._cost_intent(kind)
        view = self._views.get(kind)
        old = view.account if view is not None else None
        version = int(old["policy_version"]) + int(advance) if old else 1
        return CostPolicy(
            values.mode,
            values.currency,
            values.start,
            values.end,
            values.cap,
            values.limit,
            version,
            cost_catalog.load_catalog().sha256,
            values.general_acknowledged,
        )

    def _confirm_general(self, kind: str) -> bool:
        return a11y.confirm(
            self,
            "미검증 비용 위험 확인",
            "일반 모드는 가격 또는 요청 상한을 검증하지 못해도 사용자 cap을 예약할 수 있습니다.\n"
            "USER_CAP은 실제 최대 청구액의 보장이 아니며 strict 합격 근거가 아닙니다. "
            "미확인 비용은 철회·재시작으로 해제되지 않습니다. 중복 청구 위험이 있습니다. "
            "이 선택은 전송 동의를 대신하지 않습니다. 일반 모드를 직접 선택하시겠습니까?",
            still_current=self._same_selection(),
            fallback=self._safe_focus(kind),
        )[0]

    def _safe_focus(self, kind: str) -> QWidget:
        """Where focus goes when a modal's opener is gone: the kind's scope list."""
        return self._controls(kind).scope

    def _same_selection(self) -> Callable[[], bool]:
        """Focus returns to a modal's opener only while the same session is selected."""
        opened = self._selected_session
        return lambda: self._selected_session == opened

    def _mode_changed(self, kind: str) -> None:
        control = self._controls(kind)
        general = control.cost_mode.currentData() == "general"
        control.general_acknowledged = bool(general and self._confirm_general(kind))
        if general and not control.general_acknowledged:
            previous = control.cost_mode.blockSignals(True)
            control.cost_mode.setCurrentIndex(0)
            control.cost_mode.blockSignals(previous)
        self._cost_changed(kind)

    def _cost_changed(self, kind: str) -> None:
        control = self._controls(kind)
        code = control.currency.text()
        for spin in (control.total, control.per_request):
            spin.setPrefix(code + " ")
        try:
            start, end = self._period(kind)
            control.period_info.setText(
                f"현지 [{_local_expiry(start)}, {_local_expiry(end)}) / UTC 기간은 자동 갱신하지 않습니다"
            )
        except SecurityError as error:
            control.period_info.setText(error.code + " — 명시 UTC 기간을 확인하세요")
        control.quote_info.setText(
            "요청 생성 전 — 상한 미계산 / "
            + (
                "일반 모드: 미검증 USER_CAP 가능"
                if control.general_acknowledged
                else "strict: 검증 가격·상한이 없으면 전송 차단"
            )
        )
        self._changed(kind)

    def _quote_display(self, kind: str, value: object) -> None:
        control = self._controls(kind)
        if not isinstance(value, CostQuote):
            control.quote_info.setText(str(value) + " — 요청 차단, 상한 검증 미완료")
            return
        policy = value.policy
        facts = (
            f"마지막 요청 기준(현재 설정과 다를 수 있음): {value.kind} / 모드 {policy.mode} / 통화 {policy.currency} / "
            f"예약 U {_usd(value.amount)} / 사용자 cap C {_usd(policy.cap)} / "
            f"입력 상한 {value.input_upper if value.input_upper is not None else '미상'} / "
            f"출력 상한 {value.output_upper if value.output_upper is not None else '미상'} / "
            f"비용 정책 version {policy.policy_version} / 가격표 {policy.catalog_digest}"
        )
        if value.price_as_of_utc is None:
            facts += " / 가격 기준·만료 미상 / 미검증 사유 " + str(value.reason)
        else:
            facts += f" / 가격 기준 {_local_expiry(value.price_as_of_utc)} / 만료 {_local_expiry(value.valid_until_utc)} / 근거 {value.profile_id}"
        control.quote_info.setText(facts)

    def _cost_unavailable(self, kind: str) -> bool:
        control = self.controls[kind]
        cached = self._views.get(kind)
        if cached is None:
            control.balance.setText("비용 정보 확인 중")
            return True
        unavailable = cached.unavailable
        control.reset_clock.setEnabled(unavailable == "COST_CLOCK_INVALID")
        if unavailable is not None:
            control.balance.setText(
                (
                    "시계 확인 필요 — "
                    if unavailable == "COST_CLOCK_INVALID"
                    else "비용 이력 확인 필요 — "
                )
                + unavailable
                + " / 유료 원격 전송 차단; 녹음·로컬 기능은 계속 사용할 수 있습니다"
            )
            return True
        return False

    def _render_cost(self, kind: str) -> None:
        control = self.controls[kind]
        if self._cost_unavailable(kind):
            return
        cached = self._views.get(kind)
        if cached is None or cached.balance is None:
            return
        provider, _, _ = self._scope(kind)
        start, end = self._period(kind)
        code = control.currency.text()
        balance, account, legacy = cached.balance, cached.account, cached.legacy
        control.adopt_legacy.setEnabled(legacy)
        records = cached.records
        other = sum(
            1
            for row in records
            if row["state"] in {"RESERVED", "UNKNOWN"}
            and (row.get("currency"), row.get("period_start_utc"), row.get("period_end_utc"))
            != (code, start, end)
        )
        control.balance.setText(
            (
                "COST_PLAN_UNDERESTIMATED — 과소 예약 이력: 신규 지출 차단 / "
                if account is not None and account["blocked"]
                else ""
            )
            + ("예산 미적용 — 제공업체·통화·기간 한도 적용 필요 / " if account is None else "")
            + ("LEGACY_UNSCOPED — 통화·기간 명시 승계 전 신규 지출 차단 / " if legacy else "")
            + code
            + " 확정 "
            + _usd(balance["confirmed"])
            + " / 예약 "
            + _usd(balance["reserved"])
            + " / UNKNOWN "
            + _usd(balance["unknown_exposure"])
            + " / 잔여 "
            + _usd(balance["available"])
            + f" / UTC [{start}, {end})"
            + (f" / 다른 통화·기간 미정산 {other}건 — 신규 지출 보류" if other else "")
        )
        self._request_info[kind] = records
        control.requests.clear()
        for request in records:
            control.requests.addItem(
                str(request["request_id"])
                + " / "
                + str(request["state"])
                + " / "
                + str(request.get("quote_kind"))
                + " / "
                + str(request.get("currency") or "통화 미확정")
                + f" / UTC [{request.get('period_start_utc')}, {request.get('period_end_utc')})",
                str(request["reservation_id"]),
            )
        self._request_currency(kind)

    def _request_currency(self, kind: str) -> None:
        control = self.controls[kind]
        current = next(
            (
                r
                for r in self._request_info[kind]
                if r["reservation_id"] == control.requests.currentData()
            ),
            None,
        )
        code = current.get("currency") if current else control.currency.text()
        control.actual.setPrefix("확인 금액 " + str(code or "통화 미확정") + " ")
        control.confirm_actual.setChecked(False)

    def _cost_intent(self, kind: str) -> CostIntent:
        control = self._controls(kind)
        start, end = self._period(kind)
        return CostIntent(
            str(control.cost_mode.currentData()),
            control.currency.text(),
            start,
            end,
            _micros(control.per_request),
            _micros(control.total),
            control.general_acknowledged,
        )

    def capture_execution(
        self, kind: str, session_id: str, cancel: threading.Event
    ) -> ExecutionIntent:
        control = self._controls(kind)
        provider = str(control.provider.currentData())
        values = ProviderIntent(
            provider,
            control.model.text(),
            control.endpoint.text(),
            control.context_window.value() or None,
            control.max_output.value(),
            self._attestation,
        )
        auth = None
        if provider in {"openai", "anthropic", "gemini"}:
            try:
                auth = self.backend.credentials.capture_binding(
                    CredentialTarget(provider, values.endpoint), kind
                )
            except SecurityError:
                pass
        cost = None if provider in {"faster_whisper", "ollama"} else self._cost_intent(kind)
        return ExecutionIntent(
            kind,
            session_id,
            values,
            self._selected_scope(kind, session_id),
            cost,
            cancel,
            self.backend.credentials.capture_plan(kind),
            auth,
        )

    def _capture_view(self, kind: str) -> ViewIntent:
        try:
            provider, endpoint, data_type = self._scope(kind)
        except (SecurityError, ProviderError):
            provider, endpoint, data_type = None, None, None
        try:
            scope = self._selected_scope(kind)
        except SecurityError:
            scope = None
        try:
            cost = self._cost_intent(kind)
        except SecurityError:
            cost = None
        return ViewIntent(kind, provider, endpoint, data_type, scope, self._selected_session, cost)

    def _request_view(self, kind: str) -> None:
        if self._closed or self.backend.closing:
            return
        intent = self._capture_view(kind)
        self._desired_views[kind] = intent
        if self._view_pending.get(kind):
            return
        nonce = uuid.uuid4().hex
        self._view_nonces[kind] = nonce
        self._sent_views[kind] = intent
        self._view_pending[kind] = True
        accepted = self.backend.submit(
            lambda: self.backend.read_view(intent),
            kind=kind,
            nonce=nonce,
            generation=self._selection_generation,
            tag="view",
            reply=self.work_ready.emit,
        )
        if not accepted:
            self._view_pending[kind] = False
            self._scope_retry.start()

    def _show_scope(self, kind: str) -> str:
        self._request_view(kind)
        return self._render_scope(kind)

    def _refresh(self, kind: str) -> None:
        self._request_view(kind)

    def _on_work_ready(self, reply: PrivacyReply) -> None:
        kind = reply.kind
        if reply.tag == "view":
            self._view_pending[kind] = False
        if self._closed or self.backend.closing:
            return
        if reply.tag == "view":
            if (
                reply.generation != self._selection_generation
                or reply.nonce != self._view_nonces.get(kind)
                or self._sent_views.get(kind) != self._desired_views.get(kind)
            ):
                self._request_view(kind)
                return
            if isinstance(reply.value, PrivacyView):
                self._views[kind] = reply.value
            else:
                self._views[kind] = PrivacyView(
                    {"state": "unavailable", "library": None, "selected": None},
                    reply.error_code or "SECURITY_STATE_UNAVAILABLE",
                    None,
                    None,
                    False,
                    [],
                )
            self._render_cost(kind)
            status = self._render_scope(kind)
            self.controls[kind].status.setText(self._status_errors.get(kind) or status)
            return
        if (
            reply.generation != self._selection_generation
            or reply.nonce != self._command_nonces.get(kind)
        ):
            return
        error = reply.error_code
        if isinstance(reply.value, KeyResult):
            error = reply.value.error_code
        if error is not None:
            self._status_errors[kind] = error
            self.controls[kind].status.setText(error)
            self._request_view(kind)
            return
        if reply.tag == "proposal":
            if not isinstance(reply.value, ActionProposal):
                return
            proposal = reply.value
            if not self._confirm_proposal(proposal):
                return
            if (
                self._closed
                or self.backend.closing
                or reply.nonce != self._command_nonces.get(kind)
            ):
                return

            def commit() -> ActionProposal:
                self.backend.commit_action(proposal)
                return proposal

            if not self.backend.submit(
                commit,
                kind=kind,
                nonce=reply.nonce,
                generation=reply.generation,
                tag="committed",
                reply=self.work_ready.emit,
            ):
                self._status_errors[kind] = "RESOURCE_EXHAUSTED"
                self.controls[kind].status.setText("RESOURCE_EXHAUSTED")
            return
        if isinstance(reply.value, ActionProposal) and reply.value.intent.action == "revoke":
            intent = reply.value.intent
            self.announcer.announce(
                "privacy",
                self.controls[kind].revoke,
                "REVOCATION_PERSISTED",
                f"{kind} 전송 동의 철회를 저장했습니다 · 이미 전송한 결과는 별도로 표시합니다",
                version=(
                    "revoke",
                    kind,
                    intent.provider,
                    intent.endpoint,
                    intent.data_type,
                    intent.scope.kind,
                    reply.value.version,
                ),
            )
        self._request_view(kind)
        if isinstance(reply.value, ActionProposal) and reply.value.intent.action == "reset_clock":
            for control in self.controls.values():
                control.balance.setText("시계 기준 재설정 완료")
            for target_kind in self.controls:
                self._request_view(target_kind)

    def _confirm_proposal(self, proposal: ActionProposal) -> bool:
        intent, kind = proposal.intent, proposal.intent.kind
        if intent.action == "grant" and intent.scope.kind == "library":
            return self._confirm_library(
                kind,
                intent.provider,
                intent.endpoint,
                intent.data_type,
                proposal.version,
                proposal.deadline,
            )
        if intent.action == "reset_clock":
            return a11y.confirm(
                self,
                "시계 기준 재설정 확인",
                "운영체제의 현재 시각을 확인하셨습니까? 시계 기준 변경은 감사 이력에 남습니다. "
                "기존 예약·UNKNOWN·확정 지출은 줄어들지 않습니다. 모든 기간의 같은 제공업체·통화 "
                "확정액을 현재 예산에 보수적으로 합산합니다. 재설정하시겠습니까?",
                still_current=self._same_selection(),
                fallback=self._safe_focus(kind),
            )[0]
        if intent.action == "adopt":
            policy = proposal.cost_policy
            assert policy is not None
            return a11y.confirm(
                self,
                "이전 비용 이력 승계 확인",
                f"이전 이력은 통화·기간 근거가 없습니다. 제공업체 {intent.provider}의 이력을 "
                f"{policy.currency}, UTC [{policy.period_start_utc}, {policy.period_end_utc})로 "
                "직접 확인하여 승계합니까? UNKNOWN과 예약 노출은 그대로 유지합니다.",
                still_current=self._same_selection(),
                fallback=self._safe_focus(kind),
            )[0]
        return True

    def _capture_action(self, kind: str, action: str) -> ActionIntent:
        control = self._controls(kind)
        if action == "reset_clock":
            provider, endpoint, data_type = "", "", ""
            scope = ConsentScope.library()
        else:
            provider, endpoint, data_type = self._scope(kind)
            scope = (
                self._selected_scope(kind)
                if action in {"grant", "revoke"}
                else ConsentScope.library()
            )
        config = self.provider_config(kind) if action == "grant" else None
        cost = self._cost_intent(kind) if action in {"grant", "budget", "adopt"} else None
        return ActionIntent(
            kind,
            action,
            provider,
            endpoint,
            data_type,
            scope,
            config,
            cost,
            self.backend.credentials.capture_plan(kind),
            str(control.requests.currentData()) if control.requests.currentData() else None,
            _micros(control.actual),
            control.confirm_actual.isChecked(),
        )

    def _action(self, kind: str, action: str) -> None:
        if self._closed or self.backend.closing:
            return
        control = self._controls(kind)
        nonce = uuid.uuid4().hex
        generation = self._selection_generation
        self._command_nonces[kind] = nonce
        self._status_errors.pop(kind, None)
        if action in {"grant", "revoke", "save", "delete"}:
            self._fact_epochs[kind] += 1
            self.refresh_provider_facts(kind)
        try:
            if action in {"save", "delete"}:
                provider, target, _ = self._scope(kind)
                credential_target = CredentialTarget(provider, target)

                def key_done(result: KeyResult) -> None:
                    self.work_ready.emit(PrivacyReply(kind, nonce, generation, "key", result))

                accepted = self.backend.credentials.try_enqueue_key_change(
                    credential_target,
                    action,
                    control.key.text() if action == "save" else None,
                    command_nonce=nonce,
                    selection_generation=generation,
                    done=key_done,
                )
                if not accepted:
                    raise SecurityError("RESOURCE_EXHAUSTED")
                if action == "save":
                    control.key.clear()
                for target_kind in self.controls:
                    try:
                        other_provider, other_target, _ = self._scope(target_kind)
                    except (SecurityError, ProviderError):
                        continue
                    if (other_provider, other_target) == (provider, target):
                        self.backend.credentials.invalidate_plan(target_kind)
                        if target_kind != kind:
                            self._fact_epochs[target_kind] += 1
                            self.refresh_provider_facts(target_kind)
                control.status.setText("키 변경 접수됨 · 실제 완료 확인 중")
                return
            if action == "refresh":
                self._request_view(kind)
                return
            intent = self._capture_action(kind, action)
            accepted = self.backend.submit(
                lambda: self.backend.prepare_action(intent),
                kind=kind,
                nonce=nonce,
                generation=generation,
                tag="proposal",
                reply=self.work_ready.emit,
            )
            if not accepted:
                raise SecurityError("RESOURCE_EXHAUSTED")
            control.status.setText("확인 중 · 아직 완료되지 않았습니다")
        except (SecurityError, ProviderError) as error:
            self._status_errors[kind] = error.code
            control.status.setText(error.code)
            self._request_view(kind)

    def _revoke_endpoint(self, provider: str, target: str) -> None:
        def revoke() -> None:
            self.consents.revoke_endpoint(provider, target)
            for scopes in self.backend.granted.values():
                scopes.difference_update({s for s in scopes if s[:2] == (provider, target)})

        if not self.backend.submit(
            revoke,
            kind="summary",
            nonce=uuid.uuid4().hex,
            generation=self._selection_generation,
            tag="revoked",
            reply=self.work_ready.emit,
        ):
            raise SecurityError("RESOURCE_EXHAUSTED")
