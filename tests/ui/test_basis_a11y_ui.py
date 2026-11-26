"""G12 / G-P12 K, E, F, N, C, R, Z and UI T rows: keys, focus, modals and announcements.

Real Qt widgets under the offscreen platform: key press/release pairs through QTest,
real QMessageBox dialogs answered from the keyboard (Tab+Space = Yes, Enter = the
default No, Escape), window-level focus, and the announcement adapter with a
recording sink. Stores are real SQLite; the player, transport and background
operation seams are fakes that only record calls. Every expected value is written by
hand from G12 sections 4-5 and the approved amendment. Real Narrator speech is an
external gate and is not claimed here.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from itertools import count, product
from pathlib import Path
from types import SimpleNamespace
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
import shiboken6
from PySide6.QtCore import Qt, QThread, QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from recoryn.app.status import AIStatus
from recoryn.content import Claim, ContentStore, Segment
from recoryn.domain import ValidationError
from recoryn.jobs import JobStore
from recoryn.security import ConsentStore, CostLedger, CredentialVault
from recoryn.storage import Library
from recoryn.ui import a11y
from recoryn.ui.ai_bridge import (
    DesktopAI,
    announcement_text,
    announcement_version,
    job_announcement,
)
from recoryn.ui.content import ContentPanel
from recoryn.ui.privacy import PrivacyPanel
from tests.ui.test_cost_cap_ui import fixture_panel_catalog
from tests.ui.test_privacy_ui import DummyVault

pytestmark = pytest.mark.ui
_serial = count(1)
KEYS = {
    "Tab": Qt.Key.Key_Tab,
    "Enter": Qt.Key.Key_Return,
    "Space": Qt.Key.Key_Space,
    "Arrow": Qt.Key.Key_Down,
}
FORBIDDEN = ("검증률", "100%", "지지됨", "검증됨", "확정됨", "supported")


# --- seams -------------------------------------------------------------------------
class Ops:
    """The panel's background-operation seam: run now, hold for later, or fail."""

    def __init__(self, mode: str = "now") -> None:
        self.mode, self.held, self.calls = mode, [], 0

    def __call__(
        self, fn: Callable[[], Any], done: Callable[[Any], None], failed: Any = None
    ) -> bool:
        self.calls += 1
        if self.mode == "fail":
            if failed is not None:
                failed("G12_FAULT")
            return True
        if self.mode == "hold":
            self.held.append((fn, done, failed))
            return True
        self._run(fn, done, failed)
        return True

    @staticmethod
    def _run(fn: Callable[[], Any], done: Callable[[Any], None], failed: Any) -> None:
        try:
            value = fn()
        except Exception as error:  # the panel's failure callback, as the bridge does
            if failed is None:
                raise
            failed(type(error).__name__)
        else:
            done(value)

    def flush(self) -> None:
        while self.held:
            self._run(*self.held.pop(0))


class Window(QWidget):
    """A top-level window that, like MainWindow, reports the selected session."""

    def __init__(self) -> None:
        super().__init__()
        self.session: str | None = "s1"

    def selected_session(self) -> str | None:
        return self.session


class Modals:
    """Answers real QMessageBox.question dialogs from the keyboard.

    ``answer`` is Yes (Tab to Yes, then Space), No (Enter on the default) or Esc.
    ``during`` runs while the dialog is open (a race, an opener change). The dialog is
    always closed even if a check fails, so a failure never hangs the run.
    """

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.real = QMessageBox.question
        self.answer, self.during = "No", None
        self.opened: list[tuple[Any, ...]] = []
        self.defaults: list[tuple[bool, bool]] = []
        self.errors: list[BaseException] = []
        monkeypatch.setattr(QMessageBox, "question", self.question)

    def reset(self, answer: str = "No", during: Callable[[], None] | None = None) -> None:
        self.answer, self.during = answer, during
        self.opened.clear()
        self.defaults.clear()
        self.errors.clear()

    def question(self, *args: Any) -> Any:
        self.opened.append(args)
        QTimer.singleShot(0, self._respond)
        return self.real(*args)

    def _respond(self) -> None:
        box = QApplication.activeModalWidget()
        if not isinstance(box, QMessageBox):
            self.errors.append(AssertionError("no modal question is open"))
            return
        no = box.button(QMessageBox.StandardButton.No)
        yes = box.button(QMessageBox.StandardButton.Yes)
        try:
            self.defaults.append((box.defaultButton() is no, box.focusWidget() is no))
            if self.during is not None:
                self.during()
            if self.answer == "Yes":
                QTest.keyClick(box.focusWidget(), Qt.Key.Key_Tab)
                assert box.focusWidget() is yes, "Tab did not reach Yes"
                QTest.keyClick(yes, Qt.Key.Key_Space)
            elif self.answer == "No":
                QTest.keyClick(box.focusWidget(), Qt.Key.Key_Return)
            else:
                QTest.keyClick(box.focusWidget(), Qt.Key.Key_Escape)
        except BaseException as error:  # noqa: BLE001 - re-raised by check()
            self.errors.append(error)
        finally:
            if shiboken6.isValid(box) and box.isVisible():
                box.reject()

    def check(self) -> None:
        if self.errors:
            raise self.errors[0]


class Sink:
    """Records announcements (target, message, politeness) and forwards to Qt."""

    def __init__(self) -> None:
        self.events: list[tuple[Any, str, str]] = []
        self.threads: list[Any] = []

    def __call__(self, target: Any, message: str, politeness: str) -> None:
        self.events.append((target, message, politeness))
        self.threads.append(QThread.currentThread())
        a11y.qt_announce(target, message, politeness)


def press(widget: Any, key: str) -> None:
    QTest.keyClick(widget, KEYS[key])


def anchors(browser: QTextBrowser) -> list[tuple[str, int, int, str]]:
    """(href, start, end, block text) for each link, read from the rendered document."""
    document, found = browser.document(), []
    cursor = QTextCursor(document)
    block = document.begin()
    while block.isValid():
        text, base, current, start = block.text(), block.position(), "", 0
        for offset in range(len(text) + 1):
            href = ""
            if offset < len(text):
                cursor.setPosition(base + offset + 1)
                href = cursor.charFormat().anchorHref()
            if href != current:
                if current:
                    found.append((current, base + start, base + offset, text))
                current, start = href, offset
        block = block.next()
    return found


def focus_link(browser: QTextBrowser, href: str) -> None:
    """Select exactly the anchor, as keyboard Tab focus does (cursor at its end)."""
    for found, start, end, _ in anchors(browser):
        if found == href:
            cursor = QTextCursor(browser.document())
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            browser.setTextCursor(cursor)
            return
    raise AssertionError(f"link {href!r} is not rendered")


def link_for(panel: ContentPanel, marker: str, ref: int = 0) -> tuple[QTextBrowser, str]:
    for browser in (panel.claims, panel.review_claims):
        links = [item for item in anchors(browser) if marker in item[3]]
        if links:
            return browser, links[ref][0]
    raise AssertionError(f"no link for {marker}")


def all_text(panel: ContentPanel) -> str:
    return "\n".join(
        [
            panel.claims_title.text(),
            panel.claims.toPlainText(),
            panel.review_title.text(),
            panel.review_claims.toPlainText(),
            panel.candidate_info.text(),
            panel.status.text(),
        ]
    )


# --- environment -----------------------------------------------------------------
@pytest.fixture(scope="module")
def app() -> QApplication:
    existing = QApplication.instance()
    return existing if isinstance(existing, QApplication) else QApplication([])


@pytest.fixture(scope="module")
def env(app: QApplication, tmp_path_factory: pytest.TempPathFactory) -> Iterator[SimpleNamespace]:
    root_dir = tmp_path_factory.mktemp("g12-ui")
    with (
        Library(root_dir / "library") as library,
        ContentStore(library) as content,
        ContentStore(library) as peer,
        JobStore(library.db_path) as jobs,
        ConsentStore(root_dir / "privacy.sqlite") as consents,
        CostLedger(root_dir / "privacy.sqlite") as ledger,
        pytest.MonkeyPatch.context() as patches,
    ):
        env = SimpleNamespace(
            app=app,
            library=library,
            content=content,
            peer=peer,
            jobs=jobs,
            consents=consents,
            ledger=ledger,
        )
        env.modals = Modals(patches)
        env.grants, env.revokes, env.resets, env.adoptions = [], [], [], []
        real_grant, real_revoke = consents.grant, consents.revoke
        patches.setattr(
            consents, "grant", lambda *a, **k: (env.grants.append(a), real_grant(*a, **k))[1]
        )
        patches.setattr(
            consents, "revoke", lambda *a, **k: (env.revokes.append(a), real_revoke(*a, **k))[1]
        )
        patches.setattr(ledger, "reset_clock", lambda **k: env.resets.append(k))
        patches.setattr(ledger, "adopt_legacy", lambda *a, **k: env.adoptions.append(a))
        env.root = Window()
        layout = QVBoxLayout(env.root)
        env.privacy = PrivacyPanel(
            consents, ledger, CredentialVault(backend=DummyVault(), namespace="g12-ui")
        )
        env.privacy._g06_prices = lambda: fixture_panel_catalog(env.privacy, patches)
        env.ops = Ops()
        env.panel = ContentPanel(content, env.ops)
        env.opener, env.other = QPushButton("opener"), QPushButton("other")
        for widget in (env.privacy, env.panel, env.opener, env.other):
            layout.addWidget(widget)
        env.root.show()
        configure_privacy(env)
        build_k_world(env)
        env.bridge = DesktopAI.__new__(DesktopAI)
        env.bridge.window, env.bridge.panel, env.bridge.busy = env.root, env.panel, False
        env.retries = []
        env.bridge.summarize = lambda template, **kwargs: env.retries.append((template, kwargs))
        try:
            yield env
        finally:
            env.root.close()
            env.privacy.close()
            app.processEvents()


def configure_privacy(env: SimpleNamespace) -> None:
    privacy = env.privacy
    privacy.select_session("session")
    control = privacy.controls["stt"]
    control.scope.setCurrentIndex(control.scope.findData("library"))
    control.provider.setCurrentIndex(control.provider.findData("openai"))
    control.endpoint.setText("https://api.example.test/stt")
    control.model.setText("user-selected-test-model")
    control.total.setValue(1)
    control.per_request.setValue(0.1)
    privacy._g06_prices()
    privacy._action("stt", "budget")
    privacy._show_scope("stt")


