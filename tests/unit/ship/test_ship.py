# SPDX-License-Identifier: Apache-2.0
"""The ship skill: conventions, checks, the push guard, the skill (spec 004).

Every test is tied to its requirements with ``@pytest.mark.spec("004", ...)``; eval cases
name theirs in their ``tags``. Scratch repositories with a local remote only.
"""

import io
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

import pydantic
import pytest
import yaml

from opscout.core.config import (
    CONVENTIONAL_TYPES,
    Configuration,
    InvalidConfigError,
    Ship,
)
from opscout.core.ship import PushDecision
from opscout.entrypoints.cli import main
from opscout.services.config import parse_config
from opscout.services.ship import decide_push, read_command

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


# The push guard (User Story 1)

PATTERNS = ("main", "master", "release/*")


def decision(
    command: str, *, current: str | None = "feat/add-guard", default: str | None = "main"
) -> PushDecision | None:
    """Return the guard's decision for one command, with the branches a repository would give."""
    read = read_command(command)
    if read is None or isinstance(read, PushDecision):
        return read
    return decide_push(read, current=current, default=default, patterns=PATTERNS)


ASKED = [
    ("git push", "origin: feat/add-guard"),
    ("git push origin", "origin: feat/add-guard"),
    ("git push -u origin feat/add-guard", "origin: feat/add-guard"),
    ("git push --set-upstream origin HEAD", "origin: feat/add-guard"),
    ("git push origin HEAD:refs/heads/feat/other", "origin: feat/other"),
    ("git push --force-with-lease origin feat/add-guard", "(force)"),
    ("git push origin +feat/add-guard", "(force)"),
    ("git push --tags origin", "origin: feat/add-guard"),
    ("git push origin refs/tags/v1.0.0", "origin: refs/tags/v1.0.0"),
    ("git -C sub push origin feat/x", "origin: feat/x"),
    ("git push --dry-run --no-verify -q origin feat/x", "origin: feat/x"),
]


@spec("FR-007")
@pytest.mark.parametrize(("command", "named"), ASKED)
def test_a_plain_push_is_asked_and_named(command: str, named: str) -> None:
    result = decision(command)

    assert result is not None
    assert result.verdict == "ask"
    assert named in result.reason


DENIED_PROTECTED = [
    ("git push origin main", "main"),
    ("git push origin HEAD:main", "main"),
    ("git push origin feat/x:refs/heads/master", "master"),
    ("git push origin release/1.2", "release/1.2"),
    ("git push origin :main", "main"),
    ("git push --delete origin release/1.2", "release/1.2"),
    ("git push -f origin HEAD:main", "main"),
]


@spec("FR-008")
@pytest.mark.parametrize(("command", "branch"), DENIED_PROTECTED)
def test_a_push_to_a_protected_branch_is_denied(command: str, branch: str) -> None:
    result = decision(command)

    assert result is not None
    assert result.verdict == "deny"
    assert f"{branch} is protected" in result.reason


@spec("FR-008")
@pytest.mark.parametrize("current", ["main", "release/2.0", "develop"])
def test_pushing_from_a_protected_branch_is_denied(current: str) -> None:
    result = decision("git push", current=current, default="develop")

    assert result is not None
    assert result.verdict == "deny"
    assert current in result.reason


@spec("FR-009")
@pytest.mark.parametrize(
    "command", ["git push --all", "git push --mirror origin", "git push --branches"]
)
def test_pushing_every_branch_is_denied(command: str) -> None:
    result = decision(command)

    assert result is not None
    assert result.verdict == "deny"


@spec("FR-009")
def test_a_push_from_a_detached_head_without_a_refspec_is_denied() -> None:
    result = decision("git push origin", current=None)

    assert result is not None
    assert (result.verdict, "detached" in result.reason) == ("deny", True)


