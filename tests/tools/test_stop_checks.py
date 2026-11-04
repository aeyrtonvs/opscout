# SPDX-License-Identifier: Apache-2.0
"""Before the agent stops, the fast checks run and block the stop once (ADR-0018)."""

from tools.hooks._protocol import Result
from tools.hooks.stop_checks import decide

FAILING = Result(1, "src/opscout/core/model.py:3: error: Missing return statement\nFound 1 error")
PASSING = Result(0, "3 passed")


class FakeChecks:
    """Counts the runs and returns a fixed result."""

    def __init__(self, result: Result) -> None:
        self.runs = 0
        self.result = result

    def __call__(self) -> Result:
        self.runs += 1
        return self.result


def stop_event(*, continuing: bool) -> dict[str, object]:
    return {"hook_event_name": "Stop", "stop_hook_active": continuing}


def test_failing_checks_block_the_first_stop_and_say_why() -> None:
    decision = decide(stop_event(continuing=False), FakeChecks(FAILING))

    assert decision is not None
    assert decision["decision"] == "block"
    assert "Found 1 error" in decision["reason"]


def test_the_stop_after_a_block_goes_through_without_running_the_checks_again() -> None:
    checks = FakeChecks(FAILING)

    assert decide(stop_event(continuing=True), checks) is None
    assert checks.runs == 0


def test_passing_checks_let_the_agent_stop() -> None:
    assert decide(stop_event(continuing=False), FakeChecks(PASSING)) is None


def test_a_long_report_keeps_its_end() -> None:
    output = "\n".join(f"line {number}" for number in range(1000))

    decision = decide(stop_event(continuing=False), FakeChecks(Result(1, output)))

    assert decision is not None
    assert "line 999" in decision["reason"]
    assert "line 0\n" not in decision["reason"]
