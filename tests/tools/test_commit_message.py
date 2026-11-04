# SPDX-License-Identifier: Apache-2.0
"""Commit messages follow Conventional Commits 1.0 (ADR-0016)."""

import shutil
import subprocess
from pathlib import Path

import pytest

from tools.commit_message import main, problems


@pytest.mark.parametrize(
    "message",
    [
        "feat: add the alert triage skill",
        "fix(cli)!: rename the config flag\n\nBREAKING CHANGE: --config replaces --cfg.\n",
        "build(deps): bump ruff from 0.17.3 to 0.17.4",
        "chore: add the harness\n\nPhase 0a step 7.\n\nAssisted-by: Claude Opus 5.5\n",
        "docs: explain the leak check\n# Lines starting with '#' are git's comments.\n",
        "fixup! feat: add the alert triage skill",
        'Revert "feat: add the alert triage skill"',
    ],
)
def test_conventional_messages_pass(message: str) -> None:
    assert problems(message) == []


@pytest.mark.parametrize(
    ("message", "fragment"),
    [
        ("Add the alert triage skill", "type"),
        ("feature: add the alert triage skill", "type"),
        ("Feat: add the alert triage skill", "type"),
        ("feat:add the alert triage skill", "type"),
        ("feat: ", "type"),
        ("", "type"),
        ("feat: add the skill\nThe body starts on the next line.", "blank line"),
    ],
)
def test_other_messages_are_rejected(message: str, fragment: str) -> None:
    assert any(fragment in problem for problem in problems(message))


def test_the_hook_reads_the_message_file(tmp_path: Path) -> None:
    good = tmp_path / "good"
    good.write_text("test: cover the hook\n", encoding="utf-8")
    bad = tmp_path / "bad"
    bad.write_text("cover the hook\n", encoding="utf-8")

    assert main([str(good)]) == 0
    assert main([str(bad)]) == 1


def test_range_mode_checks_every_commit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    git = shutil.which("git")
    assert git is not None
    identity = ["-c", "user.name=Someone", "-c", "user.email=someone@example.com"]
    unsigned = ["-c", "commit.gpgsign=false"]
    for arguments in (
        ["init", "-q"],
        [*identity, *unsigned, "commit", "-q", "--allow-empty", "-m", "chore: start"],
        [*identity, *unsigned, "commit", "-q", "--allow-empty", "-m", "Tweak things"],
    ):
        subprocess.run([git, *arguments], cwd=tmp_path, check=True)  # noqa: S603  # fixed program
    monkeypatch.chdir(tmp_path)

    assert main(["--range", "HEAD~1"]) == 0
    assert main(["--range", "HEAD"]) == 1
