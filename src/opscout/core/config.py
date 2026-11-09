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

from opscout.core.tools import CAP_CEILINGS

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


JOB_NAMES: Final = ("check", "standup")
"""The jobs the engine defines (spec 007); the configuration schedules them."""

KEYCHAIN_ITEMS: Final = ("claude_token", "slack_bot_token", "slack_app_token", "bitbucket_token")
"""The names of the harness's own keychain items: the fallback Claude Code token (spec 007)
the chat app's bot and app-level tokens (spec 008), and the code host's token (spec 009).

Names only; a value never passes through the engine's output (FR-024)."""

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


CHAT_TOKENS: Final = ("slack_bot_token", "slack_app_token")


class ChatSetting(BaseModel):
    """Where deliveries go by direct message (spec 008)."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    service: Literal["slack"] = Field(description="The chat service; only slack.")
    user: Annotated[str, StringConstraints(pattern=r"^[UW][A-Z0-9]{2,20}$")] = Field(
        description="Your Slack member id (in Slack: your profile, then Copy member ID).",
    )


def _daemon_schema(schema: dict[str, Any]) -> None:
    """Make the generated schema refuse chat without both tokens, as the model does."""
    schema["dependentSchemas"] = {
        "chat": {
            "required": ["secrets"],
            "properties": {"secrets": {"required": list(CHAT_TOKENS)}},
        }
    }


class Daemon(BaseModel):
    """Scheduled jobs and what their runs need (specs 007 and 008)."""

    model_config = ConfigDict(
        strict=True, extra="forbid", frozen=True, json_schema_extra=_daemon_schema
    )

    jobs: Annotated[dict[Literal["check", "standup"], JobSettings], Field(max_length=20)] = Field(
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
    secrets: dict[
        Literal["claude_token", "slack_bot_token", "slack_app_token", "bitbucket_token"],
        KeychainRef,
    ] = Field(
        default_factory=dict,
        description=(
            "The harness's own secrets, by name, each a keychain reference: claude_token, "
            "a token from claude setup-token for jobs that cannot use your login; "
            "slack_bot_token and slack_app_token, the chat app's tokens; "
            "bitbucket_token, a read-only Bitbucket API token for the standup."
        ),
    )
    chat: ChatSetting | None = Field(
        default=None,
        description="Deliver by direct message, and record agreement (spec 008).",
    )

    @model_validator(mode="after")
    def _chat_tokens(self) -> "Daemon":
        if self.chat is not None:
            missing = [name for name in CHAT_TOKENS if name not in self.secrets]
            if missing:
                raise PydanticCustomError(
                    "opscout_chat_tokens",
                    "chat needs {missing} in daemon.secrets",
                    {"missing": " and ".join(missing)},
                )
        return self


_ProjectName = Annotated[
    str, StringConstraints(max_length=40, pattern=r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
]
_AbsolutePath = Annotated[
    str, StringConstraints(min_length=2, max_length=1024, pattern=r"^/[^\n]*$")
]
_Repository = Annotated[
    str, StringConstraints(max_length=200, pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
]


def _project_schema(schema: dict[str, Any]) -> None:
    """Make the generated schema refuse a project with neither paths nor repositories."""
    schema["anyOf"] = [
        {"required": ["paths"], "properties": {"paths": {"minItems": 1}}},
        {"required": ["repositories"], "properties": {"repositories": {"minItems": 1}}},
    ]


class StandupProject(BaseModel):
    """A project the standup groups by: its local clones and code-host repositories."""

    model_config = ConfigDict(
        strict=True, extra="forbid", frozen=True, json_schema_extra=_project_schema
    )

    paths: Annotated[list[_AbsolutePath], Field(max_length=10)] = Field(
        default_factory=list,
        description="Absolute paths of the local clones; sessions in them belong here.",
    )
    repositories: Annotated[list[_Repository], Field(max_length=10)] = Field(
        default_factory=list, description="Code-host repositories, as workspace/slug."
    )

    @model_validator(mode="after")
    def _something(self) -> "StandupProject":
        if not self.paths and not self.repositories:
            raise PydanticCustomError("opscout_project", "give paths, repositories or both")
        return self


class CodeHost(BaseModel):
    """Where the user's pull requests are (spec 009)."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    service: Literal["bitbucket"] = Field(description="The code host; only bitbucket.")
    login: Annotated[str, StringConstraints(min_length=1, max_length=200, pattern=r"^\S+$")] = (
        Field(description="The account the token belongs to: its e-mail or username.")
    )


