# Implementation Plan: Read-only identity

**Branch**: `feat/010-readonly-identity` | **Date**: 2026-11-05 | **Spec**: [spec.md](spec.md)

## Summary

The reference identity ships inside the package as documents with placeholders (R7).

**The read-only identity** has:

- AWS's `ViewOnlyAccess` for configuration metadata (Q1)
- six capability policies with exact action names: secret metadata, metrics, logs, recent
  changes, cost and cluster
- a guardrail that explicitly denies secret values, credential issuance, plaintext-secret
  reads (Q2), data-plane reads, and sessions and shells (R4)
- AWS's `ReadOnlyAccess` as the permissions boundary, the cap that keeps every write out
  even when something else is attached (R2)

**The host identity is separate and optional**, because `ssm:SendCommand` is a write (R2,
R5). It may send only seven fixed Linux documents (R5), and its own boundary is its
capability.

**The cluster side** is an EKS access policy, `AmazonEKSViewPolicy`, and a binding to
Kubernetes' `view` role (R6).

**A pure evaluator in the core** proves the properties offline. It uses a recorded catalog
of every AWS action with its access level (R1) and recorded copies of the two managed
policies:

- every secret read and every write is denied, even with `Allow *` added
- the exceptions hold only on their resources
- every declared read is allowed
- nothing is granted outside a declared capability
- the host documents equal the reference
- the cluster documents bind only the view level

**Commands**: `opscout identity check [DIR]` runs the same proofs on an instantiated copy,
and a pre-commit hook runs it in the infrastructure repository (Q3). `opscout identity
export DIR` writes the editable tree. `tools/identity_refresh.py` refreshes the records as a
reviewed change.

## Technical Context

**Language/Version**: Python ≥ 3.13

**Primary Dependencies**: none new. The code uses stdlib `json`, `re`, `importlib.resources`
and `urllib` (only the development refresh tool, with `truststore`), plus the existing
`pyyaml` and `pydantic`.

**Storage**: package data under `src/opscout/data/identity/`: the reference documents, the
catalog, the managed-policy copies and the reviewed deny list. No run records, no
configuration section.

**Testing**: pytest.

- The evaluator is tested on small hand-written policies, then on the reference tree, then
  on planted-fault copies of it (FR-020).
- The injection corpus is tested against the host parameter patterns.
- A test confirms the catalog's shape and records its date.
- Nothing in the tests uses the network or an AWS account.

**Target Platform**: any OS that the engine supports. The check is pure computation on
files.

**Project Type**: CLI and library (the engine), plus reference documents.

**Performance Goals**: the check runs in under 2 seconds on the full catalog of about 20,000
actions, and adds less than 10 seconds to the suite (SC-004).

**Constraints**:

- offline, read-only, and fail closed on anything it cannot prove
- fake values only (Principle I)
- each AWS document is at most 6,144 non-whitespace characters (R8)
- no new dependency

**Scale/Scope**:

- 457 services and about 20,000 actions in the catalog
- 2 identities and 9 AWS documents
- 7 host documents and 2 cluster documents

## Constitution Check

| Principle | Check | Result |
|---|---|---|
| I. Public engine, private data | Placeholders are reserved values (`123456789012`, `example-prod`, `opscout-readonly`); the catalog and managed-policy copies are AWS's public data; nothing from the maintainer's environment | Pass |
| II. Read-only by construction | This is the gate Principle II asks for: an identity whose writes are capped by a boundary and proved denied in code; host access only through fixed documents; every capability declared with its agents | Pass |
| III. Secrets | Secret values, credential issuance and plaintext-secret reads are denied and proved; parameters' existence stays readable; cluster view excludes Secrets | Pass |
| IV. A human approves outward actions | Nothing is applied or sent: the check and export are local; instantiation and the live check are done by a person | Pass |
| V. Configuration over code | No organization-specific branch; the instantiated copy lives in the employer's repository; the engine needs no configuration section | Pass |
| VI. Deterministic gathering | The proofs are code over recorded data; no model involved | Pass |
| VII. Specified, tested, evaluated | Tests first; planted faults per failure kind; no agent behavior, so no eval suite | Pass |
| VIII. Ports and adapters | The evaluator and checks are pure (core and services); one adapter reads files and package data; `identity` is the first user | Pass |
| IX. Observable runs | Not an agent run; the check prints its catalog date and counts | N/A |
| X. Standards; simplicity | AWS's own published reference, IAM JSON, SSM schema 2.2, Kubernetes RBAC; no new dependency; no Terraform module | Pass |

Post-design re-check: unchanged. The design splits host commands into a second identity
(R2), which tightens Principle II rather than relaxing it. The spec is updated in the same
pull request.

## Project Structure

### Documentation (this feature)

```text
specs/010-readonly-identity/
├── spec.md, plan.md, research.md, data-model.md, quickstart.md
├── contracts/commands.md, contracts/documents.md
├── checklists/requirements.md
└── tasks.md   (/speckit-tasks)
```

### Source Code (repository root)

```text
src/opscout/core/identity.py            # Statement, Policy, Identity, Capability, Catalog,
                                        #   Finding, Report; the evaluator (exact, robust)
src/opscout/services/identity.py        # the proofs: guardrail, writes, exceptions, reads,
                                        #   undeclared grants, sizes, hosts, cluster
src/opscout/adapters/identity_files.py  # read a tree (JSON, YAML) and the package data
src/opscout/entrypoints/identity.py     # wiring for check and export
src/opscout/entrypoints/cli.py          # opscout identity check | export
src/opscout/data/identity/              # catalog.json, managed/, guardrail-actions.json,
                                        #   capabilities.json, aws/, ssm/, eks/, kubernetes/
tools/identity_refresh.py               # refresh catalog and managed copies (dev only)
.pre-commit-hooks.yaml                  # + opscout-identity-check
tests/unit/identity/                    # test_evaluator, test_catalog, test_reference,
                                        #   test_faults, test_hosts, test_cluster, test_sizes,
                                        #   test_commands, test_refresh, test_traceability,
                                        #   faults/ (planted copies as patches)
docs/reference/identity.md              # instantiate (role and permission set, Terraform),
                                        #   capabilities, live check, credentials
docs/PLAN.md                            # §6 layout, §7 status, §9 rule-3 gate item
```

**Structure Decision**: the existing layers. The evaluator and the proofs are pure and take
parsed documents, so the same code proves the reference in this repository's tests and an
instantiated copy through the command. Only the adapter reads files.

## Complexity Tracking

| Item | Why needed | Simpler alternative rejected because |
|---|---|---|
| A second identity for host commands | `ssm:SendCommand` is a write, and the only boundary that caps writes and fits is AWS's `ReadOnlyAccess` (R2) | One identity with a hand-written boundary does not fit AWS's size limit, and one without a boundary fails US1 scenarios 3 and 5 |
| A recorded catalog of about 20,000 actions in the package | It is the only offline basis for "every write is denied" (FR-011) and for the check run in another repository | A hand-maintained list of writes would always be incomplete |
