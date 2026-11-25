"""G-P13: local-only model reads, re-checks and the guarded bundle a loader is given.

Order (G13 §5): lexical/namespace checks and the local drive type come first, so a UNC,
device, extended or network path is refused before any stat/open/realpath. Links,
reparse points and hard links are refused in every component, and every read compares
the opened handle with the name before and after. A loader never receives the original
folder: the confirmed bytes are copied into an owned bundle, compared again, sealed with
handles that deny writing, deleting and renaming, and checked once more. This is a
cooperating-process boundary, not an OS sandbox against same-user malicious code.
"""

from __future__ import annotations

import errno
import hashlib
import os
import shutil
import stat
import sys
import tempfile
import threading
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any, BinaryIO

from recoryn.domain import ValidationError
from recoryn.providers import ProviderError
from recoryn.storage._safe import check_path, open_file, write_all

from .artifacts import (
    ABSENT,
    ABSENT_DEFAULT,
    DIARIZATION,
    LOADERS,
    MANAGED,
    MANUAL,
    PREPROCESSOR_DEFAULT,
    PRESENT,
    SELF_DIGEST,
    WHISPER,
    WHISPER_LICENSES,
    WHISPER_OPTIONAL,
    WHISPER_REQUIRED,
    WHISPER_UNSUPPORTED,
    WHISPER_VOCABULARIES,
    FileEntry,
    ModelSourceSnapshot,
    ModelUseEvidence,
    Terms,
    artifact_digest,
)

CHUNK = 1024 * 1024
MAX_METADATA = 64 * 1024 * 1024  # config/tokenizer/vocabulary/preprocessor/license bytes
DRIVE_ALLOWED = frozenset({2, 3, 6})  # GetDriveTypeW: removable, fixed, RAM disk
BUNDLE_PREFIX = "recoryn-model-bundle-"
# G13R-03: a copy never eats the space a recording may need on the same volume.
RESERVE_MINIMUM = 1024**3
RESERVE_FRACTION = 10  # percent of the target volume


class ArtifactError(ProviderError):
    """A closed provider code plus a safe detail (never a path or an SDK message)."""

    def __init__(
        self,
        code: str,
        detail: str = "",
        *,
        retryable: bool = False,
        outcome_known: bool = True,
    ) -> None:
        # outcome_known is passed through unchanged: an unknown outcome never becomes known.
        super().__init__(code, retryable=retryable, outcome_known=outcome_known)
        self.detail = detail or code


class Guard:
    """A held handle that denies writing, deleting and renaming its file or folder."""

    def __init__(self, release: Callable[[], None]) -> None:
        self._release: Callable[[], None] | None = release

    @property
    def held(self) -> bool:
        return self._release is not None

    def release(self) -> None:
        release, self._release = self._release, None
        if release is not None:
            release()


class ArtifactIo:
    """The OS seam (tests substitute it to watch every call and to inject faults)."""

    def drive_type(self, anchor: str) -> int:
        if sys.platform != "win32":
            return 3
        import ctypes
        from ctypes import wintypes

        function = ctypes.windll.kernel32.GetDriveTypeW
        function.argtypes = [wintypes.LPCWSTR]
        function.restype = wintypes.UINT
        return int(function(anchor))  # the local mount table, not the remote server

    def check(self, path: Path) -> None:
        check_path(path)

    def stat(self, path: Path) -> os.stat_result:
        return path.lstat()

    def realpath(self, path: Path) -> str:
        return os.path.normcase(os.path.realpath(path))

    def listdir(self, path: Path) -> list[str]:
        return sorted(os.listdir(path))

    def open_read(self, path: Path) -> BinaryIO:
        return open_file(path, "rb")

    def fstat(self, stream: BinaryIO) -> os.stat_result:
        return os.fstat(stream.fileno())

    def open_new(self, path: Path) -> BinaryIO:
        return open_file(path, "xb")

    def write(self, stream: BinaryIO, data: bytes) -> None:
        write_all(stream, data)

    def mkdtemp(self, parent: Path | None) -> Path:
        return Path(tempfile.mkdtemp(prefix=BUNDLE_PREFIX, dir=parent))

    def disk_usage(self, path: Path) -> Any:
        return shutil.disk_usage(path)

    def remove(self, path: Path) -> None:
        path.unlink()

    def rmdir(self, path: Path) -> None:
        path.rmdir()

    def guard(self, path: Path, *, directory: bool) -> Guard:
        if sys.platform != "win32":
            raise ArtifactError("CAPABILITY_UNSUPPORTED", "GUARD_UNSUPPORTED")
        return _windows_guard(path, directory=directory)


