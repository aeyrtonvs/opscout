# Alert triage reference

Paste an alert into Claude Code with the opscout plugin, and ask "is this real?" or
"triage this". The `alert-triage` skill (spec 012) answers three questions:

- **Is it real?** It answers real, false positive or inconclusive.
- **What caused it?**
- **Should the threshold be kept or tuned?**

Every claim in the answer cites evidence that opscout's read-only tools returned in the same
run, and opscout checks each citation in code before you see the verdict. Then you get a
draft ticket to paste, and one question: do you agree?

Triage reads; it never changes anything. It never files the ticket, never sends a message,
never applies a threshold it proposes, and never shows a secret's value.

## What happens

1. **Begin.** `begin_triage` does the following in code:
   - parses the alert against your configured formats;
   - finds its environment;
   - sets the time windows around the alert's time: the alert's own time, else a time you
     name, else now;
   - opens a local record.

   An alert from an environment you did not configure is answered "fired, out of scope",
   with no cloud read. When the alert names no environment, triage asks you once.
2. **Gather.** Four subagents start together, each with its own short list of read-only
   tools and no shell:

   | Subagent | Reads |
   |---|---|
   | `triage-metrics` | the alarm, the metric around the alert, 7 days of history (`Maximum` per hour) |
   | `triage-logs` | the resource's log groups: errors over time and the most frequent messages |
   | `triage-changes` | changes to the resource in the 24 hours before the alert; with no resource, every change except agent heartbeats |
   | `triage-config` | the deployed configuration, and what your infrastructure code declares, when you configured clones |

3. **Synthesize.** The skill writes the verdict from the four findings only (its schema is
   in the skill's `references/verdict.md`).
4. **Check.** `check_verdict` verifies, in code:
   - every cited evidence id came from this run;
   - every quoted value is in that result: a value, or a `"key": value` fragment as the
     result shows it;
   - a classification, a cause and a threshold assessment each rest on checked evidence;
   - the environment matches;
   - no text holds a secret-shaped value.

   A failing verdict gets one retry with the failures and a hint for each. A second failure
   ends the run as inconclusive, and you see what failed.
5. **Skeptic** (off by default): another subagent tries to refute the verdict from its own
   evidence; a revision is checked again.
6. **Show.** You get the verdict, every time absolute with its offset, and the timezone. Then
   the draft in your `ticket` write-up format (spec 003), marked "Draft only, not filed".
7. **Agreement.** Agree or Disagree, with an optional reason, stored in the record. If the
   question cannot be asked, as in a headless run, the record says `not-answered`.

## Setup

Triage needs the tool server's `alerts` and `aws` sections (see [tools.md](tools.md)); with
no `aws`, it says so and returns an inconclusive verdict. Everything below is optional:

```yaml
triage:
  infrastructure:
    - name: example-infra                   # how citations name the clone
      path: /Users/example/src/example-infra
      environments: [example-prod]          # absent: every environment
  observability: true                       # see below
  skeptic: false
  metric_history_days: 7
  background_actions: [ExampleAgentHeartbeat]
```

The keys are in [configuration.md](configuration.md#triage-optional-spec-012).

### Infrastructure code

`search_iac` and `read_iac` read only inside the clones you list, with these limits:

- a path that leaves its clone once resolved, symbolic links included, is refused;
- `.git/`, `.terraform/`, `.terragrunt-cache/` and `node_modules/` are never read, nor
  state files (`*.tfstate*`), `.env*` files, `*.pem` and `*.key` files, or binary files;
- a search returns at most 50 lines, and a read at most 200 numbered lines;
- every result is redacted like any other.

### The observability platform

If you use a platform with an official read-only MCP server, register it in Claude Code
under the name **`observability`** (for example `claude mcp add observability …`) and set
`triage.observability: true`. Only the metrics and logs subagents may call it.

Why a fixed name: a plugin's subagent can only list the tools of a server whose name is
known when the plugin is written.

opscout cannot check what that server returns. Every claim that cites it is shown
"(not checked)", and such a claim can never be the only support for a classification, a
cause or a threshold assessment. You are responsible for that server being read-only.

## Records

Each triage leaves one record at `<data>/triage/runs/<run-id>.json`. `<data>` is
`OPSCOUT_DATA_DIR`, or the platform data directory, the same as spec 007's runs. A record
holds:

- the alert's format, environment and resource, and the SHA-256 of its text, never the text;
- the tools called;
- the verdict;
- the check's attempts and failures;
- the duration;
- whether the skeptic ran;
- your agreement.

An interactive session does not expose its cost, so `cost_usd` is null.

```sh
opscout triage runs [--limit N]   # newest first; an open run older than 24 hours shows as abandoned
opscout triage show <run-id>      # one record as JSON
```

The tool results that citations are checked against are kept for 24 hours under
`<data>/triage/evidence/`, redacted as the model saw them, then deleted.

## Evaluations

The skill's cases are in `plugins/opscout/evals/012-*`. They run in mock mode:

- **AWS** answers from `evals/triage/<scenario>/aws/`, layered over `evals/mcp/aws/`;
- **the observability platform** answers from a local stand-in,
  `evals/triage/observability_server.py`.

```sh
uv run python -m tools.skill_evals --plugin plugins/opscout \
  --config-dir plugins/opscout/evals/eval-config --case '012-*' \
  --max-cost-usd 15 --max-run-usd 2
```

Useful options:

- `--config-override 'triage: {skeptic: true}'` runs the same cases with the skeptic pass;
- `--keep-data DIR` keeps each run's evidence and record, to read why a check failed;
- `--evals DIR --fixtures DIR` runs your private cases built on real alerts, which never
  leave your private repository (FR-028).

## What remains your call

The skill removes the shell and the write tools from its own turn, and its subagents have no
shell. Other MCP servers you have stay visible to the skill's own turn, under your
permission prompts, because a skill cannot hide every other server. The skill's turn reads
the subagents' findings, not raw tool output. A future unattended triage must start Claude
Code with only opscout's tools (research R4).
