# SPDX-License-Identifier: Apache-2.0
"""The summary skill: write-up formats, the formats command, the launcher, the skill (spec 003).

Every test is tied to the requirements it proves with ``@pytest.mark.spec("003", ...)``;
eval cases name theirs in their ``tags``. Reserved, fake values only (Principle I).
"""

import json
import re
from pathlib import Path

import jsonschema  # type: ignore[import-untyped]
import pydantic
import pytest
import yaml

from opscout.core.config import Configuration, WriteupFormat, Writeups, schema_text
from opscout.services.config import parse_config

REPO_ROOT = Path(__file__).resolve().parents[3]
SPEC_FILE = REPO_ROOT / "specs" / "003-summary-skill" / "spec.md"
PLUGIN = REPO_ROOT / "plugins" / "opscout"
COMPAT = REPO_ROOT / "tests" / "unit" / "config_contract" / "compat" / "v1" / "writeups.yaml"


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 003."""
    return pytest.mark.spec("003", requirement)


def configuration(text: str) -> Configuration:
    """Parse a configuration file's text, with the version line added."""
    return parse_config(f"schema_version: 1\n{text}".encode(), "config.yaml")


# The writeups section (Phase 2)


@spec("FR-001")
def test_the_writeups_section_is_optional() -> None:
    assert configuration("").writeups == Writeups()


@spec("FR-001")
def test_the_section_is_an_additive_change() -> None:
    assert parse_config(COMPAT.read_bytes(), str(COMPAT)).writeups.formats
    assert '"const": 1' in schema_text()


@spec("FR-002")
@spec("FR-003")
def test_a_writeups_section_holds_language_rules_and_formats() -> None:
    writeups = configuration(
        "writeups:\n"
        "  language: Example\n"
        "  rules: [Keep it short.]\n"
        "  formats:\n"
        "    status-update:\n"
        "      description: A weekly status line.\n"
        "      sections: [Done, Next]\n"
        "      rules: [One line per item.]\n"
        "      max_lines: 6\n"
    ).writeups

    assert writeups.language == "Example"
    assert writeups.rules == ["Keep it short."]
    assert writeups.formats["status-update"] == WriteupFormat(
        description="A weekly status line.",
        sections=["Done", "Next"],
        rules=["One line per item."],
        max_lines=6,
    )


@spec("FR-003")
@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"description": ""},
        {"description": "two\nlines"},
        {"description": "x" * 201},
        {"description": "ok", "max_lines": 0},
        {"description": "ok", "max_lines": 201},
        {"description": "ok", "sections": [""]},
        {"description": "ok", "rules": ["x" * 301]},
        {"description": "ok", "rules": ["r"] * 31},
        {"description": "ok", "template": "x"},
    ],
    ids=[
        "no-description",
        "empty",
        "two-lines",
        "long",
        "zero-lines",
        "too-many-lines",
        "empty-section",
        "long-rule",
        "too-many-rules",
        "unknown-key",
    ],
)
def test_a_format_is_bounded(fields: dict[str, object]) -> None:
    with pytest.raises(pydantic.ValidationError):
        WriteupFormat.model_validate(fields)


@spec("FR-004")
@pytest.mark.parametrize("name", ["ticket", "status-update", "v2-notes"])
def test_format_names_are_lowercase_words_with_hyphens(name: str) -> None:
    formats = configuration(f"writeups:\n  formats:\n    {name}: {{description: x}}\n")

    assert name in formats.writeups.formats


@spec("FR-004")
@pytest.mark.parametrize("name", ["Ticket", "status_update", "-x", "x-", "two words", "a" * 41])
def test_other_format_names_are_problems_at_the_key(name: str) -> None:
    from opscout.core.config import InvalidConfigError

    with pytest.raises(InvalidConfigError) as error:
        configuration(f"writeups:\n  formats:\n    '{name}': {{description: x}}\n")

    (problem,) = error.value.problems
    assert (problem.line, problem.column) == (4, 5)
    assert problem.message.startswith("expected")


@spec("FR-004")
def test_editors_refuse_the_names_the_loader_refuses() -> None:
    validator = jsonschema.Draft202012Validator(json.loads(schema_text()))

    def with_format(name: str) -> dict[str, object]:
        return {"schema_version": 1, "writeups": {"formats": {name: {"description": "x"}}}}

    assert validator.is_valid(with_format("status-update"))
    assert not validator.is_valid(with_format("Status_Update"))


def test_the_compatibility_file_uses_every_writeups_field() -> None:
    document = yaml.safe_load(COMPAT.read_text(encoding="utf-8"))["writeups"]
    (format_fields,) = [set(value) for value in document["formats"].values()][:1]

    assert set(document) == set(Writeups.model_fields)
    assert format_fields == set(WriteupFormat.model_fields)


# Proof


@spec("FR-029")
@pytest.mark.xfail(reason="removed in T021, once every requirement has a test", strict=True)
def test_every_requirement_has_a_test_or_an_eval_case() -> None:
    required = set(re.findall(r"\*\*(FR-\d{3})\*\*", SPEC_FILE.read_text(encoding="utf-8")))
    proven: set[str] = set()
    for name, test in globals().items():
        if not name.startswith("test_"):
            continue
        for mark in getattr(test, "pytestmark", []):
            if mark.name == "spec" and mark.args[0] == "003":
                proven.add(mark.args[1])
            elif mark.name == "parametrize":
                for value in mark.args[1]:
                    for param_mark in getattr(value, "marks", ()):
                        if param_mark.name == "spec" and param_mark.args[0] == "003":
                            proven.add(param_mark.args[1])
    for prompt in sorted((PLUGIN / "evals").glob("*/prompt.md")):
        front = yaml.safe_load(prompt.read_text(encoding="utf-8").split("---")[1])
        proven.update(tag for tag in front.get("tags", []) if tag.startswith("FR-"))

    assert required, "no requirement found in the spec"
    assert sorted(required - proven) == []
    assert sorted(proven - required) == []
