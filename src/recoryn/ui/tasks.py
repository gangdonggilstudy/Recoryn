"""Finite background operations with queued Qt result delivery."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from recoryn.app.recording import RecordingError
from recoryn.domain import StateConflict, ValidationError


class TaskSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)


class Task(QRunnable):
    SAFE_CODES = frozenset(
        {
            "CONSENT_REQUIRED",
            "BUDGET_REQUIRED",
            "BUDGET_EXCEEDED",
            "CANCELLED",
            "REMOTE_OUTCOME_UNKNOWN",
            "DEPENDENCY_MISSING",
            "MODEL_MISSING",
            "RESOURCE_EXHAUSTED",
            "CAPABILITY_UNSUPPORTED",
            "LOCAL_EXECUTION_UNVERIFIED",
            "DEVICE_UNAVAILABLE",
            "DEVICE_ACCESS_DENIED",
            "FORMAT_CHANGED",
            "STOP_TIMEOUT",
            "DEVICE_STOP_FAILED",
            "DEVICE_RELEASE_FAILED",
            "CAPTURE_ACK_PENDING",
            "WRITER_ACK_PENDING",
            "MODEL_DOWNLOAD_ACK_PENDING",
            "INFERENCE_ACK_PENDING",
            "CAPTURE_START_FAILED_ACK_PENDING",
            "CAPTURE_START_FAILED_MEDIA_PRESERVED",
            "MODEL_DOWNLOAD_CANCELLED",
            "MODEL_CHECKSUM_MISMATCH",
            "LOCAL_MODEL_REQUIRED",
            "AI_MODEL_CHANGE_REQUIRES_IDLE",
        }
    )

    def __init__(self, operation: Callable[[], Any]) -> None:
        super().__init__()
        self.signals = TaskSignals()
        self.operation = operation

    @Slot()
    def run(self) -> None:
        try:
            result = self.operation()
        except Exception as error:
            # Device paths, HTTP response bodies, and credentials stay out of UI.
            code = getattr(error, "code", None)
            if (
                isinstance(error, (StateConflict, ValidationError, RecordingError))
                and len(error.args) == 1
            ):
                candidate = error.args[0]
                if isinstance(candidate, str) and candidate in self.SAFE_CODES:
                    code = candidate
            if not isinstance(code, str) or code not in self.SAFE_CODES:
                code = "OPERATION_FAILED_MEDIA_PRESERVED"
            self.signals.failed.emit(code)
        else:
            self.signals.finished.emit(result)
