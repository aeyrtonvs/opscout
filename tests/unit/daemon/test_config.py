# SPDX-License-Identifier: Apache-2.0
"""The ``daemon`` section of the configuration (spec 007, FR-001, FR-002)."""

from pathlib import Path

import jsonschema  # type: ignore[import-untyped]
import pytest
import yaml

from opscout.core.config import (
    Configuration,
    Daemon,
    InvalidConfigError,
    JobSettings,
    KeychainRef,
    schema_text,
)
from opscout.services.config import parse_config

REPO_ROOT = Path(__file__).resolve().parents[3]
COMPAT = REPO_ROOT / "tests" / "unit" / "config_contract" / "compat" / "v1" / "daemon.yaml"


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 007."""
    return pytest.mark.spec("007", requirement)


def configuration(text: str) -> Configuration:
    return parse_config(f"schema_version: 1\n{text}".encode(), "config.yaml")


SECTION = """\
daemon:
  jobs:
    check:
      at: "09:30"
      weekdays: [mon, tue, wed, thu, fri]
      model: sonnet
      budget_usd: 0.1
      max_turns: 5
  claude_path: /opt/example/bin/claude
  secrets:
    claude_token:
      service: opscout-example
"""


@spec("FR-001")
def test_the_section_is_optional_and_additive() -> None:
    assert configuration("").daemon == Daemon()
    assert configuration("").daemon.jobs == {}
    daemon = configuration(SECTION).daemon
    assert daemon.jobs["check"] == JobSettings(
        at="09:30",
        weekdays=["mon", "tue", "wed", "thu", "fri"],
        model="sonnet",
        budget_usd=0.1,
        max_turns=5,
    )
    assert daemon.claude_path == "/opt/example/bin/claude"
    assert daemon.secrets == {"claude_token": KeychainRef(service="opscout-example")}
    compat = parse_config(COMPAT.read_bytes(), str(COMPAT)).daemon
    assert "check" in compat.jobs


@spec("FR-001")
def test_job_defaults() -> None:
    job = configuration('daemon:\n  jobs:\n    check:\n      at: "07:00"\n').daemon.jobs["check"]
    assert job.enabled is True
    assert job.weekdays == ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    assert (job.model, job.budget_usd, job.max_turns) == (None, None, None)


@spec("FR-001")
@pytest.mark.parametrize("model", ["haiku", "sonnet", "opus", "fable", "claude-haiku-5-5"])
def test_models(model: str) -> None:
    text = f'daemon:\n  jobs:\n    check:\n      at: "07:00"\n      model: {model}\n'
    assert configuration(text).daemon.jobs["check"].model == model


@spec("FR-002")
@pytest.mark.parametrize(
    "text",
    [
        'daemon:\n  jobs:\n    standup:\n      at: "09:30"\n',
        "daemon:\n  jobs:\n    check: {}\n",
        'daemon:\n  jobs:\n    check:\n      at: "24:00"\n',
        'daemon:\n  jobs:\n    check:\n      at: "9:30"\n',
        'daemon:\n  jobs:\n    check:\n      at: "09:60"\n',
        "daemon:\n  jobs:\n    check:\n      at: 9:30\n",
        'daemon:\n  jobs:\n    check:\n      at: "09:30"\n      weekdays: []\n',
        'daemon:\n  jobs:\n    check:\n      at: "09:30"\n      weekdays: [mon, mon]\n',
        'daemon:\n  jobs:\n    check:\n      at: "09:30"\n      weekdays: [monday]\n',
        'daemon:\n  jobs:\n    check:\n      at: "09:30"\n      budget_usd: 0\n',
        'daemon:\n  jobs:\n    check:\n      at: "09:30"\n      budget_usd: -1\n',
        'daemon:\n  jobs:\n    check:\n      at: "09:30"\n      budget_usd: 5.01\n',
        'daemon:\n  jobs:\n    check:\n      at: "09:30"\n      max_turns: 0\n',
        'daemon:\n  jobs:\n    check:\n      at: "09:30"\n      max_turns: 51\n',
        'daemon:\n  jobs:\n    check:\n      at: "09:30"\n      max_turns: 2.0\n',
        'daemon:\n  jobs:\n    check:\n      at: "09:30"\n      model: gpt-4\n',
        'daemon:\n  jobs:\n    check:\n      at: "09:30"\n      model: ""\n',
        'daemon:\n  jobs:\n    check:\n      at: "09:30"\n      enabled: "yes"\n',
        'daemon:\n  jobs:\n    check:\n      at: "09:30"\n      other: x\n',
        "daemon:\n  claude_path: bin/claude\n",
        "daemon:\n  claude_path: ''\n",
        "daemon:\n  secrets:\n    slack_token:\n      service: example\n",
        "daemon:\n  secrets:\n    claude_token: the-token-itself\n",
        "daemon:\n  other: x\n",
    ],
)
def test_bad_values_are_refused(text: str) -> None:
    with pytest.raises(InvalidConfigError):
        configuration(text)


@spec("FR-002")
def test_the_schema_refuses_what_the_loader_refuses(tmp_path: Path) -> None:
    schema = yaml.safe_load(schema_text())
    validator = jsonschema.Draft202012Validator(schema)
    good = yaml.safe_load(f"schema_version: 1\n{SECTION}")
    assert list(validator.iter_errors(good)) == []
    for bad in (
        {"jobs": {"daily": {"at": "09:30"}}},
        {"jobs": {"check": {"at": "24:00"}}},
        {"jobs": {"check": {"at": "09:30", "weekdays": ["mon", "mon"]}}},
        {"jobs": {"check": {"at": "09:30", "model": "gpt-4"}}},
        {"jobs": {"check": {"at": "09:30", "budget_usd": 0}}},
        {"secrets": {"slack_token": {"service": "example"}}},
    ):
        assert list(validator.iter_errors({"schema_version": 1, "daemon": bad})) != [], bad
