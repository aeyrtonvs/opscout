# SPDX-License-Identifier: Apache-2.0
"""After each Python edit, ruff fixes and formats the file and reports the rest (ADR-0018)."""

from collections.abc import Sequence
from pathlib import Path

from tools.hooks._protocol import Result
from tools.hooks.ruff_after_edit import decide, run_ruff


class FakeRuff:
    """Records each ruff call and answers the last check with ``remaining``."""

    def __init__(self, remaining: Result) -> None:
        self.calls: list[list[str]] = []
        self.remaining = remaining

    def __call__(self, arguments: Sequence[str]) -> Result:
        self.calls.append(list(arguments))
        return self.remaining if len(self.calls) == 3 else Result(0, "")


def edit_event(path: Path) -> dict[str, object]:
    return {"tool_name": "Edit", "tool_input": {"file_path": str(path)}}


def test_fixes_come_before_formatting_and_the_last_check(tmp_path: Path) -> None:
    module = tmp_path / "module.py"
    module.write_text("x = 1\n", encoding="utf-8")
    ruff = FakeRuff(remaining=Result(0, "All checks passed!"))

    assert decide(edit_event(module), tmp_path, ruff) is None
    assert [call[:2] for call in ruff.calls] == [
        ["check", "--fix"],
        ["format", "--force-exclude"],
        ["check", "--force-exclude"],
    ]


def test_an_import_added_before_its_first_use_survives(tmp_path: Path) -> None:
    module = tmp_path / "module.py"
    module.write_text("import os\n", encoding="utf-8")

    decision = decide(edit_event(module), tmp_path, lambda args: run_ruff(args, tmp_path))

    assert decision is None
    assert module.read_text(encoding="utf-8") == "import os\n"


def test_what_ruff_cannot_fix_is_reported_to_the_agent(tmp_path: Path) -> None:
    module = tmp_path / "module.py"
    module.write_text("print(undefined)\n", encoding="utf-8")
    ruff = FakeRuff(remaining=Result(1, "module.py:1:7: F821 Undefined name `undefined`"))

    decision = decide(edit_event(module), tmp_path, ruff)

    assert decision is not None
    assert decision["decision"] == "block"
    assert "F821" in decision["reason"]


def test_other_files_are_left_alone(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    readme = project / "README.md"
    readme.write_text("# Title\n", encoding="utf-8")
    outside = tmp_path / "outside.py"
    outside.write_text("x = 1\n", encoding="utf-8")
    ruff = FakeRuff(remaining=Result(1, "unexpected"))

    assert decide(edit_event(readme), project, ruff) is None
    assert decide(edit_event(outside), project, ruff) is None
    assert decide(edit_event(project / "missing.py"), project, ruff) is None
    assert ruff.calls == []


def test_the_real_ruff_formats_the_file_and_reports_what_is_left(tmp_path: Path) -> None:
    module = tmp_path / "module.py"
    module.write_text("x=1\nprint(undefined)\n", encoding="utf-8")

    decision = decide(edit_event(module), tmp_path, lambda args: run_ruff(args, tmp_path))

    assert module.read_text(encoding="utf-8") == "x = 1\nprint(undefined)\n"
    assert decision is not None
    assert "F821" in decision["reason"]
