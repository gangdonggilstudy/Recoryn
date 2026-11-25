"""G17 strict writer cases; byte patterns and state outcomes are hand-written."""

from __future__ import annotations

import errno
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from recoryn.domain import AudioFormat, PCMBlock, StateConflict, ValidationError
from recoryn.storage import ChunkWriter, chunks
from recoryn.storage import _coordination as coordination
from recoryn.storage.chunks import has_active_writer

pytestmark = pytest.mark.unit
FORMAT = AudioFormat(48000, 1)


def block(index=0, *, track="mic", session="s", epoch="e1", frames=4):
    return PCMBlock(
        session,
        track,
        epoch,
        index,
        FORMAT,
        frames,
        bytes([index % 251 + 1, 17 if track == "mic" else 29]) * frames,
        1000 + index * 10_000_000,
        1000 + index * 10_000_000,
        index * frames,
    )


class TrackedLock:
    def __init__(self, lock):
        self.lock = lock
        self.local = threading.local()
        self.holds = []
        self.intervals = []

    @property
    def owned(self):
        return getattr(self.local, "depth", 0) > 0

    def acquire(self, *args, **kwargs):
        result = self.lock.acquire(*args, **kwargs)
        if result:
            if not self.owned:
                self.local.started = time.perf_counter()
            self.local.depth = getattr(self.local, "depth", 0) + 1
        return result

    def release(self):
        self.local.depth -= 1
        if not self.owned:
            ended = time.perf_counter()
            name = threading.current_thread().name
            self.holds.append((name, ended - self.local.started))
            self.intervals.append((name, self.local.started, ended))
        self.lock.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args):
        self.release()


class Authority:
    """A fake canonical read boundary, not the expected state model."""

    def __init__(self):
        self.deleted = False
        self.unknown = False

    def check(self, session):
        if self.unknown:
            raise ValidationError("Cannot verify writer deletion intent")
        return self.deleted


class IOTrace:
    def __init__(self, root, monkeypatch, *, durable=True, library=None):
        self.root = root
        self.events = []
        self.paths = {}
        self.sync_hook = None
        self.write_hook = None
        self.open_hook = None
        self.durable = durable
        self.original_sync = chunks.sync
        self.original_write = chunks.write_all
        self.original_open = chunks.open_file
        self.mutex = TrackedLock(coordination.root_mutex(root))
        self.registry = TrackedLock(chunks._writers_lock)
        self.coordination = TrackedLock(coordination._guard)
        monkeypatch.setitem(coordination._roots, root, self.mutex)
        if library is not None:
            monkeypatch.setattr(library, "_mutex", self.mutex)
        monkeypatch.setattr(chunks, "_writers_lock", self.registry)
        monkeypatch.setattr(coordination, "_guard", self.coordination)
        monkeypatch.setattr(chunks, "open_file", self.open)
        monkeypatch.setattr(chunks, "write_all", self.write)
        monkeypatch.setattr(chunks, "sync", self.sync)

    def open(self, path, mode):
        if mode == "xb":
            assert self.mutex.owned, ("unguarded create", path)
            self.events.append(("create", Path(path).name))
            if self.open_hook is not None:
                self.open_hook(Path(path))
        stream = self.original_open(path, mode)
        self.paths[id(stream)] = Path(path)
        return stream

    def write(self, stream, data):
        path = self.paths[id(stream)]
        assert self.mutex.owned, ("unguarded bytes", path)
        self.events.append(("write", path.name))
        if self.write_hook is not None:
            return self.write_hook(path, stream, data)
        return self.original_write(stream, data)

    def sync(self, stream):
        path = self.paths[id(stream)]
        assert not self.mutex.owned, ("root held during sync", path)
        assert not self.registry.owned and not self.coordination.owned
        self.events.append(("sync_begin", path.name))
        if self.sync_hook is not None:
            self.sync_hook("before", path, stream)
        if self.durable:
            self.original_sync(stream)
        self.events.append(("sync_done", path.name))
        if self.sync_hook is not None:
            self.sync_hook("after", path, stream)


