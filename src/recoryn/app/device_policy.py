"""The user/PC AI execution policy preference (G-P16): a small general setting, not authority.

One JSON file per user and PC, independent of any library root:
``%LOCALAPPDATA%/Recoryn/preferences/device-policy.json`` holding exactly
``{"schema_version":1,"execution_policy":"CPU_ONLY"}``. A restored policy is only the
initial choice for *new* requests; it never grants consent, verifies a model, approves a
cost or resumes a Job. Reading never creates, repairs or deletes anything. A damaged file
stays as it is until the user explicitly confirms a reset; a newer format is never
overwritten. Every failure is a closed status code, never the file text or an OS message.
Atomic replace is not a power-loss durability guarantee.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

from recoryn.domain import ValidationError
from recoryn.models.resource_catalog import POLICIES
from recoryn.storage._safe import check_path, open_file, sync, write_all

DEFAULT_POLICY = "CPU_ONLY"
FALLBACK = "GPU_WITH_CPU_FALLBACK_ALLOWED"
# AUTO is only the display name of the fallback policy; it is never stored or requested.
AUTO_LABEL = "AUTO — GPU 우선, CPU 사용 허용"
LABELS = {"CPU_ONLY": "CPU_ONLY", "GPU_ONLY": "GPU_ONLY", FALLBACK: AUTO_LABEL}
SCHEMA_VERSION = 1
MAX_BYTES = 4096
FILE_NAME = "device-policy.json"
LOCK_NAME = "device-policy.lock"
LOCK_TIMEOUT = 2.0
ABSENT = "ABSENT"  # the revision of a missing file

# Read states (display only; never Job error codes).
DEFAULT, RESTORED, INVALID, FUTURE_VERSION, UNAVAILABLE = (
    "DEFAULT",
    "RESTORED",
    "INVALID",
    "FUTURE_VERSION",
    "UNAVAILABLE",
)
# Write states.
SAVED, FAILED, CONFLICT, REFUSED = "SAVED", "FAILED", "CONFLICT", "REFUSED"
_DRIVE_REJECTED = (0, 1, 4)  # unknown, no root directory, remote (network mapping)


@dataclass(frozen=True)
class PolicyPreference:
    """The only content this setting may hold: one supported execution policy."""

    execution_policy: str

    def __post_init__(self) -> None:
        if type(self.execution_policy) is not str or self.execution_policy not in POLICIES:
            raise ValidationError("POLICY_UNSUPPORTED")

    def payload(self) -> bytes:
        # Exactly the two allowed keys; the enum is ASCII, so no escaping is involved.
        body = f'{{"schema_version":{SCHEMA_VERSION},"execution_policy":"{self.execution_policy}"}}'
        return body.encode("ascii")


@dataclass(frozen=True)
class PolicyReadResult:
    state: str
    policy: str  # the safe policy for this run: the stored one only when RESTORED
    revision: str | None  # conflict check token: ABSENT, a content digest, or None
    reason: str = ""


@dataclass(frozen=True)
class PolicyWriteResult:
    state: str
    policy: str  # the requested policy
    revision: str | None  # the file revision after this call, when known
    reason: str = ""
    current: PolicyReadResult | None = None  # a fresh observation after CONFLICT/REFUSED


class _Unavailable(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def user_location(environ: Mapping[str, str] | None = None) -> Path:
    """The per-user, per-PC location; LOCALAPPDATA only (never cwd or a model folder)."""
    base = (os.environ if environ is None else environ).get("LOCALAPPDATA")
    if not base:
        raise _Unavailable("LOCATION_UNAVAILABLE")
    return Path(base) / "Recoryn" / "preferences" / FILE_NAME


def classify(data: bytes, size: int) -> tuple[str, str | None, str]:
    """(state, policy, reason) of one bounded read, in the contract's fixed order."""
    if size > MAX_BYTES or len(data) > MAX_BYTES:
        return INVALID, None, "SIZE_LIMIT"

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    def constant(value: str) -> None:
        raise ValueError("non-finite number")

    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeError, RecursionError):
        return INVALID, None, "SYNTAX"
    if type(value) is not dict:
        return INVALID, None, "NOT_OBJECT"
    if "schema_version" not in value:
        return INVALID, None, "VERSION_MISSING"
    version = value["schema_version"]
    if type(version) is int and version > SCHEMA_VERSION:
        return FUTURE_VERSION, None, "FUTURE_VERSION"  # preserved, never parsed further
    if type(version) is not int or version != SCHEMA_VERSION:
        return INVALID, None, "VERSION_UNSUPPORTED"
    if set(value) != {"schema_version", "execution_policy"}:
        return INVALID, None, "FIELDS"
    policy = value["execution_policy"]
    if type(policy) is not str or policy not in POLICIES:
        return INVALID, None, "POLICY_UNSUPPORTED"
    return RESTORED, policy, ""


