# SPDX-License-Identifier: Apache-2.0
"""The fixture gateway: mock mode's answers to AWS calls (spec 011, FR-025 to FR-027; R5).

Each action of each environment has a file, ``<root>/<environment>/<prefix>/<Action>.json``,
holding a list of entries: ``{"match": {...}, "response": {...}}`` or ``{"match": {...},
"error": {"reason": ..., "fix": ...}}``. The first entry whose ``match`` is a subset of the
call's parameters answers. Nothing ever falls back to AWS. Timestamps written as ISO 8601
become datetimes, as botocore returns them.
"""

import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from opscout.core.config import AwsEnvironment
from opscout.core.tools import ErrorReason, ToolError


def _matches(expected: object, given: object) -> bool:
    if isinstance(expected, Mapping):
        return isinstance(given, Mapping) and all(
            key in given and _matches(value, given[key]) for key, value in expected.items()
        )
    return expected == given


def _times(value: Any) -> Any:
    if isinstance(value, str) and len(value) >= 20 and value[10:11] == "T":
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return value
        return parsed if parsed.tzinfo is not None else value
    if isinstance(value, Mapping):
        return {key: _times(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_times(item) for item in value]
    return value


class FixtureGateway:
    """Answers declared AWS read actions from a fixtures directory."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def call(
        self,
        environment: AwsEnvironment,
        region: str,
        action: str,
        params: Mapping[str, Any],
        allowed: frozenset[str],
        remaining: float,
    ) -> Mapping[str, Any]:
        """Return the first matching fixture's response (FR-025)."""
        if action not in allowed:
            raise ToolError(ErrorReason.UNDECLARED_ACTION, action)
        prefix, operation = action.split(":", 1)
        relative = f"{environment.name}/{prefix}/{operation}.json"
        given = json.dumps(params, sort_keys=True, default=str)
        try:
            entries = json.loads((self._root / relative).read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise ToolError(ErrorReason.FIXTURE_MISSING, f"{relative} for {given}") from None
        for entry in entries:
            if _matches(entry.get("match", {}), params):
                if "error" in entry:
                    error = entry["error"]
                    raise ToolError(
                        ErrorReason(error["reason"]),
                        error.get("message", relative),
                        fix=error.get("fix"),
                    )
                response: Mapping[str, Any] = _times(entry["response"])
                return response
        raise ToolError(ErrorReason.FIXTURE_MISSING, f"{relative} has no entry for {given}")
