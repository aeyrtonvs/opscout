# SPDX-License-Identifier: Apache-2.0
"""The daily standup: the window, the facts, the model's output and the ports (spec 009).

Nothing here does I/O. The ports read the three sources; ``services.standup`` turns what
they return into numbered, minimized, redacted facts, and checks the model's output
against them.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, model_validator

Source = Literal["sessions", "git", "bitbucket"]


@dataclass(frozen=True)
class Window:
    """The covered days, from the previous working day to the start of today (FR-003)."""

    start: datetime
    end: datetime
    now: datetime
    days: tuple[date, ...]


@dataclass(frozen=True)
class SessionPrompts:
    """One Claude Code session's prompts in the window: the user's own only (FR-004)."""

    session: str
    cwd: str
    prompts: tuple[tuple[datetime, str], ...]


@dataclass(frozen=True)
class TranscriptScan:
    """What the transcripts gave: the sessions, and how many lines could not be read."""

    sessions: tuple[SessionPrompts, ...]
    unreadable: int = 0


@dataclass(frozen=True)
class Commit:
    """One commit of the user in a local clone (FR-005)."""

    sha: str
    at: datetime
    ref: str
    subject: str


@dataclass(frozen=True)
class Participant:
    """Someone on a pull request, with their review state (research R3)."""

    user: str
    role: str
    approved: bool
    state: str | None
    at: datetime | None


@dataclass(frozen=True)
class PullRequest:
    """A pull request, as the code host reports it (FR-006)."""

    repository: str
    number: int
    title: str
    state: str
    created: datetime
    updated: datetime
    branch: str
    participants: tuple[Participant, ...] = ()
    user_activity: tuple[datetime, ...] = ()
    """When the user pushed or commented, for a pull request with changes requested."""


@dataclass(frozen=True)
class Repository:
    """A git repository found in a folder, with its Bitbucket repository if any (FR-023)."""

    path: str
    bitbucket: str | None
    main: str | None = None
    """For a worktree, its main repository: the project it belongs to."""


@dataclass(frozen=True)
class Project:
    """A project as the gathering sees it: listed by hand or found in folders (FR-023)."""

    paths: tuple[str, ...] = ()
    repositories: tuple[str, ...] = ()


class SourceError(Exception):
    """A source cannot be read; the message says why, never with a token (FR-008)."""


class RepositoryError(SourceError):
    """One repository cannot be read, but the rest of its source can (FR-008)."""


class Transcripts(Protocol):
    """The user's Claude Code sessions."""

    def scan(self, window: Window, roots: Sequence[Path]) -> TranscriptScan:
        """Return the prompts of sessions under ``roots`` in the window. Raises SourceError."""
        ...


class Commits(Protocol):
    """The user's commits in a local clone."""

    def commits(self, path: Path, identities: Sequence[str], window: Window) -> list[Commit]:
        """Return the user's commits in the window, once each. Raises SourceError."""
        ...

    def repositories(self, folder: Path) -> list[Repository]:
        """Return the git repositories inside a folder (FR-023). Raises SourceError."""
        ...


class CodeHost(Protocol):
    """The user's pull requests on the code host."""

    def closed(self, repository: str, window: Window) -> list[PullRequest]:
        """Return the user's pull requests merged or declined in the window."""
        ...

    def open(self, repository: str) -> list[PullRequest]:
        """Return all the user's open pull requests, whatever their age."""
        ...

    def reviews_waiting(self, repository: str) -> list[PullRequest]:
        """Return the open pull requests waiting on the user's review."""
        ...


Kind = Literal["done", "open", "blocker"]


@dataclass(frozen=True)
class Fact:
    """One gathered item, minimized and redacted, with its identifier (FR-007)."""

    id: str
    source: Source
    project: str
    at: datetime
    text: str
    kind: Kind = "done"

    def line(self) -> str:
        """Return the fact as the model and the preview get it."""
        mark = {"done": "", "open": " (open)", "blocker": " (blocker)"}[self.kind]
        return (
            f"[{self.id}] {self.project} {self.at:%Y-%m-%d %H:%M} {self.source}{mark}: {self.text}"
        )


