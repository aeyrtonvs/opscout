# SPDX-License-Identifier: Apache-2.0
"""recent_changes (spec 011, FR-011, FR-022; research R12)."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from opscout.services.tools.runtime import run_tool
from tests.unit.mcp.fakes import FakeGateway, FakeTime, tool_context

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
PLANTED = "planted-value-never-returned"


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 011."""
    return pytest.mark.spec("011", requirement)


def _trail_event(minutes: int, name: str, read_only: str = "false") -> dict[str, Any]:
    return {
        "EventId": f"id-{minutes}",
        "EventName": name,
        "ReadOnly": read_only,
        "EventTime": NOW - timedelta(minutes=minutes),
        "EventSource": "ecs.amazonaws.com",
        "Username": "deployer",
        "Resources": [{"ResourceType": "AWS::ECS::Service", "ResourceName": "example-api"}],
        "CloudTrailEvent": json.dumps(
            {
                "userIdentity": {"arn": "arn:aws:sts::123456789012:assumed-role/deployer/ci"},
                "errorCode": "InvalidParameterException" if name == "UpdateService" else None,
                "errorMessage": "bad" if name == "UpdateService" else None,
                "requestParameters": {"environment": [{"name": "DB_PASS", "value": PLANTED}]},
                "responseElements": {"echo": PLANTED},
            }
        ),
    }


def _stack(name: str, minutes: int) -> dict[str, Any]:
    return {
        "StackName": name,
        "StackStatus": "UPDATE_COMPLETE",
        "CreationTime": NOW - timedelta(days=30),
        "LastUpdatedTime": NOW - timedelta(minutes=minutes),
    }


def _stack_event(stack: str, minutes: int, status: str = "UPDATE_COMPLETE") -> dict[str, Any]:
    return {
        "StackName": stack,
        "LogicalResourceId": "Service",
        "PhysicalResourceId": "arn:aws:ecs:us-east-1:123456789012:service/example/example-api",
        "ResourceType": "AWS::ECS::Service",
        "Timestamp": NOW - timedelta(minutes=minutes),
        "ResourceStatus": status,
        "ResourceStatusReason": "Resource update failed" if "FAILED" in status else None,
        "ResourceProperties": json.dumps({"Environment": [{"Value": PLANTED}]}),
    }


def _gateway(**extra: Any) -> FakeGateway:
    return FakeGateway(
        responses={
            "cloudtrail:LookupEvents": {
                "Events": [
                    _trail_event(5, "UpdateService"),
                    _trail_event(30, "RegisterTaskDefinition"),
                    _trail_event(40, "DescribeServices", read_only="true"),
                ],
                "NextToken": "more",
            },
            "cloudformation:DescribeStacks": {
                "Stacks": [_stack("example-api", 10), _stack("example-old", 60 * 48)]
            },
            "cloudformation:DescribeStackEvents": {
                "StackEvents": [
                    _stack_event("example-api", 10, "UPDATE_FAILED"),
                    _stack_event("example-api", 60 * 30),
                ]
            },
            **extra,
        }
    )


def _run(gateway: FakeGateway, time: FakeTime | None = None, **arguments: Any) -> Any:
    return run_tool(
        "recent_changes",
        {"environment": "example-prod", **arguments},
        tool_context(gateway, time=time),
    )


@spec("FR-022")
def test_cloudtrail_writes_and_stack_events_merge_newest_first() -> None:
    gateway = _gateway()

    failed, result = _run(gateway)

    assert not failed
    changes = result["data"]["changes"]
    assert [(c["source"], c["action"]) for c in changes] == [
        ("cloudtrail", "UpdateService"),
        ("cloudformation", "UPDATE_FAILED"),
        ("cloudtrail", "RegisterTaskDefinition"),
    ]
    first = changes[0]
    assert first["actor"] == "arn:aws:sts::123456789012:assumed-role/deployer/ci"
    assert first["target"] == "example-api"
    assert first["error"] == "InvalidParameterException: bad"
    assert changes[1]["target"] == "example-api/Service"
    assert changes[1]["error"] == "Resource update failed"
    assert result["data"]["more"] == {"cloudtrail": True, "cloudformation": False}
    lookup = gateway.calls[0][3]
    assert lookup["LookupAttributes"] == [{"AttributeKey": "ReadOnly", "AttributeValue": "false"}]
    assert lookup["StartTime"] == NOW - timedelta(hours=24)
    events = [call for call in gateway.calls if call[2] == "cloudformation:DescribeStackEvents"]
    assert [call[3]["StackName"] for call in events] == ["example-api"]


