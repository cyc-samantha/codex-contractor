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
from scripts.lib.spawn_telemetry import SpawnTelemetryStore, TokenMetric  # noqa: E402
from tests.test_review_evidence import evidence  # noqa: E402


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
    values = {
        "contract": contract(),
        "software_engineer_id": "software_engineer-01",
        "software_engineer_session_id": "session-software_engineer-01",
        "software_engineer_model": "gpt-5.6-terra",
        "target_probe": lambda: target_state,
        "run_id": "run-01",
        "event_id": "review-event-01",
        "retry_cycle_id": "initial",
        "telemetry": SpawnTelemetryStore(tmp_path / "spawn-events.jsonl"),
        "runtime": lambda _contract, _profile, binding: execution(binding),
        "available_profiles": {("gpt-5.6-sol", "medium")},
        "authorized_fallbacks": {},
    }
    values.update(overrides)
    return dispatch_code_review(**values), values["telemetry"]


def test_accepts_fresh_read_only_review_after_correlated_telemetry_is_durable(
    tmp_path: Path,
) -> None:
    result, store = dispatch(tmp_path)

    assert result.evidence.reviewed_head == "b" * 40
    assert store.read_events()[0].role == "code_reviewer"
    assert store.read_events()[0].event_id == "review-event-01"


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"software_engineer_id": "code_reviewer-01"}, "self-review"),
        ({"software_engineer_session_id": "session-code_reviewer-01"}, "self-review"),
        ({"software_engineer_model": "gpt-5.6-sol"}, "distinct model"),
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

    assert store.read_events() == ()
