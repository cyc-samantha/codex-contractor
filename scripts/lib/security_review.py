"""Security-review ordering, sign-off evidence, and invalidation."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import PurePosixPath
import re
from scripts.lib.risk_routing import (
    HIGH_RISK,
    DowngradeAuthorization,
    RiskDecision,
)
from scripts.lib.spawn_telemetry import SpawnEnvelope, SpawnTelemetryStore


class SecurityReviewError(ValueError):
    """Raised when security sign-off cannot be trusted or applied."""


GIT_HEAD = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
VERDICTS = frozenset({"APPROVE", "CHANGES_REQUESTED"})
SENSITIVE_PATH_PREFIXES = (
    ".codex/hooks/",
    "scripts/codex-harness",
    "scripts/lib/code_review_dispatch.py",
    "scripts/lib/dispatch_contract.py",
    "scripts/lib/review_evidence.py",
    "scripts/lib/review_workflow.py",
    "scripts/lib/risk_routing.py",
    "scripts/lib/security_review.py",
    "scripts/lib/spawn_telemetry.py",
)


@dataclass(frozen=True)
class SecurityReviewApproval:
    task_id: str
    reviewer_id: str
    reviewer_session_id: str
    reviewer_model: str
    reviewed_head: str
    verdict: str
    dispatch_id: str
    run_id: str
    telemetry_event_id: str


@dataclass(frozen=True)
class SecurityReviewState:
    schema_version: int
    task_id: str
    required: bool
    triggers: tuple[str, ...]
    human_elevated: bool
    target_head: str
    non_sensitive_paths: tuple[str, ...]
    downgrade: DowngradeAuthorization | None
    approval: SecurityReviewApproval | None

    @classmethod
    def from_risk_decision(
        cls, task_id: str, decision: RiskDecision, target_head: str
    ) -> SecurityReviewState:
        _identifier(task_id, "task_id")
        _head(target_head, "target_head")
        return cls(
            1,
            task_id,
            decision.effective_gear == HIGH_RISK,
            decision.triggers,
            decision.human_elevated,
            target_head,
            (),
            decision.downgrade,
            None,
        )

    def record_approval(
        self, approval: SecurityReviewApproval, telemetry: SpawnTelemetryStore
    ) -> SecurityReviewState:
        if not self.required:
            raise SecurityReviewError("security review is not required")
        if not isinstance(telemetry, SpawnTelemetryStore):
            raise SecurityReviewError("security telemetry store has invalid type")
        _validate_approval(self, approval)
        _require_telemetry(approval, telemetry)
        return replace(self, approval=approval, non_sensitive_paths=())

    def for_changed_paths(
        self, changed_paths: list[str] | tuple[str, ...], new_head: str
    ) -> SecurityReviewState:
        _head(new_head, "new_head")
        if not isinstance(changed_paths, (list, tuple)):
            raise SecurityReviewError("changed paths must be a list or tuple")
        normalized = tuple(_safe_path(path) for path in changed_paths)
        if not normalized:
            raise SecurityReviewError("changed paths cannot be empty")
        if self.required and any(_is_sensitive(path) for path in normalized):
            return replace(
                self, target_head=new_head, non_sensitive_paths=(), approval=None
            )
        return replace(
            self,
            target_head=new_head,
            non_sensitive_paths=self.non_sensitive_paths + normalized,
        )


def require_code_review_approval(
    state: SecurityReviewState, target_head: str
) -> None:
    _head(target_head, "target_head")
    if not state.required:
        return
    if state.target_head != target_head:
        raise SecurityReviewError("security review target HEAD is stale")
    if state.approval is None or state.approval.verdict != "APPROVE":
        raise SecurityReviewError("security review approval is required")
    if (
        state.approval.reviewed_head != target_head
        and not state.non_sensitive_paths
    ):
        raise SecurityReviewError("security review approval scope is unproven")


def _validate_approval(
    state: SecurityReviewState, approval: SecurityReviewApproval
) -> None:
    if not isinstance(approval, SecurityReviewApproval):
        raise SecurityReviewError("security approval has invalid type")
    _approval_fields(approval)
    if approval.task_id != state.task_id:
        raise SecurityReviewError("security approval task mismatch")
    if approval.reviewed_head != state.target_head:
        raise SecurityReviewError("security approval HEAD mismatch")
    if approval.verdict not in VERDICTS:
        raise SecurityReviewError("unsupported security verdict")


def _require_telemetry(
    approval: SecurityReviewApproval, telemetry: SpawnTelemetryStore
) -> None:
    if not isinstance(telemetry, SpawnTelemetryStore):
        raise SecurityReviewError("security telemetry store has invalid type")
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


def _safe_path(value: object) -> str:
    text = _text(value, "changed path")
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts or path == PurePosixPath("."):
        raise SecurityReviewError("changed path must be repository-relative")
    return str(path)


def _is_sensitive(path: str) -> bool:
    return any(
        path == prefix.rstrip("/") or path.startswith(prefix)
        for prefix in SENSITIVE_PATH_PREFIXES
    )


def _head(value: object, name: str) -> str:
    text = _text(value, name)
    if not GIT_HEAD.fullmatch(text):
        raise SecurityReviewError(f"{name} must be a full Git object ID")
    return text


def _identifier(value: object, name: str) -> str:
    text = _text(value, name)
    if not IDENTIFIER.fullmatch(text):
        raise SecurityReviewError(f"{name} must be a stable identifier")
    return text


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise SecurityReviewError(f"{name} must be normalized text")
    if any(ord(character) < 32 for character in value):
        raise SecurityReviewError(f"{name} contains control characters")
    return value
