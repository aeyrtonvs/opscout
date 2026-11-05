# SPDX-License-Identifier: Apache-2.0
"""What the SSO check reads and reports (spec 005)."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final, Literal

MAX_CACHE_BYTES: Final = 64 * 1024
"""A token cache file above this size is not read."""

MAX_CONFIG_BYTES: Final = 1024 * 1024
"""An AWS config file above this size is not read."""

CONFIG_FILE: Final = (".aws", "config")
"""The AWS config, under the home directory, unless ``AWS_CONFIG_FILE`` names another."""

CACHE_DIRECTORY: Final = (".aws", "sso", "cache")
"""Where the AWS CLI v2 caches SSO tokens, under the home directory."""

SessionKind = Literal["sso-session", "profile"]
"""An ``[sso-session <name>]`` section, or an older profile with its own start URL."""


class AwsConfigError(Exception):
    """The AWS config cannot be read or parsed, so no session can be checked."""


class SessionState(StrEnum):
    """What the cache says about one SSO login."""

    VALID = "valid"
    EXPIRED = "expired"
    NOT_LOGGED_IN = "not-logged-in"
    UNREADABLE = "unreadable"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class SsoSession:
    """One SSO login the AWS config defines, and the name of its cache file."""

    name: str
    kind: SessionKind
    cache_key: str


@dataclass(frozen=True)
class AwsSso:
    """The SSO logins in an AWS config, and the login each profile uses."""

    sessions: tuple[SsoSession, ...]
    profiles: Mapping[str, SsoSession]


@dataclass(frozen=True)
class SessionCheck:
    """One login's state. It never holds a cache value other than the expiry."""

    name: str
    kind: SessionKind | None
    state: SessionState
    expires_at: datetime | None = None
    reason: str | None = None

    @property
    def needs_login(self) -> bool:
        """Return True unless the cached token is valid."""
        return self.state is not SessionState.VALID
