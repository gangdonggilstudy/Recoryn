"""Explicit consent, revocable transport, Windows secrets, and durable integer budgets."""

from ._core import SecurityError
from .consent import (
    CONSENT_POLICY_VERSION,
    ConsentBinding,
    ConsentRequest,
    ConsentScope,
    ConsentStore,
    SendPermit,
)
from .gateway import Gateway
from .ledger import CostLedger
from .transport import Connection, Transport
from .vault import CredentialVault

__all__ = [
    "Connection",
    "ConsentStore",
    "ConsentBinding",
    "ConsentRequest",
    "ConsentScope",
    "CONSENT_POLICY_VERSION",
    "CostLedger",
    "CredentialVault",
    "Gateway",
    "SecurityError",
    "SendPermit",
    "Transport",
]
