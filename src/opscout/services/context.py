# SPDX-License-Identifier: Apache-2.0
"""Render the personal context and splice it into a file's text (spec 006).

Everything here is pure. The block depends only on the configuration (FR-004); splicing
changes the lines from the begin marker to the end marker, or appends the block, and keeps
every other byte (FR-006).
"""

import difflib
import hashlib
import re

from opscout.core.config import MARKER_TEXT, PersonalContext
from opscout.core.context import BEGIN, END, NOTE, MarkerError, SpliceError

BOM = "\ufeff"


def render_block(context: PersonalContext) -> str:
    """Return the marked block, with ``\\n`` newlines."""
    lines = [BEGIN, NOTE, "## Personal context", ""]
    facts = []
    if context.language is not None:
        facts.append(f"- Answer in {context.language}.")
    if context.timezone is not None:
        facts.append(f"- Time zone: {context.timezone}.")
    if facts:
        lines += [*facts, ""]
    for heading, entries in (context.sections or {}).items():
        lines += [f"### {heading}", "", *(f"- {entry}" for entry in entries), ""]
    lines.pop()  # every part ends with a blank line; the end marker follows the last one
    return "\n".join([*lines, END]) + "\n"


def splice(text: str | None, block: str) -> str:
    """Return ``text`` with the block replaced, or appended after a blank line.

    Raises ``MarkerError`` when the markers are not exactly one begin before one end, each
    alone on its line.
    """
    if not text:
        return block
    newline = "\r\n" if "\r\n" in text else "\n"
    block = block.replace("\n", newline)
    lines = _lines(text)
    begin, end = _markers(lines)
    if begin is None:
        if text.endswith("\r"):
            # A newline added here would join the carriage return into a CRLF, and the next
            # run would rewrite the block with CRLF: not idempotent.
            raise SpliceError("the file ends with a bare carriage return; end it with a newline")
        ending = "" if text.endswith("\n") else newline
        return text + ending + newline + block
    if begin == 0 and lines[0].startswith(BOM):
        block = BOM + block
    return "".join([*lines[:begin], block, *lines[end + 1 :]])  # type: ignore[operator]


def _lines(text: str) -> list[str]:
    """Split on ``\\n`` only, keeping it: editors break lines there and nowhere else."""
    return [line for line in re.split(r"(?<=\n)", text) if line]


def _markers(lines: list[str]) -> tuple[int | None, int | None]:
    begin: int | None = None
    end: int | None = None
    for index, line in enumerate(lines):
        if MARKER_TEXT not in line:
            continue
        number = index + 1
        bare = line.rstrip("\r\n").removeprefix(BOM if index == 0 else "")
        if bare not in (BEGIN, END):
            raise MarkerError(f"line {number}: a marker must be alone on its line")
        if bare == BEGIN:
            if end is not None:
                raise MarkerError(f"line {number}: a second block")
            if begin is not None:
                raise MarkerError(f"line {number}: a second begin marker")
            begin = index
        else:
            if begin is None:
                raise MarkerError(
                    f"line {number}: an end marker before the begin marker"
                    if any(other.rstrip("\r\n") == BEGIN for other in lines[index:])
                    else f"line {number}: an end marker without a begin marker"
                )
            if end is not None:
                raise MarkerError(f"line {number}: a second end marker")
            end = index
    if begin is not None and end is None:
        raise MarkerError(f"line {begin + 1}: a begin marker without an end marker")
    return begin, end


def confirmation_code(current: bytes | None, new: bytes) -> str:
    """Return the code that confirms changing ``current`` into ``new``."""
    digest = hashlib.sha256()
    digest.update(b"absent" if current is None else b"present:" + current)
    digest.update(b"\x00new:")
    digest.update(new)
    return digest.hexdigest()[:12]


def unified_diff(current: str, new: str, target: str) -> str:
    """Return a unified diff from ``current`` to ``new``, naming the target."""
    lines = difflib.unified_diff(
        _lines(current), _lines(new), fromfile=target, tofile=f"{target} (opscout)"
    )
    # Like diff(1), mark a last line without a newline, so lines never run together.
    return "".join(
        line if line.endswith("\n") else f"{line}\n\\ No newline at end of file\n" for line in lines
    )
