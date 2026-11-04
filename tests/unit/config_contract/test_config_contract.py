# SPDX-License-Identifier: Apache-2.0
"""The configuration contract (spec 002, ADR-0014).

Every test is tied to the requirements it proves with ``@pytest.mark.spec("002", ...)``.
Test configurations use reserved, fake values only (Constitution Principle I).
"""

import dataclasses
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Literal

import jsonschema  # type: ignore[import-untyped]
import pydantic
import pytest
import yaml

from opscout.core.config import (
    MIGRATION_NOTES,
    RETIRED_VERSIONS,
    SCHEMA_VERSION,
    ConfigLocationError,
    Configuration,
    InvalidConfigError,
    KeychainRef,
    Problem,
    schema_text,
)
from opscout.entrypoints.cli import main
from opscout.entrypoints.config import load_config
from opscout.services.config import (
    MAX_BYTES,
    MAX_NODES,
    ConfigLocation,
    Source,
    parse_config,
    read_yaml,
    resolve_config_dir,
    validate,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
SPEC_FILE = REPO_ROOT / "specs" / "002-config-contract" / "spec.md"

# A fake value standing in for anything private; it must never reach a problem message.
FAKE = "not-a-real-value"


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 002."""
    return pytest.mark.spec("002", requirement)


def problems_of(data: str | bytes) -> tuple[Problem, ...]:
    """Return the problems ``parse_config`` finds in a configuration file."""
    raw = data.encode() if isinstance(data, str) else data
    with pytest.raises(InvalidConfigError) as error:
        parse_config(raw, "config.yaml")
    return error.value.problems


def write_config(directory: Path, text: str) -> Path:
    """Write ``config.yaml`` in a directory and return the directory."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "config.yaml").write_text(text, encoding="utf-8")
    return directory


# The core types


@spec("FR-032")
def test_a_configuration_is_typed_and_read_only() -> None:
    configuration = Configuration.model_validate({"schema_version": 1})

    assert configuration.schema_version == 1
    with pytest.raises(pydantic.ValidationError):
        configuration.schema_version = 2  # type: ignore[assignment]


@spec("FR-014")
def test_a_configuration_rejects_an_unknown_key() -> None:
    with pytest.raises(pydantic.ValidationError) as error:
        Configuration.model_validate({"schema_version": 1, "example_section": {}})

    assert error.value.errors()[0]["type"] == "extra_forbidden"


@spec("FR-015")
@pytest.mark.parametrize("version", ["1", 1.0, True])
def test_a_configuration_never_converts_a_value(version: object) -> None:
    with pytest.raises(pydantic.ValidationError):
        Configuration.model_validate({"schema_version": version})


@spec("FR-019")
@pytest.mark.parametrize(
    "fields",
    [{"service": "example-service"}, {"service": "example-service", "account": "example-user"}],
)
def test_a_keychain_reference_names_a_service_and_maybe_an_account(
    fields: dict[str, str],
) -> None:
    reference = KeychainRef.model_validate(fields)

    assert reference.service == "example-service"
    assert reference.account == fields.get("account")


@spec("FR-019")
@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"service": ""},
        {"service": "x" * 129},
        {"service": "two words"},
        {"service": "tab\there"},
        {"service": "example-service", "account": "line\nbreak"},
        {"service": "example-service", "value": "not-a-real-value"},
    ],
    ids=["no-service", "empty", "too-long", "space", "tab", "newline", "a-value-key"],
)
def test_a_keychain_reference_holds_names_only(fields: dict[str, str]) -> None:
    with pytest.raises(pydantic.ValidationError):
        KeychainRef.model_validate(fields)


@spec("FR-016")
def test_problems_are_ordered_by_position() -> None:
    later = Problem("config.yaml", 3, 1, "b", "second")
    same_line = Problem("config.yaml", 2, 5, "a", "first, column 5")
    earlier = Problem("config.yaml", 2, 1, "c", "first, column 1")

    assert sorted([later, same_line, earlier]) == [earlier, same_line, later]
    assert dataclasses.is_dataclass(earlier)
    assert earlier.render() == "config.yaml:2:1: c: first, column 1"


# Finding the configuration (User Story 1)


