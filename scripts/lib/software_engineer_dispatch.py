"""Telemetry-gated Software Engineer dispatch facade."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from scripts.lib.dispatch_contract import DispatchContract
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


class SoftwareEngineerDispatchError(RuntimeError):
    """Raised when Software Engineer dispatch cannot pass its gates."""


T13A_PROTECTED_WRITE_BOUNDARY_ACTIVE = False


@dataclass(frozen=True)
class DispatchBinding:
    task_id: str
    run_id: str
    event_id: str
    dispatch_id: str
    role: str
    role_instance_id: str
    session_id: str


@dataclass(frozen=True)
class DispatchExecution:
    binding: DispatchBinding
    payload: Any
    actual_model: str
    actual_reasoning_effort: str
    input_tokens: TokenMetric
    cached_input_tokens: TokenMetric
    output_tokens: TokenMetric
    duration_ms: int


RuntimePort = Callable[
    [DispatchContract, ExecutionProfile, DispatchBinding], DispatchExecution
]


def dispatch_software_engineer(
    contract: DispatchContract,
    run_id: str,
    event_id: str,
    retry_cycle_id: str,
    work_type: str,
    telemetry: SpawnTelemetryStore,
    runtime: RuntimePort,
    available_profiles: set[ProfileKey],
    authorized_fallbacks: Mapping[ProfileKey, ProfileKey],
) -> DispatchExecution:
    _require_activation(contract)
    profile = _resolve_profile(
        contract, work_type, available_profiles, authorized_fallbacks
    )
    binding = _binding(contract, run_id, event_id)
    execution = runtime(contract, profile, binding)
    _validate_execution(binding, profile, execution)
    envelope = _envelope(profile, execution, retry_cycle_id)
    try:
        telemetry.record(envelope)
    except SpawnTelemetryError as error:
        raise SoftwareEngineerDispatchError(f"telemetry gate failed: {error}") from error
    return execution


def _require_activation(contract: DispatchContract) -> None:
    if contract.role != "software_engineer":
        raise SoftwareEngineerDispatchError("dispatch role must be software_engineer")
    if not T13A_PROTECTED_WRITE_BOUNDARY_ACTIVE:
        raise SoftwareEngineerDispatchError("T13A protected-write prerequisite is inactive")


def _resolve_profile(
    contract: DispatchContract,
    work_type: str,
    available: set[ProfileKey],
    fallbacks: Mapping[ProfileKey, ProfileKey],
) -> ExecutionProfile:
    try:
        profile = resolve_execution_profile(
            contract.role, contract.risk, work_type, available, fallbacks
        )
    except ExecutionPolicyError as error:
        raise SoftwareEngineerDispatchError(f"execution profile unavailable: {error}") from error
    requested = (
        contract.requested_model,
        contract.requested_reasoning_effort,
    )
    if requested != (
        profile.requested_model,
        profile.requested_reasoning_effort,
    ):
        raise SoftwareEngineerDispatchError("dispatch contract contradicts execution profile")
    return profile


def _validate_execution(
    binding: DispatchBinding,
    profile: ExecutionProfile,
    execution: DispatchExecution,
) -> None:
    if execution.binding != binding:
        raise SoftwareEngineerDispatchError("runtime telemetry binding mismatch")
    actual = (execution.actual_model, execution.actual_reasoning_effort)
    if actual != (profile.actual_model, profile.actual_reasoning_effort):
        raise SoftwareEngineerDispatchError("telemetry execution profile mismatch")


def _binding(
    contract: DispatchContract, run_id: str, event_id: str
) -> DispatchBinding:
    return DispatchBinding(
        task_id=contract.task_id,
        run_id=run_id,
        event_id=event_id,
        dispatch_id=contract.dispatch_id,
        role=contract.role,
        role_instance_id=contract.role_instance_id,
        session_id=contract.session_id,
    )


def _envelope(
    profile: ExecutionProfile,
    execution: DispatchExecution,
    retry_cycle_id: str,
) -> SpawnEnvelope:
    return SpawnEnvelope(
        schema_version=1,
        event_id=execution.binding.event_id,
        task_id=execution.binding.task_id,
        run_id=execution.binding.run_id,
        dispatch_id=execution.binding.dispatch_id,
        role=execution.binding.role,
        role_instance_id=execution.binding.role_instance_id,
        session_id=execution.binding.session_id,
        pr_id=None,
        requested_model=profile.requested_model,
        actual_model=execution.actual_model,
        requested_reasoning_effort=profile.requested_reasoning_effort,
        actual_reasoning_effort=execution.actual_reasoning_effort,
        input_tokens=execution.input_tokens,
        cached_input_tokens=execution.cached_input_tokens,
        output_tokens=execution.output_tokens,
        duration_ms=execution.duration_ms,
        retry_cycle_id=retry_cycle_id,
    )
