"""Security state oracles use dummy credentials and exact integer balances only."""

from __future__ import annotations

import ctypes
import io
import os
import socket
import sqlite3
import ssl
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from recoryn.security import (
    ConsentRequest,
    ConsentScope,
    ConsentStore,
    CostLedger,
    CredentialVault,
    SecurityError,
    transport,
    vault,
)
from recoryn.security._core import check_path, endpoint

pytestmark = pytest.mark.unit
URL = "https://api.example.test/v1"


@pytest.mark.parametrize(
    "bad",
    (
        "http://api.example.test/v1",
        "ftp://api.example.test/v1",
        "https://u:p@api.example.test/v1",
        "https://api.example.test/v1?key=secret",
        "https://api.example.test/v1#fragment",
        "https://169.254.169.254/",
        "https://10.0.0.1/",
        "https://[fe80::1]/",
        "https://localhost/",
        "https://api.example.test/%0dheader",
        "https://api.example.test/v1\n",
        "https://api.example.test:0/",
    ),
)
def test_endpoint_rejection_performs_no_resolution(
    bad: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Endpoint parsing must not resolve DNS")

    monkeypatch.setattr("socket.getaddrinfo", forbidden)
    with pytest.raises(SecurityError, match="INVALID_ENDPOINT"):
        endpoint(bad)


def test_expiring_consent_is_exact_and_invalid_after_restart(tmp_path: Path) -> None:
    clock = [1000.0]
    db = tmp_path / "policy.sqlite"
    with ConsentStore(db, ttl_seconds=10, clock=lambda: clock[0]) as policy:
        assert not policy.allowed(
            "provider",
            URL,
            "audio",
            scope=ConsentScope.library(),
            request=_fixture_request(policy, "session", "stt", 0),
        )
        policy.grant(
            provider_id="provider",
            endpoint=URL,
            data_type="audio",
            capability="stt",
            scope=_fixture_grant_scope(policy),
            policy_version=2,
        )
        assert policy.allowed(
            "provider",
            URL,
            "audio",
            scope=ConsentScope.library(),
            request=_fixture_request(policy, "session", "stt", 0),
        )
        for provider, target, data_type in (
            ("other", URL, "audio"),
            ("provider", URL + "/", "audio"),
            ("provider", URL, "text"),
        ):
            assert not policy.allowed(
                provider,
                target,
                data_type,
                scope=ConsentScope.library(),
                request=_fixture_request(policy, "session", "stt", 0),
            )
        clock[0] = 1010
        assert not policy.allowed(
            "provider",
            URL,
            "audio",
            scope=ConsentScope.library(),
            request=_fixture_request(policy, "session", "stt", 0),
        )
        policy.grant(
            "provider",
            URL,
            "audio",
            capability="stt",
            scope=_fixture_grant_scope(policy),
            policy_version=2,
        )
    with ConsentStore(db) as restarted:
        assert not restarted.allowed(
            "provider",
            URL,
            "audio",
            scope=ConsentScope.library(),
            request=_fixture_request(restarted, "session", "stt", 0),
        )


def test_epoch_regrant_and_session_revocation_invalidate_permits(tmp_path: Path) -> None:
    with ConsentStore(tmp_path / "p.sqlite") as policy:
        policy.grant(
            "provider",
            URL,
            "audio",
            capability="stt",
            scope=_fixture_grant_scope(policy),
            policy_version=2,
        )
        policy.bind_session("session")
        permit = policy.permit(
            "provider",
            URL,
            "audio",
            "a" * 64,
            scope=ConsentScope.library(),
            request=_fixture_request(policy, "session", "stt", 0),
            expected_grant=_fixture_binding(policy, "provider", URL, "audio", "session", "stt", 0),
        )
        policy.validate(permit)
        policy.revoke(
            "provider",
            URL,
            "audio",
            capability="stt",
            scope=ConsentScope.library(),
            policy_version=2,
        )
        policy.grant(
            "provider",
            URL,
            "audio",
            capability="stt",
            scope=_fixture_grant_scope(policy),
            policy_version=2,
        )
        with pytest.raises(SecurityError):
            policy.validate(permit)
        permit = policy.permit(
            "provider",
            URL,
            "audio",
            "a" * 64,
            scope=ConsentScope.library(),
            request=_fixture_request(policy, "session", "stt", 0),
            expected_grant=_fixture_binding(policy, "provider", URL, "audio", "session", "stt", 0),
        )
        policy.revoke_session("session")
        with pytest.raises(SecurityError, match="SESSION_REVOKED"):
            policy.validate(permit)
        with pytest.raises(SecurityError):
            policy.bind_session("session")


def test_loopback_needs_explicit_verified_model_approval(tmp_path: Path) -> None:
    target = "http://127.0.0.1:11434/api/generate"
    with ConsentStore(tmp_path / "p.sqlite") as policy:
        with pytest.raises(SecurityError, match="LOCAL_EXECUTION_UNVERIFIED"):
            policy.grant(
                "ollama",
                target,
                "text",
                capability="stt",
                scope=_fixture_grant_scope(policy),
                policy_version=2,
            )
        policy.approve_local_endpoint(target, "a" * 64)
        policy.grant(
            "ollama",
            target,
            "text",
            capability="stt",
            scope=_fixture_grant_scope(policy),
            policy_version=2,
        )
        assert policy.allowed(
            "ollama",
            target,
            "text",
            scope=ConsentScope.library(),
            request=_fixture_request(policy, "session", "stt", 0),
        )
        assert not policy.allowed(
            "ollama",
            target + "x",
            "text",
            scope=ConsentScope.library(),
            request=_fixture_request(policy, "session", "stt", 0),
        )


def test_cost_unknown_restart_settlement_and_idempotency(tmp_path: Path) -> None:
    db = tmp_path / "library.sqlite"
    with CostLedger(db) as ledger:
        reservation = ledger.reserve("provider", "request", 60, 100)
        assert ledger.reserve("provider", "request", 60, 100) == reservation
        ledger.mark_unknown(reservation)
        ledger.mark_unknown(reservation)
        with pytest.raises(SecurityError, match="RESERVATION_MAY_BE_SENT"):
            ledger.release(reservation)
    with CostLedger(db) as restarted:
        assert restarted.snapshot("provider") == {
            "confirmed": 0,
            "reserved": 0,
            "unknown_exposure": 60,
            "available": 40,
            "limit": 100,
        }
        restarted.settle(reservation, 40)
        restarted.settle(reservation, 40)
        assert restarted.snapshot("provider")["available"] == 60
        with pytest.raises(SecurityError, match="SETTLEMENT_CONFLICT"):
            restarted.settle(reservation, 39)
        second = restarted.reserve("provider", "second", 60, 100)
        with pytest.raises(SecurityError, match="BUDGET_EXCEEDED"):
            restarted.reserve("provider", "third", 1, 100)
        restarted.release(second)
        restarted.release(second)
        assert restarted.snapshot("provider")["reserved"] == 0


@pytest.mark.parametrize("amount", (-1, True, 1.5, "1", 2**63, None))
def test_cost_rejects_non_integer_or_out_of_range_amount(tmp_path: Path, amount: Any) -> None:
    with CostLedger(tmp_path / "l.sqlite") as ledger:
        with pytest.raises(SecurityError, match="INVALID_AMOUNT"):
            ledger.reserve("p", "r", amount, 100)


def test_cost_concurrent_reservations_have_one_winner(tmp_path: Path) -> None:
    db = tmp_path / "l.sqlite"
    with CostLedger(db) as first, CostLedger(db) as second:

        def reserve(index: int) -> bool:
            try:
                (first if index % 2 else second).reserve("p", f"r{index}", 7, 10)
                return True
            except SecurityError as error:
                assert error.code == "BUDGET_EXCEEDED"
                return False

        with ThreadPoolExecutor(max_workers=8) as workers:
            assert sum(workers.map(reserve, range(16))) == 1
        assert first.snapshot("p")["reserved"] == 7


def test_ledger_detects_database_rollback_against_witness(tmp_path: Path) -> None:
    db, backup = tmp_path / "l.sqlite", tmp_path / "old.sqlite"
    with CostLedger(db) as ledger:
        with (
            closing(sqlite3.connect(db)) as source,
            closing(sqlite3.connect(backup)) as destination,
        ):
            source.backup(destination)
        ledger.reserve("p", "r", 80, 100)
    db.write_bytes(backup.read_bytes())
    with pytest.raises(SecurityError, match="LEDGER_ROLLBACK_DETECTED"):
        CostLedger(db)


@pytest.mark.parametrize("damage", ("missing", "corrupt", "database_missing"))
def test_ledger_fails_closed_for_missing_or_corrupt_witness(tmp_path: Path, damage: str) -> None:
    db = tmp_path / "l.sqlite"
    with CostLedger(db) as ledger:
        ledger.reserve("p", "r", 80, 100)
    witness = db.with_name(db.name + ".cost-witness")
    if damage == "missing":
        witness.unlink()
    elif damage == "corrupt":
        witness.write_bytes(b"{")
    else:
        db.unlink()
    with pytest.raises(SecurityError, match="LEDGER_ROLLBACK_DETECTED"):
        CostLedger(db)


class MemoryVault:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}
        self.fail = False

    def write(self, target: str, secret: bytes) -> None:
        if self.fail:
            raise OSError("B14-CANARY-DO-NOT-LOG")
        self.values[target] = secret

    def read(self, target: str) -> bytes | None:
        if self.fail:
            raise OSError("B14-CANARY-DO-NOT-LOG")
        return self.values.get(target)

    def delete(self, target: str) -> None:
        if self.fail:
            raise OSError("B14-CANARY-DO-NOT-LOG")
        self.values.pop(target, None)


