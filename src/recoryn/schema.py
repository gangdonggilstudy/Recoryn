"""Component-local static SQL descriptions, without connection ownership or admission."""

from __future__ import annotations

import json
import re
import sqlite3
import types as _mc_types
from dataclasses import dataclass as _mc_dataclass
from dataclasses import fields as _mc_fields
from enum import Enum as _mgmt_Enum
from functools import cache as _mc_cache
from functools import lru_cache
from typing import Any
from typing import Literal as _mc_Literal
from typing import TypeAlias as _mgmt_TypeAlias
from typing import cast as _mc_cast
from typing import get_args as _mc_get_args
from typing import get_origin as _mc_get_origin
from typing import get_type_hints as _mc_get_type_hints

_CATALOG: dict[str, tuple[int, str]] = {
    "library.core": (
        1,
        "CREATE TABLE IF NOT EXISTS sessions (\n                    session_id TEXT PRIMARY KEY, state TEXT NOT NULL, state_version INTEGER NOT NULL,\n                    generation INTEGER NOT NULL DEFAULT 0,\n                    manifest_sync_pending INTEGER NOT NULL DEFAULT 1,\n                    finalized_chunks TEXT, capture_health TEXT NOT NULL DEFAULT '{}'\n                );\nCREATE TABLE IF NOT EXISTS chunks (\n                    chunk_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,\n                    relative_path TEXT UNIQUE NOT NULL, descriptor TEXT NOT NULL,\n                    FOREIGN KEY(session_id) REFERENCES sessions(session_id)\n                );\nCREATE TABLE IF NOT EXISTS storage_events (\n                    event_id INTEGER PRIMARY KEY, session_id TEXT NOT NULL,\n                    kind TEXT NOT NULL, state_version INTEGER NOT NULL\n                );\nCREATE TABLE IF NOT EXISTS deleted_sessions (\n                    session_id TEXT PRIMARY KEY, generation INTEGER NOT NULL,\n                    status TEXT NOT NULL\n                );",
    ),
    "storage.projection": (
        1,
        "CREATE TABLE IF NOT EXISTS storage_visible_sessions (\n                    session_id TEXT PRIMARY KEY,\n                    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE\n                );\nCREATE TABLE IF NOT EXISTS storage_pending_deletions (\n                    session_id TEXT PRIMARY KEY\n                );\nCREATE TABLE IF NOT EXISTS storage_catalog_meta (\n                    singleton INTEGER PRIMARY KEY CHECK(singleton=1), version INTEGER NOT NULL\n                );\nCREATE TRIGGER IF NOT EXISTS storage_catalog_insert AFTER INSERT ON sessions\n                BEGIN\n                    UPDATE storage_catalog_meta SET version=version+1 WHERE singleton=1;\n                END;\nCREATE TRIGGER IF NOT EXISTS storage_catalog_change\n                AFTER UPDATE OF state,state_version,generation ON sessions\n                WHEN OLD.state!=NEW.state OR OLD.state_version!=NEW.state_version OR OLD.generation!=NEW.generation\n                BEGIN\n                    UPDATE storage_catalog_meta SET version=version+1 WHERE singleton=1;\n                END;\nCREATE TRIGGER IF NOT EXISTS storage_catalog_delete AFTER DELETE ON sessions\n                BEGIN\n                    UPDATE storage_catalog_meta SET version=version+1 WHERE singleton=1;\n                END;\nCREATE TRIGGER IF NOT EXISTS storage_visible_insert AFTER INSERT ON sessions\n                WHEN NOT EXISTS(SELECT 1 FROM deleted_sessions WHERE session_id=NEW.session_id)\n                BEGIN\n                    INSERT OR IGNORE INTO storage_visible_sessions VALUES(NEW.session_id);\n                END;\nCREATE TRIGGER IF NOT EXISTS storage_visible_delete AFTER INSERT ON deleted_sessions\n                BEGIN\n                    DELETE FROM storage_visible_sessions WHERE session_id=NEW.session_id;\n                    INSERT OR IGNORE INTO storage_pending_deletions VALUES(NEW.session_id);\n                END;",
    ),
    "capture.health": (
        2,
        "CREATE TABLE IF NOT EXISTS capture_health_runs (\n                    session_id TEXT NOT NULL, capture_run_id TEXT NOT NULL,\n                    schema_version INTEGER NOT NULL, health_version INTEGER NOT NULL,\n                    checkpoint_seq INTEGER NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL,\n                    PRIMARY KEY(session_id,capture_run_id),\n                    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE\n                );\nCREATE TABLE IF NOT EXISTS capture_health_tracks (\n                    session_id TEXT NOT NULL, capture_run_id TEXT NOT NULL,\n                    track_id TEXT NOT NULL, epoch_id TEXT NOT NULL, payload TEXT NOT NULL,\n                    PRIMARY KEY(session_id,capture_run_id,track_id,epoch_id),\n                    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE,\n                    FOREIGN KEY(session_id,capture_run_id) REFERENCES capture_health_runs(session_id,capture_run_id) ON DELETE CASCADE\n                );\nCREATE TABLE IF NOT EXISTS capture_health_events (\n                    session_id TEXT NOT NULL, event_id TEXT NOT NULL,\n                    capture_run_id TEXT NOT NULL, ordinal INTEGER NOT NULL, payload TEXT NOT NULL,\n                    gap_id TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL DEFAULT '', digest TEXT NOT NULL DEFAULT '',\n                    PRIMARY KEY(session_id,event_id),\n                    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE,\n                    FOREIGN KEY(session_id,capture_run_id) REFERENCES capture_health_runs(session_id,capture_run_id) ON DELETE CASCADE\n                );\nCREATE INDEX IF NOT EXISTS capture_health_event_order ON capture_health_events(session_id,capture_run_id,ordinal,event_id);\nCREATE UNIQUE INDEX IF NOT EXISTS capture_health_gap_phase ON capture_health_events(session_id,gap_id,kind);",
    ),
    "jobs.core": (
        1,
        "CREATE TABLE IF NOT EXISTS jobs (\n                    job_id TEXT PRIMARY KEY, kind TEXT NOT NULL, input_key TEXT NOT NULL,\n                    state TEXT NOT NULL, fence INTEGER NOT NULL DEFAULT 0,\n                    attempt_count INTEGER NOT NULL DEFAULT 0, attempt_id TEXT, owner TEXT,\n                    result_ref TEXT, error_code TEXT, blocked_reason TEXT,\n                    cancel_requested INTEGER NOT NULL DEFAULT 0,\n                    state_version INTEGER NOT NULL DEFAULT 0\n                );\nCREATE UNIQUE INDEX IF NOT EXISTS jobs_dedup\n                    ON jobs(kind, input_key) WHERE state NOT IN ('FAILED', 'CANCELLED');\nCREATE TABLE IF NOT EXISTS attempts (\n                    attempt_id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(job_id),\n                    attempt_no INTEGER NOT NULL, state TEXT NOT NULL, fence INTEGER NOT NULL,\n                    owner TEXT NOT NULL, result_ref TEXT, error_code TEXT,\n                    UNIQUE(job_id, attempt_no)\n                );\nCREATE TABLE IF NOT EXISTS events (\n                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,\n                    job_id TEXT NOT NULL REFERENCES jobs(job_id),\n                    attempt_id TEXT, state TEXT NOT NULL, fence INTEGER NOT NULL,\n                    state_version INTEGER NOT NULL\n                );\nCREATE TABLE IF NOT EXISTS job_sessions (\n                    job_id TEXT PRIMARY KEY REFERENCES jobs(job_id), session_id TEXT NOT NULL\n                );\nCREATE INDEX IF NOT EXISTS job_session_lookup ON job_sessions(session_id);\nCREATE TABLE IF NOT EXISTS job_local_readers (\n                    job_id TEXT PRIMARY KEY REFERENCES jobs(job_id),\n                    attempt_id TEXT NOT NULL REFERENCES attempts(attempt_id),\n                    fence INTEGER NOT NULL CHECK(fence > 0),\n                    active INTEGER NOT NULL CHECK(active IN (0,1))\n                );\nCREATE TABLE IF NOT EXISTS job_remote_intents (\n                    attempt_id TEXT NOT NULL REFERENCES attempts(attempt_id),\n                    reservation_id TEXT NOT NULL, job_id TEXT NOT NULL REFERENCES jobs(job_id),\n                    fence INTEGER NOT NULL CHECK(fence > 0),\n                    PRIMARY KEY(attempt_id,reservation_id)\n                );",
    ),
    "jobs.receipts": (
        1,
        "CREATE TABLE IF NOT EXISTS job_create_receipts (\n                    request_job_id TEXT PRIMARY KEY,\n                    job_id TEXT NOT NULL REFERENCES jobs(job_id)\n                );",
    ),
    "jobs.checkpoints": (
        1,
        "CREATE TABLE IF NOT EXISTS job_checkpoints (job_id TEXT NOT NULL REFERENCES jobs(job_id), attempt_id TEXT NOT NULL, result_ref TEXT NOT NULL, UNIQUE(job_id,result_ref));",
    ),
    "content.core": (
        1,
        "CREATE TABLE IF NOT EXISTS content_revisions (\n                        revision_id TEXT PRIMARY KEY,\n                        session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,\n                        revision_type TEXT NOT NULL, body TEXT NOT NULL, sha256 TEXT NOT NULL\n                    );\nCREATE INDEX IF NOT EXISTS content_session ON content_revisions(session_id);\nCREATE TABLE IF NOT EXISTS content_selections (\n                        session_id TEXT PRIMARY KEY REFERENCES sessions(session_id) ON DELETE CASCADE,\n                        transcript_id TEXT, summary_id TEXT,\n                        transcript_version INTEGER NOT NULL DEFAULT 0,\n                        summary_version INTEGER NOT NULL DEFAULT 0\n                    );\nCREATE TABLE IF NOT EXISTS content_events (\n                        event_id INTEGER PRIMARY KEY,\n                        session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,\n                        revision_id TEXT NOT NULL, revision_type TEXT NOT NULL,\n                        selected INTEGER NOT NULL\n                    );\nCREATE TRIGGER IF NOT EXISTS content_revision_immutable\n                    BEFORE UPDATE ON content_revisions\n                    BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_CONTENT_REVISION'); END;",
    ),
    "content.summary_requests": (
        1,
        "CREATE TABLE IF NOT EXISTS content_summary_requests (\n                        session_id TEXT PRIMARY KEY REFERENCES sessions(session_id) ON DELETE CASCADE,\n                        settings_key TEXT NOT NULL,\n                        request_count INTEGER NOT NULL DEFAULT 1\n                    );",
    ),
    "security.consent": (
        2,
        "CREATE TABLE IF NOT EXISTS security_execution(id INTEGER PRIMARY KEY, generation TEXT);\nCREATE TABLE IF NOT EXISTS security_sessions(session_id TEXT PRIMARY KEY, generation INTEGER, revoked INTEGER);\nCREATE TABLE security_local_endpoints(endpoint TEXT PRIMARY KEY, generation TEXT, model_digest TEXT, expires REAL NOT NULL DEFAULT 0);\nCREATE TABLE IF NOT EXISTS security_consent_meta(id INTEGER PRIMARY KEY CHECK(id=1), schema_version INTEGER NOT NULL, policy_version INTEGER NOT NULL);\nCREATE TABLE IF NOT EXISTS security_grants_v2(\n                provider TEXT NOT NULL, endpoint TEXT NOT NULL, capability TEXT NOT NULL,\n                data_type TEXT NOT NULL, scope_kind TEXT NOT NULL, scope_id TEXT NOT NULL,\n                policy_version INTEGER NOT NULL CHECK(policy_version>0),\n                grant_id TEXT NOT NULL UNIQUE, generation TEXT NOT NULL,\n                epoch INTEGER NOT NULL CHECK(epoch>=0), issued_at REAL NOT NULL,\n                expires REAL NOT NULL, allowed INTEGER NOT NULL CHECK(allowed IN (0,1)),\n                revoked_at REAL,\n                PRIMARY KEY(provider,endpoint,capability,data_type,scope_kind,scope_id,policy_version),\n                CHECK((scope_kind='session' AND length(scope_id)>0) OR (scope_kind='library' AND scope_id=''))\n            );",
    ),
    "security.cost.legacy": (
        1,
        "CREATE TABLE IF NOT EXISTS security_cost_meta(id INTEGER PRIMARY KEY, revision INTEGER);\nCREATE TABLE IF NOT EXISTS security_cost_accounts(provider TEXT PRIMARY KEY, amount_limit INTEGER);\nCREATE TABLE IF NOT EXISTS security_cost_requests(\n                        reservation_id TEXT PRIMARY KEY, provider TEXT, request_id TEXT,\n                        amount INTEGER, actual INTEGER, state TEXT,\n                        UNIQUE(provider,request_id));",
    ),
    "security.cost": (
        2,
        "CREATE TABLE security_cost_accounts_v2(\n                    account_id TEXT PRIMARY KEY, provider TEXT NOT NULL, currency TEXT NOT NULL,\n                    period_start_utc INTEGER NOT NULL CHECK(period_start_utc>=0),\n                    period_end_utc INTEGER NOT NULL CHECK(period_end_utc>period_start_utc),\n                    policy_version INTEGER NOT NULL CHECK(policy_version>0),\n                    amount_limit INTEGER NOT NULL CHECK(amount_limit>=0),\n                    blocked INTEGER NOT NULL DEFAULT 0 CHECK(blocked IN (0,1)),\n                    UNIQUE(provider,currency,period_start_utc,period_end_utc));\nCREATE TABLE security_cost_requests_v2(\n                    reservation_id TEXT PRIMARY KEY, provider TEXT NOT NULL, request_id TEXT NOT NULL,\n                    account_id TEXT NOT NULL REFERENCES security_cost_accounts_v2(account_id),\n                    reserved_amount INTEGER NOT NULL CHECK(reserved_amount>=0),\n                    actual INTEGER CHECK(actual>=0), state TEXT NOT NULL CHECK(state IN ('RESERVED','UNKNOWN','SETTLED','RELEASED')),\n                    quote_kind TEXT NOT NULL CHECK(quote_kind IN ('VERIFIED','USER_CAP','LEGACY_UNSCOPED')),\n                    model_revision TEXT, profile_id TEXT, endpoint_digest TEXT, body_sha256 TEXT,\n                    byte_length INTEGER CHECK(byte_length>0), input_upper INTEGER CHECK(input_upper>=0),\n                    output_upper INTEGER CHECK(output_upper>=0), price_as_of_utc INTEGER,\n                    valid_until_utc INTEGER, catalog_digest TEXT, request_fingerprint TEXT NOT NULL,\n                    request_json TEXT, quote_json TEXT, policy_json TEXT, dispatch_id TEXT,\n                    UNIQUE(provider,request_id),\n                    CHECK(quote_kind!='VERIFIED' OR (price_as_of_utc IS NOT NULL AND valid_until_utc IS NOT NULL AND input_upper IS NOT NULL AND output_upper IS NOT NULL)),\n                    CHECK(quote_kind='LEGACY_UNSCOPED' OR (body_sha256 IS NOT NULL AND byte_length IS NOT NULL AND quote_json IS NOT NULL AND policy_json IS NOT NULL AND request_json IS NOT NULL)));\nCREATE TABLE security_cost_usage_events(\n                    reservation_id TEXT NOT NULL REFERENCES security_cost_requests_v2(reservation_id),\n                    source TEXT NOT NULL, event_id TEXT NOT NULL, version INTEGER NOT NULL CHECK(version>0),\n                    kind TEXT NOT NULL CHECK(kind IN ('provisional','final')), currency TEXT NOT NULL,\n                    period_id TEXT NOT NULL, amount INTEGER NOT NULL CHECK(amount>=0), payload_digest TEXT NOT NULL,\n                    PRIMARY KEY(reservation_id,source,event_id));\nCREATE TABLE security_cost_meta_v2(\n                    id INTEGER PRIMARY KEY CHECK(id=1), schema_version INTEGER NOT NULL CHECK(schema_version=2),\n                    revision INTEGER NOT NULL, witness_protocol_version INTEGER NOT NULL CHECK(witness_protocol_version=2),\n                    predecessor_v1_state_digest TEXT NOT NULL, migration_state TEXT NOT NULL,\n                    clock_high_water_utc REAL NOT NULL, adopted_providers TEXT NOT NULL,\n                    clock_reset_audit TEXT NOT NULL DEFAULT '[]');",
    ),
    "g09.management": (
        1,
        "CREATE TABLE recoryn_schema_components(component TEXT PRIMARY KEY NOT NULL, version INTEGER NOT NULL CHECK(version>0), fingerprint TEXT NOT NULL, profile TEXT NOT NULL);\nCREATE TABLE recoryn_maintenance(singleton INTEGER PRIMARY KEY CHECK(singleton=1), library_instance_id TEXT NOT NULL, operation_id TEXT, epoch INTEGER NOT NULL CHECK(epoch>=0), commit_state TEXT NOT NULL CHECK(commit_state IN ('NORMAL','DB_COMMITTED')), input_digest TEXT, CHECK((commit_state='NORMAL' AND operation_id IS NULL AND epoch=0 AND input_digest IS NULL) OR (commit_state='DB_COMMITTED' AND operation_id IS NOT NULL AND epoch>0 AND input_digest IS NOT NULL)));",
    ),
}
_KEYWORDS = frozenset(
    "CREATE TABLE INDEX UNIQUE TRIGGER IF NOT EXISTS PRIMARY KEY FOREIGN REFERENCES INTEGER TEXT REAL BLOB NOT NULL DEFAULT CHECK COLLATE AUTOINCREMENT ASC DESC ON UPDATE DELETE INSERT AFTER BEFORE OF WHEN BEGIN END SELECT RAISE ABORT SET WHERE OR AND INTO VALUES IGNORE FROM IN IS OLD NEW CASCADE RESTRICT NO ACTION MATCH NONE WITHOUT ROWID STRICT FOR EACH ROW".split()
)
_IDENTIFIERS = frozenset(
    (
        word.lower()
        for _, ddl in _CATALOG.values()
        for word in re.findall("[A-Za-z_][A-Za-z0-9_]*", ddl)
        if word.upper() not in _KEYWORDS
    )
)
_COLLATIONS = frozenset({"BINARY", "NOCASE", "RTRIM"})
_TOKEN = re.compile(
    "\\s+|--[^\\n]*(?:\\n|$)|/\\*[\\s\\S]*?\\*/|'(?:''|[^'])*'|\\\"(?:\\\"\\\"|[^\\\"])*\\\"|`(?:``|[^`])*`|\\[[^\\]]*\\]|[A-Za-z_][A-Za-z0-9_]*|[0-9]+|!=|>=|<=|<>|==|[(),.;=+*/%<>-]"
)
_Token = tuple[str, str]
_Shape = dict[str, Any]


