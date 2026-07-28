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


class PipelineStateValidationError(ValueError):
    """Raised when a readable state document cannot be trusted."""


@dataclass(frozen=True)
class PipelineStateDocument:
    layout: str
    path: Path
    content: str
    fields: dict[str, str]


CANONICAL_REQUIRED_FIELDS = (
    "schema_version",
    "task_id",
    "repository",
    "phase",
    "status",
    "verdict",
    "branch",
    "worktree",
    "updated_at",
    "updated_by",
)
LEGACY_REQUIRED_FIELDS = (
    "task_id",
    "project_path",
    "current_phase",
    "status",
    "branch",
)


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
            content = path.read_text()
            fields = _parse_fields(content)
            _validate_state(layout, fields, task_id)
            return PipelineStateDocument(layout, path, content, fields)
    raise PipelineStateNotFound(f"pipeline state not found for task: {task_id}")


def _parse_fields(content: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in content.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, separator, value = line.partition(":")
        if _is_malformed_field(key, separator, value, fields):
            raise PipelineStateValidationError("malformed pipeline state field")
        fields[key] = value.strip()
    return fields


def _is_malformed_field(key: str, separator: str, value: str, fields: dict[str, str]) -> bool:
    return (
        not separator
        or not value.startswith(" ")
        or not key
        or key != key.strip()
        or key in fields
    )


def _validate_state(layout: str, fields: dict[str, str], task_id: str) -> None:
    required_fields = CANONICAL_REQUIRED_FIELDS if layout == "canonical" else LEGACY_REQUIRED_FIELDS
    _require_fields(fields, required_fields)
    _require_matching_task_id(fields, task_id)
    if layout == "canonical" and fields["schema_version"] != "1":
        raise PipelineStateValidationError("unsupported schema_version")
    if layout == "canonical" and fields["updated_by"] not in {"claude", "codex"}:
        raise PipelineStateValidationError("unsupported updated_by")


def _require_fields(fields: dict[str, str], required_fields: tuple[str, ...]) -> None:
    for field in required_fields:
        if not fields.get(field):
            raise PipelineStateValidationError(f"missing required field: {field}")


def _require_matching_task_id(fields: dict[str, str], task_id: str) -> None:
    if fields["task_id"] != task_id:
        raise PipelineStateValidationError("task_id does not match requested task")
