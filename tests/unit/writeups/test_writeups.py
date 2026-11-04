# SPDX-License-Identifier: Apache-2.0
"""The summary skill: write-up formats, the formats command, the launcher, the skill (spec 003).

Every test is tied to the requirements it proves with ``@pytest.mark.spec("003", ...)``;
eval cases name theirs in their ``tags``. Reserved, fake values only (Principle I).
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import jsonschema  # type: ignore[import-untyped]
import pydantic
import pytest
import yaml

from opscout import __version__
from opscout.core.config import Configuration, WriteupFormat, Writeups, schema_text
from opscout.core.writeups import BUILT_IN_FORMATS, SHARED_RULES
from opscout.entrypoints.cli import main
from opscout.services.config import parse_config
from opscout.services.writeups import render_formats, resolve_formats
from tools.leak_check import scan_text

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


# Resolving and printing the formats (User Story 2)

BUILT_IN_TEXT = """\
## Rules for every format
- State only facts from the session; invent nothing: no ticket keys, names, times or figures that the session does not state.
- Never list what was evaluated and ruled out, nor how the result was reached.
- Never include a secret value; you may say that a secret exists and where it lives.
- Write plain text ready to paste: no preamble, and no headings other than the format's sections.

## ticket (built-in)
A ticket update: the problem, its cause, what was done and what is left.
Sections, in order: What happened; Why; What was done; What is pending
At most 12 lines.

## message (built-in)
A short chat message for teammates.
At most 5 lines.
Rules:
- Two to four sentences, no sections.