def _invalid() -> ValueError:
    return ValueError("Unsupported component shape")


def _tokens(sql: str) -> list[_Token]:
    result: list[_Token] = []
    offset = 0
    while offset < len(sql):
        match = _TOKEN.match(sql, offset)
        if match is None:
            raise _invalid()
        word = match.group()
        offset = match.end()
        if word.isspace() or word.startswith(("--", "/*")):
            continue
        if word.startswith("'"):
            value = word[1:-1].replace("''", "'")
            if any(55296 <= ord(char) <= 57343 for char in value):
                raise _invalid()
            result.append(("s", value))
        elif word[0] in '"`[':
            value = word[1:-1]
            if word[0] != "[":
                value = value.replace(word[0] * 2, word[0])
            if value.lower() not in _IDENTIFIERS or not value.isascii():
                raise _invalid()
            result.append(("i", value.lower()))
        elif word[0].isalpha() or word[0] == "_":
            if word.upper() in _KEYWORDS:
                result.append(("k", word.upper()))
            elif word.upper() in _COLLATIONS:
                result.append(("i", word.lower()))
            elif word.lower() in _IDENTIFIERS:
                result.append(("i", word.lower()))
            else:
                raise _invalid()
        elif word.isdecimal():
            if not re.fullmatch("0|[1-9][0-9]*", word):
                raise _invalid()
            result.append(("n", word))
        else:
            result.append(("p", word))
    return result


class _Cursor:
    def __init__(self, tokens: list[_Token]) -> None:
        self.tokens = tokens
        self.position = 0

    def __bool__(self) -> bool:
        return self.position < len(self.tokens)

    def peek(self) -> str:
        if not self:
            return ""
        kind, value = self.tokens[self.position]
        return value if kind in {"k", "p"} else ""

    def pop(self) -> _Token:
        if not self:
            raise _invalid()
        token = self.tokens[self.position]
        self.position += 1
        return token

    def take(self, value: str) -> bool:
        if self.peek() == value:
            self.pop()
            return True
        return False

    def need(self, value: str) -> None:
        if not self.take(value):
            raise _invalid()

    def name(self) -> str:
        kind, value = self.pop()
        if kind != "i":
            raise _invalid()
        return value

    def group(self) -> list[_Token]:
        self.need("(")
        start = self.position
        depth = 1
        while self:
            kind, value = self.pop()
            if kind == "p" and value == "(":
                depth += 1
            elif kind == "p" and value == ")":
                depth -= 1
                if depth == 0:
                    return self.tokens[start : self.position - 1]
        raise _invalid()


def _parts(tokens: list[_Token], separator: str = ",") -> list[list[_Token]]:
    result: list[list[_Token]] = []
    start = depth = 0
    for index, (kind, value) in enumerate(tokens):
        if kind != "p":
            continue
        if value == "(":
            depth += 1
        elif value == ")":
            depth -= 1
        elif value == separator and depth == 0:
            result.append(tokens[start:index])
            start = index + 1
        if depth < 0:
            raise _invalid()
    if depth:
        raise _invalid()
    result.append(tokens[start:])
    if any(not part for part in result):
        raise _invalid()
    return result


