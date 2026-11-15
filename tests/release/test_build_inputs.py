"""Build input snapshots preserve exact bytes and reject mixed concurrent edits."""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path
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
    (root / "packaging" / "extra.dat").write_bytes(b"not an input")
    destination = tmp_path / "candidate" / "inputs"
    builder().snapshot_inputs(root, destination)
    names = {
        record["path"] for record in manager.read_json(destination / "build-inputs.json")["files"]
    }
    assert {"packaging/notices/LGPL-3.0.txt", "packaging/notices/SOURCES.json"} <= names
    assert "packaging/extra.dat" not in names
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
