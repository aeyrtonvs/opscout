# SPDX-License-Identifier: Apache-2.0
"""Traceability and architecture of the daemon core (spec 007, FR-025, FR-026)."""

import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SPEC_FILE = REPO_ROOT / "specs" / "007-daemon-core" / "spec.md"
TESTS = Path(__file__).parent


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 007."""
    return pytest.mark.spec("007", requirement)


@spec("FR-026")
def test_every_requirement_has_a_test() -> None:
    required = set(re.findall(r"\*\*(FR-\d{3})\*\*", SPEC_FILE.read_text(encoding="utf-8")))
    proven: set[str] = set()
    for path in TESTS.glob("test_*.py"):
        proven |= set(re.findall(r'@spec\("(FR-\d{3})"\)', path.read_text(encoding="utf-8")))

    assert required, "no requirement found in the spec"
    assert sorted(required - proven) == []
    assert sorted(proven - required) == []


@spec("FR-025")
def test_only_the_composition_root_imports_adapters() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    contracts = pyproject["tool"]["importlinter"]["contracts"]
    forbidden = [contract for contract in contracts if contract["type"] == "forbidden"]

    assert any(
        set(contract["source_modules"]) >= {"opscout.entrypoints.cli", "opscout.entrypoints.hook"}
        and contract["forbidden_modules"] == ["opscout.adapters"]
        and contract.get("allow_indirect_imports") is True
        for contract in forbidden
    )
    program = shutil.which("lint-imports")
    assert program is not None
    result = subprocess.run(  # noqa: S603  (a fixed program)
        [program], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout
