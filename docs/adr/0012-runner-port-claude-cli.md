---
status: accepted
date: 2026-11-03
decision-makers: repository maintainer
---

# Agent runtime behind a Runner port; the user's own `claude -p` is the default runner

## Context and Problem Statement

The daemon runs skills with nobody at the keyboard (the daily, thread mentions). PLAN.md open
item 1 asked whether runs go through headless `claude -p` or the Claude Agent SDK.

Facts (official docs, 2026-11-03):

- The Agent SDK quickstart asks for `ANTHROPIC_API_KEY`. The usage policy says: "Unless
  previously approved, Anthropic does not allow third party developers to offer claude.ai login
  or rate limits for their products, including agents built on the Claude Agent SDK."
- The same documentation says it does not prevent "an end user from signing in to the
  unmodified Claude Code binary with their own Claude subscription".
- `claude -p` supports restricted, structured runs: `--tools`, `--strict-mcp-config`,
  `--allowedTools`, `--permission-mode dontAsk`, `--output-format stream-json`,
  `--json-schema`, `--max-turns`, `--max-budget-usd`, `--no-session-persistence`.
- The docs expect `--bare`, which ignores OAuth and the keychain, to become the default for
  `-p`.

## Decision Outcome

A `Runner` port with two adapters:

- `ClaudeCliRunner` (default) invokes the user's own, unmodified `claude -p` with every flag
  set explicitly: the tool restrictions from ADR-0010, a JSON schema for structured verdicts, a
  budget, and no session persistence. The engine never stores or proxies Claude credentials;
  the run uses whatever login the user's Claude Code has.
- `AgentSdkRunner` (optional) is for users who prefer API-key billing.

Both adapters share one convergence policy (ADR-0018). A structured output that fails schema
validation, or whose evidence citations do not check out, gets one retry carrying the
validator's message. After that, the run ends as `inconclusive`, is recorded, and goes to the
user.

This is not legal advice. The policy is re-checked when the daemon is implemented
(PLAN.md §8).

### Consequences

- Good, because no credential handling lives in this project.
- Good, because the runtime can change without touching the skills.
- Bad, because the runner is coupled to the CLI's flags and stream-json events. Contract tests
  pin the expected flags and event shapes, so a change in defaults (such as `--bare`) fails a
  test instead of a run.

### Confirmation

Contract tests for the runner; each run record stores the CLI version used.

## More Information

To verify in the daemon's spec: whether a launchd agent can use the user's existing login. If
it cannot, the documented fallback is a token the user creates with `claude setup-token`, kept
in the keychain and passed only to the child process.
