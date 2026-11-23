"""G02 finite representative spaces with hand-written decisions and a separate trace model."""

from __future__ import annotations

import importlib.util
import itertools
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from recoryn.security import ConsentRequest, ConsentScope, ConsentStore, Gateway, SecurityError
from recoryn.security._core import Endpoint

URL = "https://scope.example.test/v1"
FEATURES = ("stt", "summary", "diarization")
DATA = ("audio", "transcript", "context", "attachment")
ALPHABET = (
    "grant_A",
    "grant_LIBRARY",
    "capture_A",
    "capture_B",
    "revoke_A",
    "revoke_LIBRARY",
    "expire",
    "advance_policy",
    "restart",
)
CASE_IDS = {
    "GATE": [f"G02-GATE-{i:04d}" for i in range(9216)],
    "PICK": [f"G02-PICK-{i:03d}" for i in range(288)],
    "BIND": [f"G02-BIND-{i:03d}" for i in range(576)],
    "TRACE": [
        "G02-TRACE-" + ".".join(word)
        for n in range(5)
        for word in itertools.product(ALPHABET, repeat=n)
    ],
}


class Wire:
    def __init__(self) -> None:
        self.opens = 0
        self.writes: list[bytes] = []
        self.response = b"OK"

    def open(
        self, endpoint: Endpoint, headers: Mapping[str, str], body_length: int, timeout: float
    ) -> Wire:
        self.opens += 1
        return self

    def write(self, data: bytes, timeout: float) -> None:
        self.writes.append(data)

    def read(self, limit: int, timeout: float) -> bytes:
        output, self.response = self.response[:limit], self.response[limit:]
        return output

    def close(self) -> None:
        pass


def gateway(
    policy: ConsentStore, wire: Wire, scope: ConsentScope, request: ConsentRequest, bindings: Any
) -> Gateway:
    return Gateway(policy, transport=wire, expected_grants=bindings, chunk_bytes=1).for_session(
        request.session_id,
        request.session_generation,
        capability=request.capability,
        scope=scope,
        policy_version=request.policy_version,
    )


def _model_live(
    records: dict[str, tuple[bool, int, int, int, float]],
    key: str,
    execution: int,
    version: int,
    now: float,
) -> bool:
    record = records.get(key)
    return bool(
        record and record[0] and record[1] == execution and record[2] == version and now < record[4]
    )


def _observe_trace(
    policy: ConsentStore,
    records: dict[str, tuple[bool, int, int, int, float]],
    captures: dict[str, Any],
    actual_captures: dict[str, Any],
    execution: int,
    version: int,
    now: float,
    word: tuple[str, ...],
) -> None:
    for sid, key in (("A", "A"), ("B", "LIBRARY")):
        selected = ConsentScope.session("A") if sid == "A" else ConsentScope.library()
        req = ConsentRequest(sid, 0, "stt", version)
        expected_fresh = _model_live(records, key, execution, version, now)
        fresh = policy.capture_bindings("p", URL, ("audio",), scope=selected, request=req)
        assert bool(fresh) is expected_fresh, (word, sid, "fresh")
        assert policy.allowed("p", URL, "audio", scope=selected, request=req) is expected_fresh
        expected_old = (
            expected_fresh and captures.get(sid) is not None and captures[sid] == records.get(key)
        )
        actual_old = False
        if actual_captures.get(sid):
            try:
                policy.validate_binding(actual_captures[sid][0])
            except SecurityError:
                pass
            else:
                actual_old = True
        assert actual_old is expected_old, (word, sid, "old")


