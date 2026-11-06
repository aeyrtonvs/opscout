# SPDX-License-Identifier: Apache-2.0
"""``opscout mcp``: the read-only tool server, over stdio (spec 011, ADR-0011).

The composition root for the tools: it builds the MCP server, one function per registered
tool with typed inputs, and wires the configuration, the AWS gateway and the call log. The
gateway is built on the first cloud call, so listing tools never loads the AWS SDK
(SC-002). Every call returns the same envelope, and a failure is a structured error.
"""

import json
import os
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal

import platformdirs
from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, TextContent
from pydantic import BaseModel, Field

from opscout import __version__
from opscout.core.aws import AwsGateway, CallLog
from opscout.core.config import ConfigLocationError, Configuration
from opscout.core.triage import EvidenceStore, FileReader, TriageStore
from opscout.entrypoints.config import load_config
from opscout.services.config import ENV_VAR, resolve_config_dir
from opscout.services.tools.registry import SPECS
from opscout.services.tools.runtime import ConfigLoader, ToolContext, run_tool

INSTRUCTIONS = (
    "Read-only tools for investigating alerts in the environments configured in opscout. "
    "Every result states its environment, the kind of identity it used, its timezone, and "
    "what was capped or redacted. No tool changes anything or returns a secret's value."
)

Environment = Annotated[str, Field(description="A configured environment's name or alias.")]
Region = Annotated[
    str | None, Field(description="A region of the environment; default: its first region.")
]
Since = Annotated[str | None, Field(description="The window's start, ISO 8601 with an offset.")]
Until = Annotated[
    str | None, Field(description="The window's end, ISO 8601 with an offset; default: now.")
]
Last = Annotated[
    str | None, Field(description="The window as a length back from its end: 15m, 3h or 2d.")
]


class ToolResult(BaseModel):
    """What every opscout tool returns (contracts/tools.md)."""

    environment: str | None = Field(description="The environment read, if any.")
    identity: str | None = Field(
        description='"reference identity" or "own identity, not verified", for cloud tools.'
    )
    timezone: str = Field(description="The IANA timezone every time in the result is in.")
    window: dict[str, str] | None = Field(description="The window read, if any.")
    capped: list[dict[str, Any]] = Field(description="What each cap removed.")
    redacted: dict[str, int] = Field(description="How many values of each kind were redacted.")
    partial: bool = Field(description="True when the deadline stopped the tool early.")
    data: dict[str, Any] | None = Field(description="The tool's data; null on error.")
    error: dict[str, Any] | None = Field(
        description="The reason, message and fix when the call failed; null otherwise."
    )
    evidence: str | None = Field(
        description="This result's evidence identifier, for citing it in a triage verdict."
    )


Result = Annotated[CallToolResult, ToolResult]


