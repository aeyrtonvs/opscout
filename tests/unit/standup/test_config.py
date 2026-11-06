# SPDX-License-Identifier: Apache-2.0
"""The standup section (spec 009, FR-001, FR-002)."""

from pathlib import Path

import jsonschema  # type: ignore[import-untyped]
import pytest
import yaml

from opscout.core.config import (
    JOB_NAMES,
    KEYCHAIN_ITEMS,
    Configuration,
    InvalidConfigError,
    schema_text,
)
from opscout.services.config import parse_config

REPO_ROOT = Path(__file__).resolve().parents[3]
COMPAT = REPO_ROOT / "tests" / "unit" / "config_contract" / "compat" / "v1" / "standup.yaml"

SECTION = """\
standup:
  identities: [dev@example.com]
  code_host:
    service: bitbucket
    login: dev@example.com
  projects:
    example-api:
      paths: [/opt/example/src/example-api]
      repositories: [example-workspace/example-api]
    example-web:
      repositories: [example-workspace/example-web]
  redact: [Example Corp]
daemon:
  jobs:
    standup:
      at: "09:45"
      weekdays: [mon, tue, wed, thu, fri]
  secrets:
    bitbucket_token:
      service: opscout-bitbucket
"""


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 009."""
    return pytest.mark.spec("009", requirement)


def configuration(text: str) -> Configuration:
    return parse_config(f"schema_version: 1\n{text}".encode(), "config.yaml")


@spec("FR-001")
def test_the_section_is_optional_and_additive() -> None:
    assert configuration("").standup is None
    standup = configuration(SECTION).standup
    assert standup is not None
    assert standup.identities == ["dev@example.com"]
    assert standup.code_host is not None
    assert standup.code_host.login == "dev@example.com"
    assert set(standup.projects) == {"example-api", "example-web"}
    assert standup.projects["example-web"].paths == []
    assert standup.limits.prompt_length == 300
    assert (standup.limits.prompts_per_session, standup.limits.prompts) == (20, 60)
    assert (standup.limits.commits, standup.limits.pull_requests) == (40, 30)
    assert "standup" in JOB_NAMES
    assert "bitbucket_token" in KEYCHAIN_ITEMS
    compat = parse_config(COMPAT.read_bytes(), str(COMPAT)).standup
    assert compat is not None


BAD = [
    ("identities: []", "no identity"),
    ("projects: {}", "no project"),
    ("projects: {Example: {paths: [/opt/x]}}", "a project name with capitals"),
    ("projects: {example-api: {paths: [src/example-api]}}", "a relative path"),
    ("projects: {example-api: {}}", "neither paths nor repositories"),
    ("projects: {example-api: {repositories: [example-api]}}", "a repository without workspace"),
    ("redact: [x]", "a one-character term"),
    ("limits: {prompt_length: 20}", "a prompt length below 80"),
    ("limits: {commits: 1000}", "too many commits"),
    ("code_host: {service: github, login: dev}", "an unknown code host"),
    ("other: x", "an unknown key"),
]


@spec("FR-002")
@pytest.mark.parametrize(("line", "why"), BAD)
def test_bad_sections_are_refused(line: str, why: str) -> None:
    base = {
        "identities": "identities: [dev@example.com]",
        "projects": "projects: {example-api: {paths: [/opt/x]}}",
    }
    key = line.split(":", 1)[0]
    lines = [value for name, value in base.items() if name != key] + [line]
    text = "standup:\n" + "".join(f"  {entry}\n" for entry in lines)
    with pytest.raises(InvalidConfigError):
        configuration(text)


@spec("FR-002")
def test_a_code_host_needs_its_token_by_reference_and_the_job_needs_the_section() -> None:
    without_token = SECTION.replace(
        "  secrets:\n    bitbucket_token:\n      service: opscout-bitbucket\n", ""
    )
    with pytest.raises(InvalidConfigError) as error:
        configuration(without_token)
    assert "bitbucket_token" in error.value.problems[0].message
    with pytest.raises(InvalidConfigError):
        configuration(SECTION.replace("service: opscout-bitbucket", "service: [x]"))
    with pytest.raises(InvalidConfigError) as error:
        configuration('daemon:\n  jobs:\n    standup:\n      at: "09:45"\n')
    assert "standup section" in error.value.problems[0].message


@spec("FR-002")
def test_the_schema_refuses_what_the_loader_refuses() -> None:
    validator = jsonschema.Draft202012Validator(yaml.safe_load(schema_text()))
    assert list(validator.iter_errors(yaml.safe_load(f"schema_version: 1\n{SECTION}"))) == []
    for bad in (
        {"identities": [], "projects": {"example-api": {"paths": ["/opt/x"]}}},
        {"identities": ["x"], "projects": {"example-api": {"paths": ["relative"]}}},
        {"identities": ["x"], "projects": {"example-api": {}}},
        {"identities": ["x"], "projects": {"example-api": {"repositories": ["noslash"]}}},
    ):
        errors = list(validator.iter_errors({"schema_version": 1, "standup": bad}))
        assert errors != [], bad


@spec("FR-001")
def test_folders_alone_are_enough_and_one_of_the_two_is_needed() -> None:
    standup = configuration(
        "standup:\n  identities: [dev@example.com]\n  folders: [/opt/example/src]\n"
    ).standup
    assert standup is not None
    assert standup.folders == ["/opt/example/src"]
    assert standup.projects == {}
    with pytest.raises(InvalidConfigError):
        configuration("standup:\n  identities: [dev@example.com]\n")
    with pytest.raises(InvalidConfigError):
        configuration("standup:\n  identities: [x]\n  folders: [relative/src]\n")
