"""G04 cause chains (kill, storage failure, device start failure) and forced interleavings.

Each chain row recovers twice, refuses export and transcription before sealing, finalizes
twice, exports, requests transcription and recovers twice more. Hand-computed byte
prefixes come from the child scripts' payloads, never from the implementation. Child
processes are killed at a READY barrier, as in test_process_crash.py. No device, model
or network.
"""

from __future__ import annotations

import errno
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
import wave
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from recoryn.app.ai import AIService
from recoryn.app.recording import RecordingError, RecordingService
from recoryn.cli import _export, main
from recoryn.content import ContentStore
from recoryn.domain import AudioFormat, PCMBlock, SessionState, StateConflict
from recoryn.providers import ProviderCapabilities, STTResult, TranscriptSegment
from recoryn.storage import ChunkWriter, Library
from recoryn.storage import _coordination as coordination_module
from recoryn.storage import chunks as chunk_module
from recoryn.storage import library as library_module
from recoryn.storage.chunks import has_active_writer
from tests.unit.test_unfinished_sessions import ClaimRecorder

pytestmark = pytest.mark.integration

FMT = AudioFormat(48000, 1)


@pytest.mark.parametrize(
    "operation", ["recover", "finalize"], ids=["G04-F4-LIVE-recover", "G04-F4-LIVE-finalize"]
)
def test_repeated_live_refusals_preserve_every_recording_block(
    tmp_path: Path, operation: str
) -> None:
    with Library(tmp_path / "library") as library:
        service = RecordingService(library, {"mic": FMT}, session_id="rec", chunk_frames=480)
        service.start()
        claims = ClaimRecorder()
        library._claims = claims
        stop = threading.Event()
        outcomes: dict[str, int] = {}
        data = b"\x20\x01" * 480

        def click() -> None:
            call = (
                library.recover_session if operation == "recover" else library.finalize_unfinished
            )
            while not stop.is_set():
                try:
                    call("rec")
                    result = "ACCEPTED"
                except StateConflict as error:
                    result = str(error)
                except BaseException as error:
                    result = type(error).__name__
                outcomes[result] = outcomes.get(result, 0) + 1

        worker = threading.Thread(target=click)
        worker.start()
        rejected = 0
        started = time.perf_counter()
        try:
            for index in range(300):
                stamp = 1_000_000 + index * 10_000_000
                accepted = service.submit(
                    PCMBlock(
                        "rec",
                        "mic",
                        service.epochs["mic"],
                        index,
                        FMT,
                        480,
                        data,
                        stamp,
                        stamp,
                        device_frame_position=index * 480,
                    )
                )
                rejected += not accepted
                delay = started + (index + 1) * 0.01 - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)
        finally:
            stop.set()
            worker.join(30)
        before_stop = service.health_snapshot()
        publications = list(claims.publications)
        (tmp_path / "live-measurement.json").write_text(
            json.dumps(
                {
                    "operation": operation,
                    "outcomes": outcomes,
                    "rejected_blocks": rejected,
                    "claim_publications": len(publications),
                    "accepting": before_stop["accepting"],
                    "storage_failed": before_stop["storage_failed"],
                    "dropped_frames": before_stop["tracks"]["mic"]["dropped_frames"],
                }
            ),
            encoding="utf-8",
        )
        try:
            assert not worker.is_alive()
            assert outcomes and "ACCEPTED" not in outcomes
            assert set(outcomes) <= {"SESSION_LIVE", "Live writer cannot be recovered"}
            assert publications == [], "a refused live request published a claim"
            assert rejected == 0 and before_stop["accepting"] and not before_stop["storage_failed"]
            assert service._writer_error is None
            service.stop(timeout=60)
            assert service.health_snapshot()["tracks"]["mic"]["dropped_frames"] == 0
            descriptors = library.chunks("rec")
            assert len(descriptors) == 300 and sum(d.frame_count for d in descriptors) == 144000
            assert (
                b"".join(
                    (library.root / d.relative_path / "audio.pcm").read_bytes() for d in descriptors
                )
                == data * 300
            )
        finally:
            service.join_writer()


def test_live_writer_admission_has_an_independent_claim_defense(tmp_path: Path) -> None:
    with Library(tmp_path / "library") as library:
        service = RecordingService(library, {"mic": FMT}, session_id="rec", chunk_frames=480)
        service.start()
        # Deliberately violate the manager's invariant. This is not an accepted
        # operation; it proves the capture-side defense independently.
        with library._mutex:
            library._claims["rec"] = threading.get_ident() + 1
            library._exclusive_claims.add("rec")
        try:
            stamp = 1_000_000
            assert service.submit(
                PCMBlock(
                    "rec",
                    "mic",
                    service.epochs["mic"],
                    0,
                    FMT,
                    480,
                    b"\0\x01" * 480,
                    stamp,
                    stamp,
                    device_frame_position=0,
                )
            )
            deadline = time.monotonic() + 5
            while (
                not library.chunks("rec")
                and service._writer_error is None
                and time.monotonic() < deadline
            ):
                time.sleep(0.001)
            assert service._writer_error is None and service.is_live()
            assert sum(d.frame_count for d in library.chunks("rec")) == 480
        finally:
            with library._mutex:
                library._claims.pop("rec", None)
                library._exclusive_claims.discard("rec")
            service.join_writer()


