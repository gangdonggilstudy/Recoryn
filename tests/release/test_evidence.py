"""TOC attribution uses shipped files and isolated distribution metadata, without a build."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
from pathlib import Path

import pytest
import release_evidence as evidence
import release_manager as manager


def prepared(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    site = tmp_path / "site"
    package = site / "example"
    package.mkdir(parents=True)
    (package / "__init__.py").write_bytes(b"# observed package input\n")
    (package / "codec.dll").write_bytes(b"MZ-native-library")
    metadata = site / "example-1.2.3.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.4\nName: example\nVersion: 1.2.3\nLicense-Expression: MIT\n"
    )
    (metadata / "LICENSE.txt").write_text("Synthetic license fixture, not a real grant.")
    (metadata / "RECORD").write_text(
        "example/__init__.py,,\nexample/codec.dll,,\nexample-1.2.3.dist-info/LICENSE.txt,,\n"
    )
    distribution = importlib.metadata.PathDistribution(metadata)
    monkeypatch.setattr(importlib.metadata, "distributions", lambda: [distribution])
    monkeypatch.setattr(importlib.metadata, "version", lambda name: "6.22.3")
    source = tmp_path / "inputs"
    (source / "src" / "recoryn").mkdir(parents=True)
    (source / "src" / "recoryn" / "__init__.py").write_text("# fixture application\n")
    (source / "LICENSE").write_text("Synthetic application license fixture")
    (source / "pyproject.toml").write_text('[project]\nversion="0.2.0.dev2"\n')
    (source / "build-inputs.json").write_text('{"schema_version":1,"files":[]}')
    bundle = tmp_path / "candidate"
    (bundle / "_internal" / "example").mkdir(parents=True)
    (bundle / "Recoryn.exe").write_bytes(b"MZ-GUI")
    (bundle / "Recoryn-CLI.exe").write_bytes(b"MZ-CLI")
    (bundle / "_internal" / "example" / "codec.dll").write_bytes(b"MZ-native-library")
    # This DLL has no direct package attribution; never silently claim completeness.
    (bundle / "_internal" / "unattributed.dll").write_bytes(b"MZ-unattributed")
    toc = tmp_path / "analysis.json"
    toc.write_text(
        json.dumps(
            {
                "pure": [("example", str(package / "__init__.py"), "PYMODULE")],
                "binaries": [("example/codec.dll", str(package / "codec.dll"), "BINARY")],
                "datas": [],
            }
        )
    )
    return bundle, toc, source


def test_evidence_maps_actual_native_bytes_and_package_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, toc, source = prepared(tmp_path, monkeypatch)
    evidence.generate(bundle, toc, source)
    manifest = manager.verify(bundle)
    actual = {item["path"]: item for item in manifest["files"]}
    for path in bundle.rglob("*"):
        if path.is_file() and path.name != manager.MANIFEST:
            assert (
                actual[path.relative_to(bundle).as_posix()]["sha256"]
                == hashlib.sha256(path.read_bytes()).hexdigest()
            )
    sbom = manager.read_json(bundle / "sbom.cdx.json")
    assert {item["name"] for item in sbom["components"]} == {"example", "CPython", "Recoryn"}
    package = next(item for item in sbom["components"] if item["name"] == "example")
    properties = {item["name"]: item["value"] for item in package["properties"]}
    assert properties["recoryn:included-source-file-count"] == "2"
    assert len(json.loads(properties["recoryn:analysis-inputs"])) == 2
    notices = json.loads(properties["recoryn:notice-files"])
    assert notices == ["licenses/example/LICENSE.txt"]
    assert (bundle / notices[0]).read_text() == "Synthetic license fixture, not a real grant."
    native = {
        row["path"]: row for row in manager.read_json(bundle / "native-origins.json")["files"]
    }
    codec = native["_internal/example/codec.dll"]
    assert codec["attribution"] == "ANALYSIS_TOC"
    assert codec["sha256"] == codec["origins"][0]["source_sha256"]
    assert native["_internal/unattributed.dll"]["attribution"] == "REVIEW_REQUIRED"
    assert native["Recoryn.exe"]["attribution"] == "REVIEW_REQUIRED"
    provenance = manager.read_json(bundle / "build-provenance.json")
    assert provenance["analysis_toc_sha256"] == hashlib.sha256(toc.read_bytes()).hexdigest()
    assert provenance["gates"]["code_signing"] == "NOT_RUN"
    assert manifest["distribution_status"] == "DEVELOPMENT_CANDIDATE"
    assert "not an authenticity signature" in (bundle / "NOTICE.txt").read_text(encoding="utf-8")
    # Public evidence contains relative/logical file identities, not build-host absolute paths.
    assert str(tmp_path) not in json.dumps(manifest) + json.dumps(sbom) + json.dumps(provenance)
    (bundle / "_internal" / "example" / "codec.dll").write_bytes(b"changed after evidence")
    with pytest.raises(manager.ReleaseError, match="INTEGRITY"):
        manager.verify(bundle)


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"pure": None, "binaries": [], "datas": []},
        {"pure": [[1, 2, 3]], "binaries": [], "datas": []},
    ],
)
def test_malformed_analysis_never_produces_valid_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: object
) -> None:
    bundle, toc, source = prepared(tmp_path, monkeypatch)
    toc.write_text(json.dumps(value))
    with pytest.raises(manager.ReleaseError, match="INVALID_ANALYSIS_TOC"):
        evidence.generate(bundle, toc, source)
    assert not (bundle / manager.MANIFEST).exists()
