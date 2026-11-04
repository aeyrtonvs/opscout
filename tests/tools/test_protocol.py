# SPDX-License-Identifier: Apache-2.0
"""The hook protocol reads the event as UTF-8, whatever the locale says (ADR-0021)."""

import io
import json
import sys

import pytest

from tools.hooks._protocol import Event, run_hook


def test_the_event_is_read_as_utf8_and_the_decision_is_written_as_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    raw = json.dumps({"tool_input": {"command": "echo café"}}, ensure_ascii=False).encode()
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(raw), encoding="latin-1"))
    seen: list[Event] = []

    def decide(event: Event) -> dict[str, bool]:
        seen.append(event)
        return {"ok": True}

    assert run_hook(decide) == 0
    assert seen == [{"tool_input": {"command": "echo café"}}]
    assert json.loads(capsys.readouterr().out) == {"ok": True}
