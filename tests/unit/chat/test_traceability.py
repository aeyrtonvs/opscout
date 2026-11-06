# SPDX-License-Identifier: Apache-2.0
"""Traceability and architecture of chat output (spec 008, FR-022, FR-023)."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SPEC_FILE = REPO_ROOT / "specs" / "008-chat-output" / "spec.md"
TESTS = Path(__file__).parent


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 008."""
    return pytest.mark.spec("008", requirement)


@spec("FR-023")
def test_every_requirement_has_a_test() -> None:
    required = set(re.findall(r"\*\*(FR-\d{3})\*\*", SPEC_FILE.read_text(encoding="utf-8")))
    proven: set[str] = set()
    for path in TESTS.glob("test_*.py"):
        proven |= set(re.findall(r'@spec\("(FR-\d{3})"\)', path.read_text(encoding="utf-8")))

    assert required, "no requirement found in the spec"
    assert sorted(required - proven) == []
    assert sorted(proven - required) == []


@spec("FR-022")
def test_the_chat_adapter_is_built_only_by_the_composition_root() -> None:
    adapter = REPO_ROOT / "src" / "opscout" / "adapters" / "slack.py"
    assert adapter.is_file(), "the Slack adapter lives under opscout.adapters"
    importers = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in (REPO_ROOT / "src" / "opscout").rglob("*.py")
        if re.search(r"opscout\.adapters\.slack|from opscout\.adapters import slack",
                     path.read_text(encoding="utf-8"))
    ]  # fmt: skip
    assert importers == ["src/opscout/entrypoints/daemon.py"]
    program = shutil.which("lint-imports")
    assert program is not None
    result = subprocess.run(  # noqa: S603  (a fixed program)
        [program], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout
