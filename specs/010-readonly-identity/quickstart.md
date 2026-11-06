# Quickstart: validate the read-only identity

1. Tests and gates (offline; no AWS account, no network):

   ```sh
   uv run just test tests/unit/identity
   uv run just check
   ```

2. Check the packaged reference, then confirm that a planted fault fails it:

   ```sh
   opscout identity check                          # Pass.
   opscout identity export /tmp/opscout-identity
   # edit /tmp/opscout-identity/aws/guardrail.json: delete the DenySecretValues statement
   opscout identity check /tmp/opscout-identity    # secret-allowed: … ; exit 1
   ```

3. Confirm that the wheel carries the records:

   ```sh
   uv build --wheel && unzip -l dist/opscout-*.whl | grep data/identity
   ```

4. Refresh the records, as the maintainer does now and then; review the diff before
   committing:

   ```sh
   uv run python -m tools.identity_refresh
   opscout identity check
   git diff --stat src/opscout/data/identity
   ```

5. The live check is manual and comes after someone instantiates the identity in a sandbox
   account (FR-021). Follow `docs/reference/identity.md`, "Live check", and record each
   probe's outcome in the spec's Actuals and in PLAN.md.
