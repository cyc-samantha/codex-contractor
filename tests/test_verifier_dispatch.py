from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

from scripts.lib.dispatch_contract import parse_dispatch_contract  # noqa: E402
from scripts.lib.spawn_telemetry import (  # noqa: E402
    SpawnEnvelope,
    SpawnTelemetryStore,
    TokenMetric,
)
from scripts.lib.verifier_dispatch import (  # noqa: E402
    VerifierDispatchBinding,
    VerifierDispatchError,
    VerifierExecution,
    dispatch_verifier,
)


def contract(**overrides: object):
    value: dict[str, object] = {
        "schema_version": 1,
        "dispatch_id": "verifier-dispatch-01",
        "task_id": "t18-verification",
        "repository": "/srv/codex-harness",
        "branch": "build/t18-verification",
        "worktree": "/srv/codex-harness-wt",
        "base_head": "a" * 40,
        "target_head": "b" * 40,
        "allowed_paths": ["scripts/**", "tests/**"],
        "prohibited_paths": [".env", ".git/**"],
        "acceptance_criteria": ["Write fresh verification evidence."],
        "required_tests": ["pytest -q"],
        "risk": "Build",
        "role": "verifier",
        "role_instance_id": "verifier-01",
        "session_id": "session-verifier-01",
        "requested_model": "gpt-5.6-terra",
        "requested_reasoning_effort": "low",
        "write_authority": "none",
        "permissions": {
            "filesystem": "read-only",
            "network": "disabled",
            "tools": "none",
        },
    }
    value.update(overrides)
    return parse_dispatch_contract(value)


def execution(binding: VerifierDispatchBinding, **overrides: object) -> VerifierExecution:
    values = {
        "binding": binding,
        "payload": {"verdict": "VERIFIED"},
        "actual_model": "gpt-5.6-terra",
        "actual_reasoning_effort": "low",
        "input_tokens": TokenMetric(10, None),
        "cached_input_tokens": TokenMetric(0, None),
        "output_tokens": TokenMetric(20, None),
        "duration_ms": 100,
    }
    values.update(overrides)
    return VerifierExecution(**values)


def test_verifier_dispatch_requires_read_only_contract(tmp_path: Path) -> None:
    invalid = contract()
    object.__setattr__(invalid.permissions, "filesystem", "workspace-write")

    with pytest.raises(VerifierDispatchError, match="contract"):
        dispatch_verifier(
            invalid,
            "run-01",
            "verifier-event-01",
            "initial",
            "mechanical",
            SpawnTelemetryStore(tmp_path / "events.jsonl"),
            lambda _contract, _profile, binding: execution(binding),
            {("gpt-5.6-terra", "low")},
            {},
            "b" * 40,
            "b" * 40,
            True,
        )


def test_verifier_dispatch_binds_reviewed_head_and_identity(tmp_path: Path) -> None:
    store = SpawnTelemetryStore(tmp_path / "events.jsonl")

    with pytest.raises(VerifierDispatchError, match="review HEAD"):
        dispatch_verifier(
            contract(),
            "run-01",
            "verifier-event-01",
            "initial",
            "mechanical",
            store,
            lambda _contract, _profile, binding: execution(binding),
            {("gpt-5.6-terra", "low")},
            {},
            "a" * 40,
            "b" * 40,
            True,
        )

    with pytest.raises(VerifierDispatchError, match="binding"):
        dispatch_verifier(
            contract(),
            "run-01",
            "verifier-event-01",
            "initial",
            "mechanical",
            store,
            lambda _contract, _profile, binding: execution(
                VerifierDispatchBinding(
                    binding.task_id,
                    "stale-run",
                    binding.event_id,
                    binding.dispatch_id,
                    binding.role,
                    binding.role_instance_id,
                    binding.session_id,
                    binding.target_head,
                )
            ),
            {("gpt-5.6-terra", "low")},
            {},
            "b" * 40,
            "b" * 40,
            True,
        )


def test_verifier_dispatch_requires_durable_matching_telemetry(tmp_path: Path) -> None:
    store = SpawnTelemetryStore(tmp_path / "events.jsonl")
    store.record(
        SpawnEnvelope(
            1, "verifier-event-01", "t18-verification", "run-01",
            "other-dispatch", "verifier", "verifier-01",
            "session-verifier-01", None, "gpt-5.6-terra", "gpt-5.6-terra",
            "low", "low", TokenMetric(1, None), TokenMetric(0, None),
            TokenMetric(1, None), 1, "initial",
        )
    )

    with pytest.raises(VerifierDispatchError, match="telemetry"):
        dispatch_verifier(
            contract(), "run-01", "verifier-event-01", "initial", "mechanical",
            store, lambda _contract, _profile, binding: execution(binding),
            {("gpt-5.6-terra", "low")}, {}, "b" * 40, "b" * 40, True,
        )


def test_verifier_accepts_null_with_reason_provider_metrics(tmp_path: Path) -> None:
    store = SpawnTelemetryStore(tmp_path / "events.jsonl")

    result = dispatch_verifier(
        contract(), "run-01", "verifier-event-01", "initial", "mechanical",
        store,
        lambda _contract, _profile, binding: execution(
            binding,
            input_tokens=TokenMetric(None, "provider did not report input tokens"),
            output_tokens=TokenMetric(None, "provider did not report output tokens"),
        ),
        {("gpt-5.6-terra", "low")}, {}, "b" * 40, "b" * 40, True,
    )

    assert result.payload == {"verdict": "VERIFIED"}
    event = store.read_events()[0]
    assert event.role == "verifier"
    assert event.input_tokens.value is None
    assert event.input_tokens.unavailable_reason


def test_verifier_rejects_malformed_runtime_result(tmp_path: Path) -> None:
    with pytest.raises(VerifierDispatchError, match="runtime result"):
        dispatch_verifier(
            contract(), "run-01", "verifier-event-01", "initial", "mechanical",
            SpawnTelemetryStore(tmp_path / "events.jsonl"),
            lambda _contract, _profile, _binding: object(),
            {("gpt-5.6-terra", "low")}, {}, "b" * 40, "b" * 40, True,
        )
