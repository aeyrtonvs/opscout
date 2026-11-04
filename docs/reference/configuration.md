# Configuration reference

opscout reads every organization-specific fact from **your private configuration**, never
from this public repository (ADR-0002). This page is the contract between the two:
where the configuration is found, what the file may hold, and how it changes over time
(ADR-0014, [spec 002](../../specs/002-config-contract/spec.md)).

## Where it is found

The configuration directory is the first of:

1. the `--config DIR` option;
2. the `OPSCOUT_CONFIG` environment variable, when it is set and not empty;
3. `~/.config/opscout/`.

A leading `~` is expanded in both the option and the variable. Inside Claude Code, the
plugin asks for the directory when it is installed.

The configuration is the file `config.yaml` in that directory. Nothing else there is read
by the loader; the directory may also hold the leak check's private deny-list
(`leak-denylist.txt`) or anything else of yours.

## Checking it

```sh
opscout config validate [--config DIR]
```

It prints the directory and where it came from, then either `valid (schema version 1)` or
one line per problem, in file order:

```text
<file>:<line>:<column>: <key path>: <message>
```

Every problem in the file is listed in one run. A message names the key, what was
expected and where; it never repeats the value found, so the output is safe to paste or to
keep in a CI log. The exit status is 0 when the configuration is valid, 1 when it is
invalid or cannot be found or read, and 2 on bad arguments.

To validate a private repository on every commit, add the hook this repository publishes:

```yaml
repos:
  - repo: https://github.com/aeyrtonvs/opscout
    rev: <commit>
    hooks:
      - id: opscout-config-validate
```

It validates the repository it runs in, whatever `OPSCOUT_CONFIG` says.

## The file

- UTF-8 YAML (a byte-order mark is allowed), at most 1 MiB, one document whose top level is
  a mapping.
- Plain data only: mappings, sequences, and string, integer, float, boolean, null and
  date scalars. Other tags (such as `!!python/object` or `!!binary`) and the merge key
  `<<` are refused, and reading never runs code.
- Every key is a string, and no key appears twice in a mapping. `1:`, `true:`, `~:` and
  `2001-01-01:` are not string keys; quote them if you mean text.
- Aliases are allowed, up to 10,000 nodes once expanded and 100 levels of nesting.
- No value is converted to another type: `"1"` is a string, `1.0` a number, `true` a
  boolean.
- Values mean the same to opscout and to an editor that follows YAML 1.2: an integer is
  written in plain decimal (`10`, not `0x0a`, `1_0` or `010`), and a boolean as `true` or
  `false` (`yes`, `no`, `on` and `off` are refused; quote them for text).
- Every key must be known. A key opscout does not know is a problem: a typo, or a key from
  a newer opscout. In messages, a key that is empty or not plain text is shown quoted and
  escaped.

The models in `src/opscout/core/config.py` are the source of truth. Their JSON Schema is
committed at [`schemas/config.schema.json`](../../schemas/config.schema.json), so editors
can validate the file while you write it: start the file with

```yaml
# yaml-language-server: $schema=https://raw.githubusercontent.com/aeyrtonvs/opscout/<commit>/schemas/config.schema.json
```

`opscout config schema` prints the same schema.

## Schema version 1

| Key | Required | Type | Meaning |
|---|---|---|---|
| `schema_version` | yes | integer, exactly `1` | the major version of the schema the file follows |

That is all of version 1. Each feature that needs configuration adds its own section, in
its own spec. [`example-config/`](../../example-config/) is a complete, valid example.

## Rules for every section

These hold for each section a later spec adds. Review checks them; tests enforce the
parts marked *tested*.

- **Additive change**: a new optional key or section keeps the schema version, and adds a
  configuration that uses it to the compatibility set in `tests/unit/config/compat/`
  (*tested*: every configuration there must still validate).
- **Breaking change**: removing, renaming or retyping a key, or making one required, raises
  the major version, moves the old version to `RETIRED_VERSIONS` and adds its migration
  note below (*tested*: a retired version without a note fails the suite).
- **No secret values**: a credential is a keychain reference, `{service: <name>, account:
  <name>}` with `account` optional, naming where the OS keychain stores it. A key whose
  name contains `token`, `password`, `passwd`, `secret`, `api_key`, `apikey`,
  `credential` or `private_key` must be a keychain reference (*tested*).
- **Descriptions**: every key has one, which editors show (*tested*).
- **Strict and read-only**: unknown keys are refused, values are never converted, and the
  loaded configuration cannot be changed.

A configuration for another major version gets one message: upgrade opscout if the file
is newer, or follow the migration note if it is older.

## Migration notes

None yet: schema version 1 is the first. Each retired version gets a section here, such as
`### From version 1`, saying what changed and how to update a configuration.
