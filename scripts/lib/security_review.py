"""Security-review ordering, sign-off evidence, and invalidation."""

from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path, PurePosixPath
import re
import subprocess

from scripts.lib.risk_routing import (
    HIGH_RISK,
    HIGH_RISK_TRIGGERS,
    DowngradeAuthorization,
    RiskDecision,
    validate_downgrade_authorization,
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
    "scripts/lib/execution_policy.py",
    "scripts/lib/review_evidence.py",
    "scripts/lib/review_workflow.py",
    "scripts/lib/risk_routing.py",
    "scripts/lib/security_review.py",
    "scripts/lib/security_review_evidence.py",
    "scripts/lib/software_engineer_dispatch.py",
    "scripts/lib/spawn_telemetry.py",
)


@dataclass(frozen=True)
class ChangeEvidence:
    base_head: str
    new_head: str
    changed_paths: tuple[str, ...]
    path_digest: str


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
    preserved_changes: tuple[ChangeEvidence, ...]
    prior_telemetry_event_id: str | None
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
            (), None, decision.downgrade, None,
        )

    @classmethod
    def not_required(cls, task_id: str, target_head: str) -> SecurityReviewState:
        _identifier(task_id, "task_id")
        _head(target_head, "target_head")
        return cls(1, task_id, False, (), False, target_head, (), None, None, None)

    def record_approval(
        self, approval: SecurityReviewApproval, telemetry: SpawnTelemetryStore
    ) -> SecurityReviewState:
        if not self.required:
            raise SecurityReviewError("security review is not required")
        if not isinstance(telemetry, SpawnTelemetryStore):
            raise SecurityReviewError("security telemetry store has invalid type")
        _validate_approval(self, approval)
        if approval.reviewed_head != self.target_head:
            raise SecurityReviewError("security approval HEAD mismatch")
        if approval.telemetry_event_id == self.prior_telemetry_event_id:
            raise SecurityReviewError("security review telemetry must be fresh")
        _require_telemetry(approval, telemetry)
        return replace(self, approval=approval, preserved_changes=())

    def for_change_evidence(
        self, evidence: ChangeEvidence
    ) -> SecurityReviewState:
        validate_change_evidence(evidence)
        if evidence.base_head != self.target_head:
            raise SecurityReviewError("change evidence base HEAD is stale")
        if self.required and any(_is_sensitive(path) for path in evidence.changed_paths):
            prior_event = self.approval.telemetry_event_id if self.approval else self.prior_telemetry_event_id
            return replace(
                self, target_head=evidence.new_head, preserved_changes=(),
                approval=None, prior_telemetry_event_id=prior_event,
            )
        prior_event = self.approval.telemetry_event_id if self.approval else self.prior_telemetry_event_id
        return replace(
            self, target_head=evidence.new_head,
            preserved_changes=self.preserved_changes + (evidence,),
            prior_telemetry_event_id=prior_event,
        )

    def for_git_change(
        self, repository: Path, new_head: str
    ) -> SecurityReviewState:
        evidence = collect_git_change_evidence(repository, self.target_head, new_head)
        return self.for_change_evidence(evidence)


def collect_git_change_evidence(
    repository: Path, base_head: str, new_head: str
) -> ChangeEvidence:
    _repository(repository)
    _head(base_head, "base_head")
    _head(new_head, "new_head")
    if base_head == new_head:
        raise SecurityReviewError("change evidence requires a new HEAD")
    try:
        result = subprocess.run(
            ["git", "-C", str(repository), "diff", "--name-only", "--no-renames", "--no-ext-diff", f"{base_head}..{new_head}"],
            check=False, capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SecurityReviewError("Git change probe failed") from error
    if result.returncode != 0:
        raise SecurityReviewError("Git change probe returned an error")
    paths = tuple(sorted(result.stdout.splitlines()))
    evidence = ChangeEvidence(base_head, new_head, paths, change_path_digest(paths))
    validate_change_evidence(evidence)
    return evidence


def change_path_digest(paths: tuple[str, ...]) -> str:
    return sha256("\n".join(paths).encode("utf-8")).hexdigest()


def validate_change_evidence(evidence: ChangeEvidence) -> None:
    if not isinstance(evidence, ChangeEvidence):
        raise SecurityReviewError("change evidence has invalid type")
    _head(evidence.base_head, "base_head")
    _head(evidence.new_head, "new_head")
    if evidence.base_head == evidence.new_head or not evidence.changed_paths:
        raise SecurityReviewError("change evidence is empty or unchanged")
    paths = tuple(_safe_path(path) for path in evidence.changed_paths)
    if paths != tuple(sorted(set(paths))):
        raise SecurityReviewError("change evidence paths are not canonical")
    if evidence.path_digest != change_path_digest(paths):
        raise SecurityReviewError("change evidence digest mismatch")


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
        actual = collect_git_change_evidence(
            repository, state.approval.reviewed_head, target_head
        )
        if any(_is_sensitive(path) for path in actual.changed_paths):
            raise SecurityReviewError("sensitive changes require fresh security review")
        _require_preserved_scope(state, actual)


def _require_preserved_scope(
    state: SecurityReviewState, actual: ChangeEvidence
) -> None:
    cursor = state.approval.reviewed_head if state.approval else ""
    for evidence in state.preserved_changes:
        validate_change_evidence(evidence)
        if evidence.base_head != cursor or any(_is_sensitive(path) for path in evidence.changed_paths):
            raise SecurityReviewError("security approval scope is unproven")
        cursor = evidence.new_head
    if cursor != state.target_head:
        raise SecurityReviewError("security approval scope is unproven")
    expected_paths = tuple(
        sorted(path for evidence in state.preserved_changes for path in evidence.changed_paths)
    )
    if expected_paths != actual.changed_paths:
        raise SecurityReviewError("security approval scope is unproven")


def validate_security_review_state(state: SecurityReviewState) -> None:
    if not isinstance(state, SecurityReviewState):
        raise SecurityReviewError("security review state has invalid type")
    _identifier(state.task_id, "task_id")
    _head(state.target_head, "target_head")
    if type(state.required) is not bool or type(state.human_elevated) is not bool:
        raise SecurityReviewError("security review state flags must be boolean")
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
    if state.downgrade is not None:
        validate_downgrade_authorization(state.downgrade)
    if state.prior_telemetry_event_id is not None:
        _identifier(state.prior_telemetry_event_id, "prior_telemetry_event_id")
    if state.approval is not None:
        _validate_approval(state, state.approval)
        if state.approval.telemetry_event_id == state.prior_telemetry_event_id:
            if not state.preserved_changes:
                raise SecurityReviewError("security review telemetry must be fresh")


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


def _safe_path(value: object) -> str:
    text = _text(value, "changed path")
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts or path == PurePosixPath("."):
        raise SecurityReviewError("changed path must be repository-relative")
    return str(path)


def _is_sensitive(path: str) -> bool:
    return any(
        path == prefix.rstrip("/") or path.startswith(prefix.rstrip("/") + "/")
        for prefix in SENSITIVE_PATH_PREFIXES
    )


def _repository(value: object) -> None:
    if not isinstance(value, Path) or not value.is_absolute() or ".." in value.parts:
        raise SecurityReviewError("repository must be an absolute path")


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
