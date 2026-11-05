# Research: Daemon core

Checked on 2026-11-05 against the Claude Code CLI 2.1.318 (live runs on the maintainer's
machine, model `haiku`, total cost under one US cent), PyPI, and the Python standard library.

## R1. The headless run: flags (FR-014)

**Facts** (`claude --help`, 2.1.318, and live runs):

- `--safe-mode` disables every customization: `CLAUDE.md`, skills, installed plugins, hooks,
  MCP servers, custom agents. Authentication still works normally.
- `--restricted` removes the built-in code-running tools and WebFetch unless `--tools` names
  them, and ignores user, project and local settings files.
- `--tools ""` removes every built-in tool. With `--json-schema`, the run still gets one tool,
  `StructuredOutput`, through which the model returns the output.
- `--strict-mcp-config` ignores every MCP server not given by `--mcp-config`.
- `--permission-mode dontAsk` with `--permission-prompts none` denies anything that would
  prompt.
- `--max-turns` is accepted though not listed in the help; the `StructuredOutput` turn did
  not count against `--max-turns 1`.
- Without `--safe-mode`, the run loaded the user's installed plugins (their paths appear in
  the start-up report); with it, only built-in plugins (path `builtin`) were loaded.

**Decision**: the runner always passes, in this order, with no flag left to a default:

```text
claude -p --output-format stream-json --verbose
       --safe-mode --restricted
       --tools <declared tools, comma-separated, or "">
       --strict-mcp-config [--mcp-config <declared servers as JSON>]
       --permission-mode dontAsk --permission-prompts none
       --no-session-persistence
       --model <model> --max-budget-usd <budget> --max-turns <turns>
       --json-schema <schema>
```

The child's environment (FR-017) is built from scratch, never copied whole. It holds only
these variables, each when set in the engine's own environment:

- `HOME`, `USER`, `LOGNAME`, `PATH`, `TMPDIR`, `SHELL`: the user's home, where Claude Code
  keeps its login and settings, and the search path;
- `LANG` and every `LC_*`: the locale;
- `CLAUDE_CONFIG_DIR`: a non-default Claude Code configuration directory;
- `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY` (either case), `SSL_CERT_FILE`, `SSL_CERT_DIR`,
  `NODE_EXTRA_CA_CERTS`: a corporate proxy or certificate authority;
- the secrets the job declares, under the names the runner maps them to (only
  `CLAUDE_CODE_OAUTH_TOKEN`, from `claude_token`, in this feature).

Nothing else passes: no `ANTHROPIC_API_KEY`, `ANTHROPIC_*` or `CLAUDE_CODE_*` variable from
the engine's environment (they would change the login or the profile behind the report's
back), no cloud credentials, no `OPSCOUT_*`.

One start of Claude Code may take at most 900 seconds; then the child is killed and the run
ends as `failed` ("Claude Code took longer than 900 s and was stopped"). Budget and turn
limits bound a normal run far below that; the limit catches a hung child, so a scheduled
job never holds its period's lock indefinitely.

The prompt goes on standard input, so it never shows in the process list. The working
directory is an empty directory of the engine's own (`<cache>/run`), so no project file is
in reach. The flags are pinned by a contract test (ADR-0012).

**Alternatives rejected**: `--bare`, which ignores the OAuth login and needs an API key
(ADR-0012); `--setting-sources ""` alone, which still loads plugins.

## R2. The start-up report and the result (FR-015, FR-018)

**Facts** (live stream, 2.1.318): the first line is `{"type": "system", "subtype": "init",
…}` with, among others, `tools` (`["StructuredOutput"]` for a tool-less schema run),
`mcp_servers` (`[]`), `model` (the full id, such as `claude-haiku-5-5`, for the alias
`haiku`), `permissionMode` (`"dontAsk"`), `plugins` (each with `name`, `path`, `source`),
`apiKeySource` (`"none"` under the OAuth login) and `claude_code_version` (`"2.1.318"`). The
last line is `{"type": "result", …}` with `subtype` (`success`, or an error such as
`error_max_budget_usd`), `is_error`, `num_turns`, `total_cost_usd`, `duration_ms`,
`structured_output`, `permission_denials` and `terminal_reason`. A budget overrun ended with
exit status 1, `is_error: true` and `terminal_reason: "budget_exhausted"`.

