# SPDX-License-Identifier: Apache-2.0
"""The tools that need no cloud: environments, alert parsing and resolution (spec 011, US2)."""

from opscout.core.tools import ErrorReason, ToolError
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
    """Parse an alert text against the declared formats (built in T027)."""
    if call.config is None or call.config.alerts is None:
        raise ToolError(ErrorReason.NOT_CONFIGURED, "no alert format is configured")
    raise ToolError(ErrorReason.NOT_SUPPORTED, "parse_alert is not built yet")


def resolve_environment(call: Call) -> Outcome:
    """Resolve parsed fields to an environment (built in T027)."""
    if call.config is None or call.config.aws is None:
        raise ToolError(ErrorReason.NOT_CONFIGURED, "AWS is not configured")
    raise ToolError(ErrorReason.NOT_SUPPORTED, "resolve_environment is not built yet")
