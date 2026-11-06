# SPDX-License-Identifier: Apache-2.0
"""read_alarm and read_metric (spec 011, FR-019, FR-020)."""

import re
from collections.abc import Mapping
from typing import Any, Final

from opscout.core.tools import Capped, ErrorReason, ToolError, Window
from opscout.services.tools.runtime import Call, Outcome

_STATISTIC = re.compile(r"^(Average|Sum|Minimum|Maximum|SampleCount|p[0-9]{1,2}(\.[0-9]{1,2})?)$")
MAX_PERIOD: Final = 86_400
HISTORY_ITEMS: Final = 50


def alarm_summary(alarm: Mapping[str, Any]) -> dict[str, Any]:
    """The reviewed fields of a CloudWatch alarm."""
    metric = None
    if "MetricName" in alarm:
        metric = {
            "namespace": alarm.get("Namespace"),
            "name": alarm["MetricName"],
            "dimensions": {d["Name"]: d["Value"] for d in alarm.get("Dimensions", [])},
            "statistic": alarm.get("Statistic") or alarm.get("ExtendedStatistic"),
            "period": alarm.get("Period"),
        }
    return {
        "name": alarm.get("AlarmName"),
        "state": alarm.get("StateValue"),
        "reason": alarm.get("StateReason"),
        "updated": alarm.get("StateUpdatedTimestamp"),
        "threshold": alarm.get("Threshold"),
        "comparison": alarm.get("ComparisonOperator"),
        "evaluation_periods": alarm.get("EvaluationPeriods"),
        "metric": metric,
        "metric_math": "Metrics" in alarm,
    }


def _datapoints(
    call: Call,
    environment: Any,
    region: str,
    metric: Mapping[str, Any],
    stat: str,
    period: int,
    window: Window,
) -> tuple[list[dict[str, Any]], list[Capped]]:
    limit = call.caps.default("datapoints")
    response = call.aws(
        environment,
        region,
        "cloudwatch:GetMetricData",
        MetricDataQueries=[
            {"Id": "m1", "MetricStat": {"Metric": metric, "Period": period, "Stat": stat}}
        ],
        StartTime=window.start,
        EndTime=window.end,
        ScanBy="TimestampAscending",
        MaxDatapoints=limit,
    )
    results = response.get("MetricDataResults", [])
    points: list[dict[str, Any]] = []
    if results:
        points = [
            {"time": time, "value": value}
            for time, value in zip(
                results[0].get("Timestamps", []), results[0].get("Values", []), strict=False
            )
        ]
    capped = []
    if len(points) > limit:
        capped.append(Capped("datapoints", limit, len(points) - limit))
        points = points[:limit]
    return points, capped


def read_alarm(call: Call) -> Outcome:
    """An alarm's state, threshold and history, and its metric over the window (FR-019)."""
    environment = call.environment()
    region = call.region(environment)
    name = call.argument("name")
    if not isinstance(name, str) or not name:
        raise ToolError(ErrorReason.INVALID_INPUT, "name is required")
    window, window_cap = call.window("metric_window_hours")
    capped = [window_cap] if window_cap else []
    response = call.aws(environment, region, "cloudwatch:DescribeAlarms", AlarmNames=[name])
    alarms = [*response.get("MetricAlarms", []), *response.get("CompositeAlarms", [])]
    if not alarms:
        raise ToolError(ErrorReason.NOT_FOUND, f"no alarm named {name} in {environment.name}")
    alarm = alarms[0]
    history = call.aws(
        environment,
        region,
        "cloudwatch:DescribeAlarmHistory",
        AlarmName=name,
        HistoryItemType="StateUpdate",
        StartDate=window.start,
        EndDate=window.end,
        MaxRecords=HISTORY_ITEMS,
        ScanBy="TimestampDescending",
    )
    datapoints: list[dict[str, Any]] = []
    if "MetricName" in alarm:
        metric = {
            "Namespace": alarm.get("Namespace"),
            "MetricName": alarm["MetricName"],
            "Dimensions": alarm.get("Dimensions", []),
        }
        stat = alarm.get("Statistic") or alarm.get("ExtendedStatistic") or "Average"
        datapoints, more = _datapoints(
            call, environment, region, metric, stat, int(alarm.get("Period", 60)), window
        )
        capped += more
    return Outcome(
        data={
            "alarm": alarm_summary(alarm),
            "history": [
                {"time": item.get("Timestamp"), "summary": item.get("HistorySummary")}
                for item in history.get("AlarmHistoryItems", [])
            ],
            "datapoints": datapoints,
        },
        environment=environment,
        window=window,
        capped=capped,
    )


def read_metric(call: Call) -> Outcome:
    """A metric's values by statistic and period over the window (FR-020)."""
    environment = call.environment()
    region = call.region(environment)
    namespace, name = call.argument("namespace"), call.argument("metric")
    if not isinstance(namespace, str) or not isinstance(name, str) or not namespace or not name:
        raise ToolError(ErrorReason.INVALID_INPUT, "namespace and metric are required")
    statistic = call.argument("statistic") or "Average"
    if not _STATISTIC.match(statistic):
        raise ToolError(
            ErrorReason.INVALID_INPUT,
            "statistic must be Average, Sum, Minimum, Maximum, SampleCount or a percentile",
        )
    period = call.argument("period")
    period = 300 if period is None else period
    if not isinstance(period, int) or period < 60 or period % 60 or period > MAX_PERIOD:
        raise ToolError(
            ErrorReason.INVALID_INPUT, f"period must be a multiple of 60 up to {MAX_PERIOD}"
        )
    dimensions = call.argument("dimensions") or {}
    window, window_cap = call.window("metric_window_hours")
    capped = [window_cap] if window_cap else []
    metric = {
        "Namespace": namespace,
        "MetricName": name,
        "Dimensions": [{"Name": key, "Value": value} for key, value in dimensions.items()],
    }
    datapoints, more = _datapoints(call, environment, region, metric, statistic, period, window)
    capped += more
    if not datapoints:
        listed = call.aws(environment, region, "cloudwatch:ListMetrics", **metric)
        if not listed.get("Metrics"):
            raise ToolError(
                ErrorReason.NOT_FOUND,
                f"no metric {namespace}/{name} with those dimensions in {environment.name}",
            )
    return Outcome(
        data={
            "namespace": namespace,
            "metric": name,
            "dimensions": dict(dimensions),
            "statistic": statistic,
            "period": period,
            "datapoints": datapoints,
        },
        environment=environment,
        window=window,
        capped=capped,
    )
