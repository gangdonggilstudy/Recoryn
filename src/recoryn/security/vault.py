"""Lazy Windows Credential Manager binding; no plaintext fallback or enumeration.

Native contract: https://learn.microsoft.com/en-us/windows/win32/api/wincred/ns-wincred-credentialw
https://learn.microsoft.com/en-us/windows/win32/api/wincred/nf-wincred-credreadw
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from typing import Any, Protocol

from ._core import SecurityError, digest, identifier
from ._secrets import register_secret


class VaultBackend(Protocol):
    def write(self, target: str, secret: bytes) -> None: ...
    def read(self, target: str) -> bytes | None: ...
    def delete(self, target: str) -> None: ...


class _Attribute(ctypes.Structure):
    _fields_ = [
        ("Keyword", wintypes.LPWSTR),
        ("Flags", wintypes.DWORD),
        ("ValueSize", wintypes.DWORD),
        ("Value", ctypes.POINTER(ctypes.c_ubyte)),
    ]


class _Credential(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.POINTER(_Attribute)),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


def _load_api() -> Any:
    if os.name != "nt":
        raise SecurityError("VAULT_UNAVAILABLE")
    api = ctypes.WinDLL("Advapi32", use_last_error=True)
    pointer = ctypes.POINTER(_Credential)
    api.CredWriteW.argtypes, api.CredWriteW.restype = [pointer, wintypes.DWORD], wintypes.BOOL
    api.CredReadW.argtypes, api.CredReadW.restype = (
        [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(pointer)],
        wintypes.BOOL,
    )
    api.CredDeleteW.argtypes, api.CredDeleteW.restype = (
        [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD],
        wintypes.BOOL,
    )
    api.CredFree.argtypes, api.CredFree.restype = [ctypes.c_void_p], None
    return api


class WindowsCredentialBackend:
    def write(self, target: str, secret: bytes) -> None:
        api = _load_api()
        buffer = (ctypes.c_ubyte * len(secret)).from_buffer_copy(secret)
        credential = _Credential()
        credential.Type, credential.TargetName, credential.Persist = 1, target, 2
        credential.CredentialBlobSize = len(secret)
        credential.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
        try:
            if not api.CredWriteW(ctypes.byref(credential), 0):
                raise SecurityError("VAULT_WRITE_FAILED")
        finally:
            ctypes.memset(buffer, 0, len(secret))

    def read(self, target: str) -> bytes | None:
        api = _load_api()
        pointer = ctypes.POINTER(_Credential)()
        if not api.CredReadW(target, 1, 0, ctypes.byref(pointer)):
            if ctypes.get_last_error() == 1168:
                return None
            raise SecurityError("VAULT_READ_FAILED")
        try:
            if (
                not pointer
                or not 0 < pointer.contents.CredentialBlobSize <= 2560
                or not pointer.contents.CredentialBlob
            ):
                raise SecurityError("VAULT_INVALID_VALUE")
            return ctypes.string_at(
                pointer.contents.CredentialBlob, pointer.contents.CredentialBlobSize
            )
        finally:
            api.CredFree(pointer)

    def delete(self, target: str) -> None:
        api = _load_api()
        if not api.CredDeleteW(target, 1, 0) and ctypes.get_last_error() != 1168:
            raise SecurityError("VAULT_DELETE_FAILED")


class CredentialVault:
    def __init__(self, *, backend: VaultBackend | None = None, namespace: str = "Recoryn") -> None:
        self._namespace = identifier(namespace)
        self._backend = backend if backend is not None else WindowsCredentialBackend()

    def _target(self, provider_id: str) -> str:
        return self._namespace + "/v1/" + digest(identifier(provider_id).encode("utf-8"))

    def set(self, provider_id: str, secret: str) -> None:
        target = self._target(provider_id)
        if not isinstance(secret, str) or not secret or "\x00" in secret:
            raise SecurityError("VAULT_INVALID_VALUE")
        try:
            value = secret.encode("utf-8")
            if len(value) > 2560:
                raise SecurityError("VAULT_INVALID_VALUE")
            register_secret(secret)
            self._backend.write(target, value)
        except SecurityError:
            raise
        except Exception:
            raise SecurityError("VAULT_WRITE_FAILED") from None

    def get(self, provider_id: str) -> str | None:
        try:
            result = self._backend.read(self._target(provider_id))
            if result is None:
                return None
            if type(result) is not bytes or not 0 < len(result) <= 2560 or b"\0" in result:
                raise SecurityError("VAULT_INVALID_VALUE")
            decoded = result.decode("utf-8")
            register_secret(decoded)
            return decoded
        except SecurityError:
            raise
        except Exception:
            raise SecurityError("VAULT_READ_FAILED") from None

    def delete(self, provider_id: str) -> None:
        try:
            self._backend.delete(self._target(provider_id))
        except SecurityError:
            raise
        except Exception:
            raise SecurityError("VAULT_DELETE_FAILED") from None
