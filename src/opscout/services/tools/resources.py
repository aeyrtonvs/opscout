# SPDX-License-Identifier: Apache-2.0
"""find_resources and describe_resource (spec 011, FR-023, FR-024; contracts/tools.md).

Each type has one reviewed read, and only its reviewed fields are returned. Nothing reads an
ECS task definition's contents, an instance's user data or a Lambda function's own
configuration; a function is described through the CloudFormation stack that owns it.
"""

import re
from collections.abc import Callable, Mapping
from typing import Any, Final

from opscout.core.aws import RESOURCE_TYPES
from opscout.core.config import AwsEnvironment
from opscout.core.tools import Capped, ErrorReason, ToolError
from opscout.services.tools.alarms import alarm_summary
from opscout.services.tools.runtime import Call, DeadlineReachedError, Outcome

TAG_TYPES: Final[Mapping[str, str]] = {
    "ecs-service": "ecs:service",
    "rds-instance": "rds:db",
    "rds-cluster": "rds:cluster",
    "ec2-instance": "ec2:instance",
    "load-balancer": "elasticloadbalancing:loadbalancer",
    "target-group": "elasticloadbalancing:targetgroup",
    "autoscaling-group": "autoscaling:autoScalingGroup",
    "alarm": "cloudwatch:alarm",
    "lambda-function": "lambda:function",
}
_ARN_TYPES: Final = (
    ("ecs", "service/", "ecs-service"),
    ("rds", "db:", "rds-instance"),
    ("rds", "cluster:", "rds-cluster"),
    ("ec2", "instance/", "ec2-instance"),
    ("elasticloadbalancing", "loadbalancer/", "load-balancer"),
    ("elasticloadbalancing", "targetgroup/", "target-group"),
    ("autoscaling", "autoScalingGroup:", "autoscaling-group"),
    ("cloudwatch", "alarm:", "alarm"),
    ("lambda", "function:", "lambda-function"),
)
TAG_PAGES: Final = 5
CLUSTER_PAGES: Final = 5
EVENTS: Final = 10
_INSTANCE_ID = re.compile(r"^i-[0-9a-f]{8,17}$")
NO_STACK: Final = "described only through its CloudFormation stack"


def _type_of(arn: str) -> str:
    parts = arn.split(":", 5)
    if len(parts) < 6:
        return "other"
    service, resource = parts[2], parts[5]
    for prefix, start, kind in _ARN_TYPES:
        if service == prefix and resource.startswith(start):
            return kind
    return f"other:{service}"


def _name_of(arn: str, tags: list[dict[str, str]]) -> str:
    for tag in tags:
        if tag.get("Key") == "Name":
            return tag.get("Value", "")
    return re.split(r"[/:]", arn)[-1]


def find_resources(call: Call) -> Outcome:
    """Resources by tag, name or type, through the tagging API (FR-024)."""
    environment = call.environment()
    region = call.region(environment)
    name, key, value, kind = (
        call.argument("name"),
        call.argument("tag_key"),
        call.argument("tag_value"),
        call.argument("type"),
    )
    if not name and not key:
        raise ToolError(ErrorReason.INVALID_INPUT, "give a name, a tag_key or both")
    if kind is not None and kind not in TAG_TYPES:
        raise ToolError(ErrorReason.NOT_SUPPORTED, f"types are {', '.join(RESOURCE_TYPES)}")
    params: dict[str, Any] = {"ResourcesPerPage": 100}
    if key:
        params["TagFilters"] = [{"Key": key, **({"Values": [value]} if value else {})}]
    if kind:
        params["ResourceTypeFilters"] = [TAG_TYPES[kind]]
    limit = call.caps.default("resources")
    found: list[dict[str, Any]] = []
    more = False
    for _ in range(TAG_PAGES):
        response = call.aws(environment, region, "tag:GetResources", **params)
        for mapping in response.get("ResourceTagMappingList", []):
            arn = mapping.get("ResourceARN", "")
            tags = list(mapping.get("Tags", []))
            resource_name = _name_of(arn, tags)
            if name and name.casefold() not in f"{resource_name} {arn}".casefold():
                continue
            found.append({"type": _type_of(arn), "name": resource_name, "arn": arn, "tags": tags})
        token = response.get("PaginationToken")
        if not token or len(found) > limit:
            more = bool(token)
            break
        params["PaginationToken"] = token
    else:
        more = True  # the page limit was reached with pages left
    capped = []
    if len(found) > limit:
        capped.append(Capped("resources", limit, len(found) - limit))
        found, more = found[:limit], True
    return Outcome(data={"resources": found, "more": more}, environment=environment, capped=capped)


