"""G04 CLI: `list --unfinished`, `finalize` and their closed error codes, end to end.

Subprocesses import this checkout's src (PYTHONPATH) so an isolated copy tests itself.
No device, model or network.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import wave
from pathlib import Path

import pytest

from recoryn.domain import AudioFormat, PCMBlock, SessionState
from recoryn.storage import ChunkWriter, Library

pytestmark = pytest.mark.e2e

FMT = AudioFormat(48000, 1)
SRC = Path(__file__).resolve().parents[2] / "src"


def environment() -> dict[str, str]:
    values = os.environ.copy()
    values["PYTHONPATH"] = str(SRC)
    values["PYTHONDONTWRITEBYTECODE"] = "1"
    values["PYTHONNOUSERSITE"] = "1"
    return values


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "recoryn", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        env=environment(),
    )


def block(session: str, epoch: str, index: int) -> PCMBlock:
    return PCMBlock(
        session,
        "mic",
        epoch,
        index,
        FMT,
        4,
        bytes([10 + index]) * 8,
        1000 + index * 83333,
        1000 + index * 83333,
        device_frame_position=index * 4,
    )


def interrupted(root: Path, session: str = "s") -> None:
    with Library(root) as library:
        library.create_session(session)
        library.transition(session, SessionState.RECORDING, 0)
        writer = ChunkWriter(root, block(session, "e1", 0))
        for index in range(2):
            writer.append(block(session, "e1", index))
        library.register_chunk(writer.seal())
        library.transition(session, SessionState.INTERRUPTED, 1)


def test_c1_list_unfinished_reports_inventory(tmp_path: Path) -> None:
    """G04-C1-list-unfinished"""
    root = tmp_path / "library"
    interrupted(root, "a")
    with Library(root) as library:
        library.create_session("b")
        library.transition("b", SessionState.FINALIZING, 0)
        library.finalize_session("b")
    completed = run_cli("--root", str(root), "list", "--unfinished")
    assert completed.returncode == 0, completed.stdout + completed.stderr
    listed = json.loads(completed.stdout)
    assert [(item["session_id"], item["state"], item["live"]) for item in listed] == [
        ("a", "INTERRUPTED", False)
    ]
    assert listed[0]["catalog_chunks"] == 1 and listed[0]["state_version"] == 2
    plain = json.loads(run_cli("--root", str(root), "list").stdout)
    assert plain == [
        {"session_id": "a", "state": "INTERRUPTED"},
        {"session_id": "b", "state": "FINALIZED"},
    ]


def test_c2_finalize_twice_is_idempotent(tmp_path: Path) -> None:
    """G04-C2-finalize-twice"""
    root = tmp_path / "library"
    interrupted(root)
    first = run_cli("--root", str(root), "finalize", "s")
    assert first.returncode == 0, first.stdout + first.stderr
    sealed = json.loads(first.stdout)
    assert (sealed["state"], sealed["already_finalized"], sealed["frame_count"]) == (
        "FINALIZED",
        False,
        8,
    )
    assert sealed["previous_state"] == "INTERRUPTED" and "recovery" in sealed
    assert str(root) not in first.stdout  # no local paths in the report
    second = run_cli("--root", str(root), "finalize", "s")
    assert second.returncode == 0, second.stdout
    again = json.loads(second.stdout)
    assert again["already_finalized"] is True and again["chunk_count"] == sealed["chunk_count"]


REFUSED = [
    pytest.param("delete-pending", "DELETE_PENDING", id="G04-C3-finalize-delete-pending"),
    pytest.param("missing", "NOT_FOUND", id="G04-C3-finalize-not-found"),
]


@pytest.mark.parametrize(("fixture", "code"), REFUSED)
def test_c3_finalize_refusals_print_a_closed_code(tmp_path: Path, fixture: str, code: str) -> None:
    root = tmp_path / "library"
    interrupted(root)
    if fixture == "delete-pending":
        with Library(root) as library:
            writer = ChunkWriter(root, block("s", "e2", 0))
            writer.append(block("s", "e2", 0))
            assert library.delete_session("s")["state"] == "DELETE_PENDING"
            writer.abort()
    target = "s" if fixture == "delete-pending" else "nobody"
    completed = run_cli("--root", str(root), "finalize", target)
    assert completed.returncode == 1
    output = json.loads(completed.stdout)
    assert output["code"] == code
    assert output["message"] == "Operation failed; media preserved"
    assert set(output) == {"error", "code", "message"}


_CRASH = r"""
import os
import sys
import threading
from pathlib import Path

from recoryn.domain import AudioFormat, PCMBlock, SessionState
from recoryn.storage import ChunkWriter, Library

root, ready = Path(sys.argv[1]), Path(sys.argv[2])
FMT = AudioFormat(48000, 1)


