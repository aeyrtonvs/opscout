# Quickstart: validate the daemon core

1. Tests and gates (any OS; the real-launchd test runs only on macOS):

   ```sh
   uv run just test tests/unit/daemon
   uv run just check
   ```

2. The `check` job by hand, against the example configuration (one cheap model run):

   ```sh
   opscout run check --config example-config            # delivered to <outbox file>, exit 0
   opscout run check --config example-config            # skipped (already delivered), exit 0
   opscout run check --config example-config --force    # delivered again
   opscout daemon runs check --config example-config
   ```

3. Install, idempotently (macOS):

   ```sh
   opscout daemon install --dry-run --config <private config>   # changes and a code, exit 1
   opscout daemon install --confirm <code> --config <private config>
   opscout daemon install --dry-run --config <private config>   # up to date, exit 0
   opscout daemon status --config <private config>
   ```

4. The login question (FR-019, SC-005): set `daemon.jobs.check.at` two minutes ahead, install,
   leave the keyboard, then:

   ```sh
   opscout daemon runs check --config <private config>   # trigger scheduler, outcome delivered?
   ```

   `delivered` with `apiKeySource` `none` in the outbox text: launchd jobs can use the login;
   record it in the spec. `failed` with an authentication reason: run `claude setup-token`,
   then `opscout secret set claude_token`, add `daemon.secrets.claude_token` to the
   configuration, and repeat.

5. The SessionStart notice: disable `claude` on the job's `PATH` (or set `claude_path` to a
   missing file), let the job run, then start a Claude Code session with the plugin loaded
   from the clone: the session start reports the failed run.

6. Clean up: `opscout daemon uninstall --dry-run`, then `--confirm <code>`.
