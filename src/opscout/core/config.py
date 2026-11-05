# SPDX-License-Identifier: Apache-2.0
"""The configuration contract, schema version 1 (spec 002, ADR-0014).

The models here are the source of truth: the loader enforces them, and the JSON Schema
committed at ``schemas/config.schema.json`` is generated from them. Version 1 holds only
``schema_version``; each later feature adds its section as an additive change.

Rules for every later section:

- An additive change (a new optional key or section) keeps ``SCHEMA_VERSION``. A breaking
  change (removing, renaming or retyping a key, or making one required) raises it, moves
  the old version to ``RETIRED_VERSIONS`` and adds a migration note to
  ``docs/reference/configuration.md``.
- No key accepts a secret value. A credential is named by a ``KeychainRef``.
- Every field has a description, which editors show.
"""

import json
import re
import zoneinfo
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Annotated, Any, Final, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)
from pydantic_core import PydanticCustomError

SCHEMA_VERSION: Final = 1
"""The only major version of the schema this engine reads."""

RETIRED_VERSIONS: Final[Mapping[int, str]] = MappingProxyType({})
"""Each retired major version, mapped to the anchor of its migration note."""

MIGRATION_NOTES: Final = "docs/reference/configuration.md"
SCHEMA_DIALECT: Final = "https://json-schema.org/draft/2020-12/schema"
SCHEMA_ID: Final = (
    "https://raw.githubusercontent.com/aeyrtonvs/opscout/main/schemas/config.schema.json"
)

_KeychainName = Annotated[
    str,
    StringConstraints(min_length=1, max_length=128, pattern=r"^[^\s\x00-\x1f\x7f]+$"),
]


def _exact_int(value: object) -> object:
    """Refuse anything but an integer: a literal alone would accept ``1.0`` and ``True``."""
    if type(value) is not int:
        raise PydanticCustomError("int_type", "Input should be a valid integer")
    return value


class KeychainRef(BaseModel):
    """A credential in the OS keychain, named by its service and account, never by its value."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    service: _KeychainName = Field(
        description="The keychain service under which the credential is stored.",
    )
    account: _KeychainName | None = Field(
        default=None,
        description="The keychain account of the credential, when the service holds several.",
    )


_Line = Annotated[str, StringConstraints(min_length=1, max_length=300, pattern=r"^[^\n]*$")]
_FormatName = Annotated[
    str, StringConstraints(max_length=40, pattern=r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
]


class WriteupFormat(BaseModel):
    """A shape for a write-up: its sections in order, its rules and its length (spec 003)."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    description: Annotated[
        str, StringConstraints(min_length=1, max_length=200, pattern=r"^[^\n]*$")
    ] = Field(description="What this format is for, in one line.")
    sections: list[_Line] = Field(
        default_factory=list,
        max_length=30,
        description="The headings of the write-up, in order; none for free text.",
    )
    rules: list[_Line] = Field(
        default_factory=list, max_length=30, description="Rules for this format only."
    )
    max_lines: Annotated[int, Field(ge=1, le=200)] | None = Field(
        default=None, description="The most lines a write-up in this format may have."
    )


