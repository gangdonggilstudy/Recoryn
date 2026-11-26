"""Hand clock/authority oracles; no product parser or decision builds expectations."""

from __future__ import annotations

import hashlib
import json
from itertools import product

import pytest

from recoryn.app.history import HistoryAuditCoordinator
from recoryn.domain import ValidationError
from recoryn.storage.deletion_history import (
    LIFETIME_NS,
    DeletionHistoryIndex,
    HistoryClockSample,
    HistoryEntry,
    read_format_one,
)

pytestmark = pytest.mark.unit
BASE = 100_000_000_000
CLOCK_ROWS = (
    (0, 0, True),
    (29_999_999_999, 29_999_999_999, True),
    (30_000_000_000, 30_000_000_000, False),
    (30_000_000_001, 30_000_000_001, False),
    (-1, 1, False),
    (1, -1, False),
    (1, 30_000_000_001, False),
    (30_000_000_001, 1, False),
)
J_ROWS = list(product(CLOCK_ROWS, ("quiet", "delta", "overflow", "late_finish")))


class Clock:
    def __init__(self):
        self.value = HistoryClockSample(BASE, BASE)

    def __call__(self):
        return self.value


def ready_index(tmp_path):
    clock = Clock()
    index = DeletionHistoryIndex(tmp_path, clock=clock)
    records = {"deleted": HistoryEntry(7, "a" * 64, 7, "DELETED_LOCAL")}
    ticket = index.begin_scan(fresh=True)
    prepared = index.prepare(ticket, records, index.cut())
    retired = index.publish(prepared)
    assert retired and index.valid()
    return index, clock, records


@pytest.mark.parametrize("clock_row,event", J_ROWS, ids=[f"GS11-J-{i:03}" for i in range(1, 33)])
def test_expiry_is_the_validation_start_not_a_delta_or_completion(tmp_path, clock_row, event):
    mono_age, utc_age, in_window = clock_row
    index, clock, records = ready_index(tmp_path)
    receipt = index.receipt
    assert receipt is not None
    ticket = index.begin_scan() if event == "late_finish" else None
    prepared = index.prepare(ticket, records, index.cut()) if ticket else None
    clock.value = HistoryClockSample(BASE + mono_age, BASE + utc_age)
    if event == "delta":
        index.trusted_delta("later", HistoryEntry(9, "b" * 64))
        assert index.receipt is receipt
        assert index.known("later").generation == 9
    elif event == "overflow":
        index.invalidate()
    elif prepared is not None:
        index.publish(prepared)
    assert index.valid() is (in_window and event != "overflow")
    floor = index.known("deleted")
    assert floor is not None and floor.generation == 7 and floor.db_status == "DELETED_LOCAL"
    if index.receipt is not None:
        assert index.receipt.started == HistoryClockSample(BASE, BASE)


def test_GS11_X_CLOCK_observation_error_does_not_extend_expiry(tmp_path):
    index, clock, _ = ready_index(tmp_path)
    clock.value = HistoryClockSample(BASE + LIFETIME_NS - 1, BASE + LIFETIME_NS - 1, 1, 1000)
    assert index.valid() is False
    clock.value = HistoryClockSample(BASE + 1_000_000, BASE + 1_500_000)
    assert index.valid() is False
    clock.value = HistoryClockSample(BASE + 1_000_000, BASE + 1_500_000, 0, 500_000)
    assert index.valid() is True
    with pytest.raises(ValidationError, match="DELETION_HISTORY_UNAVAILABLE"):
        HistoryClockSample(True, BASE)


def test_GS11_X_CLOCK_runtime_granularity_is_uncertainty_never_an_expiry_extension(monkeypatch):
    from types import SimpleNamespace

    import recoryn.storage.deletion_history as module

    readings = iter((BASE, BASE + 10, BASE + 12_000_000, BASE + 12_000_010))
    monkeypatch.setattr(module, "_monotonic_ns", lambda: next(readings))
    monkeypatch.setattr(module, "_utc_ns", lambda: BASE)
    monkeypatch.setattr(module, "_clock_info", lambda kind: SimpleNamespace(resolution=0.015625))
    start, later = HistoryClockSample.now(), HistoryClockSample.now()
    assert start.precision_ns == later.precision_ns == 15_625_000
    assert later.within(start) is True  # one coarse UTC tick need not have advanced
    expired = HistoryClockSample(BASE + LIFETIME_NS, BASE, precision_ns=15_625_000)
    assert expired.within(start) is False


