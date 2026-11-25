"""G-P13: what a local model loader is given, and the current run's explicit confirmation.

An artifact digest is this app's own canonical description of the exact bytes (and the
present/absent optional inputs) a loader receives. It is a technical integrity identity:
it is not a publisher signature, a license approval, a quality check or an official
digest comparison. A confirmation lives only in memory for the current run; nothing here
is persisted as "trusted forever" and no confirmation is a transfer grant or a cost
approval.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any

from recoryn.domain import ValidationError

WHISPER, DIARIZATION = "whisper", "diarization"
KINDS = (WHISPER, DIARIZATION)
# The loader contract the digest is bound to (the pinned SDK's input mapping).
LOADERS = {
    WHISPER: "faster-whisper-1.2.1-files-v1",
    DIARIZATION: "sherpa-onnx-2.0.1-pyannote-v1",
}
MANAGED, MANUAL = "MANAGED", "MANUAL"
SOURCE_KINDS = (MANAGED, MANUAL)
PRESENT, ABSENT_DEFAULT, ABSENT = "PRESENT", "ABSENT_DEFAULT", "ABSENT"
ENTRY_STATES = (PRESENT, ABSENT_DEFAULT, ABSENT)

# Whisper (faster-whisper files mapping): required, optional and license inputs.
WHISPER_REQUIRED = ("config.json", "model.bin", "tokenizer.json")
# G13R-01: the pinned faster-whisper 1.2.1 fetches its own models with "vocabulary.*"
# (faster_whisper/utils.py download_model allow_patterns), so both vocabulary forms are
# optional loader inputs; a folder holding both is ambiguous and refused.
WHISPER_OPTIONAL = ("preprocessor_config.json", "vocabulary.json", "vocabulary.txt")
WHISPER_VOCABULARIES = ("vocabulary.json", "vocabulary.txt")
# License files are matched case-insensitively and recorded under their real name.
WHISPER_LICENSES = ("LICENSE", "LICENSE.md", "LICENSE.txt")
# Load inputs this loader contract does not support (a shared vocabulary is not Whisper's).
WHISPER_UNSUPPORTED = ("shared_vocabulary.json", "shared_vocabulary.txt")
# A missing preprocessor is the fixed default, never a lookup next to the model.
PREPROCESSOR_DEFAULT = b"{}"
DIARIZATION_FILES = ("embedding.onnx", "manifest.json", "segmentation.onnx")
DIARIZATION_LICENSES = ("LICENSE.embedding.txt", "LICENSE.segmentation.txt")

# Integrity of the snapshot against its expected reference.
MATCH, SELF_DIGEST, INVALID = "MATCH", "SELF_DIGEST", "INVALID"
# License display states: id/URL and text, text only, id/URL only, nothing (G13R-06).
DECLARED, FILE_ONLY, METADATA_ONLY, NOT_PROVIDED = (
    "DECLARED",
    "FILE_ONLY",
    "METADATA_ONLY",
    "NOT_PROVIDED",
)
# Source authenticity: nothing in v1 authenticates a publisher.
UNVERIFIED = "UNVERIFIED"
# Display states (U).
UNCONFIRMED = "UNCONFIRMED"
MANUAL_USER_CONFIRMED = "MANUAL_USER_CONFIRMED"
MANAGED_PIN_MATCH = "MANAGED_PIN_MATCH"
CHANGED_INVALID = "CHANGED_INVALID"
LICENSE_UNCONFIRMED = "LICENSE_UNCONFIRMED"

ARTIFACT_DOMAIN = b"recoryn.model-artifact.v1\x00"
TERMS_DOMAIN = b"recoryn.model-terms.v1\x00"
MAX_SIZE = 2**53
_DIGEST = re.compile(r"[0-9a-f]{64}")
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


def checked_digest(value: object) -> str:
    """A lowercase SHA-256 hex digest (bool, non-text, wrong length or case refused)."""
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise ValidationError("MODEL_DIGEST_INVALID")
    return value


def checked_size(value: object) -> int:
    if type(value) is not int or not 0 <= value <= MAX_SIZE:
        raise ValidationError("MODEL_SIZE_INVALID")
    return value


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("ascii")


@dataclass(frozen=True)
class FileEntry:
    """One loader input: its exact name, size and SHA-256, or its absence (and default)."""

    name: str
    size: int
    sha256: str
    state: str = PRESENT

    def __post_init__(self) -> None:
        if type(self.name) is not str or _NAME.fullmatch(self.name) is None or ".." in self.name:
            raise ValidationError("MODEL_NAME_INVALID")
        if self.state not in ENTRY_STATES:
            raise ValidationError("MODEL_ENTRY_INVALID")
        if self.state == PRESENT:
            checked_size(self.size)
            checked_digest(self.sha256)
        elif self.size != 0 or self.sha256 != "" or type(self.size) is not int:
            raise ValidationError("MODEL_ENTRY_INVALID")

    def row(self) -> list[Any]:
        return [self.name, self.size, self.sha256, self.state]


def _sorted_entries(entries: tuple[FileEntry, ...]) -> list[FileEntry]:
    if type(entries) is not tuple or any(not isinstance(e, FileEntry) for e in entries):
        raise ValidationError("MODEL_ENTRY_INVALID")
    folded = [entry.name.casefold() for entry in entries]
    if len(set(folded)) != len(folded):
        raise ValidationError("MODEL_NAME_COLLISION")
    return sorted(entries, key=lambda entry: entry.name)


def artifact_digest(kind: str, loader: str, entries: tuple[FileEntry, ...]) -> str:
    """Domain-tagged SHA-256 of the canonical description; a moved file boundary or a
    renamed file is another identity even when the concatenated bytes are equal."""
    if kind not in KINDS or loader != LOADERS[kind]:
        raise ValidationError("MODEL_LOADER_INVALID")
    payload = {
        "files": [entry.row() for entry in _sorted_entries(entries)],
        "kind": kind,
        "loader": loader,
        "version": 1,
    }
    return hashlib.sha256(ARTIFACT_DOMAIN + canonical_json(payload)).hexdigest()


@dataclass(frozen=True)
class Terms:
    """What the confirmation showed about origin and license (never opened by the app)."""

    source_kind: str
    license_id: str | None = None
    license_url: str | None = None
    license_files: tuple[FileEntry, ...] = ()
    reference: str | None = None  # managed spec digest / the user's pinned manifest SHA

    def __post_init__(self) -> None:
        if self.source_kind not in SOURCE_KINDS:
            raise ValidationError("MODEL_SOURCE_INVALID")
        for text in (self.license_id, self.license_url):
            if text is not None and (type(text) is not str or not text.strip() or len(text) > 4096):
                raise ValidationError("MODEL_TERMS_INVALID")
        _sorted_entries(self.license_files)
        if any(entry.state != PRESENT for entry in self.license_files):
            raise ValidationError("MODEL_TERMS_INVALID")
        if self.reference is not None:
            checked_digest(self.reference)

    @property
    def license_state(self) -> str:
        if self.license_files and (self.license_id or self.license_url):
            return DECLARED
        if self.license_files:
            return FILE_ONLY  # a license text, but no identifier or URL was declared
        if self.license_id or self.license_url:
            return METADATA_ONLY
        return NOT_PROVIDED


def terms_digest(terms: Terms) -> str:
    payload = {
        "license_files": [entry.row() for entry in _sorted_entries(terms.license_files)],
        "license_id": terms.license_id if terms.license_id is not None else "UNKNOWN",
        "license_url": terms.license_url if terms.license_url is not None else "UNKNOWN",
        "reference": terms.reference if terms.reference is not None else "NONE",
        "source_kind": terms.source_kind,
        "version": 1,
    }
    return hashlib.sha256(TERMS_DOMAIN + canonical_json(payload)).hexdigest()


RootIdentity = tuple[int, int, str]


@dataclass(frozen=True)
class ModelSourceSnapshot:
    """The source as hashed for one preview or one pre-native re-check (safe metadata)."""

    kind: str
    source_kind: str
    root: str
    root_identity: RootIdentity
    entries: tuple[FileEntry, ...]
    terms: Terms
    integrity: str
    model_id: str | None = None
    loader: str = ""
    artifact_digest: str = ""
    terms_digest: str = ""
    source_authenticity: str = UNVERIFIED

    def __post_init__(self) -> None:
        if self.kind not in KINDS or self.source_kind not in SOURCE_KINDS:
            raise ValidationError("MODEL_SOURCE_INVALID")
        if self.terms.source_kind != self.source_kind or self.integrity not in (
            MATCH,
            SELF_DIGEST,
            INVALID,
        ):
            raise ValidationError("MODEL_SOURCE_INVALID")
        identity = self.root_identity
        if (
            type(identity) is not tuple
            or len(identity) != 3
            or any(type(part) is not int for part in identity[:2])
            or type(identity[2]) is not str
            or type(self.root) is not str
        ):
            raise ValidationError("MODEL_SOURCE_INVALID")
        if self.source_authenticity != UNVERIFIED:
            raise ValidationError("MODEL_SOURCE_INVALID")  # no publisher authentication in v1
        loader = self.loader or LOADERS[self.kind]
        digest = artifact_digest(self.kind, loader, self.entries)
        terms = terms_digest(self.terms)
        if (self.artifact_digest and self.artifact_digest != digest) or (
            self.terms_digest and self.terms_digest != terms
        ):
            raise ValidationError("MODEL_DIGEST_INVALID")  # a forged description
        object.__setattr__(self, "loader", loader)
        object.__setattr__(self, "artifact_digest", digest)
        object.__setattr__(self, "terms_digest", terms)

    @property
    def license_state(self) -> str:
        return self.terms.license_state

    def entry(self, name: str) -> FileEntry | None:
        return next((entry for entry in self.entries if entry.name == name), None)


@dataclass(frozen=True)
class ConfirmationKey:
    """The contract's eight fields plus the integrity verdict (G13R-02): any difference
    is another key, so a managed install judged INVALID now is never covered by its
    earlier MATCH confirmation."""

    library_instance: str
    execution_generation: str
    root_identity: RootIdentity
    kind: str
    loader_contract: str
    artifact_digest: str
    terms_digest: str
    source_kind: str
    integrity: str = MATCH


def eligible(snapshot: ModelSourceSnapshot) -> bool:
    """Whether a confirmation may be recorded at all (role and source rules, G13 §3)."""
    if snapshot.integrity == INVALID:
        return False  # never re-labelled as a manual success
    if snapshot.kind == DIARIZATION:
        # Strict: the user's pinned manifest, both models and both license texts.
        return snapshot.integrity == MATCH and snapshot.license_state == DECLARED
    if snapshot.source_kind == MANAGED:
        # A managed run needs an external reference match and declared license metadata.
        return snapshot.integrity == MATCH and snapshot.license_state != NOT_PROVIDED
    return snapshot.integrity == SELF_DIGEST  # manual Whisper: responsibility exception


@dataclass(frozen=True)
class ModelUseEvidence:
    """Issued by the run's registry after an explicit Yes; never by the model folder."""

    record_id: str
    key: ConfirmationKey
    snapshot: ModelSourceSnapshot
    issuer: ConfirmationRegistry = field(compare=False, repr=False)

    def valid(self) -> bool:
        return self.issuer.valid(self)