**Decision**: the runner reads the stream line by line. The first event must be the
start-up report, or the run is stopped and `refused`. The report must hold every field the
check reads, and must match the profile:

| Field | Must be |
|---|---|
| `tools` | exactly the declared tools, plus `StructuredOutput` when a schema is given |
| `mcp_servers` | exactly the declared servers, by name |
| `permissionMode` | `dontAsk` |
| `model` | the profile's full id; for an alias (`haiku`, `sonnet`, `opus`, `fable`), an id that starts with `claude-<alias>-` |
| `plugins` | every `path` equal to `builtin`: no user plugin, hence none of its hooks |
| `claude_code_version` | at least the minimum version, 2.1.318 |

On a difference the child is terminated, its output discarded, and the record lists each
difference. From the result the record takes `claude_code_version`, `model`,
`total_cost_usd`, `num_turns`, `duration_ms` and `apiKeySource`, plus the tools the model
called, collected from the `tool_use` blocks of the `assistant` events. The fields read are
pinned by contract tests on recorded streams; the recordings are sanitized (fake ids, a
reserved working directory) before they are committed.

## R3. Convergence (FR-016)

**Decision**: the output is `structured_output` from the result, validated with the job's
own pydantic model (no new dependency; the schema passed to `--json-schema` is that model's
`model_json_schema()`). A missing or invalid output starts one more run whose prompt ends
with the validator's message; a second failure ends as `inconclusive`. Costs and turns of
both runs are summed in the record. The child leads its own process session, so stopping
it reaches every process it started. An exception inside the runner ends the start as
`failed` with the exception's type, so it still leaves its record (FR-006). An `is_error`
result is not retried: it ends as
`failed` with `subtype` and `errors` as the reason. `refused` and `inconclusive` deliver a
notice through the output port (FR-016); `failed` does not deliver, and the SessionStart
notice (R10) reports it.

## R4. Login under launchd (FR-019)

**Facts**: in a terminal, the runs above used the OAuth login (`apiKeySource: "none"`, and
the result carried `credential_expires_at`). Claude Code keeps that login in the macOS login
keychain. A launchd agent in the user's GUI domain (`gui/<uid>`) runs in the user's session,
where that keychain is normally unlocked. This is to be confirmed live, which only an
installed job can do.

**Decision**: settle it in the implementation with the `check` job installed for the next
minute (quickstart, step 4), and record the result in the spec. The fallback is built either
way, since it costs little and the keychain may be locked: when the configuration names the
secret `claude_token`, the runner resolves it and passes it as `CLAUDE_CODE_OAUTH_TOKEN` to
the child only. The user creates it with `claude setup-token` and stores it with
`opscout secret set claude_token`.

## R5. The launchd adapter (FR-009 to FR-013)

**Facts** (`man launchd.plist`, `man launchctl`, macOS 26): a user agent's property list
lives in `~/Library/LaunchAgents` to be loaded at login. `StartCalendarInterval` takes a
list of dictionaries (`Hour`, `Minute`, `Weekday`, with 0 and 7 both Sunday) in the machine's
local time; when the machine sleeps through one or more intervals, launchd starts the job
once on wake. `launchctl bootstrap gui/<uid> <plist>` loads, `launchctl bootout
gui/<uid>/<label>` unloads, and `launchctl print gui/<uid>/<label>` exits 0 only when the
job is loaded.

**Decision**:

- Label `opscout.<job>`; file `~/Library/LaunchAgents/opscout.<job>.plist`. Only files whose
  name starts with `opscout.` are read or changed (spec edge case).
- Keys: `Label`, `ProgramArguments` (R6), `StartCalendarInterval` (one entry per weekday),
  `StandardOutPath` and `StandardErrorPath` (`<log>/<job>.log`), `EnvironmentVariables`
  with a `PATH` of the directories of `claude` (`claude_path`, or the one the installing
  shell finds), `node` and the engine's program, then `/usr/bin:/bin:/usr/sbin:/sbin`, and
  `ProcessType` `Background`. No `RunAtLoad`. The `PATH` does not copy the installing
  shell's, so installing from another terminal, or under `uv run`, changes nothing
  (independent review).
