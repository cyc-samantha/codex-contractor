"""Shared immutable types and validation primitives for security review."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import re


class SecurityReviewError(ValueError):
    """Raised when security sign-off cannot be trusted or applied."""


GIT_HEAD = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
VERDICTS = frozenset({"APPROVE", "CHANGES_REQUESTED"})
SENSITIVE_PATH_PREFIXES = (
    ".codex/hooks/",
    "scripts/codex-harness",
    "scripts/lib/code_review_dispatch.py",
    "scripts/lib/dispatch_contract.py",
    "scripts/lib/execution_policy.py",
    "scripts/lib/review_evidence.py",
    "scripts/lib/review_workflow.py",
    "scripts/lib/risk_routing.py",
    "scripts/lib/security_review.py",
    "scripts/lib/security_review_evidence.py",
    "scripts/lib/software_engineer_dispatch.py",
    "scripts/lib/spawn_telemetry.py",
)


@dataclass(frozen=True)
class ChangeEvidence:
    base_head: str
    new_head: str
    changed_paths: tuple[str, ...]
    path_digest: str


@dataclass(frozen=True)
class SecurityReviewApproval:
    task_id: str
    reviewer_id: str
    reviewer_session_id: str
    reviewer_model: str
    reviewed_head: str
    verdict: str
    dispatch_id: str
    run_id: str
    telemetry_event_id: str


def safe_path(value: object) -> str:
    text = text_value(value, "changed path")
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts or path == PurePosixPath("."):
        raise SecurityReviewError("changed path must be repository-relative")
    return str(path)


def is_sensitive(path: str) -> bool:
    return any(
        path == prefix.rstrip("/") or path.startswith(prefix.rstrip("/") + "/")
        for prefix in SENSITIVE_PATH_PREFIXES
    )


def head(value: object, name: str) -> str:
    text = text_value(value, name)
    if not GIT_HEAD.fullmatch(text):
        raise SecurityReviewError(f"{name} must be a full Git object ID")
    return text


def identifier(value: object, name: str) -> str:
    text = text_value(value, name)
    if not IDENTIFIER.fullmatch(text):
        raise SecurityReviewError(f"{name} must be a stable identifier")
    return text


def text_value(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise SecurityReviewError(f"{name} must be normalized text")
    if any(ord(character) < 32 for character in value):
        raise SecurityReviewError(f"{name} contains control characters")
    return value


def repository(value: object) -> None:
    if not isinstance(value, Path) or not value.is_absolute() or ".." in value.parts:
        raise SecurityReviewError("repository must be an absolute path")
