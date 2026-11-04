# SPDX-License-Identifier: Apache-2.0
"""Resolve the write-up formats and print them as instructions for the skill (spec 003)."""

import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from opscout.core.config import WriteupFormat, Writeups
from opscout.core.writeups import BUILT_IN_FORMATS, SHARED_RULES

TITLE = "# Write-up formats"


@dataclass(frozen=True)
class ResolvedFormat:
    """A format with its name, and whether it is built-in or configured."""

    name: str
    origin: Literal["built-in", "configured"]
    format: WriteupFormat
    shared_rules: tuple[str, ...] = ()


def resolve_formats(writeups: Writeups) -> tuple[ResolvedFormat, ...]:
    """Apply the configured formats to the built-in ones (FR-006).

    A configured format replaces the built-in format of its name, in the built-in's place;
    the other configured formats follow the built-in ones, by name.
    """
    shared = tuple(writeups.rules)
    resolved = [
        ResolvedFormat(name, "configured", writeups.formats[name], shared)
        if name in writeups.formats
        else ResolvedFormat(name, "built-in", built_in, shared)
        for name, built_in in BUILT_IN_FORMATS.items()
    ]
    resolved += [
        ResolvedFormat(name, "configured", writeups.formats[name], shared)
        for name in sorted(writeups.formats)
        if name not in BUILT_IN_FORMATS
    ]
    return tuple(resolved)


def render_formats(
    formats: tuple[ResolvedFormat, ...], *, source: str, language: str | None
) -> str:
    """Return the formats as plain Markdown instructions; the same input, the same text."""
    lines = [TITLE, "", source]
    if language is not None:
        lines.append(f"Language: {language}")
    shared = formats[0].shared_rules if formats else ()
    lines += ["", "## Rules for every format", *(f"- {rule}" for rule in (*SHARED_RULES, *shared))]
    for resolved in formats:
        shape = resolved.format
        lines += ["", f"## {resolved.name} ({resolved.origin})", shape.description]
        if shape.sections:
            lines.append(f"Sections, in order: {'; '.join(shape.sections)}")
        if shape.max_lines is not None:
            lines.append(f"At most {shape.max_lines} lines.")
        if shape.rules:
            lines += ["Rules:", *(f"- {rule}" for rule in shape.rules)]
    return "\n".join(lines) + "\n"


def render_invalid(directory: Path, problems: int) -> str:
    """Return the text printed instead of the formats when the configuration is invalid."""
    return (
        f"{TITLE}\n\n"
        f"The configuration in {directory} has {problems} problem(s), so no write-up format "
        "is available.\n"
        f"Run `opscout config validate --config {shlex.quote(str(directory))}` to list them.\n"
    )
