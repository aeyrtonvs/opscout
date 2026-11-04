# Research: Ship skill

Facts were checked on 2026-11-04 against the Claude Code documentation (hooks,
plugins/manifest-reference, permissions, plugin-evals; CLI 2.1.318).

## R1. How does the plugin's hook decide, and how does it fail? (FR-006, FR-013)

**Facts**:

- A plugin declares hooks in `hooks/hooks.json` under a `"hooks"` key. The exec form
  (`command` plus `args`, no shell) substitutes `${CLAUDE_PLUGIN_ROOT}` and
  `${user_config.KEY}` in every argument.
- The PreToolUse input holds `tool_name`, `tool_input.command`, `cwd` and
  `permission_mode`. The output `hookSpecificOutput.permissionDecision` is `allow`, `deny`,
  `ask` or `defer`, with `permissionDecisionReason`; the reason is shown to the user on
  `ask` and to Claude on `deny`.
- Exit 2 blocks the action. **Any other failure, a crash included, lets the action go
  ahead**, unless the hook sets `"onFailure": "block"`.
- Among hooks, deny > defer > ask > allow; a hook's deny wins over the user's allow rules.
  Whether a hook's `ask` still prompts in `bypassPermissions` mode is not documented.
- Plugin hooks run in `claude plugin eval` runs, outside the sandbox. In `claude -p`, a
  prompt no one can answer is denied, and Claude reads the reason.

**Decision**: `hooks/hooks.json` runs
`"${CLAUDE_PLUGIN_ROOT}/bin/opscout" hook pre-tool-use --config "${user_config.config_dir}"`
in exec form, with `"onFailure": "block"`. The command reads the event on standard input,
prints the decision as JSON and exits 0; any error while deciding about a command that
names `git push` exits 2 with the reason on standard error (FR-013). An unsubstituted
`${user_config.…}` counts as no directory, as in spec 003.

**Known limit**: if `bypassPermissions` skips a hook's `ask`, a push to a feature branch
would run unasked in that mode; a push to a protected branch is still denied. Recorded in
PLAN.md §9; checked when the first maintainer session runs in that mode.

## R2. Which push commands does the guard read? (FR-007 to FR-011)

**Decision**: the guard splits the command with `shlex` and reads only this grammar:

```text
git [-C <dir>] push [<options>] [<remote> [<refspec>…]]
```

- Anything else that mentions `push` next to `git` in the text, after any shell
  punctuation (`; & | ( ) $ \` < > newline`), an assignment or a wrapper before `git`, a
  shell's `-c`, `eval`, or a global option other than `-C`, is **denied**, asking for the
  plain form (FR-010). Text that `shlex` cannot split is denied the same way when it names
  `git` and `push`.
- Options: `--all` and `--mirror` are denied (FR-009); `-d`/`--delete` makes every refspec
  a deletion; `-f`, `--force`, `--force-with-lease`, `+refspec` are allowed through to the
  same checks (a force push to a feature branch is the user's call, asked like any push);
  `-u`, `--set-upstream`, `--tags`, `--follow-tags`, `--dry-run`, `-n`, `--no-verify`,
  `-q`, `-v` are accepted. Unknown options are denied.
- A refspec's destination is the part after `:`, or the whole refspec without one; a
  leading `+` and `refs/heads/` are stripped. `HEAD` alone means the current branch. A
  `refs/tags/…` destination is not a branch.
- With no refspec, the destination is the current branch; a detached HEAD is denied.
- `gh pr create` (and only the plain form) is asked.

The current branch and the remote's default branch come from `git` in the event's `cwd`
(or `-C <dir>`): `git symbolic-ref --short HEAD` and `git symbolic-ref --short
refs/remotes/<remote>/HEAD`. They are read in the entrypoint and passed to a pure decision
function in `services`.

**Rationale**: the same approach as this repository's dev guard (ADR-0018), smaller: the
plugin only needs to decide about pushes, so every other shape is either ignored (no
`push`) or refused.

## R3. Protected patterns (FR-008, FR-012)

`fnmatch`-style globs (`release/*`), matched against the destination branch name, case
sensitive. The protected set is the configured patterns plus `main`, `master` and the
remote's default branch, always. Without a readable configuration, the guard still uses
the three fixed ones.

## R4. The checks (FR-004, FR-005)

- **Branch**: `branch_pattern` tokens become regular expressions: `{type}` one of the
  configured types, `{slug}` `[a-z0-9]+(-[a-z0-9]+)*` up to 50 characters, `{ticket}`
  `[A-Z][A-Z0-9]+-[0-9]+`. The whole name must match, and must not be protected.
- **Message**: the Conventional Commit grammar this repository's commit-msg hook uses
  (`tools/commit_message.py`, ADR-0016), with the configured types, a subject of at most
  72 characters, and the configured trailer as the last non-empty line. Comment lines
  (`#`) are ignored. The engine has its own implementation: `tools/` is not shipped.

## R5. Evals (FR-022 to FR-024)

**Decision**: the headless runner of spec 003 gains:

- **Scratch repositories**: a case may hold `scaffold.py`; the runner runs it with the
  run's empty directory as its working directory before each arm. The ship cases' scaffold
  creates a repository on `main` with a commit, a local bare remote (`git init --bare`)
  named `origin` with `origin/HEAD` set, and an uncommitted change. Nothing leaves the
  machine.
- **`tool_order` graders** (`before`, `after`, each a tool name or `{tool, input_match}`), as
  `claude plugin eval` documents them, and `tool_used` with `min`/`max` (spec 003).
- Cases allow `Skill` and `Bash`. In `claude -p` the guard's `ask` is denied, so a push never
  runs; the graders check what was attempted, and that nothing aimed at `main`.

Graders: `tool_order` branch creation (`git (switch -c|checkout -b)`) before `git commit`,
`git commit` before `git push`; `tool_used` with `max: 0` for a push naming `main` or
`HEAD:main`; regex on the commit command for the type and the trailer.
