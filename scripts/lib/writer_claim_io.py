"""Descriptor-based durable storage for writer claims."""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import stat
from uuid import uuid4


def open_harness_data(path: Path, create: bool) -> int:
    if not path.is_absolute():
        raise ValueError("harness data path must be absolute")
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in path.parts[1:]:
            child = open_directory(descriptor, component, create)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def open_directory(parent: int, name: str, create: bool) -> int:
    try:
        return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    except FileNotFoundError:
        if not create:
            raise
        create_directory(parent, name)
        return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)


def create_directory(parent: int, name: str) -> None:
    try:
        os.mkdir(name, mode=0o700, dir_fd=parent)
        os.fsync(parent)
    except FileExistsError:
        pass


@contextmanager
def claim_directory(task: int):
    descriptor = os.open("writer.lock", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=task)
    try:
        yield descriptor
    finally:
        os.close(descriptor)


def write_json(directory: int, name: str, value: dict[str, object]) -> None:
    temporary = f".{name}.{uuid4().hex}"
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
        dir_fd=directory,
    )
    try:
        write_descriptor_json(descriptor, value)
        os.replace(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)
    finally:
        unlink_missing_ok(directory, temporary)


def write_descriptor_json(descriptor: int, value: dict[str, object]) -> None:
    with os.fdopen(descriptor, "w", encoding="utf-8") as file:
        json.dump(value, file, sort_keys=True)
        file.write("\n")
        file.flush()
        os.fsync(file.fileno())


def read_json(directory: int, name: str) -> dict[str, object]:
    descriptor = open_optional_regular(directory, name)
    if descriptor is None:
        raise FileNotFoundError(name)
    with os.fdopen(descriptor, encoding="utf-8") as file:
        value = json.load(file)
    if not isinstance(value, dict):
        raise ValueError(f"{name} must contain a JSON object")
    return value


def append_json_line(directory: int, name: str, event: dict[str, object]) -> None:
    source = open_optional_regular(directory, name)
    temporary = f".{name}.{uuid4().hex}"
    target = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
        dir_fd=directory,
    )
    try:
        if source is not None:
            copy_descriptor(source, target)
        write_all(target, (json.dumps(event, sort_keys=True) + "\n").encode())
        os.fsync(target)
        os.replace(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)
    finally:
        if source is not None:
            os.close(source)
        os.close(target)
        unlink_missing_ok(directory, temporary)


def open_optional_regular(directory: int, name: str) -> int | None:
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=directory)
    except FileNotFoundError:
        return None
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        os.close(descriptor)
        raise OSError(f"{name} must be a single-link regular file")
    return descriptor


def copy_descriptor(source: int, target: int) -> None:
    while chunk := os.read(source, 65536):
        write_all(target, chunk)


def write_all(descriptor: int, value: bytes) -> None:
    offset = 0
    while offset < len(value):
        offset += os.write(descriptor, value[offset:])


def exists_no_follow(directory: int, name: str) -> bool:
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
    except FileNotFoundError:
        return False
    os.close(descriptor)
    return True


def unlink_missing_ok(directory: int, name: str) -> None:
    try:
        os.unlink(name, dir_fd=directory)
    except FileNotFoundError:
        pass
