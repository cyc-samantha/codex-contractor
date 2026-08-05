"""Neutral value types shared by spawn telemetry modules."""

from __future__ import annotations

from dataclasses import dataclass


class SpawnTelemetryError(ValueError):
    """Raised when spawn telemetry is incomplete or contradictory."""


@dataclass(frozen=True)
class TokenMetric:
    value: int | None
    unavailable_reason: str | None
