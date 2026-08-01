from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

from scripts.lib.code_review_dispatch import (  # noqa: E402
    CodeReviewDispatchError,
    ReviewExecution,
    dispatch_code_review,
)
from scripts.lib.dispatch_contract import parse_dispatch_contract  # noqa: E402
from scripts.lib.review_evidence import parse_review_evidence  # noqa: E402
from scripts.lib.security_review import SecurityReviewState  # noqa: E402
from scripts.lib.spawn_telemetry import (  # noqa: E402
    SpawnEnvelope,
    SpawnTelemetryStore,
    TokenMetric,
)
from tests.test_review_evidence import evidence  # noqa: E402
from tests.test_security_ordering import approval, security_state  # noqa: E402


def contract(**overrides: object):
    value: dict[str, object] = {
        "schema_version": 1,
        "dispatch_id": "review-dispatch-01",
        "task_id": "t14-t15-review-loop",
        "repository": "/srv/codex-harness",
        "branch": "build/t14-t15-review-loop",
        "worktree": "/srv/codex-harness-wt",
        "base_head": "a" * 40,
        "target_head": "b" * 40,
        "allowed_paths": ["scripts/lib/**", "tests/**"],
        "prohibited_paths": [".env", ".git/**"],
        "acceptance_criteria": ["Fresh review is identity-bound."],
        "required_tests": ["pytest tests"],
        "risk": "Build",
        "role": "code_reviewer",
        "role_instance_id": "code_reviewer-01",
        "session_id": "session-code_reviewer-01",
        "requested_model": "gpt-5.6-sol",
        "requested_reasoning_effort": "medium",
        "write_authority": "none",
        "permissions": {
            "filesystem": "read-only",
            "network": "disabled",
            "tools": "none",
        },
    }
    value.update(overrides)
    return parse_dispatch_contract(value)


def execution(binding, review=None, **overrides: object) -> ReviewExecution:
    values = {
        "binding": binding,
        "evidence": review or parse_review_evidence(evidence()),
        "actual_model": "gpt-5.6-sol",
        "actual_reasoning_effort": "medium",
        "input_tokens": TokenMetric(100, None),
        "cached_input_tokens": TokenMetric(20, None),
        "output_tokens": TokenMetric(30, None),
        "duration_ms": 900,
    }
    values.update(overrides)
    return ReviewExecution(**values)


def dispatch(tmp_path: Path, **overrides: object):
    target_state = overrides.pop("target_state", ("b" * 40, True))
    engineer_model = overrides.pop("software_engineer_actual_model", "gpt-5.6-terra")
    store = overrides.pop(
        "telemetry", SpawnTelemetryStore(tmp_path / "spawn-events.jsonl")
    )
    store.record(
        SpawnEnvelope(
            1, "engineer-event-01", "t14-t15-review-loop", "run-01",
            "engineer-dispatch-01", "software_engineer", "software_engineer-01",
            "session-software_engineer-01", None, engineer_model, engineer_model,
            "high", "high", TokenMetric(100, None), TokenMetric(20, None),
            TokenMetric(30, None), 900, "initial",
        )
    )
    values = {
        "contract": contract(),
        "software_engineer_id": "software_engineer-01",
        "software_engineer_session_id": "session-software_engineer-01",
        "software_engineer_event_id": "engineer-event-01",
        "target_probe": lambda: target_state,
        "run_id": "run-01",
        "event_id": "review-event-01",
        "retry_cycle_id": "initial",
        "telemetry": store,
        "runtime": lambda _contract, _profile, binding: execution(binding),
        "available_profiles": {("gpt-5.6-sol", "medium")},
        "authorized_fallbacks": {},
        "security_review": SecurityReviewState.not_required(
            "t14-t15-review-loop", "b" * 40
        ),
    }
    values.update(overrides)
    return dispatch_code_review(**values), values["telemetry"]


