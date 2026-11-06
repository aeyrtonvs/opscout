# SPDX-License-Identifier: Apache-2.0
"""The tools, their declared AWS actions and their handlers (specs 011 and 012).

A tool's ``actions`` are every AWS action its handler may call. The surface check proves
each one is a read the reference identity allows (FR-006), and the gateway refuses any
other before it is sent (FR-007).
"""

from collections.abc import Mapping
from typing import Final

from opscout.core.tools import Registry, ToolSpec
from opscout.services.tools import alarms, alerts, changes, logs, resources, triage
from opscout.services.tools.runtime import Handler

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
        ToolSpec(
            "begin_triage",
            "Open an alert triage run: parse and resolve the alert, and return the run id, "
            "the windows, the settings and the ticket format. Writes only a local record.",
        ),
        ToolSpec(
            "check_verdict",
            "Check a triage verdict: validate it and check every citation against the tool "
            "results of the same run. One retry, then the run ends as inconclusive.",
            evidence=False,
        ),
        ToolSpec(
            "record_agreement",
            "Record whether the user agrees with a run's verdict, in its local record.",
            evidence=False,
        ),
        ToolSpec(
            "show_evidence",
            "Return earlier tool results of this machine's runs by evidence id, as the model "
            "saw them.",
            evidence=False,
        ),
        ToolSpec(
            "search_iac",
            "Search the configured infrastructure-code clones for a literal; returns file, "
            "line and text. Reads nothing outside the clones, nor state, key or .env files.",
        ),
        ToolSpec(
            "read_iac",
            "Read up to 200 lines of one file in a configured infrastructure-code clone, "
            "with their line numbers.",
        ),
    )
)


HANDLERS: dict[str, Handler] = {
    "list_environments": alerts.list_environments,
    "parse_alert": alerts.parse_alert,
    "resolve_environment": alerts.resolve_environment,
    "read_alarm": alarms.read_alarm,
    "read_metric": alarms.read_metric,
    "query_logs": logs.query_logs,
    "recent_changes": changes.recent_changes,
    "find_resources": resources.find_resources,
    "describe_resource": resources.describe_resource,
    "begin_triage": triage.begin_triage,
    "check_verdict": triage.check_verdict,
    "record_agreement": triage.record_agreement,
    "show_evidence": triage.show_evidence,
    "search_iac": triage.search_iac,
    "read_iac": triage.read_iac,
}

SPECS: Final[Mapping[str, ToolSpec]] = {tool.name: tool for tool in REGISTRY}
