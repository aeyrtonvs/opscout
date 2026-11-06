# SPDX-License-Identifier: Apache-2.0
"""query_logs: a CloudWatch Logs Insights query, bounded in time and rows (spec 011, FR-021)."""

import re
from datetime import UTC, datetime
from typing import Any, Final

from opscout.core.tools import ErrorReason, ToolError
from opscout.services.tools.runtime import Call, Outcome

MAX_QUERY_CHARS: Final = 10_000
MAX_GROUPS: Final = 10
POLL_SECONDS: Final = 1.0
STOP_MARGIN: Final = 12.0
"""Seconds kept for StopQuery before the deadline."""
_RUNNING: Final = frozenset({"Scheduled", "Running", "Unknown"})
_LIMIT: Final = re.compile(r"(?i)(?:^|\|)\s*limit\s+(\d+)\s*(?=\||$)")
"""A ``limit`` command of the query: StartQuery's own limit would override it."""
_TIMES: Final = frozenset({"@timestamp", "@ingestionTime"})
"""Fields Logs Insights writes in UTC without an offset (FR-013)."""


def _query_limit(query: str) -> int | None:
    found = [int(value) for value in _LIMIT.findall(query)]
    return min(found) if found else None


def _value(field: str, value: str) -> Any:
    if field in _TIMES:
        try:
            return datetime.strptime(value, "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=UTC)
        except ValueError:
            return value
    return value


def _rows(results: list[list[dict[str, str]]]) -> list[dict[str, Any]]:
    return [
        {
            cell["field"]: _value(cell["field"], cell.get("value", ""))
            for cell in row
            if cell.get("field") != "@ptr"
        }
        for row in results
    ]


def _similar_groups(call: Call, environment: Any, region: str, group: str) -> str:
    name = group.rstrip("/").rsplit("/", 1)[-1]
    try:
        found = call.aws(
            environment, region, "logs:DescribeLogGroups", logGroupNamePattern=name, limit=10
        )
    except ToolError:
        return ""
    names = [entry["logGroupName"] for entry in found.get("logGroups", [])]
    return f"; similar log groups: {', '.join(names)}" if names else ""


def query_logs(call: Call) -> Outcome:
    """Run the query, wait up to the cap, stop it if still running (FR-021)."""
    environment = call.environment()
    region = call.region(environment)
    groups = call.argument("log_groups") or []
    query = call.argument("query") or ""
    if not 1 <= len(groups) <= MAX_GROUPS:
        raise ToolError(ErrorReason.INVALID_INPUT, f"give 1 to {MAX_GROUPS} log groups")
    if not query or len(query) > MAX_QUERY_CHARS:
        raise ToolError(
            ErrorReason.INVALID_INPUT, f"the query must have 1 to {MAX_QUERY_CHARS} characters"
        )
    window, window_cap = call.window("log_window_hours")
    rows, rows_cap = call.caps.bound("log_rows", call.argument("limit"))
    own = _query_limit(query)
    if own is not None:
        rows = max(1, min(rows, own))
    capped = [entry for entry in (window_cap, rows_cap) if entry is not None]
    try:
        started = call.aws(
            environment,
            region,
            "logs:StartQuery",
            logGroupNames=list(groups),
            startTime=int(window.start.timestamp()),
            endTime=int(window.end.timestamp()),
            queryString=query,
            limit=rows,
        )
    except ToolError as error:
        if error.reason is ErrorReason.NOT_FOUND:
            hint = _similar_groups(call, environment, region, groups[0])
            raise ToolError(ErrorReason.NOT_FOUND, f"a log group does not exist{hint}") from None
        raise
    query_id = started["queryId"]
    # The wait is measured by the clock, polls included, and stops early enough to leave
    # time for StopQuery inside the deadline (review M5).
    wait = min(call.caps.default("log_wait_seconds"), max(call.remaining() - STOP_MARGIN, 0))
    wait_until = call.clock() + wait
    while True:
        response = call.aws(environment, region, "logs:GetQueryResults", queryId=query_id)
        status = response.get("status", "Unknown")
        if status not in _RUNNING:
            break
        if call.clock() >= wait_until or call.remaining() < STOP_MARGIN:
            break
        call.sleep(POLL_SECONDS)
    partial = status in _RUNNING
    if partial:
        call.aws(environment, region, "logs:StopQuery", queryId=query_id)
    elif status != "Complete":
        raise ToolError(ErrorReason.INVALID_INPUT, f"the query ended with status {status}")
    statistics = response.get("statistics", {})
    return Outcome(
        data={
            "status": "partial" if partial else "complete",
            "rows": _rows(response.get("results", [])),
            "statistics": {
                "matched": statistics.get("recordsMatched"),
                "scanned": statistics.get("recordsScanned"),
                "bytes": statistics.get("bytesScanned"),
            },
        },
        environment=environment,
        window=window,
        capped=capped,
        partial=partial,
    )
