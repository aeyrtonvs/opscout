# SPDX-License-Identifier: Apache-2.0
"""``opscout identity check | export``: the read-only identity's documents (spec 010).

Both commands work offline and only read, except that ``export`` writes the editable
reference into a directory that does not hold those files yet.
"""

import sys
from pathlib import Path

from opscout.adapters.identity_files import TreeError, export_tree, load_records, read_tree
from opscout.core.identity import Report
from opscout.services.identity import prove

PLACEHOLDERS = (
    "Fill the placeholders: the account 123456789012, the cluster example-prod, the role "
    "opscout-readonly and the group opscout:readonly. Leave out what your environment does "
    "not use: aws/readonly/capabilities/cluster.json, aws/hosts/ with ssm/, eks/ and "
    "kubernetes/."
)


def _print(report: Report) -> int:
    for line in report.summary:
        sys.stdout.write(f"{line}\n")
    for finding in report.findings:
        sys.stdout.write(f"{finding}\n")
    if report.passed:
        sys.stdout.write("Pass.\n")
        return 0
    count = len(report.findings)
    sys.stdout.write(f"Fail: {count} finding{'s' if count != 1 else ''}.\n")
    return 1


def check_command(directory: Path | None) -> int:
    """Prove a tree, or the packaged reference when ``directory`` is ``None``."""
    records = load_records()
    try:
        tree = records.reference if directory is None else read_tree(directory)
    except TreeError as error:
        sys.stderr.write(f"opscout identity check: {error}\n")
        return 2
    return _print(prove(tree, records))


def export_command(directory: Path) -> int:
    """Write the editable reference tree into ``directory``."""
    try:
        written = export_tree(directory)
    except TreeError as error:
        sys.stderr.write(f"opscout identity export: {error}\n")
        return 2
    sys.stdout.write(f"Wrote {len(written)} files to {directory}:\n")
    for relative in written:
        sys.stdout.write(f"  {relative}\n")
    sys.stdout.write(f"{PLACEHOLDERS}\nThen run: opscout identity check {directory}\n")
    return 0
