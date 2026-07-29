"""Git, evidence, and process reconciliation for writer-claim takeover."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess


class ReconciliationError(ValueError):
    """Raised when takeover state cannot be reconciled."""


def canonical_directory(value: str) -> str:
    path = Path(value)
    if not path.is_absolute() or path != Path(os.path.normpath(value)):
        raise ReconciliationError("repository and worktree paths must be absolute and canonical")
    descriptor = open_absolute_directory(path)
    try:
        resolved = Path(os.readlink(f"/proc/self/fd/{descriptor}"))
    finally:
        os.close(descriptor)
    if resolved != path:
        raise ReconciliationError("repository and worktree paths must be descriptor-canonical")
    return str(resolved)


def registered_worktree_head(identity: dict[str, str]) -> str:
    repository = Path(canonical_directory(identity.get("repository", "")))
    worktree = Path(canonical_directory(identity.get("worktree", "")))
    repository_fd = open_absolute_directory(repository)
    worktree_fd = open_absolute_directory(worktree)
    try:
        records = git_output(repository_fd, "worktree", "list", "--porcelain")
        branch = git_output(worktree_fd, "branch", "--show-current")
        head = git_output(worktree_fd, "rev-parse", "HEAD")
        dirty = git_output(worktree_fd, "status", "--porcelain")
    except (OSError, subprocess.CalledProcessError) as error:
        raise ReconciliationError("worktree is not reconcilable Git state") from error
    finally:
        os.close(worktree_fd)
        os.close(repository_fd)
    expected = (head, f"refs/heads/{identity.get('branch', '')}")
    if registered_worktrees(records).get(worktree) != expected or branch != identity.get("branch") or dirty:
        raise ReconciliationError("worktree registry, branch, HEAD, or dirty state mismatches claim")
    return head


def open_absolute_directory(path: Path) -> int:
    if not path.is_absolute():
        raise ReconciliationError("repository and worktree paths must be absolute")
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in path.parts[1:]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except OSError as error:
        os.close(descriptor)
        raise ReconciliationError("repository or worktree cannot be reconciled") from error


def git_output(directory: int, *arguments: str) -> str:
    path = f"/proc/self/fd/{directory}"
    return subprocess.check_output(["git", "-C", path, *arguments], text=True, pass_fds=(directory,)).strip()


def registered_worktrees(output: str) -> dict[Path, tuple[str, str]]:
    registered: dict[Path, tuple[str, str]] = {}
    record: dict[str, str] = {}
    for line in (*output.splitlines(), ""):
        if line:
            key, _, value = line.partition(" ")
            record[key] = value
        elif record.get("worktree") and record.get("HEAD") and record.get("branch"):
            registered[Path(record["worktree"]).resolve()] = (record["HEAD"], record["branch"])
            record = {}
    return registered


def active_processes(worktree: Path) -> list[int]:
    root = worktree.resolve()
    worktree_uid = root.stat().st_uid
    if not Path("/proc").is_dir():
        raise ReconciliationError("active process state cannot be evaluated")
    ignored = ancestor_processes()
    active: list[int] = []
    for process in Path("/proc").glob("[0-9]*"):
        if int(process.name) in ignored:
            continue
        try:
            cwd = (process / "cwd").resolve(strict=True)
            if cwd == root or root in cwd.parents:
                active.append(int(process.name))
        except FileNotFoundError:
            continue
        except PermissionError as error:
            try:
                if process.stat().st_uid != worktree_uid:
                    continue
            except OSError as owner_error:
                raise ReconciliationError("active process owner cannot be evaluated") from owner_error
            raise ReconciliationError("same-owner process cwd cannot be evaluated") from error
        except OSError as error:
            raise ReconciliationError("active process state cannot be evaluated") from error
    return active


def ancestor_processes() -> set[int]:
    ancestors: set[int] = set()
    process = os.getpid()
    while process > 1 and process not in ancestors:
        ancestors.add(process)
        try:
            fields = Path(f"/proc/{process}/stat").read_text().split()
            process = int(fields[3])
        except (FileNotFoundError, PermissionError, OSError, ValueError, IndexError):
            break
    return ancestors
