# SPDX-License-Identifier: Apache-2.0
"""The standup job end to end, with fakes in the composition root (spec 009)."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from opscout.core.daemon import RunnerFacts, RunProfile, RunResult
from opscout.core.standup import Commit, PullRequest, SessionPrompts
from opscout.entrypoints import daemon as composition
from opscout.entrypoints.cli import main
from tests.unit.chat.fakes import FakeChat, FakeTime
from tests.unit.daemon.fakes import (
    Clock,
    MemoryDelivery,
    MemoryRunStore,
    MemoryScheduler,
    MemorySecretStore,
)
from tests.unit.standup.fakes import API, FakeCodeHost, FakeCommits, FakeTranscripts, at

SENTINEL = "sentinel-prompt-secret-AKIAEXAMPLEEXAMPLE99"
FACTS = RunnerFacts(
    claude_code_version="2.1.318", model="claude-sonnet-5-5", api_key_source="none",
    cost_usd=0.02, turns=2, duration_ms=4000, tools_called=("StructuredOutput",), attempts=1,
)  # fmt: skip
CONFIG = f"""\
schema_version: 1
standup:
  identities: [dev@example.com]
  code_host:
    service: bitbucket
    login: dev@example.com
  projects:
    example-api:
      paths: [{API}]
      repositories: [example-workspace/example-api]
daemon:
  jobs:
    standup:
      at: "09:45"
      weekdays: [mon, tue, wed, thu, fri]
  secrets:
    bitbucket_token:
      service: opscout-bitbucket
"""
REPO = "example-workspace/example-api"


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 009."""
    return pytest.mark.spec("009", requirement)


GOOD = {
    "yesterday": [
        {"project": "example-api", "text": "Fixed the export retry", "facts": ["s1"]},
        {"project": "example-api", "text": "Committed the retry", "facts": ["c1"]},
        {"project": "example-api", "text": "Merged the export endpoint", "facts": ["p1"]},
    ],
    "today": [{"text": "Get the retry reviewed", "facts": ["p2"]}],
    "blockers": [],
}


@dataclass
class ValidatingRunner:
    """Validates scripted outputs as ClaudeCliRunner does, with the run's context."""

    outputs: list[dict[str, Any]]
    calls: list[tuple[RunProfile, str]] = field(default_factory=list)

    def run(self, profile: RunProfile, prompt: str, env: Mapping[str, str]) -> RunResult:
        message = ""
        for attempt in range(2):
            self.calls.append((profile, prompt + message))
            raw = self.outputs[min(len(self.calls) - 1, len(self.outputs) - 1)]
            try:
                output = profile.output.model_validate(
                    raw, context=dict(profile.validation_context or {})
                )
            except ValidationError as error:
                message = f"\n\nInvalid: {error}"
                if attempt == 1:
                    return RunResult("invalid_output", reason=str(error), facts=FACTS)
                continue
            return RunResult("ok", output=output, facts=FACTS)
        raise AssertionError("unreachable")


@dataclass
class World:
    config: Path
    runner: ValidatingRunner = field(default_factory=lambda: ValidatingRunner([GOOD]))
    store: MemoryRunStore = field(default_factory=MemoryRunStore)
    delivery: MemoryDelivery = field(default_factory=MemoryDelivery)
    keychain: MemorySecretStore = field(default_factory=MemorySecretStore)
    transcripts: FakeTranscripts = field(default_factory=FakeTranscripts)
    commits: FakeCommits = field(default_factory=FakeCommits)
    host: FakeCodeHost = field(default_factory=FakeCodeHost)
    chat: FakeChat = field(default_factory=FakeChat)

    def write(self, text: str) -> None:
        (self.config / "config.yaml").write_text(text, encoding="utf-8")


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    return make_world(tmp_path, monkeypatch)


def make_world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    """Build the fakes and wire them into the composition root."""
    config = tmp_path / "config"
    config.mkdir()
    made = World(config=config)
    made.write(CONFIG)
    made.keychain.values[("opscout-bitbucket", "opscout")] = "bitbucket-token-example"
    made.transcripts.sessions = [
        SessionPrompts("s", API, ((at(4, 8), f"Fix the export retry; key {SENTINEL}"),))
    ]
    made.commits.by_path = {API: [Commit("a" * 40, at(4, 11), "refs/heads/main", "Retry export")]}
    made.host.closed_prs = {REPO: [_pull(41, "Add export endpoint", "MERGED")]}
    made.host.open_prs = {REPO: [_pull(42, "Retry export job", "OPEN")]}

    def code_host(login: str, token: Any) -> FakeCodeHost:
        made.host.token = token
        return made.host

    def wiring() -> composition.Wiring:
        return composition.Wiring(
            directories=composition.Directories(
                data=tmp_path / "data", log=tmp_path / "log", cache=tmp_path / "cache"
            ),
            environ={"PATH": "/usr/bin:/bin"},
            clock=Clock([at(5, 9, 45)]),
            runner=lambda daemon, run_dir: made.runner,
            store=made.store,
            delivery=made.delivery,
            secrets=made.keychain,
            scheduler=MemoryScheduler(),
            engine_command=lambda: ["/opt/example/bin/uv", "run", "opscout"],
            path_exists=lambda path: True,
            is_terminal=lambda: False,
            ask=lambda prompt: "",
            read_secret=lambda prompt: "",
            which=lambda name, search: None,
            sleep=FakeTime().sleep,
            transcripts=lambda: made.transcripts,
            commits=lambda: made.commits,
            code_host=code_host,
        )

    monkeypatch.setattr(composition, "wiring", wiring)
    return made


