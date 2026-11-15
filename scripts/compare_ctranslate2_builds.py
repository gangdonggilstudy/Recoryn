"""Compare two CTranslate2 builds on a small random-weight Whisper model (L01 D9).

No model weights are downloaded: a 2+2 layer Whisper spec is filled with seeded random
values, saved, and run through encode() and greedy generate() for float32 and int8.
Run once per environment (e.g. the PyPI wheel and the CPU-only build) with
``--out <file>.json``; then ``--compare a.json b.json`` reports differences and timing.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import time
from pathlib import Path
from typing import Any

D, HEADS, LAYERS, MELS, FFN, VOCAB = 64, 4, 2, 80, 256, 64
# Recoryn runs faster-whisper with "int8" on CPU (FasterWhisperProvider); float32 is the
# reference precision.
COMPUTE_TYPES = ("float32", "int8")
SPECIAL = [
    "<|endoftext|>",
    "<|startoftranscript|>",
    "<|en|>",
    "<|ko|>",
    "<|translate|>",
    "<|transcribe|>",
    "<|startoflm|>",
    "<|startofprev|>",
    "<|nocaptions|>",
    "<|notimestamps|>",
]


def _shape(path: str) -> tuple[int, ...] | None:
    tail = path.rsplit("/", 2)
    leaf, owner = tail[-1], "/".join(tail[-3:-1])
    if leaf in ("gamma", "beta"):
        return (D,)
    if "conv1" in owner:
        return {"weight": (D, MELS, 3), "bias": (D,)}.get(leaf)
    if "conv2" in owner:
        return {"weight": (D, D, 3), "bias": (D,)}.get(leaf)
    if leaf == "encodings":
        return (1500, D) if path.startswith("encoder") else (448, D)
    if "embeddings" in owner and leaf == "weight":
        return (VOCAB, D)
    if owner.endswith("projection") and leaf == "weight":
        return (VOCAB, D)
    sizes = {
        "self_attention/linear_0": 3 * D,
        "self_attention/linear_1": D,
        "attention/linear_0": D,
        "attention/linear_1": 2 * D,
        "attention/linear_2": D,
        "ffn/linear_0": FFN,
        "ffn/linear_1": D,
    }
    for suffix, rows in sizes.items():
        if owner.endswith(suffix):
            cols = FFN if suffix == "ffn/linear_1" else D
            return (rows, cols) if leaf == "weight" else (rows,) if leaf == "bias" else None
    return None


def build_model(directory: Path, seed: int = 20261115) -> None:
    import numpy as np

    specs: Any = importlib.import_module("ctranslate2.specs")

    rng = np.random.default_rng(seed)
    spec = specs.WhisperSpec(LAYERS, HEADS, LAYERS, HEADS)

    def fill(layer: Any, scope: str) -> None:
        for name, value in list(vars(layer).items()):
            if name.startswith("_"):
                continue
            path = f"{scope}/{name}" if scope else name
            if isinstance(value, specs.model_spec.LayerSpec):
                fill(value, path)
            elif (
                isinstance(value, list)
                and value
                and isinstance(value[0], specs.model_spec.LayerSpec)
            ):
                for index, item in enumerate(value):
                    fill(item, f"{path}_{index}")
            elif value is None or isinstance(value, str):
                shape = _shape(path)
                if shape is not None:
                    data = rng.standard_normal(shape).astype(np.float32) * 0.08
                    if name == "gamma":
                        data = data + 1.0
                    setattr(layer, name, data)

    fill(spec, "")
    tokens = SPECIAL + [f"tok{index}" for index in range(VOCAB - len(SPECIAL))]
    spec.register_vocabulary(tokens)
    spec.config.suppress_ids = []
    spec.config.suppress_ids_begin = []
    spec.config.lang_ids = [2, 3]
    spec.config.alignment_heads = [(0, 0)]
    spec.validate()
    directory.mkdir(parents=True, exist_ok=True)
    spec.save(str(directory))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def identity(directory: Path, features: Any, prompt: list[list[int]]) -> dict[str, Any]:
    """What both runs must share for a comparison to mean anything (L06-I01)."""
    return {
        "dims": {"d_model": D, "heads": HEADS, "layers": LAYERS, "ffn": FFN, "vocab": VOCAB},
        "model_files": {
            name: _sha256((directory / name).read_bytes())
            for name in ("model.bin", "config.json", "vocabulary.json")
        },
        "features": {"shape": list(features.shape), "sha256": _sha256(features.tobytes())},
        "prompt": prompt,
    }


def run(directory: Path, threads: int, arrays: Path) -> dict[str, Any]:
    ctranslate2: Any = importlib.import_module("ctranslate2")
    import numpy as np

    rng = np.random.default_rng(7)
    features = rng.standard_normal((2, MELS, 3000)).astype(np.float32)
    prompt = [[1, 2, 5, 9], [1, 3, 5, 9]]  # sot, language, transcribe, notimestamps
    result: dict[str, Any] = {
        "version": ctranslate2.__version__,
        "compute_types": sorted(ctranslate2.get_supported_compute_types("cpu")),
        "identity": identity(directory, features, prompt),
        "threads": threads,
    }
    full: dict[str, Any] = {}
    for compute in COMPUTE_TYPES:
        model = ctranslate2.models.Whisper(
            str(directory), device="cpu", compute_type=compute, intra_threads=threads
        )
        storage = ctranslate2.StorageView.from_array(features)
        start = time.perf_counter()
        encoded = np.array(model.encode(storage, to_cpu=True))
        encode_s = time.perf_counter() - start
        start = time.perf_counter()
        generated = model.generate(
            storage,
            prompt,
            beam_size=1,
            max_length=24,
            return_scores=True,
            suppress_blank=False,
            suppress_tokens=[],
        )
        generate_s = time.perf_counter() - start
        timings = []
        for _ in range(3):
            start = time.perf_counter()
            model.encode(storage, to_cpu=True)
            timings.append(time.perf_counter() - start)
        full[compute] = encoded
        result[compute] = {
            "encoded_shape": list(encoded.shape),
            "encoded_finite": bool(np.isfinite(encoded).all()),
            "sequences": [item.sequences_ids[0] for item in generated],
            "scores": [float(item.scores[0]) for item in generated],
            "first_encode_s": encode_s,
            "generate_s": generate_s,
            "encode_repeat_s": timings,
        }
    np.savez(arrays, **full)
    result["arrays"] = {"file": arrays.name, "sha256": _sha256(arrays.read_bytes())}
    return result


def compare(left_path: Path, right_path: Path) -> dict[str, Any]:
    """Full-array comparison; refuses results that are not of the same model and input."""
    import numpy as np

    left, right = (json.loads(path.read_text(encoding="utf-8")) for path in (left_path, right_path))
    if left.get("identity") is None or left.get("identity") != right.get("identity"):
        raise SystemExit("COMPARE_IDENTITY_MISMATCH")
    dims = left["identity"]["dims"]
    expected_shape = [left["identity"]["features"]["shape"][0], 1500, dims["d_model"]]
    loaded = []
    for path, result in ((left_path, left), (right_path, right)):
        arrays = path.parent / result["arrays"]["file"]
        if _sha256(arrays.read_bytes()) != result["arrays"]["sha256"]:
            raise SystemExit("COMPARE_ARRAYS_HASH_MISMATCH")
        loaded.append(np.load(arrays))
    report: dict[str, Any] = {
        "left": left["version"],
        "right": right["version"],
        "identity": left["identity"],
        "compared": "full encoder output arrays (every element), generated tokens and scores",
    }
    for compute in COMPUTE_TYPES:
        a, b = left[compute], right[compute]
        ea, eb = loaded[0][compute], loaded[1][compute]
        for result, array in ((a, ea), (b, eb)):
            if (
                list(array.shape) != expected_shape
                or result["encoded_shape"] != expected_shape
                or not result["encoded_finite"]
                or not np.isfinite(array).all()
            ):
                raise SystemExit(f"COMPARE_SHAPE_OR_FINITE_INVALID {compute}")
        difference = np.abs(ea.astype(np.float64) - eb.astype(np.float64))
        report[compute] = {
            "elements": int(ea.size),
            "encoded_max_abs_diff": float(difference.max()),
            "encoded_mean_abs_diff": float(difference.mean()),
            "encoded_max_abs": float(np.abs(ea).max()),
            "same_tokens": a["sequences"] == b["sequences"],
            "first_token_divergence": [
                next((i for i, (x, y) in enumerate(zip(s, t, strict=False)) if x != y), None)
                for s, t in zip(a["sequences"], b["sequences"], strict=True)
            ],
            "score_diffs": [abs(x - y) for x, y in zip(a["scores"], b["scores"], strict=True)],
            "encode_median_s": [sorted(a["encode_repeat_s"])[1], sorted(b["encode_repeat_s"])[1]],
        }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--compare", nargs=2, type=Path)
    parser.add_argument(
        "--size",
        choices=("small", "base"),
        default="small",
        help="small: d_model 64, 2 layers; base: d_model 512, 8 heads, 6 layers (Whisper base-like)",
    )
    options = parser.parse_args()
    global D, HEADS, LAYERS, FFN
    if options.size == "base":
        D, HEADS, LAYERS, FFN = 512, 8, 6, 2048
    if options.compare:
        print(json.dumps(compare(*options.compare), indent=2))
        return 0
    if not (options.model / "model.bin").exists():
        build_model(options.model)
    result = run(options.model, options.threads, options.out.with_suffix(".npz"))
    options.out.write_text(json.dumps(result), encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("version", "compute_types", "arrays")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
