"""Create a new canonical pipeline task without overwriting existing state."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path
import shlex

from pipeline_state_paths import PipelineStatePathError, canonical_pipeline_path, legacy_pipeline_path


class TaskBootstrapError(ValueError):
    """Raised when canonical task initialization cannot safely proceed."""


def create_task_state(
    task_id: str, repository: Path, branch: str, worktree: Path, harness_data: Path
) -> Path:
    try:
        target = canonical_pipeline_path(task_id, harness_data)
    except PipelineStatePathError as error:
        raise TaskBootstrapError(str(error)) from error
    if legacy_pipeline_path(task_id, harness_data).exists():
        raise TaskBootstrapError(f"legacy task already exists: {task_id}")
    try:
        target.parent.mkdir(parents=True)
    except FileExistsError as error:
        raise TaskBootstrapError(f"task already exists: {task_id}") from error
    temporary = target.with_suffix(".tmp")
    temporary.write_text(_initial_state(task_id, repository, branch, worktree))
    temporary.replace(target)
    return target


def _initial_state(task_id: str, repository: Path, branch: str, worktree: Path) -> str:
    timestamp = datetime.now(UTC).isoformat()
    return (
        "schema_version: 1\n"
        f"task_id: {task_id}\nrepository: {repository}\nphase: intake\n"
        f"status: in_progress\nverdict: pending\nbranch: {branch}\n"
        f"worktree: {worktree}\nupdated_at: {timestamp}\nupdated_by: codex\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id")
    parser.add_argument("repository", type=Path)
    parser.add_argument("branch")
    parser.add_argument("worktree", type=Path)
    parser.add_argument("harness_data", type=Path)
    arguments = parser.parse_args()
    create_task_state(
        arguments.task_id, arguments.repository, arguments.branch, arguments.worktree,
        arguments.harness_data,
    )
    print(f"export CLAUDE_PIPELINE_TASK_ID={shlex.quote(arguments.task_id)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
