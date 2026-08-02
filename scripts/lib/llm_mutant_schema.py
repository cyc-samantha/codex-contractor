"""Strict input/output schema validation for semantic mutants."""

from __future__ import annotations

import fnmatch
from hashlib import sha256
from typing import Any, Mapping

from .dispatch_contract import DispatchContract
from .llm_mutant_git import ChangedHunk, changed_details
from .llm_mutant_types import (
    EQUIVALENCE,
    LLM_MUTANT_CATEGORIES,
    MAX_DURATION_MS,
    MAX_OUTPUT_BYTES,
    MAX_OUTPUT_TOKENS,
    MAX_SURVIVOR_BYTES,
    MAX_SURVIVOR_PAYLOAD_BYTES,
    MAX_SURVIVORS,
    MUTANT_FIELDS,
    LlmMutantAdapterError,
    LlmMutantResponse,
    LlmMutantSkip,
    SemanticMutant,
)
from .llm_mutant_validation import (
    bounded_json,
    choice,
    line_range,
    mutation_key,
    mutation_keys,
    normalized_text,
    range_in_locations,
    record_key,
    safe_file,
    snippet,
)
from .spawn_telemetry import TokenMetric


def validate_survivors(records: tuple[Mapping[str, Any], ...]) -> tuple[Mapping[str, Any], ...]:
    if len(records) > MAX_SURVIVORS:
        raise LlmMutantAdapterError("survivor record count exceeds cap")
    seen = set()
    for record in records:
        _validate_shape(record, "survivor")
        safe_file(record["file"])
        line_range(record["line_range"])
        original = snippet(record["original"], "survivor original")
        mutated = snippet(record["mutated"], "survivor mutated")
        choice(record["category"], LLM_MUTANT_CATEGORIES, "survivor category")
        choice(record["equivalent"], EQUIVALENCE, "survivor equivalence")
        normalized_text(record["rationale"], "survivor rationale")
        if original == mutated:
            raise LlmMutantAdapterError("survivor must change source text")
        key = record_key(record)
        if key in seen:
            raise LlmMutantAdapterError("survivor records must be unique")
        seen.add(key)
        bounded_json(record, MAX_SURVIVOR_BYTES, "survivor record")
    bounded_json(records, MAX_SURVIVOR_PAYLOAD_BYTES, "survivor payload")
    return records


def validate_response(
    response: object,
    diff: str,
    contract: DispatchContract,
    binding,
    survivor_records: tuple[Mapping[str, Any], ...],
) -> tuple[SemanticMutant, ...]:
    if not isinstance(response, LlmMutantResponse):
        raise LlmMutantSkip("runtime response schema is invalid")
    if response.runtime_reason is not None:
        if not isinstance(response.runtime_reason, str) or not response.runtime_reason:
            raise LlmMutantSkip("runtime response schema is invalid")
        raise LlmMutantSkip(response.runtime_reason)
    validate_metrics(response)
    if not isinstance(response.mutants, list):
        raise LlmMutantSkip("mutant output schema is invalid")
    if len(response.mutants) > 10:
        raise LlmMutantSkip("mutant output count exceeds cap")
    bounded_json(response.mutants, MAX_OUTPUT_BYTES, "mutant output")
    accepted = []
    seen = set(mutation_keys(survivor_records))
    for item in response.mutants:
        mutant = parse_mutant(item, diff, contract, binding)
        if mutant.equivalent == "yes":
            continue
        if mutation_key(mutant) not in seen:
            accepted.append(mutant)
            seen.add(mutation_key(mutant))
        if len(accepted) == 10:
            break
    if not accepted or all(item.equivalent == "yes" for item in accepted):
        raise LlmMutantSkip("no-valid-non-equivalent-mutants")
    return tuple(accepted)


def validate_metrics(response: LlmMutantResponse) -> None:
    for metric in (response.input_tokens, response.cached_input_tokens, response.output_tokens):
        if not isinstance(metric, TokenMetric):
            raise LlmMutantSkip("provider-token-telemetry-malformed")
        if metric.value is not None and (type(metric.value) is not int or metric.value < 0):
            raise LlmMutantSkip("provider-token-telemetry-malformed")
        if metric.value is None and (
            not isinstance(metric.unavailable_reason, str)
            or not metric.unavailable_reason
        ):
            raise LlmMutantSkip("provider-token-telemetry-missing-reason")
    if response.output_tokens.value is not None and response.output_tokens.value > MAX_OUTPUT_TOKENS:
        raise LlmMutantSkip("output-token-cap-exceeded")
    if type(response.duration_ms) is not int or not 0 <= response.duration_ms <= MAX_DURATION_MS:
        raise LlmMutantSkip("duration-cap-exceeded")


def parse_mutant(value: object, diff: str, contract: DispatchContract, binding) -> SemanticMutant:
    _validate_shape(value, "mutant")
    file = safe_file(value["file"])
    if not any(fnmatch.fnmatchcase(file, pattern) for pattern in contract.allowed_paths):
        raise LlmMutantAdapterError("mutant path is outside allowed paths")
    details = changed_details(diff)
    if file not in details:
        raise LlmMutantAdapterError("mutant path is outside reviewed diff")
    parsed_line_range = line_range(value["line_range"])
    original = snippet(value["original"], "original")
    mutated = snippet(value["mutated"], "mutated")
    if original == mutated:
        raise LlmMutantAdapterError("mutant must change source text")
    matching_hunks = tuple(
        hunk for hunk in details[file]
        if range_in_locations(parsed_line_range, hunk.locations)
    )
    if not matching_hunks:
        raise LlmMutantAdapterError("mutant line range is outside changed hunk")
    if not _original_is_in_hunk(original, parsed_line_range, matching_hunks):
        raise LlmMutantAdapterError("mutant original text does not match diff")
    category = choice(value["category"], LLM_MUTANT_CATEGORIES, "category")
    rationale = normalized_text(value["rationale"], "rationale")
    equivalent = choice(value["equivalent"], EQUIVALENCE, "mutant equivalence")
    return SemanticMutant(
        contract.task_id, binding.target_head, file, parsed_line_range, original, mutated,
        category, rationale, equivalent, binding.role, binding.role_instance_id,
        binding.session_id, binding.dispatch_id, binding.run_id, binding.event_id,
        sha256(diff.encode("utf-8")).hexdigest(),
    )


def _validate_shape(value: object, name: str) -> None:
    if not isinstance(value, Mapping) or set(value) != MUTANT_FIELDS:
        raise LlmMutantAdapterError(f"{name} schema is invalid")


def _original_is_in_hunk(
    original: str, parsed_line_range: str, hunks: tuple[ChangedHunk, ...]
) -> bool:
    bounds = [int(item) for item in parsed_line_range.split("-")]
    for hunk in hunks:
        if original in "\n".join(hunk.source):
            return True
    return False
