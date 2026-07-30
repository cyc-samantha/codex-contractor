"""Closed write authority and activation proof for the orchestrator."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re

from scripts.lib.spawn_telemetry import SpawnTelemetryStore
from scripts.lib.writer_claim_io import (
    open_harness_data,
    open_optional_regular,
    read_json,
    write_json,
)


class OrchestratorWriteBoundaryError(ValueError):
    """Raised when orchestrator write authority cannot be proven."""


_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_ARTIFACTS = {
    "coordination": ("pipeline-state", "coordination.json"),
    "dispatch": ("pipeline-state", "dispatch"),
    "pr": ("pipeline-state", "pr.json"),
    "observation": ("learning", "observations"),
}
_ALLOWLIST_DIGEST = hashlib.sha256(
    json.dumps(_ARTIFACTS, sort_keys=True).encode()
).hexdigest()


@dataclass(frozen=True)
class _ActivationBinding:
    task_id: str
    run_id: str
    event_id: str
    allowlist_digest: str


class ActivationCapability:
    """Opaque capability issued only after durable canary verification."""

    def __init__(self, binding: _ActivationBinding, issuer: object) -> None:
        self._binding = binding
        self._issuer = issuer


class OrchestratorWriteBoundary:
    def __init__(self, harness_data: Path) -> None:
        if not harness_data.is_absolute() or ".." in harness_data.parts:
            raise OrchestratorWriteBoundaryError(
                "HARNESS_DATA must be absolute and normalized"
            )
        self._root = harness_data
        self._issuer = object()

    def write_artifact(
        self,
        kind: str,
        task_id: str,
        value: dict[str, object],
        name: str | None = None,
    ) -> Path:
        task = _identifier(task_id)
        components, filename = _artifact_location(kind, task, name)
        return self._write_file(components, filename, value)

    def _write_file(
        self,
        components: tuple[str, ...],
        filename: str,
        value: dict[str, object],
    ) -> Path:
        directory_path = self._root.joinpath(*components)
        directory = _open_directory(directory_path)
        try:
            _require_safe_target(directory, filename)
            write_json(directory, filename, value)
        except OrchestratorWriteBoundaryError:
            raise
        except OSError as error:
            raise OrchestratorWriteBoundaryError(
                "artifact path is not a safe regular file"
            ) from error
        finally:
            os.close(directory)
        return directory_path / filename

    def activate(
        self,
        task_id: str,
        run_id: str,
        event_id: str,
        telemetry: SpawnTelemetryStore,
    ) -> ActivationCapability:
        binding = _activation_binding(task_id, run_id, event_id)
        _require_canary(binding, telemetry)
        record = _activation_record(binding)
        path = self._write_file(
            ("pipeline-state", binding.task_id), "activation.json", record
        )
        if _read_record(path) != record:
            raise OrchestratorWriteBoundaryError(
                "activation record was not durably persisted"
            )
        return ActivationCapability(binding, self._issuer)

    def require_active(
        self,
        capability: object,
        task_id: str,
        run_id: str,
    ) -> None:
        if not isinstance(capability, ActivationCapability):
            raise OrchestratorWriteBoundaryError("activation capability required")
        if capability._issuer is not self._issuer:
            raise OrchestratorWriteBoundaryError("activation capability issuer mismatch")
        expected = (_identifier(task_id), _identifier(run_id), _ALLOWLIST_DIGEST)
        actual = (
            capability._binding.task_id,
            capability._binding.run_id,
            capability._binding.allowlist_digest,
        )
        if actual != expected:
            raise OrchestratorWriteBoundaryError("activation binding mismatch")


def _artifact_location(
    kind: str, task_id: str, name: str | None
) -> tuple[tuple[str, ...], str]:
    if kind not in _ARTIFACTS:
        raise OrchestratorWriteBoundaryError("unknown orchestrator artifact")
    if kind == "coordination":
        return ("pipeline-state", task_id), "coordination.json"
    if kind == "pr":
        return ("pipeline-state", task_id), "pr.json"
    if kind == "dispatch":
        artifact_name = _identifier(name)
        return ("pipeline-state", task_id, "dispatch"), f"{artifact_name}.json"
    return ("learning", "observations"), f"{task_id}.json"


def _identifier(value: object) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise OrchestratorWriteBoundaryError("artifact identifier is invalid")
    return value


def _open_directory(path: Path) -> int:
    try:
        return open_harness_data(path, create=True)
    except OSError as error:
        raise OrchestratorWriteBoundaryError(
            "artifact parent is not a safe directory"
        ) from error


def _require_safe_target(directory: int, filename: str) -> None:
    try:
        descriptor = open_optional_regular(directory, filename)
    except OSError as error:
        raise OrchestratorWriteBoundaryError(
            "artifact target must be a single-link regular file"
        ) from error
    if descriptor is None:
        return
    try:
        if os.fstat(descriptor).st_nlink != 1:
            raise OrchestratorWriteBoundaryError(
                "artifact target must be a single-link regular file"
            )
    finally:
        os.close(descriptor)


def _activation_binding(
    task_id: str, run_id: str, event_id: str
) -> _ActivationBinding:
    return _ActivationBinding(
        _identifier(task_id),
        _identifier(run_id),
        _identifier(event_id),
        _ALLOWLIST_DIGEST,
    )


def _require_canary(
    binding: _ActivationBinding, telemetry: SpawnTelemetryStore
) -> None:
    matches = tuple(
        event for event in telemetry.read_events()
        if (event.task_id, event.run_id, event.event_id)
        == (binding.task_id, binding.run_id, binding.event_id)
    )
    if len(matches) != 1:
        raise OrchestratorWriteBoundaryError(
            "durable correlated telemetry canary required"
        )


def _activation_record(binding: _ActivationBinding) -> dict[str, object]:
    return {
        "schema_version": 1,
        "task_id": binding.task_id,
        "run_id": binding.run_id,
        "event_id": binding.event_id,
        "allowlist_digest": binding.allowlist_digest,
    }


def _read_record(path: Path) -> dict[str, object]:
    directory = open_harness_data(path.parent, create=False)
    try:
        return read_json(directory, path.name)
    finally:
        os.close(directory)
