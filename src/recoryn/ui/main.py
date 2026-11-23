"""Local-first desktop. Device capture begins only on the user's Record action."""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSignalBlocker, Qt, QThreadPool, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from recoryn.app.desktop import DesktopRecorder, TrackSelection
from recoryn.app.power import PowerCoordinator
from recoryn.app.recovery import (
    directory_only_lines,
    finalize_lines,
    recovery_view,
    unfinished_notice,
)
from recoryn.domain import SessionState, StateConflict
from recoryn.storage import Library
from recoryn.ui.tasks import Task

# Refusals shown as their own message; the session and its media stay unchanged.
_REFUSALS = {
    "INSPECTION_UNSAFE": "검사할 수 없음: 해당 세션 폴더의 링크·하드 링크를 제거한 뒤 새로고침하세요. 외부 경로는 열지 않았으며 복구·확정을 보류했습니다.",
    "INSPECTION_UNAVAILABLE": "검사할 수 없음: 해당 세션 폴더의 접근 권한과 저장 장치 연결을 확인한 뒤 새로고침하세요. 복구·확정을 보류했습니다.",
    "SESSION_LIVE": "녹음 중인 세션은 정지 후 복구하거나 확정할 수 있습니다.",
    "DELETE_PENDING": "삭제 요청이 있는 세션입니다. 확정하지 않았습니다.",
    "STALE_SESSION_VERSION": "세션 상태가 바뀌었습니다. 목록을 새로 고쳤으니 다시 확인하세요.",
    "NOT_FOUND": "세션을 찾을 수 없습니다. 목록을 새로 고쳤습니다.",
}


