from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import scripts.lib.pipeline_state as pipeline_state
from scripts.lib.pipeline_state import (
    PipelineStateNotFound,
    PipelineStatePathError,
    PipelineStateValidationError,
    read_pipeline_state,
    write_pipeline_state,
)
from scripts.lib.pipeline_state_paths import canonical_pipeline_path, harness_data_root


class PipelineStatePathsTest(unittest.TestCase):
    def test_imports_as_a_package_for_mutation_testing(self) -> None:
        package_result = subprocess.run(
            [sys.executable, "-c", "import scripts.lib.pipeline_state"],
            capture_output=True,
            cwd=Path(__file__).parents[1],
            text=True,
        )

        self.assertEqual(package_result.returncode, 0, package_result.stderr)
        environment = os.environ | {"PYTHONPATH": str(Path(__file__).parents[1] / "scripts" / "lib")}
        direct_result = subprocess.run(
            [sys.executable, "-c", "import pipeline_state"],
            capture_output=True,
            cwd=Path(__file__).parents[1],
            env=environment,
            text=True,
        )
        self.assertEqual(direct_result.returncode, 0, direct_result.stderr)

    def test_harness_data_environment_selects_runtime_root(self) -> None:
        with patch.dict(os.environ, {"HARNESS_DATA": "/runtime/harness"}):
            self.assertEqual(harness_data_root(), Path("/runtime/harness"))
            self.assertEqual(
                canonical_pipeline_path("task-05"),
                Path("/runtime/harness/pipeline-state/task-05/pipeline.md"),
            )

    def test_default_runtime_root_uses_home_claude_directory(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch(
            "scripts.lib.pipeline_state_paths.Path.home", return_value=Path("/users/codex")
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
        canonical.write_text(self._canonical_content("task-05"))
        legacy.write_text(self._legacy_content("task-05"))

        state = read_pipeline_state("task-05", self.harness_data)

        self.assertEqual(state.layout, "canonical")
        self.assertEqual(state.path, canonical)
        self.assertEqual(state.fields["task_id"], "task-05")

    def test_reads_supported_legacy_flat_state(self) -> None:
        legacy = self.harness_data / "pipeline-state/task-05-pipeline.md"
        legacy.parent.mkdir(parents=True)
        legacy.write_text(self._legacy_content("task-05"))

        state = read_pipeline_state("task-05", self.harness_data)

        self.assertEqual(state.layout, "legacy-flat")
        self.assertEqual(state.path, legacy)
        self.assertEqual(state.fields["project_path"], "/repo")

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

    def test_rejects_canonical_state_with_an_unknown_schema_version(self) -> None:
        content = self._canonical_content("task-06").replace("schema_version: 1", "schema_version: 999")
        self._write_canonical("task-06", content)

        with self.assertRaisesRegex(PipelineStateValidationError, "schema_version"):
            read_pipeline_state("task-06", self.harness_data)

    def test_rejects_canonical_state_with_mismatched_task_identity(self) -> None:
        self._write_canonical("task-06", self._canonical_content("other-task"))

        with self.assertRaisesRegex(PipelineStateValidationError, "task_id"):
            read_pipeline_state("task-06", self.harness_data)

    def test_rejects_missing_or_empty_canonical_required_fields(self) -> None:
        for field in ("schema_version", "task_id", "repository", "phase", "status", "verdict", "branch", "worktree", "updated_at", "updated_by"):
            with self.subTest(field=field):
                content = self._without_field(self._canonical_content("task-06"), field)
                self._write_canonical("task-06", content)

                with self.assertRaisesRegex(PipelineStateValidationError, field):
                    read_pipeline_state("task-06", self.harness_data)

                self._write_canonical("task-06", self._canonical_content("task-06", field))
                with self.assertRaisesRegex(PipelineStateValidationError, field):
                    read_pipeline_state("task-06", self.harness_data)

    def test_rejects_legacy_state_missing_a_required_legacy_field(self) -> None:
        legacy = self.harness_data / "pipeline-state/task-06-pipeline.md"
        legacy.parent.mkdir(parents=True)
        legacy.write_text("task_id: task-06\nproject_path: /repo\ncurrent_phase: build\nstatus: active\n")

        with self.assertRaisesRegex(PipelineStateValidationError, "branch"):
            read_pipeline_state("task-06", self.harness_data)

    def test_rejects_malformed_or_duplicate_pipeline_fields(self) -> None:
        invalid_lines = ("this is not a field", ": value", " phase: build", "phase: verify")
        for line in invalid_lines:
            with self.subTest(line=line):
                self._write_canonical("task-06", self._canonical_content("task-06") + f"{line}\n")
                with self.assertRaisesRegex(PipelineStateValidationError, "malformed"):
                    read_pipeline_state("task-06", self.harness_data)

    def test_rejects_pipeline_fields_without_a_space_after_the_delimiter(self) -> None:
        content = self._canonical_content("task-06").replace(": ", ":")
        self._write_canonical("task-06", content)

        with self.assertRaisesRegex(PipelineStateValidationError, "malformed"):
            read_pipeline_state("task-06", self.harness_data)

    def test_accepts_comments_and_blank_lines_between_pipeline_fields(self) -> None:
        content = "# synthetic state\n\n" + self._canonical_content("task-06")
        self._write_canonical("task-06", content)

        state = read_pipeline_state("task-06", self.harness_data)

        self.assertEqual(state.fields["task_id"], "task-06")

    def test_rejects_an_unknown_canonical_state_author(self) -> None:
        content = self._canonical_content("task-06").replace("updated_by: codex", "updated_by: unknown")
        self._write_canonical("task-06", content)

        with self.assertRaisesRegex(PipelineStateValidationError, "updated_by"):
            read_pipeline_state("task-06", self.harness_data)

    def test_writes_and_reads_canonical_state_without_creating_legacy_state(self) -> None:
        fields = self._canonical_fields("task-07")

        state = write_pipeline_state("task-07", fields, self.harness_data)

        self.assertEqual(state.layout, "canonical")
        self.assertEqual(state.fields, fields)
        self.assertEqual(read_pipeline_state("task-07", self.harness_data).fields, fields)
        self.assertFalse((self.harness_data / "pipeline-state/task-07-pipeline.md").exists())

    def test_preserves_completed_canonical_state(self) -> None:
        fields = self._canonical_fields("task-07") | {
            "phase": "ship",
            "status": "completed",
            "verdict": "merged",
        }

        write_pipeline_state("task-07", fields, self.harness_data)

        self.assertEqual(read_pipeline_state("task-07", self.harness_data).fields, fields)

    def test_atomic_replace_failure_leaves_the_previous_valid_state_intact(self) -> None:
        old_fields = self._canonical_fields("task-07")
        write_pipeline_state("task-07", old_fields, self.harness_data)
        target = self.harness_data / "pipeline-state/task-07/pipeline.md"
        old_content = target.read_text()
        new_fields = old_fields | {"updated_at": "tomorrow"}

        with patch("scripts.lib.pipeline_state.os.replace", side_effect=OSError("interrupted")):
            with self.assertRaisesRegex(OSError, "interrupted"):
                write_pipeline_state("task-07", new_fields, self.harness_data)

        self.assertEqual(target.read_text(), old_content)
        self.assertEqual(list(target.parent.glob(".pipeline.*")), [])

    def test_rejects_invalid_writer_input_without_creating_state(self) -> None:
        fields = self._canonical_fields("wrong-task")

        with self.assertRaisesRegex(PipelineStateValidationError, "task_id"):
            write_pipeline_state("task-07", fields, self.harness_data)

        self.assertFalse((self.harness_data / "pipeline-state").exists())

    def test_rejects_non_string_writer_fields(self) -> None:
        fields = self._canonical_fields("task-07")
        fields["updated_by"] = []

        with self.assertRaisesRegex(PipelineStateValidationError, "strings"):
            write_pipeline_state("task-07", fields, self.harness_data)

    def test_rejects_writer_paths_that_escape_through_a_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as outside_directory:
            state_root = self.harness_data / "pipeline-state"
            state_root.mkdir()
            (state_root / "task-07").symlink_to(outside_directory, target_is_directory=True)

            with self.assertRaises(PipelineStatePathError):
                write_pipeline_state("task-07", self._canonical_fields("task-07"), self.harness_data)

    def test_rejects_task_directory_swapped_to_a_symlink_after_validation(self) -> None:
        with tempfile.TemporaryDirectory() as outside_directory:
            outside = Path(outside_directory)
            task_directory = self.harness_data / "pipeline-state/task-07"
            task_directory.mkdir(parents=True)
            open_task_directory = pipeline_state._open_task_directory

            def swap_then_open(state_root_fd: int, task_id: str) -> int:
                task_directory.rmdir()
                task_directory.symlink_to(outside, target_is_directory=True)
                return open_task_directory(state_root_fd, task_id)

            with patch.object(pipeline_state, "_open_task_directory", side_effect=swap_then_open):
                with self.assertRaises(PipelineStatePathError):
                    write_pipeline_state("task-07", self._canonical_fields("task-07"), self.harness_data)

            self.assertFalse((outside / "pipeline.md").exists())

    def test_rejects_state_root_swapped_to_a_symlink_after_validation(self) -> None:
        with tempfile.TemporaryDirectory() as outside_directory:
            outside = Path(outside_directory)
            state_root = self.harness_data / "pipeline-state"
            state_root.mkdir()
            open_directory = pipeline_state._open_directory

            def swap_then_open(path: Path) -> int:
                state_root.rmdir()
                state_root.symlink_to(outside, target_is_directory=True)
                return open_directory(path)

            with patch.object(pipeline_state, "_open_directory", side_effect=swap_then_open):
                with self.assertRaises(PipelineStatePathError):
                    write_pipeline_state("task-07", self._canonical_fields("task-07"), self.harness_data)

            self.assertFalse((outside / "task-07/pipeline.md").exists())

    def _write_canonical(self, task_id: str, content: str) -> None:
        path = self.harness_data / "pipeline-state" / task_id / "pipeline.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    @staticmethod
    def _canonical_content(task_id: str, empty_field: str = "") -> str:
        fields = PipelineStateReaderTest._canonical_fields(task_id)
        if empty_field:
            fields[empty_field] = ""
        return "".join(f"{name}: {value}\n" for name, value in fields.items())

    @staticmethod
    def _canonical_fields(task_id: str) -> dict[str, str]:
        return {
            "schema_version": "1",
            "task_id": task_id,
            "repository": "value",
            "phase": "value",
            "status": "value",
            "verdict": "value",
            "branch": "value",
            "worktree": "value",
            "updated_at": "value",
            "updated_by": "codex",
        }

    @staticmethod
    def _legacy_content(task_id: str) -> str:
        return (
            f"task_id: {task_id}\nproject_path: /repo\ncurrent_phase: build\n"
            "status: active\nbranch: feat/task\n"
        )

    @staticmethod
    def _without_field(content: str, field: str) -> str:
        return "".join(line for line in content.splitlines(keepends=True) if not line.startswith(f"{field}:"))


if __name__ == "__main__":
    unittest.main()
