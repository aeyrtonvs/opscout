# SPDX-License-Identifier: Apache-2.0
"""The eval runner's triage keys: fixtures, mock mode, one arm, records (spec 012, FR-027,
FR-028; research R12)."""

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

from tools.skill_evals import Arm, Grader, grade, load_cases, main

FAKE_CLAUDE = """#!{python}
import json, os, pathlib, sys
config = pathlib.Path(os.environ["OPSCOUT_CONFIG"])
data = pathlib.Path(os.environ["OPSCOUT_DATA_DIR"])
runs = data / "triage" / "runs"
runs.mkdir(parents=True, exist_ok=True)
(runs / "20261106T120000Z-abcdef.json").write_text(json.dumps({{
    "outcome": "checked", "verdict": {{"classification": "real"}},
    "agreement": {{"answer": "not-answered"}}}}))
reply = json.dumps({{
    "config": (config / "config.yaml").read_text(),
    "mock": os.environ.get("OPSCOUT_MCP_MOCK", ""),
    "args": sys.argv[1:],
    "mcp": pathlib.Path(sys.argv[sys.argv.index("--mcp-config") + 1]).read_text()
    if "--mcp-config" in sys.argv else "",
}})
print(json.dumps({{"type": "result", "result": reply, "total_cost_usd": 0.01}}))
"""


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 012."""
    return pytest.mark.spec("012", requirement)


def fixture_tree(root: Path) -> Path:
    tree = root / "fixtures" / "real-deploy"
    (tree / "aws" / "example-prod").mkdir(parents=True)
    (tree / "infra").mkdir()
    (tree / "config.yaml").write_text(
        "schema_version: 1\ntriage:\n  infrastructure:\n"
        "    - {name: example-infra, path: '@CASE_ROOT@/infra'}\n",
        encoding="utf-8",
    )
    (tree / "observability.mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "observability": {"command": "@CASE_ROOT@/server", "args": ["@REPO_ROOT@"]}
                }
            }
        ),
        encoding="utf-8",
    )
    return tree


def write_case(evals: Path, name: str, front: str, graders: dict[str, str]) -> None:
    case = evals / name
    (case / "graders").mkdir(parents=True)
    (case / "prompt.md").write_text(f"---\n{front}---\n\nTriage this.\n", encoding="utf-8")
    for file, text in graders.items():
        (case / "graders" / f"{file}.md").write_text(text, encoding="utf-8")


RECORD = "---\ntype: record\nfield: verdict.classification\nequals: real\n---\n"
ANSWER = "---\ntype: record\nfield: agreement.answer\nequals: not-answered\n---\n"


def run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, evals: Path, *extra: str) -> dict:  # type: ignore[type-arg]
    fake = tmp_path / "bin"
    fake.mkdir(exist_ok=True)
    (fake / "claude").write_text(FAKE_CLAUDE.format(python=sys.executable), encoding="utf-8")
    (fake / "claude").chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake}{os.pathsep}{os.environ['PATH']}")
    out = tmp_path / "result.json"
    main(
        [
            "--plugin",
            str(tmp_path),
            "--evals",
            str(evals),
            "--config-dir",
            str(tmp_path),
            "--max-cost-usd",
            "2",
            "--out",
            str(out),
            *extra,
        ]
    )
    result: dict = json.loads(out.read_text(encoding="utf-8"))  # type: ignore[type-arg]
    return result


@spec("FR-027")
def test_a_fixture_case_runs_one_arm_with_its_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture_tree(tmp_path)
    evals = tmp_path / "evals"
    write_case(
        evals,
        "012-us1-s1",
        "fixture: real-deploy\narms: plugin\nmcp_config: observability.mcp.json\n"
        "allowed_tools: [Skill]\n",
        {"classified": RECORD, "answered": ANSWER},
    )

    result = run(tmp_path, monkeypatch, evals, "--fixtures", str(tmp_path / "fixtures"))

    (case,) = result["cases"]
    assert "without" not in case
    assert case["with"]["score"] == 1.0
    reply = json.loads(case["with"]["reply"])
    assert "@CASE_ROOT@" not in reply["config"]
    assert reply["config"].count("/infra") == 1
    assert reply["mock"].endswith("/aws")
    assert "--strict-mcp-config" not in reply["args"]  # it would drop the plugin's server
    assert "@CASE_ROOT@" not in reply["mcp"]
    assert reply["mcp"].count("/server") == 1
    assert "@REPO_ROOT@" not in reply["mcp"]
    assert result["lowest_score"] == 1.0


@spec("FR-027")
def test_every_run_gets_a_fresh_data_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture_tree(tmp_path)
    evals = tmp_path / "evals"
    for name in ("012-us1-s1", "012-us1-s2"):
        write_case(evals, name, "fixture: real-deploy\narms: plugin\n", {"one": RECORD})
    result = run(tmp_path, monkeypatch, evals, "--fixtures", str(tmp_path / "fixtures"))
    assert [case["with"]["score"] for case in result["cases"]] == [1.0, 1.0]
    assert not (tmp_path / "fixtures" / "real-deploy" / "data").exists()


@spec("FR-028")
def test_private_cases_find_fixtures_next_to_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private = tmp_path / "private"
    fixture_tree(private)
    write_case(private / "evals", "012-real-1", "fixture: real-deploy\narms: plugin\n", {})
    result = run(tmp_path, monkeypatch, private / "evals", "--fixtures", str(private / "fixtures"))
    (case,) = result["cases"]
    assert json.loads(case["with"]["reply"])["mock"].endswith("/aws")


@spec("FR-027")
def test_case_keys_are_loaded(tmp_path: Path) -> None:
    evals = tmp_path / "evals"
    write_case(
        evals,
        "012-us2-s1",
        "fixture: out-of-scope\narms: plugin\nmcp_config: x.json\n",
        {"r": RECORD},
    )
    (case,) = load_cases(evals)
    assert (case.fixture, case.arms, case.mcp_config) == ("out-of-scope", "plugin", "x.json")
    assert case.graders[0].field == "verdict.classification"
    assert case.graders[0].equals == "real"


@spec("FR-027")
@pytest.mark.parametrize(
    ("records", "field", "equals", "passed"),
    [
        ([{"outcome": "checked"}], "outcome", "checked", True),
        ([{"outcome": "open"}], "outcome", "checked", False),
        ([{"verdict": {"classification": "real"}}], "verdict.classification", "real", True),
        ([{"verdict": None}], "verdict.classification", "real", False),
        ([], "outcome", "checked", False),
        ([{"outcome": "checked"}, {"outcome": "checked"}], "outcome", "checked", False),
        ([{"check": {"attempts": 1}}], "check.attempts", "1", True),
        ([{"agreement": None}], "agreement", "null", True),
        ([{"outcome": "inconclusive"}], "outcome", "checked|inconclusive", True),
        ([{"outcome": "open"}], "outcome", "checked|inconclusive", False),
    ],
)
def test_the_record_grader_reads_the_only_record(
    records: list[dict[str, Any]],
    field: str,
    equals: str,
    passed: bool,
) -> None:
    grader = Grader(name="r", type="record", field=field, equals=equals)
    arm = Arm(text="", tools=[], cost=0.0, records=records)
    assert grade(grader, arm, lambda *_: True) is passed


@spec("FR-027")
def test_existing_two_arm_cases_still_run_both_arms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evals = tmp_path / "evals"
    write_case(evals, "003-us1-s1", "allowed_tools: [Skill]\n", {})
    monkeypatch.setenv("OPSCOUT_DATA_DIR", str(tmp_path / "unused"))
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "claude").write_text(
        f"#!{sys.executable}\nimport json\n"
        "print(json.dumps({'type': 'result', 'result': 'ok', 'total_cost_usd': 0}))\n",
        encoding="utf-8",
    )
    (fake / "claude").chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake}{os.pathsep}{os.environ['PATH']}")
    out = tmp_path / "result.json"
    main(["--plugin", str(tmp_path), "--evals", str(evals), "--config-dir", str(tmp_path),
          "--max-cost-usd", "2", "--out", str(out)])  # fmt: skip
    (case,) = json.loads(out.read_text(encoding="utf-8"))["cases"]
    assert {"with", "without"} <= set(case)


@spec("FR-027")
def test_a_tool_used_grader_may_name_a_server_by_prefix() -> None:
    arm = Arm(text="", tools=[("mcp__observability__search_traces", "{}")], cost=0.0)
    every = Grader(name="g", type="tool_used", tool="mcp__observability__*")
    exact = Grader(name="g", type="tool_used", tool="mcp__observability__get_metrics")
    assert grade(every, arm, lambda *_: True)
    assert not grade(exact, arm, lambda *_: True)


@spec("FR-029")
def test_a_configuration_override_reaches_every_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture_tree(tmp_path)
    evals = tmp_path / "evals"
    write_case(evals, "012-us6-s1", "fixture: real-deploy\narms: plugin\n", {})
    result = run(
        tmp_path,
        monkeypatch,
        evals,
        "--fixtures",
        str(tmp_path / "fixtures"),
        "--config-override",
        "triage: {skeptic: true}",
    )
    config = json.loads(result["cases"][0]["with"]["reply"])["config"]
    assert "skeptic: true" in config
    assert "example-infra" in config  # merged, not replaced


@spec("FR-027")
def test_the_runner_refuses_when_a_users_server_shadows_a_stand_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fixtures = tmp_path / "fixtures"
    fixture_tree(tmp_path)
    evals = tmp_path / "evals"
    write_case(
        evals,
        "012-us5-s1",
        "fixture: real-deploy\narms: plugin\nmcp_config: observability.mcp.json\n",
        {},
    )
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "claude").write_text(
        f"#!{sys.executable}\nimport sys\n"
        "print('observability: npx example-observability-mcp - Connected')\n",
        encoding="utf-8",
    )
    (fake / "claude").chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake}{os.pathsep}{os.environ['PATH']}")
    status = main(
        ["--plugin", str(tmp_path), "--evals", str(evals), "--config-dir", str(tmp_path),
         "--max-cost-usd", "2", "--fixtures", str(fixtures)]
    )  # fmt: skip
    assert status == 2
    assert "observability" in capsys.readouterr().err
