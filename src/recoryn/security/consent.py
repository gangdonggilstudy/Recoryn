"""Execution-scoped, expiring consent and durable session revocation."""

from __future__ import annotations

import math
import sqlite3
import time
import uuid
from collections.abc import Callable
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


@dataclass(frozen=True)
class ConsentBinding:
    execution_id: str
    provider_id: str
    endpoint: str
    data_type: str
    grant_id: str
    grant_epoch: int


@dataclass(frozen=True)
class SendPermit:
    grant_id: str
    execution_id: str
    grant_epoch: int
    provider_id: str
    endpoint: str
    data_type: str
    session_id: str | None
    session_generation: int
    body_sha256: str
    reservation_id: str | None
    expires_at: float


class ConsentStore:
    @safe_operation
    def __init__(
        self, db_path: Path, *, ttl_seconds: float = 3600, clock: Callable[[], float] = time.time
    ) -> None:
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
                self._db.executescript("""
                    BEGIN IMMEDIATE;
                    CREATE TABLE IF NOT EXISTS security_execution(id INTEGER PRIMARY KEY, generation TEXT);
                    CREATE TABLE IF NOT EXISTS security_grants(
                        provider TEXT, endpoint TEXT, data_type TEXT, grant_id TEXT,
                        generation TEXT, epoch INTEGER, expires REAL, allowed INTEGER,
                        PRIMARY KEY(provider,endpoint,data_type));
                    CREATE TABLE IF NOT EXISTS security_sessions(
                        session_id TEXT PRIMARY KEY, generation INTEGER, revoked INTEGER);
                    CREATE TABLE IF NOT EXISTS security_local_endpoints(
                        endpoint TEXT PRIMARY KEY, generation TEXT, model_digest TEXT);
                    COMMIT;
                """)
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
        except BaseException:
            self._db.close()
            raise

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

    @safe_operation
    def grant(self, provider_id: str, endpoint: str, data_type: str) -> str:
        provider_id, data_type, endpoint = (
            identifier(provider_id),
            identifier(data_type),
            parse_endpoint(endpoint).url,
        )
        with self.coordinator.hold():
            self._active()
            if not self._local_allowed(endpoint):
                raise SecurityError("LOCAL_EXECUTION_UNVERIFIED")
            row = self._db.execute(
                "SELECT epoch FROM security_grants WHERE provider=? AND endpoint=? AND data_type=?",
                (provider_id, endpoint, data_type),
            ).fetchone()
            grant_id = uuid.uuid4().hex
            self._db.execute(
                "INSERT OR REPLACE INTO security_grants VALUES(?,?,?,?,?,?,?,1)",
                (
                    provider_id,
                    endpoint,
                    data_type,
                    grant_id,
                    self.execution_id,
                    (row[0] if row else 0) + 1,
                    self._clock() + self._ttl,
                ),
            )
            return grant_id

    @safe_operation
    def revoke(self, provider_id: str, endpoint: str, data_type: str) -> None:
        key = (identifier(provider_id), parse_endpoint(endpoint).url, identifier(data_type))
        with self.coordinator.hold():
            self._active()
            self._db.execute(
                "UPDATE security_grants SET allowed=0,epoch=epoch+1 WHERE provider=? AND endpoint=? AND data_type=?",
                key,
            )

    def _grant(self, provider_id: str, endpoint: str, data_type: str) -> sqlite3.Row:
        self._active()
        row: sqlite3.Row | None = self._db.execute(
            "SELECT * FROM security_grants WHERE provider=? AND endpoint=? AND data_type=?",
            (provider_id, endpoint, data_type),
        ).fetchone()
        if (
            row is None
            or not row["allowed"]
            or row["generation"] != self.execution_id
            or not self._clock() < row["expires"]
            or not self._local_allowed(endpoint)
        ):
            raise SecurityError("CONSENT_REQUIRED")
        return row

    @safe_operation
    def allowed(self, provider_id: str, endpoint: str, data_type: str) -> bool:
        with self.coordinator.hold():
            try:
                self._grant(
                    identifier(provider_id), parse_endpoint(endpoint).url, identifier(data_type)
                )
                return True
            except (SecurityError, sqlite3.Error):
                return False

    @staticmethod
    def _binding(row: sqlite3.Row) -> ConsentBinding:
        return ConsentBinding(
            row["generation"],
            row["provider"],
            row["endpoint"],
            row["data_type"],
            row["grant_id"],
            row["epoch"],
        )

    @safe_operation
    def capture_bindings(
        self, provider_id: str, endpoint: str, data_types: tuple[str, ...]
    ) -> tuple[ConsentBinding, ...]:
        """Freeze only currently allowed scopes; later grants cannot widen this plan."""
        provider_id, endpoint = identifier(provider_id), parse_endpoint(endpoint).url
        if type(data_types) is not tuple or not 1 <= len(data_types) <= 16:
            raise SecurityError("INVALID_CONSENT_SCOPES")
        scopes = tuple(identifier(kind) for kind in data_types)
        if len(set(scopes)) != len(scopes):
            raise SecurityError("INVALID_CONSENT_SCOPES")
        with self.coordinator.hold():
            self._active()
            captured = []
            for kind in scopes:
                try:
                    captured.append(self._binding(self._grant(provider_id, endpoint, kind)))
                except SecurityError as error:
                    if error.code != "CONSENT_REQUIRED":
                        raise
            return tuple(captured)

    @safe_operation
    def validate_binding(self, binding: ConsentBinding) -> None:
        if not isinstance(binding, ConsentBinding):
            raise SecurityError("INVALID_CONSENT_BINDING")
        with self.coordinator.hold():
            row = self._grant(binding.provider_id, binding.endpoint, binding.data_type)
            if binding != self._binding(row):
                raise SecurityError("PERMIT_REVOKED")

    @safe_operation
    def bind_session(self, session_id: str, generation: int = 0) -> None:
        identifier(session_id)
        if type(generation) is not int or generation < 0:
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

    def _session(self, session_id: str | None, generation: int) -> None:
        if session_id is None:
            return
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
        session_id: str | None = None,
        session_generation: int = 0,
        reservation_id: str | None = None,
        expected_grant: ConsentBinding | None = None,
    ) -> SendPermit:
        provider_id, endpoint, data_type = (
            identifier(provider_id),
            parse_endpoint(endpoint).url,
            identifier(data_type),
        )
        with self.coordinator.hold():
            row = self._grant(provider_id, endpoint, data_type)
            if expected_grant is not None and expected_grant != self._binding(row):
                raise SecurityError("PERMIT_REVOKED")
            self._session(session_id, session_generation)
            return SendPermit(
                row["grant_id"],
                self.execution_id,
                row["epoch"],
                provider_id,
                endpoint,
                data_type,
                session_id,
                session_generation,
                body_sha256,
                reservation_id,
                min(row["expires"], self._clock() + 30),
            )

    @safe_operation
    def validate(self, permit: SendPermit) -> None:
        with self.coordinator.hold():
            row = self._grant(permit.provider_id, permit.endpoint, permit.data_type)
            if (
                permit.execution_id != self.execution_id
                or permit.grant_id != row["grant_id"]
                or permit.grant_epoch != row["epoch"]
                or not self._clock() < permit.expires_at
            ):
                raise SecurityError("PERMIT_REVOKED")
            self._session(permit.session_id, permit.session_generation)
