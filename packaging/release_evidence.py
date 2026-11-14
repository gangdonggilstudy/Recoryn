"""실제 PyInstaller TOC와 output 파일 기준 후보 SBOM/무결성 목록 생성."""

from __future__ import annotations

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
        # Metadata is declared evidence, not an automatic legal classification.
        component: dict[str, Any] = {
            "type": "library",
            "name": name,
            "version": version,
            "purl": f"pkg:pypi/{name.lower().replace('_', '-')}@{version}",
            "properties": [
                {
                    "name": "recoryn:declared-license",
                    "value": distribution.metadata["License-Expression"]
                    or distribution.metadata["License"]
                    or "NOASSERTION",
                },
                {"name": "recoryn:included-source-file-count", "value": str(len(owned))},
            ],
        }
        texts = []
        for entry in distribution.files or []:
            if any(
                token in str(entry).lower()
                for token in ("license", "copying", "notice", "copyright")
            ):
                source = _local(Path(str(distribution.locate_file(entry))))
                if source.is_file() and source.suffix.lower() in (".txt", ".md", ".rst", ""):
                    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
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
    gates = {
        "fixed_clean_commit": "NOT_RUN",
        "code_signing": "NOT_RUN",
        "clean_windows_vm": "NOT_RUN",
        "qt_corresponding_source_and_notices": "REVIEW_REQUIRED",
        "ffmpeg_build_flags_corresponding_source_and_notices": "REVIEW_REQUIRED",
        "transitive_native_license_review": "REVIEW_REQUIRED",
        "physical_hardware": "NOT_RUN",
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
        binaries.append(
            {
                **item,
                "origins": [
                    {"name": origin_name, "source_sha256": checksum}
                    for origin_name, checksum in sorted(origins)
                ],
                "attribution": "ANALYSIS_TOC" if origins else "REVIEW_REQUIRED",
            }
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
        "Recoryn DEVELOPMENT CANDIDATE — not approved for public release.\n"
        "Application license: licenses/Recoryn-LICENSE. Runtime notices: licenses/.\n"
        "sbom.cdx.json records observed bundled package inputs; it is not a legal clearance.\n"
        "native-origins.json records shipped native file hashes and TOC attribution.\n"
        "Qt/PySide/Shiboken, codecs/FFmpeg and transitive native source/notice obligations "
        "require review for these exact binaries. See build-provenance.json gates.\n"
        "No model weights are bundled. No signing, clean VM or hardware approval is claimed.\n"
        "The manifest detects changes relative to itself; it is not an authenticity signature.\n",
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
