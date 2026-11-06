# Quickstart: validate the daily standup

1. Tests and gates (any OS; no test reads real transcripts or contacts Bitbucket):

   ```sh
   uv run just test tests/unit/standup
   uv run just check
   ```

2. In a temporary copy of your configuration, add the `standup` section with your projects
   (local paths and Bitbucket repositories), your commit identities and your Bitbucket
   login, and the job `standup` in `daemon.jobs`.

3. Preview what would be sent, counts first:

   ```sh
   opscout standup preview --counts --config <config>
   opscout standup preview --config <config>      # read it yourself: what the model would get
   ```

4. Bitbucket: create an API token with scopes (`read:pullrequest:bitbucket`,
   `read:repository:bitbucket`, `read:user:bitbucket`), store it:

   ```sh
   opscout secret set bitbucket_token --config <config>
   opscout standup preview --counts --config <config>   # Missing: none
   ```

5. Evaluations with your model (cost ceiling 0.50 USD):

   ```sh
   uv run python -m tools.standup_evals
   ```

6. One real summary by DM, then judge it with the buttons:

   ```sh
   opscout run standup --force --config <config>
   ```

7. After merge: schedule it before the standup for a week; record the deliveries and the
   agreement rate (`opscout daemon runs standup`) in PLAN.md.
