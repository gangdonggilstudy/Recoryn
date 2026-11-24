"""G08 finalized export: full canonical rows, independent digest and completion."""

import hashlib
import json
from itertools import product

import pytest

from recoryn.cli import _export
from recoryn.domain import SessionState
from recoryn.domain.capture_health import CaptureReceipt
from recoryn.storage import Library
from tests.integration.test_track_health import tracked_seed
from tests.unit.test_track_health import fact

pytestmark = pytest.mark.integration
ALL_U = list(product(range(5), (1, 2), ("live", "recovery", "export")))
U = [r for r in ALL_U if r[2] == "export"]


@pytest.mark.parametrize("row", U, ids=[f"G08-U-{ALL_U.index(r) + 1:02}" for r in U])
def test_export_health_snapshot(row, tmp_path):
    state, tracks, _ = row
    with Library(tmp_path / "library") as library:
        value, version = tracked_seed(library, tracks, prefix=6 if state == 1 else 0)
        if state == 3:
            value["checkpoint_seq"] = 1
            value["events"] = [
                fact(
                    reason="DEVICE_LOST",
                    source="DEVICE",
                    start=None,
                    end=None,
                    range_quality="UNKNOWN",
                    lost_frames=None,
                    count_quality="UNKNOWN",
                ).to_dict()
            ]
            value["tracks"]["mic"].update(state="UNAVAILABLE", reason="DEVICE_LOST")
            version = library.checkpoint_capture_health("s", value, expected_health_version=version)
        if state in {1, 2, 4}:
            library.recover_session("s")
        else:
            value["checkpoint_seq"] += 1
            library.finish_capture_health(
                "s",
                value,
                expected_health_version=version,
                receipt=CaptureReceipt("run", True, True, True, False),
            )
        current = library.get_session("s")
        library.transition("s", SessionState.FINALIZING, current.state_version)
        library.finalize_session("s")
        output = tmp_path / "out"
        assert _export(library, "s", output)["complete"]
        index = json.loads((output / "export.json").read_text(encoding="utf-8"))
        metadata = index["capture_health_details"]
        payload = (output / metadata["file"]).read_bytes()
        lines = [json.loads(line) for line in payload.splitlines()]
        assert hashlib.sha256(payload).hexdigest() == metadata["sha256"]
        assert len(lines) == metadata["rows"]
        assert metadata["health_version"] == index["capture_health"]["health_version"]
        actual_events = {r["value"]["event_id"] for r in lines if r["kind"] == "event"}
        expected_events = {
            r[0] for r in library._db.execute("SELECT event_id FROM capture_health_events")
        }
        assert actual_events == expected_events
        tails = [
            r for r in lines if r["kind"] == "event" and r["value"]["reason"] == "UNKNOWN_TAIL"
        ]
        assert len(tails) == (tracks if state in {1, 2, 4} else 0)
        assert all(r["value"]["lost_frames"] is None for r in tails)


def test_export_failure_has_no_completion_marker(tmp_path, monkeypatch):
    with Library(tmp_path / "library") as library:
        library.create_session("s")
        library.transition("s", SessionState.FINALIZING, 0)
        library.finalize_session("s")
        monkeypatch.setattr(
            library, "capture_health", lambda _: {"health_schema_version": 2, "health_version": 1}
        )

        def fail(*args, **kwargs):
            raise OSError("injected health read failure")

        monkeypatch.setattr(library, "capture_health_details", fail)
        with pytest.raises(OSError):
            _export(library, "s", tmp_path / "out")
        assert not (tmp_path / "out" / "export.json").exists()
