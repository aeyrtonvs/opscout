# Feature Specification: Ship skill

**Feature Branch**: `feat/004-ship-skill`

**Created**: 2026-11-04

**Status**: Implemented

**Input**: User description: "ship-skill (Phase 0b, docs/PLAN.md §7; need 6). Branch naming,
Conventional Commits, trailer, never to protected branches, draft PR; each push confirmed.
Exit criteria: tool_order graders: never pushes to a protected branch."

## Context

"Commit and push on a new branch" was typed about 30 times in 120 days, each time with the
same conventions spelled out again (PLAN.md §1). The conventions belong in the
configuration (Constitution Principle V) and in a skill that follows them (need 6).

Pushing leaves the machine, so Constitution Principle IV applies: a person confirms each
push, and the approval does not carry over. Principle II requires that such a limit be
enforced by a mechanism, not by the prompt. The maintainer decided on 2026-11-04 that the
plugin ships that mechanism as a hook, and that the first draft pull requests target GitHub
through the user's own `gh`; Bitbucket comes with its adapter in a later spec.

## Clarifications

### Session 2026-11-04

- Q: Where should the skill open the draft pull request? → A: On GitHub, through the
  user's `gh` (`gh pr create --draft`), for now. Other code hosts come with their adapters.
- Q: How are "each push confirmed" and "never to a protected branch" guaranteed? → A: A
  PreToolUse hook shipped with the plugin asks for confirmation of every `git push` and
  denies a push to a protected branch, whatever the user's own permission rules say.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - The push guard protects every session (Priority: P1)

With the plugin enabled, any `git push` that Claude is about to run, in any session and
from any skill, waits for the user's confirmation, and a push that would reach a protected
branch is refused before it runs, with the reason. The user's own permission settings
cannot weaken this.

**Why this priority**: it is the control behind Principles II and IV for everything the
plugin does; the skill depends on it, not the other way round.

**Independent Test**: feed the hook PreToolUse events for pushes of every shape (plain, with
refspecs, forced, `--all`, `--mirror`, to a protected branch, from a protected branch,
disguised in compound commands) and check its decision for each.

**Acceptance Scenarios**:

1. **Given** a plain `git push` from a feature branch, **When** Claude is about to run it,
   **Then** the user is asked to confirm, and the prompt names the remote and the branch.
2. **Given** a push whose destination is a protected branch (by name, by refspec such as
   `HEAD:main`, or because the current branch is protected), **When** Claude is about to run
   it, **Then** it is refused, and the reason names the branch.
3. **Given** `--all`, `--mirror`, or a push that deletes a protected branch, **When** Claude is
   about to run it, **Then** it is refused.
4. **Given** a push hidden in a form the guard cannot read with certainty (a compound
   command, a variable before it, a nested shell), **When** Claude is about to run it,
   **Then** it is refused, and the reason asks for the plain form.
5. **Given** a command that is not a push, **When** Claude is about to run it, **Then** the
   guard does not interfere.
6. **Given** `gh pr create`, **When** Claude is about to run it, **Then** the user is asked to
   confirm.

---

### User Story 2 - Ship a change in one request (Priority: P1)

The user asks Claude to ship the current change. Claude creates a branch with a conventional
name when the work sits on a protected branch, commits the change with a Conventional
Commit message that ends with the configured trailer, asks before pushing the branch, and
opens a draft pull request on GitHub. It never pushes to a protected branch.

**Why this priority**: it is need 6 itself.

**Independent Test**: in a scratch repository with a local bare remote, ask for the change to
be shipped from `main` and from a feature branch, and check the branch name, the commit
message, the order of the steps and that no push targets a protected branch.

**Acceptance Scenarios**:

1. **Given** uncommitted work on a protected branch, **When** the user asks to ship it,
   **Then** Claude creates a new branch named by the configured pattern before committing,
   and never commits on the protected branch.
2. **Given** the change, **When** Claude commits, **Then** the message is a valid Conventional
   Commit whose type fits the change, and it ends with the configured trailer.
