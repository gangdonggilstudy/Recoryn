"""Integer cost reservations with a fail-closed rollback witness, independent of sessions."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

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


class CostLedger:
    @safe_operation
    def __init__(self, db_path: Path) -> None:
        self.coordinator = Coordinator(db_path)
        self.db_path = self.coordinator.path
        self._witness = check_path(self.db_path.with_name(self.db_path.name + ".cost-witness"))
        self._closed = False
        if self._witness.exists() and not self.db_path.exists():
            raise SecurityError("LEDGER_ROLLBACK_DETECTED")
        self._db = connect(self.db_path)
        try:
            with self.coordinator.hold():
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
        except BaseException:
            self._db.close()
            raise

    def __enter__(self) -> CostLedger:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        with self.coordinator.hold():
            if not self._closed:
                self._db.close()
                self._closed = True

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
        return {"revision": revision, "accounts": accounts, "requests": requests}

    def _write_witness(self) -> None:
        state = self._state()
        payload = canonical(
            {"schema_version": 1, "revision": state["revision"], "sha256": digest(canonical(state))}
        )
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

    def _verify(self) -> None:
        if self._closed:
            raise SecurityError("LEDGER_CLOSED")
        try:
            check_path(self._witness)
            if self._witness.stat().st_size > 4096:
                raise ValueError
            value = json.loads(self._witness.read_bytes())
            state = self._state()
            if value != {
                "schema_version": 1,
                "revision": state["revision"],
                "sha256": digest(canonical(state)),
            }:
                raise ValueError
        except (OSError, ValueError, TypeError, sqlite3.Error):
            raise SecurityError("LEDGER_ROLLBACK_DETECTED") from None

    def _change(self, operation: Callable[[], object]) -> None:
        self._verify()
        self._db.execute("BEGIN IMMEDIATE")
        try:
            operation()
            self._db.execute("UPDATE security_cost_meta SET revision=revision+1 WHERE id=1")
            # Witness precedes commit. A crash/commit failure between the two is
            # deliberately blocked on restart rather than silently freeing funds.
            self._write_witness()
            self._db.execute("COMMIT")
        except BaseException:
            self._db.execute("ROLLBACK")
            raise

    def _request(self, reservation_id: str) -> sqlite3.Row:
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
            return [
                {
                    "reservation_id": row["reservation_id"],
                    "request_id": row["request_id"],
                    "state": row["state"],
                    "amount_microunits": row["amount"],
                    "actual_microunits": row["actual"],
                }
                for row in self._db.execute(
                    "SELECT * FROM security_cost_requests WHERE provider=? ORDER BY rowid",
                    (identifier(provider_id),),
                )
            ]

    @safe_operation
    def reserve(
        self, provider_id: str, request_id: str, amount_microunits: int, limit_microunits: int
    ) -> str:
        provider_id, request_id = identifier(provider_id), identifier(request_id)
        amount, limit = money(amount_microunits), money(limit_microunits)
        with self.coordinator.hold():
            self._verify()
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
            self._change(
                lambda: (
                    self._db.execute(
                        "UPDATE security_cost_requests SET state='UNKNOWN' WHERE reservation_id=?",
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
            self._change(
                lambda: (
                    self._db.execute(
                        "UPDATE security_cost_requests SET state='RELEASED' WHERE reservation_id=?",
                        (reservation_id,),
                    )
                    and None
                )
            )