def _windows_guard(path: Path, *, directory: bool) -> Guard:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel32.CreateFileW
    create.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create.restype = wintypes.HANDLE
    close = kernel32.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    generic_read, share_read, open_existing = 0x80000000, 0x00000001, 3
    flags = 0x00200000 | (0x02000000 if directory else 0)  # open the reparse point itself
    # Share read only: no writer, no delete and no rename while the handle is held.
    handle = create(str(path), generic_read, share_read, None, open_existing, flags, None)
    if handle is None or handle == wintypes.HANDLE(-1).value:
        raise ArtifactError("INPUT_INVALID", "GUARD_FAILED")

    class Information(ctypes.Structure):
        _fields_ = [
            ("attributes", wintypes.DWORD),
            ("created", wintypes.FILETIME),
            ("accessed", wintypes.FILETIME),
            ("written", wintypes.FILETIME),
            ("volume", wintypes.DWORD),
            ("size_high", wintypes.DWORD),
            ("size_low", wintypes.DWORD),
            ("links", wintypes.DWORD),
            ("index_high", wintypes.DWORD),
            ("index_low", wintypes.DWORD),
        ]

    information = kernel32.GetFileInformationByHandle
    information.argtypes = [wintypes.HANDLE, ctypes.POINTER(Information)]
    information.restype = wintypes.BOOL
    info = Information()
    try:
        named = path.lstat()
        if not information(handle, ctypes.byref(info)):
            raise ArtifactError("INPUT_INVALID", "GUARD_FAILED")
        index = (info.index_high << 32) | info.index_low
        if (
            info.volume != named.st_dev & 0xFFFFFFFF
            or index != named.st_ino
            or info.attributes & 0x400
            or (not directory and info.links != 1)
        ):
            raise ArtifactError("MODEL_CHECKSUM_MISMATCH", "GUARD_IDENTITY")
    except BaseException:
        close(handle)
        raise
    return Guard(lambda: close(handle))


def local_path(path: Path, io: ArtifactIo) -> Path:
    """A local absolute path, judged by text and drive type before any filesystem access."""
    text = str(path)
    if text.startswith(("\\\\", "//")):
        raise ArtifactError("CAPABILITY_UNSUPPORTED", "PATH_NOT_LOCAL")  # UNC, \\?\, \\.\
    candidate = Path(text)
    if not candidate.is_absolute() or len(candidate.drive) != 2 or candidate.drive[1] != ":":
        raise ArtifactError("CAPABILITY_UNSUPPORTED", "PATH_NOT_ABSOLUTE")
    if ":" in text[2:]:
        raise ArtifactError("CAPABILITY_UNSUPPORTED", "PATH_STREAM")  # alternate data streams
    if io.drive_type(candidate.anchor) not in DRIVE_ALLOWED:
        raise ArtifactError("CAPABILITY_UNSUPPORTED", "PATH_NOT_LOCAL")  # network/unknown
    normalized = Path(os.path.normpath(text))
    try:
        io.check(normalized)
    except ValidationError:
        raise ArtifactError("CAPABILITY_UNSUPPORTED", "PATH_LINK") from None
    return normalized


def _cancelled(cancel: Any) -> None:
    if cancel is not None and cancel.is_set():
        raise ArtifactError("CANCELLED")


def hash_file(
    path: Path, io: ArtifactIo, cancel: Any = None, *, keep: bool = False
) -> tuple[int, str, bytes | None]:
    """(size, SHA-256, bytes when keep) of one identity-checked read in chunks."""
    path = local_path(path, io)  # never a remote, device or link path, even here
    try:
        stream = io.open_read(path)
    except FileNotFoundError:
        raise ArtifactError("MODEL_MISSING") from None
    except ValidationError:
        raise ArtifactError("CAPABILITY_UNSUPPORTED", "PATH_LINK") from None
    except OSError:
        raise ArtifactError("INPUT_INVALID", "READ_FAILED") from None
    with stream:
        before = io.fstat(stream)
        hasher, size, kept = hashlib.sha256(), 0, bytearray() if keep else None
        while True:
            _cancelled(cancel)
            block = stream.read(CHUNK)
            if not block:
                break
            size += len(block)
            hasher.update(block)
            if kept is not None:
                if size > MAX_METADATA:
                    raise ArtifactError("CAPABILITY_UNSUPPORTED", "METADATA_TOO_LARGE")
                kept.extend(block)
        after = io.fstat(stream)
        named = io.stat(path)
    if (
        (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns)
        or size != after.st_size
        or (named.st_dev, named.st_ino) != (after.st_dev, after.st_ino)
    ):
        raise ArtifactError("MODEL_CHECKSUM_MISMATCH", "SOURCE_CHANGED_DURING_READ")
    return size, hasher.hexdigest(), bytes(kept) if kept is not None else None


