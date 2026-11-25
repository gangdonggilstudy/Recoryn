"""G16 unit rows: L (file inputs x library x restart = 96) and P (paths x op x permission = 32).

Expected outcomes are hand-written bytes and strings from
docs/testing/g16-device-policy-cases.md section 5; the product parser, enum list or
serializer is never used to build an expected value. Real TEMP files only; the user's
real settings location is never read or written.
"""

from __future__ import annotations

import hashlib
import itertools
import sys
from pathlib import Path
from typing import Any

import pytest

from recoryn.app.device_policy import DevicePolicyStore, PolicyIo
from recoryn.storage import Library

pytestmark = pytest.mark.unit

CPU, GPU, FALLBACK = "CPU_ONLY", "GPU_ONLY", "GPU_WITH_CPU_FALLBACK_ALLOWED"
V1 = b'{"schema_version":1,"execution_policy":"%s"}'


def v1(policy: str) -> bytes:
    return V1 % policy.encode()


def padded(total: int) -> bytes:
    body = v1(GPU)
    return body + b" " * (total - len(body))


# L24, in the contract's order: (name, file bytes or None, state, policy, reason).
L_INPUTS: list[tuple[str, bytes | None, str, str, str]] = [
    ("missing", None, "DEFAULT", CPU, ""),
    ("cpu", v1(CPU), "RESTORED", CPU, ""),
    ("gpu", v1(GPU), "RESTORED", GPU, ""),
    ("fallback", v1(FALLBACK), "RESTORED", FALLBACK, ""),
    ("empty", b"", "INVALID", CPU, "SYNTAX"),
    ("broken", b'{"schema_version":1,', "INVALID", CPU, "SYNTAX"),
    ("utf8", b'{"schema_version":1,"execution_policy":"\xff\xfe"}', "INVALID", CPU, "SYNTAX"),
    (
        "duplicate",
        b'{"schema_version":1,"execution_policy":"GPU_ONLY","execution_policy":"CPU_ONLY"}',
        "INVALID",
        CPU,
        "SYNTAX",
    ),
    (
        "array",
        b'[{"schema_version":1,"execution_policy":"GPU_ONLY"}]',
        "INVALID",
        CPU,
        "NOT_OBJECT",
    ),
    ("no_version", b'{"execution_policy":"GPU_ONLY"}', "INVALID", CPU, "VERSION_MISSING"),
    (
        "version0",
        b'{"schema_version":0,"execution_policy":"GPU_ONLY"}',
        "INVALID",
        CPU,
        "VERSION_UNSUPPORTED",
    ),
    (
        "version2",
        b'{"schema_version":2,"execution_policy":"GPU_ONLY"}',
        "FUTURE_VERSION",
        CPU,
        "FUTURE_VERSION",
    ),
    (
        "version_true",
        b'{"schema_version":true,"execution_policy":"GPU_ONLY"}',
        "INVALID",
        CPU,
        "VERSION_UNSUPPORTED",
    ),
    (
        "version_text",
        b'{"schema_version":"1","execution_policy":"GPU_ONLY"}',
        "INVALID",
        CPU,
        "VERSION_UNSUPPORTED",
    ),
    ("no_policy", b'{"schema_version":1}', "INVALID", CPU, "FIELDS"),
    (
        "policy_null",
        b'{"schema_version":1,"execution_policy":null}',
        "INVALID",
        CPU,
        "POLICY_UNSUPPORTED",
    ),
    (
        "policy_true",
        b'{"schema_version":1,"execution_policy":true}',
        "INVALID",
        CPU,
        "POLICY_UNSUPPORTED",
    ),
    (
        "policy_number",
        b'{"schema_version":1,"execution_policy":1}',
        "INVALID",
        CPU,
        "POLICY_UNSUPPORTED",
    ),
    (
        "policy_unknown",
        b'{"schema_version":1,"execution_policy":"TPU_ONLY"}',
        "INVALID",
        CPU,
        "POLICY_UNSUPPORTED",
    ),
    (
        "policy_auto",
        b'{"schema_version":1,"execution_policy":"AUTO"}',
        "INVALID",
        CPU,
        "POLICY_UNSUPPORTED",
    ),
    (
        "extra_key",
        b'{"schema_version":1,"execution_policy":"GPU_ONLY","note":"x"}',
        "INVALID",
        CPU,
        "FIELDS",
    ),
    ("size4095", padded(4095), "RESTORED", GPU, ""),
    ("size4096", padded(4096), "RESTORED", GPU, ""),
    ("size4097", padded(4097), "INVALID", CPU, "SIZE_LIMIT"),
]
L_ROWS = list(itertools.product(range(len(L_INPUTS)), ("A", "B"), ("first", "restart")))
L_CASES = [pytest.param(*row, id=f"G16-L-{i:03d}") for i, row in enumerate(L_ROWS, 1)]


