"""Quality metadata and role/effort aggregates for spawn reconciliation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Iterable

try:
    from .spawn_telemetry_shared import SpawnTelemetryError, TokenMetric
except ImportError:
    from spawn_telemetry_shared import SpawnTelemetryError, TokenMetric

if TYPE_CHECKING:
    from .spawn_telemetry import PrReconciliation, SpawnEnvelope


QUALITY_VERDICTS = frozenset({
    "APPROVE", "CHANGES_REQUESTED", "VERIFIED", "VERIFIED_WITH_SKIP",
    "UNVERIFIED", "FAILED", "PR_CREATED", "PR_CREATION_FAILED",
    "BUILD_COMPLETE", "BUILD_FAILED", "BLOCKED",
})


@dataclass(frozen=True)
class ReconciliationQuality:
    verdict: str
    finding_count: int
    retry_count: int
    injected_learning_tokens: TokenMetric


@dataclass(frozen=True)
class RoleEffortAggregate:
    role: str
    reasoning_effort: str
    known_token_total: int
    unknown_token_fields: tuple[str, ...]


def aggregate_role_effort(events: Iterable[SpawnEnvelope]) -> tuple[RoleEffortAggregate, ...]:
    grouped: dict[tuple[str, str], list[SpawnEnvelope]] = {}
    for event in events:
        grouped.setdefault((event.role, event.actual_reasoning_effort), []).append(event)
    return tuple(_role_effort_record(key, items) for key, items in sorted(grouped.items()))


def _role_effort_record(
    key: tuple[str, str], events: Iterable[SpawnEnvelope]
) -> RoleEffortAggregate:
    usage = _spawn_module().aggregate_spawn_usage(events)
    return RoleEffortAggregate(key[0], key[1], usage.known_token_total, usage.unknown_token_fields)


def validate_quality(quality: ReconciliationQuality | None) -> None:
    if quality is None:
        return
    if not isinstance(quality, ReconciliationQuality):
        raise SpawnTelemetryError("quality has invalid type")
    if quality.verdict not in QUALITY_VERDICTS:
        raise SpawnTelemetryError("quality verdict is unsupported")
    _validate_quality_counts(quality)
    _validate_learning_tokens(quality)
def _validate_quality_counts(quality: ReconciliationQuality) -> None:
    _spawn_module()._nonnegative_integer(quality.finding_count, "quality finding_count")
    _spawn_module()._nonnegative_integer(quality.retry_count, "quality retry_count")
def _validate_learning_tokens(quality: ReconciliationQuality) -> None:
    _spawn_module()._metric(_spawn_module()._serialize(quality.injected_learning_tokens), "quality injected_learning_tokens")


def require_same_quality(
    record: PrReconciliation, quality: ReconciliationQuality | None
) -> None:
    if record.quality != quality:
        raise SpawnTelemetryError("task run already reconciled with different quality")


def parse_reconciliation(value: object) -> PrReconciliation:
    fields = _spawn_module()._mapping(value, "PR reconciliation")
    _validate_reconciliation_fields(fields)
    return _reconciliation_from_fields(fields)


def _validate_reconciliation_fields(fields: dict[str, Any]) -> None:
    base = {"schema_version", "task_id", "run_id", "pr_id", "known_token_total", "unknown_token_fields"}
    enriched = base | {"quality", "role_effort_breakdown"}
    if fields.keys() not in (base, enriched):
        raise SpawnTelemetryError("PR reconciliation has missing or unknown fields")
    if type(fields["schema_version"]) is not int or fields["schema_version"] != 1:
        raise SpawnTelemetryError("unsupported reconciliation schema_version")


def _reconciliation_from_fields(fields: dict[str, Any]) -> PrReconciliation:
    module = _spawn_module()
    unknown = _unknown_fields(fields["unknown_token_fields"])
    quality = _parse_quality(fields.get("quality"))
    breakdown = _parse_breakdown(fields.get("role_effort_breakdown", []))
    return _build_reconciliation(module, fields, unknown, quality, breakdown)
def _build_reconciliation(
    module: Any, fields: dict[str, Any], unknown: list[str], quality: ReconciliationQuality | None,
    breakdown: tuple[RoleEffortAggregate, ...],
) -> PrReconciliation:
    return module.PrReconciliation(fields["schema_version"], module._identifier(fields["task_id"], "task_id"), module._identifier(fields["run_id"], "run_id"), module._identifier(fields["pr_id"], "pr_id"), module._nonnegative_integer(fields["known_token_total"], "known_token_total"), tuple(unknown), quality, breakdown)


def _parse_quality(value: object) -> ReconciliationQuality | None:
    if value is None:
        return None
    module = _spawn_module()
    fields = module._mapping(value, "quality")
    module._exact_fields(fields, {"verdict", "finding_count", "retry_count", "injected_learning_tokens"}, "quality")
    quality = _build_quality(fields)
    validate_quality(quality)
    return quality
def _build_quality(fields: dict[str, Any]) -> ReconciliationQuality:
    module = _spawn_module()
    return ReconciliationQuality(module._text(fields["verdict"], "quality verdict"), fields["finding_count"], fields["retry_count"], module._metric(fields["injected_learning_tokens"], "quality injected_learning_tokens"))


def _parse_breakdown(value: object) -> tuple[RoleEffortAggregate, ...]:
    if not isinstance(value, list):
        raise SpawnTelemetryError("role_effort_breakdown must be a list")
    records = tuple(_parse_breakdown_record(item) for item in value)
    _validate_breakdown_order(records)
    return records
def _validate_breakdown_order(records: tuple[RoleEffortAggregate, ...]) -> None:
    keys = [(item.role, item.reasoning_effort) for item in records]
    if keys != sorted(set(keys)):
        raise SpawnTelemetryError("role_effort_breakdown must be unique and sorted")


def _parse_breakdown_record(value: object) -> RoleEffortAggregate:
    module = _spawn_module()
    fields = module._mapping(value, "role effort aggregate")
    module._exact_fields(fields, {"role", "reasoning_effort", "known_token_total", "unknown_token_fields"}, "role effort aggregate")
    return _build_breakdown(module, fields)
def _build_breakdown(module: Any, fields: dict[str, Any]) -> RoleEffortAggregate:
    unknown = _unknown_fields(fields["unknown_token_fields"])
    return RoleEffortAggregate(module._text(fields["role"], "role"), module._text(fields["reasoning_effort"], "reasoning_effort"), module._nonnegative_integer(fields["known_token_total"], "known_token_total"), tuple(unknown))


def _unknown_fields(value: object) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise SpawnTelemetryError("unknown token fields must be strings")
    return value


def _spawn_module() -> Any:
    try:
        from . import spawn_telemetry
    except ImportError:
        import spawn_telemetry
    return spawn_telemetry
