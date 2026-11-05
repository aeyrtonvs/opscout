# SPDX-License-Identifier: Apache-2.0
"""FileRunStore, LocalOutbox and two real starts at once (spec 007, US5)."""

import json
import os
import subprocess
import sys
import time
from datetime import timedelta
from pathlib import Path

import pytest

from opscout.adapters.run_files import FileRunStore, LocalOutbox
from opscout.core.daemon import CHECK, DeliveryError, RunnerFacts, RunRecord, StoreError
from opscout.entrypoints.cli import main
from tests.unit.daemon.fakes import START

STREAMS = Path(__file__).parent / "streams"
FAKE = Path(__file__).parent / "fake_claude.py"
REPO_ROOT = Path(__file__).resolve().parents[3]


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 007."""
    return pytest.mark.spec("007", requirement)


def record(run_id: str, *, job: str = "check", outcome: str = "delivered") -> RunRecord:
    started = START + timedelta(minutes=int(run_id[11:13]) - 30)
    return RunRecord.model_validate(
        {
            "run_id": run_id,
            "job": job,
            "period": "2026-11-05",
            "run_key": f"{job}:2026-11-05",
            "trigger": "scheduler",
            "forced": False,
            "engine_version": "0.0.0",
            "outcome": outcome,
            "reason": None if outcome == "delivered" else "x",
            "started_at": started,
            "ended_at": started + timedelta(seconds=2),
            "delivery": "/example/outbox/check/x.md" if outcome == "delivered" else None,
            "runner": None
            if outcome != "delivered"
            else RunnerFacts(
                claude_code_version="2.1.318",
                model="claude-haiku-5-5",
                api_key_source="none",
                cost_usd=0.0005,
                turns=2,
                duration_ms=1250,
                tools_called=("StructuredOutput",),
                attempts=1,
            ),
        }
    )


@spec("FR-020")
@spec("FR-021")
def test_a_record_is_one_json_file_with_every_field(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "data")
    written = record("20261105T083000Z-a1b2c3")
    store.write(written)
    path = tmp_path / "data" / "runs" / "check" / "20261105T083000Z-a1b2c3.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data) == {
        "run_id", "record_version", "job", "period", "run_key", "trigger", "forced",
        "engine_version", "outcome", "reason", "started_at", "ended_at", "inputs",
        "delivery", "runner", "agreement",
    }  # fmt: skip
    assert data["record_version"] == 1
    assert data["agreement"] is None
    assert data["started_at"] == "2026-11-05T09:30:00+01:00"
    assert CHECK.prompt not in path.read_text(encoding="utf-8")
    assert store.records("check", 10) == [written]


@spec("FR-020")
def test_a_failed_write_leaves_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = FileRunStore(tmp_path / "data")
    store.write(record("20261105T083000Z-a1b2c3"))

    def broken(self: Path, target: Path) -> Path:
        raise OSError("disk full")

    monkeypatch.setattr(Path, "replace", broken)
    with pytest.raises(StoreError):
        store.write(record("20261105T083100Z-d4e5f6"))
    names = sorted(p.name for p in (tmp_path / "data" / "runs" / "check").iterdir())
    assert names == ["20261105T083000Z-a1b2c3.json"]


@spec("FR-022")
def test_records_are_read_back_newest_first_by_job_and_by_key(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "data")
    for run_id, outcome in (
        ("20261105T083000Z-aaaaaa", "delivered"),
        ("20261105T083200Z-cccccc", "skipped"),
        ("20261105T083100Z-bbbbbb", "delivered"),
    ):
        store.write(record(run_id, outcome=outcome))
    store.write(record("20261105T083300Z-dddddd", job="other"))
    (tmp_path / "data" / "runs" / "check" / "broken.json").write_text("{", encoding="utf-8")

    assert [r.run_id for r in store.records("check", 10)] == [
        "20261105T083200Z-cccccc",
        "20261105T083100Z-bbbbbb",
        "20261105T083000Z-aaaaaa",
    ]
    assert [r.run_id for r in store.records(None, 2)] == [
        "20261105T083300Z-dddddd",
        "20261105T083200Z-cccccc",
    ]
    delivered = store.delivered("check:2026-11-05")
    assert delivered is not None
    assert delivered.run_id == "20261105T083100Z-bbbbbb"
    assert store.delivered("check:2026-11-06") is None
    assert FileRunStore(tmp_path / "nothing").records(None, 5) == []


HOLDER = """
import sys, time
from pathlib import Path
from opscout.adapters.run_files import FileRunStore
with FileRunStore(Path(sys.argv[1])).hold("check", "2026-11-05") as held:
    print("held" if held else "busy", flush=True)
    time.sleep(60)
