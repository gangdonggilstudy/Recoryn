"""Transcript revisions, audited editing and source-linked summary navigation.

G-P12: claims are shown in two areas (transcript-referenced / needs review), both
explicitly unverified; evidence links are pinned to the original revision and work from
the keyboard; summary candidates can be browsed and explicitly selected with a snapshot
compare-and-set. Nothing here marks a claim supported or confirms a decision or task.
"""

from __future__ import annotations

import html
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
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
from recoryn.content import ContentStore, SummarySelectionExpectation
from recoryn.content.store import summary_is_current
from recoryn.domain import StateConflict, ValidationError
from recoryn.ui import a11y

TRANSCRIPT_AREA, REVIEW_AREA = "transcript_reference", "review"
_AREA_STATUSES = ("uncertain", "unreviewed")
_BASIS_LABEL = {
    "transcript": "전사 참조",
    "user_assertion": "사용자 입력",
    "unresolved": "미해결 참조",
    "model_inference": "모델 추론(참조 없음)",
    None: "기록 없음",
}
_KIND_TITLE = {
    "decisions": "결정 제안 — 미확정",
    "tasks": "할 일 제안 — 미확정",
}


def timestamp(milliseconds: int) -> str:
    seconds, millis = divmod(milliseconds, 1000)
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes // 60:02}:{minutes % 60:02}:{seconds:02}.{millis:03}"


def claim_kind(template: object) -> str:
    """decisions / tasks / other, from the stored template only (never guessed)."""
    return template if template in ("decisions", "tasks") else "other"


