from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

from scripts.lib.spawn_telemetry import (  # noqa: E402
    SpawnTelemetryError,
    SpawnTelemetryStore,
    aggregate_spawn_usage,
    parse_spawn_envelope,
)


def envelope(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": 1,
        "event_id": "telemetry-01",
        "task_id": "t13b-t13d-dispatch",
        "run_id": "run-01",
        "dispatch_id": "dispatch-01",
        "role": "software_engineer",
        "role_instance_id": "software_engineer-01",
        "session_id": "session-software_engineer-01",
        "pr_id": None,
        "requested_model": "gpt-5.6-terra",
        "actual_model": "gpt-5.6-terra",
        "requested_reasoning_effort": "high",
        "actual_reasoning_effort": "high",
        "input_tokens": {"value": 100, "unavailable_reason": None},
        "cached_input_tokens": {"value": 20, "unavailable_reason": None},
        "output_tokens": {"value": 30, "unavailable_reason": None},
        "duration_ms": 1250,
        "retry_cycle_id": "initial",
    }
    value.update(overrides)
    return value


def test_records_versioned_minimal_envelope_with_actual_usage(tmp_path: Path) -> None:
    store = SpawnTelemetryStore(tmp_path / "spawn-events.jsonl")
    event = parse_spawn_envelope(envelope())

    store.record(event)

    assert store.read_events() == (event,)


def test_store_revalidates_programmatically_constructed_envelope(
    tmp_path: Path,
) -> None:
    store = SpawnTelemetryStore(tmp_path / "spawn-events.jsonl")
    invalid = parse_spawn_envelope(envelope())
    object.__setattr__(invalid.input_tokens, "value", -1)

    with pytest.raises(SpawnTelemetryError, match="input_tokens"):
        store.record(invalid)

    assert store.read_events() == ()


def test_store_rejects_symlinked_telemetry_file(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_text("unchanged")
    events = tmp_path / "spawn-events.jsonl"
    events.symlink_to(target)
    store = SpawnTelemetryStore(events)

    with pytest.raises(SpawnTelemetryError, match="cannot read telemetry file"):
        store.record(parse_spawn_envelope(envelope()))

    assert target.read_text() == "unchanged"


def test_store_rejects_relative_or_parent_traversal_paths(tmp_path: Path) -> None:
    with pytest.raises(SpawnTelemetryError, match="absolute and normalized"):
        SpawnTelemetryStore(Path("spawn-events.jsonl"))

    with pytest.raises(SpawnTelemetryError, match="absolute and normalized"):
        SpawnTelemetryStore(tmp_path / ".." / "spawn-events.jsonl")


@pytest.mark.parametrize(
    "metric",
    [
        {},
        {"value": None, "unavailable_reason": None},
        {"value": None, "unavailable_reason": ""},
        {"value": -1, "unavailable_reason": None},
        {"value": 1, "unavailable_reason": "provider omitted metric"},
    ],
)
def test_requires_null_with_reason_for_unavailable_provider_metrics(
    metric: object,
) -> None:
    value = envelope(input_tokens=metric)

    with pytest.raises(SpawnTelemetryError, match="input_tokens"):
        parse_spawn_envelope(value)


def test_aggregates_known_totals_and_preserves_unknown_fields() -> None:
    first = parse_spawn_envelope(envelope())
    second = parse_spawn_envelope(
        envelope(
            event_id="telemetry-02",
            input_tokens={
                "value": None,
                "unavailable_reason": "provider did not report input tokens",
            },
            output_tokens={"value": 5, "unavailable_reason": None},
        )
    )

    aggregate = aggregate_spawn_usage((first, second))

    assert aggregate.known_token_total == 175
    assert aggregate.unknown_token_fields == ("telemetry-02.input_tokens",)


def test_reconciles_late_pr_identity_idempotently(tmp_path: Path) -> None:
    store = SpawnTelemetryStore(tmp_path / "spawn-events.jsonl")
    store.record(parse_spawn_envelope(envelope()))

    first = store.reconcile_pr("t13b-t13d-dispatch", "run-01", "32")
    second = store.reconcile_pr("t13b-t13d-dispatch", "run-01", "32")

    assert first == second
    assert first.pr_id == "32"
    assert first.known_token_total == 150
    assert len(store.read_reconciliations()) == 1
