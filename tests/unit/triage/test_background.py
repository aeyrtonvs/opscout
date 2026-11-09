# SPDX-License-Identifier: Apache-2.0
"""recent_changes drops agent heartbeats by default (spec 012, FR-009; research R7)."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from opscout.services.tools.runtime import run_tool
from tests.unit.mcp.fakes import ENVIRONMENTS, FakeGateway, tool_context

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 012."""
    return pytest.mark.spec("012", requirement)


def event(minutes: int, name: str) -> dict[str, Any]:
    return {
        "EventTime": NOW - timedelta(minutes=minutes),
        "EventName": name,
        "ReadOnly": "false",
        "CloudTrailEvent": json.dumps({"userIdentity": {"arn": "arn:aws:iam::123456789012:x"}}),
        "Resources": [],
    }


def page(*events: dict[str, Any], following: str | None = None) -> dict[str, Any]:
    return {"Events": list(events), **({"NextToken": following} if following else {})}


def gateway(*pages: dict[str, Any]) -> FakeGateway:
    return FakeGateway(
        responses={
            "cloudtrail:LookupEvents": list(pages),
            "cloudformation:DescribeStacks": {"Stacks": []},
        }
    )


def run(fake: FakeGateway, config: str = ENVIRONMENTS, **arguments: Any) -> dict[str, Any]:
    failed, result = run_tool(
        "recent_changes",
        {"environment": "example-prod", **arguments},
        tool_context(fake, config=config),
    )
    assert not failed, result
    data: dict[str, Any] = result["data"]
    return data


@spec("FR-009")
def test_heartbeats_are_dropped_and_counted() -> None:
    fake = gateway(
        page(
            event(1, "UpdateInstanceInformation"),
            event(2, "UpdateService"),
            event(3, "PutInventory"),
        )
    )
    data = run(fake)
    assert [change["action"] for change in data["changes"]] == ["UpdateService"]
    assert data["background_dropped"] == 2


@spec("FR-009")
def test_include_background_keeps_everything() -> None:
    fake = gateway(page(event(1, "UpdateInstanceInformation"), event(2, "UpdateService")))
    data = run(fake, include_background=True)
    assert [c["action"] for c in data["changes"]] == ["UpdateInstanceInformation", "UpdateService"]
    assert data["background_dropped"] == 0


@spec("FR-009")
def test_configured_background_actions_are_dropped_too() -> None:
    config = ENVIRONMENTS + "triage:\n  background_actions: [ExampleAgentHeartbeat]\n"
    fake = gateway(page(event(1, "ExampleAgentHeartbeat"), event(2, "UpdateService")))
    data = run(fake, config=config)
    assert [c["action"] for c in data["changes"]] == ["UpdateService"]
    assert data["background_dropped"] == 1


@spec("FR-009")
def test_dropped_events_do_not_spend_the_page() -> None:
    first = page(*(event(i, "PutInventory") for i in range(1, 4)), following="next")
    second = page(event(10, "UpdateService"), event(11, "CreateTargetGroup"))
    fake = gateway(first, second)
    data = run(fake)
    assert [c["action"] for c in data["changes"]] == ["UpdateService", "CreateTargetGroup"]
    calls = [call for call in fake.calls if call[2] == "cloudtrail:LookupEvents"]
    assert len(calls) == 2
    assert calls[1][3]["NextToken"] == "next"


@spec("FR-009")
def test_pages_are_bounded() -> None:
    noisy = page(event(1, "PutInventory"), following="again")
    fake = gateway(noisy)
    run(fake)
    calls = [call for call in fake.calls if call[2] == "cloudtrail:LookupEvents"]
    assert len(calls) == 4
