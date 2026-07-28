from __future__ import annotations

import tempfile
import threading
import fcntl
import os
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.lib.writer_claim import (
    ClaimConflictError,
    ClaimIdentityError,
    ClaimRecoveryRequiredError,
    WriterClaimManager,
)
from scripts.lib.pipeline_state import read_pipeline_state, write_pipeline_state


class WriterClaimTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.harness_data = Path(self.temporary_directory.name)
        self.worktree = self.harness_data / "worktree"
        self.worktree.mkdir()
        self._git("init", "-b", "build/claim")
        self._git("config", "user.email", "test@example.com")
        self._git("config", "user.name", "Test")
        (self.worktree / "README").write_text("test\n")
        self._git("add", "README")
        self._git("commit", "-m", "initial")
        self.manager = WriterClaimManager(self.harness_data)
        self.identity = self._identity("session-a")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_different_tasks_acquire_independently(self) -> None:
        first = self.manager.acquire("task-one", self.identity)
        second = self.manager.acquire("task-two", self.identity)

        self.assertEqual(first.task_id, "task-one")
        self.assertEqual(second.task_id, "task-two")

    def test_acquire_rejects_relative_or_noncanonical_git_paths(self) -> None:
        for field, value in (
            ("repository", "."),
            ("worktree", ".."),
            ("repository", f"{self.worktree}/../worktree"),
        ):
            with self.subTest(field=field, value=value), self.assertRaises(ClaimRecoveryRequiredError):
                self.manager.acquire("task-one", self.identity | {field: value})

    def test_same_task_has_one_atomic_winner(self) -> None:
        self.manager.acquire("task-one", self.identity)

        with self.assertRaises(ClaimConflictError):
            self.manager.acquire("task-one", self._identity("session-b"))

    def test_concurrent_acquisition_has_one_winner(self) -> None:
        barrier = threading.Barrier(2)
        outcomes: list[str] = []

        def acquire(session_id: str) -> None:
            barrier.wait()
            try:
                self.manager.acquire("task-one", self._identity(session_id))
                outcomes.append("winner")
            except (ClaimConflictError, ClaimRecoveryRequiredError):
                outcomes.append("blocked")

        threads = [threading.Thread(target=acquire, args=(session_id,)) for session_id in ("session-a", "session-b")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertCountEqual(outcomes, ["winner", "blocked"])

    def test_crash_after_lock_creation_fails_closed(self) -> None:
        lock = self.harness_data / "pipeline-state/task-one/writer.lock"
        lock.mkdir(parents=True)

        with self.assertRaises(ClaimRecoveryRequiredError):
            self.manager.acquire("task-one", self.identity)

    def test_rejects_symlinked_task_claim_path(self) -> None:
        outside = self.harness_data / "outside"
        outside.mkdir()
        state_root = self.harness_data / "pipeline-state"
        state_root.mkdir()
        (state_root / "task-one").symlink_to(outside, target_is_directory=True)

        with self.assertRaises(ClaimRecoveryRequiredError):
            self.manager.acquire("task-one", self.identity)
        self.assertFalse((outside / "writer.lock").exists())

    def test_rejects_missing_malformed_or_identity_mismatched_owner(self) -> None:
        lock = self.harness_data / "pipeline-state/task-one/writer.lock"
        lock.mkdir(parents=True)
        with self.assertRaises(ClaimRecoveryRequiredError):
            self.manager.inspect("task-one")
        (lock / "owner.json").write_text("not-json")
        with self.assertRaises(ClaimRecoveryRequiredError):
            self.manager.inspect("task-one")
        (lock / "owner.json").write_text(
            '{"schema_version":1,"task_id":"other","owner":"codex","session_id":"s",'
            '"repository":"/repo","branch":"build/claim","worktree":"/worktree",'
            '"acquired_at":"now","last_heartbeat_at":"now"}\n'
        )

        with self.assertRaises(ClaimRecoveryRequiredError):
            self.manager.inspect("task-one")

    def test_inspect_rejects_symlinked_owner_file(self) -> None:
        lock = self.harness_data / "pipeline-state/task-one/writer.lock"
        lock.mkdir(parents=True)
        outside = self.harness_data / "outside.json"
        outside.write_text("{}")
        (lock / "owner.json").symlink_to(outside)

        with self.assertRaises(ClaimRecoveryRequiredError):
            self.manager.inspect("task-one")

    def test_inspect_rejects_fifo_owner_without_blocking(self) -> None:
        lock = self.harness_data / "pipeline-state/task-one/writer.lock"
        lock.mkdir(parents=True)
        os.mkfifo(lock / "owner.json")

        with self.assertRaises(ClaimRecoveryRequiredError):
            self.manager.inspect("task-one")

    def test_incomplete_takeover_transaction_fails_closed(self) -> None:
        self.manager.acquire("task-one", self.identity)
        transaction = self.harness_data / "pipeline-state/task-one/takeover.transaction.json"
        transaction.write_text('{"event":"writer_claim_displaced"}\n')

        with self.assertRaises(ClaimRecoveryRequiredError):
            self.manager.inspect("task-one")

    def test_owner_can_heartbeat_and_release_own_claim(self) -> None:
        self.manager.acquire("task-one", self.identity)
        refreshed = self.manager.heartbeat("task-one", self.identity)
        self.manager.release("task-one", self.identity)

        self.assertEqual(refreshed.session_id, "session-a")
        self.assertFalse((self.harness_data / "pipeline-state/task-one/writer.lock").exists())

    def test_claim_mutation_fails_closed_while_takeover_lock_is_held(self) -> None:
        self.manager.acquire("task-one", self.identity)
        mutex = self.harness_data / "pipeline-state/task-one/writer.operation.lock"
        with mutex.open("a+", encoding="utf-8") as file:
            fcntl.flock(file.fileno(), fcntl.LOCK_EX)
            with self.assertRaises(ClaimRecoveryRequiredError):
                self.manager.heartbeat("task-one", self.identity)
        self.assertEqual(self.manager.inspect("task-one").session_id, "session-a")

    def test_release_preserves_completed_pipeline_state(self) -> None:
        fields = {
            "schema_version": "1", "task_id": "task-one", "repository": "/repo",
            "phase": "ship", "status": "completed", "verdict": "merged",
            "branch": "build/claim", "worktree": str(self.worktree),
            "updated_at": "now", "updated_by": "codex",
        }
        write_pipeline_state("task-one", fields, self.harness_data)
        self.manager.acquire("task-one", self.identity)
        self.manager.release("task-one", self.identity)

        self.assertEqual(read_pipeline_state("task-one", self.harness_data).fields["status"], "completed")

    def test_displaced_owner_cannot_heartbeat_or_release_successor(self) -> None:
        self.manager.acquire("task-one", self.identity)
        successor = self.manager.takeover("task-one", self._identity("session-b"), authorization=self._authorization())

        with self.assertRaises(ClaimIdentityError):
            self.manager.heartbeat("task-one", self.identity)
        with self.assertRaises(ClaimIdentityError):
            self.manager.release("task-one", self.identity)
        self.assertEqual(successor.session_id, "session-b")

    def test_takeover_requires_explicit_human_confirmation(self) -> None:
        self.manager.acquire("task-one", self.identity)

        with self.assertRaises(ClaimRecoveryRequiredError):
            self.manager.takeover("task-one", self._identity("session-b"), authorization=self._authorization() | {"confirmed_stopped": False})

    def test_takeover_requires_auditable_human_authorization(self) -> None:
        self.manager.acquire("task-one", self.identity)

        for missing in ("authorizer_identity", "authorization_reference", "rationale"):
            authorization = self._authorization()
            authorization[missing] = ""
            with self.subTest(missing=missing), self.assertRaises(ClaimRecoveryRequiredError):
                self.manager.takeover("task-one", self._identity("session-b"), authorization=authorization)

    def test_takeover_requires_a_unique_successor_session(self) -> None:
        self.manager.acquire("task-one", self.identity)

        with self.assertRaises(ClaimRecoveryRequiredError):
            self.manager.takeover("task-one", self.identity, authorization=self._authorization())

    def test_takeover_archives_owner_and_installs_unique_successor(self) -> None:
        self.manager.acquire("task-one", self.identity)
        successor = self.manager.takeover("task-one", self._identity("session-b"), authorization=self._authorization())

        trajectory = self.harness_data / "pipeline-state/task-one/trajectory.jsonl"
        recorded = trajectory.read_text()
        self.assertIn('"session_id": "session-a"', recorded)
        self.assertIn('"authorization_reference": "incident-42"', recorded)
        self.assertFalse((self.harness_data / "pipeline-state/task-one/takeover.transaction.json").exists())
        self.assertNotEqual(successor.session_id, self.identity["session_id"])

    def test_takeover_rejects_unreconciled_repository_or_worktree(self) -> None:
        self.manager.acquire("task-one", self.identity)

        with self.assertRaises(ClaimRecoveryRequiredError):
            self.manager.takeover("task-one", self._identity("session-b") | {"worktree": "/missing"}, authorization=self._authorization())

    def test_takeover_rejects_unregistered_worktree_or_head_mismatch(self) -> None:
        self.manager.acquire("task-one", self.identity)
        identity = self._identity("session-b") | {"head": "0" * 40}

        with self.assertRaises(ClaimRecoveryRequiredError):
            self.manager.takeover("task-one", identity, authorization=self._authorization())

    def test_takeover_rejects_changed_task_git_identity(self) -> None:
        self.manager.acquire("task-one", self.identity)

        for field in ("repository", "branch", "worktree"):
            with self.subTest(field=field), self.assertRaises(ClaimRecoveryRequiredError):
                identity = self._identity("session-b") | {field: "/other" if field != "branch" else "other"}
                self.manager.takeover("task-one", identity, authorization=self._authorization())

    def test_takeover_rejects_dirty_worktree_and_stale_evidence(self) -> None:
        self.manager.acquire("task-one", self.identity)
        (self.worktree / "dirty").write_text("dirty")
        with self.assertRaises(ClaimRecoveryRequiredError):
            self.manager.takeover("task-one", self._identity("session-b"), authorization=self._authorization())
        (self.worktree / "dirty").unlink()
        evidence = self.harness_data / "pipeline-state/task-one/verification-evidence.json"
        evidence.write_text('{"task_id":"task-one","git_head":"stale","verdict":"passed"}\n')

        with self.assertRaises(ClaimRecoveryRequiredError):
            self.manager.takeover("task-one", self._identity("session-b"), authorization=self._authorization())

    def test_takeover_accepts_evidence_bound_to_current_head(self) -> None:
        self.manager.acquire("task-one", self.identity)
        evidence = self.harness_data / "pipeline-state/task-one/verification-evidence.json"
        evidence.write_text(
            f'{{"task_id":"task-one","git_head":"{self.identity["head"]}","verdict":"passed"}}\n'
        )

        successor = self.manager.takeover(
            "task-one",
            self._identity("session-b"),
            authorization=self._authorization(),
        )

        self.assertEqual(successor.session_id, "session-b")
        self.assertIn('"evidence": "valid"', (self.harness_data / "pipeline-state/task-one/trajectory.jsonl").read_text())

    def test_takeover_rejects_malformed_or_symlinked_evidence(self) -> None:
        self.manager.acquire("task-one", self.identity)
        evidence = self.harness_data / "pipeline-state/task-one/verification-evidence.json"
        evidence.write_text("not-json")
        with self.assertRaises(ClaimRecoveryRequiredError):
            self.manager.takeover("task-one", self._identity("session-b"), authorization=self._authorization())
        evidence.unlink()
        outside = self.harness_data / "outside-evidence.json"
        outside.write_text("{}")
        evidence.symlink_to(outside)

        with self.assertRaises(ClaimRecoveryRequiredError):
            self.manager.takeover("task-one", self._identity("session-b"), authorization=self._authorization())

    def test_takeover_rejects_fifo_evidence_without_blocking(self) -> None:
        self.manager.acquire("task-one", self.identity)
        evidence = self.harness_data / "pipeline-state/task-one/verification-evidence.json"
        os.mkfifo(evidence)

        with self.assertRaises(ClaimRecoveryRequiredError):
            self.manager.takeover("task-one", self._identity("session-b"), authorization=self._authorization())

    def test_takeover_rejects_detectable_active_prior_process(self) -> None:
        self.manager.acquire("task-one", self.identity)

        with patch.object(self.manager, "_active_processes", return_value=[123]):
            with self.assertRaises(ClaimRecoveryRequiredError):
                self.manager.takeover("task-one", self._identity("session-b"), authorization=self._authorization())

    def test_release_rejects_symlinked_trajectory_target(self) -> None:
        self.manager.acquire("task-one", self.identity)
        trajectory = self.harness_data / "pipeline-state/task-one/trajectory.jsonl"
        outside = self.harness_data / "outside.jsonl"
        outside.write_text("safe\n")
        trajectory.symlink_to(outside)

        with self.assertRaises(ClaimRecoveryRequiredError):
            self.manager.takeover("task-one", self._identity("session-b"), authorization=self._authorization())
        self.assertEqual(outside.read_text(), "safe\n")

    def test_takeover_rejects_hardlinked_trajectory_target(self) -> None:
        self.manager.acquire("task-one", self.identity)
        trajectory = self.harness_data / "pipeline-state/task-one/trajectory.jsonl"
        outside = self.harness_data / "outside.jsonl"
        outside.write_text("safe\n")
        os.link(outside, trajectory)

        with self.assertRaises(ClaimRecoveryRequiredError):
            self.manager.takeover("task-one", self._identity("session-b"), authorization=self._authorization())
        self.assertEqual(outside.read_text(), "safe\n")

    def test_takeover_rejects_fifo_trajectory_without_blocking(self) -> None:
        self.manager.acquire("task-one", self.identity)
        trajectory = self.harness_data / "pipeline-state/task-one/trajectory.jsonl"
        os.mkfifo(trajectory)

        with self.assertRaises(ClaimRecoveryRequiredError):
            self.manager.takeover("task-one", self._identity("session-b"), authorization=self._authorization())

    def test_interrupted_takeover_preserves_auditable_recovery_transaction(self) -> None:
        self.manager.acquire("task-one", self.identity)

        with patch("scripts.lib.writer_claim.claim_io.append_json_line", side_effect=OSError("disk failure")):
            with self.assertRaises(ClaimRecoveryRequiredError):
                self.manager.takeover("task-one", self._identity("session-b"), authorization=self._authorization())

        transaction = self.harness_data / "pipeline-state/task-one/takeover.transaction.json"
        self.assertIn('"authorization_reference": "incident-42"', transaction.read_text())
        with self.assertRaises(ClaimRecoveryRequiredError):
            self.manager.inspect("task-one")

    def _identity(self, session_id: str) -> dict[str, str]:
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.worktree, text=True).strip()
        return {
            "owner": "codex",
            "session_id": session_id,
            "repository": str(self.worktree),
            "branch": "build/claim",
            "worktree": str(self.worktree),
            "head": head,
        }

    @staticmethod
    def _authorization() -> dict[str, object]:
        return {
            "confirmed_stopped": True,
            "authorizer_identity": "human@example.com",
            "authorization_reference": "incident-42",
            "rationale": "prior session terminated unexpectedly",
        }

    def _git(self, *arguments: str) -> None:
        subprocess.run(["git", *arguments], cwd=self.worktree, check=True, capture_output=True)
