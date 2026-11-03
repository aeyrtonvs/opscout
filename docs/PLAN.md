# opscout — plan

> Status (2026-11-03): **Phase 0a in progress**; finished steps are marked done in §7. The
> constitution is ratified (1.0.2), ADRs 0001–0021 are accepted, Spec Kit 1.2.6 is
> initialized, the rule-5 gate is in place (`.claude/settings.json`), and commits are signed
> with SSH from the GitHub no-reply address. The project is named **opscout** (ADR-0019).
> Company-specific facts behind this plan live in the private config repo
> (its `CLAUDE.md`), never here.

## 0. Planning documents

| Layer | Where | Answers | Changes |
|---|---|---|---|
| Principles | [`.specify/memory/constitution.md`](../.specify/memory/constitution.md) | What is never negotiable | By amendment pull request |
| Decisions | [`docs/adr/`](adr/README.md) | Why the architecture is this way | When a decision is made or superseded |
| Plan | this file | What is built, for which need, in which order | Each phase |
| Feature spec | `specs/NNN-slug/spec.md` | What one feature must do, testably | Per feature |
| Feature design | `specs/NNN-slug/plan.md`, `research.md`, `contracts/` | How that feature is built | Per feature |
| Work | `specs/NNN-slug/tasks.md` | Ordered, traceable tasks | During implementation |
| Proof | `tests/`, `plugins/opscout/evals/` | That it does what the spec says | With the code |

`AGENTS.md` (every coding agent) and `CLAUDE.md` (Claude Code) point here.

## 1. The problem, measured

Mined from one engineer's Claude Code prompt history (6,477 prompts in 120 days):

| Repeated work | Approx. count | What gets retyped |
|---|---|---|
| Pasting an alert and asking "real or tune the threshold?" | 18+ since July | The question, the alert's timezone, which account and profile, how to reach the cluster |
| Teammates' questions relayed from chat ("is variable X configured?", "we got this report, is everything OK?") | ~60 prompts | Context they could have looked up themselves |
| SSO login | ~120 | The same command — root cause: 9 SSO sessions pointing at one portal |
| Changing effort level by hand | ~240 | The picker, every session |
| "commit and push on a new branch" | ~30 | Branch naming and commit conventions |
| "short summary, ready to paste into a ticket or a message" | 10+ | The format, then corrections ("don't list what was ruled out") |
| Not remembering yesterday's work at the daily standup | daily | — |

## 2. Agreed needs

| # | Need | Phase 1–2 (user invokes) | Later (runs on its own) |
|---|---|---|---|
| 1 | Ops alert triage (5xx, DB, WAF, CrashLoop) | Verdict real/false positive, cause with evidence, threshold assessment, **draft** ticket | Chosen alerts trigger it; reply in the alert's thread |
| 2 | Cost alert triage | Investigates only alerts with an ID and red rows, only for in-scope accounts; reports the rest as fired-but-out-of-scope | Reads the cost channel on its own |
| 3 | Teammates' questions | User mentions the bot in the thread; it answers there | Team asks it directly |
| 4 | Daily standup | Arrives on its own 15 min before the standup: yesterday by project, today, blockers. Monday covers Fri–Sun | — |
| 5 | Write-ups | Fixed format for tickets and messages | — |
| 6 | Friction | SSO check, effort per skill, commit-and-push | — |

Out of the first round: "watch this after the apply" monitoring.

Constraints: read-only always; never a secret's value; nothing applied live. Sources: IaC
and app repos, the cloud accounts, the observability platform, hosts and clusters.

## 3. Decisions

Every decision is an ADR in [`docs/adr/`](adr/README.md). The decisions this table held on
2026-11-03 were migrated unchanged (0002–0007); the rest were proposed and accepted the same
day.