def _identity(root: Path, io: ArtifactIo) -> tuple[int, int, str]:
    try:
        info = io.stat(root)
    except FileNotFoundError:
        raise ArtifactError("MODEL_MISSING") from None
    except OSError:
        raise ArtifactError("INPUT_INVALID", "READ_FAILED") from None
    if not stat.S_ISDIR(info.st_mode):
        raise ArtifactError("MODEL_MISSING")
    return info.st_dev, info.st_ino, io.realpath(root)


def whisper_snapshot(
    root: Path,
    *,
    source_kind: str = MANUAL,
    integrity: str = SELF_DIGEST,
    license_id: str | None = None,
    license_url: str | None = None,
    reference: str | None = None,
    model_id: str | None = None,
    io: ArtifactIo | None = None,
    cancel: Any = None,
) -> ModelSourceSnapshot:
    """Hash exactly the files the loader contract gives faster-whisper (G13 §4.1)."""
    io = io or ArtifactIo()
    root = local_path(root, io)
    identity = _identity(root, io)
    try:
        names = io.listdir(root)
    except OSError:
        raise ArtifactError("MODEL_MISSING") from None
    known = {
        name.casefold()
        for name in (*WHISPER_REQUIRED, *WHISPER_OPTIONAL, *WHISPER_LICENSES, *WHISPER_UNSUPPORTED)
    }
    seen: dict[str, list[str]] = {}
    for name in names:
        if name.casefold() in known:
            seen.setdefault(name.casefold(), []).append(name)
    if any(len(variants) > 1 for variants in seen.values()):
        raise ArtifactError("CAPABILITY_UNSUPPORTED", "NAME_COLLISION")
    for name in WHISPER_UNSUPPORTED:
        if name.casefold() in seen:
            raise ArtifactError("CAPABILITY_UNSUPPORTED", "LOADER_INPUT_UNSUPPORTED")
    if all(name.casefold() in seen for name in WHISPER_VOCABULARIES):
        raise ArtifactError("CAPABILITY_UNSUPPORTED", "VOCABULARY_AMBIGUOUS")
    entries: list[FileEntry] = []
    for name in (*WHISPER_REQUIRED, *WHISPER_OPTIONAL):
        variants = seen.get(name.casefold(), [])
        if variants and variants[0] != name:
            raise ArtifactError("CAPABILITY_UNSUPPORTED", "NAME_CASE")
        if not variants:
            if name in WHISPER_REQUIRED:
                raise ArtifactError("MODEL_MISSING")
            state = ABSENT_DEFAULT if name == "preprocessor_config.json" else ABSENT
            entries.append(FileEntry(name, 0, "", state))
            continue
        try:
            regular = stat.S_ISREG(io.stat(root / name).st_mode)
        except OSError:
            regular = False
        if not regular:
            raise ArtifactError(
                "MODEL_MISSING" if name in WHISPER_REQUIRED else "CAPABILITY_UNSUPPORTED"
            )
        size, digest, _ = hash_file(root / name, io, cancel)
        if size == 0:
            # An empty tokenizer would make the SDK look next to the model or on the Hub.
            raise ArtifactError(
                "MODEL_MISSING" if name in WHISPER_REQUIRED else "CAPABILITY_UNSUPPORTED"
            )
        entries.append(FileEntry(name, size, digest))
    licenses = []
    for name in WHISPER_LICENSES:
        for actual in seen.get(name.casefold(), []):
            # Any case, under its real name; an empty license file is still recorded, so
            # the snapshot and the pre-seal input check count the same names (G13R-05).
            size, digest, _ = hash_file(root / actual, io, cancel)
            licenses.append(FileEntry(actual, size, digest))
    if _identity(root, io) != identity:
        raise ArtifactError("MODEL_CHECKSUM_MISMATCH", "ROOT_CHANGED")
    terms = Terms(source_kind, license_id, license_url, tuple(licenses), reference)
    return ModelSourceSnapshot(
        WHISPER, source_kind, str(root), identity, tuple(entries), terms, integrity, model_id
    )


