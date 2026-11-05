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
from pathlib import PurePath

from opscout.core.config import Ship
from opscout.core.ship import (
    ALWAYS_PROTECTED,
    DEFAULT_REMOTE,
    PushCommand,
    PushConfig,
    PushDecision,
)

_MENTIONS = re.compile(r"\bgit\b[\s\S]*\bpush\b|\bgh\b[\s\S]*\bpr\b[\s\S]*\bcreate\b")
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
_OPERATOR = frozenset(";&|()<>")
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
_SHORTHANDS = ("heads/", "tags/", "remotes/")
DEFAULT_PUSH_CONFIG = PushConfig()
_PLAIN = (
    "run git push as its own plain command, `git [-C <dir>] push [<options>] [<remote> "
    "[<branch>...]]`, so the guard can read it"
)


def _deny_unreadable(what: str) -> PushDecision:
    return PushDecision("deny", f"opscout push guard: {what}; {_PLAIN} (spec 004).")


def _deny(what: str) -> PushDecision:
    return PushDecision("deny", f"opscout push guard: {what} (spec 004).")


def _segments(tokens: list[str]) -> list[list[str]]:
    """Split words into simple commands at the shell's operators (outside quotes)."""
    segments: list[list[str]] = [[]]
    for token in tokens:
        if token and all(character in _OPERATOR for character in token):
            segments.append([])
        else:
            segments[-1].append(token)
    return [segment for segment in segments if segment]


def read_command(command: str) -> PushCommand | PushDecision | None:
    """Read a Bash command: a plain push, a decision already, or None when it is not the guard's.

    A ``PushDecision`` comes back for ``gh pr create`` (ask) and for a push in a form the
    guard cannot read (deny). A command that only mentions a push (``git log | grep push``,
    ``echo git push``) is left alone.
    """
    if not _MENTIONS.search(command):
        return None
    try:
        lexer = shlex.shlex(command.replace("\n", " ; "), posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return _deny_unreadable("this command cannot be split into words")
    segments = _segments(tokens)
    compound = len(segments) > 1 or len(tokens) != sum(map(len, segments))
    substitutes = any("$" in token or "`" in token for token in tokens)
    found: PushCommand | PushDecision | None = None
    for segment in segments:
        head = segment[0]
        if head in _WRAPPERS or _ASSIGNMENT.fullmatch(head):
            if _MENTIONS.search(" ".join(segment)):
                return _deny_unreadable("this command runs git inside another command")
            continue
        if PurePath(head).name == "git":
            read = _read_git(segment[1:])
        elif head == "gh" and segment[1:3] == ["pr", "create"]:
            read = PushDecision("ask", "opscout: open a pull request on GitHub?")
        else:
            continue
        if read is None:
            continue
        if compound:
            return _deny_unreadable("a push or pull request must be its own command")
        if substitutes:
            return _deny_unreadable("this command substitutes text the guard cannot know")
        found = read
    return found


def _read_git(words: list[str]) -> PushCommand | PushDecision | None:
    directory = None
    if words[:1] == ["-C"] and len(words) >= 2:
        directory, words = words[1], words[2:]
    if not words:
        return None
    if words[0] != "push":
        if words[0].startswith("-") and "push" in words:
            return _deny_unreadable("git options other than -C come before push")
        if words[0] == "subtree" and "push" in words:
            return _deny_unreadable("git subtree push is not one the guard reads")
        return None
    delete = force = False
    positional: list[str] = []
    for word in words[1:]:
        if word in _EVERY_BRANCH:
            return _deny(f"{word} may push a protected branch")
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


def protected(name: str, *, default: str | None, patterns: Iterable[str]) -> bool:
    """Return whether a branch is protected: a pattern, main, master or the remote's default."""
    always = {*ALWAYS_PROTECTED, *([default] if default else [])}
    return name in always or any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns)


def _destination(target: str, current: str | None) -> str | PushDecision:
    """Return the branch a refspec's destination names, or why it is refused."""
    if target in ("HEAD", "@"):
        if current is None:
            return _deny("HEAD is detached or unknown, so this push has no branch; name it")
        return current
    if "*" in target:
        return _deny("a glob refspec may push a protected branch")
    if target.startswith(_SHORTHANDS):
        return _deny(f"{target} is ambiguous; name the branch, or use refs/heads/<branch>")
    if target.startswith("refs/heads/"):
        return target.removeprefix("refs/heads/")
    if target.startswith("refs/") and not target.startswith("refs/tags/"):
        return _deny(f"{target} is not a branch or a tag")
    return target