- The bytes come from `plistlib.dumps(…, sort_keys=True)`, so a job is up to date when its
  file holds the same bytes and it is loaded; only then is nothing written or reloaded.
  Updating is bootout, write, bootstrap; an add also boots out first, since a job may be
  loaded with its file gone.
- `launchctl` is reached through a `ServiceManager` seam (`load`, `unload`, `is_loaded`);
  the real one runs `/bin/launchctl`, tests use a fake (FR-013). The agents directory and
  the uid come from the composition root, so tests use a temporary directory.
- The real-launchd test (FR-027) bootstraps a property list from a temporary directory
  under a unique test label, running `/usr/bin/true`, and boots it out in `finally`. It is
  marked `launchd` and skipped unless `sys.platform == "darwin"` and `launchctl print
  gui/<uid>` succeeds (a CI runner may have no GUI domain).

On any other system the composition root has no scheduler: `daemon install`, `uninstall`
and `status` exit 2 with `opscout daemon <command>: no scheduler is available for this
system (only launchd, on macOS)`.

`~/Library/LaunchAgents` is a macOS path by nature; it appears only in the launchd adapter
and its composition, which ADR-0021 allows.

## R6. Which engine an installed job starts (FR-010)

**Facts**: ADR-0022's launcher runs `uv run --frozen --project <clone> opscout` from a clone,
or `uvx --from opscout==<version> opscout` for a release. `sys.executable` under `uvx` lives
in uv's cache, which `uv cache clean` may remove.

