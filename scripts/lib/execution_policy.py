"""Resolve versioned execution profiles without implicit fallback."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


class ExecutionPolicyError(ValueError):
    """Raised when no approved execution profile can be resolved."""


ProfileKey = tuple[str, str]


@dataclass(frozen=True)
class ExecutionProfile:
    policy_version: int
    requested_model: str
    requested_reasoning_effort: str
    actual_model: str
    actual_reasoning_effort: str
    fallback_reason: str | None


def resolve_execution_profile(
    role: str,
    gear: str,
    work_type: str,
    available_profiles: set[ProfileKey],
    authorized_fallbacks: Mapping[ProfileKey, ProfileKey],
) -> ExecutionProfile:
    requested = _requested_profile(role, gear, work_type)
    if requested in available_profiles:
        return _profile(requested, requested, None)
    fallback = authorized_fallbacks.get(requested)
    if fallback is None or fallback not in available_profiles:
        raise ExecutionPolicyError("no approved available profile")
    return _profile(requested, fallback, "pre-authorized profile fallback")


def _requested_profile(role: str, gear: str, work_type: str) -> ProfileKey:
    model = _model_for(work_type)
    effort = _effort_for(role, gear)
    return model, effort


def _model_for(work_type: str) -> str:
    models = {
        "simple": "gpt-5.6-Luna",
        "general": "gpt-5.6-terra",
        "mechanical": "gpt-5.6-terra",
        "complex": "gpt-5.6-sol",
        "system_design": "gpt-5.6-sol",
    }
    try:
        return models[work_type]
    except KeyError as error:
        raise ExecutionPolicyError("unsupported work type") from error


def _effort_for(role: str, gear: str) -> str:
    if role == "software_engineer":
        return _engineer_effort(gear)
    efforts = {
        "orchestrator": "medium",
        "code_reviewer": "medium",
        "security_reviewer": "medium",
        "verifier": "low",
        "architect": "high",
    }
    try:
        return efforts[role]
    except KeyError as error:
        raise ExecutionPolicyError("unsupported role") from error


def _engineer_effort(gear: str) -> str:
    efforts = {"Small Change": "medium", "Build": "high", "High Risk": "high"}
    try:
        return efforts[gear]
    except KeyError as error:
        raise ExecutionPolicyError("unsupported gear") from error


def _profile(
    requested: ProfileKey, actual: ProfileKey, reason: str | None
) -> ExecutionProfile:
    return ExecutionProfile(
        policy_version=1,
        requested_model=requested[0],
        requested_reasoning_effort=requested[1],
        actual_model=actual[0],
        actual_reasoning_effort=actual[1],
        fallback_reason=reason,
    )
