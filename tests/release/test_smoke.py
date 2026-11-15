"""Frozen smoke playback verdicts (L04-P01, L04-D02). Case space F in
docs/testing/l04-media-backend-cases.md; tables are written by hand."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest
import release_smoke as smoke

VERIFIED = "PCM_SINK_PLAYED_MUTED_FROM_EXACT_FRAME"


@pytest.mark.parametrize(
    ("playback", "status"),
    [
        ({"status": VERIFIED}, "PASS"),
        ({"status": "NO_AUDIO_OUTPUT_DEVICE_NOT_RUN"}, "PLAYBACK_NOT_VERIFIED"),
        ({}, "PLAYBACK_NOT_VERIFIED"),
        ({"status": "LOADED_SEEKED_PLAYED_MUTED_SILENCE"}, "PLAYBACK_NOT_VERIFIED"),
    ],
)
def test_not_run_or_unverified_playback_is_never_a_pass(playback: dict, status: str) -> None:
    assert smoke.overall_status(playback) == status


@pytest.mark.parametrize(
    ("first", "second", "accepted"),
    [
        (2200, 2650, True),  # measured on the development machine
        (2000, 2200, True),  # lower bounds
        (2400, 2900, True),  # upper bounds
        (2500, 2500, False),  # L04-D02 fault: seek +500 ms and no playback
        (2000, 2000, False),  # started but never advanced
        (2401, 2650, False),  # landed beyond the requested position
        (1999, 2400, False),  # landed before it
        (2200, 2399, False),  # advanced too little (199 ms)
        (2200, 2901, False),  # ran ahead of the wall clock
        (None, 2650, False),
        (2200, None, False),
    ],
)
def test_progress_oracle(first: int | None, second: int | None, accepted: bool) -> None:
    assert smoke.progress_ok(first, second) is accepted


def test_probe_without_output_device_reports_not_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = types.ModuleType("PySide6.QtMultimedia")
    module.QMediaDevices = SimpleNamespace(audioOutputs=lambda: [])  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "PySide6.QtMultimedia", module)
    result = smoke._playback_probe(tmp_path)
    assert result == {"status": "NO_AUDIO_OUTPUT_DEVICE_NOT_RUN"}
    assert smoke.overall_status(result) != "PASS"
    assert list(tmp_path.iterdir()) == []  # nothing was written or played
