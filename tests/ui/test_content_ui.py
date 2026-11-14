from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit

from recoryn.content import ContentStore, Segment
from recoryn.storage import Library
from recoryn.ui.content import ContentPanel

pytestmark = pytest.mark.ui


def operation(action, done, *, failed=None):
    done(action())
    return True


def test_incoming_result_cannot_destroy_live_editor_and_losing_edit_is_preserved(tmp_path: Path):
    app = QApplication.instance() or QApplication([])
    with Library(tmp_path / "library") as library, ContentStore(library) as store:
        library.create_session("s")
        original = store.create_transcript("s", [Segment("a", 0, 500, "before")])
        panel = ContentPanel(store, operation)
        panel.load("s")
        panel.show()
        try:
            item = panel.table.item(0, 1)
            panel.table.editItem(item)
            app.processEvents()
            editor = panel.table.findChild(QLineEdit)
            assert editor is not None
            editor.setText("사용자 작성 중")
            editor.setSelection(0, 3)
            latest = store.create_transcript(
                "s", [Segment("b", 0, 500, "later model result")], expected_active=original
            )
            panel.load("s")
            assert panel.table.findChild(QLineEdit) is editor
            assert editor.text() == "사용자 작성 중" and editor.selectedText() == "사용자"
            assert panel.revision["revision_id"] == original
            assert panel._expected_active == original
            QTest.keyClick(editor, Qt.Key.Key_Return)
            app.processEvents()
            assert store.active_transcript("s")["revision_id"] == latest
            candidate = panel.revision
            assert candidate["kind"] == "edited"
            assert candidate["parent_revision_id"] == original
            assert candidate["segments"][0]["text"] == "사용자 작성 중"
            assert candidate["segments"][0]["provenance"] == "user_assertion"
            assert "후보" in panel.status.text()
            assert store.transcript(original)["segments"][0]["text"] == "before"
        finally:
            panel.close()
            panel.deleteLater()
            app.processEvents()


def test_refresh_preserves_browsed_revision_filter_and_selection(tmp_path: Path):
    app = QApplication.instance() or QApplication([])
    with Library(tmp_path / "library") as library, ContentStore(library) as store:
        library.create_session("s")
        original = store.create_transcript("s", [Segment("a", 0, 500, "searchable")])
        current = store.create_transcript(
            "s", [Segment("b", 0, 500, "current")], expected_active=original
        )
        panel = ContentPanel(store, operation)
        try:
            panel.load("s")
            panel.versions.setCurrentIndex(panel.versions.findData(original))
            panel.search.setText("search")
            panel.table.selectRow(0)
            panel.load("s")
            assert panel.revision["revision_id"] == original
            assert panel.versions.currentData() == original
            assert panel.search.text() == "search"
            assert panel.table.currentRow() == 0
            assert not panel.table.isRowHidden(0)
            assert store.active_transcript("s")["revision_id"] == current
        finally:
            panel.close()
            panel.deleteLater()
            app.processEvents()


def test_busy_ai_cannot_discard_unsaved_edit_on_next_refresh(tmp_path: Path):
    app = QApplication.instance() or QApplication([])
    with Library(tmp_path / "library") as library, ContentStore(library) as store:
        library.create_session("s")
        original = store.create_transcript("s", [Segment("a", 0, 500, "before")])
        panel = ContentPanel(store, lambda *args, **kwargs: False)
        try:
            panel.load("s")
            panel.table.item(0, 1).setText("입력 보존")
            assert panel._unsaved_edit
            latest = store.create_transcript(
                "s", [Segment("b", 0, 500, "later")], expected_active=original
            )
            panel.load("s")
            assert panel.table.item(0, 1).text() == "입력 보존"
            panel.operation = operation
            panel._retry_edit()
            assert not panel._unsaved_edit
            assert panel.revision["segments"][0]["text"] == "입력 보존"
            assert panel.revision["parent_revision_id"] == original
            assert store.active_transcript("s")["revision_id"] == latest
        finally:
            panel.close()
            panel.deleteLater()
            app.processEvents()
