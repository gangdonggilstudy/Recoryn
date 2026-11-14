"""Kill actual child processes at observed, durable intermediate writer boundaries."""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from recoryn.storage import Library

pytestmark = pytest.mark.integration

_CHILD = r"""
import os
import sys
import threading
from pathlib import Path

from recoryn.domain import AudioFormat, PCMBlock, SessionState
from recoryn.storage import ChunkWriter, Library

root, ready, phase = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
library = Library(root)
session = library.create_session("crashed")
library.transition("crashed", SessionState.RECORDING, session.state_version)
blocks = [PCMBlock("crashed", "mic", "epoch1", i, AudioFormat(48000, 1), 4,
                   bytes([10 + i]) * 8, i * 83333, i * 83333,
                   device_frame_position=i * 4) for i in range(3)]
writer = ChunkWriter(root, blocks[0], chunk_id="crashchunk")

def pause():
    ready.write_text("READY", encoding="ascii")
    threading.Event().wait()

if phase in ("payload_fsynced", "journal_fsynced"):
    original_fsync = os.fsync
    sync_count = 0
    watched_name = "audio.pcm" if phase == "payload_fsynced" else "blocks.jsonl"
    def observed_fsync(fd):
        global sync_count
        original_fsync(fd)
        fd_stat = os.fstat(fd)
        for candidate in root.rglob(watched_name):
            candidate_stat = candidate.stat()
            if (candidate_stat.st_dev, candidate_stat.st_ino) == (fd_stat.st_dev, fd_stat.st_ino):
                sync_count += 1
                if sync_count == 3:
                    pause()
    os.fsync = observed_fsync
for block in blocks:
    writer.append(block)
if phase in ("payload_fsynced", "journal_fsynced"):
    raise RuntimeError("append never reached the observed durability boundary")
descriptor = writer.seal()
if phase == "bundle_published":
    pause()
library.register_chunk(descriptor)
if phase == "catalog_committed":
    pause()
raise RuntimeError("unknown crash phase")
"""


def start_child(root: Path, marker: Path, script: str, *arguments: str) -> subprocess.Popen[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[2] / "src")
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONNOUSERSITE"] = "1"
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(root), str(marker), *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=environment,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    deadline = time.monotonic() + 20
    while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.01)
    if not marker.exists():
        process.kill()
        stdout, stderr = process.communicate(timeout=10)
        pytest.fail(f"Child failed before synchronization barrier: {stdout}\n{stderr}")
    return process


@pytest.mark.parametrize(
    "phase", ("payload_fsynced", "journal_fsynced", "bundle_published", "catalog_committed")
)
def test_actual_process_kill_preserves_exact_prefix(tmp_path: Path, phase: str) -> None:
    root = tmp_path / "library"
    process = start_child(root, tmp_path / "ready", _CHILD, phase)
    try:
        assert process.poll() is None
        assert list(root.rglob("blocks.jsonl"))
        if phase in ("payload_fsynced", "journal_fsynced"):
            assert not list(root.rglob("descriptor.json")), "Kill must precede bundle sealing"
    finally:
        process.kill()
        process.communicate(timeout=10)
    assert process.returncode != 0
    expected = b"\x0a" * 8 + b"\x0b" * 8
    expected_frames = 8
    if phase != "payload_fsynced":
        expected += b"\x0c" * 8
        expected_frames = 12
    with Library(root) as library:
        first = library.recover_session("crashed")
        assert first["session_id"] == "crashed"
        assert sum(chunk.frame_count for chunk in library.chunks("crashed")) == expected_frames
        originals = {
            root / chunk.relative_path / "audio.pcm": (
                root / chunk.relative_path / "audio.pcm"
            ).read_bytes()
            for chunk in library.chunks("crashed")
        }
        assert b"".join(originals.values()) == expected
        library.recover_session("crashed")
        assert sum(chunk.frame_count for chunk in library.chunks("crashed")) == expected_frames
        assert all(path.read_bytes() == content for path, content in originals.items())


def test_library_writer_lock_excludes_a_second_process(tmp_path: Path) -> None:
    script = r"""
import sys
import threading
from pathlib import Path
from recoryn.storage import Library
with Library(Path(sys.argv[1])):
    Path(sys.argv[2]).write_text("READY", encoding="ascii")
    threading.Event().wait()
"""
    root = tmp_path / "library"
    process = start_child(root, tmp_path / "locked", script)
    try:
        with pytest.raises((ValueError, OSError, RuntimeError)):
            with Library(root):
                pytest.fail("A second process acquired the active library writer lock")
    finally:
        process.kill()
        process.communicate(timeout=10)
    with Library(root) as library:
        assert library.list_sessions() == []
