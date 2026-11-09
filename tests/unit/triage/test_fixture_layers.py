# SPDX-License-Identifier: Apache-2.0
"""Mock mode for the triage evals: layered roots and list matching (spec 012, FR-027; R12)."""

import json
from pathlib import Path

import pytest

from opscout.adapters.aws_fixtures import FixtureGateway
from opscout.core.config import AwsEnvironment

ENVIRONMENT = AwsEnvironment(
    name="example-prod", account_id="123456789012", profile="example-prod", regions=["us-east-1"]
)
ACTION = "cloudwatch:GetMetricData"
ALLOWED = frozenset({ACTION, "cloudwatch:DescribeAlarms"})


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 012."""
    return pytest.mark.spec("012", requirement)


def write(root: Path, action: str, entries: list[dict[str, object]]) -> None:
    prefix, operation = action.split(":")
    path = root / "example-prod" / prefix / f"{operation}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries), encoding="utf-8")


def query(period: int) -> dict[str, object]:
    return {"MetricDataQueries": [{"Id": "m1", "MetricStat": {"Period": period, "Stat": "Sum"}}]}


@spec("FR-027")
def test_a_scenario_overrides_the_base_file_by_file(tmp_path: Path) -> None:
    base, scenario = tmp_path / "base", tmp_path / "scenario"
    write(base, ACTION, [{"match": {}, "response": {"from": "base"}}])
    write(base, "cloudwatch:DescribeAlarms", [{"match": {}, "response": {"from": "base"}}])
    write(scenario, ACTION, [{"match": {}, "response": {"from": "scenario"}}])
    gateway = FixtureGateway([scenario, base])
    assert gateway.call(ENVIRONMENT, "us-east-1", ACTION, {}, ALLOWED, 1.0) == {"from": "scenario"}
    alarms = gateway.call(ENVIRONMENT, "us-east-1", "cloudwatch:DescribeAlarms", {}, ALLOWED, 1.0)
    assert alarms == {"from": "base"}


@spec("FR-027")
def test_a_list_in_match_matches_item_by_item(tmp_path: Path) -> None:
    history = {"MetricDataQueries": [{"MetricStat": {"Period": 3600}}]}
    write(
        tmp_path,
        ACTION,
        [
            {"match": history, "response": {"window": "history"}},
            {"match": {}, "response": {"window": "alert"}},
        ],
    )
    gateway = FixtureGateway(tmp_path)
    assert gateway.call(ENVIRONMENT, "us-east-1", ACTION, query(3600), ALLOWED, 1.0) == {
        "window": "history"
    }
    assert gateway.call(ENVIRONMENT, "us-east-1", ACTION, query(300), ALLOWED, 1.0) == {
        "window": "alert"
    }