| ADR | Decision | Status |
|---|---|---|
| [0001](adr/0001-record-architecture-decisions.md) | Record architecture decisions as MADR files | accepted |
| [0002](adr/0002-public-engine-private-config.md) | Public engine; config in a separate **private** repo read from a path or env var; `example-config/` as template | accepted |
| [0003](adr/0003-plugin-marketplace-and-daemon.md) | Claude Code plugin, repo as its own marketplace, **+** a separately installed daemon | accepted |
| [0004](adr/0004-python-uv.md) | Python + uv for the daemon | accepted |
| [0005](adr/0005-ports-and-adapters.md) | Adapter interfaces (alerts, costs, code host, tickets, chat); implemented: AWS, Datadog, Bitbucket, Jira, Slack | accepted |
| [0006](adr/0006-local-macos-first.md) | Runs locally (phases 0–2); macOS first (launchd) behind a scheduler interface; team-wide automation stays out of this repo | accepted |
| [0007](adr/0007-english-apache-2.md) | English; Apache-2.0 | accepted |
| [0008](adr/0008-spec-driven-development-spec-kit.md) | Spec-Driven Development with GitHub Spec Kit, spec-anchored | accepted |
| [0009](adr/0009-open-standards-agent-artifacts.md) | AGENTS.md, Agent Skills and MCP as the formats for agent-facing artifacts | accepted |
| [0010](adr/0010-defense-in-depth-read-only.md) | Read-only in five layers: identity, tool surface, output channel, redaction, interactive guard | accepted |
| [0011](adr/0011-code-led-tools-mcp-server.md) | Deterministic adapters exposed as a local read-only MCP server and a CLI | accepted |
| [0012](adr/0012-runner-port-claude-cli.md) | Runner port; the user's own `claude -p` is the default runner (answers open item 1) | accepted |
| [0013](adr/0013-evals-as-acceptance-tests.md) | Evals are the acceptance tests of agent behavior | accepted |
| [0014](adr/0014-configuration-contract.md) | Configuration contract: versioned schema, validated in both repos | accepted |
| [0015](adr/0015-leak-prevention-tooling.md) | Leak prevention by tooling, with the deny-list kept private | accepted |
| [0016](adr/0016-engineering-baseline.md) | Engineering baseline: gates, supply chain, lockstep releases | accepted |
| [0017](adr/0017-docs-as-code.md) | Docs as code: Diátaxis, Zensical, Mermaid | accepted |
| [0018](adr/0018-harness-engineering-practices.md) | Harness-engineering practices: dual-encoded rules, contracts with non-goals, sensors, bounded convergence, evidence grounding, maker/checker | accepted |
| [0019](adr/0019-project-name-opscout.md) | The project is named opscout; the working name ops-harness is retired | accepted |
| [0020](adr/0020-toolchain-pinned-through-uv.md) | Development toolchain pinned through uv (`dev` group, pre-commit revs); prerequisites are git, uv and Claude Code; neither local use nor development needs containers | accepted |
| [0021](adr/0021-local-first-portable-by-construction.md) | Local-first, portable by construction: host-specific code behind ports, scheduled jobs as idempotent commands; the foreseen hosted shape is a personal VM, not serverless | accepted |

## 4. How it is built: spec-driven

### 4.1 Flow

```mermaid
flowchart TD
  change[Change] --> kind{What kind?}
  kind -- "feature or change in specified behavior" --> specify["/speckit-specify<br/>spec.md"]
  specify --> clarify["/speckit-clarify"]
  clarify --> plan["/speckit-plan<br/>plan.md · research.md · contracts/<br/>Constitution Check"]
  plan --> tasks["/speckit-tasks<br/>tasks.md"]
  tasks --> analyze["/speckit-analyze<br/>cross-artifact consistency"]
  analyze --> implement["/speckit-implement<br/>tests and evals first"]
  implement --> converge["/speckit-converge<br/>code vs spec, plan, tasks"]
  converge --> review["Independent review<br/>fresh context, spec + constitution"]
  kind -- "fix, chore, docs" --> pr
  kind -- "cross-cutting decision" --> adr["ADR in docs/adr/"]
  review --> pr["Pull request<br/>all gates green"]
  adr --> pr
  pr --> main[(main)]
```

The spec stays in `specs/NNN-slug/` after merge as the reference for that feature
(spec-anchored, ADR-0008). Branches: `feat/NNN-slug` for specs, `fix/`, `chore/`, `docs/`
otherwise. Every spec has a mandatory Non-Goals section; a plain pull request states its
deliverable, constraints, non-goals and acceptance in the template (ADR-0018).

### 4.2 Traceability

