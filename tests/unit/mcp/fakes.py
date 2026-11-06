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
