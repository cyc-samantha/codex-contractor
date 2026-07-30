from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

from scripts.lib.dispatch_contract import parse_dispatch_contract  # noqa: E402
from scripts.lib.orchestrator_write_boundary import OrchestratorWriteBoundary  # noqa: E402
from scripts.lib.software_engineer_dispatch import (  # noqa: E402
    DispatchBinding,
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


def execution(binding: DispatchBinding, **overrides: object) -> DispatchExecution:
    values = {
        "binding": binding,
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


def activation(tmp_path: Path):
    envelope = dispatch_module_canary()
    boundary = OrchestratorWriteBoundary(tmp_path / "state")
    boundary.telemetry_store().record(envelope)
    return boundary.activate(envelope)


def dispatch_module_canary():
    from scripts.lib.spawn_telemetry import SpawnEnvelope

    return SpawnEnvelope(
        1, "canary-01", contract().task_id, "run-01",
        "t13a-activation-canary", "orchestrator", "orchestrator-canary",
        "session-t13a-canary", None,
        "gpt-5.6-sol", "gpt-5.6-sol", "medium", "medium",
        TokenMetric(1, None), TokenMetric(0, None), TokenMetric(1, None), 1,
        "canary",
    )


def test_accepts_result_only_after_correlated_telemetry_is_durable(
    tmp_path: Path,
) -> None:
    store = SpawnTelemetryStore(tmp_path / "spawn-events.jsonl")
    capability = activation(tmp_path)

    result = dispatch_software_engineer(
        contract(),
        "run-01",
        "telemetry-01",
        "initial",
        "general",
        store,
        lambda _contract, _profile, binding: execution(binding),
        {("gpt-5.6-terra", "high")},
        {},
        capability,
    )

    assert result.payload == {"status": "complete"}
    assert store.read_events()[0].dispatch_id == "dispatch-01"
    assert store.read_events()[0].event_id == "telemetry-01"


def test_rejects_missing_or_mismatched_telemetry(tmp_path: Path) -> None:
    store = SpawnTelemetryStore(tmp_path / "spawn-events.jsonl")
    capability = activation(tmp_path)

    with pytest.raises(SoftwareEngineerDispatchError, match="telemetry"):
        dispatch_software_engineer(
            contract(),
            "run-01",
            "telemetry-01",
            "initial",
            "general",
            store,
            lambda _contract, _profile, binding: execution(
                binding, actual_model="gpt-5.6-sol"
            ),
            {("gpt-5.6-terra", "high")},
            {},
            capability,
        )

    assert store.read_events() == ()


def test_rejects_unavailable_execution_profile(tmp_path: Path) -> None:
    invoked = False
    capability = activation(tmp_path)

    def runtime(_contract, _profile, _binding):
        nonlocal invoked
        invoked = True
        raise AssertionError("runtime must not be invoked")

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
            capability,
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
            lambda _contract, _profile, binding: execution(binding),
            {("gpt-5.6-terra", "high")},
            {},
            None,
        )


def test_caller_boolean_cannot_activate_dispatch(tmp_path: Path) -> None:
    invoked = False

    def runtime(_contract, _profile, binding):
        nonlocal invoked
        invoked = True
        return execution(binding)

    with pytest.raises(SoftwareEngineerDispatchError, match="capability"):
        dispatch_software_engineer(
            contract(), "run-01", "telemetry-01", "initial", "general",
            SpawnTelemetryStore(tmp_path / "spawn-events.jsonl"), runtime,
            {("gpt-5.6-terra", "high")}, {}, True,
        )

    assert invoked is False


def test_rejects_runtime_result_with_substituted_binding(tmp_path: Path) -> None:
    capability = activation(tmp_path)

    def runtime(_contract, _profile, binding):
        substituted = DispatchBinding(
            task_id=binding.task_id,
            run_id="stale-run",
            event_id=binding.event_id,
            dispatch_id=binding.dispatch_id,
            role=binding.role,
            role_instance_id=binding.role_instance_id,
            session_id=binding.session_id,
        )
        return execution(substituted)

    with pytest.raises(SoftwareEngineerDispatchError, match="binding mismatch"):
        dispatch_software_engineer(
            contract(),
            "run-01",
            "telemetry-01",
            "initial",
            "general",
            SpawnTelemetryStore(tmp_path / "spawn-events.jsonl"),
            runtime,
            {("gpt-5.6-terra", "high")},
            {},
            capability,
        )
