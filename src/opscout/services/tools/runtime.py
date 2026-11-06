# SPDX-License-Identifier: Apache-2.0
"""Run one tool call: configuration, handler, redaction, caps, envelope and call log.

Every call goes through ``run_tool``, so every result is redacted, capped and stated the
same way (FR-009 to FR-013), every failure is a structured error (FR-004), and every call
leaves one line in the call log (Constitution IX). Handlers reach AWS only through
``Call.aws``, which passes the tool's declared actions and its deadline to the gateway.
"""

import json
import logging
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from opscout.core.aws import AwsGateway, CallEntry, CallLog, find_environment, region_for
from opscout.core.config import AwsEnvironment, Configuration, InvalidConfigError
from opscout.core.tools import (
    DEADLINE_SECONDS,
    Capped,
    Caps,
    Envelope,
    ErrorReason,
    ToolError,
    ToolSpec,
    Window,
    fit,
    parse_window,
)
from opscout.services.redact import redact_structure
from opscout.services.tools.settings import kept_kinds, tool_timezone

logger = logging.getLogger(__name__)

ConfigLoader = Callable[[], Configuration | None]
"""Returns the configuration, None when there is none; raises ``InvalidConfigError``."""


class DeadlineReachedError(Exception):
    """The tool's deadline passed; the handler returns what it has, marked partial."""


@dataclass
class Outcome:
    """What a handler found, before redaction and rendering."""

    data: Mapping[str, Any]
    environment: AwsEnvironment | None = None
    window: Window | None = None
    capped: list[Capped] = field(default_factory=list)
    partial: bool = False


@dataclass
class Call:
    """One tool call as its handler sees it."""

    spec: ToolSpec
    arguments: Mapping[str, Any]
    config: Configuration | None
    caps: Caps
    now: datetime
    timezone: ZoneInfo
    gateway: Callable[[], AwsGateway]
    deadline: float
    clock: Callable[[], float] = time.monotonic

    def argument(self, name: str) -> Any:
        """The argument, or None when it was not given."""
        return self.arguments.get(name)

    def environment(self) -> AwsEnvironment:
        """The environment the call names; ``NOT_CONFIGURED`` without an aws section."""
        if self.config is None or self.config.aws is None:
            raise ToolError(ErrorReason.NOT_CONFIGURED, "AWS is not configured")
        name = self.argument("environment")
        if not isinstance(name, str) or not name:
            raise ToolError(ErrorReason.INVALID_INPUT, "environment is required")
        return find_environment(self.config.aws, name)

    def region(self, environment: AwsEnvironment) -> str:
        """The region the call names, or the environment's default."""
        return region_for(environment, self.argument("region"))

    def window(self, cap: str) -> tuple[Window, Capped | None]:
        """The call's window, with the cap's default and limit in hours."""
        return parse_window(
            self.argument("since"),
            self.argument("until"),
            self.argument("last"),
            now=self.now,
            default=timedelta(hours=self.caps.default(cap)),
            maximum=timedelta(hours=self.caps.limit(cap)),
            cap=cap,
        )

    def remaining(self) -> float:
        """Seconds left before the deadline."""
        return self.deadline - self.clock()

    def aws(
        self, environment: AwsEnvironment, region: str, action: str, **params: Any
    ) -> Mapping[str, Any]:
        """Call one AWS action this tool declared; ``DeadlineReachedError`` past the deadline."""
        remaining = self.remaining()
        if remaining <= 0:
            raise DeadlineReachedError
        return self.gateway().call(
            environment, region, action, params, self.spec.actions, remaining
        )


Handler = Callable[[Call], Outcome]


