"""Immutable PCM bundles with canonical checksummed JSONL recovery prefixes."""

from __future__ import annotations

import hashlib
import os
import threading
import uuid
import weakref
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

from recoryn.domain import AudioFormat, PCMBlock, ValidationError

from ._coordination import check_write_allowed, root_mutex
from ._safe import (
    MAX_BLOCK_BYTES,
    MAX_CHUNK_BYTES,
    MAX_JSON_BYTES,
    MAX_RECORDS,
    canonical,
    check_path,
    digest,
    identifier,
    integer,
    mkdir,
    open_file,
    read_json,
    root_path,
    safe_path,
    schema,
    sha256,
    strict_json,
    sync,
    write_all,
)

_writers: weakref.WeakSet[ChunkWriter] = weakref.WeakSet()
_writers_lock = threading.Lock()


def has_active_writer(root: Path, session_id: str) -> bool:
    with _writers_lock:
        return any(
            w.root == root and w.session_id == session_id and w._pcm is not None for w in _writers
        )


@dataclass(frozen=True)
class ChunkDescriptor:
    session_id: str
    track_id: str
    epoch_id: str
    chunk_id: str
    format: AudioFormat
    frame_count: int
    byte_count: int
    relative_path: str
    sha256: str
    first_sequence: int
    last_sequence: int
    block_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.format, AudioFormat):
            raise ValidationError("Descriptor format must be AudioFormat")
        for value in (self.session_id, self.track_id, self.epoch_id, self.chunk_id):
            identifier(value)
        integer(self.frame_count, minimum=1)
        integer(self.byte_count, minimum=1)
        integer(self.first_sequence)
        integer(self.last_sequence)
        integer(self.block_count, minimum=1)
        digest(self.sha256)
        expected = (
            f"sessions/{self.session_id}/tracks/{self.track_id}/{self.epoch_id}/{self.chunk_id}"
        )
        if self.relative_path != expected or self.last_sequence < self.first_sequence:
            raise ValidationError("Invalid descriptor identity/range")
        if self.byte_count != self.frame_count * self.format.frame_bytes:
            raise ValidationError("Descriptor frame size mismatch")
        if self.byte_count > MAX_CHUNK_BYTES or self.block_count > MAX_RECORDS:
            raise ValidationError("Descriptor size limit exceeded")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "session_id": self.session_id,
            "track_id": self.track_id,
            "epoch_id": self.epoch_id,
            "chunk_id": self.chunk_id,
            "format": self.format.to_dict(),
            "frame_count": self.frame_count,
            "byte_count": self.byte_count,
            "relative_path": self.relative_path,
            "sha256": self.sha256,
            "first_sequence": self.first_sequence,
            "last_sequence": self.last_sequence,
            "block_count": self.block_count,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ChunkDescriptor:
        schema(value)
        expected = {
            "schema_version",
            "session_id",
            "track_id",
            "epoch_id",
            "chunk_id",
            "format",
            "frame_count",
            "byte_count",
            "relative_path",
            "sha256",
            "first_sequence",
            "last_sequence",
            "block_count",
        }
        if set(value) != expected or not isinstance(value["format"], dict):
            raise ValidationError("Invalid descriptor fields")
        if not isinstance(value["relative_path"], str):
            raise ValidationError("Invalid descriptor path")
        return cls(
            identifier(value["session_id"]),
            identifier(value["track_id"]),
            identifier(value["epoch_id"]),
            identifier(value["chunk_id"]),
            AudioFormat.from_dict(value["format"]),
            integer(value["frame_count"], minimum=1),
            integer(value["byte_count"], minimum=1),
            value["relative_path"],
            digest(value["sha256"]),
            integer(value["first_sequence"]),
            integer(value["last_sequence"]),
            integer(value["block_count"], minimum=1),
        )


def _next(previous: PCMBlock | None, block: PCMBlock) -> None:
    if previous is None:
        if block.fragment_index != 0:
            raise ValidationError("Prefix must start at first fragment")
        return
    if (block.session_id, block.track_id, block.epoch_id, block.format) != (
        previous.session_id,
        previous.track_id,
        previous.epoch_id,
        previous.format,
    ):
        raise ValidationError("Mixed journal identity or format")
    if block.sequence == previous.sequence:
        if (
            block.fragment_count != previous.fragment_count
            or block.fragment_index != previous.fragment_index + 1
        ):
            raise ValidationError("Duplicate or discontinuous fragment")
    elif (
        block.sequence < previous.sequence
        or block.fragment_index != 0
        or previous.fragment_index + 1 != previous.fragment_count
    ):
        raise ValidationError("Invalid block sequence/fragment boundary")


@dataclass(frozen=True)
class JournalPrefix:
    blocks: tuple[dict[str, Any], ...]
    byte_count: int
    frame_count: int
    sha256: str
    complete: bool
    first_sequence: int
    last_sequence: int


