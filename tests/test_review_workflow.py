from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

from scripts.lib.review_evidence import parse_review_evidence  # noqa: E402
from scripts.lib.review_workflow import ReviewWorkflow, ReviewWorkflowError  # noqa: E402
from scripts.lib.spawn_telemetry import (  # noqa: E402
    SpawnEnvelope,
    SpawnTelemetryStore,
    TokenMetric,
)
from tests.test_review_evidence import evidence  # noqa: E402


def workflow() -> ReviewWorkflow:
    return ReviewWorkflow.start(parse_review_evidence(evidence()))


def telemetry(tmp_path: Path, event_id: str = "review-event-02") -> SpawnTelemetryStore:
    store = SpawnTelemetryStore(tmp_path / "spawn-events.jsonl")
    store.record(
        SpawnEnvelope(
            1, event_id, "t14-t15-review-loop", "run-01",
            "review-dispatch-01", "code_reviewer", "code_reviewer-01",
            "session-code_reviewer-01", None, "gpt-5.6-sol",
            "gpt-5.6-sol", "medium", "medium", TokenMetric(10, None),
            TokenMetric(0, None), TokenMetric(5, None), 100, "rereview-01",
        )
    )
    return store


def test_findings_return_to_bound_engineer_and_invalidate_prior_review() -> None:
    state = workflow()

    assert state.findings_for(
        "software_engineer-01", "session-software_engineer-01"
    )[0].finding_id == "finding-01"

    fixed = state.record_fix(
        "software_engineer-01", "session-software_engineer-01", "c" * 40
    )

    assert fixed.current_head == "c" * 40
    assert fixed.review_evidence is None
    assert fixed.requires_reviewer == (
        "code_reviewer-01",
        "session-code_reviewer-01",
    )


@pytest.mark.parametrize(
    ("engineer_id", "session_id"),
    [
        ("software_engineer-other", "session-software_engineer-01"),
        ("software_engineer-01", "session-software_engineer-other"),
    ],
)
def test_findings_and_fixes_reject_substitute_engineers(
    engineer_id: str, session_id: str
) -> None:
    state = workflow()

    with pytest.raises(ReviewWorkflowError, match="bound engineer"):
        state.findings_for(engineer_id, session_id)
    with pytest.raises(ReviewWorkflowError, match="bound engineer"):
        state.record_fix(engineer_id, session_id, "c" * 40)


def test_targeted_rereview_requires_raising_reviewer_and_fresh_telemetry(
    tmp_path: Path,
) -> None:
    fixed = workflow().record_fix(
        "software_engineer-01", "session-software_engineer-01", "c" * 40
    )
    approved = parse_review_evidence(
        evidence(
            reviewed_head="c" * 40,
            telemetry_event_id="review-event-02",
            verdict="APPROVE",
            findings=[],
        )
    )

    store = telemetry(tmp_path)
    completed = fixed.accept_targeted_rereview(approved, store)

    assert completed.review_evidence == approved
    assert completed.requires_reviewer is None

    wrong_reviewer = replace(
        approved,
        reviewer_id="code_reviewer-other",
        reviewer_session_id="session-code_reviewer-other",
    )
    with pytest.raises(ReviewWorkflowError, match="raising reviewer"):
        fixed.accept_targeted_rereview(wrong_reviewer, store)


def test_targeted_rereview_rejects_stale_head_task_or_telemetry(
    tmp_path: Path,
) -> None:
    fixed = workflow().record_fix(
        "software_engineer-01", "session-software_engineer-01", "c" * 40
    )
    approved = parse_review_evidence(
        evidence(
            reviewed_head="c" * 40,
            telemetry_event_id="review-event-02",
            verdict="APPROVE",
            findings=[],
        )
    )

    store = telemetry(tmp_path)
    for stale in (
        replace(approved, reviewed_head="b" * 40),
        replace(approved, task_id="another-task"),
        replace(approved, telemetry_event_id="review-event-01"),
    ):
        with pytest.raises(ReviewWorkflowError):
            fixed.accept_targeted_rereview(stale, store)


def test_fix_requires_a_new_full_git_head() -> None:
    with pytest.raises(ReviewWorkflowError, match="Git object ID"):
        workflow().record_fix(
            "software_engineer-01", "session-software_engineer-01", "new-head"
        )


def test_targeted_rereview_rejects_missing_correlated_telemetry(
    tmp_path: Path,
) -> None:
    fixed = workflow().record_fix(
        "software_engineer-01", "session-software_engineer-01", "c" * 40
    )
    approved = parse_review_evidence(
        evidence(
            reviewed_head="c" * 40,
            telemetry_event_id="review-event-02",
            verdict="APPROVE",
            findings=[],
        )
    )

    with pytest.raises(ReviewWorkflowError, match="telemetry"):
        fixed.accept_targeted_rereview(
            approved, SpawnTelemetryStore(tmp_path / "missing.jsonl")
        )
