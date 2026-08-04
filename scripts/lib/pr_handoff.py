"""Execute the one-attempt pull-request handoff contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from scripts.lib.pr_handoff_state import (
    ExistingPullRequest,
    PrHandoffError,
    PrHandoffState,
    PrHandoffStore,
    PullRequestContext,
    carry_retry_authorization,
    replace_state,
    timestamp,
)
from scripts.lib.pr_handoff_validation import (
    require_same_context,
    validate_context,
    validate_pull_request,
)


class PrCreationError(RuntimeError):
    """Raised by a creator port when the provider rejects PR creation."""

    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


@dataclass(frozen=True)
class PrHandoffResult:
    status: str
    state: PrHandoffState
    pull_request: ExistingPullRequest | None
    manual_title: str | None
    manual_body: str | None


class PrHandoffService:
    """Reconcile or create one task-bound pull request."""

    def __init__(self, task_id: str, harness_data=None) -> None:
        self.task_id = task_id
        self.store = PrHandoffStore(task_id, harness_data)

    def submit(
        self,
        request: PullRequestContext,
        *,
        find_existing: Callable[[], ExistingPullRequest | None],
        create: Callable[[], ExistingPullRequest],
    ) -> PrHandoffResult:
        _validate_request(request)
        if request.task_id != self.task_id:
            raise PrHandoffError("request task_id does not match handoff store")
        existing = find_existing()
        if existing is not None:
            return self._reconcile(request, existing)
        return self._create(request, create)

    def authorize_retry(self, request: PullRequestContext, approver: str) -> PrHandoffState:
        _validate_request(request)
        if not _valid_text(approver):
            raise PrHandoffError("retry approver is required")
        previous = self.store.read_optional()
        _require_retryable_state(previous, request)
        return self._store_authorization(previous, request, approver)

    def _store_authorization(self, previous, request, approver):
        state = replace_state(previous, target_head=request.target_head,
                              retry_authorized_by=approver, retry_authorized_at=timestamp())
        self.store.write(state)
        return state

    def _reconcile(
        self, request: PullRequestContext, existing: ExistingPullRequest
    ) -> PrHandoffResult:
        _validate_existing(existing, request)
        previous = self.store.read_optional()
        if previous is not None:
            require_same_context(previous, request, allow_target_change=True)
        attempts = previous.attempt_count if previous is not None else 0
        state = _state_for_pr(request, attempts, "EXISTING_PR", existing, previous)
        self.store.write(state)
        return _result("EXISTING_PR", state, existing)

    def _create(
        self, request: PullRequestContext, create: Callable[[], ExistingPullRequest]
    ) -> PrHandoffResult:
        previous = self.store.read_optional()
        attempt = _next_attempt(previous, request)
        reserved = _state_for_pr(request, attempt, "PR_ATTEMPT_RESERVED", None, previous)
        self.store.write(reserved)
        try:
            created = create()
            _validate_existing(created, request)
        except PrCreationError as error:
            return self._failure(request, attempt, error.category, previous)
        except PrHandoffError:
            self._record_invalid_creator(request, attempt, previous)
            raise
        except Exception as error:
            return self._failure(request, attempt, "creator-error", previous, error)
        state = _state_for_pr(request, attempt, "PR_CREATED", created, previous)
        self.store.write(state)
        return _result("PR_CREATED", state, created)

    def _failure(self, request, attempt, category, previous, error=None):
        if error is not None:
            return _raise_creator_error(request, attempt, category, previous, self.store, error)
        state = _failure_state(request, attempt, category, previous)
        self.store.write(state)
        return _result("PR_CREATION_FAILED", state, None, request)

    def _record_invalid_creator(self, request, attempt, previous):
        state = _failure_state(request, attempt, "invalid-creator-result", previous)
        self.store.write(state)


def _raise_creator_error(request, attempt, category, previous, store, error):
    state = _failure_state(request, attempt, category, previous)
    store.write(state)
    raise PrHandoffError("PR creator failed unexpectedly") from error


def _validate_request(request: PullRequestContext) -> None:
    validate_context(request)


def _validate_existing(existing, request) -> None:
    validate_pull_request(existing, request)


def _require_retryable_state(previous, request) -> None:
    if previous is None or previous.attempt_count != 1:
        raise PrHandoffError("retry authorization requires one prior attempt")
    require_same_context(previous, request, allow_target_change=True)


def _next_attempt(previous, request) -> int:
    if previous is None:
        return 1
    require_same_context(previous, request, allow_target_change=True)
    if previous.attempt_count == 1 and previous.retry_authorized_by:
        return 2
    raise PrHandoffError("automatic PR attempt allowance is exhausted")


def _failure_state(request, attempt, category, previous):
    state = _state_for_pr(request, attempt, "PR_CREATION_FAILED", None, previous)
    return replace_state(state, failure_category=_require_category(category))


def _state_for_pr(request, attempt, outcome, pull_request, previous):
    identity = (pull_request.number, pull_request.url) if pull_request else (None, None)
    state = PrHandoffState(1, request.task_id, request.run_id, request.repository, request.branch,
                           request.base_head, request.target_head, attempt, outcome,
                           timestamp(), *identity, request.title, request.body,
                           None, None, None)
    return carry_retry_authorization(state, previous)


def _result(status, state, pull_request, request=None):
    failed = status == "PR_CREATION_FAILED" and request is not None
    return PrHandoffResult(
        status, state, pull_request,
        request.title if failed else None,
        request.body if failed else None,
    )


def _require_category(category):
    if not _valid_text(category):
        return "provider-error"
    return category


def _valid_text(value):
    return isinstance(value, str) and bool(value.strip()) and value == value.strip()
