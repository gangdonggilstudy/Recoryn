"""G15 seal pipeline: forced interleavings, crash checkpoints and injected-latency measurements.

Orders are forced by parking the sealer thread outside the root mutex (never inside it).
Expected outcomes are literal tables from docs/testing/g15-seal-mutex-cases.md section 4.3.
Synthetic PCM, real SQLite and temporary folders; no device, model or network.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any

import pytest

from recoryn.app.recording import SEAL_CAPACITY, RecordingService
from recoryn.domain import AudioFormat, PCMBlock, SessionState, StateConflict, ValidationError
from recoryn.storage import ChunkWriter, Library, chunks
from recoryn.storage import _coordination as coordination
from recoryn.storage import library as library_module
from recoryn.storage.chunks import has_active_writer

pytestmark = pytest.mark.integration

FMT = AudioFormat(48000, 1)


def block(session: str, track: str, epoch: str, index: int, frames: int = 4) -> PCMBlock:
    stamp = 1_000_000 + index * 10_000_000
    return PCMBlock(
        session,
        track,
        epoch,
        index,
        FMT,
        frames,
        bytes([10 + index % 200, 0]) * frames,
        stamp,
        stamp,
        device_frame_position=index * frames,
    )


def wait_for(predicate: Callable[[], bool], seconds: float = 10) -> None:
    deadline = time.monotonic() + seconds
    while not predicate():
        assert time.monotonic() < deadline, "condition not reached"
        time.sleep(0.005)


class Park:
    """Park the first call from a non-main thread at a hook until released."""

    def __init__(self) -> None:
        self.entered, self.release = threading.Event(), threading.Event()
        self.used = False

    def __call__(self) -> None:
        if self.used or threading.current_thread() is threading.main_thread():
            return
        self.used = True
        self.entered.set()
        assert self.release.wait(20)


def hook(
    monkeypatch: pytest.MonkeyPatch, owner: Any, name: str, park: Park, *, after: bool = False
) -> None:
    original = getattr(owner, name)

    def wrapped(*args: Any, **kwargs: Any) -> Any:
        if not after:
            park()
        result = original(*args, **kwargs)
        if after:
            park()
        return result

    monkeypatch.setattr(owner, name, wrapped)


# Sealer positions: D<V, V<D<P, P<D<G (all outside the root mutex) and after release.
POSITIONS = ("before-verify", "after-verify", "before-register")


def install(monkeypatch: pytest.MonkeyPatch, position: str) -> Park:
    park = Park()
    if position == "before-verify":
        hook(monkeypatch, ChunkWriter, "_prepare", park)
    elif position == "after-verify":
        hook(monkeypatch, ChunkWriter, "_prepare", park, after=True)
    elif position == "before-register":
        hook(monkeypatch, Library, "register_chunk", park)
    elif position == "before-release":
        hook(monkeypatch, ChunkWriter, "unhold", park)
    else:
        raise AssertionError(position)
    return park


@contextmanager
def recording(
    root: Path, tracks: tuple[str, ...] = ("mic",), chunk_frames: int = 4
) -> Iterator[tuple[Library, RecordingService]]:
    with Library(root) as library:
        service = RecordingService(
            library, {track: FMT for track in tracks}, session_id="s", chunk_frames=chunk_frames
        )
        try:
            service.start()
            yield library, service
        finally:
            service.join_writer()


def catalogued(library: Library, session: str) -> int:
    return int(
        library._db.execute(
            "SELECT COUNT(*) FROM chunks WHERE session_id=?", (session,)
        ).fetchone()[0]
    )


def published(root: Path, session: str) -> int:
    tracks = root / "sessions" / session / "tracks"
    return len(list(tracks.rglob("descriptor.json"))) if tracks.exists() else 0


HB1 = [pytest.param(position, id=f"G15-HB1-{position}") for position in POSITIONS] + [
    pytest.param("after-release", id="G15-HB1-after-release")
]


def _hb1(
    root: Path, monkeypatch: pytest.MonkeyPatch, position: str, *, projection_fails: bool = False
) -> None:
    with recording(root) as (library, service):
        park = None if position == "after-release" else install(monkeypatch, position)
        assert service.submit(block("s", "mic", service.epochs["mic"], 0))
        if park is None:
            wait_for(lambda: catalogued(library, "s") == 1 and not has_active_writer(root, "s"))
            assert service.stop(timeout=30)["state"] == "FINALIZED"
            assert library.delete_session("s")["state"] == "DELETED_LOCAL"
        else:
            assert park.entered.wait(10)
            before = (published(root, "s"), catalogued(library, "s"))
            if projection_fails:
                # The journal intent is published but its DB row is not, so only the
                # in-memory index and the entry names can refuse the parked chunk.
                original = Library._project_intent

                def fail(self: Library, *args: Any) -> None:
                    raise OSError("G15 injected projection failure")

                monkeypatch.setattr(Library, "_project_intent", fail)
                with pytest.raises(OSError):
                    library.delete_session("s")
                monkeypatch.setattr(Library, "_project_intent", original)
            else:
                first = library.delete_session("s")
                # G-P05 (133b010): a live recorder is the first blocker, before the
                # active seal; both keep the deletion pending.
                assert (first["state"], first["deleted"], first["reason"]) == (
                    "DELETE_PENDING",
                    False,
                    "SESSION_LIVE",
                )
            park.release.set()
            service.join_writer()
            assert service.health_snapshot()["storage_failed"] is True
            # No bundle is published and no row is catalogued after the intent (I1).
            assert published(root, "s") == before[0] == (1 if position == "before-register" else 0)
            assert catalogued(library, "s") == before[1] == 0
            assert library.delete_session("s")["state"] == "DELETED_LOCAL"
        assert not (root / "sessions" / "s").exists()
        assert library.recover_session("s")["state"] == "DELETE_PENDING"  # I3: no rebirth
        assert not (root / "sessions" / "s").exists()


@pytest.mark.parametrize("position", HB1)
def test_hb1_seal_and_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, position: str
) -> None:
    _hb1(tmp_path / "library", monkeypatch, position)


LIVE_POSITIONS = (*POSITIONS, "before-release")
HB2 = [pytest.param(position, id=f"G15-HB2-{position}") for position in LIVE_POSITIONS]
HB3 = [pytest.param(position, id=f"G15-HB3-{position}") for position in LIVE_POSITIONS]


def _during_drain(
    root: Path, monkeypatch: pytest.MonkeyPatch, position: str, attempt: Callable[[Library], Any]
) -> None:
    with recording(root) as (library, service):
        park = install(monkeypatch, position)
        assert service.submit(block("s", "mic", service.epochs["mic"], 0))
        assert park.entered.wait(10)
        stopped: dict[str, Any] = {}
        stopper = threading.Thread(target=lambda: stopped.update(service.stop(timeout=30)))
        stopper.start()
        wait_for(lambda: not service._accepting)
        with pytest.raises(StateConflict) as refused:
            attempt(library)
        assert library.get_session("s").state is SessionState.RECORDING
        park.release.set()
        stopper.join(30)
        assert not stopper.is_alive()
        assert (stopped["state"], stopped["frame_count"]) == ("FINALIZED", 4)
        return refused.value  # type: ignore[return-value]


@pytest.mark.parametrize("position", HB2)
def test_hb2_finalize_waits_for_an_unregistered_chunk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, position: str
) -> None:
    error = _during_drain(
        tmp_path / "library", monkeypatch, position, lambda lib: lib.finalize_unfinished("s")
    )
    assert str(error) == "SESSION_LIVE"


@pytest.mark.parametrize("position", HB3)
def test_hb3_recovery_waits_for_an_unregistered_chunk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, position: str
) -> None:
    error = _during_drain(
        tmp_path / "library", monkeypatch, position, lambda lib: lib.recover_session("s")
    )
    assert str(error) == "Live writer cannot be recovered"


class RootHoldMeter:
    """Outermost root-mutex ownership per thread, excluding wait time."""

    def __init__(self, lock: Any) -> None:
        self.lock = lock
        self.local = threading.local()
        self.holds: list[tuple[str, float]] = []
        self.guard = threading.Lock()

    def __enter__(self) -> RootHoldMeter:
        self.lock.acquire()
        depth = getattr(self.local, "depth", 0)
        if depth == 0:
            self.local.started = time.perf_counter()
        self.local.depth = depth + 1
        return self

    def __exit__(self, *exc: Any) -> None:
        self.local.depth -= 1
        if self.local.depth == 0:
            elapsed = time.perf_counter() - self.local.started
            with self.guard:
                self.holds.append((threading.current_thread().name, elapsed))
        self.lock.release()

    def acquire(self, *args: Any, **kwargs: Any) -> bool:
        return bool(self.lock.acquire(*args, **kwargs))

    def release(self) -> None:
        self.lock.release()

    def longest(self, prefix: str) -> float:
        with self.guard:
            return max((s for name, s in self.holds if name.startswith(prefix)), default=0.0)

    def p99(self, prefix: str) -> float:
        with self.guard:
            values = sorted(s for name, s in self.holds if name.startswith(prefix))
        return values[min(len(values) - 1, int(len(values) * 0.99))] if values else 0.0

    def holding(self) -> bool:
        """True while the calling thread owns the root mutex."""
        return getattr(self.local, "depth", 0) > 0

    def long_holds(self) -> list[list[Any]]:
        """Diagnostic record only: holds of DIAGNOSTIC_SECONDS or more, never judged."""
        with self.guard:
            return [[n, round(s, 4)] for n, s in self.holds if s >= DIAGNOSTIC_SECONDS]


# Judgement bounds, set the way GT-P04 set MANAGEMENT_HOLD_LIMIT_SECONDS (C00 decision on
# section 15.3). A bound only has to show that one hold cannot overflow the capture queue;
# structural checks carry the rest (no seal or registration on the consumer, no verify_bundle,
# no catalog decode and no journal read under the mutex).
# - HOLD_LIMIT_SECONDS for the sealer, management, GUI-tick and catalog paths. It is 2.5x below
#   the two-track shared capture queue (256 blocks of 10 ms, about 1.28 s) and below every
#   mutant judged by time: MU7 holds at least the injected 1 s or 3 s in LAT seal1 and seal3,
#   IX4 held 1.07 s. This PC's longest legitimate hold was 35.3 ms, so a runner 1.4-1.7x
#   slower keeps about 8x headroom.
# - The consumer (append only) has no time bound and its rejected blocks are not judged
#   (C00 decision after main 90c6123 CI run 45234308753). append keeps its two fsyncs per
#   block inside the mutex (C00 decision 4), so its hold follows the disk: CI held it
#   0.23-1.04 s and rejected blocks even with one track. That throughput limit belongs to
#   G-P17 (durability unit). What G15 changed is judged by structure instead: the consumer
#   never seals, registers, verifies or decodes; no journal file is read under the mutex;
#   every submitted block is stored or recorded as a QUEUE_DROP gap.
# - Holds of DIAGNOSTIC_SECONDS or more are printed with each measurement and never fail.
HOLD_LIMIT_SECONDS = 0.5
DIAGNOSTIC_SECONDS = 0.05
STRUCTURE = ("seal", "register", "verify", "decode", "locked_journal_read")


def structure_probe(
    monkeypatch: pytest.MonkeyPatch, measured: RootHoldMeter
) -> dict[str, list[str]]:
    """Which threads seal, register, verify or decode, and which read a deletion
    journal file while owning the root mutex (structural judgement, never timed)."""
    seen: dict[str, list[str]] = {kind: [] for kind in STRUCTURE}
    guard = threading.Lock()
    original_seal = ChunkWriter.seal
    original_register = Library.register_chunk
    original_verified = chunks._verified
    original_decode = chunks.ChunkDescriptor.from_dict.__func__  # type: ignore[attr-defined]
    original_read = library_module.read_json

    def note(kind: str) -> None:
        with guard:
            seen[kind].append(threading.current_thread().name)

    def seal(self: ChunkWriter) -> Any:
        note("seal")
        return original_seal(self)

    def register(self: Library, descriptor: Any) -> None:
        note("register")
        original_register(self, descriptor)

    def verified(*args: Any) -> Any:
        note("verify")
        return original_verified(*args)

    def decode(cls: type, value: dict[str, Any]) -> Any:
        note("decode")
        return original_decode(cls, value)

    def read_json(path: Path, **kwargs: Any) -> Any:
        if path.parent.name == "deletion-journal" and measured.holding():
            note("locked_journal_read")
        return original_read(path, **kwargs)

    monkeypatch.setattr(ChunkWriter, "seal", seal)
    monkeypatch.setattr(Library, "register_chunk", register)
    monkeypatch.setattr(chunks, "_verified", verified)
    monkeypatch.setattr(chunks.ChunkDescriptor, "from_dict", classmethod(decode))
    monkeypatch.setattr(library_module, "read_json", read_json)
    return seen


def structure_counts(seen: dict[str, list[str]]) -> dict[str, int]:
    """Consumer calls per kind, and journal reads under the mutex by any thread."""
    counts = {
        f"consumer_{kind}": sum(name.startswith("recoryn-writer-") for name in seen[kind])
        for kind in STRUCTURE[:-1]
    }
    counts["locked_journal_reads"] = len(seen["locked_journal_read"])
    return counts


def assert_conserved(
    library: Library,
    session: str,
    submitted: dict[str, int],
    rejected: dict[str, int],
    stored_frames: int,
    frames: int = 480,
) -> None:
    """Every submitted block is stored or a QUEUE_DROP gap, per track (hand-counted)."""
    tracks = library.capture_health(session)["epochs"][-1]["tracks"]
    for track, blocks in submitted.items():
        health = tracks[track]
        assert health["accepted_frames"] + health["dropped_frames"] == blocks * frames
        assert health["dropped_frames"] == rejected[track] * frames
        assert all(gap["reason"] == "QUEUE_DROP" for gap in health["gaps"])
        if not health.get("gap_detail_truncated"):
            assert sum(gap["frame_count"] for gap in health["gaps"]) == health["dropped_frames"]
    assert stored_frames == sum(tracks[track]["accepted_frames"] for track in submitted)


def meter(monkeypatch: pytest.MonkeyPatch, library: Library) -> RootHoldMeter:
    measured = RootHoldMeter(library._mutex)
    monkeypatch.setattr(library, "_mutex", measured)
    monkeypatch.setitem(coordination._roots, library.root, measured)
    return measured


def old_session(root: Path, library: Library) -> None:
    library.create_session("old")
    library.transition("old", SessionState.RECORDING, 0)
    for index in range(2):
        writer = ChunkWriter(root, block("old", "mic", "e1", index))
        writer.append(block("old", "mic", "e1", index))
        library.register_chunk(writer.seal())
    library.transition("old", SessionState.INTERRUPTED, 1)


HB4 = [
    pytest.param(action, position, id=f"G15-HB4-{action}-{position}")
    for action in ("inventory", "finalize", "recover")
    for position in POSITIONS
]


@pytest.mark.parametrize(("action", "position"), HB4)
def test_hb4_management_of_another_session_never_waits_for_a_seal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, action: str, position: str
) -> None:
    root = tmp_path / "library"
    with recording(root) as (library, service):
        old_session(root, library)
        measured = meter(monkeypatch, library)
        park = install(monkeypatch, position)
        assert service.submit(block("s", "mic", service.epochs["mic"], 0))
        assert park.entered.wait(10)
        outcome: dict[str, Any] = {}

        def manage() -> None:
            if action == "inventory":
                outcome["value"] = {
                    i["session_id"]: i["state"] for i in library.unfinished_sessions()
                }
            elif action == "finalize":
                outcome["value"] = library.finalize_unfinished("old")["chunk_count"]
            else:
                outcome["value"] = library.recover_session("old")["state"]

        manager = threading.Thread(target=manage, name="g15-management")
        manager.start()
        manager.join(15)
        finished_while_parked = not manager.is_alive()
        park.release.set()
        manager.join(15)
        assert finished_while_parked, "management waited for the parked seal"
        expected = {
            "inventory": {"old": "INTERRUPTED", "s": "RECORDING"},
            "finalize": 2,
            "recover": "INTERRUPTED",
        }[action]
        assert outcome["value"] == expected
        assert service.stop(timeout=30)["frame_count"] == 4
        holds = {
            "action": action,
            "position": position,
            "management_root_max_s": round(measured.longest("g15-management"), 4),
            "sealer_root_max_s": round(measured.longest("recoryn-sealer-"), 4),
            "writer_root_max_s": round(measured.longest("recoryn-writer-"), 4),
            "long_holds": measured.long_holds(),
        }
        print("G15-HB4-MEASURE " + json.dumps(holds))
        assert measured.longest("g15-management") < HOLD_LIMIT_SECONDS
        assert measured.longest("recoryn-sealer-") < HOLD_LIMIT_SECONDS
        # The consumer's append hold follows the disk and is measured only (see above).


HB5 = [pytest.param(position, id=f"G15-HB5-{position}") for position in POSITIONS]


@pytest.mark.parametrize("position", HB5)
def test_hb5_other_track_keeps_appending_while_a_chunk_seals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, position: str
) -> None:
    root = tmp_path / "library"
    with recording(root, tracks=("mic", "system")) as (library, service):
        park = install(monkeypatch, position)
        epochs = service.epochs
        assert service.submit(block("s", "mic", epochs["mic"], 0))
        assert park.entered.wait(10)
        assert service.submit(block("s", "system", epochs["system"], 0))
        # The consumer appended and handed off the system chunk while mic is parked.
        assert service._seals is not None
        wait_for(lambda: service._seals.qsize() == 1)
        park.release.set()
        result = service.stop(timeout=30)
        assert (result["state"], result["chunk_count"], result["frame_count"]) == (
            "FINALIZED",
            2,
            8,
        )
        assert {c.track_id for c in library.chunks("s")} == {"mic", "system"}


HB6 = [
    pytest.param(position, id=f"G15-HB6-{position}")
    for position in ("before-verify", "during-verify", "after-failure", "after-stop")
]


@pytest.mark.parametrize("position", HB6)
def test_hb6_failed_verification_and_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, position: str
) -> None:
    root = tmp_path / "library"
    with recording(root) as (library, service):
        park = Park()
        original = chunks._verified

        def failing(path: Path, location: Path) -> Any:
            if position == "during-verify":
                park()
            raise ValidationError("G15 injected verification failure")

        monkeypatch.setattr(chunks, "_verified", failing)
        if position == "before-verify":
            hook(monkeypatch, ChunkWriter, "_prepare", park)
        elif position == "after-failure":
            hook(monkeypatch, RecordingService, "_mark_interrupted", park)
        assert service.submit(block("s", "mic", service.epochs["mic"], 0))
        if position == "after-stop":
            wait_for(lambda: service.health_snapshot()["storage_failed"])
            service.join_writer()
            first = library.delete_session("s")
        else:
            assert park.entered.wait(10)
            first = library.delete_session("s")
            park.release.set()
            service.join_writer()
        # G-P05 (133b010): the parked sealer keeps the recorder live (SESSION_LIVE) until
        # it is joined, so only the deletion after the stop completes at once.
        expected_first = "DELETED_LOCAL" if position == "after-stop" else "DELETE_PENDING"
        assert first["state"] == expected_first
        monkeypatch.setattr(chunks, "_verified", original)
        assert service.health_snapshot()["storage_failed"] is True
        assert published(root, "s") == 0  # a failed verification never publishes
        if first["state"] == "DELETE_PENDING":
            assert catalogued(library, "s") == 0
            assert library.delete_session("s")["state"] == "DELETED_LOCAL"
        assert not (root / "sessions" / "s").exists()


_CHILD = r"""
import os
import sys
import threading
import time
from pathlib import Path

