# SPDX-License-Identifier: Apache-2.0
"""The triage section (spec 012, FR-012, FR-014; contracts/config.md)."""

from pathlib import Path

import jsonschema  # type: ignore[import-untyped]
import pytest
import yaml

from opscout.core.config import Configuration, InvalidConfigError, schema_text
from opscout.services.config import parse_config

REPO_ROOT = Path(__file__).resolve().parents[3]
COMPAT = REPO_ROOT / "tests" / "unit" / "config_contract" / "compat" / "v1" / "triage.yaml"

AWS = """\
aws:
  environments:
    - name: example-prod
      account_id: "123456789012"
      profile: example-prod
      regions: [us-east-1]
"""

TRIAGE = """\
triage:
  infrastructure:
    - name: example-infra
      path: /srv/example/example-infra
      environments: [example-prod]
    - name: example-shared
      path: /srv/example/example-shared
  observability: true
  skeptic: true
  metric_history_days: 3
  background_actions: [ExampleAgentHeartbeat]
"""


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 012."""
    return pytest.mark.spec("012", requirement)


def configuration(text: str) -> Configuration:
    return parse_config(f"schema_version: 1\n{text}".encode(), "config.yaml")


def problems(text: str) -> str:
    with pytest.raises(InvalidConfigError) as error:
        configuration(text)
    return "\n".join(problem.render() for problem in error.value.problems)


@spec("FR-012")
def test_the_section_is_optional_with_defaults() -> None:
    assert configuration("").triage is None
    defaults = configuration("triage: {}\n").triage
    assert defaults is not None
    assert defaults.infrastructure == []
    assert (defaults.observability, defaults.skeptic) == (False, False)
    assert defaults.metric_history_days == 7
    assert defaults.background_actions == []


@spec("FR-012")
def test_clones_are_read_with_their_environments() -> None:
    triage = configuration(AWS + TRIAGE).triage
    assert triage is not None
    infra, shared = triage.infrastructure
    assert (infra.name, infra.path, infra.environments) == (
        "example-infra",
        "/srv/example/example-infra",
        ["example-prod"],
    )
    assert shared.environments is None
    assert triage.metric_history_days == 3
    assert triage.background_actions == ["ExampleAgentHeartbeat"]


@spec("FR-014")
def test_observability_is_a_declaration() -> None:
    triage = configuration(AWS + TRIAGE).triage
    assert triage is not None
    assert triage.observability is True


PATH = "/srv/example/x"
CLONE = f"triage:\n  infrastructure:\n    - {{name: example-infra, path: {PATH}"


@spec("FR-012")
@pytest.mark.parametrize(
    ("section", "message"),
    [
        (f"{CLONE.replace(PATH, 'relative/path')}}}\n", "triage.infrastructure[0].path"),
        (f"{CLONE.replace('example-infra', 'Example')}}}\n", "triage.infrastructure[0].name"),
        (f"{CLONE.replace('example-infra', 'x' * 41)}}}\n", "triage.infrastructure[0].name"),
        (
            f"{CLONE}}}\n    - {{name: example-infra, path: /srv/example/y}}\n",
            "two clones share a name",
        ),
        (f"{CLONE}, environments: [example-dev]}}\n", "is not a configured environment"),
        (f"{CLONE}, colour: blue}}\n", "triage.infrastructure[0]"),
        ("triage:\n  metric_history_days: 0\n", "triage.metric_history_days"),
        ("triage:\n  metric_history_days: 15\n", "triage.metric_history_days"),
        ("triage:\n  background_actions: ['bad action']\n", "triage.background_actions[0]"),
        ("triage:\n  observability: 'yes'\n", "triage.observability"),
    ],
)
def test_bad_triage_sections_are_refused(section: str, message: str) -> None:
    assert message in problems(AWS + section)


@spec("FR-012")
def test_limits_on_list_lengths() -> None:
    clones = "".join(f"    - {{name: c{i}, path: /srv/example/c{i}}}\n" for i in range(21))
    assert "triage.infrastructure" in problems(f"triage:\n  infrastructure:\n{clones}")
    actions = ", ".join(f"A{i}" for i in range(51))
    assert "triage.background_actions" in problems(f"triage:\n  background_actions: [{actions}]\n")


@spec("FR-012")
def test_a_refusal_never_repeats_the_value() -> None:
    rendered = problems(AWS + f"{CLONE.replace(PATH, 'secret-looking/path')}}}\n")
    assert "secret-looking" not in rendered


@spec("FR-012")
def test_clones_naming_environments_need_the_aws_section() -> None:
    assert "is not a configured environment" in problems(f"{CLONE}, environments: [a]}}\n")


@spec("FR-012")
def test_the_compatibility_file_uses_every_field() -> None:
    document = yaml.safe_load(COMPAT.read_text(encoding="utf-8"))
    used = set(document["triage"])
    assert used == set(Configuration.model_fields["triage"].annotation.__args__[0].model_fields)  # type: ignore[union-attr]
    assert parse_config(COMPAT.read_bytes(), str(COMPAT)).triage is not None


@spec("FR-012")
def test_the_schema_refuses_what_the_loader_refuses() -> None:
    validator = jsonschema.Draft202012Validator(yaml.safe_load(schema_text()))
    good = yaml.safe_load(f"schema_version: 1\n{AWS}{TRIAGE}")
    assert list(validator.iter_errors(good)) == []
    for bad in (
        {"triage": {"metric_history_days": 0}},
        {"triage": {"infrastructure": [{"name": "x", "path": "relative"}]}},
        {"triage": {"colour": "blue"}},
    ):
        assert list(validator.iter_errors({"schema_version": 1, **bad})) != [], bad