class Writeups(BaseModel):
    """Write-up formats for the summary skill; built-in formats apply without them (spec 003)."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    language: (
        Annotated[str, StringConstraints(min_length=1, max_length=40, pattern=r"^[^\n]*$")] | None
    ) = Field(
        default=None,
        description="The language to write in; without it, the language the user writes in.",
    )
    rules: list[_Line] = Field(
        default_factory=list, max_length=30, description="Rules for every format."
    )
    formats: dict[_FormatName, WriteupFormat] = Field(
        default_factory=dict,
        description=(
            "Formats by name. A name of a built-in format (ticket, message, postmortem) "
            "replaces it; a new name adds a format."
        ),
        # Editors must refuse a name the loader refuses, not leave it unchecked.
        json_schema_extra={"additionalProperties": False},
    )


CONVENTIONAL_TYPES: Final = (
    "build",
    "chore",
    "ci",
    "docs",
    "feat",
    "fix",
    "perf",
    "refactor",
    "revert",
    "style",
    "test",
)
"""The Conventional Commit types the ship skill allows by default (spec 004)."""

_Branch = Annotated[str, StringConstraints(min_length=1, max_length=100, pattern=r"^\S+$")]
_PATTERN_TOKENS: Final = ("{type}", "{slug}", "{ticket}")


def _known_tokens(pattern: str) -> str:
    """Refuse a branch pattern with a token other than {type}, {slug} and {ticket}."""
    rest = pattern
    for token in _PATTERN_TOKENS:
        rest = rest.replace(token, "")
    if "{slug}" not in pattern or not re.fullmatch(r"[a-z0-9/._-]*", rest):
        raise PydanticCustomError(
            "opscout_branch_pattern",
            "expected lowercase text with {slug} and only the tokens {type}, {slug} and {ticket}",
        )
    return pattern


class PullRequestConventions(BaseModel):
    """How the ship skill opens a pull request (spec 004)."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    base: _Branch | None = Field(
        default=None,
        description="The branch the pull request targets; without it, the remote's default.",
    )
    draft: Literal[True] = Field(
        default=True, description="Pull requests are always drafts for a person to finish."
    )


class Ship(BaseModel):
    """Conventions for the ship skill and its push guard (spec 004)."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    protected_branches: list[_Branch] = Field(
        default_factory=lambda: ["main", "master"],
        max_length=30,
        description=(
            "Branch name patterns (globs such as release/*) that are never pushed to. main, "
            "master and the remote's default branch are protected whatever this says."
        ),
    )
    branch_pattern: Annotated[
        str, StringConstraints(max_length=100), AfterValidator(_known_tokens)
    ] = Field(
        default="{type}/{slug}",
        description="How new branches are named, with the tokens {type}, {slug} and {ticket}.",
    )
    types: list[Annotated[str, StringConstraints(pattern=r"^[a-z]{1,20}$")]] = Field(
        default_factory=lambda: list(CONVENTIONAL_TYPES),
        min_length=1,
        max_length=20,
        description="The Conventional Commit types allowed in commit messages and branch names.",
    )
    trailer: Annotated[
        str, StringConstraints(max_length=100, pattern=r"^[A-Za-z][A-Za-z-]*: [^\n]*\S$")
    ] = Field(
        default="Assisted-by: Claude Code",
        description="The trailer that ends every commit message the skill writes.",
    )
    pull_request: PullRequestConventions = Field(
        default_factory=PullRequestConventions,
        description="How pull requests are opened.",
    )


_SessionName = Annotated[
    str, StringConstraints(min_length=1, max_length=100, pattern=r"^[^\s\x00-\x1f\x7f]+$")
]


def _unique(names: list[str] | None) -> list[str] | None:
    """Refuse a name listed twice."""
    if names is not None and len(set(names)) != len(names):
        raise PydanticCustomError("unique_names", "Each session may be listed only once")
    return names


class Sso(BaseModel):
    """Which SSO logins the session-start check looks at (spec 005)."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    enabled: bool = Field(
        default=True, description="Whether the check runs when a Claude Code session starts."
    )
    sessions: Annotated[
        list[_SessionName] | None, Field(min_length=1, max_length=50), AfterValidator(_unique)
    ] = Field(
        default=None,
        description=(
            "The SSO sessions or older SSO profiles to check, by name; without it, every one "
            "in the AWS config."
        ),
    )


MARKER_TEXT: Final = "opscout:personal-context"
"""Text no personal context value may hold, so the block's markers stay unambiguous."""


def _no_marker(value: str) -> str:
    """Refuse the marker text inside a value (spec 006, FR-002)."""
    if MARKER_TEXT in value:
        raise PydanticCustomError("marker_text", "Must not contain the marker text")
    return value