def reset_privacy(env: SimpleNamespace) -> None:
    privacy, control = env.privacy, env.privacy.controls["stt"]
    privacy.select_session("session")
    previous = control.scope.blockSignals(True)
    control.scope.setCurrentIndex(control.scope.findData("library"))
    control.scope.blockSignals(previous)
    previous = control.cost_mode.blockSignals(True)
    control.cost_mode.setCurrentIndex(control.cost_mode.findData("strict"))
    control.cost_mode.blockSignals(previous)
    control.general_acknowledged = False
    for button in (control.allow, control.revoke):
        button.show()
    privacy._show_scope("stt")


K_SEGMENTS = (
    Segment("a", 1000, 1500, "spoken words", track_id="mic", timing_quality="clip"),
    Segment("u", 2000, 2500, "typed note", provenance="user_assertion"),
    Segment("x", 3000, 3500, "drift words", track_id="sys", timing_quality="unverified"),
    Segment("b", 4000, 4500, "second spoken", track_id="sys", timing_quality="clip"),
)


def build_k_world(env: SimpleNamespace) -> None:
    """Session k: the summary cites the original T0; the active transcript is an edit T1."""
    content = env.content
    env.library.create_session("k")
    env.library.create_session("k-empty")
    env.t0 = content.create_transcript("k", list(K_SEGMENTS))
    env.s = content.create_summary(
        "k",
        env.t0,
        [
            Claim("AUDIO-CLAIM 논의했다", ("a",)),
            Claim("USER-CLAIM 입력했다", ("u",)),
            Claim("DRIFT-CLAIM 들렸다", ("x",)),
            Claim("MIXED-CLAIM 섞였다", ("u", "b")),
        ],
        expected_transcript=env.t0,
    )
    env.t1 = content.edit_segment("k", env.t0, "u", "typed note edited", expected_active=env.t0)


def k_panel(
    env: SimpleNamespace, session: str = "k", ops: Ops | None = None
) -> tuple[ContentPanel, list]:
    panel = ContentPanel(env.content, ops or Ops())
    seeks: list[tuple[str, int, str]] = []
    panel.seekRequested.connect(lambda *args: seeks.append(args))
    panel.show()
    panel.load(session)
    return panel, seeks


def dispose(panel: QWidget) -> None:
    if shiboken6.isValid(panel):
        panel.close()
        shiboken6.delete(panel)


# --- K: key x widget x target state x source target --------------------------------
K_KEYS = tuple(KEYS)
K_WIDGETS = (
    "time_table",
    "claim_link",
    "refuse",
    "revoke",
    "wait_cancel",
    "continue",
    "settings_nav",
)
K_STATES = ("enabled", "disabled", "hidden", "destroyed")
K_SOURCES = ("verified_audio", "user_text", "invalid_target")
K = list(product(K_KEYS, K_WIDGETS, K_STATES, K_SOURCES))
K_IDS = [f"G12-K-{n:03}" for n in range(1, 337)]
K_ROW = {"verified_audio": 0, "user_text": 1, "invalid_target": 2}
K_MARKER = {
    "verified_audio": "AUDIO-CLAIM",
    "user_text": "USER-CLAIM",
    "invalid_target": "DRIFT-CLAIM",
}


def k_oracle(row: tuple[str, str, str, str]) -> dict[str, Any]:
    key, widget, state, source = row
    runs = key in ("Enter", "Space") and state == "enabled"
    if widget in ("time_table", "claim_link"):
        return {
            "seek": 1 if runs and source == "verified_audio" else 0,
            "original_shown": widget == "claim_link" and runs,
            "located": widget == "claim_link" and runs and source != "verified_audio",
        }
    return {"command": 1 if runs else 0}


@pytest.mark.parametrize("row", K, ids=K_IDS)
def test_k_keys_activate_only_valid_targets_once(
    env: SimpleNamespace, row: tuple[str, str, str, str]
) -> None:
    key, widget, state, source = row
    want = k_oracle(row)
    if widget in ("time_table", "claim_link"):
        _k_navigation(env, row, want)
    elif widget in ("refuse", "revoke"):
        _k_privacy(env, row, want)
    else:
        _k_content_button(env, row, want)


def _k_navigation(
    env: SimpleNamespace, row: tuple[str, str, str, str], want: dict[str, Any]
) -> None:
    key, widget, state, source = row
    panel, seeks = k_panel(env)
    try:
        if widget == "time_table":
            target = panel.table
            panel.table.setCurrentCell(K_ROW[source], 0)
            if state == "disabled":
                panel.table.setEnabled(False)
            elif state == "hidden":
                panel.search.setText("second")  # hides the source row, keeps it current
                assert panel.table.isRowHidden(K_ROW[source])
            elif state == "destroyed":
                panel.load("k-empty")  # the old row no longer exists
            press(target, key)
        else:
            browser, href = link_for(panel, K_MARKER[source])
            focus_link(browser, href)
            if state == "disabled":
                browser.setEnabled(False)
            elif state == "hidden":
                browser.hide()
            elif state == "destroyed":
                panel.load("k-empty")
                panel.load("k")  # a new view generation re-renders every link
                panel._claim_clicked(href)  # a late signal from the old link
            press(browser, key)
        assert len(seeks) == want["seek"]
        if want["seek"]:
            # A link plays its summary's original T0; the table plays the shown T1.
            assert seeks == [("mic", 1000, env.t0 if widget == "claim_link" else env.t1)]
        shown = panel.revision["revision_id"] if panel.revision else None
        assert (shown == env.t0) is want["original_shown"]
        if want["located"]:
            assert "발화 위치" in panel.status.text() or "검증되지 않아" in panel.status.text()
        assert (
            env.content.active_transcript("k")["revision_id"] == env.t1
        )  # browsing is not selecting
    finally:
        dispose(panel)


def _k_privacy(env: SimpleNamespace, row: tuple[str, str, str, str], want: dict[str, Any]) -> None:
    key, widget, state, source = row
    reset_privacy(env)
    env.modals.reset("No")  # a refusal answered from the keyboard (Enter on default No)
    env.grants.clear()
    env.revokes.clear()
    control = env.privacy.controls["stt"]
    button = control.allow if widget == "refuse" else control.revoke
    assert button.isEnabled() and button.isVisible()
    throwaway = None
    try:
        if state == "disabled":
            button.setEnabled(False)
        elif state == "hidden":
            button.hide()
        elif state == "destroyed":
            throwaway = PrivacyPanel(
                env.consents, env.ledger, CredentialVault(backend=DummyVault(), namespace="g12-x")
            )
            throwaway.show()
            gone = (
                throwaway.controls["stt"].allow
                if widget == "refuse"
                else throwaway.controls["stt"].revoke
            )
            dispose(throwaway)
            assert not shiboken6.isValid(gone)
        target = env.root if state == "destroyed" else button
        press(target, key)
        env.modals.check()
        if widget == "refuse":
            assert len(env.modals.opened) == want["command"]
            assert all(defaults == (True, True) for defaults in env.modals.defaults)
            assert env.grants == []  # refusing never grants
        else:
            assert len(env.revokes) == want["command"]
            assert env.modals.opened == [] and env.grants == []
    finally:
        reset_privacy(env)


def _k_content_button(
    env: SimpleNamespace, row: tuple[str, str, str, str], want: dict[str, Any]
) -> None:
    key, widget, state, source = row
    panel, _ = k_panel(env)
    counts = {"cancel": 0, "continue": 0, "open": 0, "transcribe": 0, "retry": 0}
    owner = panel
    if state == "destroyed":
        owner = ContentPanel(SimpleNamespace(), Ops())
        owner.show()
    owner.cancelRequested.connect(lambda: counts.__setitem__("cancel", counts["cancel"] + 1))
    owner.blockedContinueRequested.connect(
        lambda: counts.__setitem__("continue", counts["continue"] + 1)
    )
    owner.blockedOpenRequested.connect(lambda: counts.__setitem__("open", counts["open"] + 1))
    owner.transcribeRequested.connect(
        lambda: counts.__setitem__("transcribe", counts["transcribe"] + 1)
    )
    owner.retrySummaryRequested.connect(lambda *_: counts.__setitem__("retry", counts["retry"] + 1))
    owner.show_ai_status(AIStatus("차단 · 조건 확인 필요", action_id="consent", can_continue=True))
    button = {
        "wait_cancel": owner.cancel_button,
        "continue": owner.blocked_continue,
        "settings_nav": owner.blocked_open,
    }[widget]
    try:
        if state == "disabled":
            button.setEnabled(False)
        elif state == "hidden":
            button.hide()
        elif state == "destroyed":
            dispose(owner)
            assert not shiboken6.isValid(button)
        press(panel if state == "destroyed" else button, key)
        signal = {"wait_cancel": "cancel", "continue": "continue", "settings_nav": "open"}[widget]
        assert counts[signal] == want["command"]
        assert sum(counts.values()) == want["command"]  # nothing else rides along
    finally:
        dispose(owner)
        dispose(panel)


# --- E: key x editing x column x filter -------------------------------------------
E_FILTERS = {"shown": "spoken", "hidden": "second", "all_hidden": "zzz-none", "empty": None}
E = list(product(K_KEYS, (False, True), ("time", "text"), tuple(E_FILTERS)))
E_IDS = [f"G12-E-{n:02}" for n in range(1, 65)]
TYPED = "고친 입력"


def e_oracle(row: tuple[str, bool, str, str]) -> int:
    key, editing, column, shown = row
    return int(key in ("Enter", "Space") and not editing and column == "time" and shown == "shown")


@pytest.mark.parametrize("row", E, ids=E_IDS)
def test_e_editing_and_filters_never_seek_or_lose_input(
    env: SimpleNamespace, row: tuple[str, bool, str, str]
) -> None:
    key, editing, column, shown = row
    ops = Ops("fail")
    panel, seeks = k_panel(env, "k-empty" if shown == "empty" else "k", ops)
    try:
        revisions = len(env.content.list_revisions("k", "transcript"))
        if shown != "empty":
            if editing:
                item = panel.table.item(0, 1)
                item.setText(TYPED)  # the save fails: a preserved, unsaved edit
                assert panel._unsaved_edit
            panel.table.setCurrentCell(0, 0 if column == "time" else 1)
            panel.search.setText(E_FILTERS[shown])
        elif editing:
            panel._unsaved_edit = True  # nothing to edit: the flag alone must not seek
        press(panel.table, key)
        assert len(seeks) == e_oracle(row)
        if seeks:
            assert seeks == [("mic", 1000, env.t1)]
        if editing and shown != "empty":
            assert panel.table.item(0, 1).text() == TYPED and panel._unsaved_edit
        assert len(env.content.list_revisions("k", "transcript")) == revisions  # no write
    finally:
        dispose(panel)