@spec("FR-022")
def test_no_request_response_or_resource_properties_reach_the_output() -> None:
    failed, result = _run(_gateway())

    assert not failed
    text = json.dumps(result)
    assert PLANTED not in text
    assert "requestParameters" not in text
    assert "ResourceProperties" not in text


@spec("FR-022")
def test_a_resource_narrows_cloudtrail_and_adds_its_own_source() -> None:
    gateway = _gateway(
        **{
            "ecs:ListServiceDeployments": {
                "serviceDeployments": [
                    {
                        "serviceDeploymentArn": "arn:aws:ecs:us-east-1:123456789012:sd/1",
                        "createdAt": NOW - timedelta(minutes=7),
                        "status": "ROLLBACK_SUCCESSFUL",
                        "statusReason": "circuit breaker",
                    }
                ]
            }
        }
    )

    failed, result = _run(gateway, resource_type="ecs-service", resource="example/example-api")

    assert not failed
    lookup = gateway.calls[0][3]
    assert lookup["LookupAttributes"] == [
        {"AttributeKey": "ResourceName", "AttributeValue": "example-api"}
    ]
    sources = [c["source"] for c in result["data"]["changes"]]
    assert "ecs" in sources
    deployment = next(c for c in result["data"]["changes"] if c["source"] == "ecs")
    assert (deployment["status"], deployment["error"]) == ("ROLLBACK_SUCCESSFUL", "circuit breaker")
    listed = next(call for call in gateway.calls if call[2] == "ecs:ListServiceDeployments")
    assert (listed[3]["cluster"], listed[3]["service"]) == ("example", "example-api")


@spec("FR-022")
@pytest.mark.parametrize(
    ("resource_type", "action", "response"),
    [
        (
            "autoscaling-group",
            "autoscaling:DescribeScalingActivities",
            {
                "Activities": [
                    {
                        "StartTime": NOW - timedelta(minutes=3),
                        "Description": "Launching a new EC2 instance",
                        "StatusCode": "Successful",
                    }
                ]
            },
        ),
        (
            "rds-instance",
            "rds:DescribeEvents",
            {"Events": [{"Date": NOW - timedelta(minutes=3), "Message": "DB instance restarted"}]},
        ),
    ],
)
def test_scaling_activities_and_database_events_are_changes(
    resource_type: str, action: str, response: dict[str, Any]
) -> None:
    gateway = _gateway(**{action: response})

    failed, result = _run(gateway, resource_type=resource_type, resource="example-db")

    assert not failed
    assert result["data"]["changes"][0]["time"] == "2026-11-06T11:57:00+00:00"


@spec("FR-011")
def test_the_tool_stops_calling_at_its_deadline_and_returns_partial() -> None:
    time = FakeTime()
    stacks = [_stack(f"example-{index}", 10 + index) for index in range(25)]
    gateway = _gateway(**{"cloudformation:DescribeStacks": {"Stacks": stacks}})
    gateway.delay = lambda: time.sleep(10)

    failed, result = _run(gateway, time=time)

    assert not failed
    assert result["partial"] is True
    assert time.now - 1000.0 < 60
    examined = [call for call in gateway.calls if call[2] == "cloudformation:DescribeStackEvents"]
    assert len(examined) <= 10


@spec("FR-011")
def test_at_most_the_stacks_cap_is_examined_most_recent_first() -> None:
    stacks = [_stack(f"example-{index}", 10 + index) for index in range(15)]
    gateway = _gateway(**{"cloudformation:DescribeStacks": {"Stacks": stacks}})

    failed, _ = _run(gateway)

    assert not failed
    examined = [c[3]["StackName"] for c in gateway.calls if c[2].endswith("DescribeStackEvents")]
    assert examined == [f"example-{index}" for index in range(10)]
