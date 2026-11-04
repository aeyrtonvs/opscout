---
paths:
  - "plugins/opscout/**"
  - ".claude-plugin/**"
---

# The plugin: skills, subagents, hooks and evals

- **Agent Skills format** (ADR-0009): a skill's `name` equals its directory, and its
  description stays within the specification's limits. Claude Code extension fields
  (`effort`, `model`, `context: fork`) are used only for a measured need.
- **A contract first** (ADR-0018): each `SKILL.md` opens with its deliverable (with the
  output schema), constraints, non-goals and acceptance. The body stays under 500 lines;
  details go in `references/`, loaded on demand.
- **Read-only** (Principles II, III): read-only is enforced by the read-only identity and
  allow-listed tools (ADR-0010), never by the prompt alone. Report whether a secret exists
  and where, never its value. Output that drives behavior is structured and validated
  against a schema, and every claim cites evidence from a tool in the same run
  (Principle VI).
- **Evals** (ADR-0013): every acceptance scenario of the skill's spec has at least one case,
  named after it (`NNN-us1-s2`). Deterministic graders come first, MCP tools are mocked, and
  fixtures are synthetic. Changing a skill's `model` needs its suite to pass first.
- **No real data** (Principle I): examples and fixtures use reserved values only.
- **Hooks** are Python commands run through uv (ADR-0021). A `userConfig` value reaches them
  as `${user_config.KEY}` in exec-form `args` or as `CLAUDE_PLUGIN_OPTION_<KEY>`; shell-form
  commands cannot use the substitution.
- **Validate** with `uv run just plugin`. The version lives only in `plugin.json` and moves in
  lockstep with `pyproject.toml` (ADR-0016).
