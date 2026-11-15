"""Opt-in GPU runtime (L01 D10). Case space: docs/testing/l07-gpu-runtime-cases.md.

Wheels here are hand-made zips with a matching fake pin and catalog; nothing is
downloaded, no DLL is loaded (the loader is a spy) and no GPU is used. Each review
counterexample (L07-01..05, L07-U01..U05) has its own test below.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import io
import marshal
import os
import queue
import stat
import sys
import threading
import zipfile
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from recoryn.domain import StateConflict, ValidationError
from recoryn.models import gpu_runtime as gpu
from recoryn.models.manager import FileSpec, ModelSpec

WINDOWS = pytest.mark.skipif(sys.platform != "win32", reason="Windows sharing semantics")
BLOCK = (
    b'if sys.platform == "win32":\r\n'
    b"    BLOCK_RAN = True\r\n"
    b"    if False:\r\n"
    b"        ctypes.CDLL(library)\r\n"
)


def init_source(*, devices: int = 1, origin: bytes = b"verified-source", block: bytes = BLOCK):
    return (
        b"import sys\r\n\r\n"
        + block
        + b"\r\nORIGIN = '"
        + origin
        + b"'\r\nCUDA_DEVICES = "
        + str(devices).encode()
        + b"\r\ndef get_cuda_device_count():\r\n    return CUDA_DEVICES\r\n"
        + b"from ctranslate2 import models\r\n"
    )


def ct2_members(init: bytes | None = None) -> dict[str, bytes]:
    return {
        "ctranslate2/__init__.py": init_source() if init is None else init,
        "ctranslate2/_ext.cp313-win_amd64.pyd": b"MZ-ext",
        "ctranslate2/ctranslate2.dll": b"MZ-ct2",
        "ctranslate2/libiomp5md.dll": b"MZ-omp",
        "ctranslate2/models/__init__.py": b"KIND = 'runtime-models'\r\n",
        # Present in the official wheel but never extracted:
        "ctranslate2/cudnn64_9.dll": b"MZ-cudnn",
        "ctranslate2/converters/__init__.py": b"raise RuntimeError('not extracted')\n",
        "ctranslate2-4.9.0.dist-info/METADATA": b"Name: ctranslate2\n",
    }


def cublas_members() -> dict[str, bytes]:
    return {
        "nvidia/cublas/bin/cublas64_12.dll": b"MZ-cublas",
        "nvidia/cublas/bin/cublasLt64_12.dll": b"MZ-cublaslt",
        "nvidia/cublas/bin/nvblas64_12.dll": b"MZ-nvblas",  # never extracted
        "nvidia/cublas/include/cublas.h": b"/* header */",  # never extracted
        "nvidia_cublas_cu12-12.8.4.1.dist-info/License.txt": b"NVIDIA terms",
    }


CATALOG_NAMES = {
    gpu.CT2_WHEEL.path: (
        "ctranslate2/__init__.py",
        "ctranslate2/_ext.cp313-win_amd64.pyd",
        "ctranslate2/ctranslate2.dll",
        "ctranslate2/libiomp5md.dll",
        "ctranslate2/models/__init__.py",
    ),
    gpu.CUBLAS_WHEEL.path: (
        "nvidia/cublas/bin/cublas64_12.dll",
        "nvidia/cublas/bin/cublasLt64_12.dll",
        "nvidia_cublas_cu12-12.8.4.1.dist-info/License.txt",
    ),
}
EXPECTED_FILES = {name for names in CATALOG_NAMES.values() for name in names}


def zip_bytes(members: dict[str, bytes], *, links: tuple[str, ...] = ()) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in members.items():
            info = zipfile.ZipInfo(name)
            if name in links:
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, data)
    return buffer.getvalue()


def catalog_for(ct2: dict[str, bytes], cublas: dict[str, bytes]) -> dict[str, Any]:
    sources = {gpu.CT2_WHEEL.path: ct2, gpu.CUBLAS_WHEEL.path: cublas}
    return {
        wheel: tuple(
            gpu.Member(
                name, len(sources[wheel][name]), hashlib.sha256(sources[wheel][name]).hexdigest()
            )
            for name in names
        )
        for wheel, names in CATALOG_NAMES.items()
    }


def fake_spec(ct2: bytes, cublas: bytes) -> ModelSpec:
    def pin(item: FileSpec, data: bytes) -> FileSpec:
        return FileSpec(item.path, item.url, len(data), hashlib.sha256(data).hexdigest())

    files = (pin(gpu.CT2_WHEEL, ct2), pin(gpu.CUBLAS_WHEEL, cublas))
    return ModelSpec(gpu.RUNTIME_ID, "other", "MIT", gpu.SPEC.license_url, files)


def use_fakes(
    monkeypatch: pytest.MonkeyPatch,
    ct2: dict[str, bytes],
    cublas: dict[str, bytes],
    *,
    catalog_from: tuple[dict[str, bytes], dict[str, bytes]] | None = None,
) -> tuple[bytes, bytes]:
    """Pin the given wheels and use the catalog of ``catalog_from`` (default: them)."""
    ct2_zip, cublas_zip = zip_bytes(ct2), zip_bytes(cublas)
    monkeypatch.setattr(gpu, "SPEC", fake_spec(ct2_zip, cublas_zip))
    monkeypatch.setattr(gpu, "CATALOG", catalog_for(*(catalog_from or (ct2, cublas))))
    start, end, _ = gpu.INIT_BLOCK
    monkeypatch.setattr(gpu, "INIT_BLOCK", (start, end, hashlib.sha256(BLOCK).hexdigest()))
    monkeypatch.setattr(gpu, "supported", lambda: True)
    return ct2_zip, cublas_zip


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    ct2, cublas = use_fakes(monkeypatch, ct2_members(), cublas_members())
    state = SimpleNamespace(calls=[], data={gpu.CT2_WHEEL.url: ct2, gpu.CUBLAS_WHEEL.url: cublas})

    def downloader(url: str, offset: int) -> Iterator[bytes]:
        state.calls.append(url)
        yield state.data[url][offset:]

    state.downloader = downloader
    return state


def tree(path: Path) -> set[str]:
    return {item.relative_to(path).as_posix() for item in path.rglob("*") if item.is_file()}


# --- Pinned plan and catalog M ---


def test_plan_pins_two_official_files_and_four_terms() -> None:
    assert [(item.path, item.size, item.sha256) for item in gpu.SPEC.files] == [
        (
            "ctranslate2-4.9.0-cp313-cp313-win_amd64.whl",
            20_408_731,
            "d009840a95a5ced75563da030d1aa79dba85c7f280a658e518d575aed40ef095",
        ),
        (
            "nvidia_cublas_cu12-12.8.4.1-py3-none-win_amd64.whl",
            567_544_208,
            "47e9b82132fa8d2b4944e708049229601448aaad7e6f296f630f2d1a32de35af",
        ),
    ]
    assert all(item.url.startswith("https://files.pythonhosted.org/") for item in gpu.SPEC.files)
    assert gpu.DOWNLOAD_BYTES == 587_952_939
    names = " ".join(item.name for item in gpu.TERMS)
    for required in ("NVIDIA CUDA Toolkit", "Intel Simplified", "Intel End User", "MIT"):
        assert required in names
    assert all(item.url.startswith("https://") for item in gpu.TERMS)


def test_catalog_is_the_reviewed_member_list() -> None:
    script = Path(__file__).resolve().parents[2] / "scripts" / "gpu_runtime_catalog.py"
    spec = importlib.util.spec_from_file_location("gpu_runtime_catalog", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # The derivation script and the source name the same members for the same wheels.
    assert {wheel: tuple(m.path for m in rows) for wheel, rows in gpu.CATALOG.items()} == {
        wheel: tuple(names) for wheel, names in module.MEMBERS.items()
    }
    found = gpu.members()
    assert len(found) == 11 and all(gpu._member_ok(name) for name in found)
    assert all(m.size > 0 and len(m.sha256) == 64 for m in found.values())
    assert set(gpu.DLL_LOAD_ORDER) <= set(found) and gpu.INIT_MEMBER in found
    assert not any("cudnn" in name or "/converters/" in name for name in found)
    assert gpu.INIT_BLOCK[2] == "1cf2cac0a98a9a00eff4b3f0a1cb86385b2fce8c4751df92d185c268fb8d5087"


# --- Consent and download D ---


def test_no_download_without_approval(tmp_path: Path, served: SimpleNamespace) -> None:
    manager = gpu.GpuRuntimeManager(tmp_path, downloader=served.downloader)
    with pytest.raises(ValidationError, match="MODEL_DOWNLOAD_REQUIRES_APPROVAL"):
        manager.install(approved=False)
    assert served.calls == [] and manager.status() == "NOT_INSTALLED"


def test_unsupported_environment_never_downloads(
    tmp_path: Path, served: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gpu, "supported", lambda: False)
    manager = gpu.GpuRuntimeManager(tmp_path, downloader=served.downloader)
    with pytest.raises(StateConflict, match="GPU_RUNTIME_UNSUPPORTED"):
        manager.install(approved=True)
    assert served.calls == []


def test_install_extracts_exactly_the_catalog_and_drops_the_wheels(
    tmp_path: Path, served: SimpleNamespace
) -> None:
    manager = gpu.GpuRuntimeManager(tmp_path, downloader=served.downloader)
    active = manager.install(approved=True)
    assert tree(active) == EXPECTED_FILES  # no cudnn, converters, headers or local manifest
    assert manager.status() == "READY" and manager.verify() == active
    assert sorted(path.name for path in tmp_path.iterdir()) == [gpu.RUNTIME_ID, "downloads"]
    assert not any((tmp_path / "downloads").rglob("*.whl"))
    assert len(served.calls) == 2


def test_wrong_downloaded_bytes_never_activate(tmp_path: Path, served: SimpleNamespace) -> None:
    served.data[gpu.CUBLAS_WHEEL.url] = b"tampered" + served.data[gpu.CUBLAS_WHEEL.url][8:]
    manager = gpu.GpuRuntimeManager(tmp_path, downloader=served.downloader)
    with pytest.raises((ValidationError, StateConflict)):
        manager.install(approved=True)
    assert manager.status() == "NOT_INSTALLED"


@pytest.mark.parametrize(
    "boundary", ["before", "after_download", "during_extract", "before_publish"]
)
def test_cancel_until_publish_leaves_no_runtime(
    tmp_path: Path, served: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    """L07-04 / L07-U05: a cancel observed at any boundary before the publish wins."""
    cancel = threading.Event()
    manager = gpu.GpuRuntimeManager(tmp_path, downloader=served.downloader)
    if boundary == "before":
        cancel.set()
    elif boundary == "after_download":
        fetch = manager._downloads.install

        def fetch_then_cancel(*args: Any, **kwargs: Any) -> Path:
            path = fetch(*args, **kwargs)
            cancel.set()
            return path

        monkeypatch.setattr(manager._downloads, "install", fetch_then_cancel)
    elif boundary == "during_extract":
        write = gpu.write_all

        def write_then_cancel(stream: Any, data: bytes) -> None:
            write(stream, data)
            cancel.set()

        monkeypatch.setattr(gpu, "write_all", write_then_cancel)
    else:
        check = gpu.exact_file_set

        def checked_then_cancel(site: Path) -> bool:
            result = check(site)
            if site.name.startswith(".extract-"):
                cancel.set()
            return result

        monkeypatch.setattr(gpu, "exact_file_set", checked_then_cancel)
    with pytest.raises(StateConflict, match="MODEL_DOWNLOAD_CANCELLED"):
        manager.install(approved=True, cancel=cancel)
    assert manager.status() == "NOT_INSTALLED"
    assert not any(path.name.startswith(".extract-") for path in tmp_path.iterdir())
    assert served.calls == ([] if boundary == "before" else served.calls)


def test_cancel_interrupts_a_large_member_within_one_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The 674 MB cuBLAS member must not be written to the end after a cancel."""
    ct2 = ct2_members()
    ct2["ctranslate2/ctranslate2.dll"] = b"MZ" + bytes(3 * 1024 * 1024)
    ct2_zip, cublas_zip = use_fakes(monkeypatch, ct2, cublas_members())
    data = {gpu.CT2_WHEEL.url: ct2_zip, gpu.CUBLAS_WHEEL.url: cublas_zip}
    cancel = threading.Event()
    writes: list[int] = []
    write = gpu.write_all

    def counted(stream: Any, block: bytes) -> None:
        write(stream, block)
        writes.append(len(block))
        if len(block) == 1024 * 1024:
            cancel.set()

    monkeypatch.setattr(gpu, "write_all", counted)

    def downloader(url: str, offset: int) -> Iterator[bytes]:
        body = data[url][offset:]
        yield from (body[index : index + 65536] for index in range(0, len(body), 65536))

    manager = gpu.GpuRuntimeManager(tmp_path, downloader=downloader)
    with pytest.raises(StateConflict, match="MODEL_DOWNLOAD_CANCELLED"):
        manager.install(approved=True, cancel=cancel)
    assert writes.count(1024 * 1024) == 1 and manager.status() == "NOT_INSTALLED"


