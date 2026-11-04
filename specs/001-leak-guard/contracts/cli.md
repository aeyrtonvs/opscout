# Contract: the leak check command

```text
python -m tools.leak_check [--redact] MODE [ARGS]
```

Run through uv by the git hooks (`.pre-commit-config.yaml`) and CI
(`.github/workflows/ci.yml`).

## Modes

| Mode | Arguments | Examines |
|---|---|---|
| `files` | `PATH…` (zero or more) | contents and names of the given files |
| `tracked` | none | contents and names of every file `git ls-files` lists |
| `message` | `FILE` | the commit message in `FILE`, comment lines included, up to the scissors line |
| `identity` | none | `GIT_AUTHOR_IDENT` and `GIT_COMMITTER_IDENT` |
| `commits` | `[BASE] HEAD` | each commit of `BASE..HEAD`, or of every commit `HEAD` reaches when `BASE` is absent or all zeros |
| `pushed` | none | each commit the remote lacks, and ref names (below) |

## Inputs

| Input | Meaning |
|---|---|
| `OPSCOUT_CONFIG` | private configuration directory; default `~/.config/opscout` |
| `<config dir>/leak-denylist.txt` | the private deny-list (layer 2) |
| `tools/leak_allowlist.toml` | the public allow-list (layer 1) |
| `git config opscout.requireDenylist` | `true` makes a missing deny-list an error |
| `CI=true` | forces redaction |
| `PRE_COMMIT_FROM_REF`, `PRE_COMMIT_TO_REF` | the range pre-commit passes to `pushed` |
| `PRE_COMMIT_LOCAL_BRANCH`, `PRE_COMMIT_REMOTE_BRANCH` | the first pushed ref, local and remote names (`pushed`) |
| `PRE_COMMIT_REMOTE_NAME` | the remote whose tracking refs mark commits as already pushed |

### Ref names in `pushed` (new, FR-032)

The names checked are `PRE_COMMIT_LOCAL_BRANCH`, `PRE_COMMIT_REMOTE_BRANCH`, and every
`refs/heads/*` and `refs/tags/*` of the local repository, each without its `refs/heads/` or
`refs/tags/` prefix and checked once. Layers 1 and 2 apply; the allow-list applies to
layer 1 as everywhere else.

## Output

- Standard output: one line per finding, `<location>: <rule>: <value>`, where a redacted
  value is shown as its first two characters followed by `… (redacted)`.
- Standard error: a warning when layer 2 is skipped; after the findings, one hint per kind
  of finding (`commit-e-mail`, `private-term`, and one shared hint for layer-1 rules).
- Ref-name findings are located as `ref <name>`.

## Exit status

| Status | Meaning |
|---|---|
| 0 | nothing found |
| 1 | at least one finding, or the clone requires a deny-list that is missing |
| 2 | bad arguments, or an invalid allow-list or deny-list entry (named in the message) |
