# SPDX-License-Identifier: Apache-2.0
"""The commands with chat configured, through fakes in the composition root (spec 008)."""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import timedelta
from pathlib import Path

import pytest

from opscout.adapters.run_files import GatewayFiles
from opscout.core.chat import Choice, GatewayStatus, Ignored
from opscout.core.daemon import CheckOutput, RunnerFacts, RunResult
from opscout.entrypoints import daemon as composition
from opscout.entrypoints.cli import main
from tests.unit.chat.fakes import TOKEN_SENTINEL, USER, FakeChat, FakeTime
from tests.unit.daemon.fakes import (
    START,
    Clock,
    MemoryDelivery,
    MemoryRunStore,
    MemoryScheduler,
    MemorySecretStore,
    ScriptedRunner,
)

FACTS = RunnerFacts(
    claude_code_version="2.1.318",
    model="claude-haiku-5-5",
    api_key_source="none",
    cost_usd=0.0005,
    turns=2,
    duration_ms=1250,
    tools_called=("StructuredOutput",),
    attempts=1,
)
OK = RunResult("ok", output=CheckOutput(ok=True, note="Fine."), facts=FACTS)
JOBS = 'daemon:\n  jobs:\n    check:\n      at: "09:30"\n'
CHAT = (
    "  chat:\n    service: slack\n    user: UEXAMPLE01\n"
    "  secrets:\n    slack_bot_token:\n      service: opscout-slack-bot\n"
    "    slack_app_token:\n      service: opscout-slack-app\n"
)


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 008."""
    return pytest.mark.spec("008", requirement)


@dataclass
class Fakes:
    config: Path
    directories: composition.Directories
    runner: ScriptedRunner = field(default_factory=lambda: ScriptedRunner([OK]))
    store: MemoryRunStore = field(default_factory=MemoryRunStore)
    delivery: MemoryDelivery = field(default_factory=MemoryDelivery)
    keychain: MemorySecretStore = field(default_factory=MemorySecretStore)
    scheduler: MemoryScheduler | None = field(default_factory=MemoryScheduler)
    chat: FakeChat = field(default_factory=FakeChat)
    time: FakeTime = field(default_factory=FakeTime)
    tokens: list[Callable[[], str]] = field(default_factory=list)

    def write(self, text: str) -> None:
        (self.config / "config.yaml").write_text(f"schema_version: 1\n{text}", encoding="utf-8")


@pytest.fixture
def fakes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Fakes:
    config = tmp_path / "config"
    config.mkdir()
    directories = composition.Directories(
        data=tmp_path / "data", log=tmp_path / "log", cache=tmp_path / "cache"
    )
    world = Fakes(config=config, directories=directories)
    world.write(JOBS + CHAT)
    world.keychain.values[("opscout-slack-bot", "opscout")] = TOKEN_SENTINEL
    world.keychain.values[("opscout-slack-app", "opscout")] = TOKEN_SENTINEL

    def chat(token: Callable[[], str]) -> FakeChat:
        world.tokens.append(token)  # resolved only when the adapter needs it
        return world.chat

    def wiring() -> composition.Wiring:
        return composition.Wiring(
            directories=directories,
            environ={"PATH": "/usr/bin:/bin"},
            clock=Clock(),
            runner=lambda daemon, run_dir: world.runner,
            store=world.store,
            delivery=world.delivery,
            secrets=world.keychain,
            scheduler=world.scheduler,
            engine_command=lambda: ["/opt/example/bin/uv", "run", "--project", "/opt/x", "opscout"],
            path_exists=lambda path: True,
            is_terminal=lambda: False,
            ask=lambda prompt: "",
            read_secret=lambda prompt: "",
            which=lambda name, search: None,
            chat=chat,
            sleep=world.time.sleep,
        )

    monkeypatch.setattr(composition, "wiring", wiring)
    return world


def run(fakes: Fakes, *arguments: str) -> int:
    return main([*arguments, "--config", str(fakes.config)])


@spec("FR-006")
def test_a_run_delivers_by_direct_message_and_records_it(
    fakes: Fakes, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(fakes, "run", "check") == 0
    [record] = fakes.store.saved
    assert record.outcome == "delivered"
    assert record.chat is not None
    assert record.delivery is not None
    assert capsys.readouterr().out == f"check 2026-11-05: delivered to {record.delivery}\n"
    [(user, message)] = fakes.chat.sent
    assert user == USER
    assert message.buttons == f"check/{record.run_id}"
    assert len(fakes.delivery.sent) == 1  # the outbox copy


@spec("FR-009")
def test_a_refused_run_sends_its_notice_without_buttons(fakes: Fakes) -> None:
    fakes.runner.results = [RunResult("refused", differences=("tools: x",), facts=FACTS)]
    assert run(fakes, "run", "check") == 1
    [(_, message)] = fakes.chat.sent
    assert message.buttons is None
    assert "refused" in message.markdown


@spec("FR-003")
def test_without_chat_nothing_is_sent(fakes: Fakes) -> None:
    fakes.write(JOBS)
    assert run(fakes, "run", "check") == 0
    assert fakes.chat.sent == []
    assert fakes.store.saved[0].chat is None


@spec("FR-002")
def test_a_missing_bot_token_fails_before_the_model(
    fakes: Fakes, capsys: pytest.CaptureFixture[str]
) -> None:
    fakes.keychain.values.clear()
    assert run(fakes, "run", "check") == 1
    assert "opscout secret set slack_bot_token" in capsys.readouterr().out
    assert fakes.runner.calls == []
    assert fakes.chat.sent == []


@spec("FR-011")
def test_the_chat_tokens_never_reach_the_model_run_or_any_output(
    fakes: Fakes, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(fakes, "run", "check") == 0
    [(_, _, environment)] = fakes.runner.calls
    assert TOKEN_SENTINEL not in environment.values()
    [token] = fakes.tokens  # only the chat adapter gets the token
    assert token() == TOKEN_SENTINEL
    captured = capsys.readouterr()
    assert TOKEN_SENTINEL not in captured.out + captured.err
    assert all(TOKEN_SENTINEL not in r.model_dump_json() for r in fakes.store.saved)


@spec("FR-007")
def test_slack_down_for_10_minutes_fails_the_run(
    fakes: Fakes, capsys: pytest.CaptureFixture[str]
) -> None:
    fakes.chat.unavailable = 1000
    assert run(fakes, "run", "check") == 1
    assert capsys.readouterr().out == (
        "check 2026-11-05: failed (delivery failed: Slack could not be reached for 10 minutes)\n"
    )
    assert fakes.store.delivered("check:2026-11-05") is None


# The gateway as an installed entry (US4)


def code_in(output: str) -> str:
    match = re.search(r"Confirmation code: ([0-9a-f]{12})", output)
    assert match is not None, output
    return match.group(1)


@spec("FR-013")
def test_install_adds_the_gateway_once_and_chat_off_removes_it(
    fakes: Fakes, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(fakes, "daemon", "install", "--dry-run") == 1
    out = capsys.readouterr().out
    assert "add opscout.check (09:30 every day)\n" in out
    assert "add opscout.gateway (always)\n" in out
    assert run(fakes, "daemon", "install", "--confirm", code_in(out)) == 0
    assert fakes.scheduler is not None
    gateway = fakes.scheduler.jobs["opscout.gateway"]
    assert gateway.keep_alive is True
    assert gateway.times == ()
    assert gateway.arguments[-3:] == ("gateway", "--config", str(fakes.config.absolute()))
    assert gateway.log == fakes.directories.log / "gateway.log"
    capsys.readouterr()
    assert run(fakes, "daemon", "install") == 0  # SC-005
    assert capsys.readouterr().out == "Scheduled jobs are up to date.\n"

    fakes.write(JOBS)
    run(fakes, "daemon", "install", "--dry-run")
    out = capsys.readouterr().out
    assert out.startswith("remove opscout.gateway\n")
    assert run(fakes, "daemon", "install", "--confirm", code_in(out)) == 0
    assert set(fakes.scheduler.jobs) == {"opscout.check"}


@spec("FR-013")
def test_without_a_scheduler_a_dm_still_works_and_install_says_so(
    fakes: Fakes, capsys: pytest.CaptureFixture[str]
) -> None:
    fakes.scheduler = None
    assert run(fakes, "run", "check") == 0
    assert len(fakes.chat.sent) == 1
    assert run(fakes, "daemon", "install") == 2
    assert "no scheduler is available" in capsys.readouterr().err


# opscout gateway (FR-012, FR-018, FR-019)


@dataclass
class ScriptedGateway:
    """Plays a script of states and events, then returns its exit code."""

    script: list[tuple[str, object]]
    code: int = 0
    tokens: tuple[str, str] | None = None

    def serve(self, handle: Callable[..., None], state: Callable[..., None]) -> int:
        for kind, value in self.script:
            if kind == "state":
                state(*value)  # type: ignore[misc]
            elif kind == "event":
                handle(value)
            elif kind == "advance":
                assert isinstance(value, int)
                FakeTime.sleep(TIME, value)
        return self.code

    def stop(self) -> None:
        pass


TIME = FakeTime()


def gateway_world(fakes: Fakes, monkeypatch: pytest.MonkeyPatch, gateway: ScriptedGateway) -> None:
    real = composition.wiring

    def make(app_token: str, bot_token: str) -> ScriptedGateway:
        gateway.tokens = (app_token, bot_token)
        return gateway

    monkeypatch.setattr(
        composition,
        "wiring",
        lambda: replace(real(), gateway=make, clock=TIME.clock, sleep=TIME.sleep),
    )


def state_file(fakes: Fakes) -> dict[str, object]:
    data: dict[str, object] = json.loads(
        (fakes.directories.data / "gateway.json").read_text(encoding="utf-8")
    )
    return data


@spec("FR-012")
def test_the_gateway_connects_handles_and_records_its_state(
    fakes: Fakes, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(fakes, "run", "check") == 0
    record = fakes.store.saved[0]
    assert record.chat is not None
    click = Choice(USER, "check", record.run_id, "agree", record.chat, "1111.2222.example")
    gateway = ScriptedGateway(
        [
            ("state", ("connecting", None)),
            ("state", ("connected", None)),
            ("event", click),
            ("event", Ignored("events_api")),
            ("advance", 61),
            ("state", ("connected", None)),
        ]
    )
    gateway_world(fakes, monkeypatch, gateway)
    capsys.readouterr()
    assert run(fakes, "gateway") == 0
    assert gateway.tokens == (TOKEN_SENTINEL, TOKEN_SENTINEL)
    stored = fakes.store.get("check", record.run_id)
    assert stored is not None
    assert stored.agreement is not None
    state = state_file(fakes)
    assert (state["state"], state["handled"], state["ignored"]) == ("stopped", 1, 1)
    log = capsys.readouterr().err
    assert log == (
        "opscout gateway: connecting to Slack\n"
        "opscout gateway: connected\n"
        "opscout gateway: stopped: asked to stop\n"
    )
    assert TOKEN_SENTINEL not in log


@spec("FR-018")
def test_a_second_gateway_says_so_and_exits(
    fakes: Fakes, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    gateway_world(fakes, monkeypatch, ScriptedGateway([]))
    with GatewayFiles(fakes.directories.data).hold() as held:
        assert held is True
        assert run(fakes, "gateway") == 0
    assert capsys.readouterr().err == "opscout gateway: another gateway is running\n"


@spec("FR-012")
def test_without_chat_the_gateway_stops_for_good(
    fakes: Fakes, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    gateway_world(fakes, monkeypatch, ScriptedGateway([]))
    fakes.write(JOBS)
    assert run(fakes, "gateway") == 0
    assert capsys.readouterr().err == "opscout gateway: stopped: daemon.chat is not configured\n"
    assert state_file(fakes)["state"] == "stopped"


@spec("FR-019")
@pytest.mark.parametrize(
    ("config", "keychain", "line"),
    [
        ("daemon: {jobs: {check: {at: '25:00'}}}\n", True, "the configuration is invalid"),
        (JOBS + CHAT, False, "the secret slack_bot_token is missing"),
    ],
)
def test_what_can_be_fixed_waits_5_minutes_then_exits_to_be_restarted(
    fakes: Fakes,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    config: str,
    keychain: bool,
    line: str,
) -> None:
    gateway = ScriptedGateway([("state", ("connected", None))])
    gateway_world(fakes, monkeypatch, gateway)
    fakes.write(config)
    if not keychain:
        fakes.keychain.values.clear()
    slept = len(TIME.slept)
    assert run(fakes, "gateway") == 1
    assert TIME.slept[slept:] == [300]
    assert gateway.tokens is None
    log = capsys.readouterr().err
    assert log.startswith(f"opscout gateway: stopped: {line}")
    assert log.endswith("; retrying in 5 minutes\n")
    assert state_file(fakes)["state"] == "stopped"


@spec("FR-019")
def test_a_rejected_token_stops_the_gateway_and_says_why(
    fakes: Fakes, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    gateway = ScriptedGateway(
        [("state", ("connecting", None)), ("state", ("stopped", "token rejected (invalid_auth)"))]
    )
    gateway_world(fakes, monkeypatch, gateway)
    assert run(fakes, "gateway") == 0
    assert capsys.readouterr().err == (
        "opscout gateway: connecting to Slack\n"
        "opscout gateway: stopped: token rejected (invalid_auth)\n"
    )
    state = state_file(fakes)
    assert (state["state"], state["reason"]) == ("stopped", "token rejected (invalid_auth)")


# Status (FR-020)


def install(fakes: Fakes, capsys: pytest.CaptureFixture[str]) -> None:
    run(fakes, "daemon", "install", "--dry-run")
    assert run(fakes, "daemon", "install", "--confirm", code_in(capsys.readouterr().out)) == 0
    capsys.readouterr()


def gateway_line(fakes: Fakes, capsys: pytest.CaptureFixture[str]) -> str:
    assert run(fakes, "daemon", "status") == 0
    [line] = [x for x in capsys.readouterr().out.splitlines() if x.startswith("gateway")]
    return line


@spec("FR-020")
def test_status_shows_the_gateway_and_its_connection(
    fakes: Fakes, capsys: pytest.CaptureFixture[str]
) -> None:
    log = fakes.directories.log / "gateway.log"
    assert gateway_line(fakes, capsys) == (
        "gateway  always  not installed (run opscout daemon install)"
    )
    install(fakes, capsys)
    assert (
        gateway_line(fakes, capsys)
        == f"gateway  always  installed, loaded  never connected (see {log})"
    )
    files = GatewayFiles(fakes.directories.data)
    since = TIME.now
    files.write(GatewayStatus(state="connected", since=since, last_seen=since))
    assert gateway_line(fakes, capsys) == (
        f"gateway  always  installed, loaded  connected since {since:%Y-%m-%d %H:%M}"
    )
    files.write(
        GatewayStatus(state="connecting", since=since, last_seen=TIME.now, reason="disconnected")
    )
    assert gateway_line(fakes, capsys) == (
        f"gateway  always  installed, loaded  not connected since {since:%Y-%m-%d %H:%M} "
        f"(see {log})"
    )
    stale = START - timedelta(minutes=20)  # the composition root's clock starts at START
    files.write(GatewayStatus(state="connected", since=stale, last_seen=stale))
    assert gateway_line(fakes, capsys) == (
        f"gateway  always  installed, loaded  not running; last seen {stale:%Y-%m-%d %H:%M} "
        f"(see {log})"
    )
    files.write(
        GatewayStatus(
            state="stopped", since=since, last_seen=since, reason="token rejected (invalid_auth)"
        )
    )
    assert gateway_line(fakes, capsys) == (
        "gateway  always  installed, loaded  stopped: token rejected (invalid_auth); "
        f"last seen {since:%Y-%m-%d %H:%M} (run opscout daemon install to start it again; "
        f"see {log})"
    )


@spec("FR-013")
def test_install_starts_again_a_gateway_that_stopped_for_good(
    fakes: Fakes, capsys: pytest.CaptureFixture[str]
) -> None:
    install(fakes, capsys)
    files = GatewayFiles(fakes.directories.data)
    files.write(
        GatewayStatus(
            state="stopped", since=TIME.now, last_seen=TIME.now, reason="token rejected (x)"
        )
    )
    assert run(fakes, "daemon", "install", "--dry-run") == 1
    out = capsys.readouterr().out
    assert out.startswith("restart opscout.gateway (stopped: token rejected (x))\n")
    assert run(fakes, "daemon", "install", "--confirm", code_in(out)) == 0
    assert fakes.scheduler is not None
    assert fakes.scheduler.restarted == ["opscout.gateway"]
    files.write(GatewayStatus(state="connected", since=TIME.now, last_seen=TIME.now))
    capsys.readouterr()
    assert run(fakes, "daemon", "install") == 0
    assert capsys.readouterr().out == "Scheduled jobs are up to date.\n"


@spec("FR-012")
def test_a_new_chat_user_reloads_the_gateway(
    fakes: Fakes, capsys: pytest.CaptureFixture[str]
) -> None:
    install(fakes, capsys)
    fakes.write(JOBS + CHAT.replace("UEXAMPLE01", "UEXAMPLE02"))
    run(fakes, "daemon", "install", "--dry-run")
    assert "update opscout.gateway (always)" in capsys.readouterr().out


@spec("FR-020")
def test_status_without_chat_names_a_leftover_gateway(
    fakes: Fakes, capsys: pytest.CaptureFixture[str]
) -> None:
    install(fakes, capsys)
    fakes.write(JOBS)
    assert gateway_line(fakes, capsys) == (
        "gateway  always  installed but chat is not configured (run opscout daemon install)"
    )
    run(fakes, "daemon", "install", "--dry-run")
    run(fakes, "daemon", "install", "--confirm", code_in(capsys.readouterr().out))
    capsys.readouterr()
    assert run(fakes, "daemon", "status") == 0
    assert "gateway" not in capsys.readouterr().out


# Failures are visible (US5)


@spec("FR-024")
def test_a_failed_run_sends_a_short_notice_by_direct_message(fakes: Fakes) -> None:
    fakes.runner.results = [RunResult("error", reason="error_max_budget_usd: over budget")]
    assert run(fakes, "run", "check") == 1
    [(user, message)] = fakes.chat.sent
    assert user == USER
    assert message.buttons is None
    assert "failed" in message.markdown
    assert "error_max_budget_usd: over budget" in message.markdown
    assert "opscout daemon runs check" in message.markdown
    [record] = fakes.store.saved
    assert record.outcome == "failed"
    assert record.chat is not None


@spec("FR-019")
def test_a_gateway_asked_to_stop_writes_that_it_stopped(
    fakes: Fakes, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    gateway_world(fakes, monkeypatch, ScriptedGateway([("state", ("connected", None))]))
    assert run(fakes, "gateway") == 0
    state = state_file(fakes)
    assert (state["state"], state["reason"]) == ("stopped", "asked to stop")
    assert capsys.readouterr().err.endswith("opscout gateway: stopped: asked to stop\n")
