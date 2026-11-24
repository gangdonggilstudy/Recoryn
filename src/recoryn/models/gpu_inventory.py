"""Owned, read-only resource observation for the owned-heavy plan (G-P11b, G11 section 4.2).

* Host RAM: the Windows read-only memory API (``GlobalMemoryStatusEx``); elsewhere the
  observation is UNAVAILABLE, never a guessed number.
* Host GPUs: one read-only ``nvidia-smi`` query that keeps UUID, PCI bus id and MIG mode.
* CUDA ordinals: an owned child process that activates the verified runtime *before*
  importing CTranslate2 (L-P07) with ``CUDA_DEVICE_ORDER=PCI_BUS_ID`` and returns the
  CUDA device count. It never loads a model.

The host index is never assumed to be the CUDA ordinal. The correspondence is verified
only when CUDA enumerates by PCI bus id, no ``CUDA_VISIBLE_DEVICES`` remapping is set, no
device runs MIG, every UUID is present and unique and the CUDA count equals the host
count; then ordinal *n* is the *n*-th device by PCI bus id. Anything else is
UNVERIFIED (RESOURCE_GPU_IDENTITY_UNVERIFIED), never "GPU 0". The inference child sets the
same ``CUDA_DEVICE_ORDER``. Real hardware correspondence is an external gate; tests
inject fakes for every probe here.
"""

from __future__ import annotations

import multiprocessing
import os
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from recoryn.models.resources import (
    NOT_OBSERVED,
    OBSERVED,
    UNAVAILABLE,
    UNKNOWN,
    GpuDevice,
    GpuObservation,
    MemoryObservation,
    ResourceSnapshot,
    ResourceSource,
)

CUDA_ORDER = {"CUDA_DEVICE_ORDER": "PCI_BUS_ID"}
_MIG_OFF = {"disabled", "[n/a]", "n/a"}


@dataclass(frozen=True, slots=True)
class HostGpu:
    index: int
    uuid: str
    bus_id: str
    name: str
    free_bytes: int
    total_bytes: int
    mig: str


