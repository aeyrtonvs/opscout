---
status: accepted
date: 2026-11-03
decision-makers: repository maintainer
---

# Python and uv for the daemon

## Context and Problem Statement

The daemon, its CLI and its tools need one implementation language.

## Decision Outcome

Python, managed with uv. Tooling: ruff (format and lint), mypy strict, pytest.

Rationale as recorded: the industry norm for DevOps and platform work, with an official Agent
SDK and Slack Bolt (Socket Mode). The official MCP Python SDK and the cloud SDKs are in the
same ecosystem.

### Consequences

- Good, because one language covers the daemon, the CLI, the MCP server and the tests.
- Bad, because users need uv installed, and there is no single-binary distribution.

### Confirmation

CI runs on the minimum supported Python (3.13) and the latest stable release.

## More Information

Migrated unchanged from PLAN.md §3. The 3.13 floor is set in the constitution.
