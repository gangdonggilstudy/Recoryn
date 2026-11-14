"""Explicit, checksummed model installation and conservative inference resources."""

from recoryn.models.manager import FileSpec, ModelManager, ModelSpec
from recoryn.models.resources import GPUInfo, ResourceScheduler, probe_gpus

__all__ = ["FileSpec", "GPUInfo", "ModelManager", "ModelSpec", "ResourceScheduler", "probe_gpus"]
