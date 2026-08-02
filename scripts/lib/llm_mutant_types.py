"""Versioned types and caps for the Codex semantic-mutant boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .spawn_telemetry import TokenMetric


class LlmMutantAdapterError(ValueError):
    """Raised when bounded mutation input or output cannot be trusted."""


class LlmMutantSkip(RuntimeError):
    """Raised when one provider call cannot produce an accepted batch."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


LLM_MUTANT_CATEGORIES = frozenset(
    {
        "off-by-one",
        "wrong-comparator",
        "swapped-args",
        "null-vs-empty",
        "async-without-await",
    }
)
MAX_DIFF_BYTES = 200 * 1024
MAX_SURVIVORS = 100
MAX_SURVIVOR_BYTES = 4 * 1024
MAX_SURVIVOR_PAYLOAD_BYTES = 64 * 1024
MAX_OUTPUT_TOKENS = 8_000
MAX_OUTPUT_BYTES = 64 * 1024
MAX_DURATION_MS = 120_000
MUTANT_FIELDS = frozenset(
    {"file", "line_range", "original", "mutated", "category", "rationale", "equivalent"}
)
EQUIVALENCE = frozenset({"yes", "no", "unsure"})


@dataclass(frozen=True)
class AdapterActivation:
    enabled: bool = False
    prerequisite_verdict: str = "T13B-D-not-landed"
    canary_event_id: str | None = None


@dataclass(frozen=True)
class LlmMutantCall:
    adapter_version: int
    task_id: str
    reviewed_head: str
    requested_model: str
    requested_reasoning_effort: str
    diff: str
    diff_digest: str
    survivor_records: tuple[Mapping[str, Any], ...]
    role: str
    role_instance_id: str
    session_id: str
    dispatch_id: str
    run_id: str
    event_id: str
    permissions: tuple[str, str, str]
    input_is_untrusted: bool
    prohibit_instruction_following: bool


@dataclass(frozen=True)
class LlmMutantResponse:
    mutants: object
    actual_model: str
    actual_reasoning_effort: str
    input_tokens: TokenMetric
    cached_input_tokens: TokenMetric
    output_tokens: TokenMetric
    duration_ms: int
    runtime_reason: str | None = None


@dataclass(frozen=True)
class SemanticMutant:
    task_id: str
    reviewed_head: str
    file: str
    line_range: str
    original: str
    mutated: str
    category: str
    rationale: str
    equivalent: str
    producer_role: str
    producer_identity: str
    producer_session: str
    dispatch_id: str
    dispatch_run: str
    telemetry_event: str
    diff_digest: str


@dataclass(frozen=True)
class LlmMutantResult:
    status: str
    mutants: tuple[SemanticMutant, ...]
    reason: str | None
    diff_digest: str


CanonicalDiffReader = Callable[[Any, str, str], str]
CodexInvoker = Callable[[LlmMutantCall], LlmMutantResponse]
TargetProbe = Callable[[], tuple[str, bool]]
