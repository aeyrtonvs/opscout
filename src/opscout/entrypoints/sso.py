# SPDX-License-Identifier: Apache-2.0
"""Read the AWS config and the SSO token cache for the check (spec 005).

Only two kinds of file are opened, for reading and with a size limit: the AWS config and the
cache file of each checked login. Nothing is written, no program is run and the network is
never used (FR-007).
"""

import os
import stat
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

from opscout.core.config import ConfigLocationError, InvalidConfigError, Sso
from opscout.core.sso import (
    CACHE_DIRECTORY,
    CONFIG_FILE,
    MAX_CACHE_BYTES,
    MAX_CONFIG_BYTES,
    AwsConfigError,
    AwsSso,
    SessionCheck,
    SessionState,
)
from opscout.entrypoints.config import load_config
from opscout.services.config import ConfigLocation, Source
from opscout.services.sso import find_sessions, judge, select


class _UnreadableError(Exception):
    """A file exists but cannot be used; the message says why, never what it holds."""


def sso_settings(location: ConfigLocation) -> tuple[Sso, str | None]:
    """Return the configured SSO settings, or the defaults and why the configuration is unused."""
    try:
        return load_config(location.directory).sso, None
    except InvalidConfigError as error:
        count = len(error.problems)
        plural = "" if count == 1 else "s"
        return Sso(), f"it has {count} problem{plural}; run opscout config validate"
    except ConfigLocationError as error:
        # Nothing at the default place is fine; a directory the user named must be usable.
        return Sso(), None if location.source is Source.DEFAULT else str(error)


def check_sessions(
    settings: Sso, environ: Mapping[str, str], home: Path, now: datetime
) -> list[SessionCheck]:
    """Return the state of every login the settings select. Raises ``AwsConfigError``."""
    if not settings.enabled:
        return []
    given = environ.get("AWS_CONFIG_FILE")
    # The AWS CLI expands variables and ~ in AWS_CONFIG_FILE.
    path = Path(os.path.expandvars(given)).expanduser() if given else home.joinpath(*CONFIG_FILE)
    try:
        text = _read(path, MAX_CONFIG_BYTES)
    except _UnreadableError as error:
        raise AwsConfigError(f"the AWS config cannot be read ({error})") from None
    found = find_sessions(text) if text is not None else AwsSso(sessions=(), profiles={})
    cache = home.joinpath(*CACHE_DIRECTORY)
    checks: list[SessionCheck] = []
    for session in select(found, settings):
        if isinstance(session, str):
            checks.append(SessionCheck(session, None, SessionState.UNKNOWN))
            continue
        try:
            token = _read(cache / f"{session.cache_key}.json", MAX_CACHE_BYTES)
        except _UnreadableError as error:
            checks.append(
                SessionCheck(session.name, session.kind, SessionState.UNREADABLE, reason=str(error))
            )
            continue
        checks.append(judge(session, token, now))
    return checks


def _read(path: Path, limit: int) -> str | None:
    """Return a file's text, None when it does not exist, or raise ``_UnreadableError``.

    The file is opened without blocking and must be a regular file, so a named pipe or a
    device at the path cannot hold the session start.
    """
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError as error:
        raise _UnreadableError(f"it cannot be read ({type(error).__name__})") from None
    with os.fdopen(descriptor, "rb") as file:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise _UnreadableError("not a regular file")
        try:
            data = file.read(limit + 1)
        except OSError as error:
            raise _UnreadableError(f"it cannot be read ({type(error).__name__})") from None
    if len(data) > limit:
        size = f"{limit // 1024 // 1024} MiB" if limit >= 1024 * 1024 else f"{limit // 1024} KiB"
        raise _UnreadableError(f"larger than {size}")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise _UnreadableError("not UTF-8") from None
