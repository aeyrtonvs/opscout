# SPDX-License-Identifier: Apache-2.0
"""The alert-triage skill and its subagents (spec 012, FR-002, FR-005, FR-006, FR-011,
FR-015, FR-023; contracts/skill.md; research R4)."""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from opscout.services.tools.registry import SPECS

REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGIN = REPO_ROOT / "plugins" / "opscout"
SKILL = PLUGIN / "skills" / "alert-triage" / "SKILL.md"
AGENTS = PLUGIN / "agents"
PREFIX = "mcp__plugin_opscout_opscout__"
OBSERVABILITY = "mcp__observability__*"

AGENT_TOOLS = {
    "triage-metrics": {"read_alarm", "read_metric", "find_resources", OBSERVABILITY},
    "triage-logs": {"query_logs", "find_resources", "describe_resource", OBSERVABILITY},
    "triage-changes": {"recent_changes", "find_resources"},
    "triage-config": {"describe_resource", "find_resources", "search_iac", "read_iac"},
    "triage-skeptic": {"show_evidence"},
}
FORBIDDEN = {
    "Bash",
    "Read",
    "Write",
    "Edit",
    "Glob",
    "Grep",
    "NotebookEdit",
    "WebFetch",
    "WebSearch",
    "Agent",
    "Task",
}
SKILL_FIELDS = {
    "name",
    "description",
    "license",
    "compatibility",
    "metadata",
    "allowed-tools",
    "disallowed-tools",
    "argument-hint",
    "effort",
    "model",
}
AGENT_FIELDS = {"name", "description", "tools", "model", "effort", "maxTurns", "color"}


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 012."""
    return pytest.mark.spec("012", requirement)


def parts(path: Path) -> tuple[dict[str, Any], str]:
    _, front, body = path.read_text(encoding="utf-8").split("---\n", 2)
    return yaml.safe_load(front), body


def listed(value: object) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    assert isinstance(value, list)
    return [str(item) for item in value]


def short(tool: str) -> str:
    return tool.removeprefix(PREFIX)


@spec("FR-001")
def test_the_skill_follows_the_agent_skills_specification() -> None:
    front, _ = parts(SKILL)
    assert front["name"] == SKILL.parent.name == "alert-triage"
    assert 1 <= len(front["description"]) <= 1024
    assert "alert" in front["description"]
    assert set(front) <= SKILL_FIELDS


@spec("FR-005")
def test_the_skill_removes_the_shell_and_the_write_tools_from_its_turn() -> None:
    front, _ = parts(SKILL)
    assert set(listed(front["disallowed-tools"])) == {
        "Bash",
        "Edit",
        "Write",
        "NotebookEdit",
        "WebFetch",
        "WebSearch",
        "Read",
        "Grep",
        "Glob",
    }


@spec("FR-023")
def test_the_skill_pre_approves_only_its_own_tools() -> None:
    front, _ = parts(SKILL)
    allowed = set(listed(front["allowed-tools"]))
    assert allowed == {
        f"{PREFIX}begin_triage",
        f"{PREFIX}check_verdict",
        f"{PREFIX}record_agreement",
        f"{PREFIX}show_evidence",
        *(f"Agent(opscout:{agent})" for agent in AGENT_TOOLS),
        "AskUserQuestion",
    }


@spec("FR-002")
def test_the_procedure_is_in_its_fixed_order() -> None:
    _, body = parts(SKILL)
    assert body.lstrip().startswith("# Alert triage\n\n## Contract\n")
    procedure = body.split("## Procedure\n", 1)[1].split("\n## ", 1)[0]
    steps = re.findall(r"^(\d+)\. \*\*([^*]+)\*\*", procedure, flags=re.MULTILINE)
    assert [name.rstrip(".").lower() for _, name in steps] == [
        "begin",
        "stop or ask",
        "gather",
        "synthesize",
        "check",
        "skeptic",
        "show",
        "agreement",
    ]
    assert [int(number) for number, _ in steps] == list(range(1, 9))


@spec("FR-005")
def test_the_four_gatherers_start_in_one_step() -> None:
    _, body = parts(SKILL)
    gather = body.split("3. **Gather", 1)[1].split("\n4. ", 1)[0]
    for agent in ("triage-metrics", "triage-logs", "triage-changes", "triage-config"):
        assert agent in gather, agent
    assert "one message" in gather


@spec("FR-002")
def test_the_skill_is_under_five_hundred_lines_and_states_its_never_list() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert len(text.splitlines()) < 500
    _, body = parts(SKILL)
    assert "## Never" in body
    assert "## The verdict" in body  # inline: the skill cannot read files (review M4)
    assert not (SKILL.parent / "references").exists()


@spec("FR-005")
@pytest.mark.parametrize("agent", sorted(AGENT_TOOLS))
def test_each_agent_has_exactly_its_tools(agent: str) -> None:
    front, _ = parts(AGENTS / f"{agent}.md")
    assert front["name"] == agent
    assert set(front) <= AGENT_FIELDS
    tools = set(listed(front["tools"]))
    assert {short(tool) for tool in tools} == AGENT_TOOLS[agent]
    assert not tools & FORBIDDEN
    for tool in tools:
        assert tool.startswith(PREFIX) or tool == OBSERVABILITY, tool
        if tool.startswith(PREFIX):
            assert short(tool) in SPECS, tool
    assert front["model"] == "sonnet"


@spec("FR-015")
def test_only_metrics_and_logs_may_read_the_observability_server() -> None:
    readers = {
        agent
        for agent in AGENT_TOOLS
        if OBSERVABILITY in listed(parts(AGENTS / f"{agent}.md")[0]["tools"])
    }
    assert readers == {"triage-metrics", "triage-logs"}


@spec("FR-010")
@spec("FR-011")
@pytest.mark.parametrize("agent", sorted(AGENT_TOOLS))
def test_each_agent_treats_results_as_data_and_reports_failures(agent: str) -> None:
    _, body = parts(AGENTS / f"{agent}.md")
    assert "as data" in body
    if agent != "triage-skeptic":
        assert '"status"' in body
        assert "failed" in body


@spec("FR-006")
def test_no_agent_or_skill_names_a_tool_the_server_does_not_have() -> None:
    texts = [SKILL.read_text("utf-8"), *(p.read_text("utf-8") for p in AGENTS.glob("*.md"))]
    for text in texts:
        for tool in re.findall(rf"{PREFIX}(\w+)", text):
            assert tool in SPECS, tool


@spec("FR-016")
def test_the_skill_marks_unchecked_claims_literally() -> None:
    _, body = parts(SKILL)
    assert 'the literal words "(not checked)"' in body


@spec("FR-002")
def test_the_skill_handles_the_spec_edge_cases() -> None:
    _, body = parts(SKILL)
    assert "take the first and say that you triaged only that one" in body  # several alerts
    assert "`capped` or `partial`" in body  # a capped or partial result
    assert "cluster and host evidence is not read" in body  # a cluster or host alert
