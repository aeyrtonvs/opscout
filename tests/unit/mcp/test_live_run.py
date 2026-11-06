# SPDX-License-Identifier: Apache-2.0
"""Faults found by the live run (spec 011, SC-006, T052).

The tests reproduce the faults the run found against a real environment: a server Claude
Code would not start (LR1), a query's own row limit overridden (LR2), log times without a
timezone (LR3), and identifiers redacted as if they were secrets (LR4). Others guard what
the fixes must not break, as the independent review of the fixes asked.
"""

import json
from pathlib import Path

import pytest

from opscout.services.redact import redact
from opscout.services.tools.runtime import run_tool
from tests.unit.mcp.fakes import FakeGateway, tool_context

PLUGIN = Path(__file__).resolve().parents[3] / "plugins" / "opscout"
KEEP = frozenset({"account-id", "ip", "email"})


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 011."""
    return pytest.mark.spec("011", requirement)


@spec("FR-029")
def test_every_option_the_server_uses_has_a_default() -> None:
    """Claude Code does not start a plugin's MCP server that names an unset option (LR1)."""
    manifest = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text("utf-8"))
    server = (PLUGIN / ".mcp.json").read_text(encoding="utf-8")
    options = manifest["userConfig"]

    used = [key for key in options if f"${{user_config.{key}}}" in server]

    assert used == ["config_dir"]
    for key in used:
        assert options[key]["default"] == "", key
        assert options[key].get("required", False) is False, key


@spec("FR-029")
def test_an_empty_option_leaves_the_user_s_own_variable_in_force() -> None:
    """The option goes in ``--config``, where empty means none, not in ``env``, where an
    empty ``OPSCOUT_CONFIG`` would hide the user's own (review of T052)."""
    server = json.loads((PLUGIN / ".mcp.json").read_text("utf-8"))["mcpServers"]["opscout"]

    assert server["args"][-2:] == ["--config", "${user_config.config_dir}"]
    assert "OPSCOUT_CONFIG" not in server.get("env", {})


def _logs(rows: list[list[dict[str, str]]]) -> FakeGateway:
    return FakeGateway(
        responses={
            "logs:StartQuery": {"queryId": "q"},
            "logs:GetQueryResults": {"status": "Complete", "results": rows, "statistics": {}},
        }
    )


@spec("FR-021")
@pytest.mark.parametrize(
    ("query", "asked", "expected"),
    [
        ("fields @message | sort @timestamp desc | limit 20", None, 20),
        ("fields @message | limit 500 | sort @timestamp desc", None, 100),
        ("fields @message | limit 20", 10, 10),
        ("filter @message like /limit 5/", None, 100),
        ("fields @message | limit 20 # the newest", None, 20),
        ('filter @message like "| limit 5 |" | fields @message', None, 100),
        ("# | limit 5\nfields @message", None, 100),
        ("fields @message\n| LIMIT 7", None, 7),
    ],
)
def test_the_query_s_own_limit_is_kept(query: str, asked: int | None, expected: int) -> None:
    """StartQuery's limit overrides the query's own; the smaller one must win (LR2)."""
    gateway = _logs([])
    arguments: dict[str, object] = {
        "environment": "example-prod",
        "log_groups": ["/g"],
        "query": query,
    }
    if asked is not None:
        arguments["limit"] = asked

    failed, _ = run_tool("query_logs", arguments, tool_context(gateway))

    assert not failed
    assert gateway.calls[0][3]["limit"] == expected


