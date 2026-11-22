"""Frozen GPU activation probe and its independent verdict (L-P08).

Case space: docs/testing/l08-frozen-gpu-cases.md. Verdict reports are synthetic and the
expected codes are written by hand; the probe itself runs only with an absent runtime or
fake CTranslate2 objects, so no GPU code runs here.
"""

from __future__ import annotations

import copy
import ctypes
import importlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import release_smoke as smoke


def module() -> Any:
    path = Path(__file__).resolve().parents[2] / "scripts" / "gpu_frozen_smoke.py"
    spec = importlib.util.spec_from_file_location("recoryn_gpu_frozen_smoke_test", path)
    assert spec is not None and spec.loader is not None
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


RUNTIME_FILES = (
    "ctranslate2/_ext.cp313-win_amd64.pyd",
    "ctranslate2/ctranslate2.dll",
    "ctranslate2/libiomp5md.dll",
    "nvidia/cublas/bin/cublas64_12.dll",
    "nvidia/cublas/bin/cublasLt64_12.dll",
)


def folders(tmp_path: Path) -> tuple[Path, Path]:
    return tmp_path / "gpu-runtime" / "ct2-cuda-4-9-0", tmp_path / "Recoryn" / "_internal"


def run(compute: str) -> dict[str, Any]:
    return {"device": "cuda", "device_index": [0], "compute_type": compute}


def report_for(active: Path, bundle: Path) -> dict[str, Any]:
    return {
        "activate": None,
        "frozen": True,
        "bundle": str(bundle),
        "exitcode": 0,
        "module": str(active / "ctranslate2" / "__init__.py"),
        "ext": str(active / "ctranslate2" / "_ext.cp313-win_amd64.pyd"),
        "version": "4.9.0",
        "cuda_devices": 1,
        "faster_whisper_uses_runtime": True,
        "runs": {"float16": run("float16"), "float32": run("float32")},
        "tokens": {"float16": [[1, 2, 7], [1, 3, 8]], "float32": [[1, 2, 7], [1, 3, 8]]},
        "loaded": [
            str(bundle.parent / "Recoryn-CLI.exe"),
            r"C:\Windows\System32\nvcuda.dll",
            str(bundle / "python313.dll"),
            str(bundle / "vcomp140.dll"),
            *(str(active / name) for name in RUNTIME_FILES),
        ],
    }


def good(tmp_path: Path) -> dict[str, Any]:
    return report_for(*folders(tmp_path))


def test_a_complete_frozen_gpu_report_passes(tmp_path: Path) -> None:
    active, _ = folders(tmp_path)
    assert module().verdict(good(tmp_path), active, []) == []


def test_paths_compare_case_insensitively_like_windows(tmp_path: Path) -> None:
    active, _ = folders(tmp_path)
    report = good(tmp_path)
    report["loaded"] = [path.upper() for path in report["loaded"]]
    report["module"] = report["module"].upper()
    assert module().verdict(report, active, []) == []


def _short(path: Path) -> str:
    buffer = ctypes.create_unicode_buffer(32_768)
    length = ctypes.windll.kernel32.GetShortPathNameW(str(path), buffer, len(buffer))
    return buffer.value if 0 < length < len(buffer) else str(path)


@pytest.mark.parametrize("short_side", ["active", "report"])
def test_an_8dot3_alias_of_the_same_runtime_folder_gives_the_same_verdict(
    tmp_path: Path, short_side: str
) -> None:
    active = tmp_path / "gpu-runtime-with-a-long-folder-name" / "ct2-cuda-4-9-0"
    bundle = tmp_path / "Recoryn" / "_internal"
    for name in (*RUNTIME_FILES, "ctranslate2/__init__.py"):
        (active / name).parent.mkdir(parents=True, exist_ok=True)
        (active / name).write_bytes(b"")
    alias = Path(_short(active))
    if str(alias) == str(active):
        pytest.skip("this volume does not create 8.3 names")
    assert alias.samefile(active)
    if short_side == "active":
        verdict = module().verdict(report_for(active, bundle), alias, [])
    else:
        verdict = module().verdict(report_for(alias, bundle), active, [])
    assert verdict == []


