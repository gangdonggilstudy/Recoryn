"""Opt-in GPU runtime the user downloads from the official source (license policy L01 D10).

Recoryn bundles a CPU-only CTranslate2 and redistributes no Intel or NVIDIA code. A user
who wants GPU acceleration explicitly accepts the vendors' terms in the app; Recoryn then
fetches the official CTranslate2 4.9.0 wheel and NVIDIA's cuBLAS wheel from PyPI.

Trust is anchored in this source, not in files on disk:

* both wheels are pinned by URL, size and SHA-256, and are re-hashed through a handle that
  blocks writes immediately before extraction;
* only the members in ``CATALOG`` (reviewed size and SHA-256 of each member of the pinned
  wheels) are extracted, and each is checked against it while it is written;
* the active runtime must hold exactly the catalog files; any other file, folder or link
  makes it DAMAGED;
* an inference worker activates it only before CTranslate2 is first imported. It opens every
  catalog file with a handle that blocks writing, deleting and renaming for the rest of the
  process, verifies the bytes read through those handles, executes the Python sources from
  those verified bytes (no bytecode cache), and loads every DLL itself by absolute path. The
  official ``__init__`` block that would search folders and environment paths for DLLs is
  replaced, and the NVIDIA driver is taken from System32 only.

Boundary: like ``storage._safe.check_path``, this is not a sandbox against a process of the
same user, which can write into this process directly; it ensures that files present, left
behind or changed before or during activation are never loaded unverified.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.abc
import importlib.machinery
import importlib.util
import os
import platform
import stat
import sys
import threading
import uuid
import zipfile
import zlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from recoryn.domain import StateConflict, ValidationError
from recoryn.models.manager import FileSpec, ModelManager, ModelSpec
from recoryn.storage._safe import (
    check_path,
    mkdir,
    open_file,
    remove_tree,
    root_path,
    safe_path,
    sync,
    write_all,
)

RUNTIME_ID = "ct2-cuda-4-9-0"
_PYPI = "https://files.pythonhosted.org/packages/"
CT2_WHEEL = FileSpec(
    "ctranslate2-4.9.0-cp313-cp313-win_amd64.whl",
    _PYPI + "3f/71/cd84a3e26cf8a932c7826a4e7d45ddbf2e2899880d6dcc5ad4833169e6da/"
    "ctranslate2-4.9.0-cp313-cp313-win_amd64.whl",
    20_408_731,
    "d009840a95a5ced75563da030d1aa79dba85c7f280a658e518d575aed40ef095",
)
CUBLAS_WHEEL = FileSpec(
    "nvidia_cublas_cu12-12.8.4.1-py3-none-win_amd64.whl",
    _PYPI + "70/61/7d7b3c70186fb651d0fbd35b01dbfc8e755f69fd58f817f3d0f642df20c3/"
    "nvidia_cublas_cu12-12.8.4.1-py3-none-win_amd64.whl",
    567_544_208,
    "47e9b82132fa8d2b4944e708049229601448aaad7e6f296f630f2d1a32de35af",
)
SPEC = ModelSpec(
    RUNTIME_ID,
    "other",
    "LicenseRef-NVIDIA-CUDA-Toolkit-EULA AND LicenseRef-Intel-Simplified-Software-License "
    "AND LicenseRef-Intel-EULA-Developer-Tools AND MIT",
    "https://docs.nvidia.com/cuda/eula/index.html",
    (CT2_WHEEL, CUBLAS_WHEEL),
)


@dataclass(frozen=True, slots=True)
class Terms:
    name: str
    applies_to: str
    url: str


# Shown to the user before any download; accepting them is the user's own act.
TERMS = (
    Terms(
        "NVIDIA CUDA Toolkit End User License Agreement",
        "cuBLAS, and the CUDA runtime code inside the official CTranslate2 wheel",
        "https://docs.nvidia.com/cuda/eula/index.html",
    ),
    Terms(
        "Intel Simplified Software License",
        "Intel oneMKL statically linked in the official CTranslate2 wheel",
        "https://www.intel.com/content/www/us/en/developer/articles/license/"
        "onemkl-license-faq.html",
    ),
    Terms(
        "Intel End User License Agreement for Developer Tools",
        "the Intel OpenMP runtime (libiomp5md.dll) in the official CTranslate2 wheel",
        "https://www.intel.com/content/www/us/en/developer/articles/license/"
        "end-user-license-agreement.html",
    ),
    Terms(
        "MIT License (CTranslate2)",
        "CTranslate2 itself",
        "https://github.com/OpenNMT/CTranslate2/blob/v4.9.0/LICENSE",
    ),
)
DOWNLOAD_BYTES = CT2_WHEEL.size + CUBLAS_WHEEL.size


@dataclass(frozen=True, slots=True)
class Member:
    path: str
    size: int
    sha256: str


# Reviewed members of the pinned wheels; scripts/gpu_runtime_catalog.py derives and checks
# them. Nothing else is extracted. Not extracted on purpose: cudnn64_9.dll (ctranslate2.dll
# never loads it), the converters/specs packages (model conversion only) and dist-info.
CATALOG: dict[str, tuple[Member, ...]] = {
    CT2_WHEEL.path: (
        Member(
            "ctranslate2/__init__.py",
            3_273,
            "825423817ffc8fe663c266490306184a029541c7a026eac43ad089af5cceb6bb",
        ),
        Member(
            "ctranslate2/_ext.cp313-win_amd64.pyd",
            814_080,
            "49b5aebcccfc4788a836aabd97fdb84d9025a0c8afcc51022c304a4b7cf801b7",
        ),
        Member(
            "ctranslate2/ctranslate2.dll",
            61_321_216,
            "a9009ad682a2c5a11f6942c3b8dac68189d629685ef02fbc3e1ab6e4c6082ab8",
        ),
        Member(
            "ctranslate2/extensions.py",
            21_940,
            "90336dd07f4abdf3427373eb446cdf923f4592f9daf388b63b963eadabfa5245",
        ),
        Member(
            "ctranslate2/libiomp5md.dll",
            1_614_192,
            "982233366b0afcda1e0f55a0b134097e35b779613f54ddb69e685e6cd06b755f",
        ),
        Member(
            "ctranslate2/logging.py",
            1_221,
            "3fd7af1ddc6e331fe21efc098c401212afa3e74eb61fae0f979f9f263c44b879",
        ),
        Member(
            "ctranslate2/models/__init__.py",
            589,
            "131121920828abf5a7f6239e7526b0523c9b225ca94c236d788e21f0d303f015",
        ),
        Member(
            "ctranslate2/version.py",
            53,
            "039315f2d55a74d61d695ab9c4207df0b0baeccbdc9f5e2f30513712474bf2bf",
        ),
    ),
    CUBLAS_WHEEL.path: (
        Member(
            "nvidia/cublas/bin/cublas64_12.dll",
            113_716_224,
            "9513540e4ec4c51ee9e7304138c2cc255c29a8c181f9e80c38efa25738becd99",
        ),
        Member(
            "nvidia/cublas/bin/cublasLt64_12.dll",
            674_667_520,
            "b199d1ff892a81b7fd3d57ba1781549609b41500b36008fef326038393ad46c7",
        ),
        Member(
            "nvidia_cublas_cu12-12.8.4.1.dist-info/License.txt",
            59_262,
            "ad6f5853fba0ca0d159d0f58d49ae49830c2f8c93f7a92648b9ce90adb4c6ccd",
        ),
    ),
}
# Loaded by absolute path in this order (each after the DLLs it imports by name).
DLL_LOAD_ORDER = (
    "nvidia/cublas/bin/cublasLt64_12.dll",
    "nvidia/cublas/bin/cublas64_12.dll",
    "ctranslate2/libiomp5md.dll",
    "ctranslate2/ctranslate2.dll",
)
INIT_MEMBER = "ctranslate2/__init__.py"
# The official package init's Windows block: it adds DLL folders found next to the package
# or through HIP_PATH and loads every *.dll in the package folder. It is replaced by the
# DLL loading in ``activate``; its exact bytes are pinned by start, end and SHA-256.
INIT_BLOCK = (
    b'if sys.platform == "win32":',
    b"        ctypes.CDLL(library)\r\n",
    "1cf2cac0a98a9a00eff4b3f0a1cb86385b2fce8c4751df92d185c268fb8d5087",
)
INIT_REPLACEMENT = b"pass  # Recoryn loaded the verified DLLs by absolute path.\r\n"
EXTENSION_SUFFIX = ".cp313-win_amd64.pyd"
_LOAD_LIBRARY_SEARCH_DEFAULT_DIRS = 0x00001000
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def supported() -> bool:
    """The pinned wheels are CPython 3.13 / Windows x64 only."""
    return (
        sys.platform == "win32"
        and sys.version_info[:2] == (3, 13)
        and platform.machine().lower() in ("amd64", "x86_64")
    )


def members() -> dict[str, Member]:
    return {item.path: item for rows in CATALOG.values() for item in rows}


def _directories() -> set[str]:
    found: set[str] = set()
    for name in members():
        parts = name.split("/")[:-1]
        found.update("/".join(parts[: index + 1]) for index in range(len(parts)))
    return found


def _member_ok(name: str) -> bool:
    parts = name.split("/")
    return (
        bool(name)
        and not name.startswith("/")
        and "\\" not in name
        and ":" not in name
        and all(part not in ("", ".", "..") for part in parts)
    )


def _cancelled(cancel: threading.Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise StateConflict("MODEL_DOWNLOAD_CANCELLED")


def _hold(path: Path) -> int:
    """Open ``path`` read-only; on Windows also deny writing, deleting and renaming it
    (and renaming its folders) for as long as the descriptor stays open."""
    check_path(path)
    if sys.platform != "win32":
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    else:
        import ctypes
        import msvcrt
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        create = kernel.CreateFileW
        create.restype = wintypes.HANDLE
        create.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        # GENERIC_READ, FILE_SHARE_READ only, OPEN_EXISTING, OPEN_REPARSE_POINT.
        handle = create(str(path), 0x80000000, 0x1, None, 3, 0x00200000, None)
        if handle in (None, wintypes.HANDLE(-1).value):
            error = ctypes.get_last_error()
            raise OSError(0, ctypes.FormatError(error), str(path), error)
        try:
            fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        except BaseException:
            kernel.CloseHandle(handle)
            raise
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or (
        getattr(info, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT
    ):
        os.close(fd)
        raise ValidationError("GPU_RUNTIME_DAMAGED")
    return fd


def _read(fd: int, limit: int) -> Iterator[bytes]:
    """Blocks of the held file from its start; never more than ``limit + 1`` bytes."""
    os.lseek(fd, 0, os.SEEK_SET)
    remaining = limit + 1
    while remaining > 0 and (block := os.read(fd, min(1024 * 1024, remaining))):
        remaining -= len(block)
        yield block


def _is_link(entry: os.DirEntry[str]) -> bool:
    info = entry.stat(follow_symlinks=False)
    return entry.is_symlink() or bool(
        getattr(info, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT
    )


def exact_file_set(site: Path) -> bool:
    """True when ``site`` holds exactly the catalog files and their folders, no links."""
    files: set[str] = set()
    folders: set[str] = set()
    pending = [("", site)]
    while pending:
        prefix, folder = pending.pop()
        with os.scandir(folder) as entries:
            for entry in entries:
                name = prefix + entry.name
                if _is_link(entry):
                    return False
                if entry.is_dir(follow_symlinks=False):
                    folders.add(name)
                    pending.append((name + "/", Path(entry.path)))
                elif entry.is_file(follow_symlinks=False):
                    files.add(name)
                else:
                    return False
    return files == set(members()) and folders == _directories()


def extract(wheels: Path, target: Path, cancel: threading.Event | None = None) -> None:
    """Extract the catalog members of both pinned wheels into ``target``.

    Each wheel is re-hashed against its pin through a handle that blocks writes and is
    then read through that same handle. A zip that is malformed, repeats or escapes a
    name, links, or whose member differs from the catalog is refused.
    """
    for item in SPEC.files:
        fd = _hold(safe_path(wheels, item.path))
        with os.fdopen(fd, "rb") as stream:
            digest = hashlib.sha256()
            size = 0
            for block in _read(fd, item.size):
                _cancelled(cancel)
                digest.update(block)
                size += len(block)
            if size != item.size or digest.hexdigest() != item.sha256:
                raise ValidationError("GPU_RUNTIME_ARCHIVE_INVALID")
            stream.seek(0)
            try:
                _extract_members(zipfile.ZipFile(stream), item.path, target, cancel)
            except (zipfile.BadZipFile, EOFError, zlib.error, NotImplementedError):
                raise ValidationError("GPU_RUNTIME_ARCHIVE_INVALID") from None


def _extract_members(
    archive: zipfile.ZipFile, wheel: str, target: Path, cancel: threading.Event | None
) -> None:
    infos = archive.infolist()
    names = [info.filename for info in infos]
    if len(set(names)) != len(names) or any(not _member_ok(name) for name in names):
        raise ValidationError("GPU_RUNTIME_ARCHIVE_INVALID")
    by_name = {info.filename: info for info in infos}
    for member in CATALOG[wheel]:
        _cancelled(cancel)
        info = by_name.get(member.path)
        if (
            info is None
            or info.is_dir()
            or stat.S_ISLNK(info.external_attr >> 16)
            or info.file_size != member.size
        ):
            raise ValidationError("GPU_RUNTIME_ARCHIVE_INVALID")
        destination = safe_path(target, *member.path.split("/"))
        mkdir(destination.parent)
        digest = hashlib.sha256()
        size = 0
        with archive.open(info) as source, open_file(destination, "xb") as out:
            while block := source.read(1024 * 1024):
                _cancelled(cancel)
                size += len(block)
                if size > member.size:
                    raise ValidationError("GPU_RUNTIME_ARCHIVE_INVALID")
                digest.update(block)
                write_all(out, block)
            sync(out)
        if size != member.size or digest.hexdigest() != member.sha256:
            raise ValidationError("GPU_RUNTIME_ARCHIVE_INVALID")


class GpuRuntimeManager:
    """Download, extract, check and remove the opt-in GPU runtime under ``root``."""

    def __init__(
        self,
        root: Path,
        *,
        downloader: Callable[[str, int], Iterator[bytes]] | None = None,
    ) -> None:
        self.root = root_path(root)
        self._downloads = ModelManager(safe_path(self.root, "downloads"), downloader=downloader)
        self._lock = threading.Lock()

    @property
    def active(self) -> Path:
        return safe_path(self.root, RUNTIME_ID)

    def generation(self) -> tuple[int, int] | None:
        """Identity of the installed runtime folder; a new install gets a new one."""
        try:
            info = os.stat(self.active)
        except FileNotFoundError:
            return None
        return (info.st_dev, info.st_ino)

    def install(
        self,
        *,
        approved: bool = False,
        cancel: threading.Event | None = None,
        progress: Callable[[int, int], None] | None = None,
    ) -> Path:
        """Fetch, check and publish the runtime. A cancel is honoured until the publish.

        The publish (one folder rename) is the only point the runtime becomes active;
        after it the install has succeeded even if removing the downloads fails.
        """
        if not supported():
            raise StateConflict("GPU_RUNTIME_UNSUPPORTED")
        if not approved:
            # Before any network access: the user has not accepted the vendors' terms.
            raise ValidationError("MODEL_DOWNLOAD_REQUIRES_APPROVAL")
        if not self._lock.acquire(blocking=False):
            raise StateConflict("GPU_RUNTIME_OPERATION_ACTIVE")
        try:
            if self.active.exists():
                raise StateConflict("GPU_RUNTIME_ALREADY_INSTALLED")
            self._sweep()
            _cancelled(cancel)
            wheels = self._wheels(cancel, progress)
            _cancelled(cancel)
            staging = safe_path(self.root, ".extract-" + RUNTIME_ID)
            remove_tree(staging)
            mkdir(staging)
            try:
                extract(wheels, staging, cancel)
                if not exact_file_set(staging):
                    raise ValidationError("GPU_RUNTIME_ARCHIVE_INVALID")
                _cancelled(cancel)  # the last point at which a cancel is honoured
                check_path(self.active)
                os.replace(staging, self.active)
            finally:
                remove_tree(staging)
            try:
                self._downloads.delete(RUNTIME_ID)
            except OSError:
                pass  # only disk space; the next install or removal deletes them
            return self.active
        finally:
            self._lock.release()

    def _wheels(
        self, cancel: threading.Event | None, progress: Callable[[int, int], None] | None
    ) -> Path:
        """Verified wheels: an earlier complete download is re-hashed and reused."""
        if safe_path(self._downloads.root, RUNTIME_ID).exists():
            try:
                return self._downloads.verify(RUNTIME_ID)
            except (OSError, ValueError, TypeError, KeyError):
                self._downloads.delete(RUNTIME_ID)
        return self._downloads.install(SPEC, approved=True, cancel=cancel, progress=progress)

    def _sweep(self) -> None:
        """Best-effort removal of folders left by an interrupted extract or removal."""
        if not self.root.exists():
            return
        for path in self.root.iterdir():
            if path.name.startswith((".extract-", ".remove-")):
                try:
                    remove_tree(path)
                except OSError:
                    pass

    def status(self) -> str:
        """Cheap check (exact file set and sizes); activation re-hashes every file."""
        if not self.active.exists():
            return "NOT_INSTALLED"
        try:
            check_path(self.active)
            if not exact_file_set(self.active):
                return "DAMAGED"
            for name, member in members().items():
                path = safe_path(self.active, *name.split("/"))
                if path.stat().st_size != member.size:
                    return "DAMAGED"
        except (OSError, ValueError):
            return "DAMAGED"
        return "READY"

    def verify(self) -> Path:
        """Full check of the installed files against the catalog (not held afterwards)."""
        if not self.active.exists():
            raise StateConflict("GPU_RUNTIME_NOT_INSTALLED")
        _PinnedRuntime(self.active).close()
        return self.active

    def remove(self) -> None:
        """Retire the runtime with one folder rename, then delete it.

        A worker that activated the runtime holds its files open, which makes the rename
        fail: GPU_RUNTIME_IN_USE, and the runtime stays intact.
        """
        if not self._lock.acquire(blocking=False):
            raise StateConflict("GPU_RUNTIME_OPERATION_ACTIVE")
        try:
            if self.active.exists():
                retired = safe_path(self.root, ".remove-" + uuid.uuid4().hex)
                try:
                    os.replace(self.active, retired)
                except PermissionError:
                    raise StateConflict("GPU_RUNTIME_IN_USE") from None
                try:
                    remove_tree(retired)
                except OSError:
                    pass  # no longer active; the next install or removal sweeps it
            try:
                self._downloads.delete(RUNTIME_ID)
            except OSError:
                pass
            self._sweep()
        finally:
            self._lock.release()


def gpu_source(
    policy: str,
    native_cuda: Callable[[], bool],
    runtime_status: Callable[[], str],
    *,
    runtime_blocked: bool,
) -> str:
    """Where CUDA would come from: "native", "runtime" or "none" (no GPU candidate).

    "native" is a CUDA-capable CTranslate2 already installed (a source run); "runtime"
    is the user's opt-in runtime. ``runtime_blocked`` (a failure of this runtime install
    in this run, or a pending install/removal) excludes only the runtime. CPU_ONLY never
    offers a GPU; the checks are only made when they can matter.
    """
    if policy == "CPU_ONLY":
        return "none"
    if native_cuda():
        return "native"
    if runtime_blocked:
        return "none"
    return "runtime" if runtime_status() == "READY" else "none"


class _PinnedRuntime:
    """Every catalog file held open, verified through its handle, sources kept in memory."""

    def __init__(self, site: Path) -> None:
        self.site = site
        self.fds: dict[str, int] = {}
        self.sources: dict[str, bytes] = {}
        try:
            for name, member in sorted(members().items()):
                fd = _hold(safe_path(site, *name.split("/")))
                self.fds[name] = fd
                digest = hashlib.sha256()
                data = bytearray()
                size = 0
                for block in _read(fd, member.size):
                    size += len(block)
                    digest.update(block)
                    if name.endswith(".py"):
                        data += block
                if size != member.size or digest.hexdigest() != member.sha256:
                    raise ValidationError("GPU_RUNTIME_DAMAGED")
                if name.endswith(".py"):
                    self.sources[name] = bytes(data)
            # With every expected file held, nothing else may be present at all.
            if not exact_file_set(site):
                raise ValidationError("GPU_RUNTIME_DAMAGED")
            self.sources[INIT_MEMBER] = _replace_init_block(self.sources[INIT_MEMBER])
        except BaseException as error:
            self.close()
            if isinstance(error, (OSError, ValueError)):
                raise ValidationError("GPU_RUNTIME_DAMAGED") from None
            raise

    def path(self, name: str) -> Path:
        return safe_path(self.site, *name.split("/"))

    def spec(self, fullname: str) -> importlib.machinery.ModuleSpec:
        base = fullname.replace(".", "/")
        for name, package in ((base + "/__init__.py", True), (base + ".py", False)):
            if name in self.sources:
                origin = self.path(name)
                spec = importlib.machinery.ModuleSpec(
                    fullname, _SourceLoader(self, name), origin=str(origin), is_package=package
                )
                spec.has_location = True
                if package:
                    spec.submodule_search_locations = [str(origin.parent)]
                return spec
        if base + EXTENSION_SUFFIX in self.fds:
            origin = self.path(base + EXTENSION_SUFFIX)
            loader = importlib.machinery.ExtensionFileLoader(fullname, str(origin))
            found = importlib.util.spec_from_file_location(fullname, origin, loader=loader)
            if found is not None:
                return found
        # Never fall through to another ctranslate2 (such as the bundled CPU build).
        raise ModuleNotFoundError(f"No module named {fullname!r}", name=fullname)

    def close(self) -> None:
        for fd in self.fds.values():
            try:
                os.close(fd)
            except OSError:
                pass
        self.fds.clear()


def _replace_init_block(source: bytes) -> bytes:
    start, end, digest = INIT_BLOCK
    if source.count(start) != 1 or source.count(end) != 1:
        raise ValidationError("GPU_RUNTIME_DAMAGED")
    first = source.index(start)
    last = source.index(end) + len(end)
    if last <= first or hashlib.sha256(source[first:last]).hexdigest() != digest:
        raise ValidationError("GPU_RUNTIME_DAMAGED")
    return source[:first] + INIT_REPLACEMENT + source[last:]


class _SourceLoader(importlib.abc.Loader):
    """Execute verified source bytes; never read or write a bytecode cache."""

    def __init__(self, pinned: _PinnedRuntime, name: str) -> None:
        self.pinned, self.name = pinned, name

    def create_module(self, spec: importlib.machinery.ModuleSpec) -> None:
        return None

    def exec_module(self, module: Any) -> None:
        origin = str(self.pinned.path(self.name))
        code = compile(self.pinned.sources[self.name], origin, "exec", dont_inherit=True)
        exec(code, module.__dict__)  # noqa: S102 - verified catalog source


class _RuntimeFinder(importlib.abc.MetaPathFinder):
    """Resolve ``ctranslate2`` and its submodules from the held catalog files only."""

    def __init__(self, pinned: _PinnedRuntime) -> None:
        self.pinned = pinned

    def find_spec(
        self, fullname: str, path: Any = None, target: Any = None
    ) -> importlib.machinery.ModuleSpec | None:
        if fullname != "ctranslate2" and not fullname.startswith("ctranslate2."):
            return None
        return self.pinned.spec(fullname)


def _system_directory() -> Path:
    import ctypes

    buffer = ctypes.create_unicode_buffer(520)
    if not ctypes.windll.kernel32.GetSystemDirectoryW(buffer, len(buffer)):
        raise OSError("GetSystemDirectoryW failed")
    return Path(buffer.value)


def _load_library(path: Path) -> Any:
    import ctypes

    # Dependencies are searched only in the application folder, System32 and the user
    # DLL folders, never in a runtime folder: all runtime DLLs are loaded here by path.
    return ctypes.WinDLL(str(path), winmode=_LOAD_LIBRARY_SEARCH_DEFAULT_DIRS)


# Runtime files stay held (and loaded DLLs referenced) for the life of the process.
_held: list[_PinnedRuntime] = []
_libraries: list[Any] = []


def activate(root: Path) -> str:
    """Make this process import the verified GPU runtime; return its module file.

    Must run before anything imports CTranslate2. Raises GPU_RUNTIME_LATE when it is
    already imported, GPU_RUNTIME_NOT_INSTALLED / GPU_RUNTIME_DAMAGED before any runtime
    code runs, and GPU_RUNTIME_UNAVAILABLE when no driver or CUDA device is usable.
    """
    if any(name == "ctranslate2" or name.startswith("ctranslate2.") for name in sys.modules):
        raise StateConflict("GPU_RUNTIME_LATE")
    manager = GpuRuntimeManager(root)
    if not manager.active.exists():
        raise StateConflict("GPU_RUNTIME_NOT_INSTALLED")
    pinned = _PinnedRuntime(manager.active)
    _held.append(pinned)
    try:
        driver = _system_directory() / "nvcuda.dll"
        if not driver.is_file():
            raise StateConflict("GPU_RUNTIME_UNAVAILABLE")
        _libraries.append(_load_library(driver))
        for name in DLL_LOAD_ORDER:
            _libraries.append(_load_library(pinned.path(name)))
        sys.meta_path.insert(0, _RuntimeFinder(pinned))
        module = importlib.import_module("ctranslate2")
        site = Path(manager.active).resolve()
        for name, loaded in list(sys.modules.items()):
            if name == "ctranslate2" or name.startswith("ctranslate2."):
                origin = getattr(loaded, "__file__", None)
                if origin is None or not Path(origin).resolve().is_relative_to(site):
                    raise StateConflict("GPU_RUNTIME_UNAVAILABLE")
        if int(module.get_cuda_device_count()) <= 0:
            raise StateConflict("GPU_RUNTIME_UNAVAILABLE")
    except StateConflict:
        raise
    except Exception:
        raise StateConflict("GPU_RUNTIME_UNAVAILABLE") from None
    return str(Path(str(module.__file__)).resolve())
