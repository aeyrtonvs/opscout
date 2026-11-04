# SPDX-License-Identifier: Apache-2.0
"""What the push guard reads and decides (spec 004)."""

from dataclasses import dataclass
from typing import Final, Literal

ALWAYS_PROTECTED: Final = ("main", "master")
"""Protected whatever the configuration says; so is the remote's default branch."""

DEFAULT_REMOTE: Final = "origin"


@dataclass(frozen=True)
class PushDecision:
    """The guard's answer: ask the user, or deny with the reason shown to Claude."""

    verdict: Literal["ask", "deny"]
    reason: str


@dataclass(frozen=True)
class PushCommand:
    """A plain ``git [-C dir] push`` the guard can read with certainty."""

    directory: str | None
    remote: str | None
    refspecs: tuple[str, ...]
    delete: bool = False
    force: bool = False