# --- F: modal x exit x opener x later user focus x completion timing ----------------
F_MODALS = (
    "library_consent",
    "general_risk",
    "summary_select",
    "unknown_retry",
    "clock_reset",
    "legacy_adoption",
)
F_EXITS = ("No", "Esc", "Yes")
F_OPENERS = ("valid", "disabled", "destroyed", "session_changed")
F = list(product(F_MODALS, F_EXITS, F_OPENERS, (False, True), ("immediate", "delayed")))
F_IDS = [f"G12-F-{n:03}" for n in range(1, 289)]


def f_oracle(row: tuple[str, str, str, bool, str]) -> tuple[int, str]:
    """(side effects, final focus) by hand: only Yes acts; a later user move wins; a
    usable current opener gets focus back; otherwise the modal's safe fallback."""
    modal, exit_key, opener, moved, timing = row
    focus = "other" if moved else ("opener" if opener == "valid" else "fallback")
    return (1 if exit_key == "Yes" else 0), focus


def _selectable_world(env: SimpleNamespace) -> tuple[str, str]:
    session = f"f{next(_serial)}"
    env.library.create_session(session)
    source = env.content.create_transcript(session, list(K_SEGMENTS))
    env.content.request_summary_settings(session, "K")
    env.content.create_summary(
        session, source, [Claim("selected", ("a",))], expected_transcript=source
    )
    target = publish(env, session, source, key="K")
    return session, target


def _prepare_fixture_history(env: SimpleNamespace) -> None:
    """Prepare positive fixture authority before any fault or race is injected."""
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="g12-history-prepare") as worker:
        status = worker.submit(env.library.verify_deletion_history, fresh=True).result(timeout=10)
    assert status == {"status": "READY", "code": ""}, status


def publish(
    env: SimpleNamespace,
    session: str,
    source: str,
    *,
    key: str | None,
    complete: bool = True,
    text: str = "candidate",
) -> str:
    """An unselected candidate through the real G-P03 publication path."""
    _prepare_fixture_history(env)
    jobs = env.jobs
    job = jobs.create("summarization", f"g12-ui-{next(_serial)}")
    jobs.bind_session(job.job_id, session)
    attempt = jobs.claim(job.job_id, "fixture")
    state = env.content.selection_state(session)
    revision = env.content.publish_summary(
        jobs,
        attempt,
        session,
        source,
        [Claim(text, ("a",))],
        complete=complete,
        expected_transcript=source,
        expected_summary=state["summary_id"],
        expected_summary_version=state["summary_version"] + 1_000,
        settings_key=key,
    )
    if not complete:
        jobs.fail(job.job_id, attempt.attempt_id, attempt.fence, "SUMMARY_PARTIAL")
    return revision


@pytest.mark.parametrize("row", F, ids=F_IDS)
def test_f_modals_default_to_no_and_return_focus_only_when_safe(
    env: SimpleNamespace, row: tuple[str, str, str, bool, str]
) -> None:
    modal, exit_key, opener_state, moved, timing = row
    effects, focus_name = f_oracle(row)
    reset_privacy(env)
    env.root.session = "s1"
    if not shiboken6.isValid(env.opener):
        env.opener = QPushButton("opener")
        env.root.layout().insertWidget(2, env.opener)
    env.opener.setEnabled(True)
    env.opener.show()
    env.grants.clear()
    env.resets.clear()
    env.adoptions.clear()
    env.retries.clear()
    panel, control = env.panel, env.privacy.controls["stt"]
    ops = env.ops
    ops.mode, ops.held = ("hold" if timing == "delayed" else "now"), []
    session = target = None
    if modal == "summary_select":
        session, target = _selectable_world(env)
        panel.load(session)
        panel.summary_candidates.setCurrentIndex(panel.summary_candidates.findData(target))
        assert panel.select_summary_button.isEnabled()
    env.opener.setFocus()
    env.root.activateWindow()
    env.app.processEvents()
    assert env.root.focusWidget() is env.opener
    opener = env.opener

    def during() -> None:
        if opener_state == "disabled":
            opener.setEnabled(False)
        elif opener_state == "destroyed":
            shiboken6.delete(opener)
        elif opener_state == "session_changed":
            if modal == "summary_select":
                panel.load("k")
            elif modal == "unknown_retry":
                env.root.session = "s2"
            else:
                env.privacy.select_session("other-session")

    env.modals.reset(exit_key, during)
    if modal == "library_consent":
        env.privacy._action("stt", "grant")
    elif modal == "general_risk":
        control.cost_mode.setCurrentIndex(control.cost_mode.findData("general"))
    elif modal == "summary_select":
        panel.select_candidate()
    elif modal == "unknown_retry":
        env.bridge.retry_summary("meeting")
    elif modal == "clock_reset":
        env.privacy._action("stt", "reset_clock")
    else:
        env.privacy._action("stt", "adopt")
    env.modals.check()
    assert len(env.modals.opened) == 1 and env.modals.defaults == [(True, True)]
    if moved:
        env.other.setFocus()
    if timing == "delayed":
        ops.flush()  # a late completion (summary selection) and a later poll
        env.app.processEvents()
        if modal in ("summary_select", "unknown_retry"):
            panel.load(panel.session_id or "k")
        else:
            env.privacy._action("stt", "refresh")
    else:
        ops.flush()
    done = {
        "library_consent": lambda: len(env.grants),
        "general_risk": lambda: int(
            control.cost_mode.currentData() == "general" and control.general_acknowledged
        ),
        "summary_select": lambda: int(env.content.selection_state(session)["summary_id"] == target),
        "unknown_retry": lambda: len(env.retries),
        "clock_reset": lambda: len(env.resets),
        "legacy_adoption": lambda: len(env.adoptions),
    }[modal]()
    assert done == effects
    fallback = {
        "summary_select": panel.summary_candidates,
        "unknown_retry": panel.versions,
    }.get(modal, control.scope)
    expected = {"other": env.other, "opener": opener, "fallback": fallback}[focus_name]
    assert env.root.focusWidget() is expected


# --- N: announcement kind x poll x focus x generation ------------------------------
N_STATES = (
    "PREPARATION_BLOCKED",
    "QUEUED",
    "RUNNING",
    "CANCEL_REQUESTED",
    "LOCAL_ACK",
    "REMOTE_UNKNOWN",
    "REVOCATION_PERSISTED",
    "SELECTION_CONFLICT",
    "BLOCKED",
    "BACKOFF",
    "ABANDONED",
    "FAILED",
)
N = list(
    product(
        N_STATES, ("same_poll", "new_version"), ("focus_current", "focus_other"), ("current", "old")
    )
)
N_IDS = [f"G12-N-{n:02}" for n in range(1, 97)]
ASSERTIVE = {"PREPARATION_BLOCKED", "REMOTE_UNKNOWN", "SELECTION_CONFLICT", "BLOCKED", "FAILED"}
# Hand-made Job snapshots for the Job-derived states (G-P07 vocabulary).
N_JOBS = {
    "QUEUED": ("QUEUED", None, False),
    "RUNNING": ("RUNNING", None, False),
    "CANCEL_REQUESTED": ("CANCEL_REQUESTED", None, True),
    "LOCAL_ACK": ("CANCELLED", None, True),
    "REMOTE_UNKNOWN": ("BLOCKED", "REMOTE_UNKNOWN", True),
    "BLOCKED": ("BLOCKED", "CONSENT", False),
    "BACKOFF": ("BACKOFF", None, False),
    "ABANDONED": ("BLOCKED", "ABANDONED", False),
    "FAILED": ("FAILED", None, False),
}


def fake_job(state: str, version: int) -> SimpleNamespace:
    value, reason, cancel = N_JOBS[state]
    if state == "BLOCKED" and version > 1:
        reason = "BUDGET"  # the same Job, a new blocking reason
    return SimpleNamespace(
        job_id="job-n",
        state=SimpleNamespace(value=value),
        state_version=version,
        blocked_reason=reason,
        error_code="TASK_FAILED" if value == "FAILED" else None,
        cancel_requested=cancel,
    )


def n_oracle(row: tuple[str, str, str, str]) -> tuple[int, str]:
    state, poll, focus, generation = row
    first = 0 if generation == "old" else 1
    return first + (
        1 if poll == "new_version" else 0
    ), "assertive" if state in ASSERTIVE else "polite"


@pytest.mark.parametrize("row", N, ids=N_IDS)
def test_n_announcements_once_per_meaning_and_never_move_focus(
    env: SimpleNamespace, row: tuple[str, str, str, str]
) -> None:
    state, poll, focus, generation = row
    events, politeness = n_oracle(row)
    sink = Sink()
    announcer = a11y.Announcer(sink)
    target = env.panel.job_status
    focused = env.panel.cancel_button if focus == "focus_current" else env.other
    focused.setFocus()
    env.app.processEvents()

    def say(version: int, generation_value: int | None) -> None:
        if state in N_JOBS:
            job = fake_job(state, version)
            kind = job_announcement(job)
            assert kind == state
            announcer.announce(
                "content",
                target,
                kind,
                announcement_text(kind, job),
                version=announcement_version(job),
                generation=generation_value,
            )
        else:
            announcer.announce(
                "content",
                target,
                state,
                f"{state} 안내",
                version=(state, version),
                generation=generation_value,
            )

    old = announcer.generation("content")
    if generation == "old":
        announcer.advance("content")  # a callback from an earlier view
    used = old if generation == "old" else None
    say(1, used)
    say(1, used)  # the same poll again
    say(2 if poll == "new_version" else 1, None if poll == "new_version" else used)
    assert len(sink.events) == events
    assert all(event[2] == politeness for event in sink.events)
    assert all(event[0] is target for event in sink.events)
    assert env.root.focusWidget() is focused  # announcing never moves focus
    texts = " ".join(event[1] for event in sink.events)
    assert "원격 취소 완료" not in texts and "원격 취소됨" not in texts
    if state == "LOCAL_ACK" and sink.events:
        assert "로컬" in texts
    if state == "REMOTE_UNKNOWN" and sink.events:
        assert "미확인" in texts and "취소 요청됨" in texts


# --- C: candidates x target x race x confirmation x session -----------------------
C_LISTS = ("none", "one", "many")
C_TARGETS = ("complete_current", "complete_old_transcript", "complete_old_settings", "partial")
C_RACES = ("unchanged", "summary_id", "summary_aba", "transcript_aba", "settings_key")
C = list(product(C_LISTS, C_TARGETS, C_RACES, ("Yes", "No", "Esc"), ("same", "changed")))
C_IDS = [f"G12-C-{n:03}" for n in range(1, 361)]
OUTDATED_NOTICE = "이전 전사·설정의 결과이거나"


