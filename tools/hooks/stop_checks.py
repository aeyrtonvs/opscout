# SPDX-License-Identifier: Apache-2.0
"""Stop hook: the fast checks run before the agent stops, and block the stop once (ADR-0018).

``stop_hook_active`` is true when the agent is already continuing because of a stop hook.
The second stop is then let through, so the agent reports the failure to the maintainer
instead of looping (AGENTS.md: "if the same check fails twice ... stop"). The checks run
again on that stop, and if they still fail the maintainer sees a warning.
"""

import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from tools.hooks._protocol import Decision, Event, Result, run_hook

MAX_REPORT_CHARS = 6000


def decide(event: Event, checks: Callable[[], Result]) -> Decision | None:
    """Block the first stop while the fast checks fail; on the next one, only warn."""
    result = checks()
    if result.returncode == 0:
        return None
    report = result.output.strip()
    if len(report) > MAX_REPORT_CHARS:
        report = "...\n" + report[-MAX_REPORT_CHARS:]
    if event.get("stop_hook_active"):
        return {
            "systemMessage": "The fast checks (`uv run just fast`) still fail after one retry:\n"
            + report
        }
    return {
        "decision": "block",
        "reason": (
            "The fast checks (`uv run just fast`) failed. If your changes caused it, fix it. "
            "If they did not, or you cannot fix it, stop and show the maintainer the error.\n"
            + report
        ),
    }


def run_fast_checks(project_dir: Path) -> Result:
    """Run ``just fast`` from the project directory."""
    just = shutil.which("just")
    if just is None:
        return Result(127, "`just` was not found. Run `uv sync` to install the toolchain.")
    completed = subprocess.run(  # noqa: S603  # fixed program and arguments
        [just, "fast"],
        cwd=project_dir,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return Result(completed.returncode, completed.stdout + completed.stderr)


def main() -> int:
    """Run the hook for the project Claude Code names."""
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", "."))
    return run_hook(lambda event: decide(event, lambda: run_fast_checks(project_dir)))


if __name__ == "__main__":
    raise SystemExit(main())
