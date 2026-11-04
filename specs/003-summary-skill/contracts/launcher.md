# Contract: the plugin's launcher, `plugins/opscout/bin/opscout`

A Python script run through uv (`#!/usr/bin/env -S uv run --script --quiet`). Claude Code
puts the plugin's `bin/` on the Bash tool's PATH, so skills call `opscout …`.

| Situation | What runs |
|---|---|
| the plugin directory sits in a clone of this repository | `uv run --quiet --frozen --project <clone> opscout ARGS…` |
| installed, plugin version `X.Y.Z` other than `0.0.0` | `uvx --quiet --from opscout==X.Y.Z opscout ARGS…` |
| installed, version `0.0.0` (no release) | prints why and how to load the plugin from a clone; exit 1 |
| uv missing | the system reports `uv` as missing (status 127) |

Arguments, standard input, standard output, standard error and the exit status pass through
unchanged: the launcher replaces itself with the command.
