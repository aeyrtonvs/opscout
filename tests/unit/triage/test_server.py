# SPDX-License-Identifier: Apache-2.0
"""The triage tools on the opscout server (spec 012, FR-001, FR-006; contracts/tools.md)."""

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp import Client

from opscout.core.config import Configuration
from opscout.entrypoints import mcp as entry
from opscout.entrypoints.mcp import build_server
from opscout.services.config import parse_config
from opscout.services.tools import registry
from tests.unit.mcp.fakes import FakeCallLog, FakeGateway
from tests.unit.triage.fakes import MemoryEvidence, MemoryFiles, MemoryRecords

NEW_TOOLS = [
    "begin_triage",
    "check_verdict",
    "record_agreement",
    "show_evidence",
    "search_iac",
    "read_iac",
]
CONFIG = parse_config(
    b"schema_version: 1\n"
    b"alerts:\n  formats:\n    - {name: example-notifier, recognize: '^CRITICAL: ', "
    b"fields: {account: '^Account: (\\d{12})', resource: '^Resource: (.+)$'}}\n"
    b"aws:\n  environments:\n    - {name: example-prod, account_id: '123456789012', "
    b"profile: example-prod, regions: [us-east-1], identity: reference}\n",
    "config.yaml",
)
ALERT = "CRITICAL: errors\nAccount: 123456789012\nResource: example-api-alb\n"


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 012."""
    return pytest.mark.spec("012", requirement)


def _server(loader: Callable[[], Configuration | None] = lambda: CONFIG) -> Any:
    return build_server(
        loader,
        FakeGateway,
        FakeCallLog(),
        MemoryEvidence(),
        records=MemoryRecords(),
        files=MemoryFiles(),
    )


def _session(steps: Callable[[Any], Any]) -> Any:
    async def main() -> Any:
        async with Client(_server()) as client:
            return await steps(client)

    return anyio.run(main)


@spec("FR-001")
def test_the_server_lists_the_triage_tools_with_schemas() -> None:
    async def steps(client: Any) -> dict[str, Any]:
        return {tool.name: tool for tool in (await client.list_tools()).tools}

    tools = _session(steps)
    for name in NEW_TOOLS:
        assert name in tools, name
        assert tools[name].description, name
        assert tools[name].input_schema["type"] == "object", name
        assert tools[name].output_schema is not None, name


@spec("FR-006")
def test_the_triage_tools_declare_no_aws_action() -> None:
    for name in NEW_TOOLS:
        assert registry.SPECS[name].actions == frozenset(), name
        assert registry.SPECS[name].needs_aws is False, name


@spec("FR-018")
def test_begin_then_check_round_trips_through_the_server() -> None:
    async def steps(client: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        begun = (await client.call_tool("begin_triage", {"text": ALERT})).structured_content
        verdict = {
            "classification": "inconclusive",
            "summary": "Nothing was read.",
            "threshold": {"assessment": "not-assessable", "reason": "No metric was read."},
            "claims": [
                {
                    "text": "The alert belongs to example-prod.",
                    "cites": [{"evidence": begun["evidence"], "quote": "example-prod"}],
                }
            ],
            "timezone": "UTC",
            "alert_time_source": "invocation",
            "environment": "example-prod",
            "identity": "reference identity",
        }
        checked = await client.call_tool(
            "check_verdict", {"run_id": begun["data"]["run_id"], "verdict": verdict}
        )
        return begun, checked.structured_content

    begun, checked = _session(steps)
    assert begun["environment"] == "example-prod"
    assert begun["data"]["resolution"]["status"] == "resolved"
    assert checked["data"]["passed"] is True, checked
    assert checked["data"]["outcome"] == "checked"
    assert checked["evidence"] is None


@spec("FR-024")
def test_agreement_through_the_server() -> None:
    async def steps(client: Any) -> dict[str, Any]:
        begun = (await client.call_tool("begin_triage", {"text": ALERT})).structured_content
        run_id = begun["data"]["run_id"]
        bad = {"classification": "maybe"}
        for _ in range(2):
            await client.call_tool("check_verdict", {"run_id": run_id, "verdict": bad})
        answer = await client.call_tool(
            "record_agreement", {"run_id": run_id, "answer": "disagree", "reason": "noise"}
        )
        content: dict[str, Any] = answer.structured_content
        return content

    content = _session(steps)
    assert content["data"]["agreement"]["answer"] == "disagree"


@spec("FR-006")
def test_mock_mode_comes_from_the_environment_when_no_flag_is_given(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict[str, Any] = {}

    def fake_build(*arguments: Any, **keywords: Any) -> Any:
        seen["gateway"] = arguments[1]

        class Server:
            def run(self, transport: str) -> None:
                seen["transport"] = transport

        return Server()

    monkeypatch.setattr(entry, "build_server", fake_build)
    monkeypatch.setenv("OPSCOUT_MCP_MOCK", str(tmp_path))
    monkeypatch.setenv("OPSCOUT_DATA_DIR", str(tmp_path / "data"))
    assert entry.serve(None, None) == 0
    gateway = seen["gateway"]()
    assert type(gateway).__name__ == "FixtureGateway"
    assert seen["transport"] == "stdio"
    assert os.environ["OPSCOUT_DATA_DIR"].endswith("data")
