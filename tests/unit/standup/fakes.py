# SPDX-License-Identifier: Apache-2.0
"""In-memory fakes of the standup's three ports (spec 009)."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from opscout.core.config import Standup, StandupProject
from opscout.core.standup import (
    Commit,
    PullRequest,
    Repository,
    RepositoryError,
    SessionPrompts,
    SourceError,
    TranscriptScan,
    Window,
)

ZONE = timezone(timedelta(hours=-6))
API = "/opt/example/src/example-api"
WEB = "/opt/example/src/example-web"
STANDUP = Standup(
    identities=["dev@example.com"],
    projects={
        "example-api": StandupProject(paths=[API], repositories=["example-workspace/example-api"]),
        "example-web": StandupProject(paths=[WEB]),
    },
    redact=["Example Corp"],
)


def at(day: int, hour: int, minute: int = 0) -> datetime:
    """Return a local time in November 2026 (5 is a Thursday)."""
    return datetime(2026, 11, day, hour, minute, tzinfo=ZONE)


@dataclass
class FakeTranscripts:
    sessions: list[SessionPrompts] = field(default_factory=list)
    unreadable: int = 0
    error: str | None = None
    roots: list[Sequence[Path]] = field(default_factory=list)

    def scan(self, window: Window, roots: Sequence[Path]) -> TranscriptScan:
        self.roots.append(roots)
        if self.error:
            raise SourceError(self.error)
        chosen = tuple(
            session
            for session in self.sessions
            if any(Path(session.cwd).is_relative_to(root) for root in roots)
        )
        return TranscriptScan(chosen, self.unreadable)


@dataclass
class FakeCommits:
    by_path: dict[str, list[Commit]] = field(default_factory=dict)
    failing: set[str] = field(default_factory=set)

    found: dict[str, list[Repository]] = field(default_factory=dict)

    def commits(self, path: Path, identities: Sequence[str], window: Window) -> list[Commit]:
        if str(path) in self.failing:
            raise SourceError(f"{path}: not a git repository")
        return list(self.by_path.get(str(path), []))

    def repositories(self, folder: Path) -> list[Repository]:
        if str(folder) in self.failing:
            raise SourceError(f"{folder}: no such folder")
        return list(self.found.get(str(folder), []))


@dataclass
class FakeCodeHost:
    closed_prs: dict[str, list[PullRequest]] = field(default_factory=dict)
    open_prs: dict[str, list[PullRequest]] = field(default_factory=dict)
    reviews: dict[str, list[PullRequest]] = field(default_factory=dict)
    error: str | None = None
    calls: list[str] = field(default_factory=list)
    token: Callable[[], str] | None = None
    gone: set[str] = field(default_factory=set)

    def _check(self, what: str) -> None:
        self.calls.append(what)
        if self.token is not None:
            self.token()  # as the real adapter does, on each request
        if self.error:
            raise SourceError(self.error)
        if what.split()[-1] in self.gone:
            raise RepositoryError("not found, or the token has no access (404)")

    def closed(self, repository: str, window: Window) -> list[PullRequest]:
        self._check(f"closed {repository}")
        return list(self.closed_prs.get(repository, []))

    def open(self, repository: str) -> list[PullRequest]:
        self._check(f"open {repository}")
        return list(self.open_prs.get(repository, []))

    def reviews_waiting(self, repository: str) -> list[PullRequest]:
        self._check(f"reviews {repository}")
        return list(self.reviews.get(repository, []))
