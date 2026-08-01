from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

from scripts.lib.risk_routing import (  # noqa: E402
    HIGH_RISK_TRIGGERS,
    DowngradeAuthorization,
    RiskRoutingError,
    route_risk,
)


EXPECTED_HIGH_RISK_TRIGGERS = (
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


def signals(**overrides: bool) -> dict[str, bool]:
    values = {trigger: False for trigger in EXPECTED_HIGH_RISK_TRIGGERS}
    values.update(overrides)
    return values


def test_routes_catalog_triggers_to_high_risk() -> None:
    assert HIGH_RISK_TRIGGERS == EXPECTED_HIGH_RISK_TRIGGERS
    for trigger in EXPECTED_HIGH_RISK_TRIGGERS:
        decision = route_risk("Build", signals(**{trigger: True}))
        assert decision.effective_gear == "High Risk"
        assert decision.triggers == (trigger,)

    assert route_risk("Small Change", signals()).effective_gear == "Small Change"


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: route_risk("Build", {"unknown": True}), "unknown trigger"),
        (lambda: route_risk("Build", signals(**{HIGH_RISK_TRIGGERS[0]: "yes"})), "boolean"),
        (lambda: route_risk("Discuss", signals()), "requested gear"),
        (lambda: route_risk("Build", signals(), human_elevated="yes"), "human"),
    ],
)
def test_rejects_unknown_or_malformed_risk_inputs(factory, message: str) -> None:
    with pytest.raises(RiskRoutingError, match=message):
        factory()


def test_rejects_non_mapping_signals() -> None:
    with pytest.raises(RiskRoutingError, match="mapping"):
        route_risk("Build", [])


def test_requires_and_records_human_downgrade_authorization() -> None:
    risky = signals(**{HIGH_RISK_TRIGGERS[0]: True})

    assert route_risk("Build", risky).effective_gear == "High Risk"

    with pytest.raises(RiskRoutingError, match="human"):
        route_risk(
            "Build",
            risky,
            downgrade=DowngradeAuthorization("software_engineer", "Build", "auth", "a1"),
        )

    decision = route_risk(
        "Build",
        risky,
        downgrade=DowngradeAuthorization("human", "Build", "documented exception", "a1"),
    )
    assert decision.effective_gear == "Build"
    assert decision.triggers == (HIGH_RISK_TRIGGERS[0],)
    assert decision.downgrade == DowngradeAuthorization(
        "human", "Build", "documented exception", "a1"
    )
    with pytest.raises(FrozenInstanceError):
        decision.downgrade.authorization_id = "tampered"
    record = decision.as_record()
    record["downgrade"]["authorization_id"] = "tampered"
    assert decision.downgrade.authorization_id == "a1"


def test_human_elevation_cannot_be_downgraded() -> None:
    authorization = DowngradeAuthorization("human", "Build", "reviewed", "a2")

    with pytest.raises(RiskRoutingError, match="elevated"):
        route_risk("Build", signals(), human_elevated=True, downgrade=authorization)

    with pytest.raises(RiskRoutingError, match="downgrade"):
        route_risk("Build", signals(), downgrade=authorization)


def test_rejects_non_string_downgrade_fields() -> None:
    authorization = DowngradeAuthorization("human", "Build", None, "a3")

    with pytest.raises(RiskRoutingError, match="rationale"):
        route_risk("Build", signals(**{HIGH_RISK_TRIGGERS[0]: True}), downgrade=authorization)


def test_orders_multiple_triggers_and_preserves_the_record() -> None:
    active = {HIGH_RISK_TRIGGERS[2]: True, HIGH_RISK_TRIGGERS[0]: True}
    decision = route_risk("Build", signals(**active))

    assert decision.triggers == (HIGH_RISK_TRIGGERS[0], HIGH_RISK_TRIGGERS[2])
    assert decision.as_record()["effective_gear"] == "High Risk"


def test_rejects_incomplete_trigger_snapshot() -> None:
    with pytest.raises(RiskRoutingError, match="complete"):
        route_risk("Build", {})


@pytest.mark.parametrize(
    "authorization",
    [
        DowngradeAuthorization("human", "Discuss", "reviewed", "a4"),
        DowngradeAuthorization("human", "Build", " ", "a4"),
        DowngradeAuthorization("human", "Build", "reviewed", " "),
    ],
)
def test_rejects_invalid_downgrade_metadata(authorization) -> None:
    with pytest.raises(RiskRoutingError, match="downgrade"):
        route_risk(
            "Build",
            signals(**{HIGH_RISK_TRIGGERS[0]: True}),
            downgrade=authorization,
        )
