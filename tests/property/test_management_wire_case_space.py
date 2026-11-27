from __future__ import annotations

import ast
import builtins
import ctypes
import functools
import inspect
import io
import json
import os
import socket
import sqlite3
import subprocess
import sys
import threading
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

import pytest

from recoryn import schema as s


# Shared test instrumentation is copied into each owned test module; no build dependency.
def _wire_data():
    return json.loads(
        (
            Path(__file__).resolve().parents[1] / "fixtures/g09_management_wire_literals_v1.json"
        ).read_text(encoding="utf8")
    )


@contextmanager
def _management_no_io(events):
    def denied(name):
        def stop(*args, **kwargs):
            events.append(name)
            raise AssertionError("MANAGEMENT_IO_ATTEMPT:" + name)

        return stop

    with pytest.MonkeyPatch.context() as patch:
        targets = [
            (builtins, "open"),
            (io, "open"),
            (sqlite3, "connect"),
            (socket, "socket"),
            (socket, "create_connection"),
            (socket, "getaddrinfo"),
            (socket, "gethostbyname"),
            (subprocess, "Popen"),
            (threading.Thread, "start"),
            (ctypes, "CDLL"),
            (ctypes, "PyDLL"),
            (ctypes.LibraryLoader, "LoadLibrary"),
        ]
        targets += [
            (os, name)
            for name in (
                "open",
                "fdopen",
                "read",
                "write",
                "stat",
                "lstat",
                "listdir",
                "scandir",
                "mkdir",
                "remove",
                "unlink",
                "rename",
                "replace",
                "system",
            )
        ]
        targets += [(ctypes, name) for name in ("WinDLL", "OleDLL") if hasattr(ctypes, name)]
        for module, names in (
            ("win32cred", ("CredRead", "CredWrite", "CredDelete")),
            ("keyring", ("get_password", "set_password", "delete_password")),
        ):
            if module in sys.modules:
                targets += [
                    (sys.modules[module], name)
                    for name in names
                    if hasattr(sys.modules[module], name)
                ]
        for owner, name in targets:
            patch.setattr(owner, name, denied(owner.__name__ + "." + name))
        yield


@pytest.fixture(scope="session", autouse=True)
def _management_selected_audit(request):
    if hasattr(request.config, "_g09_management_audit"):
        yield request.config._g09_management_audit
        return
    owned = (
        "tests/unit/test_schema_catalog.py::",
        "tests/unit/test_management_wire_api.py::",
        "tests/property/test_management_wire_case_space.py::",
    )
    state = {
        "selected": [
            item.nodeid for item in request.session.items if item.nodeid.startswith(owned)
        ],
        "reports": [],
        "calls": [],
        "IO_attempts": [],
        "active": request.session.items[0].nodeid if request.session.items else None,
    }
    selected_set = set(state["selected"])
    request.config._g09_management_audit = state
    patch = pytest.MonkeyPatch()

    def protect(real, name):
        @functools.wraps(real)
        def observed(*args, **kwargs):
            event = {"node": state["active"], "name": name, "status": "ENTERED"}
            actual = inspect.unwrap(real)
            event["actual_file"] = actual.__code__.co_filename
            event["actual_globals_schema"] = actual.__globals__ is vars(s)
            state["calls"].append(event)
            try:
                with _management_no_io(state["IO_attempts"]):
                    value = real(*args, **kwargs)
            except BaseException as error:
                event.update(
                    status="RAISED",
                    error_type=type(error).__name__,
                    kind=getattr(error, "kind", None),
                )
                raise
            event["status"] = "RETURNED"
            return value

        return observed

    for name in ("decode_management", "encode_management"):
        patch.setattr(s, name, protect(getattr(s, name), name))
    for cls in (s._FrozenWireData, s.ProgressDocument):
        patch.setattr(
            cls, "__post_init__", protect(cls.__post_init__, cls.__name__ + ".__post_init__")
        )

    class Audit:
        def pytest_runtest_setup(self, item):
            state["active"] = item.nodeid

        def pytest_runtest_logreport(self, report):
            if report.nodeid in selected_set:
                state["reports"].append(
                    {"node": report.nodeid, "when": report.when, "outcome": report.outcome}
                )

        def pytest_sessionfinish(self, session, exitstatus):
            state["exitstatus"] = int(exitstatus)
            expected = set(state["selected"])
            counts = Counter(r["node"] for r in state["reports"] if r["when"] == "call")
            state["call_counts"] = {n: counts[n] for n in expected}
            state["selected_call_once"] = all(n == 1 for n in state["call_counts"].values())
            state["nonselected_call_nodes"] = sorted(
                {r["node"] for r in state["reports"] if r["when"] == "call"} - expected
            )
            if exitstatus == 0:
                assert state["selected_call_once"] and not state["nonselected_call_nodes"]
                assert not state["IO_attempts"]
            destination = os.environ.get("RECORYN_MANAGEMENT_AUDIT")
            if destination:
                Path(destination).write_text(
                    json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf8"
                )

    request.config.pluginmanager.register(Audit(), "g09_management_selected_audit")
    yield state
    patch.undo()


