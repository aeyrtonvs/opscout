# SPDX-License-Identifier: Apache-2.0
"""The headless eval runner for the plugin's skills (spec 003, FR-028; ADR-0013 amended)."""

import json
import os
import sys
from pathlib import Path

import pytest

from tools.skill_evals import (
    Arm,
    Grader,
    case_score,
    grade,
    load_cases,
    main,
    parse_stream,
)


def spec(requirement: str) -> pytest.MarkDecorator:
    return pytest.mark.spec("003", requirement)


def write_case(root: Path, name: str, prompt: str, graders: dict[str, str]) -> None:
    case = root / name
    (case / "graders").mkdir(parents=True)
    (case / "prompt.md").write_text(
        f"---\nmax_turns: 4\nallowed_tools: [Skill]\ntags: [FR-015]\n---\n\n{prompt}\n",
        encoding="utf-8",
    )
    for file, text in graders.items():
        (case / "graders" / f"{file}.md").write_text(text, encoding="utf-8")


REGEX_ABSENT = (
    "---\ntype: regex\npattern: 'example-cache'\nflags: 'i'\nmatch: 'not_contains'\n---\n"
)
REGEX_COUNT = "---\ntype: regex\npattern: '```'\nmatch: 'count:2'\n---\n"
SKILL_USED = "---\ntype: tool_used\ntool: 'Skill'\ninput_match: 'summary'\n---\n"
JUDGE = "---\ntype: llm\n---\nOnly facts from the message.\n"


def test_cases_and_graders_are_loaded(tmp_path: Path) -> None:
    write_case(tmp_path, "003-us1-s1", "Summarize.", {"absent": REGEX_ABSENT, "used": SKILL_USED})

    (case,) = load_cases(tmp_path)

    assert (case.name, case.prompt, case.max_turns, case.allowed_tools) == (
        "003-us1-s1",
        "Summarize.",
        4,
        ["Skill"],
    )
    assert [(g.name, g.type) for g in case.graders] == [("absent", "regex"), ("used", "tool_used")]


@pytest.mark.parametrize(
    ("grader", "text", "passed"),
    [
        (
            Grader("g", "regex", pattern="example-cache", flags="i", match="not_contains"),
            "EXAMPLE-CACHE",
            False,
        ),
        (
            Grader("g", "regex", pattern="example-cache", flags="i", match="not_contains"),
            "fine",
            True,
        ),
        (Grader("g", "regex", pattern="```", match="count:2"), "```text\nx\n```", True),
        (Grader("g", "regex", pattern="```", match="count:2"), "no block", False),
        (
            Grader("g", "regex", pattern="What happened[\\s\\S]*Why"),
            "What happened\n...\nWhy",
            True,
        ),
    ],
    ids=["absent-found", "absent-ok", "count-ok", "count-missing", "contains"],
)
def test_regex_graders_match_the_final_reply(grader: Grader, text: str, passed: bool) -> None:
    assert (
        grade(
            grader, Arm(text=text, tools=[], cost=0.0), judge=lambda criteria, message, text: True
        )
        is passed
    )


def test_a_tool_used_grader_counts_within_its_bounds() -> None:
    never = Grader("g", "tool_used", tool="Bash", minimum=0, maximum=0)

    assert grade(never, Arm("", [("Skill", "{}")], 0.0), lambda c, m, t: True)
    assert not grade(never, Arm("", [("Bash", '{"command": "curl"}')], 0.0), lambda c, m, t: True)


def test_a_multiline_regex_anchors_at_line_starts() -> None:
    grader = Grader("g", "regex", pattern="^Why$", flags="m")

    assert grade(grader, Arm("What happened\nWhy\nx", [], 0.0), lambda c, m, t: True)
    assert not grade(grader, Arm("So, Why not", [], 0.0), lambda c, m, t: True)


def test_a_tool_used_grader_reads_the_tool_calls() -> None:
    grader = Grader("g", "tool_used", tool="Skill", input_match="summary")

    assert grade(
        grader, Arm("", [("Skill", '{"skill": "opscout:summary"}')], 0.0), lambda c, m, t: True
    )
    assert not grade(grader, Arm("", [("Bash", "{}")], 0.0), lambda c, m, t: True)


def test_an_llm_grader_shows_the_judge_the_message_and_the_reply() -> None:
    grader = Grader("g", "llm", criteria="Only facts.")
    seen: list[tuple[str, str, str]] = []

    def judge(criteria: str, message: str, text: str) -> bool:
        seen.append((criteria, message, text))
        return False

    assert not grade(grader, Arm("reply", [], 0.0, "the user's message"), judge)
    assert seen == [("Only facts.", "the user's message", "reply")]


def test_the_skill_indicator_is_left_out_of_a_two_arm_score() -> None:
    graders = [
        Grader("absent", "regex", pattern="x", match="not_contains"),
        Grader("used", "tool_used", tool="Skill"),
    ]

    assert case_score(graders, {"absent": True, "used": False}, two_arms=True) == 1.0
    assert case_score(graders, {"absent": True, "used": False}, two_arms=False) == 0.5


def test_a_stream_gives_the_reply_the_tool_calls_and_the_cost() -> None:
    stream = "\n".join(
        json.dumps(event)
        for event in [
            {"type": "system", "subtype": "init"},
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "tool_use", "name": "Skill", "input": {"skill": "opscout:summary"}}
                    ]
                },
            },
            {"type": "result", "result": "```text\nx\n```", "total_cost_usd": 0.12},
        ]
    )

    arm = parse_stream(stream)

    assert arm == Arm("```text\nx\n```", [("Skill", '{"skill": "opscout:summary"}')], 0.12)


FAKE_CLAUDE = """#!{python}
import json, sys
args = sys.argv[1:]
if "--model" in args:  # the judge
    print(json.dumps({{"type": "result", "result": "PASS", "total_cost_usd": 0.001}}))
    sys.exit(0)
with_plugin = "--plugin-dir" in args
if with_plugin and not args[args.index("--plugin-dir") + 1].startswith("/"):
    sys.exit("relative plugin path")  # each run starts in an empty directory
events = []
if with_plugin:
    events.append({{"type": "assistant", "message": {{"content": [
        {{"type": "tool_use", "name": "Skill", "input": {{"skill": "opscout:summary"}}}}]}}}})
reply = "```text\\nWhat happened\\n```" if with_plugin else "We checked example-cache first."
events.append({{"type": "result", "result": reply, "total_cost_usd": 0.1}})
print("\\n".join(json.dumps(e) for e in events))
"""


@spec("FR-028")
def test_the_runner_scores_both_arms_and_records_the_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    evals = tmp_path / "evals"
    write_case(
        evals,
        "003-us1-s1",
        "Summarize.",
        {"absent": REGEX_ABSENT, "block": REGEX_COUNT, "used": SKILL_USED, "facts": JUDGE},
    )
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "claude").write_text(FAKE_CLAUDE.format(python=sys.executable), encoding="utf-8")
    (fake / "claude").chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake}{os.pathsep}{os.environ['PATH']}")
    out = tmp_path / "result.json"

    monkeypatch.chdir(tmp_path)
    status = main(
        [
            "--plugin",
            "plugin",
            "--evals",
            str(evals),
            "--config-dir",
            str(tmp_path),
            "--threshold",
            "0.9",
            "--max-cost-usd",
            "2",
            "--out",
            str(out),
        ]
    )

    result = json.loads(out.read_text(encoding="utf-8"))
    (case,) = result["cases"]
    assert status == 0
    assert (case["name"], case["with"]["score"]) == ("003-us1-s1", 1.0)
    assert case["without"]["score"] == pytest.approx(1 / 3)  # the fake judge passes both arms
    assert result["lowest_score"] == 1.0
    assert result["mean_delta"] == pytest.approx(2 / 3)
    assert result["cost_usd"] == pytest.approx(0.206)  # two arms, three judge votes each
    assert "003-us1-s1" in capsys.readouterr().out


def test_the_runner_stops_at_the_cost_ceiling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evals = tmp_path / "evals"
    for name in ("003-us1-s1", "003-us1-s2"):
        write_case(evals, name, "Summarize.", {"absent": REGEX_ABSENT})
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "claude").write_text(FAKE_CLAUDE.format(python=sys.executable), encoding="utf-8")
    (fake / "claude").chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake}{os.pathsep}{os.environ['PATH']}")
    out = tmp_path / "result.json"

    monkeypatch.chdir(tmp_path)
    status = main(
        [
            "--plugin",
            "plugin",
            "--evals",
            str(evals),
            "--config-dir",
            str(tmp_path),
            "--max-cost-usd",
            "0.15",
            "--max-run-usd",
            "0.1",
            "--out",
            str(out),
        ]
    )

    result = json.loads(out.read_text(encoding="utf-8"))
    assert status == 2
    assert result["partial"] is True
    assert result["cost_usd"] <= 0.15  # no run starts unless its own ceiling still fits
    assert result["cases"] == []


def test_a_case_with_its_own_configuration_runs_with_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evals = tmp_path / "evals"
    write_case(evals, "003-us3-s5", "Summarize.", {"absent": REGEX_ABSENT})
    (evals / "003-us3-s5" / "eval-config").mkdir()
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "claude").write_text(
        f"#!{sys.executable}\nimport json, os\n"
        "print(json.dumps({'type': 'result', 'result': os.environ['OPSCOUT_CONFIG'], "
        "'total_cost_usd': 0}))\n",
        encoding="utf-8",
    )
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
        ]
    )

    (case,) = json.loads(out.read_text(encoding="utf-8"))["cases"]
    assert case["with"]["reply"] == str((evals / "003-us3-s5" / "eval-config").resolve())


def test_the_runner_fails_when_the_plugin_does_not_beat_the_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evals = tmp_path / "evals"
    write_case(
        evals, "003-us1-s1", "Summarize.", {"present": "---\ntype: regex\npattern: 'x'\n---\n"}
    )
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "claude").write_text(
        f"#!{sys.executable}\nimport json\n"
        "print(json.dumps({'type': 'result', 'result': 'x', 'total_cost_usd': 0.01}))\n",
        encoding="utf-8",
    )
    (fake / "claude").chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake}{os.pathsep}{os.environ['PATH']}")

    status = main(
        [
            "--plugin",
            str(tmp_path),
            "--evals",
            str(evals),
            "--config-dir",
            str(tmp_path),
            "--max-cost-usd",
            "2",
        ]
    )

    assert status == 1  # both arms score 1.00: a delta of 0 is not above the baseline
