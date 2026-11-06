# SPDX-License-Identifier: Apache-2.0
"""Fakes for the tool server's ports (spec 011)."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from opscout.core.aws import CallEntry
from opscout.core.config import AwsEnvironment
from opscout.core.tools import ErrorReason, ToolError

Response = Mapping[str, Any] | ToolError | Callable[[Mapping[str, Any]], Mapping[str, Any]]


@dataclass
class FakeGateway:
    """Answers each action from a table; records every call; refuses undeclared actions."""

    responses: dict[str, Response | list[Response]] = field(default_factory=dict)
    calls: list[tuple[str, str, str, dict[str, Any]]] = field(default_factory=list)
    delay: Callable[[], None] | None = None

    def call(
        self,
        environment: AwsEnvironment,
        region: str,
        action: str,
        params: Mapping[str, Any],
        allowed: frozenset[str],
        remaining: float,
    ) -> Mapping[str, Any]:
        if action not in allowed:
            raise ToolError(ErrorReason.UNDECLARED_ACTION, action)
        self.calls.append((environment.name, region, action, dict(params)))
        if self.delay is not None:
            self.delay()
        answer = self.responses.get(action, {})
        if isinstance(answer, list):
            answer = answer.pop(0) if len(answer) > 1 else answer[0]
        if isinstance(answer, ToolError):
            raise answer
        if callable(answer):
            return answer(params)
        return answer


@dataclass
class FakeCallLog:
    """Keeps every entry in memory."""

    entries: list[CallEntry] = field(default_factory=list)

    def append(self, entry: CallEntry) -> None:
        self.entries.append(entry)


@dataclass
class FakeTime:
    """A clock that only moves when something sleeps or a call takes time."""

    now: float = 1000.0

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


ENVIRONMENTS = """\
schema_version: 1
aws:
  environments:
    - name: example-prod
      account_id: "123456789012"
      profile: example-prod
      regions: [us-east-1, us-west-2]
      identity: reference
    - name: example-dev
      account_id: "000000000000"
      profile: example-dev
      regions: [us-east-1]
tools:
  timezone: Europe/Lisbon
"""


def tool_context(
    gateway: FakeGateway, config: str = ENVIRONMENTS, time: FakeTime | None = None
) -> Any:
    """A ToolContext over the fake gateway, a fixed now and, if given, a fake clock."""
    from datetime import UTC, datetime

    from opscout.services.config import parse_config
    from opscout.services.tools.runtime import ToolContext

    loaded = parse_config(config.encode(), "config.yaml")
    clock = time or FakeTime()
    return ToolContext(
        config_loader=lambda: loaded,
        gateway_factory=lambda: gateway,
        call_log=FakeCallLog(),
        now=lambda: datetime(2026, 11, 6, 12, 0, tzinfo=UTC),
        clock=clock.clock,
        sleep=clock.sleep,
    )
