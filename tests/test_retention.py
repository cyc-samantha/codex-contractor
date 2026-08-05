from __future__ import annotations

from pathlib import Path

import pytest

from scripts.lib import retention
from scripts.lib.retention import RetentionError, cleanup_disposable, is_disposable_path


def test_disposable_artifact_paths_are_allowlisted(tmp_path: Path) -> None:
    task = tmp_path / "task-01"
    (task / "scratchpad").mkdir(parents=True)
    (task / "build-artifacts").mkdir()

    assert is_disposable_path(task, task / "scratchpad" / "notes.md")
    assert is_disposable_path(task, task / "build-artifacts" / "report.json")
    assert is_disposable_path(task, task / ".dev-server.pid")


def test_durable_pipeline_artifacts_are_rejected(tmp_path: Path) -> None:
    task = tmp_path / "task-01"
    task.mkdir()

    for name in ("pipeline.md", "handoff.json", "trajectory.jsonl", "verification.json", "writer.lock"):
        assert not is_disposable_path(task, task / name)


def test_cleanup_never_crosses_task_boundary(tmp_path: Path) -> None:
    task = tmp_path / "task-01"
    neighbor = tmp_path / "task-010"
    (task / "scratchpad").mkdir(parents=True)
    (neighbor / "scratchpad").mkdir(parents=True)
    outside = neighbor / "scratchpad" / "keep.md"
    outside.write_text("keep")

    with pytest.raises(RetentionError):
        cleanup_disposable(task, task / ".." / "task-010" / "scratchpad" / "keep.md")
    assert outside.read_text() == "keep"


def test_cleanup_removes_only_existing_regular_disposable_files(tmp_path: Path) -> None:
    task = tmp_path / "task-01"
    scratchpad = task / "scratchpad"
    scratchpad.mkdir(parents=True)
    target = scratchpad / "notes.md"
    target.write_text("discard")
    directory = scratchpad / "directory"
    directory.mkdir()
    link = scratchpad / "link"
    link.symlink_to(target)

    assert cleanup_disposable(task, target)
    assert not target.exists()
    with pytest.raises(RetentionError):
        cleanup_disposable(task, directory)
    with pytest.raises(RetentionError):
        cleanup_disposable(task, link)


def test_cleanup_rejects_replaced_quarantine_object(tmp_path: Path) -> None:
    task = tmp_path / "task-01"
    scratchpad = task / "scratchpad"
    scratchpad.mkdir(parents=True)
    target = scratchpad / "notes.md"
    target.write_text("discard")
    replacement = scratchpad / "replacement.md"
    replacement.write_text("keep")
    descriptor = target.open()
    try:
        identity = retention._regular_identity(descriptor.fileno())
    finally:
        descriptor.close()
    parent = retention._open_parent(task, Path("scratchpad"))
    try:
        with pytest.raises(RetentionError):
            retention._remove_quarantine(parent, "replacement.md", identity)
    finally:
        retention.os.close(parent)
    assert replacement.read_text() == "keep"


def test_cleanup_reports_nested_parent_failure_without_descriptor_error(tmp_path: Path) -> None:
    task = tmp_path / "task-01"
    task.mkdir()

    with pytest.raises(FileNotFoundError):
        retention._open_parent(task, Path("scratchpad"))
