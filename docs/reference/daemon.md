# Scheduled jobs reference

opscout runs a few jobs on a schedule, on your own machine, with your own Claude Code
(spec 007, ADR-0021). A job is a command, `opscout run <job>`, that does its work at most
once per period; the operating system's scheduler only starts it. Today the engine has one
job, `check`, a diagnostic that runs the whole path once. The daily standup and the chat
delivery come in later specs.

## The commands

Every command takes `--config DIR`, else `OPSCOUT_CONFIG`, else `~/.config/opscout/`.

| Command | What it does | Exit status |
|---|---|---|
| `opscout run <job> [--force]` | runs the job for the current period, unless that period already delivered | 0 delivered or skipped; 1 refused, inconclusive or failed; 2 cannot start |
| `opscout daemon install [--dry-run] [--confirm CODE]` | makes the installed jobs match the enabled jobs of the configuration | 0 applied or up to date; 1 not confirmed; 2 error |
| `opscout daemon uninstall [--dry-run] [--confirm CODE]` | removes every job opscout installed | the same |
| `opscout daemon status` | each configured or installed job, its schedule, any mismatch, and its last outcome | 0; 2 error |
| `opscout daemon runs [<job>] [--limit N]` | the newest run records, 20 by default | 0 |
| `opscout secret set <name>` | stores a secret in the OS keychain, read without echo (or one line of standard input) | 0 stored; 2 error |
| `opscout secret check [<name>]` | says whether each configured secret is there, and where; never its value | 0 all present; 1 missing or unavailable; 2 error |

Install and uninstall change nothing without your approval: in a terminal they ask
`Apply these changes to your scheduled jobs? [y/N]`; elsewhere, or with `--dry-run`, they
print the changes and a confirmation code, and `--confirm <code>` applies exactly those
changes. A code stops working as soon as the configuration or the installed jobs change.
Running install again when nothing changed writes and reloads nothing.

## Periods and outcomes

A job's period is computed once, at start, from the machine's local time; for `check` it is
the calendar day. A start that finds its period already delivered is `skipped`, and so is a
start while another one holds the period's lock; `--force` runs again and the record says
so. A machine that slept through a scheduled time runs the job once on wake, for the
current period only.

| Outcome | Meaning | Delivered |
|---|---|---|
| `delivered` | the output was valid and delivered | the result |
| `skipped` | the period already delivered, or another start holds it | nothing |
| `refused` | Claude Code started with more than the job allows (see below) | a notice |
| `inconclusive` | the output failed its schema twice | a notice |
| `failed` | Claude Code, a secret or the delivery failed | nothing; the next session start says so |

## How a model run is restricted

The runner starts your own `claude -p` with every restriction as a flag: no tools but the
job's, no MCP server but the job's, `--safe-mode` (no `CLAUDE.md`, skills, plugins or hooks of
yours), `--permission-mode dontAsk`, no session persistence, and the job's model, budget,
turn limit and output schema. The prompt goes on standard input, and the working directory
is an empty one of opscout's. Then it reads Claude Code's start-up report and compares it
with the job's profile: different tools or tool servers, another permission mode, another
model, a plugin of yours, or a Claude Code older than 2.1.318 stops the run, discards its
output and records `refused` with each difference. An output that fails the job's schema
gets one more run that carries the validator's message. One start of Claude Code may take
at most 900 seconds; a run that takes longer is stopped and recorded as `failed`.

The child gets only these environment variables, when set: `HOME`, `USER`, `LOGNAME`,
`PATH`, `TMPDIR`, `SHELL`, `LANG`, every `LC_*`, `CLAUDE_CONFIG_DIR`, the proxy variables
(`HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY`, in either case), `SSL_CERT_FILE`, `SSL_CERT_DIR`
and `NODE_EXTRA_CA_CERTS`, plus the job's declared secrets. No `ANTHROPIC_*` or
`CLAUDE_CODE_*` variable of yours reaches it.

## Files and directories

| What | Where (macOS; other systems follow `platformdirs`) |
|---|---|
| Run records, one JSON file per start | `~/Library/Application Support/opscout/runs/<job>/<run-id>.json` |
| Deliveries (the outbox) | `~/Library/Application Support/opscout/outbox/<job>/<run-id>.md` |
| Job logs | `~/Library/Logs/opscout/<job>.log` |
| The runs' empty working directory | `~/Library/Caches/opscout/run` |
| Installed jobs | `~/Library/LaunchAgents/opscout.<job>.plist` |

