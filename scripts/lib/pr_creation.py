"""Canonical PR creation entry point."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Callable

from scripts.lib.pr_handoff import (
    ExistingPullRequest,
    PrHandoffResult,
    PrHandoffService,
    PullRequestContext,
)


@dataclass(frozen=True)
class TaskPullRequestInput:
    task_id: str
    run_id: str
    repository: str
    branch: str
    base_head: str
    target_head: str
    title: str
    body: str


def create_pull_request(
    handoff: PrHandoffService,
    request: PullRequestContext,
    *,
    find_existing: Callable[[], ExistingPullRequest | None],
    create: Callable[[], ExistingPullRequest],
) -> PrHandoffResult:
    """Route every provider call through the task-bound handoff service."""
    return handoff.submit(request, find_existing=find_existing, create=create)


def submit_task_pull_request(
    request_input: TaskPullRequestInput,
    *,
    find_existing: Callable[[], ExistingPullRequest | None],
    create: Callable[[], ExistingPullRequest],
    harness_data=None,
) -> PrHandoffResult:
    """Build task identity and submit it through the canonical boundary."""
    request = PullRequestContext(**asdict(request_input))
    handoff = PrHandoffService(request.task_id, harness_data)
    return create_pull_request(handoff, request, find_existing=find_existing, create=create)
