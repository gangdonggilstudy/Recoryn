"""GS02 hand-written authority, observation-age and filesystem oracles."""

import json
import os
import threading
from dataclasses import fields
from itertools import product
from pathlib import Path
from types import SimpleNamespace

import pytest

from recoryn.domain import StateConflict, ValidationError
from recoryn.storage import Library
from recoryn.storage import library as module

pytestmark = pytest.mark.unit
T = 2_500_000_000  # literal boundary from the approved contract, not the product helper
BASE = 50_000_000_000
CANARY = "secret-body-and-path-canary"
FAULTS = ("json", "schema", "name", "tmp", "permission", "unsafe")
STATES = ("valid", "failed_settled", "failed_unsettled")


def intent(sid):
    return {"schema_version": 1, "session_id": sid, "generation": 1, "state": "DELETE_REQUESTED"}


def stamp(library, ns=BASE):
    os.utime(library.root / "deletion-journal", ns=(ns, ns))
    assert (library.root / "deletion-journal").stat().st_mtime_ns == ns


def repair(library):
    for name in ("ext.json", "rogue.txt", ".tmp-pending"):
        (library.root / "deletion-journal" / name).unlink(missing_ok=True)
    stamp(library)


def fault(library, monkeypatch, kind):
    directory = library.root / "deletion-journal"
    path = directory / "ext.json"
    if kind == "json":
        path.write_text(CANARY, encoding="utf-8")
    elif kind == "schema":
        path.write_text(json.dumps({**intent("ext"), "schema_version": 99}), encoding="utf-8")
    elif kind == "name":
        (directory / "rogue.txt").write_text(CANARY, encoding="utf-8")
    elif kind == "tmp":
        (directory / ".tmp-pending").write_text(CANARY, encoding="utf-8")
    elif kind == "unsafe":
        external = library.root.parent / "external.json"
        external.write_text(json.dumps(intent("ext")), encoding="utf-8")
        os.link(external, path)
    else:
        path.write_text(json.dumps(intent("ext")), encoding="utf-8")
        read = module.read_json

        def denied(entry, **kwargs):
            if entry == path:
                raise PermissionError(CANARY)
            return read(entry, **kwargs)

        monkeypatch.setattr(module, "read_json", denied)
    stamp(library)


@pytest.fixture
def env(tmp_path, monkeypatch):
    with Library(tmp_path / "library") as library:
        library.create_session("s")
        clock = SimpleNamespace(now=BASE + 10 * T)
        monkeypatch.setattr(module, "time", SimpleNamespace(time_ns=lambda: clock.now))
        stamp(library)
        yield library, clock


def consume(library, kind):
    try:
        if kind == "job":
            with Library.job_authority(library.db_path, "s") as state:
                return state
        if kind == "writer":
            return "DELETED" if library._writer_intent("s") else "VALID"
        if kind == "chunks":
            library.chunks("s")
        else:
            library.get_session("s")
        return "VALID"
    except ValidationError as error:
        assert error.args == ("DELETION_HISTORY_UNAVAILABLE",) or kind == "writer"
        assert CANARY not in str(error)
        return "HISTORY_UNAVAILABLE"
    except StateConflict:
        return "DELETED"


def prepare(library, clock, state):
    clock.now = BASE + (T - 1 if state == "failed_unsettled" else 10 * T)
    if state != "valid":
        (library.root / "deletion-journal/ext.json").write_text(CANARY, encoding="utf-8")
        stamp(library)
    with library._mutex:
        if state == "valid":
            library._refresh_intent_index()
        else:
            with pytest.raises(ValidationError, match="DELETION_HISTORY_UNAVAILABLE"):
                library._refresh_intent_index()


J = list(
    product((-1, T - 1, T, T + 1, 10 * T), (0, T + 1), (False, True), ("none", "stamp", "version"))
)


@pytest.mark.parametrize("age,delay,reuse,change", J, ids=[f"GS02-J-{n:03}" for n in range(1, 61)])
def test_observation_uses_start_age_and_rejects_changed_authority(
    env, monkeypatch, age, delay, reuse, change
):
    library, clock = env
    clock.now = BASE + age
    with library._mutex:
        library._refresh_intent_index()
    if not reuse:
        library._intent_journal = None
    read = library._read_journal

    def delayed():
        answer = read()
        clock.now += delay
        return answer

    monkeypatch.setattr(library, "_read_journal", delayed)
    observed = library._journal_prefetch(fresh=not reuse)
    assert observed.started_ns == BASE + age
    assert observed.settled is (age in (T + 1, 10 * T))
    if change == "stamp":
        stamp(library, BASE + 1000)
    elif change == "version":
        library._history_version += 1
    with library._mutex:
        assert library._accept_observation(observed) is (change == "none")
    assert library._db.execute("SELECT count(*) FROM deleted_sessions").fetchone()[0] == 0


