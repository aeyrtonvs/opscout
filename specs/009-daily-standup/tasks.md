---
description: "Tasks for the daily standup (spec 009)"
---

# Tasks: Daily standup

**Input**: [spec.md](spec.md), [plan.md](plan.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/commands.md](contracts/commands.md),
[contracts/ports.md](contracts/ports.md), [quickstart.md](quickstart.md)

**Tests**: mandatory and first; `@spec("FR-0NN")` bound to `"009"`, one requirement per
decorator (the traceability test reads them). Fakes for the three ports; hand-written
samples that follow the documented shapes, with `example-*` values; no test reads real
transcripts, the real `claude` or Bitbucket.

## Phase 1: Setup

- [X] T001 Confirm the baseline on `feat/009-daily-standup`: `uv run just fast` passes
- [X] T002 [P] Write samples and fakes: `tests/unit/standup/samples/transcripts/` (sessions in
  two projects and one outside; typed, queued and accepted prompts; `isMeta`, compact
  summary, `promptSource: system`, task notifications, local commands, `!` input and output,
  pasted content, tool results, an assistant line, a broken line; a session across
  midnight), `tests/unit/standup/samples/bitbucket/` (`user.json`, pull request pages with
  participants: approved, no approval, changes requested; commits and comments of one pull
  request; reviews waiting; a 401 and a 429), and `tests/unit/standup/fakes.py` (the three
  ports in memory)

## Phase 2: Foundational — configuration, types, spec 007's hooks

- [X] T003 Create `tests/unit/standup/test_traceability.py`: every FR-001 to FR-022 has a test
  marked with it (this test is marked FR-019), `xfail(strict=True)` until T040
