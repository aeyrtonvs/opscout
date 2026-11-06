# SPDX-License-Identifier: Apache-2.0
"""A missing or failing integration never blocks anything else (spec 011, US5, FR-016)."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from botocore.exceptions import ProfileNotFound, UnauthorizedSSOTokenError

from opscout.adapters.aws_fixtures import FixtureGateway
from opscout.adapters.aws_live import LiveGateway
from opscout.core.config import AwsEnvironment
from opscout.services.tools.registry import REGISTRY
from opscout.services.tools.runtime import run_tool
from tests.unit.mcp.fakes import FakeGateway, tool_context

EVALS = Path(__file__).resolve().parents[3] / "evals" / "mcp"
ALERTS_ONLY = """\
schema_version: 1
alerts:
  formats:
    - {name: example, recognize: '^CRITICAL', fields: {title: '^CRITICAL: (.+)$'}}
"""


def _broken(name: str) -> str:
    """One broken environment beside the working, fixture-backed example-prod."""
    return (
        "schema_version: 1\naws:\n  environments:\n"
        f"    - {{name: {name}, account_id: '000000000000', profile: {name}, "
        "regions: [us-east-1]}\n"
        "    - {name: example-prod, account_id: '123456789012', profile: example-prod, "
        "regions: [us-east-1]}\n"
    )


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 011."""
    return pytest.mark.spec("011", requirement)


@spec("FR-016")
def test_without_aws_every_aws_tool_says_so_and_the_rest_work() -> None:
    context = tool_context(FakeGateway(), config=ALERTS_ONLY)

    for tool in REGISTRY:
        if not tool.needs_aws:
            continue
        failed, result = run_tool(tool.name, {"environment": "example-prod"}, context)
        assert failed, tool.name
        assert result["error"]["reason"] == "not-configured", tool.name
        assert result["error"]["fix"] == "see docs/reference/tools.md, Configuration"

    failed, result = run_tool("parse_alert", {"text": "CRITICAL: disk full"}, context)
    assert not failed
    assert result["data"]["fields"]["title"]["value"] == "disk full"
    failed, result = run_tool("list_environments", {}, context)
    assert not failed
    assert result["data"] == {"environments": []}


class _ExpiredClient:
    """A client whose credentials fail as an expired single sign-on login does."""

    class meta:  # noqa: N801  (botocore's attribute name)
        class events:  # noqa: N801
            @staticmethod
            def register_first(*_: Any) -> None:
                return None

    def describe_alarms(self, **_: Any) -> Mapping[str, Any]:
        raise UnauthorizedSSOTokenError()


class _ExpiredSession:
    def client(self, *_: Any, **__: Any) -> _ExpiredClient:
        return _ExpiredClient()


def _session(profile: str) -> Any:
    if profile == "example-missing":
        raise ProfileNotFound(profile=profile)
    return _ExpiredSession()


class _Routing:
    """The live gateway for broken environments; fixtures for the working one."""

    def __init__(self) -> None:
        self.live = LiveGateway(session_factory=_session)
        self.fixtures = FixtureGateway(EVALS / "aws")

    def call(self, environment: AwsEnvironment, *args: Any) -> Mapping[str, Any]:
        gateway: Any = self.fixtures if environment.name == "example-prod" else self.live
        response: Mapping[str, Any] = gateway.call(environment, *args)
        return response


@spec("FR-004")
def test_broken_environments_say_why_and_a_working_one_still_answers() -> None:
    def read(environment: str, broken: str) -> tuple[bool, Any]:
        context = tool_context(_Routing(), config=_broken(broken))  # type: ignore[arg-type]
        arguments = {"environment": environment, "name": "example-api-cpu"}
        return run_tool("read_alarm", arguments, context)

    failed, missing = read("example-missing", "example-missing")
    assert failed
    assert (missing["error"]["reason"], missing["error"]["fix"]) == (
        "profile-missing",
        "aws configure sso",
    )
    failed, expired = read("example-expired", "example-expired")
    assert failed
    assert (expired["error"]["reason"], expired["error"]["fix"]) == (
        "login-expired",
        "aws sso login --profile example-expired",
    )
    failed, working = read("example-prod", "example-expired")
    assert not failed
    assert working["data"]["alarm"]["state"] == "ALARM"
