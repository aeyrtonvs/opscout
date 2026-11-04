# opscout

**A read-only agent harness for DevOps toil.**

opscout turns the repetitive parts of DevOps work into Claude Code agents: alert triage,
cost triage, answering teammates' "is X configured?" questions, a daily-standup summary,
and fixed-format write-ups. The agents investigate and report with evidence. They never
change the systems they look at.

> **Status: pre-alpha.** The engineering bootstrap is in progress (Phase 0a of
> [`docs/PLAN.md`](docs/PLAN.md)). Nothing is usable yet.

## How it is meant to work

- **Read-only by construction.** Agents use a read-only identity and allow-listed tools, so
  read-only is enforced by permissions, not by prompts. They report whether a secret exists
  and where it lives, never its value.
- **Public engine, private configuration.** This repository holds no organization's data.
  Accounts, alert formats, channels and schedules live in your own private configuration
  repository, validated against a versioned schema.
- **Your own Claude Code.** The agents run in your unmodified Claude Code, as a plugin from
  this repository, which is its own marketplace. A separate daemon will run the scheduled
  and chat-triggered parts.
- **A human approves every outward-facing action.** Agents draft tickets and messages;
  people send them.

## Installing

There is no release yet. Once there is, the plugin installs from inside Claude Code:

```text
/plugin marketplace add aeyrtonvs/opscout
/plugin install opscout@opscout
```

## Developing

You need git, [uv](https://docs.astral.sh/uv/) and Claude Code. Every other tool is pinned
in `uv.lock` or in `.pre-commit-config.yaml`, so nothing else is installed globally.

```sh
uv sync              # the toolchain, from uv.lock
uv run just setup    # the git hooks
uv run just check    # every local gate
```

Read [`CONTRIBUTING.md`](CONTRIBUTING.md) before your first change.

## Documentation

- [`docs/PLAN.md`](docs/PLAN.md): the needs, the roadmap and the open items.
- [`docs/adr/`](docs/adr/): the architecture decisions.
- [`.specify/memory/constitution.md`](.specify/memory/constitution.md): the principles every
  change follows.
- [`AGENTS.md`](AGENTS.md): how coding agents work on this repository.

## License

[Apache-2.0](LICENSE). See also [`NOTICE`](NOTICE).