def c_oracle(row: tuple[str, str, str, str, str]) -> dict[str, Any]:
    candidates, target, race, confirm, session = row
    if candidates == "none" or target == "partial":
        return {"modal": 0, "write": False, "conflict": False, "notice": False}
    yes = confirm == "Yes"
    return {
        "modal": 1,
        "notice": target != "complete_current",
        "write": yes and race == "unchanged",
        "conflict": yes and race != "unchanged" and session == "same",
    }


def c_world(env: SimpleNamespace, candidates: str, target: str) -> dict[str, str]:
    session = f"c{next(_serial)}"
    env.library.create_session(session)
    old = env.content.create_transcript(session, list(K_SEGMENTS))
    current = env.content.create_transcript(session, list(K_SEGMENTS), expected_active=old)
    env.content.request_summary_settings(session, "K")
    base = env.content.create_summary(
        session, current, [Claim("selected", ("a",))], expected_transcript=current
    )
    world = {"session": session, "old": old, "current": current, "base": base, "target": base}
    if candidates != "none":
        source, key, complete = {
            "complete_current": (current, "K", True),
            "complete_old_transcript": (old, "K", True),
            "complete_old_settings": (current, "K-old", True),
            "partial": (current, "K", False),
        }[target]
        world["target"] = publish(env, session, source, key=key, complete=complete, text="target")
    if candidates == "many":
        world["extra"] = publish(env, session, current, key="K", text="extra")
    return world


def race(env: SimpleNamespace, world: dict[str, str], kind: str) -> None:
    peer, session = env.peer, world["session"]
    if kind in ("summary_id", "summary_aba"):
        late = peer.create_summary(
            session,
            world["current"],
            [Claim("late", ("a",))],
            expected_transcript=world["current"],
            expected_summary=world["base"],
        )
        assert peer.selection_state(session)["summary_id"] == late
        if kind == "summary_aba":
            assert peer.select_summary(session, world["base"], expected_active=late)
    elif kind == "transcript_aba":
        assert peer.select_transcript(session, world["old"], expected_active=world["current"])
        assert peer.select_transcript(session, world["current"], expected_active=world["old"])
    elif kind == "settings_key":
        peer.request_summary_settings(session, "K-new")


@pytest.fixture(scope="module")
def elsewhere(env: SimpleNamespace) -> str:
    env.library.create_session("c-other")
    source = env.content.create_transcript("c-other", list(K_SEGMENTS))
    env.content.create_summary(
        "c-other", source, [Claim("elsewhere", ("a",))], expected_transcript=source
    )
    return "c-other"


@pytest.mark.parametrize("row", C, ids=C_IDS)
def test_c_browse_then_confirm_selects_only_the_presented_snapshot(
    env: SimpleNamespace, elsewhere: str, row: tuple[str, str, str, str, str]
) -> None:
    candidates, target, race_kind, confirm, session_axis = row
    want = c_oracle(row)
    world = c_world(env, candidates, target)
    session, panel, ops = world["session"], env.panel, env.ops
    ops.mode, ops.held = "hold", []
    sink = Sink()
    panel.announcer.sink = sink
    panel.load(session)
    panel.summary_candidates.setCurrentIndex(panel.summary_candidates.findData(world["target"]))
    other_before = env.content.selection_state(elsewhere)
    env.modals.reset(confirm, lambda: race(env, world, race_kind))
    if want["modal"] == 0:
        race(env, world, race_kind)
    raced: list[Any] = []
    press(panel.select_summary_button, "Space")
    env.modals.check()
    assert len(env.modals.opened) == want["modal"]
    if want["modal"]:
        assert (OUTDATED_NOTICE in env.modals.opened[0][2]) is want["notice"]
        assert env.modals.defaults == [(True, True)]
    raced.append(env.content.selection_state(session))
    if session_axis == "changed":
        panel.load(elsewhere)
        screen = (
            panel.candidate_info.text(),
            panel.summary_candidates.count(),
            panel.claims.toPlainText(),
        )
    ops.flush()
    after = env.content.selection_state(session)
    if want["write"]:
        assert after == {
            **raced[0],
            "summary_id": world["target"],
            "summary_version": raced[0]["summary_version"] + 1,
        }
    else:
        assert after == raced[0]  # the panel wrote nothing
    conflicts = [event for event in sink.events if "충돌" in event[1]]
    assert len(conflicts) == int(want["conflict"])
    if conflicts:
        assert conflicts[0][2] == "assertive"
    if session_axis == "changed":
        assert panel.session_id == elsewhere
        assert (
            panel.candidate_info.text(),
            panel.summary_candidates.count(),
            panel.claims.toPlainText(),
        ) == screen
        assert env.content.selection_state(elsewhere) == other_before


# --- R: candidates x following/browsing x poll x unsaved edit ---------------------
R = list(
    product(
        C_LISTS, ("follow", "browse"), ("unchanged", "new_summary", "session_change"), (False, True)
    )
)
R_IDS = [f"G12-R-{n:02}" for n in range(1, 37)]


def r_oracle(row: tuple[str, str, str, bool]) -> str:
    """Which summary the panel shows after the poll (by hand, G12 4.1/4.3)."""
    candidates, mode, poll, unsaved = row
    if poll == "session_change":
        return "elsewhere"
    browsing = mode == "browse" and candidates != "none"
    if browsing:
        return "browsed"
    if poll == "new_summary" and not unsaved:
        return "late"
    return "base"


@pytest.mark.parametrize("row", R, ids=R_IDS)
def test_r_polls_keep_browsing_search_and_edits_and_never_select(
    env: SimpleNamespace, elsewhere: str, row: tuple[str, str, str, bool]
) -> None:
    candidates, mode, poll, unsaved = row
    want = r_oracle(row)
    world = c_world(env, candidates, "complete_current")
    session = world["session"]
    ops = Ops("fail")
    panel, _ = k_panel(env, session, ops)
    try:
        if mode == "browse":
            panel.summary_candidates.setCurrentIndex(
                panel.summary_candidates.findData(world["target"])
            )
        panel.search.setText("words")
        if unsaved:
            panel.table.item(0, 1).setText(TYPED)
            assert panel._unsaved_edit
        state = env.content.selection_state(session)
        late = None
        if poll == "new_summary":
            late = env.peer.create_summary(
                session,
                world["current"],
                [Claim("late result", ("a",))],
                expected_transcript=world["current"],
                expected_summary=world["base"],
            )
            state = env.content.selection_state(session)
        revision = panel.claims.document().revision()
        panel.load(elsewhere if poll == "session_change" else session)
        shown = {
            "browsed": world["target"],
            "late": late,
            "base": world["base"],
        }
        text = panel.claims.toPlainText()
        if want == "elsewhere":
            assert panel.session_id == elsewhere and "elsewhere" in text
        else:
            expected_text = {"browsed": "target", "late": "late result", "base": "selected"}[want]
            assert expected_text in text and shown[want] is not None
            assert panel.search.text() == "words"
            if poll == "unchanged":
                assert panel.claims.document().revision() == revision  # no re-render
        if unsaved and poll != "session_change":
            assert panel.table.item(0, 1).text() == TYPED and panel._unsaved_edit
        assert env.content.selection_state(session) == state  # polling and browsing never select
    finally:
        dispose(panel)


# --- Z: empty/nonempty transcript x complete/partial x legacy/new empty claims ------
Z = list(product(("empty", "nonempty"), ("complete", "partial"), ("legacy", "new_empty")))
Z_IDS = [f"G12-Z-{n:02}" for n in range(1, 9)]


def z_oracle(row: tuple[str, str, str]) -> tuple[int, int]:
    transcript, summary, claims = row
    if claims == "new_empty":
        return 0, 0
    return (1, 0) if transcript == "nonempty" else (0, 1)  # an unreferenced claim needs review


@pytest.mark.parametrize("row", Z, ids=Z_IDS)
def test_z_no_claims_partial_and_legacy_never_read_as_verified(
    env: SimpleNamespace, row: tuple[str, str, str]
) -> None:
    transcript, summary, claims = row
    referenced, review = z_oracle(row)
    session = f"z{next(_serial)}"
    env.library.create_session(session)
    source = env.content.create_transcript(
        session, list(K_SEGMENTS) if transcript == "nonempty" else []
    )
    values = (
        []
        if claims == "new_empty"
        else [Claim("legacy claim", ("a",) if transcript == "nonempty" else ())]
    )
    _prepare_fixture_history(env)
    jobs = env.jobs
    job = jobs.create("summarization", f"g12-z-{next(_serial)}")
    jobs.bind_session(job.job_id, session)
    attempt = jobs.claim(job.job_id, "fixture")
    published = env.content.publish_summary(
        jobs,
        attempt,
        session,
        source,
        values,
        complete=summary == "complete",
        expected_transcript=source,
    )
    if summary == "partial":
        jobs.fail(job.job_id, attempt.attempt_id, attempt.fence, "SUMMARY_PARTIAL")
    panel, _ = k_panel(env, session)
    try:
        if summary == "partial":  # a partial result is a candidate: the user browses it
            panel.summary_candidates.setCurrentIndex(panel.summary_candidates.findData(published))
            assert not panel.select_summary_button.isEnabled()
        text = all_text(panel)
        assert f"· {referenced}건" in panel.claims_title.text()
        assert f"· {review}건" in panel.review_title.text()
        assert not any(word in text for word in FORBIDDEN)
        assert ("부분 결과" in text) is (summary == "partial")
        if claims == "new_empty":
            assert panel.claims.toPlainText().count("0건 — 해당 없음") == 1
            assert panel.review_claims.toPlainText().count("0건 — 해당 없음") == 1
        else:
            assert "어댑터 미기록" in text
    finally:
        dispose(panel)


# --- named UI boundary rows ---------------------------------------------------------
T_UI = (
    "G12-T-06",
    "G12-T-07",
    "G12-T-08",
    "G12-T-09",
    "G12-T-11",
    "G12-T-12",
    "G12-T-13",
    "G12-T-14",
    "G12-T-15",
    "G12-T-16",
    "G12-T-17",
    "G12-T-22",
    "G12-T-23",
    "G12-T-26",
)


@pytest.mark.parametrize("case", T_UI, ids=T_UI)
def test_t_ui_boundaries(env: SimpleNamespace, case: str, tmp_path: Path) -> None:
    {
        "G12-T-06": _t06_escape,
        "G12-T-07": _t07_external,
        "G12-T-08": _t08_old_generation,
        "G12-T-09": _t09_deleted_source,
        "G12-T-11": _t11_user_assertion,
        "G12-T-12": _t12_unverified,
        "G12-T-13": _t13_mixed,
        "G12-T-14": _t14_dirty_link,
        "G12-T-15": _t15_ime_space,
        "G12-T-16": _t16_single_activation,
        "G12-T-17": _t17_empty_tab,
        "G12-T-22": _t22_worker_thread,
        "G12-T-23": _t23_cancel_without_ack,
        "G12-T-26": _t26_unknown_cancel,
    }[case](env, tmp_path)