Spec Kit gives each spec stable IDs: user stories (`US1`…), functional requirements
(`FR-001`…) and success criteria (`SC-001`…). They are carried forward:

- tasks reference stories and requirements (`T012 [US1] … FR-003`);
- tests carry a marker: `@pytest.mark.spec("003", "FR-002")`;
- eval cases are named after the scenario they prove: `003-us1-s2`;
- pull requests link their `specs/NNN-slug/`.

### 4.3 Definition of done (per spec)

- No `[NEEDS CLARIFICATION]` left; `/speckit-analyze` reports no critical findings.
- Every FR is covered by a test or an eval case; every acceptance scenario of a skill has an
  eval case.
- All gates green (4.4); eval suite at or above its threshold and baseline.
- Docs updated; an ADR written if the architecture changed.
- Actual effort recorded in the spec, to recalibrate the estimates in §7.

### 4.4 Gates

| Gate | Local (pre-commit, `just check`) | CI |
|---|---|---|
| Format and lint (ruff) | ✓ | ✓ |
| Types (mypy `--strict`) | ✓ | ✓ |
| Tests (pytest), coverage gate on `core` and `services` | ✓ | ✓ macOS + Linux, Python 3.13 and latest |
| Import contracts (import-linter) | ✓ | ✓ |
| Leak check: generic patterns / private deny-list / commit e-mail | ✓ / ✓ / ✓ | ✓ / — / ✓ |
| Secret scan (gitleaks) | ✓ | ✓ plus GitHub push protection |
| Plugin and marketplace validation (`claude plugin validate --strict`) | ✓ | ✓ |
| `example-config/` against the schema | ✓ | ✓ |
| Evals (`claude plugin eval`) | before each release | on demand, with a cost ceiling |
| CodeQL, dependency review, zizmor, OpenSSF Scorecard | — | ✓ |
| Outward-facing commands (rule 5): `ask` rules in `.claude/settings.json` | ✓ in place; denies in headless runs | — |
| Dev-time sensors (Claude Code hooks): ruff after each Python edit; fast checks before the agent stops, blocking once | ✓ (Phase 0a) | — |

Every hard rule is dual-encoded: stated in AGENTS.md and blocked by one of the gates above
(ADR-0018). A rule without a gate is an open item in §9.

## 5. Architecture overview

```mermaid
flowchart LR
  user(["Engineer"])
  team(["Teammates"])
  subgraph mac["Engineer's machine"]
    cc["Claude Code<br/>user's own login"]
    subgraph plugin["Plugin: opscout"]
      skills["Skills<br/>summary · ship · daily<br/>alert-triage · cost-triage · ask"]
      subagents["Subagents<br/>metrics · logs · changes · config drift"]
      hooks["Hooks<br/>sso-check · redaction · mutation guard"]
    end
    mcp["MCP server<br/>read-only typed tools"]
    daemon["Daemon, launchd<br/>scheduler · chat gateway · runner · run log"]
    keychain[("OS keychain")]
    config[("Private config repo")]
  end
  subgraph ext["External systems, through the read-only identity"]
    cloud["Cloud accounts"]
    obs["Observability"]
    code["Code host"]
    tickets["Tickets"]
    hosts["Clusters and hosts<br/>allow-listed documents"]
  end
  chat["Chat<br/>Socket Mode"]

  user --> cc
  cc --> skills
  skills --> subagents
  skills --> mcp
  subagents --> mcp
  mcp --> cloud & obs & code & tickets & hosts
  mcp --> config
  daemon -- "claude -p, restricted profile" --> cc
  daemon --> config
  daemon --> keychain
  daemon <--> chat
  team --> chat
```

- **Plugin.** Skills fix each procedure; investigation skills fan out subagents in parallel
  and then synthesize. Each skill sets its own `effort` (and `model` where it helps).
- **`opscout` package.** Core domain and ports, adapters, and three entry points: the
  CLI, the MCP server (stdio, read-only tools) and the daemon (ADR-0011).
- **Daemon.** Scheduler, chat gateway in Socket Mode (no public endpoint), a runner that
  starts the user's own `claude -p` with a restricted profile (ADR-0012), and the run log.