def _wire_capture(call):
    try:
        return call(), None
    except Exception as error:
        return None, error


def _wire_closed(error, goal="WIRE_EXPECTED_MALFORMED_AFTER_ACTUAL_API", kind="MALFORMED"):
    assert error is not None, goal
    assert type(error) is s.SchemaWireError
    assert (
        error.kind == kind
        and str(error) == kind
        and repr(error) == "SchemaWireError(" + kind + ")"
        and error.args == (kind,)
    )


pytestmark = pytest.mark.property
_WIRE_FIXTURE = _wire_data()


def test_management_wire_plan_audit():
    ids = [r["id"] for r in _WIRE_FIXTURE["formal70"]]
    assert len(ids) == len(set(ids)) == 70
    assert Counter(r["family"] for r in _WIRE_FIXTURE["formal70"]) == {
        "CAW": 26,
        "CAN": 18,
        "CAM": 6,
        "SC": 12,
        "FP": 8,
    }
    assert _WIRE_FIXTURE["active_local40"] == [
        r["id"] for r in _WIRE_FIXTURE["caw"] + _WIRE_FIXTURE["can"]
    ]
    assert len(set(_WIRE_FIXTURE["active_local40"])) == 40
    assert set(_WIRE_FIXTURE["active_local40"]).isdisjoint(_WIRE_FIXTURE["deferred10"])
    assert len(set(_WIRE_FIXTURE["deferred10"])) == 10
    assert _WIRE_FIXTURE["formal_denominator_increment"] == 0


def test_management_wire_primary_inventory():
    base = Path(__file__).resolve().parents[1]
    tree = ast.parse((base / "unit/test_schema_catalog.py").read_bytes())
    functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert {
        "test_component_shape_wire",
        "test_schema_catalog_id_audit",
        "test_management_wire_types",
        "test_management_tagged_null",
    } <= set(functions)
    assert len(_WIRE_FIXTURE["caw"]) == 26 and len(_WIRE_FIXTURE["can"]) == 14
    active = set(_WIRE_FIXTURE["active_local40"])
    declared = {r["id"]: r["original_primary"] for r in _WIRE_FIXTURE["formal70"]}
    for row in _WIRE_FIXTURE["caw"]:
        assert (
            declared[row["id"]]
            == "tests/unit/test_schema_catalog.py::test_management_wire_types[" + row["id"] + "]"
        )
        assert row["id"] in active
    for row in _WIRE_FIXTURE["can"]:
        assert (
            declared[row["id"]]
            == "tests/unit/test_schema_catalog.py::test_management_tagged_null[" + row["id"] + "]"
        )
        assert row["id"] in active
    nodes = _WIRE_FIXTURE["planned_nodes"]
    assert len(nodes) == len(set(nodes)) == 349
    for ident in _WIRE_FIXTURE["deferred10"]:
        assert not any("[" + ident + "]" in n for n in nodes)


def _private_current_profile_nodes():
    base = "tests/unit/test_schema_catalog.py::"
    return {
        base + "test_private_current_profile_candidate[PRIVATE-CP" + str(i).zfill(2) + "]"
        for i in range(1, 52)
    } | {
        base + "test_private_current_profile_literal_audit",
        base + "test_private_current_profile_order_and_immutability",
    }


def test_management_wire_selected_scope(request):
    own = (
        "tests/unit/test_schema_catalog.py::",
        "tests/unit/test_management_wire_api.py::",
        "tests/property/test_management_wire_case_space.py::",
    )
    selected = [item.nodeid for item in request.session.items if item.nodeid.startswith(own)]
    state = request.config._g09_management_audit
    assert selected == state["selected"]
    assert len(selected) == len(set(selected))
    assert set(selected) <= set(_WIRE_FIXTURE["planned_nodes"]) | _private_current_profile_nodes()
    assert not any(
        item.get_closest_marker("skip") or item.get_closest_marker("xfail")
        for item in request.session.items
        if item.nodeid in set(selected)
    )