def _known_zone(value: str) -> str:
    """Refuse a name the zone database does not list, exactly as written.

    Listed names only: on a case-insensitive disk ``zoneinfo`` would also load a miscased
    name, which another machine refuses.
    """
    if value not in zoneinfo.available_timezones():
        raise PydanticCustomError("time_zone", "Unknown time zone")
    return value


_LineBreak = "\\n\\r\\x0b\\x0c\\x1c-\\x1e\\x85\\u2028\\u2029"
"""Every character Python or an editor may treat as a line break."""
_OneLine = f"^[^{_LineBreak}]*\\S[^{_LineBreak}]*$"
_HeadingLine = f"^[^#\\s\\x1c-\\x1e][^{_LineBreak}]*$"
_Language = Annotated[
    str,
    StringConstraints(min_length=1, max_length=40, pattern=_OneLine),
    AfterValidator(_no_marker),
]
_TimeZone = Annotated[
    str,
    StringConstraints(max_length=64, pattern=r"^[A-Za-z][A-Za-z0-9_+-]*(/[A-Za-z0-9_+-]+)*$"),
    AfterValidator(_known_zone),
]
_Heading = Annotated[
    str,
    StringConstraints(min_length=1, max_length=60, pattern=_HeadingLine),
    AfterValidator(_no_marker),
]
_ContextLine = Annotated[
    str,
    StringConstraints(min_length=1, max_length=300, pattern=_OneLine),
    AfterValidator(_no_marker),
]


def _context_schema(schema: dict[str, Any]) -> None:
    """Make the generated schema refuse what the model refuses (spec 006, review).

    Pydantic checks a mapping's keys only by length in JSON Schema, and cannot say "at
    least one field"; both are added here.
    """
    sections = schema["properties"]["sections"]["anyOf"][0]
    sections["propertyNames"]["pattern"] = _HeadingLine
    sections["additionalProperties"] = False
    schema["anyOf"] = [{"required": [name]} for name in ("language", "timezone", "sections")]


class PersonalContext(BaseModel):
    """Facts every Claude Code session should start with (spec 006)."""

    model_config = ConfigDict(
        strict=True, extra="forbid", frozen=True, json_schema_extra=_context_schema
    )

    language: _Language | None = Field(
        default=None, description="The language Claude answers you in."
    )
    timezone: _TimeZone | None = Field(
        default=None, description="Your time zone, as an IANA name such as Europe/Lisbon."
    )
    sections: (
        Annotated[
            dict[_Heading, Annotated[list[_ContextLine], Field(min_length=1, max_length=50)]],
            Field(min_length=1, max_length=20),
        ]
        | None
    ) = Field(
        default=None,
        description="Headings, in order, each with the lines written under it.",
    )

    @model_validator(mode="after")
    def _something(self) -> "PersonalContext":
        if self.language is None and self.timezone is None and self.sections is None:
            raise PydanticCustomError("empty", "Give a language, a time zone or sections")
        return self


JOB_NAMES: Final = ("check",)
"""The jobs the engine defines (spec 007); the configuration schedules them."""

SECRET_NAMES: Final = ("claude_token",)
"""The harness's own secrets the engine uses (spec 007): the fallback Claude Code token."""

_Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

WEEKDAYS: Final[tuple[_Weekday, ...]] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _unique_days(days: list[str]) -> list[str]:
    """Refuse a weekday listed twice."""
    if len(set(days)) != len(days):
        raise PydanticCustomError("unique_weekdays", "Each weekday may be listed only once")
    return days