@spec("FR-001")
@pytest.mark.parametrize(
    ("flag", "environ", "expected", "source"),
    [
        (Path("from-flag"), {"OPSCOUT_CONFIG": "from-env"}, Path("from-flag"), Source.FLAG),
        (None, {"OPSCOUT_CONFIG": "from-env"}, Path("from-env"), Source.ENV),
        (None, {"OPSCOUT_CONFIG": ""}, Path("home/.config/opscout"), Source.DEFAULT),
        (None, {}, Path("home/.config/opscout"), Source.DEFAULT),
        (Path("~/from-flag"), {}, Path("home/from-flag"), Source.FLAG),
        (None, {"OPSCOUT_CONFIG": "~/from-env"}, Path("home/from-env"), Source.ENV),
    ],
    ids=["flag-wins", "env", "empty-env-is-unset", "default", "flag-tilde", "env-tilde"],
)
def test_the_directory_is_resolved_in_order(
    flag: Path | None, environ: dict[str, str], expected: Path, source: Source
) -> None:
    location = resolve_config_dir(flag, environ, Path("home"))

    assert location == ConfigLocation(expected, source)


@spec("FR-002")
@pytest.mark.parametrize(
    ("source", "described"),
    [
        (Source.FLAG, "from --config"),
        (Source.ENV, "from OPSCOUT_CONFIG"),
        (Source.DEFAULT, "default"),
    ],
)
def test_a_location_says_where_it_came_from(source: Source, described: str) -> None:
    assert ConfigLocation(Path("example"), source).describe() == f"example ({described})"


@spec("FR-003")
def test_a_missing_directory_is_reported_with_its_path(tmp_path: Path) -> None:
    missing = tmp_path / "missing"

    with pytest.raises(ConfigLocationError, match=re.escape(f"{missing}: no such directory")):
        load_config(missing)


@spec("FR-003")
def test_a_file_in_place_of_the_directory_is_reported(tmp_path: Path) -> None:
    not_a_directory = tmp_path / "file"
    not_a_directory.write_text("", encoding="utf-8")

    with pytest.raises(ConfigLocationError, match="not a directory"):
        load_config(not_a_directory)


@spec("FR-004")
def test_a_missing_file_is_reported_with_its_expected_path(tmp_path: Path) -> None:
    with pytest.raises(ConfigLocationError) as error:
        load_config(tmp_path)

    assert str(error.value) == f"{tmp_path / 'config.yaml'}: no such file"


