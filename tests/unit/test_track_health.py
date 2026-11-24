"""G08 hand-written transition and invalid-value oracles; no devices."""

from dataclasses import replace
from itertools import product

import pytest

from recoryn.domain import ValidationError
from recoryn.domain.capture_health import GapFact, validate_snapshot


@pytest.mark.parametrize("case", range(4), ids=[f"G08-FIX3-U{n:02}" for n in range(1, 5)])
def test_byte_bounded_projection_reports_gap_omission_only_when_needed(case):
    import copy
    import json

    from recoryn.storage.library import _bounded_health_projection

    count = 256 if case == 0 else 2
    gaps = [
        {
            "reason": "QUEUE_DROP",
            "first_sequence": n * 2 + 1,
            "last_sequence": n * 2 + 1,
            "frame_count": 480,
            "capture_mono_ns": 1_000_000_000_000_000_000 + n,
        }
        for n in range(count)
    ]
    value = {
        "detail_complete": True,
        "tracks": {
            t: {"gaps": copy.deepcopy(gaps), "dropped_frames": count * 480, "detail_complete": True}
            for t in ("mic", "system")
        },
    }
    if case == 1:
        value["extra"] = "x" * 70_000
    elif case == 2:
        value["tracks"]["mic"]["events"] = [
            fact(event_id=f"event-{n}").to_dict() for n in range(256)
        ]
    before = copy.deepcopy(value)
    result = _bounded_health_projection(value)
    assert value == before
    assert len(json.dumps(result, separators=(",", ":"), sort_keys=True).encode()) <= 60 * 1024
    removed = []
    for track in ("mic", "system"):
        after = result["tracks"][track]
        omitted = len(after.get("gaps", [])) < count
        removed.append(omitted)
        assert bool(after.get("gap_detail_truncated")) is omitted
        assert after["dropped_frames"] == count * 480
        if omitted:
            assert after["detail_complete"] is False
    assert any(removed) is (case in (0, 1))
    if case == 1:
        assert all(not t.get("gaps") for t in result["tracks"].values())
    elif case == 2:
        assert len(result["tracks"]["mic"]["events"]) < 256
    elif case == 3:
        assert result == before


EVENTS = (
    "READY",
    "ACCEPT_GOOD",
    "QUEUE_REJECT",
    "BAD_CLOCK",
    "NO_PACKETS",
    "DEVICE_DISCONTINUITY",
    "DEVICE_LOST",
    "PAUSE_CONFIRMED",
    "SUSPEND_CONFIRMED",
    "STOP_CONFIRMED",
    "STORAGE_FAILED",
    "BEGIN_RESUME",
    "DUPLICATE_EVENT",
)
STATES = (
    ("OK", "NONE"),
    ("DEGRADED", "BAD_CLOCK"),
    ("UNAVAILABLE", "STARTING"),
    ("UNAVAILABLE", "DEVICE_LOST"),
    ("UNAVAILABLE", "STORAGE_FAILED"),
    ("STOPPED", "PAUSED"),
    ("STOPPED", "FINAL"),
)
# State indices in the specification, independent of the product transition function.
EXPECTED = (
    (0, 0, 1, 1, 1, 1, 3, 5, 5, 6, 4, 0, 0),
    (1, 0, 1, 1, 1, 1, 3, 5, 5, 6, 4, 1, 1),
    (0, 0, 1, 1, 1, 1, 3, 5, 5, 6, 4, 2, 2),
    (3, 3, 3, 3, 3, 3, 3, 5, 5, 6, 4, 3, 3),
    (4,) * 13,
    (5, 5, 5, 5, 5, 5, 5, 5, 5, 6, 5, 2, 5),
    (6,) * 13,
)
S = list(product(range(7), range(13), (False, True), (1, 2)))


