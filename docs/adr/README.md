# Architecture Decision Records

Decisions that shape more than one feature are recorded here, one file per decision, in
[MADR 4.0](https://adr.github.io/madr/) format (start from [`template.md`](template.md)).
Decisions local to one feature stay in that feature's `specs/NNN-slug/research.md`.

- **Lifecycle:** `proposed` → `accepted` | `rejected`; later `deprecated` or
  `superseded by ADR-NNNN`. An accepted ADR is not rewritten; a change is a new ADR that
  supersedes it.
- **When to write one:** the decision is hard to reverse, affects several features, or
  changes how the constitution is applied.
- **Numbering:** the next free four-digit number; the title states the decision, not the
  problem.

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions as MADR files | accepted |
| [0002](0002-public-engine-private-config.md) | Public engine, private configuration repository | accepted |
| [0003](0003-plugin-marketplace-and-daemon.md) | Claude Code plugin from a self-hosted marketplace, plus a separate daemon | accepted |
| [0004](0004-python-uv.md) | Python and uv for the daemon | accepted |
| [0005](0005-ports-and-adapters.md) | Integrations behind adapter interfaces; only used adapters are built | accepted |
| [0006](0006-local-macos-first.md) | Run locally, macOS first; team-wide automation stays out of this repository | accepted |
| [0007](0007-english-apache-2.md) | English for the repository; Apache-2.0 license | accepted |
| [0008](0008-spec-driven-development-spec-kit.md) | Spec-Driven Development with GitHub Spec Kit | accepted |
| [0009](0009-open-standards-agent-artifacts.md) | AGENTS.md, Agent Skills and MCP as the formats for agent-facing artifacts | accepted |
| [0010](0010-defense-in-depth-read-only.md) | Read-only is enforced in five layers, strongest first | accepted; decision 1 amended by 0023 |
| [0011](0011-code-led-tools-mcp-server.md) | Deterministic adapters exposed as a local read-only MCP server and a CLI | accepted |
| [0012](0012-runner-port-claude-cli.md) | Runner port; the user's own `claude -p` is the default runner | accepted |
| [0013](0013-evals-as-acceptance-tests.md) | Evals are the acceptance tests of agent behavior | accepted |
| [0014](0014-configuration-contract.md) | Configuration contract: a versioned schema, validated in both repositories | accepted |
| [0015](0015-leak-prevention-tooling.md) | Leak prevention enforced by tooling, with the deny-list kept private | accepted |
| [0016](0016-engineering-baseline.md) | Engineering baseline: quality gates, supply chain, lockstep releases | accepted |
| [0017](0017-docs-as-code.md) | Documentation as code: Diátaxis, Zensical, Mermaid | accepted |
| [0018](0018-harness-engineering-practices.md) | Harness-engineering practices for the development workflow and the product's agents | accepted |
| [0019](0019-project-name-opscout.md) | The project is named opscout; the working name ops-harness is retired | accepted |
| [0020](0020-toolchain-pinned-through-uv.md) | The development toolchain is pinned through uv; neither local use nor development needs containers | accepted |
| [0021](0021-local-first-portable-by-construction.md) | Local-first and portable by construction; the foreseen hosted shape is a personal VM | accepted |
| [0022](0022-plugin-runs-the-engine-through-uv.md) | The plugin runs the engine through a uv launcher in its `bin/` | accepted |
| [0023](0023-read-only-identity-recommended.md) | The read-only identity is recommended, not required; every integration is optional | accepted |
