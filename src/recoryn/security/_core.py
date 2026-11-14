"""Safe failures, input validation, and a security-only coordination boundary."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import os
import re
import sqlite3
import stat
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from typing import ParamSpec, TypeVar
from urllib.parse import urlsplit


class SecurityError(RuntimeError):
    """Only a stable code is printable; never retain a remote diagnostic body."""

    def __init__(self, code: str, *, outcome_known: bool = True) -> None:
        self.code = code if re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", code) else "SECURITY_FAILURE"
        self.outcome_known = outcome_known
        self.retryable = False
        super().__init__(self.code)


_P = ParamSpec("_P")
_T = TypeVar("_T")


def safe_operation(function: Callable[_P, _T]) -> Callable[_P, _T]:
    @wraps(function)
    def guarded(*args: _P.args, **kwargs: _P.kwargs) -> _T:
        try:
            return function(*args, **kwargs)
        except SecurityError:
            raise
        except FileExistsError:
            raise SecurityError("ALREADY_EXISTS") from None
        except (OSError, sqlite3.Error, ValueError, TypeError, OverflowError):
            raise SecurityError("SECURITY_STATE_UNAVAILABLE") from None

    return guarded


def identifier(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value):
        raise SecurityError("INVALID_IDENTIFIER")
    return value


def money(value: object) -> int:
    if type(value) is not int or not 0 <= value <= 2**63 - 1:
        raise SecurityError("INVALID_AMOUNT")
    return value


def duration(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SecurityError("INVALID_TIMEOUT")
    if not math.isfinite(value) or not 0 < value <= 86400:
        raise SecurityError("INVALID_TIMEOUT")
    return float(value)


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def check_path(path: Path) -> Path:
    path = Path(os.path.abspath(path))
    if str(path).startswith(("\\\\", "//")):
        raise SecurityError("UNSAFE_PATH")
    for part in (*reversed(path.parents), path):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise SecurityError("UNSAFE_PATH")
        if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            raise SecurityError("UNSAFE_PATH")
    return path


@dataclass(frozen=True)
class Endpoint:
    url: str
    scheme: str
    host: str
    port: int
    target: str
    loopback: bool


def endpoint(value: str) -> Endpoint:
    try:
        if not isinstance(value, str) or len(value) > 2048 or any(ord(c) <= 32 for c in value):
            raise ValueError
        parsed = urlsplit(value)
        if (
            parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError
        host = (parsed.hostname or "").encode("idna").decode("ascii").lower()
        port = parsed.port if parsed.port is not None else (443 if parsed.scheme == "https" else 80)
        if not host or host.endswith(".") or not 1 <= port <= 65535:
            raise ValueError
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        local = address is not None and address.is_loopback
        if parsed.scheme not in {"https", "http"} or (parsed.scheme == "http" and not local):
            raise ValueError
        if address is not None and not local and not address.is_global:
            raise ValueError
        if address is None and ("." not in host or host.endswith((".local", ".localhost"))):
            raise ValueError
        target = parsed.path or "/"
        target.encode("ascii")
        if "\\" in target or re.search(r"%(?:00|0a|0d)", target, re.I):
            raise ValueError
        authority = f"[{host}]" if ":" in host else host
        default = 443 if parsed.scheme == "https" else 80
        if port != default:
            authority += f":{port}"
        return Endpoint(
            f"{parsed.scheme}://{authority}{target}", parsed.scheme, host, port, target, local
        )
    except (ValueError, UnicodeError):
        raise SecurityError("INVALID_ENDPOINT") from None


_locks_guard = threading.Lock()
_locks: dict[Path, tuple[threading.RLock, threading.local]] = {}


class Coordinator:
    """Serializes policy/transport handoff without holding the media SQLite lock.

    All security instances for a database share a thread and process lock. A slow
    authorized network call can delay policy commands, never the recorder lock.
    """

    def __init__(self, db_path: Path) -> None:
        self.path = check_path(db_path)
        with _locks_guard:
            self.lock, self._local = _locks.setdefault(
                self.path, (threading.RLock(), threading.local())
            )

    @contextmanager
    def hold(self) -> Iterator[None]:
        with self.lock:
            # Each Coordinator needs its own fd only at its outermost entry.
            # Callers share an instance for nested consent/permit operations.
            depth = getattr(self._local, "depth", 0)
            if depth:
                self._local.depth = depth + 1
                try:
                    yield
                finally:
                    self._local.depth -= 1
                return
            lock_path = check_path(self.path.with_name(self.path.name + ".security-lock"))
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o600)
            acquired = False
            try:
                if os.fstat(fd).st_size == 0:
                    os.write(fd, b"\0")
                deadline = time.monotonic() + 10
                while True:
                    try:
                        os.lseek(fd, 0, os.SEEK_SET)
                        if sys.platform == "win32":
                            import msvcrt

                            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                        else:
                            import fcntl

                            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        acquired = True
                        break
                    except OSError:
                        if time.monotonic() >= deadline:
                            raise SecurityError("POLICY_BUSY") from None
                        time.sleep(0.005)
                self._local.depth = 1
                yield
            finally:
                self._local.depth = 0
                if acquired:
                    os.lseek(fd, 0, os.SEEK_SET)
                    if sys.platform == "win32":
                        import msvcrt

                        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)


def connect(path: Path) -> sqlite3.Connection:
    path = check_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, isolation_level=None, check_same_thread=False, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        if connection.execute("PRAGMA user_version").fetchone()[0] not in (0, 1):
            raise SecurityError("UNSUPPORTED_SCHEMA")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
    except BaseException:
        connection.close()
        raise
    return connection


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()