@pytest.mark.parametrize("case", (1, 2, 3), ids=[f"G08-FIX1-COV{n:02}" for n in (1, 2, 3)])
def test_projection_budget_defenses_preserve_input_and_counters(case):
    import copy
    import json

    from recoryn.storage.library import _bounded_health_projection

    source = {
        "health_schema_version": 2,
        "health_version": 1,
        "tracks": {"mic": {"accepted_frames": 7, "dropped_frames": 5, "detail_complete": True}},
    }
    if case == 1:
        source["tracks"]["mic"]["events"] = [{"ordinal": n, "note": "x" * 1200} for n in range(100)]
    elif case == 2:
        source["native_formats"] = {"legacy_note": "x" * 100_000}
    else:
        source["tracks"]["a-oversize"] = {"legacy_note": "x" * 100_000}
    before = copy.deepcopy(source)
    view = _bounded_health_projection(source)
    assert source == before
    assert len(json.dumps(view, ensure_ascii=False, separators=(",", ":")).encode()) <= 65536
    assert view["detail_complete"] is False
    assert view["tracks"]["mic"]["accepted_frames"] == 7
    assert view["tracks"]["mic"]["dropped_frames"] == 5
    if case == 1:
        assert view["tracks"]["mic"]["events_omitted"] > 0
        assert view["tracks"]["mic"]["events"][-1]["ordinal"] == 99
    elif case == 2:
        assert "native_formats" not in view
    else:
        assert "a-oversize" not in view["tracks"] and view["tracks_omitted"] == 1


@pytest.mark.parametrize("count", [17], ids=["G08-FIX1-COV04"])
def test_checkpoint_summary_truncation_keeps_canonical_facts(count, tmp_path):
    import json

    from recoryn.storage import Library

    with Library(tmp_path) as library:
        track = snapshot()["tracks"]["mic"]
        track["dropped_frames"] = 51
        track["loss_ranges"] = [[n * 6, n * 6 + 3] for n in range(count)]
        track["gaps"] = [
            {
                "reason": "QUEUE_DROP",
                "first_sequence": n * 2,
                "last_sequence": n * 2,
                "frame_count": 3,
                "capture_mono_ns": n,
            }
            for n in range(count)
        ]
        seed(library, tracks={"mic": track})
        view = library.capture_health("s")["tracks"]["mic"]
        assert len(view["gaps"]) == len(view["loss_ranges"]) == 16
        assert view["known_loss_frames"] == 51 and view["dropped_frames"] == 51
        assert view["detail_complete"] is False
        raw = json.loads(
            library._db.execute("SELECT payload FROM capture_health_runs").fetchone()[0]
        )
        assert raw["tracks"]["mic"]["gaps"] == track["gaps"]
        assert raw["tracks"]["mic"]["loss_ranges"] == track["loss_ranges"]


@pytest.mark.parametrize("race", ("body", "deletion"), ids=["G08-FIX1-COV05", "G08-FIX1-COV06"])
def test_deferred_marker_rechecks_authority_and_body(race, tmp_path, monkeypatch):
    import json

    from recoryn.domain import StateConflict
    from recoryn.storage import Library

    with Library(tmp_path) as library:
        seed(library)
        original = library.capture_health
        before = library._db.execute("SELECT capture_health FROM sessions").fetchone()[0]

        def changed(*a, **k):
            value = original(*a, **k)
            if race == "body":
                current = {**value, "race": True}
                library._db.execute(
                    "UPDATE sessions SET capture_health=?",
                    (
                        json.dumps(
                            current, sort_keys=True, ensure_ascii=False, separators=(",", ":")
                        ),
                    ),
                )
            else:
                library._db.execute(
                    "INSERT INTO deleted_sessions VALUES('s',1000,'DELETE_PENDING')"
                )
            library._db.commit()
            return value

        monkeypatch.setattr(library, "capture_health", changed)
        with pytest.raises(
            StateConflict, match="HEALTH_SNAPSHOT_CHANGED" if race == "body" else "DELETE_PENDING"
        ):
            library.defer_capture_health("s", "run")
        after = library._db.execute("SELECT capture_health FROM sessions").fetchone()[0]
        assert "health_status" not in json.loads(after)
        if race == "body":
            assert json.loads(after)["race"] is True
        else:
            assert after == before


G = list(
    product(
        (
            "QUEUE_DROP",
            "DEVICE_DISCONTINUITY",
            "DEVICE_LOST",
            "PAUSE",
            "SUSPEND",
            "STORAGE_FAILED",
            "NO_PACKETS",
            "UNKNOWN_TAIL",
        ),
        (False, True),
        (False, True),
        (1, 2),
    )
)
B = list(product((-1, 0, 1), ("buffer", "payload", "summary", "page"), (False, True)))