- **Trust boundary.** Alert bodies, logs and chat threads are untrusted input. They reach the
  model only through tools that run under the read-only identity, and replies leave only to
  the originating thread or the user's DM (ADR-0010).
- **Verification.** Each verdict cites evidence that the harness checks in code against the
  tool outputs of the same run. Outputs are validated against their schema, with one retry
  before the run ends as `inconclusive` and goes to the user. Investigations may add a
  skeptic pass if evals show it pays off (ADR-0018).
- **Portability.** Local-first, not local-only (ADR-0021). Host-specific code sits behind
  ports (scheduler, secret store, run store, runner), and scheduled jobs are idempotent
  commands. Linux, Windows or an always-on personal VM each become an adapter, built when it
  has a user.

Three flows:

1. **Interactive.** The user invokes a skill in Claude Code → subagents → MCP tools → an
   answer or a draft.
2. **Scheduled (daily).** launchd → the daemon gathers the sources in code → a headless run
   with no tools at all → DM.
3. **Mention.** A mention in a thread → allow-list check → routing → a headless run with MCP
   tools only → reply in the thread → the user's agreement goes to the run log.

## 6. Repository layout (target)

```text
opscout/
├── .claude-plugin/marketplace.json   # the repo is its own marketplace
├── plugins/opscout/                  # what users install
│   ├── .claude-plugin/plugin.json    # version, userConfig (config directory)
│   ├── skills/<name>/SKILL.md        # Agent Skills format (+ references/, scripts/)
│   ├── agents/                       # subagents for the investigation skills
│   ├── hooks/hooks.json              # sso-check, redaction, mutation guard
│   ├── .mcp.json                     # starts the opscout MCP server
│   └── evals/<case>/                 # claude plugin eval suites
├── src/opscout/                      # core/ services/ adapters/ entrypoints/
├── tests/                            # unit/ contract/ integration/
├── schemas/config.schema.json        # generated from the config models
├── example-config/                   # fake values, validated in CI
├── deploy/                           # reference IAM policies, Slack app manifest, launchd template
├── specs/NNN-slug/                   # Spec Kit features
├── docs/                             # PLAN.md, adr/, tutorials/, how-to/, reference/, explanation/
├── .specify/                         # Spec Kit: constitution, templates, scripts, extensions
├── .claude/skills/speckit-*          # dev-time skills for working on this repo (not shipped)
├── .github/                          # workflows/, ISSUE_TEMPLATE/, PR template, CODEOWNERS, dependabot.yml
├── AGENTS.md  CLAUDE.md  README.md  CONTRIBUTING.md  SECURITY.md  CODE_OF_CONDUCT.md
├── LICENSE  NOTICE  CHANGELOG.md
└── pyproject.toml  uv.lock  .python-version  justfile  .pre-commit-config.yaml  release-please-config.json
```

## 7. Roadmap

Spec Kit assigns spec numbers when each spec is created; the order below is the plan.
Estimates are rough and are recalibrated after the first two specs (actuals go in each spec).

### Phase 0a — engineering bootstrap (no spec; ≈1–2 days)

The order matters: commit identity comes before the first commit.

1. Repo-local commit identity and commit signing (done 2026-11-03: GitHub no-reply e-mail,
   SSH signing with a dedicated key; the key is registered on GitHub in step 8).
2. Ratify the constitution and accept the ADRs (done 2026-11-03).
3. Repository skeleton and governance files (ADR-0016); `AGENTS.md` and `CLAUDE.md`. The pull
   request template also asks whether new host-specific code sits behind a port (ADR-0021).
4. Python project: `pyproject.toml` (uv), the package layers of ADR-0011, one smoke test,
   `justfile`. The whole toolchain is pinned through uv (ADR-0020): a `dev` dependency group
   (ruff, mypy, pytest, import-linter, pre-commit, rust-just, zizmor),
   `.python-version`, and `[tool.uv] required-version`. A clone is set up with `uv sync`
   and `uv run just setup`; nothing else is installed globally. ruff enables `PTH`, and the
   import-linter contracts include ADR-0021's rule that platform adapters are imported only
   by the composition root.
5. Plugin skeleton: marketplace and plugin manifests, with `userConfig` for the config
   directory; `claude plugin validate --strict` passes.
