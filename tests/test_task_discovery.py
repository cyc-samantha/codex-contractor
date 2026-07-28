from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.lib.pipeline_state import PipelineStatePathError, PipelineStateValidationError
from scripts.lib.task_discovery import discover_repository_tasks


class TaskDiscoveryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.harness_data = Path(self.temporary_directory.name)
        self.repository = Path("/synthetic/repository")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_discovers_matching_active_tasks_in_task_id_order(self) -> None:
        self._write_canonical("task-z", repository=self.repository)
        self._write_canonical("task-a", repository=self.repository)
        self._write_canonical("other-repository", repository=Path("/synthetic/other"))

        tasks = discover_repository_tasks(self.repository, self.harness_data)

        self.assertEqual([task.task_id for task in tasks], ["task-a", "task-z"])
        self.assertEqual(tasks[0].repository, self.repository)
        self.assertEqual(tasks[0].worktree, self.repository / ".claude/worktrees/task-a")
        self.assertEqual(tasks[0].updated_by, "codex")

    def test_discovers_matching_legacy_active_task_with_unavailable_canonical_fields(self) -> None:
        legacy = self.harness_data / "pipeline-state/task-legacy-pipeline.md"
        legacy.parent.mkdir(parents=True)
        legacy.write_text(
            "task_id: task-legacy\nproject_path: /synthetic/repository\n"
            "current_phase: build\nstatus: active\nbranch: legacy/task\n"
        )

        tasks = discover_repository_tasks(self.repository, self.harness_data)

        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].task_id, "task-legacy")
        self.assertIsNone(tasks[0].worktree)
        self.assertIsNone(tasks[0].verdict)
        self.assertIsNone(tasks[0].updated_at)

    def test_excludes_completed_and_non_active_tasks(self) -> None:
        self._write_canonical("task-completed", status="completed")
        self._write_canonical("task-pending", status="pending")

        self.assertEqual(discover_repository_tasks(self.repository, self.harness_data), [])

    def test_missing_state_root_returns_empty_without_creating_runtime_paths(self) -> None:
        self.assertEqual(discover_repository_tasks(self.repository, self.harness_data), [])

        self.assertFalse((self.harness_data / "pipeline-state").exists())

    def test_malformed_candidate_fails_closed(self) -> None:
        path = self.harness_data / "pipeline-state/task-invalid/pipeline.md"
        path.parent.mkdir(parents=True)
        path.write_text("schema_version: 1\ntask_id: task-invalid\n")

        with self.assertRaises(PipelineStateValidationError):
            discover_repository_tasks(self.repository, self.harness_data)

    def test_symlinked_state_root_fails_closed_without_reading_external_state(self) -> None:
        with tempfile.TemporaryDirectory() as outside_directory:
            outside = Path(outside_directory)
            self._write_canonical("task-outside", harness_data=outside)
            (self.harness_data / "pipeline-state").symlink_to(
                outside / "pipeline-state", target_is_directory=True
            )

            with self.assertRaises(PipelineStatePathError):
                discover_repository_tasks(self.repository, self.harness_data)

    def test_dangling_state_root_symlink_fails_closed(self) -> None:
        (self.harness_data / "pipeline-state").symlink_to(
            self.harness_data / "missing-state-root", target_is_directory=True
        )

        with self.assertRaises(PipelineStatePathError):
            discover_repository_tasks(self.repository, self.harness_data)

    def test_discovery_does_not_modify_existing_state(self) -> None:
        path = self._write_canonical("task-read-only")
        content = path.read_text()

        discover_repository_tasks(self.repository, self.harness_data)

        self.assertEqual(path.read_text(), content)

    def _write_canonical(
        self,
        task_id: str,
        repository: Path | None = None,
        status: str = "in_progress",
        harness_data: Path | None = None,
    ) -> Path:
        path = (harness_data or self.harness_data) / "pipeline-state" / task_id / "pipeline.md"
        path.parent.mkdir(parents=True)
        path.write_text(
            "schema_version: 1\n"
            f"task_id: {task_id}\n"
            f"repository: {repository or self.repository}\n"
            "phase: build\n"
            f"status: {status}\n"
            "verdict: pending\n"
            f"branch: build/{task_id}\n"
            f"worktree: /synthetic/repository/.claude/worktrees/{task_id}\n"
            "updated_at: 2026-07-28T00:00:00+00:00\n"
            "updated_by: codex\n"
        )
        return path


if __name__ == "__main__":
    unittest.main()
