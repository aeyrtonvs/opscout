# Contract: the configuration file, schema version 1

## Location

`config.yaml` in the configuration directory (`--config`, else `OPSCOUT_CONFIG`, else
`~/.config/opscout/`).

## Format

- UTF-8 YAML, a UTF-8 byte-order mark allowed; at most 1 MiB.
- One document whose top level is a mapping.
- Plain data only: mappings, sequences, and string, integer, float, boolean, null and
  timestamp scalars. Other tags and the merge key `<<` are rejected.
- No duplicate keys. Aliases allowed; at most 10,000 nodes once expanded.
- No value is converted: `"1"` is a string, `1.0` a float, `true` a boolean.

## Content

```yaml
schema_version: 1
```

| Key | Required | Type | Meaning |
|---|---|---|---|
| `schema_version` | yes | integer, exactly `1` | the major version of the schema this file follows |

Every other key is unknown, and therefore a problem, until a later spec adds it.

## Rules for every later section

- **Additive change**: a new optional key or section keeps `schema_version: 1`, and a
  configuration using it joins the compatibility set.
- **Breaking change**: removing, renaming or retyping a key, or making one required, takes
  `schema_version: 2` and a migration note for version 1 in
  `docs/reference/configuration.md`.
- **No secret values**: a credential is a keychain reference,
  `{service: <name>, account: <name>}` with `account` optional; a key whose name suggests a
  credential must have that type.
- **Descriptions**: every key has one, shown by editors.

## Editor association

```yaml
# yaml-language-server: $schema=https://raw.githubusercontent.com/aeyrtonvs/opscout/<commit>/schemas/config.schema.json
```
