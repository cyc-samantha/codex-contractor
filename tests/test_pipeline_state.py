from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts" / "lib"))

from pipeline_state import (
    PipelineStateNotFound,
    PipelineStatePathError,
    read_pipeline_state,
)
from pipeline_state_paths import canonical_pipeline_path, harness_data_root


class PipelineStatePathsTest(unittest.TestCase):
    def test_harness_data_environment_selects_runtime_root(self) -> None:
        with patch.dict(os.environ, {"HARNESS_DATA": "/runtime/harness"}):
            self.assertEqual(harness_data_root(), Path("/runtime/harness"))
            self.assertEqual(
                canonical_pipeline_path("task-05"),
                Path("/runtime/harness/pipeline-state/task-05/pipeline.md"),
            )

    def test_default_runtime_root_uses_home_claude_directory(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch(
            "pipeline_state_paths.Path.home", return_value=Path("/users/codex")
        ):
            self.assertEqual(harness_data_root(), Path("/users/codex/.claude"))


class PipelineStateReaderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.harness_data = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_reads_canonical_task_state_before_legacy_state(self) -> None:
        canonical = self.harness_data / "pipeline-state/task-05/pipeline.md"
        legacy = self.harness_data / "pipeline-state/task-05-pipeline.md"
        canonical.parent.mkdir(parents=True)
        canonical.write_text("task_id: canonical\n")
        legacy.write_text("task_id: legacy\n")

        state = read_pipeline_state("task-05", self.harness_data)

        self.assertEqual(state.layout, "canonical")
        self.assertEqual(state.path, canonical)
        self.assertEqual(state.content, "task_id: canonical\n")

    def test_reads_supported_legacy_flat_state(self) -> None:
        legacy = self.harness_data / "pipeline-state/task-05-pipeline.md"
        legacy.parent.mkdir(parents=True)
        legacy.write_text("task_id: legacy\n")

        state = read_pipeline_state("task-05", self.harness_data)

        self.assertEqual(state.layout, "legacy-flat")
        self.assertEqual(state.path, legacy)
        self.assertEqual(state.content, "task_id: legacy\n")

    def test_missing_state_fails_without_creating_runtime_paths(self) -> None:
        with self.assertRaisesRegex(PipelineStateNotFound, "task-05"):
            read_pipeline_state("task-05", self.harness_data)

        self.assertFalse((self.harness_data / "pipeline-state").exists())

    def test_rejects_task_identifiers_that_can_escape_the_state_root(self) -> None:
        for task_id in ("", ".", "..", "../outside", "nested/task"):
            with self.subTest(task_id=task_id):
                with self.assertRaises(PipelineStatePathError):
                    read_pipeline_state(task_id, self.harness_data)

    def test_rejects_pipeline_state_reached_through_escaping_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as outside_directory:
            outside = Path(outside_directory)
            (outside / "pipeline.md").write_text("task_id: outside\n")
            state_root = self.harness_data / "pipeline-state"
            state_root.mkdir()
            (state_root / "task-05").symlink_to(outside, target_is_directory=True)

            with self.assertRaises(PipelineStatePathError):
                read_pipeline_state("task-05", self.harness_data)


if __name__ == "__main__":
    unittest.main()