def _set(key: str, value: Any) -> Any:
    def change(report: dict[str, Any], active: Path, bundle: Path) -> None:
        report[key] = value

    return change


def _run(compute: str, **changes: Any) -> Any:
    def change(report: dict[str, Any], active: Path, bundle: Path) -> None:
        report["runs"][compute].update(changes)

    return change


def _loaded(edit: Any) -> Any:
    def change(report: dict[str, Any], active: Path, bundle: Path) -> None:
        report["loaded"] = edit(report["loaded"], active, bundle)

    return change


def _sibling(report: dict[str, Any], active: Path, bundle: Path) -> None:
    # A folder whose name only starts with the runtime folder's name is outside it.
    report["module"] = str(active.parent / (active.name + "-evil") / "ctranslate2" / "__init__.py")


def _both(value: Any) -> Any:
    return _set("tokens", {"float16": copy.deepcopy(value), "float32": copy.deepcopy(value)})


# One fault per row; the expected code is the only failure (hand-written oracle).
FAULTS = [
    ("activation", _set("activate", "GPU_RUNTIME_NOT_INSTALLED"), "ACTIVATION_FAILED"),
    ("source run", _set("frozen", False), "NOT_FROZEN"),
    ("empty bundle", _set("bundle", ""), "NOT_FROZEN"),
    ("child exit", _set("exitcode", 1), "CHILD_EXIT_NONZERO"),
    ("no exit code", lambda r, a, b: r.pop("exitcode"), "CHILD_EXIT_NONZERO"),
    ("exit code false", _set("exitcode", False), "CHILD_EXIT_NONZERO"),
    ("exit code float", _set("exitcode", 0.0), "CHILD_EXIT_NONZERO"),
    (
        "module bundled",
        lambda r, a, b: r.update(module=str(b / "ctranslate2" / "__init__.py")),
        "MODULE_NOT_RUNTIME_FILE",
    ),
    ("module sibling", _sibling, "MODULE_NOT_RUNTIME_FILE"),
    (
        "module elsewhere in runtime",
        lambda r, a, b: r.update(module=str(a / "other" / "__init__.py")),
        "MODULE_NOT_RUNTIME_FILE",
    ),
    (
        "ext bundled",
        lambda r, a, b: r.update(ext=str(b / "ctranslate2" / "_ext.pyd")),
        "EXT_NOT_RUNTIME_FILE",
    ),
    (
        "ext elsewhere in runtime",
        lambda r, a, b: r.update(ext=str(a / "other" / "unrelated.pyd")),
        "EXT_NOT_RUNTIME_FILE",
    ),
    ("cpu build version", _set("version", "4.9.0+recoryn.cpu1"), "VERSION_MISMATCH"),
    (
        "faster-whisper other",
        _set("faster_whisper_uses_runtime", False),
        "FASTER_WHISPER_OTHER_MODULE",
    ),
    ("float16 ran on cpu", _run("float16", device="cpu"), "RUN_NOT_ON_CUDA"),
    ("float32 ran on cpu", _run("float32", device="cpu"), "RUN_NOT_ON_CUDA"),
    (
        "float16 ran as float32",
        _run("float16", compute_type="float32"),
        "RUN_COMPUTE_TYPE_MISMATCH",
    ),
    ("float32 ran as int8", _run("float32", compute_type="int8"), "RUN_COMPUTE_TYPE_MISMATCH"),
    ("other gpu index", _run("float16", device_index=[1]), "RUN_DEVICE_INDEX_INVALID"),
    ("no gpu index", _run("float32", device_index=[]), "RUN_DEVICE_INDEX_INVALID"),
    ("bool gpu index", _run("float16", device_index=[False]), "RUN_DEVICE_INDEX_INVALID"),
    ("no device fact", lambda r, a, b: r["runs"]["float16"].pop("device"), "RUN_NOT_ON_CUDA"),
    ("one run", _set("runs", {"float32": run("float32")}), "RUNS_MALFORMED"),
    (
        "run not dict",
        _set("runs", {"float16": "cuda", "float32": run("float32")}),
        "RUNS_MALFORMED",
    ),
    (
        "tokens differ",
        _set("tokens", {"float16": [[1, 2], [1, 3]], "float32": [[1, 2], [1, 4]]}),
        "FLOAT16_FLOAT32_TOKENS_DIFFER",
    ),
    ("tokens empty", _both([]), "TOKENS_MALFORMED"),
    ("a sequence empty", _both([[1], []]), "TOKENS_MALFORMED"),
    ("one compute type", _set("tokens", {"float32": [[1, 2], [1, 3]]}), "TOKENS_MALFORMED"),
    ("token batch is text", _both("success"), "TOKENS_MALFORMED"),
    ("token batch flat", _both([1]), "TOKENS_MALFORMED"),
    ("one prompt only", _both([[1, 2]]), "TOKENS_MALFORMED"),
    ("three prompts", _both([[1], [2], [3]]), "TOKENS_MALFORMED"),
    ("bool tokens", _both([[False], [True]]), "TOKENS_MALFORMED"),
    ("none tokens", _both([[None], [None]]), "TOKENS_MALFORMED"),
    ("text tokens", _both([["pretend"], ["pretend"]]), "TOKENS_MALFORMED"),
    ("negative token", _both([[-1], [1]]), "TOKENS_MALFORMED"),
    (
        "runtime dll missing",
        _loaded(lambda paths, a, b: [p for p in paths if "cublasLt" not in p]),
        "RUNTIME_MODULE_SET_MISMATCH",
    ),
    (
        "extra runtime file",
        _loaded(lambda paths, a, b: [*paths, str(a / "ctranslate2" / "extra.dll")]),
        "RUNTIME_MODULE_SET_MISMATCH",
    ),
    (
        "bundled ct2 dll",
        _loaded(lambda paths, a, b: [*paths, str(b / "ctranslate2" / "ctranslate2.dll")]),
        "FOREIGN_RUNTIME_LOADED",
    ),
    (
        "bundled ct2 ext",
        _loaded(lambda paths, a, b: [*paths, str(b / "ctranslate2" / "_ext.cp313-win_amd64.pyd")]),
        "FOREIGN_RUNTIME_LOADED",
    ),
    (
        "system openmp",
        _loaded(lambda paths, a, b: [*paths, r"C:\Tools\libiomp5md.dll"]),
        "FOREIGN_RUNTIME_LOADED",
    ),
    (
        "outside cublas",
        _loaded(lambda paths, a, b: [*paths, r"C:\outside\cublas64_12.dll"]),
        "FOREIGN_RUNTIME_LOADED",
    ),
    (
        "outside cublasLt",
        _loaded(lambda paths, a, b: [*paths, r"C:\outside\cublasLt64_12.dll"]),
        "FOREIGN_RUNTIME_LOADED",
    ),
    (
        "other cublas version",
        _loaded(lambda paths, a, b: [*paths, r"C:\CUDA\v11\bin\cublas64_11.dll"]),
        "FOREIGN_RUNTIME_LOADED",
    ),
    (
        "sibling folder ct2 dll",
        _loaded(
            lambda paths, a, b: [
                *paths,
                str(a.parent / (a.name + "-evil") / "ctranslate2" / "ctranslate2.dll"),
            ]
        ),
        "FOREIGN_RUNTIME_LOADED",
    ),
]


