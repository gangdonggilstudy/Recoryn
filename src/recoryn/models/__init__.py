"""Explicit, checksummed model installation and conservative inference resources."""

from recoryn.models.manager import FileSpec, ModelManager, ModelSpec
from recoryn.models.resources import (
    GpuDevice,
    GPUInfo,
    GpuObservation,
    Lease,
    MemoryObservation,
    ResourcePlan,
    ResourceRequest,
    ResourceScheduler,
    ResourceSnapshot,
    ResourceSource,
    plan_resources,
    plan_static,
    probe_gpus,
)

__all__ = [
    "FileSpec",
    "GPUInfo",
    "GpuDevice",
    "GpuObservation",
    "Lease",
    "MemoryObservation",
    "ModelManager",
    "ModelSpec",
    "ResourcePlan",
    "ResourceRequest",
    "ResourceScheduler",
    "ResourceSnapshot",
    "ResourceSource",
    "plan_resources",
    "plan_static",
    "probe_gpus",
]
