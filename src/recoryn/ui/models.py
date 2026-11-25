"""Explicit model installation on an independent bounded worker."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QThreadPool, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from recoryn.domain import StateConflict
from recoryn.models import ModelManager, ModelSpec
from recoryn.models import artifacts as art
from recoryn.models._artifact_io import ArtifactIo, managed_snapshot, whisper_snapshot
from recoryn.models.gpu_runtime import DOWNLOAD_BYTES, TERMS, GpuRuntimeManager
from recoryn.models.manager import parse_spec, spec_digest
from recoryn.providers import ProviderError
from recoryn.storage._safe import read_json
from recoryn.ui import a11y
from recoryn.ui.tasks import Task

OLLAMA_POLICY_NOTE = (
    "로컬 Ollama 요약은 AI 실행 정책이 GPU_WITH_CPU_FALLBACK_ALLOWED일 때만 실행합니다. "
    "Recoryn은 Ollama 서버가 CPU와 GPU 중 무엇을 쓰는지와 서버 메모리를 통제하거나 보장하지 "
    "못하므로, CPU_ONLY·GPU_ONLY에서는 요약을 시작하지 않습니다. 정책은 자동으로 바꾸지 "
    "않으며, 앱을 다시 시작하면 기본값 CPU_ONLY로 돌아갑니다. 원격 제공업체는 이 PC의 "
    "장치 정책 대상이 아니며 동의·비용 확인은 그대로 적용됩니다."
)


_SOURCE_TEXT = {
    (art.WHISPER, art.MANUAL): "사용자 지정 모델 — 출처 인증 안 됨",
    (art.WHISPER, art.MANAGED): "관리 설치 — 확인한 manifest와 파일 일치",
    (art.DIARIZATION, art.MANUAL): "사용자 고정 manifest와 파일 일치 — 게시자 인증 아님",
}
_STATE_TEXT = {
    art.UNCONFIRMED: "미확인 — 확인 전에는 실행하지 않습니다",
    art.MANUAL_USER_CONFIRMED: "사용자 확인됨(이 실행 동안) — 출처 인증 아님",
    art.MANAGED_PIN_MATCH: "확인됨(이 실행 동안) — 고정 manifest 일치, 게시자 인증 아님",
    art.CHANGED_INVALID: "변경됨 또는 검증 실패 — 실행하지 않습니다. 다시 확인하세요",
    art.LICENSE_UNCONFIRMED: "조건 미확인 — 사용 권한 확인은 사용자 책임",
}
_LICENSE_TEXT = {
    art.DECLARED: "선언됨(라이선스 파일 SHA256 포함)",
    art.FILE_ONLY: "라이선스 파일 있음(SHA256 표시) — 식별자·URL 미제공, 조건 확인은 사용자 책임",
    art.METADATA_ONLY: "메타데이터만(라이선스 원문 없음)",
    art.NOT_PROVIDED: "정보 미제공 — 사용 권한 확인은 사용자 책임",
}


def confirmation_text(snapshot: art.ModelSourceSnapshot, display: str) -> str:
    """The exact preview a confirmation is bound to (G13 section 4.2)."""
    role = "로컬 Whisper 전사" if snapshot.kind == art.WHISPER else "화자 분리"
    if snapshot.integrity == art.INVALID:
        source = "관리 설치 — 검증 실패(확인한 manifest 없음 또는 불일치)"
    else:
        source = _SOURCE_TEXT[(snapshot.kind, snapshot.source_kind)]
    terms = snapshot.terms
    lines = [
        f"역할: {role}",
        f"대상 폴더: {snapshot.root}",
        f"출처: {source}",
        "출처 인증: 안 됨 — 자체 digest이며 공식 digest·서명 대조가 아닙니다",
        f"상태: {_STATE_TEXT[display]}",
        f"라이선스: {_LICENSE_TEXT[snapshot.license_state]}",
        f"  ID: {terms.license_id or '미제공'}",
        f"  URL: {terms.license_url or '미제공'}",
        f"전체 artifact SHA256: {snapshot.artifact_digest}",
        f"조건(terms) SHA256: {snapshot.terms_digest}",
        "파일:",
    ]
    copied = 0
    for entry in snapshot.entries:
        if entry.state == art.PRESENT:
            copied += entry.size
            lines.append(f"  {entry.name} · {entry.size:,} bytes · SHA256 {entry.sha256}")
        elif entry.state == art.ABSENT_DEFAULT:
            lines.append(f"  {entry.name} · 없음(고정 기본값 {{}} 사용)")
        else:
            lines.append(f"  {entry.name} · 없음")
    for entry in terms.license_files:
        copied += entry.size
        lines.append(f"  {entry.name} · {entry.size:,} bytes · SHA256 {entry.sha256}")
    lines += [
        f"실행 시 임시 사본: 약 {copied:,} bytes를 이 앱 소유 임시 폴더에 복제(원본은 그대로)",
        "이 확인은 이 실행 동안만 유효하며 전송 동의·다운로드·비용 승인이 아닙니다.",
    ]
    return "\n".join(lines)


class _Progress(QObject):
    update = Signal(int)


class ModelPanel(QWidget):
    modelSelected = Signal(str)
    attestationChanged = Signal(object)

    def __init__(
        self,
        root: Path,
        *,
        can_modify: Callable[[], bool] | None = None,
        release_gpu: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self.manager = ModelManager(root)
        # L01 D10: the opt-in GPU runtime lives next to the models, never in the bundle.
        self.gpu = GpuRuntimeManager(root.parent / "gpu-runtime")
        self.can_modify = can_modify or (lambda: True)
        # Closes an idle transcription worker that holds the GPU runtime open.
        self.release_gpu = release_gpu or (lambda: None)
        self._gpu_task: Task | None = None
        self.plan: ModelSpec | None = None
        self.cancel = threading.Event()
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.task: Task | None = None
        self.ollama: Any = None
        self._ollama_proof: Any = None
        self._ollama_generation = 0
        self._proof_generation: int | None = None
        self._attestation_task: Task | None = None
        self._shutdown_requested = False
        self.attestation_state = "UNVERIFIED"
        self._last_progress = 0.0
        self.notifier = _Progress(self)
        self.notifier.update.connect(self._progress_changed)
        # G-P13: this run's explicit local-model confirmations (memory only) and the
        # reviewed specs pinned outside the model folders (the managed references).
        self.confirmations = art.ConfirmationRegistry()
        self.artifact_io = ArtifactIo()
        self._pins: dict[str, str] = {}
        self._manual_roots: set[str] = set()
        self._confirm_snapshot: art.ModelSourceSnapshot | None = None
        self._confirm_key: art.ConfirmationKey | None = None
        self._confirm_token = 0
        self._confirm_announce = a11y.qt_announce
        layout = QVBoxLayout(self)
        self.status = QLabel(
            "명시적으로 선택한 파일만 다운로드합니다. 모델 가중치는 앱에 포함되지 않습니다."
        )
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.installed = QListWidget()
        self.installed.setAccessibleName("설치된 모델과 무결성 상태")
        layout.addWidget(self.installed)
        controls = QHBoxLayout()
        for label, callback in (
            ("목록 및 무결성 확인", self.refresh),
            ("선택 모델 사용", self.choose_installed),
            ("모델 삭제", self.delete_selected),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            controls.addWidget(button)
        layout.addLayout(controls)
        layout.addWidget(QLabel("로컬 모델 사용 확인 — 확인한 파일만 실행합니다."))
        self.confirm_preview = QPlainTextEdit()
        self.confirm_preview.setReadOnly(True)
        self.confirm_preview.setTabChangesFocus(True)  # Tab reaches the check and the button
        a11y.name(
            self.confirm_preview,
            "로컬 모델 사용 확인 내용",
            "역할, 출처, 인증 범위, 라이선스 상태, 전체 SHA256과 파일별 크기·SHA256",
        )
        layout.addWidget(self.confirm_preview)
        self.confirm_ack = QCheckBox(
            "표시된 파일·SHA256·출처·라이선스를 확인했고, 사용 권한 확인은 제 책임입니다."
        )
        self.confirm_ack.setChecked(False)
        layout.addWidget(self.confirm_ack)
        confirm_actions = QHBoxLayout()
        self.confirm_button = QPushButton("이 모델 사용 확인")
        a11y.name(
            self.confirm_button,
            "표시한 로컬 모델 사용 확인",
            "확인 창의 기본값은 아니요입니다. 다른 파일에는 적용되지 않습니다",
        )
        self.confirm_button.setEnabled(False)
        self.confirm_button.clicked.connect(self.confirm_model)
        self._confirm_keys = a11y.activate_button(self.confirm_button)
        confirm_actions.addWidget(self.confirm_button)
        self.adopt_button = QPushButton("관리 설치를 사용자 지정 모델로 따로 확인")
        self.adopt_button.setEnabled(False)
        self.adopt_button.clicked.connect(self.adopt_manual)
        self._adopt_keys = a11y.activate_button(self.adopt_button)
        confirm_actions.addWidget(self.adopt_button)
        layout.addLayout(confirm_actions)
        self.confirm_status = QLabel("")
        self.confirm_status.setWordWrap(True)
        a11y.name(self.confirm_status, "로컬 모델 사용 확인 상태")
        layout.addWidget(self.confirm_status)
        self.cleanup_status = QLabel("")
        self.cleanup_status.setWordWrap(True)
        a11y.name(self.cleanup_status, "임시 모델 사본 정리 상태")
        layout.addWidget(self.cleanup_status)
        manifest = QPushButton("출처·라이선스·SHA256가 포함된 모델 manifest 선택")
        manifest.clicked.connect(self.choose_manifest)
        layout.addWidget(manifest)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setAccessibleName("모델 다운로드 대상과 라이선스")
        layout.addWidget(self.preview)
        self.approval = QCheckBox(
            "표시된 출처·저장 공간·라이선스를 확인하고 이 모델 다운로드에 동의합니다."
        )
        layout.addWidget(self.approval)
        actions = QHBoxLayout()
        self.download_button = QPushButton("선택 모델 다운로드 / 이어받기")
        self.download_button.clicked.connect(self.download)
        actions.addWidget(self.download_button)
        cancel_button = QPushButton("다운로드 / 서버 준비 취소 (부분 파일 보존)")
        cancel_button.clicked.connect(self.cancel.set)
        actions.addWidget(cancel_button)
        layout.addLayout(actions)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        layout.addWidget(self.progress)
        layout.addWidget(
            QLabel(
                "GPU 가속(선택) — Recoryn에는 NVIDIA·Intel 코드가 들어 있지 않습니다. "
                "GPU를 쓰려면 아래 약관에 동의한 뒤 공식 배포처(PyPI)에서 직접 받습니다."
            )
        )
        self.gpu_terms = QPlainTextEdit()
        self.gpu_terms.setReadOnly(True)
        self.gpu_terms.setAccessibleName("GPU 런타임 약관과 받을 파일")
        self.gpu_terms.setPlainText(
            "\n".join(
                [f"· {item.name}\n  적용 대상: {item.applies_to}\n  {item.url}" for item in TERMS]
                + [
                    "",
                    f"받을 크기: {DOWNLOAD_BYTES:,} bytes (CTranslate2 공식판과 NVIDIA cuBLAS)",
                    f"설치 위치: {self.gpu.active}",
                    "고정된 크기와 SHA-256으로 검증한 뒤 필요한 파일만 풀고, 받은 묶음은 지웁니다.",
                    "GPU를 고른 전사 프로세스만 이 런타임을 쓰며, 쓰기 직전에 전체를 다시 검증합니다.",
                    "GPU를 쓸 수 없으면 CPU 허용 정책은 CPU로 전사하고,"
                    " GPU 전용 정책은 전사를 시작하지 않습니다.",
                    "(개발용 소스 실행에 CUDA판 CTranslate2가 이미 설치돼 있으면 그것을 먼저 씁니다.)",
                ]
            )
        )
        layout.addWidget(self.gpu_terms)
        self.gpu_approval = QCheckBox(
            "위 약관(NVIDIA·Intel·CTranslate2)을 확인했고, 이 PC에 GPU 런타임을 받는 데 동의합니다."
        )
        layout.addWidget(self.gpu_approval)
        gpu_actions = QHBoxLayout()
        self.gpu_download = QPushButton(f"GPU 런타임 받기 (약 {DOWNLOAD_BYTES // 2**20:,} MB)")
        self.gpu_download.clicked.connect(self.download_gpu)
        gpu_actions.addWidget(self.gpu_download)
        self.gpu_remove = QPushButton("GPU 런타임 삭제")
        self.gpu_remove.clicked.connect(self.remove_gpu)
        gpu_actions.addWidget(self.gpu_remove)
        layout.addLayout(gpu_actions)
        self.gpu_status = QLabel()
        self.gpu_status.setWordWrap(True)
        layout.addWidget(self.gpu_status)
        self.refresh_gpu()
        layout.addWidget(QLabel("로컬 Ollama — 이미 설치한 실행 파일과 모델만 사용합니다."))
        # G-P11a (C00 decision 5): until the policy is remembered (G-P16) the default
        # CPU_ONLY refuses local Ollama on every start; say so plainly, change nothing.
        self.ollama_policy_note = QLabel(OLLAMA_POLICY_NOTE)
        self.ollama_policy_note.setWordWrap(True)
        self.ollama_policy_note.setAccessibleName("로컬 Ollama 요약의 AI 실행 정책 조건")
        layout.addWidget(self.ollama_policy_note)
        self.ollama_executable = QLineEdit()
        self.ollama_executable.setPlaceholderText("이미 설치한 ollama 실행 파일")
        self.ollama_executable.setAccessibleName("Ollama 실행 파일 경로")
        layout.addWidget(self.ollama_executable)
        self.ollama_models = QLineEdit()
        self.ollama_models.setPlaceholderText("로컬 manifest와 blobs가 있는 모델 폴더")
        self.ollama_models.setAccessibleName("Ollama 로컬 모델 폴더")
        layout.addWidget(self.ollama_models)
        self.ollama_model = QLineEdit()
        self.ollama_model.setPlaceholderText("설치된 로컬 모델 이름:태그")
        self.ollama_model.setAccessibleName("Ollama 로컬 모델 이름과 태그")
        layout.addWidget(self.ollama_model)
        self.ollama_approval = QCheckBox(
            "선택한 실행 파일과 로컬 모델로 이 앱이 소유하는 Ollama 서버를 시작합니다."
        )
        layout.addWidget(self.ollama_approval)
        helper = QHBoxLayout()
        self.ollama_start = QPushButton("로컬 파일 검증 후 Ollama 시작")
        self.ollama_start.clicked.connect(self.start_ollama)
        helper.addWidget(self.ollama_start)
        self.ollama_stop = QPushButton("이 앱 소유 Ollama 정지")
        self.ollama_stop.clicked.connect(self.stop_ollama)
        helper.addWidget(self.ollama_stop)
        layout.addLayout(helper)

    def refresh_gpu(self) -> None:
        state = self.gpu.status()
        self.gpu_status.setText(
            {
                "NOT_INSTALLED": "GPU 런타임: 받지 않음",
                "READY": "GPU 런타임: 설치됨(파일 구성·크기 확인) · GPU를 허용한 정책에서"
                " 전사에 쓰며, 쓰기 직전에 전체를 다시 검증합니다.",
                "DAMAGED": "GPU 런타임: 손상됨 · 쓰지 않습니다. 삭제한 뒤 다시 받으세요.",
            }.get(state, "GPU 런타임: " + state)
        )

    def download_gpu(self) -> None:
        if not self.gpu_approval.isChecked():
            self.gpu_status.setText("약관을 확인하고 동의 칸을 선택한 뒤 받을 수 있습니다.")
            return
        if not self.can_modify():
            self.gpu_status.setText("AI가 사용 중인 작업을 완료하거나 취소한 뒤 받으세요.")
            return
        self._run_gpu(
            lambda: self.gpu.install(approved=True, cancel=self.cancel, progress=self._notify),
            self._gpu_installed,
        )

    @property
    def gpu_busy(self) -> bool:
        """A GPU runtime install or removal is queued or running."""
        return self.task is not None and self.task is self._gpu_task

    def _run_gpu(self, operation: Callable[[], Any], finished: Callable[[Any], None]) -> None:
        before = self.task
        self._run(operation, finished)
        if self.task is not None and self.task is not before:
            self._gpu_task = self.task

    def _gpu_installed(self, path: Path) -> None:
        self.gpu_approval.setChecked(False)
        self.refresh_gpu()
        self.status.setText("GPU 런타임을 검증해 설치했습니다: " + str(path))

    def remove_gpu(self) -> None:
        if self.task is not None:
            return
        if not self.can_modify():
            self.gpu_status.setText("AI가 사용 중인 작업을 완료하거나 취소한 뒤 삭제하세요.")
            return
        if (
            QMessageBox.question(
                self,
                "GPU 런타임 삭제",
                "받아 둔 GPU 런타임을 삭제할까요? 삭제한 뒤에는 CPU 허용 정책은 CPU로"
                " 전사하고, GPU 전용 정책은 다시 받기 전까지 전사를 시작하지 않습니다.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        # The dialog ran a nested event loop: AI work or a model task may have started.
        if self.task is not None or not self.can_modify():
            self.gpu_status.setText("AI가 사용 중인 작업을 완료하거나 취소한 뒤 삭제하세요.")
            return
        try:
            self.release_gpu()
        except Exception:
            self.gpu_status.setText(
                "GPU 런타임을 쓰던 전사 프로세스를 닫지 못했습니다. 잠시 뒤 다시 시도하세요."
            )
            return
        self._run_gpu(self.gpu.remove, lambda _: self.refresh_gpu())

    @property
    def ollama_owned(self) -> bool:
        return self.ollama is not None

    def checked_attestation(self) -> Any:
        """Read the fixed GUI snapshot; the Gateway guards actual dispatch.

        Never enter a helper lock or query its process/listener/files here. An
        in-flight network handoff can hold that lock independently of our pool.
        """
        proof = self._ollama_proof
        if (
            self._shutdown_requested
            or self.task is not None
            or self.ollama is None
            or proof is None
            or self._proof_generation != self._ollama_generation
            or getattr(proof, "expires_at_monotonic", 0) <= time.monotonic()
        ):
            self.request_attestation_check()
            raise StateConflict("LOCAL_EXECUTION_UNVERIFIED")
        return proof

    def _invalidate_owned_proof(self) -> None:
        self._ollama_generation += 1
        self._proof_generation = None
        self._ollama_proof = None
        self.attestation_state = "UNVERIFIED"
        self.attestationChanged.emit(None)

    def _accept_proof(self, proof: Any, generation: int) -> None:
        if getattr(proof, "expires_at_monotonic", 0) <= time.monotonic():
            changed = self._ollama_proof is not None
            self._proof_generation = None
            self._ollama_proof = None
            self.attestation_state = "UNVERIFIED"
            if changed:
                self.attestationChanged.emit(None)
            return
        changed = proof != self._ollama_proof or self._proof_generation != generation
        self._ollama_proof = proof
        self._proof_generation = generation
        self.attestation_state = "READY"
        if changed:
            self.attestationChanged.emit(proof)

    def request_attestation_check(self) -> None:
        """Coalesce timer checks on the single model worker, fenced by owner generation."""
        if (
            self._shutdown_requested
            or self.task is not None
            or self._attestation_task is not None
            or self.ollama is None
        ):
            return
        owner, generation = self.ollama, self._ollama_generation
        task = Task(owner.attestation)
        self._attestation_task = task
        self.attestation_state = "CHECKING"

        def current() -> bool:
            return (
                not self._shutdown_requested
                and self.ollama is owner
                and self._ollama_generation == generation
            )

        def done(proof: Any) -> None:
            if self._attestation_task is task:
                self._attestation_task = None
            if current():
                self._accept_proof(proof, generation)

        def failed(code: str) -> None:
            if self._attestation_task is task:
                self._attestation_task = None
            if current():
                changed = self._ollama_proof is not None
                self._proof_generation = None
                self._ollama_proof = None
                self.attestation_state = "UNVERIFIED"
                if changed:
                    self.attestationChanged.emit(None)
                self.status.setText("로컬 Ollama 실행 확인 실패 · 요약 동의를 다시 확인하세요.")

        task.signals.finished.connect(done)
        task.signals.failed.connect(failed)
        self.pool.start(task)

    def start_ollama(self) -> None:
        if self._shutdown_requested or self.task is not None or not self.can_modify():
            return
        if self.ollama_owned or not self.ollama_approval.isChecked():
            self.status.setText("실행 파일·로컬 모델을 선택하고 서버 시작 의도를 확인하세요.")
            return
        executable, models, model = (
            self.ollama_executable.text().strip(),
            self.ollama_models.text().strip(),
            self.ollama_model.text().strip(),
        )
        if not executable or not models or not model:
            self.status.setText("실행 파일·모델 폴더·로컬 모델 이름:태그가 필요합니다.")
            return
        self._invalidate_owned_proof()
        generation = self._ollama_generation
        self.attestation_state = "PREPARING"

        def start() -> Any:
            from recoryn.models.ollama import ManagedOllama

            self.ollama = ManagedOllama()
            owner = self.ollama
            proof = owner.start(
                Path(executable).absolute(), Path(models).absolute(), model, cancel=self.cancel
            )
            return owner, proof

        def ready(value: Any) -> None:
            owner, proof = value
            if (
                self._shutdown_requested
                or self.cancel.is_set()
                or self.ollama is not owner
                or self._ollama_generation != generation
            ):
                return
            # start() already checked readiness in the worker. Do not re-enter
            # attestation() from its queued GUI completion callback.
            self._accept_proof(proof, generation)
            self.status.setText(
                "로컬 서버 실행을 확인했습니다. 요약 제공업체·컨텍스트·전사 동의를 설정하세요. "
                "외부 daemon의 후속 무전송은 별도 검증 대상입니다."
            )

        self._run(start, ready)

    def stop_ollama(self) -> None:
        if self.task is not None or self.ollama is None:
            return
        owner = self.ollama
        self._invalidate_owned_proof()  # fence queued checks before waiting for the owner lock
        self.attestation_state = "STOPPING"

        def stop() -> None:
            owner.close()
            if self.ollama is owner:
                self.ollama = None

        def stopped(value: Any) -> None:
            self.attestation_state = "UNVERIFIED"
            self.status.setText("이 앱 소유 Ollama의 종료를 확인했습니다.")

        self._run(stop, stopped)

    def _run(self, operation: Callable[[], Any], finished: Callable[[Any], None]) -> None:
        if self._shutdown_requested or self.task is not None:
            self.status.setText("현재 모델 작업의 종료 확인을 기다려주세요.")
            return
        self.cancel.clear()
        task = Task(operation)
        self.task = task
        self.download_button.setEnabled(False)

        def done(value: Any) -> None:
            self.task = None
            self.download_button.setEnabled(True)
            if not self._shutdown_requested:
                finished(value)

        def failed(code: str) -> None:
            self.task = None
            self.download_button.setEnabled(True)
            self.status.setText(
                "모델 작업 중단: " + code + " · 검증 전 파일은 활성화되지 않습니다."
            )
            self.refresh_gpu()

        task.signals.finished.connect(done)
        task.signals.failed.connect(failed)
        self.pool.start(task)

    def choose_manifest(self) -> None:
        if self.task is not None:
            return
        filename, _ = QFileDialog.getOpenFileName(self, "모델 manifest 선택", "", "JSON (*.json)")
        if not filename:
            return
        self.approval.setChecked(False)
        try:
            self.plan = parse_spec(read_json(Path(filename), limit=1024 * 1024))
        except (OSError, ValueError, TypeError):
            self.plan = None
            self.status.setText("manifest 형식·라이선스·경로·체크섬을 확인하세요.")
            return
        # The reviewed spec is this model's external reference for the current run
        # (G13 section 3.1); installed.json never approves itself.
        self._pins[self.plan.model_id] = spec_digest(self.plan)
        self.preview.setPlainText(
            f"모델: {self.plan.model_id}\n종류: {self.plan.kind}\n"
            f"라이선스: {self.plan.license_id}\n{self.plan.license_url}\n"
            f"공간: {sum(f.size for f in self.plan.files):,} bytes\n"
            f"저장: {self.manager.root / self.plan.model_id}\n\n"
            + "\n\n".join(f"{f.path}\n{f.url}\nSHA256: {f.sha256}" for f in self.plan.files)
        )

    def _notify(self, completed: int, total: int) -> None:
        now = time.monotonic()
        if completed == total or now - self._last_progress >= 0.1:
            self._last_progress = now
            self.notifier.update.emit(completed * 100 // total)

    def _progress_changed(self, percent: int) -> None:
        self.progress.setValue(percent)

    def download(self) -> None:
        if self.plan is None or not self.approval.isChecked():
            self.status.setText("다운로드 계획을 선택하고 출처와 라이선스를 확인하세요.")
            return
        if not self.can_modify():
            self.status.setText("AI가 사용 중인 모델 작업을 완료하거나 취소한 뒤 설치하세요.")
            return
        plan = self.plan
        self._run(
            lambda: self.manager.install(
                plan, approved=True, cancel=self.cancel, progress=self._notify
            ),
            self._installed,
        )

    def _installed(self, path: Path) -> None:
        self.status.setText("모든 파일을 검증한 뒤 설치했습니다: " + path.name)
        self.modelSelected.emit(str(path))
        self.refresh()

    def refresh(self) -> None:
        def show(items: list[dict[str, Any]]) -> None:
            self.installed.clear()
            for model in items:
                item = QListWidgetItem(
                    str(model["model_id"])
                    + (" · SHA256 확인" if model["verified"] else " · 무결성 확인 실패")
                )
                item.setData(256, model)
                self.installed.addItem(item)

        self._run(self.manager.list_installed, show)

    def choose_installed(self) -> None:
        item = self.installed.currentItem()
        if item is None:
            return
        model = item.data(256)
        if not model["verified"]:
            self.status.setText("무결성 확인에 실패한 모델은 사용할 수 없습니다.")
            return
        self.modelSelected.emit(model["path"])
        self.preview_model(Path(model["path"]))

    def delete_selected(self) -> None:
        item = self.installed.currentItem()
        if item is None or self.task is not None or not self.can_modify():
            return
        model_id = item.data(256)["model_id"]
        if (
            QMessageBox.question(
                self,
                "모델 삭제",
                f"{model_id}의 설치 파일과 이어받기 파일을 삭제할까요?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        from recoryn.models._artifact_io import release_idle

        release_idle()  # no idle sealed copy of this run outlives the deleted install
        self._run(lambda: self.manager.delete(model_id), lambda value: self.refresh())

    # --- G-P13 local model confirmation ---------------------------------------------

    def _managed(self, root: Path) -> bool:
        import os

        parent = os.path.normcase(os.path.abspath(root.parent))
        own = os.path.normcase(os.path.abspath(self.manager.root))
        return parent == own and os.path.normcase(str(root)) not in self._manual_roots

    def model_snapshot(self, path: Path, *, cancel: Any = None) -> art.ModelSourceSnapshot:
        """Hash a Whisper folder (worker lanes only). A folder directly in the managed
        root is a managed install checked against its pinned reference; anything else,
        or a managed folder the user explicitly adopted, is a user-specified model."""
        root = Path(path)
        if self._managed(root):
            return managed_snapshot(
                self.manager,
                root.name,
                self._pins.get(root.name),
                io=self.artifact_io,
                cancel=cancel,
            )
        return whisper_snapshot(root, io=self.artifact_io, cancel=cancel)

    def preview_model(self, path: Path) -> None:
        """Hash on this panel's model lane (cancellable), then show the preview."""

        def failed(value: Any) -> None:
            self.confirm_status.setText("모델 파일을 확인할 수 없습니다: " + str(value))

        def snapshot() -> Any:
            try:
                return self.model_snapshot(path, cancel=self.cancel)
            except ProviderError as error:
                return error

        def done(value: Any) -> None:
            if isinstance(value, ProviderError):
                failed(getattr(value, "detail", value.code))
            else:
                self.show_confirmation(value)

        self._run(snapshot, done)

    def show_confirmation(self, snapshot: art.ModelSourceSnapshot) -> None:
        """Show exactly these bytes; a repeated display of the same key changes nothing."""
        key = self.confirmations.key(snapshot)
        display = self.confirmations.display(snapshot)
        if key == self._confirm_key and self._confirm_snapshot == snapshot:
            return  # the same model shown again (poll): no reset, no new announcement
        self._confirm_token += 1
        self._confirm_snapshot, self._confirm_key = snapshot, key
        self.confirm_ack.setChecked(False)
        text = confirmation_text(snapshot, display)
        self.confirm_preview.setPlainText(text)
        confirmed = self.confirmations.evidence(snapshot) is not None
        self.confirm_button.setEnabled(art.eligible(snapshot) and not confirmed)
        self.adopt_button.setEnabled(
            snapshot.kind == art.WHISPER
            and snapshot.source_kind == art.MANAGED
            and snapshot.integrity == art.INVALID
        )
        status = "상태: " + _STATE_TEXT[display]
        self.confirm_status.setText(status)
        self._confirm_announce(self.confirm_status, status, a11y.POLITE)

    def confirm_model(self) -> None:
        """Record the shown snapshot only after Yes and the unchecked-by-default ack."""
        snapshot, key, token = self._confirm_snapshot, self._confirm_key, self._confirm_token
        if snapshot is None or key is None or not self.confirm_button.isEnabled():
            return
        accepted, _ = a11y.confirm(
            self,
            "로컬 모델 사용 확인",
            "표시한 파일과 SHA256만 이 실행 동안 사용합니다. 출처는 인증되지 않았고 "
            "사용 권한 확인은 사용자 책임입니다. 전송 동의·비용 승인이 아닙니다. 확인할까요?",
            fallback=self.confirm_preview,
        )
        if token != self._confirm_token or self._confirm_snapshot is not snapshot:
            self.confirm_status.setText("확인 화면이 바뀌어 기록하지 않았습니다. 다시 확인하세요.")
            return  # a late answer never approves another root, digest or run
        evidence = self.confirmations.confirm(
            snapshot, shown=key, accepted=accepted, acknowledged=self.confirm_ack.isChecked()
        )
        if evidence is None:
            text = (
                "확인하지 않았습니다(아니요/Esc)."
                if not accepted
                else "책임·조건 확인란을 선택해야 기록합니다."
            )
            self.confirm_status.setText(text)
            return
        self.confirm_button.setEnabled(False)
        display = self.confirmations.display(snapshot)
        self.confirm_preview.setPlainText(confirmation_text(snapshot, display))
        status = "상태: " + _STATE_TEXT[display] + " · 새 요청부터 이 파일로 실행합니다"
        self.confirm_status.setText(status)
        self._confirm_announce(self.confirm_status, status, a11y.POLITE)

    def adopt_manual(self) -> None:
        """An explicit, separate manual adoption of a managed folder (never automatic)."""
        import os

        snapshot = self._confirm_snapshot
        if snapshot is None or not self.adopt_button.isEnabled():
            return
        self._manual_roots.add(os.path.normcase(snapshot.root))
        self.adopt_button.setEnabled(False)
        self.preview_model(Path(snapshot.root))

    def refresh_cleanup(self) -> None:
        """Show copies whose cleanup failed ("임시 모델 사본 정리 대기"), G13R-07."""
        from recoryn.models._artifact_io import cleanup_pending

        count = cleanup_pending()
        text = f"임시 모델 사본 정리 대기 {count}개 — 다음 정리 때 다시 시도합니다" if count else ""
        if self.cleanup_status.text() != text:
            self.cleanup_status.setText(text)

    def shutdown(self) -> None:
        self._shutdown_requested = True
        self._invalidate_owned_proof()
        self.cancel.set()
        if not self.pool.waitForDone(5000):
            raise StateConflict("MODEL_DOWNLOAD_ACK_PENDING")
        if self.ollama is not None:
            self.ollama.close()
            self.ollama = None