def tree(root: Path) -> dict[str, bytes]:
    """Every file below root with its bytes (directories are implied)."""
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def expected_revision(content: bytes | None) -> str:
    if content is None:
        return "ABSENT"
    return hashlib.sha256(content[:4097]).hexdigest() + ":" + str(len(content))


@pytest.mark.parametrize(("index", "library", "mode"), L_CASES)
def test_load_reconciliation_is_per_pc_and_read_only(
    tmp_path: Path, index: int, library: str, mode: str
) -> None:
    name, content, state, policy, reason = L_INPUTS[index]
    appdata = tmp_path / "LocalAppData"
    settings = appdata / "Recoryn" / "preferences" / "device-policy.json"
    if content is not None:
        settings.parent.mkdir(parents=True)
        settings.write_bytes(content)
    before = tree(appdata)
    environ = {"LOCALAPPDATA": str(appdata)}
    root = tmp_path / ("library-" + library)
    with Library(root):
        store = DevicePolicyStore.for_user(environ)
        assert store.path() == settings  # independent of which library is open
        result = store.load()
        if mode == "restart":  # a new instance reads the file again, not a memory value
            again = DevicePolicyStore.for_user(environ).load()
            assert again == result
            result = again
    assert (result.state, result.policy, result.reason) == (state, policy, reason), name
    assert result.revision == expected_revision(content)
    assert tree(appdata) == before  # reading creates, repairs and deletes nothing
    assert not (appdata / "Recoryn" / "preferences").exists() or content is not None
    assert not list(root.rglob("device-policy*"))  # nothing lands in the library root


# --- P: paths 8 x read/save 2 x permission normal/denied 2 = 32 --------------------

P_KINDS = ("local", "relative", "unc", "extended", "device", "network", "reparse", "hardlink")
P_ROWS = list(itertools.product(P_KINDS, ("read", "save"), ("allowed", "denied")))
P_CASES = [pytest.param(*row, id=f"G16-P-{i:02d}") for i, row in enumerate(P_ROWS, 1)]
P_EXPECT = {
    # kind: (read state, read reason, save state, save reason) when access is allowed.
    "local": ("RESTORED", "", "SAVED", ""),
    "relative": ("UNAVAILABLE", "PATH_NOT_ABSOLUTE", "FAILED", "PATH_NOT_ABSOLUTE"),
    "unc": ("UNAVAILABLE", "PATH_NOT_LOCAL", "FAILED", "PATH_NOT_LOCAL"),
    "extended": ("UNAVAILABLE", "PATH_NOT_LOCAL", "FAILED", "PATH_NOT_LOCAL"),
    "device": ("UNAVAILABLE", "PATH_NOT_LOCAL", "FAILED", "PATH_NOT_LOCAL"),
    "network": ("UNAVAILABLE", "PATH_NOT_LOCAL", "FAILED", "PATH_NOT_LOCAL"),
    "reparse": ("UNAVAILABLE", "PATH_UNSAFE", "FAILED", "PATH_UNSAFE"),
    "hardlink": ("UNAVAILABLE", "PATH_UNSAFE", "FAILED", "PATH_UNSAFE"),
}


class Recorder(PolicyIo):
    """Records every OS-level step; ``denied`` is a fake OS answer for opens only."""

    def __init__(self, *, denied: bool, drive: int = 3) -> None:
        self.denied = denied
        self.drive = drive
        self.calls: list[str] = []

    def drive_type(self, anchor: str) -> int:
        self.calls.append("drive")
        return self.drive

    def check(self, path: Path) -> None:
        self.calls.append("check")
        super().check(path)

    def read(self, path: Path, limit: int) -> tuple[bytes, int] | None:
        self.calls.append("read")
        if self.denied:
            raise PermissionError("G16 fake denial")
        return super().read(path, limit)

    def try_lock(self, path: Path, *, create: bool) -> Any:
        self.calls.append("lock")
        if self.denied:
            raise PermissionError("G16 fake denial")
        return super().try_lock(path, create=create)

    def open_new(self, path: Path) -> Any:
        self.calls.append("open_new")
        if self.denied:
            raise PermissionError("G16 fake denial")
        return super().open_new(path)


