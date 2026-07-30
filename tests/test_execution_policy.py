from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

from scripts.lib.execution_policy import (  # noqa: E402
    ExecutionPolicyError,
    resolve_execution_profile,
)


@pytest.mark.parametrize(
    ("role", "gear", "work_type", "model", "effort"),
    [
        ("software_engineer", "Small Change", "simple", "gpt-5.6-Luna", "medium"),
        ("software_engineer", "Build", "general", "gpt-5.6-terra", "high"),
        ("software_engineer", "Build", "complex", "gpt-5.6-sol", "high"),
        ("code_reviewer", "Build", "complex", "gpt-5.6-sol", "medium"),
        ("orchestrator", "Build", "complex", "gpt-5.6-sol", "medium"),
        ("architect", "Build", "system_design", "gpt-5.6-sol", "high"),
        ("verifier", "Build", "mechanical", "gpt-5.6-terra", "low"),
    ],
)
def test_resolves_documented_role_and_gear_profiles(
    role: str, gear: str, work_type: str, model: str, effort: str
) -> None:
    profile = resolve_execution_profile(
        role, gear, work_type, {(model, effort)}, {}
    )

    assert profile.requested_model == model
    assert profile.requested_reasoning_effort == effort
    assert profile.actual_model == model
    assert profile.actual_reasoning_effort == effort
    assert profile.fallback_reason is None


def test_rejects_unavailable_or_unapproved_fallback() -> None:
    with pytest.raises(ExecutionPolicyError, match="no approved available profile"):
        resolve_execution_profile(
            "software_engineer",
            "Build",
            "general",
            {("gpt-5.6-Luna", "medium")},
            {},
        )


def test_allows_only_pre_authorized_fallback() -> None:
    fallback = {("gpt-5.6-terra", "high"): ("gpt-5.6-sol", "high")}

    profile = resolve_execution_profile(
        "software_engineer",
        "Build",
        "general",
        {("gpt-5.6-sol", "high")},
        fallback,
    )

    assert profile.requested_model == "gpt-5.6-terra"
    assert profile.actual_model == "gpt-5.6-sol"
    assert profile.fallback_reason == "pre-authorized profile fallback"


def test_rejects_pre_authorized_effort_downgrade() -> None:
    fallback = {("gpt-5.6-sol", "high"): ("gpt-5.6-Luna", "medium")}

    with pytest.raises(ExecutionPolicyError, match="minimum effort"):
        resolve_execution_profile(
            "software_engineer",
            "Build",
            "complex",
            {("gpt-5.6-Luna", "medium")},
            fallback,
        )
