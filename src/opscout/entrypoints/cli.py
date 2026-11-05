# SPDX-License-Identifier: Apache-2.0
"""The ``opscout`` command line."""

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from opscout import __version__
from opscout.core.config import (
    SCHEMA_VERSION,
    ConfigLocationError,
    InvalidConfigError,
    Ship,
    Writeups,
    schema_text,
)
from opscout.entrypoints.config import config_file, load_config
from opscout.entrypoints.hook import BLOCKED, HookError, pre_tool_use
from opscout.services.config import resolve_config_dir
from opscout.services.ship import check_branch, check_message, render_rules
from opscout.services.writeups import render_formats, render_invalid, resolve_formats


def build_parser() -> argparse.ArgumentParser:
    """Return the parser for the ``opscout`` command."""
    parser = argparse.ArgumentParser(
        prog="opscout",
        description="Read-only Claude Code agents for the repetitive parts of DevOps work.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")

    config = commands.add_parser(
        "config", help="check the configuration", description="Check the configuration."
    )
    config_commands = config.add_subparsers(dest="config_command", metavar="COMMAND", required=True)
    validate = config_commands.add_parser(
        "validate",
        help="validate the configuration and list every problem",
        description=(
            "Validate config.yaml in the configuration directory: --config, else "
            "OPSCOUT_CONFIG, else ~/.config/opscout/."
        ),
    )
    validate.add_argument("--config", metavar="DIR", type=Path, help="the configuration directory")
    config_commands.add_parser(
        "schema",
        help="print the JSON Schema of the configuration",
        description="Print the JSON Schema, as committed at schemas/config.schema.json.",
    )
    writeup = commands.add_parser(
        "writeup", help="write-up formats", description="Write-up formats (spec 003)."
    )
    writeup_commands = writeup.add_subparsers(
        dest="writeup_command", metavar="COMMAND", required=True
    )
    formats = writeup_commands.add_parser(
        "formats",
        help="print the write-up formats for the summary skill",
        description=(
            "Print the built-in write-up formats with the configured ones applied. Always "
            "exits 0; problems are explained in the output."
        ),
    )
    formats.add_argument(
        "--config", metavar="DIR", help="the configuration directory; empty counts as absent"
    )
    ship = commands.add_parser(
        "ship", help="ship conventions and checks", description="Ship conventions (spec 004)."
    )
    ship_commands = ship.add_subparsers(dest="ship_command", metavar="COMMAND", required=True)
    rules = ship_commands.add_parser(
        "rules", help="print the conventions for the ship skill; always exits 0"
    )
    branch = ship_commands.add_parser("check-branch", help="check a branch name")
    branch.add_argument("name")
    branch.add_argument("--default-branch", metavar="NAME", help="the remote's default branch")
    message = ship_commands.add_parser("check-message", help="check a commit message")
    message_source = message.add_mutually_exclusive_group(required=True)
    message_source.add_argument("file", nargs="?", help="the message file, or - for standard input")
    message_source.add_argument(
        "-m",
        dest="paragraphs",
        action="append",
        metavar="PARAGRAPH",
        help="a paragraph, as git commit -m takes it; repeat for more",
    )
    for command in (rules, branch, message):
        command.add_argument(
            "--config", metavar="DIR", help="the configuration directory; empty counts as absent"
        )
    hook = commands.add_parser(
        "hook", help="the plugin's hooks", description="The plugin's hooks (spec 004)."
    )
    hook_commands = hook.add_subparsers(dest="hook_command", metavar="COMMAND", required=True)
    pre_tool_use = hook_commands.add_parser(
        "pre-tool-use",
        help="the push guard: read a PreToolUse event on stdin",
        description="Ask before every git push, and deny a push to a protected branch.",
    )
    pre_tool_use.add_argument(
        "--config", metavar="DIR", help="the configuration directory; empty counts as absent"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line and return its exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "config" and args.config_command == "validate":
        return _validate(args.config)
    if args.command == "config" and args.config_command == "schema":
        sys.stdout.write(schema_text())
        return 0
    if args.command == "writeup" and args.writeup_command == "formats":
        sys.stdout.write(_formats(_given_directory(args.config)))
        return 0
    if args.command == "ship":
        return _ship(args)
    if args.command == "hook" and args.hook_command == "pre-tool-use":
        # Claude Code gives a plugin's hooks their options as CLAUDE_PLUGIN_OPTION_<KEY>; the
        # docs do not say whether the key keeps its case, so both spellings are read.
        lower = "CLAUDE_PLUGIN_OPTION_config_dir"
        given = args.config or os.environ.get(
            "CLAUDE_PLUGIN_OPTION_CONFIG_DIR", os.environ.get(lower)
        )
        location = resolve_config_dir(_given_directory(given), os.environ, Path.home())
        try:
            sys.stdout.write(pre_tool_use(sys.stdin.read(), location))
        except HookError as error:
            sys.stderr.write(f"{error}\n")
            return BLOCKED
        except Exception as error:  # the guard never fails open (spec 004, FR-013)
            sys.stderr.write(f"opscout push guard: {type(error).__name__}: {error}\n")
            return BLOCKED
        return 0
    parser.print_help()
    return 0


def _ship(args: argparse.Namespace) -> int:
    """Run a ship command (spec 004)."""
    location = resolve_config_dir(_given_directory(args.config), os.environ, Path.home())
    try:
        ship = load_config(location.directory).ship
        source = f"Source: {config_file(location.directory)} ({location.source})"
    except ConfigLocationError as error:
        ship, source = Ship(), f"Source: none, {error} ({location.source}); using the defaults"
    except InvalidConfigError as error:
        if args.ship_command == "rules":
            sys.stdout.write(
                render_invalid(
                    location.directory,
                    len(error.problems),
                    title="# Ship conventions",
                    missing="ship convention",
                )
            )
            return 0
        print(f"opscout ship: the configuration has {len(error.problems)} problem(s)")
        return 1
    if args.ship_command == "rules":
        sys.stdout.write(render_rules(ship, source=source))
        return 0
    if args.ship_command == "check-branch":
        reasons = check_branch(args.name, ship, default=args.default_branch)
    else:
        if args.paragraphs:
            text = "\n\n".join(args.paragraphs) + "\n"
        elif args.file == "-":
            text = sys.stdin.read()
        else:
            text = Path(args.file).read_text(encoding="utf-8")
        reasons = check_message(text, ship, strip_comments=not args.paragraphs)
    for reason in reasons:
        print(reason)
    return 1 if reasons else 0


def _given_directory(value: str | None) -> Path | None:
    """Return the ``--config`` directory a skill passed, or None when it passed none.

    A skill passes ``${user_config.config_dir}``. Claude Code substitutes it when the plugin
    was installed and configured; when the plugin is loaded from a clone, the placeholder
    arrives as is. Both an empty value and the placeholder count as no directory, so the
    resolution falls back to ``OPSCOUT_CONFIG`` and the default (spec 003, FR-009).
    """
    if not value or value.startswith("${user_config."):
        return None
    return Path(value)


def _formats(flag: Path | None) -> str:
    """Return the write-up formats, or why there are none (spec 003, FR-008 to FR-010)."""
    location = resolve_config_dir(flag, os.environ, Path.home())
    try:
        configuration = load_config(location.directory)
    except ConfigLocationError as error:
        source = f"Source: none, {error} ({location.source}); using the built-in formats"
        return render_formats(resolve_formats(Writeups()), source=source, language=None)
    except InvalidConfigError as error:
        return render_invalid(location.directory, len(error.problems))
    writeups = configuration.writeups
    source = f"Source: {config_file(location.directory)} ({location.source})"
    return render_formats(resolve_formats(writeups), source=source, language=writeups.language)


def _validate(flag: Path | None) -> int:
    """Validate the configuration; print its directory, then the result (contracts/cli.md)."""
    location = resolve_config_dir(flag, os.environ, Path.home())
    print(f"opscout config: {location.describe()}")
    try:
        load_config(location.directory)
    except ConfigLocationError as error:
        print(f"opscout config: {error}")
        return 1
    except InvalidConfigError as error:
        for problem in error.problems:
            print(problem.render())
        return 1
    print(f"{config_file(location.directory)}: valid (schema version {SCHEMA_VERSION})")
    return 0
