# SPDX-License-Identifier: Apache-2.0
"""read_alarm and read_metric (spec 011, FR-012, FR-013, FR-019, FR-020)."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from opscout.services.tools.runtime import run_tool
from tests.unit.mcp.fakes import FakeGateway, tool_context

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
ALARM = {
    "AlarmName": "example-api-cpu",
    "StateValue": "ALARM",
    "StateReason": "Threshold Crossed: 1 datapoint [95.0] was greater than the threshold (90.0).",
    "StateUpdatedTimestamp": NOW - timedelta(minutes=20),
    "Threshold": 90.0,
    "ComparisonOperator": "GreaterThanThreshold",
    "Namespace": "AWS/ECS",
    "MetricName": "CPUUtilization",
    "Dimensions": [{"Name": "ServiceName", "Value": "example-api"}],
    "Period": 60,
    "Statistic": "Average",
    "EvaluationPeriods": 3,
    "AlarmActions": ["arn:aws:sns:us-east-1:123456789012:example-alerts"],
}
HISTORY = {
    "AlarmHistoryItems": [
        {
            "Timestamp": NOW - timedelta(minutes=20),
            "HistorySummary": "Alarm updated from OK to ALARM",
        }
    ]
}


def _series(count: int) -> dict[str, Any]:
    times = [NOW - timedelta(minutes=count - index) for index in range(count)]
    return {
        "MetricDataResults": [
            {"Id": "m1", "Timestamps": times, "Values": [float(i) for i in range(count)]}
        ]
    }


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 011."""
    return pytest.mark.spec("011", requirement)


def _alarm_gateway(points: int = 3) -> FakeGateway:
    return FakeGateway(
        responses={
            "cloudwatch:DescribeAlarms": {"MetricAlarms": [ALARM]},
            "cloudwatch:DescribeAlarmHistory": HISTORY,
            "cloudwatch:GetMetricData": _series(points),
        }
    )


@spec("FR-019")
def test_read_alarm_returns_state_threshold_history_and_datapoints() -> None:
    gateway = _alarm_gateway()

    failed, result = run_tool(
        "read_alarm",
        {"environment": "example-prod", "name": "example-api-cpu", "last": "1h"},
        tool_context(gateway),
    )

    assert not failed
    alarm = result["data"]["alarm"]
    assert alarm["name"] == "example-api-cpu"
    assert (alarm["state"], alarm["threshold"], alarm["comparison"]) == (
        "ALARM",
        90.0,
        "GreaterThanThreshold",
    )
    assert alarm["metric"] == {
        "namespace": "AWS/ECS",
        "name": "CPUUtilization",
        "dimensions": {"ServiceName": "example-api"},
        "statistic": "Average",
        "period": 60,
    }
    assert result["data"]["history"] == [
        {"time": "2026-11-06T11:40:00+00:00", "summary": "Alarm updated from OK to ALARM"}
    ]
    assert len(result["data"]["datapoints"]) == 3
    query = gateway.calls[-1][3]
    assert query["MetricDataQueries"][0]["MetricStat"]["Metric"]["MetricName"] == "CPUUtilization"
    assert query["StartTime"] == NOW - timedelta(hours=1)


@spec("FR-019")
def test_an_unknown_alarm_is_not_found() -> None:
    gateway = FakeGateway(responses={"cloudwatch:DescribeAlarms": {"MetricAlarms": []}})

    failed, result = run_tool(
        "read_alarm", {"environment": "example-prod", "name": "missing"}, tool_context(gateway)
    )

    assert failed
    assert result["error"]["reason"] == "not-found"


@spec("FR-012")
@pytest.mark.parametrize(
    ("environment", "identity"),
    [("example-prod", "reference identity"), ("example-dev", "own identity, not verified")],
)
def test_every_cloud_result_states_its_environment_and_identity(
    environment: str, identity: str
) -> None:
    failed, result = run_tool(
        "read_alarm",
        {"environment": environment, "name": "example-api-cpu"},
        tool_context(_alarm_gateway()),
    )

    assert not failed
    assert (result["environment"], result["identity"]) == (environment, identity)


@spec("FR-013")
def test_times_are_in_the_configured_timezone_with_their_offset() -> None:
    failed, result = run_tool(
        "read_alarm",
        {"environment": "example-prod", "name": "example-api-cpu"},
        tool_context(_alarm_gateway()),
    )

    assert not failed
    assert result["timezone"] == "Europe/Lisbon"
    assert result["window"] == {
        "start": "2026-11-06T09:00:00+00:00",
        "end": "2026-11-06T12:00:00+00:00",
    }
    assert result["data"]["alarm"]["updated"] == "2026-11-06T11:40:00+00:00"


@spec("FR-020")
def test_read_metric_returns_datapoints_by_statistic_and_period() -> None:
    gateway = FakeGateway(responses={"cloudwatch:GetMetricData": _series(4)})

    failed, result = run_tool(
        "read_metric",
        {
            "environment": "example-prod",
            "namespace": "AWS/ApplicationELB",
            "metric": "TargetResponseTime",
            "dimensions": {"LoadBalancer": "app/example-alb/0123456789abcdef"},
            "statistic": "p99",
            "period": 120,
            "region": "us-west-2",
        },
        tool_context(gateway),
    )

    assert not failed
    assert result["data"]["statistic"] == "p99"
    assert [point["value"] for point in result["data"]["datapoints"]] == [0.0, 1.0, 2.0, 3.0]
    _, region, action, params = gateway.calls[0]
    assert (region, action) == ("us-west-2", "cloudwatch:GetMetricData")
    stat = params["MetricDataQueries"][0]["MetricStat"]
    assert (stat["Stat"], stat["Period"]) == ("p99", 120)
    assert stat["Metric"]["Dimensions"] == [
        {"Name": "LoadBalancer", "Value": "app/example-alb/0123456789abcdef"}
    ]


@spec("FR-020")
def test_no_datapoints_checks_whether_the_metric_exists() -> None:
    gateway = FakeGateway(
        responses={
            "cloudwatch:GetMetricData": _series(0),
            "cloudwatch:ListMetrics": {"Metrics": []},
        }
    )

    failed, result = run_tool(
        "read_metric",
        {"environment": "example-prod", "namespace": "AWS/ECS", "metric": "Nope"},
        tool_context(gateway),
    )

    assert failed
    assert result["error"]["reason"] == "not-found"
    assert gateway.calls[-1][2] == "cloudwatch:ListMetrics"


@spec("FR-020")
@pytest.mark.parametrize(
    "bad",
    [{"statistic": "Median"}, {"period": 90}, {"period": 0}, {"period": 86_460}],
)
def test_a_bad_statistic_or_period_is_invalid_input(bad: dict[str, Any]) -> None:
    arguments = {"environment": "example-prod", "namespace": "AWS/ECS", "metric": "x", **bad}

    failed, result = run_tool("read_metric", arguments, tool_context(FakeGateway()))

    assert failed
    assert result["error"]["reason"] == "invalid-input"


@spec("FR-011")
def test_datapoints_beyond_the_cap_are_dropped_and_recorded() -> None:
    gateway = _alarm_gateway(points=600)

    failed, result = run_tool(
        "read_alarm",
        {"environment": "example-prod", "name": "example-api-cpu"},
        tool_context(gateway),
    )

    assert not failed
    assert len(result["data"]["datapoints"]) == 500
    assert {"cap": "datapoints", "limit": 500, "dropped": 100} in result["capped"]