from recoryn.app.recording import RecordingService
from recoryn.domain import AudioFormat, PCMBlock
from recoryn.storage import ChunkWriter, Library, chunks

root, ready, phase = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
FMT = AudioFormat(48000, 1)


def announce():
    temporary = ready.with_name(ready.name + ".tmp")
    temporary.write_text("READY", encoding="ascii")
    os.replace(temporary, ready)


def stop_here(*args, **kwargs):
    announce()
    threading.Event().wait()


def park_before(owner, name):
    original = getattr(owner, name)

    def wrapped(*args, **kwargs):
        stop_here()
        return original(*args, **kwargs)

    setattr(owner, name, wrapped)


def block(epoch, index):
    stamp = 1000 + index * 10000000
    return PCMBlock("crashed", "mic", epoch, index, FMT, 4, bytes([10 + index]) * 8,
                    stamp, stamp, device_frame_position=index * 4)


frames = {"append-payload-synced": 96000, "two-chunks": 8}.get(phase, 12)
library = Library(root)
service = RecordingService(library, {"mic": FMT}, session_id="crashed", chunk_frames=frames)
if phase == "append-payload-synced":
    original_sync = chunks.sync
    count = [0]

    def sync(stream):
        original_sync(stream)
        count[0] += 1
        if count[0] == 5:  # the third block's payload, before its journal record
            stop_here()

    chunks.sync = sync
