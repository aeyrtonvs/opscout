# Contributing to opscout

Thank you for helping. This guide is short; [`AGENTS.md`](AGENTS.md) and the
[constitution](.specify/memory/constitution.md) hold the full rules.

## Rules that never bend

1. **No real data.** This repository is public. Never commit company or product names,
   account IDs, profile names, hostnames, IP addresses, chat channel or user IDs, ticket
   keys, alert texts from a real workspace, costs or contact details, including in commit
   messages. Use reserved values: account `123456789012`, the RFC 5737 address ranges (such
   as `192.0.2.10`), `example.com`, `example-prod`, `#alerts-example` and ticket keys such as
   `EXAMPLE-123`.
2. **Agents are read-only.** They never change the systems they investigate, and they report
   whether a secret exists, never its value.
3. **Nothing leaves your machine without asking.** Creating a remote, pushing and publishing
   are always confirmed by a person.

## Setting up

You need git, [uv](https://docs.astral.sh/uv/) and Claude Code. Nothing else is installed
globally (ADR-0020).

```sh
git clone https://github.com/aeyrtonvs/opscout.git
cd opscout
uv sync              # the toolchain, from uv.lock
git config user.email "ID+login@users.noreply.github.com"   # your GitHub no-reply address
uv run just setup    # the pre-commit, commit-msg and pre-push hooks
uv run just check    # the pre-commit gates, on every file
```

The hooks accept only a GitHub no-reply commit address, so set it before your first
check or commit. GitHub shows it under *Settings → Emails*.

The first `just setup` builds gitleaks and actionlint, so it downloads Go if you do not have
it. Later runs are fast. On macOS, if it fails with `CERTIFICATE_VERIFY_FAILED`, your Python
from python.org lacks its certificate bundle: run its *Install Certificates* command once, or
run `SSL_CERT_FILE=/etc/ssl/cert.pem uv run just setup`.

### The leak check

The hooks check every commit, and again every commit you push, for real data in three
layers (ADR-0015). File names are checked as well as contents.

1. Generic patterns: secrets (gitleaks), account IDs, IP addresses outside the
   documentation ranges, chat and ticket ID shapes, internal hostnames, cloud resource
   endpoints and e-mail addresses.
2. A private deny-list of your organization's terms. It never lives here: the hook reads
   `leak-denylist.txt` from your private configuration directory (`OPSCOUT_CONFIG`, or else
   `~/.config/opscout/`). It holds one case-insensitive regular expression per line; lines
   that start with `#` are comments. Without the file, the hook warns and runs the other
   two layers. If your clone must never commit without it, make that an error:
   `git config opscout.requireDenylist true`.
3. The author and committer e-mail addresses must be GitHub no-reply addresses.

A false positive from the generic patterns goes in `tools/leak_allowlist.toml`, with the
reason it is not real data. Never put a real value there. gitleaks checks staged changes
when you commit, and the whole history before you push and in CI.

## How work is done

- **A feature, or a change in specified behavior,** follows Spec Kit: `/speckit-specify`,
  `/speckit-clarify`, `/speckit-plan`, `/speckit-tasks`, `/speckit-analyze`,
  `/speckit-implement`, on a `feat/NNN-slug` branch.
- **A fix, chore or documentation change** is a plain pull request from a `fix/…`,
  `chore/…` or `docs/…` branch. Its description states the deliverable, constraints,
  non-goals and acceptance.
- **A cross-cutting decision** is an ADR in [`docs/adr/`](docs/adr/), from `template.md`.
- **Tests come first**, always. Skills also need eval cases traced to their spec.

## Commits and pull requests

- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/); the
  `commit-msg` hook checks them.
- Commits are signed.
- A commit written with an AI agent ends with an `Assisted-by: <agent/model>` trailer.
- Pull requests target `main` and merge only with every check green.

## Updating the toolchain

Dependabot proposes updates to `uv.lock`, the GitHub Actions and the pre-commit hooks. To
update the hooks by hand, run `uv run pre-commit autoupdate --freeze`.

## License

By contributing, you agree that your contributions are licensed under
[Apache-2.0](LICENSE), as section 5 of the license states. Copyright stays with each
contributor; together they are "The opscout Authors" of [`NOTICE`](NOTICE), as recorded in
the git history.

Everyone taking part follows the [Code of Conduct](CODE_OF_CONDUCT.md).
