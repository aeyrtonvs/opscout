# SPDX-License-Identifier: Apache-2.0
"""Traceability of alert triage (spec 012, FR-027).

Every requirement is proven by a test in this directory marked with it, or by an eval case
whose ``tags`` name it. Every acceptance scenario has an eval case named after it
(``012-us<n>-s<m>``), or is listed in ``SCENARIOS_PROVEN_BY_TESTS`` with the requirement
whose tests prove it.
"""

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
SPEC_FILE = REPO_ROOT / "specs" / "012-alert-triage" / "spec.md"
EVALS = REPO_ROOT / "plugins" / "opscout" / "evals"
TESTS = Path(__file__).parent

SCENARIOS_PROVEN_BY_TESTS = {
    "012-us3-s4": "FR-026",  # the CLI lists and shows records (test_cli.py)
}


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 012."""
    return pytest.mark.spec("012", requirement)


def _eval_tags() -> dict[str, set[str]]:
    tags: dict[str, set[str]] = {}
    for prompt in sorted(EVALS.glob("012-*/prompt.md")):
        front = yaml.safe_load(prompt.read_text(encoding="utf-8").split("---\n", 2)[1]) or {}
        tags[prompt.parent.name] = set(front.get("tags", []))
    return tags


def _scenarios() -> set[str]:
    text = SPEC_FILE.read_text(encoding="utf-8")
    found: set[str] = set()
    for story, body in re.findall(
        r"### User Story (\d+) - .*?\n(.*?)(?=\n### |\n## )", text, flags=re.S
    ):
        for number in re.findall(r"^(\d+)\. \*\*Given\*\*", body, flags=re.M):
            found.add(f"012-us{story}-s{number}")
    return found


@pytest.mark.xfail(strict=True, reason="until T050, when every case exists")
@spec("FR-027")
def test_every_requirement_has_a_test_or_an_eval_case() -> None:
    required = set(re.findall(r"\*\*(FR-\d{3})\*\*", SPEC_FILE.read_text(encoding="utf-8")))
    proven: set[str] = set()
    for path in TESTS.glob("test_*.py"):
        proven |= set(re.findall(r'@spec\("(FR-\d{3})"\)', path.read_text(encoding="utf-8")))
    for tags in _eval_tags().values():
        proven |= {tag for tag in tags if tag.startswith("FR-")}

    assert required, "no requirement found in the spec"
    assert sorted(required - proven) == []
    assert sorted(proven - required) == []


@pytest.mark.xfail(strict=True, reason="until T050, when every case exists")
@spec("FR-027")
def test_every_scenario_has_an_eval_case() -> None:
    scenarios = _scenarios()
    cases = set(_eval_tags())

    def of(case: str) -> str | None:
        return next((s for s in scenarios if case == s or case.startswith(f"{s}-")), None)

    covered = {of(case) for case in cases}
    assert len(scenarios) == 22
    assert sorted(scenarios - covered - set(SCENARIOS_PROVEN_BY_TESTS)) == []
    assert sorted(case for case in cases if of(case) is None) == []
