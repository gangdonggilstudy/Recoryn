"""Recovery read model for display: plain data, no Qt and no storage writes.

The UI renders these lines into a read-only text field so keyboard and screen
reader users can read preserved ranges, missing or uncertain parts, candidates
and the next actions. Interrupted time is never presented as restored.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from recoryn.storage.chunks import ChunkDescriptor

PRESERVED, MISSING, CANDIDATE, UNKNOWN, INFO = (
    "PRESERVED",
    "MISSING",
    "CANDIDATE",
    "UNKNOWN",
    "INFO",
)

UNFINISHED_STATES = frozenset({"CREATED", "RECORDING", "PAUSED", "FINALIZING", "INTERRUPTED"})

_WARNINGS: dict[str, tuple[str, str]] = {
    "INVALID_BUNDLE": (MISSING, "손상되어 원본에 넣지 않은 저장 묶음이 있습니다(제자리에 보존)"),
    "INVALID_STAGING": (MISSING, "검증할 수 없는 임시 저장 항목이 있습니다(제자리에 보존)"),
    "STAGING_TAIL_NOT_ADOPTED": (
        MISSING,
        "임시 저장 끝부분 일부는 검증되지 않아 원본에 넣지 않았습니다",
    ),
    "MISSING_OR_INVALID_CATALOG_MEDIA": (
        MISSING,
        "목록에는 있지만 파일이 없거나 손상된 청크가 있습니다",
    ),
    "FINALIZED_ORPHAN": (CANDIDATE, "확정 목록 밖의 저장 묶음을 후보로 보존했습니다"),
    "FINALIZED_STAGING": (CANDIDATE, "확정 뒤 남은 임시 저장 항목을 보존했습니다"),
    "MANIFEST_SYNC_PENDING": (INFO, "manifest 동기화가 대기 중입니다(미디어 검증 결과는 별도)"),
    "DELETION_INTENT": (INFO, "삭제 요청이 있는 세션입니다"),
}

_DETAIL_LABELS: dict[str, tuple[str, str]] = {
    "ADOPTED": (PRESERVED, "목록 밖의 검증된 저장 묶음을 원본에 넣었습니다"),
    "RECOVERED": (PRESERVED, "임시 저장의 검증된 부분을 새 청크로 복원했습니다"),
    "ALREADY_RECOVERED": (PRESERVED, "이미 복구된 임시 저장 항목입니다"),
    "TAIL_NOT_ADOPTED": (MISSING, "임시 저장 끝부분 일부는 검증되지 않아 원본에 넣지 않았습니다"),
    "INVALID": (MISSING, "검증할 수 없는 항목을 제자리에 보존했습니다"),
    "CANDIDATE_NOT_ADOPTED": (CANDIDATE, "확정 목록 밖에 후보로 보존했습니다"),
}

_STATE_LABELS = {
    "CREATED": "생성됨",
    "RECORDING": "녹음 중",
    "PAUSED": "일시정지",
    "FINALIZING": "확정 중",
    "FINALIZED": "확정됨",
    "INTERRUPTED": "중단됨",
    "DIRECTORY_ONLY": "폴더만 있음",
    "DELETE_PENDING": "삭제 대기",
}


def describe(code: str) -> tuple[str, str]:
    """Closed mapping from a recovery warning code to (category, Korean label)."""
    base, _, suffix = code.partition(":")
    if base in _WARNINGS:
        category, label = _WARNINGS[base]
        return category, f"{label} ({suffix})" if suffix else label
    return UNKNOWN, f"알 수 없는 복구 경고: {code}"


def next_actions(state: str, *, live: bool) -> tuple[str, ...]:
    """Closed table of what the user can do next for a listed session."""
    if live:
        return ("정지 후 가능",)
    if state in UNFINISHED_STATES:
        return ("복구 검토", "세션 확정", "세션 삭제")
    if state == "FINALIZED":
        return ("내보내기", "전사 요청", "세션 삭제")
    if state == "DIRECTORY_ONLY":
        return ("복구 검토", "세션 확정")
    if state == "DELETE_PENDING":
        return ("삭제 대기 재시도",)
    return ()


def state_label(state: str) -> str:
    return f"{_STATE_LABELS.get(state, '알 수 없음')}({state})"


def _known_epochs(health: Mapping[str, Any]) -> dict[tuple[str, str], int | None]:
    """Epochs with a durable health record and their dropped frame totals."""
    known: dict[tuple[str, str], int | None] = {}
    epochs = health.get("epochs") if isinstance(health, Mapping) else None
    if not isinstance(epochs, list):
        return known
    for entry in epochs:
        tracks = entry.get("tracks") if isinstance(entry, Mapping) else None
        if not isinstance(tracks, Mapping):
            continue
        for track, value in tracks.items():
            if not isinstance(value, Mapping) or not isinstance(value.get("epoch_id"), str):
                continue
            dropped = value.get("dropped_frames")
            dropped = dropped if type(dropped) is int and dropped >= 0 else None
            if value.get("legacy_prefix_known") is False:
                dropped = None
            key = (str(track), value["epoch_id"])
            known[key] = dropped if key not in known or known[key] == dropped else None
    return known


@dataclass(frozen=True)
class EpochRange:
    track_id: str
    epoch_id: str
    chunk_count: int
    frames: int
    seconds: float
    dropped_frames: int | None  # None: no durable health record (loss is unknown)


@dataclass(frozen=True)
class RecoveryView:
    session_id: str
    previous_state: str
    state: str
    adopted: int
    recovered: int
    quarantined: int
    preserved: tuple[EpochRange, ...]
    catalog: tuple[EpochRange, ...]
    missing: tuple[str, ...]
    candidates: tuple[str, ...]
    notes: tuple[str, ...]
    actions: tuple[str, ...] = field(default=())

    def lines(self) -> list[str]:
        lines = [
            f"세션: {self.session_id}",
            f"상태: {state_label(self.previous_state)} → {state_label(self.state)}",
            f"목록상 예상 원본: 청크 {sum(item.chunk_count for item in self.catalog)}개 · "
            f"{sum(item.frames for item in self.catalog)}프레임 (파일 검증과 별도)",
            "보존된 원본:",
            "복구 검사 시점에 검증된 청크만 포함합니다.",
        ]
        if self.preserved:
            for item in self.preserved:
                loss = (
                    "유실 누계 알 수 없음(비정상 종료된 구간)"
                    if item.dropped_frames is None
                    else f"큐 유실 {item.dropped_frames}프레임"
                )
                lines.append(
                    f" - {item.track_id} · epoch {item.epoch_id[:8]} · 청크 {item.chunk_count}개 · "
                    f"{item.seconds:.2f}초 · {loss}"
                )
        else:
            lines.append(" - 확인된 청크 없음")
        lines.append(
            f"이번 복구: 채택 {self.adopted} · 임시 저장에서 복원 {self.recovered} · "
            f"격리 {self.quarantined}"
        )
        lines.append("누락·불확실:")
        lines.extend(f" - {text}" for text in self.missing or ("없음",))
        lines.append("후보(확정 목록 밖):")
        lines.extend(f" - {text}" for text in self.candidates or ("없음",))
        lines.extend(f"참고: {text}" for text in self.notes)
        lines.append("다음 행동: " + (" / ".join(self.actions) if self.actions else "없음"))
        lines.append("중단·누락 구간은 복원되지 않습니다.")
        return lines


def recovery_view(
    result: Mapping[str, Any],
    chunks: Sequence[ChunkDescriptor],
    health: Mapping[str, Any],
    *,
    live: bool = False,
) -> RecoveryView:
    """Combine a recover_session result, the catalog and capture health."""
    known = _known_epochs(health)
    ids = result.get("verified_chunk_ids")
    if isinstance(ids, (list, tuple)) and all(isinstance(i, str) for i in ids):
        has_verification, verified_ids = True, set(ids)
    else:
        has_verification, verified_ids = False, set()

    def ranges(items: Sequence[ChunkDescriptor]) -> tuple[EpochRange, ...]:
        grouped: dict[tuple[str, str], list[ChunkDescriptor]] = {}
        for chunk in items:
            grouped.setdefault((chunk.track_id, chunk.epoch_id), []).append(chunk)
        return tuple(
            EpochRange(
                track,
                epoch,
                len(group),
                sum(item.frame_count for item in group),
                sum(item.frame_count / item.format.sample_rate for item in group),
                known.get((track, epoch)),
            )
            for (track, epoch), group in grouped.items()
        )

    catalog = ranges(chunks)
    preserved = ranges([chunk for chunk in chunks if chunk.chunk_id in verified_ids])
    missing: list[str] = []
    candidates: list[str] = []
    notes: list[str] = []
    health_result = result.get("health_recovery")
    if isinstance(health_result, Mapping) and health_result.get("status") == "DEFERRED":
        notes.append("건강 판정 보류 · " + str(health_result.get("code", "HEALTH_UNREADABLE")))
    if health.get("has_unknown"):
        notes.append(
            "확인된 큐 유실 prefix 이후 미상(UNKNOWN_TAIL 또는 장치 미상 구간); 미상은 0이 아닙니다."
        )
    if not has_verification:
        notes.append("복구 미디어 검증 정보가 없어 보존량을 확인하지 못했습니다.")
    details = result.get("details") or []
    for detail in details:
        if not isinstance(detail, Mapping):
            continue
        category, label = _DETAIL_LABELS.get(
            str(detail.get("status")), (UNKNOWN, f"알 수 없는 항목 상태: {detail.get('status')}")
        )
        source = detail.get("source") or "이름 확인 불가"
        text = f"{label} [{detail.get('kind')} {source}]"
        tail = detail.get("tail_bytes")
        if type(tail) is int and tail > 0:
            text += f" · 넣지 않은 끝부분 {tail}바이트"
        if category == MISSING:
            missing.append(text)
        elif category == CANDIDATE:
            candidates.append(text)
        elif category == UNKNOWN or detail.get("status") == "ALREADY_RECOVERED":
            # Kept staging that is already in the original list is not a new loss.
            notes.append(text)
    covered = {"INVALID_BUNDLE", "INVALID_STAGING", "STAGING_TAIL_NOT_ADOPTED"}
    covered |= {"FINALIZED_ORPHAN", "FINALIZED_STAGING"}
    for code in _unique(result.get("warnings") or []):
        base = str(code).partition(":")[0]
        if details and base in covered:
            continue  # The per-item detail above already says it more precisely.
        category, label = describe(str(code))
        (missing if category == MISSING else candidates if category == CANDIDATE else notes).append(
            label
        )
    state = str(result.get("state", ""))
    return RecoveryView(
        session_id=str(result.get("session_id", "")),
        previous_state=str(result.get("previous_state", state)),
        state=state,
        adopted=int(result.get("adopted", 0)),
        recovered=int(result.get("recovered", 0)),
        quarantined=int(result.get("quarantined", 0)),
        preserved=preserved,
        catalog=catalog,
        missing=tuple(missing),
        candidates=tuple(candidates),
        notes=tuple(notes),
        actions=next_actions(state, live=live),
    )


def finalize_lines(
    result: Mapping[str, Any], chunks: Sequence[ChunkDescriptor], health: Mapping[str, Any]
) -> list[str]:
    """Lines for a finalize_unfinished result, followed by its recovery review."""
    head = [
        "이미 확정됨 · 건강 판정 보류 · 기존 확정 상태와 원본을 유지합니다."
        if result.get("already_finalized") and result.get("finalized") is False
        else "건강 판정 보류 · 확정하지 않았습니다. 원본을 보존합니다."
        if result.get("finalized") is False
        else "이미 확정된 세션입니다. 상태와 확정 목록은 바뀌지 않았습니다."
        if result.get("already_finalized")
        else "세션을 확정했습니다. 이 세션에는 더 녹음할 수 없습니다.",
        f"확정 목록: 청크 {result.get('chunk_count', 0)}개 · {result.get('frame_count', 0)}프레임",
    ]
    if result.get("manifest_sync_pending"):
        head.append("manifest 동기화가 대기 중입니다(원본 확정은 완료).")
    recovery = dict(result.get("recovery") or {})
    recovery["state"] = result.get("state", "FINALIZED")
    recovery["previous_state"] = result.get("previous_state", recovery.get("previous_state", ""))
    return head + recovery_view(recovery, chunks, health).lines()


def directory_only_lines(entry: Mapping[str, Any]) -> list[str]:
    return [
        f"세션: {entry.get('session_id', '')}",
        "상태: 폴더만 있음(DIRECTORY_ONLY) · 목록 DB에 행이 없습니다",
        f"임시 저장 항목 {entry.get('staging_entries', 0)}개 · "
        f"목록 밖 저장 묶음 {entry.get('uncatalogued_bundles', 0)}개(검증 전)",
        "‘복구 검토’를 하면 검증된 원본을 목록에 넣습니다. 삭제는 복구 뒤에 할 수 있습니다.",
        "다음 행동: " + " / ".join(next_actions("DIRECTORY_ONLY", live=False)),
    ]


def unfinished_notice(
    items: Iterable[Mapping[str, Any]], skipped: int, *, current: str | None
) -> str:
    """Startup detection text; never counts a live or currently recorded session."""
    items = list(items)
    unsafe = sum(1 for item in items if item.get("inspection_error"))
    count = sum(
        1
        for item in items
        if not item.get("live")
        and item.get("session_id") != current
        and not item.get("inspection_error")
    )
    parts: list[str] = []
    if count:
        parts.append(
            f"이전 실행에서 확정되지 않은 세션 {count}건이 있습니다. 목록에서 선택해 "
            "‘복구 검토’ 또는 ‘세션 확정’을 고르세요. 자동으로 바꾸지 않습니다."
        )
    if skipped:
        parts.append(f"세션으로 인식할 수 없는 폴더 {skipped}개는 목록에 넣지 않았습니다.")
    if unsafe:
        parts.append(
            f"검사할 수 없는 세션 {unsafe}건은 복구·확정을 보류합니다. 해당 세션을 선택해 링크·하드 링크 또는 접근 권한을 확인한 뒤 새로고침하세요."
        )
    return " ".join(parts)


def _unique(values: Iterable[Any]) -> list[Any]:
    seen: list[Any] = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return seen