def _pull(number: int, title: str, state: str) -> PullRequest:
    return PullRequest(REPO, number, title, state, at(4, 10), at(4, 12), "feature/x")


def run(world: World, *arguments: str) -> int:
    return main([*arguments, "--config", str(world.config)])


@spec("FR-015")
def test_a_daily_is_gathered_written_checked_and_delivered(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(world, "run", "standup") == 0
    [(profile, prompt)] = world.runner.calls
    assert profile.tools == ()
    assert (profile.model, profile.budget_usd, profile.max_turns) == ("haiku", 0.1, 3)
    assert set(profile.validation_context["facts"]) == {"s1", "c1", "p1", "p2"}  # type: ignore[index]
    assert "Days covered: Wednesday 4." in prompt
    [(_, _, kind, text)] = world.delivery.sent
    assert kind == "result"
    assert text.startswith("# Standup, Wednesday 4\n")
    assert "- example-api: Fixed the export retry" in text
    assert "## Blockers\n- None." in text
    assert world.host.token is not None
    assert world.host.token() == "bitbucket-token-example"


@spec("FR-003")
def test_a_monday_covers_the_weekend_and_a_second_start_gathers_nothing(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = composition.wiring
    from dataclasses import replace

    monkeypatch.setattr(composition, "wiring", lambda: replace(real(), clock=Clock([at(9, 9, 45)])))
    # By Monday the pull request opened on Wednesday waited a full working day: a blocker.
    world.runner.outputs = [
        {**GOOD, "today": [], "blockers": [{"text": "Retry waits for review", "facts": ["p2"]}]}
    ]
    assert run(world, "run", "standup") == 0
    assert "Days covered: Friday 6 to Sunday 8." in world.runner.calls[0][1]
    calls = len(world.host.calls)
    assert run(world, "run", "standup") == 0  # skipped: already delivered
    assert len(world.host.calls) == calls
    assert run(world, "run", "standup", "--force") == 0
    assert len(world.host.calls) > calls


@spec("FR-013")
def test_the_record_holds_references_and_nothing_private_leaves(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(world, "run", "standup") == 0
    [record] = world.store.saved
    assert "sessions:1" in record.inputs
    assert "facts:s1,c1,p1,p2" in record.inputs
    assert "redacted:credential=1" in record.inputs
    everything = record.model_dump_json() + capsys.readouterr().out
    everything += "".join(prompt for _, prompt in world.runner.calls)
    everything += "".join(text for *_, text in world.delivery.sent)
    assert SENTINEL not in everything
    assert "Fix the export retry" not in record.model_dump_json()


@spec("FR-011")
def test_an_output_citing_unknown_facts_is_retried_then_inconclusive(world: World) -> None:
    bad = {**GOOD, "today": [{"text": "Invented", "facts": ["x9"]}]}
    world.runner.outputs = [bad, bad]
    assert run(world, "run", "standup") == 1
    [record] = world.store.saved
    assert record.outcome == "inconclusive"
    assert "unknown fact x9" in (record.reason or "")
    assert "unknown fact x9" in world.runner.calls[1][1]
    world.runner.outputs = [bad, GOOD]
    world.store.saved.clear()
    assert run(world, "run", "standup", "--force") == 0


@spec("FR-016")
def test_a_quiet_window_is_said_without_the_model(world: World) -> None:
    world.transcripts.sessions = []
    world.commits.by_path = {}
    world.host.closed_prs = {}
    assert run(world, "run", "standup") == 0
    assert world.runner.calls == []
    [(_, _, _, text)] = world.delivery.sent
    assert "No recorded activity since Wednesday 4." in text
    assert '"Retry export job" open' in text  # the open work, still listed
    [record] = world.store.saved
    assert record.runner is None


@spec("FR-008")
def test_a_missing_source_is_named_with_the_command_that_helps(world: World) -> None:
    world.keychain.values.clear()
    world.runner.outputs = [
        {
            "yesterday": [
                {"project": "example-api", "text": "Fixed the export retry", "facts": ["s1", "c1"]}
            ],
            "today": [],
            "blockers": [],
        }
    ]
    assert run(world, "run", "standup") == 0
    [(_, _, _, text)] = world.delivery.sent
    assert "Bitbucket: missing (" in text
    assert "opscout secret set bitbucket_token" in text


@spec("FR-017")
def test_without_the_section_the_job_cannot_start(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    world.write("schema_version: 1\n")
    assert run(world, "run", "standup") == 2
    assert "standup section" in capsys.readouterr().err
