# AGENTS.md — opscout

A public, open-source harness that turns the repetitive parts of DevOps work into
Claude Code agents: alert triage, cost triage, answering teammates' "is X configured?"
questions, a daily-standup summary, and fixed-format write-ups.

## Read first

1. **`.specify/memory/constitution.md`**: the non-negotiable principles. It wins over every
   other document, this one included.
2. **`docs/PLAN.md`**, before proposing anything. It holds the agreed needs, the roadmap,
   the phase you are in and the open items. Do not re-ask a decided question; if a decision
   looks wrong, say so with evidence.
3. **`docs/adr/`**: why the architecture is the way it is (MADR; index in its README).

## Hard rules

Each rule is also enforced by a gate (dual encoding, ADR-0018). A rule whose gate is still
missing is an open item in `docs/PLAN.md` §9.

1. **This repo is public. It never contains anyone's real data.** No company or product
   names, AWS account IDs, profile names, hostnames, IPs, Slack channel or user IDs, Jira
   keys, alert texts copied from a real workspace, or costs. All of that lives in the user's
   **private** config repo, which the engine reads from a path or `OPSCOUT_CONFIG`.
   Examples here use obviously fake values (`123456789012`, `example-prod`,
   `#alerts-example`).
   *Gate:* the leak check (`tools/leak_check.py`) and gitleaks, in pre-commit and CI
   (ADR-0015).
2. **Before every commit, check the staged diff for real data** (rule 1), commit metadata
   included. A leak in a public repo cannot be undone by deleting the commit.
   *Gate:* the same checks on every commit and on every commit you push, plus the commit
   e-mail check.
3. **Agents built here are read-only by design, enforced by mechanisms, not by
   instructions.** Their tool surface exposes only reads and never a secret's value; they
   report whether a secret exists and where; on hosts they run an allow-listed command
   document, not an open shell. The reference read-only identity is the recommended outer
   layer, never a requirement: a user may run with their own identity at their own risk
   (ADR-0023).
   *Gate:* the tool surface, proved read-only by `tests/unit/mcp/test_surface.py` and
   refused at run time by the AWS gateway (spec 011); the reference identity and
   allow-listed host documents, proved by `opscout identity check` (spec 010).
4. **English** for code, comments, docs and commit messages. *Gate:* review only.
5. **Nothing leaves the machine without asking each time:** creating the GitHub remote,
   pushing, publishing a release or a plugin.
   *Gate:* `ask` rules in `.claude/settings.json`. They prompt even when permission prompts
   are bypassed, and headless runs deny them. A PreToolUse hook denies the forms they miss,
   such as `git -C … push`, and names the plain form to use.

## Working rules

- **Contract first.** Features start from a spec that includes Non-Goals; anything else
  states deliverable, constraints, non-goals and acceptance in the pull request.
- **Stay in scope.** Change only the files the current task names; anything else becomes a
  new task.
- **Integrations are optional.** A feature works without the integrations it does not use;
  a missing or failing one never blocks it (ADR-0023).
- **Never weaken a sensor.** Do not delete, skip or loosen a test or check to make it pass.
  Do not add a dependency without a reason in the plan.
- **Done means checked.** Run the checks before marking a task done. If the same check fails
  twice on the same error, stop, show the exact error, propose the fix and wait.
- **Maker is not checker.** After implementing, run Spec Kit's converge step and an
  independent review of the diff in a fresh context before opening the pull request.
- **Hand off in files, not chat.** Record progress in the feature's `tasks.md` and new open
  questions in `docs/PLAN.md` §9.

## How work is done here

Spec-Driven Development with GitHub Spec Kit (ADR-0008):

- **Feature, or a change in specified behavior** → `specify` → `clarify` → `plan` →
  `tasks` → `analyze` → `implement` (Spec Kit commands). Each feature lives in
  `specs/NNN-slug/`, on a `feat/NNN-slug` branch.
- **Fix, chore or docs** → a plain pull request; update the spec in the same pull request if
  behavior changes.
- **Cross-cutting decision** → an ADR in `docs/adr/`, from `template.md`.
- Tests are mandatory and come first. Skills also need eval cases traced to the acceptance
  scenarios of their spec (ADR-0013).

## Stack and conventions

- Python ≥ 3.13 + uv for the daemon; ruff (format and lint), mypy strict, pytest.
- Claude Code plugin layout for skills, subagents and hooks; the repo is its own
  marketplace. Skills follow the Agent Skills specification (ADR-0009).
- Conventional Commits. End agent-assisted commits with `Assisted-by: <agent/model>`.
- License: Apache-2.0.

## Repository map

- `.specify/`: Spec Kit (constitution, templates, scripts, git extension).
- `.claude/settings.json`: permission gates (rule 5) and development hooks (ADR-0018). Do
  not loosen them.
- `docs/PLAN.md`, `docs/adr/`: plan and decisions.
- `src/opscout/` and `tests/`: the Python package and its tests. `src/opscout/data/identity/`
  holds the read-only identity's reference documents and the AWS records they are proved
  against (spec 010). `plugins/opscout/`: the
  plugin, listed by `.claude-plugin/marketplace.json`: `bin/opscout` runs the engine
  (ADR-0022), `.mcp.json` starts the read-only tool server, `opscout mcp` (spec 011),
  `hooks/hooks.json` holds the push guard (spec 004) and the SSO check (spec 005),
  `skills/` holds the skills, and `evals/` their eval cases (ADR-0013).
- `evals/`: engine-side evaluation data: `evals/standup/` (spec 009), and `evals/mcp/`, the
  tool server's mock-mode fixtures and alert corpus (spec 011).
- `tools/`: this repository's development hooks and checks, including the headless eval
  runner `tools/skill_evals.py` and `tools/identity_refresh.py`, which refreshes the
  identity's AWS records; not shipped.
- `specs/`: the Spec Kit features. `schemas/config.schema.json`: the configuration's JSON
  Schema, generated from the models (`uv run just schema`). `example-config/`: a valid
  configuration with fake values. `.pre-commit-hooks.yaml`: the hooks a private configuration
  repository (spec 002) and an infrastructure repository (spec 010) use.
- Planned (PLAN.md §6): `deploy/`.
