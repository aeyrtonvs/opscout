# SPDX-License-Identifier: Apache-2.0
"""The ``opscout`` command line."""

import argparse
from collections.abc import Sequence

from opscout import __version__


def build_parser() -> argparse.ArgumentParser:
    """Return the parser for the ``opscout`` command."""
    parser = argparse.ArgumentParser(
        prog="opscout",
        description="Read-only Claude Code agents for the repetitive parts of DevOps work.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line and return its exit code."""
    parser = build_parser()
    parser.parse_args(argv)
    parser.print_help()
    return 0
