"""Thin Windows power notification adapter; no blocking work in the filter.

Sources: https://learn.microsoft.com/en-us/windows/win32/power/wm-powerbroadcast
https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-msg
https://doc.qt.io/qtforpython-6/PySide6/QtCore/QAbstractNativeEventFilter.html
"""

from __future__ import annotations

import ctypes
import sys
from collections.abc import Callable
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QByteArray


class WindowsPowerFilter(QAbstractNativeEventFilter):
    def __init__(self, callback: Callable[[str], None]) -> None:
        super().__init__()
        self.callback = callback

    def nativeEventFilter(
        self,
        eventType: QByteArray | bytes | bytearray | memoryview,
        message: int,
    ) -> tuple[bool, int]:
        kind = eventType.data() if isinstance(eventType, QByteArray) else bytes(eventType)
        if sys.platform != "win32" or kind not in {
            b"windows_generic_MSG",
            b"windows_dispatcher_MSG",
        }:
            return False, 0
        if message:
            packet = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents
            if packet.message == 0x218:
                if packet.wParam == 4:
                    self.callback("suspend")
                elif packet.wParam in {7, 18}:
                    self.callback("resume")
        # Let Qt and the window procedure perform their usual power handling.
        return False, 0
