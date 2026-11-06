# SPDX-License-Identifier: Apache-2.0
"""Jobs, periods, run keys and run profiles (spec 007, FR-003, FR-007)."""

import json
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from opscout.core.config import Daemon, JobSettings, KeychainRef
from opscout.core.daemon import CHECK, JOBS, CheckOutput, RunnerFacts
from opscout.services.daemon import period_of, resolve_profile, run_key

LISBON_SUMMER = timezone(timedelta(hours=1))


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


@spec("FR-003")
def test_the_period_is_the_local_date_at_start() -> None:
    late = datetime(2026, 11, 5, 23, 59, 59, tzinfo=LISBON_SUMMER)
    assert period_of(late) == "2026-11-05"
    assert period_of(late + timedelta(seconds=2)) == "2026-11-06"
    assert run_key("check", "2026-11-05") == "check:2026-11-05"


@spec("FR-007")
def test_the_check_job_is_one_of_the_engine_s_jobs() -> None:
    assert set(JOBS) == {"check", "standup"}  # standup: spec 009
    assert JOBS["check"] is CHECK


@spec("FR-007")
def test_the_check_profile_defaults_and_overrides() -> None:
    profile = resolve_profile(CHECK, None, Daemon())
    assert profile.tools == ()
    assert dict(profile.mcp_servers) == {}
    assert (profile.model, profile.budget_usd, profile.max_turns) == ("haiku", 0.05, 3)
    assert profile.output is CheckOutput
    assert profile.schema == CheckOutput.model_json_schema()
    assert dict(profile.secrets) == {}

    settings = JobSettings(at="09:30", model="sonnet", budget_usd=0.2, max_turns=5)
    daemon = Daemon(secrets={"claude_token": KeychainRef(service="opscout-example")})
    profile = resolve_profile(CHECK, settings, daemon)
    assert (profile.model, profile.budget_usd, profile.max_turns) == ("sonnet", 0.2, 5)
    assert dict(profile.secrets) == {"CLAUDE_CODE_OAUTH_TOKEN": "claude_token"}


@spec("FR-007")
def test_the_check_output_is_small_and_strict() -> None:
    assert CheckOutput.model_validate({"ok": True, "note": "Fine."}).ok is True
    for bad in ({"ok": "yes", "note": "x"}, {"ok": True}, {"ok": True, "note": "x" * 301}):
        with pytest.raises(ValidationError):
            CheckOutput.model_validate(bad)
    json.dumps(CheckOutput.model_json_schema())


@spec("FR-007")
def test_the_check_prompt_and_text() -> None:
    assert "structured output" in CHECK.prompt
    text = CHECK.render(CheckOutput(ok=True, note="All good."), FACTS, "2026-11-05")
    for fact in ("2026-11-05", "2.1.318", "claude-haiku-5-5", "none", "0.0005", "1.2 s"):
        assert fact in text
    assert "All good." in text