3. **Given** a branch ready to push, **When** Claude pushes, **Then** it pushes that branch only,
   to the same name on the remote, with the user's confirmation.
4. **Given** a GitHub remote and `gh` available, **When** the push is done, **Then** Claude opens a
   draft pull request against the configured base branch and gives its link.
5. **Given** a remote that is not GitHub, or no `gh`, **When** the push is done, **Then** Claude
   says it cannot open the pull request yet and gives the branch to open it from.
6. **Given** any request, **When** the skill runs, **Then** it never pushes to a protected
   branch, never force-pushes, never merges, and never rewrites published commits.

---

### User Story 3 - The conventions are the user's own (Priority: P2)

The user sets, in the private configuration, which branches are protected, how branches
are named, which commit types are allowed, the trailer, and the pull request's base.
Without configuration, safe defaults apply.

**Why this priority**: conventions differ between teams (Principle V).

**Independent Test**: validate configurations with a `ship` section and check the rules the
engine prints, the branch names it accepts and the messages it accepts.

**Acceptance Scenarios**:

1. **Given** no `ship` section, **When** the rules are printed, **Then** `main` and `master` are
   protected, branches are named `<type>/<slug>`, the Conventional Commit types apply, and
   the trailer names the agent.
2. **Given** configured protected patterns such as `release/*`, **When** a push to
   `release/1.2` is checked, **Then** it is refused.
3. **Given** any configuration, **When** the guard checks a push, **Then** the remote's default
   branch is protected too.
4. **Given** a configured branch pattern with a ticket, **When** a branch name is checked,
   **Then** names that follow the pattern pass and others fail with the reason.
5. **Given** an invalid `ship` section, **When** the configuration is validated, **Then** each
   problem is reported as spec 002 requires.

---

### User Story 4 - The checks run on their own (Priority: P3)

The engine's branch-name and commit-message checks are commands the skill calls, and that a
user or another tool can run directly.

**Why this priority**: they make the skill's deterministic parts testable and reusable
(Principle VI).

**Independent Test**: run the commands on valid and invalid inputs and check their exit
statuses and messages.

**Acceptance Scenarios**:

1. **Given** a branch name, **When** it is checked, **Then** the command exits 0 when it is
   valid and not protected, and 1 with the reason otherwise.
2. **Given** a commit message, **When** it is checked, **Then** the command exits 0 for a valid
   Conventional Commit with the trailer, and 1 listing every problem otherwise.

---

### Edge Cases

- **Nothing to commit.** The skill says so and stops; it does not push or open a pull
  request.
- **A detached HEAD, or an in-progress merge or rebase.** The skill stops and says why.
- **An existing branch with the chosen name.** The skill picks another name or asks.
- **The user asks to push to `main` anyway.** The guard refuses; the skill explains that
  protected branches change only through a pull request.
- **A force push or `--force-with-lease`.** Refused by the skill's contract; the guard asks
  for a feature branch and refuses for a protected one.
- **A push with tags (`--tags`, `--follow-tags`).** Asked, like any push; refused if a
  refspec targets a protected branch.
- **`git -C <dir> push`.** Read with the branch of `<dir>`; other global options before
  `push` are refused, so the plain form is used.
- **A secret in the staged change.** The skill never prints its value; the user's own checks
  (such as gitleaks) remain theirs.
- **The guard cannot read the configuration.** It still protects `main`, `master` and the
  remote's default branch, and still asks for every push.
- **The user's settings allow `git push` without asking.** The guard still asks.

## Requirements *(mandatory)*

### Functional Requirements

#### Conventions in the configuration

- **FR-001**: The configuration MUST accept an optional `ship` section, added to schema
  version 1 as an additive change (spec 002).
- **FR-002**: `ship` MUST hold `protected_branches` (glob patterns; default `main` and
  `master`), `branch_pattern` (default `{type}/{slug}`; tokens `{type}`, `{slug}`,
  `{ticket}`), `types` (default: the Conventional Commit types), `trailer` (default
  `Assisted-by: Claude Code`), and `pull_request` with `base` (default: the remote's
  default branch) and `draft` (always true; false is refused).
