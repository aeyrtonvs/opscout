# SPDX-License-Identifier: Apache-2.0
"""Run git, list the commits of a range, and read commit messages as git keeps them."""

import shutil
import subprocess
from collections.abc import Mapping, Sequence

NULL_SHA = "0" * 40  # what GitHub sends as the "before" commit of a new branch
# git drops this line and everything below it, such as the diff that `commit -v` shows.
SCISSORS = "# ------------------------ >8 ------------------------"
# Settings that would change git's output from what the checks parse.
STABLE_OUTPUT = ("-c", "log.showSignature=false", "-c", "core.quotePath=false")


def git(*arguments: str) -> str:
    """Run git in the current directory and return its standard output."""
    executable = shutil.which("git")
    if executable is None:
        raise RuntimeError("git was not found on PATH")
    completed = subprocess.run(  # noqa: S603  # fixed program; arguments come from this repo's tools
        [executable, *STABLE_OUTPUT, *arguments],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return completed.stdout


def commits(revisions: Sequence[str], *, merges: bool = True) -> list[str]:
    """Return the commits of ``[BASE] HEAD``, oldest first.

    With a base, they are the commits after it; without one, or with the null commit, every
    commit HEAD reaches.
    """
    *base, head = revisions
    spec = f"{base[0]}..{head}" if base and base[0] not in ("", NULL_SHA) else head
    options = () if merges else ("--no-merges",)
    return git("rev-list", "--reverse", *options, spec).split()


def pushed_revisions(environ: Mapping[str, str]) -> list[str]:
    """Return ``[BASE] HEAD`` for the commits a pre-push hook is checking.

    pre-commit passes the range in ``PRE_COMMIT_FROM_REF`` and ``PRE_COMMIT_TO_REF``. When a
    push sends the root commit, it passes neither, only the local branch, and every commit
    of that branch is new.
    """
    from_ref, to_ref = environ.get("PRE_COMMIT_FROM_REF"), environ.get("PRE_COMMIT_TO_REF")
    if from_ref and to_ref:
        return [from_ref, to_ref]
    return [environ.get("PRE_COMMIT_LOCAL_BRANCH") or "HEAD"]


def message_lines(message: str) -> list[tuple[int, str]]:
    """Return the numbered lines git keeps from a message: no comments, nothing below scissors."""
    kept: list[tuple[int, str]] = []
    for number, line in enumerate(message.splitlines(), start=1):
        if line == SCISSORS:
            break
        if not line.startswith("#"):
            kept.append((number, line))
    return kept
