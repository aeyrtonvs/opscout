# SPDX-License-Identifier: Apache-2.0
"""Traceability of the read-only identity (spec 010, FR-020)."""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SPEC_FILE = REPO_ROOT / "specs" / "010-readonly-identity" / "spec.md"
TESTS = Path(__file__).parent


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 010."""
    return pytest.mark.spec("010", requirement)


@spec("FR-020")
def test_every_requirement_has_a_test() -> None:
    required = set(re.findall(r"\*\*(FR-\d{3})\*\*", SPEC_FILE.read_text(encoding="utf-8")))
    proven: set[str] = set()
    for path in TESTS.glob("test_*.py"):
        proven |= set(re.findall(r'@spec\("(FR-\d{3})"\)', path.read_text(encoding="utf-8")))

    assert required, "no requirement found in the spec"
    assert sorted(required - proven) == []
    assert sorted(proven - required) == []


@spec("FR-021")
def test_the_live_check_is_recorded_and_what_it_left_out_is_open() -> None:
    plan = (REPO_ROOT / "docs" / "PLAN.md").read_text(encoding="utf-8")
    spec = (REPO_ROOT / "specs" / "010-readonly-identity" / "spec.md").read_text(encoding="utf-8")
    open_items = plan.split("## 9. Open items", 1)[1]
    assert "- [x] Read-only identity, live check (spec 010, FR-021)" in open_items
    assert "- [ ] Live check of the host identity and the clusters (spec 010, FR-021)" in open_items
    assert "docs/reference/identity.md" in open_items
    assert "**The live check (FR-021), 2026-11-06**" in spec.split("## Actuals", 1)[1]