## postmortem (built-in)
An incident postmortem.
Sections, in order: Cause; Impact; Fix; Follow-ups
At most 25 lines.
"""  # noqa: E501  (the expected output, line for line)


@spec("FR-005")
def test_the_built_in_formats_forbid_listing_what_was_ruled_out() -> None:
    assert list(BUILT_IN_FORMATS) == ["ticket", "message", "postmortem"]
    assert any(
        "ruled out" in rule and "how the result was reached" in rule for rule in SHARED_RULES
    )
    assert BUILT_IN_FORMATS["ticket"].sections == [
        "What happened",
        "Why",
        "What was done",
        "What is pending",
    ]
    assert BUILT_IN_FORMATS["postmortem"].sections == ["Cause", "Impact", "Fix", "Follow-ups"]


@spec("FR-007")
def test_the_built_in_formats_hold_no_organization_term() -> None:
    text = render_formats(resolve_formats(Writeups()), source="Source: built-in", language=None)

    assert scan_text(text, "built-in formats", allowlist={}, denylist=[]) == []


@spec("FR-006")
def test_a_configured_format_replaces_or_adds() -> None:
    writeups = configuration(
        "writeups:\n"
        "  formats:\n"
        "    zeta-notes: {description: Added last by name.}\n"
        "    ticket: {description: The team's own ticket shape., sections: [Summary]}\n"
        "    alpha-notes: {description: Added first by name.}\n"
    ).writeups

    resolved = resolve_formats(writeups)

    assert [(f.name, f.origin) for f in resolved] == [
        ("ticket", "configured"),
        ("message", "built-in"),
        ("postmortem", "built-in"),
        ("alpha-notes", "configured"),
        ("zeta-notes", "configured"),
    ]
    assert resolved[0].format == WriteupFormat(
        description="The team's own ticket shape.", sections=["Summary"]
    )


@spec("FR-008")
def test_the_built_in_formats_are_printed_as_instructions() -> None:
    text = render_formats(resolve_formats(Writeups()), source="Source: example", language=None)

    assert text == "# Write-up formats\n\nSource: example\n\n" + BUILT_IN_TEXT


@spec("FR-008")
def test_the_language_and_shared_rules_come_first() -> None:
    writeups = configuration(
        "writeups:\n  language: Example\n  rules: [Name services as the team does.]\n"
    ).writeups

    text = render_formats(resolve_formats(writeups), source="Source: example", language="Example")
    lines = text.splitlines()

    assert lines[2:5] == ["Source: example", "Language: Example", ""]
    rules = lines[
        lines.index("## Rules for every format") + 1 : lines.index("## ticket (built-in)")
    ]
    assert rules[:4] == [f"- {rule}" for rule in SHARED_RULES]
    assert rules[4] == "- Name services as the team does."
    assert rule_lines(writeups) == len(SHARED_RULES) + 1


def rule_lines(writeups: Writeups) -> int:
    """Count the shared rules printed for a writeups section."""
    text = render_formats(resolve_formats(writeups), source="s", language=None)
    block = text.split("## Rules for every format\n")[1].split("\n\n")[0]
    return len(block.splitlines())


@spec("FR-011")
def test_the_same_configuration_prints_the_same_text() -> None:
    writeups = configuration(
        "writeups:\n  formats:\n    b: {description: x}\n    a: {description: y}\n"
    ).writeups

    first = render_formats(resolve_formats(writeups), source="s", language=None)
    assert render_formats(resolve_formats(writeups), source="s", language=None) == first


# The formats command (User Story 2)


def write_config(directory: Path, text: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "config.yaml").write_text(f"schema_version: 1\n{text}", encoding="utf-8")
    return directory


@spec("FR-009")
@spec("FR-010")
def test_the_command_prints_the_configured_formats(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = write_config(
        tmp_path, "writeups:\n  formats:\n    status-update: {description: x}\n"
    )

    assert main(["writeup", "formats", "--config", str(directory)]) == 0
    out = capsys.readouterr().out
    assert out.startswith(
        f"# Write-up formats\n\nSource: {directory / 'config.yaml'} (from --config)\n"
    )
    assert "## status-update (configured)\nx\n" in out


@spec("FR-010")
def test_a_missing_directory_falls_back_to_the_built_in_formats(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "missing"

    assert main(["writeup", "formats", "--config", str(missing)]) == 0
    assert capsys.readouterr().out == (
        "# Write-up formats\n\n"
        f"Source: none, {missing}: no such directory (from --config); "
        "using the built-in formats\n\n" + BUILT_IN_TEXT
    )


@spec("FR-010")
@spec("FR-018")
def test_an_invalid_configuration_prints_no_format(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = write_config(tmp_path, "writeups:\n  formats:\n    Bad_Name: {description: x}\n")

    assert main(["writeup", "formats", "--config", str(directory)]) == 0
    assert capsys.readouterr().out == (
        "# Write-up formats\n\n"
        f"The configuration in {directory} has 1 problem(s), so no write-up format is available.\n"
        f"Run `opscout config validate --config {directory}` to list them.\n"
    )


@spec("FR-009")
@pytest.mark.parametrize("value", ["", "${user_config.config_dir}"], ids=["empty", "unsubstituted"])
def test_an_empty_or_unsubstituted_config_option_counts_as_absent(
    value: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = write_config(tmp_path, "")
    monkeypatch.setenv("OPSCOUT_CONFIG", str(directory))

    assert main(["writeup", "formats", "--config", value]) == 0
    assert f"Source: {directory / 'config.yaml'} (from OPSCOUT_CONFIG)" in capsys.readouterr().out


def test_printing_the_formats_takes_under_two_seconds() -> None:
    started = time.perf_counter()
    result = subprocess.run(  # noqa: S603  (the interpreter running the tests)
        [
            sys.executable,
            "-m",
            "opscout",
            "writeup",
            "formats",
            "--config",
            str(REPO_ROOT / "example-config"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout
    assert time.perf_counter() - started < 2.0  # SC-004


# The launcher (User Story 3)

LAUNCHER = PLUGIN / "bin" / "opscout"


def run_launcher(
    launcher: Path, *args: str, path: str | None = None
) -> subprocess.CompletedProcess[str]:
    """Run the launcher as Claude Code would: by its path, with PATH holding uv."""
    environment = {**os.environ}
    if path is not None:
        environment["PATH"] = path
    return subprocess.run(  # noqa: S603  (the launcher under test)
        [str(launcher), *args],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
        cwd=launcher.parent,
    )


def copy_plugin(tmp_path: Path, version: str) -> Path:
    """Copy the plugin outside any clone, as an install does, at a given version."""
    copy = tmp_path / "cache" / "opscout" / version
    shutil.copytree(PLUGIN, copy, ignore=shutil.ignore_patterns("evals"))
    manifest = copy / ".claude-plugin" / "plugin.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    manifest.write_text(json.dumps({**data, "version": version}), encoding="utf-8")
    return copy / "bin" / "opscout"


@spec("FR-021")
def test_the_launcher_is_a_python_script_run_through_uv() -> None:
    first_line = LAUNCHER.read_text(encoding="utf-8").splitlines()[0]

    assert first_line == "#!/usr/bin/env -S uv run --script --quiet"
    assert os.access(LAUNCHER, os.X_OK)
    assert "# SPDX-License-Identifier: Apache-2.0" in LAUNCHER.read_text(encoding="utf-8")


@spec("FR-022")
def test_from_a_clone_the_launcher_runs_the_clone(tmp_path: Path) -> None:
    result = run_launcher(LAUNCHER, "--version")

    assert (result.returncode, result.stdout) == (0, f"opscout {__version__}\n")


@spec("FR-025")
def test_the_launcher_passes_arguments_output_and_status_through(tmp_path: Path) -> None:
    missing = tmp_path / "a directory with spaces"

    result = run_launcher(LAUNCHER, "config", "validate", "--config", str(missing))

    assert result.returncode == 1
    assert result.stdout.splitlines()[-1] == f"opscout config: {missing}: no such directory"


@spec("FR-024")
def test_an_installed_plugin_without_a_release_says_what_to_do(tmp_path: Path) -> None:
    result = run_launcher(copy_plugin(tmp_path, "0.0.0"), "writeup", "formats")

    assert result.returncode == 1
    assert "no release" in result.stderr
    assert "claude --plugin-dir" in result.stderr


@spec("FR-023")
def test_an_installed_plugin_runs_exactly_its_release(tmp_path: Path) -> None:
    fake = tmp_path / "fake-bin"
    fake.mkdir()
    (fake / "uvx").write_text(
        f"#!{sys.executable}\nimport json, sys\nprint(json.dumps(sys.argv[1:]))\nsys.exit(7)\n",
        encoding="utf-8",
    )
    (fake / "uvx").chmod(0o755)

    result = run_launcher(
        copy_plugin(tmp_path, "1.2.3"),
        "writeup",
        "formats",
        "--config",
        "two words",
        path=f"{fake}{os.pathsep}{os.environ['PATH']}",
    )

    assert result.returncode == 7
    assert json.loads(result.stdout) == [
        "--quiet",
        "--from",
        "opscout==1.2.3",
        "opscout",
        "writeup",
        "formats",
        "--config",
        "two words",
    ]


@spec("FR-024")
def test_the_readme_states_that_uv_is_required() -> None:
    readme = (PLUGIN / "README.md").read_text(encoding="utf-8")

    assert "uv" in readme
    assert "https://docs.astral.sh/uv/" in readme


# The skill (User Story 1)

SKILL = PLUGIN / "skills" / "summary" / "SKILL.md"
AGENT_SKILLS_FIELDS = {
    "name",
    "description",
    "license",
    "compatibility",
    "metadata",
    "allowed-tools",
}
CLAUDE_CODE_FIELDS = {
    "argument-hint",
    "disable-model-invocation",
    "effort",
    "model",
    "context",
    "agent",
}
INJECTION = (
    "!`\"${CLAUDE_PLUGIN_ROOT}/bin/opscout\" writeup formats --config '${user_config.config_dir}'`"
)


def skill_parts() -> tuple[dict[str, object], str]:
    """Return the skill's frontmatter and body."""
    _, front, body = SKILL.read_text(encoding="utf-8").split("---\n", 2)
    return yaml.safe_load(front), body


