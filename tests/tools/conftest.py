# SPDX-License-Identifier: Apache-2.0
"""Fixtures shared by the tests of this repository's tooling."""

import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def clean_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Run as on a clean laptop, even when a git hook or CI runs the tests.

    During ``git commit -a`` git exports ``GIT_INDEX_FILE`` and similar variables to its
    hooks, and a test that runs git in a scratch repository would then write to this
    repository's index. The user's git configuration stays out too: global and system
    settings, and this clone's own (such as ``opscout.requireDenylist``), because each test
    starts in an empty directory outside any repository. ``CI``, which turns on redaction in
    the leak check, is cleared as well.
    """
    for name in list(os.environ):
        if name.startswith("GIT_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.delenv("CI", raising=False)
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    monkeypatch.chdir(workdir)


@pytest.fixture
def git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[..., str]:
    """Run git in a new scratch repository, which becomes the working directory."""
    executable = shutil.which("git")
    assert executable is not None
    repo = tmp_path / "repo"
    repo.mkdir()

    def run(*arguments: str) -> str:
        return subprocess.run(  # noqa: S603  # fixed program; arguments come from the tests
            [executable, *arguments],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout

    run("init", "-q")
    run("config", "user.name", "Someone")
    run("config", "user.email", "someone@users.noreply.github.com")
    run("config", "commit.gpgsign", "false")
    monkeypatch.chdir(repo)
    return run
