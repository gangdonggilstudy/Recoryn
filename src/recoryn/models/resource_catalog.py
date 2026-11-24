"""Fixed backend enforcement table for the device policy (G-P11a, contract G11 section 3.1).

Static source data only: no network, no files, no probes and no server self-reports.
The table says, per backend and task, what each execution policy means on this PC:
a forced device, an automatic choice between verified devices, a server the app does
not control, a remote provider the policy does not apply to, or a refusal code.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from types import MappingProxyType

from recoryn.domain import ValidationError

POLICIES = ("CPU_ONLY", "GPU_ONLY", "GPU_WITH_CPU_FALLBACK_ALLOWED")
KINDS = ("stt", "summary", "diarization")
BACKENDS = ("LOCAL_CT2", "LOCAL_SHERPA", "OLLAMA", "REMOTE")

# Device outcomes. "auto" chooses among verified devices under the request's policy.
CPU, CUDA, AUTO = "cpu", "cuda", "auto"
SERVER_UNKNOWN, NOT_APPLICABLE = "server_unknown", "not_applicable"

# Refusal codes (closed G-P07 catalog: both are CAPABILITY).
POLICY_UNVERIFIED = "RESOURCE_POLICY_UNVERIFIED"
GPU_UNSUPPORTED = "RESOURCE_GPU_UNSUPPORTED"
UNSUPPORTED = "CAPABILITY_UNSUPPORTED"

_REMOTE = {policy: NOT_APPLICABLE for policy in POLICIES}
_TABLE = {
    ("LOCAL_CT2", "stt"): {
        "CPU_ONLY": CPU,
        "GPU_ONLY": CUDA,
        "GPU_WITH_CPU_FALLBACK_ALLOWED": AUTO,
    },
    ("LOCAL_SHERPA", "diarization"): {
        "CPU_ONLY": CPU,
        "GPU_ONLY": GPU_UNSUPPORTED,
        "GPU_WITH_CPU_FALLBACK_ALLOWED": CPU,
    },
    # Ollama's num_gpu, /api/ps ratios, a localhost endpoint or an attestation do not
    # prove where inference runs, so the strict policies refuse it before preparation.
    ("OLLAMA", "summary"): {
        "CPU_ONLY": POLICY_UNVERIFIED,
        "GPU_ONLY": POLICY_UNVERIFIED,
        "GPU_WITH_CPU_FALLBACK_ALLOWED": SERVER_UNKNOWN,
    },
    ("REMOTE", "stt"): _REMOTE,
    ("REMOTE", "summary"): _REMOTE,
}
CATALOG = MappingProxyType({key: MappingProxyType(value) for key, value in _TABLE.items()})
CATALOG_DIGEST = hashlib.sha256(
    json.dumps(
        [[backend, kind, dict(rules)] for (backend, kind), rules in sorted(_TABLE.items())],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
).hexdigest()
REFUSALS = frozenset({POLICY_UNVERIFIED, GPU_UNSUPPORTED, UNSUPPORTED})

# The provider an AI settings screen offers, mapped to the backend identity it runs on.
# Registered identity, never inferred from an endpoint string.
PROVIDER_BACKENDS = MappingProxyType(
    {
        "faster_whisper": "LOCAL_CT2",
        "ollama": "OLLAMA",
        "openai": "REMOTE",
        "gemini": "REMOTE",
        "anthropic": "REMOTE",
        "sherpa_onnx": "LOCAL_SHERPA",
    }
)


def backend_rule(backend: str, kind: str, policy: str) -> str:
    """The device outcome or refusal code for one combination (unsupported otherwise)."""
    rules = CATALOG.get((backend, kind))
    return UNSUPPORTED if rules is None else rules[policy]


# --- offline memory profiles (G-P11b, contract G11 section 4.1) ----------------------
OWNED_BACKENDS = MappingProxyType({"LOCAL_CT2": "stt", "LOCAL_SHERPA": "diarization"})
PROFILE_STATUSES = ("MEASURED", "REVIEWED")
_COUNT_LIMIT = 2**63


def _text(value: object, maximum: int = 256) -> bool:
    return type(value) is str and 0 < len(value) <= maximum and "\x00" not in value


def _bytes_or_none(value: object) -> bool:
    return value is None or (type(value) is int and 0 <= value < _COUNT_LIMIT)


@dataclass(frozen=True, slots=True)
class MemoryProfile:
    """One reviewed offline record of a model path's planned memory, per device.

    ``cpu_host_ram`` is the host RAM the CPU path needs; ``gpu_host_ram`` and
    ``gpu_bytes`` are the host RAM and VRAM the CUDA path needs. A device whose numbers
    are None is UNKNOWN for that device only. ``digest`` must equal
    :func:`profile_digest`; ``evidence`` is the SHA-256 of the measurement record.
    """

    profile_id: str
    kind: str
    backend: str
    model_identity: str
    runtime_identity: str
    envelope: tuple[tuple[str, int], ...]
    cpu_host_ram: int | None
    gpu_host_ram: int | None
    gpu_bytes: int | None
    evidence: str
    status: str
    digest: str

    def __post_init__(self) -> None:
        envelope = self.envelope
        if (
            not all(
                _text(value)
                for value in (self.profile_id, self.model_identity, self.runtime_identity)
            )
            or OWNED_BACKENDS.get(self.backend) != self.kind
            or not all(
                _bytes_or_none(value)
                for value in (self.cpu_host_ram, self.gpu_host_ram, self.gpu_bytes)
            )
            or (self.gpu_host_ram is None) != (self.gpu_bytes is None)
            or (self.kind == "diarization" and self.gpu_bytes is not None)
            or type(envelope) is not tuple
            or not all(
                type(item) is tuple
                and len(item) == 2
                and _text(item[0], 64)
                and type(item[1]) is int
                and 0 <= item[1] < _COUNT_LIMIT
                for item in envelope
            )
            or len({item[0] for item in envelope}) != len(envelope)
            or type(self.evidence) is not str
            or type(self.status) is not str
            or type(self.digest) is not str
        ):
            raise ValidationError("INVALID_MEMORY_PROFILE")


def profile_digest(profile: MemoryProfile) -> str:
    """Canonical digest of every field except ``digest`` itself."""
    fields = [
        profile.profile_id,
        profile.kind,
        profile.backend,
        profile.model_identity,
        profile.runtime_identity,
        [list(item) for item in sorted(profile.envelope)],
        profile.cpu_host_ram,
        profile.gpu_host_ram,
        profile.gpu_bytes,
        profile.evidence,
        profile.status,
    ]
    return hashlib.sha256(json.dumps(fields, separators=(",", ":")).encode()).hexdigest()


def profile_intact(profile: MemoryProfile) -> bool:
    """A record whose digest, evidence hash and review status are all sound."""
    return (
        profile.digest == profile_digest(profile)
        and len(profile.evidence) == 64
        and all(char in "0123456789abcdef" for char in profile.evidence)
        and profile.status in PROFILE_STATUSES
    )


# C00 decision (section 4.1): no entry without real, reviewed measurements. An empty
# production catalog does not block owned inference; requirements stay UNKNOWN. Test
# profiles are injected into a ResourceScheduler, never added here.
PROFILES: tuple[MemoryProfile, ...] = ()
PROFILES_DIGEST = hashlib.sha256(
    json.dumps([profile.digest for profile in PROFILES]).encode()
).hexdigest()