6. Gates: pre-commit with gitleaks and actionlint (upstream hooks pinned by `rev`) and the
   generic leak patterns; CI workflows with pinned actions that install only uv and run
   `uv sync --locked` (ADR-0020).
7. Development harness (ADR-0018), with hook scripts in Python run through uv (ADR-0021):
   - the rule-5 `ask` rules, already in place;
   - a PreToolUse hook for the push forms those rules miss (`git -C … push`, `git -c … push`);
   - a PostToolUse ruff hook, and a Stop hook that runs the fast checks and blocks once;
   - path-scoped `.claude/rules/` for skills, Python code and specs, so each loads only when
     its files are touched; the Python rule states ADR-0021's portability rules.
8. Create the GitHub remote and push, and register the SSH signing key on GitHub, each
   confirmed by the maintainer.

Exit: `just check` green on a fresh clone set up with only git, uv and Claude Code; CI green
on the first push; the first commit reviewed for real data.

### Phase 0b — foundations

| Planned spec | Need | Delivers | Exit criteria |
|---|---|---|---|
| leak-guard | rules 1–2 | Private deny-list and commit e-mail check on top of the generic patterns (ADR-0015) | Every synthetic leak in the test set is caught; < 1 s on a typical diff |
| config-contract | all | Config models, JSON Schema, loader, `opscout config validate`, `example-config/` (ADR-0014) | Example and private configs validate; schema drift test |
| summary-skill | 5 | Write-up formats from config: ticket, message, postmortem; a contract whose non-goals include "never list what was ruled out" | Eval suite at threshold and above the no-plugin baseline |
| ship-skill | 6 | Branch naming, Conventional Commits, trailer, never to protected branches, draft PR; each push confirmed | `tool_order` graders: never pushes to a protected branch |
| sso-check-hook | 6 | SessionStart warning from the local SSO token cache, no network | Tests for valid, expired and missing cache; p95 < 100 ms |
| personal-context | 6 | Renders a marked section of `~/.claude/CLAUDE.md` from config; shows a diff and writes only on confirmation | Idempotent; content outside the markers untouched |

Outside this repo (private runbook): consolidate the SSO sessions into one (back up first,
show the diff, wait for approval).

### Phase 1 — daily standup and chat output

| Planned spec | Need | Delivers | Exit criteria |
|---|---|---|---|
| daemon-core | 4 | Jobs as idempotent `opscout run` commands; scheduler port with the launchd adapter (install, uninstall); Runner port with `ClaudeCliRunner`; `RunStore` (run log); `SecretStore` with `keyring` (ADR-0021) | Restricted profile verified from the `system/init` event; idempotent install; a job triggered twice for the same period delivers once |
| chat-output | 4 | Slack app manifest, Socket Mode, DMs only, agreement buttons | DM delivered; agreement stored in the run log |
| daily-standup | 4 | Sources gathered in code (sessions, commits and PRs, tickets); a tool-less run; Monday covers Fri–Sun; sent 15 min before the standup | Evals on synthetic histories; a week of dailies delivered; agreement ≥ 80 % |

### Phase 2 — investigation agents the user invokes

Hard dependency: runs against real systems need the read-only identity (open items). Until it
exists, development uses fixtures and MCP mocks.

| Planned spec | Need | Delivers | Exit criteria |
|---|---|---|---|
| readonly-identity | 1–3 | Reference policies that deny secret-value APIs, Kubernetes `view` binding, allow-listed host command documents; fake IDs only | Policy checks: secret reads and mutations denied |
| ops-mcp-server | 1–3 | MCP server skeleton, redaction, mocks, and the first tools alert triage needs | Tool contract tests; the plugin starts the server |
| alert-triage | 1 | Skill with four parallel subagents (metrics, logs/traces, recent changes, declared vs deployed config); structured verdict with checked evidence, assumptions and the timezone used; draft ticket | Evals on synthetic alerts (public) and real samples (private); a skeptic pass ships only with an ablation result |
| cost-triage | 2 | Cost-alert parser from config, scope filter, breakdown by service and usage type, audit trail | Every fixture parsed; out-of-scope alerts reported as fired, out of scope |
| ask | 3 | "Is X configured?" and "is everything OK?" from IaC and deployed config | Secret-value bait cases never return a value |
| thread-bot | 3 | Mentions in threads, allow-list, routing, reply in the thread | Injected instructions do not change the tool list; only allow-listed users get answers |
| run-insights | — | Agreement rate, cost and latency per skill; disagreed runs exported as eval candidates | The report is the input for deciding Phase 3 |

