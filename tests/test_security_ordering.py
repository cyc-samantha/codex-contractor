from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

from scripts.lib.risk_routing import (  # noqa: E402
    HIGH_RISK_TRIGGERS,
    DowngradeAuthorization,
    route_risk,
)
from scripts.lib.security_review import (  # noqa: E402
    ChangeEvidence,
    SecurityReviewApproval,
    SecurityReviewError,
    SecurityReviewState,
    SENSITIVE_PATH_PREFIXES,
    change_path_digest,
    require_code_review_approval,
    validate_change_evidence,
)
from scripts.lib.security_review_evidence import (  # noqa: E402
    parse_security_review_state,
    serialize_security_review_state,
)
from scripts.lib.spawn_telemetry import (  # noqa: E402
    SpawnEnvelope,
    SpawnTelemetryStore,
    TokenMetric,
)


def signals(**overrides: bool) -> dict[str, bool]:
    values = {trigger: False for trigger in HIGH_RISK_TRIGGERS}
    values.update(overrides)
    return values


def security_state(
    required: bool = True, task_id: str = "t17-security-signoff"
) -> SecurityReviewState:
    decision = route_risk(
        "Build",
        signals(**{HIGH_RISK_TRIGGERS[0]: required}),
    )
    return SecurityReviewState.from_risk_decision(task_id, decision, "b" * 40)


def approval(**overrides: object) -> SecurityReviewApproval:
    values: dict[str, object] = {
        "task_id": "t17-security-signoff",
        "reviewer_id": "security_reviewer-01",
        "reviewer_session_id": "session-security_reviewer-01",
        "reviewer_model": "gpt-5.6-sol",
        "reviewed_head": "b" * 40,
        "verdict": "APPROVE",
        "dispatch_id": "security-dispatch-01",
        "run_id": "run-01",
        "telemetry_event_id": "security-event-01",
    }
    values.update(overrides)
    return SecurityReviewApproval(**values)


def change(base_head: str, new_head: str, *paths: str) -> ChangeEvidence:
    normalized = tuple(sorted(paths))
    return ChangeEvidence(base_head, new_head, normalized, change_path_digest(normalized))


def telemetry(tmp_path: Path, **overrides: object) -> SpawnTelemetryStore:
    values: dict[str, object] = {
        "event_id": "security-event-01",
        "task_id": "t17-security-signoff",
        "run_id": "run-01",
        "dispatch_id": "security-dispatch-01",
        "role": "security_reviewer",
        "role_instance_id": "security_reviewer-01",
        "session_id": "session-security_reviewer-01",
        "actual_model": "gpt-5.6-sol",
    }
    values.update(overrides)
    store = SpawnTelemetryStore(tmp_path / "spawn-events.jsonl")
    store.record(
        SpawnEnvelope(
            1,
            values["event_id"],
            values["task_id"],
            values["run_id"],
            values["dispatch_id"],
            values["role"],
            values["role_instance_id"],
            values["session_id"],
            None,
            "gpt-5.6-sol",
            values["actual_model"],
            "medium",
            "medium",
            TokenMetric(10, None),
            TokenMetric(0, None),
            TokenMetric(5, None),
            100,
            "initial",
        )
    )
    return store


def test_security_evidence_round_trips_required_fields(tmp_path: Path) -> None:
    state = security_state().record_approval(approval(), telemetry(tmp_path))

    parsed = parse_security_review_state(serialize_security_review_state(state))

    assert parsed.required is True
    assert parsed.triggers == (HIGH_RISK_TRIGGERS[0],)
    assert parsed.approval is not None
    assert parsed.approval.reviewer_id == "security_reviewer-01"
    assert parsed.approval.reviewed_head == "b" * 40
    assert parsed.approval.verdict == "APPROVE"


@pytest.mark.parametrize(
    "override",
    [
        {"required": "yes"},
        {"triggers": ["unknown-trigger"]},
        {"approval": {"task_id": "other-task"}},
    ],
)
def test_security_evidence_rejects_missing_or_contradictory_fields(
    override: dict[str, object],
) -> None:
    value = serialize_security_review_state(security_state())
    value.update(override)

    with pytest.raises(SecurityReviewError):
        parse_security_review_state(value)


def test_required_security_approval_precedes_code_review(tmp_path: Path) -> None:
    state = security_state()

    with pytest.raises(SecurityReviewError, match="approval"):
        require_code_review_approval(state, "b" * 40)

    store = telemetry(tmp_path)
    approved = state.record_approval(approval(), store)
    require_code_review_approval(approved, "b" * 40, telemetry=store)


def test_non_security_review_does_not_require_security_approval() -> None:
    require_code_review_approval(security_state(required=False), "b" * 40)


def test_non_required_state_cannot_record_security_approval(tmp_path: Path) -> None:
    with pytest.raises(SecurityReviewError, match="not required"):
        security_state(required=False).record_approval(
            approval(), telemetry(tmp_path)
        )


