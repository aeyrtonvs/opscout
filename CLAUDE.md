# CLAUDE.md — opscout

@AGENTS.md

## Claude Code specifics

- Spec Kit is installed as project skills: `/speckit-specify`, `/speckit-clarify`,
  `/speckit-plan`, `/speckit-tasks`, `/speckit-analyze`, `/speckit-implement`, and others in
  `.claude/skills/speckit-*`. They are dev-time tools for this repo and are never shipped in
  the plugin, which lives only in `plugins/opscout/`.
- Load the plugin from source with `claude --plugin-dir plugins/opscout`; check it with
  `claude plugin validate --strict` and `claude plugin eval plugins/opscout`.
- Personal, machine-specific instructions (such as where the private config lives) go in
  `CLAUDE.local.md`, which is git-ignored.
