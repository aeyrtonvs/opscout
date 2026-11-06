# SPDX-License-Identifier: Apache-2.0
"""Infrastructure code, read only and confined to the configured clones (spec 012, R6).

Placeholder until T037: both tools say they are not supported yet.
"""

from typing import Any

from opscout.core.config import Configuration
from opscout.core.tools import ErrorReason, ToolError
from opscout.core.triage import FileReader


def search(
    config: Configuration | None,
    files: FileReader | None,
    pattern: str,
    *,
    environment: str | None,
    clone: str | None,
) -> dict[str, Any]:
    """Search the clones for a literal."""
    raise ToolError(ErrorReason.NOT_SUPPORTED, "search_iac")


def read(
    config: Configuration | None, files: FileReader | None, path: str, start: int, end: int
) -> dict[str, Any]:
    """Read a slice of one file."""
    raise ToolError(ErrorReason.NOT_SUPPORTED, "read_iac")
