# SPDX-License-Identifier: Apache-2.0
"""The ``opscout`` command line."""

import argparse
import os
import shlex
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
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
from opscout.core.context import PendingChange
from opscout.core.sso import AwsConfigError
from opscout.entrypoints import daemon, identity
from opscout.entrypoints.config import config_file, load_config
from opscout.entrypoints.context import TargetError, default_target, pending, write
from opscout.entrypoints.hook import (
    BLOCKED,
    HookError,
    could_not_run,
    pre_tool_use,
    session_start,
)
from opscout.entrypoints.sso import check_sessions, sso_settings
from opscout.services.config import resolve_config_dir
from opscout.services.context import render_block, unified_diff
from opscout.services.ship import check_branch, check_message, render_rules
from opscout.services.sso import render_status
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
    context = commands.add_parser(
        "context",
        help="your personal context in Claude Code's CLAUDE.md",
        description="Write your configured personal context into Claude Code's CLAUDE.md "
        "(spec 006).",
    )
    context_commands = context.add_subparsers(
        dest="context_command", metavar="COMMAND", required=True
    )
    show = context_commands.add_parser("show", help="print the block")
    diff = context_commands.add_parser(
        "diff", help="show what apply would change, and the code that confirms it"
    )
    apply = context_commands.add_parser(
        "apply", help="write the block, after a terminal yes or with --confirm"
    )
    for command in (show, diff, apply):
        command.add_argument(
            "--config", metavar="DIR", help="the configuration directory; empty counts as absent"
        )
    for command in (diff, apply):
        command.add_argument(
            "--target", metavar="FILE", help="the file to change; default: Claude Code's CLAUDE.md"
        )
    apply.add_argument("--confirm", metavar="CODE", help="the code opscout context diff printed")
    sso = commands.add_parser(
        "sso", help="check the SSO logins", description="Check the SSO logins (spec 005)."
    )
    sso_commands = sso.add_subparsers(dest="sso_command", metavar="COMMAND", required=True)
    sso_check = sso_commands.add_parser(
        "check",
        help="show each SSO login's state, from the local token cache",
        description=(
            "Show each SSO login's state from the local token cache, without the network. "
            "Exit 1 when a login is needed."
        ),
    )
    sso_check.add_argument(
        "--config", metavar="DIR", help="the configuration directory; empty counts as absent"
    )
    run = commands.add_parser(
        "run",
        help="run a scheduled job once for the current period",
        description=(
            "Run a job for the current period, at most once: a period that already delivered "
            "is skipped unless --force is given (spec 007). Exit 0 delivered or skipped, 1 "
            "refused, inconclusive or failed, 2 when the job cannot start."
        ),
    )
    run.add_argument("job", help="the job's name, such as check")
    run.add_argument("--force", action="store_true", help="run even if the period delivered")
    run.add_argument(
        "--trigger",
        choices=("scheduler", "user"),
        default="user",
        help="who started the run; installed jobs pass scheduler",
    )
    daemon = commands.add_parser(
        "daemon",
        help="install, list and remove the scheduled jobs",
        description="The scheduled jobs (spec 007).",
    )
    daemon_commands = daemon.add_subparsers(dest="daemon_command", metavar="COMMAND", required=True)
    install = daemon_commands.add_parser(
        "install",
        help="make the installed jobs match the configuration, after confirmation",
    )
    uninstall = daemon_commands.add_parser(
        "uninstall", help="remove every job opscout installed, after confirmation"
    )
    for command in (install, uninstall):
        command.add_argument(
            "--dry-run", action="store_true", help="list the changes and their code only"
        )
        command.add_argument("--confirm", metavar="CODE", help="the code --dry-run printed")
    status = daemon_commands.add_parser(
        "status", help="list the configured and installed jobs and their last outcome"
    )
    runs = daemon_commands.add_parser("runs", help="list recent runs, newest first")
    runs.add_argument("job", nargs="?", help="only this job's runs")
    runs.add_argument("--limit", type=int, default=20, metavar="N", help="at most N runs")
    standup = commands.add_parser(
        "standup", help="the daily standup", description="The daily standup (spec 009)."
    )
    standup_commands = standup.add_subparsers(
        dest="standup_command", metavar="COMMAND", required=True
    )
    preview = standup_commands.add_parser(
        "preview",
        help="show what the standup would send to the model; nothing is sent",
        description=(
            "Gather the window's facts as the standup would, redacted and shortened, and "
            "print them with the counts. Nothing is sent anywhere."
        ),
    )
    preview.add_argument("--counts", action="store_true", help="print the counts only")
    identity_parser = commands.add_parser(
        "identity",
        help="the read-only identity's reference documents",
        description="Prove or export the read-only identity's documents (spec 010).",
    )
    identity_commands = identity_parser.add_subparsers(
        dest="identity_command", metavar="COMMAND", required=True
    )
    identity_check = identity_commands.add_parser(
        "check",
        help="prove that a tree denies secret reads and writes; offline, read-only",
        description=(
            "Prove a directory of identity documents, or the packaged reference when DIR is "
            "omitted: secret reads and writes denied even with Allow * attached, declared "
            "reads allowed, nothing undeclared, host and cluster documents as the reference. "
            "Exit 0 pass, 1 findings, 2 unreadable."
        ),
    )
    identity_check.add_argument("directory", nargs="?", metavar="DIR", help="the tree to check")
    identity_export = identity_commands.add_parser(
        "export",
        help="write the editable reference documents into DIR, to instantiate them",
        description="Write the editable reference tree into DIR; nothing is overwritten.",
    )
    identity_export.add_argument("directory", metavar="DIR", help="where to write the tree")
    gateway = commands.add_parser(
        "gateway",
        help="hold the Slack connection and record agreement clicks (launchd runs it)",
        description=(
            "Connect to Slack over Socket Mode and store the configured user's agreement "
            "clicks in the run records (spec 008). Runs until stopped."
        ),
    )
    secret = commands.add_parser(
        "secret",
        help="the harness's own secrets in the OS keychain",
        description="Store and check the harness's own secrets; values are never shown.",
    )
    secret_commands = secret.add_subparsers(dest="secret_command", metavar="COMMAND", required=True)
    secret_set = secret_commands.add_parser(
        "set", help="store a secret: read without echo, or one line of standard input"
    )
    secret_set.add_argument("name", help="the secret's name, such as claude_token")
    secret_check = secret_commands.add_parser(
        "check", help="say whether each configured secret is in the keychain"
    )
    secret_check.add_argument("name", nargs="?", help="only this secret")
    for command in (
        run, install, uninstall, status, runs, gateway, preview, secret_set, secret_check,
    ):  # fmt: skip
        command.add_argument(
            "--config", metavar="DIR", help="the configuration directory; empty counts as absent"
        )
    hook = commands.add_parser(
        "hook", help="the plugin's hooks", description="The plugin's hooks (specs 004 and 005)."
    )
    hook_commands = hook.add_subparsers(dest="hook_command", metavar="COMMAND", required=True)
    pre_tool_use = hook_commands.add_parser(
        "pre-tool-use",
        help="the push guard: read a PreToolUse event on stdin",
        description="Ask before every git push, and deny a push to a protected branch.",
    )
    session_start = hook_commands.add_parser(
        "session-start",
        help="the SSO check: read a SessionStart event on stdin",
        description="Warn when an SSO login is needed; never blocks the session.",
    )
    for command in (pre_tool_use, session_start):
        command.add_argument(
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
    if args.command == "context":
        return _context(args)
    if args.command == "sso":
        return _sso_check(_given_directory(args.config))
    if args.command == "run":
        return daemon.run_command(
            args.job, force=args.force, trigger=args.trigger, flag=_given_directory(args.config)
        )
    if args.command == "daemon":
        return _daemon(args)
    if args.command == "standup":
        return daemon.preview_command(_given_directory(args.config), counts_only=args.counts)
    if args.command == "identity" and args.identity_command == "check":
        return identity.check_command(Path(args.directory) if args.directory else None)
    if args.command == "identity":
        return identity.export_command(Path(args.directory))
    if args.command == "gateway":
        return daemon.gateway_command(_given_directory(args.config))
    if args.command == "secret" and args.secret_command == "set":  # noqa: S105  (a command name)
        return daemon.secret_set_command(args.name, _given_directory(args.config))
    if args.command == "secret":
        return daemon.secret_check_command(args.name, _given_directory(args.config))
    if args.command == "hook" and args.hook_command == "session-start":
        try:
            sys.stdin.read()  # the event; the hook's matcher already chose the sources
            location = resolve_config_dir(_hook_directory(args), os.environ, Path.home())
            now = datetime.now(UTC)
            sys.stdout.write(session_start(location, os.environ, Path.home(), now))
        except Exception as error:  # a session start is never blocked (spec 005, FR-003)
            sys.stdout.write(could_not_run(error))
        return 0
    if args.command == "hook" and args.hook_command == "pre-tool-use":
        location = resolve_config_dir(_hook_directory(args), os.environ, Path.home())
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


def _daemon(args: argparse.Namespace) -> int:
    """Run a daemon command (spec 007)."""
    flag = _given_directory(args.config)
    if args.daemon_command in ("install", "uninstall"):
        return daemon.schedule_command(
            uninstall=args.daemon_command == "uninstall",
            dry_run=args.dry_run,
            confirm=args.confirm,
            flag=flag,
        )
    if args.daemon_command == "status":
        return daemon.status_command(flag)
    return daemon.runs_command(args.job, args.limit)


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


def _context(args: argparse.Namespace) -> int:
    """Run a context command (spec 006): 0 done, 1 a change or not confirmed, 2 an error."""
    location = resolve_config_dir(_given_directory(args.config), os.environ, Path.home())
    try:
        context = load_config(location.directory).personal_context
    except InvalidConfigError as error:
        return _context_error(
            f"the configuration has {len(error.problems)} problem(s); run opscout config validate"
        )
    except ConfigLocationError as error:
        return _context_error(str(error))
    if context is None:
        return _context_error(
            f"{config_file(location.directory)} has no personal_context section; nothing to render"
        )
    if args.context_command == "show":
        sys.stdout.write(render_block(context))
        return 0
    target = Path(args.target) if args.target else default_target(os.environ, Path.home())
    try:
        change = pending(context, target)
    except TargetError as error:
        return _context_error(str(error))
    if not change.changed:
        print(f"{target} is up to date.")
        return 0
    if args.context_command == "apply" and args.confirm is not None:
        if args.confirm.strip().lower() != change.code:
            print(
                "That code does not match the current diff: the file or the configuration "
                "changed, or the code is mistyped. Run opscout context diff again."
            )
            return 1
        return _context_write(change)
    current = change.current.decode("utf-8") if change.current is not None else ""
    sys.stdout.write(unified_diff(current, change.new.decode("utf-8"), str(target)))
    if args.context_command == "apply" and sys.stdin.isatty() and sys.stdout.isatty():
        try:
            answer = input(f"Write these changes to {target}? [y/N] ")
        except (EOFError, KeyboardInterrupt):
            answer = ""
            print()
        if answer.strip().lower() not in ("y", "yes"):
            print("Nothing was written.")
            return 1
        # The answer may come long after the diff, and Claude Code writes to this file too.
        try:
            again = pending(context, target)
        except TargetError as error:
            return _context_error(str(error))
        if again.code != change.code:
            print(
                "The file or the configuration changed while you were asked; nothing was "
                "written. Run opscout context apply again."
            )
            return 1
        return _context_write(change)
    flags = "".join(
        f" {flag} {shlex.quote(value)}"
        for flag, value in (("--config", args.config), ("--target", args.target))
        if value
    )
    print(f"\nConfirmation code: {change.code}")
    print(f"To write it: opscout context apply{flags} --confirm {change.code}")
    return 1


def _context_write(change: PendingChange) -> int:
    try:
        write(change)
    except TargetError as error:
        return _context_error(str(error))
    print(f"Wrote {change.target}.")
    return 0


def _context_error(reason: str) -> int:
    sys.stderr.write(f"opscout context: {reason}\n")
    return 2


def _hook_directory(args: argparse.Namespace) -> Path | None:
    """Return the configuration directory a hook was given, if any.

    Claude Code gives a plugin's hooks their options as CLAUDE_PLUGIN_OPTION_<KEY>; the docs
    do not say whether the key keeps its case, so both spellings are read.
    """
    lower = "CLAUDE_PLUGIN_OPTION_config_dir"
    given = args.config or os.environ.get("CLAUDE_PLUGIN_OPTION_CONFIG_DIR", os.environ.get(lower))
    return _given_directory(given)


def _sso_check(flag: Path | None) -> int:
    """Run ``opscout sso check`` (spec 005, FR-008)."""
    settings, note = sso_settings(resolve_config_dir(flag, os.environ, Path.home()))
    if not settings.enabled:
        print("The SSO check is turned off in the configuration.")
        return 0
    now = datetime.now(UTC)
    try:
        checks = check_sessions(settings, os.environ, Path.home(), now)
    except AwsConfigError as error:
        print(f"opscout: the SSO check could not run: {error}")
        return 1
    sys.stdout.write(render_status(checks, note=note))
    return 1 if any(check.needs_login for check in checks) else 0


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
