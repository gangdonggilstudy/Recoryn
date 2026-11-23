"""Execution-scoped, expiring consent and durable session revocation."""

from __future__ import annotations

import math
import sqlite3
import time
import uuid
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from ._core import (
    Coordinator,
    SecurityError,
    check_path,
    connect,
    duration,
    identifier,
    safe_operation,
)
from ._core import endpoint as parse_endpoint

CONSENT_POLICY_VERSION = 2
_MAX_INT = 2**63 - 1


def _integer(value: object, *, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= _MAX_INT:
        raise SecurityError("INVALID_CONSENT_CONTEXT")
    return value


def _capability(value: str) -> str:
    if type(value) is not str or value not in {"stt", "summary", "diarization"}:
        raise SecurityError("INVALID_CONSENT_CONTEXT")
    return value


@dataclass(frozen=True)
class ConsentScope:
    kind: str
    scope_id: str

    def __post_init__(self) -> None:
        if self.kind == "session":
            identifier(self.scope_id)
        elif self.kind != "library" or type(self.scope_id) is not str or self.scope_id != "":
            raise SecurityError("INVALID_CONSENT_SCOPE")

    @classmethod
    def session(cls, session_id: str) -> ConsentScope:
        return cls("session", session_id)

    @classmethod
    def library(cls) -> ConsentScope:
        return cls("library", "")


@dataclass(frozen=True)
class ConsentRequest:
    session_id: str
    session_generation: int
    capability: str
    policy_version: int

    def __post_init__(self) -> None:
        identifier(self.session_id)
        _integer(self.session_generation)
        _capability(self.capability)
        _integer(self.policy_version, minimum=1)


def _context(scope: ConsentScope, request: ConsentRequest) -> None:
    if type(scope) is not ConsentScope or type(request) is not ConsentRequest:
        raise SecurityError("INVALID_CONSENT_CONTEXT")


@dataclass(frozen=True)
class ConsentBinding:
    execution_id: str
    provider_id: str
    endpoint: str
    data_type: str
    grant_id: str
    grant_epoch: int
    scope: ConsentScope
    request: ConsentRequest

    def __post_init__(self) -> None:
        _context(self.scope, self.request)
        _integer(self.grant_epoch)


@dataclass(frozen=True)
class SendPermit:
    grant_id: str
    execution_id: str
    grant_epoch: int
    provider_id: str
    endpoint: str
    data_type: str
    session_id: str
    session_generation: int
    body_sha256: str
    reservation_id: str | None
    expires_at: float
    scope: ConsentScope
    request: ConsentRequest

    def __post_init__(self) -> None:
        _context(self.scope, self.request)
        _integer(self.grant_epoch)
        _integer(self.session_generation)
        if (
            (self.session_id, self.session_generation)
            != (self.request.session_id, self.request.session_generation)
            or type(self.expires_at) not in (int, float)
            or not math.isfinite(self.expires_at)
        ):
            raise SecurityError("INVALID_CONSENT_CONTEXT")

    @property
    def binding(self) -> ConsentBinding:
        return ConsentBinding(
            self.execution_id,
            self.provider_id,
            self.endpoint,
            self.data_type,
            self.grant_id,
            self.grant_epoch,
            self.scope,
            self.request,
        )


class ConsentStore:
    @safe_operation
    def __init__(
        self,
        db_path: Path,
        *,
        ttl_seconds: float = 3600,
        clock: Callable[[], float] = time.time,
        policy_version: int = CONSENT_POLICY_VERSION,
    ) -> None:
        _integer(policy_version, minimum=1)
        self.coordinator = Coordinator(db_path)
        self.db_path = self.coordinator.path
        self._clock = clock
        self._last_clock = float(clock())
        self._ttl = duration(ttl_seconds)
        self.execution_id = uuid.uuid4().hex
        self._closed = False
        self._db = connect(self.db_path)
        try:
            with self.coordinator.hold():
                self._db.execute("BEGIN IMMEDIATE")
                self._initialize(policy_version)
                columns = {
                    row[1]
                    for row in self._db.execute("PRAGMA table_info(security_local_endpoints)")
                }
                if "expires" not in columns:
                    self._db.execute(
                        "ALTER TABLE security_local_endpoints ADD COLUMN expires REAL NOT NULL DEFAULT 0"
                    )
                self._db.execute(
                    "INSERT INTO security_execution VALUES(1,?) ON CONFLICT(id) DO UPDATE SET generation=excluded.generation",
                    (self.execution_id,),
                )
                self._db.execute("COMMIT")
        except BaseException:
            try:
                if self._db.in_transaction:
                    self._db.execute("ROLLBACK")
            finally:
                self._db.close()
                self._closed = True
            raise

    def _initialize(self, policy_version: int) -> None:
        tables = {
            row[0] for row in self._db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        pair = {"security_consent_meta", "security_grants_v2"}
        if tables & pair and not pair <= tables:
            raise SecurityError("UNSUPPORTED_SCHEMA")
        for sql in (
            "CREATE TABLE IF NOT EXISTS security_execution(id INTEGER PRIMARY KEY, generation TEXT)",
            "CREATE TABLE IF NOT EXISTS security_sessions(session_id TEXT PRIMARY KEY, generation INTEGER, revoked INTEGER)",
            "CREATE TABLE IF NOT EXISTS security_local_endpoints(endpoint TEXT PRIMARY KEY, generation TEXT, model_digest TEXT)",
            "CREATE TABLE IF NOT EXISTS security_consent_meta(id INTEGER PRIMARY KEY CHECK(id=1), schema_version INTEGER NOT NULL, policy_version INTEGER NOT NULL)",
            """CREATE TABLE IF NOT EXISTS security_grants_v2(
                provider TEXT NOT NULL, endpoint TEXT NOT NULL, capability TEXT NOT NULL,
                data_type TEXT NOT NULL, scope_kind TEXT NOT NULL, scope_id TEXT NOT NULL,
                policy_version INTEGER NOT NULL CHECK(policy_version>0),
                grant_id TEXT NOT NULL UNIQUE, generation TEXT NOT NULL,
                epoch INTEGER NOT NULL CHECK(epoch>=0), issued_at REAL NOT NULL,
                expires REAL NOT NULL, allowed INTEGER NOT NULL CHECK(allowed IN (0,1)),
                revoked_at REAL,
                PRIMARY KEY(provider,endpoint,capability,data_type,scope_kind,scope_id,policy_version),
                CHECK((scope_kind='session' AND length(scope_id)>0) OR (scope_kind='library' AND scope_id=''))
            )""",
        ):
            self._db.execute(sql)
        expected = {
            "security_execution": ("id", "generation"),
            "security_sessions": ("session_id", "generation", "revoked"),
            "security_consent_meta": ("id", "schema_version", "policy_version"),
            "security_grants_v2": (
                "provider",
                "endpoint",
                "capability",
                "data_type",
                "scope_kind",
                "scope_id",
                "policy_version",
                "grant_id",
                "generation",
                "epoch",
                "issued_at",
                "expires",
                "allowed",
                "revoked_at",
            ),
        }
        for table, columns in expected.items():
            actual = tuple(row[1] for row in self._db.execute(f"PRAGMA table_info({table})"))
            if actual != columns:
                raise SecurityError(
                    "SECURITY_STATE_UNAVAILABLE"
                    if table in {"security_execution", "security_sessions"}
                    else "UNSUPPORTED_SCHEMA"
                )
        info = list(self._db.execute("PRAGMA table_info(security_grants_v2)"))
        if [row[5] for row in info] != [1, 2, 3, 4, 5, 6, 7, 0, 0, 0, 0, 0, 0, 0]:
            raise SecurityError("UNSUPPORTED_SCHEMA")
        rows = list(self._db.execute("SELECT * FROM security_consent_meta"))
        if pair <= tables:
            if len(rows) != 1 or rows[0]["id"] != 1 or rows[0]["schema_version"] != 2:
                raise SecurityError("UNSUPPORTED_SCHEMA")
            if policy_version < _integer(rows[0]["policy_version"], minimum=1):
                raise SecurityError("CONSENT_POLICY_CHANGED")
        self._db.execute(
            "INSERT OR REPLACE INTO security_consent_meta VALUES(1,2,?)", (policy_version,)
        )

    @property
    def policy_version(self) -> int:
        with self.coordinator.hold():
            self._active()
            return self._policy()

    def _policy(self, expected: int | None = None) -> int:
        row = self._db.execute(
            "SELECT policy_version FROM security_consent_meta WHERE id=1 AND schema_version=2"
        ).fetchone()
        if row is None:
            raise SecurityError("UNSUPPORTED_SCHEMA")
        current = _integer(row[0], minimum=1)
        if expected is not None and expected != current:
            raise SecurityError("CONSENT_POLICY_CHANGED")
        return current

    @safe_operation
    def advance_policy_version(self, version: int) -> None:
        _integer(version, minimum=1)
        with self.coordinator.hold():
            self._active()
            if version < self._policy():
                raise SecurityError("CONSENT_POLICY_CHANGED")
            self._db.execute(
                "UPDATE security_consent_meta SET policy_version=? WHERE id=1", (version,)
            )

    @property
    def grant_deadline(self) -> float:
        """Preview the exact deadline to freeze before a confirmation dialog."""
        with self.coordinator.hold():
            self._active()
            return float(self._clock()) + self._ttl

    def close(self) -> None:
        with self.coordinator.hold():
            if not self._closed:
                self._db.close()
                self._closed = True

    def __enter__(self) -> ConsentStore:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _active(self) -> None:
        if self._closed:
            raise SecurityError("CONSENT_STORE_CLOSED")
        now = float(self._clock())
        if not math.isfinite(now) or now < self._last_clock:
            raise SecurityError("CONSENT_CLOCK_INVALID")
        self._last_clock = now
        row = self._db.execute("SELECT generation FROM security_execution WHERE id=1").fetchone()
        if row is None or row[0] != self.execution_id:
            raise SecurityError("EXECUTION_CHANGED")

    @safe_operation
    def approve_local_endpoint(
        self, endpoint: str, model_digest: str, *, ttl_seconds: float = 3600
    ) -> None:
        parsed = parse_endpoint(endpoint)
        if (
            not parsed.loopback
            or len(model_digest) != 64
            or any(c not in "0123456789abcdef" for c in model_digest)
        ):
            raise SecurityError("LOCAL_EXECUTION_UNVERIFIED")
        with self.coordinator.hold():
            self._active()
            self._db.execute(
                "INSERT OR REPLACE INTO security_local_endpoints VALUES(?,?,?,?)",
                (
                    parsed.url,
                    self.execution_id,
                    model_digest,
                    self._clock() + duration(ttl_seconds),
                ),
            )

    def _local_allowed(self, endpoint: str) -> bool:
        parsed = parse_endpoint(endpoint)
        return (
            not parsed.loopback
            or self._db.execute(
                "SELECT 1 FROM security_local_endpoints WHERE endpoint=? AND generation=? AND expires>?",
                (parsed.url, self.execution_id, self._clock()),
            ).fetchone()
            is not None
        )

    @staticmethod
    def _key(
        provider_id: str,
        endpoint: str,
        data_type: str,
        capability: str,
        scope: ConsentScope,
        policy_version: int,
    ) -> tuple[str, str, str, str, str, str, int]:
        if type(scope) is not ConsentScope:
            raise SecurityError("INVALID_CONSENT_SCOPE")
        return (
            identifier(provider_id),
            parse_endpoint(endpoint).url,
            _capability(capability),
            identifier(data_type),
            scope.kind,
            scope.scope_id,
            _integer(policy_version, minimum=1),
        )

    _WHERE = "provider=? AND endpoint=? AND capability=? AND data_type=? AND scope_kind=? AND scope_id=? AND policy_version=?"

    @safe_operation
    def grant(
        self,
        provider_id: str,
        endpoint: str,
        data_type: str,
        *,
        capability: str,
        scope: ConsentScope,
        policy_version: int,
        expires_at: float | None = None,
    ) -> str:
        key = self._key(provider_id, endpoint, data_type, capability, scope, policy_version)
        with self.coordinator.hold():
            self._active()
            self._policy(policy_version)
            now = float(self._clock())
            expires = now + self._ttl if expires_at is None else expires_at
            if (
                type(expires) not in (int, float)
                or not math.isfinite(expires)
                or not now < expires <= now + self._ttl
            ):
                raise SecurityError("CONSENT_REQUIRED")
            if not self._local_allowed(key[1]):
                raise SecurityError("LOCAL_EXECUTION_UNVERIFIED")
            row = self._db.execute(
                "SELECT epoch FROM security_grants_v2 WHERE " + self._WHERE, key
            ).fetchone()
            epoch = _integer((_integer(row[0]) if row else 0) + 1)
            grant_id = uuid.uuid4().hex
            self._db.execute(
                "INSERT OR REPLACE INTO security_grants_v2 VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1,NULL)",
                (*key, grant_id, self.execution_id, epoch, now, expires),
            )
            return grant_id

    @safe_operation
    def revoke(
        self,
        provider_id: str,
        endpoint: str,
        data_type: str,
        *,
        capability: str,
        scope: ConsentScope,
        policy_version: int,
    ) -> None:
        key = self._key(provider_id, endpoint, data_type, capability, scope, policy_version)
        with self.coordinator.hold():
            self._active()
            row = self._db.execute(
                "SELECT epoch FROM security_grants_v2 WHERE " + self._WHERE, key
            ).fetchone()
            if row is not None:
                epoch = _integer(_integer(row[0]) + 1)
                self._db.execute(
                    "UPDATE security_grants_v2 SET allowed=0,epoch=?,revoked_at=? WHERE "
                    + self._WHERE,
                    (epoch, self._clock(), *key),
                )

    @safe_operation
    def revoke_endpoint(self, provider_id: str, endpoint: str) -> None:
        provider_id, endpoint = identifier(provider_id), parse_endpoint(endpoint).url
        with self.coordinator.hold():
            self._active()
            # Setting allowed=0 is sufficient even at the maximum representable epoch.
            self._db.execute(
                "UPDATE security_grants_v2 SET allowed=0,epoch=MIN(epoch+1,?),revoked_at=? WHERE provider=? AND endpoint=?",
                (_MAX_INT, self._clock(), provider_id, endpoint),
            )

    def _grant(
        self,
        provider_id: str,
        endpoint: str,
        data_type: str,
        scope: ConsentScope,
        request: ConsentRequest,
    ) -> sqlite3.Row:
        _context(scope, request)
        key = self._key(
            provider_id, endpoint, data_type, request.capability, scope, request.policy_version
        )
        self._active()
        self._policy(request.policy_version)
        row: sqlite3.Row | None = self._db.execute(
            "SELECT * FROM security_grants_v2 WHERE " + self._WHERE,
            key,
        ).fetchone()
        if (
            (scope.kind == "session" and scope.scope_id != request.session_id)
            or row is None
            or row["allowed"] != 1
            or row["generation"] != self.execution_id
            or not self._clock() < row["expires"]
            or not self._local_allowed(key[1])
        ):
            raise SecurityError("CONSENT_REQUIRED")
        return row

    @safe_operation
    def allowed(
        self,
        provider_id: str,
        endpoint: str,
        data_type: str,
        *,
        scope: ConsentScope,
        request: ConsentRequest,
    ) -> bool:
        with self.coordinator.hold():
            try:
                self._grant(provider_id, endpoint, data_type, scope, request)
                self._session(request.session_id, request.session_generation)
                return True
            except (SecurityError, sqlite3.Error):
                return False

    @safe_operation
    def grant_info(
        self,
        provider_id: str,
        endpoint: str,
        data_type: str,
        *,
        capability: str,
        scope: ConsentScope,
        policy_version: int,
    ) -> dict[str, object] | None:
        """Non-authorizing metadata for the exact key; never issues a permit."""
        key = self._key(provider_id, endpoint, data_type, capability, scope, policy_version)
        with self.coordinator.hold():
            self._active()
            row = self._db.execute(
                "SELECT * FROM security_grants_v2 WHERE " + self._WHERE, key
            ).fetchone()
            if row is None:
                return None
            result = dict(row)
            result["active"] = (
                row["allowed"] == 1
                and row["generation"] == self.execution_id
                and row["policy_version"] == self._policy()
                and self._clock() < row["expires"]
                and self._local_allowed(key[1])
            )
            return result

    def scope_view(
        self,
        provider_id: str | None,
        endpoint: str | None,
        data_type: str | None,
        *,
        capability: str,
        scope: ConsentScope | None,
        session_id: str | None,
    ) -> dict[str, object]:
        """Best-effort, read-only UI facts; never binds, authorizes or waits on policy.

        The process lock is only tried. An independent SQLite read transaction
        avoids sharing an in-flight policy transaction and has no busy wait.
        No cross-process coordinator/file lock, active-clock update or DDL is used.
        Execution must still capture fresh bindings through the authorizing API.
        """
        if not self.coordinator.lock.acquire(blocking=False):
            return {"state": "checking"}
        try:
            if self._closed:
                return {"state": "unavailable"}
            if session_id is not None:
                identifier(session_id)
            _capability(capability)
            now = float(self._clock())
            if not math.isfinite(now) or now < self._last_clock:
                return {"state": "unavailable"}
            with closing(
                sqlite3.connect(
                    self.db_path.absolute().as_uri() + "?mode=ro",
                    uri=True,
                    timeout=0,
                    isolation_level=None,
                )
            ) as db:
                db.row_factory = sqlite3.Row
                db.execute("PRAGMA query_only=ON")
                db.execute("BEGIN")
                if db.execute("PRAGMA user_version").fetchone()[0] not in (0, 1):
                    return {"state": "unavailable"}
                execution = db.execute(
                    "SELECT generation FROM security_execution WHERE id=1"
                ).fetchone()
                policy = db.execute(
                    "SELECT policy_version FROM security_consent_meta WHERE id=1 AND schema_version=2"
                ).fetchone()
                if execution is None or execution[0] != self.execution_id or policy is None:
                    return {"state": "unavailable"}
                version = _integer(policy[0], minimum=1)
                session_state = "ready"
                if session_id is not None:
                    session = db.execute(
                        "SELECT generation,revoked FROM security_sessions WHERE session_id=?",
                        (session_id,),
                    ).fetchone()
                    deleted_table = db.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='deleted_sessions'"
                    ).fetchone()
                    if (
                        session is not None
                        and (session[0] != 0 or session[1])
                        or deleted_table
                        and db.execute(
                            "SELECT 1 FROM deleted_sessions WHERE session_id=?", (session_id,)
                        ).fetchone()
                    ):
                        session_state = "deleted"
                    journal = check_path(self.db_path.parent / "deletion-journal")
                    if journal.exists():
                        if (journal / (session_id + ".json")).exists():
                            session_state = "deleted"
                        elif any(p.name.startswith(".tmp-") for p in journal.iterdir()):
                            session_state = "checking"

                def info(selected: ConsentScope | None) -> dict[str, object] | None:
                    if (
                        provider_id is None
                        or endpoint is None
                        or data_type is None
                        or selected is None
                    ):
                        return None
                    key = self._key(provider_id, endpoint, data_type, capability, selected, version)
                    row = db.execute(
                        "SELECT * FROM security_grants_v2 WHERE " + self._WHERE, key
                    ).fetchone()
                    if row is None:
                        return None
                    if row["generation"] != self.execution_id:
                        state = "previous"
                    elif row["allowed"] != 1:
                        state = "revoked"
                    elif now >= row["expires"]:
                        state = "expired"
                    elif (
                        parse_endpoint(key[1]).loopback
                        and not db.execute(
                            "SELECT 1 FROM security_local_endpoints WHERE endpoint=? AND generation=? AND expires>?",
                            (key[1], self.execution_id, now),
                        ).fetchone()
                    ):
                        state = "local_unverified"
                    else:
                        state = "active"
                    return {"state": state, "expires": row["expires"]}

                return {
                    "state": session_state,
                    "version": version,
                    "selected": info(scope),
                    "library": info(ConsentScope.library()),
                }
        except (SecurityError, sqlite3.Error, OSError, ValueError, TypeError):
            return {"state": "unavailable"}
        finally:
            self.coordinator.lock.release()

    @staticmethod
    def _binding(row: sqlite3.Row, request: ConsentRequest) -> ConsentBinding:
        return ConsentBinding(
            row["generation"],
            row["provider"],
            row["endpoint"],
            row["data_type"],
            row["grant_id"],
            row["epoch"],
            ConsentScope(row["scope_kind"], row["scope_id"]),
            request,
        )

    @safe_operation
    def capture_bindings(
        self,
        provider_id: str,
        endpoint: str,
        data_types: tuple[str, ...],
        *,
        scope: ConsentScope,
        request: ConsentRequest,
    ) -> tuple[ConsentBinding, ...]:
        """Freeze this request and explicitly selected grant key, without fallback."""
        _context(scope, request)
        provider_id, endpoint = identifier(provider_id), parse_endpoint(endpoint).url
        if type(data_types) is not tuple or not 1 <= len(data_types) <= 16:
            raise SecurityError("INVALID_CONSENT_SCOPES")
        types = tuple(identifier(kind) for kind in data_types)
        if len(set(types)) != len(types):
            raise SecurityError("INVALID_CONSENT_SCOPES")
        with self.coordinator.hold():
            self._active()
            self._policy(request.policy_version)
            self._session(request.session_id, request.session_generation)
            captured = []
            for kind in types:
                try:
                    captured.append(
                        self._binding(
                            self._grant(provider_id, endpoint, kind, scope, request), request
                        )
                    )
                except SecurityError as error:
                    if error.code != "CONSENT_REQUIRED":
                        raise
            return tuple(captured)

    @safe_operation
    def validate_binding(self, binding: ConsentBinding) -> None:
        if type(binding) is not ConsentBinding:
            raise SecurityError("INVALID_CONSENT_BINDING")
        with self.coordinator.hold():
            row = self._grant(
                binding.provider_id,
                binding.endpoint,
                binding.data_type,
                binding.scope,
                binding.request,
            )
            if binding != self._binding(row, binding.request):
                raise SecurityError("PERMIT_REVOKED")
            self._session(binding.request.session_id, binding.request.session_generation)

    @safe_operation
    def bind_session(self, session_id: str, generation: int = 0) -> None:
        identifier(session_id)
        if type(generation) is not int or not 0 <= generation <= _MAX_INT:
            raise SecurityError("INVALID_SESSION_GENERATION")
        with self.coordinator.hold():
            self._active()
            row = self._db.execute(
                "SELECT generation,revoked FROM security_sessions WHERE session_id=?", (session_id,)
            ).fetchone()
            if row is not None and (row[0] != generation or row[1]):
                raise SecurityError("SESSION_REVOKED")
            self._db.execute(
                "INSERT OR IGNORE INTO security_sessions VALUES(?,?,0)", (session_id, generation)
            )
            self._session(session_id, generation)

    @safe_operation
    def revoke_session(self, session_id: str) -> None:
        identifier(session_id)
        with self.coordinator.hold():
            self._active()
            self._db.execute(
                "INSERT INTO security_sessions VALUES(?,1,1) ON CONFLICT(session_id) DO UPDATE SET generation=generation+1,revoked=1",
                (session_id,),
            )

    def _session(self, session_id: str, generation: int) -> None:
        row = self._db.execute(
            "SELECT generation,revoked FROM security_sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        if row is None or row[0] != generation or row[1]:
            raise SecurityError("SESSION_REVOKED")
        journal = check_path(self.db_path.parent / "deletion-journal")
        if journal.exists() and (
            any(p.name.startswith(".tmp-") for p in journal.iterdir())
            or (journal / (session_id + ".json")).exists()
        ):
            raise SecurityError("SESSION_REVOKED")
        table = self._db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='deleted_sessions' AND type='table'"
        ).fetchone()
        if (
            table
            and self._db.execute(
                "SELECT 1 FROM deleted_sessions WHERE session_id=?", (session_id,)
            ).fetchone()
        ):
            raise SecurityError("SESSION_REVOKED")

    @safe_operation
    def permit(
        self,
        provider_id: str,
        endpoint: str,
        data_type: str,
        body_sha256: str,
        *,
        scope: ConsentScope,
        request: ConsentRequest,
        expected_grant: ConsentBinding,
        reservation_id: str | None = None,
    ) -> SendPermit:
        provider_id, endpoint, data_type = (
            identifier(provider_id),
            parse_endpoint(endpoint).url,
            identifier(data_type),
        )
        with self.coordinator.hold():
            row = self._grant(provider_id, endpoint, data_type, scope, request)
            if type(expected_grant) is not ConsentBinding or expected_grant != self._binding(
                row, request
            ):
                raise SecurityError("PERMIT_REVOKED")
            self._session(request.session_id, request.session_generation)
            return SendPermit(
                row["grant_id"],
                self.execution_id,
                row["epoch"],
                provider_id,
                endpoint,
                data_type,
                request.session_id,
                request.session_generation,
                body_sha256,
                reservation_id,
                min(row["expires"], self._clock() + 30),
                scope,
                request,
            )

    @safe_operation
    def validate(self, permit: SendPermit) -> None:
        if type(permit) is not SendPermit:
            raise SecurityError("INVALID_CONSENT_BINDING")
        with self.coordinator.hold():
            row = self._grant(
                permit.provider_id, permit.endpoint, permit.data_type, permit.scope, permit.request
            )
            if (
                permit.binding != self._binding(row, permit.request)
                or not self._clock() < permit.expires_at
            ):
                raise SecurityError("PERMIT_REVOKED")
            self._session(permit.session_id, permit.session_generation)
