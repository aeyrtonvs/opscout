---
status: accepted
date: 2026-11-04
decision-makers: repository maintainer
---

# The plugin runs the engine through a uv launcher in its `bin/`

## Context and Problem Statement

The plugin's skills, and later its MCP server and hooks, need the engine: the
configuration's loader is the only part allowed to read `config.yaml` (spec 002, FR-032).
But an installed plugin is only its own directory. Claude Code copies
`plugins/opscout/` into `cache/<marketplace>/<plugin>/<version>/` and leaves the rest of the
repository, `src/opscout/` included, behind. It installs Node dependencies for plugins, but
not Python ones (Claude Code docs, plugins/loading, checked 2026-11-04). PLAN.md §9 had
deferred the question to the MCP server's spec. The summary skill (spec 003) is the first
consumer, so the maintainer decided on 2026-11-04 to settle it there.

## Decision Drivers

- The engine a plugin runs must match the plugin's version (lockstep, ADR-0016).
- The prerequisites stay git, uv and Claude Code (ADR-0020); no global install.
- Helper scripts are Python run through uv, never shell (ADR-0021).
- Developing from a clone must use the clone's code, with no release in between.

## Considered Options

- A launcher in the plugin's `bin/`, run through uv, that runs the clone's engine or the
  matching release from PyPI.
- Vendoring the package inside the plugin directory.
- A SessionStart hook that installs the package into `${CLAUDE_PLUGIN_DATA}`.
- `uvx --from git+https://github.com/aeyrtonvs/opscout@vX.Y.Z`.

## Decision Outcome

Chosen option: the uv launcher. `plugins/opscout/bin/opscout` is a Python script whose
shebang is `#!/usr/bin/env -S uv run --script --quiet`. Claude Code puts `bin/` on the Bash
tool's PATH, so skills and commands call `opscout …`. The launcher:

1. runs `uv run --frozen --project <clone> opscout …` when the plugin directory sits in a
   clone of this repository (`claude --plugin-dir <clone>/plugins/opscout`);
2. otherwise runs `uvx --from opscout==<plugin version> opscout …`, the release ADR-0016
   publishes to PyPI;
3. otherwise, while the version is `0.0.0` (no release yet), it prints why and how to load
   the plugin from a clone, and fails.

It replaces itself with the command, so arguments, streams and the exit status pass
through. The MCP server and hooks reuse it.

Vendoring was rejected because it duplicates `src/` and still needs the dependencies
installed. The SessionStart hook was rejected because it runs at every session start and
needs its own update logic, which uv's cache already provides. The git URL was rejected
because it would be a second release channel next to PyPI.

### Consequences

- Good, because an installed plugin always runs exactly its own version, and a clone always
  runs its own code.
- Good, because nothing is installed globally; uv caches each version once.
- Bad, because the first call of a new version downloads it, which needs the network.
- Bad, because an installed plugin cannot run the engine until the first release; until
  then the plugin is loaded from a clone.
- Bad, because a missing uv is reported by the system (`env: uv: No such file or
  directory`), not by opscout; the plugin's README states the prerequisite.

### Confirmation

Tests run the launcher from the clone, from a copy outside a clone at version `0.0.0`, and
at a release version with a stand-in `uvx` (spec 003, FR-021 to FR-025). The lockstep test
keeps `plugin.json`'s version equal to the package's.

## More Information

Spec 003 (`specs/003-summary-skill/`), research R1. Closes the PLAN.md §9 item "How the
plugin finds the Python package".
