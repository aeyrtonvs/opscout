# SPDX-License-Identifier: Apache-2.0
"""The ship skill's checks and the push guard's decision (spec 004).

The guard reads only the plain form, ``git [-C <dir>] push [<options>] [<remote>
[<refspec>...]]``, and ``gh pr create``. A push in any other form, such as one inside a
compound command, after a variable or a wrapper, or in a nested shell, is denied with a
request for the plain form. It catches the forms an agent writes by habit and fails closed
on the rest; it is not a defense against deliberate evasion (ADR-0018).
"""

import fnmatch
import re
import shlex
from collections.abc import Iterable

from opscout.core.ship import ALWAYS_PROTECTED, DEFAULT_REMOTE, PushCommand, PushDecision

_MENTIONS_PUSH = re.compile(r"(?:^|[\s;&|(`$])git\b[\s\S]*\bpush\b")
_MENTIONS_PR = re.compile(r"(?:^|[\s;&|(`$])gh\b[\s\S]*\bpr\b[\s\S]*\bcreate\b")
_ANYWHERE = re.compile(r"\bgit\b[\s\S]*\bpush\b|\bgh\b[\s\S]*\bpr\b[\s\S]*\bcreate\b")
_ASSIGNMENT = re.compile(r"[A-Za-z_]\w*=.*", re.DOTALL)
# Programs that run another command: what follows them is a nested script.
_WRAPPERS = frozenset(
    {
        "bash",
        "dash",
        "fish",
        "ksh",
        "sh",
        "zsh",
        "eval",
        "env",
        "sudo",
        "doas",
        "nice",
        "nohup",
        "time",
        "command",
        "exec",
        "xargs",
        "watch",
        "timeout",
    }
)
_PUNCTUATION = frozenset(";&|()<>")
_ACCEPTED = frozenset(
    {
        "-u",
        "--set-upstream",
        "--tags",
        "--follow-tags",
        "--no-follow-tags",
        "--dry-run",
        "-n",
        "--no-verify",
        "--verify",
        "-q",
        "--quiet",
        "-v",
        "--verbose",
        "--porcelain",
        "--progress",
        "--no-progress",
        "--atomic",
        "--no-atomic",
        "--force-if-includes",
    }
)
_FORCE = frozenset({"-f", "--force", "--force-with-lease"})
_DELETE = frozenset({"-d", "--delete"})
_EVERY_BRANCH = frozenset({"--all", "--mirror", "--branches"})
_PLAIN = (
    "run git push as its own plain command, `git [-C <dir>] push [<options>] [<remote> "
    "[<branch>...]]`, so the guard can read it"
)


def _deny_unreadable(what: str) -> PushDecision:
    return PushDecision("deny", f"opscout push guard: {what}; {_PLAIN} (spec 004).")


def read_command(command: str) -> PushCommand | PushDecision | None:
    """Read a Bash command: a plain push, a decision already, or None when it is not the guard's.

    A ``PushDecision`` comes back for ``gh pr create`` (ask) and for a push in a form the
    guard cannot read (deny).
    """
    mentions_push = bool(_MENTIONS_PUSH.search(command))
    mentions_pr = bool(_MENTIONS_PR.search(command))
    nested = bool(_ANYWHERE.search(command))
    if not (mentions_push or mentions_pr or nested):
        return None
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return _deny_unreadable("this command cannot be split into words")
    plain = (
        "\n" not in command
        and not any(set(token) & _PUNCTUATION for token in tokens)
        and not any("$" in token or "`" in token for token in tokens)
    )
    if tokens[:3] == ["gh", "pr", "create"] and plain:
        return PushDecision("ask", "opscout: open a pull request on GitHub?")
    if tokens and (tokens[0] in _WRAPPERS or _ASSIGNMENT.fullmatch(tokens[0])) and nested:
        return _deny_unreadable("this command runs git inside another command")
    if not plain or not tokens or tokens[0] != "git":
        if mentions_push:
            return _deny_unreadable("this command pushes in a form the guard cannot read")
        if mentions_pr:
            return _deny_unreadable(
                "this command opens a pull request in a form the guard cannot read"
            )
        return None
    return _read_git(tokens[1:])


def _read_git(words: list[str]) -> PushCommand | PushDecision | None:
    directory = None
    if words[:1] == ["-C"] and len(words) >= 2:
        directory, words = words[1], words[2:]
    if not words or words[0] != "push":
        if words and words[0].startswith("-") and "push" in words:
            return _deny_unreadable("git options other than -C come before push")
        return None
    delete = force = False
    positional: list[str] = []
    for word in words[1:]:
        if word in _EVERY_BRANCH:
            return PushDecision(
                "deny", f"opscout push guard: {word} may push a protected branch (spec 004)."
            )
        if word in _DELETE:
            delete = True
        elif word in _FORCE or word.startswith("--force-with-lease="):
            force = True
        elif word in _ACCEPTED:
            continue
        elif word.startswith("-"):
            return _deny_unreadable(f"the option {word} is not one the guard reads")
        else:
            positional.append(word)
    remote = positional[0] if positional else None
    refspecs = tuple(positional[1:])
    force = force or any(spec.startswith("+") for spec in refspecs)
    return PushCommand(directory, remote, refspecs, delete=delete, force=force)


def _branch(name: str) -> str:
    return name.removeprefix("refs/heads/")


def protected(name: str, *, default: str | None, patterns: Iterable[str]) -> bool:
    """Return whether a branch is protected: a pattern, main, master or the remote's default."""
    always = {*ALWAYS_PROTECTED, *([default] if default else [])}
    return name in always or any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns)


def decide_push(
    push: PushCommand, *, current: str | None, default: str | None, patterns: Iterable[str]
) -> PushDecision:
    """Decide about a plain push: deny any protected destination, else ask (FR-007, FR-008)."""
    patterns = tuple(patterns)
    remote = push.remote or DEFAULT_REMOTE
    destinations: list[str] = []
    deleted: list[str] = []
    if not push.refspecs:
        if current is None:
            return PushDecision(
                "deny",
                "opscout push guard: HEAD is detached, so this push has no branch; name the "
                "branch to push (spec 004).",
            )
        destinations.append(current)
    for spec in push.refspecs:
        spec = spec.removeprefix("+")
        source, _, target = spec.partition(":")
        if push.delete or (":" in spec and not source):
            deleted.append(_branch(target or source))
            continue
        target = target or source
        destinations.append(current or "HEAD" if target == "HEAD" else _branch(target))
    for name in [*deleted, *destinations]:
        if name.startswith("refs/"):
            continue
        if protected(name, default=default, patterns=patterns):
            action = "deleting" if name in deleted else "pushing to"
            return PushDecision(
                "deny",
                f"opscout push guard: {name} is protected, so {action} it is refused; push a "
                "feature branch and open a pull request (spec 004).",
            )
    named = ", ".join([*destinations, *(f"delete {name}" for name in deleted)])
    forced = " (force)" if push.force else ""
    return PushDecision("ask", f"opscout: push to {remote}: {named}{forced}?")
