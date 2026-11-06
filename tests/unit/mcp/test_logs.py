# SPDX-License-Identifier: Apache-2.0
"""query_logs (spec 011, FR-011, FR-021)."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from opscout.core.tools import ErrorReason, ToolError
from opscout.services.tools.runtime import run_tool
from tests.unit.mcp.fakes import FakeGateway, FakeTime, tool_context

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
GROUP = "/ecs/example-api"
QUERY = "fields @timestamp, @message | filter @message like /ERROR/"
ROWS = [
    [
        {"field": "@timestamp", "value": "2026-11-06 11:59:00.000"},
        {"field": "@message", "value": f"ERROR timeout calling example-db {index}"},
        {"field": "@ptr", "value": "opaque"},
    ]
    for index in range(3)
]
STATS = {"recordsMatched": 3.0, "recordsScanned": 900.0, "bytesScanned": 12_000.0}


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 011."""
    return pytest.mark.spec("011", requirement)


def _query(**extra: Any) -> dict[str, Any]:
    return {"environment": "example-prod", "log_groups": [GROUP], "query": QUERY, **extra}


def _gateway(*statuses: str) -> FakeGateway:
    results: list[Any] = [
        {
            "status": status,
            "results": ROWS if status == "Complete" else ROWS[:1],
            "statistics": STATS,
        }
        for status in statuses
    ]
    return FakeGateway(
        responses={
            "logs:StartQuery": {"queryId": "q-1"},
            "logs:GetQueryResults": results,
            "logs:StopQuery": {"success": True},
        }
    )


@spec("FR-021")
def test_a_query_starts_is_polled_and_returns_rows_and_statistics() -> None:
    gateway = _gateway("Running", "Complete")

    failed, result = run_tool("query_logs", _query(last="15m"), tool_context(gateway))

    assert not failed
    data = result["data"]
    assert data["status"] == "complete"
    assert data["rows"][0] == {
        "@timestamp": "2026-11-06T11:59:00+00:00",
        "@message": "ERROR timeout calling example-db 0",
    }
    assert len(data["rows"]) == 3
    assert data["statistics"] == {"matched": 3.0, "scanned": 900.0, "bytes": 12_000.0}
    start = gateway.calls[0][3]
    assert start["logGroupNames"] == [GROUP]
    assert start["queryString"] == QUERY
    assert start["startTime"] == int((NOW - timedelta(minutes=15)).timestamp())
    assert start["endTime"] == int(NOW.timestamp())
    assert start["limit"] == 100


@spec("FR-011")
def test_the_window_and_rows_are_capped_and_recorded() -> None:
    gateway = _gateway("Complete")

    failed, result = run_tool("query_logs", _query(last="3d", limit=5_000), tool_context(gateway))

    assert not failed
    assert {"cap": "log_window_hours", "limit": 24, "dropped": 48 * 60} in result["capped"]
    assert {"cap": "log_rows", "limit": 1000, "dropped": 4000} in result["capped"]
    assert gateway.calls[0][3]["limit"] == 1000


@spec("FR-021")
def test_a_query_still_running_at_the_wait_limit_is_stopped_and_partial() -> None:
    time = FakeTime()
    gateway = _gateway("Running")

    failed, result = run_tool("query_logs", _query(), tool_context(gateway, time=time))

    assert not failed
    assert result["data"]["status"] == "partial"
    assert result["partial"] is True
    assert len(result["data"]["rows"]) == 1
    assert [call[2] for call in gateway.calls][-1] == "logs:StopQuery"
    assert time.now - 1000.0 <= 31


@spec("FR-021")
@pytest.mark.parametrize(
    "bad",
    [
        {"query": "x" * 10_001},
        {"log_groups": [f"/g/{index}" for index in range(11)]},
        {"log_groups": []},
        {"limit": 0},
    ],
)
def test_bad_queries_are_invalid_input(bad: dict[str, Any]) -> None:
    failed, result = run_tool("query_logs", _query(**bad), tool_context(_gateway("Complete")))

    assert failed
    assert result["error"]["reason"] == "invalid-input"


@spec("FR-021")
def test_a_failed_query_and_a_missing_group_are_named() -> None:
    failed, result = run_tool("query_logs", _query(), tool_context(_gateway("Failed")))
    assert failed
    assert result["error"]["reason"] == "invalid-input"
    assert "Failed" in result["error"]["message"]

    gateway = FakeGateway(
        responses={
            "logs:StartQuery": ToolError(ErrorReason.NOT_FOUND, "Log group does not exist"),
            "logs:DescribeLogGroups": {"logGroups": [{"logGroupName": "/ecs/example-api-v2"}]},
        }
    )
    failed, result = run_tool("query_logs", _query(), tool_context(gateway))
    assert failed
    assert result["error"]["reason"] == "not-found"
    assert "/ecs/example-api-v2" in result["error"]["message"]
