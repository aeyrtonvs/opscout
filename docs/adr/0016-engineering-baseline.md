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

**Local gates** (pre-commit; `just check` runs its pre-commit stage): ruff format and lint, mypy
`--strict`, pytest, import-linter, the leak check (ADR-0015), gitleaks, a Conventional Commit
message check, and `claude plugin validate --strict` for the plugin and marketplace
manifests (amended 2026-11-03, below).

**CI** (GitHub Actions): the tests on macOS and Linux, on the minimum supported and the
latest stable Python, and the other gates on Linux; a coverage gate on `core` and
`services`; CodeQL; dependency review; zizmor for workflow security; OpenSSF Scorecard once
the repository is public. Actions are pinned by commit SHA, workflow tokens are read-only by
default, and Dependabot updates `uv`, `github-actions` and `pre-commit`.

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

**Amended 2026-11-03, after an independent review of Phase 0a.** The gates are split by
stage: `just check` runs the pre-commit stage on every file; the commit-msg stage checks
each message; a pre-push stage checks every commit about to leave the machine, including
commits that skipped the other hooks. gitleaks checks staged changes at commit time and
the whole history before a push and in CI. The tests run on both operating systems, the
other gates once on Linux, and Dependabot also updates the pre-commit hooks.

**Amended 2026-11-04.** The macOS test jobs are no longer required checks of the ruleset on
`main`. GitHub's hosted macOS arm64 runners were twice unavailable for pull request #4: the
jobs waited 15 minutes for a runner, were cancelled without running a step, and blocked the
merge although every other check passed. The macOS jobs still run on every pull request and
push, as information, and CI also runs the tests daily on `main` and on demand, so a
macOS-only regression shows within a day. The required checks are the Linux tests (minimum
and latest Python), the leak check, manifests and workflows job, dependency review, and
CodeQL. The engine has no macOS-specific code yet; whether macOS should block again is
decided with the first macOS adapter (launchd, keychain) in Phase 1.

**Amended 2026-11-05 (spec 007, daemon-core).** The macOS test jobs stay informational. The
first macOS-specific code, the launchd adapter, reaches launchd through a seam
(`ServiceManager`), so its logic is tested on every operating system with a fake; the
keychain adapter is tested on an in-memory `keyring` backend. One test runs against the
real launchd: it is marked `launchd` and runs only on macOS in a GUI session, that is on
the maintainer's machine with every `just fast`, and in CI's macOS jobs (every pull request,
informational, and daily on `main`) when the runner has a GUI session; elsewhere it is
skipped and says why. A launchd regression thus shows before a merge or within a day,
without letting a missing hosted runner block a merge.