def managed_snapshot(
    manager: Any,
    model_id: str,
    reference: str | None,
    *,
    io: ArtifactIo | None = None,
    cancel: Any = None,
) -> ModelSourceSnapshot:
    """A managed install: its own spec must equal the reference pinned outside the folder.

    The folder's installed.json is never its own expected value (G13 §3.1, T11/T12):
    without an external reference, or on any mismatch or corruption, the snapshot is
    INVALID and stays so (no automatic manual fallback).
    """
    from .artifacts import INVALID, MATCH
    from .manager import spec_digest

    io = io or ArtifactIo()
    folder = Path(manager.root) / model_id
    integrity, license_id, license_url = INVALID, None, None
    declared: dict[str, tuple[int, str]] = {}
    try:
        path, spec = manager.verified_spec(model_id)
        license_id, license_url = spec.license_id, spec.license_url
        if reference is not None and spec_digest(spec) == reference and spec.kind == WHISPER:
            integrity, folder = MATCH, path
            declared = {item.path: (item.size, item.sha256) for item in spec.files}
    except (OSError, ValueError, KeyError, TypeError):
        integrity = INVALID
    snapshot = whisper_snapshot(
        folder,
        source_kind=MANAGED,
        integrity=integrity,
        license_id=license_id,
        license_url=license_url,
        reference=reference,
        model_id=model_id,
        io=io,
        cancel=cancel,
    )
    if integrity == MATCH:
        # G13R-04: MATCH is bound to exactly the bytes hashed for this snapshot.
        hashed = [entry for entry in snapshot.entries if entry.state == PRESENT]
        hashed += list(snapshot.terms.license_files)
        if any(declared.get(entry.name) != (entry.size, entry.sha256) for entry in hashed):
            snapshot = replace(snapshot, integrity=INVALID, artifact_digest="", terms_digest="")
    return snapshot


def diarization_snapshot(
    files: dict[str, bytes],
    root: Path,
    *,
    license_id: str,
    license_url: str,
    reference: str,
    io: ArtifactIo | None = None,
) -> ModelSourceSnapshot:
    """The strictly verified diarization bytes (manifest, two models, two licenses)."""
    from .artifacts import DIARIZATION_FILES, DIARIZATION_LICENSES, MATCH

    io = io or ArtifactIo()
    root = local_path(root, io)
    identity = _identity(root, io)
    if set(files) != {*DIARIZATION_FILES, *DIARIZATION_LICENSES}:
        raise ArtifactError("DIARIZATION_MANIFEST_INVALID")
    entries = tuple(
        FileEntry(name, len(files[name]), hashlib.sha256(files[name]).hexdigest())
        for name in DIARIZATION_FILES
    )
    licenses = tuple(
        FileEntry(name, len(files[name]), hashlib.sha256(files[name]).hexdigest())
        for name in DIARIZATION_LICENSES
    )
    terms = Terms(MANUAL, license_id, license_url, licenses, reference)
    return ModelSourceSnapshot(DIARIZATION, MANUAL, str(root), identity, entries, terms, MATCH)


def _same_source(current: ModelSourceSnapshot, expected: ModelSourceSnapshot) -> None:
    if (
        current.root_identity != expected.root_identity
        or current.entries != expected.entries
        or current.artifact_digest != expected.artifact_digest
        or current.terms_digest != expected.terms_digest
        or current.integrity != expected.integrity
    ):
        raise ArtifactError("MODEL_CHECKSUM_MISMATCH", "SOURCE_CHANGED")


def recheck_whisper(
    evidence: ModelUseEvidence, *, io: ArtifactIo | None = None, cancel: Any = None
) -> None:
    """Right before native: the original source must still be the confirmed one; a
    managed install is judged again against its manager spec and pin (G13R-02)."""
    if not isinstance(evidence, ModelUseEvidence) or not evidence.valid():
        raise ArtifactError("CAPABILITY_UNSUPPORTED", "MODEL_CONFIRMATION_REQUIRED")
    expected = evidence.snapshot
    if expected.kind != WHISPER:
        raise ArtifactError("CAPABILITY_UNSUPPORTED", "MODEL_ROLE_MISMATCH")
    if expected.source_kind == MANAGED and expected.model_id is not None:
        from .manager import ModelManager

        try:
            manager = ModelManager(Path(expected.root).parent)
        except (OSError, ValueError):
            raise ArtifactError("MODEL_CHECKSUM_MISMATCH", "SOURCE_CHANGED") from None
        current = managed_snapshot(
            manager, expected.model_id, expected.terms.reference, io=io, cancel=cancel
        )
        _same_source(current, expected)
        return
    current = whisper_snapshot(
        Path(expected.root),
        source_kind=expected.source_kind,
        integrity=expected.integrity,
        license_id=expected.terms.license_id,
        license_url=expected.terms.license_url,
        reference=expected.terms.reference,
        model_id=expected.model_id,
        io=io,
        cancel=cancel,
    )
    _same_source(current, expected)


