"""사용자 데이터/기존 dist에 손대지 않는 고유 출력 전용 개발 release 빌더."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path
from typing import Any


def snapshot_inputs(root: Path, destination: Path) -> Path:
    """Copy a bounded source tree; detect edits during snapshot, never reset Git."""
    from release_manager import ReleaseError, atomic_json, digest, safe

    root, destination = safe(root), safe(destination)
    if destination.is_relative_to(root / "src") or destination.is_relative_to(root / "packaging"):
        raise ReleaseError("BUILD_OUTPUT_OVERLAPS_SOURCE")
    sources = [root / name for name in ("LICENSE", "pyproject.toml", "scripts/build_release.py")]
    for directory in ("src/recoryn", "packaging"):
        for source in (root / directory).rglob("*"):
            safe(source)
            if source.is_file() and (
                source.suffix in {".py", ".pyi", ".spec"} or source.name == "py.typed"
            ):
                sources.append(source)
    sources.extend(path for path in root.glob("requirements*.txt") if path.is_file())
    before: list[dict[str, Any]] = [
        {
            "path": path.relative_to(root).as_posix(),
            "size": path.stat().st_size,
            "sha256": digest(path),
        }
        for path in sorted(sources)
    ]
    destination.mkdir(parents=True, exist_ok=False)
    for path, record in zip(sorted(sources), before, strict=True):
        target = destination / record["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(safe(path), target)
        if digest(target) != record["sha256"] or digest(path) != record["sha256"]:
            raise ReleaseError("SOURCE_CHANGED_DURING_SNAPSHOT")
    # Also detect an earlier copied file changing while the later files were read.
    if any(digest(root / record["path"]) != record["sha256"] for record in before):
        raise ReleaseError("SOURCE_CHANGED_DURING_SNAPSHOT")
    atomic_json(destination / "build-inputs.json", {"schema_version": 1, "files": before})
    return destination


def build(output: Path, *, smoke: bool = False) -> Path:
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "packaging"))
    from release_evidence import generate
    from release_manager import ReleaseError, safe, verify

    if sys.platform != "win32":
        raise ReleaseError("WINDOWS_BUILD_REQUIRED")
    if sys.version_info[:2] != (3, 13):
        raise ReleaseError("PYTHON_313_BUILD_REQUIRED")
    for package, expected in (
        ("pyinstaller", "6.22.3"),
        ("PySide6-Essentials", "6.12.0"),
        ("PySide6-Addons", "6.12.0"),
        ("av", "16.1.0"),
        ("faster-whisper", "1.2.1"),
        ("ctranslate2", "4.9.0"),
        ("onnxruntime", "1.32.0"),
        ("numpy", "2.3.5"),
        ("tokenizers", "0.23.3"),
        ("huggingface-hub", "2.4.0"),
        ("sherpa-onnx", "2.0.1"),
        ("sherpa-onnx-core", "2.0.1"),
        ("onnx", "1.23.2"),
    ):
        if version(package) != expected:
            raise ReleaseError("BUILD_DEPENDENCY_VERSION_MISMATCH")
    output = safe(output)
    if output.is_relative_to(root) and not any(
        output.is_relative_to(root / directory) for directory in ("build", "dist")
    ):
        raise ReleaseError("BUILD_OUTPUT_OVERLAPS_SOURCE")
    output.mkdir(parents=True, exist_ok=False)
    snapshot = snapshot_inputs(root, output / "inputs")
    environment = dict(os.environ)
    environment.update(
        {
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "HF_HUB_OFFLINE": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1",
            "DO_NOT_TRACK": "1",
            "PIP_NO_INDEX": "1",
            "RECORYN_BUILD_EVIDENCE": str(output / "analysis-toc.json"),
            "PYTHONPATH": os.pathsep.join((str(snapshot / "src"), str(snapshot / "packaging"))),
        }
    )
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--distpath",
        str(output / "dist"),
        "--workpath",
        str(output / "work"),
        str(snapshot / "packaging" / "recoryn.spec"),
    ]
    with (output / "build.log").open("xb") as log:
        subprocess.run(
            command,
            cwd=snapshot,
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=True,
            timeout=1800,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    bundle = output / "dist" / "Recoryn"
    generate(bundle, output / "analysis-toc.json", snapshot)
    verify(bundle)
    if smoke:
        with (
            (output / "smoke.stdout.json").open("xb") as out,
            (output / "smoke.stderr.log").open("xb") as err,
        ):
            subprocess.run(
                [str(bundle / "Recoryn-CLI.exe"), "--release-smoke"],
                cwd=output,
                env=environment,
                stdout=out,
                stderr=err,
                check=True,
                timeout=180,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        result = json.loads((output / "smoke.stdout.json").read_text(encoding="utf-8"))
        if result.get("status") != "PASS":
            raise ReleaseError("FROZEN_SMOKE_FAILED")
    return bundle


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Recoryn 개발 후보 onedir 빌드; 기존 출력 덮어쓰기 금지"
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--smoke", action="store_true")
    options = parser.parse_args()
    print(build(options.output, smoke=options.smoke))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