def fact(**changes):
    values = dict(
        session_id="s",
        capture_run_id="run",
        track_id="mic",
        epoch_id="epoch",
        event_id="event",
        gap_id="gap",
        ordinal=1,
        reason="QUEUE_DROP",
        source="APP_QUEUE",
        clock_ref="source",
        start=10,
        end=20,
        range_quality="EXACT_SOURCE",
        lost_frames=10,
        count_quality="EXACT",
        open=False,
    )
    values.update(changes)
    return GapFact(**values)


def snapshot(**changes):
    value = {
        "schema_version": 2,
        "session_id": "s",
        "capture_run_id": "run",
        "process_clock_id": "clock",
        "checkpoint_seq": 0,
        "observed_mono_ns": 1,
        "tracks": {
            "mic": {
                "epoch_id": "epoch",
                "state": "OK",
                "reason": "NONE",
                "accepted_frames": 0,
                "dropped_frames": 0,
                "detail_complete": True,
            }
        },
        "events": [],
    }
    value.update(changes)
    return value


def seed(library, **changes):
    library.create_session("s")
    value = snapshot(**changes)
    version = library.begin_capture_health("s", value, expected_state_version=0)
    return value, version


@pytest.mark.parametrize("row", S, ids=[f"G08-S-{i:03}" for i in range(1, 365)])
def test_state_table(row):
    state, event, stale, tracks = row
    from recoryn.app.recording import RecordingService

    # The source-token admission is exercised through the public observation method.
    if stale:
        import copy
        import threading

        target = object.__new__(RecordingService)
        names = ("mic", "system")[:tracks]
        target._gate, target._epochs = threading.Lock(), {t: "new-" + t for t in names}
        target._health_started = target._accepting = True
        target.session_id, target._capture_run_id = "s", "run"
        target._event_ordinal, target._pending_events = 0, []
        target._track_health = {
            t: {
                "state": STATES[state][0],
                "reason": STATES[state][1],
                "epoch_id": "new-" + t,
                "detail_complete": True,
                "loss_ranges": [],
            }
            for t in names
        }
        notices = (
            {"event": "ready"},
            {"event": "packet", "accepted": True},
            {"event": "packet", "accepted": False},
            {"event": "packet", "flags": ["TIMESTAMP_ERROR"]},
            {"event": "idle"},
            {"event": "packet", "flags": ["DATA_DISCONTINUITY"]},
            {"event": "error", "code": "DEVICE_LOST"},
            {"event": "stopped", "code": "PAUSED"},
            {"event": "stopped", "code": "SUSPENDED"},
            {"event": "stopped", "release_ack": True},
            {"event": "error", "code": "STORAGE_FAILED"},
            {"event": "ready", "running": True},
            {"event": "packet", "sequence": 0},
        )
        before = copy.deepcopy((target._track_health, target._pending_events, target._epochs))
        assert RecordingService.observe_health(target, "mic", "old", notices[event]) is False
        assert (target._track_health, target._pending_events, target._epochs) == before
    else:
        from types import SimpleNamespace

        target = SimpleNamespace(
            _track_health={
                "mic": dict(zip(("state", "reason"), STATES[state], strict=True)),
                **({"system": {"state": "OK", "reason": "NONE"}} if tracks == 2 else {}),
            }
        )
        RecordingService._track_event(target, "mic", EVENTS[event])
        result = tuple(target._track_health["mic"].values())
        assert result[0] == STATES[EXPECTED[state][event]][0]
        if EXPECTED[state][event] in {3, 4, 5, 6}:
            assert result[1] == STATES[EXPECTED[state][event]][1]
        # Another track's input fact is untouched by this transition.
        if tracks == 2:
            assert target._track_health["system"] == {"state": "OK", "reason": "NONE"}