@pytest.mark.parametrize(("case", "change", "code"), FAULTS, ids=[row[0] for row in FAULTS])
def test_each_single_fault_fails_with_its_own_code(
    tmp_path: Path, case: str, change: Any, code: str
) -> None:
    active, bundle = folders(tmp_path)
    report = good(tmp_path)
    change(report, active, bundle)
    assert module().verdict(report, active, []) == [code]


# Exact types; bool is not an int (hand-written).
TYPE_FAULTS = [
    ("activate", 5),
    ("frozen", 1),
    ("bundle", None),
    ("bundle", 42),
    ("module", None),
    ("ext", 5),
    ("version", 4.9),
    ("cuda_devices", True),
    ("cuda_devices", "1"),
    ("faster_whisper_uses_runtime", 1),
    ("runs", []),
    ("tokens", [[1, 2]]),
    ("loaded", None),
    ("loaded", ["C:/a.dll", 5]),
]


@pytest.mark.parametrize(("key", "value"), TYPE_FAULTS)
def test_a_fact_of_the_wrong_type_fails_before_any_other_check(
    tmp_path: Path, key: str, value: Any
) -> None:
    active, _ = folders(tmp_path)
    report = good(tmp_path)
    report[key] = value
    assert module().verdict(report, active, []) == ["BAD_TYPE_" + key.upper()]