A record holds the trigger, the job, the engine version, the run key, the outcome and its
reason, the start and end times, the delivery, Claude Code's version, model, login source,
cost, turns, duration and the tools it called, and an empty agreement field for the chat
delivery to fill. It never holds a secret or the prompt. Only files whose name starts with
`opscout.` are read or changed in the agents directory.

An installed job runs the same engine that installed it: `uv run --project <clone>` from a
clone, or `uvx --from opscout==<version>` from a release, with the configuration directory
it was installed with. `opscout daemon status` says when that program or clone is gone, or
when the job was installed by another version; run `opscout daemon install` again then.

## When a job did not run well

With the plugin enabled, the start of a Claude Code session lists, after the SSO check, each
enabled job whose last run was refused, inconclusive or failed, that has no run for its
latest scheduled time (15 minutes after it, and only if the job was installed before it), or
that is configured but not installed. It reads only the configuration and the run records,
and says nothing when every job is fine.

## The login of a scheduled job

A job started by launchd runs in your login session, so Claude Code normally finds the
login you made in a terminal; the `check` job's delivery names the login source it saw. If
a scheduled run fails because it cannot use your login, create a long-lived token and keep
it in the keychain:

```sh
claude setup-token                    # prints a token
opscout secret set claude_token       # paste it; it is not shown
```

then name it in the configuration:

```yaml
daemon:
  secrets:
    claude_token:
      service: opscout-example        # any keychain service name; account defaults to opscout
```

The runner then passes it as `CLAUDE_CODE_OAUTH_TOKEN` to Claude Code only.

## Delivery by direct message (Slack)

With the `daemon.chat` setting, every delivery also reaches you as a Slack direct message
from your own opscout app, and each result asks **Agree** or **Disagree**; your answer is
stored in the run's record, for the evidence later phases depend on (spec 008).

The app can only write to you: it asks for two permissions, `chat:write` and `im:write`,
reads no channel and no message, receives no event but the clicks on its own buttons, and
its Messages tab is read-only. It connects outward over Socket Mode, so your machine opens
no port.

### Set it up once

1. In Slack, **Create New App → From a manifest**, choose your workspace and paste
   [`deploy/slack/opscout-app-manifest.yaml`](../../deploy/slack/opscout-app-manifest.yaml).
   **Install to Workspace**. The **Bot User OAuth Token** (`xoxb-…`) is under **OAuth &
   Permissions**.
2. Under **Basic Information → App-Level Tokens**, generate a token with the scope
   `connections:write` (`xapp-…`).
3. In your Slack profile, **⋮ → Copy member ID**.
4. Store both tokens; they are read without echo and never shown again:

   ```sh
   opscout secret set slack_bot_token
   opscout secret set slack_app_token
   opscout secret check
   ```

5. In your configuration:

   ```yaml
   daemon:
     chat:
       service: slack
       user: UEXAMPLE01             # your member id
     secrets:
       slack_bot_token:
         service: opscout-slack-bot
       slack_app_token:
         service: opscout-slack-app
   ```

6. `opscout daemon install` (it now also adds `opscout.gateway`), then `opscout run check
   --force` to see a message arrive.

### What happens

- A result goes to the outbox file first, then by direct message; it counts as delivered
  only once Slack accepted it. When Slack cannot be reached, the run keeps trying for up to
  10 minutes, then ends `failed`. A text longer than about 11,000 characters is cut, and
  the message names the outbox file.
- A refused or inconclusive run sends its notice, and a failed run a short notice, without
  buttons. A failure of the delivery itself is reported at the next session start.
- **The gateway** (`opscout gateway`, run by launchd from login, restarted after an error)
  holds the connection and stores your clicks. **Agree** stores `agree`; **Disagree** asks
  for an optional reason of up to 500 characters; clicking the other button changes your
  answer. Only your own clicks count; anything else is ignored. A reason is kept in the run
  record only, never in a log.
- Its log is `~/Library/Logs/opscout/gateway.log`, with states and counts only; its state
  is `~/Library/Application Support/opscout/gateway.json`. `opscout daemon status` shows
  whether it is connected, and the session start says when it is not installed, stopped,
  or not connected for 15 minutes.
- A token Slack rejects (revoked, app removed) stops the gateway for good, and status says
  so; after you store a new token, `opscout daemon install` starts it again. A missing
  token or an invalid configuration makes it try again every 5 minutes. A change of
  `daemon.chat` takes effect at the next `opscout daemon install`.

## Other systems

The scheduler adapter is launchd, on macOS. Elsewhere `opscout run` works (with cron or a
systemd timer of your own), and `daemon install`, `uninstall` and `status` say that no
scheduler is available.
