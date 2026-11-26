"""Component-local static SQL descriptions, without connection ownership or admission."""

from __future__ import annotations

import json
import re
import sqlite3
from functools import lru_cache
from typing import Any

# Fixed source-backed DDL; no database construction or test-fixture dependency.
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
    "CREATE TABLE INDEX UNIQUE TRIGGER IF NOT EXISTS PRIMARY KEY FOREIGN REFERENCES "
    "INTEGER TEXT REAL BLOB NOT NULL DEFAULT CHECK COLLATE AUTOINCREMENT ASC DESC "
    "ON UPDATE DELETE INSERT AFTER BEFORE OF WHEN BEGIN END SELECT RAISE ABORT "
    "SET WHERE OR AND INTO VALUES IGNORE FROM IN IS OLD NEW CASCADE RESTRICT "
    "NO ACTION MATCH NONE WITHOUT ROWID STRICT FOR EACH ROW".split()
)
_IDENTIFIERS = frozenset(
    word.lower()
    for _, ddl in _CATALOG.values()
    for word in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", ddl)
    if word.upper() not in _KEYWORDS
)
_COLLATIONS = frozenset({"BINARY", "NOCASE", "RTRIM"})
_TOKEN = re.compile(
    r"\s+|--[^\n]*(?:\n|$)|/\*[\s\S]*?\*/|"
    r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|`(?:``|[^`])*`|\[[^\]]*\]|"
    r"[A-Za-z_][A-Za-z0-9_]*|[0-9]+|!=|>=|<=|<>|==|[(),.;=+*/%<>-]"
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
            if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
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
            if not re.fullmatch(r"0|[1-9][0-9]*", word):
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
                and columns[keys[0][0]][1] == "INTEGER"
                and not inline_primary_desc
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
        if kind not in {"TABLE", "INDEX", "TRIGGER"} or unique and kind != "INDEX":
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
    # SQLite omits exactly the outer DEFAULT (...) wrapper in table_xinfo.
    # This adjusts only the observation check; the SQL wire keeps every token.
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
            or default != _pragma_default(column[3])
            or actual[5] != column[4]
            or actual[6] != column[5]
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
        if not re.fullmatch(r"sqlite_autoindex_" + re.escape(name) + r"_[1-9][0-9]*", row[1], re.I):
            raise _invalid()
        autoindexes.append([row[3], _index_keys(connection, row[1])])
    if _wire(sorted(autoindexes, key=_wire)) != _wire(obj["autoindexes"]):
        raise _invalid()


def component_shape_wire(connection: sqlite3.Connection, component: str) -> bytes:
    """Describe one component on a caller-owned connection using schema reads only.

    This is neither a whole-dataset profile check nor an admission/ownership proof.
    The caller retains connection, transaction and concurrency ownership.
    """
    expected = _expected(component)  # Reject unknown names before the first query.
    try:
        stamp = _read(connection, "PRAGMA main.schema_version")
        rows = _read(connection, "SELECT type,name,tbl_name,sql FROM main.sqlite_schema")
        required = {obj["name"]: obj for obj in expected["objects"]}
        all_objects = {obj["name"]: obj for name in _CATALOG for obj in _expected(name)["objects"]}
        by_name = {str(row[1]).lower(): row for row in rows}
        selected_tables = {name for name, obj in required.items() if obj["kind"] == "table"}
        for kind, raw_name, raw_table, _ in rows:
            name, table = str(raw_name).lower(), str(raw_table).lower()
            if table in selected_tables and kind in {"index", "trigger"}:
                if name.startswith("sqlite_autoindex_") and kind == "index":
                    continue
                known = all_objects.get(name)
                if known is None or known.get("table") != table or known["kind"] != kind:
                    raise _invalid()
        observed: dict[str, _Shape] = {}
        for name, obj in required.items():
            row = by_name.get(name)
            if row is None or row[0] != obj["kind"] or not isinstance(row[3], str):
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
                    or _index_keys(connection, name) != parsed[0]["keys"]
                ):
                    raise _invalid()
        if stamp != _read(connection, "PRAGMA main.schema_version"):
            raise _invalid()
        return _wire(
            {**expected, "objects": sorted(observed.values(), key=lambda o: (o["name"], o["kind"]))}
        )
    except sqlite3.Error:
        raise _invalid() from None