def test_scope_manifest_is_complete() -> None:
    families = dict(CASE_IDS)
    tests = Path(__file__).resolve().parents[1]
    for group in ("unit", "integration", "ui"):
        path = (
            tests
            / group
            / ("test_consent_scope_ui.py" if group == "ui" else "test_consent_scope.py")
        )
        spec = importlib.util.spec_from_file_location("g02_manifest_" + group, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        families.update(module.CASE_IDS)
    expected = {
        "GATE": 9216,
        "PICK": 288,
        "BIND": 576,
        "FROZEN": 504,
        "HB": 180,
        "TIME": 72,
        "TRACE": 7381,
        "UI": 182,
        "UI_FIX": 30,
        "MIG": 12,
        "TYPE": 22,
    }
    assert set(families) == set(expected)
    for name, count in expected.items():
        assert len(families[name]) == len(set(families[name])) == count, name
    all_ids = [value for values in families.values() for value in values]
    assert len(all_ids) == len(set(all_ids)) == 18463


def test_authorization_case_space(tmp_path: Path) -> None:
    seen: set[tuple[Any, ...]] = set()
    allowed = 0
    groups = itertools.product(
        ("session", "library"),
        FEATURES,
        ("none", "active", "revoked", "expired"),
        (False, True),
        (False, True),
        ("A", "B"),
    )
    for group_number, (
        scope_kind,
        grant_feature,
        state,
        deleted,
        current_execution,
        sid,
    ) in enumerate(groups):
        scope = ConsentScope.session("A") if scope_kind == "session" else ConsentScope.library()
        clock = [1000.0]
        with ConsentStore(
            tmp_path / f"gate-{group_number}.db", ttl_seconds=60, clock=lambda clock=clock: clock[0]
        ) as policy:
            policy.bind_session("A")
            policy.bind_session("B")
            grant = {"capability": grant_feature, "scope": scope, "policy_version": 2}
            if state != "none":
                policy.grant("p", URL, "audio", **grant)
            captured = {}
            for feature, current_policy in itertools.product(FEATURES, (False, True)):
                request = ConsentRequest(sid, 0, feature, 2 if current_policy else 1)
                try:
                    captured[feature, current_policy] = policy.capture_bindings(
                        "p", URL, ("audio",), scope=scope, request=request
                    )
                except SecurityError as error:
                    assert error.code == "CONSENT_POLICY_CHANGED"
                    captured[feature, current_policy] = error
            if state == "revoked":
                policy.revoke("p", URL, "audio", **grant)
            elif state == "expired":
                clock[0] = 1060.0
            if deleted:
                policy.revoke_session(sid)
            if not current_execution:
                with ConsentStore(policy.db_path, clock=lambda clock=clock: clock[0]):
                    pass
            with policy.coordinator.hold():
                for (
                    feature,
                    provider_match,
                    endpoint_match,
                    data_match,
                    current_policy,
                ) in itertools.product(
                    FEATURES, (False, True), (False, True), (False, True), (False, True)
                ):
                    row = (
                        scope_kind,
                        grant_feature,
                        state,
                        deleted,
                        current_execution,
                        sid,
                        feature,
                        provider_match,
                        endpoint_match,
                        data_match,
                        current_policy,
                    )
                    assert row not in seen
                    seen.add(row)
                    expected = (
                        (scope_kind == "library" or sid == "A")
                        and grant_feature == feature
                        and provider_match
                        and endpoint_match
                        and data_match
                        and current_policy
                        and current_execution
                        and state == "active"
                        and not deleted
                    )
                    wire = Wire()
                    request = ConsentRequest(sid, 0, feature, 2 if current_policy else 1)
                    bindings = captured[feature, current_policy]
                    try:
                        if isinstance(bindings, SecurityError):
                            raise bindings
                        view = gateway(policy, wire, scope, request, bindings)
                        result = view.request(
                            "p" if provider_match else "q",
                            URL if endpoint_match else URL + "-other",
                            "audio" if data_match else "transcript",
                            b"a",
                        )
                    except SecurityError as error:
                        assert not expected, (row, error.code)
                        # Earlier capture/view phases have their own recorded diagnostics.
                        if not current_policy:
                            assert error.code == "CONSENT_POLICY_CHANGED"
                        elif not current_execution:
                            assert error.code == "EXECUTION_CHANGED"
                        elif deleted:
                            assert error.code == "SESSION_REVOKED"
                        else:
                            assert error.code == "CONSENT_REQUIRED"
                    else:
                        assert expected and result == b"OK", row
                        allowed += 1
                    assert wire.opens == int(expected), row
                    assert wire.writes == ([b"a"] if expected else []), row
    assert len(seen) == 9216 and allowed == 9


def test_selected_scope_case_space(tmp_path: Path) -> None:
    # Rows are hand-written, columns are session-A/session-B/library-A/library-B.
    oracle = (
        (False, False, False, False),
        (True, False, False, False),
        (False, False, True, True),
        (True, False, True, True),
        (False, False, True, True),
        (True, False, False, False),
    )
    count = allowed = 0
    for index, (catalog, feature, data) in enumerate(itertools.product(range(6), FEATURES, DATA)):
        with ConsentStore(tmp_path / f"pick-{index}.db") as policy:
            policy.bind_session("A")
            policy.bind_session("B")
            for selected, present in (
                (ConsentScope.session("A"), catalog in (1, 3, 4, 5)),
                (ConsentScope.library(), catalog in (2, 3, 4, 5)),
            ):
                if present:
                    policy.grant(
                        "p", URL, data, capability=feature, scope=selected, policy_version=2
                    )
            if catalog in (4, 5):
                policy.revoke(
                    "p",
                    URL,
                    data,
                    capability=feature,
                    scope=ConsentScope.session("A") if catalog == 4 else ConsentScope.library(),
                    policy_version=2,
                )
            for column, (scope_kind, sid) in enumerate(
                (("session", "A"), ("session", "B"), ("library", "A"), ("library", "B"))
            ):
                scope = (
                    ConsentScope.session(sid) if scope_kind == "session" else ConsentScope.library()
                )
                request = ConsentRequest(sid, 0, feature, 2)
                assert (
                    policy.allowed("p", URL, data, scope=scope, request=request)
                    is oracle[catalog][column]
                )
                bindings = policy.capture_bindings("p", URL, (data,), scope=scope, request=request)
                wire = Wire()
                view = gateway(policy, wire, scope, request, bindings)
                expected = oracle[catalog][column]
                if expected:
                    assert view.request("p", URL, data, b"a") == b"OK"
                    allowed += 1
                else:
                    with pytest.raises(SecurityError, match="CONSENT_REQUIRED"):
                        view.request("p", URL, data, b"a")
                assert wire.opens == int(expected)
                count += 1
    assert count == 288 and allowed == 108


def test_binding_freshness_case_space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    count = allowed = 0
    for index, (scope_kind, feature, data) in enumerate(
        itertools.product(("session", "library"), FEATURES, DATA)
    ):
        scope = ConsentScope.session("A") if scope_kind == "session" else ConsentScope.library()
        other = ConsentScope.library() if scope_kind == "session" else ConsentScope.session("A")
        request = ConsentRequest("A", 0, feature, 2)
        with ConsentStore(tmp_path / f"bind-{index}.db") as policy:
            policy.bind_session("A")
            for selected in (scope, other):
                policy.grant("p", URL, data, capability=feature, scope=selected, policy_version=2)
            bindings = policy.capture_bindings("p", URL, (data,), scope=scope, request=request)
            with policy.coordinator.hold():
                for state, boundary in itertools.product(range(6), range(1, 5)):
                    wire = Wire()
                    view = gateway(policy, wire, scope, request, bindings)
                    original = policy.validate
                    calls = 0

                    def validate(
                        token: Any,
                        state: int = state,
                        boundary: int = boundary,
                        other: ConsentScope = other,
                        original: Any = original,
                    ) -> None:
                        nonlocal calls
                        calls += 1
                        if calls == boundary:
                            if state == 1:
                                token = replace(token, grant_id="old-id")
                            elif state == 2:
                                token = replace(token, grant_epoch=token.grant_epoch - 1)
                            elif state == 3:
                                token = replace(token, execution_id="old-execution")
                            elif state == 4:
                                token = replace(token, scope=other)
                            elif state == 5:
                                token = replace(
                                    token, request=replace(token.request, policy_version=1)
                                )
                        original(token)

                    with monkeypatch.context() as patch:
                        patch.setattr(policy, "validate", validate)
                        if state == 0:
                            assert view.request("p", URL, data, b"ab") == b"OK"
                            assert calls == 4
                            allowed += 1
                        else:
                            with pytest.raises(SecurityError) as error:
                                view.request("p", URL, data, b"ab")
                            assert calls == boundary
                            assert error.value.outcome_known is (boundary < 3)
                            assert len(wire.writes) == max(0, boundary - 2)
                    count += 1
    assert count == 576 and allowed == 96


def test_bounded_consent_traces(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from recoryn.security import consent

    # The alphabet does not change filesystem entries. Only cache the validated
    # immutable journal parent; actual exists/tombstone/session checks still run.
    journal = tmp_path / "deletion-journal"
    original_path = consent.check_path
    checked_journal = original_path(journal)
    monkeypatch.setattr(
        consent,
        "check_path",
        lambda path: checked_journal if path == journal else original_path(path),
    )
    clock = [1000.0]
    seen: set[str] = set()
    restarts = [0]
    with ConsentStore(tmp_path / "traces.db", clock=lambda: clock[0], ttl_seconds=60) as root:
        for sid in ("A", "B"):
            root.bind_session(sid)

        def walk(
            policy: ConsentStore,
            word: tuple[str, ...],
            records: dict[str, Any],
            captures: dict[str, Any],
            actual_captures: dict[str, Any],
            execution: int,
            version: int,
        ) -> None:
            case_id = "G02-TRACE-" + ".".join(word)
            assert case_id not in seen
            seen.add(case_id)
            _observe_trace(
                policy, records, captures, actual_captures, execution, version, clock[0], word
            )
            if len(word) == 4:
                return
            for event in ALPHABET:
                next_word = (*word, event)
                next_records, next_captures, next_actual = (
                    records.copy(),
                    captures.copy(),
                    actual_captures.copy(),
                )
                old_time, old_last_clock = clock[0], policy._last_clock
                if event == "restart":
                    # A new real Store reads a snapshot containing this branch's
                    # uncommitted rows, then rotates the execution generation.
                    # Same-file/process restart is additionally checked in MIG
                    # and the existing subprocess regression. The parent Store
                    # belongs exclusively to the sibling histories, not this run.
                    restarts[0] += 1
                    db = tmp_path / f"restart-{restarts[0]}.db"
                    db.write_bytes(policy._db.serialize())
                    with (
                        ConsentStore(
                            db, clock=lambda: clock[0], ttl_seconds=60, policy_version=version
                        ) as child,
                        child.coordinator.hold(),
                    ):
                        child._db.execute("BEGIN")
                        try:
                            walk(
                                child,
                                next_word,
                                next_records,
                                next_captures,
                                next_actual,
                                execution + 1,
                                version,
                            )
                        finally:
                            child._db.execute("ROLLBACK")
                    clock[0], policy._last_clock = old_time, old_last_clock
                    continue
                # Savepoints isolate sibling fixtures; no transport or concurrent
                # commit is simulated here. HB tests use real committed barriers.
                savepoint = "branch_" + str(len(word))
                policy._db.execute("SAVEPOINT " + savepoint)
                next_version = version
                try:
                    if event.startswith("grant_") or event.startswith("revoke_"):
                        key = event.split("_", 1)[1]
                        selected = (
                            ConsentScope.session("A") if key == "A" else ConsentScope.library()
                        )
                        previous = records.get(key)
                        if event.startswith("grant_"):
                            policy.grant(
                                "p",
                                URL,
                                "audio",
                                capability="stt",
                                scope=selected,
                                policy_version=version,
                            )
                            next_records[key] = (
                                True,
                                execution,
                                version,
                                (previous[3] if previous else 0) + 1,
                                clock[0] + 60,
                            )
                        else:
                            policy.revoke(
                                "p",
                                URL,
                                "audio",
                                capability="stt",
                                scope=selected,
                                policy_version=version,
                            )
                            if previous:
                                next_records[key] = (
                                    False,
                                    previous[1],
                                    previous[2],
                                    previous[3] + 1,
                                    previous[4],
                                )
                    elif event.startswith("capture_"):
                        sid = event[-1]
                        key = "A" if sid == "A" else "LIBRARY"
                        selected = (
                            ConsentScope.session("A") if sid == "A" else ConsentScope.library()
                        )
                        next_actual[sid] = policy.capture_bindings(
                            "p",
                            URL,
                            ("audio",),
                            scope=selected,
                            request=ConsentRequest(sid, 0, "stt", version),
                        )
                        next_captures[sid] = (
                            records.get(key)
                            if _model_live(records, key, execution, version, clock[0])
                            else None
                        )
                    elif event == "expire":
                        clock[0] += 1000
                    else:
                        next_version += 1
                        policy.advance_policy_version(next_version)
                    walk(
                        policy,
                        next_word,
                        next_records,
                        next_captures,
                        next_actual,
                        execution,
                        next_version,
                    )
                finally:
                    policy._db.execute("ROLLBACK TO " + savepoint)
                    policy._db.execute("RELEASE " + savepoint)
                    clock[0], policy._last_clock = old_time, old_last_clock

        with root.coordinator.hold():
            root._db.execute("BEGIN")
            try:
                walk(root, (), {}, {}, {}, 0, 2)
            finally:
                root._db.execute("ROLLBACK")
    assert seen == set(CASE_IDS["TRACE"])
    assert len(seen) == 7381 and restarts[0] == 820
