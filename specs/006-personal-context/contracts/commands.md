# Contract: the context commands

```text
opscout context show  [--config DIR]                     # the block; exit 0, or 2
opscout context diff  [--config DIR] [--target FILE]     # exit 0 none, 1 a change, 2 error
opscout context apply [--config DIR] [--target FILE] [--confirm CODE]
                                                         # exit 0 written or none, 1 not confirmed, 2 error
```

- `diff`: a unified diff (`--- <target>`, `+++ <target> (opscout)`), then
  `Confirmation code: <code>` and the apply command to run; or `<target> is up to date.`
- `apply` without `--confirm`: in a terminal, the diff and `Write these changes to <target>?
  [y/N]`; otherwise the diff, the code, and exit 1. With a code that does not match:
  `The file or the configuration changed since that diff; run opscout context diff again.`,
  exit 1. Written: `Wrote <target>.`
- Errors (exit 2) on standard error: `opscout context: <reason>`.
