# Research: Alert triage (spec 012)

The maintainer asked for every planning decision to be made without asking (2026-11-06).
Each one is recorded here with its reason and the alternatives considered.

## R1. Where the citation check runs: in opscout's own tool server

**Decision**: three new tools on the `opscout mcp` server, which declare no AWS action:

- `begin_triage`: parses and resolves the alert, opens the run, and returns its settings;
- `check_verdict`: validates the verdict and checks every citation;
- `record_agreement`: stores the user's answer.

The skill calls them in its fixed order. The server already sees every tool result it
produced (R2), so the check needs nothing from the model but the verdict.

**Rationale**: Principle VI asks the harness to check each citation in code. The server
produced the evidence, so it can check it without trusting a copy the model passes back.
A tool call is also typed, validated and logged like the other tools.

**Alternatives**:

- **A CLI command through Bash** (`opscout triage check`): the skill would need a shell,
  which FR-005 removes from the subagents and R4 removes from the skill's own turn. A
  verdict passed as a shell argument is also fragile.
- **A `SubagentStop` or `Stop` hook**: hooks see the transcript, not the tool results in a
  checkable form. Plugin agents cannot declare hooks either (R4).

## R2. Evidence identifiers and the evidence store

**Decision**: every opscout tool result, success or error, gains an `evidence` field holding
an identifier, `ev-` plus 10 random hexadecimal characters. The rendered, already-redacted
result is stored at `<data>/triage/evidence/<id>.json`, with the tool's name and its time.

- `<data>` is the platform data directory of spec 007, overridable with `OPSCOUT_DATA_DIR`
  for tests and evals.
- Files older than 24 hours are deleted when the server starts and when a triage begins.
- **"In this run"** means stored by this machine's server between the run's
  `begin_triage` and its `check_verdict`.

**Rationale**:

- Claude Code's documentation does not say whether a subagent's MCP calls reach the same
  server process as its parent's. A store on disk works either way.
- The stored result is the redacted one the model saw, so no secret value is written
  (Principle III).
- 24 hours bounds what accumulates; the run record keeps only what it needs (R8).

**Alternatives**:

- **Memory only**: breaks if a subagent's calls reach another process.
- **Hashing results instead of storing them**: a quote could not be checked against a hash.
- **No expiry**: grows without bound; PLAN.md §9 already tracks retention for spec 007.

## R3. The observability platform: a fixed server name

**Decision**: the metrics and logs subagents list `mcp__observability__*` among their tools.
The user registers their platform's official read-only server in Claude Code under the name
`observability`, and sets `triage.observability: true`. Without that setting, the skill tells
the subagents not to try it. A claim citing it carries `{"observability": "<tool>",
"quote": ...}`, which the check marks as "not checked" (FR-016, FR-018).

**Rationale**, from the Claude Code documentation (sub-agents, plugin components and skills
pages, read on 2026-11-06):

- A plugin subagent's `tools:` allow-list may name a server's tools with `mcp__<server>__*`.
- No mechanism lets a subagent's frontmatter name a server chosen at install time, and plugin
  agents ignore `mcpServers`, `hooks` and `permissionMode`.

A fixed name is the only allow-list that works. This refines the spec's first clarification,
whose answer had the configuration name the server and its tools.

**Alternatives**:

- **Omit `tools:` and use `disallowedTools`**: the subagent would inherit every other server
  the user has, including ones that write.
- **Generate a user-level agent file from the configuration**: it writes outside the repo and
  the plugin, for one setting.
- **Proxy the platform through opscout**: it reverses spec 011's non-goal and ADR-0011.

## R4. Subagents and the skill's own turn

**Decision**:

- **Five plugin agents** in `plugins/opscout/agents/`: `triage-metrics`, `triage-logs`,
  `triage-changes`, `triage-config` and `triage-skeptic`.
  - Each has a `tools:` allow-list of exact opscout tool names
    (`mcp__plugin_opscout_opscout__<tool>`), plus `mcp__observability__*` for metrics and logs.
  - None has Bash, Read, Write, Edit or a web tool.
  - The gatherers use `model: sonnet`; the skeptic too.
- **The skill** `alert-triage`:
  - `disallowed-tools: Bash, Edit, Write, NotebookEdit, WebFetch, WebSearch` removes the shell
    and the write tools from its own turn;
  - `allowed-tools` pre-approves the opscout triage tools, `Agent` and `AskUserQuestion`.
- **The four gatherers** start in one message, so they run in parallel (FR-005).

**Rationale**:

- The subagents read untrusted text (alerts, logs); an allow-list with no shell and no write
  is the mechanism that holds whatever the text says (FR-011, Principle II).
- `allowed-tools` only pre-approves; `disallowed-tools` is the field that removes tools
  (Claude Code skills page).

