# Quickstart: validate chat output

1. Tests and gates (any OS; no test contacts Slack):

   ```sh
   uv run just test tests/unit/chat
   uv run just check
   ```

2. Create the app (the user, in Slack): **Create New App → From a manifest**, paste
   `deploy/slack/opscout-app-manifest.yaml`, install it in the workspace; under **Basic
   Information → App-Level Tokens** create a token with `connections:write`. Copy your own
   member id from your Slack profile (**⋮ → Copy member ID**).

3. Store the tokens (the user types them; they are not shown):

   ```sh
   opscout secret set slack_bot_token --config <config>   # xoxb-…
   opscout secret set slack_app_token --config <config>   # xapp-…
   opscout secret check --config <config>
   ```

   with `daemon.chat` (`service: slack`, `user: <member id>`) and both secrets in the
   configuration (a temporary copy of `example-config` for this check).

4. A manual run delivers by DM:

   ```sh
   opscout run check --force --config <config>   # delivered to <outbox file>; a DM arrives
   ```

5. Install the gateway and a scheduled `check` two minutes ahead; confirm with the code:

   ```sh
   opscout daemon install --dry-run --config <config>
   opscout daemon install --confirm <code> --config <config>
   opscout daemon status --config <config>       # gateway connected
   ```

   The scheduled run's DM arrives (SC-001). Click **Agree**: the record holds it
   (`opscout daemon runs check`, then read the record), and the message shows the choice
   (SC-002). Click **Disagree**, give a reason; the record holds both.

6. Turn Wi-Fi off and on; within a minute status shows the gateway connected again (SC-006).

7. Clean up: `opscout daemon uninstall --dry-run`, then `--confirm <code>`. The app stays
   in the workspace for the daily standup, or is removed there by hand.