class RootHoldMeter:
    """Measure outermost lock ownership, excluding contention/wait time."""

    def __init__(self, lock: Any) -> None:
        self.lock = lock
        self.local = threading.local()
        self.holds: list[float] = []
        self.management_holds: list[float] = []
        self.long_holds: list[dict[str, Any]] = []
        self.active = True

    def __enter__(self) -> RootHoldMeter:
        self.lock.acquire()
        depth = getattr(self.local, "depth", 0)
        if depth == 0:
            self.local.started = time.perf_counter()
        self.local.depth = depth + 1
        return self

    def __exit__(self, *exc: Any) -> None:
        self.local.depth -= 1
        if self.local.depth == 0 and self.active:
            elapsed = time.perf_counter() - self.local.started
            self.holds.append(elapsed)
            if threading.current_thread().name == "g04-management":
                self.management_holds.append(elapsed)
            if elapsed >= 0.05:
                self.long_holds.append(
                    {
                        "thread": threading.current_thread().name,
                        "seconds": elapsed,
                        "stack": [f"{f.name}:{f.lineno}" for f in traceback.extract_stack(limit=6)],
                    }
                )
        self.lock.release()


@pytest.mark.parametrize(
    "action",
    ["inventory", "finalize", "recover"],
    ids=["G04-F3-PERF-inventory-7200", "G04-F3-PERF-finalize-900", "G04-F3-PERF-recover-900"],
)
def test_management_never_blocks_another_recording(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
) -> None:
    """관리 작업 완료까지 측정한다(상한 300초). writer seal 지연은 G-P15 후속이다."""
    root = tmp_path / "library"
    with Library(root) as library:
        library.create_session("old")
        library.transition("old", SessionState.RECORDING, 0)
        if action == "inventory":
            for track in ("mic", "system"):
                epoch = root / "sessions" / "old" / "tracks" / track / "epoch1"
                for index in range(3600):
                    bundle = epoch / f"b{index:06d}"
                    bundle.mkdir(parents=True)
                    for name in ("audio.pcm", "blocks.jsonl", "descriptor.json"):
                        (bundle / name).write_bytes(b"x")
        else:
            # Real, independently sealed 30-minute PCM, not mocked verification.
            # Batch catalog fixture setup avoids O(n^2) registration setup costs.
            rows = []
            for index in range(900):
                stamp = 1_000_000 + index * 2_000_000_000
                sample = PCMBlock(
                    "old",
                    "mic",
                    "e1",
                    index,
                    FMT,
                    96_000,
                    b"\x10\0" * 96_000,
                    stamp,
                    stamp,
                    device_frame_position=index * 96_000,
                )
                writer = ChunkWriter(root, sample)
                writer.append(sample)
                descriptor = writer.seal()
                rows.append(
                    (
                        descriptor.chunk_id,
                        "old",
                        descriptor.relative_path,
                        json.dumps(descriptor.to_dict()),
                    )
                )
            with library._mutex, library._transaction() as connection:
                connection.executemany("INSERT INTO chunks VALUES(?,?,?,?)", rows)
        library.transition("old", SessionState.INTERRUPTED, 1)
        meter = RootHoldMeter(library._mutex)
        monkeypatch.setattr(library, "_mutex", meter)
        monkeypatch.setitem(coordination_module._roots, library.root, meter)
        service = RecordingService(library, {"mic": FMT}, session_id="rec")
        service.start()
        result: dict[str, Any] = {}
        done = threading.Event()

        def management() -> None:
            started = time.perf_counter()
            try:
                if action == "inventory":
                    entries, warnings = library.unfinished_inventory()
                    old = next(item for item in entries if item["session_id"] == "old")
                    assert old["uncatalogued_bundles"] == 7200
                    assert warnings == {"skipped_entries": 0}
                elif action == "finalize":
                    sealed = library.finalize_unfinished("old")
                    assert (sealed["chunk_count"], sealed["frame_count"]) == (900, 86_400_000)
                else:
                    recovered = library.recover_session("old")
                    assert len(recovered["verified_chunk_ids"]) == 900
                result["ok"] = True
            except BaseException as error:
                result["error"] = repr(error)
            finally:
                result["seconds"] = time.perf_counter() - started
                done.set()

        worker = threading.Thread(target=management, name="g04-management")
        epoch = service.epochs["mic"]
        rejected = 0
        index = 0
        started = time.perf_counter()
        try:
            while index < 600 or not done.is_set():
                assert time.perf_counter() - started < 300, (
                    "management exceeded the 300-second safety limit"
                )
                if index == 50:
                    worker.start()
                stamp = 1_000_000 + index * 10_000_000
                sample = PCMBlock(
                    "rec",
                    "mic",
                    epoch,
                    index,
                    FMT,
                    480,
                    b"\0\x01" * 480,
                    stamp,
                    stamp,
                    device_frame_position=index * 480,
                )
                rejected += not service.submit(sample)
                index += 1
                delay = started + index * 0.01 - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)
            worker.join(30)
        finally:
            meter.active = False
            service.stop(timeout=60)
            if worker.ident is not None:
                worker.join(60)
        health = service.health_snapshot()["tracks"]["mic"]
        measurement = {
            "action": action,
            "seconds": result["seconds"],
            "root_max_seconds": max(meter.holds),
            "management_root_max_seconds": max(meter.management_holds),
            "long_holds": meter.long_holds,
            "management_long_holds": [
                hold for hold in meter.long_holds if hold["thread"] == "g04-management"
            ],
            "rejected": rejected,
            "dropped_frames": health["dropped_frames"],
            "submitted_frames": index * 480,
            "stored_frames": sum(item.frame_count for item in library.chunks("rec")),
        }
        (tmp_path / "measurement.json").write_text(json.dumps(measurement), encoding="utf-8")
        print(json.dumps(measurement))
        assert result.get("ok"), result
        # writer seal의 긴 보유나 환경 부하로 인한 거부는 측정값으로 남긴다.
        # 관리 작업에 귀속되는 보유만 판정하며 저장 계층 전체의 유실 0은 요구하지 않는다.
        assert max(meter.management_holds) < 0.05, measurement
        assert measurement["management_long_holds"] == [], measurement


