"""Validate identity-bound code review evidence."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
import re
from typing import Any


class ReviewEvidenceError(ValueError):
    """Raised when formal review evidence is incomplete or contradictory."""


IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
GIT_HEAD = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
VERDICTS = frozenset({"APPROVE", "CHANGES_REQUESTED"})
SEVERITIES = frozenset({"CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"})
EVIDENCE_FIELDS = frozenset(
    {
        "schema_version", "task_id", "reviewed_head", "software_engineer_id",
        "software_engineer_session_id", "software_engineer_model", "reviewer_id",
        "reviewer_session_id", "reviewer_model",
        "dispatch_id", "run_id", "telemetry_event_id", "verdict", "findings",
    }
)
FINDING_FIELDS = frozenset(
    {
        "finding_id", "severity", "file", "line", "message", "preventable",
        "raising_reviewer_id", "raising_reviewer_session_id",
    }
)


@dataclass(frozen=True)
class ReviewFinding:
    finding_id: str
    severity: str
    file: str
    line: int
    message: str
    preventable: bool
    raising_reviewer_id: str
    raising_reviewer_session_id: str


@dataclass(frozen=True)
class ReviewEvidence:
    schema_version: int
    task_id: str
    reviewed_head: str
    software_engineer_id: str
    software_engineer_session_id: str
    software_engineer_model: str
    reviewer_id: str
    reviewer_session_id: str
    reviewer_model: str
    dispatch_id: str
    run_id: str
    telemetry_event_id: str
    verdict: str
    findings: tuple[ReviewFinding, ...]


def parse_review_evidence(value: object) -> ReviewEvidence:
    fields = _mapping(value, "review evidence")
    _exact_fields(fields, EVIDENCE_FIELDS, "review evidence")
    if fields["schema_version"] != 1:
        raise ReviewEvidenceError("unsupported schema_version")
    evidence = _build_evidence(fields)
    _validate_evidence(evidence)
    return evidence


def serialize_review_evidence(evidence: ReviewEvidence) -> dict[str, Any]:
    value = asdict(evidence)
    value["findings"] = [asdict(finding) for finding in evidence.findings]
    return value


def _build_evidence(fields: dict[str, Any]) -> ReviewEvidence:
    return ReviewEvidence(
        schema_version=1,
        task_id=_identifier(fields["task_id"], "task_id"),
        reviewed_head=_head(fields["reviewed_head"]),
        software_engineer_id=_identifier(
            fields["software_engineer_id"], "software_engineer_id"
        ),
        software_engineer_session_id=_identifier(
            fields["software_engineer_session_id"], "software_engineer_session_id"
        ),
        software_engineer_model=_text(
            fields["software_engineer_model"], "software_engineer_model"
        ),
        reviewer_id=_identifier(fields["reviewer_id"], "reviewer_id"),
        reviewer_session_id=_identifier(
            fields["reviewer_session_id"], "reviewer_session_id"
        ),
        reviewer_model=_text(fields["reviewer_model"], "reviewer_model"),
        dispatch_id=_identifier(fields["dispatch_id"], "dispatch_id"),
        run_id=_identifier(fields["run_id"], "run_id"),
        telemetry_event_id=_identifier(
            fields["telemetry_event_id"], "telemetry_event_id"
        ),
        verdict=_choice(fields["verdict"], VERDICTS, "verdict"),
        findings=_findings(fields["findings"]),
    )


def _findings(value: object) -> tuple[ReviewFinding, ...]:
    if not isinstance(value, list):
        raise ReviewEvidenceError("findings must be a list")
    findings = tuple(_finding(item) for item in value)
    if len({finding.finding_id for finding in findings}) != len(findings):
        raise ReviewEvidenceError("finding_id must be unique")
    return findings


def _finding(value: object) -> ReviewFinding:
    fields = _mapping(value, "finding")
    _exact_fields(fields, FINDING_FIELDS, "finding")
    return ReviewFinding(
        finding_id=_identifier(fields["finding_id"], "finding_id"),
        severity=_choice(fields["severity"], SEVERITIES, "severity"),
        file=_relative_path(fields["file"]),
        line=_positive_integer(fields["line"], "line"),
        message=_text(fields["message"], "message"),
        preventable=_boolean(fields["preventable"], "preventable"),
        raising_reviewer_id=_identifier(
            fields["raising_reviewer_id"], "raising_reviewer_id"
        ),
        raising_reviewer_session_id=_identifier(
            fields["raising_reviewer_session_id"], "raising_reviewer_session_id"
        ),
    )


def _validate_evidence(evidence: ReviewEvidence) -> None:
    if (
        evidence.reviewer_id == evidence.software_engineer_id
        or evidence.reviewer_session_id == evidence.software_engineer_session_id
    ):
        raise ReviewEvidenceError("self-review is forbidden")
    if evidence.reviewer_model == evidence.software_engineer_model:
        raise ReviewEvidenceError("formal review requires a distinct model")
    if evidence.verdict == "APPROVE" and evidence.findings:
        raise ReviewEvidenceError("APPROVE cannot contain findings")
    if evidence.verdict == "CHANGES_REQUESTED" and not evidence.findings:
        raise ReviewEvidenceError("CHANGES_REQUESTED requires findings")
    if any(not _raised_by_reviewer(evidence, finding) for finding in evidence.findings):
        raise ReviewEvidenceError("finding must bind the raising reviewer")


def _raised_by_reviewer(
    evidence: ReviewEvidence, finding: ReviewFinding
) -> bool:
    return (
        finding.raising_reviewer_id == evidence.reviewer_id
        and finding.raising_reviewer_session_id == evidence.reviewer_session_id
    )


def _mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ReviewEvidenceError(f"{name} must be an object")
    return value


def _exact_fields(
    fields: dict[str, Any], expected: frozenset[str], name: str
) -> None:
    missing = expected - fields.keys()
    unknown = fields.keys() - expected
    if missing:
        raise ReviewEvidenceError(f"missing required field: {min(missing)}")
    if unknown:
        raise ReviewEvidenceError(f"unknown field in {name}: {min(unknown)}")


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ReviewEvidenceError(f"{name} must be normalized text")
    if any(ord(character) < 32 for character in value):
        raise ReviewEvidenceError(f"{name} contains control characters")
    return value


def _identifier(value: object, name: str) -> str:
    text = _text(value, name)
    if not IDENTIFIER.fullmatch(text):
        raise ReviewEvidenceError(f"{name} must be a stable identifier")
    return text


def _head(value: object) -> str:
    text = _text(value, "reviewed_head")
    if not GIT_HEAD.fullmatch(text):
        raise ReviewEvidenceError("reviewed_head must be a full Git object ID")
    return text


def _choice(value: object, choices: frozenset[str], name: str) -> str:
    text = _text(value, name)
    if text not in choices:
        raise ReviewEvidenceError(f"unsupported {name}")
    return text


def _relative_path(value: object) -> str:
    text = _text(value, "file")
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts or path == PurePosixPath("."):
        raise ReviewEvidenceError("file must be a safe repository-relative path")
    if any(character in text for character in "*?["):
        raise ReviewEvidenceError("file must be a concrete reviewed path")
    return str(path)


def _positive_integer(value: object, name: str) -> int:
    if type(value) is not int or value < 1:
        raise ReviewEvidenceError(f"{name} must be a positive integer")
    return value


def _boolean(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise ReviewEvidenceError(f"{name} must be a boolean")
    return value
