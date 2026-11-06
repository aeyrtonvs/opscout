# SPDX-License-Identifier: Apache-2.0
"""Edge cases of the tools (spec 011, FR-004, FR-010, FR-011, FR-019 to FR-024)."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from opscout.core.aws import CallEntry
from opscout.core.tools import Caps, ErrorReason, Registry, ToolError, ToolSpec, fit
from opscout.services.redact import redact
from opscout.services.tools.runtime import run_tool
from tests.unit.mcp.fakes import FakeGateway, tool_context

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 011."""
    return pytest.mark.spec("011", requirement)


def _run(tool: str, gateway: FakeGateway, config: str | None = None, **arguments: Any) -> Any:
    context = tool_context(gateway) if config is None else tool_context(gateway, config=config)
    return run_tool(tool, {"environment": "example-prod", **arguments}, context)


@spec("FR-010")
def test_configured_redaction_kinds_apply_to_every_output() -> None:
    config = (
        "schema_version: 1\naws:\n  environments:\n"
        "    - {name: example-prod, account_id: '123456789012', profile: p, regions: [us-east-1]}\n"
        "tools:\n  redact: {account_ids: true, ips: true, emails: true}\n"
    )
    value = "owner ops@example.com at 192.0.2.10 in 123456789012"
    gateway = FakeGateway(
        responses={
            "tag:GetResources": {
                "ResourceTagMappingList": [
                    {"ResourceARN": "arn:x", "Tags": [{"Key": "Name", "Value": value}]}
                ]
            }
        }
    )

    failed, result = _run("find_resources", gateway, config, name="owner")

    assert not failed
    assert result["data"]["resources"][0]["name"] == "owner [email] at [ip] in [account-id]"
    assert result["redacted"] == {"email": 2, "ip": 2, "account-id": 2}


@spec("FR-011")
def test_shared_types_refuse_duplicates_and_fit_has_a_last_resort() -> None:
    with pytest.raises(ValueError, match="unique"):
        Registry((ToolSpec("a", "x"), ToolSpec("a", "y")))
    assert Caps().bound("log_rows", 10) == (10, None)
    flat = {f"key{index}": "v" * 3_000 for index in range(20)}
    fitted, capped = fit(flat, 10_000)
    assert fitted == {"omitted": "the result did not fit in 10000 characters"}
    assert capped[-1].cap == "result_chars"
    with pytest.raises(ValueError, match="may be kept"):
        redact("x", keep=frozenset({"phone"}))


@spec("FR-019")
def test_a_metric_math_alarm_has_no_datapoints_and_names_are_required() -> None:
    gateway = FakeGateway(
        responses={
            "cloudwatch:DescribeAlarms": {
                "MetricAlarms": [{"AlarmName": "math", "Metrics": [{"Id": "e1"}]}]
            },
            "cloudwatch:DescribeAlarmHistory": {},
        }
    )
    failed, result = _run("read_alarm", gateway, name="math")
    assert not failed
    assert result["data"]["datapoints"] == []
    assert result["data"]["alarm"]["metric_math"] is True

    failed, result = _run("read_alarm", FakeGateway())
    assert result["error"]["reason"] == "invalid-input"
    failed, result = _run("read_metric", FakeGateway(), metric="m")
    assert result["error"]["reason"] == "invalid-input"


@spec("FR-020")
def test_a_metric_that_exists_with_no_data_is_an_empty_series() -> None:
    gateway = FakeGateway(
        responses={
            "cloudwatch:GetMetricData": {"MetricDataResults": []},
            "cloudwatch:ListMetrics": {"Metrics": [{"MetricName": "m"}]},
        }
    )

    failed, result = _run("read_metric", gateway, namespace="AWS/EC2", metric="m")

    assert not failed
    assert result["data"]["datapoints"] == []


@spec("FR-017")
def test_parse_alert_needs_text() -> None:
    config = (
        "schema_version: 1\nalerts:\n  formats:\n"
        "    - {name: a, recognize: x, fields: {title: '(x)'}}\n"
    )
    failed, result = run_tool("parse_alert", {}, tool_context(FakeGateway(), config=config))
    assert failed
    assert result["error"]["reason"] == "invalid-input"


@spec("FR-022")
def test_changes_survive_odd_events_and_cap_each_source() -> None:
    config = (
        "schema_version: 1\naws:\n  environments:\n"
        "    - {name: example-prod, account_id: '123456789012', profile: p, regions: [us-east-1]}\n"
        "tools:\n  caps: {change_items: 2}\n"
    )
    events = [
        {
            "EventName": f"Put{index}",
            "ReadOnly": "false",
            "EventTime": NOW - timedelta(minutes=index),
            "CloudTrailEvent": "not json",
        }
        for index in range(3)
    ]
    gateway = FakeGateway(
        responses={
            "cloudtrail:LookupEvents": {"Events": events},
            "cloudformation:DescribeStacks": {"Stacks": []},
            "ecs:ListServiceDeployments": {"serviceDeployments": []},
        }
    )

    failed, result = _run(
        "recent_changes", gateway, config, resource_type="ecs-service", resource="example-api"
    )

    assert not failed
    assert [change["action"] for change in result["data"]["changes"]] == ["Put0", "Put1"]
    assert result["data"]["more"]["cloudtrail"] is True
    assert {"cap": "change_items:cloudtrail", "limit": 2, "dropped": 1} in result["capped"]
    listed = next(call for call in gateway.calls if call[2] == "ecs:ListServiceDeployments")
    assert "cluster" not in listed[3]