@spec("FR-013")
def test_log_times_carry_the_configured_timezone() -> None:
    """Logs Insights writes @timestamp in UTC without an offset (LR3)."""
    row = [
        {"field": "@timestamp", "value": "2026-11-06 18:20:38.264"},
        {"field": "@ingestionTime", "value": "2026-11-06 18:20:39.000"},
        {"field": "@message", "value": "GET / 200"},
    ]
    config = (
        "schema_version: 1\naws:\n  environments:\n"
        "    - {name: example-prod, account_id: '123456789012', profile: p, regions: [us-east-1]}\n"
        "tools:\n  timezone: America/Chicago\n"
    )

    failed, result = run_tool(
        "query_logs",
        {"environment": "example-prod", "log_groups": ["/g"], "query": "fields @message"},
        tool_context(_logs([row]), config=config),
    )

    assert not failed
    assert result["data"]["rows"] == [
        {
            "@timestamp": "2026-11-06T12:20:38.264000-06:00",
            "@ingestionTime": "2026-11-06T12:20:39-06:00",
            "@message": "GET / 200",
        }
    ]


@spec("FR-009")
@pytest.mark.parametrize(
    "text",
    [
        "(service example-api) has started 1 tasks: (task 0123456789abcdef0123456789abcdef).",
        "arn:aws:ecs:us-east-1:123456789012:task/example/0123456789abcdef0123456789abcdef",
        "arn:aws:secretsmanager:us-east-1:123456789012:secret:example/db-AbCdEf",
        "arn:aws:ssm:us-east-1:123456789012:parameter/example/api_token",
    ],
)
def test_identifiers_are_not_taken_for_secrets(text: str) -> None:
    """A task ID or an ARN says where something is, which rule 3 allows (LR4)."""
    assert redact(text, keep=KEEP) == (text, {})


@spec("FR-009")
def test_an_identifier_still_loses_what_the_configuration_redacts() -> None:
    arn = "arn:aws:secretsmanager:us-east-1:123456789012:secret:example-corp/db-AbCdEf"

    redacted, counts = redact(arn, ["Example Corp"])

    assert (
        redacted == "arn:aws:secretsmanager:us-east-1:[account-id]:secret:[deny-listed]/db-AbCdEf"
    )
    assert counts == {"account-id": 1, "deny-listed": 1}


@spec("FR-009")
@pytest.mark.parametrize(
    "text",
    [
        "arn:aws:iam::123456789012:user/x password=hunter2xyz",
        "arn:aws:s3:::example/password=hunter2xyz",
        "token 0123456789abcdef0123456789abcdef",
        "api_key: task 0123456789abcdef0123456789abcdef",
        "task 0123456789abcdef0123456789abcdef",
        "arn:aws:ssm:us-east-1:123456789012:parameter/app/db_password: hunter2xyz",
        "arn:aws:s3:::example/token:hunter2xyz",
        "arn:aws:iam::123456789012:user/x:AKIAEXAMPLEEXAMPLE12",
        "arn:aws:s3:::example/ghp_exampleexampleexampleexampleexamp1",
        "arn:aws:s3:::example/eyJhbGciOiJIUzI1.eyJzdWIiOiIxMjM0.hunter2xyzsig",
        "arn:aws:s3:::example/postgres://admin:hunter2xyz@db.example.com/app",
        '{"Value":"arn:aws:s3:::example/k:secret:hunter2xyz"}',
        "arn:aws:s3:::example/k Authorization: Bearer hunter2xyzabcdef",
        "arn:aws:s3:::example/hunter2xyzhunter2xyzhunter2xyz12",
        "arn:aws:s3:::secret:hunter2xyz",
    ],
)
def test_a_secret_in_or_next_to_an_identifier_is_still_redacted(text: str) -> None:
    """Only the two shapes the live run hit are let through (review of T052)."""
    redacted, counts = redact(text, keep=KEEP)

    assert "hunter2xyz" not in redacted
    assert "0123456789abcdef0123456789abcdef" not in redacted
    assert "AKIAEXAMPLEEXAMPLE12" not in redacted
    assert "ghp_" not in redacted
    assert counts, text


@spec("FR-009")
def test_a_deny_listed_term_at_the_end_of_an_identifier_is_redacted() -> None:
    redacted, counts = redact("arn:aws:s3:::example corp", ["Example Corp"])

    assert redacted == "arn:aws:s3:::[deny-listed]"
    assert counts == {"deny-listed": 1}
