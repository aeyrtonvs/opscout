# SPDX-License-Identifier: Apache-2.0
"""Read and write the personal context's target (spec 006).

The target is one file: ``CLAUDE.md`` in Claude Code's configuration directory, or the file
``--target`` names. It is written only after a confirmation the caller has checked, in one
step through a temporary file, so a failed write leaves the old content (FR-010).
"""

import contextlib
import os
import stat
import tempfile
from collections.abc import Mapping
from pathlib import Path

from opscout.core.config import PersonalContext
from opscout.core.context import MAX_TARGET_BYTES, TARGET_NAME, PendingChange, SpliceError
from opscout.services.confirm import confirmation_code
from opscout.services.context import render_block, splice

NEW_FILE_MODE = 0o666
"""A new file's permissions before the umask, as any editor creates one."""


class TargetError(Exception):
    """The target cannot be read or written; the message names it and says why."""


def default_target(environ: Mapping[str, str], home: Path) -> Path:
    """Return ``CLAUDE.md`` in ``CLAUDE_CONFIG_DIR``, or in ``~/.claude``."""
    directory = environ.get("CLAUDE_CONFIG_DIR")
    base = Path(directory).expanduser() if directory else home / ".claude"
    return base / TARGET_NAME


def pending(context: PersonalContext, target: Path) -> PendingChange:
    """Return the change applying the context would make. Raises ``TargetError``."""
    current = _read(target)
    try:
        text = current.decode("utf-8") if current is not None else None
    except UnicodeDecodeError:
        raise TargetError(f"{target}: not UTF-8") from None
    try:
        new = splice(text, render_block(context)).encode("utf-8")
    except SpliceError as error:
        raise TargetError(f"{target}: {error}") from None
    return PendingChange(target, current, new, confirmation_code(current, new))


def write(change: PendingChange) -> None:
    """Replace the target with the change's new content in one step. Raises ``TargetError``."""
    real = change.target.resolve()
    failed = f"{change.target}: could not be written"
    try:
        real.parent.mkdir(parents=True, exist_ok=True)
        mode = stat.S_IMODE(real.stat().st_mode) if real.exists() else _new_file_mode()
        handle, temporary = tempfile.mkstemp(dir=real.parent, prefix=f".{real.name}.")
    except OSError as error:
        raise TargetError(f"{failed} ({type(error).__name__})") from None
    try:
        with os.fdopen(handle, "wb") as file:
            file.write(change.new)
            file.flush()
            os.fsync(file.fileno())
        Path(temporary).chmod(mode)
        # The last check before the move: Claude Code itself writes to this file.
        if _read(change.target) != change.current:
            raise TargetError(f"{change.target}: changed since the diff; nothing was written")
        Path(temporary).replace(real)
    except BaseException as error:
        with contextlib.suppress(OSError):
            Path(temporary).unlink()
        if isinstance(error, OSError):
            raise TargetError(f"{failed} ({type(error).__name__})") from None
        raise


def _new_file_mode() -> int:
    """Return the permissions a new file gets under the current umask."""
    umask = os.umask(0)
    os.umask(umask)
    return NEW_FILE_MODE & ~umask


def _read(target: Path) -> bytes | None:
    """Return the target's bytes, None when it does not exist; only a regular file is read."""
    try:
        descriptor = os.open(target, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
    except FileNotFoundError:
        return None
    except OSError as error:
        raise TargetError(f"{target}: cannot be read ({type(error).__name__})") from None
    with os.fdopen(descriptor, "rb") as file:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise TargetError(f"{target}: not a regular file")
        try:
            data = file.read(MAX_TARGET_BYTES + 1)
        except OSError as error:
            raise TargetError(f"{target}: cannot be read ({type(error).__name__})") from None
    if len(data) > MAX_TARGET_BYTES:
        raise TargetError(f"{target}: larger than 1 MiB")
    return data