def scan_prefix(path: Path, *, strict: bool = False) -> JournalPrefix:
    check_path(path)
    records: list[dict[str, Any]] = []
    byte_count = frame_count = 0
    previous: PCMBlock | None = None
    content_hash = hashlib.sha256()
    complete = True
    packet_count = packet_bytes = packet_frames = 0
    packet_hash = content_hash.copy()
    with (
        open_file(path / "audio.pcm", "rb") as pcm,
        open_file(path / "blocks.jsonl", "rb") as journal,
    ):
        while True:
            line = journal.readline(MAX_JSON_BYTES + 1)
            if not line:
                break
            try:
                if not line.endswith(b"\n") or len(records) >= MAX_RECORDS:
                    raise ValidationError("Torn or oversized journal")
                record = strict_json(line)
                if set(record) != {
                    "schema_version",
                    "metadata",
                    "offset",
                    "length",
                    "payload_sha256",
                    "record_sha256",
                }:
                    raise ValidationError("Invalid journal fields")
                schema(record)
                checksum = digest(record["record_sha256"])
                unhashed = {key: value for key, value in record.items() if key != "record_sha256"}
                if sha256(canonical(unhashed)) != checksum:
                    raise ValidationError("Journal checksum mismatch")
                offset, length = integer(record["offset"]), integer(record["length"], minimum=1)
                if (
                    offset != byte_count
                    or length > MAX_BLOCK_BYTES
                    or offset + length > MAX_CHUNK_BYTES
                ):
                    raise ValidationError("Invalid PCM range")
                payload = pcm.read(length)
                if len(payload) != length or sha256(payload) != digest(record["payload_sha256"]):
                    raise ValidationError("PCM checksum/length mismatch")
                if not isinstance(record["metadata"], dict):
                    raise ValidationError("Invalid block metadata")
                block = PCMBlock.from_metadata(record["metadata"], payload)
                if record["metadata"] != block.to_metadata():
                    raise ValidationError("Noncanonical block metadata")
                _next(previous, block)
                previous = block
                content_hash.update(payload)
                byte_count += length
                frame_count += block.frame_count
                records.append(record)
                if block.fragment_index + 1 == block.fragment_count:
                    packet_count, packet_bytes, packet_frames = (
                        len(records),
                        byte_count,
                        frame_count,
                    )
                    packet_hash = content_hash.copy()
            except (ValueError, KeyError, TypeError) as exc:
                if strict:
                    raise ValidationError("Invalid journal record") from exc
                complete = False
                break
        if os.fstat(pcm.fileno()).st_size != byte_count:
            complete = False
        if strict and not complete:
            raise ValidationError("Unjournaled PCM tail")
    if previous is not None and previous.fragment_index + 1 != previous.fragment_count:
        if strict:
            raise ValidationError("Incomplete final packet fragments")
        complete = False
        records = records[:packet_count]
        byte_count, frame_count, content_hash = packet_bytes, packet_frames, packet_hash
    if not records:
        raise ValidationError("No verified prefix")
    return JournalPrefix(
        tuple(records),
        byte_count,
        frame_count,
        content_hash.hexdigest(),
        complete,
        records[0]["metadata"]["sequence"],
        records[-1]["metadata"]["sequence"],
    )


def verify_bundle(path: Path) -> ChunkDescriptor:
    path = root_path(path)
    descriptor = ChunkDescriptor.from_dict(read_json(path / "descriptor.json"))
    prefix = scan_prefix(path, strict=True)
    if (
        prefix.byte_count,
        prefix.frame_count,
        prefix.sha256,
        len(prefix.blocks),
        prefix.first_sequence,
        prefix.last_sequence,
    ) != (
        descriptor.byte_count,
        descriptor.frame_count,
        descriptor.sha256,
        descriptor.block_count,
        descriptor.first_sequence,
        descriptor.last_sequence,
    ):
        raise ValidationError("Descriptor does not match journal")
    first = prefix.blocks[0]["metadata"]
    if (first["session_id"], first["track_id"], first["epoch_id"], first["format"]) != (
        descriptor.session_id,
        descriptor.track_id,
        descriptor.epoch_id,
        descriptor.format.to_dict(),
    ):
        raise ValidationError("Descriptor identity mismatch")
    # A copied descriptor cannot redirect registration to another bundle path.
    if tuple(path.parts[-6:]) != tuple(Path(descriptor.relative_path).parts):
        raise ValidationError("Bundle location does not match identity")
    return descriptor


