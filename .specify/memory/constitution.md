<!--
Sync Impact Report
- Version change: 1.0.2 → 2.0.0 (MAJOR, ADR-0023): Principle II is redefined. The
  harness's own mechanisms (the allow-listed tool surface, which exposes no write and no
  secret-value operation, and the allow-listed host documents) stay mandatory; the
  read-only identity becomes the recommended outer layer, and a user may run with another
  identity at their own risk. Principle III's secret-value rule moves to the tool surface,
  and the reference identity keeps its denies. Principle V gains "every integration is
  optional". Approved by the maintainer on 2026-11-06
- 1.0.2 (PATCH): "OS-specific code lives behind the scheduler port"
  becomes "behind ports, such as the scheduler and the secret store", matching ADR-0011 and
  ADR-0021; a clarification, no principle changes. Approved by the maintainer on 2026-11-03
- 1.0.1: the project is renamed opscout (ADR-0019); the title is the only change
- 1.0.0: ratified by the maintainer on 2026-11-03, with no change to the 0.2.0 text
- 0.2.0 (ADR-0018, harness-engineering practices): Principle VI gains evidence grounding and
  bounded convergence; the workflow gains mandatory Non-Goals in specs, verification and
  escalation, and maker/checker review; Governance gains "Rules and gates" (dual encoding)
- 0.1.0: Principles I–X (derived from CLAUDE.md hard rules and docs/PLAN.md decisions);
  sections Technology & Platform Constraints, Development Workflow & Quality Gates, Governance
- Templates:
  - .specify/templates/plan-template.md: ✅ no change (Constitution Check reads its gates from this file)
  - .specify/templates/spec-template.md: ✅ no change
  - .specify/templates/tasks-template.md: ⚠ marks tests as optional; Principle VII makes them
    mandatory here, so /speckit-tasks must always generate test (and, for skills, eval) tasks
- Follow-up TODOs: none
-->

# opscout Constitution

## Core Principles

### I. Public engine, private data (NON-NEGOTIABLE)

- This repository is public. It MUST NOT contain real organizational or personal data:
  company or product names, account IDs, profile names, hostnames, IPs, chat channel or user
  IDs, ticket keys, alert texts copied from a real workspace, costs, or contact details —
  including commit metadata such as the author e-mail.
- Every organization-specific fact MUST come from the private configuration (Principle V).
- Examples and fixtures MUST use reserved values: AWS account `123456789012`, documentation
  IP ranges (RFC 5737), reserved domains (RFC 2606, e.g. `example.com`), and names such as
  `example-prod` or `#alerts-example`.
- The staged diff MUST pass the leak check before every commit, and CI MUST repeat it.
  A leak is an incident: the published history is considered compromised. Deleting the
  commit is not a fix.

*Rationale: a leak in a public repository cannot be undone.*

### II. Read-only by construction (NON-NEGOTIABLE)

- Agents MUST NOT change the systems they investigate: cloud accounts, clusters, hosts,
  IaC, observability, tickets or code hosts.
- Read-only MUST be enforced by mechanisms the model cannot override. The harness's own are
  mandatory: an allow-listed tool surface that exposes no write and no secret-value
  operation, and allow-listed host command documents. Instructions in prompts are a last
  layer, never the control.
- The read-only identity is the recommended outer layer. opscout ships it as a reference and
  recommends it, but never requires it: a user who runs with another identity accepts that
  risk, and opscout states which identity a run used (ADR-0023).
- Unattended (headless) runs MUST NOT have a general-purpose shell. They get only
  allow-listed, read-only tools.
