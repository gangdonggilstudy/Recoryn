"""실제 임시 파일·독립 hash oracle로 설치/rollback/제거 실패를 검사한다."""

from __future__ import annotations

import hashlib
import json
import os
import runpy
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import release_manager as manager


def artifact(tmp_path: Path, name: str, version: str) -> Path:
    root = tmp_path / name
    root.mkdir()
    (root / "_internal").mkdir()
    (root / "Recoryn.exe").write_bytes(b"MZ-GUI-" + version.encode())
    (root / "Recoryn-CLI.exe").write_bytes(b"MZ-CLI-" + version.encode())
    (root / "_internal" / "Qt6Core.dll").write_bytes(b"dynamic-test-oracle")
    records = [
        {
            "path": str(path.relative_to(root)).replace("\\", "/"),
            "size": len(path.read_bytes()),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in sorted(root.rglob("*"))
        if path.is_file()
    ]
    (root / manager.MANIFEST).write_text(
        json.dumps(
            {"app_id": manager.APP_ID, "schema_version": 1, "version": version, "files": records}
        ),
        encoding="utf-8",
    )
    return root


def test_install_update_rollback_does_not_modify_source_or_user_data(tmp_path: Path) -> None:
    first, second = artifact(tmp_path, "one", "0.2.0"), artifact(tmp_path, "two", "0.2.1")
    data = tmp_path / "Recoryn" / "sessions" / "source.pcm"
    data.parent.mkdir(parents=True)
    data.write_bytes(b"user-original-never-remove")
    before = manager.inventory(first)
    destination = tmp_path / "Programs" / "Recoryn"
    one = manager.install(first, destination)
    two = manager.install(second, destination)
    assert one["current"] != two["current"] and two["previous"] == one["current"]
    assert manager.verify(Path(two["launch"]).parent)["version"] == "0.2.1"
    # Rollback must work when the new application itself has become damaged.
    Path(two["launch"]).write_bytes(b"damaged")
    assert manager.rollback(destination)["current"] == one["current"]
    assert manager.inventory(first) == before
    assert data.read_bytes() == b"user-original-never-remove"
    removed = manager.uninstall(destination)
    assert removed["deactivated"] and not removed["uninstalled"]  # Tampered version is preserved.
    assert removed["pending"] == [two["current"]]
    assert data.read_bytes() == b"user-original-never-remove"
    assert not (destination / "current.json").exists()


def test_uninstall_releases_only_verified_files_and_can_repeat(tmp_path: Path) -> None:
    source = artifact(tmp_path, "source", "1.0")
    target = tmp_path / "Programs" / "Recoryn"
    manager.install(source, target)
    assert manager.uninstall(target) == {
        "uninstalled": True,
        "deactivated": True,
        "pending": [],
        "user_data_preserved": True,
    }
    assert list((target / "versions").iterdir()) == []
    assert manager.uninstall(target)["uninstalled"]
    assert manager.verify(source)["version"] == "1.0"


def test_uninstall_locked_file_is_pending_and_external_retry_finishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = artifact(tmp_path, "source", "1.0")
    target = tmp_path / "Programs" / "Recoryn"
    installed = manager.install(source, target)
    executable = Path(installed["launch"])
    original = Path.unlink

    def locked(path: Path, *args: Any, **kwargs: Any) -> None:
        if path == executable:
            raise PermissionError("owned executable still running")
        original(path, *args, **kwargs)

    with monkeypatch.context() as local:
        local.setattr(Path, "unlink", locked)
        result = manager.uninstall(target)
        assert not result["uninstalled"] and result["deactivated"]
        assert executable.exists() and (executable.parent / manager.MANIFEST).exists()
    assert manager.uninstall(target)["uninstalled"]


def test_activation_failure_preserves_old_pointer_and_staged_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    one, two = artifact(tmp_path, "one", "1"), artifact(tmp_path, "two", "2")
    target = tmp_path / "Programs" / "Recoryn"
    first = manager.install(one, target)
    before = (target / "current.json").read_bytes()
    original = manager.atomic_json

    def fault(path: Path, value: dict[str, Any]) -> None:
        if path.name == "current.json":
            raise OSError("injected activation failure")
        original(path, value)

    with monkeypatch.context() as local:
        local.setattr(manager, "atomic_json", fault)
        with pytest.raises(OSError):
            manager.install(two, target)
    assert (target / "current.json").read_bytes() == before
    assert manager.verify(Path(first["launch"]).parent)["version"] == "1"
    assert len(list((target / "versions").iterdir())) == 2
    assert manager.install(two, target)["previous"] == first["current"]


def test_bad_rollback_target_does_not_change_active_pointer(tmp_path: Path) -> None:
    one, two = artifact(tmp_path, "one", "1"), artifact(tmp_path, "two", "2")
    target = tmp_path / "Programs" / "Recoryn"
    first = manager.install(one, target)
    manager.install(two, target)
    before = (target / "current.json").read_bytes()
    Path(first["launch"]).write_bytes(b"corrupt-previous")
    with pytest.raises(manager.ReleaseError):
        manager.rollback(target)
    assert (target / "current.json").read_bytes() == before


def test_installer_lock_serializes_update_and_refuses_unowned_directory(tmp_path: Path) -> None:
    source = artifact(tmp_path, "source", "1")
    target = tmp_path / "Programs" / "Recoryn"
    manager.install(source, target)
    with manager.installation(target):
        with pytest.raises(OSError):
            manager.install(source, target)
    unowned = tmp_path / "original-recordings"
    unowned.mkdir()
    canary = unowned / "recording.pcm"
    canary.write_bytes(b"preserve")
    with pytest.raises(OSError):
        manager.install(source, unowned)
    assert list(unowned.iterdir()) == [canary]
    with pytest.raises(manager.ReleaseError):
        manager.install(source, source / "subdir")


@pytest.mark.parametrize(
    "path",
    [
        "../escape",
        "/absolute",
        "C:/escape",
        "_internal/CON.txt",
        "_internal/a:ads",
        "_internal/a\\b",
        "a/../b",
        "a. ",
    ],
)
def test_inventory_rejects_traversal_ads_absolute_and_reserved_paths(
    tmp_path: Path, path: str
) -> None:
    source = artifact(tmp_path, "source", "1")
    manifest = manager.read_json(source / manager.MANIFEST)
    manifest["files"][0]["path"] = path
    manager.atomic_json(source / manager.MANIFEST, manifest)
    with pytest.raises(manager.ReleaseError):
        manager.verify(source)


@pytest.mark.parametrize(
    "mutation", ["missing", "changed", "extra", "boolsize", "hash", "case", "weights"]
)
def test_inventory_checks_actual_files_not_declared_success(tmp_path: Path, mutation: str) -> None:
    source = artifact(tmp_path, "source", "1")
    manifest = manager.read_json(source / manager.MANIFEST)
    if mutation == "missing":
        (source / "Recoryn.exe").unlink()
    elif mutation == "changed":
        (source / "Recoryn.exe").write_bytes(b"different")
    elif mutation == "extra":
        (source / "unexpected.txt").write_text("unexpected")
    elif mutation == "weights":
        (source / "model.safetensors").write_bytes(b"test-weight-canary")
        manifest["files"] = manager.inventory(source)
    elif mutation == "boolsize":
        manifest["files"][0]["size"] = True
    elif mutation == "hash":
        manifest["files"][0]["sha256"] = "not-a-digest"
    else:
        manifest["files"].append(
            {**manifest["files"][0], "path": manifest["files"][0]["path"].upper()}
        )
    manager.atomic_json(source / manager.MANIFEST, manifest)
    with pytest.raises(manager.ReleaseError):
        manager.verify(source)


@pytest.mark.parametrize("name", ["entry_gui.py", "entry_cli.py"])
def test_frozen_entries_dispatch_spawn_before_application_imports(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    package = Path(__file__).resolve().parents[2] / "packaging"
    calls = []
    module = ModuleType("multiprocessing")

    def spawn_dispatch() -> None:
        calls.append("spawn")
        raise SystemExit(73)  # Simulate PyInstaller's handled child command line.

    monkeypatch.setattr(module, "freeze_support", spawn_dispatch, raising=False)
    monkeypatch.setitem(sys.modules, "multiprocessing", module)
    monkeypatch.setitem(sys.modules, "recoryn_release", None)  # Any application import must fail.
    runpy.run_path(str(package / name), run_name="inert_import")
    assert calls == []
    with pytest.raises(SystemExit) as stopped:
        runpy.run_path(str(package / name), run_name="__main__")
    assert stopped.value.code == 73 and calls == ["spawn"]


def test_hardlinks_and_parent_paths_are_refused_before_installation(tmp_path: Path) -> None:
    source = artifact(tmp_path, "source", "1")
    canary = tmp_path / "user-original.pcm"
    canary.write_bytes(b"original-not-owned-by-installer")
    os.link(canary, source / "alias.pcm")
    with pytest.raises(manager.ReleaseError, match="HARDLINK"):
        manager.install(source, tmp_path / "Programs" / "Recoryn")
    assert canary.read_bytes() == b"original-not-owned-by-installer"
    with pytest.raises(manager.ReleaseError, match="PARENT_PATH"):
        manager.safe(tmp_path / "fake" / ".." / "original.pcm")


@pytest.mark.parametrize("schema", [True, 2, "1"])
def test_future_and_boolean_manifest_schema_are_not_accepted(tmp_path: Path, schema: Any) -> None:
    source = artifact(tmp_path, "source", "1")
    manifest = manager.read_json(source / manager.MANIFEST)
    manifest["schema_version"] = schema
    manager.atomic_json(source / manager.MANIFEST, manifest)
    with pytest.raises(manager.ReleaseError, match="IDENTITY"):
        manager.verify(source)


def test_ambiguous_metadata_cannot_override_identity(tmp_path: Path) -> None:
    metadata = tmp_path / "ambiguous.json"
    metadata.write_text('{"app_id":"unowned","app_id":"org.recoryn.desktop"}')
    with pytest.raises(manager.ReleaseError, match="DUPLICATE"):
        manager.read_json(metadata)
    metadata.write_text('{"unexpected":NaN}')
    with pytest.raises(manager.ReleaseError, match="NONFINITE"):
        manager.read_json(metadata)


def test_unowned_original_inside_version_is_preserved_on_uninstall(tmp_path: Path) -> None:
    source = artifact(tmp_path, "source", "1")
    target = tmp_path / "Programs" / "Recoryn"
    result = manager.install(source, target)
    canary = Path(result["launch"]).parent / "sessions" / "original.pcm"
    canary.parent.mkdir()
    canary.write_bytes(b"original-media")
    removed = manager.uninstall(target)
    assert removed["deactivated"] and not removed["uninstalled"]
    assert removed["pending"] == [result["current"]]
    assert canary.read_bytes() == b"original-media"


def test_update_and_rollback_reject_invalid_activation_without_replacing_it(tmp_path: Path) -> None:
    source = artifact(tmp_path, "source", "1")
    target = tmp_path / "Programs" / "Recoryn"
    manager.install(source, target)
    pointer = target / "current.json"
    current = manager.read_json(pointer)
    current["schema_version"] = True
    manager.atomic_json(pointer, current)
    before = pointer.read_bytes()
    with pytest.raises(manager.ReleaseError, match="ACTIVATION"):
        manager.install(source, target)
    with pytest.raises(manager.ReleaseError, match="ACTIVATION"):
        manager.rollback(target)
    assert pointer.read_bytes() == before


@pytest.mark.parametrize("suffix", sorted(manager.WEIGHTS))
def test_known_model_serialization_policy_rejects_candidate(tmp_path: Path, suffix: str) -> None:
    source = artifact(tmp_path, "source", "1")
    (source / "_internal" / ("payload" + suffix.upper())).write_bytes(b"synthetic serialized data")
    manifest = manager.read_json(source / manager.MANIFEST)
    manifest["files"] = manager.inventory(source)
    manager.atomic_json(source / manager.MANIFEST, manifest)
    with pytest.raises(manager.ReleaseError, match="BUNDLED_MODEL_WEIGHTS_FORBIDDEN"):
        manager.verify(source)


def test_native_exe_dll_pyd_are_allowed_runtime_files(tmp_path: Path) -> None:
    source = artifact(tmp_path, "source", "1")
    for suffix in (".exe", ".dll", ".pyd"):
        (source / "_internal" / ("runtime" + suffix)).write_bytes(b"synthetic native runtime")
    manifest = manager.read_json(source / manager.MANIFEST)
    manifest["files"] = manager.inventory(source)
    manager.atomic_json(source / manager.MANIFEST, manifest)
    assert manager.verify(source)["version"] == "1"
