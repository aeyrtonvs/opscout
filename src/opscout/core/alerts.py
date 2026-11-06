# SPDX-License-Identifier: Apache-2.0
"""Parse an alert against the declared formats, and resolve it to an environment (spec 011).

Pure. A format is declared in the private configuration, never learned. Parsing returns
only what the format's expressions match, each field with the text it came from; it never
guesses (FR-017). Resolution matches an account ID, an environment's name or an alias, or
says the alert is out of scope (FR-018).
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from opscout.core.config import Alerts, Aws, AwsEnvironment

MAX_ALERT_CHARS: Final = 20_000
"""Alert text beyond this is cut before matching, which bounds backtracking (research R9)."""

_ACCOUNT = re.compile(r"(?<!\d)\d{12}(?!\d)")
_FIELD_ORDER: Final = ("account", "environment", "project", "resource", "title")


@dataclass(frozen=True)
class ParsedField:
    """A field's value and the text it came from."""

    value: str
    source: str


@dataclass(frozen=True)
class ParsedAlert:
    """The first matching format and its fields, or no format."""

    format: str | None
    fields: Mapping[str, ParsedField] = field(default_factory=dict)
    also_matched: tuple[str, ...] = ()
    cut: int = 0

    def render(self) -> dict[str, Any]:
        """The result as the tool returns it."""
        if self.format is None:
            return {"matched": False}
        return {
            "matched": True,
            "format": self.format,
            "fields": {
                name: {"value": parsed.value, "source": parsed.source}
                for name, parsed in self.fields.items()
            },
            "also_matched": list(self.also_matched),
        }


def parse_alert(text: str, alerts: Alerts) -> ParsedAlert:
    """Parse ``text`` with the first declared format that recognizes it."""
    cut = max(len(text) - MAX_ALERT_CHARS, 0)
    text = text[:MAX_ALERT_CHARS]
    matching = [entry for entry in alerts.formats if re.search(entry.recognize, text, re.MULTILINE)]
    if not matching:
        return ParsedAlert(format=None, cut=cut)
    chosen = matching[0]
    fields: dict[str, ParsedField] = {}
    for name, pattern in chosen.fields.items():
        match = re.search(pattern, text, re.MULTILINE)
        if match is not None and match.group(1) is not None and match.group(1).strip():
            fields[name] = ParsedField(match.group(1).strip(), match.group(0).strip())
    return ParsedAlert(
        format=chosen.name,
        fields=fields,
        also_matched=tuple(entry.name for entry in matching[1:]),
        cut=cut,
    )


@dataclass(frozen=True)
class Resolution:
    """The environment an alert belongs to, or why none matched."""

    environment: AwsEnvironment | None
    matched_by: tuple[str, str] | None = None
    unmatched: tuple[tuple[str, str], ...] = ()

    def render(self) -> dict[str, Any]:
        """The result as the tool returns it."""
        if self.environment is None or self.matched_by is None:
            return {
                "resolved": False,
                "out_of_scope": True,
                "unmatched": [{"field": name, "value": value} for name, value in self.unmatched],
            }
        return {
            "resolved": True,
            "environment": self.environment.name,
            "matched_by": {"field": self.matched_by[0], "value": self.matched_by[1]},
        }


def _by_name(aws: Aws, value: str) -> AwsEnvironment | None:
    wanted = value.strip().casefold()
    for environment in aws.environments:
        names = [environment.name, *environment.aliases]
        if any(wanted == name.casefold() for name in names):
            return environment
    return None


def _by_account(aws: Aws, value: str) -> AwsEnvironment | None:
    for account in _ACCOUNT.findall(value):
        for environment in aws.environments:
            if environment.account_id == account:
                return environment
    return None


def _in_text(aws: Aws, text: str) -> tuple[AwsEnvironment, str] | None:
    for account in _ACCOUNT.findall(text):
        found = _by_account(aws, account)
        if found is not None:
            return found, account
    for environment in aws.environments:
        for name in (environment.name, *environment.aliases):
            match = re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", text, re.IGNORECASE)
            if match is not None:
                return environment, match.group(0)
    return None


def resolve(aws: Aws, fields: Mapping[str, str], text: str | None) -> Resolution:
    """Match an account ID first, then a name or alias, in fields, then in free text."""
    ordered = sorted(
        fields.items(),
        key=lambda item: _FIELD_ORDER.index(item[0]) if item[0] in _FIELD_ORDER else 99,
    )
    for name, value in ordered:
        found = _by_account(aws, value) if name == "account" else _by_name(aws, value)
        if found is not None:
            return Resolution(found, (name, value))
    if text:
        in_text = _in_text(aws, text)
        if in_text is not None:
            return Resolution(in_text[0], ("text", in_text[1]))
    return Resolution(None, unmatched=tuple(ordered))
