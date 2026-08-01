"""Security-review ordering, sign-off evidence, and invalidation."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from scripts.lib.risk_routing import (
    HIGH_RISK,
    HIGH_RISK_TRIGGERS,
    DowngradeAuthorization,
    RiskDecision,
    validate_downgrade_authorization,
)
from scripts.lib.security_review_git import (
    change_path_digest,
    collect_git_change_evidence,
    validate_change_evidence,
)
from scripts.lib.security_review_types import (
    ChangeEvidence,
    SecurityReviewApproval,
    SecurityReviewError,
    SENSITIVE_PATH_PREFIXES,
    VERDICTS,
    head as _head,
    identifier as _identifier,
    is_sensitive as _is_sensitive,
    safe_path as _safe_path,
    text_value as _text,
)
from scripts.lib.spawn_telemetry import SpawnEnvelope, SpawnTelemetryStore


@dataclass(frozen=True)
class SecurityReviewState:
    schema_version: int
    task_id: str
    required: bool
    triggers: tuple[str, ...]
    human_elevated: bool
    target_head: str
    preserved_changes: tuple[ChangeEvidence, ...]
    prior_telemetry_event_id: str | None
    prior_reviewer_id: str | None
    prior_reviewer_session_id: str | None
    downgrade: DowngradeAuthorization | None
    approval: SecurityReviewApproval | None

    @classmethod
    def from_risk_decision(
        cls, task_id: str, decision: RiskDecision, target_head: str
    ) -> SecurityReviewState:
        _identifier(task_id, "task_id")
        _head(target_head, "target_head")
        return cls(
            1, task_id, decision.effective_gear == HIGH_RISK,
            decision.triggers, decision.human_elevated, target_head,
            (), None, None, None, decision.downgrade, None,
        )

    @classmethod
    def not_required(cls, task_id: str, target_head: str) -> SecurityReviewState:
        _identifier(task_id, "task_id")
        _head(target_head, "target_head")
        return cls(1, task_id, False, (), False, target_head, (), None, None, None, None, None)

    def record_approval(
        self, approval: SecurityReviewApproval, telemetry: SpawnTelemetryStore
    ) -> SecurityReviewState:
        if not self.required:
            raise SecurityReviewError("security review is not required")
        if not isinstance(telemetry, SpawnTelemetryStore):
            raise SecurityReviewError("security telemetry store has invalid type")
        if self.approval is not None:
            raise SecurityReviewError("security approval already exists")
        _validate_approval(self, approval)
        if approval.reviewed_head != self.target_head:
            raise SecurityReviewError("security approval HEAD mismatch")
        if approval.telemetry_event_id == self.prior_telemetry_event_id:
            raise SecurityReviewError("security review telemetry must be fresh")
        if (
            self.prior_reviewer_id is not None
            and (
                approval.reviewer_id != self.prior_reviewer_id
                or approval.reviewer_session_id != self.prior_reviewer_session_id
            )
        ):
            raise SecurityReviewError("security re-review requires the prior reviewer")
        _require_telemetry(approval, telemetry)
        return replace(self, approval=approval, preserved_changes=())

    def for_change_evidence(
        self, evidence: ChangeEvidence
    ) -> SecurityReviewState:
        validate_change_evidence(evidence)
        if evidence.base_head != self.target_head:
            raise SecurityReviewError("change evidence base HEAD is stale")
        needs_fresh_review = (
            self.approval is not None and self.approval.verdict != "APPROVE"
        )
        if self.required and (
            needs_fresh_review or any(_is_sensitive(path) for path in evidence.changed_paths)
        ):
            prior_event = self.approval.telemetry_event_id if self.approval else self.prior_telemetry_event_id
            prior_reviewer = self.approval.reviewer_id if self.approval else self.prior_reviewer_id
            prior_session = self.approval.reviewer_session_id if self.approval else self.prior_reviewer_session_id
            return replace(
                self, target_head=evidence.new_head, preserved_changes=(),
                approval=None, prior_telemetry_event_id=prior_event,
                prior_reviewer_id=prior_reviewer,
                prior_reviewer_session_id=prior_session,
            )
        prior_event = self.approval.telemetry_event_id if self.approval else self.prior_telemetry_event_id
        prior_reviewer = self.approval.reviewer_id if self.approval else self.prior_reviewer_id
        prior_session = self.approval.reviewer_session_id if self.approval else self.prior_reviewer_session_id
        return replace(
            self, target_head=evidence.new_head,
            preserved_changes=self.preserved_changes + (evidence,),
            prior_telemetry_event_id=prior_event,
            prior_reviewer_id=prior_reviewer,
            prior_reviewer_session_id=prior_session,
        )

    def for_git_change(
        self, repository: Path, new_head: str
    ) -> SecurityReviewState:
        evidence = collect_git_change_evidence(repository, self.target_head, new_head)
        return self.for_change_evidence(evidence)


def require_code_review_approval(
    state: SecurityReviewState,
    target_head: str,
    repository: Path | None = None,
    telemetry: SpawnTelemetryStore | None = None,
) -> None:
    validate_security_review_state(state)
    _head(target_head, "target_head")
    if state.target_head != target_head:
        raise SecurityReviewError("security review target HEAD is stale")
    if not state.required:
        return
    if state.approval is None or state.approval.verdict != "APPROVE":
        raise SecurityReviewError("security review approval is required")
    if not isinstance(telemetry, SpawnTelemetryStore):
        raise SecurityReviewError("security telemetry store is required")
    _require_telemetry(state.approval, telemetry)
    if state.approval.reviewed_head != target_head:
        if not isinstance(repository, Path):
            raise SecurityReviewError("repository probe is required for preserved scope")
        _require_preserved_scope(state, repository)


def _require_preserved_scope(
    state: SecurityReviewState, repository: Path
) -> None:
    cursor = state.approval.reviewed_head if state.approval else ""
    for evidence in state.preserved_changes:
        actual = collect_git_change_evidence(
            repository, evidence.base_head, evidence.new_head
        )
        if (
            evidence.base_head != cursor
            or actual != evidence
            or any(_is_sensitive(path) for path in actual.changed_paths)
        ):
            raise SecurityReviewError("security approval scope is unproven")
        cursor = evidence.new_head
    if cursor != state.target_head:
        raise SecurityReviewError("security approval scope is unproven")


def validate_security_review_state(state: SecurityReviewState) -> None:
    if not isinstance(state, SecurityReviewState):
        raise SecurityReviewError("security review state has invalid type")
    _identifier(state.task_id, "task_id")
    if state.schema_version != 1:
        raise SecurityReviewError("unsupported schema_version")
    _head(state.target_head, "target_head")
    if type(state.required) is not bool or type(state.human_elevated) is not bool:
        raise SecurityReviewError("security review state flags must be boolean")
    if not isinstance(state.triggers, tuple) or not isinstance(state.preserved_changes, tuple):
        raise SecurityReviewError("security review state sequences have invalid type")
    expected_triggers = tuple(
        trigger for trigger in HIGH_RISK_TRIGGERS if trigger in state.triggers
    )
    if state.triggers != expected_triggers:
        raise SecurityReviewError("security triggers are not canonical")
    for evidence in state.preserved_changes:
        validate_change_evidence(evidence)
    if not state.required and (
        state.human_elevated
        or (state.triggers and state.downgrade is None)
        or (state.downgrade is not None and not state.triggers)
    ):
        raise SecurityReviewError("security routing evidence is contradictory")
    if state.required and not (state.triggers or state.human_elevated):
        raise SecurityReviewError("required security state lacks a High Risk reason")
    if state.required and state.downgrade is not None:
        raise SecurityReviewError("required security state cannot contain a downgrade")
    if state.approval is not None and not state.required:
        raise SecurityReviewError("non-required security state has approval")
    if state.downgrade is not None:
        validate_downgrade_authorization(state.downgrade)
    if state.prior_telemetry_event_id is not None:
        _identifier(state.prior_telemetry_event_id, "prior_telemetry_event_id")
    if (state.prior_reviewer_id is None) != (state.prior_reviewer_session_id is None):
        raise SecurityReviewError("prior reviewer identity is incomplete")
    if state.prior_reviewer_id is not None:
        _identifier(state.prior_reviewer_id, "prior_reviewer_id")
        _identifier(state.prior_reviewer_session_id, "prior_reviewer_session_id")
    if state.approval is not None:
        _validate_approval(state, state.approval)
        if state.approval.telemetry_event_id == state.prior_telemetry_event_id:
            if not state.preserved_changes:
                raise SecurityReviewError("security review telemetry must be fresh")
        if (
            state.prior_reviewer_id is not None
            and (
                state.approval.reviewer_id != state.prior_reviewer_id
                or state.approval.reviewer_session_id != state.prior_reviewer_session_id
            )
        ):
            raise SecurityReviewError("security re-review requires the prior reviewer")


def _validate_approval(
    state: SecurityReviewState, approval: SecurityReviewApproval
) -> None:
    if not isinstance(approval, SecurityReviewApproval):
        raise SecurityReviewError("security approval has invalid type")
    _approval_fields(approval)
    if approval.task_id != state.task_id:
        raise SecurityReviewError("security approval task mismatch")


def _require_telemetry(
    approval: SecurityReviewApproval, telemetry: SpawnTelemetryStore
) -> None:
    matches = tuple(
        event for event in telemetry.read_events()
        if _telemetry_matches(approval, event)
    )
    if len(matches) != 1:
        raise SecurityReviewError("security review telemetry is missing or mismatched")


def _telemetry_matches(
    approval: SecurityReviewApproval, event: SpawnEnvelope
) -> bool:
    return (
        event.event_id == approval.telemetry_event_id
        and event.task_id == approval.task_id
        and event.run_id == approval.run_id
        and event.dispatch_id == approval.dispatch_id
        and event.role == "security_reviewer"
        and event.role_instance_id == approval.reviewer_id
        and event.session_id == approval.reviewer_session_id
        and event.actual_model == approval.reviewer_model
    )


def _approval_fields(approval: SecurityReviewApproval) -> None:
    _identifier(approval.task_id, "task_id")
    _identifier(approval.reviewer_id, "reviewer_id")
    _identifier(approval.reviewer_session_id, "reviewer_session_id")
    _text(approval.reviewer_model, "reviewer_model")
    _head(approval.reviewed_head, "reviewed_head")
    _text(approval.verdict, "verdict")
    _identifier(approval.dispatch_id, "dispatch_id")
    _identifier(approval.run_id, "run_id")
    _identifier(approval.telemetry_event_id, "telemetry_event_id")
    if approval.verdict not in VERDICTS:
        raise SecurityReviewError("unsupported security verdict")
