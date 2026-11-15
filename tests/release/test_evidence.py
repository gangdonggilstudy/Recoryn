"""TOC attribution uses shipped files and isolated distribution metadata, without a build."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import shutil
from pathlib import Path

import pytest
import release_evidence as evidence
import release_manager as manager

NOTICES = Path(__file__).resolve().parents[2] / "packaging" / "notices"


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
    shutil.copytree(NOTICES, source / "packaging" / "notices")
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


def _distribution(site: Path, name: str, version: str, meta: str, texts: dict[str, str]) -> Path:
    package = site / name.lower()
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(f"# {name}\n")
    info = site / f"{name}-{version}.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(
        f"Metadata-Version: 2.4\nName: {name}\nVersion: {version}\n{meta}"
    )
    record = [f"{name.lower()}/__init__.py,,"]
    for file_name, body in texts.items():
        (info / file_name).write_text(body)
        record.append(f"{info.name}/{file_name},,")
    (info / "RECORD").write_text("\n".join(record) + "\n")
    return info


def l03_candidate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    bundle, toc, source = prepared(tmp_path, monkeypatch)
    site = tmp_path / "l03-site"
    infos = [
        # PySide6 wheels ship only the Qt commercial text although Recoryn uses LGPL.
        _distribution(
            site,
            "PySide6_Essentials",
            "6.12.0",
            "License: LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only\n",
            {"LicenseRef-Qt-Commercial.txt": "QT COMMERCIAL TEXT CANARY"},
        ),
        _distribution(site, "ctranslate2", "4.9.0", "License: MIT\n", {}),
        _distribution(site, "mystery", "0.1", "", {}),
    ]
    distributions = [importlib.metadata.PathDistribution(info) for info in infos]
    original = importlib.metadata.distributions()
    monkeypatch.setattr(importlib.metadata, "distributions", lambda: [*original, *distributions])
    rows = json.loads(toc.read_text())
    for name in ("pyside6_essentials", "ctranslate2", "mystery"):
        rows["pure"].append([name, str(site / name / "__init__.py"), "PYMODULE"])
    toc.write_text(json.dumps(rows))
    for relative in (
        "_internal/PySide6/Qt6Multimedia.dll",
        "_internal/PySide6/Qt6Core.dll",
        "_internal/ctranslate2/libiomp5md.dll",
        "_internal/vcruntime140.dll",
    ):
        target = bundle / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"MZ-" + relative.encode())
    return bundle, toc, source


def test_l03_qt_is_distributed_under_lgpl_texts_not_the_commercial_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, toc, source = l03_candidate(tmp_path, monkeypatch)
    evidence.generate(bundle, toc, source)
    sbom = {row["name"]: row for row in manager.read_json(bundle / "sbom.cdx.json")["components"]}
    qt = sbom["PySide6_Essentials"]
    properties = {item["name"]: item["value"] for item in qt["properties"]}
    assert properties["recoryn:declared-license"].startswith("LGPL-3.0-only OR GPL-2.0-only")
    assert properties["recoryn:distributed-license"] == "LGPL-3.0-only"
    assert properties["recoryn:license-basis"] == "RECORYN_L01_OVERRIDE"
    assert qt["licenses"] == [{"expression": "LGPL-3.0-only"}]
    notices = json.loads(properties["recoryn:notice-files"])
    assert notices == [
        "licenses/PySide6_Essentials/GPL-3.0.txt",
        "licenses/PySide6_Essentials/LGPL-3.0.txt",
    ]
    assert (bundle / notices[1]).read_bytes() == (NOTICES / "LGPL-3.0.txt").read_bytes()
    shipped = b"".join(path.read_bytes() for path in bundle.rglob("*") if path.is_file())
    assert b"QT COMMERCIAL TEXT CANARY" not in shipped


def test_l03_missing_wheel_texts_are_supplied_and_unknown_is_not_invented(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, toc, source = l03_candidate(tmp_path, monkeypatch)
    evidence.generate(bundle, toc, source)
    sbom = {row["name"]: row for row in manager.read_json(bundle / "sbom.cdx.json")["components"]}
    ct2 = {item["name"]: item["value"] for item in sbom["ctranslate2"]["properties"]}
    assert json.loads(ct2["recoryn:notice-files"]) == [
        "licenses/ctranslate2/CTranslate2-LICENSE.txt"
    ]
    assert sbom["ctranslate2"]["licenses"] == [{"expression": "MIT"}]
    mystery = {item["name"]: item["value"] for item in sbom["mystery"]["properties"]}
    assert mystery["recoryn:distributed-license"] == "NOASSERTION"
    assert "licenses" not in sbom["mystery"]
    assert sbom["example"]["licenses"] == [{"expression": "MIT"}]


def test_l03_native_map_notice_and_gate_name_open_conditions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, toc, source = l03_candidate(tmp_path, monkeypatch)
    evidence.generate(bundle, toc, source)
    native = {
        row["path"]: row for row in manager.read_json(bundle / "native-origins.json")["files"]
    }
    assert native["_internal/PySide6/Qt6Multimedia.dll"]["license_status"] == "DECLARED"
    assert native["_internal/PySide6/Qt6Core.dll"]["license"] == "LGPL-3.0-only"
    assert native["_internal/ctranslate2/libiomp5md.dll"]["license_status"] == (
        "CONDITIONS_UNCONFIRMED"
    )
    assert native["_internal/vcruntime140.dll"]["license_status"] == "REDISTRIBUTABLE_PROPRIETARY"
    assert native["Recoryn.exe"]["component"].startswith("PyInstaller")
    assert native["_internal/unattributed.dll"]["license_status"] == "UNMAPPED"
    assert evidence.license_gaps(bundle) == [
        "_internal/example/codec.dll",
        "_internal/unattributed.dll",
    ]
    provenance = manager.read_json(bundle / "build-provenance.json")
    assert provenance["gates"]["transitive_native_license_review"] == "UNMAPPED_NATIVE_FILES"
    notice = (bundle / "NOTICE.txt").read_text(encoding="utf-8")
    # L01 D7: no FFmpeg or media backend is shipped: no FFmpeg text, offer or patent row.
    assert not (bundle / "licenses" / "FFmpeg-Qt-Multimedia").exists()
    assert "LGPL-2.1" not in notice and "PATENT_REVIEW_REQUIRED" not in notice
    for required in (
        "Qt Multimedia's media backends",
        "No FFmpeg code is distributed.",
        "no media decoder is used.",
        "CONDITIONS_UNCONFIRMED: _internal/ctranslate2/libiomp5md.dll",
        "UNMAPPED: _internal/unattributed.dll",
        "PySide6_Essentials 6.12.0: LGPL-3.0-only",
        "ctranslate2 4.9.0: MIT",
        "x264/x265/OpenH264",
        "not an authenticity signature",
        # L03-04: Microsoft and Intel conditions are open, not implied approvals.
        "release gate microsoft_runtime_conditions",
        "is not yet confirmed",
    ):
        assert required in notice, required
    gates = provenance["gates"]
    assert gates["ffmpeg_build_flags_corresponding_source_and_notices"] == (
        "NOT_DISTRIBUTED_L01_D1_D7"
    )
    assert (
        gates["microsoft_runtime_conditions"]
        == gates["intel_runtime_conditions"]
        == ("REVIEW_REQUIRED")
    )
    assert manager.verify(bundle)["version"] == "0.2.0.dev2"


@pytest.mark.parametrize(
    "relative",
    [
        "_internal/PySide6/avcodec-63.dll",
        "_internal/PySide6/plugins/multimedia/ffmpegmediaplugin.dll",
        "_internal/PySide6/plugins/multimedia/windowsmediaplugin.dll",
    ],
)
def test_l04_reintroduced_qt_ffmpeg_is_unmapped_and_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative: str
) -> None:
    # Two independent stops: no license mapping (build gate) and the D7 policy (verify).
    bundle, toc, source = l03_candidate(tmp_path, monkeypatch)
    target = bundle / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"MZ-qt-ffmpeg")
    evidence.generate(bundle, toc, source)
    native = {
        row["path"]: row for row in manager.read_json(bundle / "native-origins.json")["files"]
    }
    assert native[relative]["license_status"] == "UNMAPPED"
    assert relative in evidence.license_gaps(bundle)
    assert not (bundle / "licenses" / "FFmpeg-Qt-Multimedia").exists()
    with pytest.raises(manager.ReleaseError, match="LICENSE_EXCLUDED_COMPONENT"):
        manager.verify(bundle)


@pytest.mark.parametrize("damage", ["missing", "tampered"])
def test_l03_notice_texts_must_exist_with_pinned_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damage: str
) -> None:
    bundle, toc, source = prepared(tmp_path, monkeypatch)
    notices = source / "packaging" / "notices"
    if damage == "missing":
        shutil.rmtree(notices)
        expected = "NOTICE_TEXTS_MISSING"
    else:
        (notices / "LGPL-3.0.txt").write_bytes(b"edited license text")
        expected = "NOTICE_TEXT_HASH_MISMATCH"
    with pytest.raises(manager.ReleaseError, match=expected):
        evidence.generate(bundle, toc, source)
    assert not (bundle / manager.MANIFEST).exists()


# Hand-written decision table against the reviewed map (L03-01): exact reviewed
# paths only; a directory never implies a license.
OPENBLAS = "_internal/numpy.libs/libscipy_openblas64_-9e3e5a4229c1ca39f10dc82bba9e2b2b.dll"
NATIVE_TABLE = [
    ("Recoryn.exe", "DECLARED"),
    ("Recoryn-CLI.exe", "DECLARED"),
    ("_internal/python313.dll", "DECLARED"),
    ("_internal/_ssl.pyd", "DECLARED"),
    ("_internal/libssl-3.dll", "DECLARED"),
    ("_internal/libssl-3-x64.dll", "UNMAPPED"),  # host-tool OpenSSL must never pass silently
    ("_internal/sqlite3.dll", "DECLARED"),
    ("_internal/ucrtbase.dll", "UNMAPPED"),  # not in the reviewed bundle (System32 copy)
    ("_internal/api-ms-win-core-file-l1-1-0.dll", "UNMAPPED"),
    (
        "_internal/numpy.libs/msvcp140-a4c2229bdc2a2a630acdc095b4d86008.dll",
        "REDISTRIBUTABLE_PROPRIETARY",
    ),
    ("_internal/PySide6/MSVCP140_2.dll", "REDISTRIBUTABLE_PROPRIETARY"),
    # L01 D7: Qt's FFmpeg files are no longer reviewed components of the bundle.
    ("_internal/PySide6/swscale-10.dll", "UNMAPPED"),
    ("_internal/PySide6/avcodec-63.dll", "UNMAPPED"),
    ("_internal/PySide6/plugins/multimedia/ffmpegmediaplugin.dll", "UNMAPPED"),
    ("_internal/PySide6/plugins/multimedia/windowsmediaplugin.dll", "UNMAPPED"),
    ("_internal/PySide6/Qt6Multimedia.dll", "DECLARED"),
    ("_internal/PySide6/Qt6MultimediaWidgets.dll", "DECLARED"),
    ("_INTERNAL/PYSIDE6/QT6CORE.DLL", "DECLARED"),
    ("_internal\\PySide6\\plugins\\platforms\\qwindows.dll", "DECLARED"),
    ("_internal/PySide6/QtCore.pyd", "DECLARED"),
    ("_internal/shiboken6/shiboken6.abi3.dll", "DECLARED"),
    ("_internal/ctranslate2/ctranslate2.dll", "CONDITIONS_UNCONFIRMED"),
    ("_internal/ctranslate2/_ext.cp313-win_amd64.pyd", "DECLARED"),
    ("_internal/ctranslate2/cudnn64_9.dll", "UNMAPPED"),
    ("_internal/av.libs/libx264-165.dll", "UNMAPPED"),
    ("_internal/sherpa_onnx/lib/onnxruntime.dll", "DECLARED"),
    ("_internal/onnxruntime/capi/onnxruntime.dll", "DECLARED"),
    (OPENBLAS, "DECLARED"),
    ("_internal/numpy.libs/libscipy_openblas64_-9e3e5a4229c1ca39.dll", "UNMAPPED"),
    ("_internal/tokenizers/tokenizers.pyd", "DECLARED"),
    ("_internal/new-vendor/unknown.dll", "UNMAPPED"),
    # L03-01 counterexamples: unknown files inside reviewed directories.
    ("_internal/PySide6/plugins/newvendor/unknown.dll", "UNMAPPED"),
    ("_internal/PySide6/Qt6NewVendor.dll", "UNMAPPED"),
    ("_internal/shiboken6/unknown-vendor.dll", "UNMAPPED"),
]
NATIVE_MAP = evidence.load_native_map(NOTICES.parents[1])


@pytest.mark.parametrize(("path", "status"), NATIVE_TABLE)
def test_l03_native_license_decision_table(path: str, status: str) -> None:
    assert evidence.native_license(path, NATIVE_MAP)[2] == status


def test_l03_reviewed_native_map_is_exact_and_valid() -> None:
    data = json.loads((NOTICES / "native-map.json").read_text(encoding="utf-8"))
    paths = [path for group in data["components"] for path in group["files"]]
    assert len(paths) == len(set(paths)) == len(NATIVE_MAP) == 105
    # L01 D7: no FFmpeg group, no FFmpeg/backend path and no LGPL-2.1 text remain.
    assert not any(group["component"].startswith("FFmpeg") for group in data["components"])
    assert not any(manager.excluded_component(path) for path in paths)
    sources = json.loads((NOTICES / "SOURCES.json").read_text(encoding="utf-8"))
    assert "LGPL-2.1.txt" not in {row["file"] for row in sources["files"]}
    assert not (NOTICES / "LGPL-2.1.txt").exists()
    assert not any("*" in path or path.endswith("/") for path in paths)


@pytest.mark.parametrize("damage", ["status", "expression", "duplicate"])
def test_l03_invalid_native_map_is_refused(tmp_path: Path, damage: str) -> None:
    data = json.loads((NOTICES / "native-map.json").read_text(encoding="utf-8"))
    group = data["components"][0]
    if damage == "status":
        group["status"] = "APPROVED"
    elif damage == "expression":
        group["license"] = "MIT AND AND"
    else:
        data["components"][1]["files"].append(group["files"][0].upper())
    target = tmp_path / "packaging" / "notices"
    target.mkdir(parents=True)
    (target / "native-map.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(manager.ReleaseError, match="NATIVE_MAP_INVALID"):
        evidence.load_native_map(tmp_path)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("MIT AND AND", [{"license": {"name": "MIT AND AND"}}]),
        ("Proprietary", [{"license": {"name": "Proprietary"}}]),
        ("Apache-2.0-or-later", [{"license": {"name": "Apache-2.0-or-later"}}]),
        ("mit and apache-2.0", [{"expression": "MIT AND Apache-2.0"}]),
        (
            "GPL-2.0-or-later WITH Bootloader-exception",
            [{"expression": "GPL-2.0-or-later WITH Bootloader-exception"}],
        ),
        ("LicenseRef-Declared-As-Full-Text", [{"expression": "LicenseRef-Declared-As-Full-Text"}]),
        ("NOASSERTION", []),
    ],
)
def test_l03_only_valid_spdx_becomes_an_expression(value: str, expected: object) -> None:
    # L03-02: shape-alike strings are kept as names, never asserted as SPDX.
    assert evidence.cyclonedx_licenses(value) == expected


def test_l03_full_license_text_in_metadata_is_not_pasted_into_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, toc, source = prepared(tmp_path, monkeypatch)
    site = tmp_path / "long-site"
    infos = [
        _distribution(
            site,
            name,
            "1.0",
            "License: Copyright (c) Example.\n        FULL-TEXT-CANARY all rights reserved.\n",
            {},
        )
        for name in ("numpy", "verbose")
    ]
    original = importlib.metadata.distributions()
    added = [importlib.metadata.PathDistribution(info) for info in infos]
    monkeypatch.setattr(importlib.metadata, "distributions", lambda: [*original, *added])
    rows = json.loads(toc.read_text())
    for name in ("numpy", "verbose"):
        rows["pure"].append([name, str(site / name / "__init__.py"), "PYMODULE"])
    toc.write_text(json.dumps(rows))
    evidence.generate(bundle, toc, source)
    sbom = {row["name"]: row for row in manager.read_json(bundle / "sbom.cdx.json")["components"]}
    assert sbom["numpy"]["licenses"] == [{"expression": "BSD-3-Clause"}]
    assert sbom["verbose"]["licenses"] == [{"expression": evidence.LONG_DECLARED}]
    notice = (bundle / "NOTICE.txt").read_text(encoding="utf-8")
    assert "FULL-TEXT-CANARY" not in notice
    assert f"verbose 1.0: {evidence.LONG_DECLARED}" in notice
    # L03-03: the SBOM keeps the identity of the declared text, not the text itself.
    assert "FULL-TEXT-CANARY" not in (bundle / "sbom.cdx.json").read_text(encoding="utf-8")
    properties = {item["name"]: item["value"] for item in sbom["verbose"]["properties"]}
    # Oracle: the header as the metadata parser unfolds it, hashed here independently.
    declared = (added[1].metadata.get_all("License") or [""])[0]
    assert "FULL-TEXT-CANARY" in declared
    assert properties["recoryn:declared-license"] == evidence.LONG_DECLARED
    assert properties["recoryn:declared-license-chars"] == str(len(declared))
    assert (
        properties["recoryn:declared-license-sha256"]
        == hashlib.sha256(declared.encode("utf-8")).hexdigest()
    )


def test_l03_mpl_source_location_and_prose_declarations_are_normalized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, toc, source = prepared(tmp_path, monkeypatch)
    site = tmp_path / "prose-site"
    infos = [
        _distribution(site, "tqdm", "4.70.1", "License: MPL-2.0 AND MIT\n", {"LICENCE": "t"}),
        _distribution(site, "protobuf", "7.36.2", "License: 3-Clause BSD License\n", {}),
    ]
    original = importlib.metadata.distributions()
    added = [importlib.metadata.PathDistribution(info) for info in infos]
    monkeypatch.setattr(importlib.metadata, "distributions", lambda: [*original, *added])
    rows = json.loads(toc.read_text())
    for name in ("tqdm", "protobuf"):
        rows["pure"].append([name, str(site / name / "__init__.py"), "PYMODULE"])
    toc.write_text(json.dumps(rows))
    evidence.generate(bundle, toc, source)
    sbom = {row["name"]: row for row in manager.read_json(bundle / "sbom.cdx.json")["components"]}
    assert sbom["protobuf"]["licenses"] == [{"expression": "BSD-3-Clause"}]
    assert sbom["tqdm"]["licenses"] == [{"expression": "MPL-2.0 AND MIT"}]
    notice = (bundle / "NOTICE.txt").read_text(encoding="utf-8")
    assert "tqdm 4.70.1: https://pypi.org/project/tqdm/4.70.1/#files" in notice


# --- L-P05 / L01 D8: notice completeness (case space docs/testing/l05-notice-cases.md) ---

SOURCES = json.loads((NOTICES / "SOURCES.json").read_text(encoding="utf-8"))
QT = json.loads((NOTICES / "qt-third-party.json").read_text(encoding="utf-8"))
MANIFESTS = {
    "SOURCES.json",
    "native-map.json",
    "qt-third-party.json",
    "corresponding-sources.json",
    "ct2-native.json",
}


def test_l05_every_notice_text_is_pinned_and_every_pin_matches() -> None:
    pinned = {row["file"]: row for row in SOURCES["files"]}
    on_disk = {
        path.relative_to(NOTICES).as_posix()
        for path in NOTICES.rglob("*")
        if path.is_file() and path.name not in MANIFESTS
    }
    assert on_disk == set(pinned)  # no unpinned text, no pin without a file
    for name, row in pinned.items():
        data = (NOTICES / name).read_bytes()
        assert (len(data), hashlib.sha256(data).hexdigest()) == (row["bytes"], row["sha256"])
        assert row["url"].startswith("https://")


# Hand-written expectations from the Qt 6.12.0 qt_attribution.json review (L-P05).
QT_EXPECTED = {
    ("qtbase", "zlib"): ("Zlib", "Qt6Core.dll"),
    ("qtbase", "pcre2"): (
        "LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception",
        "Qt6Core.dll",
    ),
    ("qtbase", "freetype"): ("FTL OR GPL-2.0-only", "Qt6Gui.dll"),
    ("qtbase", "harfbuzz-ng"): ("MIT", "Qt6Gui.dll"),
    ("qtbase", "libpng"): ("Libpng AND libpng-2.0", "Qt6Gui.dll"),
    # L05-01: libtiff's JPEG support puts libjpeg-turbo into qtiff.dll as well.
    ("qtbase", "libjpeg"): (
        "IJG AND BSD-3-Clause",
        "plugins/imageformats/qjpeg.dll and plugins/imageformats/qtiff.dll",
    ),
    ("qtbase", "psl-data"): ("MPL-2.0", "Qt6Network.dll"),
    ("qtbase", "wintab"): ("LicenseRef-Lcs-Telegraphics", "plugins/platforms/qwindows.dll"),
    ("qtimageformats", "libtiff"): ("libtiff", "plugins/imageformats/qtiff.dll"),
    ("qtimageformats", "libwebp"): ("BSD-3-Clause", "plugins/imageformats/qwebp.dll"),
    ("qtmultimedia", "dr_libs"): ("Unlicense OR MIT-0", "Qt6Multimedia.dll"),
    ("qtmultimedia", "tlsf"): ("BSD-3-Clause", "Qt6Multimedia.dll"),
    ("qtsvg", "qtsvg-xsvg"): ("HPND-sell-variant", "Qt6Svg.dll"),
}
# Not shipped: other platforms, unshipped modules, and the excluded FFmpeg plugin.
QT_ABSENT = {
    "ffmpeg",
    "ffmpeg-libjpeg",
    "ffmpeg-zlib",
    "signalsmith-stretch",
    "pffft",
    "eigen",
    "resonance-audio",
    "opengl-es2-headers",  # L05-02: desktop OpenGL build, no ES2 headers compiled
    "sqlite",
    "forkfd",
    "pixman",
    "libdbus-1-headers",
}


def test_l05_qt_attribution_table() -> None:
    entries = QT["entries"]
    keys = [(entry["repo"], entry["id"]) for entry in entries]
    assert len(keys) == len(set(keys)) == 47
    pinned = {row["file"] for row in SOURCES["files"]}
    for entry in entries:
        assert evidence.spdx(entry["license"]) == entry["license"], entry["id"]
        assert entry["copyright"] and all(
            line.strip().lower() not in {"", "none", "null", "n/a", "-"}
            for line in entry["copyright"]
        )
        assert entry["files"] and set(entry["files"]) <= pinned
    table = {(entry["repo"], entry["id"]): entry for entry in entries}
    for key, (license_id, shipped) in QT_EXPECTED.items():
        assert table[key]["license"] == license_id
        assert table[key]["shipped_in"].split(" (")[0] == shipped  # notes follow in brackets
    assert not QT_ABSENT & {entry["id"] for entry in entries}
    # L05-04: libjpeg's notices come from its pinned COPYRIGHT.txt, not a placeholder.
    libjpeg = table[("qtbase", "libjpeg")]["copyright"]
    assert libjpeg[0] == "Copyright (C) 2009-2026 D. R. Commander" and len(libjpeg) == 15


def test_l05_qt_third_party_notice_sbom_and_texts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, toc, source = l03_candidate(tmp_path, monkeypatch)
    evidence.generate(bundle, toc, source)
    notice = (bundle / "NOTICE.txt").read_text(encoding="utf-8")
    for entry in QT["entries"]:
        version = f" {entry['version']}" if entry["version"] else ""
        assert f"  {entry['name']}{version} ({entry['license']}) in {entry['shipped_in']}" in notice
        for line in entry["copyright"]:
            assert f"    {line}" in notice
        for name in entry["files"]:
            copied = bundle / "licenses" / "Qt-third-party" / name.removeprefix("qt/")
            assert copied.read_bytes() == (NOTICES / name).read_bytes()
    for required in (
        "Portions of this software are copyright (C) 2026 The FreeType Project",
        "This software is based in part on the work of the Independent JPEG Group.",
        "The Public Suffix List 2026-05-14_08-35-31_UTC in Qt6Network.dll: ",  # MPL-2.0
        "https://code.qt.io/cgit/qt/qtbase.git/tree/src/3rdparty/libpsl?h=v6.12.0",
        "learn.microsoft.com/en-us/visualstudio/releases/2022/redistribution",
        "licensed Visual Studio users",
    ):
        assert required in notice, required
    archives = json.loads((NOTICES / "corresponding-sources.json").read_text(encoding="utf-8"))
    for row in archives["archives"]:
        assert f"{row['url']} (SHA-256 {row['sha256']})" in notice
    sbom = manager.read_json(bundle / "sbom.cdx.json")["components"]
    qt_rows = [row for row in sbom if row["name"].startswith("Qt 6.12.0 third-party: ")]
    assert len(qt_rows) == 47 and all(row["licenses"] for row in qt_rows)
    listed = notice.split("Components (distributed license", 1)[1].split("\n\n", 1)[0]
    assert "Qt 6.12.0 third-party" not in listed  # not duplicated as NOASSERTION rows
    gates = manager.read_json(bundle / "build-provenance.json")["gates"]
    assert gates["qt_corresponding_source_and_notices"] == (
        "TEXTS_INCLUDED_UPSTREAM_SOURCES_RECORDED_HOSTING_DECISION_REQUIRED"
    )
    assert manager.verify(bundle)["version"] == "0.2.0.dev2"


def test_l05_no_qt_runtime_means_no_qt_section(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, toc, source = prepared(tmp_path, monkeypatch)
    evidence.generate(bundle, toc, source)
    notice = (bundle / "NOTICE.txt").read_text(encoding="utf-8")
    assert not (bundle / "licenses" / "Qt-third-party").exists()
    assert "Third-party code inside the shipped Qt" not in notice


def _damage_qt(source: Path, damage: str) -> str:
    notices = source / "packaging" / "notices"
    qt = json.loads((notices / "qt-third-party.json").read_text(encoding="utf-8"))
    archives = json.loads((notices / "corresponding-sources.json").read_text(encoding="utf-8"))
    entry = qt["entries"][0]
    if damage == "unpinned_text":
        entry["files"].append("qt/qtbase/NOT-PINNED.txt")
    elif damage == "invalid_spdx":
        entry["license"] = "MIT AND AND"
    elif damage == "empty_copyright":
        entry["copyright"] = []
    elif damage == "placeholder_copyright":
        entry["copyright"] = ["None"]  # L05-04: the original libjpeg row
    elif damage == "duplicate":
        qt["entries"].append(dict(entry))
    elif damage == "foreign_source_url":
        archives["archives"][0]["url"] = "https://example.invalid/qtbase.tar.xz"
    else:
        archives["archives"][0]["sha256"] = "0" * 63
    (notices / "qt-third-party.json").write_text(json.dumps(qt), encoding="utf-8")
    (notices / "corresponding-sources.json").write_text(json.dumps(archives), encoding="utf-8")
    return (
        "CORRESPONDING_SOURCES_INVALID"
        if "source" in damage or "sha" in damage
        else ("QT_ATTRIBUTION_INVALID")
    )


@pytest.mark.parametrize(
    "damage",
    [
        "unpinned_text",
        "invalid_spdx",
        "empty_copyright",
        "placeholder_copyright",
        "duplicate",
        "foreign_source_url",
        "short_sha",
    ],
)
def test_l05_unreviewed_qt_records_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damage: str
) -> None:
    bundle, toc, source = l03_candidate(tmp_path, monkeypatch)
    code = _damage_qt(source, damage)
    with pytest.raises(manager.ReleaseError, match=code):
        evidence.generate(bundle, toc, source)
    assert not (bundle / manager.MANIFEST).exists()


CT2 = json.loads((NOTICES / "ct2-native.json").read_text(encoding="utf-8"))
DLL, OMP = "ctranslate2/ctranslate2.dll", "ctranslate2/libiomp5md.dll"
# Hand-written from the CTranslate2 v4.9.0 build script and DLL string review (L-P05).
CT2_EXPECTED = {
    "ctranslate2": ("MIT", DLL),
    "onemkl": ("LicenseRef-Intel-Simplified-Software-License", DLL),
    "onednn": ("Apache-2.0", DLL),
    "onednn-xbyak": ("BSD-3-Clause", DLL),
    "cuda-runtime": ("LicenseRef-NVIDIA-CUDA-Toolkit-EULA", DLL),
    "curand-device": ("LicenseRef-NVIDIA-CUDA-Toolkit-EULA AND BSD-3-Clause", DLL),
    "thrust": ("Apache-2.0 AND BSL-1.0 AND BSD-2-Clause", DLL),
    "cub": ("BSD-3-Clause", DLL),
    "spdlog": ("MIT", DLL),
    "fmt": ("MIT", DLL),
    "cpu_features": ("Apache-2.0", DLL),
    "avx_mathfun": ("MIT AND Zlib", DLL),
    "openmp": ("LicenseRef-Intel-EULA-Developer-Tools", OMP),
}
# Not compiled into the Windows wheel (options BUILD_CLI/BUILD_TESTS/WITH_RUY/
# WITH_FLASH_ATTN off; cuDNN is excluded from the bundle by L01 D3).
CT2_ABSENT = {"cutlass", "cxxopts", "googletest", "ruy", "cudnn", "cublas"}


def test_l05_ctranslate2_native_table() -> None:
    entries = CT2["entries"]
    ids = [entry["id"] for entry in entries]
    assert len(ids) == len(set(ids)) == 16
    pinned = {row["file"] for row in SOURCES["files"]}
    for entry in entries:
        assert evidence.spdx(entry["license"]) == entry["license"], entry["id"]
        assert entry["copyright"] and set(entry["files"]) <= pinned
    table = {entry["id"]: entry for entry in entries}
    for key, (license_id, shipped) in CT2_EXPECTED.items():
        assert (table[key]["license"], table[key]["shipped_in"]) == (license_id, shipped)
    assert not CT2_ABSENT & set(ids)
    dll = evidence.native_license("_internal/ctranslate2/ctranslate2.dll", NATIVE_MAP)
    assert dll[2] == "CONDITIONS_UNCONFIRMED"
    for part in (
        "LicenseRef-NVIDIA-CUDA-Toolkit-EULA",
        "LicenseRef-Intel-Simplified-Software-License",
    ):
        assert part in dll[1]


def test_l05_nvidia_header_source_is_not_redistributed() -> None:
    # Only the license comments the cuRAND headers require are kept, never their code.
    names = {path.name.lower() for path in NOTICES.rglob("*")}
    assert not names & {"curand_kernel.h", "curand_philox4x32_x.h", "curand_precalc.h"}
    excerpt = (NOTICES / "ct2" / "nvidia" / "NVIDIA-cuRAND-notices.txt").read_bytes()
    assert excerpt.startswith(b"/* Copyright 2010-2014 NVIDIA Corporation")
    assert excerpt.rstrip().endswith(b"*/") and b"#" not in excerpt
    assert b"U.S. Government End Users" in excerpt and b"D. E. Shaw Research" in excerpt


def test_l05_no_notice_text_trips_the_distribution_policy() -> None:
    # A copied text named like an excluded runtime (e.g. "curand...") would block a release.
    for path in NOTICES.rglob("*"):
        if path.is_file():
            relative = path.relative_to(NOTICES).as_posix()
            for root in ("licenses/Qt-third-party/", "licenses/ctranslate2-native/"):
                assert manager.excluded_component("_internal/../" + root + relative) is None


def test_l05_ctranslate2_native_notice_texts_and_sbom(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, toc, source = l03_candidate(tmp_path, monkeypatch)
    evidence.generate(bundle, toc, source)
    notice = (bundle / "NOTICE.txt").read_text(encoding="utf-8")
    for entry in CT2["entries"]:
        version = f" {entry['version']}" if entry["version"] else ""
        assert f"  {entry['name']}{version} ({entry['license']}) in {entry['shipped_in']}" in notice
        for line in entry["copyright"]:
            assert f"    {line}" in notice
        for name in entry["files"]:
            copied = bundle / "licenses" / "ctranslate2-native" / name.removeprefix("ct2/")
            assert copied.read_bytes() == (NOTICES / name).read_bytes()
    excerpt = (NOTICES / "ct2" / "nvidia" / "NVIDIA-cuRAND-notices.txt").read_text(encoding="utf-8")
    assert excerpt.rstrip() in notice  # reproduced verbatim in the user documentation
    sbom = manager.read_json(bundle / "sbom.cdx.json")["components"]
    native = [row for row in sbom if row["name"].startswith("CTranslate2 native: ")]
    assert len(native) == 16 and all(row["licenses"] for row in native)
    gates = manager.read_json(bundle / "build-provenance.json")["gates"]
    assert (
        gates["nvidia_runtime_conditions"]
        == gates["intel_runtime_conditions"]
        == ("REVIEW_REQUIRED")
    )
    assert "release gates nvidia_runtime_conditions and" in notice
    # Only the separate NVIDIA DLLs are excluded; the static runtime is disclosed.
    assert "NVIDIA CUDA/cuDNN runtime DLLs (the CUDA runtime statically linked inside" in notice
    assert manager.verify(bundle)["version"] == "0.2.0.dev2"


def test_l05_unpinned_ctranslate2_record_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, toc, source = l03_candidate(tmp_path, monkeypatch)
    path = source / "packaging" / "notices" / "ct2-native.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["entries"][0]["files"].append("ct2/NOT-PINNED.txt")
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(manager.ReleaseError, match="CT2_ATTRIBUTION_INVALID"):
        evidence.generate(bundle, toc, source)
    assert not (bundle / manager.MANIFEST).exists()
