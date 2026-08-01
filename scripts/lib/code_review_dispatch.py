"""Telemetry-gated Code Reviewer dispatch facade."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from scripts.lib.dispatch_contract import DispatchContract
from scripts.lib.execution_policy import (
    ExecutionPolicyError,
    ExecutionProfile,
    ProfileKey,
    resolve_execution_profile,
)
from scripts.lib.review_evidence import (
    ReviewEvidence,
    ReviewEvidenceError,
    parse_review_evidence,
    serialize_review_evidence,
)
from scripts.lib.security_review import (
    SecurityReviewError,
    SecurityReviewState,
    require_code_review_approval,
    validate_security_review_state,
)
from scripts.lib.spawn_telemetry import (
    SpawnEnvelope,
    SpawnTelemetryError,
    SpawnTelemetryStore,
    TokenMetric,
)


class CodeReviewDispatchError(RuntimeError):
    """Raised when formal Code Reviewer dispatch cannot pass its gates."""


@dataclass(frozen=True)
class ReviewBinding:
    task_id: str
    run_id: str
    event_id: str
    dispatch_id: str
    reviewer_id: str
    reviewer_session_id: str
    software_engineer_id: str
    software_engineer_session_id: str
    software_engineer_model: str
    reviewer_model: str
    reviewed_head: str


@dataclass(frozen=True)
class ReviewExecution:
    binding: ReviewBinding
    evidence: ReviewEvidence
    actual_model: str
    actual_reasoning_effort: str
    input_tokens: TokenMetric
    cached_input_tokens: TokenMetric
    output_tokens: TokenMetric
    duration_ms: int


RuntimePort = Callable[
    [DispatchContract, ExecutionProfile, ReviewBinding], ReviewExecution
]
TargetProbe = Callable[[], tuple[str, bool]]


def dispatch_code_review(
    contract: DispatchContract,
    software_engineer_id: str,
    software_engineer_session_id: str,
    software_engineer_event_id: str,
    target_probe: TargetProbe,
    run_id: str,
    event_id: str,
    retry_cycle_id: str,
    telemetry: SpawnTelemetryStore,
    runtime: RuntimePort,
    available_profiles: set[ProfileKey],
    authorized_fallbacks: Mapping[ProfileKey, ProfileKey],
    security_review: SecurityReviewState,
) -> ReviewExecution:
    current_head, worktree_clean = target_probe()
    _require_security_approval(
        contract, security_review, current_head, run_id, telemetry
    )
    _require_reviewable(
        contract, software_engineer_id, software_engineer_session_id,
        current_head, worktree_clean,
    )
    software_engineer_model = _engineer_model(
        telemetry,
        software_engineer_event_id,
        contract.task_id,
        run_id,
        software_engineer_id,
        software_engineer_session_id,
    )
    profile = _resolve_profile(contract, available_profiles, authorized_fallbacks)
    if software_engineer_model == profile.actual_model:
        raise CodeReviewDispatchError("formal review requires a distinct model")
    binding = _binding(
        contract, software_engineer_id, software_engineer_session_id,
        software_engineer_model, profile.actual_model, run_id, event_id,
    )
    execution = runtime(contract, profile, binding)
    _require_unchanged_target(contract, target_probe())
    validated = _validated_execution(binding, profile, execution)
    try:
        telemetry.record(_envelope(profile, validated, retry_cycle_id))
    except SpawnTelemetryError as error:
        raise CodeReviewDispatchError(f"telemetry gate failed: {error}") from error
    return validated


def _require_security_approval(
    contract: DispatchContract,
    security_review: SecurityReviewState,
    target_head: str,
    run_id: str,
    telemetry: SpawnTelemetryStore,
) -> None:
    if not isinstance(security_review, SecurityReviewState):
        raise CodeReviewDispatchError("security review state is required")
    if security_review.task_id != contract.task_id:
        raise CodeReviewDispatchError("security review task mismatch")
    try:
        validate_security_review_state(security_review)
    except SecurityReviewError as error:
        raise CodeReviewDispatchError(str(error)) from error
    if security_review.required != (contract.risk == "High Risk"):
        raise CodeReviewDispatchError("security review risk does not match contract")
    if (
        security_review.downgrade is not None
        and security_review.downgrade.target_gear != contract.risk
    ):
        raise CodeReviewDispatchError("security downgrade target does not match contract")
    try:
        require_code_review_approval(
            security_review, target_head, contract.repository, telemetry, run_id
        )
    except SecurityReviewError as error:
        raise CodeReviewDispatchError(str(error)) from error


def _engineer_model(
    telemetry: SpawnTelemetryStore,
    event_id: str,
    task_id: str,
    run_id: str,
    engineer_id: str,
    engineer_session_id: str,
) -> str:
    matches = tuple(
        event for event in telemetry.read_events()
        if _engineer_event_matches(
            event, event_id, task_id, run_id, engineer_id, engineer_session_id
        )
    )
    if len(matches) != 1:
        raise CodeReviewDispatchError(
            "durable Software Engineer telemetry is missing or mismatched"
        )
    return matches[0].actual_model


def _engineer_event_matches(
    event: SpawnEnvelope,
    event_id: str,
    task_id: str,
    run_id: str,
    engineer_id: str,
    engineer_session_id: str,
) -> bool:
    identity = (event.role_instance_id, event.session_id)
    expected_identity = (engineer_id, engineer_session_id)
    return (
        event.event_id == event_id
        and event.task_id == task_id
        and event.run_id == run_id
        and event.role == "software_engineer"
        and identity == expected_identity
    )


def _require_reviewable(
    contract: DispatchContract,
    engineer_id: str,
    engineer_session_id: str,
    current_head: str,
    clean: bool,
) -> None:
    if contract.role != "code_reviewer":
        raise CodeReviewDispatchError("dispatch role must be code_reviewer")
    if (
        contract.role_instance_id == engineer_id
        or contract.session_id == engineer_session_id
    ):
        raise CodeReviewDispatchError("self-review is forbidden")
    if clean is not True:
        raise CodeReviewDispatchError("review worktree must be clean")
    if current_head != contract.target_head:
        raise CodeReviewDispatchError("review target HEAD is stale")


def _require_unchanged_target(
    contract: DispatchContract, target_state: tuple[str, bool]
) -> None:
    current_head, clean = target_state
    if current_head != contract.target_head or clean is not True:
        raise CodeReviewDispatchError("repository changed during review")


def _resolve_profile(
    contract: DispatchContract,
    available: set[ProfileKey],
    fallbacks: Mapping[ProfileKey, ProfileKey],
) -> ExecutionProfile:
    try:
        profile = resolve_execution_profile(
            contract.role, contract.risk, "complex", available, fallbacks
        )
    except ExecutionPolicyError as error:
        raise CodeReviewDispatchError(f"execution profile unavailable: {error}") from error
    requested = (contract.requested_model, contract.requested_reasoning_effort)
    expected = (profile.requested_model, profile.requested_reasoning_effort)
    if requested != expected:
        raise CodeReviewDispatchError("dispatch contract contradicts execution profile")
    return profile


def _binding(
    contract: DispatchContract,
    engineer_id: str,
    engineer_session_id: str,
    engineer_model: str,
    reviewer_model: str,
    run_id: str,
    event_id: str,
) -> ReviewBinding:
    return ReviewBinding(
        task_id=contract.task_id,
        run_id=run_id,
        event_id=event_id,
        dispatch_id=contract.dispatch_id,
        reviewer_id=contract.role_instance_id,
        reviewer_session_id=contract.session_id,
        software_engineer_id=engineer_id,
        software_engineer_session_id=engineer_session_id,
        software_engineer_model=engineer_model,
        reviewer_model=reviewer_model,
        reviewed_head=contract.target_head,
    )


def _validated_execution(
    binding: ReviewBinding,
    profile: ExecutionProfile,
    execution: ReviewExecution,
) -> ReviewExecution:
    if execution.binding != binding:
        raise CodeReviewDispatchError("runtime telemetry binding mismatch")
    actual = (execution.actual_model, execution.actual_reasoning_effort)
    if actual != (profile.actual_model, profile.actual_reasoning_effort):
        raise CodeReviewDispatchError("telemetry execution profile mismatch")
    try:
        evidence = parse_review_evidence(serialize_review_evidence(execution.evidence))
    except ReviewEvidenceError as error:
        raise CodeReviewDispatchError(f"invalid review evidence: {error}") from error
    if not _evidence_matches(binding, evidence):
        raise CodeReviewDispatchError("review evidence binding mismatch")
    return ReviewExecution(
        binding, evidence, execution.actual_model,
        execution.actual_reasoning_effort, execution.input_tokens,
        execution.cached_input_tokens, execution.output_tokens,
        execution.duration_ms,
    )


def _evidence_matches(binding: ReviewBinding, evidence: ReviewEvidence) -> bool:
    return (
        evidence.task_id == binding.task_id
        and evidence.reviewed_head == binding.reviewed_head
        and evidence.software_engineer_id == binding.software_engineer_id
        and evidence.software_engineer_session_id
        == binding.software_engineer_session_id
        and evidence.software_engineer_model == binding.software_engineer_model
        and evidence.reviewer_id == binding.reviewer_id
        and evidence.reviewer_session_id == binding.reviewer_session_id
        and evidence.reviewer_model == binding.reviewer_model
        and evidence.dispatch_id == binding.dispatch_id
        and evidence.run_id == binding.run_id
        and evidence.telemetry_event_id == binding.event_id
    )


def _envelope(
    profile: ExecutionProfile,
    execution: ReviewExecution,
    retry_cycle_id: str,
) -> SpawnEnvelope:
    binding = execution.binding
    return SpawnEnvelope(
        1, binding.event_id, binding.task_id, binding.run_id,
        binding.dispatch_id, "code_reviewer", binding.reviewer_id,
        binding.reviewer_session_id, None, profile.requested_model,
        execution.actual_model, profile.requested_reasoning_effort,
        execution.actual_reasoning_effort, execution.input_tokens,
        execution.cached_input_tokens, execution.output_tokens,
        execution.duration_ms, retry_cycle_id,
    )
