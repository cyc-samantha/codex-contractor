"""Parse and serialize immutable security-review evidence."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from scripts.lib.risk_routing import (
    DowngradeAuthorization,
    HIGH_RISK_TRIGGERS,
    validate_downgrade_authorization,
)
from scripts.lib.security_review import (
    SecurityReviewApproval,
    SecurityReviewError,
    SecurityReviewState,
    _approval_fields,
    _head,
    _identifier,
    _is_sensitive,
    _safe_path,
    _text,
)


STATE_FIELDS = frozenset(
    {
        "schema_version", "task_id", "required", "triggers", "human_elevated",
        "target_head", "non_sensitive_paths", "downgrade", "approval",
    }
)
APPROVAL_FIELDS = frozenset(
    {
        "task_id", "reviewer_id", "reviewer_session_id", "reviewer_model",
        "reviewed_head", "verdict", "dispatch_id", "run_id",
        "telemetry_event_id",
    }
)


def serialize_security_review_state(
    state: SecurityReviewState,
) -> dict[str, Any]:
    value = asdict(state)
    value["triggers"] = list(state.triggers)
    value["non_sensitive_paths"] = list(state.non_sensitive_paths)
    if state.downgrade is not None:
        value["downgrade"] = asdict(state.downgrade)
    if state.approval is not None:
        value["approval"] = asdict(state.approval)
    return value


def parse_security_review_state(value: object) -> SecurityReviewState:
    fields = _mapping(value, "security review state")
    _exact_fields(fields, STATE_FIELDS, "security review state")
    if fields["schema_version"] != 1:
        raise SecurityReviewError("unsupported schema_version")
    task_id = _identifier(fields["task_id"], "task_id")
    required = _boolean(fields["required"], "required")
    human_elevated = _boolean(fields["human_elevated"], "human_elevated")
    triggers = _triggers(fields["triggers"])
    target_head = _head(fields["target_head"], "target_head")
    non_sensitive_paths = _paths(fields["non_sensitive_paths"])
    downgrade = _downgrade(fields["downgrade"])
    approval = _approval(fields["approval"])
    _validate_state(
        task_id, required, triggers, human_elevated, non_sensitive_paths,
        downgrade, approval,
    )
    return SecurityReviewState(
        1, task_id, required, triggers, human_elevated,
        target_head, non_sensitive_paths, downgrade, approval,
    )


def _validate_state(
    task_id: str,
    required: bool,
    triggers: tuple[str, ...],
    human_elevated: bool,
    non_sensitive_paths: tuple[str, ...],
    downgrade: DowngradeAuthorization | None,
    approval: SecurityReviewApproval | None,
) -> None:
    if any(_is_sensitive(path) for path in non_sensitive_paths):
        raise SecurityReviewError("security preservation path is sensitive")
    if not required and (
        triggers or human_elevated or non_sensitive_paths or downgrade or approval
    ):
        raise SecurityReviewError("non-required security state has risk evidence")
    if approval is not None and approval.task_id != task_id:
        raise SecurityReviewError("security approval task mismatch")
    if approval is not None and not required:
        raise SecurityReviewError("non-required security state has approval")


def _approval(value: object) -> SecurityReviewApproval | None:
    if value is None:
        return None
    fields = _mapping(value, "security approval")
    _exact_fields(fields, APPROVAL_FIELDS, "security approval")
    approval = SecurityReviewApproval(
        _identifier(fields["task_id"], "task_id"),
        _identifier(fields["reviewer_id"], "reviewer_id"),
        _identifier(fields["reviewer_session_id"], "reviewer_session_id"),
        _text(fields["reviewer_model"], "reviewer_model"),
        _head(fields["reviewed_head"], "reviewed_head"),
        _text(fields["verdict"], "verdict"),
        _identifier(fields["dispatch_id"], "dispatch_id"),
        _identifier(fields["run_id"], "run_id"),
        _identifier(fields["telemetry_event_id"], "telemetry_event_id"),
    )
    _approval_fields(approval)
    return approval


def _downgrade(value: object) -> DowngradeAuthorization | None:
    if value is None:
        return None
    fields = _mapping(value, "downgrade")
    expected = frozenset({"authorized_by", "target_gear", "rationale", "authorization_id"})
    _exact_fields(fields, expected, "downgrade")
    try:
        authorization = DowngradeAuthorization(**fields)
        return validate_downgrade_authorization(authorization)
    except (TypeError, ValueError) as error:
        raise SecurityReviewError(f"invalid downgrade authorization: {error}") from error


def _triggers(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise SecurityReviewError("triggers must be a list")
    if any(trigger not in HIGH_RISK_TRIGGERS for trigger in value):
        raise SecurityReviewError("unknown security trigger")
    if len(value) != len(set(value)):
        raise SecurityReviewError("security triggers must be unique")
    ordered = tuple(trigger for trigger in HIGH_RISK_TRIGGERS if trigger in value)
    if tuple(value) != ordered:
        raise SecurityReviewError("security triggers must use catalog order")
    return ordered


def _paths(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise SecurityReviewError("non_sensitive_paths must be a list")
    paths = tuple(_safe_path(path) for path in value)
    if len(paths) != len(set(paths)):
        raise SecurityReviewError("non_sensitive_paths must be unique")
    return paths


def _boolean(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise SecurityReviewError(f"{name} must be boolean")
    return value


def _mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise SecurityReviewError(f"{name} must be an object")
    return value


def _exact_fields(
    fields: dict[str, Any], expected: frozenset[str], name: str
) -> None:
    missing = expected - fields.keys()
    unknown = fields.keys() - expected
    if missing:
        raise SecurityReviewError(f"missing required field: {min(missing)}")
    if unknown:
        raise SecurityReviewError(f"unknown field in {name}: {min(unknown)}")
