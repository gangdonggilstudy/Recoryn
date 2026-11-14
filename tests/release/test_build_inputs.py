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
