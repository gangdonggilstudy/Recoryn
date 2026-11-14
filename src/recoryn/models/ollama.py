"""Explicitly owned Ollama server with pinned local blobs and cloud disabled.

See https://docs.ollama.com/faq#how-do-i-disable-ollamas-cloud-features
This controls our child only; it does not certify the daemon or its network stack.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from recoryn.domain import StateConflict, ValidationError
from recoryn.providers import LocalModelAttestation, ProviderError
from recoryn.storage._safe import check_path, open_file, read_json, root_path, safe_path

from ._owned import OwnedServer, listener_matches


def verify_local_model(models: Path, model: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]+:[A-Za-z0-9_.-]+", model) or model.endswith(":cloud"):
        raise ValidationError("OLLAMA_LOCAL_MODEL_NAME_REQUIRED")
    name, tag = model.split(":")
    root = root_path(models)
    manifest = safe_path(root, "manifests", "registry.ollama.ai", "library", name, tag)
    data = read_json(manifest, limit=1024 * 1024)
    if data.get("schemaVersion") != 2 or not isinstance(data.get("layers"), list):
        raise ValidationError("OLLAMA_MODEL_MANIFEST")
    records = [data.get("config"), *data["layers"]]
    if not 2 <= len(records) <= 1000:
        raise ValidationError("OLLAMA_MODEL_MANIFEST")
    has_weights = False
    for item in records:
        if not isinstance(item, dict):
            raise ValidationError("OLLAMA_MODEL_MANIFEST")
        digest = item.get("digest", "")
        size = item.get("size")
        if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            raise ValidationError("OLLAMA_MODEL_DIGEST")
        if type(size) is not int or size < 0:
            raise ValidationError("OLLAMA_MODEL_SIZE")
        has_weights |= item.get("mediaType") == "application/vnd.ollama.image.model"
        blob = safe_path(root, "blobs", digest.replace(":", "-"))
        hasher = hashlib.sha256()
        actual = 0
        with open_file(blob, "rb") as stream:
            while block := stream.read(1024 * 1024):
                actual += len(block)
                hasher.update(block)
        if actual != size or hasher.hexdigest() != digest[7:]:
            raise ValidationError("OLLAMA_MODEL_CHECKSUM")
    if not has_weights:
        raise ValidationError("OLLAMA_LOCAL_WEIGHTS_REQUIRED")
    # Reject remote execution hints rather than elevating a loopback endpoint.
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":"))
    if any(key in encoded.lower() for key in ("remote_host", "remote_model", "cloud")):
        raise ValidationError("OLLAMA_REMOTE_MODEL_BLOCKED")
    return hashlib.sha256(encoded.encode()).hexdigest()


def _model_files(models: Path, model: str) -> tuple[Path, ...]:
    name, tag = model.split(":")
    manifest = safe_path(models, "manifests", "registry.ollama.ai", "library", name, tag)
    data = read_json(manifest, limit=1024 * 1024)
    return (
        manifest,
        *(
            safe_path(models, "blobs", item["digest"].replace(":", "-"))
            for item in [data["config"], *data["layers"]]
        ),
    )


def _identities(paths: tuple[Path, ...]) -> tuple[tuple[int, ...], ...]:
    output = []
    for path in paths:
        check_path(path)
        stat = path.stat()
        if stat.st_nlink != 1:
            raise ValidationError("OLLAMA_MODEL_FILE_CHANGED")
        output.append((stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))
    return tuple(output)


class ManagedOllama:
    def __init__(self, *, startup_timeout: float = 10) -> None:
        if (
            isinstance(startup_timeout, bool)
            or not isinstance(startup_timeout, (int, float))
            or not math.isfinite(startup_timeout)
            or not 0 < startup_timeout <= 60
        ):
            raise ValidationError("OLLAMA_START_TIMEOUT_INVALID")
        self.startup_timeout = startup_timeout
        self.process: Any = None
        self._attestation: LocalModelAttestation | None = None
        self._lock = threading.RLock()
        self._generation = 0
        self._port = 0
        self._paths: tuple[Path, ...] = ()
        self._snapshot: tuple[tuple[int, ...], ...] = ()

    @contextmanager
    def _execution_guard(self, generation: int) -> Iterator[None]:
        with self._lock:
            try:
                valid = (
                    self._generation == generation
                    and self._attestation is not None
                    and self.process is not None
                    and self.process.poll() is None
                    and listener_matches(self.process.pid, self._port, job=self.process.job_handle)
                    and _identities(self._paths) == self._snapshot
                )
            except Exception:
                valid = False
            if not valid:
                if self._generation == generation:
                    self._attestation = None
                raise ProviderError("LOCAL_EXECUTION_UNVERIFIED")
            yield

    def start(
        self, executable: Path, models: Path, model: str, *, cancel: threading.Event | None = None
    ) -> LocalModelAttestation:
        with self._lock:
            return self._start(executable, models, model, cancel)

    def _start(
        self, executable: Path, models: Path, model: str, cancel: threading.Event | None
    ) -> LocalModelAttestation:
        if self.process is not None:
            raise StateConflict("OLLAMA_ALREADY_OWNED")
        executable = root_path(executable)
        if not executable.is_file():
            raise ValidationError("OLLAMA_EXECUTABLE_MISSING")
        digest = verify_local_model(models, model)
        self._paths = (executable, *_model_files(root_path(models), model))
        self._snapshot = _identities(self._paths)
        # Rehash while checking the file identities around validation; no model is loaded.
        if (
            verify_local_model(models, model) != digest
            or _identities(self._paths) != self._snapshot
        ):
            raise ValidationError("OLLAMA_MODEL_FILE_CHANGED")
        if cancel is not None and cancel.is_set():
            raise StateConflict("OLLAMA_START_CANCELLED")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reserve:
            reserve.bind(("127.0.0.1", 0))
            port = reserve.getsockname()[1]
        environment = dict(os.environ)
        environment.update(
            {
                "OLLAMA_HOST": f"127.0.0.1:{port}",
                "OLLAMA_MODELS": str(root_path(models)),
                "OLLAMA_NO_CLOUD": "1",
                "OLLAMA_ORIGINS": "http://127.0.0.1",
            }
        )
        for name in (
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "http_proxy",
            "https_proxy",
            "all_proxy",
        ):
            environment.pop(name, None)
        environment["NO_PROXY"] = "127.0.0.1,localhost,::1"
        check_path(executable)
        self._port = port
        self._generation += 1
        generation = self._generation
        self.process = OwnedServer(executable, environment)
        try:
            deadline = time.monotonic() + self.startup_timeout
            while True:
                if cancel is not None and cancel.is_set():
                    raise StateConflict("OLLAMA_START_CANCELLED")
                if self.process.poll() is not None:
                    raise StateConflict("OLLAMA_OWNED_SERVER_NOT_RUNNING")
                if listener_matches(self.process.pid, port, job=self.process.job_handle):
                    break
                if time.monotonic() >= deadline:
                    raise StateConflict("OLLAMA_START_NOT_READY")
                threading.Event().wait(0.02)
            if _identities(self._paths) != self._snapshot:
                raise ValidationError("OLLAMA_MODEL_FILE_CHANGED")
            self._attestation = LocalModelAttestation(
                f"http://127.0.0.1:{port}/api/chat",
                model,
                digest,
                True,
                time.monotonic() + 3600,
                lifetime_guard=lambda: self._execution_guard(generation),
            )
            return self.attestation()
        except BaseException:
            self.close()
            raise

    def attestation(self) -> LocalModelAttestation:
        with self._lock:
            proof = self._attestation
            if proof is None:
                raise StateConflict("OLLAMA_OWNED_SERVER_NOT_RUNNING")
            try:
                with proof.execution_guard():
                    return proof
            except ProviderError:
                self._attestation = None
                raise StateConflict("OLLAMA_LOCAL_EXECUTION_UNVERIFIED") from None

    def close(self) -> None:
        with self._lock:
            self._attestation = None
            self._generation += 1
            child = self.process
            if child is not None:
                # The private Job stops and acknowledges every owned descendant.
                # Keep the child reference on failure for an explicit cleanup retry.
                child.close()
                self.process = None
