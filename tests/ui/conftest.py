"""G-P16: every MainWindow in tests/ui uses the real policy store on its own TEMP path.

The product's initialization and real load/save path still run (no always-successful
fake); only the location is isolated, so no test reads or writes the user's settings.
Module scope so module-scoped windows are covered too; undone at each module's end.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterator

import pytest

from recoryn.app.device_policy import DevicePolicyStore


@pytest.fixture(scope="module", autouse=True)
def isolated_device_policy(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    import recoryn.ui.main as main_module

    base = tmp_path_factory.mktemp("g16-policy")
    windows = itertools.count()

    def store() -> DevicePolicyStore:
        root = base / f"window-{next(windows)}" / "Recoryn" / "preferences"
        return DevicePolicyStore(root / "device-policy.json")

    patch = pytest.MonkeyPatch()
    patch.setattr(main_module, "default_policy_store", store)
    patch.setenv("LOCALAPPDATA", str(base / "LocalAppData"))  # a stray user path is TEMP too
    try:
        yield
    finally:
        patch.undo()
