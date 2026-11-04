# Research: Summary skill

Facts were checked on 2026-11-04 against the Claude Code documentation (plugins/loading,
plugins/manifest-reference, skills, permissions, plugin-evals) and the local CLI 2.1.318.

## R1. How does the plugin run the engine? (FR-021 to FR-025; ADR-0022)

**Facts**:

- An installed plugin is copied to `cache/<marketplace>/<plugin>/<version>/`; files outside
  the plugin directory are not copied, so `src/opscout/` never reaches an installed plugin.
- Executables in the plugin's `bin/` are on the Bash tool's `PATH` while the plugin is
  enabled.
- The docs offer no automatic Python dependency install for plugins; Node is the only
  runtime with one.
- A script with the shebang `#!/usr/bin/env -S uv run --script --quiet` and an inline
  `# /// script` block runs with Python ≥ 3.13 through uv in about 0.4 s (measured here).
  Without uv, the system reports `env: uv: No such file or directory`, status 127.

**Decision**: `plugins/opscout/bin/opscout` is that script. It reads the plugin's version from
`../.claude-plugin/plugin.json` and then:

1. **From a clone**: when `../../..` (the repository root) holds a `pyproject.toml` whose
   project name is `opscout` and a `src/opscout/` directory, it runs
   `uv run --quiet --frozen --project <root> opscout ARGS…`.
2. **Installed**: otherwise, when the version is a release (not `0.0.0`), it runs
   `uvx --quiet --from opscout==<version> opscout ARGS…`, the release ADR-0016 publishes to
   PyPI.
3. **Neither**: it prints that no release of this version exists and how to load the plugin
   from a clone (`claude --plugin-dir <clone>/plugins/opscout`), and exits with status 1.

It replaces itself with the command (`os.execvp`), so arguments, input, output and the exit
status pass through unchanged (FR-025). The lockstep version test (ADR-0016) keeps the
plugin's version equal to the package's.

**Alternatives considered**:

- *Vendoring the package inside the plugin directory.* Duplicates `src/`, and the package's
  dependencies (Pydantic, PyYAML) still need an install step. Rejected.
- *A SessionStart hook that installs into `${CLAUDE_PLUGIN_DATA}`.* The documented route for
  Python dependencies, but it runs at every session start and needs its own update logic;
  uv's cache already does both. Rejected for now.
- *`uvx --from git+https://…@vX.Y.Z`.* Works without PyPI, but ADR-0016 makes PyPI the
  release channel; a git URL would be a second one. Rejected.
- *A shell script.* ADR-0021 and the Python rule require Python run through uv. Rejected.

## R2. How does the skill get the formats? (FR-008 to FR-011, FR-014, FR-020)

**Facts**: a skill's !`command` lines run before the skill reaches the model, through the
Bash tool, checked against permission rules; a skill's `allowed-tools` pre-approves them for
that turn. `${user_config.KEY}` is substituted in skill content. A command that exits with a
non-zero status aborts the whole skill invocation.

**Decision**:

- The engine command is `opscout writeup formats [--config DIR]`. It always exits 0
  (FR-010) and prints plain Markdown (contracts/writeup-formats.md).
- `SKILL.md` injects
  `!`opscout writeup formats --config "${user_config.config_dir}"`` and declares
  `allowed-tools: Bash(opscout writeup formats *)`, nothing else (FR-019, FR-020).
