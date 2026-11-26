"""Twenty fixed S1 cases: hand/source DDL against independent versioned bytes."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

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