@pytest.mark.parametrize("first", ["finalize", "recover"])
@pytest.mark.parametrize("second", ["delete", "recover", "finalize", "resume"])
def test_f3_claim_competitors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    first: str,
    second: str,
) -> None:
    with Library(tmp_path / "library") as library:
        service = RecordingService(library, {"mic": FMT}, session_id="s")
        service.start()
        assert service.submit(block("s", service.epochs["mic"], 0))
        service.pause(timeout=60)
        before = originals(library.root, "s")
        entered, release = threading.Event(), threading.Event()
        original = library._require_inspection_safe
        parked = False

        def park(sid: str) -> None:
            nonlocal parked
            if not parked:
                parked = True
                entered.set()
                assert release.wait(5)
            original(sid)

        monkeypatch.setattr(library, "_require_inspection_safe", park)
        results: dict[str, Any] = {}

        def run(name: str, action: str) -> None:
            try:
                if action == "resume":
                    results[name] = service.resume()
                else:
                    method = {
                        "finalize": library.finalize_unfinished,
                        "recover": library.recover_session,
                        "delete": library.delete_session,
                    }[action]
                    results[name] = method("s")
            except BaseException as error:
                results[name] = error

        one = threading.Thread(target=run, args=("one", first))
        two = threading.Thread(target=run, args=("two", second))
        one.start()
        try:
            assert entered.wait(5)
            two.start()
            two.join(0.15)
            # Independent session work must proceed while first is parked.
            library.create_session("other")
            assert library.get_session("other").state == SessionState.CREATED
            if second in ("finalize", "recover"):
                assert two.is_alive(), "same-session operations must wait for the claim"
            elif second == "delete":
                assert not two.is_alive() and results["two"]["state"] == "DELETE_PENDING"
                assert originals(library.root, "s") == before
            else:
                assert not two.is_alive()
                assert isinstance(results["two"], StateConflict)
                assert str(results["two"]) == "SESSION_OPERATION_IN_PROGRESS"
                assert not service.is_live()
        finally:
            release.set()
            one.join(10)
            if two.ident is not None:
                two.join(10)
            if service.is_live():
                service.join_writer()
        assert not one.is_alive() and not two.is_alive()
        assert not library._claims
        assert all(originals(library.root, "s").get(k) == v for k, v in before.items())
        if second == "delete":
            assert isinstance(results["one"], StateConflict)
            assert str(results["one"]) == "DELETE_PENDING"
            assert finalized_events(library, "s") == 0
            assert library.delete_session("s")["deleted"]
        else:
            assert not isinstance(results["one"], BaseException), results
            if second in ("finalize", "recover"):
                assert not isinstance(results["two"], BaseException), results


@pytest.mark.parametrize(
    "failure", ["inspection", "commit"], ids=["G04-F3-FAIL-inspection", "G04-F3-FAIL-commit"]
)
def test_f3_failed_operation_releases_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    with _interrupted(tmp_path / "library") as library:
        original = library._event

        def fail_event(connection: Any, sid: str, kind: str, version: int) -> None:
            if kind == "FINALIZED":
                raise OSError("injected final transaction failure")
            original(connection, sid, kind, version)

        def fail_inspect(sid: str) -> None:
            raise OSError("injected inspection failure")

        with monkeypatch.context() as patch:
            if failure == "inspection":
                patch.setattr(library, "_require_inspection_safe", fail_inspect)
            else:
                patch.setattr(library, "_event", fail_event)
            with pytest.raises(OSError):
                library.finalize_unfinished("s")
        assert not library._claims
        assert finalized_events(library, "s") == 0
        assert library.finalize_unfinished("s")["state"] == "FINALIZED"
        assert finalized_events(library, "s") == 1


def test_f3_final_commit_rechecks_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _interrupted(tmp_path / "library") as library:
        library.recover_session("s")
        session = library.get_session("s")
        library.transition("s", SessionState.FINALIZING, session.state_version)
        original = library._manifest

        def stale_snapshot(sid: str) -> dict[str, Any]:
            manifest = original(sid)
            # Simulate an unexpected catalog change after verification; an
            # operation claim alone is not proof that the snapshot is current.
            with library._mutex, library._transaction() as connection:
                connection.execute(
                    "UPDATE sessions SET generation=generation+1 WHERE session_id=?", (sid,)
                )
            return manifest

        with monkeypatch.context() as patch:
            patch.setattr(library, "_manifest", stale_snapshot)
            with pytest.raises(StateConflict, match="STALE_SESSION_VERSION"):
                library.finalize_session("s")
        assert library.get_session("s").state == SessionState.FINALIZING
        assert finalized_events(library, "s") == 0 and not library._claims
        assert library.finalize_session("s")["state"] == "FINALIZED"


