"""Immutable repository and unified-hunk inspection for T18B."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess

from .llm_mutant_types import LlmMutantAdapterError


@dataclass(frozen=True)
class ChangedHunk:
    locations: frozenset[int]
    source_by_line: dict[int, tuple[str, ...]]


def canonical_diff(repository: Path, base_head: str, target_head: str) -> str:
    root = git(repository, "rev-parse", "--show-toplevel").resolve()
    if root != repository.resolve():
        raise LlmMutantAdapterError("repository identity mismatch")
    git(repository, "cat-file", "-e", f"{base_head}^{{commit}}")
    git(repository, "cat-file", "-e", f"{target_head}^{{commit}}")
    return git(
        repository, "diff", "--no-ext-diff", "--find-renames",
        f"{base_head}...{target_head}",
    )


def target_probe(repository: Path) -> tuple[str, bool]:
    head = git(repository, "rev-parse", "HEAD")
    clean = git(repository, "status", "--porcelain") == ""
    return head, clean


def changed_details(diff: str) -> dict[str, tuple[ChangedHunk, ...]]:
    details: dict[str, list[ChangedHunk]] = {}
    current: str | None = None
    hunk_locations: set[int] = set()
    hunk_source: dict[int, list[str]] = {}
    pending_removed: list[str] = []
    old_line = new_line = 0
    hunk = re.compile(
        r"^@@ -[0-9]+(?:,[0-9]+)? \+([0-9]+)(?:,[0-9]+)? @@"
    )
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            if current and hunk_locations:
                details[current].append(
                    ChangedHunk(
                        frozenset(hunk_locations),
                        {number: tuple(lines) for number, lines in hunk_source.items()},
                    )
                )
                hunk_locations = set()
                hunk_source = {}
                pending_removed = []
            current = line[6:]
            details.setdefault(current, [])
        elif line.startswith("@@") and current:
            if hunk_locations:
                details[current].append(
                    ChangedHunk(
                        frozenset(hunk_locations),
                        {number: tuple(lines) for number, lines in hunk_source.items()},
                    )
                )
            match = hunk.match(line)
            if not match:
                raise LlmMutantAdapterError("canonical diff hunk is malformed")
            old_match = re.search(r" -([0-9]+)", line)
            old_line = int(old_match.group(1)) if old_match else 0
            new_line = int(match.group(1))
            hunk_locations = set()
            hunk_source = {}
            pending_removed = []
        elif current and line.startswith("-") and not line.startswith("---"):
            pending_removed.append(line[1:])
            old_line += 1
        elif current and line.startswith("+") and not line.startswith("+++"):
            hunk_locations.add(new_line)
            hunk_source.setdefault(new_line, []).extend(pending_removed)
            hunk_source[new_line].append(line[1:])
            pending_removed = []
            new_line += 1
        elif current and line.startswith(" "):
            hunk_locations.add(new_line)
            hunk_source.setdefault(new_line, []).append(line[1:])
            old_line += 1
            new_line += 1
    if current and hunk_locations:
        details[current].append(
            ChangedHunk(
                frozenset(hunk_locations),
                {number: tuple(lines) for number, lines in hunk_source.items()},
            )
        )
    return {name: tuple(hunks) for name, hunks in details.items()}


def git(repository: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repository), *arguments],
            capture_output=True, text=True, check=True, timeout=10,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise LlmMutantAdapterError("bound Git inspection failed") from error
    return result.stdout.strip()