def test_cancel_after_publish_is_too_late_and_install_succeeds(
    tmp_path: Path, served: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    cancel = threading.Event()
    manager = gpu.GpuRuntimeManager(tmp_path, downloader=served.downloader)
    delete = manager._downloads.delete
    monkeypatch.setattr(
        manager._downloads, "delete", lambda model_id: (cancel.set(), delete(model_id))[1]
    )
    assert manager.install(approved=True, cancel=cancel) == manager.active
    assert cancel.is_set() and manager.status() == "READY"


def test_cleanup_failure_after_publish_still_succeeds(
    tmp_path: Path, served: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """L07-05: removing the downloads is not part of the install's outcome."""
    manager = gpu.GpuRuntimeManager(tmp_path, downloader=served.downloader)

    def denied(model_id: str) -> None:
        raise PermissionError(13, "synthetic: in use")

    monkeypatch.setattr(manager._downloads, "delete", denied)
    assert manager.install(approved=True) == manager.active
    assert manager.status() == "READY"


def test_retry_after_extract_failure_reuses_the_verified_download(
    tmp_path: Path, served: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """L07-05: a failed extract neither activates nor blocks the retry."""
    manager = gpu.GpuRuntimeManager(tmp_path, downloader=served.downloader)
    real = gpu.extract
    monkeypatch.setattr(
        gpu, "extract", lambda *args: (_ for _ in ()).throw(OSError(28, "synthetic: no space"))
    )
    with pytest.raises(OSError):
        manager.install(approved=True)
    assert manager.status() == "NOT_INSTALLED" and len(served.calls) == 2
    monkeypatch.setattr(gpu, "extract", real)
    assert manager.install(approved=True) == manager.active
    assert manager.status() == "READY" and len(served.calls) == 2  # not fetched again


def test_retry_refetches_a_damaged_earlier_download(
    tmp_path: Path, served: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = gpu.GpuRuntimeManager(tmp_path, downloader=served.downloader)
    real = gpu.extract
    monkeypatch.setattr(gpu, "extract", lambda *args: (_ for _ in ()).throw(OSError(28, "x")))
    with pytest.raises(OSError):
        manager.install(approved=True)
    wheel = tmp_path / "downloads" / gpu.RUNTIME_ID / gpu.CT2_WHEEL.path
    wheel.write_bytes(b"x" * wheel.stat().st_size)
    monkeypatch.setattr(gpu, "extract", real)
    assert manager.install(approved=True) == manager.active
    assert len(served.calls) == 4 and manager.status() == "READY"


# --- Extraction X ---


def _crafted(case: str) -> tuple[dict[str, bytes], dict[str, bytes], tuple[str, ...]]:
    ct2, cublas = ct2_members(), cublas_members()
    links: tuple[str, ...] = ()
    if case == "traversal":
        ct2["ctranslate2/../../escape.dll"] = b"x"
    elif case == "absolute":
        ct2["C:/Windows/escape.dll"] = b"x"
    elif case == "backslash_traversal":
        # zipfile turns "\\" into "/" on Windows, so this must fail as a traversal.
        ct2["ctranslate2\\..\\..\\escape.dll"] = b"x"
    elif case == "symlink":
        links = ("ctranslate2/ctranslate2.dll",)
    elif case == "missing_member":
        del cublas["nvidia/cublas/bin/cublasLt64_12.dll"]
    elif case == "member_changed":
        ct2["ctranslate2/ctranslate2.dll"] = b"MZ-CT2"  # same size, other bytes
    elif case == "member_resized":
        ct2["ctranslate2/ctranslate2.dll"] = b"MZ-ct2-longer"
    return ct2, cublas, links


@pytest.mark.parametrize(
    "case",
    [
        "traversal",
        "absolute",
        "backslash_traversal",
        "duplicate",
        "symlink",
        "missing_member",
        "crc",
        "member_changed",
        "member_resized",
    ],
)
def test_unsafe_or_foreign_archives_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    ct2, cublas, links = _crafted(case)
    ct2_zip, cublas_zip = zip_bytes(ct2, links=links), zip_bytes(cublas)
    if case == "duplicate":
        buffer = io.BytesIO(ct2_zip)
        with zipfile.ZipFile(buffer, "a") as archive, pytest.warns(UserWarning):
            archive.writestr("ctranslate2/ctranslate2.dll", b"MZ-second")
        ct2_zip = buffer.getvalue()
    if case == "crc":
        cublas_zip = cublas_zip.replace(b"MZ-cublaslt", b"MZ-CUBLASLT", 1)
    use_fakes(monkeypatch, ct2_members(), cublas_members())  # the reviewed catalog
    monkeypatch.setattr(gpu, "SPEC", fake_spec(ct2_zip, cublas_zip))  # pins match the zips
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    (wheels / gpu.CT2_WHEEL.path).write_bytes(ct2_zip)
    (wheels / gpu.CUBLAS_WHEEL.path).write_bytes(cublas_zip)
    (tmp_path / "target").mkdir()
    with pytest.raises(ValidationError, match="GPU_RUNTIME_ARCHIVE_INVALID"):
        gpu.extract(wheels, tmp_path / "target")


def test_wheel_replaced_after_download_check_is_refused(
    tmp_path: Path, served: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """L07-02: extraction re-checks the pin; a swapped verified wheel never activates."""
    manager = gpu.GpuRuntimeManager(tmp_path, downloader=served.downloader)
    fetch = manager._downloads.install
    swapped = zip_bytes(ct2_members(init_source(origin=b"archive-replaced")))

    def fetch_then_swap(*args: Any, **kwargs: Any) -> Path:
        path = fetch(*args, **kwargs)
        (path / gpu.CT2_WHEEL.path).write_bytes(swapped)
        return path

    monkeypatch.setattr(manager._downloads, "install", fetch_then_swap)
    with pytest.raises(ValidationError, match="GPU_RUNTIME_ARCHIVE_INVALID"):
        manager.install(approved=True)
    assert manager.status() == "NOT_INSTALLED"


def test_wheel_differing_only_outside_the_catalog_is_refused(
    tmp_path: Path, served: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """L07-02: extraction uses the pinned archive itself, not just matching members."""
    manager = gpu.GpuRuntimeManager(tmp_path, downloader=served.downloader)
    fetch = manager._downloads.install
    other = ct2_members()
    other["ctranslate2-4.9.0.dist-info/METADATA"] = b"Name: something-else\n"
    swapped = zip_bytes(other)

    def fetch_then_swap(*args: Any, **kwargs: Any) -> Path:
        path = fetch(*args, **kwargs)
        (path / gpu.CT2_WHEEL.path).write_bytes(swapped)
        return path

    monkeypatch.setattr(manager._downloads, "install", fetch_then_swap)
    with pytest.raises(ValidationError, match="GPU_RUNTIME_ARCHIVE_INVALID"):
        manager.install(approved=True)
    assert manager.status() == "NOT_INSTALLED"


@WINDOWS
def test_wheel_cannot_be_rewritten_while_it_is_extracted(
    tmp_path: Path, served: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = gpu.GpuRuntimeManager(tmp_path, downloader=served.downloader)
    attempts: list[str] = []
    write = gpu.write_all

    def write_and_try_swap(stream: Any, data: bytes) -> None:
        write(stream, data)
        if not attempts:
            wheel = tmp_path / "downloads" / gpu.RUNTIME_ID / gpu.CT2_WHEEL.path
            try:
                wheel.open("r+b").close()
                attempts.append("WRITE_ALLOWED")
            except PermissionError:
                attempts.append("WRITE_BLOCKED")

    monkeypatch.setattr(gpu, "write_all", write_and_try_swap)
    manager.install(approved=True)
    assert attempts == ["WRITE_BLOCKED"] and manager.status() == "READY"


# --- Status S and verify V ---


@pytest.fixture
def installed(tmp_path: Path, served: SimpleNamespace) -> gpu.GpuRuntimeManager:
    manager = gpu.GpuRuntimeManager(tmp_path / "gpu-runtime", downloader=served.downloader)
    manager.install(approved=True)
    return manager


@pytest.mark.parametrize(
    "change",
    ["missing", "resized", "extra_dll", "pycache", "local_manifest", "rocm_folder"],
)
def test_status_requires_exactly_the_catalog(installed: gpu.GpuRuntimeManager, change: str) -> None:
    active = installed.active
    dll = active / "nvidia" / "cublas" / "bin" / "cublas64_12.dll"
    if change == "missing":
        dll.unlink()
    elif change == "resized":
        dll.write_bytes(dll.read_bytes() + b"!")
    elif change == "extra_dll":
        (active / "ctranslate2" / "UNKNOWN-VENDOR.dll").write_bytes(b"MZ")
    elif change == "pycache":
        (active / "ctranslate2" / "__pycache__").mkdir()
        (active / "ctranslate2" / "__pycache__" / "__init__.cpython-313.pyc").write_bytes(b"x")
    elif change == "local_manifest":
        (active / "runtime.json").write_text("{}", encoding="utf-8")
    else:
        (active / "_rocm_sdk_core" / "bin").mkdir(parents=True)
    assert installed.status() == "DAMAGED"
    with pytest.raises(ValidationError, match="GPU_RUNTIME_DAMAGED"):
        installed.verify()


def test_verify_detects_a_same_size_change(installed: gpu.GpuRuntimeManager) -> None:
    dll = installed.active / "ctranslate2" / "ctranslate2.dll"
    data = bytearray(dll.read_bytes())
    data[-1] ^= 1
    dll.write_bytes(bytes(data))
    assert installed.status() == "READY"  # sizes only
    with pytest.raises(ValidationError, match="GPU_RUNTIME_DAMAGED"):
        installed.verify()


def test_remove_returns_to_not_installed_and_sweeps(installed: gpu.GpuRuntimeManager) -> None:
    (installed.root / ".remove-left-behind").mkdir()
    (installed.root / ".extract-left-behind").mkdir()
    installed.remove()
    assert installed.status() == "NOT_INSTALLED"
    assert sorted(path.name for path in installed.root.iterdir()) == ["downloads"]
    assert not any((installed.root / "downloads").iterdir())


@WINDOWS
def test_remove_while_a_worker_holds_the_runtime_is_refused(
    installed: gpu.GpuRuntimeManager,
) -> None:
    """L07-U03 safety net: a runtime in use is never half-deleted."""
    pinned = gpu._PinnedRuntime(installed.active)
    try:
        with pytest.raises(StateConflict, match="GPU_RUNTIME_IN_USE"):
            installed.remove()
        assert installed.status() == "READY" and tree(installed.active) == EXPECTED_FILES
    finally:
        pinned.close()
    installed.remove()
    assert installed.status() == "NOT_INSTALLED"


# --- Activation A ---


def _drop_ct2_modules() -> None:
    for name in [name for name in sys.modules if name.split(".")[0] == "ctranslate2"]:
        del sys.modules[name]


@pytest.fixture
def activation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[SimpleNamespace]:
    _drop_ct2_modules()
    monkeypatch.setattr(sys, "meta_path", list(sys.meta_path))
    loads: list[Path] = []
    dll_dirs: list[str] = []
    monkeypatch.setattr(gpu, "_load_library", lambda path: loads.append(Path(path)) or object())
    system = tmp_path / "System32"
    system.mkdir()
    (system / "nvcuda.dll").write_bytes(b"MZ-driver")
    monkeypatch.setattr(gpu, "_system_directory", lambda: system)
    monkeypatch.setattr(gpu, "_held", [])
    monkeypatch.setattr(gpu, "_libraries", [])
    monkeypatch.setattr(os, "add_dll_directory", dll_dirs.append, raising=False)
    state = SimpleNamespace(loads=loads, dll_dirs=dll_dirs, system=system)
    try:
        yield state
    finally:
        for pinned in gpu._held:
            pinned.close()
        _drop_ct2_modules()


def expected_loads(state: SimpleNamespace, manager: gpu.GpuRuntimeManager) -> list[Path]:
    return [state.system / "nvcuda.dll"] + [
        manager.active.joinpath(*name.split("/")) for name in gpu.DLL_LOAD_ORDER
    ]


def test_activation_runs_verified_sources_and_loads_dlls_by_path(
    installed: gpu.GpuRuntimeManager, activation: SimpleNamespace
) -> None:
    location = gpu.activate(installed.root)
    assert Path(location).is_relative_to(installed.active.resolve())
    module = sys.modules["ctranslate2"]
    assert module.ORIGIN == "verified-source" and not hasattr(module, "BLOCK_RAN")
    assert module.models.KIND == "runtime-models"
    assert type(module.__spec__.loader) is gpu._SourceLoader  # no bytecode loader
    # The driver from System32, then every runtime DLL by absolute path; no DLL folders.
    assert activation.loads == expected_loads(activation, installed)
    assert activation.dll_dirs == []
    assert not any(installed.active.rglob("*.pyc"))


def _timestamp_pyc(source: Path, code_text: str) -> bytes:
    info = source.stat()
    code = compile(code_text, str(source), "exec")
    return (
        importlib.util.MAGIC_NUMBER
        + (0).to_bytes(4, "little")
        + (int(info.st_mtime) & 0xFFFFFFFF).to_bytes(4, "little")
        + (info.st_size & 0xFFFFFFFF).to_bytes(4, "little")
        + marshal.dumps(code)
    )


@pytest.mark.parametrize("file_set_check", ["real", "bypassed"])
def test_stale_bytecode_is_never_executed(
    installed: gpu.GpuRuntimeManager,
    activation: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    file_set_check: str,
) -> None:
    """L07-01 (A/extra_pyc): a valid timestamp pyc next to a verified source."""
    init = installed.active / "ctranslate2" / "__init__.py"
    cache = Path(importlib.util.cache_from_source(str(init)))
    cache.parent.mkdir()
    witness = "ORIGIN = 'unverified-witness'\ndef get_cuda_device_count():\n    return 1\n"
    cache.write_bytes(_timestamp_pyc(init, witness))
    if file_set_check == "real":
        with pytest.raises(ValidationError, match="GPU_RUNTIME_DAMAGED"):
            gpu.activate(installed.root)
        assert activation.loads == [] and "ctranslate2" not in sys.modules
    else:
        # Even if the exact file-set check were bypassed, the loader runs verified bytes.
        monkeypatch.setattr(gpu, "exact_file_set", lambda site: True)
        gpu.activate(installed.root)
        assert sys.modules["ctranslate2"].ORIGIN == "verified-source"


def test_unknown_dll_in_the_package_folder_is_refused_before_loading(
    installed: gpu.GpuRuntimeManager, activation: SimpleNamespace
) -> None:
    """L07-01 (B/extra_dll_selection): nothing is loaded, not even the driver."""
    (installed.active / "ctranslate2" / "UNKNOWN-VENDOR.dll").write_bytes(b"MZ-unknown")
    with pytest.raises(ValidationError, match="GPU_RUNTIME_DAMAGED"):
        gpu.activate(installed.root)
    assert activation.loads == [] and gpu.sys.meta_path == sys.meta_path


def test_environment_dll_paths_are_never_used(
    installed: gpu.GpuRuntimeManager,
    activation: SimpleNamespace,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """L07-01 (C): HIP_PATH and the official block's folder search are not consulted."""
    foreign = tmp_path / "foreign" / "bin"
    foreign.mkdir(parents=True)
    (foreign / "cublas64_12.dll").write_bytes(b"MZ-foreign")
    monkeypatch.setenv("HIP_PATH", str(foreign.parent))
    gpu.activate(installed.root)
    assert activation.dll_dirs == [] and activation.loads == expected_loads(activation, installed)


def test_runtime_modules_never_fall_through_to_another_ctranslate2(
    installed: gpu.GpuRuntimeManager,
    activation: SimpleNamespace,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    other = tmp_path / "bundled" / "ctranslate2"
    (other / "converters").mkdir(parents=True)
    (other / "__init__.py").write_text("ORIGIN = 'bundled-cpu'\n", encoding="utf-8")
    (other / "converters" / "__init__.py").write_text("ORIGIN = 'bundled'\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(other.parent))
    gpu.activate(installed.root)
    assert sys.modules["ctranslate2"].ORIGIN == "verified-source"
    # A file created in the runtime after activation (which no lock can prevent) is not a
    # module either: names outside the catalog never reach another finder.
    planted = installed.active / "ctranslate2" / "converters"
    planted.mkdir()
    (planted / "__init__.py").write_text("ORIGIN = 'planted-after'\n", encoding="utf-8")
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("ctranslate2.converters")
    assert "ctranslate2.converters" not in sys.modules


@WINDOWS
def test_files_cannot_change_between_verification_and_import(
    installed: gpu.GpuRuntimeManager, activation: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """L07-03: the barrier of the review, at the first load after verification."""
    outcomes: dict[str, str] = {}
    active = installed.active
    init = active / "ctranslate2" / "__init__.py"

    def attempt(label: str, action: Any) -> None:
        try:
            action()
            outcomes[label] = "ALLOWED"
        except PermissionError:
            outcomes[label] = "BLOCKED"

    def load_after_swap_attempts(path: Path) -> object:
        if not outcomes:
            attempt("rewrite_init", lambda: init.open("r+b").close())
            attempt("delete_dll", lambda: (active / "ctranslate2" / "ctranslate2.dll").unlink())
            attempt("rename_init", lambda: os.replace(init, init.with_name("moved.py")))
            attempt("rename_runtime", lambda: os.replace(active, active.with_name("moved")))
        activation.loads.append(Path(path))
        return object()

    monkeypatch.setattr(gpu, "_load_library", load_after_swap_attempts)
    gpu.activate(installed.root)
    assert set(outcomes.values()) == {"BLOCKED"} and len(outcomes) == 4
    assert sys.modules["ctranslate2"].ORIGIN == "verified-source"


@pytest.mark.parametrize("imported", ["ctranslate2", "ctranslate2.models"])
def test_activation_after_import_is_refused(
    installed: gpu.GpuRuntimeManager,
    activation: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    imported: str,
) -> None:
    monkeypatch.setitem(sys.modules, imported, SimpleNamespace())
    with pytest.raises(StateConflict, match="GPU_RUNTIME_LATE"):
        gpu.activate(installed.root)
    assert activation.loads == []


def test_activation_without_driver_loads_nothing(
    installed: gpu.GpuRuntimeManager, activation: SimpleNamespace
) -> None:
    (activation.system / "nvcuda.dll").unlink()
    with pytest.raises(StateConflict, match="GPU_RUNTIME_UNAVAILABLE"):
        gpu.activate(installed.root)
    assert activation.loads == []


def test_activation_of_a_damaged_runtime_is_refused(
    installed: gpu.GpuRuntimeManager, activation: SimpleNamespace
) -> None:
    (installed.active / "ctranslate2" / "ctranslate2.dll").write_bytes(b"MZ-swp")
    with pytest.raises(ValidationError, match="GPU_RUNTIME_DAMAGED"):
        gpu.activate(installed.root)
    assert activation.loads == []


def test_activation_without_runtime_is_not_installed(
    tmp_path: Path, activation: SimpleNamespace, served: SimpleNamespace
) -> None:
    with pytest.raises(StateConflict, match="GPU_RUNTIME_NOT_INSTALLED"):
        gpu.activate(tmp_path / "absent")
    assert activation.loads == []


@pytest.mark.parametrize("variant", ["no_cuda_device", "init_block_changed"])
def test_activation_codes_for_other_init_files(
    tmp_path: Path,
    activation: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    variant: str,
) -> None:
    init = (
        init_source(devices=0)
        if variant == "no_cuda_device"
        else init_source(block=BLOCK.replace(b"BLOCK_RAN = True", b"BLOCK_RAN = 1"))
    )
    ct2, cublas = use_fakes(monkeypatch, ct2_members(init), cublas_members())
    data = {gpu.CT2_WHEEL.url: ct2, gpu.CUBLAS_WHEEL.url: cublas}
    manager = gpu.GpuRuntimeManager(
        tmp_path / "gpu-runtime", downloader=lambda url, offset: iter([data[url][offset:]])
    )
    manager.install(approved=True)
    if variant == "no_cuda_device":
        with pytest.raises(StateConflict, match="GPU_RUNTIME_UNAVAILABLE"):
            gpu.activate(manager.root)
    else:
        with pytest.raises(ValidationError, match="GPU_RUNTIME_DAMAGED"):
            gpu.activate(manager.root)
        assert activation.loads == []


# --- Worker W ---


def test_worker_answers_each_request_with_the_explicit_code(tmp_path: Path) -> None:
    from recoryn.app import inference

    requests: queue.Queue[Any] = queue.Queue()
    replies: queue.Queue[Any] = queue.Queue()
    for item in ((1, "first"), (2, "second"), None):
        requests.put(item)
    inference._worker("model", "cuda", requests, replies, str(tmp_path / "absent"))
    answers = [replies.get_nowait(), replies.get_nowait()]
    assert answers == [(1, "GPU_RUNTIME_NOT_INSTALLED"), (2, "GPU_RUNTIME_NOT_INSTALLED")]


@pytest.mark.parametrize(
    ("runtime", "supported", "expected"),
    [
        (None, True, None),  # a CUDA-capable CTranslate2 is already the installed one
        ("runtime", False, "GPU_RUNTIME_UNSUPPORTED"),
        ("absent", True, "GPU_RUNTIME_NOT_INSTALLED"),
    ],
)
def test_worker_activation_codes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    runtime: str | None,
    supported: bool,
    expected: str | None,
) -> None:
    from recoryn.app import inference

    monkeypatch.setattr(gpu, "supported", lambda: supported)
    root = None if runtime is None else str(tmp_path / runtime)
    assert inference._activate_gpu(root) == expected


def test_parent_raises_and_records_the_worker_gpu_code(tmp_path: Path) -> None:
    from recoryn.app.inference import LocalSTTProcess
    from recoryn.providers import ProviderError, STTRequest

    process = LocalSTTProcess(tmp_path, device="cuda", gpu_runtime=tmp_path)
    process._process = SimpleNamespace(is_alive=lambda: True)
    process._requests, process._replies = queue.Queue(), queue.Queue()
    process._start = lambda: None  # type: ignore[method-assign]
    process._replies.put((1, "GPU_RUNTIME_DAMAGED"))
    assert process.gpu_failure is None
    with pytest.raises(ProviderError, match="GPU_RUNTIME_DAMAGED"):
        process.transcribe(STTRequest(tmp_path / "clip.wav", "ko"))
    assert process.gpu_failure == "GPU_RUNTIME_DAMAGED"
    cpu = LocalSTTProcess(tmp_path, device="cpu", gpu_runtime=tmp_path)
    assert cpu.gpu_runtime is None and cpu.gpu_failure is None


# --- Device source U ---


@pytest.mark.parametrize("policy", ["CPU_ONLY", "GPU_ONLY", "GPU_WITH_CPU_FALLBACK_ALLOWED"])
@pytest.mark.parametrize("blocked", [False, True])
@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("status", ["NOT_INSTALLED", "READY", "DAMAGED"])
def test_gpu_source_table(policy: str, blocked: bool, native: bool, status: str) -> None:
    calls: list[str] = []

    def native_cuda() -> bool:
        calls.append("native")
        return native

    def runtime_status() -> str:
        calls.append("status")
        return status

    # Independent oracle: a GPU needs a GPU policy and a CUDA source; the native one
    # wins, and the runtime counts only when READY and not blocked.
    gpu_policy = policy != "CPU_ONLY"
    if gpu_policy and native:
        expected = "native"
    elif gpu_policy and status == "READY" and not blocked:
        expected = "runtime"
    else:
        expected = "none"
    assert gpu.gpu_source(policy, native_cuda, runtime_status, runtime_blocked=blocked) == expected
    if not gpu_policy:
        assert calls == []  # no CTranslate2 import or file checks when no GPU can be used
    if blocked or native:
        assert "status" not in calls


# --- Task boundary (L07-U02) ---


@pytest.mark.parametrize(
    "code",
    [
        "RESOURCE_GPU_UNAVAILABLE",
        "GPU_RUNTIME_UNSUPPORTED",
        "GPU_RUNTIME_IN_USE",
        "GPU_RUNTIME_DAMAGED",
    ],
)
def test_task_keeps_gpu_codes_for_the_user(code: str) -> None:
    from recoryn.ui.tasks import Task

    def fail() -> None:
        raise StateConflict(code)

    seen: list[str] = []
    task = Task(fail)
    task.signals.failed.connect(seen.append)
    task.run()
    assert seen == [code]


# --- Screen: consent, pending change, release, wording (L07-U03/U04) ---


@pytest.fixture
def panel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from recoryn.ui.models import ModelPanel

    released: list[str] = []
    widget = ModelPanel(tmp_path / "models", release_gpu=lambda: released.append("release"))
    held: list[Any] = []
    monkeypatch.setattr(widget.pool, "start", held.append)  # queued, never run here
    widget.held, widget.released = held, released
    try:
        yield widget
    finally:
        widget.task = None
        widget.shutdown()


def test_panel_never_downloads_without_consent(panel: Any) -> None:
    assert panel.gpu.root == panel.manager.root.parent / "gpu-runtime"
    panel.download_gpu()
    assert panel.held == [] and "동의" in panel.gpu_status.text() and not panel.gpu_busy
    panel.gpu_approval.setChecked(True)
    panel.download_gpu()
    assert len(panel.held) == 1 and panel.gpu_busy
    panel.download_gpu()
    assert len(panel.held) == 1  # one model operation at a time


def test_panel_remove_releases_the_worker_first(
    panel: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QMessageBox

    asked: list[str] = []

    def answer(parent: Any, title: str, text: str, *args: Any) -> Any:
        asked.append(text)
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", answer)
    panel.remove_gpu()
    assert panel.released == ["release"] and len(panel.held) == 1 and panel.gpu_busy
    assert "GPU 전용 정책" in asked[0] and "CPU 허용 정책" in asked[0]


def test_panel_remove_stops_when_the_worker_cannot_be_released(
    panel: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)

    def stuck() -> None:
        raise StateConflict("INFERENCE_ACK_PENDING")

    panel.release_gpu = stuck
    panel.remove_gpu()
    assert panel.held == [] and not panel.gpu_busy and "닫지 못했습니다" in panel.gpu_status.text()


def test_panel_states_terms_and_policy_wording(panel: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    text = panel.gpu_terms.toPlainText()
    assert all(item.url in text for item in gpu.TERMS) and f"{gpu.DOWNLOAD_BYTES:,}" in text
    # L07-U04: no unconditional "falls back to CPU"; both policies are named.
    assert "CPU 허용 정책은 CPU로" in text and "GPU 전용 정책은 전사를 시작하지 않습니다" in text
    for state, words in (("NOT_INSTALLED", "받지 않음"), ("READY", "설치됨"), ("DAMAGED", "손상")):
        monkeypatch.setattr(panel.gpu, "status", lambda state=state: state)
        panel.refresh_gpu()
        shown = panel.gpu_status.text()
        assert words in shown and "CPU로 합니다" not in shown
