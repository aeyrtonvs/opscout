# Contract: the `alert-triage` skill and its subagents (spec 012)

## The skill

- **Path**: `plugins/opscout/skills/alert-triage/SKILL.md`, under 500 lines (ADR-0018).
  Details go in `references/`.
- **Frontmatter**:
  - `name: alert-triage` and a `description` that triggers on a pasted alert or "is this
    alert real?";
  - `argument-hint: "<alert text>"`;
  - `disallowed-tools: Bash, Edit, Write, NotebookEdit, WebFetch, WebSearch`;
  - `allowed-tools`: the triage tools (`begin_triage`, `check_verdict`, `record_agreement`,
    `show_evidence`), `Agent` and `AskUserQuestion`.

### The procedure (FR-002), in this order

1. **Begin**: call `begin_triage` with the alert's text, and `alert_time` if the user named a
   time.
2. **Stop or ask**, from `begin_triage`'s result:
   - **Out of scope**: say "fired, out of scope", name the environment found, and stop. Do
     not call any other tool.
   - **No format matched**: ask once for the environment and the resource. With an answer,
     call `begin_triage` again with the alert text and the answer appended; with none, stop
     without a verdict.
   - **Ambiguous environment**: ask once which one, then begin again as above.
   - **AWS not configured**: say so with the fix, and go to step 5 with an `inconclusive`
     verdict that cites `begin_triage`'s evidence.
3. **Gather**: start `triage-metrics`, `triage-logs`, `triage-changes` and `triage-config` in
   one message. Each gets:
   - the run id;
   - the parsed alert, the environment and the windows;
   - the settings it needs: history days and period for metrics; whether `observability`
     is on for metrics and logs; the clone names for config.
4. **Synthesize** the verdict (contracts/verdict.md) from the four findings only, citing
   their evidence.
5. **Check**: call `check_verdict`.
   - On failure with `retry`: fix only the failing citations and call it once more.
   - On `final` and `inconclusive`: show the failures.
6. **Skeptic** (only when `settings.skeptic` is true and the check passed): start
   `triage-skeptic` with the verdict. If it returns a revised verdict, call `check_verdict`
   with it once, and show the verdict `check_verdict` returns.
7. **Show**:
   - the verdict, with every time absolute and with its timezone; claims citing
     observability marked "(not checked)";
   - then the draft ticket in `ticket_format`, in one fenced `text` block, followed by
     "Draft only, not filed."
8. **Agreement**: ask with `AskUserQuestion` (Agree / Disagree, the reason as the free
   text), then call `record_agreement`. If the question cannot be asked, record
   `not-answered`.

### Never

- call a tool outside this list;
- write the draft anywhere;
- run more than one alert per invocation (say so when several are pasted);
- repeat a secret's value.

## The subagents

All of them live in `plugins/opscout/agents/`. `<t>` stands for
`mcp__plugin_opscout_opscout__<t>`.

| Agent | `tools:` | Gathers |
|---|---|---|
| `triage-metrics` | `<read_alarm>`, `<read_metric>`, `<find_resources>`, `mcp__observability__*` | the alarm and its state history in the alert's window; the metric in that window at the alarm's period; the history window at `history_period`; the same metric on the platform, when observability is on |
| `triage-logs` | `<query_logs>`, `<find_resources>`, `<describe_resource>`, `mcp__observability__*` | the resource's log groups; errors and their counts in the alert's window; traces on the platform, when on |
| `triage-changes` | `<recent_changes>`, `<find_resources>` | changes to the resource in the 24 hours before the alert, or, with no resource, background-filtered changes, saying which |
| `triage-config` | `<describe_resource>`, `<find_resources>`, `<search_iac>`, `<read_iac>` | the deployed configuration; where the resource is declared, and the declared values that differ |
| `triage-skeptic` | `<show_evidence>` | tries to refute the verdict from its cited evidence; returns `confirmed` or a revised verdict |

The four gatherers use `model: sonnet` and `maxTurns: 12`. The skeptic uses `model: sonnet`
and `maxTurns: 6`.

### A gatherer's output: one finding

The last message is a single fenced `json` block:

```json
{
  "kind": "metrics",
  "status": "ok",
  "summary": "…",
  "observations": [
    {"text": "…", "cites": [{"evidence": "ev-…", "quote": "…"}]}
  ],
  "not_read": ["…"]
}
```

`status` is `ok`, `empty` or `failed` (FR-010). `observations` are at most 10. `not_read`
lists what the agent could not read, and why.