Candidate, not committed: let alert triage see earlier verdicts for the same alert, since
recurrence informs "real or tune the threshold?". Only verdicts the user agreed with, with
their dates, to limit memory poisoning (OWASP ASI06).

### Phase 3 — unattended runs, gated by evidence (later)

Chosen alerts trigger triage on their own, the cost channel is read on its own, and
teammates ask the bot directly. Each step needs an ADR and run-log evidence (for example
≥ 90 % agreement over ≥ 30 runs). Team-wide automation stays out of this repo (ADR-0006).
Still out: "watch this after the apply" monitoring.

Hosting: if the unattended parts must run while the laptop is off, the foreseen shape is an
always-on personal Linux VM, not serverless. Its ADR supersedes the hosting part of ADR-0006
and starts from the delta list in ADR-0021.

## 8. Platform facts that shaped this

Checked 2026-11-02 (official docs):

- **Claude in Slack for teams (Claude Tag)** is Team/Enterprise only and runs in a cloud
  sandbox without the user's cloud credentials → not usable on a Max plan.
- **Claude Code in Slack** works with GitHub repos only.
- **Cloud scheduled tasks (routines)** cannot read local files (no access to the session
  history the daily needs); API keys as env vars are visible to anyone using the
  environment. Triggers: cron (≥ hourly), an HTTP API trigger, GitHub events.
- **Headless `claude -p`**: `--allowedTools`, `--permission-mode`, `--output-format`,
  `--json-schema`, `--max-turns`, `--max-budget-usd`, `--model`, `--effort`.
  `--bare` ignores OAuth/keychain and needs `ANTHROPIC_API_KEY`.
- **Skills frontmatter**: `model`, `effort`, `allowed-tools`, `context: fork` (+ `agent`,
  `background`), `disable-model-invocation: true` for user-only skills.
- **SessionStart hooks**: stdout on exit 0 is injected into context
  (`additionalContext` capped at 10,000 chars); non-zero exit does not block.

Checked 2026-11-03 (official docs and the local CLI, Claude Code 2.1.317):

- **Spec Kit 1.2.6** (2026-11-02): `--integration claude` installs skills in
  `.claude/skills/speckit-*`; the current feature is tracked in `.specify/feature.json`, so
  branch names are free; official extensions `git`, `github`, `agent-context`, `assess`,
  `bug`; 180+ community extensions, unreviewed; presets `lean` and `constitution-sync`; a
  release every few days.
- **Plugin manifest**: `userConfig` (types include `directory`; `sensitive` values go to the
  OS secure store), `dependencies`; `bin/` is added to the Bash tool's PATH;
  `${CLAUDE_PLUGIN_ROOT}` changes on update, `${CLAUDE_PLUGIN_DATA}` persists;
  `claude plugin validate [--strict]`; auto-update is off by default for third-party
  marketplaces.
- **Subagents shipped in a plugin** ignore `permissionMode`, `hooks` and `mcpServers`.
- **`claude plugin eval`**: cases in the plugin's `evals/`; graders `regex`, `tool_used`,
  `tool_order`, `file_exists`, `llm`, `baseline`; a no-plugin baseline arm; MCP mocks;
  `--threshold`, `--max-cost-usd`; CI credentials documented as an API key or cloud-provider
  credentials.
- **Headless, more flags**: `--tools ""` removes the built-in tools; `--restricted`;
  `--permission-mode dontAsk`; `--permission-prompts none`; since 2.1.302, `-p` without a mode
  denies anything that needs approval; the docs expect `--bare` to become the `-p` default.
- **Auth**: `claude setup-token` prints a one-year token for `CLAUDE_CODE_OAUTH_TOKEN`; the
  Agent SDK docs ask for an API key; policy quotes in ADR-0012.
- **Sandbox** confines Bash only; MCP servers and hooks run outside it; its behavior under
  `-p` is not documented.
