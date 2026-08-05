"""Durable file and lock operations for spawn telemetry."""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import stat
from typing import Any

try:
    from .spawn_telemetry_shared import SpawnTelemetryError
    from .writer_claim_io import append_json_line, open_harness_data, open_optional_regular
except ImportError:
    from scripts.lib.spawn_telemetry_shared import SpawnTelemetryError
    from writer_claim_io import append_json_line, open_harness_data, open_optional_regular


def _append_durable(path: Path, value: dict[str, Any]) -> None:
    directory = open_harness_data(path.parent, create=True)
    try:
        append_json_line(directory, path.name, value)
    finally:
        os.close(directory)


@contextmanager
def _exclusive_lock(path: Path):
    directory = open_harness_data(path.parent, create=True)
    descriptor = _open_lock_file(directory, f".{path.name}.lock")
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        _release_lock(descriptor, directory)

def _release_lock(descriptor: int, directory: int) -> None:
    fcntl.flock(descriptor, fcntl.LOCK_UN)
    os.close(descriptor)
    os.close(directory)


def _open_lock_file(directory: int, name: str) -> int:
    descriptor = os.open(name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=directory)
    metadata = os.fstat(descriptor)
    if stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1:
        return descriptor
    os.close(descriptor)
    raise SpawnTelemetryError("telemetry lock must be a single-link regular file")


def _read_jsonl(path: Path) -> tuple[dict[str, Any], ...]:
    directory = _open_data_directory(path)
    if directory is None:
        return ()
    try:
        return _read_lines(directory, path)
    finally:
        os.close(directory)

def _open_data_directory(path: Path) -> int | None:
    try:
        return open_harness_data(path.parent, create=False)
    except FileNotFoundError:
        return None


def _read_lines(directory: int, path: Path) -> tuple[dict[str, Any], ...]:
    try:
        descriptor = open_optional_regular(directory, path.name)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as error:
        raise SpawnTelemetryError(f"cannot read telemetry file: {path.name}") from error
    if descriptor is None:
        return ()
    return _decode_lines(descriptor, path)

def _decode_lines(descriptor: int, path: Path) -> tuple[dict[str, Any], ...]:
    try:
        with os.fdopen(descriptor, encoding="utf-8") as stream:
            return tuple(json.loads(line) for line in stream)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as error:
        raise SpawnTelemetryError(f"cannot read telemetry file: {path.name}") from error
