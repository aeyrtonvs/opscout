# SPDX-License-Identifier: Apache-2.0
"""GitLog: the user's commits in a local clone, through one read-only ``git log``.

Subjects only, never bodies or diffs; each commit once, whatever branches reach it
(spec 009, research R2).
"""

import os
import re
import shutil
import subprocess
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from opscout.core.standup import Commit, Repository, SourceError, Window

_SEPARATOR = "\x1f"
_BITBUCKET = re.compile(r"bitbucket\.org[:/]([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")
_SKIP = frozenset({"node_modules", "vendor"})
DEPTH = 3


def arguments(path: Path, identities: Sequence[str], window: Window) -> list[str]:
    """Return the read-only arguments of the ``git log`` call."""
    return [
        "-C", str(path), "log", "--all", "--source", "--no-merges", "--no-color",
        *(f"--author={identity}" for identity in identities),
        f"--since={window.start.isoformat()}", f"--until={window.end.isoformat()}",
        f"--format=%H{_SEPARATOR}%aI{_SEPARATOR}%S{_SEPARATOR}%s",
    ]  # fmt: skip


def _environment() -> dict[str, str]:
    """The environment for git: none of git's own variables, which a git hook would set."""
    return {
        **{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_PAGER": "cat",
        "GIT_TERMINAL_PROMPT": "0",
    }


class GitLog:
    """The ``Commits`` port on the git command."""

    def __init__(self, program: str | None = None) -> None:
        self._program = program

    def commits(self, path: Path, identities: Sequence[str], window: Window) -> list[Commit]:
        """Return the user's commits in the window. Raises ``SourceError``."""
        program = self._program or shutil.which("git")
        if program is None:
            raise SourceError("git is not on PATH")
        environment = _environment()
        try:
            result = subprocess.run(  # noqa: S603  (a fixed, read-only git command)
                [program, *arguments(path, identities, window)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise SourceError(f"{path}: git could not run ({type(error).__name__})") from None
        if result.returncode != 0:
            raise SourceError(f"{path}: not a git repository, or git failed")
        seen: dict[str, Commit] = {}
        for line in result.stdout.splitlines():
            parts = line.split(_SEPARATOR)
            if len(parts) != 4 or parts[0] in seen:
                continue
            sha, when, ref, subject = parts
            try:
                moment = datetime.fromisoformat(when)
            except ValueError:
                continue  # not the shape asked for: skipped, never guessed
            if moment.tzinfo is None:
                continue
            seen[sha] = Commit(sha, moment, ref, subject)
        return list(seen.values())

    def repositories(self, folder: Path) -> list[Repository]:
        """Return the git repositories inside a folder, at most three levels down (FR-023)."""
        if not folder.is_dir():
            raise SourceError(f"{folder}: no such folder")
        found: list[Repository] = []
        self._walk(folder, 0, found)
        return found

    def _walk(self, directory: Path, depth: int, found: list[Repository]) -> None:
        try:
            children = sorted(child for child in directory.iterdir() if child.is_dir())
        except OSError:
            return
        for child in children:
            if child.name.startswith(".") or child.name in _SKIP:
                continue
            marker = child / ".git"
            if marker.is_dir():
                found.append(Repository(str(child), self._bitbucket(child)))
            elif marker.is_file():  # a worktree: it belongs to its main repository
                found.append(Repository(str(child), self._bitbucket(child), self._main(child)))
            elif depth + 1 < DEPTH:
                self._walk(child, depth + 1, found)

    def _main(self, path: Path) -> str | None:
        """Return a worktree's main repository, from git's common directory."""
        output = self._git(path, "rev-parse", "--path-format=absolute", "--git-common-dir")
        return str(Path(output).parent) if output else None

    def _git(self, path: Path, *args: str) -> str | None:
        program = self._program or shutil.which("git")
        if program is None:
            return None
        result = subprocess.run(  # noqa: S603  (a fixed, read-only git command)
            [program, "-C", str(path), *args],
            capture_output=True, text=True, timeout=20, check=False, env=_environment(),
        )  # fmt: skip
        return result.stdout.strip() if result.returncode == 0 else None

    def _bitbucket(self, path: Path) -> str | None:
        url = self._git(path, "remote", "get-url", "origin")
        match = _BITBUCKET.search(url) if url else None
        return f"{match.group(1)}/{match.group(2)}" if match else None
