from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts" / "lib"))

from builder_guardian_evidence import (  # noqa: E402
    BuilderGuardianEvidenceError,
    parse_builder_guardian_verification,
)


def evidence(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "task_id": "t25-builder-guardian",
        "run_id": "run-01",
        "repository": "/repo",
        "worktree": "/repo/.claude/worktrees/t25",
        "approved_commit": "a" * 40,
        "timestamp": "2026-08-05T10:00:00+00:00",
        "commands": [
            {"name": "unit", "command": "true", "exit_code": 0, "output": ""},
        ],
        "status": "PASSED",
        "sandbox_run": True,
    }
    value.update(overrides)
    return value


def test_builder_guardian_verification_uses_shared_evidence_type() -> None:
    parsed = parse_builder_guardian_verification(evidence())

    assert parsed.shared.git_head == "a" * 40
    assert parsed.shared.verdict == "VERIFIED"
    assert parsed.shared.tier_results[0].status == "PASS"


def test_builder_guardian_rejects_failed_shared_evidence() -> None:
    failed = evidence(
        status="FAILED",
        commands=[{"name": "unit", "command": "false", "exit_code": 1, "output": "boom"}],
    )

    parsed = parse_builder_guardian_verification(failed)

    assert parsed.shared.verdict == "UNVERIFIED"
    assert parsed.shared.tier_results[0].status == "FAIL"
    assert not parsed.is_ready(expected_commands=["false"])


def test_builder_guardian_preserves_identity_adapter_fields() -> None:
    parsed = parse_builder_guardian_verification(evidence())

    assert parsed.task_id == "t25-builder-guardian"
    assert parsed.run_id == "run-01"
    assert parsed.repository == Path("/repo")
    assert parsed.worktree == Path("/repo/.claude/worktrees/t25")
    assert parsed.approved_commit == "a" * 40


def test_builder_guardian_rejects_invalid_shared_verification_shape() -> None:
    with pytest.raises(BuilderGuardianEvidenceError):
        parse_builder_guardian_verification(evidence(commands=[]))


def test_builder_guardian_rejects_boolean_exit_codes() -> None:
    with pytest.raises(BuilderGuardianEvidenceError):
        parse_builder_guardian_verification(
            evidence(commands=[{"name": "unit", "command": "true", "exit_code": True, "output": ""}])
        )


def test_builder_guardian_preserves_nullable_command_names() -> None:
    parsed = parse_builder_guardian_verification(
        evidence(commands=[{"name": None, "command": "true", "exit_code": 0, "output": ""}])
    )

    assert parsed.is_ready(expected_commands=["true"])


def test_builder_guardian_wraps_malformed_shared_evidence() -> None:
    with pytest.raises(BuilderGuardianEvidenceError):
        parse_builder_guardian_verification(evidence(sandbox_run="yes"))