UNREADABLE = [
    "git status && git push",
    "git push; echo done",
    "FOO=1 git push",
    "env git push",
    "sudo git push",
    "bash -c 'git push'",
    'sh -c "git push origin main"',
    "eval git push",
    "git -c core.hooksPath=/dev/null push",
    "git --git-dir=.git push",
    'git push origin "$(git branch --show-current)"',
    "git push origin `whoami`",
    "git push --prune origin",
    "git push --repo=origin",
    "git push 'unterminated",
    "(git push)",
    "git push origin feat/x | tee log",
    "echo git push",
    "cd sub\ngit push",
    "git add -A && gh pr create --draft",
]


@spec("FR-010")
@pytest.mark.parametrize("command", UNREADABLE)
def test_a_push_in_a_form_the_guard_cannot_read_is_denied(command: str) -> None:
    result = decision(command)

    assert result is not None
    assert result.verdict == "deny"
    assert "plain" in result.reason


@spec("FR-011")
def test_opening_a_pull_request_is_asked() -> None:
    result = decision("gh pr create --draft --base main --title 'feat: x' --body 'y'")

    assert result is not None
    assert result.verdict == "ask"


@spec("FR-011")
@pytest.mark.parametrize(
    "command",
    [
        "git status",
        "git commit -m 'fix: push the fix'",
        "git log --grep push",
        'grep -r "git push" docs',
        "ls -la",
        "gh pr view 6",
        "uv run pytest",
        "git switch -c feat/x && git add -A",
    ],
)
def test_other_commands_are_left_alone(command: str) -> None:
    assert decision(command) is None


# The hook (User Story 1)


def git(directory: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(directory), *args], check=True, capture_output=True)  # noqa: S603, S607


def scratch_repository(
    tmp_path: Path, *, default: str = "main", current: str = "feat/add-guard"
) -> Path:
    """A repository on ``current`` whose remote ``origin`` has ``default`` as its default branch."""
    repository = tmp_path / "repository"
    repository.mkdir()
    git(repository, "init", "-q", "-b", "main")
    git(repository, "config", "user.email", "test@example.com")
    git(repository, "config", "user.name", "Test")
    git(repository, "commit", "-q", "--allow-empty", "-m", "chore: start")
    git(repository, "remote", "add", "origin", str(tmp_path / "remote.git"))
    git(repository, "update-ref", f"refs/remotes/origin/{default}", "HEAD")
    git(repository, "symbolic-ref", "refs/remotes/origin/HEAD", f"refs/remotes/origin/{default}")
    if current != "main":
        git(repository, "switch", "-q", "-c", current)
    return repository


def hook(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    event: dict[str, object] | str,
    *,
    config: str = "",
) -> tuple[int, dict[str, Any] | None, str]:
    """Run ``opscout hook pre-tool-use`` with an event on stdin; return status, JSON, stderr."""
    text = event if isinstance(event, str) else json.dumps(event)
    monkeypatch.setattr("sys.stdin", io.StringIO(text))
    try:
        status = main(["hook", "pre-tool-use", "--config", config])
    except SystemExit as exit_info:
        status = int(exit_info.code or 0)
    captured = capsys.readouterr()
    return status, json.loads(captured.out) if captured.out.strip() else None, captured.err


def bash(command: str, cwd: Path) -> dict[str, object]:
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}


@spec("FR-007")
def test_the_hook_asks_for_a_push_of_the_current_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repository = scratch_repository(tmp_path)
    monkeypatch.setenv("OPSCOUT_CONFIG", str(tmp_path / "none"))

    status, output, _ = hook(monkeypatch, capsys, bash("git push", repository))

    assert status == 0
    assert output == {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": "opscout: push to origin: feat/add-guard?",
        }
    }


@spec("FR-008")
@pytest.mark.parametrize(
    ("current", "default", "command", "branch"),
    [
        ("main", "main", "git push", "main"),
        ("feat/x", "develop", "git push origin develop", "develop"),
        ("develop", "develop", "git push", "develop"),
    ],
    ids=["current-main", "default-by-name", "current-default"],
)
def test_the_hook_reads_the_branches_from_the_repository(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    current: str,
    default: str,
    command: str,
    branch: str,
) -> None:
    repository = scratch_repository(tmp_path, default=default, current=current)
    monkeypatch.setenv("OPSCOUT_CONFIG", str(tmp_path / "none"))

    _, output, _ = hook(monkeypatch, capsys, bash(command, repository))

    assert output is not None
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert f"{branch} is protected" in output["hookSpecificOutput"]["permissionDecisionReason"]