def test_GS11_X_FLOOR_delta_does_not_erase_components_or_reduce_a_tombstone(tmp_path):
    index, _, _ = ready_index(tmp_path)
    old_receipt = index.receipt
    rejected = None
    try:
        index.trusted_delta("deleted", HistoryEntry(8, "c" * 64))
    except ValidationError as error:
        rejected = error.args
    assert rejected is None, ("valid monotone delta was rejected", rejected)
    value = index.known("deleted")
    assert value is not None
    assert (value.journal_generation, value.db_generation, value.db_status) == (
        8,
        7,
        "DELETED_LOCAL",
    )
    assert index.receipt is old_receipt
    for value in (
        HistoryEntry(6, "d" * 64),
        HistoryEntry(db_generation=9, db_status="DELETE_PENDING"),
    ):
        with pytest.raises(ValidationError, match="DELETION_HISTORY_UNAVAILABLE"):
            index.trusted_delta("deleted", value)
        assert index.known("deleted").generation == 8


@pytest.mark.parametrize("io_error", (False, True), ids=["GS11-X-FLOOR-content", "GS11-X-FLOOR-io"])
def test_failed_audit_keeps_the_exact_previously_verified_negative_floor(tmp_path, io_error):
    index, _, records = ready_index(tmp_path)
    scan = index.begin_scan()
    index.failed(scan, io_error=io_error)
    assert index.valid() is False
    assert index.known("deleted") == records["deleted"]
    assert index.cut().materialize() == records
    assert index.needs_fresh is (not io_error)


@pytest.mark.parametrize(
    "old_result", ("success", "failure"), ids=["GS11-X-OBS-late-success", "GS11-X-OBS-late-failure"]
)
def test_an_older_observation_cannot_replace_a_completed_explicit_repair(tmp_path, old_result):
    index, _, rows = ready_index(tmp_path)
    old = index.begin_scan()
    prepared_old = index.prepare(old, rows, index.cut())
    repair = index.begin_scan(fresh=True)
    assert index.publish(index.prepare(repair, rows, index.cut()))
    current = index.receipt
    assert current is not None and current.observation == repair.observation
    if old_result == "success":
        assert index.publish(prepared_old) == ()
    else:
        index.failed(old, io_error=False)
    assert index.receipt is current and index.valid()
    assert index.known("deleted") == rows["deleted"]


@pytest.mark.parametrize("case", ("interval", "coalesce", "fresh", "close", "root"))
def test_GS11_X_CONTROL_one_worker_and_actual_ack(case):
    class Owner:
        deletion_history_instance = "root-a"

        def __init__(self):
            self.calls = []

        def verify_deletion_history(self, *, fresh=False, can_publish=None):
            assert can_publish is None or can_publish() is True
            self.calls.append(fresh)
            return {"status": "READY", "code": ""}

    owner, now = Owner(), [0]
    coordinator = HistoryAuditCoordinator(owner, clock=lambda: now[0])
    first = coordinator.request()
    assert first is not None and coordinator.is_current(first)
    assert owner.calls == [], "requesting must not run canonical I/O in the owner lane"
    now[0] = 4_999_999_999
    assert coordinator.request() is None
    if case == "interval":
        assert coordinator.completed(first) is None
        now[0] = 5_000_000_000
        second = coordinator.request()
        assert second is not None and second.generation == 2
        assert coordinator.execute(second) == {"status": "READY", "code": ""}
        assert owner.calls == [False]
    else:
        now[0] = 5_000_000_000
        assert coordinator.request() is None
        assert coordinator.request(fresh=case == "fresh", force=True) is None
        if case == "close":
            coordinator.close()
            assert coordinator.inflight is first, "cancel is not an executor termination ACK"
            assert not coordinator.is_current(first)
            assert coordinator.completed(first) is None
            assert coordinator.inflight is None and coordinator.request(force=True) is None
        else:
            if case == "root":
                owner.deletion_history_instance = "root-b"
                assert not coordinator.is_current(first)
                assert coordinator.execute(first)["code"] == "DELETION_HISTORY_UNAVAILABLE"
            second = coordinator.completed(first)
            assert second is not None and second.generation == 2
            assert second.fresh is (case == "fresh")
            assert second.instance == owner.deletion_history_instance
            assert coordinator.completed(first) is None
            assert coordinator.inflight is second
            assert coordinator.execute(second) == {"status": "READY", "code": ""}
            assert owner.calls == [case == "fresh"]


def test_GS11_X_PARSER_semantic_digest_binds_values_not_json_spacing(tmp_path):
    journal = tmp_path / "deletion-journal"
    journal.mkdir()
    path = journal / "one.json"
    value = {"schema_version": 1, "session_id": "one", "generation": 3, "state": "DELETE_REQUESTED"}
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")
    first = read_format_one(tmp_path).records["one"]
    literal = b'{"generation":3,"schema_version":1,"session_id":"one","state":"DELETE_REQUESTED"}'
    assert first.generation == 3 and first.journal_digest == hashlib.sha256(literal).hexdigest()
    path.write_bytes(literal + b"\n")
    assert read_format_one(tmp_path).records["one"] == first
    path.write_bytes(literal.replace(b'"generation":3', b'"generation":4') + b"\n")
    changed = read_format_one(tmp_path).records["one"]
    assert changed.generation == 4 and changed.journal_digest != first.journal_digest


def test_GS11_X_PARSER_transient_read_is_not_reclassified_as_content_damage(tmp_path):
    journal = tmp_path / "deletion-journal"
    journal.mkdir()
    (journal / "one.json").write_text("{}", encoding="utf-8")
    failure = PermissionError("temporary reader denial")

    def denied(path):
        raise failure

    with pytest.raises(PermissionError) as caught:
        read_format_one(tmp_path, reader=denied)
    assert caught.value is failure


def test_GS11_X_FLOOR_expired_initial_scan_pins_negative_facts_without_permission(tmp_path):
    clock = Clock()
    index = DeletionHistoryIndex(tmp_path, clock=clock)
    scan = index.begin_scan(fresh=True)
    records = {"gone": HistoryEntry(11, "e" * 64, 11, "DELETED_LOCAL")}
    prepared = index.prepare(scan, records, index.cut())
    clock.value = HistoryClockSample(BASE + 30_000_000_000, BASE + 30_000_000_000)
    retired = index.publish(prepared)
    assert retired and index.valid() is False and index.receipt is None
    floor = index.known("gone")
    assert floor is not None and floor.generation == 11 and floor.db_status == "DELETED_LOCAL"
    another = index.begin_scan(fresh=True)
    with pytest.raises(ValidationError, match="DELETION_HISTORY_UNAVAILABLE"):
        index.prepare(another, {}, index.cut())
    assert index.known("gone").generation == 11


def test_GS11_X_PAGE_keyset_is_bounded_and_bound_to_root_and_catalog(tmp_path):
    from recoryn.domain import StateConflict
    from recoryn.storage import Library

    root = tmp_path / "a"
    with Library(root) as library:
        with library._mutex:
            library._db.executemany(
                "INSERT INTO sessions(session_id,state,state_version) VALUES(?,'CREATED',0)",
                [(f"s{i:03}",) for i in range(260)],
            )
            library._db.commit()
        first = library.sessions_page()
        assert [s.session_id for s in first["sessions"]] == [f"s{i:03}" for i in range(128)]
        second = library.sessions_page(
            cursor=first["next"], expected_catalog_version=first["catalog_version"]
        )
        assert [s.session_id for s in second["sessions"]] == [f"s{i:03}" for i in range(128, 256)]
        last = library.sessions_page(cursor=second["next"])
        assert [s.session_id for s in last["sessions"]] == ["s256", "s257", "s258", "s259"]
        assert last["next"] is None
        with Library(tmp_path / "b") as other:
            with pytest.raises(StateConflict, match="STALE_SESSION_VERSION"):
                other.sessions_page(cursor=first["next"])
        library.create_session("new")
        with pytest.raises(StateConflict, match="STALE_SESSION_VERSION"):
            library.sessions_page(cursor=first["next"])
        with pytest.raises(StateConflict, match="STALE_SESSION_VERSION"):
            library.sessions_page(expected_catalog_version=first["catalog_version"])


@pytest.mark.parametrize(
    "argument",
    [
        {"limit": 0},
        {"limit": 129},
        {"limit": True},
        {"cursor": False},
        {"cursor": "{}"},
        {"cursor": '{"schema_version":2,"instance":"x","version":0,"after":"s"}'},
        {"expected_catalog_version": True},
        {"cursor": '{"schema_version":1,"extra":0}'},
    ],
    ids=[f"GS11-X-PAGE-{i:02}" for i in range(1, 9)],
)
def test_page_rejects_invalid_cursors_and_bounds_without_returning_a_partial_list(
    tmp_path, argument
):
    from recoryn.storage import Library

    with Library(tmp_path / "library") as library:
        with pytest.raises(ValidationError):
            library.sessions_page(**argument)


def test_GS11_X_CLOCK_failure_does_not_close_or_freeze_the_local_catalog(tmp_path):
    from recoryn.storage import Library

    def broken_clock():
        raise OSError("private observer canary")

    index, _, _ = ready_index(tmp_path)
    index.clock = broken_clock
    assert index.valid() is False and index.known("deleted").generation == 7

    with Library(tmp_path / "library", history_clock=broken_clock) as library:
        library.check_local_catalog()
        assert library.create_session("s").session_id == "s"
        assert library.get_session("s").state.value == "CREATED"
        assert library.deletion_history_status() == {
            "status": "UNAVAILABLE",
            "code": "DELETION_HISTORY_UNAVAILABLE",
        }
        with pytest.raises(ValidationError, match="DELETION_HISTORY_UNAVAILABLE"):
            library.sessions_page()


@pytest.mark.parametrize(
    "invalid",
    ("registration", "source", "consumer", "sealer", "run", "root", "instance", "thread"),
    ids=[f"GS11-X-CONTROL-{i:02}" for i in range(1, 9)],
)
def test_capture_context_needs_explicit_registration_and_every_current_ack(tmp_path, invalid):
    import threading
    from dataclasses import replace

    from recoryn.domain import SessionState, StateConflict
    from recoryn.storage import Library

    class Owner:
        state = ("run-a", True, True, True)

        def is_live(self):
            return False  # insufficient on its own

        def capture_control_state(self):
            return self.state

    with Library(tmp_path / "library") as library:
        library.create_session("s")
        library.transition("s", SessionState.FINALIZING, 0)
        owner = Owner()
        library.register_live_owner("s", owner)
        with pytest.raises(StateConflict, match="SESSION_LIVE"):
            library.capture_control("s", owner, object())
        registration = library.register_capture_controller("s", owner)
        if invalid == "registration":
            with pytest.raises(StateConflict, match="SESSION_LIVE"):
                library.capture_control("s", owner, object())
            return
        if invalid in {"source", "consumer", "sealer"}:
            index = {"source": 1, "consumer": 2, "sealer": 3}[invalid]
            state = list(owner.state)
            state[index] = False
            owner.state = tuple(state)
            with pytest.raises(StateConflict, match="SESSION_LIVE"):
                library.capture_control("s", owner, registration)
            return
        proof = library.capture_control("s", owner, registration)
        library.invalidate_deletion_history()
        with pytest.raises(ValidationError, match="DELETION_HISTORY_UNAVAILABLE"):
            library.finalize_session("s")
        if invalid == "run":
            owner.state = ("run-b", True, True, True)
        elif invalid == "root":
            proof = replace(proof, root=tmp_path / "other")
        elif invalid == "instance":
            proof = replace(proof, instance="other")
        else:
            proof = replace(proof, thread_id=threading.get_ident() + 1)
        with pytest.raises(StateConflict, match="SESSION_LIVE"):
            library.finalize_session("s", capture_control=proof)
        assert library.get_session("s").state.value == "FINALIZING"


