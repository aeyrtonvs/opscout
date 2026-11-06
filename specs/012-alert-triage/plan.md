# Implementation Plan: Alert triage

**Branch**: `feat/012-alert-triage` | **Date**: 2026-11-06 | **Spec**: [spec.md](spec.md)

## Summary

`alert-triage` is a plugin skill with five plugin subagents. It runs a fixed procedure
(contracts/skill.md) over spec 011's read-only tools and six new tools on the same server,
none of which declares an AWS action.

**The new tools** (contracts/tools.md):

- **Run tools**: `begin_triage` opens a run: it parses, resolves, computes the windows and
  returns the ticket format. `check_verdict` validates the verdict and checks every
  citation. `record_agreement` stores the user's answer.
- **Read tools**: `show_evidence` returns stored results to the skeptic. `search_iac` and
  `read_iac` read infrastructure code confined to the configured clones (R6).

**How a verdict is checked**:

- Every tool result now carries an evidence identifier.
- The redacted result is kept for 24 hours in a local evidence store (R2).
- `check_verdict` verifies each quote against it in code (R5) and bounds the retries (R9).

**Two outward boundaries**:

- **The subagents' allow-lists**: no shell, no write, no generic file read (R4).
- **The observability platform**: reached only under the fixed server name `observability`,
  and marked not checked (R3).

Each triage leaves a local record, read with `opscout triage runs | show` (R8).
`recent_changes` drops agent heartbeats by default (R7). The evals run in mock mode, one
fixture tree per scenario (R12), and the skeptic pass ships only under FR-029's rule (R13).

## Technical Context

**Language/Version**: Python ≥ 3.13; Markdown for the skill and its agents.

**Primary Dependencies**: no new dependency. The work uses the existing `mcp`, `pydantic`,
`platformdirs` and `pyyaml`, and spec 003's write-up formats.

**Storage**:

- the private configuration, with one new optional section, `triage`;
- the evidence store under `<data>/triage/evidence/`, expiring after 24 hours;
- the triage records under `<data>/triage/runs/`.

`<data>` is spec 007's data directory, or `OPSCOUT_DATA_DIR`.

**Testing**: pytest, in four layers:

- **Core**: pure tests of the verdict model and `check`.
- **Services**: begin, check with its attempts, agreement, the infrastructure-code
  confinement, and the background filter, against memory stores.
- **Adapters**: the file stores, on a temporary directory.
- **Contract**: tests through `mcp.Client` against the real server, and CLI tests.

The surface check runs on the larger registry. The skill is tested by its eval suite
(ADR-0013, R12).

**Target Platform**: macOS first, any OS the engine supports (ADR-0021).

**Project Type**: CLI and library (the engine), plus the plugin's skill and agents.

**Performance Goals**: a mock-mode triage within 5 minutes in at least 90 % of cases
(SC-005). Every new tool answers in under 1 second locally.

**Constraints**:

- read only;
- fake values only;
- no shell in the skill's turn or the subagents';
- the verdict and the record hold no secret value;
- the skill is under 500 lines.

**Scale/Scope**: 6 new tools, 1 changed tool, 1 skill, 5 subagents, 1 configuration
section, 2 CLI commands, and about 20 eval cases.

## Constitution Check

Constitution 2.0.0.

| Principle | Check | Result |
|---|---|---|
| I. Public engine, private data | Fixtures and eval cases use reserved values; real alert samples are evaluated from the private repository (FR-028); records stay local and hold the alert's digest, not its text | Pass |
| II. Read-only by construction | The new tools declare no AWS action and the surface check covers them. Infrastructure-code reads are confined in code (R6). The subagents' allow-lists hold no shell or write, and the skill removes Bash and the write tools from its own turn (R4). The only files written are local evidence and run records | Pass, with the residual risk in R4 stated |
| III. Secrets | Evidence is stored after the always-on redaction. The check refuses a verdict holding a secret-shaped value. `read_iac` skips state files, `.env*` and key files. No new tool reads a secret | Pass |
| IV. A human approves outward actions | The draft is never filed; nothing is sent anywhere | Pass |
| V. Configuration over code | Clones, observability, the skeptic, the history and background actions are configuration. Each integration is optional: with no clone, no observability or no AWS, triage still answers | Pass |
| VI. Deterministic gathering, model judgment | Parsing, resolution, windows, the confinement, the background filter, the citation check and the retry bound are code. The model chooses the queries and judges. The verdict is schema-validated, and convergence is bounded by the server (R9) | Pass |
| VII. Specified, tested, evaluated | Tests first; every FR traced to a test or an eval case; the suite's baseline is recorded | Pass |
| VIII. Ports and adapters | `EvidenceStore`, `TriageStore` and `FileReader` are core ports with file and memory adapters. The only user of each is this feature | Pass |
| IX. Observable runs | Each triage leaves a record with its verdict, check, tools, duration and agreement; the cost is not exposed in an interactive session and is recorded as null | Pass, with the cost gap stated |
| X. Standards; simplicity | Claude Code's own skill and agent formats and MCP; no new dependency; the skeptic is a configuration switch, not a variant | Pass |

