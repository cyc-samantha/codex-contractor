from __future__ import annotations

import sys
import subprocess
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts" / "lib"))

from task_bootstrap import TaskBootstrapError, create_task_state


class TaskBootstrapTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.harness_data = Path(self.temporary_directory.name)
        self.repository = Path("/synthetic/repository")
        self.worktree = self.repository / ".claude/worktrees/task-one"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_creates_canonical_task_state(self) -> None:
        path = create_task_state(
            "task-one", self.repository, "fix/task-one", self.worktree, self.harness_data
        )
        content = path.read_text()
        self.assertEqual(path, self.harness_data / "pipeline-state/task-one/pipeline.md")
        self.assertIn("schema_version: 1", content)
        self.assertIn("task_id: task-one", content)
        self.assertIn("updated_by: codex", content)

    def test_refuses_to_overwrite_existing_task_state(self) -> None:
        create_task_state("task-one", self.repository, "fix/task-one", self.worktree, self.harness_data)
        with self.assertRaises(TaskBootstrapError):
            create_task_state("task-one", self.repository, "fix/task-one", self.worktree, self.harness_data)

    def test_rejects_unsafe_task_id(self) -> None:
        for task_id in ("../escape", "$(command)", "task id", "task\nid"):
            with self.subTest(task_id=task_id), self.assertRaises(TaskBootstrapError):
                create_task_state(task_id, self.repository, "fix/task-one", self.worktree, self.harness_data)

    def test_refuses_to_shadow_supported_legacy_state(self) -> None:
        legacy = self.harness_data / "pipeline-state/task-one-pipeline.md"
        legacy.parent.mkdir(parents=True)
        legacy.write_text("task_id: task-one\n")
        with self.assertRaises(TaskBootstrapError):
            create_task_state("task-one", self.repository, "fix/task-one", self.worktree, self.harness_data)

    def test_cli_returns_task_id_export_for_following_pipeline_steps(self) -> None:
        command = [
            sys.executable, str(Path(__file__).parents[1] / "scripts/lib/task_bootstrap.py"),
            "task-one", str(self.repository), "fix/task-one", str(self.worktree), str(self.harness_data),
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout, "export CLAUDE_PIPELINE_TASK_ID=task-one\n")