@pytest.mark.parametrize("row", G, ids=[f"G08-G-{i:02}" for i in range(1, 65)])
def test_gap_partitions(row):
    reason, exact, known, tracks = row
    sources = {
        "QUEUE_DROP": "APP_QUEUE",
        "DEVICE_DISCONTINUITY": "DEVICE",
        "DEVICE_LOST": "DEVICE",
        "PAUSE": "CONTROL",
        "SUSPEND": "CONTROL",
        "STORAGE_FAILED": "STORAGE",
        "NO_PACKETS": "DEVICE",
        "UNKNOWN_TAIL": "RECOVERY",
    }
    # Exact device-lost/no-packet/storage/tail ranges lack evidence. Queue needs a count.
    valid = (
        (reason == "QUEUE_DROP" and known)
        or (reason == "DEVICE_DISCONTINUITY" and (not exact or known))
        or (reason in {"PAUSE", "SUSPEND"} and not known)
        or (
            reason in {"DEVICE_LOST", "STORAGE_FAILED", "NO_PACKETS", "UNKNOWN_TAIL"}
            and not known
            and not exact
        )
    )
    kwargs = dict(
        reason=reason,
        source=sources[reason],
        lost_frames=10 if known else None,
        count_quality="EXACT" if known else "UNKNOWN",
        start=10 if exact else None,
        end=20 if exact else None,
        range_quality="OBSERVED_CONTROL"
        if exact and reason in {"PAUSE", "SUSPEND"}
        else "EXACT_SOURCE"
        if exact
        else "UNKNOWN",
        kind="UNKNOWN_TAIL" if reason == "UNKNOWN_TAIL" else "OPEN",
    )
    if valid:
        for _ in range(tracks):
            value = fact(**kwargs)
            assert value.lost_frames == (10 if known else None)
    else:
        with pytest.raises(ValidationError):
            fact(**kwargs)


@pytest.mark.parametrize("case", range(1, 25), ids=[f"G08-T-{i:02}" for i in range(1, 25)])
def test_invalid_and_identity_cases(case, tmp_path):
    if case in {1, 2, 3, 4, 5, 6, 7, 9, 24}:
        changes = {
            1: {"lost_frames": True},
            2: {"lost_frames": -1},
            3: {"lost_frames": 2**63},
            4: {"lost_frames": "0"},
            5: {"start": float("nan")},
            6: {"start": -1},
            7: {"end": 9},
            9: {"track_id": ""},
            24: {
                "reason": "UNKNOWN_TAIL",
                "source": "RECOVERY",
                "kind": "UNKNOWN_TAIL",
                "lost_frames": 0,
            },
        }
        with pytest.raises(ValidationError):
            fact(**changes[case])
    elif case == 19:
        with pytest.raises(ValidationError, match="HEALTH_VERSION_UNSUPPORTED"):
            validate_snapshot(snapshot(schema_version=3))
    else:
        import copy

        from recoryn.domain import StateConflict
        from recoryn.domain.capture_health import CaptureReceipt
        from recoryn.storage import Library

        with Library(tmp_path) as library:
            value, version = seed(library)
            before = library.capture_health("s")
            if case == 13:
                assert (
                    library.checkpoint_capture_health("s", value, expected_health_version=version)
                    == version
                )
                assert library.capture_health("s") == before
                return
            altered = copy.deepcopy(value)
            altered["checkpoint_seq"] = 1
            if case == 8:
                altered["events"] = [
                    fact(
                        reason="PAUSE",
                        source="CONTROL",
                        clock_ref="other",
                        range_quality="OBSERVED_CONTROL",
                        lost_frames=None,
                        count_quality="UNKNOWN",
                    ).to_dict()
                ]
            elif case == 10:
                altered["session_id"] = "other"
            elif case == 11:
                altered["tracks"]["mic"]["epoch_id"] = "old"
            elif case == 12:
                altered["capture_run_id"] = "future"
            elif case == 14:
                altered["events"] = [fact().to_dict()]
                version = library.checkpoint_capture_health(
                    "s", altered, expected_health_version=version
                )
                altered["events"] = [replace(fact(), start=9, lost_frames=11).to_dict()]
                altered["checkpoint_seq"] = 2
                before = library.capture_health("s")
            elif case in {15, 16}:
                altered["tracks"]["mic"]["accepted_frames"] = 6
                version = library.checkpoint_capture_health(
                    "s", altered, expected_health_version=version
                )
                before = library.capture_health("s")
                altered["checkpoint_seq"] = 0 if case == 15 else 2
                if case == 16:
                    altered["tracks"]["mic"]["accepted_frames"] = 0
            elif case in {20, 21}:
                if case == 20:
                    library._db.execute(
                        "UPDATE capture_health_runs SET payload='{' WHERE session_id='s'"
                    )
                    library._db.commit()
                    assert library.recover_session("s")["health_recovery"]["status"] == "DEFERRED"
                else:
                    library._db.execute(
                        "INSERT INTO capture_health_events(session_id,event_id,capture_run_id,ordinal,payload) VALUES('s','broken','run',1,'{')"
                    )
                    library._db.commit()
                    with pytest.raises(ValidationError, match="HEALTH_UNREADABLE"):
                        library.capture_health_details("s")
                return
            elif case == 22:
                assert library.delete_session("s")["deleted"]
                with pytest.raises((StateConflict, KeyError)):
                    library.checkpoint_capture_health("s", altered, expected_health_version=version)
                assert (
                    library._db.execute("SELECT COUNT(*) FROM capture_health_runs").fetchone()[0]
                    == 0
                )
                return
            with pytest.raises((ValidationError, StateConflict)):
                if case in {17, 18}:
                    library.finish_capture_health(
                        "s",
                        altered,
                        expected_health_version=version,
                        receipt=CaptureReceipt("run", True, True, False, False)
                        if case == 17
                        else True,
                    )
                elif case == 23:
                    library.record_capture_health("s", {})
                else:
                    library.checkpoint_capture_health("s", altered, expected_health_version=version)
            assert library.capture_health("s") == before


