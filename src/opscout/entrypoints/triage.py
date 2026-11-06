# SPDX-License-Identifier: Apache-2.0
"""``opscout triage runs | show``: the local triage records (spec 012, FR-026).

Records live under ``<data>/triage/runs/``, where ``<data>`` is ``OPSCOUT_DATA_DIR`` or the
platform data directory, spec 007's (research R8).
"""

import os
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import platformdirs

from opscout.core.triage import TriageRecord, Unreadable
from opscout.services.triage import summarize

DATA_ENV = "OPSCOUT_DATA_DIR"


def data_directory(environ: Mapping[str, str]) -> Path:
    """``OPSCOUT_DATA_DIR``, else the platform data directory (research R2, R8)."""
    given = environ.get(DATA_ENV, "")
    if given and not given.startswith("${"):
        return Path(given)
    return Path(platformdirs.user_data_dir("opscout", appauthor=False))


def runs_command(limit: int) -> int:
    """List triage runs, newest first."""
    if limit < 1:
        sys.stderr.write("opscout triage runs: --limit must be at least 1\n")
        return 2
    from opscout.adapters.triage_files import FileRecords

    listed = FileRecords(data_directory(os.environ)).records(limit)
    if not listed:
        sys.stdout.write("no triage runs yet\n")
        return 0
    records = [entry for entry in listed if isinstance(entry, TriageRecord)]
    rows = {row["run_id"]: row for row in summarize(records, datetime.now(UTC))}
    for entry in listed:
        if isinstance(entry, Unreadable):
            sys.stdout.write(f"{entry.name}  unreadable\n")
            continue
        row = rows[entry.run_id]
        started = row["started_at"].astimezone().isoformat(timespec="minutes")
        fields = [
            row["run_id"],
            started,
            row["format"] or "-",
            row["environment"] or "-",
            row["outcome"],
            row["classification"] or "-",
            row["agreement"] or "-",
        ]
        sys.stdout.write("  ".join(fields) + "\n")
    return 0


def show_command(run_id: str) -> int:
    """Print one record as indented JSON."""
    from opscout.adapters.triage_files import FileRecords

    found = FileRecords(data_directory(os.environ)).get(run_id)
    if found is None:
        sys.stderr.write("opscout triage show: no triage run has that id\n")
        return 1
    sys.stdout.write(found.model_dump_json(indent=2) + "\n")
    return 0