elif phase in ("queued-for-seal", "two-chunks"):
    original_prepare = ChunkWriter._prepare

    def prepare(self):
        if phase == "queued-for-seal":
            stop_here()
        threading.Event().wait()

    ChunkWriter._prepare = prepare
elif phase == "descriptor-written":
    park_before(chunks, "_verified")
elif phase == "verified-before-publish":
    park_before(ChunkWriter, "_publish")
elif phase == "published-before-register":
    park_before(Library, "register_chunk")
elif phase == "registered":
    park_before(ChunkWriter, "unhold")
service.start()
epoch = service.epochs["mic"]
for index in range(3):
    assert service.submit(block(epoch, index))
if phase == "two-chunks":
    staging = root / "sessions" / "crashed" / "staging"
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        journals = sorted(staging.glob("*/blocks.jsonl")) if staging.exists() else []
        lines = sorted(len(path.read_bytes().splitlines()) for path in journals)
        if lines == [1, 2]:
            break
        time.sleep(0.01)
    announce()
threading.Event().wait()
"""


def start_child(root: Path, marker: Path, phase: str) -> subprocess.Popen[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[2] / "src")
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONNOUSERSITE"] = "1"
    process = subprocess.Popen(
        [sys.executable, "-c", _CHILD, str(root), str(marker), phase],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=environment,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    deadline = time.monotonic() + 30
    while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.01)
    if not marker.exists():
        process.kill()
        stdout, stderr = process.communicate(timeout=10)
        pytest.fail(f"Child failed before its barrier: {stdout}\n{stderr}")
    return process


def originals(root: Path) -> dict[str, bytes]:
    base = root / "sessions" / "crashed"
    return {
        path.relative_to(base).as_posix(): path.read_bytes()
        for folder in ("tracks", "staging")
        if (base / folder).exists()
        for path in (base / folder).rglob("*")
        if path.is_file()
    }


CRASH = [
    pytest.param("append-payload-synced", 2, 1, id="G15-C1-append-payload-synced"),
    pytest.param("queued-for-seal", 3, 1, id="G15-C2-queued-for-seal"),
    pytest.param("descriptor-written", 3, 1, id="G15-C3-descriptor-written"),
    pytest.param("verified-before-publish", 3, 1, id="G15-C4-verified-before-publish"),
    pytest.param("published-before-register", 3, 1, id="G15-C5-published-before-register"),
    pytest.param("registered", 3, 1, id="G15-C6-registered"),
    pytest.param("two-chunks", 3, 2, id="G15-C7-two-chunks"),
]


@pytest.mark.parametrize(("phase", "blocks", "chunk_count"), CRASH)
def test_crash_checkpoints_recover_the_exact_prefix(
    tmp_path: Path, phase: str, blocks: int, chunk_count: int
) -> None:
    root, marker = tmp_path / "library", tmp_path / "ready"
    process = start_child(root, marker, phase)
    try:
        assert process.poll() is None
    finally:
        process.kill()
        process.communicate(timeout=10)
    expected = b"".join(bytes([10 + index]) * 8 for index in range(blocks))
    with Library(root) as library:
        before = originals(root)
        first = library.recover_session("crashed")
        second = library.recover_session("crashed")
        assert (second["adopted"], second["recovered"]) == (0, 0)
        assert first["state"] == second["state"] == "INTERRUPTED"
        catalog = library.chunks("crashed")
        assert len(catalog) == chunk_count
        joined = b"".join((root / c.relative_path / "audio.pcm").read_bytes() for c in catalog)
        assert joined == expected  # exact prefix, no duplicated frame
        after = originals(root)
        assert all(after.get(name) == data for name, data in before.items())


LAT = [
    pytest.param(seal, append, 1, id=f"G15-LAT-seal{seal:g}-append{int(append * 1000)}ms")
    for append in (0.0, 0.005)
    for seal in (0.0, 0.2, 1.0, 3.0)
] + [
    # G05R-02 observation O1: two tracks lost frames on HEAD even without tombstones.
    pytest.param(seal, 0.0, 2, id=f"G15-LAT2-two-tracks-seal{seal:g}")
    for seal in (0.0, 1.0)
]


@pytest.mark.parametrize(("seal_delay", "append_delay", "track_count"), LAT)
def test_injected_latency_keeps_the_root_mutex_short(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    seal_delay: float,
    append_delay: float,
    track_count: int,
) -> None:
    root = tmp_path / "library"
    with Library(root) as library:
        measured = meter(monkeypatch, library)
        original_prepare = ChunkWriter._prepare
        original_sync = chunks.sync

        # time.sleep(0) would itself yield the GIL on every call, so a zero delay must
        # leave the original code path untouched.
        def slow_prepare(self: ChunkWriter) -> Any:
            if seal_delay:
                time.sleep(seal_delay)  # a slow disk or CPU while verifying, outside the mutex
            return original_prepare(self)

        def slow_sync(stream: Any) -> None:
            if append_delay and threading.current_thread().name.startswith("recoryn-writer-"):
                time.sleep(append_delay)
            original_sync(stream)

        monkeypatch.setattr(ChunkWriter, "_prepare", slow_prepare)
        monkeypatch.setattr(chunks, "sync", slow_sync)
        seen = structure_probe(monkeypatch, measured)
        tracks = ("mic", "system")[:track_count]
        service = RecordingService(
            library, {track: FMT for track in tracks}, session_id="rec", chunk_frames=48_000
        )
        rejected = dict.fromkeys(tracks, 0)
        fifo_max = 0
        try:
            service.start()
            epochs = service.epochs
            started = time.perf_counter()
            for index in range(600):  # 6 s at 100 blocks per second per track, 1 s chunks
                for track in tracks:
                    rejected[track] += not service.submit(
                        block("rec", track, epochs[track], index, frames=480)
                    )
                assert service._seals is not None
                fifo_max = max(fifo_max, service._seals.qsize())
                delay = started + (index + 1) * 0.01 - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)
            result = service.stop(timeout=120)
        finally:
            service.join_writer()
        measurement = {
            "tracks": track_count,
            "seal_delay_s": seal_delay,
            "append_delay_s": append_delay,
            "writer_root_max_s": round(measured.longest("recoryn-writer-"), 4),
            "writer_root_p99_s": round(measured.p99("recoryn-writer-"), 4),
            "sealer_root_max_s": round(measured.longest("recoryn-sealer-"), 4),
            "rejected_blocks": sum(rejected.values()),
            "fifo_max": fifo_max,
            "stored_frames": result["frame_count"],
            **structure_counts(seen),
            "long_holds": measured.long_holds(),
        }
        print("G15-LAT-MEASURE " + json.dumps(measurement))
        # Structure, the sealer bound and conservation carry the verdict. The consumer's
        # hold and the rejected blocks are measurements (CI disks: section 17).
        assert {key: measurement[key] for key in structure_counts(seen)} == dict.fromkeys(
            structure_counts(seen), 0
        )
        assert len(seen["seal"]) == len(seen["register"]) >= 1  # the sealer did the work
        assert measurement["sealer_root_max_s"] < HOLD_LIMIT_SECONDS
        assert fifo_max <= SEAL_CAPACITY
        assert_conserved(
            library, "rec", dict.fromkeys(tracks, 600), rejected, result["frame_count"]
        )


# --- PART2: registration (section 3.3) and the deletion-intent index (section 11) -----

HISTORY_UNAVAILABLE = "DELETION_HISTORY_UNAVAILABLE"
UNAVAILABLE = "UNAVAILABLE"
OVERLAP = "Overlapping source sequence ranges"


def held(measured: RootHoldMeter, action: Callable[[], Any]) -> float:
    """The calling thread's longest root-mutex hold during action alone."""
    with measured.guard:
        measured.holds.clear()
    action()
    return measured.longest(threading.current_thread().name)