@dataclass
class ToolContext:
    """What every call shares: where the configuration, AWS and the call log come from."""

    config_loader: ConfigLoader
    gateway_factory: Callable[[], AwsGateway]
    call_log: CallLog
    now: Callable[[], datetime] = lambda: datetime.now(UTC)
    clock: Callable[[], float] = time.monotonic
    deadline_seconds: float = DEADLINE_SECONDS
    _gateway: AwsGateway | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def gateway(self) -> AwsGateway:
        """The gateway, built on first use so that listing tools never loads the AWS SDK."""
        with self._lock:
            if self._gateway is None:
                self._gateway = self.gateway_factory()
            return self._gateway


def _error_result(error: ToolError, zone: ZoneInfo) -> dict[str, Any]:
    return {
        "environment": None,
        "identity": None,
        "timezone": zone.key,
        "window": None,
        "capped": [],
        "redacted": {},
        "partial": False,
        "data": None,
        "error": error.render(),
    }


def _render(outcome: Outcome, call: Call) -> dict[str, Any]:
    data, counts = redact_structure(outcome.data, kept_kinds(call.config))
    environment = outcome.environment
    envelope = Envelope(
        data=data,
        timezone=call.timezone,
        environment=environment.name if environment else None,
        identity=environment.identity if environment else None,
        window=outcome.window,
        capped=tuple(outcome.capped),
        redacted=counts,
        partial=outcome.partial,
    )
    rendered = envelope.render()
    rendered["error"] = None
    overhead = len(json.dumps({**rendered, "data": None}, ensure_ascii=False))
    limit = call.caps.limit("result_chars") - overhead - 200
    rendered["data"], dropped = fit(rendered["data"], limit)
    rendered["capped"] += [entry.render() for entry in dropped]
    return rendered


def run_tool(
    name: str,
    arguments: Mapping[str, Any],
    context: ToolContext,
    handlers: Mapping[str, Handler] | None = None,
    specs: Mapping[str, ToolSpec] | None = None,
) -> tuple[bool, dict[str, Any]]:
    """Run the tool ``name``; return whether it failed, and its rendered result."""
    from opscout.services.tools import registry

    handler = (handlers or registry.HANDLERS)[name]
    spec = (specs or {tool.name: tool for tool in registry.REGISTRY})[name]
    started = context.clock()
    zone = ZoneInfo("UTC")
    environment: str | None = None
    try:
        config = context.config_loader()
        zone = tool_timezone(config)
        caps = Caps.from_config(config.tools.caps) if config else Caps()
        call = Call(
            spec=spec,
            arguments={key: value for key, value in arguments.items() if value is not None},
            config=config,
            caps=caps,
            now=context.now(),
            timezone=zone,
            gateway=context.gateway,
            deadline=started + context.deadline_seconds,
            clock=context.clock,
        )
        try:
            outcome = handler(call)
        except DeadlineReachedError:
            outcome = Outcome(data={}, partial=True)
        environment = outcome.environment.name if outcome.environment else None
        result = _render(outcome, call)
        failed = False
        status = "partial" if result["partial"] else ("capped" if result["capped"] else "ok")
    except InvalidConfigError as error:
        count = len(error.problems)
        result = _error_result(
            ToolError(ErrorReason.INVALID_CONFIG, f"{count} problem(s) in the configuration"),
            zone,
        )
        failed, status = True, ErrorReason.INVALID_CONFIG.value
    except ToolError as error:
        result = _error_result(error, zone)
        failed, status = True, error.reason.value
    except Exception as error:  # every other failure stays inside this call (FR-004)
        logger.exception("tool %s failed", name)
        result = _error_result(ToolError(ErrorReason.INTERNAL, type(error).__name__), zone)
        failed, status = True, ErrorReason.INTERNAL.value
    entry = CallEntry(
        time=context.now(),
        tool=name,
        environment=environment,
        outcome=status,
        duration_ms=int((context.clock() - started) * 1000),
        redacted=dict(result["redacted"]),
    )
    try:
        context.call_log.append(entry)
    except Exception:  # the log never fails a call (research R11)
        logger.exception("the call log could not be written")
    return failed, result