def _t06_escape(env: SimpleNamespace, tmp_path: Path) -> None:
    session = f"t06-{next(_serial)}"
    env.library.create_session(session)
    source = env.content.create_transcript(session, list(K_SEGMENTS))
    hostile = "<script>alert(1)</script><b>bold</b> & <a href='https://evil.example'>x</a>"
    env.content.create_summary(
        session, source, [Claim(hostile, ("a",))], expected_transcript=source
    )
    panel, seeks = k_panel(env, session)
    try:
        assert hostile in panel.claims.toPlainText()  # shown literally, not interpreted
        hrefs = [href for href, *_ in anchors(panel.claims) + anchors(panel.review_claims)]
        assert hrefs and all(href.startswith("claim:") for href in hrefs)
        assert "<script" not in panel.claims.toHtml().lower().replace("&lt;script", "")
    finally:
        dispose(panel)


def _t07_external(env: SimpleNamespace, tmp_path: Path) -> None:
    from PySide6.QtCore import QUrl

    panel, seeks = k_panel(env)
    try:
        before = panel.revision["revision_id"]
        for url in (
            "https://example.com/claim:0:0",
            "file:///C:/Windows",
            "claim:0:0@999",
            "javascript:x",
        ):
            panel.claims.anchorClicked.emit(QUrl(url))
            panel._claim_clicked(url)
        assert seeks == [] and panel.revision["revision_id"] == before
        assert not panel.claims.openExternalLinks() and not panel.claims.openLinks()
    finally:
        dispose(panel)


def _t08_old_generation(env: SimpleNamespace, tmp_path: Path) -> None:
    panel, seeks = k_panel(env)
    try:
        _, old = link_for(panel, "AUDIO-CLAIM")
        panel.load("k-empty")
        panel.load("k")
        _, new = link_for(panel, "AUDIO-CLAIM")
        assert new != old
        panel._claim_clicked(old)
        assert seeks == []
        panel._claim_clicked(new)
        assert seeks == [("mic", 1000, env.t0)]
        panel._claim_clicked("claim:0:0")  # an existing generation-less caller: current view
        assert seeks == [("mic", 1000, env.t0)] * 2
    finally:
        dispose(panel)


def _t09_deleted_source(env: SimpleNamespace, tmp_path: Path) -> None:
    # A private library: a pending deletion must not linger in the shared one.
    with (
        Library(tmp_path / "library") as library,
        ContentStore(library) as content,
        JobStore(library.db_path) as jobs,
    ):
        library.create_session("gone")
        source = content.create_transcript("gone", list(K_SEGMENTS))
        content.create_summary(
            "gone", source, [Claim("AUDIO-CLAIM", ("a",))], expected_transcript=source
        )
        panel = ContentPanel(content, Ops())
        seeks: list[Any] = []
        panel.seekRequested.connect(lambda *args: seeks.append(args))
        panel.show()
        try:
            panel.load("gone")
            browser, href = link_for(panel, "AUDIO-CLAIM")
            reader = jobs.create("summarization", "t09-reader")
            jobs.bind_session(reader.job_id, "gone")
            held = jobs.claim(reader.job_id, "reader")
            assert library.delete_session("gone")["deleted"] is False
            focus_link(browser, href)
            press(browser, "Enter")
            assert seeks == [] and "근거 확인 불가" in panel.status.text()
            jobs.fail(reader.job_id, held.attempt_id, held.fence, "T09_DONE")
        finally:
            dispose(panel)


def _t11_user_assertion(env: SimpleNamespace, tmp_path: Path) -> None:
    panel, seeks = k_panel(env)
    try:
        row = 1
        assert panel.revision["segments"][row]["provenance"] == "user_assertion"
        assert panel.revision["segments"][row]["start_ms"] == 2000  # it has a time
        panel.table.setCurrentCell(row, 0)
        for key in ("Enter", "Space"):
            press(panel.table, key)
        panel._seek(row, 0)
        assert seeks == [] and "검증되지 않아" in panel.status.text()
    finally:
        dispose(panel)


def _t12_unverified(env: SimpleNamespace, tmp_path: Path) -> None:
    panel, seeks = k_panel(env)
    try:
        assert panel.revision["segments"][2]["timing_quality"] == "unverified"
        panel.table.setCurrentCell(2, 0)
        press(panel.table, "Enter")
        browser, href = link_for(panel, "DRIFT-CLAIM")
        focus_link(browser, href)
        press(browser, "Space")
        assert seeks == []
    finally:
        dispose(panel)


def _t13_mixed(env: SimpleNamespace, tmp_path: Path) -> None:
    panel, seeks = k_panel(env)
    try:
        browser, first = link_for(panel, "MIXED-CLAIM", 0)
        assert browser is panel.review_claims  # a user-asserted ref sends it to review
        focus_link(browser, first)
        press(browser, "Enter")
        assert seeks == [] and "발화 위치" in panel.status.text()
        panel.load("k-empty")
        panel.load("k")
        browser, second = link_for(panel, "MIXED-CLAIM", 1)
        focus_link(browser, second)
        press(browser, "Enter")
        assert seeks == [("sys", 4000, env.t0)]  # only the audio ref, at its own time
        assert not any(word in all_text(panel) for word in FORBIDDEN)
    finally:
        dispose(panel)


def _t14_dirty_link(env: SimpleNamespace, tmp_path: Path) -> None:
    panel, seeks = k_panel(env, ops=Ops("fail"))
    try:
        panel.table.item(0, 1).setText(TYPED)
        assert panel._unsaved_edit
        browser, href = link_for(panel, "AUDIO-CLAIM")
        focus_link(browser, href)
        press(browser, "Enter")
        assert seeks == [] and "편집" in panel.status.text()
        assert panel.revision["revision_id"] == env.t1 and panel.table.item(0, 1).text() == TYPED
    finally:
        dispose(panel)


def _t15_ime_space(env: SimpleNamespace, tmp_path: Path) -> None:
    from PySide6.QtGui import QInputMethodEvent

    panel, seeks = k_panel(env)
    try:
        panel.table.setCurrentCell(0, 1)
        panel.table.editItem(panel.table.item(0, 1))
        editors = panel.table.viewport().findChildren(QLineEdit)
        assert editors, "no editor opened"
        editor = editors[0]
        editor.setText("조합 ")
        QApplication.sendEvent(editor, QInputMethodEvent("가", []))  # a composition in progress
        press(editor, "Space")
        press(panel.table, "Space")
        assert seeks == []
        assert editor.text().startswith("조합 ") and editor.text().endswith(" ")
    finally:
        dispose(panel)


def _t16_single_activation(env: SimpleNamespace, tmp_path: Path) -> None:
    panel, seeks = k_panel(env)
    try:
        panel.table.setCurrentCell(0, 0)
        press(panel.table, "Enter")
        assert len(seeks) == 1
        browser, href = link_for(panel, "AUDIO-CLAIM")
        focus_link(browser, href)
        press(browser, "Enter")  # Qt's own link activation and ours: still one
        assert len(seeks) == 2
    finally:
        dispose(panel)


def _t17_empty_tab(env: SimpleNamespace, tmp_path: Path) -> None:
    session = f"t17-{next(_serial)}"
    env.library.create_session(session)
    source = env.content.create_transcript(session, list(K_SEGMENTS))
    env.content.create_summary(session, source, [], expected_transcript=source)
    panel, _ = k_panel(env, session)
    try:
        panel.activateWindow()
        panel.claims.setFocus()
        env.app.processEvents()
        assert anchors(panel.claims) == []
        press(panel.claims, "Tab")
        env.app.processEvents()
        assert panel.focusWidget() is not panel.claims  # no keyboard trap
    finally:
        dispose(panel)


def _t22_worker_thread(env: SimpleNamespace, tmp_path: Path) -> None:
    sink = Sink()
    announcer = a11y.Announcer(sink)
    target = env.panel.job_status
    worker = threading.Thread(
        target=lambda: announcer.announce(
            "content", target, "RUNNING", "AI 작업 실행 중", version=("t22", 1)
        )
    )
    worker.start()
    worker.join(5)
    assert sink.events == []  # queued, not delivered on the worker
    env.app.processEvents()
    assert len(sink.events) == 1 and sink.threads == [env.app.thread()]


def _bridge(env: SimpleNamespace, store: JobStore, panel: ContentPanel) -> DesktopAI:
    bridge = DesktopAI.__new__(DesktopAI)
    bridge.window = SimpleNamespace(
        selected_session=lambda: "s",
        busy=False,
        model_panel=SimpleNamespace(request_attestation_check=lambda: None),
        live_stt=SimpleNamespace(setChecked=lambda value: None),
    )
    bridge.panel, bridge._history, bridge.local = panel, store, None
    bridge._last_snapshot, bridge._gpu_failed = "", None
    bridge._live_tick = lambda: None
    bridge.busy = False
    return bridge


def _empty_panel() -> ContentPanel:
    panel = ContentPanel(
        SimpleNamespace(
            active_transcript=lambda _: None,
            list_revisions=lambda *_: [],
            active_summary=lambda _: None,
        ),
        Ops(),
    )
    panel.show()
    return panel


def _t23_cancel_without_ack(env: SimpleNamespace, tmp_path: Path) -> None:
    with JobStore(Path(":memory:")) as store:
        job = store.create("summarization", "t23")
        store.bind_session(job.job_id, "s")
        store.claim(job.job_id, "worker")
        panel = _empty_panel()
        sink = Sink()
        panel.announcer.sink = sink
        bridge = _bridge(env, store, panel)
        try:
            bridge.tick()
            store.cancel(job.job_id)  # cancel requested; the worker has not acknowledged
            bridge.tick()
            bridge.tick()
            kinds = [message for _, message, _ in sink.events]
            assert len(kinds) == 2 and kinds[0].startswith("AI 작업 실행 중")
            assert kinds[1].startswith("취소 요청됨")
            assert not any("로컬 종료 확인" in message.split(" · ")[0] for message in kinds)
            assert not any("완료" in message for message in kinds)
        finally:
            dispose(panel)


