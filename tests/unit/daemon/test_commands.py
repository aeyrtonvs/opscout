# SPDX-License-Identifier: Apache-2.0
"""The daemon commands, with fake adapters in the composition root (spec 007)."""

import io
import re
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from opscout.core.daemon import CheckOutput, RunnerFacts, RunResult, ScheduledJob
from opscout.entrypoints import daemon as composition
from opscout.entrypoints.cli import main
from tests.unit.daemon.fakes import (
    SENTINEL,
    START,
    Clock,
    MemoryDelivery,
    MemoryRunStore,
    MemoryScheduler,
    MemorySecretStore,
    ScriptedRunner,
)


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 007."""
    return pytest.mark.spec("007", requirement)


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
CONFIG = """\
schema_version: 1
daemon:
  jobs:
    check:
      at: "09:30"
      weekdays: [mon, tue, wed, thu, fri]
"""


@dataclass
class Fakes:
    """The fakes wired into the composition root, and the configuration directory."""

    config: Path
    directories: composition.Directories
    runner: ScriptedRunner = field(default_factory=lambda: ScriptedRunner([OK]))
    store: MemoryRunStore = field(default_factory=MemoryRunStore)
    delivery: MemoryDelivery = field(default_factory=MemoryDelivery)
    keychain: MemorySecretStore = field(default_factory=MemorySecretStore)
    scheduler: MemoryScheduler | None = field(default_factory=MemoryScheduler)
    clock: Clock = field(default_factory=Clock)
    terminal: bool = False
    answers: list[str] = field(default_factory=list)
    runner_daemons: list[object] = field(default_factory=list)

    def write(self, text: str) -> None:
        (self.config / "config.yaml").write_text(text, encoding="utf-8")


@pytest.fixture
def fakes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Fakes:
    config = tmp_path / "config"
    config.mkdir()
    directories = composition.Directories(
        data=tmp_path / "data", log=tmp_path / "log", cache=tmp_path / "cache"
    )
    world = Fakes(config=config, directories=directories)
    world.write(CONFIG)

    def runner(daemon: object, run_dir: Path) -> ScriptedRunner:
        world.runner_daemons.append(daemon)
        return world.runner

    def wiring() -> composition.Wiring:
        return composition.Wiring(
            directories=directories,
            environ={"PATH": "/usr/bin:/bin"},
            clock=world.clock,
            runner=runner,
            store=world.store,
            delivery=world.delivery,
            secrets=world.keychain,
            scheduler=world.scheduler,
            engine_command=lambda: ["/opt/example/bin/uv", "run", "--project", "/opt/x", "opscout"],
            path_exists=lambda path: not path.startswith("/missing"),
            is_terminal=lambda: world.terminal,
            ask=lambda prompt: world.answers.pop(0) if world.answers else "",
            read_secret=lambda prompt: "typed-secret",
            which=lambda name, search: None,
        )

    monkeypatch.setattr(composition, "wiring", wiring)
    return world


def run(fakes: Fakes, *arguments: str) -> int:
    return main([*arguments, "--config", str(fakes.config)])


# opscout run (US1)


@spec("FR-006")
def test_run_prints_the_outcome_and_exits_by_it(
    fakes: Fakes, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(fakes, "run", "check") == 0
    record = fakes.store.saved[0]
    assert capsys.readouterr().out == f"check 2026-11-05: delivered to {record.delivery}\n"
    assert record.trigger == "user"

    assert run(fakes, "run", "check", "--trigger", "scheduler") == 0
    assert capsys.readouterr().out == (
        f"check 2026-11-05: skipped (already delivered by run {record.run_id})\n"
    )
    assert fakes.store.saved[1].trigger == "scheduler"

    fakes.runner.results = [RunResult("error", reason="exit 1")]
    assert run(fakes, "run", "check", "--force") == 1
    assert capsys.readouterr().out == "check 2026-11-05: failed (exit 1)\n"


@spec("FR-006")
def test_run_cannot_start_on_an_invalid_configuration(
    fakes: Fakes, capsys: pytest.CaptureFixture[str]
) -> None:
    fakes.write("schema_version: 1\ndaemon:\n  jobs:\n    check:\n      at: '25:00'\n")
    assert run(fakes, "run", "check") == 2
    assert "run opscout config validate" in capsys.readouterr().err
    assert fakes.store.saved == []
    assert fakes.runner.calls == []


@spec("FR-006")
def test_run_refuses_an_unknown_job(fakes: Fakes, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(fakes, "run", "standup") == 2
    assert capsys.readouterr().err == (
        'opscout run: unknown job "standup"; configured jobs: check\n'
    )
    fakes.write("schema_version: 1\n")
    assert run(fakes, "run", "standup") == 2
    assert capsys.readouterr().err == (
        'opscout run: unknown job "standup"; configured jobs: none (the engine\'s jobs: check)\n'
    )


@spec("FR-004")
def test_run_does_not_start_without_a_writable_store(
    fakes: Fakes, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from opscout.core.daemon import StoreError

    def broken(job: str, period: str) -> object:
        raise StoreError("/example/runs/check: cannot be written (PermissionError)")

    monkeypatch.setattr(fakes.store, "hold", broken)
    assert run(fakes, "run", "check") == 2
    assert capsys.readouterr().err == (
        "opscout run: the run store cannot be used: "
        "/example/runs/check: cannot be written (PermissionError)\n"
    )
    assert fakes.runner.calls == []


@spec("FR-017")
def test_run_gives_the_runner_the_configured_claude_path(fakes: Fakes) -> None:
    fakes.write(CONFIG + "  claude_path: /opt/example/bin/claude\n")
    assert run(fakes, "run", "check") == 0
    assert getattr(fakes.runner_daemons[0], "claude_path", None) == "/opt/example/bin/claude"


def test_run_uses_the_clock_of_the_composition_root(fakes: Fakes) -> None:
    fakes.clock.times = [START.replace(day=6)]
    assert run(fakes, "run", "check") == 0
    assert fakes.store.saved[0].period == "2026-11-06"


# opscout daemon install, uninstall and status (US2)


def code_in(output: str) -> str:
    match = re.search(r"Confirmation code: ([0-9a-f]{12})", output)
    assert match is not None, output
    return match.group(1)


@spec("FR-009")
@spec("FR-029")
def test_a_dry_run_lists_the_changes_and_a_code_and_writes_nothing(
    fakes: Fakes, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(fakes, "daemon", "install", "--dry-run") == 1
    out = capsys.readouterr().out
    assert out.startswith("add opscout.check (09:30 mon\N{EN DASH}fri)\n")
    code = code_in(out)
    assert f"opscout daemon install --config {fakes.config} --confirm {code}" in out
    assert fakes.scheduler is not None
    assert fakes.scheduler.applied == []


@spec("FR-029")
def test_without_a_terminal_or_a_code_nothing_changes(
    fakes: Fakes, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(fakes, "daemon", "install") == 1
    assert "Confirmation code:" in capsys.readouterr().out
    assert fakes.scheduler is not None
    assert fakes.scheduler.applied == []


@spec("FR-029")
@pytest.mark.parametrize(
    ("answer", "applied"), [("y", True), ("yes", True), ("n", False), ("", False)]
)
def test_a_terminal_answer_decides(
    fakes: Fakes, capsys: pytest.CaptureFixture[str], answer: str, applied: bool
) -> None:
    fakes.terminal = True
    fakes.answers = [answer]
    assert run(fakes, "daemon", "install") == (0 if applied else 1)
    out = capsys.readouterr().out
    assert fakes.scheduler is not None
    assert bool(fakes.scheduler.applied) is applied
    assert ("Installed 1, updated 0, removed 0." in out) is applied
    assert ("Nothing was changed." in out) is not applied


@spec("FR-029")
def test_the_change_is_computed_again_after_the_yes(
    fakes: Fakes, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    fakes.terminal = True
    scheduler = fakes.scheduler
    assert scheduler is not None

    def meanwhile(prompt: str) -> str:
        scheduler.jobs["opscout.other"] = _other()
        return "y"

    def wired() -> composition.Wiring:
        from dataclasses import replace

        return replace(original(), ask=meanwhile)

    original = composition.wiring
    monkeypatch.setattr(composition, "wiring", wired)
    assert run(fakes, "daemon", "install") == 1
    assert "changed while you were asked" in capsys.readouterr().out
    assert scheduler.applied == []


def _other() -> ScheduledJob:
    from types import MappingProxyType

    return ScheduledJob(
        name="other",
        arguments=("/opt/example/bin/true",),
        times=((1, 8, 0),),
        log=Path("/example/other.log"),
        environment=MappingProxyType({}),
    )


@spec("FR-009")
@spec("FR-029")
def test_the_code_applies_until_something_changes(
    fakes: Fakes, capsys: pytest.CaptureFixture[str]
) -> None:
    run(fakes, "daemon", "install", "--dry-run")
    code = code_in(capsys.readouterr().out)
    fakes.write(CONFIG.replace("09:30", "10:00"))
    assert run(fakes, "daemon", "install", "--confirm", code) == 1
    assert "changed since that code" in capsys.readouterr().out
    assert fakes.scheduler is not None
    assert fakes.scheduler.applied == []

    run(fakes, "daemon", "install", "--dry-run")
    code = code_in(capsys.readouterr().out)
    assert run(fakes, "daemon", "install", "--confirm", code.upper()) == 0
    assert capsys.readouterr().out.endswith("Installed 1, updated 0, removed 0.\n")
    assert set(fakes.scheduler.jobs) == {"opscout.check"}
    [job] = fakes.scheduler.jobs.values()
    assert job.arguments == (
        "/opt/example/bin/uv", "run", "--project", "/opt/x", "opscout",
        "run", "check", "--config", str(fakes.config.absolute()), "--trigger", "scheduler",
    )  # fmt: skip
    assert job.log == fakes.directories.log / "check.log"
    assert fakes.directories.log.is_dir()
    assert dict(job.environment) == {"PATH": "/opt/example/bin:/usr/bin:/bin:/usr/sbin:/sbin"}

    assert run(fakes, "daemon", "install", "--dry-run") == 0
    assert capsys.readouterr().out == "Scheduled jobs are up to date.\n"


@spec("FR-009")
@spec("FR-011")
def test_no_jobs_configured_removes_opscout_s_jobs_and_uninstall_removes_all(
    fakes: Fakes, capsys: pytest.CaptureFixture[str]
) -> None:
    scheduler = fakes.scheduler
    assert scheduler is not None
    scheduler.jobs = {"opscout.check": _other(), "opscout.other": _other()}
    scheduler.loaded = set(scheduler.jobs)
    fakes.write("schema_version: 1\n")
    run(fakes, "daemon", "install", "--dry-run")
    out = capsys.readouterr().out
    assert out.startswith("remove opscout.check\nremove opscout.other\n")
    assert run(fakes, "daemon", "install", "--confirm", code_in(out)) == 0
    assert scheduler.jobs == {}
    assert capsys.readouterr().out.endswith("Installed 0, updated 0, removed 2.\n")

    scheduler.jobs = {"opscout.check": _other()}
    fakes.write(CONFIG)
    run(fakes, "daemon", "uninstall", "--dry-run")
    out = capsys.readouterr().out
    assert out.startswith("remove opscout.check\n")
    assert f"opscout daemon uninstall --config {fakes.config} --confirm" in out
    assert run(fakes, "daemon", "uninstall", "--confirm", code_in(out)) == 0
    assert run(fakes, "daemon", "uninstall") == 0
    assert capsys.readouterr().out.endswith("Nothing to uninstall.\n")


@spec("FR-012")
def test_status_names_each_mismatch_and_the_last_outcome(
    fakes: Fakes, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(fakes, "daemon", "status") == 0
    assert capsys.readouterr().out == (
        "check  09:30 mon\N{EN DASH}fri  not installed (run opscout daemon install)  last: none\n"
    )
    run(fakes, "daemon", "install", "--dry-run")
    run(fakes, "daemon", "install", "--confirm", code_in(capsys.readouterr().out))
    run(fakes, "run", "check")
    capsys.readouterr()
    assert run(fakes, "daemon", "status") == 0
    assert capsys.readouterr().out == (
        "check  09:30 mon\N{EN DASH}fri  installed, loaded  last: delivered 2026-11-05 09:30\n"
    )

    scheduler = fakes.scheduler
    assert scheduler is not None
    scheduler.loaded.clear()
    scheduler.jobs["opscout.other"] = _other()
    fakes.write(CONFIG.replace("09:30", "10:00"))
    run(fakes, "daemon", "status")
    assert capsys.readouterr().out == (
        "check  10:00 mon\N{EN DASH}fri  schedule differs from the configuration "
        "(run opscout daemon install)  last: delivered 2026-11-05 09:30\n"
        "other  -  installed but not configured (run opscout daemon install)  last: none\n"
    )


@spec("FR-012")
def test_status_says_when_the_installed_engine_is_gone(
    fakes: Fakes, capsys: pytest.CaptureFixture[str]
) -> None:
    from types import MappingProxyType

    scheduler = fakes.scheduler
    assert scheduler is not None
    scheduler.jobs["opscout.check"] = ScheduledJob(
        name="check",
        arguments=("/missing/uvx", "--quiet", "--from", "opscout==0.9.0", "opscout"),
        times=((1, 9, 30),),
        log=Path("/example/check.log"),
        environment=MappingProxyType({}),
    )
    scheduler.loaded.add("opscout.check")
    run(fakes, "daemon", "status")
    out = capsys.readouterr().out
    assert "stale: /missing/uvx is missing" in out
    assert "stale: installed with engine 0.9.0" in out
    assert "(run opscout daemon install)" in out


@spec("FR-013")
@pytest.mark.parametrize("command", ["install", "uninstall", "status"])
def test_without_a_scheduler_the_commands_say_so(
    fakes: Fakes, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    fakes.scheduler = None
    assert run(fakes, "daemon", command) == 2
    assert capsys.readouterr().err == (
        f"opscout daemon {command}: no scheduler is available for this system "
        "(only launchd, on macOS)\n"
    )


@spec("FR-012")
def test_an_invalid_configuration_stops_install_and_status(
    fakes: Fakes, capsys: pytest.CaptureFixture[str]
) -> None:
    fakes.write("schema_version: 1\ndaemon: {jobs: {check: {at: '25:00'}}}\n")
    for command in ("install", "status"):
        assert run(fakes, "daemon", command) == 2
        assert "run opscout config validate" in capsys.readouterr().err
    assert fakes.scheduler is not None
    assert fakes.scheduler.applied == []


# opscout secret set and check (US4)

SECRETS = CONFIG + "  secrets:\n    claude_token:\n      service: opscout-example\n"


@spec("FR-024")
def test_secret_set_reads_without_echo_in_a_terminal(
    fakes: Fakes, capsys: pytest.CaptureFixture[str]
) -> None:
    fakes.write(SECRETS)
    fakes.terminal = True
    assert run(fakes, "secret", "set", "claude_token") == 0
    assert capsys.readouterr().out == (
        "Stored claude_token in the keychain (service opscout-example, account opscout).\n"
    )
    assert fakes.keychain.values == {("opscout-example", "opscout"): "typed-secret"}


@spec("FR-024")
def test_secret_set_reads_one_line_of_standard_input_otherwise(
    fakes: Fakes, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    fakes.write(SECRETS)
    monkeypatch.setattr("sys.stdin", io.StringIO(f"{SENTINEL}\nsecond line\n"))
    assert run(fakes, "secret", "set", "claude_token") == 0
    assert fakes.keychain.values == {("opscout-example", "opscout"): SENTINEL}
    captured = capsys.readouterr()
    assert SENTINEL not in captured.out + captured.err


@spec("FR-024")
@pytest.mark.parametrize(
    ("config", "arguments", "error"),
    [
        (SECRETS, ("set", "slack_token"), 'unknown secret "slack_token"; known: claude_token'),
        (CONFIG, ("set", "claude_token"), "add daemon.secrets.claude_token"),
        (SECRETS, ("check", "slack_token"), 'unknown secret "slack_token"'),
        (CONFIG, ("check", "claude_token"), "claude_token is not in daemon.secrets"),
    ],
)
def test_secret_commands_refuse_unknown_or_unconfigured_names(
    fakes: Fakes,
    capsys: pytest.CaptureFixture[str],
    config: str,
    arguments: tuple[str, ...],
    error: str,
) -> None:
    fakes.write(config)
    assert run(fakes, "secret", *arguments) == 2
    assert error in capsys.readouterr().err
    assert fakes.keychain.values == {}


@spec("FR-024")
def test_secret_set_refuses_an_empty_value(
    fakes: Fakes, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    fakes.write(SECRETS)
    monkeypatch.setattr("sys.stdin", io.StringIO("\n"))
    assert run(fakes, "secret", "set", "claude_token") == 2
    assert "nothing was stored" in capsys.readouterr().err


@spec("FR-024")
def test_secret_check_reports_existence_and_location_only(
    fakes: Fakes, capsys: pytest.CaptureFixture[str]
) -> None:
    fakes.write(CONFIG)
    assert run(fakes, "secret", "check") == 0
    assert capsys.readouterr().out == "No secrets are configured.\n"
    fakes.write(SECRETS)
    assert run(fakes, "secret", "check") == 1
    assert capsys.readouterr().out == (
        "claude_token: missing (keychain service opscout-example, account opscout)\n"
    )
    fakes.keychain.values[("opscout-example", "opscout")] = SENTINEL
    assert run(fakes, "secret", "check", "claude_token") == 0
    out = capsys.readouterr().out
    assert out == "claude_token: present (keychain service opscout-example, account opscout)\n"
    fakes.keychain.unavailable = True
    assert run(fakes, "secret", "check") == 1
    assert capsys.readouterr().out == (
        "claude_token: unavailable (the keychain is locked; keychain service opscout-example, "
        "account opscout)\n"
    )


@spec("FR-019")
@spec("FR-024")
def test_the_fallback_token_reaches_only_the_child_and_never_any_output(
    fakes: Fakes, capsys: pytest.CaptureFixture[str]
) -> None:
    fakes.write(SECRETS)
    assert run(fakes, "run", "check") == 1
    out = capsys.readouterr().out
    assert "opscout secret set claude_token" in out
    assert fakes.runner.calls == []

    fakes.keychain.values[("opscout-example", "opscout")] = SENTINEL
    assert run(fakes, "run", "check", "--force") == 0
    assert fakes.runner.calls[0][2] == {"CLAUDE_CODE_OAUTH_TOKEN": SENTINEL}
    captured = capsys.readouterr()
    assert SENTINEL not in captured.out + captured.err
    assert all(SENTINEL not in record.model_dump_json() for record in fakes.store.saved)
    assert all(SENTINEL not in text for *_, text in fakes.delivery.sent)
    assert run(fakes, "daemon", "runs") == 0
    assert SENTINEL not in capsys.readouterr().out


@spec("FR-012")
def test_status_of_disabled_jobs_and_other_schedules(
    fakes: Fakes, capsys: pytest.CaptureFixture[str]
) -> None:
    fakes.write(
        "schema_version: 1\ndaemon:\n  jobs:\n    check:\n      at: '07:00'\n      enabled: false\n"
    )
    run(fakes, "daemon", "status")
    assert capsys.readouterr().out == "check  07:00 every day  disabled  last: none\n"
    scheduler = fakes.scheduler
    assert scheduler is not None
    scheduler.jobs["opscout.check"] = _other()
    scheduler.loaded.add("opscout.check")
    run(fakes, "daemon", "status")
    assert capsys.readouterr().out == (
        "check  07:00 every day  disabled but installed (run opscout daemon install)  last: none\n"
    )
    fakes.write("schema_version: 1\ndaemon:\n  jobs:\n    check:\n      at: '07:00'\n"
                "      weekdays: [sat, mon]\n")  # fmt: skip
    scheduler.jobs.clear()
    run(fakes, "daemon", "status")
    assert capsys.readouterr().out.startswith("check  07:00 mon, sat  not installed")
    fakes.write("schema_version: 1\n")
    run(fakes, "daemon", "status")
    assert capsys.readouterr().out == "No jobs are configured or installed.\n"


@spec("FR-012")
def test_status_says_when_the_clone_is_gone(
    fakes: Fakes, capsys: pytest.CaptureFixture[str]
) -> None:
    from types import MappingProxyType

    scheduler = fakes.scheduler
    assert scheduler is not None
    scheduler.jobs["opscout.check"] = ScheduledJob(
        name="check",
        arguments=("/opt/example/bin/uv", "run", "--project", "/missing/clone", "opscout"),
        times=((1, 9, 30),),
        log=Path("/example/check.log"),
        environment=MappingProxyType({}),
    )
    run(fakes, "daemon", "status")
    assert "stale: /missing/clone is missing" in capsys.readouterr().out


@spec("FR-009")
def test_a_dry_run_never_applies_even_with_a_valid_code(
    fakes: Fakes, capsys: pytest.CaptureFixture[str]
) -> None:
    run(fakes, "daemon", "install", "--dry-run")
    code = code_in(capsys.readouterr().out)
    assert run(fakes, "daemon", "install", "--dry-run", "--confirm", code) == 1
    assert fakes.scheduler is not None
    assert fakes.scheduler.applied == []


@spec("FR-010")
def test_the_job_s_path_does_not_depend_on_the_installing_shell(
    fakes: Fakes, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def wired(path: str) -> composition.Wiring:
        from dataclasses import replace

        found = {"claude": "/opt/claude/bin/claude", "node": "/opt/node/bin/node"}
        return replace(
            original(), environ={"PATH": path}, which=lambda name, search: found.get(name)
        )

    original = composition.wiring
    monkeypatch.setattr(composition, "wiring", lambda: wired("/usr/bin:/bin"))
    run(fakes, "daemon", "install", "--dry-run")
    first = code_in(capsys.readouterr().out)
    monkeypatch.setattr(composition, "wiring", lambda: wired("/opt/venv/bin:/usr/bin:/bin"))
    run(fakes, "daemon", "install", "--dry-run")
    assert code_in(capsys.readouterr().out) == first
    assert run(fakes, "daemon", "install", "--confirm", first) == 0
    assert fakes.scheduler is not None
    [job] = fakes.scheduler.jobs.values()
    assert job.environment["PATH"] == (
        "/opt/claude/bin:/opt/node/bin:/opt/example/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    )
