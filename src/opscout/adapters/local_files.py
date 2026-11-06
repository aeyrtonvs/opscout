# SPDX-License-Identifier: Apache-2.0
"""Reads infrastructure code from local clones, never outside them (spec 012, research R6).

Paths are resolved, symbolic links included, and anything that leaves the clone is refused.
Version-control and tool caches are not walked; large, binary and undecodable files read as
nothing.
"""

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Final

from opscout.core.triage import SKIPPED_DIRECTORIES

MAX_FILES: Final = 20_000
MAX_BYTES: Final = 1_000_000


class LocalFiles:
    """Implements ``FileReader`` on the local file system."""

    def exists(self, root: str) -> bool:
        """Whether the clone is an existing directory."""
        return Path(root).is_dir()

    def files(self, root: str) -> Iterator[str]:
        """Relative paths of the files under the clone, in a stable order."""
        base = Path(root)
        count = 0
        for directory, subdirectories, names in os.walk(base, followlinks=False):
            subdirectories[:] = sorted(
                d for d in subdirectories if d.casefold() not in SKIPPED_DIRECTORIES
            )
            for name in sorted(names):
                count += 1
                if count > MAX_FILES:
                    return
                yield (Path(directory) / name).relative_to(base).as_posix()

    def resolve(self, root: str, relative: str) -> str | None:
        """The path relative to the clone once resolved, or None when it leaves it."""
        if Path(relative).is_absolute():
            return None
        base = Path(root).resolve()
        target = (base / relative).resolve()
        if not target.is_relative_to(base):
            return None
        return target.relative_to(base).as_posix()

    def read_text(self, root: str, relative: str) -> str | None:
        """The file's text, or None when it is missing, large, binary or not UTF-8."""
        path = Path(root).resolve() / relative
        try:
            if not path.is_file() or path.stat().st_size > MAX_BYTES:
                return None
            data = path.read_bytes()
        except OSError:
            return None
        if b"\x00" in data[:8192]:
            return None
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return None
