"""Require an explicit human decision before resuming a discovered task."""

from __future__ import annotations

from dataclasses import dataclass

if __package__:
    from .task_discovery import DiscoveredTask
else:
    from task_discovery import DiscoveredTask


class TaskSelectionError(ValueError):
    """Raised when a human selection cannot be safely interpreted."""


@dataclass(frozen=True)
class TaskSelection:
    kind: str
    task: DiscoveredTask | None


def select_task(tasks: list[DiscoveredTask], choice: str | None) -> TaskSelection:
    _require_unique_task_ids(tasks)
    if choice == "new":
        return TaskSelection("new", None)
    if not choice or not choice.startswith("resume:"):
        raise TaskSelectionError("explicit task selection is required")
    return TaskSelection("resume", _selected_task(tasks, choice.removeprefix("resume:")))


def _require_unique_task_ids(tasks: list[DiscoveredTask]) -> None:
    task_ids = [task.task_id for task in tasks]
    if len(task_ids) != len(set(task_ids)):
        raise TaskSelectionError("discovered task identities are ambiguous")


def _selected_task(tasks: list[DiscoveredTask], task_id: str) -> DiscoveredTask:
    matches = [task for task in tasks if task.task_id == task_id]
    if len(matches) != 1:
        raise TaskSelectionError(f"selection does not identify one task: {task_id}")
    return matches[0]