@pytest.mark.parametrize(
    "action",
    ["inventory", "recover", "seal"],
    ids=["G04-F3-LOCK-inventory", "G04-F3-LOCK-recover", "G04-F3-LOCK-seal"],
)
def test_f3_filesystem_work_has_no_root_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
) -> None:
    with _interrupted(tmp_path / "library") as library:
        calls: list[None] = []
        original_verify = library_module.verify_bundle
        original_inspect = library._inspect_media_path

        def verify(path: Path) -> Any:
            assert not library._mutex._is_owned(), "media verification holds capture root_mutex"
            calls.append(None)
            return original_verify(path)

        def inspect(path: Path) -> None:
            assert not library._mutex._is_owned(), "folder inspection holds capture root_mutex"
            calls.append(None)
            original_inspect(path)

        if action == "seal":
            library.recover_session("s")
            session = library.get_session("s")
            library.transition("s", SessionState.FINALIZING, session.state_version)
        monkeypatch.setattr(library_module, "verify_bundle", verify)
        monkeypatch.setattr(library, "_inspect_media_path", inspect)
        if action == "inventory":
            library.unfinished_inventory()
        elif action == "recover":
            library.recover_session("s")
        else:
            library.finalize_session("s")
        assert calls


def test_f3_manifest_projection_does_not_reject_capture_admission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _interrupted(tmp_path / "library") as library:
        library.recover_session("s")
        entered, release = threading.Event(), threading.Event()
        original = library._manifest
        results: list[Any] = []

        def park(sid: str) -> dict[str, Any]:
            result = original(sid)
            entered.set()
            assert release.wait(5)
            return result

        def project() -> None:
            try:
                results.append(library.write_manifest("s"))
            except BaseException as error:
                results.append(error)

        monkeypatch.setattr(library, "_manifest", park)
        worker = threading.Thread(target=project)
        worker.start()
        try:
            assert entered.wait(5)
            writer = ChunkWriter(library.root, block("s", "e2", 0))
            writer.append(block("s", "e2", 0))
            library.register_chunk(writer.seal())
        finally:
            release.set()
            worker.join(10)
        assert not worker.is_alive()
        assert isinstance(results[0], StateConflict) and str(results[0]) == "STALE_SESSION_VERSION"
        assert sum(item.frame_count for item in library.chunks("s")) == 16
        assert not library._claims


