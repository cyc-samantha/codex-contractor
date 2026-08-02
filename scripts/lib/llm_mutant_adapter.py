"""Bounded, read-only Codex generation for semantic mutation candidates."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import subprocess
from typing import Any, Mapping

from .dispatch_contract import DispatchContract
from .spawn_telemetry import (
    SpawnTelemetryError,
    SpawnTelemetryStore,
    TokenMetric,
)
from .verifier_dispatch import (
    VerifierDispatchBinding,
    VerifierDispatchError,
    VerifierExecution,
    dispatch_verifier,
)
from .llm_mutant_types import (
    AdapterActivation,
    CanonicalDiffReader,
    CodexInvoker,
    LLM_MUTANT_CATEGORIES,
    MAX_DIFF_BYTES,
    MAX_DURATION_MS,
    LlmMutantCall,
    LlmMutantResponse,
    LlmMutantResult,
    LlmMutantSkip,
    SemanticMutant,
    TargetProbe,
    LlmMutantAdapterError,
)
from .llm_mutant_git import canonical_diff, target_probe as git_target_probe
from .llm_mutant_runtime import NativeCodexRuntime
from .llm_mutant_schema import validate_response, validate_survivors
from .llm_mutant_validation import bounded_text


@dataclass(frozen=True)
class _CanonicalDiff:
    text: str
    digest: str


@dataclass(frozen=True)
class _AdapterPayload:
    status: str
    mutants: tuple[SemanticMutant, ...]
    reason: str | None


def generate_llm_mutants(
    contract: DispatchContract,
    reviewed_head: str,
    run_id: str,
    event_id: str,
    retry_cycle_id: str,
    work_type: str,
    telemetry: SpawnTelemetryStore,
    canonical_diff_reader: CanonicalDiffReader | None,
    survivor_records: tuple[Mapping[str, Any], ...],
    supplied_diff: str | None,
    invoke: CodexInvoker | None,
    available_profiles: set[tuple[str, str]],
    authorized_fallbacks: Mapping[tuple[str, str], tuple[str, str]],
    activation: AdapterActivation | None = None,
    engineer_role_instance_id: str = "software_engineer-01",
    engineer_session_id: str = "session-software_engineer-01",
    target_probe: TargetProbe | None = None,
) -> LlmMutantResult:
    _validate_identity(contract, reviewed_head, engineer_role_instance_id, engineer_session_id)
    if activation is None or not activation.enabled:
        return _skip("activation-disabled", "")
    if activation.prerequisite_verdict != "T13B-D-ready":
        return _skip("activation-prerequisite-unavailable", "")
    if not activation.canary_event_id or not _has_rollout_canary(
        telemetry, contract.task_id, run_id, activation.canary_event_id
    ):
        return _skip("telemetry-canary-unavailable", "")
    reader = canonical_diff_reader or canonical_diff
    runtime = invoke or NativeCodexRuntime()
    canonical = _canonical_diff(contract, reviewed_head, supplied_diff, reader)
    survivors = validate_survivors(survivor_records)
    probe = target_probe or (lambda: git_target_probe(contract.repository))
    _require_target(probe(), reviewed_head)
    try:
        execution = _dispatch_once(
            contract, reviewed_head, run_id, event_id, retry_cycle_id, work_type,
            telemetry, canonical, survivors, runtime, available_profiles,
            authorized_fallbacks, probe,
        )
    except VerifierDispatchError as error:
        cause = error.__cause__
        if isinstance(cause, LlmMutantAdapterError):
            raise cause
        return _skip("dispatch-unavailable", canonical.digest)
    payload = execution.payload
    if not isinstance(payload, _AdapterPayload):
        return _skip("malformed-runtime-payload", canonical.digest)
    return LlmMutantResult(payload.status, payload.mutants, payload.reason, canonical.digest)


def _validate_identity(
    contract: DispatchContract,
    reviewed_head: str,
    engineer_identity: str,
    engineer_session: str,
) -> None:
    if contract.role != "verifier" or contract.role_instance_id == engineer_identity:
        raise LlmMutantAdapterError("producer must be a distinct non-Software Engineer role")
    if contract.session_id == engineer_session or contract.target_head != reviewed_head:
        raise LlmMutantAdapterError("adapter identity or review HEAD is contradictory")


def _canonical_diff(
    contract: DispatchContract,
    reviewed_head: str,
    supplied_diff: str | None,
    reader: CanonicalDiffReader,
) -> _CanonicalDiff:
    if supplied_diff is not None:
        bounded_text(supplied_diff, MAX_DIFF_BYTES, "canonical diff")
    try:
        text = reader(contract.repository, contract.base_head, reviewed_head)
    except Exception as error:
        raise LlmMutantAdapterError("canonical diff reconstruction failed") from error
    bounded_text(text, MAX_DIFF_BYTES, "canonical diff")
    digest = sha256(text.encode("utf-8")).hexdigest()
    if supplied_diff is not None and supplied_diff != text:
        raise LlmMutantAdapterError("canonical diff digest does not match reconstructed diff")
    return _CanonicalDiff(text, digest)


def _dispatch_once(
    contract: DispatchContract,
    reviewed_head: str,
    run_id: str,
    event_id: str,
    retry_cycle_id: str,
    work_type: str,
    telemetry: SpawnTelemetryStore,
    canonical: _CanonicalDiff,
    survivors: tuple[Mapping[str, Any], ...],
    invoke: CodexInvoker,
    available_profiles: set[tuple[str, str]],
    fallbacks: Mapping[tuple[str, str], tuple[str, str]],
    target_probe: TargetProbe,
) -> VerifierExecution:
    def runtime(_contract, _profile, binding: VerifierDispatchBinding) -> VerifierExecution:
        call = LlmMutantCall(
            1, contract.task_id, reviewed_head, _profile.actual_model,
            _profile.actual_reasoning_effort, canonical.text, canonical.digest,
            survivors, contract.role, contract.role_instance_id, contract.session_id,
            contract.dispatch_id, run_id, event_id, ("read-only", "disabled", "none"),
            True, True,
        )
        response = _invoke_once(invoke, call, _profile.actual_model, _profile.actual_reasoning_effort)
        try:
            validated = validate_response(
                response, canonical.text, contract, binding, survivors
            )
            payload = _AdapterPayload("PASS", validated, None)
        except (LlmMutantSkip, LlmMutantAdapterError) as error:
            if not _metrics_are_recordable(response):
                response = _failure_response(
                    _profile.actual_model, _profile.actual_reasoning_effort, str(error), 0
                )
            payload = _AdapterPayload("SKIP", (), str(error))
        return VerifierExecution(
            binding, payload, response.actual_model, response.actual_reasoning_effort,
            response.input_tokens, response.cached_input_tokens,
            response.output_tokens, response.duration_ms,
        )

    return dispatch_verifier(
        contract, run_id, event_id, retry_cycle_id, work_type, telemetry, runtime,
        available_profiles, fallbacks, reviewed_head, target_probe,
    )


def _invoke_once(invoke, call, model: str, effort: str) -> LlmMutantResponse:
    try:
        response = invoke(call)
    except (subprocess.TimeoutExpired, TimeoutError):
        return _failure_response(model, effort, "runtime-timeout", MAX_DURATION_MS)
    except Exception:
        return _failure_response(model, effort, "runtime-error", 0)
    if not isinstance(response, LlmMutantResponse):
        return _failure_response(model, effort, "malformed-runtime-response", 0)
    return response


def _failure_response(
    model: str, effort: str, reason: str, duration_ms: int
) -> LlmMutantResponse:
    metric = TokenMetric(None, reason)
    return LlmMutantResponse((), model, effort, metric, metric, metric, duration_ms)


def _metrics_are_recordable(response: object) -> bool:
    if not isinstance(response, LlmMutantResponse):
        return False
    metrics = (response.input_tokens, response.cached_input_tokens, response.output_tokens)
    return all(
        isinstance(metric, TokenMetric)
        and (metric.value is not None or bool(metric.unavailable_reason))
        for metric in metrics
    ) and type(response.duration_ms) is int and response.duration_ms >= 0


def _has_rollout_canary(
    telemetry: SpawnTelemetryStore, task_id: str, run_id: str, event_id: str
) -> bool:
    try:
        return any(_is_correlated_canary(event, task_id, run_id, event_id)
                   for event in telemetry.read_events())
    except SpawnTelemetryError:
        return False


def _is_correlated_canary(event, task_id: str, run_id: str, event_id: str) -> bool:
    identity_matches = (
        event.event_id == event_id and event.task_id == task_id
        and event.run_id == run_id and event.role == "software_engineer"
    )
    profile_matches = (
        event.requested_model == event.actual_model
        and event.requested_reasoning_effort == event.actual_reasoning_effort
    )
    metrics_known = all(metric.value is not None for metric in (
        event.input_tokens, event.cached_input_tokens, event.output_tokens
    ))
    return identity_matches and profile_matches and metrics_known and event.retry_cycle_id == "canary"


def _require_target(state: tuple[str, bool], reviewed_head: str) -> None:
    current_head, clean = state
    if current_head != reviewed_head or clean is not True:
        raise LlmMutantAdapterError("review HEAD is stale or worktree is dirty")


def _skip(reason: str, digest: str) -> LlmMutantResult:
    return LlmMutantResult("SKIP", (), reason, digest)
