from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from scripts.lib.pr_handoff import (
    ExistingPullRequest,
    PrCreationError,
    PrHandoffError,
    PrHandoffService,
    PrHandoffState,
    PullRequestContext,
)
from scripts.lib.pr_creation import create_pull_request


REPOSITORY = "/repo/codex-harness"
BASE_HEAD = "a" * 40
FIRST_TARGET = "b" * 40
SECOND_TARGET = "c" * 40


def context(target_head: str = FIRST_TARGET) -> PullRequestContext:
    return PullRequestContext(
        task_id="task-20",
        run_id="run-1",
        repository=REPOSITORY,
        branch="build/task-20",
        base_head=BASE_HEAD,
        target_head=target_head,
        title="feat: add PR handoff",
        body="Preserve one-attempt PR delivery state.",
    )


def pull_request(request: PullRequestContext, number: int = 42) -> ExistingPullRequest:
    return ExistingPullRequest(
        repository=request.repository,
        task_id=request.task_id,
        run_id=request.run_id,
        branch=request.branch,
        base_head=request.base_head,
        target_head=request.target_head,
        number=number,
        url=f"https://github.com/example/repo/pull/{number}",
    )


def service(tmp_path: Path) -> PrHandoffService:
    return PrHandoffService("task-20", tmp_path)


def test_validates_and_round_trips_attempt_state(tmp_path: Path) -> None:
    state = PrHandoffState(
        schema_version=1,
        task_id="task-20",
        run_id="run-1",
        repository=REPOSITORY,
        branch="build/task-20",
        base_head=BASE_HEAD,
        target_head=FIRST_TARGET,
        attempt_count=1,
        outcome="PR_CREATION_FAILED",
        updated_at="2026-08-04T20:00:00+00:00",
        pr_number=None,
        pr_url=None,
        title="feat: add PR handoff",
        body="Preserve one-attempt PR delivery state.",
        failure_category="provider-unavailable",
        retry_authorized_by=None,
        retry_authorized_at=None,
    )

    store = service(tmp_path).store
    store.write(state)

    assert store.read() == state


@pytest.mark.parametrize(
    "override",
    [
        {"task_id": ""},
        {"schema_version": 2},
        {"schema_version": True},
        {"base_head": "not-a-head"},
        {"attempt_count": -1},
        {"attempt_count": True},
        {"outcome": "UNKNOWN"},
    ],
)
def test_rejects_malformed_or_contradictory_attempt_state(
    tmp_path: Path, override: dict[str, object]
) -> None:
    state = PrHandoffState(
        schema_version=1,
        task_id="task-20",
        run_id="run-1",
        repository=REPOSITORY,
        branch="build/task-20",
        base_head=BASE_HEAD,
        target_head=FIRST_TARGET,
        attempt_count=0,
        outcome="NOT_ATTEMPTED",
        updated_at="2026-08-04T20:00:00+00:00",
        pr_number=None,
        pr_url=None,
        title="feat: add PR handoff",
        body="Preserve one-attempt PR delivery state.",
        failure_category=None,
        retry_authorized_by=None,
        retry_authorized_at=None,
    )
    handoff = service(tmp_path)
    path = handoff.store.path
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({**state.as_dict(), **override}))

    with pytest.raises(PrHandoffError):
        handoff.store.read()


def test_reconciles_matching_existing_pr_without_consuming_attempt(
    tmp_path: Path,
) -> None:
    request = context()
    calls: list[str] = []

    result = service(tmp_path).submit(
        request,
        find_existing=lambda: pull_request(request),
        create=lambda: calls.append("create") or pull_request(request),
    )

    assert result.status == "EXISTING_PR"
    assert result.pull_request == pull_request(request)
    assert calls == []
    assert result.state.attempt_count == 0


def test_canonical_pr_creation_entrypoint_uses_handoff_service(tmp_path: Path) -> None:
    request = context()
    result = create_pull_request(
        service(tmp_path),
        request,
        find_existing=lambda: None,
        create=lambda: pull_request(request),
    )

    assert result.status == "PR_CREATED"
    assert result.state.outcome == "PR_CREATED"


def test_handoff_state_path_is_derived_from_task_identity(tmp_path: Path) -> None:
    assert service(tmp_path).store.path == (
        tmp_path / "pipeline-state" / "task-20" / "pr-handoff.json"
    )