def test_GS11_X_CONTROL_valid_context_is_explicit_and_never_mints_a_global_receipt(tmp_path):
    from recoryn.domain import SessionState
    from recoryn.storage import Library

    class Owner:
        def is_live(self):
            return False

        def capture_control_state(self):
            return ("run-a", True, True, True)

    with Library(tmp_path / "library") as library:
        library.create_session("s")
        library.transition("s", SessionState.FINALIZING, 0)
        owner = Owner()
        registration = library.register_capture_controller("s", owner)
        proof = library.capture_control("s", owner, registration)
        library.invalidate_deletion_history()
        result = library.finalize_session("s", capture_control=proof)
        assert result["state"] == "FINALIZED" and result["frame_count"] == 0
        assert library.deletion_history_status()["status"] == "UNAVAILABLE"
        with pytest.raises(ValidationError, match="DELETION_HISTORY_UNAVAILABLE"):
            library.recover_session("s")


@pytest.mark.parametrize(
    "phase", ("before", "after"), ids=["GS11-X-GATE-before", "GS11-X-GATE-after"]
)
def test_a_cancelled_observer_never_publishes_a_receipt_or_erases_a_negative(
    tmp_path, monkeypatch, phase
):
    from recoryn.storage import Library

    with Library(tmp_path / "library") as library:
        library.create_session("past")
        assert library.delete_session("past")["deleted"]
        floor = library._authority.known("past")
        library.invalidate_deletion_history()
        allowed = [phase == "after"]
        calls = []
        reading = library._read_journal

        def read():
            calls.append("read")
            value = reading()
            allowed[0] = False
            return value

        monkeypatch.setattr(library, "_read_journal", read)
        assert library.verify_deletion_history(can_publish=lambda: allowed[0]) == {
            "status": "UNAVAILABLE",
            "code": "DELETION_HISTORY_UNAVAILABLE",
        }
        assert calls == (["read"] if phase == "after" else [])
        assert library._authority.receipt is None
        assert library._authority.known("past") == floor
        monkeypatch.setattr(library, "_read_journal", reading)
        assert library.verify_deletion_history(fresh=True)["status"] == "READY"


def test_GS11_X_POWER_controller_keeps_real_ack_while_suspending_requests():
    class Owner:
        deletion_history_instance = "root"
        calls = 0

        def verify_deletion_history(self, *, fresh=False, can_publish=None):
            assert not fresh and can_publish() is True
            self.calls += 1
            return {"status": "READY", "code": ""}

    owner = Owner()
    controller = HistoryAuditCoordinator(owner, clock=lambda: 0)
    old = controller.request()
    controller.set_suspended(True)
    assert controller.inflight is old and controller.request(force=True) is None
    assert controller.execute(old)["status"] == "UNAVAILABLE" and owner.calls == 0
    assert not controller.is_current(old)
    assert controller.completed(old) is None
    controller.set_suspended(False)
    request = controller.request(force=True)
    assert request is not None and request.generation == 2
    assert controller.execute(request) == {"status": "READY", "code": ""}
    assert owner.calls == 1
    controller.close()
    assert controller.execute(request)["status"] == "UNAVAILABLE" and owner.calls == 1


_COV_INVALID_ENTRIES = [
    {},
    {"journal_generation": 1},
    {"journal_generation": 1, "journal_digest": 7},
    {"journal_generation": 1, "journal_digest": "a" * 63},
    {"journal_generation": 1, "journal_digest": "A" * 64},
    {"journal_digest": "a" * 64, "db_generation": 1, "db_status": "DELETE_PENDING"},
    {"db_generation": 1, "db_status": "OTHER"},
    {"journal_generation": True, "journal_digest": "a" * 64},
    {"db_generation": True, "db_status": "DELETE_PENDING"},
    {"journal_generation": 1, "journal_digest": "a" * 64, "db_status": "DELETE_PENDING"},
]


