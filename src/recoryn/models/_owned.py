"""Windows server ownership: suspended creation, private Job, exact listener PID.

https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-assignprocesstojobobject
https://learn.microsoft.com/en-us/windows/win32/api/iphlpapi/nf-iphlpapi-getextendedtcptable
No device, model, process or socket is opened at import time.
"""

from __future__ import annotations

import ctypes
import socket
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any

from recoryn.domain import StateConflict


class _Startup(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        *[
            (name, wintypes.DWORD)
            for name in (
                "dwX",
                "dwY",
                "dwXSize",
                "dwYSize",
                "dwXCountChars",
                "dwYCountChars",
                "dwFillAttribute",
                "dwFlags",
            )
        ],
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.c_void_p),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class _ProcessInfo(ctypes.Structure):
    _fields_ = [
        ("process", wintypes.HANDLE),
        ("thread", wintypes.HANDLE),
        ("pid", wintypes.DWORD),
        ("tid", wintypes.DWORD),
    ]


class _Limits(ctypes.Structure):
    _fields_ = [
        ("process_time", ctypes.c_int64),
        ("job_time", ctypes.c_int64),
        ("flags", wintypes.DWORD),
        ("working_min", ctypes.c_size_t),
        ("working_max", ctypes.c_size_t),
        ("process_limit", wintypes.DWORD),
        ("affinity", ctypes.c_size_t),
        ("priority", wintypes.DWORD),
        ("scheduling", wintypes.DWORD),
    ]


class _IO(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_uint64)
        for name in (
            "read_count",
            "write_count",
            "other_count",
            "read_bytes",
            "write_bytes",
            "other_bytes",
        )
    ]


class _Extended(ctypes.Structure):
    _fields_ = [
        ("basic", _Limits),
        ("io", _IO),
        *[
            (name, ctypes.c_size_t)
            for name in (
                "process_memory",
                "job_memory",
                "peak_process",
                "peak_job",
            )
        ],
    ]


class _Accounting(ctypes.Structure):
    _fields_ = [
        *[
            (name, ctypes.c_int64)
            for name in (
                "user",
                "kernel",
                "period_user",
                "period_kernel",
            )
        ],
        *[
            (name, wintypes.DWORD)
            for name in (
                "faults",
                "total",
                "active",
                "terminated",
            )
        ],
    ]


