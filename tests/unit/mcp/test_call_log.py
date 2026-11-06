# SPDX-License-Identifier: Apache-2.0
"""The local call log (spec 011, FR-008; Constitution IX; research R11)."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from opscout.adapters.call_log import JsonlCallLog
from opscout.core.aws import CallEntry
from opscout.services.config import parse_config
from opscout.services.tools.runtime import ToolContext, run_tool
from tests.unit.mcp.fakes import FakeGateway

MARKER = "unique-marker-7f3a"


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 011."""
    return pytest.mark.spec("011", requirement)


@spec("FR-008")
def test_one_line_per_call_with_its_facts(tmp_path: Path) -> None:
    log = JsonlCallLog(tmp_path / "state")
    entry = CallEntry(
        time=datetime(2026, 11, 6, 12, 0, tzinfo=UTC),
        tool="read_alarm",
        environment="example-prod",
        outcome="ok",
        duration_ms=120,
        redacted={"credential": 1},
    )

    log.append(entry)
    log.append(entry)

    lines = (tmp_path / "state" / "mcp-calls.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0]) == {
        "time": "2026-11-06T12:00:00+00:00",
        "tool": "read_alarm",
        "environment": "example-prod",
        "outcome": "ok",
        "duration_ms": 120,
        "redacted": {"credential": 1},
    }


@spec("FR-008")
def test_no_argument_or_output_reaches_the_log(tmp_path: Path) -> None:
    config = parse_config(
        b"schema_version: 1\nalerts:\n  formats:\n    - name: example\n"
        b"      recognize: x\n      fields: {title: '(.+)'}\n",
        "config.yaml",
    )
    context = ToolContext(
        config_loader=lambda: config,
        gateway_factory=FakeGateway,
        call_log=JsonlCallLog(tmp_path),
    )

    run_tool("parse_alert", {"text": f"x {MARKER}"}, context)
    run_tool("list_environments", {}, context)

    text = (tmp_path / "mcp-calls.jsonl").read_text(encoding="utf-8")
    assert MARKER not in text
    assert len(text.splitlines()) == 2


@spec("FR-008")
def test_a_log_that_cannot_be_written_never_fails_the_call(tmp_path: Path) -> None:
    blocked = tmp_path / "file"
    blocked.write_text("not a directory", encoding="utf-8")
    context = ToolContext(
        config_loader=lambda: None,
        gateway_factory=FakeGateway,
        call_log=JsonlCallLog(blocked / "below"),
    )

    failed, result = run_tool("list_environments", {}, context)

    assert not failed
    assert result["data"] == {"environments": []}
