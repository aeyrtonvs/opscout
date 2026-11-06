# SPDX-License-Identifier: Apache-2.0
"""The launchd adapter, through its seam, and once against launchd itself (spec 007, US2)."""

import os
import plistlib
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

from opscout.adapters.launchd import Launchctl, LaunchdScheduler, plist_bytes
from opscout.core.config import Daemon, JobSettings
from opscout.core.daemon import ScheduledJob, SchedulerError
from opscout.entrypoints.daemon import engine_command
from opscout.services.daemon import wanted_jobs

COMMAND = ("/opt/example/bin/uv", "run", "--quiet", "--frozen", "--project", "/opt/x", "opscout")


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 007."""
    return pytest.mark.spec("007", requirement)


def job(name: str = "check", *, minute: int = 30) -> ScheduledJob:
    return ScheduledJob(
        name=name,
        arguments=(*COMMAND, "run", name, "--config", "/opt/config", "--trigger", "scheduler"),
        times=((1, 9, minute), (7, 9, minute)),
        log=Path(f"/opt/log/{name}.log"),
        environment=MappingProxyType({"PATH": "/opt/example/bin:/usr/bin:/bin"}),
    )


@dataclass
class RecordingManager:
    """The service manager seam: records each call and keeps the loaded labels."""

    loaded: set[str] = field(default_factory=set)
    calls: list[tuple[str, str]] = field(default_factory=list)

    def load(self, plist: Path) -> None:
        self.calls.append(("load", plist.name))
        self.loaded.add(plist.stem)

    def unload(self, label: str) -> None:
        self.calls.append(("unload", label))
        self.loaded.discard(label)

    def is_loaded(self, label: str) -> bool:
        return label in self.loaded

    def restart(self, label: str) -> None:
        self.calls.append(("restart", label))


# The property lists (FR-010)


@spec("FR-010")
def test_the_property_list_runs_the_job_with_the_engine_that_installed_it() -> None:
    data: dict[str, Any] = plistlib.loads(plist_bytes(job()))
    assert data == {
        "Label": "opscout.check",
        "ProgramArguments": list(job().arguments),
        "StartCalendarInterval": [
            {"Hour": 9, "Minute": 30, "Weekday": 0},
            {"Hour": 9, "Minute": 30, "Weekday": 1},
        ],
        "StandardOutPath": "/opt/log/check.log",
        "StandardErrorPath": "/opt/log/check.log",
        "EnvironmentVariables": {"PATH": "/opt/example/bin:/usr/bin:/bin"},
        "ProcessType": "Background",
    }
    assert plist_bytes(job()) == plist_bytes(job())


@spec("FR-010")
def test_the_wanted_jobs_are_the_enabled_ones() -> None:
    daemon = Daemon(
        jobs={"check": JobSettings(at="07:05", weekdays=["mon", "sun"])},
    )
    [wanted] = wanted_jobs(
        daemon, COMMAND, config=Path("/opt/config"), logs=Path("/opt/log"), path="/usr/bin"
    )
    assert wanted.label == "opscout.check"
    assert wanted.arguments == (
        *COMMAND, "run", "check", "--config", "/opt/config", "--trigger", "scheduler",
    )  # fmt: skip
    assert wanted.times == ((1, 7, 5), (7, 7, 5))
    assert wanted.log == Path("/opt/log/check.log")
    assert dict(wanted.environment) == {"PATH": "/usr/bin"}
    disabled = Daemon(jobs={"check": JobSettings(at="07:05", enabled=False)})
    assert wanted_jobs(disabled, COMMAND, config=Path("/c"), logs=Path("/l"), path="") == []


@spec("FR-010")
def test_the_engine_command_is_the_clone_or_the_release(tmp_path: Path) -> None:
    clone = tmp_path / "clone"
    (clone / "src" / "opscout").mkdir(parents=True)
    (clone / "pyproject.toml").write_text('[project]\nname = "opscout"\n', encoding="utf-8")
    package = clone / "src" / "opscout" / "__init__.py"
    tools = {"uv": "/opt/example/bin/uv", "uvx": "/opt/example/bin/uvx"}
    assert engine_command(package, "0.0.0", tools.get) == [
        "/opt/example/bin/uv", "run", "--quiet", "--frozen", "--project", str(clone), "opscout",
    ]  # fmt: skip
    installed = tmp_path / "site-packages" / "opscout" / "__init__.py"
    assert engine_command(installed, "1.2.3", tools.get) == [
        "/opt/example/bin/uvx", "--quiet", "--from", "opscout==1.2.3", "opscout",
    ]  # fmt: skip
    with pytest.raises(LookupError, match="uvx"):
        engine_command(installed, "1.2.3", lambda name: None)


# LaunchdScheduler through the seam (FR-009, FR-011, FR-013)


@pytest.fixture
def agents(tmp_path: Path) -> Path:
    directory = tmp_path / "LaunchAgents"
    directory.mkdir()
    (directory / "com.example.other.plist").write_bytes(b"not opscout's")
    return directory


@spec("FR-009")
@spec("FR-013")
def test_install_adds_then_changes_nothing(agents: Path) -> None:
    manager = RecordingManager()
    scheduler = LaunchdScheduler(agents, manager)
    pending = scheduler.plan([job()])
    assert [(c.action, c.label) for c in pending.changes] == [("add", "opscout.check")]
    scheduler.apply(pending)
    assert (agents / "opscout.check.plist").read_bytes() == plist_bytes(job())
    assert manager.calls == [("unload", "opscout.check"), ("load", "opscout.check.plist")]

    assert scheduler.plan([job()]).changes == ()
    [installed] = scheduler.installed()
    assert (installed.label, installed.loaded) == ("opscout.check", True)
    assert installed.arguments == job().arguments
    assert set(scheduler.installed_times()) == {"check"}
    assert (agents / "com.example.other.plist").read_bytes() == b"not opscout's"


@spec("FR-009")
def test_a_changed_schedule_is_updated_by_unload_write_load(agents: Path) -> None:
    manager = RecordingManager()
    scheduler = LaunchdScheduler(agents, manager)
    scheduler.apply(scheduler.plan([job()]))
    manager.calls.clear()
    pending = scheduler.plan([job(minute=45)])
    [change] = pending.changes
    assert (change.action, change.current, change.new) == (
        "update", plist_bytes(job()), plist_bytes(job(minute=45)),
    )  # fmt: skip
    scheduler.apply(pending)
    assert manager.calls == [("unload", "opscout.check"), ("load", "opscout.check.plist")]
    assert (agents / "opscout.check.plist").read_bytes() == plist_bytes(job(minute=45))


@spec("FR-009")
def test_an_unloaded_job_is_loaded_and_a_hand_written_one_replaced(agents: Path) -> None:
    manager = RecordingManager()
    scheduler = LaunchdScheduler(agents, manager)
    (agents / "opscout.check.plist").write_bytes(plist_bytes(job()))
    pending = scheduler.plan([job()])
    assert [(c.action, c.label) for c in pending.changes] == [("load", "opscout.check")]
    scheduler.apply(pending)
    assert manager.calls == [("load", "opscout.check.plist")]

    (agents / "opscout.check.plist").write_bytes(b"written by hand")
    assert [c.action for c in scheduler.plan([job()]).changes] == ["update"]
    [installed] = scheduler.installed()
    assert installed.arguments == ()


@spec("FR-011")
def test_uninstall_removes_every_opscout_job_and_nothing_else(agents: Path) -> None:
    manager = RecordingManager()
    scheduler = LaunchdScheduler(agents, manager)
    scheduler.apply(scheduler.plan([job(), job("other")]))
    manager.calls.clear()
    pending = scheduler.plan([])
    assert [(c.action, c.label) for c in pending.changes] == [
        ("remove", "opscout.check"),
        ("remove", "opscout.other"),
    ]
    scheduler.apply(pending)
    assert manager.calls == [("unload", "opscout.check"), ("unload", "opscout.other")]
    assert [p.name for p in agents.iterdir()] == ["com.example.other.plist"]
    assert scheduler.plan([]).changes == ()


@spec("FR-013")
def test_launchctl_is_called_through_the_seam(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def run(command: list[str]) -> "subprocess.CompletedProcess[str]":
        calls.append(command)
        return subprocess.CompletedProcess(command, 0 if command[1] != "print" else 113, "", "")

    launchctl = Launchctl(501, run)
    launchctl.load(tmp_path / "opscout.check.plist")
    assert launchctl.is_loaded("opscout.check") is False
    launchctl.unload("opscout.check")
    assert calls == [
        ["/bin/launchctl", "bootstrap", "gui/501", str(tmp_path / "opscout.check.plist")],
        ["/bin/launchctl", "print", "gui/501/opscout.check"],
        ["/bin/launchctl", "print", "gui/501/opscout.check"],
    ]


# The real service manager (FR-027): macOS only, in a GUI session


def _gui_domain() -> bool:
    if sys.platform != "darwin" or shutil.which("launchctl") is None:
        return False
    result = subprocess.run(  # noqa: S603  (a fixed program)
        ["/bin/launchctl", "print", f"gui/{os.getuid()}"],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


@pytest.mark.launchd
@pytest.mark.skipif(not _gui_domain(), reason="needs launchd and a GUI session (macOS)")
@spec("FR-027")
def test_the_real_launchd_loads_and_unloads(tmp_path: Path) -> None:
    label = f"opscout.test-{uuid.uuid4().hex[:8]}"
    plist = tmp_path / f"{label}.plist"
    plist.write_bytes(
        plistlib.dumps(
            {
                "Label": label,
                "ProgramArguments": ["/usr/bin/true"],
                "StartCalendarInterval": [{"Hour": 3, "Minute": 0, "Weekday": 0}],
            },
            sort_keys=True,
        )
    )
    launchctl = Launchctl(os.getuid())
    try:
        launchctl.load(plist)
        assert launchctl.is_loaded(label) is True
    finally:
        launchctl.unload(label)
    assert launchctl.is_loaded(label) is False


@spec("FR-009")
def test_an_add_first_unloads_a_job_left_loaded_without_its_file(agents: Path) -> None:
    manager = RecordingManager(loaded={"opscout.check"})
    scheduler = LaunchdScheduler(agents, manager)
    scheduler.apply(scheduler.plan([job()]))
    assert manager.calls == [("unload", "opscout.check"), ("load", "opscout.check.plist")]


@spec("FR-010")
def test_a_kept_alive_entry_runs_at_login_and_after_an_error() -> None:
    gateway = ScheduledJob(
        name="gateway",
        arguments=(*COMMAND, "gateway", "--config", "/opt/config"),
        times=(),
        log=Path("/opt/log/gateway.log"),
        environment=MappingProxyType({"PATH": "/usr/bin:/bin"}),
        keep_alive=True,
    )
    data: dict[str, Any] = plistlib.loads(plist_bytes(gateway))
    assert data["Label"] == "opscout.gateway"
    assert data["RunAtLoad"] is True
    assert data["KeepAlive"] == {"SuccessfulExit": False}
    assert data["ThrottleInterval"] == 30
    assert "StartCalendarInterval" not in data
    assert "RunAtLoad" not in plistlib.loads(plist_bytes(job()))


@spec("FR-011")
def test_unload_waits_until_launchd_has_let_the_job_go() -> None:
    answers = iter([0, 0, 0, 113])  # loaded; then still loaded twice after the bootout
    calls: list[list[str]] = []
    slept: list[float] = []

    def run(command: list[str]) -> "subprocess.CompletedProcess[str]":
        calls.append(command)
        code = 0 if command[1] == "bootout" else next(answers)
        return subprocess.CompletedProcess(command, code, "", "")

    Launchctl(501, run, sleep=slept.append).unload("opscout.gateway")
    assert [c[1] for c in calls] == ["print", "bootout", "print", "print", "print"]
    assert slept == [0.5, 0.5]


@spec("FR-011")
def test_unload_gives_up_after_15_seconds() -> None:
    def run(command: list[str]) -> "subprocess.CompletedProcess[str]":
        return subprocess.CompletedProcess(command, 0, "", "")

    slept: list[float] = []
    with pytest.raises(SchedulerError, match="still loaded"):
        Launchctl(501, run, sleep=slept.append).unload("opscout.gateway")
    assert sum(slept) == pytest.approx(15)


@spec("FR-013")
def test_a_restart_kickstarts_the_loaded_job(agents: Path) -> None:
    from opscout.core.daemon import PendingSchedule, SchedulerChange

    manager = RecordingManager(loaded={"opscout.gateway"})
    LaunchdScheduler(agents, manager).apply(
        PendingSchedule((SchedulerChange("restart", "opscout.gateway", None, None),))
    )
    assert manager.calls == [("restart", "opscout.gateway")]
    calls: list[list[str]] = []

    def run(command: list[str]) -> "subprocess.CompletedProcess[str]":
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    Launchctl(501, run).restart("opscout.gateway")
    assert calls == [["/bin/launchctl", "kickstart", "-k", "gui/501/opscout.gateway"]]