def test_vault_fake_roundtrip_and_safe_failure_has_no_plaintext_fallback(tmp_path: Path) -> None:
    backend = MemoryVault()
    credentials = CredentialVault(backend=backend, namespace="B14-test-only")
    assert not backend.values
    assert credentials.get("provider") is None
    credentials.set("provider", "B14-CANARY-DO-NOT-LOG")
    assert credentials.get("provider") == "B14-CANARY-DO-NOT-LOG"
    assert all("provider" not in target and "CANARY" not in target for target in backend.values)
    backend.fail = True
    operations: tuple[Callable[[], object], ...] = (
        lambda: credentials.set("provider", "dummy"),
        lambda: credentials.get("provider"),
        lambda: credentials.delete("provider"),
    )
    for operation in operations:
        with pytest.raises(SecurityError) as error:
            operation()
        assert "CANARY" not in str(error.value)
    assert list(tmp_path.iterdir()) == []
    backend.fail = False
    credentials.delete("provider")
    credentials.delete("provider")
    assert credentials.get("provider") is None


def test_native_wincred_struct_and_buffer_free_use_only_fake_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = b"B14-FAKE-NATIVE-KEY"
    buffer = (ctypes.c_ubyte * len(secret)).from_buffer_copy(secret)
    credential = vault._Credential()
    credential.CredentialBlobSize = len(secret)
    credential.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
    freed: list[bool] = []

    class FakeAPI:
        def CredWriteW(self, pointer: Any, flags: int) -> int:
            item = ctypes.cast(pointer, ctypes.POINTER(vault._Credential)).contents
            assert item.Type == 1 and item.Persist == 2 and flags == 0
            assert ctypes.string_at(item.CredentialBlob, item.CredentialBlobSize) == secret
            return 1

        def CredReadW(self, target: str, kind: int, flags: int, output: Any) -> int:
            assert kind == 1 and flags == 0
            ctypes.cast(output, ctypes.POINTER(ctypes.POINTER(vault._Credential)))[0] = (
                ctypes.pointer(credential)
            )
            return 1

        def CredDeleteW(self, target: str, kind: int, flags: int) -> int:
            return 1

        def CredFree(self, pointer: Any) -> None:
            freed.append(True)

    monkeypatch.setattr(vault, "_load_api", lambda: FakeAPI())
    credentials = CredentialVault(namespace="B14-test-only")
    credentials.set("fake", secret.decode())
    assert credentials.get("fake") == secret.decode()
    credentials.delete("fake")
    assert freed == [True]


