"""SQLite content rows are immutable; selection CAS failure preserves candidates."""

from __future__ import annotations

import hashlib
import html
import json
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any
from uuid import uuid4

from recoryn.domain import StateConflict, ValidationError
from recoryn.jobs import AttemptRecord, JobStore
from recoryn.storage import Library
from recoryn.storage._coordination import root_mutex

from .models import Claim, Segment, identifier, text_value

_MAX_ITEMS = 100_000
_MAX_REVISION_BYTES = 16 * 1024 * 1024


def _encode(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    if len(encoded.encode("utf-8")) > _MAX_REVISION_BYTES:
        raise ValidationError("CONTENT_REVISION_TOO_LARGE")
    return encoded


def _expected(value: str | None) -> None:
    if value is not None:
        identifier(value)


def _expected_version(value: int | None) -> None:
    """A selection version captured from selection_state(); None keeps ID-only CAS."""
    if value is not None and (type(value) is not int or not 0 <= value < 2**63):
        raise ValidationError("INVALID_SELECTION_VERSION")


def _settings_key(value: str | None) -> None:
    if value is not None:
        text_value(value, maximum=256, empty=False)


def _coverage(value: dict[str, Any] | None, units: list[str]) -> tuple[dict[str, Any], bool]:
    if value is None:
        value = {
            "schema_version": 1,
            "planned": units,
            "completed": units,
            "failed": [],
            "missing": [],
        }
    if not isinstance(value, dict) or set(value) - {
        "schema_version",
        "planned",
        "completed",
        "failed",
        "missing",
        "source_ranges",
        "checkpoint",
    }:
        raise ValidationError("INVALID_CONTENT_COVERAGE")
    if type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        raise ValidationError("INVALID_CONTENT_COVERAGE_SCHEMA")
    groups: dict[str, list[str]] = {}
    for key in ("planned", "completed", "failed"):
        group = value.get(key)
        if not isinstance(group, (list, tuple)) or len(group) > _MAX_ITEMS:
            raise ValidationError("INVALID_CONTENT_COVERAGE_UNITS")
        groups[key] = [text_value(unit, maximum=256, empty=False) for unit in group]
        if len(set(groups[key])) != len(group):
            raise ValidationError("DUPLICATE_CONTENT_COVERAGE_UNIT")
    planned, done, failed = (set(groups[key]) for key in ("planned", "completed", "failed"))
    if done & failed or not (done | failed) <= planned:
        raise ValidationError("INVALID_CONTENT_COVERAGE_PARTITION")
    groups["missing"] = [unit for unit in groups["planned"] if unit not in done | failed]
    if "missing" in value:
        missing = value["missing"]
        if (
            not isinstance(missing, (list, tuple))
            or any(not isinstance(unit, str) for unit in missing)
            or len(set(missing)) != len(missing)
            or set(missing) != set(groups["missing"])
        ):
            raise ValidationError("INVALID_CONTENT_MISSING_COVERAGE")
    result: dict[str, Any] = {"schema_version": 1, **groups}
    if "source_ranges" in value:
        ranges = value["source_ranges"]
        if not isinstance(ranges, (list, tuple)) or any(
            not isinstance(item, dict) for item in ranges
        ):
            raise ValidationError("INVALID_CONTENT_SOURCE_RANGES")
        try:
            result["source_ranges"] = json.loads(json.dumps(ranges, allow_nan=False))
        except (TypeError, ValueError, RecursionError) as exc:
            raise ValidationError("INVALID_CONTENT_SOURCE_RANGES") from exc
    if "checkpoint" in value:
        if not isinstance(value["checkpoint"], dict):
            raise ValidationError("INVALID_CONTENT_CHECKPOINT")
        try:
            result["checkpoint"] = json.loads(json.dumps(value["checkpoint"], allow_nan=False))
        except (TypeError, ValueError, RecursionError) as exc:
            raise ValidationError("INVALID_CONTENT_CHECKPOINT") from exc
    return result, done == planned and not failed


BASES = ("transcript", "user_assertion", "unresolved", "model_inference")


def canonical_basis(provenances: set[str] | frozenset[str], has_refs: bool) -> str:
    """The stored basis from the referenced provenance set (G12 section 3.1 table).

    unresolved outranks user_assertion, which outranks transcript; no reference at all
    is model_inference. This classifies where references come from, not whether the
    claim's meaning is supported.
    """
    if "unresolved" in provenances:
        return "unresolved"
    if "user_assertion" in provenances:
        return "user_assertion"
    return "transcript" if has_refs else "model_inference"


@dataclass(frozen=True, slots=True)
class SummarySelectionExpectation:
    """The selection snapshot a candidate list was presented with (all fields required).

    An observed empty ID or settings key is None; versions are non-negative ints. The
    selection transaction compares every field, so an ABA return or a settings change
    while a confirmation was open is refused instead of silently re-based.
    """

    session_id: str
    transcript_id: str | None
    transcript_version: int
    summary_id: str | None
    summary_version: int
    summary_settings_key: str | None

    def __post_init__(self) -> None:
        try:
            identifier(self.session_id)
            for value in (self.transcript_id, self.summary_id):
                if value is not None:
                    identifier(value)
            if self.summary_settings_key is not None:
                text_value(self.summary_settings_key, maximum=256, empty=False)
        except ValidationError:
            raise ValidationError("INVALID_SUMMARY_SELECTION_EXPECTATION") from None
        for version in (self.transcript_version, self.summary_version):
            if type(version) is not int or not 0 <= version < 2**63:
                raise ValidationError("INVALID_SUMMARY_SELECTION_EXPECTATION")

    @classmethod
    def from_state(cls, state: dict[str, Any]) -> SummarySelectionExpectation:
        return cls(
            state["session_id"],
            state["transcript_id"],
            state["transcript_version"],
            state["summary_id"],
            state["summary_version"],
            state["summary_settings_key"],
        )


CLAIM_STATUSES = (
    "uncertain",
    "unreviewed",
    "unsupported",
    "disputed",
    "user_assertion",
    "model_inference",
)
# Why a claim's evidence cannot be shown (G12 section 3.2 / FIX1 G12R-01, G12R-05).
CLAIM_RECORD_INVALID = "CONTENT_CLAIM_RECORD_INVALID"


def _claim_view(
    index: int, claim: object, segments: dict[str, Any], source_ok: bool
) -> dict[str, Any]:
    """One read-only evidence view; a malformed or contradictory record is a problem."""
    record = claim if isinstance(claim, dict) else {}
    text = record.get("text")
    raw_refs = record.get("segment_ids")
    stored, provider, status = (
        record.get("basis"),
        record.get("provider_basis"),
        record.get("status"),
    )
    valid = (
        isinstance(claim, dict)
        and isinstance(text, str)
        and isinstance(raw_refs, list)
        and all(isinstance(ref, str) for ref in raw_refs)
        and len(set(raw_refs)) == len(raw_refs)
        and status in CLAIM_STATUSES
        and (stored is None or stored in BASES)
        and (provider is None or provider in ("transcript", "user_assertion", "model_inference"))
    )
    if not valid:
        return {
            "index": index,
            "text": text if isinstance(text, str) else "",
            "status": status if status in CLAIM_STATUSES else None,
            "basis": None,
            "computed_basis": None,
            "basis_recorded": False,
            "provider_basis": None,
            "refs": [],
            "problem": CLAIM_RECORD_INVALID,
        }
    assert isinstance(raw_refs, list)
    refs = []
    for segment_id in raw_refs:
        segment = segments.get(segment_id)
        refs.append(
            {
                "segment_id": segment_id,
                "found": segment is not None,
                "provenance": None if segment is None else segment["provenance"],
                "timing_quality": None if segment is None else segment.get("timing_quality"),
                "start_ms": None if segment is None else segment["start_ms"],
                "track_id": None if segment is None else segment.get("track_id"),
            }
        )
    computed = (
        canonical_basis({item["provenance"] for item in refs if item["found"]}, bool(refs))
        if source_ok and all(item["found"] for item in refs)
        else None
    )
    problem = None
    if not source_ok or computed is None:
        problem = "CONTENT_CLAIM_SOURCE_UNAVAILABLE"
    elif stored is not None and stored != computed:
        problem = "CONTENT_CLAIM_BASIS_MISMATCH"
    return {
        "index": index,
        "text": text,
        "status": status,
        "basis": stored,
        "computed_basis": computed,
        "basis_recorded": stored is not None,
        "provider_basis": provider,
        "refs": refs,
        "problem": problem,
    }


def summary_is_current(summary: dict[str, Any], expected: SummarySelectionExpectation) -> bool:
    """Current only when built from the expected transcript with the same recorded key.

    Two missing keys (legacy) are not a verified current setting.
    """
    key = summary.get("settings_key")
    return (
        summary.get("transcript_revision_id") == expected.transcript_id
        and key is not None
        and expected.summary_settings_key is not None
        and key == expected.summary_settings_key
    )


class ContentStore:
    """Content connection shares Library's root ordering and deletion boundary.

    Only content-owned tables are added. Library owns user_version and sessions.
    Returned JSON dictionaries are fresh copies, never mutable stored objects.
    """

    def __init__(self, library: Library) -> None:
        if not isinstance(library, Library):
            raise ValidationError("CONTENT_LIBRARY_REQUIRED")
        self.library = library
        self._mutex = root_mutex(library.root)
        self._closed = False
        with self._mutex:
            library.check_local_catalog()  # Construction is not management/publication permission.
            self._db = sqlite3.connect(
                library.db_path, timeout=5, isolation_level=None, check_same_thread=False
            )
            self._db.row_factory = sqlite3.Row
            try:
                self._check_version(self._db)
                self._db.execute("PRAGMA foreign_keys=ON")
                self._db.execute("PRAGMA synchronous=FULL")
                self._db.executescript("""
                    BEGIN IMMEDIATE;
                    CREATE TABLE IF NOT EXISTS content_revisions (
                        revision_id TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
                        revision_type TEXT NOT NULL, body TEXT NOT NULL, sha256 TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS content_session ON content_revisions(session_id);
                    CREATE TABLE IF NOT EXISTS content_selections (
                        session_id TEXT PRIMARY KEY REFERENCES sessions(session_id) ON DELETE CASCADE,
                        transcript_id TEXT, summary_id TEXT,
                        transcript_version INTEGER NOT NULL DEFAULT 0,
                        summary_version INTEGER NOT NULL DEFAULT 0
                    );
                    CREATE TABLE IF NOT EXISTS content_events (
                        event_id INTEGER PRIMARY KEY,
                        session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
                        revision_id TEXT NOT NULL, revision_type TEXT NOT NULL,
                        selected INTEGER NOT NULL
                    );
                    CREATE TRIGGER IF NOT EXISTS content_revision_immutable
                    BEFORE UPDATE ON content_revisions
                    BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_CONTENT_REVISION'); END;
                    CREATE TABLE IF NOT EXISTS content_summary_requests (
                        session_id TEXT PRIMARY KEY REFERENCES sessions(session_id) ON DELETE CASCADE,
                        settings_key TEXT NOT NULL,
                        request_count INTEGER NOT NULL DEFAULT 1
                    );
                    COMMIT;
                """)
            except BaseException:
                self._db.close()
                self._closed = True
                raise

    @staticmethod
    def _check_version(connection: sqlite3.Connection) -> None:
        if connection.execute("PRAGMA user_version").fetchone()[0] != 1:
            raise ValidationError("UNSUPPORTED_CONTENT_LIBRARY_SCHEMA")

    def _ensure_open(self) -> None:
        if self._closed:
            raise StateConflict("CONTENT_STORE_CLOSED")

    def close(self) -> None:
        with self._mutex:
            if not self._closed:
                self._db.close()
                self._closed = True

    def __enter__(self) -> ContentStore:
        self._ensure_open()
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._mutex:
            self._ensure_open()
            self._check_version(self._db)
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield self._db
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise

    def _live(self, connection: sqlite3.Connection, session_id: str) -> None:
        identifier(session_id)
        self._ensure_open()
        self._check_version(connection)
        # Atomic Job callbacks use only the supplied SQL connection. Their caller
        # performs the filesystem/journal preflight under root_mutex first.
        if connection is self._db:
            self.library.get_session(session_id)
        if connection.execute(
            "SELECT 1 FROM deleted_sessions WHERE session_id=?", (session_id,)
        ).fetchone():
            raise StateConflict("CONTENT_SESSION_DELETED")
        if (
            connection.execute(
                "SELECT 1 FROM sessions WHERE session_id=?", (session_id,)
            ).fetchone()
            is None
        ):
            raise StateConflict("CONTENT_SESSION_MISSING")

    @staticmethod
    def _selection(
        connection: sqlite3.Connection, session_id: str
    ) -> tuple[str | None, str | None]:
        row = connection.execute(
            "SELECT transcript_id,summary_id FROM content_selections WHERE session_id=?",
            (session_id,),
        ).fetchone()
        return (row[0], row[1]) if row is not None else (None, None)

    @staticmethod
    def _selection_versions(connection: sqlite3.Connection, session_id: str) -> tuple[int, int]:
        row = connection.execute(
            "SELECT transcript_version,summary_version FROM content_selections WHERE session_id=?",
            (session_id,),
        ).fetchone()
        return (row[0], row[1]) if row is not None else (0, 0)

    @staticmethod
    def _requested_settings(connection: sqlite3.Connection, session_id: str) -> str | None:
        row = connection.execute(
            "SELECT settings_key FROM content_summary_requests WHERE session_id=?", (session_id,)
        ).fetchone()
        return row[0] if row is not None else None

    def selection_state(self, session_id: str) -> dict[str, Any]:
        """One consistent read of both selections, their versions and requested settings."""
        with self._mutex:
            self._live(self._db, session_id)
            transcript_id, summary_id = self._selection(self._db, session_id)
            transcript_version, summary_version = self._selection_versions(self._db, session_id)
            return {
                "session_id": session_id,
                "transcript_id": transcript_id,
                "transcript_version": transcript_version,
                "summary_id": summary_id,
                "summary_version": summary_version,
                "summary_settings_key": self._requested_settings(self._db, session_id),
            }

    def request_summary_settings(self, session_id: str, settings_key: str) -> None:
        """Record the latest admitted summary settings; selection versions stay unchanged."""
        # Required here; only publish_summary's optional key keeps None as ID-only CAS.
        text_value(settings_key, maximum=256, empty=False)
        with self._transaction() as connection:
            self._live(connection, session_id)
            connection.execute(
                "INSERT INTO content_summary_requests(session_id,settings_key) VALUES(?,?) "
                "ON CONFLICT(session_id) DO UPDATE SET settings_key=excluded.settings_key,"
                "request_count=request_count+1",
                (session_id, settings_key),
            )

    def _load(
        self,
        connection: sqlite3.Connection,
        revision_id: str,
        revision_type: str,
        *,
        checked_session: str | None = None,
    ) -> dict[str, Any]:
        identifier(revision_id)
        row = connection.execute(
            "SELECT * FROM content_revisions WHERE revision_id=?", (revision_id,)
        ).fetchone()
        if row is None:
            raise KeyError(revision_id)
        if checked_session is None or row["session_id"] != checked_session:
            # A caller that already checked this session under the same held mutex
            # (list_revisions) skips only that repeated filesystem/journal check.
            self._live(connection, row["session_id"])
        if row["revision_type"] != revision_type:
            raise ValidationError("CONTENT_REVISION_TYPE_MISMATCH")
        body = row["body"]
        if (
            not isinstance(body, str)
            or hashlib.sha256(body.encode("utf-8")).hexdigest() != row["sha256"]
        ):
            raise ValidationError("CONTENT_REVISION_INTEGRITY")
        try:
            value = json.loads(body)
        except (ValueError, RecursionError) as exc:
            raise ValidationError("CONTENT_REVISION_SCHEMA") from exc
        if (
            not isinstance(value, dict)
            or type(value.get("schema_version")) is not int
            or value["schema_version"] != 1
            or value.get("revision_id") != revision_id
            or value.get("session_id") != row["session_id"]
        ):
            raise ValidationError("CONTENT_REVISION_SCHEMA")
        value["revision_type"] = row["revision_type"]
        value.setdefault("kind", row["revision_type"])
        value["content_hash"] = row["sha256"]
        return value

    @staticmethod
    def _save(
        connection: sqlite3.Connection, body: dict[str, Any], revision_type: str, selected: bool
    ) -> None:
        encoded = _encode(body)
        connection.execute(
            "INSERT INTO content_revisions VALUES(?,?,?,?,?)",
            (
                body["revision_id"],
                body["session_id"],
                revision_type,
                encoded,
                hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
            ),
        )
        connection.execute(
            "INSERT INTO content_events(session_id,revision_id,revision_type,selected) VALUES(?,?,?,?)",
            (body["session_id"], body["revision_id"], revision_type, int(selected)),
        )

    @staticmethod
    def _segments(segments: Sequence[Segment]) -> tuple[Segment, ...]:
        if not isinstance(segments, Sequence) or isinstance(segments, (str, bytes)):
            raise ValidationError("INVALID_TRANSCRIPT_SEGMENTS")
        result = tuple(segments)
        if len(result) > _MAX_ITEMS or any(not isinstance(item, Segment) for item in result):
            raise ValidationError("INVALID_TRANSCRIPT_SEGMENTS")
        if len({s.segment_id for s in result}) != len(result):
            raise ValidationError("DUPLICATE_SEGMENT_ID")
        last_times: dict[str | None, int] = {}
        for item in result:
            if item.timing_quality == "unverified":
                continue
            if item.start_ms < last_times.get(item.track_id, 0):
                raise ValidationError("UNORDERED_TRANSCRIPT_SEGMENTS")
            last_times[item.track_id] = item.start_ms
        return result

    def _create_transcript(
        self,
        connection: sqlite3.Connection,
        session_id: str,
        segments: tuple[Segment, ...],
        kind: str,
        parent_revision_id: str | None,
        expected_active: str | None,
        select: bool = True,
        audio_revision_id: str | None = None,
        coverage: dict[str, Any] | None = None,
        partial: bool = False,
        allow_draft_selection: bool = False,
        expected_version: int | None = None,
    ) -> str:
        self._live(connection, session_id)
        if parent_revision_id is not None:
            parent = self._load(connection, parent_revision_id, "transcript")
            if parent["session_id"] != session_id:
                raise ValidationError("CONTENT_PARENT_SESSION_MISMATCH")
        normalized, covered = _coverage(coverage, [item.segment_id for item in segments])
        complete = kind != "draft" and covered and not partial
        active, _ = self._selection(connection, session_id)
        version, _ = self._selection_versions(connection, session_id)
        selected = select and (complete or allow_draft_selection) and active == expected_active
        if expected_version is not None and version != expected_version:
            # A selection that moved away and back keeps its ID but not its version.
            selected = False
        revision_id = uuid4().hex
        body = {
            "schema_version": 1,
            "revision_id": revision_id,
            "session_id": session_id,
            "kind": "draft" if kind == "corrected" and not complete else kind,
            "segments": [asdict(item) for item in segments],
            "parent_revision_id": parent_revision_id,
            "complete": complete,
            "coverage": normalized,
            "audio_revision_id": audio_revision_id,
        }
        self._save(connection, body, "transcript", selected)
        connection.execute(
            "INSERT OR IGNORE INTO content_selections(session_id) VALUES(?)", (session_id,)
        )
        if selected:
            connection.execute(
                "UPDATE content_selections SET transcript_id=?,transcript_version=transcript_version+1 "
                "WHERE session_id=?",
                (revision_id, session_id),
            )
        return revision_id

    @staticmethod
    def _transcript_arguments(
        kind: str, parent_revision_id: str | None, expected_active: str | None
    ) -> None:
        if kind not in ("draft", "corrected", "edited"):
            raise ValidationError("INVALID_TRANSCRIPT_KIND")
        _expected(parent_revision_id)
        _expected(expected_active)

    def create_transcript(
        self,
        session_id: str,
        segments: Sequence[Segment],
        *,
        kind: str = "corrected",
        parent_revision_id: str | None = None,
        expected_active: str | None = None,
        audio_revision_id: str | None = None,
        coverage: dict[str, Any] | None = None,
    ) -> str:
        values = self._segments(segments)
        self._transcript_arguments(kind, parent_revision_id, expected_active)
        _expected(audio_revision_id)
        with self._transaction() as connection:
            return self._create_transcript(
                connection,
                session_id,
                values,
                kind,
                parent_revision_id,
                expected_active,
                audio_revision_id=audio_revision_id,
                coverage=coverage,
            )

    def transcript(self, revision_id: str) -> dict[str, Any]:
        with self._mutex:
            self._ensure_open()
            return self._load(self._db, revision_id, "transcript")

    def active_transcript(self, session_id: str) -> dict[str, Any] | None:
        with self._mutex:
            self._live(self._db, session_id)
            revision_id, _ = self._selection(self._db, session_id)
            return None if revision_id is None else self._load(self._db, revision_id, "transcript")

    def edit_segment(
        self,
        session_id: str,
        revision_id: str,
        segment_id: str,
        text: str,
        *,
        expected_active: str | None,
    ) -> str:
        text_value(text)
        identifier(segment_id)
        _expected(expected_active)
        with self._transaction() as connection:
            source = self._load(connection, revision_id, "transcript")
            if source["session_id"] != session_id:
                raise ValidationError("CONTENT_PARENT_SESSION_MISMATCH")
            segments = [Segment(**item) for item in source["segments"]]
            if not any(item.segment_id == segment_id for item in segments):
                raise KeyError(segment_id)
            edited = tuple(
                replace(item, text=text, provenance="user_assertion", timing_quality="unverified")
                if item.segment_id == segment_id
                else item
                for item in segments
            )
            return self._create_transcript(
                connection,
                session_id,
                edited,
                "edited",
                revision_id,
                expected_active,
                audio_revision_id=source.get("audio_revision_id"),
                coverage=source.get("coverage"),
                partial=not source["complete"],
            )

    def search(self, session_id: str, query: str) -> list[Segment]:
        text_value(query, maximum=4096)
        active = self.active_transcript(session_id)
        if active is None or not query:
            return []
        return [
            Segment(**item)
            for item in active["segments"]
            if query.casefold() in item["text"].casefold()
        ]

    @staticmethod
    def _claims(claims: Sequence[Claim]) -> tuple[Claim, ...]:
        if not isinstance(claims, Sequence) or isinstance(claims, (str, bytes)):
            raise ValidationError("INVALID_SUMMARY_CLAIMS")
        result = tuple(claims)
        if len(result) > _MAX_ITEMS or any(not isinstance(item, Claim) for item in result):
            raise ValidationError("INVALID_SUMMARY_CLAIMS")
        return result

    def _create_summary(
        self,
        connection: sqlite3.Connection,
        session_id: str,
        transcript_revision_id: str,
        claims: tuple[Claim, ...],
        template: str,
        expected_transcript: str | None,
        expected_summary: str | None,
        select: bool = True,
        coverage: dict[str, Any] | None = None,
        partial: bool = False,
        expected_transcript_version: int | None = None,
        expected_summary_version: int | None = None,
        settings_key: str | None = None,
    ) -> str:
        self._live(connection, session_id)
        source = self._load(connection, transcript_revision_id, "transcript")
        if source["session_id"] != session_id:
            raise ValidationError("CONTENT_PARENT_SESSION_MISMATCH")
        source_segments = {s["segment_id"]: s for s in source["segments"]}
        encoded_claims = []
        for claim in claims:
            if any(ref not in source_segments for ref in claim.segment_ids):
                raise ValidationError("UNKNOWN_CLAIM_SEGMENT")
            provenance = {source_segments[ref]["provenance"] for ref in claim.segment_ids}
            encoded: dict[str, Any] = {
                "text": claim.text,
                "segment_ids": list(claim.segment_ids),
                "status": claim.status,
                "basis": canonical_basis(provenance, bool(claim.segment_ids)),
            }
            if claim.provider_basis is not None:
                # Optional v1 envelope field: the adapter's reference value only.
                encoded["provider_basis"] = claim.provider_basis
            encoded_claims.append(encoded)
        active_transcript, active_summary = self._selection(connection, session_id)
        transcript_version, summary_version = self._selection_versions(connection, session_id)
        requested = self._requested_settings(connection, session_id)
        normalized, covered = _coverage(coverage, list(source_segments))
        complete = source["complete"] and covered and not partial
        selected = (
            select
            and complete
            and active_transcript == expected_transcript == transcript_revision_id
            and active_summary == expected_summary
            and (
                expected_transcript_version is None
                or transcript_version == expected_transcript_version
            )
            and (expected_summary_version is None or summary_version == expected_summary_version)
            # An older settings request cannot replace the result of the latest one.
            and (settings_key is None or requested is None or requested == settings_key)
        )
        revision_id = uuid4().hex
        body = {
            "schema_version": 1,
            "revision_id": revision_id,
            "session_id": session_id,
            "transcript_revision_id": transcript_revision_id,
            "transcript_hash": source["content_hash"],
            "claims": encoded_claims,
            "template": template,
            "complete": complete,
            "coverage": normalized,
            "audio_revision_id": source.get("audio_revision_id"),
        }
        if settings_key is not None:
            body["settings_key"] = settings_key
        self._save(connection, body, "summary", selected)
        if selected:
            connection.execute(
                "UPDATE content_selections SET summary_id=?,summary_version=summary_version+1 WHERE session_id=?",
                (revision_id, session_id),
            )
        return revision_id

    def _publication_preflight(
        self, jobs: JobStore, attempt: AttemptRecord, session_id: str
    ) -> None:
        if not isinstance(jobs, JobStore) or not isinstance(attempt, AttemptRecord):
            raise ValidationError("INVALID_CONTENT_JOB_CONTEXT")
        self._live(self._db, session_id)
        jobs._ensure_open()
        path = jobs._db.execute("PRAGMA database_list").fetchone()[2]
        if Path(path) != self.library.db_path:
            raise ValidationError("CONTENT_JOB_DATABASE_MISMATCH")
        self._publication_session(jobs._db, attempt, session_id)

    @staticmethod
    def _publication_session(
        connection: sqlite3.Connection, attempt: AttemptRecord, session_id: str
    ) -> None:
        binding = connection.execute(
            "SELECT session_id FROM job_sessions WHERE job_id=?", (attempt.job_id,)
        ).fetchone()
        if binding is not None and binding[0] != session_id:
            raise StateConflict("CONTENT_JOB_SESSION_MISMATCH")

    def publish_transcript(
        self,
        jobs: JobStore,
        attempt: AttemptRecord,
        session_id: str,
        segments: Sequence[Segment],
        *,
        complete: bool = True,
        kind: str = "corrected",
        parent_revision_id: str | None = None,
        expected_active: str | None = None,
        audio_revision_id: str | None = None,
        coverage: dict[str, Any] | None = None,
        expected_transcript_version: int | None = None,
    ) -> str:
        """Atomic fenced result, or an inactive draft checkpoint when incomplete.

        expected_transcript_version, captured with selection_state() when the work
        was planned, keeps a late result a candidate after the selection moved,
        including a move away and back to the same revision ID.
        """
        values = self._segments(segments)
        self._transcript_arguments(kind, parent_revision_id, expected_active)
        _expected(audio_revision_id)
        _expected_version(expected_transcript_version)
        normalized, covered = _coverage(coverage, [item.segment_id for item in values])
        if type(complete) is not bool or (complete and not covered):
            raise ValidationError("INVALID_CONTENT_COMPLETENESS")
        if not isinstance(jobs, JobStore):
            raise ValidationError("INVALID_CONTENT_JOB_CONTEXT")
        with self._mutex, jobs._lock:
            self._publication_preflight(jobs, attempt, session_id)
            streaming = jobs.get(attempt.job_id).kind == "streaming_transcription"
            if complete and kind == "draft" and not streaming:
                raise ValidationError("PARTIAL_TRANSCRIPT_REQUIRES_CHECKPOINT")

            def publisher(connection: sqlite3.Connection) -> str:
                self._publication_session(connection, attempt, session_id)
                return self._create_transcript(
                    connection,
                    session_id,
                    values,
                    kind if complete else "draft",
                    parent_revision_id,
                    expected_active,
                    select=complete,
                    audio_revision_id=audio_revision_id,
                    coverage=normalized,
                    partial=not complete,
                    allow_draft_selection=streaming and complete,
                    expected_version=expected_transcript_version,
                )

            _, revision_id = jobs._publish_with(
                attempt.job_id, attempt.attempt_id, attempt.fence, publisher, complete=complete
            )
            return revision_id

    def publish_summary(
        self,
        jobs: JobStore,
        attempt: AttemptRecord,
        session_id: str,
        transcript_revision_id: str,
        claims: Sequence[Claim],
        *,
        complete: bool = True,
        template: str = "meeting",
        expected_transcript: str | None = None,
        expected_summary: str | None = None,
        coverage: dict[str, Any] | None = None,
        expected_transcript_version: int | None = None,
        expected_summary_version: int | None = None,
        settings_key: str | None = None,
    ) -> str:
        """Selected only if IDs, both captured selection versions and settings still match.

        A mismatch stores the result as a candidate of its original input.
        """
        values = self._claims(claims)
        text_value(template, maximum=128, empty=False)
        _expected(expected_transcript)
        _expected(expected_summary)
        _expected_version(expected_transcript_version)
        _expected_version(expected_summary_version)
        _settings_key(settings_key)
        if type(complete) is not bool or not isinstance(jobs, JobStore):
            raise ValidationError("INVALID_CONTENT_JOB_CONTEXT")
        with self._mutex, jobs._lock:
            self._publication_preflight(jobs, attempt, session_id)

            def publisher(connection: sqlite3.Connection) -> str:
                self._publication_session(connection, attempt, session_id)
                source = self._load(connection, transcript_revision_id, "transcript")
                normalized, covered = _coverage(
                    coverage, [item["segment_id"] for item in source["segments"]]
                )
                if complete and (not source["complete"] or not covered):
                    raise ValidationError("INCOMPLETE_SUMMARY_INPUT")
                return self._create_summary(
                    connection,
                    session_id,
                    transcript_revision_id,
                    values,
                    template,
                    expected_transcript,
                    expected_summary,
                    select=complete,
                    coverage=normalized,
                    partial=not complete,
                    expected_transcript_version=expected_transcript_version,
                    expected_summary_version=expected_summary_version,
                    settings_key=settings_key,
                )

            _, revision_id = jobs._publish_with(
                attempt.job_id, attempt.attempt_id, attempt.fence, publisher, complete=complete
            )
            return revision_id

    def list_revisions(self, session_id: str, kind: str | None = None) -> list[dict[str, Any]]:
        if kind not in (None, "transcript", "summary", "draft", "corrected", "edited"):
            raise ValidationError("INVALID_CONTENT_REVISION_FILTER")
        with self._mutex:
            self._live(self._db, session_id)
            active_transcript, active_summary = self._selection(self._db, session_id)
            values = []
            for row in self._db.execute(
                "SELECT revision_id,revision_type FROM content_revisions "
                "WHERE session_id=? ORDER BY rowid",
                (session_id,),
            ).fetchall():
                value = self._load(self._db, row[0], row[1], checked_session=session_id)
                if kind is not None and kind not in (row[1], value.get("kind")):
                    continue
                value["selected"] = value["revision_id"] in (active_transcript, active_summary)
                if row[1] == "summary":
                    value["stale"] = value["transcript_revision_id"] != active_transcript
                values.append(value)
            return values

    def _select(
        self, session_id: str, revision_id: str, expected_active: str | None, revision_type: str
    ) -> bool:
        _expected(expected_active)
        with self._transaction() as connection:
            source = self._load(connection, revision_id, revision_type)
            self._live(connection, session_id)
            if source["session_id"] != session_id:
                raise ValidationError("CONTENT_SELECTION_SESSION_MISMATCH")
            active_transcript, active_summary = self._selection(connection, session_id)
            active = active_transcript if revision_type == "transcript" else active_summary
            if active != expected_active:
                return False
            column = "transcript_id" if revision_type == "transcript" else "summary_id"
            version = "transcript_version" if revision_type == "transcript" else "summary_version"
            connection.execute(
                f"UPDATE content_selections SET {column}=?,{version}={version}+1 "
                "WHERE session_id=?",
                (revision_id, session_id),
            )
            connection.execute(
                "INSERT INTO content_events(session_id,revision_id,revision_type,selected) "
                "VALUES(?,?,?,1)",
                (session_id, revision_id, "select_" + revision_type),
            )
            return True

    def select_transcript(
        self, session_id: str, revision_id: str, *, expected_active: str | None
    ) -> bool:
        return self._select(session_id, revision_id, expected_active, "transcript")

    def select_summary(
        self, session_id: str, revision_id: str, *, expected_active: str | None
    ) -> bool:
        return self._select(session_id, revision_id, expected_active, "summary")

    def create_summary(
        self,
        session_id: str,
        transcript_revision_id: str,
        claims: Sequence[Claim],
        *,
        template: str = "meeting",
        expected_transcript: str | None = None,
        expected_summary: str | None = None,
        coverage: dict[str, Any] | None = None,
    ) -> str:
        text_value(template, maximum=128, empty=False)
        _expected(expected_transcript)
        _expected(expected_summary)
        values = self._claims(claims)
        with self._transaction() as connection:
            return self._create_summary(
                connection,
                session_id,
                transcript_revision_id,
                values,
                template,
                expected_transcript,
                expected_summary,
                coverage=coverage,
            )

    def claim_evidence(self, revision_id: str) -> list[dict[str, Any]]:
        """Read-only evidence view of a summary against its fixed source revision.

        Recomputes each claim's canonical basis from the original transcript revision
        and compares it with the stored value; nothing is rewritten. A mismatch, an
        invalid stored value or an unreadable source is "evidence unverifiable"
        (``CONTENT_CLAIM_BASIS_MISMATCH`` / ``source_ok=False``) and never seekable.
        """
        with self._mutex:
            self._ensure_open()
            summary = self._load(self._db, revision_id, "summary")
            try:
                source = self._load(self._db, summary["transcript_revision_id"], "transcript")
                segments = {item["segment_id"]: item for item in source["segments"]}
                source_ok = source["content_hash"] == summary.get("transcript_hash")
            except (KeyError, ValidationError, StateConflict):
                segments, source_ok = {}, False
            claims = summary.get("claims", [])
            if not isinstance(claims, list):
                raise ValidationError("CONTENT_REVISION_SCHEMA")
            views = []
            for index, claim in enumerate(claims):
                views.append(_claim_view(index, claim, segments, source_ok))
            return views

    def select_summary_candidate(
        self,
        session_id: str,
        revision_id: str,
        *,
        expected: SummarySelectionExpectation,
        allow_outdated: bool = False,
    ) -> bool:
        """Select a summary only if the presented snapshot still holds exactly.

        Every snapshot field (both IDs, both versions, the requested settings key, None
        included) is compared inside the transaction; a mismatch returns False with no
        write. A partial candidate is refused; an earlier-transcript/settings or
        unverifiable candidate needs ``allow_outdated`` after an explicit confirmation.
        """
        if type(expected) is not SummarySelectionExpectation or type(allow_outdated) is not bool:
            raise ValidationError("INVALID_SUMMARY_SELECTION_EXPECTATION")
        identifier(revision_id)
        if expected.session_id != session_id:
            raise ValidationError("CONTENT_SELECTION_SESSION_MISMATCH")
        with self._transaction() as connection:
            target = self._load(connection, revision_id, "summary")
            self._live(connection, session_id)
            if target["session_id"] != session_id:
                raise ValidationError("CONTENT_SELECTION_SESSION_MISMATCH")
            if not target.get("complete"):
                raise StateConflict("CONTENT_SUMMARY_NOT_COMPLETE")
            transcript_id, summary_id = self._selection(connection, session_id)
            transcript_version, summary_version = self._selection_versions(connection, session_id)
            observed = (
                transcript_id,
                transcript_version,
                summary_id,
                summary_version,
                self._requested_settings(connection, session_id),
            )
            if observed != (
                expected.transcript_id,
                expected.transcript_version,
                expected.summary_id,
                expected.summary_version,
                expected.summary_settings_key,
            ):
                return False
            if not summary_is_current(target, expected) and not allow_outdated:
                raise StateConflict("CONTENT_SUMMARY_OUTDATED_CONFIRMATION_REQUIRED")
            connection.execute(
                "UPDATE content_selections SET summary_id=?,summary_version=summary_version+1 "
                "WHERE session_id=?",
                (revision_id, session_id),
            )
            connection.execute(
                "INSERT INTO content_events(session_id,revision_id,revision_type,selected) "
                "VALUES(?,?,?,1)",
                (session_id, revision_id, "select_summary"),
            )
            return True

    def summary(self, revision_id: str) -> dict[str, Any]:
        with self._mutex:
            self._ensure_open()
            value = self._load(self._db, revision_id, "summary")
            active, _ = self._selection(self._db, value["session_id"])
            value["stale"] = value["transcript_revision_id"] != active
            return value

    def active_summary(self, session_id: str) -> dict[str, Any] | None:
        with self._mutex:
            self._live(self._db, session_id)
            _, revision_id = self._selection(self._db, session_id)
            return None if revision_id is None else self.summary(revision_id)

    def export_transcript(self, revision_id: str, format: str) -> str:
        value = self.transcript(revision_id)
        if format == "json":
            return _encode(value)
        if format == "txt":
            return "\n".join(item["text"] for item in value["segments"])
        if format not in ("srt", "vtt"):
            raise ValidationError("UNSUPPORTED_TRANSCRIPT_EXPORT")
        cues = []
        for number, item in enumerate(value["segments"], 1):
            start = _timestamp(item["start_ms"], format)
            end = _timestamp(item["end_ms"], format)
            text = item["text"].replace("\r\n", "\n").replace("\r", "\n")
            text = "\n".join(line for line in text.split("\n") if line.strip())
            if format == "vtt":
                text = html.escape(text)
            cues.append(f"{number}\n{start} --> {end}\n{text}\n")
        return ("WEBVTT\n\n" if format == "vtt" else "") + "\n".join(cues)


def _timestamp(value: int, format: str) -> str:
    seconds, milliseconds = divmod(value, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}{',' if format == 'srt' else '.'}{milliseconds:03}"
