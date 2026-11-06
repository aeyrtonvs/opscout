# Implementation Plan: Read-only tools for the investigation agents

**Branch**: `feat/011-ops-mcp-server` | **Date**: 2026-11-06 | **Spec**: [spec.md](spec.md)

## Summary

`opscout mcp` is a local MCP server over stdio, built on the official Python SDK (R1). The
plugin's `.mcp.json` starts it through the launcher (R10). It offers nine typed tools
(contracts/tools.md):

- **Without the cloud**:
  - `list_environments`;
  - `parse_alert`, against the alert formats declared in the private configuration;
  - `resolve_environment`.
- **AWS, through a gateway port**:
  - `read_alarm`, `read_metric` and `query_logs`;
  - `recent_changes`;
  - `find_resources` and `describe_resource`, for a fixed list of types (Q2).

**The gateway has two adapters**: the live one (boto3, as the `aws` extra; R2) and one that
answers from fixtures for mock mode (R5).

**The read-only surface is proved twice**:

- **In the test suite**: every action a tool declares must be in spec 010's catalog, must
  not be a write, and must be allowed by the reference read-only identity (R3).
- **At run time**: an undeclared operation is refused before it is signed.

Three operations the tools need are not in that identity yet. Spec 010's capabilities gain
them first, and `opscout identity check` keeps passing (R4).

**Every result** is a validated envelope with:

- the environment and the identity kind, which is declared and never checked (ADR-0023);
- the timezone and the window;
- what was capped (R7) and what was redacted. Spec 009's redaction is extended: account
  IDs, IP addresses and e-mail addresses are kept unless the configuration turns their
  redaction on (Q1, R6).

**Nothing blocks the server**: a missing or failing integration becomes a structured error
with its fix (R8). Each call leaves one line in a local call log, without its arguments or
output (R11).

## Technical Context

**Language/Version**: Python ≥ 3.13

**Primary Dependencies**: both are new, and this plan is their reason (AGENTS.md):

- `mcp>=2.3,<3`, a core dependency. It is the server (R1).
- `boto3>=1.43,<2`, as the `aws` optional extra. It is the live gateway (R2).

Existing: `pydantic`, `pyyaml` and `platformdirs`. botocore's `Stubber` tests the live
adapter offline.

**Storage**:

- the private configuration, read only, with three new optional sections (R9);
- fixtures in `evals/mcp/aws/` and the alert corpus in `evals/mcp/alerts/` (R5);
- the call log, `mcp-calls.jsonl` under the platform state directory (R11).

**Testing**: pytest, in three layers:

- pure core tests for parsing, resolution, windows, caps and envelopes;
- service tests for each tool against a fake gateway;
- contract tests through `mcp.Client`, connected in-process to the real `MCPServer`, plus
  one stdio test that starts the server the way `.mcp.json` does.

The surface check runs on the real registry and on planted tools. The fixture adapter is
tested with sockets blocked. The live adapter is tested with botocore's `Stubber`, for the
run-time guard, the error mapping and the retries.

**Target Platform**: macOS first, any OS the engine supports (ADR-0021). stdio only.

**Project Type**: CLI and library (the engine), plus the plugin's server definition.

**Performance Goals**:

- tools listed in under 2 seconds after start, because boto3 is imported lazily (SC-002);
- every tool returns within 60 seconds (SC-003, R7).

**Constraints**:

- read only;
- no network port;
- fake values only (Principle I). Tests that need a second environment use one more fake
  account ID, added to `tools/leak_allowlist.toml` with its reason;
- results of at most 40,000 characters;
- the configuration may lower caps, never raise them.

**Scale/Scope**: 9 tools, 27 declared AWS actions across 10 services, 9 resource types,
and 3 configuration sections.

## Constitution Check

Constitution 2.0.0.

