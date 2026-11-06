# SPDX-License-Identifier: Apache-2.0
"""Every tool result carries its evidence identifier (spec 012, FR-007; research R2)."""

import dataclasses
import logging
import re
from typing import Any

import anyio
import pytest
from mcp import Client

from opscout.entrypoints.mcp import build_server
from opscout.services.tools.runtime import run_tool
from tests.unit.mcp.fakes import FakeCallLog, FakeGateway, tool_context
from tests.unit.triage.fakes import MemoryEvidence

ALARM = {
    "cloudwatch:DescribeAlarms": {
        "MetricAlarms": [{"AlarmName": "example-alarm", "StateValue": "ALARM", "MetricName": "m"}]
    }
}


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 012."""
    return pytest.mark.spec("012", requirement)


def _context(store: MemoryEvidence) -> Any:
    return dataclasses.replace(tool_context(FakeGateway(dict(ALARM))), evidence=store)


@spec("FR-007")
def test_a_result_carries_evidence_and_its_stored_copy() -> None:
    store = MemoryEvidence()
    failed, result = run_tool(
        "read_alarm", {"environment": "example-prod", "name": "example-alarm"}, _context(store)
    )
    assert not failed
    assert re.fullmatch(r"ev-[0-9a-f]{10}", result["evidence"])
    stored = store.get(result["evidence"])
    assert stored is not None
    assert stored.tool == "read_alarm"
    assert dict(stored.result) == {k: v for k, v in result.items() if k != "evidence"}


@spec("FR-007")
def test_an_error_carries_evidence_too() -> None:
    store = MemoryEvidence()
    failed, result = run_tool(
        "read_alarm", {"environment": "nowhere", "name": "x"}, _context(store)
    )
    assert failed
    stored = store.get(result["evidence"])
    assert stored is not None
    assert stored.result["error"]["reason"] == "unknown-environment"


@spec("FR-007")
def test_a_store_that_fails_never_fails_the_call(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    failed, result = run_tool(
        "read_alarm",
        {"environment": "example-prod", "name": "example-alarm"},
        _context(MemoryEvidence(fail=True)),
    )
    assert not failed
    assert result["evidence"] is None
    assert "evidence" in caplog.text


@spec("FR-007")
def test_the_output_schema_lists_evidence() -> None:
    async def main() -> None:
        server = build_server(lambda: None, FakeGateway, FakeCallLog())
        async with Client(server) as client:
            for tool in (await client.list_tools()).tools:
                assert tool.output_schema is not None
                assert "evidence" in tool.output_schema["properties"], tool.name

    anyio.run(main)
