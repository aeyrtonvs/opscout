# SPDX-License-Identifier: Apache-2.0
"""The start-up report check and ClaudeCliRunner's contract (spec 007, US3).

ClaudeCliRunner runs against ``fake_claude.py``, which prints streams recorded from Claude
Code 2.1.318 and sanitized (``streams/``). No test starts the real ``claude``.
"""

import json
import sys
import time
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

from opscout.adapters.claude_cli import (
    ClaudeCliRunner,
    ReportError,
    arguments,
    child_environment,
    read_report,
)
from opscout.core.daemon import CHECK, CheckOutput, StartupReport
from opscout.services.daemon import compare_profile
from tests.unit.daemon.fakes import SENTINEL

STREAMS = Path(__file__).parent / "streams"
FAKE = Path(__file__).parent / "fake_claude.py"
PROFILE = CHECK.profile


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 007."""
    return pytest.mark.spec("007", requirement)


def first_event(name: str) -> dict[str, Any]:
    line = (STREAMS / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()[0]
    event: dict[str, Any] = json.loads(line)
    return event


def report(name: str) -> StartupReport:
    return read_report(first_event(name))


class Fake:
    """A copy of the fake ``claude`` with its settings, and its log."""

    def __init__(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "claude"
        # The test's own interpreter, not whatever python3 the child's PATH finds first.
        source = FAKE.read_text(encoding="utf-8").split("\n", 1)[1]
        self.path.write_text(f"#!{sys.executable}\n{source}", encoding="utf-8")
        self.path.chmod(0o755)
        self.log = directory / "log.jsonl"

    def script(self, *streams: str | Path, exit: int = 0, pause: float = 0) -> None:
        paths = [s if isinstance(s, Path) else STREAMS / f"{s}.jsonl" for s in streams]
        settings = {"log": str(self.log), "streams": [str(p) for p in paths], "exit": exit}
        if pause:
            settings["pause"] = pause
        self.path.with_suffix(".json").write_text(json.dumps(settings), encoding="utf-8")

    def starts(self) -> list[dict[str, Any]]:
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]


ENVIRON = {
    "HOME": "/home/example",
    "USER": "example",
    "LOGNAME": "example",
    "PATH": "/usr/bin:/bin",
    "TMPDIR": "/tmp/example",  # noqa: S108  (a reserved value)
    "SHELL": "/bin/zsh",
    "LANG": "en_US.UTF-8",
    "LC_ALL": "en_US.UTF-8",
    "CLAUDE_CONFIG_DIR": "/home/example/.claude",
    "HTTPS_PROXY": "http://proxy.example.com:3128",
    "no_proxy": "example.com",
    "SSL_CERT_FILE": "/etc/example/ca.pem",
    "NODE_EXTRA_CA_CERTS": "/etc/example/ca.pem",
    "ANTHROPIC_API_KEY": SENTINEL,
    "ANTHROPIC_BASE_URL": "https://example.com",
    "CLAUDE_CODE_USE_BEDROCK": "1",
    "CLAUDE_CODE_OAUTH_TOKEN": SENTINEL,
    "AWS_PROFILE": "example-prod",
    "OPSCOUT_CONFIG": "/home/example/config",
    "EXAMPLE_OTHER": "x",
}


@pytest.fixture
def fake(tmp_path: Path) -> Fake:
    return Fake(tmp_path / "bin")


def runner(fake: Fake, tmp_path: Path, **overrides: Any) -> ClaudeCliRunner:
    options: dict[str, Any] = {
        "claude_path": str(fake.path),
        "run_dir": tmp_path / "cache" / "run",
        "environ": ENVIRON,
        "compare": compare_profile,
    }
    options.update(overrides)
    return ClaudeCliRunner(**options)


# The start-up report check (FR-015)


@spec("FR-015")
def test_the_recorded_report_matches_the_check_profile() -> None:
    assert report("success") == StartupReport(
        tools=("StructuredOutput",),
        mcp_servers=(),
        model="claude-haiku-5-5",
        permission_mode="dontAsk",
        plugins=(("example-builtin", "builtin"),),
        api_key_source="none",
        claude_code_version="2.1.318",
    )
    assert compare_profile(PROFILE, report("success")) == ()


@spec("FR-015")
@pytest.mark.parametrize(
    ("stream", "difference"),
    [
        ("extra_tools", "tools: expected [StructuredOutput], got [Bash, StructuredOutput]"),
        ("mcp_server", "tool servers: expected [], got [example]"),
        ("permission_mode", "permission mode: expected dontAsk, got default"),
        ("user_plugin", "plugins: expected only built-in plugins, got example"),
        ("old_version", "Claude Code version: expected 2.1.318 or later, got 2.1.300"),
    ],
)
def test_each_difference_is_named(stream: str, difference: str) -> None:
    assert difference in compare_profile(PROFILE, report(stream))


@spec("FR-015")
def test_the_model_must_be_of_the_alias_family_or_the_exact_id() -> None:
    sonnet = replace(report("success"), model="claude-sonnet-5-5")
    assert compare_profile(PROFILE, sonnet) == ("model: expected haiku, got claude-sonnet-5-5",)
    exact = replace(PROFILE, model="claude-haiku-5-5")
    assert compare_profile(exact, report("success")) == ()
    other = replace(PROFILE, model="claude-haiku-5-0")
    assert compare_profile(other, report("success")) != ()


@spec("FR-015")
def test_declared_tools_and_servers_are_expected() -> None:
    profile = replace(
        PROFILE,
        tools=("mcp__example__lookup",),
        mcp_servers=MappingProxyType({"example": {"command": "/opt/example/bin/server"}}),
    )
    assert compare_profile(profile, report("mcp_server")) == ()
    assert compare_profile(profile, report("success")) != ()


@spec("FR-015")
@pytest.mark.parametrize(
    "missing",
    ["tools", "mcp_servers", "model", "permissionMode", "plugins", "apiKeySource",
     "claude_code_version"],
)  # fmt: skip
def test_a_report_without_a_field_is_refused(missing: str) -> None:
    event = first_event("success")
    del event[missing]
    with pytest.raises(ReportError, match=missing):
        read_report(event)


@spec("FR-015")
def test_a_version_that_cannot_be_read_differs() -> None:
    odd = replace(report("success"), claude_code_version="next")
    assert compare_profile(PROFILE, odd) == (
        "Claude Code version: expected 2.1.318 or later, got next",
    )


# The runner's contract (FR-014, FR-016 to FR-018)


@spec("FR-014")
def test_every_restriction_is_passed_explicitly() -> None:
    schema = json.dumps(CheckOutput.model_json_schema(), separators=(",", ":"), sort_keys=True)
    assert arguments(PROFILE) == [
        "-p",
        "--output-format", "stream-json",
        "--verbose",
        "--safe-mode",
        "--restricted",
        "--tools", "",
        "--strict-mcp-config",
        "--permission-mode", "dontAsk",
        "--permission-prompts", "none",
        "--no-session-persistence",
        "--model", "haiku",
        "--max-budget-usd", "0.05",
        "--max-turns", "3",
        "--json-schema", schema,
    ]  # fmt: skip


@spec("FR-014")
def test_declared_tools_and_servers_are_passed() -> None:
    profile = replace(
        PROFILE,
        tools=("Read", "mcp__example__lookup"),
        mcp_servers=MappingProxyType({"example": {"command": "/opt/example/bin/server"}}),
    )
    passed = arguments(profile)
    assert passed[passed.index("--tools") + 1] == "Read,mcp__example__lookup"
    config = passed[passed.index("--mcp-config") + 1]
    assert json.loads(config) == {"mcpServers": {"example": {"command": "/opt/example/bin/server"}}}
    assert passed.index("--strict-mcp-config") < passed.index("--mcp-config")


@spec("FR-014")
def test_the_prompt_goes_on_standard_input_in_an_empty_directory(
    fake: Fake, tmp_path: Path
) -> None:
    fake.script("success")
    result = runner(fake, tmp_path).run(PROFILE, CHECK.prompt, {})
    assert result.status == "ok"
    [start] = fake.starts()
    assert start["argv"] == arguments(PROFILE)
    assert start["stdin"] == CHECK.prompt
    assert CHECK.prompt not in json.dumps(start["argv"])
    assert Path(start["cwd"]).resolve() == (tmp_path / "cache" / "run").resolve()
    assert list((tmp_path / "cache" / "run").iterdir()) == []


@spec("FR-018")
def test_a_valid_output_returns_the_run_s_own_facts(fake: Fake, tmp_path: Path) -> None:
    fake.script("success")
    result = runner(fake, tmp_path).run(PROFILE, CHECK.prompt, {})
    assert result.output == CheckOutput(ok=True, note="The scheduled self-check reached the model.")
    assert result.facts is not None
    assert result.facts.model_dump() == {
        "claude_code_version": "2.1.318",
        "model": "claude-haiku-5-5",
        "api_key_source": "none",
        "cost_usd": 0.0005,
        "turns": 2,
        "duration_ms": 1250,
        "tools_called": ("StructuredOutput",),
        "attempts": 1,
    }


@spec("FR-015")
def test_a_refused_report_stops_the_child_and_keeps_no_output(fake: Fake, tmp_path: Path) -> None:
    fake.script("extra_tools", pause=30)
    began = time.monotonic()
    result = runner(fake, tmp_path).run(PROFILE, CHECK.prompt, {})
    assert time.monotonic() - began < 10
    assert result.status == "refused"
    assert result.output is None
    assert result.differences == (
        "tools: expected [StructuredOutput], got [Bash, StructuredOutput]",
    )
    assert result.facts is not None
    assert result.facts.claude_code_version == "2.1.318"


@spec("FR-015")
def test_a_stream_without_its_report_is_refused(fake: Fake, tmp_path: Path) -> None:
    fake.script("no_report")
    result = runner(fake, tmp_path).run(PROFILE, CHECK.prompt, {})
    assert result.status == "refused"
    assert result.differences == ("the first event was not the start-up report",)


@spec("FR-016")
def test_an_invalid_output_is_retried_once_with_the_validator_s_message(
    fake: Fake, tmp_path: Path
) -> None:
    fake.script("invalid_output", "success")
    result = runner(fake, tmp_path).run(PROFILE, CHECK.prompt, {})
    assert result.status == "ok"
    first, second = fake.starts()
    assert first["stdin"] == CHECK.prompt
    assert second["stdin"].startswith(CHECK.prompt)
    assert "ok: Input should be a valid boolean" in second["stdin"]
    assert "note: Field required" in second["stdin"]
    assert result.facts is not None
    assert (result.facts.attempts, result.facts.turns, result.facts.cost_usd) == (2, 4, 0.001)
    assert result.facts.duration_ms == 2500


@spec("FR-016")
def test_a_second_invalid_output_is_inconclusive(fake: Fake, tmp_path: Path) -> None:
    fake.script("invalid_output")
    result = runner(fake, tmp_path).run(PROFILE, CHECK.prompt, {})
    assert result.status == "invalid_output"
    assert result.reason is not None
    assert "note: Field required" in result.reason
    assert len(fake.starts()) == 2


@spec("FR-016")
def test_a_budget_error_is_not_retried(fake: Fake, tmp_path: Path) -> None:
    fake.script("budget", exit=1)
    result = runner(fake, tmp_path).run(PROFILE, CHECK.prompt, {})
    assert result.status == "error"
    assert result.reason == "error_max_budget_usd: Reached maximum budget ($1e-7)"
    assert len(fake.starts()) == 1
    assert result.facts is not None
    assert result.facts.cost_usd == 0.0005


@spec("FR-016")
def test_an_exit_without_a_stream_is_an_error(fake: Fake, tmp_path: Path) -> None:
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    fake.script(empty, exit=3)
    result = runner(fake, tmp_path).run(PROFILE, CHECK.prompt, {})
    assert result.status == "error"
    assert result.reason is not None
    assert "status 3" in result.reason


@spec("FR-016")
def test_a_stream_without_a_result_is_an_error(fake: Fake, tmp_path: Path) -> None:
    cut = tmp_path / "cut.jsonl"
    cut.write_text(
        (STREAMS / "success.jsonl").read_text(encoding="utf-8").splitlines()[0] + "\n",
        encoding="utf-8",
    )
    fake.script(cut, exit=1)
    result = runner(fake, tmp_path).run(PROFILE, CHECK.prompt, {})
    assert result.status == "error"
    assert result.reason == "Claude Code exited with status 1 without a result"


@spec("FR-016")
def test_a_run_that_takes_too_long_is_stopped(fake: Fake, tmp_path: Path) -> None:
    fake.script("success", pause=30)
    result = runner(fake, tmp_path, timeout=1).run(PROFILE, CHECK.prompt, {})
    assert result.status == "error"
    assert result.reason == "Claude Code took longer than 1 s and was stopped"


@spec("FR-017")
def test_the_child_gets_only_the_allow_list_and_the_declared_secrets(
    fake: Fake, tmp_path: Path
) -> None:
    allowed = {
        name: value
        for name, value in ENVIRON.items()
        if not name.startswith(("ANTHROPIC_", "CLAUDE_CODE_", "AWS_", "OPSCOUT_", "EXAMPLE_"))
    }
    assert child_environment(ENVIRON, {}) == allowed
    assert child_environment(ENVIRON, {"CLAUDE_CODE_OAUTH_TOKEN": "declared"}) == {
        **allowed,
        "CLAUDE_CODE_OAUTH_TOKEN": "declared",
    }
    fake.script("success")
    runner(fake, tmp_path).run(PROFILE, CHECK.prompt, {"CLAUDE_CODE_OAUTH_TOKEN": "declared"})
    environment = fake.starts()[0]["env"]
    assert "ANTHROPIC_API_KEY" not in environment
    assert "AWS_PROFILE" not in environment
    assert environment["CLAUDE_CODE_OAUTH_TOKEN"] == "declared"  # noqa: S105  (a fake)
    assert environment["HOME"] == "/home/example"


@spec("FR-017")
def test_the_executable_comes_from_the_configuration_then_the_path(
    fake: Fake, tmp_path: Path
) -> None:
    fake.script("success")
    on_path = {**ENVIRON, "PATH": f"{fake.path.parent}:/usr/bin:/bin"}
    assert (
        runner(fake, tmp_path, claude_path=None, environ=on_path)
        .run(PROFILE, CHECK.prompt, {})
        .status
        == "ok"
    )

    missing = runner(fake, tmp_path, claude_path="/missing/claude").run(PROFILE, CHECK.prompt, {})
    assert missing.status == "error"
    assert missing.reason == "Claude Code not found at /missing/claude (daemon.claude_path)"

    nowhere = runner(fake, tmp_path, claude_path=None, environ={"PATH": "/missing"})
    result = nowhere.run(PROFILE, CHECK.prompt, {})
    assert result.reason == (
        "Claude Code not found: daemon.claude_path is not set and claude is not on PATH (/missing)"
    )
