# Quickstart: validate the configuration contract

Prerequisites: a clone set up with `uv sync` and `uv run just setup` (CONTRIBUTING.md).

## 1. The suite

```sh
uv run just test tests/unit/config
```

Expected: every test passes, including the traceability test (every FR of
[spec.md](spec.md) has a test), the drift test, and the end-to-end timing test (SC-006).

## 2. The example validates (SC-001)

```sh
uv run opscout config validate --config example-config
```

Expected: exit 0 and

```text
opscout config: example-config (from --config)
example-config/config.yaml: valid (schema version 1)
```

## 3. Problems are located, and values are not printed (US1, SC-004, SC-005)

```sh
dir=$(mktemp -d)
printf 'schema_version: 1\nexample_section:\n  token: not-a-real-value\n' > "$dir/config.yaml"
uv run opscout config validate --config "$dir"; echo "exit $?"
```

Expected: exit 1, one problem at line 2 naming `example_section` as an unknown key, and no
`not-a-real-value` in the output.

## 4. The committed schema is current (SC-003)

```sh
uv run opscout config schema | diff - schemas/config.schema.json && echo "in step"
```

Expected: `in step`.

## 5. A private configuration validates (SC-002)

Run locally only; nothing from it is copied here:

```sh
uv run opscout config validate --config <path to your private configuration repository>
```

Expected: exit 0. The private repository then adds the `opscout-config-validate` hook
([contracts/cli.md](contracts/cli.md)).