@pytest.mark.parametrize("field", ["repository", "task_id", "branch", "base_head", "target_head"])
def test_rejects_mismatched_existing_pr(tmp_path: Path, field: str) -> None:
    request = context()
    existing = pull_request(request)
    mismatch = replace(existing, **{field: "mismatch"})

    with pytest.raises(PrHandoffError, match="existing PR"):
        service(tmp_path).submit(
            request,
            find_existing=lambda: mismatch,
            create=lambda: pull_request(request),
        )


def test_allows_one_creation_attempt_and_blocks_retry(tmp_path: Path) -> None:
    request = context()
    calls: list[str] = []
    handoff = service(tmp_path)

    first = handoff.submit(
        request,
        find_existing=lambda: None,
        create=lambda: calls.append("create") or pull_request(request),
    )

    with pytest.raises(PrHandoffError, match="attempt"):
        handoff.submit(
            request,
            find_existing=lambda: None,
            create=lambda: calls.append("retry") or pull_request(request, 43),
        )

    assert first.status == "PR_CREATED"
    assert calls == ["create"]


def test_changed_head_does_not_reset_attempt_allowance(tmp_path: Path) -> None:
    handoff = service(tmp_path)
    first_request = context(FIRST_TARGET)
    second_request = context(SECOND_TARGET)

    handoff.submit(
        first_request,
        find_existing=lambda: None,
        create=lambda: pull_request(first_request),
    )

    with pytest.raises(PrHandoffError, match="attempt"):
        handoff.submit(
            second_request,
            find_existing=lambda: None,
            create=lambda: pull_request(second_request, 43),
        )


def test_run_id_prevents_cross_run_allowance_reuse(tmp_path: Path) -> None:
    handoff = service(tmp_path)
    first = context()
    second = replace(first, run_id="run-2")

    handoff.submit(
        first,
        find_existing=lambda: None,
        create=lambda: pull_request(first),
    )

    with pytest.raises(PrHandoffError, match="identity"):
        handoff.submit(
            second,
            find_existing=lambda: None,
            create=lambda: pull_request(second),
        )


def test_reserves_attempt_before_provider_side_effect(tmp_path: Path) -> None:
    handoff = service(tmp_path)
    request = context()
    observed: list[str] = []

    def create() -> ExistingPullRequest:
        observed.append(handoff.store.read().outcome)
        return pull_request(request)

    handoff.submit(request, find_existing=lambda: None, create=create)

    assert observed == ["PR_ATTEMPT_RESERVED"]


def test_human_authorization_allows_second_attempt(tmp_path: Path) -> None:
    handoff = service(tmp_path)
    first_request = context(FIRST_TARGET)
    second_request = context(SECOND_TARGET)

    handoff.submit(
        first_request,
        find_existing=lambda: None,
        create=lambda: pull_request(first_request),
    )
    handoff.authorize_retry(second_request, "human-approval-1")

    result = handoff.submit(
        second_request,
        find_existing=lambda: None,
        create=lambda: pull_request(second_request, 43),
    )

    assert result.status == "PR_CREATED"
    assert result.state.attempt_count == 2
    assert result.state.retry_authorized_by == "human-approval-1"


def test_failure_records_copy_ready_manual_handoff_without_retry(tmp_path: Path) -> None:
    request = context()
    calls: list[str] = []
    handoff = service(tmp_path)

    result = handoff.submit(
        request,
        find_existing=lambda: None,
        create=lambda: calls.append("create") or (_ for _ in ()).throw(
            PrCreationError("provider-unavailable")
        ),
    )

    assert result.status == "PR_CREATION_FAILED"
    assert result.manual_title == request.title
    assert result.manual_body == request.body
    assert result.state.failure_category == "provider-unavailable"
    assert calls == ["create"]

    with pytest.raises(PrHandoffError, match="attempt"):
        handoff.submit(
            request,
            find_existing=lambda: None,
            create=lambda: calls.append("retry") or pull_request(request),
        )
    assert calls == ["create"]


def test_malformed_failure_category_uses_trusted_fallback(tmp_path: Path) -> None:
    request = context()
    result = service(tmp_path).submit(
        request,
        find_existing=lambda: None,
        create=lambda: (_ for _ in ()).throw(PrCreationError("")),
    )

    assert result.status == "PR_CREATION_FAILED"
    assert result.state.failure_category == "provider-error"


