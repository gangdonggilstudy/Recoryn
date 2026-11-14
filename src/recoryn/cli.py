"""An offline CLI for the P0.1 synthetic recording core."""

from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import stat
import time
import wave
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from recoryn import __version__


def _default_root() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    return Path(base) / "Recoryn" if base else Path.home() / ".local" / "share" / "recoryn"


def _duration(value: str) -> float:
    seconds = float(value)
    if not math.isfinite(seconds) or not 0 < seconds <= 86400:
        raise argparse.ArgumentTypeError("seconds must be finite and within (0, 86400]")
    return seconds


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="recoryn",
        description="P0.1 offline recording core. simulate generates audio; no devices are opened.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--root", type=Path, default=_default_root(), help="local library directory"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    simulate = commands.add_parser("simulate", help="record two deterministic synthetic tracks")
    simulate.add_argument("--seconds", type=_duration, default=1.0)
    commands.add_parser("list", help="list stored sessions")
    for name in ("inspect", "recover", "export", "delete"):
        command = commands.add_parser(name)
        command.add_argument("session_id")
        if name == "export":
            command.add_argument("--output", type=Path, required=True, help="new local directory")
    return parser


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False))


def _simulate(library: Any, seconds: float) -> dict[str, Any]:
    from recoryn.app import RecordingService
    from recoryn.capture import SyntheticSource
    from recoryn.domain import AudioFormat

    formats = {"mic": AudioFormat(44100, 1), "system": AudioFormat(48000, 2)}
    service = RecordingService(library, formats)
    try:
        service.start()
        sources = {
            track: iter(
                SyntheticSource(
                    service.session_id,
                    track,
                    service.epochs[track],
                    format,
                    max(1, int(seconds * format.sample_rate)),
                    block_frames=format.sample_rate // 100,
                )
            )
            for track, format in formats.items()
        }
        while sources:
            for track in list(sources):
                try:
                    service.submit(next(sources[track]))
                except StopIteration:
                    del sources[track]
            if sources:
                time.sleep(0.01)
        result = service.stop()
        return {"session_id": service.session_id, "input": "synthetic", **result}
    finally:
        # A timed-out writer still owns storage; do not release its Library lock.
        service.join_writer()


