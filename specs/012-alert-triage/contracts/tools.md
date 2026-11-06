# Contract: the triage tools and the changes to spec 011's tools (spec 012)

All the tools below run on the `opscout` server (spec 011) and declare no AWS action, so
the surface check covers them as it is. They return spec 011's envelope, and every envelope
now carries `evidence` (R2).

## Every result: `evidence`

| Field | Type | Meaning |
|---|---|---|
| `evidence` | string, `^ev-[0-9a-f]{10}$` | the identifier of this result in the evidence store; a citation names it |

The stored copy is the rendered result, after redaction and caps, with the tool's name and
the time it was stored.

## `recent_changes`, one new input

| Input | Type | Default | Effect |
|---|---|---|---|
| `include_background` | boolean | false | when false, CloudTrail events whose action is in the built-in background list or in `triage.background_actions` are dropped |

`data` gains `background_dropped`, the number of events dropped. The built-in list:
`UpdateInstanceInformation`, `PutInventory`, `PutComplianceItems`,
`UpdateInstanceAssociationStatus`, `ListInstanceAssociations`, `PutConfigurationAggregator`.

## `begin_triage`

| Input | Type |
|---|---|
| `text` | the alert's text, at most 20,000 characters |
| `alert_time` | optional, ISO 8601 with an offset: the time the user named |

`data`:

| Field | Meaning |
|---|---|
| `run_id` | the run's identifier |
| `started_at` | when the run began |
| `alert` | `parse_alert`'s data: the format and fields, or `{"matched": false}` |
| `resolution` | `resolve_environment`'s data: the environment, `out-of-scope`, `ambiguous` or `unknown` |
| `alert_time` | `{time, source}`, where source is `alert`, `user` or `invocation` |
| `windows` | suggested `since` and `until` for the alert's window (one hour before, 30 minutes after) and the history window |
| `settings` | `metric_history_days`, `history_period` (3,600), `skeptic`, `observability`, `infrastructure` (the clone names that serve the environment) |
| `ticket_format` | the resolved `ticket` write-up format: name, sections, limit, rules, language |

It writes the run record as `open` (R8). With no `alerts` section, `alert` is
`{"matched": false}` and the reason is stated; no error.

## `search_iac`

| Input | Type |
|---|---|
| `pattern` | a literal, 2 to 200 characters, matched case-insensitively |
| `environment` | optional; the clones serving it come first |
| `clone` | optional; one clone by name |

`data`: `matches` `[{clone, path, line, text}]`, at most 50; `searched` (the clone names);
`missing` (clone names whose path does not exist). With no clone configured: the
`not-configured` error.

## `read_iac`

| Input | Type |
|---|---|
| `path` | `<clone>/<relative path>` |
| `start` | the first line, from 1 |
| `end` | the last line, at most `start + 199` |

`data`: `clone`, `path`, `lines` `[{line, text}]`. Refused with `invalid-input`: a path
outside the clone once resolved (symbolic links included), a skipped file (`.git/`,
`.terraform/`, `*.tfstate*`, `.env*`, `*.pem`, `*.key`), a binary file.

## `show_evidence`

| Input | Type |
|---|---|
| `ids` | one to 20 evidence identifiers |

`data`: `items` `[{id, tool, stored_at, result}]`; an identifier not found is listed in
`missing`. It stores no new evidence.

## `check_verdict`

| Input | Type |
|---|---|
| `run_id` | the run's identifier |
| `verdict` | the verdict (contracts/verdict.md) |

`data`:

| Field | Meaning |
|---|---|
| `passed` | whether this verdict passed |
| `failures` | `[{where, reason}]`: `where` is a JSON path in the verdict, such as `claims[2].cites[0]` |
| `retry` | true when one more attempt is allowed |
| `final` | true when the run is closed |
| `outcome` | `checked`, `inconclusive` or `open` |
| `verdict` | the verdict the run holds now, which is the one to show |

The attempts follow research R9. A call for an unknown run, or for a closed run beyond its
one revision, returns `invalid-input`.

## `record_agreement`

| Input | Type |
|---|---|
| `run_id` | the run's identifier |
| `answer` | `agree`, `disagree` or `not-answered` |
| `reason` | optional, at most 500 characters, redacted like any text |

`data`: `{run_id, agreement}`. It refuses an `open` run. A second call replaces the answer.