Post-design re-check: unchanged. Two decisions refine the spec's clarifications (R3, R6),
and the spec is updated in this pull request. Spec 011's contract gains `evidence` and
`include_background` (R7, R15), and is updated too.

## Project Structure

### Documentation (this feature)

```text
specs/012-alert-triage/
├── spec.md
├── plan.md             # this file
├── research.md         # R1–R15
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── tools.md        # the six new tools, evidence, include_background
│   ├── verdict.md      # the verdict and the check's rules
│   ├── skill.md        # the procedure, the subagents and their findings
│   ├── config.md       # the triage section
│   └── cli.md          # opscout triage runs | show; OPSCOUT_MCP_MOCK
├── checklists/requirements.md
└── tasks.md            # /speckit-tasks
```

### Source Code (repository root)

```text
src/opscout/
├── core/
│   ├── config.py          # + InfrastructureClone, Triage
│   └── triage.py          # Verdict, citations, check(), TriageRecord, ports (new)
├── services/
│   ├── triage.py          # begin, check_verdict, record_agreement, render (new)
│   ├── iac.py             # search_iac, read_iac: confinement and skip rules (new)
│   └── tools/
│       ├── registry.py    # + six ToolSpecs and handlers
│       ├── runtime.py     # + evidence on every result
│       ├── changes.py     # + include_background
│       └── triage.py      # the six handlers (new)
├── adapters/
│   ├── evidence_files.py  # EvidenceStore on files (new)
│   ├── triage_files.py    # TriageStore on files (new)
│   └── local_files.py     # FileReader (new)
└── entrypoints/
    ├── mcp.py             # + six tools; OPSCOUT_MCP_MOCK; OPSCOUT_DATA_DIR
    ├── triage.py          # opscout triage runs | show (new)
    └── cli.py             # + the triage commands

plugins/opscout/
├── skills/alert-triage/SKILL.md (+ references/verdict.md)
├── agents/triage-{metrics,logs,changes,config,skeptic}.md
└── evals/012-*/           # cases named after the scenarios

evals/triage/              # per-scenario configuration, aws fixtures, infra trees, the
                           # observability stand-in, skeptic-on configuration (new)
tools/skill_evals.py       # + mock, mcp_config, arms; OPSCOUT_DATA_DIR per run; record grader
schemas/config.schema.json # regenerated
example-config/config.yaml # + triage, fake values
docs/reference/
├── triage.md              # new: the skill, setup, records, observability, residual risk
└── tools.md               # + the six tools, evidence, include_background
tests/unit/triage/         # new
```

**Structure Decision**: the existing four layers (ADR-0011). `check()` takes a secret
detector as a parameter, so `core` does not import `services.redact`. The new tools live in
the same server, so the surface check and the call log cover them. No new import contract
is needed: the existing ones already forbid `mcp` and `boto3` outside their layers.

## Complexity Tracking

| Item | Why needed | Simpler alternative rejected because |
|---|---|---|
| An evidence store on disk | A subagent's MCP calls may reach another server process; the documentation does not say (R2) | Memory alone could fail every citation silently |
| Two confined infrastructure-code tools | A plugin agent cannot restrict `Read` to a directory (R4, R6) | `Read` would let a prompt-injected subagent read any file on the machine |
| A fixed observability server name | Plugin agents cannot name a server chosen at install time (R3) | Inheriting every tool would include the user's servers that write |
