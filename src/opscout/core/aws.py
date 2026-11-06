# SPDX-License-Identifier: Apache-2.0
"""The AWS side of the tool surface: ports, tables and environment helpers (spec 011).

Pure: the gateway that actually calls AWS is an adapter. Every call names the IAM action
it is, and the tool's declared actions travel with it, so an adapter can refuse an action
the tool did not declare before anything is sent (FR-007).
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final, Protocol

from opscout.core.config import Aws, AwsEnvironment
from opscout.core.tools import ErrorReason, ToolError

SERVICE_PREFIX: Final[Mapping[str, str]] = {
    "autoscaling": "autoscaling",
    "cloudformation": "cloudformation",
    "cloudtrail": "cloudtrail",
    "cloudwatch": "cloudwatch",
    "ec2": "ec2",
    "ecs": "ecs",
    "elbv2": "elasticloadbalancing",
    "logs": "logs",
    "rds": "rds",
    "resourcegroupstaggingapi": "tag",
}
"""Each botocore service the tools use, mapped to its IAM prefix (research R3).

For these services the botocore operation name is the IAM action name.
"""

_CLIENT: Final[Mapping[str, str]] = {prefix: service for service, prefix in SERVICE_PREFIX.items()}

RESOURCE_TYPES: Final = (
    "ecs-service",
    "rds-instance",
    "rds-cluster",
    "ec2-instance",
    "load-balancer",
    "target-group",
    "autoscaling-group",
    "alarm",
    "lambda-function",
)
"""The types ``describe_resource`` reads (spec 011, FR-023)."""


def iam_action(service: str, operation: str) -> str:
    """The IAM action a botocore call is. Raises ``KeyError`` for an unknown service."""
    return f"{SERVICE_PREFIX[service]}:{operation}"


def client_for(prefix: str) -> str:
    """The botocore service for an IAM prefix. Raises ``KeyError`` for one not in the table."""
    return _CLIENT[prefix]


def find_environment(aws: Aws | None, name: str) -> AwsEnvironment:
    """The configured environment named ``name``, or with it as an alias (any case)."""
    if aws is None:
        raise ToolError(ErrorReason.NOT_CONFIGURED, "AWS is not configured")
    wanted = name.casefold()
    for environment in aws.environments:
        if wanted == environment.name.casefold() or wanted in (
            alias.casefold() for alias in environment.aliases
        ):
            return environment
    names = ", ".join(environment.name for environment in aws.environments)
    raise ToolError(ErrorReason.UNKNOWN_ENVIRONMENT, f"the configured environments are {names}")


def region_for(environment: AwsEnvironment, region: str | None) -> str:
    """The region to read: the one asked for, if in scope, or the environment's first."""
    if region is None:
        return environment.regions[0]
    if region not in environment.regions:
        raise ToolError(
            ErrorReason.INVALID_INPUT,
            f"{environment.name} covers the regions {', '.join(environment.regions)}",
        )
    return region


class AwsGateway(Protocol):
    """Calls AWS read actions for the tools (data-model.md, Port)."""

    def call(
        self,
        environment: AwsEnvironment,
        region: str,
        action: str,
        params: Mapping[str, Any],
        allowed: frozenset[str],
        remaining: float,
    ) -> Mapping[str, Any]:
        """Call ``action`` (``prefix:Operation``) and return its response.

        ``remaining`` is how many seconds the tool's deadline leaves; the call may take its
        read timeout beyond it, never more than ``remaining`` plus 10 seconds (research R7).

        Raises ``ToolError``: ``UNDECLARED_ACTION`` when ``action`` is not in ``allowed``,
        before anything is sent; otherwise the reason AWS or the transport gave.
        """
        ...


@dataclass(frozen=True)
class CallEntry:
    """One line of the call log; never the call's arguments or output (research R11)."""

    time: datetime
    tool: str
    environment: str | None
    outcome: str
    duration_ms: int
    redacted: Mapping[str, int] = field(default_factory=dict)


class CallLog(Protocol):
    """Where each tool call leaves its line (Constitution IX)."""

    def append(self, entry: CallEntry) -> None:
        """Record the call; never raises."""
        ...


BACKGROUND_ACTIONS: Final[frozenset[str]] = frozenset(
    {
        "UpdateInstanceInformation",
        "PutInventory",
        "PutComplianceItems",
        "UpdateInstanceAssociationStatus",
        "ListInstanceAssociations",
        "PutConfigurationAggregator",
    }
)
"""CloudTrail writes agents make on their own, dropped from recent changes by default
(spec 012, research R7): in an account with managed instances they fill the change cap."""
