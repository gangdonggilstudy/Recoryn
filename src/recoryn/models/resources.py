"""Read-only GPU discovery; explicit execution policy; one heavy inference lease."""

from __future__ import annotations

import shutil
import subprocess
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from recoryn.domain import StateConflict, ValidationError


@dataclass(frozen=True, slots=True)
class GPUInfo:
    index: int
    name: str
    free_bytes: int
    total_bytes: int


def probe_gpus() -> tuple[str, tuple[GPUInfo, ...]]:
    executable = shutil.which("nvidia-smi")
    if executable is None:
        return "UNAVAILABLE", ()
    try:
        result = subprocess.run(
            [
                executable,
                "--query-gpu=index,name,memory.free,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        gpus = []
        for row in result.stdout.splitlines():
            fields = row.split(",")
            if len(fields) != 4:
                return "UNKNOWN", ()
            index, free, total = int(fields[0]), int(fields[2]), int(fields[3])
            if not 0 <= index < 1024 or not 0 <= free <= total or total <= 0:
                return "UNKNOWN", ()
            gpus.append(GPUInfo(index, fields[1].strip(), free * 2**20, total * 2**20))
        return "OBSERVED", tuple(gpus)
    except (OSError, subprocess.SubprocessError, ValueError):
        return "UNKNOWN", ()


class ResourceScheduler:
    def __init__(self, *, headroom_bytes: int = 512 * 2**20) -> None:
        if type(headroom_bytes) is not int or headroom_bytes < 0:
            raise ValidationError("RESOURCE_HEADROOM")
        self.headroom_bytes = headroom_bytes
        self._lease = threading.Lock()

    def choose(
        self, policy: str, required_bytes: int, gpus: tuple[GPUInfo, ...]
    ) -> tuple[str, int]:
        if type(required_bytes) is not int or required_bytes < 0:
            raise ValidationError("RESOURCE_ESTIMATE_REQUIRED")
        if policy == "CPU_ONLY":
            return "cpu", 0
        if policy not in ("GPU_ONLY", "GPU_WITH_CPU_FALLBACK_ALLOWED"):
            raise ValidationError("RESOURCE_POLICY")
        for gpu in gpus:
            if gpu.free_bytes >= required_bytes + self.headroom_bytes:
                return "cuda", gpu.index
        if policy == "GPU_WITH_CPU_FALLBACK_ALLOWED":
            return "cpu", 0
        raise StateConflict("RESOURCE_GPU_UNAVAILABLE")

    @contextmanager
    def acquire(self, cancel: threading.Event | None = None) -> Iterator[None]:
        while not self._lease.acquire(timeout=0.1):
            if cancel is not None and cancel.is_set():
                raise StateConflict("RESOURCE_CANCELLED")
        try:
            if cancel is not None and cancel.is_set():
                raise StateConflict("RESOURCE_CANCELLED")
            yield
        finally:
            self._lease.release()
