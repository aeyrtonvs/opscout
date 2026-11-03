---
status: accepted
date: 2026-11-03
decision-makers: repository maintainer
---

# Harness-engineering practices for the development workflow and the product's agents

## Context and Problem Statement

A practitioner guide, "Harness Engineering: How to Build AI Workflows That Never Fall Apart"
(published on X, 2026-09-12), describes a reliable agent system as three layers: the
harness (environment and memory), the loop (objective sensors and convergence) and the graph
(separate contexts for planning, implementing and reviewing). It lists five jobs for a
personal harness: turn every request into a bounded contract; give a map, not an
encyclopedia; externalize memory into durable files; build sensors before granting
autonomy; and dual-encode every rule (stated in text *and* blocked by a mechanical gate).

Most of this is already in the plan: specs as contracts (ADR-0008), durable decisions
(ADR-0001), gates and evals as sensors (ADR-0013, ADR-0016), and permissions over
instructions (ADR-0010). Comparing the two exposed gaps. This ADR records what is adopted,
where it lives, and what is deliberately left out. The practices apply twice: to how this
repository is built with a coding agent, and to the agents the product ships, since
opscout is itself a harness.

## Decision Outcome

Adopted:

1. **Dual encoding of hard rules.** Every non-negotiable rule is stated where agents read it
   (AGENTS.md, a skill) and enforced by a gate that blocks a violation. AGENTS.md names the
   gate next to each rule. A rule whose gate does not exist yet is an open item in
   PLAN.md §9. The first gap found: rule 5 ("nothing leaves the machine without asking") had
   no gate, while coding agents are often run with permission prompts bypassed. Explicit
   `ask` rules in `.claude/settings.json` close it, because they prompt even in that mode.
2. **Bounded contracts.** Every spec has a mandatory *Non-Goals* section. The constitution
   requires it, `/speckit-specify` loads the constitution, and `/speckit-analyze` reports a
   missing mandated section as critical, so no template override is needed. Every skill opens
   with a contract: deliverable (with its output schema), constraints, non-goals, and
   acceptance. For example, the summary skill's non-goal "never list what was evaluated and
   ruled out" is a correction measured in PLAN.md §1. Plain pull requests carry a four-line
   contract in their template.
3. **Sensors before "done" (development).** Claude Code project hooks run sensors while the
   agent works. After an edit to a Python file, ruff fixes and formats it and reports what is
   left. Before the agent stops, the fast checks run and block the stop once if they fail.
   The loop is bounded, so the agent cannot claim success on broken work and cannot loop
   forever. The full gates stay in pre-commit and CI.
4. **Bounded convergence and escalation.**
   - Development: if the same check fails twice on the same error, the agent stops, shows the
     exact error and proposes a fix for the human to approve.
   - Product: the runner validates every structured output against its schema. A failure gets
     one retry, carrying the validator's message. After that, the run ends as `inconclusive`
     and goes to the human, and the run log records it.
5. **Evidence grounding (product).** Every claim in a verdict cites evidence returned by a
   tool in the same run. The harness checks each citation in code: the evidence ID exists,
   and the quoted value appears in that tool's output. Verdicts also state their assumptions
   and the timezone used.
6. **Separate maker and checker.**
   - Development: after `/speckit-implement` comes `/speckit-converge`, a core Spec Kit command
     that compares code with spec, plan and tasks. Then an independent review of the diff, in
     a fresh context, against the spec and the constitution, before the pull request.
   - Product: investigation skills may add a skeptic pass that tries to refute the verdict
     using only the gathered evidence. It stays only if an eval ablation shows it improves
     accuracy, because it costs tokens.
7. **A map, not an encyclopedia.**
   - AGENTS.md stays a compact map (about 100 lines) and links to details. The constitution
     is read on demand, not imported.
   - A SKILL.md body stays under 500 lines, with details in `references/` loaded on demand.
   - MCP tools return the slice a step needs, not the whole configuration.
8. **Model changes are harness events.** Switching a skill's model, or adopting a new model,
   requires its eval suite to pass first (ADR-0013).

Not adopted:

- **A separate `HARNESS.md`.** Its sections (scope, map, verification protocol, escalation)
  are covered by AGENTS.md, an open standard, and the constitution. A third file would
  duplicate them.
- **Four attempts before human review.** Two attempts are used instead, as in the guide's own
  template ("fails twice"), which keeps cost and loops bounded.
- **Three separate workers for every task, and isolated worktrees by default.** Spec Kit
  already separates planning, implementing and reviewing. Worktrees stay optional, for
  parallel `[P]` tasks.
- **The guide's quantitative claims** (for example, that a review pass halves hallucinated
  claims). They are not taken as facts; the evals measure.

### Consequences

- Good, because rules and enforcement are paired visibly, and the rule-5 gap is closed before
  the first push.
- Good, because the product's verdicts become mechanically checkable, which strengthens
  need #1 ("cause with evidence").
- Bad, because there are hook scripts to maintain and test.
- Bad, because the skeptic pass and retries cost tokens; evals and budgets bound that cost.

### Confirmation

- Every non-negotiable rule in AGENTS.md names its gate, or has an open item.
- Hook scripts have tests: the stop hook blocks once, then lets the agent stop.
- Runner tests cover the retry-then-`inconclusive` path.
- The skeptic pass ships only with an eval ablation result.

## More Information

Source: x.com/mirku21/status/2098836008468992471 (article "Harness Engineering"). It is a
practitioner guide, not a standard; the practices are adopted on their merits for this
project.