def build_server(
    config_loader: ConfigLoader,
    gateway_factory: Callable[[], AwsGateway],
    call_log: CallLog,
    evidence: EvidenceStore | None = None,
    *,
    records: TriageStore | None = None,
    files: FileReader | None = None,
) -> MCPServer:
    """Build the server with every registered tool (FR-002, FR-003)."""
    context = ToolContext(
        config_loader=config_loader,
        gateway_factory=gateway_factory,
        call_log=call_log,
        evidence=evidence,
        records=records,
        files=files,
        engine_version=__version__,
    )
    server = MCPServer("opscout", instructions=INSTRUCTIONS)

    def respond(tool: str, /, **arguments: Any) -> CallToolResult:
        failed, result = run_tool(tool, arguments, context)
        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(result, ensure_ascii=False))],
            structured_content=result,
            is_error=failed,
        )

    def list_environments() -> Result:
        return respond("list_environments")

    def parse_alert(
        text: Annotated[str, Field(description="The alert's text, as received.")],
    ) -> Result:
        return respond("parse_alert", text=text)

    def resolve_environment(
        fields: Annotated[
            dict[str, str] | None,
            Field(description="Parsed alert fields, such as account, environment or project."),
        ] = None,
        text: Annotated[
            str | None, Field(description="Free text that names an account or environment.")
        ] = None,
    ) -> Result:
        return respond("resolve_environment", fields=fields, text=text)

    def read_alarm(
        environment: Environment,
        name: Annotated[str, Field(description="The alarm's name.")],
        since: Since = None,
        until: Until = None,
        last: Last = None,
        region: Region = None,
    ) -> Result:
        return respond(
            "read_alarm",
            environment=environment,
            name=name,
            since=since,
            until=until,
            last=last,
            region=region,
        )

    def read_metric(
        environment: Environment,
        namespace: Annotated[str, Field(description="The metric's namespace, e.g. AWS/ECS.")],
        metric: Annotated[str, Field(description="The metric's name.")],
        dimensions: Annotated[
            dict[str, str] | None, Field(description="The metric's dimensions, by name.")
        ] = None,
        statistic: Annotated[
            str, Field(description="Average, Sum, Minimum, Maximum, SampleCount or p99 and such.")
        ] = "Average",
        period: Annotated[int, Field(description="The period in seconds, a multiple of 60.")] = 300,
        since: Since = None,
        until: Until = None,
        last: Last = None,
        region: Region = None,
    ) -> Result:
        return respond(
            "read_metric",
            environment=environment,
            namespace=namespace,
            metric=metric,
            dimensions=dimensions,
            statistic=statistic,
            period=period,
            since=since,
            until=until,
            last=last,
            region=region,
        )

    def query_logs(
        environment: Environment,
        log_groups: Annotated[list[str], Field(description="One to ten log group names.")],
        query: Annotated[str, Field(description="A CloudWatch Logs Insights query.")],
        limit: Annotated[int | None, Field(description="The most rows to return.")] = None,
        since: Since = None,
        until: Until = None,
        last: Last = None,
        region: Region = None,
    ) -> Result:
        return respond(
            "query_logs",
            environment=environment,
            log_groups=log_groups,
            query=query,
            limit=limit,
            since=since,
            until=until,
            last=last,
            region=region,
        )

    def recent_changes(
        environment: Environment,
        resource_type: Annotated[
            str | None, Field(description="Narrow to a resource of this type.")
        ] = None,
        resource: Annotated[
            str | None, Field(description="Narrow to the resource with this name or ARN.")
        ] = None,
        since: Since = None,
        until: Until = None,
        last: Last = None,
        region: Region = None,
        include_background: Annotated[
            bool,
            Field(description="Keep agent heartbeats, which are dropped by default (spec 012)."),
        ] = False,
    ) -> Result:
        return respond(
            "recent_changes",
            environment=environment,
            resource_type=resource_type,
            resource=resource,
            since=since,
            until=until,
            last=last,
            region=region,
            include_background=include_background,
        )

    def find_resources(
        environment: Environment,
        name: Annotated[
            str | None, Field(description="Part of the resource's Name tag or ARN.")
        ] = None,
        tag_key: Annotated[str | None, Field(description="A tag key the resource has.")] = None,
        tag_value: Annotated[str | None, Field(description="That tag's value.")] = None,
        type: Annotated[str | None, Field(description="One of describe_resource's types.")] = None,
        region: Region = None,
    ) -> Result:
        return respond(
            "find_resources",
            environment=environment,
            name=name,
            tag_key=tag_key,
            tag_value=tag_value,
            type=type,
            region=region,
        )

    def describe_resource(
        environment: Environment,
        type: Annotated[
            str,
            Field(
                description=(
                    "ecs-service, rds-instance, rds-cluster, ec2-instance, load-balancer, "
                    "target-group, autoscaling-group, alarm or lambda-function."
                )
            ),
        ],
        name: Annotated[str, Field(description="The resource's name, ID or ARN.")],
        region: Region = None,
    ) -> Result:
        return respond(
            "describe_resource", environment=environment, type=type, name=name, region=region
        )

    def begin_triage(
        text: Annotated[str, Field(description="The alert's text, as pasted.", max_length=20_000)],
        alert_time: Annotated[
            str | None,
            Field(description="The time the user named, ISO 8601 with an offset."),
        ] = None,
    ) -> Result:
        return respond("begin_triage", text=text, alert_time=alert_time)

    def check_verdict(
        run_id: Annotated[str, Field(description="The run id begin_triage returned.")],
        verdict: Annotated[
            dict[str, Any],
            Field(description="The verdict, as the skill's verdict reference defines it."),
        ],
    ) -> Result:
        return respond("check_verdict", run_id=run_id, verdict=verdict)

    def record_agreement(
        run_id: Annotated[str, Field(description="The run id.")],
        answer: Annotated[
            Literal["agree", "disagree", "not-answered"], Field(description="The user's answer.")
        ],
        reason: Annotated[
            str | None, Field(description="The user's reason, if given.", max_length=500)
        ] = None,
    ) -> Result:
        return respond("record_agreement", run_id=run_id, answer=answer, reason=reason)

    def show_evidence(
        ids: Annotated[
            list[str], Field(description="Evidence ids, 1 to 20.", min_length=1, max_length=20)
        ],
    ) -> Result:
        return respond("show_evidence", ids=ids)

    def search_iac(
        pattern: Annotated[
            str,
            Field(
                description="A literal, matched case-insensitively.", min_length=2, max_length=200
            ),
        ],
        environment: Annotated[
            str | None, Field(description="Search this environment's clones first.")
        ] = None,
        clone: Annotated[str | None, Field(description="Search only this clone.")] = None,
    ) -> Result:
        return respond("search_iac", pattern=pattern, environment=environment, clone=clone)

    def read_iac(
        path: Annotated[str, Field(description="<clone>/<path inside the clone>.")],
        start: Annotated[int, Field(description="The first line, from 1.", ge=1)],
        end: Annotated[int, Field(description="The last line; at most start + 199.", ge=1)],
    ) -> Result:
        return respond("read_iac", path=path, start=start, end=end)

    functions = (
        list_environments,
        parse_alert,
        resolve_environment,
        read_alarm,
        read_metric,
        query_logs,
        recent_changes,
        find_resources,
        describe_resource,
        begin_triage,
        check_verdict,
        record_agreement,
        show_evidence,
        search_iac,
        read_iac,
    )
    for function in functions:
        server.add_tool(
            function,
            name=function.__name__,
            description=SPECS[function.__name__].description,
            structured_output=True,
        )
    return server


