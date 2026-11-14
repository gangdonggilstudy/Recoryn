"""Executable CLI checks with independent WAV sample counts."""

from __future__ import annotations

import json
import subprocess
import sys
import wave
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "recoryn", *args], capture_output=True, text=True, timeout=30
    )


def test_help_and_version_do_not_initialize_storage(tmp_path: Path) -> None:
    root = tmp_path / "not-created"
    assert run_cli("--root", str(root), "--help").returncode == 0
    assert run_cli("--version").returncode == 0
    assert not root.exists()


def test_two_track_recording_export_and_delete(tmp_path: Path) -> None:
    root = tmp_path / "library"
    completed = run_cli("--root", str(root), "simulate", "--seconds", "0.02")
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(completed.stdout)
    session = result["session_id"]
    inspected = run_cli("--root", str(root), "inspect", session)
    assert inspected.returncode == 0, inspected.stdout
    details = json.loads(inspected.stdout)
    assert details["state"] == "FINALIZED"
    assert {item["track_id"] for item in details["chunks"]} == {"mic", "system"}
    listed = run_cli("--root", str(root), "list")
    assert json.loads(listed.stdout) == [{"session_id": session, "state": "FINALIZED"}]
    output = tmp_path / "exported"
    exported = run_cli("--root", str(root), "export", session, "--output", str(output))
    assert exported.returncode == 0, exported.stdout + exported.stderr
    manifest = json.loads((output / "export.json").read_text(encoding="utf-8"))
    assert len(manifest["files"]) == 2
    for item in manifest["files"]:
        with wave.open(str(output / item["file"]), "rb") as audio:
            expected_rate = 44100 if item["track_id"] == "mic" else 48000
            assert audio.getframerate() == expected_rate
            assert audio.getnframes() == int(expected_rate * 0.02)
            assert audio.getnchannels() == (1 if item["track_id"] == "mic" else 2)
    assert run_cli("--root", str(root), "export", session, "--output", str(output)).returncode == 1
    assert run_cli("--root", str(root), "recover", session).returncode == 0
    assert run_cli("--root", str(root), "delete", session).returncode == 0
    assert json.loads(run_cli("--root", str(root), "list").stdout) == []
    assert run_cli("--root", str(root), "recover", session).returncode != 0 or (
        not json.loads(run_cli("--root", str(root), "list").stdout)
    )


@pytest.mark.parametrize("duration", ["nan", "inf", "0", "-1", "86401"])
def test_invalid_duration_does_not_create_library(tmp_path: Path, duration: str) -> None:
    root = tmp_path / "unused"
    assert run_cli("--root", str(root), "simulate", "--seconds", duration).returncode == 2
    assert not root.exists()