N = list(product(FAULTS, (False, True), ("get_session", "chunks"), (1, 2, 20)))


@pytest.mark.parametrize(
    "cause,settled,kind,repeats", N, ids=[f"GS02-N-{n:03}" for n in range(1, 73)]
)
def test_failure_memo_is_closed_and_only_content_reads_are_hot(
    env, monkeypatch, cause, settled, kind, repeats
):
    library, clock = env
    clock.now = BASE + (10 * T if settled else T - 1)
    fault(library, monkeypatch, cause)
    read, calls = library._read_journal, []

    def counted():
        calls.append(1)
        return read()

    monkeypatch.setattr(library, "_read_journal", counted)
    before = list(library._db.execute("SELECT * FROM sessions"))
    for _ in range(repeats):
        assert consume(library, kind) == "HISTORY_UNAVAILABLE"
    assert len(calls) == (repeats if cause == "permission" else 1)
    assert list(library._db.execute("SELECT * FROM sessions")) == before
    memo = library._intent_failure
    if cause == "permission":
        assert memo is None
        return
    assert memo is not None and memo.journal is None and memo.content_failure
    assert memo.names == frozenset(
        {"rogue.txt" if cause == "name" else ".tmp-pending" if cause == "tmp" else "ext.json"}
    )
    assert CANARY not in repr(memo)
    assert {f.name for f in fields(memo)} == {
        "version",
        "epoch",
        "stamp",
        "started_ns",
        "journal",
        "names",
        "settled",
        "content_failure",
    }
    assert all(not isinstance(getattr(memo, f.name), BaseException) for f in fields(memo))


@pytest.mark.parametrize(
    "age", (-1, T - 1, T, T + 1, 10 * T), ids=[f"GS02-X-AGE-{n}" for n in range(1, 6)]
)
def test_failed_observation_does_not_settle_using_its_completion_time(env, monkeypatch, age):
    library, clock = env
    clock.now = BASE + age
    fault(library, monkeypatch, "json")
    read = library._read_journal

    def slow_failure():
        try:
            return read()
        finally:
            clock.now += T + 1

    monkeypatch.setattr(library, "_read_journal", slow_failure)
    assert consume(library, "read") == "HISTORY_UNAVAILABLE"
    assert library._intent_failure.settled is (age in (T + 1, 10 * T))


@pytest.mark.parametrize(
    "error", (ValueError, OSError, RuntimeError), ids=[f"GS02-X-CONTEXT-{n}" for n in range(1, 4)]
)
def test_authority_never_catches_the_callers_transaction_error(env, monkeypatch, error):
    library, clock = env
    read = library._journal_prefetch

    def close_after_read():
        observed = read()
        library.close()
        return observed

    monkeypatch.setattr(library, "_journal_prefetch", close_after_read)
    original = error("caller transaction failed")
    with pytest.raises(error) as caught, Library.job_authority(library.db_path, "s") as state:
        assert state == "HISTORY_UNAVAILABLE"
        raise original
    assert caught.value is original


@pytest.mark.parametrize(
    "invalid", ("closed", "missing", "future"), ids=[f"GS02-X-AUTH-{n}" for n in range(1, 4)]
)
def test_invalid_observation_context_cannot_be_published(env, invalid):
    from dataclasses import replace

    library, clock = env
    observed = library._journal_prefetch(fresh=True)
    published = library._published_observation
    if invalid == "closed":
        library.close()
    elif invalid == "missing":
        library._missing_deletion_history = True
    else:
        observed = replace(observed, epoch=library._observation_epoch + 1)
    with library._mutex:
        assert library._accept_observation(observed) is False
    if invalid != "closed":
        assert library._published_observation == published


@pytest.mark.parametrize(
    "order",
    ("valid_valid", "valid_failed", "failed_valid"),
    ids=[f"GS02-X-FRESH-{n}" for n in range(1, 4)],
)
def test_superseded_fresh_read_does_not_repeat_body_io_under_root(env, monkeypatch, order):
    library, clock = env
    if order == "failed_valid":
        fault(library, monkeypatch, "json")
    earlier = library._journal_prefetch(fresh=True)
    if order == "valid_failed":
        fault(library, monkeypatch, "json")
    else:
        repair(library)
    newer = library._journal_prefetch(fresh=True)
    with library._mutex:
        assert library._accept_observation(newer)

    def forbidden():
        raise AssertionError("superseded completed preflight re-read under root")

    monkeypatch.setattr(library, "_read_journal", forbidden)
    with library._mutex:
        if order == "valid_failed":
            with pytest.raises(ValidationError, match="DELETION_HISTORY_UNAVAILABLE"):
                library._deletion_history(earlier)
        else:
            assert library._deletion_history(earlier) == ({}, {})
    assert library._published_observation == newer.epoch