def _t26_unknown_cancel(env: SimpleNamespace, tmp_path: Path) -> None:
    with JobStore(Path(":memory:")) as store:
        job = store.create("summarization", "t26")
        store.bind_session(job.job_id, "s")
        attempt = store.claim(job.job_id, "worker")
        store.fail(
            job.job_id,
            attempt.attempt_id,
            attempt.fence,
            "REMOTE_OUTCOME_UNKNOWN",
            outcome_known=False,
        )
        assert (store.get(job.job_id).state.value, store.get(job.job_id).blocked_reason) == (
            "BLOCKED",
            "REMOTE_UNKNOWN",
        )
        panel = _empty_panel()
        sink = Sink()
        panel.announcer.sink = sink
        bridge = _bridge(env, store, panel)
        cancelled: list[str] = []
        bridge.service = SimpleNamespace(
            cancel_session=lambda session: (cancelled.append(session), store.cancel(job.job_id))
        )
        bridge.pool = SimpleNamespace(start=lambda task: task.run())
        bridge._tasks = set()
        bridge._preparation_cancel = threading.Event()
        panel.cancelRequested.connect(bridge.cancel)
        try:
            bridge.tick()
            press(panel.cancel_button, "Enter")  # the existing wait/job cancel, by keyboard
            bridge.tick()
            after = store.get(job.job_id)
            assert cancelled == ["s"]
            assert (after.state.value, after.blocked_reason, after.cancel_requested) == (
                "BLOCKED",
                "REMOTE_UNKNOWN",
                True,
            )
            messages = [message for _, message, _ in sink.events]
            assert any(message.startswith("취소 요청됨") for message in messages)
            assert messages[-1].startswith("취소 요청됨 · 원격 결과·비용 미확인")
            assert not any(
                "로컬 종료 확인" in message.split(" · ")[0] or "완료" in message
                for message in messages
            )
        finally:
            dispose(panel)


# --- traces (extra nodes, not counted as semantic rows) -----------------------------
def test_trace_tab_between_links_survives_a_poll_and_names_are_present(
    env: SimpleNamespace,
) -> None:
    panel, seeks = k_panel(env)
    try:
        panel.activateWindow()
        panel.claims.setFocus()
        env.app.processEvents()
        press(panel.claims, "Tab")
        first = a11y.focused_anchor(panel.claims)
        assert first.startswith("claim:")
        panel.load("k")  # an unchanged poll mid-trace keeps the focused link
        assert a11y.focused_anchor(panel.claims) == first
        press(panel.claims, "Tab")
        second = a11y.focused_anchor(panel.claims)
        assert second.startswith("claim:") and second != first
        QTest.keyClick(panel.claims, Qt.Key.Key_Backtab, Qt.KeyboardModifier.ShiftModifier)
        assert a11y.focused_anchor(panel.claims) == first  # Shift+Tab focus is a link too
        press(panel.claims, "Enter")
        assert seeks == [("mic", 1000, env.t0)]
        for widget in (
            panel.table,
            panel.claims,
            panel.review_claims,
            panel.summary_candidates,
            panel.select_summary_button,
            panel.cancel_button,
            panel.blocked_open,
            panel.blocked_continue,
            panel.templates,
            env.privacy.controls["stt"].revoke,
            env.privacy.controls["stt"].allow,
        ):
            assert widget.accessibleName()
        for widget in (
            panel.claims,
            panel.review_claims,
            panel.summary_candidates,
            panel.cancel_button,
            panel.select_summary_button,
            env.privacy.controls["stt"].revoke,
        ):
            assert widget.accessibleDescription()
    finally:
        dispose(panel)


def test_trace_bridge_names_the_real_window_policy_control_only(
    app: QApplication, tmp_path: Path
) -> None:
    from recoryn.ui.main import MainWindow

    with Library(tmp_path / "library") as library:
        window = MainWindow(library)
        window.timer.stop()
        try:
            policy = window.device_policy
            before = policy.currentText()
            app.processEvents()  # the bridge names it once the window has built it
            assert policy.accessibleName() == "AI 실행 정책"
            assert "자동으로 바뀌지" in policy.accessibleDescription()
            assert policy.currentText() == before  # accessibility only; no policy change
        finally:
            window.close()
            window.deleteLater()
            app.processEvents()


def test_trace_busy_selection_unchanged_list_and_selected_label(env: SimpleNamespace) -> None:
    """A busy bridge refuses the selection visibly; an unchanged poll keeps the list."""
    world = c_world(env, "one", "complete_current")
    session = world["session"]

    class Busy(Ops):
        def __call__(self, fn: Any, done: Any, failed: Any = None) -> bool:
            self.calls += 1
            return False  # DesktopAI.operation while another operation runs

    busy = Busy()
    panel = ContentPanel(env.content, busy)
    panel.show()
    try:
        panel.load(session)
        # The selected base has no recorded settings key: selected, never presumed current.
        assert panel.candidate_info.text() == "선택된 요약입니다. 이전 전사·설정 기준입니다."
        removed: list[Any] = []
        panel.summary_candidates.model().rowsRemoved.connect(lambda *args: removed.append(args))
        panel.load(session)  # an unchanged poll
        assert removed == []
        panel.summary_candidates.setCurrentIndex(panel.summary_candidates.findData(world["target"]))
        before = env.content.selection_state(session)
        env.modals.reset("Yes")
        press(panel.select_summary_button, "Space")
        env.modals.check()
        assert busy.calls == 1 and env.content.selection_state(session) == before
        assert "선택하지 못했습니다" in panel.candidate_info.text()
    finally:
        dispose(panel)


# =====================================================================================
# FIX1 (G-P12 independent review G12R-01..09): X rows. Each row is the reviewer's
# counterexample shape or a rule that had no row; expectations are hand-written from
# G12 sections 3.2, 4.1-4.3 and 5.1-5.2.
# =====================================================================================
from tests.unit.test_claim_basis import _tamper  # noqa: E402

X_IDS = [f"G12-X-{n:02}" for n in range(1, 17)]
UNVERIFIABLE = "근거 확인 불가"


def _x_world(
    env: SimpleNamespace, claims: list[Claim], *, key: str | None = None
) -> tuple[str, str, str]:
    session = f"x{next(_serial)}"
    env.library.create_session(session)
    source = env.content.create_transcript(session, list(K_SEGMENTS))
    if key is not None:
        env.content.request_summary_settings(session, key)
    summary = env.content.create_summary(session, source, claims, expected_transcript=source)
    return session, source, summary


def _paragraph(browser: QTextBrowser, marker: str) -> str:
    return next((line for line in browser.toPlainText().splitlines() if marker in line), "")


def _no_evidence_path(env: SimpleNamespace, panel: ContentPanel, seeks: list, marker: str) -> None:
    """The unverifiable claim offers no link, no playback and no evidence row."""
    assert marker in panel.review_claims.toPlainText() and marker not in panel.claims.toPlainText()
    line = _paragraph(panel.review_claims, marker)
    assert UNVERIFIABLE in line and "재생 가능" not in line and "근거 1" not in line
    assert [href for href, _, _, text in anchors(panel.review_claims) if marker in text] == []
    for browser in (panel.claims, panel.review_claims):
        for key in ("Enter", "Space"):
            press(browser, key)
    panel._claim_clicked("claim:0:0")  # the old generation-less caller, too
    assert seeks == [] and panel.table.selectedItems() == []


@pytest.mark.parametrize("case", X_IDS, ids=X_IDS)
def test_x_fix1_rows(env: SimpleNamespace, case: str, tmp_path: Path) -> None:
    globals()["_x" + case[-2:]](env, tmp_path)


def _x01(env: SimpleNamespace, tmp_path: Path) -> None:
    """G12R-01 P1: stored basis mismatch -> unverifiable, seek 0."""
    session, source, summary = _x_world(env, [Claim("X01-CLAIM", ("a",))])
    _tamper(env.library, summary, lambda body: body["claims"][0].update(basis="user_assertion"))
    panel, seeks = k_panel(env, session)
    try:
        _no_evidence_path(env, panel, seeks, "X01-CLAIM")
        assert "저장된 출처가 원 전사와 맞지 않습니다" in panel.review_claims.toPlainText()
    finally:
        dispose(panel)


def _x02(env: SimpleNamespace, tmp_path: Path) -> None:
    """G12R-01 P2 and G12R-02: a changed source is unverifiable even though the stored
    basis is transcript, status uncertain and no adapter value (only the problem guard
    keeps it out of the transcript-referenced area)."""
    from recoryn.ui.content import REVIEW_AREA, claim_area

    session, source, summary = _x_world(env, [Claim("X02-CLAIM", ("a",))])
    _tamper(
        env.library, source, lambda body: body["segments"][0].update(text="CHANGED AFTER SUMMARY")
    )
    (view,) = env.content.claim_evidence(summary)
    assert (view["basis"], view["status"], view["provider_basis"]) == (
        "transcript",
        "uncertain",
        None,
    )
    assert view["problem"] == "CONTENT_CLAIM_SOURCE_UNAVAILABLE"
    assert (
        claim_area(view["status"], view["basis"], view["provider_basis"], view["problem"])
        == REVIEW_AREA
    )
    panel, seeks = k_panel(env, session)
    try:
        _no_evidence_path(env, panel, seeks, "X02-CLAIM")
        assert "원 전사를 읽을 수 없거나 요약 당시와 다릅니다" in panel.review_claims.toPlainText()
    finally:
        dispose(panel)


def _x03(env: SimpleNamespace, tmp_path: Path) -> None:
    """G12R-05 P3: a stored status 'supported' is a damaged record, never shown as one."""
    session, source, summary = _x_world(env, [Claim("X03-CLAIM", ("a",))])
    _tamper(env.library, summary, lambda body: body["claims"][0].update(status="supported"))
    panel, seeks = k_panel(env, session)
    try:
        _no_evidence_path(env, panel, seeks, "X03-CLAIM")
        assert "supported" not in all_text(panel)
    finally:
        dispose(panel)


def _x04(env: SimpleNamespace, tmp_path: Path) -> None:
    """G12R-05: malformed records never escape the poll as TypeError."""
    session, source, summary = _x_world(env, [Claim("X04-CLAIM", ("a",)), Claim("X04-OK", ("a",))])
    _tamper(env.library, summary, lambda body: body["claims"][0].update(segment_ids=5))
    panel, seeks = k_panel(env, session)  # load() must not raise
    try:
        _no_evidence_path(env, panel, seeks, "X04-CLAIM")
        assert "X04-OK" in panel.claims.toPlainText()  # the intact claim still shows
        _tamper(env.library, summary, lambda body: body.update(claims=None))
        other = ContentPanel(env.content, Ops())
        other.show()
        try:
            other.load(session)
            assert UNVERIFIABLE in other.review_claims.toPlainText()
            assert anchors(other.claims) == anchors(other.review_claims) == []
        finally:
            dispose(other)
    finally:
        dispose(panel)