def sealed_writer(root: Path, first: PCMBlock) -> ChunkWriter:
    """A held writer whose chunk is published and whose capability is live."""
    writer = ChunkWriter(root, first)
    writer.append(first)
    writer.hold()
    writer.seal()
    return writer


def capability_of(writer: ChunkWriter) -> chunks.SealedChunk:
    capability = writer.capability
    assert capability is not None
    return capability


def intent_body(session: str, generation: int = 1) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "session_id": session,
        "generation": generation,
        "state": "DELETE_REQUESTED",
    }


def tombstones(root: Path, count: int) -> set[str]:
    """Completed deletions as G-P05 leaves them: a journal intent and a DELETED_LOCAL row."""
    with Library(root):
        pass  # schema and journal folder
    names = {f"t{index:04d}" for index in range(count)}
    for session in names:
        (root / "deletion-journal" / f"{session}.json").write_text(
            json.dumps(intent_body(session)), encoding="utf-8"
        )
    with closing(sqlite3.connect(root / "library.sqlite")) as connection, connection:
        connection.executemany(
            "INSERT INTO deleted_sessions VALUES(?,1,'DELETED_LOCAL')", [(s,) for s in names]
        )
    return names


def oracle(root: Path) -> tuple[set[str], set[str]]:
    """(intents, listed sessions) read with json and sqlite3 directly, never the Library."""
    journal = {
        json.loads(path.read_bytes())["session_id"]
        for path in (root / "deletion-journal").glob("*.json")
    }
    with closing(sqlite3.connect(root / "library.sqlite")) as connection:
        deleted = {row[0] for row in connection.execute("SELECT session_id FROM deleted_sessions")}
        sessions = {row[0] for row in connection.execute("SELECT session_id FROM sessions")}
    intents = journal | deleted
    return intents, sessions - intents


