# SPDX-License-Identifier: Apache-2.0
"""Triage records, as files under the data directory (spec 012, research R8).

One record per run at ``<data>/triage/runs/<run-id>.json``, written to a temporary file in
the same directory and moved into place, as spec 007's records are. The run id starts with
its UTC start time, so the names sort by time.
"""

import contextlib
import os
import re
import tempfile
from pathlib import Path

from pydantic import ValidationError

from opscout.core.triage import RUN_ID_PATTERN, TriageRecord, Unreadable

_RUN_ID = re.compile(RUN_ID_PATTERN)


class FileRecords:
    """Implements ``TriageStore`` on one JSON file per run."""

    def __init__(self, data: Path) -> None:
        self._directory = data / "triage" / "runs"

    def write(self, record: TriageRecord) -> None:
        """Write the record atomically; raises ``OSError`` when it cannot."""
        self._directory.mkdir(parents=True, exist_ok=True)
        name = f"{record.run_id}.json"
        handle, temporary = tempfile.mkstemp(dir=self._directory, prefix=f".{name}.")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as file:
                file.write(record.model_dump_json(indent=2))
                file.flush()
                os.fsync(file.fileno())
            Path(temporary).replace(self._directory / name)
        except BaseException:
            with contextlib.suppress(OSError):
                Path(temporary).unlink()
            raise

    def get(self, run_id: str) -> TriageRecord | None:
        """The record, or None when absent, unreadable or not a run id."""
        if not _RUN_ID.fullmatch(run_id):
            return None
        found = self._read(self._directory / f"{run_id}.json")
        return found if isinstance(found, TriageRecord) else None

    def records(self, limit: int) -> list[TriageRecord | Unreadable]:
        """The newest records first; an unreadable one is listed by its name."""
        if not self._directory.is_dir():
            return []
        paths = sorted(self._directory.glob("*.json"), key=lambda p: p.name, reverse=True)
        return [self._read(path) for path in paths[:limit]]

    @staticmethod
    def _read(path: Path) -> TriageRecord | Unreadable:
        try:
            return TriageRecord.model_validate_json(path.read_bytes())
        except (OSError, ValidationError, ValueError):
            return Unreadable(path.name)
