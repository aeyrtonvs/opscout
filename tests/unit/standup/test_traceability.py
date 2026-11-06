# SPDX-License-Identifier: Apache-2.0
"""Traceability of the daily standup (spec 009, FR-019)."""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SPEC_FILE = REPO_ROOT / "specs" / "009-daily-standup" / "spec.md"
TESTS = Path(__file__).parent


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 009."""
    return pytest.mark.spec("009", requirement)


@spec("FR-019")
def test_every_requirement_has_a_test() -> None:
    required = set(re.findall(r"\*\*(FR-\d{3})\*\*", SPEC_FILE.read_text(encoding="utf-8")))
    proven: set[str] = set()
    for path in TESTS.glob("test_*.py"):
        proven |= set(re.findall(r'@spec\("(FR-\d{3})"\)', path.read_text(encoding="utf-8")))

    assert required, "no requirement found in the spec"
    assert sorted(required - proven) == []
    assert sorted(proven - required) == []


@spec("FR-020")
def test_the_week_after_merge_is_an_open_item_in_the_plan() -> None:
    plan = (REPO_ROOT / "docs" / "PLAN.md").read_text(encoding="utf-8")
    open_items = plan.split("## 9. Open items", 1)[1]
    assert "daily standup" in open_items.lower()
    assert "agreement" in open_items
