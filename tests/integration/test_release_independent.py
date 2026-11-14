"""BR42 independent install, packaging, and evidence oracles; no real build or EXE."""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import json
import runpy
import socket
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.syspath_prepend(str(ROOT / "packaging"))

    def denied(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("BR42 attempted network access")

    monkeypatch.setattr(socket, "socket", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)
    monkeypatch.setattr(socket, "create_connection", denied)


def candidate(path: Path, version: str = "1", extras: dict[str, bytes] | None = None) -> Path:
    path.mkdir(parents=True)
    payloads = {
        "Recoryn.exe": b"fake-gui-" + version.encode(),
        "Recoryn-CLI.exe": b"fake-cli-" + version.encode(),
        "_internal/Qt6Core.dll": b"fake-dynamic-library",
        **(extras or {}),
    }
    records = []
    for name, data in sorted(payloads.items()):
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        records.append(
            {"path": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        )
    # Match file ordering independently, without the product inventory helper.
    records.sort(key=lambda item: tuple(part.casefold() for part in item["path"].split("/")))
    (path / "release-manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "app_id": "org.recoryn.desktop",
                "version": version,
                "files": records,
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize(
    "malicious",
    [
        "../../outside.pcm",
        "D:/outside.pcm",
        "a/./b",
        "a//b",
        "_internal/file:stream",
        "a\\b",
        "LPT1.txt",
        "file.",
        "file ",
    ],
)
def test_malicious_inventory_never_creates_install_destination(
    tmp_path: Path, malicious: str
) -> None:
    manager = importlib.import_module("release_manager")
    source = candidate(tmp_path / "source")
    manifest_path = source / "release-manifest.json"
    value = json.loads(manifest_path.read_bytes())
    value["files"][0]["path"] = malicious
    manifest_path.write_text(json.dumps(value))
    destination = tmp_path / "Programs" / "Recoryn"
    with pytest.raises(manager.ReleaseError):
        manager.install(source, destination)
    assert not destination.exists()


def test_update_copy_failure_keeps_old_pointer_original_and_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = importlib.import_module("release_manager")
    one, two = candidate(tmp_path / "one", "1"), candidate(tmp_path / "two", "2")
    destination = tmp_path / "Programs" / "Recoryn"
    media = tmp_path / "Recoryn" / "sessions" / "original.pcm"
    media.parent.mkdir(parents=True)
    media.write_bytes(b"independent-user-original")
    manager.install(one, destination)
    pointer = (destination / "current.json").read_bytes()
    copy = manager.shutil.copyfile

    def interrupted(source, target, *args, **kwargs):
        if Path(source) == two / "Recoryn-CLI.exe":
            Path(target).write_bytes(b"torn-copy")
            raise OSError("independent-copy-fault")
        return copy(source, target, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(manager.shutil, "copyfile", interrupted)
        with pytest.raises(OSError):
            manager.install(two, destination)
    assert (destination / "current.json").read_bytes() == pointer
    assert media.read_bytes() == b"independent-user-original"
    assert (two / "Recoryn-CLI.exe").read_bytes() == b"fake-cli-2"
    assert any(path.name.startswith(".staging-") for path in (destination / "versions").iterdir())


@pytest.mark.parametrize("change", ["extra_original", "changed_binary", "hardlink"])
def test_uninstall_preserves_uncertain_version_and_external_original(
    tmp_path: Path, change: str
) -> None:
    manager = importlib.import_module("release_manager")
    source = candidate(tmp_path / "source")
    destination = tmp_path / "Programs" / "Recoryn"
    installed = manager.install(source, destination)
    directory = Path(installed["launch"]).parent
    original = tmp_path / "source-track.pcm"
    original.write_bytes(b"original-canary")
    if change == "extra_original":
        (directory / "source-track.pcm").write_bytes(original.read_bytes())
    elif change == "changed_binary":
        (directory / "Recoryn.exe").write_bytes(b"unknown-modification")
    else:
        (directory / "source-track.pcm").hardlink_to(original)
    before = {
        p.relative_to(directory).as_posix(): p.read_bytes()
        for p in directory.rglob("*")
        if p.is_file()
    }
    result = manager.uninstall(destination)
    assert result["deactivated"] and not result["uninstalled"]
    assert before == {
        p.relative_to(directory).as_posix(): p.read_bytes()
        for p in directory.rglob("*")
        if p.is_file()
    }
    assert original.read_bytes() == b"original-canary"


@pytest.mark.parametrize("entry", ["entry_gui.py", "entry_cli.py"])
def test_frozen_child_dispatch_precedes_even_import_of_app(
    entry: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = ModuleType("multiprocessing")

    def handled_child() -> None:
        raise SystemExit(47)

    fake.freeze_support = handled_child
    monkeypatch.setitem(sys.modules, "multiprocessing", fake)
    monkeypatch.setitem(sys.modules, "recoryn_release", None)
    runpy.run_path(str(ROOT / "packaging" / entry), run_name="unimported_app")
    with pytest.raises(SystemExit) as result:
        runpy.run_path(str(ROOT / "packaging" / entry), run_name="__main__")
    assert result.value.code == 47


@pytest.mark.parametrize(
    "weight", ["model.onnx", "model.ort", "weights.ckpt", "model.tflite", "weights.pkl"]
)
def test_br42_01_known_model_formats_cannot_enter_verified_bundle(
    tmp_path: Path, weight: str
) -> None:
    manager = importlib.import_module("release_manager")
    source = candidate(tmp_path / "source", extras={"_internal/" + weight: b"synthetic-weight"})
    with pytest.raises(manager.ReleaseError, match="BUNDLED_MODEL_WEIGHTS_FORBIDDEN"):
        manager.verify(source)


@pytest.mark.parametrize(
    "weight", ["model.onnx", "model.ort", "weights.ckpt", "model.tflite", "weights.pkl"]
)
def test_br42_01_hook_added_model_formats_abort_before_exe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    weight: str,
) -> None:
    hooks = ModuleType("PyInstaller.utils.hooks")
    for name in ("collect_data_files", "collect_dynamic_libs", "collect_submodules"):
        setattr(hooks, name, lambda package: [])
    monkeypatch.setitem(sys.modules, "PyInstaller.utils.hooks", hooks)
    monkeypatch.setenv("RECORYN_BUILD_EVIDENCE", str(tmp_path / "toc.json"))
    exes: list[object] = []

    def analysis(*args, **kwargs):
        return SimpleNamespace(pure=[], binaries=[], scripts=[], datas=[(weight, "fake", "DATA")])

    def exe(*args, **kwargs):
        exes.append(kwargs)
        return "unexpected-exe"

    with pytest.raises(ValueError, match="BUNDLED_MODEL_WEIGHTS_FORBIDDEN"):
        runpy.run_path(
            str(ROOT / "packaging" / "recoryn.spec"),
            init_globals={
                "SPECPATH": str(ROOT / "packaging"),
                "Analysis": analysis,
                "EXE": exe,
                "PYZ": lambda value: "fake-pyz",
                "COLLECT": lambda *a, **kw: "bundle",
            },
        )
    assert not exes and not (tmp_path / "toc.json").exists()


def test_sbom_uses_observed_distribution_and_records_exact_shipped_hashes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = importlib.import_module("release_evidence")
    manager = importlib.import_module("release_manager")
    source = tmp_path / "inputs"
    (source / "src" / "recoryn").mkdir(parents=True)
    (source / "LICENSE").write_text("independent-application-license")
    (source / "pyproject.toml").write_text('[project]\nversion="9.1"\n')
    (source / "build-inputs.json").write_text('{"schema_version":1,"files":[]}')
    (source / "src" / "recoryn" / "__init__.py").write_text("# synthetic source")
    site = tmp_path / "site"
    (site / "selected").mkdir(parents=True)
    native = site / "selected" / "runtime.dll"
    native.write_bytes(b"actual-shipped-runtime")
    distributions = []
    for name in ("selected", "unshipped"):
        metadata_path = site / (name + "-1.dist-info")
        metadata_path.mkdir()
        (metadata_path / "METADATA").write_text(
            f"Metadata-Version: 2.4\nName: {name}\nVersion: 1\nLicense-Expression: MIT\n"
        )
        (metadata_path / "LICENSE").write_text("synthetic-license-" + name)
        (metadata_path / "RECORD").write_text(
            f"{name}/runtime.dll,,\n{name}-1.dist-info/LICENSE,,\n"
        )
        distributions.append(importlib.metadata.PathDistribution(metadata_path))
    monkeypatch.setattr(importlib.metadata, "distributions", lambda: distributions)
    monkeypatch.setattr(importlib.metadata, "version", lambda name: "synthetic-build-tool")
    bundle = candidate(
        tmp_path / "bundle", extras={"_internal/selected/runtime.dll": native.read_bytes()}
    )
    (bundle / "release-manifest.json").unlink()
    toc = tmp_path / "analysis.json"
    toc.write_text(
        json.dumps(
            {"pure": [], "datas": [], "binaries": [["selected/runtime.dll", str(native), "BINARY"]]}
        )
    )
    evidence.generate(bundle, toc, source)
    verified = manager.verify(bundle)
    sbom = json.loads((bundle / "sbom.cdx.json").read_bytes())
    assert {row["name"] for row in sbom["components"]} == {"selected", "Recoryn", "CPython"}
    assert (
        bundle / "licenses" / "selected" / "LICENSE"
    ).read_text() == "synthetic-license-selected"
    for record in verified["files"]:
        data = (bundle / record["path"]).read_bytes()
        assert len(data) == record["size"] and hashlib.sha256(data).hexdigest() == record["sha256"]
    origins = json.loads((bundle / "native-origins.json").read_bytes())
    row = next(row for row in origins["files"] if row["path"] == "_internal/selected/runtime.dll")
    assert row["sha256"] == hashlib.sha256(native.read_bytes()).hexdigest()
    assert row["origins"][0]["source_sha256"] == row["sha256"]
    assert verified["gates"]["clean_windows_vm"] == "NOT_RUN"
    assert verified["distribution_status"] == "DEVELOPMENT_CANDIDATE"


def test_br42_02_toc_network_path_is_rejected_before_any_filesystem_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = importlib.import_module("release_evidence")
    manager = importlib.import_module("release_manager")
    bundle = candidate(tmp_path / "bundle")
    source = tmp_path / "inputs"
    source.mkdir()
    toc = tmp_path / "analysis.json"
    toc.write_text(
        json.dumps(
            {
                "pure": [],
                "datas": [],
                "binaries": [
                    ["runtime.dll", "\\\\br42-never-contact.invalid\\share\\runtime.dll", "BINARY"]
                ],
            }
        )
    )
    original = Path.is_file
    probes: list[str] = []

    def guarded_probe(path: Path) -> bool:
        if str(path).startswith("\\\\"):
            probes.append(str(path))
            raise AssertionError("UNC_METADATA_PROBE_BEFORE_LOCAL_PATH_VALIDATION")
        return original(path)

    monkeypatch.setattr(Path, "is_file", guarded_probe)
    with pytest.raises(manager.ReleaseError, match="NETWORK_PATH_FORBIDDEN"):
        evidence.generate(bundle, toc, source)
    assert probes == []
