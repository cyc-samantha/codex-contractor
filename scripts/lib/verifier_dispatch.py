"""Read-only deterministic verifier dispatch with telemetry gating."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from scripts.lib.dispatch_contract import (
    DispatchContract,
    parse_dispatch_contract,
    serialize_dispatch_contract,
)
from scripts.lib.execution_policy import (
    ExecutionPolicyError,
    ExecutionProfile,
    ProfileKey,
    resolve_execution_profile,
)
from scripts.lib.spawn_telemetry import (
    SpawnEnvelope,
    SpawnTelemetryError,
    SpawnTelemetryStore,
    TokenMetric,
)


class VerifierDispatchError(RuntimeError):
    """Raised when read-only verifier dispatch cannot pass its gates."""


@dataclass(frozen=True)
class VerifierDispatchBinding:
    task_id: str
    run_id: str
    event_id: str
    dispatch_id: str
    role: str
    role_instance_id: str
    session_id: str
    target_head: str


@dataclass(frozen=True)
class VerifierExecution:
    binding: VerifierDispatchBinding
    payload: Any
    actual_model: str
    actual_reasoning_effort: str
    input_tokens: TokenMetric
    cached_input_tokens: TokenMetric
    output_tokens: TokenMetric
    duration_ms: int


VerifierRuntime = Callable[
    [DispatchContract, ExecutionProfile, VerifierDispatchBinding], VerifierExecution
]


def dispatch_verifier(
    contract: DispatchContract,
    run_id: str,
    event_id: str,
    retry_cycle_id: str,
    work_type: str,
    telemetry: SpawnTelemetryStore,
    runtime: VerifierRuntime,
    available_profiles: set[ProfileKey],
    authorized_fallbacks: Mapping[ProfileKey, ProfileKey],
    review_head: str,
    current_head: str,
    worktree_clean: bool,
) -> VerifierExecution:
    validated = _validated_target(contract, review_head, current_head, worktree_clean)
    profile = _resolve_profile(validated, work_type, available_profiles, authorized_fallbacks)
    binding = _binding(validated, run_id, event_id)
    _reject_existing_event(telemetry, event_id)
    execution = _run_runtime(runtime, validated, profile, binding)
    _validate_execution(binding, profile, execution)
    _record_telemetry(telemetry, _envelope(profile, execution, retry_cycle_id))
    return execution


def _validate_contract(contract: DispatchContract) -> DispatchContract:
    try:
        validated = parse_dispatch_contract(serialize_dispatch_contract(contract))
    except (TypeError, ValueError) as error:
        raise VerifierDispatchError(f"verifier contract is not trusted: {error}") from error
    _require_verifier_role(validated)
    _require_read_only_permissions(validated)
    return validated


def _validated_target(
    contract: DispatchContract,
    review_head: str,
    current_head: str,
    worktree_clean: bool,
) -> DispatchContract:
    validated = _validate_contract(contract)
    _require_fresh_target(validated, review_head, current_head, worktree_clean)
    return validated


def _require_verifier_role(contract: DispatchContract) -> None:
    if contract.role != "verifier":
        raise VerifierDispatchError("verifier dispatch requires verifier role")


def _require_read_only_permissions(contract: DispatchContract) -> None:
    permissions = contract.permissions
    if (permissions.filesystem, permissions.network, permissions.tools) != (
        "read-only", "disabled", "none"
    ):
        raise VerifierDispatchError("verifier permissions must be read-only")


def _require_fresh_target(
    contract: DispatchContract,
    review_head: str,
    current_head: str,
    worktree_clean: bool,
) -> None:
    if type(worktree_clean) is not bool or not worktree_clean:
        raise VerifierDispatchError("verifier worktree must be clean")
    if contract.target_head != review_head:
        raise VerifierDispatchError("verifier target does not match review HEAD")
    if contract.target_head != current_head:
        raise VerifierDispatchError("verifier target does not match current HEAD")


def _resolve_profile(
    contract: DispatchContract,
    work_type: str,
    available: set[ProfileKey],
    fallbacks: Mapping[ProfileKey, ProfileKey],
) -> ExecutionProfile:
    try:
        profile = resolve_execution_profile(contract.role, "Build", work_type, available, fallbacks)
    except ExecutionPolicyError as error:
        raise VerifierDispatchError(f"execution profile unavailable: {error}") from error
    _require_requested_profile(contract, profile)
    return profile


def _require_requested_profile(
    contract: DispatchContract, profile: ExecutionProfile
) -> None:
    requested = (contract.requested_model, contract.requested_reasoning_effort)
    actual = (profile.requested_model, profile.requested_reasoning_effort)
    if requested != actual:
        raise VerifierDispatchError("dispatch contract contradicts execution profile")


def _binding(contract: DispatchContract, run_id: str, event_id: str) -> VerifierDispatchBinding:
    values = (contract.task_id, run_id, event_id, contract.dispatch_id,
              contract.role, contract.role_instance_id, contract.session_id,
              contract.target_head)
    return VerifierDispatchBinding(*values)


def _run_runtime(
    runtime: VerifierRuntime,
    contract: DispatchContract,
    profile: ExecutionProfile,
    binding: VerifierDispatchBinding,
) -> VerifierExecution:
    try:
        return runtime(contract, profile, binding)
    except Exception as error:
        raise VerifierDispatchError("verifier runtime failed") from error


def _reject_existing_event(telemetry: SpawnTelemetryStore, event_id: str) -> None:
    try:
        if any(event.event_id == event_id for event in telemetry.read_events()):
            raise VerifierDispatchError("telemetry event_id already exists")
    except SpawnTelemetryError as error:
        raise VerifierDispatchError(f"telemetry gate failed: {error}") from error


def _validate_execution(
    binding: VerifierDispatchBinding,
    profile: ExecutionProfile,
    execution: VerifierExecution,
) -> None:
    _require_execution_type(execution)
    _require_execution_binding(execution, binding)
    _require_execution_profile(execution, profile)


def _require_execution_type(execution: object) -> None:
    if not isinstance(execution, VerifierExecution):
        raise VerifierDispatchError("runtime result is malformed")


def _require_execution_binding(
    execution: VerifierExecution, binding: VerifierDispatchBinding
) -> None:
    if execution.binding != binding:
        raise VerifierDispatchError("runtime telemetry binding mismatch")


def _require_execution_profile(
    execution: VerifierExecution, profile: ExecutionProfile
) -> None:
    actual = (execution.actual_model, execution.actual_reasoning_effort)
    expected = (profile.actual_model, profile.actual_reasoning_effort)
    if actual != expected:
        raise VerifierDispatchError("telemetry execution profile mismatch")


def _envelope(
    profile: ExecutionProfile,
    execution: VerifierExecution,
    retry_cycle_id: str,
) -> SpawnEnvelope:
    binding = execution.binding
    return SpawnEnvelope(
        1,
        binding.event_id,
        binding.task_id,
        binding.run_id,
        binding.dispatch_id,
        binding.role,
        binding.role_instance_id,
        binding.session_id,
        None,
        profile.requested_model,
        execution.actual_model,
        profile.requested_reasoning_effort,
        execution.actual_reasoning_effort,
        execution.input_tokens,
        execution.cached_input_tokens,
        execution.output_tokens,
        execution.duration_ms,
        retry_cycle_id,
    )


def _record_telemetry(
    telemetry: SpawnTelemetryStore,
    envelope: SpawnEnvelope,
) -> None:
    try:
        telemetry.record(envelope)
        recorded = tuple(
            event for event in telemetry.read_events()
            if event.event_id == envelope.event_id
        )
    except SpawnTelemetryError as error:
        raise VerifierDispatchError(f"telemetry gate failed: {error}") from error
    if recorded != (envelope,):
        raise VerifierDispatchError("telemetry read-back did not match verifier dispatch")