def test_no_cuda_device_also_makes_every_device_index_invalid(tmp_path: Path) -> None:
    active, _ = folders(tmp_path)
    report = good(tmp_path)
    report["cuda_devices"] = 0
    failures = module().verdict(report, active, [])
    assert failures == ["NO_CUDA_DEVICE", "RUN_DEVICE_INDEX_INVALID"]


def test_cudnn_loaded_from_anywhere_fails(tmp_path: Path) -> None:
    active, _ = folders(tmp_path)
    report = good(tmp_path)
    report["loaded"].append(r"C:\Program Files\NVIDIA\CUDNN\bin\cudnn64_9.dll")
    assert module().verdict(report, active, []) == ["CUDNN_LOADED"]


def test_cudnn_inside_the_runtime_fails_both_checks(tmp_path: Path) -> None:
    active, _ = folders(tmp_path)
    report = good(tmp_path)
    report["loaded"].append(str(active / "ctranslate2" / "cudnn64_9.dll"))
    failures = module().verdict(report, active, [])
    assert failures == ["RUNTIME_MODULE_SET_MISMATCH", "CUDNN_LOADED"]


def test_a_pyc_written_into_the_runtime_fails(tmp_path: Path) -> None:
    active, _ = folders(tmp_path)
    pyc = [str(active / "ctranslate2" / "__pycache__" / "__init__.cpython-313.pyc")]
    assert module().verdict(good(tmp_path), active, pyc) == ["PYC_WRITTEN_IN_RUNTIME"]


