# SPDX-License-Identifier: Apache-2.0
"""Faults found by the independent review (spec 011, T045).

Each test reproduces one finding that passed the earlier suite: secret shapes redaction
missed (H1, M1), unredacted error messages (M2), a datapoints cap that could not fire (M3),
a read timeout and retry that broke the 60 s bound (M4), a deadline that threw away what a
tool had found (M5), a change without a time (L1) and silent slices (L2).
"""

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from opscout.adapters.aws_live import LiveGateway
from opscout.core.config import AwsEnvironment
from opscout.core.tools import ErrorReason, ToolError
from opscout.services.redact import redact, redact_structure
from opscout.services.tools.runtime import run_tool
from tests.unit.mcp.fakes import FakeGateway, FakeTime, tool_context

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
KEEP = frozenset({"account-id", "ip", "email"})
PROD = AwsEnvironment(
    name="example-prod", account_id="123456789012", profile="example-prod", regions=["us-east-1"]
)


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 011."""
    return pytest.mark.spec("011", requirement)


@spec("FR-009")
@pytest.mark.parametrize(
    "text",
    [
        '{"DB_PASSWORD":"hunter2xyz"}',
        '{"password": "hunter2xyz", "user": "app"}',
        "MYSQL_PWD=hunter2xyz",
        "DB_PASS=hunter2xyz",
        "run --password hunter2xyz now",
        "Authorization: Bearer abcdEFGH1234ijkl",
        "postgres://user:hun/ter2xyz@db.example.com/db",
        "client_credentials=hunter2xyz",
    ],
)
def test_common_secret_shapes_are_redacted(text: str) -> None:
    redacted, counts = redact(text, keep=KEEP)

    assert "hunter2xyz" not in redacted
    assert "ter2xyz" not in redacted
    assert "abcdEFGH1234ijkl" not in redacted
    assert counts, text


@spec("FR-009")
def test_ordinary_words_near_secret_names_survive() -> None:
    for text in ("author: jane", "passport office", "auth flow changed", "bypass mode"):
        assert redact(text, keep=KEEP) == (text, {}), text


@spec("FR-009")
@pytest.mark.parametrize("name", ["DB_PASS", "AdminPwd", "auth", "DbCredentials"])
def test_secret_named_tags_and_keys_hide_their_values(name: str) -> None:
    value = {"tags": [{"Key": name, "Value": "plain-1"}], name: "plain-2"}

    redacted, counts = redact_structure(value, KEEP)

    assert "plain" not in json.dumps(redacted)
    assert counts == {"secret": 2}


@spec("FR-009")
def test_error_messages_are_redacted_like_data() -> None:
    config = (
        "schema_version: 1\naws:\n  environments:\n"
        "    - {name: example-prod, account_id: '123456789012', profile: p, regions: [us-east-1]}\n"
        "tools:\n  redact: {account_ids: true}\n"
    )
    message = (
        "arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/x password=hunter2xyz"
    )
    gateway = FakeGateway(
        responses={
            "elasticloadbalancing:DescribeLoadBalancers": ToolError(
                ErrorReason.INVALID_INPUT, message
            )
        }
    )

    failed, result = run_tool(
        "describe_resource",
        {"environment": "example-prod", "type": "load-balancer", "name": "x"},
        tool_context(gateway, config=config),
    )

    assert failed
    assert "hunter2xyz" not in result["error"]["message"]
    assert "123456789012" not in result["error"]["message"]
    assert result["redacted"] == {"account-id": 1, "credential": 1}


def _honoring(params: Mapping[str, Any]) -> Mapping[str, Any]:
    """GetMetricData as AWS answers it: at most MaxDatapoints, in the asked order."""
    times = [NOW - timedelta(minutes=minute) for minute in range(2_000)]
    if params.get("ScanBy") == "TimestampAscending":
        times.reverse()
    limit = params["MaxDatapoints"]
    page = times[:limit]
    return {
        "MetricDataResults": [
            {"Id": "m1", "Timestamps": page, "Values": [float(i) for i in range(len(page))]}
        ],
        "NextToken": "more" if len(times) > limit else None,
    }


@spec("FR-011")
def test_the_datapoints_cap_keeps_the_newest_points_and_says_so() -> None:
    gateway = FakeGateway(responses={"cloudwatch:GetMetricData": _honoring})

    failed, result = run_tool(
        "read_metric",
        {"environment": "example-prod", "namespace": "AWS/EC2", "metric": "m", "last": "14d"},
        tool_context(gateway),
    )

    assert not failed
    points = result["data"]["datapoints"]
    assert len(points) == 500
    assert points[-1]["time"] == "2026-11-06T12:00:00+00:00"
    assert points == sorted(points, key=lambda point: point["time"])
    assert any(entry["cap"] == "datapoints" for entry in result["capped"])


@spec("FR-011")
@pytest.mark.parametrize("remaining", [45.0, 30.0, 20.0, 10.0, 2.0, 0.5, 0.0])
def test_a_call_can_never_outlast_its_budget(remaining: float) -> None:
    """Every attempt, connect plus read, fits in the time left plus the 10 s grace."""
    gateway = LiveGateway(session_factory=lambda profile: _session())
    config: Any = gateway.client(PROD, "us-east-1", "logs", remaining).meta.config
    attempts = config.retries["total_max_attempts"]

    worst = attempts * (config.connect_timeout + config.read_timeout) + (attempts - 1) * 1
    assert worst <= remaining + 10, (remaining, attempts, config.read_timeout)
    assert config.read_timeout >= 1


def _session() -> Any:
    import boto3

    return boto3.session.Session(
        aws_access_key_id="AKIAEXAMPLEEXAMPLE12",
        aws_secret_access_key="example-secret-not-real",  # noqa: S106
        region_name="us-east-1",
    )


@spec("FR-021")
def test_slow_polls_still_stop_the_query_and_keep_their_rows() -> None:
    time = FakeTime()
    rows = [[{"field": "@message", "value": "first row"}]]
    gateway = FakeGateway(
        responses={
            "logs:StartQuery": {"queryId": "q"},
            "logs:GetQueryResults": {"status": "Running", "results": rows},
            "logs:StopQuery": {"success": True},
        }
    )
    gateway.delay = lambda: time.sleep(1.5)

    failed, result = run_tool(
        "query_logs",
        {"environment": "example-prod", "log_groups": ["/g"], "query": "q"},
        tool_context(gateway, time=time),
    )

    assert not failed
    assert result["partial"] is True
    assert result["environment"] == "example-prod"
    assert result["data"]["rows"] == [{"@message": "first row"}]
    assert gateway.calls[-1][2] == "logs:StopQuery"
    assert time.now - 1000.0 < 60


@spec("FR-011")
def test_a_deadline_keeps_the_environment_and_what_was_found() -> None:
    time = FakeTime()
    service = {"serviceName": "example-api", "clusterArn": "arn:c/one"}
    gateway = FakeGateway(
        responses={
            "ecs:ListClusters": {"clusterArns": [f"arn:c/{index}" for index in range(10)]},
            "ecs:DescribeServices": [{"services": [service]}, {"services": []}],
        }
    )
    gateway.delay = lambda: time.sleep(10)

    failed, result = run_tool(
        "describe_resource",
        {"environment": "example-prod", "type": "ecs-service", "name": "example-api"},
        tool_context(gateway, time=time),
    )

    assert not failed
    assert result["partial"] is True
    assert result["environment"] == "example-prod"
    assert result["data"]["configuration"]["name"] == "example-api"


@spec("FR-022")
def test_a_change_without_a_time_does_not_break_the_list() -> None:
    gateway = FakeGateway(
        responses={
            "cloudtrail:LookupEvents": {
                "Events": [
                    {"EventName": "PutA", "ReadOnly": "false"},
                    {"EventName": "PutB", "ReadOnly": "false", "EventTime": NOW},
                ]
            },
            "cloudformation:DescribeStacks": {"Stacks": []},
        }
    )

    failed, result = run_tool(
        "recent_changes", {"environment": "example-prod"}, tool_context(gateway)
    )

    assert not failed
    assert [change["action"] for change in result["data"]["changes"]] == ["PutB", "PutA"]


@spec("FR-011")
def test_sliced_matches_are_recorded_and_clusters_are_paged() -> None:
    instances = [{"InstanceId": f"i-{index:017x}"} for index in range(30)]
    gateway = FakeGateway(
        responses={"ec2:DescribeInstances": {"Reservations": [{"Instances": instances}]}}
    )
    failed, result = run_tool(
        "describe_resource",
        {"environment": "example-prod", "type": "ec2-instance", "name": "example"},
        tool_context(gateway),
    )
    assert not failed
    assert len(result["data"]["matches"]) == 25
    assert {"cap": "resources", "limit": 25, "dropped": 5} in result["capped"]

    service = {"serviceName": "example-api", "clusterArn": "arn:c/late"}
    gateway = FakeGateway(
        responses={
            "ecs:ListClusters": [
                {"clusterArns": ["arn:c/a"], "nextToken": "page-2"},
                {"clusterArns": ["arn:c/late"]},
            ],
            "ecs:DescribeServices": [{"services": []}, {"services": [service]}],
        }
    )
    failed, result = run_tool(
        "describe_resource",
        {"environment": "example-prod", "type": "ecs-service", "name": "example-api"},
        tool_context(gateway),
    )
    assert not failed
    assert result["data"]["configuration"]["cluster"] == "arn:c/late"


@spec("FR-011")
def test_a_deadline_before_anything_is_found_is_partial_with_its_environment() -> None:
    time = FakeTime()
    pages = {"clusterArns": ["arn:c/x"], "nextToken": "more"}
    gateway = FakeGateway(
        responses={"ecs:ListClusters": pages, "ecs:DescribeServices": {"services": []}}
    )
    gateway.delay = lambda: time.sleep(6)

    failed, result = run_tool(
        "describe_resource",
        {"environment": "example-prod", "type": "ecs-service", "name": "example-api"},
        tool_context(gateway, time=time),
    )

    assert not failed
    assert result["partial"] is True
    assert result["environment"] == "example-prod"
    assert result["data"] == {}
    listed = [call for call in gateway.calls if call[2] == "ecs:ListClusters"]
    assert len(listed) == 5
