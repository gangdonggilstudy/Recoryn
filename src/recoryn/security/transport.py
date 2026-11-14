"""Bounded direct HTTP; no environment proxy, redirect, retry, or unchecked DNS target.

References: https://docs.python.org/3.13/library/http.client.html
https://docs.python.org/3.13/library/ssl.html#ssl.create_default_context
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
from collections.abc import Mapping
from typing import Protocol

from ._core import Endpoint, SecurityError


class Connection(Protocol):
    def write(self, data: bytes, timeout: float) -> None: ...
    def read(self, limit: int, timeout: float) -> bytes: ...
    def close(self) -> None: ...


class Transport(Protocol):
    def open(
        self, endpoint: Endpoint, headers: Mapping[str, str], body_length: int, timeout: float
    ) -> Connection: ...


def _socket(target: Endpoint, timeout: float) -> socket.socket:
    addresses = socket.getaddrinfo(target.host, target.port, type=socket.SOCK_STREAM)
    if not addresses:
        raise SecurityError("DNS_TARGET_DENIED")
    for _, _, _, _, address in addresses:
        ip = ipaddress.ip_address(address[0])
        if (target.loopback and not ip.is_loopback) or (not target.loopback and not ip.is_global):
            raise SecurityError("DNS_TARGET_DENIED")
    last_error: OSError | None = None
    for family, kind, protocol, _, address in addresses:
        stream = socket.socket(family, kind, protocol)
        try:
            stream.settimeout(timeout)
            stream.connect(address)
            return stream
        except OSError as error:
            last_error = error
            stream.close()
    raise SecurityError("CONNECTION_FAILED") from last_error


class _HttpConnection:
    def __init__(
        self, target: Endpoint, headers: Mapping[str, str], length: int, timeout: float
    ) -> None:
        raw = _socket(target, timeout)
        try:
            stream = (
                ssl.create_default_context().wrap_socket(raw, server_hostname=target.host)
                if target.scheme == "https"
                else raw
            )
            self._client = http.client.HTTPConnection(target.host, target.port, timeout=timeout)
            self._client.sock = stream
            self._client.auto_open = 0
        except BaseException:
            raw.close()
            raise
        self._target, self._headers, self._length = target, dict(headers), length
        self._started = False
        self._response: http.client.HTTPResponse | None = None

    def _timeout(self, timeout: float) -> None:
        if self._client.sock is None:
            raise SecurityError("CONNECTION_CLOSED")
        self._client.sock.settimeout(timeout)

    def write(self, data: bytes, timeout: float) -> None:
        self._timeout(timeout)
        if not self._started:
            self._client.putrequest("POST", self._target.target, skip_accept_encoding=True)
            for name, value in self._headers.items():
                self._client.putheader(name, value)
            self._client.putheader("Content-Length", str(self._length))
            self._client.endheaders()
            self._started = True
        if data:
            self._client.send(data)

    def read(self, limit: int, timeout: float) -> bytes:
        self._timeout(timeout)
        if self._response is None:
            self._response = self._client.getresponse()
            if 300 <= self._response.status < 400:
                raise SecurityError("REDIRECT_DENIED", outcome_known=False)
            if not 200 <= self._response.status < 300:
                raise SecurityError("REMOTE_REJECTED", outcome_known=False)
        return self._response.read1(limit)

    def close(self) -> None:
        self._client.close()


class DirectTransport:
    def open(
        self, endpoint: Endpoint, headers: Mapping[str, str], body_length: int, timeout: float
    ) -> Connection:
        return _HttpConnection(endpoint, headers, body_length, timeout)