def classify(call: Callable[[], Any]) -> Any:
    try:
        value = call()
    except StateConflict as error:
        return "INTENT" if str(error) == "Session has a deletion intent" else f"CONFLICT:{error}"
    except ValidationError as error:
        return UNAVAILABLE if error.args == (HISTORY_UNAVAILABLE,) else f"INVALID:{error}"
    return value


def count_catalog_work(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """Catalog rows decoded and bundles re-hashed while it runs (structural, not timed)."""
    counts = {"descriptor_decodes": 0, "verify_bundle": 0}
    original_decode = chunks.ChunkDescriptor.from_dict.__func__  # type: ignore[attr-defined]
    original_verify = library_module.verify_bundle

    def decode(cls: type, value: dict[str, Any]) -> Any:
        counts["descriptor_decodes"] += 1
        return original_decode(cls, value)

    def verify(path: Path) -> Any:
        counts["verify_bundle"] += 1
        return original_verify(path)

    monkeypatch.setattr(chunks.ChunkDescriptor, "from_dict", classmethod(decode))
    monkeypatch.setattr(library_module, "verify_bundle", verify)
    return counts


def count_locked_journal_reads(
    monkeypatch: pytest.MonkeyPatch, measured: RootHoldMeter
) -> list[int]:
    """Journal files read while the reading thread owns the root mutex (structural)."""
    reads = [0]
    original = library_module.read_json

    def read_json(path: Path, **kwargs: Any) -> Any:
        if path.parent.name == "deletion-journal" and measured.holding():
            reads[0] += 1
        return original(path, **kwargs)

    monkeypatch.setattr(library_module, "read_json", read_json)
    return reads


REG = [pytest.param(count, id=f"G15-REG-n{count}") for count in (0, 900, 3600)]


@pytest.mark.parametrize("existing", REG)
def test_reg_registration_hold_does_not_grow_with_the_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, existing: int
) -> None:
    root = tmp_path / "library"
    with Library(root) as library:
        library.create_session("s")
        library.transition("s", SessionState.RECORDING, 0)
        writer = sealed_writer(root, block("s", "mic", "e1", existing))
        template = capability_of(writer).descriptor.to_dict()
        folder = template["relative_path"].rsplit("/", 1)[0]
        # Bulk catalog fixture (probe 2): one-block ranges 0..existing-1 in one
        # transaction, so only the registration of the next chunk is timed.
        rows = []
        for index in range(existing):
            chunk_id = f"bulk{index:05d}"
            value = dict(
                template,
                chunk_id=chunk_id,
                relative_path=f"{folder}/{chunk_id}",
                first_sequence=index,
                last_sequence=index,
            )
            encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
            rows.append((chunk_id, "s", value["relative_path"], encoded))
        library._db.executemany("INSERT INTO chunks VALUES(?,?,?,?)", rows)
        library._db.commit()
        measured = meter(monkeypatch, library)
        work = count_catalog_work(monkeypatch)
        capability = capability_of(writer)
        try:
            hold = held(measured, lambda: library.register_chunk(capability))
        finally:
            writer.unhold()
        structure = dict(work)
        assert catalogued(library, "s") == existing + 1
        # The reduced check still refuses an overlap with the oldest range.
        overlapping = sealed_writer(root, block("s", "mic", "e1", 0))
        try:
            with pytest.raises(StateConflict) as refused:
                library.register_chunk(capability_of(overlapping))
        finally:
            overlapping.unhold()
        assert str(refused.value) == OVERLAP
        assert catalogued(library, "s") == existing + 1
        measurement = {
            "existing": existing,
            "root_hold_s": round(hold, 4),
            **structure,
            "long_holds": measured.long_holds(),
        }
        print("G15-REG-MEASURE " + json.dumps(measurement))
        # Structure carries the verdict: no catalog row is decoded (the overlap check runs in
        # SQLite) and nothing is re-hashed, whatever n is. The bound only guards the queue.
        assert structure == {"descriptor_decodes": 0, "verify_bundle": 0}
        assert hold < HOLD_LIMIT_SECONDS


SCALE_OPERATIONS = ("create_session", "get_session", "register_chunk", "list_sessions")
IDX_SCALE = [
    pytest.param(count, operation, id=f"G15-IDX-SCALE-{operation}-n{count}")
    for count in (0, 100, 400, 1000)
    for operation in SCALE_OPERATIONS
]


