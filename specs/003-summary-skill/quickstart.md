# Quickstart: validate the summary skill

Prerequisites: a clone set up with `uv sync` and `uv run just setup`.

## 1. The suite

```sh
uv run just test tests/unit/writeups tests/unit/config_contract
```

## 2. The formats, from the example configuration

```sh
plugins/opscout/bin/opscout writeup formats --config example-config
```

Expected: the built-in ticket, message and postmortem formats plus the example's configured
ones, and exit 0.

## 3. The skill, loaded from the clone

```sh
claude --plugin-dir plugins/opscout
```

Then ask, after some work in the session: "give me a short summary for the ticket".
Expected: one block in the ticket format, without what was ruled out.

## 4. The evals (each run confirmed; reports stay local)

Until the first release (ADR-0013, amended):

```sh
uv run python -m tools.skill_evals --plugin plugins/opscout \
  --config-dir plugins/opscout/evals/eval-config --threshold 0.9 --max-cost-usd 3 \
  --out plugins/opscout/evals/results/runner.json
```

Expected: every case at or above 0.9, and a positive delta over the no-plugin baseline.