class StandupLimits(BaseModel):
    """How much of each source the standup keeps (research R5)."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    prompt_length: Annotated[int, Field(ge=80, le=1000)] = Field(
        default=300, description="The longest a prompt is kept, in characters."
    )
    prompts_per_session: Annotated[int, Field(ge=2, le=100)] = Field(
        default=20, description="The most prompts kept per session (first and last halves)."
    )
    prompts: Annotated[int, Field(ge=10, le=300)] = Field(
        default=60, description="The most prompts kept in all."
    )
    commits: Annotated[int, Field(ge=10, le=200)] = Field(
        default=40, description="The most commits kept."
    )
    pull_requests: Annotated[int, Field(ge=5, le=100)] = Field(
        default=30, description="The most pull request facts kept."
    )


_Term = Annotated[str, StringConstraints(min_length=2, max_length=100, pattern=_OneLine)]


def _standup_schema(schema: dict[str, Any]) -> None:
    """Make the generated schema refuse a section with neither folders nor projects."""
    schema["anyOf"] = [
        {"required": ["folders"], "properties": {"folders": {"minItems": 1}}},
        {"required": ["projects"], "properties": {"projects": {"minProperties": 1}}},
    ]


class Standup(BaseModel):
    """The daily standup's sources and projects (spec 009)."""

    model_config = ConfigDict(
        strict=True, extra="forbid", frozen=True, json_schema_extra=_standup_schema
    )

    identities: Annotated[
        list[Annotated[str, StringConstraints(min_length=1, max_length=200, pattern=_OneLine)]],
        Field(min_length=1, max_length=10),
    ] = Field(description="Your commit identities: author e-mails or names.")
    code_host: CodeHost | None = Field(
        default=None, description="Where your pull requests are; without it, none are read."
    )
    folders: Annotated[list[_AbsolutePath], Field(max_length=10)] = Field(
        default_factory=list,
        description=(
            "Folders whose git repositories are your projects, each named after its "
            "directory, with its Bitbucket repository from its origin remote."
        ),
    )
    projects: Annotated[dict[_ProjectName, StandupProject], Field(max_length=30)] = Field(
        default_factory=dict,
        description=(
            "Projects listed by hand, to group repositories or adjust one found in a folder."
        ),
        json_schema_extra={"additionalProperties": False},
    )
    redact: Annotated[list[_Term], Field(max_length=100)] = Field(
        default_factory=list,
        description="Terms never sent to the model, whatever their case: names, codes.",
    )
    limits: StandupLimits = Field(
        default_factory=StandupLimits, description="How much of each source is kept."
    )

    @model_validator(mode="after")
    def _somewhere(self) -> "Standup":
        if not self.folders and not self.projects:
            raise PydanticCustomError("opscout_standup", "give folders, projects or both")
        return self


ALERT_FIELDS: Final = (
    "severity",
    "title",
    "project",
    "environment",
    "resource",
    "account",
    "region",
    "metric",
    "threshold",
    "value",
    "time",
)
"""The fields an alert format may extract (spec 011, FR-014)."""
AlertField = Literal[
    "severity",
    "title",
    "project",
    "environment",
    "resource",
    "account",
    "region",
    "metric",
    "threshold",
    "value",
    "time",
]


def _compiles(value: str) -> str:
    """Refuse an expression Python cannot compile."""
    try:
        re.compile(value, re.MULTILINE)
    except re.error:
        raise PydanticCustomError("opscout_regex", "not a valid regular expression") from None
    return value


def _one_group(value: str) -> str:
    """Refuse a field expression without exactly one capture group."""
    if re.compile(value, re.MULTILINE).groups != 1:
        raise PydanticCustomError("opscout_regex", "needs exactly one capture group")
    return value


_Regex = Annotated[str, StringConstraints(min_length=1, max_length=500), AfterValidator(_compiles)]
_FieldRegex = Annotated[_Regex, AfterValidator(_one_group)]


class AlertFormat(BaseModel):
    """How to recognize one kind of alert text and extract its fields (spec 011)."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    name: Annotated[
        str, StringConstraints(min_length=1, max_length=64, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    ] = Field(description="The format's name, as the tools report it.")
    recognize: _Regex = Field(
        description="A regular expression that matches alerts in this format (multi-line)."
    )
    fields: Annotated[dict[AlertField, _FieldRegex], Field(min_length=1)] = Field(
        description=(
            "Each field to extract, with a regular expression that has exactly one capture "
            "group (multi-line)."
        ),
    )


class Alerts(BaseModel):
    """The alert formats the alert tools recognize, in order of precedence (spec 011)."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    formats: Annotated[list[AlertFormat], Field(min_length=1, max_length=50)] = Field(
        description="The formats, tried in this order; the first that matches wins."
    )

    @model_validator(mode="after")
    def _unique_formats(self) -> "Alerts":
        names = [entry.name for entry in self.formats]
        for name in names:
            if names.count(name) > 1:
                raise PydanticCustomError("opscout_alerts", "two formats share a name")
        return self


