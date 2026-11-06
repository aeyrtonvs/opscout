# SPDX-License-Identifier: Apache-2.0
"""The tool surface's shared types: specs, windows, caps, envelopes and errors (spec 011).

Pure: no I/O. Every tool result passes through an ``Envelope``, which states the
environment, the identity kind, the timezone, the window and what was capped or redacted
(FR-011 to FR-013). Every failure is a ``ToolError`` with a fixed reason (FR-004).
"""

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Final, Literal
from zoneinfo import ZoneInfo

CAP_DEFAULTS: Final[Mapping[str, int]] = {
    "result_chars": 40_000,
    "metric_window_hours": 3,
    "log_window_hours": 1,
    "change_window_hours": 24,
    "log_rows": 100,
    "log_wait_seconds": 30,
    "change_items": 50,
    "stacks": 10,
    "resources": 25,
    "datapoints": 500,
}
"""What a tool uses when the caller asks for nothing else (research R7)."""

CAP_CEILINGS: Final[Mapping[str, int]] = {
    "result_chars": 40_000,
    "metric_window_hours": 14 * 24,
    "log_window_hours": 24,
    "change_window_hours": 7 * 24,
    "log_rows": 1_000,
    "log_wait_seconds": 50,
    "change_items": 200,
    "stacks": 25,
    "resources": 100,
    "datapoints": 1_440,
}
"""The most a caller may ask for; the configuration may lower these, never raise them."""

STRING_CHARS: Final = 4_000
"""The longest string a result keeps whole; a longer one is cut before items are dropped."""

FUTURE_SLACK: Final = timedelta(minutes=5)
"""How far past now a window may end, for clock skew."""

DEADLINE_SECONDS: Final = 45.0
"""After this, a tool makes no further cloud call and returns what it has (research R7)."""

_LAST = re.compile(r"^([1-9][0-9]{0,3})([mhd])$")
_UNITS: Final = {"m": "minutes", "h": "hours", "d": "days"}

IdentityKind = Literal["reference", "own"]
IDENTITY_TEXT: Final[Mapping[str, str]] = {
    "reference": "reference identity",
    "own": "own identity, not verified",
}


class ErrorReason(StrEnum):
    """Why a tool call failed (data-model.md, research R8)."""

    NOT_CONFIGURED = "not-configured"
    INVALID_CONFIG = "invalid-config"
    UNKNOWN_ENVIRONMENT = "unknown-environment"
    PROFILE_MISSING = "profile-missing"
    LOGIN_EXPIRED = "login-expired"
    NO_CREDENTIALS = "no-credentials"
    UNREACHABLE = "unreachable"
    THROTTLED = "throttled"
    DENIED = "denied"
    UNDECLARED_ACTION = "undeclared-action"
    NOT_FOUND = "not-found"
    NOT_SUPPORTED = "not-supported"
    INVALID_INPUT = "invalid-input"
    FIXTURE_MISSING = "fixture-missing"
    INTERNAL = "internal-error"

    def describe(self) -> str:
        """The fixed first part of every message with this reason."""
        return _DESCRIPTIONS[self]


_DESCRIPTIONS: Final[Mapping[ErrorReason, str]] = {
    ErrorReason.NOT_CONFIGURED: "not configured",
    ErrorReason.INVALID_CONFIG: "the configuration has problems",
    ErrorReason.UNKNOWN_ENVIRONMENT: "unknown environment",
    ErrorReason.PROFILE_MISSING: "the AWS profile is not in the AWS config",
    ErrorReason.LOGIN_EXPIRED: "the login expired",
    ErrorReason.NO_CREDENTIALS: "no AWS credentials were found",
    ErrorReason.UNREACHABLE: "AWS could not be reached",
    ErrorReason.THROTTLED: "AWS throttled the call",
    ErrorReason.DENIED: "the identity does not allow this call",
    ErrorReason.UNDECLARED_ACTION: "the tool tried an action it did not declare",
    ErrorReason.NOT_FOUND: "not found",
    ErrorReason.NOT_SUPPORTED: "not supported",
    ErrorReason.INVALID_INPUT: "invalid input",
    ErrorReason.FIXTURE_MISSING: "no fixture matches this call",
    ErrorReason.INTERNAL: "the tool failed unexpectedly",
}

