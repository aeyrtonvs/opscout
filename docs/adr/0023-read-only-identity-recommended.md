---
status: accepted
date: 2026-11-06
decision-makers: repository maintainer
---

# The read-only identity is recommended, not required; every integration is optional

## Context and Problem Statement

ADR-0010's first layer is a dedicated read-only identity per environment, and spec 010
ships it as reference documents. Constitution 1.0.2 and AGENTS.md rule 3 made it a
requirement: agents "use a read-only identity". In practice that puts IAM work in an
employer's infrastructure repository in front of anyone who wants to try opscout. Many
users already have a narrowed role that is not strictly read-only and is theirs to judge.
A user who only wants the daily standup or the write-ups should not have to configure AWS
at all. Should opscout require its identity, and should any integration be required?

## Decision Drivers

- Read-only stays enforced by mechanisms the model cannot override (Principle II).
- No friction for features that do not touch the systems an integration reaches.
- opscout recommends what it considers correct; the user owns the risk of their own
  accounts.

## Considered Options

- Require the reference identity before any agent reaches a real system (ADR-0010 as
  written).
- Recommend the reference identity, let the user run with another identity, and keep the
  harness's own controls mandatory.
- Make every control optional, the tool surface included.

## Decision Outcome

Chosen option: "Recommend the reference identity and keep the harness's own controls
mandatory", because the controls opscout owns still hold whatever identity the user picks,
and the identity it cannot apply becomes a recommendation instead of a gate.

1. **The reference identity is recommended.** opscout ships it, documents it as the
   recommended setup and proves it with `opscout identity check`. It never requires it and
   never refuses to run with another identity.
2. **Another identity is the user's choice and risk.** opscout states which kind of
   identity a run used, the reference or the user's own, when it is configured and in
   what the run reports, and never blocks on it. How it is configured and stated is
   decided in the spec that first reaches a cloud account (ops-mcp-server).
3. **The harness's own controls stay mandatory.** They do not depend on the identity:
   - the tool surface exposes only read operations and never a secret-value API;
   - unattended runs have no general-purpose shell;
   - hosts are reached only through the allow-listed command documents;
   - replies go only to the configured output channels;
   - tool outputs are redacted.
4. **Every integration is optional.** AWS, Kubernetes, hosts, observability, code hosts,
   tickets and chat are each enabled only when configured. A missing, unconfigured or
   failing integration never blocks a feature that does not use it.

### Consequences

- Good, because opscout can be tried, and its other features used, without IAM work or
  any cloud configuration.
- Good, because the read-only guarantee for unattended runs rests on the tool surface,
  which opscout controls, rather than on IAM, which it does not.
- Bad, because a user who runs with a broader identity loses the outer layer. A defect in
  a tool, a vetted third-party server, or a shell in an interactive session then reaches
  whatever that identity allows. opscout says so; the user decides.
- Bad, because `opscout identity check` proves only the reference identity. A user's own
  identity is not verified.

### Confirmation

- Each spec that adds an integration has a requirement, with a test, that the features
  which do not use it run without it configured.
- ops-mcp-server's tool contract tests prove the surface exposes no write and no
  secret-value operation, whatever identity the server runs under.
- The ops-mcp-server spec states how a run reports the identity it used.

## More Information

Amends ADR-0010, decision 1: the dedicated identity is the recommended outer layer, not a
requirement. ADR-0010's other layers are unchanged. Constitution 2.0.0 redefines
Principle II and adds the optional-integration rule to Principle V. The live check of the
reference identity in a sandbox account (spec 010, FR-021) is still worth running, because
it validates what opscout recommends; it gates nothing.
