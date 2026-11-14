"""Pinned local model bytes and licenses, before any optional native loader."""

from __future__ import annotations

import hashlib
from pathlib import Path
from urllib.parse import urlsplit

from recoryn.domain import ValidationError
from recoryn.providers import ProviderError
from recoryn.storage._safe import open_file, root_path, safe_path, strict_json

from .contracts import DiarizationConfig, sha256


def read_local(path: Path, maximum: int) -> bytes:
    try:
        root_path(path)
        with open_file(path, "rb") as stream:
            data = stream.read(maximum + 1)
        if len(data) > maximum:
            raise ProviderError("DIARIZATION_INPUT_TOO_LARGE")
        return data
    except (OSError, ValueError) as error:
        if isinstance(error, ProviderError):
            raise
        raise ProviderError("DIARIZATION_INPUT_UNAVAILABLE") from None


def verified_models(config: DiarizationConfig) -> dict[str, bytes]:
    if not config.license_accepted:
        raise ProviderError("DIARIZATION_LICENSE_REQUIRED")
    raw = read_local(config.manifest_path, 64 * 1024)
    if hashlib.sha256(raw).hexdigest() != config.manifest_sha256:
        raise ProviderError("DIARIZATION_MANIFEST_CHECKSUM")
    try:
        value = strict_json(raw)
        if (
            set(value) != {"schema_version", "runtime", "runtime_version", "models"}
            or type(value["schema_version"]) is not int
            or value["schema_version"] != 1
            or value["runtime"] != "sherpa-onnx"
            or value["runtime_version"] != "2.0.1"
            or not isinstance(value["models"], dict)
            or set(value["models"]) != {"segmentation", "embedding"}
        ):
            raise ProviderError("DIARIZATION_MANIFEST_INVALID")
        output: dict[str, bytes] = {}
        for role, item in value["models"].items():
            if not isinstance(item, dict) or set(item) != {
                "file",
                "size",
                "sha256",
                "license_id",
                "license_url",
                "license_file",
                "license_sha256",
            }:
                raise ProviderError("DIARIZATION_MANIFEST_INVALID")
            if item["file"] != role + ".onnx" or item["license_file"] != f"LICENSE.{role}.txt":
                raise ProviderError("DIARIZATION_MANIFEST_INVALID")
            if type(item["size"]) is not int or not 1 <= item["size"] <= 128 * 1024 * 1024:
                raise ProviderError("DIARIZATION_MANIFEST_INVALID")
            license_id, url = item["license_id"], item["license_url"]
            if not isinstance(license_id, str) or not license_id.strip() or len(license_id) > 256:
                raise ProviderError("DIARIZATION_MANIFEST_INVALID")
            if not isinstance(url, str) or len(url) > 4096:
                raise ProviderError("DIARIZATION_MANIFEST_INVALID")
            parsed = urlsplit(url)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
                or any(ord(c) <= 32 for c in url)
            ):
                raise ProviderError("DIARIZATION_MANIFEST_INVALID")
            data = read_local(safe_path(config.manifest_path.parent, item["file"]), item["size"])
            license_bytes = read_local(
                safe_path(config.manifest_path.parent, item["license_file"]), 64 * 1024
            )
            if len(data) != item["size"] or hashlib.sha256(data).hexdigest() != sha256(
                item["sha256"]
            ):
                raise ProviderError("DIARIZATION_MODEL_CHECKSUM")
            if (
                hashlib.sha256(license_bytes).hexdigest() != sha256(item["license_sha256"])
                or not license_bytes.decode("utf-8").strip()
            ):
                raise ProviderError("DIARIZATION_LICENSE_INVALID")
            output[role] = data
        return output
    except (ValidationError, KeyError, TypeError, UnicodeError, ValueError) as error:
        if isinstance(error, ProviderError):
            raise
        raise ProviderError("DIARIZATION_MANIFEST_INVALID") from None