_FIXES: Final[Mapping[ErrorReason, str]] = {
    ErrorReason.NOT_CONFIGURED: "see docs/reference/tools.md, Configuration",
    ErrorReason.INVALID_CONFIG: "opscout config validate",
    ErrorReason.PROFILE_MISSING: "aws configure sso",
}


class ToolError(Exception):
    """A tool call that failed, with a fixed reason and, when one exists, its fix."""

    def __init__(self, reason: ErrorReason, detail: str, *, fix: str | None = None) -> None:
        self.reason = reason
        self.message = f"{reason.describe()}: {detail}"
        self.fix = fix if fix is not None else _FIXES.get(reason)
        super().__init__(self.message)

    def render(self) -> dict[str, str | None]:
        """The error as a tool returns it."""
        return {"reason": self.reason.value, "message": self.message, "fix": self.fix}


@dataclass(frozen=True)
class ToolSpec:
    """One tool: what it does, and every AWS action it may call (FR-003, FR-005)."""

    name: str
    description: str
    actions: frozenset[str] = frozenset()
    needs_aws: bool = False


@dataclass(frozen=True)
class Registry:
    """The tools the server offers, by unique name."""

    tools: tuple[ToolSpec, ...]

    def __post_init__(self) -> None:
        names = [tool.name for tool in self.tools]
        if len(names) != len(set(names)):
            raise ValueError("tool names must be unique")

    def __iter__(self) -> Any:
        return iter(self.tools)


@dataclass(frozen=True, order=True)
class Window:
    """A time window; both ends are aware."""

    start: datetime
    end: datetime


@dataclass(frozen=True)
class Capped:
    """What a cap removed: for a window, ``dropped`` counts minutes; otherwise, items."""

    cap: str
    limit: int
    dropped: int

    def render(self) -> dict[str, str | int]:
        """The record as a tool returns it."""
        return {"cap": self.cap, "limit": self.limit, "dropped": self.dropped}


@dataclass(frozen=True)
class Caps:
    """The caps in effect: the ceilings, lowered where the configuration says so."""

    configured: Mapping[str, int] = field(default_factory=dict)

    @classmethod
    def from_config(cls, configured: Mapping[str, int]) -> "Caps":
        """Validate configured caps against the ceilings. Raises ``ValueError``."""
        for name, value in configured.items():
            if name not in CAP_CEILINGS:
                raise ValueError(f"unknown cap {name}")
            if not 1 <= value <= CAP_CEILINGS[name]:
                raise ValueError(f"{name}: at least 1 and at most {CAP_CEILINGS[name]}")
        return cls(dict(configured))

    def limit(self, name: str) -> int:
        """The most a caller may ask for."""
        return self.configured.get(name, CAP_CEILINGS[name])

    def default(self, name: str) -> int:
        """What a caller gets when it asks for nothing."""
        return min(CAP_DEFAULTS[name], self.limit(name))

    def bound(self, name: str, asked: int | None) -> tuple[int, Capped | None]:
        """The value to use for a request, and a record if the cap lowered it."""
        if asked is None:
            return self.default(name), None
        if asked < 1:
            raise ToolError(ErrorReason.INVALID_INPUT, f"{name} must be at least 1")
        limit = self.limit(name)
        if asked > limit:
            return limit, Capped(name, limit, asked - limit)
        return asked, None


def _instant(text: str, name: str) -> datetime:
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        raise ToolError(
            ErrorReason.INVALID_INPUT, f"{name} must be an ISO 8601 time with an offset"
        ) from None
    if value.tzinfo is None:
        raise ToolError(ErrorReason.INVALID_INPUT, f"{name} has no offset")
    return value


