"""Deterministic High Risk routing and downgrade authorization."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass


REQUESTED_GEARS = frozenset({"Small Change", "Build"})
DOWNGRADE_GEARS = frozenset({"Small Change", "Build"})
HIGH_RISK = "High Risk"
HIGH_RISK_TRIGGERS = (
    "authentication_authorization",
    "secrets_credentials",
    "payments_trading_finance",
    "destructive_migrations",
    "sensitive_data",
    "package_installation_removal",
    "deployment_cloud_infrastructure",
    "filesystem_bulk_operations_retention",
    "git_history_protected_branches",
    "security_controls_sandboxes_hooks",
    "data_schema_coercion_filtering",
    "breaking_apis_shared_libraries",
    "untrusted_scripts_plugins_generated_instructions",
    "backup_restore_disaster_recovery",
)


class RiskRoutingError(ValueError):
    """Raised when risk routing cannot be evaluated safely."""


@dataclass(frozen=True)
class DowngradeAuthorization:
    """Auditable human authorization for reducing an automatic risk result."""

    authorized_by: str
    target_gear: str
    rationale: str
    authorization_id: str


@dataclass(frozen=True)
class RiskDecision:
    """The immutable result of deterministic risk routing."""

    requested_gear: str
    effective_gear: str
    triggers: tuple[str, ...]
    human_elevated: bool
    downgrade: DowngradeAuthorization | None

    def as_record(self) -> dict[str, object]:
        """Return a JSON-compatible record for pipeline state."""

        return asdict(self)


def route_risk(
    requested_gear: str,
    signals: Mapping[str, bool],
    *,
    human_elevated: bool = False,
    downgrade: DowngradeAuthorization | None = None,
) -> RiskDecision:
    """Resolve a requested gear while preserving every risk decision."""

    _validate_request(requested_gear, signals, human_elevated, downgrade)
    triggers = _active_triggers(signals)
    effective_gear = _resolve_gear(requested_gear, triggers, human_elevated, downgrade)
    return RiskDecision(
        requested_gear,
        effective_gear,
        triggers,
        human_elevated,
        _downgrade_record(downgrade),
    )


def _validate_request(
    requested_gear: str,
    signals: Mapping[str, bool],
    human_elevated: bool,
    downgrade: DowngradeAuthorization | None,
) -> None:
    if requested_gear not in REQUESTED_GEARS:
        raise RiskRoutingError("invalid requested gear")
    if not isinstance(signals, Mapping):
        raise RiskRoutingError("risk signals must be a mapping")
    if not isinstance(human_elevated, bool):
        raise RiskRoutingError("human elevation must be boolean")
    if downgrade is not None and not isinstance(downgrade, DowngradeAuthorization):
        raise RiskRoutingError("downgrade authorization has invalid type")


def _active_triggers(signals: Mapping[str, bool]) -> tuple[str, ...]:
    unknown = set(signals) - set(HIGH_RISK_TRIGGERS)
    if unknown:
        raise RiskRoutingError("unknown trigger")
    if set(signals) != set(HIGH_RISK_TRIGGERS):
        raise RiskRoutingError("risk trigger snapshot is not complete")
    for value in signals.values():
        if not isinstance(value, bool):
            raise RiskRoutingError("trigger values must be boolean")
    return tuple(trigger for trigger in HIGH_RISK_TRIGGERS if signals.get(trigger, False))


def _resolve_gear(
    requested_gear: str,
    triggers: tuple[str, ...],
    human_elevated: bool,
    downgrade: DowngradeAuthorization | None,
) -> str:
    if human_elevated:
        if downgrade is not None:
            raise RiskRoutingError("human-elevated High Risk cannot be downgraded")
        return HIGH_RISK
    if downgrade is not None:
        if not triggers:
            raise RiskRoutingError("downgrade requires a High Risk condition")
        _validate_downgrade(downgrade)
        return downgrade.target_gear
    return HIGH_RISK if triggers else requested_gear


def _validate_downgrade(authorization: DowngradeAuthorization) -> None:
    values = (authorization.authorized_by, authorization.target_gear,
              authorization.rationale, authorization.authorization_id)
    if any(not isinstance(value, str) for value in values):
        raise RiskRoutingError("downgrade rationale and ID must be strings")
    if authorization.authorized_by != "human":
        raise RiskRoutingError("downgrade must be authorized by human")
    if authorization.target_gear not in DOWNGRADE_GEARS:
        raise RiskRoutingError("downgrade target gear is invalid")
    if not authorization.rationale.strip() or not authorization.authorization_id.strip():
        raise RiskRoutingError("downgrade authorization requires rationale and ID")


def validate_downgrade_authorization(
    authorization: DowngradeAuthorization,
) -> DowngradeAuthorization:
    """Validate and return a downgrade record for downstream evidence."""

    if not isinstance(authorization, DowngradeAuthorization):
        raise RiskRoutingError("downgrade authorization has invalid type")
    _validate_downgrade(authorization)
    return authorization


def _downgrade_record(
    authorization: DowngradeAuthorization | None,
) -> DowngradeAuthorization | None:
    if authorization is None:
        return None
    _validate_downgrade(authorization)
    return authorization
