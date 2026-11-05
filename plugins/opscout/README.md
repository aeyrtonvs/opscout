# The opscout plugin

Read-only Claude Code agents for the repetitive parts of DevOps work. See the
[repository](https://github.com/aeyrtonvs/opscout) for what it does and how it is built.

## Requirements

- [Claude Code](https://code.claude.com).
- [uv](https://docs.astral.sh/uv/), with the `uvx` its installers add: the plugin runs the
  opscout engine through it (ADR-0022). Without uv, its commands fail with
  `env: uv: No such file or directory`.
- A private configuration directory (asked for at install time), validated with
  `opscout config validate`. See `docs/reference/configuration.md` in the repository.

## Loading it

There is no release yet, so load the plugin from a clone:

```sh
git clone https://github.com/aeyrtonvs/opscout
claude --plugin-dir opscout/plugins/opscout
```

From a clone, the plugin runs the clone's engine. Once released, install it from this
repository's marketplace, and it runs the engine release of exactly its own version:

```text
/plugin install opscout --marketplace aeyrtonvs/opscout
```

## Skills

- `summary`: a write-up of the session's work, ready to paste into a ticket, a chat message
  or a postmortem, in your configured formats (spec 003).
- `ship`: branch, commit with a checked Conventional Commit message, push through the push
  guard, and open a draft pull request with your `gh` (spec 004).

## Hooks

- **Push guard** (PreToolUse, spec 004): asks before every `git push` and `gh pr create`
  Claude runs, and refuses a push to a protected branch, whatever your permission settings
  say.
- **SSO check** (SessionStart, spec 005): when a session starts, resumes, is cleared or is
  forked, tells you and Claude which AWS SSO logins have expired or are missing, with the
  `aws sso login` command for each, from the local token cache alone. It never uses the
  network and never shows a token. `opscout sso check` shows the same by hand.
