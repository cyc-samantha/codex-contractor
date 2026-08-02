from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

from scripts.lib.verification_evidence import (  # noqa: E402
    VerificationEvidenceError,
    parse_verification_evidence,
    read_verification_evidence,
    serialize_verification_evidence,
    write_verification_evidence,
)


def evidence(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": 1,
        "task_id": "t18-verification",
        "git_head": "b" * 40,
        "generated_at": "2026-08-02T10:00:00+00:00",
        "verdict": "VERIFIED",
        "tier_results": [{"tier": 1, "status": "PASS"}],
        "sandbox_run": True,
    }
    value.update(overrides)
    return value


def test_verification_evidence_round_trips_required_fields() -> None:
    parsed = parse_verification_evidence(evidence())

    assert serialize_verification_evidence(parsed) == evidence()
    assert parsed.git_head == "b" * 40


@pytest.mark.parametrize(
    "override",
    [
        {"task_id": ""},
        {"schema_version": 2},
        {"verdict": "UNKNOWN"},
        {"tier_results": {}},
        {"extra": True},
    ],
)
def test_verification_evidence_rejects_missing_or_unknown_fields(
    override: dict[str, object],
) -> None:
    value = evidence()
    value.update(override)

    with pytest.raises(VerificationEvidenceError):
        parse_verification_evidence(value)


@pytest.mark.parametrize(
    "override",
    [
        {
            "verdict": "VERIFIED_WITH_SKIP",
            "tier_results": [
                {"tier": 1, "status": "FAIL"},
                {"tier": 2, "status": "SKIP"},
            ],
        },
        {"verdict": "VERIFIED", "tier_results": [{"tier": 1, "status": "SKIP"}]},
        {"sandbox_run": False},
    ],
)
def test_verification_evidence_rejects_false_positive_verified_verdicts(
    override: dict[str, object],
) -> None:
    value = evidence()
    value.update(override)

    with pytest.raises(VerificationEvidenceError):
        parse_verification_evidence(value)


def test_evidence_requires_review_and_worktree_head_match(tmp_path: Path) -> None:
    parsed = parse_verification_evidence(evidence())

    with pytest.raises(VerificationEvidenceError, match="review HEAD"):
        write_verification_evidence(
            tmp_path / "verification-evidence.json",
            parsed,
            review_head="a" * 40,
            current_head="b" * 40,
            worktree_clean=True,
        )

    with pytest.raises(VerificationEvidenceError, match="current HEAD"):
        write_verification_evidence(
            tmp_path / "verification-evidence.json",
            parsed,
            review_head="b" * 40,
            current_head="c" * 40,
            worktree_clean=True,
        )


def test_dirty_worktree_invalidates_verification_evidence(tmp_path: Path) -> None:
    parsed = parse_verification_evidence(evidence())

    with pytest.raises(VerificationEvidenceError, match="clean"):
        write_verification_evidence(
            tmp_path / "verification-evidence.json",
            parsed,
            review_head="b" * 40,
            current_head="b" * 40,
            worktree_clean=False,
        )


def test_evidence_writer_replaces_atomically_and_round_trips(tmp_path: Path) -> None:
    target = tmp_path / "verification-evidence.json"
    parsed = parse_verification_evidence(evidence())

    write_verification_evidence(
        target,
        parsed,
        review_head="b" * 40,
        current_head="b" * 40,
        worktree_clean=True,
    )

    assert parse_verification_evidence(json.loads(target.read_text())) == parsed


def test_context_bound_read_requires_fresh_heads_and_clean_worktree(tmp_path: Path) -> None:
    target = tmp_path / "verification-evidence.json"
    parsed = parse_verification_evidence(evidence())
    write_verification_evidence(
        target, parsed, review_head="b" * 40, current_head="b" * 40,
        worktree_clean=True,
    )

    assert read_verification_evidence(
        target, review_head="b" * 40, current_head="b" * 40,
        worktree_clean=True,
    ) == parsed
    with pytest.raises(VerificationEvidenceError, match="freshness"):
        read_verification_evidence(target, review_head="b" * 40)


def test_canonical_fixture_remains_compatible() -> None:
    fixture = Path(__file__).parent / "fixtures/pipeline-state/verification-evidence.json"

    parsed = parse_verification_evidence(json.loads(fixture.read_text()))

    assert parsed.task_id == "fixture-task-active"
    assert parsed.tier_results[0].status == "passed"


def test_evidence_writer_rejects_symlink_target(tmp_path: Path) -> None:
    target = tmp_path / "verification-evidence.json"
    original = tmp_path / "original.json"
    original.write_text("unchanged")
    target.symlink_to(original)

    with pytest.raises(VerificationEvidenceError, match="regular"):
        write_verification_evidence(
            target,
            parse_verification_evidence(evidence()),
            review_head="b" * 40,
            current_head="b" * 40,
            worktree_clean=True,
        )

    assert original.read_text() == "unchanged"