@pytest.mark.parametrize("address", ("127.0.0.1", "169.254.169.254", "192.168.1.1", "::1"))
def test_dns_rebinding_to_private_address_is_rejected_before_socket(
    monkeypatch: pytest.MonkeyPatch, address: str
) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", (address, 443))])

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("A denied DNS address must not create a socket")

    monkeypatch.setattr(socket, "socket", forbidden)
    with pytest.raises(SecurityError, match="DNS_TARGET_DENIED"):
        transport._socket(endpoint(URL), 1)


@pytest.mark.parametrize("status", (200, 302, 401))
def test_native_http_uses_checked_target_tls_and_never_follows_redirect(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    payload = f"HTTP/1.1 {status} Result\r\nContent-Length: 2\r\nLocation: https://private.invalid/secret\r\n\r\nOK".encode()
    sent: list[bytes] = []
    connected: list[object] = []
    tls_hosts: list[str] = []

    class Socket:
        def settimeout(self, value: float) -> None:
            assert value > 0

        def connect(self, address: object) -> None:
            connected.append(address)

        def sendall(self, data: bytes) -> None:
            sent.append(data)

        def makefile(self, mode: str) -> io.BytesIO:
            return io.BytesIO(payload)

        def close(self) -> None:
            pass

    raw = Socket()

    class TLS:
        def wrap_socket(self, stream: object, *, server_hostname: str) -> Socket:
            tls_hosts.append(server_hostname)
            return raw

    monkeypatch.setenv("HTTPS_PROXY", "http://must-not-use.invalid:8080")
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", ("1.1.1.1", 443))])
    monkeypatch.setattr(socket, "socket", lambda *a, **kw: raw)
    monkeypatch.setattr(ssl, "create_default_context", lambda: TLS())
    connection = transport.DirectTransport().open(
        endpoint(URL), {"content-type": "text/plain"}, 4, 1
    )
    try:
        connection.write(b"body", 1)
        if status == 200:
            assert connection.read(3, 1) == b"OK"
            assert connection.read(3, 1) == b""
        else:
            with pytest.raises(
                SecurityError, match="REDIRECT_DENIED" if status == 302 else "REMOTE_REJECTED"
            ):
                connection.read(3, 1)
    finally:
        connection.close()
    assert connected == [("1.1.1.1", 443)]
    assert tls_hosts == ["api.example.test"]
    assert b"POST /v1 HTTP/1.1" in b"".join(sent)
    assert b"body" in b"".join(sent)


def test_consent_clock_rollback_and_stale_execution_fail_closed(tmp_path: Path) -> None:
    clock = [1000.0]
    db = tmp_path / "p.sqlite"
    with ConsentStore(db, clock=lambda: clock[0]) as policy:
        policy.grant(
            "p",
            URL,
            "audio",
            capability="stt",
            scope=_fixture_grant_scope(policy),
            policy_version=2,
        )
        clock[0] = 999
        assert not policy.allowed(
            "p",
            URL,
            "audio",
            scope=ConsentScope.library(),
            request=_fixture_request(policy, "session", "stt", 0),
        )
        with pytest.raises(SecurityError, match="CONSENT_CLOCK_INVALID"):
            policy.grant(
                "p",
                URL,
                "audio",
                capability="stt",
                scope=_fixture_grant_scope(policy),
                policy_version=2,
            )
        clock[0] = 1001
        with ConsentStore(db):
            assert not policy.allowed(
                "p",
                URL,
                "audio",
                scope=ConsentScope.library(),
                request=_fixture_request(policy, "session", "stt", 0),
            )


def test_native_vault_missing_and_failed_results_never_use_real_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailedAPI:
        def CredReadW(self, *args: object) -> int:
            return 0

        def CredDeleteW(self, *args: object) -> int:
            return 0

        def CredWriteW(self, *args: object) -> int:
            return 0

    monkeypatch.setattr(vault, "_load_api", lambda: FailedAPI())
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 1168)
    credentials = CredentialVault(namespace="B14-test-only")
    assert credentials.get("p") is None
    credentials.delete("p")
    with pytest.raises(SecurityError, match="VAULT_WRITE_FAILED"):
        credentials.set("p", "dummy")
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 5)
    with pytest.raises(SecurityError, match="VAULT_READ_FAILED"):
        credentials.get("p")
    with pytest.raises(SecurityError, match="VAULT_DELETE_FAILED"):
        credentials.delete("p")