class ConfirmationRegistry:
    """The current run's confirmations, in memory only (restart/restore asks again)."""

    def __init__(self, library_instance: str | None = None) -> None:
        self.library_instance = library_instance or uuid.uuid4().hex
        self.generation = uuid.uuid4().hex
        self._records: dict[ConfirmationKey, ModelUseEvidence] = {}
        self._lock = threading.Lock()

    def key(self, snapshot: ModelSourceSnapshot) -> ConfirmationKey:
        return ConfirmationKey(
            self.library_instance,
            self.generation,
            snapshot.root_identity,
            snapshot.kind,
            snapshot.loader,
            snapshot.artifact_digest,
            snapshot.terms_digest,
            snapshot.source_kind,
            snapshot.integrity,
        )

    def __len__(self) -> int:
        """How many confirmations this run holds (display and tests; never persisted)."""
        with self._lock:
            return len(self._records)

    def new_generation(self) -> None:
        """A new run, a restore or an import: no earlier confirmation carries over."""
        with self._lock:
            self.generation = uuid.uuid4().hex
            self._records.clear()

    def confirm(
        self,
        snapshot: ModelSourceSnapshot,
        *,
        shown: ConfirmationKey,
        accepted: bool,
        acknowledged: bool,
    ) -> ModelUseEvidence | None:
        """Record exactly the snapshot the dialog showed; No/Esc/unchecked records nothing."""
        if accepted is not True or acknowledged is not True or not eligible(snapshot):
            return None
        with self._lock:
            key = self.key(snapshot)
            if shown != key:
                return None  # a stale dialog: another root, digest, terms or run
            evidence = ModelUseEvidence(uuid.uuid4().hex, key, snapshot, self)
            self._records[key] = evidence
            return evidence

    def evidence(self, snapshot: ModelSourceSnapshot) -> ModelUseEvidence | None:
        with self._lock:
            return self._records.get(self.key(snapshot))

    def valid(self, evidence: object) -> bool:
        if not isinstance(evidence, ModelUseEvidence) or evidence.issuer is not self:
            return False
        with self._lock:
            current = self._records.get(evidence.key)
            return (
                current is not None
                and current.record_id == evidence.record_id
                and evidence.key == self.key(evidence.snapshot)
            )

    def changed(self, snapshot: ModelSourceSnapshot) -> bool:
        """A confirmation exists for this root and role, but for other bytes or terms."""
        with self._lock:
            return any(
                key.root_identity == snapshot.root_identity
                and key.kind == snapshot.kind
                and (key.artifact_digest, key.terms_digest, key.source_kind, key.integrity)
                != (
                    snapshot.artifact_digest,
                    snapshot.terms_digest,
                    snapshot.source_kind,
                    snapshot.integrity,
                )
                for key in self._records
            )

    def display(self, snapshot: ModelSourceSnapshot) -> str:
        if snapshot.integrity == INVALID:
            return CHANGED_INVALID
        if self.evidence(snapshot) is None and self.changed(snapshot):
            return CHANGED_INVALID  # confirmed before, but for other bytes or terms
        if self.evidence(snapshot) is not None:
            # A reference match (managed spec or the user's pinned diarization manifest)
            # is shown as such; a manual Whisper digest is the user's own confirmation.
            return MANAGED_PIN_MATCH if snapshot.integrity == MATCH else MANUAL_USER_CONFIRMED
        if snapshot.kind == WHISPER and snapshot.source_kind == MANUAL:
            return LICENSE_UNCONFIRMED if snapshot.license_state != DECLARED else UNCONFIRMED
        return UNCONFIRMED
