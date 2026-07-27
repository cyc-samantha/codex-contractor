"""Resolve shared pipeline-state paths without mutating runtime state."""

from __future__ import annotations

import os
import re
from pathlib import Path


class PipelineStatePathError(ValueError):
    """Raised when a task identity cannot be resolved beneath state root."""


def validate_task_id(task_id: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", task_id):
        raise PipelineStatePathError(f"unsafe pipeline task id: {task_id!r}")


def harness_data_root() -> Path:
    configured_root = os.environ.get("HARNESS_DATA")
    return Path(configured_root) if configured_root else Path.home() / ".claude"


def pipeline_state_root(harness_data: Path | None = None) -> Path:
    return (harness_data or harness_data_root()) / "pipeline-state"


def assert_pipeline_path(path: Path, harness_data: Path | None = None) -> None:
    state_root = pipeline_state_root(harness_data).resolve()
    if not path.resolve().is_relative_to(state_root):
        raise PipelineStatePathError(f"pipeline path escapes state root: {path}")


def canonical_pipeline_path(task_id: str, harness_data: Path | None = None) -> Path:
    validate_task_id(task_id)
    return pipeline_state_root(harness_data) / task_id / "pipeline.md"


def legacy_pipeline_path(task_id: str, harness_data: Path | None = None) -> Path:
    validate_task_id(task_id)
    return pipeline_state_root(harness_data) / f"{task_id}-pipeline.md"
