"""Run the actual spec with fake analysis results; hooks must not sneak in weights."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest


@pytest.mark.parametrize("weight", ["silero_vad.onnx", "model.bin", "encoder.safetensors", None])
def test_spec_rejects_hook_added_weights_before_executable_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, weight: str | None
) -> None:
    hooks = ModuleType("PyInstaller.utils.hooks")
    for name in ("collect_data_files", "collect_dynamic_libs", "collect_submodules"):
        monkeypatch.setattr(hooks, name, lambda package: [], raising=False)
    monkeypatch.setitem(sys.modules, "PyInstaller.utils.hooks", hooks)
    monkeypatch.setenv("RECORYN_BUILD_EVIDENCE", str(tmp_path / "analysis.json"))
    calls = []

    def analysis(*args: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(
            pure=[],
            binaries=[],
            scripts=[],
            datas=[(weight, "synthetic-weight", "DATA")] if weight else [],
        )

    def executable(*args: Any, **kwargs: Any) -> str:
        assert kwargs["exclude_binaries"] is True and kwargs["upx"] is False
        calls.append(kwargs["name"])
        return kwargs["name"]  # type: ignore[no-any-return]

    package = Path(__file__).resolve().parents[2] / "packaging"
    environment = {
        "SPECPATH": str(package),
        "Analysis": analysis,
        "PYZ": lambda value: "archive",
        "EXE": executable,
        "COLLECT": lambda *args, **kwargs: "onedir",
    }
    if weight:
        with pytest.raises(ValueError, match="BUNDLED_MODEL_WEIGHTS_FORBIDDEN"):
            runpy.run_path(str(package / "recoryn.spec"), init_globals=environment)
        assert calls == [] and not (tmp_path / "analysis.json").exists()
    else:
        runpy.run_path(str(package / "recoryn.spec"), init_globals=environment)
        assert calls == ["Recoryn", "Recoryn-CLI"]
        assert (tmp_path / "analysis.json").is_file()


def _run_spec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rows: list[tuple[str, str, str]]
) -> dict[str, Any]:
    hooks = ModuleType("PyInstaller.utils.hooks")
    for name in ("collect_data_files", "collect_dynamic_libs", "collect_submodules"):
        monkeypatch.setattr(hooks, name, lambda package: [], raising=False)
    monkeypatch.setitem(sys.modules, "PyInstaller.utils.hooks", hooks)
    monkeypatch.setenv("RECORYN_BUILD_EVIDENCE", str(tmp_path / "analysis.json"))
    seen: dict[str, Any] = {}

    def analysis(*args: Any, **kwargs: Any) -> Any:
        seen["analysis"] = kwargs
        return SimpleNamespace(
            pure=[],
            scripts=[],
            binaries=[row for row in rows if row[2] == "BINARY"],
            datas=[row for row in rows if row[2] == "DATA"],
        )

    def collect(*args: Any, **kwargs: Any) -> str:
        seen["collected"] = [row for group in args[2:] for row in group]
        return "onedir"

    package = Path(__file__).resolve().parents[2] / "packaging"
    runpy.run_path(
        str(package / "recoryn.spec"),
        init_globals={
            "SPECPATH": str(package),
            "Analysis": analysis,
            "PYZ": lambda value: "archive",
            "EXE": lambda *args, **kwargs: kwargs["name"],
            "COLLECT": collect,
        },
    )
    return seen


def test_spec_drops_license_excluded_components_and_keeps_required_ones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # PyInstaller dest names use Windows separators; keep them as raw strings.
    excluded = [
        (r"av.libs\libx264-165.dll", "x264.dll", "BINARY"),
        (r"av\audio\frame.pyd", "frame.pyd", "BINARY"),
        (r"PySide6\Qt6VirtualKeyboard.dll", "vk.dll", "BINARY"),
        (r"PySide6\plugins\platforminputcontexts\qtvirtualkeyboardplugin.dll", "p.dll", "BINARY"),
        (r"PySide6\Qt6Quick.dll", "q.dll", "BINARY"),
        (r"PySide6\plugins\imageformats\qpdf.dll", "pdf.dll", "BINARY"),
        (r"ctranslate2\cudnn64_9.dll", "cudnn.dll", "BINARY"),
        (r"av-16.1.0.dist-info\METADATA", "METADATA", "DATA"),
        # L02-P03: a hook flattened a forbidden source to an innocent destination.
        (
            r"vendor\avcodec-62.dll",
            r"C:\venv\Lib\site-packages\av.libs\avcodec-62-0796e49249259295.dll",
            "BINARY",
        ),
        (r"codecs\h264.dll", r"C:\venv\Lib\site-packages\x\libopenh264-7.dll", "BINARY"),
        (r"tools\helper.dll", r"C:\elsewhere\bin\libx265-199.dll", "BINARY"),
    ]
    kept = [
        (r"PySide6\Qt6Multimedia.dll", "m.dll", "BINARY"),
        (r"PySide6\avcodec-63.dll", "qt-ffmpeg.dll", "BINARY"),
        (r"ctranslate2\libiomp5md.dll", "omp.dll", "BINARY"),
        (r"faster_whisper\assets\README", "readme", "DATA"),
        # Qt's own FFmpeg stays; a profile directory named "av" must not matter.
        (
            r"PySide6\avcodec-63.dll",
            r"C:\venv\Lib\site-packages\PySide6\avcodec-63.dll",
            "BINARY",
        ),
        (r"numpy\_core\x.pyd", r"C:\Users\av\venv\Lib\site-packages\numpy\_core\x.pyd", "BINARY"),
    ]
    seen = _run_spec(tmp_path, monkeypatch, excluded + kept)
    assert sorted(seen["collected"]) == sorted(kept + kept)  # GUI and CLI analyses
    assert "av" in seen["analysis"]["excludes"]
    hooks = [Path(path).name for path in seen["analysis"]["runtime_hooks"]]
    assert hooks == ["rthook_no_av.py"]


def test_runtime_hook_satisfies_import_but_refuses_any_pyav_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delitem(sys.modules, "av", raising=False)
    hook = Path(__file__).resolve().parents[2] / "packaging" / "rthook_no_av.py"
    runpy.run_path(str(hook))
    import av  # type: ignore[import-not-found,unused-ignore]

    assert av.__recoryn_stub__ is True
    with pytest.raises(AttributeError, match="RECORYN_PYAV_NOT_BUNDLED"):
        av.open  # noqa: B018
    with pytest.raises(ImportError):
        from av import audio  # type: ignore[import-not-found,unused-ignore]  # noqa: F401
    assert getattr(av, "__path__", None) is None


def test_runtime_hook_never_replaces_an_already_imported_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing = ModuleType("av")
    monkeypatch.setitem(sys.modules, "av", existing)
    runpy.run_path(str(Path(__file__).resolve().parents[2] / "packaging" / "rthook_no_av.py"))
    assert sys.modules["av"] is existing
