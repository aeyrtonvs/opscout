# SPDX-License-Identifier: Apache-2.0
"""Run git, and list the commits of a range, for the checks that read history."""

import shutil
import subprocess
from collections.abc import Sequence

NULL_SHA = "0" * 40  # what GitHub sends as the "before" commit of a new branch


def git(*arguments: str) -> str:
    """Run git in the current directory and return its standard output."""
    executable = shutil.which("git")
    if executable is None:
        raise RuntimeError("git was not found on PATH")
    completed = subprocess.run(  # noqa: S603  # fixed program; arguments come from this repo's tools
        [executable, *arguments],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return completed.stdout


def commits(revisions: Sequence[str]) -> list[str]:
    """Return the commits of ``[BASE] HEAD``, oldest first.

    With a base, they are the commits after it; without one, or with the null commit, every
    commit HEAD reaches.
    """
    *base, head = revisions
    spec = f"{base[0]}..{head}" if base and base[0] not in ("", NULL_SHA) else head
    return git("rev-list", "--reverse", spec).split()
