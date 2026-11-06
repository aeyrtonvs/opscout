# SPDX-License-Identifier: Apache-2.0
"""recent_changes: who changed what, when, in an environment (spec 011, FR-022; R12).

A change carries who, what, when, on which resource and any error. It never carries a
CloudTrail event's request or response, nor a stack event's resource properties: those can
hold the values a change set, such as a task definition's environment.
"""

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Final

from opscout.core.config import AwsEnvironment
from opscout.core.tools import Capped, Window
from opscout.services.tools.runtime import Call, DeadlineReachedError, Outcome

_SOURCE_TYPE: Final = {"rds-instance": "db-instance", "rds-cluster": "db-cluster"}
TRAIL_PAGE: Final = 50


def _change(
    time: datetime | None,
    source: str,
    action: str | None,
    target: str | None,
    *,
    actor: str | None = None,
    status: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "time": time,
        "source": source,
        "actor": actor,
        "action": action,
        "target": target,
        "status": status,
        "error": error,
    }


def _trail(
    call: Call, env: AwsEnvironment, region: str, window: Window, items: int
) -> tuple[list[dict[str, Any]], bool]:
    resource = call.argument("resource")
    attribute = (
        {"AttributeKey": "ResourceName", "AttributeValue": _short(resource)}
        if resource
        else {"AttributeKey": "ReadOnly", "AttributeValue": "false"}
    )
    response = call.aws(
        env,
        region,
        "cloudtrail:LookupEvents",
        LookupAttributes=[attribute],
        StartTime=window.start,
        EndTime=window.end,
        MaxResults=min(TRAIL_PAGE, items),
    )
    changes = []
    for event in response.get("Events", []):
        if str(event.get("ReadOnly", "false")).lower() == "true":
            continue
        try:
            # Only these keys are read; requestParameters and responseElements never are.
            detail = json.loads(event.get("CloudTrailEvent") or "{}")
        except ValueError:
            detail = {}
        identity = detail.get("userIdentity") or {}
        code, message = detail.get("errorCode"), detail.get("errorMessage")
        changes.append(
            _change(
                event.get("EventTime"),
                "cloudtrail",
                event.get("EventName"),
                ", ".join(r.get("ResourceName", "") for r in event.get("Resources", [])) or None,
                actor=identity.get("arn") or event.get("Username"),
                error=f"{code}: {message}" if code else None,
            )
        )
    return changes, bool(response.get("NextToken"))


def _stacks(
    call: Call, env: AwsEnvironment, region: str, window: Window, items: int
) -> tuple[list[dict[str, Any]], bool]:
    response = call.aws(env, region, "cloudformation:DescribeStacks")
    updated = [
        stack
        for stack in response.get("Stacks", [])
        if (stack.get("LastUpdatedTime") or stack.get("CreationTime")) is not None
        and (stack.get("LastUpdatedTime") or stack["CreationTime"]) >= window.start
    ]
    updated.sort(key=lambda s: s.get("LastUpdatedTime") or s["CreationTime"], reverse=True)
    limit = call.caps.default("stacks")
    more = len(updated) > limit or bool(response.get("NextToken"))
    resource = call.argument("resource")
    changes: list[dict[str, Any]] = []
    for stack in updated[:limit]:
        events = call.aws(
            env, region, "cloudformation:DescribeStackEvents", StackName=stack["StackName"]
        )
        for event in events.get("StackEvents", []):
            if (
                event.get("Timestamp") is None
                or not window.start <= event["Timestamp"] <= window.end
            ):
                continue
            physical = event.get("PhysicalResourceId") or ""
            if (
                resource
                and _short(resource) not in physical
                and event.get("LogicalResourceId") != resource
            ):
                continue
            status = event.get("ResourceStatus")
            # ResourceProperties is never read: it is the resource's full properties.
            changes.append(
                _change(
                    event["Timestamp"],
                    "cloudformation",
                    status,
                    f"{event.get('StackName')}/{event.get('LogicalResourceId')}",
                    status=status,
                    error=event.get("ResourceStatusReason") if "FAILED" in str(status) else None,
                )
            )
    return changes, more


_NO_TIME: Final = datetime.min.replace(tzinfo=UTC)


def _newest(change: dict[str, Any]) -> datetime:
    """Sort key: a change without a time sorts last (review L1)."""
    time: datetime | None = change["time"]
    return time if time is not None else _NO_TIME


