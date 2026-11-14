"""No integration fixture may accidentally contact DNS or a remote service."""

import socket
from collections.abc import Iterator
from typing import NoReturn

import pytest


@pytest.fixture(autouse=True)
def deny_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    attempts: list[str] = []

    def denied(*args: object, **kwargs: object) -> NoReturn:
        attempts.append("network")
        raise AssertionError("P04 tests forbid DNS and network access")

    for name in ("getaddrinfo", "gethostbyname", "gethostbyaddr", "create_connection"):
        monkeypatch.setattr(socket, name, denied)
    for name in ("connect", "connect_ex", "sendto"):
        monkeypatch.setattr(socket.socket, name, denied)
    yield
    assert not attempts, "The tested path attempted network access, even if it caught the error"