INVALIDATIONS = list(
    product(
        ("same", "stamp", "version", "same_tick", "repair", "reopen", "late"),
        STATES,
        ("read", "job"),
    )
)


@pytest.mark.parametrize(
    "event,state,kind", INVALIDATIONS, ids=[f"GS02-I-{n:03}" for n in range(1, 43)]
)
def test_invalidation_repair_and_reverse_publication(env, event, state, kind):
    library, clock = env
    prepare(library, clock, state)
    if event == "same":
        assert consume(library, kind) == ("VALID" if state == "valid" else "HISTORY_UNAVAILABLE")
    elif event in ("stamp", "version", "same_tick"):
        if event == "same_tick" and state == "valid":
            clock.now = BASE + T - 1
            library._intent_settled = False
        repair(library)
        if event == "version":
            with library._mutex:
                library._publish_intent("s", 1)
        else:
            (library.root / "deletion-journal/s.json").write_text(
                json.dumps(intent("s")), encoding="utf-8"
            )
            stamp(library, BASE if event == "same_tick" else BASE + 1000)
        result = consume(library, kind)
        if event == "same_tick" and state == "failed_settled":
            assert result == "HISTORY_UNAVAILABLE"
        else:
            assert result == ("JOURNAL_ONLY" if kind == "job" else "DELETED")
    elif event == "repair":
        if state == "valid":
            (library.root / "deletion-journal/ext.json").write_text(CANARY, encoding="utf-8")
            stamp(library)
            with pytest.raises(ValidationError, match="DELETION_HISTORY_UNAVAILABLE"):
                library.list_sessions()
        repair(library)
        assert [s.session_id for s in library.list_sessions()] == ["s"]
        assert library._intent_failure is None
        assert consume(library, kind) == "VALID"
    elif event == "reopen":
        root = library.root
        previous = library._intent_failure
        library.close()
        assert library._intent_failure is None
        with Library(root) as reopened:
            assert reopened._intent_failure is not previous or previous is None
            assert consume(reopened, kind) == (
                "VALID" if state == "valid" else "HISTORY_UNAVAILABLE"
            )
    else:
        old = library._journal_prefetch(fresh=True)
        repair(library)
        assert [s.session_id for s in library.list_sessions()] == ["s"]
        with library._mutex:
            assert library._accept_observation(old) is False
        assert consume(library, kind) == "VALID"


class Meter:
    def __init__(self, lock):
        self.lock = lock
        self.local = threading.local()
        self.events = []

    def __enter__(self):
        self.lock.acquire()
        self.local.depth = getattr(self.local, "depth", 0) + 1
        return self

    def __exit__(self, *args):
        self.local.depth -= 1
        self.lock.release()

    def note(self, kind, path):
        if getattr(self.local, "depth", 0):
            self.events.append((kind, Path(path)))


L = list(
    product(
        ("get_session", "chunks", "job", "writer"),
        ("settled", "unsettled", "changed"),
        ("normal", "name", "tmp"),
    )
)


@pytest.mark.parametrize("kind,age,entry", L, ids=[f"GS02-L-{n:03}" for n in range(1, 37)])
def test_root_filesystem_exception_is_names_of_exact_journal_only(
    env, monkeypatch, kind, age, entry
):
    library, clock = env
    if entry == "normal":
        (library.root / "deletion-journal/ext.json").write_text(
            json.dumps(intent("ext")), encoding="utf-8"
        )
        stamp(library)
    else:
        fault(library, monkeypatch, entry)
    clock.now = BASE + (T - 1 if age == "unsettled" else 10 * T)
    with library._mutex:
        try:
            library._refresh_intent_index()
        except ValidationError:
            pass
    if age == "changed":
        stamp(library, BASE + 1000)
    (library.root / "sessions").mkdir(exist_ok=True)
    meter = Meter(library._mutex)
    monkeypatch.setattr(library, "_mutex", meter)
    for owner, name, index in (
        (Path, "iterdir", 0),
        (os, "scandir", 0),
        (os, "listdir", 0),
        (module, "read_json", 0),
        (Path, "is_file", 0),
    ):
        original = getattr(owner, name)

        def watched(*args, original=original, name=name, index=index, **kwargs):
            meter.note(name, args[index])
            return original(*args, **kwargs)

        monkeypatch.setattr(owner, name, watched)
    result = consume(library, kind)
    if kind == "writer":
        assert result == ("HISTORY_UNAVAILABLE" if entry == "tmp" else "VALID")
    else:
        assert result == ("VALID" if entry == "normal" else "HISTORY_UNAVAILABLE")
    if kind == "job":
        assert meter.events == []  # Job never borrows _live's names-only mutex exception.
    cold = kind in ("get_session", "chunks") and age == "changed"
    if not cold:
        assert all(
            operation in {"iterdir", "scandir", "listdir"}
            and path == library.root / "deletion-journal"
            for operation, path in meter.events
        )
    else:
        assert any(operation == "iterdir" for operation, path in meter.events)
        assert all(
            path == library.root / "deletion-journal"
            if operation in {"iterdir", "scandir", "listdir"}
            else path.parent == library.root / "deletion-journal"
            for operation, path in meter.events
        )
    # Independent negative control: an unrelated path cannot inherit the exception.
    with library._mutex:
        list((library.root / "sessions").iterdir())
    assert any(path != library.root / "deletion-journal" for operation, path in meter.events)


