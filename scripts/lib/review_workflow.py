"""Identity-bound review finding and targeted re-review transitions."""

from __future__ import annotations

from dataclasses import dataclass, replace
import re

from scripts.lib.review_evidence import ReviewEvidence, ReviewFinding
from scripts.lib.spawn_telemetry import SpawnEnvelope, SpawnTelemetryStore


class ReviewWorkflowError(ValueError):
    """Raised when the review loop changes identity or immutable target."""


GIT_HEAD = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")


@dataclass(frozen=True)
class ReviewWorkflow:
    task_id: str
    software_engineer_id: str
    software_engineer_session_id: str
    current_head: str
    review_evidence: ReviewEvidence | None
    requires_reviewer: tuple[str, str] | None
    prior_telemetry_event_id: str

    @classmethod
    def start(cls, evidence: ReviewEvidence) -> ReviewWorkflow:
        return cls(
            evidence.task_id,
            evidence.software_engineer_id,
            evidence.software_engineer_session_id,
            evidence.reviewed_head,
            evidence,
            None,
            evidence.telemetry_event_id,
        )

    def findings_for(
        self, engineer_id: str, engineer_session_id: str
    ) -> tuple[ReviewFinding, ...]:
        self._require_engineer(engineer_id, engineer_session_id)
        if self.review_evidence is None:
            raise ReviewWorkflowError("review evidence was invalidated")
        if self.review_evidence.verdict != "CHANGES_REQUESTED":
            raise ReviewWorkflowError("review has no findings to route")
        return self.review_evidence.findings

    def record_fix(
        self, engineer_id: str, engineer_session_id: str, fixed_head: str
    ) -> ReviewWorkflow:
        self._require_engineer(engineer_id, engineer_session_id)
        if self.review_evidence is None:
            raise ReviewWorkflowError("review evidence was already invalidated")
        if self.review_evidence.verdict != "CHANGES_REQUESTED":
            raise ReviewWorkflowError("approved review cannot enter a fix loop")
        if not GIT_HEAD.fullmatch(fixed_head):
            raise ReviewWorkflowError("engineer fix must bind a full Git object ID")
        if fixed_head == self.current_head:
            raise ReviewWorkflowError("engineer fix must produce a new immutable HEAD")
        reviewer = (
            self.review_evidence.reviewer_id,
            self.review_evidence.reviewer_session_id,
        )
        return replace(
            self,
            current_head=fixed_head,
            review_evidence=None,
            requires_reviewer=reviewer,
        )

    def accept_targeted_rereview(
        self, evidence: ReviewEvidence, telemetry: SpawnTelemetryStore
    ) -> ReviewWorkflow:
        if self.review_evidence is not None or self.requires_reviewer is None:
            raise ReviewWorkflowError("targeted re-review is not required")
        if (evidence.reviewer_id, evidence.reviewer_session_id) != self.requires_reviewer:
            raise ReviewWorkflowError("targeted re-review requires the raising reviewer")
        self._require_evidence_binding(evidence)
        self._require_telemetry(evidence, telemetry)
        return replace(self, review_evidence=evidence, requires_reviewer=None)

    def _require_engineer(self, engineer_id: str, session_id: str) -> None:
        if (
            engineer_id != self.software_engineer_id
            or session_id != self.software_engineer_session_id
        ):
            raise ReviewWorkflowError("findings require the bound engineer")

    def _require_evidence_binding(self, evidence: ReviewEvidence) -> None:
        if evidence.task_id != self.task_id:
            raise ReviewWorkflowError("targeted re-review task mismatch")
        if evidence.reviewed_head != self.current_head:
            raise ReviewWorkflowError("targeted re-review HEAD mismatch")
        if (
            evidence.software_engineer_id != self.software_engineer_id
            or evidence.software_engineer_session_id
            != self.software_engineer_session_id
        ):
            raise ReviewWorkflowError("targeted re-review engineer mismatch")
        if evidence.telemetry_event_id == self.prior_telemetry_event_id:
            raise ReviewWorkflowError("targeted re-review telemetry must be fresh")

    def _require_telemetry(
        self, evidence: ReviewEvidence, telemetry: SpawnTelemetryStore
    ) -> None:
        matches = tuple(
            event for event in telemetry.read_events()
            if event.event_id == evidence.telemetry_event_id
        )
        if len(matches) != 1 or not _telemetry_matches(evidence, matches[0]):
            raise ReviewWorkflowError("targeted re-review telemetry is missing or mismatched")


def _telemetry_matches(evidence: ReviewEvidence, event: SpawnEnvelope) -> bool:
    return (
        event.task_id == evidence.task_id
        and event.run_id == evidence.run_id
        and event.dispatch_id == evidence.dispatch_id
        and event.role == "code_reviewer"
        and event.role_instance_id == evidence.reviewer_id
        and event.session_id == evidence.reviewer_session_id
    )