- The only writes allowed are messages to explicitly configured output channels (the
  user's DM, the thread a request came from) and local run records. Tickets, pull requests
  and fixes are produced as drafts for a human.
- Every integration MUST declare the permissions it needs. The reference identity grants
  nothing beyond them.

*Rationale: alerts, logs and chat messages are untrusted input. An agent that can be talked
into acting must be unable to act.*

### III. Secrets: existence and location, never value (NON-NEGOTIABLE)

- Agents MAY report whether a secret exists, where it lives and its metadata. They MUST NOT
  read, print, log or store its value.
- The tool surface MUST NOT expose secret-value APIs (for example
  `secretsmanager:GetSecretValue` and SecureString decryption). The reference identity MUST
  deny them too, and the reference cluster access MUST exclude `secrets`.
- Tool outputs SHOULD be redacted before they reach the model. Run records MUST NOT contain
  secret values.
- The harness's own credentials live in the OS keychain. The configuration names keychain
  services only.

### IV. A human approves every outward-facing action (NON-NEGOTIABLE)

- Nothing leaves the machine without explicit confirmation of that specific action:
  creating a remote, pushing, publishing a release, package or plugin.
- An approval does not carry over to the next action.
- Agents propose; humans apply. A live change diagnosed by an agent is listed exactly and
  waits for the go-ahead.

### V. Configuration over code

- Everything environment-specific (accounts in scope, alert formats, schedules, write-up
  formats, allow-listed users) MUST be expressed in the private configuration and validated
  against a versioned schema shipped with the engine.
- `example-config/` MUST validate against the current schema in CI.
- Breaking schema changes require a major schema version and a migration note.
- Code MUST NOT contain organization-specific branches.
- Every integration is optional. It is enabled only when configured, and a missing,
  unconfigured or failing integration MUST NOT block a feature that does not use it
  (ADR-0023).

### VI. Deterministic gathering, model judgment

- Parsing, scoping, data gathering and filtering MUST be implemented in typed, tested code.
  The model is used for judgment, correlation and writing.
- Any agent output that drives behavior (verdicts, routing, scope decisions) MUST be
  structured and validated against a schema.
- A skill fixes the order of its procedure. The model does not improvise the steps of a
  defined investigation.
- Every claim in a verdict MUST cite evidence returned by a tool in the same run, and the
  harness checks each citation in code. Verdicts state their assumptions and the timezone
  used.
- Convergence is bounded: an output that fails validation gets one retry carrying the
  validator's message. After that, the run ends as `inconclusive` and goes to a human.

### VII. Specified, tested, evaluated

- Every feature starts from a specification whose acceptance scenarios are testable.
- Python code is written test-first. Tests are mandatory, overriding the "optional tests"
  default of the Spec Kit tasks template.
- Agent behavior (skills and subagents) MUST have an eval suite whose cases trace back to
  the acceptance scenarios of its spec. A change MUST NOT lower a suite's score below its
  recorded baseline.
- Nothing merges with a failing gate.

### VIII. Ports and adapters, only what is used

- The core depends on interfaces. Integrations are adapters. Layering is enforced by
  tooling (import contracts), not by convention.
- Only adapters with a current user are built. A new integration is a new adapter with
  contract tests and no change to the core.

### IX. Observable, accountable runs

- Every agent run MUST leave a local record: trigger, skill and version, inputs by
  reference, tools called, verdict, cost, duration, and whether the user agreed.
- Promoting any behavior to run unattended requires evidence from these records and an
  ADR.

### X. Standards over invention; simplicity

- Prefer open standards and established tools over custom formats: AGENTS.md, Agent
  Skills, MCP, Conventional Commits, SemVer, MADR.
- Build the smallest thing that satisfies the spec. One-way-door decisions require an ADR.
  Complexity beyond the plan's gates is justified in its Complexity Tracking section.

## Technology & Platform Constraints

- Python ≥ 3.13 managed with uv; ruff (format and lint), mypy `--strict`, pytest.
- License Apache-2.0, with SPDX identifiers in source files.
- Claude Code plugin layout; the repository is its own marketplace. Skills follow the
  Agent Skills specification and use Claude Code extension fields (such as `effort` or
  `model`) only where they serve a measured need.
- macOS first (launchd). OS-specific code lives behind ports, such as the scheduler and the
  secret store.
- English for code, comments, documentation and commit messages.
- The agent runtime is the user's own, unmodified Claude Code. The engine never stores or
  proxies Claude credentials.

## Development Workflow & Quality Gates

- **Change classes.** A feature or a change in specified behavior goes through the Spec Kit
  flow: specify → clarify → plan → tasks → analyze → implement. A fix, chore or
  documentation change is a plain pull request; if it changes specified behavior, the spec
  is updated in the same pull request. A cross-cutting decision is an ADR in `docs/adr/`.
- **Branches.** `feat/NNN-slug` for specs (created by the Spec Kit git extension);
  `fix/…`, `chore/…`, `docs/…` otherwise. `main` is protected and changes only through
  pull requests.
- **Contracts.** Every spec MUST include a **Non-Goals** section listing what the feature must
  not do or touch. For agent-facing features, it lists behaviors the agent must never
  perform. A plain pull request states its deliverable, constraints, non-goals and
  acceptance in the template.
- **Verification and escalation.** A task is marked done only after its checks pass. If the
  same check fails twice on the same error, the agent stops, shows the exact error and
  proposes a fix for the human to approve.
- **Maker and checker.** After implementation, `/speckit-converge` and an independent review
  of the diff in a fresh context run before the pull request.
- **Commits.** Conventional Commits. Agent-assisted commits end with
  `Assisted-by: <agent/model>`.
- **Gates** (pre-commit and CI): format, lint, types, tests, import contracts, leak check,
  secret scan, plugin validation, and validation of `example-config/`.
- **Definition of done** for a spec: no `[NEEDS CLARIFICATION]` left; `/speckit-analyze`
  reports no critical findings; every functional requirement is covered by a test or an
  eval case; documentation updated; an ADR exists if the architecture changed.

## Governance

- This constitution supersedes all other practices. AGENTS.md, CLAUDE.md and the docs are
  runtime guidance and must not contradict it; on conflict, the constitution wins and the
  other document is corrected.
- Amendments are pull requests that edit this file, update the Sync Impact Report and bump
  the version: MAJOR when a principle is removed or redefined, MINOR when a principle or
  section is added or materially expanded, PATCH for clarifications. An amendment that
  changes an architectural decision links its ADR.
- **Rules and gates.** Every NON-NEGOTIABLE rule is encoded twice: stated where agents read
  it, and enforced by a mechanical gate that AGENTS.md names next to the rule. A rule
  without its gate is an open item in PLAN.md §9 until the gate exists.
- Every `plan.md` MUST pass the Constitution Check. A violation is either justified in
  Complexity Tracking or the plan changes.
- Compliance is checked in every pull request (template checklist) and before every
  release.

**Version**: 2.0.0 | **Ratified**: 2026-11-03 | **Last Amended**: 2026-11-06