@spec("FR-007")
def test_the_hook_reads_the_branch_of_the_directory_after_minus_c(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repository = scratch_repository(tmp_path, current="main")
    monkeypatch.setenv("OPSCOUT_CONFIG", str(tmp_path / "none"))

    _, output, _ = hook(monkeypatch, capsys, bash(f"git -C {repository} push", tmp_path))

    assert output is not None
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"


@spec("FR-012")
def test_the_hook_reads_the_protected_patterns_from_the_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repository = scratch_repository(tmp_path)
    config = tmp_path / "config"
    config.mkdir()
    (config / "config.yaml").write_text(
        "schema_version: 1\nship:\n  protected_branches: ['release/*']\n", encoding="utf-8"
    )

    _, output, _ = hook(
        monkeypatch, capsys, bash("git push origin release/1.2", repository), config=str(config)
    )

    assert output is not None
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"


@spec("FR-012")
@pytest.mark.parametrize(
    "configuration_text",
    [None, "schema_version: 1\nship: {types: []}\n"],
    ids=["missing", "invalid"],
)
def test_without_a_readable_configuration_main_stays_protected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    configuration_text: str | None,
) -> None:
    repository = scratch_repository(tmp_path, default="trunk")
    config = tmp_path / "config"
    if configuration_text is not None:
        config.mkdir()
        (config / "config.yaml").write_text(configuration_text, encoding="utf-8")

    for command in ("git push origin main", "git push origin master", "git push origin trunk"):
        _, output, _ = hook(monkeypatch, capsys, bash(command, repository), config=str(config))
        assert output is not None
        assert output["hookSpecificOutput"]["permissionDecision"] == "deny", command


@spec("FR-013")
@pytest.mark.parametrize(
    "event", ["not json", '{"tool_name": "Bash"}'], ids=["malformed", "no-command"]
)
def test_an_event_the_hook_cannot_read_blocks_the_command(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], event: str
) -> None:
    status, output, error = hook(monkeypatch, capsys, event)

    assert (status, output) == (2, None)
    assert "opscout push guard" in error


@spec("FR-011")
def test_the_hook_is_silent_for_other_tools_and_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    other: dict[str, object] = {
        "tool_name": "Read",
        "tool_input": {"file_path": "x"},
        "cwd": str(tmp_path),
    }

    assert hook(monkeypatch, capsys, other)[:2] == (0, None)
    assert hook(monkeypatch, capsys, bash("git status", tmp_path))[:2] == (0, None)


@spec("FR-006")
def test_the_plugin_declares_the_hook_so_that_a_failure_blocks() -> None:
    hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    (entry,) = hooks["hooks"]["PreToolUse"]
    (command,) = entry["hooks"]

    assert entry["matcher"] == "Bash"
    assert command["type"] == "command"
    assert command["command"] == "${CLAUDE_PLUGIN_ROOT}/bin/opscout"
    assert command["args"] == ["hook", "pre-tool-use", "--config", "${user_config.config_dir}"]
    assert command["onFailure"] == "block"


@spec("FR-013")
def test_the_guard_decides_in_under_a_second(tmp_path: Path) -> None:
    repository = scratch_repository(tmp_path)
    event = json.dumps(bash("git push origin HEAD:main", repository))
    started = time.perf_counter()
    result = subprocess.run(  # noqa: S603  (the launcher under test)
        [
            str(PLUGIN / "bin" / "opscout"),
            "hook",
            "pre-tool-use",
            "--config",
            "${user_config.config_dir}",
        ],
        input=event,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert '"deny"' in result.stdout
    assert time.perf_counter() - started < 1.0  # SC-004


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
