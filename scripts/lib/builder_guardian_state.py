"""Persistent state machine and identity checks."""

from __future__ import annotations

import fnmatch
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from builder_guardian_contract import digest, validate_contract


class StateError(Exception):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], check=True, text=True, capture_output=True)
    return result.stdout.strip()


def initial_data(contract: dict) -> dict:
    return {"task_id": contract["task_id"], "run_id": os.urandom(12).hex(),
            "contract_hash": digest(contract), "status": "CONTRACT_READY", "review_cycle": 0}


def load_state(directory: Path) -> dict:
    try:
        return json.loads((directory / "state.json").read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise StateError("BLOCKED: missing pipeline state") from error


def create_directory(root: Path, contract: dict, source: Path) -> Path:
    directory = root / contract["task_id"]
    if directory.exists():
        raise StateError("BLOCKED: task already exists")
    directory.mkdir(parents=True)
    shutil.copyfile(source, directory / "contract.json")
    return directory


class PipelineState:
    def __init__(self, directory: Path, data: dict):
        self.directory = directory
        self.data = data

    @classmethod
    def create(cls, root: Path, contract: dict, source: Path) -> "PipelineState":
        directory = create_directory(root, contract, source)
        state = cls(directory, initial_data(contract))
        state.save()
        state.transition("CONTRACT_READY", "orchestrator", "contract validated")
        return state

    @classmethod
    def open(cls, root: Path, task_id: str) -> "PipelineState":
        directory = root / task_id
        state = cls(directory, load_state(directory))
        state.assert_contract()
        return state

    @property
    def contract(self) -> dict:
        return json.loads((self.directory / "contract.json").read_text())

    @property
    def repo(self) -> Path:
        return Path(self.contract["repository"]).resolve()

    @property
    def review_repo(self) -> Path:
        return Path(self.data["worktree"]).resolve()

    def assert_contract(self) -> None:
        contract = self.contract
        validate_contract(contract)
        if digest(contract) != self.data["contract_hash"]:
            raise StateError("CONTRACT_CHANGE_REQUIRED")

    def save(self) -> None:
        temporary = self.directory / "state.json.tmp"
        temporary.write_text(json.dumps(self.data, indent=2, sort_keys=True) + "\n")
        temporary.replace(self.directory / "state.json")

    def transition(self, target: str, actor: str, reason: str, session_id: str = "orchestrator") -> None:
        record = {"previous_state": self.data.get("status"), "new_state": target,
                  "task_id": self.data["task_id"], "commit_sha": self.data.get("review_target"),
                  "actor": actor, "session_id": session_id, "timestamp": now(), "reason": reason}
        with (self.directory / "transitions.jsonl").open("a") as stream:
            stream.write(json.dumps(record, sort_keys=True) + "\n")
        self.data["status"] = target
        self.save()

    def accept_handoff(self, package: dict) -> None:
        self.assert_handoff_admitted()
        self.validate_handoff_shape(package)
        self.check_handoff_identity(package)
        actual_files = self.changed_files(package)
        self.check_scope(actual_files)
        self.verify_builder_package(package, actual_files)
        self.complete_handoff(package)

    def complete_handoff(self, package: dict) -> None:
        self.validate_handoff_evidence(package)
        self.store_handoff(package)

    def assert_handoff_admitted(self) -> None:
        if self.data["status"] not in {"CONTRACT_READY", "BUILDING"}:
            raise StateError("BLOCKED: handoff is not admitted in current state")

    def verify_builder_package(self, package: dict, actual_files: list[str]) -> None:
        from builder_guardian_evidence import execute_builder_checks, validate_test_paths

        validate_test_paths(Path(package["worktree"]), package["tests_changed"], actual_files)
        package["results"] = execute_builder_checks(self.contract["builder_checks"], Path(package["worktree"]))

    def validate_handoff_shape(self, package: dict) -> None:
        required = {"task_id", "review_target", "base_commit", "changed_files", "summary",
                    "ac_evidence", "tests_changed", "commands", "results", "limitations",
                    "risks", "builder_session_id", "worktree", "branch", "repository"}
        if required - package.keys() or package["task_id"] != self.data["task_id"]:
            raise StateError("BLOCKED: invalid Builder handoff")

    def changed_files(self, package: dict) -> list[str]:
        actual_files = git(self.repo, "diff", "--name-only", f"{package['base_commit']}...{package['review_target']}").splitlines()
        if sorted(package["changed_files"]) != sorted(actual_files):
            raise StateError("BLOCKED: changed-file evidence mismatch")
        return actual_files

    def validate_handoff_evidence(self, package: dict) -> None:
        expected_ac = {item["id"] for item in self.contract["acceptance_criteria"]}
        if set(package["ac_evidence"]) != expected_ac:
            raise StateError("BLOCKED: incomplete acceptance evidence")
        expected_checks = {item["command"] for item in self.contract["builder_checks"]}
        if {item["command"] for item in package["results"]} != expected_checks:
            raise StateError("BLOCKED: Builder validation incomplete")

    def store_handoff(self, package: dict) -> None:
        self.data.update({"review_target": package["review_target"], "builder_session_id": package["builder_session_id"],
                          "worktree": package["worktree"], "branch": package["branch"]})
        (self.directory / "handoff.json").write_text(json.dumps(package, indent=2, sort_keys=True) + "\n")
        self.data["handoff_hash"] = digest(package)
        self.transition("AWAITING_REVIEW", "builder", "immutable handoff accepted", package["builder_session_id"])

    def check_handoff_identity(self, package: dict) -> None:
        self.validate_base_target(package)
        from builder_guardian_evidence import branch_matches, target_descends
        if not target_descends(self.repo, package["base_commit"], package["review_target"]):
            raise StateError("BLOCKED: review target does not descend from base")
        if not branch_matches(Path(package["worktree"]), package["branch"]):
            raise StateError("BLOCKED: Builder branch identity mismatch")
        self.validate_worktree(package)

    def validate_base_target(self, package: dict) -> None:
        base_match = Path(package["repository"]).resolve() == self.repo and package["base_commit"] == self.contract["base_commit"]
        if not base_match:
            raise StateError("BLOCKED: handoff identity mismatch")
        if git(self.repo, "rev-parse", package["review_target"]) != package["review_target"]:
            raise StateError("BLOCKED: invalid review target")

    def validate_worktree(self, package: dict) -> None:
        worktree = Path(package["worktree"]).resolve()
        self.validate_isolation(worktree, package["branch"])
        self.validate_registration(worktree, package["branch"])
        target_match = git(worktree, "rev-parse", "HEAD") == package["review_target"]
        if not target_match or git(worktree, "status", "--porcelain"):
            raise StateError("BLOCKED: worktree does not match review target")
        self.validate_common_dir(worktree)

    def validate_registration(self, worktree: Path, branch: str) -> None:
        from builder_guardian_evidence import registered_worktree
        if not registered_worktree(self.repo, worktree, branch):
            raise StateError("BLOCKED: unregistered Builder worktree")

    def validate_isolation(self, worktree: Path, branch: str) -> None:
        if worktree == self.repo or branch in {"main", "master"}:
            raise StateError("BLOCKED: Builder must use an isolated worktree")

    def validate_common_dir(self, worktree: Path) -> None:
        common_dir = Path(git(worktree, "rev-parse", "--git-common-dir"))
        if not common_dir.is_absolute():
            common_dir = worktree / common_dir
        if common_dir.resolve() != (self.repo / ".git").resolve():
            raise StateError("BLOCKED: unregistered Builder worktree")

    def assert_handoff(self) -> None:
        package = json.loads((self.directory / "handoff.json").read_text())
        if digest(package) != self.data.get("handoff_hash"):
            raise StateError("BLOCKED: stale Builder handoff")
        if package.get("review_target") != self.data.get("review_target"):
            raise StateError("BLOCKED: stale Builder handoff")
        self.check_handoff_identity(package)
        self.changed_files(package)

    def check_scope(self, files: list[str]) -> None:
        allowed = self.contract["allowed_scope"]
        prohibited = self.contract["prohibited_changes"]
        outside = any(not any(fnmatch.fnmatch(path, pattern) for pattern in allowed) for path in files)
        forbidden = any(any(fnmatch.fnmatch(path, pattern) for pattern in prohibited) for path in files)
        if outside or forbidden:
            raise StateError("CONTRACT_CHANGE_REQUIRED")

    def summary(self) -> dict:
        return {key: self.data.get(key) for key in ("task_id", "run_id", "status", "review_target", "review_cycle")}

    def ready_record(self) -> dict:
        if self.data["status"] != "VERIFIED":
            raise StateError("BLOCKED: all gates have not passed")
        self.assert_handoff()
        evidence, verdict = self.ready_evidence()
        self.validate_ready_evidence(evidence, verdict)
        return self.finish_ready_record(evidence, verdict)

    def finish_ready_record(self, evidence: dict, verdict: dict) -> dict:
        record = self.build_ready_record(evidence, verdict)
        self.persist_ready_record(record)
        return record

    def persist_ready_record(self, record: dict) -> None:
        (self.directory / "ready.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
        self.transition("READY_TO_SHIP", "orchestrator", "all identity-bound gates passed")

    def ready_evidence(self) -> tuple[dict, dict]:
        evidence = json.loads((self.directory / "verification.json").read_text())
        verdict = json.loads((self.directory / "guardian-verdict.json").read_text())
        return evidence, verdict

    def validate_ready_evidence(self, evidence: dict, verdict: dict) -> None:
        identities = self.evidence_identities(evidence, verdict)
        clean_target = (git(self.review_repo, "rev-parse", "HEAD") == self.data["review_target"]
                        and not git(self.review_repo, "status", "--porcelain"))
        if not all(identities) or not clean_target or not self.artifacts_authorize(evidence, verdict):
            raise StateError("BLOCKED: stale evidence")

    def artifacts_authorize(self, evidence: dict, verdict: dict) -> bool:
        hashes = (digest(evidence) == self.data.get("verification_hash"),
                  digest(verdict) == self.data.get("guardian_verdict_hash"))
        ac_pass = all(item.get("result") == "PASS" for item in verdict.get("ac_results", []))
        guardian_pass = verdict.get("verdict") == "APPROVED" and ac_pass
        return all(hashes) and guardian_pass and not verdict.get("blocking_findings") and not verdict.get("missing_evidence") and self.verification_passed(evidence)

    def verification_passed(self, evidence: dict) -> bool:
        expected = [item["command"] for item in self.contract["final_checks"]]
        from builder_guardian_evidence import (
            BuilderGuardianEvidenceError,
            parse_builder_guardian_verification,
        )
        try:
            parsed = parse_builder_guardian_verification(evidence)
        except BuilderGuardianEvidenceError:
            return False
        return parsed.is_ready(expected)

    def evidence_identities(self, evidence: dict, verdict: dict) -> tuple[bool, ...]:
        return self.verification_identities(evidence) + self.guardian_identities(verdict)

    def verification_identities(self, evidence: dict) -> tuple[bool, ...]:
        return (evidence.get("task_id") == self.data["task_id"], evidence.get("run_id") == self.data["run_id"],
                Path(evidence.get("repository", "")).resolve() == self.repo,
                Path(evidence.get("worktree", "")).resolve() == self.review_repo,
                evidence.get("approved_commit") == self.data["review_target"])

    def guardian_identities(self, verdict: dict) -> tuple[bool, ...]:
        return (verdict.get("reviewed_target") == self.data["review_target"], verdict.get("task_id") == self.data["task_id"],
                verdict.get("run_id") == self.data["run_id"], Path(verdict.get("repository", "")).resolve() == self.repo,
                Path(verdict.get("worktree", "")).resolve() == self.review_repo,
                verdict.get("guardian_session_id") == self.data.get("guardian_session_id"))

    def build_ready_record(self, evidence: dict, verdict: dict) -> dict:
        return {"status": "READY_TO_SHIP", "task_id": self.data["task_id"],
                  "base_commit": self.contract["base_commit"], "approved_commit": self.data["review_target"],
                  "builder_session_id": self.data["builder_session_id"], "guardian_session_id": verdict["guardian_session_id"],
                  "guardian_verdict": verdict["verdict"], "verification_status": evidence["status"],
                  "verification_timestamp": evidence["timestamp"], "changed_files": json.loads((self.directory / "handoff.json").read_text())["changed_files"],
                  "evidence": {"guardian": "guardian-verdict.json", "verification": "verification.json"},
                  "repository": str(self.repo), "worktree": self.data["worktree"], "run_id": self.data["run_id"]}
