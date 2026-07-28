"""Discover active pipeline tasks for one repository without changing state."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

if __package__:
    from .pipeline_state import PipelineStateDocument, read_pipeline_state
    from .pipeline_state_paths import PipelineStatePathError, pipeline_state_root, validate_task_id
else:
    from pipeline_state import PipelineStateDocument, read_pipeline_state
    from pipeline_state_paths import PipelineStatePathError, pipeline_state_root, validate_task_id


ACTIVE_STATUSES = {"active", "in_progress"}
LEGACY_SUFFIX = "-pipeline.md"


@dataclass(frozen=True)
class DiscoveredTask:
    task_id: str
    repository: Path
    branch: str
    worktree: Path | None
    phase: str
    status: str
    verdict: str | None
    updated_at: str | None
    updated_by: str | None


def discover_repository_tasks(
    repository: Path, harness_data: Path | None = None
) -> list[DiscoveredTask]:
    state_root = pipeline_state_root(harness_data)
    if not state_root.exists():
        return []
    if state_root.is_symlink():
        raise PipelineStatePathError(f"unsafe pipeline state root: {state_root}")
    tasks = _read_task_documents(state_root, harness_data)
    return _matching_active_tasks(tasks, repository)


def _read_task_documents(
    state_root: Path, harness_data: Path | None
) -> list[PipelineStateDocument]:
    return [read_pipeline_state(task_id, harness_data) for task_id in _task_ids(state_root)]


def _task_ids(state_root: Path) -> list[str]:
    canonical_ids = [entry.name for entry in state_root.iterdir() if entry.is_dir()]
    legacy_ids = [_legacy_task_id(entry) for entry in state_root.glob(f"*{LEGACY_SUFFIX}")]
    return sorted(set(_validated_task_ids(canonical_ids + legacy_ids)))


def _legacy_task_id(path: Path) -> str:
    return path.name.removesuffix(LEGACY_SUFFIX)


def _validated_task_ids(task_ids: list[str]) -> list[str]:
    for task_id in task_ids:
        validate_task_id(task_id)
    return task_ids


def _matching_active_tasks(
    documents: list[PipelineStateDocument], repository: Path
) -> list[DiscoveredTask]:
    normalized_repository = repository.resolve()
    tasks = [_task_summary(document) for document in documents]
    return [task for task in tasks if _is_matching_active_task(task, normalized_repository)]


def _task_summary(document: PipelineStateDocument) -> DiscoveredTask:
    fields = document.fields
    repository = fields.get("repository") or fields["project_path"]
    return DiscoveredTask(
        task_id=fields["task_id"], repository=Path(repository).resolve(), branch=fields["branch"],
        worktree=_optional_path(fields.get("worktree")), phase=_phase(fields), status=fields["status"],
        verdict=fields.get("verdict"), updated_at=fields.get("updated_at"), updated_by=fields.get("updated_by"),
    )


def _optional_path(value: str | None) -> Path | None:
    return Path(value).resolve() if value else None


def _phase(fields: dict[str, str]) -> str:
    return fields.get("phase") or fields["current_phase"]


def _is_matching_active_task(task: DiscoveredTask, repository: Path) -> bool:
    return task.repository == repository and task.status in ACTIVE_STATUSES
