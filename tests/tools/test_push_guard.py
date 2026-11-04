# SPDX-License-Identifier: Apache-2.0
"""The push guard denies the forms that slip past the rule-5 ask rules (AGENTS.md, ADR-0018)."""

import json
from pathlib import Path

import pytest

from tools.hooks.push_guard import ask_prefixes, decide, find_escape

REPO_ROOT = Path(__file__).resolve().parents[2]
SETTINGS = {
    "permissions": {
        "ask": [
            "Bash(git push *)",
            "Bash(gh pr create *)",
            "Bash(gh api *)",
            "Bash(uv publish *)",
            "Bash(twine upload *)",
            "PublishPlugin",
        ]
    }
}
PREFIXES = ask_prefixes(SETTINGS)


def test_the_gated_prefixes_come_from_the_bash_ask_rules() -> None:
    assert PREFIXES == [
        ("git", "push"),
        ("gh", "pr", "create"),
        ("gh", "api"),
        ("uv", "publish"),
        ("twine", "upload"),
    ]


def test_every_bash_ask_rule_in_the_project_settings_is_guarded() -> None:
    settings = json.loads((REPO_ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    bash_rules = [rule for rule in settings["permissions"]["ask"] if rule.startswith("Bash(")]

    assert len(ask_prefixes(settings)) == len(bash_rules)


@pytest.mark.parametrize(
    "command",
    [
        "git -C /srv/repo push",
        "git -c credential.helper= push origin main",
        "git --git-dir=.git push",
        "git --work-tree . push",
        "FOO=1 git push",
        "/usr/bin/git push",
        "command git push",
        "env GIT_TRACE=1 git push",
        "cd repo && git -C . push --tags",
        "git status; git -C repo push",
        "git status\ngit -C repo push",
        "echo $(git push)",
        "echo `git push`",
        "(git push)",
        "bash -c 'git push'",
        'sh -lc "cd repo && git push"',
        "eval git push",
        "xargs -I{} git -C {} push",
        "gh pr -R owner/repo create --fill",
        "uv --directory sub publish",
        "uv run twine upload dist/*",
        # Found by the independent review: forms that broke the parser or hid the push.
        "# don't push yet\ngit -C repo push",
        "git -C repo \\\npush",
        'out="$(git -C repo push)"',
        "bash <<'EOF'\ngit -C repo push\nEOF",
        "cat <<< 'x'\ngit -C repo push",
        "echo $((1<<4))\ngit -C repo push",
        "echo $'it\\'s' && git -C repo push",
    ],
)
def test_forms_the_ask_rules_miss_are_caught(command: str) -> None:
    assert find_escape(command, PREFIXES) is not None


@pytest.mark.parametrize(
    "command",
    [
        "git push",
        "git push origin main",
        "cd repo && git push",
        "git status && git log --oneline",
        "git -C repo status",
        "git -c color.ui=never log",
        "git log --format=%h#x; git push",
        "git commit -m 'git push later'",
        "grep -rn 'git -C repo push' docs",
        "git commit -F - <<'EOF'\nchore: mention git -C repo push\nEOF\ngit status",
        "git commit -F - <<'EOF'\nfix: don't stop\nEOF\ngit status",
        "# a note about git -C repo push\ngit status",
        "echo 'unbalanced",
        "gh pr view 12",
        "gh api repos/owner/repo",
        "uv run pytest",
        "uv publish",
        "ls ~/.gitconfig",
    ],
)
def test_other_commands_pass_through(command: str) -> None:
    assert find_escape(command, PREFIXES) is None


def test_a_denial_names_the_plain_form_to_use() -> None:
    event = {"tool_name": "Bash", "tool_input": {"command": "git -C repo push"}}

    output = decide(event, PREFIXES)

    assert output is not None
    specific = output["hookSpecificOutput"]
    assert specific["hookEventName"] == "PreToolUse"
    assert specific["permissionDecision"] == "deny"
    assert "`git push`" in specific["permissionDecisionReason"]


@pytest.mark.parametrize(
    "event",
    [
        {"tool_name": "Read", "tool_input": {"file_path": "/srv/repo/README.md"}},
        {"tool_name": "Bash", "tool_input": {"command": "git push"}},
        {"tool_name": "Bash", "tool_input": {"command": "echo 'unbalanced"}},
    ],
)
def test_no_decision_is_returned_otherwise(event: dict[str, object]) -> None:
    assert decide(event, PREFIXES) is None


def test_a_command_that_cannot_be_parsed_is_denied_when_it_names_a_gated_command() -> None:
    event = {"tool_name": "Bash", "tool_input": {"command": "echo \"it's\" 'x && git push"}}

    output = decide(event, PREFIXES)

    assert output is not None
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