class FrozenModelBundle:
    """An owned, sealed copy of exactly the confirmed bytes (G13 §5.2).

    Guards stay held until ``close``, which the owner calls only after the child that
    reads the bundle has exited (its ACK); a failed cleanup is reported, never retried
    on other paths. Only this bundle's own files and folder are ever removed.
    """

    def __init__(
        self,
        snapshot: ModelSourceSnapshot,
        directory: Path,
        names: tuple[str, ...],
        guards: list[Guard],
        io: ArtifactIo,
    ) -> None:
        self.snapshot = snapshot
        self.directory = directory
        self.names = names
        self._guards = guards
        self._io = io
        self.state = "SEALED"

    @property
    def sealed(self) -> bool:
        return self.state == "SEALED" and all(guard.held for guard in self._guards)

    def description(self) -> dict[str, Any]:
        """Plain metadata for the child (never the original folder, never a pickle)."""
        return {
            "kind": self.snapshot.kind,
            "loader": self.snapshot.loader,
            "directory": str(self.directory),
            "artifact_digest": self.snapshot.artifact_digest,
            "entries": [entry.row() for entry in self.snapshot.entries],
            "licenses": [entry.name for entry in self.snapshot.terms.license_files],
            "bundle_id": "recoryn-bundle-" + self.snapshot.artifact_digest[:16],
        }

    def close(self) -> bool:
        """Release the guards and remove only this bundle; False: cleanup pending."""
        if self.state == "CLOSED":
            return True
        for guard in self._guards:
            guard.release()
        removed = _remove_owned(self.directory, self.names, self._io)
        self.state = "CLOSED" if removed else "CLEANUP_PENDING"
        return removed


def _remove_owned(directory: Path, names: tuple[str, ...], io: ArtifactIo) -> bool:
    ok = True
    for name in names:
        try:
            io.remove(directory / name)
        except FileNotFoundError:
            pass
        except OSError:
            ok = False
    try:
        io.rmdir(directory)
    except FileNotFoundError:
        pass
    except OSError:
        ok = False
    return ok


def _inputs(root: Path, io: ArtifactIo) -> set[str]:
    """The loader-relevant names present in a Whisper folder (case-folded)."""
    known = {
        name.casefold()
        for name in (*WHISPER_REQUIRED, *WHISPER_OPTIONAL, *WHISPER_LICENSES, *WHISPER_UNSUPPORTED)
    }
    try:
        return {name.casefold() for name in io.listdir(root) if name.casefold() in known}
    except OSError:
        raise ArtifactError("MODEL_CHECKSUM_MISMATCH", "SOURCE_CHANGED") from None


def _expected_inputs(snapshot: ModelSourceSnapshot) -> set[str]:
    present = {entry.name.casefold() for entry in snapshot.entries if entry.state == PRESENT}
    return present | {entry.name.casefold() for entry in snapshot.terms.license_files}


def _copy(source: Path, target: Path, entry: FileEntry, io: ArtifactIo, cancel: Any) -> None:
    try:
        reader = io.open_read(source)
    except FileNotFoundError:
        raise ArtifactError("MODEL_CHECKSUM_MISMATCH", "SOURCE_CHANGED") from None
    except (OSError, ValidationError):
        raise ArtifactError("MODEL_CHECKSUM_MISMATCH", "SOURCE_CHANGED") from None
    with reader:
        before = io.fstat(reader)
        writer = io.open_new(target)
        with writer:
            hasher, size = hashlib.sha256(), 0
            while True:
                _cancelled(cancel)
                block = reader.read(CHUNK)
                if not block:
                    break
                size += len(block)
                if size > entry.size:
                    raise ArtifactError("MODEL_CHECKSUM_MISMATCH", "SOURCE_CHANGED")
                hasher.update(block)
                io.write(writer, block)
        after = io.fstat(reader)
        named = io.stat(source)
    if (
        size != entry.size
        or hasher.hexdigest() != entry.sha256
        or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns)
        or (named.st_dev, named.st_ino) != (after.st_dev, after.st_ino)
    ):
        raise ArtifactError("MODEL_CHECKSUM_MISMATCH", "SOURCE_CHANGED")


def _verify_bundle(
    directory: Path, entries: tuple[FileEntry, ...], io: ArtifactIo, cancel: Any
) -> None:
    _exact_listing(directory, {entry.name for entry in entries}, io)
    for entry in entries:
        size, digest, _ = hash_file(directory / entry.name, io, cancel)
        if (size, digest) != (entry.size, entry.sha256):
            raise ArtifactError("MODEL_CHECKSUM_MISMATCH", "BUNDLE_CHANGED")