"""


@spec("FR-004")
def test_the_lock_is_exclusive_between_processes_and_dies_with_its_holder(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "data")
    holder = subprocess.Popen(  # noqa: S603  (the test's own interpreter)
        [sys.executable, "-c", HOLDER, str(tmp_path / "data")],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "held"
        with store.hold("check", "2026-11-05") as held:
            assert held is False
        with store.hold("check", "2026-11-06") as held:
            assert held is True
    finally:
        holder.kill()
        holder.wait()
        if holder.stdout is not None:
            holder.stdout.close()
    with store.hold("check", "2026-11-05") as held:
        assert held is True


@spec("FR-008")
def test_the_outbox_writes_one_file_per_delivery(tmp_path: Path) -> None:
    outbox = LocalOutbox(tmp_path / "data")
    path = outbox.deliver("check", "20261105T083000Z-a1b2c3", "result", "# Text\n")
    assert path == str(tmp_path / "data" / "outbox" / "check" / "20261105T083000Z-a1b2c3.md")
    assert Path(path).read_text(encoding="utf-8") == "# Text\n"
    assert [p.name for p in Path(path).parent.iterdir()] == ["20261105T083000Z-a1b2c3.md"]


@pytest.mark.skipif(os.geteuid() == 0, reason="root writes anywhere")
@spec("FR-020")
def test_an_unwritable_store_or_outbox_raises(tmp_path: Path) -> None:
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        with pytest.raises(StoreError), FileRunStore(locked).hold("check", "2026-11-05"):
            pass
        with pytest.raises(DeliveryError):
            LocalOutbox(locked).deliver("check", "x", "result", "text")
    finally:
        locked.chmod(0o700)


def environment(tmp_path: Path) -> dict[str, str]:
    """An environment whose home, and so whose data directory, is the test's."""
    kept = {k: v for k, v in os.environ.items() if not k.startswith(("XDG_", "OPSCOUT_"))}
    return {**kept, "HOME": str(tmp_path / "home")}


def fake_claude(tmp_path: Path, *, pause: float) -> Path:
    directory = tmp_path / "bin"
    directory.mkdir()
    path = directory / "claude"
    source = FAKE.read_text(encoding="utf-8").split("\n", 1)[1]
    path.write_text(f"#!{sys.executable}\n{source}", encoding="utf-8")
    path.chmod(0o755)
    settings = {
        "log": str(directory / "log.jsonl"),
        "streams": [str(STREAMS / "success.jsonl")],
        "pause": pause,
    }
    path.with_suffix(".json").write_text(json.dumps(settings), encoding="utf-8")
    return path


@spec("FR-004")
@spec("FR-026")
def test_two_real_starts_at_once_deliver_once(tmp_path: Path) -> None:
    claude = fake_claude(tmp_path, pause=1)
    config = tmp_path / "config"
    config.mkdir()
    (config / "config.yaml").write_text(
        f'schema_version: 1\ndaemon:\n  jobs:\n    check:\n      at: "09:30"\n'
        f"  claude_path: {claude}\n",
        encoding="utf-8",
    )
    command = [sys.executable, "-m", "opscout", "run", "check", "--config", str(config)]
    env = environment(tmp_path)
    starts = [
        subprocess.Popen(  # noqa: S603  (the test's own interpreter)
            command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        for _ in range(2)
    ]
    outputs = [start.communicate(timeout=60) for start in starts]
    assert [start.returncode for start in starts] == [0, 0], outputs
    lines = sorted(out.strip() for out, _ in outputs)
    assert lines[0].startswith("check ")
    assert ": delivered to " in lines[0]
    assert ": skipped (" in lines[1]
    assert len((tmp_path / "bin" / "log.jsonl").read_text(encoding="utf-8").splitlines()) == 1

    began = time.monotonic()
    again = subprocess.run(  # noqa: S603  (the test's own interpreter)
        command, env=env, capture_output=True, text=True, check=False, timeout=60
    )
    assert time.monotonic() - began < 1, "a skipped start takes under one second (SC-006)"
    assert again.returncode == 0
    assert "skipped (already delivered by run" in again.stdout


@spec("FR-022")
def test_daemon_runs_lists_the_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from opscout.entrypoints import daemon as composition

    store = FileRunStore(tmp_path / "data")
    store.write(record("20261105T083000Z-a1b2c3"))
    store.write(record("20261105T083100Z-d4e5f6", outcome="skipped"))
    real = composition.wiring

    def wired() -> composition.Wiring:
        from dataclasses import replace

        return replace(real(), store=store)

    monkeypatch.setattr(composition, "wiring", wired)
    config = tmp_path / "config"
    config.mkdir()
    (config / "config.yaml").write_text("schema_version: 1\n", encoding="utf-8")
    assert main(["daemon", "runs", "--config", str(config)]) == 0
    assert capsys.readouterr().out == (
        "20261105T083100Z-d4e5f6  check  2026-11-05  scheduler  skipped       -           2.0 s\n"
        "20261105T083000Z-a1b2c3  check  2026-11-05  scheduler  delivered     0.0005 USD  2.0 s\n"
    )
    assert main(["daemon", "runs", "other", "--config", str(config)]) == 0
    assert capsys.readouterr().out == "No runs recorded.\n"
    assert main(["daemon", "runs", "--limit", "1", "--config", str(config)]) == 0
    assert capsys.readouterr().out.count("\n") == 1
