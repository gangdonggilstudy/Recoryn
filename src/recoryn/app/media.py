"""Bounded derived WAV clips with fixed source ranges and honest clock quality."""

from __future__ import annotations

import hashlib
import json
import math
import struct
import uuid
import wave
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from recoryn.audio import FrameRegion, energy_vad
from recoryn.domain import AudioFormat, PCMBlock, ValidationError
from recoryn.storage import Library
from recoryn.storage._coordination import root_mutex
from recoryn.storage._safe import atomic_json, mkdir, open_file, safe_path
from recoryn.storage.chunks import ChunkDescriptor, scan_prefix, verify_bundle


@dataclass(frozen=True)
class AudioClip:
    path: Path
    track_id: str
    epoch_id: str
    offset_ms: int | None
    duration_ms: int
    timing_quality: str
    source_ranges: tuple[dict[str, Any], ...]
    sha256: str = ""


def _correlated(metadata: dict[str, Any]) -> bool:
    return (
        metadata["capture_mono_ns"] is not None
        and metadata["clock_quality"] in {"DEVICE_CORRELATED", "SYNTHETIC"}
        and "TIMESTAMP_ERROR" not in metadata["flags"]
    )


def _clock_step(previous: dict[str, Any], current: dict[str, Any], rate: int) -> bool:
    """Conservative 1%/1us rejection policy, matching audio alignment gates.

    This is not a measured hardware tolerance. A clock discontinuity must not
    compress a host-clock gap into apparently continuous, precise STT input.
    """
    if not _correlated(previous) or not _correlated(current):
        return False
    elapsed = current["capture_mono_ns"] - previous["capture_mono_ns"]
    nominal = previous["frame_count"] * 1_000_000_000 // rate
    return bool(elapsed > 0 and abs(elapsed - nominal) <= max(1000, nominal // 100))


def _int16(payload: bytes, format: AudioFormat) -> bytes:
    if format.sample_type == "s16le":
        return payload
    width = format.frame_bytes // format.channels
    output = bytearray(len(payload) // width * 2)
    for index, offset in enumerate(range(0, len(payload), width)):
        if format.sample_type == "f32le":
            value = struct.unpack_from("<f", payload, offset)[0]
            if not math.isfinite(value):
                raise ValidationError("DERIVED_AUDIO_NONFINITE")
            integer = round(max(-1.0, min(1.0, value)) * 32767)
        else:
            integer = int.from_bytes(payload[offset : offset + width], "little", signed=True)
            integer >>= width * 8 - 16
        struct.pack_into("<h", output, index * 2, integer)
    return bytes(output)


def prepare_clips(
    library: Library,
    session_id: str,
    *,
    max_seconds: int = 30,
    chunk_ids: frozenset[str] | None = None,
    origin_ns: int | None = None,
    speech_only: bool = False,
) -> tuple[str, tuple[AudioClip, ...]]:
    """Derive from a fixed sealed-chunk snapshot; never inspect a growing WAV.

    All existing gaps split clips. Unknown source timestamps stay unknown; the
    caller must not publish their relative offsets as precise session times.
    Outputs live below the session so deletion also removes derived audio.
    """
    if type(max_seconds) is not int or not 1 <= max_seconds <= 60:
        raise ValidationError("DERIVED_AUDIO_DURATION")
    if type(speech_only) is not bool:
        raise ValidationError("DERIVED_AUDIO_VAD")
    with root_mutex(library.root):
        library.get_session(session_id)
        chunks = library.chunks(session_id)
    if chunk_ids is not None:
        chunks = [item for item in chunks if item.chunk_id in chunk_ids]
    snapshot = hashlib.sha256(
        json.dumps(
            [item.to_dict() for item in chunks], sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    output = safe_path(library.root, "sessions", session_id, "derived", "audio-" + uuid.uuid4().hex)
    with root_mutex(library.root):
        # Public get_session() checks deletion intent; never recreate a deleted tree.
        library.get_session(session_id)
        mkdir(output)
    grouped: dict[tuple[str, str], list[ChunkDescriptor]] = defaultdict(list)
    origin: int | None = origin_ns
    for chunk in chunks:
        grouped[chunk.track_id, chunk.epoch_id].append(chunk)
        bundle = safe_path(library.root, chunk.relative_path)
        if verify_bundle(bundle) != chunk:
            raise ValidationError("DERIVED_SOURCE_CATALOG_MISMATCH")
        records = scan_prefix(bundle, strict=True).blocks
        for record in records:
            metadata = record["metadata"]
            stamp = metadata["capture_mono_ns"]
            if _correlated(metadata):
                if origin_ns is None:
                    origin = stamp if origin is None else min(origin, stamp)
    clips: list[AudioClip] = []
    for (track, epoch), track_chunks in grouped.items():
        pcm = bytearray()
        ranges: list[dict[str, Any]] = []
        first_stamp: int | None = None
        previous: dict[str, Any] | None = None
        current_format: AudioFormat | None = None
        frames = 0
        clock_uncertain = False

        def flush(format: AudioFormat | None, track_id: str, epoch_id: str) -> None:
            nonlocal pcm, ranges, frames, first_stamp
            if not ranges or format is None:
                return
            regions: tuple[FrameRegion, ...] = (FrameRegion(0, frames),)
            if speech_only:
                regions = energy_vad(
                    PCMBlock(
                        session_id,
                        track_id,
                        epoch_id,
                        0,
                        AudioFormat(format.sample_rate, format.channels),
                        frames,
                        bytes(pcm),
                        first_stamp,
                        first_stamp or 0,
                    ),
                    min_speech_ms=0,
                )
            for region in regions:
                path = safe_path(output, f"clip-{len(clips):06d}.wav")
                width = format.channels * 2
                with open_file(path, "xb") as stream, wave.open(stream, "wb") as audio:
                    audio.setnchannels(format.channels)
                    audio.setsampwidth(2)
                    audio.setframerate(format.sample_rate)
                    audio.writeframes(
                        bytes(pcm[region.start_frame * width : region.end_frame * width])
                    )
                selected = []
                for source in ranges:
                    start = max(region.start_frame, source["output_frame_start"])
                    end = min(
                        region.end_frame, source["output_frame_start"] + source["frame_count"]
                    )
                    if start >= end:
                        continue
                    delta = start - source["output_frame_start"]
                    stamp = source["capture_mono_ns"]
                    selected.append(
                        {
                            **source,
                            "source_chunk_frame_start": source["source_chunk_frame_start"] + delta,
                            "output_frame_start": start - region.start_frame,
                            "frame_count": end - start,
                            "capture_mono_ns": stamp + delta * 1_000_000_000 // format.sample_rate
                            if stamp is not None
                            else None,
                        }
                    )
                offset = (
                    (
                        first_stamp
                        + region.start_frame * 1_000_000_000 // format.sample_rate
                        - origin
                    )
                    // 1_000_000
                    if first_stamp is not None and origin is not None
                    else None
                )
                digest = hashlib.sha256()
                with open_file(path, "rb") as stream:
                    while part := stream.read(256 * 1024):
                        digest.update(part)
                clips.append(
                    AudioClip(
                        path,
                        track_id,
                        epoch_id,
                        offset,
                        ((region.end_frame - region.start_frame) * 1000 + format.sample_rate - 1)
                        // format.sample_rate,
                        "correlated" if offset is not None else "unknown",
                        tuple(selected),
                        digest.hexdigest(),
                    )
                )
            pcm, ranges, frames, first_stamp = bytearray(), [], 0, None

        for chunk in track_chunks:
            bundle = safe_path(library.root, chunk.relative_path)
            if verify_bundle(bundle) != chunk:
                raise ValidationError("DERIVED_SOURCE_CATALOG_MISMATCH")
            records = scan_prefix(bundle, strict=True).blocks
            with open_file(safe_path(bundle, "audio.pcm"), "rb") as stream:
                for record in records:
                    metadata = record["metadata"]
                    fmt = chunk.format
                    stamp = metadata["capture_mono_ns"]
                    jumped = (
                        previous is not None
                        and (
                            metadata["sequence"] == previous["sequence"] + 1
                            or metadata["sequence"] == previous["sequence"]
                            and metadata["fragment_index"] == previous["fragment_index"] + 1
                        )
                        and "DATA_DISCONTINUITY" not in metadata["flags"]
                        and _correlated(previous)
                        and _correlated(metadata)
                        and not _clock_step(previous, metadata, fmt.sample_rate)
                    )
                    # Once a correlated clock jumps within an epoch, do not
                    # silently restore precise source times on its next packet.
                    clock_uncertain = clock_uncertain or jumped
                    valid_stamp = _correlated(metadata) and not clock_uncertain
                    split = previous is not None and (
                        fmt != current_format
                        or metadata["sequence"] != previous["sequence"] + 1
                        and not (
                            metadata["sequence"] == previous["sequence"]
                            and metadata["fragment_index"] == previous["fragment_index"] + 1
                        )
                        or "DATA_DISCONTINUITY" in metadata["flags"]
                        or not valid_stamp
                        or previous["capture_mono_ns"] is None
                        or stamp < previous["capture_mono_ns"]
                        or metadata.get("device_frame_position") is not None
                        and previous.get("device_frame_position") is not None
                        and metadata["device_frame_position"]
                        != previous["device_frame_position"] + previous["frame_count"]
                    )
                    if ranges and split:
                        flush(current_format, track, epoch)
                    current_format = fmt
                    stream.seek(record["offset"])
                    payload = stream.read(record["length"])
                    if len(payload) != record["length"]:
                        raise ValidationError("DERIVED_SOURCE_CHANGED")
                    limit = min(
                        fmt.sample_rate * max_seconds,
                        (8 * 1024 * 1024 - 4096) // (fmt.channels * 2),
                    )
                    packet_offset = 0
                    while packet_offset < metadata["frame_count"]:
                        take = min(metadata["frame_count"] - packet_offset, limit - frames)
                        piece_stamp = (
                            stamp + packet_offset * 1_000_000_000 // fmt.sample_rate
                            if valid_stamp
                            else None
                        )
                        if not ranges:
                            first_stamp = piece_stamp
                        start = packet_offset * fmt.frame_bytes
                        pcm.extend(_int16(payload[start : start + take * fmt.frame_bytes], fmt))
                        ranges.append(
                            {
                                "chunk_id": chunk.chunk_id,
                                "sequence": metadata["sequence"],
                                "fragment_index": metadata["fragment_index"],
                                "source_chunk_frame_start": record["offset"] // fmt.frame_bytes
                                + packet_offset,
                                "output_frame_start": frames,
                                "frame_count": take,
                                "capture_mono_ns": piece_stamp,
                            }
                        )
                        frames += take
                        packet_offset += take
                        if frames == limit:
                            flush(current_format, track, epoch)
                    previous = metadata
                    if not valid_stamp:
                        flush(current_format, track, epoch)
        flush(current_format, track, epoch)
    atomic_json(
        safe_path(output, "clips.json"),
        {
            "schema_version": 1,
            "snapshot_sha256": snapshot,
            "clock_origin_ns": origin,
            "clips": [{**asdict(clip), "path": clip.path.name} for clip in clips],
        },
    )
    return snapshot, tuple(clips)
