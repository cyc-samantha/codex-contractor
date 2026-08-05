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
    identity = _validated_identity(descriptor)
    return _quarantine_and_remove(parent, name, identity)


def _validated_identity(descriptor: int) -> tuple[int, int]:
    try:
        return _regular_identity(descriptor)
    finally:
        os.close(descriptor)


def _try_open_target(parent: int, name: str) -> int | None:
    try:
        return _open_target(parent, name)
    except FileNotFoundError:
        return None


def _quarantine_and_remove(parent: int, name: str, identity: tuple[int, int]) -> bool:
    quarantine = _quarantine_name(parent)
    quarantine_fd = _open_quarantine(parent, quarantine)
    if not _move_to_quarantine(parent, quarantine_fd, name):
        _finish_quarantine(parent, quarantine, quarantine_fd)
        return False
    return _remove_after_quarantine(parent, quarantine, quarantine_fd, name, identity)


def _move_to_quarantine(parent: int, quarantine: int, name: str) -> bool:
    try:
        os.rename(name, name, src_dir_fd=parent, dst_dir_fd=quarantine)
    except FileNotFoundError:
        return False
    return True


def _remove_after_quarantine(
    parent: int, quarantine: str, descriptor: int, name: str, identity: tuple[int, int]
) -> bool:
    try:
        result = _remove_quarantine(descriptor, name, identity)
    except Exception:
        _finish_quarantine(parent, quarantine, descriptor)
        raise
    if not _finish_quarantine(parent, quarantine, descriptor):
        raise RetentionError("retention quarantine could not be removed")
    return result


def _quarantine_name(parent: int) -> str:
    quarantine = f".retention-{secrets.token_hex(8)}"
    try:
        os.mkdir(quarantine, 0o700, dir_fd=parent)
    except FileExistsError as error:
        raise RetentionError("retention quarantine collision") from error
    return quarantine


def _open_quarantine(parent: int, name: str) -> int:
    return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)


def _finish_quarantine(parent: int, name: str, descriptor: int) -> bool:
    os.close(descriptor)
    return _remove_quarantine_directory(parent, name)


def _remove_quarantine_directory(parent: int, name: str) -> bool:
    try:
        os.rmdir(name, dir_fd=parent)
    except OSError as error:
        return isinstance(error, FileNotFoundError)
    return True


def _remove_quarantine(parent: int, name: str, identity: tuple[int, int]) -> bool:
    descriptor = _try_open_target(parent, name)
    if descriptor is None:
        raise RetentionError("quarantined target disappeared")
    try:
        return _unlink_quarantine(parent, name, descriptor, identity)
    finally:
        os.close(descriptor)


def _unlink_quarantine(parent: int, name: str, descriptor: int, identity: tuple[int, int]) -> bool:
    _require_identity(descriptor, identity)
    os.unlink(name, dir_fd=parent)
    return True


def _require_identity(descriptor: int, identity: tuple[int, int]) -> None:
    if _regular_identity(descriptor) != identity:
        raise RetentionError("disposable target changed during cleanup")


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
        child = _open_child(descriptor, part)
        os.close(descriptor)
        descriptor = child
    return descriptor


def _open_child(descriptor: int, part: str) -> int:
    try:
        return os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
    except OSError:
        os.close(descriptor)
        raise


def _open_target(parent: int, name: str) -> int:
    flags = getattr(os, "O_PATH", os.O_RDONLY) | os.O_NOFOLLOW
    return os.open(name, flags, dir_fd=parent)


def _regular_identity(descriptor: int) -> tuple[int, int]:
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode):
        raise RetentionError("disposable target must be a regular file")
    return _identity(metadata)


def _identity(metadata: os.stat_result) -> tuple[int, int]:
    return metadata.st_dev, metadata.st_ino