def _api() -> Any:
    if sys.platform != "win32":
        raise StateConflict("OLLAMA_OWNERSHIP_UNSUPPORTED")
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    definitions = {
        "CreateJobObjectW": ([ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
        "SetInformationJobObject": (
            [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD],
            wintypes.BOOL,
        ),
        "QueryInformationJobObject": (
            [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p],
            wintypes.BOOL,
        ),
        "AssignProcessToJobObject": ([wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
        "TerminateJobObject": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
        "CreateProcessW": (
            [
                wintypes.LPCWSTR,
                wintypes.LPWSTR,
                ctypes.c_void_p,
                ctypes.c_void_p,
                wintypes.BOOL,
                wintypes.DWORD,
                ctypes.c_void_p,
                wintypes.LPCWSTR,
                ctypes.POINTER(_Startup),
                ctypes.POINTER(_ProcessInfo),
            ],
            wintypes.BOOL,
        ),
        "ResumeThread": ([wintypes.HANDLE], wintypes.DWORD),
        "WaitForSingleObject": ([wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
        "GetExitCodeProcess": ([wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
        "TerminateProcess": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
        "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
        "OpenProcess": ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
        "IsProcessInJob": (
            [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)],
            wintypes.BOOL,
        ),
    }
    for name, (arguments, result) in definitions.items():
        getattr(api, name).argtypes = arguments
        getattr(api, name).restype = result
    return api


class OwnedServer:
    """Only our new server and its descendants; parent death closes this private Job."""

    def __init__(
        self,
        executable: Path,
        environment: dict[str, str],
        *,
        arguments: tuple[str, ...] = ("serve",),
    ) -> None:
        self._api = _api()
        self._job: Any = None
        self._process: Any = None
        self._returncode: int | None = None
        self._exit_handles: dict[int, Any] = {}
        self.pid = 0
        api = self._api
        job = api.CreateJobObjectW(None, None)
        if not job:
            raise StateConflict("OLLAMA_OWNERSHIP_FAILED")
        info = _ProcessInfo()
        try:
            limits = _Extended()
            limits.basic.flags = 0x2000 | 0x8  # KILL_ON_JOB_CLOSE | ACTIVE_PROCESS
            limits.basic.process_limit = 16
            if not api.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                raise StateConflict("OLLAMA_OWNERSHIP_FAILED")
            startup = _Startup()
            startup.cb = ctypes.sizeof(startup)
            startup.dwFlags = 1  # STARTF_USESHOWWINDOW, SW_HIDE; no inherited handles.
            command = ctypes.create_unicode_buffer(
                subprocess.list2cmdline([str(executable), *arguments])
            )
            block = ctypes.create_unicode_buffer(
                "\0".join(
                    f"{key}={value}"
                    for key, value in sorted(environment.items(), key=lambda item: item[0].upper())
                )
                + "\0\0"
            )
            if not api.CreateProcessW(
                str(executable),
                command,
                None,
                None,
                False,
                0x4 | 0x400 | 0x08000000,  # SUSPENDED | UNICODE_ENVIRONMENT | NO_WINDOW
                block,
                str(executable.parent),
                ctypes.byref(startup),
                ctypes.byref(info),
            ):
                raise StateConflict("OLLAMA_LAUNCH_FAILED")
            if not api.AssignProcessToJobObject(job, info.process):
                raise StateConflict("OLLAMA_OWNERSHIP_FAILED")
            if api.ResumeThread(info.thread) == 0xFFFFFFFF:
                raise StateConflict("OLLAMA_LAUNCH_FAILED")
            self._job, self._process, self.pid = job, info.process, int(info.pid)
        except BaseException:
            if info.process:
                api.TerminateProcess(info.process, 1)
                api.WaitForSingleObject(info.process, 5000)
                api.CloseHandle(info.process)
            api.CloseHandle(job)
            raise
        finally:
            if info.thread:
                api.CloseHandle(info.thread)

    def poll(self) -> int | None:
        if self._returncode is not None:
            return self._returncode
        if self._process is None:
            return 0
        status = self._api.WaitForSingleObject(self._process, 0)
        if status == 0x102:
            return None
        code = wintypes.DWORD()
        if status != 0 or not self._api.GetExitCodeProcess(self._process, ctypes.byref(code)):
            raise StateConflict("OLLAMA_PROCESS_STATE_UNKNOWN")
        self._returncode = int(code.value)
        return self._returncode

    @property
    def job_handle(self) -> Any:
        return self._job

    def _capture_exit_handles(self) -> None:
        """Retain exact active descendants across Job accounting/handle signal lag."""
        buffer = ctypes.create_string_buffer(8 + 16 * ctypes.sizeof(ctypes.c_size_t))
        if not self._api.QueryInformationJobObject(self._job, 3, buffer, len(buffer), None):
            raise StateConflict("OLLAMA_STOP_ACK_PENDING")
        assigned = wintypes.DWORD.from_buffer_copy(buffer).value
        count = wintypes.DWORD.from_buffer_copy(buffer, 4).value
        if count > 16 or assigned > count:
            raise StateConflict("OLLAMA_STOP_ACK_PENDING")
        for index in range(count):
            pid = ctypes.c_size_t.from_buffer_copy(
                buffer, 8 + index * ctypes.sizeof(ctypes.c_size_t)
            ).value
            if pid == self.pid or pid in self._exit_handles:
                continue
            handle = self._api.OpenProcess(0x00101000, False, pid)
            if not handle:
                # A vanished process has no remaining object that a new handle can observe.
                if ctypes.get_last_error() == 87:
                    continue
                raise StateConflict("OLLAMA_STOP_ACK_PENDING")
            member = wintypes.BOOL()
            if (
                not self._api.IsProcessInJob(handle, self._job, ctypes.byref(member))
                or not member.value
            ):
                self._api.CloseHandle(handle)
                raise StateConflict("OLLAMA_STOP_ACK_PENDING")
            self._exit_handles[int(pid)] = handle

    def close(self, timeout: float = 3) -> None:
        if self._job is not None:
            self._capture_exit_handles()
            if not self._api.TerminateJobObject(self._job, 1):
                raise StateConflict("OLLAMA_STOP_ACK_PENDING")
            deadline = time.monotonic() + timeout
            while True:
                accounting = _Accounting()
                if not self._api.QueryInformationJobObject(
                    self._job, 1, ctypes.byref(accounting), ctypes.sizeof(accounting), None
                ):
                    raise StateConflict("OLLAMA_STOP_ACK_PENDING")
                if accounting.active == 0:
                    break
                if time.monotonic() >= deadline:
                    raise StateConflict("OLLAMA_STOP_ACK_PENDING")
                threading.Event().wait(0.01)
            for handle in self._exit_handles.values():
                milliseconds = max(0, int((deadline - time.monotonic()) * 1000))
                if self._api.WaitForSingleObject(handle, milliseconds) != 0:
                    raise StateConflict("OLLAMA_STOP_ACK_PENDING")
            milliseconds = max(0, int((deadline - time.monotonic()) * 1000))
            if (
                self._api.WaitForSingleObject(self._process, milliseconds) != 0
                or self.poll() is None
            ):
                raise StateConflict("OLLAMA_STOP_ACK_PENDING")
            for handle in self._exit_handles.values():
                self._api.CloseHandle(handle)
            self._exit_handles.clear()
            self._api.CloseHandle(self._job)
            self._job = None
        if self._process is not None:
            self._api.CloseHandle(self._process)
            self._process = None


class _TCPRow(ctypes.Structure):
    _fields_ = [
        (name, wintypes.DWORD)
        for name in (
            "state",
            "address",
            "port",
            "remote_address",
            "remote_port",
            "pid",
        )
    ]


def listener_matches(pid: int, port: int, *, job: Any = None) -> bool:
    """Observe only IPv4 TCP listeners, without connecting or sending a request."""
    if sys.platform != "win32":
        return False
    api = ctypes.WinDLL("iphlpapi", use_last_error=True)
    api.GetExtendedTcpTable.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.BOOL,
        wintypes.ULONG,
        ctypes.c_int,
        wintypes.ULONG,
    ]
    api.GetExtendedTcpTable.restype = wintypes.DWORD
    size = wintypes.DWORD()
    result = api.GetExtendedTcpTable(None, ctypes.byref(size), False, socket.AF_INET, 3, 0)
    for _ in range(3):
        if result not in (0, 122) or not 4 <= size.value <= 16 * 1024 * 1024:
            return False
        buffer = ctypes.create_string_buffer(size.value)
        result = api.GetExtendedTcpTable(buffer, ctypes.byref(size), False, socket.AF_INET, 3, 0)
        if result == 122:
            continue
        if result:
            return False
        count = wintypes.DWORD.from_buffer_copy(buffer).value
        width = ctypes.sizeof(_TCPRow)
        if 4 + count * width > len(buffer):
            return False
        for index in range(count):
            row = _TCPRow.from_buffer_copy(buffer, 4 + index * width)
            if row.state == 2 and socket.ntohs(row.port & 0xFFFF) == port:
                # IN_ADDR and TCP port are network byte order inside DWORD fields.
                address = int(row.address).to_bytes(4, "little")
                if address != b"\x7f\0\0\x01":
                    return False
                if row.pid == pid:
                    return True
                if job is None:
                    return False
                # Windows venv launchers can host the listener in an owned descendant.
                kernel = _api()
                process = kernel.OpenProcess(0x1000, False, row.pid)
                if not process:
                    return False
                try:
                    member = wintypes.BOOL()
                    return bool(
                        kernel.IsProcessInJob(process, job, ctypes.byref(member)) and member.value
                    )
                finally:
                    kernel.CloseHandle(process)
        return False
    return False
