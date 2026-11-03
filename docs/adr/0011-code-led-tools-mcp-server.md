---
status: accepted
date: 2026-11-03
decision-makers: repository maintainer
---

# Deterministic adapters, exposed to agents as a local read-only MCP server and a CLI

## Context and Problem Statement

Constitution Principle VI puts parsing and data gathering in tested code. The same steps run in
interactive sessions and in headless runs, which have no shell (ADR-0010). Shell recipes inside
prompts are brittle, hard to test, and cannot be allowed or denied per operation.

## Considered Options

- Skills call vendor CLIs through the shell
- Only third-party MCP servers
- An own MCP server for project-specific tools, plus selected official read-only servers

## Decision Outcome

Chosen option: "own MCP server plus selected official read-only servers".

One Python package, `opscout`, in four layers:

- `core`: domain models and ports; no I/O.
- `services`: use cases (parse an alert, resolve the account in scope, gather the daily's
  sources).
- `adapters`: cloud, observability, code host, tickets, chat, scheduler, keychain, agent runner.
- `entrypoints`: the `opscout` CLI, the MCP server (`opscout mcp`, stdio) and the
  daemon.

Layering is enforced with import-linter contracts. Each adapter's SDK is an optional extra (for
example `opscout[aws]`). A Python entry-point group for third-party adapters is designed now
and built when a second provider needs it.

The plugin's `.mcp.json` starts the server, and skills call typed tools (for example
`parse_alert`, `resolve_account`, `cost_breakdown`) instead of free-form commands. Where an
official read-only MCP server already covers a need, it is used instead of re-implementing it.

### Consequences

- Good, because interactive and headless runs share one tested code path.
- Good, because every tool has a schema and can be allowed or denied by name.
- Good, because any MCP client can use the tools.
- Bad, because there is one more process, and the project maintains tool schemas.

### Confirmation

import-linter runs in CI; each tool has contract tests; evals run against MCP mocks.

## More Information

Open: how the plugin locates the package (`uvx` with a pinned version, or an executable in the
plugin's `bin/`). Decided in the MCP server's spec.