@spec("FR-012")
def test_the_skill_follows_the_agent_skills_specification() -> None:
    front, _ = skill_parts()

    assert front["name"] == SKILL.parent.name == "summary"
    assert isinstance(front["description"], str)
    assert 1 <= len(front["description"]) <= 1024
    assert set(front) <= AGENT_SKILLS_FIELDS | CLAUDE_CODE_FIELDS


@spec("FR-013")
def test_the_skill_opens_with_its_contract() -> None:
    _, body = skill_parts()
    contract = body.split("## Contract\n", 1)[1].split("\n## ", 1)[0]

    assert body.lstrip().startswith("# Summary\n\n## Contract\n")
    for part in ("**Deliverable:**", "**Constraints:**", "**Non-goals:**", "**Acceptance:**"):
        assert part in contract
    assert "ruled out" in contract


@spec("FR-014")
def test_the_skill_injects_the_formats_for_the_configured_directory() -> None:
    _, body = skill_parts()

    assert body.count(INJECTION) == 1
    assert [line for line in body.splitlines() if line.startswith("!`")] == [INJECTION]


@spec("FR-019")
@spec("FR-020")
def test_the_skill_pre_approves_only_the_formats_command() -> None:
    front, body = skill_parts()

    assert front["allowed-tools"] == 'Bash("${CLAUDE_PLUGIN_ROOT}/bin/opscout" writeup formats *)'
    assert re.search(r"never (post|call)", body, re.IGNORECASE)


