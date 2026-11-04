# Contract: the ship commands and the guard

```text
opscout ship rules [--config DIR]            # always exits 0; Markdown for the skill
opscout ship check-branch NAME [--config DIR] [--default-branch NAME]
opscout ship check-message FILE|- [--config DIR]
opscout hook pre-tool-use [--config DIR]     # a PreToolUse event on stdin
```

- `check-branch` and `check-message`: exit 0 when valid; 1 with one reason per line.
- `hook pre-tool-use`: prints nothing for a command that is not its business; otherwise
  `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask"|"deny",
  "permissionDecisionReason": "…"}}`; exit 0. An error while deciding about a command that
  names `git push`: exit 2, reason on standard error.

`plugins/opscout/hooks/hooks.json`:

```json
{"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command",
  "command": "${CLAUDE_PLUGIN_ROOT}/bin/opscout",
  "args": ["hook", "pre-tool-use", "--config", "${user_config.config_dir}"],
  "onFailure": "block"}]}]}}
```
