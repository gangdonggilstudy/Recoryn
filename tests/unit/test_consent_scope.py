"""Independent boundaries for the G02 consent contract; no native credentials or I/O egress."""

from __future__ import annotations

import itertools
import shutil
import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from recoryn.security import ConsentRequest, ConsentScope, ConsentStore, CostLedger, SecurityError

URL = "https://scope.example.test/v1"
TIME = list(
    itertools.product(
        ("session", "library"),
        ("stt", "summary", "diarization"),
        ("grant", "permit"),
        (-1, 0, 1),
        (False, True),
    )
)
CASE_IDS = {
    "TIME": [f"G02-TIME-{i:03d}" for i in range(72)],
    "MIG": [f"G02-MIG-{i:02d}" for i in range(1, 13)],
    "TYPE": [f"G02-TYPE-{i:02d}" for i in range(1, 23)],
}


def prepare(
    policy: ConsentStore, scope: ConsentScope, capability: str = "stt"
) -> tuple[ConsentRequest, dict[str, Any]]:
    policy.bind_session("A")
    request = ConsentRequest("A", 0, capability, policy.policy_version)
    return request, {
        "scope": scope,
        "capability": capability,
        "policy_version": request.policy_version,
    }


@pytest.mark.parametrize("row", TIME, ids=CASE_IDS["TIME"])
def test_exact_consent_time_boundaries(tmp_path: Path, row: tuple[Any, ...]) -> None:
    scope_kind, feature, target, delta, rollback = row
    clock = [1000.0]
    scope = ConsentScope.session("A") if scope_kind == "session" else ConsentScope.library()
    with ConsentStore(tmp_path / "policy.db", ttl_seconds=60, clock=lambda: clock[0]) as policy:
        request, grant = prepare(policy, scope, feature)
        policy.grant("p", URL, "audio", **grant)
        binding = policy.capture_bindings("p", URL, ("audio",), scope=scope, request=request)[0]
        token = policy.permit(
            "p", URL, "audio", "a" * 64, scope=scope, request=request, expected_grant=binding
        )
        clock[0] = (1060 if target == "grant" else 1030) + delta
        if rollback:
            clock[0] += 1
            policy.allowed("p", URL, "audio", scope=scope, request=request)
            clock[0] -= 1
        expected = delta == -1 and not rollback
        if target == "grant":
            assert policy.allowed("p", URL, "audio", scope=scope, request=request) is expected
        elif expected:
            policy.validate(token)
        else:
            with pytest.raises(SecurityError):
                policy.validate(token)


