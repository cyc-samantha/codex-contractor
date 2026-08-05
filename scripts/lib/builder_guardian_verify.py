"""Commit-bound deterministic verification in a disposable checkout."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from builder_guardian_contract import digest
from builder_guardian_evidence import parse_builder_guardian_verification
from builder_guardian_state import PipelineState, StateError, git, now


def run_check(check: dict, checkout: Path) -> dict:
    try:
        result = invoke_check(check, checkout)
        return check_result(check, result.returncode, (result.stdout + result.stderr)[-4000:])
    except subprocess.TimeoutExpired:
        return check_result(check, None, "timeout")


def invoke_check(check: dict, checkout: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-lc", check["command"]], cwd=checkout, text=True,
                          capture_output=True, timeout=int(check.get("timeout_seconds", 600)))


def check_result(check: dict, exit_code: int | None, output: str) -> dict:
    return {"name": check.get("name", check["command"]), "command": check["command"],
            "exit_code": exit_code, "output": output}


def disposable_checkout(state: PipelineState, destination: Path) -> None:
    archive = subprocess.Popen(["git", "-C", str(state.repo), "archive", state.data["review_target"]], stdout=subprocess.PIPE)
    extract = subprocess.run(["tar", "-x", "-C", str(destination)], stdin=archive.stdout, capture_output=True)
    if archive.stdout:
        archive.stdout.close()
    if archive.wait() != 0 or extract.returncode != 0:
        raise StateError("VERIFICATION_BLOCKED")


def assert_approved_target(state: PipelineState) -> str:
    assert_guardian_approved(state)
    state.assert_handoff()
    target = state.data["review_target"]
    clean_target = git(state.review_repo, "rev-parse", "HEAD") == target and not git(state.review_repo, "status", "--porcelain")
    if not clean_target:
        raise StateError("VERIFICATION_BLOCKED")
    return target

def assert_guardian_approved(state: PipelineState) -> None:
    if state.data["status"] != "GUARDIAN_APPROVED":
        raise StateError("BLOCKED: Guardian approval required")


def collect_results(state: PipelineState) -> list[dict]:
    with tempfile.TemporaryDirectory(prefix="codex-verify-") as temporary:
        checkout = Path(temporary)
        disposable_checkout(state, checkout)
        return [run_check(check, checkout) for check in state.contract["final_checks"]]


def write_evidence(state: PipelineState, target: str, results: list[dict]) -> None:
    evidence = {"task_id": state.data["task_id"], "run_id": state.data["run_id"],
                "repository": str(state.repo), "worktree": state.data["worktree"],
                "approved_commit": target, "timestamp": now(), "commands": results,
                "status": "PASSED" if all(item["exit_code"] == 0 for item in results) else "FAILED"}
    parse_builder_guardian_verification(evidence)
    (state.directory / "verification.json").write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    state.data["verification_hash"] = digest(evidence)


def fail_verification(state: PipelineState) -> None:
    state.data.pop("review_target", None)
    state.data.pop("guardian_verdict_hash", None)
    state.data.pop("verification_hash", None)
    state.transition("VERIFICATION_FAILED", "verifier", "required deterministic check failed", "deterministic-verifier")
    state.transition("BUILDING", "orchestrator", "verification defect requires a new target")
    raise StateError("VERIFICATION_FAILED")


def run_verification(state: PipelineState) -> None:
    target = assert_approved_target(state)
    state.transition("VERIFYING", "verifier", "approved target identity confirmed", "deterministic-verifier")
    results = collect_results(state)
    write_evidence(state, target, results)
    if any(item["exit_code"] != 0 for item in results):
        fail_verification(state)
    state.transition("VERIFIED", "verifier", "all deterministic checks passed", "deterministic-verifier")
