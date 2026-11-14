"""No implicit downloads, archive extraction, remote code, or unverified activation."""

from __future__ import annotations

import hashlib
import http.client
import os
import re
import threading
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlsplit

from recoryn.domain import StateConflict, ValidationError
from recoryn.storage._safe import (
    atomic_json,
    check_path,
    digest,
    identifier,
    integer,
    mkdir,
    open_file,
    read_json,
    remove_tree,
    root_path,
    safe_path,
    schema,
    sync,
    write_all,
)


@dataclass(frozen=True, slots=True)
class FileSpec:
    path: str
    url: str
    size: int
    sha256: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.path, str)
            or not self.path
            or any(not re.fullmatch(r"[A-Za-z0-9_.-]+", p) for p in self.path.split("/"))
        ):
            raise ValidationError("MODEL_FILE_PATH")
        if any(p in (".", "..") or p.endswith((".", " ")) for p in self.path.split("/")):
            raise ValidationError("MODEL_FILE_PATH")
        for part in self.path.split("/"):
            # Include extensions when checking Windows reserved device names.
            identifier(part.split(".")[0])
        _url(self.url)
        integer(self.size, minimum=1)
        digest(self.sha256)


@dataclass(frozen=True, slots=True)
class ModelSpec:
    model_id: str
    kind: str
    license_id: str
    license_url: str
    files: tuple[FileSpec, ...]

    def __post_init__(self) -> None:
        identifier(self.model_id)
        if self.kind not in ("whisper", "diarization", "other"):
            raise ValidationError("MODEL_KIND")
        if (
            not isinstance(self.license_id, str)
            or not self.license_id.strip()
            or len(self.license_id) > 256
        ):
            raise ValidationError("MODEL_LICENSE_REQUIRED")
        _url(self.license_url)
        if (
            type(self.files) is not tuple
            or not self.files
            or len(self.files) > 1000
            or any(not isinstance(item, FileSpec) for item in self.files)
        ):
            raise ValidationError("MODEL_FILES_REQUIRED")
        names = [f.path.casefold() for f in self.files]
        if len(set(names)) != len(names) or "installed.json" in names:
            raise ValidationError("MODEL_DUPLICATE_FILE")
        for name in names:
            if any(other.startswith(name + "/") for other in names):
                raise ValidationError("MODEL_FILE_DIRECTORY_CONFLICT")


def _url(url: str) -> tuple[str, int | None, str]:
    if not isinstance(url, str):
        raise ValidationError("MODEL_HTTPS_URL_REQUIRED")
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
        or any(ord(c) < 33 for c in url)
    ):
        raise ValidationError("MODEL_HTTPS_URL_REQUIRED")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValidationError("MODEL_URL_PORT") from exc
    return (
        parsed.hostname,
        port,
        (parsed.path or "/") + ("?" + parsed.query if parsed.query else ""),
    )