_Region = Annotated[str, StringConstraints(pattern=r"^[a-z]{2}(-[a-z]+)+-[0-9]$")]


def _unique_regions(regions: list[str]) -> list[str]:
    if len(set(regions)) != len(regions):
        raise PydanticCustomError("opscout_regions", "each region may be listed only once")
    return regions


class AwsEnvironment(BaseModel):
    """One AWS account in scope, and how the tools reach it (spec 011, FR-015)."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    name: Annotated[
        str, StringConstraints(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    ] = Field(description="The environment's name, as tools and alerts refer to it.")
    account_id: Annotated[str, StringConstraints(pattern=r"^[0-9]{12}$")] = Field(
        description="The AWS account ID, as a quoted 12-digit string."
    )
    profile: Annotated[
        str, StringConstraints(min_length=1, max_length=128, pattern=r"^[^\s\x00-\x1f\x7f]+$")
    ] = Field(description="The AWS profile, from your AWS config, that reaches this account.")
    regions: Annotated[
        list[_Region], Field(min_length=1, max_length=10), AfterValidator(_unique_regions)
    ] = Field(description="The regions in scope; the first is the default.")
    aliases: Annotated[
        list[Annotated[str, StringConstraints(min_length=1, max_length=64, pattern=_OneLine)]],
        Field(max_length=20),
    ] = Field(
        default_factory=list,
        description="Other names alerts use for this environment, such as a project name.",
    )
    identity: Literal["reference", "own"] = Field(
        default="own",
        description=(
            "reference when the profile uses opscout's reference read-only identity (spec "
            "010); own otherwise. Results state it; nothing checks or requires it (ADR-0023)."
        ),
    )


class Aws(BaseModel):
    """The AWS environments the tools may read (spec 011, FR-015)."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    environments: Annotated[list[AwsEnvironment], Field(min_length=1, max_length=50)] = Field(
        description="The environments in scope, one AWS account each."
    )

    @model_validator(mode="after")
    def _unique_environments(self) -> "Aws":
        seen: dict[str, str] = {}
        accounts: set[str] = set()
        for environment in self.environments:
            if environment.name.casefold() in seen:
                raise PydanticCustomError("opscout_aws", "two environments share a name")
            if environment.account_id in accounts:
                raise PydanticCustomError("opscout_aws", "two environments share an account ID")
            seen[environment.name.casefold()] = environment.name
            accounts.add(environment.account_id)
        for environment in self.environments:
            for alias in environment.aliases:
                owner = seen.get(alias.casefold())
                if owner is not None and owner != environment.name:
                    raise PydanticCustomError(
                        "opscout_aws",
                        "an alias is already the name or an alias of another environment",
                    )
                seen[alias.casefold()] = environment.name
        return self


class ToolRedaction(BaseModel):
    """Which operational values the tools redact; secrets are always redacted (FR-010)."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    account_ids: bool = Field(default=False, description="Redact AWS account IDs.")
    ips: bool = Field(default=False, description="Redact IP addresses.")
    emails: bool = Field(default=False, description="Redact e-mail addresses.")


_CAP_NAMES: Final = ", ".join(CAP_CEILINGS)


def _known_caps(caps: dict[str, int]) -> dict[str, int]:
    """Refuse an unknown cap or one above its ceiling (FR-011)."""
    for name, value in caps.items():
        if name not in CAP_CEILINGS:
            raise PydanticCustomError(
                "opscout_caps", "unknown cap; the caps are {names}", {"names": _CAP_NAMES}
            )
        if not 1 <= value <= CAP_CEILINGS[name]:
            raise PydanticCustomError(
                "opscout_caps",
                "expected at least 1 and at most {ceiling}",
                {"ceiling": CAP_CEILINGS[name]},
            )
    return caps


CAP_DESCRIPTIONS: Final[Mapping[str, str]] = {
    "result_chars": "The most characters in one tool result.",
    "metric_window_hours": "The longest window, in hours, for alarms and metrics.",
    "log_window_hours": "The longest window, in hours, for a log query.",
    "change_window_hours": "The longest window, in hours, for recent changes.",
    "log_rows": "The most rows a log query returns.",
    "log_wait_seconds": "The longest a log query is waited for, in seconds.",
    "change_items": "The most changes returned per source.",
    "stacks": "The most CloudFormation stacks examined for events.",
    "resources": "The most resources a search returns.",
    "datapoints": "The most metric data points returned.",
}


def _caps_schema() -> dict[str, Any]:
    return {
        "additionalProperties": False,
        "properties": {
            name: {
                "type": "integer",
                "minimum": 1,
                "maximum": ceiling,
                "description": f"{CAP_DESCRIPTIONS[name]} At most {ceiling}.",
            }
            for name, ceiling in CAP_CEILINGS.items()
        },
    }


class Tools(BaseModel):
    """How the tool server shapes its results (spec 011)."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    timezone: _TimeZone | None = Field(
        default=None,
        description=(
            "The IANA time zone results are written in; without it, personal_context's, then UTC."
        ),
    )
    redact: ToolRedaction = Field(
        default_factory=ToolRedaction,
        description="Which operational values to redact; secrets are always redacted.",
    )
    caps: Annotated[dict[str, int], AfterValidator(_known_caps)] = Field(
        default_factory=dict,
        description="Lower limits for the tools' caps; none may exceed its ceiling.",
        json_schema_extra=_caps_schema(),
    )