@pytest.mark.parametrize(
    "values", _COV_INVALID_ENTRIES, ids=[f"GS11-COV-{i:03}" for i in range(1, 11)]
)
def test_invalid_authority_components_never_become_a_fact(values):
    with pytest.raises(ValidationError, match="^DELETION_HISTORY_UNAVAILABLE$"):
        HistoryEntry(**values)


@pytest.mark.parametrize("operation", ("scan", "delta"), ids=["GS11-COV-011", "GS11-COV-012"])
def test_closed_authority_cannot_gain_a_new_fact_or_receipt(tmp_path, operation):
    index = DeletionHistoryIndex(tmp_path, clock=Clock())
    index.close()
    with pytest.raises(ValidationError, match="^DELETION_HISTORY_UNAVAILABLE$"):
        if operation == "scan":
            index.begin_scan()
        else:
            index.trusted_delta("s", HistoryEntry(db_generation=1, db_status="DELETE_PENDING"))
    assert index.known("s") is None and index.receipt is None and not index.valid()


@pytest.mark.parametrize("error", (OSError, OverflowError), ids=["GS11-COV-013", "GS11-COV-014"])
def test_an_unreadable_clock_revokes_permission_without_losing_negative_facts(tmp_path, error):
    index, _, _ = ready_index(tmp_path)
    fact = HistoryEntry(db_generation=1, db_status="DELETE_PENDING")
    index.trusted_delta("s", fact)

    def unavailable():
        raise error("observer unavailable")

    index.clock = unavailable
    assert index.valid() is False and index.known("s") == fact


def test_GS11_COV_015_another_instances_cut_never_publishes_permission(tmp_path):
    index = DeletionHistoryIndex(tmp_path / "one", clock=Clock())
    scan = index.begin_scan()
    other = DeletionHistoryIndex(tmp_path / "two", clock=Clock())
    with pytest.raises(ValidationError, match="^DELETION_HISTORY_UNAVAILABLE$"):
        index.prepare(scan, {}, other.cut())
    assert index.receipt is None and not index.valid()


def test_GS11_COV_017_initial_negative_floor_and_a_later_delta_both_survive_publication(tmp_path):
    index = DeletionHistoryIndex(tmp_path, clock=Clock())
    first = HistoryEntry(db_generation=1, db_status="DELETE_PENDING")
    later = HistoryEntry(db_generation=2, db_status="DELETED_LOCAL")
    index.trusted_delta("s", first)
    scan = index.begin_scan()
    prepared = index.prepare(scan, {"s": first}, index.cut())
    index.trusted_delta("later", later)
    index.publish(prepared)
    assert index.known("s") == first and index.known("later") == later and index.valid()
    assert "s" in index and "later" in index