@pytest.mark.parametrize(("count", "operation"), IDX_SCALE)
def test_idx_scale_queries_stay_short_as_tombstones_grow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, count: int, operation: str
) -> None:
    root = tmp_path / "library"
    deleted = tombstones(root, count)
    with Library(root) as library:
        library.create_session("live")
        library.transition("live", SessionState.RECORDING, 0)
        intents, listed = oracle(root)
        assert intents == deleted and listed == {"live"}
        measured = meter(monkeypatch, library)
        reads = count_locked_journal_reads(monkeypatch, measured)

        def judged(hold: float) -> None:
            measurement = {
                "tombstones": count,
                "operation": operation,
                "root_hold_s": round(hold, 4),
                "journal_reads_under_mutex": reads[0],
                "long_holds": measured.long_holds(),
            }
            print("G15-IDX-SCALE-MEASURE " + json.dumps(measurement))
            # The index answers: no journal file is read under the mutex, whatever N is.
            assert reads[0] == 0
            assert hold < HOLD_LIMIT_SECONDS

        if operation == "create_session":
            judged(held(measured, lambda: library.create_session("fresh")))
            for session in deleted:
                assert classify(lambda s=session: library.create_session(s)) == "INTENT"
            assert oracle(root)[1] == {"live", "fresh"}
        elif operation == "get_session":
            judged(held(measured, lambda: library.get_session("live")))
            for session in deleted:
                assert classify(lambda s=session: library.get_session(s)) == "INTENT"
        elif operation == "register_chunk":
            writer = sealed_writer(root, block("live", "mic", "e1", 0))
            capability = capability_of(writer)
            try:
                judged(held(measured, lambda: library.register_chunk(capability)))
            finally:
                writer.unhold()
            assert catalogued(library, "live") == 1
        else:
            result: list[set[str]] = []
            judged(
                held(
                    measured,
                    lambda: result.append({s.session_id for s in library.list_sessions()}),
                )
            )
            assert result == [listed]
        assert reads[0] == 0  # the refusal loops above read nothing under the mutex either


FAIL_TABLE: dict[str, tuple[Any, Any, Any, Any]] = {
    # state: (get_session a, b, j; list_sessions), written by hand from section 11.4.
    "normal": ("OK", "OK", "INTENT", {"a", "b"}),
    "tmp_added": (UNAVAILABLE, UNAVAILABLE, UNAVAILABLE, UNAVAILABLE),
    "unknown_added": (UNAVAILABLE, UNAVAILABLE, UNAVAILABLE, UNAVAILABLE),
    "corrupt_added": (UNAVAILABLE, UNAVAILABLE, UNAVAILABLE, UNAVAILABLE),
    "intent_removed": ("OK", "OK", "OK", {"a", "b", "j"}),
    "journal_removed": (UNAVAILABLE, UNAVAILABLE, UNAVAILABLE, UNAVAILABLE),
    "db_only": ("OK", "INTENT", "INTENT", {"a"}),
    # Accepted difference (section 11.6): an in-place rewrite of an existing entry keeps
    # its name and the directory stamp, so _live keeps the validated index and still
    # blocks j; the management list validates contents in full and fails closed.
    "inplace_rewrite": ("OK", "OK", "INTENT", UNAVAILABLE),
}
IDX_FAIL = [
    pytest.param(state, query, id=f"G15-IDX-FAIL-{state}-{query}")
    for state in FAIL_TABLE
    for query in ("get", "list")
]


@pytest.mark.parametrize(("state", "query"), IDX_FAIL)
def test_idx_fail_outside_changes_are_revalidated(tmp_path: Path, state: str, query: str) -> None:
    root = tmp_path / "library"
    with Library(root) as library:
        for session in ("a", "b", "j"):
            library.create_session(session)
    journal = root / "deletion-journal"
    (journal / "j.json").write_text(json.dumps(intent_body("j")), encoding="utf-8")
    with Library(root) as library:
        assert classify(lambda: library.get_session("j")) == "INTENT"  # indexed at open
        # The change follows at once, usually inside the same directory mtime tick.
        if state == "tmp_added":
            (journal / ".tmp-abandoned").write_bytes(b'{"schema_version":1')
        elif state == "unknown_added":
            (journal / "notes.txt").write_bytes(b"x")
        elif state == "corrupt_added":
            (journal / "x.json").write_bytes(b'{"schema_version":1,,}')
        elif state == "intent_removed":
            (journal / "j.json").unlink()
        elif state == "journal_removed":
            shutil.rmtree(journal)
        elif state == "db_only":
            library._db.execute("INSERT INTO deleted_sessions VALUES('b',1,'DELETE_PENDING')")
            library._db.commit()
        elif state == "inplace_rewrite":
            (journal / "j.json").write_bytes(b'{"schema_version":1,,}')
        expected = FAIL_TABLE[state]
        if query == "get":
            observed = tuple(
                classify(lambda s=session: "OK" if library.get_session(s) else None)
                for session in ("a", "b", "j")
            )
            assert observed == expected[:3]
        else:
            assert classify(lambda: {s.session_id for s in library.list_sessions()}) == expected[3]


IDX_HB = [
    pytest.param(position, False, id=f"G15-IDX-HB-{position}")
    for position in (*POSITIONS, "after-release")
] + [pytest.param("before-register", True, id="G15-IDX-HB-projection-failed")]


@pytest.mark.parametrize(("position", "projection_fails"), IDX_HB)
def test_idx_hb_seal_and_delete_among_tombstones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, position: str, projection_fails: bool
) -> None:
    root = tmp_path / "library"
    tombstones(root, 400)
    _hb1(root, monkeypatch, position, projection_fails=projection_fails)


IDX_OPEN = [
    pytest.param(state, id=f"G15-IDX-OPEN-{state}")
    for state in ("normal-n400", "tmp-present", "corrupt-intent")
]


@pytest.mark.parametrize("state", IDX_OPEN)
def test_idx_open_validates_once_and_fails_closed(tmp_path: Path, state: str) -> None:
    root = tmp_path / "library"
    deleted = tombstones(root, 400)
    with Library(root) as library:
        library.create_session("a")
    journal = root / "deletion-journal"
    if state == "tmp-present":
        (journal / ".tmp-orphan").write_bytes(b"{")
    elif state == "corrupt-intent":
        (journal / "t0000.json").write_bytes(b'{"schema_version":1,,}')
    with Library(root) as library:  # opening succeeds in every state
        if state == "normal-n400":
            assert {s.session_id for s in library.list_sessions()} == oracle(root)[1] == {"a"}
            assert library.get_session("a").session_id == "a"
            for session in deleted:
                assert classify(lambda s=session: library.create_session(s)) == "INTENT"
        else:
            for call in (
                lambda: library.get_session("a"),
                lambda: library.create_session("new"),
                library.list_sessions,
            ):
                assert classify(call) == UNAVAILABLE


IDX_UI = [
    pytest.param(count, tracks, id=f"G15-IDX-UI-n{count}-tracks{tracks}")
    for count in (0, 1000)
    for tracks in (1, 2)
]


