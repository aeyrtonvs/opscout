# SPDX-License-Identifier: Apache-2.0
"""find_resources and describe_resource (spec 011, FR-009, FR-023, FR-024)."""

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from opscout.core.tools import ErrorReason, ToolError
from opscout.services.tools.runtime import run_tool
from tests.unit.mcp.fakes import FakeGateway, tool_context

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
ACCOUNT = "123456789012"
SERVICE_ARN = f"arn:aws:ecs:us-east-1:{ACCOUNT}:service/example/example-api"


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 011."""
    return pytest.mark.spec("011", requirement)


def _describe(gateway: FakeGateway, kind: str, name: str) -> tuple[bool, Any]:
    return run_tool(
        "describe_resource",
        {"environment": "example-prod", "type": kind, "name": name},
        tool_context(gateway),
    )


def _mapping(arn: str, name: str | None = None, **tags: str) -> dict[str, Any]:
    pairs = [{"Key": key, "Value": value} for key, value in tags.items()]
    if name:
        pairs.append({"Key": "Name", "Value": name})
    return {"ResourceARN": arn, "Tags": pairs}


TAGGED = {
    "ResourceTagMappingList": [
        _mapping(SERVICE_ARN, team="api"),
        _mapping(f"arn:aws:ec2:us-east-1:{ACCOUNT}:instance/i-0123456789abcdef0", "example-api-1"),
        _mapping(f"arn:aws:rds:us-east-1:{ACCOUNT}:db:example-db", team="data"),
        _mapping(f"arn:aws:lambda:us-east-1:{ACCOUNT}:function:example-worker", ApiToken="abc"),
    ],
    "PaginationToken": "",
}


@spec("FR-024")
def test_find_by_name_matches_the_name_tag_or_the_arn() -> None:
    gateway = FakeGateway(responses={"tag:GetResources": TAGGED})

    failed, result = run_tool(
        "find_resources",
        {"environment": "example-prod", "name": "example-api"},
        tool_context(gateway),
    )

    assert not failed
    found = [(r["type"], r["name"]) for r in result["data"]["resources"]]
    assert found == [("ecs-service", "example-api"), ("ec2-instance", "example-api-1")]
    assert result["data"]["more"] is False


@spec("FR-024")
def test_find_by_tag_and_type_passes_the_filters() -> None:
    gateway = FakeGateway(responses={"tag:GetResources": TAGGED})

    failed, _ = run_tool(
        "find_resources",
        {
            "environment": "example-prod",
            "tag_key": "team",
            "tag_value": "api",
            "type": "ecs-service",
        },
        tool_context(gateway),
    )

    assert not failed
    params = gateway.calls[0][3]
    assert params["TagFilters"] == [{"Key": "team", "Values": ["api"]}]
    assert params["ResourceTypeFilters"] == ["ecs:service"]


@spec("FR-024")
def test_find_needs_a_name_or_a_tag_and_caps_its_results() -> None:
    failed, result = run_tool(
        "find_resources", {"environment": "example-prod"}, tool_context(FakeGateway())
    )
    assert failed
    assert result["error"]["reason"] == "invalid-input"

    many = {
        "ResourceTagMappingList": [
            _mapping(f"arn:aws:ec2:us-east-1:{ACCOUNT}:instance/i-{index:017x}", f"example-{index}")
            for index in range(40)
        ],
        "PaginationToken": "",
    }
    failed, result = run_tool(
        "find_resources",
        {"environment": "example-prod", "name": "example"},
        tool_context(FakeGateway(responses={"tag:GetResources": many})),
    )
    assert not failed
    assert len(result["data"]["resources"]) == 25
    assert result["data"]["more"] is True


@spec("FR-009")
def test_a_secret_named_tag_has_its_value_redacted() -> None:
    gateway = FakeGateway(responses={"tag:GetResources": TAGGED})

    failed, result = run_tool(
        "find_resources", {"environment": "example-prod", "name": "worker"}, tool_context(gateway)
    )

    assert not failed
    assert result["data"]["resources"][0]["tags"] == [{"Key": "ApiToken", "Value": "[secret]"}]


SERVICE = {
    "serviceName": "example-api",
    "serviceArn": SERVICE_ARN,
    "clusterArn": f"arn:aws:ecs:us-east-1:{ACCOUNT}:cluster/example",
    "status": "ACTIVE",
    "desiredCount": 2,
    "runningCount": 1,
    "pendingCount": 1,
    "launchType": "FARGATE",
    "taskDefinition": f"arn:aws:ecs:us-east-1:{ACCOUNT}:task-definition/example-api:42",
    "deployments": [
        {
            "status": "PRIMARY",
            "rolloutState": "IN_PROGRESS",
            "desiredCount": 2,
            "runningCount": 1,
            "createdAt": NOW,
            "taskDefinition": f"arn:aws:ecs:us-east-1:{ACCOUNT}:task-definition/example-api:42",
        }
    ],
    "loadBalancers": [{"targetGroupArn": "arn:tg", "containerName": "api", "containerPort": 8080}],
    "networkConfiguration": {
        "awsvpcConfiguration": {"subnets": ["subnet-1"], "securityGroups": ["sg-1"]}
    },
    "events": [{"createdAt": NOW, "message": f"event {index}"} for index in range(15)],
    "serviceRegistries": [{"registryArn": "arn:r"}],
}


@spec("FR-023")
def test_an_ecs_service_returns_its_reviewed_fields_and_never_reads_its_task_definition() -> None:
    gateway = FakeGateway(responses={"ecs:DescribeServices": {"services": [SERVICE]}})

    failed, result = _describe(gateway, "ecs-service", "example/example-api")

    assert not failed
    configuration = result["data"]["configuration"]
    assert configuration["task_definition"].endswith("task-definition/example-api:42")
    assert configuration["counts"] == {"desired": 2, "running": 1, "pending": 1}
    assert len(configuration["events"]) == 10
    assert "serviceRegistries" not in json.dumps(configuration)
    assert [call[2] for call in gateway.calls] == ["ecs:DescribeServices"]
    assert gateway.calls[0][3] == {"cluster": "example", "services": ["example-api"]}


@spec("FR-023")
def test_an_ecs_service_without_its_cluster_is_found_across_clusters() -> None:
    gateway = FakeGateway(
        responses={
            "ecs:ListClusters": {"clusterArns": ["arn:c/one", "arn:c/example"]},
            "ecs:DescribeServices": [
                {"services": [], "failures": [{"reason": "MISSING"}]},
                {"services": [SERVICE]},
            ],
        }
    )

    failed, result = _describe(gateway, "ecs-service", "example-api")

    assert not failed
    assert result["data"]["configuration"]["name"] == "example-api"


@spec("FR-023")
@pytest.mark.parametrize(
    ("kind", "action", "response", "check"),
    [
        (
            "rds-instance",
            "rds:DescribeDBInstances",
            {
                "DBInstances": [
                    {
                        "DBInstanceIdentifier": "example-db",
                        "Engine": "postgres",
                        "EngineVersion": "16.4",
                        "DBInstanceClass": "db.t4g.medium",
                        "DBInstanceStatus": "available",
                        "MultiAZ": True,
                        "Endpoint": {"Address": "example-db.example.com", "Port": 5432},
                        "MasterUsername": "admin",
                        "PendingModifiedValues": {
                            "MasterUserPassword": "****",
                            "DBInstanceClass": "x",
                        },
                    }
                ]
            },
            lambda c: c["engine"] == "postgres" and c["pending"] == {"DBInstanceClass": "x"},
        ),
        (
            "rds-cluster",
            "rds:DescribeDBClusters",
            {
                "DBClusters": [
                    {
                        "DBClusterIdentifier": "example-cluster",
                        "Engine": "aurora-postgresql",
                        "Status": "available",
                    }
                ]
            },
            lambda c: c["status"] == "available",
        ),
        (
            "ec2-instance",
            "ec2:DescribeInstances",
            {
                "Reservations": [
                    {
                        "Instances": [
                            {
                                "InstanceId": "i-0123456789abcdef0",
                                "InstanceType": "t3.small",
                                "State": {"Name": "running"},
                            }
                        ]
                    }
                ]
            },
            lambda c: c["state"] == "running",
        ),
        (
            "autoscaling-group",
            "autoscaling:DescribeAutoScalingGroups",
            {
                "AutoScalingGroups": [
                    {
                        "AutoScalingGroupName": "example-asg",
                        "MinSize": 1,
                        "MaxSize": 4,
                        "DesiredCapacity": 2,
                        "Instances": [],
                    }
                ]
            },
            lambda c: (c["min"], c["max"], c["desired"]) == (1, 4, 2),
        ),
        (
            "alarm",
            "cloudwatch:DescribeAlarms",
            {"MetricAlarms": [{"AlarmName": "example-cpu", "StateValue": "OK"}]},
            lambda c: c["state"] == "OK",
        ),
    ],
)
def test_each_type_returns_its_reviewed_fields(
    kind: str, action: str, response: dict[str, Any], check: Any
) -> None:
    gateway = FakeGateway(responses={action: response})

    failed, result = _describe(gateway, kind, "example")

    assert not failed, result
    assert check(result["data"]["configuration"])
    assert "MasterUserPassword" not in json.dumps(result)
    assert "MasterUsername" not in json.dumps(result)


@spec("FR-023")
def test_a_load_balancer_and_a_target_group_include_listeners_and_health() -> None:
    gateway = FakeGateway(
        responses={
            "elasticloadbalancing:DescribeLoadBalancers": {
                "LoadBalancers": [
                    {
                        "LoadBalancerArn": "arn:lb",
                        "LoadBalancerName": "example-alb",
                        "Scheme": "internet-facing",
                        "State": {"Code": "active"},
                        "Type": "application",
                    }
                ]
            },
            "elasticloadbalancing:DescribeListeners": {
                "Listeners": [
                    {
                        "Port": 443,
                        "Protocol": "HTTPS",
                        "DefaultActions": [{"Type": "forward", "TargetGroupArn": "arn:tg"}],
                    }
                ]
            },
            "elasticloadbalancing:DescribeTargetGroups": {
                "TargetGroups": [
                    {
                        "TargetGroupArn": "arn:tg",
                        "TargetGroupName": "example-tg",
                        "Protocol": "HTTP",
                        "Port": 8080,
                        "HealthCheckPath": "/health",
                    }
                ]
            },
            "elasticloadbalancing:DescribeTargetHealth": {
                "TargetHealthDescriptions": [
                    {
                        "Target": {"Id": "192.0.2.21", "Port": 8080},
                        "TargetHealth": {"State": "unhealthy", "Reason": "Target.Timeout"},
                    }
                ]
            },
        }
    )

    failed, result = _describe(gateway, "load-balancer", "example-alb")
    assert not failed
    assert result["data"]["configuration"]["listeners"][0]["port"] == 443

    failed, result = _describe(gateway, "target-group", "example-tg")
    assert not failed
    assert result["data"]["configuration"]["targets"] == [
        {
            "id": "192.0.2.21",
            "port": 8080,
            "state": "unhealthy",
            "reason": "Target.Timeout",
            "description": None,
        }
    ]


STACK_RESOURCE = {
    "StackName": "example-worker-stack",
    "LogicalResourceId": "Worker",
    "PhysicalResourceId": "example-worker",
    "ResourceType": "AWS::Lambda::Function",
    "ResourceStatus": "UPDATE_COMPLETE",
    "Timestamp": NOW,
}


@spec("FR-023")
def test_a_lambda_function_is_described_through_its_stack_without_parameters() -> None:
    gateway = FakeGateway(
        responses={
            "cloudformation:DescribeStackResources": {"StackResources": [STACK_RESOURCE]},
            "cloudformation:DescribeStacks": {
                "Stacks": [
                    {
                        "StackName": "example-worker-stack",
                        "StackStatus": "UPDATE_COMPLETE",
                        "LastUpdatedTime": NOW,
                        "Parameters": [{"ParameterKey": "DbPassword", "ParameterValue": "plain"}],
                        "Outputs": [
                            {"OutputKey": "QueueUrl", "OutputValue": "https://sqs.example.com/q"},
                            {"OutputKey": "DbPassword", "OutputValue": "plain-output"},
                        ],
                    }
                ]
            },
            "cloudformation:ListStackResources": {
                "StackResourceSummaries": [
                    STACK_RESOURCE,
                    {
                        **STACK_RESOURCE,
                        "LogicalResourceId": "Queue",
                        "PhysicalResourceId": "q",
                        "ResourceType": "AWS::SQS::Queue",
                    },
                ]
            },
        }
    )

    failed, result = _describe(gateway, "lambda-function", "example-worker")

    assert not failed
    stack = result["data"]["stack"]
    assert stack["name"] == "example-worker-stack"
    assert {"OutputKey": "DbPassword", "OutputValue": "[secret]"} in stack["outputs"]
    assert [row["logical_id"] for row in stack["resources"]] == ["Worker"]
    text = json.dumps(result)
    assert "plain" not in text.replace("plain-output", "")
    assert "plain-output" not in text
    assert "Parameters" not in text
    assert not any(call[2].startswith("lambda:") for call in gateway.calls)


@spec("FR-023")
def test_a_function_no_stack_owns_is_not_found_with_the_reason() -> None:
    gateway = FakeGateway(
        responses={
            "cloudformation:DescribeStackResources": ToolError(
                ErrorReason.INVALID_INPUT, "Stack for example-worker does not exist"
            )
        }
    )

    failed, result = _describe(gateway, "lambda-function", "example-worker")

    assert failed
    assert result["error"]["reason"] == "not-found"
    assert "described only through its CloudFormation stack" in result["error"]["message"]


@spec("FR-023")
def test_other_types_are_not_supported_and_none_found_is_not_found() -> None:
    failed, result = _describe(FakeGateway(), "s3-bucket", "example")
    assert failed
    assert result["error"]["reason"] == "not-supported"
    assert "lambda-function" in result["error"]["message"]

    gateway = FakeGateway(responses={"rds:DescribeDBInstances": {"DBInstances": []}})
    failed, result = _describe(gateway, "rds-instance", "missing")
    assert failed
    assert result["error"]["reason"] == "not-found"


@spec("FR-023")
def test_several_instances_with_one_name_are_listed() -> None:
    instances = [
        {"InstanceId": f"i-{index:017x}", "InstanceType": "t3.small", "State": {"Name": "running"}}
        for index in range(3)
    ]
    gateway = FakeGateway(
        responses={"ec2:DescribeInstances": {"Reservations": [{"Instances": instances}]}}
    )

    failed, result = _describe(gateway, "ec2-instance", "example-api")

    assert not failed
    assert len(result["data"]["matches"]) == 3
    assert gateway.calls[0][3] == {"Filters": [{"Name": "tag:Name", "Values": ["example-api"]}]}


@spec("FR-023")
def test_one_service_name_in_several_clusters_lists_every_match() -> None:
    other = {**SERVICE, "clusterArn": f"arn:aws:ecs:us-east-1:{ACCOUNT}:cluster/other"}
    gateway = FakeGateway(
        responses={
            "ecs:ListClusters": {"clusterArns": ["arn:c/example", "arn:c/other", "arn:c/empty"]},
            "ecs:DescribeServices": [
                {"services": [SERVICE]},
                {"services": [other]},
                {"services": []},
            ],
        }
    )

    failed, result = _describe(gateway, "ecs-service", "example-api")

    assert not failed
    assert [match["cluster"] for match in result["data"]["matches"]] == [
        SERVICE["clusterArn"],
        other["clusterArn"],
    ]
