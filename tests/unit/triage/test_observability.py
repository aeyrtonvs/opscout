# SPDX-License-Identifier: Apache-2.0
"""The observability stand-in and the setting (spec 012, FR-014, FR-016; research R3, R12)."""

import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import anyio
import pytest
from mcp import Client

from opscout.services.config import parse_config
from opscout.services.triage import Stores, begin
from tests.unit.triage.fakes import MemoryEvidence, MemoryRecords

REPO_ROOT = Path(__file__).resolve().parents[3]
STAND_IN = REPO_ROOT / "evals" / "triage" / "observability_server.py"
MONITOR = REPO_ROOT / "evals" / "triage" / "monitor-alert"


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 012."""
    return pytest.mark.spec("012", requirement)


def stand_in() -> ModuleType:
    loaded = importlib.util.spec_from_file_location("observability_server", STAND_IN)
    assert loaded is not None
    assert loaded.loader is not None
    module = importlib.util.module_from_spec(loaded)
    loaded.loader.exec_module(module)
    return module


@spec("FR-016")
def test_the_stand_in_answers_two_tools_from_its_fixture(tmp_path: Path) -> None:
    fixture = tmp_path / "observability.json"
    fixture.write_text(json.dumps({"traces": [{"error": "example timeout"}]}), encoding="utf-8")
    server = stand_in().build(fixture)

    async def main() -> tuple[list[str], Any]:
        async with Client(server) as client:
            names = sorted(tool.name for tool in (await client.list_tools()).tools)
            result = await client.call_tool("search_traces", {"query": "example-api"})
            return names, result

    names, result = anyio.run(main)
    assert names == ["get_metrics", "search_traces"]
    assert "example timeout" in "".join(getattr(block, "text", "") for block in result.content)


@spec("FR-014")
def test_the_eval_registers_it_under_the_fixed_name() -> None:
    config = json.loads((MONITOR / "observability.mcp.json").read_text(encoding="utf-8"))
    (name,) = config["mcpServers"]
    assert name == "observability"
    assert "observability_server.py" in " ".join(config["mcpServers"][name]["args"])


@spec("FR-016")
def test_begin_says_whether_observability_is_on() -> None:
    def settings(text: str) -> dict[str, Any]:
        config = parse_config(f"schema_version: 1\n{text}".encode(), "config.yaml")
        stores = Stores(MemoryEvidence(), MemoryRecords(), "0.0.0")
        data: dict[str, Any] = begin("x", None, config, datetime.now(UTC), stores)["settings"]
        return data

    assert settings("")["observability"] is False
    assert settings("triage:\n  observability: true\n")["observability"] is True