| Principle | Check | Result |
|---|---|---|
| I. Public engine, private data | Fixtures, examples and tests use reserved values; alert formats and environments live only in the private configuration; the leak check covers `evals/mcp/` | Pass |
| II. Read-only by construction | This is the mandatory gate ADR-0023 names: the tool surface is proved, in code, to hold only reads the reference identity allows, and an undeclared call is refused at run time, whatever identity runs it. No tool writes, and the server opens no port | Pass |
| III. Secrets | No declared action can return a secret's value (the guardrail's groups are excluded through the reference identity); ECS task definitions, instance attributes and Lambda configurations are never read; every output is redacted, secrets always | Pass |
| IV. A human approves outward actions | Nothing leaves the machine except AWS read calls the user's own identity makes; no message, no ticket | Pass |
| V. Configuration over code | Alert formats, environments, caps, timezone and redaction kinds are configuration; every section is optional, and a missing one blocks nothing (V, ADR-0023) | Pass |
| VI. Deterministic gathering | Parsing, resolution and gathering are typed code; the model only chooses which tool to call | Pass |
| VII. Specified, tested, evaluated | Tests first; every FR traced; no agent behavior here, so the eval suite belongs to alert triage, which reuses `evals/mcp/` | Pass |
| VIII. Ports and adapters | `AwsGateway` and `CallLog` are ports in the core, each with two adapters and contract tests; alert triage is the first user | Pass |
| IX. Observable runs | Each tool call leaves a local line: time, tool, environment, outcome, duration and redaction counts, never arguments or output (R11) | Pass |
| X. Standards; simplicity | MCP through its official SDK; AWS through its SDK; no custom protocol; one fixture format | Pass |

Post-design re-check: unchanged. Spec 010's capabilities change (R4) under spec 010's own
check, which keeps Principle II's proof whole. Its documentation table and counts are
updated in the same pull request.

## Project Structure

### Documentation (this feature)

```text
specs/011-ops-mcp-server/
├── spec.md
├── plan.md            # this file
├── research.md        # R1–R12
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── tools.md       # the nine tools, their inputs, data and declared actions
│   └── config.md      # the three configuration sections
├── checklists/requirements.md
└── tasks.md           # /speckit-tasks
```

### Source Code (repository root)

```text
src/opscout/
├── core/
│   ├── config.py          # + AlertFormat, Alerts, Environment, Aws, Tools (R9)
│   ├── tools.py           # ToolSpec, Registry, Window, Caps, Envelope, ToolError (new)
│   ├── alerts.py          # parse and resolve, pure (new)
│   └── aws.py             # Environment helpers, ResourceRef, AwsGateway and CallLog ports,
│                          # the service-to-IAM table (new)
├── services/
│   ├── redact.py          # + keep kinds, structured redaction (R6)
│   ├── surface.py         # prove_surface(registry, records) (new, R3)
│   └── tools/             # one module per tool family (new)
│       ├── registry.py    # the nine ToolSpecs and their handlers
│       ├── envelope.py    # caps, redaction and time formatting applied to every result
│       ├── alarms.py      # read_alarm, read_metric
│       ├── logs.py        # query_logs
│       ├── changes.py     # recent_changes
│       └── resources.py   # find_resources, describe_resource
├── adapters/
│   ├── aws_live.py        # boto3 gateway: run-time guard, errors, retries (new)
│   ├── aws_fixtures.py    # fixture gateway (new)
│   └── call_log.py        # JSONL call log (new)
├── data/identity/         # capabilities.json, changes.json, + inventory.json (R4)
└── entrypoints/
    ├── mcp.py             # composition root: MCPServer, tool wiring (new)
    └── cli.py             # + `opscout mcp [--mock DIR]`

plugins/opscout/
├── .mcp.json              # new (R10)
└── bin/opscout            # + the aws extra; mcp-safe errors (R10)

evals/mcp/                 # aws/ fixtures and alerts/ corpus, fake values (new, R5)
schemas/config.schema.json # regenerated
example-config/config.yaml # + the three sections, fake values
docs/reference/
├── tools.md               # new: the tools, mock mode, configuration, errors
└── identity.md            # capabilities table and counts
tests/unit/mcp/            # new
tests/support/list_tools.py
```

**Structure Decision**: the existing single package, in its four layers (ADR-0011). New
core modules hold only types and pure logic; boto3 is imported only by
`adapters/aws_live.py`. The import contracts gain one rule: only `adapters` imports `boto3` and
`botocore`, and only `entrypoints` imports `mcp`.

## Complexity Tracking

| Item | Why needed | Simpler alternative rejected because |
|---|---|---|
| Two new dependencies, one of them with an unused web stack | The protocol has two negotiation eras, and AWS's single sign-on credentials need botocore (R1, R2) | A hand-written MCP loop has to follow both eras; shelling out to the `aws` CLI cannot refuse an operation before it runs |
| A run-time guard on top of the surface test | The test proves declarations; the guard proves the code calls only what it declares (FR-007) | Code review alone would let a forgotten call reach AWS under a broad identity |
| A change to spec 010's capabilities | Three needed reads are outside the reference identity (R4) | Calling them through the user's own identity would break FR-006, the gate this spec exists for |
