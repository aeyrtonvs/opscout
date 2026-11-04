---
name: ship
description: Ships the current change by the user's conventions - creates a conventionally named branch when the work is on a protected branch, commits with a Conventional Commit message and the configured trailer, pushes the branch with the user's confirmation, and opens a draft pull request on GitHub. Use when the user asks to commit and push, ship, or open a pull request for their change.
argument-hint: "[what to ship]"
allowed-tools:
  - Bash("${CLAUDE_PLUGIN_ROOT}/bin/opscout" ship *)
  - Bash(git status *)
  - Bash(git diff *)
  - Bash(git symbolic-ref --short refs/remotes/origin/HEAD)
  - Bash(git remote get-url *)
  - Bash(git switch -c *)
  - Bash(git add *)
  - Bash(git commit -m *)
  - Bash(git push -u origin *)
  - Bash(gh auth status *)
  - Bash(gh pr create --draft *)
---

# Ship

## Contract

- **Deliverable:** the user's change committed on a feature branch with a Conventional
  Commit message that ends with the configured trailer, that branch pushed after the user
  confirms, and a draft pull request on GitHub; then a short report: branch, commit subject,
  push result, and the pull request's link.
- **Constraints:** the conventions below; every command as its own plain command, so the
  plugin's push guard can read it; stage only what the user asked to ship.
- **Non-goals:** never push to a protected branch, never force-push, never merge a pull
  request, never delete a branch, never rewrite history that was pushed (no rebase, amend or
  reset of pushed commits), never skip hooks (`--no-verify`), and never print a secret
  value found in the change.
- **Acceptance:** the branch passes `ship check-branch`, the message passes
  `ship check-message`, the push targets only the new branch, and the pull request is a
  draft.

## The conventions

!`"${CLAUDE_PLUGIN_ROOT}/bin/opscout" ship rules --config '${user_config.config_dir}'`

## Procedure

1. **Check the conventions.** If the text above says the configuration has problems, stop:
   give the user the exact command the text prints to list them.
2. **Look at the state**: `git status --short --branch`, then `git diff --stat` and
   `git diff --staged --stat`. Stop and say why if there is nothing to commit, if HEAD is
   detached, or if a merge, rebase or cherry-pick is in progress.
3. **Decide what to ship**: only the change the user asked for. If it is unclear which
   files belong to it, ask. Never stage files that hold secrets, such as `.env` files.
4. **Branch.** Read the remote's default branch with
   `git symbolic-ref --short refs/remotes/origin/HEAD` (drop the `origin/`). If the current
   branch is protected by the conventions above, or is that default branch, choose a name
   by the branch pattern (the type that fits the change, a short slug), check it with
   `"${CLAUDE_PLUGIN_ROOT}/bin/opscout" ship check-branch <name> --default-branch <default>`
   until it passes, then run `git switch -c <name>`. On a feature branch, stay on it.
5. **Stage** the files of the change with `git add <paths>`, naming them.
6. **Message.** Write a Conventional Commit subject whose type fits the change, an optional
   body that says why, and the trailer as the last paragraph. Check it with
   `"${CLAUDE_PLUGIN_ROOT}/bin/opscout" ship check-message -m "<subject>" [-m "<body>"] -m "<trailer>"`
   until it passes, then commit with the same paragraphs:
   `git commit -m "<subject>" [-m "<body>"] -m "<trailer>"`.
7. **Push** the branch, as its own command: `git push -u origin <branch>`. The plugin's guard
   asks the user to confirm. If the push is refused or not confirmed, stop and report; never
   try another form.
8. **Pull request.** If `git remote get-url origin` is a GitHub address and `gh auth status`
   succeeds, open a draft: `gh pr create --draft --base <base> --head <branch> --title
   "<subject>" --body "<body or a short summary>"`, where `<base>` is the conventions' base.
   Otherwise, say that the pull request cannot be opened from here yet, and give the branch.
9. **Report** the branch, the commit subject, the push result and the pull request's link,
   in a few lines.

If the user asks to push to a protected branch, explain that protected branches change only
through a pull request, and ship from a feature branch instead.