def _resolved(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record every path handed to the OS final-path resolver (L08-06)."""
    import os

    seen: list[str] = []
    original = os.path.realpath

    def spy(path: Any, *args: Any, **kwargs: Any) -> Any:
        seen.append(str(path))
        return original(path, *args, **kwargs)

    monkeypatch.setattr(os.path, "realpath", spy)
    return seen


# Reported paths that are not on a local drive: never resolved, always refused.
NON_LOCAL = [
    ("unc cublas", "loaded", r"\\review.invalid\share\cublas64_12.dll", ["FOREIGN_RUNTIME_LOADED"]),
    ("unc other", "loaded", r"\\review.invalid\share\other.dll", []),
    ("extended unc", "loaded", r"\\?\UNC\review.invalid\share\other.dll", []),
    ("extended drive", "loaded", r"\\?\C:\Windows\other.dll", []),
    ("device namespace", "loaded", r"\\.\pipe\other", []),
    ("relative", "loaded", "other.dll", []),
    ("unc module", "module", r"\\review.invalid\share\ctranslate2\__init__.py", None),
]


@pytest.mark.parametrize(
    ("case", "key", "path", "extra"), NON_LOCAL, ids=[row[0] for row in NON_LOCAL]
)
def test_a_non_local_reported_path_is_refused_without_resolving_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    key: str,
    path: str,
    extra: list[str] | None,
) -> None:
    active, _ = folders(tmp_path)
    report = good(tmp_path)
    if key == "loaded":
        report["loaded"].append(path)
    else:
        report[key] = path
    verdict = module().verdict
    seen = _resolved(monkeypatch)
    failures = verdict(report, active, [])
    expected = ["NON_LOCAL_PATH_REPORTED"] + (
        ["MODULE_NOT_RUNTIME_FILE"] if extra is None else extra
    )
    assert failures == expected
    assert path not in seen
    assert all(p[1:3] == ":\\" or p[1:3] == ":/" for p in seen)


def test_a_mapped_network_drive_is_never_resolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    active, _ = folders(tmp_path)
    report = good(tmp_path)
    report["loaded"].append(r"Z:\share\other.dll")
    loaded = module()
    real = loaded._drive_type
    monkeypatch.setattr(loaded, "_drive_type", lambda root: 4 if root == "Z:\\" else real(root))
    seen = _resolved(monkeypatch)
    assert loaded.verdict(report, active, []) == ["NON_LOCAL_PATH_REPORTED"]
    assert not any(p.upper().startswith("Z:") for p in seen)


def test_local_drive_paths_are_still_resolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    active, _ = folders(tmp_path)
    verdict = module().verdict
    seen = _resolved(monkeypatch)
    assert verdict(good(tmp_path), active, []) == []
    assert str(active / "ctranslate2" / "__init__.py") in seen


REQUIRED_FACTS = (
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


def test_the_verdict_requires_exactly_the_hand_listed_facts() -> None:
    assert module().REQUIRED == REQUIRED_FACTS


@pytest.mark.parametrize("key", REQUIRED_FACTS)
def test_a_report_missing_a_required_fact_never_passes(tmp_path: Path, key: str) -> None:
    active, _ = folders(tmp_path)
    report = good(tmp_path)
    report.pop(key)
    assert module().verdict(report, active, []) == ["MISSING_" + key.upper()]


def test_the_child_failure_report_is_not_a_pass(tmp_path: Path) -> None:
    active, _ = folders(tmp_path)
    report = {"activate": "GPU_SMOKE_CHILD_FAILED", "exitcode": None}
    assert "MISSING_LOADED" in module().verdict(report, active, [])


def test_expected_runtime_modules_match_the_hand_list() -> None:
    expected = {name.lower() for name in RUNTIME_FILES}
    assert module().EXPECTED_RUNTIME_MODULES == expected


def test_foreign_names_cover_every_runtime_binary_name() -> None:
    names = {name.rsplit("/", 1)[-1].lower() for name in RUNTIME_FILES}
    assert module().FOREIGN_NAMES == names


@pytest.mark.parametrize("unresolved", [None, ""])
def test_one_unresolved_module_name_fails_the_whole_list(unresolved: str | None) -> None:
    names = {1: "C:/a.exe", 2: unresolved, 3: "C:/c.dll"}
    with pytest.raises(OSError, match="MODULE_NAME_UNRESOLVED"):
        smoke.module_paths([1, 2, 3], names.get)


def test_resolved_module_names_are_kept_in_order() -> None:
    names = {1: "C:/a.exe", 2: "C:/b.dll"}
    assert smoke.module_paths([1, 2], names.get) == ["C:/a.exe", "C:/b.dll"]


def test_loaded_modules_lists_this_process_extension_files() -> None:
    paths = {Path(path).resolve() for path in smoke.loaded_modules()}
    ctypes_ext = importlib.import_module("_ctypes").__file__
    assert ctypes_ext is not None and Path(ctypes_ext).resolve() in paths
    assert len(paths) > 5


class _Output:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def put(self, item: dict[str, Any]) -> None:
        self.items.append(item)


def _child_in_process(monkeypatch: pytest.MonkeyPatch, activate: str | None) -> None:
    # _block_network installs a permanent audit hook; keep it out of the test process.
    monkeypatch.setattr(smoke, "_block_network", lambda: None)
    inference = importlib.import_module("recoryn.app.inference")
    monkeypatch.setattr(inference, "_activate_gpu", lambda root: activate)


def test_an_unresolved_module_list_is_reported_not_hidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _child_in_process(monkeypatch, "GPU_RUNTIME_NOT_INSTALLED")

    def unresolved() -> list[str]:
        raise OSError("MODULE_NAME_UNRESOLVED")

    monkeypatch.setattr(smoke, "loaded_modules", unresolved)
    output = _Output()
    smoke._gpu_child(output, "R", "M")
    (report,) = output.items
    assert report["loaded"] is None and report["loaded_error"] == "MODULE_NAME_UNRESOLVED"


def test_the_probe_reports_what_the_model_runs_on_not_what_it_asked_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _child_in_process(monkeypatch, None)
    requested: list[tuple[str, str]] = []

    class Whisper:
        # Asked for CUDA, the model object says it fell back to CPU float32.
        def __init__(self, model: str, device: str, compute_type: str) -> None:
            requested.append((device, compute_type))
            self.device, self.device_index, self.compute_type = "cpu", [0], "float32"

        def generate(self, features: Any, prompts: list[list[int]], **options: Any) -> Any:
            return [SimpleNamespace(sequences_ids=[[*prompt, 50]]) for prompt in prompts]

    fake = SimpleNamespace(
        __file__="R/ctranslate2/__init__.py",
        __version__="4.9.0",
        get_cuda_device_count=lambda: 1,
        models=SimpleNamespace(Whisper=Whisper),
        StorageView=SimpleNamespace(from_array=lambda array: array),
    )
    monkeypatch.setitem(sys.modules, "ctranslate2", fake)
    monkeypatch.setitem(sys.modules, "ctranslate2._ext", SimpleNamespace(__file__="R/_ext.pyd"))
    monkeypatch.setitem(sys.modules, "faster_whisper.transcribe", SimpleNamespace(ctranslate2=fake))
    monkeypatch.setattr(smoke, "loaded_modules", lambda: [])
    output = _Output()
    smoke._gpu_child(output, "R", "M")
    (report,) = output.items
    assert requested == [("cuda", "float16"), ("cuda", "float32")]
    assert report["runs"] == {
        "float16": {"device": "cpu", "device_index": [0], "compute_type": "float32"},
        "float32": {"device": "cpu", "device_index": [0], "compute_type": "float32"},
    }
    assert report["tokens"]["float16"] == [[1, 2, 5, 9, 50], [1, 3, 5, 9, 50]]
    assert report["faster_whisper_uses_runtime"] is True


def test_the_probe_with_no_installed_runtime_reports_without_gpu_code(tmp_path: Path) -> None:
    report = smoke.gpu_probe(tmp_path / "absent", tmp_path / "no-model", timeout=120)
    expected = (
        "GPU_RUNTIME_NOT_INSTALLED"
        if sys.version_info[:2] == (3, 13)
        else "GPU_RUNTIME_UNSUPPORTED"
    )
    assert report["activate"] == expected
    assert report["frozen"] is False and report["bundle"] == ""
    assert report["exitcode"] == 0
    assert "module" not in report and "tokens" not in report and "runs" not in report
    assert not any("ctranslate2" in Path(path).name.lower() for path in report["loaded"])


def test_a_child_that_does_not_answer_in_time_is_reported_as_failed(tmp_path: Path) -> None:
    report = smoke.gpu_probe(tmp_path / "absent", tmp_path / "no-model", timeout=0.001)
    assert report["activate"] == "GPU_SMOKE_CHILD_FAILED"


@pytest.mark.parametrize(
    ("probe", "status"),
    [({"activate": None}, 0), ({"activate": "GPU_RUNTIME_UNAVAILABLE"}, 2), ({}, 2)],
)
def test_release_dispatch_prints_the_probe_and_maps_the_exit_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    probe: dict[str, Any],
    status: int,
) -> None:
    import recoryn_release

    seen: list[tuple[Path, Path]] = []

    def fake(runtime_root: Path, model: Path) -> dict[str, Any]:
        seen.append((runtime_root, model))
        return copy.deepcopy(probe)

    monkeypatch.setattr(smoke, "gpu_probe", fake)
    argv = ["Recoryn-CLI.exe", "--release-gpu-smoke", "--runtime-root", "R", "--model", "M"]
    monkeypatch.setattr(sys, "argv", argv)
    assert recoryn_release.main(gui=False) == status
    assert seen == [(Path("R"), Path("M"))]
    assert json.loads(capsys.readouterr().out) == probe


def test_release_dispatch_requires_both_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    import recoryn_release

    monkeypatch.setattr(sys, "argv", ["Recoryn-CLI.exe", "--release-gpu-smoke", "--model", "M"])
    with pytest.raises(SystemExit) as raised:
        recoryn_release.main(gui=False)
    assert raised.value.code == 2