def block(i, epoch="e1"):
    return PCMBlock("crashed", "mic", epoch, i, FMT, 4, bytes([10 + i]) * 8,
                    1000 + i * 83333, 1000 + i * 83333, device_frame_position=i * 4)


library = Library(root)
session = library.create_session("crashed")
library.transition("crashed", SessionState.RECORDING, session.state_version)
writer = ChunkWriter(root, block(0))
for i in range(2):
    writer.append(block(i))
library.register_chunk(writer.seal())
open_writer = ChunkWriter(root, block(2))
open_writer.append(block(2))  # an unsealed chunk is in flight when the process dies
temporary = ready.with_name(ready.name + ".tmp")
temporary.write_text("READY", encoding="ascii")
os.replace(temporary, ready)
threading.Event().wait()
"""


def test_c4_killed_recording_recovers_finalizes_and_exports(tmp_path: Path) -> None:
    """G04-C4-kill-recover-finalize-export"""
    root, marker = tmp_path / "library", tmp_path / "ready"
    process = subprocess.Popen(
        [sys.executable, "-c", _CRASH, str(root), str(marker)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=environment(),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        deadline = time.monotonic() + 20
        while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert marker.exists(), process.communicate(timeout=10)
    finally:
        process.kill()
        process.communicate(timeout=10)
    early = run_cli("--root", str(root), "export", "crashed", "--output", str(tmp_path / "early"))
    assert early.returncode == 1 and not (tmp_path / "early").exists()
    recovered = run_cli("--root", str(root), "recover", "crashed")
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    report = json.loads(recovered.stdout)
    assert (report["state"], report["previous_state"], report["recovered"]) == (
        "INTERRUPTED",
        "RECORDING",
        1,
    )
    finalized = run_cli("--root", str(root), "finalize", "crashed")
    assert finalized.returncode == 0, finalized.stdout
    assert json.loads(finalized.stdout)["frame_count"] == 12
    output = tmp_path / "exported"
    exported = run_cli("--root", str(root), "export", "crashed", "--output", str(output))
    assert exported.returncode == 0, exported.stdout + exported.stderr
    manifest = json.loads((output / "export.json").read_text(encoding="utf-8"))
    audio = b""
    for item in manifest["files"]:
        with wave.open(str(output / item["file"]), "rb") as stream:
            audio += stream.readframes(stream.getnframes())
    assert audio == b"".join(bytes([10 + index]) * 8 for index in range(3))
    again = run_cli("--root", str(root), "recover", "crashed")
    assert json.loads(again.stdout)["state"] == "FINALIZED"


def test_declared_cli_denominators_are_complete_and_unique() -> None:
    ids = [
        "G04-C1-list-unfinished",
        "G04-C2-finalize-twice",
        *(case.id for case in REFUSED),
        "G04-C4-kill-recover-finalize-export",
    ]
    assert len(ids) == len(set(ids)) == 5


@pytest.mark.skipif(sys.platform != "win32", reason="actual NTFS junction/hard link")
@pytest.mark.parametrize(
    "kind", ("junction", "hardlink"), ids=[f"G04-FIX2-CLI-{i}" for i in range(2)]
)
def test_cli_isolates_unsafe_session_and_keeps_good_session_finalizable(
    tmp_path: Path, kind: str
) -> None:
    import _winapi

    root = tmp_path / "library"
    interrupted(root, "bad")
    interrupted(root, "good")
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "private"
    target.write_bytes(b"private canary")
    if kind == "junction":
        link = root / "sessions/bad/staging"
        link.rmdir()
        _winapi.CreateJunction(str(outside), str(link))
    else:
        link = root / "sessions/bad/tracks/linked-file"
        link.hardlink_to(target)
    try:
        result = run_cli("--root", str(root), "list", "--unfinished")
        assert result.returncode == 0, result.stdout + result.stderr
        listed = {row["session_id"]: row for row in json.loads(result.stdout)}
        assert set(listed) == {"bad", "good"}
        assert listed["bad"]["inspection_error"] == "INSPECTION_UNSAFE"
        assert listed["good"]["inspection_error"] is None
        for action in ("recover", "finalize"):
            result = run_cli("--root", str(root), action, "bad")
            assert result.returncode == 1
            assert json.loads(result.stdout)["code"] == "INSPECTION_UNSAFE"
        result = run_cli("--root", str(root), "finalize", "good")
        assert result.returncode == 0, result.stdout + result.stderr
        assert json.loads(result.stdout)["frame_count"] == 8
        assert target.read_bytes() == b"private canary"
    finally:
        assert link.parent.is_relative_to(root)
        if kind == "junction":
            assert getattr(link.lstat(), "st_file_attributes", 0) & 0x400
            link.rmdir()
        else:
            assert link.lstat().st_nlink == 2
            link.unlink()