# The eval suite (FR-026 to FR-028)

EVALS = PLUGIN / "evals"
CASE_KEYS = {
    "name",
    "description",
    "tags",
    "plugins",
    "runs",
    "expected_outcome",
    "model",
    "max_turns",
    "timeout_seconds",
    "allowed_tools",
    "append_system_prompt",
    "env",
}
# Scenarios the engine decides, proven by the unit tests above rather than by an eval.
ENGINE_SCENARIOS = {"003-us2-s1", "003-us2-s2", "003-us2-s5", "003-us2-s6"}


def cases() -> dict[str, dict[str, object]]:
    """Return every eval case's frontmatter, by case name."""
    return {
        prompt.parent.name: yaml.safe_load(prompt.read_text(encoding="utf-8").split("---\n")[1])
        for prompt in sorted(EVALS.glob("*/prompt.md"))
    }


def scenarios() -> set[str]:
    """Return the skill's scenarios, as eval case names (003-usN-sM), for stories 1 and 2."""
    text = SPEC_FILE.read_text(encoding="utf-8")
    found = set()
    for story in (1, 2):
        section = text.split(f"### User Story {story} ")[1].split("\n---\n")[0]
        found |= {
            f"003-us{story}-s{n}" for n in re.findall(r"^(\d+)\. \*\*Given\*\*", section, re.M)
        }
    return found


@spec("FR-026")
def test_every_skill_scenario_has_an_eval_case() -> None:
    names = set(cases())

    assert scenarios() - ENGINE_SCENARIOS <= names
    for name in names:
        assert name in scenarios() or re.fullmatch(r"003-edge-[a-z]+(-[a-z]+)*", name), name


@spec("FR-026")
def test_every_case_uses_only_documented_keys_and_synthetic_data() -> None:
    for name, front in cases().items():
        assert set(front) <= CASE_KEYS, name
        assert front["allowed_tools"] == ["Skill"], name
        text = (EVALS / name / "prompt.md").read_text(encoding="utf-8")
        assert scan_text(text, name, allowlist={}, denylist=[]) == [], name


@spec("FR-027")
def test_deterministic_graders_come_first() -> None:
    for name in cases():
        kinds = {
            grader.stem: yaml.safe_load(grader.read_text(encoding="utf-8").split("---\n")[1])[
                "type"
            ]
            for grader in sorted((EVALS / name / "graders").glob("*.md"))
        }
        assert "regex" in kinds.values(), name
        assert [stem for stem, kind in kinds.items() if kind == "llm"] in ([], ["only-facts"]), name


@spec("FR-028")
def test_the_recorded_eval_result_meets_the_threshold() -> None:
    actuals = SPEC_FILE.read_text(encoding="utf-8").split("## Actuals", 1)
    assert len(actuals) == 2, "the eval result is not recorded in the spec yet"
    score = re.search(r"lowest case score: ([0-9.]+)", actuals[1])
    delta = re.search(r"delta over the no-plugin baseline: \+([0-9.]+)", actuals[1])

    assert score is not None
    assert float(score.group(1)) >= 0.9
    assert delta is not None
    assert float(delta.group(1)) > 0


# Proof


@spec("FR-029")
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