**Residual risk**: other MCP servers the user has stay visible to the skill's own turn, under
the user's permission prompts, because a skill cannot remove every server except one. The
main turn reads the subagents' findings, not raw tool output. A headless triage (Phase 3)
must instead start `claude -p` with `--tools`, as spec 007's runner does.

**Alternatives**:

- **One agent with every tool**: no parallelism, and a single context holding all the
  untrusted text.
- **`model: haiku` for the gatherers**: cheaper, but writing Logs Insights queries and
  choosing dimensions is where a weaker model fails. The eval suite measures it, and
  ADR-0013 makes a model change a harness event.

## R5. The verdict schema and the check's rules

**Decision**: the verdict is JSON, defined in `contracts/verdict.md` and validated by a
pydantic model. A citation is one of:

- `{"evidence": "ev-…", "quote": "…"}`, checked;
- `{"observability": "<tool>", "quote": "…"}`, not checked.

The check:

1. **Validates** the verdict against the schema.
2. **Checks every checked citation**:
   - its evidence exists in this run (R2);
   - its quote, with whitespace collapsed, is a substring of one scalar of the stored result
     rendered as text;
   - a numeric quote also matches a number equal to it, so "52" finds `52.0`;
   - a quote shorter than 3 characters must equal a whole scalar.
3. **Requires checked support**:
   - "real" and "false positive" need at least one checked citation among the claims;
   - the cause needs one among its own citations;
   - "tune" needs one in the threshold assessment.

   A classification or cause resting only on unchecked citations fails.
4. **Matches the environment**: the verdict's environment and identity must equal those of
   the AWS evidence it cites.
5. **Looks for secrets**: the verdict's text is run through the always-on redaction, and any
   secret-shaped value fails it (FR-021).
6. **Validates the timezones** as IANA names.

**Rationale**:

- These rules are ADR-0018's definition ("the evidence ID exists, and the quoted value
  appears in that tool's output"), made exact enough to test.
- The short-quote rule stops "5" from matching any number.
- The secret scan turns FR-021 into a gate rather than an instruction.

**Alternatives**:

- **Quotes compared against the whole JSON text**: field names and punctuation would match.
- **An LLM judge of support**: not code, and not deterministic.

## R6. Infrastructure code through confined tools

**Decision**: two new tools, which declare no AWS action:

- `search_iac(pattern, environment?)`: a literal, case-insensitive search;
- `read_iac(path, start, end)`: a slice of at most 200 lines.

**Confinement**:

- Both read only under `triage.infrastructure` clones; the clones that serve the
  environment come first.
- A path is relative to a named clone (`<clone>/<path>`), resolved, and refused if it leaves
  the clone, symbolic links included.
- They skip `.git/`, `.terraform/`, state files (`*.tfstate*`), `.env*`, `*.pem`, `*.key` and
  binary files.
- Results are capped at 50 matches or 200 lines, and redacted like every result.

**Evidence**: every line carries its path and number, so a file citation is an evidence
citation checked like the others (FR-018).

**Rationale**:

- A subagent with Claude Code's `Read` could read any file on the machine.
- Confinement in code holds whatever the text says.
- It also gives file reads evidence identifiers, so one check covers everything.

**Alternatives**:

- **`Read` and `Grep` with permission rules**: a plugin agent cannot carry permission rules
  (R4).
- **Re-reading the file at check time**: the file may change between read and check, and the
  model saw the read.

## R7. Background changes

**Decision**:

- `recent_changes` gains `include_background` (default false). When false, it drops CloudTrail
  events whose action is in a built-in list of agent heartbeats (`UpdateInstanceInformation`,
  `PutInventory`, `PutComplianceItems`, `UpdateInstanceAssociationStatus`,
  `ListInstanceAssociations`, `PutConfigurationAggregator`) or in
  `triage.background_actions`.
- The result counts what it dropped (`background_dropped`).
- The changes subagent asks for the resource when it is known and says which it did
  (FR-009).

**Rationale**: spec 011's live run found heartbeats filling the change cap. Dropping them by
default helps every caller, and the count keeps it visible. This changes specified behavior,
so spec 011's contract is updated in this pull request.

**Alternatives**: filtering in the subagent's prompt, which is not deterministic and would
still spend the cap.

## R8. The triage record

**Decision**:

- **Where**: one JSON file per run at `<data>/triage/runs/<run-id>.json`, written atomically
  like spec 007's records. `run-id` is `<UTC timestamp>-<6 hex>`.
- **Who writes it**: `begin_triage` writes it as `open`. `check_verdict` completes it with
  the verdict, the check and the duration, as `checked` or `inconclusive`.
  `record_agreement` adds the agreement. A record never completed shows `abandoned` after
  24 hours.
