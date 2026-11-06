# SPDX-License-Identifier: Apache-2.0
"""Settings the tools derive from the configuration (spec 011, FR-010, FR-013)."""

from zoneinfo import ZoneInfo

from opscout.core.config import Configuration


def tool_timezone(config: Configuration | None) -> ZoneInfo:
    """The results' timezone: ``tools.timezone``, then ``personal_context``'s, then UTC."""
    if config is not None:
        if config.tools.timezone is not None:
            return ZoneInfo(config.tools.timezone)
        if config.personal_context is not None and config.personal_context.timezone:
            return ZoneInfo(config.personal_context.timezone)
    return ZoneInfo("UTC")


def kept_kinds(config: Configuration | None) -> frozenset[str]:
    """The redaction kinds the configuration keeps; by default all three (FR-010)."""
    redact = config.tools.redact if config is not None else None
    kept = {"account-id", "ip", "email"}
    if redact is not None:
        if redact.account_ids:
            kept.discard("account-id")
        if redact.ips:
            kept.discard("ip")
        if redact.emails:
            kept.discard("email")
    return frozenset(kept)
