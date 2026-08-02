"""Bounded, read-only Codex generation for semantic mutation candidates."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import fnmatch
from typing import Any, Mapping

from .dispatch_contract import DispatchContract
from .spawn_telemetry import SpawnTelemetryStore, TokenMetric
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
    EQUIVALENCE,
    LLM_MUTANT_CATEGORIES,
    MAX_DIFF_BYTES,
    MAX_DURATION_MS,
    MAX_OUTPUT_BYTES,
    MAX_OUTPUT_TOKENS,
    MAX_SURVIVOR_BYTES,
    MAX_SURVIVOR_PAYLOAD_BYTES,
    MAX_SURVIVORS,
    MUTANT_FIELDS,
    LlmMutantCall,
    LlmMutantResponse,
    LlmMutantResult,
    SemanticMutant,
    TargetProbe,
    LlmMutantAdapterError,
)
from .llm_mutant_validation import (
    bounded_json,
    bounded_text,
    choice,
    line_range,
    normalized_text,
    safe_file,
    snippet,
)


class _LlmMutantSkip(RuntimeError):
    """Raised internally when the provider cannot produce an accepted batch."""


def generate_llm_mutants(
    contract: DispatchContract,
    reviewed_head: str,
    run_id: str,
    event_id: str,
    retry_cycle_id: str,
    work_type: str,
    telemetry: SpawnTelemetryStore,
    canonical_diff_reader: CanonicalDiffReader,
    survivor_records: tuple[Mapping[str, Any], ...],
    supplied_diff: str | None,
    invoke: CodexInvoker,
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
    if not activation.rollout_prerequisites_met:
        return _skip("rollout-prerequisites-unmet", "")
    canonical = _canonical_diff(contract, reviewed_head, supplied_diff, canonical_diff_reader)
    survivors = _validate_survivors(survivor_records)
    probe = target_probe or (lambda: (reviewed_head, True))
    _require_target(probe(), reviewed_head)
    try:
        execution = _dispatch_once(
            contract, reviewed_head, run_id, event_id, retry_cycle_id, work_type,
            telemetry, canonical, survivors, invoke, available_profiles,
            authorized_fallbacks, probe,
        )
    except VerifierDispatchError as error:
        cause = error.__cause__
        if isinstance(cause, LlmMutantAdapterError):
            raise cause
        return _skip("runtime-unavailable", canonical.digest)
    except (_LlmMutantSkip, TimeoutError):
        return _skip("runtime-unavailable", canonical.digest)
    if not activation.telemetry_canary():
        return _skip("telemetry-canary-unavailable", canonical.digest)
    return LlmMutantResult("PASS", execution.payload, None, canonical.digest)


@dataclass(frozen=True)
class _CanonicalDiff:
    text: str
    digest: str


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


def _validate_survivors(
    records: tuple[Mapping[str, Any], ...],
) -> tuple[Mapping[str, Any], ...]:
    if len(records) > MAX_SURVIVORS:
        raise LlmMutantAdapterError("survivor record count exceeds cap")
    for record in records:
        _validate_mutant_shape(record, "survivor")
        bounded_json(record, MAX_SURVIVOR_BYTES, "survivor record")
    bounded_json(records, MAX_SURVIVOR_PAYLOAD_BYTES, "survivor payload")
    return records


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
            1, contract.task_id, reviewed_head, canonical.text, canonical.digest,
            survivors, contract.role, contract.role_instance_id, contract.session_id,
            contract.dispatch_id, run_id, event_id, ("read-only", "disabled", "none"),
            True, True,
        )
        response = invoke(call)
        validated = _validate_response(response, canonical.text, contract, binding)
        return VerifierExecution(
            binding, validated, response.actual_model, response.actual_reasoning_effort,
            response.input_tokens, response.cached_input_tokens,
            response.output_tokens, response.duration_ms,
        )

    return dispatch_verifier(
        contract, run_id, event_id, retry_cycle_id, work_type, telemetry, runtime,
        available_profiles, fallbacks, reviewed_head, target_probe,
    )


def _validate_response(
    response: object,
    diff: str,
    contract: DispatchContract,
    binding: VerifierDispatchBinding,
) -> tuple[SemanticMutant, ...]:
    if not isinstance(response, LlmMutantResponse):
        raise _LlmMutantSkip("runtime response schema is invalid")
    _validate_metrics(response)
    if not isinstance(response.mutants, list):
        raise _LlmMutantSkip("mutant output schema is invalid")
    bounded_json(response.mutants, MAX_OUTPUT_BYTES, "mutant output")
    accepted = tuple(
        _parse_mutant(item, diff, contract, binding) for item in response.mutants[:10]
    )
    if not accepted or all(item.equivalent == "yes" for item in accepted):
        raise _LlmMutantSkip("no valid non-equivalent mutants")
    return accepted


def _validate_metrics(response: LlmMutantResponse) -> None:
    for metric in (response.input_tokens, response.cached_input_tokens, response.output_tokens):
        if not isinstance(metric, TokenMetric):
            raise _LlmMutantSkip("provider token telemetry is malformed")
        if metric.value is None and not metric.unavailable_reason:
            raise _LlmMutantSkip("provider token telemetry is unavailable without reason")
    if response.output_tokens.value is not None and response.output_tokens.value > MAX_OUTPUT_TOKENS:
        raise _LlmMutantSkip("output token cap exceeded")
    if type(response.duration_ms) is not int or not 0 <= response.duration_ms <= MAX_DURATION_MS:
        raise _LlmMutantSkip("runtime duration cap exceeded")


def _parse_mutant(
    value: object,
    diff: str,
    contract: DispatchContract,
    binding: VerifierDispatchBinding,
) -> SemanticMutant:
    _validate_mutant_shape(value, "mutant")
    fields = value
    file = safe_file(fields["file"])
    if not any(fnmatch.fnmatchcase(file, pattern) for pattern in contract.allowed_paths):
        raise LlmMutantAdapterError("mutant path is outside allowed paths")
    if file not in _changed_files(diff):
        raise LlmMutantAdapterError("mutant path is outside reviewed diff")
    parsed_line_range = line_range(fields["line_range"])
    original = snippet(fields["original"], "original")
    mutated = snippet(fields["mutated"], "mutated")
    if original not in _changed_source(diff):
        raise LlmMutantAdapterError("mutant original text does not match diff")
    category = choice(fields["category"], LLM_MUTANT_CATEGORIES, "category")
    rationale = normalized_text(fields["rationale"], "rationale")
    equivalent = choice(fields["equivalent"], EQUIVALENCE, "mutant equivalence")
    if equivalent == "yes" and len(rationale) < 1:
        raise LlmMutantAdapterError("equivalent mutant requires rationale")
    return SemanticMutant(
        contract.task_id, binding.target_head, file, parsed_line_range, original, mutated,
        category, rationale, equivalent, binding.role, binding.role_instance_id,
        binding.session_id, binding.dispatch_id, binding.run_id, binding.event_id,
        sha256(diff.encode("utf-8")).hexdigest(),
    )


def _validate_mutant_shape(value: object, name: str) -> None:
    if not isinstance(value, Mapping) or set(value) != MUTANT_FIELDS:
        raise LlmMutantAdapterError(f"{name} schema is invalid")


def _changed_files(diff: str) -> set[str]:
    return {
        line[6:]
        for line in diff.splitlines()
        if line.startswith("+++ b/")
    }


def _changed_source(diff: str) -> str:
    return "\n".join(
        line[1:]
        for line in diff.splitlines()
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    )


def _require_target(state: tuple[str, bool], reviewed_head: str) -> None:
    current_head, clean = state
    if current_head != reviewed_head or clean is not True:
        raise LlmMutantAdapterError("review HEAD is stale or worktree is dirty")


def _skip(reason: str, digest: str) -> LlmMutantResult:
    return LlmMutantResult("SKIP", (), reason, digest)