class MainWindow(QMainWindow):
    def __init__(self, library: Library, *, recorder: DesktopRecorder | None = None) -> None:
        super().__init__()
        self.library = library
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)  # control operations are serialized
        self._tasks: set[Task] = set()
        self.busy = False
        self._started_at: float | None = None
        self._closing = False
        self._closing_requested = False
        self.recorder = recorder or DesktopRecorder(library, self._source_factory)
        self.power = PowerCoordinator(self.recorder)
        self._pending_suspend = False
        self._pending_deletions: dict[str, dict[str, Any]] = {}
        self._inventory: dict[str, dict[str, Any]] = {}
        self._inventory_pool = QThreadPool(self)
        self._inventory_pool.setMaxThreadCount(1)
        self._inventory_tasks: set[Task] = set()
        self._inventory_generation = 0
        self._inventory_requested: int | None = None
        self._inventory_loading = False
        self._review_details: tuple[str, int, str] | None = None
        self.setWindowTitle("Recoryn — 로컬 AI 음성 기록")
        self.resize(1180, 780)
        self._build()
        from recoryn.ui.ai_bridge import DesktopAI

        self.ai_bridge = DesktopAI(self)
        from recoryn.security import ConsentStore, CostLedger, CredentialVault
        from recoryn.ui.privacy import PrivacyPanel

        self.consents = ConsentStore(library.root / "security.sqlite")
        self.ledger = CostLedger(library.root / "security.sqlite")
        self.privacy_panel = PrivacyPanel(self.consents, self.ledger, CredentialVault())
        self.ai_bridge.attach_privacy(self.privacy_panel)
        from recoryn.ui.models import ModelPanel

        self.model_panel = ModelPanel(
            library.root / "models",
            can_modify=self._models_idle,
            release_gpu=lambda: self.ai_bridge.release_gpu_runtime(),
        )
        self.model_panel.modelSelected.connect(self.local_model.setText)
        self.model_panel.attestationChanged.connect(self.privacy_panel.set_local_attestation)
        self.tabs.addTab(self.model_panel, "모델 관리")
        self.refresh_sessions()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(250)
        from recoryn.ui.power import WindowsPowerFilter

        self._power_filter = WindowsPowerFilter(
            lambda kind: QTimer.singleShot(0, lambda: self._power_event(kind))
        )
        application = QApplication.instance()
        if application is not None:
            application.installNativeEventFilter(self._power_filter)

    @staticmethod
    def _source_factory(device_id: str, loopback: bool) -> Any:
        from recoryn.capture.wasapi import WasapiSource

        return WasapiSource(device_id, loopback=loopback)

    def _build(self) -> None:
        container = QWidget()
        self.setCentralWidget(container)
        layout = QVBoxLayout(container)
        self.indicator = QLabel("대기 · 로컬 전용")
        self.indicator.setAccessibleName("녹음 및 저장 상태")
        self.indicator.setStyleSheet("font-size:22px;font-weight:600;padding:10px")
        layout.addWidget(self.indicator)
        device_bar = QHBoxLayout()
        self.microphone = QComboBox()
        self.system = QComboBox()
        for combo, label in ((self.microphone, "마이크"), (self.system, "시스템 출력")):
            combo.setAccessibleName(label + " 장치")
            combo.addItem("사용 안 함", None)
            device_bar.addWidget(QLabel(label))
            device_bar.addWidget(combo, 1)
        self.devices_button = QPushButton("장치 새로고침")
        self.devices_button.clicked.connect(self.refresh_devices)
        device_bar.addWidget(self.devices_button)
        layout.addLayout(device_bar)
        meters = QHBoxLayout()
        self.meters: dict[str, QProgressBar] = {}
        for track, label in (("mic", "마이크 음량"), ("system", "PC 소리 음량")):
            meters.addWidget(QLabel(label))
            meter = QProgressBar()
            meter.setRange(0, 100)
            meter.setValue(0)
            meter.setAccessibleName(label)
            meters.addWidget(meter)
            self.meters[track] = meter
        layout.addLayout(meters)
        controls = QHBoxLayout()
        self.record_button = QPushButton("● 녹음 시작 (Ctrl+R)")
        self.pause_button = QPushButton("일시정지 / 재개")
        self.stop_button = QPushButton("■ 정지 (Ctrl+.)")
        self.elapsed = QLabel("00:00:00")
        self.captured = QLabel("수락된 오디오: 없음")
        self.captured.setAccessibleName("트랙별 수락된 오디오 시간; 경과 시간과 다릅니다")
        self.record_button.clicked.connect(self.start_recording)
        self.pause_button.clicked.connect(self.pause_resume)
        self.stop_button.clicked.connect(self.stop_recording)
        for widget in (self.record_button, self.pause_button, self.stop_button, self.elapsed):
            controls.addWidget(widget)
        layout.addLayout(controls)
        layout.addWidget(self.captured)
        self.warning = QLabel(
            "녹음 전 참여자 동의와 적용 규정을 확인하세요. 외부 전송은 기본 차단됩니다."
        )
        self.warning.setWordWrap(True)
        self.warning.setAccessibleName("경고 및 처리 결과")
        layout.addWidget(self.warning)
        self.deletion_status = QLabel("")
        self.deletion_status.setWordWrap(True)
        self.deletion_status.setAccessibleName("삭제 진행·보류 이유와 원본 보존 상태")
        layout.addWidget(self.deletion_status)
        self.recovery_status = QLabel("")
        self.recovery_status.setWordWrap(True)
        self.recovery_status.setAccessibleName("미확정 세션 안내")
        layout.addWidget(self.recovery_status)
        splitter = QSplitter()
        layout.addWidget(splitter, 1)
        sidebar = QWidget()
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.addWidget(QLabel("기록"))
        self.sessions = QListWidget()
        self.sessions.setAccessibleName("녹음 세션 목록")
        self.sessions.currentItemChanged.connect(self._session_selected)
        sidebar_layout.addWidget(self.sessions)
        self.finalize_button = QPushButton("세션 확정")
        self.finalize_button.setAccessibleName("선택한 미확정 세션을 확정")
        self.finalize_button.clicked.connect(self.finalize_selected)
        for text, callback in (
            ("새로고침", self.refresh_sessions),
            ("복구 검토", self.recover_selected),
            (None, None),
            ("오디오 내보내기", self.export_selected),
            ("세션 삭제", self.delete_selected),
        ):
            if text is None:
                sidebar_layout.addWidget(self.finalize_button)
                continue
            button = QPushButton(text)
            button.clicked.connect(callback)
            sidebar_layout.addWidget(button)
        self.retry_delete_button = QPushButton("삭제 대기 재시도")
        self.retry_delete_button.setAccessibleName("숨겨진 삭제 대기 세션의 원본 제거 재시도")
        self.retry_delete_button.clicked.connect(self.retry_pending_deletions)
        sidebar_layout.addWidget(self.retry_delete_button)
        splitter.addWidget(sidebar)
        self.tabs = QTabWidget()
        splitter.addWidget(self.tabs)
        splitter.setStretchFactor(1, 4)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setAccessibleName("세션 상태와 복구 정보")
        self.tabs.addTab(self.details, "녹음 정보")
        settings = QWidget()
        form = QFormLayout(settings)
        self.local_model = QLineEdit()
        self.local_model.setAccessibleName("로컬 Whisper 모델 폴더")
        form.addRow("로컬 Whisper 모델", self.local_model)
        choose = QPushButton("모델 폴더 선택")
        choose.clicked.connect(self._choose_model)
        form.addRow(choose)
        self.device_policy = QComboBox()
        self.device_policy.addItems(["CPU_ONLY", "GPU_ONLY", "GPU_WITH_CPU_FALLBACK_ALLOWED"])
        form.addRow("AI 실행 정책", self.device_policy)
        self.live_stt = QCheckBox("녹음 중 임시 전사 (모델 설정 후 적용)")
        self.live_stt.setChecked(False)
        form.addRow(self.live_stt)
        retry_live = QPushButton("임시 전사 새 작업으로 명시 재개")
        retry_live.clicked.connect(lambda: self.ai_bridge.retry_live())
        form.addRow(retry_live)
        self.diarization_manifest = QLineEdit()
        self.diarization_manifest.setAccessibleName("검증할 로컬 화자 분리 manifest 경로")
        form.addRow("선택 화자 분리 manifest", self.diarization_manifest)
        self.diarization_hash = QLineEdit()
        self.diarization_hash.setAccessibleName("신뢰한 화자 분리 manifest의 SHA256")
        form.addRow("manifest SHA256", self.diarization_hash)
        self.diarization_approval = QCheckBox(
            "선택 모델의 출처·라이선스를 확인하고 CPU 화자 분리에 동의합니다. "
            "익명 추정이며 사람 신원을 확인하지 않습니다."
        )
        form.addRow(self.diarization_approval)
        self.tabs.addTab(settings, "AI 및 개인정보 설정")
        for sequence, callback in (
            ("Ctrl+R", self._record_shortcut),
            ("Ctrl+.", self.stop_recording),
        ):
            action = QAction(self)
            action.setShortcut(QKeySequence(sequence))
            action.triggered.connect(callback)
            self.addAction(action)
        self.statusBar().showMessage(
            "데이터는 이 PC에 저장됩니다. 장치 백엔드는 실장비 검증 전입니다."
        )
        self._update_controls()

    def _record_shortcut(self) -> None:
        if isinstance(QApplication.focusWidget(), (QLineEdit, QPlainTextEdit)):
            return
        self.start_recording()

    def _power_event(self, kind: str) -> None:
        if self._closing_requested:
            return
        if kind == "suspend":
            self._pending_suspend = True
            self.live_stt.setChecked(False)
            self.warning.setText("절전 알림 · 캡처와 저장 종료 확인 중입니다.")
        elif kind == "resume":
            self.warning.setText(
                "절전 복귀 · 자동 녹음 재개 없음. 종료 확인 후 재개를 직접 선택하세요. "
                "중단 구간은 복원되지 않습니다."
            )
        self._drain_power()

    def _drain_power(self) -> None:
        if not self._pending_suspend or self.busy or self._closing_requested:
            return
        self._pending_suspend = False

        def paused(value: Any) -> None:
            if value:
                self.indicator.setText("Ⅱ 절전 일시정지 · 재개는 사용자 동작이 필요합니다")
            self.refresh_sessions()

        self.operation(self.power.suspend, paused)

    def operation(
        self, action: Callable[[], Any], done: Callable[[Any], None] | None = None
    ) -> None:
        if self.busy:
            return
        self.busy = True
        self._update_controls()
        task = Task(action)
        self._tasks.add(task)

        def success(result: Any) -> None:
            self._tasks.discard(task)
            self.busy = False
            if done:
                done(result)
            self._update_controls()
            self._drain_power()

        def failure(code: str) -> None:
            self._tasks.discard(task)
            self.busy = False
            self.warning.setText("작업 실패: " + code + " · 보존된 원본과 복구 정보를 확인하세요.")
            self._update_controls()
            self._drain_power()

        task.signals.finished.connect(success)
        task.signals.failed.connect(failure)
        self.pool.start(task)

    def _update_controls(self) -> None:
        active = False
        if self.recorder.session_id:
            active = self.library.get_session(self.recorder.session_id).state in {
                SessionState.RECORDING,
                SessionState.PAUSED,
            }
        self.record_button.setEnabled(not self.busy and not active)
        self.pause_button.setEnabled(not self.busy and active)
        self.stop_button.setEnabled(not self.busy and active)
        for combo in (self.microphone, self.system):
            combo.setEnabled(not self.busy and not active)
        self.devices_button.setEnabled(not self.busy and not active)
        self.retry_delete_button.setEnabled(not self.busy and bool(self._pending_deletions))
        self.finalize_button.setEnabled(self._finalize_allowed())

    def _finalize_allowed(self) -> bool:
        """Unfinished, not live, not busy; the current recorder session only if INTERRUPTED."""
        session_id = self.selected_session()
        if self.busy or self._inventory_loading or not session_id:
            return False
        entry = self._inventory.get(session_id)
        if entry is None or entry["live"] or entry.get("inspection_error"):
            return False
        if session_id == self.recorder.session_id:
            # A paused current recording is finished with the normal Stop control.
            return bool(entry["state"] == SessionState.INTERRUPTED.value)
        return True

    def refresh_devices(self) -> None:
        def enumerate_devices() -> Any:
            from recoryn.capture.devices import list_devices

            return list_devices()

        def show(items: Any) -> None:
            for combo in (self.microphone, self.system):
                combo.clear()
                combo.addItem("사용 안 함", None)
            for item in items:
                combo = self.microphone if item.flow == "capture" else self.system
                combo.addItem(item.name + (" (기본)" if item.default else ""), item.device_id)
            self.warning.setText("장치 목록을 갱신했습니다. 녹음할 트랙을 직접 선택하세요.")

        self.operation(enumerate_devices, show)

    def start_recording(self) -> None:
        if self.busy or not self.record_button.isEnabled():
            return
        choices = [
            ("mic", self.microphone.currentData(), False),
            ("system", self.system.currentData(), True),
        ]
        if not any(device for _, device, _ in choices):
            self.warning.setText(
                "장치를 새로고침한 뒤 녹음할 마이크 또는 시스템 출력을 선택하세요."
            )
            return

        def start() -> str:
            from recoryn.capture.devices import probe_device

            selections = tuple(
                TrackSelection(track, device, loopback, probe_device(device, loopback=loopback))
                for track, device, loopback in choices
                if device
            )
            return self.recorder.start(selections)

        def started(session_id: str) -> None:
            self._started_at = time.monotonic()
            self.indicator.setText("● REC · 녹음 중 · 로컬 저장")
            self.warning.setText("녹음 중입니다. AI 실패는 원본 저장을 중단시키지 않습니다.")
            self.refresh_sessions()

        self.operation(start, started)

    def pause_resume(self) -> None:
        if not self.recorder.session_id:
            return
        paused = self.library.get_session(self.recorder.session_id).state == SessionState.PAUSED

        def done(result: Any) -> None:
            self.indicator.setText(
                "● REC · 녹음 중" if paused else "Ⅱ 일시정지 · 중단 구간은 복원되지 않습니다"
            )
            self.refresh_sessions()

        self.operation(self.power.resume if paused else self.recorder.pause, done)

    def stop_recording(self) -> None:
        if not self.stop_button.isEnabled():
            return

        def done(result: Any) -> None:
            self.indicator.setText(
                "■ 원본 확정 · manifest 동기화 대기 · AI 처리는 별도"
                if result.get("manifest_sync_pending")
                else "■ 원본 저장 완료 · AI 처리는 별도"
            )
            self._started_at = None
            self.refresh_sessions()

        self.operation(self.recorder.stop, done)

    def refresh_sessions(self) -> None:
        """Refresh cheap catalog rows now; inspect folders off the GUI thread."""
        if self._closing_requested:
            return
        self._inventory_generation += 1
        self._inventory_requested = self._inventory_generation
        self._inventory_loading = True
        self.recovery_status.setText("미확정 세션 확인 중")
        self._render_sessions(list(self._inventory.values()))
        self._start_inventory()

    def _start_inventory(self) -> None:
        if self._inventory_tasks or self._inventory_requested is None or self._closing_requested:
            return
        generation = self._inventory_requested
        self._inventory_requested = None
        library = self.library
        task = Task(library.unfinished_inventory)
        self._inventory_tasks.add(task)

        def complete(result: Any, *, failed: bool = False) -> None:
            self._inventory_tasks.discard(task)
            if self._closing_requested:
                return
            if generation == self._inventory_generation:
                self._inventory_loading = False
                if failed:
                    self._inventory = {}
                    self.recovery_status.setText(
                        "미확정 세션을 확인하지 못했습니다. ‘새로고침’으로 다시 확인하세요."
                    )
                    self._render_sessions([])
                else:
                    items, warnings = result
                    self._inventory = {item["session_id"]: item for item in items}
                    notice = unfinished_notice(
                        items, warnings["skipped_entries"], current=self.recorder.session_id
                    )
                    if items:
                        notice += " 조회 시점의 관찰이며, 복구·확정 시 다시 검사합니다."
                    self.recovery_status.setText(notice)
                    self._render_sessions(items)
            self._start_inventory()  # only the newest coalesced request remains

        task.signals.finished.connect(complete, Qt.ConnectionType.QueuedConnection)
        task.signals.failed.connect(
            lambda code: complete(None, failed=True), Qt.ConnectionType.QueuedConnection
        )
        self._inventory_pool.start(task)

    def _render_sessions(self, items: list[dict[str, Any]]) -> None:
        current = self.selected_session()
        recording = self.recorder.session_id
        blocker = QSignalBlocker(self.sessions)
        self.sessions.clear()
        try:
            sessions = self.library.list_sessions()
        except (ValueError, OSError):
            sessions = []
            self.recovery_status.setText(
                "미확정 세션을 확인하지 못했습니다. ‘새로고침’으로 다시 확인하세요."
            )
        for session in sessions:
            entry = self._inventory.get(session.session_id)
            unfinished = entry is not None and not entry["live"] and session.session_id != recording
            label = session.state.value + (" · 미확정" if unfinished else "")
            if entry is not None and entry.get("inspection_error"):
                label += " · 검사할 수 없음(" + str(entry["inspection_error"]) + ")"
            item = QListWidgetItem(f"{label}  {session.session_id[:12]}")
            item.setData(Qt.ItemDataRole.UserRole, session.session_id)
            self.sessions.addItem(item)
            if session.session_id == current:
                self.sessions.setCurrentItem(item)
        for entry in items:
            if entry["state"] != "DIRECTORY_ONLY":
                continue
            label = (
                "검사할 수 없음(" + str(entry["inspection_error"]) + ")"
                if entry.get("inspection_error")
                else "폴더만 있음 · 복구 필요"
            )
            item = QListWidgetItem(f"{label}  {entry['session_id'][:12]}")
            item.setData(Qt.ItemDataRole.UserRole, entry["session_id"])
            self.sessions.addItem(item)
            if entry["session_id"] == current:
                self.sessions.setCurrentItem(item)
        blocker.unblock()
        self._session_selected()
        self._update_controls()

    def selected_session(self) -> str | None:
        item = self.sessions.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def _session_selected(self, current: Any = None, previous: Any = None) -> None:
        session_id = self.selected_session()
        if (
            self._review_details is not None
            and session_id is not None
            and self._review_details[0] != session_id
        ):
            self._review_details = None
        self._update_controls()
        if session_id is None:
            return
        entry = self._inventory.get(session_id)
        if entry is not None and entry.get("inspection_error"):
            self.ai_bridge.panel.setEnabled(False)
            self.details.setPlainText(
                f"세션: {session_id}\n" + _REFUSALS[str(entry["inspection_error"])]
            )
            return
        if entry is not None and entry["state"] == "DIRECTORY_ONLY":
            # No catalog row yet: show the inventory, never the AI panel for it.
            # Preserve previous edit input, but make every AI/edit control inert.
            self.ai_bridge.panel.setEnabled(False)
            self.details.setPlainText("\n".join(directory_only_lines(entry)))
            return
        session = self.library.get_session(session_id)
        chunks = self.library.chunks(session_id)
        self.ai_bridge.panel.setEnabled(True)
        self.ai_bridge.selection(session_id)
        if self._review_details is not None and self._review_details[:2] == (
            session_id,
            session.state_version,
        ):
            self.details.setPlainText(self._review_details[2])
            return
        self._review_details = None
        self.details.setPlainText(
            f"세션: {session_id}\n녹음 상태: {session.state.value}\n확정 청크: {len(chunks)}\n"
            f"원본 트랙: {', '.join(sorted({item.track_id for item in chunks}))}\n"
            f"건강 정보: {self.library.capture_health(session_id)}\n\n"
            "원본 확정과 전사·요약 완료는 별개입니다. 실장비 호환성·무손실은 보장되지 않습니다."
        )

    def _refusal(self, error: Exception) -> dict[str, str] | None:
        if isinstance(error, KeyError):
            return {"refused": "NOT_FOUND"}
        code = error.args[0] if isinstance(error, StateConflict) and error.args else None
        if code == "Live writer cannot be recovered":
            code = "SESSION_LIVE"
        return {"refused": code} if code in _REFUSALS else None

    def _show_refusal(self, code: str) -> None:
        self.warning.setText(_REFUSALS[code])
        self.refresh_sessions()

    def recover_selected(self) -> None:
        session_id = self.selected_session()
        if not session_id:
            return
        entry = self._inventory.get(session_id)
        if entry is not None and entry.get("inspection_error"):
            self._show_refusal(str(entry["inspection_error"]))
            return

        def recover() -> Any:
            try:
                result = self.library.recover_session(session_id)
            except (StateConflict, KeyError) as error:
                refused = self._refusal(error)
                if refused is None:
                    raise
                return refused
            if result.get("state") == "DELETE_PENDING":
                return result, [], {}
            return (
                result,
                self.library.chunks(session_id),
                self.library.capture_health(session_id),
            )

        def done(value: Any) -> None:
            if isinstance(value, dict):
                self._show_refusal(value["refused"])
                return
            result, chunks, health = value
            # Pin this explicit review to the state version; a later read-only
            # inventory result must not overwrite it with generic details.
            self.refresh_sessions()
            text = "\n".join(recovery_view(result, chunks, health).lines())
            self._review_details = (
                session_id,
                self.library.get_session(session_id).state_version,
                text,
            )
            self.details.setPlainText(text)
            self.warning.setText(
                "복구 결과를 확인하세요. 누락되거나 불확실한 구간은 원본으로 복원되지 않습니다."
            )

        self.operation(recover, done)

    def _finalize_dialog(self) -> QMessageBox:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("세션 확정")
        box.setText(
            "확정하면 이 세션에 더 녹음할 수 없습니다. 검증되지 않은 끝부분과 중단 구간은 "
            "복원되지 않습니다. 확정할까요?"
        )
        yes = box.addButton("확정", QMessageBox.ButtonRole.YesRole)
        no = box.addButton("아니요", QMessageBox.ButtonRole.NoRole)
        yes.setAccessibleName("세션 확정 승인")
        no.setAccessibleName("세션 확정 취소")
        box.setDefaultButton(no)
        box.setEscapeButton(no)  # Esc never confirms.
        return box

    def _confirm_finalize(self) -> bool:
        box = self._finalize_dialog()
        box.exec()
        confirmed = box.clickedButton() is not None and box.clickedButton() is not (
            box.escapeButton()
        )
        self.sessions.setFocus()
        return confirmed

    def finalize_selected(self) -> None:
        session_id = self.selected_session()
        if not session_id or not self._finalize_allowed():
            return
        entry = self._inventory[session_id]
        if not self._confirm_finalize():
            return
        current = self.recorder.session_id == session_id
        expected = entry["state_version"]

        def finalize() -> Any:
            if current:
                # Acknowledge sources and the writer before sealing (as delete does).
                self.recorder.close()
                self.recorder.recording = None
            try:
                result = self.library.finalize_unfinished(session_id, expected_version=expected)
            except (StateConflict, KeyError) as error:
                refused = self._refusal(error)
                if refused is None:
                    raise
                return refused
            return (
                result,
                self.library.chunks(session_id),
                self.library.capture_health(session_id),
            )

        def done(value: Any) -> None:
            if isinstance(value, dict):
                self._show_refusal(value["refused"])
                return
            result, chunks, health = value
            self.refresh_sessions()
            text = "\n".join(finalize_lines(result, chunks, health))
            self._review_details = (
                session_id,
                self.library.get_session(session_id).state_version,
                text,
            )
            self.details.setPlainText(text)
            self.warning.setText(
                "세션을 확정했습니다. 내보내기와 전사를 요청할 수 있습니다. "
                "중단·누락 구간은 복원되지 않습니다."
            )

        self.operation(finalize, done)

    def export_selected(self) -> None:
        session_id = self.selected_session()
        if not session_id or self.busy:
            return
        base = QFileDialog.getExistingDirectory(self, "내보낼 상위 폴더 선택")
        if not base:
            return
        destination = Path(base) / ("Recoryn-" + session_id[:12] + "-" + str(time.time_ns()))

        def export() -> Any:
            from recoryn.cli import _export

            return _export(self.library, session_id, destination)

        self.operation(
            export, lambda value: self.warning.setText("오디오 내보내기 완료: " + str(destination))
        )

    def delete_selected(self) -> None:
        session_id = self.selected_session()
        if not session_id or self.busy:
            return
        choice = QMessageBox.question(
            self,
            "세션 삭제",
            "원본과 기록을 삭제하면 근거 음성을 재생할 수 없습니다. 내보낸 사본은 남습니다. 삭제할까요?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if choice == QMessageBox.StandardButton.Yes:
            self.ai_bridge.stop_playback()

            def delete() -> Any:
                self.ai_bridge.before_delete(session_id)
                if self.recorder.session_id == session_id:
                    # Release acknowledged capture/writer ownership before
                    # deleting the session metadata used by later UI polling.
                    self.recorder.close()
                    self.recorder.recording = None
                return self.library.delete_session(session_id)

            self.operation(
                delete,
                self._delete_result,
            )

    def _delete_result(self, result: dict[str, Any]) -> None:
        session_id = result["session_id"]
        if result.get("deleted") is True and result.get("state") == "DELETED_LOCAL":
            self._pending_deletions.pop(session_id, None)
            self.deletion_status.setText("로컬 원본·기록 삭제 완료 · 내보낸 사본은 남습니다.")
            self.warning.setText("로컬 삭제를 완료했습니다.")
        else:
            # Keep the ID independently of list_sessions(), which correctly
            # hides deletion intents. A live reader still owns the media.
            self._pending_deletions[session_id] = dict(result)
            self._show_pending_deletions()
        if self.recorder.recording is None:
            self._started_at = None
        self.refresh_sessions()
        panel = self.ai_bridge.panel
        if panel.session_id == session_id and self.selected_session() != session_id:
            panel.session_id = None
            panel.show_transcript(None)
            panel._show_summary(None)

    def _show_pending_deletions(self) -> None:
        if not self._pending_deletions:
            return
        result = next(iter(self._pending_deletions.values()))
        reason = {
            "ACTIVE_READER_OR_WRITER": "로컬 reader/writer 종료 확인 대기",
            "MEDIA_REMOVAL_FAILED": "원본 파일 제거 실패",
        }.get(str(result.get("reason", "")), "삭제 상태 확인 필요")
        if result.get("state") == "DELETE_PENDING" and result.get("deleted") is False:
            text = (
                f"삭제 대기 {len(self._pending_deletions)}건 · 원본 제거 보류 · {reason}. "
                "원본 제거가 끝나지 않았으며 삭제 완료가 아닙니다. "
                "종료 확인 후 ‘삭제 대기 재시도’를 선택하세요."
            )
        else:
            text = (
                "삭제 결과 확인 필요 · 로컬 원본 삭제 완료를 확인하지 못했습니다. "
                "‘삭제 대기 재시도’로 상태를 다시 확인하세요."
            )
        self.deletion_status.setText(text)
        self.warning.setText(text)

    def retry_pending_deletions(self) -> None:
        if self.busy or not self._pending_deletions:
            return
        sessions = tuple(self._pending_deletions)

        def retry() -> list[dict[str, Any]]:
            return [self.library.delete_session(session) for session in sessions]

        def done(results: list[dict[str, Any]]) -> None:
            for result in results:
                self._delete_result(result)
            self._show_pending_deletions()

        self.operation(retry, done)

    def _choose_model(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "이미 설치한 로컬 모델 폴더")
        if directory:
            self.local_model.setText(directory)

    def _models_idle(self) -> bool:
        if self.ai_bridge.busy:
            return False
        service = self.ai_bridge.service
        if service is None:
            return True
        snapshot = service.runner.snapshot()
        return not snapshot["active"] and not snapshot["pending"]

    def _tick(self) -> None:
        if self._closing_requested:
            return
        if self._started_at is not None:
            seconds = int(time.monotonic() - self._started_at)
            self.elapsed.setText(f"{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}")
        self.ai_bridge.tick()
        blocks, health = self.recorder.observations()
        if health:
            self.warning.setText("장치 상태: " + str(health[-1].get("code", "CAPTURE_WARNING")))
        recording = self.recorder.recording
        if recording is not None:
            capture_health = recording.health_snapshot()
            if capture_health["storage_failed"]:
                self.indicator.setText("저장 오류 · 녹음 지속을 확인할 수 없습니다")
                self.warning.setText("확정된 원본은 보존됩니다. 정지 후 복구 정보를 확인하세요.")
            elif any(track["dropped_frames"] for track in capture_health["tracks"].values()):
                self.warning.setText(
                    "오디오 저장 큐 포화로 유실된 프레임이 있습니다. 건강 정보에 누계를 보존합니다."
                )
            chunks = [] if self.busy else self.library.chunks(recording.session_id)
            times = []
            epochs = recording.epochs
            for track, fmt in recording.formats.items():
                previous = sum(
                    chunk.frame_count / chunk.format.sample_rate
                    for chunk in chunks
                    if chunk.track_id == track and chunk.epoch_id != epochs[track]
                )
                frames = capture_health["tracks"].get(track, {}).get("accepted_frames", 0)
                times.append(f"{track} {previous + frames / fmt.sample_rate:.2f}초")
            self.captured.setText("수락된 오디오 (저장 확정과 별개): " + " · ".join(times))
        for track, meter in self.meters.items():
            from recoryn.ui.meter import peak_percent

            meter.setValue(peak_percent(blocks[track]) if track in blocks else 0)
        if self._pending_deletions and not (
            recording is not None and recording.health_snapshot()["storage_failed"]
        ):
            self._show_pending_deletions()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._closing:
            event.accept()
            return
        event.ignore()
        if self.busy:
            self.warning.setText("현재 작업의 확인을 기다린 뒤 닫아주세요.")
            return

        self._closing_requested = True
        self._inventory_generation += 1
        self._inventory_requested = None
        self.ai_bridge.stop_playback()
        central = self.centralWidget()
        if central is not None:
            central.setEnabled(False)

        def closed(result: Any) -> None:
            self.timer.stop()
            application = QApplication.instance()
            if application is not None:
                application.removeNativeEventFilter(self._power_filter)
            self._closing = True
            self.close()

        def shutdown() -> None:
            self.recorder.close()
            self._inventory_pool.waitForDone()  # worker ACK before Library can close
            self.model_panel.shutdown()
            self.ai_bridge.close()
            self.consents.close()
            self.ledger.close()

        self.operation(shutdown, closed)


def run(root: str | None = None) -> int:
    application = QApplication.instance() or QApplication(sys.argv[:1])
    data = (
        Path(root) if root else Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Recoryn"
    )
    with Library(data) as library:
        window = MainWindow(library)
        window.show()
        return application.exec()