- **Hooks**: types `command`, `http`, `mcp_tool`, `prompt`, `agent`; PostToolUse can replace
  the tool output the model sees.
- **Instructions files**: Claude Code reads `AGENTS.md` only when there is no `CLAUDE.md` or
  `CLAUDE.local.md` (2.1.277+); `@AGENTS.md` imports are the documented way to share one
  file; `CLAUDE.local.md` is supported for personal, git-ignored instructions.
- **Telemetry**: Claude Code exports OpenTelemetry metrics and events (cost, tokens, tool
  results).
- **Docs tooling**: Material for MkDocs gets critical fixes only until 2026-11-05; its
  successor is Zensical.
- **Python 3.15.0** was released on 2026-10-09 (secondary sources).
- **Permission rules**: `deny` and explicit `ask` rules apply even in `bypassPermissions`
  mode, and headless runs deny an `ask` (checked here: `git push --dry-run` was denied).
  `Bash(git push *)` also matches plain `git push`. Compound commands are matched per
  subcommand, but `git -C dir push` and `git -c key=value push` are not matched.
- **Settings** reload in a running session, including `permissions` and `hooks`.
- **Stop hook**: `stop_hook_active` marks a continuation; `decision: "block"` with a
  `reason`, or exit code 2, keeps the agent working; at most 8 consecutive continuations.
- **Path-scoped rules**: `.claude/rules/*.md` with `paths:` frontmatter load only when
  Claude reads or edits a matching file.
- **`claude plugin details`** shows a plugin's projected token cost as text only (no JSON),
  so it is a manual release check, not a CI gate.

Sources: code.claude.com/docs (plugins/manifest-reference, plugins/marketplace-reference,
plugin-evals, skills, sub-agents, cli-reference, headless, authentication, sandboxing, hooks,
memory, monitoring-usage), agentskills.io/specification, github.com/github/spec-kit releases,
genai.owasp.org (Top 10 for Agentic Applications).

## 9. Open items

- [x] Ratify the constitution (→ 1.0.0) and decide the proposed ADRs: ratified, and all
      accepted, on 2026-11-03.
- [ ] Rule-5 gate gaps: `git -C … push` and `git -c … push` escape the `ask` rules; a
      PreToolUse hook closes them (Phase 0a). Account connectors that also send data out
      (ticket and docs tools, artifact publishing) are not gated in this repo; decide whether
      rule 5 covers them.
- [x] **Before the first commit:** the global git e-mail is a work address. Done 2026-11-03:
      the repo-local `user.email` is the GitHub no-reply address.
- [x] Name: **opscout** (ADR-0019). The working name `ops-harness` was taken on PyPI by an
      unrelated project and collided with a CI/CD vendor's name. Re-check that `opscout` is
      still free on PyPI and GitHub right before the first push.
- [x] Runner (former item 1): ADR-0012 accepted. The user's own `claude -p` is the default
      runner; the Agent SDK is an optional API-key runner.
- [ ] Read-only identity (former item 2): the reference policies come from this repo
      (Phase 2); who applies them, and through which IaC repo, is still open.
- [x] GitHub account (former item 3): confirmed, the remote goes in `aeyrtonvs`.
- [ ] How the plugin finds the Python package (`uvx` with a pinned version, or `bin/`):
      decide in the MCP server's spec.
- [ ] Evals in CI need an API key with a cost ceiling: enable them, or keep evals local.
- [x] The local uv was 0.6.17 (April 2025): upgraded to 0.13.7 on 2026-11-03; ADR-0020 sets
      the floor in `pyproject.toml`.
- [x] ADR-0020 (toolchain pinned through uv) and ADR-0021 (local-first, portable by
      construction): accepted on 2026-11-03. ADR-0020 was corrected first: `actionlint-py`
      ships no wheels, so actionlint comes from its upstream pre-commit hook.
- [x] Constitution PATCH (→ 1.0.2): OS-specific code lives behind ports, such as the
      scheduler and the secret store, matching ADR-0011 and ADR-0021. Done 2026-11-03.
- [ ] Windows has no CI gate (ADR-0021): add a Windows job and the Task Scheduler adapter with
      the first Windows user.
- [ ] Re-verify §8 facts at implementation time; they change.
