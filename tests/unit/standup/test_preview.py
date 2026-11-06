# SPDX-License-Identifier: Apache-2.0
"""`opscout standup preview`: what would be sent, and nothing sent (spec 009, FR-022)."""

from pathlib import Path

import pytest

from opscout.entrypoints.cli import main
from tests.unit.standup.test_job import SENTINEL, World, make_world


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    return make_world(tmp_path, monkeypatch)


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 009."""
    return pytest.mark.spec("009", requirement)


@spec("FR-022")
def test_the_preview_shows_the_facts_as_the_model_would_get_them(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["standup", "preview", "--config", str(world.config)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Window: Wednesday 4 00:00 to Thursday 5 00:00 (local time)\n")
    assert (
        "[s1] example-api 2026-11-04 08:00 sessions: "
        "Fix the export retry; key sentinel-prompt-secret-[credential]"
    ) in out
    assert "[p2] example-api" in out
    assert SENTINEL not in out
    assert "Counts: sessions 1, commits 1, pull requests 2, reviews waiting 0" in out
    assert "Redactions: credential 1" in out
    assert "Missing: none" in out
    assert world.runner.calls == []
    assert world.delivery.sent == []
    assert world.store.saved == []


@spec("FR-022")
def test_counts_only(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["standup", "preview", "--counts", "--config", str(world.config)]) == 0
    out = capsys.readouterr().out
    assert "[s1]" not in out
    assert "Counts:" in out


@spec("FR-022")
def test_without_the_section_it_says_so(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    world.write("schema_version: 1\n")
    assert main(["standup", "preview", "--config", str(world.config)]) == 2
    assert "no standup section" in capsys.readouterr().err
