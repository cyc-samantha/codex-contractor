"""Fail-closed validation helpers for the semantic-mutant boundary."""

from __future__ import annotations

import json
from pathlib import PurePosixPath
import re
from typing import Any, Mapping

from .llm_mutant_types import LlmMutantAdapterError, SemanticMutant


LINE_RANGE = re.compile(r"^[1-9][0-9]*(?:-[1-9][0-9]*)?$")


def safe_file(value: object) -> str:
    text = normalized_text(value, "file")
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts or path == PurePosixPath("."):
        raise LlmMutantAdapterError("mutant file path is unsafe")
    return str(path)


def line_range(value: object) -> str:
    text = normalized_text(value, "line_range")
    if not LINE_RANGE.fullmatch(text):
        raise LlmMutantAdapterError("mutant line range is invalid")
    values = [int(item) for item in text.split("-")]
    if len(values) == 2 and values[0] > values[1]:
        raise LlmMutantAdapterError("mutant line range is reversed")
    return text


def choice(value: object, choices: frozenset[str], name: str) -> str:
    text = normalized_text(value, name)
    if text not in choices:
        raise LlmMutantAdapterError(f"unsupported {name}")
    return text


def snippet(value: object, name: str) -> str:
    text = normalized_text(value, name, allow_newlines=True)
    if not text:
        raise LlmMutantAdapterError(f"{name} must not be empty")
    return text


def normalized_text(
    value: object, name: str, *, allow_newlines: bool = False
) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise LlmMutantAdapterError(f"{name} must be normalized text")
    forbidden = set(range(1, 9)) | set(range(11, 32)) | {0}
    if not allow_newlines:
        forbidden |= {9, 10, 13}
    if any(ord(character) in forbidden for character in value):
        raise LlmMutantAdapterError(f"{name} contains control characters")
    return value


def bounded_text(value: object, maximum: int, name: str) -> str:
    if not isinstance(value, str):
        raise LlmMutantAdapterError(f"{name} must be text")
    if len(value.encode("utf-8")) > maximum:
        raise LlmMutantAdapterError(f"{name} exceeds cap")
    return value


def bounded_json(value: object, maximum: int, name: str) -> None:
    try:
        encoded = json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise LlmMutantAdapterError(f"{name} is not serializable") from error
    if len(encoded) > maximum:
        raise LlmMutantAdapterError(f"{name} exceeds cap")


def range_in_locations(value: str, locations: set[int]) -> bool:
    bounds = [int(item) for item in value.split("-")]
    return all(number in locations for number in range(bounds[0], bounds[-1] + 1))


def record_key(value: Mapping[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        safe_file(value["file"]), value["line_range"], value["original"],
        value["mutated"], value["category"],
    )


def mutation_keys(records: tuple[Mapping[str, Any], ...]) -> set[tuple[str, str, str, str, str]]:
    return {record_key(record) for record in records}


def mutation_key(value: SemanticMutant) -> tuple[str, str, str, str, str]:
    return (value.file, value.line_range, value.original, value.mutated, value.category)