def _x05(env: SimpleNamespace, tmp_path: Path) -> None:
    """G12R-03 P5: a focused link keeps its summary and place; one polite notice."""
    session, source, first = _x_world(env, [Claim("FIRST-CLAIM", ("a",))])
    panel, seeks = k_panel(env, session)
    sink = Sink()
    panel.announcer.sink = sink
    try:
        panel.activateWindow()
        panel.claims.setFocus()
        env.app.processEvents()
        press(panel.claims, "Tab")
        focused = a11y.focused_anchor(panel.claims)
        assert focused.startswith("claim:")
        second = env.peer.create_summary(
            session,
            source,
            [Claim("SECOND-CLAIM", ("a",))],
            expected_transcript=source,
            expected_summary=first,
        )
        assert env.content.selection_state(session)["summary_id"] == second
        panel.load(session)
        panel.load(session)  # a second poll: still one notice
        assert "FIRST-CLAIM" in panel.claims.toPlainText()
        assert "SECOND-CLAIM" not in panel.claims.toPlainText()
        assert a11y.focused_anchor(panel.claims) == focused
        assert panel.focusWidget() is panel.claims
        notices = [event for event in sink.events if "새 요약" in event[1]]
        assert len(notices) == 1 and notices[0][2] == "polite" and "그대로" in notices[0][1]
        press(panel.claims, "Enter")
        assert seeks == [("mic", 1000, source)]  # the kept link still works
    finally:
        dispose(panel)


def _x06(env: SimpleNamespace, tmp_path: Path) -> None:
    """G12R-03: focus on the candidate list keeps the shown summary as well."""
    session, source, first = _x_world(env, [Claim("FIRST-CLAIM", ("a",))])
    panel, seeks = k_panel(env, session)
    sink = Sink()
    panel.announcer.sink = sink
    try:
        panel.activateWindow()
        panel.summary_candidates.setFocus()
        env.app.processEvents()
        env.peer.create_summary(
            session,
            source,
            [Claim("SECOND-CLAIM", ("a",))],
            expected_transcript=source,
            expected_summary=first,
        )
        panel.load(session)
        assert "FIRST-CLAIM" in panel.claims.toPlainText()
        assert panel.summary_candidates.currentData() == first
        assert panel.focusWidget() is panel.summary_candidates
        assert len([event for event in sink.events if "새 요약" in event[1]]) == 1
    finally:
        dispose(panel)


def _x07(env: SimpleNamespace, tmp_path: Path) -> None:
    """G12R-04 P8: a late active result while browsing keeps the presented snapshot;
    selecting then conflicts exactly like a race inside the dialog."""
    world = c_world(env, "one", "complete_current")
    session, panel, ops = world["session"], env.panel, env.ops
    ops.mode, ops.held = "now", []
    sink = Sink()
    panel.announcer.sink = sink
    panel.load(session)
    panel.summary_candidates.setCurrentIndex(panel.summary_candidates.findData(world["target"]))
    late = env.peer.create_summary(
        session,
        world["current"],
        [Claim("LATE-CLAIM", ("a",))],
        expected_transcript=world["current"],
        expected_summary=world["base"],
    )
    panel.load(session)
    assert "target" in panel.claims.toPlainText()  # still browsing the same candidate
    assert "선택 요약이 바뀌었습니다" in panel.candidate_info.text()
    assert len([event for event in sink.events if "새 요약" in event[1]]) == 1
    env.modals.reset("Yes")
    press(panel.select_summary_button, "Space")
    env.modals.check()
    assert len(env.modals.opened) == 1
    assert env.content.selection_state(session)["summary_id"] == late  # not replaced
    assert [event for event in sink.events if "충돌" in event[1]][0][2] == "assertive"


def _x08(env: SimpleNamespace, tmp_path: Path) -> None:
    """G12R-06 P4: an unrecorded basis shows the source computed from the revision."""
    session, source, summary = _x_world(env, [Claim("X08-CLAIM", ("a",))])
    _tamper(env.library, summary, lambda body: body["claims"][0].pop("basis"))
    panel, seeks = k_panel(env, session)
    try:
        line = _paragraph(panel.review_claims, "X08-CLAIM")
        assert "출처 기록 없음 · 원 전사에서 계산: 전사 참조" in line
        assert UNVERIFIABLE not in line  # the source itself is intact
    finally:
        dispose(panel)


def _x09(env: SimpleNamespace, tmp_path: Path) -> None:
    """G12R-07: Enter on the select button opens the confirmation (default No)."""
    world = c_world(env, "one", "complete_current")
    session, panel = world["session"], env.panel
    env.ops.mode, env.ops.held = "now", []
    panel.load(session)
    panel.summary_candidates.setCurrentIndex(panel.summary_candidates.findData(world["target"]))
    before = env.content.selection_state(session)
    env.modals.reset("No")
    press(panel.select_summary_button, "Enter")
    env.modals.check()
    assert len(env.modals.opened) == 1 and env.modals.defaults == [(True, True)]
    assert env.content.selection_state(session) == before


def _x10(env: SimpleNamespace, tmp_path: Path) -> None:
    """G12R-07: each area's accessible name carries its count."""
    session, source, summary = _x_world(
        env, [Claim("A1", ("a",)), Claim("A2", ("b",)), Claim("R1", ("u",))]
    )
    panel, _ = k_panel(env, session)
    try:
        assert (
            "2건" in panel.claims.accessibleName() and "1건" in panel.review_claims.accessibleName()
        )
        panel.load("k-empty")
        assert (
            "0건" in panel.claims.accessibleName() and "0건" in panel.review_claims.accessibleName()
        )
    finally:
        dispose(panel)


def _x11(env: SimpleNamespace, tmp_path: Path) -> None:
    """G12R-07: a preparation cancel and an existing Job cancel are said differently."""
    results = {}
    with JobStore(Path(":memory:")) as store:
        for name, busy, jobs in (("prep", True, 0), ("job", False, 1), ("both", True, 1)):
            panel = _empty_panel()
            sink = Sink()
            panel.announcer.sink = sink
            bridge = _bridge(env, store, panel)
            bridge.busy = busy
            session = f"x11-{name}"
            bridge.window.selected_session = lambda session=session: session
            for index in range(jobs):
                job = store.create("summarization", f"{session}-{index}")
                store.bind_session(job.job_id, session)
            bridge.service = SimpleNamespace(cancel_session=lambda session: None)
            bridge.pool = SimpleNamespace(start=lambda task: task.run())
            bridge._tasks, bridge._preparation_cancel = set(), threading.Event()
            try:
                bridge.cancel()
                results[name] = [message for _, message, _ in sink.events]
            finally:
                dispose(panel)
    assert len(results["prep"]) == 1 and "실행 준비(작업 미접수) 취소" in results["prep"][0]
    assert "기존 AI 작업" not in results["prep"][0]
    assert "기존 AI 작업 1건 취소" in results["job"][0] and "실행 준비" not in results["job"][0]
    assert "실행 준비" in results["both"][0] and "기존 AI 작업 1건" in results["both"][0]


def _x12(env: SimpleNamespace, tmp_path: Path) -> None:
    """G12R-07: the same Job meaning is not repeated after other announcements."""
    sink = Sink()
    announcer = a11y.Announcer(sink)
    target = env.panel.job_status
    running = fake_job("RUNNING", 1)
    for _ in range(2):
        announcer.announce(
            "content", target, "RUNNING", "실행 중", version=announcement_version(running)
        )
        announcer.announce("content", target, "CANCEL_REQUESTED", "취소", version=("cancel", 1))
    assert [event[1] for event in sink.events] == ["실행 중", "취소"]
    newer = fake_job("RUNNING", 2)
    announcer.announce("content", target, "RUNNING", "실행 중", version=announcement_version(newer))
    assert len(sink.events) == 3


def _x13(env: SimpleNamespace, tmp_path: Path) -> None:
    """G12R-08: a link of an earlier render in the same session does nothing."""
    world = c_world(env, "one", "complete_current")
    session = world["session"]
    panel, seeks = k_panel(env, session)
    try:
        _, old = link_for(panel, "selected")
        panel.summary_candidates.setCurrentIndex(panel.summary_candidates.findData(world["target"]))
        _, new = link_for(panel, "target")
        assert new != old and old.split("@")[1].split(".")[0] == str(panel.view_generation)
        panel._claim_clicked(old)
        assert seeks == []
        panel._claim_clicked(new)
        assert len(seeks) == 1
    finally:
        dispose(panel)


def _x14(env: SimpleNamespace, tmp_path: Path) -> None:
    """G12R-09 RM3: two missing settings keys are not current (confirmation needed)."""
    from recoryn.content import SummarySelectionExpectation
    from recoryn.domain import StateConflict

    session, source, base = _x_world(env, [Claim("BASE", ("a",))])
    legacy = env.content.create_summary(
        session,
        source,
        [Claim("LEGACY", ("a",))],
        expected_transcript=source,
        expected_summary="0" * 32,
    )
    state = env.content.selection_state(session)
    assert (
        state["summary_settings_key"] is None
        and env.content.summary(legacy).get("settings_key") is None
    )
    snapshot = SummarySelectionExpectation.from_state(state)
    with pytest.raises(StateConflict, match="CONTENT_SUMMARY_OUTDATED_CONFIRMATION_REQUIRED"):
        env.content.select_summary_candidate(session, legacy, expected=snapshot)
    panel = env.panel
    env.ops.mode, env.ops.held = "now", []
    panel.load(session)
    index = panel.summary_candidates.findData(legacy)
    assert "설정 비교 불명" in panel.summary_candidates.itemText(index)
    panel.summary_candidates.setCurrentIndex(index)
    env.modals.reset("No")
    press(panel.select_summary_button, "Space")
    env.modals.check()
    assert OUTDATED_NOTICE in env.modals.opened[0][2]


def _x15(env: SimpleNamespace, tmp_path: Path) -> None:
    """G12R-09 RM4: a held (auto-repeating) key runs a command once, not repeatedly."""
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent

    panel, _ = k_panel(env)
    counts = {"cancel": 0}
    panel.cancelRequested.connect(lambda: counts.__setitem__("cancel", counts["cancel"] + 1))
    none = Qt.KeyboardModifier.NoModifier
    try:
        for key in (Qt.Key.Key_Return, Qt.Key.Key_Space):
            QApplication.sendEvent(
                panel.cancel_button, QKeyEvent(QEvent.Type.KeyPress, key, none, "", False)
            )
            for _ in range(3):
                QApplication.sendEvent(
                    panel.cancel_button, QKeyEvent(QEvent.Type.KeyPress, key, none, "", True)
                )
            QApplication.sendEvent(
                panel.cancel_button, QKeyEvent(QEvent.Type.KeyRelease, key, none, "", False)
            )
        assert counts["cancel"] == 2  # one per real press
    finally:
        dispose(panel)


