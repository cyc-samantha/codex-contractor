from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

from scripts.lib.dispatch_contract import parse_dispatch_contract  # noqa: E402
from scripts.lib.software_engineer_dispatch import (  # noqa: E402
    DispatchExecution,
    SoftwareEngineerDispatchError,
    dispatch_software_engineer,
)
from scripts.lib.spawn_telemetry import SpawnTelemetryStore, TokenMetric  # noqa: E402


def contract():
    return parse_dispatch_contract(
        {
            "schema_version": 1,
            "dispatch_id": "dispatch-01",
            "task_id": "t13b-t13d-dispatch",
            "repository": "/srv/codex-harness",
            "branch": "build/t13b-t13d-dispatch",
            "worktree": "/srv/codex-harness-wt",
            "base_head": "a" * 40,
            "target_head": "b" * 40,
            "allowed_paths": ["scripts/lib/**", "tests/**"],
            "prohibited_paths": [".env", ".git/**"],
            "acceptance_criteria": ["Telemetry-gated dispatch."],
            "required_tests": ["pytest -q"],
            "risk": "Build",
            "role": "software_engineer",
            "role_instance_id": "software_engineer-01",
            "session_id": "session-software_engineer-01",
            "requested_model": "gpt-5.6-terra",
            "requested_reasoning_effort": "high",
            "write_authority": "task_scope",
            "permissions": {
                "filesystem": "workspace-write",
                "network": "disabled",
                "tools": "task_required",
            },
        }
    )


def execution(**overrides: object) -> DispatchExecution:
    values = {
        "payload": {"status": "complete"},
        "actual_model": "gpt-5.6-terra",
        "actual_reasoning_effort": "high",
        "input_tokens": TokenMetric(100, None),
        "cached_input_tokens": TokenMetric(20, None),
        "output_tokens": TokenMetric(30, None),
        "duration_ms": 900,
    }
    values.update(overrides)
    return DispatchExecution(**values)


def test_accepts_result_only_after_correlated_telemetry_is_durable(
    tmp_path: Path,
) -> None:
    store = SpawnTelemetryStore(tmp_path / "spawn-events.jsonl")

    result = dispatch_software_engineer(
        contract(),
        "run-01",
        "telemetry-01",
        "initial",
        "general",
        store,
        lambda _contract, _profile: execution(),
        {("gpt-5.6-terra", "high")},
        {},
        protected_write_boundary_active=True,
    )

    assert result.payload == {"status": "complete"}
    assert store.read_events()[0].dispatch_id == "dispatch-01"
    assert store.read_events()[0].event_id == "telemetry-01"


def test_rejects_missing_or_mismatched_telemetry(tmp_path: Path) -> None:
    store = SpawnTelemetryStore(tmp_path / "spawn-events.jsonl")

    with pytest.raises(SoftwareEngineerDispatchError, match="telemetry"):
        dispatch_software_engineer(
            contract(),
            "run-01",
            "telemetry-01",
            "initial",
            "general",
            store,
            lambda _contract, _profile: execution(actual_model="gpt-5.6-sol"),
            {("gpt-5.6-terra", "high")},
            {},
            protected_write_boundary_active=True,
        )

    assert store.read_events() == ()


def test_rejects_unavailable_execution_profile(tmp_path: Path) -> None:
    invoked = False

    def runtime(_contract, _profile):
        nonlocal invoked
        invoked = True
        return execution()

    with pytest.raises(SoftwareEngineerDispatchError, match="profile"):
        dispatch_software_engineer(
            contract(),
            "run-01",
            "telemetry-01",
            "initial",
            "general",
            SpawnTelemetryStore(tmp_path / "spawn-events.jsonl"),
            runtime,
            set(),
            {},
            protected_write_boundary_active=True,
        )

    assert invoked is False


def test_activation_remains_disabled_until_t13a(tmp_path: Path) -> None:
    with pytest.raises(SoftwareEngineerDispatchError, match="T13A"):
        dispatch_software_engineer(
            contract(),
            "run-01",
            "telemetry-01",
            "initial",
            "general",
            SpawnTelemetryStore(tmp_path / "spawn-events.jsonl"),
            lambda _contract, _profile: execution(),
            {("gpt-5.6-terra", "high")},
            {},
            protected_write_boundary_active=False,
        )
