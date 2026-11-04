# SPDX-License-Identifier: Apache-2.0
"""PostToolUse hook: ruff fixes and formats each Python file the agent edits (ADR-0018).

What ruff cannot fix is sent back to the agent next to the tool result. Files outside the
project, and files the ruff configuration excludes, are left alone.
"""

import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from tools.hooks._protocol import Decision, Event, Result, run_hook

PYTHON_SUFFIXES = frozenset({".py", ".pyi"})
Ruff = Callable[[Sequence[str]], Result]


def decide(event: Event, project_dir: Path, ruff: Ruff) -> Decision | None:
    """Fix, format and check the edited file; report what is left, if anything."""
    file_path = event.get("tool_input", {}).get("file_path")
    if not isinstance(file_path, str):
        return None
    path = Path(file_path)
    if (
        path.suffix not in PYTHON_SUFFIXES
        or not path.is_file()
        or not path.resolve().is_relative_to(project_dir.resolve())
    ):
        return None
    ruff(["format", "--force-exclude", str(path)])
    ruff(["check", "--fix", "--force-exclude", str(path)])
    remaining = ruff(["check", "--force-exclude", "--output-format", "concise", str(path)])
    if remaining.returncode == 0:
        return None
    return {
        "decision": "block",
        "reason": (
            f"ruff formatted {path.name} and fixed what it could. "
            f"Fix what is left:\n{remaining.output.strip()}"
        ),
    }


def run_ruff(arguments: Sequence[str], project_dir: Path) -> Result:
    """Run the ruff that uv.lock pins, from the project directory."""
    completed = subprocess.run(  # noqa: S603  # fixed program, arguments built above
        [sys.executable, "-m", "ruff", *arguments],
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
    return run_hook(
        lambda event: decide(event, project_dir, lambda args: run_ruff(args, project_dir))
    )


if __name__ == "__main__":
    raise SystemExit(main())