@pytest.mark.parametrize(("count", "track_count"), IDX_UI)
def test_idx_ui_tick_and_recording_among_tombstones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, count: int, track_count: int
) -> None:
    """G05R-02: 12 s real time, a GUI tick proxy calling chunks() every 250 ms."""
    root = tmp_path / "library"
    tombstones(root, count)
    with Library(root) as library:
        measured = meter(monkeypatch, library)
        seen = structure_probe(monkeypatch, measured)
        tracks = ("mic", "system")[:track_count]
        service = RecordingService(library, {track: FMT for track in tracks}, session_id="rec")
        stop_tick = threading.Event()
        tick_errors: list[str] = []
        ticks = [0]

        def tick() -> None:
            while not stop_tick.wait(0.25):
                try:
                    library.chunks("rec")
                    ticks[0] += 1
                except Exception as error:  # noqa: BLE001 - every tick failure is recorded
                    tick_errors.append(repr(error))

        ticker = threading.Thread(target=tick, name="g15-gui-tick")
        rejected = dict.fromkeys(tracks, 0)
        try:
            service.start()
            ticker.start()
            epochs = service.epochs
            started = time.perf_counter()
            for index in range(1200):  # 12 s at 100 blocks per second per track
                for track in tracks:
                    rejected[track] += not service.submit(
                        block("rec", track, epochs[track], index, frames=480)
                    )
                delay = started + (index + 1) * 0.01 - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)
            result = service.stop(timeout=120)
        finally:
            stop_tick.set()
            if ticker.is_alive():
                ticker.join(10)
            service.join_writer()
        measurement = {
            "tombstones": count,
            "tracks": track_count,
            "tick_root_max_s": round(measured.longest("g15-gui-tick"), 4),
            "sealer_root_max_s": round(measured.longest("recoryn-sealer-"), 4),
            "writer_root_max_s": round(measured.longest("recoryn-writer-"), 4),
            "writer_root_p99_s": round(measured.p99("recoryn-writer-"), 4),
            "rejected_blocks": sum(rejected.values()),
            "stored_frames": result["frame_count"],
            "ticks": ticks[0],
            **structure_counts(seen),
            "long_holds": measured.long_holds(),
        }
        print("G15-IDX-UI-MEASURE " + json.dumps(measurement))
        assert tick_errors == [] and ticks[0] >= 40
        assert measurement["tick_root_max_s"] < HOLD_LIMIT_SECONDS
        assert measurement["sealer_root_max_s"] < HOLD_LIMIT_SECONDS
        assert {key: measurement[key] for key in structure_counts(seen)} == dict.fromkeys(
            structure_counts(seen), 0
        )
        assert_conserved(
            library, "rec", dict.fromkeys(tracks, 1200), rejected, result["frame_count"]
        )
        # Rejected blocks are measured only (CI disks, section 17). Every accepted block
        # is stored; with no rejection that is 576,000 frames per track.


IDX_IO = [pytest.param(case, id=f"G15-IDX-{case}") for case in ("IO1", "IO2", "IO3", "IO4", "IO5")]


@pytest.mark.parametrize("case", IDX_IO)
def test_idx_io_journal_errors_never_stop_another_recording(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    """G05R-04: a journal read error stops management only, never another recording."""
    root = tmp_path / "library"
    armed = {"read": False, "own": False}
    denied: list[str] = []
    original_read = library_module.read_json
    original_names = Library._writer_names

    def read_json(path: Path, **kwargs: Any) -> Any:
        if (
            armed["read"]
            and path.parent.name == "deletion-journal"
            and (case in ("IO4", "IO5") or path.name == "other.json")
        ):
            denied.append(threading.current_thread().name)
            if case == "IO1":
                armed["read"] = False  # once
            raise PermissionError("G15 injected journal read denial")
        return original_read(path, **kwargs)

    def writer_names(self: Library) -> frozenset[str]:
        if armed["own"] and threading.current_thread().name.startswith("recoryn-"):
            raise PermissionError("G15 injected own-intent check failure")
        return original_names(self)

    monkeypatch.setattr(library_module, "read_json", read_json)
    monkeypatch.setattr(Library, "_writer_names", writer_names)
    if case == "IO5":
        deleted = tombstones(root, 3)
        with Library(root) as library:
            library.create_session("a")
        armed["read"] = True
        with Library(root) as library:  # opening succeeds
            for call in (
                lambda: library.get_session("a"),
                lambda: library.create_session("new"),
                library.list_sessions,
            ):
                assert classify(call) == UNAVAILABLE
            armed["read"] = False
            assert {s.session_id for s in library.list_sessions()} == {"a"}
            assert library.create_session("new").session_id == "new"
            for session in deleted:
                assert classify(lambda s=session: library.get_session(s)) == "INTENT"
        return
    with Library(root) as library:
        library.create_session("other")
        service = RecordingService(library, {"mic": FMT}, session_id="rec", chunk_frames=48_000)
        rejected = 0
        try:
            service.start()
            epoch = service.epochs["mic"]
            started = time.perf_counter()
            for index in range(400):  # 4 s, four 1 s chunks
                if index == 150:
                    wait_for(lambda: catalogued(library, "rec") == 1)
                    if case in ("IO1", "IO2"):
                        assert library.delete_session("other")["state"] == "DELETED_LOCAL"
                        armed["read"] = True
                    elif case == "IO3":
                        armed["own"] = True
                    else:
                        (root / "deletion-journal" / "ext.json").write_text(
                            json.dumps(intent_body("ext")), encoding="utf-8"
                        )
                        armed["read"] = True
                if index == 250 and case in ("IO2", "IO4"):
                    assert classify(library.list_sessions) == UNAVAILABLE  # management only
                rejected += not service.submit(block("rec", "mic", epoch, index, frames=480))
                delay = started + (index + 1) * 0.01 - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)
            if case == "IO3":
                wait_for(lambda: service.health_snapshot()["storage_failed"])
            failed = service.health_snapshot()["storage_failed"]
            still_armed = armed["read"]
            armed["read"] = armed["own"] = False
            if case == "IO3":
                service.join_writer()
            else:
                result = service.stop(timeout=60)
        finally:
            service.join_writer()
        assert not any(name.startswith("recoryn-") for name in denied)  # capture never read
        if case == "IO3":
            # Fail closed for I1: the unverifiable session stops at its next write.
            assert failed is True
            assert str(service._writer_error) == "Cannot verify writer deletion intent"
            assert catalogued(library, "rec") == 1  # nothing after the failure
            assert library.get_session("rec").state is SessionState.INTERRUPTED
            return
        # The recording never fails; a rejected block (consumer throughput on a slow disk,
        # section 17) is a measured QUEUE_DROP gap, not a verdict.
        assert failed is False
        accepted = 400 - rejected
        assert (result["state"], result["chunk_count"], result["frame_count"]) == (
            "FINALIZED",
            -(-accepted // 100),  # 1 s chunks of 100 whole blocks
            accepted * 480,
        )
        assert_conserved(library, "rec", {"mic": 400}, {"mic": rejected}, result["frame_count"])
        print("G15-IDX-IO-MEASURE " + json.dumps({"case": case, "rejected_blocks": rejected}))
        if case == "IO1":
            assert still_armed is True  # the one denial was never consumed by capture
        if case in ("IO1", "IO2"):
            assert classify(lambda: library.get_session("other")) == "INTENT"
            assert classify(lambda: library.create_session("other")) == "INTENT"
        else:
            assert {s.session_id for s in library.list_sessions()} == {"other", "rec"}


START = [
    pytest.param("recoryn-writer-", id="G15-START-consumer-fails"),
    pytest.param("recoryn-sealer-", id="G15-START-sealer-fails"),
]


@pytest.mark.parametrize("prefix", START)
def test_start_failure_leaves_no_worker_and_no_live_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, prefix: str
) -> None:
    """G15R-02: as before G15, a worker thread that cannot start leaves nothing live."""
    root = tmp_path / "library"
    original = threading.Thread.start

    def start(self: threading.Thread) -> None:
        if self.name.startswith(prefix):
            raise RuntimeError("can't start new thread")
        original(self)

    with Library(root) as library:
        service = RecordingService(library, {"mic": FMT}, session_id="s")
        monkeypatch.setattr(threading.Thread, "start", start)
        with pytest.raises(RuntimeError):
            service.start()
        monkeypatch.undo()
        alive = [t.name for t in threading.enumerate() if t.name.startswith("recoryn-")]
        assert alive == []
        assert service.is_live() is False
        service.join_writer()  # nothing left to wait for
        assert library.recover_session("s")["state"] == "CREATED"
        assert library.delete_session("s")["state"] == "DELETED_LOCAL"


