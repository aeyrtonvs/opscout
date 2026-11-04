# Security policy

## Supported versions

opscout has no release yet. Until 1.0, only the latest release receives fixes.

## Reporting a vulnerability

Report it privately through GitHub: open the repository's **Security** tab and choose
**Report a vulnerability**
([direct link](https://github.com/aeyrtonvs/opscout/security/advisories/new)). Do not open a
public issue.

Describe what is affected, how to reproduce it with fake values, and the impact you expect.
Do not include real secrets or real organizational data; describe them instead.

opscout has a single maintainer, who aims to acknowledge a report within 7 days and to give
a status update at least every 14 days until it is resolved. Fixes are published with an
advisory that credits the reporter, unless you prefer to stay anonymous.

## What matters most

Given what opscout is for, these are the most serious findings:

- a way to make an agent change a system it investigates, despite the read-only design;
- a way to make an agent read, print or store a secret's value;
- prompt injection through an alert, a log or a chat message that leads to either of the
  above, or to data leaving the machine without the user's approval;
- a way for data from a private configuration to reach this public repository or a
  release.
