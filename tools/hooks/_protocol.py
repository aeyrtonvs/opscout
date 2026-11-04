# SPDX-License-Identifier: Apache-2.0
"""The hook protocol: an event as JSON on stdin, an optional decision as JSON on stdout."""

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

Event = dict[str, Any]
Decision = dict[str, Any]


@dataclass(frozen=True)
class Result:
    """The exit code and combined output of a command a hook ran."""

    returncode: int
    output: str


def run_hook(decide: Callable[[Event], Decision | None]) -> int:
    """Read the event, write the decision if there is one, and return the exit code."""
    event: Event = json.load(sys.stdin)
    decision = decide(event)
    if decision is not None:
        json.dump(decision, sys.stdout)
    return 0
