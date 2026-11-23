"""Transcript revisions, audited editing and source-linked summary navigation."""

from __future__ import annotations

import html
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from recoryn.app.status import AIStatus
from recoryn.content import ContentStore


def timestamp(milliseconds: int) -> str:
    seconds, millis = divmod(milliseconds, 1000)
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes // 60:02}:{minutes % 60:02}:{seconds:02}.{millis:03}"


class ContentPanel(QWidget):
    transcribeRequested = Signal()
    summarizeRequested = Signal(str)
    cancelRequested = Signal()
    retryTranscribeRequested = Signal()
    retrySummaryRequested = Signal(str)
    diarizeRequested = Signal()
    seekRequested = Signal(str, int, str)
    blockedOpenRequested = Signal()
    blockedContinueRequested = Signal()

    def __init__(self, store: ContentStore, operation: Callable[..., Any]) -> None:
        super().__init__()
        self.store, self.operation = store, operation
        self.session_id: str | None = None
        self.revision: dict[str, Any] | None = None
        self._loading = False
        self._claim_refs: dict[str, tuple[str, str]] = {}
        self._expected_active: str | None = None
        self._edit_pending = False
        self._unsaved_edit = False
        layout = QVBoxLayout(self)
        actions = QHBoxLayout()
        for text, signal in (
            ("전체 전사 실행", self.transcribeRequested),
            ("전사 명시 재실행", self.retryTranscribeRequested),
            ("AI 작업 취소", self.cancelRequested),
        ):
            button = QPushButton(text)
            if text == "전체 전사 실행":
                self.transcribe_button = button
            button.clicked.connect(signal.emit)
            actions.addWidget(button)
        self.search = QLineEdit()
        self.search.setPlaceholderText("전사문 검색")
        self.search.setAccessibleName("전사문 검색")
        self.search.textChanged.connect(self._filter)
        actions.addWidget(self.search)
        layout.addLayout(actions)
        history = QHBoxLayout()
        self.versions = QComboBox()
        self.versions.setAccessibleName("전사 버전 및 편집 이력")
        self.versions.currentIndexChanged.connect(self._version_changed)
        history.addWidget(self.versions, 1)
        self.select_button = QPushButton("이 버전 선택")
        self.select_button.clicked.connect(self.select_version)
        history.addWidget(self.select_button)
        export = QPushButton("TXT / SRT / VTT / JSON 내보내기")
        export.clicked.connect(self.export)
        history.addWidget(export)
        layout.addLayout(history)
        self.status = QLabel("세션을 선택하세요.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.job_status = QLabel("AI 대기 · 녹음 조작과 독립적으로 실행합니다.")
        self.job_status.setWordWrap(True)
        self.job_status.setAccessibleName("AI 작업·취소·원격 결과 상태")
        layout.addWidget(self.job_status)
        blocked_actions = QHBoxLayout()
        self.blocked_open = QPushButton("설정 위치 확인")
        self.blocked_open.setAccessibleName("AI 차단 사유의 설정 위치 확인; 자동 실행 안 함")
        self.blocked_continue = QPushButton("조건 다시 확인 후 계속")
        self.blocked_continue.setAccessibleName("현재 선택의 같은 AI 작업 조건을 다시 확인 후 계속")
        self.blocked_open.clicked.connect(self.blockedOpenRequested.emit)
        self.blocked_continue.clicked.connect(self.blockedContinueRequested.emit)
        for button in (self.blocked_open, self.blocked_continue):
            button.setEnabled(False)
            blocked_actions.addWidget(button)
        layout.addLayout(blocked_actions)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["시작", "전사문 (편집 시 새 버전)", "근거", "트랙 / 화자"]
        )
        self.table.setAccessibleName("시간순 전사문; 시간 셀을 두 번 누르면 원본 재생")
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(1, 480)
        self.table.itemChanged.connect(self._edited)
        self.table.cellDoubleClicked.connect(self._seek)
        self._edit_triggers = self.table.editTriggers()
        layout.addWidget(self.table, 3)
        retry_edit = QPushButton("보존된 편집 입력 저장 재시도")
        retry_edit.clicked.connect(self._retry_edit)
        layout.addWidget(retry_edit)
        summary_actions = QHBoxLayout()
        self.templates = QComboBox()
        for label, key in (
            ("회의록", "meeting"),
            ("강의 노트", "lecture"),
            ("핵심 요약", "key_points"),
            ("결정 사항", "decisions"),
            ("할 일", "tasks"),
        ):
            self.templates.addItem(label, key)
        summary_actions.addWidget(self.templates)
        summary_button = QPushButton("선택 전사 요약")
        summary_button.clicked.connect(
            lambda: self.summarizeRequested.emit(self.templates.currentData())
        )
        summary_actions.addWidget(summary_button)
        retry_summary = QPushButton("요약 명시 재실행")
        retry_summary.clicked.connect(
            lambda: self.retrySummaryRequested.emit(self.templates.currentData())
        )
        summary_actions.addWidget(retry_summary)
        layout.addLayout(summary_actions)
        self.claims = QTextBrowser()
        self.claims.setAccessibleName("AI 요약과 원본 근거; 사실성은 검토가 필요합니다")
        self.claims.setOpenExternalLinks(False)
        self.claims.setOpenLinks(False)
        self.claims.anchorClicked.connect(lambda url: self._claim_clicked(url.toString()))
        layout.addWidget(self.claims, 2)
        diarization = QHBoxLayout()
        self.diarization_ranges = QComboBox()
        self.diarization_ranges.setAccessibleName("익명 화자 추정을 적용할 고정 원본 구간")
        diarization.addWidget(self.diarization_ranges, 1)
        speakers = QPushButton("선택 구간 익명 화자 추정 (CPU)")
        speakers.clicked.connect(self.diarizeRequested.emit)
        diarization.addWidget(speakers)
        layout.addLayout(diarization)

    def show_ai_status(self, status: AIStatus) -> None:
        self.job_status.setText(status.text)
        self.blocked_open.setEnabled(status.action_id is not None)
        self.blocked_continue.setEnabled(status.can_continue)

    def load(self, session_id: str) -> None:
        if self.session_id != session_id:
            self.show_ai_status(AIStatus("AI 대기 · 녹음 조작과 독립적으로 실행합니다."))
        same_session = self.session_id == session_id
        if same_session and (
            self.table.state() == QAbstractItemView.State.EditingState
            or self._edit_pending
            or self._unsaved_edit
        ):
            # Replacing table items destroys an active delegate/IME composition.
            # Keep the revision and CAS expectation captured before editing.
            return
        viewed = self.revision if same_session else None
        following_active = viewed is None or viewed["revision_id"] == self._expected_active
        self.session_id = session_id
        active = self.store.active_transcript(session_id)
        self._expected_active = active["revision_id"] if active else None
        displayed = active if following_active else viewed
        revisions = self.store.list_revisions(session_id, "transcript")
        self._loading = True
        self.versions.clear()
        selected = -1
        for index, revision in enumerate(revisions):
            identifier = revision["revision_id"]
            label = f"{revision.get('kind', 'transcript')} · {identifier[:10]}"
            if active and identifier == active["revision_id"]:
                label += " · 선택됨"
            if displayed and identifier == displayed["revision_id"]:
                selected = index
            self.versions.addItem(label, identifier)
        self.versions.setCurrentIndex(selected)
        self._loading = False
        if (
            self.revision is None
            or displayed is None
            or self.revision["revision_id"] != displayed["revision_id"]
            or not same_session
        ):
            self.show_transcript(displayed)
        summary = self.store.active_summary(session_id)
        self._show_summary(summary)

    def show_transcript(self, revision: dict[str, Any] | None) -> None:
        self._unsaved_edit = False
        self.revision = revision
        self._loading = True
        self.diarization_ranges.clear()
        for source in (revision or {}).get("coverage", {}).get("source_ranges", []):
            if source.get("offset_ms") is not None:
                self.diarization_ranges.addItem(
                    f"{source['track_id']} · {timestamp(source['offset_ms'])} · "
                    f"{source['duration_ms'] / 1000:.2f}초",
                    source,
                )
        segments = revision["segments"] if revision else []
        self.table.setRowCount(len(segments))
        for row, segment in enumerate(segments):
            values = [
                timestamp(segment["start_ms"]),
                segment["text"],
                segment["provenance"],
                " · ".join(
                    str(value)
                    for value in (segment.get("track_id"), segment.get("speaker"))
                    if value
                ),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column != 1:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, column, item)
        self._loading = False
        self.status.setText(
            f"{revision['kind']} · {len(segments)}문장 · "
            + ("계획 범위 처리 완료" if revision.get("complete") else "부분 결과 / 임시 전사")
            + " · 사용자 편집은 발화 검증을 의미하지 않습니다."
            if revision
            else "전사 결과가 없습니다. 로컬 모델을 설정한 뒤 전체 전사를 실행하세요."
        )
        self._filter(self.search.text())
        if revision and revision.get("coverage", {}).get("checkpoint", {}).get("diarization"):
            self.status.setText(
                self.status.text() + " · 선택 구간만 익명 화자 추정; 겹침·신원·정확성 미확인"
            )

    def _filter(self, text: str) -> None:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 1)
            self.table.setRowHidden(
                row,
                bool(text) and item is not None and text.casefold() not in item.text().casefold(),
            )

    def _version_changed(self, index: int) -> None:
        if not self._loading and index >= 0:
            self.show_transcript(self.store.transcript(self.versions.itemData(index)))

    def select_version(self) -> None:
        if self.session_id is None or self.revision is None:
            return
        active = self.store.active_transcript(self.session_id)
        expected = active["revision_id"] if active else None
        session_id, revision_id = self.session_id, self.revision["revision_id"]
        self.operation(
            lambda: self.store.select_transcript(session_id, revision_id, expected_active=expected),
            lambda value: self.load(session_id),
        )

    def _edited(self, item: QTableWidgetItem) -> None:
        if self._loading or item.column() != 1 or not self.revision or not self.session_id:
            return
        revision = self.revision
        session_id = self.session_id
        segment = revision["segments"][item.row()]
        edited_text = item.text()
        expected = self._expected_active
        self._edit_pending = True
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        def saved(value: str) -> None:
            self._edit_pending = False
            self._unsaved_edit = False
            self.table.setEditTriggers(self._edit_triggers)
            if self.session_id != session_id:
                return
            self.load(session_id)
            # Even a CAS-losing edit is a preserved candidate, visible to its
            # author rather than silently replaced by the newer active result.
            self.show_transcript(self.store.transcript(value))
            selected = self.store.active_transcript(session_id)
            if selected is None or selected["revision_id"] != value:
                self.status.setText("편집본을 후보로 보존했습니다. 비교 후 이 버전을 선택하세요.")

        def failed(code: str) -> None:
            self._edit_pending = False
            self._unsaved_edit = True
            self.table.setEditTriggers(self._edit_triggers)
            self.status.setText("편집 저장 실패 · 입력을 유지합니다. 권한·세션 상태를 확인하세요.")

        accepted = self.operation(
            lambda: self.store.edit_segment(
                session_id,
                revision["revision_id"],
                segment["segment_id"],
                edited_text,
                expected_active=expected,
            ),
            saved,
            failed=failed,
        )
        if accepted is False:
            failed("AI_BUSY")

    def _retry_edit(self) -> None:
        if not self.revision or not self._unsaved_edit or self._edit_pending:
            return
        for row, segment in enumerate(self.revision["segments"]):
            item = self.table.item(row, 1)
            if item is not None and item.text() != segment["text"]:
                self._edited(item)
                return

    def _seek(self, row: int, column: int) -> None:
        if self.revision is None or column != 0:
            return
        segment = self.revision["segments"][row]
        if segment["provenance"] != "audio" or segment.get("timing_quality") == "unverified":
            self.status.setText(
                "이 문장은 원본 발화 위치가 검증되지 않아 음성 근거로 재생하지 않습니다."
            )
            return
        self.seekRequested.emit(
            segment.get("track_id") or "mic", segment["start_ms"], self.revision["revision_id"]
        )

    def _show_summary(self, summary: dict[str, Any] | None) -> None:
        self._claim_refs.clear()
        if summary is None:
            self.claims.setPlainText(
                "요약 결과가 없습니다. 요약 제공업체와 전송 범위를 설정하세요."
            )
            return
        content = ["<p>AI 요약 · 사실성과 근거의 의미는 검토가 필요합니다.</p>"]
        if summary.get("stale"):
            content.append("<p><b>이전 전사의 요약입니다. 근거는 당시 버전에 연결됩니다.</b></p>")
        for index, claim in enumerate(summary["claims"]):
            refs = []
            for ref_index, segment_id in enumerate(claim["segment_ids"]):
                key = f"claim:{index}:{ref_index}"
                self._claim_refs[key] = (summary["transcript_revision_id"], segment_id)
                refs.append(f'<a href="{key}">근거 {ref_index + 1}</a>')
            content.append(
                f"<p>{html.escape(claim['text'])} <b>[{html.escape(claim['status'])}]</b> {' '.join(refs)}</p>"
            )
        self.claims.setHtml("".join(content))

    def _claim_clicked(self, key: str) -> None:
        reference = self._claim_refs.get(key)
        if reference is None:
            return
        revision = self.store.transcript(reference[0])
        self.show_transcript(revision)
        for row, segment in enumerate(revision["segments"]):
            if segment["segment_id"] == reference[1]:
                self.search.clear()
                self.table.selectRow(row)
                item = self.table.item(row, 0)
                if item is not None:
                    self.table.scrollToItem(item)
                self._seek(row, 0)
                break

    def export(self) -> None:
        if self.revision is None:
            return
        filename, chosen = QFileDialog.getSaveFileName(
            self,
            "고정 전사 버전 내보내기",
            "transcript.srt",
            "SRT (*.srt);;VTT (*.vtt);;Text (*.txt);;JSON (*.json)",
        )
        if not filename:
            return
        path = Path(filename)
        format = path.suffix.lower().lstrip(".")
        revision_id = self.revision["revision_id"]

        def write() -> None:
            data = self.store.export_transcript(revision_id, format)
            with path.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(data)

        self.operation(write, lambda value: self.status.setText("전사 내보내기를 완료했습니다."))