def _download(url: str, offset: int) -> Iterator[bytes]:
    host, port, path = _url(url)
    connection = http.client.HTTPSConnection(host, port, timeout=20)
    try:
        headers = {"Accept-Encoding": "identity", "User-Agent": "Recoryn-model-download"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        connection.request("GET", path, headers=headers)
        response = connection.getresponse()
        if response.status != (206 if offset else 200):
            raise ValidationError("MODEL_DOWNLOAD_STATUS_OR_REDIRECT")
        if offset and not (response.getheader("Content-Range") or "").startswith(
            f"bytes {offset}-"
        ):
            raise ValidationError("MODEL_DOWNLOAD_RANGE")
        if response.getheader("Content-Encoding", "identity") != "identity":
            raise ValidationError("MODEL_DOWNLOAD_ENCODING")
        while block := response.read(256 * 1024):
            yield block
    finally:
        connection.close()


def _verify_file_set(root: Path, files: tuple[FileSpec, ...]) -> None:
    expected = {item.path.casefold() for item in files} | {"installed.json"}
    pending = [root]
    inspected = 0
    while pending:
        directory = pending.pop()
        for path in directory.iterdir():
            check_path(path)
            inspected += 1
            if inspected > 4096 or len(path.relative_to(root).parts) > 32:
                raise ValidationError("MODEL_FILE_SET_LIMIT")
            name = path.relative_to(root).as_posix().casefold()
            if path.is_dir():
                if not any(value.startswith(name + "/") for value in expected):
                    raise ValidationError("MODEL_UNEXPECTED_DIRECTORY")
                pending.append(path)
            elif name not in expected:
                raise ValidationError("MODEL_UNEXPECTED_FILE")


class ModelManager:
    """Caller-reviewed manifests pin bytes; their hashes do not authenticate publishers.

    The caller must explicitly accept the model's license and displayed source URLs.
    Partial files remain resumable after cancellation; activation requires every hash.
    """

    def __init__(
        self,
        root: Path,
        *,
        downloader: Callable[[str, int], Iterator[bytes]] | None = None,
    ) -> None:
        self.root = root_path(root)
        self._download = downloader or _download
        self._lock = threading.Lock()

    def install(
        self,
        spec: ModelSpec,
        *,
        approved: bool = False,
        cancel: threading.Event | None = None,
        progress: Callable[[int, int], None] | None = None,
    ) -> Path:
        if not approved:
            raise ValidationError("MODEL_DOWNLOAD_REQUIRES_APPROVAL")
        if not self._lock.acquire(blocking=False):
            raise StateConflict("MODEL_OPERATION_ACTIVE")
        try:
            target = safe_path(self.root, spec.model_id)
            if target.exists():
                raise StateConflict("MODEL_ALREADY_INSTALLED")
            staging = safe_path(self.root, ".partial-" + spec.model_id)
            mkdir(staging)
            plan = {"schema_version": 1, "spec": asdict(spec)}
            plan_path = safe_path(staging, "plan.json")
            if plan_path.exists() and read_json(plan_path, limit=1024 * 1024) != _json_plan(plan):
                raise StateConflict("MODEL_PARTIAL_PLAN_MISMATCH")
            atomic_json(plan_path, plan)
            total = sum(item.size for item in spec.files)
            completed = 0
            for item in spec.files:
                if cancel is not None and cancel.is_set():
                    raise StateConflict("MODEL_DOWNLOAD_CANCELLED")
                path = safe_path(staging, "files", item.path)
                mkdir(path.parent)
                offset = path.stat().st_size if path.exists() else 0
                if offset > item.size:
                    raise ValidationError("MODEL_PARTIAL_OVERSIZED")
                if offset < item.size:
                    self._receive(path, item, offset, completed, total, cancel, progress)
                self._verify(path, item)
                completed += item.size
                if progress:
                    progress(completed, total)
            files_root = safe_path(staging, "files")
            _verify_file_set(files_root, spec.files)
            if cancel is not None and cancel.is_set():
                raise StateConflict("MODEL_DOWNLOAD_CANCELLED")
            atomic_json(safe_path(files_root, "installed.json"), plan)
            check_path(target)
            if cancel is not None and cancel.is_set():
                raise StateConflict("MODEL_DOWNLOAD_CANCELLED")
            os.rename(files_root, target)
            remove_tree(staging)
            return target
        finally:
            self._lock.release()

    def _receive(
        self,
        path: Path,
        item: FileSpec,
        offset: int,
        completed: int,
        total: int,
        cancel: threading.Event | None,
        progress: Callable[[int, int], None] | None,
    ) -> None:
        # Existing partials may be appended only after conservative path checks.
        check_path(path)
        flags = os.O_WRONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        flags |= os.O_APPEND if path.exists() else os.O_CREAT | os.O_EXCL
        fd = os.open(path, flags, 0o600)
        try:
            check_path(path)
            actual, named = os.fstat(fd), path.stat()
            if (actual.st_dev, actual.st_ino) != (
                named.st_dev,
                named.st_ino,
            ) or actual.st_nlink != 1:
                raise ValidationError("MODEL_FILE_CHANGED")
            with os.fdopen(fd, "ab", buffering=0, closefd=False) as stream:
                for block in self._download(item.url, offset):
                    if cancel is not None and cancel.is_set():
                        raise StateConflict("MODEL_DOWNLOAD_CANCELLED")
                    if not isinstance(block, bytes) or not block or len(block) > 1024 * 1024:
                        raise ValidationError("MODEL_DOWNLOAD_BLOCK")
                    if offset + len(block) > item.size:
                        raise ValidationError("MODEL_DOWNLOAD_OVERSIZED")
                    write_all(stream, block)
                    offset += len(block)
                    if progress:
                        progress(completed + offset, total)
                sync(stream)
        finally:
            os.close(fd)
        if offset != item.size:
            raise ValidationError("MODEL_DOWNLOAD_INCOMPLETE")

    @staticmethod
    def _verify(path: Path, item: FileSpec) -> None:
        hasher = hashlib.sha256()
        size = 0
        with open_file(path, "rb") as stream:
            while block := stream.read(256 * 1024):
                size += len(block)
                hasher.update(block)
        if size != item.size or hasher.hexdigest() != item.sha256:
            raise ValidationError("MODEL_CHECKSUM_MISMATCH")

    def verify(self, model_id: str) -> Path:
        path = safe_path(self.root, identifier(model_id))
        data = read_json(safe_path(path, "installed.json"), limit=1024 * 1024)
        schema(data)
        if set(data) != {"schema_version", "spec"}:
            raise ValidationError("MODEL_MANIFEST_SCHEMA")
        spec = parse_spec(data["spec"])
        if spec.model_id != model_id:
            raise ValidationError("MODEL_ID_MISMATCH")
        _verify_file_set(path, spec.files)
        for item in spec.files:
            self._verify(safe_path(path, item.path), item)
        return path

    def list_installed(self) -> list[dict[str, object]]:
        if not self.root.exists():
            return []
        result: list[dict[str, object]] = []
        for path in sorted(self.root.iterdir()):
            check_path(path)
            if not path.is_dir() or path.name.startswith("."):
                continue
            try:
                verified = self.verify(path.name)
                result.append({"model_id": path.name, "path": str(verified), "verified": True})
            except (OSError, KeyError, TypeError, ValueError):
                result.append({"model_id": path.name, "verified": False})
        return result

    def delete(self, model_id: str) -> None:
        with self._lock:
            remove_tree(safe_path(self.root, identifier(model_id)))
            remove_tree(safe_path(self.root, ".partial-" + model_id))


def _json_plan(value: dict[str, object]) -> dict[str, object]:
    import json

    result: dict[str, object] = json.loads(json.dumps(value))
    return result


def parse_spec(value: object) -> ModelSpec:
    if not isinstance(value, dict) or set(value) != {
        "model_id",
        "kind",
        "license_id",
        "license_url",
        "files",
    }:
        raise ValidationError("MODEL_SPEC_SCHEMA")
    try:
        files = tuple(FileSpec(**item) for item in value["files"])
        return ModelSpec(
            value["model_id"], value["kind"], value["license_id"], value["license_url"], files
        )
    except (TypeError, KeyError, AttributeError) as exc:
        raise ValidationError("MODEL_SPEC_SCHEMA") from exc