def _pick(source: Mapping[str, Any], fields: Mapping[str, str]) -> dict[str, Any]:
    return {target: source.get(key) for target, key in fields.items()}


def _ecs(call: Call, env: AwsEnvironment, region: str, name: str) -> dict[str, Any]:
    parts = name.split(":", 5)[-1].split("/") if name.startswith("arn:") else name.split("/")
    parts = [part for part in parts if part and part != "service"]
    service = parts[-1]
    clusters = [parts[-2]] if len(parts) > 1 else []
    if not clusters:
        token: str | None = None
        for _ in range(CLUSTER_PAGES):
            page = {"nextToken": token} if token else {}
            listed = call.aws(env, region, "ecs:ListClusters", maxResults=100, **page)
            clusters += [arn.rsplit("/", 1)[-1] for arn in listed.get("clusterArns", [])]
            token = listed.get("nextToken")
            if not token:
                break
    matches: list[dict[str, Any]] = []
    for cluster in clusters:
        try:
            response = call.aws(
                env, region, "ecs:DescribeServices", cluster=cluster, services=[service]
            )
        except DeadlineReachedError:
            if not matches:
                raise
            call.partial = True  # what was found so far is returned (review M5)
            break
        for found in response.get("services", []):
            network = (found.get("networkConfiguration") or {}).get("awsvpcConfiguration", {})
            matches.append(
                {
                    "name": found.get("serviceName"),
                    "arn": found.get("serviceArn"),
                    "cluster": found.get("clusterArn"),
                    "status": found.get("status"),
                    "counts": {
                        "desired": found.get("desiredCount"),
                        "running": found.get("runningCount"),
                        "pending": found.get("pendingCount"),
                    },
                    "launch_type": found.get("launchType"),
                    "capacity_providers": [
                        entry.get("capacityProvider")
                        for entry in found.get("capacityProviderStrategy", [])
                    ],
                    # The ARN only: the task definition's contents hold its environment.
                    "task_definition": found.get("taskDefinition"),
                    "deployments": [
                        _pick(
                            deployment,
                            {
                                "status": "status",
                                "rollout": "rolloutState",
                                "rollout_reason": "rolloutStateReason",
                                "desired": "desiredCount",
                                "running": "runningCount",
                                "created": "createdAt",
                                "updated": "updatedAt",
                                "task_definition": "taskDefinition",
                            },
                        )
                        for deployment in found.get("deployments", [])
                    ],
                    "load_balancers": found.get("loadBalancers", []),
                    "network": {
                        "subnets": network.get("subnets", []),
                        "security_groups": network.get("securityGroups", []),
                        "public_ip": network.get("assignPublicIp"),
                    },
                    "events": [
                        {"time": event.get("createdAt"), "message": event.get("message")}
                        for event in found.get("events", [])[:EVENTS]
                    ],
                }
            )
    if len(matches) > 1:
        return {"matches": matches}
    if matches:
        return matches[0]
    raise ToolError(ErrorReason.NOT_FOUND, f"no ECS service {service} in {env.name}")


def _pending(values: Mapping[str, Any] | None) -> dict[str, Any]:
    return {key: value for key, value in (values or {}).items() if "Password" not in key}