IO = list(product((PermissionError, OSError), (T - 1, 10 * T), ("read", "chunks", "job")))


@pytest.mark.parametrize("error,age,kind", IO, ids=[f"GS02-F1-IO-{i:02}" for i in range(1, 13)])
def test_transient_read_error_recovers_on_next_call_without_management_refresh(
    env, monkeypatch, error, age, kind
):
    library, clock = env
    clock.now = BASE + age
    library._intent_journal = None
    original, reads = library._read_journal, []

    def once():
        reads.append(1)
        if len(reads) == 1:
            raise error(CANARY)
        return original()

    monkeypatch.setattr(library, "_read_journal", once)
    assert consume(library, kind) == "HISTORY_UNAVAILABLE"
    assert library._intent_failure is None
    assert consume(library, kind) == "VALID"
    assert len(reads) == 2
    assert library.get_session("s").session_id == "s"


NAMES = list(product(("same", "add", "remove", "stamp"), (T - 1, T, -1), ("read", "job")))


@pytest.mark.parametrize(
    "event,age,kind", NAMES, ids=[f"GS02-F1-NAMES-{i:02}" for i in range(1, 25)]
)
def test_unsettled_content_failure_requires_the_same_names_but_never_reuses_future_mtime(
    env, monkeypatch, event, age, kind
):
    library, clock = env
    clock.now = BASE + age
    fault(library, monkeypatch, "json")
    assert consume(library, "read") == "HISTORY_UNAVAILABLE"
    original, reads = library._read_journal, []

    def counted():
        reads.append(1)
        return original()

    monkeypatch.setattr(library, "_read_journal", counted)
    if event == "add":
        (library.root / "deletion-journal/added.json").write_text(
            json.dumps(intent("added")), encoding="utf-8"
        )
        stamp(library)
    elif event == "remove":
        (library.root / "deletion-journal/ext.json").unlink()
        stamp(library)
    elif event == "stamp":
        stamp(library, BASE + 1000)
    expected = "VALID" if event == "remove" else "HISTORY_UNAVAILABLE"
    assert consume(library, kind) == expected
    assert len(reads) == (0 if event == "same" and age != -1 else 1)


AUTH = list(product(("success", "content", "io"), ("same", "stamp", "version", "closed")))


@pytest.mark.parametrize("latest,context", AUTH, ids=[f"GS02-F1-AUTH-{i:02}" for i in range(1, 13)])
def test_job_uses_newer_completed_observation_only_for_the_same_live_snapshot(
    env, monkeypatch, latest, context
):
    library, clock = env
    original, reads, older = library._journal_prefetch, [], []

    def superseded():
        reads.append(1)
        observed = original(fresh=True)
        if older:
            return observed
        older.append(observed)
        if latest == "content":
            fault(library, monkeypatch, "json")
        read = library._read_journal
        if latest == "io":

            def denied():
                raise PermissionError(CANARY)

            monkeypatch.setattr(library, "_read_journal", denied)
        newer = original(fresh=True)
        monkeypatch.setattr(library, "_read_journal", read)
        with library._mutex:
            assert library._accept_observation(newer)
        if context == "stamp":
            stamp(library, BASE + 1000)
        elif context == "version":
            library._history_version += 1
        elif context == "closed":
            library.close()
        return observed

    monkeypatch.setattr(library, "_journal_prefetch", superseded)
    expected = (
        "HISTORY_UNAVAILABLE"
        if context == "closed" or latest == "content" or (latest == "io" and context == "same")
        else "VALID"
    )
    assert consume(library, "job") == expected
    assert len(reads) == (1 if context in ("same", "closed") else 2)
