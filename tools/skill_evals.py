# SPDX-License-Identifier: Apache-2.0
"""Run the plugin's eval cases headlessly with ``claude -p`` (spec 003; ADR-0013 amended).

``claude plugin eval`` sandboxes each run to the plugin directory, so before the first
release it cannot run the engine from the clone. Until then this runner plays the same
cases (``evals/<case>/prompt.md`` and ``graders/*.md``) through ``claude -p``: once with the
plugin (``--plugin-dir``) and once without it, and grades them as ``claude plugin eval``
documents: regex graders on the final reply, ``tool_used`` on the tool calls (the Skill
indicator is left out of a two-arm score), and an ``llm`` grader as a majority of three
Haiku votes. Runs are isolated from the user's settings and MCP servers, start in an empty
directory, and stop at a cost ceiling.

    uv run python -m tools.skill_evals --plugin plugins/opscout \\
        --config-dir plugins/opscout/evals/eval-config --max-cost-usd 3
"""

import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

Judge = Callable[[str, str, str], bool]  # criterion, user message, reply
ISOLATION = ["--setting-sources", "project", "--strict-mcp-config", "--no-session-persistence"]


@dataclass(frozen=True)
class Grader:
    """One grader file: its type and the keys ``claude plugin eval`` documents."""

    name: str
    type: str
    weight: float = 1.0
    pattern: str = ""
    flags: str = ""
    match: str = ""
    tool: str = ""
    input_match: str = ""
    criteria: str = ""


@dataclass(frozen=True)
class Case:
    """One eval case: the prompt, the tools it allows, and its graders."""

    name: str
    prompt: str
    max_turns: int
    allowed_tools: list[str]
    graders: list[Grader] = field(default_factory=list)


@dataclass(frozen=True)
class Arm:
    """What one run produced: the final reply, the tool calls and the cost."""

    text: str
    tools: list[tuple[str, str]]
    cost: float
    prompt: str = ""


def _front(path: Path) -> tuple[dict[str, Any], str]:
    _, front, body = path.read_text(encoding="utf-8").split("---\n", 2)
    return yaml.safe_load(front) or {}, body.strip()


def load_cases(evals: Path) -> list[Case]:
    """Return every case under ``evals``, by name."""
    cases = []
    for prompt in sorted(evals.glob("*/prompt.md")):
        front, body = _front(prompt)
        graders = []
        for file in sorted((prompt.parent / "graders").glob("*.md")):
            keys, text = _front(file)
            graders.append(
                Grader(
                    name=file.stem,
                    type=keys["type"],
                    weight=float(keys.get("weight", 1)),
                    pattern=keys.get("pattern", ""),
                    flags=keys.get("flags", ""),
                    match=str(keys.get("match", "")),
                    tool=keys.get("tool", ""),
                    input_match=keys.get("input_match", ""),
                    criteria=text,
                )
            )
        cases.append(
            Case(
                name=prompt.parent.name,
                prompt=body,
                max_turns=int(front.get("max_turns", 10)),
                allowed_tools=list(front.get("allowed_tools", [])),
                graders=graders,
            )
        )
    return cases


def grade(grader: Grader, arm: Arm, judge: Judge) -> bool:
    """Return whether one grader passes on one run."""
    if grader.type == "regex":
        flags = re.IGNORECASE if "i" in grader.flags else 0
        found = re.findall(grader.pattern, arm.text, flags)
        if grader.match == "not_contains":
            return not found
        if grader.match.startswith("count:"):
            return len(found) == int(grader.match.removeprefix("count:"))
        return bool(found)
    if grader.type == "tool_used":
        return any(
            name == grader.tool and re.search(grader.input_match or "", arguments)
            for name, arguments in arm.tools
        )
    if grader.type == "llm":
        return judge(grader.criteria, arm.prompt, arm.text)
    raise ValueError(f"grader {grader.name}: type {grader.type} is not supported")


def _with_only(grader: Grader) -> bool:
    return grader.type == "tool_used" and grader.tool == "Skill"


def case_score(graders: Sequence[Grader], passed: dict[str, bool], *, two_arms: bool) -> float:
    """Return the weighted share of passing graders; the Skill indicator is left out of two arms."""
    scored = [g for g in graders if not (two_arms and _with_only(g))] or list(graders)
    total = sum(g.weight for g in scored)
    return sum(g.weight for g in scored if passed[g.name]) / total if total else 0.0


def parse_stream(stream: str) -> Arm:
    """Return the final reply, the tool calls and the cost of a ``stream-json`` run."""
    text, tools, cost = "", [], 0.0
    for line in stream.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "assistant":
            for part in event.get("message", {}).get("content", []):
                if part.get("type") == "tool_use":
                    tools.append((part["name"], json.dumps(part.get("input", {}))))
        elif event.get("type") == "result":
            text = event.get("result", "")
            cost = float(event.get("total_cost_usd") or 0.0)
    return Arm(text, tools, cost)