@spec("FR-004")
def test_a_directory_in_place_of_the_file_is_reported(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").mkdir()

    with pytest.raises(ConfigLocationError, match=r"config\.yaml: not a file$"):
        load_config(tmp_path)


@spec("FR-004")
def test_a_misnamed_file_gets_a_hint(tmp_path: Path) -> None:
    (tmp_path / "config.yml").write_text("schema_version: 1\n", encoding="utf-8")

    with pytest.raises(ConfigLocationError, match=r"found config\.yml: rename it to config\.yaml"):
        load_config(tmp_path)


@spec("FR-004")
def test_other_files_in_the_directory_are_never_read(tmp_path: Path) -> None:
    write_config(tmp_path, "schema_version: 1\n")
    unreadable = tmp_path / "leak-denylist.txt"
    unreadable.write_text(FAKE, encoding="utf-8")
    unreadable.chmod(0)
    (tmp_path / "notes.yaml").write_text("{ not yaml", encoding="utf-8")
    try:
        assert load_config(tmp_path) == Configuration(schema_version=1)
    finally:
        unreadable.chmod(0o600)


# Reading the file and validating its contents (User Story 1)


def alias_bomb(levels: int, width: int) -> str:
    """Return a document whose aliases expand to ``width ** levels`` nodes."""
    lines = [f"l0: &l0 [{', '.join(['x'] * width)}]"]
    lines += [f"l{n}: &l{n} [{', '.join([f'*l{n - 1}'] * width)}]" for n in range(1, levels)]
    return "schema_version: 1\n" + "\n".join(lines) + "\n"


def case(
    name: str, data: str | bytes, where: tuple[str, int, int], message: str, *requirements: str
) -> object:
    """One invalid configuration: the key path, line and column of a problem, and its text."""
    marks = [spec(requirement) for requirement in requirements]
    return pytest.param(data, where, message, id=name, marks=marks)


V1 = "schema_version: 1\n"

# fmt: off
INVALID = [
    case("invalid-utf-8", V1.encode() + b"example: \xff" + FAKE.encode() + b"\n",
         ("(document)", 2, 10), "not valid UTF-8", "FR-005"),
    case("invalid-utf-8-after-accents", V1.encode() + b"\xc3\xa9\xc3\xa9: \xff\n",
         ("(document)", 2, 5), "not valid UTF-8", "FR-005"),
    case("invalid-utf-8-after-a-bom", b"\xef\xbb\xbfex: \xff\n",
         ("(document)", 1, 5), "not valid UTF-8", "FR-005"),
    case("too-large", V1.encode() + b"#" + b"x" * MAX_BYTES + b"\n",
         ("(document)", 1, 1), "larger than 1 MiB", "FR-005"),
    case("python-tag", f"{V1}example: !!python/object:os.system {FAKE}\n",
         ("example", 2, 10), "not allowed", "FR-006"),
    case("python-apply-tag", f"{V1}example: !!python/object/apply:os.system [{FAKE}]\n",
         ("example", 2, 10), "not allowed", "FR-006"),
    case("python-name-tag", f"{V1}example: !!python/name:os.system\n",
         ("example", 2, 10), "not allowed", "FR-006"),
    case("binary-tag", f"{V1}example: !!binary bm90LWEtcmVhbC12YWx1ZQ==\n",
         ("example", 2, 10), "not allowed", "FR-006"),
    case("set-tag", f"{V1}example: !!set {{{FAKE}: null}}\n",
         ("example", 2, 10), "not allowed", "FR-006"),
    case("local-tag", f"{V1}example: !secret {FAKE}\n",
         ("example", 2, 10), "not allowed", "FR-006"),
    case("merge-key", f"{V1}example:\n  <<: {{a: {FAKE}}}\n",
         ("example", 3, 3), "merge key", "FR-006"),
    case("complex-key", f"{V1}? [example, key]\n: {FAKE}\n",
         ("(top level)", 2, 3), "a key must be a string", "FR-006"),
    case("integer-key", f"{V1}1: {FAKE}\n",
         ("(top level)", 2, 1), "a key must be a string", "FR-006"),
    case("boolean-key", f"{V1}yes: {FAKE}\n",
         ("(top level)", 2, 1), "a key must be a string", "FR-006"),
    case("null-key", f"{V1}~: {FAKE}\n",
         ("(top level)", 2, 1), "a key must be a string", "FR-006"),
    case("date-key", f"{V1}2001-01-01: {FAKE}\n",
         ("(top level)", 2, 1), "a key must be a string", "FR-006"),
    case("bad-tagged-value", f"schema_version: !!float {FAKE}\n",
         ("schema_version", 1, 17), "cannot be read as its tag says", "FR-006"),
    case("tagged-integer", f"schema_version: !!int {FAKE}\n",
         ("schema_version", 1, 17), "plain decimal", "FR-015"),
    case("duplicate-key", f"{V1}schema_version: 1\n",
         ("schema_version", 2, 1), "duplicate key", "FR-007"),
    case("syntax", f"{V1}example: [{FAKE}\n",
         ("(document)", 3, 1), "not valid YAML", "FR-008"),
    case("undefined-alias", f"{V1}example: *{FAKE}\n",
         ("(document)", 2, 10), "not valid YAML", "FR-008"),
    case("two-documents", f"{V1}---\n{V1}",
         ("(document)", 2, 1), "not valid YAML", "FR-008"),
    case("nul-character", f"{V1}example: \x00{FAKE}\n",
         ("(document)", 2, 10), "a character YAML does not allow", "FR-008"),
    case("bell-character", f"{V1}example: \x07{FAKE}\n",
         ("(document)", 2, 10), "a character YAML does not allow", "FR-008"),
    case("noncharacter", f"{V1}example: ￾{FAKE}\n",
         ("(document)", 2, 10), "a character YAML does not allow", "FR-008"),
    case("empty", "", ("(document)", 1, 1), "empty", "FR-009"),
    case("comments-only", "# only a comment\n", ("(document)", 1, 1), "empty", "FR-009"),
    case("top-level-list", f"- {FAKE}\n", ("(top level)", 1, 1), "must be a mapping", "FR-009"),
    case("top-level-scalar", f"{FAKE}\n", ("(top level)", 1, 1), "must be a mapping", "FR-009"),
    case("alias-bomb", alias_bomb(levels=5, width=10),
         ("(document)", 1, 1), f"more than {MAX_NODES:,} nodes", "FR-010"),
    case("too-deep", f"{V1}example: " + "[" * 200 + "]" * 200 + "\n",
         ("(document)", 1, 1), "nested deeper than", "FR-010"),
    case("too-deep-for-the-parser", f"{V1}example: " + "[" * 5000 + "]" * 5000 + "\n",
         ("(document)", 1, 1), "nested deeper than", "FR-010"),
    case("no-version", f"example: {FAKE}\n",
         ("example", 1, 1), "unknown key", "FR-011", "FR-014"),
    case("version-as-text", 'schema_version: "1"\n',
         ("schema_version", 1, 17), "expected an integer", "FR-011", "FR-015"),
    case("version-as-float", "schema_version: 1.0\n",
         ("schema_version", 1, 17), "expected an integer", "FR-011", "FR-015"),
    case("version-as-boolean", "schema_version: true\n",
         ("schema_version", 1, 17), "expected an integer", "FR-011", "FR-015"),
    case("hexadecimal-integer", "schema_version: 0x1\n",
         ("schema_version", 1, 17), "plain decimal", "FR-015"),
    case("underscored-integer", "schema_version: 0_1\n",
         ("schema_version", 1, 17), "plain decimal", "FR-015"),
    case("leading-zero-integer", "schema_version: 01\n",
         ("schema_version", 1, 17), "plain decimal", "FR-015"),
    case("yaml-1.1-boolean", f"{V1}example: off\n",
         ("example", 2, 10), "true or false", "FR-015"),
    case("unknown-key", f"{V1}example_section:\n  token: {FAKE}\n",
         ("example_section", 2, 1), "unknown key; it may be a typo or come from a newer opscout",
         "FR-014"),
]
# fmt: on


@pytest.mark.parametrize(("data", "where", "message"), INVALID)
def test_an_invalid_configuration_is_reported_where_it_is_wrong(
    data: str | bytes, where: tuple[str, int, int], message: str
) -> None:
    found = problems_of(data)

    assert any(
        (problem.path, problem.line, problem.column) == where and message in problem.message
        for problem in found
    ), [problem.render() for problem in found]


@spec("FR-017")
@pytest.mark.parametrize(("data", "where", "message"), INVALID)
def test_no_problem_message_contains_the_value(
    data: str | bytes, where: tuple[str, int, int], message: str
) -> None:
    rendered = "\n".join(problem.render() for problem in problems_of(data))

    assert FAKE not in rendered
    assert "bm90LWEtcmVhbC12YWx1ZQ" not in rendered


def test_the_set_of_invalid_configurations_is_large_enough() -> None:
    assert len(INVALID) >= 20  # SC-004


@spec("FR-005")
def test_a_byte_order_mark_is_accepted() -> None:
    assert parse_config(b"\xef\xbb\xbfschema_version: 1\n", "config.yaml").schema_version == 1


@spec("FR-010")
def test_a_small_alias_is_accepted() -> None:
    document, _ = read_yaml(b"base: &b [one, two]\ncopy: *b\n", "config.yaml")

    assert document == {"base": ["one", "two"], "copy": ["one", "two"]}


@spec("FR-009")
def test_a_missing_version_is_reported_at_the_top_level() -> None:
    (problem,) = problems_of("{}\n")

    assert (problem.path, problem.line, problem.message) == (
        "schema_version",
        1,
        "required key is missing",
    )


class _Section(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(strict=True, extra="forbid", frozen=True)

    credential: KeychainRef
    items: list[int] = []


class _Nested(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(strict=True, extra="forbid", frozen=True)

    section: _Section


@spec("FR-014")
@spec("FR-015")
def test_problems_are_located_at_any_depth() -> None:
    text = (
        f"section:\n  credential:\n    service: {FAKE}\n    value: {FAKE}\n  items: [1, two, 3]\n"
    )
    document, reader = read_yaml(text.encode(), "config.yaml")

    with pytest.raises(InvalidConfigError) as error:
        validate(document, reader, _Nested)

    assert [(p.path, p.line, p.column, p.message) for p in error.value.problems] == [
        (
            "section.credential.value",
            4,
            5,
            "unknown key; it may be a typo or come from a newer opscout",
        ),
        ("section.items[1]", 5, 14, "expected an integer"),
    ]


class _Kinds(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(strict=True, extra="forbid", frozen=True)

    credential: KeychainRef | None = None
    items: list[int] = []
    kind: Literal["first", "second"] = "first"
    flag: bool = False
    count: Annotated[int, pydantic.Field(gt=0)] = 1
    choice: int | bool = 0


@spec("FR-015")
@spec("FR-017")
@pytest.mark.parametrize(
    ("text", "path", "message"),
    [
        ('credential: {service: ""}', "credential.service", "expected at least 1 character(s)"),
        (f"credential: {{service: {'x' * 129}}}", "credential.service", "expected at most 128"),
        ("credential: {service: two words}", "credential.service", "expected text matching"),
        ("credential: {service: 5}", "credential.service", "expected a string"),
        ("credential: [example]", "credential", "expected a mapping"),
        ("items: example", "items", "expected a list"),
        ("kind: third", "kind", "expected 'first' or 'second'"),
        ("flag: example", "flag", "expected true or false"),
        ("count: 0", "count", "not a valid value here"),
        ("choice: example", "choice", "expected an integer"),
    ],
    ids=[
        "too-short",
        "too-long",
        "pattern",
        "string",
        "mapping",
        "list",
        "literal",
        "boolean",
        "other",
        "union",
    ],
)
def test_every_kind_of_problem_says_what_was_expected(text: str, path: str, message: str) -> None:
    document, reader = read_yaml(f"{text}\n".encode(), "config.yaml")

    with pytest.raises(InvalidConfigError) as error:
        validate(document, reader, _Kinds)

    first = error.value.problems[0]
    assert (first.path, first.line) == (path, 1)
    assert message in first.message


@spec("FR-007")
def test_distinct_keys_are_never_duplicates() -> None:
    document, reader = read_yaml(b"a: 1\nA: 2\n'1': 3\n'true': 4\n", "config.yaml")

    assert document == {"a": 1, "A": 2, "1": 3, "true": 4}
    assert reader.refused == []
    found = problems_of(f"{V1}'true': {FAKE}\ntrue: {FAKE}\n")
    assert [p.message for p in found if p.line == 3] == ["a key must be a string"]


@spec("FR-017")
@pytest.mark.parametrize(
    ("key", "shown"),
    [
        ("''", '""'),
        ('"two\\nlines"', '"two\\nlines"'),
        ('"\\e[31mred"', '"\\u001b[31mred"'),
        ("'a.b'", '"a.b"'),
        ("plain_key-1", "plain_key-1"),
        ("k" * 80, "k" * 64 + "…"),
    ],
    ids=["empty", "line-break", "terminal-escape", "dot", "plain", "long"],
)
def test_keys_are_printed_escaped(key: str, shown: str) -> None:
    (problem,) = problems_of(f"{V1}{key}: 1\n")

    assert problem.path == shown
    assert "\n" not in problem.render()
    assert "\x1b" not in problem.render()


@spec("FR-016")
def test_reading_and_content_problems_are_reported_together() -> None:
    found = problems_of(
        f"schema_version: 1\nexample_a: 1\nexample_a: 2\nexample_b: !secret {FAKE}\n"
        f"example_c: {FAKE}\n"
    )

    assert [(p.line, p.path, p.message.split(";")[0]) for p in found] == [
        (2, "example_a", "unknown key"),
        (3, "example_a", "duplicate key"),
        (4, "example_b", "this tag is not allowed"),
        (5, "example_c", "unknown key"),
    ]


@spec("FR-016")
def test_every_problem_is_reported_in_one_run_in_file_order() -> None:
    found = problems_of(f'example_a: {FAKE}\nschema_version: "1"\nexample_b: {FAKE}\n')

    assert [(p.file, p.line, p.path) for p in found] == [
        ("config.yaml", 1, "example_a"),
        ("config.yaml", 2, "schema_version"),
        ("config.yaml", 3, "example_b"),
    ]


# The command (User Story 1)


@spec("FR-002")
@spec("FR-018")
def test_validate_reports_a_valid_configuration(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = write_config(tmp_path / "example", "schema_version: 1\n")

    assert main(["config", "validate", "--config", str(directory)]) == 0
    assert capsys.readouterr().out == (
        f"opscout config: {directory} (from --config)\n"
        f"{directory / 'config.yaml'}: valid (schema version 1)\n"
    )


@spec("FR-018")
def test_validate_lists_the_problems_and_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = write_config(tmp_path, f"schema_version: 1\nexample_section: {FAKE}\n")

    assert main(["config", "validate", "--config", str(directory)]) == 1
    assert capsys.readouterr().out.splitlines()[1:] == [
        f"{directory / 'config.yaml'}:2:1: example_section: "
        "unknown key; it may be a typo or come from a newer opscout"
    ]


@spec("FR-003")
@spec("FR-018")
def test_validate_fails_on_a_missing_directory_and_names_its_source(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPSCOUT_CONFIG", str(tmp_path / "missing"))

    assert main(["config", "validate"]) == 1
    assert capsys.readouterr().out == (
        f"opscout config: {tmp_path / 'missing'} (from OPSCOUT_CONFIG)\n"
        f"opscout config: {tmp_path / 'missing'}: no such directory\n"
    )


@spec("FR-001")
def test_validate_uses_the_default_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPSCOUT_CONFIG", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    write_config(tmp_path / ".config" / "opscout", "schema_version: 1\n")

    assert main(["config", "validate"]) == 0
    assert "(default)" in capsys.readouterr().out


@spec("FR-018")
@pytest.mark.parametrize(
    "argv", [["config"], ["config", "validate", "--unknown"], ["config", "unknown"]]
)
def test_bad_arguments_exit_with_status_two(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(argv)

    assert exit_info.value.code == 2


@spec("FR-032")
def test_the_loader_returns_what_the_command_validates(tmp_path: Path) -> None:
    directory = write_config(tmp_path, "schema_version: 1\n")

    configuration = load_config(directory)

    assert configuration == Configuration(schema_version=1)
    assert configuration.model_config.get("frozen") is True


# The example configuration (User Story 2)

EXAMPLE_DIR = REPO_ROOT / "example-config"
EXAMPLE = EXAMPLE_DIR / "config.yaml"
SCHEMA_FILE = REPO_ROOT / "schemas" / "config.schema.json"


@spec("FR-026")
def test_the_example_is_a_valid_configuration() -> None:
    assert load_config(EXAMPLE_DIR) == Configuration(schema_version=1)


@spec("FR-026")
def test_the_example_explains_every_key_and_names_its_schema() -> None:
    lines = EXAMPLE.read_text(encoding="utf-8").splitlines()

    assert lines[0] == "# yaml-language-server: $schema=../schemas/config.schema.json"
    for number, line in enumerate(lines):
        if re.match(r"^\s*[A-Za-z_][\w-]*:", line):
            assert lines[number - 1].lstrip().startswith("#"), f"no comment above: {line}"


@spec("FR-028")
def test_the_example_says_how_to_start_a_private_configuration() -> None:
    readme = (EXAMPLE_DIR / "README.md").read_text(encoding="utf-8")

    assert "private" in readme
    assert "opscout config validate" in readme
    assert "opscout-config-validate" in readme


@spec("FR-027")
def test_the_gates_validate_the_example() -> None:
    hooks = {
        hook["id"]: hook
        for repo in yaml.safe_load((REPO_ROOT / ".pre-commit-config.yaml").read_text("utf-8"))[
            "repos"
        ]
        for hook in repo["hooks"]
    }
    hook = hooks["example-config"]
    assert "opscout config validate --config example-config" in hook["entry"]
    assert hook["pass_filenames"] is False
    for changed in (
        "example-config/config.yaml",
        "schemas/config.schema.json",
        "src/opscout/core/config.py",
    ):
        assert re.search(hook["files"], changed), changed

    workflow = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text("utf-8"))
    (check,) = [
        step for step in workflow["jobs"]["gates"]["steps"] if "just check" in step.get("run", "")
    ]
    assert "example-config" not in check.get("env", {}).get("SKIP", "")


# The schema for editors (User Story 3)


def undescribed(schema: dict[str, Any], where: str = "") -> list[str]:
    """Return every property, at any depth, that has no description."""
    missing = []
    for name, value in schema.get("properties", {}).items():
        if "description" not in value:
            missing.append(f"{where}{name}")
        missing += undescribed(value, f"{where}{name}.")
    for name, value in schema.get("$defs", {}).items():
        missing += undescribed(value, f"{where}$defs.{name}.")
    return missing


@spec("FR-021")
def test_the_schema_declares_its_dialect_identifier_and_title() -> None:
    document = json.loads(schema_text())

    assert document["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert document["$id"].endswith("/schemas/config.schema.json")
    assert document["title"] == "opscout configuration"
    jsonschema.Draft202012Validator.check_schema(document)


@spec("FR-022")
def test_the_committed_schema_matches_the_models() -> None:
    assert SCHEMA_FILE.read_text(encoding="utf-8") == schema_text(), (
        "schemas/config.schema.json is out of date: run `uv run just schema`"
    )


@spec("FR-023")
def test_the_schema_command_prints_the_committed_schema(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["config", "schema"]) == 0
    assert capsys.readouterr().out == SCHEMA_FILE.read_text(encoding="utf-8")


@spec("FR-024")
def test_every_key_has_a_description() -> None:
    assert undescribed(json.loads(schema_text())) == []
    nested = {"properties": {"section": {"description": "x", "properties": {"key": {}}}}}
    assert undescribed(nested) == ["section.key"]


@spec("FR-025")
def test_a_general_purpose_validator_accepts_the_example() -> None:
    validator = jsonschema.Draft202012Validator(json.loads(SCHEMA_FILE.read_text(encoding="utf-8")))

    validator.validate(yaml.safe_load(EXAMPLE.read_text(encoding="utf-8")))
    assert not validator.is_valid({"schema_version": 1, "example_section": {}})
    assert not validator.is_valid({"schema_version": 2})


# Schema changes are explicit (User Story 4)

COMPAT_DIR = Path(__file__).parent / "compat" / f"v{SCHEMA_VERSION}"
REFERENCE = REPO_ROOT / MIGRATION_NOTES
CREDENTIAL_WORDS = (
    "token",
    "password",
    "passwd",
    "secret",
    "api_key",
    "apikey",
    "credential",
    "private_key",
)


@spec("FR-012")
def test_a_newer_version_asks_to_upgrade_and_reports_nothing_else() -> None:
    (problem,) = problems_of(f"schema_version: 2\nexample_section: {FAKE}\n")

    assert (problem.path, problem.line) == ("schema_version", 1)
    assert "newer opscout" in problem.message
    assert "upgrade opscout" in problem.message


@spec("FR-013")
def test_a_retired_version_names_its_migration_note_and_nothing_else() -> None:
    with pytest.raises(InvalidConfigError) as error:
        parse_config(
            f"schema_version: 0\nexample_section: {FAKE}\n".encode(),
            "config.yaml",
            retired={0: "#from-version-0"},
        )

    (problem,) = error.value.problems
    assert f"{MIGRATION_NOTES}#from-version-0" in problem.message


@spec("FR-013")
def test_an_unknown_version_is_reported_alone() -> None:
    (problem,) = problems_of(f"schema_version: -1\nexample_section: {FAKE}\n")

    assert problem.message == "unknown schema version; this opscout reads version 1"


@spec("FR-029")
def test_the_schema_allows_only_the_supported_version() -> None:
    document = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))

    assert document["properties"]["schema_version"]["const"] == SCHEMA_VERSION
    for path in sorted(COMPAT_DIR.glob("*.yaml")):
        assert yaml.safe_load(path.read_text(encoding="utf-8"))["schema_version"] == SCHEMA_VERSION


@spec("FR-030")
def test_every_configuration_of_the_compatibility_set_still_validates() -> None:
    paths = sorted(COMPAT_DIR.glob("*.yaml"))

    assert COMPAT_DIR / "minimal.yaml" in paths
    for path in paths:
        parse_config(path.read_bytes(), str(path))


def anchor(heading: str) -> str:
    """Return the anchor GitHub gives a Markdown heading."""
    return "#" + re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def missing_notes(retired: Mapping[int, str], reference: str) -> list[int]:
    """Return each retired version whose migration note is not in the reference."""
    anchors = {anchor(line.lstrip("#")) for line in reference.splitlines() if line.startswith("#")}
    return [version for version, note in retired.items() if note not in anchors]


@spec("FR-031")
def test_every_retired_version_has_a_migration_note() -> None:
    reference = REFERENCE.read_text(encoding="utf-8")

    assert "## Migration notes" in reference
    assert missing_notes(RETIRED_VERSIONS, reference) == []
    assert missing_notes({0: "#from-version-0"}, "### From version 0\n") == []
    assert missing_notes({0: "#from-version-0"}, reference) == [0]


def unreferenced_credentials(schema: dict[str, Any]) -> list[str]:
    """Return every property named like a credential that is not a keychain reference."""
    found = []
    objects = [
        ("", schema),
        *((f"$defs.{name}.", value) for name, value in schema.get("$defs", {}).items()),
    ]
    while objects:
        where, current = objects.pop()
        for name, value in current.get("properties", {}).items():
            refs = [value.get("$ref"), *(option.get("$ref") for option in value.get("anyOf", []))]
            if any(word in name.lower() for word in CREDENTIAL_WORDS) and (
                "#/$defs/KeychainRef" not in refs
            ):
                found.append(f"{where}{name}")
            objects.append((f"{where}{name}.", value))
    return sorted(found)


class _Credentials(pydantic.BaseModel):
    api_token: KeychainRef
    Database_Password: KeychainRef | None = None


class _Leaky(pydantic.BaseModel):
    api_token: str
    nested: _Credentials


@spec("FR-019")
@spec("FR-020")
def test_a_credential_can_only_be_a_keychain_reference() -> None:
    assert unreferenced_credentials(json.loads(schema_text())) == []
    assert unreferenced_credentials(_Credentials.model_json_schema()) == []
    assert unreferenced_credentials(_Leaky.model_json_schema()) == ["api_token"]
    assert set(CREDENTIAL_WORDS) == {
        "token",
        "password",
        "passwd",
        "secret",
        "api_key",
        "apikey",
        "credential",
        "private_key",
    }
    spec_text = SPEC_FILE.read_text(encoding="utf-8")
    assert all(f"`{word}`" in spec_text for word in CREDENTIAL_WORDS)


# The private repository's hook (User Story 5)


@spec("FR-033")
def test_the_published_hook_validates_the_repository_it_runs_in(tmp_path: Path) -> None:
    (hook,) = yaml.safe_load((REPO_ROOT / ".pre-commit-hooks.yaml").read_text("utf-8"))
    assert hook["id"] == "opscout-config-validate"
    assert hook["language"] == "python"
    assert hook["pass_filenames"] is False
    assert [
        name
        for name in ("config.yaml", "config.yml", "sub/config.yaml", "notes.yaml")
        if re.search(hook["files"], name)
    ] == ["config.yaml", "config.yml"]

    program, *arguments = hook["entry"].split()
    assert program == "opscout"
    repository = write_config(tmp_path / "private", "schema_version: 1\n")
    elsewhere = write_config(tmp_path / "elsewhere", f"example_section: {FAKE}\n")
    environment = {**os.environ, "OPSCOUT_CONFIG": str(elsewhere)}

    def run() -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603  (the interpreter running the tests)
            [sys.executable, "-m", "opscout", *arguments],
            cwd=repository,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    valid = run()
    assert (valid.returncode, valid.stdout.splitlines()[0]) == (
        0,
        "opscout config: . (from --config)",
    )

    write_config(repository, f"schema_version: 1\nexample_section: {FAKE}\n")
    invalid = run()
    assert invalid.returncode == 1
    assert "example_section: unknown key" in invalid.stdout


# Proof


def test_validating_the_example_takes_under_two_seconds() -> None:
    started = time.perf_counter()
    result = subprocess.run(  # noqa: S603  (the interpreter running the tests)
        [sys.executable, "-m", "opscout", "config", "validate", "--config", str(EXAMPLE_DIR)],
        capture_output=True,
        text=True,
        check=False,
    )
    elapsed = time.perf_counter() - started

    assert result.returncode == 0, result.stdout
    assert elapsed < 2.0  # SC-006, start-up included


@spec("FR-034")
def test_every_requirement_has_a_test() -> None:
    required = set(re.findall(r"\*\*(FR-\d{3})\*\*", SPEC_FILE.read_text(encoding="utf-8")))
    proven: set[str] = set()
    for name, test in globals().items():
        if not name.startswith("test_"):
            continue
        for mark in getattr(test, "pytestmark", []):
            if mark.name == "spec" and mark.args[0] == "002":
                proven.add(mark.args[1])
            elif mark.name == "parametrize":
                for value in mark.args[1]:
                    for param_mark in getattr(value, "marks", ()):
                        if param_mark.name == "spec" and param_mark.args[0] == "002":
                            proven.add(param_mark.args[1])

    assert required, "no requirement found in the spec"
    assert sorted(required - proven) == []
    assert sorted(proven - required) == []