def _exact_listing(directory: Path, names: set[str], io: ArtifactIo) -> None:
    """A sealed bundle holds exactly its own names: a file added later (the folder guard
    cannot stop creation) is refused before any loader sees the folder (G13R-07)."""
    try:
        present = set(io.listdir(directory))
    except OSError:
        raise ArtifactError("MODEL_CHECKSUM_MISMATCH", "BUNDLE_CHANGED") from None
    if not names <= present or present - names:
        raise ArtifactError("MODEL_CHECKSUM_MISMATCH", "BUNDLE_CHANGED")


def _reserve(target: Path, needed: int, io: ArtifactIo) -> None:
    """The copy needs the model size plus max(1 GiB, 10% of the volume) free (G13R-03)."""
    try:
        usage = io.disk_usage(target)
    except OSError:
        raise ArtifactError("RESOURCE_EXHAUSTED", "DISK_UNKNOWN") from None
    reserve = max(RESERVE_MINIMUM, usage.total * RESERVE_FRACTION // 100)
    if usage.free < needed + reserve:
        raise ArtifactError("RESOURCE_EXHAUSTED", "DISK_RESERVE")


def freeze(
    evidence: ModelUseEvidence,
    *,
    data: dict[str, bytes] | None = None,
    parent: Path | None = None,
    io: ArtifactIo | None = None,
    cancel: Any = None,
) -> FrozenModelBundle:
    """Re-check the source, copy the confirmed bytes, seal, and check the seal (G13 §5.2).

    ``data`` carries the already strictly verified diarization bytes; Whisper bytes are
    copied from the source in chunks and compared while copying. Any change, cancel,
    short write or full disk leaves no bundle behind and no native loader is reached.
    """
    io = io or ArtifactIo()
    if not isinstance(evidence, ModelUseEvidence) or not evidence.valid():
        raise ArtifactError("CAPABILITY_UNSUPPORTED", "MODEL_CONFIRMATION_REQUIRED")
    snapshot = evidence.snapshot
    if (data is not None) != (snapshot.kind == DIARIZATION):
        raise ArtifactError("CAPABILITY_UNSUPPORTED", "MODEL_ROLE_MISMATCH")  # T14
    present = tuple(entry for entry in snapshot.entries if entry.state == PRESENT)
    licenses = snapshot.terms.license_files
    files = (*present, *licenses)
    if snapshot.kind == WHISPER:
        recheck_whisper(evidence, io=io, cancel=cancel)
    elif data is None or {
        name: (len(value), hashlib.sha256(value).hexdigest()) for name, value in data.items()
    } != {entry.name: (entry.size, entry.sha256) for entry in files}:
        raise ArtifactError("DIARIZATION_MODEL_CHECKSUM", "SOURCE_CHANGED")
    _cancelled(cancel)
    _reserve(parent or Path(tempfile.gettempdir()), sum(entry.size for entry in files), io)
    try:
        directory = io.mkdtemp(parent)
    except OSError:
        raise ArtifactError("INPUT_INVALID", "BUNDLE_CREATE_FAILED") from None
    names = tuple(entry.name for entry in files)
    guards: list[Guard] = []
    try:
        root = Path(snapshot.root)
        for entry in files:
            target = directory / entry.name
            if data is None:
                _copy(root / entry.name, target, entry, io, cancel)
            else:
                with io.open_new(target) as writer:
                    io.write(writer, data[entry.name])
        if snapshot.kind == WHISPER and (
            _identity(root, io) != snapshot.root_identity
            or _inputs(root, io) != _expected_inputs(snapshot)
        ):
            # Another folder, or a loader input that appeared/vanished while copying.
            raise ArtifactError("MODEL_CHECKSUM_MISMATCH", "SOURCE_CHANGED")
        for entry in files:
            guards.append(io.guard(directory / entry.name, directory=False))
        guards.append(io.guard(directory, directory=True))
        _verify_bundle(directory, files, io, cancel)  # the sealed bytes, read again
        return FrozenModelBundle(snapshot, directory, names, guards, io)
    except BaseException as error:
        for guard in guards:
            guard.release()
        _remove_owned(directory, names, io)
        if isinstance(error, ArtifactError | ProviderError):
            raise
        if isinstance(error, OSError):
            code = "RESOURCE_EXHAUSTED" if error.errno == errno.ENOSPC else "INPUT_INVALID"
            raise ArtifactError(code, "BUNDLE_WRITE_FAILED") from None
        if isinstance(error, ValidationError):
            raise ArtifactError("INPUT_INVALID", "BUNDLE_WRITE_FAILED") from None
        raise


class _Use:
    def __init__(self, bundle: FrozenModelBundle, evidence: ModelUseEvidence) -> None:
        self.bundle, self.evidence, self.users = bundle, evidence, 0


_BUNDLES: dict[str, _Use] = {}
_PENDING: list[FrozenModelBundle] = []
_LOCK = threading.Lock()


def _close_now(bundle: FrozenModelBundle) -> bool:
    if bundle.close():
        return True
    with _LOCK:
        if bundle not in _PENDING:
            _PENDING.append(bundle)  # "임시 모델 사본 정리 대기": retried, never elsewhere
    return False


def _sweep(keep: ModelUseEvidence | None) -> list[FrozenModelBundle]:
    """Idle bundles no confirmation can use any more (caller closes them unlocked)."""
    stale = []
    for record, use in list(_BUNDLES.items()):
        same_place = keep is not None and (
            use.evidence.snapshot.root_identity,
            use.evidence.snapshot.kind,
        ) == (keep.snapshot.root_identity, keep.snapshot.kind)
        replaced = same_place and keep is not None and record != keep.record_id
        if use.users == 0 and (replaced or not use.evidence.valid()):
            del _BUNDLES[record]
            stale.append(use.bundle)
    return stale


def _recheck_source(
    evidence: ModelUseEvidence, data: dict[str, bytes] | None, io: ArtifactIo, cancel: Any
) -> None:
    """The per-Job source check before an already sealed copy is used again."""
    snapshot = evidence.snapshot
    if snapshot.kind == WHISPER:
        recheck_whisper(evidence, io=io, cancel=cancel)
        return
    _cancelled(cancel)
    expected = {
        entry.name: (entry.size, entry.sha256)
        for entry in (
            *(e for e in snapshot.entries if e.state == PRESENT),
            *snapshot.terms.license_files,
        )
    }
    if (
        data is None
        or {name: (len(value), hashlib.sha256(value).hexdigest()) for name, value in data.items()}
        != expected
    ):
        raise ArtifactError("DIARIZATION_MODEL_CHECKSUM", "SOURCE_CHANGED")


def _retire(record: str, use: _Use) -> None:
    with _LOCK:
        if use.users != 0 or _BUNDLES.get(record) is not use:
            return  # another Job still reads it: it is retired when that Job ends
        del _BUNDLES[record]
    _close_now(use.bundle)


def _retry_pending() -> None:
    with _LOCK:
        pending = list(_PENDING)
        _PENDING.clear()
    for bundle in pending:
        _close_now(bundle)


def acquire(
    evidence: ModelUseEvidence,
    *,
    data: dict[str, bytes] | None = None,
    parent: Path | None = None,
    io: ArtifactIo | None = None,
    cancel: Any = None,
) -> FrozenModelBundle:
    """The sealed bundle of this confirmation for one Job (G13R-03 a).

    Every Job re-checks the original source first. The same confirmation then reuses
    its already sealed copy (guards held) instead of copying the model again; another
    confirmation of the same folder retires the idle older copy. A Job hands the copy
    back with ``release`` only after its child's exit ACK; nothing else ever closes a
    copy in use.
    """
    io = io or ArtifactIo()
    if not isinstance(evidence, ModelUseEvidence) or not evidence.valid():
        raise ArtifactError("CAPABILITY_UNSUPPORTED", "MODEL_CONFIRMATION_REQUIRED")
    with _LOCK:
        stale = _sweep(evidence)
        use = _BUNDLES.get(evidence.record_id)
        if use is not None and not use.bundle.sealed:
            del _BUNDLES[evidence.record_id]
            use = None
    for bundle in stale:
        _close_now(bundle)
    _retry_pending()
    if use is not None:
        try:
            _recheck_source(evidence, data, io, cancel)
        except ArtifactError as error:
            if error.code != "CANCELLED":
                _retire(evidence.record_id, use)  # its source changed: never usable again
            raise
        with _LOCK:
            if use.bundle.sealed and _BUNDLES.get(evidence.record_id) is use:
                use.users += 1
                return use.bundle
    bundle = freeze(evidence, data=data, parent=parent, io=io, cancel=cancel)
    with _LOCK:
        current = _BUNDLES.get(evidence.record_id)
        if current is None or not current.bundle.sealed:
            current = _BUNDLES[evidence.record_id] = _Use(bundle, evidence)
            current.users = 1
            return bundle
        current.users += 1
        shared = current.bundle
    _close_now(bundle)  # another Job sealed the same confirmation meanwhile
    return shared


def release(bundle: FrozenModelBundle) -> bool:
    """A Job's use ends (after its child's exit ACK). The copy stays sealed for the next
    Job of the same confirmation; a copy that was never shared is closed now. False:
    its cleanup is pending."""
    with _LOCK:
        for use in _BUNDLES.values():
            if use.bundle is bundle:
                use.users = max(0, use.users - 1)
                return True
    return _close_now(bundle)


def release_idle() -> int:
    """Close every copy no Job uses (shutdown, model deletion); retry pending cleanups.
    Returns how many copies still wait for their cleanup."""
    with _LOCK:
        idle = [
            record
            for record, use in _BUNDLES.items()
            if use.users == 0 or not use.bundle.sealed  # unused, or already closed
        ]
        bundles = [_BUNDLES.pop(record).bundle for record in idle]
    _retry_pending()
    for bundle in bundles:
        _close_now(bundle)
    return cleanup_pending()


def cleanup_pending() -> int:
    with _LOCK:
        return len(_PENDING)


def _description_entries(description: object, kind: str) -> tuple[Path, tuple[FileEntry, ...], str]:
    try:
        if not isinstance(description, dict) or description.get("kind") != kind:
            raise ValueError
        entries = tuple(FileEntry(*row) for row in description["entries"])
        digest = artifact_digest(kind, LOADERS[kind], entries)
        if digest != description["artifact_digest"] or description["loader"] != LOADERS[kind]:
            raise ValueError
        return Path(description["directory"]), entries, digest
    except (KeyError, TypeError, ValueError):
        raise ArtifactError("MODEL_CHECKSUM_MISMATCH", "BUNDLE_DESCRIPTION") from None


def whisper_files(
    description: object, io: ArtifactIo | None = None
) -> tuple[dict[str, Any], list[BinaryIO], str]:
    """Child side: the files mapping of the pinned SDK, read from the sealed bundle only.

    Small inputs are bytes; model.bin is a reader of the bundle copy (no full Python
    bytes copy). The tokenizer is always supplied (no path/Hub fallback) and a missing
    preprocessor is the fixed default bytes. Every byte is compared with the bundle's
    digest first; the identifier given to the SDK is the bundle id, never a path.
    """
    io = io or ArtifactIo()
    directory, entries, digest = _description_entries(description, WHISPER)
    directory = local_path(directory, io)
    licenses = description.get("licenses", []) if isinstance(description, dict) else []
    expected = {entry.name for entry in entries if entry.state == PRESENT}
    _exact_listing(directory, expected | {str(name) for name in licenses}, io)
    mapping: dict[str, Any] = {}
    handles: list[BinaryIO] = []
    try:
        for entry in entries:
            if entry.state == ABSENT_DEFAULT:
                mapping[entry.name] = PREPROCESSOR_DEFAULT
                continue
            if entry.state == ABSENT:
                continue
            keep = entry.name != "model.bin"
            size, sha, data = hash_file(directory / entry.name, io, keep=keep)
            if (size, sha) != (entry.size, entry.sha256):
                raise ArtifactError("MODEL_CHECKSUM_MISMATCH", "BUNDLE_CHANGED")
            if keep:
                mapping[entry.name] = data
            else:
                stream = io.open_read(directory / entry.name)
                handles.append(stream)
                mapping[entry.name] = stream
        if not mapping.get("tokenizer.json") or "model.bin" not in mapping:
            raise ArtifactError("MODEL_MISSING")
        return mapping, handles, digest
    except BaseException:
        for stream in handles:
            stream.close()
        raise


def diarization_files(description: object, io: ArtifactIo | None = None) -> dict[str, Path]:
    """Child side: the sealed bundle's model paths, each compared with its digest first."""
    io = io or ArtifactIo()
    directory, entries, _ = _description_entries(description, DIARIZATION)
    directory = local_path(directory, io)
    licenses = description.get("licenses", []) if isinstance(description, dict) else []
    _exact_listing(directory, {entry.name for entry in entries} | {str(n) for n in licenses}, io)
    paths: dict[str, Path] = {}
    for entry in entries:
        size, sha, _ = hash_file(directory / entry.name, io)
        if (size, sha) != (entry.size, entry.sha256):
            raise ArtifactError("DIARIZATION_MODEL_CHECKSUM", "BUNDLE_CHANGED")
        paths[entry.name] = directory / entry.name
    return paths


__all__ = [
    "MANAGED",
    "acquire",
    "cleanup_pending",
    "release",
    "release_idle",
    "ArtifactError",
    "ArtifactIo",
    "FrozenModelBundle",
    "Guard",
    "diarization_files",
    "diarization_snapshot",
    "freeze",
    "hash_file",
    "local_path",
    "managed_snapshot",
    "recheck_whisper",
    "whisper_files",
    "whisper_snapshot",
]
