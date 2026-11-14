"""사용자 범위 version-directory 설치. 원본·설정·키 저장소에는 접근하지 않는다."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

APP_ID = "org.recoryn.desktop"
MANIFEST = "release-manifest.json"
# Candidate policy for known model/object serialization suffixes. It does not
# classify arbitrary renamed bytes. Native runtimes (.dll/.pyd/.exe) are allowed.
WEIGHTS = {
    ".onnx",
    ".ort",
    ".bin",
    ".safetensors",
    ".pt",
    ".pth",
    ".pt2",
    ".gguf",
    ".ckpt",
    ".tflite",
    ".pkl",
    ".pickle",
    ".joblib",
    ".h5",
    ".hdf5",
    ".pb",
    ".npy",
    ".npz",
    ".caffemodel",
    ".mlmodel",
    ".weights",
}


class ReleaseError(ValueError):
    """표시 가능한 안정 오류 코드만 전달한다."""


def safe(path: Path) -> Path:
    if str(path).startswith(("\\\\", "//")):
        raise ReleaseError("NETWORK_PATH_FORBIDDEN")
    if ".." in path.parts:
        raise ReleaseError("PARENT_PATH_FORBIDDEN")
    path = path.absolute()
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ReleaseError("REPARSE_PATH_FORBIDDEN")
        if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            raise ReleaseError("HARDLINK_PATH_FORBIDDEN")
    return path


def digest(path: Path) -> str:
    with safe(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def files(root: Path) -> list[Path]:
    safe(root)
    result: list[Path] = []
    for path in root.rglob("*"):
        safe(path)
        if len(result) >= 100_000 or len(path.relative_to(root).parts) > 64:
            raise ReleaseError("INVENTORY_LIMIT_EXCEEDED")
        if path.is_file():
            result.append(path)
        elif not path.is_dir():
            raise ReleaseError("SPECIAL_FILE_FORBIDDEN")
    return sorted(result)


def read_json(path: Path) -> dict[str, Any]:
    path = safe(path)
    if path.stat().st_size > 32 * 1024 * 1024:
        raise ReleaseError("METADATA_TOO_LARGE")

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ReleaseError("DUPLICATE_METADATA_KEY")
            result[key] = item
        return result

    def nonfinite(value: str) -> None:
        raise ReleaseError("NONFINITE_METADATA")

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=unique, parse_constant=nonfinite
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ReleaseError("INVALID_METADATA") from exc
    if not isinstance(value, dict):
        raise ReleaseError("INVALID_METADATA")
    return value


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    safe(path)
    temporary = path.with_name(path.name + ".tmp-" + uuid4().hex)
    with temporary.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def inventory(root: Path) -> list[dict[str, Any]]:
    return [
        {"path": p.relative_to(root).as_posix(), "size": p.stat().st_size, "sha256": digest(p)}
        for p in files(root)
        if p.relative_to(root).as_posix() != MANIFEST
    ]


def verify(root: Path, *, allow_missing: bool = False) -> dict[str, Any]:
    root = safe(root)
    manifest = read_json(root / MANIFEST)
    if (
        manifest.get("app_id") != APP_ID
        or type(manifest.get("schema_version")) is not int
        or manifest["schema_version"] != 1
    ):
        raise ReleaseError("INVALID_RELEASE_IDENTITY")
    version = manifest.get("version")
    if (
        not isinstance(version, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}", version) is None
    ):
        raise ReleaseError("INVALID_RELEASE_VERSION")
    records = manifest.get("files")
    if not isinstance(records, list) or not records:
        raise ReleaseError("INVALID_INVENTORY")
    keys = set()
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            raise ReleaseError("INVALID_INVENTORY")
        name = record["path"]
        parts = PurePosixPath(name).parts
        if (
            not parts
            or "/".join(parts) != name
            or any(
                part in (".", "..")
                or re.search(r'[\\<>:"|?*\x00-\x1f]', part)
                or part.endswith((".", " "))
                or re.fullmatch(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", part, re.I)
                for part in parts
            )
            or name.startswith("/")
            or name.casefold() in keys
            or name.casefold() == MANIFEST.casefold()
        ):
            raise ReleaseError("INVALID_INVENTORY_PATH")
        keys.add(name.casefold())
        if type(record.get("size")) is not int or record["size"] < 0:
            raise ReleaseError("INVALID_INVENTORY_SIZE")
        if (
            not isinstance(record.get("sha256"), str)
            or re.fullmatch("[0-9a-f]{64}", record["sha256"]) is None
        ):
            raise ReleaseError("INVALID_INVENTORY_HASH")
    actual = inventory(root)
    expected = {record["path"]: record for record in records}
    if (
        actual != [expected.get(record["path"]) for record in actual]
        if allow_missing
        else records != actual
    ):
        raise ReleaseError("RELEASE_INTEGRITY_MISMATCH")
    if any(Path(record["path"]).suffix.lower() in WEIGHTS for record in records):
        raise ReleaseError("BUNDLED_MODEL_WEIGHTS_FORBIDDEN")
    if not {"Recoryn.exe", "Recoryn-CLI.exe"}.issubset({record["path"] for record in records}):
        raise ReleaseError("RELEASE_ENTRY_MISSING")
    return manifest


def default_root() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        raise ReleaseError("USER_INSTALL_ROOT_UNAVAILABLE")
    return safe(Path(base) / "Programs" / "Recoryn")


@contextmanager
def installation(root: Path, *, create: bool = False) -> Iterator[None]:
    root = safe(root)
    marker = root / ".recoryn-install.json"
    if not root.exists():
        if not create:
            raise ReleaseError("INSTALLATION_NOT_FOUND")
        root.mkdir(parents=True, exist_ok=False)
        atomic_json(marker, {"schema_version": 1, "app_id": APP_ID})
        (root / "versions").mkdir()
    identity = read_json(marker)
    if (
        identity != {"schema_version": 1, "app_id": APP_ID}
        or type(identity.get("schema_version")) is not int
    ):
        raise ReleaseError("INSTALLATION_IDENTITY_MISMATCH")
    lock = safe(root / ".install.lock").open("a+b")
    locked = False
    try:
        lock.seek(0, os.SEEK_END)
        if lock.tell() == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        locked = True
        yield
    finally:
        if locked:
            lock.seek(0)
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


def _version(root: Path, value: object) -> Path:
    if not isinstance(value, str) or re.fullmatch(r"v-[A-Za-z0-9._-]{1,120}", value) is None:
        raise ReleaseError("INVALID_ACTIVATION_POINTER")
    return safe(root / "versions" / value)


def _activation(root: Path) -> dict[str, Any]:
    value = read_json(root / "current.json")
    if (
        set(value) != {"schema_version", "app_id", "current", "previous"}
        or type(value.get("schema_version")) is not int
        or value["schema_version"] != 1
        or value.get("app_id") != APP_ID
    ):
        raise ReleaseError("INVALID_ACTIVATION_POINTER")
    _version(root, value.get("current"))
    if value.get("previous") is not None:
        _version(root, value["previous"])
    return value


def install(source: Path, root: Path) -> dict[str, Any]:
    """설치 실패 시 기존 current pointer와 이전 version 디렉터리를 보존한다."""
    source, root = safe(source), safe(root)
    if source.is_relative_to(root) or root.is_relative_to(source):
        raise ReleaseError("INSTALL_SOURCE_OVERLAP")
    manifest = verify(source)
    version_id = "v-" + manifest["version"] + "-" + digest(source / MANIFEST)[:16]
    with installation(root, create=True):
        pointer = root / "current.json"
        previous = _activation(root) if pointer.exists() else {}
        if previous:
            verify(_version(root, previous.get("current")))
        target = _version(root, version_id)
        if not target.exists():
            stage = safe(root / "versions" / (".staging-" + uuid4().hex))
            stage.mkdir(exist_ok=False)
            # Incomplete staging is preserved on error and never activated.
            for record in manifest["files"]:
                relative = record["path"]
                output = safe(stage / relative)
                output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(safe(source / relative), output)
            shutil.copyfile(source / MANIFEST, stage / MANIFEST)
            verify(stage)
            os.replace(stage, target)
        else:
            verify(target)
        current = previous.get("current")
        selected = {
            "schema_version": 1,
            "app_id": APP_ID,
            "current": version_id,
            "previous": previous.get("previous") if current == version_id else current,
        }
        atomic_json(pointer, selected)
        return {"installed": True, **selected, "launch": str(target / "Recoryn.exe")}


def rollback(root: Path) -> dict[str, Any]:
    root = safe(root)
    with installation(root):
        pointer = root / "current.json"
        current = _activation(root)
        old = _version(root, current.get("previous"))
        verify(old)
        _version(root, current.get("current"))
        selected = {
            "schema_version": 1,
            "app_id": APP_ID,
            "current": old.name,
            "previous": current["current"],
        }
        atomic_json(pointer, selected)
        return {"rolled_back": True, **selected}


def uninstall(root: Path) -> dict[str, Any]:
    """활성화를 해제하고 검증된 소유 파일만 제거한다. 잠긴/변경 파일은 pending이다."""
    root = safe(root)
    pending: list[str] = []
    with installation(root):
        pointer = root / "current.json"
        if pointer.exists():
            os.replace(safe(pointer), safe(root / "uninstalled.json"))
        for version in sorted(safe(root / "versions").iterdir()):
            safe(version)
            try:
                _version(root, version.name)
                manifest = verify(version, allow_missing=True)
            except (OSError, ValueError):
                pending.append(version.name)
                continue
            version_pending = False
            for name in [record["path"] for record in manifest["files"]]:
                try:
                    safe(version / name).unlink()
                except FileNotFoundError:
                    pass
                except OSError:
                    version_pending = True
                    pending.append(version.name + "/" + name)
            if not version_pending:
                try:
                    safe(version / MANIFEST).unlink()
                except OSError:
                    pending.append(version.name + "/" + MANIFEST)
            for directory in sorted(
                (p for p in version.rglob("*") if p.is_dir()),
                key=lambda p: len(p.parts),
                reverse=True,
            ):
                try:
                    safe(directory).rmdir()
                except OSError:
                    pass
            try:
                version.rmdir()
            except OSError:
                if version.name not in pending:
                    pending.append(version.name)
        return {
            "uninstalled": not pending,
            "deactivated": True,
            "pending": pending,
            "user_data_preserved": True,
        }