def payload(index: int) -> bytes:
    return bytes([10 + index % 200, 0]) * 4  # block()'s four-frame payload


def test_hb6_failed_verification_recovers_only_the_verified_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G15R-03, contract 4.3 HB6: nothing of the failed chunk is published or catalogued,
    its staging stays, the session is INTERRUPTED and recovery adopts only the verified
    prefix. Expected by hand: chunk 1 = blocks 0-2, chunk 2's damaged block 5 is lost."""
    root = tmp_path / "library"
    original = ChunkWriter._prepare
    calls = [0]

    def prepare(self: ChunkWriter) -> Any:
        calls[0] += 1
        if calls[0] == 2:  # chunk 2 (blocks 3-5): flip block 5's first byte, size kept
            with (self.staging_path / "audio.pcm").open("r+b") as stream:
                stream.seek(2 * 8)
                first = stream.read(1)
                stream.seek(2 * 8)
                stream.write(bytes([first[0] ^ 0xFF]))
        return original(self)

    monkeypatch.setattr(ChunkWriter, "_prepare", prepare)
    with recording(root, chunk_frames=12) as (library, service):
        epoch = service.epochs["mic"]
        for index in range(6):  # two chunks of three blocks
            assert service.submit(block("s", "mic", epoch, index))
        wait_for(lambda: service.health_snapshot()["storage_failed"])
        service.join_writer()
        staging = root / "sessions" / "s" / "staging"
        assert sorted((c.first_sequence, c.last_sequence) for c in library.chunks("s")) == [(0, 2)]
        assert published(root, "s") == 1
        assert len(list(staging.iterdir())) == 1  # the failed chunk stays for recovery
        assert library.get_session("s").state is SessionState.INTERRUPTED
        monkeypatch.setattr(ChunkWriter, "_prepare", original)
        first = library.recover_session("s")
        second = library.recover_session("s")
        catalog = sorted(library.chunks("s"), key=lambda c: c.first_sequence)
        assert [(c.first_sequence, c.last_sequence) for c in catalog] == [(0, 2), (3, 4)]
        assert "STAGING_TAIL_NOT_ADOPTED" in first["warnings"]
        assert (second["adopted"], second["recovered"]) == (0, 0)
        adopted = (root / catalog[1].relative_path / "audio.pcm").read_bytes()
        assert adopted == payload(3) + payload(4)


def test_sealer_failure_aborts_every_queued_writer_and_loses_no_appended_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G15R-03, contract 3.4: after a sealer failure the FIFO writers and the open writer
    are aborted (none active, staging kept) and recovery adopts every appended block."""
    root = tmp_path / "library"
    writers: list[ChunkWriter] = []
    appended: list[int] = []
    original_init = ChunkWriter.__init__
    original_append = ChunkWriter.append
    original_prepare = ChunkWriter._prepare
    park = Park()

    def init(self: ChunkWriter, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)
        writers.append(self)  # strong references: an unaborted writer stays visible

    def append(self: ChunkWriter, item: PCMBlock) -> None:
        original_append(self, item)
        appended.append(item.sequence)

    def prepare(self: ChunkWriter) -> Any:
        if not park.used:
            park()  # chunk 1 waits outside the mutex while the FIFO fills
            raise OSError("G15 injected prepare failure")
        return original_prepare(self)

    monkeypatch.setattr(ChunkWriter, "__init__", init)
    monkeypatch.setattr(ChunkWriter, "append", append)
    monkeypatch.setattr(ChunkWriter, "_prepare", prepare)
    with recording(root, chunk_frames=12) as (library, service):
        epoch = service.epochs["mic"]
        for index in range(3):
            assert service.submit(block("s", "mic", epoch, index))
        assert park.entered.wait(10)
        for index in range(3, 14):  # chunks 2-4 queue in the FIFO, blocks 12-13 stay open
            assert service.submit(block("s", "mic", epoch, index))
        assert service._seals is not None
        seals = service._seals
        wait_for(lambda: seals.qsize() == 3 and len(appended) == 14)
        park.release.set()
        wait_for(lambda: service.health_snapshot()["storage_failed"])
        service.join_writer()
        assert library.get_session("s").state is SessionState.INTERRUPTED
        assert (published(root, "s"), catalogued(library, "s")) == (0, 0)
        assert len(writers) == 5
        assert not has_active_writer(root, "s")  # every writer was aborted
        assert all(writer.staging_path.is_dir() for writer in writers)
        monkeypatch.undo()
        first = library.recover_session("s")
        second = library.recover_session("s")
        catalog = sorted(library.chunks("s"), key=lambda c: c.first_sequence)
        assert sum(c.frame_count for c in catalog) == len(appended) * 4 == 56
        joined = b"".join((root / c.relative_path / "audio.pcm").read_bytes() for c in catalog)
        assert joined == b"".join(payload(index) for index in sorted(appended))
        assert (second["adopted"], second["recovered"]) == (0, 0)
        assert first["state"] == "INTERRUPTED"


SEALER_ERRORS = [
    "G15-HB6R-verified-prefix",
    "G15-FIFO-abort-after-failure",
]


def test_declared_integration_denominators_are_complete_and_unique() -> None:
    groups = {
        "HB1": HB1,
        "HB2": HB2,
        "HB3": HB3,
        "HB4": HB4,
        "HB5": HB5,
        "HB6": HB6,
        "REG": REG,
        "IDX-SCALE": IDX_SCALE,
        "IDX-FAIL": IDX_FAIL,
        "IDX-HB": IDX_HB,
        "IDX-OPEN": IDX_OPEN,
        "IDX-UI": IDX_UI,
        "IDX-IO": IDX_IO,
        "START": START,
    }
    sizes = {name: len(cases) for name, cases in groups.items()}
    assert sizes == {
        "HB1": 4,
        "HB2": 4,
        "HB3": 4,
        "HB4": 9,
        "HB5": 3,
        "HB6": 4,
        "REG": 3,
        "IDX-SCALE": 16,
        "IDX-FAIL": 16,
        "IDX-HB": 5,
        "IDX-OPEN": 3,
        "IDX-UI": 4,
        "IDX-IO": 5,
        "START": 2,
    }
    ids = [case.id for cases in groups.values() for case in cases]
    ids += [case.id for case in CRASH] + [case.id for case in LAT] + SEALER_ERRORS
    assert len(CRASH) == 7 and len(LAT) == 8 + 2 and len(SEALER_ERRORS) == 2
    assert len(ids) == len(set(ids)) == 28 + 7 + 10 + 3 + 49 + 2 + 2