def _claude(arguments: list[str], environment: dict[str, str]) -> str:
    program = shutil.which("claude")
    if program is None:
        raise SystemExit("skill_evals: the claude command is required")
    with tempfile.TemporaryDirectory() as directory:
        result = subprocess.run(  # noqa: S603  (the user's own claude CLI)
            [program, *arguments],
            capture_output=True,
            text=True,
            check=False,
            cwd=directory,
            env=environment,
            stdin=subprocess.DEVNULL,
        )
    return result.stdout


def _run(case: Case, plugin: Path | None, environment: dict[str, str]) -> Arm:
    arguments = ["-p", "--output-format", "stream-json", "--verbose", *ISOLATION]
    arguments += ["--max-turns", str(case.max_turns), "--max-budget-usd", "0.5"]
    if case.allowed_tools:
        arguments += ["--allowedTools", *case.allowed_tools]
    if plugin is not None:
        arguments += ["--plugin-dir", str(plugin)]
    arm = parse_stream(_claude([*arguments, "--", case.prompt], environment))
    return Arm(arm.text, arm.tools, arm.cost, case.prompt)


def _judge_with(environment: dict[str, str], spent: list[float], notes: list[str]) -> Judge:
    def judge(criteria: str, message: str, text: str) -> bool:
        prompt = (
            "You grade one reply against one criterion. Answer PASS or FAIL as the first "
            "word, then one sentence saying why.\n\n"
            f"Criterion:\n{criteria}\n\nThe user's message:\n{message}\n\nThe reply:\n{text}\n"
        )
        votes = 0
        for _ in range(3):
            output = _claude(
                [
                    "-p",
                    "--model",
                    "haiku",
                    "--output-format",
                    "json",
                    "--tools",
                    "",
                    *ISOLATION,
                    "--",
                    prompt,
                ],
                environment,
            )
            try:
                result = json.loads(output)
            except json.JSONDecodeError:
                continue
            spent.append(float(result.get("total_cost_usd") or 0.0))
            verdict = str(result.get("result", "")).strip()
            notes.append(verdict)
            votes += verdict.upper().startswith("PASS")
        return votes >= 2

    return judge


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m tools.skill_evals", description=__doc__)
    parser.add_argument("--plugin", type=Path, required=True, help="the plugin directory")
    parser.add_argument("--evals", type=Path, help="the eval cases (default: <plugin>/evals)")
    parser.add_argument(
        "--config-dir", type=Path, required=True, help="OPSCOUT_CONFIG for the runs"
    )
    parser.add_argument("--case", default="*", help="a glob of case names")
    parser.add_argument("--threshold", type=float, default=0.9)
    parser.add_argument("--max-cost-usd", type=float, required=True)
    parser.add_argument("--out", type=Path, help="write the result as JSON here")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the cases; exit 1 below the threshold, 2 at the cost ceiling."""
    args = _parser().parse_args(argv)
    environment = {**os.environ, "OPSCOUT_CONFIG": str(args.config_dir.resolve())}
    plugin = args.plugin.resolve()  # each run starts in an empty directory
    spent: list[float] = []
    notes: list[str] = []
    judge = _judge_with(environment, spent, notes)
    results: list[dict[str, Any]] = []
    partial = False
    for case in load_cases(args.evals or plugin / "evals"):
        if not fnmatch.fnmatch(case.name, args.case):
            continue
        if sum(spent) >= args.max_cost_usd:
            partial = True
            break
        record: dict[str, Any] = {"name": case.name}
        for label, loaded in (("with", plugin), ("without", None)):
            notes.clear()
            arm = _run(case, loaded, environment)
            spent.append(arm.cost)
            passed = {g.name: grade(g, arm, judge) for g in case.graders}
            record[label] = {
                "score": case_score(case.graders, passed, two_arms=True),
                "graders": passed,
                "reply": arm.text,
                "judge_notes": list(notes),
                "cost_usd": arm.cost,
            }
        record["delta"] = record["with"]["score"] - record["without"]["score"]
        results.append(record)
        print(
            f"{case.name}: {record['with']['score']:.2f} with the plugin, "
            f"{record['without']['score']:.2f} without (delta {record['delta']:+.2f})"
        )
    summary = {
        "cases": results,
        "partial": partial,
        "cost_usd": round(sum(spent), 6),
        "lowest_score": min((r["with"]["score"] for r in results), default=0.0),
        "mean_delta": sum(r["delta"] for r in results) / len(results) if results else 0.0,
    }
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(summary, indent=2, default=asdict), encoding="utf-8")
    print(
        f"lowest case score {summary['lowest_score']:.2f}, mean delta "
        f"{summary['mean_delta']:+.2f}, cost USD {summary['cost_usd']:.2f}"
        + (" (stopped at the cost ceiling)" if partial else "")
    )
    if partial:
        return 2
    return 0 if summary["lowest_score"] >= args.threshold else 1


if __name__ == "__main__":
    sys.exit(main())
