"""실제 PyInstaller TOC와 output 파일 기준 후보 SBOM/무결성 목록 생성."""

from __future__ import annotations

import hashlib
import importlib.metadata as metadata
import json
import os
import platform
import re
import shutil
import sys
import tomllib
from pathlib import Path
from typing import Any

from packaging.licenses import InvalidLicenseExpression, canonicalize_license_expression
from release_manager import (
    APP_ID,
    MANIFEST,
    ReleaseError,
    atomic_json,
    digest,
    inventory,
    read_json,
    safe,
)

NOTICE_SKIP = ("licenseref-qt-commercial",)
# L01 D5. Wheel metadata is not always the license Recoryn ships under: PySide6 and
# shiboken6 wheels carry only the Qt commercial text although Recoryn uses them
# under LGPL-3.0, and ctranslate2/tokenizers/sherpa-onnx-core wheels carry no text.
# Texts are verbatim upstream copies pinned in packaging/notices/SOURCES.json.
_QT = ("LGPL-3.0-only", ("LGPL-3.0.txt", "GPL-3.0.txt"))
LICENSE_OVERRIDES: dict[str, tuple[str, tuple[str, ...]]] = {
    "pyside6": _QT,
    "pyside6-essentials": _QT,
    "pyside6-addons": _QT,
    "pyside6-pdf": _QT,
    "pyside6-webengine": _QT,
    "shiboken6": _QT,
    "ctranslate2": ("MIT", ("CTranslate2-LICENSE.txt",)),
    "tokenizers": ("Apache-2.0", ("tokenizers-LICENSE.txt",)),
    "sherpa-onnx-core": ("Apache-2.0", ("sherpa-onnx-LICENSE.txt",)),
    # Declares only the "BSD License" classifier; its own bundled LICENSE.txt is the
    # three-clause text (copyright, binary reproduction, no endorsement).
    "colorama": ("BSD-3-Clause", ()),
    # Metadata "License" holds the whole bundled text (BSD-3-Clause plus the wheel's
    # third-party terms, all in its LICENSE.txt); the native OpenBLAS rule covers the
    # GCC runtime exception separately.
    "numpy": ("BSD-3-Clause", ()),
    # Prose form of the same terms; only the bootloader ships (native rule).
    "pyinstaller": ("GPL-2.0-or-later WITH Bootloader-exception", ()),
    # Prose declarations of the texts each wheel bundles (MIT, BSD-3, Apache-2.0).
    "onnxruntime": ("MIT", ()),
    "protobuf": ("BSD-3-Clause", ()),
    "sherpa-onnx": ("Apache-2.0", ()),
}
# MPL-2.0 files ship unmodified as bytecode; recipients are told where the exact
# Source Code Form is (MPL-2.0 section 3.2).
MPL_SOURCES = {"tqdm": "https://pypi.org/project/tqdm/{version}/#files"}
# A declared value that is a whole license text or long prose is not an expression.
LONG_DECLARED = "LicenseRef-Declared-As-Full-Text"
NATIVE_STATUSES = {
    "DECLARED",
    "REDISTRIBUTABLE_PROPRIETARY",
    "CONDITIONS_UNCONFIRMED",
    "PATENT_REVIEW_REQUIRED",
}
UNMAPPED = ("UNMAPPED", "NOASSERTION", "UNMAPPED")
NativeMap = dict[str, tuple[str, str, str]]
# L01 D8: third-party code inside the shipped Qt libraries and plugins.
QT_PACKAGES = {"pyside6", "pyside6-essentials", "pyside6-addons", "shiboken6"}
QT_TEXT_ROOT = "licenses/Qt-third-party"
CT2_TEXT_ROOT = "licenses/ctranslate2-native"
PLACEHOLDERS = {"", "none", "null", "n/a", "-", "unknown", "noassertion"}
CT2_ATTRIBUTION_BASIS = "CTRANSLATE2_NATIVE_REVIEW_L05"
# FTL section "Credits": the year of the FreeType version in use (2.14.3, 1996-2026).
FREETYPE_CREDIT = (
    "Portions of this software are copyright (C) 2026 The FreeType Project "
    "(www.freetype.org). All rights reserved."
)
IJG_CREDIT = "This software is based in part on the work of the Independent JPEG Group."
QT_ATTRIBUTION_BASIS = "QT_ATTRIBUTION_JSON_V6_12_0"
VS_REDISTRIBUTION = "https://learn.microsoft.com/en-us/visualstudio/releases/2022/redistribution"