class Harness:
    def __init__(self, root, monkeypatch, *, durable=True):
        self.root = root
        self.authority = Authority()
        coordination.register_intent_check(root, self.authority.check)
        self.io = IOTrace(root, monkeypatch, durable=durable)
        self.writers = []

    def writer(self, *, track="mic", chunk=None):
        writer = ChunkWriter(self.root, block(track=track), chunk)
        writer._operation_lock = OperationProbe(writer._operation_lock, self.io)
        self.writers.append(writer)
        return writer

    def close(self):
        for writer in self.writers:
            writer.unhold()
            writer.abort()
        coordination.unregister_intent_check(self.root, self.authority.check)


class OperationProbe:
    def __init__(self, lock, io):
        self.lock, self.io = lock, io

    def acquire(self, *args, **kwargs):
        assert not self.io.mutex.owned, "writer operation wait under root"
        assert not self.io.registry.owned and not self.io.coordination.owned
        return self.lock.acquire(*args, **kwargs)

    def release(self):
        self.lock.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args):
        self.release()


@pytest.fixture
def harness(tmp_path, monkeypatch):
    value = Harness(tmp_path, monkeypatch)
    try:
        yield value
    finally:
        value.close()


def start_action(action, name="g17-operation"):
    result, error, done = [], [], threading.Event()

    def run():
        try:
            result.append(action())
        except BaseException as failure:
            error.append(failure)
        finally:
            done.set()

    thread = threading.Thread(target=run, name=name)
    thread.start()
    return thread, done, result, error


# This table is independent of ChunkWriter's fields/transitions.
STATES = (
    "NEW",
    "OPEN_IDLE",
    "OPEN_SYNCING",
    "SEALING_SYNCING",
    "SEALED_WAIT_REGISTER",
    "PUBLISHED_RELEASED",
    "ABORTED_DRAINING",
    "FAILED_DRAINING",
)
COMMANDS = ("append", "sync", "seal", "abort")
EXPECTED = {
    "NEW": (True, True, False, True),
    "OPEN_IDLE": (True, True, True, True),
    "OPEN_SYNCING": (True, True, True, True),
    "SEALING_SYNCING": (False, True, False, True),
    "SEALED_WAIT_REGISTER": (False, True, False, True),
    "PUBLISHED_RELEASED": (False, True, False, True),
    "ABORTED_DRAINING": (False, False, False, True),
    "FAILED_DRAINING": (False, False, False, True),
}
W = [(state, command) for state in STATES for command in COMMANDS]