def claim_area(status: object, basis: object, provider_basis: object, problem: object) -> str:
    """G12 section 4.1: only an unverified-status claim whose stored and adapter bases are
    transcript (or no adapter value) and whose evidence reads back cleanly goes to the
    transcript-referenced area; everything else needs review. Neither area is support."""
    if (
        problem is None
        and basis == "transcript"
        and status in _AREA_STATUSES
        and provider_basis in (None, "transcript")
    ):
        return TRANSCRIPT_AREA
    return REVIEW_AREA


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
        # Evidence link key -> (session, summary rev, transcript rev, segment, generation,
        # render). Only verifiable evidence ever gets a key (FIX1 G12R-01).
        self._claim_refs: dict[str, tuple[str, str, str, str, int, int]] = {}
        self.view_generation = 0
        self._render_serial = 0  # every actual re-render gets new link identities (G12R-08)
        self._rendered_summary: tuple[Any, ...] | None = None
        self._shown_summary: str | None = None
        self._seen_active: tuple[str, Any, Any] | None = None  # (session, summary id, version)
        self._active_moved = False
        self._expected_active: str | None = None
        self._edit_pending = False
        self._unsaved_edit = False
        self._browsed_summary: str | None = None
        self._candidate_snapshot: SummarySelectionExpectation | None = None
        self._confirming = False
        self.announcer = a11y.Announcer()
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
            if text == "AI 작업 취소":
                self.cancel_button = button
                a11y.name(
                    button,
                    "AI 대기·작업 취소 요청",
                    "선택 세션의 준비 중·대기·실행 AI 작업에 취소를 요청합니다. 한도 증액·모드 "
                    "변경·재전송은 하지 않으며 원격 결과는 별도로 표시됩니다.",
                )
            button.clicked.connect(signal.emit)
            a11y.activate_button(button)
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
            a11y.activate_button(button)
            blocked_actions.addWidget(button)
        layout.addLayout(blocked_actions)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["시작", "전사문 (편집 시 새 버전)", "근거", "트랙 / 화자"]
        )
        self.table.setAccessibleName(
            "시간순 전사문; 시간 셀에서 Enter·Space 또는 두 번 누르기로 원본 재생"
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(1, 480)
        self.table.itemChanged.connect(self._edited)
        self.table.cellDoubleClicked.connect(self._seek)
        a11y.KeyActivation(self.table, self._seek_current, when=self._table_key_is_seek)
        self._edit_triggers = self.table.editTriggers()
        layout.addWidget(self.table, 3)
        retry_edit = QPushButton("보존된 편집 입력 저장 재시도")
        retry_edit.clicked.connect(self._retry_edit)
        layout.addWidget(retry_edit)
        summary_actions = QHBoxLayout()
        self.templates = QComboBox()
        self.templates.setAccessibleName("요약 형식")
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
        candidates = QHBoxLayout()
        self.summary_candidates = QComboBox()
        a11y.name(
            self.summary_candidates,
            "요약 후보 열람",
            "목록에서 고르는 것은 열람만 합니다. 선택은 '이 요약 선택'과 확인 뒤에만 합니다.",
        )
        self.summary_candidates.currentIndexChanged.connect(self._candidate_changed)
        candidates.addWidget(self.summary_candidates, 1)
        self.select_summary_button = QPushButton("이 요약 선택")
        a11y.name(
            self.select_summary_button,
            "열람 중인 요약 후보를 선택",
            "항상 확인을 묻습니다. 부분 결과는 선택할 수 없습니다.",
        )
        self.select_summary_button.setEnabled(False)
        self.select_summary_button.clicked.connect(self.select_candidate)
        a11y.activate_button(self.select_summary_button)  # Enter and Space (G12R-07)
        candidates.addWidget(self.select_summary_button)
        layout.addLayout(candidates)
        self.candidate_info = QLabel("")
        self.candidate_info.setWordWrap(True)
        layout.addWidget(self.candidate_info)
        self.claims_title = QLabel("전사 참조 요약 — 의미 지지 미검증 · 0건")
        layout.addWidget(self.claims_title)
        self.claims = self._browser(
            "전사 참조 요약; 원문을 참조하지만 의미가 지지된다는 뜻은 아닙니다"
        )
        layout.addWidget(self.claims, 2)
        self.review_title = QLabel("추가 검토 필요 — 확정된 사실/결정/할 일이 아닙니다 · 0건")
        layout.addWidget(self.review_title)
        self.review_claims = self._browser(
            "추가 검토가 필요한 AI 요약 항목; 확정된 사실·결정·할 일이 아닙니다"
        )
        layout.addWidget(self.review_claims, 2)
        diarization = QHBoxLayout()
        self.diarization_ranges = QComboBox()
        self.diarization_ranges.setAccessibleName("익명 화자 추정을 적용할 고정 원본 구간")
        diarization.addWidget(self.diarization_ranges, 1)
        speakers = QPushButton("선택 구간 익명 화자 추정 (CPU)")
        speakers.clicked.connect(self.diarizeRequested.emit)
        diarization.addWidget(speakers)
        layout.addLayout(diarization)

    def _browser(self, accessible_name: str) -> QTextBrowser:
        browser = QTextBrowser()
        a11y.name(
            browser,
            accessible_name,
            "Tab·Shift+Tab으로 근거 링크를 오가고, Enter 또는 링크에서 Space로 원 전사의 "
            "해당 문장을 엽니다. 재생은 검증된 음성 근거만 하며 의미 지지를 뜻하지 않습니다.",
        )
        browser.setOpenExternalLinks(False)
        browser.setOpenLinks(False)
        browser.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction
            | Qt.TextInteractionFlag.LinksAccessibleByKeyboard
        )
        browser.anchorClicked.connect(lambda url: self._claim_clicked(url.toString()))

        def focused_link(event: QKeyEvent, view: QTextBrowser = browser) -> bool:
            # Enter/Space activate only a link that has keyboard focus; otherwise native.
            return bool(a11y.focused_anchor(view))

        def activate(view: QTextBrowser = browser) -> None:
            self._claim_clicked(a11y.focused_anchor(view))

        a11y.KeyActivation(browser, activate, when=focused_link)
        return browser

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
            # Keep the revision and CAS expectation captured before editing; only a
            # new active summary is announced (G12 section 4.1).
            self._note_active(kept=True)
            return
        if not same_session:
            self.view_generation += 1
            self._browsed_summary = None
            self._rendered_summary = None
            self.announcer.advance("content")
        viewed = self.revision if same_session else None
        following_active = viewed is None or viewed["revision_id"] == self._expected_active
        self.session_id = session_id
        active = self.store.active_transcript(session_id)
        self._expected_active = active["revision_id"] if active else None
        displayed = active if following_active else viewed
        listed = self.store.list_revisions(session_id)  # one listing per load
        revisions = [
            item for item in listed if item.get("revision_type", "transcript") != "summary"
        ]
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
        self._refresh_candidates(
            [item for item in listed if item.get("revision_type") == "summary"]
        )

    # --- summary candidates (browse != select) -------------------------------------
    def _refresh_candidates(self, candidates: list[dict[str, Any]] | None = None) -> None:
        session_id = self.session_id
        if session_id is None:
            return
        if not callable(getattr(self.store, "selection_state", None)):
            # A store without the candidate API (a minimal double): show the active one.
            self._show_summary(self.store.active_summary(session_id))
            return
        if self._confirming:
            self._note_active(kept=True)
            return  # a confirmation is open: keep what the user is deciding on
        state = self.store.selection_state(session_id)
        if candidates is None:
            candidates = self.store.list_revisions(session_id, "summary")
        identifiers = {item["revision_id"] for item in candidates}
        if self._browsed_summary not in identifiers:
            self._browsed_summary = None
        if (
            self._browsed_summary is None
            and self._shown_summary in identifiers
            and self._shown_summary != state["summary_id"]
            and self._focus_in_summary()
        ):
            # A keyboard/screen-reader user is reading this summary: keep it on screen
            # (and its focused link) and only announce the new active one (G12R-03).
            self._browsed_summary = self._shown_summary
        snapshot = self._candidate_snapshot
        if self._browsed_summary is None or snapshot is None or snapshot.session_id != session_id:
            snapshot = SummarySelectionExpectation.from_state(state)
        # While browsing, the snapshot presented when browsing began is kept; a change is
        # shown, announced and settled by the selection's own CAS (G12R-04).
        self._candidate_snapshot = snapshot
        self._active_moved = (state["summary_id"], state["summary_version"]) != (
            snapshot.summary_id,
            snapshot.summary_version,
        )
        self._note_active(kept=self._browsed_summary is not None, state=state)
        wanted = self._browsed_summary or state["summary_id"]
        items = [(self._candidate_label(item), item["revision_id"]) for item in candidates]
        present = [
            (self.summary_candidates.itemText(index), self.summary_candidates.itemData(index))
            for index in range(self.summary_candidates.count())
        ]
        shown = next((index for index, (_, ident) in enumerate(items) if ident == wanted), -1)
        self._loading = True
        if items != present:
            self.summary_candidates.clear()
            for label, identifier in items:
                self.summary_candidates.addItem(label, identifier)
        if self.summary_candidates.currentIndex() != shown:
            self.summary_candidates.setCurrentIndex(shown)
        self._loading = False
        browsed = next(
            (
                item
                for item in candidates
                if item["revision_id"] == (self._browsed_summary or state["summary_id"])
            ),
            None,
        )
        self._show_candidate(browsed)

    def _focus_in_summary(self) -> bool:
        focused = a11y.FocusReturn(None, window=self.window()).focused()
        views = (self.claims, self.review_claims, self.summary_candidates)
        return focused is not None and any(
            focused is view or view.isAncestorOf(focused) for view in views
        )

    def _note_active(self, *, kept: bool, state: dict[str, Any] | None = None) -> None:
        """Announce a newly active summary once (polite); focus never moves."""
        session_id = self.session_id
        if session_id is None or not callable(getattr(self.store, "selection_state", None)):
            return
        if state is None:
            try:
                state = self.store.selection_state(session_id)
            except (KeyError, StateConflict, ValidationError):
                return
        current = (session_id, state["summary_id"], state["summary_version"])
        previous, self._seen_active = self._seen_active, current
        if previous is None or previous[0] != session_id or previous[1] == current[1]:
            return
        if current[1] is None:
            return
        self.announcer.announce(
            "content",
            self.candidate_info,
            "NEW_ACTIVE_SUMMARY",
            "새 요약이 선택되었습니다"
            + (" · 지금 보던 요약을 그대로 표시합니다" if kept else " · 새 요약을 표시합니다"),
            version=current,
        )

    def _candidate_label(self, item: dict[str, Any]) -> str:
        parts = ["선택됨" if item.get("selected") else "후보"]
        if not item.get("complete"):
            parts.append("부분")
        snapshot = self._candidate_snapshot
        if snapshot is not None and not summary_is_current(item, snapshot):
            if item.get("transcript_revision_id") != snapshot.transcript_id:
                parts.append("이전 전사")
            elif item.get("settings_key") is None or snapshot.summary_settings_key is None:
                parts.append("설정 비교 불명")
            else:
                parts.append("이전 설정")
        parts.append(f"원 전사 {str(item.get('transcript_revision_id'))[:10]}")
        parts.append(str(item["revision_id"])[:10])
        return " · ".join(parts)

    def _candidate_changed(self, index: int) -> None:
        if self._loading or index < 0 or self.session_id is None:
            return
        self._browsed_summary = self.summary_candidates.itemData(index)
        if self._active_moved:
            # The user moved on to another candidate: present the current selection.
            self._candidate_snapshot = SummarySelectionExpectation.from_state(
                self.store.selection_state(self.session_id)
            )
            self._active_moved = False
        try:
            summary = self.store.summary(self._browsed_summary)
        except (KeyError, StateConflict, ValidationError):
            self._show_candidate(None)
            return
        self._show_candidate(summary)

    def _show_candidate(self, summary: dict[str, Any] | None) -> None:
        snapshot = self._candidate_snapshot
        selectable = (
            summary is not None
            and bool(summary.get("complete"))
            and snapshot is not None
            and summary["revision_id"] != snapshot.summary_id
        )
        self.select_summary_button.setEnabled(selectable)
        if summary is None:
            self.candidate_info.setText(
                "선택된 요약이 없습니다."
                if self.summary_candidates.count()
                else "요약 후보가 없습니다."
            )
        elif not summary.get("complete"):
            self.candidate_info.setText(
                "부분 결과 — 열람·근거 확인만 할 수 있고 전체 요약으로 선택할 수 없습니다."
            )
        elif snapshot is not None and summary["revision_id"] == snapshot.summary_id:
            self.candidate_info.setText(
                "선택된 요약입니다."
                + ("" if summary_is_current(summary, snapshot) else " 이전 전사·설정 기준입니다.")
            )
        elif snapshot is not None and not summary_is_current(summary, snapshot):
            self.candidate_info.setText(
                "이전 전사/설정 또는 비교할 수 없는 후보입니다 — 선택하려면 확인이 필요합니다."
            )
        else:
            self.candidate_info.setText("현재 전사·요청 설정의 후보입니다.")
        if self._active_moved and self._browsed_summary is not None:
            self.candidate_info.setText(
                self.candidate_info.text()
                + " · 열람을 시작한 뒤 선택 요약이 바뀌었습니다. 선택하면 다시 확인합니다."
            )
        self._show_summary(summary)

    def select_candidate(self) -> None:
        """Explicitly select the browsed candidate; always confirms, default No."""
        session_id, target, snapshot = (
            self.session_id,
            self._browsed_summary,
            self._candidate_snapshot,
        )
        if session_id is None or target is None or snapshot is None or self._confirming:
            return
        try:
            summary = self.store.summary(target)
        except (KeyError, StateConflict, ValidationError):
            return
        if not summary.get("complete"):
            return
        outdated = not summary_is_current(summary, snapshot)
        text = (
            "열람 중인 요약을 이 세션의 선택 요약으로 바꿉니다. 전사 선택·요청 설정·이전 작업 "
            "결과는 바뀌지 않습니다."
            + (
                "\n이 후보는 이전 전사·설정의 결과이거나 현재와 비교할 수 없습니다."
                if outdated
                else ""
            )
            + "\n선택하시겠습니까?"
        )
        generation = self.view_generation
        self._confirming = True
        try:
            accepted, focus = a11y.confirm(
                self,
                "요약 선택 확인",
                text,
                still_current=lambda: (
                    self.session_id == session_id and self.view_generation == generation
                ),
                restore=False,
            )
        finally:
            self._confirming = False
        if not accepted or not focus.still_current():
            # A refusal, or a screen that changed while asking, returns focus now; a
            # confirmed current request returns it when its write completes.
            focus.restore(self.summary_candidates)
        if not accepted:
            return

        def done(selected: bool) -> None:
            if self.session_id != session_id or self.view_generation != generation:
                return  # an old session's callback changes nothing on the new screen
            if not selected:
                self.candidate_info.setText(
                    "선택 충돌 — 다른 선택·전사·설정 변경이 있었습니다. 다시 조회한 뒤 선택하세요."
                )
                self.announcer.announce(
                    "content",
                    self.candidate_info,
                    "SELECTION_CONFLICT",
                    "요약 선택 충돌 · 다시 조회 후 선택",
                    version=("conflict", target, snapshot),
                )
            self._browsed_summary = None
            self._refresh_candidates()
            focus.restore(self.summary_candidates)

        def failed(code: str) -> None:
            if self.session_id == session_id and self.view_generation == generation:
                self.candidate_info.setText("요약을 선택하지 못했습니다 · 기존 선택을 유지합니다.")
                focus.restore(self.summary_candidates)

        accepted_operation = self.operation(
            lambda: self.store.select_summary_candidate(
                session_id, target, expected=snapshot, allow_outdated=outdated
            ),
            done,
            failed=failed,
        )
        if accepted_operation is False:
            failed("AI_BUSY")

    # --- transcript ---------------------------------------------------------------
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

    def _editing(self) -> bool:
        return (
            self.table.state() == QAbstractItemView.State.EditingState
            or self._edit_pending
            or self._unsaved_edit
        )

    def _table_key_is_seek(self, event: QKeyEvent) -> bool:
        # Enter/Space seek only from a time cell, never inside an editor or IME.
        return not self._editing() and self.table.currentColumn() == 0

    def _seek_current(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= self.table.rowCount() or self.table.isRowHidden(row):
            return
        self._seek(row, 0)

    def _seek(self, row: int, column: int) -> None:
        if self.revision is None or column != 0:
            return
        if not 0 <= row < len(self.revision["segments"]) or self.table.isRowHidden(row):
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

    # --- summary display ------------------------------------------------------------
    _PROBLEM_TEXT = {
        "CONTENT_CLAIM_SOURCE_UNAVAILABLE": "원 전사를 읽을 수 없거나 요약 당시와 다릅니다",
        "CONTENT_CLAIM_BASIS_MISMATCH": "저장된 출처가 원 전사와 맞지 않습니다",
        "CONTENT_CLAIM_RECORD_INVALID": "저장된 항목의 형식·상태가 올바르지 않습니다",
    }

    def _show_summary(self, summary: dict[str, Any] | None) -> None:
        if summary is None:
            key: tuple[Any, ...] = (self.view_generation, None)
            if key == self._rendered_summary:
                return
            self._rendered_summary = key
            self._shown_summary = None
            self._render_serial += 1
            self._claim_refs.clear()
            self._set_area_titles(0, 0)
            self.claims.setPlainText(
                "요약 결과가 없습니다. 요약 제공업체와 전송 범위를 설정하세요."
            )
            self.review_claims.setPlainText("해당 없음")
            return
        # Revisions are immutable: within one view generation the same summary and
        # staleness render the same evidence, so an unchanged poll rebuilds nothing.
        key = (self.view_generation, summary["revision_id"], summary.get("stale"))
        if key == self._rendered_summary:
            return  # the same poll does not rebuild the HTML or its links (focus stays)
        self._rendered_summary = key
        self._shown_summary = summary["revision_id"]
        self._render_serial += 1
        self._claim_refs.clear()
        try:
            views = self.store.claim_evidence(summary["revision_id"])
        except (KeyError, StateConflict, ValidationError, AttributeError, TypeError):
            views = None
        kind = claim_kind(summary.get("template"))
        title = _KIND_TITLE.get(kind, "AI 요약 — 미확정")
        header = [f"<p><b>{html.escape(title)}</b> · 사실성과 근거의 의미는 검토가 필요합니다.</p>"]
        if summary.get("stale"):
            header.append("<p><b>이전 전사의 요약입니다. 근거는 당시 버전에 연결됩니다.</b></p>")
        if not summary.get("complete"):
            header.append("<p><b>부분 결과입니다. 처리되지 않은 범위가 있습니다.</b></p>")
        areas: dict[str, list[str]] = {TRANSCRIPT_AREA: [], REVIEW_AREA: []}
        if views is None:
            areas[REVIEW_AREA].append(
                "<p>근거 확인 불가 — 요약 또는 원 전사를 읽을 수 없습니다. 재생하지 않습니다.</p>"
            )
        else:
            for view in views:
                area = claim_area(
                    view["status"], view["basis"], view["provider_basis"], view["problem"]
                )
                areas[area].append(self._claim_html(summary, view, area))
        counts = {name: len(items) for name, items in areas.items()}
        self._set_area_titles(counts[TRANSCRIPT_AREA], counts[REVIEW_AREA])
        empty = "<p>0건 — 해당 없음. 주장이 없다는 것은 지지·검증 결과가 아닙니다.</p>"
        self.claims.setHtml("".join(header + (areas[TRANSCRIPT_AREA] or [empty])))
        self.review_claims.setHtml("".join(header + (areas[REVIEW_AREA] or [empty])))

    def _set_area_titles(self, referenced: int, review: int) -> None:
        self.claims_title.setText(f"전사 참조 요약 — 의미 지지 미검증 · {referenced}건")
        self.review_title.setText(
            f"추가 검토 필요 — 확정된 사실/결정/할 일이 아닙니다 · {review}건"
        )
        # The counts are part of what a screen reader hears on entering an area.
        self.claims.setAccessibleName(
            f"전사 참조 요약 {referenced}건; 원문을 참조하지만 의미가 지지된다는 뜻은 아닙니다"
        )
        self.review_claims.setAccessibleName(
            f"추가 검토 필요 {review}건; 확정된 사실·결정·할 일이 아닙니다"
        )

    def _claim_html(self, summary: dict[str, Any], view: dict[str, Any], area: str) -> str:
        assert self.session_id is not None
        text = html.escape(str(view["text"]))
        problem = view["problem"]
        if problem is not None:
            # Evidence that cannot be verified is never offered as evidence: no link, no
            # source row, no playback; only the fact and its reason (G12R-01, G12R-05).
            reason = self._PROBLEM_TEXT.get(problem, "근거를 확인할 수 없습니다")
            return f"<p>{text} <b>[근거 확인 불가 · {html.escape(reason)} · 재생·원문 이동 없음]</b></p>"
        refs = []
        for ref_index, ref in enumerate(view["refs"]):
            key = f"claim:{view['index']}:{ref_index}@{self.view_generation}.{self._render_serial}"
            self._claim_refs[key] = (
                self.session_id,
                summary["revision_id"],
                summary["transcript_revision_id"],
                ref["segment_id"],
                self.view_generation,
                self._render_serial,
            )
            playable = (
                ref["found"]
                and ref["provenance"] == "audio"
                and ref["timing_quality"] != "unverified"
            )
            where = (
                f"{timestamp(ref['start_ms'])} {ref.get('track_id') or ''}".strip()
                if ref["start_ms"] is not None
                else "위치 없음"
            )
            label = (
                f"근거 {ref_index + 1}: 원 전사 {summary['transcript_revision_id'][:10]} · "
                f"{where} · {'재생 가능' if playable else '원문 보기만'}"
            )
            refs.append(f'<a href="{html.escape(key)}">{html.escape(label)}</a>')
        provider = view["provider_basis"]
        source = (
            _BASIS_LABEL.get(view["basis"], "확인 불가")
            if view["basis_recorded"]
            else "기록 없음 · 원 전사에서 계산: "
            + _BASIS_LABEL.get(view["computed_basis"], "확인 불가")
        )
        facts = (
            f"상태 {view['status']} · 출처 {source}"
            + f" · 어댑터 {_BASIS_LABEL.get(provider, '확인 불가') if provider else '미기록'}"
        )
        reason = ""
        if area == REVIEW_AREA:
            reason = " · 원인: 출처·상태·어댑터 근거가 전사 참조 요건이 아님"
        return (
            f"<p>{text} <b>[{html.escape(facts + reason)}]</b> "
            f"{' '.join(refs) if refs else '(참조 없음)'}</p>"
        )

    def _claim_clicked(self, key: str) -> None:
        if "@" not in key:
            # A direct caller's generation-less key means the current render only.
            key = f"{key}@{self.view_generation}.{self._render_serial}"
        reference = self._claim_refs.get(key)
        if reference is None:
            return  # an unknown, external, stale or unverifiable link does nothing
        session_id, _, transcript_id, segment_id, generation, serial = reference
        if (
            session_id != self.session_id
            or generation != self.view_generation
            or serial != self._render_serial
        ):
            return
        if self._editing():
            self.status.setText("편집 중인 입력이 있습니다 · 편집을 저장한 뒤 근거로 이동하세요.")
            return
        try:
            revision = self.store.transcript(transcript_id)
        except (KeyError, StateConflict, ValidationError):
            self.status.setText("근거 확인 불가 · 원 전사를 읽을 수 없어 재생하지 않습니다.")
            return
        self.show_transcript(revision)
        for row, segment in enumerate(revision["segments"]):
            if segment["segment_id"] == segment_id:
                self.search.clear()
                self.table.selectRow(row)
                item = self.table.item(row, 0)
                if item is not None:
                    self.table.scrollToItem(item)
                    self.table.setCurrentCell(row, 0)
                if segment["provenance"] != "audio":
                    self.status.setText(
                        "사용자 입력·미해결 근거입니다 · 발화 위치 미확인, 원문만 표시합니다."
                    )
                    return
                self._seek(row, 0)
                self.table.setFocus(Qt.FocusReason.OtherFocusReason)
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
