"""Allowlisted diagnostics; bundles contain generated safe records, never project files."""

from __future__ import annotations

import json
import os
import re
import threading
import time
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path

from recoryn.security._core import SecurityError, check_path, safe_operation
from recoryn.security._secrets import redact, register_secret

_FIELDS = {
    "event",
    "code",
    "level",
    "app_version",
    "session_id",
    "job_id",
    "attempt_id",
    "state",
    "duration_ms",
    "frame_count",
    "dropped_frames",
    "byte_count",
    "timestamp",
}
_STRINGS = {"event", "code", "level", "app_version", "session_id", "job_id", "attempt_id", "state"}


def sanitize_event(
    event: Mapping[str, object], *, secrets: Sequence[str] = ()
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in event.items():
        if key not in _FIELDS:
            continue
        if key in _STRINGS:
            if not isinstance(value, str):
                continue
            value = redact(value, secrets)
            if re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", value):
                result[key] = value
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            if 0 <= value < 2**63:
                result[key] = value
    return result


class DiagnosticLog:
    def __init__(
        self,
        path: Path,
        *,
        max_bytes: int = 1024 * 1024,
        retention_days: int = 7,
        secrets: Sequence[str] = (),
    ) -> None:
        if (
            type(max_bytes) is not int
            or max_bytes < 256
            or type(retention_days) is not int
            or retention_days < 1
        ):
            raise SecurityError("INVALID_LOG_LIMIT")
        self.path, self.max_bytes, self.retention_days = Path(path), max_bytes, retention_days
        self._secrets = tuple(secrets)
        self._lock = threading.Lock()

    @safe_operation
    def write(self, event: Mapping[str, object]) -> None:
        record = (
            json.dumps(
                sanitize_event(event, secrets=self._secrets), sort_keys=True, allow_nan=False
            ).encode("utf-8")
            + b"\n"
        )
        if len(record) > self.max_bytes:
            raise SecurityError("DIAGNOSTIC_TOO_LARGE")
        with self._lock:
            path = check_path(self.path)
            path.parent.mkdir(parents=True, exist_ok=True)
            backup = check_path(path.with_name(path.name + ".1"))
            if (
                backup.exists()
                and time.time() - backup.stat().st_mtime > self.retention_days * 86400
            ):
                backup.unlink()
            if path.exists():
                if time.time() - path.stat().st_mtime > self.retention_days * 86400:
                    path.unlink()
                elif path.stat().st_size + len(record) > self.max_bytes:
                    os.replace(path, backup)
            fd = os.open(
                path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600
            )
            with os.fdopen(fd, "ab") as stream:
                check_path(path)
                stream.write(record)


@safe_operation
def support_bundle(
    output: Path,
    events: Sequence[Mapping[str, object]],
    *,
    metadata: Mapping[str, object] | None = None,
    secrets: Sequence[str] = (),
    max_bytes: int = 1024 * 1024,
) -> Path:
    if len(events) > 1000:
        raise SecurityError("DIAGNOSTIC_TOO_LARGE")
    records = b"".join(
        json.dumps(sanitize_event(event, secrets=secrets), sort_keys=True, allow_nan=False).encode(
            "utf-8"
        )
        + b"\n"
        for event in events
    )
    environment = json.dumps(
        sanitize_event(metadata or {}, secrets=secrets), sort_keys=True, allow_nan=False
    ).encode("utf-8")
    if len(records) + len(environment) > max_bytes:
        raise SecurityError("DIAGNOSTIC_TOO_LARGE")
    output = check_path(output)
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with (
        os.fdopen(fd, "wb") as stream,
        zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as bundle,
    ):
        bundle.writestr("diagnostics.jsonl", records)
        bundle.writestr("environment.json", environment)
    return output


__all__ = ["DiagnosticLog", "register_secret", "sanitize_event", "support_bundle"]