class ChunkWriter:
    def __init__(self, root: Path, first_block: PCMBlock, chunk_id: str | None = None) -> None:
        self.root = root_path(root)
        self.session_id = identifier(first_block.session_id)
        self.track_id = identifier(first_block.track_id)
        self.epoch_id = identifier(first_block.epoch_id)
        self.chunk_id = identifier(chunk_id if chunk_id is not None else uuid.uuid4().hex)
        self.format = first_block.format
        self.relative_path = (
            f"sessions/{self.session_id}/tracks/{self.track_id}/{self.epoch_id}/{self.chunk_id}"
        )
        self.staging_path = safe_path(
            self.root, f"sessions/{self.session_id}/staging/{self.chunk_id}"
        )
        self.path = safe_path(self.root, self.relative_path)
        self._pcm: BinaryIO | None = None
        self._journal: BinaryIO | None = None
        self._previous: PCMBlock | None = None
        self._frames = self._bytes = self._count = 0
        self._first_sequence = first_block.sequence
        self._hash = hashlib.sha256()
        self._closed = False
        self._failed = False

    def _open(self) -> None:
        check_write_allowed(self.root, self.session_id)
        if self.path.exists() or self.staging_path.exists():
            raise FileExistsError("Chunk identity already exists")
        mkdir(self.staging_path.parent)
        self.staging_path.mkdir()
        try:
            self._pcm = open_file(self.staging_path / "audio.pcm", "xb")
            self._journal = open_file(self.staging_path / "blocks.jsonl", "xb")
        except BaseException:
            self.abort()
            raise
        with _writers_lock:
            _writers.add(self)

    def append(self, block: PCMBlock) -> None:
        with root_mutex(self.root):
            check_write_allowed(self.root, self.session_id)
            self._append(block)

    def _append(self, block: PCMBlock) -> None:
        if self._closed or self._failed:
            raise ValueError("Writer is closed or failed")
        if (block.session_id, block.track_id, block.epoch_id, block.format) != (
            self.session_id,
            self.track_id,
            self.epoch_id,
            self.format,
        ):
            raise ValidationError("Writer identity mismatch")
        _next(self._previous, block)
        if (
            not 0 < len(block.payload) <= MAX_BLOCK_BYTES
            or self._bytes + len(block.payload) > MAX_CHUNK_BYTES
            or self._count >= MAX_RECORDS
        ):
            raise ValidationError("Chunk size limit exceeded")
        if self._pcm is None:
            self._open()
        assert self._pcm is not None and self._journal is not None
        record = {
            "schema_version": 1,
            "metadata": block.to_metadata(),
            "offset": self._bytes,
            "length": len(block.payload),
            "payload_sha256": sha256(block.payload),
        }
        record["record_sha256"] = sha256(canonical(record))
        encoded = canonical(record) + b"\n"
        if len(encoded) > MAX_JSON_BYTES:
            raise ValidationError("Journal size limit exceeded")
        try:
            write_all(self._pcm, block.payload)
            sync(self._pcm)
            write_all(self._journal, encoded)
            sync(self._journal)
        except BaseException:
            self._failed = True
            self.abort()
            raise
        self._hash.update(block.payload)
        if self._count == 0:
            self._first_sequence = block.sequence
        self._frames += block.frame_count
        self._bytes += len(block.payload)
        self._count += 1
        self._previous = block

    def seal(self) -> ChunkDescriptor:
        with root_mutex(self.root):
            check_write_allowed(self.root, self.session_id)
            return self._seal()

    def _seal(self) -> ChunkDescriptor:
        if self._closed or self._failed or self._previous is None:
            raise ValueError("Cannot seal empty, closed or failed writer")
        if self._previous.fragment_index + 1 != self._previous.fragment_count:
            raise ValidationError("Cannot seal incomplete packet fragments")
        descriptor = ChunkDescriptor(
            self.session_id,
            self.track_id,
            self.epoch_id,
            self.chunk_id,
            self.format,
            self._frames,
            self._bytes,
            self.relative_path,
            self._hash.hexdigest(),
            self._first_sequence,
            self._previous.sequence,
            self._count,
        )
        try:
            assert self._pcm is not None and self._journal is not None
            sync(self._pcm)
            sync(self._journal)
            with open_file(self.staging_path / "descriptor.json", "xb") as stream:
                write_all(stream, canonical(descriptor.to_dict()) + b"\n")
                sync(stream)
            self.abort()
            scan_prefix(self.staging_path, strict=True)
            mkdir(self.path.parent)
            check_path(self.path)
            if self.path.exists():
                raise FileExistsError("Final bundle already exists")
            # A unique nonempty directory cannot be replaced by this rename.
            self.staging_path.rename(self.path)
            return verify_bundle(self.path)
        except BaseException:
            self.abort()
            raise

    def abort(self) -> None:
        with root_mutex(self.root):
            self._abort()

    def _abort(self) -> None:
        self._closed = True
        error: OSError | None = None
        for stream in (self._pcm, self._journal):
            if stream is not None:
                try:
                    stream.close()
                except OSError as exc:
                    error = exc
        self._pcm = self._journal = None
        if error is not None:
            raise error
