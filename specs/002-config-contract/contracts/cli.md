# Contract: the `opscout config` commands

```text
opscout config validate [--config DIR]
opscout config schema
```

## `opscout config validate`

Checks the configuration in a directory and reports every problem.

### Inputs

| Input | Meaning |
|---|---|
| `--config DIR` | the configuration directory; wins over everything else |
| `OPSCOUT_CONFIG` | the configuration directory when `--config` is absent; empty means unset |
| `~/.config/opscout/` | the directory when neither is given |
| `<dir>/config.yaml` | the configuration file; nothing else in the directory is read |

### Output (standard output)

The first line names the directory and its source:

```text
opscout config: <dir> (from --config | from OPSCOUT_CONFIG | default)
```

Then, when the file is valid:

```text
<dir>/config.yaml: valid (schema version 1)
```

or one line per problem, in file order:

```text
<dir>/config.yaml:<line>:<column>: <key path>: <message>
```

Example, with a reserved name for the unknown key:

```text
opscout config: example-config (from --config)
example-config/config.yaml:3:1: example_section: unknown key; it may be a typo or come from a newer opscout
```

The key path is dotted, with `[n]` for list items; `(top level)` means the top-level
mapping and `(document)` the file as a whole (encoding, size, syntax, limits). A message
never contains the value found in the file (FR-017).

### Exit status

| Status | Meaning |
|---|---|
| 0 | the configuration is valid |
| 1 | it is invalid, or the directory or file is missing or unreadable |
| 2 | bad arguments |

## `opscout config schema`

Prints the JSON Schema of the configuration to standard output, byte for byte as committed
at `schemas/config.schema.json`. Exit status 0. Regenerate the committed file with
`uv run just schema`.

## The pre-commit hook (`.pre-commit-hooks.yaml`)

```yaml
# In a private configuration repository's .pre-commit-config.yaml
repos:
  - repo: https://github.com/aeyrtonvs/opscout
    rev: <commit SHA>            # a tag once releases exist
    hooks:
      - id: opscout-config-validate
```

Runs `opscout config validate --config .` from that repository's root whenever
`config.yaml` (or a misnamed `config.yml`) is part of the commit.
