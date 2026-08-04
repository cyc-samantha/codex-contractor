from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import subprocess
import sys
import tomllib

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

from scripts.lib.dispatch_contract import (  # noqa: E402
    DispatchContractError,
    parse_dispatch_contract,
    serialize_dispatch_contract,
)


ROLES = (
    "orchestrator",
    "software_engineer",
    "code_reviewer",
    "security_reviewer",
    "verifier",
)
READ_ONLY_ROLES = {"code_reviewer", "security_reviewer", "verifier"}
REPO_ROOT = Path(
    subprocess.check_output(
        ["git", "rev-parse", "--show-toplevel"], text=True
    ).strip()
)


def contract_for(role: str) -> dict[str, object]:
    write_authority = {
        "orchestrator": "coordination_only",
        "software_engineer": "task_scope",
        "code_reviewer": "none",
        "security_reviewer": "none",
        "verifier": "none",
    }[role]
    filesystem = "workspace-write" if role == "software_engineer" else "read-only"
    return {
        "schema_version": 1,
        "dispatch_id": f"dispatch-{role}",
        "task_id": "t13-role-dispatch-contracts",
        "repository": "/srv/codex-harness",
        "branch": "build/t13-role-dispatch-contracts",
        "worktree": "/srv/codex-harness-wt",
        "base_head": "a" * 40,
        "target_head": "b" * 40,
        "allowed_paths": ["scripts/lib/dispatch_contract.py"],
        "prohibited_paths": [".env", ".git/**"],
        "acceptance_criteria": ["Complete contracts round-trip."],
        "required_tests": ["pytest -q tests/test_dispatch_contract.py"],
        "risk": "Build",
        "role": role,
        "role_instance_id": f"{role}-01",
        "session_id": f"session-{role}-01",
        "requested_model": "gpt-5.6-sol",
        "requested_reasoning_effort": "medium",
        "write_authority": write_authority,
        "permissions": {
            "filesystem": filesystem,
            "network": "disabled",
            "tools": "none" if role in READ_ONLY_ROLES else "task_required",
        },
    }


@pytest.mark.parametrize("role", ROLES)
def test_round_trips_each_version_one_role(role: str) -> None:
    parsed = parse_dispatch_contract(contract_for(role))

    assert parsed.role == role
    assert parse_dispatch_contract(serialize_dispatch_contract(parsed)) == parsed


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.pop("task_id"), "missing required field"),
        (lambda value: value.update(schema_version=2), "unsupported schema_version"),
        (lambda value: value.update(role="product_manager"), "unsupported role"),
        (lambda value: value.update(extra=True), "unknown field"),
        (lambda value: value.update(base_head="not-a-sha"), "base_head"),
        (lambda value: value.update(allowed_paths=[]), "allowed_paths"),
        (lambda value: value.update(repository="relative/repo"), "repository"),
    ],
)
def test_rejects_incomplete_unknown_and_malformed_contracts(
    mutation, message: str
) -> None:
    value = contract_for("software_engineer")
    mutation(value)

    with pytest.raises(DispatchContractError, match=message):
        parse_dispatch_contract(value)


def test_binds_stable_role_and_session_identity() -> None:
    value = contract_for("code_reviewer")
    value["role_instance_id"] = "software_engineer-01"

    with pytest.raises(DispatchContractError, match="role_instance_id"):
        parse_dispatch_contract(value)

    value = contract_for("code_reviewer")
    value["session_id"] = ""
    with pytest.raises(DispatchContractError, match="session_id"):
        parse_dispatch_contract(value)

    value = contract_for("code_reviewer")
    value["session_id"] = "session-software_engineer-01"
    with pytest.raises(DispatchContractError, match="session_id"):
        parse_dispatch_contract(value)


def test_binds_scope_git_risk_execution_and_verification() -> None:
    parsed = parse_dispatch_contract(contract_for("software_engineer"))

    assert parsed.repository == Path("/srv/codex-harness")
    assert parsed.base_head == "a" * 40
    assert parsed.target_head == "b" * 40
    assert parsed.allowed_paths == ("scripts/lib/dispatch_contract.py",)
    assert parsed.acceptance_criteria == ("Complete contracts round-trip.",)
    assert parsed.required_tests == ("pytest -q tests/test_dispatch_contract.py",)
    assert parsed.risk == "Build"
    assert parsed.requested_model == "gpt-5.6-sol"
    assert parsed.permissions.filesystem == "workspace-write"


