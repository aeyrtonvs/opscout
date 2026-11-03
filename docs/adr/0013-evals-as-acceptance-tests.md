---
status: accepted
date: 2026-11-03
decision-makers: repository maintainer
---

# Evals are the acceptance tests of agent behavior

## Context and Problem Statement

A skill is a prompt, so a change can make it worse without any test failing. Constitution
Principle VII requires evals that trace back to the acceptance scenarios of a spec.

Facts (official docs and local CLI, 2026-11-03): `claude plugin eval` runs the eval cases in the
plugin's `evals/` directory (`prompt.md` plus `graders/*.md`). The deterministic graders are
`regex`, `tool_used`, `tool_order` and `file_exists`. The model-based graders are `llm` (majority
of three votes) and `baseline`. It runs a no-plugin arm and reports the score delta, can mock MCP
servers, and accepts `--threshold` and `--max-cost-usd`. The documented CI credentials are an
API key or cloud-provider credentials.

## Decision Outcome

- Each skill has an eval suite. Each acceptance scenario of its spec maps to at least one case,
  and the case name carries the trace (for example `003-us1-s2`).
- Deterministic graders come first. An LLM grader is used only for qualities that cannot be
  asserted, with its rubric in the grader file.
- Public suites use synthetic fixtures. Suites built on real samples live in the private
  configuration repository and run only locally.
- MCP tools are mocked in evals.
- Gate: the score is at or above the threshold and does not drop below the recorded baseline.
  Suites run locally before every release, and in CI only on demand, with an API key and a cost
  ceiling.
- Runs the user disagreed with (Principle IX) become candidate eval cases.
- A model change is a harness event: switching a skill's `model`, or adopting a new model,
  requires its suite to pass first (ADR-0018).

### Consequences

- Good, because regressions in agent behavior become visible and block a merge.
- Bad, because evals consume plan quota or API credit; mitigated by running them locally, on
  demand in CI, and under a cost ceiling.
- Bad, because LLM graders vary between runs; mitigated by majority voting and by preferring
  deterministic graders.

### Confirmation

The release checklist includes the eval report. A skill pull request without its eval cases
does not pass review.
