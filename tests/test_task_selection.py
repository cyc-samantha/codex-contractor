from __future__ import annotations

import unittest
from pathlib import Path

from scripts.lib.task_discovery import DiscoveredTask
from scripts.lib.task_selection import TaskSelectionError, select_task


class TaskSelectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tasks = [self._task("task-a"), self._task("task-b")]

    def test_requires_an_explicit_resume_selection(self) -> None:
        selection = select_task(self.tasks, "task-b")

        self.assertEqual(selection.kind, "resume")
        self.assertEqual(selection.task.task_id, "task-b")

    def test_requires_an_explicit_new_task_selection(self) -> None:
        selection = select_task(self.tasks, "new")

        self.assertEqual(selection.kind, "new")
        self.assertIsNone(selection.task)

    def test_rejects_missing_or_unknown_selection(self) -> None:
        for choice in (None, "", "task-missing"):
            with self.subTest(choice=choice), self.assertRaises(TaskSelectionError):
                select_task(self.tasks, choice)

    def test_rejects_ambiguous_candidate_identity(self) -> None:
        with self.assertRaises(TaskSelectionError):
            select_task([self._task("task-a"), self._task("task-a")], "task-a")

    @staticmethod
    def _task(task_id: str) -> DiscoveredTask:
        return DiscoveredTask(task_id, Path("/repo"), "branch", None, "build", "in_progress", None, None, None)
