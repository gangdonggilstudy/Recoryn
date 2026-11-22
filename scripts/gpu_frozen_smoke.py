"""Check GPU runtime activation inside a frozen Recoryn bundle on a real NVIDIA GPU (L-P08).

Usage: python scripts/gpu_frozen_smoke.py --bundle <dist/Recoryn> --runtime-root <folder>
       --output <new folder>

The runtime must already be installed under ``--runtime-root`` (the in-app opt-in
download, L01 D10); this script never downloads. It verifies the installed files
against the source catalog, builds a small random-weight Whisper model (no weights are
downloaded), runs ``Recoryn-CLI.exe --release-gpu-smoke`` and judges the facts the
probe reports by its own rules instead of trusting a pass string. It cannot prove the
report itself is genuine. Exit 0 only on PASS.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from recoryn.models import gpu_runtime as gpu  # noqa: E402

# Written by hand from the L-P07 import table, not derived from gpu.DLL_LOAD_ORDER: these
# are the only runtime files a working activation maps (cuDNN is never used).
EXPECTED_RUNTIME_MODULES = frozenset(
    {
        "ctranslate2/_ext.cp313-win_amd64.pyd",
        "ctranslate2/ctranslate2.dll",
        "ctranslate2/libiomp5md.dll",
        "nvidia/cublas/bin/cublas64_12.dll",
        "nvidia/cublas/bin/cublaslt64_12.dll",
    }
)
# Any of these loaded from outside the runtime means another copy took part (L08-01).
FOREIGN_NAMES = frozenset(
    {
        "ctranslate2.dll",
        "libiomp5md.dll",
        "_ext.cp313-win_amd64.pyd",
        "cublas64_12.dll",
        "cublaslt64_12.dll",
    }
)
FOREIGN_PREFIXES = ("cublas",)  # other cuBLAS versions too
MODULE_FILE = "ctranslate2/__init__.py"
EXT_FILE = "ctranslate2/_ext.cp313-win_amd64.pyd"
PROMPTS = 2  # the probe generates for two fixed prompts
COMPUTE_TYPES = ("float16", "float32")
REQUIRED = (
    "activate",
    "frozen",
    "bundle",
    "module",
    "ext",
    "version",
    "cuda_devices",
    "faster_whisper_uses_runtime",
    "runs",
    "tokens",
    "loaded",
)
# Exact types: bool is not accepted where an int is expected (L08-04).
TYPES: dict[str, type] = {
    "frozen": bool,
    "bundle": str,
    "module": str,
    "ext": str,
    "version": str,
    "cuda_devices": int,
    "faster_whisper_uses_runtime": bool,
    "runs": dict,
    "tokens": dict,
    "loaded": list,
}


_DRIVE = re.compile(r"[A-Za-z]:[\\/]")
_LOCAL_DRIVE_TYPES = frozenset({2, 3, 6})  # removable, fixed, RAM disk (GetDriveTypeW)


def _drive_type(root: str) -> int:
    import ctypes

    return int(ctypes.windll.kernel32.GetDriveTypeW(root))


def _local(path: str) -> bool:
    """A drive-letter path on a local volume, decided from the string and drive type only.

    UNC, device namespaces (``\\\\?\\``, ``\\\\.\\``), relative paths and mapped network
    drives are never handed to the OS path resolver (L08-06).
    """
    return bool(_DRIVE.match(path)) and _drive_type(path[:3]) in _LOCAL_DRIVE_TYPES


def _norm(path: str) -> str:
    # realpath gives the long final name, so an 8.3 alias of the same folder compares
    # equal (L08-05); normcase matches Windows' case-insensitive names. Paths that are
    # not local are compared as plain strings and never resolved (L08-06).
    if not _local(path):
        return os.path.normcase(path)
    return os.path.normcase(os.path.realpath(path))


def _inside(path: str, folder: str) -> bool:
    return _norm(path).startswith(_norm(folder).rstrip("\\/") + os.sep)


def _same(path: str, expected: Path) -> bool:
    return _norm(path) == _norm(str(expected))


def _ints(values: Any) -> bool:
    return (
        type(values) is list
        and bool(values)
        and all(type(value) is int and value >= 0 for value in values)
    )


def _schema(report: dict[str, Any]) -> list[str]:
    failures = [
        "BAD_TYPE_" + key.upper() for key, kind in TYPES.items() if type(report[key]) is not kind
    ]
    if report["activate"] is not None and type(report["activate"]) is not str:
        failures.append("BAD_TYPE_ACTIVATE")
    if type(report["loaded"]) is list and not all(type(path) is str for path in report["loaded"]):
        failures.append("BAD_TYPE_LOADED")
    return failures


def _runs(runs: dict[str, Any], devices: int) -> list[str]:
    if set(runs) != set(COMPUTE_TYPES) or not all(type(run) is dict for run in runs.values()):
        return ["RUNS_MALFORMED"]
    failures = []
    for compute in COMPUTE_TYPES:
        run = runs[compute]
        if run.get("device") != "cuda":
            failures.append("RUN_NOT_ON_CUDA")
        if run.get("compute_type") != compute:
            failures.append("RUN_COMPUTE_TYPE_MISMATCH")
        index = run.get("device_index")
        if not _ints(index) or any(value >= devices for value in index):
            failures.append("RUN_DEVICE_INDEX_INVALID")
    return sorted(set(failures), key=failures.index)


def _tokens(tokens: dict[str, Any]) -> list[str]:
    if set(tokens) != set(COMPUTE_TYPES) or not all(
        type(batch) is list and len(batch) == PROMPTS and all(_ints(seq) for seq in batch)
        for batch in tokens.values()
    ):
        return ["TOKENS_MALFORMED"]
    if tokens["float16"] != tokens["float32"]:
        return ["FLOAT16_FLOAT32_TOKENS_DIFFER"]
    return []


def verdict(report: dict[str, Any], active: Path, pyc: list[str]) -> list[str]:
    """Every failed condition; an empty list is a pass."""
    missing = [key for key in REQUIRED if key not in report]
    if missing:
        return ["MISSING_" + key.upper() for key in missing]
    schema = _schema(report)
    if schema:
        return schema
    failures = []
    if not all(_local(path) for path in [report["module"], report["ext"], *report["loaded"]]):
        failures.append("NON_LOCAL_PATH_REPORTED")
    if report["activate"] is not None:
        failures.append("ACTIVATION_FAILED")
    if report["frozen"] is not True or not report["bundle"]:
        failures.append("NOT_FROZEN")
    if type(report.get("exitcode")) is not int or report["exitcode"] != 0:
        failures.append("CHILD_EXIT_NONZERO")
    if not _same(report["module"], active / MODULE_FILE):
        failures.append("MODULE_NOT_RUNTIME_FILE")
    if not _same(report["ext"], active / EXT_FILE):
        failures.append("EXT_NOT_RUNTIME_FILE")
    if report["version"] != "4.9.0":
        failures.append("VERSION_MISMATCH")
    if report["cuda_devices"] < 1:
        failures.append("NO_CUDA_DEVICE")
    if report["faster_whisper_uses_runtime"] is not True:
        failures.append("FASTER_WHISPER_OTHER_MODULE")
    failures += _runs(report["runs"], report["cuda_devices"])
    failures += _tokens(report["tokens"])
    site = str(active)
    loaded = report["loaded"]
    from_runtime = {
        os.path.relpath(_norm(path), _norm(site)).replace(os.sep, "/").lower()
        for path in loaded
        if _inside(path, site)
    }
    if from_runtime != EXPECTED_RUNTIME_MODULES:
        failures.append("RUNTIME_MODULE_SET_MISMATCH")
    if any("cudnn" in os.path.basename(path).lower() for path in loaded):
        failures.append("CUDNN_LOADED")
    if any(
        not _inside(path, site)
        and (
            os.path.basename(path).lower() in FOREIGN_NAMES
            or os.path.basename(path).lower().startswith(FOREIGN_PREFIXES)
        )
        for path in loaded
    ):
        failures.append("FOREIGN_RUNTIME_LOADED")
    if pyc:
        failures.append("PYC_WRITTEN_IN_RUNTIME")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    options.output.mkdir(parents=True)  # new folder only; never reuse evidence
    manager = gpu.GpuRuntimeManager(options.runtime_root.absolute())
    if manager.status() != "READY":
        raise SystemExit("GPU runtime is not installed under --runtime-root")
    manager.verify()
    from compare_ctranslate2_builds import build_model

    model = options.output / "model-small"
    build_model(model)
    command = [
        str(options.bundle.absolute() / "Recoryn-CLI.exe"),
        "--release-gpu-smoke",
        "--runtime-root",
        str(options.runtime_root.absolute()),
        "--model",
        str(model.absolute()),
    ]
    done = subprocess.run(
        command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600
    )
    (options.output / "probe.stderr.log").write_text(done.stderr, encoding="utf-8")
    lines = done.stdout.strip().splitlines()
    report = json.loads(lines[-1]) if lines else {}
    pyc = sorted(str(path) for path in manager.active.rglob("*.pyc"))
    failures = verdict(report, manager.active, pyc)
    manager.verify()  # the runtime is unchanged after use
    result = {
        "status": "PASS" if not failures and done.returncode == 0 else "FAIL",
        "failures": failures,
        "returncode": done.returncode,
        "report": report,
        "pyc_in_runtime": pyc,
    }
    (options.output / "gpu-smoke.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("status", "failures", "returncode")}))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
