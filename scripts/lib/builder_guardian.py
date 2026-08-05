#!/usr/bin/env python3
"""Fail-closed Builder-Guardian workflow coordinator."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from builder_guardian_contract import ContractError, load_contract
from builder_guardian_builder import run_builder
from builder_guardian_evidence import BuilderGuardianEvidenceError
from builder_guardian_review import run_guardian
from builder_guardian_state import PipelineState, StateError
from builder_guardian_verify import run_verification


def add_task_command(commands, name: str) -> None:
    commands.add_parser(name).add_argument("task_id")


def add_commands(commands) -> None:
    commands.add_parser("init").add_argument("contract", type=Path)
    handoff = commands.add_parser("handoff")
    handoff.add_argument("task_id")
    handoff.add_argument("package", type=Path)
    for name in ("build", "review", "verify", "gate", "status"):
        add_task_command(commands, name)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="codex-harness")
    result.add_argument("--state-root", type=Path, default=None)
    add_commands(result.add_subparsers(dest="command", required=True))
    return result


def state_root(value: Path | None) -> Path:
    if value:
        return value.resolve()
    harness_data = Path(os.environ.get("HARNESS_DATA", Path.home() / ".claude"))
    return harness_data / "pipeline-state"


def initialize(args: argparse.Namespace) -> dict:
    contract = load_contract(args.contract)
    state = PipelineState.create(state_root(args.state_root), contract, args.contract)
    return state.summary()


def accept_handoff(args: argparse.Namespace) -> dict:
    state = PipelineState.open(state_root(args.state_root), args.task_id)
    package = json.loads(args.package.read_text())
    state.accept_handoff(package)
    run_guardian(state)
    return state.summary()


def review(args: argparse.Namespace) -> dict:
    state = PipelineState.open(state_root(args.state_root), args.task_id)
    run_guardian(state)
    return state.summary()


def build(args: argparse.Namespace) -> dict:
    state = PipelineState.open(state_root(args.state_root), args.task_id)
    run_builder(state)
    run_guardian(state)
    return state.summary()


def verify(args: argparse.Namespace) -> dict:
    state = PipelineState.open(state_root(args.state_root), args.task_id)
    run_verification(state)
    return state.summary()


def gate(args: argparse.Namespace) -> dict:
    state = PipelineState.open(state_root(args.state_root), args.task_id)
    return state.ready_record()


def status(args: argparse.Namespace) -> dict:
    return PipelineState.open(state_root(args.state_root), args.task_id).summary()


def execute(args: argparse.Namespace) -> dict:
    handlers = {"init": initialize, "handoff": accept_handoff, "build": build,
                "review": review, "verify": verify, "gate": gate, "status": status}
    return handlers[args.command](args)


def emit_error(error: Exception) -> int:
    print(json.dumps({"status": str(error)}), file=sys.stderr)
    return 2


def main() -> int:
    try:
        print(json.dumps(execute(parser().parse_args()), sort_keys=True))
        return 0
    except (BuilderGuardianEvidenceError, ContractError, StateError, OSError, json.JSONDecodeError) as error:
        return emit_error(error)


if __name__ == "__main__":
    raise SystemExit(main())
