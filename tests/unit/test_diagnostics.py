"""Canaries are synthetic. No existing support folder or user credentials are read."""

import json
import os
import time
import zipfile
from pathlib import Path

import pytest

from recoryn.diagnostics import DiagnosticLog, register_secret, sanitize_event, support_bundle
from recoryn.security import SecurityError

pytestmark = pytest.mark.unit
CANARY = "B14-DIAGNOSTIC-CANARY"


def test_allowlist_and_registered_secret_scrub_all_persistent_output(tmp_path: Path) -> None:
    register_secret(CANARY)
    event = {
        "code": CANARY,
        "event": "WRITE_FAILED",
        "duration_ms": 3,
        "api_key": CANARY,
        "audio": CANARY,
        "transcript": CANARY,
        "headers": {"authorization": CANARY},
        "path": CANARY,
        "message": CANARY,
    }
    assert sanitize_event(event) == {"code": "REDACTED", "event": "WRITE_FAILED", "duration_ms": 3}
    log = DiagnosticLog(tmp_path / "diagnostics.jsonl")
    assert list(tmp_path.iterdir()) == []
    log.write(event)
    archive = support_bundle(tmp_path / "support.zip", [event], metadata=event)
    assert CANARY.encode() not in (tmp_path / "diagnostics.jsonl").read_bytes()
    with zipfile.ZipFile(archive) as bundle:
        assert set(bundle.namelist()) == {"diagnostics.jsonl", "environment.json"}
        for name in bundle.namelist():
            value = bundle.read(name)
            assert CANARY.encode() not in value
            assert b"transcript" not in value and b"api_key" not in value


def test_logs_rotate_at_a_bounded_size_and_bundle_never_overwrites(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    log = DiagnosticLog(path, max_bytes=256)
    for _ in range(30):
        log.write({"event": "BOUNDARY", "frame_count": 123})
    assert path.stat().st_size <= 256
    assert path.with_name(path.name + ".1").stat().st_size <= 256
    destination = tmp_path / "support.zip"
    support_bundle(destination, [{"code": "OK"}])
    before = destination.read_bytes()
    with pytest.raises(SecurityError, match="ALREADY_EXISTS"):
        support_bundle(destination, [{"code": "REPLACEMENT"}])
    assert destination.read_bytes() == before
    for line in path.read_text(encoding="utf-8").splitlines():
        assert json.loads(line)["event"] == "BOUNDARY"


def test_metadata_types_limits_and_expired_logs(tmp_path: Path) -> None:
    event = {
        "event": object(),
        "code": "line\nbreak",
        "frame_count": True,
        "duration_ms": -1,
        "byte_count": float("inf"),
        "state": 42,
        "app_version": "1.0",
    }
    assert sanitize_event(event, secrets=("",)) == {"app_version": "1.0"}
    for size, days in ((1, 7), (256, 0), (True, 1)):
        with pytest.raises(SecurityError):
            DiagnosticLog(tmp_path / "bad", max_bytes=size, retention_days=days)
    path = tmp_path / "expired.jsonl"
    path.write_bytes(b"OLD_RECORD")
    path.with_name(path.name + ".1").write_bytes(b"OLD_BACKUP")
    old = time.time() - 10 * 86400
    os.utime(path, (old, old))
    os.utime(path.with_name(path.name + ".1"), (old, old))
    DiagnosticLog(path).write({"event": "NEW"})
    assert b"OLD" not in path.read_bytes()
    assert not path.with_name(path.name + ".1").exists()
    with pytest.raises(SecurityError, match="DIAGNOSTIC_TOO_LARGE"):
        support_bundle(tmp_path / "large.zip", [{}] * 1001)
    with pytest.raises(SecurityError, match="DIAGNOSTIC_TOO_LARGE"):
        support_bundle(tmp_path / "large.zip", [{"event": "LONG"}], max_bytes=1)
