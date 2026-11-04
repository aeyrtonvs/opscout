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
    Writeups,
    schema_text,
)
from opscout.entrypoints.config import config_file, load_config
from opscout.services.config import resolve_config_dir
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
    parser.print_help()
    return 0


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
