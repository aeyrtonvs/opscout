# SPDX-License-Identifier: Apache-2.0
"""The SessionStart notice about scheduled jobs (spec 007, FR-028, US5 scenario 5)."""

import json
import time
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from opscout.core.config import Daemon, JobSettings
from opscout.core.daemon import RunRecord, RunStore, Scheduler
from opscout.entrypoints import daemon as composition
from opscout.entrypoints.hook import session_start
from opscout.services.config import ConfigLocation, Source
from opscout.services.daemon import latest_slot, session_notices
from tests.unit.daemon.fakes import ZONE, MemoryRunStore, MemoryScheduler

# Thursday 2026-11-05, 10:00 local; the check job runs at 09:30 on weekdays.
NOW = datetime(2026, 11, 5, 10, 0, tzinfo=ZONE)
DAEMON = Daemon(
    jobs={"check": JobSettings(at="09:30", weekdays=["mon", "tue", "wed", "thu", "fri"])}
)
INSTALLED_YESTERDAY = {"check": NOW - timedelta(days=1)}


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 007."""
    return pytest.mark.spec("007", requirement)


def record(outcome: str, *, period: str = "2026-11-05", hour: int = 9) -> RunRecord:
    started = datetime.fromisoformat(f"{period}T{hour:02d}:30:00+01:00")
    return RunRecord.model_validate(
        {
            "run_id": f"{started:%Y%m%dT%H%M%S}Z-aaaaaa",
            "job": "check",
            "period": period,
            "run_key": f"check:{period}",
            "trigger": "scheduler",
            "forced": False,
            "engine_version": "0.0.0",
            "outcome": outcome,
            "reason": None if outcome == "delivered" else "x",
            "started_at": started,
            "ended_at": started + timedelta(seconds=2),
        }
    )


@spec("FR-028")
def test_nothing_is_said_when_all_is_well_or_nothing_is_configured() -> None:
    records = {"check": [record("delivered")]}
    assert session_notices(DAEMON, records, INSTALLED_YESTERDAY, NOW) is None
    assert session_notices(Daemon(), {}, {}, NOW) is None
    disabled = Daemon(jobs={"check": JobSettings(at="09:30", enabled=False)})
    assert session_notices(disabled, {}, {}, NOW) is None


@spec("FR-028")
@pytest.mark.parametrize(
    ("outcome", "words"),
    [("failed", "failed"), ("refused", "was refused"), ("inconclusive", "was inconclusive")],
)
def test_a_last_run_that_did_not_deliver_is_reported(outcome: str, words: str) -> None:
    records = {"check": [record("skipped", hour=9), record(outcome, hour=9)]}
    assert session_notices(DAEMON, records, INSTALLED_YESTERDAY, NOW) == (
        "opscout scheduled jobs:\n"
        f"- check: the last run {words} on 2026-11-05 09:30 (see opscout daemon runs check)"
    )


@spec("FR-028")
def test_a_missing_run_is_reported_after_the_grace_and_the_install() -> None:
    earlier = {"check": [record("delivered", period="2026-11-04")]}
    assert session_notices(DAEMON, earlier, INSTALLED_YESTERDAY, NOW) == (
        "opscout scheduled jobs:\n"
        "- check: no run for its 09:30 slot on 2026-11-05 (see opscout daemon runs check)"
    )
    within_grace = NOW.replace(hour=9, minute=40)
    assert session_notices(DAEMON, earlier, INSTALLED_YESTERDAY, within_grace) is None
    installed_after_slot = {"check": NOW.replace(hour=9, minute=50)}
    assert session_notices(DAEMON, earlier, installed_after_slot, NOW) is None


@spec("FR-028")
def test_the_latest_slot_skips_days_off() -> None:
    saturday = datetime(2026, 11, 7, 12, 0, tzinfo=ZONE)
    slot = latest_slot(DAEMON.jobs["check"], saturday)
    assert slot == datetime(2026, 11, 6, 9, 30, tzinfo=ZONE)


@spec("FR-028")
def test_a_configured_job_not_installed_is_reported_where_a_scheduler_exists() -> None:
    assert session_notices(DAEMON, {}, {}, NOW) == (
        "opscout scheduled jobs:\n"
        "- check: configured but not installed (run opscout daemon install)"
    )
    records = {"check": [record("delivered")]}
    assert session_notices(DAEMON, records, None, NOW) is None


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "config"
    directory.mkdir()
    (directory / "config.yaml").write_text(
        "schema_version: 1\nsso:\n  enabled: false\ndaemon:\n  jobs:\n    check:\n"
        '      at: "09:30"\n      weekdays: [mon, tue, wed, thu, fri]\n',
        encoding="utf-8",
    )
    return directory


def wire(monkeypatch: pytest.MonkeyPatch, store: RunStore, scheduler: Scheduler | None) -> None:
    real = composition.wiring
    monkeypatch.setattr(
        composition, "wiring", lambda: replace(real(), store=store, scheduler=scheduler)
    )


@spec("FR-028")
def test_the_hook_appends_the_notice_after_the_sso_warning(
    config_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = MemoryRunStore([record("failed")])
    wire(monkeypatch, store, MemoryScheduler(times={}))
    monkeypatch.setattr(
        "opscout.entrypoints.hook.render_warning", lambda *args: "opscout SSO check: example."
    )
    location = ConfigLocation(config_dir, Source.FLAG)
    output = json.loads(session_start(location, {}, tmp_path, NOW, ZONE))
    message = output["systemMessage"]
    assert message.startswith("opscout SSO check: example.\n\nopscout scheduled jobs:\n")
    assert "- check: configured but not installed" in message
    assert output["hookSpecificOutput"]["additionalContext"] == message


@spec("FR-028")
def test_the_hook_says_nothing_when_all_is_well(
    config_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = MemoryRunStore([record("delivered")])
    scheduler = MemoryScheduler()
    wire(monkeypatch, store, scheduler)
    monkeypatch.setattr(
        MemoryScheduler, "installed_times", lambda self: {"check": NOW - timedelta(days=3)}
    )
    location = ConfigLocation(config_dir, Source.FLAG)
    assert session_start(location, {}, tmp_path, NOW, ZONE) == ""


@spec("FR-028")
def test_an_unreadable_run_store_is_one_line_never_an_error(
    config_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Broken(MemoryRunStore):
        def records(self, job: str | None, limit: int) -> list[RunRecord]:
            raise PermissionError("denied")

    wire(monkeypatch, Broken(), MemoryScheduler())
    location = ConfigLocation(config_dir, Source.FLAG)
    began = time.monotonic()
    output = json.loads(session_start(location, {}, tmp_path, NOW, ZONE))
    assert time.monotonic() - began < 2, "within spec 005's time budget"
    assert output["systemMessage"] == (
        "opscout scheduled jobs: could not be checked (PermissionError)"
    )
