"""Independent GS05 literal ID/primary audit and output-space properties."""

from __future__ import annotations

import hashlib
import json
import zipfile
from collections import Counter
from collections.abc import Iterator
from dataclasses import asdict
from itertools import product
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.property
_CLOSED_OUTPUT_STORES: tuple[tuple[str, bytes], ...] = ()
_TEMPLATE_OUTPUT_EXECUTION = ""


@pytest.fixture(scope="module", autouse=True)
def closed_output_store(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    from recoryn.security import ConsentStore, CostLedger

    global _CLOSED_OUTPUT_STORES, _TEMPLATE_OUTPUT_EXECUTION
    source = tmp_path_factory.mktemp("gs05-empty-output")
    with ConsentStore(source / "policy.db", clock=lambda: 1000) as policy:
        _TEMPLATE_OUTPUT_EXECUTION = policy.execution_id
        assert policy._db.execute("SELECT COUNT(*) FROM security_grants_v2").fetchone()[0] == 0
    with CostLedger(source / "cost.db", clock=lambda: 1000) as ledger:
        witness = ledger._witness
        assert (
            ledger._db.execute("SELECT COUNT(*) FROM security_cost_requests_v2").fetchone()[0] == 0
        )
    assert not (source / "policy.db-wal").exists() and not (source / "cost.db-wal").exists()
    _CLOSED_OUTPUT_STORES = tuple(
        (path.name, path.read_bytes())
        for path in (source / "policy.db", source / "cost.db", witness)
    )
    try:
        yield
    finally:
        _CLOSED_OUTPUT_STORES = ()
        _TEMPLATE_OUTPUT_EXECUTION = ""


def literal_manifest() -> dict[str, str]:
    manifest: dict[str, str] = {}
    unit = "tests/unit/test_secret_lifetime.py"
    integration = "tests/integration/test_secret_lifetime.py"
    ui = "tests/ui/test_secret_lifetime_ui.py"
    prop = "tests/property/test_secret_lifetime_case_space.py"

    def put(case_id: str, owner: str) -> None:
        assert case_id not in manifest, case_id
        manifest[case_id] = owner

    for row in product(range(5), range(4), range(3), range(2), range(2)):
        put("GS05-A-" + "-".join(map(str, row)), unit)
    for route, value in product(range(5), range(8)):
        put(f"GS05-B-{route}-{value}", integration)
        put(f"GS05-F-{route}-{value}", unit)
    for cause, cut in product(range(6), range(6)):
        put(f"GS05-C2-{cause}-{cut}", integration)
    for route, fault in product(range(5), range(9)):
        put(f"GS05-D-{route}-{fault}", integration)
    for row in range(20):
        put(f"GS05-E-{row:02}", unit)
    for sink, stage in product(range(12), range(6)):
        put(f"GS05-G-{sink}-{stage}", prop)
    for action, generation in product(range(8), range(2)):
        put(f"GS05-U-{action}-{generation}", ui)
    for row in range(11):
        put(f"GS05-X-{row:02}", unit)
    for route, outcome in product(range(5), range(9)):
        put(f"GS05-P-{route}-{outcome}", integration)
    for route, boundary, code in product(range(5), range(2), range(2)):
        put(f"GS05-Q-{route}-{boundary}-{code}", integration)
    for route, wait in product(range(5), range(2)):
        put(f"GS05-L-{route}-{wait}", integration)
    for row in product(range(11), range(2), range(2), range(2)):
        put("GS05-V-" + "-".join(map(str, row)), ui)
    for outcome, view in product(range(4), range(4)):
        put(f"GS05-S-{outcome}-{view}", ui)
    for row in range(20):
        owner = unit if row < 12 else ui if row in (13, 14, 15, 17) else integration
        put(f"GS05-T-{row:02}", owner)
    for route, cut, catalog in product(range(5), range(5), range(2)):
        put(f"GS05-K-{route}-{cut}-{catalog}", integration)
    for quote, cache, gate in product(range(2), range(2), range(3)):
        put(f"GS05-J-{quote}-{cache}-{gate}", unit)
    return manifest


EXPECTED_PRIMARY = literal_manifest()


class _ExecutionAudit:
    def __init__(self, selected: dict[str, str]) -> None:
        self.selected = selected
        self.calls: Counter[str] = Counter()
        self.outcomes: dict[str, str] = {}

    def pytest_runtest_logreport(self, report: Any) -> None:
        if report.when == "call" and report.nodeid in self.selected:
            self.calls[report.nodeid] += 1
            self.outcomes[report.nodeid] = report.outcome


@pytest.fixture(scope="session", autouse=True)
def execution_audit(request: pytest.FixtureRequest) -> Any:
    existing = request.config.pluginmanager.get_plugin("gs05-literal-call-audit")
    if existing is not None:
        yield existing
        return
    selected: dict[str, str] = {}
    seen: set[str] = set()
    for item in request.session.items:
        call = getattr(item, "callspec", None)
        case_id = call.params.get("case_id") if call is not None else None
        if not isinstance(case_id, str) or not case_id.startswith("GS05-"):
            continue
        assert case_id in EXPECTED_PRIMARY, case_id
        assert case_id not in seen, case_id
        seen.add(case_id)
        owner = item.path.relative_to(request.config.rootpath).as_posix()
        assert owner == EXPECTED_PRIMARY[case_id], (case_id, owner)
        selected[item.nodeid] = case_id
    audit = _ExecutionAudit(selected)
    if (
        not request.config.option.keyword
        and not request.config.option.markexpr
        and any(item.name == "test_literal_781_primary_manifest" for item in request.session.items)
        and set(EXPECTED_PRIMARY.values()).issubset(
            {
                item.path.relative_to(request.config.rootpath).as_posix()
                for item in request.session.items
            }
        )
    ):
        assert seen == set(EXPECTED_PRIMARY), set(EXPECTED_PRIMARY) - seen
    request.config.pluginmanager.register(audit, "gs05-literal-call-audit")
    try:
        yield audit
    finally:
        request.config.pluginmanager.unregister(audit)
    assert set(audit.calls) == set(selected), set(selected) - set(audit.calls)
    assert all(count == 1 for count in audit.calls.values()), audit.calls


def test_literal_781_primary_manifest() -> None:
    assert len(EXPECTED_PRIMARY) == 781
    owners = Counter(EXPECTED_PRIMARY.values())
    assert owners == {
        "tests/unit/test_secret_lifetime.py": 335,
        "tests/integration/test_secret_lifetime.py": 250,
        "tests/property/test_secret_lifetime_case_space.py": 72,
        "tests/ui/test_secret_lifetime_ui.py": 124,
    }


G_CASES = [
    pytest.param(f"GS05-G-{sink}-{stage}", sink, stage, id=f"GS05-G-{sink}-{stage}")
    for sink, stage in product(range(12), range(6))
]


@pytest.mark.parametrize("case_id,sink,stage", G_CASES)
def test_output_space(
    case_id: str, sink: int, stage: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from recoryn.diagnostics import DiagnosticLog, sanitize_event, support_bundle
    from recoryn.jobs import JobStore
    from recoryn.jobs.failures import normalize_failure
    from recoryn.providers import ExecutionContext, ProviderConfig
    from recoryn.security import ConsentStore, CostLedger, SecurityError
    from recoryn.ui.privacy import PrivacyReply, _execution_key
    from tests.integration.test_secret_lifetime import Wire
    from tests.unit.test_cost_cap import fixture_reservation, fixture_wire
    from tests.unit.test_secret_lifetime import (
        K_A,
        K_B,
        key_command,
        secret_world,
        widget_for_world,
    )

    for name, content in _CLOSED_OUTPUT_STORES:
        target = tmp_path / name
        assert not target.exists(), "each output row owns its DB/witness clone"
        target.write_bytes(content)
    with ConsentStore(tmp_path / "policy.db", clock=lambda: 1000) as policy:
        assert policy.execution_id != _TEMPLATE_OUTPUT_EXECUTION
        with secret_world(policy) as world:
            wire = Wire()
            world.gateway.transport = wire
            error: BaseException = SecurityError("AUTH_REQUIRED")
            callbacks: list[Any] = []
            if stage == 1:
                world.backend.error = OSError("GS05-PRIVATE-OUTPUT-CANARY")
            elif stage == 2:

                def partial_header() -> None:
                    raise OSError("GS05-PRIVATE-OUTPUT-CANARY")

                wire.on_header = partial_header
            if stage in (1, 2, 3):
                try:
                    assert world.send() == b"{}"
                except SecurityError as caught:
                    error = caught
                assert world.backend.reads == 1
                assert wire.opens == (0 if stage == 1 else 1)
            elif stage in (4, 5):
                world.backend.write_error = stage == 4
                done, result = key_command(world, "save")
                assert done.wait(3)
                callbacks = [PrivacyReply("stt", "GS05-completed", 0, "key", result[0])]
                assert result[0].error_code == ("VAULT_WRITE_FAILED" if stage == 4 else None)
                if stage == 5:
                    world.credentials.invalidate_plan("stt")
            else:
                assert (
                    world.credentials.capture_binding(world.auth.ref.target, "stt").ref
                    == world.auth.ref
                )
                assert world.backend.reads == 0
            config = ProviderConfig(
                "openai", "fixture", endpoint=world.route[3], context_window_tokens=100_000
            )
            context = ExecutionContext(headers={"X-Trace-ID": "GS05-safe"})
            code = normalize_failure(error).code
            safe_record = {
                "event": "GS05_output",
                "code": code,
                "state": "BLOCKED",
                "frame_count": 80,
            }
            tainted = dict(
                safe_record,
                api_key=K_A,
                credential_hash=hashlib.sha256(K_A.encode()).hexdigest(),
                native_error="GS05-PRIVATE-OUTPUT-CANARY",
            )
            observed: bytes
            if sink == 0:
                observed = repr((context, world.auth, config, callbacks)).encode()
                assert "headers=" not in repr(context) and "service=" not in repr(world.auth)
            elif sink == 1:
                public = asdict(config)
                assert set(public) == {
                    "provider_id",
                    "model",
                    "endpoint",
                    "execution_location",
                    "timeout_seconds",
                    "max_response_bytes",
                    "context_window_tokens",
                    "max_output_tokens",
                    "max_requests",
                    "local_attestation",
                    "api_version",
                }
                assert public["provider_id"] == "openai" and public["model"] == "fixture"
                observed = json.dumps(public, sort_keys=True).encode()
            elif sink == 2:
                key = _execution_key(config, "stt", "GS05-safe-session")
                literal = [
                    "openai",
                    "fixture",
                    "https://openai.gs05.invalid/v1/audio/transcriptions",
                    "remote",
                    None,
                    100_000,
                    1024,
                    "stt",
                    "GS05-safe-session",
                ]
                assert (
                    key == hashlib.sha256(json.dumps(literal, sort_keys=True).encode()).hexdigest()
                )
                observed = key.encode()
            elif sink == 3:
                with JobStore(tmp_path / "jobs.db") as jobs:
                    job = jobs.create("stt", "GS05-safe-input")
                    attempt = jobs.claim(job.job_id, "GS05-safe-owner")
                    final = jobs.fail(
                        job.job_id,
                        attempt.attempt_id,
                        attempt.fence,
                        "AUTH_REQUIRED",
                        retryable=False,
                        outcome_known=True,
                    )
                    assert str(final.state) == "BLOCKED" and final.blocked_reason == "AUTH"
                    rows = jobs._db.execute("SELECT * FROM events").fetchall()
                    assert rows
                    observed = (
                        repr([tuple(row) for row in rows]).encode()
                        + (tmp_path / "jobs.db").read_bytes()
                        + "\n".join(jobs._db.iterdump()).encode()
                    )
            elif sink == 4:
                policy.revoke_endpoint(world.route[0], world.route[3])
                row = policy._db.execute(
                    "SELECT allowed FROM security_grants_v2 WHERE provider='openai'"
                ).fetchone()
                assert tuple(row) == (0,)
                observed = policy.db_path.read_bytes() + "\n".join(policy._db.iterdump()).encode()
            elif sink == 5:
                with CostLedger(tmp_path / "cost.db", clock=lambda: 1000) as ledger:
                    request = fixture_wire(
                        "openai", world.route[3], "audio", b"synthetic", model="fixture"
                    )
                    reservation = fixture_reservation(
                        ledger, monkeypatch, request, 80, 100, "GS05-cost"
                    )
                    if stage in (2, 3):
                        ledger.mark_unknown(reservation)
                    row = ledger._request(reservation)
                    assert row["state"] == ("UNKNOWN" if stage in (2, 3) else "RESERVED")
                    observed = (
                        ledger.db_path.read_bytes()
                        + ledger._witness.read_bytes()
                        + "\n".join(ledger._db.iterdump()).encode()
                    )
            elif sink == 6:
                from recoryn.content import ContentStore
                from recoryn.storage import Library

                with Library(tmp_path / "library") as library, ContentStore(library) as content:
                    library.create_session("GS05-safe-session")
                    settings = _execution_key(config, "summary", "GS05-safe-session")
                    content.request_summary_settings("GS05-safe-session", settings)
                    state = content.selection_state("GS05-safe-session")
                    assert state == {
                        "session_id": "GS05-safe-session",
                        "transcript_id": None,
                        "transcript_version": 0,
                        "summary_id": None,
                        "summary_version": 0,
                        "summary_settings_key": settings,
                    }
                    library.write_manifest("GS05-safe-session")
                    manifest = library.root / "sessions" / "GS05-safe-session" / "manifest.json"
                    assert manifest.is_file()
                    observed = (
                        json.dumps(state).encode()
                        + manifest.read_bytes()
                        + library.db_path.read_bytes()
                    )
            elif sink == 7:
                path = tmp_path / "diagnostic.jsonl"
                DiagnosticLog(path).write(tainted)
                observed = path.read_bytes()
                assert json.loads(observed) == safe_record
            elif sink == 8:
                safe = normalize_failure(error)
                observed = (str(error) + repr(error) + repr(safe)).encode()
                assert not safe.retryable
                assert "GS05-PRIVATE-OUTPUT-CANARY" not in str(error)
            elif sink == 9:
                from tests.ui.test_secret_lifetime_ui import settle_privacy

                with widget_for_world(world) as panel:
                    settle_privacy(panel)
                    panel._command_nonces["stt"] = "GS05-safe"
                    panel._on_work_ready(
                        PrivacyReply(
                            "stt",
                            "GS05-safe",
                            panel._selection_generation,
                            "key",
                            error_code="VAULT_WRITE_FAILED",
                        )
                    )
                    assert panel.controls["stt"].status.text() == "VAULT_WRITE_FAILED"
                    if stage == 5:
                        panel.select_session("GS05-next-view")
                        panel._on_work_ready(
                            PrivacyReply(
                                "stt", "GS05-safe", 0, "key", error_code="VAULT_DELETE_FAILED"
                            )
                        )
                        assert panel.controls["stt"].status.text() != "VAULT_DELETE_FAILED"
                    observed = panel.controls["stt"].status.text().encode()
            elif sink == 10:
                output = support_bundle(tmp_path / "support.zip", [tainted], metadata=tainted)
                with zipfile.ZipFile(output) as bundle:
                    assert bundle.namelist() == ["diagnostics.jsonl", "environment.json"]
                    records = [bundle.read(name) for name in bundle.namelist()]
                    assert [json.loads(value) for value in records] == [safe_record, safe_record]
                    observed = b"".join(records)
            else:
                crash = sanitize_event(dict(tainted, level="ERROR"))
                assert crash == dict(safe_record, level="ERROR")
                observed = json.dumps(crash, sort_keys=True).encode()
            assert observed, case_id
            for secret in (K_A, K_B):
                assert secret.encode() not in observed, case_id
                assert hashlib.sha256(secret.encode()).hexdigest().encode() not in observed, case_id
            assert b"GS05-PRIVATE-OUTPUT-CANARY" not in observed, case_id
