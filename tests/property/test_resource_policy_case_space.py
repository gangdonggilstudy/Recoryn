"""G11 case-space census: the full amended denominator and the G-P11a share.

The family formulas are transcribed from the G11 contract (section 7.1 and the amendment
section 6). G-P11a owns exactly A36 + Ua144 + C001-016 + C097-100 + T19/20/27/28/30/31 = 206.
Every other ID belongs to G-P11b and must not be claimed by a P11a node.
"""

from __future__ import annotations

import inspect
from itertools import product

from recoryn.models import ResourceRequest
from tests.integration import test_resource_policy as integration
from tests.ui import test_resource_policy_ui as ui
from tests.unit import test_resource_policy as unit

FAMILIES = {
    "A": ("G11-A-{:02}", 36),
    "P": ("G11-P-{:05}", 31104),
    "E": ("G11-E-{:02}", 72),
    "G": ("G11-G-{:03}", 120),
    "R": ("G11-R-{:03}", 144),
    "Q": ("G11-Q-{:03}", 864),
    "L": ("G11-L-{:02}", 96),
    "UA": ("G11-UA-{:03}", 144),
    "UB": ("G11-UB-{:02}", 48),
    "C": ("G11-C-{:03}", 120),
    "S": ("G11-S-{:02}", 20),
    "T": ("G11-T-{:02}", 31),
}
P11A_RULE = {
    "A": set(range(1, 37)),
    "UA": set(range(1, 145)),
    "C": set(range(1, 17)) | set(range(97, 101)),
    "T": {19, 20, 27, 28, 30, 31},
}


def ids(family: str) -> list[str]:
    pattern, size = FAMILIES[family]
    return [pattern.format(n) for n in range(1, size + 1)]


def declared() -> list[str]:
    """IDs the P11a nodes actually parametrize or name (not recomputed from the rule)."""
    named = [
        case
        for function in (
            ui.test_t30_continue_after_policy_change_takes_a_new_snapshot,
            ui.test_t31_strict_ollama_refusal_precedes_attestation,
        )
        for case in ("G11-T-30", "G11-T-31")
        if (inspect.getdoc(function) or "").startswith(case)
    ]
    return [
        *unit.A_IDS,
        *unit.C_IDS,
        *unit.C_PENDING_IDS,
        *unit.T_IDS,
        *integration.T_IDS,
        *ui.UA_IDS,
        *named,
    ]


def test_full_amended_denominator() -> None:
    every = [case for family in FAMILIES for case in ids(family)]
    assert len(every) == len(set(every)) == 32_799
    assert sum(size for _, size in FAMILIES.values()) == 32_772 + 24 + 3


def test_p11a_share_has_no_missing_duplicate_or_extra() -> None:
    rule = {FAMILIES[family][0].format(n) for family, numbers in P11A_RULE.items() for n in numbers}
    nodes = declared()
    missing = rule - set(nodes)
    extra = set(nodes) - rule
    duplicate = len(nodes) - len(set(nodes))
    assert (len(rule), len(missing), duplicate, len(extra)) == (206, 0, 0, 0)
    every = {case for family in FAMILIES for case in ids(family)}
    assert len(every - rule) == 32_593  # G-P11b, not run or counted by this unit


def test_family_tuples_match_their_ids() -> None:
    assert len(unit.A) == len(unit.A_IDS) and len(ui.UA) == len(ui.UA_IDS)
    assert len(unit.C) == len(unit.C_IDS) and len(unit.C_PENDING) == len(unit.C_PENDING_IDS)
    assert ui.UA == list(product(unit.POLICIES, unit.KINDS, unit.BACKENDS, ui.STAGES))


def test_request_digest_separates_every_static_field() -> None:
    """Auxiliary: the captured snapshot identity distinguishes each field it carries."""
    requests = [
        ResourceRequest(kind, backend, policy, priority=priority)
        for (policy, kind, backend), priority in product(unit.A, (0, 1, 2))
    ]
    digests = {request.digest for request in requests}
    assert len(digests) == len(requests) == 108
    base = ResourceRequest("stt", "LOCAL_CT2", "CPU_ONLY")
    variants = [
        ResourceRequest("stt", "LOCAL_CT2", "CPU_ONLY", model_identity="m"),
        ResourceRequest("stt", "LOCAL_CT2", "CPU_ONLY", runtime_identity="m"),
        ResourceRequest("stt", "LOCAL_CT2", "CPU_ONLY", profile_identity="m"),
        ResourceRequest("stt", "LOCAL_CT2", "CPU_ONLY", preferred_gpu="m"),
        ResourceRequest("stt", "LOCAL_CT2", "CPU_ONLY", input_envelope=(("frames", 1),)),
    ]
    assert len({base.digest, *(item.digest for item in variants)}) == 6
