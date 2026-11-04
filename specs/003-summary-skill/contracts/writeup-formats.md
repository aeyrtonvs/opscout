# Contract: `opscout writeup formats`

```text
opscout writeup formats [--config DIR]
```

Resolves the configuration directory as `opscout config validate` does (an empty `--config`
counts as absent), reads it only through the loader, and prints the write-up formats as
Markdown. The exit status is always 0, because a skill injection that fails aborts the skill
(FR-010).

## Output

When the configuration was read:

```markdown
# Write-up formats

Source: <dir>/config.yaml (from --config)
Language: <language>            ← only when set

## Rules for every format
- <shared built-in rule>
- <configured shared rule>

## ticket (built-in)
<description>
Sections, in order: What happened; Why; What was done; What is pending
At most 12 lines.
Rules:
- <rule>
```

When the directory or the file is missing, the source line names the problem and its
source, such as `Source: none, <dir>: no such directory (default); using the built-in
formats`, followed by the built-in formats.

When the configuration is invalid:

```markdown
# Write-up formats

The configuration in <dir> has <n> problem(s), so no write-up format is available.
Run `opscout config validate --config <dir>` to list them.
```

The same configuration always prints the same text (FR-011).
