# Quickstart: validate the leak guard

Prerequisites: a clone set up with `uv sync` and `uv run just setup` (CONTRIBUTING.md).

## 1. The suite

```sh
uv run just test tests/tools/test_leak_check.py
```

Expected: every test passes, including the traceability test (every FR of
[spec.md](spec.md) has a test) and the typical-change timing test (SC-003).

## 2. The repository is clean (SC-002)

```sh
uv run --frozen python -m tools.leak_check tracked
```

Expected: exit 0 and no output on standard output.

## 3. End-to-end time (SC-003)

```sh
time uv run --frozen python -m tools.leak_check tracked
```

Expected: well under one second (0.31 s on 2026-11-03).

## 4. A synthetic ref-name leak is stopped before a push (US4, scenario 6)

In a scratch clone, never in this repository's own refs:

```sh
git switch -c "fix/$(printf '%s-%s' EXAMPLX 12)"    # a ticket-key shape, assembled
PRE_COMMIT_FROM_REF=HEAD PRE_COMMIT_TO_REF=HEAD \
  uv run --frozen python -m tools.leak_check pushed
```

Expected: exit 1 with `ref fix/…: ticket-key`. Delete the branch afterwards.

## 5. The gates

```sh
uv run just check
```

Expected: every pre-commit gate passes.

The contract of each mode is in [contracts/cli.md](contracts/cli.md).
