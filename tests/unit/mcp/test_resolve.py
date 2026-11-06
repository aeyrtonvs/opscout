# SPDX-License-Identifier: Apache-2.0
"""Resolving an alert to a configured environment (spec 011, FR-018)."""

from typing import Any

import pytest

from opscout.core.alerts import resolve
from opscout.core.config import Aws
from opscout.services.config import parse_config
from opscout.services.tools.runtime import ToolContext, run_tool
from tests.unit.mcp.fakes import FakeCallLog, FakeGateway

CONFIG = """\
schema_version: 1
aws:
  environments:
    - name: example-prod
      account_id: "123456789012"
      profile: example-prod
      regions: [us-east-1, us-west-2]
      aliases: [Production, example-api]
      identity: reference
    - name: example-dev
      account_id: "000000000000"
      profile: example-dev
      regions: [us-east-1]
"""


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 011."""
    return pytest.mark.spec("011", requirement)


def _aws() -> Aws:
    aws = parse_config(CONFIG.encode(), "config.yaml").aws
    assert aws is not None
    return aws


@spec("FR-018")
@pytest.mark.parametrize(
    ("fields", "text", "environment", "matched_by"),
    [
        ({"account": "123456789012"}, None, "example-prod", ("account", "123456789012")),
        ({"environment": "EXAMPLE-DEV"}, None, "example-dev", ("environment", "EXAMPLE-DEV")),
        ({"project": "example-api"}, None, "example-prod", ("project", "example-api")),
        ({"environment": "production"}, None, "example-prod", ("environment", "production")),
        (None, "Account: 000000000000 is high", "example-dev", ("text", "000000000000")),
        (None, "latency up on Production since 10:00", "example-prod", ("text", "Production")),
        (
            {"account": "123456789012", "environment": "example-dev"},
            None,
            "example-prod",
            ("account", "123456789012"),
        ),
    ],
)
def test_an_environment_is_matched_by_account_name_or_alias(
    fields: dict[str, str] | None,
    text: str | None,
    environment: str,
    matched_by: tuple[str, str],
) -> None:
    resolution = resolve(_aws(), fields or {}, text)

    assert resolution.environment is not None
    assert resolution.environment.name == environment
    assert resolution.matched_by == matched_by


@spec("FR-018")
def test_no_match_is_out_of_scope_with_what_did_not_match() -> None:
    only_prod = Aws(environments=[_aws().environments[0]])
    resolution = resolve(only_prod, {"account": "000000000000", "environment": "qa"}, None)

    assert resolution.environment is None
    assert resolution.render() == {
        "resolved": False,
        "out_of_scope": True,
        "unmatched": [
            {"field": "account", "value": "000000000000"},
            {"field": "environment", "value": "qa"},
        ],
    }


def _run(name: str, arguments: dict[str, Any], config: str = CONFIG) -> tuple[bool, Any]:
    loaded = parse_config(config.encode(), "config.yaml")
    context = ToolContext(
        config_loader=lambda: loaded, gateway_factory=FakeGateway, call_log=FakeCallLog()
    )
    return run_tool(name, arguments, context)


@spec("FR-018")
def test_the_tool_states_the_environment_and_its_identity() -> None:
    failed, result = _run("resolve_environment", {"fields": {"account": "123456789012"}})

    assert not failed
    assert result["environment"] == "example-prod"
    assert result["identity"] == "reference identity"
    assert result["data"] == {
        "resolved": True,
        "environment": "example-prod",
        "matched_by": {"field": "account", "value": "123456789012"},
    }


@spec("FR-018")
def test_the_tool_needs_something_to_resolve_and_an_aws_section() -> None:
    failed, result = _run("resolve_environment", {})
    assert failed
    assert result["error"]["reason"] == "invalid-input"

    failed, result = _run("resolve_environment", {"text": "x"}, "schema_version: 1\n")
    assert failed
    assert result["error"]["reason"] == "not-configured"


@spec("FR-018")
def test_list_environments_returns_names_regions_aliases_and_identities() -> None:
    failed, result = _run("list_environments", {})

    assert not failed
    assert result["data"]["environments"] == [
        {
            "name": "example-prod",
            "regions": ["us-east-1", "us-west-2"],
            "aliases": ["Production", "example-api"],
            "identity": "reference",
        },
        {"name": "example-dev", "regions": ["us-east-1"], "aliases": [], "identity": "own"},
    ]