def parse_window(
    since: str | None,
    until: str | None,
    last: str | None,
    *,
    now: datetime,
    default: timedelta,
    maximum: timedelta,
    cap: str,
) -> tuple[Window, Capped | None]:
    """Build a window from ``since``/``until`` or ``last``, capped at ``maximum``.

    Raises ``ToolError(INVALID_INPUT)`` for an inverted, empty, future or naive window.
    """
    if since is not None and last is not None:
        raise ToolError(ErrorReason.INVALID_INPUT, "give since or last, not both")
    end = _instant(until, "until") if until is not None else now
    if end > now + FUTURE_SLACK:
        raise ToolError(ErrorReason.INVALID_INPUT, "the window ends in the future")
    if last is not None:
        match = _LAST.match(last)
        if match is None:
            raise ToolError(ErrorReason.INVALID_INPUT, "last must look like 15m, 3h or 2d")
        start = end - timedelta(**{_UNITS[match[2]]: int(match[1])})
    elif since is not None:
        start = _instant(since, "since")
    else:
        start = end - default
    if start >= end:
        raise ToolError(ErrorReason.INVALID_INPUT, "the window must start before it ends")
    if end - start > maximum:
        dropped = int((end - start - maximum).total_seconds() // 60)
        return Window(end - maximum, end), Capped(
            cap, int(maximum.total_seconds() // 3600), dropped
        )
    return Window(start, end), None


def _size(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False, default=str))


def _cut_strings(value: Any, cut: list[int]) -> Any:
    if isinstance(value, str) and len(value) > STRING_CHARS:
        cut.append(1)
        return f"{value[:STRING_CHARS]} [cut {len(value) - STRING_CHARS} characters]"
    if isinstance(value, Mapping):
        return {key: _cut_strings(item, cut) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_cut_strings(item, cut) for item in value]
    return value


def _lists(value: Any) -> Iterable[list[Any]]:
    if isinstance(value, list):
        yield value
        for item in value:
            yield from _lists(item)
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _lists(item)


def fit(data: Mapping[str, Any], limit: int) -> tuple[dict[str, Any], list[Capped]]:
    """Fit ``data`` within ``limit`` characters of JSON (FR-011).

    Strings longer than ``STRING_CHARS`` are cut first; then whole items are dropped from
    the end of the largest list until the result fits.
    """
    result: dict[str, Any] = json.loads(json.dumps(data, ensure_ascii=False, default=str))
    if _size(result) <= limit:
        return result, []
    capped: list[Capped] = []
    cut: list[int] = []
    result = _cut_strings(result, cut)
    if cut:
        capped.append(Capped("string_chars", STRING_CHARS, len(cut)))
    dropped = 0
    while (excess := _size(result) - limit) > 0:
        lists = [items for items in _lists(result) if items]
        if not lists:
            result = {"omitted": f"the result did not fit in {limit} characters"}
            dropped += 1
            break
        largest = max(lists, key=_size)
        while excess > 0 and largest:
            excess -= _size(largest.pop()) + 2
            dropped += 1
    if dropped:
        capped.append(Capped("result_chars", limit, dropped))
    return result, capped


def _render_times(value: Any, zone: ZoneInfo) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(zone).isoformat()
    if isinstance(value, Mapping):
        return {key: _render_times(item, zone) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_render_times(item, zone) for item in value]
    return value


@dataclass(frozen=True)
class Envelope:
    """A tool's result with everything the reader needs to weigh it (FR-012, FR-013)."""

    data: Mapping[str, Any]
    timezone: ZoneInfo
    environment: str | None = None
    identity: IdentityKind | None = None
    window: Window | None = None
    capped: tuple[Capped, ...] = ()
    redacted: Mapping[str, int] = field(default_factory=dict)
    partial: bool = False

    def render(self) -> dict[str, Any]:
        """The envelope as JSON-ready data, every time in the envelope's timezone."""
        zone = self.timezone
        return {
            "environment": self.environment,
            "identity": IDENTITY_TEXT[self.identity] if self.identity else None,
            "timezone": zone.key,
            "window": (
                {
                    "start": _render_times(self.window.start, zone),
                    "end": _render_times(self.window.end, zone),
                }
                if self.window
                else None
            ),
            "capped": [entry.render() for entry in self.capped],
            "redacted": dict(self.redacted),
            "partial": self.partial,
            "data": _render_times(self.data, zone),
        }
