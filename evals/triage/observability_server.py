# SPDX-License-Identifier: Apache-2.0
"""A local stand-in for an observability platform's read-only MCP server (spec 012, R12).

The alert-triage evals register it under the name ``observability``, as a user would
register their platform's official server. It answers two tools from a JSON fixture,
``{"metrics": ..., "traces": ...}``, and never reaches the network.

    python evals/triage/observability_server.py <fixture.json>
"""

import json
import sys
from pathlib import Path
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import Field


def build(fixture: Path) -> MCPServer:
    """The stand-in server, answering from ``fixture``."""
    answers: dict[str, Any] = json.loads(fixture.read_text(encoding="utf-8"))
    server = MCPServer("observability", instructions="Read-only observability stand-in.")

    def get_metrics(
        query: Annotated[str, Field(description="A metric query, such as a service name.")],
    ) -> str:
        """Return a service's metrics over the last hours."""
        return json.dumps({"query": query, "series": answers.get("metrics", [])})

    def search_traces(
        query: Annotated[str, Field(description="A service, resource or error to search for.")],
    ) -> str:
        """Return the traces that match the query, with their errors."""
        return json.dumps({"query": query, "traces": answers.get("traces", [])})

    server.add_tool(get_metrics, name="get_metrics", description="Query metrics.")
    server.add_tool(search_traces, name="search_traces", description="Search traces.")
    return server


if __name__ == "__main__":
    build(Path(sys.argv[1])).run("stdio")
