# SPDX-License-Identifier: Apache-2.0
"""The tools that need no cloud: environments, alert parsing and resolution (spec 011, US2)."""

from opscout.core import alerts
from opscout.core.tools import Capped, ErrorReason, ToolError
from opscout.services.tools.runtime import Call, Outcome


def list_environments(call: Call) -> Outcome:
    """The configured environments: names, regions, aliases and identity kinds."""
    aws = call.config.aws if call.config is not None else None
    environments = [
        {
            "name": environment.name,
            "regions": list(environment.regions),
            "aliases": list(environment.aliases),
            "identity": environment.identity,
        }
        for environment in (aws.environments if aws is not None else [])
    ]
    return Outcome(data={"environments": environments})


def parse_alert(call: Call) -> Outcome:
    """Parse an alert text against the declared formats (FR-017)."""
    if call.config is None or call.config.alerts is None:
        raise ToolError(ErrorReason.NOT_CONFIGURED, "no alert format is configured")
    text = call.argument("text")
    if not isinstance(text, str):
        raise ToolError(ErrorReason.INVALID_INPUT, "text is required")
    parsed = alerts.parse_alert(text, call.config.alerts)
    capped = [Capped("alert_chars", alerts.MAX_ALERT_CHARS, parsed.cut)] if parsed.cut else []
    return Outcome(data=parsed.render(), capped=capped)


def resolve_environment(call: Call) -> Outcome:
    """Resolve parsed fields or free text to a configured environment (FR-018)."""
    if call.config is None or call.config.aws is None:
        raise ToolError(ErrorReason.NOT_CONFIGURED, "AWS is not configured")
    fields = call.argument("fields") or {}
    text = call.argument("text")
    if not fields and not text:
        raise ToolError(ErrorReason.INVALID_INPUT, "give fields, text or both")
    resolution = alerts.resolve(call.config.aws, fields, text)
    return Outcome(data=resolution.render(), environment=resolution.environment)