@pytest.mark.parametrize("ttl", (0, -1, True, float("nan"), "1"))
def test_invalid_consent_ttl_never_creates_storage(tmp_path: Path, ttl: Any) -> None:
    with pytest.raises(SecurityError, match="INVALID_TIMEOUT"):
        ConsentStore(tmp_path / "policy.sqlite", ttl_seconds=ttl)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("value", ("", "..", "../file", "contains space", 42))
def test_identifiers_are_not_paths_or_free_text(tmp_path: Path, value: Any) -> None:
    with ConsentStore(tmp_path / "p.sqlite") as policy:
        with pytest.raises(SecurityError, match="INVALID_IDENTIFIER"):
            policy.grant(
                value,
                URL,
                "audio",
                capability="stt",
                scope=_fixture_grant_scope(policy),
                policy_version=2,
            )


def test_local_attestation_and_send_permit_expire_independently(tmp_path: Path) -> None:
    clock = [1000.0]
    with ConsentStore(tmp_path / "p.sqlite", clock=lambda: clock[0]) as policy:
        target = "http://127.0.0.1:11434/api/chat"
        with pytest.raises(SecurityError, match="LOCAL_EXECUTION_UNVERIFIED"):
            policy.approve_local_endpoint(URL, "a" * 64)
        policy.approve_local_endpoint(target, "a" * 64, ttl_seconds=5)
        policy.grant(
            "ollama",
            target,
            "transcript",
            capability="stt",
            scope=_fixture_grant_scope(policy),
            policy_version=2,
        )
        clock[0] += 6
        assert not policy.allowed(
            "ollama",
            target,
            "transcript",
            scope=ConsentScope.library(),
            request=_fixture_request(policy, "session", "stt", 0),
        )
        policy.grant(
            "p",
            URL,
            "audio",
            capability="stt",
            scope=_fixture_grant_scope(policy),
            policy_version=2,
        )
        permit = policy.permit(
            "p",
            URL,
            "audio",
            "a" * 64,
            scope=ConsentScope.library(),
            request=_fixture_request(policy, "session", "stt", 0),
            expected_grant=_fixture_binding(policy, "p", URL, "audio", "session", "stt", 0),
        )
        clock[0] += 31
        with pytest.raises(SecurityError, match="PERMIT_REVOKED"):
            policy.validate(permit)
        policy.close()
        policy.close()
        assert not policy.allowed(
            "p",
            URL,
            "audio",
            scope=ConsentScope.library(),
            request=_fixture_request(policy, "session", "stt", 0),
        )


