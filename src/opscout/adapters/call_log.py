# SPDX-License-Identifier: Apache-2.0
"""The tool server's call log: one JSON line per call (spec 011, research R11).

It holds the time, the tool, the environment, the outcome, the duration and the redaction
counts, never a call's arguments or output, which can carry private text. A log that cannot
be written never fails a call.
"""

import json
import logging
from pathlib import Path

from platformdirs import user_state_path

from opscout.core.aws import CallEntry

logger = logging.getLogger(__name__)


class JsonlCallLog:
    """Appends each call to ``mcp-calls.jsonl`` in the platform state directory."""

    def __init__(self, directory: Path | None = None) -> None:
        self._file = (directory or user_state_path("opscout")) / "mcp-calls.jsonl"

    def append(self, entry: CallEntry) -> None:
        """Record the call; never raises."""
        line = {
            "time": entry.time.isoformat(),
            "tool": entry.tool,
            "environment": entry.environment,
            "outcome": entry.outcome,
            "duration_ms": entry.duration_ms,
            "redacted": dict(entry.redacted),
        }
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            with self._file.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(line) + "\n")
        except OSError as error:
            logger.warning("the call log could not be written: %s", error.strerror)
