# Contract: commands

Spec 007's commands keep their behavior when `daemon.chat` is absent.

## `opscout run <job>` with chat configured

Same lines and exit codes as spec 007. A delivery that Slack does not accept within 10
minutes, or refuses, ends:

```text
check 2026-11-05: failed (delivery failed: Slack refused the message (invalid_auth))
check 2026-11-05: failed (delivery failed: Slack could not be reached for 10 minutes)
```

A missing token fails before any model run:

```text
check 2026-11-05: failed (the secret slack_bot_token is missing from the keychain; store it with opscout secret set slack_bot_token)
```

## `opscout gateway [--config DIR]`

Runs in the foreground until stopped; launchd runs it as `opscout.gateway`. Log lines (to
standard error):

```text
opscout gateway: connecting to Slack
opscout gateway: connected
opscout gateway: disconnected; reconnecting
opscout gateway: cannot connect (URLError); reconnecting
opscout gateway: stopped: token rejected (invalid_auth)
opscout gateway: stopped: daemon.chat is not configured
opscout gateway: another gateway is running
opscout gateway: stopped: asked to stop
```

Exit 0 when it must not be restarted (the last three); exit 1 on any other error, so
launchd starts it again. An invalid configuration or a missing token logs
`opscout gateway: stopped: <why>; retrying in 5 minutes`, waits 5 minutes, then exits 1.

## `opscout daemon install | uninstall | status`

With chat configured, the gateway is one more entry: `add opscout.gateway (always)`.
Status adds a line:

```text
gateway  always  installed, loaded  connected since 2026-11-05 09:12
gateway  always  installed, loaded  not connected since 2026-11-05 09:12 (see <log file>)
gateway  always  installed, loaded  not running; last seen 2026-11-05 09:12 (see <log file>)
gateway  always  installed, loaded  stopped: token rejected (invalid_auth); last seen 2026-11-05 09:12 (run opscout daemon install to start it again; see <log file>)
gateway  always  installed, loaded  never connected (see <log file>)
gateway  always  not installed (run opscout daemon install)
gateway  always  installed but chat is not configured (run opscout daemon install)
```

A gateway that stopped for good is started again by install, after confirmation:
`restart opscout.gateway (stopped: token rejected (invalid_auth))`. A change of the chat
setting shows as `update opscout.gateway (always)`.

## `opscout secret set | check`

`slack_bot_token` and `slack_app_token` are known names, stored and checked like
`claude_token`.

## SessionStart notice (spec 007, FR-028), with chat configured

```text
opscout scheduled jobs:
- gateway: not installed (run opscout daemon install)
- gateway: never connected (see <log file>)
- gateway: not connected since 2026-11-05 09:12 (see <log file>)
- gateway: not running since 2026-11-05 09:12 (see <log file>)
- gateway: stopped: token rejected (invalid_auth) (run opscout daemon install to start it again)
```

## The direct message

A result: the job's text, then `Agree` and `Disagree`, then
`opscout check, run 20261105T094500Z-a1b2c3`. After a click the last line reads
`Agreed on 2026-11-05 10:02` or `Disagreed on 2026-11-05 10:02: <reason>`, or
`This choice could not be recorded (run <run-id> not found).` A notice or a failure notice
has the text only.