class JobSettings(BaseModel):
    """When a job runs and the limits of its model run (spec 007)."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    enabled: bool = Field(
        default=True, description="Whether opscout daemon install schedules this job."
    )
    at: Annotated[str, StringConstraints(pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")] = Field(
        description='The time of day, HH:MM in the machine\'s local time; quote it ("09:30").'
    )
    weekdays: Annotated[
        list[_Weekday],
        Field(min_length=1, max_length=7, json_schema_extra={"uniqueItems": True}),
        AfterValidator(_unique_days),
    ] = Field(
        default_factory=lambda: list(WEEKDAYS),
        description="The days it runs, from mon to sun; without it, every day.",
    )
    model: (
        Annotated[
            str,
            StringConstraints(
                max_length=100, pattern=r"^(haiku|sonnet|opus|fable|claude-[a-z0-9][a-z0-9.-]*)$"
            ),
        ]
        | None
    ) = Field(
        default=None,
        description="The model: an alias (haiku, sonnet, opus, fable) or a full claude-… id.",
    )
    budget_usd: Annotated[float, Field(gt=0, le=5)] | None = Field(
        default=None, description="The most one run may cost, in US dollars."
    )
    max_turns: Annotated[int, Field(ge=1, le=50)] | None = Field(
        default=None, description="The most turns one run may take."
    )


class Daemon(BaseModel):
    """Scheduled jobs and what their runs need (spec 007)."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    jobs: Annotated[dict[Literal["check"], JobSettings], Field(max_length=20)] = Field(
        default_factory=dict,
        description="The jobs to schedule, by name; the engine defines them (now only check).",
    )
    claude_path: (
        Annotated[str, StringConstraints(min_length=2, max_length=1024, pattern=r"^/[^\n]*$")]
        | None
    ) = Field(
        default=None,
        description="The Claude Code executable, as an absolute path; without it, PATH.",
    )
    secrets: dict[Literal["claude_token"], KeychainRef] = Field(
        default_factory=dict,
        description=(
            "The harness's own secrets, by name, each a keychain reference; claude_token is "
            "a token from claude setup-token, for jobs that cannot use your login."
        ),
    )


class Configuration(BaseModel):
    """The private opscout configuration (config.yaml in the configuration directory)."""

    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        frozen=True,
        title="opscout configuration",
    )

    schema_version: Annotated[Literal[1], BeforeValidator(_exact_int)] = Field(
        description=(
            "The major version of the configuration schema this file follows. "
            "This engine reads version 1."
        ),
    )
    writeups: Writeups = Field(
        default_factory=Writeups,
        description="Write-up formats for the summary skill (spec 003).",
    )
    ship: Ship = Field(
        default_factory=Ship,
        description="Branch, commit and pull request conventions, and the protected branches.",
    )
    sso: Sso = Field(
        default_factory=Sso,
        description="The SSO check at the start of a Claude Code session (spec 005).",
    )
    personal_context: PersonalContext | None = Field(
        default=None,
        description=(
            "The facts opscout context apply writes into your Claude Code CLAUDE.md (spec 006)."
        ),
    )
    daemon: Daemon = Field(
        default_factory=Daemon,
        description="Scheduled jobs, the Claude Code executable and the harness's secrets "
        "(spec 007).",
    )


@dataclass(frozen=True, order=True)
class Problem:
    """One thing wrong with a configuration file. It never holds the value found."""

    file: str
    line: int
    column: int
    path: str = field(compare=False)
    message: str = field(compare=False)

    def render(self) -> str:
        """Return the problem as ``file:line:column: path: message``."""
        return f"{self.file}:{self.line}:{self.column}: {self.path}: {self.message}"


class ConfigError(Exception):
    """The configuration cannot be used."""


class ConfigLocationError(ConfigError):
    """The configuration directory or file is missing or cannot be read."""


class InvalidConfigError(ConfigError):
    """The configuration file has problems."""

    def __init__(self, problems: tuple[Problem, ...]) -> None:
        super().__init__(f"{len(problems)} problem(s) in the configuration")
        self.problems = problems


def schema_document() -> dict[str, Any]:
    """Return the JSON Schema of the configuration."""
    return {"$schema": SCHEMA_DIALECT, "$id": SCHEMA_ID, **Configuration.model_json_schema()}


def schema_text() -> str:
    """Return the JSON Schema as committed at ``schemas/config.schema.json``."""
    return json.dumps(schema_document(), indent=2, ensure_ascii=False) + "\n"
