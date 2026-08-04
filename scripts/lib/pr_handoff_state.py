"""Typed, durable state for one task's pull-request handoff."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path

from scripts.lib.pipeline_state_paths import PipelineStatePathError, canonical_pipeline_path
from scripts.lib.writer_claim_io import open_harness_data, open_optional_regular, read_json, write_json


class PrHandoffError(ValueError):
    """Raised when PR handoff state or identity cannot be trusted."""


@dataclass(frozen=True)
class PullRequestContext:
    task_id: str
    run_id: str
    repository: str
    branch: str
    base_head: str
    target_head: str
    title: str
    body: str


@dataclass(frozen=True)
class ExistingPullRequest:
    repository: str
    task_id: str
    run_id: str
    branch: str
    base_head: str
    target_head: str
    number: int
    url: str


@dataclass(frozen=True)
class PrHandoffState:
    schema_version: int
    task_id: str
    run_id: str
    repository: str
    branch: str
    base_head: str
    target_head: str
    attempt_count: int
    outcome: str
    updated_at: str
    pr_number: int | None
    pr_url: str | None
    title: str
    body: str
    failure_category: str | None
    retry_authorized_by: str | None
    retry_authorized_at: str | None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class PrHandoffStore:
    """Read and atomically write one task's PR handoff state."""

    def __init__(self, task_id: str, harness_data: Path | None = None) -> None:
        try:
            path = canonical_pipeline_path(task_id, harness_data).with_name("pr-handoff.json")
        except PipelineStatePathError as error:
            raise PrHandoffError(str(error)) from error
        self.path = path

    def read(self) -> PrHandoffState:
        parent, name = self._open_parent()
        try:
            value = _read_json(parent, name)
        finally:
            os.close(parent)
        return parse_state(value)

    def read_optional(self) -> PrHandoffState | None:
        try:
            return self.read()
        except PrHandoffError as error:
            return _optional_state(error)

    def write(self, state: PrHandoffState) -> None:
        validated = parse_state(state.as_dict())
        parent, name = self._open_parent(create=True)
        try:
            _write_state(parent, name, validated)
        finally:
            os.close(parent)

    def _open_parent(self, create: bool = False) -> tuple[int, str]:
        try:
            parent = open_harness_data(self.path.parent, create=create)
        except FileNotFoundError as error:
            raise _parent_error(create) from error
        except OSError as error:
            raise PrHandoffError("PR handoff state parent is untrusted") from error
        return parent, self.path.name


def _parent_error(create: bool) -> PrHandoffError:
    if not create:
        return PrHandoffError("PR handoff state is missing")
    return PrHandoffError("PR handoff state parent is untrusted")


def parse_state(value: object) -> PrHandoffState:
    from scripts.lib.pr_handoff_validation import validate_state

    _require_mapping(value)
    _require_state_fields(value)
    return _validated_state(value, validate_state)


def _validated_state(value, validate):
    state = _construct_state(value)
    validate(state)
    return state


def _read_json(parent: int, name: str) -> dict[str, object]:
    try:
        return read_json(parent, name)
    except FileNotFoundError as error:
        raise PrHandoffError("PR handoff state is missing") from error
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise PrHandoffError("PR handoff state is invalid JSON") from error


def _write_state(parent: int, name: str, state: PrHandoffState) -> None:
    _require_safe_target(parent, name)
    try:
        write_json(parent, name, state.as_dict())
    except OSError as error:
        raise PrHandoffError("PR handoff state write failed") from error


def _optional_state(error: PrHandoffError) -> PrHandoffState | None:
    if str(error) == "PR handoff state is missing":
        return None
    raise error


def _require_mapping(value: object) -> None:
    if not isinstance(value, dict):
        raise PrHandoffError("PR handoff state must be an object")


def _require_state_fields(value: dict[str, object]) -> None:
    expected = set(PrHandoffState.__dataclass_fields__)
    if set(value) != expected:
        raise PrHandoffError("PR handoff state has missing or unknown fields")


def _construct_state(value: dict[str, object]) -> PrHandoffState:
    try:
        return PrHandoffState(**value)
    except TypeError as error:
        raise PrHandoffError("PR handoff state fields are malformed") from error


def _require_safe_target(parent: int, name: str) -> None:
    try:
        descriptor = open_optional_regular(parent, name)
    except OSError as error:
        raise PrHandoffError("PR handoff state target is unsafe") from error
    if descriptor is not None:
        os.close(descriptor)


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


def replace_state(state: PrHandoffState, **changes: object) -> PrHandoffState:
    values = state.as_dict()
    values.update(changes)
    return parse_state(values)


def carry_retry_authorization(
    state: PrHandoffState, previous: PrHandoffState | None
) -> PrHandoffState:
    if previous is None or previous.retry_authorized_by is None:
        return state
    return replace_state(
        state,
        retry_authorized_by=previous.retry_authorized_by,
        retry_authorized_at=previous.retry_authorized_at,
    )