def _revision(data: bytes, size: int) -> str:
    return hashlib.sha256(data).hexdigest() + ":" + str(size)


class PolicyLock:
    def __init__(self, fd: int) -> None:
        self.fd = fd

    def release(self) -> None:
        try:
            if sys.platform == "win32":
                import msvcrt

                os.lseek(self.fd, 0, os.SEEK_SET)
                msvcrt.locking(self.fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.fd, fcntl.LOCK_UN)
        finally:
            os.close(self.fd)


class PolicyIo:
    """The store's only OS operations; tests subclass it to observe or inject faults."""

    def drive_type(self, anchor: str) -> int:
        if sys.platform != "win32":
            return 3
        import ctypes
        from ctypes import wintypes

        # Queries the local mount table, not the remote server.
        query = ctypes.windll.kernel32.GetDriveTypeW
        query.argtypes = [wintypes.LPCWSTR]
        query.restype = wintypes.UINT
        return int(query(anchor))

    def check(self, path: Path) -> None:
        check_path(path)

    def read(self, path: Path, limit: int) -> tuple[bytes, int] | None:
        try:
            stream = open_file(path, "rb")
        except FileNotFoundError:
            return None
        with stream:
            size = os.fstat(stream.fileno()).st_size
            return stream.read(limit + 1), size

    def makedirs(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)

    def open_new(self, path: Path) -> BinaryIO:
        return open_file(path, "xb")

    def write(self, stream: BinaryIO, data: bytes) -> None:
        write_all(stream, data)

    def fsync(self, stream: BinaryIO) -> None:
        sync(stream)

    def replace(self, source: Path, target: Path) -> None:
        os.replace(source, target)

    def remove(self, path: Path) -> None:
        path.unlink()

    def exists(self, path: Path) -> bool:
        return os.path.lexists(path)

    def try_lock(self, path: Path, *, create: bool) -> PolicyLock | None:
        """A held lock, None when it is busy; FileNotFoundError when absent and not created."""
        flags = os.O_RDWR | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags | (os.O_CREAT if create else 0), 0o600)
        try:
            check_path(path)
            if os.fstat(fd).st_size == 0:
                os.write(fd, b"\0")
            os.lseek(fd, 0, os.SEEK_SET)
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            os.close(fd)
            if isinstance(error, (FileNotFoundError, NotADirectoryError)):
                raise
            return None  # held by another cooperating store
        except BaseException:
            os.close(fd)
            raise
        return PolicyLock(fd)


