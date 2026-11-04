# SPDX-License-Identifier: Apache-2.0
"""The ship skill: conventions, checks, the push guard, the skill (spec 004).

Every test is tied to its requirements with ``@pytest.mark.spec("004", ...)``; eval cases
name theirs in their ``tags``. Scratch repositories with a local remote only.
"""

import re
from pathlib import Path

import pydantic
import pytest
import yaml

from opscout.core.config import (
    CONVENTIONAL_TYPES,
    Configuration,
    InvalidConfigError,
    Ship,
)
from opscout.services.config import parse_config

REPO_ROOT = Path(__file__).resolve().parents[3]
SPEC_FILE = REPO_ROOT / "specs" / "004-ship-skill" / "spec.md"
PLUGIN = REPO_ROOT / "plugins" / "opscout"
COMPAT = REPO_ROOT / "tests" / "unit" / "config_contract" / "compat" / "v1" / "ship.yaml"


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 004."""
    return pytest.mark.spec("004", requirement)


def configuration(text: str) -> Configuration:
    return parse_config(f"schema_version: 1\n{text}".encode(), "config.yaml")


# The ship section


@spec("FR-001")
def test_the_ship_section_is_optional_and_additive() -> None:
    assert configuration("").ship == Ship()
    assert (
        parse_config(COMPAT.read_bytes(), str(COMPAT)).ship.branch_pattern
        == "{type}/{ticket}-{slug}"
    )


@spec("FR-002")
def test_the_defaults_are_safe() -> None:
    ship = Ship()

    assert ship.protected_branches == ["main", "master"]
    assert ship.branch_pattern == "{type}/{slug}"
    assert ship.types == list(CONVENTIONAL_TYPES)
    assert ship.trailer == "Assisted-by: Claude Code"
    assert (ship.pull_request.base, ship.pull_request.draft) == (None, True)


@spec("FR-002")
@pytest.mark.parametrize(
    "fields",
    [
        {"protected_branches": ["two words"]},
        {"protected_branches": [""]},
        {"branch_pattern": "{type}/fixed"},
        {"branch_pattern": "{type}/{slug}/{owner}"},
        {"branch_pattern": "Feature/{slug}"},
        {"types": []},
        {"types": ["Feat"]},
        {"trailer": "no colon here"},
        {"trailer": "Assisted-by: x\nSigned-off-by: y"},
        {"pull_request": {"draft": False}},
        {"pull_request": {"base": "two words"}},
        {"remote": "origin"},
    ],
    ids=[
        "space-in-pattern",
        "empty-pattern",
        "no-slug",
        "unknown-token",
        "capitals",
        "no-types",
        "type-capitals",
        "trailer-shape",
        "two-trailers",
        "not-draft",
        "base-space",
        "unknown-key",
    ],
)
def test_the_ship_section_is_bounded(fields: dict[str, object]) -> None:
    with pytest.raises(pydantic.ValidationError):
        Ship.model_validate(fields)


@spec("FR-002")
def test_a_non_draft_pull_request_is_a_located_problem() -> None:
    with pytest.raises(InvalidConfigError) as error:
        configuration("ship:\n  pull_request:\n    draft: false\n")

    (problem,) = error.value.problems
    assert (problem.path, problem.line) == ("ship.pull_request.draft", 4)


@spec("FR-002")
def test_a_bad_branch_pattern_says_what_is_allowed() -> None:
    with pytest.raises(InvalidConfigError) as error:
        configuration("ship:\n  branch_pattern: '{type}/{owner}'\n")

    (problem,) = error.value.problems
    assert problem.path == "ship.branch_pattern"
    assert "only the tokens {type}, {slug} and {ticket}" in problem.message
    assert "{owner}" not in problem.message


def test_the_compatibility_file_uses_every_ship_field() -> None:
    document = yaml.safe_load(COMPAT.read_text(encoding="utf-8"))["ship"]

    assert set(document) == set(Ship.model_fields)


# Proof


@spec("FR-025")
@pytest.mark.xfail(reason="removed in T020, once every requirement has a test", strict=True)
def test_every_requirement_has_a_test_or_an_eval_case() -> None:
    required = set(re.findall(r"\*\*(FR-\d{3})\*\*", SPEC_FILE.read_text(encoding="utf-8")))
    proven: set[str] = set()
    for name, test in globals().items():
        if not name.startswith("test_"):
            continue
        for mark in getattr(test, "pytestmark", []):
            if mark.name == "spec" and mark.args[0] == "004":
                proven.add(mark.args[1])
            elif mark.name == "parametrize":
                for value in mark.args[1]:
                    for param_mark in getattr(value, "marks", ()):
                        if param_mark.name == "spec" and param_mark.args[0] == "004":
                            proven.add(param_mark.args[1])
    for prompt in sorted((PLUGIN / "evals").glob("004-*/prompt.md")):
        front = yaml.safe_load(prompt.read_text(encoding="utf-8").split("---")[1])
        proven.update(tag for tag in front.get("tags", []) if tag.startswith("FR-"))

    assert required, "no requirement found in the spec"
    assert sorted(required - proven) == []
    assert sorted(proven - required) == []
