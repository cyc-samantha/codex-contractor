"""Independent Builder evidence checks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess

try:
    from .verification_evidence import (
        VerificationEvidence,
        VerificationEvidenceError,
        parse_verification_evidence,
    )
except ImportError:
    from verification_evidence import (
        VerificationEvidence,
        VerificationEvidenceError,
        parse_verification_evidence,
    )


class BuilderGuardianEvidenceError(ValueError):
    """Raised when the Builder-Guardian verification adapter is invalid."""


@dataclass(frozen=True)
class BuilderGuardianVerification:
    shared: VerificationEvidence
    task_id: str
    run_id: str
    repository: Path
    worktree: Path
    approved_commit: str
    commands: tuple[dict, ...]

    def is_ready(self, expected_commands: list[str]) -> bool:
        return self._has_expected_commands(expected_commands) and self._all_passed()

    def _has_expected_commands(self, expected: list[str]) -> bool:
        return [item["command"] for item in self.commands] == expected

    def _all_passed(self) -> bool:
        return self.shared.verdict == "VERIFIED" and all(item["exit_code"] == 0 for item in self.commands)


def parse_builder_guardian_verification(value: object) -> BuilderGuardianVerification:
    fields = _mapping(value)
    _require_fields(fields)
    commands = _commands(fields["commands"])
    shared = _shared_evidence(fields, commands)
    _require_identity(fields)
    return _verification(shared, fields, commands)


def _verification(
    shared: VerificationEvidence, fields: dict, commands: tuple[dict, ...]
) -> BuilderGuardianVerification:
    return BuilderGuardianVerification(
        shared, fields["task_id"], fields["run_id"], Path(fields["repository"]),
        Path(fields["worktree"]), fields["approved_commit"], commands,
    )


def _mapping(value: object) -> dict:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise BuilderGuardianEvidenceError("verification evidence must be an object")
    return value


def _require_fields(fields: dict) -> None:
    expected = {
        "task_id", "run_id", "repository", "worktree", "approved_commit",
        "timestamp", "commands", "status", "sandbox_run",
    }
    if fields.keys() != expected:
        raise BuilderGuardianEvidenceError("verification evidence fields are invalid")


def _commands(value: object) -> tuple[dict, ...]:
    if not isinstance(value, list) or not value:
        raise BuilderGuardianEvidenceError("verification commands are required")
    return _validated_commands(tuple(value))


def _validated_commands(commands: tuple[dict, ...]) -> tuple[dict, ...]:
    required = {"name", "command", "exit_code", "output"}
    if any(not isinstance(item, dict) or item.keys() != required for item in commands):
        raise BuilderGuardianEvidenceError("verification command shape is invalid")
    _validate_command_text(commands)
    _validate_exit_codes(commands)
    return commands


def _validate_command_text(commands: tuple[dict, ...]) -> None:
    if any(not isinstance(item["command"], str) or not item["command"] for item in commands):
        raise BuilderGuardianEvidenceError("verification command is invalid")
    if any(not isinstance(item["output"], str) for item in commands):
        raise BuilderGuardianEvidenceError("verification output is invalid")


def _validate_exit_codes(commands: tuple[dict, ...]) -> None:
    if any(_invalid_exit_code(item["exit_code"]) for item in commands):
        raise BuilderGuardianEvidenceError("verification exit code is invalid")


def _invalid_exit_code(value: object) -> bool:
    return value is not None and (type(value) is not int or value < 0)


def _require_identity(fields: dict) -> None:
    if not isinstance(fields["run_id"], str) or not fields["run_id"]:
        raise BuilderGuardianEvidenceError("verification run identity is invalid")
    for name in ("repository", "worktree"):
        _require_path_identity(fields[name], name)


def _require_path_identity(value: object, name: str) -> None:
    if not isinstance(value, str):
        raise BuilderGuardianEvidenceError(f"verification {name} is invalid")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise BuilderGuardianEvidenceError(f"verification {name} is invalid")


def _shared_evidence(fields: dict, commands: tuple[dict, ...]) -> VerificationEvidence:
    verdict = _shared_verdict(fields["status"])
    try:
        return parse_verification_evidence(_shared_payload(fields, commands, verdict))
    except (VerificationEvidenceError, TypeError, KeyError) as error:
        raise BuilderGuardianEvidenceError("shared verification evidence is invalid") from error


def _shared_verdict(status: object) -> str:
    if not isinstance(status, str) or status not in {"PASSED", "FAILED"}:
        raise BuilderGuardianEvidenceError("verification status is invalid")
    return "VERIFIED" if status == "PASSED" else "UNVERIFIED"


def _shared_payload(
    fields: dict, commands: tuple[dict, ...], verdict: str
) -> dict:
    tiers = [
        {"tier": index, "status": "PASS" if item["exit_code"] == 0 else "FAIL"}
        for index, item in enumerate(commands)
    ]
    return {
        "schema_version": 1,
        "task_id": fields["task_id"],
        "git_head": fields["approved_commit"],
        "generated_at": fields["timestamp"],
        "verdict": verdict,
        "tier_results": tiers,
        "sandbox_run": fields["sandbox_run"],
    }

from builder_guardian_state import StateError, git


def target_descends(repo: Path, base: str, target: str) -> bool:
    result = subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", base, target])
    return result.returncode == 0 and base != target


def branch_matches(worktree: Path, branch: str) -> bool:
    return git(worktree, "branch", "--show-current") == branch


def registered_worktree(repo: Path, worktree: Path, branch: str) -> bool:
    output = git(repo, "worktree", "list", "--porcelain")
    expected = f"worktree {worktree}\nHEAD "
    branch_line = f"branch refs/heads/{branch}"
    return any(block.startswith(expected) and branch_line in block.splitlines() for block in output.split("\n\n"))


def validate_test_paths(worktree: Path, tests: list[str], files: list[str]) -> None:
    if not tests or not set(tests) <= set(files):
        raise StateError("BLOCKED: changed tests are not in the review target")
    if any(not (worktree / path).is_file() for path in tests):
        raise StateError("BLOCKED: changed test path is missing")


def execute_check(check: dict, worktree: Path) -> dict:
    try:
        result = subprocess.run(["bash", "-lc", check["command"]], cwd=worktree, timeout=check.get("timeout_seconds", 600))
        return {"command": check["command"], "passed": result.returncode == 0}
    except subprocess.TimeoutExpired:
        return {"command": check["command"], "passed": False}


def execute_builder_checks(checks: list[dict], worktree: Path) -> list[dict]:
    results = [execute_check(check, worktree) for check in checks]
    if any(not result["passed"] for result in results):
        raise StateError("BLOCKED: Builder validation failed")
    if git(worktree, "status", "--porcelain"):
        raise StateError("BLOCKED: Builder checks changed the review target")
    return results