@pytest.mark.parametrize("state,command", W, ids=[f"G17-W-{i:03}" for i in range(1, 33)])
def test_strict_writer_state_and_sync_handle_lifetime(harness, monkeypatch, state, command):
    h = harness
    writer = h.writer()
    ready, release = threading.Event(), threading.Event()
    background = []
    if state != "NEW":
        writer.append(block())
    if state in {"OPEN_SYNCING", "SEALING_SYNCING", "ABORTED_DRAINING"}:

        def park(phase, path, stream):
            if phase == "before" and path.name == "audio.pcm":
                ready.set()
                assert release.wait(10)

        h.io.sync_hook = park
        operation = (
            writer.seal_chunk if state == "SEALING_SYNCING" else lambda: writer.append(block(1))
        )
        background.append(start_action(operation))
        assert ready.wait(5)
    if state == "ABORTED_DRAINING":
        attempting = threading.Event()
        original_lock = writer._operation_lock

        class AbortLock:
            def __enter__(self):
                if threading.current_thread().name == "g17-abort":
                    attempting.set()
                original_lock.acquire()

            def __exit__(self, *args):
                original_lock.release()

        monkeypatch.setattr(writer, "_operation_lock", AbortLock())
        background.append(start_action(writer.abort, "g17-abort"))
        assert attempting.wait(5) and writer._closing
    elif state == "FAILED_DRAINING":
        close_files = writer._close_files

        def failed_sync(phase, path, stream):
            raise OSError("g17-sync-error")

        def closing():
            ready.set()
            assert release.wait(10)
            close_files()

        h.io.sync_hook = failed_sync
        monkeypatch.setattr(writer, "_close_files", closing)
        background.append(start_action(lambda: writer.append(block(1))))
        assert ready.wait(5) and writer._failed
    elif state in {"SEALED_WAIT_REGISTER", "PUBLISHED_RELEASED"}:
        capability = writer.seal_chunk()
        if state == "PUBLISHED_RELEASED":
            capability.release()
    if state in {"OPEN_SYNCING", "SEALING_SYNCING", "ABORTED_DRAINING"}:
        close_files = writer._close_files

        def confirmed_close():
            assert release.is_set(), "a syncing handle was closed before its ACK"
            assert not h.io.mutex.owned and not h.io.registry.owned
            close_files()

        monkeypatch.setattr(writer, "_close_files", confirmed_close)
    observed = None
    try:
        if background:
            assert has_active_writer(h.root, "s")
            # This is the independent deletion/control lane; it must not wait for sync.
            with h.io.mutex:
                assert not h.io.registry.owned
        index = 0 if state == "NEW" else 2 if state == "OPEN_SYNCING" else 1
        action = {
            "append": lambda: writer.append(block(index)),
            "sync": writer._sync,
            "seal": writer.seal_chunk,
            "abort": writer.abort,
        }[command]
        attempted = threading.Event()
        previous_lock = writer._operation_lock

        class ObservedLock:
            def __enter__(self):
                if threading.current_thread().name == "g17-command":
                    attempted.set()
                previous_lock.__enter__()
                return self

            def __exit__(self, *args):
                previous_lock.__exit__(*args)

        monkeypatch.setattr(writer, "_operation_lock", ObservedLock())
        observed = start_action(action, "g17-command")
        if background:
            deadline = time.monotonic() + 5
            # A real operation must either attempt serialization or finish. Keep
            # sync parked until then; early-close mutants cannot win a scheduler race.
            while not attempted.is_set() and not observed[1].is_set():
                assert time.monotonic() < deadline
                time.sleep(0.001)
        release.set()
        observed[0].join(5)
        assert not observed[0].is_alive()
        expected = EXPECTED[state][COMMANDS.index(command)]
        assert (not observed[3]) is expected
        if not expected:
            assert isinstance(observed[3][0], ValueError)
        if expected and command == "abort":
            assert not has_active_writer(h.root, "s")
        if expected and command == "append":
            data = (writer.staging_path / "audio.pcm").read_bytes()
            payloads = [block(i).payload for i in range(index + 1)]
            assert data == b"".join(payloads)
        if expected and command == "seal":
            cap = observed[2][0]
            assert cap.descriptor.frame_count == (8 if state == "OPEN_SYNCING" else 4)
            cap.release()
    finally:
        release.set()
        for entry in background + ([observed] if observed is not None else []):
            entry[0].join(10)
            assert not entry[0].is_alive()
        h.io.sync_hook = None


def test_unhold_during_readback_keeps_the_inflight_seal_active(harness, monkeypatch):
    """G17-X-01: closed FileIO is not an ACK of the still-running verification."""
    h = harness
    writer = h.writer()
    writer.append(block())
    writer.hold()
    entered, release = threading.Event(), threading.Event()
    original = chunks._verified

    def verifying(*args):
        entered.set()
        assert release.wait(5)
        return original(*args)

    monkeypatch.setattr(chunks, "_verified", verifying)
    worker = start_action(writer.seal)
    try:
        assert entered.wait(5)
        writer.unhold()
        assert has_active_writer(h.root, "s")
        release.set()
        worker[0].join(5)
        assert not worker[0].is_alive() and worker[3] == []
        assert not has_active_writer(h.root, "s")
        assert (writer.path / "audio.pcm").read_bytes() == block().payload
    finally:
        release.set()
        worker[0].join(5)


def test_libraryless_writer_does_not_wait_for_a_sqlite_read_lock(tmp_path):
    """G17-X-02: missing authority cannot turn a root-held check into a busy wait."""
    connection = sqlite3.connect(tmp_path / "library.sqlite")
    writer = ChunkWriter(tmp_path, block(), "blocked-read")
    try:
        connection.execute("PRAGMA user_version=1")
        connection.execute("CREATE TABLE deleted_sessions(session_id TEXT, generation INTEGER)")
        connection.commit()
        connection.execute("BEGIN EXCLUSIVE")
        started = time.monotonic()
        with pytest.raises(ValidationError, match="Cannot verify writer deletion generation"):
            writer.append(block())
        assert time.monotonic() - started < 0.5
        assert not writer.staging_path.exists() and not writer.path.exists()
        assert not has_active_writer(tmp_path, "s")
    finally:
        writer.abort()
        connection.rollback()
        connection.close()