- **What it holds**:
  - the alert's format, environment and resource, and the SHA-256 of its text (never the
    text);
  - the tools called, from the evidence store, and the observability tools cited;
  - the check's attempts and failures; whether the skeptic ran and disagreed;
  - the engine version; the agreement.
  - The cost is `null`: an interactive session does not expose it to the skill.
- **Reading it**: `opscout triage runs [--limit N]` and `opscout triage show <id>`.

**Rationale**: FR-025 and FR-026, and Principle IX. Run-insights reads these files later.

**Alternatives**: reusing spec 007's `RunRecord`, which is keyed by job and period and
carries delivery fields a triage does not have.

## R9. The retry bound, enforced by the server

**Decision**: `check_verdict` counts the attempts per run.

| Attempt | Result |
|---|---|
| First failure | The failures, with `retry: true` |
| Second failure | Closes the run as `inconclusive`, with `final: true` and the failures |
| A pass | Closes the run as `checked` |
| One revision after a pass (the skeptic, R13) | Replaces the verdict if it passes; keeps the earlier one if it fails |
| After a final result | Refused |

**Rationale**: Principle VI's bounded convergence, enforced where the model cannot skip it.

## R10. The draft's format

**Decision**: `begin_triage` returns the resolved `ticket` write-up format, from spec 003's
`resolve_formats`, with its sections, limit and rules. The skill writes the draft from the
checked verdict in that shape.

**Rationale**: the summary skill's format without a shell call (R4); one source for formats.

## R11. Agreement

**Decision**: after the draft, the skill asks with `AskUserQuestion`, offering Agree and
Disagree; the "Other" text and the notes become the reason. It then calls
`record_agreement(run_id, answer, reason?)`. A run without an answer stays "not answered".
`record_agreement` refuses a run that is not checked or inconclusive, and a second answer
replaces the first.

## R12. Evals

**Decision**:

- **Cases**: `plugins/opscout/evals/012-…`, one or more per acceptance scenario, named after
  it (FR-027). Each case has its own configuration and fixtures under
  `evals/triage/<scenario>/`, with a `config.yaml` and an `aws/` tree in spec 011's fixture
  format.
- **`tools/skill_evals.py` gains three case keys**:
  - `mock`: a fixtures directory, passed to the server as `OPSCOUT_MCP_MOCK`;
  - `mcp_config`: an extra `--mcp-config` file, for the observability stand-in;
  - `arms: plugin`: one arm only, since without the plugin there is nothing to triage.

  Every run gets a fresh `OPSCOUT_DATA_DIR`, so evals never touch the user's records.
- **Grading**: deterministic graders read the final reply and the tool calls, and a new
  `record` grader reads the run's triage record (classification, check outcome, agreement).
  A case for a property that cannot be asserted uses an LLM grader with its rubric.
- **The observability stand-in**: `evals/triage/observability_server.py`, a small MCP stdio
  server built on the same SDK, answering two tools from a fixture.
- **Real alerts**: their cases live in the private repository, run with `--evals <dir>`
  (FR-028).

**Rationale**:

- ADR-0013: deterministic graders first; mocked tools.
- The data-directory override keeps evals out of the user's run-insights.

**Alternatives**: one shared fixture tree, which cannot hold a "real" and a "false positive"
answer for the same metric.

## R13. The skeptic pass and its ablation

**Decision**:

- **The setting**: `triage.skeptic` (default false). `begin_triage` returns it.
- **When it is on**: after the first passing check, the skill starts `triage-skeptic` with
  the verdict and its evidence identifiers. It reads them with `show_evidence` and either
  confirms or returns a revised verdict. A revised verdict goes through `check_verdict` again,
  as a second attempt. The verdict shown is the last one that passed, and the record notes
  the disagreement.
- **The ablation**: the public suite runs twice, with two evaluation configurations that
  differ only in `triage.skeptic`. FR-029's rule decides, and Actuals records both scores and
  both costs.

**Rationale**: ADR-0018 says the pass ships only with an ablation result; the setting makes
the ablation a configuration change, not a code change.

## R14. Metric history

**Decision**: `triage.metric_history_days`, 1 to 14, default 7. `begin_triage` returns it,
with a period of 3,600 s for the history: at most 336 points, under the data-points cap.
The metrics subagent reads the history in a second `read_metric` call, separate from the
alert's window at the alarm's own period.

## R15. What changes in spec 011's surface

**Decision**: the six new tools (`begin_triage`, `check_verdict`, `record_agreement`,
`show_evidence`, `search_iac`, `read_iac`) declare no AWS action, so the surface check covers
them unchanged. `recent_changes` keeps its declared actions. Every result gains `evidence`. Spec
011's contract and the tool reference change in this pull request.
