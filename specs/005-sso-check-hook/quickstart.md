# Quickstart: validate the SSO check hook

```sh
uv run just test tests/unit/sso
plugins/opscout/bin/opscout sso check              # your own sessions; exit 1 if a login is needed
echo '{"hook_event_name":"SessionStart","source":"startup"}' \
  | plugins/opscout/bin/opscout hook session-start # nothing, or one JSON warning
uv run just check
```

In a session: `claude --plugin-dir plugins/opscout` with an expired session shows the warning
before the first prompt; after `aws sso login --sso-session <name>`, `/clear` shows none.
