# SPDX-License-Identifier: Apache-2.0
"""Mock mode with the shipped fixtures, through the MCP client (spec 011, FR-025, FR-027;
SC-005). Sockets are blocked: no call may reach the network."""

import json
import socket
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp import Client

from opscout.adapters.aws_fixtures import FixtureGateway
from opscout.core.config import Configuration
from opscout.entrypoints.mcp import build_server
from opscout.services.config import parse_config
from opscout.services.tools.registry import REGISTRY
from tests.unit.mcp.fakes import FakeCallLog

EVALS = Path(__file__).resolve().parents[3] / "evals" / "mcp"
PLANTED = ("fixture-pass-", "Qw7Qw7Qw7")
PROD = {"environment": "example-prod"}
CALLS: list[tuple[str, dict[str, Any]]] = [
    ("list_environments", {}),
    ("parse_alert", {"text": "CRITICAL: example-api CPU high\nAccount: 123456789012"}),
    ("resolve_environment", {"fields": {"account": "123456789012"}}),
    ("read_alarm", {**PROD, "name": "example-api-cpu", "last": "3h"}),
    (
        "read_metric",
        {
            **PROD,
            "namespace": "AWS/ECS",
            "metric": "CPUUtilization",
            "dimensions": {"ServiceName": "example-api"},
        },
    ),
    ("query_logs", {**PROD, "log_groups": ["/ecs/example-api"], "query": "fields @message"}),
    ("recent_changes", {**PROD, "resource_type": "ecs-service", "resource": "example/example-api"}),
    ("find_resources", {**PROD, "tag_key": "team"}),
    ("describe_resource", {**PROD, "type": "ecs-service", "name": "example/example-api"}),
    ("describe_resource", {**PROD, "type": "lambda-function", "name": "example-worker"}),
    ("describe_resource", {**PROD, "type": "rds-instance", "name": "example-db"}),
    ("describe_resource", {**PROD, "type": "ec2-instance", "name": "i-0123456789abcdef1"}),
    ("describe_resource", {**PROD, "type": "load-balancer", "name": "example-alb"}),
    ("describe_resource", {**PROD, "type": "target-group", "name": "example-api"}),
    ("describe_resource", {**PROD, "type": "autoscaling-group", "name": "example-asg"}),
    ("describe_resource", {**PROD, "type": "alarm", "name": "example-api-cpu"}),
]


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 011."""
    return pytest.mark.spec("011", requirement)


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_: Any, **__: Any) -> None:
        raise AssertionError("mock mode reached the network")

    monkeypatch.setattr(socket.socket, "connect", refuse)


def _config() -> Configuration:
    return parse_config((EVALS / "config.yaml").read_bytes(), "config.yaml")


def _calls(calls: list[tuple[str, dict[str, Any]]], root: Path = EVALS / "aws") -> list[Any]:
    async def main() -> list[Any]:
        server = build_server(_config, lambda: FixtureGateway(root), FakeCallLog())
        results = []
        async with Client(server) as client:
            for name, arguments in calls:
                result = await client.call_tool(name, arguments)
                results.append((result.is_error, result.structured_content))
        return results

    return anyio.run(main)


@spec("FR-027")
def test_every_declared_action_has_a_fixture() -> None:
    declared = {action for tool in REGISTRY for action in tool.actions}
    shipped = {
        f"{path.parent.name}:{path.stem}"
        for path in (EVALS / "aws" / "example-prod").rglob("*.json")
    }
    assert shipped == declared


@spec("FR-025")
def test_every_tool_answers_from_the_fixtures_through_the_server() -> None:
    results = _calls(CALLS)

    for (name, arguments), (is_error, content) in zip(CALLS, results, strict=True):
        assert not is_error, (name, arguments, content)
        assert content["error"] is None
        if name not in ("list_environments", "parse_alert"):
            assert content["environment"] == "example-prod", name
            assert content["identity"] == "reference identity", name
        text = json.dumps(content)
        for planted in PLANTED:
            assert planted not in text, (name, planted)


@spec("FR-027")
def test_the_fixtures_exercise_caps_errors_and_redaction() -> None:
    oversized = {
        **PROD,
        "log_groups": ["/ecs/example-api"],
        "query": "fields @message | limit 200 # oversized",
        "last": "3d",
        "limit": 5000,
    }
    results = _calls(
        [
            ("query_logs", oversized),
            ("read_alarm", {**PROD, "name": "example-throttled"}),
            ("read_alarm", {**PROD, "name": "example-expired"}),
            ("query_logs", {**PROD, "log_groups": ["/ecs/example-missing"], "query": "x"}),
            (
                "query_logs",
                {**PROD, "log_groups": ["/ecs/example-api"], "query": "fields @message"},
            ),
        ]
    )

    (_, big), (throttled, throttle), (expired, login), (missing, absent), (_, rows) = results
    caps = {entry["cap"] for entry in big["capped"]}
    assert {"log_window_hours", "log_rows", "result_chars"} <= caps
    assert len(json.dumps(big)) <= 40_000
    assert throttled
    assert throttle["error"]["reason"] == "throttled"
    assert expired
    assert login["error"]["fix"] == "aws sso login --profile example-prod"
    assert missing
    assert absent["error"]["reason"] == "not-found"
    assert rows["redacted"].get("connection-string") == 1
    assert rows["redacted"].get("secret-like", 0) >= 1


@spec("FR-026")
def test_a_call_with_no_fixture_names_it_and_never_goes_live(tmp_path: Path) -> None:
    ((is_error, content),) = _calls([("read_alarm", {**PROD, "name": "x"})], root=tmp_path)

    assert is_error
    assert content["error"]["reason"] == "fixture-missing"
    assert "example-prod/cloudwatch/DescribeAlarms.json" in content["error"]["message"]