def test_ledger_limit_changes_missing_ids_and_conflicting_request_are_safe(tmp_path: Path) -> None:
    with CostLedger(tmp_path / "p.sqlite") as ledger:
        assert ledger.snapshot("p")["available"] == 0
        reservation = ledger.reserve("p", "r", 80, 100)
        with pytest.raises(SecurityError, match="RESERVATION_CONFLICT"):
            ledger.reserve("p", "r", 81, 100)
        with pytest.raises(SecurityError, match="BUDGET_POLICY_CHANGED"):
            ledger.reserve("p", "r", 80, 101)
        with pytest.raises(SecurityError, match="RESERVATION_NOT_FOUND"):
            ledger.release("missing")
        with pytest.raises(SecurityError, match="RESERVATION_NOT_DISPATCHABLE"):
            ledger.check_reservation(reservation, "other")
        ledger.set_limit("p", 10)
        with pytest.raises(SecurityError, match="BUDGET_EXCEEDED"):
            ledger.check_reservation(reservation, "p")
        ledger.set_limit("p", 100)
        ledger.check_reservation(reservation, "p")
        ledger.release(reservation)
        with pytest.raises(SecurityError, match="RESERVATION_CONFLICT"):
            ledger.mark_unknown(reservation)
        with pytest.raises(SecurityError, match="RESERVATION_CONFLICT"):
            ledger.settle(reservation, 20)
        assert ledger.reservations("p")[0]["state"] == "RELEASED"
        ledger.close()
        with pytest.raises(SecurityError, match="LEDGER_CLOSED"):
            ledger.snapshot("p")


def test_interrupted_ledger_witness_blocks_further_spending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with CostLedger(tmp_path / "p.sqlite") as ledger:
        original = ledger._write_witness

        def fail_after_witness() -> None:
            original()
            raise OSError("B14-CANARY-WITNESS-IO")

        monkeypatch.setattr(ledger, "_write_witness", fail_after_witness)
        with pytest.raises(SecurityError, match="SECURITY_STATE_UNAVAILABLE"):
            ledger.reserve("p", "r", 80, 100)
        with pytest.raises(SecurityError, match="LEDGER_ROLLBACK_DETECTED"):
            ledger.snapshot("p")


@pytest.mark.parametrize("constructor", (ConsentStore, CostLedger))
def test_future_schema_is_not_mutated(tmp_path: Path, constructor: Any) -> None:
    db = tmp_path / "future.sqlite"
    with closing(sqlite3.connect(db)) as connection:
        connection.execute("PRAGMA user_version=99")
    before = db.read_bytes()
    with pytest.raises(SecurityError, match="UNSUPPORTED_SCHEMA"):
        constructor(db)
    assert db.read_bytes() == before