@pytest.mark.parametrize("row", B, ids=[f"G08-B-{i:02}" for i in range(1, 25)])
def test_limits(row, tmp_path):
    delta, target, tail = row
    if target == "payload":
        from recoryn.domain.capture_health import encoded
        from recoryn.storage import Library

        event = (
            fact(
                reason="UNKNOWN_TAIL",
                source="RECOVERY",
                kind="UNKNOWN_TAIL",
                start=None,
                end=None,
                range_quality="UNKNOWN",
                lost_frames=None,
                count_quality="UNKNOWN",
            )
            if tail
            else fact()
        )
        with Library(tmp_path) as library:
            seed(library, events=[event.to_dict()])
            # Untrusted persisted JSON can contain whitespace; no runtime padding API.
            raw = encoded(event.to_dict()).ljust(4096 + delta)
            assert len(raw.encode()) == 4096 + delta
            import hashlib

            library._db.execute(
                "UPDATE capture_health_events SET payload=?,digest=?",
                (raw, hashlib.sha256(raw.encode()).hexdigest()),
            )
            library._db.commit()
            if delta > 0:
                with pytest.raises(ValidationError, match="HEALTH_UNREADABLE"):
                    library.capture_health_details("s")
            else:
                page = library.capture_health_details("s")
                restored = next(r["value"] for r in page["rows"] if r["kind"] == "event")
                assert restored["lost_frames"] == (None if tail else 10)
    elif target == "buffer":
        events = [fact(event_id=f"e{i}").to_dict() for i in range(256 + delta)]
        if delta > 0:
            with pytest.raises(ValidationError, match="HEALTH_PAYLOAD_TOO_LARGE"):
                validate_snapshot(snapshot(events=events))
        else:
            assert len(validate_snapshot(snapshot(events=events))["events"]) == 256 + delta
    else:
        from recoryn.domain.capture_health import encoded
        from recoryn.storage import Library

        with Library(tmp_path) as library:
            if target == "page":
                seed(
                    library,
                    events=[
                        fact(
                            reason="UNKNOWN_TAIL",
                            source="RECOVERY",
                            kind="UNKNOWN_TAIL",
                            start=None,
                            end=None,
                            range_quality="UNKNOWN",
                            lost_frames=None,
                            count_quality="UNKNOWN",
                        ).to_dict()
                    ]
                    if tail
                    else [],
                )
                if delta > 0:
                    with pytest.raises(ValidationError, match="HEALTH_PAGE_LIMIT"):
                        library.capture_health_details("s", limit=256 + delta)
                else:
                    page = library.capture_health_details("s", limit=256 + delta)
                    assert len(page["rows"]) == (3 if tail else 2)
            else:
                library.create_session("s")
                data = {"padding": "", "tail_unknown": tail}
                overhead = len(encoded(data).encode())
                data["padding"] = "x" * (65536 + delta - overhead)
                assert len(encoded(data).encode()) == 65536 + delta
                if delta > 0:
                    with pytest.raises(ValidationError):
                        library.record_capture_health("s", data)
                    assert library.capture_health("s") == {}
                else:
                    library.record_capture_health("s", data)
                    assert library.capture_health("s") == data


