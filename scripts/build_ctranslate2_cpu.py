"""Build the CPU-only CTranslate2 4.9.0 wheel that Recoryn bundles (license policy L01 D9).

The PyPI Windows wheel statically links Intel oneMKL, ships the Intel OpenMP runtime and
compiles in NVIDIA CUDA runtime/cuRAND code. This build uses the same pinned sources with
WITH_MKL=OFF, WITH_CUDA=OFF, WITH_DNNL=ON (oneDNN 3.1.1, static, MSVC OpenMP) and
OPENMP_RUNTIME=COMP, so the wheel carries only open-source code plus Microsoft's
redistributable OpenMP runtime (vcomp140.dll). GPU users obtain the official runtime
themselves (D10).

Usage: python scripts/build_ctranslate2_cpu.py --output build/ct2-cpu-<id>
Requires Windows, Visual Studio 2022 with the C++ workload, Git and network access to
GitHub and PyPI (sources and the pinned pybind11 build dependency only).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

CT2_TAG, CT2_COMMIT = "v4.9.0", "a22ba1c63ee35d1a0d25db149aa2a66d36a6a732"
SUBMODULES = {  # only what a CPU build compiles; CUDA/test/CLI submodules are not fetched
    "third_party/cpu_features": "8a494eb1e158ec2050e5f699a504fbc9b896a43b",
    "third_party/spdlog": "76fb40d95455f249bd70824ecfcae7a8f0930fa3",
}
ONEDNN_TAG, ONEDNN_COMMIT = "v3.1.1", "64f6bcbcbab628e96f33a62c3e975f8535a7bde4"
LOCAL_VERSION = "4.9.0+recoryn.cpu1"
# The wheel build backend (python/pyproject.toml) is installed offline from these pinned files.
BUILD_DEPS = {
    "pybind11==2.13.6": "237c41e29157b962835d356b370ededd57594a26d5894a795960f0047cb5caf5",
    "setuptools==84.2.1": "ca140b45d5325a9478f880e351484f62fef15f336462e449ca0c03c873d589c2",
    "wheel==0.48.0": "3217dcc807155e45db462d7ef2431f5ddda0d7273b700d05a67b271ceb1287ab",
    "packaging==26.3": "d7193f7c8e4e93f444fde0262bf90af30e16fa0ad0ad44cb553c87339b23cd1c",
}
# The exact toolchain of the pinned artifact; any other one is refused (L06-02).
TOOLCHAIN = {"msvc": "14.42.34433", "cmake": "3.29.5-msvc4", "python": "3.13.1"}
# Microsoft.VC143.OpenMP of that toolset (Visual Studio Distributable Code).
VCOMP_SHA256 = "036b9b3f7ece8dfd48aeccd77113721c5305043aaa9c64d1e72812252727aa7c"
# Every option that selects a backend or extra code is explicit, not a source default.
CT2_OPTIONS = {
    "BUILD_CLI": "OFF",
    "BUILD_TESTS": "OFF",
    "BUILD_SHARED_LIBS": "ON",
    "WITH_MKL": "OFF",
    "WITH_DNNL": "ON",
    "WITH_CUDA": "OFF",
    "WITH_CUDNN": "OFF",
    "WITH_RUY": "OFF",
    "WITH_OPENBLAS": "OFF",
    "WITH_ACCELERATE": "OFF",
    "WITH_HIP": "OFF",
    "WITH_MPS": "OFF",
    "WITH_FLASH_ATTN": "OFF",
    "WITH_TENSOR_PARALLEL": "OFF",
    "ENABLE_CPU_DISPATCH": "ON",
    "OPENMP_RUNTIME": "COMP",
}
ONEDNN_OPTIONS = {
    "ONEDNN_LIBRARY_TYPE": "STATIC",
    "ONEDNN_CPU_RUNTIME": "OMP",
    "ONEDNN_BUILD_EXAMPLES": "OFF",
    "ONEDNN_BUILD_TESTS": "OFF",
    "ONEDNN_ENABLE_WORKLOAD": "INFERENCE",
    "ONEDNN_BUILD_GRAPH": "OFF",
}
# Imports and strings that must not appear in the built DLL (Intel/NVIDIA runtimes).
FORBIDDEN_IMPORTS = ("libiomp5md.dll", "cudart64", "cublas", "cudnn", "nvcuda")
FORBIDDEN_STRINGS = (
    b"CUDA driver version is insufficient",
    b"cudaGetDeviceCount",
    b"nvcuda.dll",
    b"cublas64_",
    b"Intel(R) oneAPI Math Kernel Library",
    b"libiomp5md",
)


def run(command: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> str:
    print("+", " ".join(command), flush=True)
    done = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if done.returncode:
        print(done.stdout[-4000:], flush=True)
        print(done.stderr[-4000:], flush=True)
        raise SystemExit(f"STEP_FAILED {done.returncode}: {command[0]}")
    return done.stdout


def visual_studio() -> Path:
    vswhere = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
    vswhere = vswhere / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
    path = run(
        [
            str(vswhere),
            "-latest",
            "-products",
            "*",
            "-requires",
            "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
            "-property",
            "installationPath",
        ]
    ).strip()
    if not path:
        raise SystemExit("VISUAL_STUDIO_CPP_REQUIRED")
    return Path(path)


def clone(url: str, tag: str, commit: str, target: Path) -> None:
    run(
        [
            "git",
            "-c",
            "advice.detachedHead=false",
            "clone",
            "-q",
            "--depth",
            "1",
            "--branch",
            tag,
            url,
            str(target),
        ]
    )
    head = run(["git", "rev-parse", "HEAD"], cwd=target).strip()
    if head != commit:
        raise SystemExit(f"SOURCE_COMMIT_MISMATCH {url} {head}")


def developer_environment(vs: Path) -> dict[str, str]:
    """Environment of vcvars64.bat (cl.exe, INCLUDE, LIB) for the extension build."""
    script = vs / "VC" / "Auxiliary" / "Build" / "vcvars64.bat"
    done = subprocess.run(
        f'cmd /d /s /c ""{script}" >nul 2>&1 && set"',
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    env = dict(
        line.split("=", 1)
        for line in done.stdout.splitlines()
        if "=" in line and not line.startswith("=")
    )
    search = next((value for key, value in env.items() if key.upper() == "PATH"), "")
    compilers = [Path(item) / "cl.exe" for item in search.split(";") if item]
    compiler = next((path for path in compilers if path.is_file()), None)
    if compiler is None or _toolset(compiler) != TOOLCHAIN["msvc"]:
        raise SystemExit(f"MSVC_DEVELOPER_ENVIRONMENT_MISMATCH {compiler}")
    return env


def openmp_runtime(vs: Path) -> Path:
    path = vs / "VC" / "Redist" / "MSVC" / TOOLCHAIN["msvc"] / "x64"
    path = path / "Microsoft.VC143.OpenMP" / "vcomp140.dll"
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != VCOMP_SHA256:
        raise SystemExit("MSVC_OPENMP_REDIST_MISMATCH")
    return path


def _toolset(compiler: Path) -> str:
    """MSVC toolset version from .../VC/Tools/MSVC/<version>/bin/... (empty if not one)."""
    parts = [part.lower() for part in compiler.parts]
    for index in range(len(parts) - 2):
        if parts[index : index + 2] == ["tools", "msvc"]:
            return compiler.parts[index + 2]
    return ""


def check_toolchain(vs: Path, cmake_exe: str) -> dict[str, str]:
    import platform

    found = {
        "msvc": TOOLCHAIN["msvc"]
        if (vs / "VC" / "Tools" / "MSVC" / TOOLCHAIN["msvc"]).is_dir()
        else "missing",
        "cmake": run([cmake_exe, "--version"]).splitlines()[0].removeprefix("cmake version "),
        "python": platform.python_version(),
    }
    if found != TOOLCHAIN:
        raise SystemExit(f"TOOLCHAIN_MISMATCH {found}")
    return found


def cache_options(build: Path, expected: dict[str, str]) -> dict[str, str]:
    """The configured values, read back from CMakeCache.txt; any drift is refused."""
    entries = {}
    for line in (
        (build / "CMakeCache.txt").read_text(encoding="utf-8", errors="replace").splitlines()
    ):
        match = re.fullmatch(r"([A-Za-z0-9_]+):[A-Z]+=(.*)", line)
        if match:
            entries[match.group(1)] = match.group(2)
    configured = {key: entries.get(key, "") for key in expected}
    if {key: value.upper() for key, value in configured.items()} != expected:
        raise SystemExit(f"CMAKE_OPTION_MISMATCH {configured}")
    # The Visual Studio generator records the chosen compiler outside the cache.
    records = list(build.glob(f"CMakeFiles/{TOOLCHAIN['cmake']}/CMakeCXXCompiler.cmake"))
    text = records[0].read_text(encoding="utf-8", errors="replace") if len(records) == 1 else ""
    found = re.search(r'set\(CMAKE_CXX_COMPILER "([^"]+)"\)', text)
    configured["CMAKE_CXX_COMPILER"] = found.group(1) if found else ""
    if _toolset(Path(configured["CMAKE_CXX_COMPILER"])) != TOOLCHAIN["msvc"]:
        raise SystemExit(f"TOOLCHAIN_MISMATCH compiler {configured['CMAKE_CXX_COMPILER']}")
    return configured


def pe_imports(path: Path) -> list[str]:
    import importlib

    pefile: Any = importlib.import_module("pefile")
    pe = pefile.PE(str(path), fast_load=True)
    pe.parse_data_directories(
        directories=[
            pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
            pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"],
        ]
    )
    entries = list(getattr(pe, "DIRECTORY_ENTRY_IMPORT", [])) + list(
        getattr(pe, "DIRECTORY_ENTRY_DELAY_IMPORT", [])
    )
    return sorted(entry.dll.decode().lower() for entry in entries)


def check_dll(path: Path) -> dict[str, Any]:
    """The built DLL must carry no Intel/NVIDIA runtime (also enforced by the release builder)."""
    imports = pe_imports(path)
    data = path.read_bytes()
    bad_imports = [name for name in imports if name.startswith(FORBIDDEN_IMPORTS)]
    bad_strings = [text.decode() for text in FORBIDDEN_STRINGS if text in data]
    if bad_imports or bad_strings or "vcomp140.dll" not in imports:
        raise SystemExit(f"CPU_BUILD_CHECK_FAILED {bad_imports} {bad_strings} {imports}")
    return {"imports": imports, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 4)
    options = parser.parse_args()
    if sys.platform != "win32":
        raise SystemExit("WINDOWS_BUILD_REQUIRED")
    work = options.output.absolute()
    work.mkdir(parents=True, exist_ok=False)
    vs = visual_studio()
    cmake = vs / "Common7" / "IDE" / "CommonExtensions" / "Microsoft" / "CMake" / "CMake" / "bin"
    cmake_exe = str(cmake / "cmake.exe")
    # The single installed toolset is used; cache_options() verifies it is the pinned one.
    generator = ["-G", "Visual Studio 17 2022", "-A", "x64"]
    toolchain = check_toolchain(vs, cmake_exe)
    jobs = str(options.jobs)
    # Sources are UTF-8; without /utf-8 MSVC reads them in the system code page (e.g. cp949)
    # and the extension's docstrings become invalid UTF-8 at import time.
    compile_env = dict(os.environ, CL="/utf-8")

    ct2, onednn = work / "CTranslate2", work / "oneDNN"
    clone("https://github.com/OpenNMT/CTranslate2.git", CT2_TAG, CT2_COMMIT, ct2)
    for path, commit in SUBMODULES.items():
        run(["git", "submodule", "update", "--init", "--depth", "1", path], cwd=ct2)
        head = run(["git", "rev-parse", "HEAD"], cwd=ct2 / path).strip()
        if head != commit:
            raise SystemExit(f"SUBMODULE_COMMIT_MISMATCH {path} {head}")
    clone("https://github.com/oneapi-src/oneDNN.git", ONEDNN_TAG, ONEDNN_COMMIT, onednn)

    onednn_prefix, ct2_prefix = work / "onednn-install", work / "ct2-install"
    run(
        [
            cmake_exe,
            "-S",
            str(onednn),
            "-B",
            str(onednn / "build"),
            *generator,
            f"-DCMAKE_INSTALL_PREFIX={onednn_prefix}",
            *[f"-D{key}={value}" for key, value in ONEDNN_OPTIONS.items()],
        ],
        env=compile_env,
    )
    onednn_cache = cache_options(onednn / "build", ONEDNN_OPTIONS)
    run(
        [
            cmake_exe,
            "--build",
            str(onednn / "build"),
            "--config",
            "Release",
            "--target",
            "install",
            "--parallel",
            jobs,
        ],
        env=compile_env,
    )
    run(
        [
            cmake_exe,
            "-S",
            str(ct2),
            "-B",
            str(ct2 / "build"),
            *generator,
            "-DCMAKE_POLICY_VERSION_MINIMUM=3.5",
            f"-DCMAKE_INSTALL_PREFIX={ct2_prefix}",
            f"-DCMAKE_PREFIX_PATH={onednn_prefix}",
            *[f"-D{key}={value}" for key, value in CT2_OPTIONS.items()],
        ],
        env=compile_env,
    )
    ct2_cache = cache_options(ct2 / "build", CT2_OPTIONS)
    run(
        [
            cmake_exe,
            "--build",
            str(ct2 / "build"),
            "--config",
            "Release",
            "--target",
            "install",
            "--parallel",
            jobs,
        ],
        env=compile_env,
    )

    dll = ct2_prefix / "bin" / "ctranslate2.dll"
    dll_check = check_dll(dll)
    package = ct2 / "python" / "ctranslate2"
    shutil.copyfile(dll, package / "ctranslate2.dll")
    omp = openmp_runtime(vs)
    shutil.copyfile(omp, package / "vcomp140.dll")
    shutil.copyfile(ct2 / "README.md", ct2 / "python" / "README.md")
    (package / "version.py").write_text(
        f'"""Version information."""\n\n__version__ = "{LOCAL_VERSION}"\n', encoding="utf-8"
    )
    # setuptools compiles the pybind11 extension with the MSVC developer environment.
    env = developer_environment(vs)
    env.update(CTRANSLATE2_ROOT=str(ct2_prefix), DISTUTILS_USE_SDK="1", MSSdk="1", CL="/utf-8")
    deps, dist = work / "build-deps", work / "dist"
    requirements = work / "build-deps.txt"
    lines = [f"{name} --hash=sha256:{digest}" for name, digest in BUILD_DEPS.items()]
    requirements.write_text("\n".join(lines) + "\n", encoding="utf-8")
    run(
        [
            sys.executable,
            "-m",
            "pip",
            "download",
            "--no-deps",
            "--require-hashes",
            "-d",
            str(deps),
            "-r",
            str(requirements),
        ]
    )
    run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-index",
            "--find-links",
            str(deps),
            "-w",
            str(dist),
            str(ct2 / "python"),
        ],
        env=env,
    )
    wheels = list(dist.glob("ctranslate2-*.whl"))
    if len(wheels) != 1:
        raise SystemExit("WHEEL_NOT_BUILT")
    # Import the built wheel itself (not an installed copy) and confirm it has no CUDA.
    unpacked = work / "wheel-check"
    shutil.unpack_archive(wheels[0], unpacked, format="zip")
    probe = (
        "import sys; sys.path.insert(0, sys.argv[1]); import ctranslate2; "
        "print(ctranslate2.__file__, ctranslate2.__version__, ctranslate2.get_cuda_device_count())"
    )
    imported = run([sys.executable, "-c", probe, str(unpacked)]).split()
    if (
        len(imported) != 3
        or not Path(imported[0]).resolve().is_relative_to(unpacked.resolve())
        or imported[1:] != [LOCAL_VERSION, "0"]
    ):
        raise SystemExit(f"WHEEL_IMPORT_CHECK_FAILED {imported}")
    report = {
        "ctranslate2": {"tag": CT2_TAG, "commit": CT2_COMMIT, "submodules": SUBMODULES},
        "onednn": {"tag": ONEDNN_TAG, "commit": ONEDNN_COMMIT},
        "toolchain": toolchain,
        "options": {"ctranslate2": ct2_cache, "onednn": onednn_cache},
        "compile_flags": "CL=/utf-8",
        "version": LOCAL_VERSION,
        "ctranslate2_dll": dll_check,
        "vcomp140": {"source": str(omp), "sha256": hashlib.sha256(omp.read_bytes()).hexdigest()},
        "wheel": {
            "name": wheels[0].name,
            "sha256": hashlib.sha256(wheels[0].read_bytes()).hexdigest(),
        },
    }
    (work / "ct2-cpu-build.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
