"""Read canonical and supported legacy pipeline state."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pipeline_state_paths import (
    PipelineStatePathError,
    assert_pipeline_path,
    canonical_pipeline_path,
    legacy_pipeline_path,
)


class PipelineStateNotFound(Exception):
    """Raised when neither supported pipeline-state layout exists."""


@dataclass(frozen=True)
class PipelineStateDocument:
    layout: str
    path: Path
    content: str


def read_pipeline_state(
    task_id: str, harness_data: Path | None = None
) -> PipelineStateDocument:
    candidates = (
        ("canonical", canonical_pipeline_path(task_id, harness_data)),
        ("legacy-flat", legacy_pipeline_path(task_id, harness_data)),
    )
    for layout, path in candidates:
        if path.is_file():
            assert_pipeline_path(path, harness_data)
            return PipelineStateDocument(layout, path, path.read_text())
    raise PipelineStateNotFound(f"pipeline state not found for task: {task_id}")