- [X] T004 Write failing tests in `tests/unit/standup/test_config.py` (FR-001, FR-002): the
  section per data-model.md ("1–10 identities", "projects 1–30", "paths absolute, 0–10",
  "repositories `<workspace>/<slug>`, 0–10", "at least one of the two", `redact` "0–100 terms,
  2–100 characters", `limits` ranges); a duplicate project, a relative path, a bad repository,
  a code host without `bitbucket_token`, a token as a value, unknown keys refused; `standup`
  a known job; `bitbucket_token` a known keychain item; the schema refuses what the loader
  refuses; a compatibility file
- [X] T005 Implement the `standup` section, `JOB_NAMES` and `KEYCHAIN_ITEMS` in
  `src/opscout/core/config.py`; add `tests/unit/config_contract/compat/v1/standup.yaml`;
  regenerate the schema; T004 passes
- [X] T006 Write `src/opscout/core/standup.py`: `Window`, `Fact`, `Gathered`, `SessionPrompts`,
  `Commit`, `PullRequest`, `SourceError`, `StandupOutput` (fields only), the three ports
- [X] T007 Write failing tests, then implement, spec 007's hooks (FR-016, FR-017, research R8):
  `RunProfile.validation_context` passed by `ClaudeCliRunner` to `model_validate` (a refusal
  from a context-aware validator retries once with its message, then `invalid_output`);
  `Start.prepare` called after the lock and the delivered check (a skipped start never calls
  it); `Ready` delivers its text without a runner call and records `delivered` with no runner
  facts; `Run` uses its prompt, context, render and inputs; an exception in `prepare` ends
  `failed` with its type; in `tests/unit/daemon/test_run_job.py`, `tests/unit/daemon/test_runner.py`,
  `src/opscout/core/daemon.py`, `src/opscout/services/daemon.py`,
  `src/opscout/adapters/claude_cli.py`; spec 007's and 008's tests still pass

## Phase 3: User Story 2 — the facts are gathered in code (P1)

**Goal**: the window's facts from three sources, by project, numbered.
**Independent test**: the adapters on samples; the gathering with fakes.

- [X] T008 [P] [US2] Write failing tests in `tests/unit/standup/test_window.py` (FR-003, research
  R4): a Tuesday covers Monday; a Monday covers Friday to Sunday; a custom week; the covered
  days' wording; a daylight-saving week
- [X] T009 [P] [US2] Write failing tests in `tests/unit/standup/test_transcripts.py` (FR-004,
  research R1): only the user's prompts from the samples; every excluded kind left out;
  pasted and tagged blocks removed; prompts outside the window left out; the session across
  midnight split by time; the project by the longest path; a session outside every project
  never read past its `cwd`; a broken line counted, not fatal; files older than the window
  skipped by modification time
- [X] T010 [P] [US2] Write failing tests in `tests/unit/standup/test_git.py` (FR-005, FR-014): on
  a real temporary repository with commits by two authors on two branches and a merge, the
  user's commits once each, with branch, time and subject; the exact read-only arguments
  (`log --all --source --no-merges`, one `--author` per identity, `--since`, `--until`); a
  path that is not a repository is a `SourceError`
- [X] T011 [P] [US2] Write failing tests in `tests/unit/standup/test_bitbucket.py` (FR-006,
  FR-014, research R3): with a fake opener on the samples, `/user` once; the three queries
  (closed in the window; **all** open ones, with no date filter; reviews waiting), their `q`
  and `fields`, pagination capped at 5 pages; a 20-second timeout per request and 60 seconds
  per source; only `GET`; Basic
  auth from the login and the token; the token never in an error or log; 401/403 name the
  token or scope; 429 waits as asked, within a limit; the commits and comments of an open
  pull request with changes requested
- [X] T012 [US2] Implement `src/opscout/adapters/claude_transcripts.py`,
  `src/opscout/adapters/git_log.py`, `src/opscout/adapters/bitbucket.py`; T008 to T011 pass
  (with the window in `src/opscout/services/standup.py`)
- [X] T013 [P] [US2] Write failing tests in `tests/unit/standup/test_gather.py` (FR-007, FR-008,
  FR-021, research R3, R5): facts from fakes ordered by project and time, numbered `s`, `c`,
  `p`, `r`; duplicates once; each cap applied and counted; a failing source becomes a missing
  note with its reason, the others still gathered; the blocker rule on fixed clocks (no
  approval for one full working day; changes requested then answered by a commit or a
  comment; a younger pull request is open work)
- [X] T014 [US2] Implement the gathering, minimization and blocker rule in
  `src/opscout/services/standup.py`; T013 passes

## Phase 4: User Story 3 — nothing private leaves; source text cannot steer (P1)

- [X] T015 [P] [US3] Write failing tests in `tests/unit/standup/test_redact.py` (FR-009,
  research R6): every kind of the table planted in prompts, subjects, titles and branches is
  replaced by its marker; the deny-list terms, whole words, any case; counts by kind; text
  without secrets unchanged; a corpus of realistic false-positive traps (versions, dates,
  short hex, file paths) left alone
- [X] T016 [US3] Implement `src/opscout/services/redact.py`; T015 passes
- [X] T017 [P] [US3] Write failing tests in `tests/unit/standup/test_output.py` (FR-010, FR-011,
  FR-012, research R7): the prompt holds the facts only inside the untrusted block, after
  redaction; `StandupOutput` with the facts as context refuses an unknown id, a project not
  configured or without facts, a line without citations, a non-blocker under blockers, a
  marked blocker left out, too many or too few yesterday lines; accepts a good output; the
  render turns `<` and `>` into `‹` and `›` in every text, so `<!channel>`, `<@UEXAMPLE01>`
  and `<https://example.com|x>` stay text, and leaves a plain `@` alone
- [X] T018 [US3] Implement the prompt, the validators and the render in
  `src/opscout/services/standup.py` and `src/opscout/core/standup.py`; T017 passes
- [X] T019 [US3] Write failing tests, then implement, that the record holds the inputs by
  reference only (FR-013): sources, counts, ids, cuts, redaction counts by kind (a planted
  e-mail shows as `email=1`), missing sources;
  a sentinel secret and a sentinel prompt text appear in no record, output or log
  (`tests/unit/standup/test_job.py`)

## Phase 5: User Story 1 — the summary arrives before the standup (P1) 🎯 MVP

- [X] T020 [P] [US1] Write failing tests in `tests/unit/standup/test_job.py` with fakes in the
  composition root (FR-015, FR-017, US1 scenarios 1–5): `opscout run standup` gathers, runs
  the model with the prompt and context, renders three sections and the covered days, and
  delivers by DM with buttons when chat is configured; a Monday covers the weekend; a second
  start is skipped without gathering; `--force` gathers again; without chat, the outbox
- [X] T021 [US1] Implement the `standup` job (its profile: no tools, `sonnet`, 0.10 USD, 3
  turns) and its `prepare` wiring in `src/opscout/core/daemon.py` and
  `src/opscout/entrypoints/daemon.py`; T020 passes

**Checkpoint**: a daily from fakes, through spec 007 and 008's path.

## Phase 6: User Story 4 — only what happened (P2)

- [X] T022 [P] [US4] Write failing tests in `tests/unit/standup/test_job.py` (FR-016, US4): no
  facts delivers "No recorded activity since <day>" and the open work, with no runner call;
  every delivered line cites a fact (a fake output citing none is refused, retried, then
  `inconclusive`); a missing source is named in the message with the command that helps
- [X] T023 [US4] Implement the quiet-day text and the missing-source line in
  `src/opscout/services/standup.py`; T022 passes
- [X] T024 [P] [US4] Write failing tests in `tests/unit/standup/test_preview.py` (FR-022):
  `opscout standup preview` prints the window, the redacted facts and the counts exactly as
  the prompt would hold them; `--counts` prints counts only; no runner, delivery or network
  call; exit 2 without a `standup` section
- [X] T025 [US4] Implement `opscout standup preview` in `src/opscout/entrypoints/daemon.py` and
  `cli.py`; T024 passes

## Phase 7: User Story 5 — setup and evaluations (P2)

- [X] T026 [P] [US5] Write the evaluation cases in `evals/standup/` (research R9): fact lists and
  expected checks for `ordinary-tuesday`, `monday-covers-weekend`, `quiet-day`,
  `bitbucket-missing`, `planted-secrets`, `planted-instructions`, `large-day`,
  `stale-review-blocker`, with `example-*` values
- [X] T027 [P] [US5] Write failing tests in `tests/unit/standup/test_evals.py` (FR-018): each case
  loads; its graders pass on a hand-written good output and fail on outputs that cite unknown
  facts, drop a blocker, leak a planted value or follow a planted instruction; the runner of
  the evaluations stops at the cost ceiling and exits 1 on a failure (with a fake runner)
- [X] T028 [US5] Implement `tools/standup_evals.py` and the graders; T027 passes
- [X] T029 [P] [US5] Write `docs/reference/standup.md` (setup, the token's scopes, what is read
  and what is never sent, the preview, the blocker rule, evaluations), the `standup` section
  in `docs/reference/configuration.md` and a commented example in `example-config/config.yaml`;
  a test marked FR-020 that `docs/PLAN.md` §9 holds the open item for the week of dailies and
  the agreement rate

## Phase 8: Polish and the live check

- [X] T030 Update `docs/PLAN.md`: the status line (spec 008 merged, spec 009 in progress), the
  daily-standup paragraph in §7, the §9 item for the week of dailies and the agreement rate
  (FR-020)
- [X] T031 Live, with the user's projects in a temporary configuration: `opscout standup preview
  --counts` (counts and redaction kinds only shown here); the user reads the full preview
  themself (quickstart steps 2–3). Their read found four gaps, fixed with tests first:
  Claude Code repeats the id on the closing paste tag (`</pasted_content id="1">`), so
  pasted text went through; a 12-digit account ID glued to letters escaped redaction; the
  interruption marker came through as a prompt; and session times showed in UTC beside
  commits in local time
- [X] T032 Live: the user creates the Bitbucket token with scopes and stores it; confirm the
  endpoints, the scope that reads the account, and the fields; record them in research R3
  (quickstart step 4). Confirmed with three scopes (R3). Live, two discovered repositories
  answered 404 (gone, or no access) and failed the whole source; a 404 now fails only that
  repository (`RepositoryError`), named in the missing line, with tests first
- [X] T033 Live: run the evaluations with the user's model (cost ceiling 0.50 USD); record the
  result and cost in the spec's Actuals; choose the default model (research R7). Result in R7:
  8 of 8 with `sonnet` and `haiku` after the prompt forbade quoting planted instructions;
  the default is `haiku`, the smallest that passes (spec assumption)
- [X] T034 Live: one real summary by DM; the user judges it with the buttons (quickstart step 6);
  a fact with a planted `<!channel>` and `<@…>` shows as text, notifying no one. Delivered and
  agreed with (stored once the gateway ran); the model left the planted markup out, so the
  escaping rests on the render's tests (spec Actuals)
- [X] T035 Record the live results in the spec's Actuals and PLAN.md §7
- [X] T036 Run `uv run just check` and `uv run just coverage` (100 % on `core` and `services`)
- [X] T037 Converge, then the independent review of the diff in a fresh context; record its
  findings and fixes in this file. Converge appended T041–T042 (phase 9). The review found
  no high-severity defect; each finding was fixed with a test first:
  - M1: a deny-listed term reached the model in a project name, or inside a longer word;
    terms now match anywhere, and a project name holding one is renamed (joined when two
    become one).
  - M2: prompts were shortened before redaction, so a cut could leave part of a value; they
    are redacted whole, then shortened.
  - M3: a listed project grouping a found repository duplicated it; a listed project now
    claims its paths and repositories.
  - M4: Bitbucket's 60 s budget reset on each call and ignored successful requests; it is
    one budget for the source, and a source that runs out keeps what it read.
  - M5: "closed in the window" had no upper bound; the query and a check now keep the last
    update inside the window (the list gives no closing time, research R3).
  - L1 line breaks in model text could add a section: the render joins them. L2 an
    unanswered changes request is not a blocker by age, and the label says why. L3 an odd
    answer from Bitbucket or git is a source error, not a failed job. L4 a yesterday line
    cites only its project's facts. L5 the output's project name is bounded. L6 the prompt
    lets one line cite several blockers past ten. L7 reviews the user approved are not
    waiting. L8 a `next` link off the API is not followed. L9 subagent briefs
    (`isSidechain`) are not prompts.
  - Found by the pre-commit hook: run inside a git hook, discovery's git inherited the hook's
    `GIT_*` variables and read the wrong repository; it now runs, as the log already did,
    without them (and the tests' own git calls too).
- [X] T038 Run the gates again after the review's fixes
- [X] T039 Check the staged diff for real data (rule 2): no project, path, identity, login,
  workspace or term of the user's
- [X] T040 Remove the traceability `xfail`; set the spec's status to Implemented and record the
  effort

## Dependencies

1 → 2 → 3 (US2) → 4 (US3) → 5 (US1, MVP) → 6 (US4) → 7 (US5) → 8. Tests before their
implementation in each phase. T021 needs T014, T016 and T018; T031–T034 need every story
and, for T032–T034, the user; T040 last.

## Parallel examples

- Phase 3: T008, T009, T010 and T011 together; then T013.
- Phase 4: T015 and T017 together.
- Phase 6: T022 and T024 together.
- Phase 7: T026, T027 and T029 together.

## Implementation strategy

MVP: phases 1–5, a daily from fakes through the real prompt, checks and delivery. Then the
quiet day and the preview (US4), the evaluations (US5), and the live check, which needs the
user's projects, token and judgement.

## Phase 9: Convergence

- [X] T041 Make Markdown link syntax (`[text](url)`) and URL schemes (`https://`) inert in the
  render, as `<…>` already is, in `src/opscout/services/standup.py` `plain()`, test first in
  `tests/unit/standup/test_output.py`: Slack's `markdown` block makes both live links per
  FR-012 (partial)
- [X] T042 Give a session's fact the time of its last prompt in the window besides its first,
  in `src/opscout/services/standup.py` `_sessions`, test first in
  `tests/unit/standup/test_gather.py` per FR-004 (partial)
