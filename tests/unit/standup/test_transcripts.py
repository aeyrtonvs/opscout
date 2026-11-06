# SPDX-License-Identifier: Apache-2.0
"""Reading the user's prompts from Claude Code transcripts (spec 009, FR-004; research R1).

The samples follow the shapes of Claude Code 2.1.318's local transcripts, with fake values.
"""

import os
import shutil
from pathlib import Path

import pytest

from opscout.adapters.claude_transcripts import TranscriptFiles
from opscout.services.standup import window_for
from tests.unit.standup.fakes import API, at

SAMPLES = Path(__file__).parent / "samples" / "transcripts"
WINDOW = window_for(at(5, 9, 45), ["mon", "tue", "wed", "thu", "fri"])  # Wednesday 4


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 009."""
    return pytest.mark.spec("009", requirement)


@pytest.fixture
def projects(tmp_path: Path) -> Path:
    root = tmp_path / "projects"
    shutil.copytree(SAMPLES, root)
    return root


@spec("FR-004")
def test_only_the_user_s_own_prompts_in_the_window(projects: Path) -> None:
    scan = TranscriptFiles(projects).scan(WINDOW, [Path(API)])
    by_session = {session.session[-3:]: session for session in scan.sessions}
    assert set(by_session) == {"001", "003"}
    texts = [text for _, text in by_session["001"].prompts]
    assert texts == [
        "Fix the retry of the export job in example-api",
        "Check this alert and open a PR",
        "Look at this",
        "Then retry",
        "Also add a test for the retry",
        "Then push it",
        "Late prompt before midnight",
    ]
    assert by_session["001"].cwd == API
    assert by_session["003"].cwd == f"{API}/web"
    assert scan.unreadable == 1


@spec("FR-004")
def test_replies_tool_output_pasted_text_and_system_lines_never_appear(projects: Path) -> None:
    scan = TranscriptFiles(projects).scan(WINDOW, [Path(API)])
    everything = " ".join(text for s in scan.sessions for _, text in s.prompts)
    for absent in (
        "xoxb-assistant-only", "secret tool output", "Caveat", "background task",
        "output", "/clear", "aws sso login", "logged in", "continued from",
        "CRITICAL", "192.0.2.10", "after midnight", "Something private",
        "123456789012", "pasted_content", "Request interrupted", "Subagent brief",
    ):  # fmt: skip
        assert absent not in everything, absent


@spec("FR-004")
def test_sessions_outside_the_projects_are_not_read(projects: Path) -> None:
    scan = TranscriptFiles(projects).scan(WINDOW, [Path("/opt/example/src/example-web")])
    assert scan.sessions == ()


@spec("FR-004")
def test_files_older_than_the_window_are_skipped(projects: Path) -> None:
    old = WINDOW.start.timestamp() - 3600
    for path in projects.rglob("*.jsonl"):
        os.utime(path, (old, old))
    assert TranscriptFiles(projects).scan(WINDOW, [Path(API)]).sessions == ()


@spec("FR-008")
def test_a_missing_directory_is_a_source_error(tmp_path: Path) -> None:
    from opscout.core.standup import SourceError

    with pytest.raises(SourceError, match="no Claude Code transcripts"):
        TranscriptFiles(tmp_path / "missing").scan(WINDOW, [Path(API)])