def _rds_instance(call: Call, env: AwsEnvironment, region: str, name: str) -> dict[str, Any]:
    response = call.aws(env, region, "rds:DescribeDBInstances", DBInstanceIdentifier=name)
    instances = response.get("DBInstances", [])
    if not instances:
        raise ToolError(ErrorReason.NOT_FOUND, f"no RDS instance {name} in {env.name}")
    found = instances[0]
    endpoint = found.get("Endpoint") or {}
    return {
        **_pick(
            found,
            {
                "name": "DBInstanceIdentifier",
                "engine": "Engine",
                "version": "EngineVersion",
                "class": "DBInstanceClass",
                "status": "DBInstanceStatus",
                "multi_az": "MultiAZ",
                "storage": "AllocatedStorage",
                "storage_type": "StorageType",
                "backup_window": "PreferredBackupWindow",
                "backup_retention": "BackupRetentionPeriod",
                "maintenance_window": "PreferredMaintenanceWindow",
                "cluster": "DBClusterIdentifier",
            },
        ),
        "endpoint": {"address": endpoint.get("Address"), "port": endpoint.get("Port")},
        "parameter_groups": [
            group.get("DBParameterGroupName") for group in found.get("DBParameterGroups", [])
        ],
        "pending": _pending(found.get("PendingModifiedValues")),
    }


def _rds_cluster(call: Call, env: AwsEnvironment, region: str, name: str) -> dict[str, Any]:
    response = call.aws(env, region, "rds:DescribeDBClusters", DBClusterIdentifier=name)
    clusters = response.get("DBClusters", [])
    if not clusters:
        raise ToolError(ErrorReason.NOT_FOUND, f"no RDS cluster {name} in {env.name}")
    found = clusters[0]
    return {
        **_pick(
            found,
            {
                "name": "DBClusterIdentifier",
                "engine": "Engine",
                "version": "EngineVersion",
                "status": "Status",
                "multi_az": "MultiAZ",
                "endpoint": "Endpoint",
                "reader_endpoint": "ReaderEndpoint",
                "port": "Port",
                "parameter_group": "DBClusterParameterGroup",
                "backup_window": "PreferredBackupWindow",
                "backup_retention": "BackupRetentionPeriod",
                "maintenance_window": "PreferredMaintenanceWindow",
            },
        ),
        "members": [
            {
                "instance": member.get("DBInstanceIdentifier"),
                "writer": member.get("IsClusterWriter"),
            }
            for member in found.get("DBClusterMembers", [])
        ],
        "pending": _pending(found.get("PendingModifiedValues")),
    }


def _instance(found: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": found.get("InstanceId"),
        "type": found.get("InstanceType"),
        "state": (found.get("State") or {}).get("Name"),
        "image": found.get("ImageId"),
        "subnet": found.get("SubnetId"),
        "vpc": found.get("VpcId"),
        "security_groups": [group.get("GroupId") for group in found.get("SecurityGroups", [])],
        "instance_profile": (found.get("IamInstanceProfile") or {}).get("Arn"),
        "launched": found.get("LaunchTime"),
        "private_ip": found.get("PrivateIpAddress"),
        "public_ip": found.get("PublicIpAddress"),
        "tags": found.get("Tags", []),
    }


def _ec2(call: Call, env: AwsEnvironment, region: str, name: str) -> dict[str, Any]:
    params: dict[str, Any] = (
        {"InstanceIds": [name]}
        if _INSTANCE_ID.match(name)
        else {"Filters": [{"Name": "tag:Name", "Values": [name]}]}
    )
    response = call.aws(env, region, "ec2:DescribeInstances", **params)
    instances = [
        _instance(instance)
        for reservation in response.get("Reservations", [])
        for instance in reservation.get("Instances", [])
    ]
    if not instances:
        raise ToolError(ErrorReason.NOT_FOUND, f"no EC2 instance {name} in {env.name}")
    if len(instances) > 1:
        return {"matches": instances}
    return instances[0]


