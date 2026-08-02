"""Validate and atomically persist fresh verification evidence."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import re
from typing import Any

from scripts.lib.writer_claim_io import (
    open_harness_data,
    open_optional_regular,
    write_json,
)


class VerificationEvidenceError(ValueError):
    """Raised when verification evidence is incomplete or stale."""


IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
GIT_HEAD = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
STATUSES = frozenset({"PASS", "FAIL", "SKIP", "N/A"})
VERDICTS = frozenset({"VERIFIED", "VERIFIED_WITH_SKIP", "UNVERIFIED"})
EVIDENCE_FIELDS = frozenset(
    {
        "schema_version", "task_id", "git_head", "generated_at", "verdict",
        "tier_results", "sandbox_run",
    }
)
TIER_FIELDS = frozenset({"tier", "status"})


@dataclass(frozen=True)
class TierResult:
    tier: int
    status: str


@dataclass(frozen=True)
class VerificationEvidence:
    schema_version: int
    task_id: str
    git_head: str
    generated_at: str
    verdict: str
    tier_results: tuple[TierResult, ...]
    sandbox_run: bool


def parse_verification_evidence(value: object) -> VerificationEvidence:
    fields = _mapping(value, "verification evidence")
    _exact_fields(fields, EVIDENCE_FIELDS, "verification evidence")
    if fields["schema_version"] != 1:
        raise VerificationEvidenceError("unsupported schema_version")
    evidence = _build_evidence(fields)
    _validate_verdict(evidence)
    return evidence


def serialize_verification_evidence(
    evidence: VerificationEvidence,
) -> dict[str, Any]:
    value = asdict(evidence)
    value["tier_results"] = [asdict(result) for result in evidence.tier_results]
    return value


def _build_evidence(fields: dict[str, Any]) -> VerificationEvidence:
    return VerificationEvidence(
        1, _identifier(fields["task_id"], "task_id"),
        _head(fields["git_head"], "git_head"),
        _timestamp(fields["generated_at"]),
        _choice(fields["verdict"], VERDICTS, "verdict"),
        _tier_results(fields["tier_results"]),
        _boolean(fields["sandbox_run"], "sandbox_run"),
    )


def write_verification_evidence(
    path: Path,
    evidence: VerificationEvidence,
    *,
    review_head: str,
    current_head: str,
    worktree_clean: bool,
) -> None:
    validated = parse_verification_evidence(serialize_verification_evidence(evidence))
    _require_freshness(validated, review_head, current_head, worktree_clean)
    _atomic_write(path, serialize_verification_evidence(validated))


def read_verification_evidence(path: Path) -> VerificationEvidence:
    parent, name = _open_target_parent(path)
    try:
        value = _read_value(parent, name)
    finally:
        os.close(parent)
    return parse_verification_evidence(value)


def _require_freshness(
    evidence: VerificationEvidence,
    review_head: str,
    current_head: str,
    worktree_clean: bool,
) -> None:
    if type(worktree_clean) is not bool or not worktree_clean:
        raise VerificationEvidenceError("worktree must be clean")
    approved_head = _head(review_head, "review HEAD")
    actual_head = _head(current_head, "current HEAD")
    if evidence.git_head != approved_head:
        raise VerificationEvidenceError("evidence does not match review HEAD")
    if evidence.git_head != actual_head:
        raise VerificationEvidenceError("evidence does not match current HEAD")


def _read_value(parent: int, name: str) -> dict[str, Any]:
    try:
        descriptor = open_optional_regular(parent, name)
        if descriptor is None:
            raise VerificationEvidenceError("verification evidence is missing")
        return _load_json(descriptor)
    except OSError as error:
        raise VerificationEvidenceError("verification evidence target must be regular") from error


def _load_json(descriptor: int) -> dict[str, Any]:
    with os.fdopen(descriptor, encoding="utf-8") as stream:
        try:
            value = json.load(stream)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise VerificationEvidenceError("verification evidence is invalid JSON") from error
    return _mapping(value, "verification evidence")


def _atomic_write(path: Path, value: dict[str, Any]) -> None:
    parent, name = _open_target_parent(path)
    try:
        _reject_nonregular_target(parent, name)
        write_json(parent, name, value)
    except OSError as error:
        raise VerificationEvidenceError("verification evidence atomic write failed") from error
    finally:
        os.close(parent)


def _open_target_parent(path: Path) -> tuple[int, str]:
    _validate_evidence_path(path)
    try:
        parent = open_harness_data(path.parent, create=False)
    except (OSError, ValueError) as error:
        raise VerificationEvidenceError("evidence parent must be a trusted directory") from error
    return parent, path.name


def _validate_evidence_path(path: Path) -> None:
    if not path.is_absolute() or ".." in path.parts or not path.name:
        raise VerificationEvidenceError("evidence path must be absolute and normalized")


def _reject_nonregular_target(parent: int, name: str) -> None:
    try:
        descriptor = open_optional_regular(parent, name)
    except OSError as error:
        raise VerificationEvidenceError("verification evidence target must be regular") from error
    if descriptor is not None:
        os.close(descriptor)


def _tier_results(value: object) -> tuple[TierResult, ...]:
    if not isinstance(value, list) or not value:
        raise VerificationEvidenceError("tier_results must be a non-empty list")
    results = tuple(_tier_result(item) for item in value)
    if len({result.tier for result in results}) != len(results):
        raise VerificationEvidenceError("tier numbers must be unique")
    return results


def _tier_result(value: object) -> TierResult:
    fields = _mapping(value, "tier result")
    _exact_fields(fields, TIER_FIELDS, "tier result")
    tier = fields["tier"]
    if type(tier) is not int or tier < 0:
        raise VerificationEvidenceError("tier must be a nonnegative integer")
    return TierResult(tier, _choice(fields["status"], STATUSES, "tier status"))


def _validate_verdict(evidence: VerificationEvidence) -> None:
    _reject_verified_failure(evidence)
    _require_skip_for_partial_verdict(evidence)


def _reject_verified_failure(evidence: VerificationEvidence) -> None:
    failed = any(result.status == "FAIL" for result in evidence.tier_results)
    if evidence.verdict == "VERIFIED" and failed:
        raise VerificationEvidenceError("VERIFIED cannot contain a failed tier")


def _require_skip_for_partial_verdict(evidence: VerificationEvidence) -> None:
    skipped = any(result.status == "SKIP" for result in evidence.tier_results)
    if evidence.verdict == "VERIFIED_WITH_SKIP" and not skipped:
        raise VerificationEvidenceError("VERIFIED_WITH_SKIP requires a skipped tier")


def _mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise VerificationEvidenceError(f"{name} must be an object")
    return value


def _exact_fields(
    fields: dict[str, Any], expected: frozenset[str], name: str
) -> None:
    missing = expected - fields.keys()
    unknown = fields.keys() - expected
    if missing:
        raise VerificationEvidenceError(f"missing required field: {min(missing)}")
    if unknown:
        raise VerificationEvidenceError(f"unknown field in {name}: {min(unknown)}")


def _identifier(value: object, name: str) -> str:
    text = _text(value, name)
    if not IDENTIFIER.fullmatch(text):
        raise VerificationEvidenceError(f"{name} must be a stable identifier")
    return text


def _head(value: object, name: str) -> str:
    text = _text(value, name)
    if not GIT_HEAD.fullmatch(text):
        raise VerificationEvidenceError(f"{name} must be a full Git object ID")
    return text


def _timestamp(value: object) -> str:
    text = _text(value, "generated_at")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise VerificationEvidenceError("generated_at must be ISO-8601") from error
    if parsed.tzinfo is None:
        raise VerificationEvidenceError("generated_at must include timezone")
    return text


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise VerificationEvidenceError(f"{name} must be normalized text")
    if any(ord(character) < 32 for character in value):
        raise VerificationEvidenceError(f"{name} contains control characters")
    return value


def _choice(value: object, choices: frozenset[str], name: str) -> str:
    text = _text(value, name)
    if text not in choices:
        raise VerificationEvidenceError(f"unsupported {name}")
    return text


def _boolean(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise VerificationEvidenceError(f"{name} must be a boolean")
    return value
