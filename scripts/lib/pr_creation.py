"""Canonical PR creation entry point."""

from __future__ import annotations

from typing import Callable

from scripts.lib.pr_handoff import (
    ExistingPullRequest,
    PrHandoffResult,
    PrHandoffService,
    PullRequestContext,
)


def create_pull_request(
    handoff: PrHandoffService,
    request: PullRequestContext,
    *,
    find_existing: Callable[[], ExistingPullRequest | None],
    create: Callable[[], ExistingPullRequest],
) -> PrHandoffResult:
    """Route every provider call through the task-bound handoff service."""
    return handoff.submit(request, find_existing=find_existing, create=create)
