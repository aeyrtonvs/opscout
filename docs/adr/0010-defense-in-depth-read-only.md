---
status: accepted
date: 2026-11-03
decision-makers: repository maintainer
---

# Read-only is enforced in five layers, strongest first

## Context and Problem Statement

Agents read untrusted text (alert bodies, log lines, chat threads) while holding access to
private data and a channel that sends messages out. With that combination, a prompt injection
can become data exfiltration or, given write access, an action. The OWASP Top 10 for Agentic
Applications (December 2025) names the relevant risks: goal hijack (ASI01), tool misuse
(ASI02), identity and privilege abuse (ASI03), supply chain (ASI04) and unexpected code
execution (ASI05). Constitution Principles II and III require controls the model cannot
override.

Facts that constrain the design (official docs, 2026-11-03):

- Subagents shipped inside a plugin ignore `permissionMode`, `hooks` and `mcpServers`, so
  enforcement cannot live in plugin subagent frontmatter.
- Claude Code's sandbox confines Bash only. MCP servers and hooks run outside it.
- A headless run can drop every built-in tool (`--tools ""`), load only listed MCP servers
  (`--strict-mcp-config`), and deny anything not pre-approved (`--permission-mode dontAsk`,
  `--permission-prompts none`).
- A PostToolUse hook can replace what the model sees from a tool (`updatedToolOutput`,
  `updatedMCPToolOutput`). The original output is still recorded in telemetry.

## Decision Outcome

1. **Identity.** A dedicated read-only identity per environment, never the user's admin role:
   view-only cloud permissions with explicit denies on secret-value APIs; the Kubernetes `view`
   role, which excludes Secrets; a read-only observability key; minimal chat-bot scopes;
   read-only code-host and ticket tokens. This repository ships reference policies with fake
   IDs; the employer's IaC repository instantiates them.
2. **Tool surface.** Headless runs get no built-in shell or editor: only the harness's
   read-only MCP server (ADR-0011) and vetted read-only servers, each tool listed by name, with
   turn and budget limits. Hosts are reached through allow-listed command documents, never a
   generic run-shell document.
3. **Output channel.** The bot answers only allow-listed users, and only in the thread or DM
   the request came from.
4. **Redaction.** A PostToolUse hook redacts secret-shaped values before the model sees them.
   This covers read-only APIs that still return plaintext, such as function environment
   variables or container task definitions.
5. **Interactive guard.** In interactive sessions, skills declare `allowed-tools` and a
   PreToolUse hook denies mutating CLI verbs. This is a safety net, not a control.

### Consequences

- Good, because a hijacked model still cannot change infrastructure or read secret values.
- Bad, because it needs IAM work in the employer's IaC repository (PLAN.md open items).
- Bad, because redaction is pattern-based and therefore best-effort; layers 1 and 2 carry the
  guarantee.

### Confirmation

- An integration test with the real identity in a sandbox account: a mutation and a secret
  read both return access denied.
- Runner tests assert that the `system/init` event of a headless run lists only the allowed
  tools.
- Eval cases with instructions injected into alert text and chat threads.

## More Information

**Amended 2026-11-05 (spec 010).** Decision 1 now has these parts:

- **The read-only identity's boundary.** Its permissions boundary is AWS's `ReadOnlyAccess`.
  The policy grammar documents no wildcard in the service prefix (such as `*:Get*`), and a
  customer-managed policy is limited to 6,144 characters. So no hand-written boundary can
  cap every write, while `ReadOnlyAccess` allows no write except a few that the guardrail
  denies.
- **The guardrail.** It is a customer-managed policy of explicit denies attached to the
  identity. It denies secret values, credential issuance, reads that return plaintext
  secrets, application data, and sessions and shells.
- **The host identity.** `ssm:SendCommand` is a write, so host commands use a second,
  optional identity per environment. It may only send the catalog's fixed command
  documents, under its own boundary.
- **The check.** `opscout identity check` proves all of this offline, against a recorded
  copy of AWS's action catalog. It is the static half of this ADR's confirmation. The live
  half, a sandbox account, stays an open item in PLAN.md §9.

**Amended 2026-11-06 by [ADR-0023](0023-read-only-identity-recommended.md).** Decision 1's
identity is the recommended outer layer, not a requirement: a user may run with their own
identity at their own risk. Layers 2 to 5 are unchanged, and the tool surface carries the
guarantee whatever identity is used.