def p_location(tmp_path: Path, kind: str, *, existing: bool) -> tuple[Path, Path | None]:
    """(settings path, the file whose bytes must stay unchanged or None)."""
    local = tmp_path / "LocalAppData" / "Recoryn" / "preferences" / "device-policy.json"
    if kind == "local":
        if existing:
            local.parent.mkdir(parents=True)
            local.write_bytes(v1(GPU))
        return local, local if existing else None
    if kind == "relative":
        return Path("Recoryn") / "preferences" / "device-policy.json", None
    if kind == "unc":
        return Path(r"\\g16-server\share\Recoryn\preferences\device-policy.json"), None
    if kind == "extended":
        return Path("\\\\?\\" + str(local)), None
    if kind == "device":
        return Path(r"\\.\GLOBALROOT\Recoryn\device-policy.json"), None
    if kind == "network":
        return Path(local.anchor) / "Recoryn" / "preferences" / "device-policy.json", None
    if kind == "reparse":
        import _winapi

        target = tmp_path / "outside"
        target.mkdir()
        (target / "device-policy.json").write_bytes(v1(GPU))
        local.parent.parent.mkdir(parents=True)
        _winapi.CreateJunction(str(target), str(local.parent))
        return local, target / "device-policy.json"
    local.parent.mkdir(parents=True)
    local.write_bytes(v1(GPU))
    (local.parent / "second-name.json").hardlink_to(local)
    return local, local


@pytest.mark.parametrize(("kind", "operation", "permission"), P_CASES)
def test_only_local_inspected_paths_are_opened(
    tmp_path: Path, kind: str, operation: str, permission: str
) -> None:
    if kind == "reparse" and sys.platform != "win32":
        pytest.skip("an actual NTFS junction requires Windows")
    path, watched = p_location(tmp_path, kind, existing=operation == "read")
    before = watched.read_bytes() if watched is not None else None
    io = Recorder(denied=permission == "denied", drive=4 if kind == "network" else 3)
    store = DevicePolicyStore(path, io=io)
    try:
        if operation == "read":
            result: Any = store.load()
        else:
            result = store.save(GPU, observed_revision=None)
    finally:
        if kind == "reparse":
            path.parent.rmdir()  # only the junction itself, never its target
    read_state, read_reason, save_state, save_reason = P_EXPECT[kind]
    state, reason = (read_state, read_reason) if operation == "read" else (save_state, save_reason)
    if kind == "local" and permission == "denied":
        state = "UNAVAILABLE" if operation == "read" else "FAILED"
        reason = "IO_ERROR"
    assert (result.state, result.reason) == (state, reason)
    opened = [call for call in io.calls if call in ("read", "lock", "open_new")]
    if kind in ("relative", "unc", "extended", "device"):
        assert io.calls == []  # refused by its text: nothing is resolved or queried
    elif kind == "network":
        assert io.calls == ["drive"]  # the local mount table only; nothing on the share
    elif kind in ("reparse", "hardlink"):
        assert opened == []  # the fake denial is never even reached
    if watched is not None:
        assert watched.read_bytes() == before
    if kind == "local" and operation == "save" and permission == "allowed":
        assert path.read_bytes() == v1(GPU)  # exactly the two allowed keys


def test_declared_unit_denominators_are_complete_and_unique() -> None:
    assert len(L_INPUTS) == 24 and len({row[0] for row in L_INPUTS}) == 24
    assert len(L_CASES) == 24 * 2 * 2 == 96 and len(P_CASES) == 8 * 2 * 2 == 32
    assert [c.id for c in L_CASES] == [f"G16-L-{i:03d}" for i in range(1, 97)]
    assert [c.id for c in P_CASES] == [f"G16-P-{i:02d}" for i in range(1, 33)]
    assert len(padded(4095)) == 4095 and len(padded(4097)) == 4097
