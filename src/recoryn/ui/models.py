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
from recoryn.models.manager import parse_spec
from recoryn.storage._safe import read_json
from recoryn.ui.tasks import Task


class _Progress(QObject):
    update = Signal(int)


class ModelPanel(QWidget):
    modelSelected = Signal(str)
    attestationChanged = Signal(object)

    def __init__(self, root: Path, *, can_modify: Callable[[], bool] | None = None) -> None:
        super().__init__()
        self.manager = ModelManager(root)
        self.can_modify = can_modify or (lambda: True)
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
        layout.addWidget(QLabel("로컬 Ollama — 이미 설치한 실행 파일과 모델만 사용합니다."))
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