- **Verified 2026-11-04** with three headless runs (`claude -p --plugin-dir plugins/opscout`,
  synthetic text, USD 0.38 in all):
  1. `claude -p` denies the Skill tool itself unless it is allowed (`--allowedTools
     "Skill"`; in an eval case, `allowed_tools: [Skill]`).
  2. A plugin loaded with `--plugin-dir` has no `userConfig` values, and `claude plugin
     configure` accepts only installed plugins, so `${user_config.config_dir}` arrives
     unsubstituted. Inside double quotes the permission check refuses it ("the shell may
     read it differently than it was parsed … requires explicit approval") and the skill
     aborts.
  3. Single-quoted (`--config '${user_config.config_dir}'`) it passes the check; the formats
     command treats an empty value or the unsubstituted placeholder as no directory, so the
     resolution falls back to `OPSCOUT_CONFIG` and the default (FR-009). The launcher in
     `bin/` was found on the injection's PATH, and `OPSCOUT_CONFIG` reached it.
  4. With `OPSCOUT_CONFIG=example-config`, the write-up came out in the ticket format, eight
     lines, without the ruled-out causes, with the closing format line.

## R3. The `writeups` section (FR-001 to FR-007)

**Decision**: Pydantic models in `opscout.core.config`, strict and frozen like the rest:

```yaml
writeups:
  language: Spanish            # optional, free text: the language to write in
  rules: [...]                 # optional, for every format
  formats:                     # optional
    ticket:                    # name: ^[a-z][a-z0-9]*(-[a-z0-9]+)*$
      description: ...         # required, one line
      sections: [...]          # optional, headings in order
      rules: [...]             # optional
      max_lines: 12            # optional, positive integer
```

The built-in formats are a constant in `opscout.core.writeups`; `resolve_formats` (pure, in
`opscout.services.writeups`) applies the configured ones: a configured name replaces the
built-in of that name, a new name is added (FR-006). Strings are bounded (a description up
to 200 characters, a rule or section up to 300, at most 30 of each) so a format stays a
format.

Adding `writeups` is additive: `schema_version` stays 1 and a compatibility file using every
field joins `tests/unit/config_contract/compat/v1/` (spec 002, FR-030).

## R4. Built-in formats (FR-005, FR-007)

From PLAN.md §1–§2 (public): plain text ready to paste.

| Name | Sections | Limit |
|---|---|---|
| `ticket` | What happened; Why; What was done; What is pending | 12 lines |
| `message` | none (two to four sentences) | 5 lines |
| `postmortem` | Cause; Impact; Fix; Follow-ups | 25 lines |

Shared built-in rules, applied by the skill whatever the configuration says (they are its
contract, FR-016): only facts from the session; never list what was evaluated and ruled
out, nor how the result was reached; never a secret value; nothing invented (ticket keys,
names, times, figures); plain text, no headings beyond the sections.

## R5. Evals (FR-026 to FR-028; ADR-0013)

**Facts** (plugin-evals): a case is `evals/<name>/prompt.md` (frontmatter: `runs`,
`max_turns`, `allowed_tools`, `tags`, …; an unknown key is an error) with
`graders/*.md`. `regex` graders match the final reply by default; `match: not_contains`
requires absence; `count:N` counts. `tool_used` with `tool: Skill` is a with-only indicator
in a two-arm run. A case's score is the weighted share of passing graders, averaged over
runs; `--threshold` fails the run below it; the baseline delta is reported but never changes
the exit code. Reports publish to claude.ai unless `--no-publish` is passed. A skill's
!`command` needs Bash granted with `--allow-tools`.

**Decision**:

- One case per skill scenario (`003-us1-s1` … `003-us2-s5`). Each prompt holds a synthetic
  work log written as the user would paste or recount it, with distinctive fake tokens for
  the ruled-out hypotheses (for example `EXAMPLE-DNS-RESOLVER`), then the request in natural
  language.
- Graders: `regex` `not_contains` for every ruled-out token; `regex` for the sections in
  order; `regex` `count` or a line-bound pattern for the limit; an `llm` grader only for
  "only facts from the session"; `tool_used: Skill` as the plugin-fired indicator.
- **Settled by the headless check**: evals run with `OPSCOUT_CONFIG` exported to a synthetic
  configuration in `plugins/opscout/evals/config/`, never the default directory (which, on
  the maintainer's machine, is the private configuration). Whether `claude plugin eval`
  passes the variable to its runs is not documented; the case `003-us2-s3` asks for a format
  only that synthetic configuration defines, so it fails visibly if the variable is lost.
- Configured-format cases (US2) need the skill to read a synthetic configuration. A case may
  set only `EVAL_*` environment variables, so `OPSCOUT_CONFIG` cannot be set that way, and
  the docs do not say what `${user_config.config_dir}` becomes in an eval run. The headless
  check of R2 settles it before any eval is written. If an eval run cannot point the skill
  at a synthetic configuration, the US2 behaviors that the engine decides (which formats
  apply, replacement, shared rules, language) are proven by unit tests of the formats
  command, and the evals cover what the model decides with the built-in formats. Either
  way, an eval never reads the maintainer's real configuration.
- An empty `--config ""` (an unset option substituted as empty) counts as not given, so the
  command falls back to `OPSCOUT_CONFIG` and the default, as spec 002 resolves it.
- **First run through `claude plugin eval` (2026-11-04, USD 1.79)**: every case failed
  because the plugin's `bin/` is not on an eval run's PATH (`command not found: opscout`).
  With the launcher called by its path (`"${CLAUDE_PLUGIN_ROOT}/bin/opscout"`), the run's
  sandbox refused to read the clone outside the plugin directory (`pyproject.toml:
  Operation not permitted`), and a case's `add_dirs` cannot leave the case directory. Each
  run's HOME is also a sealed temporary directory, so an eval can never read the real
  configuration.
- **Decision (maintainer, 2026-11-04)**: until the first release, `tools/skill_evals.py`
  plays the same cases through `claude -p` (ADR-0013, amended), each run confirmed:
  `uv run python -m tools.skill_evals --plugin plugins/opscout --config-dir
  plugins/opscout/evals/eval-config --threshold 0.9 --max-cost-usd 3 --out
  plugins/opscout/evals/results/runner.json`.

## R6. Skill frontmatter (FR-012)

**Decision**: a test parses `SKILL.md` frontmatter and checks `name` equals the directory,
`description` is 1–1024 characters, and every key is an Agent Skills field (`name`,
`description`, `license`, `compatibility`, `metadata`, `allowed-tools`) or an allowed
Claude Code extension (`argument-hint`, `disable-model-invocation`, `effort`, `model`,
`context`, `agent`). `claude plugin validate --strict` (already a gate) checks the plugin as
a whole.