def _load_balancer(call: Call, env: AwsEnvironment, region: str, name: str) -> dict[str, Any]:
    key = {"LoadBalancerArns": [name]} if name.startswith("arn:") else {"Names": [name]}
    response = call.aws(env, region, "elasticloadbalancing:DescribeLoadBalancers", **key)
    balancers = response.get("LoadBalancers", [])
    if not balancers:
        raise ToolError(ErrorReason.NOT_FOUND, f"no load balancer {name} in {env.name}")
    found = balancers[0]
    listeners = call.aws(
        env,
        region,
        "elasticloadbalancing:DescribeListeners",
        LoadBalancerArn=found["LoadBalancerArn"],
    )
    return {
        "name": found.get("LoadBalancerName"),
        "arn": found.get("LoadBalancerArn"),
        "type": found.get("Type"),
        "scheme": found.get("Scheme"),
        "state": (found.get("State") or {}).get("Code"),
        "dns": found.get("DNSName"),
        "vpc": found.get("VpcId"),
        "listeners": [
            {
                "port": listener.get("Port"),
                "protocol": listener.get("Protocol"),
                "actions": [
                    {"type": action.get("Type"), "target_group": action.get("TargetGroupArn")}
                    for action in listener.get("DefaultActions", [])
                ],
            }
            for listener in listeners.get("Listeners", [])
        ],
    }


def _target_group(call: Call, env: AwsEnvironment, region: str, name: str) -> dict[str, Any]:
    key = {"TargetGroupArns": [name]} if name.startswith("arn:") else {"Names": [name]}
    response = call.aws(env, region, "elasticloadbalancing:DescribeTargetGroups", **key)
    groups = response.get("TargetGroups", [])
    if not groups:
        raise ToolError(ErrorReason.NOT_FOUND, f"no target group {name} in {env.name}")
    found = groups[0]
    health = call.aws(
        env,
        region,
        "elasticloadbalancing:DescribeTargetHealth",
        TargetGroupArn=found["TargetGroupArn"],
    )
    return {
        **_pick(
            found,
            {
                "name": "TargetGroupName",
                "arn": "TargetGroupArn",
                "protocol": "Protocol",
                "port": "Port",
                "target_type": "TargetType",
                "health_check_path": "HealthCheckPath",
                "health_check_protocol": "HealthCheckProtocol",
                "healthy_threshold": "HealthyThresholdCount",
                "unhealthy_threshold": "UnhealthyThresholdCount",
                "load_balancers": "LoadBalancerArns",
            },
        ),
        "targets": [
            {
                "id": (entry.get("Target") or {}).get("Id"),
                "port": (entry.get("Target") or {}).get("Port"),
                "state": (entry.get("TargetHealth") or {}).get("State"),
                "reason": (entry.get("TargetHealth") or {}).get("Reason"),
                "description": (entry.get("TargetHealth") or {}).get("Description"),
            }
            for entry in health.get("TargetHealthDescriptions", [])
        ],
    }


def _autoscaling(call: Call, env: AwsEnvironment, region: str, name: str) -> dict[str, Any]:
    response = call.aws(
        env, region, "autoscaling:DescribeAutoScalingGroups", AutoScalingGroupNames=[name]
    )
    groups = response.get("AutoScalingGroups", [])
    if not groups:
        raise ToolError(ErrorReason.NOT_FOUND, f"no Auto Scaling group {name} in {env.name}")
    found = groups[0]
    template = found.get("LaunchTemplate") or (
        (found.get("MixedInstancesPolicy") or {})
        .get("LaunchTemplate", {})
        .get("LaunchTemplateSpecification", {})
    )
    return {
        "name": found.get("AutoScalingGroupName"),
        "min": found.get("MinSize"),
        "max": found.get("MaxSize"),
        "desired": found.get("DesiredCapacity"),
        "health_check": found.get("HealthCheckType"),
        "launch_template": {
            "id": template.get("LaunchTemplateId"),
            "version": template.get("Version"),
        },
        "target_groups": found.get("TargetGroupARNs", []),
        "instances": [
            {
                "id": instance.get("InstanceId"),
                "lifecycle": instance.get("LifecycleState"),
                "health": instance.get("HealthStatus"),
            }
            for instance in found.get("Instances", [])
        ],
    }