def test_invalid_pr_url_fails_closed_and_consumes_attempt(tmp_path: Path) -> None:
    request = context()
    invalid = replace(pull_request(request), url="https://github.com/example/repo/issues/42")
    handoff = service(tmp_path)

    with pytest.raises(PrHandoffError, match="URL"):
        handoff.submit(
            request,
            find_existing=lambda: None,
            create=lambda: invalid,
        )

    assert handoff.store.read().outcome == "PR_CREATION_FAILED"


def test_success_records_pr_and_never_merges(tmp_path: Path) -> None:
    request = context()
    result = service(tmp_path).submit(
        request,
        find_existing=lambda: None,
        create=lambda: pull_request(request),
    )

    assert result.status == "PR_CREATED"
    assert result.pull_request == pull_request(request)
    assert result.state.pr_number == 42
    assert result.state.pr_url == "https://github.com/example/repo/pull/42"


def test_existing_pr_after_head_change_does_not_reset_attempt_allowance(
    tmp_path: Path,
) -> None:
    handoff = service(tmp_path)
    first_request = context(FIRST_TARGET)
    second_request = context(SECOND_TARGET)

    handoff.submit(
        first_request,
        find_existing=lambda: None,
        create=lambda: pull_request(first_request),
    )
    reconciled = handoff.submit(
        second_request,
        find_existing=lambda: pull_request(second_request, 43),
        create=lambda: pull_request(second_request, 44),
    )

    assert reconciled.status == "EXISTING_PR"
    assert reconciled.state.attempt_count == 1
    with pytest.raises(PrHandoffError, match="attempt"):
        handoff.submit(
            second_request,
            find_existing=lambda: None,
            create=lambda: pull_request(second_request, 44),
        )


def test_state_symlink_target_fails_closed_without_overwriting_victim(
    tmp_path: Path,
) -> None:
    handoff = service(tmp_path)
    handoff.store.path.parent.mkdir(parents=True)
    victim = handoff.store.path.parent / "victim.json"
    victim.write_text("do not overwrite")
    target = handoff.store.path
    target.symlink_to(victim)
    state = PrHandoffState(
        schema_version=1,
        task_id="task-20",
        run_id="run-1",
        repository=REPOSITORY,
        branch="build/task-20",
        base_head=BASE_HEAD,
        target_head=FIRST_TARGET,
        attempt_count=0,
        outcome="NOT_ATTEMPTED",
        updated_at="2026-08-04T20:00:00+00:00",
        pr_number=None,
        pr_url=None,
        title="feat: add PR handoff",
        body="Preserve one-attempt PR delivery state.",
        failure_category=None,
        retry_authorized_by=None,
        retry_authorized_at=None,
    )

    with pytest.raises(PrHandoffError, match="target"):
        handoff.store.write(state)
    assert victim.read_text() == "do not overwrite"


def test_malformed_created_pr_records_failure_and_blocks_retry(tmp_path: Path) -> None:
    request = context()
    handoff = service(tmp_path)
    malformed = replace(pull_request(request), target_head="d" * 40)

    with pytest.raises(PrHandoffError):
        handoff.submit(
            request,
            find_existing=lambda: None,
            create=lambda: malformed,
        )

    state = handoff.store.read()
    assert state.outcome == "PR_CREATION_FAILED"
    assert state.attempt_count == 1
    with pytest.raises(PrHandoffError, match="attempt"):
        handoff.submit(
            request,
            find_existing=lambda: None,
            create=lambda: pull_request(request),
        )


def test_state_rejects_non_integer_pr_identity(tmp_path: Path) -> None:
    state = PrHandoffState(
        schema_version=1,
        task_id="task-20",
        run_id="run-1",
        repository=REPOSITORY,
        branch="build/task-20",
        base_head=BASE_HEAD,
        target_head=FIRST_TARGET,
        attempt_count=1,
        outcome="PR_CREATED",
        updated_at="2026-08-04T20:00:00+00:00",
        pr_number=42,
        pr_url="https://github.com/example/repo/pull/42",
        title="feat: add PR handoff",
        body="Preserve one-attempt PR delivery state.",
        failure_category=None,
        retry_authorized_by=None,
        retry_authorized_at=None,
    )
    handoff = service(tmp_path)
    path = handoff.store.path
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({**state.as_dict(), "pr_number": "42"}))

    with pytest.raises(PrHandoffError):
        handoff.store.read()
