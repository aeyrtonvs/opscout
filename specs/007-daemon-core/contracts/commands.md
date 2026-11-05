# Contract: the daemon commands

Every command takes `--config DIR` (else `OPSCOUT_CONFIG`, else `~/.config/opscout/`, as
spec 002 resolves it). Errors (exit 2) go to standard error as `opscout <command>: <reason>`.
Exit codes: research R13.

## `opscout run <job> [--force] [--trigger scheduler|user]`

Runs one job for the current period. `--trigger` defaults to `user`; installed jobs pass
`scheduler`. Prints one line:

```text
check 2026-11-05: delivered to <outbox file>
check 2026-11-05: skipped (already delivered by run 20261105T094500Z-a1b2c3)
check 2026-11-05: skipped (another start holds this period)
check 2026-11-05: refused (tools: expected [StructuredOutput], got [Bash, StructuredOutput])
check 2026-11-05: inconclusive (the output failed its schema twice: <validator message>)
check 2026-11-05: failed (<reason>)
```

A run whose record could not be written prints, on standard error, `opscout run: <the line
above>, but its record could not be written: <reason>; the next start may deliver again`,
exit 1.

An unknown job: `opscout run: unknown job "<name>"; configured jobs: check` (or `none (the
engine's jobs: check)`), exit 2. An invalid configuration points to `opscout config
validate`; a run store that cannot be used is named; both exit 2 before any model run.

## `opscout daemon install [--dry-run] [--confirm CODE]`

Makes the installed jobs match the enabled jobs of the configuration. Output: one line per
change (`add opscout.check (09:30 mon–fri)`, `update …`, `remove …`), then:

- nothing to change: `Scheduled jobs are up to date.`, exit 0;
- `--dry-run` (even with `--confirm`), or no terminal and no code: `Confirmation code: <code>` and the command to
  run, exit 1;
- in a terminal: `Apply these changes to your scheduled jobs? [y/N]`;
- a code that no longer matches: `The configuration or the installed jobs changed since that
  code; run opscout daemon install --dry-run again.`, exit 1;
- applied: `Installed <n>, updated <n>, removed <n>.` (with `, loaded <n>` when installed
  jobs were only loaded), exit 0;
- in a terminal, a no or no answer: `Nothing was changed.`, exit 1; a change between the
  question and the answer: nothing is applied, exit 1.

Where no scheduler exists (anything but macOS), install, uninstall and status exit 2 with
`opscout daemon <command>: no scheduler is available for this system (only launchd, on
macOS)`.

## `opscout daemon uninstall [--dry-run] [--confirm CODE]`

Removes every `opscout.*` job; same confirmation and messages as install
(`Nothing to uninstall.` when none).

## `opscout daemon status`

One block per job, configured or installed:

```text
check  09:30 mon–fri  installed, loaded  last: delivered 2026-11-05 09:30
```

Mismatches are named on the line: `not installed`, `installed but not configured`,
`schedule differs from the configuration`, `not loaded`, `stale: <program> is missing` or
`stale: installed with engine <version>`, and `disabled` for a disabled job; each mismatch
says to run `opscout daemon install`. Without any job: `No jobs are configured or
installed.` Exit 0.

## `opscout daemon runs [<job>] [--limit N]`

Newest first, default 20:

```text
20261105T093000Z-a1b2c3  check  2026-11-05  scheduler  delivered     0.0005 USD  1.3 s
```

## `opscout secret set <name>` / `opscout secret check [<name>]`

`set` reads the value without echo in a terminal, else one line from standard input, and
prints `Stored <name> in the keychain (service <service>, account <account>).` The name must
be known and in `daemon.secrets`, and an empty value is refused (exit 2). `check` prints,
per configured secret, `<name>: present (keychain service <service>, account <account>)`,
with `missing` or `unavailable` (`<reason>; ` before the service) instead; never the value.
It exits 1 when one is not present, and prints `No secrets are configured.` when none is.
An unknown name: exit 2.

## SessionStart notice (FR-028)

Appended to the existing SessionStart hook output (spec 005), one line per job needing
attention, under `opscout scheduled jobs:`:

```text
- check: the last run failed on 2026-11-05 09:30 (see opscout daemon runs check)
- check: no run for its 09:30 slot on 2026-11-05 (see opscout daemon runs check)
- check: configured but not installed (run opscout daemon install)
```

`refused` and `inconclusive` read `the last run was refused on …` and `… was
inconclusive on …`. A run store that cannot be read gives one line, `opscout scheduled
jobs: could not be checked (<error type>)`.
