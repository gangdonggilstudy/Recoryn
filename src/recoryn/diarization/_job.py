"""Windows owned-child lifetime guard, independent of the child's native GIL.

The child must wait on its start gate until attach succeeds. The handle is
non-inheritable and stays solely with the owner; parent exit closes it in the OS.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import Any

from recoryn.providers import ProviderError


class _Limits(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IO(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_uint64)
        for name in (
            "ReadOperationCount",
            "WriteOperationCount",
            "OtherOperationCount",
            "ReadTransferCount",
            "WriteTransferCount",
            "OtherTransferCount",
        )
    ]


class _Extended(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _Limits),
        ("IoInfo", _IO),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def _api() -> Any:
    if sys.platform != "win32":
        raise ProviderError("DIARIZATION_PLATFORM_UNSUPPORTED")
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    api.CreateJobObjectW.restype = wintypes.HANDLE
    api.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    api.SetInformationJobObject.restype = wintypes.BOOL
    api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    api.OpenProcess.restype = wintypes.HANDLE
    api.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    api.AssignProcessToJobObject.restype = wintypes.BOOL
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.CloseHandle.restype = wintypes.BOOL
    return api


class ChildJob:
    """One child, 1 GiB commit cap, kill on owner-handle close; fail closed."""

    def __init__(self) -> None:
        self._api: Any = None
        self._handle: Any = None

    def attach(self, pid: int) -> None:
        if type(pid) is not int or pid <= 0 or self._handle is not None:
            raise ProviderError("DIARIZATION_GUARD_INVALID")
        api = _api()
        job = api.CreateJobObjectW(None, None)
        if not job:
            raise ProviderError("DIARIZATION_GUARD_FAILED")
        process = None
        try:
            limits = _Extended()
            # KILL_ON_JOB_CLOSE | PROCESS_MEMORY | ACTIVE_PROCESS (no descendants).
            limits.BasicLimitInformation.LimitFlags = 0x2000 | 0x100 | 0x8
            limits.BasicLimitInformation.ActiveProcessLimit = 1
            limits.ProcessMemoryLimit = 1024 * 1024 * 1024
            if not api.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                raise ProviderError("DIARIZATION_GUARD_FAILED")
            process = api.OpenProcess(0x100 | 0x1, False, pid)
            if not process or not api.AssignProcessToJobObject(job, process):
                raise ProviderError("DIARIZATION_GUARD_FAILED")
            self._api, self._handle = api, job
            job = None
        finally:
            if process:
                api.CloseHandle(process)
            if job:
                api.CloseHandle(job)

    def close(self) -> None:
        if self._handle is not None:
            if not self._api.CloseHandle(self._handle):
                raise ProviderError("DIARIZATION_GUARD_CLOSE_FAILED")
            self._handle = None
