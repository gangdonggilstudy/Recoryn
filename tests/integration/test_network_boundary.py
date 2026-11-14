"""Observe attempted network operations before importing Recoryn in a fresh process."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

_AUDIT_SCRIPT = r"""
import contextlib
import io
import json
import pathlib
import runpy
import sys

events = []
class NetworkForbidden(RuntimeError):
    pass

def audit(event, arguments):
    if event.startswith("socket."):
        events.append(event)
        raise NetworkForbidden(event)

sys.addaudithook(audit)
import socket
try:
    socket.getaddrinfo("recoryn-observer-positive.invalid", 443)
except NetworkForbidden:
    pass
assert events == ["socket.getaddrinfo"], events
events.clear()

before = set(pathlib.Path.cwd().rglob("*"))
mode = sys.argv[1]
if mode == "import":
    import recoryn
    import recoryn.domain
    import recoryn.capture
    import recoryn.storage
    import recoryn.jobs
    import recoryn.app
    import recoryn.cli
elif mode == "help":
    sys.argv = ["recoryn", "--help"]
    try:
        runpy.run_module("recoryn", run_name="__main__")
    except SystemExit as exc:
        assert exc.code in (None, 0), exc.code
elif mode == "workflow":
    from recoryn.cli import main
    root = pathlib.Path.cwd() / "library"
    capture = io.StringIO()
    with contextlib.redirect_stdout(capture):
        assert main(["--root", str(root), "simulate", "--seconds", "0.02"]) == 0
    session_id = json.loads(capture.getvalue())["session_id"]
    for arguments in (
        ["list"], ["inspect", session_id], ["recover", session_id],
        ["export", session_id, "--output", str(pathlib.Path.cwd() / "export")],
        ["delete", session_id], ["recover", session_id],
    ):
        with contextlib.redirect_stdout(io.StringIO()):
            assert main(["--root", str(root), *arguments]) == 0, arguments
else:
    raise AssertionError(mode)
assert events == [], events
if mode in ("import", "help"):
    assert set(pathlib.Path.cwd().rglob("*")) == before, "import/help created files"
print("P04_NETWORK_OBSERVER_OK")
"""


@pytest.mark.parametrize("mode", ("import", "help", "workflow"))
def test_import_and_help_are_observably_offline_and_side_effect_free(
    tmp_path: Path, mode: str
) -> None:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[2] / "src")
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONNOUSERSITE"] = "1"
    result = subprocess.run(
        [sys.executable, "-c", _AUDIT_SCRIPT, mode],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "P04_NETWORK_OBSERVER_OK" in result.stdout
