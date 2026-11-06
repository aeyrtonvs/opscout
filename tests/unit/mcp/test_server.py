# SPDX-License-Identifier: Apache-2.0
"""The MCP server, through an in-process client (spec 011, FR-002 to FR-004; SC-002)."""

import json
import subprocess
import sys
from collections.abc import Callable
from typing import Any

import anyio
import pytest
from mcp import Client

from opscout.core.config import Configuration, InvalidConfigError, Problem
from opscout.entrypoints.mcp import build_server
from opscout.services.tools import registry
from tests.unit.mcp.fakes import FakeCallLog, FakeGateway

TOOLS = [
    "list_environments",
    "parse_alert",
    "resolve_environment",
    "read_alarm",
    "read_metric",
    "query_logs",
    "recent_changes",
    "find_resources",
    "describe_resource",
]


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 011."""
    return pytest.mark.spec("011", requirement)


def _absent() -> Configuration | None:
    return None


def _invalid() -> Configuration | None:
    problem = Problem("config.yaml", 2, 1, "aws", "two environments share a name")
    raise InvalidConfigError((problem,))


def _no_cloud() -> Configuration | None:
    return Configuration(schema_version=1)


def _list(loader: Callable[[], Configuration | None]) -> list[str]:
    async def main() -> list[str]:
        server = build_server(loader, FakeGateway, FakeCallLog())
        async with Client(server) as client:
            return [tool.name for tool in (await client.list_tools()).tools]

    return anyio.run(main)


def _call(
    loader: Callable[[], Configuration | None], name: str, arguments: dict[str, Any]
) -> tuple[bool, dict[str, Any]]:
    async def main() -> tuple[bool, dict[str, Any]]:
        server = build_server(loader, FakeGateway, FakeCallLog())
        async with Client(server) as client:
            result = await client.call_tool(name, arguments)
            content = result.structured_content
            if content is None:
                text = "".join(getattr(block, "text", "") for block in result.content)
                return result.is_error, {"text": text}
            return result.is_error, dict(content)

    return anyio.run(main)


@spec("FR-002")
@pytest.mark.parametrize("loader", [_absent, _invalid, _no_cloud])
def test_the_server_lists_nine_tools_whatever_the_configuration(
    loader: Callable[[], Configuration | None],
) -> None:
    assert _list(loader) == TOOLS


@spec("FR-003")
def test_every_tool_has_a_description_and_input_and_output_schemas() -> None:
    async def main() -> None:
        async with Client(build_server(_absent, FakeGateway, FakeCallLog())) as client:
            for tool in (await client.list_tools()).tools:
                assert tool.description, tool.name
                assert tool.input_schema["type"] == "object", tool.name
                assert tool.output_schema is not None, tool.name
                assert {"data", "error", "identity", "capped"} <= set(
                    tool.output_schema["properties"]
                ), tool.name

    anyio.run(main)


@spec("FR-002")
def test_listing_is_fast_and_does_not_load_the_aws_sdk() -> None:
    script = (
        "import sys, time, anyio\n"
        "from mcp import Client\n"
        "start = time.monotonic()\n"
        "from opscout.entrypoints.mcp import build_server\n"
        "from tests.unit.mcp.fakes import FakeCallLog, FakeGateway\n"
        "async def main():\n"
        "    async with Client(build_server(lambda: None, FakeGateway, FakeCallLog())) as c:\n"
        "        return len((await c.list_tools()).tools)\n"
        "count = anyio.run(main)\n"
        "loaded = ['boto3' in sys.modules, 'botocore' in sys.modules]\n"
        "print(count, time.monotonic() - start, *loaded)\n"
    )
    done = subprocess.run(  # noqa: S603
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )
    count, seconds, boto3, botocore = done.stdout.split()
    assert (count, boto3, botocore) == ("9", "False", "False")
    assert float(seconds) < 2.0


@spec("FR-003")
def test_input_that_breaks_the_schema_is_refused_before_the_handler_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ran: list[str] = []
    monkeypatch.setitem(registry.HANDLERS, "parse_alert", lambda call: ran.append("x"))

    is_error, content = _call(_absent, "parse_alert", {"text": 42})

    assert is_error
    assert ran == []
    assert "text" in json.dumps(content)


@spec("FR-004")
def test_a_failing_handler_is_a_structured_error_and_the_server_goes_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(call: object) -> None:
        raise RuntimeError("boom")

    async def main() -> tuple[Any, Any]:
        server = build_server(_no_cloud, FakeGateway, FakeCallLog())
        async with Client(server) as client:
            monkeypatch.setitem(registry.HANDLERS, "parse_alert", broken)
            first = await client.call_tool("parse_alert", {"text": "x"})
            monkeypatch.undo()
            second = await client.call_tool("list_environments", {})
            return first, second

    first, second = anyio.run(main)
    assert first.is_error
    assert first.structured_content["error"]["reason"] == "internal-error"
    assert "boom" not in json.dumps(first.structured_content)
    assert not second.is_error


@spec("FR-004")
def test_an_invalid_configuration_is_named_with_its_fix() -> None:
    for name, arguments in (("parse_alert", {"text": "x"}), ("list_environments", {})):
        is_error, content = _call(_invalid, name, arguments)
        assert is_error
        assert content["error"]["reason"] == "invalid-config"
        assert content["error"]["fix"] == "opscout config validate"
        assert content["data"] is None


@spec("FR-002")
def test_an_absent_configuration_still_answers() -> None:
    is_error, content = _call(_absent, "list_environments", {})
    assert not is_error
    assert content["data"] == {"environments": []}
    is_error, content = _call(_absent, "parse_alert", {"text": "CRITICAL: x"})
    assert is_error
    assert content["error"]["reason"] == "not-configured"


@spec("FR-003")
def test_a_tool_argument_called_name_reaches_its_handler() -> None:
    """Regression: the server's own ``name`` parameter once shadowed the tools' ``name``."""
    for tool, arguments in (
        ("read_alarm", {"environment": "example-prod", "name": "example-cpu"}),
        ("describe_resource", {"environment": "e", "type": "alarm", "name": "example-cpu"}),
        ("find_resources", {"environment": "e", "name": "example"}),
    ):
        is_error, content = _call(_absent, tool, arguments)
        assert is_error
        assert content["error"]["reason"] == "not-configured", tool
