"""Fixed backend enforcement table for the device policy (G-P11a, contract G11 section 3.1).

Static source data only: no network, no files, no probes and no server self-reports.
The table says, per backend and task, what each execution policy means on this PC:
a forced device, an automatic choice between verified devices, a server the app does
not control, a remote provider the policy does not apply to, or a refusal code.
"""

from __future__ import annotations

import hashlib
import json
from types import MappingProxyType

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
