# CLAUDE.md — opscout

@AGENTS.md

## Claude Code specifics

- Spec Kit is installed as project skills: `/speckit-specify`, `/speckit-clarify`,
  `/speckit-plan`, `/speckit-tasks`, `/speckit-analyze`, `/speckit-implement`, and others in
  `.claude/skills/speckit-*`. They are dev-time tools for this repo and are never shipped in
  the plugin, which lives only in `plugins/opscout/`.
- Load the plugin from source with `claude --plugin-dir plugins/opscout`; check it with
  `uv run just plugin` and `claude plugin eval plugins/opscout`.
- Personal, machine-specific instructions (such as where the private config lives) go in
  `CLAUDE.local.md`, which is git-ignored.
- Project hooks (ADR-0018): a guard denies push forms the rule-5 `ask` rules miss, ruff runs
  after each Python edit, and `uv run just fast` runs before you stop, blocking the stop
  once if it fails. Rules in `.claude/rules/` load with the files they cover.