BAD_GAPS = [
    {"source": "OTHER"},
    {"reason": "OTHER"},
    {"reason": []},
    {"range_quality": "OTHER"},
    {"range_quality": []},
    {"count_quality": "OTHER"},
    {"kind": "OTHER"},
    {"observation_bounds": (1, 2, 3)},
    {"observation_bounds": None},
    {"open": 1},
    {"detail_complete": 1},
    {"count_quality": "UNKNOWN"},
    {"lost_frames": None},
    {"reason": "DEVICE_LOST", "source": "DEVICE"},
    {"range_quality": "OBSERVED_CONTROL"},
    {
        "reason": "UNKNOWN_TAIL",
        "source": "RECOVERY",
        "lost_frames": None,
        "count_quality": "UNKNOWN",
        "kind": "UNKNOWN_TAIL",
    },
]


@pytest.mark.parametrize(
    "changes", BAD_GAPS, ids=[f"G08-X-DOM-G{i:02}" for i in range(len(BAD_GAPS))]
)
def test_gap_closed_grammar(changes):
    with pytest.raises(ValidationError):
        fact(**changes)


BAD_SNAPSHOTS = [
    {"arbitrary": "private"},
    {"schema_version": True},
    {"tracks": []},
    {"tracks": {}},
    {"tracks": {"mic": []}},
    *[
        {"tracks": {"mic": {**snapshot()["tracks"]["mic"], **changes}}}
        for changes in (
            {"raw": "private"},
            {"state": "OTHER"},
            {"reason": "OTHER"},
            {"detail_complete": 1},
            {"count_complete": 1},
            {"last_accepted_sequence": -1},
            {"loss_ranges": "bad"},
            {"loss_ranges": [[1]]},
            {"loss_ranges": [[2, 1]]},
            {"gaps": "bad"},
            {"gaps": [{"reason": "OTHER"}]},
            {
                "gaps": [
                    {
                        "reason": "QUEUE_DROP",
                        "first_sequence": 1,
                        "last_sequence": 1,
                        "frame_count": -1,
                        "capture_mono_ns": None,
                    }
                ]
            },
        )
    ],
    {"queue": "bad"},
    {"queue": {"private": "raw"}},
    {"queue": {"closed": 1}},
    {"queue": {"dropped_frames": -1}},
    {"events": "bad"},
    {"events": [{**fact().to_dict(), "epoch_id": "other"}]},
    {"events": [{**fact().to_dict(), "track_id": "other"}]},
    {"events": [{**fact().to_dict(), "session_id": "other"}]},
]


@pytest.mark.parametrize(
    "changes", BAD_SNAPSHOTS, ids=[f"G08-X-DOM-S{i:02}" for i in range(len(BAD_SNAPSHOTS))]
)
def test_snapshot_closed_grammar(changes):
    with pytest.raises(ValidationError):
        validate_snapshot(snapshot(**changes))


def test_g08_x_encoding_and_loss_identity():
    from recoryn.domain.capture_health import (
        GapFact,
        encoded,
        loss_totals,
        track_loss,
        transition_track,
    )

    with pytest.raises(ValidationError):
        encoded(object())
    with pytest.raises(ValidationError):
        GapFact.from_dict({"private": "raw"})
    with pytest.raises(ValidationError):
        transition_track("OTHER", "NONE", "READY")
    with pytest.raises(ValidationError, match="HEALTH_EVENT_CONFLICT"):
        loss_totals([fact().to_dict(), replace(fact(), start=9, lost_frames=11).to_dict()])
    assert track_loss({"loss_ranges": [[10, 20], [15, 25]], "media_loss_unknown": False}) == {
        "known_loss_frames": 15,
        "known_lower_bound": 15,
    }
    assert track_loss(
        {
            "loss_ranges": [],
            "media_loss_unknown": True,
            "dropped_frames": 6,
            "device_lost_frames": 4,
        }
    ) == {"known_loss_frames": None, "known_lower_bound": 6}
