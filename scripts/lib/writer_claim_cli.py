"""Command-line entry point for writer claims."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from writer_claim import ClaimError, WriterClaimManager


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("harness_data", type=Path)
    parser.add_argument("action", choices=("acquire", "heartbeat", "release", "takeover", "inspect"))
    parser.add_argument("task_id")
    parser.add_argument("--owner")
    parser.add_argument("--session-id")
    parser.add_argument("--repository")
    parser.add_argument("--branch")
    parser.add_argument("--worktree")
    parser.add_argument("--head")
    parser.add_argument("--confirmed-stopped", action="store_true")
    parser.add_argument("--authorizer-identity")
    parser.add_argument("--authorization-reference")
    parser.add_argument("--rationale")
    arguments = parser.parse_args()
    manager = WriterClaimManager(arguments.harness_data)
    try:
        result = _run(manager, arguments)
    except ClaimError as error:
        parser.error(str(error))
    if result is not None:
        print(json.dumps(result.__dict__, sort_keys=True))
    return 0


def _run(manager: WriterClaimManager, arguments: argparse.Namespace):
    if arguments.action == "inspect":
        return manager.inspect(arguments.task_id)
    identity = _identity(arguments)
    if arguments.action == "acquire":
        return manager.acquire(arguments.task_id, identity)
    if arguments.action == "heartbeat":
        return manager.heartbeat(arguments.task_id, identity)
    if arguments.action == "release":
        manager.release(arguments.task_id, identity)
        return None
    return manager.takeover(arguments.task_id, identity, authorization=_authorization(arguments))


def _identity(arguments: argparse.Namespace) -> dict[str, str]:
    fields = ("owner", "session_id", "repository", "branch", "worktree", "head")
    return {field: getattr(arguments, field) or "" for field in fields}


def _authorization(arguments: argparse.Namespace) -> dict[str, object]:
    return {
        "confirmed_stopped": arguments.confirmed_stopped,
        "authorizer_identity": arguments.authorizer_identity or "",
        "authorization_reference": arguments.authorization_reference or "",
        "rationale": arguments.rationale or "",
    }


if __name__ == "__main__":
    raise SystemExit(main())