def test_refused_admission_keeps_the_previously_confirmed_prefix(harness):
    """G17-X-03: no attempted bytes means authority repair can seal the old cut."""
    writer = harness.writer()
    writer.append(block())
    before = {p.name: p.read_bytes() for p in writer.staging_path.iterdir()}
    harness.authority.unknown = True
    harness.io.events.clear()
    with pytest.raises(ValidationError, match="Cannot verify writer deletion intent"):
        writer.append(block(1))
    assert harness.io.events == []
    assert has_active_writer(harness.root, "s")
    assert {p.name: p.read_bytes() for p in writer.staging_path.iterdir()} == before
    harness.authority.unknown = False
    descriptor = writer.seal()
    assert descriptor.frame_count == 4 and descriptor.block_count == 1
    assert (writer.path / "audio.pcm").read_bytes() == block().payload


def test_sync_failure_keeps_its_primary_error_when_close_also_fails(harness, monkeypatch):
    """G17-X-04: cleanup cannot replace ENOSPC with a secondary close error."""
    writer = harness.writer()
    writer.append(block())
    close = writer._close_files

    def close_then_fail():
        close()
        raise OSError(errno.EBADF, "secondary close failure")

    def no_space(phase, path, stream):
        if phase == "before":
            raise OSError(errno.ENOSPC, "primary sync failure")

    monkeypatch.setattr(writer, "_close_files", close_then_fail)
    harness.io.sync_hook = no_space
    with pytest.raises(OSError) as caught:
        writer.append(block(1))
    assert caught.value.errno == errno.ENOSPC
    assert writer._count == 1 and writer._frames == 4
    assert not has_active_writer(harness.root, "s")
    assert (writer.staging_path / "audio.pcm").read_bytes() == block().payload + block(1).payload
    assert len((writer.staging_path / "blocks.jsonl").read_bytes().splitlines()) == 1
    assert not writer.path.exists()
    monkeypatch.setattr(writer, "_close_files", close)


@pytest.mark.parametrize(
    "opened", (True, False), ids=["G17-F1-COST-open", "G17-F1-COST-standalone"]
)
def test_append_checks_full_authority_once_and_never_caches_across_blocks(
    tmp_path, monkeypatch, opened
):
    from recoryn.storage import Library

    library = Library(tmp_path) if opened else None
    if library is not None:
        library.create_session("s")
    original, calls = chunks.check_write_allowed, []

    def checked(root, session):
        calls.append(session)
        return original(root, session)

    monkeypatch.setattr(chunks, "check_write_allowed", checked)
    writer = ChunkWriter(tmp_path, block(), "cost")
    try:
        writer.append(block())
        calls.clear()
        for index in range(1, 5):
            writer.append(block(index))
        assert calls == ["s"] * (4 if opened else 12)
        assert writer._frames == 20 and writer._count == 5
        assert (writer.staging_path / "audio.pcm").read_bytes() == b"".join(
            block(i).payload for i in range(5)
        )
    finally:
        writer.abort()
        if library is not None:
            library.close()


@pytest.mark.parametrize(
    "fault",
    ("permission", "sharing", "locked", "io", "invalid"),
    ids=[f"G17-F1-READ-{x}" for x in ("permission", "sharing", "locked", "io", "invalid")],
)
@pytest.mark.parametrize("expires", (False, True), ids=["clears", "expires"])
def test_read_retry_is_bounded_specific_and_preserves_primary_exception(
    monkeypatch, fault, expires
):
    clock, calls, waits = [0.0], [], []
    error = (
        PermissionError("temporary")
        if fault == "permission"
        else (
            ValidationError("bad digest")
            if fault == "invalid"
            else OSError(errno.EIO, "read fault")
        )
    )
    if fault in {"sharing", "locked"}:
        error.winerror = 32 if fault == "sharing" else 33
    monkeypatch.setattr(coordination, "_read_clock", lambda: clock[0])

    def wait(seconds):
        assert 0 < seconds <= 0.01
        assert clock[0] < 1.0, "sealed read retry exceeded its one-second budget"
        waits.append(seconds)
        clock[0] += 0.5

    def operation():
        calls.append(1)
        if expires or len(calls) == 1:
            raise error
        return b"verified bytes"

    monkeypatch.setattr(coordination, "_read_wait", wait)
    retryable = fault in {"permission", "sharing", "locked"}
    if retryable and not expires:
        assert coordination.retry_sealed_read(operation) == b"verified bytes"
        assert len(calls) == 2 and len(waits) == 1
    else:
        with pytest.raises(type(error)) as caught:
            coordination.retry_sealed_read(operation)
        assert caught.value is error
        assert len(calls) == (3 if retryable else 1)
        assert len(waits) == (2 if retryable else 0)


