"""Bounded JSON and conservative local path handling (no power-loss guarantee)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
import uuid
from pathlib import Path
from typing import Any, BinaryIO, cast

from recoryn.domain import ValidationError

SCHEMA_VERSION = 1
MAX_JSON_BYTES = 64 * 1024
MAX_BLOCK_BYTES = 16 * 1024 * 1024
MAX_CHUNK_BYTES = 1024 * 1024 * 1024
MAX_RECORDS = 100_000


def identifier(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value):
        raise ValidationError("Unsafe identifier")
    if value.upper() in {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(10)),
        *(f"LPT{i}" for i in range(10)),
    }:
        raise ValidationError("Reserved identifier")
    return value


def integer(value: object, *, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= 2**63 - 1:
        raise ValidationError("Invalid integer")
    return value


def digest(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValidationError("Invalid SHA256")
    return value


def canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (ValueError, TypeError, RecursionError, UnicodeError) as exc:
        raise ValidationError("Invalid JSON value") from exc


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError("Duplicate JSON key")
        result[key] = value
    return result


def _invalid_number(value: str) -> None:
    raise ValidationError("Non-integer JSON number")


def strict_json(data: bytes, *, limit: int = MAX_JSON_BYTES) -> dict[str, Any]:
    if len(data) > limit:
        raise ValidationError("JSON size limit exceeded")
    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_pairs,
            parse_constant=_invalid_number,
            parse_float=_invalid_number,
        )
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ValidationError("Invalid JSON") from exc
    if not isinstance(value, dict):
        raise ValidationError("JSON object required")
    return value


def schema(value: dict[str, Any]) -> None:
    if type(value.get("schema_version")) is not int or value["schema_version"] != SCHEMA_VERSION:
        raise ValidationError("Unsupported schema version")


def root_path(root: Path) -> Path:
    if str(root).startswith(("\\\\", "//")):
        raise ValidationError("UNC and device namespace roots are not supported")
    path = Path(os.path.abspath(root))
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        # This queries the local mount table, not the remote server.
        # https://learn.microsoft.com/windows/win32/api/fileapi/nf-fileapi-getdrivetypew
        drive_type = ctypes.windll.kernel32.GetDriveTypeW
        drive_type.argtypes = [wintypes.LPCWSTR]
        drive_type.restype = wintypes.UINT
        if drive_type(path.anchor) in (0, 1, 4):
            raise ValidationError("Unknown or network drive roots are not supported")
    check_path(path)
    return path


def check_path(path: Path) -> None:
    """Reject links/reparse points in every existing component, including ancestors.

    This is a cooperating-process boundary, not an OS sandbox against an attacker
    with the same user's permissions racing directory replacement.
    """
    absolute = Path(os.path.abspath(path))
    for component in [*reversed(absolute.parents), absolute]:
        try:
            info = component.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValidationError("Links and reparse points are not supported")
        if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            raise ValidationError("Hard-linked files are not supported")
        if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
            raise ValidationError("Special files are not supported")


def safe_path(root: Path, *parts: str) -> Path:
    candidate = root
    for part in parts:
        relative = Path(part)
        if relative.is_absolute() or relative.drive or ".." in relative.parts or "\\" in part:
            raise ValidationError("Unsafe relative path")
        if ":" in part:
            raise ValidationError("Alternate streams are not supported")
        candidate /= relative
    if not candidate.is_relative_to(root):
        raise ValidationError("Path escaped root")
    check_path(candidate)
    return candidate


def mkdir(path: Path) -> None:
    check_path(path)
    path.mkdir(parents=True, exist_ok=True)
    check_path(path)


def open_file(path: Path, mode: str) -> BinaryIO:
    check_path(path)
    flags = os.O_RDONLY if mode == "rb" else os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        check_path(path)
        actual, named = os.fstat(fd), path.lstat()
        if (actual.st_dev, actual.st_ino) != (named.st_dev, named.st_ino):
            raise ValidationError("File changed during open")
        if not stat.S_ISREG(actual.st_mode) or actual.st_nlink != 1:
            raise ValidationError("Unsafe file")
        return cast(BinaryIO, os.fdopen(fd, mode, buffering=0))
    except BaseException:
        os.close(fd)
        raise


def read_json(path: Path, *, limit: int = MAX_JSON_BYTES) -> dict[str, Any]:
    with open_file(path, "rb") as stream:
        return strict_json(stream.read(limit + 1), limit=limit)


def write_all(stream: BinaryIO, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = stream.write(view)
        if written is None or written <= 0:
            raise OSError("Short write")
        view = view[written:]


def sync(stream: BinaryIO) -> None:
    stream.flush()
    os.fsync(stream.fileno())


def atomic_json(path: Path, value: object) -> None:
    encoded = canonical(value) + b"\n"
    if len(encoded) > 8 * 1024 * 1024:
        raise ValidationError("Projection size limit exceeded")
    check_path(path)
    if path.exists():
        schema(read_json(path, limit=8 * 1024 * 1024))
    mkdir(path.parent)
    temporary = path.parent / (".tmp-" + uuid.uuid4().hex)
    try:
        with open_file(temporary, "xb") as stream:
            write_all(stream, encoded)
            sync(stream)
        check_path(path)
        check_path(temporary)
        os.replace(temporary, path)
        # Directory fsync is not portable to Windows. File fsync and SQLite FULL
        # do not constitute a guarantee about controller caches or power loss.
    finally:
        if temporary.exists():
            check_path(temporary)
            temporary.unlink()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def remove_tree(path: Path) -> None:
    check_path(path)
    if not path.exists():
        return
    for child in path.iterdir():
        check_path(child)
        if child.is_dir():
            remove_tree(child)
        else:
            child.unlink()
    check_path(path)
    path.rmdir()
