---
paths:
  - "src/**/*.py"
  - "tests/**/*.py"
  - "tools/**/*.py"
---

# Python code

- **Test first** (Principle VII): write the test, watch it fail for the right reason, then
  make it pass. When a spec exists, mark the test with `@pytest.mark.spec("NNN", "FR-00X")`.
- **Layers** (ADR-0011): `core` holds models and ports and does no I/O; `services` use only
  `core`; `adapters` implement ports; `entrypoints` is the composition root, the only place
  that wires adapters to services. `uv run just imports` enforces it.
- **Portability** (ADR-0021):
  - A scheduled job is an idempotent `opscout run <job>` command. It records a run key, so a
    second trigger for the same period sends nothing.
  - Host-specific capabilities sit behind ports, each with a fake for tests: `Scheduler`,
    `Runner`, `SecretStore`, `RunStore`.
  - Paths use `pathlib`, never `os.path`. State, logs and caches live under `platformdirs`
    directories. Executables are found with `shutil.which` or set in the configuration.
    Text is read and written with `encoding="utf-8"`. No hard-coded `~/Library`,
    `/usr/local` or `/bin/bash`.
  - Hooks and helper scripts are Python run through uv, never shell scripts.
- **Data** (Principles I, III, V): no organization-specific values or branches in code.
  Examples use reserved values (`123456789012`, RFC 5737 addresses, `example.com`). Code may
  report that a secret exists and where it lives, never read, print or log its value.
- **Style**: `# SPDX-License-Identifier: Apache-2.0` on the first line, full type hints
  (`mypy --strict`), absolute imports. A hook runs ruff after each edit; fix what it reports.
- **Dependencies**: add one only with a reason in `docs/PLAN.md` or an ADR, using `uv add`.
