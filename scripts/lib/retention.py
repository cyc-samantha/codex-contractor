"""Bounded cleanup for explicitly disposable task artifacts."""

from __future__ import annotations

import os
from pathlib import Path
import secrets
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
    try:
        identity = _regular_identity(descriptor)
    finally:
        os.close(descriptor)
    return _quarantine_and_remove(parent, name, identity)


def _try_open_target(parent: int, name: str) -> int | None:
    try:
        return _open_target(parent, name)
    except FileNotFoundError:
        return None


def _quarantine_and_remove(parent: int, name: str, identity: tuple[int, int]) -> bool:
    quarantine = f".retention-{secrets.token_hex(8)}"
    try:
        os.rename(name, quarantine, src_dir_fd=parent, dst_dir_fd=parent)
    except FileNotFoundError:
        return False
    return _remove_quarantine(parent, quarantine, identity)


def _remove_quarantine(parent: int, name: str, identity: tuple[int, int]) -> bool:
    descriptor = _try_open_target(parent, name)
    if descriptor is None:
        raise RetentionError("quarantined target disappeared")
    try:
        if _regular_identity(descriptor) != identity:
            raise RetentionError("disposable target changed during cleanup")
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
    return _descend(descriptor, relative.parts)


def _descend(descriptor: int, parts: tuple[str, ...]) -> int:
    for part in parts:
        try:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
        except OSError:
            os.close(descriptor)
            raise
        os.close(descriptor)
        descriptor = child
    return descriptor


def _open_target(parent: int, name: str) -> int:
    flags = getattr(os, "O_PATH", os.O_RDONLY) | os.O_NOFOLLOW
    return os.open(name, flags, dir_fd=parent)


def _regular_identity(descriptor: int) -> tuple[int, int]:
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode):
        raise RetentionError("disposable target must be a regular file")
    return metadata.st_dev, metadata.st_ino