@pytest.mark.parametrize("case", range(1, 13), ids=CASE_IDS["MIG"])
def test_legacy_and_schema_cases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: int
) -> None:
    db = tmp_path / "policy.db"
    scope = ConsentScope.session("A")
    if case == 2:
        with sqlite3.connect(db) as connection:
            connection.execute(
                "CREATE TABLE security_grants(provider,endpoint,data_type,grant_id,generation,epoch,expires,allowed,PRIMARY KEY(provider,endpoint,data_type))"
            )
            connection.execute(
                "INSERT INTO security_grants VALUES('p',?,'audio','old','old',1,999999,1)", (URL,)
            )
    if case == 7:
        with sqlite3.connect(db) as connection:
            connection.execute(
                "CREATE TABLE security_consent_meta(id INTEGER PRIMARY KEY,schema_version INTEGER,policy_version INTEGER)"
            )
            connection.execute("INSERT INTO security_consent_meta VALUES(1,2,2)")
        with pytest.raises(SecurityError, match="UNSUPPORTED_SCHEMA"):
            ConsentStore(db)
        with sqlite3.connect(db) as connection:
            assert not connection.execute(
                "SELECT 1 FROM sqlite_master WHERE name='security_grants_v2'"
            ).fetchone()
        return
    if case == 8:
        from recoryn.security import consent

        original = consent.connect

        class Broken:
            def __init__(self, connection: sqlite3.Connection):
                self.connection = connection

            def __getattr__(self, name: str) -> Any:
                return getattr(self.connection, name)

            def execute(self, sql: str, *args: Any) -> Any:
                if "CREATE TABLE IF NOT EXISTS security_grants_v2" in sql:
                    raise OSError("fixture write failure")
                return self.connection.execute(sql, *args)

        monkeypatch.setattr(consent, "connect", lambda path: Broken(original(path)))
        with pytest.raises(SecurityError, match="SECURITY_STATE_UNAVAILABLE"):
            ConsentStore(db)
        with sqlite3.connect(db) as connection:
            assert not connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        return
    if case == 9:
        with sqlite3.connect(db) as connection:
            connection.execute("PRAGMA user_version=1")
        with CostLedger(db) as ledger:
            reservation = ledger.reserve("p", "fixture", 40, 100)
            ledger.mark_unknown(reservation)
            before = db.with_name(db.name + ".cost-witness").read_bytes()
            with ConsentStore(db) as policy:
                _, grant = prepare(policy, scope)
                policy.grant("p", URL, "audio", **grant)
                assert ledger.snapshot("p")["unknown_exposure"] == 40
                assert db.with_name(db.name + ".cost-witness").read_bytes() == before
                assert policy._db.execute("PRAGMA user_version").fetchone()[0] == 1
        return
    if case == 11:
        with ConsentStore(db, policy_version=1) as policy:
            policy.advance_policy_version(2)
            with pytest.raises(SecurityError, match="CONSENT_POLICY_CHANGED"):
                policy.advance_policy_version(1)
            policy.advance_policy_version(2)
            policy.advance_policy_version(2**63 - 1)
            policy.advance_policy_version(2**63 - 1)
            with pytest.raises(SecurityError):
                policy.advance_policy_version(2**63)
            assert policy.policy_version == 2**63 - 1
        with pytest.raises(SecurityError, match="CONSENT_POLICY_CHANGED"):
            ConsentStore(db)
        return
    with ConsentStore(db) as policy:
        request, grant = prepare(policy, scope)
        if case in (1, 2):
            assert not policy.allowed("p", URL, "audio", scope=scope, request=request)
            assert policy._db.execute("SELECT COUNT(*) FROM security_grants_v2").fetchone()[0] == 0
            with pytest.raises(SecurityError):
                policy.grant("p", URL, "audio")  # type: ignore[call-arg]
            return
        policy.grant("p", URL, "audio", **grant)
        binding = policy.capture_bindings("p", URL, ("audio",), scope=scope, request=request)[0]
        if case == 4:
            policy.grant("p", URL, "audio", **grant)
            with pytest.raises(SecurityError, match="PERMIT_REVOKED"):
                policy.validate_binding(binding)
            return
        if case == 5:
            with pytest.raises(SecurityError, match="INVALID_CONSENT_BINDING"):
                policy.validate_binding({"grant_id": binding.grant_id})  # type: ignore[arg-type]
            return
        if case == 12:
            library = ConsentScope.library()
            policy.bind_session("B")
            policy.grant("p", URL, "audio", capability="stt", scope=library, policy_version=2)
            policy.revoke_session("A")
            assert not policy.allowed("p", URL, "audio", scope=library, request=request)
            assert policy.allowed(
                "p", URL, "audio", scope=library, request=replace(request, session_id="B")
            )
            return
    if case == 6:
        with sqlite3.connect(db) as connection:
            connection.execute("UPDATE security_consent_meta SET schema_version=3")
        before = db.read_bytes()
        with pytest.raises(SecurityError, match="UNSUPPORTED_SCHEMA"):
            ConsentStore(db)
        assert db.read_bytes() == before
        return
    if case == 10:
        copy = tmp_path / "copied.db"
        shutil.copyfile(db, copy)
        db = copy
    assert case in (3, 10)
    with ConsentStore(db) as reopened:
        reopened.bind_session("A")
        assert not reopened.allowed("p", URL, "audio", scope=scope, request=request)
        with pytest.raises(SecurityError):
            reopened.validate_binding(binding)


@pytest.mark.parametrize("case", range(1, 23), ids=CASE_IDS["TYPE"])
def test_malformed_scope_context(tmp_path: Path, case: int) -> None:
    fields: list[Any] = ["A", 0, "stt", 2]
    scope_fields: list[Any] = ["session", "A"]
    bad_scope = None
    if case <= 5:
        index, value = [(0, "unknown"), (1, None), (1, ""), (1, "../A"), (0, "library")][case - 1]
        scope_fields[index] = value
    elif case == 6:
        bad_scope = True
    else:
        index, value = {
            7: (2, None),
            8: (2, "download"),
            9: (2, "STT"),
            10: (3, True),
            11: (3, 0),
            12: (3, -1),
            13: (3, "2"),
            14: (3, None),
            15: (0, None),
            16: (0, ""),
            17: (0, "../A"),
            18: (1, True),
            19: (1, -1),
            20: (1, "0"),
            21: (3, 2.0),
            22: (1, None),
        }[case]
        fields[index] = value
    with ConsentStore(tmp_path / "policy.db") as policy:
        with pytest.raises(SecurityError):
            scope = None if bad_scope else ConsentScope(*scope_fields)
            request = ConsentRequest(*fields)
            policy.grant(
                "p",
                URL,
                "audio",
                capability=request.capability,
                scope=scope,
                policy_version=request.policy_version,
            )  # type: ignore[arg-type]
        assert policy._db.execute("SELECT COUNT(*) FROM security_grants_v2").fetchone()[0] == 0
