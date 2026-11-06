# SPDX-License-Identifier: Apache-2.0
"""Parsing an alert against the declared formats (spec 011, FR-017)."""

import json
from pathlib import Path
from typing import Any

import pytest

from opscout.core.alerts import MAX_ALERT_CHARS, parse_alert, resolve
from opscout.core.config import Alerts
from opscout.services.config import parse_config
from opscout.services.tools.runtime import ToolContext, run_tool
from tests.unit.mcp.fakes import FakeCallLog, FakeGateway

CONFIG = """\
schema_version: 1
alerts:
  formats:
    - name: example-notifier
      recognize: '^(CRITICAL|WARNING): '
      fields:
        severity: '^(CRITICAL|WARNING): '
        title: '^(?:CRITICAL|WARNING): (.+)$'
        environment: '^Environment: (.+)$'
        account: '^Account: (\\d{12})'
        region: '^Region: ([a-z0-9-]+)$'
        threshold: '^Threshold: (.+)$'
    - name: example-monitor
      recognize: '^Triggered: \\['
      fields:
        project: '^Triggered: \\[([^\\]]+)\\]'
        environment: '^Triggered: \\[[^\\]]+\\]\\[([^\\]]+)\\]'
    - name: example-any-critical
      recognize: 'CRITICAL'
      fields:
        title: '^(.+)$'
"""

NOTIFIER = """\
CRITICAL: example-api CPU above 90%
Environment: example-prod
Account: 123456789012
Region: us-east-1
"""


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 011."""
    return pytest.mark.spec("011", requirement)


def _alerts() -> Alerts:
    alerts = parse_config(CONFIG.encode(), "config.yaml").alerts
    assert alerts is not None
    return alerts


@spec("FR-017")
def test_a_declared_format_returns_its_name_and_fields_with_their_source() -> None:
    result = parse_alert(NOTIFIER, _alerts())

    assert result.format == "example-notifier"
    assert result.fields["severity"].value == "CRITICAL"
    assert result.fields["title"].value == "example-api CPU above 90%"
    assert result.fields["account"].value == "123456789012"
    assert result.fields["account"].source == "Account: 123456789012"
    assert result.fields["region"].value == "us-east-1"


@spec("FR-017")
def test_a_field_that_does_not_match_is_absent_never_guessed() -> None:
    result = parse_alert(NOTIFIER, _alerts())

    assert "threshold" not in result.fields


@spec("FR-017")
def test_no_matching_format_is_said_and_returns_no_field() -> None:
    result = parse_alert("Disk almost full on example-host", _alerts())

    assert result.format is None
    assert result.fields == {}
    assert result.render() == {"matched": False}


@spec("FR-017")
def test_the_first_matching_format_wins_and_the_others_are_named() -> None:
    result = parse_alert(NOTIFIER, _alerts())

    assert result.also_matched == ("example-any-critical",)
    monitor = parse_alert("Triggered: [example-api][prod] High latency", _alerts())
    assert monitor.format == "example-monitor"
    assert monitor.fields["project"].value == "example-api"
    assert monitor.fields["environment"].value == "prod"
    assert monitor.also_matched == ()


@spec("FR-017")
def test_text_beyond_the_limit_is_cut_and_the_cut_recorded() -> None:
    tail = "\nAccount: 123456789012"
    text = "CRITICAL: x\n" + "y" * MAX_ALERT_CHARS + tail

    result = parse_alert(text, _alerts())

    assert "account" not in result.fields
    assert result.cut == len(text) - MAX_ALERT_CHARS


def _run(text: str, config: str = CONFIG) -> tuple[bool, dict[str, Any]]:
    loaded = parse_config(config.encode(), "config.yaml")
    context = ToolContext(
        config_loader=lambda: loaded, gateway_factory=FakeGateway, call_log=FakeCallLog()
    )
    return run_tool("parse_alert", {"text": text}, context)


@spec("FR-017")
def test_the_tool_returns_the_parsed_alert_in_its_envelope() -> None:
    failed, result = _run(NOTIFIER)

    assert not failed
    data = result["data"]
    assert data["matched"] is True
    assert data["format"] == "example-notifier"
    assert data["fields"]["account"] == {
        "value": "123456789012",
        "source": "Account: 123456789012",
    }
    assert data["also_matched"] == ["example-any-critical"]
    assert result["environment"] is None


@spec("FR-017")
def test_the_tool_records_a_cut_and_refuses_without_formats() -> None:
    failed, result = _run("CRITICAL: " + "z" * (MAX_ALERT_CHARS + 5))
    assert not failed
    assert {"cap": "alert_chars", "limit": MAX_ALERT_CHARS, "dropped": 15} in result["capped"]

    failed, result = _run(NOTIFIER, "schema_version: 1\n")
    assert failed
    assert result["error"]["reason"] == "not-configured"


CORPUS = Path(__file__).resolve().parents[3] / "evals" / "mcp" / "alerts"


@spec("FR-017")
def test_the_synthetic_corpus_parses_and_resolves_as_expected() -> None:
    """SC-005: 100 % of the corpus parses to its expected fields or to no format."""
    config = parse_config((CORPUS / "config.yaml").read_bytes(), "config.yaml")
    assert config.alerts is not None
    assert config.aws is not None
    cases = sorted((CORPUS / "cases").glob("*.txt"))
    assert len(cases) >= 6
    for case in cases:
        expected = json.loads(case.with_suffix(".json").read_text(encoding="utf-8"))
        parsed = parse_alert(case.read_text(encoding="utf-8"), config.alerts)
        assert parsed.format == expected["format"], case.name
        assert {name: field.value for name, field in parsed.fields.items()} == expected["fields"], (
            case.name
        )
        assert list(parsed.also_matched) == expected.get("also_matched", []), case.name
        fields = {name: field.value for name, field in parsed.fields.items()}
        resolution = resolve(config.aws, fields, case.read_text(encoding="utf-8"))
        name = resolution.environment.name if resolution.environment else None
        assert name == expected["environment"], case.name
