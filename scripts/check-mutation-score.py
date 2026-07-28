#!/usr/bin/env python3
"""Fail when mutmut's killed-mutant ratio is below the required threshold."""

from __future__ import annotations

import sys

THRESHOLD_PERCENT = 70


def mutation_statuses(lines: list[str]) -> list[str]:
    return [line.rsplit(": ", 1)[-1].strip() for line in lines if ": " in line]


def main() -> int:
    statuses = mutation_statuses(sys.stdin.readlines())
    if not statuses or set(statuses) - {"killed", "survived"}:
        return fail_closed()
    killed = statuses.count("killed")
    score = killed * 100 / len(statuses)
    print(f"mutation score: {score:.1f}% ({killed}/{len(statuses)} killed)")
    return 0 if score >= THRESHOLD_PERCENT else 1


def fail_closed() -> int:
    print("mutation score unavailable or contains unsupported statuses", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
