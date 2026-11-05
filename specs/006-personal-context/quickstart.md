# Quickstart: validate the personal context

```sh
uv run just test tests/unit/context
opscout context show --config example-config
opscout context diff --config example-config --target /tmp/example/CLAUDE.md   # exit 1, a code
opscout context apply --config example-config --target /tmp/example/CLAUDE.md --confirm <code>
opscout context diff --config example-config --target /tmp/example/CLAUDE.md   # exit 0, up to date
uv run just check
```
