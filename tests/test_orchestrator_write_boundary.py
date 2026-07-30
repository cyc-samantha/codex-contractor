from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

from scripts.lib.orchestrator_write_boundary import (  # noqa: E402
    OrchestratorWriteBoundary,
    OrchestratorWriteBoundaryError,
)
from scripts.lib.spawn_telemetry import (  # noqa: E402
    SpawnEnvelope,
    SpawnTelemetryStore,
    TokenMetric,
)


def canary(task_id: str = "task-01", run_id: str = "run-01") -> SpawnEnvelope:
    return SpawnEnvelope(
        1, "canary-01", task_id, run_id, "dispatch-01", "orchestrator",
        "orchestrator-01", "session-orchestrator-01", None, "gpt-5.6-sol",
        "gpt-5.6-sol", "medium", "medium", TokenMetric(1, None),
        TokenMetric(0, None), TokenMetric(1, None), 1, "canary",
    )


@pytest.mark.parametrize(
    ("kind", "name"),
    [
        ("coordination", None),
        ("dispatch", "dispatch-01"),
        ("pr", None),
        ("observation", None),
    ],
)
def test_allows_each_enumerated_coordination_artifact(
    tmp_path: Path, kind: str, name: str | None,
) -> None:
    boundary = OrchestratorWriteBoundary(tmp_path)

    path = boundary.write_artifact(kind, "task-01", {"ok": True}, name)

    assert path.is_file()


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
    store = SpawnTelemetryStore(tmp_path / "spawn-events.jsonl")
    boundary = OrchestratorWriteBoundary(tmp_path)

    with pytest.raises(OrchestratorWriteBoundaryError, match="canary"):
        boundary.activate("task-01", "run-01", "canary-01", store)

    store.record(canary())
    capability = boundary.activate("task-01", "run-01", "canary-01", store)
    boundary.require_active(capability, "task-01", "run-01")


def test_activation_rejects_wrong_task_run_or_event(tmp_path: Path) -> None:
    store = SpawnTelemetryStore(tmp_path / "spawn-events.jsonl")
    store.record(canary())
    boundary = OrchestratorWriteBoundary(tmp_path)

    for binding in (
        ("other-task", "run-01", "canary-01"),
        ("task-01", "other-run", "canary-01"),
        ("task-01", "run-01", "other-event"),
    ):
        with pytest.raises(OrchestratorWriteBoundaryError, match="canary"):
            boundary.activate(*binding, store)


def test_forged_or_mismatched_capability_is_rejected(tmp_path: Path) -> None:
    store = SpawnTelemetryStore(tmp_path / "spawn-events.jsonl")
    store.record(canary())
    first = OrchestratorWriteBoundary(tmp_path)
    capability = first.activate("task-01", "run-01", "canary-01", store)

    with pytest.raises(OrchestratorWriteBoundaryError, match="capability"):
        OrchestratorWriteBoundary(tmp_path).require_active(
            capability, "task-01", "run-01"
        )
    with pytest.raises(OrchestratorWriteBoundaryError, match="binding"):
        first.require_active(capability, "task-01", "other-run")