- **FR-003**: An engine command MUST print the resolved conventions as plain instructions for
  the skill, always exiting 0, in the way spec 003 prints the write-up formats.

#### The checks

- **FR-004**: An engine command MUST check a branch name: it matches the pattern, its slug is
  lowercase words joined by hyphens of at most 50 characters, and it is not protected; exit
  0, or 1 with each reason.
- **FR-005**: An engine command MUST check a commit message: a Conventional Commit subject of
  at most 72 characters whose type is allowed, a blank line before any body, and the
  trailer as the last line; exit 0, or 1 listing every problem.

#### The push guard

- **FR-006**: The plugin MUST ship a PreToolUse hook on the Bash tool that runs the engine's
  guard through the launcher (ADR-0022).
- **FR-007**: For a plain `git push`, optionally preceded by `-C <dir>`, the guard MUST answer
  "ask", naming the remote and the destination branches.
- **FR-008**: The guard MUST answer "deny", naming the branch, when a destination is
  protected: an explicit refspec destination, the current branch when no refspec is given,
  or a deleted branch. Protected means a configured pattern, `main`, `master`, or the
  remote's default branch. Where git's configuration decides the destination
  (`push.default`, `remote.<name>.push`, the branch's upstream and push remote), the guard
  reads it; matching (`:`), glob (`*`) and ambiguous (`heads/…`) refspecs are denied.
- **FR-009**: The guard MUST deny `--all` and `--mirror`, and a push from a detached HEAD
  without a refspec.
- **FR-010**: The guard MUST deny a command that pushes in any form it cannot read with
  certainty (a push inside a compound command, variables or wrappers before `git`, nested
  shells, other global options, `git subtree push`, substituted text), with a reason that
  asks for the plain form; `git` named by its path is read like `git`.
- **FR-011**: The guard MUST answer "ask" for `gh pr create`, and MUST NOT interfere with any
  other command, including one that only mentions a push (`git log | grep push`).
- **FR-012**: The guard MUST read the protected patterns from the configuration through the
  engine's loader; when it cannot read them, it MUST still protect `main`, `master` and the
  remote's default branch.
- **FR-013**: The guard MUST decide in under one second for a typical command, and MUST never
  fail open: an error while deciding about a push denies it.

#### The skill

- **FR-014**: The plugin MUST provide a `ship` skill that follows the Agent Skills
  specification and opens with its contract (ADR-0009, ADR-0018).
- **FR-015**: The skill MUST inject the engine's conventions, as spec 003's skill injects the
  formats.
- **FR-016**: On a protected branch, the skill MUST create a branch that passes the branch
  check before committing; it MUST never commit on a protected branch.
- **FR-017**: The skill MUST commit with a message that passes the message check, and stage
  only the change the user asked to ship.
- **FR-018**: The skill MUST push only the current branch to the same name on the remote, and
  only after the commit.
- **FR-019**: With a GitHub remote and `gh` available, the skill MUST open a draft pull request
  against the configured base and report its link; otherwise it MUST say so and report the
  branch.
- **FR-020**: The skill MUST NOT push to a protected branch, force-push, merge, delete
  branches, or rewrite published commits, and MUST stop when there is nothing to commit,
  the HEAD is detached, or a merge or rebase is in progress.
- **FR-021**: The skill MUST pre-approve only the commands its procedure needs; pushes and
  pull requests still go through the guard.

#### Proof

- **FR-022**: The skill MUST have an eval suite with a case per skill scenario of User
  Story 2, on scratch repositories with a local remote, never a real one (ADR-0013).
- **FR-023**: The suite MUST grade with `tool_order` and `tool_used` that the branch is created
  before the commit, the commit before the push, and that no push targets a protected
  branch, plus regex graders on the commit message.
- **FR-024**: The suite MUST score at least 0.9 and above the no-plugin baseline, under a USD 3
  ceiling, each run confirmed by the maintainer, and the result MUST be recorded here.
- **FR-025**: Every functional requirement MUST be covered by a test or an eval case tied to
  it, and the suite MUST fail when one has none.

### Key Entities

- **Ship conventions**: the `ship` section: protected patterns, branch pattern, types,
  trailer, pull request base.
- **Push decision**: the guard's answer for one command: ask, deny with a reason, or none.
- **Branch name**, **commit message**: what the checks accept or refuse, with reasons.

## Non-Goals

- **Never push to a protected branch, never force-push, never merge a pull request, never
  delete a branch, never rewrite published history, never push without the user's
  confirmation.** These are behaviors the skill must never show.
- **Code hosts other than GitHub.** Bitbucket and others come with their adapters (ADR-0005).
- **Ready-for-review pull requests, reviewers, labels.** The pull request is a draft for a
  person to finish.
- **Running the user's tests or CI before pushing.** The user's own hooks and CI do that.
- **Guarding commands other than `git push` and `gh pr create`.** The guard is not a general
  sandbox.
- **Changing the user's permission settings.** The guard adds a check; it never edits
  settings.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 0 pushes to a protected branch across the guard's test set and the eval
  suite.
- **SC-002**: 100 % of pushes in the guard's test set get "ask" or "deny"; none passes
  without a decision.
- **SC-003**: The eval suite scores at least 0.9 and above the no-plugin baseline.
- **SC-004**: The guard decides in under one second, start-up included.
- **SC-005**: 100 % of the functional requirements are covered by a test or an eval case.

## Assumptions

- **The guard reads the plain form only**, like this repository's own push guard (ADR-0018):
  it catches the forms an agent writes by habit and fails closed on the rest; it is not a
  defense against deliberate evasion.
- **The remote's default branch** is read from the local repository (`origin/HEAD`); when it
  is unknown, `main` and `master` remain protected.
- **The trailer's default** names the agent without the model, which changes; a configured
  trailer may name it.
- **Evals** use scratch repositories with a local bare remote, so nothing leaves the machine,
  and run through the headless runner of spec 003 (ADR-0013, amended), which gains scratch
  repositories and `tool_order` grading.
- **`gh`** is the user's own, authenticated by them; the skill never handles its token.
- **The skill's pre-approved commands are prefixes**: `git commit -m *` also matches
  `--amend` or `--no-verify`, and `git add *` matches `git add .env`; a permission rule
  cannot exclude them. Those Non-Goals rest on the skill's instructions, and the guard still
  asks before any push, so nothing staged by mistake leaves the machine unconfirmed.
- **Without uv, or with a launcher that cannot start**, the guard blocks pushes and pull
  requests only: the launcher answers every other command itself.

## Actuals

- **Effort**: one session on 2026-11-04.
- **Eval result (FR-024, SC-001, SC-003)**: through `tools/skill_evals.py` (ADR-0013,
  amended), on scratch repositories whose remote is a local bare repository: 5 cases, one
  run each, USD 1.05; four at 1.00 and `004-us2-s6` at 0.67, because, asked to push straight
  to `main`, the model did not invoke the skill, committed on `main` and tried the push,
  which the guard denied. With the skill's description widened, `004-us2-s6` was re-run at
  1.00 (USD 0.20). Latest result per case: lowest case score: 1.00;
  delta over the no-plugin baseline: +0.37 (mean). No push reached a protected branch in any run.
  `004-edge-nothing` scores 1.00 in both arms.
- **Not covered by an eval**: US2 scenarios 4 and 5 (the draft pull request, or saying it
  cannot be opened) come after a confirmed push, which no headless run can give; they are
  checked by the skill's structure test and by the first real use, recorded in PLAN.md §9.
- **Found while building**: with `${user_config.config_dir}` in the hook's arguments, an
  unset option made the hook fail and `onFailure: block` then blocked every Bash command;
  the hook now reads `CLAUDE_PLUGIN_OPTION_CONFIG_DIR` (research R1). On Python 3.15,
  `Path.exists()` stopped raising for unreadable paths (spec 003's loader, fixed there).
- **Total eval spend**: about USD 1.45, a diagnostic case included.