class DevicePolicyStore:
    """Load/save of the preference. Call only from a worker, never the GUI thread.

    Cooperating stores (threads or processes) share one OS lock next to the file; a
    revision check and the replace happen under it. Waiting is bounded by a monotonic
    ``lock_timeout``. This is not a defense against a malicious program with the same
    user's rights replacing files.
    """

    def __init__(
        self,
        location: Path | Callable[[], Path] = user_location,
        *,
        io: PolicyIo | None = None,
        lock_timeout: float = LOCK_TIMEOUT,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._location = location
        self.io = io or PolicyIo()
        self.lock_timeout = lock_timeout
        self._monotonic = monotonic
        self._sleep = sleep
        self._guard = threading.Lock()

    @classmethod
    def for_user(cls, environ: Mapping[str, str] | None = None) -> DevicePolicyStore:
        return cls(lambda: user_location(environ))

    def path(self) -> Path:
        """The checked local location (raises the closed UNAVAILABLE code)."""
        location = self._location() if callable(self._location) else self._location
        text = str(location)
        # UNC, extended (\\?\) and device (\\.\) namespaces are refused by text first:
        # nothing remote is resolved or opened.
        if text.startswith(("\\\\", "//")):
            raise _Unavailable("PATH_NOT_LOCAL")
        if not location.is_absolute() or not location.anchor:
            raise _Unavailable("PATH_NOT_ABSOLUTE")
        if self.io.drive_type(location.anchor) in _DRIVE_REJECTED:
            raise _Unavailable("PATH_NOT_LOCAL")
        try:
            self.io.check(location)
        except ValidationError:
            raise _Unavailable("PATH_UNSAFE") from None
        return location

    # --- reading ---------------------------------------------------------------------

    def load(self) -> PolicyReadResult:
        with self._guard:
            try:
                path = self.path()
                lock = self._acquire(path, create=False)
                try:
                    return self._observe(path)
                finally:
                    if lock is not None:
                        lock.release()
            except _Unavailable as error:
                return PolicyReadResult(UNAVAILABLE, DEFAULT_POLICY, None, error.code)
            except ValidationError:
                return PolicyReadResult(UNAVAILABLE, DEFAULT_POLICY, None, "PATH_UNSAFE")
            except OSError:
                return PolicyReadResult(UNAVAILABLE, DEFAULT_POLICY, None, "IO_ERROR")

    def _observe(self, path: Path) -> PolicyReadResult:
        read = self.io.read(path, MAX_BYTES)
        if read is None:
            return PolicyReadResult(DEFAULT, DEFAULT_POLICY, ABSENT)
        data, size = read
        state, policy, reason = classify(data, size)
        return PolicyReadResult(
            state,
            policy if state == RESTORED and policy else DEFAULT_POLICY,
            _revision(data, size),
            reason,
        )

    # --- writing ---------------------------------------------------------------------

    def save(self, policy: str, *, observed_revision: str | None) -> PolicyWriteResult:
        """Save one explicit selection; a damaged or newer file is never overwritten.

        ``observed_revision`` is the revision this caller last observed; a different file
        is a CONFLICT (no automatic overwrite). None means no earlier observation exists.
        """
        return self._write(policy, observed_revision, reset=False)

    def reset_invalid(
        self, policy: str, *, observed_revision: str | None, confirmed: bool
    ) -> PolicyWriteResult:
        """Replace a damaged current-format file after the user's explicit confirmation."""
        if confirmed is not True:
            return PolicyWriteResult(REFUSED, str(policy), observed_revision, "NOT_CONFIRMED")
        return self._write(policy, observed_revision, reset=True)

    def _write(self, policy: str, observed: str | None, *, reset: bool) -> PolicyWriteResult:
        try:
            payload = PolicyPreference(policy).payload()
        except ValidationError:
            return PolicyWriteResult(REFUSED, str(policy), observed, "POLICY_UNSUPPORTED")
        with self._guard:
            try:
                path = self.path()
                self._make_parent(path.parent)
                lock = self._acquire(path, create=True)
                if lock is None:
                    return PolicyWriteResult(FAILED, policy, observed, "LOCK_TIMEOUT")
                try:
                    return self._write_locked(path, policy, payload, observed, reset)
                finally:
                    lock.release()
            except _Unavailable as error:
                return PolicyWriteResult(FAILED, policy, observed, error.code)
            except ValidationError:
                return PolicyWriteResult(FAILED, policy, observed, "PATH_UNSAFE")
            except OSError:
                return PolicyWriteResult(FAILED, policy, observed, "IO_ERROR")

    def _write_locked(
        self, path: Path, policy: str, payload: bytes, observed: str | None, reset: bool
    ) -> PolicyWriteResult:
        current = self._observe(path)
        if current.state == FUTURE_VERSION:
            return PolicyWriteResult(REFUSED, policy, current.revision, "FUTURE_VERSION", current)
        if reset and current.state != INVALID:
            # Nothing damaged to replace any more: the file changed since it was shown.
            return PolicyWriteResult(CONFLICT, policy, current.revision, "NOT_INVALID", current)
        if not reset and current.state == INVALID:
            return PolicyWriteResult(REFUSED, policy, current.revision, "RESET_REQUIRED", current)
        if observed is not None and current.revision != observed:
            return PolicyWriteResult(CONFLICT, policy, current.revision, "REVISION", current)
        if current.state == RESTORED and current.policy == policy and not reset:
            if current.revision == _revision(payload, len(payload)):
                return PolicyWriteResult(SAVED, policy, current.revision)  # idempotent
        temporary = path.with_name("." + FILE_NAME + "." + uuid.uuid4().hex + ".tmp")
        try:
            with self.io.open_new(temporary) as stream:
                self.io.write(stream, payload)
                self.io.fsync(stream)
            self._replace(temporary, path)
        except OSError:
            reason = "WRITE_FAILED"
            try:
                if self.io.exists(temporary):
                    self.io.remove(temporary)
            except OSError:
                reason = "WRITE_FAILED_TEMP_LEFT"  # the original setting is untouched
            return PolicyWriteResult(FAILED, policy, current.revision, reason)
        return PolicyWriteResult(SAVED, policy, _revision(payload, len(payload)))

    def _replace(self, temporary: Path, path: Path) -> None:
        """Bounded retry of a transient sharing denial within this call only.

        A failed call reports FAILED; the next save starts fresh (no lasting state).
        """
        deadline = self._monotonic() + self.lock_timeout
        while True:
            try:
                self.io.replace(temporary, path)
                return
            except PermissionError:
                if self._monotonic() >= deadline:
                    raise
                self._sleep(0.01)

    def _make_parent(self, directory: Path) -> None:
        if not self.io.exists(directory):
            self.io.makedirs(directory)
        try:
            self.io.check(directory)
        except ValidationError:
            raise _Unavailable("PATH_UNSAFE") from None

    def _acquire(self, path: Path, *, create: bool) -> PolicyLock | None:
        """The cooperating lock, waiting at most ``lock_timeout``.

        A reader never creates the lock file (reading has no side effects); without it no
        writer has ever existed, and the atomic replace keeps reads whole anyway.
        """
        lock_path = path.with_name(LOCK_NAME)
        deadline = self._monotonic() + self.lock_timeout
        while True:
            try:
                held = self.io.try_lock(lock_path, create=create)
            except (FileNotFoundError, NotADirectoryError):
                if create:
                    raise
                return None
            if held is not None:
                return held
            if self._monotonic() >= deadline:
                if create:
                    return None
                raise _Unavailable("LOCK_TIMEOUT")
            self._sleep(0.01)


# --- GUI-side state -------------------------------------------------------------------

LOADING, SAVING, SAVE_FAILED, NO_STORE, CLOSED = (
    "LOADING",
    "SAVING",
    "SAVE_FAILED",
    "NO_STORE",
    "CLOSED",
)
SAVED_STATE = "SAVED"


@dataclass(frozen=True)
class PolicyView:
    current: str  # the policy captured by every new request
    state: str
    text: str
    reset_allowed: bool
    file_policy: str | None = None


def label(policy: str) -> str:
    return LABELS.get(policy, policy)


def status_text(current: str, state: str, file_policy: str | None = None) -> str:
    """Hand-readable status; the current choice and whether it persists are separate."""
    run = "현재 실행: " + label(current)
    tail = {
        LOADING: "저장된 설정 확인 중",
        DEFAULT: "저장된 설정 없음 · 기본값",
        RESTORED: "저장된 설정 복원됨",
        SAVING: "저장 중",
        SAVED_STATE: "저장됨 · 다음 시작에도 유지",
        INVALID: "설정 파일 손상 · 저장 안 됨, 다음 시작에 유지되지 않을 수 있음. "
        "‘설정 재설정’으로 교체할 수 있습니다",
        FUTURE_VERSION: "다른(새) 버전의 설정을 보존 · 이 버전에서는 저장하지 않음",
        SAVE_FAILED: "저장 안 됨, 다음 시작에 유지되지 않을 수 있음",
        CONFLICT: "저장 안 됨 · 다른 곳에서 설정이 바뀌었습니다"
        + (f"(파일: {label(file_policy)})" if file_policy else "")
        + ". 다시 선택하면 저장합니다",
        UNAVAILABLE: "설정 위치 확인 필요 · 저장된 설정을 읽지 못함",
        NO_STORE: "이 창은 설정을 저장하지 않음",
        CLOSED: "창 닫힘",
    }[state]
    text = run + " · " + tail
    if current != FALLBACK:
        text += ". 로컬 Ollama 요약은 이 정책에서 차단됩니다(필요하면 AUTO를 직접 선택)"
    return text


class _Chain:
    """The revision the worker compares against; shared by queued saves (worker side)."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.revision: str | None = None
        self.conflicted = False
        self.observed: PolicyReadResult | None = None  # what the conflicting save saw

    def adopt(self, revision: str | None) -> None:
        with self.lock:
            self.revision = revision
            self.conflicted = False
            self.observed = None


class PolicyController:
    """One window's policy state. ``submit(work, done)`` runs ``work`` on one serial
    worker (FIFO, never the GUI thread) and delivers ``done(result)`` on the GUI thread;
    ``notify(view, announce)`` updates the UI.

    A selection applies to new requests at once and bumps a generation, so an older load
    answer never replaces it. Only a user selection is saved; it is queued behind the
    load, which records the observed revision first. The store itself refuses to
    overwrite a damaged or newer file. Restoring never triggers AI work, consent,
    verification or a resume.
    """

    def __init__(
        self,
        store: DevicePolicyStore | None,
        submit: Callable[[Callable[[], Any], Callable[[Any], None]], None],
        notify: Callable[[PolicyView, bool], None],
    ) -> None:
        self.store = store
        self._submit = submit
        self._notify = notify
        self.current = DEFAULT_POLICY
        self.state = LOADING if store is not None else NO_STORE
        self.file_policy: str | None = None
        self.read_state: str | None = None
        self.closed = False
        self._generation = 0
        self._ticket = 0
        self._chain = _Chain()
        self._announced: tuple[str, str] | None = None

    def view(self) -> PolicyView:
        return PolicyView(
            self.current,
            self.state,
            status_text(self.current, self.state, self.file_policy),
            self.state == INVALID,
            self.file_policy,
        )

    def _emit(self, announce: bool = False) -> None:
        key = (self.state, self.current)
        announce = announce and key != self._announced
        if announce:
            self._announced = key
        self._notify(self.view(), announce)

    def start(self) -> None:
        store, chain = self.store, self._chain
        if store is None:
            self._emit()
            return

        def work() -> PolicyReadResult:
            result = store.load()
            chain.adopt(result.revision)  # in FIFO order, before any queued save runs
            return result

        generation, ticket = self._generation, self._ticket
        self._submit(work, lambda result: self._loaded(generation, ticket, result))
        self._emit()

    def select(self, policy: str, *, user: bool) -> None:
        if self.closed or type(policy) is not str or policy not in POLICIES:
            return
        self.current = policy
        self._generation += 1
        if user:
            self._request_save()
        else:
            self._emit()

    def _request_save(self) -> None:
        store = self.store
        if store is None:
            self._emit()
            return
        self._ticket += 1
        ticket, policy, chain = self._ticket, self.current, self._chain

        def work() -> PolicyWriteResult:
            with chain.lock:
                if chain.conflicted:
                    # Queued before the user saw the conflict: never an automatic overwrite.
                    return PolicyWriteResult(
                        CONFLICT, policy, chain.revision, "REVISION", chain.observed
                    )
                result = store.save(policy, observed_revision=chain.revision)
                if result.state == SAVED:
                    chain.revision = result.revision
                elif result.state == CONFLICT:
                    chain.conflicted, chain.observed = True, result.current
                return result

        self.state = SAVING
        self._submit(work, lambda result: self._saved(ticket, result))
        self._emit()

    def reset(self, *, confirmed: bool) -> None:
        if self.closed or self.store is None or self.state != INVALID:
            return
        if not confirmed:
            self._emit()
            return  # No / Escape: nothing is written
        self._ticket += 1
        ticket, policy, chain, store = self._ticket, self.current, self._chain, self.store

        def work() -> PolicyWriteResult:
            with chain.lock:
                result = store.reset_invalid(
                    policy, observed_revision=chain.revision, confirmed=True
                )
                if result.state == SAVED:
                    chain.revision, chain.conflicted = result.revision, False
                return result

        self.state = SAVING
        self._submit(work, lambda result: self._saved(ticket, result))
        self._emit()

    def _loaded(self, generation: int, ticket: int, result: Any) -> None:
        if self.closed:
            return
        if not isinstance(result, PolicyReadResult):
            result = PolicyReadResult(UNAVAILABLE, DEFAULT_POLICY, None, "IO_ERROR")
        if self._ticket != ticket:
            return  # a save requested since then reports the newer status itself
        self.read_state = result.state
        self.file_policy = result.policy if result.state == RESTORED else None
        if generation == self._generation:
            self.current = result.policy  # DEFAULT_POLICY unless RESTORED
        self.state = result.state
        self._emit(announce=result.state != DEFAULT)

    def _saved(self, ticket: int, result: Any) -> None:
        if self.closed or ticket != self._ticket:
            return  # closed, or an older answer that never replaces a newer selection
        if not isinstance(result, PolicyWriteResult):
            result = PolicyWriteResult(FAILED, self.current, None, "IO_ERROR")
        if result.current is not None:
            observed = result.current
            self.read_state = observed.state
            self.file_policy = observed.policy if observed.state == RESTORED else None
            if result.state == CONFLICT:
                self._chain.adopt(observed.revision)  # shown now; a new choice may save
        if result.state == SAVED:
            self.read_state, self.file_policy = RESTORED, result.policy
            self.state = SAVED_STATE
        elif result.state == CONFLICT:
            self.state = CONFLICT
        elif result.state == REFUSED and result.reason == "FUTURE_VERSION":
            self.state = FUTURE_VERSION
        elif result.state == REFUSED and result.reason == "RESET_REQUIRED":
            self.state = INVALID
        else:
            self.state = SAVE_FAILED
        self._emit(announce=True)

    def close(self) -> None:
        self.closed = True
        self.state = CLOSED