**Decision**: install writes the same command the launcher would run, with absolute paths:
`<uv> run --quiet --frozen --project <clone> opscout run <job> --config <dir> --trigger
scheduler` when the engine's package sits in a clone, else `<uvx> --quiet --from
opscout==<version> opscout run …`. `uv` and `uvx` are found with `shutil.which` at install.
Status reports the job stale when that program or the clone is gone, or when the recorded
version differs from the running engine's (US2 scenario 7).

## R7. Run store, run key and lock (FR-003, FR-004, FR-020, FR-021)

**Decision**:

- Directories come from `platformdirs` (`user_data_dir("opscout")`, `user_log_dir`,
  `user_cache_dir`); records under `<data>/runs/<job>/<run-id>.json`, where the run id is
  the start time in UTC (`20261105T094500Z`) and 6 random hexadecimal characters.
- A record is written to a temporary file in the same directory and moved with
  `os.replace`, so it is complete or absent.
- The period of a daily job is the local date at start (`2026-11-05`); the run key is
  `<job>:<period>`.
- The lock is `fcntl.flock(LOCK_EX | LOCK_NB)` on `<data>/runs/<job>/<period>.lock`, held
  from the "already delivered?" read to the record of the outcome. The kernel releases it
  when the process ends, so a crashed run leaves no stale lock (spec edge case). A start
  that cannot take it records `skipped` ("another start holds this period").
- `fcntl` is POSIX: macOS and Linux. Windows has no user and no gate (ADR-0021); the
  adapter would gain an `msvcrt` lock with its first Windows user.
- A skipped start reads one directory of small files and never starts the model (SC-006).

**Alternatives rejected**: a lock file created with `O_EXCL`, which needs stale-lock
detection; the `filelock` package, a dependency the plan does not name.

## R8. The output port (FR-005, FR-008)

**Decision**: `Delivery.deliver(job, run_id, kind, text)`, where `kind` is `result` or
`notice`. The adapter writes `<data>/outbox/<job>/<run-id>.md` in one step and returns its
path, which the record keeps as the delivery reference. chat-output adds the direct message
as a second adapter.

## R9. Secrets (FR-023, FR-024)

**Facts**: `keyring` 25.7.0 (2025-11-16, MIT) uses the macOS Keychain, the freedesktop
Secret Service and the Windows Credential Locker; `get_password` returns `None` for a
missing item and raises `keyring.errors.KeyringError` (or `NoKeyringError`) when no backend
works or the keychain refuses. On Linux it pulls `SecretStorage` and `jeepney`.

**Decision**: the configuration gives `daemon.secrets: {<name>: <keychain reference>}`,
spec 002's `KeychainRef`; the only name known now is `claude_token`, and validation refuses
others (chat-output adds its own). The account defaults to `opscout` when the reference
gives none. `SecretStore.status(name)` returns `present`, `missing` or `unavailable`;
`resolve(name)` returns the value or raises with the status. `opscout secret set <name>`
reads with `getpass` in a terminal, or one line from standard input otherwise. The adapter
test installs an in-memory `keyring` backend with `keyring.set_keyring`; every test of the
runner and the records searches the outputs for a sentinel secret value (SC-004).

## R10. The SessionStart notice (FR-028)

**Decision**: `session_start` in `entrypoints/hook.py` appends a job section after the SSO
warning, from the configuration and the run records only (no `launchctl`). For each enabled
job it reports: the last outcome when it is `refused`, `inconclusive` or `failed`; a missing
run when the most recent scheduled time is more than 15 minutes past, later than the job
file's modification time (so a job installed after today's slot is not reported), and no
record holds that period; or "not installed" when the job file is absent, on macOS only (elsewhere no scheduler
adapter exists, spec edge case). Each line names
`opscout daemon runs <job>` or `opscout daemon install`. With nothing to report it adds
nothing. It reads a job's newest 100 records, enough for any day's slot. The launcher's "could not run" messages say "opscout's session checks" instead of
"the SSO check", since the hook now does both; spec 005's tests are updated in the same
change.

## R11. Confirmation of install and uninstall (FR-029)

**Decision**: the pending change is the list of actions (`add`, `update`, `remove`, `load`,
`unload`, each with its label) and, for each file, its current and new bytes. Its code is the
first 12 hexadecimal characters of SHA-256 over that list, as in spec 006 (research R3).
`confirmation_code` moves from `services/context.py` to `services/confirm.py`, shared by
both features; spec 006's behavior does not change. In a terminal, install asks
`Apply these changes to your scheduled jobs? [y/N]`, computes the change again after the
answer and applies it only if its code is unchanged.

## R12. The `check` job (FR-007)

**Decision**: period the local date; profile: no tools, model `haiku`, budget 0.05 USD, 3
turns (each overridable in the configuration). The prompt asks for `{"ok": true, "note":
"<one short sentence>"}`. The delivered text names the Claude Code version, model, login
source (`apiKeySource`), cost and duration from the run's own reports. It never reads
anything of the user's.

## R13. Exit codes and messages

| Command | 0 | 1 | 2 |
|---|---|---|---|
| `opscout run <job>` | `delivered`, `skipped` | `refused`, `inconclusive`, `failed`; or a run whose record could not be written | cannot start: invalid configuration, unknown job, run store not writable |
| `daemon install`, `uninstall` | applied, or nothing to change | not confirmed | error |
| `daemon status`, `runs` | listed | — | error |
| `secret set`, `check` | stored; present | missing, unavailable | error |

Errors go to standard error as `opscout <command>: <reason>`.

## R13b. The composition-root rule (FR-025)

The existing layers contract lets any entrypoint import an adapter. A second import-linter
contract, `forbidden` with `allow_indirect_imports = true`, forbids
`opscout.entrypoints.cli` and `opscout.entrypoints.hook` from importing `opscout.adapters`
directly, so only `opscout.entrypoints.daemon` builds adapters. A test marked FR-025 reads
`pyproject.toml` and asserts the contract is present, so removing it fails the suite.

## R14. Dependencies (constitution: no dependency without a reason)

| Package | Group | Reason | Version |
|---|---|---|---|
| `platformdirs` | runtime | state, log and cache directories on every OS (ADR-0021 rule 3) | `>=4.14,<5`, locked at 4.14.3, the version `uv.lock` already held through the development tools |
| `keyring` | runtime | the `SecretStore` adapter (ADR-0021) | `>=25.7,<26`, locked at 25.7.0 |

No new development dependency: launchd and Claude Code are faked through their seams.

## R15. The macOS CI policy (FR-027; clarified 2026-11-05)

**Decision**: the macOS test jobs stay informational. ADR-0016 records why (the adapter is
tested everywhere through its seam; the real-launchd test runs on macOS, locally, on every
pull request and daily on `main`), and PLAN.md §9's item is closed.
