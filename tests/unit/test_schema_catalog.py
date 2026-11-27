"""Twenty fixed S1 cases: hand/source DDL against independent versioned bytes."""

from __future__ import annotations

import builtins
import ctypes
import dataclasses
import functools
import hashlib
import inspect
import io
import json
import os
import random
import socket
import sqlite3
import subprocess
import sys
import threading
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

import pytest

from recoryn import schema as s
from recoryn.schema import component_shape_wire, expected_shape_wire

_DDL: dict[str, str] = {
    "library.core": "CREATE TABLE IF NOT EXISTS sessions (\n                    session_id TEXT PRIMARY KEY, state TEXT NOT NULL, state_version INTEGER NOT NULL,\n                    generation INTEGER NOT NULL DEFAULT 0,\n                    manifest_sync_pending INTEGER NOT NULL DEFAULT 1,\n                    finalized_chunks TEXT, capture_health TEXT NOT NULL DEFAULT '{}'\n                );\nCREATE TABLE IF NOT EXISTS chunks (\n                    chunk_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,\n                    relative_path TEXT UNIQUE NOT NULL, descriptor TEXT NOT NULL,\n                    FOREIGN KEY(session_id) REFERENCES sessions(session_id)\n                );\nCREATE TABLE IF NOT EXISTS storage_events (\n                    event_id INTEGER PRIMARY KEY, session_id TEXT NOT NULL,\n                    kind TEXT NOT NULL, state_version INTEGER NOT NULL\n                );\nCREATE TABLE IF NOT EXISTS deleted_sessions (\n                    session_id TEXT PRIMARY KEY, generation INTEGER NOT NULL,\n                    status TEXT NOT NULL\n                );",
    "storage.projection": "CREATE TABLE IF NOT EXISTS storage_visible_sessions (\n                    session_id TEXT PRIMARY KEY,\n                    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE\n                );\nCREATE TABLE IF NOT EXISTS storage_pending_deletions (\n                    session_id TEXT PRIMARY KEY\n                );\nCREATE TABLE IF NOT EXISTS storage_catalog_meta (\n                    singleton INTEGER PRIMARY KEY CHECK(singleton=1), version INTEGER NOT NULL\n                );\nCREATE TRIGGER IF NOT EXISTS storage_catalog_insert AFTER INSERT ON sessions\n                BEGIN\n                    UPDATE storage_catalog_meta SET version=version+1 WHERE singleton=1;\n                END;\nCREATE TRIGGER IF NOT EXISTS storage_catalog_change\n                AFTER UPDATE OF state,state_version,generation ON sessions\n                WHEN OLD.state!=NEW.state OR OLD.state_version!=NEW.state_version OR OLD.generation!=NEW.generation\n                BEGIN\n                    UPDATE storage_catalog_meta SET version=version+1 WHERE singleton=1;\n                END;\nCREATE TRIGGER IF NOT EXISTS storage_catalog_delete AFTER DELETE ON sessions\n                BEGIN\n                    UPDATE storage_catalog_meta SET version=version+1 WHERE singleton=1;\n                END;\nCREATE TRIGGER IF NOT EXISTS storage_visible_insert AFTER INSERT ON sessions\n                WHEN NOT EXISTS(SELECT 1 FROM deleted_sessions WHERE session_id=NEW.session_id)\n                BEGIN\n                    INSERT OR IGNORE INTO storage_visible_sessions VALUES(NEW.session_id);\n                END;\nCREATE TRIGGER IF NOT EXISTS storage_visible_delete AFTER INSERT ON deleted_sessions\n                BEGIN\n                    DELETE FROM storage_visible_sessions WHERE session_id=NEW.session_id;\n                    INSERT OR IGNORE INTO storage_pending_deletions VALUES(NEW.session_id);\n                END;",
    "capture.health": "CREATE TABLE IF NOT EXISTS capture_health_runs (\n                    session_id TEXT NOT NULL, capture_run_id TEXT NOT NULL,\n                    schema_version INTEGER NOT NULL, health_version INTEGER NOT NULL,\n                    checkpoint_seq INTEGER NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL,\n                    PRIMARY KEY(session_id,capture_run_id),\n                    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE\n                );\nCREATE TABLE IF NOT EXISTS capture_health_tracks (\n                    session_id TEXT NOT NULL, capture_run_id TEXT NOT NULL,\n                    track_id TEXT NOT NULL, epoch_id TEXT NOT NULL, payload TEXT NOT NULL,\n                    PRIMARY KEY(session_id,capture_run_id,track_id,epoch_id),\n                    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE,\n                    FOREIGN KEY(session_id,capture_run_id) REFERENCES capture_health_runs(session_id,capture_run_id) ON DELETE CASCADE\n                );\nCREATE TABLE IF NOT EXISTS capture_health_events (\n                    session_id TEXT NOT NULL, event_id TEXT NOT NULL,\n                    capture_run_id TEXT NOT NULL, ordinal INTEGER NOT NULL, payload TEXT NOT NULL,\n                    gap_id TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL DEFAULT '', digest TEXT NOT NULL DEFAULT '',\n                    PRIMARY KEY(session_id,event_id),\n                    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE,\n                    FOREIGN KEY(session_id,capture_run_id) REFERENCES capture_health_runs(session_id,capture_run_id) ON DELETE CASCADE\n                );\nCREATE INDEX IF NOT EXISTS capture_health_event_order ON capture_health_events(session_id,capture_run_id,ordinal,event_id);\nCREATE UNIQUE INDEX IF NOT EXISTS capture_health_gap_phase ON capture_health_events(session_id,gap_id,kind);",
    "jobs.core": "CREATE TABLE IF NOT EXISTS jobs (\n                    job_id TEXT PRIMARY KEY, kind TEXT NOT NULL, input_key TEXT NOT NULL,\n                    state TEXT NOT NULL, fence INTEGER NOT NULL DEFAULT 0,\n                    attempt_count INTEGER NOT NULL DEFAULT 0, attempt_id TEXT, owner TEXT,\n                    result_ref TEXT, error_code TEXT, blocked_reason TEXT,\n                    cancel_requested INTEGER NOT NULL DEFAULT 0,\n                    state_version INTEGER NOT NULL DEFAULT 0\n                );\nCREATE UNIQUE INDEX IF NOT EXISTS jobs_dedup\n                    ON jobs(kind, input_key) WHERE state NOT IN ('FAILED', 'CANCELLED');\nCREATE TABLE IF NOT EXISTS attempts (\n                    attempt_id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(job_id),\n                    attempt_no INTEGER NOT NULL, state TEXT NOT NULL, fence INTEGER NOT NULL,\n                    owner TEXT NOT NULL, result_ref TEXT, error_code TEXT,\n                    UNIQUE(job_id, attempt_no)\n                );\nCREATE TABLE IF NOT EXISTS events (\n                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,\n                    job_id TEXT NOT NULL REFERENCES jobs(job_id),\n                    attempt_id TEXT, state TEXT NOT NULL, fence INTEGER NOT NULL,\n                    state_version INTEGER NOT NULL\n                );\nCREATE TABLE IF NOT EXISTS job_sessions (\n                    job_id TEXT PRIMARY KEY REFERENCES jobs(job_id), session_id TEXT NOT NULL\n                );\nCREATE INDEX IF NOT EXISTS job_session_lookup ON job_sessions(session_id);\nCREATE TABLE IF NOT EXISTS job_local_readers (\n                    job_id TEXT PRIMARY KEY REFERENCES jobs(job_id),\n                    attempt_id TEXT NOT NULL REFERENCES attempts(attempt_id),\n                    fence INTEGER NOT NULL CHECK(fence > 0),\n                    active INTEGER NOT NULL CHECK(active IN (0,1))\n                );\nCREATE TABLE IF NOT EXISTS job_remote_intents (\n                    attempt_id TEXT NOT NULL REFERENCES attempts(attempt_id),\n                    reservation_id TEXT NOT NULL, job_id TEXT NOT NULL REFERENCES jobs(job_id),\n                    fence INTEGER NOT NULL CHECK(fence > 0),\n                    PRIMARY KEY(attempt_id,reservation_id)\n                );",
    "jobs.receipts": "CREATE TABLE IF NOT EXISTS job_create_receipts (\n                    request_job_id TEXT PRIMARY KEY,\n                    job_id TEXT NOT NULL REFERENCES jobs(job_id)\n                );",
    "jobs.checkpoints": "CREATE TABLE IF NOT EXISTS job_checkpoints (job_id TEXT NOT NULL REFERENCES jobs(job_id), attempt_id TEXT NOT NULL, result_ref TEXT NOT NULL, UNIQUE(job_id,result_ref));",
    "content.core": "CREATE TABLE IF NOT EXISTS content_revisions (\n                        revision_id TEXT PRIMARY KEY,\n                        session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,\n                        revision_type TEXT NOT NULL, body TEXT NOT NULL, sha256 TEXT NOT NULL\n                    );\nCREATE INDEX IF NOT EXISTS content_session ON content_revisions(session_id);\nCREATE TABLE IF NOT EXISTS content_selections (\n                        session_id TEXT PRIMARY KEY REFERENCES sessions(session_id) ON DELETE CASCADE,\n                        transcript_id TEXT, summary_id TEXT,\n                        transcript_version INTEGER NOT NULL DEFAULT 0,\n                        summary_version INTEGER NOT NULL DEFAULT 0\n                    );\nCREATE TABLE IF NOT EXISTS content_events (\n                        event_id INTEGER PRIMARY KEY,\n                        session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,\n                        revision_id TEXT NOT NULL, revision_type TEXT NOT NULL,\n                        selected INTEGER NOT NULL\n                    );\nCREATE TRIGGER IF NOT EXISTS content_revision_immutable\n                    BEFORE UPDATE ON content_revisions\n                    BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_CONTENT_REVISION'); END;",
    "content.summary_requests": "CREATE TABLE IF NOT EXISTS content_summary_requests (\n                        session_id TEXT PRIMARY KEY REFERENCES sessions(session_id) ON DELETE CASCADE,\n                        settings_key TEXT NOT NULL,\n                        request_count INTEGER NOT NULL DEFAULT 1\n                    );",
    "security.consent": "CREATE TABLE IF NOT EXISTS security_execution(id INTEGER PRIMARY KEY, generation TEXT);\nCREATE TABLE IF NOT EXISTS security_sessions(session_id TEXT PRIMARY KEY, generation INTEGER, revoked INTEGER);\nCREATE TABLE security_local_endpoints(endpoint TEXT PRIMARY KEY, generation TEXT, model_digest TEXT, expires REAL NOT NULL DEFAULT 0);\nCREATE TABLE IF NOT EXISTS security_consent_meta(id INTEGER PRIMARY KEY CHECK(id=1), schema_version INTEGER NOT NULL, policy_version INTEGER NOT NULL);\nCREATE TABLE IF NOT EXISTS security_grants_v2(\n                provider TEXT NOT NULL, endpoint TEXT NOT NULL, capability TEXT NOT NULL,\n                data_type TEXT NOT NULL, scope_kind TEXT NOT NULL, scope_id TEXT NOT NULL,\n                policy_version INTEGER NOT NULL CHECK(policy_version>0),\n                grant_id TEXT NOT NULL UNIQUE, generation TEXT NOT NULL,\n                epoch INTEGER NOT NULL CHECK(epoch>=0), issued_at REAL NOT NULL,\n                expires REAL NOT NULL, allowed INTEGER NOT NULL CHECK(allowed IN (0,1)),\n                revoked_at REAL,\n                PRIMARY KEY(provider,endpoint,capability,data_type,scope_kind,scope_id,policy_version),\n                CHECK((scope_kind='session' AND length(scope_id)>0) OR (scope_kind='library' AND scope_id=''))\n            );",
    "security.cost.legacy": "CREATE TABLE IF NOT EXISTS security_cost_meta(id INTEGER PRIMARY KEY, revision INTEGER);\nCREATE TABLE IF NOT EXISTS security_cost_accounts(provider TEXT PRIMARY KEY, amount_limit INTEGER);\nCREATE TABLE IF NOT EXISTS security_cost_requests(\n                        reservation_id TEXT PRIMARY KEY, provider TEXT, request_id TEXT,\n                        amount INTEGER, actual INTEGER, state TEXT,\n                        UNIQUE(provider,request_id));",
    "security.cost": "CREATE TABLE security_cost_accounts_v2(\n                    account_id TEXT PRIMARY KEY, provider TEXT NOT NULL, currency TEXT NOT NULL,\n                    period_start_utc INTEGER NOT NULL CHECK(period_start_utc>=0),\n                    period_end_utc INTEGER NOT NULL CHECK(period_end_utc>period_start_utc),\n                    policy_version INTEGER NOT NULL CHECK(policy_version>0),\n                    amount_limit INTEGER NOT NULL CHECK(amount_limit>=0),\n                    blocked INTEGER NOT NULL DEFAULT 0 CHECK(blocked IN (0,1)),\n                    UNIQUE(provider,currency,period_start_utc,period_end_utc));\nCREATE TABLE security_cost_requests_v2(\n                    reservation_id TEXT PRIMARY KEY, provider TEXT NOT NULL, request_id TEXT NOT NULL,\n                    account_id TEXT NOT NULL REFERENCES security_cost_accounts_v2(account_id),\n                    reserved_amount INTEGER NOT NULL CHECK(reserved_amount>=0),\n                    actual INTEGER CHECK(actual>=0), state TEXT NOT NULL CHECK(state IN ('RESERVED','UNKNOWN','SETTLED','RELEASED')),\n                    quote_kind TEXT NOT NULL CHECK(quote_kind IN ('VERIFIED','USER_CAP','LEGACY_UNSCOPED')),\n                    model_revision TEXT, profile_id TEXT, endpoint_digest TEXT, body_sha256 TEXT,\n                    byte_length INTEGER CHECK(byte_length>0), input_upper INTEGER CHECK(input_upper>=0),\n                    output_upper INTEGER CHECK(output_upper>=0), price_as_of_utc INTEGER,\n                    valid_until_utc INTEGER, catalog_digest TEXT, request_fingerprint TEXT NOT NULL,\n                    request_json TEXT, quote_json TEXT, policy_json TEXT, dispatch_id TEXT,\n                    UNIQUE(provider,request_id),\n                    CHECK(quote_kind!='VERIFIED' OR (price_as_of_utc IS NOT NULL AND valid_until_utc IS NOT NULL AND input_upper IS NOT NULL AND output_upper IS NOT NULL)),\n                    CHECK(quote_kind='LEGACY_UNSCOPED' OR (body_sha256 IS NOT NULL AND byte_length IS NOT NULL AND quote_json IS NOT NULL AND policy_json IS NOT NULL AND request_json IS NOT NULL)));\nCREATE TABLE security_cost_usage_events(\n                    reservation_id TEXT NOT NULL REFERENCES security_cost_requests_v2(reservation_id),\n                    source TEXT NOT NULL, event_id TEXT NOT NULL, version INTEGER NOT NULL CHECK(version>0),\n                    kind TEXT NOT NULL CHECK(kind IN ('provisional','final')), currency TEXT NOT NULL,\n                    period_id TEXT NOT NULL, amount INTEGER NOT NULL CHECK(amount>=0), payload_digest TEXT NOT NULL,\n                    PRIMARY KEY(reservation_id,source,event_id));\nCREATE TABLE security_cost_meta_v2(\n                    id INTEGER PRIMARY KEY CHECK(id=1), schema_version INTEGER NOT NULL CHECK(schema_version=2),\n                    revision INTEGER NOT NULL, witness_protocol_version INTEGER NOT NULL CHECK(witness_protocol_version=2),\n                    predecessor_v1_state_digest TEXT NOT NULL, migration_state TEXT NOT NULL,\n                    clock_high_water_utc REAL NOT NULL, adopted_providers TEXT NOT NULL,\n                    clock_reset_audit TEXT NOT NULL DEFAULT '[]');",
    "g09.management": "CREATE TABLE recoryn_schema_components(component TEXT PRIMARY KEY NOT NULL, version INTEGER NOT NULL CHECK(version>0), fingerprint TEXT NOT NULL, profile TEXT NOT NULL);\nCREATE TABLE recoryn_maintenance(singleton INTEGER PRIMARY KEY CHECK(singleton=1), library_instance_id TEXT NOT NULL, operation_id TEXT, epoch INTEGER NOT NULL CHECK(epoch>=0), commit_state TEXT NOT NULL CHECK(commit_state IN ('NORMAL','DB_COMMITTED')), input_digest TEXT, CHECK((commit_state='NORMAL' AND operation_id IS NULL AND epoch=0 AND input_digest IS NULL) OR (commit_state='DB_COMMITTED' AND operation_id IS NOT NULL AND epoch>0 AND input_digest IS NOT NULL)));",
}


# X00 hand wire literals; never loaded from ignored build files at runtime.
_FIX1_ORACLES: dict[str, dict[str, str | int]] = {
    "NEGATIVE_LOWERCASE_COLUMN_COLLATION": {
        "expected_wire_utf8": '{"component":"jobs.checkpoints","format":"recoryn-shape-v1","objects":[{"autoincrement":false,"autoindexes":[["u",[["job_id","ASC","BINARY"],["result_ref","ASC","NOCASE"]]]],"checks":[],"columns":[["job_id","TEXT",true,null,0,0,"BINARY"],["attempt_id","TEXT",true,null,0,0,"BINARY"],["result_ref","TEXT",true,null,0,0,"NOCASE"]],"foreign_keys":[[["job_id"],"jobs",["job_id"],"NO ACTION","NO ACTION","NONE"]],"kind":"table","name":"job_checkpoints","rowid":true,"strict":false}],"version":1}',
        "expected_fingerprint": "recoryn-shape-v1:eeef915f23b6ccd2e5ccb0f38733493024f80a26a29fc9a22c0e99c7396a4a13",
        "expected_byte_length": 490,
    },
    "NEGATIVE_LOWERCASE_KEY_COLLATION": {
        "expected_wire_utf8": '{"component":"jobs.checkpoints","format":"recoryn-shape-v1","objects":[{"autoincrement":false,"autoindexes":[["u",[["job_id","ASC","BINARY"],["result_ref","ASC","NOCASE"]]]],"checks":[],"columns":[["job_id","TEXT",true,null,0,0,"BINARY"],["attempt_id","TEXT",true,null,0,0,"BINARY"],["result_ref","TEXT",true,null,0,0,"BINARY"]],"foreign_keys":[[["job_id"],"jobs",["job_id"],"NO ACTION","NO ACTION","NONE"]],"kind":"table","name":"job_checkpoints","rowid":true,"strict":false}],"version":1}',
        "expected_fingerprint": "recoryn-shape-v1:d287ca74a47a529e15c839cc7bd4ddf2b7b6ede66409f31402e145c821dc160a",
        "expected_byte_length": 490,
    },
    "NEGATIVE_DEFAULT_PARENTHESES": {
        "expected_wire_utf8": '{"component":"content.summary_requests","format":"recoryn-shape-v1","objects":[{"autoincrement":false,"autoindexes":[["pk",[["session_id","ASC","BINARY"]]]],"checks":[],"columns":[["session_id","TEXT",false,null,1,0,"BINARY"],["settings_key","TEXT",true,null,0,0,"BINARY"],["request_count","INTEGER",true,[["p","("],["n","1"],["p",")"]],0,0,"BINARY"]],"foreign_keys":[[["session_id"],"sessions",["session_id"],"NO ACTION","CASCADE","NONE"]],"kind":"table","name":"content_summary_requests","rowid":true,"strict":false}],"version":1}',
        "expected_fingerprint": "recoryn-shape-v1:b383b3000188c84d7fe0f2626297da93b2b21df0aa951e7b79626b2812138c98",
        "expected_byte_length": 532,
    },
    "NEGATIVE_STRICT_TEXT_PRIMARY": {
        "expected_wire_utf8": '{"component":"jobs.receipts","format":"recoryn-shape-v1","objects":[{"autoincrement":false,"autoindexes":[["pk",[["request_job_id","ASC","BINARY"]]]],"checks":[],"columns":[["request_job_id","TEXT",false,null,1,0,"BINARY"],["job_id","TEXT",true,null,0,0,"BINARY"]],"foreign_keys":[[["job_id"],"jobs",["job_id"],"NO ACTION","NO ACTION","NONE"]],"kind":"table","name":"job_create_receipts","rowid":true,"strict":true}],"version":1}',
        "expected_fingerprint": "recoryn-shape-v1:8720648ff93d08c82388945223ca41fc406329add1c40e3e2fe056df2b71061e",
        "expected_byte_length": 429,
    },
}

# Literal order is the S1 contract, not the product catalog's enumeration.
_CASES = (
    ("G09a-X-SC-01", "library.core", None),
    ("G09a-X-SC-02", "storage.projection", None),
    ("G09a-X-SC-03", "capture.health", None),
    ("G09a-X-SC-04", "jobs.core", None),
    ("G09a-X-SC-05", "jobs.receipts", None),
    ("G09a-X-SC-06", "jobs.checkpoints", None),
    ("G09a-X-SC-07", "content.core", None),
    ("G09a-X-SC-08", "content.summary_requests", None),
    ("G09a-X-SC-09", "security.consent", None),
    ("G09a-X-SC-10", "security.cost.legacy", None),
    ("G09a-X-SC-11", "security.cost", None),
    ("G09a-X-SC-12", "g09.management", None),
    ("G09a-X-FP-01", "jobs.checkpoints", "NORMAL_CHECKPOINT_SQL_FORMAT_ONLY"),
    ("G09a-X-FP-02", "content.core", "NEGATIVE_LITERAL_CASE"),
    ("G09a-X-FP-03", "jobs.core", "NEGATIVE_WHERE_NOT_REMOVAL"),
    ("G09a-X-FP-04", "jobs.checkpoints", "NEGATIVE_COLLATION"),
    ("G09a-X-FP-05", "jobs.checkpoints", "NEGATIVE_LOWERCASE_COLUMN_COLLATION"),
    ("G09a-X-FP-06", "jobs.checkpoints", "NEGATIVE_LOWERCASE_KEY_COLLATION"),
    ("G09a-X-FP-07", "content.summary_requests", "NEGATIVE_DEFAULT_PARENTHESES"),
    ("G09a-X-FP-08", "jobs.receipts", "NEGATIVE_STRICT_TEXT_PRIMARY"),
)


@pytest.mark.unit
@pytest.mark.parametrize("case_id,component,variant", _CASES, ids=[row[0] for row in _CASES])
def test_component_shape_wire(
    tmp_path: Path, case_id: str, component: str, variant: str | None
) -> None:
    fixture_path = Path(__file__).resolve().parents[1] / "fixtures" / "g09_schema_v1.json"
    fixture_bytes = fixture_path.read_bytes()
    assert len(fixture_bytes) == 306337
    assert hashlib.sha256(fixture_bytes).hexdigest() == (
        "8b3611904a5db6371d2ebef831f7477a9cd8fa2c6b13ad55f0774417911dedbb"
    )
    golden = json.loads(fixture_bytes)
    normal = golden["components"][component]
    oracle = (
        normal
        if variant is None
        else _FIX1_ORACLES[variant]
        if variant in _FIX1_ORACLES
        else golden["lexical_examples"][variant]
    )
    expected = oracle.get("expected_wire_utf8", oracle.get("expected_utf8_bytes_text"))
    expected_bytes = expected.encode("utf-8")
    expected_fingerprint = oracle["expected_fingerprint"]
    # DDL is source-backed literal input, never rendered by a product/golden model.
    ddl = _DDL[component]
    if variant == "NORMAL_CHECKPOINT_SQL_FORMAT_ONLY":
        ddl = """cReAtE /* known spellings only */ tAbLe "JOB_CHECKPOINTS" (
            "JOB_ID" text not null references "JOBS"("JOB_ID"),
            "ATTEMPT_ID" text not null, "RESULT_REF" text not null,
            unique("JOB_ID", "RESULT_REF")
        );"""
    elif variant == "NEGATIVE_LITERAL_CASE":
        ddl = ddl.replace("'IMMUTABLE_CONTENT_REVISION'", "'immutable_content_revision'")
    elif variant == "NEGATIVE_WHERE_NOT_REMOVAL":
        ddl = ddl.replace("state NOT IN", "state IN")
    elif variant == "NEGATIVE_COLLATION":
        ddl = ddl.replace("result_ref TEXT NOT NULL", "result_ref TEXT NOT NULL COLLATE NOCASE")
    elif variant == "NEGATIVE_LOWERCASE_COLUMN_COLLATION":
        ddl = ddl.replace("result_ref TEXT NOT NULL", "result_ref TEXT NOT NULL COLLATE nocase")
    elif variant == "NEGATIVE_LOWERCASE_KEY_COLLATION":
        ddl = ddl.replace("UNIQUE(job_id,result_ref)", "UNIQUE(job_id,result_ref COLLATE nocase)")
    elif variant == "NEGATIVE_DEFAULT_PARENTHESES":
        ddl = ddl.replace("DEFAULT 1", "DEFAULT (1)")
    elif variant == "NEGATIVE_STRICT_TEXT_PRIMARY":
        ddl = ddl.rstrip(";") + " STRICT;"
    path = tmp_path / (case_id + ".sqlite")
    connection = sqlite3.connect(path)
    try:
        if component in {
            "storage.projection",
            "capture.health",
            "content.core",
            "content.summary_requests",
        }:
            connection.executescript(_DDL["library.core"])
        if component in {"jobs.receipts", "jobs.checkpoints"}:
            connection.executescript(_DDL["jobs.core"])
        connection.executescript(ddl)
        connection.commit()
        raw_schema_before = tuple(
            connection.execute(
                "SELECT type,name,tbl_name,sql FROM main.sqlite_schema ORDER BY name,type"
            )
        )
        before_files = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
        changes = connection.total_changes
        transaction = connection.in_transaction
        actions: list[tuple[int, str | None, str | None]] = []
        statements: list[str] = []
        # Authorizer observes actual operations, not a mock execute counter.
        forbidden = {
            sqlite3.SQLITE_INSERT,
            sqlite3.SQLITE_UPDATE,
            sqlite3.SQLITE_DELETE,
            sqlite3.SQLITE_CREATE_TABLE,
            sqlite3.SQLITE_CREATE_INDEX,
            sqlite3.SQLITE_CREATE_TRIGGER,
            sqlite3.SQLITE_CREATE_VIEW,
            sqlite3.SQLITE_DROP_TABLE,
            sqlite3.SQLITE_DROP_INDEX,
            sqlite3.SQLITE_DROP_TRIGGER,
            sqlite3.SQLITE_DROP_VIEW,
            sqlite3.SQLITE_ALTER_TABLE,
            sqlite3.SQLITE_TRANSACTION,
            sqlite3.SQLITE_SAVEPOINT,
            sqlite3.SQLITE_ATTACH,
            sqlite3.SQLITE_DETACH,
        }

        def authorize(
            action: int,
            first: str | None,
            second: str | None,
            database: str | None,
            source: str | None,
        ) -> int:
            actions.append((action, first, second))
            if action in forbidden:
                return sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_PRAGMA and first not in {
                "schema_version",
                "table_xinfo",
                "foreign_key_list",
                "index_list",
                "index_xinfo",
            }:
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        connection.set_authorizer(authorize)
        connection.set_trace_callback(statements.append)
        version = normal["model"]["version"]  # Hand fixture, not product enum/catalog.
        catalog_wire = expected_shape_wire(component, version)
        assert actions == [] and statements == [], "catalog API must not query SQLite"
        assert catalog_wire == normal["expected_wire_utf8"].encode("utf-8"), (
            "fixed catalog must equal the independent hand wire"
        )
        assert (
            "recoryn-shape-v1:" + hashlib.sha256(catalog_wire).hexdigest()
            == normal["expected_fingerprint"]
        )
        if variant in _FIX1_ORACLES:
            rejection: ValueError | None = None
            actual_wire = None
            try:
                actual_wire = component_shape_wire(connection, component)
            except ValueError as error:
                rejection = error
            assert rejection is None, (
                "supported named SQL must be accepted by the actual descriptor"
            )
        else:
            actual_wire = component_shape_wire(connection, component)
        assert actual_wire == expected_bytes, "actual SQL description must equal the hand wire"
        assert "recoryn-shape-v1:" + hashlib.sha256(actual_wire).hexdigest() == expected_fingerprint
        if variant is not None and variant.startswith("NEGATIVE_"):
            assert actual_wire != catalog_wire, "semantic difference must not normalize away"
        else:
            assert actual_wire == catalog_wire
        assert actions and statements, "actual caller-owned SQLite reads must be exercised"
        assert not any(action in forbidden for action, _, _ in actions), "description writes0"
        assert all(sql.lstrip().upper().startswith(("SELECT ", "PRAGMA ")) for sql in statements)
        assert connection.total_changes == changes and connection.in_transaction is transaction
        connection.set_authorizer(None)
        connection.set_trace_callback(None)
        assert (
            tuple(
                connection.execute(
                    "SELECT type,name,tbl_name,sql FROM main.sqlite_schema ORDER BY name,type"
                )
            )
            == raw_schema_before
        )
        assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before_files
        # The caller can still use the same connection; the API did not close it.
        assert connection.execute("SELECT 1").fetchone() == (1,)
    finally:
        connection.close()


@pytest.mark.unit
def test_schema_catalog_id_audit() -> None:
    expected = {
        "G09a-X-SC-01",
        "G09a-X-SC-02",
        "G09a-X-SC-03",
        "G09a-X-SC-04",
        "G09a-X-SC-05",
        "G09a-X-SC-06",
        "G09a-X-SC-07",
        "G09a-X-SC-08",
        "G09a-X-SC-09",
        "G09a-X-SC-10",
        "G09a-X-SC-11",
        "G09a-X-SC-12",
        "G09a-X-FP-01",
        "G09a-X-FP-02",
        "G09a-X-FP-03",
        "G09a-X-FP-04",
        "G09a-X-FP-05",
        "G09a-X-FP-06",
        "G09a-X-FP-07",
        "G09a-X-FP-08",
    }
    ids = [row[0] for row in _CASES]
    assert len(ids) == len(set(ids)) == 20
    assert set(ids) == expected
    assert len([row for row in _CASES if row[2] is None]) == 12
    assert len([row for row in _CASES if row[2] is not None]) == 8


# Shared test instrumentation is copied into each owned test module; no build dependency.
def _wire_data():
    return json.loads(
        (
            Path(__file__).resolve().parents[1] / "fixtures/g09_management_wire_literals_v1.json"
        ).read_text(encoding="utf8")
    )


@contextmanager
def _management_no_io(events):
    def denied(name):
        def stop(*args, **kwargs):
            events.append(name)
            raise AssertionError("MANAGEMENT_IO_ATTEMPT:" + name)

        return stop

    with pytest.MonkeyPatch.context() as patch:
        targets = [
            (builtins, "open"),
            (io, "open"),
            (sqlite3, "connect"),
            (socket, "socket"),
            (socket, "create_connection"),
            (socket, "getaddrinfo"),
            (socket, "gethostbyname"),
            (subprocess, "Popen"),
            (threading.Thread, "start"),
            (ctypes, "CDLL"),
            (ctypes, "PyDLL"),
            (ctypes.LibraryLoader, "LoadLibrary"),
        ]
        targets += [
            (os, name)
            for name in (
                "open",
                "fdopen",
                "read",
                "write",
                "stat",
                "lstat",
                "listdir",
                "scandir",
                "mkdir",
                "remove",
                "unlink",
                "rename",
                "replace",
                "system",
            )
        ]
        targets += [(ctypes, name) for name in ("WinDLL", "OleDLL") if hasattr(ctypes, name)]
        for module, names in (
            ("win32cred", ("CredRead", "CredWrite", "CredDelete")),
            ("keyring", ("get_password", "set_password", "delete_password")),
        ):
            if module in sys.modules:
                targets += [
                    (sys.modules[module], name)
                    for name in names
                    if hasattr(sys.modules[module], name)
                ]
        for owner, name in targets:
            patch.setattr(owner, name, denied(owner.__name__ + "." + name))
        yield


@pytest.fixture(scope="session", autouse=True)
def _management_selected_audit(request):
    if hasattr(request.config, "_g09_management_audit"):
        yield request.config._g09_management_audit
        return
    owned = (
        "tests/unit/test_schema_catalog.py::",
        "tests/unit/test_management_wire_api.py::",
        "tests/property/test_management_wire_case_space.py::",
    )
    state = {
        "selected": [
            item.nodeid for item in request.session.items if item.nodeid.startswith(owned)
        ],
        "reports": [],
        "calls": [],
        "IO_attempts": [],
        "active": request.session.items[0].nodeid if request.session.items else None,
    }
    selected_set = set(state["selected"])
    request.config._g09_management_audit = state
    patch = pytest.MonkeyPatch()

    def protect(real, name):
        @functools.wraps(real)
        def observed(*args, **kwargs):
            event = {"node": state["active"], "name": name, "status": "ENTERED"}
            actual = inspect.unwrap(real)
            event["actual_file"] = actual.__code__.co_filename
            event["actual_globals_schema"] = actual.__globals__ is vars(s)
            state["calls"].append(event)
            try:
                with _management_no_io(state["IO_attempts"]):
                    value = real(*args, **kwargs)
            except BaseException as error:
                event.update(
                    status="RAISED",
                    error_type=type(error).__name__,
                    kind=getattr(error, "kind", None),
                )
                raise
            event["status"] = "RETURNED"
            return value

        return observed

    for name in ("decode_management", "encode_management"):
        patch.setattr(s, name, protect(getattr(s, name), name))
    for cls in (s._FrozenWireData, s.ProgressDocument):
        patch.setattr(
            cls, "__post_init__", protect(cls.__post_init__, cls.__name__ + ".__post_init__")
        )

    class Audit:
        def pytest_runtest_setup(self, item):
            state["active"] = item.nodeid

        def pytest_runtest_logreport(self, report):
            if report.nodeid in selected_set:
                state["reports"].append(
                    {"node": report.nodeid, "when": report.when, "outcome": report.outcome}
                )

        def pytest_sessionfinish(self, session, exitstatus):
            state["exitstatus"] = int(exitstatus)
            expected = set(state["selected"])
            counts = Counter(r["node"] for r in state["reports"] if r["when"] == "call")
            state["call_counts"] = {n: counts[n] for n in expected}
            state["selected_call_once"] = all(n == 1 for n in state["call_counts"].values())
            state["nonselected_call_nodes"] = sorted(
                {r["node"] for r in state["reports"] if r["when"] == "call"} - expected
            )
            if exitstatus == 0:
                assert state["selected_call_once"] and not state["nonselected_call_nodes"]
                assert not state["IO_attempts"]
            destination = os.environ.get("RECORYN_MANAGEMENT_AUDIT")
            if destination:
                Path(destination).write_text(
                    json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf8"
                )

    request.config.pluginmanager.register(Audit(), "g09_management_selected_audit")
    yield state
    patch.undo()


def _wire_capture(call):
    try:
        return call(), None
    except Exception as error:
        return None, error


def _wire_closed(error, goal="WIRE_EXPECTED_MALFORMED_AFTER_ACTUAL_API", kind="MALFORMED"):
    assert error is not None, goal
    assert type(error) is s.SchemaWireError
    assert (
        error.kind == kind
        and str(error) == kind
        and repr(error) == "SchemaWireError(" + kind + ")"
        and error.args == (kind,)
    )


_WIRE_FIXTURE = _wire_data()
_WIRE_CAW = _WIRE_FIXTURE["caw"]
_WIRE_CAN = _WIRE_FIXTURE["can"]


def _wire_plain(value):
    if dataclasses.is_dataclass(value):
        return {
            field.name: _wire_plain(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if type(value) is tuple:
        return [_wire_plain(x) for x in value]
    return value


@pytest.mark.parametrize("row", _WIRE_CAW, ids=[row["id"] for row in _WIRE_CAW])
def test_management_wire_types(row, tmp_path, monkeypatch):
    raw = bytes.fromhex(row["raw_hex"])
    if row["id"] == "G09a-X-CAW-01":
        caller = tmp_path / "caller-bindings-hand.json"
        caller.write_bytes(raw)
        assert caller.read_bytes() == raw
    digest_events = []
    if row["id"] == "G09a-X-CAW-12":
        positive = _WIRE_FIXTURE["hand6"]["PROGRESS"]["raw_utf8"].encode()
        with _management_no_io([]):
            good = s.decode_management(positive, kind=s.ManagementObjectKind.PROGRESS)
            assert s.encode_management(good) == positive
        real = s._mp_record_digest

        @functools.wraps(real)
        def observe(value):
            digest_events.append(
                {
                    "length": len(value),
                    "file": real.__code__.co_filename,
                    "globals_schema": real.__globals__ is vars(s),
                }
            )
            return real(value)

        monkeypatch.setattr(s, "_mp_record_digest", observe)
        assert (
            len(raw) == 282
            and hashlib.sha256(raw).hexdigest()
            == "e5c5016fe2f1fefd627e9341986573fcf5045e98e6924fb3741ab4d2a4ec9ba0"
        )
    with _management_no_io([]):
        document, error = _wire_capture(
            lambda: s.decode_management(raw, kind=getattr(s.ManagementObjectKind, row["kind"]))
        )
        if row["expected"] == "MALFORMED":
            goal = (
                "CAW12_MUST_REJECT_AFTER_ACTUAL_PROGRESS"
                if row["id"] == "G09a-X-CAW-12"
                else "CANONICAL_RAW_MUST_REJECT_AFTER_ACTUAL_BINDINGS"
                if row["id"] in {"G09a-X-CAW-25", "G09a-X-CAW-26"}
                else "CAW_HAND_MUST_REJECT_AFTER_ACTUAL_API"
            )
            _wire_closed(error, goal)
            assert error.__cause__ is None and error.__context__ is None
        else:
            assert error is None, "CAW_HAND_NORMAL_MUST_RETURN"
            assert type(document) is s.BindingsDocument
            assert _wire_plain(document) == json.loads(raw)
            assert s.encode_management(document) == raw
            assert (
                len(raw) == 1726
                and hashlib.sha256(raw).hexdigest()
                == "83bb6f081d0c9f86854da76644fae5127c22dd733cd64eb1f1c72bdd28c289e6"
            )
            with pytest.raises(dataclasses.FrozenInstanceError):
                document.generation = 1
            assert not any(hasattr(document, n) for n in ("permit", "proof", "owner", "complete"))
    if row["id"] == "G09a-X-CAW-12":
        assert (
            len(digest_events) == 1
            and digest_events[0]["length"] == 63
            and digest_events[0]["globals_schema"]
        ), "CAW12_ACTUAL_DIGEST63_GUARD_REACHED"


@pytest.mark.parametrize("row", _WIRE_CAN, ids=[row["id"] for row in _WIRE_CAN])
def test_management_tagged_null(row):
    positive = row["positive_raw"].encode()
    raw = row["raw_utf8"].encode()
    with _management_no_io([]):
        good, error = _wire_capture(
            lambda: s.decode_management(positive, kind=getattr(s.ManagementObjectKind, row["kind"]))
        )
        assert error is None, "CAN_COMPLETE_NORMAL_COUNTERPART_MUST_RETURN"
        assert _wire_plain(good) == json.loads(positive)
        assert s.encode_management(good) == positive
        if row["expected"] == "MALFORMED":
            _, error = _wire_capture(
                lambda: s.decode_management(raw, kind=getattr(s.ManagementObjectKind, row["kind"]))
            )
            _wire_closed(error, "CAN_ONE_FIELD_NEGATIVE_MUST_REJECT_AFTER_ACTUAL_API")
        else:
            assert positive == raw
            if row["id"] == "G09a-X-CAN-01":
                assert type(good.targets[0].source_pointer) is s.AbsentPointer
            if row["id"] == "G09a-X-CAN-04":
                assert (
                    good.targets[0].source_cut == "UNRESOLVED"
                    and good.targets[0].source_pointer is None
                    and good.targets[0].source_digest is None
                )
                assert good.disposition == "RECONCILIATION_REQUIRED"
            if row["id"] == "G09a-X-CAN-05":
                assert (
                    type(good.targets[0].source_pointer) is s.FreshPointer
                    and good.targets[0].source_pointer.epoch == 0
                )
            if row["id"] == "G09a-X-CAN-16":
                assert good.binding_links is None and good.phase == "PREPARING"


# Private D14 FIX1 input inventory; expected is independent hand/golden data.
_CP_ROWS = [
    {
        "id": "PRIVATE-CP01",
        "label": "catalog-positive/F2_J",
        "constructor": "PAIRS",
        "pairs": [
            ["attempts", "table"],
            ["events", "table"],
            ["job_checkpoints", "table"],
            ["job_create_receipts", "table"],
            ["job_local_readers", "table"],
            ["job_remote_intents", "table"],
            ["job_session_lookup", "index"],
            ["job_sessions", "table"],
            ["jobs", "table"],
            ["jobs_dedup", "index"],
            ["recoryn_maintenance", "table"],
            ["recoryn_schema_components", "table"],
        ],
        "expected": "SPEC",
        "profile": "F2_J",
    },
    {
        "id": "PRIVATE-CP02",
        "label": "catalog-positive/F2_L",
        "constructor": "PAIRS",
        "pairs": [
            ["capture_health_event_order", "index"],
            ["capture_health_events", "table"],
            ["capture_health_gap_phase", "index"],
            ["capture_health_runs", "table"],
            ["capture_health_tracks", "table"],
            ["chunks", "table"],
            ["deleted_sessions", "table"],
            ["recoryn_maintenance", "table"],
            ["recoryn_schema_components", "table"],
            ["sessions", "table"],
            ["storage_catalog_change", "trigger"],
            ["storage_catalog_delete", "trigger"],
            ["storage_catalog_insert", "trigger"],
            ["storage_catalog_meta", "table"],
            ["storage_events", "table"],
            ["storage_pending_deletions", "table"],
            ["storage_visible_delete", "trigger"],
            ["storage_visible_insert", "trigger"],
            ["storage_visible_sessions", "table"],
        ],
        "expected": "SPEC",
        "profile": "F2_L",
    },
    {
        "id": "PRIVATE-CP03",
        "label": "catalog-positive/F2_LC",
        "constructor": "PAIRS",
        "pairs": [
            ["capture_health_event_order", "index"],
            ["capture_health_events", "table"],
            ["capture_health_gap_phase", "index"],
            ["capture_health_runs", "table"],
            ["capture_health_tracks", "table"],
            ["chunks", "table"],
            ["content_events", "table"],
            ["content_revision_immutable", "trigger"],
            ["content_revisions", "table"],
            ["content_selections", "table"],
            ["content_session", "index"],
            ["content_summary_requests", "table"],
            ["deleted_sessions", "table"],
            ["recoryn_maintenance", "table"],
            ["recoryn_schema_components", "table"],
            ["sessions", "table"],
            ["storage_catalog_change", "trigger"],
            ["storage_catalog_delete", "trigger"],
            ["storage_catalog_insert", "trigger"],
            ["storage_catalog_meta", "table"],
            ["storage_events", "table"],
            ["storage_pending_deletions", "table"],
            ["storage_visible_delete", "trigger"],
            ["storage_visible_insert", "trigger"],
            ["storage_visible_sessions", "table"],
        ],
        "expected": "SPEC",
        "profile": "F2_LC",
    },
    {
        "id": "PRIVATE-CP04",
        "label": "catalog-positive/F2_LC_CONS",
        "constructor": "PAIRS",
        "pairs": [
            ["capture_health_event_order", "index"],
            ["capture_health_events", "table"],
            ["capture_health_gap_phase", "index"],
            ["capture_health_runs", "table"],
            ["capture_health_tracks", "table"],
            ["chunks", "table"],
            ["content_events", "table"],
            ["content_revision_immutable", "trigger"],
            ["content_revisions", "table"],
            ["content_selections", "table"],
            ["content_session", "index"],
            ["content_summary_requests", "table"],
            ["deleted_sessions", "table"],
            ["recoryn_maintenance", "table"],
            ["recoryn_schema_components", "table"],
            ["security_consent_meta", "table"],
            ["security_execution", "table"],
            ["security_grants_v2", "table"],
            ["security_local_endpoints", "table"],
            ["security_sessions", "table"],
            ["sessions", "table"],
            ["storage_catalog_change", "trigger"],
            ["storage_catalog_delete", "trigger"],
            ["storage_catalog_insert", "trigger"],
            ["storage_catalog_meta", "table"],
            ["storage_events", "table"],
            ["storage_pending_deletions", "table"],
            ["storage_visible_delete", "trigger"],
            ["storage_visible_insert", "trigger"],
            ["storage_visible_sessions", "table"],
        ],
        "expected": "SPEC",
        "profile": "F2_LC_CONS",
    },
    {
        "id": "PRIVATE-CP05",
        "label": "catalog-positive/F2_LC_CONS_COST1",
        "constructor": "PAIRS",
        "pairs": [
            ["capture_health_event_order", "index"],
            ["capture_health_events", "table"],
            ["capture_health_gap_phase", "index"],
            ["capture_health_runs", "table"],
            ["capture_health_tracks", "table"],
            ["chunks", "table"],
            ["content_events", "table"],
            ["content_revision_immutable", "trigger"],
            ["content_revisions", "table"],
            ["content_selections", "table"],
            ["content_session", "index"],
            ["content_summary_requests", "table"],
            ["deleted_sessions", "table"],
            ["recoryn_maintenance", "table"],
            ["recoryn_schema_components", "table"],
            ["security_consent_meta", "table"],
            ["security_cost_accounts", "table"],
            ["security_cost_meta", "table"],
            ["security_cost_requests", "table"],
            ["security_execution", "table"],
            ["security_grants_v2", "table"],
            ["security_local_endpoints", "table"],
            ["security_sessions", "table"],
            ["sessions", "table"],
            ["storage_catalog_change", "trigger"],
            ["storage_catalog_delete", "trigger"],
            ["storage_catalog_insert", "trigger"],
            ["storage_catalog_meta", "table"],
            ["storage_events", "table"],
            ["storage_pending_deletions", "table"],
            ["storage_visible_delete", "trigger"],
            ["storage_visible_insert", "trigger"],
            ["storage_visible_sessions", "table"],
        ],
        "expected": "SPEC",
        "profile": "F2_LC_CONS_COST1",
    },
    {
        "id": "PRIVATE-CP06",
        "label": "catalog-positive/F2_LC_CONS_COST2",
        "constructor": "PAIRS",
        "pairs": [
            ["capture_health_event_order", "index"],
            ["capture_health_events", "table"],
            ["capture_health_gap_phase", "index"],
            ["capture_health_runs", "table"],
            ["capture_health_tracks", "table"],
            ["chunks", "table"],
            ["content_events", "table"],
            ["content_revision_immutable", "trigger"],
            ["content_revisions", "table"],
            ["content_selections", "table"],
            ["content_session", "index"],
            ["content_summary_requests", "table"],
            ["deleted_sessions", "table"],
            ["recoryn_maintenance", "table"],
            ["recoryn_schema_components", "table"],
            ["security_consent_meta", "table"],
            ["security_cost_accounts", "table"],
            ["security_cost_accounts_v2", "table"],
            ["security_cost_meta", "table"],
            ["security_cost_meta_v2", "table"],
            ["security_cost_requests", "table"],
            ["security_cost_requests_v2", "table"],
            ["security_cost_usage_events", "table"],
            ["security_execution", "table"],
            ["security_grants_v2", "table"],
            ["security_local_endpoints", "table"],
            ["security_sessions", "table"],
            ["sessions", "table"],
            ["storage_catalog_change", "trigger"],
            ["storage_catalog_delete", "trigger"],
            ["storage_catalog_insert", "trigger"],
            ["storage_catalog_meta", "table"],
            ["storage_events", "table"],
            ["storage_pending_deletions", "table"],
            ["storage_visible_delete", "trigger"],
            ["storage_visible_insert", "trigger"],
            ["storage_visible_sessions", "table"],
        ],
        "expected": "SPEC",
        "profile": "F2_LC_CONS_COST2",
    },
    {
        "id": "PRIVATE-CP07",
        "label": "catalog-positive/F2_LC_COST1",
        "constructor": "PAIRS",
        "pairs": [
            ["capture_health_event_order", "index"],
            ["capture_health_events", "table"],
            ["capture_health_gap_phase", "index"],
            ["capture_health_runs", "table"],
            ["capture_health_tracks", "table"],
            ["chunks", "table"],
            ["content_events", "table"],
            ["content_revision_immutable", "trigger"],
            ["content_revisions", "table"],
            ["content_selections", "table"],
            ["content_session", "index"],
            ["content_summary_requests", "table"],
            ["deleted_sessions", "table"],
            ["recoryn_maintenance", "table"],
            ["recoryn_schema_components", "table"],
            ["security_cost_accounts", "table"],
            ["security_cost_meta", "table"],
            ["security_cost_requests", "table"],
            ["sessions", "table"],
            ["storage_catalog_change", "trigger"],
            ["storage_catalog_delete", "trigger"],
            ["storage_catalog_insert", "trigger"],
            ["storage_catalog_meta", "table"],
            ["storage_events", "table"],
            ["storage_pending_deletions", "table"],
            ["storage_visible_delete", "trigger"],
            ["storage_visible_insert", "trigger"],
            ["storage_visible_sessions", "table"],
        ],
        "expected": "SPEC",
        "profile": "F2_LC_COST1",
    },
    {
        "id": "PRIVATE-CP08",
        "label": "catalog-positive/F2_LC_COST2",
        "constructor": "PAIRS",
        "pairs": [
            ["capture_health_event_order", "index"],
            ["capture_health_events", "table"],
            ["capture_health_gap_phase", "index"],
            ["capture_health_runs", "table"],
            ["capture_health_tracks", "table"],
            ["chunks", "table"],
            ["content_events", "table"],
            ["content_revision_immutable", "trigger"],
            ["content_revisions", "table"],
            ["content_selections", "table"],
            ["content_session", "index"],
            ["content_summary_requests", "table"],
            ["deleted_sessions", "table"],
            ["recoryn_maintenance", "table"],
            ["recoryn_schema_components", "table"],
            ["security_cost_accounts", "table"],
            ["security_cost_accounts_v2", "table"],
            ["security_cost_meta", "table"],
            ["security_cost_meta_v2", "table"],
            ["security_cost_requests", "table"],
            ["security_cost_requests_v2", "table"],
            ["security_cost_usage_events", "table"],
            ["sessions", "table"],
            ["storage_catalog_change", "trigger"],
            ["storage_catalog_delete", "trigger"],
            ["storage_catalog_insert", "trigger"],
            ["storage_catalog_meta", "table"],
            ["storage_events", "table"],
            ["storage_pending_deletions", "table"],
            ["storage_visible_delete", "trigger"],
            ["storage_visible_insert", "trigger"],
            ["storage_visible_sessions", "table"],
        ],
        "expected": "SPEC",
        "profile": "F2_LC_COST2",
    },
    {
        "id": "PRIVATE-CP09",
        "label": "catalog-positive/F2_LJ",
        "constructor": "PAIRS",
        "pairs": [
            ["attempts", "table"],
            ["capture_health_event_order", "index"],
            ["capture_health_events", "table"],
            ["capture_health_gap_phase", "index"],
            ["capture_health_runs", "table"],
            ["capture_health_tracks", "table"],
            ["chunks", "table"],
            ["deleted_sessions", "table"],
            ["events", "table"],
            ["job_checkpoints", "table"],
            ["job_create_receipts", "table"],
            ["job_local_readers", "table"],
            ["job_remote_intents", "table"],
            ["job_session_lookup", "index"],
            ["job_sessions", "table"],
            ["jobs", "table"],
            ["jobs_dedup", "index"],
            ["recoryn_maintenance", "table"],
            ["recoryn_schema_components", "table"],
            ["sessions", "table"],
            ["storage_catalog_change", "trigger"],
            ["storage_catalog_delete", "trigger"],
            ["storage_catalog_insert", "trigger"],
            ["storage_catalog_meta", "table"],
            ["storage_events", "table"],
            ["storage_pending_deletions", "table"],
            ["storage_visible_delete", "trigger"],
            ["storage_visible_insert", "trigger"],
            ["storage_visible_sessions", "table"],
        ],
        "expected": "SPEC",
        "profile": "F2_LJ",
    },
    {
        "id": "PRIVATE-CP10",
        "label": "catalog-positive/F2_LJC",
        "constructor": "PAIRS",
        "pairs": [
            ["attempts", "table"],
            ["capture_health_event_order", "index"],
            ["capture_health_events", "table"],
            ["capture_health_gap_phase", "index"],
            ["capture_health_runs", "table"],
            ["capture_health_tracks", "table"],
            ["chunks", "table"],
            ["content_events", "table"],
            ["content_revision_immutable", "trigger"],
            ["content_revisions", "table"],
            ["content_selections", "table"],
            ["content_session", "index"],
            ["content_summary_requests", "table"],
            ["deleted_sessions", "table"],
            ["events", "table"],
            ["job_checkpoints", "table"],
            ["job_create_receipts", "table"],
            ["job_local_readers", "table"],
            ["job_remote_intents", "table"],
            ["job_session_lookup", "index"],
            ["job_sessions", "table"],
            ["jobs", "table"],
            ["jobs_dedup", "index"],
            ["recoryn_maintenance", "table"],
            ["recoryn_schema_components", "table"],
            ["sessions", "table"],
            ["storage_catalog_change", "trigger"],
            ["storage_catalog_delete", "trigger"],
            ["storage_catalog_insert", "trigger"],
            ["storage_catalog_meta", "table"],
            ["storage_events", "table"],
            ["storage_pending_deletions", "table"],
            ["storage_visible_delete", "trigger"],
            ["storage_visible_insert", "trigger"],
            ["storage_visible_sessions", "table"],
        ],
        "expected": "SPEC",
        "profile": "F2_LJC",
    },
    {
        "id": "PRIVATE-CP11",
        "label": "catalog-positive/F2_LJC_CONS",
        "constructor": "PAIRS",
        "pairs": [
            ["attempts", "table"],
            ["capture_health_event_order", "index"],
            ["capture_health_events", "table"],
            ["capture_health_gap_phase", "index"],
            ["capture_health_runs", "table"],
            ["capture_health_tracks", "table"],
            ["chunks", "table"],
            ["content_events", "table"],
            ["content_revision_immutable", "trigger"],
            ["content_revisions", "table"],
            ["content_selections", "table"],
            ["content_session", "index"],
            ["content_summary_requests", "table"],
            ["deleted_sessions", "table"],
            ["events", "table"],
            ["job_checkpoints", "table"],
            ["job_create_receipts", "table"],
            ["job_local_readers", "table"],
            ["job_remote_intents", "table"],
            ["job_session_lookup", "index"],
            ["job_sessions", "table"],
            ["jobs", "table"],
            ["jobs_dedup", "index"],
            ["recoryn_maintenance", "table"],
            ["recoryn_schema_components", "table"],
            ["security_consent_meta", "table"],
            ["security_execution", "table"],
            ["security_grants_v2", "table"],
            ["security_local_endpoints", "table"],
            ["security_sessions", "table"],
            ["sessions", "table"],
            ["storage_catalog_change", "trigger"],
            ["storage_catalog_delete", "trigger"],
            ["storage_catalog_insert", "trigger"],
            ["storage_catalog_meta", "table"],
            ["storage_events", "table"],
            ["storage_pending_deletions", "table"],
            ["storage_visible_delete", "trigger"],
            ["storage_visible_insert", "trigger"],
            ["storage_visible_sessions", "table"],
        ],
        "expected": "SPEC",
        "profile": "F2_LJC_CONS",
    },
    {
        "id": "PRIVATE-CP12",
        "label": "catalog-positive/F2_LJC_CONS_COST1",
        "constructor": "PAIRS",
        "pairs": [
            ["attempts", "table"],
            ["capture_health_event_order", "index"],
            ["capture_health_events", "table"],
            ["capture_health_gap_phase", "index"],
            ["capture_health_runs", "table"],
            ["capture_health_tracks", "table"],
            ["chunks", "table"],
            ["content_events", "table"],
            ["content_revision_immutable", "trigger"],
            ["content_revisions", "table"],
            ["content_selections", "table"],
            ["content_session", "index"],
            ["content_summary_requests", "table"],
            ["deleted_sessions", "table"],
            ["events", "table"],
            ["job_checkpoints", "table"],
            ["job_create_receipts", "table"],
            ["job_local_readers", "table"],
            ["job_remote_intents", "table"],
            ["job_session_lookup", "index"],
            ["job_sessions", "table"],
            ["jobs", "table"],
            ["jobs_dedup", "index"],
            ["recoryn_maintenance", "table"],
            ["recoryn_schema_components", "table"],
            ["security_consent_meta", "table"],
            ["security_cost_accounts", "table"],
            ["security_cost_meta", "table"],
            ["security_cost_requests", "table"],
            ["security_execution", "table"],
            ["security_grants_v2", "table"],
            ["security_local_endpoints", "table"],
            ["security_sessions", "table"],
            ["sessions", "table"],
            ["storage_catalog_change", "trigger"],
            ["storage_catalog_delete", "trigger"],
            ["storage_catalog_insert", "trigger"],
            ["storage_catalog_meta", "table"],
            ["storage_events", "table"],
            ["storage_pending_deletions", "table"],
            ["storage_visible_delete", "trigger"],
            ["storage_visible_insert", "trigger"],
            ["storage_visible_sessions", "table"],
        ],
        "expected": "SPEC",
        "profile": "F2_LJC_CONS_COST1",
    },
    {
        "id": "PRIVATE-CP13",
        "label": "catalog-positive/F2_LJC_CONS_COST2",
        "constructor": "PAIRS",
        "pairs": [
            ["attempts", "table"],
            ["capture_health_event_order", "index"],
            ["capture_health_events", "table"],
            ["capture_health_gap_phase", "index"],
            ["capture_health_runs", "table"],
            ["capture_health_tracks", "table"],
            ["chunks", "table"],
            ["content_events", "table"],
            ["content_revision_immutable", "trigger"],
            ["content_revisions", "table"],
            ["content_selections", "table"],
            ["content_session", "index"],
            ["content_summary_requests", "table"],
            ["deleted_sessions", "table"],
            ["events", "table"],
            ["job_checkpoints", "table"],
            ["job_create_receipts", "table"],
            ["job_local_readers", "table"],
            ["job_remote_intents", "table"],
            ["job_session_lookup", "index"],
            ["job_sessions", "table"],
            ["jobs", "table"],
            ["jobs_dedup", "index"],
            ["recoryn_maintenance", "table"],
            ["recoryn_schema_components", "table"],
            ["security_consent_meta", "table"],
            ["security_cost_accounts", "table"],
            ["security_cost_accounts_v2", "table"],
            ["security_cost_meta", "table"],
            ["security_cost_meta_v2", "table"],
            ["security_cost_requests", "table"],
            ["security_cost_requests_v2", "table"],
            ["security_cost_usage_events", "table"],
            ["security_execution", "table"],
            ["security_grants_v2", "table"],
            ["security_local_endpoints", "table"],
            ["security_sessions", "table"],
            ["sessions", "table"],
            ["storage_catalog_change", "trigger"],
            ["storage_catalog_delete", "trigger"],
            ["storage_catalog_insert", "trigger"],
            ["storage_catalog_meta", "table"],
            ["storage_events", "table"],
            ["storage_pending_deletions", "table"],
            ["storage_visible_delete", "trigger"],
            ["storage_visible_insert", "trigger"],
            ["storage_visible_sessions", "table"],
        ],
        "expected": "SPEC",
        "profile": "F2_LJC_CONS_COST2",
    },
    {
        "id": "PRIVATE-CP14",
        "label": "catalog-positive/F2_LJC_COST1",
        "constructor": "PAIRS",
        "pairs": [
            ["attempts", "table"],
            ["capture_health_event_order", "index"],
            ["capture_health_events", "table"],
            ["capture_health_gap_phase", "index"],
            ["capture_health_runs", "table"],
            ["capture_health_tracks", "table"],
            ["chunks", "table"],
            ["content_events", "table"],
            ["content_revision_immutable", "trigger"],
            ["content_revisions", "table"],
            ["content_selections", "table"],
            ["content_session", "index"],
            ["content_summary_requests", "table"],
            ["deleted_sessions", "table"],
            ["events", "table"],
            ["job_checkpoints", "table"],
            ["job_create_receipts", "table"],
            ["job_local_readers", "table"],
            ["job_remote_intents", "table"],
            ["job_session_lookup", "index"],
            ["job_sessions", "table"],
            ["jobs", "table"],
            ["jobs_dedup", "index"],
            ["recoryn_maintenance", "table"],
            ["recoryn_schema_components", "table"],
            ["security_cost_accounts", "table"],
            ["security_cost_meta", "table"],
            ["security_cost_requests", "table"],
            ["sessions", "table"],
            ["storage_catalog_change", "trigger"],
            ["storage_catalog_delete", "trigger"],
            ["storage_catalog_insert", "trigger"],
            ["storage_catalog_meta", "table"],
            ["storage_events", "table"],
            ["storage_pending_deletions", "table"],
            ["storage_visible_delete", "trigger"],
            ["storage_visible_insert", "trigger"],
            ["storage_visible_sessions", "table"],
        ],
        "expected": "SPEC",
        "profile": "F2_LJC_COST1",
    },
    {
        "id": "PRIVATE-CP15",
        "label": "catalog-positive/F2_LJC_COST2",
        "constructor": "PAIRS",
        "pairs": [
            ["attempts", "table"],
            ["capture_health_event_order", "index"],
            ["capture_health_events", "table"],
            ["capture_health_gap_phase", "index"],
            ["capture_health_runs", "table"],
            ["capture_health_tracks", "table"],
            ["chunks", "table"],
            ["content_events", "table"],
            ["content_revision_immutable", "trigger"],
            ["content_revisions", "table"],
            ["content_selections", "table"],
            ["content_session", "index"],
            ["content_summary_requests", "table"],
            ["deleted_sessions", "table"],
            ["events", "table"],
            ["job_checkpoints", "table"],
            ["job_create_receipts", "table"],
            ["job_local_readers", "table"],
            ["job_remote_intents", "table"],
            ["job_session_lookup", "index"],
            ["job_sessions", "table"],
            ["jobs", "table"],
            ["jobs_dedup", "index"],
            ["recoryn_maintenance", "table"],
            ["recoryn_schema_components", "table"],
            ["security_cost_accounts", "table"],
            ["security_cost_accounts_v2", "table"],
            ["security_cost_meta", "table"],
            ["security_cost_meta_v2", "table"],
            ["security_cost_requests", "table"],
            ["security_cost_requests_v2", "table"],
            ["security_cost_usage_events", "table"],
            ["sessions", "table"],
            ["storage_catalog_change", "trigger"],
            ["storage_catalog_delete", "trigger"],
            ["storage_catalog_insert", "trigger"],
            ["storage_catalog_meta", "table"],
            ["storage_events", "table"],
            ["storage_pending_deletions", "table"],
            ["storage_visible_delete", "trigger"],
            ["storage_visible_insert", "trigger"],
            ["storage_visible_sessions", "table"],
        ],
        "expected": "SPEC",
        "profile": "F2_LJC_COST2",
    },
    {
        "id": "PRIVATE-CP16",
        "label": "catalog-positive/F2_LJ_CONS",
        "constructor": "PAIRS",
        "pairs": [
            ["attempts", "table"],
            ["capture_health_event_order", "index"],
            ["capture_health_events", "table"],
            ["capture_health_gap_phase", "index"],
            ["capture_health_runs", "table"],
            ["capture_health_tracks", "table"],
            ["chunks", "table"],
            ["deleted_sessions", "table"],
            ["events", "table"],
            ["job_checkpoints", "table"],
            ["job_create_receipts", "table"],
            ["job_local_readers", "table"],
            ["job_remote_intents", "table"],
            ["job_session_lookup", "index"],
            ["job_sessions", "table"],
            ["jobs", "table"],
            ["jobs_dedup", "index"],
            ["recoryn_maintenance", "table"],
            ["recoryn_schema_components", "table"],
            ["security_consent_meta", "table"],
            ["security_execution", "table"],
            ["security_grants_v2", "table"],
            ["security_local_endpoints", "table"],
            ["security_sessions", "table"],
            ["sessions", "table"],
            ["storage_catalog_change", "trigger"],
            ["storage_catalog_delete", "trigger"],
            ["storage_catalog_insert", "trigger"],
            ["storage_catalog_meta", "table"],
            ["storage_events", "table"],
            ["storage_pending_deletions", "table"],
            ["storage_visible_delete", "trigger"],
            ["storage_visible_insert", "trigger"],
            ["storage_visible_sessions", "table"],
        ],
        "expected": "SPEC",
        "profile": "F2_LJ_CONS",
    },
    {
        "id": "PRIVATE-CP17",
        "label": "catalog-positive/F2_LJ_CONS_COST1",
        "constructor": "PAIRS",
        "pairs": [
            ["attempts", "table"],
            ["capture_health_event_order", "index"],
            ["capture_health_events", "table"],
            ["capture_health_gap_phase", "index"],
            ["capture_health_runs", "table"],
            ["capture_health_tracks", "table"],
            ["chunks", "table"],
            ["deleted_sessions", "table"],
            ["events", "table"],
            ["job_checkpoints", "table"],
            ["job_create_receipts", "table"],
            ["job_local_readers", "table"],
            ["job_remote_intents", "table"],
            ["job_session_lookup", "index"],
            ["job_sessions", "table"],
            ["jobs", "table"],
            ["jobs_dedup", "index"],
            ["recoryn_maintenance", "table"],
            ["recoryn_schema_components", "table"],
            ["security_consent_meta", "table"],
            ["security_cost_accounts", "table"],
            ["security_cost_meta", "table"],
            ["security_cost_requests", "table"],
            ["security_execution", "table"],
            ["security_grants_v2", "table"],
            ["security_local_endpoints", "table"],
            ["security_sessions", "table"],
            ["sessions", "table"],
            ["storage_catalog_change", "trigger"],
            ["storage_catalog_delete", "trigger"],
            ["storage_catalog_insert", "trigger"],
            ["storage_catalog_meta", "table"],
            ["storage_events", "table"],
            ["storage_pending_deletions", "table"],
            ["storage_visible_delete", "trigger"],
            ["storage_visible_insert", "trigger"],
            ["storage_visible_sessions", "table"],
        ],
        "expected": "SPEC",
        "profile": "F2_LJ_CONS_COST1",
    },
    {
        "id": "PRIVATE-CP18",
        "label": "catalog-positive/F2_LJ_CONS_COST2",
        "constructor": "PAIRS",
        "pairs": [
            ["attempts", "table"],
            ["capture_health_event_order", "index"],
            ["capture_health_events", "table"],
            ["capture_health_gap_phase", "index"],
            ["capture_health_runs", "table"],
            ["capture_health_tracks", "table"],
            ["chunks", "table"],
            ["deleted_sessions", "table"],
            ["events", "table"],
            ["job_checkpoints", "table"],
            ["job_create_receipts", "table"],
            ["job_local_readers", "table"],
            ["job_remote_intents", "table"],
            ["job_session_lookup", "index"],
            ["job_sessions", "table"],
            ["jobs", "table"],
            ["jobs_dedup", "index"],
            ["recoryn_maintenance", "table"],
            ["recoryn_schema_components", "table"],
            ["security_consent_meta", "table"],
            ["security_cost_accounts", "table"],
            ["security_cost_accounts_v2", "table"],
            ["security_cost_meta", "table"],
            ["security_cost_meta_v2", "table"],
            ["security_cost_requests", "table"],
            ["security_cost_requests_v2", "table"],
            ["security_cost_usage_events", "table"],
            ["security_execution", "table"],
            ["security_grants_v2", "table"],
            ["security_local_endpoints", "table"],
            ["security_sessions", "table"],
            ["sessions", "table"],
            ["storage_catalog_change", "trigger"],
            ["storage_catalog_delete", "trigger"],
            ["storage_catalog_insert", "trigger"],
            ["storage_catalog_meta", "table"],
            ["storage_events", "table"],
            ["storage_pending_deletions", "table"],
            ["storage_visible_delete", "trigger"],
            ["storage_visible_insert", "trigger"],
            ["storage_visible_sessions", "table"],
        ],
        "expected": "SPEC",
        "profile": "F2_LJ_CONS_COST2",
    },
    {
        "id": "PRIVATE-CP19",
        "label": "catalog-positive/F2_LJ_COST1",
        "constructor": "PAIRS",
        "pairs": [
            ["attempts", "table"],
            ["capture_health_event_order", "index"],
            ["capture_health_events", "table"],
            ["capture_health_gap_phase", "index"],
            ["capture_health_runs", "table"],
            ["capture_health_tracks", "table"],
            ["chunks", "table"],
            ["deleted_sessions", "table"],
            ["events", "table"],
            ["job_checkpoints", "table"],
            ["job_create_receipts", "table"],
            ["job_local_readers", "table"],
            ["job_remote_intents", "table"],
            ["job_session_lookup", "index"],
            ["job_sessions", "table"],
            ["jobs", "table"],
            ["jobs_dedup", "index"],
            ["recoryn_maintenance", "table"],
            ["recoryn_schema_components", "table"],
            ["security_cost_accounts", "table"],
            ["security_cost_meta", "table"],
            ["security_cost_requests", "table"],
            ["sessions", "table"],
            ["storage_catalog_change", "trigger"],
            ["storage_catalog_delete", "trigger"],
            ["storage_catalog_insert", "trigger"],
            ["storage_catalog_meta", "table"],
            ["storage_events", "table"],
            ["storage_pending_deletions", "table"],
            ["storage_visible_delete", "trigger"],
            ["storage_visible_insert", "trigger"],
            ["storage_visible_sessions", "table"],
        ],
        "expected": "SPEC",
        "profile": "F2_LJ_COST1",
    },
    {
        "id": "PRIVATE-CP20",
        "label": "catalog-positive/F2_LJ_COST2",
        "constructor": "PAIRS",
        "pairs": [
            ["attempts", "table"],
            ["capture_health_event_order", "index"],
            ["capture_health_events", "table"],
            ["capture_health_gap_phase", "index"],
            ["capture_health_runs", "table"],
            ["capture_health_tracks", "table"],
            ["chunks", "table"],
            ["deleted_sessions", "table"],
            ["events", "table"],
            ["job_checkpoints", "table"],
            ["job_create_receipts", "table"],
            ["job_local_readers", "table"],
            ["job_remote_intents", "table"],
            ["job_session_lookup", "index"],
            ["job_sessions", "table"],
            ["jobs", "table"],
            ["jobs_dedup", "index"],
            ["recoryn_maintenance", "table"],
            ["recoryn_schema_components", "table"],
            ["security_cost_accounts", "table"],
            ["security_cost_accounts_v2", "table"],
            ["security_cost_meta", "table"],
            ["security_cost_meta_v2", "table"],
            ["security_cost_requests", "table"],
            ["security_cost_requests_v2", "table"],
            ["security_cost_usage_events", "table"],
            ["sessions", "table"],
            ["storage_catalog_change", "trigger"],
            ["storage_catalog_delete", "trigger"],
            ["storage_catalog_insert", "trigger"],
            ["storage_catalog_meta", "table"],
            ["storage_events", "table"],
            ["storage_pending_deletions", "table"],
            ["storage_visible_delete", "trigger"],
            ["storage_visible_insert", "trigger"],
            ["storage_visible_sessions", "table"],
        ],
        "expected": "SPEC",
        "profile": "F2_LJ_COST2",
    },
    {
        "id": "PRIVATE-CP21",
        "label": "catalog-positive/F2_L_CONS",
        "constructor": "PAIRS",
        "pairs": [
            ["capture_health_event_order", "index"],
            ["capture_health_events", "table"],
            ["capture_health_gap_phase", "index"],
            ["capture_health_runs", "table"],
            ["capture_health_tracks", "table"],
            ["chunks", "table"],
            ["deleted_sessions", "table"],
            ["recoryn_maintenance", "table"],
            ["recoryn_schema_components", "table"],
            ["security_consent_meta", "table"],
            ["security_execution", "table"],
            ["security_grants_v2", "table"],
            ["security_local_endpoints", "table"],
            ["security_sessions", "table"],
            ["sessions", "table"],
            ["storage_catalog_change", "trigger"],
            ["storage_catalog_delete", "trigger"],
            ["storage_catalog_insert", "trigger"],
            ["storage_catalog_meta", "table"],
            ["storage_events", "table"],
            ["storage_pending_deletions", "table"],
            ["storage_visible_delete", "trigger"],
            ["storage_visible_insert", "trigger"],
            ["storage_visible_sessions", "table"],
        ],
        "expected": "SPEC",
        "profile": "F2_L_CONS",
    },
    {
        "id": "PRIVATE-CP22",
        "label": "catalog-positive/F2_L_CONS_COST1",
        "constructor": "PAIRS",
        "pairs": [
            ["capture_health_event_order", "index"],
            ["capture_health_events", "table"],
            ["capture_health_gap_phase", "index"],
            ["capture_health_runs", "table"],
            ["capture_health_tracks", "table"],
            ["chunks", "table"],
            ["deleted_sessions", "table"],
            ["recoryn_maintenance", "table"],
            ["recoryn_schema_components", "table"],
            ["security_consent_meta", "table"],
            ["security_cost_accounts", "table"],
            ["security_cost_meta", "table"],
            ["security_cost_requests", "table"],
            ["security_execution", "table"],
            ["security_grants_v2", "table"],
            ["security_local_endpoints", "table"],
            ["security_sessions", "table"],
            ["sessions", "table"],
            ["storage_catalog_change", "trigger"],
            ["storage_catalog_delete", "trigger"],
            ["storage_catalog_insert", "trigger"],
            ["storage_catalog_meta", "table"],
            ["storage_events", "table"],
            ["storage_pending_deletions", "table"],
            ["storage_visible_delete", "trigger"],
            ["storage_visible_insert", "trigger"],
            ["storage_visible_sessions", "table"],
        ],
        "expected": "SPEC",
        "profile": "F2_L_CONS_COST1",
    },
    {
        "id": "PRIVATE-CP23",
        "label": "catalog-positive/F2_L_CONS_COST2",
        "constructor": "PAIRS",
        "pairs": [
            ["capture_health_event_order", "index"],
            ["capture_health_events", "table"],
            ["capture_health_gap_phase", "index"],
            ["capture_health_runs", "table"],
            ["capture_health_tracks", "table"],
            ["chunks", "table"],
            ["deleted_sessions", "table"],
            ["recoryn_maintenance", "table"],
            ["recoryn_schema_components", "table"],
            ["security_consent_meta", "table"],
            ["security_cost_accounts", "table"],
            ["security_cost_accounts_v2", "table"],
            ["security_cost_meta", "table"],
            ["security_cost_meta_v2", "table"],
            ["security_cost_requests", "table"],
            ["security_cost_requests_v2", "table"],
            ["security_cost_usage_events", "table"],
            ["security_execution", "table"],
            ["security_grants_v2", "table"],
            ["security_local_endpoints", "table"],
            ["security_sessions", "table"],
            ["sessions", "table"],
            ["storage_catalog_change", "trigger"],
            ["storage_catalog_delete", "trigger"],
            ["storage_catalog_insert", "trigger"],
            ["storage_catalog_meta", "table"],
            ["storage_events", "table"],
            ["storage_pending_deletions", "table"],
            ["storage_visible_delete", "trigger"],
            ["storage_visible_insert", "trigger"],
            ["storage_visible_sessions", "table"],
        ],
        "expected": "SPEC",
        "profile": "F2_L_CONS_COST2",
    },
    {
        "id": "PRIVATE-CP24",
        "label": "catalog-positive/F2_L_COST1",
        "constructor": "PAIRS",
        "pairs": [
            ["capture_health_event_order", "index"],
            ["capture_health_events", "table"],
            ["capture_health_gap_phase", "index"],
            ["capture_health_runs", "table"],
            ["capture_health_tracks", "table"],
            ["chunks", "table"],
            ["deleted_sessions", "table"],
            ["recoryn_maintenance", "table"],
            ["recoryn_schema_components", "table"],
            ["security_cost_accounts", "table"],
            ["security_cost_meta", "table"],
            ["security_cost_requests", "table"],
            ["sessions", "table"],
            ["storage_catalog_change", "trigger"],
            ["storage_catalog_delete", "trigger"],
            ["storage_catalog_insert", "trigger"],
            ["storage_catalog_meta", "table"],
            ["storage_events", "table"],
            ["storage_pending_deletions", "table"],
            ["storage_visible_delete", "trigger"],
            ["storage_visible_insert", "trigger"],
            ["storage_visible_sessions", "table"],
        ],
        "expected": "SPEC",
        "profile": "F2_L_COST1",
    },
    {
        "id": "PRIVATE-CP25",
        "label": "catalog-positive/F2_L_COST2",
        "constructor": "PAIRS",
        "pairs": [
            ["capture_health_event_order", "index"],
            ["capture_health_events", "table"],
            ["capture_health_gap_phase", "index"],
            ["capture_health_runs", "table"],
            ["capture_health_tracks", "table"],
            ["chunks", "table"],
            ["deleted_sessions", "table"],
            ["recoryn_maintenance", "table"],
            ["recoryn_schema_components", "table"],
            ["security_cost_accounts", "table"],
            ["security_cost_accounts_v2", "table"],
            ["security_cost_meta", "table"],
            ["security_cost_meta_v2", "table"],
            ["security_cost_requests", "table"],
            ["security_cost_requests_v2", "table"],
            ["security_cost_usage_events", "table"],
            ["sessions", "table"],
            ["storage_catalog_change", "trigger"],
            ["storage_catalog_delete", "trigger"],
            ["storage_catalog_insert", "trigger"],
            ["storage_catalog_meta", "table"],
            ["storage_events", "table"],
            ["storage_pending_deletions", "table"],
            ["storage_visible_delete", "trigger"],
            ["storage_visible_insert", "trigger"],
            ["storage_visible_sessions", "table"],
        ],
        "expected": "SPEC",
        "profile": "F2_L_COST2",
    },
    {
        "id": "PRIVATE-CP26",
        "label": "catalog-positive/F2_S_CONS",
        "constructor": "PAIRS",
        "pairs": [
            ["recoryn_maintenance", "table"],
            ["recoryn_schema_components", "table"],
            ["security_consent_meta", "table"],
            ["security_execution", "table"],
            ["security_grants_v2", "table"],
            ["security_local_endpoints", "table"],
            ["security_sessions", "table"],
        ],
        "expected": "SPEC",
        "profile": "F2_S_CONS",
    },
    {
        "id": "PRIVATE-CP27",
        "label": "catalog-positive/F2_S_CONS_COST1",
        "constructor": "PAIRS",
        "pairs": [
            ["recoryn_maintenance", "table"],
            ["recoryn_schema_components", "table"],
            ["security_consent_meta", "table"],
            ["security_cost_accounts", "table"],
            ["security_cost_meta", "table"],
            ["security_cost_requests", "table"],
            ["security_execution", "table"],
            ["security_grants_v2", "table"],
            ["security_local_endpoints", "table"],
            ["security_sessions", "table"],
        ],
        "expected": "SPEC",
        "profile": "F2_S_CONS_COST1",
    },
    {
        "id": "PRIVATE-CP28",
        "label": "catalog-positive/F2_S_CONS_COST2",
        "constructor": "PAIRS",
        "pairs": [
            ["recoryn_maintenance", "table"],
            ["recoryn_schema_components", "table"],
            ["security_consent_meta", "table"],
            ["security_cost_accounts", "table"],
            ["security_cost_accounts_v2", "table"],
            ["security_cost_meta", "table"],
            ["security_cost_meta_v2", "table"],
            ["security_cost_requests", "table"],
            ["security_cost_requests_v2", "table"],
            ["security_cost_usage_events", "table"],
            ["security_execution", "table"],
            ["security_grants_v2", "table"],
            ["security_local_endpoints", "table"],
            ["security_sessions", "table"],
        ],
        "expected": "SPEC",
        "profile": "F2_S_CONS_COST2",
    },
    {
        "id": "PRIVATE-CP29",
        "label": "catalog-positive/F2_S_COST1",
        "constructor": "PAIRS",
        "pairs": [
            ["recoryn_maintenance", "table"],
            ["recoryn_schema_components", "table"],
            ["security_cost_accounts", "table"],
            ["security_cost_meta", "table"],
            ["security_cost_requests", "table"],
        ],
        "expected": "SPEC",
        "profile": "F2_S_COST1",
    },
    {
        "id": "PRIVATE-CP30",
        "label": "catalog-positive/F2_S_COST2",
        "constructor": "PAIRS",
        "pairs": [
            ["recoryn_maintenance", "table"],
            ["recoryn_schema_components", "table"],
            ["security_cost_accounts", "table"],
            ["security_cost_accounts_v2", "table"],
            ["security_cost_meta", "table"],
            ["security_cost_meta_v2", "table"],
            ["security_cost_requests", "table"],
            ["security_cost_requests_v2", "table"],
            ["security_cost_usage_events", "table"],
        ],
        "expected": "SPEC",
        "profile": "F2_S_COST2",
    },
    {
        "id": "PRIVATE-CP31",
        "label": "catalog-delta/extra",
        "constructor": "PAIRS",
        "pairs": [
            ["attempts", "table"],
            ["events", "table"],
            ["job_checkpoints", "table"],
            ["job_create_receipts", "table"],
            ["job_local_readers", "table"],
            ["job_remote_intents", "table"],
            ["job_session_lookup", "index"],
            ["job_sessions", "table"],
            ["jobs", "table"],
            ["jobs_dedup", "index"],
            ["recoryn_maintenance", "table"],
            ["recoryn_schema_components", "table"],
            ["unregistered_extra", "table"],
        ],
        "expected": "NONE",
        "profile": None,
        "source_duplicate_expectation_unresolved_preserved": False,
    },
    {
        "id": "PRIVATE-CP32",
        "label": "catalog-delta/missing",
        "constructor": "PAIRS",
        "pairs": [
            ["attempts", "table"],
            ["events", "table"],
            ["job_create_receipts", "table"],
            ["job_local_readers", "table"],
            ["job_remote_intents", "table"],
            ["job_session_lookup", "index"],
            ["job_sessions", "table"],
            ["jobs", "table"],
            ["jobs_dedup", "index"],
            ["recoryn_maintenance", "table"],
            ["recoryn_schema_components", "table"],
        ],
        "expected": "NONE",
        "profile": None,
        "source_duplicate_expectation_unresolved_preserved": False,
    },
    {
        "id": "PRIVATE-CP33",
        "label": "catalog-delta/kind",
        "constructor": "PAIRS",
        "pairs": [
            ["attempts", "table"],
            ["events", "table"],
            ["job_checkpoints", "index"],
            ["job_create_receipts", "table"],
            ["job_local_readers", "table"],
            ["job_remote_intents", "table"],
            ["job_session_lookup", "index"],
            ["job_sessions", "table"],
            ["jobs", "table"],
            ["jobs_dedup", "index"],
            ["recoryn_maintenance", "table"],
            ["recoryn_schema_components", "table"],
        ],
        "expected": "NONE",
        "profile": None,
        "source_duplicate_expectation_unresolved_preserved": False,
    },
    {
        "id": "PRIVATE-CP34",
        "label": "catalog-delta/duplicate",
        "constructor": "PAIRS",
        "pairs": [
            ["attempts", "table"],
            ["events", "table"],
            ["job_checkpoints", "table"],
            ["job_create_receipts", "table"],
            ["job_local_readers", "table"],
            ["job_remote_intents", "table"],
            ["job_session_lookup", "index"],
            ["job_sessions", "table"],
            ["jobs", "table"],
            ["jobs", "table"],
            ["jobs_dedup", "index"],
            ["recoryn_maintenance", "table"],
            ["recoryn_schema_components", "table"],
        ],
        "expected": "VALUE_ERROR",
        "profile": None,
        "source_duplicate_expectation_unresolved_preserved": True,
    },
    {
        "id": "PRIVATE-CP35",
        "label": "catalog-delta/foreign-component-object",
        "constructor": "PAIRS",
        "pairs": [
            ["attempts", "table"],
            ["content_summary_requests", "table"],
            ["events", "table"],
            ["job_create_receipts", "table"],
            ["job_local_readers", "table"],
            ["job_remote_intents", "table"],
            ["job_session_lookup", "index"],
            ["job_sessions", "table"],
            ["jobs", "table"],
            ["jobs_dedup", "index"],
            ["recoryn_maintenance", "table"],
            ["recoryn_schema_components", "table"],
        ],
        "expected": "NONE",
        "profile": None,
        "source_duplicate_expectation_unresolved_preserved": False,
    },
    {
        "id": "PRIVATE-CP36",
        "label": "catalog-role/jobs-with-security-no-library",
        "constructor": "PAIRS",
        "pairs": [
            ["attempts", "table"],
            ["events", "table"],
            ["job_checkpoints", "table"],
            ["job_create_receipts", "table"],
            ["job_local_readers", "table"],
            ["job_remote_intents", "table"],
            ["job_session_lookup", "index"],
            ["job_sessions", "table"],
            ["jobs", "table"],
            ["jobs_dedup", "index"],
            ["recoryn_maintenance", "table"],
            ["recoryn_schema_components", "table"],
            ["security_consent_meta", "table"],
            ["security_execution", "table"],
            ["security_grants_v2", "table"],
            ["security_local_endpoints", "table"],
            ["security_sessions", "table"],
        ],
        "expected": "NONE",
        "profile": None,
    },
    {
        "id": "PRIVATE-CP37",
        "label": "catalog-role/bare-content",
        "constructor": "PAIRS",
        "pairs": [
            ["content_events", "table"],
            ["content_revision_immutable", "trigger"],
            ["content_revisions", "table"],
            ["content_selections", "table"],
            ["content_session", "index"],
            ["content_summary_requests", "table"],
            ["recoryn_maintenance", "table"],
            ["recoryn_schema_components", "table"],
        ],
        "expected": "NONE",
        "profile": None,
    },
    {
        "id": "PRIVATE-CP38",
        "label": "catalog-role/cost2-without-v1",
        "constructor": "PAIRS",
        "pairs": [
            ["recoryn_maintenance", "table"],
            ["recoryn_schema_components", "table"],
            ["security_cost_accounts_v2", "table"],
            ["security_cost_meta_v2", "table"],
            ["security_cost_requests_v2", "table"],
            ["security_cost_usage_events", "table"],
        ],
        "expected": "NONE",
        "profile": None,
    },
    {
        "id": "PRIVATE-CP39",
        "label": "root-fix1/OUTER_LIST",
        "constructor": "OUTER_LIST",
        "pairs": [
            ["attempts", "table"],
            ["events", "table"],
            ["job_checkpoints", "table"],
            ["job_create_receipts", "table"],
            ["job_local_readers", "table"],
            ["job_remote_intents", "table"],
            ["job_session_lookup", "index"],
            ["job_sessions", "table"],
            ["jobs", "table"],
            ["jobs_dedup", "index"],
            ["recoryn_maintenance", "table"],
            ["recoryn_schema_components", "table"],
        ],
        "expected": "VALUE_ERROR",
        "profile": None,
    },
    {
        "id": "PRIVATE-CP40",
        "label": "root-fix1/PAIR_LIST",
        "constructor": "PAIR_LIST",
        "pairs": [
            ["attempts", "table"],
            ["events", "table"],
            ["job_checkpoints", "table"],
            ["job_create_receipts", "table"],
            ["job_local_readers", "table"],
            ["job_remote_intents", "table"],
            ["job_session_lookup", "index"],
            ["job_sessions", "table"],
            ["jobs", "table"],
            ["jobs_dedup", "index"],
            ["recoryn_maintenance", "table"],
            ["recoryn_schema_components", "table"],
        ],
        "expected": "VALUE_ERROR",
        "profile": None,
    },
    {
        "id": "PRIVATE-CP41",
        "label": "root-fix1/PAIR_LEN1",
        "constructor": "PAIR_LEN1",
        "pairs": [
            ["attempts", "table"],
            ["events", "table"],
            ["job_checkpoints", "table"],
            ["job_create_receipts", "table"],
            ["job_local_readers", "table"],
            ["job_remote_intents", "table"],
            ["job_session_lookup", "index"],
            ["job_sessions", "table"],
            ["jobs", "table"],
            ["jobs_dedup", "index"],
            ["recoryn_maintenance", "table"],
            ["recoryn_schema_components", "table"],
        ],
        "expected": "VALUE_ERROR",
        "profile": None,
    },
    {
        "id": "PRIVATE-CP42",
        "label": "root-fix1/NAME_INT",
        "constructor": "NAME_INT",
        "pairs": [
            ["attempts", "table"],
            ["events", "table"],
            ["job_checkpoints", "table"],
            ["job_create_receipts", "table"],
            ["job_local_readers", "table"],
            ["job_remote_intents", "table"],
            ["job_session_lookup", "index"],
            ["job_sessions", "table"],
            ["jobs", "table"],
            ["jobs_dedup", "index"],
            ["recoryn_maintenance", "table"],
            ["recoryn_schema_components", "table"],
        ],
        "expected": "VALUE_ERROR",
        "profile": None,
    },
    {
        "id": "PRIVATE-CP43",
        "label": "root-fix1/KIND_BOOL",
        "constructor": "KIND_BOOL",
        "pairs": [
            ["attempts", "table"],
            ["events", "table"],
            ["job_checkpoints", "table"],
            ["job_create_receipts", "table"],
            ["job_local_readers", "table"],
            ["job_remote_intents", "table"],
            ["job_session_lookup", "index"],
            ["job_sessions", "table"],
            ["jobs", "table"],
            ["jobs_dedup", "index"],
            ["recoryn_maintenance", "table"],
            ["recoryn_schema_components", "table"],
        ],
        "expected": "VALUE_ERROR",
        "profile": None,
    },
    {
        "id": "PRIVATE-CP44",
        "label": "root-fix1/UNKNOWN_KIND",
        "constructor": "UNKNOWN_KIND",
        "pairs": [
            ["attempts", "table"],
            ["events", "table"],
            ["job_checkpoints", "table"],
            ["job_create_receipts", "table"],
            ["job_local_readers", "table"],
            ["job_remote_intents", "table"],
            ["job_session_lookup", "index"],
            ["job_sessions", "table"],
            ["jobs", "table"],
            ["jobs_dedup", "index"],
            ["recoryn_maintenance", "table"],
            ["recoryn_schema_components", "table"],
        ],
        "expected": "VALUE_ERROR",
        "profile": None,
    },
    {
        "id": "PRIVATE-CP45",
        "label": "root-fix1/EMPTY",
        "constructor": "EMPTY",
        "pairs": [
            ["attempts", "table"],
            ["events", "table"],
            ["job_checkpoints", "table"],
            ["job_create_receipts", "table"],
            ["job_local_readers", "table"],
            ["job_remote_intents", "table"],
            ["job_session_lookup", "index"],
            ["job_sessions", "table"],
            ["jobs", "table"],
            ["jobs_dedup", "index"],
            ["recoryn_maintenance", "table"],
            ["recoryn_schema_components", "table"],
        ],
        "expected": "NONE",
        "profile": None,
    },
    {
        "id": "PRIVATE-CP46",
        "label": "root-fix1/EMPTY_NAME",
        "constructor": "EMPTY_NAME",
        "pairs": [
            ["attempts", "table"],
            ["events", "table"],
            ["job_checkpoints", "table"],
            ["job_create_receipts", "table"],
            ["job_local_readers", "table"],
            ["job_remote_intents", "table"],
            ["job_session_lookup", "index"],
            ["job_sessions", "table"],
            ["jobs", "table"],
            ["jobs_dedup", "index"],
            ["recoryn_maintenance", "table"],
            ["recoryn_schema_components", "table"],
        ],
        "expected": "VALUE_ERROR",
        "profile": None,
    },
    {
        "id": "PRIVATE-CP47",
        "label": "root-fix1/DUP_NAME_KIND",
        "constructor": "DUP_NAME_KIND",
        "pairs": [
            ["attempts", "table"],
            ["events", "table"],
            ["job_checkpoints", "table"],
            ["job_create_receipts", "table"],
            ["job_local_readers", "table"],
            ["job_remote_intents", "table"],
            ["job_session_lookup", "index"],
            ["job_sessions", "table"],
            ["jobs", "table"],
            ["jobs_dedup", "index"],
            ["recoryn_maintenance", "table"],
            ["recoryn_schema_components", "table"],
        ],
        "expected": "VALUE_ERROR",
        "profile": None,
    },
    {
        "id": "PRIVATE-CP48",
        "label": "root-fix1/OUTER_TUPLE_SUBCLASS",
        "constructor": "OUTER_TUPLE_SUBCLASS",
        "pairs": [
            ["attempts", "table"],
            ["events", "table"],
            ["job_checkpoints", "table"],
            ["job_create_receipts", "table"],
            ["job_local_readers", "table"],
            ["job_remote_intents", "table"],
            ["job_session_lookup", "index"],
            ["job_sessions", "table"],
            ["jobs", "table"],
            ["jobs_dedup", "index"],
            ["recoryn_maintenance", "table"],
            ["recoryn_schema_components", "table"],
        ],
        "expected": "VALUE_ERROR",
        "profile": None,
    },
    {
        "id": "PRIVATE-CP49",
        "label": "root-fix1/PAIR_TUPLE_SUBCLASS",
        "constructor": "PAIR_TUPLE_SUBCLASS",
        "pairs": [
            ["attempts", "table"],
            ["events", "table"],
            ["job_checkpoints", "table"],
            ["job_create_receipts", "table"],
            ["job_local_readers", "table"],
            ["job_remote_intents", "table"],
            ["job_session_lookup", "index"],
            ["job_sessions", "table"],
            ["jobs", "table"],
            ["jobs_dedup", "index"],
            ["recoryn_maintenance", "table"],
            ["recoryn_schema_components", "table"],
        ],
        "expected": "VALUE_ERROR",
        "profile": None,
    },
    {
        "id": "PRIVATE-CP50",
        "label": "root-fix1/NAME_STR_SUBCLASS",
        "constructor": "NAME_STR_SUBCLASS",
        "pairs": [
            ["attempts", "table"],
            ["events", "table"],
            ["job_checkpoints", "table"],
            ["job_create_receipts", "table"],
            ["job_local_readers", "table"],
            ["job_remote_intents", "table"],
            ["job_session_lookup", "index"],
            ["job_sessions", "table"],
            ["jobs", "table"],
            ["jobs_dedup", "index"],
            ["recoryn_maintenance", "table"],
            ["recoryn_schema_components", "table"],
        ],
        "expected": "VALUE_ERROR",
        "profile": None,
    },
    {
        "id": "PRIVATE-CP51",
        "label": "root-fix1/KIND_STR_SUBCLASS",
        "constructor": "KIND_STR_SUBCLASS",
        "pairs": [
            ["attempts", "table"],
            ["events", "table"],
            ["job_checkpoints", "table"],
            ["job_create_receipts", "table"],
            ["job_local_readers", "table"],
            ["job_remote_intents", "table"],
            ["job_session_lookup", "index"],
            ["job_sessions", "table"],
            ["jobs", "table"],
            ["jobs_dedup", "index"],
            ["recoryn_maintenance", "table"],
            ["recoryn_schema_components", "table"],
        ],
        "expected": "VALUE_ERROR",
        "profile": None,
    },
]
_CP_IDS = tuple("PRIVATE-CP" + str(n).zfill(2) for n in range(1, 52))
_CP_HOOKS: list[str] = []
_CP_OBS: list[dict] = []
_CP_PROP_OBS: list[dict] = []
_CP_GOLDEN = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures/g09_schema_v1.json").read_text(encoding="utf8")
)


class _CPTuple(tuple):
    def __getattribute__(self, name):
        _CP_HOOKS.append("tuple.getattribute")
        return tuple.__getattribute__(self, name)

    def __iter__(self):
        _CP_HOOKS.append("tuple.iter")
        return tuple.__iter__(self)

    def __len__(self):
        _CP_HOOKS.append("tuple.len")
        return tuple.__len__(self)

    def __getitem__(self, key):
        _CP_HOOKS.append("tuple.getitem")
        return tuple.__getitem__(self, key)

    def __hash__(self):
        _CP_HOOKS.append("tuple.hash")
        return tuple.__hash__(self)

    def __eq__(self, other):
        _CP_HOOKS.append("tuple.eq")
        return tuple.__eq__(self, other)

    def __str__(self):
        _CP_HOOKS.append("tuple.str")
        return tuple.__str__(self)

    def __repr__(self):
        _CP_HOOKS.append("tuple.repr")
        return tuple.__repr__(self)


class _CPStr(str):
    def __getattribute__(self, name):
        _CP_HOOKS.append("str.getattribute")
        return str.__getattribute__(self, name)

    def __iter__(self):
        _CP_HOOKS.append("str.iter")
        return str.__iter__(self)

    def __getitem__(self, key):
        _CP_HOOKS.append("str.getitem")
        return str.__getitem__(self, key)

    def __len__(self):
        _CP_HOOKS.append("str.len")
        return str.__len__(self)

    def __hash__(self):
        _CP_HOOKS.append("str.hash")
        return str.__hash__(self)

    def __eq__(self, other):
        _CP_HOOKS.append("str.eq")
        return str.__eq__(self, other)

    def __lt__(self, other):
        _CP_HOOKS.append("str.lt")
        return str.__lt__(self, other)

    def __str__(self):
        _CP_HOOKS.append("str.str")
        return str.__str__(self)

    def __repr__(self):
        _CP_HOOKS.append("str.repr")
        return str.__repr__(self)

    def __int__(self):
        _CP_HOOKS.append("str.int")
        return 1


def _cp_construct(row):
    pairs = tuple(tuple(pair) for pair in row["pairs"])
    constructor = row["constructor"]
    if constructor == "PAIRS":
        return pairs
    if constructor == "EMPTY":
        return ()
    if constructor == "OUTER_LIST":
        return list(pairs)
    if constructor == "OUTER_TUPLE_SUBCLASS":
        return _CPTuple(pairs)
    if constructor == "DUP_NAME_KIND":
        return (*pairs, ("jobs", "view"))
    index = pairs.index(("jobs", "table"))
    changes = {
        "PAIR_LIST": ["jobs", "table"],
        "PAIR_LEN1": ("jobs",),
        "NAME_INT": (1, "table"),
        "KIND_BOOL": ("jobs", True),
        "UNKNOWN_KIND": ("jobs", "unknown"),
        "EMPTY_NAME": ("", "table"),
        "PAIR_TUPLE_SUBCLASS": _CPTuple(("jobs", "table")),
        "NAME_STR_SUBCLASS": (_CPStr("jobs"), "table"),
        "KIND_STR_SUBCLASS": ("jobs", _CPStr("table")),
    }
    return (*pairs[:index], changes[constructor], *pairs[index + 1 :])


def _cp_expected(profile):
    hand = _CP_GOLDEN["target_profiles"][profile]
    components = tuple(tuple(row[:3]) for row in hand["expected_registry_rows"])
    owned = tuple(
        sorted(
            (obj["name"], obj["kind"])
            for name in hand["components"]
            for obj in _CP_GOLDEN["components"][name]["model"]["objects"]
        )
    )
    rows = tuple(tuple(row) for row in hand["expected_registry_rows"])
    return profile, components, owned, rows


def _cp_spec_fields(value):
    return value.profile_id, value.components, value.owned_objects, value.registry_rows


def _cp_actual_call(value, record):
    events = []
    _CP_HOOKS.clear()
    with _management_no_io(events):
        result, error = _wire_capture(lambda: s._current_profile_candidate(value))
    record.update(
        status="RETURNED" if error is None else "RAISED",
        error=type(error).__name__ if error else None,
        hooks=tuple(_CP_HOOKS),
        IO=tuple(events),
        returned_type=type(result).__name__,
    )
    assert record["hooks"] == (), "CP_EXACT_TYPE_BEFORE_HOSTILE_PROTOCOLS"
    assert record["IO"] == (), "CP_PRIVATE_SQL_AND_IO_ZERO"
    return result, error


@pytest.mark.unit
@pytest.mark.parametrize("row", _CP_ROWS, ids=[row["id"] for row in _CP_ROWS])
def test_private_current_profile_candidate(row):
    value = _cp_construct(row)
    record = {"id": row["id"], "constructor": row["constructor"]}
    _CP_OBS.append(record)
    result, error = _cp_actual_call(value, record)
    if row["expected"] == "VALUE_ERROR":
        goal = (
            "M03_CURRENT_PROFILE_DUPLICATE_MUST_REJECT"
            if row["id"] == "PRIVATE-CP34"
            else "CP_EXACT_VALUE_ERROR"
        )
        assert type(error) is ValueError, goal
        assert error.args == ("INVALID_CURRENT_PROFILE_INPUT",)
        assert str(error) == "INVALID_CURRENT_PROFILE_INPUT"
        assert repr(error) == "ValueError('INVALID_CURRENT_PROFILE_INPUT')"
        assert result is None
    elif row["expected"] == "NONE":
        assert error is None, "CP_VALID_UNMATCHED_MUST_RETURN"
        goal = (
            "M01_CURRENT_PROFILE_EXTRA_MUST_NOT_MATCH"
            if row["id"] == "PRIVATE-CP31"
            else "M02_CURRENT_PROFILE_KIND_MUST_MATCH"
            if row["id"] == "PRIVATE-CP33"
            else "CP_EXPECT_NO_MATCH"
        )
        assert result is None, goal
    else:
        assert error is None, "CP_NORMAL_ACTUAL_RETURN"
        assert type(result) is s._CurrentProfileSpec
        expected = _cp_expected(row["profile"])
        assert result.profile_id == expected[0]
        assert result.components == expected[1], "M04_CURRENT_PROFILE_FIXED_COMPONENT_FP"
        assert result.owned_objects == expected[2]
        assert result.registry_rows == expected[3]
        assert (
            type(result.components)
            is type(result.owned_objects)
            is type(result.registry_rows)
            is tuple
        )
        assert all(
            type(item) is tuple
            for group in (result.components, result.owned_objects, result.registry_rows)
            for item in group
        )
        assert not hasattr(result, "__dict__")
        assert row["profile"] not in repr(result)


@pytest.mark.unit
def test_private_current_profile_literal_audit(request):
    assert tuple(row["id"] for row in _CP_ROWS) == _CP_IDS
    assert len(_CP_IDS) == len(set(_CP_IDS)) == 51
    assert Counter(row["expected"] for row in _CP_ROWS) == {
        "SPEC": 30,
        "NONE": 8,
        "VALUE_ERROR": 13,
    }
    names = [row["profile"] for row in _CP_ROWS[:30]]
    assert len(names) == len(set(names)) == 30 and set(names) == set(_CP_GOLDEN["target_profiles"])
    signatures = []
    for row in _CP_ROWS[:30]:
        expected = _cp_expected(row["profile"])
        assert tuple(map(tuple, row["pairs"])) == expected[2]
        assert len(expected[2]) == len({name for name, _ in expected[2]})
        signatures.append(expected[2])
    assert len(set(signatures)) == 30
    assert dataclasses.is_dataclass(s._CurrentProfileSpec)
    assert tuple(field.name for field in dataclasses.fields(s._CurrentProfileSpec)) == (
        "profile_id",
        "components",
        "owned_objects",
        "registry_rows",
    )
    assert s._CurrentProfileSpec.__dataclass_params__.frozen
    assert not s._CurrentProfileSpec.__dataclass_params__.repr
    own = [
        item.nodeid
        for item in request.session.items
        if "::test_private_current_profile_" in item.nodeid
    ]
    declared = [
        "tests/unit/test_schema_catalog.py::test_private_current_profile_candidate[" + ident + "]"
        for ident in _CP_IDS
    ]
    declared += [
        "tests/unit/test_schema_catalog.py::test_private_current_profile_literal_audit",
        "tests/unit/test_schema_catalog.py::test_private_current_profile_order_and_immutability",
    ]
    assert len(own) == len(set(own)) and set(own) <= set(declared)
    assert not any(
        item.get_closest_marker("skip") or item.get_closest_marker("xfail")
        for item in request.session.items
        if item.nodeid in set(own)
    )


@pytest.mark.unit
def test_private_current_profile_order_and_immutability():
    rng = random.Random(1401)
    for row in _CP_ROWS[:30]:
        expected = _cp_expected(row["profile"])
        original = tuple(tuple(pair) for pair in row["pairs"])
        for ordinal in range(5):
            shuffled = list(original)
            rng.shuffle(shuffled)
            supplied = tuple(shuffled)
            before = tuple(supplied)
            record = {"profile": row["profile"], "shuffle": ordinal}
            _CP_PROP_OBS.append(record)
            result, error = _cp_actual_call(supplied, record)
            assert error is None and type(result) is s._CurrentProfileSpec
            assert _cp_spec_fields(result) == expected
            assert supplied == before
            with pytest.raises(dataclasses.FrozenInstanceError):
                result.profile_id = "changed"
            with pytest.raises(TypeError):
                result.components[0][0] = "changed"
            assert _cp_spec_fields(result) == expected
    assert len(_CP_PROP_OBS) == 150


# D15: fixed pre-execution hand program; no ignored-build runtime input.
_SEAM_LABELS = (
    "READ_OK",
    "UNKNOWN_COMPONENT",
    "MISSING_REQUIRED",
    "CURSOR_ERROR",
    "ROW_FACTORY_ERROR",
    "EXECUTE_ERROR",
    "FETCH_ERROR",
    "CLOSE_ONLY",
    "OTHER_SQLITE_ERROR",
    "DUAL_SQLITE",
    "CLOSE_NONSQLITE",
    "DUAL_CLOSE_NONSQLITE",
    "NONSQLITE_VALUEERROR",
    "INTERRUPT",
    "EXPECTED_OUTSIDE",
    "INDEX_READ_ERROR",
    "TABLE_READ_ERROR",
    "PRIVATE_WIRE_OK",
    "LAST_STAMP_ERROR",
    "LAST_STAMP_CHANGED",
)
_SEAM_LITERAL_JSON = (
    '{"labels":["READ_OK","UNKNOWN_COMPONENT","MISSING_REQUIRED","CURSOR_ERROR","ROW_FACTORY_'
    'ERROR","EXECUTE_ERROR","FETCH_ERROR","CLOSE_ONLY","OTHER_SQLITE_ERROR","DUAL_SQLITE","CL'
    'OSE_NONSQLITE","DUAL_CLOSE_NONSQLITE","NONSQLITE_VALUEERROR","INTERRUPT","EXPECTED_OUTSI'
    'DE","INDEX_READ_ERROR","TABLE_READ_ERROR","PRIVATE_WIRE_OK","LAST_STAMP_ERROR","LAST_STA'
    'MP_CHANGED"],"program":[{"read":1,"cursor":"r1","sql":"PRAGMA main.schema_version","rows'
    '":[[7]]},{"read":2,"cursor":"r2","sql":"SELECT type,name,tbl_name,sql FROM main.sqlite_s'
    'chema","rows":[["table","job_checkpoints","job_checkpoints","CREATE TABLE IF NOT EXISTS '
    "job_checkpoints (job_id TEXT NOT NULL REFERENCES jobs(job_id), attempt_id TEXT NOT NULL,"
    ' result_ref TEXT NOT NULL, UNIQUE(job_id,result_ref));"],["index","sqlite_autoindex_job_'
    'checkpoints_1","job_checkpoints",null]]},{"read":3,"cursor":"r3","sql":"PRAGMA main.tabl'
    'e_xinfo(\\"job_checkpoints\\")","rows":[[0,"job_id","TEXT",1,null,0,0],[1,"attempt_id","TE'
    'XT",1,null,0,0],[2,"result_ref","TEXT",1,null,0,0]]},{"read":4,"cursor":"r4","sql":"PRAG'
    'MA main.foreign_key_list(\\"job_checkpoints\\")","rows":[[0,0,"jobs","job_id","job_id","NO'
    ' ACTION","NO ACTION","NONE"]]},{"read":5,"cursor":"r5","sql":"PRAGMA main.index_list(\\"j'
    'ob_checkpoints\\")","rows":[[0,"sqlite_autoindex_job_checkpoints_1",1,"u",0]]},{"read":6,'
    '"cursor":"r6","sql":"PRAGMA main.index_xinfo(\\"sqlite_autoindex_job_checkpoints_1\\")","r'
    'ows":[[0,0,"job_id",0,"BINARY",1],[1,2,"result_ref",0,"BINARY",1],[2,-1,null,0,"BINARY",'
    '0]]},{"read":7,"cursor":"r7","sql":"PRAGMA main.schema_version","rows":[[7]]}],"anchor":'
    '{"SC06_primary":"tests/unit/test_schema_catalog.py::test_component_shape_wire[G09a-X-SC-'
    '06]","SC06_case_literal":["G09a-X-SC-06","jobs.checkpoints",null],"DDL_utf8":"CREATE TAB'
    "LE IF NOT EXISTS job_checkpoints (job_id TEXT NOT NULL REFERENCES jobs(job_id), attempt_"
    'id TEXT NOT NULL, result_ref TEXT NOT NULL, UNIQUE(job_id,result_ref));","DDL_sha256":"7'
    'e15e84a716ef92728b9b44483555164017fa0a5fe17962bfac05d806fc0865a","golden_pointer":"/comp'
    'onents/jobs.checkpoints","model":{"component":"jobs.checkpoints","format":"recoryn-shape'
    '-v1","objects":[{"autoincrement":false,"autoindexes":[["u",[["job_id","ASC","BINARY"],["'
    'result_ref","ASC","BINARY"]]]],"checks":[],"columns":[["job_id","TEXT",true,null,0,0,"BI'
    'NARY"],["attempt_id","TEXT",true,null,0,0,"BINARY"],["result_ref","TEXT",true,null,0,0,"'
    'BINARY"]],"foreign_keys":[[["job_id"],"jobs",["job_id"],"NO ACTION","NO ACTION","NONE"]]'
    ',"kind":"table","name":"job_checkpoints","rowid":true,"strict":false}],"version":1},"exp'
    'ected_wire_utf8":"{\\"component\\":\\"jobs.checkpoints\\",\\"format\\":\\"recoryn-shape-v1\\",\\"'
    'objects\\":[{\\"autoincrement\\":false,\\"autoindexes\\":[[\\"u\\",[[\\"job_id\\",\\"ASC\\",\\"BINAR'
    'Y\\"],[\\"result_ref\\",\\"ASC\\",\\"BINARY\\"]]]],\\"checks\\":[],\\"columns\\":[[\\"job_id\\",\\"TEX'
    'T\\",true,null,0,0,\\"BINARY\\"],[\\"attempt_id\\",\\"TEXT\\",true,null,0,0,\\"BINARY\\"],[\\"resu'
    'lt_ref\\",\\"TEXT\\",true,null,0,0,\\"BINARY\\"]],\\"foreign_keys\\":[[[\\"job_id\\"],\\"jobs\\",[\\'
    '"job_id\\"],\\"NO ACTION\\",\\"NO ACTION\\",\\"NONE\\"]],\\"kind\\":\\"table\\",\\"name\\":\\"job_chec'
    'kpoints\\",\\"rowid\\":true,\\"strict\\":false}],\\"version\\":1}","expected_wire_bytes":490,"e'
    'xpected_fingerprint":"recoryn-shape-v1:08ad04f16fc95966ba8c2c01a4c563500fab44faec263d2c7'
    'efdddd72d7c27d5","wire_copied_not_generated_from_model_or_product":true},"routes":[{"rou'
    'te_id":"READ_OK|_read","route":"_read","api_name_future_private_unimplemented":"recoryn.'
    'schema._read","fake_identity":"READ_OK|_read|connection","fresh_all_objects":true,"prepa'
    're_hash_or_raise":false,"expected_model":null,"component_input":"jobs.checkpoints","prog'
    'ram":[{"read":1,"cursor":"r1","sql":"PRAGMA main.schema_version","rows":[[7]]}],"fault":'
    'null,"close_fault":null,"exception_objects_spec_only":{},"outcome":{"final_component_wir'
    'e_return":0,"component_wire_return_not_applicable":true,"kind":"rows","rows":[[7]],"runt'
    'ime_container":"list[tuple]"},"trace_oracle":[{"op":"route.call.enter","api":"recoryn.sc'
    'hema._read"},{"op":"cursor.create.enter","read":1,"cursor":"READ_OK|_read|r1"},{"op":"cu'
    'rsor.create.return","read":1,"cursor":"READ_OK|_read|r1","fresh_cursor":true},{"op":"row'
    '_factory.enter","read":1,"cursor":"READ_OK|_read|r1","value":null},{"op":"row_factory.re'
    'turn","read":1,"cursor":"READ_OK|_read|r1","value":null},{"op":"execute.enter","read":1,'
    '"cursor":"READ_OK|_read|r1","sql":"PRAGMA main.schema_version"},{"op":"execute.return","'
    'read":1,"cursor":"READ_OK|_read|r1","value":"same_cursor"},{"op":"fetchall.enter","read"'
    ':1,"cursor":"READ_OK|_read|r1"},{"op":"fetchall.return","read":1,"cursor":"READ_OK|_read'
    '|r1","rows":[[7]],"runtime_container":"list[tuple]"},{"op":"close.enter","read":1,"curso'
    'r":"READ_OK|_read|r1"},{"op":"close.return","read":1,"cursor":"READ_OK|_read|r1","value"'
    ':null},{"op":"route.return","kind":"rows","rows":[[7]]}],"trace_counts":{"cursor.create.'
    'enter":1,"cursor.create.return":1,"row_factory.enter":1,"row_factory.return":1,"execute.'
    'enter":1,"execute.return":1,"fetchall.enter":1,"fetchall.return":1,"close.enter":1,"clos'
    'e.return":1,"close.raise":0},"internal_canonical_wire_call_count_not_constrained":true,"'
    'native_cleanup_proved":false},{"route_id":"UNKNOWN_COMPONENT|public","route":"public","a'
    'pi_name_future_private_unimplemented":"recoryn.schema.component_shape_wire","fake_identi'
    'ty":"UNKNOWN_COMPONENT|public|connection","fresh_all_objects":true,"prepare_hash_or_rais'
    'e":false,"expected_model":"actual_public_expected_lookup_not_stubbed","component_input":'
    '"unregistered.component","program":[],"fault":null,"close_fault":null,"exception_objects'
    '_spec_only":{"SHAPE":{"identity":"UNKNOWN_COMPONENT|public|SHAPE","exact_class":"builtin'
    's.ValueError","args":["Unsupported component shape"],"str":"Unsupported component shape"'
    ',"repr":"ValueError(\'Unsupported component shape\')","__cause__":null,"__context__":null,'
    '"__suppress_context__":false,"role":"captured_product_created_error","context_fields_are'
    '_post_call_oracle_not_fixture_assignment":true,"fixture_must_not_precreate":true}},"outc'
    'ome":{"final_component_wire_return":0,"component_wire_return_not_applicable":false,"kind'
    '":"exception","error":{"identity":"UNKNOWN_COMPONENT|public|SHAPE","exact_class":"builti'
    'ns.ValueError","args":["Unsupported component shape"],"str":"Unsupported component shape'
    '","repr":"ValueError(\'Unsupported component shape\')","__cause__":null,"__context__":null'
    ',"__suppress_context__":false},"identity_assertion_required":false,"capture_product_crea'
    'ted_error_only":true},"trace_oracle":[{"op":"route.call.enter","api":"recoryn.schema.com'
    'ponent_shape_wire"},{"op":"route.raise","identity":"UNKNOWN_COMPONENT|public|SHAPE","exa'
    'ct_class":"builtins.ValueError"}],"trace_counts":{"cursor.create.enter":0,"cursor.create'
    '.return":0,"row_factory.enter":0,"row_factory.return":0,"execute.enter":0,"execute.retur'
    'n":0,"fetchall.enter":0,"fetchall.return":0,"close.enter":0,"close.return":0,"close.rais'
    'e":0},"internal_canonical_wire_call_count_not_constrained":true,"native_cleanup_proved":'
    'false},{"route_id":"MISSING_REQUIRED|private","route":"private","api_name_future_private'
    '_unimplemented":"recoryn.schema._component_shape_wire_read","fake_identity":"MISSING_REQ'
    'UIRED|private|connection","fresh_all_objects":true,"prepare_hash_or_raise":false,"expect'
    'ed_model":"fresh_deep_copy_of_hand_anchor.model","component_input":"jobs.checkpoints","p'
    'rogram":[{"read":1,"cursor":"r1","sql":"PRAGMA main.schema_version","rows":[[7]]},{"read'
    '":2,"cursor":"r2","sql":"SELECT type,name,tbl_name,sql FROM main.sqlite_schema","rows":['
    ']}],"fault":null,"close_fault":null,"exception_objects_spec_only":{"SHAPE":{"identity":"'
    'MISSING_REQUIRED|private|SHAPE","exact_class":"builtins.ValueError","args":["Unsupported'
    ' component shape"],"str":"Unsupported component shape","repr":"ValueError(\'Unsupported c'
    'omponent shape\')","__cause__":null,"__context__":null,"__suppress_context__":false,"role'
    '":"captured_product_created_error","context_fields_are_post_call_oracle_not_fixture_assi'
    'gnment":true,"fixture_must_not_precreate":true}},"outcome":{"final_component_wire_return'
    '":0,"component_wire_return_not_applicable":false,"kind":"exception","error":{"identity":'
    '"MISSING_REQUIRED|private|SHAPE","exact_class":"builtins.ValueError","args":["Unsupporte'
    'd component shape"],"str":"Unsupported component shape","repr":"ValueError(\'Unsupported '
    'component shape\')","__cause__":null,"__context__":null,"__suppress_context__":false},"id'
    'entity_assertion_required":false,"capture_product_created_error_only":true},"trace_oracl'
    'e":[{"op":"route.call.enter","api":"recoryn.schema._component_shape_wire_read"},{"op":"c'
    'ursor.create.enter","read":1,"cursor":"MISSING_REQUIRED|private|r1"},{"op":"cursor.creat'
    'e.return","read":1,"cursor":"MISSING_REQUIRED|private|r1","fresh_cursor":true},{"op":"ro'
    'w_factory.enter","read":1,"cursor":"MISSING_REQUIRED|private|r1","value":null},{"op":"ro'
    'w_factory.return","read":1,"cursor":"MISSING_REQUIRED|private|r1","value":null},{"op":"e'
    'xecute.enter","read":1,"cursor":"MISSING_REQUIRED|private|r1","sql":"PRAGMA main.schema_'
    'version"},{"op":"execute.return","read":1,"cursor":"MISSING_REQUIRED|private|r1","value"'
    ':"same_cursor"},{"op":"fetchall.enter","read":1,"cursor":"MISSING_REQUIRED|private|r1"},'
    '{"op":"fetchall.return","read":1,"cursor":"MISSING_REQUIRED|private|r1","rows":[[7]],"ru'
    'ntime_container":"list[tuple]"},{"op":"close.enter","read":1,"cursor":"MISSING_REQUIRED|'
    'private|r1"},{"op":"close.return","read":1,"cursor":"MISSING_REQUIRED|private|r1","value'
    '":null},{"op":"cursor.create.enter","read":2,"cursor":"MISSING_REQUIRED|private|r2"},{"o'
    'p":"cursor.create.return","read":2,"cursor":"MISSING_REQUIRED|private|r2","fresh_cursor"'
    ':true},{"op":"row_factory.enter","read":2,"cursor":"MISSING_REQUIRED|private|r2","value"'
    ':null},{"op":"row_factory.return","read":2,"cursor":"MISSING_REQUIRED|private|r2","value'
    '":null},{"op":"execute.enter","read":2,"cursor":"MISSING_REQUIRED|private|r2","sql":"SEL'
    'ECT type,name,tbl_name,sql FROM main.sqlite_schema"},{"op":"execute.return","read":2,"cu'
    'rsor":"MISSING_REQUIRED|private|r2","value":"same_cursor"},{"op":"fetchall.enter","read"'
    ':2,"cursor":"MISSING_REQUIRED|private|r2"},{"op":"fetchall.return","read":2,"cursor":"MI'
    'SSING_REQUIRED|private|r2","rows":[],"runtime_container":"list[tuple]"},{"op":"close.ent'
    'er","read":2,"cursor":"MISSING_REQUIRED|private|r2"},{"op":"close.return","read":2,"curs'
    'or":"MISSING_REQUIRED|private|r2","value":null},{"op":"route.raise","identity":"MISSING_'
    'REQUIRED|private|SHAPE","exact_class":"builtins.ValueError"}],"trace_counts":{"cursor.cr'
    'eate.enter":2,"cursor.create.return":2,"row_factory.enter":2,"row_factory.return":2,"exe'
    'cute.enter":2,"execute.return":2,"fetchall.enter":2,"fetchall.return":2,"close.enter":2,'
    '"close.return":2,"close.raise":0},"internal_canonical_wire_call_count_not_constrained":t'
    'rue,"native_cleanup_proved":false},{"route_id":"MISSING_REQUIRED|public","route":"public'
    '","api_name_future_private_unimplemented":"recoryn.schema.component_shape_wire","fake_id'
    'entity":"MISSING_REQUIRED|public|connection","fresh_all_objects":true,"prepare_hash_or_r'
    'aise":false,"expected_model":"actual_public_expected_lookup_not_stubbed","component_inpu'
    't":"jobs.checkpoints","program":[{"read":1,"cursor":"r1","sql":"PRAGMA main.schema_versi'
    'on","rows":[[7]]},{"read":2,"cursor":"r2","sql":"SELECT type,name,tbl_name,sql FROM main'
    '.sqlite_schema","rows":[]}],"fault":null,"close_fault":null,"exception_objects_spec_only'
    '":{"SHAPE":{"identity":"MISSING_REQUIRED|public|SHAPE","exact_class":"builtins.ValueErro'
    'r","args":["Unsupported component shape"],"str":"Unsupported component shape","repr":"Va'
    'lueError(\'Unsupported component shape\')","__cause__":null,"__context__":null,"__suppress'
    '_context__":false,"role":"captured_product_created_error","context_fields_are_post_call_'
    'oracle_not_fixture_assignment":true,"fixture_must_not_precreate":true}},"outcome":{"fina'
    'l_component_wire_return":0,"component_wire_return_not_applicable":false,"kind":"exceptio'
    'n","error":{"identity":"MISSING_REQUIRED|public|SHAPE","exact_class":"builtins.ValueErro'
    'r","args":["Unsupported component shape"],"str":"Unsupported component shape","repr":"Va'
    'lueError(\'Unsupported component shape\')","__cause__":null,"__context__":null,"__suppress'
    '_context__":false},"identity_assertion_required":false,"capture_product_created_error_on'
    'ly":true},"trace_oracle":[{"op":"route.call.enter","api":"recoryn.schema.component_shape'
    '_wire"},{"op":"cursor.create.enter","read":1,"cursor":"MISSING_REQUIRED|public|r1"},{"op'
    '":"cursor.create.return","read":1,"cursor":"MISSING_REQUIRED|public|r1","fresh_cursor":t'
    'rue},{"op":"row_factory.enter","read":1,"cursor":"MISSING_REQUIRED|public|r1","value":nu'
    'll},{"op":"row_factory.return","read":1,"cursor":"MISSING_REQUIRED|public|r1","value":nu'
    'll},{"op":"execute.enter","read":1,"cursor":"MISSING_REQUIRED|public|r1","sql":"PRAGMA m'
    'ain.schema_version"},{"op":"execute.return","read":1,"cursor":"MISSING_REQUIRED|public|r'
    '1","value":"same_cursor"},{"op":"fetchall.enter","read":1,"cursor":"MISSING_REQUIRED|pub'
    'lic|r1"},{"op":"fetchall.return","read":1,"cursor":"MISSING_REQUIRED|public|r1","rows":['
    '[7]],"runtime_container":"list[tuple]"},{"op":"close.enter","read":1,"cursor":"MISSING_R'
    'EQUIRED|public|r1"},{"op":"close.return","read":1,"cursor":"MISSING_REQUIRED|public|r1",'
    '"value":null},{"op":"cursor.create.enter","read":2,"cursor":"MISSING_REQUIRED|public|r2"'
    '},{"op":"cursor.create.return","read":2,"cursor":"MISSING_REQUIRED|public|r2","fresh_cur'
    'sor":true},{"op":"row_factory.enter","read":2,"cursor":"MISSING_REQUIRED|public|r2","val'
    'ue":null},{"op":"row_factory.return","read":2,"cursor":"MISSING_REQUIRED|public|r2","val'
    'ue":null},{"op":"execute.enter","read":2,"cursor":"MISSING_REQUIRED|public|r2","sql":"SE'
    'LECT type,name,tbl_name,sql FROM main.sqlite_schema"},{"op":"execute.return","read":2,"c'
    'ursor":"MISSING_REQUIRED|public|r2","value":"same_cursor"},{"op":"fetchall.enter","read"'
    ':2,"cursor":"MISSING_REQUIRED|public|r2"},{"op":"fetchall.return","read":2,"cursor":"MIS'
    'SING_REQUIRED|public|r2","rows":[],"runtime_container":"list[tuple]"},{"op":"close.enter'
    '","read":2,"cursor":"MISSING_REQUIRED|public|r2"},{"op":"close.return","read":2,"cursor"'
    ':"MISSING_REQUIRED|public|r2","value":null},{"op":"route.raise","identity":"MISSING_REQU'
    'IRED|public|SHAPE","exact_class":"builtins.ValueError"}],"trace_counts":{"cursor.create.'
    'enter":2,"cursor.create.return":2,"row_factory.enter":2,"row_factory.return":2,"execute.'
    'enter":2,"execute.return":2,"fetchall.enter":2,"fetchall.return":2,"close.enter":2,"clos'
    'e.return":2,"close.raise":0},"internal_canonical_wire_call_count_not_constrained":true,"'
    'native_cleanup_proved":false},{"route_id":"CURSOR_ERROR|private","route":"private","api_'
    'name_future_private_unimplemented":"recoryn.schema._component_shape_wire_read","fake_ide'
    'ntity":"CURSOR_ERROR|private|connection","fresh_all_objects":true,"prepare_hash_or_raise'
    '":false,"expected_model":"fresh_deep_copy_of_hand_anchor.model","component_input":"jobs.'
    'checkpoints","program":[{"read":1,"cursor":"r1","sql":"PRAGMA main.schema_version","rows'
    '":[[7]]}],"fault":{"read":1,"stage":"cursor.create","raise":"E"},"close_fault":null,"exc'
    'eption_objects_spec_only":{"E":{"identity":"CURSOR_ERROR|private|E","exact_class":"sqlit'
    'e3.OperationalError","args":["CURSOR_ERROR_MARKER"],"str":"CURSOR_ERROR_MARKER","repr":"'
    'OperationalError(\'CURSOR_ERROR_MARKER\')","__cause__":null,"__context__":null,"__suppress'
    '_context__":false,"role":"fresh_injected_error","context_fields_are_post_call_oracle_not'
    '_fixture_assignment":true,"construction_initial_state":{"__cause__":null,"__context__":n'
    'ull,"__suppress_context__":false},"fixture_must_not_seed_context":true}},"outcome":{"fin'
    'al_component_wire_return":0,"component_wire_return_not_applicable":false,"kind":"excepti'
    'on","error":{"identity":"CURSOR_ERROR|private|E","exact_class":"sqlite3.OperationalError'
    '","args":["CURSOR_ERROR_MARKER"],"str":"CURSOR_ERROR_MARKER","repr":"OperationalError(\'C'
    'URSOR_ERROR_MARKER\')","__cause__":null,"__context__":null,"__suppress_context__":false},'
    '"identity_assertion_required":true,"capture_product_created_error_only":false},"trace_or'
    'acle":[{"op":"route.call.enter","api":"recoryn.schema._component_shape_wire_read"},{"op"'
    ':"cursor.create.enter","read":1,"cursor":"CURSOR_ERROR|private|r1"},{"op":"cursor.create'
    '.raise","read":1,"cursor":"CURSOR_ERROR|private|r1","identity":"CURSOR_ERROR|private|E"}'
    ',{"op":"route.raise","identity":"CURSOR_ERROR|private|E","exact_class":"sqlite3.Operatio'
    'nalError"}],"trace_counts":{"cursor.create.enter":1,"cursor.create.return":0,"row_factor'
    'y.enter":0,"row_factory.return":0,"execute.enter":0,"execute.return":0,"fetchall.enter":'
    '0,"fetchall.return":0,"close.enter":0,"close.return":0,"close.raise":0},"internal_canoni'
    'cal_wire_call_count_not_constrained":true,"native_cleanup_proved":false},{"route_id":"CU'
    'RSOR_ERROR|public","route":"public","api_name_future_private_unimplemented":"recoryn.sch'
    'ema.component_shape_wire","fake_identity":"CURSOR_ERROR|public|connection","fresh_all_ob'
    'jects":true,"prepare_hash_or_raise":false,"expected_model":"actual_public_expected_looku'
    'p_not_stubbed","component_input":"jobs.checkpoints","program":[{"read":1,"cursor":"r1","'
    'sql":"PRAGMA main.schema_version","rows":[[7]]}],"fault":{"read":1,"stage":"cursor.creat'
    'e","raise":"E"},"close_fault":null,"exception_objects_spec_only":{"E":{"identity":"CURSO'
    'R_ERROR|public|E","exact_class":"sqlite3.OperationalError","args":["CURSOR_ERROR_MARKER"'
    '],"str":"CURSOR_ERROR_MARKER","repr":"OperationalError(\'CURSOR_ERROR_MARKER\')","__cause_'
    '_":null,"__context__":null,"__suppress_context__":false,"role":"fresh_injected_error","c'
    'ontext_fields_are_post_call_oracle_not_fixture_assignment":true,"construction_initial_st'
    'ate":{"__cause__":null,"__context__":null,"__suppress_context__":false},"fixture_must_no'
    't_seed_context":true},"PUBLIC_CLOSED":{"identity":"CURSOR_ERROR|public|PUBLIC_CLOSED","e'
    'xact_class":"builtins.ValueError","args":["Unsupported component shape"],"str":"Unsuppor'
    'ted component shape","repr":"ValueError(\'Unsupported component shape\')","__cause__":null'
    ',"__context__":"CURSOR_ERROR|public|E","__suppress_context__":true,"role":"captured_prod'
    'uct_created_error","context_fields_are_post_call_oracle_not_fixture_assignment":true,"fi'
    'xture_must_not_precreate":true}},"outcome":{"final_component_wire_return":0,"component_w'
    'ire_return_not_applicable":false,"kind":"exception","error":{"identity":"CURSOR_ERROR|pu'
    'blic|PUBLIC_CLOSED","exact_class":"builtins.ValueError","args":["Unsupported component s'
    'hape"],"str":"Unsupported component shape","repr":"ValueError(\'Unsupported component sha'
    'pe\')","__cause__":null,"__context__":"CURSOR_ERROR|public|E","__suppress_context__":true'
    '},"identity_assertion_required":false,"capture_product_created_error_only":true},"trace_'
    'oracle":[{"op":"route.call.enter","api":"recoryn.schema.component_shape_wire"},{"op":"cu'
    'rsor.create.enter","read":1,"cursor":"CURSOR_ERROR|public|r1"},{"op":"cursor.create.rais'
    'e","read":1,"cursor":"CURSOR_ERROR|public|r1","identity":"CURSOR_ERROR|public|E"},{"op":'
    '"route.raise","identity":"CURSOR_ERROR|public|PUBLIC_CLOSED","exact_class":"builtins.Val'
    'ueError"}],"trace_counts":{"cursor.create.enter":1,"cursor.create.return":0,"row_factory'
    '.enter":0,"row_factory.return":0,"execute.enter":0,"execute.return":0,"fetchall.enter":0'
    ',"fetchall.return":0,"close.enter":0,"close.return":0,"close.raise":0},"internal_canonic'
    'al_wire_call_count_not_constrained":true,"native_cleanup_proved":false},{"route_id":"ROW'
    '_FACTORY_ERROR|private","route":"private","api_name_future_private_unimplemented":"recor'
    'yn.schema._component_shape_wire_read","fake_identity":"ROW_FACTORY_ERROR|private|connect'
    'ion","fresh_all_objects":true,"prepare_hash_or_raise":false,"expected_model":"fresh_deep'
    '_copy_of_hand_anchor.model","component_input":"jobs.checkpoints","program":[{"read":1,"c'
    'ursor":"r1","sql":"PRAGMA main.schema_version","rows":[[7]]}],"fault":{"read":1,"stage":'
    '"row_factory","raise":"E"},"close_fault":null,"exception_objects_spec_only":{"E":{"ident'
    'ity":"ROW_FACTORY_ERROR|private|E","exact_class":"sqlite3.OperationalError","args":["ROW'
    '_FACTORY_ERROR_MARKER"],"str":"ROW_FACTORY_ERROR_MARKER","repr":"OperationalError(\'ROW_F'
    'ACTORY_ERROR_MARKER\')","__cause__":null,"__context__":null,"__suppress_context__":false,'
    '"role":"fresh_injected_error","context_fields_are_post_call_oracle_not_fixture_assignmen'
    't":true,"construction_initial_state":{"__cause__":null,"__context__":null,"__suppress_co'
    'ntext__":false},"fixture_must_not_seed_context":true}},"outcome":{"final_component_wire_'
    'return":0,"component_wire_return_not_applicable":false,"kind":"exception","error":{"iden'
    'tity":"ROW_FACTORY_ERROR|private|E","exact_class":"sqlite3.OperationalError","args":["RO'
    'W_FACTORY_ERROR_MARKER"],"str":"ROW_FACTORY_ERROR_MARKER","repr":"OperationalError(\'ROW_'
    'FACTORY_ERROR_MARKER\')","__cause__":null,"__context__":null,"__suppress_context__":false'
    '},"identity_assertion_required":true,"capture_product_created_error_only":false},"trace_'
    'oracle":[{"op":"route.call.enter","api":"recoryn.schema._component_shape_wire_read"},{"o'
    'p":"cursor.create.enter","read":1,"cursor":"ROW_FACTORY_ERROR|private|r1"},{"op":"cursor'
    '.create.return","read":1,"cursor":"ROW_FACTORY_ERROR|private|r1","fresh_cursor":true},{"'
    'op":"row_factory.enter","read":1,"cursor":"ROW_FACTORY_ERROR|private|r1","value":null},{'
    '"op":"row_factory.raise","read":1,"cursor":"ROW_FACTORY_ERROR|private|r1","identity":"RO'
    'W_FACTORY_ERROR|private|E"},{"op":"close.enter","read":1,"cursor":"ROW_FACTORY_ERROR|pri'
    'vate|r1"},{"op":"close.return","read":1,"cursor":"ROW_FACTORY_ERROR|private|r1","value":'
    'null},{"op":"route.raise","identity":"ROW_FACTORY_ERROR|private|E","exact_class":"sqlite'
    '3.OperationalError"}],"trace_counts":{"cursor.create.enter":1,"cursor.create.return":1,"'
    'row_factory.enter":1,"row_factory.return":0,"execute.enter":0,"execute.return":0,"fetcha'
    'll.enter":0,"fetchall.return":0,"close.enter":1,"close.return":1,"close.raise":0},"inter'
    'nal_canonical_wire_call_count_not_constrained":true,"native_cleanup_proved":false},{"rou'
    'te_id":"ROW_FACTORY_ERROR|public","route":"public","api_name_future_private_unimplemente'
    'd":"recoryn.schema.component_shape_wire","fake_identity":"ROW_FACTORY_ERROR|public|conne'
    'ction","fresh_all_objects":true,"prepare_hash_or_raise":false,"expected_model":"actual_p'
    'ublic_expected_lookup_not_stubbed","component_input":"jobs.checkpoints","program":[{"rea'
    'd":1,"cursor":"r1","sql":"PRAGMA main.schema_version","rows":[[7]]}],"fault":{"read":1,"'
    'stage":"row_factory","raise":"E"},"close_fault":null,"exception_objects_spec_only":{"E":'
    '{"identity":"ROW_FACTORY_ERROR|public|E","exact_class":"sqlite3.OperationalError","args"'
    ':["ROW_FACTORY_ERROR_MARKER"],"str":"ROW_FACTORY_ERROR_MARKER","repr":"OperationalError('
    '\'ROW_FACTORY_ERROR_MARKER\')","__cause__":null,"__context__":null,"__suppress_context__":'
    'false,"role":"fresh_injected_error","context_fields_are_post_call_oracle_not_fixture_ass'
    'ignment":true,"construction_initial_state":{"__cause__":null,"__context__":null,"__suppr'
    'ess_context__":false},"fixture_must_not_seed_context":true},"PUBLIC_CLOSED":{"identity":'
    '"ROW_FACTORY_ERROR|public|PUBLIC_CLOSED","exact_class":"builtins.ValueError","args":["Un'
    'supported component shape"],"str":"Unsupported component shape","repr":"ValueError(\'Unsu'
    'pported component shape\')","__cause__":null,"__context__":"ROW_FACTORY_ERROR|public|E","'
    '__suppress_context__":true,"role":"captured_product_created_error","context_fields_are_p'
    'ost_call_oracle_not_fixture_assignment":true,"fixture_must_not_precreate":true}},"outcom'
    'e":{"final_component_wire_return":0,"component_wire_return_not_applicable":false,"kind":'
    '"exception","error":{"identity":"ROW_FACTORY_ERROR|public|PUBLIC_CLOSED","exact_class":"'
    'builtins.ValueError","args":["Unsupported component shape"],"str":"Unsupported component'
    ' shape","repr":"ValueError(\'Unsupported component shape\')","__cause__":null,"__context__'
    '":"ROW_FACTORY_ERROR|public|E","__suppress_context__":true},"identity_assertion_required'
    '":false,"capture_product_created_error_only":true},"trace_oracle":[{"op":"route.call.ent'
    'er","api":"recoryn.schema.component_shape_wire"},{"op":"cursor.create.enter","read":1,"c'
    'ursor":"ROW_FACTORY_ERROR|public|r1"},{"op":"cursor.create.return","read":1,"cursor":"RO'
    'W_FACTORY_ERROR|public|r1","fresh_cursor":true},{"op":"row_factory.enter","read":1,"curs'
    'or":"ROW_FACTORY_ERROR|public|r1","value":null},{"op":"row_factory.raise","read":1,"curs'
    'or":"ROW_FACTORY_ERROR|public|r1","identity":"ROW_FACTORY_ERROR|public|E"},{"op":"close.'
    'enter","read":1,"cursor":"ROW_FACTORY_ERROR|public|r1"},{"op":"close.return","read":1,"c'
    'ursor":"ROW_FACTORY_ERROR|public|r1","value":null},{"op":"route.raise","identity":"ROW_F'
    'ACTORY_ERROR|public|PUBLIC_CLOSED","exact_class":"builtins.ValueError"}],"trace_counts":'
    '{"cursor.create.enter":1,"cursor.create.return":1,"row_factory.enter":1,"row_factory.ret'
    'urn":0,"execute.enter":0,"execute.return":0,"fetchall.enter":0,"fetchall.return":0,"clos'
    'e.enter":1,"close.return":1,"close.raise":0},"internal_canonical_wire_call_count_not_con'
    'strained":true,"native_cleanup_proved":false},{"route_id":"EXECUTE_ERROR|private","route'
    '":"private","api_name_future_private_unimplemented":"recoryn.schema._component_shape_wir'
    'e_read","fake_identity":"EXECUTE_ERROR|private|connection","fresh_all_objects":true,"pre'
    'pare_hash_or_raise":false,"expected_model":"fresh_deep_copy_of_hand_anchor.model","compo'
    'nent_input":"jobs.checkpoints","program":[{"read":1,"cursor":"r1","sql":"PRAGMA main.sch'
    'ema_version","rows":[[7]]}],"fault":{"read":1,"stage":"execute","raise":"E"},"close_faul'
    't":null,"exception_objects_spec_only":{"E":{"identity":"EXECUTE_ERROR|private|E","exact_'
    'class":"sqlite3.OperationalError","args":["EXECUTE_ERROR_MARKER"],"str":"EXECUTE_ERROR_M'
    'ARKER","repr":"OperationalError(\'EXECUTE_ERROR_MARKER\')","__cause__":null,"__context__":'
    'null,"__suppress_context__":false,"role":"fresh_injected_error","context_fields_are_post'
    '_call_oracle_not_fixture_assignment":true,"construction_initial_state":{"__cause__":null'
    ',"__context__":null,"__suppress_context__":false},"fixture_must_not_seed_context":true}}'
    ',"outcome":{"final_component_wire_return":0,"component_wire_return_not_applicable":false'
    ',"kind":"exception","error":{"identity":"EXECUTE_ERROR|private|E","exact_class":"sqlite3'
    '.OperationalError","args":["EXECUTE_ERROR_MARKER"],"str":"EXECUTE_ERROR_MARKER","repr":"'
    'OperationalError(\'EXECUTE_ERROR_MARKER\')","__cause__":null,"__context__":null,"__suppres'
    's_context__":false},"identity_assertion_required":true,"capture_product_created_error_on'
    'ly":false},"trace_oracle":[{"op":"route.call.enter","api":"recoryn.schema._component_sha'
    'pe_wire_read"},{"op":"cursor.create.enter","read":1,"cursor":"EXECUTE_ERROR|private|r1"}'
    ',{"op":"cursor.create.return","read":1,"cursor":"EXECUTE_ERROR|private|r1","fresh_cursor'
    '":true},{"op":"row_factory.enter","read":1,"cursor":"EXECUTE_ERROR|private|r1","value":n'
    'ull},{"op":"row_factory.return","read":1,"cursor":"EXECUTE_ERROR|private|r1","value":nul'
    'l},{"op":"execute.enter","read":1,"cursor":"EXECUTE_ERROR|private|r1","sql":"PRAGMA main'
    '.schema_version"},{"op":"execute.raise","read":1,"cursor":"EXECUTE_ERROR|private|r1","id'
    'entity":"EXECUTE_ERROR|private|E"},{"op":"close.enter","read":1,"cursor":"EXECUTE_ERROR|'
    'private|r1"},{"op":"close.return","read":1,"cursor":"EXECUTE_ERROR|private|r1","value":n'
    'ull},{"op":"route.raise","identity":"EXECUTE_ERROR|private|E","exact_class":"sqlite3.Ope'
    'rationalError"}],"trace_counts":{"cursor.create.enter":1,"cursor.create.return":1,"row_f'
    'actory.enter":1,"row_factory.return":1,"execute.enter":1,"execute.return":0,"fetchall.en'
    'ter":0,"fetchall.return":0,"close.enter":1,"close.return":1,"close.raise":0},"internal_c'
    'anonical_wire_call_count_not_constrained":true,"native_cleanup_proved":false},{"route_id'
    '":"EXECUTE_ERROR|public","route":"public","api_name_future_private_unimplemented":"recor'
    'yn.schema.component_shape_wire","fake_identity":"EXECUTE_ERROR|public|connection","fresh'
    '_all_objects":true,"prepare_hash_or_raise":false,"expected_model":"actual_public_expecte'
    'd_lookup_not_stubbed","component_input":"jobs.checkpoints","program":[{"read":1,"cursor"'
    ':"r1","sql":"PRAGMA main.schema_version","rows":[[7]]}],"fault":{"read":1,"stage":"execu'
    'te","raise":"E"},"close_fault":null,"exception_objects_spec_only":{"E":{"identity":"EXEC'
    'UTE_ERROR|public|E","exact_class":"sqlite3.OperationalError","args":["EXECUTE_ERROR_MARK'
    'ER"],"str":"EXECUTE_ERROR_MARKER","repr":"OperationalError(\'EXECUTE_ERROR_MARKER\')","__c'
    'ause__":null,"__context__":null,"__suppress_context__":false,"role":"fresh_injected_erro'
    'r","context_fields_are_post_call_oracle_not_fixture_assignment":true,"construction_initi'
    'al_state":{"__cause__":null,"__context__":null,"__suppress_context__":false},"fixture_mu'
    'st_not_seed_context":true},"PUBLIC_CLOSED":{"identity":"EXECUTE_ERROR|public|PUBLIC_CLOS'
    'ED","exact_class":"builtins.ValueError","args":["Unsupported component shape"],"str":"Un'
    'supported component shape","repr":"ValueError(\'Unsupported component shape\')","__cause__'
    '":null,"__context__":"EXECUTE_ERROR|public|E","__suppress_context__":true,"role":"captur'
    'ed_product_created_error","context_fields_are_post_call_oracle_not_fixture_assignment":t'
    'rue,"fixture_must_not_precreate":true}},"outcome":{"final_component_wire_return":0,"comp'
    'onent_wire_return_not_applicable":false,"kind":"exception","error":{"identity":"EXECUTE_'
    'ERROR|public|PUBLIC_CLOSED","exact_class":"builtins.ValueError","args":["Unsupported com'
    'ponent shape"],"str":"Unsupported component shape","repr":"ValueError(\'Unsupported compo'
    'nent shape\')","__cause__":null,"__context__":"EXECUTE_ERROR|public|E","__suppress_contex'
    't__":true},"identity_assertion_required":false,"capture_product_created_error_only":true'
    '},"trace_oracle":[{"op":"route.call.enter","api":"recoryn.schema.component_shape_wire"},'
    '{"op":"cursor.create.enter","read":1,"cursor":"EXECUTE_ERROR|public|r1"},{"op":"cursor.c'
    'reate.return","read":1,"cursor":"EXECUTE_ERROR|public|r1","fresh_cursor":true},{"op":"ro'
    'w_factory.enter","read":1,"cursor":"EXECUTE_ERROR|public|r1","value":null},{"op":"row_fa'
    'ctory.return","read":1,"cursor":"EXECUTE_ERROR|public|r1","value":null},{"op":"execute.e'
    'nter","read":1,"cursor":"EXECUTE_ERROR|public|r1","sql":"PRAGMA main.schema_version"},{"'
    'op":"execute.raise","read":1,"cursor":"EXECUTE_ERROR|public|r1","identity":"EXECUTE_ERRO'
    'R|public|E"},{"op":"close.enter","read":1,"cursor":"EXECUTE_ERROR|public|r1"},{"op":"clo'
    'se.return","read":1,"cursor":"EXECUTE_ERROR|public|r1","value":null},{"op":"route.raise"'
    ',"identity":"EXECUTE_ERROR|public|PUBLIC_CLOSED","exact_class":"builtins.ValueError"}],"'
    'trace_counts":{"cursor.create.enter":1,"cursor.create.return":1,"row_factory.enter":1,"r'
    'ow_factory.return":1,"execute.enter":1,"execute.return":0,"fetchall.enter":0,"fetchall.r'
    'eturn":0,"close.enter":1,"close.return":1,"close.raise":0},"internal_canonical_wire_call'
    '_count_not_constrained":true,"native_cleanup_proved":false},{"route_id":"FETCH_ERROR|pri'
    'vate","route":"private","api_name_future_private_unimplemented":"recoryn.schema._compone'
    'nt_shape_wire_read","fake_identity":"FETCH_ERROR|private|connection","fresh_all_objects"'
    ':true,"prepare_hash_or_raise":false,"expected_model":"fresh_deep_copy_of_hand_anchor.mod'
    'el","component_input":"jobs.checkpoints","program":[{"read":1,"cursor":"r1","sql":"PRAGM'
    'A main.schema_version","rows":[[7]]}],"fault":{"read":1,"stage":"fetchall","raise":"E"},'
    '"close_fault":null,"exception_objects_spec_only":{"E":{"identity":"FETCH_ERROR|private|E'
    '","exact_class":"sqlite3.OperationalError","args":["FETCH_ERROR_MARKER"],"str":"FETCH_ER'
    'ROR_MARKER","repr":"OperationalError(\'FETCH_ERROR_MARKER\')","__cause__":null,"__context_'
    '_":null,"__suppress_context__":false,"role":"fresh_injected_error","context_fields_are_p'
    'ost_call_oracle_not_fixture_assignment":true,"construction_initial_state":{"__cause__":n'
    'ull,"__context__":null,"__suppress_context__":false},"fixture_must_not_seed_context":tru'
    'e}},"outcome":{"final_component_wire_return":0,"component_wire_return_not_applicable":fa'
    'lse,"kind":"exception","error":{"identity":"FETCH_ERROR|private|E","exact_class":"sqlite'
    '3.OperationalError","args":["FETCH_ERROR_MARKER"],"str":"FETCH_ERROR_MARKER","repr":"Ope'
    'rationalError(\'FETCH_ERROR_MARKER\')","__cause__":null,"__context__":null,"__suppress_con'
    'text__":false},"identity_assertion_required":true,"capture_product_created_error_only":f'
    'alse},"trace_oracle":[{"op":"route.call.enter","api":"recoryn.schema._component_shape_wi'
    're_read"},{"op":"cursor.create.enter","read":1,"cursor":"FETCH_ERROR|private|r1"},{"op":'
    '"cursor.create.return","read":1,"cursor":"FETCH_ERROR|private|r1","fresh_cursor":true},{'
    '"op":"row_factory.enter","read":1,"cursor":"FETCH_ERROR|private|r1","value":null},{"op":'
    '"row_factory.return","read":1,"cursor":"FETCH_ERROR|private|r1","value":null},{"op":"exe'
    'cute.enter","read":1,"cursor":"FETCH_ERROR|private|r1","sql":"PRAGMA main.schema_version'
    '"},{"op":"execute.return","read":1,"cursor":"FETCH_ERROR|private|r1","value":"same_curso'
    'r"},{"op":"fetchall.enter","read":1,"cursor":"FETCH_ERROR|private|r1"},{"op":"fetchall.r'
    'aise","read":1,"cursor":"FETCH_ERROR|private|r1","identity":"FETCH_ERROR|private|E"},{"o'
    'p":"close.enter","read":1,"cursor":"FETCH_ERROR|private|r1"},{"op":"close.return","read"'
    ':1,"cursor":"FETCH_ERROR|private|r1","value":null},{"op":"route.raise","identity":"FETCH'
    '_ERROR|private|E","exact_class":"sqlite3.OperationalError"}],"trace_counts":{"cursor.cre'
    'ate.enter":1,"cursor.create.return":1,"row_factory.enter":1,"row_factory.return":1,"exec'
    'ute.enter":1,"execute.return":1,"fetchall.enter":1,"fetchall.return":0,"close.enter":1,"'
    'close.return":1,"close.raise":0},"internal_canonical_wire_call_count_not_constrained":tr'
    'ue,"native_cleanup_proved":false},{"route_id":"FETCH_ERROR|public","route":"public","api'
    '_name_future_private_unimplemented":"recoryn.schema.component_shape_wire","fake_identity'
    '":"FETCH_ERROR|public|connection","fresh_all_objects":true,"prepare_hash_or_raise":false'
    ',"expected_model":"actual_public_expected_lookup_not_stubbed","component_input":"jobs.ch'
    'eckpoints","program":[{"read":1,"cursor":"r1","sql":"PRAGMA main.schema_version","rows":'
    '[[7]]}],"fault":{"read":1,"stage":"fetchall","raise":"E"},"close_fault":null,"exception_'
    'objects_spec_only":{"E":{"identity":"FETCH_ERROR|public|E","exact_class":"sqlite3.Operat'
    'ionalError","args":["FETCH_ERROR_MARKER"],"str":"FETCH_ERROR_MARKER","repr":"Operational'
    'Error(\'FETCH_ERROR_MARKER\')","__cause__":null,"__context__":null,"__suppress_context__":'
    'false,"role":"fresh_injected_error","context_fields_are_post_call_oracle_not_fixture_ass'
    'ignment":true,"construction_initial_state":{"__cause__":null,"__context__":null,"__suppr'
    'ess_context__":false},"fixture_must_not_seed_context":true},"PUBLIC_CLOSED":{"identity":'
    '"FETCH_ERROR|public|PUBLIC_CLOSED","exact_class":"builtins.ValueError","args":["Unsuppor'
    'ted component shape"],"str":"Unsupported component shape","repr":"ValueError(\'Unsupporte'
    'd component shape\')","__cause__":null,"__context__":"FETCH_ERROR|public|E","__suppress_c'
    'ontext__":true,"role":"captured_product_created_error","context_fields_are_post_call_ora'
    'cle_not_fixture_assignment":true,"fixture_must_not_precreate":true}},"outcome":{"final_c'
    'omponent_wire_return":0,"component_wire_return_not_applicable":false,"kind":"exception",'
    '"error":{"identity":"FETCH_ERROR|public|PUBLIC_CLOSED","exact_class":"builtins.ValueErro'
    'r","args":["Unsupported component shape"],"str":"Unsupported component shape","repr":"Va'
    'lueError(\'Unsupported component shape\')","__cause__":null,"__context__":"FETCH_ERROR|pub'
    'lic|E","__suppress_context__":true},"identity_assertion_required":false,"capture_product'
    '_created_error_only":true},"trace_oracle":[{"op":"route.call.enter","api":"recoryn.schem'
    'a.component_shape_wire"},{"op":"cursor.create.enter","read":1,"cursor":"FETCH_ERROR|publ'
    'ic|r1"},{"op":"cursor.create.return","read":1,"cursor":"FETCH_ERROR|public|r1","fresh_cu'
    'rsor":true},{"op":"row_factory.enter","read":1,"cursor":"FETCH_ERROR|public|r1","value":'
    'null},{"op":"row_factory.return","read":1,"cursor":"FETCH_ERROR|public|r1","value":null}'
    ',{"op":"execute.enter","read":1,"cursor":"FETCH_ERROR|public|r1","sql":"PRAGMA main.sche'
    'ma_version"},{"op":"execute.return","read":1,"cursor":"FETCH_ERROR|public|r1","value":"s'
    'ame_cursor"},{"op":"fetchall.enter","read":1,"cursor":"FETCH_ERROR|public|r1"},{"op":"fe'
    'tchall.raise","read":1,"cursor":"FETCH_ERROR|public|r1","identity":"FETCH_ERROR|public|E'
    '"},{"op":"close.enter","read":1,"cursor":"FETCH_ERROR|public|r1"},{"op":"close.return","'
    'read":1,"cursor":"FETCH_ERROR|public|r1","value":null},{"op":"route.raise","identity":"F'
    'ETCH_ERROR|public|PUBLIC_CLOSED","exact_class":"builtins.ValueError"}],"trace_counts":{"'
    'cursor.create.enter":1,"cursor.create.return":1,"row_factory.enter":1,"row_factory.retur'
    'n":1,"execute.enter":1,"execute.return":1,"fetchall.enter":1,"fetchall.return":0,"close.'
    'enter":1,"close.return":1,"close.raise":0},"internal_canonical_wire_call_count_not_const'
    'rained":true,"native_cleanup_proved":false},{"route_id":"CLOSE_ONLY|private","route":"pr'
    'ivate","api_name_future_private_unimplemented":"recoryn.schema._component_shape_wire_rea'
    'd","fake_identity":"CLOSE_ONLY|private|connection","fresh_all_objects":true,"prepare_has'
    'h_or_raise":false,"expected_model":"fresh_deep_copy_of_hand_anchor.model","component_inp'
    'ut":"jobs.checkpoints","program":[{"read":1,"cursor":"r1","sql":"PRAGMA main.schema_vers'
    'ion","rows":[[7]]}],"fault":null,"close_fault":"C","exception_objects_spec_only":{"C":{"'
    'identity":"CLOSE_ONLY|private|C","exact_class":"sqlite3.OperationalError","args":["CLOSE'
    '_ONLY_MARKER"],"str":"CLOSE_ONLY_MARKER","repr":"OperationalError(\'CLOSE_ONLY_MARKER\')",'
    '"__cause__":null,"__context__":null,"__suppress_context__":false,"role":"fresh_injected_'
    'error","context_fields_are_post_call_oracle_not_fixture_assignment":true,"construction_i'
    'nitial_state":{"__cause__":null,"__context__":null,"__suppress_context__":false},"fixtur'
    'e_must_not_seed_context":true}},"outcome":{"final_component_wire_return":0,"component_wi'
    're_return_not_applicable":false,"kind":"exception","error":{"identity":"CLOSE_ONLY|priva'
    'te|C","exact_class":"sqlite3.OperationalError","args":["CLOSE_ONLY_MARKER"],"str":"CLOSE'
    '_ONLY_MARKER","repr":"OperationalError(\'CLOSE_ONLY_MARKER\')","__cause__":null,"__context'
    '__":null,"__suppress_context__":false},"identity_assertion_required":true,"capture_produ'
    'ct_created_error_only":false},"trace_oracle":[{"op":"route.call.enter","api":"recoryn.sc'
    'hema._component_shape_wire_read"},{"op":"cursor.create.enter","read":1,"cursor":"CLOSE_O'
    'NLY|private|r1"},{"op":"cursor.create.return","read":1,"cursor":"CLOSE_ONLY|private|r1",'
    '"fresh_cursor":true},{"op":"row_factory.enter","read":1,"cursor":"CLOSE_ONLY|private|r1"'
    ',"value":null},{"op":"row_factory.return","read":1,"cursor":"CLOSE_ONLY|private|r1","val'
    'ue":null},{"op":"execute.enter","read":1,"cursor":"CLOSE_ONLY|private|r1","sql":"PRAGMA '
    'main.schema_version"},{"op":"execute.return","read":1,"cursor":"CLOSE_ONLY|private|r1","'
    'value":"same_cursor"},{"op":"fetchall.enter","read":1,"cursor":"CLOSE_ONLY|private|r1"},'
    '{"op":"fetchall.return","read":1,"cursor":"CLOSE_ONLY|private|r1","rows":[[7]],"runtime_'
    'container":"list[tuple]"},{"op":"close.enter","read":1,"cursor":"CLOSE_ONLY|private|r1"}'
    ',{"op":"close.raise","read":1,"cursor":"CLOSE_ONLY|private|r1","identity":"CLOSE_ONLY|pr'
    'ivate|C"},{"op":"route.raise","identity":"CLOSE_ONLY|private|C","exact_class":"sqlite3.O'
    'perationalError"}],"trace_counts":{"cursor.create.enter":1,"cursor.create.return":1,"row'
    '_factory.enter":1,"row_factory.return":1,"execute.enter":1,"execute.return":1,"fetchall.'
    'enter":1,"fetchall.return":1,"close.enter":1,"close.return":0,"close.raise":1},"internal'
    '_canonical_wire_call_count_not_constrained":true,"native_cleanup_proved":false},{"route_'
    'id":"CLOSE_ONLY|public","route":"public","api_name_future_private_unimplemented":"recory'
    'n.schema.component_shape_wire","fake_identity":"CLOSE_ONLY|public|connection","fresh_all'
    '_objects":true,"prepare_hash_or_raise":false,"expected_model":"actual_public_expected_lo'
    'okup_not_stubbed","component_input":"jobs.checkpoints","program":[{"read":1,"cursor":"r1'
    '","sql":"PRAGMA main.schema_version","rows":[[7]]}],"fault":null,"close_fault":"C","exce'
    'ption_objects_spec_only":{"C":{"identity":"CLOSE_ONLY|public|C","exact_class":"sqlite3.O'
    'perationalError","args":["CLOSE_ONLY_MARKER"],"str":"CLOSE_ONLY_MARKER","repr":"Operatio'
    'nalError(\'CLOSE_ONLY_MARKER\')","__cause__":null,"__context__":null,"__suppress_context__'
    '":false,"role":"fresh_injected_error","context_fields_are_post_call_oracle_not_fixture_a'
    'ssignment":true,"construction_initial_state":{"__cause__":null,"__context__":null,"__sup'
    'press_context__":false},"fixture_must_not_seed_context":true},"PUBLIC_CLOSED":{"identity'
    '":"CLOSE_ONLY|public|PUBLIC_CLOSED","exact_class":"builtins.ValueError","args":["Unsuppo'
    'rted component shape"],"str":"Unsupported component shape","repr":"ValueError(\'Unsupport'
    'ed component shape\')","__cause__":null,"__context__":"CLOSE_ONLY|public|C","__suppress_c'
    'ontext__":true,"role":"captured_product_created_error","context_fields_are_post_call_ora'
    'cle_not_fixture_assignment":true,"fixture_must_not_precreate":true}},"outcome":{"final_c'
    'omponent_wire_return":0,"component_wire_return_not_applicable":false,"kind":"exception",'
    '"error":{"identity":"CLOSE_ONLY|public|PUBLIC_CLOSED","exact_class":"builtins.ValueError'
    '","args":["Unsupported component shape"],"str":"Unsupported component shape","repr":"Val'
    'ueError(\'Unsupported component shape\')","__cause__":null,"__context__":"CLOSE_ONLY|publi'
    'c|C","__suppress_context__":true},"identity_assertion_required":false,"capture_product_c'
    'reated_error_only":true},"trace_oracle":[{"op":"route.call.enter","api":"recoryn.schema.'
    'component_shape_wire"},{"op":"cursor.create.enter","read":1,"cursor":"CLOSE_ONLY|public|'
    'r1"},{"op":"cursor.create.return","read":1,"cursor":"CLOSE_ONLY|public|r1","fresh_cursor'
    '":true},{"op":"row_factory.enter","read":1,"cursor":"CLOSE_ONLY|public|r1","value":null}'
    ',{"op":"row_factory.return","read":1,"cursor":"CLOSE_ONLY|public|r1","value":null},{"op"'
    ':"execute.enter","read":1,"cursor":"CLOSE_ONLY|public|r1","sql":"PRAGMA main.schema_vers'
    'ion"},{"op":"execute.return","read":1,"cursor":"CLOSE_ONLY|public|r1","value":"same_curs'
    'or"},{"op":"fetchall.enter","read":1,"cursor":"CLOSE_ONLY|public|r1"},{"op":"fetchall.re'
    'turn","read":1,"cursor":"CLOSE_ONLY|public|r1","rows":[[7]],"runtime_container":"list[tu'
    'ple]"},{"op":"close.enter","read":1,"cursor":"CLOSE_ONLY|public|r1"},{"op":"close.raise"'
    ',"read":1,"cursor":"CLOSE_ONLY|public|r1","identity":"CLOSE_ONLY|public|C"},{"op":"route'
    '.raise","identity":"CLOSE_ONLY|public|PUBLIC_CLOSED","exact_class":"builtins.ValueError"'
    '}],"trace_counts":{"cursor.create.enter":1,"cursor.create.return":1,"row_factory.enter":'
    '1,"row_factory.return":1,"execute.enter":1,"execute.return":1,"fetchall.enter":1,"fetcha'
    'll.return":1,"close.enter":1,"close.return":0,"close.raise":1},"internal_canonical_wire_'
    'call_count_not_constrained":true,"native_cleanup_proved":false},{"route_id":"OTHER_SQLIT'
    'E_ERROR|private","route":"private","api_name_future_private_unimplemented":"recoryn.sche'
    'ma._component_shape_wire_read","fake_identity":"OTHER_SQLITE_ERROR|private|connection","'
    'fresh_all_objects":true,"prepare_hash_or_raise":false,"expected_model":"fresh_deep_copy_'
    'of_hand_anchor.model","component_input":"jobs.checkpoints","program":[{"read":1,"cursor"'
    ':"r1","sql":"PRAGMA main.schema_version","rows":[[7]]}],"fault":{"read":1,"stage":"execu'
    'te","raise":"E"},"close_fault":null,"exception_objects_spec_only":{"E":{"identity":"OTHE'
    'R_SQLITE_ERROR|private|E","exact_class":"sqlite3.DatabaseError","args":["OTHER_SQLITE_ER'
    'ROR_MARKER"],"str":"OTHER_SQLITE_ERROR_MARKER","repr":"DatabaseError(\'OTHER_SQLITE_ERROR'
    '_MARKER\')","__cause__":null,"__context__":null,"__suppress_context__":false,"role":"fres'
    'h_injected_error","context_fields_are_post_call_oracle_not_fixture_assignment":true,"con'
    'struction_initial_state":{"__cause__":null,"__context__":null,"__suppress_context__":fal'
    'se},"fixture_must_not_seed_context":true}},"outcome":{"final_component_wire_return":0,"c'
    'omponent_wire_return_not_applicable":false,"kind":"exception","error":{"identity":"OTHER'
    '_SQLITE_ERROR|private|E","exact_class":"sqlite3.DatabaseError","args":["OTHER_SQLITE_ERR'
    'OR_MARKER"],"str":"OTHER_SQLITE_ERROR_MARKER","repr":"DatabaseError(\'OTHER_SQLITE_ERROR_'
    'MARKER\')","__cause__":null,"__context__":null,"__suppress_context__":false},"identity_as'
    'sertion_required":true,"capture_product_created_error_only":false},"trace_oracle":[{"op"'
    ':"route.call.enter","api":"recoryn.schema._component_shape_wire_read"},{"op":"cursor.cre'
    'ate.enter","read":1,"cursor":"OTHER_SQLITE_ERROR|private|r1"},{"op":"cursor.create.retur'
    'n","read":1,"cursor":"OTHER_SQLITE_ERROR|private|r1","fresh_cursor":true},{"op":"row_fac'
    'tory.enter","read":1,"cursor":"OTHER_SQLITE_ERROR|private|r1","value":null},{"op":"row_f'
    'actory.return","read":1,"cursor":"OTHER_SQLITE_ERROR|private|r1","value":null},{"op":"ex'
    'ecute.enter","read":1,"cursor":"OTHER_SQLITE_ERROR|private|r1","sql":"PRAGMA main.schema'
    '_version"},{"op":"execute.raise","read":1,"cursor":"OTHER_SQLITE_ERROR|private|r1","iden'
    'tity":"OTHER_SQLITE_ERROR|private|E"},{"op":"close.enter","read":1,"cursor":"OTHER_SQLIT'
    'E_ERROR|private|r1"},{"op":"close.return","read":1,"cursor":"OTHER_SQLITE_ERROR|private|'
    'r1","value":null},{"op":"route.raise","identity":"OTHER_SQLITE_ERROR|private|E","exact_c'
    'lass":"sqlite3.DatabaseError"}],"trace_counts":{"cursor.create.enter":1,"cursor.create.r'
    'eturn":1,"row_factory.enter":1,"row_factory.return":1,"execute.enter":1,"execute.return"'
    ':0,"fetchall.enter":0,"fetchall.return":0,"close.enter":1,"close.return":1,"close.raise"'
    ':0},"internal_canonical_wire_call_count_not_constrained":true,"native_cleanup_proved":fa'
    'lse},{"route_id":"OTHER_SQLITE_ERROR|public","route":"public","api_name_future_private_u'
    'nimplemented":"recoryn.schema.component_shape_wire","fake_identity":"OTHER_SQLITE_ERROR|'
    'public|connection","fresh_all_objects":true,"prepare_hash_or_raise":false,"expected_mode'
    'l":"actual_public_expected_lookup_not_stubbed","component_input":"jobs.checkpoints","pro'
    'gram":[{"read":1,"cursor":"r1","sql":"PRAGMA main.schema_version","rows":[[7]]}],"fault"'
    ':{"read":1,"stage":"execute","raise":"E"},"close_fault":null,"exception_objects_spec_onl'
    'y":{"E":{"identity":"OTHER_SQLITE_ERROR|public|E","exact_class":"sqlite3.DatabaseError",'
    '"args":["OTHER_SQLITE_ERROR_MARKER"],"str":"OTHER_SQLITE_ERROR_MARKER","repr":"DatabaseE'
    'rror(\'OTHER_SQLITE_ERROR_MARKER\')","__cause__":null,"__context__":null,"__suppress_conte'
    'xt__":false,"role":"fresh_injected_error","context_fields_are_post_call_oracle_not_fixtu'
    're_assignment":true,"construction_initial_state":{"__cause__":null,"__context__":null,"_'
    '_suppress_context__":false},"fixture_must_not_seed_context":true},"PUBLIC_CLOSED":{"iden'
    'tity":"OTHER_SQLITE_ERROR|public|PUBLIC_CLOSED","exact_class":"builtins.ValueError","arg'
    's":["Unsupported component shape"],"str":"Unsupported component shape","repr":"ValueErro'
    'r(\'Unsupported component shape\')","__cause__":null,"__context__":"OTHER_SQLITE_ERROR|pub'
    'lic|E","__suppress_context__":true,"role":"captured_product_created_error","context_fiel'
    'ds_are_post_call_oracle_not_fixture_assignment":true,"fixture_must_not_precreate":true}}'
    ',"outcome":{"final_component_wire_return":0,"component_wire_return_not_applicable":false'
    ',"kind":"exception","error":{"identity":"OTHER_SQLITE_ERROR|public|PUBLIC_CLOSED","exact'
    '_class":"builtins.ValueError","args":["Unsupported component shape"],"str":"Unsupported '
    'component shape","repr":"ValueError(\'Unsupported component shape\')","__cause__":null,"__'
    'context__":"OTHER_SQLITE_ERROR|public|E","__suppress_context__":true},"identity_assertio'
    'n_required":false,"capture_product_created_error_only":true},"trace_oracle":[{"op":"rout'
    'e.call.enter","api":"recoryn.schema.component_shape_wire"},{"op":"cursor.create.enter","'
    'read":1,"cursor":"OTHER_SQLITE_ERROR|public|r1"},{"op":"cursor.create.return","read":1,"'
    'cursor":"OTHER_SQLITE_ERROR|public|r1","fresh_cursor":true},{"op":"row_factory.enter","r'
    'ead":1,"cursor":"OTHER_SQLITE_ERROR|public|r1","value":null},{"op":"row_factory.return",'
    '"read":1,"cursor":"OTHER_SQLITE_ERROR|public|r1","value":null},{"op":"execute.enter","re'
    'ad":1,"cursor":"OTHER_SQLITE_ERROR|public|r1","sql":"PRAGMA main.schema_version"},{"op":'
    '"execute.raise","read":1,"cursor":"OTHER_SQLITE_ERROR|public|r1","identity":"OTHER_SQLIT'
    'E_ERROR|public|E"},{"op":"close.enter","read":1,"cursor":"OTHER_SQLITE_ERROR|public|r1"}'
    ',{"op":"close.return","read":1,"cursor":"OTHER_SQLITE_ERROR|public|r1","value":null},{"o'
    'p":"route.raise","identity":"OTHER_SQLITE_ERROR|public|PUBLIC_CLOSED","exact_class":"bui'
    'ltins.ValueError"}],"trace_counts":{"cursor.create.enter":1,"cursor.create.return":1,"ro'
    'w_factory.enter":1,"row_factory.return":1,"execute.enter":1,"execute.return":0,"fetchall'
    '.enter":0,"fetchall.return":0,"close.enter":1,"close.return":1,"close.raise":0},"interna'
    'l_canonical_wire_call_count_not_constrained":true,"native_cleanup_proved":false},{"route'
    '_id":"DUAL_SQLITE|private","route":"private","api_name_future_private_unimplemented":"re'
    'coryn.schema._component_shape_wire_read","fake_identity":"DUAL_SQLITE|private|connection'
    '","fresh_all_objects":true,"prepare_hash_or_raise":false,"expected_model":"fresh_deep_co'
    'py_of_hand_anchor.model","component_input":"jobs.checkpoints","program":[{"read":1,"curs'
    'or":"r1","sql":"PRAGMA main.schema_version","rows":[[7]]}],"fault":{"read":1,"stage":"ex'
    'ecute","raise":"E"},"close_fault":"C","exception_objects_spec_only":{"E":{"identity":"DU'
    'AL_SQLITE|private|E","exact_class":"sqlite3.OperationalError","args":["DUAL_SQLITE_READ_'
    'MARKER"],"str":"DUAL_SQLITE_READ_MARKER","repr":"OperationalError(\'DUAL_SQLITE_READ_MARK'
    'ER\')","__cause__":null,"__context__":null,"__suppress_context__":false,"role":"fresh_inj'
    'ected_error","context_fields_are_post_call_oracle_not_fixture_assignment":true,"construc'
    'tion_initial_state":{"__cause__":null,"__context__":null,"__suppress_context__":false},"'
    'fixture_must_not_seed_context":true},"C":{"identity":"DUAL_SQLITE|private|C","exact_clas'
    's":"sqlite3.DatabaseError","args":["DUAL_SQLITE_CLOSE_MARKER"],"str":"DUAL_SQLITE_CLOSE_'
    'MARKER","repr":"DatabaseError(\'DUAL_SQLITE_CLOSE_MARKER\')","__cause__":null,"__context__'
    '":"DUAL_SQLITE|private|E","__suppress_context__":false,"role":"fresh_injected_error","co'
    'ntext_fields_are_post_call_oracle_not_fixture_assignment":true,"construction_initial_sta'
    'te":{"__cause__":null,"__context__":null,"__suppress_context__":false},"fixture_must_not'
    '_seed_context":true}},"outcome":{"final_component_wire_return":0,"component_wire_return_'
    'not_applicable":false,"kind":"exception","error":{"identity":"DUAL_SQLITE|private|C","ex'
    'act_class":"sqlite3.DatabaseError","args":["DUAL_SQLITE_CLOSE_MARKER"],"str":"DUAL_SQLIT'
    'E_CLOSE_MARKER","repr":"DatabaseError(\'DUAL_SQLITE_CLOSE_MARKER\')","__cause__":null,"__c'
    'ontext__":"DUAL_SQLITE|private|E","__suppress_context__":false},"identity_assertion_requ'
    'ired":true,"capture_product_created_error_only":false},"trace_oracle":[{"op":"route.call'
    '.enter","api":"recoryn.schema._component_shape_wire_read"},{"op":"cursor.create.enter","'
    'read":1,"cursor":"DUAL_SQLITE|private|r1"},{"op":"cursor.create.return","read":1,"cursor'
    '":"DUAL_SQLITE|private|r1","fresh_cursor":true},{"op":"row_factory.enter","read":1,"curs'
    'or":"DUAL_SQLITE|private|r1","value":null},{"op":"row_factory.return","read":1,"cursor":'
    '"DUAL_SQLITE|private|r1","value":null},{"op":"execute.enter","read":1,"cursor":"DUAL_SQL'
    'ITE|private|r1","sql":"PRAGMA main.schema_version"},{"op":"execute.raise","read":1,"curs'
    'or":"DUAL_SQLITE|private|r1","identity":"DUAL_SQLITE|private|E"},{"op":"close.enter","re'
    'ad":1,"cursor":"DUAL_SQLITE|private|r1"},{"op":"close.raise","read":1,"cursor":"DUAL_SQL'
    'ITE|private|r1","identity":"DUAL_SQLITE|private|C"},{"op":"route.raise","identity":"DUAL'
    '_SQLITE|private|C","exact_class":"sqlite3.DatabaseError"}],"trace_counts":{"cursor.creat'
    'e.enter":1,"cursor.create.return":1,"row_factory.enter":1,"row_factory.return":1,"execut'
    'e.enter":1,"execute.return":0,"fetchall.enter":0,"fetchall.return":0,"close.enter":1,"cl'
    'ose.return":0,"close.raise":1},"internal_canonical_wire_call_count_not_constrained":true'
    ',"native_cleanup_proved":false},{"route_id":"DUAL_SQLITE|public","route":"public","api_n'
    'ame_future_private_unimplemented":"recoryn.schema.component_shape_wire","fake_identity":'
    '"DUAL_SQLITE|public|connection","fresh_all_objects":true,"prepare_hash_or_raise":false,"'
    'expected_model":"actual_public_expected_lookup_not_stubbed","component_input":"jobs.chec'
    'kpoints","program":[{"read":1,"cursor":"r1","sql":"PRAGMA main.schema_version","rows":[['
    '7]]}],"fault":{"read":1,"stage":"execute","raise":"E"},"close_fault":"C","exception_obje'
    'cts_spec_only":{"E":{"identity":"DUAL_SQLITE|public|E","exact_class":"sqlite3.Operationa'
    'lError","args":["DUAL_SQLITE_READ_MARKER"],"str":"DUAL_SQLITE_READ_MARKER","repr":"Opera'
    'tionalError(\'DUAL_SQLITE_READ_MARKER\')","__cause__":null,"__context__":null,"__suppress_'
    'context__":false,"role":"fresh_injected_error","context_fields_are_post_call_oracle_not_'
    'fixture_assignment":true,"construction_initial_state":{"__cause__":null,"__context__":nu'
    'll,"__suppress_context__":false},"fixture_must_not_seed_context":true},"C":{"identity":"'
    'DUAL_SQLITE|public|C","exact_class":"sqlite3.DatabaseError","args":["DUAL_SQLITE_CLOSE_M'
    'ARKER"],"str":"DUAL_SQLITE_CLOSE_MARKER","repr":"DatabaseError(\'DUAL_SQLITE_CLOSE_MARKER'
    '\')","__cause__":null,"__context__":"DUAL_SQLITE|public|E","__suppress_context__":false,"'
    'role":"fresh_injected_error","context_fields_are_post_call_oracle_not_fixture_assignment'
    '":true,"construction_initial_state":{"__cause__":null,"__context__":null,"__suppress_con'
    'text__":false},"fixture_must_not_seed_context":true},"PUBLIC_CLOSED":{"identity":"DUAL_S'
    'QLITE|public|PUBLIC_CLOSED","exact_class":"builtins.ValueError","args":["Unsupported com'
    'ponent shape"],"str":"Unsupported component shape","repr":"ValueError(\'Unsupported compo'
    'nent shape\')","__cause__":null,"__context__":"DUAL_SQLITE|public|C","__suppress_context_'
    '_":true,"role":"captured_product_created_error","context_fields_are_post_call_oracle_not'
    '_fixture_assignment":true,"fixture_must_not_precreate":true}},"outcome":{"final_componen'
    't_wire_return":0,"component_wire_return_not_applicable":false,"kind":"exception","error"'
    ':{"identity":"DUAL_SQLITE|public|PUBLIC_CLOSED","exact_class":"builtins.ValueError","arg'
    's":["Unsupported component shape"],"str":"Unsupported component shape","repr":"ValueErro'
    'r(\'Unsupported component shape\')","__cause__":null,"__context__":"DUAL_SQLITE|public|C",'
    '"__suppress_context__":true},"identity_assertion_required":false,"capture_product_create'
    'd_error_only":true},"trace_oracle":[{"op":"route.call.enter","api":"recoryn.schema.compo'
    'nent_shape_wire"},{"op":"cursor.create.enter","read":1,"cursor":"DUAL_SQLITE|public|r1"}'
    ',{"op":"cursor.create.return","read":1,"cursor":"DUAL_SQLITE|public|r1","fresh_cursor":t'
    'rue},{"op":"row_factory.enter","read":1,"cursor":"DUAL_SQLITE|public|r1","value":null},{'
    '"op":"row_factory.return","read":1,"cursor":"DUAL_SQLITE|public|r1","value":null},{"op":'
    '"execute.enter","read":1,"cursor":"DUAL_SQLITE|public|r1","sql":"PRAGMA main.schema_vers'
    'ion"},{"op":"execute.raise","read":1,"cursor":"DUAL_SQLITE|public|r1","identity":"DUAL_S'
    'QLITE|public|E"},{"op":"close.enter","read":1,"cursor":"DUAL_SQLITE|public|r1"},{"op":"c'
    'lose.raise","read":1,"cursor":"DUAL_SQLITE|public|r1","identity":"DUAL_SQLITE|public|C"}'
    ',{"op":"route.raise","identity":"DUAL_SQLITE|public|PUBLIC_CLOSED","exact_class":"builti'
    'ns.ValueError"}],"trace_counts":{"cursor.create.enter":1,"cursor.create.return":1,"row_f'
    'actory.enter":1,"row_factory.return":1,"execute.enter":1,"execute.return":0,"fetchall.en'
    'ter":0,"fetchall.return":0,"close.enter":1,"close.return":0,"close.raise":1},"internal_c'
    'anonical_wire_call_count_not_constrained":true,"native_cleanup_proved":false},{"route_id'
    '":"CLOSE_NONSQLITE|private","route":"private","api_name_future_private_unimplemented":"r'
    'ecoryn.schema._component_shape_wire_read","fake_identity":"CLOSE_NONSQLITE|private|conne'
    'ction","fresh_all_objects":true,"prepare_hash_or_raise":false,"expected_model":"fresh_de'
    'ep_copy_of_hand_anchor.model","component_input":"jobs.checkpoints","program":[{"read":1,'
    '"cursor":"r1","sql":"PRAGMA main.schema_version","rows":[[7]]}],"fault":null,"close_faul'
    't":"C","exception_objects_spec_only":{"C":{"identity":"CLOSE_NONSQLITE|private|C","exact'
    '_class":"builtins.RuntimeError","args":["CLOSE_NONSQLITE_MARKER"],"str":"CLOSE_NONSQLITE'
    '_MARKER","repr":"RuntimeError(\'CLOSE_NONSQLITE_MARKER\')","__cause__":null,"__context__":'
    'null,"__suppress_context__":false,"role":"fresh_injected_error","context_fields_are_post'
    '_call_oracle_not_fixture_assignment":true,"construction_initial_state":{"__cause__":null'
    ',"__context__":null,"__suppress_context__":false},"fixture_must_not_seed_context":true}}'
    ',"outcome":{"final_component_wire_return":0,"component_wire_return_not_applicable":false'
    ',"kind":"exception","error":{"identity":"CLOSE_NONSQLITE|private|C","exact_class":"built'
    'ins.RuntimeError","args":["CLOSE_NONSQLITE_MARKER"],"str":"CLOSE_NONSQLITE_MARKER","repr'
    '":"RuntimeError(\'CLOSE_NONSQLITE_MARKER\')","__cause__":null,"__context__":null,"__suppre'
    'ss_context__":false},"identity_assertion_required":true,"capture_product_created_error_o'
    'nly":false},"trace_oracle":[{"op":"route.call.enter","api":"recoryn.schema._component_sh'
    'ape_wire_read"},{"op":"cursor.create.enter","read":1,"cursor":"CLOSE_NONSQLITE|private|r'
    '1"},{"op":"cursor.create.return","read":1,"cursor":"CLOSE_NONSQLITE|private|r1","fresh_c'
    'ursor":true},{"op":"row_factory.enter","read":1,"cursor":"CLOSE_NONSQLITE|private|r1","v'
    'alue":null},{"op":"row_factory.return","read":1,"cursor":"CLOSE_NONSQLITE|private|r1","v'
    'alue":null},{"op":"execute.enter","read":1,"cursor":"CLOSE_NONSQLITE|private|r1","sql":"'
    'PRAGMA main.schema_version"},{"op":"execute.return","read":1,"cursor":"CLOSE_NONSQLITE|p'
    'rivate|r1","value":"same_cursor"},{"op":"fetchall.enter","read":1,"cursor":"CLOSE_NONSQL'
    'ITE|private|r1"},{"op":"fetchall.return","read":1,"cursor":"CLOSE_NONSQLITE|private|r1",'
    '"rows":[[7]],"runtime_container":"list[tuple]"},{"op":"close.enter","read":1,"cursor":"C'
    'LOSE_NONSQLITE|private|r1"},{"op":"close.raise","read":1,"cursor":"CLOSE_NONSQLITE|priva'
    'te|r1","identity":"CLOSE_NONSQLITE|private|C"},{"op":"route.raise","identity":"CLOSE_NON'
    'SQLITE|private|C","exact_class":"builtins.RuntimeError"}],"trace_counts":{"cursor.create'
    '.enter":1,"cursor.create.return":1,"row_factory.enter":1,"row_factory.return":1,"execute'
    '.enter":1,"execute.return":1,"fetchall.enter":1,"fetchall.return":1,"close.enter":1,"clo'
    'se.return":0,"close.raise":1},"internal_canonical_wire_call_count_not_constrained":true,'
    '"native_cleanup_proved":false},{"route_id":"CLOSE_NONSQLITE|public","route":"public","ap'
    'i_name_future_private_unimplemented":"recoryn.schema.component_shape_wire","fake_identit'
    'y":"CLOSE_NONSQLITE|public|connection","fresh_all_objects":true,"prepare_hash_or_raise":'
    'false,"expected_model":"actual_public_expected_lookup_not_stubbed","component_input":"jo'
    'bs.checkpoints","program":[{"read":1,"cursor":"r1","sql":"PRAGMA main.schema_version","r'
    'ows":[[7]]}],"fault":null,"close_fault":"C","exception_objects_spec_only":{"C":{"identit'
    'y":"CLOSE_NONSQLITE|public|C","exact_class":"builtins.RuntimeError","args":["CLOSE_NONSQ'
    'LITE_MARKER"],"str":"CLOSE_NONSQLITE_MARKER","repr":"RuntimeError(\'CLOSE_NONSQLITE_MARKE'
    'R\')","__cause__":null,"__context__":null,"__suppress_context__":false,"role":"fresh_inje'
    'cted_error","context_fields_are_post_call_oracle_not_fixture_assignment":true,"construct'
    'ion_initial_state":{"__cause__":null,"__context__":null,"__suppress_context__":false},"f'
    'ixture_must_not_seed_context":true}},"outcome":{"final_component_wire_return":0,"compone'
    'nt_wire_return_not_applicable":false,"kind":"exception","error":{"identity":"CLOSE_NONSQ'
    'LITE|public|C","exact_class":"builtins.RuntimeError","args":["CLOSE_NONSQLITE_MARKER"],"'
    'str":"CLOSE_NONSQLITE_MARKER","repr":"RuntimeError(\'CLOSE_NONSQLITE_MARKER\')","__cause__'
    '":null,"__context__":null,"__suppress_context__":false},"identity_assertion_required":tr'
    'ue,"capture_product_created_error_only":false},"trace_oracle":[{"op":"route.call.enter",'
    '"api":"recoryn.schema.component_shape_wire"},{"op":"cursor.create.enter","read":1,"curso'
    'r":"CLOSE_NONSQLITE|public|r1"},{"op":"cursor.create.return","read":1,"cursor":"CLOSE_NO'
    'NSQLITE|public|r1","fresh_cursor":true},{"op":"row_factory.enter","read":1,"cursor":"CLO'
    'SE_NONSQLITE|public|r1","value":null},{"op":"row_factory.return","read":1,"cursor":"CLOS'
    'E_NONSQLITE|public|r1","value":null},{"op":"execute.enter","read":1,"cursor":"CLOSE_NONS'
    'QLITE|public|r1","sql":"PRAGMA main.schema_version"},{"op":"execute.return","read":1,"cu'
    'rsor":"CLOSE_NONSQLITE|public|r1","value":"same_cursor"},{"op":"fetchall.enter","read":1'
    ',"cursor":"CLOSE_NONSQLITE|public|r1"},{"op":"fetchall.return","read":1,"cursor":"CLOSE_'
    'NONSQLITE|public|r1","rows":[[7]],"runtime_container":"list[tuple]"},{"op":"close.enter"'
    ',"read":1,"cursor":"CLOSE_NONSQLITE|public|r1"},{"op":"close.raise","read":1,"cursor":"C'
    'LOSE_NONSQLITE|public|r1","identity":"CLOSE_NONSQLITE|public|C"},{"op":"route.raise","id'
    'entity":"CLOSE_NONSQLITE|public|C","exact_class":"builtins.RuntimeError"}],"trace_counts'
    '":{"cursor.create.enter":1,"cursor.create.return":1,"row_factory.enter":1,"row_factory.r'
    'eturn":1,"execute.enter":1,"execute.return":1,"fetchall.enter":1,"fetchall.return":1,"cl'
    'ose.enter":1,"close.return":0,"close.raise":1},"internal_canonical_wire_call_count_not_c'
    'onstrained":true,"native_cleanup_proved":false},{"route_id":"DUAL_CLOSE_NONSQLITE|privat'
    'e","route":"private","api_name_future_private_unimplemented":"recoryn.schema._component_'
    'shape_wire_read","fake_identity":"DUAL_CLOSE_NONSQLITE|private|connection","fresh_all_ob'
    'jects":true,"prepare_hash_or_raise":false,"expected_model":"fresh_deep_copy_of_hand_anch'
    'or.model","component_input":"jobs.checkpoints","program":[{"read":1,"cursor":"r1","sql":'
    '"PRAGMA main.schema_version","rows":[[7]]}],"fault":{"read":1,"stage":"execute","raise":'
    '"E"},"close_fault":"C","exception_objects_spec_only":{"E":{"identity":"DUAL_CLOSE_NONSQL'
    'ITE|private|E","exact_class":"sqlite3.OperationalError","args":["DUAL_CLOSE_READ_MARKER"'
    '],"str":"DUAL_CLOSE_READ_MARKER","repr":"OperationalError(\'DUAL_CLOSE_READ_MARKER\')","__'
    'cause__":null,"__context__":null,"__suppress_context__":false,"role":"fresh_injected_err'
    'or","context_fields_are_post_call_oracle_not_fixture_assignment":true,"construction_init'
    'ial_state":{"__cause__":null,"__context__":null,"__suppress_context__":false},"fixture_m'
    'ust_not_seed_context":true},"C":{"identity":"DUAL_CLOSE_NONSQLITE|private|C","exact_clas'
    's":"builtins.RuntimeError","args":["DUAL_CLOSE_NONSQLITE_CLOSE_MARKER"],"str":"DUAL_CLOS'
    'E_NONSQLITE_CLOSE_MARKER","repr":"RuntimeError(\'DUAL_CLOSE_NONSQLITE_CLOSE_MARKER\')","__'
    'cause__":null,"__context__":"DUAL_CLOSE_NONSQLITE|private|E","__suppress_context__":fals'
    'e,"role":"fresh_injected_error","context_fields_are_post_call_oracle_not_fixture_assignm'
    'ent":true,"construction_initial_state":{"__cause__":null,"__context__":null,"__suppress_'
    'context__":false},"fixture_must_not_seed_context":true}},"outcome":{"final_component_wir'
    'e_return":0,"component_wire_return_not_applicable":false,"kind":"exception","error":{"id'
    'entity":"DUAL_CLOSE_NONSQLITE|private|C","exact_class":"builtins.RuntimeError","args":["'
    'DUAL_CLOSE_NONSQLITE_CLOSE_MARKER"],"str":"DUAL_CLOSE_NONSQLITE_CLOSE_MARKER","repr":"Ru'
    'ntimeError(\'DUAL_CLOSE_NONSQLITE_CLOSE_MARKER\')","__cause__":null,"__context__":"DUAL_CL'
    'OSE_NONSQLITE|private|E","__suppress_context__":false},"identity_assertion_required":tru'
    'e,"capture_product_created_error_only":false},"trace_oracle":[{"op":"route.call.enter","'
    'api":"recoryn.schema._component_shape_wire_read"},{"op":"cursor.create.enter","read":1,"'
    'cursor":"DUAL_CLOSE_NONSQLITE|private|r1"},{"op":"cursor.create.return","read":1,"cursor'
    '":"DUAL_CLOSE_NONSQLITE|private|r1","fresh_cursor":true},{"op":"row_factory.enter","read'
    '":1,"cursor":"DUAL_CLOSE_NONSQLITE|private|r1","value":null},{"op":"row_factory.return",'
    '"read":1,"cursor":"DUAL_CLOSE_NONSQLITE|private|r1","value":null},{"op":"execute.enter",'
    '"read":1,"cursor":"DUAL_CLOSE_NONSQLITE|private|r1","sql":"PRAGMA main.schema_version"},'
    '{"op":"execute.raise","read":1,"cursor":"DUAL_CLOSE_NONSQLITE|private|r1","identity":"DU'
    'AL_CLOSE_NONSQLITE|private|E"},{"op":"close.enter","read":1,"cursor":"DUAL_CLOSE_NONSQLI'
    'TE|private|r1"},{"op":"close.raise","read":1,"cursor":"DUAL_CLOSE_NONSQLITE|private|r1",'
    '"identity":"DUAL_CLOSE_NONSQLITE|private|C"},{"op":"route.raise","identity":"DUAL_CLOSE_'
    'NONSQLITE|private|C","exact_class":"builtins.RuntimeError"}],"trace_counts":{"cursor.cre'
    'ate.enter":1,"cursor.create.return":1,"row_factory.enter":1,"row_factory.return":1,"exec'
    'ute.enter":1,"execute.return":0,"fetchall.enter":0,"fetchall.return":0,"close.enter":1,"'
    'close.return":0,"close.raise":1},"internal_canonical_wire_call_count_not_constrained":tr'
    'ue,"native_cleanup_proved":false},{"route_id":"DUAL_CLOSE_NONSQLITE|public","route":"pub'
    'lic","api_name_future_private_unimplemented":"recoryn.schema.component_shape_wire","fake'
    '_identity":"DUAL_CLOSE_NONSQLITE|public|connection","fresh_all_objects":true,"prepare_ha'
    'sh_or_raise":false,"expected_model":"actual_public_expected_lookup_not_stubbed","compone'
    'nt_input":"jobs.checkpoints","program":[{"read":1,"cursor":"r1","sql":"PRAGMA main.schem'
    'a_version","rows":[[7]]}],"fault":{"read":1,"stage":"execute","raise":"E"},"close_fault"'
    ':"C","exception_objects_spec_only":{"E":{"identity":"DUAL_CLOSE_NONSQLITE|public|E","exa'
    'ct_class":"sqlite3.OperationalError","args":["DUAL_CLOSE_READ_MARKER"],"str":"DUAL_CLOSE'
    '_READ_MARKER","repr":"OperationalError(\'DUAL_CLOSE_READ_MARKER\')","__cause__":null,"__co'
    'ntext__":null,"__suppress_context__":false,"role":"fresh_injected_error","context_fields'
    '_are_post_call_oracle_not_fixture_assignment":true,"construction_initial_state":{"__caus'
    'e__":null,"__context__":null,"__suppress_context__":false},"fixture_must_not_seed_contex'
    't":true},"C":{"identity":"DUAL_CLOSE_NONSQLITE|public|C","exact_class":"builtins.Runtime'
    'Error","args":["DUAL_CLOSE_NONSQLITE_CLOSE_MARKER"],"str":"DUAL_CLOSE_NONSQLITE_CLOSE_MA'
    'RKER","repr":"RuntimeError(\'DUAL_CLOSE_NONSQLITE_CLOSE_MARKER\')","__cause__":null,"__con'
    'text__":"DUAL_CLOSE_NONSQLITE|public|E","__suppress_context__":false,"role":"fresh_injec'
    'ted_error","context_fields_are_post_call_oracle_not_fixture_assignment":true,"constructi'
    'on_initial_state":{"__cause__":null,"__context__":null,"__suppress_context__":false},"fi'
    'xture_must_not_seed_context":true}},"outcome":{"final_component_wire_return":0,"componen'
    't_wire_return_not_applicable":false,"kind":"exception","error":{"identity":"DUAL_CLOSE_N'
    'ONSQLITE|public|C","exact_class":"builtins.RuntimeError","args":["DUAL_CLOSE_NONSQLITE_C'
    'LOSE_MARKER"],"str":"DUAL_CLOSE_NONSQLITE_CLOSE_MARKER","repr":"RuntimeError(\'DUAL_CLOSE'
    '_NONSQLITE_CLOSE_MARKER\')","__cause__":null,"__context__":"DUAL_CLOSE_NONSQLITE|public|E'
    '","__suppress_context__":false},"identity_assertion_required":true,"capture_product_crea'
    'ted_error_only":false},"trace_oracle":[{"op":"route.call.enter","api":"recoryn.schema.co'
    'mponent_shape_wire"},{"op":"cursor.create.enter","read":1,"cursor":"DUAL_CLOSE_NONSQLITE'
    '|public|r1"},{"op":"cursor.create.return","read":1,"cursor":"DUAL_CLOSE_NONSQLITE|public'
    '|r1","fresh_cursor":true},{"op":"row_factory.enter","read":1,"cursor":"DUAL_CLOSE_NONSQL'
    'ITE|public|r1","value":null},{"op":"row_factory.return","read":1,"cursor":"DUAL_CLOSE_NO'
    'NSQLITE|public|r1","value":null},{"op":"execute.enter","read":1,"cursor":"DUAL_CLOSE_NON'
    'SQLITE|public|r1","sql":"PRAGMA main.schema_version"},{"op":"execute.raise","read":1,"cu'
    'rsor":"DUAL_CLOSE_NONSQLITE|public|r1","identity":"DUAL_CLOSE_NONSQLITE|public|E"},{"op"'
    ':"close.enter","read":1,"cursor":"DUAL_CLOSE_NONSQLITE|public|r1"},{"op":"close.raise","'
    'read":1,"cursor":"DUAL_CLOSE_NONSQLITE|public|r1","identity":"DUAL_CLOSE_NONSQLITE|publi'
    'c|C"},{"op":"route.raise","identity":"DUAL_CLOSE_NONSQLITE|public|C","exact_class":"buil'
    'tins.RuntimeError"}],"trace_counts":{"cursor.create.enter":1,"cursor.create.return":1,"r'
    'ow_factory.enter":1,"row_factory.return":1,"execute.enter":1,"execute.return":0,"fetchal'
    'l.enter":0,"fetchall.return":0,"close.enter":1,"close.return":0,"close.raise":1},"intern'
    'al_canonical_wire_call_count_not_constrained":true,"native_cleanup_proved":false},{"rout'
    'e_id":"NONSQLITE_VALUEERROR|private","route":"private","api_name_future_private_unimplem'
    'ented":"recoryn.schema._component_shape_wire_read","fake_identity":"NONSQLITE_VALUEERROR'
    '|private|connection","fresh_all_objects":true,"prepare_hash_or_raise":false,"expected_mo'
    'del":"fresh_deep_copy_of_hand_anchor.model","component_input":"jobs.checkpoints","progra'
    'm":[{"read":1,"cursor":"r1","sql":"PRAGMA main.schema_version","rows":[[7]]}],"fault":{"'
    'read":1,"stage":"execute","raise":"E"},"close_fault":null,"exception_objects_spec_only":'
    '{"E":{"identity":"NONSQLITE_VALUEERROR|private|E","exact_class":"builtins.ValueError","a'
    'rgs":["NONSQLITE_VALUEERROR_MARKER"],"str":"NONSQLITE_VALUEERROR_MARKER","repr":"ValueEr'
    'ror(\'NONSQLITE_VALUEERROR_MARKER\')","__cause__":null,"__context__":null,"__suppress_cont'
    'ext__":false,"role":"fresh_injected_error","context_fields_are_post_call_oracle_not_fixt'
    'ure_assignment":true,"construction_initial_state":{"__cause__":null,"__context__":null,"'
    '__suppress_context__":false},"fixture_must_not_seed_context":true}},"outcome":{"final_co'
    'mponent_wire_return":0,"component_wire_return_not_applicable":false,"kind":"exception","'
    'error":{"identity":"NONSQLITE_VALUEERROR|private|E","exact_class":"builtins.ValueError",'
    '"args":["NONSQLITE_VALUEERROR_MARKER"],"str":"NONSQLITE_VALUEERROR_MARKER","repr":"Value'
    'Error(\'NONSQLITE_VALUEERROR_MARKER\')","__cause__":null,"__context__":null,"__suppress_co'
    'ntext__":false},"identity_assertion_required":true,"capture_product_created_error_only":'
    'false},"trace_oracle":[{"op":"route.call.enter","api":"recoryn.schema._component_shape_w'
    'ire_read"},{"op":"cursor.create.enter","read":1,"cursor":"NONSQLITE_VALUEERROR|private|r'
    '1"},{"op":"cursor.create.return","read":1,"cursor":"NONSQLITE_VALUEERROR|private|r1","fr'
    'esh_cursor":true},{"op":"row_factory.enter","read":1,"cursor":"NONSQLITE_VALUEERROR|priv'
    'ate|r1","value":null},{"op":"row_factory.return","read":1,"cursor":"NONSQLITE_VALUEERROR'
    '|private|r1","value":null},{"op":"execute.enter","read":1,"cursor":"NONSQLITE_VALUEERROR'
    '|private|r1","sql":"PRAGMA main.schema_version"},{"op":"execute.raise","read":1,"cursor"'
    ':"NONSQLITE_VALUEERROR|private|r1","identity":"NONSQLITE_VALUEERROR|private|E"},{"op":"c'
    'lose.enter","read":1,"cursor":"NONSQLITE_VALUEERROR|private|r1"},{"op":"close.return","r'
    'ead":1,"cursor":"NONSQLITE_VALUEERROR|private|r1","value":null},{"op":"route.raise","ide'
    'ntity":"NONSQLITE_VALUEERROR|private|E","exact_class":"builtins.ValueError"}],"trace_cou'
    'nts":{"cursor.create.enter":1,"cursor.create.return":1,"row_factory.enter":1,"row_factor'
    'y.return":1,"execute.enter":1,"execute.return":0,"fetchall.enter":0,"fetchall.return":0,'
    '"close.enter":1,"close.return":1,"close.raise":0},"internal_canonical_wire_call_count_no'
    't_constrained":true,"native_cleanup_proved":false},{"route_id":"NONSQLITE_VALUEERROR|pub'
    'lic","route":"public","api_name_future_private_unimplemented":"recoryn.schema.component_'
    'shape_wire","fake_identity":"NONSQLITE_VALUEERROR|public|connection","fresh_all_objects"'
    ':true,"prepare_hash_or_raise":false,"expected_model":"actual_public_expected_lookup_not_'
    'stubbed","component_input":"jobs.checkpoints","program":[{"read":1,"cursor":"r1","sql":"'
    'PRAGMA main.schema_version","rows":[[7]]}],"fault":{"read":1,"stage":"execute","raise":"'
    'E"},"close_fault":null,"exception_objects_spec_only":{"E":{"identity":"NONSQLITE_VALUEER'
    'ROR|public|E","exact_class":"builtins.ValueError","args":["NONSQLITE_VALUEERROR_MARKER"]'
    ',"str":"NONSQLITE_VALUEERROR_MARKER","repr":"ValueError(\'NONSQLITE_VALUEERROR_MARKER\')",'
    '"__cause__":null,"__context__":null,"__suppress_context__":false,"role":"fresh_injected_'
    'error","context_fields_are_post_call_oracle_not_fixture_assignment":true,"construction_i'
    'nitial_state":{"__cause__":null,"__context__":null,"__suppress_context__":false},"fixtur'
    'e_must_not_seed_context":true}},"outcome":{"final_component_wire_return":0,"component_wi'
    're_return_not_applicable":false,"kind":"exception","error":{"identity":"NONSQLITE_VALUEE'
    'RROR|public|E","exact_class":"builtins.ValueError","args":["NONSQLITE_VALUEERROR_MARKER"'
    '],"str":"NONSQLITE_VALUEERROR_MARKER","repr":"ValueError(\'NONSQLITE_VALUEERROR_MARKER\')"'
    ',"__cause__":null,"__context__":null,"__suppress_context__":false},"identity_assertion_r'
    'equired":true,"capture_product_created_error_only":false},"trace_oracle":[{"op":"route.c'
    'all.enter","api":"recoryn.schema.component_shape_wire"},{"op":"cursor.create.enter","rea'
    'd":1,"cursor":"NONSQLITE_VALUEERROR|public|r1"},{"op":"cursor.create.return","read":1,"c'
    'ursor":"NONSQLITE_VALUEERROR|public|r1","fresh_cursor":true},{"op":"row_factory.enter","'
    'read":1,"cursor":"NONSQLITE_VALUEERROR|public|r1","value":null},{"op":"row_factory.retur'
    'n","read":1,"cursor":"NONSQLITE_VALUEERROR|public|r1","value":null},{"op":"execute.enter'
    '","read":1,"cursor":"NONSQLITE_VALUEERROR|public|r1","sql":"PRAGMA main.schema_version"}'
    ',{"op":"execute.raise","read":1,"cursor":"NONSQLITE_VALUEERROR|public|r1","identity":"NO'
    'NSQLITE_VALUEERROR|public|E"},{"op":"close.enter","read":1,"cursor":"NONSQLITE_VALUEERRO'
    'R|public|r1"},{"op":"close.return","read":1,"cursor":"NONSQLITE_VALUEERROR|public|r1","v'
    'alue":null},{"op":"route.raise","identity":"NONSQLITE_VALUEERROR|public|E","exact_class"'
    ':"builtins.ValueError"}],"trace_counts":{"cursor.create.enter":1,"cursor.create.return":'
    '1,"row_factory.enter":1,"row_factory.return":1,"execute.enter":1,"execute.return":0,"fet'
    'chall.enter":0,"fetchall.return":0,"close.enter":1,"close.return":1,"close.raise":0},"in'
    'ternal_canonical_wire_call_count_not_constrained":true,"native_cleanup_proved":false},{"'
    'route_id":"INTERRUPT|private","route":"private","api_name_future_private_unimplemented":'
    '"recoryn.schema._component_shape_wire_read","fake_identity":"INTERRUPT|private|connectio'
    'n","fresh_all_objects":true,"prepare_hash_or_raise":false,"expected_model":"fresh_deep_c'
    'opy_of_hand_anchor.model","component_input":"jobs.checkpoints","program":[{"read":1,"cur'
    'sor":"r1","sql":"PRAGMA main.schema_version","rows":[[7]]}],"fault":{"read":1,"stage":"e'
    'xecute","raise":"E"},"close_fault":null,"exception_objects_spec_only":{"E":{"identity":"'
    'INTERRUPT|private|E","exact_class":"builtins.KeyboardInterrupt","args":["INTERRUPT_MARKE'
    'R"],"str":"INTERRUPT_MARKER","repr":"KeyboardInterrupt(\'INTERRUPT_MARKER\')","__cause__":'
    'null,"__context__":null,"__suppress_context__":false,"role":"fresh_injected_error","cont'
    'ext_fields_are_post_call_oracle_not_fixture_assignment":true,"construction_initial_state'
    '":{"__cause__":null,"__context__":null,"__suppress_context__":false},"fixture_must_not_s'
    'eed_context":true}},"outcome":{"final_component_wire_return":0,"component_wire_return_no'
    't_applicable":false,"kind":"exception","error":{"identity":"INTERRUPT|private|E","exact_'
    'class":"builtins.KeyboardInterrupt","args":["INTERRUPT_MARKER"],"str":"INTERRUPT_MARKER"'
    ',"repr":"KeyboardInterrupt(\'INTERRUPT_MARKER\')","__cause__":null,"__context__":null,"__s'
    'uppress_context__":false},"identity_assertion_required":true,"capture_product_created_er'
    'ror_only":false},"trace_oracle":[{"op":"route.call.enter","api":"recoryn.schema._compone'
    'nt_shape_wire_read"},{"op":"cursor.create.enter","read":1,"cursor":"INTERRUPT|private|r1'
    '"},{"op":"cursor.create.return","read":1,"cursor":"INTERRUPT|private|r1","fresh_cursor":'
    'true},{"op":"row_factory.enter","read":1,"cursor":"INTERRUPT|private|r1","value":null},{'
    '"op":"row_factory.return","read":1,"cursor":"INTERRUPT|private|r1","value":null},{"op":"'
    'execute.enter","read":1,"cursor":"INTERRUPT|private|r1","sql":"PRAGMA main.schema_versio'
    'n"},{"op":"execute.raise","read":1,"cursor":"INTERRUPT|private|r1","identity":"INTERRUPT'
    '|private|E"},{"op":"close.enter","read":1,"cursor":"INTERRUPT|private|r1"},{"op":"close.'
    'return","read":1,"cursor":"INTERRUPT|private|r1","value":null},{"op":"route.raise","iden'
    'tity":"INTERRUPT|private|E","exact_class":"builtins.KeyboardInterrupt"}],"trace_counts":'
    '{"cursor.create.enter":1,"cursor.create.return":1,"row_factory.enter":1,"row_factory.ret'
    'urn":1,"execute.enter":1,"execute.return":0,"fetchall.enter":0,"fetchall.return":0,"clos'
    'e.enter":1,"close.return":1,"close.raise":0},"internal_canonical_wire_call_count_not_con'
    'strained":true,"native_cleanup_proved":false},{"route_id":"INTERRUPT|public","route":"pu'
    'blic","api_name_future_private_unimplemented":"recoryn.schema.component_shape_wire","fak'
    'e_identity":"INTERRUPT|public|connection","fresh_all_objects":true,"prepare_hash_or_rais'
    'e":false,"expected_model":"actual_public_expected_lookup_not_stubbed","component_input":'
    '"jobs.checkpoints","program":[{"read":1,"cursor":"r1","sql":"PRAGMA main.schema_version"'
    ',"rows":[[7]]}],"fault":{"read":1,"stage":"execute","raise":"E"},"close_fault":null,"exc'
    'eption_objects_spec_only":{"E":{"identity":"INTERRUPT|public|E","exact_class":"builtins.'
    'KeyboardInterrupt","args":["INTERRUPT_MARKER"],"str":"INTERRUPT_MARKER","repr":"Keyboard'
    'Interrupt(\'INTERRUPT_MARKER\')","__cause__":null,"__context__":null,"__suppress_context__'
    '":false,"role":"fresh_injected_error","context_fields_are_post_call_oracle_not_fixture_a'
    'ssignment":true,"construction_initial_state":{"__cause__":null,"__context__":null,"__sup'
    'press_context__":false},"fixture_must_not_seed_context":true}},"outcome":{"final_compone'
    'nt_wire_return":0,"component_wire_return_not_applicable":false,"kind":"exception","error'
    '":{"identity":"INTERRUPT|public|E","exact_class":"builtins.KeyboardInterrupt","args":["I'
    'NTERRUPT_MARKER"],"str":"INTERRUPT_MARKER","repr":"KeyboardInterrupt(\'INTERRUPT_MARKER\')'
    '","__cause__":null,"__context__":null,"__suppress_context__":false},"identity_assertion_'
    'required":true,"capture_product_created_error_only":false},"trace_oracle":[{"op":"route.'
    'call.enter","api":"recoryn.schema.component_shape_wire"},{"op":"cursor.create.enter","re'
    'ad":1,"cursor":"INTERRUPT|public|r1"},{"op":"cursor.create.return","read":1,"cursor":"IN'
    'TERRUPT|public|r1","fresh_cursor":true},{"op":"row_factory.enter","read":1,"cursor":"INT'
    'ERRUPT|public|r1","value":null},{"op":"row_factory.return","read":1,"cursor":"INTERRUPT|'
    'public|r1","value":null},{"op":"execute.enter","read":1,"cursor":"INTERRUPT|public|r1","'
    'sql":"PRAGMA main.schema_version"},{"op":"execute.raise","read":1,"cursor":"INTERRUPT|pu'
    'blic|r1","identity":"INTERRUPT|public|E"},{"op":"close.enter","read":1,"cursor":"INTERRU'
    'PT|public|r1"},{"op":"close.return","read":1,"cursor":"INTERRUPT|public|r1","value":null'
    '},{"op":"route.raise","identity":"INTERRUPT|public|E","exact_class":"builtins.KeyboardIn'
    'terrupt"}],"trace_counts":{"cursor.create.enter":1,"cursor.create.return":1,"row_factory'
    '.enter":1,"row_factory.return":1,"execute.enter":1,"execute.return":0,"fetchall.enter":0'
    ',"fetchall.return":0,"close.enter":1,"close.return":1,"close.raise":0},"internal_canonic'
    'al_wire_call_count_not_constrained":true,"native_cleanup_proved":false},{"route_id":"EXP'
    'ECTED_OUTSIDE|public","route":"public","api_name_future_private_unimplemented":"recoryn.'
    'schema.component_shape_wire","fake_identity":"EXPECTED_OUTSIDE|public|connection","fresh'
    '_all_objects":true,"prepare_hash_or_raise":false,"expected_model":"actual_public_expecte'
    'd_lookup_not_stubbed","component_input":"str_subclass_value_jobs.checkpoints_hash_raises'
    '_E_in_actual_call_only","program":[],"fault":null,"close_fault":null,"exception_objects_'
    'spec_only":{"E":{"identity":"EXPECTED_OUTSIDE|public|E","exact_class":"sqlite3.Operation'
    'alError","args":["EXPECTED_HASH_MARKER"],"str":"EXPECTED_HASH_MARKER","repr":"Operationa'
    'lError(\'EXPECTED_HASH_MARKER\')","__cause__":null,"__context__":null,"__suppress_context_'
    '_":false,"role":"fresh_injected_error","context_fields_are_post_call_oracle_not_fixture_'
    'assignment":true,"construction_initial_state":{"__cause__":null,"__context__":null,"__su'
    'ppress_context__":false},"fixture_must_not_seed_context":true}},"outcome":{"final_compon'
    'ent_wire_return":0,"component_wire_return_not_applicable":false,"kind":"exception","erro'
    'r":{"identity":"EXPECTED_OUTSIDE|public|E","exact_class":"sqlite3.OperationalError","arg'
    's":["EXPECTED_HASH_MARKER"],"str":"EXPECTED_HASH_MARKER","repr":"OperationalError(\'EXPEC'
    'TED_HASH_MARKER\')","__cause__":null,"__context__":null,"__suppress_context__":false},"id'
    'entity_assertion_required":true,"capture_product_created_error_only":false},"trace_oracl'
    'e":[{"op":"route.call.enter","api":"recoryn.schema.component_shape_wire"},{"op":"compone'
    'nt.__hash__.enter","phase":"actual_public_call_only"},{"op":"component.__hash__.raise","'
    'identity":"EXPECTED_OUTSIDE|public|E"},{"op":"route.raise","identity":"EXPECTED_OUTSIDE|'
    'public|E","exact_class":"sqlite3.OperationalError"}],"trace_counts":{"cursor.create.ente'
    'r":0,"cursor.create.return":0,"row_factory.enter":0,"row_factory.return":0,"execute.ente'
    'r":0,"execute.return":0,"fetchall.enter":0,"fetchall.return":0,"close.enter":0,"close.re'
    'turn":0,"close.raise":0},"internal_canonical_wire_call_count_not_constrained":true,"nati'
    've_cleanup_proved":false},{"route_id":"INDEX_READ_ERROR|_index_keys","route":"_index_key'
    's","api_name_future_private_unimplemented":"recoryn.schema._index_keys","fake_identity":'
    '"INDEX_READ_ERROR|_index_keys|connection","fresh_all_objects":true,"prepare_hash_or_rais'
    'e":false,"expected_model":null,"component_input":"jobs.checkpoints","program":[{"read":1'
    ',"cursor":"r1","sql":"PRAGMA main.index_xinfo(\\"sqlite_autoindex_job_checkpoints_1\\")","'
    'rows":[[0,0,"job_id",0,"BINARY",1],[1,2,"result_ref",0,"BINARY",1],[2,-1,null,0,"BINARY"'
    ',0]]}],"fault":{"read":1,"stage":"execute","raise":"E"},"close_fault":null,"exception_ob'
    'jects_spec_only":{"E":{"identity":"INDEX_READ_ERROR|_index_keys|E","exact_class":"sqlite'
    '3.OperationalError","args":["INDEX_READ_ERROR_MARKER"],"str":"INDEX_READ_ERROR_MARKER","'
    'repr":"OperationalError(\'INDEX_READ_ERROR_MARKER\')","__cause__":null,"__context__":null,'
    '"__suppress_context__":false,"role":"fresh_injected_error","context_fields_are_post_call'
    '_oracle_not_fixture_assignment":true,"construction_initial_state":{"__cause__":null,"__c'
    'ontext__":null,"__suppress_context__":false},"fixture_must_not_seed_context":true}},"out'
    'come":{"final_component_wire_return":0,"component_wire_return_not_applicable":true,"kind'
    '":"exception","error":{"identity":"INDEX_READ_ERROR|_index_keys|E","exact_class":"sqlite'
    '3.OperationalError","args":["INDEX_READ_ERROR_MARKER"],"str":"INDEX_READ_ERROR_MARKER","'
    'repr":"OperationalError(\'INDEX_READ_ERROR_MARKER\')","__cause__":null,"__context__":null,'
    '"__suppress_context__":false},"identity_assertion_required":true,"capture_product_create'
    'd_error_only":false},"trace_oracle":[{"op":"route.call.enter","api":"recoryn.schema._ind'
    'ex_keys"},{"op":"cursor.create.enter","read":1,"cursor":"INDEX_READ_ERROR|_index_keys|r1'
    '"},{"op":"cursor.create.return","read":1,"cursor":"INDEX_READ_ERROR|_index_keys|r1","fre'
    'sh_cursor":true},{"op":"row_factory.enter","read":1,"cursor":"INDEX_READ_ERROR|_index_ke'
    'ys|r1","value":null},{"op":"row_factory.return","read":1,"cursor":"INDEX_READ_ERROR|_ind'
    'ex_keys|r1","value":null},{"op":"execute.enter","read":1,"cursor":"INDEX_READ_ERROR|_ind'
    'ex_keys|r1","sql":"PRAGMA main.index_xinfo(\\"sqlite_autoindex_job_checkpoints_1\\")"},{"o'
    'p":"execute.raise","read":1,"cursor":"INDEX_READ_ERROR|_index_keys|r1","identity":"INDEX'
    '_READ_ERROR|_index_keys|E"},{"op":"close.enter","read":1,"cursor":"INDEX_READ_ERROR|_ind'
    'ex_keys|r1"},{"op":"close.return","read":1,"cursor":"INDEX_READ_ERROR|_index_keys|r1","v'
    'alue":null},{"op":"route.raise","identity":"INDEX_READ_ERROR|_index_keys|E","exact_class'
    '":"sqlite3.OperationalError"}],"trace_counts":{"cursor.create.enter":1,"cursor.create.re'
    'turn":1,"row_factory.enter":1,"row_factory.return":1,"execute.enter":1,"execute.return":'
    '0,"fetchall.enter":0,"fetchall.return":0,"close.enter":1,"close.return":1,"close.raise":'
    '0},"internal_canonical_wire_call_count_not_constrained":true,"native_cleanup_proved":fal'
    'se},{"route_id":"TABLE_READ_ERROR|_verify_table","route":"_verify_table","api_name_futur'
    'e_private_unimplemented":"recoryn.schema._verify_table","fake_identity":"TABLE_READ_ERRO'
    'R|_verify_table|connection","fresh_all_objects":true,"prepare_hash_or_raise":false,"expe'
    'cted_model":"fresh_deep_copy_of_hand_anchor.model.objects[0]","component_input":"jobs.ch'
    'eckpoints","program":[{"read":1,"cursor":"r1","sql":"PRAGMA main.table_xinfo(\\"job_check'
    'points\\")","rows":[[0,"job_id","TEXT",1,null,0,0],[1,"attempt_id","TEXT",1,null,0,0],[2,'
    '"result_ref","TEXT",1,null,0,0]]}],"fault":{"read":1,"stage":"execute","raise":"E"},"clo'
    'se_fault":null,"exception_objects_spec_only":{"E":{"identity":"TABLE_READ_ERROR|_verify_'
    'table|E","exact_class":"sqlite3.OperationalError","args":["TABLE_READ_ERROR_MARKER"],"st'
    'r":"TABLE_READ_ERROR_MARKER","repr":"OperationalError(\'TABLE_READ_ERROR_MARKER\')","__cau'
    'se__":null,"__context__":null,"__suppress_context__":false,"role":"fresh_injected_error"'
    ',"context_fields_are_post_call_oracle_not_fixture_assignment":true,"construction_initial'
    '_state":{"__cause__":null,"__context__":null,"__suppress_context__":false},"fixture_must'
    '_not_seed_context":true}},"outcome":{"final_component_wire_return":0,"component_wire_ret'
    'urn_not_applicable":true,"kind":"exception","error":{"identity":"TABLE_READ_ERROR|_verif'
    'y_table|E","exact_class":"sqlite3.OperationalError","args":["TABLE_READ_ERROR_MARKER"],"'
    'str":"TABLE_READ_ERROR_MARKER","repr":"OperationalError(\'TABLE_READ_ERROR_MARKER\')","__c'
    'ause__":null,"__context__":null,"__suppress_context__":false},"identity_assertion_requir'
    'ed":true,"capture_product_created_error_only":false},"trace_oracle":[{"op":"route.call.e'
    'nter","api":"recoryn.schema._verify_table"},{"op":"cursor.create.enter","read":1,"cursor'
    '":"TABLE_READ_ERROR|_verify_table|r1"},{"op":"cursor.create.return","read":1,"cursor":"T'
    'ABLE_READ_ERROR|_verify_table|r1","fresh_cursor":true},{"op":"row_factory.enter","read":'
    '1,"cursor":"TABLE_READ_ERROR|_verify_table|r1","value":null},{"op":"row_factory.return",'
    '"read":1,"cursor":"TABLE_READ_ERROR|_verify_table|r1","value":null},{"op":"execute.enter'
    '","read":1,"cursor":"TABLE_READ_ERROR|_verify_table|r1","sql":"PRAGMA main.table_xinfo(\\'
    '"job_checkpoints\\")"},{"op":"execute.raise","read":1,"cursor":"TABLE_READ_ERROR|_verify_'
    'table|r1","identity":"TABLE_READ_ERROR|_verify_table|E"},{"op":"close.enter","read":1,"c'
    'ursor":"TABLE_READ_ERROR|_verify_table|r1"},{"op":"close.return","read":1,"cursor":"TABL'
    'E_READ_ERROR|_verify_table|r1","value":null},{"op":"route.raise","identity":"TABLE_READ_'
    'ERROR|_verify_table|E","exact_class":"sqlite3.OperationalError"}],"trace_counts":{"curso'
    'r.create.enter":1,"cursor.create.return":1,"row_factory.enter":1,"row_factory.return":1,'
    '"execute.enter":1,"execute.return":0,"fetchall.enter":0,"fetchall.return":0,"close.enter'
    '":1,"close.return":1,"close.raise":0},"internal_canonical_wire_call_count_not_constraine'
    'd":true,"native_cleanup_proved":false},{"route_id":"PRIVATE_WIRE_OK|private","route":"pr'
    'ivate","api_name_future_private_unimplemented":"recoryn.schema._component_shape_wire_rea'
    'd","fake_identity":"PRIVATE_WIRE_OK|private|connection","fresh_all_objects":true,"prepar'
    'e_hash_or_raise":false,"expected_model":"fresh_deep_copy_of_hand_anchor.model","componen'
    't_input":"jobs.checkpoints","program":[{"read":1,"cursor":"r1","sql":"PRAGMA main.schema'
    '_version","rows":[[7]]},{"read":2,"cursor":"r2","sql":"SELECT type,name,tbl_name,sql FRO'
    'M main.sqlite_schema","rows":[["table","job_checkpoints","job_checkpoints","CREATE TABLE'
    " IF NOT EXISTS job_checkpoints (job_id TEXT NOT NULL REFERENCES jobs(job_id), attempt_id"
    ' TEXT NOT NULL, result_ref TEXT NOT NULL, UNIQUE(job_id,result_ref));"],["index","sqlite'
    '_autoindex_job_checkpoints_1","job_checkpoints",null]]},{"read":3,"cursor":"r3","sql":"P'
    'RAGMA main.table_xinfo(\\"job_checkpoints\\")","rows":[[0,"job_id","TEXT",1,null,0,0],[1,"'
    'attempt_id","TEXT",1,null,0,0],[2,"result_ref","TEXT",1,null,0,0]]},{"read":4,"cursor":"'
    'r4","sql":"PRAGMA main.foreign_key_list(\\"job_checkpoints\\")","rows":[[0,0,"jobs","job_i'
    'd","job_id","NO ACTION","NO ACTION","NONE"]]},{"read":5,"cursor":"r5","sql":"PRAGMA main'
    '.index_list(\\"job_checkpoints\\")","rows":[[0,"sqlite_autoindex_job_checkpoints_1",1,"u",'
    '0]]},{"read":6,"cursor":"r6","sql":"PRAGMA main.index_xinfo(\\"sqlite_autoindex_job_check'
    'points_1\\")","rows":[[0,0,"job_id",0,"BINARY",1],[1,2,"result_ref",0,"BINARY",1],[2,-1,n'
    'ull,0,"BINARY",0]]},{"read":7,"cursor":"r7","sql":"PRAGMA main.schema_version","rows":[['
    '7]]}],"fault":null,"close_fault":null,"exception_objects_spec_only":{},"outcome":{"final'
    '_component_wire_return":1,"component_wire_return_not_applicable":false,"kind":"wire","wi'
    're_anchor":"hand_anchor.expected_wire_utf8","wire_bytes":490,"wire_fingerprint":"recoryn'
    '-shape-v1:08ad04f16fc95966ba8c2c01a4c563500fab44faec263d2c7efdddd72d7c27d5"},"trace_orac'
    'le":[{"op":"route.call.enter","api":"recoryn.schema._component_shape_wire_read"},{"op":"'
    'cursor.create.enter","read":1,"cursor":"PRIVATE_WIRE_OK|private|r1"},{"op":"cursor.creat'
    'e.return","read":1,"cursor":"PRIVATE_WIRE_OK|private|r1","fresh_cursor":true},{"op":"row'
    '_factory.enter","read":1,"cursor":"PRIVATE_WIRE_OK|private|r1","value":null},{"op":"row_'
    'factory.return","read":1,"cursor":"PRIVATE_WIRE_OK|private|r1","value":null},{"op":"exec'
    'ute.enter","read":1,"cursor":"PRIVATE_WIRE_OK|private|r1","sql":"PRAGMA main.schema_vers'
    'ion"},{"op":"execute.return","read":1,"cursor":"PRIVATE_WIRE_OK|private|r1","value":"sam'
    'e_cursor"},{"op":"fetchall.enter","read":1,"cursor":"PRIVATE_WIRE_OK|private|r1"},{"op":'
    '"fetchall.return","read":1,"cursor":"PRIVATE_WIRE_OK|private|r1","rows":[[7]],"runtime_c'
    'ontainer":"list[tuple]"},{"op":"close.enter","read":1,"cursor":"PRIVATE_WIRE_OK|private|'
    'r1"},{"op":"close.return","read":1,"cursor":"PRIVATE_WIRE_OK|private|r1","value":null},{'
    '"op":"cursor.create.enter","read":2,"cursor":"PRIVATE_WIRE_OK|private|r2"},{"op":"cursor'
    '.create.return","read":2,"cursor":"PRIVATE_WIRE_OK|private|r2","fresh_cursor":true},{"op'
    '":"row_factory.enter","read":2,"cursor":"PRIVATE_WIRE_OK|private|r2","value":null},{"op"'
    ':"row_factory.return","read":2,"cursor":"PRIVATE_WIRE_OK|private|r2","value":null},{"op"'
    ':"execute.enter","read":2,"cursor":"PRIVATE_WIRE_OK|private|r2","sql":"SELECT type,name,'
    'tbl_name,sql FROM main.sqlite_schema"},{"op":"execute.return","read":2,"cursor":"PRIVATE'
    '_WIRE_OK|private|r2","value":"same_cursor"},{"op":"fetchall.enter","read":2,"cursor":"PR'
    'IVATE_WIRE_OK|private|r2"},{"op":"fetchall.return","read":2,"cursor":"PRIVATE_WIRE_OK|pr'
    'ivate|r2","rows":[["table","job_checkpoints","job_checkpoints","CREATE TABLE IF NOT EXIS'
    "TS job_checkpoints (job_id TEXT NOT NULL REFERENCES jobs(job_id), attempt_id TEXT NOT NU"
    'LL, result_ref TEXT NOT NULL, UNIQUE(job_id,result_ref));"],["index","sqlite_autoindex_j'
    'ob_checkpoints_1","job_checkpoints",null]],"runtime_container":"list[tuple]"},{"op":"clo'
    'se.enter","read":2,"cursor":"PRIVATE_WIRE_OK|private|r2"},{"op":"close.return","read":2,'
    '"cursor":"PRIVATE_WIRE_OK|private|r2","value":null},{"op":"cursor.create.enter","read":3'
    ',"cursor":"PRIVATE_WIRE_OK|private|r3"},{"op":"cursor.create.return","read":3,"cursor":"'
    'PRIVATE_WIRE_OK|private|r3","fresh_cursor":true},{"op":"row_factory.enter","read":3,"cur'
    'sor":"PRIVATE_WIRE_OK|private|r3","value":null},{"op":"row_factory.return","read":3,"cur'
    'sor":"PRIVATE_WIRE_OK|private|r3","value":null},{"op":"execute.enter","read":3,"cursor":'
    '"PRIVATE_WIRE_OK|private|r3","sql":"PRAGMA main.table_xinfo(\\"job_checkpoints\\")"},{"op"'
    ':"execute.return","read":3,"cursor":"PRIVATE_WIRE_OK|private|r3","value":"same_cursor"},'
    '{"op":"fetchall.enter","read":3,"cursor":"PRIVATE_WIRE_OK|private|r3"},{"op":"fetchall.r'
    'eturn","read":3,"cursor":"PRIVATE_WIRE_OK|private|r3","rows":[[0,"job_id","TEXT",1,null,'
    '0,0],[1,"attempt_id","TEXT",1,null,0,0],[2,"result_ref","TEXT",1,null,0,0]],"runtime_con'
    'tainer":"list[tuple]"},{"op":"close.enter","read":3,"cursor":"PRIVATE_WIRE_OK|private|r3'
    '"},{"op":"close.return","read":3,"cursor":"PRIVATE_WIRE_OK|private|r3","value":null},{"o'
    'p":"cursor.create.enter","read":4,"cursor":"PRIVATE_WIRE_OK|private|r4"},{"op":"cursor.c'
    'reate.return","read":4,"cursor":"PRIVATE_WIRE_OK|private|r4","fresh_cursor":true},{"op":'
    '"row_factory.enter","read":4,"cursor":"PRIVATE_WIRE_OK|private|r4","value":null},{"op":"'
    'row_factory.return","read":4,"cursor":"PRIVATE_WIRE_OK|private|r4","value":null},{"op":"'
    'execute.enter","read":4,"cursor":"PRIVATE_WIRE_OK|private|r4","sql":"PRAGMA main.foreign'
    '_key_list(\\"job_checkpoints\\")"},{"op":"execute.return","read":4,"cursor":"PRIVATE_WIRE_'
    'OK|private|r4","value":"same_cursor"},{"op":"fetchall.enter","read":4,"cursor":"PRIVATE_'
    'WIRE_OK|private|r4"},{"op":"fetchall.return","read":4,"cursor":"PRIVATE_WIRE_OK|private|'
    'r4","rows":[[0,0,"jobs","job_id","job_id","NO ACTION","NO ACTION","NONE"]],"runtime_cont'
    'ainer":"list[tuple]"},{"op":"close.enter","read":4,"cursor":"PRIVATE_WIRE_OK|private|r4"'
    '},{"op":"close.return","read":4,"cursor":"PRIVATE_WIRE_OK|private|r4","value":null},{"op'
    '":"cursor.create.enter","read":5,"cursor":"PRIVATE_WIRE_OK|private|r5"},{"op":"cursor.cr'
    'eate.return","read":5,"cursor":"PRIVATE_WIRE_OK|private|r5","fresh_cursor":true},{"op":"'
    'row_factory.enter","read":5,"cursor":"PRIVATE_WIRE_OK|private|r5","value":null},{"op":"r'
    'ow_factory.return","read":5,"cursor":"PRIVATE_WIRE_OK|private|r5","value":null},{"op":"e'
    'xecute.enter","read":5,"cursor":"PRIVATE_WIRE_OK|private|r5","sql":"PRAGMA main.index_li'
    'st(\\"job_checkpoints\\")"},{"op":"execute.return","read":5,"cursor":"PRIVATE_WIRE_OK|priv'
    'ate|r5","value":"same_cursor"},{"op":"fetchall.enter","read":5,"cursor":"PRIVATE_WIRE_OK'
    '|private|r5"},{"op":"fetchall.return","read":5,"cursor":"PRIVATE_WIRE_OK|private|r5","ro'
    'ws":[[0,"sqlite_autoindex_job_checkpoints_1",1,"u",0]],"runtime_container":"list[tuple]"'
    '},{"op":"close.enter","read":5,"cursor":"PRIVATE_WIRE_OK|private|r5"},{"op":"close.retur'
    'n","read":5,"cursor":"PRIVATE_WIRE_OK|private|r5","value":null},{"op":"cursor.create.ent'
    'er","read":6,"cursor":"PRIVATE_WIRE_OK|private|r6"},{"op":"cursor.create.return","read":'
    '6,"cursor":"PRIVATE_WIRE_OK|private|r6","fresh_cursor":true},{"op":"row_factory.enter","'
    'read":6,"cursor":"PRIVATE_WIRE_OK|private|r6","value":null},{"op":"row_factory.return","'
    'read":6,"cursor":"PRIVATE_WIRE_OK|private|r6","value":null},{"op":"execute.enter","read"'
    ':6,"cursor":"PRIVATE_WIRE_OK|private|r6","sql":"PRAGMA main.index_xinfo(\\"sqlite_autoind'
    'ex_job_checkpoints_1\\")"},{"op":"execute.return","read":6,"cursor":"PRIVATE_WIRE_OK|priv'
    'ate|r6","value":"same_cursor"},{"op":"fetchall.enter","read":6,"cursor":"PRIVATE_WIRE_OK'
    '|private|r6"},{"op":"fetchall.return","read":6,"cursor":"PRIVATE_WIRE_OK|private|r6","ro'
    'ws":[[0,0,"job_id",0,"BINARY",1],[1,2,"result_ref",0,"BINARY",1],[2,-1,null,0,"BINARY",0'
    ']],"runtime_container":"list[tuple]"},{"op":"close.enter","read":6,"cursor":"PRIVATE_WIR'
    'E_OK|private|r6"},{"op":"close.return","read":6,"cursor":"PRIVATE_WIRE_OK|private|r6","v'
    'alue":null},{"op":"cursor.create.enter","read":7,"cursor":"PRIVATE_WIRE_OK|private|r7"},'
    '{"op":"cursor.create.return","read":7,"cursor":"PRIVATE_WIRE_OK|private|r7","fresh_curso'
    'r":true},{"op":"row_factory.enter","read":7,"cursor":"PRIVATE_WIRE_OK|private|r7","value'
    '":null},{"op":"row_factory.return","read":7,"cursor":"PRIVATE_WIRE_OK|private|r7","value'
    '":null},{"op":"execute.enter","read":7,"cursor":"PRIVATE_WIRE_OK|private|r7","sql":"PRAG'
    'MA main.schema_version"},{"op":"execute.return","read":7,"cursor":"PRIVATE_WIRE_OK|priva'
    'te|r7","value":"same_cursor"},{"op":"fetchall.enter","read":7,"cursor":"PRIVATE_WIRE_OK|'
    'private|r7"},{"op":"fetchall.return","read":7,"cursor":"PRIVATE_WIRE_OK|private|r7","row'
    's":[[7]],"runtime_container":"list[tuple]"},{"op":"close.enter","read":7,"cursor":"PRIVA'
    'TE_WIRE_OK|private|r7"},{"op":"close.return","read":7,"cursor":"PRIVATE_WIRE_OK|private|'
    'r7","value":null},{"op":"route.return","kind":"wire","bytes":490,"fingerprint":"recoryn-'
    'shape-v1:08ad04f16fc95966ba8c2c01a4c563500fab44faec263d2c7efdddd72d7c27d5"}],"trace_coun'
    'ts":{"cursor.create.enter":7,"cursor.create.return":7,"row_factory.enter":7,"row_factory'
    '.return":7,"execute.enter":7,"execute.return":7,"fetchall.enter":7,"fetchall.return":7,"'
    'close.enter":7,"close.return":7,"close.raise":0},"internal_canonical_wire_call_count_not'
    '_constrained":true,"native_cleanup_proved":false},{"route_id":"PRIVATE_WIRE_OK|public","'
    'route":"public","api_name_future_private_unimplemented":"recoryn.schema.component_shape_'
    'wire","fake_identity":"PRIVATE_WIRE_OK|public|connection","fresh_all_objects":true,"prep'
    'are_hash_or_raise":false,"expected_model":"actual_public_expected_lookup_not_stubbed","c'
    'omponent_input":"jobs.checkpoints","program":[{"read":1,"cursor":"r1","sql":"PRAGMA main'
    '.schema_version","rows":[[7]]},{"read":2,"cursor":"r2","sql":"SELECT type,name,tbl_name,'
    'sql FROM main.sqlite_schema","rows":[["table","job_checkpoints","job_checkpoints","CREAT'
    "E TABLE IF NOT EXISTS job_checkpoints (job_id TEXT NOT NULL REFERENCES jobs(job_id), att"
    'empt_id TEXT NOT NULL, result_ref TEXT NOT NULL, UNIQUE(job_id,result_ref));"],["index",'
    '"sqlite_autoindex_job_checkpoints_1","job_checkpoints",null]]},{"read":3,"cursor":"r3","'
    'sql":"PRAGMA main.table_xinfo(\\"job_checkpoints\\")","rows":[[0,"job_id","TEXT",1,null,0,'
    '0],[1,"attempt_id","TEXT",1,null,0,0],[2,"result_ref","TEXT",1,null,0,0]]},{"read":4,"cu'
    'rsor":"r4","sql":"PRAGMA main.foreign_key_list(\\"job_checkpoints\\")","rows":[[0,0,"jobs"'
    ',"job_id","job_id","NO ACTION","NO ACTION","NONE"]]},{"read":5,"cursor":"r5","sql":"PRAG'
    'MA main.index_list(\\"job_checkpoints\\")","rows":[[0,"sqlite_autoindex_job_checkpoints_1"'
    ',1,"u",0]]},{"read":6,"cursor":"r6","sql":"PRAGMA main.index_xinfo(\\"sqlite_autoindex_jo'
    'b_checkpoints_1\\")","rows":[[0,0,"job_id",0,"BINARY",1],[1,2,"result_ref",0,"BINARY",1],'
    '[2,-1,null,0,"BINARY",0]]},{"read":7,"cursor":"r7","sql":"PRAGMA main.schema_version","r'
    'ows":[[7]]}],"fault":null,"close_fault":null,"exception_objects_spec_only":{},"outcome":'
    '{"final_component_wire_return":1,"component_wire_return_not_applicable":false,"kind":"wi'
    're","wire_anchor":"hand_anchor.expected_wire_utf8","wire_bytes":490,"wire_fingerprint":"'
    'recoryn-shape-v1:08ad04f16fc95966ba8c2c01a4c563500fab44faec263d2c7efdddd72d7c27d5"},"tra'
    'ce_oracle":[{"op":"route.call.enter","api":"recoryn.schema.component_shape_wire"},{"op":'
    '"cursor.create.enter","read":1,"cursor":"PRIVATE_WIRE_OK|public|r1"},{"op":"cursor.creat'
    'e.return","read":1,"cursor":"PRIVATE_WIRE_OK|public|r1","fresh_cursor":true},{"op":"row_'
    'factory.enter","read":1,"cursor":"PRIVATE_WIRE_OK|public|r1","value":null},{"op":"row_fa'
    'ctory.return","read":1,"cursor":"PRIVATE_WIRE_OK|public|r1","value":null},{"op":"execute'
    '.enter","read":1,"cursor":"PRIVATE_WIRE_OK|public|r1","sql":"PRAGMA main.schema_version"'
    '},{"op":"execute.return","read":1,"cursor":"PRIVATE_WIRE_OK|public|r1","value":"same_cur'
    'sor"},{"op":"fetchall.enter","read":1,"cursor":"PRIVATE_WIRE_OK|public|r1"},{"op":"fetch'
    'all.return","read":1,"cursor":"PRIVATE_WIRE_OK|public|r1","rows":[[7]],"runtime_containe'
    'r":"list[tuple]"},{"op":"close.enter","read":1,"cursor":"PRIVATE_WIRE_OK|public|r1"},{"o'
    'p":"close.return","read":1,"cursor":"PRIVATE_WIRE_OK|public|r1","value":null},{"op":"cur'
    'sor.create.enter","read":2,"cursor":"PRIVATE_WIRE_OK|public|r2"},{"op":"cursor.create.re'
    'turn","read":2,"cursor":"PRIVATE_WIRE_OK|public|r2","fresh_cursor":true},{"op":"row_fact'
    'ory.enter","read":2,"cursor":"PRIVATE_WIRE_OK|public|r2","value":null},{"op":"row_factor'
    'y.return","read":2,"cursor":"PRIVATE_WIRE_OK|public|r2","value":null},{"op":"execute.ent'
    'er","read":2,"cursor":"PRIVATE_WIRE_OK|public|r2","sql":"SELECT type,name,tbl_name,sql F'
    'ROM main.sqlite_schema"},{"op":"execute.return","read":2,"cursor":"PRIVATE_WIRE_OK|publi'
    'c|r2","value":"same_cursor"},{"op":"fetchall.enter","read":2,"cursor":"PRIVATE_WIRE_OK|p'
    'ublic|r2"},{"op":"fetchall.return","read":2,"cursor":"PRIVATE_WIRE_OK|public|r2","rows":'
    '[["table","job_checkpoints","job_checkpoints","CREATE TABLE IF NOT EXISTS job_checkpoint'
    "s (job_id TEXT NOT NULL REFERENCES jobs(job_id), attempt_id TEXT NOT NULL, result_ref TE"
    'XT NOT NULL, UNIQUE(job_id,result_ref));"],["index","sqlite_autoindex_job_checkpoints_1"'
    ',"job_checkpoints",null]],"runtime_container":"list[tuple]"},{"op":"close.enter","read":'
    '2,"cursor":"PRIVATE_WIRE_OK|public|r2"},{"op":"close.return","read":2,"cursor":"PRIVATE_'
    'WIRE_OK|public|r2","value":null},{"op":"cursor.create.enter","read":3,"cursor":"PRIVATE_'
    'WIRE_OK|public|r3"},{"op":"cursor.create.return","read":3,"cursor":"PRIVATE_WIRE_OK|publ'
    'ic|r3","fresh_cursor":true},{"op":"row_factory.enter","read":3,"cursor":"PRIVATE_WIRE_OK'
    '|public|r3","value":null},{"op":"row_factory.return","read":3,"cursor":"PRIVATE_WIRE_OK|'
    'public|r3","value":null},{"op":"execute.enter","read":3,"cursor":"PRIVATE_WIRE_OK|public'
    '|r3","sql":"PRAGMA main.table_xinfo(\\"job_checkpoints\\")"},{"op":"execute.return","read"'
    ':3,"cursor":"PRIVATE_WIRE_OK|public|r3","value":"same_cursor"},{"op":"fetchall.enter","r'
    'ead":3,"cursor":"PRIVATE_WIRE_OK|public|r3"},{"op":"fetchall.return","read":3,"cursor":"'
    'PRIVATE_WIRE_OK|public|r3","rows":[[0,"job_id","TEXT",1,null,0,0],[1,"attempt_id","TEXT"'
    ',1,null,0,0],[2,"result_ref","TEXT",1,null,0,0]],"runtime_container":"list[tuple]"},{"op'
    '":"close.enter","read":3,"cursor":"PRIVATE_WIRE_OK|public|r3"},{"op":"close.return","rea'
    'd":3,"cursor":"PRIVATE_WIRE_OK|public|r3","value":null},{"op":"cursor.create.enter","rea'
    'd":4,"cursor":"PRIVATE_WIRE_OK|public|r4"},{"op":"cursor.create.return","read":4,"cursor'
    '":"PRIVATE_WIRE_OK|public|r4","fresh_cursor":true},{"op":"row_factory.enter","read":4,"c'
    'ursor":"PRIVATE_WIRE_OK|public|r4","value":null},{"op":"row_factory.return","read":4,"cu'
    'rsor":"PRIVATE_WIRE_OK|public|r4","value":null},{"op":"execute.enter","read":4,"cursor":'
    '"PRIVATE_WIRE_OK|public|r4","sql":"PRAGMA main.foreign_key_list(\\"job_checkpoints\\")"},{'
    '"op":"execute.return","read":4,"cursor":"PRIVATE_WIRE_OK|public|r4","value":"same_cursor'
    '"},{"op":"fetchall.enter","read":4,"cursor":"PRIVATE_WIRE_OK|public|r4"},{"op":"fetchall'
    '.return","read":4,"cursor":"PRIVATE_WIRE_OK|public|r4","rows":[[0,0,"jobs","job_id","job'
    '_id","NO ACTION","NO ACTION","NONE"]],"runtime_container":"list[tuple]"},{"op":"close.en'
    'ter","read":4,"cursor":"PRIVATE_WIRE_OK|public|r4"},{"op":"close.return","read":4,"curso'
    'r":"PRIVATE_WIRE_OK|public|r4","value":null},{"op":"cursor.create.enter","read":5,"curso'
    'r":"PRIVATE_WIRE_OK|public|r5"},{"op":"cursor.create.return","read":5,"cursor":"PRIVATE_'
    'WIRE_OK|public|r5","fresh_cursor":true},{"op":"row_factory.enter","read":5,"cursor":"PRI'
    'VATE_WIRE_OK|public|r5","value":null},{"op":"row_factory.return","read":5,"cursor":"PRIV'
    'ATE_WIRE_OK|public|r5","value":null},{"op":"execute.enter","read":5,"cursor":"PRIVATE_WI'
    'RE_OK|public|r5","sql":"PRAGMA main.index_list(\\"job_checkpoints\\")"},{"op":"execute.ret'
    'urn","read":5,"cursor":"PRIVATE_WIRE_OK|public|r5","value":"same_cursor"},{"op":"fetchal'
    'l.enter","read":5,"cursor":"PRIVATE_WIRE_OK|public|r5"},{"op":"fetchall.return","read":5'
    ',"cursor":"PRIVATE_WIRE_OK|public|r5","rows":[[0,"sqlite_autoindex_job_checkpoints_1",1,'
    '"u",0]],"runtime_container":"list[tuple]"},{"op":"close.enter","read":5,"cursor":"PRIVAT'
    'E_WIRE_OK|public|r5"},{"op":"close.return","read":5,"cursor":"PRIVATE_WIRE_OK|public|r5"'
    ',"value":null},{"op":"cursor.create.enter","read":6,"cursor":"PRIVATE_WIRE_OK|public|r6"'
    '},{"op":"cursor.create.return","read":6,"cursor":"PRIVATE_WIRE_OK|public|r6","fresh_curs'
    'or":true},{"op":"row_factory.enter","read":6,"cursor":"PRIVATE_WIRE_OK|public|r6","value'
    '":null},{"op":"row_factory.return","read":6,"cursor":"PRIVATE_WIRE_OK|public|r6","value"'
    ':null},{"op":"execute.enter","read":6,"cursor":"PRIVATE_WIRE_OK|public|r6","sql":"PRAGMA'
    ' main.index_xinfo(\\"sqlite_autoindex_job_checkpoints_1\\")"},{"op":"execute.return","read'
    '":6,"cursor":"PRIVATE_WIRE_OK|public|r6","value":"same_cursor"},{"op":"fetchall.enter","'
    'read":6,"cursor":"PRIVATE_WIRE_OK|public|r6"},{"op":"fetchall.return","read":6,"cursor":'
    '"PRIVATE_WIRE_OK|public|r6","rows":[[0,0,"job_id",0,"BINARY",1],[1,2,"result_ref",0,"BIN'
    'ARY",1],[2,-1,null,0,"BINARY",0]],"runtime_container":"list[tuple]"},{"op":"close.enter"'
    ',"read":6,"cursor":"PRIVATE_WIRE_OK|public|r6"},{"op":"close.return","read":6,"cursor":"'
    'PRIVATE_WIRE_OK|public|r6","value":null},{"op":"cursor.create.enter","read":7,"cursor":"'
    'PRIVATE_WIRE_OK|public|r7"},{"op":"cursor.create.return","read":7,"cursor":"PRIVATE_WIRE'
    '_OK|public|r7","fresh_cursor":true},{"op":"row_factory.enter","read":7,"cursor":"PRIVATE'
    '_WIRE_OK|public|r7","value":null},{"op":"row_factory.return","read":7,"cursor":"PRIVATE_'
    'WIRE_OK|public|r7","value":null},{"op":"execute.enter","read":7,"cursor":"PRIVATE_WIRE_O'
    'K|public|r7","sql":"PRAGMA main.schema_version"},{"op":"execute.return","read":7,"cursor'
    '":"PRIVATE_WIRE_OK|public|r7","value":"same_cursor"},{"op":"fetchall.enter","read":7,"cu'
    'rsor":"PRIVATE_WIRE_OK|public|r7"},{"op":"fetchall.return","read":7,"cursor":"PRIVATE_WI'
    'RE_OK|public|r7","rows":[[7]],"runtime_container":"list[tuple]"},{"op":"close.enter","re'
    'ad":7,"cursor":"PRIVATE_WIRE_OK|public|r7"},{"op":"close.return","read":7,"cursor":"PRIV'
    'ATE_WIRE_OK|public|r7","value":null},{"op":"route.return","kind":"wire","bytes":490,"fin'
    'gerprint":"recoryn-shape-v1:08ad04f16fc95966ba8c2c01a4c563500fab44faec263d2c7efdddd72d7c'
    '27d5"}],"trace_counts":{"cursor.create.enter":7,"cursor.create.return":7,"row_factory.en'
    'ter":7,"row_factory.return":7,"execute.enter":7,"execute.return":7,"fetchall.enter":7,"f'
    'etchall.return":7,"close.enter":7,"close.return":7,"close.raise":0},"internal_canonical_'
    'wire_call_count_not_constrained":true,"native_cleanup_proved":false},{"route_id":"LAST_S'
    'TAMP_ERROR|private","route":"private","api_name_future_private_unimplemented":"recoryn.s'
    'chema._component_shape_wire_read","fake_identity":"LAST_STAMP_ERROR|private|connection",'
    '"fresh_all_objects":true,"prepare_hash_or_raise":false,"expected_model":"fresh_deep_copy'
    '_of_hand_anchor.model","component_input":"jobs.checkpoints","program":[{"read":1,"cursor'
    '":"r1","sql":"PRAGMA main.schema_version","rows":[[7]]},{"read":2,"cursor":"r2","sql":"S'
    'ELECT type,name,tbl_name,sql FROM main.sqlite_schema","rows":[["table","job_checkpoints"'
    ',"job_checkpoints","CREATE TABLE IF NOT EXISTS job_checkpoints (job_id TEXT NOT NULL REF'
    "ERENCES jobs(job_id), attempt_id TEXT NOT NULL, result_ref TEXT NOT NULL, UNIQUE(job_id,"
    'result_ref));"],["index","sqlite_autoindex_job_checkpoints_1","job_checkpoints",null]]},'
    '{"read":3,"cursor":"r3","sql":"PRAGMA main.table_xinfo(\\"job_checkpoints\\")","rows":[[0,'
    '"job_id","TEXT",1,null,0,0],[1,"attempt_id","TEXT",1,null,0,0],[2,"result_ref","TEXT",1,'
    'null,0,0]]},{"read":4,"cursor":"r4","sql":"PRAGMA main.foreign_key_list(\\"job_checkpoint'
    's\\")","rows":[[0,0,"jobs","job_id","job_id","NO ACTION","NO ACTION","NONE"]]},{"read":5,'
    '"cursor":"r5","sql":"PRAGMA main.index_list(\\"job_checkpoints\\")","rows":[[0,"sqlite_aut'
    'oindex_job_checkpoints_1",1,"u",0]]},{"read":6,"cursor":"r6","sql":"PRAGMA main.index_xi'
    'nfo(\\"sqlite_autoindex_job_checkpoints_1\\")","rows":[[0,0,"job_id",0,"BINARY",1],[1,2,"r'
    'esult_ref",0,"BINARY",1],[2,-1,null,0,"BINARY",0]]},{"read":7,"cursor":"r7","sql":"PRAGM'
    'A main.schema_version","rows":[[7]]}],"fault":{"read":7,"stage":"fetchall","raise":"E"},'
    '"close_fault":null,"exception_objects_spec_only":{"E":{"identity":"LAST_STAMP_ERROR|priv'
    'ate|E","exact_class":"sqlite3.OperationalError","args":["LAST_STAMP_ERROR_MARKER"],"str"'
    ':"LAST_STAMP_ERROR_MARKER","repr":"OperationalError(\'LAST_STAMP_ERROR_MARKER\')","__cause'
    '__":null,"__context__":null,"__suppress_context__":false,"role":"fresh_injected_error","'
    'context_fields_are_post_call_oracle_not_fixture_assignment":true,"construction_initial_s'
    'tate":{"__cause__":null,"__context__":null,"__suppress_context__":false},"fixture_must_n'
    'ot_seed_context":true}},"outcome":{"final_component_wire_return":0,"component_wire_retur'
    'n_not_applicable":false,"kind":"exception","error":{"identity":"LAST_STAMP_ERROR|private'
    '|E","exact_class":"sqlite3.OperationalError","args":["LAST_STAMP_ERROR_MARKER"],"str":"L'
    'AST_STAMP_ERROR_MARKER","repr":"OperationalError(\'LAST_STAMP_ERROR_MARKER\')","__cause__"'
    ':null,"__context__":null,"__suppress_context__":false},"identity_assertion_required":tru'
    'e,"capture_product_created_error_only":false},"trace_oracle":[{"op":"route.call.enter","'
    'api":"recoryn.schema._component_shape_wire_read"},{"op":"cursor.create.enter","read":1,"'
    'cursor":"LAST_STAMP_ERROR|private|r1"},{"op":"cursor.create.return","read":1,"cursor":"L'
    'AST_STAMP_ERROR|private|r1","fresh_cursor":true},{"op":"row_factory.enter","read":1,"cur'
    'sor":"LAST_STAMP_ERROR|private|r1","value":null},{"op":"row_factory.return","read":1,"cu'
    'rsor":"LAST_STAMP_ERROR|private|r1","value":null},{"op":"execute.enter","read":1,"cursor'
    '":"LAST_STAMP_ERROR|private|r1","sql":"PRAGMA main.schema_version"},{"op":"execute.retur'
    'n","read":1,"cursor":"LAST_STAMP_ERROR|private|r1","value":"same_cursor"},{"op":"fetchal'
    'l.enter","read":1,"cursor":"LAST_STAMP_ERROR|private|r1"},{"op":"fetchall.return","read"'
    ':1,"cursor":"LAST_STAMP_ERROR|private|r1","rows":[[7]],"runtime_container":"list[tuple]"'
    '},{"op":"close.enter","read":1,"cursor":"LAST_STAMP_ERROR|private|r1"},{"op":"close.retu'
    'rn","read":1,"cursor":"LAST_STAMP_ERROR|private|r1","value":null},{"op":"cursor.create.e'
    'nter","read":2,"cursor":"LAST_STAMP_ERROR|private|r2"},{"op":"cursor.create.return","rea'
    'd":2,"cursor":"LAST_STAMP_ERROR|private|r2","fresh_cursor":true},{"op":"row_factory.ente'
    'r","read":2,"cursor":"LAST_STAMP_ERROR|private|r2","value":null},{"op":"row_factory.retu'
    'rn","read":2,"cursor":"LAST_STAMP_ERROR|private|r2","value":null},{"op":"execute.enter",'
    '"read":2,"cursor":"LAST_STAMP_ERROR|private|r2","sql":"SELECT type,name,tbl_name,sql FRO'
    'M main.sqlite_schema"},{"op":"execute.return","read":2,"cursor":"LAST_STAMP_ERROR|privat'
    'e|r2","value":"same_cursor"},{"op":"fetchall.enter","read":2,"cursor":"LAST_STAMP_ERROR|'
    'private|r2"},{"op":"fetchall.return","read":2,"cursor":"LAST_STAMP_ERROR|private|r2","ro'
    'ws":[["table","job_checkpoints","job_checkpoints","CREATE TABLE IF NOT EXISTS job_checkp'
    "oints (job_id TEXT NOT NULL REFERENCES jobs(job_id), attempt_id TEXT NOT NULL, result_re"
    'f TEXT NOT NULL, UNIQUE(job_id,result_ref));"],["index","sqlite_autoindex_job_checkpoint'
    's_1","job_checkpoints",null]],"runtime_container":"list[tuple]"},{"op":"close.enter","re'
    'ad":2,"cursor":"LAST_STAMP_ERROR|private|r2"},{"op":"close.return","read":2,"cursor":"LA'
    'ST_STAMP_ERROR|private|r2","value":null},{"op":"cursor.create.enter","read":3,"cursor":"'
    'LAST_STAMP_ERROR|private|r3"},{"op":"cursor.create.return","read":3,"cursor":"LAST_STAMP'
    '_ERROR|private|r3","fresh_cursor":true},{"op":"row_factory.enter","read":3,"cursor":"LAS'
    'T_STAMP_ERROR|private|r3","value":null},{"op":"row_factory.return","read":3,"cursor":"LA'
    'ST_STAMP_ERROR|private|r3","value":null},{"op":"execute.enter","read":3,"cursor":"LAST_S'
    'TAMP_ERROR|private|r3","sql":"PRAGMA main.table_xinfo(\\"job_checkpoints\\")"},{"op":"exec'
    'ute.return","read":3,"cursor":"LAST_STAMP_ERROR|private|r3","value":"same_cursor"},{"op"'
    ':"fetchall.enter","read":3,"cursor":"LAST_STAMP_ERROR|private|r3"},{"op":"fetchall.retur'
    'n","read":3,"cursor":"LAST_STAMP_ERROR|private|r3","rows":[[0,"job_id","TEXT",1,null,0,0'
    '],[1,"attempt_id","TEXT",1,null,0,0],[2,"result_ref","TEXT",1,null,0,0]],"runtime_contai'
    'ner":"list[tuple]"},{"op":"close.enter","read":3,"cursor":"LAST_STAMP_ERROR|private|r3"}'
    ',{"op":"close.return","read":3,"cursor":"LAST_STAMP_ERROR|private|r3","value":null},{"op'
    '":"cursor.create.enter","read":4,"cursor":"LAST_STAMP_ERROR|private|r4"},{"op":"cursor.c'
    'reate.return","read":4,"cursor":"LAST_STAMP_ERROR|private|r4","fresh_cursor":true},{"op"'
    ':"row_factory.enter","read":4,"cursor":"LAST_STAMP_ERROR|private|r4","value":null},{"op"'
    ':"row_factory.return","read":4,"cursor":"LAST_STAMP_ERROR|private|r4","value":null},{"op'
    '":"execute.enter","read":4,"cursor":"LAST_STAMP_ERROR|private|r4","sql":"PRAGMA main.for'
    'eign_key_list(\\"job_checkpoints\\")"},{"op":"execute.return","read":4,"cursor":"LAST_STAM'
    'P_ERROR|private|r4","value":"same_cursor"},{"op":"fetchall.enter","read":4,"cursor":"LAS'
    'T_STAMP_ERROR|private|r4"},{"op":"fetchall.return","read":4,"cursor":"LAST_STAMP_ERROR|p'
    'rivate|r4","rows":[[0,0,"jobs","job_id","job_id","NO ACTION","NO ACTION","NONE"]],"runti'
    'me_container":"list[tuple]"},{"op":"close.enter","read":4,"cursor":"LAST_STAMP_ERROR|pri'
    'vate|r4"},{"op":"close.return","read":4,"cursor":"LAST_STAMP_ERROR|private|r4","value":n'
    'ull},{"op":"cursor.create.enter","read":5,"cursor":"LAST_STAMP_ERROR|private|r5"},{"op":'
    '"cursor.create.return","read":5,"cursor":"LAST_STAMP_ERROR|private|r5","fresh_cursor":tr'
    'ue},{"op":"row_factory.enter","read":5,"cursor":"LAST_STAMP_ERROR|private|r5","value":nu'
    'll},{"op":"row_factory.return","read":5,"cursor":"LAST_STAMP_ERROR|private|r5","value":n'
    'ull},{"op":"execute.enter","read":5,"cursor":"LAST_STAMP_ERROR|private|r5","sql":"PRAGMA'
    ' main.index_list(\\"job_checkpoints\\")"},{"op":"execute.return","read":5,"cursor":"LAST_S'
    'TAMP_ERROR|private|r5","value":"same_cursor"},{"op":"fetchall.enter","read":5,"cursor":"'
    'LAST_STAMP_ERROR|private|r5"},{"op":"fetchall.return","read":5,"cursor":"LAST_STAMP_ERRO'
    'R|private|r5","rows":[[0,"sqlite_autoindex_job_checkpoints_1",1,"u",0]],"runtime_contain'
    'er":"list[tuple]"},{"op":"close.enter","read":5,"cursor":"LAST_STAMP_ERROR|private|r5"},'
    '{"op":"close.return","read":5,"cursor":"LAST_STAMP_ERROR|private|r5","value":null},{"op"'
    ':"cursor.create.enter","read":6,"cursor":"LAST_STAMP_ERROR|private|r6"},{"op":"cursor.cr'
    'eate.return","read":6,"cursor":"LAST_STAMP_ERROR|private|r6","fresh_cursor":true},{"op":'
    '"row_factory.enter","read":6,"cursor":"LAST_STAMP_ERROR|private|r6","value":null},{"op":'
    '"row_factory.return","read":6,"cursor":"LAST_STAMP_ERROR|private|r6","value":null},{"op"'
    ':"execute.enter","read":6,"cursor":"LAST_STAMP_ERROR|private|r6","sql":"PRAGMA main.inde'
    'x_xinfo(\\"sqlite_autoindex_job_checkpoints_1\\")"},{"op":"execute.return","read":6,"curso'
    'r":"LAST_STAMP_ERROR|private|r6","value":"same_cursor"},{"op":"fetchall.enter","read":6,'
    '"cursor":"LAST_STAMP_ERROR|private|r6"},{"op":"fetchall.return","read":6,"cursor":"LAST_'
    'STAMP_ERROR|private|r6","rows":[[0,0,"job_id",0,"BINARY",1],[1,2,"result_ref",0,"BINARY"'
    ',1],[2,-1,null,0,"BINARY",0]],"runtime_container":"list[tuple]"},{"op":"close.enter","re'
    'ad":6,"cursor":"LAST_STAMP_ERROR|private|r6"},{"op":"close.return","read":6,"cursor":"LA'
    'ST_STAMP_ERROR|private|r6","value":null},{"op":"cursor.create.enter","read":7,"cursor":"'
    'LAST_STAMP_ERROR|private|r7"},{"op":"cursor.create.return","read":7,"cursor":"LAST_STAMP'
    '_ERROR|private|r7","fresh_cursor":true},{"op":"row_factory.enter","read":7,"cursor":"LAS'
    'T_STAMP_ERROR|private|r7","value":null},{"op":"row_factory.return","read":7,"cursor":"LA'
    'ST_STAMP_ERROR|private|r7","value":null},{"op":"execute.enter","read":7,"cursor":"LAST_S'
    'TAMP_ERROR|private|r7","sql":"PRAGMA main.schema_version"},{"op":"execute.return","read"'
    ':7,"cursor":"LAST_STAMP_ERROR|private|r7","value":"same_cursor"},{"op":"fetchall.enter",'
    '"read":7,"cursor":"LAST_STAMP_ERROR|private|r7"},{"op":"fetchall.raise","read":7,"cursor'
    '":"LAST_STAMP_ERROR|private|r7","identity":"LAST_STAMP_ERROR|private|E"},{"op":"close.en'
    'ter","read":7,"cursor":"LAST_STAMP_ERROR|private|r7"},{"op":"close.return","read":7,"cur'
    'sor":"LAST_STAMP_ERROR|private|r7","value":null},{"op":"route.raise","identity":"LAST_ST'
    'AMP_ERROR|private|E","exact_class":"sqlite3.OperationalError"}],"trace_counts":{"cursor.'
    'create.enter":7,"cursor.create.return":7,"row_factory.enter":7,"row_factory.return":7,"e'
    'xecute.enter":7,"execute.return":7,"fetchall.enter":7,"fetchall.return":6,"close.enter":'
    '7,"close.return":7,"close.raise":0},"internal_canonical_wire_call_count_not_constrained"'
    ':true,"native_cleanup_proved":false},{"route_id":"LAST_STAMP_ERROR|public","route":"publ'
    'ic","api_name_future_private_unimplemented":"recoryn.schema.component_shape_wire","fake_'
    'identity":"LAST_STAMP_ERROR|public|connection","fresh_all_objects":true,"prepare_hash_or'
    '_raise":false,"expected_model":"actual_public_expected_lookup_not_stubbed","component_in'
    'put":"jobs.checkpoints","program":[{"read":1,"cursor":"r1","sql":"PRAGMA main.schema_ver'
    'sion","rows":[[7]]},{"read":2,"cursor":"r2","sql":"SELECT type,name,tbl_name,sql FROM ma'
    'in.sqlite_schema","rows":[["table","job_checkpoints","job_checkpoints","CREATE TABLE IF '
    "NOT EXISTS job_checkpoints (job_id TEXT NOT NULL REFERENCES jobs(job_id), attempt_id TEX"
    'T NOT NULL, result_ref TEXT NOT NULL, UNIQUE(job_id,result_ref));"],["index","sqlite_aut'
    'oindex_job_checkpoints_1","job_checkpoints",null]]},{"read":3,"cursor":"r3","sql":"PRAGM'
    'A main.table_xinfo(\\"job_checkpoints\\")","rows":[[0,"job_id","TEXT",1,null,0,0],[1,"atte'
    'mpt_id","TEXT",1,null,0,0],[2,"result_ref","TEXT",1,null,0,0]]},{"read":4,"cursor":"r4",'
    '"sql":"PRAGMA main.foreign_key_list(\\"job_checkpoints\\")","rows":[[0,0,"jobs","job_id","'
    'job_id","NO ACTION","NO ACTION","NONE"]]},{"read":5,"cursor":"r5","sql":"PRAGMA main.ind'
    'ex_list(\\"job_checkpoints\\")","rows":[[0,"sqlite_autoindex_job_checkpoints_1",1,"u",0]]}'
    ',{"read":6,"cursor":"r6","sql":"PRAGMA main.index_xinfo(\\"sqlite_autoindex_job_checkpoin'
    'ts_1\\")","rows":[[0,0,"job_id",0,"BINARY",1],[1,2,"result_ref",0,"BINARY",1],[2,-1,null,'
    '0,"BINARY",0]]},{"read":7,"cursor":"r7","sql":"PRAGMA main.schema_version","rows":[[7]]}'
    '],"fault":{"read":7,"stage":"fetchall","raise":"E"},"close_fault":null,"exception_object'
    's_spec_only":{"E":{"identity":"LAST_STAMP_ERROR|public|E","exact_class":"sqlite3.Operati'
    'onalError","args":["LAST_STAMP_ERROR_MARKER"],"str":"LAST_STAMP_ERROR_MARKER","repr":"Op'
    'erationalError(\'LAST_STAMP_ERROR_MARKER\')","__cause__":null,"__context__":null,"__suppre'
    'ss_context__":false,"role":"fresh_injected_error","context_fields_are_post_call_oracle_n'
    'ot_fixture_assignment":true,"construction_initial_state":{"__cause__":null,"__context__"'
    ':null,"__suppress_context__":false},"fixture_must_not_seed_context":true},"PUBLIC_CLOSED'
    '":{"identity":"LAST_STAMP_ERROR|public|PUBLIC_CLOSED","exact_class":"builtins.ValueError'
    '","args":["Unsupported component shape"],"str":"Unsupported component shape","repr":"Val'
    'ueError(\'Unsupported component shape\')","__cause__":null,"__context__":"LAST_STAMP_ERROR'
    '|public|E","__suppress_context__":true,"role":"captured_product_created_error","context_'
    'fields_are_post_call_oracle_not_fixture_assignment":true,"fixture_must_not_precreate":tr'
    'ue}},"outcome":{"final_component_wire_return":0,"component_wire_return_not_applicable":f'
    'alse,"kind":"exception","error":{"identity":"LAST_STAMP_ERROR|public|PUBLIC_CLOSED","exa'
    'ct_class":"builtins.ValueError","args":["Unsupported component shape"],"str":"Unsupporte'
    'd component shape","repr":"ValueError(\'Unsupported component shape\')","__cause__":null,"'
    '__context__":"LAST_STAMP_ERROR|public|E","__suppress_context__":true},"identity_assertio'
    'n_required":false,"capture_product_created_error_only":true},"trace_oracle":[{"op":"rout'
    'e.call.enter","api":"recoryn.schema.component_shape_wire"},{"op":"cursor.create.enter","'
    'read":1,"cursor":"LAST_STAMP_ERROR|public|r1"},{"op":"cursor.create.return","read":1,"cu'
    'rsor":"LAST_STAMP_ERROR|public|r1","fresh_cursor":true},{"op":"row_factory.enter","read"'
    ':1,"cursor":"LAST_STAMP_ERROR|public|r1","value":null},{"op":"row_factory.return","read"'
    ':1,"cursor":"LAST_STAMP_ERROR|public|r1","value":null},{"op":"execute.enter","read":1,"c'
    'ursor":"LAST_STAMP_ERROR|public|r1","sql":"PRAGMA main.schema_version"},{"op":"execute.r'
    'eturn","read":1,"cursor":"LAST_STAMP_ERROR|public|r1","value":"same_cursor"},{"op":"fetc'
    'hall.enter","read":1,"cursor":"LAST_STAMP_ERROR|public|r1"},{"op":"fetchall.return","rea'
    'd":1,"cursor":"LAST_STAMP_ERROR|public|r1","rows":[[7]],"runtime_container":"list[tuple]'
    '"},{"op":"close.enter","read":1,"cursor":"LAST_STAMP_ERROR|public|r1"},{"op":"close.retu'
    'rn","read":1,"cursor":"LAST_STAMP_ERROR|public|r1","value":null},{"op":"cursor.create.en'
    'ter","read":2,"cursor":"LAST_STAMP_ERROR|public|r2"},{"op":"cursor.create.return","read"'
    ':2,"cursor":"LAST_STAMP_ERROR|public|r2","fresh_cursor":true},{"op":"row_factory.enter",'
    '"read":2,"cursor":"LAST_STAMP_ERROR|public|r2","value":null},{"op":"row_factory.return",'
    '"read":2,"cursor":"LAST_STAMP_ERROR|public|r2","value":null},{"op":"execute.enter","read'
    '":2,"cursor":"LAST_STAMP_ERROR|public|r2","sql":"SELECT type,name,tbl_name,sql FROM main'
    '.sqlite_schema"},{"op":"execute.return","read":2,"cursor":"LAST_STAMP_ERROR|public|r2","'
    'value":"same_cursor"},{"op":"fetchall.enter","read":2,"cursor":"LAST_STAMP_ERROR|public|'
    'r2"},{"op":"fetchall.return","read":2,"cursor":"LAST_STAMP_ERROR|public|r2","rows":[["ta'
    'ble","job_checkpoints","job_checkpoints","CREATE TABLE IF NOT EXISTS job_checkpoints (jo'
    "b_id TEXT NOT NULL REFERENCES jobs(job_id), attempt_id TEXT NOT NULL, result_ref TEXT NO"
    'T NULL, UNIQUE(job_id,result_ref));"],["index","sqlite_autoindex_job_checkpoints_1","job'
    '_checkpoints",null]],"runtime_container":"list[tuple]"},{"op":"close.enter","read":2,"cu'
    'rsor":"LAST_STAMP_ERROR|public|r2"},{"op":"close.return","read":2,"cursor":"LAST_STAMP_E'
    'RROR|public|r2","value":null},{"op":"cursor.create.enter","read":3,"cursor":"LAST_STAMP_'
    'ERROR|public|r3"},{"op":"cursor.create.return","read":3,"cursor":"LAST_STAMP_ERROR|publi'
    'c|r3","fresh_cursor":true},{"op":"row_factory.enter","read":3,"cursor":"LAST_STAMP_ERROR'
    '|public|r3","value":null},{"op":"row_factory.return","read":3,"cursor":"LAST_STAMP_ERROR'
    '|public|r3","value":null},{"op":"execute.enter","read":3,"cursor":"LAST_STAMP_ERROR|publ'
    'ic|r3","sql":"PRAGMA main.table_xinfo(\\"job_checkpoints\\")"},{"op":"execute.return","rea'
    'd":3,"cursor":"LAST_STAMP_ERROR|public|r3","value":"same_cursor"},{"op":"fetchall.enter"'
    ',"read":3,"cursor":"LAST_STAMP_ERROR|public|r3"},{"op":"fetchall.return","read":3,"curso'
    'r":"LAST_STAMP_ERROR|public|r3","rows":[[0,"job_id","TEXT",1,null,0,0],[1,"attempt_id","'
    'TEXT",1,null,0,0],[2,"result_ref","TEXT",1,null,0,0]],"runtime_container":"list[tuple]"}'
    ',{"op":"close.enter","read":3,"cursor":"LAST_STAMP_ERROR|public|r3"},{"op":"close.return'
    '","read":3,"cursor":"LAST_STAMP_ERROR|public|r3","value":null},{"op":"cursor.create.ente'
    'r","read":4,"cursor":"LAST_STAMP_ERROR|public|r4"},{"op":"cursor.create.return","read":4'
    ',"cursor":"LAST_STAMP_ERROR|public|r4","fresh_cursor":true},{"op":"row_factory.enter","r'
    'ead":4,"cursor":"LAST_STAMP_ERROR|public|r4","value":null},{"op":"row_factory.return","r'
    'ead":4,"cursor":"LAST_STAMP_ERROR|public|r4","value":null},{"op":"execute.enter","read":'
    '4,"cursor":"LAST_STAMP_ERROR|public|r4","sql":"PRAGMA main.foreign_key_list(\\"job_checkp'
    'oints\\")"},{"op":"execute.return","read":4,"cursor":"LAST_STAMP_ERROR|public|r4","value"'
    ':"same_cursor"},{"op":"fetchall.enter","read":4,"cursor":"LAST_STAMP_ERROR|public|r4"},{'
    '"op":"fetchall.return","read":4,"cursor":"LAST_STAMP_ERROR|public|r4","rows":[[0,0,"jobs'
    '","job_id","job_id","NO ACTION","NO ACTION","NONE"]],"runtime_container":"list[tuple]"},'
    '{"op":"close.enter","read":4,"cursor":"LAST_STAMP_ERROR|public|r4"},{"op":"close.return"'
    ',"read":4,"cursor":"LAST_STAMP_ERROR|public|r4","value":null},{"op":"cursor.create.enter'
    '","read":5,"cursor":"LAST_STAMP_ERROR|public|r5"},{"op":"cursor.create.return","read":5,'
    '"cursor":"LAST_STAMP_ERROR|public|r5","fresh_cursor":true},{"op":"row_factory.enter","re'
    'ad":5,"cursor":"LAST_STAMP_ERROR|public|r5","value":null},{"op":"row_factory.return","re'
    'ad":5,"cursor":"LAST_STAMP_ERROR|public|r5","value":null},{"op":"execute.enter","read":5'
    ',"cursor":"LAST_STAMP_ERROR|public|r5","sql":"PRAGMA main.index_list(\\"job_checkpoints\\"'
    ')"},{"op":"execute.return","read":5,"cursor":"LAST_STAMP_ERROR|public|r5","value":"same_'
    'cursor"},{"op":"fetchall.enter","read":5,"cursor":"LAST_STAMP_ERROR|public|r5"},{"op":"f'
    'etchall.return","read":5,"cursor":"LAST_STAMP_ERROR|public|r5","rows":[[0,"sqlite_autoin'
    'dex_job_checkpoints_1",1,"u",0]],"runtime_container":"list[tuple]"},{"op":"close.enter",'
    '"read":5,"cursor":"LAST_STAMP_ERROR|public|r5"},{"op":"close.return","read":5,"cursor":"'
    'LAST_STAMP_ERROR|public|r5","value":null},{"op":"cursor.create.enter","read":6,"cursor":'
    '"LAST_STAMP_ERROR|public|r6"},{"op":"cursor.create.return","read":6,"cursor":"LAST_STAMP'
    '_ERROR|public|r6","fresh_cursor":true},{"op":"row_factory.enter","read":6,"cursor":"LAST'
    '_STAMP_ERROR|public|r6","value":null},{"op":"row_factory.return","read":6,"cursor":"LAST'
    '_STAMP_ERROR|public|r6","value":null},{"op":"execute.enter","read":6,"cursor":"LAST_STAM'
    'P_ERROR|public|r6","sql":"PRAGMA main.index_xinfo(\\"sqlite_autoindex_job_checkpoints_1\\"'
    ')"},{"op":"execute.return","read":6,"cursor":"LAST_STAMP_ERROR|public|r6","value":"same_'
    'cursor"},{"op":"fetchall.enter","read":6,"cursor":"LAST_STAMP_ERROR|public|r6"},{"op":"f'
    'etchall.return","read":6,"cursor":"LAST_STAMP_ERROR|public|r6","rows":[[0,0,"job_id",0,"'
    'BINARY",1],[1,2,"result_ref",0,"BINARY",1],[2,-1,null,0,"BINARY",0]],"runtime_container"'
    ':"list[tuple]"},{"op":"close.enter","read":6,"cursor":"LAST_STAMP_ERROR|public|r6"},{"op'
    '":"close.return","read":6,"cursor":"LAST_STAMP_ERROR|public|r6","value":null},{"op":"cur'
    'sor.create.enter","read":7,"cursor":"LAST_STAMP_ERROR|public|r7"},{"op":"cursor.create.r'
    'eturn","read":7,"cursor":"LAST_STAMP_ERROR|public|r7","fresh_cursor":true},{"op":"row_fa'
    'ctory.enter","read":7,"cursor":"LAST_STAMP_ERROR|public|r7","value":null},{"op":"row_fac'
    'tory.return","read":7,"cursor":"LAST_STAMP_ERROR|public|r7","value":null},{"op":"execute'
    '.enter","read":7,"cursor":"LAST_STAMP_ERROR|public|r7","sql":"PRAGMA main.schema_version'
    '"},{"op":"execute.return","read":7,"cursor":"LAST_STAMP_ERROR|public|r7","value":"same_c'
    'ursor"},{"op":"fetchall.enter","read":7,"cursor":"LAST_STAMP_ERROR|public|r7"},{"op":"fe'
    'tchall.raise","read":7,"cursor":"LAST_STAMP_ERROR|public|r7","identity":"LAST_STAMP_ERRO'
    'R|public|E"},{"op":"close.enter","read":7,"cursor":"LAST_STAMP_ERROR|public|r7"},{"op":"'
    'close.return","read":7,"cursor":"LAST_STAMP_ERROR|public|r7","value":null},{"op":"route.'
    'raise","identity":"LAST_STAMP_ERROR|public|PUBLIC_CLOSED","exact_class":"builtins.ValueE'
    'rror"}],"trace_counts":{"cursor.create.enter":7,"cursor.create.return":7,"row_factory.en'
    'ter":7,"row_factory.return":7,"execute.enter":7,"execute.return":7,"fetchall.enter":7,"f'
    'etchall.return":6,"close.enter":7,"close.return":7,"close.raise":0},"internal_canonical_'
    'wire_call_count_not_constrained":true,"native_cleanup_proved":false},{"route_id":"LAST_S'
    'TAMP_CHANGED|private","route":"private","api_name_future_private_unimplemented":"recoryn'
    '.schema._component_shape_wire_read","fake_identity":"LAST_STAMP_CHANGED|private|connecti'
    'on","fresh_all_objects":true,"prepare_hash_or_raise":false,"expected_model":"fresh_deep_'
    'copy_of_hand_anchor.model","component_input":"jobs.checkpoints","program":[{"read":1,"cu'
    'rsor":"r1","sql":"PRAGMA main.schema_version","rows":[[7]]},{"read":2,"cursor":"r2","sql'
    '":"SELECT type,name,tbl_name,sql FROM main.sqlite_schema","rows":[["table","job_checkpoi'
    'nts","job_checkpoints","CREATE TABLE IF NOT EXISTS job_checkpoints (job_id TEXT NOT NULL'
    " REFERENCES jobs(job_id), attempt_id TEXT NOT NULL, result_ref TEXT NOT NULL, UNIQUE(job"
    '_id,result_ref));"],["index","sqlite_autoindex_job_checkpoints_1","job_checkpoints",null'
    ']]},{"read":3,"cursor":"r3","sql":"PRAGMA main.table_xinfo(\\"job_checkpoints\\")","rows":'
    '[[0,"job_id","TEXT",1,null,0,0],[1,"attempt_id","TEXT",1,null,0,0],[2,"result_ref","TEXT'
    '",1,null,0,0]]},{"read":4,"cursor":"r4","sql":"PRAGMA main.foreign_key_list(\\"job_checkp'
    'oints\\")","rows":[[0,0,"jobs","job_id","job_id","NO ACTION","NO ACTION","NONE"]]},{"read'
    '":5,"cursor":"r5","sql":"PRAGMA main.index_list(\\"job_checkpoints\\")","rows":[[0,"sqlite'
    '_autoindex_job_checkpoints_1",1,"u",0]]},{"read":6,"cursor":"r6","sql":"PRAGMA main.inde'
    'x_xinfo(\\"sqlite_autoindex_job_checkpoints_1\\")","rows":[[0,0,"job_id",0,"BINARY",1],[1,'
    '2,"result_ref",0,"BINARY",1],[2,-1,null,0,"BINARY",0]]},{"read":7,"cursor":"r7","sql":"P'
    'RAGMA main.schema_version","rows":[[8]]}],"fault":null,"close_fault":null,"exception_obj'
    'ects_spec_only":{"SHAPE":{"identity":"LAST_STAMP_CHANGED|private|SHAPE","exact_class":"b'
    'uiltins.ValueError","args":["Unsupported component shape"],"str":"Unsupported component '
    'shape","repr":"ValueError(\'Unsupported component shape\')","__cause__":null,"__context__"'
    ':null,"__suppress_context__":false,"role":"captured_product_created_error","context_fiel'
    'ds_are_post_call_oracle_not_fixture_assignment":true,"fixture_must_not_precreate":true}}'
    ',"outcome":{"final_component_wire_return":0,"component_wire_return_not_applicable":false'
    ',"kind":"exception","error":{"identity":"LAST_STAMP_CHANGED|private|SHAPE","exact_class"'
    ':"builtins.ValueError","args":["Unsupported component shape"],"str":"Unsupported compone'
    'nt shape","repr":"ValueError(\'Unsupported component shape\')","__cause__":null,"__context'
    '__":null,"__suppress_context__":false},"identity_assertion_required":false,"capture_prod'
    'uct_created_error_only":true},"trace_oracle":[{"op":"route.call.enter","api":"recoryn.sc'
    'hema._component_shape_wire_read"},{"op":"cursor.create.enter","read":1,"cursor":"LAST_ST'
    'AMP_CHANGED|private|r1"},{"op":"cursor.create.return","read":1,"cursor":"LAST_STAMP_CHAN'
    'GED|private|r1","fresh_cursor":true},{"op":"row_factory.enter","read":1,"cursor":"LAST_S'
    'TAMP_CHANGED|private|r1","value":null},{"op":"row_factory.return","read":1,"cursor":"LAS'
    'T_STAMP_CHANGED|private|r1","value":null},{"op":"execute.enter","read":1,"cursor":"LAST_'
    'STAMP_CHANGED|private|r1","sql":"PRAGMA main.schema_version"},{"op":"execute.return","re'
    'ad":1,"cursor":"LAST_STAMP_CHANGED|private|r1","value":"same_cursor"},{"op":"fetchall.en'
    'ter","read":1,"cursor":"LAST_STAMP_CHANGED|private|r1"},{"op":"fetchall.return","read":1'
    ',"cursor":"LAST_STAMP_CHANGED|private|r1","rows":[[7]],"runtime_container":"list[tuple]"'
    '},{"op":"close.enter","read":1,"cursor":"LAST_STAMP_CHANGED|private|r1"},{"op":"close.re'
    'turn","read":1,"cursor":"LAST_STAMP_CHANGED|private|r1","value":null},{"op":"cursor.crea'
    'te.enter","read":2,"cursor":"LAST_STAMP_CHANGED|private|r2"},{"op":"cursor.create.return'
    '","read":2,"cursor":"LAST_STAMP_CHANGED|private|r2","fresh_cursor":true},{"op":"row_fact'
    'ory.enter","read":2,"cursor":"LAST_STAMP_CHANGED|private|r2","value":null},{"op":"row_fa'
    'ctory.return","read":2,"cursor":"LAST_STAMP_CHANGED|private|r2","value":null},{"op":"exe'
    'cute.enter","read":2,"cursor":"LAST_STAMP_CHANGED|private|r2","sql":"SELECT type,name,tb'
    'l_name,sql FROM main.sqlite_schema"},{"op":"execute.return","read":2,"cursor":"LAST_STAM'
    'P_CHANGED|private|r2","value":"same_cursor"},{"op":"fetchall.enter","read":2,"cursor":"L'
    'AST_STAMP_CHANGED|private|r2"},{"op":"fetchall.return","read":2,"cursor":"LAST_STAMP_CHA'
    'NGED|private|r2","rows":[["table","job_checkpoints","job_checkpoints","CREATE TABLE IF N'
    "OT EXISTS job_checkpoints (job_id TEXT NOT NULL REFERENCES jobs(job_id), attempt_id TEXT"
    ' NOT NULL, result_ref TEXT NOT NULL, UNIQUE(job_id,result_ref));"],["index","sqlite_auto'
    'index_job_checkpoints_1","job_checkpoints",null]],"runtime_container":"list[tuple]"},{"o'
    'p":"close.enter","read":2,"cursor":"LAST_STAMP_CHANGED|private|r2"},{"op":"close.return"'
    ',"read":2,"cursor":"LAST_STAMP_CHANGED|private|r2","value":null},{"op":"cursor.create.en'
    'ter","read":3,"cursor":"LAST_STAMP_CHANGED|private|r3"},{"op":"cursor.create.return","re'
    'ad":3,"cursor":"LAST_STAMP_CHANGED|private|r3","fresh_cursor":true},{"op":"row_factory.e'
    'nter","read":3,"cursor":"LAST_STAMP_CHANGED|private|r3","value":null},{"op":"row_factory'
    '.return","read":3,"cursor":"LAST_STAMP_CHANGED|private|r3","value":null},{"op":"execute.'
    'enter","read":3,"cursor":"LAST_STAMP_CHANGED|private|r3","sql":"PRAGMA main.table_xinfo('
    '\\"job_checkpoints\\")"},{"op":"execute.return","read":3,"cursor":"LAST_STAMP_CHANGED|priv'
    'ate|r3","value":"same_cursor"},{"op":"fetchall.enter","read":3,"cursor":"LAST_STAMP_CHAN'
    'GED|private|r3"},{"op":"fetchall.return","read":3,"cursor":"LAST_STAMP_CHANGED|private|r'
    '3","rows":[[0,"job_id","TEXT",1,null,0,0],[1,"attempt_id","TEXT",1,null,0,0],[2,"result_'
    'ref","TEXT",1,null,0,0]],"runtime_container":"list[tuple]"},{"op":"close.enter","read":3'
    ',"cursor":"LAST_STAMP_CHANGED|private|r3"},{"op":"close.return","read":3,"cursor":"LAST_'
    'STAMP_CHANGED|private|r3","value":null},{"op":"cursor.create.enter","read":4,"cursor":"L'
    'AST_STAMP_CHANGED|private|r4"},{"op":"cursor.create.return","read":4,"cursor":"LAST_STAM'
    'P_CHANGED|private|r4","fresh_cursor":true},{"op":"row_factory.enter","read":4,"cursor":"'
    'LAST_STAMP_CHANGED|private|r4","value":null},{"op":"row_factory.return","read":4,"cursor'
    '":"LAST_STAMP_CHANGED|private|r4","value":null},{"op":"execute.enter","read":4,"cursor":'
    '"LAST_STAMP_CHANGED|private|r4","sql":"PRAGMA main.foreign_key_list(\\"job_checkpoints\\")'
    '"},{"op":"execute.return","read":4,"cursor":"LAST_STAMP_CHANGED|private|r4","value":"sam'
    'e_cursor"},{"op":"fetchall.enter","read":4,"cursor":"LAST_STAMP_CHANGED|private|r4"},{"o'
    'p":"fetchall.return","read":4,"cursor":"LAST_STAMP_CHANGED|private|r4","rows":[[0,0,"job'
    's","job_id","job_id","NO ACTION","NO ACTION","NONE"]],"runtime_container":"list[tuple]"}'
    ',{"op":"close.enter","read":4,"cursor":"LAST_STAMP_CHANGED|private|r4"},{"op":"close.ret'
    'urn","read":4,"cursor":"LAST_STAMP_CHANGED|private|r4","value":null},{"op":"cursor.creat'
    'e.enter","read":5,"cursor":"LAST_STAMP_CHANGED|private|r5"},{"op":"cursor.create.return"'
    ',"read":5,"cursor":"LAST_STAMP_CHANGED|private|r5","fresh_cursor":true},{"op":"row_facto'
    'ry.enter","read":5,"cursor":"LAST_STAMP_CHANGED|private|r5","value":null},{"op":"row_fac'
    'tory.return","read":5,"cursor":"LAST_STAMP_CHANGED|private|r5","value":null},{"op":"exec'
    'ute.enter","read":5,"cursor":"LAST_STAMP_CHANGED|private|r5","sql":"PRAGMA main.index_li'
    'st(\\"job_checkpoints\\")"},{"op":"execute.return","read":5,"cursor":"LAST_STAMP_CHANGED|p'
    'rivate|r5","value":"same_cursor"},{"op":"fetchall.enter","read":5,"cursor":"LAST_STAMP_C'
    'HANGED|private|r5"},{"op":"fetchall.return","read":5,"cursor":"LAST_STAMP_CHANGED|privat'
    'e|r5","rows":[[0,"sqlite_autoindex_job_checkpoints_1",1,"u",0]],"runtime_container":"lis'
    't[tuple]"},{"op":"close.enter","read":5,"cursor":"LAST_STAMP_CHANGED|private|r5"},{"op":'
    '"close.return","read":5,"cursor":"LAST_STAMP_CHANGED|private|r5","value":null},{"op":"cu'
    'rsor.create.enter","read":6,"cursor":"LAST_STAMP_CHANGED|private|r6"},{"op":"cursor.crea'
    'te.return","read":6,"cursor":"LAST_STAMP_CHANGED|private|r6","fresh_cursor":true},{"op":'
    '"row_factory.enter","read":6,"cursor":"LAST_STAMP_CHANGED|private|r6","value":null},{"op'
    '":"row_factory.return","read":6,"cursor":"LAST_STAMP_CHANGED|private|r6","value":null},{'
    '"op":"execute.enter","read":6,"cursor":"LAST_STAMP_CHANGED|private|r6","sql":"PRAGMA mai'
    'n.index_xinfo(\\"sqlite_autoindex_job_checkpoints_1\\")"},{"op":"execute.return","read":6,'
    '"cursor":"LAST_STAMP_CHANGED|private|r6","value":"same_cursor"},{"op":"fetchall.enter","'
    'read":6,"cursor":"LAST_STAMP_CHANGED|private|r6"},{"op":"fetchall.return","read":6,"curs'
    'or":"LAST_STAMP_CHANGED|private|r6","rows":[[0,0,"job_id",0,"BINARY",1],[1,2,"result_ref'
    '",0,"BINARY",1],[2,-1,null,0,"BINARY",0]],"runtime_container":"list[tuple]"},{"op":"clos'
    'e.enter","read":6,"cursor":"LAST_STAMP_CHANGED|private|r6"},{"op":"close.return","read":'
    '6,"cursor":"LAST_STAMP_CHANGED|private|r6","value":null},{"op":"cursor.create.enter","re'
    'ad":7,"cursor":"LAST_STAMP_CHANGED|private|r7"},{"op":"cursor.create.return","read":7,"c'
    'ursor":"LAST_STAMP_CHANGED|private|r7","fresh_cursor":true},{"op":"row_factory.enter","r'
    'ead":7,"cursor":"LAST_STAMP_CHANGED|private|r7","value":null},{"op":"row_factory.return"'
    ',"read":7,"cursor":"LAST_STAMP_CHANGED|private|r7","value":null},{"op":"execute.enter","'
    'read":7,"cursor":"LAST_STAMP_CHANGED|private|r7","sql":"PRAGMA main.schema_version"},{"o'
    'p":"execute.return","read":7,"cursor":"LAST_STAMP_CHANGED|private|r7","value":"same_curs'
    'or"},{"op":"fetchall.enter","read":7,"cursor":"LAST_STAMP_CHANGED|private|r7"},{"op":"fe'
    'tchall.return","read":7,"cursor":"LAST_STAMP_CHANGED|private|r7","rows":[[8]],"runtime_c'
    'ontainer":"list[tuple]"},{"op":"close.enter","read":7,"cursor":"LAST_STAMP_CHANGED|priva'
    'te|r7"},{"op":"close.return","read":7,"cursor":"LAST_STAMP_CHANGED|private|r7","value":n'
    'ull},{"op":"route.raise","identity":"LAST_STAMP_CHANGED|private|SHAPE","exact_class":"bu'
    'iltins.ValueError"}],"trace_counts":{"cursor.create.enter":7,"cursor.create.return":7,"r'
    'ow_factory.enter":7,"row_factory.return":7,"execute.enter":7,"execute.return":7,"fetchal'
    'l.enter":7,"fetchall.return":7,"close.enter":7,"close.return":7,"close.raise":0},"intern'
    'al_canonical_wire_call_count_not_constrained":true,"native_cleanup_proved":false},{"rout'
    'e_id":"LAST_STAMP_CHANGED|public","route":"public","api_name_future_private_unimplemente'
    'd":"recoryn.schema.component_shape_wire","fake_identity":"LAST_STAMP_CHANGED|public|conn'
    'ection","fresh_all_objects":true,"prepare_hash_or_raise":false,"expected_model":"actual_'
    'public_expected_lookup_not_stubbed","component_input":"jobs.checkpoints","program":[{"re'
    'ad":1,"cursor":"r1","sql":"PRAGMA main.schema_version","rows":[[7]]},{"read":2,"cursor":'
    '"r2","sql":"SELECT type,name,tbl_name,sql FROM main.sqlite_schema","rows":[["table","job'
    '_checkpoints","job_checkpoints","CREATE TABLE IF NOT EXISTS job_checkpoints (job_id TEXT'
    " NOT NULL REFERENCES jobs(job_id), attempt_id TEXT NOT NULL, result_ref TEXT NOT NULL, U"
    'NIQUE(job_id,result_ref));"],["index","sqlite_autoindex_job_checkpoints_1","job_checkpoi'
    'nts",null]]},{"read":3,"cursor":"r3","sql":"PRAGMA main.table_xinfo(\\"job_checkpoints\\")'
    '","rows":[[0,"job_id","TEXT",1,null,0,0],[1,"attempt_id","TEXT",1,null,0,0],[2,"result_r'
    'ef","TEXT",1,null,0,0]]},{"read":4,"cursor":"r4","sql":"PRAGMA main.foreign_key_list(\\"j'
    'ob_checkpoints\\")","rows":[[0,0,"jobs","job_id","job_id","NO ACTION","NO ACTION","NONE"]'
    ']},{"read":5,"cursor":"r5","sql":"PRAGMA main.index_list(\\"job_checkpoints\\")","rows":[['
    '0,"sqlite_autoindex_job_checkpoints_1",1,"u",0]]},{"read":6,"cursor":"r6","sql":"PRAGMA '
    'main.index_xinfo(\\"sqlite_autoindex_job_checkpoints_1\\")","rows":[[0,0,"job_id",0,"BINAR'
    'Y",1],[1,2,"result_ref",0,"BINARY",1],[2,-1,null,0,"BINARY",0]]},{"read":7,"cursor":"r7"'
    ',"sql":"PRAGMA main.schema_version","rows":[[8]]}],"fault":null,"close_fault":null,"exce'
    'ption_objects_spec_only":{"SHAPE":{"identity":"LAST_STAMP_CHANGED|public|SHAPE","exact_c'
    'lass":"builtins.ValueError","args":["Unsupported component shape"],"str":"Unsupported co'
    'mponent shape","repr":"ValueError(\'Unsupported component shape\')","__cause__":null,"__co'
    'ntext__":null,"__suppress_context__":false,"role":"captured_product_created_error","cont'
    'ext_fields_are_post_call_oracle_not_fixture_assignment":true,"fixture_must_not_precreate'
    '":true}},"outcome":{"final_component_wire_return":0,"component_wire_return_not_applicabl'
    'e":false,"kind":"exception","error":{"identity":"LAST_STAMP_CHANGED|public|SHAPE","exact'
    '_class":"builtins.ValueError","args":["Unsupported component shape"],"str":"Unsupported '
    'component shape","repr":"ValueError(\'Unsupported component shape\')","__cause__":null,"__'
    'context__":null,"__suppress_context__":false},"identity_assertion_required":false,"captu'
    're_product_created_error_only":true},"trace_oracle":[{"op":"route.call.enter","api":"rec'
    'oryn.schema.component_shape_wire"},{"op":"cursor.create.enter","read":1,"cursor":"LAST_S'
    'TAMP_CHANGED|public|r1"},{"op":"cursor.create.return","read":1,"cursor":"LAST_STAMP_CHAN'
    'GED|public|r1","fresh_cursor":true},{"op":"row_factory.enter","read":1,"cursor":"LAST_ST'
    'AMP_CHANGED|public|r1","value":null},{"op":"row_factory.return","read":1,"cursor":"LAST_'
    'STAMP_CHANGED|public|r1","value":null},{"op":"execute.enter","read":1,"cursor":"LAST_STA'
    'MP_CHANGED|public|r1","sql":"PRAGMA main.schema_version"},{"op":"execute.return","read":'
    '1,"cursor":"LAST_STAMP_CHANGED|public|r1","value":"same_cursor"},{"op":"fetchall.enter",'
    '"read":1,"cursor":"LAST_STAMP_CHANGED|public|r1"},{"op":"fetchall.return","read":1,"curs'
    'or":"LAST_STAMP_CHANGED|public|r1","rows":[[7]],"runtime_container":"list[tuple]"},{"op"'
    ':"close.enter","read":1,"cursor":"LAST_STAMP_CHANGED|public|r1"},{"op":"close.return","r'
    'ead":1,"cursor":"LAST_STAMP_CHANGED|public|r1","value":null},{"op":"cursor.create.enter"'
    ',"read":2,"cursor":"LAST_STAMP_CHANGED|public|r2"},{"op":"cursor.create.return","read":2'
    ',"cursor":"LAST_STAMP_CHANGED|public|r2","fresh_cursor":true},{"op":"row_factory.enter",'
    '"read":2,"cursor":"LAST_STAMP_CHANGED|public|r2","value":null},{"op":"row_factory.return'
    '","read":2,"cursor":"LAST_STAMP_CHANGED|public|r2","value":null},{"op":"execute.enter","'
    'read":2,"cursor":"LAST_STAMP_CHANGED|public|r2","sql":"SELECT type,name,tbl_name,sql FRO'
    'M main.sqlite_schema"},{"op":"execute.return","read":2,"cursor":"LAST_STAMP_CHANGED|publ'
    'ic|r2","value":"same_cursor"},{"op":"fetchall.enter","read":2,"cursor":"LAST_STAMP_CHANG'
    'ED|public|r2"},{"op":"fetchall.return","read":2,"cursor":"LAST_STAMP_CHANGED|public|r2",'
    '"rows":[["table","job_checkpoints","job_checkpoints","CREATE TABLE IF NOT EXISTS job_che'
    "ckpoints (job_id TEXT NOT NULL REFERENCES jobs(job_id), attempt_id TEXT NOT NULL, result"
    '_ref TEXT NOT NULL, UNIQUE(job_id,result_ref));"],["index","sqlite_autoindex_job_checkpo'
    'ints_1","job_checkpoints",null]],"runtime_container":"list[tuple]"},{"op":"close.enter",'
    '"read":2,"cursor":"LAST_STAMP_CHANGED|public|r2"},{"op":"close.return","read":2,"cursor"'
    ':"LAST_STAMP_CHANGED|public|r2","value":null},{"op":"cursor.create.enter","read":3,"curs'
    'or":"LAST_STAMP_CHANGED|public|r3"},{"op":"cursor.create.return","read":3,"cursor":"LAST'
    '_STAMP_CHANGED|public|r3","fresh_cursor":true},{"op":"row_factory.enter","read":3,"curso'
    'r":"LAST_STAMP_CHANGED|public|r3","value":null},{"op":"row_factory.return","read":3,"cur'
    'sor":"LAST_STAMP_CHANGED|public|r3","value":null},{"op":"execute.enter","read":3,"cursor'
    '":"LAST_STAMP_CHANGED|public|r3","sql":"PRAGMA main.table_xinfo(\\"job_checkpoints\\")"},{'
    '"op":"execute.return","read":3,"cursor":"LAST_STAMP_CHANGED|public|r3","value":"same_cur'
    'sor"},{"op":"fetchall.enter","read":3,"cursor":"LAST_STAMP_CHANGED|public|r3"},{"op":"fe'
    'tchall.return","read":3,"cursor":"LAST_STAMP_CHANGED|public|r3","rows":[[0,"job_id","TEX'
    'T",1,null,0,0],[1,"attempt_id","TEXT",1,null,0,0],[2,"result_ref","TEXT",1,null,0,0]],"r'
    'untime_container":"list[tuple]"},{"op":"close.enter","read":3,"cursor":"LAST_STAMP_CHANG'
    'ED|public|r3"},{"op":"close.return","read":3,"cursor":"LAST_STAMP_CHANGED|public|r3","va'
    'lue":null},{"op":"cursor.create.enter","read":4,"cursor":"LAST_STAMP_CHANGED|public|r4"}'
    ',{"op":"cursor.create.return","read":4,"cursor":"LAST_STAMP_CHANGED|public|r4","fresh_cu'
    'rsor":true},{"op":"row_factory.enter","read":4,"cursor":"LAST_STAMP_CHANGED|public|r4","'
    'value":null},{"op":"row_factory.return","read":4,"cursor":"LAST_STAMP_CHANGED|public|r4"'
    ',"value":null},{"op":"execute.enter","read":4,"cursor":"LAST_STAMP_CHANGED|public|r4","s'
    'ql":"PRAGMA main.foreign_key_list(\\"job_checkpoints\\")"},{"op":"execute.return","read":4'
    ',"cursor":"LAST_STAMP_CHANGED|public|r4","value":"same_cursor"},{"op":"fetchall.enter","'
    'read":4,"cursor":"LAST_STAMP_CHANGED|public|r4"},{"op":"fetchall.return","read":4,"curso'
    'r":"LAST_STAMP_CHANGED|public|r4","rows":[[0,0,"jobs","job_id","job_id","NO ACTION","NO '
    'ACTION","NONE"]],"runtime_container":"list[tuple]"},{"op":"close.enter","read":4,"cursor'
    '":"LAST_STAMP_CHANGED|public|r4"},{"op":"close.return","read":4,"cursor":"LAST_STAMP_CHA'
    'NGED|public|r4","value":null},{"op":"cursor.create.enter","read":5,"cursor":"LAST_STAMP_'
    'CHANGED|public|r5"},{"op":"cursor.create.return","read":5,"cursor":"LAST_STAMP_CHANGED|p'
    'ublic|r5","fresh_cursor":true},{"op":"row_factory.enter","read":5,"cursor":"LAST_STAMP_C'
    'HANGED|public|r5","value":null},{"op":"row_factory.return","read":5,"cursor":"LAST_STAMP'
    '_CHANGED|public|r5","value":null},{"op":"execute.enter","read":5,"cursor":"LAST_STAMP_CH'
    'ANGED|public|r5","sql":"PRAGMA main.index_list(\\"job_checkpoints\\")"},{"op":"execute.ret'
    'urn","read":5,"cursor":"LAST_STAMP_CHANGED|public|r5","value":"same_cursor"},{"op":"fetc'
    'hall.enter","read":5,"cursor":"LAST_STAMP_CHANGED|public|r5"},{"op":"fetchall.return","r'
    'ead":5,"cursor":"LAST_STAMP_CHANGED|public|r5","rows":[[0,"sqlite_autoindex_job_checkpoi'
    'nts_1",1,"u",0]],"runtime_container":"list[tuple]"},{"op":"close.enter","read":5,"cursor'
    '":"LAST_STAMP_CHANGED|public|r5"},{"op":"close.return","read":5,"cursor":"LAST_STAMP_CHA'
    'NGED|public|r5","value":null},{"op":"cursor.create.enter","read":6,"cursor":"LAST_STAMP_'
    'CHANGED|public|r6"},{"op":"cursor.create.return","read":6,"cursor":"LAST_STAMP_CHANGED|p'
    'ublic|r6","fresh_cursor":true},{"op":"row_factory.enter","read":6,"cursor":"LAST_STAMP_C'
    'HANGED|public|r6","value":null},{"op":"row_factory.return","read":6,"cursor":"LAST_STAMP'
    '_CHANGED|public|r6","value":null},{"op":"execute.enter","read":6,"cursor":"LAST_STAMP_CH'
    'ANGED|public|r6","sql":"PRAGMA main.index_xinfo(\\"sqlite_autoindex_job_checkpoints_1\\")"'
    '},{"op":"execute.return","read":6,"cursor":"LAST_STAMP_CHANGED|public|r6","value":"same_'
    'cursor"},{"op":"fetchall.enter","read":6,"cursor":"LAST_STAMP_CHANGED|public|r6"},{"op":'
    '"fetchall.return","read":6,"cursor":"LAST_STAMP_CHANGED|public|r6","rows":[[0,0,"job_id"'
    ',0,"BINARY",1],[1,2,"result_ref",0,"BINARY",1],[2,-1,null,0,"BINARY",0]],"runtime_contai'
    'ner":"list[tuple]"},{"op":"close.enter","read":6,"cursor":"LAST_STAMP_CHANGED|public|r6"'
    '},{"op":"close.return","read":6,"cursor":"LAST_STAMP_CHANGED|public|r6","value":null},{"'
    'op":"cursor.create.enter","read":7,"cursor":"LAST_STAMP_CHANGED|public|r7"},{"op":"curso'
    'r.create.return","read":7,"cursor":"LAST_STAMP_CHANGED|public|r7","fresh_cursor":true},{'
    '"op":"row_factory.enter","read":7,"cursor":"LAST_STAMP_CHANGED|public|r7","value":null},'
    '{"op":"row_factory.return","read":7,"cursor":"LAST_STAMP_CHANGED|public|r7","value":null'
    '},{"op":"execute.enter","read":7,"cursor":"LAST_STAMP_CHANGED|public|r7","sql":"PRAGMA m'
    'ain.schema_version"},{"op":"execute.return","read":7,"cursor":"LAST_STAMP_CHANGED|public'
    '|r7","value":"same_cursor"},{"op":"fetchall.enter","read":7,"cursor":"LAST_STAMP_CHANGED'
    '|public|r7"},{"op":"fetchall.return","read":7,"cursor":"LAST_STAMP_CHANGED|public|r7","r'
    'ows":[[8]],"runtime_container":"list[tuple]"},{"op":"close.enter","read":7,"cursor":"LAS'
    'T_STAMP_CHANGED|public|r7"},{"op":"close.return","read":7,"cursor":"LAST_STAMP_CHANGED|p'
    'ublic|r7","value":null},{"op":"route.raise","identity":"LAST_STAMP_CHANGED|public|SHAPE"'
    ',"exact_class":"builtins.ValueError"}],"trace_counts":{"cursor.create.enter":7,"cursor.c'
    'reate.return":7,"row_factory.enter":7,"row_factory.return":7,"execute.enter":7,"execute.'
    'return":7,"fetchall.enter":7,"fetchall.return":7,"close.enter":7,"close.return":7,"close'
    '.raise":0},"internal_canonical_wire_call_count_not_constrained":true,"native_cleanup_pro'
    'ved":false}],"single_labels":["READ_OK","UNKNOWN_COMPONENT","EXPECTED_OUTSIDE","INDEX_RE'
    'AD_ERROR","TABLE_READ_ERROR"]}'
)
_SEAM_LITERAL_SHA = "18f64e437acbeac8da34645a8cf536f0e2d726493b8e332f46553117f00df51f"
_SEAM_HAND = json.loads(_SEAM_LITERAL_JSON)
_SEAM_OBS: list[dict] = []
_SEAM_LIVE: list[object] = []


class _SeamCursor:
    def __init__(self, owner, step):
        self.owner = owner
        self.step = step
        self.token = owner.spec["route_id"] + "|" + step["cursor"]

    def enter(self, stage, **extra):
        self.owner.trace.append(
            {"op": stage + ".enter", "read": self.step["read"], "cursor": self.token, **extra}
        )
        self.owner.fail(stage, self.step, self.token)

    def returned(self, stage, **extra):
        self.owner.trace.append(
            {"op": stage + ".return", "read": self.step["read"], "cursor": self.token, **extra}
        )

    @property
    def row_factory(self):
        return None

    @row_factory.setter
    def row_factory(self, value):
        self.enter("row_factory", value=value)
        assert value is None, "SEAM_ROW_FACTORY_NONE"
        self.returned("row_factory", value=None)

    def execute(self, sql):
        self.enter("execute", sql=sql)
        assert sql == self.step["sql"], "SEAM_EXACT_HAND_SQL"
        self.returned("execute", value="same_cursor")
        return self

    def fetchall(self):
        self.enter("fetchall")
        rows = [tuple(row) for row in self.step["rows"]]
        self.returned("fetchall", rows=[list(row) for row in rows], runtime_container="list[tuple]")
        return rows

    def close(self):
        self.owner.trace.append(
            {"op": "close.enter", "read": self.step["read"], "cursor": self.token}
        )
        symbol = self.owner.spec["close_fault"]
        if symbol:
            self.owner.trace.append(
                {
                    "op": "close.raise",
                    "read": self.step["read"],
                    "cursor": self.token,
                    "identity": self.owner.spec["exception_objects_spec_only"][symbol]["identity"],
                }
            )
            raise self.owner.errors[symbol]
        self.returned("close", value=None)


class _SeamConnection:
    def __init__(self, spec, errors):
        self.spec = spec
        self.errors = errors
        self.offset = 0
        self.cursors = []
        self.trace = [
            {"op": "route.call.enter", "api": spec["api_name_future_private_unimplemented"]}
        ]

    def fail(self, stage, step, token):
        fault = self.spec["fault"]
        if fault and fault["read"] == step["read"] and fault["stage"] == stage:
            self.trace.append(
                {
                    "op": stage + ".raise",
                    "read": step["read"],
                    "cursor": token,
                    "identity": self.spec["exception_objects_spec_only"]["E"]["identity"],
                }
            )
            raise self.errors["E"]

    def cursor(self):
        assert self.offset < len(self.spec["program"]), "SEAM_NO_EXTRA_READ"
        step = self.spec["program"][self.offset]
        self.offset += 1
        token = self.spec["route_id"] + "|" + step["cursor"]
        self.trace.append({"op": "cursor.create.enter", "read": step["read"], "cursor": token})
        self.fail("cursor.create", step, token)
        value = _SeamCursor(self, step)
        self.cursors.append(value)
        self.trace.append(
            {
                "op": "cursor.create.return",
                "read": step["read"],
                "cursor": token,
                "fresh_cursor": True,
            }
        )
        return value


class _SeamHash(str):
    def __new__(cls, error, trace, identity):
        value = super().__new__(cls, "jobs.checkpoints")
        value.error = error
        value.trace = trace
        value.identity = identity
        return value

    def __hash__(self):
        self.trace.extend(
            [
                {"op": "component.__hash__.enter", "phase": "actual_public_call_only"},
                {"op": "component.__hash__.raise", "identity": self.identity},
            ]
        )
        raise self.error


def _seam_anchor():
    raw = (Path(__file__).resolve().parents[1] / "fixtures/g09_schema_v1.json").read_bytes()
    assert len(raw) == 306337
    assert hashlib.sha256(raw).hexdigest() == (
        "8b3611904a5db6371d2ebef831f7477a9cd8fa2c6b13ad55f0774417911dedbb"
    )
    anchor = json.loads(raw)["components"]["jobs.checkpoints"]
    assert anchor["model"] == _SEAM_HAND["anchor"]["model"]
    assert anchor["expected_wire_utf8"] == _SEAM_HAND["anchor"]["expected_wire_utf8"]
    assert anchor["expected_byte_length"] == 490
    assert anchor["expected_fingerprint"] == _SEAM_HAND["anchor"]["expected_fingerprint"]
    return anchor


def _seam_errors(spec):
    classes = {
        "sqlite3.OperationalError": sqlite3.OperationalError,
        "sqlite3.DatabaseError": sqlite3.DatabaseError,
        "builtins.RuntimeError": RuntimeError,
        "builtins.ValueError": ValueError,
        "builtins.KeyboardInterrupt": KeyboardInterrupt,
    }
    errors = {}
    for symbol, expected in spec["exception_objects_spec_only"].items():
        if symbol not in {"E", "C"}:
            continue
        value = classes[expected["exact_class"]](*expected["args"])
        assert value.__cause__ is None and value.__context__ is None
        assert value.__suppress_context__ is False
        errors[symbol] = value
    return errors


def _seam_error_token(error, errors, key):
    for symbol, value in errors.items():
        if error is value:
            return key + "|" + symbol
    if type(error) is ValueError:
        return key + ("|PUBLIC_CLOSED" if error.__suppress_context__ else "|SHAPE")
    return key + "|UNEXPECTED_CAPTURED"


def _seam_run_route(spec):
    anchor = _seam_anchor()
    errors = _seam_errors(spec)
    fake = _SeamConnection(spec, errors)
    _SEAM_LIVE.append((fake, anchor["model"], errors))
    name = spec["api_name_future_private_unimplemented"].rsplit(".", 1)[-1]
    function = getattr(s, name)
    actual = inspect.unwrap(function)
    assert actual.__globals__ is vars(s) and actual.__module__ == "recoryn.schema"
    assert actual.__qualname__ == name
    assert Path(actual.__code__.co_filename).resolve() == Path(s.__file__).resolve()
    record = {
        "route_id": spec["route_id"],
        "function": name,
        "actual_file": actual.__code__.co_filename,
        "actual_line": actual.__code__.co_firstlineno,
        "globals_schema": actual.__globals__ is vars(s),
        "trace": fake.trace,
        "fresh_error_ids": {k: id(v) for k, v in errors.items()},
        "IO": [],
    }
    route = spec["route"]
    if route == "private":
        args = (fake, anchor["model"])
    elif route == "public":
        component = spec["component_input"]
        if spec["route_id"].startswith("EXPECTED_OUTSIDE|"):
            component = _SeamHash(
                errors["E"], fake.trace, spec["exception_objects_spec_only"]["E"]["identity"]
            )
        args = (fake, component)
    elif route == "_read":
        args = (fake, spec["program"][0]["sql"])
    elif route == "_index_keys":
        args = (fake, "sqlite_autoindex_job_checkpoints_1")
    else:
        assert route == "_verify_table"
        args = (fake, anchor["model"]["objects"][0])
    value = None
    error = None
    with _management_no_io(record["IO"]):
        try:
            value = function(*args)
        except (Exception, KeyboardInterrupt) as caught:
            error = caught
    record["fake_id"] = id(fake)
    record["model_id"] = id(anchor["model"])
    record["cursor_ids"] = [id(cursor) for cursor in fake.cursors]
    outcome = spec["outcome"]
    record["returned_type"] = type(value).__name__
    record["returned_bytes"] = len(value) if type(value) is bytes else None
    record["actual_error"] = type(error).__name__ if error is not None else None
    if error is not None:
        token = _seam_error_token(error, errors, spec["route_id"])
        full_class = ("sqlite3." if isinstance(error, sqlite3.Error) else "builtins.") + type(
            error
        ).__name__
        fake.trace.append({"op": "route.raise", "identity": token, "exact_class": full_class})
        record["error_identity"] = token
    elif type(value) is bytes:
        fake.trace.append(
            {
                "op": "route.return",
                "kind": "wire",
                "bytes": len(value),
                "fingerprint": "recoryn-shape-v1:" + hashlib.sha256(value).hexdigest(),
            }
        )
    elif type(value) is list:
        fake.trace.append(
            {"op": "route.return", "kind": "rows", "rows": [list(row) for row in value]}
        )
    else:
        fake.trace.append(
            {"op": "route.return", "kind": "unexpected", "type": type(value).__name__}
        )
    _SEAM_OBS.append(record)
    assert record["IO"] == [], "SEAM_ACTUAL_CALL_IO_ZERO"
    if outcome["kind"] == "exception":
        expected = outcome["error"]
        symbol = expected["identity"].rsplit("|", 1)[-1]
        if outcome["identity_assertion_required"]:
            assert error is errors[symbol], "SEAM_ORIGINAL_ERROR_IDENTITY_AFTER_ACTUAL_CALL"
        else:
            assert type(error) is ValueError, "SEAM_CLOSED_VALUEERROR_AFTER_ACTUAL_CALL"
        assert type(error).__name__ == expected["exact_class"].rsplit(".", 1)[-1]
        assert error.args == tuple(expected["args"])
        assert str(error) == expected["str"] and repr(error) == expected["repr"]
        assert (
            error.__cause__ is None
            and error.__suppress_context__ is expected["__suppress_context__"]
        )
        context = expected["__context__"]
        assert error.__context__ is (
            None if context is None else errors[context.rsplit("|", 1)[-1]]
        )
        if symbol == "PUBLIC_CLOSED" and error.__context__ is errors.get("C") and "E" in errors:
            assert errors["C"].__context__ is errors["E"]
        assert value is None, "SEAM_ERROR_MUST_NOT_RETURN_FINAL_WIRE"
    elif outcome["kind"] == "wire":
        assert error is None, "SEAM_NORMAL_WIRE_MUST_RETURN"
        assert type(value) is bytes and value == anchor["expected_wire_utf8"].encode("utf8")
        assert len(value) == 490
        assert (
            "recoryn-shape-v1:" + hashlib.sha256(value).hexdigest()
            == anchor["expected_fingerprint"]
        )
    else:
        assert error is None and type(value) is list and value == [(7,)]
        assert all(type(row) is tuple for row in value)
    counts = {op: sum(row["op"] == op for row in fake.trace) for op in spec["trace_counts"]}
    assert counts == spec["trace_counts"], "SEAM_CLOSE_ATTEMPT_AND_RETURN_COUNTS"
    assert fake.trace == spec["trace_oracle"], "SEAM_EXACT_HAND_TRACE_AFTER_ACTUAL_CALL"


@pytest.mark.unit
@pytest.mark.parametrize("label", _SEAM_LABELS, ids=_SEAM_LABELS)
def test_private_schema_read_error_seam(label):
    routes = [row for row in _SEAM_HAND["routes"] if row["route_id"].split("|", 1)[0] == label]
    assert len(routes) == (1 if label in _SEAM_HAND["single_labels"] else 2)
    for row in routes:
        _seam_run_route(row)


@pytest.mark.unit
def test_private_schema_read_error_seam_literal_audit():
    assert hashlib.sha256(_SEAM_LITERAL_JSON.encode("utf8")).hexdigest() == _SEAM_LITERAL_SHA
    assert _SEAM_HAND["labels"] == list(_SEAM_LABELS)
    assert len(_SEAM_LABELS) == len(set(_SEAM_LABELS)) == 20
    routes = _SEAM_HAND["routes"]
    assert len(routes) == len({row["route_id"] for row in routes}) == 35
    assert len(_SEAM_HAND["program"]) == 7
    assert len(_SEAM_HAND["single_labels"]) == 5
    _seam_anchor()
