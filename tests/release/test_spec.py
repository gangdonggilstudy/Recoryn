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
