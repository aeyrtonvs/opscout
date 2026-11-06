# SPDX-License-Identifier: Apache-2.0
"""The user's commits from a local clone, read-only (spec 009, FR-005, FR-014)."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from opscout.adapters.git_log import GitLog, arguments
from opscout.core.standup import SourceError
from opscout.services.standup import window_for
from tests.unit.standup.fakes import at

WINDOW = window_for(at(5, 9, 45), ["mon", "tue", "wed", "thu", "fri"])  # Wednesday 4
GIT = shutil.which("git")


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 009."""
    return pytest.mark.spec("009", requirement)


def git(repo: Path, *args: str, author: str = "dev@example.com", when: str = "") -> None:
    env = {
        **{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
        "GIT_AUTHOR_NAME": "Example", "GIT_AUTHOR_EMAIL": author,
        "GIT_COMMITTER_NAME": "Example", "GIT_COMMITTER_EMAIL": author,
        "GIT_CONFIG_NOSYSTEM": "1", "HOME": str(repo.parent),
    }  # fmt: skip
    if when:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = when
    assert GIT is not None
    subprocess.run([GIT, "-C", str(repo), *args], env=env, check=True, capture_output=True)  # noqa: S603


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "example-api"
    path.mkdir()
    git(path, "init", "-q", "-b", "main")
    git(
        path,
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "Before the window",
        when="2026-11-03T12:00:00-06:00",
    )
    git(
        path,
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "Retry export job on 5xx",
        when="2026-11-04T10:00:00-06:00",
    )
    git(path, "checkout", "-q", "-b", "feature/web")
    git(
        path,
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "Teammate work",
        author="other@example.com",
        when="2026-11-04T11:00:00-06:00",
    )
    git(
        path,
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "Login form tweaks",
        when="2026-11-04T12:00:00-06:00",
    )
    git(path, "checkout", "-q", "main")
    git(
        path,
        "merge",
        "-q",
        "--no-ff",
        "-m",
        "Merge feature/web",
        "feature/web",
        when="2026-11-04T13:00:00-06:00",
    )
    git(path, "commit", "-q", "--allow-empty", "-m", "Today", when="2026-11-05T08:00:00-06:00")
    return path


@pytest.mark.skipif(GIT is None, reason="needs git")
@spec("FR-005")
def test_the_user_s_commits_in_the_window_once_each(repo: Path) -> None:
    commits = GitLog().commits(repo, ["dev@example.com"], WINDOW)
    assert sorted(c.subject for c in commits) == ["Login form tweaks", "Retry export job on 5xx"]
    assert len({c.sha for c in commits}) == 2
    tweaks = next(c for c in commits if c.subject == "Login form tweaks")
    assert "feature/web" in tweaks.ref or "main" in tweaks.ref
    assert tweaks.at == at(4, 12)


@spec("FR-014")
def test_only_read_only_arguments() -> None:
    args = arguments(Path("/opt/example/src/example-api"), ["dev@example.com", "Example"], WINDOW)
    assert args[:3] == ["-C", "/opt/example/src/example-api", "log"]
    assert {"--all", "--source", "--no-merges", "--no-color"} <= set(args)
    assert args.count("--author=dev@example.com") == 1
    assert "--author=Example" in args
    assert f"--since={WINDOW.start.isoformat()}" in args
    assert f"--until={WINDOW.end.isoformat()}" in args
    writes = {"commit", "push", "fetch", "pull", "reset", "checkout", "merge", "rebase", "gc"}
    assert writes.isdisjoint(args)


@pytest.mark.skipif(GIT is None, reason="needs git")
@spec("FR-008")
def test_a_path_that_is_not_a_repository_is_a_source_error(tmp_path: Path) -> None:
    with pytest.raises(SourceError, match="not a git repository"):
        GitLog().commits(tmp_path, ["dev@example.com"], WINDOW)


@spec("FR-008")
def test_a_line_git_gives_in_another_shape_is_skipped(tmp_path: Path) -> None:
    import stat
    import sys

    good = "\x1f".join(["a" * 40, "2026-11-04T11:00:00-06:00", "refs/heads/main", "Fix"])
    odd = "\x1f".join(["b" * 40, "yesterday", "refs/heads/main", "Odd"])
    naive = "\x1f".join(["c" * 40, "2026-11-04T11:00:00", "refs/heads/main", "Naive"])
    program = tmp_path / "git"
    program.write_text(
        f"#!{sys.executable}\nprint({odd!r})\nprint({naive!r})\nprint({good!r})\n", encoding="utf-8"
    )
    program.chmod(program.stat().st_mode | stat.S_IXUSR)
    commits = GitLog(str(program)).commits(tmp_path, ["dev@example.com"], WINDOW)
    assert [c.subject for c in commits] == ["Fix"]
