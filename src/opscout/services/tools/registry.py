# SPDX-License-Identifier: Apache-2.0
"""The nine tools, their declared AWS actions and their handlers (spec 011, contracts/tools.md).

A tool's ``actions`` are every AWS action its handler may call. The surface check proves
each one is a read the reference identity allows (FR-006), and the gateway refuses any
other before it is sent (FR-007).
"""

from collections.abc import Mapping
from typing import Final

from opscout.core.tools import ErrorReason, Registry, ToolError, ToolSpec
from opscout.services.tools import alerts
from opscout.services.tools.runtime import Call, Handler, Outcome

REGISTRY: Final = Registry(
    (
        ToolSpec(
            "list_environments",
            "List the configured AWS environments: their names, regions, aliases and whether "
            "each uses opscout's reference read-only identity or the user's own.",
        ),
        ToolSpec(
            "parse_alert",
            "Parse an alert's text against the alert formats in the private configuration and "
            "return its fields, each with the text it came from; never guesses a field.",
        ),
        ToolSpec(
            "resolve_environment",
            "Resolve an alert's account, environment or project to a configured environment, "
            "or say that it is out of scope.",
        ),
        ToolSpec(
            "read_alarm",
            "Read a CloudWatch alarm: its state, threshold and recent state changes, and its "
            "metric's values over a time window.",
            frozenset(
                {
                    "cloudwatch:DescribeAlarms",
                    "cloudwatch:DescribeAlarmHistory",
                    "cloudwatch:GetMetricData",
                }
            ),
            needs_aws=True,
        ),
        ToolSpec(
            "read_metric",
            "Read a CloudWatch metric by namespace, name and dimensions, with a statistic and "
            "a period, over a time window.",
            frozenset({"cloudwatch:GetMetricData", "cloudwatch:ListMetrics"}),
            needs_aws=True,
        ),
        ToolSpec(
            "query_logs",
            "Run a CloudWatch Logs Insights query over named log groups and a time window, "
            "bounded in time and rows; returns its rows, marked partial when stopped.",
            frozenset(
                {
                    "logs:StartQuery",
                    "logs:GetQueryResults",
                    "logs:StopQuery",
                    "logs:DescribeLogGroups",
                }
            ),
            needs_aws=True,
        ),
        ToolSpec(
            "recent_changes",
            "List recent changes in an environment over a time window: API activity that "
            "changed something, stack events and deployments; never their request contents.",
            frozenset(
                {
                    "cloudtrail:LookupEvents",
                    "cloudformation:DescribeStacks",
                    "cloudformation:DescribeStackEvents",
                    "ecs:ListServiceDeployments",
                    "ecs:DescribeServiceDeployments",
                    "autoscaling:DescribeScalingActivities",
                    "rds:DescribeEvents",
                }
            ),
            needs_aws=True,
        ),
        ToolSpec(
            "find_resources",
            "Find resources in an environment by name, tag or type, so an alert's resource "
            "text becomes a resource that can be described.",
            frozenset({"tag:GetResources"}),
            needs_aws=True,
        ),
        ToolSpec(
            "describe_resource",
            "Describe the deployed configuration of one resource, for a fixed list of types, "
            "with only reviewed fields; never a secret's value.",
            frozenset(
                {
                    "ecs:DescribeServices",
                    "ecs:ListServices",
                    "ecs:ListClusters",
                    "rds:DescribeDBInstances",
                    "rds:DescribeDBClusters",
                    "ec2:DescribeInstances",
                    "elasticloadbalancing:DescribeLoadBalancers",
                    "elasticloadbalancing:DescribeTargetGroups",
                    "elasticloadbalancing:DescribeTargetHealth",
                    "elasticloadbalancing:DescribeListeners",
                    "autoscaling:DescribeAutoScalingGroups",
                    "cloudwatch:DescribeAlarms",
                    "cloudformation:DescribeStackResources",
                    "cloudformation:ListStackResources",
                    "cloudformation:DescribeStacks",
                }
            ),
            needs_aws=True,
        ),
    )
)


def _not_built(call: Call) -> Outcome:
    """A placeholder until the tool is built (T034)."""
    call.environment()
    raise ToolError(ErrorReason.NOT_SUPPORTED, f"{call.spec.name} is not built yet")


HANDLERS: dict[str, Handler] = {
    "list_environments": alerts.list_environments,
    "parse_alert": alerts.parse_alert,
    "resolve_environment": alerts.resolve_environment,
    "read_alarm": _not_built,
    "read_metric": _not_built,
    "query_logs": _not_built,
    "recent_changes": _not_built,
    "find_resources": _not_built,
    "describe_resource": _not_built,
}

SPECS: Final[Mapping[str, ToolSpec]] = {tool.name: tool for tool in REGISTRY}
