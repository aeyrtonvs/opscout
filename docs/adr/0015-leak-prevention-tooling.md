---
status: accepted
date: 2026-11-03
decision-makers: repository maintainer
---

# Leak prevention is enforced by tooling, with the deny-list kept private

## Context and Problem Statement

Constitution Principle I requires checking every staged diff for real data. A manual check
eventually fails, and the list of sensitive terms cannot be stored in the public repository
without leaking it.

## Decision Outcome

Three layers, all in pre-commit; layers 1 and 3 also run in CI:

1. **Generic patterns**, kept in this repository: secrets (gitleaks), 12-digit account IDs
   other than the reserved examples, IPs outside the documentation ranges, chat-platform ID
   shapes, ticket-key shapes, internal-looking hostnames.
2. **Private deny-list**, kept in the private configuration repository (organization and
   product names, account IDs, profile names, hostnames, channel names) and read by the local
   hook through the configuration path. The public repository never contains the terms.
3. **Commit metadata**: author and committer e-mail must match an allow-list (for example the
   GitHub no-reply address), so a work address cannot reveal the employer.

Once the GitHub repository exists, GitHub secret scanning and push protection are enabled.

### Consequences

- Good, because the "check the staged diff" rule becomes automatic instead of a habit.
- Bad, because false positives need an allow-list file with a reason for each entry.
- Bad, because CI cannot run layer 2, so installing the local hook is part of setting up a
  clone; the contributor guide says so.

### Confirmation

A test suite of synthetic leaks that the check must catch; the hook runs in under a second on
a typical diff.
