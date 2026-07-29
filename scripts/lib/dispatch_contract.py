"""Validate and serialize standalone role dispatch contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
import re
from typing import Any


class DispatchContractError(ValueError):
    """Raised when a dispatch contract cannot be trusted."""


ROLES = frozenset(
    {
        "orchestrator",
        "software_engineer",
        "code_reviewer",
        "security_reviewer",
        "verifier",
    }
)
READ_ONLY_ROLES = frozenset({"code_reviewer", "security_reviewer", "verifier"})
RISKS = frozenset({"Small Change", "Build", "High Risk"})
EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max", "ultra"})
WRITE_AUTHORITY = {
    "orchestrator": "coordination_only",
    "software_engineer": "task_scope",
    "code_reviewer": "none",
    "security_reviewer": "none",
    "verifier": "none",
}
FILESYSTEM_PERMISSION = {
    "orchestrator": "read-only",
    "software_engineer": "workspace-write",
    "code_reviewer": "read-only",
    "security_reviewer": "read-only",
    "verifier": "read-only",
}
CONTRACT_FIELDS = frozenset(
    {
        "schema_version",
        "dispatch_id",
        "task_id",
        "repository",
        "branch",
        "worktree",
        "base_head",
        "target_head",
        "allowed_paths",
        "prohibited_paths",
        "acceptance_criteria",
        "required_tests",
        "risk",
        "role",
        "role_instance_id",
        "session_id",
        "requested_model",
        "requested_reasoning_effort",
        "write_authority",
        "permissions",
    }
)
PERMISSION_FIELDS = frozenset({"filesystem", "network", "tools"})
IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
GIT_HEAD = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")


@dataclass(frozen=True)
class DispatchPermissions:
    filesystem: str
    network: str
    tools: str


@dataclass(frozen=True)
class DispatchContract:
    schema_version: int
    dispatch_id: str
    task_id: str
    repository: Path
    branch: str
    worktree: Path
    base_head: str
    target_head: str
    allowed_paths: tuple[str, ...]
    prohibited_paths: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    required_tests: tuple[str, ...]
    risk: str
    role: str
    role_instance_id: str
    session_id: str
    requested_model: str
    requested_reasoning_effort: str
    write_authority: str
    permissions: DispatchPermissions


def parse_dispatch_contract(value: object) -> DispatchContract:
    fields = _require_mapping(value, "dispatch contract")
    _require_exact_fields(fields, CONTRACT_FIELDS, "dispatch contract")
    _require_version(fields["schema_version"])
    role = _require_choice(fields["role"], ROLES, "role")
    contract = _build_contract(fields, role)
    _validate_role_invariants(contract)
    return contract


def serialize_dispatch_contract(contract: DispatchContract) -> dict[str, Any]:
    serialized = asdict(contract)
    serialized["repository"] = str(contract.repository)
    serialized["worktree"] = str(contract.worktree)
    for field in _SEQUENCE_FIELDS:
        serialized[field] = list(getattr(contract, field))
    return serialized


def _build_contract(fields: dict[str, Any], role: str) -> DispatchContract:
    scalar = _validated_scalars(fields)
    return DispatchContract(
        schema_version=1,
        role=role,
        permissions=_parse_permissions(fields["permissions"]),
        **scalar,
    )


def _validated_scalars(fields: dict[str, Any]) -> dict[str, Any]:
    values = {name: _require_text(fields[name], name) for name in _TEXT_FIELDS}
    values.update({name: _require_identifier(fields[name], name) for name in _IDENTIFIER_FIELDS})
    values.update({name: _require_sequence(fields[name], name) for name in _SEQUENCE_FIELDS})
    values["repository"] = _require_absolute_path(fields["repository"], "repository")
    values["worktree"] = _require_absolute_path(fields["worktree"], "worktree")
    values["base_head"] = _require_head(fields["base_head"], "base_head")
    values["target_head"] = _require_head(fields["target_head"], "target_head")
    values["risk"] = _require_choice(fields["risk"], RISKS, "risk")
    values["requested_reasoning_effort"] = _require_choice(
        fields["requested_reasoning_effort"], EFFORTS, "requested_reasoning_effort"
    )
    _validate_relative_paths(values["allowed_paths"], "allowed_paths")
    _validate_relative_paths(values["prohibited_paths"], "prohibited_paths")
    _reject_path_overlap(values["allowed_paths"], values["prohibited_paths"])
    return values


def _parse_permissions(value: object) -> DispatchPermissions:
    fields = _require_mapping(value, "permissions")
    _require_exact_fields(fields, PERMISSION_FIELDS, "permissions")
    return DispatchPermissions(
        filesystem=_require_choice(
            fields["filesystem"], {"read-only", "workspace-write"}, "permissions.filesystem"
        ),
        network=_require_choice(
            fields["network"], {"disabled", "task_required"}, "permissions.network"
        ),
        tools=_require_choice(fields["tools"], {"none", "task_required"}, "permissions.tools"),
    )


def _validate_role_invariants(contract: DispatchContract) -> None:
    if not contract.role_instance_id.startswith(f"{contract.role}-"):
        raise DispatchContractError("role_instance_id must be bound to role")
    if contract.write_authority != WRITE_AUTHORITY[contract.role]:
        _raise_authority_error(contract.role)
    expected_filesystem = FILESYSTEM_PERMISSION[contract.role]
    if contract.permissions.filesystem != expected_filesystem:
        raise DispatchContractError(f"{contract.role} filesystem permission is contradictory")
    if contract.role in READ_ONLY_ROLES and contract.permissions.tools != "none":
        raise DispatchContractError("read-only role cannot receive task tools")


def _raise_authority_error(role: str) -> None:
    if role in READ_ONLY_ROLES:
        raise DispatchContractError("read-only role cannot claim write authority")
    raise DispatchContractError(f"{role} write authority is contradictory")


def _require_mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise DispatchContractError(f"{name} must be an object")
    return value


def _require_exact_fields(
    fields: dict[str, Any], expected: frozenset[str], name: str
) -> None:
    missing = expected - fields.keys()
    unknown = fields.keys() - expected
    if missing:
        raise DispatchContractError(f"missing required field: {min(missing)}")
    if unknown:
        raise DispatchContractError(f"unknown field in {name}: {min(unknown)}")


def _require_version(value: object) -> None:
    if type(value) is not int or value != 1:
        raise DispatchContractError("unsupported schema_version")


def _require_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise DispatchContractError(f"{name} must be non-empty normalized text")
    if any(ord(character) < 32 for character in value):
        raise DispatchContractError(f"{name} contains control characters")
    return value


def _require_identifier(value: object, name: str) -> str:
    text = _require_text(value, name)
    if not IDENTIFIER.fullmatch(text):
        raise DispatchContractError(f"{name} must be a stable identifier")
    return text


def _require_choice(value: object, choices: set[str] | frozenset[str], name: str) -> str:
    text = _require_text(value, name)
    if text not in choices:
        raise DispatchContractError(f"unsupported {name}")
    return text


def _require_absolute_path(value: object, name: str) -> Path:
    text = _require_text(value, name)
    path = Path(text)
    if not path.is_absolute() or ".." in path.parts:
        raise DispatchContractError(f"{name} must be an absolute normalized path")
    return path


def _require_head(value: object, name: str) -> str:
    text = _require_text(value, name)
    if not GIT_HEAD.fullmatch(text):
        raise DispatchContractError(f"{name} must be a full Git object ID")
    return text


def _require_sequence(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise DispatchContractError(f"{name} must be a non-empty list")
    items = tuple(_require_text(item, name) for item in value)
    if len(items) != len(set(items)):
        raise DispatchContractError(f"{name} must not contain duplicates")
    return items


def _validate_relative_paths(paths: tuple[str, ...], name: str) -> None:
    for value in paths:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or path == PurePosixPath("."):
            raise DispatchContractError(f"{name} must contain safe repository-relative paths")


def _reject_path_overlap(allowed: tuple[str, ...], prohibited: tuple[str, ...]) -> None:
    if set(allowed) & set(prohibited):
        raise DispatchContractError("allowed_paths and prohibited_paths overlap")


_TEXT_FIELDS = (
    "branch",
    "requested_model",
    "write_authority",
)
_IDENTIFIER_FIELDS = ("dispatch_id", "task_id", "role_instance_id", "session_id")
_SEQUENCE_FIELDS = (
    "allowed_paths",
    "prohibited_paths",
    "acceptance_criteria",
    "required_tests",
)
