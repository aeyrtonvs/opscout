---
status: accepted
date: 2026-11-03
decision-makers: repository maintainer
---

# The development toolchain is pinned through uv; neither local use nor development needs containers

## Context and Problem Statement

The gates of ADR-0016 need tools beyond Python: just, pre-commit, gitleaks, actionlint and
zizmor. If each contributor installs them globally, versions drift between clones and CI,
and setting up a clone becomes a list of manual steps. Running the project in Docker was
proposed as the way to standardize. The question covers both audiences: users, who install
the plugin, and contributors, who work on this repository.

## Decision Drivers

- One documented prerequisite set, and the same tool versions locally and in CI.
- The runtime depends on the host: the user's own Claude Code and its login in the OS
  keychain (ADR-0012), launchd (ADR-0006), the keychain for the harness's tokens
  (Principle III), `~/.claude` session history (the daily standup), the local SSO token cache
  (sso-check), and the private configuration path (ADR-0002).
- The constitution: the agent runtime is the user's own, unmodified Claude Code, and the
  engine never stores or proxies Claude credentials.
- Supply chain (ADR-0016): exact versions with hashes, and automated updates.
- Simplicity (Principle X): no new tool where an existing one covers the need.

## Considered Options

- Global installs, documented in CONTRIBUTING (Homebrew or similar)
- The toolchain pinned through uv: a `dev` dependency group, plus pre-commit hooks pinned by
  revision
- A Docker image for the runtime on the user's machine (plugin's MCP server, daemon)
- A dev container for development
- A polyglot version manager (mise, asdf, aqua) or Nix

## Decision Outcome

Chosen option: "the toolchain pinned through uv", because uv is already a prerequisite
(ADR-0004), it locks every tool with hashes in `uv.lock`, CI uses the same lockfile, and it
adds no new tool.

**Prerequisites.**

- Users: Claude Code and uv. uv fetches the Python it needs; the plugin starts a pinned
  package version (how is decided in the MCP server's spec, PLAN.md §9).
- Contributors: git, uv and Claude Code (needed for `claude plugin validate` and evals).
  Nothing else is installed globally.

**How each tool is pinned.**

| Tool | Pinned by |
|---|---|
| Python | `.python-version` (minimum supported, 3.13) and `requires-python` |
| uv | `[tool.uv] required-version` in `pyproject.toml` |
| ruff, mypy, pytest, import-linter, pre-commit, zizmor | `dev` dependency group, locked in `uv.lock` |
| just | `rust-just` (PyPI wheels of the upstream binary), `dev` group |
| gitleaks, actionlint | their upstream pre-commit hooks, pinned by `rev` (`language: golang`; pre-commit bootstraps Go if it is missing) |

Rule: a new development tool goes into the `dev` group or into a pre-commit hook pinned by
revision. It is never added as a global install instruction. Non-Python binaries are taken
from a PyPI package that ships the upstream binary as wheels, or else from the upstream
pre-commit hook.

**Setting up a clone.** `uv sync` installs the toolchain; `uv run just setup` installs the
git hooks; `uv run just check` runs the local gates. CI installs only uv (pinned action) and
runs `uv sync --locked` and the same `just` recipes.

**Why not containers.** This covers development and the local deployment of ADR-0006.

- Runtime in Docker on the user's machine: on macOS a container runs in a Linux VM. It has no
  access to the keychain, so the user's Claude Code login is not available inside it; a token
  would have to be passed in, which ADR-0012 keeps as a fallback, not the default. launchd
  does not exist there, and the session history, the SSO cache and the private configuration
  would need bind mounts. It also replaces uv with Docker Desktop as the user's prerequisite:
  a heavier install that needs a paid subscription for professional use in larger
  organizations.
- Hosted: the foreseen hosted shape, a personal VM (ADR-0021), installs the same package with
  uv and needs no container either. If a container image is ever wanted, it is built from the
  same `uv.lock`, so this decision is its base, not an obstacle.
- Dev container: the macOS-specific code (launchd, keychain) cannot be exercised in it, and
  CI already covers Linux. It is reconsidered if a contributor needs Codespaces or a Linux
  workstation; it would then reuse the same `uv sync`, not a second toolchain definition.
- mise, asdf, aqua or Nix: each adds a tool and a second lockfile, and uv already covers
  every tool in the table.

### Consequences

- Good, because a clone is ready with one prerequisite plus Claude Code, and local results
  match CI.
- Good, because Dependabot's `uv` ecosystem updates the whole toolchain, not only runtime
  dependencies.
- Bad, because `rust-just` is a third-party repackaging of the upstream binary, which adds
  one link to the supply chain. Mitigations: `uv.lock` pins its hashes; just's own
  installation docs list it; updates are reviewed like any dependency. If it is abandoned,
  this decision is revisited for just.
- Bad, because the first pre-commit run downloads Go to build gitleaks and actionlint: slow
  once, and it needs the network.
- Neutral: macOS-specific code is tested only on macOS hosts, which CI already includes
  (ADR-0016).

### Confirmation

- CI workflows install only uv and run `uv sync --locked`. A workflow step that installs a
  development tool by other means (Homebrew, apt, curl) fails review, and a lockfile out of
  sync with `pyproject.toml` fails `--locked`.
- CONTRIBUTING lists git, uv and Claude Code as the only prerequisites.

## More Information

Related: ADR-0004 (Python and uv), ADR-0006 (local, macOS first), ADR-0012 (the user's own
`claude -p`), ADR-0016 (gates and supply chain), ADR-0021 (portability and the foreseen
hosted shape).

Checked 2026-11-03:

- PyPI: `rust-just` 1.59.0 (macOS and Linux wheels; repository `gnpaone/rust-just`),
  `zizmor` 1.32.0 (macOS and Linux wheels), `pre-commit` 4.7.0, `uv` 0.13.7.
  `actionlint-py` 1.7.12.25 ships no wheels: its sdist downloads the upstream release at
  install time and checks it against SHA-256 sums it carries. actionlint therefore comes
  from its upstream pre-commit hook.
- pre-commit documentation, `golang` language: "new in 3.0.0: pre-commit will bootstrap go
  if it is not present".
- just README, installation table: `uv tool install rust-just` and `pipx install rust-just`.
- gitleaks and actionlint `.pre-commit-hooks.yaml`: hooks `gitleaks` and `actionlint`, both
  with `language: golang`.
- Docker Desktop license page (docs.docker.com/subscription/desktop-license): free for small
  businesses (fewer than 250 employees and less than $10 million in annual revenue), personal
  use, education and non-commercial open source; a paid subscription is required for
  professional use in larger organizations.
