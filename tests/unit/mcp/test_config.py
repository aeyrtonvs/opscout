# SPDX-License-Identifier: Apache-2.0
"""The alerts, aws and tools sections (spec 011, FR-010, FR-011, FR-013 to FR-015)."""

from pathlib import Path

import jsonschema  # type: ignore[import-untyped]
import pytest
import yaml

from opscout.core.config import Configuration, InvalidConfigError, schema_text
from opscout.services.config import parse_config
from opscout.services.tools.settings import tool_timezone

REPO_ROOT = Path(__file__).resolve().parents[3]
COMPAT = REPO_ROOT / "tests" / "unit" / "config_contract" / "compat" / "v1" / "tools.yaml"
SECOND_ACCOUNT = "000000000000"

SECTIONS = """\
alerts:
  formats:
    - name: example-notifier
      recognize: '^(CRITICAL|WARNING): '
      fields:
        severity: '^(CRITICAL|WARNING): '
        account: '^Account: (\\d{12})'
    - name: example-monitor
      recognize: '^Triggered: \\['
      fields:
        project: '^Triggered: \\[([^\\]]+)\\]'
aws:
  environments:
    - name: example-prod
      account_id: "123456789012"
      profile: example-prod
      regions: [us-east-1]
      aliases: [Production, prod]
      identity: reference
    - name: example-dev
      account_id: "000000000000"
      profile: example-dev
      regions: [us-east-1, us-west-2]
tools:
  timezone: Europe/Lisbon
  redact:
    emails: true
  caps:
    log_rows: 200
"""


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 011."""
    return pytest.mark.spec("011", requirement)


def configuration(text: str) -> Configuration:
    return parse_config(f"schema_version: 1\n{text}".encode(), "config.yaml")


def problems(text: str) -> str:
    with pytest.raises(InvalidConfigError) as error:
        configuration(text)
    return "\n".join(problem.render() for problem in error.value.problems)


@spec("FR-014")
def test_the_alert_formats_are_read_in_order() -> None:
    config = configuration(SECTIONS)
    assert config.alerts is not None
    assert [f.name for f in config.alerts.formats] == ["example-notifier", "example-monitor"]
    assert set(config.alerts.formats[0].fields) == {"severity", "account"}


@spec("FR-015")
def test_the_environments_are_read_and_identity_defaults_to_own() -> None:
    config = configuration(SECTIONS)
    assert config.aws is not None
    prod, dev = config.aws.environments
    assert (prod.name, prod.account_id, prod.profile) == (
        "example-prod",
        "123456789012",
        "example-prod",
    )
    assert (prod.identity, dev.identity) == ("reference", "own")
    assert dev.regions == ["us-east-1", "us-west-2"]
    assert dev.aliases == []


@spec("FR-010")
def test_redaction_kinds_default_to_kept() -> None:
    assert configuration("").tools.redact.model_dump() == {
        "account_ids": False,
        "ips": False,
        "emails": False,
    }
    assert configuration(SECTIONS).tools.redact.emails is True


@spec("FR-011")
def test_caps_can_be_lowered_never_raised() -> None:
    assert configuration(SECTIONS).tools.caps == {"log_rows": 200}
    assert "at most 1000" in problems("tools:\n  caps:\n    log_rows: 1001\n")
    assert "unknown cap" in problems("tools:\n  caps:\n    rows: 5\n")
    assert problems("tools:\n  caps:\n    log_rows: 0\n")


@spec("FR-013")
def test_the_timezone_falls_back_to_personal_context_then_utc() -> None:
    assert str(tool_timezone(configuration(SECTIONS))) == "Europe/Lisbon"
    personal = configuration("personal_context:\n  timezone: Europe/Madrid\n")
    assert str(tool_timezone(personal)) == "Europe/Madrid"
    assert str(tool_timezone(configuration(""))) == "UTC"
    assert str(tool_timezone(None)) == "UTC"
    assert "tools.timezone" in problems("tools:\n  timezone: Mars/Base\n")


@spec("FR-014")
@pytest.mark.parametrize(
    ("section", "why"),
    [
        ("alerts:\n  formats: []\n", "no format"),
        (
            "alerts:\n  formats:\n    - {name: Bad, recognize: x, fields: {title: '(x)'}}\n",
            "a name with capitals",
        ),
        (
            "alerts:\n  formats:\n    - {name: a, recognize: '(', fields: {title: '(x)'}}\n",
            "an expression that does not compile",
        ),
        (
            "alerts:\n  formats:\n    - {name: a, recognize: x, fields: {title: 'x'}}\n",
            "a field without a capture group",
        ),
        (
            "alerts:\n  formats:\n    - {name: a, recognize: x, fields: {title: '(x)(y)'}}\n",
            "a field with two capture groups",
        ),
        (
            "alerts:\n  formats:\n    - {name: a, recognize: x, fields: {colour: '(x)'}}\n",
            "an unknown field",
        ),
        (
            "alerts:\n  formats:\n    - {name: a, recognize: x, fields: {}}\n",
            "no field",
        ),
        (
            f"alerts:\n  formats:\n    - {{name: a, recognize: '{'x' * 501}', "
            "fields: {title: '(x)'}}\n",
            "an expression longer than 500 characters",
        ),
        (
            "alerts:\n  formats:\n"
            "    - {name: a, recognize: x, fields: {title: '(x)'}}\n"
            "    - {name: a, recognize: y, fields: {title: '(y)'}}\n",
            "two formats with one name",
        ),
    ],
)
def test_bad_alert_formats_are_refused(section: str, why: str) -> None:
    assert problems(section), why


ENVIRONMENT = (
    "    - {name: example-prod, account_id: '123456789012', profile: p, regions: [us-east-1]"
)


@spec("FR-015")
@pytest.mark.parametrize(
    ("section", "message"),
    [
        ("aws:\n  environments: []\n", ""),
        (f"aws:\n  environments:\n{ENVIRONMENT}, extra: 1}}\n", ""),
        (
            "aws:\n  environments:\n    - {name: e, account_id: '12345', profile: p, "
            "regions: [us-east-1]}\n",
            "",
        ),
        (
            "aws:\n  environments:\n    - {name: e, account_id: 123456789012, profile: p, "
            "regions: [us-east-1]}\n",
            "",
        ),
        (
            "aws:\n  environments:\n    - {name: e, account_id: '123456789012', profile: p, "
            "regions: [useast1]}\n",
            "",
        ),
        (
            "aws:\n  environments:\n    - {name: e, account_id: '123456789012', profile: p, "
            "regions: []}\n",
            "",
        ),
        (
            "aws:\n  environments:\n    - {name: e, account_id: '123456789012', profile: p, "
            "regions: [us-east-1, us-east-1]}\n",
            "each region may be listed only once",
        ),
        (
            f"aws:\n  environments:\n{ENVIRONMENT}}}\n"
            f"    - {{name: example-prod, account_id: '{SECOND_ACCOUNT}', profile: q, "
            "regions: [us-east-1]}\n",
            "two environments share a name",
        ),
        (
            f"aws:\n  environments:\n{ENVIRONMENT}}}\n"
            "    - {name: example-dev, account_id: '123456789012', profile: q, "
            "regions: [us-east-1]}\n",
            "two environments share an account ID",
        ),
        (
            f"aws:\n  environments:\n{ENVIRONMENT}, aliases: [prod]}}\n"
            f"    - {{name: example-dev, account_id: '{SECOND_ACCOUNT}', profile: q, "
            "regions: [us-east-1], aliases: [PROD]}\n",
            "an alias is already the name or an alias of another environment",
        ),
        (
            f"aws:\n  environments:\n{ENVIRONMENT}}}\n"
            f"    - {{name: example-dev, account_id: '{SECOND_ACCOUNT}', profile: q, "
            "regions: [us-east-1], aliases: [Example-Prod]}\n",
            "an alias is already the name or an alias of another environment",
        ),
    ],
)
def test_bad_environments_are_refused(section: str, message: str) -> None:
    assert message in problems(section)


@spec("FR-015")
def test_the_sections_are_optional_and_the_compatibility_file_validates() -> None:
    config = configuration("")
    assert (config.alerts, config.aws) == (None, None)
    assert config.tools.timezone is None
    assert parse_config(COMPAT.read_bytes(), str(COMPAT)).aws is not None


@spec("FR-015")
def test_the_schema_refuses_what_the_loader_refuses() -> None:
    validator = jsonschema.Draft202012Validator(yaml.safe_load(schema_text()))
    assert list(validator.iter_errors(yaml.safe_load(f"schema_version: 1\n{SECTIONS}"))) == []
    bad_sections: tuple[dict[str, object], ...] = (
        {"alerts": {"formats": []}},
        {
            "aws": {
                "environments": [
                    {"name": "e", "account_id": "1", "profile": "p", "regions": ["us-east-1"]}
                ]
            }
        },
        {"tools": {"caps": {"log_rows": 1001}}},
        {"tools": {"caps": {"rows": 1}}},
        {"tools": {"redact": {"phones": True}}},
    )
    for bad in bad_sections:
        assert list(validator.iter_errors({"schema_version": 1, **bad})) != [], bad
