# Example configuration

`config.yaml` here is a valid opscout configuration with fake values only. The gates
validate it on every change (spec 002), so it always matches the current schema.

## Start a private configuration from it

Your real configuration never goes in this public repository. Keep it in a **private**
repository of your own:

1. Create the private repository and copy `config.yaml` into its root.
2. Point editors at the schema of the opscout commit you use, so they complete keys and flag
   mistakes. Replace the first line with:

   ```yaml
   # yaml-language-server: $schema=https://raw.githubusercontent.com/aeyrtonvs/opscout/<commit>/schemas/config.schema.json
   ```

3. Validate it:

   ```sh
   opscout config validate --config <path to the private repository>
   ```

   Without `--config`, opscout reads `OPSCOUT_CONFIG`, then `~/.config/opscout/`.

4. Validate it on every commit with the hook this repository publishes. In the private
   repository's `.pre-commit-config.yaml`:

   ```yaml
   repos:
     - repo: https://github.com/aeyrtonvs/opscout
       rev: <commit>   # the same commit as the schema line
       hooks:
         - id: opscout-config-validate
   ```

The configuration holds no secrets: a credential is named by its keychain service, never
by its value. See [`docs/reference/configuration.md`](../docs/reference/configuration.md)
for the whole contract.