@pytest.mark.parametrize("secret", ("", "contains\0nul", "x" * 2561, "\ud800"))
def test_vault_rejects_invalid_values_without_fallback(secret: str) -> None:
    backend = MemoryVault()
    credentials = CredentialVault(backend=backend)
    with pytest.raises(SecurityError):
        credentials.set("p", secret)
    assert not backend.values


def test_native_loader_declares_wincred_abi_without_loading_os_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Function:
        argtypes: list[object]
        restype: object

        def __call__(self, *args: object) -> int:
            pytest.fail("ABI inspection must not call an OS credential function")

    class API:
        CredWriteW, CredReadW, CredDeleteW, CredFree = (
            Function(),
            Function(),
            Function(),
            Function(),
        )

    fake = API()
    monkeypatch.setattr(ctypes, "WinDLL", lambda *a, **kw: fake)
    assert vault._load_api() is fake
    assert len(fake.CredWriteW.argtypes) == 2
    assert len(fake.CredReadW.argtypes) == 4
    assert fake.CredFree.argtypes == [ctypes.c_void_p]
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        assert ctypes.sizeof(vault._Credential) == 80
    with monkeypatch.context() as patch:
        patch.setattr(os, "name", "posix")
        with pytest.raises(SecurityError, match="VAULT_UNAVAILABLE"):
            vault._load_api()


def test_security_path_rejects_unc_and_hardlink_without_touching_source(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite"
    source.write_bytes(b"untouched")
    alias = tmp_path / "alias.sqlite"
    os.link(source, alias)
    with pytest.raises(SecurityError, match="UNSAFE_PATH"):
        ConsentStore(alias)
    assert source.read_bytes() == alias.read_bytes() == b"untouched"
    with pytest.raises(SecurityError, match="UNSAFE_PATH"):
        check_path(Path(r"\\not-contacted.invalid\share\state.sqlite"))


def test_reparse_path_is_rejected_from_file_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "untrusted"
    original = Path.lstat

    class Reparse:
        st_mode = 0o040755
        st_file_attributes = 0x400

    def metadata(path: Path) -> Any:
        return Reparse() if path == target else original(path)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "lstat", metadata)
        with pytest.raises(SecurityError, match="UNSAFE_PATH"):
            check_path(target / "state.sqlite")


def test_policy_contention_has_bounded_safe_failure_and_releases_fd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import msvcrt

    with ConsentStore(tmp_path / "security.sqlite") as policy:
        instants = iter((0.0, 0.0, 11.0))

        def busy(*args: object) -> None:
            raise OSError("B14-LOCK-CANARY")

        with monkeypatch.context() as patch:
            patch.setattr(msvcrt, "locking", busy)
            patch.setattr("recoryn.security._core.time.monotonic", lambda: next(instants))
            with pytest.raises(SecurityError, match="POLICY_BUSY"):
                policy.grant(
                    "p",
                    URL,
                    "audio",
                    capability="stt",
                    scope=ConsentScope.library(),
                    policy_version=2,
                )
        # The failed acquisition left no lock/depth that can bypass later policy checks.
        policy.grant(
            "p",
            URL,
            "audio",
            capability="stt",
            scope=_fixture_grant_scope(policy),
            policy_version=2,
        )
        assert policy.allowed(
            "p",
            URL,
            "audio",
            scope=ConsentScope.library(),
            request=_fixture_request(policy, "session", "stt", 0),
        )


@pytest.mark.parametrize("deletion", ("intent", "pending", "tombstone"))
def test_session_deletion_evidence_blocks_already_issued_permit(
    tmp_path: Path, deletion: str
) -> None:
    db = tmp_path / "security.sqlite"
    with ConsentStore(db) as policy:
        policy.grant(
            "p",
            URL,
            "audio",
            capability="stt",
            scope=_fixture_grant_scope(policy),
            policy_version=2,
        )
        policy.bind_session("session")
        token = policy.permit(
            "p",
            URL,
            "audio",
            "0" * 64,
            scope=ConsentScope.library(),
            request=_fixture_request(policy, "session", "stt", 0),
            expected_grant=_fixture_binding(policy, "p", URL, "audio", "session", "stt", 0),
        )
        if deletion == "tombstone":
            with closing(sqlite3.connect(db)) as connection:
                connection.execute("CREATE TABLE deleted_sessions(session_id TEXT PRIMARY KEY)")
                connection.execute("INSERT INTO deleted_sessions VALUES('session')")
                connection.commit()
        else:
            journal = tmp_path / "deletion-journal"
            journal.mkdir()
            (journal / ("session.json" if deletion == "intent" else ".tmp-delete")).write_bytes(
                b"{}"
            )
        with pytest.raises(SecurityError, match="SESSION_REVOKED"):
            policy.validate(token)
        with pytest.raises(SecurityError, match="INVALID_SESSION_GENERATION"):
            policy.bind_session("another", True)


