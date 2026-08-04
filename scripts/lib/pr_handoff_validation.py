"""Validate PR handoff identities and state invariants."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re

from scripts.lib.pr_handoff_state import (
    ExistingPullRequest,
    PrHandoffError,
    PrHandoffState,
    PullRequestContext,
)


def validate_state(state: PrHandoffState) -> None:
    _validate_structure(state)
    _validate_pr_identity(state)
    _validate_retry_authorization(state)


def _validate_structure(state: PrHandoffState) -> None:
    _validate_version(state)
    validate_context(_context_from_state(state))
    _validate_attempt(state)
    _validate_outcome(state)
    _validate_timestamp(state.updated_at, "updated_at")


def _context_from_state(state: PrHandoffState) -> PullRequestContext:
    return PullRequestContext(
        state.task_id, state.repository, state.branch, state.base_head,
        state.target_head, state.title, state.body,
    )


def _validate_version(state: PrHandoffState) -> None:
    if type(state.schema_version) is not int or state.schema_version != 1:
        raise PrHandoffError("unsupported PR handoff schema_version")


def _validate_attempt(state: PrHandoffState) -> None:
    if type(state.attempt_count) is not int or state.attempt_count not in (0, 1, 2):
        raise PrHandoffError("attempt_count is outside the allowed range")


def _validate_outcome(state: PrHandoffState) -> None:
    _require_outcome(state)
    _require_outcome_attempt_pair(state)
    _validate_failure_category(state)


def _require_outcome(state: PrHandoffState) -> None:
    outcomes = {"NOT_ATTEMPTED", "EXISTING_PR", "PR_CREATED", "PR_CREATION_FAILED"}
    if state.outcome not in outcomes:
        raise PrHandoffError("unsupported PR handoff outcome")


def _require_outcome_attempt_pair(state: PrHandoffState) -> None:
    creation_outcome = {"PR_CREATED", "PR_CREATION_FAILED"}
    if state.attempt_count == 0 and state.outcome in creation_outcome:
        raise PrHandoffError("zero attempts cannot have a creation outcome")
    if state.attempt_count and state.outcome == "NOT_ATTEMPTED":
        raise PrHandoffError("attempted state cannot be NOT_ATTEMPTED")


def _validate_failure_category(state: PrHandoffState) -> None:
    failed = state.outcome == "PR_CREATION_FAILED"
    present = _valid_text(state.failure_category)
    if failed != present:
        raise PrHandoffError("PR failure category is inconsistent")


def _validate_pr_identity(state: PrHandoffState) -> None:
    _validate_pr_number(state.pr_number)
    _validate_pr_url(state.pr_url)
    has_identity = state.pr_number is not None and state.pr_url is not None
    needs_identity = state.outcome in {"PR_CREATED", "EXISTING_PR"}
    if has_identity != needs_identity:
        raise PrHandoffError("PR identity is inconsistent with outcome")


def _validate_pr_number(value: object) -> None:
    if value is not None and (type(value) is not int or value < 1):
        raise PrHandoffError("PR number is invalid")


def _validate_pr_url(value: object) -> None:
    if value is not None and not _valid_text(value):
        raise PrHandoffError("PR URL is invalid")


def _validate_retry_authorization(state: PrHandoffState) -> None:
    _require_authorization_pair(state)
    if state.retry_authorized_by is not None:
        _validate_timestamp(state.retry_authorized_at, "retry_authorized_at")


def _require_authorization_pair(state: PrHandoffState) -> None:
    authorized = state.retry_authorized_by is not None
    timestamp = state.retry_authorized_at is not None
    if authorized != timestamp:
        raise PrHandoffError("retry authorization is incomplete")
    if authorized and state.attempt_count not in {1, 2}:
        raise PrHandoffError("retry authorization is not bound to one attempt")


def validate_context(request: PullRequestContext) -> None:
    _require_text_fields(request, ("task_id", "repository", "branch", "title", "body"))
    if not Path(request.repository).is_absolute():
        raise PrHandoffError("repository must be absolute")
    _validate_head(request.base_head, "base_head")
    _validate_head(request.target_head, "target_head")


def _require_text_fields(value: object, names: tuple[str, ...]) -> None:
    for name in names:
        if not _valid_text(getattr(value, name)):
            raise PrHandoffError(f"{name} is required")


def _validate_head(value: object, name: str) -> None:
    valid = isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", value)
    if not valid:
        raise PrHandoffError(f"{name} is not a valid Git HEAD")


def _validate_timestamp(value: object, name: str) -> None:
    if not _valid_text(value):
        raise PrHandoffError(f"{name} is required")
    try:
        datetime.fromisoformat(value)
    except ValueError as error:
        raise PrHandoffError(f"{name} is not an ISO timestamp") from error


def _valid_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value == value.strip()


def validate_pull_request(
    pull_request: ExistingPullRequest, request: PullRequestContext
) -> None:
    _require_text_fields(pull_request, ("repository", "task_id", "branch", "url"))
    _validate_head(pull_request.base_head, "existing PR base_head")
    _validate_head(pull_request.target_head, "existing PR target_head")
    if type(pull_request.number) is not int or pull_request.number < 1:
        raise PrHandoffError("existing PR number is invalid")
    require_matching_identity(pull_request, request)


def require_matching_identity(
    pull_request: ExistingPullRequest, request: PullRequestContext
) -> None:
    fields = ("repository", "task_id", "branch", "base_head", "target_head")
    if any(getattr(pull_request, field) != getattr(request, field) for field in fields):
        raise PrHandoffError("existing PR identity does not match request")


def require_same_context(
    state: PrHandoffState, request: PullRequestContext, allow_target_change: bool = False
) -> None:
    fields = ("task_id", "repository", "branch", "base_head")
    if any(getattr(state, field) != getattr(request, field) for field in fields):
        raise PrHandoffError("PR handoff state identity does not match request")
    if not allow_target_change and state.target_head != request.target_head:
        raise PrHandoffError("PR handoff target HEAD does not match request")


def _valid_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value == value.strip()
