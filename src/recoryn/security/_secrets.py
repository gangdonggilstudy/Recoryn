"""Bounded process-memory redaction hints, never a persistent secret store."""

import threading
from collections import deque
from collections.abc import Sequence

_lock = threading.Lock()
_values: deque[str] = deque(maxlen=256)


def register_secret(secret: str) -> None:
    with _lock:
        if secret and secret not in _values:
            _values.append(secret)


def redact(value: str, extra: Sequence[str] = ()) -> str:
    with _lock:
        secrets = tuple(_values) + tuple(extra)
    for secret in sorted(set(secrets), key=len, reverse=True):
        if secret:
            value = value.replace(secret, "REDACTED")
    return value