def _short(resource: str) -> str:
    """The last part of a name or ARN: ``cluster/service`` or an ARN gives ``service``."""
    return resource.rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1]


def _ecs(
    call: Call, env: AwsEnvironment, region: str, window: Window, items: int
) -> tuple[list[dict[str, Any]], bool]:
    resource = str(call.argument("resource"))
    parts = (
        resource.split(":", 5)[-1].split("/")
        if resource.startswith("arn:")
        else resource.split("/")
    )
    parts = [part for part in parts if part and part != "service"]
    params: dict[str, Any] = {
        "service": parts[-1],
        "createdAt": {"after": window.start, "before": window.end},
        "maxResults": min(items, 100),
    }
    if len(parts) > 1:
        params["cluster"] = parts[-2]
    response = call.aws(env, region, "ecs:ListServiceDeployments", **params)
    changes = [
        _change(
            deployment.get("startedAt") or deployment.get("createdAt"),
            "ecs",
            "deployment",
            parts[-1],
            status=deployment.get("status"),
            error=deployment.get("statusReason"),
        )
        for deployment in response.get("serviceDeployments", [])
    ]
    return changes, bool(response.get("nextToken"))


def _autoscaling(
    call: Call, env: AwsEnvironment, region: str, window: Window, items: int
) -> tuple[list[dict[str, Any]], bool]:
    name = _short(str(call.argument("resource")))
    response = call.aws(
        env,
        region,
        "autoscaling:DescribeScalingActivities",
        AutoScalingGroupName=name,
        MaxRecords=min(items, 100),
    )
    changes = [
        _change(
            activity.get("StartTime"),
            "autoscaling",
            activity.get("Description"),
            name,
            status=activity.get("StatusCode"),
            error=activity.get("StatusMessage"),
        )
        for activity in response.get("Activities", [])
        if activity.get("StartTime") is not None and activity["StartTime"] >= window.start
    ]
    return changes, bool(response.get("NextToken"))


def _rds(
    call: Call, env: AwsEnvironment, region: str, window: Window, items: int
) -> tuple[list[dict[str, Any]], bool]:
    name = _short(str(call.argument("resource")))
    response = call.aws(
        env,
        region,
        "rds:DescribeEvents",
        SourceIdentifier=name,
        SourceType=_SOURCE_TYPE[str(call.argument("resource_type"))],
        StartTime=window.start,
        EndTime=window.end,
        MaxRecords=max(20, min(items, 100)),
    )
    changes = [
        _change(event.get("Date"), "rds", event.get("Message"), name)
        for event in response.get("Events", [])
    ]
    return changes, bool(response.get("Marker"))


Source = Callable[[Call, AwsEnvironment, str, Window, int], tuple[list[dict[str, Any]], bool]]
_BY_TYPE: Final[Mapping[str, tuple[str, Source]]] = {
    "ecs-service": ("ecs", _ecs),
    "autoscaling-group": ("autoscaling", _autoscaling),
    "rds-instance": ("rds", _rds),
    "rds-cluster": ("rds", _rds),
}


def recent_changes(call: Call) -> Outcome:
    """Merge the sources newest first, each capped; stop at the deadline (FR-022, FR-011)."""
    environment = call.environment()
    region = call.region(environment)
    window, window_cap = call.window("change_window_hours")
    capped: list[Capped] = [window_cap] if window_cap else []
    items = call.caps.default("change_items")
    sources: list[tuple[str, Source]] = [("cloudtrail", _trail), ("cloudformation", _stacks)]
    resource_type = call.argument("resource_type")
    if call.argument("resource") and resource_type in _BY_TYPE:
        sources.append(_BY_TYPE[resource_type])
    changes: list[dict[str, Any]] = []
    more: dict[str, bool] = {}
    partial = False
    for name, source in sources:
        try:
            found, more[name] = source(call, environment, region, window, items)
        except DeadlineReachedError:
            partial = True
            break
        found.sort(key=_newest, reverse=True)
        if len(found) > items:
            capped.append(Capped(f"change_items:{name}", items, len(found) - items))
            more[name] = True
        changes += found[:items]
    changes.sort(key=_newest, reverse=True)
    return Outcome(
        data={"changes": changes, "more": more},
        environment=environment,
        window=window,
        capped=capped,
        partial=partial,
    )