def test_continuation_owner_close_cannot_reuse_an_open_library_receipt(tmp_path):
    """G17-F1-OWNER: a new/closed authority cannot share an old integer receipt."""
    from recoryn.storage import Library

    with Library(tmp_path) as library:
        library.create_session("s")
        token = coordination.write_generation(library.root)
        assert token is not None
    assert coordination.write_generation(tmp_path) is None
    assert library._append_generation() is None
    with Library(tmp_path) as replacement:
        assert coordination.write_generation(replacement.root) != token
        replacement._publish_intent("s", 1)
        writer = ChunkWriter(replacement.root, block())
        with pytest.raises(StateConflict, match="deletion intent"):
            with coordination.root_mutex(replacement.root):
                writer._check_media_continuation(token)
        assert not writer.staging_path.exists()


@pytest.mark.parametrize(
    "at", ("audio.pcm", "blocks.jsonl"), ids=["G17-F1-CLOSE-payload", "G17-F1-CLOSE-journal"]
)
def test_fast_continuation_still_rejects_closing_after_each_sync(tmp_path, monkeypatch, at):
    from recoryn.storage import Library

    with Library(tmp_path) as library:
        library.create_session("s")
        trace = IOTrace(library.root, monkeypatch, library=library)
        writer = ChunkWriter(library.root, block(), "closing")
        writer.append(block())

        def close_during_sync(phase, path, stream):
            if phase == "after" and path.name == at:
                writer._closing = True

        trace.sync_hook = close_during_sync
        try:
            with pytest.raises(ValueError, match="Writer is closing"):
                writer.append(block(1))
            assert writer._count == 1 and writer._frames == 4
            assert (writer.staging_path / "audio.pcm").read_bytes() == block().payload + block(
                1
            ).payload
            lines = (writer.staging_path / "blocks.jsonl").read_bytes().splitlines()
            assert len(lines) == (1 if at == "audio.pcm" else 2)
            assert not writer.path.exists()
        finally:
            trace.sync_hook = None
            writer.abort()


def test_published_capability_release_still_waits_for_the_seal_exit(tmp_path, monkeypatch):
    """G17-F2-A4: publication ACK cannot release a still-running seal's fence."""
    from recoryn.storage import Library

    with Library(tmp_path) as library:
        library.create_session("s")
        writer = ChunkWriter(library.root, block(), "handoff")
        writer.hold()
        writer.append(block())
        original = chunks._writers_lock
        entered, proceed = threading.Event(), threading.Event()
        results, errors = [], []

        class RegistryBarrier:
            def __enter__(self):
                if (
                    threading.current_thread().name == "g17-final-exit"
                    and writer._capability is not None
                    and writer._seal_in_progress
                ):
                    assert not library._mutex._is_owned()
                    entered.set()
                    assert proceed.wait(10), "seal exit was not released"
                original.acquire()
                return self

            def __exit__(self, *args):
                original.release()

        monkeypatch.setattr(chunks, "_writers_lock", RegistryBarrier())

        def seal():
            try:
                results.append(writer.seal_chunk())
            except BaseException as error:
                errors.append(error)

        worker = threading.Thread(target=seal, name="g17-final-exit")
        worker.start()
        try:
            assert entered.wait(10), "seal did not reach its published exit"
            capability = writer.capability
            assert capability is not None
            capability.release()
            # No independent hold remains; only the in-flight seal owns this ACK.
            assert writer._sealing is False and writer._seal_in_progress is True
            assert chunks.has_active_writer(library.root, "s")
            assert library.delete_session("s")["state"] == "DELETE_PENDING"
            assert writer.path.exists()
        finally:
            proceed.set()
            worker.join(10)
            writer.unhold()
            writer.abort()
        assert not worker.is_alive() and not errors and len(results) == 1
        assert not chunks.has_active_writer(library.root, "s")
