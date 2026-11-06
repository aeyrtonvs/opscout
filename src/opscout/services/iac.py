# SPDX-License-Identifier: Apache-2.0
"""Infrastructure code, read only and confined to the configured clones (spec 012, R6).

``search`` finds a literal, case-insensitively, in the clones that serve an environment
first; ``read`` returns up to 200 numbered lines of one file. A path is ``<clone>/<path>``;
once resolved it must stay inside its clone, symbolic links included. Version-control and
tool caches, state files, ``.env`` files, keys and binary files are never read. The tool
runtime redacts every result like any other (FR-009).
"""

import fnmatch
from pathlib import PurePosixPath
from typing import Any, Final

from opscout.core.config import Configuration, InfrastructureClone
from opscout.core.tools import ErrorReason, ToolError
from opscout.core.triage import SKIPPED_DIRECTORIES, FileReader

MAX_MATCHES: Final = 50
MAX_LINES: Final = 200
MAX_LINE_CHARS: Final = 300
SKIPPED_FILES: Final = ("*.tfstate", "*.tfstate.*", ".env", ".env.*", "*.pem", "*.key")


def _clones(config: Configuration | None) -> list[InfrastructureClone]:
    clones = config.triage.infrastructure if config and config.triage else []
    if not clones:
        raise ToolError(ErrorReason.NOT_CONFIGURED, "no infrastructure clone is configured")
    return list(clones)


def _skipped(relative: str) -> bool:
    path = PurePosixPath(relative)
    if any(part in SKIPPED_DIRECTORIES for part in path.parts[:-1]):
        return True
    return any(fnmatch.fnmatch(path.name, pattern) for pattern in SKIPPED_FILES)


def _serves(clone: InfrastructureClone, environment: str | None) -> bool:
    return clone.environments is None or environment in clone.environments


def search(
    config: Configuration | None,
    files: FileReader | None,
    pattern: str,
    *,
    environment: str | None,
    clone: str | None,
) -> dict[str, Any]:
    """Every line holding ``pattern``, the environment's clones first, at most 50."""
    clones = _clones(config)
    if files is None:
        raise ToolError(ErrorReason.NOT_CONFIGURED, "file reading is not available")
    if clone is not None:
        clones = [c for c in clones if c.name == clone]
        if not clones:
            raise ToolError(ErrorReason.INVALID_INPUT, "no configured clone has that name")
    elif environment is not None:
        clones = [c for c in clones if _serves(c, environment)]
    clones.sort(key=lambda c: c.environments is None)
    needle = pattern.casefold()
    matches: list[dict[str, Any]] = []
    searched: list[str] = []
    missing: list[str] = []
    more = False
    for entry in clones:
        if not files.exists(entry.path):
            missing.append(entry.name)
            continue
        searched.append(entry.name)
        for relative in files.files(entry.path):
            if more:
                break
            if _skipped(relative) or files.resolve(entry.path, relative) != relative:
                continue
            text = files.read_text(entry.path, relative)
            if text is None:
                continue
            for number, line in enumerate(text.splitlines(), start=1):
                if needle in line.casefold():
                    if len(matches) == MAX_MATCHES:
                        more = True
                        break
                    matches.append(
                        {
                            "clone": entry.name,
                            "path": f"{entry.name}/{relative}",
                            "line": number,
                            "text": line.strip()[:MAX_LINE_CHARS],
                        }
                    )
    return {"matches": matches, "searched": searched, "missing": missing, "more": more}


def read(
    config: Configuration | None, files: FileReader | None, path: str, start: int, end: int
) -> dict[str, Any]:
    """Lines ``start`` to ``end`` of one file in a clone, numbered from 1."""
    clones = {c.name: c for c in _clones(config)}
    if files is None:
        raise ToolError(ErrorReason.NOT_CONFIGURED, "file reading is not available")
    name, _, relative = path.partition("/")
    entry = clones.get(name)
    if entry is None:
        raise ToolError(ErrorReason.INVALID_INPUT, "the path must start with a clone's name")
    if not relative or not 1 <= start <= end or end - start >= MAX_LINES:
        raise ToolError(
            ErrorReason.INVALID_INPUT, f"give a file and at most {MAX_LINES} lines, from 1"
        )
    resolved = files.resolve(entry.path, relative)
    if resolved is None:
        raise ToolError(ErrorReason.INVALID_INPUT, "the path leaves its clone")
    if _skipped(resolved) or _skipped(relative):
        raise ToolError(ErrorReason.INVALID_INPUT, "this kind of file is never read")
    text = files.read_text(entry.path, resolved)
    if text is None:
        raise ToolError(ErrorReason.INVALID_INPUT, "the file is missing, binary or unreadable")
    lines = text.splitlines()
    return {
        "clone": name,
        "path": f"{name}/{resolved}",
        "lines": [
            {"line": number, "text": lines[number - 1][:MAX_LINE_CHARS]}
            for number in range(start, min(end, len(lines)) + 1)
        ],
        "total_lines": len(lines),
    }
