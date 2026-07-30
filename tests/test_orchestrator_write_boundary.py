from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

from scripts.lib.orchestrator_write_boundary import (  # noqa: E402
    ActivationCapability,
    OrchestratorWriteBoundary,
    OrchestratorWriteBoundaryError,
    require_activation,
)
from scripts.lib.spawn_telemetry import (  # noqa: E402
    SpawnEnvelope,
    SpawnTelemetryStore,
    TokenMetric,
)


def canary(task_id: str = "task-01", run_id: str = "run-01") -> SpawnEnvelope:
    return SpawnEnvelope(
        1, "canary-01", task_id, run_id, "t13a-activation-canary", "orchestrator",
        "orchestrator-canary", "session-t13a-canary", None, "gpt-5.6-sol",
        "gpt-5.6-sol", "medium", "medium", TokenMetric(1, None),
        TokenMetric(0, None), TokenMetric(1, None), 1, "canary",
    )


@pytest.mark.parametrize(
    ("kind", "name", "relative"),
    [
        ("coordination", None, "pipeline-state/task-01/coordination.json"),
        ("dispatch", "dispatch-01", "pipeline-state/task-01/dispatch/dispatch-01.json"),
        ("pr", None, "pipeline-state/task-01/pr.json"),
        ("observation", None, "learning/observations/task-01.jsonl"),
    ],
)
def test_allows_each_enumerated_coordination_artifact(
    tmp_path: Path, kind: str, name: str | None, relative: str,
) -> None:
    boundary = OrchestratorWriteBoundary(tmp_path)

    path = boundary.write_artifact(kind, "task-01", {"ok": True}, name)

    assert path == tmp_path / relative
    assert path.read_text() == '{"ok": true}\n'


@pytest.mark.parametrize("kind", ["source", "test", "migration", "repo_config"])
def test_blocks_source_test_migration_and_repo_config_paths(
    tmp_path: Path, kind: str,
) -> None:
    with pytest.raises(OrchestratorWriteBoundaryError, match="artifact"):
        OrchestratorWriteBoundary(tmp_path).write_artifact(
            kind, "task-01", {"bad": True}, "file"
        )


@pytest.mark.parametrize("name", ["../source", "/absolute", "*.json", "a/**"])
def test_rejects_absolute_traversal_and_glob_names(tmp_path: Path, name: str) -> None:
    with pytest.raises(OrchestratorWriteBoundaryError, match="identifier"):
        OrchestratorWriteBoundary(tmp_path).write_artifact(
            "dispatch", "task-01", {"bad": True}, name
        )


def test_rejects_symlinked_parent(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "pipeline-state").symlink_to(outside, target_is_directory=True)

    with pytest.raises((OrchestratorWriteBoundaryError, OSError)):
        OrchestratorWriteBoundary(tmp_path).write_artifact(
            "coordination", "task-01", {"bad": True}
        )


def test_rejects_hard_link_target(tmp_path: Path) -> None:
    boundary = OrchestratorWriteBoundary(tmp_path)
    target = boundary.write_artifact("coordination", "task-01", {"ok": True})
    target.with_name("linked.json").hardlink_to(target)

    with pytest.raises(OrchestratorWriteBoundaryError, match="single-link"):
        boundary.write_artifact("coordination", "task-01", {"bad": True})


def test_activation_requires_durable_correlated_canary(tmp_path: Path) -> None:
    boundary = OrchestratorWriteBoundary(tmp_path)

    with pytest.raises(OrchestratorWriteBoundaryError, match="canary"):
        boundary.activate(canary())

    boundary.telemetry_store().record(canary())
    capability = boundary.activate(canary())
    require_activation(capability, "task-01", "run-01")
    record = tmp_path / "pipeline-state" / "task-01" / "activation.json"
    assert record.read_text() == (
        '{"allowlist_digest": '
        '"21c07d1a7607ff10840b8e1186a8235c3d7efeba063cccf4554b97bd69b2ea93", '
        '"event_id": "canary-01", "run_id": "run-01", '
        '"schema_version": 1, "task_id": "task-01"}\n'
    )


def test_telemetry_store_uses_canonical_harness_location(tmp_path: Path) -> None:
    store = OrchestratorWriteBoundary(tmp_path).telemetry_store()

    assert store.events_path == tmp_path / "telemetry" / "spawn-events.jsonl"


def test_activation_rejects_wrong_task_run_or_event(tmp_path: Path) -> None:
    boundary = OrchestratorWriteBoundary(tmp_path)
    boundary.telemetry_store().record(canary())

    for envelope in (
        canary(task_id="other-task"),
        canary(run_id="other-run"),
        SpawnEnvelope(**{**canary().__dict__, "event_id": "other-event"}),
    ):
        with pytest.raises(OrchestratorWriteBoundaryError, match="canary"):
            boundary.activate(envelope)


def test_activation_rejects_noncanonical_canary_profile(tmp_path: Path) -> None:
    boundary = OrchestratorWriteBoundary(tmp_path)
    value = canary()
    forged = SpawnEnvelope(
        **{**value.__dict__, "actual_reasoning_effort": "low"}
    )
    boundary.telemetry_store().record(forged)

    with pytest.raises(OrchestratorWriteBoundaryError, match="canary"):
        boundary.activate(forged)


def test_forged_or_mismatched_capability_is_rejected(tmp_path: Path) -> None:
    boundary = OrchestratorWriteBoundary(tmp_path)
    boundary.telemetry_store().record(canary())
    capability = boundary.activate(canary())

    with pytest.raises(TypeError, match="boundary-issued"):
        ActivationCapability()
    with pytest.raises(OrchestratorWriteBoundaryError, match="binding"):
        require_activation(capability, "task-01", "other-run")


def test_observations_are_append_only_jsonl(tmp_path: Path) -> None:
    boundary = OrchestratorWriteBoundary(tmp_path)
    path = boundary.write_artifact("observation", "task-01", {"sequence": 1})
    boundary.write_artifact("observation", "task-01", {"sequence": 2})

    assert path.suffix == ".jsonl"
    assert path.read_text().count("\n") == 2