def host_memory(clock: Callable[[], int] = time.monotonic_ns) -> MemoryObservation:
    """Free/total physical memory from GlobalMemoryStatusEx (read-only, no device)."""
    if sys.platform != "win32":
        return MemoryObservation(UNAVAILABLE, source="no-memory-api")
    try:
        import ctypes
        from ctypes import wintypes

        class Status(ctypes.Structure):
            _fields_ = [
                ("dwLength", wintypes.DWORD),
                ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = Status()
        status.dwLength = ctypes.sizeof(Status)
        windll = getattr(ctypes, "windll")  # noqa: B009 - absent on non-Windows typing
        if not windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return MemoryObservation(UNKNOWN, source="GlobalMemoryStatusEx")
        return MemoryObservation(
            OBSERVED,
            clock(),
            int(status.ullAvailPhys),
            int(status.ullTotalPhys),
            "GlobalMemoryStatusEx",
        )
    except Exception:
        return MemoryObservation(UNKNOWN, source="GlobalMemoryStatusEx")


def host_gpus(
    run: Callable[..., Any] = subprocess.run, which: Callable[[str], str | None] = shutil.which
) -> tuple[str, tuple[HostGpu, ...]]:
    """(state, rows) from one read-only nvidia-smi query; malformed output is UNKNOWN."""
    executable = which("nvidia-smi")
    if executable is None:
        return UNAVAILABLE, ()
    try:
        result = run(
            [
                executable,
                "--query-gpu=index,uuid,pci.bus_id,name,memory.free,memory.total,mig.mode.current",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        rows = []
        for line in str(result.stdout).splitlines():
            fields = [item.strip() for item in line.split(",")]
            if len(fields) != 7:
                return UNKNOWN, ()
            index, free, total = int(fields[0]), int(fields[4]), int(fields[5])
            if not 0 <= index < 1024 or not 0 <= free <= total or total <= 0:
                return UNKNOWN, ()
            rows.append(
                HostGpu(
                    index, fields[1], fields[2], fields[3], free * 2**20, total * 2**20, fields[6]
                )
            )
        return OBSERVED, tuple(rows)
    except (OSError, subprocess.SubprocessError, ValueError):
        return UNKNOWN, ()


def _count_child(runtime: str | None, reply: Any) -> None:
    # The runtime must be active before anything imports CTranslate2 (L-P07 D10).
    try:
        os.environ.update(CUDA_ORDER)
        os.environ.update({"HF_HUB_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1"})
        if runtime is not None:
            from recoryn.models.gpu_runtime import activate, supported

            if not supported():
                reply.send(None)
                return
            activate(Path(runtime))
        import importlib

        ctranslate2 = importlib.import_module("ctranslate2")
        reply.send(int(ctranslate2.get_cuda_device_count()))
    except Exception:
        reply.send(None)
    finally:
        reply.close()


class ProbeOwners:
    """Probe children that did not exit; a GPU runtime change waits for them."""

    def __init__(self) -> None:
        self._held: list[Any] = []
        self._lock = threading.Lock()

    def hold(self, process: Any) -> None:
        with self._lock:
            self._held.append(process)

    def live(self) -> bool:
        with self._lock:
            self._held = [item for item in self._held if item.is_alive()]
            return bool(self._held)


PROBE_OWNERS = ProbeOwners()


def cuda_device_count(runtime: Path | None, timeout: float = 60) -> int | None:
    """CUDA device count seen by a fresh owned child; None when unknown."""
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(
        target=_count_child,
        args=(None if runtime is None else str(runtime), sender),
        name="recoryn-gpu-probe",
        daemon=True,
    )
    try:
        process.start()
        sender.close()
        value = receiver.recv() if receiver.poll(timeout) else None
    except (OSError, EOFError):
        value = None
    finally:
        receiver.close()
        process.join(2)
        if process.is_alive():
            process.terminate()
            process.join(2)
        if process.is_alive():
            PROBE_OWNERS.hold(process)  # never report it finished
        else:
            process.close()
    return value if type(value) is int and 0 <= value < 1024 else None


def join_identity(
    state: str,
    rows: tuple[HostGpu, ...],
    count: int | None,
    environ: Mapping[str, str],
    observed_ns: int,
) -> GpuObservation:
    """Join host rows with the CUDA count; verified only under the module's conditions."""
    if state != OBSERVED:
        return GpuObservation(state, source="nvidia-smi")
    ordered = sorted(rows, key=lambda row: row.bus_id.lower())
    uuids = [row.uuid for row in rows]
    reason = None
    if environ.get("CUDA_VISIBLE_DEVICES") is not None:
        reason = "CUDA_VISIBLE_DEVICES"
    elif any(row.mig.lower() not in _MIG_OFF for row in rows):
        reason = "MIG"
    elif any(not item for item in uuids) or len(set(uuids)) != len(uuids):
        reason = "UUID"
    elif len({row.bus_id.lower() for row in rows}) != len(rows):
        reason = "BUS_ID"
    elif count is None:
        reason = "CUDA_COUNT_UNKNOWN"
    elif count != len(rows):
        reason = "CUDA_COUNT"
    if reason in ("UUID", "BUS_ID"):
        # No device identity to show: observed, never a verified placement.
        return GpuObservation(OBSERVED, observed_ns, (), False, "nvidia-smi", reason)
    try:
        devices = tuple(
            GpuDevice(
                row.uuid, ordinal, row.index, row.name or "GPU", row.free_bytes, row.total_bytes
            )
            for ordinal, row in enumerate(ordered)
        )
        if reason is not None:
            # Keep the observation for display, but never as a verified placement.
            return GpuObservation(OBSERVED, observed_ns, devices, False, "nvidia-smi", reason)
        return GpuObservation(OBSERVED, observed_ns, devices, True, "nvidia-smi+cuda")
    except Exception:
        return GpuObservation(UNKNOWN, source="nvidia-smi", reason="ROW_INVALID")


class Inventory:
    """The production observer: observes only what the plan needs (G11 section 4.2)."""

    def __init__(
        self,
        *,
        memory: Callable[[], MemoryObservation] = host_memory,
        gpus: Callable[[], tuple[str, tuple[HostGpu, ...]]] = host_gpus,
        count: Callable[[Path | None], int | None] = cuda_device_count,
        environ: Mapping[str, str] | None = None,
        clock: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        self._memory, self._gpus, self._count = memory, gpus, count
        self._environ = os.environ if environ is None else environ
        self._clock = clock
        self._cache: dict[tuple[Any, ...], int | None] = {}
        self._last_gpu: GpuObservation | None = None
        self._last_ram: MemoryObservation | None = None
        self._lock = threading.Lock()

    def __call__(self, need_gpu: bool, need_ram: bool, source: ResourceSource) -> ResourceSnapshot:
        ram = self._memory() if need_ram else MemoryObservation(NOT_OBSERVED)
        gpu = self._gpu(source) if need_gpu else GpuObservation(NOT_OBSERVED)
        with self._lock:
            last_gpu, last_ram = self._last_gpu, self._last_ram
            if gpu.state == OBSERVED:
                self._last_gpu = gpu
            if ram.state == OBSERVED:
                self._last_ram = ram
        taken = max(self._clock(), gpu.observed_ns or 0, ram.observed_ns or 0)
        return ResourceSnapshot(taken, gpu, ram, source, last_gpu, last_ram)

    def _gpu(self, source: ResourceSource) -> GpuObservation:
        state, rows = self._gpus()
        observed = self._clock()
        if state != OBSERVED:
            return GpuObservation(state, source="nvidia-smi")
        key = (
            source.cuda_source,
            None if source.runtime_root is None else str(source.runtime_root),
            self._environ.get("CUDA_VISIBLE_DEVICES"),
            tuple(sorted((row.bus_id, row.uuid) for row in rows)),
        )
        with self._lock:
            known = key in self._cache
            count = self._cache.get(key)
        if not known:
            count = self._count(source.runtime_root if source.cuda_source == "runtime" else None)
            if count is not None:
                with self._lock:
                    self._cache[key] = count
        return join_identity(state, rows, count, self._environ, observed)
