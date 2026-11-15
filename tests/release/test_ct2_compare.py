"""The CTranslate2 build comparison refuses results it cannot compare (L06-I01).

Case space: docs/testing/l06-ctranslate2-cpu-cases.md (E). Results are synthetic; no
CTranslate2 runs here.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest


def module() -> Any:
    path = Path(__file__).resolve().parents[2] / "scripts" / "compare_ctranslate2_builds.py"
    spec = importlib.util.spec_from_file_location("recoryn_ct2_compare_test", path)
    assert spec is not None and spec.loader is not None
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


IDENTITY = {
    "dims": {"d_model": 4, "heads": 1, "layers": 1, "ffn": 8, "vocab": 64},
    "model_files": {"model.bin": "a" * 64, "config.json": "b" * 64, "vocabulary.json": "c" * 64},
    "features": {"shape": [2, 80, 3000], "sha256": "d" * 64},
    "prompt": [[1, 2, 5, 9], [1, 3, 5, 9]],
}


def write(folder: Path, name: str, offset: float = 0.0, **change: Any) -> Path:
    arrays = {
        compute: np.full((2, 1500, 4), 0.5 + offset, dtype=np.float32)
        for compute in ("float32", "int8")
    }
    arrays.update(change.pop("arrays", {}))
    npz = folder / f"{name}.npz"
    np.savez(npz, **arrays)
    result: dict[str, Any] = {
        "version": name,
        "identity": change.pop("identity", IDENTITY),
        "arrays": {"file": npz.name, "sha256": hashlib.sha256(npz.read_bytes()).hexdigest()},
    }
    for compute, array in arrays.items():
        result[compute] = {
            "encoded_shape": list(array.shape),
            "encoded_finite": bool(np.isfinite(array).all()),
            "sequences": [[1, 2, 3], [1, 2, 4]],
            "scores": [-1.0, -2.0],
            "encode_repeat_s": [0.1, 0.1, 0.1],
        }
        result[compute].update(change.get(compute, {}))
    path = folder / f"{name}.json"
    path.write_text(json.dumps(result), encoding="utf-8")
    return path


def test_full_arrays_are_compared(tmp_path: Path) -> None:
    left = write(tmp_path, "left")
    right = write(tmp_path, "right", offset=0.25)
    report = module().compare(left, right)
    for compute in ("float32", "int8"):
        assert report[compute]["elements"] == 2 * 1500 * 4
        assert report[compute]["encoded_max_abs_diff"] == pytest.approx(0.25)
        assert report[compute]["same_tokens"] is True


def test_identity_mismatch_is_refused(tmp_path: Path) -> None:
    other = json.loads(json.dumps(IDENTITY))
    other["model_files"]["model.bin"] = "e" * 64  # another model
    left, right = write(tmp_path, "left"), write(tmp_path, "right", identity=other)
    with pytest.raises(SystemExit, match="COMPARE_IDENTITY_MISMATCH"):
        module().compare(left, right)


def test_original_counterexample_shape_is_refused(tmp_path: Path) -> None:
    # L06-I01: a result claiming encoded_shape [1, 1, 1] used to compare as "diff 0".
    left = write(tmp_path, "left")
    right = write(tmp_path, "right", float32={"encoded_shape": [1, 1, 1]})
    with pytest.raises(SystemExit, match="COMPARE_SHAPE_OR_FINITE_INVALID"):
        module().compare(left, right)


def test_non_finite_output_is_refused(tmp_path: Path) -> None:
    broken = np.full((2, 1500, 4), 0.5, dtype=np.float32)
    broken[0, 0, 0] = np.nan
    left = write(tmp_path, "left")
    right = write(tmp_path, "right", arrays={"int8": broken})
    with pytest.raises(SystemExit, match="COMPARE_SHAPE_OR_FINITE_INVALID"):
        module().compare(left, right)


def test_tampered_arrays_are_refused(tmp_path: Path) -> None:
    left, right = write(tmp_path, "left"), write(tmp_path, "right")
    np.savez(tmp_path / "right.npz", float32=np.zeros((2, 1500, 4), np.float32))
    with pytest.raises(SystemExit, match="COMPARE_ARRAYS_HASH_MISMATCH"):
        module().compare(left, right)