_CloneName = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,39}$")]
_EnvironmentName = Annotated[
    str, StringConstraints(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
]
_CloudTrailAction = Annotated[str, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9]{0,127}$")]


class InfrastructureClone(BaseModel):
    """A local clone of infrastructure code that triage reads (spec 012, FR-012)."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    name: _CloneName = Field(description="How citations and read_iac name this clone.")
    path: _AbsolutePath = Field(description="The clone's absolute path; it is only read.")
    environments: Annotated[list[_EnvironmentName], Field(min_length=1, max_length=50)] | None = (
        Field(
            default=None,
            description="The environments this clone declares; absent means every environment.",
        )
    )


class Triage(BaseModel):
    """Alert triage's settings (spec 012)."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    infrastructure: Annotated[list[InfrastructureClone], Field(max_length=20)] = Field(
        default_factory=list,
        description="Local clones of infrastructure code, read only by the triage tools.",
    )
    observability: bool = Field(
        default=False,
        description=(
            "True when a read-only observability server is registered in Claude Code under "
            "the name `observability`; its evidence is marked not checked."
        ),
    )
    skeptic: bool = Field(
        default=False, description="Run the skeptic pass after a verdict passes its check."
    )
    metric_history_days: Annotated[int, Field(ge=1, le=14)] = Field(
        default=7, description="Days of metric history for the threshold assessment."
    )
    background_actions: Annotated[list[_CloudTrailAction], Field(max_length=50)] = Field(
        default_factory=list,
        description="More CloudTrail actions to drop from recent changes as background.",
    )

    @model_validator(mode="after")
    def _unique_clones(self) -> "Triage":
        names = [clone.name for clone in self.infrastructure]
        if len(set(names)) != len(names):
            raise PydanticCustomError("opscout_triage", "two clones share a name")
        return self


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
    standup: Standup | None = Field(
        default=None, description="The daily standup's sources and projects (spec 009)."
    )
    alerts: Alerts | None = Field(
        default=None, description="The alert formats the alert tools recognize (spec 011)."
    )
    aws: Aws | None = Field(
        default=None, description="The AWS environments the tools may read (spec 011)."
    )
    tools: Tools = Field(
        default_factory=Tools,
        description="Timezone, redaction and caps for the tool server's results (spec 011).",
    )
    triage: Triage | None = Field(
        default=None,
        description="Alert triage: infrastructure clones, observability, the skeptic pass "
        "(spec 012).",
    )

    @model_validator(mode="after")
    def _triage_environments(self) -> "Configuration":
        if self.triage is None:
            return self
        known = {e.name for e in self.aws.environments} if self.aws else set()
        for clone in self.triage.infrastructure:
            if any(name not in known for name in clone.environments or ()):
                raise PydanticCustomError(
                    "opscout_triage",
                    "a clone in triage.infrastructure lists an environment that "
                    "is not a configured environment",
                )
        return self

    @model_validator(mode="after")
    def _standup_needs(self) -> "Configuration":
        if "standup" in self.daemon.jobs and self.standup is None:
            raise PydanticCustomError(
                "opscout_standup", "the standup job needs the standup section"
            )
        if self.standup and self.standup.code_host and "bitbucket_token" not in self.daemon.secrets:
            raise PydanticCustomError(
                "opscout_standup", "a code host needs bitbucket_token in daemon.secrets"
            )
        return self


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
