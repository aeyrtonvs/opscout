# Quickstart: validate spec 011

Prerequisites: a clone, `uv sync`, and Claude Code. Every step except the last runs with no
AWS account.

## 1. The surface check and the contract tests

```sh
uv run pytest -m spec tests/unit/mcp -q
uv run just check
```

Expected:

- every tool's declared actions pass the surface check (FR-006);
- the planted tools that declare a write, a secret read or a plaintext-secret read fail
  with the tool and the action named;
- coverage stays 100 % on core and services.

## 2. The identity still passes

```sh
uv run opscout identity check
```

Expected: `Pass.`. Reads are 45/45 allowed, and the reference read-only identity has 9
policies (research R4).

## 3. The server starts with no configuration

```sh
uv run pytest tests/unit/mcp/test_plugin.py tests/unit/mcp/test_server.py -q
```

Expected:

- the command in `plugins/opscout/.mcp.json` starts the server through the launcher, and it
  lists the nine tools within 2 seconds of launch;
- with no configuration, `parse_alert` returns `not-configured`, and `list_environments`
  returns an empty list;
- listing does not load boto3.

## 4. Mock mode

```sh
uv run opscout mcp --mock evals/mcp/aws   # started by the test helper, not by hand
uv run pytest tests/unit/mcp/test_mock.py -q
```

Expected:

- every tool answers from `evals/mcp/aws/`, with no network access (the tests block
  sockets);
- a call with no fixture returns `fixture-missing` with the file and parameters named.

## 5. In Claude Code

```sh
claude --plugin-dir plugins/opscout
```

Then run `/mcp`: `opscout` is connected, with nine tools. Ask Claude to parse a pasted alert
in the configured format; the answer uses the private configuration's formats, which shows
that `${user_config.config_dir}` reached the server. Record the result in research R10.

## 6. Live, once (manual; not a gate)

With one environment configured in the private configuration and a valid login, ask Claude
to use the tools in turn:

- read an alarm;
- read its metric for the last 3 hours;
- run a log query over one log group for the last 15 minutes;
- list the last 24 hours of changes;
- describe one ECS service.

Expected: each result names the environment and the identity kind. Record the outcome in
the spec's Actuals (SC-006).
