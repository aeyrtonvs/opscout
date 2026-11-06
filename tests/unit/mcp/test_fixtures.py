# SPDX-License-Identifier: Apache-2.0
"""The fixture gateway behind mock mode (spec 011, FR-007, FR-025, FR-026; research R5)."""

import json
import socket
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from opscout.adapters.aws_fixtures import FixtureGateway
from opscout.core.config import AwsEnvironment
from opscout.core.tools import ErrorReason, ToolError

PROD = AwsEnvironment(
    name="example-prod", account_id="123456789012", profile="example-prod", regions=["us-east-1"]
)
DESCRIBE = "cloudwatch:DescribeAlarms"


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 011."""
    return pytest.mark.spec("011", requirement)


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_: Any, **__: Any) -> None:
        raise AssertionError("mock mode reached the network")

    monkeypatch.setattr(socket.socket, "connect", refuse)


def _write(root: Path, entries: list[dict[str, Any]]) -> None:
    path = root / "example-prod" / "cloudwatch" / "DescribeAlarms.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(entries), encoding="utf-8")


def _call(gateway: FixtureGateway, params: dict[str, Any]) -> Any:
    return gateway.call(PROD, "us-east-1", DESCRIBE, params, frozenset({DESCRIBE}), 40.0)


@spec("FR-025")
def test_the_first_matching_entry_answers_and_times_become_datetimes(tmp_path: Path) -> None:
    _write(
        tmp_path,
        [
            {"match": {"AlarmNames": ["other"]}, "response": {"MetricAlarms": []}},
            {
                "match": {"AlarmNames": ["example-cpu"]},
                "response": {
                    "MetricAlarms": [
                        {
                            "AlarmName": "example-cpu",
                            "StateUpdatedTimestamp": "2026-11-06T10:00:00Z",
                        }
                    ]
                },
            },
            {"match": {}, "response": {"MetricAlarms": [{"AlarmName": "fallback"}]}},
        ],
    )
    gateway = FixtureGateway(tmp_path)

    alarm = _call(gateway, {"AlarmNames": ["example-cpu"]})["MetricAlarms"][0]

    assert alarm["StateUpdatedTimestamp"] == datetime(2026, 11, 6, 10, 0, tzinfo=UTC)
    assert _call(gateway, {"AlarmNames": ["x"]})["MetricAlarms"][0]["AlarmName"] == "fallback"


@spec("FR-025")
def test_an_error_entry_becomes_its_tool_error(tmp_path: Path) -> None:
    _write(
        tmp_path,
        [{"match": {}, "error": {"reason": "login-expired", "fix": "aws sso login --profile x"}}],
    )

    with pytest.raises(ToolError) as error:
        _call(FixtureGateway(tmp_path), {})

    assert error.value.reason is ErrorReason.LOGIN_EXPIRED
    assert error.value.fix == "aws sso login --profile x"


@spec("FR-026")
def test_no_file_or_no_match_names_the_fixture_and_never_goes_live(tmp_path: Path) -> None:
    gateway = FixtureGateway(tmp_path)
    with pytest.raises(ToolError) as error:
        _call(gateway, {"AlarmNames": ["example-cpu"]})
    assert error.value.reason is ErrorReason.FIXTURE_MISSING
    assert "example-prod/cloudwatch/DescribeAlarms.json" in error.value.message
    assert "example-cpu" in error.value.message

    _write(tmp_path, [{"match": {"AlarmNames": ["other"]}, "response": {}}])
    with pytest.raises(ToolError) as error:
        _call(gateway, {"AlarmNames": ["example-cpu"]})
    assert error.value.reason is ErrorReason.FIXTURE_MISSING


@spec("FR-007")
def test_an_undeclared_action_is_refused_in_mock_mode_too(tmp_path: Path) -> None:
    _write(tmp_path, [{"match": {}, "response": {}}])

    with pytest.raises(ToolError) as error:
        FixtureGateway(tmp_path).call(
            PROD, "us-east-1", DESCRIBE, {}, frozenset({"cloudwatch:ListMetrics"}), 40.0
        )

    assert error.value.reason is ErrorReason.UNDECLARED_ACTION
