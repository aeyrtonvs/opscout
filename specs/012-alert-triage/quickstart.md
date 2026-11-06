# Quickstart: validate alert triage (spec 012)

## Prerequisites

- A clone of this repository, `uv`, and Claude Code logged in.
- For the live check: one AWS environment in the private configuration (spec 011).

## 1. The engine's tests

```sh
uv run just fast
uv run pytest tests/unit/triage tests/unit/mcp -q
```

These prove:

- the verdict model and the check's rules (contracts/verdict.md);
- the evidence store, its expiry and the attempt bound;
- the confinement of `search_iac` and `read_iac`;
- the background filter of `recent_changes`;
- the record's transitions;
- the CLI.

## 2. The tools, through the server in mock mode

```sh
OPSCOUT_CONFIG=evals/triage/real-deploy OPSCOUT_DATA_DIR="$(mktemp -d)" \
  uv run opscout mcp --mock evals/triage/real-deploy/aws
```

The contract tests drive the same server in-process (`tests/unit/mcp/`). Expected:

- `begin_triage` on `evals/triage/real-deploy/alert.txt` returns a run id, the environment
  `example-prod` and the settings;
- every result carries `evidence`.

## 3. The skill's evals (mock mode, cost-capped)

```sh
uv run python -m tools.skill_evals --plugin plugins/opscout \
  --config-dir plugins/opscout/evals/eval-config --case '012-*' --max-cost-usd 15 \
  --max-run-usd 2
```

Expected: the classification score is at least 80 % (SC-001), and every shown verdict
passed the check or is inconclusive with its failures (SC-002).

**The ablation (FR-029)**: run the suite again with
`--config-override 'triage: {skeptic: true}'`, then compare the two results' scores and
costs.

## 4. Live, in a session

```sh
claude --plugin-dir plugins/opscout
```

1. Paste an alert from a configured environment and ask "is this real?".
2. Check the following:
   - no question about account, profile, region or timezone (SC-004);
   - the verdict shows checked citations;
   - the draft is in the ticket format, marked not filed;
   - the agreement question appears.
3. Run `opscout triage runs` and `opscout triage show <id>`, and check that the record
   holds the outcome and the agreement, and no alert text.
