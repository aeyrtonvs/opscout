# Data model: Daemon core

## Daemon (the `daemon` section; optional)

| Field | Type | Rule |
|---|---|---|
| `jobs` | mapping job name → JobSettings | names the engine knows (now only `check`); up to 20 |
| `claude_path` | path or absent | absolute; the Claude Code executable, else the search path |
| `secrets` | mapping secret name → `KeychainRef` (spec 002) | names the engine knows (now only `claude_token`) |

Example (`example-config/config.yaml`):

```yaml
daemon:
  jobs:
    check:
      at: "09:30"
      weekdays: [mon, tue, wed, thu, fri]
```

## JobSettings

| Field | Type | Rule |
|---|---|---|
| `enabled` | boolean | default true |
| `at` | `HH:MM` | 00:00–23:59, the machine's local time |
| `weekdays` | list of `mon`…`sun` | 1–7, unique; default every day |
| `model` | text or absent | an alias (`haiku`, `sonnet`, `opus`, `fable`) or a full id `claude-…` |
| `budget_usd` | number or absent | > 0 and ≤ 5 |
| `max_turns` | integer or absent | 1–50 |

## Job (engine-defined, `core`)

| Field | Meaning |
|---|---|
| `name` | `check` |
| `period(now)` | the local date, ISO (`2026-11-05`) |
| `profile` | the default RunProfile, overridden by JobSettings |
| `prompt` | the text sent on standard input |
| `output` | the pydantic model of the structured output |
| `render(output, facts)` | the delivered text |

## RunProfile

| Field | Type |
|---|---|
| `tools` | tuple of tool names (empty for `check`) |
| `mcp_servers` | mapping name → server definition (empty for `check`) |
| `model`, `budget_usd`, `max_turns` | as JobSettings |
| `schema` | JSON Schema of the output |
| `secrets` | mapping environment variable → secret name (`CLAUDE_CODE_OAUTH_TOKEN` → `claude_token` when configured) |

## StartupReport (parsed from `system/init`)

`tools`, `mcp_servers` (names), `model`, `permission_mode`, `plugin_paths`,
`api_key_source`, `claude_code_version`. Missing any field → the run is `refused`.

## RunResult (from the runner)

| Field | Meaning |
|---|---|
| `status` | `ok`, `refused`, `invalid_output`, `error` |
| `output` | the validated output (when `ok`) |
| `differences` | profile vs report (when `refused`) |
| `reason` | the validator's message or the CLI's error |
| `facts` | RunnerFacts |

## RunnerFacts

`claude_code_version`, `model`, `api_key_source`, `cost_usd` (summed over attempts),
`turns`, `duration_ms`, `tools_called`, `attempts` (1 or 2).

## RunRecord (one JSON file per start)

| Field | Type | Meaning |
|---|---|---|
| `run_id` | text | `20261105T094500Z-a1b2c3` |
| `record_version` | 1 | the record's format |
| `job`, `period`, `run_key` | text | `check`, `2026-11-05`, `check:2026-11-05` |
| `trigger` | `scheduler` or `user` | |
| `forced` | boolean | `--force` given |
| `engine_version` | text | the package version |
| `outcome` | `delivered`, `skipped`, `refused`, `inconclusive`, `failed` | |
| `reason` | text or null | why, for every outcome but `delivered` |
| `started_at`, `ended_at` | ISO 8601 with offset | |
| `inputs` | list of references | none for `check` |
| `delivery` | path or null | the outbox file |
| `runner` | RunnerFacts or null | null when the model did not run |
| `agreement` | null | filled by chat-output |

No field holds a secret's value or the prompt's text.

**Outcome transitions** of a start:

```text
start → (invalid config / unknown job / store unwritable) → exit 2, no record
start → lock busy → skipped
start → key already delivered, no --force → skipped
start → secret missing or unavailable → failed
start → runner: refused → notice delivered → refused
start → runner: invalid output twice → notice delivered → inconclusive
start → runner: error → failed
start → runner: ok → delivery fails → failed
start → runner: ok → delivered
```

## ScheduledJob (what the scheduler should run)

`name`, `label` (`opscout.<job>`), `arguments` (the absolute program, then `run <job>
--config <dir> --trigger scheduler`), `times` (ISO weekday 1–7, hour, minute; local time),
`log` (`<log>/<job>.log`), `environment` (`PATH`: the directories of `claude`, `node` and
the engine's program, then the system's; research R5).

## InstalledJob (launchd)

`label`, `path`, `content` (the file's bytes), `loaded`, `arguments` (empty when the file
cannot be read), `modified_at`. Status reads the program, the clone after `--project` and
the version in `opscout==<version>` from the arguments.

## SchedulerChange

`action` (`add`, `update`, `remove`, `load`), `label`, `current` bytes or absent, `new` bytes
or absent, and the `ScheduledJob` for every action but `remove`. A **PendingSchedule** is
the ordered list of changes; its confirmation code is computed over it
(`services/confirm.py`, research R11).

## SecretStatus

`present`, `missing`, `unavailable` (with the backend's reason, never the value).