def _x16(env: SimpleNamespace, tmp_path: Path) -> None:
    """G12R-09 RM6 as a semantic row: another session's candidate is refused."""
    from recoryn.content import SummarySelectionExpectation
    from recoryn.domain import ValidationError

    session_a, _, _ = _x_world(env, [Claim("A", ("a",))])
    session_b, source_b, _ = _x_world(env, [Claim("B", ("a",))])
    foreign = env.content.create_summary(
        session_b,
        source_b,
        [Claim("B2", ("a",))],
        expected_transcript=source_b,
        expected_summary="0" * 32,
    )
    snapshot = SummarySelectionExpectation.from_state(env.content.selection_state(session_a))
    before = (env.content.selection_state(session_a), env.content.selection_state(session_b))
    with pytest.raises(ValidationError, match="^CONTENT_SELECTION_SESSION_MISMATCH$"):
        env.content.select_summary_candidate(
            session_a, foreign, expected=snapshot, allow_outdated=True
        )
    assert (
        env.content.selection_state(session_a),
        env.content.selection_state(session_b),
    ) == before


# G-P12b / G12R-10: independent axes and hand-written UI/storage expectations.
Y_F = list(
    product(
        ("claims", "review_claims", "summary_candidates"),
        (True, False),
        ("stay", "leave", "select"),
    )
)
Y_B = list(product(("inside", "outside"), ("none", "id", "aba")))
Y_D = list(product(("select", "snapshot", "summary"), ("intent", "key", "validation")))
Y = (
    [("focus", *row) for row in Y_F]
    + [("browse", *row) for row in Y_B]
    + [("denied", *row) for row in Y_D]
)
Y_IDS = [f"G12-Y-{n:02}" for n in range(1, 34)]


def _y_storage(env: SimpleNamespace, session: str) -> tuple[Any, ...]:
    """Read raw persisted bytes and counters, including when public reads are denied."""
    db = env.content._db
    return (
        tuple(
            tuple(row)
            for row in db.execute("SELECT * FROM content_selections WHERE session_id=?", (session,))
        ),
        tuple(
            tuple(row)
            for row in db.execute(
                "SELECT revision_id,body,sha256 FROM content_revisions WHERE session_id=? "
                "ORDER BY revision_id",
                (session,),
            )
        ),
        env.content._db.total_changes,
        env.peer._db.total_changes,
        env.jobs._db.total_changes,
    )


def _y_focus(env: SimpleNamespace, panel: ContentPanel, name: str) -> None:
    panel.activateWindow()
    widget = getattr(panel, name)
    widget.setFocus()
    env.app.processEvents()
    if name == "summary_candidates":
        press(widget, "Arrow")  # the sole initial item cannot change
    else:
        press(widget, "Tab")  # enter an actual evidence link
    env.app.processEvents()
    assert panel.focusWidget() is widget


def _y_choose(env: SimpleNamespace, panel: ContentPanel, target: str) -> None:
    combo = panel.summary_candidates
    panel.activateWindow()
    combo.setFocus()
    env.app.processEvents()
    wanted = combo.findData(target)
    assert wanted >= 0
    while combo.currentIndex() != wanted:
        key = Qt.Key.Key_Down if combo.currentIndex() < wanted else Qt.Key.Key_Up
        QTest.keyClick(combo, key)
    assert combo.currentData() == target


@pytest.mark.parametrize("row", Y, ids=Y_IDS)
def test_y_followup_rows(
    env: SimpleNamespace, row: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    if row[0] == "focus":
        _y_focus_hold(env, *row[1:])
    elif row[0] == "browse":
        _y_explicit_browse(env, *row[1:])
    else:
        _y_denied(env, monkeypatch, *row[1:])


def _y_focus_hold(env: SimpleNamespace, area: str, complete: bool, action: str) -> None:
    session, source, first = _x_world(
        env, [Claim("FIRST-AUDIO", ("a",)), Claim("FIRST-REVIEW", ("u",))]
    )
    if not complete:
        # A legacy/damaged selected partial still must never become selectable.
        _tamper(env.library, first, lambda body: body.update(complete=False))
    ops = Ops()
    panel, seeks = k_panel(env, session, ops)
    sink = Sink()
    panel.announcer.sink = sink
    try:
        snapshot = panel._candidate_snapshot
        _y_focus(env, panel, area)
        widget = getattr(panel, area)
        anchor = a11y.focused_anchor(widget) if isinstance(widget, QTextBrowser) else None
        second = env.peer.create_summary(
            session,
            source,
            [Claim("SECOND", ("a",))],
            expected_transcript=source,
            expected_summary=first,
        )
        before = _y_storage(env, session)
        panel.load(session)
        panel.load(session)
        assert "FIRST-AUDIO" in panel.claims.toPlainText()
        assert panel.focusWidget() is widget
        if isinstance(widget, QTextBrowser):
            assert a11y.focused_anchor(widget) == anchor
        assert "지금 보던 요약 · 선택 요약 아님" in panel.candidate_info.text()
        assert "선택된 요약입니다" not in panel.candidate_info.text()
        assert panel.select_summary_button.isEnabled() is complete
        assert panel._candidate_snapshot == snapshot
        assert _y_storage(env, session) == before and seeks == []
        assert len([event for event in sink.events if "새 요약" in event[1]]) == 1
        if action == "leave":
            panel.search.setFocus()
            env.app.processEvents()
            press(panel.search, "Arrow")
            assert panel.focusWidget() is panel.search
            panel.load(session)
            assert "SECOND" in panel.claims.toPlainText()
            assert "FIRST-AUDIO" not in panel.claims.toPlainText()
            assert panel.summary_candidates.currentData() == second
            assert panel._candidate_snapshot.summary_id == second
            assert panel._candidate_snapshot.summary_version == snapshot.summary_version + 1
            assert panel.candidate_info.text().startswith("선택된 요약입니다")
            assert not panel.select_summary_button.isEnabled()
        elif action == "select":
            env.modals.reset("Yes")
            press(panel.select_summary_button, "Enter")
            env.modals.check()
            assert len(env.modals.opened) == int(complete)
            assert ops.calls == int(complete)
            conflicts = [event for event in sink.events if "충돌" in event[1]]
            assert len(conflicts) == int(complete)
            if complete:
                assert conflicts[0][2] == "assertive"
                # The conflict refreshed the snapshot. A fresh keyboard browse then
                # requires a second confirmation; No must leave the active untouched.
                _y_choose(env, panel, first)
                env.modals.reset("No")
                press(panel.select_summary_button, "Space")
                env.modals.check()
                assert len(env.modals.opened) == 1 and ops.calls == 1
        assert _y_storage(env, session) == before
        assert env.content.selection_state(session)["summary_id"] == second
        assert seeks == []
    finally:
        dispose(panel)


def _y_explicit_browse(env: SimpleNamespace, focus: str, change: str) -> None:
    world = c_world(env, "one", "complete_current")
    session = world["session"]
    panel, seeks = k_panel(env, session)
    try:
        _y_choose(env, panel, world["target"])
        snapshot = panel._candidate_snapshot
        if focus == "inside":
            _y_focus(env, panel, "claims")
        else:
            panel.search.setFocus()
            env.app.processEvents()
            press(panel.search, "Arrow")
            assert panel.focusWidget() is panel.search
        if change != "none":
            race(env, world, "summary_id" if change == "id" else "summary_aba")
        before = _y_storage(env, session)
        panel.load(session)
        panel.load(session)
        assert "target" in panel.claims.toPlainText()
        assert panel.summary_candidates.currentData() == world["target"]
        assert panel._candidate_snapshot == snapshot
        assert "선택된 요약입니다" not in panel.candidate_info.text()
        assert panel.select_summary_button.isEnabled()
        assert _y_storage(env, session) == before and seeks == []
    finally:
        dispose(panel)


def _y_denied(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, stage: str, error: str
) -> None:
    import sys

    session, source, base = _x_world(env, [Claim("BASE", ("a",))])
    first = env.content.create_summary(
        session, source, [Claim("BROWSED", ("a",))], expected_summary="z" * 32
    )
    ops = Ops()
    panel, seeks = k_panel(env, session, ops)
    sink = Sink()
    panel.announcer.sink = sink
    held = job = None
    try:
        _y_choose(env, panel, first)
        env.peer.create_summary(
            session,
            source,
            [Claim("LATE", ("a",))],
            expected_transcript=source,
            expected_summary=base,
        )
        panel.load(session)
        previous = (
            panel._browsed_summary,
            panel._candidate_snapshot,
            panel.claims.toPlainText(),
            panel.review_claims.toPlainText(),
        )
        errors: list[str] = []
        monkeypatch.setattr(sys, "excepthook", lambda *args: errors.append(str(args[1])))
        if error == "intent":
            _prepare_fixture_history(env)
            job = env.jobs.create("summarization", f"y-reader-{next(_serial)}")
            env.jobs.bind_session(job.job_id, session)
            held = env.jobs.claim(job.job_id, "reader")
            assert env.library.delete_session(session)["state"] == "DELETE_PENDING"
        else:

            def denied(*args: Any, **kwargs: Any) -> Any:
                raise (KeyError if error == "key" else ValidationError)("G12_Y_CANARY")

            monkeypatch.setattr(
                env.content, "selection_state" if stage == "snapshot" else "summary", denied
            )
        before = _y_storage(env, session)
        env.modals.reset("Yes")
        if stage == "select":
            for key in ("Enter", "Space"):
                press(panel.select_summary_button, key)
        else:
            combo = panel.summary_candidates
            index = combo.currentIndex()
            key = Qt.Key.Key_Up if index > 0 else Qt.Key.Key_Down
            for _ in range(2):
                combo.setFocus()
                QTest.keyClick(combo, key)
                env.app.processEvents()
                assert combo.currentData() == first
        assert errors == []
        assert (
            panel._browsed_summary,
            panel._candidate_snapshot,
            panel.claims.toPlainText(),
            panel.review_claims.toPlainText(),
        ) == previous
        assert "세션 삭제 진행 중이거나 요약을 읽을 수 없어 선택할 수 없습니다" in (
            panel.candidate_info.text()
        )
        assert "G12_Y_CANARY" not in panel.candidate_info.text()
        notices = [event for event in sink.events if "선택할 수 없습니다" in event[1]]
        assert len(notices) == 1 and notices[0][2] == "assertive"
        assert ops.calls == 0 and env.modals.opened == []
        assert _y_storage(env, session) == before and seeks == []
    finally:
        if held is not None:
            env.jobs.fail(job.job_id, held.attempt_id, held.fence, "Y_DONE")
        dispose(panel)
