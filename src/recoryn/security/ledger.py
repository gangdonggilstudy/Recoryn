"""Integer cost reservations with a fail-closed rollback witness, independent of sessions."""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from weakref import ReferenceType, ref

from . import cost_catalog
from ._core import (
    Coordinator,
    SecurityError,
    canonical,
    check_path,
    connect,
    digest,
    identifier,
    money,
    safe_operation,
)
from .cost import CostPolicy, CostQuote, CostRequest, clock_value, cost_headers, currency, quote

_V1 = {"security_cost_meta", "security_cost_accounts", "security_cost_requests"}
_V2 = {
    "security_cost_accounts_v2",
    "security_cost_requests_v2",
    "security_cost_usage_events",
    "security_cost_meta_v2",
}


@dataclass(frozen=True)
class _Dispatch:
    reservation_id: str
    account_id: str
    provider: str
    target: str
    data_type: str
    operation: str
    headers: tuple[tuple[str, str], ...]
    body: bytes
    policy: CostPolicy
    quote_json: str
    deadline: float
    valid_from: int | None
    valid_until: int | None


class CostLedger:
    @safe_operation
    def __init__(
        self,
        db_path: Path,
        *,
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.coordinator = Coordinator(db_path)
        self.db_path = self.coordinator.path
        self._witness = check_path(self.db_path.with_name(self.db_path.name + ".cost-witness"))
        self._closed = False
        self._clock, self._monotonic = clock, monotonic
        self._last_now = clock_value(clock())
        self._quote_deadlines: dict[str, float] = {}
        self._dispatches: dict[str, _Dispatch] = {}
        self._verified_stamp: tuple[object, ...] | None = None
        self._balance_cache: dict[str, dict[str, int]] = {}
        self._exposure_faults: dict[str, str | None] = {}
        self._prepared_quotes: OrderedDict[
            int, tuple[ReferenceType[CostRequest], CostPolicy, CostQuote]
        ] = OrderedDict()
        self._reserved_quotes: OrderedDict[
            str, tuple[ReferenceType[CostRequest], CostPolicy, CostQuote]
        ] = OrderedDict()
        if self._witness.exists() and not self.db_path.exists():
            raise SecurityError("LEDGER_ROLLBACK_DETECTED")
        self._db = connect(self.db_path)
        try:
            with self.coordinator.hold():
                tables = self._tables()
                if tables & _V2:
                    if not (_V1 | _V2) <= tables:
                        raise SecurityError("LEDGER_ROLLBACK_DETECTED")
                    self._verify()
                    self._ensure_clock_audit()
                    return
                if self._witness.exists():
                    if not _V1 <= tables or self._read_witness().get("schema_version") != 1:
                        raise SecurityError("LEDGER_ROLLBACK_DETECTED")
                elif tables & _V1:
                    raise SecurityError("LEDGER_ROLLBACK_DETECTED")
                self._db.executescript("""
                    BEGIN IMMEDIATE;
                    CREATE TABLE IF NOT EXISTS security_cost_meta(id INTEGER PRIMARY KEY, revision INTEGER);
                    CREATE TABLE IF NOT EXISTS security_cost_accounts(provider TEXT PRIMARY KEY, amount_limit INTEGER);
                    CREATE TABLE IF NOT EXISTS security_cost_requests(
                        reservation_id TEXT PRIMARY KEY, provider TEXT, request_id TEXT,
                        amount INTEGER, actual INTEGER, state TEXT,
                        UNIQUE(provider,request_id));
                    COMMIT;
                """)
                meta = self._db.execute(
                    "SELECT revision FROM security_cost_meta WHERE id=1"
                ).fetchone()
                if meta is None:
                    if self._witness.exists():
                        raise SecurityError("LEDGER_ROLLBACK_DETECTED")
                    self._db.execute("INSERT INTO security_cost_meta VALUES(1,0)")
                    self._write_witness()
                self._verify()
                self._initialize_v2()
        except BaseException:
            self._db.close()
            self._closed = True
            raise

    def _tables(self) -> set[str]:
        return {
            row[0] for row in self._db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }

    def _read_witness(self) -> dict[str, Any]:
        check_path(self._witness)
        if self._witness.stat().st_size > 4096:
            raise SecurityError("LEDGER_ROLLBACK_DETECTED")
        value = json.loads(self._witness.read_bytes())
        if type(value) is not dict:
            raise SecurityError("LEDGER_ROLLBACK_DETECTED")
        return value

    def _initialize_v2(self) -> None:
        """Only reached after authenticating v1; never bless the current DB anew."""
        predecessor = digest(canonical(self._state()))
        legacy = bool(
            self._db.execute("SELECT 1 FROM security_cost_accounts LIMIT 1").fetchone()
            or self._db.execute("SELECT 1 FROM security_cost_requests LIMIT 1").fetchone()
        )
        revision = self._db.execute(
            "SELECT revision FROM security_cost_meta WHERE id=1"
        ).fetchone()[0]
        self._db.execute("BEGIN IMMEDIATE")
        try:
            for sql in (
                """CREATE TABLE security_cost_accounts_v2(
                    account_id TEXT PRIMARY KEY, provider TEXT NOT NULL, currency TEXT NOT NULL,
                    period_start_utc INTEGER NOT NULL CHECK(period_start_utc>=0),
                    period_end_utc INTEGER NOT NULL CHECK(period_end_utc>period_start_utc),
                    policy_version INTEGER NOT NULL CHECK(policy_version>0),
                    amount_limit INTEGER NOT NULL CHECK(amount_limit>=0),
                    blocked INTEGER NOT NULL DEFAULT 0 CHECK(blocked IN (0,1)),
                    UNIQUE(provider,currency,period_start_utc,period_end_utc))""",
                """CREATE TABLE security_cost_requests_v2(
                    reservation_id TEXT PRIMARY KEY, provider TEXT NOT NULL, request_id TEXT NOT NULL,
                    account_id TEXT NOT NULL REFERENCES security_cost_accounts_v2(account_id),
                    reserved_amount INTEGER NOT NULL CHECK(reserved_amount>=0),
                    actual INTEGER CHECK(actual>=0), state TEXT NOT NULL CHECK(state IN ('RESERVED','UNKNOWN','SETTLED','RELEASED')),
                    quote_kind TEXT NOT NULL CHECK(quote_kind IN ('VERIFIED','USER_CAP','LEGACY_UNSCOPED')),
                    model_revision TEXT, profile_id TEXT, endpoint_digest TEXT, body_sha256 TEXT,
                    byte_length INTEGER CHECK(byte_length>0), input_upper INTEGER CHECK(input_upper>=0),
                    output_upper INTEGER CHECK(output_upper>=0), price_as_of_utc INTEGER,
                    valid_until_utc INTEGER, catalog_digest TEXT, request_fingerprint TEXT NOT NULL,
                    request_json TEXT, quote_json TEXT, policy_json TEXT, dispatch_id TEXT,
                    UNIQUE(provider,request_id),
                    CHECK(quote_kind!='VERIFIED' OR (price_as_of_utc IS NOT NULL AND valid_until_utc IS NOT NULL AND input_upper IS NOT NULL AND output_upper IS NOT NULL)),
                    CHECK(quote_kind='LEGACY_UNSCOPED' OR (body_sha256 IS NOT NULL AND byte_length IS NOT NULL AND quote_json IS NOT NULL AND policy_json IS NOT NULL AND request_json IS NOT NULL)))""",
                """CREATE TABLE security_cost_usage_events(
                    reservation_id TEXT NOT NULL REFERENCES security_cost_requests_v2(reservation_id),
                    source TEXT NOT NULL, event_id TEXT NOT NULL, version INTEGER NOT NULL CHECK(version>0),
                    kind TEXT NOT NULL CHECK(kind IN ('provisional','final')), currency TEXT NOT NULL,
                    period_id TEXT NOT NULL, amount INTEGER NOT NULL CHECK(amount>=0), payload_digest TEXT NOT NULL,
                    PRIMARY KEY(reservation_id,source,event_id))""",
                """CREATE TABLE security_cost_meta_v2(
                    id INTEGER PRIMARY KEY CHECK(id=1), schema_version INTEGER NOT NULL CHECK(schema_version=2),
                    revision INTEGER NOT NULL, witness_protocol_version INTEGER NOT NULL CHECK(witness_protocol_version=2),
                    predecessor_v1_state_digest TEXT NOT NULL, migration_state TEXT NOT NULL,
                    clock_high_water_utc REAL NOT NULL, adopted_providers TEXT NOT NULL,
                    clock_reset_audit TEXT NOT NULL DEFAULT '[]')""",
            ):
                self._db.execute(sql)
            self._db.execute(
                "INSERT INTO security_cost_meta_v2(id,schema_version,revision,witness_protocol_version,predecessor_v1_state_digest,migration_state,clock_high_water_utc,adopted_providers) VALUES(1,2,?,2,?,?,?,'[]')",
                (revision, predecessor, "LEGACY_UNSCOPED" if legacy else "READY", self._last_now),
            )
            self._write_witness()
            self._db.execute("COMMIT")
        except BaseException:
            if self._db.in_transaction:
                self._db.execute("ROLLBACK")
            raise

    def _ensure_clock_audit(self) -> None:
        """Authenticate the old v2 witness before adding the recovery audit field."""
        columns = {row[1] for row in self._db.execute("PRAGMA table_info(security_cost_meta_v2)")}
        if "clock_reset_audit" not in columns:
            high = self._db.execute(
                "SELECT clock_high_water_utc FROM security_cost_meta_v2 WHERE id=1"
            ).fetchone()[0]
            self._change(
                lambda: self._db.execute(
                    "ALTER TABLE security_cost_meta_v2 ADD COLUMN clock_reset_audit TEXT NOT NULL DEFAULT '[]'"
                ),
                reset_clock=high,
            )

    @classmethod
    def open_for_ui(cls, db_path: Path) -> CostLedger:
        """Keep cost integrity failures out of the recording application startup."""
        try:
            return cls(db_path)
        except SecurityError as error:
            return _UnavailableLedger(db_path, error.code)

    def availability(self) -> str | None:
        try:
            with self.coordinator.hold():
                self._verify()
                self._now()
        except SecurityError as error:
            return error.code
        except (OSError, ValueError, TypeError, sqlite3.Error):
            return "SECURITY_STATE_UNAVAILABLE"
        return None

    @safe_operation
    def reset_clock(self, *, confirmed: bool) -> None:
        """Explicit recovery; all historical same-currency spending stays exposed."""
        if confirmed is not True:
            raise SecurityError("COST_CLOCK_INVALID")
        with self.coordinator.hold():
            self._verify()
            now = clock_value(self._clock())
            high = self._db.execute(
                "SELECT clock_high_water_utc FROM security_cost_meta_v2 WHERE id=1"
            ).fetchone()[0]
            audits = json.loads(
                self._db.execute(
                    "SELECT clock_reset_audit FROM security_cost_meta_v2 WHERE id=1"
                ).fetchone()[0]
            )
            audits.append({"event_id": uuid.uuid4().hex, "previous_high_water": high, "utc": now})
            self._change(
                lambda: self._db.execute(
                    "UPDATE security_cost_meta_v2 SET clock_reset_audit=? WHERE id=1",
                    (canonical(audits).decode(),),
                ),
                reset_clock=now,
            )
            self._last_now = now
            self._dispatches.clear()

    def _now(self) -> float:
        now = clock_value(self._clock())
        high = self._db.execute(
            "SELECT clock_high_water_utc FROM security_cost_meta_v2 WHERE id=1"
        ).fetchone()[0]
        if now < max(self._last_now, high):
            raise SecurityError("COST_CLOCK_INVALID")
        self._last_now = now
        return now

    def __enter__(self) -> CostLedger:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        with self.coordinator.hold():
            if not self._closed:
                self._db.close()
                self._closed = True
                self._prepared_quotes.clear()
                self._reserved_quotes.clear()
                self._dispatches.clear()

    def _state(self) -> dict[str, Any]:
        revision = self._db.execute(
            "SELECT revision FROM security_cost_meta WHERE id=1"
        ).fetchone()[0]
        accounts = [
            list(row)
            for row in self._db.execute("SELECT * FROM security_cost_accounts ORDER BY provider")
        ]
        requests = [
            list(row)
            for row in self._db.execute(
                "SELECT * FROM security_cost_requests ORDER BY reservation_id"
            )
        ]
        state: dict[str, Any] = {"revision": revision, "accounts": accounts, "requests": requests}
        present = self._tables() & _V2
        if present:
            if present != _V2:
                raise SecurityError("LEDGER_ROLLBACK_DETECTED")
            state["v2"] = {
                "schema": {
                    table: [list(row) for row in self._db.execute(f"PRAGMA table_info({table})")]
                    for table in sorted(_V1 | _V2)
                },
                "accounts": [
                    list(row)
                    for row in self._db.execute(
                        "SELECT * FROM security_cost_accounts_v2 ORDER BY account_id"
                    )
                ],
                "requests": [
                    list(row)
                    for row in self._db.execute(
                        "SELECT * FROM security_cost_requests_v2 ORDER BY reservation_id"
                    )
                ],
                "events": [
                    list(row)
                    for row in self._db.execute(
                        "SELECT * FROM security_cost_usage_events ORDER BY reservation_id,source,event_id"
                    )
                ],
                "meta": [
                    list(row)
                    for row in self._db.execute("SELECT * FROM security_cost_meta_v2 ORDER BY id")
                ],
            }
            meta = state["v2"]["meta"]
            if len(meta) != 1 or meta[0][0:4] != [1, 2, revision, 2]:
                raise SecurityError("LEDGER_ROLLBACK_DETECTED")
        return state

    def _write_witness(self) -> None:
        state = self._state()
        payload = canonical(self._witness_value(state))
        temporary = check_path(self._witness.with_name(self._witness.name + "." + uuid.uuid4().hex))
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            check_path(self._witness)
            os.replace(temporary, self._witness)
        finally:
            if temporary.exists():
                temporary.unlink()

    @staticmethod
    def _witness_value(state: dict[str, Any]) -> dict[str, Any]:
        value = {
            "schema_version": 2 if "v2" in state else 1,
            "revision": state["revision"],
            "sha256": digest(canonical(state)),
        }
        if "v2" in state:
            meta = state["v2"]["meta"][0]
            if len(meta) > 8 and json.loads(meta[8]):
                # Older v2 readers compare the whole witness dictionary. Reject
                # them after reset rather than let them ignore all-period debt.
                value["clock_reset_protocol_version"] = 1
        return value

    def _verify(self) -> None:
        if self._closed:
            raise SecurityError("LEDGER_CLOSED")
        try:
            check_path(self._witness)
            if self._witness.stat().st_size > 4096:
                raise ValueError
            value = self._read_witness()
            state = self._state()
            if value != self._witness_value(state):
                raise ValueError
        except (OSError, ValueError, TypeError, sqlite3.Error):
            raise SecurityError("LEDGER_ROLLBACK_DETECTED") from None

        self._verified_stamp = self._stamp()
        self._balance_cache.clear()
        self._exposure_faults.clear()

    def _stamp(self) -> tuple[object, ...]:
        check_path(self._witness)
        witness = self._witness.stat()
        revision = self._db.execute("SELECT revision FROM security_cost_meta WHERE id=1").fetchone()
        return (
            self._db.execute("PRAGMA data_version").fetchone()[0],
            self._db.execute("PRAGMA schema_version").fetchone()[0],
            self._db.total_changes,
            tuple(revision) if revision else None,
            witness.st_mtime_ns,
            witness.st_size,
        )

    def _verify_cached(self) -> None:
        if self._closed:
            raise SecurityError("LEDGER_CLOSED")
        if self._verified_stamp != self._stamp():
            self._verify()

    def _change(self, operation: Callable[[], object], *, reset_clock: float | None = None) -> None:
        self._verify()
        now = self._now() if reset_clock is None else clock_value(reset_clock)
        self._db.execute("BEGIN IMMEDIATE")
        try:
            operation()
            self._db.execute("UPDATE security_cost_meta SET revision=revision+1 WHERE id=1")
            self._db.execute(
                "UPDATE security_cost_meta_v2 SET revision=revision+1,clock_high_water_utc=? WHERE id=1",
                (now,),
            )
            # Witness precedes commit. A crash/commit failure between the two is
            # deliberately blocked on restart rather than silently freeing funds.
            self._write_witness()
            self._db.execute("COMMIT")
            self._verified_stamp = self._stamp()
            self._balance_cache.clear()
            self._exposure_faults.clear()
            for account_id in {d.account_id for d in self._dispatches.values()}:
                self._cache_dispatch_balance(account_id)
        except BaseException:
            if self._db.in_transaction:
                self._db.execute("ROLLBACK")
            raise

    def _request(self, reservation_id: str) -> sqlite3.Row:
        identifier(reservation_id)
        modern: sqlite3.Row | None = self._db.execute(
            "SELECT *,reserved_amount AS amount FROM security_cost_requests_v2 WHERE reservation_id=?",
            (reservation_id,),
        ).fetchone()
        if modern is not None:
            return modern
        row: sqlite3.Row | None = self._db.execute(
            "SELECT * FROM security_cost_requests WHERE reservation_id=?",
            (identifier(reservation_id),),
        ).fetchone()
        if row is None:
            raise SecurityError("RESERVATION_NOT_FOUND")
        return row

    def _snapshot(self, provider_id: str) -> dict[str, int]:
        account = self._db.execute(
            "SELECT amount_limit FROM security_cost_accounts WHERE provider=?", (provider_id,)
        ).fetchone()
        confirmed = reserved = unknown = 0
        for row in self._db.execute(
            "SELECT amount,actual,state FROM security_cost_requests WHERE provider=?",
            (provider_id,),
        ):
            if row["state"] == "SETTLED":
                confirmed += row["actual"]
            elif row["state"] == "RESERVED":
                reserved += row["amount"]
            elif row["state"] == "UNKNOWN":
                unknown += row["amount"]
        limit = account[0] if account else 0
        return {
            "confirmed": confirmed,
            "reserved": reserved,
            "unknown_exposure": unknown,
            "available": max(0, limit - confirmed - reserved - unknown),
            "limit": limit,
        }

    @safe_operation
    def snapshot(self, provider_id: str) -> dict[str, int]:
        with self.coordinator.hold():
            self._verify()
            return self._snapshot(identifier(provider_id))

    @safe_operation
    def set_limit(self, provider_id: str, limit_microunits: int) -> None:
        provider_id, limit = identifier(provider_id), money(limit_microunits)
        with self.coordinator.hold():

            def apply() -> None:
                self._db.execute(
                    "INSERT INTO security_cost_accounts VALUES(?,?) ON CONFLICT(provider) DO UPDATE SET amount_limit=excluded.amount_limit",
                    (provider_id, limit),
                )

            self._change(apply)

    @safe_operation
    def reservations(self, provider_id: str) -> list[dict[str, object]]:
        with self.coordinator.hold():
            self._verify()
            provider_id = identifier(provider_id)
            current = [
                dict(row)
                for row in self._db.execute(
                    """SELECT r.reservation_id,r.request_id,r.state,r.reserved_amount AS amount_microunits,
                          r.actual AS actual_microunits,r.quote_kind,a.currency,
                          a.period_start_utc,a.period_end_utc,r.model_revision,r.profile_id,
                          r.input_upper,r.output_upper,r.price_as_of_utc
                   FROM security_cost_requests_v2 r JOIN security_cost_accounts_v2 a USING(account_id)
                   WHERE r.provider=? ORDER BY r.rowid""",
                    (provider_id,),
                )
            ]
            adopted = {row["reservation_id"] for row in current}
            return current + [
                {
                    "reservation_id": row["reservation_id"],
                    "request_id": row["request_id"],
                    "state": row["state"],
                    "amount_microunits": row["amount"],
                    "actual_microunits": row["actual"],
                    "quote_kind": "LEGACY_UNSCOPED",
                    "currency": None,
                    "period_start_utc": None,
                    "period_end_utc": None,
                }
                for row in self._db.execute(
                    "SELECT * FROM security_cost_requests WHERE provider=? ORDER BY rowid",
                    (provider_id,),
                )
                if row["reservation_id"] not in adopted
            ]

    @safe_operation
    def reserve(
        self, provider_id: str, request_id: str, amount_microunits: int, limit_microunits: int
    ) -> str:
        provider_id, request_id = identifier(provider_id), identifier(request_id)
        amount, limit = money(amount_microunits), money(limit_microunits)
        with self.coordinator.hold():
            self._verify()
            if provider_id in self._adopted():
                raise SecurityError("COST_LEGACY_UNSCOPED")
            existing = self._db.execute(
                "SELECT * FROM security_cost_requests WHERE provider=? AND request_id=?",
                (provider_id, request_id),
            ).fetchone()
            account = self._db.execute(
                "SELECT amount_limit FROM security_cost_accounts WHERE provider=?", (provider_id,)
            ).fetchone()
            if account is not None and account[0] != limit:
                raise SecurityError("BUDGET_POLICY_CHANGED")
            if existing:
                if existing["amount"] != amount:
                    raise SecurityError("RESERVATION_CONFLICT")
                return str(existing["reservation_id"])
            current = self._snapshot(provider_id)
            exposure = current["confirmed"] + current["reserved"] + current["unknown_exposure"]
            if exposure + amount > limit:
                raise SecurityError("BUDGET_EXCEEDED")
            reservation = uuid.uuid4().hex

            def create() -> None:
                self._db.execute(
                    "INSERT OR IGNORE INTO security_cost_accounts VALUES(?,?)", (provider_id, limit)
                )
                self._db.execute(
                    "INSERT INTO security_cost_requests VALUES(?,?,?,?,NULL,'RESERVED')",
                    (reservation, provider_id, request_id, amount),
                )

            self._change(create)
            return reservation

    @safe_operation
    def check_reservation(self, reservation_id: str, provider_id: str) -> None:
        with self.coordinator.hold():
            self._verify()
            row = self._request(reservation_id)
            if row["provider"] != provider_id or row["state"] != "RESERVED":
                raise SecurityError("RESERVATION_NOT_DISPATCHABLE")
            if "account_id" in row.keys():
                if row["quote_kind"] == "LEGACY_UNSCOPED":
                    raise SecurityError("COST_LEGACY_UNSCOPED")
                policy = CostPolicy(**json.loads(row["policy_json"]))
                account = self._eligible_account(provider_id, policy, self._now())
                balance = self._account_snapshot(account["account_id"])
            else:
                balance = self._snapshot(provider_id)
            if (
                balance["confirmed"] + balance["reserved"] + balance["unknown_exposure"]
                > balance["limit"]
            ):
                raise SecurityError("BUDGET_EXCEEDED")

    @safe_operation
    def mark_unknown(self, reservation_id: str) -> None:
        with self.coordinator.hold():
            self._verify()
            row = self._request(reservation_id)
            if row["state"] == "UNKNOWN":
                return
            if row["state"] != "RESERVED":
                raise SecurityError("RESERVATION_CONFLICT")
            table = (
                "security_cost_requests_v2"
                if "account_id" in row.keys()
                else "security_cost_requests"
            )
            self._change(
                lambda: (
                    self._db.execute(
                        f"UPDATE {table} SET state='UNKNOWN' WHERE reservation_id=?",
                        (reservation_id,),
                    )
                    and None
                )
            )

    @safe_operation
    def settle(self, reservation_id: str, actual_microunits: int) -> None:
        actual = money(actual_microunits)
        with self.coordinator.hold():
            self._verify()
            row = self._request(reservation_id)
            if row["state"] == "SETTLED":
                if row["actual"] != actual:
                    raise SecurityError("SETTLEMENT_CONFLICT")
                return
            if "account_id" in row.keys():
                account = self._account_id(row["account_id"])
                last = self._db.execute(
                    "SELECT MAX(version) FROM security_cost_usage_events WHERE reservation_id=?",
                    (reservation_id,),
                ).fetchone()[0]
                self.apply_usage(
                    reservation_id,
                    source="manual",
                    event_id="manual",
                    version=(last or 0) + 1,
                    final=True,
                    currency_code=account["currency"],
                    period_id=account["account_id"],
                    amount=actual,
                )
                return
            if row["state"] == "SETTLED":
                if row["actual"] != actual:
                    raise SecurityError("SETTLEMENT_CONFLICT")
                return
            if row["state"] not in {"RESERVED", "UNKNOWN"}:
                raise SecurityError("RESERVATION_CONFLICT")
            self._change(
                lambda: (
                    self._db.execute(
                        "UPDATE security_cost_requests SET state='SETTLED',actual=? WHERE reservation_id=?",
                        (actual, reservation_id),
                    )
                    and None
                )
            )

    @safe_operation
    def release(self, reservation_id: str) -> None:
        with self.coordinator.hold():
            self._verify()
            row = self._request(reservation_id)
            if row["state"] == "RELEASED":
                return
            if row["state"] != "RESERVED":
                raise SecurityError("RESERVATION_MAY_BE_SENT")
            table = (
                "security_cost_requests_v2"
                if "account_id" in row.keys()
                else "security_cost_requests"
            )
            self._change(
                lambda: (
                    self._db.execute(
                        f"UPDATE {table} SET state='RELEASED' WHERE reservation_id=?",
                        (reservation_id,),
                    )
                    and None
                )
            )

    def _account_id(self, account_id: str) -> sqlite3.Row:
        row: sqlite3.Row | None = self._db.execute(
            "SELECT * FROM security_cost_accounts_v2 WHERE account_id=?", (account_id,)
        ).fetchone()
        if row is None:
            raise SecurityError("COST_PERIOD_CHANGED")
        return row

    def _account(self, provider: str, policy: CostPolicy) -> sqlite3.Row | None:
        row: sqlite3.Row | None = self._db.execute(
            "SELECT * FROM security_cost_accounts_v2 WHERE provider=? AND currency=? AND period_start_utc=? AND period_end_utc=?",
            (provider, policy.currency, policy.period_start_utc, policy.period_end_utc),
        ).fetchone()
        return row

    @safe_operation
    def account(
        self, provider: str, currency_code: str, start: int, end: int
    ) -> dict[str, Any] | None:
        with self.coordinator.hold():
            self._verify()
            row = self._db.execute(
                "SELECT * FROM security_cost_accounts_v2 WHERE provider=? AND currency=? AND period_start_utc=? AND period_end_utc=?",
                (identifier(provider), currency(currency_code), money(start), money(end)),
            ).fetchone()
            return dict(row) if row else None

    @safe_operation
    def apply_policy(self, provider: str, policy: CostPolicy) -> str:
        provider = identifier(provider)
        if type(policy) is not CostPolicy:
            raise SecurityError("COST_REQUEST_INVALID")
        with self.coordinator.hold():
            self._verify()
            self._now()
            old = self._account(provider, policy)
            if old:
                if (
                    policy.policy_version < old["policy_version"]
                    or policy.policy_version == old["policy_version"]
                    and policy.limit != old["amount_limit"]
                ):
                    raise SecurityError("BUDGET_POLICY_CHANGED")
                if policy.policy_version == old["policy_version"]:
                    return str(old["account_id"])
                account_id = str(old["account_id"])
                self._change(
                    lambda: self._db.execute(
                        "UPDATE security_cost_accounts_v2 SET policy_version=?,amount_limit=? WHERE account_id=?",
                        (policy.policy_version, policy.limit, account_id),
                    )
                )
                return account_id
            account_id = uuid.uuid4().hex
            self._change(
                lambda: self._db.execute(
                    "INSERT INTO security_cost_accounts_v2 VALUES(?,?,?,?,?,?,?,0)",
                    (
                        account_id,
                        provider,
                        policy.currency,
                        policy.period_start_utc,
                        policy.period_end_utc,
                        policy.policy_version,
                        policy.limit,
                    ),
                )
            )
            return account_id

    def _account_snapshot(self, account_id: str) -> dict[str, int]:
        account = self._account_id(account_id)
        confirmed = reserved = unknown = 0
        for row in self._db.execute(
            "SELECT state,reserved_amount,actual FROM security_cost_requests_v2 WHERE account_id=?",
            (account_id,),
        ):
            if row[0] == "SETTLED":
                confirmed += row[2]
            elif row[0] == "RESERVED":
                reserved += row[1]
            elif row[0] == "UNKNOWN":
                unknown += row[1]
        reset = self._db.execute(
            "SELECT clock_reset_audit FROM security_cost_meta_v2 WHERE id=1"
        ).fetchone()[0]
        if json.loads(reset):
            # A clock reset cannot make spending appear to belong only to the
            # future. Until trustworthy per-charge times exist, include every
            # settled period of this provider/currency in the current budget.
            confirmed = self._db.execute(
                "SELECT COALESCE(SUM(r.actual),0) FROM security_cost_requests_v2 r "
                "JOIN security_cost_accounts_v2 a USING(account_id) "
                "WHERE a.provider=? AND a.currency=? AND r.state='SETTLED'",
                (account["provider"], account["currency"]),
            ).fetchone()[0]
        return {
            "confirmed": confirmed,
            "reserved": reserved,
            "unknown_exposure": unknown,
            "limit": account["amount_limit"],
            "available": max(0, account["amount_limit"] - confirmed - reserved - unknown),
        }

    @safe_operation
    def account_snapshot(
        self, provider: str, currency_code: str, start: int, end: int
    ) -> dict[str, int]:
        with self.coordinator.hold():
            self._verify()
            row = self.account(provider, currency_code, start, end)
            if row is None:
                return {
                    "confirmed": 0,
                    "reserved": 0,
                    "unknown_exposure": 0,
                    "limit": 0,
                    "available": 0,
                }
            return self._account_snapshot(row["account_id"])

    def _legacy_providers(self) -> set[str]:
        return {
            row[0]
            for row in self._db.execute(
                "SELECT provider FROM security_cost_accounts UNION SELECT provider FROM security_cost_requests"
            )
        }

    def _adopted(self) -> set[str]:
        return set(
            json.loads(
                self._db.execute(
                    "SELECT adopted_providers FROM security_cost_meta_v2 WHERE id=1"
                ).fetchone()[0]
            )
        )

    @safe_operation
    def legacy_unscoped(self, provider: str) -> bool:
        with self.coordinator.hold():
            self._verify()
            return provider in self._legacy_providers() - self._adopted()

    @safe_operation
    def adopt_legacy(self, provider: str, policy: CostPolicy, *, confirmed: bool) -> None:
        """Explicitly assign old opaque exposure; never make an old request dispatchable."""
        if confirmed is not True:
            raise SecurityError("COST_LEGACY_UNSCOPED")
        with self.coordinator.hold():
            self._verify()
            if not self.legacy_unscoped(provider):
                return
            account_id = self.apply_policy(provider, policy)
            rows = list(
                self._db.execute(
                    "SELECT * FROM security_cost_requests WHERE provider=?", (provider,)
                )
            )

            def apply() -> None:
                for row in rows:
                    self._db.execute(
                        """INSERT INTO security_cost_requests_v2(reservation_id,provider,request_id,account_id,reserved_amount,actual,state,quote_kind,request_fingerprint) VALUES(?,?,?,?,?,?,?,'LEGACY_UNSCOPED',?)""",
                        (
                            row["reservation_id"],
                            provider,
                            row["request_id"],
                            account_id,
                            row["amount"],
                            row["actual"],
                            row["state"],
                            digest(canonical(["legacy", provider, row["request_id"]])),
                        ),
                    )
                adopted = self._adopted() | {provider}
                state = "READY" if self._legacy_providers() <= adopted else "LEGACY_UNSCOPED"
                self._db.execute(
                    "UPDATE security_cost_meta_v2 SET adopted_providers=?,migration_state=? WHERE id=1",
                    (json.dumps(sorted(adopted)), state),
                )

            self._change(apply)

    def _eligible_account(self, provider: str, policy: CostPolicy, now: float) -> sqlite3.Row:
        if self.legacy_unscoped(provider):
            raise SecurityError("COST_LEGACY_UNSCOPED")
        if not policy.period_start_utc <= now < policy.period_end_utc:
            raise SecurityError("COST_PERIOD_CHANGED")
        account = self._account(provider, policy)
        if account is None:
            raise SecurityError("BUDGET_REQUIRED")
        if (
            account["policy_version"] != policy.policy_version
            or account["amount_limit"] != policy.limit
        ):
            raise SecurityError("BUDGET_POLICY_CHANGED")
        if account["blocked"]:
            raise SecurityError("COST_PLAN_UNDERESTIMATED")
        if self._db.execute(
            "SELECT 1 FROM security_cost_requests_v2 WHERE provider=? AND account_id!=? AND state IN ('RESERVED','UNKNOWN') LIMIT 1",
            (provider, account["account_id"]),
        ).fetchone():
            raise SecurityError("COST_UNRESOLVED_EXPOSURE")
        return account

    @safe_operation
    def quote_request(self, request: CostRequest, policy: CostPolicy) -> CostQuote:
        """Use the ledger's clock and fixed catalog; never create a reservation."""
        with self.coordinator.hold():
            self._verify()
            result = quote(request, policy, cost_catalog.load_catalog(), self._now())
            self._prepared_quotes[id(request)] = (ref(request), policy, result)
            while len(self._prepared_quotes) > 4:
                self._prepared_quotes.popitem(last=False)
            return result

    @safe_operation
    def reserve_quote(
        self, request_id: str, quoted: CostQuote, policy: CostPolicy, request: CostRequest
    ) -> str:
        if (
            type(request) is not CostRequest
            or type(quoted) is not CostQuote
            or type(policy) is not CostPolicy
        ):
            raise SecurityError("COST_REQUEST_INVALID")
        identifier(request_id)
        with self.coordinator.hold():
            self._verify()
            now = self._now()
            prepared = self._prepared_quotes.pop(id(request), None)
            catalog = cost_catalog.load_catalog()
            if (
                prepared is not None
                and prepared[0]() is request
                and prepared[1] == policy
                and policy.catalog_digest == catalog.sha256
                and (
                    prepared[2].valid_until_utc is None
                    or prepared[2].valid_from_utc is not None
                    and prepared[2].valid_from_utc <= now < prepared[2].valid_until_utc
                )
            ):
                expected = prepared[2]
            else:
                expected = quote(request, policy, catalog, now)
            if expected != quoted:
                raise SecurityError("COST_QUOTE_MISMATCH")
            account = self._eligible_account(request.provider_id, policy, now)
            old = self._db.execute(
                "SELECT * FROM security_cost_requests_v2 WHERE provider=? AND request_id=?",
                (request.provider_id, request_id),
            ).fetchone()
            if old:
                if (
                    old["quote_json"] != canonical(asdict(quoted)).decode()
                    or old["request_fingerprint"] != request.fingerprint
                ):
                    raise SecurityError("RESERVATION_CONFLICT")
                return str(old["reservation_id"])
            balance = self._account_snapshot(account["account_id"])
            if (
                balance["confirmed"]
                + balance["reserved"]
                + balance["unknown_exposure"]
                + quoted.amount
                > balance["limit"]
            ):
                raise SecurityError("BUDGET_EXCEEDED")
            reservation_id = uuid.uuid4().hex

            def create() -> None:
                self._db.execute(
                    """INSERT INTO security_cost_requests_v2(reservation_id,provider,request_id,account_id,reserved_amount,actual,state,quote_kind,model_revision,profile_id,endpoint_digest,body_sha256,byte_length,input_upper,output_upper,price_as_of_utc,valid_until_utc,catalog_digest,request_fingerprint,request_json,quote_json,policy_json,dispatch_id) VALUES(?,?,?,?,?,NULL,'RESERVED',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)""",
                    (
                        reservation_id,
                        request.provider_id,
                        request_id,
                        account["account_id"],
                        quoted.amount,
                        quoted.kind,
                        request.model_revision,
                        quoted.profile_id,
                        digest(request.endpoint.encode()),
                        quoted.body_sha256,
                        quoted.byte_length,
                        quoted.input_upper,
                        quoted.output_upper,
                        quoted.price_as_of_utc,
                        quoted.valid_until_utc,
                        policy.catalog_digest,
                        request.fingerprint,
                        canonical(request.metadata()).decode(),
                        canonical(asdict(quoted)).decode(),
                        canonical(asdict(policy)).decode(),
                    ),
                )

            self._change(create)
            until = min(
                policy.period_end_utc,
                quoted.valid_until_utc
                if quoted.valid_until_utc is not None
                else policy.period_end_utc,
            )
            self._quote_deadlines[reservation_id] = self._monotonic() + max(0, until - now)
            self._reserved_quotes[reservation_id] = (ref(request), policy, expected)
            while len(self._reserved_quotes) > 4:
                self._reserved_quotes.popitem(last=False)
            return reservation_id

    @safe_operation
    def validate_dispatch(
        self,
        reservation_id: str,
        provider: str,
        target: str,
        body: bytes,
        *,
        data_type: str,
        operation: str,
        headers: dict[str, str] | None = None,
        dispatch_id: str,
        phase: str = "open",
        bytes_sent: int | None = None,
    ) -> None:
        if phase not in {"open", "write"}:
            raise SecurityError("COST_REQUEST_INVALID")
        identifier(dispatch_id)
        with self.coordinator.hold():
            if phase == "write":
                self._validate_write(
                    reservation_id,
                    provider,
                    target,
                    body,
                    data_type,
                    operation,
                    cost_headers(headers),
                    dispatch_id,
                    bytes_sent,
                )
                return
            self._verify()
            now = self._now()
            row = self._request(reservation_id)
            if "account_id" not in row.keys() or row["quote_kind"] == "LEGACY_UNSCOPED":
                raise SecurityError("COST_LEGACY_UNSCOPED")
            if row["provider"] != provider:
                raise SecurityError("COST_QUOTE_MISMATCH")
            saved = json.loads(row["request_json"])
            policy = CostPolicy(**json.loads(row["policy_json"]))
            prepared = self._reserved_quotes.pop(reservation_id, None)
            prepared_request = prepared[0]() if prepared is not None else None
            reusable = (
                prepared is not None
                and prepared_request is not None
                and prepared_request.body is body
                and prepared[1] == policy
            )
            body_digest = (
                prepared_request.body_sha256
                if reusable and prepared_request is not None
                else digest(body)
            )
            if (
                body_digest != saved["body_sha256"]
                or len(body) != saved["byte_length"]
                or target != saved["endpoint"]
                or data_type != saved["data_type"]
                or operation != saved["operation"]
                or cost_headers(headers) != tuple(tuple(p) for p in saved["headers"])
            ):
                raise SecurityError("COST_QUOTE_MISMATCH")
            request = (
                prepared_request
                if reusable and prepared_request is not None
                else CostRequest(
                    provider,
                    target,
                    saved["model_revision"],
                    saved["api_version"],
                    saved["operation"],
                    saved["data_type"],
                    body,
                    cost_headers(headers),
                )
            )
            if request.fingerprint != row["request_fingerprint"]:
                raise SecurityError("COST_QUOTE_MISMATCH")
            self._eligible_account(provider, policy, now)
            quoted = json.loads(row["quote_json"])
            catalog = cost_catalog.load_catalog()
            if catalog.sha256 != policy.catalog_digest:
                raise SecurityError("COST_QUOTE_MISMATCH")
            if quoted["kind"] == "VERIFIED" and (
                quoted["valid_until_utc"] is None
                or not quoted["valid_from_utc"] <= now < quoted["valid_until_utc"]
            ):
                raise SecurityError("COST_QUOTE_EXPIRED")
            if quoted["kind"] == "VERIFIED":
                expected = (
                    prepared[2]
                    if reusable and prepared is not None
                    else quote(request, policy, catalog, now)
                )
                if canonical(asdict(expected)).decode() != row["quote_json"]:
                    raise SecurityError("COST_QUOTE_MISMATCH")
            else:
                from .cost import inspect_wire

                if not reusable:
                    inspect_wire(request, catalog.find(request))
                if (
                    policy.mode != "general"
                    or not policy.general_acknowledged
                    or quoted["amount"] != policy.cap
                ):
                    raise SecurityError("COST_QUOTE_MISMATCH")
                expected = CostQuote(**{**quoted, "policy": policy})
            until = min(
                policy.period_end_utc,
                expected.valid_until_utc
                if expected.valid_until_utc is not None
                else policy.period_end_utc,
            )
            deadline = self._quote_deadlines.setdefault(
                reservation_id, self._monotonic() + max(0, until - now)
            )
            if self._monotonic() >= deadline:
                raise SecurityError("COST_QUOTE_EXPIRED")
            if phase == "open":
                if row["state"] != "RESERVED" or row["dispatch_id"] is not None:
                    raise SecurityError("RESERVATION_NOT_DISPATCHABLE")
                self._change(
                    lambda: self._db.execute(
                        "UPDATE security_cost_requests_v2 SET dispatch_id=? WHERE reservation_id=?",
                        (dispatch_id, reservation_id),
                    )
                )
                self._dispatches[dispatch_id] = _Dispatch(
                    reservation_id,
                    str(row["account_id"]),
                    provider,
                    target,
                    data_type,
                    operation,
                    cost_headers(headers),
                    body,
                    policy,
                    row["quote_json"],
                    deadline,
                    quoted["valid_from_utc"],
                    quoted["valid_until_utc"],
                )
            account = self._account_id(row["account_id"])
            balance = self._account_snapshot(account["account_id"])
            self._balance_cache[str(account["account_id"])] = balance
            self._exposure_faults[str(account["account_id"])] = None
            if (
                balance["confirmed"] + balance["reserved"] + balance["unknown_exposure"]
                > balance["limit"]
            ):
                raise SecurityError("BUDGET_EXCEEDED")

    def _validate_write(
        self,
        reservation_id: str,
        provider: str,
        target: str,
        body: bytes,
        data_type: str,
        operation: str,
        headers: tuple[tuple[str, str], ...],
        dispatch_id: str,
        bytes_sent: int | None,
    ) -> None:
        self._verify_cached()
        now = self._now()
        saved = self._dispatches.get(dispatch_id)
        if saved is None:
            raise SecurityError("RESERVATION_NOT_DISPATCHABLE")
        if body is not saved.body or (
            reservation_id,
            provider,
            target,
            data_type,
            operation,
            headers,
        ) != (
            saved.reservation_id,
            saved.provider,
            saved.target,
            saved.data_type,
            saved.operation,
            saved.headers,
        ):
            raise SecurityError("COST_QUOTE_MISMATCH")
        if type(bytes_sent) is not int or bytes_sent < 0:
            raise SecurityError("COST_REQUEST_INVALID")
        if bytes_sent > len(saved.body):
            raise SecurityError("COST_PLAN_UNDERESTIMATED")
        policy = saved.policy
        if not policy.period_start_utc <= now < policy.period_end_utc:
            raise SecurityError("COST_PERIOD_CHANGED")
        if (
            self._monotonic() >= saved.deadline
            or saved.valid_until is not None
            and (saved.valid_from is None or not saved.valid_from <= now < saved.valid_until)
        ):
            raise SecurityError("COST_QUOTE_EXPIRED")
        row = self._request(reservation_id)
        if row["state"] not in {"RESERVED", "UNKNOWN"} or row["dispatch_id"] != dispatch_id:
            raise SecurityError("RESERVATION_NOT_DISPATCHABLE")
        if row["quote_json"] != saved.quote_json:
            raise SecurityError("COST_QUOTE_MISMATCH")
        account = self._account_id(row["account_id"])
        if (
            account["policy_version"] != policy.policy_version
            or account["amount_limit"] != policy.limit
        ):
            raise SecurityError("BUDGET_POLICY_CHANGED")
        if account["blocked"]:
            raise SecurityError("COST_PLAN_UNDERESTIMATED")
        account_id = str(account["account_id"])
        balance = self._balance_cache.get(account_id)
        if balance is None:
            # Recomputed only when an authenticated ledger transaction changed.
            balance = self._cache_dispatch_balance(account_id)
        if self._exposure_faults[account_id] is not None:
            raise SecurityError(str(self._exposure_faults[account_id]))
        if (
            balance["confirmed"] + balance["reserved"] + balance["unknown_exposure"]
            > balance["limit"]
        ):
            raise SecurityError("BUDGET_EXCEEDED")

    def _cache_dispatch_balance(self, account_id: str) -> dict[str, int]:
        account = self._account_id(account_id)
        balance = self._account_snapshot(account_id)
        fault = None
        if account["provider"] in self._legacy_providers() - self._adopted():
            fault = "COST_LEGACY_UNSCOPED"
        elif self._db.execute(
            "SELECT 1 FROM security_cost_requests_v2 WHERE provider=? AND account_id!=? "
            "AND state IN ('RESERVED','UNKNOWN') LIMIT 1",
            (account["provider"], account_id),
        ).fetchone():
            fault = "COST_UNRESOLVED_EXPOSURE"
        self._balance_cache[account_id] = balance
        self._exposure_faults[account_id] = fault
        return balance

    def finish_dispatch(self, dispatch_id: str) -> None:
        """Drop only ephemeral validation state; UNKNOWN exposure stays durable."""
        self._dispatches.pop(dispatch_id, None)

    @safe_operation
    def apply_usage(
        self,
        reservation_id: str,
        *,
        source: str,
        event_id: str,
        version: int,
        final: bool,
        currency_code: str,
        period_id: str,
        amount: int,
    ) -> None:
        identifier(source)
        identifier(event_id)
        money(version)
        money(amount)
        currency(currency_code)
        if version == 0 or type(final) is not bool:
            raise SecurityError("SETTLEMENT_CONFLICT")
        payload = digest(
            canonical(
                [reservation_id, source, event_id, version, final, currency_code, period_id, amount]
            )
        )
        with self.coordinator.hold():
            self._verify()
            row = self._request(reservation_id)
            if "account_id" not in row.keys():
                raise SecurityError("COST_LEGACY_UNSCOPED")
            account = self._account_id(row["account_id"])
            if currency_code != account["currency"]:
                raise SecurityError("COST_CURRENCY_MISMATCH")
            if period_id != account["account_id"]:
                raise SecurityError("COST_PERIOD_CHANGED")
            old = self._db.execute(
                "SELECT payload_digest FROM security_cost_usage_events WHERE reservation_id=? AND source=? AND event_id=?",
                (reservation_id, source, event_id),
            ).fetchone()
            if old:
                if old[0] != payload:
                    raise SecurityError("SETTLEMENT_CONFLICT")
                return
            last = self._db.execute(
                "SELECT MAX(version) FROM security_cost_usage_events WHERE reservation_id=?",
                (reservation_id,),
            ).fetchone()[0]
            if (
                row["state"] not in {"RESERVED", "UNKNOWN", "SETTLED"}
                or last is not None
                and version <= last
            ):
                raise SecurityError("SETTLEMENT_CONFLICT")
            if row["state"] == "SETTLED" and (not final or row["actual"] != amount):
                raise SecurityError("SETTLEMENT_CONFLICT")

            def apply() -> None:
                self._db.execute(
                    "INSERT INTO security_cost_usage_events VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        reservation_id,
                        source,
                        event_id,
                        version,
                        "final" if final else "provisional",
                        currency_code,
                        period_id,
                        amount,
                        payload,
                    ),
                )
                if final:
                    self._db.execute(
                        "UPDATE security_cost_requests_v2 SET state='SETTLED',actual=? WHERE reservation_id=?",
                        (amount, reservation_id),
                    )
                    if amount > row["reserved_amount"]:
                        self._db.execute(
                            "UPDATE security_cost_accounts_v2 SET blocked=1 WHERE account_id=?",
                            (account["account_id"],),
                        )

            self._change(apply)


class _UnavailableLedger(CostLedger):
    """A cost-only failure surface. It never authenticates or rewrites bad state."""

    def __init__(self, db_path: Path, code: str) -> None:
        self.coordinator = Coordinator(db_path)
        self.db_path = self.coordinator.path
        self._startup_error = code
        self._closed = False

    def _verify(self) -> None:
        raise SecurityError(self._startup_error)

    def availability(self) -> str | None:
        return self._startup_error

    def close(self) -> None:
        self._closed = True

    def finish_dispatch(self, dispatch_id: str) -> None:
        pass