def test_accepts_fresh_read_only_review_after_correlated_telemetry_is_durable(
    tmp_path: Path,
) -> None:
    result, store = dispatch(tmp_path)

    assert result.evidence.reviewed_head == "b" * 40
    assert store.read_events()[-1].role == "code_reviewer"
    assert store.read_events()[-1].event_id == "review-event-01"


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"software_engineer_id": "code_reviewer-01"}, "self-review"),
        ({"software_engineer_session_id": "session-code_reviewer-01"}, "self-review"),
        ({"software_engineer_actual_model": "gpt-5.6-sol"}, "distinct model"),
        ({"software_engineer_event_id": "missing-event"}, "Engineer telemetry"),
        ({"target_state": ("b" * 40, False)}, "clean"),
        ({"target_state": ("c" * 40, True)}, "target HEAD"),
    ],
)
def test_rejects_self_review_dirty_or_stale_targets(
    tmp_path: Path, override: dict[str, object], message: str
) -> None:
    invoked = False

    def runtime(*_args):
        nonlocal invoked
        invoked = True

    with pytest.raises(CodeReviewDispatchError, match=message):
        dispatch(tmp_path, runtime=runtime, **override)

    assert invoked is False


def test_rejects_result_until_correlated_telemetry_and_evidence_match(
    tmp_path: Path,
) -> None:
    substituted = parse_review_evidence(evidence(telemetry_event_id="other-event"))

    with pytest.raises(CodeReviewDispatchError, match="evidence binding"):
        dispatch(
            tmp_path,
            runtime=lambda _contract, _profile, binding: execution(
                binding, substituted
            ),
        )


def test_rejects_post_review_repository_mutation_before_telemetry(
    tmp_path: Path,
) -> None:
    states = iter((("b" * 40, True), ("c" * 40, False)))
    store = SpawnTelemetryStore(tmp_path / "spawn-events.jsonl")

    with pytest.raises(CodeReviewDispatchError, match="changed during review"):
        dispatch(tmp_path, target_probe=lambda: next(states), telemetry=store)

    assert tuple(event.role for event in store.read_events()) == ("software_engineer",)


def test_security_sign_off_is_required_before_code_review_dispatch(
    tmp_path: Path,
) -> None:
    with pytest.raises(CodeReviewDispatchError, match="approval"):
        dispatch(
            tmp_path,
            contract=contract(risk="High Risk"),
            security_review=security_state(task_id="t14-t15-review-loop"),
        )

    store = SpawnTelemetryStore(tmp_path / "approved-events.jsonl")
    approved = security_state(task_id="t14-t15-review-loop").record_approval(
        approval(task_id="t14-t15-review-loop"),
        telemetry(store, task_id="t14-t15-review-loop"),
    )
    result, _ = dispatch(
        tmp_path,
        contract=contract(risk="High Risk"),
        telemetry=store,
        security_review=approved,
    )

    assert result.evidence.verdict == "CHANGES_REQUESTED"


def test_code_review_dispatch_rejects_missing_security_state(tmp_path: Path) -> None:
    with pytest.raises(CodeReviewDispatchError, match="security review state"):
        dispatch(tmp_path, security_review=None)


def test_high_risk_dispatch_rejects_non_required_security_state(tmp_path: Path) -> None:
    with pytest.raises(CodeReviewDispatchError, match="risk"):
        dispatch(
            tmp_path,
            contract=contract(risk="High Risk"),
            security_review=SecurityReviewState.not_required(
                "t14-t15-review-loop", "b" * 40
            ),
        )


def test_code_review_dispatch_rejects_security_approval_from_another_run(
    tmp_path: Path,
) -> None:
    store = SpawnTelemetryStore(tmp_path / "security-events.jsonl")
    approved = security_state(task_id="t14-t15-review-loop").record_approval(
        approval(task_id="t14-t15-review-loop", run_id="run-other"),
        telemetry(store, task_id="t14-t15-review-loop", run_id="run-other"),
    )

    with pytest.raises(CodeReviewDispatchError, match="run"):
        dispatch(
            tmp_path,
            contract=contract(risk="High Risk"),
            telemetry=store,
            security_review=approved,
        )


def telemetry(
    store: SpawnTelemetryStore,
    task_id: str = "t17-security-signoff",
    run_id: str = "run-01",
) -> SpawnTelemetryStore:
    store.record(
        SpawnEnvelope(
            1, "security-event-01", task_id, run_id,
            "security-dispatch-01", "security_reviewer", "security_reviewer-01",
            "session-security_reviewer-01", None, "gpt-5.6-sol", "gpt-5.6-sol",
            "medium", "medium", TokenMetric(10, None), TokenMetric(0, None),
            TokenMetric(5, None), 100, "initial",
        )
    )
    return store
