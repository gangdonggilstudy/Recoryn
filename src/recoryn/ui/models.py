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
from recoryn.models.gpu_runtime import DOWNLOAD_BYTES, TERMS, GpuRuntimeManager
from recoryn.models.manager import parse_spec
from recoryn.storage._safe import read_json
from recoryn.ui.tasks import Task

OLLAMA_POLICY_NOTE = (
    "로컬 Ollama 요약은 AI 실행 정책이 GPU_WITH_CPU_FALLBACK_ALLOWED일 때만 실행합니다. "
    "Recoryn은 Ollama 서버가 CPU와 GPU 중 무엇을 쓰는지와 서버 메모리를 통제하거나 보장하지 "
    "못하므로, CPU_ONLY·GPU_ONLY에서는 요약을 시작하지 않습니다. 정책은 자동으로 바꾸지 "
    "않으며, 앱을 다시 시작하면 기본값 CPU_ONLY로 돌아갑니다. 원격 제공업체는 이 PC의 "
    "장치 정책 대상이 아니며 동의·비용 확인은 그대로 적용됩니다."
)


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
        self._run(lambda: self.manager.delete(model_id), lambda value: self.refresh())

    def shutdown(self) -> None:
        self._shutdown_requested = True
        self._invalidate_owned_proof()
        self.cancel.set()
        if not self.pool.waitForDone(5000):
            raise StateConflict("MODEL_DOWNLOAD_ACK_PENDING")
        if self.ollama is not None:
            self.ollama.close()
            self.ollama = None
