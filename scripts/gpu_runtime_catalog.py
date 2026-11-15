"""Derive (or check) the GPU runtime member catalog from the two pinned wheels (L01 D10).

Usage: python scripts/gpu_runtime_catalog.py <folder with both wheels> [--check]

The wheels must match the pinned size and SHA-256 in ``recoryn.models.gpu_runtime``.
Prints the size and SHA-256 of every member Recoryn extracts; with ``--check`` it
compares them with the catalog in the source and exits 1 on any difference. It also
checks that the pinned ``ctranslate2/__init__.py`` holds the Windows DLL block that
activation replaces exactly once, and prints that block's SHA-256.
"""

from __future__ import annotations

import hashlib
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from recoryn.models import gpu_runtime as gpu  # noqa: E402

MEMBERS = {
    gpu.CT2_WHEEL.path: (
        "ctranslate2/__init__.py",
        "ctranslate2/_ext.cp313-win_amd64.pyd",
        "ctranslate2/ctranslate2.dll",
        "ctranslate2/extensions.py",
        "ctranslate2/libiomp5md.dll",
        "ctranslate2/logging.py",
        "ctranslate2/models/__init__.py",
        "ctranslate2/version.py",
    ),
    gpu.CUBLAS_WHEEL.path: (
        "nvidia/cublas/bin/cublas64_12.dll",
        "nvidia/cublas/bin/cublasLt64_12.dll",
        "nvidia_cublas_cu12-12.8.4.1.dist-info/License.txt",
    ),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    folder = Path(sys.argv[1])
    check = "--check" in sys.argv[2:]
    found: dict[str, tuple[gpu.Member, ...]] = {}
    for item in gpu.SPEC.files:
        path = folder / item.path
        if path.stat().st_size != item.size or sha256(path) != item.sha256:
            print("WHEEL_PIN_MISMATCH", item.path)
            return 1
        with zipfile.ZipFile(path) as archive:
            rows = []
            for name in MEMBERS[item.path]:
                data = archive.read(name)
                rows.append(gpu.Member(name, len(data), hashlib.sha256(data).hexdigest()))
                if name == gpu.INIT_MEMBER:
                    start, end, _ = gpu.INIT_BLOCK
                    if data.count(start) != 1 or data.count(end) != 1:
                        print("INIT_BLOCK_NOT_UNIQUE")
                        return 1
                    first = data.index(start)
                    last = data.index(end) + len(end)
                    print("INIT_BLOCK", hashlib.sha256(data[first:last]).hexdigest())
            found[item.path] = tuple(rows)
    for wheel, listed in found.items():
        print(wheel)
        for row in listed:
            print(f'    Member("{row.path}", {row.size:_}, "{row.sha256}"),')
    if check and found != gpu.CATALOG:
        print("CATALOG_MISMATCH")
        return 1
    print("CATALOG_MATCH" if found == gpu.CATALOG else "CATALOG_DIFFERS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