@spec("FR-021")
def test_a_failing_hint_lookup_and_other_errors_pass_through() -> None:
    query: dict[str, Any] = {"log_groups": ["/g"], "query": "fields @message"}
    gateway = FakeGateway(
        responses={
            "logs:StartQuery": ToolError(ErrorReason.NOT_FOUND, "missing"),
            "logs:DescribeLogGroups": ToolError(ErrorReason.DENIED, "no"),
        }
    )
    failed, result = _run("query_logs", gateway, **query)
    assert failed
    assert result["error"]["message"].endswith("a log group does not exist")

    gateway = FakeGateway(responses={"logs:StartQuery": ToolError(ErrorReason.DENIED, "no")})
    _failed, result = _run("query_logs", gateway, **query)
    assert result["error"]["reason"] == "denied"


class _BrokenLog:
    def append(self, entry: CallEntry) -> None:
        raise RuntimeError("disk on fire")


@spec("FR-004")
def test_a_broken_call_log_never_fails_the_call() -> None:
    context = tool_context(FakeGateway())
    context.call_log = _BrokenLog()

    failed, result = run_tool("list_environments", {}, context)

    assert not failed
    assert len(result["data"]["environments"]) == 2


@spec("FR-024")
def test_find_reads_pages_and_types_unknown_arns() -> None:
    gateway = FakeGateway(
        responses={
            "tag:GetResources": [
                {
                    "ResourceTagMappingList": [{"ResourceARN": "not-an-arn", "Tags": []}],
                    "PaginationToken": "next",
                },
                {
                    "ResourceTagMappingList": [
                        {"ResourceARN": "arn:aws:s3:::example-bucket", "Tags": []}
                    ],
                    "PaginationToken": "",
                },
            ]
        }
    )

    failed, result = _run("find_resources", gateway, name="example")

    assert not failed
    assert [r["type"] for r in result["data"]["resources"]] == ["other:s3"]
    assert gateway.calls[1][3]["PaginationToken"] == "next"
    failed, result = _run("find_resources", FakeGateway(), name="x", type="s3-bucket")
    assert result["error"]["reason"] == "not-supported"
    failed, result = _run(
        "find_resources",
        FakeGateway(
            responses={
                "tag:GetResources": {
                    "ResourceTagMappingList": [{"ResourceARN": "plain", "Tags": []}]
                }
            }
        ),
        name="plain",
    )
    assert result["data"]["resources"][0]["type"] == "other"


@spec("FR-023")
@pytest.mark.parametrize(
    ("kind", "responses"),
    [
        ("ecs-service", {"ecs:DescribeServices": {"services": []}}),
        ("rds-cluster", {"rds:DescribeDBClusters": {"DBClusters": []}}),
        ("ec2-instance", {"ec2:DescribeInstances": {"Reservations": []}}),
        ("load-balancer", {"elasticloadbalancing:DescribeLoadBalancers": {}}),
        ("target-group", {"elasticloadbalancing:DescribeTargetGroups": {}}),
        ("autoscaling-group", {"autoscaling:DescribeAutoScalingGroups": {}}),
        ("alarm", {"cloudwatch:DescribeAlarms": {}}),
        ("lambda-function", {"cloudformation:DescribeStackResources": {"StackResources": []}}),
    ],
)
def test_each_type_says_when_nothing_was_found(kind: str, responses: dict[str, Any]) -> None:
    name = "example/example-api" if kind == "ecs-service" else "example"

    failed, result = _run(
        "describe_resource", FakeGateway(responses=responses), type=kind, name=name
    )

    assert failed
    assert result["error"]["reason"] == "not-found", json.dumps(result)


@spec("FR-023")
def test_describe_needs_a_name_and_passes_other_stack_errors_through() -> None:
    failed, result = _run("describe_resource", FakeGateway(), type="alarm")
    assert failed
    assert result["error"]["reason"] == "invalid-input"

    gateway = FakeGateway(
        responses={
            "cloudformation:DescribeStackResources": ToolError(ErrorReason.THROTTLED, "slow")
        }
    )
    _failed, result = _run(
        "describe_resource",
        gateway,
        type="lambda-function",
        name="arn:aws:lambda:us-east-1:123456789012:function:example-worker",
    )
    assert result["error"]["reason"] == "throttled"


@spec("FR-024")
def test_running_out_of_pages_says_there_is_more() -> None:
    page = {"ResourceTagMappingList": [], "PaginationToken": "next"}
    gateway = FakeGateway(responses={"tag:GetResources": page})

    failed, result = _run("find_resources", gateway, name="example")

    assert not failed
    assert result["data"] == {"resources": [], "more": True}
    assert len(gateway.calls) == 5