def test_incompatible_consent_schema_fails_safely(tmp_path: Path) -> None:
    db = tmp_path / "security.sqlite"
    with closing(sqlite3.connect(db)) as connection:
        connection.execute("CREATE TABLE security_execution(unexpected TEXT)")
    with pytest.raises(SecurityError, match="SECURITY_STATE_UNAVAILABLE"):
        ConsentStore(db)


def test_witness_oversize_and_failed_replacement_are_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "security.sqlite"
    with CostLedger(db) as ledger:

        def disk_full(*args: object) -> None:
            raise OSError("B14-DISK-CANARY")

        with monkeypatch.context() as patch:
            patch.setattr("recoryn.security.ledger.os.replace", disk_full)
            with pytest.raises(SecurityError, match="SECURITY_STATE_UNAVAILABLE"):
                ledger.reserve("p", "r", 80, 100)
        assert not tuple(tmp_path.glob("*.cost-witness.*"))
        assert ledger.snapshot("p")["reserved"] == 0
        ledger.reserve("p", "r", 80, 100)
    witness = db.with_name(db.name + ".cost-witness")
    witness.write_bytes(b" " * 4097)
    with pytest.raises(SecurityError, match="LEDGER_ROLLBACK_DETECTED"):
        CostLedger(db)


def test_witness_with_lost_cost_schema_is_not_treated_as_new_budget(tmp_path: Path) -> None:
    db = tmp_path / "security.sqlite"
    with CostLedger(db) as ledger:
        ledger.reserve("p", "r", 80, 100)
    with closing(sqlite3.connect(db)) as connection:
        connection.execute("DELETE FROM security_cost_meta")
        connection.commit()
    with pytest.raises(SecurityError, match="LEDGER_ROLLBACK_DETECTED"):
        CostLedger(db)


@pytest.mark.parametrize("malformed", (b"", b"x\0y", b"x" * 2561, b"\xff"))
def test_invalid_vault_read_values_never_escape_or_persist(malformed: bytes) -> None:
    backend = MemoryVault()
    credentials = CredentialVault(backend=backend)
    backend.read = lambda target: malformed  # type: ignore[method-assign]
    with pytest.raises(SecurityError, match="VAULT_(INVALID_VALUE|READ_FAILED)"):
        credentials.get("p")


def test_native_invalid_blob_frees_native_result(monkeypatch: pytest.MonkeyPatch) -> None:
    malformed = vault._Credential()
    malformed.CredentialBlobSize = 4  # Nonempty size with a NULL payload must never be read.
    freed: list[bool] = []

    class API:
        def CredReadW(self, target: str, kind: int, flags: int, output: Any) -> int:
            ctypes.cast(output, ctypes.POINTER(ctypes.POINTER(vault._Credential)))[0] = (
                ctypes.pointer(malformed)
            )
            return 1

        def CredFree(self, pointer: Any) -> None:
            freed.append(True)

    monkeypatch.setattr(vault, "_load_api", lambda: API())
    with pytest.raises(SecurityError, match="VAULT_INVALID_VALUE"):
        CredentialVault(namespace="B14-test-only").get("p")
    assert freed == [True]


@pytest.mark.parametrize("failure", ("empty_dns", "connect", "tls"))
def test_native_connection_failures_close_socket_without_retrying_http(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    closed: list[bool] = []
    connections: list[object] = []

    class Socket:
        def settimeout(self, value: float) -> None:
            pass

        def connect(self, address: object) -> None:
            connections.append(address)
            if failure == "connect":
                raise OSError("B14-CONNECT-CANARY")

        def close(self) -> None:
            closed.append(True)

    class TLS:
        def wrap_socket(self, *args: object, **kwargs: object) -> None:
            raise OSError("B14-TLS-CANARY")

    addresses = [] if failure == "empty_dns" else [(2, 1, 6, "", ("1.1.1.1", 443))]
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: addresses)
    monkeypatch.setattr(socket, "socket", lambda *a, **kw: Socket())
    monkeypatch.setattr(ssl, "create_default_context", lambda: TLS())
    with pytest.raises((SecurityError, OSError)):
        transport.DirectTransport().open(endpoint(URL), {}, 4, 1)
    assert connections == ([] if failure == "empty_dns" else [("1.1.1.1", 443)])
    assert closed == ([] if failure == "empty_dns" else [True])


