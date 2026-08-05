"""Bounded cleanup for explicitly disposable task artifacts."""

from __future__ import annotations

import os
from pathlib import Path
import stat


class RetentionError(ValueError):
    """Raised when cleanup would cross a durable or unsafe boundary."""


DISPOSABLE_ROOTS = frozenset({"scratchpad", "build-artifacts"})


def is_disposable_path(task_dir: Path, target: Path) -> bool:
    try:
        relative = _relative_path(task_dir, target)
    except RetentionError:
        return False
    return _is_allowlisted(relative)


def cleanup_disposable(task_dir: Path, target: Path) -> bool:
    relative = _relative_path(task_dir, target)
    if not _is_allowlisted(relative):
        raise RetentionError("path is not an allowlisted disposable artifact")
    parent = _try_open_parent(task_dir, relative.parent)
    if parent is None:
        return False
    return _cleanup_parent(parent, relative.name)

def _cleanup_parent(parent: int, name: str) -> bool:
    try:
        return _remove_regular(parent, name)
    finally:
        os.close(parent)


def _try_open_parent(task_dir: Path, relative: Path) -> int | None:
    try:
        return _open_parent(task_dir, relative)
    except FileNotFoundError:
        return None


def _remove_regular(parent: int, name: str) -> bool:
    descriptor = _try_open_target(parent, name)
    if descriptor is None:
        return False
    return _unlink_regular(parent, name, descriptor)


def _try_open_target(parent: int, name: str) -> int | None:
    try:
        return _open_target(parent, name)
    except FileNotFoundError:
        return None


def _unlink_regular(parent: int, name: str, descriptor: int) -> bool:
    try:
        _require_regular(descriptor)
        os.unlink(name, dir_fd=parent)
        return True
    finally:
        os.close(descriptor)


def _relative_path(task_dir: Path, target: Path) -> Path:
    _validate_roots(task_dir, target)
    try:
        return target.relative_to(task_dir)
    except ValueError as error:
        raise RetentionError("target is outside task directory") from error


def _validate_roots(task_dir: Path, target: Path) -> None:
    if not task_dir.is_absolute() or not target.is_absolute():
        raise RetentionError("retention paths must be absolute")
    if ".." in task_dir.parts or ".." in target.parts:
        raise RetentionError("retention paths cannot contain parent traversal")
    if not task_dir.is_dir() or task_dir.is_symlink():
        raise RetentionError("task directory must be a real directory")


def _is_allowlisted(relative: Path) -> bool:
    if relative == Path(".dev-server.pid"):
        return True
    return len(relative.parts) > 1 and relative.parts[0] in DISPOSABLE_ROOTS


def _open_parent(task_dir: Path, relative: Path) -> int:
    descriptor = os.open(task_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        return _descend(descriptor, relative.parts)
    except OSError:
        os.close(descriptor)
        raise


def _descend(descriptor: int, parts: tuple[str, ...]) -> int:
    for part in parts:
        child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
        os.close(descriptor)
        descriptor = child
    return descriptor


def _open_target(parent: int, name: str) -> int:
    flags = getattr(os, "O_PATH", os.O_RDONLY) | os.O_NOFOLLOW
    return os.open(name, flags, dir_fd=parent)


def _require_regular(descriptor: int) -> None:
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        raise RetentionError("disposable target must be a regular file")