@dataclass(frozen=True)
class Gathered:
    """Everything the window gave, and what was cut, redacted or missing (FR-013)."""

    window: Window
    facts: tuple[Fact, ...]
    cut: Mapping[str, int] = field(default_factory=lambda: MappingProxyType({}))
    redactions: Mapping[str, int] = field(default_factory=lambda: MappingProxyType({}))
    missing: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    unreadable: int = 0
    projects: tuple[str, ...] = ()
    """The projects the window was gathered for: listed and found in folders."""

    def inputs(self) -> tuple[str, ...]:
        """Return the record's references: counts, ids, cuts, redactions; never text."""
        counts = dict.fromkeys(("sessions", "git", "bitbucket"), 0)
        for fact in self.facts:
            counts[fact.source] += 1
        references = [f"{source}:{count}" for source, count in counts.items()]
        references.append("facts:" + ",".join(fact.id for fact in self.facts))
        references += [f"cut:{kind}={n}" for kind, n in sorted(self.cut.items()) if n]
        references += [f"redacted:{kind}={n}" for kind, n in sorted(self.redactions.items()) if n]
        references += [f"missing:{source}" for source in sorted(self.missing)]
        if self.unreadable:
            references.append(f"unreadable:{self.unreadable}")
        return tuple(references)


class Line(BaseModel):
    """One line of the summary, citing the facts it rests on."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str = Field(min_length=1, max_length=200, description="One short, plain line.")
    facts: list[str] = Field(
        min_length=1, max_length=20, description="The ids of the facts this line rests on."
    )


class ProjectLine(Line):
    """A line of yesterday's work, under its project."""

    project: str = Field(
        max_length=100,
        pattern=r"^[a-z0-9][a-z0-9-]*$",
        description="The project, as the facts name it.",
    )


class StandupOutput(BaseModel):
    """The model's summary; checked against the run's facts (FR-011, research R7).

    Given the facts as validation context, it refuses an unknown fact, a project that is
    not configured or has no facts, a non-blocker under blockers, a blocker left out, and a
    yesterday of the wrong length; spec 007's runner then retries once with the message.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    yesterday: list[ProjectLine] = Field(
        max_length=8, description="What was done, grouped by project, 3 to 6 lines."
    )
    today: list[Line] = Field(max_length=8, description="The open work.")
    blockers: list[Line] = Field(
        max_length=10, description="Exactly the facts marked (blocker), each cited."
    )
    note: str | None = Field(default=None, max_length=200, description="Anything else, short.")

    @model_validator(mode="after")
    def _against_facts(self, info: ValidationInfo) -> "StandupOutput":
        context = info.context
        if not context or "facts" not in context:
            return self
        facts: Mapping[str, Mapping[str, str]] = context["facts"]
        configured = set(context.get("projects", ()))
        with_facts = {fact["project"] for fact in facts.values()}
        problems: list[str] = []
        lines: list[Line] = [*self.yesterday, *self.today, *self.blockers]
        for line in lines:
            problems += [f"unknown fact {fact}" for fact in line.facts if fact not in facts]
        for line in self.yesterday:
            problems += [
                f"{fact} is not in {line.project}"
                for fact in line.facts
                if fact in facts and facts[fact]["project"] != line.project
            ]
            if line.project not in configured:
                problems.append(f"{line.project} is not a configured project")
            elif line.project not in with_facts:
                problems.append(f"{line.project} has no facts")
        blockers = {id_ for id_, fact in facts.items() if fact["kind"] == "blocker"}
        cited = {fact for line in self.blockers for fact in line.facts}
        problems += [
            f"{fact} is not a blocker" for fact in sorted(cited - blockers) if fact in facts
        ]
        problems += [f"blocker {fact} is left out" for fact in sorted(blockers - cited)]
        done = sum(1 for fact in facts.values() if fact["kind"] == "done")
        if done >= 3 and not 3 <= len(self.yesterday) <= 6:
            problems.append("write 3 to 6 yesterday lines")
        elif done and not 1 <= len(self.yesterday) <= 6:
            problems.append("write 1 to 6 yesterday lines")
        if problems:
            raise ValueError("; ".join(problems))
        return self