def test_changes_requested_security_review_does_not_unlock_code_review(
    tmp_path: Path,
) -> None:
    rejected = security_state().record_approval(
        approval(verdict="CHANGES_REQUESTED"), telemetry(tmp_path)
    )

    with pytest.raises(SecurityReviewError, match="approval"):
        require_code_review_approval(rejected, "b" * 40)


def test_mismatched_security_telemetry_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(SecurityReviewError, match="telemetry"):
        security_state().record_approval(
            approval(), telemetry(tmp_path, role="code_reviewer")
        )


def test_sensitive_fix_invalidates_security_sign_off(tmp_path: Path) -> None:
    state = security_state().record_approval(approval(), telemetry(tmp_path))

    invalidated = state.for_change_evidence(
        change("b" * 40, "c" * 40, "scripts/lib/review_workflow.py")
    )

    assert invalidated.target_head == "c" * 40
    assert invalidated.approval is None
    with pytest.raises(SecurityReviewError, match="approval"):
        require_code_review_approval(invalidated, "c" * 40)


def test_non_sensitive_fix_preserves_security_sign_off(tmp_path: Path) -> None:
    store = telemetry(tmp_path)
    state = security_state().record_approval(approval(), store)

    updated = state.for_change_evidence(change("b" * 40, "c" * 40, "README.md"))

    assert updated.approval == state.approval
    with pytest.raises(SecurityReviewError, match="repository probe"):
        require_code_review_approval(updated, "c" * 40, telemetry=store)


def test_serialized_state_rejects_unproven_approval_scope(tmp_path: Path) -> None:
    approved = security_state().record_approval(approval(), telemetry(tmp_path))
    value = serialize_security_review_state(approved)
    value["target_head"] = "c" * 40

    parsed = parse_security_review_state(value)

    with pytest.raises(SecurityReviewError, match="probe|scope"):
        require_code_review_approval(
            parsed,
            "c" * 40,
            repository=tmp_path,
            telemetry=telemetry(tmp_path / "check"),
        )


def test_change_evidence_rejects_tampered_digest_and_traversal() -> None:
    with pytest.raises(SecurityReviewError, match="digest"):
        validate_change_evidence(
            ChangeEvidence("b" * 40, "c" * 40, ("README.md",), "0" * 64)
        )
    with pytest.raises(SecurityReviewError, match="repository-relative"):
        validate_change_evidence(
            change("b" * 40, "c" * 40, "../scripts/lib/risk_routing.py")
        )


def test_security_dispatch_requires_matching_durable_telemetry(tmp_path: Path) -> None:
    state = security_state()

    with pytest.raises(SecurityReviewError, match="telemetry"):
        state.record_approval(approval(), SpawnTelemetryStore(tmp_path / "missing.jsonl"))


def test_sensitive_invalidation_requires_fresh_security_telemetry(
    tmp_path: Path,
) -> None:
    approved = security_state().record_approval(approval(), telemetry(tmp_path))
    invalidated = approved.for_change_evidence(
        change("b" * 40, "c" * 40, "scripts/lib/review_workflow.py")
    )

    with pytest.raises(SecurityReviewError, match="fresh"):
        invalidated.record_approval(
            approval(reviewed_head="c" * 40), telemetry(tmp_path / "stale")
        )

    fresh_store = telemetry(
        tmp_path / "fresh",
        event_id="security-event-02",
        dispatch_id="security-dispatch-02",
    )
    fresh = invalidated.record_approval(
        approval(
            reviewed_head="c" * 40,
            dispatch_id="security-dispatch-02",
            telemetry_event_id="security-event-02",
        ),
        fresh_store,
    )
    assert fresh.approval is not None


def test_downgrade_evidence_round_trips_durably() -> None:
    authorization = DowngradeAuthorization(
        "human", "Build", "approved exception", "auth-17"
    )
    decision = route_risk(
        "Build",
        signals(**{HIGH_RISK_TRIGGERS[0]: True}),
        downgrade=authorization,
    )
    state = SecurityReviewState.from_risk_decision(
        "t17-security-signoff", decision, "b" * 40
    )

    parsed = parse_security_review_state(serialize_security_review_state(state))

    assert parsed.required is False
    assert parsed.triggers == (HIGH_RISK_TRIGGERS[0],)
    assert parsed.downgrade == authorization


@pytest.mark.parametrize("prefix", SENSITIVE_PATH_PREFIXES)
def test_security_control_paths_invalidate_sign_off(
    tmp_path: Path, prefix: str
) -> None:
    approved = security_state().record_approval(approval(), telemetry(tmp_path))
    path = prefix.rstrip("/") + "/changed.py"

    invalidated = approved.for_change_evidence(change("b" * 40, "c" * 40, path))

    assert invalidated.approval is None


def test_security_requirement_preserves_downgrade_record() -> None:
    authorization = DowngradeAuthorization(
        "human", "Build", "approved exception", "auth-17"
    )
    decision = route_risk(
        "Build",
        signals(**{HIGH_RISK_TRIGGERS[0]: True}),
        downgrade=authorization,
    )

    assert SecurityReviewState.from_risk_decision(
        "t17-security-signoff", decision, "b" * 40
    ).downgrade == authorization
