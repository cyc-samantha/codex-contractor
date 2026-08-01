"""Trusted Git change probes for security-review transitions."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import subprocess

from scripts.lib.security_review_types import (
    ChangeEvidence,
    SecurityReviewError,
    head,
    repository,
    safe_path,
)


def collect_git_change_evidence(
    repo: Path, base_head: str, new_head: str
) -> ChangeEvidence:
    repository(repo)
    head(base_head, "base_head")
    head(new_head, "new_head")
    if base_head == new_head:
        raise SecurityReviewError("change evidence requires a new HEAD")
    try:
        result = subprocess.run(
            [
                "git", "-C", str(repo), "diff", "--name-only", "--no-renames",
                "--no-ext-diff", f"{base_head}..{new_head}",
            ],
            check=False, capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SecurityReviewError("Git change probe failed") from error
    if result.returncode != 0:
        raise SecurityReviewError("Git change probe returned an error")
    paths = tuple(sorted(result.stdout.splitlines()))
    evidence = ChangeEvidence(base_head, new_head, paths, change_path_digest(paths))
    validate_change_evidence(evidence)
    return evidence


def change_path_digest(paths: tuple[str, ...]) -> str:
    return sha256("\n".join(paths).encode("utf-8")).hexdigest()


def validate_change_evidence(evidence: ChangeEvidence) -> None:
    if not isinstance(evidence, ChangeEvidence):
        raise SecurityReviewError("change evidence has invalid type")
    head(evidence.base_head, "base_head")
    head(evidence.new_head, "new_head")
    if evidence.base_head == evidence.new_head or not evidence.changed_paths:
        raise SecurityReviewError("change evidence is empty or unchanged")
    paths = tuple(safe_path(path) for path in evidence.changed_paths)
    if paths != tuple(sorted(set(paths))):
        raise SecurityReviewError("change evidence paths are not canonical")
    if evidence.path_digest != change_path_digest(paths):
        raise SecurityReviewError("change evidence digest mismatch")
