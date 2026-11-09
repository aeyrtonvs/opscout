# SPDX-License-Identifier: Apache-2.0
"""Opening a triage run (spec 012, FR-003, FR-004, FR-008, FR-022; contracts/tools.md)."""

import hashlib
import re
from datetime import UTC, datetime, timedelta

import pytest

from opscout.core.config import Configuration
from opscout.services.config import parse_config
from opscout.services.triage import Stores, begin
from tests.unit.triage.fakes import MemoryEvidence, MemoryRecords

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)

FORMATS = """\
alerts:
  formats:
    - name: example-notifier
      recognize: '^(CRITICAL|WARNING): '
      fields:
        severity: '^(CRITICAL|WARNING): '
        title: '^(?:CRITICAL|WARNING): (.+)$'
        environment: '^Environment: (.+)$'
        resource: '^Resource: (.+)$'
        account: '^Account: (\\d{12})'
        metric: '^Metric: (.+)$'
        time: '^Time: (.+)$'
"""
AWS = """\
aws:
  environments:
    - name: example-prod
      account_id: "123456789012"
      profile: example-prod
      regions: [us-east-1]
      aliases: [Production]
"""
ALERT = """\
CRITICAL: example-api 5XX errors above threshold
Environment: Production
Resource: example-api-alb
Account: 123456789012
Metric: HTTPCode_Target_5XX_Count
"""


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 012."""
    return pytest.mark.spec("012", requirement)


def config(text: str = FORMATS + AWS) -> Configuration:
    return parse_config(f"schema_version: 1\n{text}".encode(), "config.yaml")


def stores() -> Stores:
    return Stores(evidence=MemoryEvidence(), records=MemoryRecords(), engine_version="0.0.0")


@spec("FR-003")
def test_a_parsed_alert_opens_a_run_with_its_environment() -> None:
    used = stores()
    data = begin(ALERT, None, config(), NOW, used)

    assert re.fullmatch(r"20261106T120000Z-[0-9a-f]{6}", data["run_id"])
    assert data["started_at"] == NOW
    assert data["alert"]["format"] == "example-notifier"
    assert data["resolution"]["status"] == "resolved"
    assert data["resolution"]["environment"] == "example-prod"
    assert data["cloud_reads"] is True
    record = used.records.get(data["run_id"])
    assert record is not None
    assert record.outcome == "open"
    assert (record.alert.format, record.alert.environment, record.alert.resource) == (
        "example-notifier",
        "example-prod",
        "example-api-alb",
    )
    assert record.alert.digest == hashlib.sha256(ALERT.encode()).hexdigest()
    assert "errors above threshold" not in record.model_dump_json()


@spec("FR-008")
def test_without_a_time_the_invocation_is_used_and_said() -> None:
    data = begin(ALERT, None, config(), NOW, stores())
    assert data["alert_time"] == {"time": NOW, "source": "invocation"}
    assert data["windows"]["alert"] == {
        "since": NOW - timedelta(hours=1),
        "until": NOW,
    }


@spec("FR-008")
def test_a_time_the_user_names_is_used() -> None:
    named = "2026-11-06T04:40:00-06:00"
    data = begin(ALERT, named, config(), NOW, stores())
    alert_time = datetime.fromisoformat(named)
    assert data["alert_time"] == {"time": alert_time, "source": "user"}
    assert data["windows"]["alert"] == {
        "since": alert_time - timedelta(hours=1),
        "until": alert_time + timedelta(minutes=30),
    }
    assert data["windows"]["changes"]["since"] == alert_time - timedelta(hours=24)


@spec("FR-008")
def test_a_time_in_the_alert_wins_and_keeps_its_offset() -> None:
    text = ALERT + "Time: 2026-11-06T15:40:00+00:00\n"
    data = begin(text, "2026-11-06T09:00:00-06:00", config(), NOW, stores())
    assert data["alert_time"]["source"] == "alert"
    assert data["alert_time"]["time"] == datetime(2026, 11, 6, 15, 40, tzinfo=UTC)
    assert data["alert_time"]["offset"] == "+00:00"


@spec("FR-008")
def test_an_unparsable_time_in_the_alert_is_ignored_and_said() -> None:
    text = ALERT + "Time: yesterday at noon\n"
    data = begin(text, None, config(), NOW, stores())
    assert data["alert_time"]["source"] == "invocation"
    assert data["alert_time"]["unparsed"] == "the alert's time could not be read"


@spec("FR-008")
def test_a_window_never_ends_in_the_future() -> None:
    data = begin(ALERT, NOW.isoformat(), config(), NOW, stores())
    assert data["windows"]["alert"]["until"] == NOW


@spec("FR-008")
def test_the_history_window_follows_the_setting() -> None:
    data = begin(ALERT, None, config(), NOW, stores())
    assert data["settings"]["metric_history_days"] == 7
    assert data["settings"]["history_period"] == 3600
    assert data["windows"]["history"] == {"since": NOW - timedelta(days=7), "until": NOW}
    shorter = config(FORMATS + AWS + "triage:\n  metric_history_days: 2\n")
    data = begin(ALERT, None, shorter, NOW, stores())
    assert data["windows"]["history"]["since"] == NOW - timedelta(days=2)


@spec("FR-008")
def test_the_settings_name_the_clones_that_serve_the_environment() -> None:
    triage = (
        "triage:\n  skeptic: true\n  observability: true\n  infrastructure:\n"
        "    - {name: example-infra, path: /srv/example/infra, environments: [example-prod]}\n"
        "    - {name: example-shared, path: /srv/example/shared}\n"
    )
    data = begin(ALERT, None, config(FORMATS + AWS + triage), NOW, stores())
    assert data["settings"]["infrastructure"] == ["example-infra", "example-shared"]
    assert (data["settings"]["skeptic"], data["settings"]["observability"]) == (True, True)


@spec("FR-004")
def test_an_out_of_scope_alert_allows_no_cloud_read() -> None:
    text = ALERT.replace("123456789012", "000000000000").replace("Production", "Staging")
    data = begin(text, None, config(), NOW, stores())
    assert data["resolution"]["status"] == "out-of-scope"
    assert {"field": "environment", "value": "Staging"} in data["resolution"]["unmatched"]
    assert data["cloud_reads"] is False


@spec("FR-004")
def test_an_alert_that_names_no_environment_asks_once() -> None:
    text = "CRITICAL: something failed\nResource: example-api-alb\n"
    data = begin(text, None, config(), NOW, stores())
    assert data["resolution"]["status"] == "unknown"
    assert data["cloud_reads"] is False


@spec("FR-004")
def test_an_unknown_format_is_said() -> None:
    data = begin("the site is slow", None, config(), NOW, stores())
    assert data["alert"] == {"matched": False}
    assert data["resolution"]["status"] == "unknown"
    assert data["cloud_reads"] is False


@spec("FR-004")
def test_without_formats_or_aws_the_run_still_opens() -> None:
    data = begin(ALERT, None, config(""), NOW, stores())
    assert data["alert"] == {"matched": False, "reason": "no alert format is configured"}
    assert data["resolution"]["status"] == "aws-not-configured"
    assert "configuration" in data["resolution"]["fix"]
    assert data["cloud_reads"] is False
    data = begin(ALERT, None, None, NOW, stores())
    assert data["resolution"]["status"] == "aws-not-configured"


@spec("FR-022")
def test_the_ticket_format_is_returned() -> None:
    data = begin(ALERT, None, config(), NOW, stores())
    assert data["ticket_format"]["name"] == "ticket"
    assert data["ticket_format"]["sections"] == [
        "What happened",
        "Why",
        "What was done",
        "What is pending",
    ]
    assert data["ticket_format"]["max_lines"] == 12
    configured = (
        "writeups:\n  formats:\n    ticket:\n      description: Ours.\n"
        "      sections: [Summary, Next]\n      max_lines: 6\n"
    )
    data = begin(ALERT, None, config(FORMATS + AWS + configured), NOW, stores())
    assert (data["ticket_format"]["sections"], data["ticket_format"]["origin"]) == (
        ["Summary", "Next"],
        "configured",
    )


@spec("FR-007")
def test_begin_prunes_old_evidence() -> None:
    used = stores()
    old = used.evidence.put("read_metric", {}, NOW - timedelta(hours=25))
    begin(ALERT, None, config(), NOW, used)
    assert used.evidence.get(old) is None


@spec("FR-008")
def test_an_alert_time_in_the_future_is_clamped_to_now_and_said() -> None:
    future = (NOW + timedelta(hours=3)).isoformat()
    data = begin(ALERT, future, config(), NOW, stores())
    window = data["windows"]["alert"]
    assert window["since"] < window["until"] == NOW
    assert "after now" in data["alert_time"]["future"]
