"""Explicit consent, credentials and scoped, quoted remote cost controls."""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, ExitStack, contextmanager
from dataclasses import dataclass
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

from recoryn.providers import ExecutionContext, LocalModelAttestation, ProviderConfig, ProviderError
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
from recoryn.ui import a11y


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

    def __init__(
        self,
        consents: ConsentStore,
        ledger: CostLedger,
        vault: CredentialVault,
        *,
        gateway: Gateway | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.consents, self.ledger, self.vault, self._gateway = consents, ledger, vault, gateway
        self.announcer = a11y.Announcer()
        self._attestation: LocalModelAttestation | None = None
        self._selected_session: str | None = None
        self._selection_pending = False
        self._selection_origin: str | None = None
        self._scope_retry = QTimer(self)
        self._scope_retry.setSingleShot(True)
        self._scope_retry.setInterval(50)
        self._scope_retry.timeout.connect(self._retry_scope_views)
        self._granted: dict[str, set[tuple[str, str, str, ConsentScope, int]]] = {
            "stt": set(),
            "summary": set(),
        }
        self.controls = {kind: _Controls(kind) for kind in ("stt", "summary")}
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
        self._selected_session = session_id
        self._selection_pending = False
        for kind, control in self.controls.items():
            if changed:
                control.scope.setCurrentIndex(0)
            self._show_scope(kind)

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
        self._scope_retry.stop()
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

    def _show_scope(self, kind: str) -> str:
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
        provider: str | None
        target: str | None
        data_type: str | None
        try:
            provider, target, data_type = self._scope(kind)
        except (SecurityError, ProviderError):
            provider, target, data_type = None, None, None
        view = self.consents.scope_view(
            provider,
            target,
            data_type,
            capability=kind,
            scope=self._selected_scope(kind) if enabled else None,
            session_id=self._selected_session,
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
        try:
            for provider, target, data_type, scope, version in self._granted[kind]:
                self.consents.revoke(
                    provider,
                    target,
                    data_type,
                    capability=kind,
                    scope=scope,
                    policy_version=version,
                )
            self._granted[kind].clear()
            self.controls[kind].status.setText("설정 변경 — 선택한 범위를 다시 허용하세요")
        except SecurityError as error:
            self.controls[kind].status.setText(error.code)
        self._show_scope(kind)

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

    def _config_key(
        self,
        config: ProviderConfig,
        kind: str,
        session_id: str,
    ) -> str:
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

    def _snapshot(self, kind: str, session_id: str, config: ProviderConfig) -> _Snapshot:
        scope = self._selected_scope(kind, session_id)
        types = ("audio",) if kind == "stt" else ("transcript", "context")
        with self.consents.coordinator.hold():
            version = self.consents.policy_version
            self.consents.bind_session(session_id)
            request = ConsentRequest(session_id, 0, kind, version)
            bindings = self.consents.capture_bindings(
                config.provider_id, config.endpoint, types, scope=scope, request=request
            )
            key = self._config_key(config, kind, session_id)
        control = self._controls(kind)
        return _Snapshot(
            config,
            scope,
            request,
            bindings,
            types,
            _micros(control.per_request),
            _micros(control.total),
            key,
            None if config.provider_id == "ollama" else self._cost_policy(kind),
        )

    def prepare_execution(
        self, kind: str, session_id: str, cancel: threading.Event
    ) -> PrivacyExecution:
        config = self.provider_config(kind)
        if config.provider_id == "faster_whisper":
            return PrivacyExecution(
                config,
                self._config_key(config, kind, session_id),
                ExecutionContext(cancel=cancel),
                None,
            )
        snapshot = self._snapshot(kind, session_id, config)
        return PrivacyExecution(
            config,
            snapshot.config_key,
            self._execution_context(snapshot, cancel),
            self._gateway_for(snapshot),
        )

    def execution_context(
        self, kind: str, cancel: threading.Event, *, session_id: str
    ) -> ExecutionContext:
        return self.prepare_execution(kind, session_id, cancel).context

    def _execution_context(self, snapshot: _Snapshot, cancel: threading.Event) -> ExecutionContext:
        config = snapshot.config
        policy, ledger = self.consents, self.ledger
        types, bindings = snapshot.data_types, snapshot.bindings
        if not bindings:
            raise SecurityError("CONSENT_REQUIRED")
        if config.provider_id == "ollama":
            return ExecutionContext(cancel=cancel)
        cap, limit = snapshot.cap, snapshot.limit
        if cap <= 0 or limit <= 0:
            raise SecurityError("BUDGET_REQUIRED")
        secret = self.vault.get(self._vault_key(config.provider_id, config.endpoint))
        if not secret:
            raise SecurityError("AUTH_REQUIRED")
        header = {"openai": "authorization", "anthropic": "x-api-key", "gemini": "x-goog-api-key"}[
            config.provider_id
        ]
        headers = {header: ("Bearer " + secret if config.provider_id == "openai" else secret)}
        provider, target = config.provider_id, config.endpoint

        cost_policy = snapshot.cost_policy
        if cost_policy is None:
            raise SecurityError("COST_REQUEST_INVALID")
        notify = self.quote_ready.emit

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
                try:
                    quoted = ledger.quote_request(request, cost_policy)
                    reservation = ledger.reserve_quote(
                        uuid.uuid4().hex, quoted, cost_policy, request
                    )
                except SecurityError as error:
                    try:
                        notify(snapshot.request.capability, error.code)
                    except RuntimeError:
                        pass  # Closing the display must not change cost admission.
                    raise
                try:
                    notify(snapshot.request.capability, quoted)
                except RuntimeError:
                    pass
                return reservation

        return ExecutionContext(cancel=cancel, headers=headers, reservation_factory=reserve)

    def gateway_for(self, session_id: str, *, kind: str = "summary") -> Gateway:
        config = self.provider_config(kind)
        return self._gateway_for(self._snapshot(kind, session_id, config))

    def _gateway_for(self, snapshot: _Snapshot) -> Gateway:
        config = snapshot.config
        types, bindings = snapshot.data_types, snapshot.bindings
        base = self._gateway
        base_guard = base.dispatch_guard if base else None
        proof = config.local_attestation

        @contextmanager
        def local_guard(permit: SendPermit) -> Iterator[None]:
            # Freeze this plan's proof and scope. Never consult widgets or adopt
            # a subsequently installed proof from a worker/transport callback.
            if (
                permit.provider_id != config.provider_id
                or permit.endpoint != config.endpoint
                or permit.data_type not in types
                or permit.request != snapshot.request
                or permit.scope != snapshot.scope
                or proof is None
                or proof.endpoint != config.endpoint
                or proof.model != config.model
            ):
                raise SecurityError("LOCAL_EXECUTION_UNVERIFIED")
            with ExitStack() as stack:
                if base_guard is not None:
                    stack.enter_context(base_guard(permit))
                stack.enter_context(proof.execution_guard())
                yield

        dispatch_guard: Callable[[SendPermit], AbstractContextManager[None]] | None = (
            local_guard if proof is not None else base_guard
        )
        return Gateway(
            self.consents,
            ledger=None if config.provider_id == "ollama" else self.ledger,
            transport=base.transport if base else None,
            timeout=base.timeout if base else 30,
            max_request_bytes=base.max_request_bytes if base else 32 * 1024 * 1024,
            max_response_bytes=base.max_response_bytes if base else 8 * 1024 * 1024,
            chunk_bytes=base.chunk_bytes if base else 64 * 1024,
            expected_grants=bindings,
            dispatch_guard=dispatch_guard,
        ).for_session(
            snapshot.request.session_id,
            snapshot.request.session_generation,
            capability=snapshot.request.capability,
            scope=snapshot.scope,
            policy_version=snapshot.request.policy_version,
        )

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
        control = self._controls(kind)
        provider, _, _ = self._scope(kind)
        start, end = self._period(kind)
        code = control.currency.text()
        old = self.ledger.account(provider, code, start, end)
        version = int(old["policy_version"]) + int(advance) if old else 1
        return CostPolicy(
            str(control.cost_mode.currentData()),
            code,
            start,
            end,
            _micros(control.per_request),
            _micros(control.total),
            version,
            cost_catalog.load_catalog().sha256,
            control.general_acknowledged,
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
        unavailable = self.ledger.availability()
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

    def _refresh(self, kind: str) -> None:
        control = self.controls[kind]
        if self._cost_unavailable(kind):
            return
        provider, _, _ = self._scope(kind)
        start, end = self._period(kind)
        code = control.currency.text()
        balance = self.ledger.account_snapshot(provider, code, start, end)
        account = self.ledger.account(provider, code, start, end)
        legacy = self.ledger.legacy_unscoped(provider)
        control.adopt_legacy.setEnabled(legacy)
        records = self.ledger.reservations(provider)
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

    def _action(self, kind: str, action: str) -> None:
        control = self._controls(kind)
        try:
            if action == "reset_clock":
                if not a11y.confirm(
                    self,
                    "시계 기준 재설정 확인",
                    "운영체제의 현재 시각을 확인하셨습니까? 시계 기준 변경은 감사 이력에 남습니다. "
                    "기존 예약·UNKNOWN·확정 지출은 줄어들지 않습니다. 모든 기간의 같은 제공업체·통화 "
                    "확정액을 현재 예산에 보수적으로 합산합니다. 재설정하시겠습니까?",
                    still_current=self._same_selection(),
                    fallback=self._safe_focus(kind),
                )[0]:
                    return
                self.ledger.reset_clock(confirmed=True)
                for target_kind, target_control in self.controls.items():
                    if not self._cost_unavailable(target_kind):
                        target_control.balance.setText(
                            "시계 기준 재설정 완료 — 기존 지출을 보존합니다"
                        )
                return
            provider, target, data_type = self._scope(kind)
            if action == "grant":
                config = self.provider_config(kind)
                scope = self._selected_scope(kind)
                version, deadline = self.consents.policy_version, self.consents.grant_deadline
                if provider != "ollama" and (
                    _micros(control.per_request) <= 0 or _micros(control.total) <= 0
                ):
                    raise SecurityError("BUDGET_REQUIRED")
                if scope.kind == "library" and not self._confirm_library(
                    kind, provider, target, data_type, version, deadline
                ):
                    return
                if provider == "ollama":
                    assert config.local_attestation is not None
                    self.consents.approve_local_endpoint(
                        target,
                        config.local_attestation.artifact_sha256,
                        ttl_seconds=config.local_attestation.expires_at_monotonic
                        - time.monotonic(),
                    )
                self.consents.grant(
                    provider,
                    target,
                    data_type,
                    capability=kind,
                    scope=scope,
                    policy_version=version,
                    expires_at=deadline,
                )
                self._granted[kind].add((provider, target, data_type, scope, version))
            elif action == "revoke":
                scope, version = self._selected_scope(kind), self.consents.policy_version
                self.consents.revoke(
                    provider,
                    target,
                    data_type,
                    capability=kind,
                    scope=scope,
                    policy_version=version,
                )
                self._granted[kind].discard((provider, target, data_type, scope, version))
                self.announcer.announce(
                    "privacy",
                    control.revoke,
                    "REVOCATION_PERSISTED",
                    f"{kind} 전송 동의 철회를 저장했습니다 · 이미 전송한 결과는 별도로 표시합니다",
                    version=("revoke", kind, provider, target, data_type, scope.kind, version),
                )
            elif action == "save":
                self._revoke_endpoint(provider, target)
                self.vault.set(self._vault_key(provider, target), control.key.text())
                control.key.clear()
                self._changed(kind)
            elif action == "delete":
                self._revoke_endpoint(provider, target)
                self.vault.delete(self._vault_key(provider, target))
                self._changed(kind)
            elif action == "budget":
                self.ledger.apply_policy(provider, self._cost_policy(kind, advance=True))
            elif action == "adopt":
                policy = self._cost_policy(kind)
                if not a11y.confirm(
                    self,
                    "이전 비용 이력 승계 확인",
                    f"이전 이력은 통화·기간 근거가 없습니다. 제공업체 {provider}의 이력을 "
                    f"{policy.currency}, UTC [{policy.period_start_utc}, {policy.period_end_utc})로 "
                    "직접 확인하여 승계합니까? UNKNOWN과 예약 노출은 그대로 유지합니다.",
                    still_current=self._same_selection(),
                    fallback=self._safe_focus(kind),
                )[0]:
                    return
                self.ledger.adopt_legacy(provider, policy, confirmed=True)
            elif action == "settle":
                if not control.confirm_actual.isChecked() or not control.requests.currentData():
                    raise SecurityError("SETTLEMENT_CONFIRMATION_REQUIRED")
                self.ledger.settle(str(control.requests.currentData()), _micros(control.actual))
                control.confirm_actual.setChecked(False)
            elif action != "refresh":
                raise SecurityError("INVALID_PRIVACY_ACTION")
            self._refresh(kind)
        except (SecurityError, ProviderError) as error:
            control.status.setText(error.code)
            self._show_scope(kind)
        else:
            control.status.setText(self._show_scope(kind))

    def _revoke_endpoint(self, provider: str, target: str) -> None:
        self.consents.revoke_endpoint(provider, target)
        for scopes in self._granted.values():
            scopes.difference_update({scope for scope in scopes if scope[:2] == (provider, target)})
