from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

from scripts.lib.review_evidence import (  # noqa: E402
    ReviewEvidenceError,
    parse_review_evidence,
    serialize_review_evidence,
)


def evidence(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": 1,
        "task_id": "t14-t15-review-loop",
        "reviewed_head": "b" * 40,
        "software_engineer_id": "software_engineer-01",
        "software_engineer_session_id": "session-software_engineer-01",
        "software_engineer_model": "gpt-5.6-terra",
        "reviewer_id": "code_reviewer-01",
        "reviewer_session_id": "session-code_reviewer-01",
        "reviewer_model": "gpt-5.6-sol",
        "dispatch_id": "review-dispatch-01",
        "run_id": "run-01",
        "telemetry_event_id": "review-event-01",
        "verdict": "CHANGES_REQUESTED",
        "findings": [
            {
                "finding_id": "finding-01",
                "severity": "HIGH",
                "file": "scripts/lib/example.py",
                "line": 12,
                "message": "Reject stale evidence.",
                "preventable": False,
                "raising_reviewer_id": "code_reviewer-01",
                "raising_reviewer_session_id": "session-code_reviewer-01",
            }
        ],
    }
    value.update(overrides)
    return value


def test_review_evidence_binds_task_head_engineer_reviewer_and_findings() -> None:
    parsed = parse_review_evidence(evidence())

    assert serialize_review_evidence(parsed) == evidence()
    assert parsed.findings[0].raising_reviewer_id == parsed.reviewer_id


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"task_id": ""}, "task_id"),
        ({"reviewed_head": "short"}, "reviewed_head"),
        ({"reviewer_id": "software_engineer-01"}, "self-review"),
        ({"reviewer_session_id": "session-software_engineer-01"}, "self-review"),
        ({"reviewer_model": "gpt-5.6-terra"}, "distinct model"),
        ({"verdict": "APPROVE"}, "APPROVE"),
        ({"findings": []}, "CHANGES_REQUESTED"),
    ],
)
def test_review_evidence_rejects_missing_or_contradictory_bindings(
    override: dict[str, object], message: str
) -> None:
    with pytest.raises(ReviewEvidenceError, match=message):
        parse_review_evidence(evidence(**override))


def test_finding_must_bind_the_raising_reviewer() -> None:
    finding = evidence()["findings"][0].copy()
    finding["raising_reviewer_id"] = "code_reviewer-substitute"

    with pytest.raises(ReviewEvidenceError, match="raising reviewer"):
        parse_review_evidence(evidence(findings=[finding]))


def test_finding_file_must_be_a_concrete_reviewed_path() -> None:
    finding = evidence()["findings"][0].copy()
    finding["file"] = "scripts/lib/*.py"

    with pytest.raises(ReviewEvidenceError, match="concrete"):
        parse_review_evidence(evidence(findings=[finding]))
