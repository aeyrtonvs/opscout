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
    schema_text,
)
from opscout.entrypoints.config import config_file, load_config
from opscout.services.config import resolve_config_dir


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
    parser.print_help()
    return 0


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