def _output_directory(path: Path, library_root: Path) -> Path:
    if str(path).startswith(("\\\\", "//")):
        raise ValueError("Network export paths are not supported")
    absolute = path.absolute()
    for ancestor in (absolute, *absolute.parents):
        try:
            metadata = ancestor.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode) or (
            getattr(metadata, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise ValueError("Linked export paths are not supported")
    resolved = absolute.resolve()
    if resolved.is_relative_to(library_root.resolve()):
        raise ValueError("Exports must be outside the source library")
    resolved.mkdir(parents=True, exist_ok=False)
    return resolved


def _export(library: Any, session_id: str, output: Path) -> dict[str, Any]:
    from recoryn.domain import SessionState
    from recoryn.storage import verify_bundle

    session = library.get_session(session_id)
    if session.state != SessionState.FINALIZED:
        raise ValueError("Only finalized sessions can be exported")
    # Finish a pending DB projection before declaring a complete project export.
    library.write_manifest(session_id)
    chunks = library.chunks(session_id)
    grouped: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for chunk in chunks:
        verified = verify_bundle(library.root / chunk.relative_path)
        if verified.sha256 != chunk.sha256:
            raise ValueError("Source bundle does not match the catalog")
        if chunk.format.sample_type not in {"s16le", "s24le", "s32le"}:
            raise ValueError("This increment exports integer PCM WAV only")
        grouped[(chunk.track_id, chunk.epoch_id)].append(chunk)
    destination = _output_directory(output, library.root)
    files: list[dict[str, Any]] = []
    for (track, epoch), group in sorted(grouped.items()):
        # Epochs remain separate: pause and device gaps are never silently compressed.
        format = group[0].format
        if any(item.format != format for item in group):
            raise ValueError("An epoch cannot mix PCM formats")
        if sum(item.byte_count for item in group) > 0xFFFFFFFF - 36:
            raise ValueError("WAV size limit exceeded; split export is required")
        files.extend(_export_contiguous_runs(library, destination, track, epoch, group))
    manifest = {
        "schema_version": 1,
        "session_id": session_id,
        "files": files,
        "capture_health": library.capture_health(session_id),
    }
    # The index is the completion marker; partial outputs without it are not complete.
    with (destination / "export.json").open("x", encoding="utf-8") as index_stream:
        json.dump(manifest, index_stream, ensure_ascii=False, sort_keys=True, allow_nan=False)
        index_stream.flush()
        os.fsync(index_stream.fileno())
    return {"session_id": session_id, "files": files, "complete": True}


def _export_contiguous_runs(
    library: Any, destination: Path, track: str, epoch: str, group: list[Any]
) -> list[dict[str, Any]]:
    """Split at source discontinuities; never compress a gap into continuous WAV."""
    from contextlib import ExitStack

    format = group[0].format
    files: list[dict[str, Any]] = []
    previous: dict[str, Any] | None = None
    entry: dict[str, Any] | None = None
    audio: wave.Wave_write | None = None
    with ExitStack() as stack:
        for chunk in group:
            bundle = library.root / chunk.relative_path
            with (
                (bundle / "blocks.jsonl").open("r", encoding="utf-8") as journal,
                (bundle / "audio.pcm").open("rb") as pcm,
            ):
                for line in journal:
                    record = json.loads(line)
                    metadata = record["metadata"]
                    reason: str | None = None
                    if previous is not None:
                        contiguous = (
                            metadata["sequence"] == previous["sequence"]
                            and metadata["fragment_index"] == previous["fragment_index"] + 1
                        ) or (
                            metadata["sequence"] == previous["sequence"] + 1
                            and metadata["fragment_index"] == 0
                            and previous["fragment_index"] + 1 == previous["fragment_count"]
                        )
                        if not contiguous:
                            reason = "SEQUENCE_GAP"
                        old_position = previous.get("device_frame_position")
                        position = metadata.get("device_frame_position")
                        if (
                            old_position is not None
                            and position is not None
                            and position != old_position + previous["frame_count"]
                        ):
                            reason = "DEVICE_POSITION_GAP"
                        if set(metadata.get("flags", [])) & {
                            "DATA_DISCONTINUITY",
                            "BACKEND_DISCONTINUITY",
                            "TIMESTAMP_ERROR",
                        }:
                            reason = "BACKEND_DISCONTINUITY"
                    if audio is None or reason is not None:
                        stack.close()
                        filename = f"{track}-{epoch}"
                        if files:
                            filename += f"-part{len(files) + 1:04d}"
                        filename += ".wav"
                        stream = stack.enter_context((destination / filename).open("xb"))
                        audio = stack.enter_context(wave.open(stream, "wb"))
                        audio.setnchannels(format.channels)
                        audio.setsampwidth(format.frame_bytes // format.channels)
                        audio.setframerate(format.sample_rate)
                        entry = {
                            "file": filename,
                            "track_id": track,
                            "epoch_id": epoch,
                            "frame_count": 0,
                            "source_chunks": [],
                            "source_ranges": [],
                            "gap_before": reason,
                        }
                        files.append(entry)
                    assert entry is not None
                    pcm.seek(record["offset"])
                    payload = pcm.read(record["length"])
                    if len(payload) != record["length"]:
                        raise ValueError("Source media changed during export")
                    audio.writeframesraw(payload)
                    entry["source_ranges"].append(
                        {
                            "chunk_id": chunk.chunk_id,
                            "sequence": metadata["sequence"],
                            "fragment_index": metadata["fragment_index"],
                            "source_chunk_frame_start": record["offset"] // format.frame_bytes,
                            "output_frame_start": entry["frame_count"],
                            "frame_count": metadata["frame_count"],
                            "capture_mono_ns": metadata["capture_mono_ns"],
                            "device_frame_position": metadata.get("device_frame_position"),
                        }
                    )
                    entry["frame_count"] += metadata["frame_count"]
                    if chunk.chunk_id not in entry["source_chunks"]:
                        entry["source_chunks"].append(chunk.chunk_id)
                    previous = metadata
    return files


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    # Help/version return before optional runtime modules or storage initialization.
    from recoryn.storage import Library

    try:
        with Library(args.root) as library:
            if args.command == "simulate":
                result: object = _simulate(library, args.seconds)
            elif args.command == "list":
                result = [
                    {"session_id": item.session_id, "state": item.state.value}
                    for item in library.list_sessions()
                ]
            elif args.command == "inspect":
                session = library.get_session(args.session_id)
                result = {
                    "session_id": session.session_id,
                    "state": session.state.value,
                    "state_version": session.state_version,
                    "chunks": [item.to_dict() for item in library.chunks(session.session_id)],
                    "capture_health": library.capture_health(session.session_id),
                }
            elif args.command == "recover":
                result = library.recover_session(args.session_id)
            elif args.command == "delete":
                result = library.delete_session(args.session_id)
            else:
                result = _export(library, args.session_id, args.output)
        _print(result)
        return 0
    except KeyboardInterrupt:
        _print({"error": "INTERRUPTED", "recovery_available": True})
        return 130
    except (ValueError, RuntimeError, OSError, sqlite3.Error, KeyError) as error:
        # Do not persist/print exception repr: SDKs and paths may contain private data.
        _print({"error": type(error).__name__, "message": "Operation failed; media preserved"})
        return 1
