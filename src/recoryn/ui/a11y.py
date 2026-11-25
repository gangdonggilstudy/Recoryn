"""Keyboard activation, modal focus return and accessibility announcements (G-P12).

This adapter never grants, revokes, cancels or selects anything by itself: it routes a
validated key press to an existing UI command, returns focus only where it is still safe,
and posts announcements on the GUI thread. Qt event emission is checked by tests; real
screen-reader speech (Narrator) is an external gate.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import shiboken6
from PySide6.QtCore import QEvent, QObject, Qt, QThread, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QAbstractButton, QApplication, QMessageBox, QWidget

POLITE, ASSERTIVE = "polite", "assertive"
# G12 section 5.2 and amendment 2-1: what is announced and how urgently. Wording comes
# from the callers (G-P07 status text); this table never redefines a reason.
ANNOUNCEMENTS = {
    "PREPARATION_BLOCKED": ASSERTIVE,
    "QUEUED": POLITE,
    "RUNNING": POLITE,
    "CANCEL_REQUESTED": POLITE,
    "LOCAL_ACK": POLITE,
    "REMOTE_UNKNOWN": ASSERTIVE,
    "REVOCATION_PERSISTED": POLITE,
    "SELECTION_CONFLICT": ASSERTIVE,
    "BLOCKED": ASSERTIVE,
    "BACKOFF": POLITE,
    "ABANDONED": POLITE,
    "FAILED": ASSERTIVE,
    # FIX1 G12R-03: a new active summary arrived (the view may be kept as it was).
    "NEW_ACTIVE_SUMMARY": POLITE,
}
ACTIVATION_KEYS = (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space)


def alive(widget: object) -> bool:
    """A Qt object whose C++ side still exists (never touch a destroyed widget)."""
    return widget is not None and shiboken6.isValid(widget)


def qt_announce(target: QObject, message: str, politeness: str) -> None:
    from PySide6.QtGui import QAccessible, QAccessibleAnnouncementEvent

    if not alive(target):
        return
    event = QAccessibleAnnouncementEvent(target, message)
    event.setPoliteness(
        QAccessible.AnnouncementPoliteness.Assertive
        if politeness == ASSERTIVE
        else QAccessible.AnnouncementPoliteness.Polite
    )
    QAccessible.updateAccessibility(event)


class Announcer(QObject):
    """GUI-thread announcements keyed by (generation, version, kind) per scope.

    A key already announced in the current generation (an unchanged poll, or the same
    meaning again after other announcements in between) is silent; only a new meaning
    is announced once; a callback from an earlier generation (old session/view) is
    dropped. Calls from a worker thread are queued to the GUI thread. Announcing never
    moves focus.
    """

    MEMORY = 256  # meanings remembered per scope and generation

    _posted = Signal(object)

    def __init__(self, sink: Callable[[QObject, str, str], None] | None = None) -> None:
        super().__init__()
        self.sink = sink or qt_announce
        self._generations: dict[str, int] = {}
        self._seen: dict[str, dict[tuple[int, object, str], None]] = {}
        self._posted.connect(self._deliver)

    def generation(self, scope: str) -> int:
        return self._generations.get(scope, 0)

    def advance(self, scope: str) -> int:
        value = self.generation(scope) + 1
        self._generations[scope] = value
        self._seen.pop(scope, None)
        return value

    def announce(
        self,
        scope: str,
        target: QObject,
        kind: str,
        message: str,
        *,
        version: object,
        generation: int | None = None,
    ) -> None:
        if kind not in ANNOUNCEMENTS:
            raise ValueError("unknown announcement kind")
        request = (
            scope,
            target,
            kind,
            message,
            version,
            self.generation(scope) if generation is None else generation,
        )
        application = QApplication.instance()
        if application is not None and QThread.currentThread() is not application.thread():
            self._posted.emit(request)  # queued: Qt objects stay on the GUI thread
        else:
            self._deliver(request)

    def _deliver(self, request: tuple[Any, ...]) -> bool:
        scope, target, kind, message, version, generation = request
        if generation != self.generation(scope):
            return False
        key = (generation, version, kind)
        seen = self._seen.setdefault(scope, {})
        if key in seen:
            return False
        seen[key] = None
        while len(seen) > self.MEMORY:
            seen.pop(next(iter(seen)))
        self.sink(target, message, ANNOUNCEMENTS[kind])
        return True


class KeyActivation(QObject):
    """Enter/Space on one widget run its command exactly once per key press.

    The press is consumed so a native activation never runs as well (no double). Tab
    and arrow keys are not touched. ``when`` decides whether the command may run; a
    refused press is still consumed for Enter/Space so nothing else is activated.
    """

    def __init__(
        self,
        widget: QWidget,
        command: Callable[[], object],
        *,
        when: Callable[[QKeyEvent], bool] | None = None,
        keys: tuple[Qt.Key, ...] = ACTIVATION_KEYS,
    ) -> None:
        super().__init__(widget)
        self.command, self.when, self.keys = command, when, keys
        widget.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt API
        if event.type() not in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            return False
        assert isinstance(event, QKeyEvent)
        if event.key() not in self.keys or event.modifiers() not in (
            Qt.KeyboardModifier.NoModifier,
            Qt.KeyboardModifier.KeypadModifier,
        ):
            return False
        if not (isinstance(watched, QWidget) and watched.isEnabled() and watched.isVisible()):
            return True  # a disabled or hidden target runs nothing, natively or ours
        if self.when is not None and not self.when(event):
            return False  # not ours (e.g. an editor or a non-link Space): native behavior
        if event.type() == QEvent.Type.KeyPress and not event.isAutoRepeat():
            self.command()
        return True


def activate_button(button: QAbstractButton) -> KeyActivation:
    """Enter and Space both click an enabled, visible button once."""
    return KeyActivation(
        button,
        lambda: button.click() if button.isEnabled() and button.isVisible() else None,
    )


class FocusReturn:
    """Return focus to an opener after a modal or a late completion, only when safe.

    Safe means: the opener still exists, is visible and enabled, the request is still
    current (``still_current``) and the user has not moved focus elsewhere since the
    modal closed. Otherwise a live, visible fallback (a safe navigation spot) is used,
    or the current focus is kept. Focus is read per window: right after a modal closes
    the OS may not have reactivated the parent yet, but its focus child is already
    the widget that will receive the keys.
    """

    def __init__(
        self,
        opener: QWidget | None,
        still_current: Callable[[], bool] = lambda: True,
        window: QWidget | None = None,
    ) -> None:
        self.opener = opener
        self.still_current = still_current
        if window is None and opener is not None and alive(opener):
            window = opener.window()
        self.window = window
        self.after_modal: QWidget | None = None

    def focused(self) -> QWidget | None:
        current = QApplication.focusWidget()
        if alive(self.window):
            assert self.window is not None
            if alive(current) and current is not None and current.window() is self.window:
                return current
            child = self.window.focusWidget()
            return child if alive(child) else None
        return current if alive(current) else None

    def modal_closed(self) -> None:
        self.after_modal = self.focused()

    def restore(self, fallback: QWidget | None = None) -> QWidget | None:
        current = self.focused()
        opener = self.opener if alive(self.opener) else None
        if current is not None and current is not opener and current is not self.after_modal:
            return current  # the user moved on: a late completion never steals focus
        if (
            opener is not None
            and opener.isVisible()
            and opener.isEnabled()
            and self.still_current()
        ):
            opener.setFocus(Qt.FocusReason.OtherFocusReason)
            return opener
        if (
            fallback is not None
            and alive(fallback)
            and fallback.isVisible()
            and fallback.isEnabled()
        ):
            fallback.setFocus(Qt.FocusReason.OtherFocusReason)
            return fallback
        return current


def confirm(
    parent: QWidget,
    title: str,
    text: str,
    *,
    opener: QWidget | None = None,
    still_current: Callable[[], bool] = lambda: True,
    fallback: QWidget | None = None,
    restore: bool = True,
) -> tuple[bool, FocusReturn]:
    """A Yes/No question whose default and Escape are No (rejection never grants).

    The static ``QMessageBox.question`` is kept so existing callers and tests that
    replace it keep working. The opener defaults to the widget focused when the
    question opens. Focus returns to it only when still safe; a caller completing
    later passes ``restore=False`` and calls ``restore()`` then.
    """
    window = parent.window() if alive(parent) else None
    if opener is None:
        opener = FocusReturn(None, window=window).focused()
    focus = FocusReturn(opener, still_current, window)
    accepted = (
        QMessageBox.question(
            parent,
            title,
            text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        == QMessageBox.StandardButton.Yes
    )
    focus.modal_closed()
    if restore:
        focus.restore(fallback)
    return accepted, focus


def focused_anchor(view: Any) -> str:
    """The href of the link that has keyboard focus in a text browser, else "".

    Keyboard link focus (Tab or Shift+Tab) selects exactly the anchor text, in either
    direction; a caret or a partial selection is not a focused link.
    """
    from PySide6.QtGui import QTextCursor

    cursor = view.textCursor()
    if not cursor.hasSelection():
        return ""
    first = QTextCursor(cursor)
    first.setPosition(cursor.selectionStart() + 1)
    last = QTextCursor(cursor)
    last.setPosition(cursor.selectionEnd())
    href = first.charFormat().anchorHref()
    return href if href and last.charFormat().anchorHref() == href else ""


def name(widget: QWidget, accessible_name: str, description: str = "") -> QWidget:
    widget.setAccessibleName(accessible_name)
    if description:
        widget.setAccessibleDescription(description)
    return widget
