# Research: Leak guard

The Technical Context of [plan.md](plan.md) has no open unknowns: the stack is the one
Phase 0a chose (Python 3.13, the standard library and the git CLI). The research below
settles the design questions the spec leaves to the plan.

## R1. Which ref names can the pre-push check see? (FR-032)

**Facts** (read from pre-commit 4.x, `pre_commit/commands/hook_impl.py`, `_pre_push_ns`):

- git gives a pre-push hook one stdin line per ref being pushed:
  `<local ref> <local sha> <remote ref> <remote sha>`.
- pre-commit consumes stdin itself and passes the hooks only the **first** ref that has
  something to push, in `PRE_COMMIT_LOCAL_BRANCH` and `PRE_COMMIT_REMOTE_BRANCH`, with the
  range in `PRE_COMMIT_FROM_REF` and `PRE_COMMIT_TO_REF`.
- It skips deletions (local sha all zeros).
- When no ref brings a commit the remote lacks (for example a new branch that points at a
  commit already on the remote), it runs **no** pre-push hook at all.

**Decision**: in `pushed` mode, check the names of:

1. the local and remote refs pre-commit passes (`PRE_COMMIT_LOCAL_BRANCH`,
   `PRE_COMMIT_REMOTE_BRANCH`), since the remote name may differ from the local one
   (`git push origin HEAD:refs/heads/<name>`); and
2. every local branch and tag (`git for-each-ref refs/heads refs/tags`), which covers the
   other refs of a multi-ref push that pre-commit does not pass.

Names are checked without their `refs/heads/` or `refs/tags/` prefix, and each finding is
located as `ref <name>`.

**Rationale**: it is the same trade-off `pushed_commits` already makes for commits: check
more than the push, never less. Over-checking costs nothing unless a local ref name holds a
leak, which is worth fixing anyway. Reading the remote's refs would need the network, which
the spec rules out.

**Known limit**: a push that brings no new commit runs no pre-commit hook, so its ref names
are not checked here. The rule-5 `ask` prompt before every push (AGENTS.md) is the
remaining control for that case; it is recorded in PLAN.md §9.

**Alternatives considered**:

- *A pre-push hook outside pre-commit that reads stdin itself.* Exact, and it covers the
  no-new-commit case, but it adds a second hook installer next to `just setup` and bypasses
  the framework every other gate uses. Rejected for now; revisit if the known limit is hit.
- *Only the refs pre-commit passes.* Misses the second and later refs of
  `git push origin a b`. Rejected.
- *`git ls-remote` to compare with the remote.* Needs the network. Rejected (Non-Goals).

## R2. Where is the one-second budget measured? (FR-031, SC-003)

**Facts**: on 2026-11-03, `uv run --frozen python -m tools.leak_check tracked` took 0.31 s
for every tracked file, start-up included; 20 files took 0.06 s.

**Decision**: the test measures the whole command in a fresh interpreter
(`python -m tools.leak_check files …` as a subprocess) on a synthetic typical change of
20 files and 1,000 lines, and asserts under one second. The `uv run` wrapper is left out of
the test because its overhead depends on the machine's cache, not on the check; the
quickstart measures it by hand.

**Rationale**: an in-process timing would hide the import and start-up cost the contributor
actually waits for. A subprocess with the current interpreter is deterministic enough for
CI with a one-second budget against a 0.1 s typical time.

**Alternatives considered**: timing `scan_text` in-process only (misses start-up); timing
`uv run` in the test (flaky on a cold cache).

## R3. How are tests tied to requirements? (FR-030, SC-005)

**Decision**: every test in `tests/tools/test_leak_check.py` carries one
`@pytest.mark.spec("001", "FR-0NN")` marker per requirement it proves (the marker is already
registered in `pyproject.toml`, PLAN.md §4.2). A traceability test reads the spec's
requirement IDs and the markers collected from that module, and fails when a requirement
has no test.

**Rationale**: SC-005 is then a gate, not a review item. Reading the IDs from the spec keeps
one source of truth.

**Alternatives considered**: a hand-kept table in the spec (drifts); a pytest plugin
(more code than the check needs).

## R4. Which requirements does the Phase 0a code not meet yet?

Read against the spec on 2026-11-03:

| Requirement | Status in Phase 0a | Work |
|---|---|---|
| FR-032 ref names | missing | new code (R1) |
| FR-030 traceability | no markers | markers and the traceability test (R3) |
| FR-031 typical change | only the pathological-line test | the end-to-end timing test (R2) |
| FR-012 no deny-list here | by convention | ignore `leak-denylist.txt` in `.gitignore` and test that none is tracked |
| FR-027 evidence for pattern changes | not written down | state it in CONTRIBUTING.md and in the module's docstring |
| FR-005, FR-006 every suffix and endpoint kind | partly tested | add the missing synthetic cases |
| FR-021 merges and deletions | not tested | add tests |
| FR-017 no identity, FR-023 one hint per kind, FR-025 missing value | not tested | add tests |

Every other requirement is met and tested; the tests gain markers only.

## R5. Synthetic leaks in a public test file (FR-029)

**Decision**: keep the Phase 0a technique: each synthetic leak is a constant built by
concatenation at import time (`"OPS" + "-1234"`), so the file's text never holds a value
the check reports. The `files` pre-commit hook, which scans the test file itself, is the
proof.
