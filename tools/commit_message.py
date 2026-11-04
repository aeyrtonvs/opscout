# SPDX-License-Identifier: Apache-2.0
"""Commit messages follow Conventional Commits 1.0 (ADR-0016).

python -m tools.commit_message FILE                 # the commit-msg hook
python -m tools.commit_message --range [BASE] HEAD  # each commit of a range (CI)
"""

import argparse
import re
import sys
from collections.abc import Sequence
from pathlib import Path

from tools._git import commits, git

TYPES = (
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
SUBJECT = re.compile(rf"(?:{'|'.join(TYPES)})(?:\([a-z0-9][a-z0-9./-]*\))?!?: \S.*")
# Messages git writes itself, for autosquash and for reverts.
GENERATED = ("fixup! ", "squash! ", "amend! ", 'Revert "')
SCISSORS = "# ------------------------ >8 ------------------------"


def problems(message: str) -> list[str]:
    """Return what keeps ``message`` from being a Conventional Commit; empty when it is one."""
    lines: list[str] = []
    for line in message.splitlines():
        if line == SCISSORS:
            break
        if not line.startswith("#"):
            lines.append(line)
    subject = lines[0] if lines else ""
    if subject.startswith(GENERATED):
        return []
    found = []
    if not SUBJECT.fullmatch(subject):
        found.append(
            f"the subject {subject!r} must read '<type>[(scope)][!]: <description>', "
            f"with a type from: {', '.join(TYPES)}"
        )
    if len(lines) > 1 and lines[1].strip():
        found.append("a blank line must separate the subject from the body")
    return found


def main(argv: Sequence[str] | None = None) -> int:
    """Check one message file, or every commit of a range; return 1 on any problem."""
    parser = argparse.ArgumentParser(
        prog="python -m tools.commit_message",
        description="Check that commit messages follow Conventional Commits (ADR-0016).",
    )
    parser.add_argument("target", nargs="+", help="a message file, or [BASE] HEAD with --range")
    parser.add_argument("--range", action="store_true", help="check each commit of a range")
    args = parser.parse_args(argv)

    messages: list[tuple[str, str]]
    if args.range:
        if len(args.target) > 2:
            parser.error("--range takes [BASE] HEAD")
        messages = [
            (f"commit {sha[:12]}", git("show", "-s", "--format=%B", sha))
            for sha in commits(args.target)
        ]
    else:
        messages = [(name, Path(name).read_text(encoding="utf-8")) for name in args.target]

    failed = False
    for where, message in messages:
        for problem in problems(message):
            print(f"{where}: {problem}", file=sys.stderr)
            failed = True
    if failed:
        print("See https://www.conventionalcommits.org/en/v1.0.0/", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