_CHILD = r"""
import os
import sys
import threading
from pathlib import Path

from recoryn.domain import AudioFormat, PCMBlock, SessionState
from recoryn.storage import ChunkWriter, Library

root, ready, phase = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
FMT = AudioFormat(48000, 1)
SESSION = "crashed"


def pause(session=SESSION):
    # Publish the barrier atomically so the parent never reads a half-written marker.
    temporary = ready.with_name(ready.name + ".tmp")
    temporary.write_text(session, encoding="ascii")
    os.replace(temporary, ready)
    threading.Event().wait()


def block(i, epoch="epoch1", track="mic", session=SESSION):
    return PCMBlock(session, track, epoch, i, FMT, 4, bytes([10 + i]) * 8,
                    1000 + i * 83333, 1000 + i * 83333, device_frame_position=i * 4)


library = Library(root)
if phase in ("payload_fsynced", "journal_fsynced", "bundle_published", "catalog_committed"):
    session = library.create_session(SESSION)
    library.transition(SESSION, SessionState.RECORDING, session.state_version)
    writer = ChunkWriter(root, block(0), chunk_id="crashchunk")
    if phase in ("payload_fsynced", "journal_fsynced"):
        original_fsync = os.fsync
        count = 0
        watched = "audio.pcm" if phase == "payload_fsynced" else "blocks.jsonl"

        def observed(fd):
            global count
            original_fsync(fd)
            status = os.fstat(fd)
            for candidate in root.rglob(watched):
                other = candidate.stat()
                if (other.st_dev, other.st_ino) == (status.st_dev, status.st_ino):
                    count += 1
                    if count == 3:
                        pause()
        os.fsync = observed
    for i in range(3):
        writer.append(block(i))
    descriptor = writer.seal()
    if phase == "bundle_published":
        pause()
    library.register_chunk(descriptor)
    pause()
elif phase in ("stop_finalizing", "finalized_before_manifest"):
    from recoryn.app.recording import RecordingService
    service = RecordingService(library, {"mic": FMT}, session_id=SESSION)
    service.start()
    for i in range(3):
        assert service.submit(block(i, service.epochs["mic"]))
    if phase == "stop_finalizing":
        library.finalize_session = lambda session_id: pause()
    else:
        library.write_manifest = lambda session_id: pause()
    service.stop()
elif phase in ("recovery_work", "finalize_committing"):
    session = library.create_session(SESSION)
    library.transition(SESSION, SessionState.RECORDING, session.state_version)
    writer = ChunkWriter(root, block(0), chunk_id="crashchunk")
    for i in range(3):
        writer.append(block(i))
    if phase == "recovery_work":
        writer.abort()  # the crash leftover is staging only
        original_append = ChunkWriter._append

        def append(self, item):
            original_append(self, item)
            if "recovery-work" in str(self.staging_path):
                pause()
        ChunkWriter._append = append
    else:
        library.register_chunk(writer.seal())
        library.finalize_session = lambda session_id: pause()
    library.finalize_unfinished(SESSION)
elif phase in ("device_first", "device_second"):
    from recoryn.app.desktop import DesktopRecorder, TrackSelection
    from recoryn.app.recording import RecordingError

    class Source:
        def __init__(self, fail):
            self.fail = fail
            self.running = False

        def start(self, session_id, track_id, epoch_id, submit, on_health):
            if self.fail:
                raise RuntimeError("fake device start failure")
            for i in range(3):
                submit(block(i, epoch_id, track_id, session_id))
            self.running = True
            return FMT

        def stop(self, timeout=5.0):
            self.running = False

    failing = "mic" if phase == "device_first" else "system"
    recorder = DesktopRecorder(library, lambda device, loopback: Source(device == failing))
    selections = (TrackSelection("mic", "mic", False, FMT),
                  TrackSelection("system", "system", True, FMT))
    try:
        recorder.start(selections)
    except RecordingError:
        pass
    pause(recorder.session_id)
raise RuntimeError("phase did not reach its barrier")
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


def killed(root: Path, tmp_path: Path, phase: str) -> str:
    marker = tmp_path / "ready"
    process = start_child(root, marker, _CHILD, phase)
    try:
        assert process.poll() is None
    finally:
        process.kill()
        process.communicate(timeout=10)
    assert process.returncode != 0
    return marker.read_text(encoding="ascii")


def payload(count: int) -> bytes:
    return b"".join(bytes([10 + index]) * 8 for index in range(count))


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


def originals(root: Path, session: str) -> dict[str, bytes]:
    base = root / "sessions" / session
    return {
        path.relative_to(base).as_posix(): path.read_bytes()
        for folder in ("tracks", "staging")
        if (base / folder).exists()
        for path in (base / folder).rglob("*")
        if path.is_file()
    }


def finalized_events(library: Library, session: str) -> int:
    return int(
        library._db.execute(
            "SELECT COUNT(*) FROM storage_events WHERE session_id=? AND kind='FINALIZED'",
            (session,),
        ).fetchone()[0]
    )


class FakeSTT:
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities("fake", transcription=True)

    def transcribe(self, request: Any, context: Any = None) -> STTResult:
        item = TranscriptSegment("x", request.offset_ms, request.offset_ms + 1, "x")
        return STTResult("fake", "model", (item,), True, processed_ms=1)


def transcription(library: Library, session: str) -> str:
    with ContentStore(library) as content:
        service = AIService(library, content)
        try:
            job = service.transcribe(session, FakeSTT(), config_key="stt")
            return "ACCEPTED" if isinstance(job, str) and job else "?"
        except StateConflict as error:
            return {
                "TRANSCRIPTION_REQUIRES_FINALIZED_AUDIO": "REQUIRES_FINALIZED",
                "TRANSCRIPTION_AUDIO_EMPTY": "EMPTY",
            }.get(str(error), str(error))
        finally:
            service.close()


def chain(root: Path, session: str, expected: bytes, tmp: Path, *, sealed: bool = False) -> None:
    """O1-O7 of section 4.4 on one cause; sealed means the cause already reached FINALIZED."""
    # O2 on the direct path: a user may finalize right after the crash without a separate
    # recover. Check that on a copy, so the full chain below still starts from the cause.
    direct = tmp / "direct"
    shutil.copytree(root, direct)
    with Library(direct) as copy:
        result = copy.finalize_unfinished(session)
        assert result["frame_count"] == len(expected) // 2
        assert result["already_finalized"] is sealed
        joined = b"".join(
            (direct / chunk.relative_path / "audio.pcm").read_bytes()
            for chunk in copy.chunks(session)
        )
        assert joined == expected
    with Library(root) as library:
        before = originals(root, session)
        first = library.recover_session(session)
        second = library.recover_session(session)
        assert (second["adopted"], second["recovered"], second["state"]) == (0, 0, first["state"])
        assert all(originals(root, session).get(k) == v for k, v in before.items())  # O1
        if not sealed:
            assert first["state"] in {"CREATED", "PAUSED", "INTERRUPTED"}
            with pytest.raises(ValueError, match="Only finalized"):
                _export(library, session, tmp / "early")
            assert transcription(library, session) == "REQUIRES_FINALIZED"  # O7 before
        result = library.finalize_unfinished(session)
        assert result["state"] == "FINALIZED" and result["already_finalized"] is sealed
        catalog = library.chunks(session)
        joined = b"".join(
            (root / chunk.relative_path / "audio.pcm").read_bytes() for chunk in catalog
        )
        assert joined == expected and result["frame_count"] == len(expected) // 2  # O2
        row = library._db.execute(
            "SELECT finalized_chunks,state_version,manifest_sync_pending FROM sessions "
            "WHERE session_id=?",
            (session,),
        ).fetchone()
        assert [item["chunk_id"] for item in json.loads(row[0])] == [c.chunk_id for c in catalog]
        again = library.finalize_unfinished(session)  # O4
        assert again["already_finalized"] is True
        assert tuple(
            library._db.execute(
                "SELECT finalized_chunks,state_version,manifest_sync_pending FROM sessions "
                "WHERE session_id=?",
                (session,),
            ).fetchone()
        ) == (row[0], row[1], 0)
        assert finalized_events(library, session) == 1
        exported = _export(library, session, tmp / "out")  # O6
        audio = b""
        for item in exported["files"]:
            with wave.open(str(tmp / "out" / item["file"]), "rb") as stream:
                audio += stream.readframes(stream.getnframes())
        assert audio == expected and (tmp / "out" / "export.json").is_file()
        assert transcription(library, session) == ("ACCEPTED" if expected else "EMPTY")  # O7
        third, fourth = library.recover_session(session), library.recover_session(session)
        assert third == fourth and third["state"] == "FINALIZED"  # O3 after sealing
        assert all(originals(root, session).get(k) == v for k, v in before.items())


KILLS = [
    pytest.param("payload_fsynced", 2, False, id="G04-K1-payload-fsynced"),
    pytest.param("journal_fsynced", 3, False, id="G04-K2-journal-fsynced"),
    pytest.param("bundle_published", 3, False, id="G04-K3-bundle-published"),
    pytest.param("catalog_committed", 3, False, id="G04-K4-catalog-committed"),
    pytest.param("stop_finalizing", 3, False, id="G04-K5-stop-finalizing"),
    pytest.param("finalized_before_manifest", 3, True, id="G04-K6-finalized-before-manifest"),
    pytest.param("recovery_work", 3, False, id="G04-K7-recovery-work"),
    pytest.param("finalize_committing", 3, False, id="G04-K8-finalize-committing"),
    pytest.param("device_first", 0, False, id="G04-D1-first-device-start-failure"),
    pytest.param("device_second", 3, False, id="G04-D2-second-device-start-failure"),
]
_START_STATES = {
    "payload_fsynced": "RECORDING",
    "journal_fsynced": "RECORDING",
    "bundle_published": "RECORDING",
    "catalog_committed": "RECORDING",
    "stop_finalizing": "FINALIZING",
    "finalized_before_manifest": "FINALIZED",
    "recovery_work": "RECORDING",
    "finalize_committing": "FINALIZING",
    "device_first": "PAUSED",
    "device_second": "PAUSED",
}


@pytest.mark.parametrize(("phase", "blocks", "sealed"), KILLS)
def test_killed_process_cause_chain(tmp_path: Path, phase: str, blocks: int, sealed: bool) -> None:
    root = tmp_path / "library"
    session = killed(root, tmp_path, phase)
    with Library(root) as library:
        assert library.get_session(session).state.value == _START_STATES[phase]
        if phase == "finalized_before_manifest":
            assert tuple(
                library._db.execute(
                    "SELECT manifest_sync_pending FROM sessions WHERE session_id=?", (session,)
                ).fetchone()
            ) == (1,)
        if phase == "recovery_work":
            assert list((root / "sessions" / session / "recovery-work").iterdir())
    chain(root, session, payload(blocks), tmp_path, sealed=sealed)


def _storage_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cause: str) -> int:
    root = tmp_path / "library"
    with Library(root) as library:
        if cause == "commit_denied":
            library.create_session("s")
            library.transition("s", SessionState.RECORDING, 0)
            writer = ChunkWriter(root, block("s", "e1", 0))
            for index in range(3):
                writer.append(block("s", "e1", index))
            library.register_chunk(writer.seal())
            library.transition("s", SessionState.FINALIZING, 1)
            denied = False

            def authorizer(action: int, first: Any, *rest: Any) -> int:
                nonlocal denied
                if action == sqlite3.SQLITE_TRANSACTION and first == "COMMIT" and not denied:
                    denied = True
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK

            library._db.set_authorizer(authorizer)
            with pytest.raises(sqlite3.DatabaseError):
                library.finalize_session("s")
            library._db.set_authorizer(None)
            assert library.get_session("s").state is SessionState.FINALIZING
            return 3
        frames = 1 if cause == "seal_failed" else 96_000
        service = RecordingService(library, {"mic": FMT}, session_id="s", chunk_frames=frames)
        try:
            with monkeypatch.context() as patch:
                if cause == "enospc":
                    calls = 0
                    original = chunk_module.write_all

                    def write_all(stream: Any, data: bytes) -> None:
                        nonlocal calls
                        calls += 1
                        if calls == 5:  # the third block's payload
                            raise OSError(errno.ENOSPC, "G04 injected ENOSPC")
                        original(stream, data)

                    patch.setattr(chunk_module, "write_all", write_all)
                elif cause == "seal_failed":

                    def fail_seal(writer: ChunkWriter) -> None:
                        raise OSError("G04 injected rotation seal failure")

                    patch.setattr(ChunkWriter, "seal", fail_seal)
                else:
                    original_health = library.record_capture_health

                    def fail_health(session_id: str, health: dict[str, Any]) -> None:
                        patch.setattr(library, "record_capture_health", original_health)
                        raise OSError("G04 injected health write failure")

                    patch.setattr(library, "record_capture_health", fail_health)
                service.start()
                count = 1 if cause == "seal_failed" else 3
                for index in range(count):
                    assert service.submit(block("s", service.epochs["mic"], index))
                with pytest.raises(RecordingError):
                    service.stop()
            assert library.get_session("s").state is SessionState.INTERRUPTED
            assert not service.is_live()
        finally:
            service.join_writer()
        return {"enospc": 2, "seal_failed": 1, "health_failed": 3}[cause]


FAILURES = [
    pytest.param("enospc", id="G04-F1-enospc"),
    pytest.param("seal_failed", id="G04-F2-rotation-seal-failure"),
    pytest.param("health_failed", id="G04-F3-health-write-failure"),
    pytest.param("commit_denied", id="G04-F4-finalize-commit-denied"),
]


@pytest.mark.parametrize("cause", FAILURES)
def test_storage_failure_cause_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cause: str
) -> None:
    blocks = _storage_failure(tmp_path, monkeypatch, cause)
    chain(tmp_path / "library", "s", payload(blocks), tmp_path)


def _interrupted(root: Path) -> Library:
    library = Library(root)
    library.create_session("s")
    library.transition("s", SessionState.RECORDING, 0)
    writer = ChunkWriter(root, block("s", "e1", 0))
    for index in range(2):
        writer.append(block("s", "e1", index))
    library.register_chunk(writer.seal())
    staging = ChunkWriter(root, block("s", "e1", 2))
    staging.append(block("s", "e1", 2))
    staging.abort()
    library.transition("s", SessionState.INTERRUPTED, 1)
    return library


def interleave(
    first: Callable[[], Any],
    second: Callable[[], Any],
    hold: Callable[[threading.Event, threading.Event], Callable[[], None]],
) -> tuple[Any, Any]:
    """Park first inside its session claim; second waits without holding root_mutex."""
    entered, release = threading.Event(), threading.Event()
    restore = hold(entered, release)
    results: dict[str, Any] = {}

    def run(name: str, call: Callable[[], Any]) -> None:
        try:
            results[name] = call()
        except BaseException as error:
            results[name] = error

    one = threading.Thread(target=run, args=("first", first))
    one.start()
    assert entered.wait(5)
    two = threading.Thread(target=run, args=("second", second))
    two.start()
    two.join(0.2)
    assert two.is_alive(), "the second call must wait for the first session operation"
    release.set()
    one.join(5)
    two.join(5)
    restore()
    assert not one.is_alive() and not two.is_alive()
    return results["first"], results["second"]


def hold_method(library: Library, name: str) -> Callable[..., Callable[[], None]]:
    original = getattr(library, name)

    def hold(entered: threading.Event, release: threading.Event) -> Callable[[], None]:
        parked = False

        def parked_call(*args: Any, **kwargs: Any) -> Any:
            nonlocal parked
            if not parked:
                parked = True
                entered.set()
                assert release.wait(5)
            return original(*args, **kwargs)

        setattr(library, name, parked_call)
        return lambda: setattr(library, name, original)

    return hold


H_FINALIZE = [
    pytest.param("ui-first", id="G04-H1-finalize-ui-then-cli"),
    pytest.param("cli-first", id="G04-H1-finalize-cli-then-ui"),
]


@pytest.mark.parametrize("order", H_FINALIZE)
def test_h1_two_finalizations_seal_once(tmp_path: Path, order: str) -> None:
    library = _interrupted(tmp_path / "library")
    try:
        ui = lambda: library.finalize_unfinished("s", expected_version=2)  # noqa: E731
        cli = lambda: library.finalize_unfinished("s")  # noqa: E731
        calls = (ui, cli) if order == "ui-first" else (cli, ui)
        first, second = interleave(*calls, hold_method(library, "finalize_session"))
        assert first["already_finalized"] is False and second["already_finalized"] is True
        assert finalized_events(library, "s") == 1
    finally:
        library.close()


H_RECOVER = [
    pytest.param("finalize-first", id="G04-H2-finalize-then-recover"),
    pytest.param("recover-first", id="G04-H2-recover-then-finalize"),
]


@pytest.mark.parametrize("order", H_RECOVER)
def test_h2_finalize_and_recover_linearize(tmp_path: Path, order: str) -> None:
    root = tmp_path / "library"
    library = _interrupted(root)
    try:
        before = originals(root, "s")
        finalize = lambda: library.finalize_unfinished("s")  # noqa: E731
        recover = lambda: library.recover_session("s")  # noqa: E731
        if order == "finalize-first":
            sealed, recovered = interleave(
                finalize, recover, hold_method(library, "finalize_session")
            )
            assert recovered["state"] == "FINALIZED" and recovered["recovered"] == 0
        else:
            recovered, sealed = interleave(
                recover, finalize, hold_method(library, "write_manifest")
            )
            assert recovered["recovered"] == 1 and sealed["recovery"]["recovered"] == 0
        assert sealed["state"] == "FINALIZED" and sealed["frame_count"] == 12
        assert len(library.chunks("s")) == 2
        assert all(originals(root, "s").get(k) == v for k, v in before.items())
    finally:
        library.close()


H_DELETE = [
    pytest.param("finalize-first", id="G04-H3-finalize-then-delete"),
    pytest.param("delete-first", id="G04-H3-delete-then-finalize"),
]


@pytest.mark.parametrize("order", H_DELETE)
def test_h3_finalize_and_delete_linearize(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, order: str
) -> None:
    root = tmp_path / "library"
    library = _interrupted(root)
    try:
        finalize = lambda: library.finalize_unfinished("s")  # noqa: E731
        delete = lambda: library.delete_session("s")  # noqa: E731
        if order == "finalize-first":
            entered, release = threading.Event(), threading.Event()
            restore = hold_method(library, "finalize_session")(entered, release)
            results: list[Any] = []

            def finish() -> None:
                try:
                    results.append(finalize())
                except BaseException as error:
                    results.append(error)

            worker = threading.Thread(target=finish)
            worker.start()
            try:
                assert entered.wait(5)
                before = originals(root, "s")
                deleted = delete()
                assert deleted["state"] == "DELETE_PENDING" and not deleted["deleted"]
                assert originals(root, "s") == before
            finally:
                release.set()
                worker.join(5)
                restore()
            assert not worker.is_alive()
            assert isinstance(results[0], StateConflict) and str(results[0]) == "DELETE_PENDING"
            assert finalized_events(library, "s") == 0
            deleted = delete()  # explicit retry after claim release
        else:
            original = library_module.remove_tree

            def hold(entered: threading.Event, release: threading.Event) -> Callable[[], None]:
                def parked(path: Path) -> None:
                    entered.set()
                    assert release.wait(5)
                    original(path)

                monkeypatch.setattr(library_module, "remove_tree", parked)
                return lambda: monkeypatch.setattr(library_module, "remove_tree", original)

            deleted, sealed = interleave(delete, finalize, hold)
            assert isinstance(sealed, StateConflict) and str(sealed) == "DELETE_PENDING"
        assert deleted["state"] == "DELETED_LOCAL" and deleted["deleted"] is True
        assert not (root / "sessions" / "s").exists()  # never recreated
    finally:
        library.close()


H_LIVE = [
    pytest.param("before-first-block", id="G04-H4-CE1-live-before-first-block"),
    pytest.param("writer-open", id="G04-H4-live-writer-open"),
    pytest.param("after-seal", id="G04-H4-live-after-seal"),
]


def wait_for(predicate: Callable[[], bool]) -> None:
    deadline = time.monotonic() + 5
    while not predicate():
        assert time.monotonic() < deadline, "condition not reached"
        time.sleep(0.005)


@pytest.mark.parametrize("position", H_LIVE)
def test_h4_live_recording_refuses_recovery_and_finalize(tmp_path: Path, position: str) -> None:
    """G04-CE1: recovering a live recording used to interrupt it and make stop fail."""
    root = tmp_path / "library"
    with Library(root) as library:
        frames = 4 if position == "after-seal" else 96_000
        service = RecordingService(library, {"mic": FMT}, session_id="s", chunk_frames=frames)
        try:
            service.start()
            epoch = service.epochs["mic"]
            if position != "before-first-block":
                assert service.submit(block("s", epoch, 0))
            if position == "writer-open":
                wait_for(lambda: has_active_writer(library.root, "s"))
                expected = "Live writer cannot be recovered"
            else:
                if position == "after-seal":
                    wait_for(
                        lambda: (
                            len(library.chunks("s")) == 1
                            and not has_active_writer(library.root, "s")
                        )
                    )
                expected = "SESSION_LIVE"
            with pytest.raises(StateConflict) as refused:
                library.recover_session("s")
            assert str(refused.value) == expected
            with pytest.raises(StateConflict, match="SESSION_LIVE"):
                library.finalize_unfinished("s")
            assert library.get_session("s").state is SessionState.RECORDING
            assert service.submit(block("s", epoch, 1))  # the recording continues
            assert service.stop()["state"] == "FINALIZED"
            assert sum(chunk.frame_count for chunk in library.chunks("s")) in {4, 8}
            assert len({c.chunk_id for c in library.chunks("s")}) == len(library.chunks("s"))
        finally:
            service.join_writer()


_HOLDER = r"""
import sys
import threading
from pathlib import Path
from recoryn.storage import Library
with Library(Path(sys.argv[1])):
    Path(sys.argv[2]).write_text("READY", encoding="ascii")
    threading.Event().wait()