def normalized(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def spdx(expression: str) -> str | None:
    """Canonical SPDX expression, or None when the grammar/identifiers are invalid."""
    try:
        return str(canonicalize_license_expression(expression))
    except InvalidLicenseExpression:
        return None


def load_native_map(source_root: Path) -> NativeMap:
    """Reviewed exact native paths (L03-01). A directory is never evidence of a license:
    any EXE/DLL/PYD not listed here stays UNMAPPED and fails the release build."""
    data = read_json(source_root / "packaging" / "notices" / "native-map.json")
    table: NativeMap = {}
    for group in data["components"]:
        expression = spdx(group["license"])
        if group["status"] not in NATIVE_STATUSES or expression != group["license"]:
            raise ReleaseError("NATIVE_MAP_INVALID")
        for path in group["files"]:
            key = path.replace("\\", "/").lower()
            if key in table:
                raise ReleaseError("NATIVE_MAP_INVALID")
            table[key] = (group["component"], group["license"], group["status"])
    return table


def native_license(path: str, table: NativeMap) -> tuple[str, str, str]:
    return table.get(path.replace("\\", "/").lower(), UNMAPPED)


def cyclonedx_licenses(expression: str) -> list[dict[str, Any]]:
    if expression == "NOASSERTION":
        return []
    canonical = spdx(expression)
    if canonical is not None:
        return [{"expression": canonical}]
    # Not a valid SPDX expression (L03-02): keep it as a named, unasserted license.
    return [{"license": {"name": expression[:200]}}]


def license_gaps(bundle: Path) -> list[str]:
    """Native files a release build may not ship without an explicit mapping."""
    rows = read_json(safe(bundle) / "native-origins.json")["files"]
    return sorted(row["path"] for row in rows if row["license_status"] == "UNMAPPED")


def _notice_texts(source_root: Path) -> dict[str, Path]:
    root = source_root / "packaging" / "notices"
    sources = read_json(root / "SOURCES.json")
    texts = {}
    for row in sources["files"]:
        path = safe(root / row["file"])
        if digest(path) != row["sha256"]:
            raise ReleaseError("NOTICE_TEXT_HASH_MISMATCH")
        texts[row["file"]] = path
    return texts


def _attributions(
    source_root: Path, texts: dict[str, Path], name: str, code: str
) -> list[dict[str, Any]]:
    """Reviewed attribution entries; every text must be pinned (L01 D8)."""
    data = read_json(source_root / "packaging" / "notices" / name)
    entries: list[dict[str, Any]] = data["entries"]
    seen: set[tuple[str, str]] = set()
    for entry in entries:
        key = (entry.get("repo", ""), entry["id"])
        if (
            key in seen
            or not entry["copyright"]
            # A placeholder is not a copyright notice (L05-04).
            or any(line.strip().lower() in PLACEHOLDERS for line in entry["copyright"])
            or spdx(entry["license"]) != entry["license"]
            or not entry["files"]
            or any(name not in texts for name in entry["files"])
        ):
            raise ReleaseError(code)
        seen.add(key)
    return entries


def _corresponding_sources(source_root: Path) -> list[dict[str, Any]]:
    data = read_json(source_root / "packaging" / "notices" / "corresponding-sources.json")
    archives: list[dict[str, Any]] = data["archives"]
    if not archives or any(
        not row["url"].startswith("https://download.qt.io/")
        or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"])
        for row in archives
    ):
        raise ReleaseError("CORRESPONDING_SOURCES_INVALID")
    return archives


def _qt_text(name: str) -> str:
    return f"{QT_TEXT_ROOT}/{name.removeprefix('qt/')}"


def _qt_notice(entries: list[dict[str, Any]], archives: list[dict[str, Any]]) -> list[str]:
    lines = [
        "",
        "Third-party code inside the shipped Qt 6.12.0 libraries and plugins (from Qt's",
        f"qt_attribution.json at v6.12.0; texts under {QT_TEXT_ROOT}/):",
    ]
    for entry in entries:
        version = f" {entry['version']}" if entry["version"] else ""
        lines.append(f"  {entry['name']}{version} ({entry['license']}) in {entry['shipped_in']}")
        lines += [f"    {line}" for line in entry["copyright"]]
        lines.append("    text: " + ", ".join(_qt_text(name) for name in entry["files"]))
    ids = {entry["id"] for entry in entries}
    if "freetype" in ids:
        lines += ["", FREETYPE_CREDIT]
    if "libjpeg" in ids:
        lines += ["", IJG_CREDIT]
    lines += ["", "Exact upstream sources of the LGPL-3.0 Qt and PySide6 code shipped here:"]
    lines += [f"  {row['component']}: {row['url']} (SHA-256 {row['sha256']})" for row in archives]
    lines += [
        "  Whether these sources are also hosted with a public release is an open release",
        "  gate (build-provenance.json).",
    ]
    return lines


def _ct2_text(name: str) -> str:
    return f"{CT2_TEXT_ROOT}/{name.removeprefix('ct2/')}"


def _ct2_notice(entries: list[dict[str, Any]]) -> list[str]:
    lines = [
        "",
        "Code inside ctranslate2/ctranslate2.dll, Recoryn's CPU-only build of CTranslate2",
        "4.9.0 (scripts/build_ctranslate2_cpu.py). Texts under",
        f"{CT2_TEXT_ROOT}/; record packaging/notices/ct2-native.json:",
    ]
    for entry in entries:
        version = f" {entry['version']}" if entry["version"] else ""
        lines.append(f"  {entry['name']}{version} ({entry['license']}) in {entry['shipped_in']}")
        lines += [f"    {line}" for line in entry["copyright"]]
        if entry["note"]:
            lines.append(f"    note: {entry['note']}")
        lines.append("    text: " + ", ".join(_ct2_text(name) for name in entry["files"]))
    lines += [
        "  ctranslate2/vcomp140.dll is Microsoft's redistributable OpenMP runtime (see the",
        "  Microsoft paragraph below).",
    ]
    return lines


def _property(component: dict[str, Any], key: str, default: str = "") -> str:
    for item in component.get("properties", []):
        if item["name"] == key:
            return str(item["value"])
    return default


def _notice(
    version: str,
    components: list[dict[str, Any]],
    binaries: list[dict[str, Any]],
    qt_entries: list[dict[str, Any]],
    archives: list[dict[str, Any]],
    ct2_entries: list[dict[str, Any]],
) -> str:
    lines = [
        f"Recoryn {version} DEVELOPMENT CANDIDATE - not approved for public release.",
        "This notice, sbom.cdx.json and native-origins.json are technical records of the",
        "shipped files; they are not a legal clearance.",
        "",
        "Application: Recoryn, Apache-2.0 (licenses/Recoryn-LICENSE).",
        "Python runtime: CPython, PSF-2.0 including its bundled third-party terms",
        "(licenses/CPython-LICENSE.txt: OpenSSL, libffi, SQLite, zlib, expat, mpdecimal).",
        "",
        "Not distributed by license policy L01 D1-D3 and D7: PyAV and its FFmpeg build",
        "with x264/x265/OpenH264, Qt Multimedia's media backends (FFmpeg and Windows",
        "Media Foundation plugins) and Qt's FFmpeg libraries, Qt Virtual Keyboard with",
        "Qml/Quick, Qt PDF, the Mesa/LLVM software OpenGL fallback, NVIDIA CUDA/cuDNN, and",
        "(L01 D9) the Intel oneMKL/OpenMP and NVIDIA CUDA/cuRAND code that the PyPI",
        "CTranslate2 wheel contains: Recoryn ships a CPU-only build of the same source.",
        "GPU acceleration needs the official runtime, which users obtain themselves.",
        "No FFmpeg code is distributed. Recoryn plays its own verified 16-bit PCM WAV",
        "clips through Qt Multimedia's audio output; no media decoder is used.",
        "",
        "LGPL components are separate shared libraries that may be replaced with",
        "compatible builds of the same version:",
        "  Qt 6.12.0, PySide6 6.12.0, shiboken6 6.12.0: LGPL-3.0-only",
        "    texts licenses/<package>/LGPL-3.0.txt and GPL-3.0.txt;",
        "    files _internal/PySide6/ and _internal/shiboken6/.",
        "  Exact upstream sources are listed after the Qt third-party section below.",
        "",
        "Components (distributed license; notice files under licenses/):",
    ]
    for component in sorted(components, key=lambda row: row["name"].lower()):
        if component["type"] != "library" or _property(component, "recoryn:license-basis") in (
            QT_ATTRIBUTION_BASIS,
            CT2_ATTRIBUTION_BASIS,
        ):
            continue  # Code inside Qt/CTranslate2 binaries has its own sections below.
        notices = json.loads(_property(component, "recoryn:notice-files", "[]"))
        lines.append(
            f"  {component['name']} {component['version']}: "
            f"{_property(component, 'recoryn:distributed-license', 'NOASSERTION')}; "
            f"{', '.join(notices) if notices else 'no notice file in the wheel'}"
        )
    mpl = [
        (component["name"], component["version"])
        for component in components
        if normalized(component["name"]) in MPL_SOURCES
    ]
    # MPL-2.0 data compiled into Qt (Public Suffix List in Qt6Network) is listed too.
    qt_mpl = [entry for entry in qt_entries if "MPL-2.0" in entry["license"]]
    if mpl or qt_mpl:
        lines += ["", "MPL-2.0 files are distributed unmodified; Source Code Form:"]
        lines += [
            f"  {name} {version}: " + MPL_SOURCES[normalized(name)].format(version=version)
            for name, version in sorted(mpl)
        ]
        lines += [
            f"  {entry['name']} {entry['version']} in {entry['shipped_in']}: "
            f"https://code.qt.io/cgit/qt/{entry['repo']}.git/tree/"
            f"{entry['attribution'].rsplit('/', 1)[0]}?h=v6.12.0"
            for entry in qt_mpl
        ]
    if qt_entries:
        lines += _qt_notice(qt_entries, archives)
    if ct2_entries:
        lines += _ct2_notice(ct2_entries)
    open_rows = [row for row in binaries if row["license_status"] != "DECLARED"]
    lines += ["", "Native files with open conditions (see native-origins.json):"]
    lines += [
        f"  {row['license_status']}: {row['path']} - {row['component']} ({row['license']})"
        for row in open_rows
    ] or ["  none"]
    lines += [
        "",
        "Microsoft Visual C++ runtime files (msvcp140*.dll, vcruntime140*.dll) are Visual",
        f"Studio Distributable Code ({VS_REDISTRIBUTION}). Microsoft",
        "limits their redistribution to licensed Visual Studio users under its license",
        "terms; whether the publisher of a release meets that condition",
        "is not yet confirmed (release gate microsoft_runtime_conditions).",
        "",
        "No model weights are bundled. No signing, clean VM or hardware approval is claimed.",
        "The manifest detects changes relative to itself; it is not an authenticity signature.",
        "",
    ]
    return "\n".join(lines)


def _local(path: Path) -> Path:
    # abspath is lexical; no resolve/stat/is_file may precede UNC rejection.
    if str(path).startswith(("\\\\", "//")):
        raise ReleaseError("NETWORK_PATH_FORBIDDEN")
    # Distribution RECORD paths can contain ../Scripts; normalize them locally
    # before applying the same link/hardlink/device-path policy as the installer.
    return safe(Path(os.path.abspath(path)))


def _key(path: Path) -> str:
    return os.path.normcase(str(_local(path).resolve()))


def generate(bundle: Path, toc_path: Path, source_root: Path) -> dict[str, Any]:
    bundle, source_root = safe(bundle), safe(source_root)
    toc = read_json(toc_path)
    if set(toc) != {"pure", "binaries", "datas"} or any(
        not isinstance(group, list) for group in toc.values()
    ):
        raise ReleaseError("INVALID_ANALYSIS_TOC")
    rows = [row for group in toc.values() for row in group]
    if any(
        not isinstance(row, list) or len(row) != 3 or any(not isinstance(item, str) for item in row)
        for row in rows
    ):
        raise ReleaseError("INVALID_ANALYSIS_TOC")
    source_paths = {_key(path) for row in rows if (path := _local(Path(row[1]))).is_file()}
    if not (source_root / "packaging" / "notices" / "SOURCES.json").is_file():
        raise ReleaseError("NOTICE_TEXTS_MISSING")
    notice_texts = _notice_texts(source_root)
    native_map = load_native_map(source_root)
    components = []
    license_root = bundle / "licenses"
    license_root.mkdir()
    for distribution in metadata.distributions():
        owned = [
            entry
            for entry in distribution.files or []
            if _key(Path(str(distribution.locate_file(entry)))) in source_paths
        ]
        if not owned:
            continue
        name = distribution.metadata["Name"] or "UNKNOWN"
        version = distribution.version
        declared = (
            next(iter(distribution.metadata.get_all("License-Expression") or []), None)
            or next(iter(distribution.metadata.get_all("License") or []), None)
            or "NOASSERTION"
        )
        override = LICENSE_OVERRIDES.get(normalized(name))
        full_text = "\n" in declared.strip() or len(declared) > 120
        if override:
            distributed = override[0]
        elif full_text:
            distributed = LONG_DECLARED  # Never paste a whole text into SBOM/NOTICE fields.
        else:
            distributed = declared
        # A full text stays in the copied notice files; the SBOM records its identity
        # instead of a 47 kB property (L03-03).
        declared_properties = (
            [
                {"name": "recoryn:declared-license", "value": LONG_DECLARED},
                {
                    "name": "recoryn:declared-license-sha256",
                    "value": hashlib.sha256(declared.encode("utf-8")).hexdigest(),
                },
                {"name": "recoryn:declared-license-chars", "value": str(len(declared))},
            ]
            if full_text
            else [{"name": "recoryn:declared-license", "value": declared}]
        )
        # Metadata is declared evidence, not an automatic legal classification.
        component: dict[str, Any] = {
            "type": "library",
            "name": name,
            "version": version,
            "purl": f"pkg:pypi/{name.lower().replace('_', '-')}@{version}",
            "properties": [
                *declared_properties,
                {"name": "recoryn:distributed-license", "value": distributed},
                {
                    "name": "recoryn:license-basis",
                    "value": "RECORYN_L01_OVERRIDE" if override else "DECLARED_METADATA",
                },
                {"name": "recoryn:included-source-file-count", "value": str(len(owned))},
            ],
        }
        if licenses := cyclonedx_licenses(distributed):
            component["licenses"] = licenses
        safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
        texts = []
        for text_name in override[1] if override else ():
            target = license_root / safe_name / text_name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(notice_texts[text_name], target)
            texts.append(target.relative_to(bundle).as_posix())
        for entry in distribution.files or []:
            lowered = str(entry).lower()
            if any(token in lowered for token in NOTICE_SKIP):
                continue  # Not the terms Recoryn distributes this component under.
            if any(token in lowered for token in ("license", "copying", "notice", "copyright")):
                source = _local(Path(str(distribution.locate_file(entry))))
                if source.is_file() and source.suffix.lower() in (".txt", ".md", ".rst", ""):
                    source = safe(source)
                    target = license_root / safe_name / source.name
                    if target.exists() and digest(target) != digest(source):
                        target = target.with_name(digest(source)[:10] + "-" + source.name)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
                    texts.append(target.relative_to(bundle).as_posix())
        component["properties"].append(
            {"name": "recoryn:notice-files", "value": json.dumps(sorted(set(texts)))}
        )
        owned_paths = {_key(Path(str(distribution.locate_file(entry)))) for entry in owned}
        included = sorted(
            {
                (row[0], row[2], digest(Path(row[1])))
                for row in rows
                if _key(Path(row[1])) in owned_paths
            }
        )
        component["properties"].append(
            {
                "name": "recoryn:analysis-inputs",
                "value": json.dumps(
                    [
                        {"name": name, "type": kind, "source_sha256": checksum}
                        for name, kind, checksum in included
                    ],
                    sort_keys=True,
                ),
            }
        )
        components.append(component)
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.exists():
        shutil.copyfile(python_license, license_root / "CPython-LICENSE.txt")
    shutil.copyfile(source_root / "LICENSE", license_root / "Recoryn-LICENSE")
    with (source_root / "pyproject.toml").open("rb") as stream:
        version = tomllib.load(stream)["project"]["version"]
    components.append(
        {
            "type": "application",
            "name": "Recoryn",
            "version": version,
            "licenses": [{"license": {"id": "Apache-2.0"}}],
        }
    )
    components.append(
        {
            "type": "framework",
            "name": "CPython",
            "version": platform.python_version(),
            "licenses": [{"license": {"id": "PSF-2.0"}}],
        }
    )
    # L01 D8: Qt's own third-party code is attributed when the Qt runtime ships.
    qt_entries: list[dict[str, Any]] = []
    archives: list[dict[str, Any]] = []
    if any(normalized(row["name"]) in QT_PACKAGES for row in components):
        qt_entries = _attributions(
            source_root, notice_texts, "qt-third-party.json", "QT_ATTRIBUTION_INVALID"
        )
        archives = _corresponding_sources(source_root)
        for name in sorted({name for entry in qt_entries for name in entry["files"]}):
            target = bundle / _qt_text(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(notice_texts[name], target)
        components += [
            {
                "type": "library",
                "name": f"Qt 6.12.0 third-party: {entry['name']}",
                "version": entry["version"] or "unversioned",
                "licenses": cyclonedx_licenses(entry["license"]),
                "properties": [
                    {"name": "recoryn:license-basis", "value": QT_ATTRIBUTION_BASIS},
                    {"name": "recoryn:shipped-in", "value": entry["shipped_in"]},
                    {
                        "name": "recoryn:qt-attribution",
                        "value": f"{entry['repo']}/{entry['attribution']}#{entry['id']}",
                    },
                    {
                        "name": "recoryn:notice-files",
                        "value": json.dumps([_qt_text(name) for name in entry["files"]]),
                    },
                ],
            }
            for entry in qt_entries
        ]
    # L01 D8/D9: code statically inside the CPU-only ctranslate2.dll.
    ct2_entries: list[dict[str, Any]] = []
    if any(normalized(row["name"]) == "ctranslate2" for row in components):
        ct2_entries = _attributions(
            source_root, notice_texts, "ct2-native.json", "CT2_ATTRIBUTION_INVALID"
        )
        for name in sorted({name for entry in ct2_entries for name in entry["files"]}):
            target = bundle / _ct2_text(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(notice_texts[name], target)
        components += [
            {
                "type": "library",
                "name": f"CTranslate2 native: {entry['name']}",
                "version": entry["version"] or "unversioned",
                "licenses": cyclonedx_licenses(entry["license"]),
                "properties": [
                    {"name": "recoryn:license-basis", "value": CT2_ATTRIBUTION_BASIS},
                    {"name": "recoryn:shipped-in", "value": entry["shipped_in"]},
                    {
                        "name": "recoryn:notice-files",
                        "value": json.dumps([_ct2_text(name) for name in entry["files"]]),
                    },
                ],
            }
            for entry in ct2_entries
        ]
    atomic_json(
        bundle / "sbom.cdx.json",
        {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "version": 1,
            "components": sorted(components, key=lambda row: row["name"].lower()),
        },
    )
    source_snapshot = [
        {"path": path.relative_to(source_root).as_posix(), "sha256": digest(path)}
        for path in sorted((source_root / "src" / "recoryn").rglob("*.py"))
    ]
    native_sources: dict[str, set[tuple[str, str]]] = {}
    for row in toc["binaries"] + toc["datas"]:
        source = _local(Path(row[1]))
        if source.is_file():
            native_sources.setdefault(row[0].replace("\\", "/"), set()).add(
                (source.name, digest(source))
            )
    binaries = []
    for item in inventory(bundle):
        if Path(item["path"]).suffix.lower() not in {".exe", ".dll", ".pyd"}:
            continue
        name = item["path"].removeprefix("_internal/")
        origins = native_sources.get(name, set())
        shipped_by, license_expression, status = native_license(item["path"], native_map)
        binaries.append(
            {
                **item,
                "origins": [
                    {"name": origin_name, "source_sha256": checksum}
                    for origin_name, checksum in sorted(origins)
                ],
                "attribution": "ANALYSIS_TOC" if origins else "REVIEW_REQUIRED",
                "component": shipped_by,
                "license": license_expression,
                "license_status": status,
            }
        )
    statuses = {row["license_status"] for row in binaries}
    gates = {
        "fixed_clean_commit": "NOT_RUN",
        "code_signing": "NOT_RUN",
        "clean_windows_vm": "NOT_RUN",
        # Texts and replaceable shared libraries are provided; publishing the
        # corresponding source for a public release is still a G4 decision.
        "qt_corresponding_source_and_notices": (
            "TEXTS_INCLUDED_UPSTREAM_SOURCES_RECORDED_HOSTING_DECISION_REQUIRED"
        ),
        # L01 D1 and D7: verify() refuses any PyAV or Qt FFmpeg file, so no FFmpeg
        # source offer or codec patent question remains for this distribution.
        "ffmpeg_build_flags_corresponding_source_and_notices": "NOT_DISTRIBUTED_L01_D1_D7",
        "transitive_native_license_review": (
            "UNMAPPED_NATIVE_FILES"
            if "UNMAPPED" in statuses
            else "MAPPED_WITH_OPEN_CONDITIONS"
            if statuses - {"DECLARED"}
            else "MAPPED"
        ),
        "physical_hardware": "NOT_RUN",
        # Classification is not confirmation (L03-04, L01-02).
        # L01 D9: the CPU-only CTranslate2 build carries no Intel or NVIDIA runtime.
        "intel_runtime_conditions": "NOT_DISTRIBUTED_L01_D9",
        "nvidia_runtime_conditions": "NOT_DISTRIBUTED_L01_D9",
        "microsoft_runtime_conditions": "REVIEW_REQUIRED",
    }
    atomic_json(
        bundle / "build-provenance.json",
        {
            "schema_version": 1,
            "version": version,
            "python": platform.python_version(),
            "platform": platform.platform(),
            "pyinstaller": metadata.version("pyinstaller"),
            "pyinstaller_hooks_contrib": metadata.version("pyinstaller-hooks-contrib"),
            "source_snapshot": source_snapshot,
            "build_inputs": read_json(source_root / "build-inputs.json"),
            "analysis_toc_sha256": digest(toc_path),
            "gates": gates,
            "claim": "개발 후보; SBOM은 실제 TOC 귀속 관찰이며 native 전이 의존성의 법률 승인이 아님",
        },
    )
    atomic_json(
        bundle / "native-origins.json",
        {
            "schema_version": 1,
            "files": binaries,
            "unattributed_native_components": "REVIEW_REQUIRED",
        },
    )
    (bundle / "NOTICE.txt").write_text(
        _notice(version, components, binaries, qt_entries, archives, ct2_entries),
        encoding="utf-8",
    )
    manifest = {
        "schema_version": 1,
        "app_id": APP_ID,
        "version": version,
        "distribution_status": "DEVELOPMENT_CANDIDATE",
        "gates": gates,
        "files": inventory(bundle),
    }
    atomic_json(bundle / MANIFEST, manifest)
    return manifest
