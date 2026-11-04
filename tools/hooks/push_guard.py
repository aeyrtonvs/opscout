# SPDX-License-Identifier: Apache-2.0
"""PreToolUse hook: outward-facing commands must take the form their ``ask`` rule matches.

Rule 5 of AGENTS.md is enforced by ``ask`` rules in ``.claude/settings.json``, such as
``Bash(git push *)``. Those rules match the command as written, so forms like
``git -C repo push``, ``FOO=1 git push`` or ``bash -c 'git push'`` slip past them. This hook
denies those forms and names the plain form to use, which the ``ask`` rule then catches.
The gated operations are read from the ``ask`` rules themselves, so the two cannot drift
apart.

The command is read roughly as a shell reads it: quotes, comments, line continuations and
here-documents first, then words. A command this reader still cannot split is denied when it
names a gated command, so a gap in the reader fails closed. The hook catches the forms an
agent writes by habit; it is not a defense against deliberate evasion.
"""

import json
import os
import re
import shlex
from collections.abc import Sequence
from pathlib import Path, PurePath
from typing import Any

from tools.hooks._protocol import Decision, Event, run_hook

Prefix = tuple[str, ...]

ASK_RULE = re.compile(r"Bash\((?P<prefix>[^*()]+?)(?: \*)?\)")
# A here-document operator; not a here-string (<<<) and not a shift such as 1<<4.
HEREDOC = re.compile(
    r"(?<![<\w])<<(?!<)(?P<strip>-?)[ \t]*(?P<quote>['\"]?)(?P<delimiter>[A-Za-z_]\w*)(?P=quote)"
)
# Command substitutions inside a word, such as "$(git push)" in double quotes.
SUBSTITUTION = re.compile(r"\$\(([^()]*)\)|`([^`]*)`")
PUNCTUATION = "();<>|&`\n"
SEPARATOR_CHARS = frozenset(";|&\n")
SHELLS = frozenset({"bash", "dash", "fish", "ksh", "sh", "zsh"})
# Global options that take a separate value, so the value is not read as the subcommand.
VALUE_OPTIONS = {
    "gh": frozenset({"-R", "--repo"}),
    "git": frozenset({"-C", "-c", "--config-env", "--git-dir", "--namespace", "--work-tree"}),
    "uv": frozenset({"--cache-dir", "--color", "--config-file", "--directory", "--project"}),
}


def ask_prefixes(settings: dict[str, Any]) -> list[Prefix]:
    """Return the command prefixes of the ``Bash(...)`` ask rules, in order."""
    rules = settings.get("permissions", {}).get("ask", [])
    return [tuple(match["prefix"].split()) for rule in rules if (match := ASK_RULE.fullmatch(rule))]


def find_escape(command: str, prefixes: Sequence[Prefix], *, nested: bool = False) -> Prefix | None:
    """Return the gated prefix that ``command`` runs in a form its ask rule misses, if any.

    Inside a nested script (``eval``, a shell's ``-c``, a command substitution in a word, a
    here-document fed to a shell) every gated command escapes, since the ask rules see only
    the outer command.
    """
    text, scripts = _preprocess(command)
    for script in scripts:
        if (found := find_escape(script, prefixes, nested=True)) is not None:
            return found
    try:
        simple_commands = _simple_commands(text)
    except ValueError:  # quoting this reader cannot follow, such as $'...': fail closed
        return _named(text, prefixes)
    for words in simple_commands:
        for script in _nested_scripts(words):
            if (found := find_escape(script, prefixes, nested=True)) is not None:
                return found
        for prefix in prefixes:
            if _invokes(words, prefix) and (nested or tuple(words[: len(prefix)]) != prefix):
                return prefix
    return None


def decide(event: Event, prefixes: Sequence[Prefix]) -> Decision | None:
    """Deny a Bash command that runs a gated operation in a form its ask rule misses."""
    command = event.get("tool_input", {}).get("command")
    if event.get("tool_name") != "Bash" or not isinstance(command, str):
        return None
    try:
        prefix = find_escape(command, prefixes)
    except Exception:  # a bug in the reader must not open the gate
        prefix = _named(command, prefixes)
    if prefix is None:
        return None
    plain = " ".join(prefix)
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"Rule 5 (AGENTS.md): `{plain}` must ask the maintainer first, and its ask rule "
                f"matches only the plain form. Run it as its own command starting with `{plain}`, "
                f"from the right directory (`cd <dir> && {plain} ...`), with no options, "
                f"variables or wrappers before it."
            ),
        }
    }