"""


def test_h5_cli_finalize_while_another_process_holds_the_library(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "library"
    _interrupted(root).close()
    process = start_child(root, tmp_path / "held", _HOLDER)
    try:
        assert main(["--root", str(root), "finalize", "s"]) == 1
        output = json.loads(capsys.readouterr().out)
        assert output["code"] == "STATE_CONFLICT" and "message" in output
    finally:
        process.kill()
        process.communicate(timeout=10)
    with Library(root) as library:
        assert library.get_session("s").state is SessionState.INTERRUPTED
        assert finalized_events(library, "s") == 0


def test_declared_integration_denominators_are_complete_and_unique() -> None:
    chains = KILLS + FAILURES
    races = H_FINALIZE + H_RECOVER + H_DELETE + H_LIVE
    assert len(chains) == 8 + 2 + 4 == 14
    assert len(races) + 1 == 2 + 2 + 2 + 3 + 1 == 10
    ids = [case.id for case in chains + races] + ["G04-H5-cli-finalize-library-held"]
    assert len(ids) == len(set(ids)) == 24


@pytest.mark.parametrize(
    "phase", ("live", "paused-resumed", "same-owner"), ids=[f"G04-FIX-OWNER-{i}" for i in range(3)]
)
def test_another_owner_cannot_hide_a_real_recording_service(tmp_path: Path, phase: str) -> None:
    class IdleOwner:
        def is_live(self) -> bool:
            return False

    with Library(tmp_path / "library") as library:
        service = RecordingService(library, {"mic": FMT}, session_id="s")
        service.start()
        other = IdleOwner()
        try:
            if phase == "paused-resumed":
                service.pause()
            library.register_live_owner("s", service if phase == "same-owner" else other)
            if phase == "paused-resumed":
                service.resume()
            assert service.is_live()
            for operation in (library.recover_session, library.finalize_unfinished):
                with pytest.raises(StateConflict, match="SESSION_LIVE"):
                    operation("s")
            epoch = service.epochs["mic"]
            data = bytes([42]) * 8
            assert service.submit(
                PCMBlock("s", "mic", epoch, 0, FMT, 4, data, 1000, 1000, device_frame_position=0)
            )
            service.stop(timeout=60)
            assert library.get_session("s").state is SessionState.FINALIZED
            assert sum(chunk.frame_count for chunk in library.chunks("s")) == 4
            assert finalized_events(library, "s") == 1
            assert not service.is_live() and not service.worker_alive
            assert (
                b"".join(
                    (library.root / chunk.relative_path / "audio.pcm").read_bytes()
                    for chunk in library.chunks("s")
                )
                == data
            )
        finally:
            # A bad finalize mutant must not leave an actual test writer running.
            try:
                service._drain(60)
            except (StateConflict, RecordingError):
                pass
            assert not service.worker_alive
