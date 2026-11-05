# Contract: the SSO commands and the hook

```text
opscout sso check [--config DIR]          # every checked session with its state
opscout hook session-start [--config DIR] # a SessionStart event on stdin (not needed)
```

- `sso check`: one line per session, `<name>: <state>[; run: <command>]`, times in local time;
  exit 0 when none needs a login, 1 when one does. No SSO session: one line saying so, exit 0.
  The check turned off: one line saying so, exit 0.
- `hook session-start`: nothing when no login is needed or the check is off; otherwise one
  JSON object

  ```json
  {"systemMessage": "…", "hookSpecificOutput": {"hookEventName": "SessionStart",
   "additionalContext": "…"}}
  ```

  with the same text in both. Always exit 0. Any error: a `systemMessage` only, starting
  `opscout: the SSO check could not run`, with the reason for an AWS config that cannot be
  read and only the error's type otherwise. The launcher answers the same way, exit 0, when
  it cannot start the engine (no release, no `uvx`, an exit other than 0, over 8 s).

The warning text:

```text
opscout SSO check: attention needed for 2 of 3 SSO sessions before AWS commands will work.
- example-session: expired at 2026-11-04 09:12 (local time); run: aws sso login --sso-session example-session
- example-profile: not logged in; run: aws sso login --profile example-profile
```

A name is shell-quoted in the command when it needs it. When the configuration could not be
used, a last line says so and that every session was checked.

`plugins/opscout/hooks/hooks.json` gains:

```json
"SessionStart": [{"matcher": "startup|resume|clear|fork", "hooks": [{"type": "command",
  "command": "${CLAUDE_PLUGIN_ROOT}/bin/opscout", "args": ["hook", "session-start"],
  "timeout": 10}]}]
```
