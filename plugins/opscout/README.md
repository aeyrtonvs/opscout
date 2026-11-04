# The opscout plugin

Read-only Claude Code agents for the repetitive parts of DevOps work. See the
[repository](https://github.com/aeyrtonvs/opscout) for what it does and how it is built.

## Requirements

- [Claude Code](https://code.claude.com).
- [uv](https://docs.astral.sh/uv/): the plugin runs the opscout engine through it
  (ADR-0022). Without uv, its commands fail with `env: uv: No such file or directory`.
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
