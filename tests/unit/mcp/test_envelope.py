# SPDX-License-Identifier: Apache-2.0
"""What every tool's result shares (spec 011, FR-009, FR-011; SC-003, SC-004)."""

import json
import threading
from datetime import UTC, datetime
from typing import Any

import pytest

from opscout.core.tools import ErrorReason, ToolError
from opscout.services.tools.runtime import run_tool
from tests.unit.mcp.fakes import FakeGateway, FakeTime, tool_context

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
LEAK = "postgres://admin:hunter2pass@db.example.com:5432/app"
KEY = "AKIAEXAMPLEEXAMPLE12"
SECRET_LIKE = "Zx9" * 12


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 011."""
    return pytest.mark.spec("011", requirement)


def _leaky(text: str) -> str:
    return f"{text} {LEAK} key={KEY} token {SECRET_LIKE}"


LEAKY: dict[str, Any] = {
    "cloudwatch:DescribeAlarms": {
        "MetricAlarms": [{"AlarmName": "a", "StateReason": _leaky("reason"), "MetricName": "m"}]
    },
    "cloudwatch:DescribeAlarmHistory": {
        "AlarmHistoryItems": [{"Timestamp": NOW, "HistorySummary": _leaky("summary")}]
    },
    "cloudwatch:GetMetricData": {"MetricDataResults": [{"Timestamps": [NOW], "Values": [1.0]}]},
    "logs:StartQuery": {"queryId": "q"},
    "logs:GetQueryResults": {
        "status": "Complete",
        "results": [[{"field": "@message", "value": _leaky("log line")}]],
    },
    "cloudtrail:LookupEvents": {
        "Events": [{"EventName": _leaky("x"), "ReadOnly": "false", "EventTime": NOW}]
    },
    "cloudformation:DescribeStacks": {"Stacks": []},
    "tag:GetResources": {
        "ResourceTagMappingList": [
            {
                "ResourceARN": "arn:aws:ec2:us-east-1:123456789012:instance/i-0123456789abcdef0",
                "Tags": [{"Key": "Name", "Value": _leaky("example")}],
            }
        ]
    },
    "ec2:DescribeInstances": {
        "Reservations": [
            {
                "Instances": [
                    {
                        "InstanceId": "i-0123456789abcdef0",
                        "Tags": [{"Key": "Note", "Value": _leaky("n")}],
                    }
                ]
            }
        ]
    },
}
CALLS = [
    ("read_alarm", {"name": "a"}),
    ("read_metric", {"namespace": "AWS/EC2", "metric": "m"}),
    ("query_logs", {"log_groups": ["/g"], "query": "fields @message"}),
    ("recent_changes", {}),
    ("find_resources", {"name": "example"}),
    ("describe_resource", {"type": "ec2-instance", "name": "i-0123456789abcdef0"}),
]


@spec("FR-009")
@pytest.mark.parametrize(("tool", "arguments"), CALLS)
def test_no_planted_secret_reaches_any_output(tool: str, arguments: dict[str, Any]) -> None:
    failed, result = run_tool(
        tool,
        {"environment": "example-prod", **arguments},
        tool_context(FakeGateway(responses=dict(LEAKY))),
    )

    assert not failed, result
    text = json.dumps(result)
    for planted in ("hunter2pass", KEY, SECRET_LIKE):
        assert planted not in text, (tool, planted)
    if tool != "read_metric":  # its output is numbers only; nothing to plant in
        assert sum(result["redacted"].values()) >= 3, tool


@spec("FR-011")
def test_every_output_stays_within_its_size_cap() -> None:
    rows = [[{"field": "@message", "value": "x" * 3_000}] for _ in range(100)]
    gateway = FakeGateway(
        responses={
            "logs:StartQuery": {"queryId": "q"},
            "logs:GetQueryResults": {"status": "Complete", "results": rows},
        }
    )

    failed, result = run_tool(
        "query_logs",
        {"environment": "example-prod", "log_groups": ["/g"], "query": "fields @message"},
        tool_context(gateway),
    )

    assert not failed
    assert len(json.dumps(result)) <= 40_000
    assert any(entry["cap"] == "result_chars" for entry in result["capped"])
    assert result["data"]["rows"]


@spec("FR-011")
def test_a_configured_result_cap_is_honored() -> None:
    config = (
        "schema_version: 1\naws:\n  environments:\n"
        "    - {name: example-prod, account_id: '123456789012', profile: p, regions: [us-east-1]}\n"
        "tools:\n  caps:\n    result_chars: 5000\n"
    )
    rows = [[{"field": "@message", "value": "y" * 400}] for _ in range(50)]
    gateway = FakeGateway(
        responses={
            "logs:StartQuery": {"queryId": "q"},
            "logs:GetQueryResults": {"status": "Complete", "results": rows},
        }
    )

    failed, result = run_tool(
        "query_logs",
        {"environment": "example-prod", "log_groups": ["/g"], "query": "q"},
        tool_context(gateway, config=config),
    )

    assert not failed
    assert len(json.dumps(result)) <= 5_000


@spec("FR-004")
def test_an_unknown_environment_lists_the_configured_ones() -> None:
    failed, result = run_tool(
        "read_alarm", {"environment": "example-qa", "name": "a"}, tool_context(FakeGateway())
    )

    assert failed
    assert result["error"]["reason"] == "unknown-environment"
    assert "example-prod, example-dev" in result["error"]["message"]


@spec("FR-004")
def test_a_region_outside_the_environment_is_invalid_input() -> None:
    failed, result = run_tool(
        "read_alarm",
        {"environment": "example-dev", "name": "a", "region": "us-west-2"},
        tool_context(FakeGateway()),
    )

    assert failed
    assert result["error"]["reason"] == "invalid-input"


@spec("FR-004")
def test_parallel_calls_are_independent() -> None:
    gateway = FakeGateway(
        responses={
            **LEAKY,
            "tag:GetResources": ToolError(ErrorReason.THROTTLED, "slow down"),
        }
    )
    context = tool_context(gateway)
    results: dict[str, tuple[bool, Any]] = {}

    def run(tool: str, arguments: dict[str, Any]) -> None:
        results[tool] = run_tool(tool, {"environment": "example-prod", **arguments}, context)

    threads = [threading.Thread(target=run, args=call) for call in CALLS[:5]]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results["find_resources"][0] is True
    assert results["find_resources"][1]["error"]["reason"] == "throttled"
    assert [results[tool][0] for tool, _ in CALLS[:4]] == [False] * 4


@spec("FR-011")
@pytest.mark.parametrize(("tool", "arguments"), CALLS)
def test_every_tool_returns_within_sixty_seconds_against_a_slow_gateway(
    tool: str, arguments: dict[str, Any]
) -> None:
    time = FakeTime()
    gateway = FakeGateway(
        responses={
            **LEAKY,
            "logs:GetQueryResults": {"status": "Running", "results": []},
            "cloudformation:DescribeStacks": {
                "Stacks": [
                    {"StackName": f"s{index}", "LastUpdatedTime": NOW} for index in range(25)
                ]
            },
            "cloudformation:DescribeStackEvents": {"StackEvents": []},
        }
    )
    gateway.delay = lambda: time.sleep(10)

    run_tool(tool, {"environment": "example-prod", **arguments}, tool_context(gateway, time=time))

    assert time.now - 1000.0 < 60, tool
