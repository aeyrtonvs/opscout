# Data model: Alert triage (spec 012)

All models are pydantic, frozen, and forbid unknown keys, as in specs 007 and 011.

## Configuration (`core/config.py`)

- **InfrastructureClone**: `name`, `path` (absolute), `environments` (a list of
  configured environment names, or none for all).
- **Triage**: `infrastructure` (list of InfrastructureClone, at most 20, unique names),
  `observability` (bool, default false), `skeptic` (bool, default false),
  `metric_history_days` (1–14, default 7), `background_actions` (list, at most 50).
- **Configuration** gains `triage: Triage | None`. A cross-section validator checks that
  every clone's `environments` names a configured environment (contracts/config.md).

## Evidence (`core/triage.py`, stored by `adapters/evidence_files.py`)

- **EvidenceId**: `ev-` and 10 lower-case hexadecimal characters.
- **StoredEvidence**: `id`, `tool`, `stored_at` (aware datetime), `result` (the rendered
  envelope, as returned).
- **EvidenceStore** (Protocol):
  - `put(tool, result, at) -> EvidenceId`;
  - `get(id) -> StoredEvidence | None`;
  - `since(at) -> list[StoredEvidence]`;
  - `prune(older_than)`.

  It has two adapters: files and memory (tests).

## Verdict (`core/triage.py`)

- **Citation**: either `CheckedCitation` (`evidence`, `quote`) or `UncheckedCitation`
  (`observability`, `quote`).
- **Cause**: `text`, `cites`.
- **Threshold**: `assessment` (`keep` | `tune` | `not-assessable`), `proposal`, `reason`,
  `cites`.
- **Claim**: `text`, `cites`.
- **SkepticNote**: `ran`, `disagreed`, `note`.
- **Verdict**: the fields of contracts/verdict.md. The model holds the field rules: the
  lengths, `proposal` iff `tune`, and the IANA timezones.
- **Failure**: `where` (JSON path), `reason`.
- **CheckResult**: `passed`, `failures`.

`check(verdict, store, run) -> CheckResult` is a pure function over the verdict, the stored
evidence of the run, and a secret detector passed in, so the core stays free of I/O and of
services (research R5).

## Run record (`core/triage.py`, stored by `adapters/triage_files.py`)

- **AlertRef**: `format` (or null), `environment` (or null), `resource` (or null), `digest`
  (SHA-256 hex of the text).
- **CheckSummary**: `attempts` (0–3), `failures` (those of the last failed attempt).
- **Agreement**: `answer` (`agree` | `disagree` | `not-answered`), `reason` (or null), `at`.
- **TriageRecord**:
  - identity: `run_id`, `record_version` (1), `engine_version`, `started_at`, `ended_at`
    (or null);
  - state: `outcome` (`open` | `checked` | `inconclusive`), `alert` (AlertRef), `settings`
    (skeptic and observability as used);
  - result: `verdict` (or null), `check` (CheckSummary), `revised` (bool: the skeptic's
    revision was taken);
  - evidence: `tools` (tool name → calls, from the evidence stored in the run's window),
    `observability_tools` (tool names cited);
  - `duration_seconds` (or null), `cost_usd` (always null here), `agreement` (or null).
- **TriageStore** (Protocol):
  - `write(record)`;
  - `get(run_id) -> TriageRecord | None`;
  - `records(limit) -> list[TriageRecord | Unreadable]`.

  It has two adapters: files and memory.

### State transitions

```text
open --check passes--------------------------------> checked
open --check fails, retry--------------------------> open (attempts 1)
open (attempts 1) --check fails--------------------> inconclusive (final)
checked --skeptic revision passes------------------> checked (revised)
checked --skeptic revision fails-------------------> checked (kept, failure noted)
checked | inconclusive --record_agreement----------> same outcome, agreement set
open, read 24 h after start------------------------> shown as abandoned (not written)
```

## Services (`services/triage.py`)

- **`begin(text, alert_time, config, now, stores) -> data`**: parses, resolves, computes the
  windows and settings, resolves the ticket format, and writes the open record.
- **`check_verdict(run_id, verdict_json, …) -> data`**: validates, calls `check`, applies
  research R9, and writes the record.
- **`record_agreement(run_id, answer, reason, …)`**.
- **`search_iac` / `read_iac`**: the confinement and skip rules of research R6, over a
  `FileReader` port. Its adapter is the local file system.
- **`render_runs(records)` / `render_record(record)`**: for the CLI.
