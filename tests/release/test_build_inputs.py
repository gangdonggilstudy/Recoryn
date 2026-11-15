"""Build input snapshots preserve exact bytes and reject mixed concurrent edits."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import release_manager as manager


def builder() -> Any:
    path = Path(__file__).resolve().parents[2] / "scripts" / "build_release.py"
    spec = importlib.util.spec_from_file_location("recoryn_build_release_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_tree(tmp_path: Path) -> Path:
    root = tmp_path / "repository"
    for name in (
        "LICENSE",
        "pyproject.toml",
        "scripts/build_release.py",
        "src/recoryn/__init__.py",
        "packaging/entry_gui.py",
        "packaging/recoryn.spec",
        "requirements-desktop.txt",
    ):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(("synthetic input " + name).encode())
    (root / "src" / "recoryn" / "model.bin").write_bytes(b"must not be copied")
    return root


def test_snapshot_includes_packager_entries_spec_and_exact_source(tmp_path: Path) -> None:
    root = source_tree(tmp_path)
    destination = tmp_path / "candidate" / "inputs"
    builder().snapshot_inputs(root, destination)
    records = manager.read_json(destination / "build-inputs.json")["files"]
    names = {record["path"] for record in records}
    assert names == {
        "LICENSE",
        "pyproject.toml",
        "scripts/build_release.py",
        "src/recoryn/__init__.py",
        "packaging/entry_gui.py",
        "packaging/recoryn.spec",
        "requirements-desktop.txt",
    }
    for record in records:
        assert (destination / record["path"]).read_bytes() == (root / record["path"]).read_bytes()
        assert record["sha256"] == manager.digest(destination / record["path"])
    assert not (destination / "src" / "recoryn" / "model.bin").exists()
    before = (destination / "build-inputs.json").read_bytes()
    with pytest.raises(FileExistsError):
        builder().snapshot_inputs(root, destination)
    assert (destination / "build-inputs.json").read_bytes() == before


def test_snapshot_rejects_changes_to_already_copied_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = source_tree(tmp_path)
    destination = tmp_path / "inputs"
    original = shutil.copyfile

    def edit(source: Path, target: Path) -> Any:
        result = original(source, target)
        if source == root / "src" / "recoryn" / "__init__.py":
            (root / "LICENSE").write_bytes(b"concurrent edit after LICENSE copy")
        return result

    monkeypatch.setattr(shutil, "copyfile", edit)
    with pytest.raises(manager.ReleaseError, match="SOURCE_CHANGED"):
        builder().snapshot_inputs(root, destination)
    assert not (destination / "build-inputs.json").exists()
    assert (root / "LICENSE").read_bytes() == b"concurrent edit after LICENSE copy"


def test_snapshot_rejects_output_within_collected_inputs(tmp_path: Path) -> None:
    root = source_tree(tmp_path)
    destination = root / "packaging" / "candidate"
    with pytest.raises(manager.ReleaseError, match="OVERLAPS_SOURCE"):
        builder().snapshot_inputs(root, destination)
    assert not destination.exists()


def test_snapshot_carries_pinned_notice_texts_but_no_other_packaging_data(
    tmp_path: Path,
) -> None:
    # L03: release notices are build inputs with exact bytes; arbitrary data is not.
    root = source_tree(tmp_path)
    notices = root / "packaging" / "notices"
    notices.mkdir()
    (notices / "LGPL-3.0.txt").write_bytes(b"verbatim license text\r\n")
    (notices / "SOURCES.json").write_text('{"schema_version":1,"files":[]}')
    # L-P05: third-party texts live in nested folders and keep their exact bytes.
    nested = notices / "qt" / "qtbase" / "src" / "3rdparty" / "zlib"
    nested.mkdir(parents=True)
    (nested / "LICENSE").write_bytes(b"zlib terms without extension\r\n")
    (root / "packaging" / "extra.dat").write_bytes(b"not an input")
    destination = tmp_path / "candidate" / "inputs"
    builder().snapshot_inputs(root, destination)
    names = {
        record["path"] for record in manager.read_json(destination / "build-inputs.json")["files"]
    }
    assert {
        "packaging/notices/LGPL-3.0.txt",
        "packaging/notices/SOURCES.json",
        "packaging/notices/qt/qtbase/src/3rdparty/zlib/LICENSE",
    } <= names
    assert "packaging/extra.dat" not in names
    assert (destination / "packaging/notices/qt/qtbase/src/3rdparty/zlib/LICENSE").read_bytes() == (
        b"zlib terms without extension\r\n"
    )
    assert (destination / "packaging/notices/LGPL-3.0.txt").read_bytes() == (
        b"verbatim license text\r\n"
    )


def test_pyinstaller_path_excludes_host_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    # A Git Bash PATH once let PyInstaller collect Git's mingw64 OpenSSL DLLs.
    module = builder()
    monkeypatch.setenv("SystemRoot", r"X:\Win")
    monkeypatch.setenv("PATH", r"C:\Program Files\Git\mingw64\bin;C:\tools")
    monkeypatch.setattr(module.sys, "executable", r"V:\venv\Scripts\python.exe")
    monkeypatch.setattr(module.sys, "base_prefix", r"P:\Python313")
    assert module.isolated_path().split(";") == [
        r"V:\venv\Scripts",
        r"P:\Python313",
        r"P:\Python313\DLLs",
        r"X:\Win\System32",
        r"X:\Win",
    ]


def test_builder_rechecks_recorded_toc_destinations_and_sources() -> None:
    # L02-P03: the recorded Analysis TOC is re-checked independently of the spec.
    module = builder()
    toc = {
        "pure": [["av", "C:/venv/Lib/site-packages/av/__init__.py", "PYMODULE"]],
        "binaries": [
            ["vendor/avcodec-62.dll", "C:/venv/Lib/site-packages/av.libs/avcodec-62.dll", "BINARY"],
            [
                "PySide6/avcodec-63.dll",
                "C:/venv/Lib/site-packages/PySide6/avcodec-63.dll",
                "BINARY",
            ],
            ["PySide6/Qt6Pdf.dll", "C:/venv/Lib/site-packages/PySide6/Qt6Pdf.dll", "BINARY"],
            # L01 D7: Qt's own FFmpeg and both media backends are excluded too.
            [
                "PySide6/plugins/multimedia/windowsmediaplugin.dll",
                "C:/venv/Lib/site-packages/PySide6/plugins/multimedia/windowsmediaplugin.dll",
                "BINARY",
            ],
        ],
        "datas": [["notes/README", "C:/Users/av/README", "DATA"]],
    }
    assert module.excluded_toc_rows(toc) == [
        "PySide6/Qt6Pdf.dll <- C:/venv/Lib/site-packages/PySide6/Qt6Pdf.dll",
        "PySide6/avcodec-63.dll <- C:/venv/Lib/site-packages/PySide6/avcodec-63.dll",
        "PySide6/plugins/multimedia/windowsmediaplugin.dll <- "
        "C:/venv/Lib/site-packages/PySide6/plugins/multimedia/windowsmediaplugin.dll",
        "vendor/avcodec-62.dll <- C:/venv/Lib/site-packages/av.libs/avcodec-62.dll",
    ]


VERIFIED = {"status": "PCM_SINK_PLAYED_MUTED_FROM_EXACT_FRAME", "positions_ms": [2200, 2650]}


@pytest.mark.parametrize(
    ("result", "code"),
    [
        ({"status": "PASS", "playback": VERIFIED}, None),
        ({"status": "PLAYBACK_NOT_VERIFIED", "playback": VERIFIED}, "FROZEN_SMOKE_FAILED"),
        # L04-P01: the original counterexample, a NOT_RUN probe wrapped in a top PASS.
        (
            {"status": "PASS", "playback": {"status": "NO_AUDIO_OUTPUT_DEVICE_NOT_RUN"}},
            "FROZEN_SMOKE_PLAYBACK_NOT_VERIFIED",
        ),
        ({"status": "PASS"}, "FROZEN_SMOKE_PLAYBACK_NOT_VERIFIED"),
        (
            {"status": "PASS", "playback": "PCM_SINK_PLAYED_MUTED_FROM_EXACT_FRAME"},
            "FROZEN_SMOKE_PLAYBACK_NOT_VERIFIED",
        ),
        (
            {"status": "PASS", "playback": {"status": "LOADED_SEEKED_PLAYED_MUTED_SILENCE"}},
            "FROZEN_SMOKE_PLAYBACK_NOT_VERIFIED",
        ),
    ],
)
def test_builder_requires_verified_playback_in_smoke(result: dict[str, Any], code: str | None):
    module = builder()
    if code is None:
        assert module.smoke_verdict(result) is None
    else:
        with pytest.raises(manager.ReleaseError, match=code):
            module.smoke_verdict(result)


# L01 D9: markers of the PyPI CTranslate2 wheel's Intel/NVIDIA runtimes, by hand.
PYPI_MARKERS = [
    b"CUDA driver version is insufficient for CUDA runtime version",
    b"cudaGetDeviceCount",
    b"nvcuda.dll",
    b"cublas64_12.dll",
    b"Intel(R) oneAPI Math Kernel Library Version 2025.3",
    b"libiomp5md.dll",
]


@pytest.mark.parametrize("marker", PYPI_MARKERS)
def test_builder_finds_each_intel_or_nvidia_marker(marker: bytes) -> None:
    clean = b"MZ" + b"\x00" * 64 + b"dnnl_sgemm spdlog cpu_features vcomp140.dll"
    assert builder().ctranslate2_string_violations(clean) == []
    assert builder().ctranslate2_string_violations(clean + marker)


def test_builder_requires_the_cpu_build_files(tmp_path: Path) -> None:
    package = tmp_path / "ctranslate2"
    package.mkdir()
    assert builder().ctranslate2_cpu_violations(package, {"files": {}}) == [
        "missing ctranslate2.dll"
    ]


def test_builder_pins_the_cpu_only_ctranslate2_build() -> None:
    source = (Path(__file__).resolve().parents[2] / "scripts" / "build_release.py").read_text(
        encoding="utf-8"
    )
    assert '("ctranslate2", "4.9.0+recoryn.cpu1")' in source
    assert '("ctranslate2", "4.9.0")' not in source


# --- L06-01/03: the CPU-only CTranslate2 gate, with hand-written oracles. ---


@pytest.mark.parametrize(
    ("imports", "expected"),
    [
        (["KERNEL32.dll", "MSVCP140.dll", "VCOMP140.DLL"], []),
        (["KERNEL32.dll", "VCOMP140.DLL", "LIBIOMP5MD.DLL"], ["import libiomp5md.dll"]),
        (["vcomp140.dll", "cudart64_12.dll"], ["import cudart64_12.dll"]),
        (["vcomp140.dll", "nvcuda.dll"], ["import nvcuda.dll"]),
        (["vcomp140.dll", "cublasLt64_12.dll"], ["import cublaslt64_12.dll"]),
        (["vcomp140.dll", "cudnn64_9.dll"], ["import cudnn64_9.dll"]),
        (["vcomp140.dll", "mkl_rt.2.dll"], ["import mkl_rt.2.dll"]),
        (["KERNEL32.dll"], ["no vcomp140.dll import"]),  # not the MSVC OpenMP build
    ],
)
def test_ctranslate2_import_table(imports: list[str], expected: list[str]) -> None:
    assert builder().ctranslate2_import_violations(imports) == expected


@pytest.mark.parametrize(
    "data",
    [
        b"..CUDAGETDEVICECOUNT..",  # re-cased
        b"..Intel(r) ONEAPI Math Kernel LIBRARY..",
        "libiomp5md".encode("utf-16-le"),  # wide string
        "nvcuda.DLL".encode("utf-16-le"),
    ],
)
def test_ctranslate2_markers_are_not_bypassed_by_case_or_encoding(data: bytes) -> None:
    assert builder().ctranslate2_string_violations(b"MZ" + data)


def test_pe_imports_combine_regular_and_delay_imports(monkeypatch: pytest.MonkeyPatch) -> None:
    module = builder()
    parsed: list[object] = []

    class Image:
        DIRECTORY_ENTRY_IMPORT = [SimpleNamespace(dll=b"KERNEL32.dll")]
        DIRECTORY_ENTRY_DELAY_IMPORT = [SimpleNamespace(dll=b"cudart64_12.dll")]

        def __init__(self, path: str, fast_load: bool) -> None:
            assert fast_load

        def parse_data_directories(self, directories: list[object]) -> None:
            parsed.extend(directories)

        def close(self) -> None:
            parsed.append("closed")

    fake = SimpleNamespace(
        PE=Image,
        DIRECTORY_ENTRY={
            "IMAGE_DIRECTORY_ENTRY_IMPORT": 1,
            "IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT": 13,
        },
    )
    real_import = importlib.import_module
    monkeypatch.setattr(
        importlib, "import_module", lambda name: fake if name == "pefile" else real_import(name)
    )
    assert module.pe_imports(Path("ctranslate2.dll")) == ["KERNEL32.dll", "cudart64_12.dll"]
    assert parsed == [1, 13, "closed"]  # delay imports are parsed, the image is released


PINNED_FILES = ("ctranslate2.dll", "vcomp140.dll", "_ext.cp313-win_amd64.pyd")


def _package(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    package = tmp_path / "ctranslate2"
    package.mkdir()
    files = {}
    for index, name in enumerate(PINNED_FILES):
        (package / name).write_bytes(b"MZ-pinned-" + bytes([index]))
        files[name] = hashlib.sha256((package / name).read_bytes()).hexdigest()
    return package, {"schema_version": 1, "files": files}


def test_ctranslate2_pin_accepts_exact_bytes_and_names_each_drift(tmp_path: Path) -> None:
    module = builder()
    package, pin = _package(tmp_path)
    assert module.ctranslate2_pin_violations(package, pin) == []
    (package / "vcomp140.dll").write_bytes(b"MZ-other-openmp")  # same name, other bytes
    (package / "_ext.cp313-win_amd64.pyd").unlink()
    assert module.ctranslate2_pin_violations(package, pin) == [
        "missing _ext.cp313-win_amd64.pyd",
        "hash vcomp140.dll",
    ]


@pytest.mark.parametrize("damage", ["schema", "file_set", "short_hash"])
def test_ctranslate2_pin_record_is_validated(tmp_path: Path, damage: str) -> None:
    _, pin = _package(tmp_path)
    if damage == "schema":
        pin["schema_version"] = 2
    elif damage == "file_set":
        pin["files"]["libiomp5md.dll"] = "0" * 64
    else:
        pin["files"]["ctranslate2.dll"] = "0" * 63
    (tmp_path / "packaging").mkdir()
    (tmp_path / "packaging" / "ctranslate2-cpu.json").write_text(json.dumps(pin), encoding="utf-8")
    with pytest.raises(manager.ReleaseError, match="CTRANSLATE2_PIN_INVALID"):
        builder().ctranslate2_pin(tmp_path)


def test_committed_pin_matches_the_build_script_and_release_pins() -> None:
    root = Path(__file__).resolve().parents[2]
    pin = builder().ctranslate2_pin(root)
    spec = importlib.util.spec_from_file_location(
        "recoryn_ct2_build_test", root / "scripts" / "build_ctranslate2_cpu.py"
    )
    assert spec is not None and spec.loader is not None
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    assert pin["version"] == script.LOCAL_VERSION == "4.9.0+recoryn.cpu1"
    assert pin["files"]["vcomp140.dll"] == script.VCOMP_SHA256
    assert pin["toolchain"] == script.TOOLCHAIN
    assert pin["sources"]["ctranslate2"]["commit"] == script.CT2_COMMIT
