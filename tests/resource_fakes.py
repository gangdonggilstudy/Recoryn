"""Fake resource intents for tests that call AIService directly (G-P11a).

These are not device or memory profiles. A LOCAL_CT2 request under CPU_ONLY forces the
CPU and a REMOTE request is outside this PC's device policy, so neither depends on a GPU,
on memory or on any probe. Tests of the policy itself build their own requests.
"""

from __future__ import annotations

from typing import Any

from recoryn.models import ResourceRequest


def stt_request(
    policy: str = "CPU_ONLY", backend: str = "LOCAL_CT2", **fields: Any
) -> ResourceRequest:
    return ResourceRequest("stt", backend, policy, **fields)


def summary_request(
    policy: str = "CPU_ONLY", backend: str = "REMOTE", **fields: Any
) -> ResourceRequest:
    return ResourceRequest("summary", backend, policy, **fields)


STT = stt_request()
SUMMARY = summary_request()
