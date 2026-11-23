"""Reviewed, compiled-in pricing only. Empty is intentional; never fetch or load a file."""

from ._core import SecurityError
from .cost import CostCatalog, PriceEntry

_ENTRIES: tuple[PriceEntry, ...] = ()
_EXPECTED_DIGEST = "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"


def load_catalog() -> CostCatalog:
    catalog = CostCatalog(_ENTRIES)
    if catalog.sha256 != _EXPECTED_DIGEST:
        raise SecurityError("COST_QUOTE_MISMATCH")
    if any(
        entry.wire_protocol in {"text-fixture-v1", "audio-fixture-v1", "opaque-fixture-v1"}
        for entry in catalog.entries
    ):
        raise SecurityError("COST_BOUND_UNVERIFIED")
    return catalog
