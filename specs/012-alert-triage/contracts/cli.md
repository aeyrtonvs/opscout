# Contract: `opscout triage` (spec 012, FR-026)

| Command | Output | Exit |
|---|---|---|
| `opscout triage runs [--limit N]` | one line per run, newest first: id, start time, format, environment, outcome, classification, agreement; `N` defaults to 20, at least 1 | 0; 2 for an invalid `--limit` |
| `opscout triage show <id>` | the record as indented JSON | 0; 1 when no run has that id |

Both read `<data>/triage/runs/`, where `<data>` is the platform data directory or
`OPSCOUT_DATA_DIR`. A run still `open` 24 hours after its start is shown as `abandoned`. A
record that cannot be read is listed as unreadable, with its file name, and never stops the
listing.

## `opscout mcp`, one new variable

`OPSCOUT_MCP_MOCK`, when set and `--mock` is not given, is the fixtures directory for mock
mode (research R12). Like `--mock`, it never falls back to AWS.
