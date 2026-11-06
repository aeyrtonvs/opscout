# SPDX-License-Identifier: Apache-2.0
"""The plugin starts the tool server (spec 011, FR-001, FR-029; SC-002)."""

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import anyio
import pytest
from mcp import Client, StdioServerParameters

from tests.unit.writeups.test_writeups import copy_plugin, run_launcher

REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGIN = REPO_ROOT / "plugins" / "opscout"
MCP_JSON = PLUGIN / ".mcp.json"
LAUNCHER = PLUGIN / "bin" / "opscout"


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 011."""
    return pytest.mark.spec("011", requirement)


def _definition() -> dict[str, object]:
    servers = json.loads(MCP_JSON.read_text(encoding="utf-8"))["mcpServers"]
    assert list(servers) == ["opscout"]
    server: dict[str, object] = servers["opscout"]
    return server


@spec("FR-001")
def test_the_plugin_defines_one_local_stdio_server() -> None:
    server = _definition()

    assert server["command"] == "${CLAUDE_PLUGIN_ROOT}/bin/opscout"
    assert server["args"] == ["mcp", "--config", "${user_config.config_dir}"]
    assert "env" not in server
    assert server.get("type", "stdio") == "stdio"
    assert "url" not in server
    assert "port" not in json.dumps(server)


@spec("FR-001")
def test_the_launcher_asks_for_the_aws_extra_in_both_modes(tmp_path: Path) -> None:
    source = LAUNCHER.read_text(encoding="utf-8")
    assert re.search(r'"--extra",\s*"aws"', source)
    fake = tmp_path / "fake-bin"
    fake.mkdir()
    (fake / "uvx").write_text('#!/bin/sh\nfor a in "$@"; do echo "$a"; done\n', encoding="utf-8")
    (fake / "uvx").chmod(0o755)

    result = run_launcher(
        copy_plugin(tmp_path, "1.2.3"), "mcp", path=f"{fake}{os.pathsep}{os.environ['PATH']}"
    )

    assert result.stdout.splitlines()[:4] == ["--quiet", "--from", "opscout[aws]==1.2.3", "opscout"]


@spec("FR-001")
def test_with_no_release_the_server_fails_on_stderr_without_hook_output(tmp_path: Path) -> None:
    result = run_launcher(copy_plugin(tmp_path, "0.0.0"), "mcp")

    assert result.returncode == 1
    assert result.stdout == ""
    assert "no release" in result.stderr


@spec("FR-029")
def test_the_command_in_the_definition_starts_the_server_and_lists_nine_tools() -> None:
    server = _definition()
    command = str(server["command"]).replace("${CLAUDE_PLUGIN_ROOT}", str(PLUGIN))
    parameters = StdioServerParameters(
        command=command,
        args=[str(arg) for arg in server["args"]],  # type: ignore[attr-defined]
        env={**os.environ, "OPSCOUT_CONFIG": str(REPO_ROOT / "no-such-directory")},
    )

    async def main() -> tuple[int, float]:
        start = time.monotonic()
        async with Client(parameters) as client:
            tools = (await client.list_tools()).tools
            elapsed = time.monotonic() - start
            result = await client.call_tool("list_environments", {})
            assert not result.is_error
            return len(tools), elapsed

    count, elapsed = anyio.run(main)

    assert count == 9
    assert elapsed < 2.0, f"listing took {elapsed:.2f} s from launch (SC-002)"


@spec("FR-001")
def test_an_unsubstituted_placeholder_counts_as_no_directory(tmp_path: Path) -> None:
    from opscout.core.config import Configuration
    from opscout.entrypoints.mcp import config_loader

    (tmp_path / "config.yaml").write_text("schema_version: 1\n", encoding="utf-8")
    placeholder = {"OPSCOUT_CONFIG": "${user_config.config_dir}"}

    assert isinstance(config_loader(tmp_path, placeholder)(), Configuration)
    assert config_loader(None, {"OPSCOUT_CONFIG": str(tmp_path / "missing")})() is None


@spec("FR-001")
def test_other_commands_do_not_load_the_tool_server() -> None:
    """The hooks share the CLI and must decide within a second (specs 004, 005).

    Importing the MCP SDK costs about a quarter of a second, so only ``opscout mcp`` loads
    it.
    """
    probe = (
        "import sys, opscout.entrypoints.cli;"
        "print(sorted(m for m in sys.modules if m == 'mcp' or m.startswith(('mcp.', 'boto'))))"
    )
    result = subprocess.run(  # noqa: S603  (this interpreter, a fixed probe)
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )

    assert result.stdout.strip() == "[]"
