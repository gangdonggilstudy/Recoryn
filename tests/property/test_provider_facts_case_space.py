"""Static 302-row manifest plus selection-aware, independent call-report audit."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

import pytest

pytestmark = pytest.mark.property
SIZES = {"D": 90, "S": 63, "P": 20, "T": 21, "M": 36, "L": 72}
_AUDIT = pytest.StashKey[object]()


class _Calls:
    def __init__(self) -> None:
        self.ids: list[str] = []

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        match = re.search(r"GS04-[A-Z]-\d{3}", report.nodeid)
        if report.when == "call" and match:
            self.ids.append(match.group())


@pytest.fixture(scope="session", autouse=True)
def execution_audit(request: pytest.FixtureRequest) -> None:
    """One recorder even when this fixture is re-exported by several test modules."""
    if _AUDIT in request.config.stash:
        return
    from tests.unit.test_provider_facts import EXECUTED

    EXECUTED.clear()
    recorder = _Calls()
    request.config.stash[_AUDIT] = recorder
    request.config.pluginmanager.register(recorder, "gs04a-execution-audit")

    def finish() -> None:
        try:
            assert Counter(EXECUTED) == Counter(recorder.ids)
            assert all(n == 1 for n in Counter(EXECUTED).values())
        finally:
            request.config.pluginmanager.unregister(recorder)

    request.addfinalizer(finish)


def declared_ids() -> list[str]:
    from tests.ui import (
        test_local_server_notice_ui,
        test_managed_install_ui,
        test_provider_facts_ui,
    )
    from tests.unit import test_provider_facts, test_summary_templates

    ids: list[str] = []
    for module in (
        test_provider_facts,
        test_summary_templates,
        test_provider_facts_ui,
        test_managed_install_ui,
        test_local_server_notice_ui,
    ):
        for name, function in vars(module).items():
            if (
                not name.startswith("test_")
                or getattr(function, "__module__", None) != module.__name__
            ):
                continue
            for mark in getattr(function, "pytestmark", ()):
                if mark.name != "parametrize":
                    continue
                explicit: Any = mark.kwargs.get("ids")
                for index, parameter in enumerate(mark.args[1]):
                    cid = explicit[index] if explicit else getattr(parameter, "id", None)
                    if isinstance(cid, str) and cid.startswith("GS04-"):
                        ids.append(cid)
    return ids


def test_case_space() -> None:
    expected = {
        f"GS04-{family}-{n:03d}" for family, size in SIZES.items() for n in range(1, size + 1)
    }
    actual = declared_ids()
    assert len(expected) == 302
    assert len(actual) == len(set(actual)) == 302
    assert set(actual) == expected
    assert not any(re.match(r"GS04-[NCH]-", cid) for cid in actual)
