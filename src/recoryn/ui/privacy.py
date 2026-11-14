"""Explicit, separate STT/summary consent, credential, and USD budget controls."""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, ExitStack, contextmanager
from decimal import Decimal

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
    ConsentStore,
    CostLedger,
    CredentialVault,
    Gateway,
    SecurityError,
    SendPermit,
)
from recoryn.security._core import endpoint as parse_endpoint


def _micros(control: QDoubleSpinBox) -> int:
    return int(Decimal(str(control.value())) * 1_000_000)


def _usd(value: int) -> str:
    return f"{Decimal(value) / 1_000_000:.6f}"


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
        self.apply_budget = QPushButton("제공업체 USD 한도 적용")
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
            ("새 BYOK 키", self.key),
            ("키 저장", self.save_key),
            ("키 폐기", self.delete_key),
            ("제공업체 전체 한도", self.total),
            ("요청 1회 비용 상한", self.per_request),
            ("예산", self.apply_budget),
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
        self._attestation: LocalModelAttestation | None = None
        self._granted: dict[str, set[tuple[str, str, str]]] = {"stt": set(), "summary": set()}
        self.controls = {kind: _Controls(kind) for kind in ("stt", "summary")}
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
            controls.save_key.clicked.connect(lambda checked=False, k=kind: self._action(k, "save"))
            controls.delete_key.clicked.connect(
                lambda checked=False, k=kind: self._action(k, "delete")
            )
            controls.apply_budget.clicked.connect(
                lambda checked=False, k=kind: self._action(k, "budget")
            )
            controls.refresh.clicked.connect(
                lambda checked=False, k=kind: self._action(k, "refresh")
            )
            controls.settle.clicked.connect(lambda checked=False, k=kind: self._action(k, "settle"))
            controls.provider.currentIndexChanged.connect(lambda index, k=kind: self._changed(k))
            controls.endpoint.textChanged.connect(lambda text, k=kind: self._changed(k))
            controls.model.textChanged.connect(lambda text, k=kind: self._changed(k))
            for setting in (
                controls.context_window,
                controls.max_output,
                controls.total,
                controls.per_request,
            ):
                setting.valueChanged.connect(lambda value, k=kind: self._changed(k))

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
            for scope in self._granted[kind]:
                self.consents.revoke(*scope)
            self._granted[kind].clear()
            self.controls[kind].status.setText("설정 변경 — 선택한 범위를 다시 허용하세요")
        except SecurityError as error:
            self.controls[kind].status.setText(error.code)

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

    def config_key(self, kind: str) -> str:
        if str(self._controls(kind).provider.currentData()) == "none":
            return hashlib.sha256(b"summary:none").hexdigest()
        config = self.provider_config(kind)
        data = [
            config.provider_id,
            config.model,
            config.endpoint,
            config.execution_location,
            config.local_attestation.artifact_sha256 if config.local_attestation else None,
            config.context_window_tokens,
            config.max_output_tokens,
            _micros(self.controls[kind].per_request),
            _micros(self.controls[kind].total),
        ]
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def execution_context(self, kind: str, cancel: threading.Event) -> ExecutionContext:
        config = self.provider_config(kind)
        if config.provider_id == "faster_whisper":
            return ExecutionContext(cancel=cancel)
        policy, ledger = self.consents, self.ledger
        types = ("audio",) if kind == "stt" else ("transcript", "context")
        bindings = policy.capture_bindings(config.provider_id, config.endpoint, types)
        if not bindings:
            raise SecurityError("CONSENT_REQUIRED")
        if config.provider_id == "ollama":
            return ExecutionContext(cancel=cancel)
        control = self.controls[kind]
        cap, limit = _micros(control.per_request), _micros(control.total)
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

        def reserve(
            actual_provider: str, actual_endpoint: str, data_type: str, body_size: int
        ) -> str:
            if (
                actual_provider != provider
                or parse_endpoint(actual_endpoint).url != target
                or data_type not in types
                or type(body_size) is not int
                or body_size < 0
            ):
                raise SecurityError("BUDGET_SCOPE_MISMATCH")
            binding = next((item for item in bindings if item.data_type == data_type), None)
            if binding is None:
                raise SecurityError("CONSENT_REQUIRED")
            with policy.coordinator.hold():
                policy.validate_binding(binding)
                return ledger.reserve(provider, uuid.uuid4().hex, cap, limit)

        return ExecutionContext(cancel=cancel, headers=headers, reservation_factory=reserve)

    def gateway_for(self, session_id: str, *, kind: str = "summary") -> Gateway:
        config = self.provider_config(kind)
        types = ("audio",) if kind == "stt" else ("transcript", "context")
        bindings = self.consents.capture_bindings(
            config.provider_id,
            config.endpoint,
            types,
        )
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
        ).for_session(session_id)

    def _refresh(self, kind: str) -> None:
        control = self.controls[kind]
        provider, _, _ = self._scope(kind)
        balance = self.ledger.snapshot(provider)
        control.balance.setText(
            "USD 확정 "
            + _usd(balance["confirmed"])
            + " / 예약 "
            + _usd(balance["reserved"])
            + " / UNKNOWN "
            + _usd(balance["unknown_exposure"])
            + " / 잔여 "
            + _usd(balance["available"])
        )
        control.requests.clear()
        for request in self.ledger.reservations(provider):
            control.requests.addItem(
                str(request["request_id"]) + " / " + str(request["state"]),
                str(request["reservation_id"]),
            )

    def _action(self, kind: str, action: str) -> None:
        control = self._controls(kind)
        try:
            provider, target, data_type = self._scope(kind)
            if action == "grant":
                config = self.provider_config(kind)
                if provider == "ollama":
                    assert config.local_attestation is not None
                    self.consents.approve_local_endpoint(
                        target,
                        config.local_attestation.artifact_sha256,
                        ttl_seconds=config.local_attestation.expires_at_monotonic
                        - time.monotonic(),
                    )
                elif _micros(control.per_request) <= 0 or _micros(control.total) <= 0:
                    raise SecurityError("BUDGET_REQUIRED")
                self.consents.grant(provider, target, data_type)
                self._granted[kind].add((provider, target, data_type))
            elif action == "revoke":
                self.consents.revoke(provider, target, data_type)
                self._granted[kind].discard((provider, target, data_type))
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
                self.ledger.set_limit(provider, _micros(control.total))
            elif action == "settle":
                if not control.confirm_actual.isChecked() or not control.requests.currentData():
                    raise SecurityError("SETTLEMENT_CONFIRMATION_REQUIRED")
                self.ledger.settle(str(control.requests.currentData()), _micros(control.actual))
                control.confirm_actual.setChecked(False)
            elif action != "refresh":
                raise SecurityError("INVALID_PRIVACY_ACTION")
            self._refresh(kind)
            control.status.setText(
                "허용됨" if self.consents.allowed(provider, target, data_type) else "거부됨"
            )
        except (SecurityError, ProviderError) as error:
            control.status.setText(error.code)

    def _revoke_endpoint(self, provider: str, target: str) -> None:
        for data_type in ("audio", "transcript", "context"):
            self.consents.revoke(provider, target, data_type)
        for scopes in self._granted.values():
            scopes.difference_update({scope for scope in scopes if scope[:2] == (provider, target)})
