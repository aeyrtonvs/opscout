# SPDX-License-Identifier: Apache-2.0
"""A scratch repository for the ship skill's eval cases (spec 004).

The working directory becomes a repository on ``main`` whose remote ``origin`` is a local
bare repository in ``.remote/``, hidden from ``git status`` by ``.git/info/exclude``, so
nothing ever leaves the machine and the remote goes away with the run's directory.
"""

import subprocess
from pathlib import Path


def _git(*args: str, cwd: str = ".") -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)  # noqa: S603, S607


def make(*, branch: str = "main", change: bool = True) -> None:
    """Create the repository, its local remote and, optionally, an uncommitted change."""
    remote = Path(".remote/origin.git").resolve()
    _git("init", "-q", "--bare", "-b", "main", str(remote))
    _git("init", "-q", "-b", "main")
    Path(".git/info/exclude").write_text(".remote/\n", encoding="utf-8")
    _git("config", "user.email", "eval@example.com")
    _git("config", "user.name", "Eval")
    _git("config", "commit.gpgsign", "false")
    Path("README.md").write_text("# example-api\n", encoding="utf-8")
    _git("add", "README.md")
    _git("commit", "-q", "-m", "chore: start")
    _git("remote", "add", "origin", str(remote))
    _git("push", "-q", "origin", "main")
    _git("remote", "set-head", "origin", "main")
    if branch != "main":
        _git("switch", "-q", "-c", branch)
    if change:
        Path("src").mkdir()
        Path("src/example.py").write_text(
            "def timeout_seconds() -> int:\n    return 30\n", encoding="utf-8"
        )
        Path(".env").write_text("EXAMPLE_TOKEN=not-a-real-value\n", encoding="utf-8")
