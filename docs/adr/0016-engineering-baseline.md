---
status: accepted
date: 2026-11-03
decision-makers: repository maintainer
---

# Engineering baseline: quality gates, supply chain, lockstep releases

## Context and Problem Statement

The repository is a portfolio piece and part of the maintainer's daily work. It should meet
the practices reviewers look for without slowing a single maintainer down.

## Decision Outcome

**Local gates** (pre-commit; `just check` runs the same set): ruff format and lint, mypy
`--strict`, pytest, import-linter, the leak check (ADR-0015), gitleaks, a Conventional Commit
message check, and `claude plugin validate --strict` for the plugin and marketplace
manifests (amended 2026-11-03, below).

**CI** (GitHub Actions): the same gates on macOS and Linux, on the minimum supported and the
latest stable Python; a coverage gate on `core` and `services`; CodeQL; dependency review;
zizmor for workflow security; OpenSSF Scorecard once the repository is public. Actions are
pinned by commit SHA, workflow tokens are read-only by default, and Dependabot updates `uv`
and `github-actions`.

**Releases**: Conventional Commits drive release-please. The Python package and the plugin
share one version (lockstep): release-please bumps `pyproject.toml` and `plugin.json` together
and tags `vX.Y.Z`. Each GitHub release carries a CycloneDX SBOM and build-provenance
attestations. Publishing to PyPI uses Trusted Publishing, with no long-lived tokens. The
maintainer confirms every publish (Principle IV).

**Repository governance**: LICENSE and NOTICE, SPDX headers, README, CONTRIBUTING, SECURITY.md
with private vulnerability reporting, CODE_OF_CONDUCT, issue forms, a pull request template
(spec link, leak checklist, ADR question), CODEOWNERS, a ruleset on `main` (pull request
required, checks required, linear history), and signed commits.

**Target**: OpenSSF OSPS Baseline Level 1 at the first public release; the OpenSSF Best
Practices "passing" badge afterwards.

### Consequences

- Good, because quality and supply-chain posture are verifiable, and releases are
  reproducible and attributable.
- Bad, because the setup takes about a day, mostly templates.
- Bad, because lockstep versions bump the plugin even when only the daemon changed.

### Confirmation

CI status, Scorecard results and release assets are visible in the repository.

## More Information

**Amended 2026-11-03.** The manifests were also to be checked against a JSON Schema, but none
is published for `plugin.json` or `marketplace.json`: the documentation describes `$schema`
only for editor autocomplete, and Claude Code 2.1.318 embeds none. `claude plugin validate
--strict` is the manifest gate instead. It rejects unknown fields, unknown `userConfig` keys
and types, a marketplace entry whose version differs from `plugin.json`, and a source path
that leaves the repository. A schema check is added if Anthropic publishes one. CI runs the
validator with the Claude Code CLI bundled in the `claude-agent-sdk` wheels (ADR-0020).
