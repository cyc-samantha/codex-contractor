"""Validate, persist, aggregate, and reconcile spawn telemetry."""
from __future__ import annotations
from dataclasses import asdict, dataclass
import os
from pathlib import Path
import re
from typing import Any, Iterable
from scripts.lib.writer_claim_io import open_harness_data
from scripts.lib.spawn_telemetry_shared import SpawnTelemetryError, TokenMetric

IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
TOKEN_FIELDS = ("input_tokens", "cached_input_tokens", "output_tokens")
ENVELOPE_FIELDS = frozenset(
    {
        "schema_version", "event_id", "task_id", "run_id", "dispatch_id",
        "role", "role_instance_id", "session_id", "pr_id", "requested_model",
        "actual_model", "requested_reasoning_effort",
        "actual_reasoning_effort", "input_tokens", "cached_input_tokens",
        "output_tokens", "duration_ms", "retry_cycle_id",
    }
)

@dataclass(frozen=True)
class SpawnEnvelope:
    schema_version: int
    event_id: str
    task_id: str
    run_id: str
    dispatch_id: str
    role: str
    role_instance_id: str
    session_id: str
    pr_id: str | None
    requested_model: str
    actual_model: str
    requested_reasoning_effort: str
    actual_reasoning_effort: str
    input_tokens: TokenMetric
    cached_input_tokens: TokenMetric
    output_tokens: TokenMetric
    duration_ms: int
    retry_cycle_id: str

@dataclass(frozen=True)
class SpawnUsageAggregate:
    known_token_total: int
    unknown_token_fields: tuple[str, ...]


@dataclass(frozen=True)
class PrReconciliation:
    schema_version: int
    task_id: str
    run_id: str
    pr_id: str
    known_token_total: int
    unknown_token_fields: tuple[str, ...]
    quality: ReconciliationQuality | None = None
    role_effort_breakdown: tuple[RoleEffortAggregate, ...] = ()

def parse_spawn_envelope(value: object) -> SpawnEnvelope:
    fields = _mapping(value, "spawn envelope")
    _exact_fields(fields, ENVELOPE_FIELDS, "spawn envelope")
    if fields["schema_version"] != 1:
        raise SpawnTelemetryError("unsupported schema_version")
    return SpawnEnvelope(
        schema_version=1,
        event_id=_identifier(fields["event_id"], "event_id"),
        task_id=_identifier(fields["task_id"], "task_id"),
        run_id=_identifier(fields["run_id"], "run_id"),
        dispatch_id=_identifier(fields["dispatch_id"], "dispatch_id"),
        role=_text(fields["role"], "role"),
        role_instance_id=_identifier(fields["role_instance_id"], "role_instance_id"),
        session_id=_identifier(fields["session_id"], "session_id"),
        pr_id=_optional_identifier(fields["pr_id"], "pr_id"),
        requested_model=_text(fields["requested_model"], "requested_model"),
        actual_model=_text(fields["actual_model"], "actual_model"),
        requested_reasoning_effort=_text(
            fields["requested_reasoning_effort"], "requested_reasoning_effort"
        ),
        actual_reasoning_effort=_text(
            fields["actual_reasoning_effort"], "actual_reasoning_effort"
        ),
        input_tokens=_metric(fields["input_tokens"], "input_tokens"),
        cached_input_tokens=_metric(
            fields["cached_input_tokens"], "cached_input_tokens"
        ),
        output_tokens=_metric(fields["output_tokens"], "output_tokens"),
        duration_ms=_nonnegative_integer(fields["duration_ms"], "duration_ms"),
        retry_cycle_id=_identifier(fields["retry_cycle_id"], "retry_cycle_id"),
    )

def aggregate_spawn_usage(events: Iterable[SpawnEnvelope]) -> SpawnUsageAggregate:
    total = 0
    unknown: list[str] = []
    for event in events:
        for field in TOKEN_FIELDS:
            metric = getattr(event, field)
            if metric.value is None:
                unknown.append(f"{event.event_id}.{field}")
            else:
                total += metric.value
    return SpawnUsageAggregate(total, tuple(unknown))