def _wire(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def _keys(tokens: list[_Token], columns: dict[str, list[Any]]) -> list[list[str]]:
    result = []
    for part in _parts(tokens):
        cursor = _Cursor(part)
        name = cursor.name()
        collation = str(columns[name][6]) if name in columns else "BINARY"
        if cursor.take("COLLATE"):
            collation = cursor.name().upper()
            if collation not in _COLLATIONS:
                raise _invalid()
        order = cursor.pop()[1] if cursor.peek() in {"ASC", "DESC"} else "ASC"
        if cursor:
            raise _invalid()
        result.append([name, order, collation])
    return result


def _foreign(cursor: _Cursor, names: list[str]) -> list[Any]:
    cursor.need("REFERENCES")
    target = cursor.name()
    target_names = [_Cursor(part).name() for part in _parts(cursor.group())]
    if len(target_names) != len(names):
        raise _invalid()
    update = delete = "NO ACTION"
    while cursor.peek() == "ON":
        cursor.pop()
        action_kind = cursor.pop()[1]
        if action_kind not in {"UPDATE", "DELETE"}:
            raise _invalid()
        action = cursor.pop()[1]
        if action in {"SET", "NO"}:
            action += " " + cursor.pop()[1]
        if action not in {"NO ACTION", "CASCADE", "RESTRICT", "SET NULL", "SET DEFAULT"}:
            raise _invalid()
        if action_kind == "UPDATE":
            update = action
        else:
            delete = action
    match = "NONE"
    if cursor.take("MATCH"):
        cursor.need("NONE")
    return [names, target, target_names, update, delete, match]


def _table(cursor: _Cursor, name: str) -> _Shape:
    clauses = _parts(cursor.group())
    columns: dict[str, list[Any]] = {}
    constraints: list[tuple[str, list[_Token]]] = []
    checks: list[list[_Token]] = []
    foreign: list[list[Any]] = []
    inline_primary_desc = False
    autoincrement = False
    for clause in clauses:
        item = _Cursor(clause)
        if item.peek() in {"PRIMARY", "UNIQUE", "CHECK", "FOREIGN"}:
            kind = item.pop()[1]
            if kind == "PRIMARY":
                item.need("KEY")
            elif kind == "FOREIGN":
                item.need("KEY")
            group = item.group()
            if kind == "CHECK":
                checks.append(group)
            elif kind == "FOREIGN":
                source = [_Cursor(part).name() for part in _parts(group)]
                foreign.append(_foreign(item, source))
            else:
                constraints.append(("pk" if kind == "PRIMARY" else "u", group))
            if item:
                raise _invalid()
            continue
        column_name = item.name()
        column_type = item.pop()[1]
        if column_type not in {"INTEGER", "TEXT", "REAL", "BLOB"} or column_name in columns:
            raise _invalid()
        column: list[Any] = [column_name, column_type, False, None, 0, 0, "BINARY"]
        columns[column_name] = column
        while item:
            if item.take("NOT"):
                item.need("NULL")
                column[2] = True
            elif item.take("PRIMARY"):
                item.need("KEY")
                order = item.pop()[1] if item.peek() in {"ASC", "DESC"} else "ASC"
                inline_primary_desc = order == "DESC"
                autoincrement = item.take("AUTOINCREMENT")
                constraints.append(("pk", [("i", column_name), ("k", order)]))
            elif item.take("UNIQUE"):
                constraints.append(("u", [("i", column_name)]))
            elif item.take("CHECK"):
                checks.append(item.group())
            elif item.take("DEFAULT"):
                if item.peek() == "(":
                    column[3] = [("p", "("), *item.group(), ("p", ")")]
                else:
                    token = item.pop()
                    if token[0] not in {"s", "n"} and token != ("k", "NULL"):
                        raise _invalid()
                    column[3] = [token]
            elif item.peek() == "REFERENCES":
                foreign.append(_foreign(item, [column_name]))
            elif item.take("COLLATE"):
                collation = item.name().upper()
                if collation not in _COLLATIONS:
                    raise _invalid()
                column[6] = collation
            else:
                raise _invalid()
    rowid = True
    strict = False
    while cursor.peek() in {"WITHOUT", "STRICT"}:
        if cursor.take("WITHOUT"):
            cursor.need("ROWID")
            rowid = False
        else:
            cursor.need("STRICT")
            strict = True
        cursor.take(",")
    indexes: list[list[Any]] = []
    primary_count = 0
    for kind, group in constraints:
        keys = _keys(group, columns)
        if any(key[0] not in columns for key in keys):
            raise _invalid()
        if kind == "pk":
            primary_count += 1
            for ordinal, key in enumerate(keys, 1):
                columns[key[0]][4] = ordinal
            integer_alias = (
                rowid
                and len(keys) == 1
                and (columns[keys[0][0]][1] == "INTEGER")
                and (not inline_primary_desc)
            )
            if integer_alias:
                continue
        indexes.append([kind, keys])
    if primary_count > 1 or not columns:
        raise _invalid()
    return {
        "kind": "table",
        "name": name,
        "columns": list(columns.values()),
        "autoindexes": sorted(indexes, key=_wire),
        "checks": sorted(checks, key=_wire),
        "foreign_keys": sorted(foreign, key=_wire),
        "autoincrement": autoincrement,
        "rowid": rowid,
        "strict": strict,
    }


def _index(cursor: _Cursor, name: str, unique: bool, tables: dict[str, _Shape]) -> _Shape:
    cursor.need("ON")
    table = cursor.name()
    columns = {col[0]: col for col in tables.get(table, {}).get("columns", [])}
    keys = _keys(cursor.group(), columns)
    where: list[_Token] | None = None
    if cursor.take("WHERE"):
        where = []
        while cursor and cursor.peek() != ";":
            where.append(cursor.pop())
        if not where:
            raise _invalid()
    return {
        "kind": "index",
        "name": name,
        "table": table,
        "origin": "c",
        "keys": keys,
        "unique": unique,
        "where": where,
    }


def _trigger(cursor: _Cursor, name: str) -> _Shape:
    timing = cursor.pop()[1]
    event = cursor.pop()[1]
    if timing not in {"BEFORE", "AFTER"} or event not in {"UPDATE", "INSERT", "DELETE"}:
        raise _invalid()
    update_of = []
    if cursor.take("OF"):
        if event != "UPDATE":
            raise _invalid()
        update_of.append(cursor.name())
        while cursor.take(","):
            update_of.append(cursor.name())
    cursor.need("ON")
    table = cursor.name()
    if cursor.take("FOR"):
        cursor.need("EACH")
        cursor.need("ROW")
    when: list[_Token] | None = None
    if cursor.take("WHEN"):
        when = []
        while cursor and cursor.peek() != "BEGIN":
            when.append(cursor.pop())
        if not when:
            raise _invalid()
    cursor.need("BEGIN")
    body: list[list[_Token]] = []
    while cursor and cursor.peek() != "END":
        statement: list[_Token] = []
        while cursor and cursor.peek() != ";":
            statement.append(cursor.pop())
        cursor.need(";")
        if not statement or statement[0][1] not in {"SELECT", "UPDATE", "INSERT", "DELETE"}:
            raise _invalid()
        body.append(statement)
    cursor.need("END")
    if not body:
        raise _invalid()
    return {
        "kind": "trigger",
        "name": name,
        "table": table,
        "timing": timing,
        "event": event,
        "update_of": update_of,
        "when": when,
        "body": body,
    }


def _objects(sql: str, tables: dict[str, _Shape] | None = None) -> list[_Shape]:
    cursor = _Cursor(_tokens(sql))
    result = []
    known_tables = dict(tables or {})
    while cursor:
        cursor.need("CREATE")
        unique = cursor.take("UNIQUE")
        kind = cursor.pop()[1]
        if kind not in {"TABLE", "INDEX", "TRIGGER"} or (unique and kind != "INDEX"):
            raise _invalid()
        if cursor.take("IF"):
            cursor.need("NOT")
            cursor.need("EXISTS")
        name = cursor.name()
        if kind == "TABLE":
            obj = _table(cursor, name)
            known_tables[name] = obj
        elif kind == "INDEX":
            obj = _index(cursor, name, unique, known_tables)
        else:
            obj = _trigger(cursor, name)
        cursor.take(";")
        result.append(obj)
    return result


@lru_cache(maxsize=12)
def _expected(component: str) -> _Shape:
    if not isinstance(component, str) or component not in _CATALOG:
        raise _invalid()
    version, ddl = _CATALOG[component]
    return {
        "format": "recoryn-shape-v1",
        "component": component,
        "version": version,
        "objects": sorted(_objects(ddl), key=lambda obj: (obj["name"], obj["kind"])),
    }


def expected_shape_wire(component: str, version: int) -> bytes:
    """Return the fixed source-backed wire; do not read a database or test oracle."""
    model = _expected(component)
    if type(version) is not int or version != model["version"]:
        raise _invalid()
    return _wire(model)


def _read(connection: sqlite3.Connection, sql: str) -> list[tuple[Any, ...]]:
    cursor = connection.cursor()
    try:
        cursor.row_factory = None
        return cursor.execute(sql).fetchall()
    finally:
        cursor.close()


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _pragma_collation(value: object) -> str:
    if not isinstance(value, str) or value.upper() not in _COLLATIONS:
        raise _invalid()
    return value.upper()


def _pragma_default(tokens: list[_Token] | None) -> list[_Token] | None:
    if tokens and tokens[0] == ("p", "("):
        cursor = _Cursor(tokens)
        inner = cursor.group()
        if cursor:
            raise _invalid()
        return inner
    return tokens


def _index_keys(connection: sqlite3.Connection, name: str) -> list[list[str]]:
    keys = []
    for row in _read(connection, f"PRAGMA main.index_xinfo({_quote(name)})"):
        if row[5]:
            if row[1] < 0 or row[2] is None:
                raise _invalid()
            keys.append(
                [str(row[2]).lower(), "DESC" if row[3] else "ASC", _pragma_collation(row[4])]
            )
    return keys


def _verify_table(connection: sqlite3.Connection, obj: _Shape) -> None:
    name = obj["name"]
    info = _read(connection, f"PRAGMA main.table_xinfo({_quote(name)})")
    if len(info) != len(obj["columns"]):
        raise _invalid()
    indexed_primary = any(index[0] == "pk" for index in obj["autoindexes"])
    implicit_primary_nn = not obj["rowid"] or (obj["strict"] and indexed_primary)
    for actual, column in zip(info, obj["columns"], strict=True):
        nullable_flag = column[2] or (implicit_primary_nn and bool(column[4]))
        default = _tokens(actual[4]) if actual[4] is not None else None
        if (
            str(actual[1]).lower() != column[0]
            or str(actual[2]).upper() != column[1]
            or bool(actual[3]) != nullable_flag
            or (default != _pragma_default(column[3]))
            or (actual[5] != column[4])
            or (actual[6] != column[5])
        ):
            raise _invalid()
    actual_foreign: dict[int, list[Any]] = {}
    for row in _read(connection, f"PRAGMA main.foreign_key_list({_quote(name)})"):
        if row[0] not in actual_foreign:
            actual_foreign[row[0]] = [[], str(row[2]).lower(), [], row[5], row[6], row[7]]
        fk = actual_foreign[row[0]]
        fk[0].append(str(row[3]).lower())
        fk[2].append(str(row[4]).lower())
    if _wire(sorted(actual_foreign.values(), key=_wire)) != _wire(obj["foreign_keys"]):
        raise _invalid()
    autoindexes = []
    for row in _read(connection, f"PRAGMA main.index_list({_quote(name)})"):
        if row[3] not in {"pk", "u"}:
            continue
        if not re.fullmatch("sqlite_autoindex_" + re.escape(name) + "_[1-9][0-9]*", row[1], re.I):
            raise _invalid()
        autoindexes.append([row[3], _index_keys(connection, row[1])])
    if _wire(sorted(autoindexes, key=_wire)) != _wire(obj["autoindexes"]):
        raise _invalid()


def _component_shape_wire_read(connection: sqlite3.Connection, expected: _Shape) -> bytes:
    stamp = _read(connection, "PRAGMA main.schema_version")
    rows = _read(connection, "SELECT type,name,tbl_name,sql FROM main.sqlite_schema")
    required = {obj["name"]: obj for obj in expected["objects"]}
    all_objects = {obj["name"]: obj for name in _CATALOG for obj in _expected(name)["objects"]}
    by_name = {str(row[1]).lower(): row for row in rows}
    selected_tables = {name for name, obj in required.items() if obj["kind"] == "table"}
    for kind, raw_name, raw_table, _ in rows:
        name, table = (str(raw_name).lower(), str(raw_table).lower())
        if table in selected_tables and kind in {"index", "trigger"}:
            if name.startswith("sqlite_autoindex_") and kind == "index":
                continue
            known = all_objects.get(name)
            if known is None or known.get("table") != table or known["kind"] != kind:
                raise _invalid()
    observed: dict[str, _Shape] = {}
    for name, obj in required.items():
        row = by_name.get(name)
        if row is None or row[0] != obj["kind"] or (not isinstance(row[3], str)):
            raise _invalid()
        if obj["kind"] == "table":
            parsed = _objects(row[3])
            if len(parsed) != 1 or parsed[0]["name"] != name:
                raise _invalid()
            observed[name] = parsed[0]
            _verify_table(connection, parsed[0])
    for name, obj in required.items():
        if obj["kind"] == "table":
            continue
        parsed = _objects(by_name[name][3], observed)
        if len(parsed) != 1 or parsed[0]["name"] != name or parsed[0]["table"] != obj["table"]:
            raise _invalid()
        observed[name] = parsed[0]
        if obj["kind"] == "index":
            info = _read(connection, f"PRAGMA main.index_list({_quote(obj['table'])})")
            found = [row for row in info if str(row[1]).lower() == name]
            if (
                len(found) != 1
                or bool(found[0][2]) != parsed[0]["unique"]
                or bool(found[0][4]) != (parsed[0]["where"] is not None)
                or (_index_keys(connection, name) != parsed[0]["keys"])
            ):
                raise _invalid()
    if stamp != _read(connection, "PRAGMA main.schema_version"):
        raise _invalid()
    return _wire(
        {**expected, "objects": sorted(observed.values(), key=lambda o: (o["name"], o["kind"]))}
    )


def component_shape_wire(connection: sqlite3.Connection, component: str) -> bytes:
    """Describe one component on a caller-owned connection using schema reads only.

    This is neither a whole-dataset profile check nor an admission/ownership proof.
    The caller retains connection, transaction and concurrency ownership.
    """
    expected = _expected(component)
    try:
        return _component_shape_wire_read(connection, expected)
    except sqlite3.Error:
        raise _invalid() from None


_mb_MAX_BYTES = 8388608
_mb_MAX_DEPTH = 16
_mb_ROLES = frozenset({"library", "jobs", "content", "consent", "consent1-legacy", "cost"})
_mb_PROFILES = frozenset(
    ["F2_J"]
    + ["F2_S_" + suffix for suffix in ("CONS", "COST1", "COST2", "CONS_COST1", "CONS_COST2")]
    + [
        "F2_" + library + suffix
        for library in ("L", "LJ", "LC", "LJC")
        for suffix in ("", "_CONS", "_COST1", "_COST2", "_CONS_COST1", "_CONS_COST2")
    ]
)


class SchemaWireError(ValueError):
    def __init__(self, kind: _mc_Literal["MALFORMED", "LIMIT_EXCEEDED"]) -> None:
        self.kind = (
            kind if type(kind) is str and kind in {"MALFORMED", "LIMIT_EXCEEDED"} else "MALFORMED"
        )
        super().__init__(self.kind)

    def __repr__(self) -> str:
        return f"SchemaWireError({self.kind})"


def _mb_bad() -> SchemaWireError:
    return SchemaWireError("MALFORMED")


@_mc_cache
def _mb_hints(cls: type[Any]) -> dict[str, Any]:
    return _mc_get_type_hints(cls)


def _mb_matches(value: object, annotation: Any) -> bool:
    origin, args = (_mc_get_origin(annotation), _mc_get_args(annotation))
    if origin is _mc_Literal:
        return any(type(value) is type(option) and value == option for option in args)
    if origin is _mc_types.UnionType:
        return any(_mb_matches(value, option) for option in args)
    if origin is tuple:
        return (
            type(value) is tuple
            and len(args) == 2
            and (args[1] is Ellipsis)
            and all(_mb_matches(item, args[0]) for item in value)
        )
    return type(value) is annotation


class _FrozenWireData:
    __slots__ = ()

    def __post_init__(self) -> None:
        for field in _mc_fields(self):  # type: ignore[arg-type]
            if not _mb_matches(
                getattr(self, field.name), _mb_hints(_mc_cast(Any, type(self)))[field.name]
            ):
                raise _mb_bad()


@_mc_dataclass(frozen=True, slots=True)
class ManagementIdentity(_FrozenWireData):
    kind: _mc_Literal["FILE", "DIR"]
    volume_hex: str
    file_id_hex: str


@_mc_dataclass(frozen=True, slots=True)
class BindingPrimary(_FrozenWireData):
    kind: _mc_Literal["LIBRARY_ROOT", "DB_PARENT"]
    anchor_identity: ManagementIdentity
    namespace_identity: ManagementIdentity
    catalog_id: str


@_mc_dataclass(frozen=True, slots=True)
class OperationRef(_FrozenWireData):
    operation_id: str
    plan_digest: str
    link_nonce: str


@_mc_dataclass(frozen=True, slots=True)
class HistoricalBinding(_FrozenWireData):
    name: str
    identity: ManagementIdentity
    retired_by: OperationRef


@_mc_dataclass(frozen=True, slots=True)
class CurrentBinding(_FrozenWireData):
    name: str
    identity: ManagementIdentity | None


@_mc_dataclass(frozen=True, slots=True)
class OperationGenesis(_FrozenWireData):
    kind: _mc_Literal["OPERATION"]
    operation_id: str
    plan_digest: str


@_mc_dataclass(frozen=True, slots=True)
class FreshBindingTarget(_FrozenWireData):
    db_id: str
    dataset_id: str
    anchor_identity: ManagementIdentity
    namespace_identity: ManagementIdentity
    name: str
    roles: tuple[str, ...]
    profile_id: str
    pre_identity: None


@_mc_dataclass(frozen=True, slots=True)
class FreshBindingLayout(_FrozenWireData):
    primary: BindingPrimary
    targets: tuple[FreshBindingTarget, ...]


@_mc_dataclass(frozen=True, slots=True)
class FreshGenesis(_FrozenWireData):
    kind: _mc_Literal["FRESH_INIT"]
    intent_id: str
    layout: FreshBindingLayout


@_mc_dataclass(frozen=True, slots=True)
class UncommittedFloor(_FrozenWireData):
    kind: _mc_Literal["UNCOMMITTED"]


@_mc_dataclass(frozen=True, slots=True)
class EpochCredit(_FrozenWireData):
    operation_id: str
    plan_digest: str
    sequence: int
    record_digest: str


@_mc_dataclass(frozen=True, slots=True)
class KnownEpochFloor(_FrozenWireData):
    kind: _mc_Literal["KNOWN"]
    value: int
    credits: tuple[EpochCredit, ...]


@_mc_dataclass(frozen=True, slots=True)
class BindingEntry(_FrozenWireData):
    db_id: str
    dataset_id: str
    state: _mc_Literal["PREPARED", "BOUND", "RETIRED"]
    current: CurrentBinding
    history: tuple[HistoricalBinding, ...]
    roles: tuple[str, ...]
    primary: BindingPrimary
    genesis: OperationGenesis | FreshGenesis
    operation_ref: OperationRef | None
    epoch_floor: UncommittedFloor | KnownEpochFloor


@_mc_dataclass(frozen=True, slots=True)
class BindingsDocument(_FrozenWireData):
    format: _mc_Literal["recoryn-management-bindings-v1"]
    version: int
    catalog_id: str
    generation: int
    anchor_identity: ManagementIdentity
    namespace_identity: ManagementIdentity
    entries: tuple[BindingEntry, ...]


_mb_RECORDS = frozenset(
    {
        ManagementIdentity,
        BindingPrimary,
        OperationRef,
        HistoricalBinding,
        CurrentBinding,
        OperationGenesis,
        FreshBindingTarget,
        FreshBindingLayout,
        FreshGenesis,
        UncommittedFloor,
        EpochCredit,
        KnownEpochFloor,
        BindingEntry,
        BindingsDocument,
    }
)


def _mb_plain(value: object, depth: int = 0) -> Any:
    if type(value) in _mb_RECORDS:
        if depth >= _mb_MAX_DEPTH:
            raise SchemaWireError("LIMIT_EXCEEDED")
        return {
            field.name: _mb_plain(getattr(value, field.name), depth + 1)
            for field in _mc_fields(_mc_cast(Any, value))
        }
    if type(value) is tuple:
        if depth >= _mb_MAX_DEPTH:
            raise SchemaWireError("LIMIT_EXCEEDED")
        return [_mb_plain(item, depth + 1) for item in value]
    if type(value) in {str, int, type(None)}:
        return value
    raise _mb_bad()


def _mb_canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def _mb_object(value: Any, keys: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != set(keys.split()):
        raise _mb_bad()
    return value


def _mb_array(value: Any) -> list[Any]:
    if type(value) is not list:
        raise _mb_bad()
    return value


def _mb_text(value: Any) -> str:
    if type(value) is not str or any(55296 <= ord(c) <= 57343 for c in value):
        raise _mb_bad()
    return value


def _mb_hex(value: Any, length: int = 32) -> str:
    if type(value) is not str or re.fullmatch("[0-9a-f]{" + str(length) + "}", value) is None:
        raise _mb_bad()
    return value


def _mb_integer(value: Any) -> int:
    if type(value) is not int or value < 0 or value > 2**63 - 1:
        raise _mb_bad()
    return value


def _mb_name(value: Any) -> str:
    value = _mb_text(value)
    base = value.split(".", 1)[0].rstrip(" ").upper()
    reserved = {"CON", "PRN", "AUX", "NUL", "CLOCK$", "CONIN$", "CONOUT$"}
    reserved.update(prefix + digit for prefix in ("COM", "LPT") for digit in "123456789¹²³")
    if (
        not value
        or value in {".", ".."}
        or value.endswith((".", " "))
        or any(ord(c) < 32 or c in '<>:"/\\|?*' for c in value)
        or (base in reserved)
        or (len(value.encode("utf-16-le")) > 510)
    ):
        raise _mb_bad()
    return _mc_cast(str, value)


def _mb_ordered(keys: list[Any]) -> None:
    if keys != sorted(keys) or len(keys) != len(set(keys)):
        raise _mb_bad()


def _mb_roles(value: Any) -> tuple[str, ...]:
    result = tuple(_mb_text(role) for role in _mb_array(value))
    _mb_ordered(list(result))
    if not result or not set(result) <= _mb_ROLES or {"consent", "consent1-legacy"} <= set(result):
        raise _mb_bad()
    return result


def _mb_identity(value: Any, expected_kind: str) -> ManagementIdentity:
    obj = _mb_object(value, "kind volume_hex file_id_hex")
    if obj["kind"] != expected_kind:
        raise _mb_bad()
    return ManagementIdentity(
        obj["kind"], _mb_hex(obj["volume_hex"], 16), _mb_hex(obj["file_id_hex"])
    )


def _mb_primary(value: Any) -> BindingPrimary:
    obj = _mb_object(value, "kind anchor_identity namespace_identity catalog_id")
    if obj["kind"] not in {"LIBRARY_ROOT", "DB_PARENT"}:
        raise _mb_bad()
    return BindingPrimary(
        obj["kind"],
        _mb_identity(obj["anchor_identity"], "DIR"),
        _mb_identity(obj["namespace_identity"], "DIR"),
        _mb_hex(obj["catalog_id"]),
    )


def _mb_ref(value: Any) -> OperationRef:
    obj = _mb_object(value, "operation_id plan_digest link_nonce")
    return OperationRef(
        _mb_hex(obj["operation_id"]), _mb_hex(obj["plan_digest"], 64), _mb_hex(obj["link_nonce"])
    )


def _mb_genesis(value: Any) -> OperationGenesis | FreshGenesis:
    if type(value) is not dict:
        raise _mb_bad()
    if value.get("kind") == "OPERATION":
        obj = _mb_object(value, "kind operation_id plan_digest")
        return OperationGenesis(
            "OPERATION", _mb_hex(obj["operation_id"]), _mb_hex(obj["plan_digest"], 64)
        )
    obj = _mb_object(value, "kind intent_id layout")
    if obj["kind"] != "FRESH_INIT":
        raise _mb_bad()
    layout = _mb_object(obj["layout"], "primary targets")
    targets = []
    for item in _mb_array(layout["targets"]):
        item = _mb_object(
            item,
            "db_id dataset_id anchor_identity namespace_identity name roles profile_id pre_identity",
        )
        if item["pre_identity"] is not None or item["profile_id"] not in _mb_PROFILES:
            raise _mb_bad()
        targets.append(
            FreshBindingTarget(
                _mb_hex(item["db_id"]),
                _mb_hex(item["dataset_id"]),
                _mb_identity(item["anchor_identity"], "DIR"),
                _mb_identity(item["namespace_identity"], "DIR"),
                _mb_name(item["name"]),
                _mb_roles(item["roles"]),
                item["profile_id"],
                None,
            )
        )
    _mb_ordered([target.db_id for target in targets])
    if not targets:
        raise _mb_bad()
    return FreshGenesis(
        "FRESH_INIT",
        _mb_hex(obj["intent_id"]),
        FreshBindingLayout(_mb_primary(layout["primary"]), tuple(targets)),
    )


def _mb_floor(
    value: Any, genesis: OperationGenesis | FreshGenesis
) -> UncommittedFloor | KnownEpochFloor:
    if type(value) is not dict:
        raise _mb_bad()
    if value.get("kind") == "UNCOMMITTED":
        _mb_object(value, "kind")
        return UncommittedFloor("UNCOMMITTED")
    obj = _mb_object(value, "kind value credits")
    if obj["kind"] != "KNOWN":
        raise _mb_bad()
    number = _mb_integer(obj["value"])
    credits = []
    for credit in _mb_array(obj["credits"]):
        credit = _mb_object(credit, "operation_id plan_digest sequence record_digest")
        credits.append(
            EpochCredit(
                _mb_hex(credit["operation_id"]),
                _mb_hex(credit["plan_digest"], 64),
                _mb_integer(credit["sequence"]),
                _mb_hex(credit["record_digest"], 64),
            )
        )
    _mb_ordered([(c.operation_id, c.sequence, c.record_digest) for c in credits])
    if (
        number == 0
        and (credits or not isinstance(genesis, FreshGenesis))
        or (number > 0 and (not credits))
    ):
        raise _mb_bad()
    return KnownEpochFloor("KNOWN", number, tuple(credits))


def _mb_entry(value: Any) -> BindingEntry:
    obj = _mb_object(
        value,
        "db_id dataset_id state current history roles primary genesis operation_ref epoch_floor",
    )
    if obj["state"] not in {"PREPARED", "BOUND", "RETIRED"}:
        raise _mb_bad()
    genesis = _mb_genesis(obj["genesis"])
    current = _mb_object(obj["current"], "name identity")
    if current["identity"] is None:
        if obj["state"] != "PREPARED" or not isinstance(genesis, FreshGenesis):
            raise _mb_bad()
        identity = None
    else:
        identity = _mb_identity(current["identity"], "FILE")
    history = []
    history_keys = []
    for item in _mb_array(obj["history"]):
        history_keys.append(_mb_canonical(item))
        item = _mb_object(item, "name identity retired_by")
        history.append(
            HistoricalBinding(
                _mb_name(item["name"]),
                _mb_identity(item["identity"], "FILE"),
                _mb_ref(item["retired_by"]),
            )
        )
    _mb_ordered(history_keys)
    floor = _mb_floor(obj["epoch_floor"], genesis)
    if identity is None and isinstance(floor, KnownEpochFloor):
        raise _mb_bad()
    return BindingEntry(
        _mb_hex(obj["db_id"]),
        _mb_hex(obj["dataset_id"]),
        obj["state"],
        CurrentBinding(_mb_name(current["name"]), identity),
        tuple(history),
        _mb_roles(obj["roles"]),
        _mb_primary(obj["primary"]),
        genesis,
        None if obj["operation_ref"] is None else _mb_ref(obj["operation_ref"]),
        floor,
    )


def _mb_document(value: Any) -> BindingsDocument:
    obj = _mb_object(
        value, "format version catalog_id generation anchor_identity namespace_identity entries"
    )
    if obj["format"] != "recoryn-management-bindings-v1" or _mb_integer(obj["version"]) != 1:
        raise _mb_bad()
    entries = tuple(_mb_entry(item) for item in _mb_array(obj["entries"]))
    _mb_ordered([(entry.dataset_id, entry.db_id) for entry in entries])
    if len({entry.db_id for entry in entries}) != len(entries):
        raise _mb_bad()
    physical = [
        (e.current.identity.volume_hex, e.current.identity.file_id_hex)
        for e in entries
        if e.current.identity is not None
    ]
    if len(set(physical)) != len(physical):
        raise _mb_bad()
    return BindingsDocument(
        "recoryn-management-bindings-v1",
        obj["version"],
        _mb_hex(obj["catalog_id"]),
        _mb_integer(obj["generation"]),
        _mb_identity(obj["anchor_identity"], "DIR"),
        _mb_identity(obj["namespace_identity"], "DIR"),
        entries,
    )


def _mb_pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in items:
        if name in result:
            raise _mb_bad()
        result[name] = value
    return result


def _mb_no_number(token: str) -> Any:
    raise _mb_bad()


def _mb_depth(value: Any, depth: int = 0) -> None:
    if type(value) in {dict, list}:
        if depth >= _mb_MAX_DEPTH:
            raise SchemaWireError("LIMIT_EXCEEDED")
        if type(value) is dict:
            for name, child in value.items():
                _mb_text(name)
                _mb_depth(child, depth + 1)
        else:
            for child in value:
                _mb_depth(child, depth + 1)
    elif type(value) is str:
        _mb_text(value)


def _mb_scan_depth(text: str) -> None:
    depth = 0
    quoted = escaped = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "{[":
            depth += 1
            if depth > _mb_MAX_DEPTH:
                raise SchemaWireError("LIMIT_EXCEEDED")
        elif char in "}]":
            depth -= 1


def _mb_decode_bindings(raw: bytes) -> BindingsDocument:
    """Validate bytes into immutable data. No identity or authority is established."""
    if type(raw) is not bytes:
        raise _mb_bad()
    if len(raw) > _mb_MAX_BYTES:
        raise SchemaWireError("LIMIT_EXCEEDED")
    if raw.startswith(b"\xef\xbb\xbf") or raw.endswith(b"\n"):
        raise _mb_bad()
    failed = False
    try:
        text = raw.decode("utf-8")
        _mb_scan_depth(text)
        value = json.loads(
            text,
            object_pairs_hook=_mb_pairs,
            parse_float=_mb_no_number,
            parse_constant=_mb_no_number,
        )
    except SchemaWireError:
        raise
    except (UnicodeError, ValueError, RecursionError):
        failed = True
    if failed:
        raise _mb_bad()
    _mb_depth(value)
    try:
        document = _mb_document(value)
        canonical = _mb_canonical(_mb_plain(document))
    except (KeyError, TypeError, UnicodeError, RecursionError):
        failed = True
    if failed:
        raise _mb_bad()
    if len(canonical) > _mb_MAX_BYTES:
        raise SchemaWireError("LIMIT_EXCEEDED")
    if raw != canonical:
        raise _mb_bad()
    return document


def _mb_encode_bindings(document: BindingsDocument) -> bytes:
    """Revalidate frozen data and return the exact canonical wire, without I/O."""
    if type(document) is not BindingsDocument:
        raise _mb_bad()
    failed = False
    try:
        plain = _mb_plain(document)
        _mb_depth(plain)
        checked = _mb_document(plain)
        raw = _mb_canonical(_mb_plain(checked))
    except (KeyError, TypeError, UnicodeError, RecursionError):
        failed = True
    if failed:
        raise _mb_bad()
    if len(raw) > _mb_MAX_BYTES:
        raise SchemaWireError("LIMIT_EXCEEDED")
    return raw


def _mp_record_digest(value: object) -> str:
    if type(value) is not str or re.fullmatch("[0-9a-f]{64}", value) is None:
        raise _mb_bad()
    return value


@_mc_dataclass(frozen=True, slots=True)
class ProgressDocument(_FrozenWireData):
    format: _mc_Literal["recoryn-maintenance-progress-v1"]
    version: int
    operation_id: str
    plan_digest: str
    sequence: int
    record_digest: str

    def __post_init__(self) -> None:
        if type(self.format) is not str or self.format != "recoryn-maintenance-progress-v1":
            raise _mb_bad()
        if type(self.version) is not int or self.version != 1:
            raise _mb_bad()
        _mb_hex(self.operation_id, 32)
        _mb_hex(self.plan_digest, 64)
        _mb_integer(self.sequence)
        _mp_record_digest(self.record_digest)
        _FrozenWireData.__post_init__(self)


def _mp_document(value: Any) -> ProgressDocument:
    obj = _mb_object(value, "format version operation_id plan_digest sequence record_digest")
    return ProgressDocument(
        obj["format"],
        obj["version"],
        obj["operation_id"],
        obj["plan_digest"],
        obj["sequence"],
        obj["record_digest"],
    )


def _mp_plain(document: ProgressDocument) -> dict[str, object]:
    return {
        "format": document.format,
        "version": document.version,
        "operation_id": document.operation_id,
        "plan_digest": document.plan_digest,
        "sequence": document.sequence,
        "record_digest": document.record_digest,
    }


def _mp_parse_integer(token: str) -> int:
    if len(token) > 20:
        raise _mb_bad()
    return int(token)


def _mp_parse(raw: bytes) -> Any:
    failed = False
    value: Any = None
    try:
        text = raw.decode("utf-8")
        _mb_scan_depth(text)
        value = json.loads(
            text,
            object_pairs_hook=_mb_pairs,
            parse_int=_mp_parse_integer,
            parse_float=_mb_no_number,
            parse_constant=_mb_no_number,
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        failed = True
    if failed:
        raise _mb_bad()
    _mb_depth(value)
    return value


def _mp_decode_progress(raw: bytes) -> ProgressDocument:
    """Return immutable validated wire data, without file or authority checks."""
    if type(raw) is not bytes:
        raise _mb_bad()
    if len(raw) > _mb_MAX_BYTES:
        raise SchemaWireError("LIMIT_EXCEEDED")
    if raw.startswith(b"\xef\xbb\xbf") or raw.endswith(b"\n"):
        raise _mb_bad()
    document = _mp_document(_mp_parse(raw))
    canonical = _mb_canonical(_mp_plain(document))
    if len(canonical) > _mb_MAX_BYTES:
        raise SchemaWireError("LIMIT_EXCEEDED")
    if raw != canonical:
        raise _mb_bad()
    return document


def _mp_encode_progress(document: ProgressDocument) -> bytes:
    """Revalidate a directly constructed DTO and return exact canonical bytes."""
    if type(document) is not ProgressDocument:
        raise _mb_bad()
    checked = _mp_document(_mp_plain(document))
    raw = _mb_canonical(_mp_plain(checked))
    if len(raw) > _mb_MAX_BYTES:
        raise SchemaWireError("LIMIT_EXCEEDED")
    return raw


WireOperationKind: _mgmt_TypeAlias = _mc_Literal["APPLY", "ROLLBACK"]
_mn_ROOT_KEYS = (
    "format operation_id kind dataset_id reverses_operation_id targets approval_digest commit_order"
)


@_mc_dataclass(frozen=True, slots=True)
class AbsentPointer(_FrozenWireData):
    kind: _mc_Literal["ABSENT"]


@_mc_dataclass(frozen=True, slots=True)
class FreshPointer(_FrozenWireData):
    kind: _mc_Literal["FRESH"]
    dataset_id: str
    epoch: int


@_mc_dataclass(frozen=True, slots=True)
class CommitPointer(_FrozenWireData):
    kind: _mc_Literal["COMMIT"]
    dataset_id: str
    operation_id: str
    epoch: int
    input_digest: str


WirePointer: _mgmt_TypeAlias = AbsentPointer | FreshPointer | CommitPointer


@_mc_dataclass(frozen=True, slots=True)
class PhysicalBinding(_FrozenWireData):
    anchor_identity: ManagementIdentity
    parent_identity: ManagementIdentity
    name: str
    identity: ManagementIdentity


@_mc_dataclass(frozen=True, slots=True)
class LocalBinding(_FrozenWireData):
    anchor_identity: ManagementIdentity
    namespace_identity: ManagementIdentity
    catalog_id: str
    db_id: str
    link_nonce: str


@_mc_dataclass(frozen=True, slots=True)
class PostComponent(_FrozenWireData):
    component: str
    version: int
    fingerprint: str


@_mc_dataclass(frozen=True, slots=True)
class PostContract(_FrozenWireData):
    profile_id: str
    physical_version: int
    components: tuple[PostComponent, ...]
    pointer: WirePointer
    preservation_digest: str


@_mc_dataclass(frozen=True, slots=True)
class PlannedSlot(_FrozenWireData):
    operation_id: str
    db_id: str
    kind: _mc_Literal["DB_IMAGE", "COST_WITNESS"]


@_mc_dataclass(frozen=True, slots=True)
class PlanTarget(_FrozenWireData):
    db_id: str
    roles: tuple[str, ...]
    physical_binding: PhysicalBinding
    local_binding: LocalBinding
    pre_profile: str
    pre_pointer: WirePointer
    pre_state_digest: str
    target_profile: str
    target_epoch: int
    input_digest: str
    post_contract: PostContract
    pre_image_slot: PlannedSlot
    sidecar_slots: tuple[PlannedSlot, ...]


@_mc_dataclass(frozen=True, slots=True)
class PlanDocument(_FrozenWireData):
    format: _mc_Literal["recoryn-maintenance-plan-v1"]
    operation_id: str
    kind: WireOperationKind
    dataset_id: str
    reverses_operation_id: str | None
    targets: tuple[PlanTarget, ...]
    approval_digest: str
    commit_order: tuple[str, ...]


_mn_RECORDS = frozenset(
    {
        ManagementIdentity,
        AbsentPointer,
        FreshPointer,
        CommitPointer,
        PhysicalBinding,
        LocalBinding,
        PostComponent,
        PostContract,
        PlannedSlot,
        PlanTarget,
        PlanDocument,
    }
)


def _mn_plain(value: object, depth: int = 0) -> Any:
    if type(value) in _mn_RECORDS:
        if depth >= 16:
            raise SchemaWireError("LIMIT_EXCEEDED")
        return {
            field.name: _mn_plain(getattr(value, field.name), depth + 1)
            for field in _mc_fields(_mc_cast(Any, value))
        }
    if type(value) is tuple:
        if depth >= 16:
            raise SchemaWireError("LIMIT_EXCEEDED")
        return [_mn_plain(item, depth + 1) for item in value]
    if type(value) is str:
        return _mb_text(value)
    if type(value) in {int, type(None)}:
        return value
    raise _mb_bad()


def _mn_positive_epoch(value: Any) -> int:
    number = _mb_integer(value)
    if number == 0:
        raise _mb_bad()
    return number


def _mn_label(value: Any) -> str:
    result = _mb_text(value)
    if not result:
        raise _mb_bad()
    return result


def _mn_pointer(value: Any) -> WirePointer:
    if type(value) is not dict:
        raise _mb_bad()
    if value.get("kind") == "ABSENT":
        _mb_object(value, "kind")
        return AbsentPointer("ABSENT")
    if value.get("kind") == "FRESH":
        obj = _mb_object(value, "kind dataset_id epoch")
        epoch = _mb_integer(obj["epoch"])
        if epoch != 0:
            raise _mb_bad()
        return FreshPointer("FRESH", _mb_hex(obj["dataset_id"]), epoch)
    obj = _mb_object(value, "kind dataset_id operation_id epoch input_digest")
    if obj["kind"] != "COMMIT":
        raise _mb_bad()
    return CommitPointer(
        "COMMIT",
        _mb_hex(obj["dataset_id"]),
        _mb_hex(obj["operation_id"]),
        _mn_positive_epoch(obj["epoch"]),
        _mb_hex(obj["input_digest"], 64),
    )


def _mn_post(value: Any) -> PostContract:
    obj = _mb_object(value, "profile_id physical_version components pointer preservation_digest")
    physical_version = _mb_integer(obj["physical_version"])
    if physical_version not in {0, 1, 2}:
        raise _mb_bad()
    components = []
    for value in _mb_array(obj["components"]):
        item = _mb_object(value, "component version fingerprint")
        fingerprint = _mb_text(item["fingerprint"])
        prefix = "recoryn-shape-v1:"
        if not fingerprint.startswith(prefix):
            raise _mb_bad()
        _mb_hex(fingerprint[len(prefix) :], 64)
        components.append(
            PostComponent(
                _mn_label(item["component"]), _mn_positive_epoch(item["version"]), fingerprint
            )
        )
    _mb_ordered([component.component for component in components])
    if not components:
        raise _mb_bad()
    return PostContract(
        _mn_label(obj["profile_id"]),
        physical_version,
        tuple(components),
        _mn_pointer(obj["pointer"]),
        _mb_hex(obj["preservation_digest"], 64),
    )


def _mn_slot(value: Any, operation: str, db_id: str, kind: str) -> PlannedSlot:
    obj = _mb_object(value, "operation_id db_id kind")
    if obj["operation_id"] != operation or obj["db_id"] != db_id or obj["kind"] != kind:
        raise _mb_bad()
    return PlannedSlot(operation, db_id, _mc_cast(_mc_Literal["DB_IMAGE", "COST_WITNESS"], kind))


def _mn_target(value: Any, operation: str, dataset: str, kind: WireOperationKind) -> PlanTarget:
    obj = _mb_object(
        value,
        "db_id roles physical_binding local_binding pre_profile pre_pointer pre_state_digest target_profile target_epoch input_digest post_contract pre_image_slot sidecar_slots",
    )
    db_id = _mb_hex(obj["db_id"])
    physical = _mb_object(obj["physical_binding"], "anchor_identity parent_identity name identity")
    physical_fact = PhysicalBinding(
        _mb_identity(physical["anchor_identity"], "DIR"),
        _mb_identity(physical["parent_identity"], "DIR"),
        _mb_name(physical["name"]),
        _mb_identity(physical["identity"], "FILE"),
    )
    local = _mb_object(
        obj["local_binding"], "anchor_identity namespace_identity catalog_id db_id link_nonce"
    )
    local_fact = LocalBinding(
        _mb_identity(local["anchor_identity"], "DIR"),
        _mb_identity(local["namespace_identity"], "DIR"),
        _mb_hex(local["catalog_id"]),
        _mb_hex(local["db_id"]),
        _mb_hex(local["link_nonce"]),
    )
    if local_fact.db_id != db_id or local_fact.anchor_identity != physical_fact.anchor_identity:
        raise _mb_bad()
    pre = _mn_pointer(obj["pre_pointer"])
    if isinstance(pre, (FreshPointer, CommitPointer)) and pre.dataset_id != dataset:
        raise _mb_bad()
    epoch = _mn_positive_epoch(obj["target_epoch"])
    if isinstance(pre, CommitPointer) and (epoch <= pre.epoch or pre.operation_id == operation):
        raise _mb_bad()
    input_digest = _mb_hex(obj["input_digest"], 64)
    target_profile = _mn_label(obj["target_profile"])
    post = _mn_post(obj["post_contract"])
    if post.profile_id != target_profile or (kind == "APPLY" and post.physical_version != 2):
        raise _mb_bad()
    if post.physical_version == 2:
        ptr = post.pointer
        if not isinstance(ptr, CommitPointer) or (
            ptr.dataset_id != dataset
            or ptr.operation_id != operation
            or ptr.epoch != epoch
            or (ptr.input_digest != input_digest)
        ):
            raise _mb_bad()
    elif kind != "ROLLBACK" or not isinstance(post.pointer, AbsentPointer):
        raise _mb_bad()
    image = _mn_slot(obj["pre_image_slot"], operation, db_id, "DB_IMAGE")
    sidecars = tuple(
        _mn_slot(value, operation, db_id, "COST_WITNESS")
        for value in _mb_array(obj["sidecar_slots"])
    )
    _mb_ordered([(slot.operation_id, slot.db_id, slot.kind) for slot in sidecars])
    return PlanTarget(
        db_id,
        _mb_roles(obj["roles"]),
        physical_fact,
        local_fact,
        _mn_label(obj["pre_profile"]),
        pre,
        _mb_hex(obj["pre_state_digest"], 64),
        target_profile,
        epoch,
        input_digest,
        post,
        image,
        sidecars,
    )


def _mn_permutation(order: tuple[str, ...], target_ids: list[str]) -> None:
    if len(order) != len(target_ids) or set(order) != set(target_ids):
        raise _mb_bad()


def _mn_document(value: Any) -> PlanDocument:
    obj = _mb_object(value, _mn_ROOT_KEYS)
    if obj["format"] != "recoryn-maintenance-plan-v1" or obj["kind"] not in ("APPLY", "ROLLBACK"):
        raise _mb_bad()
    operation, dataset = (_mb_hex(obj["operation_id"]), _mb_hex(obj["dataset_id"]))
    kind = _mc_cast(WireOperationKind, obj["kind"])
    reverse = obj["reverses_operation_id"]
    if kind == "APPLY":
        if reverse is not None:
            raise _mb_bad()
    else:
        reverse = _mb_hex(reverse)
        if reverse == operation:
            raise _mb_bad()
    targets = tuple(
        _mn_target(item, operation, dataset, kind) for item in _mb_array(obj["targets"])
    )
    target_ids = [target.db_id for target in targets]
    _mb_ordered(target_ids)
    physical = [
        (t.physical_binding.identity.volume_hex, t.physical_binding.identity.file_id_hex)
        for t in targets
    ]
    if not targets or len(physical) != len(set(physical)):
        raise _mb_bad()
    order = tuple(_mb_hex(item) for item in _mb_array(obj["commit_order"]))
    _mn_permutation(order, target_ids)
    return PlanDocument(
        "recoryn-maintenance-plan-v1",
        operation,
        kind,
        dataset,
        reverse,
        targets,
        _mb_hex(obj["approval_digest"], 64),
        order,
    )


def _mn_decode_plan(raw: bytes) -> PlanDocument:
    """Decode only PLAN data. Never open a source, image, namespace or service."""
    if type(raw) is not bytes:
        raise _mb_bad()
    if len(raw) > 8388608:
        raise SchemaWireError("LIMIT_EXCEEDED")
    if raw.startswith(b"\xef\xbb\xbf") or raw.endswith(b"\n"):
        raise _mb_bad()
    try:
        text = raw.decode("utf-8")
        _mb_scan_depth(text)
        value = json.loads(
            text,
            object_pairs_hook=_mb_pairs,
            parse_float=_mb_no_number,
            parse_constant=_mb_no_number,
        )
        _mb_depth(value)
        document = _mn_document(value)
        canonical = _mb_canonical(_mn_plain(document))
    except SchemaWireError:
        raise
    except (UnicodeError, ValueError, KeyError, TypeError, RecursionError):
        raise _mb_bad() from None
    if len(canonical) > 8388608:
        raise SchemaWireError("LIMIT_EXCEEDED")
    if raw != canonical:
        raise _mb_bad()
    return document


def _mn_encode_plan(document: PlanDocument) -> bytes:
    """Recheck immutable PLAN facts and emit canonical bytes, without I/O."""
    if type(document) is not PlanDocument:
        raise _mb_bad()
    try:
        plain = _mn_plain(document)
        _mb_depth(plain)
        checked = _mn_document(plain)
        raw = _mb_canonical(_mn_plain(checked))
    except SchemaWireError:
        raise
    except (UnicodeError, ValueError, KeyError, TypeError, RecursionError):
        raise _mb_bad() from None
    if len(raw) > 8388608:
        raise SchemaWireError("LIMIT_EXCEEDED")
    return raw


_mr_SchemaWireError = SchemaWireError
_mr_MAX_BYTES = 8388608


@_mc_dataclass(frozen=True, slots=True)
class ArtifactRef(_FrozenWireData):
    operation_id: str
    db_id: str
    kind: _mc_Literal["DB_IMAGE", "COST_WITNESS"]
    digest: str
    identity: ManagementIdentity


@_mc_dataclass(frozen=True, slots=True)
class BindingLink(_FrozenWireData):
    db_id: str
    anchor_identity: ManagementIdentity
    namespace_identity: ManagementIdentity
    catalog_id: str
    link_nonce: str
    binding_digest: str


@_mc_dataclass(frozen=True, slots=True)
class RecordTarget(_FrozenWireData):
    db_id: str
    source_cut: _mc_Literal["PRE", "IMAGE_UNREBOUND", "POST", "UNRESOLVED"]
    source_pointer: AbsentPointer | FreshPointer | CommitPointer | None
    source_digest: str | None
    pre_image: ArtifactRef | None
    sidecars: tuple[ArtifactRef, ...]
    credited_epoch: int | None
    restore_effect: RestoreEffect


@_mc_dataclass(frozen=True, slots=True)
class RecordDocument(_FrozenWireData):
    format: _mc_Literal["recoryn-maintenance-record-v1"]
    version: int
    operation_id: str
    plan_digest: str
    sequence: int
    prior_digest: str | None
    phase: _mc_Literal["PREPARING", "IMAGE_VERIFIED", "APPLYING", "VERIFYING", "VERIFIED"]
    disposition: _mc_Literal["RUNNING", "NEEDS_RESUME", "QUARANTINED", "RECONCILIATION_REQUIRED"]
    targets: tuple[RecordTarget, ...]
    binding_links: tuple[BindingLink, ...] | None
    output_digest: str | None


_mr_RECORD_TYPES = frozenset(
    {
        AbsentPointer,
        FreshPointer,
        CommitPointer,
        ArtifactRef,
        BindingLink,
        RecordTarget,
        RecordDocument,
        ManagementIdentity,
    }
)


def _mr_plain(value: object, depth: int = 0) -> Any:
    if type(value) in _mr_RECORD_TYPES:
        if depth >= 16:
            raise _mr_SchemaWireError("LIMIT_EXCEEDED")
        return {
            field.name: _mr_plain(getattr(value, field.name), depth + 1)
            for field in _mc_fields(_mc_cast(Any, value))
        }
    if type(value) is tuple:
        if depth >= 16:
            raise _mr_SchemaWireError("LIMIT_EXCEEDED")
        return [_mr_plain(item, depth + 1) for item in value]
    if type(value) in {str, int, type(None)}:
        return value
    raise _mb_bad()


def _mr_pointer(value: Any) -> AbsentPointer | FreshPointer | CommitPointer:
    if type(value) is not dict:
        raise _mb_bad()
    if value.get("kind") == "ABSENT":
        _mb_object(value, "kind")
        return AbsentPointer("ABSENT")
    if value.get("kind") == "FRESH":
        obj = _mb_object(value, "kind dataset_id epoch")
        return FreshPointer("FRESH", _mb_hex(obj["dataset_id"]), _mb_integer(obj["epoch"]))
    obj = _mb_object(value, "kind dataset_id operation_id epoch input_digest")
    if obj["kind"] != "COMMIT":
        raise _mb_bad()
    return CommitPointer(
        "COMMIT",
        _mb_hex(obj["dataset_id"]),
        _mb_hex(obj["operation_id"]),
        _mb_integer(obj["epoch"]),
        _mb_hex(obj["input_digest"], 64),
    )


def _mr_artifact(value: Any) -> ArtifactRef:
    obj = _mb_object(value, "operation_id db_id kind digest identity")
    return ArtifactRef(
        _mb_hex(obj["operation_id"]),
        _mb_hex(obj["db_id"]),
        obj["kind"],
        _mb_hex(obj["digest"], 64),
        _mb_identity(obj["identity"], "FILE"),
    )


def _mr_link(value: Any) -> BindingLink:
    obj = _mb_object(
        value, "db_id anchor_identity namespace_identity catalog_id link_nonce binding_digest"
    )
    return BindingLink(
        _mb_hex(obj["db_id"]),
        _mb_identity(obj["anchor_identity"], "DIR"),
        _mb_identity(obj["namespace_identity"], "DIR"),
        _mb_hex(obj["catalog_id"]),
        _mb_hex(obj["link_nonce"]),
        _mb_hex(obj["binding_digest"], 64),
    )


def _mr_target(value: Any) -> RecordTarget:
    obj = _mb_object(
        value,
        "db_id source_cut source_pointer source_digest pre_image sidecars credited_epoch restore_effect",
    )
    return RecordTarget(
        _mb_hex(obj["db_id"]),
        obj["source_cut"],
        None if obj["source_pointer"] is None else _mr_pointer(obj["source_pointer"]),
        None if obj["source_digest"] is None else _mb_hex(obj["source_digest"], 64),
        None if obj["pre_image"] is None else _mr_artifact(obj["pre_image"]),
        tuple(_mr_artifact(x) for x in _mb_array(obj["sidecars"])),
        None if obj["credited_epoch"] is None else _mb_integer(obj["credited_epoch"]),
        obj["restore_effect"],
    )


def _mr_document(value: Any) -> RecordDocument:
    obj = _mb_object(
        value,
        "format version operation_id plan_digest sequence prior_digest phase disposition targets binding_links output_digest",
    )
    return RecordDocument(
        obj["format"],
        _mb_integer(obj["version"]),
        _mb_hex(obj["operation_id"]),
        _mb_hex(obj["plan_digest"], 64),
        _mb_integer(obj["sequence"]),
        None if obj["prior_digest"] is None else _mb_hex(obj["prior_digest"], 64),
        obj["phase"],
        obj["disposition"],
        tuple(_mr_target(x) for x in _mb_array(obj["targets"])),
        None
        if obj["binding_links"] is None
        else tuple(_mr_link(x) for x in _mb_array(obj["binding_links"])),
        None if obj["output_digest"] is None else _mb_hex(obj["output_digest"], 64),
    )


def _mr_check_pointer(pointer: AbsentPointer | FreshPointer | CommitPointer) -> None:
    if type(pointer) is FreshPointer:
        if pointer.epoch != 0:
            raise _mb_bad()
    elif type(pointer) is CommitPointer and pointer.epoch == 0:
        raise _mb_bad()


def _mr_check_ref(ref: ArtifactRef, operation_id: str, db_id: str, kind: str) -> None:
    if ref.operation_id != operation_id or ref.db_id != db_id or ref.kind != kind:
        raise _mb_bad()


def _mr_check(document: RecordDocument) -> None:
    if document.version != 1:
        raise _mb_bad()
    if document.sequence == 0 and document.prior_digest is not None:
        raise _mb_bad()
    if document.sequence > 0 and document.prior_digest is None:
        raise _mb_bad()
    if (document.phase == "VERIFIED") != (document.output_digest is not None):
        raise _mb_bad()
    ids = [target.db_id for target in document.targets]
    _mb_ordered(ids)
    if document.binding_links is None:
        if document.phase != "PREPARING":
            raise _mb_bad()
    else:
        links = [link.db_id for link in document.binding_links]
        _mb_ordered(links)
        if links != ids:
            raise _mb_bad()
    for target in document.targets:
        if target.source_pointer is None or target.source_digest is None:
            if target.source_cut != "UNRESOLVED" or document.disposition not in {
                "QUARANTINED",
                "RECONCILIATION_REQUIRED",
            }:
                raise _mb_bad()
        if target.source_pointer is not None:
            _mr_check_pointer(target.source_pointer)
        if target.source_cut == "POST":
            if target.credited_epoch is None or target.credited_epoch == 0:
                raise _mb_bad()
        elif target.credited_epoch is not None:
            raise _mb_bad()
        if target.pre_image is not None:
            _mr_check_ref(target.pre_image, document.operation_id, target.db_id, "DB_IMAGE")
        elif document.phase != "PREPARING":
            raise _mb_bad()
        for ref in target.sidecars:
            _mr_check_ref(ref, document.operation_id, target.db_id, "COST_WITNESS")
        _mb_ordered([(ref.operation_id, ref.db_id, ref.kind) for ref in target.sidecars])
        if document.phase in {"VERIFYING", "VERIFIED"} and target.source_cut != "POST":
            raise _mb_bad()


def _mr_parse_integer(token: str) -> int:
    if len(token) > 20:
        raise _mb_bad()
    return int(token)


def _mr_parse(raw: bytes) -> Any:
    failed = False
    value: Any = None
    try:
        text = raw.decode("utf-8")
        _mb_scan_depth(text)
        value = json.loads(
            text,
            object_pairs_hook=_mb_pairs,
            parse_int=_mr_parse_integer,
            parse_float=_mb_no_number,
            parse_constant=_mb_no_number,
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        failed = True
    if failed:
        raise _mb_bad()
    _mb_depth(value)
    return value


def _mr_decode_record(raw: bytes) -> RecordDocument:
    """Validate local wire facts only; no actual chain or authority is established."""
    if type(raw) is not bytes:
        raise _mb_bad()
    if len(raw) > _mr_MAX_BYTES:
        raise _mr_SchemaWireError("LIMIT_EXCEEDED")
    if raw.startswith(b"\xef\xbb\xbf") or raw.endswith(b"\n"):
        raise _mb_bad()
    document = _mr_document(_mr_parse(raw))
    _mr_check(document)
    canonical = _mb_canonical(_mr_plain(document))
    if len(canonical) > _mr_MAX_BYTES:
        raise _mr_SchemaWireError("LIMIT_EXCEEDED")
    if raw != canonical:
        raise _mb_bad()
    return document


def _mr_encode_record(document: RecordDocument) -> bytes:
    """Revalidate typed data; constructor return is not a semantic receipt."""
    if type(document) is not RecordDocument:
        raise _mb_bad()
    checked = _mr_document(_mr_plain(document))
    _mr_check(checked)
    raw = _mb_canonical(_mr_plain(checked))
    if len(raw) > _mr_MAX_BYTES:
        raise _mr_SchemaWireError("LIMIT_EXCEEDED")
    return raw


_mo_SchemaWireError = SchemaWireError


@_mc_dataclass(frozen=True, slots=True)
class ComponentFact(_FrozenWireData):
    name: str
    version: int
    fingerprint: str


@_mc_dataclass(frozen=True, slots=True)
class SourceSidecar(_FrozenWireData):
    kind: _mc_Literal["COST_WITNESS"]
    digest: str
    identity: ManagementIdentity


@_mc_dataclass(frozen=True, slots=True)
class OutputTarget(_FrozenWireData):
    db_id: str
    profile_id: str
    physical_version: int
    components: tuple[ComponentFact, ...]
    source_pointer: AbsentPointer | FreshPointer | CommitPointer
    data_digest: str
    media_digest: str | None
    sidecar_digests: tuple[SourceSidecar, ...]
    deletion_digest: str | None
    health_digest: str | None


@_mc_dataclass(frozen=True, slots=True)
class OutputDocument(_FrozenWireData):
    format: _mc_Literal["recoryn-maintenance-output-v1"]
    operation_id: str
    plan_digest: str
    targets: tuple[OutputTarget, ...]


@_mc_dataclass(frozen=True, slots=True)
class CompleteDocument(_FrozenWireData):
    format: _mc_Literal["recoryn-maintenance-complete-v1"]
    operation_id: str
    plan_digest: str
    record_digest: str
    output_digest: str


_mo_RECORDS = frozenset(
    {
        ComponentFact,
        AbsentPointer,
        FreshPointer,
        CommitPointer,
        SourceSidecar,
        OutputTarget,
        OutputDocument,
        CompleteDocument,
        ManagementIdentity,
    }
)


def _mo_plain(value: object, depth: int = 0) -> Any:
    if type(value) in _mo_RECORDS:
        if depth >= _mb_MAX_DEPTH:
            raise _mo_SchemaWireError("LIMIT_EXCEEDED")
        _FrozenWireData.__post_init__(_mc_cast(Any, value))
        return {
            f.name: _mo_plain(getattr(value, f.name), depth + 1)
            for f in _mc_fields(_mc_cast(Any, value))
        }
    if type(value) is tuple:
        if depth >= _mb_MAX_DEPTH:
            raise _mo_SchemaWireError("LIMIT_EXCEEDED")
        return [_mo_plain(item, depth + 1) for item in value]
    if type(value) in {str, int, type(None)}:
        return value
    raise _mb_bad()


def _mo_nonempty(value: Any) -> str:
    value = _mb_text(value)
    if not value:
        raise _mb_bad()
    return _mc_cast(str, value)


def _mo_digest(value: Any) -> str:
    return _mb_hex(value, 64)


def _mo_component(value: Any) -> ComponentFact:
    obj = _mb_object(value, "name version fingerprint")
    fingerprint = _mb_text(obj["fingerprint"])
    prefix = "recoryn-shape-v1:"
    if not fingerprint.startswith(prefix):
        raise _mb_bad()
    _mb_hex(fingerprint[len(prefix) :], 64)
    name = _mo_nonempty(obj["name"])
    version = _mb_integer(obj["version"])
    if version == 0:
        raise _mb_bad()
    return ComponentFact(name, version, fingerprint)


def _mo_pointer(value: Any) -> AbsentPointer | FreshPointer | CommitPointer:
    if type(value) is not dict:
        raise _mb_bad()
    kind = value.get("kind")
    if kind == "ABSENT":
        _mb_object(value, "kind")
        return AbsentPointer("ABSENT")
    if kind == "FRESH":
        obj = _mb_object(value, "kind dataset_id epoch")
        if _mb_integer(obj["epoch"]) != 0:
            raise _mb_bad()
        return FreshPointer("FRESH", _mb_hex(obj["dataset_id"]), 0)
    obj = _mb_object(value, "kind dataset_id operation_id epoch input_digest")
    if kind != "COMMIT" or _mb_integer(obj["epoch"]) == 0:
        raise _mb_bad()
    return CommitPointer(
        "COMMIT",
        _mb_hex(obj["dataset_id"]),
        _mb_hex(obj["operation_id"]),
        _mb_integer(obj["epoch"]),
        _mo_digest(obj["input_digest"]),
    )


def _mo_sidecar(value: Any) -> SourceSidecar:
    obj = _mb_object(value, "kind digest identity")
    if obj["kind"] != "COST_WITNESS":
        raise _mb_bad()
    return SourceSidecar(
        "COST_WITNESS", _mo_digest(obj["digest"]), _mb_identity(obj["identity"], "FILE")
    )


def _mo_optional_digest(value: Any, required: bool) -> str | None:
    if required:
        return _mo_digest(value)
    if value is not None:
        raise _mb_bad()
    return None


def _mo_target(value: Any) -> OutputTarget:
    obj = _mb_object(
        value,
        "db_id profile_id physical_version components source_pointer data_digest media_digest sidecar_digests deletion_digest health_digest",
    )
    profile = _mo_nonempty(obj["profile_id"])
    is_legacy = profile == "LEGACY_JOBS_R0K0"
    if profile not in _mb_PROFILES and not is_legacy:
        raise _mb_bad()
    version = _mb_integer(obj["physical_version"])
    pointer = _mo_pointer(obj["source_pointer"])
    if is_legacy:
        if version not in (0, 1) or type(pointer) is not AbsentPointer:
            raise _mb_bad()
    elif version != 2 or type(pointer) is not CommitPointer:
        raise _mb_bad()
    components = tuple(_mo_component(item) for item in _mb_array(obj["components"]))
    _mb_ordered([c.name for c in components])
    if not components:
        raise _mb_bad()
    if is_legacy:
        if len(components) != 1 or components[0].name != "jobs.core" or components[0].version != 1:
            raise _mb_bad()
        if components[0].fingerprint != (
            "recoryn-shape-v1:2a9a2a799001d3377a969193eaed1955de89a9adfaf0a851a77af9811352de0a"
        ):
            raise _mb_bad()
    sidecars = tuple(_mo_sidecar(item) for item in _mb_array(obj["sidecar_digests"]))
    _mb_ordered([s.kind for s in sidecars])
    if is_legacy and sidecars:
        raise _mb_bad()
    has_library = profile.startswith("F2_L")
    return OutputTarget(
        _mb_hex(obj["db_id"]),
        profile,
        version,
        components,
        pointer,
        _mo_digest(obj["data_digest"]),
        _mo_optional_digest(obj["media_digest"], has_library),
        sidecars,
        _mo_optional_digest(obj["deletion_digest"], has_library),
        _mo_optional_digest(obj["health_digest"], has_library),
    )


def _mo_output(value: Any) -> OutputDocument:
    obj = _mb_object(value, "format operation_id plan_digest targets")
    if obj["format"] != "recoryn-maintenance-output-v1":
        raise _mb_bad()
    operation = _mb_hex(obj["operation_id"])
    targets = tuple(_mo_target(t) for t in _mb_array(obj["targets"]))
    _mb_ordered([target.db_id for target in targets])
    if not targets:
        raise _mb_bad()
    for target in targets:
        if type(target.source_pointer) is CommitPointer:
            if target.source_pointer.operation_id != operation:
                raise _mb_bad()
    return OutputDocument(
        "recoryn-maintenance-output-v1", operation, _mo_digest(obj["plan_digest"]), targets
    )


def _mo_complete(value: Any) -> CompleteDocument:
    obj = _mb_object(value, "format operation_id plan_digest record_digest output_digest")
    if obj["format"] != "recoryn-maintenance-complete-v1":
        raise _mb_bad()
    return CompleteDocument(
        "recoryn-maintenance-complete-v1",
        _mb_hex(obj["operation_id"]),
        _mo_digest(obj["plan_digest"]),
        _mo_digest(obj["record_digest"]),
        _mo_digest(obj["output_digest"]),
    )


def _mo_load(raw: bytes) -> Any:
    if type(raw) is not bytes:
        raise _mb_bad()
    if len(raw) > _mb_MAX_BYTES:
        raise _mo_SchemaWireError("LIMIT_EXCEEDED")
    if raw.startswith(b"\xef\xbb\xbf") or raw.endswith(b"\n"):
        raise _mb_bad()
    try:
        text = raw.decode("utf-8")
        _mb_scan_depth(text)
        value = json.loads(
            text,
            object_pairs_hook=_mb_pairs,
            parse_float=_mb_no_number,
            parse_constant=_mb_no_number,
        )
    except _mo_SchemaWireError:
        raise
    except (UnicodeError, ValueError, RecursionError):
        raise _mb_bad() from None
    _mb_depth(value)
    return value


def _mo_decode(
    raw: bytes, kind: _mc_Literal["OUTPUT", "COMPLETE"]
) -> OutputDocument | CompleteDocument:
    value = _mo_load(raw)
    try:
        document: OutputDocument | CompleteDocument = (
            _mo_output(value) if kind == "OUTPUT" else _mo_complete(value)
        )
        canonical = _mb_canonical(_mo_plain(document))
    except (KeyError, TypeError, UnicodeError, RecursionError):
        raise _mb_bad() from None
    if len(canonical) > _mb_MAX_BYTES:
        raise _mo_SchemaWireError("LIMIT_EXCEEDED")
    if raw != canonical:
        raise _mb_bad()
    return document


def _mo_decode_output(raw: bytes) -> OutputDocument:
    return _mc_cast(OutputDocument, _mo_decode(raw, "OUTPUT"))


def _mo_decode_complete(raw: bytes) -> CompleteDocument:
    return _mc_cast(CompleteDocument, _mo_decode(raw, "COMPLETE"))


def _mo_encode_output(document: OutputDocument) -> bytes:
    if type(document) is not OutputDocument:
        raise _mb_bad()
    checked = _mo_output(_mo_plain(document))
    raw = _mb_canonical(_mo_plain(checked))
    if len(raw) > _mb_MAX_BYTES:
        raise _mo_SchemaWireError("LIMIT_EXCEEDED")
    return raw


def _mo_encode_complete(document: CompleteDocument) -> bytes:
    if type(document) is not CompleteDocument:
        raise _mb_bad()
    checked = _mo_complete(_mo_plain(document))
    raw = _mb_canonical(_mo_plain(checked))
    if len(raw) > _mb_MAX_BYTES:
        raise _mo_SchemaWireError("LIMIT_EXCEEDED")
    return raw


BindingGenesis: _mgmt_TypeAlias = OperationGenesis | FreshGenesis
EpochFloor: _mgmt_TypeAlias = UncommittedFloor | KnownEpochFloor
RestoreEffect: _mgmt_TypeAlias = _mc_Literal[
    "NOT_STARTED",
    "INTENT_RECORDED",
    "BACKUP_RETURNED",
    "BACKUP_FAILED",
    "NO_COPY_VERIFIED",
    "UNKNOWN",
    None,
]
WireDisposition: _mgmt_TypeAlias = _mc_Literal[
    "RUNNING", "NEEDS_RESUME", "QUARANTINED", "RECONCILIATION_REQUIRED"
]
WirePhase: _mgmt_TypeAlias = _mc_Literal[
    "PREPARING", "IMAGE_VERIFIED", "APPLYING", "VERIFYING", "VERIFIED"
]


class ManagementObjectKind(_mgmt_Enum):
    BINDINGS = "BINDINGS"
    PLAN = "PLAN"
    RECORD = "RECORD"
    PROGRESS = "PROGRESS"
    OUTPUT = "OUTPUT"
    COMPLETE = "COMPLETE"


ManagementDocument: _mgmt_TypeAlias = (
    BindingsDocument
    | PlanDocument
    | RecordDocument
    | ProgressDocument
    | OutputDocument
    | CompleteDocument
)
_mgmt_MAX_RAW_BYTES = 8388608


def decode_management(raw: bytes, *, kind: ManagementObjectKind) -> ManagementDocument:
    if type(kind) is not ManagementObjectKind:
        raise SchemaWireError("MALFORMED")
    if type(raw) is not bytes:
        raise SchemaWireError("MALFORMED")
    if len(raw) > _mgmt_MAX_RAW_BYTES:
        raise SchemaWireError("LIMIT_EXCEEDED")
    if kind is ManagementObjectKind.BINDINGS:
        return _mb_decode_bindings(raw)
    if kind is ManagementObjectKind.PLAN:
        return _mn_decode_plan(raw)
    if kind is ManagementObjectKind.RECORD:
        return _mr_decode_record(raw)
    if kind is ManagementObjectKind.PROGRESS:
        return _mp_decode_progress(raw)
    if kind is ManagementObjectKind.OUTPUT:
        return _mo_decode_output(raw)
    if kind is ManagementObjectKind.COMPLETE:
        return _mo_decode_complete(raw)
    raise SchemaWireError("MALFORMED")


def encode_management(document: ManagementDocument) -> bytes:
    if type(document) is BindingsDocument:
        return _mb_encode_bindings(document)
    if type(document) is PlanDocument:
        return _mn_encode_plan(document)
    if type(document) is RecordDocument:
        return _mr_encode_record(document)
    if type(document) is ProgressDocument:
        return _mp_encode_progress(document)
    if type(document) is OutputDocument:
        return _mo_encode_output(document)
    if type(document) is CompleteDocument:
        return _mo_encode_complete(document)
    raise SchemaWireError("MALFORMED")


# Logical supplied-object candidates only; no raw engine filtering or admission.
@_mc_dataclass(frozen=True, slots=True, repr=False)
class _CurrentProfileSpec:
    profile_id: str
    components: tuple[tuple[str, int, str], ...]
    owned_objects: tuple[tuple[str, str], ...]
    registry_rows: tuple[tuple[str, int, str, str], ...]


_CP_COMPONENTS: tuple[tuple[str, int, str, tuple[tuple[str, str], ...]], ...] = (
    (
        "capture.health",
        2,
        "recoryn-shape-v1:5f180b67a914f29c7d55a131978d5807fc7f42ac19d477bc7a960ad1f5073622",
        (
            ("capture_health_event_order", "index"),
            ("capture_health_events", "table"),
            ("capture_health_gap_phase", "index"),
            ("capture_health_runs", "table"),
            ("capture_health_tracks", "table"),
        ),
    ),
    (
        "content.core",
        1,
        "recoryn-shape-v1:03fff360eba1dc0649b608b7211124650705e1cd065993648f933e83470dc731",
        (
            ("content_events", "table"),
            ("content_revision_immutable", "trigger"),
            ("content_revisions", "table"),
            ("content_selections", "table"),
            ("content_session", "index"),
        ),
    ),
    (
        "content.summary_requests",
        1,
        "recoryn-shape-v1:4d3e4230d431ce3674ceb0aaf238720d273825fb9fb4202cf3c430eaec65ee6d",
        (("content_summary_requests", "table"),),
    ),
    (
        "g09.management",
        1,
        "recoryn-shape-v1:a9e56d69fe77d280595c42a2f18d64bc80b93b0c38c323942208e349cbbb1d1e",
        (("recoryn_maintenance", "table"), ("recoryn_schema_components", "table")),
    ),
    (
        "jobs.checkpoints",
        1,
        "recoryn-shape-v1:08ad04f16fc95966ba8c2c01a4c563500fab44faec263d2c7efdddd72d7c27d5",
        (("job_checkpoints", "table"),),
    ),
    (
        "jobs.core",
        1,
        "recoryn-shape-v1:2a9a2a799001d3377a969193eaed1955de89a9adfaf0a851a77af9811352de0a",
        (
            ("attempts", "table"),
            ("events", "table"),
            ("job_local_readers", "table"),
            ("job_remote_intents", "table"),
            ("job_session_lookup", "index"),
            ("job_sessions", "table"),
            ("jobs", "table"),
            ("jobs_dedup", "index"),
        ),
    ),
    (
        "jobs.receipts",
        1,
        "recoryn-shape-v1:07e734ac1586231964d4236f8d90b812d5ddf8cdb038605115c6656828b69153",
        (("job_create_receipts", "table"),),
    ),
    (
        "library.core",
        1,
        "recoryn-shape-v1:582f0b08f997d875adecfb581a6f2c38de3056815c146f5d588f1e4d61ebda47",
        (
            ("chunks", "table"),
            ("deleted_sessions", "table"),
            ("sessions", "table"),
            ("storage_events", "table"),
        ),
    ),
    (
        "security.consent",
        2,
        "recoryn-shape-v1:6a9f50c4185781c91dace5df925d6f4977d6c17499502db0b5531861dc5996e0",
        (
            ("security_consent_meta", "table"),
            ("security_execution", "table"),
            ("security_grants_v2", "table"),
            ("security_local_endpoints", "table"),
            ("security_sessions", "table"),
        ),
    ),
    (
        "security.cost",
        2,
        "recoryn-shape-v1:1cb2ff7b81b6a8545b28204f8308904678677e2dc7341e1755b93ac919be59aa",
        (
            ("security_cost_accounts_v2", "table"),
            ("security_cost_meta_v2", "table"),
            ("security_cost_requests_v2", "table"),
            ("security_cost_usage_events", "table"),
        ),
    ),
    (
        "security.cost.legacy",
        1,
        "recoryn-shape-v1:d6b3887b884e0f2a3300c213c665ad44b7c649755328c8b165aa307a8fee874b",
        (
            ("security_cost_accounts", "table"),
            ("security_cost_meta", "table"),
            ("security_cost_requests", "table"),
        ),
    ),
    (
        "storage.projection",
        1,
        "recoryn-shape-v1:5e2e65aad65986131f63687f8f24a114c392ce16eda9a2e34856e3458bafd9b3",
        (
            ("storage_catalog_change", "trigger"),
            ("storage_catalog_delete", "trigger"),
            ("storage_catalog_insert", "trigger"),
            ("storage_catalog_meta", "table"),
            ("storage_pending_deletions", "table"),
            ("storage_visible_delete", "trigger"),
            ("storage_visible_insert", "trigger"),
            ("storage_visible_sessions", "table"),
        ),
    ),
)
_CP_PROFILES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("F2_J", ("g09.management", "jobs.checkpoints", "jobs.core", "jobs.receipts")),
    ("F2_L", ("capture.health", "g09.management", "library.core", "storage.projection")),
    (
        "F2_LC",
        (
            "capture.health",
            "content.core",
            "content.summary_requests",
            "g09.management",
            "library.core",
            "storage.projection",
        ),
    ),
    (
        "F2_LC_CONS",
        (
            "capture.health",
            "content.core",
            "content.summary_requests",
            "g09.management",
            "library.core",
            "security.consent",
            "storage.projection",
        ),
    ),
    (
        "F2_LC_CONS_COST1",
        (
            "capture.health",
            "content.core",
            "content.summary_requests",
            "g09.management",
            "library.core",
            "security.consent",
            "security.cost.legacy",
            "storage.projection",
        ),
    ),
    (
        "F2_LC_CONS_COST2",
        (
            "capture.health",
            "content.core",
            "content.summary_requests",
            "g09.management",
            "library.core",
            "security.consent",
            "security.cost",
            "security.cost.legacy",
            "storage.projection",
        ),
    ),
    (
        "F2_LC_COST1",
        (
            "capture.health",
            "content.core",
            "content.summary_requests",
            "g09.management",
            "library.core",
            "security.cost.legacy",
            "storage.projection",
        ),
    ),
    (
        "F2_LC_COST2",
        (
            "capture.health",
            "content.core",
            "content.summary_requests",
            "g09.management",
            "library.core",
            "security.cost",
            "security.cost.legacy",
            "storage.projection",
        ),
    ),
    (
        "F2_LJ",
        (
            "capture.health",
            "g09.management",
            "jobs.checkpoints",
            "jobs.core",
            "jobs.receipts",
            "library.core",
            "storage.projection",
        ),
    ),
    (
        "F2_LJC",
        (
            "capture.health",
            "content.core",
            "content.summary_requests",
            "g09.management",
            "jobs.checkpoints",
            "jobs.core",
            "jobs.receipts",
            "library.core",
            "storage.projection",
        ),
    ),
    (
        "F2_LJC_CONS",
        (
            "capture.health",
            "content.core",
            "content.summary_requests",
            "g09.management",
            "jobs.checkpoints",
            "jobs.core",
            "jobs.receipts",
            "library.core",
            "security.consent",
            "storage.projection",
        ),
    ),
    (
        "F2_LJC_CONS_COST1",
        (
            "capture.health",
            "content.core",
            "content.summary_requests",
            "g09.management",
            "jobs.checkpoints",
            "jobs.core",
            "jobs.receipts",
            "library.core",
            "security.consent",
            "security.cost.legacy",
            "storage.projection",
        ),
    ),
    (
        "F2_LJC_CONS_COST2",
        (
            "capture.health",
            "content.core",
            "content.summary_requests",
            "g09.management",
            "jobs.checkpoints",
            "jobs.core",
            "jobs.receipts",
            "library.core",
            "security.consent",
            "security.cost",
            "security.cost.legacy",
            "storage.projection",
        ),
    ),
    (
        "F2_LJC_COST1",
        (
            "capture.health",
            "content.core",
            "content.summary_requests",
            "g09.management",
            "jobs.checkpoints",
            "jobs.core",
            "jobs.receipts",
            "library.core",
            "security.cost.legacy",
            "storage.projection",
        ),
    ),
    (
        "F2_LJC_COST2",
        (
            "capture.health",
            "content.core",
            "content.summary_requests",
            "g09.management",
            "jobs.checkpoints",
            "jobs.core",
            "jobs.receipts",
            "library.core",
            "security.cost",
            "security.cost.legacy",
            "storage.projection",
        ),
    ),
    (
        "F2_LJ_CONS",
        (
            "capture.health",
            "g09.management",
            "jobs.checkpoints",
            "jobs.core",
            "jobs.receipts",
            "library.core",
            "security.consent",
            "storage.projection",
        ),
    ),
    (
        "F2_LJ_CONS_COST1",
        (
            "capture.health",
            "g09.management",
            "jobs.checkpoints",
            "jobs.core",
            "jobs.receipts",
            "library.core",
            "security.consent",
            "security.cost.legacy",
            "storage.projection",
        ),
    ),
    (
        "F2_LJ_CONS_COST2",
        (
            "capture.health",
            "g09.management",
            "jobs.checkpoints",
            "jobs.core",
            "jobs.receipts",
            "library.core",
            "security.consent",
            "security.cost",
            "security.cost.legacy",
            "storage.projection",
        ),
    ),
    (
        "F2_LJ_COST1",
        (
            "capture.health",
            "g09.management",
            "jobs.checkpoints",
            "jobs.core",
            "jobs.receipts",
            "library.core",
            "security.cost.legacy",
            "storage.projection",
        ),
    ),
    (
        "F2_LJ_COST2",
        (
            "capture.health",
            "g09.management",
            "jobs.checkpoints",
            "jobs.core",
            "jobs.receipts",
            "library.core",
            "security.cost",
            "security.cost.legacy",
            "storage.projection",
        ),
    ),
    (
        "F2_L_CONS",
        (
            "capture.health",
            "g09.management",
            "library.core",
            "security.consent",
            "storage.projection",
        ),
    ),
    (
        "F2_L_CONS_COST1",
        (
            "capture.health",
            "g09.management",
            "library.core",
            "security.consent",
            "security.cost.legacy",
            "storage.projection",
        ),
    ),
    (
        "F2_L_CONS_COST2",
        (
            "capture.health",
            "g09.management",
            "library.core",
            "security.consent",
            "security.cost",
            "security.cost.legacy",
            "storage.projection",
        ),
    ),
    (
        "F2_L_COST1",
        (
            "capture.health",
            "g09.management",
            "library.core",
            "security.cost.legacy",
            "storage.projection",
        ),
    ),
    (
        "F2_L_COST2",
        (
            "capture.health",
            "g09.management",
            "library.core",
            "security.cost",
            "security.cost.legacy",
            "storage.projection",
        ),
    ),
    ("F2_S_CONS", ("g09.management", "security.consent")),
    ("F2_S_CONS_COST1", ("g09.management", "security.consent", "security.cost.legacy")),
    (
        "F2_S_CONS_COST2",
        ("g09.management", "security.consent", "security.cost", "security.cost.legacy"),
    ),
    ("F2_S_COST1", ("g09.management", "security.cost.legacy")),
    ("F2_S_COST2", ("g09.management", "security.cost", "security.cost.legacy")),
)


def _current_profile_candidate(
    logical_objects: tuple[tuple[str, str], ...],
) -> _CurrentProfileSpec | None:
    """Match supplied logical pairs, without reading or certifying their source."""
    if type(logical_objects) is not tuple:
        raise ValueError("INVALID_CURRENT_PROFILE_INPUT")
    input_names: set[str] = set()
    for pair in logical_objects:
        if type(pair) is not tuple or len(pair) != 2:
            raise ValueError("INVALID_CURRENT_PROFILE_INPUT")
        name, kind = pair
        if type(name) is not str or type(kind) is not str:
            raise ValueError("INVALID_CURRENT_PROFILE_INPUT")
        if not name or kind not in ("table", "index", "view", "trigger"):
            raise ValueError("INVALID_CURRENT_PROFILE_INPUT")
        if name in input_names:
            raise ValueError("INVALID_CURRENT_PROFILE_INPUT")
        input_names.add(name)
    supplied = frozenset(logical_objects)
    fixed = {entry[0]: entry for entry in _CP_COMPONENTS}
    if len(fixed) != len(_CP_COMPONENTS) or len(fixed) != 12 or len(_CP_PROFILES) != 30:
        raise RuntimeError("INVALID_CURRENT_PROFILE_CATALOG")
    specs: list[_CurrentProfileSpec] = []
    profile_names: set[str] = set()
    signatures: set[frozenset[tuple[str, str]]] = set()
    for profile_id, component_names in _CP_PROFILES:
        if profile_id in profile_names or len(set(component_names)) != len(component_names):
            raise RuntimeError("INVALID_CURRENT_PROFILE_CATALOG")
        profile_names.add(profile_id)
        try:
            chosen = tuple(fixed[name] for name in component_names)
        except KeyError:
            raise RuntimeError("INVALID_CURRENT_PROFILE_CATALOG") from None
        components = tuple(sorted((entry[0], entry[1], entry[2]) for entry in chosen))
        owned = tuple(sorted(pair for entry in chosen for pair in entry[3]))
        if len({name for name, _ in owned}) != len(owned):
            raise RuntimeError("INVALID_CURRENT_PROFILE_CATALOG")
        signature = frozenset(owned)
        if signature in signatures:
            raise RuntimeError("INVALID_CURRENT_PROFILE_CATALOG")
        signatures.add(signature)
        registry = tuple(
            (name, version, fingerprint, profile_id) for name, version, fingerprint in components
        )
        if tuple(row[:3] for row in registry) != components or any(
            row[3] != profile_id for row in registry
        ):
            raise RuntimeError("INVALID_CURRENT_PROFILE_CATALOG")
        specs.append(_CurrentProfileSpec(profile_id, components, owned, registry))
    for spec in specs:
        if frozenset(spec.owned_objects) == supplied:
            return spec
    return None


@_mc_dataclass(frozen=True, slots=True, repr=False)
class _SuppliedInventoryProjection:
    logical_objects: tuple[tuple[str, str], ...]
    logical_object_rows: tuple[tuple[Any, ...], ...]
    engine_object_rows: tuple[tuple[Any, ...], ...]
    table_evidence: tuple[tuple[Any, ...], ...]
    profile_candidate: _CurrentProfileSpec | None


def _inv_need(condition: bool) -> None:
    if not condition:
        raise ValueError("INVALID_SUPPLIED_INVENTORY_INPUT")


def _inv_text(value: Any, *, name: bool = False) -> None:
    _inv_need(type(value) is str)
    _inv_need((not name or bool(value)) and "\0" not in value)
    _inv_need(not any(0xD800 <= ord(char) <= 0xDFFF for char in value))


def _inv_number(value: Any, minimum: int = 0, maximum: int = 2**63 - 1) -> None:
    _inv_need(type(value) is int)
    _inv_need(minimum <= value <= maximum)


def _inv_tuple(value: Any, width: int | None = None) -> None:
    _inv_need(type(value) is tuple)
    if width is not None:
        _inv_need(len(value) == width)


def _inv_ordinals(rows: tuple[Any, ...]) -> None:
    _inv_need(sorted(row[0] for row in rows) == list(range(len(rows))))


def _inv_structure(objects: Any, evidence: Any) -> None:
    """Validate every supplied cell before any semantic unsupported branch."""
    _inv_tuple(objects)
    _inv_tuple(evidence)
    for row in objects:
        _inv_tuple(row, 4)
        kind, name, owner, sql = row
        _inv_text(kind)
        _inv_need(kind in ("table", "index", "view", "trigger"))
        _inv_text(name, name=True)
        _inv_text(owner, name=True)
        if sql is not None:
            _inv_text(sql)
    _inv_need(len({row[1] for row in objects}) == len(objects))
    for bundle in evidence:
        _inv_tuple(bundle, 4)
        owner, columns, indexes, infos = bundle
        _inv_text(owner, name=True)
        _inv_tuple(columns)
        _inv_tuple(indexes)
        _inv_tuple(infos)
        for row in columns:
            _inv_tuple(row, 7)
            _inv_number(row[0])
            _inv_text(row[1], name=True)
            _inv_text(row[2])
            _inv_number(row[3], 0, 1)
            if row[4] is not None:
                _inv_text(row[4])
            _inv_number(row[5])
            _inv_number(row[6], 0, 3)
        _inv_ordinals(columns)
        _inv_need(len({row[1] for row in columns}) == len(columns))
        ranks = sorted(row[5] for row in columns if row[5])
        _inv_need(ranks == list(range(1, len(ranks) + 1)))
        for row in indexes:
            _inv_tuple(row, 5)
            _inv_number(row[0])
            _inv_text(row[1], name=True)
            _inv_number(row[2], 0, 1)
            _inv_text(row[3])
            _inv_need(row[3] in ("c", "u", "pk"))
            _inv_number(row[4], 0, 1)
        _inv_ordinals(indexes)
        _inv_need(len({row[1] for row in indexes}) == len(indexes))
        for entry in infos:
            _inv_tuple(entry, 2)
            _inv_text(entry[0], name=True)
            _inv_tuple(entry[1])
            for row in entry[1]:
                _inv_tuple(row, 6)
                _inv_number(row[0])
                _inv_number(row[1], -2)
                if row[2] is not None:
                    _inv_text(row[2], name=True)
                _inv_number(row[3], 0, 1)
                if row[4] is not None:
                    _inv_text(row[4], name=True)
                _inv_number(row[5], 0, 1)
            _inv_ordinals(entry[1])
        _inv_need(len({entry[0] for entry in infos}) == len(infos))
    _inv_need(len({bundle[0] for bundle in evidence}) == len(evidence))


def _inv_references(objects: tuple[Any, ...], evidence: tuple[Any, ...]) -> None:
    """Identity joins use raw strings; canonical names never repair references."""
    rows = {row[1]: row for row in objects}
    tables = {row[1] for row in objects if row[0] == "table"}
    for kind, name, owner, _ in objects:
        if kind in ("table", "view"):
            _inv_need(owner == name)
        else:
            _inv_need(owner in rows)
            _inv_need(rows[owner][0] in (("table",) if kind == "index" else ("table", "view")))
    _inv_need({bundle[0] for bundle in evidence} == tables)
    for _, columns, indexes, infos in evidence:
        _inv_need({row[1] for row in indexes} == {entry[0] for entry in infos})
        by_cid = {row[0]: row for row in columns}
        for _, info in infos:
            for row in info:
                if row[1] >= 0:
                    _inv_need(row[1] in by_cid and row[2] == by_cid[row[1]][1])
                else:
                    _inv_need(row[2] is None)


def _inv_fold(value: str) -> str:
    return "".join(chr(ord(c) + 32) if "A" <= c <= "Z" else c for c in value)


def _inv_canonical(value: str, known: frozenset[str]) -> str:
    folded = _inv_fold(value)
    return folded if value.isascii() and folded in known else value


def _inv_collation(value: str | None) -> str | None:
    if value is not None and value.isascii() and value.upper() in _COLLATIONS:
        return value.upper()
    return None


def _inv_parse_table(row: tuple[Any, ...], known: frozenset[str]) -> _Shape | None:
    if row[3] is None:
        return None
    try:
        parsed = _objects(row[3])
    except ValueError as error:
        if type(error) is ValueError and error.args == ("Unsupported component shape",):
            return None
        raise
    if len(parsed) != 1 or parsed[0]["kind"] != "table":
        return None
    model = parsed[0]
    if model["name"] != _inv_canonical(row[1], known):
        return None
    return model


def _inv_columns_match(model: _Shape, columns: tuple[Any, ...]) -> bool:
    if len(columns) != len(model["columns"]):
        return False
    indexed = any(index[0] == "pk" for index in model["autoindexes"])
    implicit_nn = not model["rowid"] or (model["strict"] and indexed)
    for actual, expected in zip(columns, model["columns"], strict=True):
        if not actual[1].isascii() or not actual[2].isascii():
            return False
        try:
            default = _tokens(actual[4]) if actual[4] is not None else None
        except ValueError as error:
            if type(error) is ValueError and error.args == ("Unsupported component shape",):
                return False
            raise
        if (
            actual[1].lower() != expected[0]
            or actual[2].upper() != expected[1]
            or bool(actual[3]) != (expected[2] or (implicit_nn and bool(expected[4])))
            or default != _pragma_default(expected[3])
            or actual[5] != expected[4]
            or actual[6] != expected[5]
        ):
            return False
    return True


def _inv_auto_keys(info: tuple[Any, ...]) -> tuple[tuple[str, str, str], ...] | None:
    keys = []
    auxiliary_started = False
    for row in info:
        if not row[5]:
            auxiliary_started = True
            continue
        if auxiliary_started or row[1] < 0 or row[2] is None or not row[2].isascii():
            return None
        collation = _inv_collation(row[4])
        if collation is None:
            return None
        keys.append((row[2].lower(), "DESC" if row[3] else "ASC", collation))
    return tuple(keys)


def _inv_auxiliary_match(
    model: _Shape, origin: str, info: tuple[Any, ...], columns: tuple[Any, ...]
) -> bool:
    aux = [row for row in info if not row[5]]
    if model["rowid"]:
        return (
            len(aux) == 1 and aux[0][1:4] == (-1, None, 0) and _inv_collation(aux[0][4]) == "BINARY"
        )
    primary = [item for item in model["autoindexes"] if item[0] == "pk"]
    if len(primary) != 1 or len(primary[0][1]) != 1:
        return False
    pk = primary[0][1][0][0]
    if any(col[6] != "BINARY" for col in model["columns"]):
        return False
    for kind, keys in model["autoindexes"]:
        if len(keys) != 1 or keys[0][1:] != ["ASC", "BINARY"]:
            return False
        if kind == "u" and keys[0][0] == pk:
            return False
    expected = [
        row for row in columns if (row[1].lower() != pk if origin == "pk" else row[1].lower() == pk)
    ]
    return len(aux) == len(expected) and all(
        actual[1:4] == (column[0], column[1], 0) and _inv_collation(actual[4]) == "BINARY"
        for actual, column in zip(aux, expected, strict=True)
    )


def _inv_internal_table(row: tuple[Any, ...], bundle: tuple[Any, ...]) -> bool:
    shapes = {
        "sqlite_sequence": ("CREATE TABLE sqlite_sequence(name,seq)", ("name", "seq")),
        "sqlite_stat1": ("CREATE TABLE sqlite_stat1(tbl,idx,stat)", ("tbl", "idx", "stat")),
    }
    if row[0] != "table" or row[1] not in shapes:
        return False
    sql, names = shapes[row[1]]
    expected = tuple((i, name, "", 0, None, 0, 0) for i, name in enumerate(names))
    return (
        row[2] == row[1]
        and row[3] == sql
        and bundle[1] == expected
        and not bundle[2]
        and not bundle[3]
    )


def _project_supplied_inventory(
    objects: Any, evidence: Any, /
) -> _SuppliedInventoryProjection | None:
    """Partition supplied immutable facts; certify neither their source nor authority."""
    _inv_structure(objects, evidence)
    _inv_references(objects, evidence)
    known = frozenset(name for component in _CP_COMPONENTS for name, _ in component[3]) | frozenset(
        ("sqlite_sequence", "sqlite_stat1", "sqlite_stat2", "sqlite_stat3", "sqlite_stat4")
    )
    names = [_inv_canonical(row[1], known) for row in objects]
    _inv_need(len(set(names)) == len(names))
    normalized = tuple(
        sorted(
            (
                (
                    owner,
                    tuple(sorted(columns)),
                    tuple(sorted(indexes)),
                    tuple(sorted((name, tuple(sorted(info))) for name, info in infos)),
                )
                for owner, columns, indexes, infos in evidence
            ),
            key=lambda bundle: _inv_canonical(bundle[0], known),
        )
    )
    bundles = {bundle[0]: bundle for bundle in normalized}
    rows = {row[1]: row for row in objects}
    engine: set[str] = set()
    has_ai = False
    for row in objects:
        if row[0] == "table" and _inv_fold(row[1]).startswith("sqlite_"):
            if not _inv_internal_table(row, bundles[row[1]]):
                return None
            engine.add(row[1])
    for row in objects:
        if row[0] != "table" or row[1] in engine:
            continue
        owner = row[1]
        _, columns, indexes, infos = bundles[owner]
        index_info = dict(infos)
        implicit = [index for index in indexes if index[3] in ("pk", "u")]
        null_schema = [
            item for item in objects if item[0] == "index" and item[2] == owner and item[3] is None
        ]
        model = None
        if _inv_canonical(owner, known) in known or implicit or null_schema:
            model = _inv_parse_table(row, known)
            if model is None or not _inv_columns_match(model, columns):
                return None
            has_ai = has_ai or model["autoincrement"]
        actual_obligations = []
        for index in indexes:
            _, name, unique, origin, partial = index
            schema_row = rows.get(name)
            if schema_row is not None and (schema_row[0] != "index" or schema_row[2] != owner):
                return None
            if origin == "c":
                if (
                    schema_row is None
                    or schema_row[3] is None
                    or _inv_fold(name).startswith("sqlite_")
                ):
                    return None
                continue
            if model is None or unique != 1 or partial != 0:
                return None
            match = re.fullmatch(
                "sqlite_autoindex_" + re.escape(owner) + r"_([1-9][0-9]*)",
                name,
                re.ASCII,
            )
            if match is None or len(match[1]) > 19 or int(match[1]) > 2**63 - 1:
                return None
            if not model["rowid"] and origin == "pk":
                if schema_row is not None:
                    return None
            elif schema_row is None or schema_row[3] is not None:
                return None
            else:
                engine.add(name)
            info = index_info[name]
            keys = _inv_auto_keys(info)
            if keys is None or not _inv_auxiliary_match(model, origin, info, columns):
                return None
            actual_obligations.append((origin, keys))
        if model is not None:
            expected_obligations = [
                (kind, tuple(tuple(key) for key in keys)) for kind, keys in model["autoindexes"]
            ]
            if sorted(actual_obligations) != sorted(expected_obligations):
                return None
        listed = {index[1] for index in indexes}
        if any(
            item[0] == "index" and item[2] == owner and item[1] not in listed for item in objects
        ):
            return None
    if has_ai and "sqlite_sequence" not in engine:
        return None
    if any(_inv_fold(row[1]).startswith("sqlite_") and row[1] not in engine for row in objects):
        return None
    logical_rows = tuple(
        sorted(
            (row for row in objects if row[1] not in engine),
            key=lambda row: (_inv_canonical(row[1], known), row[0]),
        )
    )
    engine_rows = tuple(
        sorted((row for row in objects if row[1] in engine), key=lambda row: (row[1], row[0]))
    )
    _inv_need(len(logical_rows) + len(engine_rows) == len(objects))
    logical = tuple((_inv_canonical(row[1], known), row[0]) for row in logical_rows)
    return _SuppliedInventoryProjection(
        logical, logical_rows, engine_rows, normalized, _current_profile_candidate(logical)
    )