@pytest.mark.parametrize("role", READ_ONLY_ROLES)
def test_rejects_contradictory_role_permissions(role: str) -> None:
    value = contract_for(role)
    value["write_authority"] = "task_scope"

    with pytest.raises(DispatchContractError, match="read-only role"):
        parse_dispatch_contract(value)


def test_rejects_engineer_paths_outside_contract() -> None:
    value = contract_for("software_engineer")
    value["allowed_paths"] = ["../outside"]

    with pytest.raises(DispatchContractError, match="allowed_paths"):
        parse_dispatch_contract(value)


def test_rejects_orchestrator_source_authority() -> None:
    value = contract_for("orchestrator")
    value["write_authority"] = "task_scope"

    with pytest.raises(DispatchContractError, match="orchestrator"):
        parse_dispatch_contract(value)


def test_implementation_plan_records_bundle_progress() -> None:
    plan = (
        REPO_ROOT / "docs" / "STANDALONE-CODEX-HARNESS-IMPLEMENTATION-PLAN.md"
    ).read_text()

    assert "| T10 | Complete |" in plan
    assert "| T11 | Complete |" in plan
    assert "| T12 | Complete |" in plan
    assert "| T13 | Complete |" in plan
    assert "| T13A | Complete |" in plan
    assert "| T13B-T13D | Complete |" in plan
    assert "| T14 | Complete |" in plan
    assert "| T15 | Complete |" in plan
    assert "| T16 | Complete |" in plan
    assert "| T17 | Complete |" in plan
    assert "| T18 | Complete |" in plan
    assert "| T18A | Complete |" in plan
    assert "| T18B | Complete |" in plan
    assert "| T19 | Complete |" in plan
    assert "| T20 | Complete |" in plan
    assert "| T21 | Complete |" in plan
    assert "merged in PR #41" in plan
    assert "boundary-issued capability" in plan


def test_rejects_duplicate_scope_entries() -> None:
    value = contract_for("software_engineer")
    value["required_tests"] = ["pytest -q", "pytest -q"]

    with pytest.raises(DispatchContractError, match="required_tests"):
        parse_dispatch_contract(value)


def test_rejects_unknown_permission_fields() -> None:
    value = contract_for("software_engineer")
    permissions = deepcopy(value["permissions"])
    assert isinstance(permissions, dict)
    permissions["shell"] = "unrestricted"
    value["permissions"] = permissions

    with pytest.raises(DispatchContractError, match="permissions"):
        parse_dispatch_contract(value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("dispatch_id", "dispatch with spaces"),
        ("task_id", "../task"),
        ("role_instance_id", "software_engineer-UPPER"),
        ("session_id", "session/child"),
    ],
)
def test_rejects_non_stable_identifiers(field: str, value: str) -> None:
    contract = contract_for("software_engineer")
    contract[field] = value

    with pytest.raises(DispatchContractError, match=field):
        parse_dispatch_contract(contract)


def test_rejects_paths_that_are_both_allowed_and_prohibited() -> None:
    contract = contract_for("software_engineer")
    contract["prohibited_paths"] = ["scripts/lib/dispatch_contract.py"]

    with pytest.raises(DispatchContractError, match="overlap"):
        parse_dispatch_contract(contract)


@pytest.mark.parametrize(
    ("allowed", "prohibited"),
    [
        ("scripts//lib/dispatch_contract.py", "scripts/lib/dispatch_contract.py"),
        ("scripts/lib/dispatch_contract.py", "scripts/**"),
        ("scripts/file.py", "scripts/**/*.py"),
        ("scripts/**/*.py", "scripts/lib/**"),
    ],
)
def test_rejects_canonical_or_pattern_scope_overlap(
    allowed: str, prohibited: str
) -> None:
    contract = contract_for("software_engineer")
    contract["allowed_paths"] = [allowed]
    contract["prohibited_paths"] = [prohibited]

    with pytest.raises(DispatchContractError, match="overlap"):
        parse_dispatch_contract(contract)


@pytest.mark.parametrize("role", ROLES)
def test_role_profiles_use_supported_custom_agent_fields(role: str) -> None:
    profile_path = REPO_ROOT / ".codex" / "agents" / f"{role.replace('_', '-')}.toml"
    profile = tomllib.loads(profile_path.read_text())

    assert profile["name"] == role
    assert profile["description"]
    assert profile["developer_instructions"]
    assert profile["sandbox_mode"] == FILESYSTEM_SANDBOX[role]


FILESYSTEM_SANDBOX = {
    "orchestrator": "read-only",
    "software_engineer": "workspace-write",
    "code_reviewer": "read-only",
    "security_reviewer": "read-only",
    "verifier": "read-only",
}