class SpawnTelemetryStore:
    def __init__(self, events_path: Path) -> None:
        if not events_path.is_absolute() or ".." in events_path.parts:
            raise SpawnTelemetryError("telemetry path must be absolute and normalized")
        self.events_path = events_path
        self.reconciliations_path = events_path.with_name("pr-reconciliations.jsonl")

    def record(self, event: SpawnEnvelope) -> None:
        validated = parse_spawn_envelope(_serialize(event))
        with _exclusive_lock(self.events_path):
            existing = self.read_events()
            if any(item.event_id == validated.event_id for item in existing):
                raise SpawnTelemetryError("duplicate telemetry event_id")
            _append_durable(self.events_path, _serialize(validated))
            if validated not in self.read_events():
                raise SpawnTelemetryError("telemetry event was not durably persisted")

    def read_events(self) -> tuple[SpawnEnvelope, ...]:
        return tuple(parse_spawn_envelope(item) for item in _read_jsonl(self.events_path))

    def reconcile_pr(
        self,
        task_id: str,
        run_id: str,
        pr_id: str,
        *,
        quality: ReconciliationQuality | None = None,
    ) -> PrReconciliation:
        identifiers = (
            _identifier(task_id, "task_id"),
            _identifier(run_id, "run_id"),
            _identifier(pr_id, "pr_id"),
        )
        _validate_quality(quality)
        with _exclusive_lock(self.events_path):
            with _exclusive_lock(self.reconciliations_path):
                matching = _matching_reconciliation(
                    self.read_reconciliations(), task_id, run_id
                )
                if matching is not None:
                    _require_same_pr(matching, pr_id)
                    _require_same_quality(matching, quality)
                    return matching
                return self._record_reconciliation(*identifiers, quality)

    def read_reconciliations(self) -> tuple[PrReconciliation, ...]:
        return tuple(_parse_reconciliation(item) for item in _read_jsonl(self.reconciliations_path))

    def _record_reconciliation(
        self,
        task_id: str,
        run_id: str,
        pr_id: str,
        quality: ReconciliationQuality | None,
    ) -> PrReconciliation:
        events = tuple(
            event for event in self.read_events()
            if event.task_id == task_id and event.run_id == run_id
        )
        if not events:
            raise SpawnTelemetryError("no telemetry events for task run")
        usage = aggregate_spawn_usage(events)
        record = PrReconciliation(
            1, task_id, run_id, pr_id,
            usage.known_token_total, usage.unknown_token_fields,
            quality, aggregate_role_effort(events),
        )
        _append_durable(self.reconciliations_path, _serialize(record))
        return record

def _metric(value: object, name: str) -> TokenMetric:
    fields = _mapping(value, name)
    _exact_fields(fields, frozenset({"value", "unavailable_reason"}), name)
    metric_value = fields["value"]
    reason = fields["unavailable_reason"]
    if metric_value is None:
        return TokenMetric(None, _text(reason, name))
    if type(metric_value) is not int or metric_value < 0 or reason is not None:
        raise SpawnTelemetryError(f"{name} must be a value or null-with-reason")
    return TokenMetric(metric_value, None)

def _mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise SpawnTelemetryError(f"{name} must be an object")
    return value

def _exact_fields(
    fields: dict[str, Any], expected: frozenset[str], name: str
) -> None:
    if fields.keys() != expected:
        raise SpawnTelemetryError(f"{name} has missing or unknown fields")

def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise SpawnTelemetryError(f"{name} must be normalized text")
    return value

def _identifier(value: object, name: str) -> str:
    text = _text(value, name)
    if not IDENTIFIER.fullmatch(text):
        raise SpawnTelemetryError(f"{name} must be a stable identifier")
    return text

def _optional_identifier(value: object, name: str) -> str | None:
    return None if value is None else _identifier(value, name)

def _nonnegative_integer(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise SpawnTelemetryError(f"{name} must be a nonnegative integer")
    return value

def _serialize(value: object) -> dict[str, Any]:
    return asdict(value)

def _parse_reconciliation(value: object) -> PrReconciliation:
    return parse_reconciliation(value)

def _matching_reconciliation(
    records: tuple[PrReconciliation, ...], task_id: str, run_id: str
) -> PrReconciliation | None:
    return next(
        (
            record for record in records
            if record.task_id == task_id and record.run_id == run_id
        ),
        None,
    )

def _require_same_pr(record: PrReconciliation, pr_id: str) -> None:
    if record.pr_id != pr_id:
        raise SpawnTelemetryError("task run already reconciled to another PR")


def _validate_quality(quality: ReconciliationQuality | None) -> None:
    validate_quality(quality)


def _require_same_quality(
    record: PrReconciliation, quality: ReconciliationQuality | None
) -> None:
    require_same_quality(record, quality)


try:
    from .spawn_telemetry_quality import (
        ReconciliationQuality,
        RoleEffortAggregate,
        aggregate_role_effort,
        parse_reconciliation,
        require_same_quality,
        validate_quality,
    )
except ImportError:
    from spawn_telemetry_quality import (
        ReconciliationQuality,
        RoleEffortAggregate,
        aggregate_role_effort,
        parse_reconciliation,
        require_same_quality,
        validate_quality,
    )

try:
    from .spawn_telemetry_io import _append_durable, _exclusive_lock, _read_jsonl
except ImportError:
    from spawn_telemetry_io import _append_durable, _exclusive_lock, _read_jsonl