def config_loader(flag: Path | None, environ: dict[str, str]) -> ConfigLoader:
    """Load the configuration on every call: None when there is none (FR-002).

    An unsubstituted ``${user_config.…}`` in ``OPSCOUT_CONFIG`` counts as absent (R10).
    """
    if environ.get(ENV_VAR, "").startswith("${user_config."):
        environ = {key: value for key, value in environ.items() if key != ENV_VAR}
    location = resolve_config_dir(flag, environ, Path.home())

    def load() -> Configuration | None:
        try:
            return load_config(location.directory)
        except ConfigLocationError:
            return None

    return load


DATA_ENV = "OPSCOUT_DATA_DIR"
MOCK_ENV = "OPSCOUT_MCP_MOCK"
EVIDENCE_HOURS = 24


def data_directory(environ: Mapping[str, str]) -> Path:
    """``OPSCOUT_DATA_DIR``, else the platform data directory (spec 012, research R2)."""
    given = environ.get(DATA_ENV, "")
    if given and not given.startswith("${"):
        return Path(given)
    return Path(platformdirs.user_data_dir("opscout", appauthor=False))


def serve(flag: Path | None, mock: Path | None) -> int:
    """Run ``opscout mcp [--mock DIR]`` until the client closes stdin."""
    from opscout.adapters.call_log import JsonlCallLog
    from opscout.adapters.evidence_files import FileEvidence
    from opscout.adapters.triage_files import FileRecords

    environ = dict(os.environ)
    if mock is None and environ.get(MOCK_ENV):
        mock = Path(environ[MOCK_ENV])
    data = data_directory(environ)
    evidence = FileEvidence(data)
    evidence.prune(datetime.now(UTC) - timedelta(hours=EVIDENCE_HOURS))

    def gateway() -> AwsGateway:
        if mock is not None:
            from opscout.adapters.aws_fixtures import FixtureGateway

            return FixtureGateway(mock)
        from opscout.adapters.aws_live import LiveGateway

        return LiveGateway()

    server = build_server(
        config_loader(flag, environ),
        gateway,
        JsonlCallLog(),
        evidence,
        records=FileRecords(data),
    )
    server.run("stdio")
    return 0