def test_frozen_grant_bindings_do_not_expand_or_revive(tmp_path: Path) -> None:
    from dataclasses import replace

    with ConsentStore(tmp_path / "security.sqlite") as policy:
        assert (
            policy.capture_bindings(
                "p",
                URL,
                ("audio", "transcript"),
                scope=ConsentScope.library(),
                request=_fixture_request(policy, "session", "stt", 0),
            )
            == ()
        )
        policy.grant(
            "p",
            URL,
            "audio",
            capability="stt",
            scope=_fixture_grant_scope(policy),
            policy_version=2,
        )
        captured = policy.capture_bindings(
            "p",
            URL,
            ("audio", "transcript"),
            scope=ConsentScope.library(),
            request=_fixture_request(policy, "session", "stt", 0),
        )
        assert len(captured) == 1 and captured[0].data_type == "audio"
        policy.validate_binding(captured[0])
        policy.permit(
            "p",
            URL,
            "audio",
            "0" * 64,
            expected_grant=captured[0],
            scope=ConsentScope.library(),
            request=_fixture_request(policy, "session", "stt", 0),
        )
        policy.grant(
            "p",
            URL,
            "transcript",
            capability="stt",
            scope=_fixture_grant_scope(policy),
            policy_version=2,
        )
        assert len(captured) == 1
        policy.revoke(
            "p", URL, "audio", capability="stt", scope=ConsentScope.library(), policy_version=2
        )
        policy.grant(
            "p",
            URL,
            "audio",
            capability="stt",
            scope=_fixture_grant_scope(policy),
            policy_version=2,
        )
        with pytest.raises(SecurityError, match="PERMIT_REVOKED"):
            policy.validate_binding(captured[0])
        with pytest.raises(SecurityError, match="PERMIT_REVOKED"):
            policy.permit(
                "p",
                URL,
                "audio",
                "0" * 64,
                expected_grant=captured[0],
                scope=ConsentScope.library(),
                request=_fixture_request(policy, "session", "stt", 0),
            )
        with pytest.raises(SecurityError, match="PERMIT_REVOKED"):
            policy.validate_binding(replace(captured[0], execution_id="different"))
        for scopes in ((), ("audio", "audio")):
            with pytest.raises(SecurityError, match="INVALID_CONSENT_SCOPES"):
                policy.capture_bindings(
                    "p",
                    URL,
                    scopes,
                    scope=ConsentScope.library(),
                    request=_fixture_request(policy, "session", "stt", 0),
                )
        policy.close()
        with pytest.raises(SecurityError, match="CONSENT_STORE_CLOSED"):
            policy.capture_bindings(
                "p",
                URL,
                ("audio",),
                scope=ConsentScope.library(),
                request=_fixture_request(policy, "session", "stt", 0),
            )


# The older tests exercise revocation/transport, with an explicitly chosen library
# grant. G02's separate cases exercise the default session-only permission.
def _fixture_request(
    policy: ConsentStore, session_id: str = "session", capability: str = "stt", generation: int = 0
) -> ConsentRequest:
    try:
        policy.bind_session(session_id, generation)
    except SecurityError:
        pass  # Registration grants nothing; the tested API still checks the fence.
    return ConsentRequest(session_id, generation, capability, 2)


def _fixture_grant_scope(policy: ConsentStore) -> ConsentScope:
    _fixture_request(policy)
    return ConsentScope.library()


def _fixture_binding(
    policy: ConsentStore,
    provider: str,
    endpoint: str,
    data_type: str,
    session_id: str = "session",
    capability: str = "stt",
    generation: int = 0,
):
    request = _fixture_request(policy, session_id, capability, generation)
    bindings = policy.capture_bindings(
        provider, endpoint, (data_type,), scope=ConsentScope.library(), request=request
    )
    if not bindings:
        raise SecurityError("CONSENT_REQUIRED")
    return bindings[0]