def decide_push(
    push: PushCommand,
    *,
    current: str | None,
    default: str | None,
    patterns: Iterable[str],
    config: PushConfig = DEFAULT_PUSH_CONFIG,
) -> PushDecision:
    """Decide about a plain push: deny any protected destination, else ask (FR-007, FR-008).

    The destination of a push without a refspec follows git's configuration: ``push.default``
    (``simple`` and ``current`` push the current branch, ``upstream`` its upstream, and
    ``matching`` every branch) and ``remote.<name>.push``, which may redirect any push.
    """
    patterns = tuple(patterns)
    remote = push.remote or DEFAULT_REMOTE
    if config.remote_push:
        return _deny(
            f"remote.{remote}.push is set, so git's configuration chooses the destination; "
            "remove it, or push with `git push -u origin <branch>` from a clone without it"
        )
    destinations: list[str] = []
    deleted: list[str] = []
    if not push.refspecs:
        if config.push_default == "matching":
            return _deny("push.default is matching, which pushes every branch")
        if current is None:
            return _deny("HEAD is detached, so this push has no branch; name the branch to push")
        upstream = config.upstream if config.push_default in ("upstream", "tracking") else None
        destinations.append(upstream or current)
    for spec in push.refspecs:
        bare = spec.removeprefix("+")
        if bare in ("", ":"):
            return _deny("a matching refspec (:) pushes every branch both sides have")
        source, colon, target = bare.partition(":")
        if push.delete or (colon and not source):
            name = _destination(target or source, current)
            if isinstance(name, PushDecision):
                return name
            deleted.append(name)
            continue
        name = _destination(target or source, current)
        if isinstance(name, PushDecision):
            return name
        destinations.append(name)
    for name in [*deleted, *destinations]:
        if name.startswith("refs/tags/"):
            continue
        if protected(name, default=default, patterns=patterns):
            action = "deleting" if name in deleted else "pushing to"
            return _deny(
                f"{name} is protected, so {action} it is refused; push a feature branch and "
                "open a pull request"
            )
    named = ", ".join([*destinations, *(f"delete {name}" for name in deleted)])
    forced = " (force)" if push.force else ""
    return PushDecision("ask", f"opscout: push to {remote}: {named}{forced}?")


# The conventions and the checks (User Stories 3 and 4)

MAX_SLUG = 50
MAX_SUBJECT = 72
_SLUG = r"(?P<slug>[a-z0-9]+(?:-[a-z0-9]+)*)"
_TICKET = r"[A-Z][A-Z0-9]+-[0-9]+"
_SCISSORS = "# ------------------------ >8 ------------------------"


def render_rules(ship: Ship, *, source: str) -> str:
    """Return the conventions as plain instructions for the skill; deterministic (FR-003)."""
    extra = [pattern for pattern in ship.protected_branches if pattern not in ALWAYS_PROTECTED]
    protected_list = ", ".join([*ALWAYS_PROTECTED, *extra])
    branch = (
        f"Branch names: {ship.branch_pattern}. {{type}} is one of: {', '.join(ship.types)}. "
        f"{{slug}} is lowercase words joined by hyphens, at most {MAX_SLUG} characters."
    )
    if "{ticket}" in ship.branch_pattern:
        branch += " {ticket} is a ticket key such as EXAMPLE-123."
    base = ship.pull_request.base or "the remote's default branch"
    lines = [
        "# Ship conventions",
        "",
        source,
        "",
        f"Protected branches, never pushed to: {protected_list}, and the remote's default branch.",
        branch,
        f"Commit messages: `<type>[(scope)][!]: <description>`, at most {MAX_SUBJECT} "
        "characters, with a type from the list above; a blank line before any body; the last "
        f"line is exactly: {ship.trailer}",
        f"Pull requests: drafts, against {base}.",
    ]
    return "\n".join(lines) + "\n"


def _branch_regex(ship: Ship) -> re.Pattern[str]:
    types = "|".join(map(re.escape, ship.types))
    parts = re.split(r"(\{type\}|\{slug\}|\{ticket\})", ship.branch_pattern)
    tokens = {"{type}": f"(?:{types})", "{slug}": _SLUG, "{ticket}": _TICKET}
    return re.compile("".join(tokens.get(part, re.escape(part)) for part in parts))


def check_branch(name: str, ship: Ship, *, default: str | None) -> list[str]:
    """Return why a branch name is not acceptable; empty when it is (FR-004)."""
    reasons = []
    if protected(name, default=default, patterns=ship.protected_branches):
        reasons.append(f"{name} is protected; ship from a feature branch")
    match = _branch_regex(ship).fullmatch(name)
    if match is None:
        if not reasons:
            reasons.append(
                f"the name does not follow {ship.branch_pattern} (types: {', '.join(ship.types)})"
            )
    elif len(match.group("slug")) > MAX_SLUG:
        reasons.append(f"the slug is longer than {MAX_SLUG} characters")
    return reasons


def check_message(message: str, ship: Ship, *, strip_comments: bool = True) -> list[str]:
    """Return every problem of a commit message; empty when it is acceptable (FR-005).

    A message file drops its ``#`` lines and what follows the scissors line, as git's editor
    does; ``git commit -m`` keeps both, so paragraphs are checked with ``strip_comments``
    off.
    """
    text = message.split(_SCISSORS, 1)[0] if strip_comments else message
    lines = [
        line.rstrip() for line in text.splitlines() if not (strip_comments and line.startswith("#"))
    ]
    while lines and not lines[-1]:
        lines.pop()
    subject = lines[0] if lines else ""
    types = "|".join(map(re.escape, ship.types))
    reasons = []
    if not re.fullmatch(rf"(?:{types})(?:\([A-Za-z0-9][A-Za-z0-9_./-]*\))?!?: \S.*", subject):
        reasons.append(
            "the subject must read '<type>[(scope)][!]: <description>' with a type from: "
            + ", ".join(ship.types)
        )
    elif len(subject) > MAX_SUBJECT:
        reasons.append(f"the subject is longer than {MAX_SUBJECT} characters")
    if len(lines) > 1 and lines[1]:
        reasons.append("a blank line must separate the subject from the body")
    if len(lines) < 2 or lines[-1] != ship.trailer:
        reasons.append(f"the last line must be the trailer: {ship.trailer}")
    return reasons