def _preprocess(command: str) -> tuple[str, list[str]]:
    """Return the command without comments, line continuations and here-document bodies.

    Also return the bodies of the here-documents fed to a shell, which are scripts to check.
    Any other body is data, such as a commit message, and is dropped.
    """
    out: list[str] = []
    scripts: list[str] = []
    pending: list[tuple[str, bool]] = []
    line_start = 0
    quote = ""
    i, end = 0, len(command)
    while i < end:
        char = command[i]
        if quote == "'":
            out.append(char)
            quote = "" if char == "'" else quote
            i += 1
        elif char == "\\" and i + 1 < end:
            if command[i + 1] != "\n":  # a backslash-newline joins the two lines
                out.append(command[i : i + 2])
            i += 2
        elif quote == '"':
            out.append(char)
            quote = "" if char == '"' else quote
            i += 1
        elif char in "'\"":
            out.append(char)
            quote = char
            i += 1
        elif char == "#" and (not out or out[-1][-1] in " \t\n;&|()"):
            newline = command.find("\n", i)
            i = end if newline == -1 else newline
        elif (
            char == "<"
            and (heredoc := HEREDOC.match(command, i))
            and "$((" not in "".join(out[line_start:])
        ):
            pending.append((heredoc["delimiter"], heredoc["strip"] == "-"))
            out.append(heredoc.group())
            i = heredoc.end()
        elif char == "\n":
            out.append(char)
            i += 1
            if pending:
                line = "".join(out[line_start:])
                to_shell = any(
                    _program(word) in SHELLS for word in re.findall(r"[^\s;&|()<>'\"]+", line)
                )
                for delimiter, strip_tabs in pending:
                    body: list[str] = []
                    while i < end:
                        newline = command.find("\n", i)
                        raw = command[i:] if newline == -1 else command[i:newline]
                        i = end if newline == -1 else newline + 1
                        if (raw.lstrip("\t") if strip_tabs else raw) == delimiter:
                            break
                        body.append(raw)
                    if to_shell:
                        scripts.append("\n".join(body))
                pending.clear()
            line_start = len(out)
        else:
            out.append(char)
            i += 1
    return "".join(out), scripts


def _simple_commands(command: str) -> list[list[str]]:
    """Split a command line into the words of each simple command."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=PUNCTUATION)
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""  # comments are already gone; shlex would also end a word at "#"
    commands: list[list[str]] = [[]]
    for token in lexer:
        if set(token) <= set(PUNCTUATION) and set(token) & SEPARATOR_CHARS:
            commands.append([])
        else:
            commands[-1].append(token)
    return [words for words in commands if words]


def _nested_scripts(words: list[str]) -> list[str]:
    """Return the scripts that ``eval``, a shell's ``-c`` or a substitution in a word runs."""
    scripts: list[str] = []
    for index, word in enumerate(words):
        scripts.extend(
            next(part for part in match.groups() if part is not None)
            for match in SUBSTITUTION.finditer(word)
        )
        name = _program(word)
        if name == "eval":
            scripts.append(" ".join(words[index + 1 :]))
        elif name in SHELLS:
            rest = words[index + 1 :]
            for position, token in enumerate(rest[:-1]):
                if token.startswith("-") and not token.startswith("--") and "c" in token:
                    scripts.append(rest[position + 1])
                    break
    return scripts


def _named(text: str, prefixes: Sequence[Prefix]) -> Prefix | None:
    """Return the first gated prefix whose words appear, in order, on one line of ``text``."""
    for prefix in prefixes:
        program, *subcommand = prefix
        pattern = rf"(?<![\w.-]){re.escape(program)}(?:\.exe)?\b" + "".join(
            rf"[^\n]*?\b{re.escape(word)}\b" for word in subcommand
        )
        if re.search(pattern, text):
            return prefix
    return None


def _invokes(words: list[str], prefix: Prefix) -> bool:
    """Whether ``words`` runs the prefix's program with the prefix's subcommand."""
    program, *subcommand = prefix
    value_options = VALUE_OPTIONS.get(program, frozenset())
    return any(
        _program(word) == program
        and _leading_words(words[index + 1 :], value_options, len(subcommand)) == subcommand
        for index, word in enumerate(words)
    )


def _leading_words(tokens: list[str], value_options: frozenset[str], count: int) -> list[str]:
    """Return the first ``count`` words that are neither options nor option values."""
    words: list[str] = []
    skip_value = False
    for token in tokens:
        if len(words) == count:
            break
        if skip_value:
            skip_value = False
        elif token.startswith("-"):
            skip_value = token in value_options
        else:
            words.append(token)
    return words


def _program(word: str) -> str:
    """The program a word names, without its directory: ``/usr/bin/git`` is ``git``."""
    return PurePath(word).name.removesuffix(".exe")


def main() -> int:
    """Run the hook against the project's own ask rules."""
    settings_file = Path(os.environ.get("CLAUDE_PROJECT_DIR", ".")) / ".claude" / "settings.json"
    prefixes = ask_prefixes(json.loads(settings_file.read_text(encoding="utf-8")))
    return run_hook(lambda event: decide(event, prefixes))


if __name__ == "__main__":
    raise SystemExit(main())