def _alarm(call: Call, env: AwsEnvironment, region: str, name: str) -> dict[str, Any]:
    response = call.aws(env, region, "cloudwatch:DescribeAlarms", AlarmNames=[name])
    alarms = [*response.get("MetricAlarms", []), *response.get("CompositeAlarms", [])]
    if not alarms:
        raise ToolError(ErrorReason.NOT_FOUND, f"no alarm {name} in {env.name}")
    return alarm_summary(alarms[0])


def _lambda(call: Call, env: AwsEnvironment, region: str, name: str) -> dict[str, Any]:
    function = name.rsplit(":", 1)[-1] if name.startswith("arn:") else name
    try:
        owned = call.aws(
            env, region, "cloudformation:DescribeStackResources", PhysicalResourceId=function
        )
    except ToolError as error:
        if error.reason in (ErrorReason.INVALID_INPUT, ErrorReason.NOT_FOUND):
            raise ToolError(ErrorReason.NOT_FOUND, f"{function}: {NO_STACK}") from None
        raise
    rows = owned.get("StackResources", [])
    if not rows:
        raise ToolError(ErrorReason.NOT_FOUND, f"{function}: {NO_STACK}")
    stack_name = rows[0]["StackName"]
    stacks = call.aws(env, region, "cloudformation:DescribeStacks", StackName=stack_name)
    stack = (stacks.get("Stacks") or [{}])[0]
    listed = call.aws(env, region, "cloudformation:ListStackResources", StackName=stack_name)
    logical = {row.get("LogicalResourceId") for row in rows}
    return {
        "stack": {
            "name": stack_name,
            "status": stack.get("StackStatus"),
            "updated": stack.get("LastUpdatedTime") or stack.get("CreationTime"),
            # Outputs only: a stack's parameters and template can hold plain values.
            "outputs": [
                {"OutputKey": output.get("OutputKey"), "OutputValue": output.get("OutputValue")}
                for output in stack.get("Outputs", [])
            ],
            "resources": [
                {
                    "logical_id": row.get("LogicalResourceId"),
                    "physical_id": row.get("PhysicalResourceId"),
                    "type": row.get("ResourceType"),
                    "status": row.get("ResourceStatus"),
                    "updated": row.get("LastUpdatedTimestamp") or row.get("Timestamp"),
                }
                for row in listed.get("StackResourceSummaries", [])
                if row.get("LogicalResourceId") in logical
                or row.get("PhysicalResourceId") == function
            ],
        }
    }


Describer = Callable[[Call, AwsEnvironment, str, str], dict[str, Any]]
_DESCRIBERS: Final[Mapping[str, Describer]] = {
    "ecs-service": _ecs,
    "rds-instance": _rds_instance,
    "rds-cluster": _rds_cluster,
    "ec2-instance": _ec2,
    "load-balancer": _load_balancer,
    "target-group": _target_group,
    "autoscaling-group": _autoscaling,
    "alarm": _alarm,
    "lambda-function": _lambda,
}


def describe_resource(call: Call) -> Outcome:
    """One resource's reviewed configuration (FR-023)."""
    environment = call.environment()
    region = call.region(environment)
    kind, name = call.argument("type"), call.argument("name")
    if kind not in _DESCRIBERS:
        raise ToolError(ErrorReason.NOT_SUPPORTED, f"the types are {', '.join(RESOURCE_TYPES)}")
    if not isinstance(name, str) or not name:
        raise ToolError(ErrorReason.INVALID_INPUT, "name is required")
    described = _DESCRIBERS[kind](call, environment, region, name)
    capped = []
    limit = call.caps.default("resources")
    if len(described.get("matches", [])) > limit:
        capped.append(Capped("resources", limit, len(described["matches"]) - limit))
        described["matches"] = described["matches"][:limit]
    if "stack" in described or "matches" in described:
        data = {"type": kind, **described}
    else:
        data = {"type": kind, "configuration": described}
    return Outcome(data=data, environment=environment, capped=capped)