def test_GS11_COV_018_missing_canonical_directory_cannot_be_a_successful_empty_history(tmp_path):
    with pytest.raises(ValidationError):
        read_format_one(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_GS11_COV_019_keyset_pages_and_compatibility_list_preserve_all_129_literal_ids(tmp_path):
    from recoryn.storage import Library

    expected = [f"s{i:03}" for i in range(129)]
    with Library(tmp_path) as library:
        for sid in expected:
            library.create_session(sid)
        first = library.sessions_page()
        assert [s.session_id for s in first["sessions"]] == expected[:128]
        assert first["next"] is not None
        last = library.sessions_page(cursor=first["next"])
        assert [s.session_id for s in last["sessions"]] == expected[128:]
        assert last["next"] is None
        assert [s.session_id for s in library.list_sessions()] == expected


def test_GS11_COV_020_missing_catalog_projection_metadata_is_not_an_empty_library(tmp_path):
    from recoryn.storage import Library

    with Library(tmp_path) as library:
        library.create_session("s")
        with library._mutex:
            library._db.execute("DELETE FROM storage_catalog_meta")
            library._db.commit()
        with pytest.raises(ValidationError, match="^DELETION_HISTORY_UNAVAILABLE$"):
            library.sessions_page()
        assert library._db.execute("SELECT session_id FROM sessions").fetchall()[0][0] == "s"


def test_GS11_COV_021_cancelled_audit_admission_reads_no_body_and_grants_no_new_receipt(
    tmp_path, monkeypatch
):
    from recoryn.storage import Library
    from recoryn.storage import library as module

    with Library(tmp_path) as library:
        receipt = library._authority.receipt

        def forbidden(*args, **kwargs):
            pytest.fail("cancelled admission read a canonical body")

        monkeypatch.setattr(module, "read_json", forbidden)
        assert library.verify_deletion_history(can_publish=lambda: False) == {
            "status": "UNAVAILABLE",
            "code": "DELETION_HISTORY_UNAVAILABLE",
        }
        assert library._authority.receipt is receipt


def test_GS11_COV_016_initial_pinned_negative_is_not_lost_when_first_audit_finishes(tmp_path):
    index = DeletionHistoryIndex(tmp_path, clock=Clock())
    fact = HistoryEntry(db_generation=1, db_status="DELETE_PENDING")
    index.trusted_delta("s", fact)
    scan = index.begin_scan()
    index.publish(index.prepare(scan, {"s": fact}, index.cut()))
    assert index.known("s") == fact and index.valid()


def test_GS11_COV_022_a_higher_journal_does_not_hide_a_lower_database_generation():
    before = HistoryEntry(2, "a" * 64, 5, "DELETED_LOCAL")
    with pytest.raises(ValidationError, match="^DELETION_HISTORY_UNAVAILABLE$"):
        before.advance(HistoryEntry(6, "b" * 64, 3, "DELETED_LOCAL"))
    assert before == HistoryEntry(2, "a" * 64, 5, "DELETED_LOCAL")


@pytest.mark.parametrize(
    "state",
    ("valid", "tombstone", "missing", "closed"),
    ids=[f"GS11-COV-{i:03}" for i in range(23, 27)],
)
def test_public_authority_view_is_exact_and_never_outlives_its_instance(tmp_path, state):
    from recoryn.storage import Library

    with Library(tmp_path) as library:
        if state != "missing":
            library.create_session("s")
        if state == "tombstone":
            assert library.delete_session("s")["state"] == "DELETED_LOCAL"
        if state == "closed":
            library.close()
            with pytest.raises(ValidationError, match="^DELETION_HISTORY_UNAVAILABLE$"):
                library.authority_view("s")
            assert library.verify_deletion_history() == {
                "status": "UNAVAILABLE",
                "code": "DELETION_HISTORY_UNAVAILABLE",
            }
        else:
            assert library.authority_view("s") == {
                "session_id": "s",
                "authority": {"valid": "VALID", "tombstone": "TOMBSTONE", "missing": "MISSING"}[
                    state
                ],
                "generation": 1 if state == "tombstone" else None,
            }


def test_GS11_COV_027_local_open_is_never_a_management_preflight(tmp_path):
    from recoryn.storage import Library

    with Library(tmp_path, defer_history=True) as library:
        library.check_local_catalog()
        library.create_session("s")
        with pytest.raises(ValidationError, match="^DELETION_HISTORY_UNAVAILABLE$"):
            library.check_management_history()
        assert library.get_session("s").session_id == "s"


def test_GS11_COV_028_content_damage_needs_explicit_fresh_repair(tmp_path, monkeypatch):
    from recoryn.storage import Library
    from recoryn.storage import library as module

    with Library(tmp_path) as library:
        damaged = tmp_path / "deletion-journal" / "broken.json"
        damaged.write_bytes(b"{")
        assert library.verify_deletion_history(fresh=True)["status"] == "UNAVAILABLE"
        damaged.unlink()
        reads = []
        original = module.read_json

        def observed(*args, **kwargs):
            reads.append(args[0])
            return original(*args, **kwargs)

        monkeypatch.setattr(module, "read_json", observed)
        assert library.verify_deletion_history()["status"] == "UNAVAILABLE"
        assert reads == []
        assert library.verify_deletion_history(fresh=True)["status"] == "READY"


def test_GS11_COV_029_missing_parser_handoff_is_not_verified_empty_history(tmp_path, monkeypatch):
    from recoryn.storage import Library

    with Library(tmp_path) as library:
        library.create_session("s")
        with monkeypatch.context() as patch:
            patch.setattr(library, "_read_journal", lambda: {})
            assert library.verify_deletion_history(fresh=True)["status"] == "UNAVAILABLE"
            assert library.deletion_history_status()["status"] == "UNAVAILABLE"
        assert library.get_session("s").session_id == "s"
        assert library.verify_deletion_history(fresh=True)["status"] == "READY"


def test_GS11_COV_030_a_runtime_future_schema_never_receives_a_new_permission(tmp_path):
    from recoryn.storage import Library

    with Library(tmp_path) as library:
        with library._mutex:
            library._db.execute("PRAGMA user_version=2")
        assert library.verify_deletion_history(fresh=True)["status"] == "UNAVAILABLE"
        assert library.deletion_history_status()["status"] == "UNAVAILABLE"
        with library._mutex:
            assert library._db.execute("PRAGMA user_version").fetchone()[0] == 2


def test_GS11_COV_031_job_stamp_io_failure_denies_only_that_call(tmp_path, monkeypatch):
    from recoryn.storage import Library

    with Library(tmp_path) as library:
        library.create_session("s")

        def denied():
            raise PermissionError("transient metadata read")

        with monkeypatch.context() as patch:
            patch.setattr(library, "_journal_stamp", denied)
            with Library.job_authority(library.db_path, "s") as authority:
                assert authority == "HISTORY_UNAVAILABLE"
        with Library.job_authority(library.db_path, "s") as authority:
            assert authority == "VALID"


def test_GS11_COV_032_a_closed_library_never_passes_management_preflight(tmp_path):
    from recoryn.storage import Library

    library = Library(tmp_path)
    library.close()
    with pytest.raises(ValidationError, match="^DELETION_HISTORY_UNAVAILABLE$"):
        library.check_management_history()


def test_GS11_COV_033_root_owner_cannot_start_heavy_verification(tmp_path, monkeypatch):
    from recoryn.domain import StateConflict
    from recoryn.storage import Library

    with Library(tmp_path) as library:
        receipt = library._authority.receipt

        def forbidden():
            pytest.fail("heavy inspection entered under root")

        monkeypatch.setattr(library, "_inspect_staged_intents", forbidden)
        with library._mutex, pytest.raises(StateConflict, match="^DELETION_HISTORY_UNAVAILABLE$"):
            library.verify_deletion_history(fresh=True)
        assert library._authority.receipt is receipt


def test_GS11_COV_034_missing_journal_at_reopen_is_not_verified_empty_history(tmp_path):
    from recoryn.storage import Library

    with Library(tmp_path) as library:
        library.create_session("s")
    (tmp_path / "deletion-journal").rmdir()
    with Library(tmp_path, defer_history=True) as reopened:
        assert reopened.verify_deletion_history(fresh=True)["status"] == "UNAVAILABLE"
        assert reopened.deletion_history_status()["status"] == "UNAVAILABLE"
        with pytest.raises(ValidationError, match="^DELETION_HISTORY_UNAVAILABLE$"):
            reopened.check_management_history()


def test_GS11_COV_035_a_reserved_delete_never_grants_job_admission(tmp_path, monkeypatch):
    import threading

    from recoryn.storage import Library

    with Library(tmp_path) as library:
        library.create_session("s")
        entered, release = threading.Event(), threading.Event()
        real_prepare = library._prepare_intent
        outcomes, errors = [], []

        def blocked(*args):
            entered.set()
            assert release.wait(5)
            return real_prepare(*args)

        def delete():
            try:
                outcomes.append(library.delete_session("s"))
            except BaseException as error:
                errors.append(error)

        monkeypatch.setattr(library, "_prepare_intent", blocked)
        worker = threading.Thread(target=delete, name="gs11-cov-reserved-delete")
        worker.start()
        try:
            assert entered.wait(5)
            with Library.job_authority(library.db_path, "s") as authority:
                assert authority == "HISTORY_UNAVAILABLE"
        finally:
            release.set()
            worker.join(5)
        assert not worker.is_alive() and not errors
        assert len(outcomes) == 1 and outcomes[0]["state"] == "DELETED_LOCAL"
        with Library.job_authority(library.db_path, "s") as authority:
            assert authority == "TOMBSTONE"
