# SPDX-License-Identifier: Apache-2.0
"""The standup's evaluation cases and their graders, with a fake runner (spec 009, FR-018)."""

import copy
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from opscout.core.daemon import RunnerFacts, RunProfile, RunResult
from tools.standup_evals import CASES, evaluate, load_case, main

FACTS = RunnerFacts(
    claude_code_version="2.1.318", model="claude-sonnet-5-5", api_key_source="none",
    cost_usd=0.02, turns=2, duration_ms=4000, tools_called=("StructuredOutput",), attempts=1,
)  # fmt: skip
NAMES = sorted(path.stem for path in CASES.glob("*.yaml"))


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 009."""
    return pytest.mark.spec("009", requirement)


@dataclass
class Replay:
    """Returns given outputs, validated as ClaudeCliRunner validates them."""

    outputs: list[dict[str, Any]]
    prompts: list[str] = field(default_factory=list)
    cost: float = 0.02

    def run(self, profile: RunProfile, prompt: str, env: Mapping[str, str]) -> RunResult:
        self.prompts.append(prompt)
        raw = self.outputs[min(len(self.prompts) - 1, len(self.outputs) - 1)]
        facts = FACTS.model_copy(update={"cost_usd": self.cost})
        try:
            output = profile.output.model_validate(
                raw, context=dict(profile.validation_context or {})
            )
        except ValidationError as error:
            return RunResult("invalid_output", reason=str(error), facts=facts)
        return RunResult("ok", output=output, facts=facts)


@spec("FR-018")
def test_the_suite_holds_the_planned_cases() -> None:
    assert NAMES == [
        "bitbucket-missing", "large-day", "monday-covers-weekend", "ordinary-tuesday",
        "planted-instructions", "planted-secrets", "quiet-day", "stale-review-blocker",
    ]  # fmt: skip


@spec("FR-018")
@pytest.mark.parametrize("name", NAMES)
def test_each_case_passes_with_its_reference_output(name: str) -> None:
    case = load_case(CASES / f"{name}.yaml")
    outputs = [case.good] if case.good else []
    result = evaluate(case, Replay(outputs))
    assert result.failures == [], result.failures
    assert result.quiet is case.expect.get("quiet", False)


def broken(name: str, change: Any) -> list[str]:
    case = load_case(CASES / f"{name}.yaml")
    assert case.good is not None
    output = copy.deepcopy(case.good)
    change(output)
    return evaluate(case, Replay([output])).failures


@spec("FR-018")
def test_the_graders_catch_a_wrong_output() -> None:
    cites_nothing_real = broken("ordinary-tuesday", lambda o: o["today"][0].update(facts=["x9"]))
    assert any("unknown fact x9" in failure for failure in cites_nothing_real)
    drops_blocker = broken("stale-review-blocker", lambda o: o.update(blockers=[]))
    assert any("blocker p2 is left out" in failure for failure in drops_blocker)
    leaks = broken("planted-secrets", lambda o: o.update(note="mail jane.doe@example.com"))
    assert any("jane.doe@example.com" in failure for failure in leaks)
    obeys = broken("planted-instructions", lambda o: o["yesterday"][0].update(text="PINEAPPLE"))
    assert any("PINEAPPLE" in failure for failure in obeys)


@spec("FR-018")
def test_planted_values_never_reach_the_prompt() -> None:
    case = load_case(CASES / "planted-secrets.yaml")
    replay = Replay([case.good] if case.good else [])
    evaluate(case, replay)
    [prompt] = replay.prompts
    for value in case.expect["absent"]:
        assert value not in prompt


@spec("FR-018")
def test_the_command_stops_at_the_cost_ceiling_and_fails_on_a_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    def replay_of_good() -> Replay:
        return Replay([{"yesterday": [], "today": [], "blockers": []}], cost=0.3)

    monkeypatch.setattr("tools.standup_evals.make_runner", lambda model: replay_of_good())
    assert main(["--max-cost-usd", "0.5"]) == 1
    out = capsys.readouterr().out
    assert "stopped: the cost ceiling of 0.50 USD was reached" in out
    assert "fail" in out
