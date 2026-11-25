"""Content values contain no device, database or model dependencies."""

from __future__ import annotations

from dataclasses import dataclass

from recoryn.domain import ValidationError


def text_value(value: object, *, maximum: int = 1_000_000, empty: bool = True) -> str:
    if not isinstance(value, str) or len(value) > maximum or "\x00" in value:
        raise ValidationError("INVALID_CONTENT_TEXT")
    if not empty and not value.strip():
        raise ValidationError("EMPTY_CONTENT_IDENTIFIER")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise ValidationError("INVALID_CONTENT_ENCODING") from exc
    return value


def identifier(value: object) -> str:
    return text_value(value, maximum=128, empty=False)


def milliseconds(value: object) -> int:
    if type(value) is not int or not 0 <= value < 2**63:
        raise ValidationError("INVALID_CONTENT_TIME")
    return value


@dataclass(frozen=True, slots=True)
class Segment:
    segment_id: str
    start_ms: int
    end_ms: int
    text: str
    speaker: str | None = None
    provenance: str = "audio"
    track_id: str | None = None
    timing_quality: str = "model"

    def __post_init__(self) -> None:
        identifier(self.segment_id)
        milliseconds(self.start_ms)
        milliseconds(self.end_ms)
        if self.end_ms < self.start_ms:
            raise ValidationError("INVALID_SEGMENT_INTERVAL")
        text_value(self.text)
        if self.speaker is not None:
            text_value(self.speaker, maximum=256, empty=False)
        if self.provenance not in ("audio", "user_assertion", "unresolved"):
            raise ValidationError("INVALID_SEGMENT_PROVENANCE")
        if self.track_id is not None:
            identifier(self.track_id)
        if self.timing_quality not in ("model", "clip", "unverified"):
            raise ValidationError("INVALID_SEGMENT_TIMING_QUALITY")


PROVIDER_BASES = ("transcript", "user_assertion", "model_inference")


@dataclass(frozen=True, slots=True)
class Claim:
    """One automatic summary claim.

    ``provider_basis`` keeps the adapter's normalized basis as a reference only: None
    means "not recorded", never "transcript". The stored canonical basis is always
    recomputed from the referenced source provenance (G12 section 3.1).
    """

    text: str
    segment_ids: tuple[str, ...]
    status: str = "uncertain"
    provider_basis: str | None = None

    def __post_init__(self) -> None:
        if self.provider_basis is not None and (
            type(self.provider_basis) is not str or self.provider_basis not in PROVIDER_BASES
        ):
            raise ValidationError("INVALID_CLAIM_PROVIDER_BASIS")
        text_value(self.text, empty=False)
        if type(self.segment_ids) is not tuple or len(self.segment_ids) > 100_000:
            raise ValidationError("INVALID_CLAIM_REFERENCES")
        for segment_id in self.segment_ids:
            identifier(segment_id)
        if len(set(self.segment_ids)) != len(self.segment_ids):
            raise ValidationError("DUPLICATE_CLAIM_REFERENCE")
        if self.status not in (
            "uncertain",
            "unreviewed",
            "unsupported",
            "disputed",
            "user_assertion",
            "model_inference",
        ):
            # An AI DTO cannot confer human-verified support on its own output.
            raise ValidationError("INVALID_AUTOMATIC_CLAIM_STATUS")
